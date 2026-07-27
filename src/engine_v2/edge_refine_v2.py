# -*- coding: utf-8 -*-
"""edge_refine_v2 — معالجة الحواف الصعبة (matting) للمنتجات المعقدة.

للمنتجات ذات الحواف غير الواضحة (دجاج مغلف، أغلفة شفافة، انحناءات):
- refine_alpha: تنعيم مصفوفة alpha عبر guided filter (أو fallback
  bilateral) لالتقاط أنصاف الشفافية عند الأطراف بدل القص الحاد.
- remove_halo: إزالة هالة الخلفية (color decontamination) عند الحواف.
- feather_edges: تنعيم أطراف القص بتدرج ناعم anti-aliased.
- detect_uncertain_edges: كشف مناطق الحواف المشكوك فيها ليعرضها
  المساعد الذكي على المستخدم في الوضع التعاوني.
- smart_suggestions: تحليل الصورة واقتراح تحسينات (المساعد الذكي).
"""
from __future__ import annotations

import cv2
import numpy as np

__all__ = ["refine_alpha", "remove_halo", "feather_edges",
           "detect_uncertain_edges", "smart_suggestions",
           "detect_glare", "remove_glare", "remove_dark_fringe",
           "polish_for_store", "auto_straighten_angle"]


def _guided_filter(guide: np.ndarray, src: np.ndarray, radius: int,
                   eps: float) -> np.ndarray:
    """guided filter — ximgproc إن وجد وإلا تنفيذ box-filter مكافئ."""
    try:
        from cv2 import ximgproc
        return ximgproc.guidedFilter(guide, src, radius, eps)
    except Exception:
        pass
    # تنفيذ قياسي He et al. 2010 بمرشحات صندوقية (سريع وكافٍ)
    guide = guide.astype(np.float32) / 255.0 if guide.dtype == np.uint8 \
        else guide.astype(np.float32)
    src_f = src.astype(np.float32) / 255.0 if src.dtype == np.uint8 \
        else src.astype(np.float32)
    if guide.ndim == 3:
        guide = cv2.cvtColor(guide, cv2.COLOR_BGR2GRAY)
    ksize = (radius * 2 + 1, radius * 2 + 1)
    mean_i = cv2.boxFilter(guide, -1, ksize)
    mean_p = cv2.boxFilter(src_f, -1, ksize)
    corr_ip = cv2.boxFilter(guide * src_f, -1, ksize)
    corr_ii = cv2.boxFilter(guide * guide, -1, ksize)
    var_i = corr_ii - mean_i * mean_i
    cov_ip = corr_ip - mean_i * mean_p
    a = cov_ip / (var_i + eps)
    b = mean_p - a * mean_i
    mean_a = cv2.boxFilter(a, -1, ksize)
    mean_b = cv2.boxFilter(b, -1, ksize)
    out = mean_a * guide + mean_b
    return np.clip(out * 255.0, 0, 255).astype(np.uint8)


def refine_alpha(image_bgr: np.ndarray, alpha: np.ndarray,
                 radius: int = 8, eps: float = 1e-3) -> np.ndarray:
    """ينعّم alpha بحواف الصورة الحقيقية — يلتقط أنصاف الشفافية.

    المدخل: صورة BGR + قناة alpha (uint8). الناتج alpha محسّنة uint8.
    """
    if alpha is None or alpha.size == 0:
        return alpha
    a = alpha if alpha.dtype == np.uint8 else \
        np.clip(alpha * 255, 0, 255).astype(np.uint8)
    refined = _guided_filter(image_bgr, a, radius, eps)
    # حافظ على المناطق الداخلية الصلبة — التنعيم للحواف فقط
    solid = cv2.erode(a, np.ones((7, 7), np.uint8))
    refined = np.where(solid > 250, a, refined)
    return refined.astype(np.uint8)


def remove_halo(image_bgr: np.ndarray, alpha: np.ndarray,
                strength: float = 0.8) -> np.ndarray:
    """إزالة هالة لون الخلفية عند الحواف (color decontamination).

    يستبدل ألوان بكسلات الحافة شبه الشفافة بألوان أقرب بكسل داخلي صلب.
    """
    if alpha is None:
        return image_bgr
    a = alpha if alpha.dtype == np.uint8 else \
        np.clip(alpha * 255, 0, 255).astype(np.uint8)
    edge_band = (a > 10) & (a < 245)
    if not edge_band.any():
        return image_bgr
    solid = (a >= 245).astype(np.uint8)
    # أقرب بكسل صلب لكل بكسل حافة
    dist, labels = cv2.distanceTransformWithLabels(
        1 - solid, cv2.DIST_L2, 3, labelType=cv2.DIST_LABEL_PIXEL)
    solid_idx = np.flatnonzero(solid.ravel())
    if solid_idx.size == 0:
        return image_bgr
    lab_of_solid = labels.ravel()[solid_idx]
    lut = np.zeros(int(labels.max()) + 1, dtype=np.int64)
    lut[lab_of_solid] = solid_idx
    nearest = lut[labels.ravel()].reshape(labels.shape)
    out = image_bgr.copy()
    ys, xs = np.nonzero(edge_band)
    src_flat = image_bgr.reshape(-1, 3)
    donor = src_flat[nearest[ys, xs]]
    w = (strength * (1.0 - a[ys, xs] / 255.0))[:, None]
    out[ys, xs] = np.clip(out[ys, xs] * (1 - w) + donor * w, 0,
                          255).astype(np.uint8)
    return out


def feather_edges(alpha: np.ndarray, radius: int = 2) -> np.ndarray:
    """تدرج ناعم anti-aliased على أطراف القص."""
    if alpha is None or radius <= 0:
        return alpha
    a = alpha if alpha.dtype == np.uint8 else \
        np.clip(alpha * 255, 0, 255).astype(np.uint8)
    k = radius * 2 + 1
    return cv2.GaussianBlur(a, (k, k), 0)


def detect_uncertain_edges(image_bgr: np.ndarray,
                           alpha: np.ndarray) -> list[tuple[int, int, int, int]]:
    """مناطق حواف مشكوك فيها (تباين ضعيف بين المنتج والخلفية) — للمساعد.

    يعيد قائمة مستطيلات (x, y, w, h) ليعرضها الوضع التعاوني على المستخدم.
    """
    if alpha is None:
        return []
    a = alpha if alpha.dtype == np.uint8 else \
        np.clip(alpha * 255, 0, 255).astype(np.uint8)
    band = cv2.morphologyEx(a, cv2.MORPH_GRADIENT,
                            np.ones((9, 9), np.uint8))
    band_mask = band > 30
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    grad = cv2.magnitude(
        cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3),
        cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))
    # حافة قص بلا حافة صورة حقيقية = منطقة مشكوك فيها
    weak = band_mask & (grad < 25)
    weak_u8 = (weak * 255).astype(np.uint8)
    weak_u8 = cv2.morphologyEx(weak_u8, cv2.MORPH_CLOSE,
                               np.ones((15, 15), np.uint8))
    contours, _ = cv2.findContours(weak_u8, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    rects = []
    min_area = max(120, image_bgr.shape[0] * image_bgr.shape[1] // 4000)
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w * h >= min_area:
            rects.append((int(x), int(y), int(w), int(h)))
    rects.sort(key=lambda r: r[2] * r[3], reverse=True)
    return rects[:8]


def smart_suggestions(image_bgr: np.ndarray,
                      alpha: np.ndarray | None = None) -> list[dict]:
    """المساعد الذكي: يحلل الصورة ويقترح تحسينات بالعربي.

    كل اقتراح: {key, label_ar, reason_ar, params} — الواجهة تعرضها
    والمستخدم يطبق ما يوافق عليه بنقرة (الوضع التعاوني).
    """
    sugg: list[dict] = []
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    mean, std = float(np.mean(gray)), float(np.std(gray))
    # إضاءة منخفضة/عالية
    if mean < 95:
        sugg.append({"key": "brightness", "label_ar": "رفع الإضاءة",
                     "reason_ar": "الصورة داكنة — رفع الإضاءة يوضح التفاصيل",
                     "params": {"value": int(min(40, (110 - mean)))}})
    elif mean > 200:
        sugg.append({"key": "brightness", "label_ar": "خفض الإضاءة",
                     "reason_ar": "الصورة ساطعة أكثر من اللازم",
                     "params": {"value": -int(min(30, (mean - 190)))}})
    # تباين ضعيف
    if std < 42:
        sugg.append({"key": "contrast", "label_ar": "تحسين التباين (CLAHE)",
                     "reason_ar": "التباين ضعيف — تحسينه يبرز المنتج",
                     "params": {"clip": 2.0}})
    # حدة منخفضة (تباين لابلاس)
    blur_metric = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if blur_metric < 60:
        sugg.append({"key": "sharpen", "label_ar": "رفع الحدة الذكي",
                     "reason_ar": "الصورة طرية قليلًا — رفع حدة خفيف يوضح "
                                  "النصوص وحقائق المنتج",
                     "params": {"amount": 0.6}})
    # ضوضاء عالية
    noise = float(np.std(cv2.absdiff(gray, cv2.medianBlur(gray, 3))))
    if noise > 6.5:
        sugg.append({"key": "denoise", "label_ar": "إزالة الضوضاء الحافظة",
                     "reason_ar": "توجد حبيبات ضوضاء — إزالتها مع حفظ "
                                  "التفاصيل",
                     "params": {"h": 7}})
    # حواف مشكوك فيها
    if alpha is not None:
        rects = detect_uncertain_edges(image_bgr, alpha)
        if rects:
            sugg.append({"key": "edge_review",
                         "label_ar": f"مراجعة {len(rects)} منطقة حواف",
                         "reason_ar": "حواف القص غير مؤكدة في هذه المناطق "
                                      "(انحناءات/شفافية) — راجعها بفرشاة "
                                      "الاسترجاع أو طبّق تنعيم الحواف الذكي",
                         "params": {"rects": rects}})
        sugg.append({"key": "refine_alpha", "label_ar": "تنعيم الحواف الذكي",
                     "reason_ar": "يلتقط أنصاف الشفافية عند الأطراف "
                                  "(مفيد للأغلفة الشفافة والانحناءات)",
                     "params": {"radius": 8}})
        sugg.append({"key": "remove_halo", "label_ar": "إزالة هالة الخلفية",
                     "reason_ar": "يزيل بقايا لون الخلفية العالقة على الحواف",
                     "params": {"strength": 0.8}})
    return sugg


# ---------------------------------------------------------------- glare
def detect_glare(image_bgr: np.ndarray,
                 sensitivity: float = 0.5) -> np.ndarray:
    """كشف الانعكاسات الضوئية (لمعان الفلاش) — قناع uint8.

    الانعكاس = سطوع عالٍ جدًا + تشبع منخفض + مساحة صغيرة نسبيًا.
    sensitivity 0..1: كلما زادت التقط انعكاسات أخف.
    """
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    s, v = hsv[..., 1], hsv[..., 2]
    v_th = int(250 - 35 * float(np.clip(sensitivity, 0, 1)))
    s_th = int(40 + 45 * float(np.clip(sensitivity, 0, 1)))
    mask = ((v >= v_th) & (s <= s_th)).astype(np.uint8) * 255
    # تجاهل الخلفية البيضاء الكبيرة: استبعد المكونات الضخمة (> 12% من الصورة)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    total = mask.shape[0] * mask.shape[1]
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] > total * 0.12:
            mask[labels == i] = 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8))
    return mask


def remove_glare(image_bgr: np.ndarray, strength: float = 0.7,
                 mask: np.ndarray | None = None) -> np.ndarray:
    """إزالة الانعكاسات بترميم inpainting حافظ للتفاصيل.

    strength 0..1: يتحكم بحساسية الكشف وقوة المزج مع الأصل.
    mask اختياري: قناع يدوي (فرشاة المستخدم) بدل الكشف التلقائي.
    """
    st = float(np.clip(strength, 0.0, 1.0))
    if st <= 0:
        return image_bgr
    m = mask if mask is not None else detect_glare(image_bgr, st)
    if m is None or not (m > 0).any():
        return image_bgr
    repaired = cv2.inpaint(image_bgr, m, 5, cv2.INPAINT_TELEA)
    # مزج ناعم: قوة الإزالة تتدرج مع strength وحواف القناع
    soft = cv2.GaussianBlur(m, (9, 9), 0).astype(np.float32) / 255.0
    w = (soft * st)[:, :, None]
    out = image_bgr.astype(np.float32) * (1 - w) + \
        repaired.astype(np.float32) * w
    return np.clip(out, 0, 255).astype(np.uint8)


# ================================================== store-ready polishing
def remove_dark_fringe(img_bgr: np.ndarray, alpha: np.ndarray,
                       width: int = 3) -> np.ndarray:
    """يزيل الحواف الداكنة (السوداء) الملوثة حول حدود المنتج.

    بعد العزل تبقى أحيانًا بكسلات داكنة مختلطة بلون الخلفية الأصلية على
    الحافة. نكتشف شريط الحافة، وحيث تكون البكسلات أدكن بوضوح من جوارها
    الداخلي نستبدلها بمزيج من ألوان الجوار الداخلي النظيف.
    """
    a = alpha if alpha.dtype == np.uint8 else \
        np.clip(alpha, 0, 255).astype(np.uint8)
    solid = (a > 200).astype(np.uint8)
    if solid.sum() == 0:
        return img_bgr
    k = np.ones((3, 3), np.uint8)
    inner = cv2.erode(solid, k, iterations=max(1, width))
    band = ((solid - inner) > 0) & (a > 10)
    if not band.any():
        return img_bgr

    # مرجع الألوان: تمدد ألوان المنطقة الداخلية النظيفة نحو الحافة
    ref = img_bgr.copy()
    ref[inner == 0] = 0
    for _ in range(width + 2):
        dil = cv2.dilate(ref, k)
        mask_empty = (ref.sum(axis=2) == 0)
        ref[mask_empty] = dil[mask_empty]

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY).astype(np.int16)
    ref_gray = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY).astype(np.int16)
    # بكسل حافة أدكن من مرجعه الداخلي بفارق كبير = تلوث داكن
    dark = band & (gray < ref_gray - 35) & (ref_gray > 30)
    if not dark.any():
        return img_bgr
    out = img_bgr.copy()
    blend = 0.75
    out[dark] = (ref[dark].astype(np.float32) * blend +
                 img_bgr[dark].astype(np.float32) * (1 - blend)).astype(np.uint8)
    return out


def polish_for_store(img_bgr: np.ndarray,
                     alpha: np.ndarray | None = None,
                     strength: float = 0.5) -> tuple[np.ndarray, np.ndarray | None]:
    """تنقيح نهائي للتسليم: حواف نظيفة بلا سواد + لمعة متجر جميلة.

    مظهر تصوير استوديو حقيقي: (1) تنعيم ألفا الذكي، (2) إزالة هالة
    الخلفية، (3) إزالة الحواف الداكنة، (4) توازن أبيض تلقائي لطيف،
    (5) تباين تكيفي CLAHE، (6) تدرج إضاءة استوديو علوي ناعم،
    (7) نضارة ألوان vibrance محسوبة، (8) حدة ذكية خفيفة.
    strength ‏0..1 يضبط قوة اللمعة فقط — تنظيف الحواف يتم دائمًا
    كاملًا. يعيد (صورة، ألفا محسّنة أو None).
    """
    out = img_bgr.copy()
    a = None
    if alpha is not None:
        a = refine_alpha(out, alpha)
        out = remove_halo(out, a)
        out = remove_dark_fringe(out, a)

    s = float(np.clip(strength, 0.0, 1.0))
    if s > 0.02:
        base_clean = out.copy()
        # (4) توازن أبيض تلقائي لطيف (gray-world مخفف)
        f = out.astype(np.float32)
        means = f.reshape(-1, 3).mean(axis=0)
        gray_mean = float(means.mean())
        gains = np.clip(gray_mean / np.maximum(means, 1.0), 0.9, 1.1)
        gains = 1.0 + (gains - 1.0) * (0.7 * s)
        f = np.clip(f * gains[None, None, :], 0, 255)
        out = f.astype(np.uint8)
        # (5) تباين تكيفي لطيف على قناة الإضاءة فقط
        lab = cv2.cvtColor(out, cv2.COLOR_BGR2LAB)
        l_ch, a_ch, b_ch = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=1.0 + s * 1.2, tileGridSize=(8, 8))
        l2 = clahe.apply(l_ch)
        l_ch = cv2.addWeighted(l_ch, 1 - 0.6 * s, l2, 0.6 * s, 0)
        # (6) تدرج إضاءة استوديو علوي ناعم على قناة الإضاءة
        h = l_ch.shape[0]
        grad = (np.linspace(1.0 + 0.05 * s, 1.0 - 0.03 * s, h,
                            dtype=np.float32))[:, None]
        l_ch = np.clip(l_ch.astype(np.float32) * grad, 0, 255).astype(np.uint8)
        out = cv2.cvtColor(cv2.merge([l_ch, a_ch, b_ch]), cv2.COLOR_LAB2BGR)
        # (7) نضارة ألوان vibrance: تعزيز التشبع المنخفض فقط بلا مبالغة
        hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV).astype(np.float32)
        sat = hsv[..., 1]
        boost = (1.0 - sat / 255.0) * (0.25 * s)
        hsv[..., 1] = np.clip(sat * (1.0 + boost), 0, 255)
        out = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
        # (8) حدة ذكية خفيفة
        blur = cv2.GaussianBlur(out, (0, 0), 1.6)
        out = cv2.addWeighted(out, 1 + 0.5 * s, blur, -0.5 * s, 0)
        if a is not None:
            # اللمعة داخل قناع المنتج فقط — الحواف والخلفية تبقى نظيفة
            mask3 = (cv2.erode((a > 200).astype(np.uint8) * 255,
                               np.ones((3, 3), np.uint8)
                               ).astype(np.float32) / 255.0)[..., None]
            out = (out.astype(np.float32) * mask3 +
                   base_clean.astype(np.float32) * (1 - mask3)).astype(np.uint8)
    return out, a


def auto_straighten_angle(alpha: np.ndarray) -> float:
    """يكشف زاوية ميل المنتج (بالدرجات) لتصحيحها — التوزين التلقائي.

    يعتمد minAreaRect على قناع ألفا؛ يعيد الزاوية المقترحة للتدوير
    العكسي في نطاق ±10° فقط (أكبر من ذلك غالبًا وضع مقصود).
    """
    a = alpha if alpha.dtype == np.uint8 else \
        np.clip(alpha, 0, 255).astype(np.uint8)
    mask = (a > 128).astype(np.uint8)
    if mask.sum() < 100:
        return 0.0
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return 0.0
    c = max(contours, key=cv2.contourArea)
    (_, _), (w, h), ang = cv2.minAreaRect(c)
    if w < h:
        ang += 90.0
    # طبّع إلى أقرب استقامة
    while ang > 45.0:
        ang -= 90.0
    while ang < -45.0:
        ang += 90.0
    if abs(ang) > 10.0 or abs(ang) < 0.15:
        return 0.0
    return round(-ang, 1)
