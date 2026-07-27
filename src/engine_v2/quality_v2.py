# -*- coding: utf-8 -*-
"""quality_v2 — محرك الجودة الفائقة الواعي بالنص (Text-Aware Quality Engine).

ابتكار خاص بالبرنامج يجعل نصوص المنتج وجداول الحقائق الغذائية واضحة تمامًا
بعد المعالجة والتصغير — دون هالات ودون إتلاف باقي الصورة:

1) text_saliency_map:   خريطة مناطق النص بلا OCR ثقيل (كثافة تدرجات + مورفولوجيا).
2) smart_downscale:     تصغير تدريجي متعدد الخطوات مع حدة تعويضية بعد كل خطوة —
                        يحافظ على مقروئية النص أفضل بكثير من التصغير بخطوة واحدة.
3) adaptive_text_sharpen: حدة انتقائية موزونة بخريطة النص (بلا هالات على الخلفية).
4) readability_score:   مقياس مقروئية موضوعي (طاقة حواف + تباين محلي في مناطق النص)
                        يُستخدم للمعايرة التلقائية: أي خطوة تُنقص المقروئية تُلغى.
5) enhance_preserving_text: تحسين تلقائي لا يمس تفاصيل النص (denoise انتقائي).
6) polish_output_file:  تمريرة لاحقة على ملف ناتج جاهز — ترفع وضوحه وتعيد حفظه
                        بجودة عالية (تعمل حتى على نواتج المحرك القديم V1).
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

__all__ = [
    "text_saliency_map", "smart_downscale", "adaptive_text_sharpen",
    "readability_score", "enhance_preserving_text", "polish_output_file",
    "QualityReport",
]


# --------------------------------------------------------------- saliency
def text_saliency_map(img: np.ndarray, dilate_px: int = 7) -> np.ndarray:
    """خريطة 0..1 لمناطق النص/التفاصيل الدقيقة — سريعة بلا OCR.

    تعتمد على كثافة التدرجات عالية التردد المتجمعة في سطور (سمة النص المطبوع)
    مع إغلاق مورفولوجي أفقي يربط الحروف في كتل كلمات.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    # تدرجات عالية التردد
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    mag = np.clip(mag / (mag.mean() * 4.0 + 1e-6), 0, 1)
    m8 = (mag * 255).astype(np.uint8)
    # عتبة تكيفية ثم ربط الحروف أفقيًا (نص لاتيني/عربي كلاهما سطري)
    _, bw = cv2.threshold(m8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    h, w = gray.shape[:2]
    kx = max(3, w // 160)
    closed = cv2.morphologyEx(bw, cv2.MORPH_CLOSE,
                              cv2.getStructuringElement(cv2.MORPH_RECT, (kx, 3)))
    # استبعاد الحواف الطويلة المنفردة (حدود المنتج) — النص كتل كثيفة صغيرة
    n, labels, stats, _ = cv2.connectedComponentsWithStats(closed, 8)
    keep = np.zeros_like(closed)
    img_area = float(h * w)
    for i in range(1, n):
        x, y, bw_, bh_, area = stats[i]
        if area < 12:                      # ضجيج
            continue
        if bw_ > w * 0.95 or bh_ > h * 0.95:   # إطار كامل
            continue
        fill = area / max(1, bw_ * bh_)
        aspect = bw_ / max(1, bh_)
        # كتل نصية: امتلاء معقول وليست خطوطًا رفيعة جدًا طويلة
        if fill > 0.12 and area < img_area * 0.25 and 0.05 < aspect < 40:
            keep[labels == i] = 255
    if dilate_px > 0:
        keep = cv2.dilate(keep, np.ones((dilate_px, dilate_px), np.uint8))
    sal = cv2.GaussianBlur(keep.astype(np.float32) / 255.0, (0, 0), 2.0)
    return np.clip(sal, 0, 1)


# ------------------------------------------------------------ readability
def readability_score(img: np.ndarray, sal: np.ndarray | None = None) -> float:
    """مقياس مقروئية 0..100: طاقة حواف + تباين محلي داخل مناطق النص."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    if sal is None:
        sal = text_saliency_map(img)
    mask = sal > 0.35
    if not mask.any():
        return 0.0
    lap = cv2.Laplacian(gray, cv2.CV_32F, ksize=3)
    edge_energy = float(np.abs(lap)[mask].mean())
    # تباين محلي (انحراف معياري في نافذة 9×9)
    g32 = gray.astype(np.float32)
    mean = cv2.blur(g32, (9, 9))
    sq = cv2.blur(g32 * g32, (9, 9))
    local_std = np.sqrt(np.clip(sq - mean * mean, 0, None))
    contrast = float(local_std[mask].mean())
    return float(min(100.0, edge_energy * 0.9 + contrast * 0.9))


# --------------------------------------------------------------- sharpen
def adaptive_text_sharpen(img: np.ndarray, strength: float = 0.8,
                          sal: np.ndarray | None = None) -> np.ndarray:
    """حدة انتقائية فوق مناطق النص فقط — بلا هالات على الخلفية البيضاء.

    unsharp مزدوج النطاق: نصف قطر صغير (0.8) لحروف دقيقة + متوسط (1.8)
    للنص الأكبر، موزون بخريطة النص.
    """
    if strength <= 0:
        return img
    if sal is None:
        sal = text_saliency_map(img)
    if not (sal > 0.2).any():
        return img
    f = img.astype(np.float32)
    fine = cv2.GaussianBlur(f, (0, 0), 0.8)
    mid = cv2.GaussianBlur(f, (0, 0), 1.8)
    sharp = f + strength * 0.9 * (f - fine) + strength * 0.5 * (f - mid)
    w = np.clip(sal, 0, 1)[:, :, None] if img.ndim == 3 else np.clip(sal, 0, 1)
    out = f * (1 - w) + sharp * w
    return np.clip(out, 0, 255).astype(np.uint8)


# ------------------------------------------------------------- downscale
def smart_downscale(img: np.ndarray, target_w: int, target_h: int,
                    text_aware: bool = True) -> np.ndarray:
    """تصغير تدريجي يحافظ على مقروئية النص.

    بدل خطوة واحدة قاسية (INTER_AREA)، ينزل بخطوات ≤ 0.65 مع unsharp
    تعويضي خفيف بعد كل خطوة — النتيجة نص أوضح بشكل ملموس عند التصغير القوي.
    """
    h, w = img.shape[:2]
    if target_w >= w and target_h >= h:
        if target_w == w and target_h == h:
            return img
        return cv2.resize(img, (target_w, target_h),
                          interpolation=cv2.INTER_LANCZOS4)
    cur = img
    ch, cw = h, w
    total_scale = min(target_w / w, target_h / h)
    # حدة استباقية خفيفة قبل التصغير القوي (تعوض فقدان الترددات العالية)
    if text_aware and total_scale < 0.75:
        sal0 = text_saliency_map(cur)
        cur = adaptive_text_sharpen(cur, strength=0.45, sal=sal0)
    while cw > target_w or ch > target_h:
        step = max(min(target_w / cw, target_h / ch), 0.65)
        nw = max(target_w, int(round(cw * step)))
        nh = max(target_h, int(round(ch * step)))
        if nw == cw and nh == ch:
            nw, nh = target_w, target_h
        cur = cv2.resize(cur, (nw, nh), interpolation=cv2.INTER_AREA)
        cw, ch = nw, nh
        if text_aware and (cw > target_w or ch > target_h):
            # تعويض خفيف بين الخطوات
            f = cur.astype(np.float32)
            blur = cv2.GaussianBlur(f, (0, 0), 0.9)
            cur = np.clip(f + 0.28 * (f - blur), 0, 255).astype(np.uint8)
    if cw != target_w or ch != target_h:
        cur = cv2.resize(cur, (target_w, target_h),
                         interpolation=cv2.INTER_LANCZOS4)
    if text_aware:
        # اللمسة النهائية: حدة نصية بعد الوصول للمقاس النهائي + معايرة تلقائية
        sal = text_saliency_map(cur)
        cand = adaptive_text_sharpen(cur, strength=0.7, sal=sal)
        if readability_score(cand, sal) >= readability_score(cur, sal):
            cur = cand
    return cur


# --------------------------------------------------------------- enhance
def enhance_preserving_text(img: np.ndarray) -> np.ndarray:
    """تحسين تلقائي لا يمس النص: كالتحسين المعتاد لكن الـ denoise لا يطبق
    فوق مناطق النص، والحدة النهائية نصية انتقائية مع معايرة تلقائية."""
    from engine_v2.enhancement_v2 import EnhanceSettings, auto_enhance
    sal = text_saliency_map(img)
    before = readability_score(img, sal)
    # تحسين بلا denoise وبلا sharpen (سنطبقهما انتقائيًا)
    s = EnhanceSettings(denoise=False, sharpen_amount=0.0)
    out = auto_enhance(img, s)
    # denoise فقط خارج مناطق النص
    den = cv2.bilateralFilter(out, 5, 28, 28)
    w = np.clip(sal * 1.6, 0, 1)[:, :, None]
    out = np.clip(den.astype(np.float32) * (1 - w) +
                  out.astype(np.float32) * w, 0, 255).astype(np.uint8)
    # حدة نصية
    out = adaptive_text_sharpen(out, strength=0.75, sal=sal)
    # معايرة تلقائية: لا نقبل نتيجة أقل مقروئية من الأصل
    after = readability_score(out, sal)
    if after + 1e-6 < before * 0.98:
        out = adaptive_text_sharpen(img, strength=0.6, sal=sal)
    return out


# ------------------------------------------------------------ post-pass
@dataclass
class QualityReport:
    path: str = ""
    before: float = 0.0
    after: float = 0.0
    improved: bool = False
    error: str = ""


def _imread_u(path: str) -> np.ndarray | None:
    try:
        data = np.fromfile(str(path), np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return None


def _imwrite_u(path: str, img: np.ndarray, quality: int = 101) -> bool:
    ext = str(path).rsplit(".", 1)[-1].lower()
    if ext == "webp":
        params = [cv2.IMWRITE_WEBP_QUALITY, int(quality)]
        enc = ".webp"
    elif ext in ("jpg", "jpeg"):
        params = [cv2.IMWRITE_JPEG_QUALITY, min(100, int(quality))]
        enc = ".jpg"
    else:
        params = [cv2.IMWRITE_PNG_COMPRESSION, 3]
        enc = ".png"
    ok, buf = cv2.imencode(enc, img, params)
    if not ok:
        return False
    buf.tofile(str(path))
    return True


def polish_output_file(path: str, quality: int = 101,
                       blur_dates: bool = False) -> QualityReport:
    """تمريرة جودة لاحقة على ملف ناتج جاهز (من أي محرك):
    حدة نصية انتقائية + معايرة تلقائية + (اختياري) طمس التواريخ،
    ثم إعادة الحفظ بجودة عالية. آمنة: لا تحفظ إلا إذا تحسنت المقروئية."""
    rep = QualityReport(path=str(path))
    img = _imread_u(path)
    if img is None:
        rep.error = "تعذر قراءة الملف"
        return rep
    sal = text_saliency_map(img)
    rep.before = readability_score(img, sal)
    out = adaptive_text_sharpen(img, strength=0.65, sal=sal)
    rep.after = readability_score(out, sal)
    changed = False
    if rep.after > rep.before * 1.01:
        img = out
        changed = True
    if blur_dates:
        try:
            from engine_v2.date_blur_v2 import auto_blur_dates
            img2, n = auto_blur_dates(img)
            if n > 0:
                img = img2
                changed = True
        except Exception:
            pass
    if changed:
        if not _imwrite_u(str(path), img, quality):
            rep.error = "فشل الحفظ"
            return rep
        rep.improved = True
    return rep
