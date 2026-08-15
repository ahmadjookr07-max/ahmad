from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows_app"))

import native_app  # noqa: E402


class _Label:
    def __init__(self):
        self.value = ""

    def setText(self, value):
        self.value = value


class _Window:
    def __init__(self, base: Path, items, selected):
        self.base = base
        self.current_result = SimpleNamespace(items=items)
        self._selected = selected
        self._editor_drafts = {}
        self._manual_reference_source_name = ""
        self._editor_loaded_source_name = ""
        self._individual_edit_source_name = ""
        self.status_label = _Label()
        self.populated = False
        self.zip_refreshed = False

    def _selected_result_items(self):
        return self._selected

    def _result_path(self, raw):
        return self.base / raw

    def _capture_results_position(self):
        return None

    def _populate_results(self, restore_position=None):
        self.populated = True

    def _refresh_delivery_zip(self):
        self.zip_refreshed = True

    def _show_tap_hint(self, _text):
        pass


def _item(name: str, output: str):
    return SimpleNamespace(source_name=name, output_path=output, review_path=output)


def _delete(window):
    old_question = native_app.QMessageBox.question
    try:
        native_app.QMessageBox.question = lambda *a, **k: native_app.QMessageBox.Yes
        native_app.MainWindow._delete_selected_outputs(window)
    finally:
        native_app.QMessageBox.question = old_question


def test_shared_output_is_not_deleted():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        shared = base / "same.webp"
        shared.write_bytes(b"webp")
        draft = base / "draft.png"
        draft.write_bytes(b"draft")
        one, two = _item("one.jpg", "same.webp"), _item("two.jpg", "same.webp")
        win = _Window(base, [one, two], [one])
        win._editor_drafts["one.jpg"] = draft
        win._manual_reference_source_name = "one.jpg"
        _delete(win)
        assert shared.exists(), "لا يجوز حذف ملف ما زال صف آخر يستخدمه"
        assert win.current_result.items == [two]
        assert not draft.exists(), "يجب حذف مسودة الصف المحذوف"
        assert win._manual_reference_source_name == ""
        assert win.populated and win.zip_refreshed


def test_unshared_output_is_deleted():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        unique = base / "unique.webp"
        unique.write_bytes(b"webp")
        one = _item("one.jpg", "unique.webp")
        win = _Window(base, [one], [one])
        _delete(win)
        assert not unique.exists(), "يجب حذف الملف حين لا يشير إليه أي صف آخر"
        assert win.current_result.items == []


if __name__ == "__main__":
    test_shared_output_is_not_deleted()
    test_unshared_output_is_deleted()
    print("OK: item mutation v3.2")


def test_session_restore_clears_prior_state():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows_app"))
    import v31_patch

    class _SessionWindow:
        def __init__(self):
            self.current_result = "old-session"
            self._result_items_by_name = {"old": object()}
            self._manual_reference_source_name = "old"
            self._editor_drafts = {"old": Path("draft")}
            self.seen_before_restore = ""

        def v2_restore_session(self, _session_id):
            self.seen_before_restore = self.current_result
            self.current_result = "new-session"

    window = _SessionWindow()
    v31_patch._patch_session_reset(window)
    window.v2_restore_session("new")
    assert window.seen_before_restore is None
    assert window.current_result == "new-session"
    assert window._result_items_by_name == {}
    assert window._manual_reference_source_name == ""


if __name__ == "__main__":
    test_session_restore_clears_prior_state()
    print("OK: session reset v3.2")
