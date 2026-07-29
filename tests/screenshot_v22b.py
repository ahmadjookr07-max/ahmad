# -*- coding: utf-8 -*-
"""لقطات عبر مسار V2 الكامل: شريط أدوات V2 مع زر حقائق التغذية،
وشريط الربط مع أداة الميول بعرض كامل."""
import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "windows_app"))

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import native_app  # noqa: E402
import native_app_v2  # noqa: E402

# تفعيل ترقيع V2 على MainWindow
native_app_v2._patch_ui(native_app)

OUT = Path("/home/ubuntu/analysis/shots")
OUT.mkdir(parents=True, exist_ok=True)

win = native_app.MainWindow()
win.resize(1720, 980)
win.show()
app.processEvents()

win.grab().save(str(OUT / "v2_main_window.png"))

# شريط أدوات V2
toolbar = win.findChild(object, "v2Toolbar")
if toolbar is not None:
    toolbar.grab().save(str(OUT / "v2_toolbar.png"))
    print("toolbar buttons:",
          [b.text() for b in toolbar.findChildren(
              __import__("PySide6.QtWidgets", fromlist=["QPushButton"]
                         ).QPushButton)])

# شريط الربط مع الميول بعرض كامل
if hasattr(win, "manual_group"):
    win.manual_group.setMinimumWidth(1400)
    app.processEvents()
    if hasattr(win, "manual_tilt_spin"):
        win.manual_tilt_spin.setValue(2.5)
        app.processEvents()
    win.manual_group.grab().save(str(OUT / "v2_link_bar.png"))

print("done")
