from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows_app"))

from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
from per_image_unit_patch import _item_units, install_per_image_unit


class _Index:
    def units_for_code(self, code):
        assert code == "10000001"
        return ["حبه", "شدة", "كرتون", "ربطة"]


class _Window:
    def __init__(self):
        self.individual_editor_panel = QWidget()
        QVBoxLayout(self.individual_editor_panel)
        self.v2_catalog_index = _Index()
        self.item = SimpleNamespace(item_code="10000001", output_path="", source_name="front.jpg")
        self.current_result = None
        self.status_label = SimpleNamespace(setText=lambda _text: None)

    def _individual_editable_item(self):
        return self.item


def run() -> None:
    _app = QApplication.instance() or QApplication([])
    window = _Window()
    assert _item_units(window, window.item) == ["حبه", "شدة", "كرتون", "ربطة"]
    report = install_per_image_unit(window)
    assert report["installed"] is True, report
    combo = window._per_image_unit_combo
    values = [combo.itemData(i) for i in range(combo.count())]
    assert values == [None, "حبه", "شدة", "كرتون", "ربطة"], values
    combo.setCurrentIndex(4)
    assert window._per_image_unit_override == "ربطة"
    print("OK: item-specific Excel units are shown, including ربطة")


if __name__ == "__main__":
    run()
