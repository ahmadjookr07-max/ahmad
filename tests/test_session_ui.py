# -*- coding: utf-8 -*-
"""Functional test: save a session from a populated window, restore in a new one."""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "windows_app"))
sys.path.insert(0, os.path.join(_ROOT, "src"))

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

# حراسة ضد التعليق: أي حوار مُودال في بيئة بلا شاشة ينتظر للأبد
for _k in ("warning", "critical", "information", "question", "about"):
    setattr(QMessageBox, _k,
            staticmethod(lambda *a, **kw: QMessageBox.StandardButton.Ok))

import native_app_v2  # noqa: E402
native_app_v2._activate_engine = lambda: None
import native_app  # noqa: E402
native_app_v2._patch_ui(native_app)

from pathlib import Path  # noqa: E402

tmp = Path(tempfile.mkdtemp())
app = QApplication([])

# window 1: fill results, save session
w1 = native_app.MainWindow()
w1.v2_session_store = __import__("engine_v2.session_v2", fromlist=["SessionStore"]).SessionStore(tmp)
# صورة مولّدة محليًا: لا اعتماد على ملفات خارجية
import cv2  # noqa: E402
import numpy as np  # noqa: E402

fixtures = []
for i in range(1, 6):
    fixture = str(tmp / f"fixture-{i}.png")
    _fx = np.full((300, 300, 3), 235, np.uint8)
    cv2.rectangle(_fx, (70, 60), (230, 250), (70, 130, 205), -1)
    cv2.putText(_fx, str(i), (130, 160), cv2.FONT_HERSHEY_SIMPLEX,
                1.2, (20, 20, 20), 3)
    cv2.imwrite(fixture, _fx)
    assert os.path.isfile(fixture), "تعذر توليد صورة الاختبار"
    fixtures.append(fixture)
items = [
    native_app.BatchItemResult(
        source_path=fixtures[i - 1], source_name=f"PHOTO-{i:03d}.jpg", status="review",
        item_code=f"{10000+i}", product_name=f"صنف تجريبي {i}",
        barcode=f"628100000{i:04d}", explanation="اختبار",
        review_path=fixtures[i - 1])
    for i in range(1, 6)
]
w1.current_result = native_app.BatchRunResult(
    workspace=str(tmp / "ws"), database_path="", catalog_summary={},
    items=items, elapsed_ms=0.0, delivery_zip="", report_json="", report_csv="")
w1._populate_results()
w1._show_results_page()
w1.results_table.setCurrentCell(3, 0)
sid = w1.v2_save_session()
print("saved session:", sid)
sessions = w1.v2_session_store.list_sessions()
print("sessions listed:", len(sessions), "total imgs:", sessions[0]["total"])

# window 2: restore
w2 = native_app.MainWindow()
w2.v2_session_store = __import__("engine_v2.session_v2", fromlist=["SessionStore"]).SessionStore(tmp)
state = w2.v2_session_store.load(sid)
w2.v2_restore_session(state)
print("row right after restore:", w2.results_table.currentRow())
app.processEvents()
print("row after processEvents:", w2.results_table.currentRow())
# let deferred QTimer.singleShot(0/120) re-selection run
from PySide6.QtCore import QEventLoop, QTimer
loop = QEventLoop()
QTimer.singleShot(300, loop.quit)
loop.exec()
print("row after timers:", w2.results_table.currentRow())
rows = w2.results_table.rowCount()
row = w2.results_table.currentRow()
from PySide6.QtCore import Qt as _Qt
print("visible:", w2._visible_result_rows())
print("userroles:", [w2.results_table.item(r,0).data(_Qt.UserRole) for r in range(rows)])
print("selmodel current:", w2.results_table.selectionModel().currentIndex().row())
code = w2.current_result.items[3].item_code if w2.current_result else "?"
print(f"restored rows={rows} current_row={row} item4_code={code}")
assert rows == 5, "rows mismatch"
assert row == 3, "position not restored"
assert code == "10004", "data mismatch"
print("SESSION SAVE/RESUME TEST PASSED")
