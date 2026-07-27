# -*- coding: utf-8 -*-
"""اختبارات أداة التنظيف حسب اللقطة/الوحدة وإصلاح التكرارات الفاسدة."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from engine_v2.cleanup_v2 import (apply_plan, available_seqs,  # noqa: E402
                                  available_units, plan_cleanup,
                                  plan_fix_duplicates)

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049"
    "454e44ae426082")


def make(folder: Path, name: str, payload: bytes = PNG) -> Path:
    p = folder / name
    p.write_bytes(payload)
    return p


def test_scan_and_availability(tmp_path):
    make(tmp_path, "10001_حبه.webp")
    make(tmp_path, "10001_2_حبه.webp")
    make(tmp_path, "10002_شده.webp")
    assert available_units(tmp_path) == ["حبه", "شده"]
    assert available_seqs(tmp_path) == [1, 2]


def test_keep_only_seq2(tmp_path):
    """الاحتفاظ باللقطة الثانية فقط لكل صنف وحذف الباقي وإعادة تسميتها غلافًا."""
    make(tmp_path, "10001_حبه.webp")
    make(tmp_path, "10001_2_حبه.webp")
    make(tmp_path, "10001_3_حبه.webp")
    make(tmp_path, "10002_حبه.webp")  # لا لقطة 2 لهذا الصنف — يبقى سليمًا
    plan = plan_cleanup(tmp_path, seq_filter=2, mode="keep_only")
    deleted, renamed, errors = apply_plan(plan)
    assert not errors
    assert deleted == 2  # 10001 و10001_3 حذفتا
    names = sorted(p.name for p in tmp_path.iterdir() if p.is_file())
    assert "10001_حبه.webp" in names          # اللقطة 2 أصبحت الغلاف
    assert "10002_حبه.webp" in names          # لم يُمس
    assert not any("_2_" in n or "_3_" in n for n in names)
    assert (tmp_path / "_المحذوفات").is_dir()


def test_delete_only_seq3(tmp_path):
    """حذف اللقطة الثالثة فقط من جميع الأصناف والإبقاء على الباقي."""
    make(tmp_path, "10001_حبه.webp")
    make(tmp_path, "10001_2_حبه.webp")
    make(tmp_path, "10001_3_حبه.webp")
    plan = plan_cleanup(tmp_path, seq_filter=3, mode="delete_only",
                        rename_survivors=False)
    deleted, renamed, errors = apply_plan(plan)
    assert not errors and deleted == 1 and renamed == 0
    names = {p.name for p in tmp_path.iterdir() if p.is_file()}
    assert names == {"10001_حبه.webp", "10001_2_حبه.webp"}


def test_unit_filter_and_change(tmp_path):
    """فلترة بالوحدة مع تغيير وحدة المتبقي."""
    make(tmp_path, "10001_حبه.webp")
    make(tmp_path, "10001_2_شده.webp")
    plan = plan_cleanup(tmp_path, unit_filter="شده", mode="keep_only",
                        new_unit="كرتون")
    deleted, renamed, errors = apply_plan(plan)
    assert not errors and deleted == 1
    names = {p.name for p in tmp_path.iterdir() if p.is_file()}
    assert "10001_كرتون.webp" in names


def test_fix_mangled_duplicates(tmp_path):
    """أسماء `_2__حبه` المطابقة محتوًى تُحذف والمختلفة تُعاد تسميتها."""
    make(tmp_path, "10001_2_حبه.webp", PNG)
    make(tmp_path, "10001_2__حبه.webp", PNG)              # مكرر بالمحتوى
    make(tmp_path, "10002_2_حبه.webp", PNG)
    make(tmp_path, "10002_2__حبه.webp", PNG + b"x")       # محتوى مختلف
    plan = plan_fix_duplicates(tmp_path)
    deleted, renamed, errors = apply_plan(plan)
    assert not errors
    assert deleted == 1 and renamed == 1
    names = {p.name for p in tmp_path.iterdir() if p.is_file()}
    assert "10001_2_حبه.webp" in names
    assert "10002_3_حبه.webp" in names        # أصبحت لقطة إضافية قانونية
    assert not any("__" in n for n in names)


def test_no_match_no_damage(tmp_path):
    """فلتر لا يطابق شيئًا في keep_only لا يحذف أي ملف (أمان)."""
    make(tmp_path, "10001_حبه.webp")
    plan = plan_cleanup(tmp_path, seq_filter=5, mode="keep_only")
    deleted, renamed, errors = apply_plan(plan)
    assert deleted == 0 and not errors
    assert (tmp_path / "10001_حبه.webp").exists()


if __name__ == "__main__":
    import inspect
    import tempfile
    mod = sys.modules[__name__]
    passed = 0
    for name, fn in sorted(inspect.getmembers(mod, inspect.isfunction)):
        if not name.startswith("test_"):
            continue
        with tempfile.TemporaryDirectory() as td:
            fn(Path(td))
        print(f"OK  {name}")
        passed += 1
    print(f"\n{passed} tests passed")
