# -*- coding: utf-8 -*-
"""حاجز 2.9.11 — المجلد المنجز/القديم يطبّق السياسات الأربع.

أمر المالك حرفيًا: «والخيار يجب أن يكون مفعل في المنجزة والقديمة».
قبل هذا الحاجز كان `plan_legacy_renames` يختزل السياسة في علم
منطقي واحد (`join_all`) فيسقط `replicate_all_units` و
`default_unit` في وحدة واحدة، فيبقى المجلد المنجز كله `_حبه`
مهما اختار المالك.

الاختبار يبني مجلدًا منجزًا حقيقيًا على القرص (صنف بثلاث وحدات
من الإكسل حبه/شدة/كرتون وصورتان) ويقيس المخرج في كل سياسة.

تحديث 2.9.12: اصطلاح الترقيم صار (بلا رقم، 1، 2) بدل (بلا
رقم، 2، 3) بأمر المالك، فحُدّثت التوقعات هنا تبعًا لذلك.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine_v2 import legacy_folder_v2 as LF          # noqa: E402
from engine_v2.naming_v2 import (NamingSettings,      # noqa: E402
                                 UNIT_POLICY_DEFAULT,
                                 UNIT_POLICY_JOIN_ALL,
                                 UNIT_POLICY_REPLICATE,
                                 UNIT_POLICY_PER_IMAGE)

UNITS = ["حبه", "شدة", "كرتون"]
ITEM = "10011205"


class FakeIndex:
    """فهرس إكسل مصغّر — وحدات الصنف بترتيب الإكسل حرفيًا."""

    def units_for_code(self, code: str):
        return list(UNITS) if str(code) == ITEM else []

    def primary_unit_for_code(self, code: str):
        return UNITS[0] if str(code) == ITEM else ""


def _make_folder(tmp: Path, count: int = 2) -> Path:
    """مجلد منجز بالنمط القديم `{item}_{unit}` و`{item}_{unit}_2`."""
    folder = tmp / "منجز"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{ITEM}_حبه.webp").write_bytes(b"a")
    if count > 1:
        (folder / f"{ITEM}_حبه_2.webp").write_bytes(b"b")
    return folder


def _plan_with_policy(folder: Path, policy: str):
    """يبني الخطة بسياسة محددة عبر حقن الإعدادات في الوحدة."""
    settings = NamingSettings()
    settings.enabled = True
    settings.unit_policy = policy
    original = LF._naming_settings
    LF._naming_settings = lambda: settings          # type: ignore[assignment]
    try:
        groups, unparsed = LF.scan_legacy_folder(folder)
        return LF.plan_legacy_renames(groups, index=FakeIndex(),
                                      unparsed=unparsed), groups
    finally:
        LF._naming_settings = original              # type: ignore[assignment]


def test_join_all_units():
    """الدمج: كل وحدات الإكسل بترتيبها، والثانية `-1` (2.9.12)."""
    tmp = Path(tempfile.mkdtemp())
    try:
        folder = _make_folder(tmp)
        plan, _ = _plan_with_policy(folder, UNIT_POLICY_JOIN_ALL)
        stems = [r.new_stem for r in plan.rows]
        assert stems[0] == f"{ITEM}_حبه_شدة_كرتون", stems
        assert stems[1] == f"{ITEM}_حبه_شدة_كرتون-1", stems
        assert all(not r.copies for r in plan.rows)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_default_unit_reads_excel():
    """الوحدة الواحدة: أولى وحدات الإكسل هي الأصل لا قيمة ثابتة."""
    tmp = Path(tempfile.mkdtemp())
    try:
        folder = _make_folder(tmp)
        plan, _ = _plan_with_policy(folder, UNIT_POLICY_DEFAULT)
        stems = [r.new_stem for r in plan.rows]
        assert stems[0] == f"{ITEM}_حبه", stems
        assert stems[1] == f"{ITEM}_حبه-1", stems
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_replicate_plans_one_name_per_unit():
    """نسخة لكل وحدة: ثلاثة أسماء لكل صورة، والباقي نُسخ لا نقل."""
    tmp = Path(tempfile.mkdtemp())
    try:
        folder = _make_folder(tmp)
        plan, _ = _plan_with_policy(folder, UNIT_POLICY_REPLICATE)
        first = plan.rows[0]
        assert first.new_stem == f"{ITEM}_حبه", first.new_stem
        assert first.copies == [f"{ITEM}_شدة", f"{ITEM}_كرتون"], first.copies
        second = plan.rows[1]
        assert second.new_stem == f"{ITEM}_حبه-1", second.new_stem
        assert second.copies == [f"{ITEM}_شدة-1", f"{ITEM}_كرتون-1"], \
            second.copies
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_replicate_applies_copies_on_disk():
    """التنفيذ الفعلي: ست صور بعد النسخ ولا ملف مفقود."""
    tmp = Path(tempfile.mkdtemp())
    try:
        folder = _make_folder(tmp)
        plan, _ = _plan_with_policy(folder, UNIT_POLICY_REPLICATE)
        res = LF.apply_legacy_plan(plan)
        assert not res["errors"], res["errors"]
        names = sorted(p.name for p in folder.glob("*.webp"))
        expected = sorted([
            f"{ITEM}_حبه.webp", f"{ITEM}_شدة.webp", f"{ITEM}_كرتون.webp",
            f"{ITEM}_حبه-1.webp", f"{ITEM}_شدة-1.webp", f"{ITEM}_كرتون-1.webp",
        ])
        assert names == expected, names
        # لا فقدان بيانات: كل نسخة تحمل محتوى أصلها
        assert (folder / f"{ITEM}_شدة.webp").read_bytes() == b"a"
        assert (folder / f"{ITEM}_كرتون-1.webp").read_bytes() == b"b"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_per_image_uses_excel_first_unit():
    """لكل صورة وحدتها: بلا اختيار يدوي تُستخدم وحدة الإكسل الأولى."""
    tmp = Path(tempfile.mkdtemp())
    try:
        folder = _make_folder(tmp)
        plan, _ = _plan_with_policy(folder, UNIT_POLICY_PER_IMAGE)
        assert plan.rows[0].new_stem == f"{ITEM}_حبه"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_disabled_settings_keeps_old_path():
    """الخيار معطّل ⇒ لا تغيير في القاعدة القديمة (لا انهيار)."""
    tmp = Path(tempfile.mkdtemp())
    try:
        folder = _make_folder(tmp)
        settings = NamingSettings()
        settings.enabled = False
        original = LF._naming_settings
        LF._naming_settings = lambda: settings   # type: ignore[assignment]
        try:
            groups, unparsed = LF.scan_legacy_folder(folder)
            plan = LF.plan_legacy_renames(groups, index=FakeIndex(),
                                          unparsed=unparsed)
        finally:
            LF._naming_settings = original       # type: ignore[assignment]
        stems = [r.new_stem for r in plan.rows]
        assert stems[0] == f"{ITEM}_حبه", stems
        assert stems[1] == f"{ITEM}_حبه-1", stems
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  ✗ {fn.__name__}: {exc}")
        except Exception as exc:  # pragma: no cover
            failed += 1
            print(f"  ✗ {fn.__name__}: خطأ غير متوقع: {exc!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} ناجح")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
