from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows_app"))
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication, QGroupBox
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
        assert window._pipeline_patch_report["processor_patched"]
        shadow_toggle = window._auto_shadow_after_isolation_cb
        assert shadow_toggle.isChecked()
        enhancement_group = window.findChild(QGroupBox, "enhancementGroup")
        assert enhancement_group is not None and shadow_toggle.parent() is enhancement_group
        print("OK: unit, nutrition, and automatic-shadow patches are mounted in the real MainWindow")
    finally:
        window.close()
        app.processEvents()


if __name__ == "__main__":
    run()
