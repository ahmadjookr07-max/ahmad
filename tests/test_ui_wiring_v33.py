from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows_app"))
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication
import native_app
import native_app_v2


def run() -> None:
    app = QApplication.instance() or QApplication([])
    native_app_v2._patch_ui(native_app)
    window = native_app.MainWindow()
    try:
        assert getattr(window, "_per_image_unit_v33", False)
        assert window._per_image_unit_widget.parent() is window.individual_editor_panel
        assert callable(getattr(window, "_save_nutrition_result", None))
        print("OK: unit and nutrition patches are mounted in the real MainWindow")
    finally:
        window.close()
        app.processEvents()


if __name__ == "__main__":
    run()
