# -*- coding: utf-8 -*-
"""لقطات شاشة offscreen للتحقق البصري من واجهة v2.2:
1) شريط الربط المباشر مع أداة الميول اليدوية الجديدة
2) شريط الأدوات مع زر حقائق التغذية
3) نافذة مركز حقائق التغذية
"""
import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "windows_app"))

OUT = Path("/home/ubuntu/analysis/shots")
OUT.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import native_app  # noqa: E402

win = native_app.MainWindow()
win.resize(1600, 950)
win.show()
app.processEvents()

# 1) النافذة كاملة (صفحة النتائج تحتوي شريط الربط)
try:
    # الانتقال لصفحة النتائج إن وُجدت stacked pages
    if hasattr(win, "stack") and hasattr(win, "results_page"):
        win.stack.setCurrentWidget(win.results_page)
        app.processEvents()
except Exception:
    pass
win.grab().save(str(OUT / "main_window.png"))

# 2) شريط الربط المباشر مع أداة الميول
if hasattr(win, "manual_group"):
    win.manual_group.grab().save(str(OUT / "link_bar_tilt.png"))
    print("tilt widget exists:", hasattr(win, "manual_tilt_spin"))
    if hasattr(win, "manual_tilt_spin"):
        win.manual_tilt_spin.setValue(3.5)
        app.processEvents()
        win.manual_group.grab().save(str(OUT / "link_bar_tilt_set.png"))

# 3) زر حقائق التغذية في V2 (native_app_v2)
try:
    import native_app_v2
    names = [n for n in dir(win) if "nutrition" in n.lower()]
    print("nutrition attrs on window:", names)
except Exception as e:
    print("v2 import:", e)

for b_name in ("nutrition_center_button", "nutrition_button",
               "v2_nutrition_button"):
    b = getattr(win, b_name, None)
    if b is not None:
        print("nutrition button found:", b_name, "text:", b.text())

print("saved to", OUT)
