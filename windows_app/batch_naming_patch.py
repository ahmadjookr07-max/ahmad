# -*- coding: utf-8 -*-
"""2.9.8 — تطبيق سياسة تسمية المالك على **مسار الدفعة**.

## المشكلة التي تحلها هذه الوحدة

قرار المالك (2.9.6): اسم الصورة يحمل **كل وحدات الصنف من الإكسل**:
``10000014_حبه_باكت`` لا ``10000014_حبه``. وقد نُفِّذ هذا في
``engine_v2`` (``build_name_join_all`` + ``build_output_stem``) فعمل في:

- الربط اليدوي  ✅ (``10008272_باكت_حبه_كرتون_كرتون1``)
- المجلد المنجز ✅ (``legacy_folder_v2``)

لكنه **لم يعمل في مسار الدفعة**. السبب — بعد تشخيص بالبايتكود:

اسم ناتج الدفعة يُبنى داخل المحرّك المُسلَّم **مُصرَّفًا بلا مصدر**::

    smart_catalog_vision/pipeline.pyc      → run_batch → _item_from_match
    smart_catalog_vision/final_images.pyc  → FinalImageProcessor.process
                                             (safe_filename_component,
                                              normalize_unit, افتراضي 'حبة')

فالمحرّك يسمّي بـ``record.unit`` — **وحدة واحدة** — ولا يعرف سياسة
``join_all_units`` إطلاقًا. و``integration_v2.build_output_stem`` (التي
تطبّق السياسة) لا يستدعيها مسار الدفعة، بل صور حقائق التغذية فقط.

ولأن المحرّك بلا مصدر فلا يمكن إصلاحه في مكانه. والحل الصحيح ليس نسخ
منطق التسمية هنا (فيتباعد عن ``engine_v2`` حتمًا)، بل **إعادة تسمية
النواتج بعد الدفعة** باستدعاء نفس دوال ``engine_v2`` — فتبقى قاعدة
واحدة في مكان واحد تخدم المسارات الثلاثة.

## لماذا بعد الدفعة لا قبلها؟

لأن ``run_batch`` لا يقبل دالة تسمية من الخارج (فحصنا توقيعه). والبديل
الوحيد قبل الدفعة هو ترقيع ``FinalImageProcessor`` وهو صنف مُصرَّف
داخلي يتغير مع أي تحديث للمحرّك — ترقيعه هشّ. أما إعادة التسمية بعد
اكتمال الدفعة فتعتمد على شيء واحد ثابت: ``output_path`` في النتيجة.

## ما تضمنه

- الاسم الرئيسي بكل الوحدات بلا رقم، والإضافية ``-1`` ثم ``-2``...
- عدم طمس ملف موجود (يُبحث عن أول تسلسل حر).
- تحديث ``output_path`` في كل ``BatchItemResult`` **وفي تقارير**
  ``state.json`` إن وُجدت، وإلا صارت التقارير تشير لملفات غير موجودة.
- إن أخفق أي جزء، يُترك الاسم الأصلي ولا تسقط الدفعة أبدًا.

## علة الوحدة الواحدة (2.9.9 — اكتُشفت بتشخيص `match_source`)

كان الشرط ``if len(units) < 2: continue`` يتخطّى كل صنف له **وحدة
واحدة** بحجة أن «اسم المحرّك صحيح أصلًا». والافتراض خاطئ: المحرّك
يسمّي بـ``record.unit``، وعندما تصل فارغة (``unit=None``) يسقط إلى
الافتراضية ``حبة``. فصنفٌ وحدته الوحيدة ``كرتون`` كان يُسمّى
``10031002_حبه`` — وحدة لا يملكها الصنف إطلاقًا.

والتشخيص أثبت أن هذا يحدث مع ``match_source='catalog_barcode'`` و
``confidence=1.0``، أي أن رقم الصنف **مؤكد** والوحدة الصحيحة متاحة
في الإكسل، ومع ذلك يُكتب اسم خاطئ يكسر الربط بالمتجر. وهي أغلبية
أصناف المالك (كرتون/كيس/درزن/علبة…) لا حالة نادرة.

الإصلاح: لا نتخطّى إلا إذا **لم يوجد كتالوج** للصنف؛ ومع وجوده
يُقارَن الاسم بـ``want_stem`` المبني من وحدات الإكسل، فيُصحَّح إن
خالفها ويُترك إن طابقها (الشرط التالي يكفل ذلك بلا إعادة تسمية
عابثة).

## الكائنات مُجمّدة (علة اكتُشفت بالتشخيص)

``BatchItemResult`` و``BatchRunResult`` كلاهما
``@dataclass(frozen=True)``، فـ``setattr(it, "output_path", ...)`` يرفع
``FrozenInstanceError``. وكان محميَّا بـ``except`` صامت — فأُعيدت
تسمية الملفات على القرص بينما بقيت النتائج تشير للأسماء القديمة
⇒ **صور مفقودة في الواجهة ومعاينة تخفق**. وهو أسوأ من عدم
إعادة التسمية أصلًا.

الحل: ``dataclasses.replace`` يُنشئ عنصرًا جديدًا بالمسار المحدَّث،
ويُستبدل داخل ``result.items`` بالفهرس — و``items`` قائمة عادية
قابلة للتعديل في مكانها رغم تجميد الحاوية، فلا يلزم إعادة
بناء النتيجة ولا تنكسر المراجع الممسوكة في الواجهة.

وإن تعذر تحديث العنصر، **يُرجَع الملف لاسمه الأول** حفاظًا على
اتساق القرص مع النتيجة — لا نقبل حالة وسطى مكسورة.
"""
from __future__ import annotations

import dataclasses
import json
import os
import sys
from pathlib import Path
from typing import Any

# اللواحق التي يكتبها المحرّك للنواتج النهائية.
_OUT_EXTS = (".webp", ".png", ".jpg", ".jpeg")


def _log(msg: str) -> None:
    print(f"[batch-naming] {msg}", file=sys.stderr)


def _units_for(item: str) -> list[str]:
    """وحدات الصنف من فهرس الإكسل المسجَّل — عبر ``integration_v2``."""
    try:
        from engine_v2 import integration_v2 as integ
        fn = getattr(integ, "_units_from_catalog", None)
        if fn is None:
            return []
        return list(fn(str(item)) or [])
    except Exception:
        return []


def _policy_active() -> tuple[bool, str]:
    """هل سياسة ``join_all_units`` مفعّلة؟ ومعها الوحدة الافتراضية."""
    try:
        from engine_v2 import integration_v2 as integ
        from engine_v2.naming_v2 import UNIT_POLICY_JOIN_ALL
        fn = getattr(integ, "_current_naming_settings", None)
        if fn is None:
            return False, "حبه"
        s = fn()
        if s is None or not getattr(s, "enabled", False):
            return False, "حبه"
        active = getattr(s, "unit_policy", "") == UNIT_POLICY_JOIN_ALL
        return active, getattr(s, "default_unit", "حبه")
    except Exception:
        return False, "حبه"


def _target_stem(item: str, units: list[str], seq: int,
                 default_unit: str) -> str:
    """الاسم المطلوب وفق قاعدة المالك — من ``engine_v2`` نفسها."""
    from engine_v2.naming_v2 import build_name_join_all
    return build_name_join_all(item, units, seq, total=seq,
                               default_unit=default_unit)


def _free_path(folder: Path, item: str, units: list[str],
               default_unit: str, ext: str,
               taken: set[str]) -> tuple[Path, str]:
    """أول مسار حر للصنف: الرئيسي بلا رقم ثم -1، -2 ...

    ``taken`` يمنع تصادم دفعة واحدة تكتب عدة صور للصنف نفسه قبل أن
    تظهر على القرص.
    """
    seq = 1
    while True:
        stem = _target_stem(item, units, seq, default_unit)
        cand = folder / f"{stem}{ext}"
        key = str(cand).casefold()
        if key not in taken and not cand.exists():
            return cand, stem
        seq += 1
        if seq > 9999:  # حاجز أمان
            return folder / f"{item}_{seq}{ext}", f"{item}_{seq}"


def _rewrite_state(workspace: Path, mapping: dict[str, str]) -> None:
    """يحدّث مسارات النواتج في تقارير مساحة العمل.

    بدون هذا تبقى ``state.json`` والتقارير تشير إلى أسماء قديمة لم تعد
    على القرص، فيفشل استئناف الجلسة وتظهر صور مفقودة في الواجهة.
    """
    if not mapping:
        return
    for name in ("state.json", "results.json", "state_v2.json"):
        path = workspace / name
        if not path.is_file():
            continue
        try:
            raw = path.read_text(encoding="utf-8")
            for old, new in mapping.items():
                raw = raw.replace(json.dumps(old, ensure_ascii=False)[1:-1],
                                  json.dumps(new, ensure_ascii=False)[1:-1])
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(raw, encoding="utf-8")
            os.replace(tmp, path)
        except Exception as exc:
            _log(f"تعذر تحديث {name}: {exc}")


def _set_output_path(items: Any, idx: int, item: Any, new_path: str) -> bool:
    """يضبط ``output_path`` للعنصر ويُرجع هل نجح.

    ثلاث محاولات بالترتيب، لأن بنية المحرّك مُصرّفة وقد تتغير:
    1) ``setattr`` مباشرة (لو لم يكن الصنف مُجمّدًا).
    2) ``dataclasses.replace`` + استبدال في القائمة (المسار الفعّال).
    3) ``object.__setattr__`` — يخترق التجميد إن تعذر الاستبدال
       (مثلاً لو كان ``items`` مجموعة غير قابلة للفهرسة).
    """
    try:
        setattr(item, "output_path", new_path)
        if str(getattr(item, "output_path", "")) == new_path:
            return True
    except Exception:
        pass
    try:
        if dataclasses.is_dataclass(item):
            fresh = dataclasses.replace(item, output_path=new_path)
            items[idx] = fresh
            return str(getattr(items[idx], "output_path", "")) == new_path
    except Exception as exc:
        _log(f"replace أخفق: {exc}")
    try:
        object.__setattr__(item, "output_path", new_path)
        return str(getattr(item, "output_path", "")) == new_path
    except Exception as exc:
        _log(f"__setattr__ أخفق: {exc}")
    return False


def apply_join_all_units(result: Any) -> Any:
    """يعيد تسمية نواتج الدفعة وفق كل وحدات الصنف. يعيد النتيجة نفسها.

    لا يرفع استثناءً أبدًا: أي إخفاق يُترك معه الاسم الأصلي، لأن فقدان
    قاعدة تسمية أهون من فقدان دفعة معالجة كاملة.
    """
    active, default_unit = _policy_active()
    if not active:
        return result
    items = getattr(result, "items", None)
    if not items:
        return result

    mapping: dict[str, str] = {}
    taken: set[str] = set()
    renamed = 0

    for idx, it in enumerate(items):
        try:
            out = getattr(it, "output_path", None)
            item_code = getattr(it, "item_code", None)
            if not out or not item_code:
                continue
            src = Path(out)
            if not src.is_absolute():
                ws = getattr(result, "workspace", None)
                if ws:
                    src = Path(ws) / out
            if not src.is_file() or src.suffix.casefold() not in _OUT_EXTS:
                continue
            units = _units_for(str(item_code))
            if not units:
                # لا كتالوج للصنف: لا مرجع نصحّح إليه.
                continue
            want_stem = _target_stem(str(item_code), units, 1, default_unit)
            if src.stem == want_stem or src.stem.startswith(want_stem + "-"):
                continue  # مطابق للقاعدة سلفًا
            dst, _stem = _free_path(src.parent, str(item_code), units,
                                    default_unit, src.suffix, taken)
            os.replace(src, dst)
            # حدّث النتيجة لتشير للملف الجديد. العناصر مُجمّدة
            # (frozen dataclass) فلا ينفع setattr — نستبدل العنصر.
            if not _set_output_path(items, idx, it, str(dst)):
                # لم نستطع تحديث النتيجة: أرجع الملف لاسمه لأن
                # قرصًا يخالف النتيجة يعني صورًا مفقودة في الواجهة.
                try:
                    os.replace(dst, src)
                except OSError:
                    pass
                _log(f"تعذر تحديث مسار النتيجة ⇒ أُرجع {src.name}")
                continue
            taken.add(str(dst).casefold())
            mapping[src.name] = dst.name
            renamed += 1
        except Exception as exc:
            _log(f"تعذرت إعادة تسمية عنصر: {exc}")

    if renamed:
        _log(f"طُبِّقت قاعدة كل الوحدات على {renamed} ملفًا")
        ws = getattr(result, "workspace", None)
        if ws:
            _rewrite_state(Path(ws), mapping)
    return result
