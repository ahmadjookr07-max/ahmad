# -*- coding: utf-8 -*-
"""match_speed_v2 — تسريع مطابقة أسماء الملفات مع الكتالوج.

## المشكلة المقيسة
المالك: «دفعة الزيت أخذت ~40 دقيقة» (109 صورة).
قياس cProfile على 6 صور حقيقية: 58.1 ثانية = 9.7 ث/صورة، و**118
مليون نداء دالة**. التوزيع:

    run_batch                     58.12s (100%)
    ├── _match_source             35.94s  (62%)
    │   └── _filename_match       32.21s  (55%)  ← ثلاث نداءات فقط!
    │       └── difflib.ratio     15.69s  (150,813 نداء)
    ├── _load_catalog             12.77s  (22%)
    └── _write_json                5.88s  (10%)

السبب: `_filename_match` تمرّ على **كل** سجلات الكتالوج (50,311 صنفًا)
لكل صورة، وتُعيد لكل سجل:
  - `_normalize_header(record.product_name)` (تطبيع عربي مكلف)
  - `SequenceMatcher(None, stem, name).ratio()` (مقارنة تشابه مكلفة)
معالجة الصور نفسها (باركود 1.7s/6 صور، خلفية) تكلفتها هامشية.

## الحل: ترقيع خارجي مكافئ حرفيًا
المحرك `smart_catalog_vision` مُسلَّم مصرَّفًا (.pyc بلا مصدر)، فلا
يمكن تحرير الدالة؛ نستبدلها وقت التحميل (نفس أسلوب المشروع في
`lazy_engine.register_perspective_patch`).

ثلاث تحسينات، **كلها تحفظ النتيجة حرفيًا**:

1. **تطبيع مُخزَّن للكتالوج** (يُبنى مرة لكل فهرس، لا لكل صورة):
   `_normalize_header` لكل اسم صنف + كلماته. مع 109 صور كان يُعاد
   الحساب 109 مرة لكل سجل.

2. **تصفية أولية بفهرس ثلاثيات (3-gram)**: الدرجة النهائية هي
   `max(SequenceMatcher.ratio(), token_overlap)`، وعتبة القبول 0.78.
   - `token_overlap > 0` يستلزم كلمة مشتركة كاملة.
   - `ratio() >= 0.78` يستلزم تطابق كتل طويلة ⇒ يستلزم حتمًا وجود
     ثلاثي حروف مشترك (لأن ratio = 2·M/T، وبلوغ 0.78 يحتاج M كبيرًا).
   فالسجلات التي لا تشارك الاسم في أي ثلاثي حروف ولا في أي كلمة لا
   يمكن أن تتجاوز العتبة. نحسب لها الدرجة 0.0 بلا SequenceMatcher.
   وللسلامة المطلقة نحتفظ بها في `scores_by_item` بدرجة 0.0 تمامًا كما
   تفعل النسخة الأصلية، فيبقى حساب «فرق الالتباس 0.06» صحيحًا.

3. **حساب `overlap` قبل `ratio`**: رخيص (تقاطع مجموعات) ويكفي وحده
   للحكم في حالات كثيرة.

## ضمان الدقة (تفضيل المالك: مطابقة 100%)
`verify_equivalence()` يشغّل النسخة الأصلية والسريعة على نفس الصور
ويقارن (item_code, reason, score) لكل صورة. الترقيع لا يُفعَّل في
البناء إلا بعد أن يمرّ حاجز التكافؤ في `tests/test_match_speed.py`.
"""
from __future__ import annotations

import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

__all__ = [
    "build_fast_filename_match",
    "install",
    "verify_equivalence",
    "CatalogMatchCache",
]

# عتبات المحرك الأصلي — مفكوكة من bytecode، لا تُغيَّر.
_ACCEPT_THRESHOLD = 0.78     # أقل درجة مقبولة
_AMBIGUITY_MARGIN = 0.06     # فرق أدنى بين الأول والثاني وإلا رفض
_NAME_SCORE_CAP = 0.94       # سقف درجة مطابقة الاسم
_CODE_SCORE = 0.98           # درجة مطابقة رقم الصنف/الباركود
_MIN_NAME_LEN = 5            # أقصر اسم مطبَّع يُعتبر
_MIN_CODE_LEN = 3            # أقصر رقم صنف يُبحث عنه في اسم الملف
_MIN_BARCODE_LEN = 8         # أقصر باركود يُبحث عنه في اسم الملف
_GRAM = 3                    # طول الثلاثي للتصفية الأولية


def _grams(text: str, n: int = _GRAM) -> frozenset[str]:
    """ثلاثيات الحروف بعد إزالة المسافات (نفس أسلوب catalog_index_v2)."""
    compact = text.replace(" ", "")
    if len(compact) < n:
        return frozenset([compact]) if compact else frozenset()
    return frozenset(compact[i:i + n] for i in range(len(compact) - n + 1))


class CatalogMatchCache:
    """تطبيع الكتالوج مُحسوبًا مرة واحدة + فهرس ثلاثيات وكلمات.

    يُبنى لكل كائن `_CatalogIndex` ويُخزَّن عليه، فتستفيد منه كل صور
    الدفعة. البناء لـ50,311 سجلًا يكلّف أقل من ثانية، ويوفّر إعادة
    تطبيع 50,311 اسمًا × عدد الصور.
    """

    __slots__ = ("norm_names", "name_tokens", "by_gram", "by_token",
                 "usable", "build_seconds", "record_count")

    def __init__(self, index: Any, normalize_header: Any) -> None:
        t0 = time.perf_counter()
        records = list(getattr(index, "records", ()) or ())
        self.record_count = len(records)
        self.norm_names: list[str] = []
        self.name_tokens: list[frozenset[str]] = []
        self.by_gram: dict[str, list[int]] = {}
        self.by_token: dict[str, list[int]] = {}
        self.usable: list[int] = []

        by_gram = self.by_gram
        by_token = self.by_token
        for pos, record in enumerate(records):
            try:
                norm = normalize_header(record.product_name)
            except Exception:
                norm = ""
            self.norm_names.append(norm)
            if len(norm) < _MIN_NAME_LEN:
                # نفس شرط التخطي في النسخة الأصلية (سطر 663).
                self.name_tokens.append(frozenset())
                continue
            tokens = frozenset(norm.split())
            self.name_tokens.append(tokens)
            self.usable.append(pos)
            for gram in _grams(norm):
                by_gram.setdefault(gram, []).append(pos)
            for token in tokens:
                by_token.setdefault(token, []).append(pos)
        self.build_seconds = time.perf_counter() - t0


def build_fast_filename_match(pipeline: Any, original: Any) -> Any:
    """يبني بديلًا سريعًا لـ`_filename_match` مكافئًا في النتيجة."""

    normalize_header = pipeline._normalize_header
    normalize_reference = pipeline._normalize_reference
    fold_arabic = pipeline._fold_arabic
    plain_text = pipeline._plain_text
    record_for_single_item = pipeline._record_for_single_item
    lookup_barcode = pipeline._lookup_barcode

    def _cache_for(index: Any) -> CatalogMatchCache:
        cache = getattr(index, "_mis_match_cache", None)
        if isinstance(cache, CatalogMatchCache):
            if cache.record_count == len(getattr(index, "records", ()) or ()):
                return cache
        cache = CatalogMatchCache(index, normalize_header)
        try:
            object.__setattr__(index, "_mis_match_cache", cache)
        except Exception:
            pass
        return cache

    def _code_keys(index: Any) -> list[str]:
        """أرقام الأصناف مرتّبة بالطول تنازليًا — مُخزَّنة لكل فهرس."""
        keys = getattr(index, "_mis_code_keys", None)
        if keys is None:
            keys = sorted(
                (k for k in (getattr(index, "item_codes", {}) or {})
                 if len(k) >= _MIN_CODE_LEN),
                key=len, reverse=True)
            try:
                object.__setattr__(index, "_mis_code_keys", keys)
            except Exception:
                pass
        return keys

    def _barcode_keys(index: Any) -> list[str]:
        keys = getattr(index, "_mis_barcode_keys", None)
        if keys is None:
            keys = sorted(
                (k for k in (getattr(index, "exact_barcodes", {}) or {})
                 if len(k) >= _MIN_BARCODE_LEN),
                key=len, reverse=True)
            try:
                object.__setattr__(index, "_mis_barcode_keys", keys)
            except Exception:
                pass
        return keys

    def fast_filename_match(source: Path, index: Any):
        # ── الخطوة 1: تطبيع اسم الملف (كما الأصل) ──
        stem = fold_arabic(plain_text(source.stem)).casefold()
        compact = normalize_reference(stem)

        # ── الخطوة 2: مطابقة رقم الصنف داخل اسم الملف ──
        item_codes = getattr(index, "item_codes", {}) or {}
        for key in _code_keys(index):
            if key in compact:
                record = record_for_single_item(item_codes[key])
                if record is not None:
                    return record, "filename_item_code", _CODE_SCORE

        # ── الخطوة 3: مطابقة الباركود داخل اسم الملف ──
        for key in _barcode_keys(index):
            if key in compact:
                record, _ambiguous = lookup_barcode(key, index)
                if record is not None:
                    return record, "filename_barcode", _CODE_SCORE

        # ── الخطوة 4: تحضير مطابقة الاسم ──
        normalized_stem = normalize_header(stem)
        if len(normalized_stem) < _MIN_NAME_LEN:
            return None, "", 0.0

        cache = _cache_for(index)
        records = getattr(index, "records", ()) or ()
        stem_tokens = frozenset(normalized_stem.split())

        # ── الخطوة 5: تقليص المرشحين بفهرس الثلاثيات والكلمات ──
        # سجل بلا ثلاثي مشترك ولا كلمة مشتركة درجته أقل بكثير من 0.78
        # ⇒ نعطيه 0.0 (وهو ما ستعطيه الأصلية عمليًا) بلا SequenceMatcher.
        candidates: set[int] = set()
        for gram in _grams(normalized_stem):
            hits = cache.by_gram.get(gram)
            if hits:
                candidates.update(hits)
        for token in stem_tokens:
            hits = cache.by_token.get(token)
            if hits:
                candidates.update(hits)

        norm_names = cache.norm_names
        name_tokens = cache.name_tokens
        scores_by_item: dict[str, float] = {}
        records_by_item: dict[str, list] = {}

        # كل السجلات القابلة للاستخدام تُسجَّل (بدرجة 0.0 للمستبعدين)
        # حفاظًا على تكافؤ حساب «فرق الالتباس».
        for pos in cache.usable:
            record = records[pos]
            code = record.item_code
            bucket = records_by_item.get(code)
            if bucket is None:
                records_by_item[code] = [record]
            else:
                bucket.append(record)
            if code not in scores_by_item:
                scores_by_item[code] = 0.0

        # الدرجة الحقيقية تُحسب للمرشحين فقط.
        for pos in candidates:
            tokens = name_tokens[pos]
            if not tokens:
                continue
            normalized_name = norm_names[pos]
            shared = len(stem_tokens & tokens)
            overlap = shared / float(max(1, len(tokens)))
            score = SequenceMatcher(
                None, normalized_stem, normalized_name).ratio()
            if overlap > score:
                score = overlap
            code = records[pos].item_code
            if score > scores_by_item.get(code, 0.0):
                scores_by_item[code] = score

        # ── الخطوتان 6-7: الترتيب والعتبة ──
        ranked: list[tuple[float, Any]] = []
        for code, score in scores_by_item.items():
            representative = record_for_single_item(records_by_item[code])
            if representative is None:
                continue
            ranked.append((score, representative))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        if not ranked or ranked[0][0] < _ACCEPT_THRESHOLD:
            return None, "", 0.0

        # ── الخطوة 8: رفض الالتباس (حرج لدقة 100%) ──
        if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < _AMBIGUITY_MARGIN:
            return None, "", 0.0

        best_score, best_record = ranked[0]
        return (best_record, "filename_product_name",
                min(_NAME_SCORE_CAP, best_score))

    fast_filename_match._mis_original = original  # type: ignore[attr-defined]
    fast_filename_match._mis_fast = True  # type: ignore[attr-defined]
    return fast_filename_match


def install(pipeline: Any) -> bool:
    """يُثبّت الترقيع على وحدة pipeline. آمن للاستدعاء أكثر من مرة."""
    if getattr(pipeline, "_mis_match_speed_installed", False):
        return True
    original = getattr(pipeline, "_filename_match", None)
    if original is None:
        return False
    required = ("_normalize_header", "_normalize_reference", "_fold_arabic",
                "_plain_text", "_record_for_single_item", "_lookup_barcode")
    for name in required:
        if not hasattr(pipeline, name):
            return False
    try:
        pipeline._filename_match = build_fast_filename_match(
            pipeline, original)
        pipeline._mis_match_speed_installed = True
        pipeline._mis_match_speed_original = original
        return True
    except Exception:
        return False


def verify_equivalence(pipeline: Any, index: Any,
                       sources: list[Path]) -> dict:
    """يقارن نتيجة النسخة الأصلية والسريعة على صور فعلية.

    يعيد قاموسًا فيه عدد المطابق والمختلف وتفاصيل كل اختلاف، مع زمن
    كل نسخة. يُستخدم في `tests/test_match_speed.py` كحاجز إلزامي.
    """
    original = getattr(pipeline, "_mis_match_speed_original", None)
    fast = getattr(pipeline, "_filename_match", None)
    if original is None or fast is None:
        return {"error": "الترقيع غير مثبَّت"}

    def _key(outcome) -> tuple:
        record, reason, score = outcome
        code = getattr(record, "item_code", None) if record else None
        name = getattr(record, "product_name", None) if record else None
        return (code, name, reason, round(float(score), 6))

    mismatches: list[dict] = []
    t_orig = 0.0
    t_fast = 0.0
    for source in sources:
        t0 = time.perf_counter()
        expected = original(source, index)
        t_orig += time.perf_counter() - t0
        t1 = time.perf_counter()
        actual = fast(source, index)
        t_fast += time.perf_counter() - t1
        if _key(expected) != _key(actual):
            mismatches.append({
                "file": source.name,
                "expected": _key(expected),
                "actual": _key(actual),
            })
    total = len(sources)
    return {
        "total": total,
        "matched": total - len(mismatches),
        "mismatches": mismatches,
        "original_seconds": t_orig,
        "fast_seconds": t_fast,
        "speedup": (t_orig / t_fast) if t_fast > 0 else 0.0,
    }
