# -*- coding: utf-8 -*-
"""integration_v2 — دمج محرك V2 مع خط المعالجة القديم (pyc).

activate() يرقّع FinalImageProcessor.process في final_images وpipeline
لتوجيه إنتاج الصور النهائية عبر ProcessorV2 مع التسمية الموحدة الجديدة،
مع fallback للأصلي عند أي خطأ. IMAGE_OVERRIDES تسمح بتخصيص خيارات كل صورة.
"""
from __future__ import annotations

import dataclasses
import os
import threading
from pathlib import Path

from typing import TYPE_CHECKING

from .naming_v2 import (next_sequence, build_name, build_name_dash,
                        build_name_join_all, UNIT_POLICY_JOIN_ALL,
                        UNIT_SUFFIX_DEFAULT, SCHEME_DASH,
                        load_saved_settings, parse_name, dedupe_units,
                        unit_key, NamingSettings,
                        plan_stems_for_policy)

if TYPE_CHECKING:  # للتحليل الساكن فقط — لا يُحمّل عند التشغيل
    from .processor_v2 import ProcessorV2, ProcessOptionsV2


def _lazy_processor_mod():
    """استيراد كسول لـ processor_v2 (cv2/numpy ثقيلة) — يسرّع الإقلاع
    لأن activate() تُستدعى قبل ظهور النافذة، والمحرك لا يُحتاج فعليًا
    إلا عند معالجة أول صورة."""
    from . import processor_v2
    return processor_v2


def __getattr__(name):  # PEP 562 — توافق خلفي لمن يستورد الأسماء من هنا
    if name in ("ProcessorV2", "ProcessOptionsV2"):
        return getattr(_lazy_processor_mod(), name)
    raise AttributeError(name)


_LOCK = threading.Lock()
_PROCESSOR = None  # ProcessorV2 | None — يُنشأ كسوليًا
_MODEL_DIR = ""
_ACTIVE = False

# per-source-path overrides: {source_path: ProcessOptionsV2 | dict}
IMAGE_OVERRIDES: dict[str, object] = {}
# per-source-path unit override: {source_path: unit}
UNIT_OVERRIDES: dict[str, str] = {}
# إعدادات حقائق تغذية افتراضية تطبق على كل صور الدفعة (تفعلها الواجهة)
DEFAULT_NUTRITION: dict = {}


def set_default_nutrition(settings: dict | None) -> None:
    """يعتمد إعدادات حقائق التغذية كوضع افتراضي لكل الصور القادمة."""
    DEFAULT_NUTRITION.clear()
    if settings:
        DEFAULT_NUTRITION.update(settings)


def _bridge(opts, explicit=None):
    """يُمرّر الخيارات عبر جسر الوعي لتسري أوامر المالك فعليًا.

    دون هذه الوصلة كانت أوامر الحوار تُحفظ وتُعرض كأنها نُفّذت
    ثم تُهمل عند المعالجة. الفشل هنا لا يوقف المعالجة: إعداد
    مفقود أهون من دفعة متوقفة.
    """
    try:
        from .awareness_bridge_v2 import apply_overrides
        return apply_overrides(opts, explicit=explicit)
    except Exception:
        return opts


def _coerce_options(obj, source_path: str = ""):
    """يحول dict قادمة من نافذة حقائق التغذية (أو أي مصدر) إلى
    ProcessOptionsV2 جاهزة للمعالج — مع تحويل bbox النسبي (x1,y1,x2,y2)
    إلى بكسلات (x,y,w,h) وبناء InsetPlacement من anchor/scale/offset.

    ويُمرّر الناتج عبر جسر الوعي، فهذه الدالة هي الممر الوحيد
    لبناء خيارات المعالجة، فمن هنا تسري أوامر المالك على كل صورة.
    """
    mod = _lazy_processor_mod()
    if obj is None:
        opts = mod.ProcessOptionsV2()
        if DEFAULT_NUTRITION:
            opts = _apply_nutrition_dict(opts, DEFAULT_NUTRITION, source_path)
            return _bridge(opts, explicit=set(DEFAULT_NUTRITION))
        return _bridge(opts)
    if isinstance(obj, mod.ProcessOptionsV2):
        # كائن جاهز من المتصل: نحترم ما ضبطه ولا نملأ إلا الفراغات
        return _bridge(obj, explicit=_non_default_fields(mod, obj))
    if isinstance(obj, dict):
        opts = mod.ProcessOptionsV2()
        opts = _apply_nutrition_dict(opts, obj, source_path)
        return _bridge(opts, explicit=set(obj))
    return obj


def _non_default_fields(mod, opts) -> set:
    """أسماء الحقول التي غيّرها المتصل عن الافتراضي.

    ما غيّره المتصل صراحةً أقوى من التجاوز المحفوظ، لأن أحدث فعل
    مباشر أصدق تعبيرًا عن النية من إعداد قديم.
    """
    out = set()
    try:
        ref = mod.ProcessOptionsV2()
        for f in getattr(ref, "__dataclass_fields__", {}):
            if getattr(opts, f, None) != getattr(ref, f, None):
                out.add(f)
    except Exception:
        return out
    return out


def _apply_nutrition_dict(opts, d: dict, source_path: str = ""):
    """يطبق مفاتيح نافذة حقائق التغذية على ProcessOptionsV2."""
    mode = str(d.get("nutrition_mode", "none") or "none")
    if mode in ("none", "not_found"):
        opts.nutrition_mode = "none"
    elif mode == "remove":
        # الإزالة تتم في طبقة لاحقة — المعالج لا يدمج شيئًا
        opts.nutrition_mode = "remove"
    else:
        opts.nutrition_mode = mode
    src = str(d.get("nutrition_source", "") or
              d.get("nutrition_source_path", "") or "")
    if src and src != str(source_path):
        opts.nutrition_source_path = src
    bbox = d.get("nutrition_bbox")
    if bbox and len(bbox) == 4:
        x1, y1, x2, y2 = (float(v) for v in bbox)
        if max(x1, y1, x2, y2) <= 1.0:
            # نسب — حولها لبكسلات عند المعالجة لاحقًا عبر مصدر الصورة
            try:
                import numpy as _np
                import cv2 as _cv2  # noqa: F401 — ضمان توفر القراءة
                ref = src or str(source_path)
                img = None
                if ref:
                    data = _np.fromfile(ref, _np.uint8)
                    img = _cv2.imdecode(data, 1)
                if img is not None:
                    H, W = img.shape[:2]
                    px = (int(x1 * W), int(y1 * H),
                          max(1, int((x2 - x1) * W)),
                          max(1, int((y2 - y1) * H)))
                    opts.nutrition_bbox = px
            except Exception:
                opts.nutrition_bbox = None
        else:
            # قيم بكسلية جاهزة بصيغة (x, y, w, h) — تمر كما هي
            opts.nutrition_bbox = (int(x1), int(y1), int(x2), int(y2))
    anchor = d.get("nutrition_anchor")
    scale = d.get("nutrition_scale")
    offset = d.get("nutrition_offset") or (0.0, 0.0)
    if anchor or scale:
        try:
            from .nutrition_v2 import InsetPlacement
            ox, oy = (float(offset[0]), float(offset[1]))
            opts.nutrition_placement = InsetPlacement(
                anchor=str(anchor or "bottom_left"),
                offset_x=int(ox * 800), offset_y=int(oy * 700),
                scale=float(scale or 0.28)).clamp()
        except Exception:
            pass
    values = d.get("nutrition_values")
    if values and hasattr(opts, "nutrition_values"):
        opts.nutrition_values = values
    return opts


def set_override(source_path: str, options) -> None:
    if isinstance(options, dict):
        options = _coerce_options(options, str(source_path))
    IMAGE_OVERRIDES[str(source_path)] = options


def set_unit_override(source_path: str, unit: str) -> None:
    UNIT_OVERRIDES[str(source_path)] = unit


def clear_overrides() -> None:
    IMAGE_OVERRIDES.clear()
    UNIT_OVERRIDES.clear()


def get_processor(model_dir: str = ""):
    global _PROCESSOR, _MODEL_DIR
    with _LOCK:
        if _PROCESSOR is None or (model_dir and model_dir != _MODEL_DIR):
            _MODEL_DIR = model_dir or _default_model_dir()
            _PROCESSOR = _lazy_processor_mod().ProcessorV2(_MODEL_DIR)
    return _PROCESSOR


def _default_model_dir() -> str:
    try:
        from .paths_v2 import models_dir
        return models_dir()
    except Exception:
        here = Path(__file__).parent
        for cand in [here / "models",
                     here.parent.parent / "resources" / "models",
                     here.parents[2] / "resources" / "models"]:
            if cand.is_dir():
                return str(cand)
        return str(here)


# مجلد بيانات التطبيق الذي تحفظ فيه سياسة التسمية (تعيّنه الواجهة عند الإقلاع)
NAMING_DATA_ROOT: str = ""


def set_naming_data_root(path: str | Path) -> None:
    global NAMING_DATA_ROOT
    NAMING_DATA_ROOT = str(path)


def _current_naming_settings():
    """سياسة التسمية الفاعلة — **لا تُرجع None أبدًا**.

    العلة الجذرية التي أخفت نفسها (نمط النجاح الزائف على مستوى المحرّك):
    كانت تُرجع ``None`` إن لم تكن الواجهة قد سجّلت ``NAMING_DATA_ROOT``
    بعد (وهذا يقع في كل المسارات التي تستدعي المحرّك مباشرة، وفي
    جهة المجلد المنجز). وكل مستعمليها يفحص ``settings is not None``
    قبل تطبيق ``join_all_units`` ⇒ فارتداد صامت إلى الوحدة الواحدة
    في **الجهتين**، فخرجت 992 صورة للمالك بوحدة ``حبه`` وحدها مع أن
    74% من أصنافه لها أكثر من وحدة في الإكسل.

    الإصلاح: إرجاع ``NamingSettings()`` الافتراضية (وافتراضها
    ``join_all_units``) فيعمل البرنامج بالقاعدة الصحيحة بلا أي ضبط
    يدوي من المالك، وفي أي بيئة ومن أي مسار استدعاء.
    """
    if NAMING_DATA_ROOT:
        try:
            saved = load_saved_settings(NAMING_DATA_ROOT)
            if saved is not None:
                return saved
        except Exception:
            pass
    try:
        return NamingSettings()
    except Exception:
        return None


# مرجع فهرس الإكسل الحي (CatalogIndex) — تسجله الواجهة عند تحميل الإكسل
# لتستطيع سياسة join_all_units جلب كل وحدات الصنف حرفيًا من الإكسل.
_CATALOG_REF: dict[str, object] = {"index": None}


def set_catalog_index(index) -> None:
    """تسجله الواجهة: فهرس الإكسل المحمّل (لوحدات join_all_units)."""
    _CATALOG_REF["index"] = index


def barcode_decision_from_catalog(item: str, preferred: str = "",
                                  unit: str = "") -> dict:
    """قرار باركود/وحدة مثبت من Excel لاستخدام كل مسارات التسمية."""
    empty = {"barcode": "", "unit": str(unit or ""),
             "status": "missing", "candidates": []}
    idx = _CATALOG_REF.get("index")
    if idx is None:
        return empty
    try:
        resolver = getattr(idx, "resolve_retail_barcode", None)
        if callable(resolver):
            decision = resolver(str(item), unit=str(unit or ""),
                                observed=str(preferred or ""))
            return dict(decision or empty)
    except Exception:
        pass
    return empty


def _barcode_from_catalog(item: str, preferred: str = "",
                          unit: str = "") -> str:
    """التوافق مع المستدعين القدامى: يعيد الباركود المثبت فقط."""
    return str(barcode_decision_from_catalog(
        item, preferred=preferred, unit=unit).get("barcode", "") or "")


def _units_from_catalog(item: str, excel_order: bool = False) -> list[str]:
    """وحدات الصنف من الإكسل — تعيد [] إن لم يتوفر الكتالوج.

    ``excel_order=False`` (الافتراضي، لسياسة الوحدة الواحدة):
    **الوحدة ذات العبوة=1 تتصدر**. سياسة الوحدة الواحدة تأخذ
    ``units[0]``، وترتيب صفوف الإكسل عشوائي، فكان صنفٌا صورته صورة
    حبة يُسمّى ``باكت`` لأن صف الباكت ورد أولًا (مقيسة على 484
    صنفًا: 99.8% تطابق).

    ``excel_order=True`` (لسياسة ``join_all_units``): الترتيب
    **حرفيًا كما وردت صفوف الإكسل** بلا أي إعادة ترتيب.

    2.9.10 — لماذا فُصل المساران: أمر المالك في سياسة الدمج
    نصٌّ: «قم بجمع كل الوحدات التابعة له من ملف الإكسل (بنفس
    ترتيبها)» ومثاله ``حبه_شدة_كرتون``. وتصدير وحدة العبوة=1
    قد يقلب هذا الترتيب (إن ورد الكرتون قبل الحبة يخرج
    ``حبه_كرتون_شدة``) فيخالف «بنفس ترتيبها».
    التصدير مُبرّر للوحدة الواحدة (اختيار أيّها تمطل الصورة)،
    ولا معنى له في الدمج لأن كل الوحدات تُكتب أصلًا.

    التكرار الإملائي (حبه/حبة) يُحذف في الحالتين مع الاحتفاط
    بأول إملاء ورد حرفيًا — ولا يُجرى أي تصحيح إملائي.
    """
    idx = _CATALOG_REF.get("index")
    if idx is not None:
        try:
            units = [str(u) for u in idx.units_for_code(str(item))
                     if str(u or "").strip()]
            if units:
                if not excel_order:
                    primary = ""
                    try:
                        primary = str(
                            idx.primary_unit_for_code(str(item)) or "")
                    except Exception:
                        primary = ""
                    if primary:
                        key = unit_key(primary)
                        units = [primary] + [u for u in units
                                             if unit_key(u) != key]
                return dedupe_units(units)
        except Exception:
            pass
    return []


def _count_item_images(stems: list[str], item: str) -> int:
    item_s = str(item)
    count = 0
    for s in stems:
        pn = parse_name(s)
        if pn and pn.item == item_s:
            count += 1
            continue
        # أسماء join_all متعددة الوحدات لا يفهمها parse_name — طابق البادئة
        if s == item_s or s.startswith(f"{item_s}_"):
            count += 1
    return count


# ---------------------------------------------------------------------------
# 2.9.12 — سياق إعادة المعالجة (إصلاح «اختفاء الصور»)
#
# العلة: كل ربط أو تحرير لصفٍّ له مخرَج قائم كان يولّد **اسمًا
# جديدًا** (-2 ثم -3 ثم -4…) ثم يُحذف القديم، فيبقى الصف مشيرًا
# إلى ملف غير موجود. الحل: أثناء إعادة المعالجة نحجز الجذع
# المستقر نفسه فيُكتب فوقه — لا تكاثر ولا ملف يتيم.
#
# السياق خاص بكل خيط (thread-local) لأن المعالجة تجري في عمّال
# متوازية، فلا يتسرّب حجز صفٍّ إلى صفٍّ آخر.
# ---------------------------------------------------------------------------
_reprocess_ctx = threading.local()


def set_reprocess_stem(item: str, stem: str | None) -> None:
    """يحجز الجذع المستقر للصنف ``item`` في الخيط الحالي.

    يُستدعى قبل إعادة معالجة صورة لها مخرَج سابق (ربط يدوي،
    تحرير فردي، تعيين واجهة) ليُكتب فوق الملف نفسه.
    و``stem=None`` يرفع الحجز.
    """
    table = getattr(_reprocess_ctx, "stems", None)
    if table is None:
        table = {}
        _reprocess_ctx.stems = table
    key = str(item).strip()
    if stem:
        table[key] = str(stem)
    else:
        table.pop(key, None)


def clear_reprocess_stems() -> None:
    """يرفع كل الحجوزات في الخيط الحالي (يُستدعى في ``finally``)."""
    _reprocess_ctx.stems = {}


class reprocess_scope:
    """مدير سياق يضمن ثبات اسم المخرَج أثناء إعادة المعالجة.

    >>> with reprocess_scope("10001099", "10001099_حبه-1"):
    ...     processor.process(...)   # يكتب فوق الملف نفسه
    """

    def __init__(self, item: str, stem: str | None):
        self._item = str(item).strip()
        self._stem = stem

    def __enter__(self):
        if self._stem:
            set_reprocess_stem(self._item, self._stem)
        return self

    def __exit__(self, *exc):
        set_reprocess_stem(self._item, None)
        return False


def _reserved_reprocess_stem(out_dir: Path, item: str) -> str | None:
    """الجذع المحجوز لهذا الصنف إن كنّا في إعادة معالجة.

    مصدران للسياق، وكلاهما لازم:

    1. السياق المحلي ``reprocess_scope`` في هذه الوحدة — يُستعمل
       من اختبارات المحرك ومن أي مستدعٍ يعرف رمز الصنف.
    2. سياق ``integrity_patch`` الذي تضبطه الواجهة بـ**مسار**
       المخرَج السابق دون أن تعرف الوحدة ولا الجذع المتوقع.
       وهي الحالة الفعلية في الإنتاج (الربط اليدوي والتحرير
       الفردي)، وترقيع ``_unique_output_path`` يقرأ منها أيضًا
       فيتّفق مولّدا الأسماء على اسم واحد.

    الاستيراد مؤجّل ومحروس لأن ``integrity_patch`` يسكن
    ``windows_app`` وليس متاحًا حين يُستعمل المحرك وحده.
    """
    item_key = str(item).strip()
    table = getattr(_reprocess_ctx, "stems", None)
    if table:
        stem = table.get(item_key)
        if stem:
            return str(Path(stem).stem)
    try:
        from integrity_patch import reserved_stem_for_reprocess
    except Exception:
        return None
    try:
        return reserved_stem_for_reprocess(out_dir, item_key)
    except Exception:
        return None


def _next_free_sequence(stems: list[str], item: str) -> int:
    """أول رقم **شاغر** للصنف — لا ``عدد + 1``.

    الفرق جوهري: ``عدد + 1`` يتجاهل الفجوات فيتصاعد أبديًا
    (تحذف صورتين من ثلاث فيصير التالي -4 والمجلد فيه صورة)،
    و``next_sequence`` يملأ الفجوات فيبقى الترقيم متصلًا نظيفًا.

    الدالة السليمة ``next_sequence`` موجودة أصلًا في ``naming_v2``
    ولم تكن مستعملة هنا — وهذا جوهر العلة.

    ونحرس الأسماء متعددة الوحدات (join_all) التي لا يفهمها
    ``parse_name``: إن وُجدت ولم يُرجِع ``next_sequence`` شيئًا أكبر،
    نسقط إلى العدّ لئلا نطمس صورة قائمة.
    """
    seq = next_sequence(stems, item)
    item_s = str(item).strip()
    # أسماء لا يفهمها parse_name لكنها تخص الصنف نفسه.
    opaque = 0
    for s in stems:
        if parse_name(s):
            continue
        if s == item_s or s.startswith(f"{item_s}_"):
            opaque += 1
    if opaque:
        seq = max(seq, _count_item_images(stems, item) + 1)
    return seq


def build_output_stems(out_dir: str | Path, item: str,
                       unit: str = UNIT_SUFFIX_DEFAULT) -> list[str]:
    """**كل** أسماء الملف التالي للصنف وفق السياسة المحفوظة.

    يعيد قائمة: اسمًا واحدًا في أغلب السياسات، و**اسمًا لكل وحدة** في
    ``replicate_all_units`` (الصنف الذي له حبه/شدة/كرتون في الإكسل يأخذ
    ثلاث نسخ). الوحدات تُقرأ من الإكسل حرفيًا وبترتيبه.

    2.9.11: قبل هذا التاريخ كانت الدالة تفرّع على ``join_all_units`` ثم
    ``SCHEME_DASH`` وتسقط كل ما بقي في وحدة واحدة قيمتها الوسيط ``unit``
    القادم من المحرك (``حبه`` دائمًا) — فسياستا ``replicate_all_units``
    و``default_unit`` لم تكن لهما وجود في مسار الإنتاج إطلاقًا. الآن
    القرار كله في ``plan_stems_for_policy``.

    2.9.12 — إصلاح «اختفاء الصور» (علة جذرية أنتجت أربعة أعراض):
    كان السطر ``seq = existing + 1`` يمنح رقمًا جديدًا في **كل** نداء،
    حتى حين تكون الصورة إعادةَ معالجة لصفٍّ له مخرَج قائم. فكل ربط أو
    تحرير لنفس الصف يرى ملفه القديم موجودًا فيتصاعد: ``-2`` ثم ``-3``
    ثم ``-4``… ثم يُحذف القديم، فيبقى الصف مشيرًا إلى اسم غير موجود:

        ملف الصورة غير موجود: 10001099_حبه-4.webp

    الآن نميّز حالتين:
    - **إعادة معالجة** (سياق ``reprocess_scope`` نشط): يُعاد الجذع
      المستقر نفسه فيُكتب فوقه — لا تكاثر ولا ملف يتيم.
    - **صورة جديدة**: تستحق رقمًا جديدًا، والسلوك كما كان.

    وبديل ``existing + 1`` صار ``next_sequence`` الذي يختار أول رقم
    **شاغر** — وهو المنطق السليم الموجود أصلًا في ``naming_v2`` والذي
    لم يكن مستعملًا هنا، فيملأ الفجوات بدل التصاعد الأبدي.
    """
    out_dir = Path(out_dir)
    stems = [p.stem for p in out_dir.glob("*.webp")] if out_dir.is_dir() else []

    # إعادة معالجة صفٍّ له مخرَج قائم ⇒ ثبِّت الاسم واكتب فوقه.
    reserved = _reserved_reprocess_stem(out_dir, item)
    if reserved:
        return [reserved]

    settings = _current_naming_settings()
    if settings is None or not settings.enabled:
        return [build_name(item, next_sequence(stems, item), unit)]
    # ترتيب Excel يُحفظ لسياسات الدمج/التكرار، أما وحدة الصورة الواحدة
    # فتؤخذ من صف العبوة=1 حتى لا يختار الباركود وحدة صف عشوائي.
    units = (_units_from_catalog(item, excel_order=True)
             or ([unit] if unit else []))
    preferred_units = _units_from_catalog(item, excel_order=False)
    chosen_unit = (preferred_units[0] if preferred_units else unit)
    barcode = _barcode_from_catalog(item, unit=chosen_unit)
    # في نمط الباركود، عدّ التسلسل على بادئة الباركود لا رقم الصنف.
    identity = barcode if getattr(settings, "reference_mode", "item_code") == "barcode" else item
    seq = _next_free_sequence(stems, identity)
    planned = plan_stems_for_policy(item, units, seq, total=seq,
                                    settings=settings, chosen_unit=chosen_unit,
                                    barcode=barcode)

    # لا اسم بديل برقم الصنف عند اختيار الباركود وغياب قيمته في Excel.
    # يُترك الاسم للمحرك ثم تظهر الحالة للمراجعة؛ لا ربط مضلل.
    return planned or [build_name(item, next_sequence(stems, item), unit)]


def build_output_stem(out_dir: str | Path, item: str,
                      unit: str = UNIT_SUFFIX_DEFAULT) -> str:
    """اسم الملف التالي للصنف (الاسم الأول) وفق السياسة المحفوظة.

    غلاف توافقي حول ``build_output_stems`` لمن يحتاج اسمًا واحدًا؛ مع
    ``replicate_all_units`` تُنشأ بقية النسخ في طبقة الدفعة
    (``batch_naming_patch``) بعد كتابة الملف.
    """
    stems = build_output_stems(out_dir, item, unit)
    return stems[0] if stems else build_name(item, 1, unit)


def _wrap_result(result_cls, ok: bool, output_path: str, error: str,
                 original_kwargs: dict):
    """يبني كائن نتيجة متوافقًا مع dataclass القديم ديناميكيًا."""
    if result_cls is None:
        return None
    try:
        fields = {f.name for f in dataclasses.fields(result_cls)}
    except TypeError:
        fields = set()
    kwargs = {}
    for name, value in [("success", ok), ("ok", ok),
                        ("output_path", output_path), ("path", output_path),
                        ("error", error), ("error_message", error)]:
        if name in fields:
            kwargs[name] = value
    for k, v in original_kwargs.items():
        if k in fields and k not in kwargs:
            kwargs[k] = v
    try:
        return result_cls(**kwargs)
    except Exception:
        return None


def activate(model_dir: str = "") -> bool:
    """يفعّل الترقيع على FinalImageProcessor في الوحدات القديمة."""
    global _ACTIVE
    if _ACTIVE:
        return True
    patched = False
    for mod_name in ("smart_catalog_vision.final_images",
                     "smart_catalog_vision.pipeline"):
        try:
            import importlib
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        cls = getattr(mod, "FinalImageProcessor", None)
        if cls is None or getattr(cls, "_v2_patched", False):
            continue
        original = cls.process

        def make_v2_process(orig):
            def _v2_process(self, source_path, output_path, *args, **kwargs):
                try:
                    src = str(source_path)
                    opts = _coerce_options(IMAGE_OVERRIDES.get(src), src)
                    requested = Path(str(output_path))
                    item = str(kwargs.get("item_number", "") or "").strip()
                    unit = str(kwargs.get("unit", UNIT_SUFFIX_DEFAULT) or
                               UNIT_SUFFIX_DEFAULT).strip()
                    # وحدة الصف في Excel هي المرجع عند وجودها؛ فالمعالج
                    # الموروث يمرر أحيانًا «حبة» الافتراضية بدل «حبه» الفعلية.
                    catalog_units = _units_from_catalog(item, excel_order=False) if item else []
                    if catalog_units:
                        unit = str(catalog_units[0]).strip() or unit
                    # صيغة الأسماء التاريخية للجلسات هي «حبه»، أما المحرك
                    # الموروث فيمرر أحيانًا «حبة»؛ نوحدها كي لا يظهر ملفان
                    # لنفس الصورة بسبب اختلاف حرف واحد.
                    if unit == "حبة":
                        unit = "حبه"
                    # المعالج الموروث يستقبل **مجلدًا** ثم يسمي الملف في
                    # داخله. تمرير المجلد إلى ProcessorV2 كأنه ملف يجعل
                    # الكتابة تفشل بصمت فيرجع إلى العزل القديم البطيء.
                    # نبني الملف النهائي هنا بالسياسة الموحدة نفسها.
                    if requested.suffix:
                        target = requested
                    elif item:
                        requested.mkdir(parents=True, exist_ok=True)
                        target = requested / f"{build_output_stem(requested, item, unit)}.webp"
                    else:
                        # لا نخمن اسمًا إذا غاب رقم الصنف؛ اترك المسار
                        # الموروث يتعامل مع الحالة حتى لا تُنسب صورة خطأ.
                        return orig(self, source_path, output_path,
                                    *args, **kwargs)
                    proc = get_processor(model_dir)
                    res = proc.process(src, str(target), opts)
                    if res.ok:
                        try:
                            return orig(self, source_path, output_path,
                                        *args, **kwargs) \
                                if os.environ.get("V2_CHAIN_OLD") else \
                                _mk_result(orig, self, res, source_path,
                                           target, kwargs, opts)
                        except Exception:
                            return _mk_result(orig, self, res, source_path,
                                              target, kwargs, opts)
                    # فشل V2 → الأصلي
                    return orig(self, source_path, output_path,
                                *args, **kwargs)
                except Exception:
                    return orig(self, source_path, output_path,
                                *args, **kwargs)
            return _v2_process

        def _mk_result(orig, self_obj, res, source_path, target, original_kwargs, opts):
            """يحوّل نتيجة V2 إلى ``FinalImageResult`` كاملة.

            لا يكفي ``output_path`` وحده: خط الدفعة يقرأ حقول طريقة العزل
            والمقاس والنسب قبل إنشاء صفه. رجوع كائن V2 الخام جعله ينهار
            ثم يعيد تشغيل المعالج القديم. نبني النتيجة الموروثة بلا أي
            معالجة بكسلات إضافية.
            """
            from types import SimpleNamespace
            import hashlib
            import cv2

            def _sha256(path):
                digest = hashlib.sha256()
                try:
                    with open(path, "rb") as handle:
                        for block in iter(lambda: handle.read(1024 * 1024), b""):
                            digest.update(block)
                    return digest.hexdigest()
                except Exception:
                    return ""

            src_path, out_path = Path(str(source_path)), Path(str(target))
            source = cv2.imread(str(src_path), cv2.IMREAD_COLOR)
            output = cv2.imread(str(out_path), cv2.IMREAD_COLOR)
            sh, sw = source.shape[:2] if source is not None else (0, 0)
            oh, ow = output.shape[:2] if output is not None else (0, 0)
            item = str(original_kwargs.get("item_number", "") or "")
            unit = str(original_kwargs.get("unit", UNIT_SUFFIX_DEFAULT) or
                       UNIT_SUFFIX_DEFAULT)
            product = str(original_kwargs.get("product_name", "") or "")
            values = {
                "source_path": str(src_path),
                "output_path": str(out_path),
                "item_number": item,
                "unit": unit,
                "product_name": product,
                "source_sha256": _sha256(src_path),
                "output_sha256": _sha256(out_path),
                "source_width": int(sw), "source_height": int(sh),
                "output_width": int(ow), "output_height": int(oh),
                "foreground_method": "editor_v2",
                "foreground_ratio": float(getattr(res, "confidence", 0.0) or 0.0),
                "crop_bbox": (0, 0, int(ow), int(oh)),
                "background_removed": True,
                "display_enhanced": bool(getattr(opts, "enhance", True)),
                "presentation_rotation_degrees": 0.0,
                "warnings": list(getattr(res, "warnings", []) or []),
                "foreground_quality_score": float(getattr(res, "confidence", 0.0) or 0.0),
                "foreground_quality_status": "editor_v2",
                "foreground_quality_metrics": {},
            }
            try:
                from smart_catalog_vision.final_images import FinalImageResult
                return FinalImageResult(**values)
            except Exception:
                return SimpleNamespace(**values)

        cls.process = make_v2_process(original)
        cls._v2_patched = True
        patched = True
    _ACTIVE = patched
    return patched
