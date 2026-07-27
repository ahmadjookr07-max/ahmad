"""Functional test: BulkRenameDialog Excel-matching on real legacy files."""
import os
import sys
import json

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "/home/ubuntu/v2_project/app_v2/src")
sys.path.insert(0, "/home/ubuntu/v2_project/app_v2/windows_app")

from PySide6.QtWidgets import QApplication

import v2_ui

EXCEL = "/home/ubuntu/v2_project/catalog.xlsx"
FOLDER = "/home/ubuntu/v2_project/old_results/processed"

app = QApplication.instance() or QApplication([])

dlg = v2_ui.BulkRenameDialog()
dlg.folder_edit.setText(FOLDER)
dlg.excel_edit.setText(EXCEL)
dlg._preview()

rows = dlg.table.rowCount()
print("rows:", rows)
statuses = {}
samples_bad, samples_ok = [], []
for i in range(rows):
    lab = dlg.table.item(i, 3).text() if dlg.table.item(i, 3) else ""
    statuses[lab.split(" —")[0]] = statuses.get(lab.split(" —")[0], 0) + 1
    if "مطابق ✓" in lab and len(samples_ok) < 3:
        samples_ok.append((dlg.table.item(i, 0).text(), dlg.table.item(i, 1).text(), lab))
    elif "مطابق ✓" not in lab and len(samples_bad) < 5:
        samples_bad.append((dlg.table.item(i, 0).text(), dlg.table.item(i, 1).text(), lab))

print("status counts:", json.dumps(statuses, ensure_ascii=False, indent=1))
print("OK samples:", samples_ok)
print("BAD samples:", samples_bad)
print("status bar:", dlg.status.text())
print("TEST DONE")
