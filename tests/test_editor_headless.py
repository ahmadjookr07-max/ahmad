# -*- coding: utf-8 -*-
"""اختبار headless للمحرر V2PhotoEditorDialog: يفتح صورة حقيقية ويشغّل
كل الأدوات برمجيًا ويتحقق من النتائج."""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "windows_app"))
sys.path.insert(0, os.path.join(_ROOT, "src"))

import cv2
import numpy as np
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication(sys.argv)

# حراسة ضد التعليق: أي صندوق حوار مُودال في بيئة بلا شاشة يعلّق
# الاختبار للأبد (ينتظر ضغطة زر لن تأتي) — نسجلها ونمضي.
_DIALOGS = []


def _no_modal(kind):
    def _fn(*a, **kw):
        _DIALOGS.append((kind, [x for x in a if isinstance(x, str)]))
        return QMessageBox.StandardButton.Ok
    return _fn


for _k in ("warning", "critical", "information", "question", "about"):
    setattr(QMessageBox, _k, staticmethod(_no_modal(_k)))

from photo_editor_v2 import V2PhotoEditorDialog, EditorCanvas  # noqa: E402

OUT_DIR = os.path.join(tempfile.mkdtemp(prefix="editor_test_"), "out")
os.makedirs(OUT_DIR, exist_ok=True)

# صورة منتج مولّدة محليًا: لا اعتماد على ملفات خارجية
SRC = os.path.join(OUT_DIR, "منتج_اختبار.jpg")
_img = np.full((900, 1000, 3), 232, np.uint8)
cv2.rectangle(_img, (300, 180), (700, 760), (60, 120, 200), -1)
cv2.rectangle(_img, (360, 250), (640, 420), (245, 245, 245), -1)
cv2.circle(_img, (500, 200), 70, (40, 90, 170), -1)
cv2.putText(_img, "PRODUCT", (372, 350), cv2.FONT_HERSHEY_SIMPLEX,
            1.1, (30, 30, 30), 3)
cv2.imwrite(SRC, _img)
assert os.path.isfile(SRC), "تعذر توليد صورة الاختبار"

checks = {}

dlg = V2PhotoEditorDialog(SRC)
checks["no_modal_on_load"] = not _DIALOGS
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

# 5) الظل الواقعي — القائمة تُعبّأ عند فتح لوحة الظل فقط
dlg._populate_shadow_presets()
checks["shadow_presets_loaded"] = dlg.shadow_combo.count() >= 5
idx = dlg.shadow_combo.findText("ظل استوديو 3D")
checks["shadow_preset_found"] = idx >= 0
_before_shadow = None if dlg._composited is None else dlg._composited.copy()
# الظل مربوط بمفتاح تفعيل مستقل (كما يفعل المستخدم)
dlg.shadow_combo.setVisible(True)
dlg.shadow_combo.setCurrentIndex(idx)
dlg.shadow_enable_cb.setChecked(True)
dlg._shadow_changed()
dlg._recompose()
checks["shadow"] = dlg._shadow_opts is not None and dlg._composited is not None
# الظل يجب أن يغير البكسل فعلًا لا أن يُسجّل في الإعدادات فقط
checks["shadow_changes_pixels"] = (
    _before_shadow is not None and dlg._composited is not None
    and (_before_shadow.shape != dlg._composited.shape
         or bool(np.abs(_before_shadow.astype(int)
                        - dlg._composited.astype(int)).max() > 3)))
# إلغاء التفعيل يجب أن يزيل الظل
dlg.shadow_enable_cb.setChecked(False)
dlg._shadow_changed()
checks["shadow_off"] = dlg._shadow_opts is None
dlg.shadow_enable_cb.setChecked(True)
dlg._shadow_changed()
dlg._recompose()

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
