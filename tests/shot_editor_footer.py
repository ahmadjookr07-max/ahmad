"""لقطات لتذييل تبويب «تحرير مباشر» على الدقات التي كانت تفشل."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows_app"))
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

OUT = Path("/home/ubuntu/shots")
OUT.mkdir(exist_ok=True)
CASES = [(800, 600), (1024, 600), (1024, 700), (1280, 800)]


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    from native_app import MainWindow  # type: ignore

    for width, height in CASES:
        win = MainWindow()
        win.resize(width, height)
        win.show()
        QApplication.processEvents()
        win._show_results_page()
        for _ in range(4):
            QApplication.processEvents()
        win.preview_tabs.setCurrentWidget(win.edit_tab)
        for _ in range(6):
            QApplication.processEvents()
        win.grab().save(str(OUT / f"editor_{width}x{height}.png"))
        footer = win.editor_footer
        print(f"{width}×{height}: footer h={footer.height()} "
              f"hfw={footer.layout().heightForWidth(footer.width())}")
        for btn in (win.individual_apply_button, win.editor_nutrition_button,
                    win.individual_reset_button, win.individual_cancel_button):
            geo = btn.geometry()
            print(f"    {btn.text()[:18]:20s} x={geo.x():4d} y={geo.y():3d} "
                  f"w={geo.width():4d} h={geo.height():3d} vis={btn.isVisible()}")
        win.close()
        win.deleteLater()
        QApplication.processEvents()
    print(f"saved to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
