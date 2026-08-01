"""لقطات تحقق بصري لكل الشاشات — تُثبت أن المقياس التلقائي يضبط التنسيق.

تُنتج صورة PNG لكل (دقة × شاشة) بعد استقرار التخطيط، فتُقارن بصريًا مع
ما رصده المستخدم (تكدّس، قص من الأسفل، بتر كلمات).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "windows_app"))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

OUT = Path("/home/ubuntu/shots2")
OUT.mkdir(parents=True, exist_ok=True)

SIZES = [(800, 600), (1024, 600), (1024, 700), (1280, 800), (1366, 768),
         (1920, 1080)]


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    from test_responsive_audit import build_window, prepare_results_page

    for width, height in SIZES:
        win = build_window()
        win.resize(width, height)
        win.show()
        QApplication.processEvents()
        prepare_results_page(win)
        for _ in range(8):
            QApplication.processEvents()
        factor = getattr(win, "ui_scale", None)
        value = factor.factor if factor is not None else 1.0
        win.grab().save(str(OUT / f"review_{width}x{height}.png"))
        if hasattr(win, "preview_tabs") and hasattr(win, "edit_tab"):
            win.preview_tabs.setCurrentWidget(win.edit_tab)
            for _ in range(8):
                QApplication.processEvents()
            win.grab().save(str(OUT / f"editor_{width}x{height}.png"))
        print(f"{width}x{height} factor={value:.3f}")
        win.close()
        win.deleteLater()
        QApplication.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
