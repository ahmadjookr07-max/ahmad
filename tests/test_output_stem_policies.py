"""اختبار build_output_stem مع سياسات dash وjoin_all_units.

2.9.10 — قاعدة المالك النهائية: الرئيسية (الواجهة ★) **بلا رقم**،
والإضافية الأولى ``-1`` ثم ``-2`` ثم ``-3``. الرقم ترتيب الصورة
بين الإضافيات، ولا تصادم مع الرئيسية لأنها بلا رقم أصلًا.

ويبقى الشرط الجوهري قائمًا: **لا يُرجَع اسم مشغول على القرص**
فلا تُطمس صورة موجودة — وهو ما يحرسه تسلسل الأسماء أدناه.
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


class FakeIdxUnordered:
    """صفوف الإكسل: الكرتون أولًا، ووحدة العبوة=1 هي الحبة."""

    def units_for_code(self, code):
        return ["كرتون", "شدة", "حبة"]

    def primary_unit_for_code(self, code):
        return "حبة"


def main() -> None:
    with tempfile.TemporaryDirectory() as root, \
            tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "10001102_حبه.webp").write_bytes(b"x")

        # 1) سياسة dash: الإضافية الأولى بعد الرئيسية = -1
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
        # الثالثة -2؛ إرجاع -1 مرة ثانية يطمس الملف المكتوب توًّا.
        assert third == "10001102_حبة_شدة_كرتون-2", third
        print("join_all third:", third)
        (d2 / f"{third}.webp").write_bytes(b"x")
        fourth = iv.build_output_stem(d2, "10001102")
        assert fourth == "10001102_حبة_شدة_كرتون-3", fourth
        print("join_all fourth:", fourth)
        # لا رقم -0 في أي مرحلة، ولا اسم مكرر يطمس ملفًا
        got = [first, second, third, fourth]
        assert not any(n.endswith("-0") for n in got), got
        assert len(set(got)) == 4, f"تكرار أسماء: {got}"

        # 3) الدمج يتبع ترتيب صفوف الإكسل حرفيًا («بنفس ترتيبها»)
        #    ولا يقدّم وحدة العبوة=1 كما تفعل سياسة الوحدة الواحدة.
        iv.set_catalog_index(FakeIdxUnordered())
        d3 = Path(td) / "k"
        d3.mkdir()
        ordered = iv.build_output_stem(d3, "10001102")
        assert ordered == "10001102_كرتون_شدة_حبة", ordered
        print("join_all excel order:", ordered)
        single = iv._units_from_catalog("10001102")
        assert single and single[0] == "حبة", single
        iv.set_catalog_index(None)
    print("OUTPUT STEM POLICY TESTS PASSED")


if __name__ == "__main__":
    main()
