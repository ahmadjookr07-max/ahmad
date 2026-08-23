from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MIS_SKIP_LICENSE", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "windows_app"), str(ROOT / "src")]
from PySide6.QtWidgets import QApplication
from native_app import MainWindow


def run() -> None:
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as td:
        window = MainWindow()
        window.v2_data_root = Path(td)
        combo = window.reference_mode_combo
        assert combo.itemData(0) == "item_code"
        assert combo.itemData(1) == "barcode"
        assert "وحدة Excel" in combo.itemText(0)
        assert "باركود خطي مثبت" in combo.itemText(1)
        assert "مجلد منجز" in window.reference_mode_hint.text()
        assert window.barcode_review_help.objectName() == "barcodeReviewHelp"
        assert "barcode_review_multiple_candidates.csv" in window.barcode_review_help.text()
        assert "لا يُختار باركود عشوائي" in window.barcode_review_help.text()
        combo.setCurrentIndex(1)
        app.processEvents()
        assert "باركود_Excel_غير_مثبت" in window.naming_preview_label.text()
        path = window._naming_settings_path()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["reference_mode"] == "barcode"
        window._load_reference_mode_state()
        assert combo.currentData() == "barcode"
        combo.setCurrentIndex(0)
        app.processEvents()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["reference_mode"] == "item_code"
        assert "رقم الصنف + الوحدة" in window.naming_preview_label.text()
        window.close()
    print("OK: reference mode is visible before processing and persists safely")


if __name__ == "__main__":
    run()
