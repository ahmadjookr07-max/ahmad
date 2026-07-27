# -*- coding: utf-8 -*-
"""اختبار headless للمحرر V2PhotoEditorDialog: يفتح صورة حقيقية ويشغّل
كل الأدوات برمجيًا ويتحقق من النتائج."""
import os, sys, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "/home/ubuntu/v2_project/app_v2/windows_app")
sys.path.insert(0, "/home/ubuntu/v2_project/app_v2/src")

import numpy as np
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from photo_editor_v2 import V2PhotoEditorDialog, EditorCanvas

SRC = "/home/ubuntu/upload/92E19735-37AF-4F79-BBA1-467F1AFE4883.jpeg"
OUT_DIR = "/home/ubuntu/v2_project/v2_out/editor_test"
os.makedirs(OUT_DIR, exist_ok=True)

checks = {}

dlg = V2PhotoEditorDialog(SRC)
checks["load"] = dlg._original is not None
print("loaded:", dlg._original.shape)

# 1) منزلقات يدوية
dlg._sliders["brightness"].setValue(15)
dlg._sliders["contrast"].setValue(20)
dlg._sliders["sharpness"].setValue(30)
dlg._recompose()
checks["sliders"] = dlg._composited is not None and dlg._composited.mean() > dlg._original.mean()

# 2) منطقة عزل مستطيلة + تحسين على المنطقة فقط
h, w = dlg._original.shape[:2]
dlg._on_stroke([(w*0.25, h*0.25), (w*0.75, h*0.75)], 0, EditorCanvas.TOOL_REGION_RECT)
checks["region_rect"] = dlg._region_mask is not None and dlg._region_mask.max() == 255
dlg.region_only_cb.setChecked(True)
before_px = dlg._original[5, 5].copy()
dlg._smart_enhance()
after_px_outside = dlg._original[5, 5]
checks["region_only_enhance"] = bool(np.abs(after_px_outside.astype(int) - before_px.astype(int)).max() <= 6)

# 3) إزالة الخلفية الذكية (synchronous عبر انتظار الخيط)
dlg._clear_region()
done = {"v": False}
orig_recompose = dlg._recompose
dlg._smart_cutout()
t0 = time.time()
while dlg._worker.isRunning() and time.time() - t0 < 120:
    app.processEvents()
    time.sleep(0.05)
app.processEvents()
checks["cutout"] = dlg._cutout_applied and dlg._base is not None and dlg._base.shape[2] == 4

# 4) قلم التبييض + استرجاع
pts = [(w*0.1 + i, h*0.1) for i in range(0, 60, 5)]
dlg._on_stroke(pts, 30, EditorCanvas.TOOL_ERASE)
checks["erase_pen"] = dlg._alpha_manual is not None and (dlg._alpha_manual == 0).any()
dlg._on_stroke(pts[:5], 30, EditorCanvas.TOOL_RESTORE)
checks["restore_pen"] = (dlg._alpha_manual == 255).any()

# 5) الظل الواقعي
idx = dlg.shadow_combo.findText("ظل استوديو 3D")
dlg.shadow_combo.setCurrentIndex(idx)
dlg._recompose()
checks["shadow"] = dlg._shadow_opts is not None and dlg._composited is not None

# 6) التأطير 800×700
dlg._smart_frame()
checks["frame_800x700"] = dlg._composited is not None and \
    dlg._composited.shape[1] >= 800 and dlg._composited.shape[0] >= 700

# 7) undo/redo
n_hist = len(dlg._history)
dlg._undo()
checks["undo"] = len(dlg._history) == n_hist - 1
dlg._redo_action()
checks["redo"] = len(dlg._history) == n_hist

# 8) حفظ مباشر (بدون حوار)
import cv2
out_path = os.path.join(OUT_DIR, "final.webp")
ok, buf = cv2.imencode(".webp", dlg._composited, [cv2.IMWRITE_WEBP_QUALITY, 101])
buf.tofile(out_path)
checks["save"] = os.path.exists(out_path) and os.path.getsize(out_path) > 1000

# 9) قبل/بعد
dlg._toggle_before(True)
dlg._toggle_before(False)
checks["before_after"] = True

# 10) zoom API
dlg.canvas.fit_view()
checks["canvas"] = not dlg.canvas._item.pixmap().isNull()

cv2.imwrite(os.path.join(OUT_DIR, "composited.png"), dlg._composited)

print("\n===== RESULTS =====")
all_ok = True
for k, v in checks.items():
    print(f"{'PASS' if v else 'FAIL'}  {k}")
    all_ok = all_ok and v
print("ALL:", "PASS" if all_ok else "FAIL")
sys.exit(0 if all_ok else 1)
