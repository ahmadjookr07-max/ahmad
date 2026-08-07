# -*- coding: utf-8 -*-
"""اختبار `editor_sync_patch` (م-3 م-8 م-9 م-13).

يتحقق من: حرس فساد البيانات، التزامن عند تغيير الصف، ومؤشر الأدوات.
(انزياح الفرشاة يحتاج Qt فيُختبر بالتشغيل الفعلي.)
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "windows_app"))

from windows_app.editor_sync_patch import install_editor_sync  # noqa: E402

FAILS: list[str] = []


def check(c: bool, msg: str) -> None:
    print(("  ✓ " if c else "  ✗ ") + msg)
    if not c:
        FAILS.append(msg)


class FakeEditor:
    def __init__(self, path: str = "") -> None:
        self._image_path = path
        self._has_image = bool(path)
        self._has_edits = False
        self.loaded: list[str] = []
        self.tool: str = ""
        self.erase_btn = FakeBtn()
        self.restore_btn = FakeBtn()

    def has_image(self) -> bool:
        return self._has_image

    def has_edits(self) -> bool:
        return self._has_edits

    def load_image(self, p: str) -> None:
        self._image_path = p
        self._has_image = True
        self.loaded.append(p)

    def _pick_tool(self, tool: str) -> None:
        self.tool = tool


class FakeBtn:
    def __init__(self) -> None:
        self.checked = False

    def setChecked(self, v: bool) -> None:
        self.checked = v


class FakeItem:
    def __init__(self, name: str, src: str) -> None:
        self.source_name = name
        self.source_path = src


class FakeTab:
    pass


class FakeTabs:
    def __init__(self, current: object) -> None:
        self._current = current

    def currentWidget(self) -> object:
        return self._current


class FakeWindow:
    def __init__(self, editor: FakeEditor, src_path: str = "") -> None:
        self._editor = editor
        self._src_path = src_path
        self.saves: list[str] = []
        self.warnings: list[str] = []
        self.edit_tab = FakeTab()
        self.preview_tabs = FakeTabs(self.edit_tab)
        self._unified_editor_instance = editor

    @property
    def unified_editor(self) -> FakeEditor:
        return self._editor

    def _individual_editable_item(self) -> FakeItem | None:
        if not self._src_path:
            return None
        return FakeItem("IMG.jpg", self._src_path)

    def _save_unified_edit_as_draft(self, silent: bool = False) -> str:
        self.saves.append("saved")
        return "draft.png"

    def _show_selected_preview(self) -> None:
        pass


def test_data_guard_blocks_mismatch():
    print("\n[1] حرس فساد البيانات يمنع الحفظ عند عدم التطابق")
    with tempfile.TemporaryDirectory() as d:
        pasta = Path(d) / "pasta.jpg"
        laban = Path(d) / "laban.jpg"
        pasta.write_bytes(b"p")
        laban.write_bytes(b"l")

        editor = FakeEditor(str(pasta))
        w = FakeWindow(editor, str(laban))

        rep = install_editor_sync(w)
        check(rep["data_guard"], "حرس البيانات رُكّب")

        result = w._save_unified_edit_as_draft(silent=True)
        check(result is None,
              "الحفظ أُلغي عند عدم التطابق (المحرر=pasta، الصف=laban)")
        check(not w.saves, "لم يُنفَّذ الحفظ الفعلي")


def test_data_guard_allows_match():
    print("\n[2] حرس البيانات يسمح الحفظ عند التطابق")
    with tempfile.TemporaryDirectory() as d:
        img = Path(d) / "IMG.jpg"
        img.write_bytes(b"x")

        editor = FakeEditor(str(img))
        w = FakeWindow(editor, str(img))

        install_editor_sync(w)
        result = w._save_unified_edit_as_draft(silent=True)
        check(result == "draft.png", "الحفظ نجح عند التطابق")
        check(len(w.saves) == 1, "الحفظ الفعلي نُفِّذ مرة واحدة")


def test_sync_on_row_change():
    print("\n[3] تحديث المحرر عند تغيير الصف في تبويب التحرير")
    with tempfile.TemporaryDirectory() as d:
        old_img = Path(d) / "old.jpg"
        new_img = Path(d) / "new.jpg"
        old_img.write_bytes(b"o")
        new_img.write_bytes(b"n")

        editor = FakeEditor(str(old_img))
        w = FakeWindow(editor, str(new_img))

        install_editor_sync(w)
        w._show_selected_preview()

        check(len(editor.loaded) == 1,
              "المحرر حُدِّث بالصورة الجديدة")
        check(editor._image_path == str(new_img),
              f"المسار الجديد: {Path(editor._image_path).name}")


def test_sync_skips_when_has_edits():
    print("\n[4] لا تحديث إذا كان المحرر يحمل تعديلات غير محفوظة")
    with tempfile.TemporaryDirectory() as d:
        old_img = Path(d) / "old.jpg"
        new_img = Path(d) / "new.jpg"
        old_img.write_bytes(b"o")
        new_img.write_bytes(b"n")

        editor = FakeEditor(str(old_img))
        editor._has_edits = True
        w = FakeWindow(editor, str(new_img))

        install_editor_sync(w)
        w._show_selected_preview()

        check(not editor.loaded,
              "المحرر لم يُحدَّث — التعديلات غير المحفوظة محمية")


def test_tool_indicator():
    print("\n[5] مؤشر الأدوات يُظهر الأداة النشطة")
    editor = FakeEditor()
    w = FakeWindow(editor)

    rep = install_editor_sync(w)
    check(rep["tool_indicator"], "مؤشر الأدوات رُكّب")

    editor._pick_tool("erase")
    check(editor.erase_btn.checked, "زر التبييض مُحدَّد")
    check(not editor.restore_btn.checked, "زر الاسترجاع غير مُحدَّد")

    editor._pick_tool("restore")
    check(editor.restore_btn.checked, "زر الاسترجاع مُحدَّد")
    check(not editor.erase_btn.checked, "زر التبييض غير مُحدَّد")


def main():
    print("=" * 64)
    print("اختبار تزامن المحرر وحرس فساد البيانات")
    print("=" * 64)
    test_data_guard_blocks_mismatch()
    test_data_guard_allows_match()
    test_sync_on_row_change()
    test_sync_skips_when_has_edits()
    test_tool_indicator()
    print("\n" + "=" * 64)
    if FAILS:
        print(f"إخفاقات: {len(FAILS)}")
        for f in FAILS:
            print(f"  · {f}")
        return 1
    print("كل الفحوص نجحت")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
