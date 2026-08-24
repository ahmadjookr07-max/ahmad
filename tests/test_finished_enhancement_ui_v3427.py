# -*- coding: utf-8 -*-
"""حارس واجهة v3.4.27: لوحة تحسين الصور المنجزة تعرض خيارات مستقلة ومحكومة."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "windows_app"), str(ROOT / "src")]
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QCheckBox, QVBoxLayout, QWidget
from pipeline_patch import _install_finished_tool

app = QApplication.instance() or QApplication(sys.argv)
FAILS: list[str] = []


def check(condition: bool, label: str) -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        FAILS.append(label)


class Window(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.results_action_bar = QWidget(self)
        QVBoxLayout(self.results_action_bar)


window = Window()
_install_finished_tool(window)
button = getattr(window, "_finished_tool_btn", None)
check(button is not None, "زر معالجة الصور المنجزة موجود")

seen: dict[str, bool] = {}
with tempfile.TemporaryDirectory(prefix="finished_ui_") as temp:
    def inspect_and_close() -> None:
        dialog = app.activeModalWidget()
        if dialog is None:
            seen["dialog"] = False
            return
        seen["dialog"] = True
        wanted = ["finishedSafeAll", "finishedPreserveTextBarcode",
                  "finishedUnderstandImageType", "finishedRepairEdges", "finishedRepairGaps",
                  "finishedRestoreTexture", "finishedAddShadow", "finishedEnhanceAppearance",
                  "previewFinishedEnhancement"]
        for name in wanted:
            widget = dialog.findChild(QWidget, name)
            seen[name] = widget is not None
        for name in wanted[:7]:
            widget = dialog.findChild(QCheckBox, name)
            seen[f"checked:{name}"] = bool(widget and widget.isChecked())
        # تغيير الحواف يخرج من نمط المعالجة الشاملة، مع بقاء الحماية مفعلة.
        edge = dialog.findChild(QCheckBox, "finishedRepairEdges")
        safe = dialog.findChild(QCheckBox, "finishedSafeAll")
        protect = dialog.findChild(QCheckBox, "finishedPreserveTextBarcode")
        if edge is not None:
            edge.setChecked(False)
        seen["custom_mode"] = bool(safe is not None and not safe.isChecked())
        seen["protection_remains"] = bool(protect is not None and protect.isChecked())
        dialog.reject()

    with patch("PySide6.QtWidgets.QFileDialog.getExistingDirectory", return_value=temp):
        QTimer.singleShot(20, inspect_and_close)
        button.click()

check(seen.get("dialog"), "نافذة الخيارات تفتح")
for name in ("finishedSafeAll", "finishedPreserveTextBarcode", "finishedUnderstandImageType",
             "finishedRepairEdges", "finishedRepairGaps", "finishedRestoreTexture", "finishedAddShadow",
             "finishedEnhanceAppearance", "previewFinishedEnhancement"):
    check(seen.get(name), f"خيار {name} ظاهر")
for name in ("finishedSafeAll", "finishedPreserveTextBarcode", "finishedUnderstandImageType",
             "finishedRepairEdges", "finishedRepairGaps", "finishedRestoreTexture", "finishedAddShadow"):
    check(seen.get(f"checked:{name}"), f"خيار {name} مفعّل افتراضيًا")
check(seen.get("custom_mode"), "إلغاء خيار فرعي يحول إلى نمط مخصص")
check(seen.get("protection_remains"), "الحماية تبقى مفعلة في النمط المخصص")

print("ALL:", "PASS" if not FAILS else "FAIL")
sys.exit(0 if not FAILS else 1)
