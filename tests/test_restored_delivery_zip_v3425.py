# -*- coding: utf-8 -*-
"""حارس v3.4.25: الجلسة القديمة بلا delivery_zip تُعيد إنشاء الحزمة بدل رفضها."""
from __future__ import annotations

import os
import sys
import tempfile
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "windows_app"), str(ROOT / "src")]

import cv2
import numpy as np
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

import native_app as na
from delivery_excel_report import REPORT_FILENAME

app = QApplication.instance() or QApplication(sys.argv)
FAILS: list[str] = []


def check(condition: bool, name: str) -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {name}")
    if not condition:
        FAILS.append(name)


with tempfile.TemporaryDirectory(prefix="restored_zip_") as td:
    workspace = Path(td)
    processed = workspace / "processed"
    processed.mkdir()
    output = processed / "100001_حبه.webp"
    image = np.full((40, 50, 3), 210, np.uint8)
    cv2.imwrite(str(output), image, [cv2.IMWRITE_WEBP_QUALITY, 101])

    window = na.MainWindow()
    old_item = na.BatchItemResult(
        source_path=str(workspace / "front.jpg"), source_name="front.jpg",
        status="manual", item_code="100001", product_name="قهوة اختبار",
        barcode="6281111111111", output_path="processed/100001_حبه.webp",
        match_source="manual_excel")
    # هذه هي الحالة التي كانت تظهر للمستخدم: صفوف منجزة موجودة لكن ZIP فارغ.
    window.current_result = na.BatchRunResult(
        workspace=str(workspace), database_path="", catalog_summary={}, items=[old_item],
        elapsed_ms=0.0, delivery_zip="", report_json="", report_csv="")
    window.current_workspace = workspace
    window.delivery_excel_report_check.setChecked(True)

    target = window._ensure_delivery_zip_target()
    check(target == workspace / "delivery.zip", "الجلسة القديمة تأخذ هدف ZIP افتراضيًا داخل مساحة العمل")
    check(str(getattr(window.current_result, "delivery_zip", "")) == str(target),
          "مسار الحزمة يُسجل مع نتيجة الجلسة المستعادة")

    window._refresh_delivery_zip(immediate=True)
    check(target is not None and target.is_file(), "تُبنى حزمة ZIP مباشرة من الصور الجاهزة القديمة")
    with zipfile.ZipFile(target) as archive:
        names = set(archive.namelist())
        check("processed/100001_حبه.webp" in names, "الصورة الجاهزة القديمة تدخل الحزمة")
        check(f"reports/{REPORT_FILENAME}" in names, "تقرير Excel يدخل الحزمة المعاد بناؤها")
        check(archive.testzip() is None, "الحزمة المعاد بناؤها سليمة")

    destination = workspace / "exported.zip"
    original_get_save = QFileDialog.getSaveFileName
    original_info = QMessageBox.information
    original_warn = QMessageBox.warning
    QFileDialog.getSaveFileName = staticmethod(lambda *args, **kwargs: (str(destination), "ZIP (*.zip)"))
    QMessageBox.information = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    QMessageBox.warning = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    try:
        window._save_delivery_zip()
    finally:
        QFileDialog.getSaveFileName = original_get_save
        QMessageBox.information = original_info
        QMessageBox.warning = original_warn
    check(destination.is_file(), "زر حفظ ZIP يصدّر الجلسة القديمة بلا رسالة الحزمة المفقودة")

    source = (ROOT / "windows_app" / "v2_ui.py").read_text(encoding="utf-8")
    check('delivery_zip=_delivery_zip' in source,
          "استعادة الجلسة تسجل هدف ZIP تلقائيًا")
    window.close()

print("ALL:", "PASS" if not FAILS else "FAIL")
sys.exit(0 if not FAILS else 1)
