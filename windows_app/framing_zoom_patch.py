# -*- coding: utf-8 -*-
"""تأطير المنتج: تقريب آمن وتمركز وحفظ موضع المستخدم.

يُستخدم بعد العزل فقط. لا يغير البكسلات داخل المنتج ولا يقصّه: يُحسب
أقصى تقريب من حدود القناع ثم تُضبط نافذة العرض حول مركز الكتلة الفعلي.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

__all__ = [
    "ProductFrame", "DEFAULT_AUTO_FRAME", "frame_product", "save_framed_image",
    "install_final_framing_patch",
]


@dataclass(frozen=True)
class ProductFrame:
    """إعداد تقريب المنتج وموضعه؛ القيم بالنسب المئوية من اللوحة."""

    zoom_percent: int = 106
    offset_x_percent: int = 0
    offset_y_percent: int = 0

    def normalized(self) -> "ProductFrame":
        return ProductFrame(
            zoom_percent=max(100, min(130, int(self.zoom_percent))),
            offset_x_percent=max(-20, min(20, int(self.offset_x_percent))),
            offset_y_percent=max(-20, min(20, int(self.offset_y_percent))),
        )


# تقريب افتراضي متحفظ: يزيد حضور المنتج 6% فقط، ولا يقطع الحواف.
DEFAULT_AUTO_FRAME = ProductFrame()


def _foreground_mask(image: np.ndarray) -> np.ndarray:
    """قناع المنتج من اللوحة البيضاء، مع استبعاد الضجيج الضعيف."""
    if image is None or image.size == 0:
        return np.zeros((1, 1), np.uint8)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    mask = np.where(gray < 246, 255, 0).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if count <= 1:
        return mask
    areas = stats[1:, cv2.CC_STAT_AREA]
    largest = 1 + int(np.argmax(areas))
    # لا نرمي الظل الهادئ المتصل بالمنتج؛ نزيل فقط البقع المنفصلة.
    return np.where(labels == largest, 255, 0).astype(np.uint8)


def _crop_window(mask: np.ndarray, frame: ProductFrame) -> tuple[int, int, int, int]:
    """نافذة تكبير آمنة: تضمن بقاء كامل المنتج وهامش صغير حوله."""
    h, w = mask.shape[:2]
    points = cv2.findNonZero(mask)
    if points is None:
        return 0, 0, w, h
    x, y, bw, bh = cv2.boundingRect(points)
    pad = max(4, int(round(min(w, h) * 0.015)))
    left_required = max(0, x - pad)
    top_required = max(0, y - pad)
    right_required = min(w, x + bw + pad)
    bottom_required = min(h, y + bh + pad)

    f = frame.normalized()
    wanted_zoom = f.zoom_percent / 100.0
    required_w = max(1, right_required - left_required)
    required_h = max(1, bottom_required - top_required)
    safe_zoom = min(w / required_w, h / required_h)
    zoom = max(1.0, min(wanted_zoom, safe_zoom))
    crop_w = max(required_w, min(w, int(round(w / zoom))))
    crop_h = max(required_h, min(h, int(round(h / zoom))))

    # مركز المنتج الفعلي، ثم إزاحة مستخدم محدودة؛ نقيّد النافذة كي لا تقص المنتج.
    moments = cv2.moments(mask, binaryImage=True)
    cx = (moments["m10"] / moments["m00"]) if moments["m00"] else (x + bw / 2)
    cy = (moments["m01"] / moments["m00"]) if moments["m00"] else (y + bh / 2)
    cx += f.offset_x_percent * w * 0.01
    cy += f.offset_y_percent * h * 0.01

    desired_left = int(round(cx - crop_w / 2))
    desired_top = int(round(cy - crop_h / 2))
    lower_left = max(0, right_required - crop_w)
    upper_left = min(w - crop_w, left_required)
    lower_top = max(0, bottom_required - crop_h)
    upper_top = min(h - crop_h, top_required)
    left = max(lower_left, min(upper_left, desired_left))
    top = max(lower_top, min(upper_top, desired_top))
    return left, top, crop_w, crop_h


def frame_product(image: np.ndarray, frame: ProductFrame = DEFAULT_AUTO_FRAME) -> np.ndarray:
    """يكبّر المنتج ويعيده إلى لوحة بنفس الأبعاد، مركزًا أو بإزاحة محفوظة.

    لا نقصّ نافذة من الصورة حين يكون المنتج قريبًا من طرفها؛ ذلك يمنع
    التمركز الحقيقي. بدلاً منه نكبر اللوحة ثم نزيحها على خلفية بيضاء حتى
    يصبح مركز المنتج في الموضع المطلوب مع إبقاء كامل حدوده داخل الإطار.
    """
    if image is None or image.size == 0:
        return image
    mask = _foreground_mask(image)
    points = cv2.findNonZero(mask)
    if points is None or cv2.countNonZero(mask) < 64:
        return image
    h, w = image.shape[:2]
    x, y, bw, bh = cv2.boundingRect(points)
    moments = cv2.moments(mask, binaryImage=True)
    cx = (moments["m10"] / moments["m00"]) if moments["m00"] else (x + bw / 2)
    cy = (moments["m01"] / moments["m00"]) if moments["m00"] else (y + bh / 2)
    f = frame.normalized()
    requested = f.zoom_percent / 100.0
    # هامش صغير ثابت حول كامل المنتج؛ لا نتجاوز أكبر تقريب آمن.
    pad = max(3, int(round(min(w, h) * 0.012)))
    safe_scale = min((w - 2 * pad) / max(1, bw), (h - 2 * pad) / max(1, bh))
    scale = max(1.0, min(requested, safe_scale))
    target_x = w / 2.0 + f.offset_x_percent * w * 0.01
    target_y = h / 2.0 + f.offset_y_percent * h * 0.01
    # لا تسمح الإزاحة بقص المنتج بعد التكبير.
    min_x = pad + (bw * scale) / 2.0
    max_x = w - pad - (bw * scale) / 2.0
    min_y = pad + (bh * scale) / 2.0
    max_y = h - pad - (bh * scale) / 2.0
    target_x = max(min_x, min(max_x, target_x))
    target_y = max(min_y, min(max_y, target_y))
    matrix = np.float32(((scale, 0.0, target_x - cx * scale),
                         (0.0, scale, target_y - cy * scale)))
    return cv2.warpAffine(image, matrix, (w, h), flags=cv2.INTER_LANCZOS4,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))


def save_framed_image(path: str | Path, frame: ProductFrame) -> bool:
    """يطبق التأطير ويحفظ فوق نفس ملف الصنف كتابةً ذرية بلا صورة مكررة."""
    target = Path(path)
    image = cv2.imread(str(target), cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        return False
    result = frame_product(image, frame)
    if result is image:
        return True
    temp = target.with_name(f".{target.stem}.frame.tmp{target.suffix}")
    ext = target.suffix.lower() or ".webp"
    if ext == ".webp":
        params = [cv2.IMWRITE_WEBP_QUALITY, 101]
    elif ext in (".jpg", ".jpeg"):
        params = [cv2.IMWRITE_JPEG_QUALITY, 100]
    else:
        params = [cv2.IMWRITE_PNG_COMPRESSION, 3]
    try:
        ok, encoded = cv2.imencode(ext, result, params)
        if not ok:
            return False
        encoded.tofile(str(temp))
        temp.replace(target)
        return True
    except Exception:
        try:
            temp.unlink(missing_ok=True)
        except Exception:
            pass
        return False


def install_final_framing_patch(final_module: Any) -> bool:
    """يرقّع المعالج المصرّف بعد تحميله؛ التمركز موجود داخله ونضيف تقريبًا خفيفًا."""
    processor = getattr(final_module, "FinalImageProcessor", None)
    if processor is None or getattr(processor, "_mis_framing_zoom_patched", False):
        return processor is not None
    original = getattr(processor, "_compose", None)
    if not callable(original):
        return False

    def composed(self: Any, image: np.ndarray, mask: np.ndarray,
                 remove_background: bool) -> np.ndarray:
        output = original(self, image, mask, remove_background)
        # لا نغير صور الدفعة التي اختار مالكها عدم العزل.
        if not remove_background:
            return output
        try:
            custom = getattr(self, "_mis_product_frame", DEFAULT_AUTO_FRAME)
            if not isinstance(custom, ProductFrame):
                custom = DEFAULT_AUTO_FRAME
            return frame_product(output, custom)
        except Exception:
            return output

    composed._mis_framing_zoom_patched = True
    processor._compose = composed
    processor._mis_framing_zoom_patched = True
    return True
