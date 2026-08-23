from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "windows_app"), str(ROOT / "src")]

from PySide6.QtWidgets import QApplication, QDialog
from engine_v2.session_v2 import SessionStore
from v2_ui import SessionDialog


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ✓ {message}")


def run() -> None:
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as td:
        store = SessionStore(td)
        first = store.new_session("جلسة أولى")
        store.save(force=True)
        second = store.new_session("جلسة ثانية")
        store.save(force=True)

        dialog = SessionDialog(store)
        check(dialog.table.rowCount() == 2, "تعرض القائمة الجلسات المحفوظة")
        check(not dialog.resume_btn.isEnabled(),
              "زر الفتح معطل قبل اختيار جلسة")
        check("لم تُحدَّد جلسة" in dialog.selection_label.text(),
              "تظهر رسالة تطلب تحديد جلسة بوضوح")

        dialog.table.setCurrentCell(0, 0)
        app.processEvents()
        expected = dialog._sessions[0]["session_id"]
        check(dialog.selected_session_id == expected,
              "اختيار الصف يثبت الجلسة المحددة صراحة")
        check(dialog.resume_btn.isEnabled(),
              "يتفعل زر فتح الجلسة بعد التحديد فقط")
        check("الجلسة المحددة الآن" in dialog.selection_label.text(),
              "يعرض الشريط اسم الجلسة المحددة قبل الفتح")
        dialog._resume()
        check(dialog.result() == QDialog.Accepted,
              "لا تُفتح الجلسة إلا عبر فعل فتح صريح")
        dialog.deleteLater()
    print("OK: session dialog makes selection explicit before opening")


if __name__ == "__main__":
    run()
