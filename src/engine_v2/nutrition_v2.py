# -*- coding: utf-8 -*-
"""nutrition_v2 — حقائق التغذية: كشف الجدول، الدمج المصغر، الصورة المستقلة.

InsetPlacement: تحكم كامل بالموقع (4 زوايا + حر) والمقياس والإطار.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .enhancement_v2 import enhance_nutrition_label

ANCHORS = ("bottom_left", "bottom_right", "top_left", "top_right", "free")


@dataclass
class InsetPlacement:
    anchor: str = "bottom_left"     # أحد ANCHORS
    offset_x: int = 0               # إزاحة إضافية بالبكسل (أو موضع حر)
    offset_y: int = 0
    scale: float = 0.28             # نسبة عرض الملصق من عرض الصورة 0.12-0.6
    border: int = 2                 # سماكة إطار رمادي
    margin: int = 14                # هامش من الحواف

    def clamp(self) -> "InsetPlacement":
        self.scale = float(min(0.6, max(0.12, self.scale)))
        if self.anchor not in ANCHORS:
            self.anchor = "bottom_left"
        return self


def detect_nutrition_table(img: np.ndarray) -> tuple[int, int, int, int] | None:
    """يكشف مستطيل جدول حقائق التغذية عبر بنية الخطوط الشبكية.

    يعيد (x, y, w, h) أو None.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    h, w = gray.shape
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                   cv2.THRESH_BINARY_INV, 25, 12)
    hk = max(20, w // 18)
    vk = max(20, h // 18)
    horiz = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
                             cv2.getStructuringElement(cv2.MORPH_RECT, (hk, 1)))
    vert = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (1, vk)))
    grid = cv2.add(horiz, vert)
    grid = cv2.dilate(grid, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(grid, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_score = 0.0
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        area = cw * ch
        if area < (w * h) * 0.02:
            continue
        aspect = ch / max(1, cw)
        if not 0.5 <= aspect <= 4.0:
            continue
        roi = binary[y:y + ch, x:x + cw]
        density = float(roi.mean()) / 255.0
        score = area * (0.5 + density)
        if score > best_score:
            best_score = score
            best = (x, y, cw, ch)
    return best


def crop_region(img: np.ndarray, box: tuple[int, int, int, int],
                pad: int = 6) -> np.ndarray:
    x, y, w, h = box
    H, W = img.shape[:2]
    x0 = max(0, x - pad)
    y0 = max(0, y - pad)
    x1 = min(W, x + w + pad)
    y1 = min(H, y + h + pad)
    return img[y0:y1, x0:x1].copy()


def _place(canvas_w: int, canvas_h: int, label_w: int, label_h: int,
           placement: InsetPlacement) -> tuple[int, int]:
    m = placement.margin
    a = placement.anchor
    if a == "free":
        x = placement.offset_x
        y = placement.offset_y
    elif a == "bottom_right":
        x = canvas_w - label_w - m + placement.offset_x
        y = canvas_h - label_h - m + placement.offset_y
    elif a == "top_left":
        x = m + placement.offset_x
        y = m + placement.offset_y
    elif a == "top_right":
        x = canvas_w - label_w - m + placement.offset_x
        y = m + placement.offset_y
    else:  # bottom_left (افتراضي)
        x = m + placement.offset_x
        y = canvas_h - label_h - m + placement.offset_y
    x = max(0, min(canvas_w - label_w, x))
    y = max(0, min(canvas_h - label_h, y))
    return x, y


def merge_label_inset(product_img: np.ndarray, label_img: np.ndarray,
                      placement: InsetPlacement | None = None,
                      enhance: bool = True) -> np.ndarray:
    """يدمج ملصق حقائق التغذية كصورة مصغرة على صورة المنتج النهائية."""
    p = (placement or InsetPlacement()).clamp()
    out = product_img.copy()
    H, W = out.shape[:2]
    if enhance:
        label_img = enhance_nutrition_label(label_img)
    lw = int(W * p.scale)
    lh = int(label_img.shape[0] * lw / max(1, label_img.shape[1]))
    lh = min(lh, int(H * 0.6))
    label = cv2.resize(label_img, (lw, lh), interpolation=cv2.INTER_AREA)
    if p.border > 0:
        label = cv2.copyMakeBorder(label, p.border, p.border, p.border,
                                   p.border, cv2.BORDER_CONSTANT,
                                   value=(150, 150, 150))
        lh, lw = label.shape[:2]
    x, y = _place(W, H, lw, lh, p)
    out[y:y + lh, x:x + lw] = label
    return out


def render_standalone_label(label_img: np.ndarray,
                            canvas_w: int = 800, canvas_h: int = 700,
                            align: str = "center",
                            enhance: bool = True,
                            hq: bool = True) -> np.ndarray:
    """يرسم ملصق حقائق التغذية منفردًا على لوحة بيضاء.

    وضع hq (افتراضي منذ 2.3): لا يُصغّر الملصق أبدًا — إذا كانت دقة
    الملصق المقتص من الصورة الأصلية أعلى من اللوحة المطلوبة تتوسع اللوحة
    لتحافظ على كامل التفاصيل، والملصقات الصغيرة تُكبّر بـ LANCZOS4
    لتملأ اللوحة بوضوح أعلى — تصلح للاستخدام كصورة مستقلة للصنف."""
    if enhance:
        label_img = enhance_nutrition_label(label_img)
    lh, lw = label_img.shape[:2]
    margin = 30
    if hq:
        # وسّع اللوحة بدل تصغير ملصق عالي الدقة (حتى 3× المقاس المطلوب)
        needed_w = lw + 2 * margin
        needed_h = lh + 2 * margin
        if needed_w > canvas_w or needed_h > canvas_h:
            ratio = min(3.0, max(needed_w / canvas_w, needed_h / canvas_h))
            canvas_w = int(canvas_w * ratio)
            canvas_h = int(canvas_h * ratio)
    sc = min((canvas_w - 2 * margin) / lw, (canvas_h - 2 * margin) / lh)
    nw, nh = int(lw * sc), int(lh * sc)
    label = cv2.resize(label_img, (nw, nh),
                       interpolation=cv2.INTER_AREA if sc < 1
                       else cv2.INTER_LANCZOS4)
    canvas = np.full((canvas_h, canvas_w, 3), 255, np.uint8)
    if align == "left":
        x = margin
    elif align == "right":
        x = canvas_w - nw - margin
    else:
        x = (canvas_w - nw) // 2
    if align == "top":
        y = margin
    elif align == "bottom":
        y = canvas_h - nh - margin
    else:
        y = (canvas_h - nh) // 2
    canvas[y:y + nh, x:x + nw] = label
    return canvas
