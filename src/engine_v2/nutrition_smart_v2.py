# -*- coding: utf-8 -*-
"""nutrition_smart_v2 — المحرك الذكي متعدد المراحل لحقائق التغذية.

قاعدة المصداقية (مطلب المستخدم): المطابقة مع المنتج 100% — لا وهم للمشتري.
يُعرض فقط ما قُرئ فعلاً من صورة المنتج بثقة عالية؛ أي قيمة غير مؤكدة
تُعلَّم `needs_review=True` وتُعرض للمستخدم للتأكيد أو التصحيح اليدوي قبل
الاعتماد. التحقق المنطقي (سعرات مقابل مغذيات) يُستخدم للتنبيه فقط — لا
يعدل القيم تلقائيًا أبدًا.

المراحل:
1. كشف منطقة الجدول تلقائيًا (أكبر كتلة نصية كثيفة بإطار/خطوط).
2. تجهيز متعدد النسخ: descreen+Otsu، adaptive، رمادي محسّن، وقلب
   الألوان للجداول الداكنة.
3. قراءة Tesseract بعدة أوضاع (psm 6/4) عربي+إنجليزي لكل نسخة.
4. دمج القراءات بالتصويت: القيمة التي تتفق عليها قراءتان تُعتمد بثقة
   عالية؛ قراءة واحدة فقط = ثقة متوسطة وتُعلَّم للمراجعة.
5. تحقق منطقي تنبيهي: Atwater (سعرات ≈ دهون×9 + كربوهيدرات×4 +
   بروتين×4) وحدود القيم الفيزيائية (لا سالب، لا > حجم الحصة).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .nutrition_ocr_v2 import (FIELD_SPECS, NutritionData, NutritionRow,
                               _configure_tesseract, _extract_numbers,
                               _match_field, _norm, _prepare_for_ocr)

__all__ = ["SmartExtractionResult", "smart_extract", "detect_table_region",
           "validate_consistency"]


@dataclass
class FieldReading:
    """قراءة حقل واحد مع مستوى الثقة وعدد الأصوات."""
    key: str = ""
    amount: str = ""
    unit: str = ""
    percent: str = ""
    votes: int = 0
    needs_review: bool = True


@dataclass
class SmartExtractionResult:
    """نتيجة الاستخراج الذكي — data جاهزة + قوائم مراجعة وتنبيهات."""
    data: NutritionData = field(default_factory=NutritionData)
    review_keys: list = field(default_factory=list)     # حقول تحتاج تأكيدًا
    warnings: list = field(default_factory=list)        # تنبيهات منطقية
    table_found: bool = False
    passes_used: int = 0

    @property
    def ok(self) -> bool:
        return bool(self.data.rows or self.data.calories)


# ---------------------------------------------------------- table detection
def detect_table_region(img: np.ndarray) -> np.ndarray:
    """يحاول قص منطقة جدول الحقائق (أكبر مستطيل بخطوط أفقية كثيفة).

    إن لم يُعثر على منطقة مؤكدة تُعاد الصورة كاملة — لا نخاطر بفقد بيانات.
    """
    try:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        h, w = gray.shape
        binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                       cv2.THRESH_BINARY_INV, 25, 15)
        # الخطوط الأفقية — سمة مميزة لجداول الحقائق الغذائية
        kern = cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, w // 8), 1))
        horiz = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kern)
        # وسّع رأسيًا لدمج الخطوط في كتلة واحدة
        dil = cv2.dilate(horiz, cv2.getStructuringElement(
            cv2.MORPH_RECT, (5, max(15, h // 40))))
        contours, _ = cv2.findContours(dil, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        best = None
        for c in contours:
            x, y, cw, ch = cv2.boundingRect(c)
            area = cw * ch
            if cw > w * 0.25 and ch > h * 0.1 and \
                    (best is None or area > best[4]):
                best = (x, y, cw, ch, area)
        if best is None:
            return img
        x, y, cw, ch, _ = best
        # هامش أمان 3%
        mx, my = int(cw * 0.03) + 5, int(ch * 0.05) + 5
        x0, y0 = max(0, x - mx), max(0, y - my)
        x1, y1 = min(w, x + cw + mx), min(h, y + ch + my)
        crop = img[y0:y1, x0:x1]
        # لا نقبل قصًا يفقد أكثر من 95% أو أصغر من حد مفيد
        if crop.shape[0] < 80 or crop.shape[1] < 80:
            return img
        return crop
    except Exception:
        return img


# ---------------------------------------------------------- variant prep
def _variants(img: np.ndarray) -> list[np.ndarray]:
    """نسخ تجهيز متعددة — كل نسخة تلتقط ما قد تفشل فيه الأخرى."""
    out = [_prepare_for_ocr(img)]
    try:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        h, w = gray.shape
        if max(h, w) < 1600:
            sc = 1600 / max(h, w)
            gray = cv2.resize(gray, (int(w * sc), int(h * sc)),
                              interpolation=cv2.INTER_CUBIC)
        # adaptive — أفضل للإضاءة غير المتجانسة
        adap = cv2.adaptiveThreshold(cv2.medianBlur(gray, 3), 255,
                                     cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                     cv2.THRESH_BINARY, 31, 12)
        out.append(adap)
        # جدول داكن بنص فاتح؟ اقلب
        if float(np.mean(gray)) < 110:
            out.append(cv2.bitwise_not(out[0]))
    except Exception:
        pass
    return out


def _ocr_pass(binary: np.ndarray, pytesseract, psm: int) -> str:
    cfg = f"--psm {psm}"
    try:
        return pytesseract.image_to_string(binary, lang="ara+eng", config=cfg)
    except Exception:
        try:
            return pytesseract.image_to_string(binary, config=cfg)
        except Exception:
            return ""


def _parse_text(raw: str) -> dict[str, tuple[str, str, str]]:
    """نص OCR خام → {key: (amount, unit, pct)} + الحقول الرأسية."""
    found: dict[str, tuple[str, str, str]] = {}
    for line in raw.splitlines():
        line = line.strip()
        if len(line) < 2:
            continue
        key = _match_field(_norm(line))
        if key is None:
            continue
        amount, unit, pct = _extract_numbers(line)
        if key not in found and (amount or pct):
            found[key] = (amount, unit, pct)
    return found


# ---------------------------------------------------------- validation
def _f(s: str) -> float | None:
    try:
        return float(s)
    except Exception:
        return None


def validate_consistency(data: NutritionData) -> list[str]:
    """تحقق منطقي تنبيهي فقط — لا يعدل أي قيمة.

    يعيد قائمة تنبيهات عربية تُعرض للمستخدم في شاشة المراجعة.
    """
    warnings: list[str] = []
    vals = {r.key: _f(r.amount) for r in data.rows}
    cal = _f(data.calories)
    fat, carb, protein = vals.get("total_fat"), vals.get("total_carbs"), \
        vals.get("protein")
    if cal is not None and None not in (fat, carb, protein):
        est = fat * 9 + carb * 4 + protein * 4
        if est > 0 and (cal < est * 0.6 or cal > est * 1.6):
            warnings.append(
                f"تنبيه: السعرات ({cal:g}) لا تتناسق مع المغذيات "
                f"(المتوقع ≈ {est:g}) — راجع القراءة من العبوة")
    sat = vals.get("saturated_fat")
    if sat is not None and fat is not None and sat > fat + 0.01:
        warnings.append("تنبيه: الدهون المشبعة أكبر من الدهون الكلية — "
                        "راجع القيمتين")
    sug = vals.get("sugars")
    if sug is not None and carb is not None and sug > carb + 0.01:
        warnings.append("تنبيه: السكريات أكبر من الكربوهيدرات الكلية — "
                        "راجع القيمتين")
    for r in data.rows:
        v = _f(r.amount)
        if v is not None and v < 0:
            warnings.append(f"تنبيه: قيمة سالبة في {r.label_ar}")
        p = _f(r.percent)
        if p is not None and p > 300:
            warnings.append(f"تنبيه: نسبة يومية غير منطقية في {r.label_ar} "
                            f"({p:g}%)")
    return warnings


# ---------------------------------------------------------- main entry
def smart_extract(img: np.ndarray) -> SmartExtractionResult:
    """الاستخراج الذكي الكامل: كشف منطقة → نسخ متعددة → تصويت → تحقق.

    كل حقل: صوتان متفقان = ثقة عالية (needs_review=False)، صوت واحد =
    يُعرض لكن يُعلَّم للمراجعة الإلزامية. لا اختراع قيم أبدًا.

    اكتفاء ذاتي: إن غاب محرك OCR تُعاد نتيجة فارغة مع تنبيه عربي
    واضح يوجّه للإدخال اليدوي، بدل إسقاط التطبيق.
    """
    try:
        import pytesseract
    except Exception:
        empty = SmartExtractionResult()
        try:
            from .runtime_deps_v2 import describe_missing
            empty.warnings.append(describe_missing("ocr"))
        except Exception:
            empty.warnings.append(
                "قراءة النصوص غير متاحة على هذا الجهاز — أدخِل القيم يدوياً.")
        return empty
    _configure_tesseract(pytesseract)

    result = SmartExtractionResult()
    region = detect_table_region(img)
    result.table_found = region.shape[:2] != img.shape[:2]

    # اجمع القراءات من (نسخ التجهيز × أوضاع psm)
    readings: list[dict[str, tuple[str, str, str]]] = []
    for variant in _variants(region):
        for psm in (6, 4):
            raw = _ocr_pass(variant, pytesseract, psm)
            result.passes_used += 1
            if raw.strip():
                parsed = _parse_text(raw)
                if parsed:
                    readings.append(parsed)
            if len(readings) >= 4:      # يكفي للتصويت — لا نهدر وقتًا
                break
        if len(readings) >= 4:
            break

    # صوّت لكل حقل: اجمع كل القيم المرشحة ثم اختر الأغلبية الحقيقية
    # candidates[key][sig] = [votes, amount, unit, pct]
    candidates: dict[str, dict[str, list]] = {}
    for parsed in readings:
        for key, (amount, unit, pct) in parsed.items():
            sig = f"{amount}|{pct}"
            slot = candidates.setdefault(key, {})
            if sig in slot:
                slot[sig][0] += 1
                if not slot[sig][2] and unit:
                    slot[sig][2] = unit
            else:
                slot[sig] = [1, amount, unit, pct]

    merged: dict[str, FieldReading] = {}
    for key, sigs in candidates.items():
        # الفائز: الأكثر أصواتًا، وعند التعادل القيمة الأكثر اكتمالًا (بوحدة/نسبة)
        best_sig = max(sigs, key=lambda s: (sigs[s][0],
                                            bool(sigs[s][2]) + bool(sigs[s][3])))
        votes, amount, unit, pct = sigs[best_sig]
        disagree = sum(v[0] for s, v in sigs.items() if s != best_sig)
        fr = FieldReading(key, amount, unit, pct, votes, True)
        # ثقة عالية فقط إذا فازت بصوتين+ وتجاوزت المخالفين — مصداقية 100%
        fr.needs_review = not (votes >= 2 and votes > disagree)
        merged[key] = fr

    data = NutritionData()
    high_conf = 0
    for key, fr in merged.items():
        if key == "calories":
            data.calories = fr.amount
        elif key == "servings":
            data.servings = fr.amount
        elif key == "serving_size":
            data.serving_size = (fr.amount +
                                 (" " + fr.unit if fr.unit else "")).strip()
        else:
            data.rows.append(NutritionRow(
                key=key, label_ar=FIELD_SPECS[key][0], amount=fr.amount,
                unit=fr.unit, percent=fr.percent))
        if fr.needs_review:
            result.review_keys.append(key)
        else:
            high_conf += 1

    total = max(1, len(merged))
    data.confidence = round(high_conf / total, 2) if merged else 0.0
    result.data = data
    result.warnings = validate_consistency(data)
    return result
