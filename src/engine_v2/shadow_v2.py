# -*- coding: utf-8 -*-
"""shadow_v2 — توليد ظل واقعي قريب من 3D لصور المنتجات.

يولّد نوعين من الظلال من قناع alpha الخاص بالمنتج:
1. Contact shadow (ظل التلامس الأرضي): شكل بيضاوي ناعم تحت قاعدة المنتج
   يعطي إحساس أن المنتج "واقف" على سطح — أساس المظهر ثلاثي الأبعاد.
2. Drop shadow (الظل المسقط المنظوري): نسخة من silhouette المنتج مُمالة
   ومضغوطة عموديًا باتجاه الإضاءة مع ضبابية وتدرج شفافية (أقرب للمنتج
   أغمق، أبعد أفتح) — يحاكي إسقاط إضاءة استوديو حقيقية.

الاستخدام:
    opts = ShadowOptions(kind="contact", opacity=0.35, blur=25)
    result = apply_shadow(rgba_image, opts)  # RGBA فيها الظل تحت المنتج
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional, Tuple

import numpy as np
import cv2


@dataclass
class ShadowOptions:
    """خيارات الظل الواقعي."""

    kind: str = "contact"           # contact | drop | both | none
    opacity: float = 0.38           # 0..1 شدة الظل
    blur: int = 21                  # نصف قطر الضبابية (بكسل على مقياس 1000px)
    # ظل التلامس
    contact_height_ratio: float = 0.10   # ارتفاع البيضاوي نسبة لعرض المنتج
    contact_width_ratio: float = 1.02    # عرض البيضاوي نسبة لعرض قاعدة المنتج
    contact_offset_y: int = 0            # إزاحة عمودية إضافية
    # الظل المسقط
    drop_angle_deg: float = 35.0    # زاوية اتجاه الظل (0 = يمين، 90 = أسفل)
    drop_length_ratio: float = 0.55 # طول الظل نسبة لارتفاع المنتج
    drop_squash: float = 0.35       # ضغط عمودي (كلما قلّ صار الظل أكثر أفقية/أرضية)
    drop_fade: float = 0.85         # قوة تلاشي الظل مع البعد (0=بلا تلاشي، 1=قوي)
    # عام
    color: Tuple[int, int, int] = (30, 30, 34)  # لون الظل (رمادي مائل للدفء الخفيف)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["color"] = list(self.color)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ShadowOptions":
        d = dict(d or {})
        if "color" in d and isinstance(d["color"], (list, tuple)):
            d["color"] = tuple(int(c) for c in d["color"])[:3]
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


def _ensure_rgba(img: np.ndarray) -> np.ndarray:
    if img is None:
        raise ValueError("image is None")
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    elif img.shape[2] == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
        img[:, :, 3] = 255
    return img


def _alpha_bbox(alpha: np.ndarray, thr: int = 10) -> Optional[Tuple[int, int, int, int]]:
    ys, xs = np.where(alpha > thr)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def _scaled_blur(blur: int, width: int) -> int:
    """تكييف الضبابية مع حجم الصورة (المعايرة على عرض 1000px)."""
    k = max(3, int(round(blur * width / 1000.0)))
    if k % 2 == 0:
        k += 1
    return k


def _base_profile(alpha: np.ndarray, x0: int, x1: int, y1: int, band: int) -> Tuple[int, int]:
    """تقدير عرض قاعدة المنتج الفعلية من الشريط السفلي من القناع."""
    band_top = max(0, y1 - band)
    strip = alpha[band_top : y1 + 1, x0 : x1 + 1]
    cols = np.where(strip.max(axis=0) > 40)[0]
    if len(cols) == 0:
        return x0, x1
    return x0 + int(cols.min()), x0 + int(cols.max())


def make_contact_shadow(alpha: np.ndarray, opts: ShadowOptions,
                        canvas_shape: Tuple[int, int]) -> np.ndarray:
    """ظل تلامس بيضاوي ناعم تحت قاعدة المنتج. يعيد قناة شدة 0..255."""
    h, w = canvas_shape
    shadow = np.zeros((h, w), dtype=np.uint8)
    bbox = _alpha_bbox(alpha)
    if bbox is None:
        return shadow
    x0, y0, x1, y1 = bbox
    prod_w = x1 - x0 + 1
    prod_h = y1 - y0 + 1
    bx0, bx1 = _base_profile(alpha, x0, x1, y1, band=max(4, prod_h // 12))
    base_w = max(10, bx1 - bx0 + 1)

    ell_w = int(base_w * opts.contact_width_ratio)
    ell_h = max(6, int(prod_w * opts.contact_height_ratio))
    cx = (bx0 + bx1) // 2
    cy = min(h - 1, y1 + opts.contact_offset_y + ell_h // 6)

    cv2.ellipse(shadow, (cx, cy), (max(4, ell_w // 2), max(3, ell_h // 2)),
                0, 0, 360, 255, -1)

    # نواة داكنة + هالة أوسع = عمق واقعي
    core = np.zeros_like(shadow)
    cv2.ellipse(core, (cx, cy), (max(3, int(ell_w * 0.30)), max(2, int(ell_h * 0.30))),
                0, 0, 360, 255, -1)

    k1 = _scaled_blur(opts.blur, w)
    k2 = _scaled_blur(max(7, opts.blur // 2), w)
    shadow = cv2.GaussianBlur(shadow, (k1, k1), 0)
    core = cv2.GaussianBlur(core, (k2, k2), 0)
    out = np.clip(shadow.astype(np.float32) * 0.75 + core.astype(np.float32) * 0.55,
                  0, 255).astype(np.uint8)
    return out


def make_drop_shadow(alpha: np.ndarray, opts: ShadowOptions,
                     canvas_shape: Tuple[int, int]) -> np.ndarray:
    """ظل مسقط منظوري مُمال من silhouette المنتج. يعيد قناة شدة 0..255."""
    h, w = canvas_shape
    shadow = np.zeros((h, w), dtype=np.uint8)
    bbox = _alpha_bbox(alpha)
    if bbox is None:
        return shadow
    x0, y0, x1, y1 = bbox
    prod_h = y1 - y0 + 1
    prod_w = x1 - x0 + 1

    sil = (alpha > 30).astype(np.uint8) * 255
    # تحويل منظوري: القاعدة تبقى مكانها، القمة تنزاح باتجاه زاوية الظل وتنضغط
    angle = np.deg2rad(opts.drop_angle_deg)
    shift = float(np.cos(angle)) * prod_h * opts.drop_length_ratio
    squash = max(0.08, min(1.0, opts.drop_squash))

    src = np.float32([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
    new_top_y = y1 - prod_h * squash
    dst = np.float32([
        [x0 + shift, new_top_y],
        [x1 + shift, new_top_y],
        [x1, y1],
        [x0, y1],
    ])
    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(sil, M, (w, h), flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=0)

    # تدرج التلاشي: أغمق عند القاعدة، أفتح مع الارتفاع (البعد)
    if opts.drop_fade > 0:
        yy = np.arange(h, dtype=np.float32)
        top = max(0.0, new_top_y)
        span = max(1.0, y1 - top)
        grad = np.clip((yy - top) / span, 0.0, 1.0)
        grad = (1.0 - opts.drop_fade) + opts.drop_fade * grad
        warped = (warped.astype(np.float32) * grad[:, None]).astype(np.uint8)

    k = _scaled_blur(opts.blur, w)
    warped = cv2.GaussianBlur(warped, (k, k), 0)
    # ضبابية إضافية تصاعدية للأجزاء البعيدة (محاكاة انتشار الضوء)
    far = cv2.GaussianBlur(warped, (k * 2 + 1, k * 2 + 1), 0)
    yy = np.linspace(1.0, 0.0, h, dtype=np.float32)[:, None]
    warped = (warped.astype(np.float32) * (1 - yy * 0.5) +
              far.astype(np.float32) * (yy * 0.5)).astype(np.uint8)
    return warped


def build_shadow_layer(alpha: np.ndarray, opts: ShadowOptions,
                       canvas_shape: Optional[Tuple[int, int]] = None) -> np.ndarray:
    """يبني قناة شدة الظل الكاملة حسب النوع المطلوب."""
    if canvas_shape is None:
        canvas_shape = alpha.shape[:2]
    kind = (opts.kind or "none").lower()
    if kind == "none":
        return np.zeros(canvas_shape, dtype=np.uint8)
    layers = []
    if kind in ("contact", "both"):
        layers.append(make_contact_shadow(alpha, opts, canvas_shape))
    if kind in ("drop", "both"):
        layers.append(make_drop_shadow(alpha, opts, canvas_shape))
    if not layers:
        return np.zeros(canvas_shape, dtype=np.uint8)
    out = layers[0].astype(np.float32)
    for l in layers[1:]:
        out = 255.0 - (255.0 - out) * (255.0 - l.astype(np.float32)) / 255.0
    return np.clip(out, 0, 255).astype(np.uint8)


def apply_shadow(rgba: np.ndarray, opts: ShadowOptions,
                 pad_bottom: int = 0) -> np.ndarray:
    """يطبق الظل تحت المنتج ويعيد صورة BGRA جديدة.

    الظل يُرسم خلف المنتج (لا يغطيه أبدًا). إذا احتاج الظل مساحة سفلية
    إضافية يمكن تمرير pad_bottom لتوسيع اللوحة.
    """
    img = _ensure_rgba(rgba.copy())
    if pad_bottom > 0:
        img = cv2.copyMakeBorder(img, 0, pad_bottom, 0, 0,
                                 cv2.BORDER_CONSTANT, value=(0, 0, 0, 0))
    h, w = img.shape[:2]
    alpha = img[:, :, 3]
    intensity = build_shadow_layer(alpha, opts, (h, w))
    if intensity.max() == 0:
        return img

    # الظل لا يظهر فوق المنتج نفسه
    inv_product = 255 - alpha
    shadow_alpha = (intensity.astype(np.float32) * (inv_product.astype(np.float32) / 255.0)
                    * float(np.clip(opts.opacity, 0.0, 1.0)))
    shadow_alpha = np.clip(shadow_alpha, 0, 255).astype(np.uint8)

    out = img.copy()
    prod_a = alpha.astype(np.float32) / 255.0
    sh_a = shadow_alpha.astype(np.float32) / 255.0
    combined_a = prod_a + sh_a * (1.0 - prod_a)
    b, g, r = (float(opts.color[2]), float(opts.color[1]), float(opts.color[0]))
    shadow_rgb = np.zeros((h, w, 3), dtype=np.float32)
    shadow_rgb[:, :, 0] = b
    shadow_rgb[:, :, 1] = g
    shadow_rgb[:, :, 2] = r
    src_rgb = img[:, :, :3].astype(np.float32)
    safe_a = np.where(combined_a > 1e-5, combined_a, 1.0)
    out_rgb = (src_rgb * prod_a[:, :, None] +
               shadow_rgb * (sh_a * (1.0 - prod_a))[:, :, None]) / safe_a[:, :, None]
    out[:, :, :3] = np.clip(out_rgb, 0, 255).astype(np.uint8)
    out[:, :, 3] = np.clip(combined_a * 255.0, 0, 255).astype(np.uint8)
    return out


def apply_shadow_on_white(rgba: np.ndarray, opts: ShadowOptions) -> np.ndarray:
    """يطبق الظل ثم يركب النتيجة على خلفية بيضاء نقية (BGR)."""
    shadowed = apply_shadow(rgba, opts)
    h, w = shadowed.shape[:2]
    a = shadowed[:, :, 3].astype(np.float32) / 255.0
    rgb = shadowed[:, :, :3].astype(np.float32)
    white = np.full((h, w, 3), 255.0, dtype=np.float32)
    out = rgb * a[:, :, None] + white * (1.0 - a[:, :, None])
    return np.clip(out, 0, 255).astype(np.uint8)


# إعدادات جاهزة (Presets) بأسماء عربية للواجهة
SHADOW_PRESETS = {
    "بدون ظل": ShadowOptions(kind="none"),
    "ظل أرضي ناعم": ShadowOptions(kind="contact", opacity=0.35, blur=23),
    "ظل أرضي قوي": ShadowOptions(kind="contact", opacity=0.55, blur=17,
                                  contact_height_ratio=0.12),
    "ظل مسقط يمين": ShadowOptions(kind="both", opacity=0.30, blur=25,
                                   drop_angle_deg=35.0, drop_length_ratio=0.45,
                                   drop_squash=0.30),
    "ظل مسقط يسار": ShadowOptions(kind="both", opacity=0.30, blur=25,
                                   drop_angle_deg=145.0, drop_length_ratio=0.45,
                                   drop_squash=0.30),
    "ظل استوديو 3D": ShadowOptions(kind="both", opacity=0.42, blur=27,
                                    drop_angle_deg=55.0, drop_length_ratio=0.35,
                                    drop_squash=0.22, drop_fade=0.9,
                                    contact_height_ratio=0.11),
}
