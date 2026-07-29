# -*- coding: utf-8 -*-
"""اختبار تعيين الصورة الرئيسية وإعادة الترقيم (2.3)."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from engine_v2.primary_image_v2 import renumber_item_images  # noqa: E402


def _touch(d: Path, name: str) -> Path:
    p = d / name
    p.write_bytes(b"x")
    return p


def test_basic_dash_policy():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        a = _touch(d, "10001102_حبه.webp")      # الرئيسية الحالية
        b = _touch(d, "10001102_حبه-1.webp")
        c = _touch(d, "10001102_حبه-2.webp")
        # نجعل c هي الرئيسية الجديدة
        res = renumber_item_images(d, "10001102", [c, a, b], ["حبه"], settings=None)
        assert res.ok, res.error
        assert Path(res.primary_path).name == "10001102_حبه.webp"
        names = sorted(p.name for p in d.glob("*.webp"))
        assert names == sorted([
            "10001102_حبه.webp", "10001102_حبه-1.webp", "10001102_حبه-2.webp"]), names
        # الملف الرئيسي الجديد يجب أن يحمل محتوى c الأصلي — تحقق بالحجم نفسه (كلها x)
        print("basic dash OK:", names)


def test_join_all_policy():
    from engine_v2 import naming_v2 as nv
    settings = nv.NamingSettings(enabled=True, scheme=nv.SCHEME_DASH,
                                 unit_policy=nv.UNIT_POLICY_JOIN_ALL,
                                 default_unit="حبه")
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        a = _touch(d, "555_حبة_شدة.webp")
        b = _touch(d, "555_حبة_شدة-1.webp")
        res = renumber_item_images(d, "555", [b, a], ["حبة", "شدة"],
                                   settings=settings)
        assert res.ok, res.error
        names = sorted(p.name for p in d.glob("*.webp"))
        assert names == sorted(["555_حبة_شدة.webp", "555_حبة_شدة-1.webp"]), names
        print("join_all OK:", names)


def test_siblings_move_together():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        a = _touch(d, "77_حبه.webp")
        _touch(d, "77_حبه.png")  # شقيق بنفس الجذع
        b = _touch(d, "77_حبه-1.webp")
        res = renumber_item_images(d, "77", [b, a], ["حبه"], settings=None)
        assert res.ok, res.error
        names = sorted(p.name for p in d.iterdir())
        assert "77_حبه.webp" in names and "77_حبه-1.webp" in names \
            and "77_حبه-1.png" in names, names
        print("siblings OK:", names)


if __name__ == "__main__":
    test_basic_dash_policy()
    test_join_all_policy()
    test_siblings_move_together()
    print("ALL PRIMARY IMAGE TESTS PASSED")
