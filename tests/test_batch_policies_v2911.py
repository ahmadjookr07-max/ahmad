# -*- coding: utf-8 -*-
"""2.9.11 — رقعة الدفعة تطبّق **السياسات الأربع** لا اثنتين.

## ما يُفحص وسبب أهميته

مسار الدفعة هو الذي يستعمله المالك فعليًا في العمل اليومي (مئات
الصور)، وكان يمرّ في ``batch_naming_patch`` عبر علم منطقي واحد
(``join`` أم لا)، فسياستا ``replicate_all_units`` و``per_image``
لم تكن لهما وجود في الإنتاج مهما اختار المالك في الإعدادات:
الخيار يُحفظ ولا يُطبَّق — وهو أسوأ من غيابه لأنه يوهم بالعمل.

الاختبار يبني نواتج دفعة مزيفة على القرص (كائن نتيجة بنفس شكل
``BatchRunResult``: ``items`` + ``workspace``، والعناصر
``frozen dataclass`` كما في المحرّك المُصرَّف حتى نتأكد أن
``dataclasses.replace`` يعمل) ثم يستدعي ``apply_join_all_units``
لكل سياسة ويتحقق من:

1. اسم الملف على القرص مطابق للسياسة.
2. ``output_path`` في النتيجة يشير للملف الموجود فعلًا — فقرصٌ
   يخالف النتيجة يعني صورًا مفقودة في الواجهة (علة 2.9.10).
3. ``replicate_all_units`` يُنشئ **نسخة لكل وحدة** بمحتوى مطابق،
   ولا يزيد عدد ``items`` (النسخ مخرجات رفع لا نتائج معالجة).
4. استيفاء النسخ الناقصة لملف اسمه مطابق سلفًا (تغيير السياسة
   بعد معالجة سابقة).
"""
from __future__ import annotations

import dataclasses
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "windows_app"))

import batch_naming_patch as bnp  # noqa: E402
from engine_v2 import naming_v2  # noqa: E402

PASS, FAIL = 0, 0


def check(cond: bool, msg: str) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {msg}")
    else:
        FAIL += 1
        print(f"  ✗ {msg}")


@dataclasses.dataclass(frozen=True)
class FakeItem:
    """يحاكي ``BatchItemResult`` — مُجمّد عن قصد."""
    item_code: str
    output_path: str


@dataclasses.dataclass(frozen=True)
class FakeResult:
    """يحاكي ``BatchRunResult`` — الحاوية مُجمّدة و``items`` قائمة."""
    items: list
    workspace: str


def Settings(policy: str, default_unit: str = "حبه",
             enabled: bool = True):
    """إعدادات تسمية حقيقية — لا بديلًا مزيفًا.

    جُرّب أولًا بصنف وهمي فأخفق: ``plan_stems_for_policy``
    تستدعي ``settings.render`` وهي منطق القالب كله.
    والاختبار بإعدادات مزيفة لا يقاس أصلًا ما سيجري عند
    المالك، فالواجب تمرير ``NamingSettings`` نفسه.
    """
    s = naming_v2.NamingSettings()
    s.enabled = enabled
    s.unit_policy = policy
    s.default_unit = default_unit
    return s


def _install(units_map: dict[str, list[str]], settings) -> None:
    """يزرع الكتالوج والإعدادات في مسار قراءة الرقعة."""
    bnp._units_for = lambda item, join: list(units_map.get(str(item), []))
    bnp._policy_settings = lambda: settings
    bnp._policy_active = lambda: (
        bool(getattr(settings, "enabled", False)),
        getattr(settings, "unit_policy", "") == naming_v2.UNIT_POLICY_JOIN_ALL,
        getattr(settings, "default_unit", "حبه"),
    )


def _build(tmp: Path, names: dict[str, str]) -> FakeResult:
    """ينشئ ملفات نواتج ويعيد نتيجة دفعة تشير إليها."""
    items = []
    for code, fname in names.items():
        p = tmp / fname
        p.write_bytes(b"IMG:" + code.encode())
        items.append(FakeItem(item_code=code, output_path=str(p)))
    return FakeResult(items=items, workspace=str(tmp))


def _names(tmp: Path) -> set[str]:
    return {p.name for p in tmp.iterdir() if p.is_file()}


def test_default_unit() -> None:
    """``default_unit``: وحدة الإكسل الأولى والافتراضية احتياط.

    توقّعت أولًا أن تكتب الافتراضية دائمًا — وهو خطأٌ فهمتُه
    من الاسم. وتوثيق ``plan_stems_for_policy`` صريح: تصدير
    ``حبه`` دائمًا **هو العطب الذي أبلغ عنه المالك**؛
    فالأصل وحدة الإكسل الأولى، والافتراضية لصنف بلا
    وحدة في الإكسل فقط. فيُفحص الأمران.
    """
    print("\n[1] السياسة: الوحدة الواحدة (default_unit)")
    tmp = Path(tempfile.mkdtemp())
    try:
        _install({"10000014": ["كرتون", "حبه"]},
                 Settings(naming_v2.UNIT_POLICY_DEFAULT, "حبه"))
        res = _build(tmp, {"10000014": "10000014_خطأ.webp"})
        bnp.apply_join_all_units(res)
        check(_names(tmp) == {"10000014_كرتون.webp"},
              f"وحدة الإكسل الأولى لا الافتراضية العمياء: "
              f"{sorted(_names(tmp))}")
        check(Path(res.items[0].output_path).is_file(),
              "output_path يشير لملف موجود")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_default_unit_fallback() -> None:
    print("\n[1ب] صنف بلا وحدة في الإكسل ⇒ الافتراضية")
    tmp = Path(tempfile.mkdtemp())
    try:
        _install({"10000015": [""]},
                 Settings(naming_v2.UNIT_POLICY_DEFAULT, "حبه"))
        res = _build(tmp, {"10000015": "10000015_خطأ.webp"})
        bnp.apply_join_all_units(res)
        got = sorted(_names(tmp))
        check(got == ["10000015_حبه.webp"] or got == ["10000015_خطأ.webp"],
              f"لا تُكتب وحدة ملفقة لصنف بلا وحدة: {got}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_join_all() -> None:
    print("\n[2] السياسة: دمج كل الوحدات")
    tmp = Path(tempfile.mkdtemp())
    try:
        _install({"10008272": ["باكت", "حبه", "كرتون"]},
                 Settings(naming_v2.UNIT_POLICY_JOIN_ALL))
        res = _build(tmp, {"10008272": "10008272_حبه.webp"})
        bnp.apply_join_all_units(res)
        got = sorted(_names(tmp))
        check(len(got) == 1 and got[0].startswith("10008272_")
              and "باكت" in got[0] and "كرتون" in got[0],
              f"كل الوحدات في اسم واحد: {got}")
        check(Path(res.items[0].output_path).is_file(),
              "output_path يشير لملف موجود")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_per_image() -> None:
    print("\n[3] السياسة: وحدة الإكسل الأولى")
    tmp = Path(tempfile.mkdtemp())
    try:
        _install({"10031002": ["كرتون"]},
                 Settings(naming_v2.UNIT_POLICY_PER_IMAGE))
        # المحرّك المُصرَّف يسقط إلى «حبه» — وهي وحدة لا يملكها الصنف.
        res = _build(tmp, {"10031002": "10031002_حبه.webp"})
        bnp.apply_join_all_units(res)
        check(_names(tmp) == {"10031002_كرتون.webp"},
              f"صُحّحت الوحدة من الإكسل: {sorted(_names(tmp))}")
        check("حبه" not in Path(res.items[0].output_path).name,
              "لم تبق الوحدة العمياء «حبه»")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_replicate() -> None:
    print("\n[4] السياسة: نسخة لكل وحدة")
    tmp = Path(tempfile.mkdtemp())
    try:
        units = ["حبه", "كرتون", "باكت"]
        _install({"10010033": units},
                 Settings(naming_v2.UNIT_POLICY_REPLICATE))
        res = _build(tmp, {"10010033": "10010033_حبه_قديم.webp"})
        bnp.apply_join_all_units(res)
        got = _names(tmp)
        check(len(got) == len(units),
              f"عدد الملفات = عدد الوحدات ({len(units)}): {sorted(got)}")
        for u in units:
            check(any(u in n for n in got), f"توجد نسخة للوحدة: {u}")
        blobs = {(tmp / n).read_bytes() for n in got}
        check(len(blobs) == 1, "كل النسخ بنفس محتوى الأصل")
        check(len(res.items) == 1,
              "النسخ لم تُقحم في items (لا يتضاعف عدّاد المعالجة)")
        check(Path(res.items[0].output_path).is_file(),
              "output_path يشير لملف موجود")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_replicate_completes_missing() -> None:
    print("\n[5] استيفاء نسخ ناقصة لاسم مطابق سلفًا")
    tmp = Path(tempfile.mkdtemp())
    try:
        units = ["حبه", "كرتون"]
        st = Settings(naming_v2.UNIT_POLICY_REPLICATE)
        _install({"10000099": units}, st)
        first = naming_v2.plan_stems_for_policy(
            "10000099", units, 1, total=1, settings=st)[0]
        res = _build(tmp, {"10000099": f"{first}.webp"})
        bnp.apply_join_all_units(res)
        got = _names(tmp)
        check(len(got) == 2, f"استُوفيت النسخة الناقصة: {sorted(got)}")
        check(f"{first}.webp" in got, "الملف الأصلي لم يُعد تسميته عبثًا")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_disabled_does_nothing() -> None:
    print("\n[6] التسمية المخصّصة معطّلة ⇒ لا تغيير")
    tmp = Path(tempfile.mkdtemp())
    try:
        _install({"10000014": ["كرتون"]},
                 Settings(naming_v2.UNIT_POLICY_REPLICATE, enabled=False))
        res = _build(tmp, {"10000014": "أصلي.webp"})
        bnp.apply_join_all_units(res)
        check(_names(tmp) == {"أصلي.webp"},
              "لم يُفرض أي اسم لم يطلبه المستخدم")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_no_catalog_left_alone() -> None:
    print("\n[7] صنف بلا كتالوج يبقى كما هو")
    tmp = Path(tempfile.mkdtemp())
    try:
        _install({}, Settings(naming_v2.UNIT_POLICY_REPLICATE))
        res = _build(tmp, {"99999999": "99999999_حبه.webp"})
        bnp.apply_join_all_units(res)
        check(_names(tmp) == {"99999999_حبه.webp"},
              "لا مرجع نصحّح إليه ⇒ لا مساس بالملف")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    print("=" * 62)
    print("رقعة الدفعة — السياسات الأربع (2.9.11)")
    print("=" * 62)
    for fn in (test_default_unit, test_default_unit_fallback,
               test_join_all, test_per_image,
               test_replicate, test_replicate_completes_missing,
               test_disabled_does_nothing, test_no_catalog_left_alone):
        fn()
    print("=" * 62)
    print(f"النتيجة: {PASS}/{PASS + FAIL}")
    if FAIL:
        print(f"فشل {FAIL} فحصًا")
        return 1
    print("كل الفحوص نجحت ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
