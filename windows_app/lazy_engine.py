# -*- coding: utf-8 -*-
"""lazy_engine — تأجيل استيراد محرّك الرؤية الثقيل إلى ما بعد ظهور النافذة.

المشكلة التي تعالجها الوحدة
---------------------------
كان ``native_app`` يستورد ``smart_catalog_vision.pipeline`` على مستوى
الوحدة. ذلك الاستيراد يجرّ خلفه ``cv2`` و``numpy`` و``openpyxl``
و``final_images`` قبل أن تُرسم أول بكسل على الشاشة، فيقف المالك أمام
شاشة فارغة طوال زمن التحميل.

لماذا لم يُصلَح داخل المحرّك
---------------------------
``smart_catalog_vision`` يُسلَّم مُصرَّفًا (``.pyc`` بلا مصدر ``.py``)،
فلا سبيل لتأجيل استيراداته من الداخل. الحل الوحيد المتاح هو ألّا
يُستورد أصلًا وقت الإقلاع، وهذا ما تفعله هذه الوحدة.

كيف تعمل
--------
تُقدَّم ثلاثة أنواع من الوكلاء، وكلها تُحمِّل المحرّك عند أول لمسة
حقيقية فقط:

- ``_LazyModule`` وكيل للوحدة ``pipeline`` نفسها؛ أي ``pipeline.X``
  يُحمِّل المحرّك ثم يمرّر الطلب.
- ``_lazy_callable`` غلاف لدالة؛ الاستدعاء يُحمِّل ثم ينفّذ.
- ``_LazyClassProxy`` وكيل لصنف يُستعمل في ``isinstance`` وفي التلميحات
  النوعية؛ يدعم ``__instancecheck__`` بلا تحميل مسبق للمقارنة الرخيصة.

كما تُوفَّر ``warm_up_async()`` التي تُسخِّن المحرّك في خيط خلفي بعد
ظهور النافذة، فلا يدفع المستخدم كلفة التحميل عند أول دفعة أيضًا.

ضمانات
------
- تحميل واحد فقط مهما تعدّدت نقاط اللمس (قفل + علم).
- آمن عبر الخيوط: خيط الواجهة وخيط التسخين قد يتسابقان بلا ضرر.
- الأخطاء تُرفَع كما هي عند أول استعمال حقيقي، لا تُبتلع، فلا يتحوّل
  عطب استيراد إلى سلوك صامت غامض.
"""
from __future__ import annotations

import sys
import threading
from typing import Any, Callable

__all__ = [
    "pipeline",
    "engine_ready",
    "load_engine",
    "warm_up_async",
    "SUPPORTED_IMAGE_EXTENSIONS",
    "BatchItemResult",
    "BatchRunResult",
    "IndividualImagePreview",
    "FinalImageOptions",
    "apply_individual_image_edit",
    "apply_manual_link",
    "apply_manual_links",
    "preview_individual_image_edit",
    "run_batch",
]

_lock = threading.RLock()
_real_pipeline: Any = None
_real_final_images: Any = None
_warm_thread: threading.Thread | None = None


def engine_ready() -> bool:
    """هل حُمِّل المحرّك فعلًا؟ (فحص رخيص بلا أي أثر جانبي)."""
    return _real_pipeline is not None


def load_engine() -> Any:
    """يُحمِّل المحرّك مرة واحدة ويُعيد وحدة ``pipeline`` الحقيقية.

    يُستدعى ضمنيًا من كل وكيل. آمن للاستدعاء من أي خيط ومن أي عدد
    من النقاط في وقت واحد.
    """
    global _real_pipeline, _real_final_images
    if _real_pipeline is not None:
        return _real_pipeline
    with _lock:
        if _real_pipeline is not None:
            return _real_pipeline
        from smart_catalog_vision import pipeline as _pipeline
        from smart_catalog_vision import final_images as _final

        _apply_perspective_patch(_pipeline)
        _apply_lossless_quality_patch(_final)
        # الباركود الخطي وحده هو دليل الربط: لا OCR أو مطابقة اسم ملف
        # للصور التي لا باركود فيها، فتظهر فورًا للمراجعة/ربط الوجه والخلف.
        try:
            from linear_barcode_fast_path import install_linear_barcode_fast_path
            install_linear_barcode_fast_path(_pipeline)
        except Exception as exc:                      # noqa: BLE001
            print(f"[barcode-fast] تعذر تركيب المسار السريع: {exc}",
                  file=sys.stderr)
        # 2.9.12 — ترقيعات السلامة: تمنع اختفاء الصور عند
        # الربط وفشل الحفظ بعد الطمس. تُطبّق هنا لأن
        # ``smart_catalog_vision`` مُسلَّم مُصرَّفًا فلا يُعدّل من الداخل،
        # وهذا نفس نمط الترقيعين أعلاه. الفشل لا يُسقط
        # التطبيق — يُسجّل ويُترك السلوك الأصلي.
        try:
            from integrity_patch import apply_integrity_patches
            apply_integrity_patches(_pipeline, _final)
        except Exception as exc:                      # noqa: BLE001
            print(f"[integrity] تعذر تطبيق ترقيعات السلامة: {exc}",
                  file=sys.stderr)
        # لا تُركّب رقعة تقريب 106% القديمة: V2 يطبق قناع محرر الصور
        # وتأطير 800×700 في الحفظ الوحيد، وأي تأطير ثانٍ يبطئ ويشوّه النتيجة.
        _real_final_images = _final
        _real_pipeline = _pipeline
        return _real_pipeline


# ---------------------------------------------------------------------------
# ترقيع القص المنظوري
# ---------------------------------------------------------------------------
# كان ``native_app`` يرقّع ``pipeline._prepare_individual_source`` وقت
# الاستيراد. بما أن الاستيراد صار مؤجَّلًا، يجب أن يُطبَّق الترقيع لحظة
# التحميل الفعلي وإلا ضاع القص المنظوري بصمت.
_patch_provider: Callable[[Any], Any] | None = None


def register_perspective_patch(factory: Callable[[Any], Any]) -> None:
    """يسجّل مصنع الترقيع الذي يُطبَّق فور تحميل المحرّك.

    ``factory`` يستقبل الدالة الأصلية ويُعيد البديل. تسجيله لا يُحمِّل
    المحرّك؛ وإن كان المحرّك محمّلًا مسبقًا يُطبَّق الترقيع فورًا.
    """
    global _patch_provider
    _patch_provider = factory
    if _real_pipeline is not None:
        _apply_perspective_patch(_real_pipeline)


def _apply_perspective_patch(module: Any) -> None:
    if _patch_provider is None:
        return
    if getattr(module, "_mis_perspective_patched", False):
        return
    original = module._prepare_individual_source
    module._prepare_individual_source = _patch_provider(original)
    module._mis_perspective_patched = True


# ---------------------------------------------------------------------------
# ترقيع جودة WebP بلا فقدان (101)
# ---------------------------------------------------------------------------
# العلة التي يعالجها هذا الترقيع — علة حاجبة مقاسة، لا احتمالية:
#
#   الواجهة تعرض خيار «فائقة — بلا فقدان (lossless)» بقيمة 101، لكن
#   ``FinalImageOptions.validated`` في المحرّك يشترط
#   ``1 <= webp_quality <= 100`` فيرفع ``ValueError`` ويقتل الدفعة
#   بأكملها قبل معالجة صورة واحدة. النتيجة عند المالك: صفر مخرجات.
#
#   أثر مأخوذ من سجل مهمة حقيقية:
#     File "smart_catalog_vision/final_images.py", line 54, in validated
#     ValueError: جودة WebP يجب أن تكون بين 1 و100
#
# لماذا 101 هي القيمة الصحيحة لا الخاطئة (قياس فعلي، صورة 800×700):
#     q=94  →   524,444 بايت — ضغط مفقود
#     q=100 →   623,552 بايت — ما زال مفقودًا
#     q=101 → 1,679,222 بايت — مطابق بايت ببايت (lossless حقيقي)
#
# أي أن 100 لا تُحقّق «بلا فقدان» مطلقًا؛ 101 في OpenCV هي علم
# lossless الحقيقي. ومسار الحفظ ``FinalImageProcessor._write_webp``
# يمرّر القيمة إلى ``cv2.IMWRITE_WEBP_QUALITY`` مباشرة، فلا مانع تقني
# من 101 في أي موضع. الخلل محصور في طبقة التحقق وحدها.
#
# لماذا الترقيع وليس تعديل المصدر: ``smart_catalog_vision`` يُسلَّم
# مُصرَّفًا (``.pyc`` بلا ``.py``)، فالتعديل عند الحدّ الفاصل هو المسار
# الوحيد المتاح — وهو نفس النمط المتبع أصلًا في ترقيع القص المنظوري.
#
# نطاق الترقيع مضبوط بإحكام: 101 فقط تُستثنى، وكل ما دون 1 أو فوق 101
# يبقى مرفوضًا كما كان، فلا يضيع أي تحقق مشروع.
LOSSLESS_WEBP_QUALITY = 101


def _apply_lossless_quality_patch(module: Any) -> None:
    """يجعل ``FinalImageOptions.validated`` يقبل الجودة 101 (lossless).

    يُطبَّق مرة واحدة فقط، ويفشل بصمت آمن إن تغيّرت بنية المحرّك في
    إصدار لاحق (مثلًا صار يقبل 101 أصلًا) فلا يتحوّل الترقيع نفسه إلى
    مصدر عطب جديد.
    """
    if getattr(module, "_mis_lossless_patched", False):
        return
    options_class = getattr(module, "FinalImageOptions", None)
    if options_class is None:
        return
    original = getattr(options_class, "validated", None)
    if original is None:
        return

    def validated(self: Any) -> Any:
        quality = getattr(self, "webp_quality", None)
        if quality != LOSSLESS_WEBP_QUALITY:
            return original(self)
        # نُمرّر بقيمة مقبولة للتحقق ثم نُعيد 101 إلى الكائن الناتج،
        # فيصل علم lossless سليمًا إلى مسار الحفظ.
        probe = _replace_quality(self, 100)
        checked = original(probe)
        target = checked if checked is not None else self
        return _replace_quality(target, LOSSLESS_WEBP_QUALITY)

    validated.__name__ = "validated"
    validated.__qualname__ = f"{options_class.__name__}.validated"
    validated.__doc__ = (original.__doc__ or "") + \
        "\n\nمُرقَّع: يقبل الجودة 101 (WebP بلا فقدان)."
    options_class.validated = validated
    module._mis_lossless_patched = True


def _replace_quality(options: Any, quality: int) -> Any:
    """نسخة من الخيارات بجودة مختلفة — تعمل مع dataclass أو بدونه."""
    try:
        import dataclasses

        if dataclasses.is_dataclass(options):
            return dataclasses.replace(options, webp_quality=quality)
    except Exception:
        pass
    try:
        import copy

        clone = copy.copy(options)
        object.__setattr__(clone, "webp_quality", quality)
        return clone
    except Exception:
        return options


# ---------------------------------------------------------------------------
# الوكلاء
# ---------------------------------------------------------------------------
class _LazyModule:
    """وكيل لوحدة ``pipeline``: أي وصول لسمة يُحمِّل المحرّك ثم يمرّر."""

    __slots__ = ()

    def __getattr__(self, name: str) -> Any:
        return getattr(load_engine(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(load_engine(), name, value)

    def __repr__(self) -> str:
        state = "loaded" if engine_ready() else "not-loaded"
        return f"<lazy smart_catalog_vision.pipeline ({state})>"


pipeline = _LazyModule()


def _lazy_callable(name: str) -> Callable[..., Any]:
    """يُنشئ غلافًا لدالة في ``pipeline`` يُحمِّل عند أول استدعاء.

    2.9.8: ``run_batch`` يمر أيضًا بطبقة تسمية المالك. السبب أن اسم
    ناتج الدفعة يُبنى داخل المحرّك المُصرَّف (``final_images.pyc``)
    بوحدة واحدة، فلا يرى سياسة ``join_all_units``. وهذه نقطة الاستيراد
    الوحيدة لـ``run_batch`` في الواجهة، فالترقيع هنا يغطي كل المستدعين.
    """

    def _call(*args: Any, **kwargs: Any) -> Any:
        result = getattr(load_engine(), name)(*args, **kwargs)
        if name == "run_batch":
            try:
                from batch_naming_patch import apply_join_all_units
                result = apply_join_all_units(result)
            except Exception as exc:  # لا تُسقط دفعة بسبب التسمية
                import sys as _sys
                print(f"[batch-naming] تعذر تطبيق قاعدة الوحدات: {exc}",
                      file=_sys.stderr)
        return result

    _call.__name__ = name
    _call.__qualname__ = name
    _call.__doc__ = f"غلاف كسول لـ smart_catalog_vision.pipeline.{name}"
    return _call


class _LazyClassProxy:
    """وكيل لصنف من المحرّك.

    يخدم ثلاثة استعمالات دون تحميل مبكر:

    - ``isinstance(x, Proxy)`` — إن لم يُحمَّل المحرّك بعد فلا يمكن أن
      يكون ``x`` من إنتاجه أصلًا، فتُعاد ``False`` فورًا بلا تحميل.
    - ``Proxy(...)`` — إنشاء كائن حقيقي (يُحمِّل).
    - التلميحات النوعية ``Proxy | None`` — تُقيَّم كسلسلة بفضل
      ``from __future__ import annotations``، فلا تُحمِّل شيئًا.
    """

    __slots__ = ("_name",)

    def __init__(self, name: str) -> None:
        object.__setattr__(self, "_name", name)

    def _resolve(self) -> Any:
        return getattr(load_engine(), object.__getattribute__(self, "_name"))

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._resolve()(*args, **kwargs)

    def __instancecheck__(self, instance: Any) -> bool:
        if not engine_ready():
            # لا كائن من صنف لم يُحمَّل بعد.
            return False
        return isinstance(instance, self._resolve())

    def __subclasscheck__(self, subclass: type) -> bool:
        if not engine_ready():
            return False
        return issubclass(subclass, self._resolve())

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolve(), name)

    def __or__(self, other: Any) -> Any:  # يدعم ``Proxy | None`` وقت التشغيل
        return Any

    def __ror__(self, other: Any) -> Any:
        return Any

    def __repr__(self) -> str:
        return f"<lazy class {object.__getattribute__(self, '_name')}>"


class _LazyConstant:
    """وكيل لثابت مجموعة (``SUPPORTED_IMAGE_EXTENSIONS``).

    يدعم ``in`` والتكرار والطول بتحميل المحرّك عند أول استعمال. هذه
    العمليات لا تحدث إلا عند إضافة صور، وعندها يكون المحرّك مطلوبًا
    على أي حال.
    """

    __slots__ = ("_name",)

    def __init__(self, name: str) -> None:
        self._name = name

    def _value(self) -> Any:
        return getattr(load_engine(), self._name)

    def __contains__(self, item: Any) -> bool:
        return item in self._value()

    def __iter__(self):
        return iter(self._value())

    def __len__(self) -> int:
        return len(self._value())

    def __repr__(self) -> str:
        return repr(self._value()) if engine_ready() else f"<lazy {self._name}>"


# الأصناف المستعملة في ``isinstance`` وفي التلميحات النوعية
BatchItemResult = _LazyClassProxy("BatchItemResult")
BatchRunResult = _LazyClassProxy("BatchRunResult")
IndividualImagePreview = _LazyClassProxy("IndividualImagePreview")

# الدوال الثقيلة — كلها تُستدعى من خيوط عاملة لا من خيط الواجهة
run_batch = _lazy_callable("run_batch")
apply_manual_link = _lazy_callable("apply_manual_link")
apply_manual_links = _lazy_callable("apply_manual_links")
apply_individual_image_edit = _lazy_callable("apply_individual_image_edit")
preview_individual_image_edit = _lazy_callable("preview_individual_image_edit")

SUPPORTED_IMAGE_EXTENSIONS = _LazyConstant("SUPPORTED_IMAGE_EXTENSIONS")


class _LazyFinalImageOptions:
    """وكيل ``FinalImageOptions`` من وحدة ``final_images``."""

    __slots__ = ()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        load_engine()
        return _real_final_images.FinalImageOptions(*args, **kwargs)

    def __instancecheck__(self, instance: Any) -> bool:
        if not engine_ready():
            return False
        return isinstance(instance, _real_final_images.FinalImageOptions)

    def __getattr__(self, name: str) -> Any:
        load_engine()
        return getattr(_real_final_images.FinalImageOptions, name)

    def __or__(self, other: Any) -> Any:
        return Any

    def __ror__(self, other: Any) -> Any:
        return Any

    def __repr__(self) -> str:
        return "<lazy FinalImageOptions>"


FinalImageOptions = _LazyFinalImageOptions()


# ---------------------------------------------------------------------------
# التسخين الخلفي
# ---------------------------------------------------------------------------
def warm_up_async(on_done: Callable[[bool, str], None] | None = None) -> None:
    """يُحمِّل المحرّك في خيط خلفي بعد ظهور النافذة.

    الغرض: أن يكون المحرّك جاهزًا قبل أن يضغط المستخدم «تشغيل»، فلا
    يدفع كلفة التحميل مرتين. لا يُطلق أكثر من خيط واحد، ولا يرمي
    استثناءً أبدًا؛ الفشل يُبلَّغ عبر ``on_done``.
    """
    global _warm_thread
    if engine_ready():
        if on_done is not None:
            on_done(True, "")
        return
    with _lock:
        if _warm_thread is not None and _warm_thread.is_alive():
            return

        def _run() -> None:
            ok, message = True, ""
            try:
                load_engine()
            except Exception as exc:  # pragma: no cover - بيئة ناقصة
                ok, message = False, str(exc)
            if on_done is not None:
                try:
                    on_done(ok, message)
                except Exception:
                    pass

        _warm_thread = threading.Thread(
            target=_run, name="engine-warmup", daemon=True)
        _warm_thread.start()
