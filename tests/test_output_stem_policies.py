"""اختبار build_output_stem مع سياسات dash وjoin_all_units.

2.9.12 — اصطلاح المالك الجديد: الرئيسية بلا رقم، ثم **1، 2، 3**.
أي أن الصورة الثانية للصنف هي `-1` لا `-2`. وهذا يلغي المنع
القديم لـ`-1` الذي كان قائمًا في 2.9.9، لأن `-1` صار رقمًا
مشروعًا يعني «الصورة الثانية».

ما يبقى ثابتًا: لا يتكرر رقم، ولا تُطمس صورة موجودة على القرص.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from engine_v2 import integration_v2 as iv  # noqa: E402
from engine_v2 import naming_v2 as nv  # noqa: E402


class FakeIdx:
    def units_for_code(self, code):
        return ["حبة", "شدة", "كرتون"]


def main() -> None:
    with tempfile.TemporaryDirectory() as root, \
            tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "10001102_حبه.webp").write_bytes(b"x")

        # 1) سياسة dash: الصورة التالية بعد الرئيسية = -1 (2.9.12)
        s = nv.NamingSettings(enabled=True, scheme=nv.SCHEME_DASH)
        nv.save_settings(root, s)
        iv.NAMING_DATA_ROOT = root
        stem = iv.build_output_stem(d, "10001102")
        assert stem == "10001102_حبه-1", stem
        print("dash next:", stem)

        # 2) سياسة join_all_units مع كتالوج مسجل
        iv.set_catalog_index(FakeIdx())
        s2 = nv.NamingSettings(enabled=True, scheme=nv.SCHEME_DASH,
                               unit_policy=nv.UNIT_POLICY_JOIN_ALL)
        nv.save_settings(root, s2)
        d2 = Path(td) / "j"
        d2.mkdir()
        first = iv.build_output_stem(d2, "10001102")
        assert first == "10001102_حبة_شدة_كرتون", first
        print("join_all first:", first)
        (d2 / f"{first}.webp").write_bytes(b"x")
        second = iv.build_output_stem(d2, "10001102")
        assert second == "10001102_حبة_شدة_كرتون-1", second
        print("join_all second:", second)
        (d2 / f"{second}.webp").write_bytes(b"x")
        third = iv.build_output_stem(d2, "10001102")
        # الثالثة تأخذ -2؛ إرجاع -1 مرة ثانية يطمس ملفًا مكتوبًا توًّا.
        assert third == "10001102_حبة_شدة_كرتون-2", third
        print("join_all third:", third)
        (d2 / f"{third}.webp").write_bytes(b"x")
        fourth = iv.build_output_stem(d2, "10001102")
        assert fourth == "10001102_حبة_شدة_كرتون-3", fourth
        print("join_all fourth:", fourth)

        # لا تكرار، والرئيسية وحدها بلا رقم.
        got = [first, second, third, fourth]
        assert len(set(got)) == 4, f"تكرار أسماء: {got}"
        assert sum(1 for n in got if "-" not in n.rsplit("_", 1)[-1]) == 1, got

        # 3) ملء الفجوات: حذف الوسط ثم طلب اسم جديد يعيد استعمال
        #    الرقم الشاغر بدل التصاعد إلى ما لا نهاية.
        (d2 / f"{second}.webp").unlink()
        refilled = iv.build_output_stem(d2, "10001102")
        assert refilled == "10001102_حبة_شدة_كرتون-1", refilled
        print("gap refilled:", refilled)
    print("OUTPUT STEM POLICY TESTS PASSED")


if __name__ == "__main__":
    main()
