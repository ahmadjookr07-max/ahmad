"""اختبار build_output_stem مع سياسات dash وjoin_all_units."""
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

        # 1) سياسة dash: الصورة التالية بعد الرئيسية = -1
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
        assert third == "10001102_حبة_شدة_كرتون-2", third
        print("join_all third:", third)
    print("OUTPUT STEM POLICY TESTS PASSED")


if __name__ == "__main__":
    main()
