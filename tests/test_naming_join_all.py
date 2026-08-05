# -*- coding: utf-8 -*-
"""اختبار سياسة join_all_units.

2.9.12 — اصطلاح المالك الجديد: الرئيسية
``{item}_حبة_شدة_كرتون`` بلا رقم، ثم ``-1`` ثم ``-2`` ثم ``-3``.
أي أن ``-1`` صار رقمًا مشروعًا يعني «الصورة الثانية»، بعدما
كان ممنوعًا في 2.9.9. ويبقى الشرط الثابت: لا تكرار لرقم
واحد، والوحدات حرفيًا من الإكسل وبنفس الترتيب.
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


def test_plan_names_for_item():
    s = NamingSettings(unit_policy=UNIT_POLICY_JOIN_ALL)
    plans = plan_names_for_item("10001102", 3, ["حبة", "شدة"], s)
    # 2.9.12 — تسلسل متصل بلا تكرار: الرئيسية ثم -1 ثم -2.
    assert plans == [["10001102_حبة_شدة"],
                     ["10001102_حبة_شدة-1"],
                     ["10001102_حبة_شدة-2"]], plans
    flat = [n for grp in plans for n in grp]
    assert len(flat) == len(set(flat)), f"تكرار أسماء: {flat}"
    # الرئيسية وحدها بلا رقم.
    assert sum(1 for n in flat if "-" not in n) == 1, flat


def test_from_dict():
    s2 = NamingSettings.from_dict({"unit_policy": "join_all_units",
                                   "enabled": True})
    assert s2.unit_policy == "join_all_units"
    assert "join_all_units" in VALID_POLICIES


class FakeIdx:
    def units_for_code(self, code):
        return ["حبة", "شدة", "كرتون"] if code == "10001102" else []


def test_build_output_stem_join_all():
    integ.set_catalog_index(FakeIdx())
    with tempfile.TemporaryDirectory() as td:
        settings_dir = os.path.join(td, "data")
        os.makedirs(settings_dir)
        with open(os.path.join(settings_dir, "naming_settings.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"unit_policy": "join_all_units", "enabled": True},
                      f, ensure_ascii=False)
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
            # الثالثة تأخذ -2 لا -1؛ فالاسم -1 مشغول على القرص
            # فعلًا وإرجاعه يطمس صورة المالك.
            assert n3 == "10001102_حبة_شدة_كرتون-2", n3
            # صنف خارج الكتالوج → يعتمد وحدة الاستدعاء
            n4 = integ.build_output_stem(out, "999", "باكت")
            assert n4 == "999_باكت", n4
        finally:
            integ.NAMING_DATA_ROOT = old_root
            integ.set_catalog_index(None)


if __name__ == "__main__":
    test_join_units()
    test_build_name_join_all()
    test_plan_names_for_item()
    test_from_dict()
    test_build_output_stem_join_all()
    print("ALL_JOIN_ALL_TESTS_OK")
