# -*- coding: utf-8 -*-
"""integrity_patch — إغلاق سلسلة «اختفاء الصور» عند الربط والتحرير (2.9.12).

خلفية القياس (لا تخمين — كل رقم هنا مقروء من البايتكود أو المصدر)
------------------------------------------------------------------
أبلغ المالك عن خمسة أعراض ظنّها أعطالًا منفصلة. القياس أثبت أن أربعة
منها فروعُ **علة واحدة**: تسلسل الاسم يتصاعد أبدًا عند إعادة المعالجة،
ثم يُحذف الملف القديم، فيبقى الصف مشيرًا إلى اسم لم يعد موجودًا.

أثره الحرفي في صور المالك:
    ملف الصورة غير موجود: 10001099_حبه-4.webp
    لم يُعثر على الصورة المحددة داخل نتائج المهمة: 10001099_حبه-4.webp
وتكرار الصنف 10001099 في صفّين متتاليين بنفس رقم الصنف والباركود.

ثلاثة أنماط تسمية متضاربة (المصدر الحقيقي للفوضى)
-------------------------------------------------
| الموضع                                        | ينتج            |
|-----------------------------------------------|-----------------|
| `FinalImageProcessor._unique_output_path`      | `..._حبه_2.webp` |
| `integration_v2.build_output_stems`            | `..._حبه-2.webp` |
| `nutrition_crop.save_nutrition_image`          | `..._حبه-2(2).webp` |

النمط الرسمي المعتمد (`naming_v2.build_name_dash`) هو الثاني وحده.
النمط الثالث `(2)` **لا تفهمه** `parse_name` إطلاقًا ⇒ الصورة تُعامَل
كاسم غريب لا ينتمي للصنف ⇒ تسقط إلى آخر القائمة. وهذا بعينه شكوى
المالك: «صورة حقائق التغذية تنزل إلى الأسفل ولا تبقى قرب الصنف».

العلة الجذرية في `integration_v2.build_output_stems` (سطر 343)
--------------------------------------------------------------
    existing = _count_item_images(stems, item)
    seq = existing + 1
التسلسل = عدد الملفات + 1 **دائمًا**، بلا اعتبار لكون هذه الصورة
إعادة معالجة لصفٍّ له مخرَج سابق. فكل ربط/تحرير يرى ملفه القديم
موجودًا فيمنحه رقمًا جديدًا: -2 ثم -3 ثم -4…

للمقارنة: `naming_v2.next_sequence` في الملف نفسه يختار أول رقم
**شاغر** — منطق سليم. أي أن الصواب موجود في المشروع لكنه لم يُستعمل هنا.

فلسفة الإصلاح: منع الفقد لا استرداده
------------------------------------
عولجت الظاهرة في 2.9.9 بـ`_recover_output_path` التي تبحث عن الملف
**بعد** ضياعه، فتنجح أحيانًا وتفشل أحيانًا — وهو سبب وصف المالك
للسلوك بأنه «غير منطقي». هنا نمنع الضياع من أصله، ونُبقي تلك الدالة
شبكةَ أمان للجلسات القديمة المتضررة.

لماذا الترقيع عند حدّ التحميل
-----------------------------
`smart_catalog_vision` مُسلَّم مُصرَّفًا (`.pyc` بلا `.py`) فلا يُعدَّل
من الداخل. وهذا نفس النمط المعتمد أصلًا في `lazy_engine` (ترقيع القص
المنظوري، وترقيع جودة WebP). أما إصلاحات `engine_v2` و`windows_app`
فتتم في المصدر المفتوح مباشرة — أأمن وأدق.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import threading
from pathlib import Path
from typing import Any, Iterable

__all__ = [
    "apply_integrity_patches",
    "reserved_stem_for_reprocess",
    "normalize_key",
    "match_item_position",
    "reprocess_scope",
    "current_reprocess_target",
]

# النمط الرسمي: {item}_{unit} ثم -2، -3… (naming_v2.build_name_dash)
_DASH_SEQ_RE = re.compile(r"^(?P<base>.+?)-(?P<seq>\d+)$")
# الأنماط الشاذة التي يجب استيعابها عند القراءة: (2) و_2
_PAREN_SEQ_RE = re.compile(r"^(?P<base>.+?)\((?P<seq>\d+)\)$")
_UNDER_SEQ_RE = re.compile(r"^(?P<base>.+?)_(?P<seq>\d+)$")


def _log(message: str) -> None:
    """تسجيل تشخيصي على stderr — يظهر في سجل التشغيل ولا يزعج المالك."""
    try:
        print(f"[integrity] {message}", file=sys.stderr, flush=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# أدوات المسارات
# ---------------------------------------------------------------------------
def normalize_key(path: Path | str) -> str:
    """مفتاح مسار موحّد للمقارنة على ويندوز.

    ويندوز لا يفرّق بين ``A.WEBP`` و``a.webp`` ويقبل ``/`` و``\\`` معًا،
    فمقارنة النصوص الخام تفشل بصمت وتُعدّ الملف مفقودًا وهو موجود.
    """
    text = str(path)
    try:
        text = os.path.realpath(text)
    except Exception:
        text = os.path.abspath(text)
    return os.path.normcase(os.path.normpath(text))


def split_sequence(stem: str) -> tuple[str, int]:
    """يفصل الجذع إلى (أساس، تسلسل) مستوعبًا الأنماط الثلاثة.

    ``10001099_حبه-4`` ⇒ (``10001099_حبه``, 4)   ← الرسمي
    ``10001099_حبه(2)`` ⇒ (``10001099_حبه``, 2)  ← شاذ من nutrition_crop
    ``10001099_حبه_2`` ⇒ (``10001099_حبه``, 2)   ← شاذ من final_images

    والجذع بلا رقم يُردّ بـ``0`` لا ``1``، لأن ``0`` تعني حرفيًا
    «لا رقم ظاهر» فيُعيد ``canonical_stem`` بناءه بلا رقم.
    لو رُدّ بـ``1`` لالتبس بالصورة الثانية ``-1`` في اصطلاح 2.9.12.

    ملاحظة دقيقة: النمط ``_2`` يلتبس بوحدة تحوي رقمًا (مثل ``حبه_2``
    كوحدة حقيقية)، لذا يُطبّق أخيرًا وبشرط أن يكون الرقم قصيرًا.
    """
    for pattern in (_DASH_SEQ_RE, _PAREN_SEQ_RE):
        match = pattern.match(stem)
        if match:
            return match.group("base"), int(match.group("seq"))
    match = _UNDER_SEQ_RE.match(stem)
    if match and len(match.group("seq")) <= 2:
        return match.group("base"), int(match.group("seq"))
    return stem, 0


def canonical_stem(base: str, seq: int) -> str:
    """يبني الجذع بالنمط الرسمي وحده.

    هنا ``seq`` هو **الرقم الظاهر** المقروء من اسم الملف
    لا الرتبة الداخلية، فيُعاد بناؤه كما هو: المدخل
    ``10001099_حبه(2)`` يُردّ ``10001099_حبه-2`` — توحيد للنمط
    لا إزاحة للرقم. وإزاحة اصطلاح 2.9.12 تتم مرة واحدة
    في ``naming_v2.migrate_legacy_dash_names`` لا هنا، وإلا
    أُزيحت الأرقام مرتين فضاعت المطابقة.

    وتوحيد النمط هو المقصود: ``parse_name`` تفهم ``-n`` وحده،
    فتُرتّب الصور بجوار صنفها بدل أن تسقط إلى آخر القائمة.
    """
    return base if seq <= 0 else f"{base}-{seq}"


# ---------------------------------------------------------------------------
# سياق إعادة المعالجة — قلب الإصلاح
# ---------------------------------------------------------------------------
# يُضبط من الواجهة قبل الربط/التحرير ليعرف مولّد الأسماء أن هذه الصورة
# ليست جديدة بل إعادة معالجة لصفٍّ له مخرَج قائم يجب الكتابة فوقه.
_context = threading.local()


def current_reprocess_target() -> str | None:
    """المخرَج السابق للصف الجاري معالجته في هذا الخيط (أو ``None``)."""
    return getattr(_context, "reprocess_target", None)


class reprocess_scope:
    """مدير سياق يعلن أن ما يجري إعادةُ معالجة لمخرَج قائم.

    الاستعمال::

        with reprocess_scope(old_output_path):
            engine.apply_manual_link(...)

    داخل النطاق يعيد مولّد الأسماء **المسار نفسه** فيُكتب فوقه، فلا
    يتكاثر ``-2 -3 -4`` ولا يُهجَر ملف يتيم. آمن مع التداخل والخيوط.
    """

    def __init__(self, previous_output: Path | str | None) -> None:
        self._value = str(previous_output) if previous_output else None
        self._saved: str | None = None

    def __enter__(self) -> "reprocess_scope":
        self._saved = current_reprocess_target()
        _context.reprocess_target = self._value
        return self

    def __exit__(self, *exc: Any) -> bool:
        _context.reprocess_target = self._saved
        return False


def reserved_stem_for_reprocess(out_dir: Path | str, item: str) -> str | None:
    """يعيد الجذع المستقر الواجب استعماله عند إعادة المعالجة.

    يعيد ``None`` حين لا يكون السياق إعادة معالجة — فيُترك السلوك
    الأصلي (توليد اسم جديد) كما هو، لأن الصورة الجديدة **تستحق** رقمًا
    جديدًا. التمييز بين الحالتين هو جوهر الإصلاح.
    """
    target = current_reprocess_target()
    if not target:
        return None
    previous = Path(target)
    try:
        same_dir = normalize_key(previous.parent) == normalize_key(out_dir)
    except Exception:
        same_dir = False
    if not same_dir:
        return None
    base, seq = split_sequence(previous.stem)
    # يجب أن يخص الصنف نفسه، وإلا فهو مخرَج صف آخر ولا يجوز الكتابة فوقه.
    if item and not base.startswith(str(item)):
        return None
    return canonical_stem(base, seq)


# ---------------------------------------------------------------------------
# حماية الملفات المرجعية من الحذف
# ---------------------------------------------------------------------------
_guard_lock = threading.RLock()
# خريطة: مسار الملف بعد نقله إلى staging ⇒ موضعه الأصلي الواجب إعادته إليه
_restore_map: dict[str, str] = {}


def register_restore(staged: Path | str, home: Path | str) -> None:
    """يسجّل أن ``staged`` نسخةٌ منقولة يجب إعادتها إلى ``home`` قبل الحذف."""
    with _guard_lock:
        _restore_map[normalize_key(staged)] = str(home)


def clear_restore_map() -> None:
    with _guard_lock:
        _restore_map.clear()


def _rescue_before_delete(folder: Path) -> None:
    """يستعيد أي ملف مرجعي داخل ``folder`` قبل حذف المجلد.

    ``apply_manual_links`` ينقل المخرجات السابقة إلى مجلد staging ثم
    يحذفه بـ``shutil.rmtree``. إن كان بين المنقول ملف ما زال مرجعًا
    لصف آخر، يختفي نهائيًا — وهو ما يراه المالك «اختفاء أصناف».
    """
    if not folder.is_dir():
        return
    with _guard_lock:
        if not _restore_map:
            return
        targets = dict(_restore_map)
    for child in folder.rglob("*"):
        if not child.is_file():
            continue
        home = targets.get(normalize_key(child))
        if not home:
            continue
        destination = Path(home)
        if destination.exists():
            continue
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(child), str(destination))
            _log(f"أُنقذ ملف مرجعي من الحذف: {destination.name}")
        except Exception as exc:
            _log(f"فشل إنقاذ {child.name}: {exc}")


def _patch_rmtree_guard(pipeline: Any) -> None:
    """يحرس ``shutil.rmtree`` داخل وحدة المحرك وحدها (لا shutil العام).

    قياس مسبق أثبت أن ``shutil`` مستورد على مستوى وحدة ``pipeline``،
    فالاعتراض ممكن. لو لم يكن مرئيًا نتخطّى بأمان بدل الفشل الصامت.
    """
    if getattr(pipeline, "_mis_rmtree_guarded", False):
        return
    module_shutil = getattr(pipeline, "shutil", None)
    if module_shutil is None:
        _log("تحذير: shutil غير مرئي في pipeline — تخطّي حارس الحذف")
        return

    original_rmtree = module_shutil.rmtree

    def guarded_rmtree(path: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            _rescue_before_delete(Path(str(path)))
        except Exception as exc:
            _log(f"تعذر إنقاذ الملفات المرجعية قبل الحذف: {exc}")
        return original_rmtree(path, *args, **kwargs)

    class _ShutilProxy:
        """وكيل لا يمسّ ``shutil`` العام — يعترض ``rmtree`` فقط."""

        def __getattr__(self, name: str) -> Any:
            if name == "rmtree":
                return guarded_rmtree
            return getattr(module_shutil, name)

    pipeline.shutil = _ShutilProxy()
    pipeline._mis_rmtree_guarded = True
    _log("رُقّع حارس rmtree — لا حذف لملف مرجعي")


# ---------------------------------------------------------------------------
# مطابقة متسامحة لموضع الصورة — إصلاح فشل الحفظ بعد الطمس
# ---------------------------------------------------------------------------
def match_item_position(items: Any, source_name: str) -> int | None:
    """يجد موضع الصورة داخل ``items`` بمحاولات متدرجة الدقة.

    سبب الحاجة: ``_set_primary_image`` (★) يعيد تسمية الملف ويُحدِّث
    ``source_name`` **في الذاكرة فقط**، بينما ``_individual_item_position``
    يطابق على ``job_state.json`` المقروء من القرص. فينفصل الاسمان
    ويفشل الحفظ بعد الطمس مهما كان الملف موجودًا.

    الترتيب: تطابق تام ⇒ اسم الملف المجرد ⇒ الجذع بلا امتداد ⇒
    مسارات المخرَج ⇒ أساس التسلسل. لا يرفع استثناءً أبدًا.
    """
    try:
        pool = list(items)
    except Exception:
        return None
    wanted = str(source_name or "").strip()
    if not wanted:
        return None

    for index, item in enumerate(pool):
        if str(getattr(item, "source_name", "")) == wanted:
            return index

    wanted_name = Path(wanted).name
    for index, item in enumerate(pool):
        if Path(str(getattr(item, "source_name", ""))).name == wanted_name:
            return index

    wanted_stem = Path(wanted).stem
    for index, item in enumerate(pool):
        if Path(str(getattr(item, "source_name", ""))).stem == wanted_stem:
            return index

    for index, item in enumerate(pool):
        for attr in ("output_path", "review_path", "source_path"):
            value = str(getattr(item, attr, "") or "")
            if not value:
                continue
            if Path(value).name == wanted_name or Path(value).stem == wanted_stem:
                return index

    wanted_base, _ = split_sequence(wanted_stem)
    if wanted_base:
        for index, item in enumerate(pool):
            for attr in ("output_path", "source_name"):
                value = str(getattr(item, attr, "") or "")
                if not value:
                    continue
                base, _ = split_sequence(Path(value).stem)
                if base == wanted_base:
                    return index
    return None


def _patch_item_position(pipeline: Any) -> None:
    """يغلّف ``_individual_item_position`` بمطابقة متسامحة.

    نُبقي رفع الخطأ حين تفشل كل المحاولات فعلًا، فلا نُخفي عطبًا حقيقيًا
    خلف تسامحٍ زائد.
    """
    if getattr(pipeline, "_mis_position_patched", False):
        return
    original = getattr(pipeline, "_individual_item_position", None)
    if original is None:
        _log("تحذير: _individual_item_position غير موجود — تخطّي الترقيع")
        return

    def _individual_item_position(result: Any, source_name: Any) -> Any:
        try:
            return original(result, source_name)
        except Exception as exc:
            index = match_item_position(getattr(result, "items", []),
                                        str(source_name))
            if index is None:
                raise
            _log(f"استُرجع موضع الصورة بمطابقة متسامحة: {source_name}"
                 f" ⇒ فهرس {index} (الأصل: {exc})")
            return index

    _individual_item_position.__name__ = "_individual_item_position"
    _individual_item_position.__doc__ = (
        (getattr(original, "__doc__", "") or "")
        + "\n\nمُرقَّع (2.9.12): مطابقة متسامحة تمنع فشل الحفظ بعد ★.")
    pipeline._individual_item_position = _individual_item_position
    pipeline._mis_position_patched = True
    _log("رُقّع _individual_item_position — مطابقة متسامحة")


# ---------------------------------------------------------------------------
# توحيد مولّد الاسم في المحرك القديم
# ---------------------------------------------------------------------------
def _patch_unique_output_path(final_images: Any) -> None:
    """يجعل ``FinalImageProcessor._unique_output_path`` يحترم إعادة المعالجة.

    الموضع مقاس من البايتكود: تابعٌ داخل الصنف ``FinalImageProcessor``
    بتوقيع ``(output_dir, item_number, unit, overwrite)`` — وليس على
    مستوى الوحدة كما قد يُظن.

    الأصل يبني ``{item}_حبه`` ثم ``_2`` عند التعارض (شرطة سفلية تخالف
    النمط الرسمي). هنا: عند إعادة المعالجة يُعاد المسار المستقر،
    وفي غيرها يُترك الأصل كما هو تمامًا.
    """
    processor = getattr(final_images, "FinalImageProcessor", None)
    if processor is None:
        _log("تحذير: FinalImageProcessor غير موجود — تخطّي ترقيع الاسم")
        return
    if getattr(processor, "_mis_stable_path_patched", False):
        return
    original = getattr(processor, "_unique_output_path", None)
    if original is None:
        _log("تحذير: _unique_output_path غير موجود — تخطّي الترقيع")
        return

    def _unique_output_path(output_dir: Any, item_number: Any,
                            unit: Any = None, overwrite: Any = False) -> Any:
        try:
            stem = reserved_stem_for_reprocess(output_dir, str(item_number))
            if stem:
                target = Path(output_dir) / f"{stem}.webp"
                _log(f"مسار مستقر عند إعادة المعالجة: {target.name}")
                return target
        except Exception as exc:
            _log(f"سقوط آمن إلى السلوك الأصلي: {exc}")
        return original(output_dir, item_number, unit, overwrite)

    _unique_output_path.__name__ = "_unique_output_path"
    _unique_output_path.__doc__ = (
        (getattr(original, "__doc__", "") or "")
        + "\n\nمُرقَّع (2.9.12): يعيد المسار المستقر عند إعادة المعالجة"
          " بدل توليد لاحقة جديدة، فلا تختفي الصور ولا تتكاثر الأسماء.")
    try:
        processor._unique_output_path = staticmethod(_unique_output_path)
    except Exception:
        processor._unique_output_path = _unique_output_path
    processor._mis_stable_path_patched = True
    _log("رُقّع FinalImageProcessor._unique_output_path")


# ---------------------------------------------------------------------------
# نقطة الدخول
# ---------------------------------------------------------------------------
def apply_integrity_patches(pipeline: Any, final_images: Any) -> None:
    """يطبّق ترقيعات السلامة. آمن للاستدعاء المتكرر ولا يرفع استثناءً.

    فشل أي ترقيع يُسجَّل ويُترك السلوك الأصلي، فلا يتحوّل الإصلاح نفسه
    إلى مصدر عطب جديد.
    """
    for name, action in (
        ("حارس الحذف", lambda: _patch_rmtree_guard(pipeline)),
        ("مطابقة متسامحة", lambda: _patch_item_position(pipeline)),
        ("مسار مخرَج مستقر", lambda: _patch_unique_output_path(final_images)),
    ):
        try:
            action()
        except Exception as exc:
            _log(f"فشل ترقيع «{name}»: {exc}")
