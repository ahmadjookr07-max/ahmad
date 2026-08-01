# -*- coding: utf-8 -*-
"""nutrition_v2 — حقائق التغذية: كشف الجدول، الدمج المصغر، الصورة المستقلة.

InsetPlacement: تحكم كامل بالموقع (4 زوايا + حر) والمقياس والإطار.

سياسة الجودة (2.4): الدمج داخل صورة الصنف هو الوضع الافتراضي المعتمد.
لكي تبقى كتابات الجدول مقروءة تمامًا بعد الدمج، لا يُصغَّر الملصق قسرًا
إلى نسبة من صورة الصنف؛ بل **تتوسّع لوحة صورة الصنف** (بترقية دقتها) حتى
يجلس الملصق بدقته الأصلية أو قريبًا منها. هذا يعكس مصدر المشكلة الأصلي:
كان الجدول يفقد مقروئيته لأنه يُضغط في 28% من عرض صورة 800×700.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .enhancement_v2 import enhance_nutrition_label

ANCHORS = ("bottom_left", "bottom_right", "top_left", "top_right", "free")

#: أقل عرض بالبكسل يبقى معه جدول الحقائق مقروءًا بوضوح على الشاشة والطباعة.
#: مقيس تجريبيًا على جداول حقائق حقيقية (سطور بحجم 0.4 من ارتفاع 2000px).
MIN_READABLE_LABEL_WIDTH = 520


@dataclass
class InsetPlacement:
    anchor: str = "bottom_right"    # أحد ANCHORS — الافتراضي: أسفل يمين
    offset_x: int = 0               # إزاحة إضافية بالبكسل (أو موضع حر)
    offset_y: int = 0
    scale: float = 0.34             # نسبة عرض الملصق من عرض الصورة 0.12-0.6
    border: int = 2                 # سماكة إطار رمادي
    margin: int = 14                # هامش من الحواف
    #: يمنع تصغير الملصق تحت حد المقروئية عبر توسيع لوحة صورة الصنف.
    preserve_label_pixels: bool = True
    #: أقصى معامل توسيع مسموح للوحة صورة الصنف (حماية من ملفات ضخمة).
    #: مقيس رقميًا: 4× يكفي لوصول بكسلات الجدول 100% عند المقياس
    #: الافتراضي 0.34 (3× كان يتوقف عند 87%، أي تصغير مدمر للنص).
    max_canvas_upscale: float = 4.0
    #: خلفية بيضاء خلف الملصق (بطاقة) لفصله عن صورة المنتج.
    label_card: bool = True

    def clamp(self) -> "InsetPlacement":
        self.scale = float(min(0.6, max(0.12, self.scale)))
        if self.anchor not in ANCHORS:
            self.anchor = "bottom_right"
        self.max_canvas_upscale = float(min(8.0, max(1.0,
                                                     self.max_canvas_upscale)))
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
    else:  # bottom_left
        x = m + placement.offset_x
        y = canvas_h - label_h - m + placement.offset_y
    x = max(0, min(canvas_w - label_w, x))
    y = max(0, min(canvas_h - label_h, y))
    return x, y


def _target_label_width(canvas_w: int, canvas_h: int, label_w: int,
                        label_h: int,
                        p: InsetPlacement) -> tuple[int, int, float]:
    """يحسب (عرض اللوحة، ارتفاع اللوحة، عرض الملصق) بعد ضمان المقروئية.

    المنطق: العرض المطلوب للملصق = scale × عرض اللوحة. إذا كان هذا العرض
    أصغر من دقة الملصق الأصلية (أي سنضطر لتصغيره وفقدان النص)، نوسّع لوحة
    صورة الصنف بالمعامل اللازم — بحد أقصى max_canvas_upscale — حتى يجلس
    الملصق بدقته الكاملة. النتيجة: صفر تصغير للنص في الحالة الشائعة.
    """
    want = canvas_w * p.scale
    if not p.preserve_label_pixels:
        return canvas_w, canvas_h, want
    # العرض المطلوب للملصق: دقته الأصلية كاملة، ولا يُطلب أكثر
    # مما يوجد فعلًا (لا تكبير مصطنع يضخم الملف بلا فائدة).
    # مهم: البطاقة البيضاء (pad ≈ 2% من العرض) والإطار يستهلكان جزءًا من
    # العرض المخصص، فلو حسبنا الحاجة على عرض الملصق وحده لخسرنا ~10% من
    # بكسلات النص. نضيف تلك الهوامش إلى الحاجة ليجلس النص بدقة 100%.
    need = float(label_w)
    if p.label_card:
        need = need / max(0.5, 1.0 - 2 * 0.02)     # هامش البطاقة 2% لكل جهة
    if p.border > 0:
        need += 2 * p.border
    if want >= need:
        return canvas_w, canvas_h, want
    factor = min(p.max_canvas_upscale, need / max(1.0, want))
    new_w = int(round(canvas_w * factor))
    new_h = int(round(canvas_h * factor))
    return new_w, new_h, new_w * p.scale


def merge_label_inset(product_img: np.ndarray, label_img: np.ndarray,
                      placement: InsetPlacement | None = None,
                      enhance: bool = True) -> np.ndarray:
    """يدمج جدول حقائق التغذية داخل صورة المنتج نفسها بجودة كاملة.

    الوضع المعتمد افتراضيًا: أسفل يمين. لا يُصغَّر الملصق تحت حد المقروئية؛
    إذا لزم، تُرقّى لوحة صورة الصنف (LANCZOS4) ليجلس الملصق بدقته.
    """
    p = (placement or InsetPlacement()).clamp()
    out = product_img.copy()
    if enhance:
        label_img = enhance_nutrition_label(label_img)
    lh0, lw0 = label_img.shape[:2]
    H, W = out.shape[:2]

    new_w, new_h, want_w = _target_label_width(W, H, lw0, lh0, p)
    if (new_w, new_h) != (W, H):
        # ترقية لوحة صورة الصنف — LANCZOS4 يحافظ على حدة كتابات العلبة
        out = cv2.resize(out, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
        H, W = out.shape[:2]

    lw = max(24, int(round(want_w)))
    lh = int(round(lh0 * lw / max(1, lw0)))
    max_lh = int(H * 0.72)          # الجداول الطويلة تحتاج متنفسًا أعلى
    if lh > max_lh:                      # جدول طويل جدًا — قيّد بالارتفاع
        lh = max_lh
        lw = int(round(lw0 * lh / max(1, lh0)))
    interp = cv2.INTER_AREA if lw < lw0 else cv2.INTER_LANCZOS4
    label = cv2.resize(label_img, (lw, lh), interpolation=interp)

    if p.label_card:
        # بطاقة بيضاء رقيقة تفصل الجدول عن خلفية المنتج وتزيد التباين
        pad = max(4, int(lw * 0.02))
        label = cv2.copyMakeBorder(label, pad, pad, pad, pad,
                                   cv2.BORDER_CONSTANT, value=(255, 255, 255))
    if p.border > 0:
        label = cv2.copyMakeBorder(label, p.border, p.border, p.border,
                                   p.border, cv2.BORDER_CONSTANT,
                                   value=(150, 150, 150))
    lh, lw = label.shape[:2]
    if lw >= W or lh >= H:               # حماية: لا يتجاوز الملصق اللوحة
        sc = min((W - 2 * p.margin) / lw, (H - 2 * p.margin) / lh)
        lw, lh = max(8, int(lw * sc)), max(8, int(lh * sc))
        label = cv2.resize(label, (lw, lh), interpolation=cv2.INTER_AREA)
    x, y = _place(W, H, lw, lh, p)
    out[y:y + lh, x:x + lw] = label
    return out


def merge_stats(product_img: np.ndarray, label_img: np.ndarray,
                placement: InsetPlacement | None = None) -> dict:
    """يعيد أرقام الدمج المتوقعة (للعرض في الواجهة قبل الحفظ)."""
    p = (placement or InsetPlacement()).clamp()
    lh0, lw0 = label_img.shape[:2]
    H, W = product_img.shape[:2]
    new_w, new_h, want_w = _target_label_width(W, H, lw0, lh0, p)
    # العرض الفعلي المتاح لبكسلات الجدول بعد خصم البطاقة والإطار
    inner = want_w
    if p.border > 0:
        inner -= 2 * p.border
    if p.label_card:
        inner = inner * (1.0 - 2 * 0.02)
    kept = min(1.0, inner / max(1.0, lw0))
    return {
        "canvas": (int(new_w), int(new_h)),
        "canvas_upscaled": (new_w, new_h) != (W, H),
        "label_source": (int(lw0), int(lh0)),
        "label_placed_width": int(round(want_w)),
        "label_pixel_ratio": round(kept, 3),
    }


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
