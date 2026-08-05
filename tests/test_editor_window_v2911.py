#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""2.9.11 — نافذة التحرير المستقلة: مساحة الصورة + زوم/تحريك صريح.

شكوى المالك حرفيًا: «التحرير محشور في زاوية والصورة تأخذ 35% فقط،
أريد نافذة مستقلة بحجم كامل مع تكبير وتحريك سهل».

يتحقق من:
1. `zoom_step` / `zoom_actual` موجودتان وتعملان فعلًا وتحترمان الحدود.
2. أزرار الزوم الثلاثة (－ / 1:1 / ＋) موجودة في الشريط وموصولة.
3. اختصارات Ctrl+= / Ctrl+- / Ctrl+0 مثبتة بنطاق آمن (لا تختلس التطبيق).
4. اللوحة المتقدمة تنتقل جانبيًا على الشاشات العريضة القصيرة وتعود،
   دون فقد قيمة أي منزلقة.
5. **الأهم**: نسبة ارتفاع الصورة ≥ 55% على 1366×768 و1920×1080
   مع فتح الأدوات المتقدمة — وهي عين ما اشتكى منه المالك.
6. `_open_individual_editor` يفتح النافذة المستقلة افتراضيًا.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MIS_SKIP_LICENSE", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows_app"))
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}" + (f" — {extra}" if extra else ""))
    else:
        FAIL += 1
        print(f"  FAIL {name}" + (f" — {extra}" if extra else ""))


app = QApplication.instance() or QApplication(sys.argv)

from unified_editor import UnifiedEditorWidget  # noqa: E402

# صورة اختبار
img = np.full((900, 1200, 3), 235, dtype=np.uint8)
img[200:700, 300:900] = (40, 90, 200)
tmp = Path("/tmp/_editor_window_v2911.png")
try:
    import cv2

    cv2.imwrite(str(tmp), img)
except Exception:
    from PIL import Image

    Image.fromarray(img[:, :, ::-1]).save(tmp)


# ------------------------------------------------------------ [1] الزوم البرمجي
print("[1] الزوم البرمجي في الكانفس")

ed = UnifiedEditorWidget()
ed.resize(1300, 700)
ed.show()
app.processEvents()
ed.load_image(str(tmp))
app.processEvents()

canvas = ed.canvas
check("zoom_step موجودة", hasattr(canvas, "zoom_step"))
check("zoom_actual موجودة", hasattr(canvas, "zoom_actual"))

canvas.fit_view()
app.processEvents()
z_fit = canvas._zoom
canvas.zoom_step(1.25)
app.processEvents()
check("التكبير يرفع معامل الزوم", canvas._zoom > z_fit,
      f"{z_fit:.3f} -> {canvas._zoom:.3f}")

z_before = canvas._zoom
canvas.zoom_step(1 / 1.25)
app.processEvents()
check("التصغير يخفض معامل الزوم", canvas._zoom < z_before,
      f"{z_before:.3f} -> {canvas._zoom:.3f}")

canvas.zoom_actual()
app.processEvents()
check("1:1 يضبط الزوم على 1.0 بالضبط", abs(canvas._zoom - 1.0) < 1e-6,
      f"{canvas._zoom:.6f}")

# الحدود: تكبير متكرر لا يتجاوز السقف ولا ينهار
for _ in range(40):
    canvas.zoom_step(1.25)
app.processEvents()
check("سقف الزوم محترم", canvas._zoom <= canvas.ZOOM_MAX + 1e-6,
      f"{canvas._zoom:.3f} <= {canvas.ZOOM_MAX}")
for _ in range(80):
    canvas.zoom_step(1 / 1.25)
app.processEvents()
check("أرضية الزوم محترمة", canvas._zoom >= canvas.ZOOM_MIN - 1e-6,
      f"{canvas._zoom:.4f} >= {canvas.ZOOM_MIN}")

# بلا صورة: لا انهيار
empty = UnifiedEditorWidget()
try:
    empty.canvas.zoom_step(1.25)
    empty.canvas.zoom_actual()
    ok_empty = True
except Exception as exc:
    ok_empty = False
    print(f"    {exc}")
check("الزوم بلا صورة لا يُسقط الواجهة", ok_empty)

# ------------------------------------------------------------ [2] أزرار الشريط
print("\n[2] أزرار الزوم في الشريط")

for attr, label in (("zoom_in_btn", "＋"), ("zoom_out_btn", "－"),
                    ("zoom_reset_btn", "1:1")):
    btn = getattr(ed, attr, None)
    check(f"الزر {attr} موجود", btn is not None)
    if btn is not None:
        check(f"نص الزر {attr} صحيح", btn.text() == label, btn.text())
        check(f"للزر {attr} تلميح عربي", bool(btn.toolTip()), btn.toolTip())

# النقر الفعلي على الأزرار يغيّر الزوم
canvas.fit_view()
app.processEvents()
z0 = canvas._zoom
ed.zoom_in_btn.click()
app.processEvents()
check("نقر زر التكبير يعمل فعلًا", canvas._zoom > z0,
      f"{z0:.3f} -> {canvas._zoom:.3f}")
ed.zoom_reset_btn.click()
app.processEvents()
check("نقر زر 1:1 يعمل فعلًا", abs(canvas._zoom - 1.0) < 1e-6)
z1 = canvas._zoom
ed.zoom_out_btn.click()
app.processEvents()
check("نقر زر التصغير يعمل فعلًا", canvas._zoom < z1)

# ------------------------------------------------------------ [3] الاختصارات
print("\n[3] اختصارات الزوم")

from PySide6.QtGui import QKeySequence, QShortcut  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402

shortcuts = ed.findChildren(QShortcut)
keys = {s.key().toString() for s in shortcuts}
for want in ("Ctrl+=", "Ctrl+-", "Ctrl+0"):
    check(f"الاختصار {want} مثبت",
          any(QKeySequence(want).matches(s.key()) == QKeySequence.ExactMatch
              for s in shortcuts),
          str(sorted(keys)))
check("نطاق الاختصارات ليس على مستوى التطبيق (لا يختلس المفاتيح)",
      all(s.context() != Qt.ApplicationShortcut for s in shortcuts))

# ------------------------------------------------- [4] اللوحة المتقدمة جانبيًا
print("\n[4] اللوحة المتقدمة تنتقل جانبيًا وتعود")

ed.advanced_toggle_btn.setChecked(True)
app.processEvents()
ed.feather_slider.setValue(18)
app.processEvents()

ed.resize(1600, 760)          # عريض وقصير ⇒ جانبي
app.processEvents()
check("الوضع الجانبي تفعّل على شاشة عريضة قصيرة",
      bool(getattr(ed, "_advanced_side", False)))
check("قيمة المنزلقة لم تُفقد بالنقل", ed.feather_slider.value() == 18,
      str(ed.feather_slider.value()))
check("اللوحة ما زالت مرئية", ed.advanced_panel.isVisible())

ed.resize(900, 1100)          # ضيّق وطويل ⇒ أسفل
app.processEvents()
check("العودة للوضع السفلي على شاشة ضيقة طويلة",
      not bool(getattr(ed, "_advanced_side", False)))
check("قيمة المنزلقة سليمة بعد الرجوع", ed.feather_slider.value() == 18,
      str(ed.feather_slider.value()))

# تبديل متكرر لا يسرّب ولا يكسر
ok_cycles = True
for _ in range(3):
    ed.resize(1600, 760)
    app.processEvents()
    ed.resize(900, 1100)
    app.processEvents()
    if ed.feather_slider.value() != 18 or not ed.has_image():
        ok_cycles = False
        break
check("3 دورات تبديل موضع بلا كسر", ok_cycles)

# ------------------------------------------------- [5] نسبة ارتفاع الصورة
print("\n[5] نسبة ارتفاع الصورة (جوهر الشكوى)")

for w, h in ((1366, 768), (1920, 1080), (1600, 900)):
    probe = UnifiedEditorWidget()
    probe.resize(w, h)
    probe.show()
    probe.load_image(str(tmp))
    probe.advanced_toggle_btn.setChecked(True)   # أسوأ حالة: كل الأدوات مفتوحة
    app.processEvents()
    probe.resize(w, h)
    app.processEvents()
    app.processEvents()
    ratio = probe.canvas.height() / max(1, probe.height())
    check(f"الصورة ≥55% من الارتفاع على {w}×{h}", ratio >= 0.55,
          f"{ratio * 100:.1f}%")
    probe.close()
    probe.deleteLater()

# --------------------------------------- [6] النافذة المستقلة هي الافتراضي
print("\n[6] النافذة المستقلة افتراضيًا")

src = (ROOT / "windows_app" / "native_app.py").read_text(encoding="utf-8")
check("_prefers_standalone_editor معرفة", "_prefers_standalone_editor" in src)
check("فتح التحرير يستدعي النافذة الموسّعة",
      "if self._prefers_standalone_editor():\n            self._open_expanded_editor()" in src)
check("النافذة الموسّعة تفرض حدًا أدنى لارتفاع الصورة",
      "_expanded_canvas_floor" in src)
check("الحد الأدنى يُرفع عند العودة للتبويب",
      src.count("_expanded_canvas_floor") >= 3)

import native_app  # noqa: E402

MW = native_app.MainWindow
check("_prefers_standalone_editor موجودة في MainWindow",
      hasattr(MW, "_prefers_standalone_editor"))


class _Probe:
    pass


probe = _Probe()
probe._prefers_standalone_editor = MW._prefers_standalone_editor.__get__(probe)
check("القيمة الافتراضية = نافذة مستقلة", probe._prefers_standalone_editor())


class _BadSettings:
    def value(self, *a, **k):
        raise RuntimeError("إعدادات تالفة")


probe.settings = _BadSettings()
check("إعدادات تالفة لا تمنع التحرير (احتياط = نافذة مستقلة)",
      probe._prefers_standalone_editor())


class _OffSettings:
    def value(self, key, default=None):
        return "false"


probe.settings = _OffSettings()
check("من يعطّل الخيار يُحترم اختياره",
      probe._prefers_standalone_editor() is False)

print(f"\n===== {PASS} passed / {FAIL} failed =====")
if FAIL == 0:
    print("ALL_EDITOR_WINDOW_V2911_TESTS_OK")
sys.exit(1 if FAIL else 0)
