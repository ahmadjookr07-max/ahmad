# -*- coding: utf-8 -*-
"""اختبار سياسة join_all_units.

2.9.10 — قاعدة المالك النهائية كما نصّ عليها حرفيًا:
الرئيسية (الواجهة ★) ``{item}_حبة_شدة_كرتون`` **بلا رقم**،
والإضافية الأولى ``-1`` ثم ``-2`` ثم ``-3`` — أي أن الرقم هو
ترتيب الصورة **بين الإضافيات** لا بين كل صور الصنف.

لا تصادم مع الرئيسية لأنها بلا رقم أصلًا: ``base`` لا يماثل
``base-1``. لذلك حجة 2.9.9 التي حوّلت الإضافية الأولى إلى ``-2``
باطلة، وقد أُعيد الأمر إلى ما طلبه المالك.

والوحدات تُجمع **حرفيًا من الإكسل وبنفس ترتيب صفوفه** بلا
إعادة ترتيب (لا تصدير لوحدة العبوة=1 في هذه السياسة).
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from engine_v2.naming_v2 import (build_name_join_all, join_units,
                                 NamingSettings, plan_names_for_item,
                                 UNIT_POLICY_JOIN_ALL, VALID_POLICIES)
from engine_v2 import integration_v2 as integ


def test_join_units():
    assert join_units(["حبة", "شدة", "كرتون"]) == "حبة_شدة_كرتون"
    assert join_units(["كرتون", "حبة"]) == "كرتون_حبة"  # ترتيب الإكسل يُحترم
    assert join_units([]) == "حبه"
    assert join_units(["حبة", "حبة", "شدة"]) == "حبة_شدة"  # إزالة تكرار فقط


def test_build_name_join_all():
    u = ["حبة", "شدة", "كرتون"]
    assert build_name_join_all("10001102", u, 1) == "10001102_حبة_شدة_كرتون"
    assert build_name_join_all("10001102", u, 2) == "10001102_حبة_شدة_كرتون-1"
    assert build_name_join_all("10001102", u, 4) == "10001102_حبة_شدة_كرتون-3"
    assert build_name_join_all("10001102", ["حبة"], 1) == "10001102_حبة"
    assert build_name_join_all("10001102", ["حبة"], 2) == "10001102_حبة-1"


def test_owner_examples_verbatim():
    """أمثلة المالك الثلاثة كما كتبها نصًّا — لا تُعدّل."""
    assert build_name_join_all("10011205", ["حبه", "شدة", "كرتون"], 1) \
        == "10011205_حبه_شدة_كرتون"
    assert build_name_join_all("10011205", ["حبه", "شدة", "كرتون"], 2) \
        == "10011205_حبه_شدة_كرتون-1"
    assert build_name_join_all("10011205", ["حبه", "شدة", "كرتون"], 3) \
        == "10011205_حبه_شدة_كرتون-2"
    assert build_name_join_all("10000429", ["حبه", "كرتون"], 1) \
        == "10000429_حبه_كرتون"
    assert build_name_join_all("10000429", ["حبه", "كرتون"], 2) \
        == "10000429_حبه_كرتون-1"
    assert build_name_join_all("10001205", ["حبه"], 1) == "10001205_حبه"
    assert build_name_join_all("10001205", ["حبه"], 2) == "10001205_حبه-1"


def test_no_collision_primary_vs_first_extra():
    """الرئيسية والإضافية الأولى لا يتصادمان (حرس الانعكاس).

    مَن يقرأ الكود لاحقًا فيظنّ ``-1`` عطبًا «يتداخل مع
    الرئيسية» فليقرأ هذا: الرئيسية بلا رقم، فلا تماثل.
    """
    u = ["حبه", "شدة", "كرتون"]
    names = [build_name_join_all("10011205", u, i) for i in range(1, 6)]
    assert len(names) == len(set(names)), names
    assert names[0] == "10011205_حبه_شدة_كرتون"
    assert names[1] == "10011205_حبه_شدة_كرتون-1"
    assert not any(n.endswith("-0") for n in names), names


def test_plan_names_for_item():
    s = NamingSettings(unit_policy=UNIT_POLICY_JOIN_ALL)
    plans = plan_names_for_item("10001102", 3, ["حبة", "شدة"], s)
    # 2.9.10 — قاعدة المالك: الرئيسية بلا رقم ثم -1 ثم -2.
    assert plans == [["10001102_حبة_شدة"],
                     ["10001102_حبة_شدة-1"],
                     ["10001102_حبة_شدة-2"]], plans
    flat = [n for grp in plans for n in grp]
    assert len(flat) == len(set(flat)), f"تكرار أسماء: {flat}"
    assert not any(n.endswith("-0") for n in flat), flat


def test_from_dict():
    s2 = NamingSettings.from_dict({"unit_policy": "join_all_units",
                                   "enabled": True})
    assert s2.unit_policy == "join_all_units"
    assert "join_all_units" in VALID_POLICIES


class FakeIdx:
    def units_for_code(self, code):
        return ["حبة", "شدة", "كرتون"] if code == "10001102" else []


class FakeIdxUnordered:
    """الإكسل يضع الكرتون أولًا والحبة أخيرًا (وعبوة الحبة=1).

    يحرس أمر المالك «بنفس ترتيبها»: الدمج يتبع ترتيب الصفوف
    حرفيًا ولا يقدّم وحدة العبوة=1 كما تفعل سياسة الوحدة الواحدة.
    """

    def units_for_code(self, code):
        return ["كرتون", "شدة", "حبة"] if code == "10001102" else []

    def primary_unit_for_code(self, code):
        return "حبة" if code == "10001102" else ""


def _write_policy(td: str) -> str:
    settings_dir = os.path.join(td, "data")
    os.makedirs(settings_dir, exist_ok=True)
    with open(os.path.join(settings_dir, "naming_settings.json"), "w",
              encoding="utf-8") as f:
        json.dump({"unit_policy": "join_all_units", "enabled": True},
                  f, ensure_ascii=False)
    return settings_dir


def test_build_output_stem_join_all():
    integ.set_catalog_index(FakeIdx())
    with tempfile.TemporaryDirectory() as td:
        settings_dir = _write_policy(td)
        old_root = getattr(integ, "NAMING_DATA_ROOT", None)
        integ.NAMING_DATA_ROOT = settings_dir
        try:
            out = os.path.join(td, "out")
            os.makedirs(out)
            n1 = integ.build_output_stem(out, "10001102", "حبة")
            assert n1 == "10001102_حبة_شدة_كرتون", n1
            open(os.path.join(out, n1 + ".webp"), "wb").close()
            n2 = integ.build_output_stem(out, "10001102", "حبة")
            assert n2 == "10001102_حبة_شدة_كرتون-1", n2
            open(os.path.join(out, n2 + ".webp"), "wb").close()
            n3 = integ.build_output_stem(out, "10001102", "حبة")
            # الثالثة -2؛ الاسم -1 مشغول على القرص فعلًا
            # وإرجاعه يطمس صورة المالك.
            assert n3 == "10001102_حبة_شدة_كرتون-2", n3
            # صنف خارج الكتالوج → يعتمد وحدة الاستدعاء
            n4 = integ.build_output_stem(out, "999", "باكت")
            assert n4 == "999_باكت", n4
        finally:
            integ.NAMING_DATA_ROOT = old_root
            integ.set_catalog_index(None)


def test_excel_order_respected_not_primary_first():
    """الدمج يتبع ترتيب صفوف الإكسل حرفيًا لا وحدة العبوة=1."""
    integ.set_catalog_index(FakeIdxUnordered())
    with tempfile.TemporaryDirectory() as td:
        settings_dir = _write_policy(td)
        old_root = getattr(integ, "NAMING_DATA_ROOT", None)
        integ.NAMING_DATA_ROOT = settings_dir
        try:
            out = os.path.join(td, "out")
            os.makedirs(out)
            n1 = integ.build_output_stem(out, "10001102", "حبة")
            assert n1 == "10001102_كرتون_شدة_حبة", n1
            # وسياسة الوحدة الواحدة تبقى تقدّم وحدة العبوة=1
            units_single = integ._units_from_catalog("10001102")
            assert units_single and units_single[0] == "حبة", units_single
            units_join = integ._units_from_catalog("10001102",
                                                   excel_order=True)
            assert units_join == ["كرتون", "شدة", "حبة"], units_join
        finally:
            integ.NAMING_DATA_ROOT = old_root
            integ.set_catalog_index(None)


if __name__ == "__main__":
    test_join_units()
    test_build_name_join_all()
    test_owner_examples_verbatim()
    test_no_collision_primary_vs_first_extra()
    test_plan_names_for_item()
    test_from_dict()
    test_build_output_stem_join_all()
    test_excel_order_respected_not_primary_first()
    print("ALL_JOIN_ALL_TESTS_OK")
