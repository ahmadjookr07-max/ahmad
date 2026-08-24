# -*- coding: utf-8 -*-
"""حارس v3.4.24: خيار تقرير Excel ظاهر وقابل للتعطيل في شريط التسليم."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "windows_app"), str(ROOT / "src")]

from PySide6.QtWidgets import QApplication, QCheckBox
import native_app as na

app = QApplication.instance() or QApplication(sys.argv)
FAILS: list[str] = []


def check(condition: bool, name: str) -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {name}")
    if not condition:
        FAILS.append(name)


with tempfile.TemporaryDirectory(prefix="delivery_excel_ui_") as td:
    window = na.MainWindow()
    option = window.findChild(QCheckBox, "deliveryExcelReport")
    check(option is not None, "خيار تقرير Excel موجود في واجهة النتائج")
    if option is not None:
        check(option.isChecked(), "إرفاق التقرير مفعّل افتراضيًا")
        check("رقم الصنف" in option.toolTip() and "الباركود" in option.toolTip(),
              "الخيار يشرح محتوى تقرير Excel بوضوح")

    result = na.BatchRunResult(
        workspace=td, database_path="", catalog_summary={}, items=[], elapsed_ms=0.0,
        delivery_zip=str(Path(td) / "delivery.zip"), report_json="", report_csv="")
    window.current_result = result
    window.current_workspace = Path(td)
    window._update_controls()
    if option is not None:
        check(option.isEnabled(), "الخيار يصبح متاحًا عند وجود نتائج قابلة للتسليم")
        option.blockSignals(True)
        option.setChecked(False)
        option.blockSignals(False)
        check(not option.isChecked(), "يمكن إيقاف إرفاق التقرير قبل الحفظ")

    window.close()

print("ALL:", "PASS" if not FAILS else "FAIL")
sys.exit(0 if not FAILS else 1)
