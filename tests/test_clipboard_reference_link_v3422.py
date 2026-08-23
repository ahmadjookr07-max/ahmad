from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MIS_SKIP_LICENSE", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "windows_app"), str(ROOT / "src")]

from PySide6.QtWidgets import QApplication, QLabel, QLineEdit
from native_app import MainWindow


class Stub:
    _is_high_confidence_reference = staticmethod(MainWindow._is_high_confidence_reference)

    def __init__(self, reference, target) -> None:
        self.reference = reference
        self.target = target
        self.current = reference
        self.manual_item_edit = QLineEdit()
        self.status_label = QLabel()
        self._clipboard_link_reference = {}
        self.started_with = ""
        self.started_target_key = ""

    def _selected_result_item(self):
        return self.current

    def _start_manual_link(self) -> None:
        self.started_with = self.manual_item_edit.text()
        self.started_target_key = self.target.source_path


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ✓ {message}")


def run() -> None:
    app = QApplication.instance() or QApplication([])
    reference = SimpleNamespace(
        source_path="/raw/back/barcode.jpg", source_name="barcode.jpg",
        item_code="10003188", barcode="9556296309736", status="matched",
        confidence=0.99, output_path="/out/10003188_شدة.webp",
    )
    target = SimpleNamespace(
        source_path="/raw/front/fruit-rings.jpg", source_name="fruit-rings.jpg",
        item_code="", barcode="", status="review", confidence=0.0,
        output_path="",
    )
    stub = Stub(reference, target)
    MainWindow._copy_selected_link_reference(stub, "barcode")
    check(QApplication.clipboard().text() == "9556296309736",
          "نسخ الباركود الخطي إلى حافظة النظام")
    check(stub._clipboard_link_reference["source_key"].endswith("barcode.jpg"),
          "مرجع الحافظة يحتفظ بهوية المصدر لا بالباركود وحده")
    check("output_path" not in stub._clipboard_link_reference,
          "الحافظة لا تحمل مسار مخرج يمكن أن يكتب فوق صورة شقيقة")
    stub.current = target
    MainWindow._paste_link_reference_and_start(stub)
    check(stub.started_with == "9556296309736",
          "لصق المرجع يمرر القيمة نفسها إلى مسار الربط المعتاد")
    check(stub.started_target_key == target.source_path,
          "اللصق يبدأ من صورة الواجهة المحددة لا من صورة الباركود المرجعية")
    app.processEvents()
    print("OK: clipboard linking preserves independent image identity")


if __name__ == "__main__":
    run()
