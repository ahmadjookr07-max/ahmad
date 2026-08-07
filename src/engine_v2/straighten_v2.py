# -*- coding: utf-8 -*-
"""straighten_v2 — تقويم وضعية المنتج تلقائيًا بالنص والهندسة.

## البلاغ
«هناك بعض المنتجات تكون **وضعيتها ليست مستقيمة** يجب اضافة خاصية
ل يكون المنتج ب **الشكل المثالي** سواء عن طريق **قراءة الكلمات
ومعرفة الاتجاه وهذا افضل شيء** او ابتكر طريقة».

## المبدأ: أربع إشارات مستقلة تُدمج بترجيح
لا إشارة واحدة تكفي لكل المنتجات، فكلٌّ تخفت في حالة:

| الإشارة | قوّتها | تخفت حين |
| --- | --- | --- |
| **سطور النص** (اقتراح المالك) | الأقوى للمعلّبات | لا نص أو نص منحنٍ |
| حدّ المنتج المستقيم | قوية للعلب والكراتين | الكيس المجعّد |
| المستطيل الأصغر المحيط | متوسطة | الشكل غير المنتظم |
| التناظر الرأسي | قوية للقناني | الشكل غير المتناظر |

ولذلك تُقاس الأربع، ويُحسب لكل واحدة **وزن ثقة** من جودة إشارتها
نفسها، ثم تُدمج بمتوسط مرجّح دائري (لا حسابي، فالزوايا دورية).

## حدود السلامة
- التصحيح فوق ±20° مشبوه ⇒ يُعلَّم `needs_review` ولا يُطبَّق تلقائيًا
- الدوران يوسّع الإطار ⇒ **يجب أن يتلوه اقتصاص محسوب**
- الزوايا تُطبَّع إلى المدى (−45°, 45°] فتقويم 87° = −3°
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

__all__ = [
    "TiltEstimate",
    "text_line_angle",
    "edge_line_angle",
    "min_rect_angle",
    "symmetry_angle",
    "estimate_tilt",
    "straighten",
]


@dataclass
class TiltEstimate:
    """نتيجة تقدير الميل — شفافة بكل إشاراتها."""

    angle: float = 0.0                  # الزاوية المقترحة للتصحيح
    confidence: float = 0.0
    needs_review: bool = False
    signals: dict = field(default_factory=dict)   # اسم ⇒ (زاوية، وزن)
    notes: list[str] = field(default_factory=list)


def _norm45(deg: float) -> float:
    """يطبّع الزاوية إلى المدى (−45, 45]."""
    a = float(deg) % 180.0
    if a > 90.0:
        a -= 180.0
    if a > 45.0:
        a -= 90.0
    elif a <= -45.0:
        a += 90.0
    return a


def _mask_of(alpha_or_img: np.ndarray) -> np.ndarray:
    """يحوّل صورة أو ألفا أو قناعًا منطقيًا إلى قناع 0/1.

    **علة أمسكها القياس**: قناع قيمه 0/1 كان يُمرّر فيُعامل
    بعتبة >127 فيخرج **فارغًا تمامًا** — فأعطت كل الإشارات
    صفرًا رغم أن كل دالة تعمل وحدها. فصار التحويل يقيس
    مدى القيم قبل اختيار العتبة.
    """
    a = alpha_or_img
    if a.ndim == 3:
        d = 255 - a.astype(np.int16)
        return (d.max(axis=2) > 12).astype(np.uint8)
    if a.dtype == bool:
        return a.astype(np.uint8)
    mx = float(a.max()) if a.size else 0.0
    if mx <= 1.0:                     # قناع منطقي 0/1 أو عشري 0..1
        return (a > 0).astype(np.uint8)
    if a.dtype != np.uint8:
        a = np.clip(a, 0, 255).astype(np.uint8)
    return (a > 127).astype(np.uint8)


# ═════════════════════ 1. زاوية سطور النص ═════════════════════

def text_line_angle(image_bgr: np.ndarray,
                    mask: np.ndarray | None = None,
                    ) -> tuple[float, float]:
    """يقدّر الميل من اتجاه سطور الطباعة على المنتج.

    سطور الطباعة أفقية في الواقع، فميلها في الصورة = ميل المنتج.
    ونستعملها كما اقترح المالك لأنها **أقوى إشارة للمعلّبات**.

    الطريقة: نعزل مكوّنات صغيرة عريضة (الحروف والكلمات) داخل
    المنتج، ثم نصل الحروف المتجاورة أفقيًا بإغلاق مورفولوجي
    فتتكوّن «سطور»، ثم نقيس زاوية كل سطر بـ`minAreaRect` ونأخذ
    **الوسيط** (لا المتوسط — فالوسيط أمتن ضد سطر شاذّ).

    يعيد `(angle_deg, weight)` والوزن 0 إذا لم تُوجد سطور.
    """
    m = _mask_of(image_bgr) if mask is None else _mask_of(mask)
    if not m.any():
        return 0.0, 0.0
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    inner = cv2.erode(m, np.ones((9, 9), np.uint8))
    if not inner.any():
        inner = m

    # عتبة تكيّفية داخل المنتج: النص إما أغمق أو أفتح من محيطه
    blur = cv2.GaussianBlur(gray, (0, 0), 3)
    diff = cv2.absdiff(gray, blur)
    thr = np.zeros_like(gray)
    vals = diff[inner > 0]
    if vals.size < 100:
        return 0.0, 0.0
    cut = float(np.percentile(vals, 92))
    if cut < 4:
        return 0.0, 0.0
    thr[(diff >= cut) & (inner > 0)] = 255

    # وصل الحروف أفقيًا لتكوين سطور
    ys, xs = np.where(inner > 0)
    pw = int(xs.max() - xs.min() + 1)
    kx = max(9, int(pw * 0.05) | 1)
    lines = cv2.morphologyEx(thr, cv2.MORPH_CLOSE,
                             np.ones((3, kx), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(lines, 8)
    if n <= 1:
        return 0.0, 0.0

    angles: list[float] = []
    weights: list[float] = []
    for i in range(1, n):
        w = int(stats[i, cv2.CC_STAT_WIDTH])
        h = int(stats[i, cv2.CC_STAT_HEIGHT])
        area = int(stats[i, cv2.CC_STAT_AREA])
        # سطر نص: عريض ورقيق ومساحته معتبرة
        if w < pw * 0.10 or h < 3 or w < h * 2.2 or area < 40:
            continue
        comp = (lab == i).astype(np.uint8)
        cnts, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            continue
        rect = cv2.minAreaRect(max(cnts, key=cv2.contourArea))
        (_, _), (rw, rh), ang = rect
        if rw < rh:                      # نريد زاوية الضلع الطويل
            ang += 90.0
        # اصطلاح الإشارة: محور y مقلوب في إحداثيات الصورة،
        # و`getRotationMatrix2D` يدوّر عكس عقارب الساعة للزاوية
        # الموجبة — فالقياس أعطى ميل −8° كـ+7.43°. نوحّد الاصطلاح
        # على «زاوية دوران المنتج كما تُمرّر لـgetRotationMatrix2D».
        angles.append(-_norm45(ang))
        weights.append(float(w))         # السطر الأطول أوثق

    if len(angles) < 2:
        return 0.0, 0.0

    arr = np.array(angles, dtype=np.float64)
    wt = np.array(weights, dtype=np.float64)
    med = float(np.median(arr))
    # التشتّت يحدّد الثقة: سطور متوافقة ⇒ ثقة عالية
    spread = float(np.median(np.abs(arr - med)))
    conf = float(np.clip(1.0 - spread / 6.0, 0.0, 1.0))
    conf *= float(np.clip(len(angles) / 5.0, 0.3, 1.0))
    # نُرجع الوسيط المرجّح بالأطوال حول الوسيط
    near = np.abs(arr - med) <= max(2.0, spread * 2.0)
    if near.sum() >= 2:
        ang = float(np.average(arr[near], weights=wt[near]))
    else:
        ang = med
    return ang, conf


# ═════════════════════ 2. زاوية حدّ المنتج ═════════════════════

def edge_line_angle(mask: np.ndarray) -> tuple[float, float]:
    """يقدّر الميل من أطول الأضلاع المستقيمة في حدّ المنتج."""
    m = _mask_of(mask)
    if not m.any():
        return 0.0, 0.0
    edges = cv2.Canny(m * 255, 50, 150)
    ys, xs = np.where(m > 0)
    pw = int(xs.max() - xs.min() + 1)
    ph = int(ys.max() - ys.min() + 1)
    min_len = max(20, int(min(pw, ph) * 0.35))
    lines = cv2.HoughLinesP(edges, 1, np.pi / 360, threshold=40,
                            minLineLength=min_len, maxLineGap=6)
    if lines is None or len(lines) < 2:
        return 0.0, 0.0
    # شكل المخرَج يختلف بين إصدارات OpenCV: (N,1,4) أو (N,4)
    segs = lines.reshape(-1, 4)

    angs: list[float] = []
    lens: list[float] = []
    for x1, y1, x2, y2 in segs:
        ln = float(np.hypot(x2 - x1, y2 - y1))
        ang = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
        angs.append(-_norm45(ang))       # نفس اصطلاح إشارة النص
        lens.append(ln)
    arr = np.array(angs)
    wt = np.array(lens)
    med = float(np.median(arr))
    spread = float(np.median(np.abs(arr - med)))
    conf = float(np.clip(1.0 - spread / 8.0, 0.0, 1.0))
    conf *= float(np.clip(len(angs) / 6.0, 0.3, 1.0))
    near = np.abs(arr - med) <= max(2.5, spread * 2.0)
    ang = (float(np.average(arr[near], weights=wt[near]))
           if near.sum() >= 2 else med)
    return ang, conf


# ═════════════════════ 3. المستطيل الأصغر ═════════════════════

def min_rect_angle(mask: np.ndarray) -> tuple[float, float]:
    """زاوية المستطيل الأصغر المحيط — إشارة مساندة.

    ثقتها مرتبطة بـ**امتلاء** المستطيل: المنتج المستطيل يملأه
    فتوثق زاويته؛ والكيس المجعّد لا يملأه فتضعف.
    """
    m = _mask_of(mask)
    if not m.any():
        return 0.0, 0.0
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return 0.0, 0.0
    c = max(cnts, key=cv2.contourArea)
    rect = cv2.minAreaRect(c)
    (_, _), (rw, rh), ang = rect
    if rw < rh:
        ang += 90.0
    fill = float(cv2.contourArea(c)) / float(max(1.0, rw * rh))
    conf = float(np.clip((fill - 0.55) / 0.35, 0.0, 1.0)) * 0.7
    return -_norm45(ang), conf           # نفس اصطلاح إشارة النص


# ═════════════════════ 4. التناظر الرأسي ═════════════════════

def symmetry_angle(mask: np.ndarray, span: float = 12.0,
                   step: float = 1.0) -> tuple[float, float]:
    """الزاوية التي تعظّم التناظر الرأسي — أقوى إشارة للقناني."""
    m = _mask_of(mask)
    if not m.any():
        return 0.0, 0.0
    ys, xs = np.where(m > 0)
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    sub = m[y0:y1 + 1, x0:x1 + 1]
    if sub.shape[0] < 8 or sub.shape[1] < 8:
        return 0.0, 0.0
    # نصغّر للسرعة
    scale = 160.0 / max(sub.shape)
    if scale < 1.0:
        sub = cv2.resize(sub, None, fx=scale, fy=scale,
                         interpolation=cv2.INTER_NEAREST)

    def sym_of(img: np.ndarray) -> float:
        half = img.shape[1] // 2
        if half < 2:
            return 0.0
        left = img[:, :half]
        right = np.fliplr(img[:, img.shape[1] - half:])
        inter = np.logical_and(left, right).sum()
        union = np.logical_or(left, right).sum()
        return float(inter) / float(max(1, union))

    h, w = sub.shape[:2]
    ctr = (w / 2.0, h / 2.0)
    best_a, best_s = 0.0, sym_of(sub)
    base_s = best_s
    a = -span
    while a <= span + 1e-6:
        if abs(a) > 1e-9:
            M = cv2.getRotationMatrix2D(ctr, a, 1.0)
            rot = cv2.warpAffine(sub, M, (w, h), flags=cv2.INTER_NEAREST)
            s = sym_of(rot)
            if s > best_s:
                best_s, best_a = s, a
        a += step
    gain = best_s - base_s
    conf = float(np.clip(gain / 0.06, 0.0, 1.0)) * float(
        np.clip(best_s, 0.0, 1.0))
    # اصطلاح الإشارة: `best_a` هي زاوية الدوران التي **تُصلح**
    # المنتج، والإشارات الثلاث الأخرى تعُد زاوية **ميل المنتج**
    # نفسه. والقياس أكد التعارض: ميل −11° ← الثلاث أعطت −11°
    # والتناطر +11°، فسحبت المتوسط المرجّح إلى النصف (−6.09°).
    return -_norm45(best_a), conf


# ═════════════════════════ الدمج ═════════════════════════

def estimate_tilt(image_bgr: np.ndarray,
                  mask: np.ndarray | None = None,
                  *,
                  use_text: bool = True,
                  max_auto_deg: float = 20.0,
                  min_confidence: float = 0.35,
                  ) -> TiltEstimate:
    """يقدّر ميل المنتج بدمج الإشارات الأربع بترجيح.

    الدمج **دائري** (متوسط الجيب والجيب التمام) لا حسابي، لأن
    الزوايا دورية: متوسط 44° و−44° حسابيًا صفر، ودائريًا 90°≡0°
    وهو الصحيح.
    """
    est = TiltEstimate()
    m = _mask_of(mask if mask is not None else image_bgr)
    if not m.any():
        est.notes.append("لا منتج — لا تقويم")
        return est

    sig: dict[str, tuple[float, float]] = {}
    if use_text:
        sig["text"] = text_line_angle(image_bgr, m)
    sig["edge"] = edge_line_angle(m)
    sig["rect"] = min_rect_angle(m)
    sig["symmetry"] = symmetry_angle(m)

    # أوزان الأولوية: النص أقوى إشارة (كما اقترح المالك)
    prior = {"text": 1.60, "edge": 1.15, "rect": 0.70, "symmetry": 1.00}
    vs, ws = [], []
    for k, (ang, conf) in sig.items():
        w = conf * prior.get(k, 1.0)
        est.signals[k] = (round(ang, 3), round(conf, 3))
        if conf > 0.05:
            vs.append(ang)
            ws.append(w)

    if not vs:
        est.notes.append("لا إشارة موثوقة — لا تقويم")
        return est

    # متوسط دائري على مدى 90° (الزوايا هنا مطبَّعة إلى ±45)
    arr = np.radians(np.array(vs) * 4.0)      # ×4 ⇒ 45° تصير 180°
    wt = np.array(ws)
    s = float(np.sum(wt * np.sin(arr)))
    c = float(np.sum(wt * np.cos(arr)))
    if abs(s) < 1e-12 and abs(c) < 1e-12:
        est.notes.append("إشارات متعارضة تمامًا — لا تقويم")
        return est
    merged = float(np.degrees(np.arctan2(s, c)) / 4.0)
    est.angle = _norm45(merged)

    # الثقة: قوة الاتفاق (طول المتجه المحصّل ÷ مجموع الأوزان)
    r = float(np.hypot(s, c)) / float(max(1e-9, wt.sum()))
    est.confidence = float(np.clip(r, 0.0, 1.0))

    if abs(est.angle) < 0.35:
        est.notes.append("المنتج مستقيم أصلًا")
        est.angle = 0.0
        return est
    if est.confidence < min_confidence:
        est.needs_review = True
        est.notes.append(
            f"ثقة منخفضة {est.confidence:.2f} < {min_confidence} "
            f"⇒ يحتاج مراجعة")
    if abs(est.angle) > max_auto_deg:
        est.needs_review = True
        est.notes.append(
            f"الزاوية {est.angle:.1f}° تتجاوز ±{max_auto_deg:.0f}° "
            f"⇒ يحتاج تأكيد المالك")
    return est


def straighten(image_bgr: np.ndarray, angle_deg: float,
               alpha: np.ndarray | None = None,
               border_white: bool = True,
               ) -> tuple[np.ndarray, np.ndarray | None]:
    """يدوّر الصورة (والألفا معها) بزاوية التصحيح مع توسيع الإطار.

    الإطار يُوسَّع لئلا تُقطع الزوايا بالدوران، **فيجب أن يتلوه
    اقتصاص محسوب** (`product_finish_v2.smart_crop_box`).
    """
    if abs(angle_deg) < 1e-3:
        return image_bgr, alpha
    h, w = image_bgr.shape[:2]
    ctr = (w / 2.0, h / 2.0)
    M = cv2.getRotationMatrix2D(ctr, angle_deg, 1.0)
    cos = abs(M[0, 0]); sin = abs(M[0, 1])
    nw = int(h * sin + w * cos)
    nh = int(h * cos + w * sin)
    M[0, 2] += nw / 2.0 - ctr[0]
    M[1, 2] += nh / 2.0 - ctr[1]
    bval = (255, 255, 255) if border_white else (0, 0, 0)
    out = cv2.warpAffine(image_bgr, M, (nw, nh), flags=cv2.INTER_CUBIC,
                         borderMode=cv2.BORDER_CONSTANT, borderValue=bval)
    out_a = None
    if alpha is not None:
        a = alpha
        if a.ndim == 3:
            a = a[:, :, 0]
        out_a = cv2.warpAffine(a, M, (nw, nh), flags=cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return out, out_a
