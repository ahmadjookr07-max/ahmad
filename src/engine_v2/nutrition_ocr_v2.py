# -*- coding: utf-8 -*-
"""nutrition_ocr_v2 — استخراج قيم جدول حقائق التغذية عبر OCR.

Tesseract (ara+eng, psm 6) + قاموس مصطلحات ثنائي اللغة + استخراج الأرقام
والوحدات والنسب مع تحويل الأرقام العربية. تمر النتيجة دائمًا بشاشة مراجعة
إلزامية في الواجهة قبل الاعتماد.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import cv2
import numpy as np

FOOTNOTE_AR = ("٭ النسبة المئوية للقيمة اليومية مبنية على نظام غذائي "
               "يحتوي على ٢٠٠٠ سعرة حرارية.")

# key -> (label_ar, [aliases])
FIELD_SPECS: dict[str, tuple[str, list[str]]] = {
    "serving_size": ("حجم الحصة", ["حجم الحصه", "serving size", "حجم الحصة"]),
    "servings": ("عدد الحصص", ["عدد الحصص", "servings per container",
                                "عدد الحصص لكل عبوه"]),
    "calories": ("السعرات الحرارية", ["السعرات", "الطاقه", "الطاقة",
                                       "calories", "energy", "طاقة"]),
    "total_fat": ("الدهون الكلية", ["الدهون الكليه", "مجموع الدهون",
                                     "الدهون", "total fat", "fat"]),
    "saturated_fat": ("الدهون المشبعة", ["الدهون المشبعه", "دهون مشبعه",
                                          "saturated fat", "saturated"]),
    "trans_fat": ("الدهون المتحولة", ["الدهون المتحوله", "دهون متحوله",
                                       "trans fat", "trans"]),
    "cholesterol": ("الكوليسترول", ["كوليسترول", "cholesterol", "كولسترول"]),
    "sodium": ("الصوديوم", ["صوديوم", "sodium", "ملح", "الملح"]),
    "total_carbs": ("الكربوهيدرات الكلية", ["الكربوهيدرات", "كربوهيدرات",
                                             "total carbohydrate", "carbohydrate"]),
    "fiber": ("الألياف الغذائية", ["الالياف", "الياف", "dietary fiber",
                                    "fiber", "fibre"]),
    "sugars": ("السكريات", ["السكريات الكليه", "سكريات", "sugars", "sugar",
                             "total sugars"]),
    "added_sugars": ("سكريات مضافة", ["سكريات مضافه", "added sugars"]),
    "protein": ("البروتين", ["بروتين", "protein"]),
    "vitamin_d": ("فيتامين د", ["vitamin d", "فيتامين d"]),
    "calcium": ("الكالسيوم", ["كالسيوم", "calcium"]),
    "iron": ("الحديد", ["حديد", "iron"]),
    "potassium": ("البوتاسيوم", ["بوتاسيوم", "potassium"]),
    "vitamin_a": ("فيتامين أ", ["vitamin a", "فيتامين a"]),
    "vitamin_c": ("فيتامين ج", ["vitamin c", "فيتامين c"]),
}

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫", "0123456789.")
_UNIT_MAP = {"g": "غ", "غ": "غ", "جم": "غ", "غم": "غ", "gm": "غ",
             "mg": "ملغ", "ملغ": "ملغ", "مجم": "ملغ", "ملجم": "ملغ",
             "mcg": "مكغ", "مكغ": "مكغ", "ميكروغرام": "مكغ",
             "ml": "مل", "مل": "مل", "l": "لتر", "لتر": "لتر",
             "kcal": "سعرة", "سعره": "سعرة", "سعرة": "سعرة", "cal": "سعرة"}

# 20G ملتصقة: قد يقرأ tesseract "206" — افصل الرقم عن حرف الوحدة
_GLUED_G_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(g|mg|mcg|ml|غ|ملغ|مكغ|مل|جم|غم)\b",
                         re.IGNORECASE)
_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[%٪]")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


@dataclass
class NutritionRow:
    key: str = ""
    label_ar: str = ""
    amount: str = ""
    unit: str = ""
    percent: str = ""

    def to_dict(self) -> dict:
        return {"key": self.key, "label_ar": self.label_ar,
                "amount": self.amount, "unit": self.unit,
                "percent": self.percent}

    @classmethod
    def from_dict(cls, d: dict) -> "NutritionRow":
        return cls(d.get("key", ""), d.get("label_ar", ""),
                   d.get("amount", ""), d.get("unit", ""),
                   d.get("percent", ""))


@dataclass
class NutritionData:
    servings: str = ""
    serving_size: str = ""
    calories: str = ""
    rows: list = field(default_factory=list)   # list[NutritionRow]
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {"servings": self.servings, "serving_size": self.serving_size,
                "calories": self.calories, "confidence": self.confidence,
                "rows": [r.to_dict() for r in self.rows]}

    @classmethod
    def from_dict(cls, d: dict) -> "NutritionData":
        n = cls(d.get("servings", ""), d.get("serving_size", ""),
                d.get("calories", ""))
        n.confidence = d.get("confidence", 0.0)
        n.rows = [NutritionRow.from_dict(r) for r in d.get("rows", [])]
        return n


def blank_template() -> NutritionData:
    """قالب فارغ للإدخال اليدوي — كل الحقول القياسية."""
    data = NutritionData()
    main_keys = ["total_fat", "saturated_fat", "trans_fat", "cholesterol",
                 "sodium", "total_carbs", "fiber", "sugars", "added_sugars",
                 "protein", "vitamin_d", "calcium", "iron", "potassium"]
    for k in main_keys:
        data.rows.append(NutritionRow(key=k, label_ar=FIELD_SPECS[k][0]))
    return data


def _prepare_for_ocr(img: np.ndarray) -> np.ndarray:
    """descreen (median+gaussian) ثم تكبير 2000 + NlMeans + CLAHE + Otsu.

    ملاحظة مؤكدة: moiré يفسد adaptiveThreshold — Otsu بعد descreen أفضل.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    gray = cv2.medianBlur(gray, 3)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    h, w = gray.shape
    target = 2000
    if max(h, w) < target:
        sc = target / max(h, w)
        gray = cv2.resize(gray, (int(w * sc), int(h * sc)),
                          interpolation=cv2.INTER_CUBIC)
    gray = cv2.fastNlMeansDenoising(gray, None, 7, 7, 21)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


def _norm(text: str) -> str:
    t = text.translate(_AR_DIGITS)
    t = t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    t = t.replace("ة", "ه").replace("ى", "ي")
    return re.sub(r"\s+", " ", t).strip().lower()


def _match_field(line_norm: str) -> str | None:
    best_key, best_len = None, 0
    for key, (label_ar, aliases) in FIELD_SPECS.items():
        for alias in [label_ar] + aliases:
            a = _norm(alias)
            if a and a in line_norm and len(a) > best_len:
                best_key, best_len = key, len(a)
    return best_key


def _extract_numbers(line: str) -> tuple[str, str, str]:
    """يعيد (amount, unit_ar, pct) من سطر."""
    line = line.translate(_AR_DIGITS)
    pct = ""
    m = _PCT_RE.search(line)
    if m:
        pct = m.group(1)
        line = line[:m.start()] + line[m.end():]
    amount, unit = "", ""
    m = _GLUED_G_RE.search(line)
    if m:
        amount = m.group(1)
        unit = _UNIT_MAP.get(m.group(2).lower(), m.group(2))
    else:
        m = _NUM_RE.search(line)
        if m:
            amount = m.group(0)
    return amount, unit, pct


def _configure_tesseract(pytesseract) -> None:
    """على ويندوز: ابحث عن tesseract المحمول بجوار التنفيذي ثم Program Files."""
    import os
    import shutil
    import sys
    from pathlib import Path
    if shutil.which("tesseract"):
        return
    cands = []
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        cands.append(Path(meipass) / "tesseract" / "tesseract.exe")
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        cands.append(exe_dir / "tesseract" / "tesseract.exe")
        cands.append(exe_dir / "_internal" / "tesseract" / "tesseract.exe")
    cands.append(Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
                 / "Tesseract-OCR" / "tesseract.exe")
    for c in cands:
        try:
            if c.is_file():
                pytesseract.pytesseract.tesseract_cmd = str(c)
                tessdata = c.parent / "tessdata"
                if tessdata.is_dir():
                    os.environ.setdefault("TESSDATA_PREFIX", str(tessdata))
                return
        except Exception:
            continue


def ocr_available() -> bool:
    """هل قراءة النصوص متاحة فعلياً؟ فحص رخيص لا يرمي استثناءاً."""
    try:
        from .runtime_deps_v2 import have_ocr
        return have_ocr()
    except Exception:
        try:
            import pytesseract  # noqa: F401
            return True
        except Exception:
            return False


def extract_nutrition_data(img: np.ndarray) -> NutritionData:
    """يستخرج NutritionData من صورة جدول حقائق تغذية.

    اكتفاء ذاتي: إن غاب محرك OCR تُعاد نتيجة فارغة بثقة صفر
    (أي: أدخِل القيم يدوياً) بدل إسقاط التطبيق في البيئات الناقصة.
    """
    try:
        import pytesseract
    except Exception:
        return NutritionData()
    _configure_tesseract(pytesseract)
    binary = _prepare_for_ocr(img)
    config = "--psm 6"
    try:
        raw = pytesseract.image_to_string(binary, lang="ara+eng",
                                          config=config)
    except Exception:
        try:
            raw = pytesseract.image_to_string(binary, config=config)
        except Exception:
            # محرك Tesseract غير مثبّت على النظام — لا انهيار
            return NutritionData()

    data = NutritionData()
    matched = 0
    total_lines = 0
    for line in raw.splitlines():
        line = line.strip()
        if len(line) < 2:
            continue
        total_lines += 1
        ln = _norm(line)
        key = _match_field(ln)
        if key is None:
            continue
        amount, unit, pct = _extract_numbers(line)
        if key == "calories":
            data.calories = amount
            matched += 1
            continue
        if key == "servings":
            data.servings = amount
            matched += 1
            continue
        if key == "serving_size":
            data.serving_size = (amount + (" " + unit if unit else "")).strip()
            matched += 1
            continue
        row = NutritionRow(key=key, label_ar=FIELD_SPECS[key][0],
                           amount=amount, unit=unit, percent=pct)
        # لا تكرر نفس الحقل
        if not any(r.key == key for r in data.rows):
            data.rows.append(row)
            matched += 1
    data.confidence = round(matched / max(6, total_lines * 0.5), 2) \
        if total_lines else 0.0
    data.confidence = min(1.0, data.confidence)
    return data
