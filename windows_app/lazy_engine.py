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
    """يُنشئ غلافًا لدالة في ``pipeline`` يُحمِّل عند أول استدعاء."""

    def _call(*args: Any, **kwargs: Any) -> Any:
        return getattr(load_engine(), name)(*args, **kwargs)

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
