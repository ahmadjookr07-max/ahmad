#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تشخيص: من يأكل ارتفاع صفحة المحرر على 1366×768؟"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows_app"))
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)
from unified_editor import UnifiedEditorWidget

img = np.full((900, 1200, 3), 235, dtype=np.uint8)
tmp = Path("/tmp/_dbg_layout.png")
from PIL import Image
Image.fromarray(img).save(tmp)

for w, h in ((1366, 768), (1600, 900), (1920, 1080)):
    ed = UnifiedEditorWidget()
    ed.resize(w, h)
    ed.show()
    ed.load_image(str(tmp))
    ed.advanced_toggle_btn.setChecked(True)
    app.processEvents()
    ed.resize(w, h)
    app.processEvents()
    app.processEvents()
    print(f"\n=== {w}x{h} (side={getattr(ed, '_advanced_side', None)}) ===")
    root = ed._root_layout
    total = 0
    for i in range(root.count()):
        it = root.itemAt(i)
        wd = it.widget()
        if wd is None:
            print(f"  [{i}] (non-widget) h={it.geometry().height()}")
            continue
        print(f"  [{i}] {wd.objectName() or type(wd).__name__:<28} "
              f"h={wd.height():<5} vis={wd.isVisible()} "
              f"min={wd.minimumHeight()} max={wd.maximumHeight()}")
        if wd.isVisible():
            total += wd.height()
    print(f"  canvas h={ed.canvas.height()} ratio={ed.canvas.height()/max(1,ed.height())*100:.1f}%")
    print(f"  sum visible={total}  widget h={ed.height()}")
    ed.close()
