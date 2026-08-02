# -*- coding: utf-8 -*-
"""date_blur_v2 — كشف تواريخ الإنتاج/الانتهاء المطبوعة وطمسها بتمويه طفيف
بحسب لون المنتج (Date Redaction Engine).

يعمل تلقائيًا على كل صورة:
1) ترشيح بصري سريع لمناطق نص نقطي/محفور (dot-matrix / inkjet) — النمط
   الشائع لطباعة التواريخ على العبوات.
2) تأكيد بـ OCR خفيف (pytesseract على المناطق المرشحة فقط) + أنماط تواريخ:
   2025/05/12 ، 12.05.2025 ، EXP 2026 ، PROD ، BB ، الإنتاج/الانتهاء ، أشهر
   إنجليزية JAN..DEC.
3) طمس طفيف متناسق مع لون المنتج: inpaint (TELEA) يملأ المنطقة بخامة
   العبوة المحيطة ثم دمج ناعم — لا بقعة ضبابية ظاهرة.

حماية: لا يطمس داخل جدول الحقائق الغذائية ولا فوق الباركود.
وضع يدوي: blur_region_manual(img, box) لنفس الطمس بلون المنتج على منطقة
يحددها المستخدم في المحرر إذا لم يُكشف التاريخ تلقائيًا.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import cv2
import numpy as np

__all__ = [
    "DateRegion", "detect_date_regions", "blur_regions",
    "blur_region_manual", "auto_blur_dates",
]

# أنماط التواريخ — أرقام غربية وعربية
_AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_TRANS = str.maketrans(_AR_DIGITS, "0123456789")

_DATE_PATTERNS = [
    re.compile(r"\d{1,4}\s*[/.\-]\s*\d{1,2}\s*[/.\-]\s*\d{1,4}"),   # 12/05/2025
    re.compile(r"\b\d{1,2}\s*[/\-]\s*20\d{2}\b"),                    # 05/2026
    re.compile(r"(?:EXP|PRD|PROD|MFG|MFD|BBE|E\s*:|P\s*:)\W*\d", re.I),
    re.compile(r"(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
               r"\W*20?\d{2}", re.I),
    re.compile(r"\b20\d{2}\s*[/.\-]\s*\d{1,2}\b"),                   # 2025/05
    re.compile(r"(?:الإنتاج|الانتهاء|الصلاحية|تاريخ انتاج|تاريخ إنتاج|ينتهي في)"),
]

# كلمات تدل أن السطر حقائق غذائية/مكونات — لا يُطمس أبدًا
_NUTRITION_HINTS = re.compile(
    r"(?:KCAL|CAL|ENERGY|PROTEIN|FAT|CARB|SUGAR|SODIUM|SALT|FIBER|FIBRE|"
    r"VITAMIN|CHOLESTEROL|SERVING|INGREDIENT|NET\s*W|\d\s*G\b|\d\s*MG\b|"
    r"سعر|طاقة|بروتين|دهون|كربوهيدرات|سكر|صوديوم|ملح|ألياف|مكونات)", re.I)


def _looks_like_date(text: str) -> bool:
    t = (text or "").translate(_TRANS).strip()
    if len(t) < 4:
        return False
    # سطر حقائق غذائية/مكونات لا يُعامل كتاريخ إلا بصيغة تاريخ كاملة صريحة
    if _NUTRITION_HINTS.search(t) and not _DATE_PATTERNS[0].search(t):
        return False
    digits = sum(ch.isdigit() for ch in t)
    if digits < 2 and not any(p.search(t) for p in _DATE_PATTERNS[2:]):
        return False
    return any(p.search(t) for p in _DATE_PATTERNS)


@dataclass
class DateRegion:
    x: int
    y: int
    w: int
    h: int
    text: str = ""
    confidence: float = 0.0

    def box(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.w, self.h


# ----------------------------------------------------------- candidates
def _candidate_text_boxes(img: np.ndarray) -> list[tuple[int, int, int, int]]:
    """مناطق نص مرشحة (سريعة، بلا OCR): تدرجات كثيفة تتجمع في أشرطة سطرية."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    h, w = gray.shape[:2]
    grad = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    _, bw = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    kx = max(6, w // 90)
    connected = cv2.morphologyEx(
        bw, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (kx, 3)))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(connected, 8)
    boxes = []
    for i in range(1, n):
        x, y, bw_, bh_, area = stats[i]
        if bh_ < 8 or bh_ > h * 0.08:        # سطر تاريخ: ارتفاع محدود فعلاً
            continue
        if bw_ < bh_ * 1.6 or bw_ > w * 0.6:   # شريط أفقي وليس إطارًا/عنوانًا
            continue
        if (bw_ * bh_) > (h * w) * 0.03:       # مساحة سطر تاريخ معقولة فقط
            continue
        fill = area / max(1, bw_ * bh_)
        if fill < 0.18:
            continue
        boxes.append((int(x), int(y), int(bw_), int(bh_)))
    # دمج الصناديق المتقاربة على نفس السطر
    boxes.sort(key=lambda b: (b[1], b[0]))
    merged: list[list[int]] = []
    for b in boxes:
        placed = False
        for m in merged:
            if abs(b[1] - m[1]) < max(b[3], m[3]) * 0.6 and \
                    b[0] < m[0] + m[2] + max(b[3], m[3]) * 2 and \
                    m[0] < b[0] + b[2] + max(b[3], m[3]) * 2:
                x0 = min(m[0], b[0]); y0 = min(m[1], b[1])
                x1 = max(m[0] + m[2], b[0] + b[2])
                y1 = max(m[1] + m[3], b[1] + b[3])
                m[:] = [x0, y0, x1 - x0, y1 - y0]
                placed = True
                break
        if not placed:
            merged.append(list(b))
    return [tuple(m) for m in merged][:40]


def _protected_mask(img: np.ndarray) -> np.ndarray:
    """قناع المناطق المحمية (جدول الحقائق + باركود) — لا طمس داخلها."""
    h, w = img.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    try:
        from engine_v2.nutrition_v2 import detect_nutrition_table
        box = detect_nutrition_table(img)
        if box:
            x, y, bw_, bh_ = box
            # إذا غطى الصندوق معظم الصورة فهو جسم العبوة كلها وليس جدولاً — تجاهله
            if (bw_ * bh_) < (h * w) * 0.35:
                mask[max(0, y):y + bh_, max(0, x):x + bw_] = 255
    except Exception:
        pass
    # باركود: شرائط عمودية كثيفة
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    vert = (np.abs(gx) - np.abs(gy)) > 40
    vert8 = (vert * 255).astype(np.uint8)
    vert8 = cv2.morphologyEx(vert8, cv2.MORPH_CLOSE,
                             np.ones((9, 9), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(vert8, 8)
    for i in range(1, n):
        x, y, bw_, bh_, area = stats[i]
        if area > (h * w) * 0.004 and bw_ > bh_ * 0.8:
            mask[y:y + bh_, x:x + bw_] = 255
    return mask


# -------------------------------------------------------------- detect
def detect_date_regions(img: np.ndarray,
                        use_ocr: bool = True,
                        max_candidates: int = 12) -> list[DateRegion]:
    """كشف مناطق التواريخ المطبوعة. يعيد قائمة DateRegion مع الثقة.

    مُحسّن للسرعة: المرشحات تُحسب على نسخة مصغرة، وOCR يجري فقط
    على أفضل المرشحين (أولوية لأسفل الصورة حيث تُطبع التواريخ عادة)."""
    regions: list[DateRegion] = []
    if img is None or img.size == 0:
        return regions
    H0, W0 = img.shape[:2]
    # مرشحات على نسخة مصغرة للسرعة (الدقة تكفي لتحديد الصناديق)
    scale = 1.0
    work = img
    if max(H0, W0) > 1400:
        scale = 1400 / max(H0, W0)
        work = cv2.resize(img, (int(W0 * scale), int(H0 * scale)),
                          interpolation=cv2.INTER_AREA)
    candidates = _candidate_text_boxes(work)
    if not candidates:
        return regions
    if scale != 1.0:
        inv = 1.0 / scale
        candidates = [(int(x * inv), int(y * inv),
                       int(w_ * inv), int(h_ * inv))
                      for (x, y, w_, h_) in candidates]
    # قيود صارمة بعد إرجاع المقياس الأصلي: منطقة تاريخ مطبوع لا تتجاوز
    # 8% من ارتفاع الصورة ولا 60% من عرضها ولا 3% من مساحتها
    candidates = [(x, y, w_, h_) for (x, y, w_, h_) in candidates
                  if h_ <= H0 * 0.08 and w_ <= W0 * 0.6
                  and (w_ * h_) <= (H0 * W0) * 0.03]
    # أولوية: أسفل الصورة أولاً (موضع طباعة التواريخ المعتاد) ثم الأعلى
    candidates.sort(key=lambda b: -(b[1] + b[3]))
    candidates = candidates[:max_candidates]
    protected = _protected_mask(work)
    if scale != 1.0:
        protected = cv2.resize(protected, (W0, H0),
                               interpolation=cv2.INTER_NEAREST)
    ocr = None
    if use_ocr:
        try:
            import pytesseract
            ocr = pytesseract
        except Exception:
            ocr = None
    h, w = img.shape[:2]
    ar_budget = 2   # محاولات OCR عربية مكلفة — حد أقصى

    # إعداد مرشحات OCR مرة واحدة ثم تشغيل tesseract في **دفعة واحدة**.
    # كل استدعاء لـ image_to_string يُشغّل عملية نظام مستقلة (~0.25s)،
    # فـ 12 مرشحًا = ~3s. دمج المرشحين في لوحة رأسية واحدة بفواصل
    # بيضاء يجعلها استدعاءً واحدًا بـ psm 6، ثم تُقرأ الأسطر مرتبة.
    boxes: list[tuple] = []
    for (x, y, bw_, bh_) in candidates:
        in_protected = protected[y:y + bh_, x:x + bw_].mean() > 60
        pad = max(2, bh_ // 4)
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(w, x + bw_ + pad), min(h, y + bh_ + pad)
        if x1 <= x0 or y1 <= y0:
            continue
        boxes.append((x0, y0, x1, y1, in_protected, bh_))

    batch_texts: dict[int, str] = {}
    if ocr is not None and boxes:
        try:
            rois = []
            for (x0, y0, x1, y1, _ip, _bh) in boxes:
                roi = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
                if roi.shape[0] < 34:
                    sc = 34 / roi.shape[0]
                    roi = cv2.resize(roi, None, fx=sc, fy=sc,
                                     interpolation=cv2.INTER_CUBIC)
                roi = cv2.threshold(roi, 0, 255,
                                    cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
                rois.append(roi)
            gap = 18
            sheet_w = max(r.shape[1] for r in rois) + 2 * gap
            sheet_h = sum(r.shape[0] + gap for r in rois) + gap
            sheet = np.full((sheet_h, sheet_w), 255, np.uint8)
            offsets = []
            cy = gap
            for r in rois:
                sheet[cy:cy + r.shape[0], gap:gap + r.shape[1]] = r
                offsets.append(cy)
                cy += r.shape[0] + gap
            raw = ocr.image_to_string(
                sheet, lang="eng",
                config="--psm 6 -c tessedit_char_whitelist="
                       "0123456789/.-:EXPRODBMFGJANUYLGSTCVebrpamjunlgsoctvd ")
            lines = [ln.strip() for ln in (raw or "").splitlines()
                     if ln.strip()]
            # ربط الأسطر بالمرشحين بالترتيب (لوحة رأسية مرتبة)
            for i, ln in enumerate(lines[:len(boxes)]):
                batch_texts[i] = ln
        except Exception:
            batch_texts = {}

    ar_pending: list[int] = []
    for bi, (x0, y0, x1, y1, in_protected, bh_) in enumerate(boxes):
        if len(regions) >= 4:
            break  # إيقاف مبكر — طمس 4 تواريخ يكفي لأي عبوة
        crop = img[y0:y1, x0:x1]
        text, conf = "", 0.0
        if ocr is not None:
            try:
                text = (batch_texts.get(bi) or "").strip()
                if _looks_like_date(text):
                    # داخل المنطقة المحمية نطمس فقط التاريخ الصريح المؤكد
                    # (صيغة رقمية كاملة أو EXP/PROD) — لا قيم الحقائق الغذائية
                    strict = bool(_DATE_PATTERNS[0].search(
                        text.translate(_TRANS)) or
                        _DATE_PATTERNS[2].search(text))
                    if in_protected and not strict:
                        conf = 0.0
                    else:
                        conf = 0.9
                else:
                    # محاولة عربية — تُأجّل لدفعة واحدة بعد الحلقة
                    if not in_protected and ar_budget > 0:
                        ar_budget -= 1
                        ar_pending.append(bi)
            except Exception:
                conf = 0.0
        if conf > 0:
            regions.append(DateRegion(x0, y0, x1 - x0, y1 - y0, text, conf))

    # دفعة عربية واحدة فقط إن لم يُعط المسار الإنجليزي أي نتيجة.
    # التواريخ المطبوعة رقمية في الغالب، فإن نجح الإنجليزي نتجاوز ara
    # تمامًا (توفير ~0.5s لكل صورة بلا أي خسارة في الدقة).
    if ocr is not None and ar_pending and not regions:
        try:
            crops = []
            for bi in ar_pending:
                x0, y0, x1, y1 = boxes[bi][:4]
                c = img[y0:y1, x0:x1]
                if c.shape[0] < 34:
                    sc = 34 / c.shape[0]
                    c = cv2.resize(c, None, fx=sc, fy=sc,
                                   interpolation=cv2.INTER_CUBIC)
                crops.append(c)
            gap = 18
            sw = max(c.shape[1] for c in crops) + 2 * gap
            sh = sum(c.shape[0] + gap for c in crops) + gap
            sheet2 = np.full((sh, sw, 3), 255, np.uint8)
            cy = gap
            for c in crops:
                sheet2[cy:cy + c.shape[0], gap:gap + c.shape[1]] = c
                cy += c.shape[0] + gap
            raw2 = ocr.image_to_string(sheet2, lang="ara+eng",
                                       config="--psm 6")
            lines2 = [ln.strip() for ln in (raw2 or "").splitlines()
                      if ln.strip()]
            for i, bi in enumerate(ar_pending[:len(lines2)]):
                if _looks_like_date(lines2[i]):
                    x0, y0, x1, y1 = boxes[bi][:4]
                    regions.append(DateRegion(x0, y0, x1 - x0, y1 - y0,
                                              lines2[i], 0.75))
                    if len(regions) >= 4:
                        break
        except Exception:
            pass
    return regions


# ---------------------------------------------------------------- blur
def _color_match_fill(img: np.ndarray, box: tuple[int, int, int, int],
                      feather: int = 5) -> np.ndarray:
    """طمس طفيف بحسب لون المنتج: inpaint بخامة الجوار + دمج ناعم.

    مُسرّع: كل العمليات تجري على نافذة محلية حول المنطقة فقط
    بدل الصورة الكاملة — أسرع عشرات المرات على الصور الكبيرة."""
    x, y, w_, h_ = box
    H, W = img.shape[:2]
    x = max(0, min(x, W - 1)); y = max(0, min(y, H - 1))
    w_ = max(1, min(w_, W - x)); h_ = max(1, min(h_, H - y))
    # نافذة محلية موسعة حول المنطقة — مقيّدة بسقف لمنع
    # توسّعها على المناطق العريضة (النافذة الأكبر = inpaint أبطأ)
    pad = max(16, feather * 4, min(min(w_, h_), 64))
    wy0, wy1 = max(0, y - pad), min(H, y + h_ + pad)
    wx0, wx1 = max(0, x - pad), min(W, x + w_ + pad)
    win = img[wy0:wy1, wx0:wx1]
    ly, lx = y - wy0, x - wx0
    mask = np.zeros(win.shape[:2], np.uint8)
    mask[ly:ly + h_, lx:lx + w_] = 255
    # نصف قطر inpaint مقيّد بـ 4: زمن TELEA ينمو تربيعيًا مع نصف
    # القطر (radius=20 → 1.07s مقابل radius=3 → 0.03s لنفس المنطقة)،
    # والمنطقة تُموّه بـ Gaussian بعده أصلاً فلا فرق بصري يُذكر.
    radius = max(3, min(4, min(w_, h_) // 3))
    # سقف زمني إضافي: المناطق الكبيرة تُعالج على نسخة
    # مصغرة ثم تُكبر (الطمس لا يحتاج دقة عالية أصلاً)
    _scale = 1.0
    if mask.sum() // 255 > 20000:
        _scale = (20000.0 / (mask.sum() // 255)) ** 0.5
        small_win = cv2.resize(win, None, fx=_scale, fy=_scale,
                               interpolation=cv2.INTER_AREA)
        small_mask = cv2.resize(mask, (small_win.shape[1],
                                       small_win.shape[0]),
                                interpolation=cv2.INTER_NEAREST)
        try:
            small_fill = cv2.inpaint(small_win, small_mask,
                                     max(3, int(radius * _scale)),
                                     cv2.INPAINT_TELEA)
            filled = cv2.resize(small_fill, (win.shape[1], win.shape[0]),
                                interpolation=cv2.INTER_LINEAR)
        except Exception:
            filled = win.copy()
            filled[ly:ly + h_, lx:lx + w_] = np.median(
                win.reshape(-1, 3), axis=0)
        _done = True
    else:
        _done = False
    try:
        if not _done:
            filled = cv2.inpaint(win, mask, radius, cv2.INPAINT_TELEA)
    except Exception:
        filled = win.copy()
        ring = win.reshape(-1, 3)
        med = np.median(ring, axis=0)
        filled[ly:ly + h_, lx:lx + w_] = med
    # تمويه خفيف داخل المنطقة ليمتزج مع خامة الطباعة
    region = filled[ly:ly + h_, lx:lx + w_]
    k = max(3, (min(w_, h_) // 6) | 1)
    filled[ly:ly + h_, lx:lx + w_] = cv2.GaussianBlur(region, (k, k), 0)
    # دمج ناعم بحواف ريشية داخل النافذة
    soft = cv2.GaussianBlur(mask.astype(np.float32) / 255.0,
                            (0, 0), max(1.5, feather))
    soft3 = soft[:, :, None]
    blended = win.astype(np.float32) * (1 - soft3) + \
        filled.astype(np.float32) * soft3
    # يُعدّل داخل النافذة مباشرة دون نسخ الصورة الكاملة
    # (المستدعي مسؤول عن تمرير نسخة قابلة للتعديل)
    img[wy0:wy1, wx0:wx1] = np.clip(blended, 0, 255).astype(np.uint8)
    return img


def blur_regions(img: np.ndarray,
                 regions: list[DateRegion] | list[tuple],
                 mode: str = "color_match") -> np.ndarray:
    """يطمس قائمة مناطق. mode: color_match (افتراضي) | gaussian."""
    out = np.ascontiguousarray(img.copy())
    for r in regions:
        box = r.box() if isinstance(r, DateRegion) else tuple(r)
        if mode == "gaussian":
            x, y, w_, h_ = box
            H, W = out.shape[:2]
            x = max(0, min(x, W - 1)); y = max(0, min(y, H - 1))
            w_ = max(1, min(w_, W - x)); h_ = max(1, min(h_, H - y))
            k = max(9, (min(w_, h_) // 2) | 1)
            out[y:y + h_, x:x + w_] = cv2.GaussianBlur(
                out[y:y + h_, x:x + w_], (k, k), 0)
        else:
            out = _color_match_fill(out, box)
    return out


def blur_region_manual(img: np.ndarray, box: tuple[int, int, int, int],
                       mode: str = "color_match") -> np.ndarray:
    """الوضع اليدوي من المحرر: طمس منطقة يحددها المستخدم بنفس منطق
    التمويه الطفيف بلون المنتج."""
    return blur_regions(img, [tuple(box)], mode=mode)


def auto_blur_dates(img: np.ndarray,
                    use_ocr: bool = True) -> tuple[np.ndarray, int]:
    """الكشف والطمس التلقائي دفعة واحدة. يعيد (الصورة، عدد المناطق المطموسة)."""
    regions = detect_date_regions(img, use_ocr=use_ocr)
    if not regions:
        return img, 0
    return blur_regions(img, regions), len(regions)
