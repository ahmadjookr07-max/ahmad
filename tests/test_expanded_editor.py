#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبار النقطة 4 — صفحة التحرير الموسّعة + وحدة الترويسة من الإكسل.

يتحقق من:
1. زر «توسيع الصفحة» موجود في تذييل المحرّر وموصول.
2. فتح الصفحة الموسّعة ينقل نفس ودجت المحرّر (لا نسخة ثانية).
3. الحالة والتعديلات لا تُفقد عند التوسيع ثم الرجوع.
4. الأدوات المتقدمة تُفتح تلقائيًا في الصفحة الموسّعة وتعود لحالتها.
5. الإغلاق يعيد المحرّر والتذييل إلى التبويب في مكانهما.
6. `_units_label_for_code` يقرأ وحدات الإكسل المجموعة لا نصًا مثبتًا.
7. تكرار التوسيع/الرجوع عدة مرات لا يسرّب ولا يكسر الترتيب.
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
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton  # noqa: E402

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


# ------------------------------------------------------------------ [1] البناء
print("[1] بناء التبويب والزر")

from unified_editor import UnifiedEditorWidget  # noqa: E402


from PySide6.QtWidgets import QMainWindow, QVBoxLayout, QWidget  # noqa: E402


class _Harness(QMainWindow):
    """يعيد استخدام دوال MainWindow دون إقلاع التطبيق كاملاً."""

    def __init__(self) -> None:
        super().__init__()
        import native_app

        self.native_app = native_app
        self.editor = UnifiedEditorWidget()

        self.tab = QWidget()
        self.setCentralWidget(self.tab)
        self.layout = QVBoxLayout(self.tab)
        header = QLabel("header")
        self.layout.addWidget(header)
        self.layout.addWidget(self.editor, 1)
        self.footer = QLabel("footer")
        self.layout.addWidget(self.footer)

        self.unified_editor = self.editor
        self._editor_tab_layout = self.layout
        self._editor_tab_footer = self.footer
        self._expanded_editor_window = None
        self.editor_expand_button = QPushButton("⛶ توسيع الصفحة")
        self.individual_editor_product_label = QLabel("منتج تجريبي")
        self.individual_editor_meta_label = QLabel("رقم الصنف: 10001633")


MW = None
try:
    import native_app

    MW = native_app.MainWindow
except Exception as exc:  # pragma: no cover
    print(f"  تعذر استيراد MainWindow: {exc}")

check("استيراد native_app.MainWindow", MW is not None)

# نربط دوال MainWindow الحقيقية بالـharness — نختبر الكود الفعلي لا نسخة منه
for meth in ("_toggle_expanded_editor", "_open_expanded_editor",
             "_close_expanded_editor", "_units_label_for_code"):
    check(f"الدالة {meth} موجودة في MainWindow", hasattr(MW, meth))
    if hasattr(MW, meth):
        setattr(_Harness, meth, getattr(MW, meth))

h = _Harness()

# ---------------------------------------------------------- [2] فتح ثم إغلاق
print("\n[2] التوسيع ينقل نفس الودجت")

img = np.full((240, 320, 3), 210, dtype=np.uint8)
img[60:180, 80:240] = (40, 90, 200)
tmp = Path("/tmp/_expanded_editor_src.png")
try:
    import cv2

    cv2.imwrite(str(tmp), img)
except Exception:
    from PIL import Image

    Image.fromarray(img[:, :, ::-1]).save(tmp)

h.editor.load_image(str(tmp))
check("الصورة محمّلة قبل التوسيع", h.editor.has_image())

editor_id_before = id(h.editor)
h._toggle_expanded_editor()
app.processEvents()

win = h._expanded_editor_window
check("نافذة موسّعة أُنشئت", isinstance(win, QDialog))
check("المحرّر انتقل إلى النافذة الموسّعة",
      win is not None and h.editor.window() is win)
check("نفس كائن المحرّر (لا نسخة ثانية)", id(h.unified_editor) == editor_id_before)
check("التذييل انتقل أيضًا", h.footer.window() is win)
check("الأدوات المتقدمة فُتحت تلقائيًا",
      h.editor.advanced_toggle_btn.isChecked())
check("لافتة بديلة ظهرت في التبويب",
      getattr(h, "_expanded_placeholder", None) is not None)
check("نص الزر تحوّل للإرجاع", "إرجاع" in h.editor_expand_button.text())
check("الصورة لم تُفقد بالتوسيع", h.editor.has_image())

# ------------------------------------------------- [3] تعديل داخل الموسّعة
print("\n[3] التعديلات تنجو من الرجوع")

h.editor.rotate_slider.setValue(3)
app.processEvents()
had_edits = h.editor.has_edits()
check("تعديل مسجّل داخل الصفحة الموسّعة", had_edits)

h._toggle_expanded_editor()  # إغلاق
app.processEvents()

check("النافذة أُغلقت", h._expanded_editor_window is None)
check("المحرّر عاد إلى التبويب", h.editor.window() is not win)
check("التذييل عاد إلى التبويب",
      h.layout.indexOf(h.footer) == h.layout.count() - 1)
check("المحرّر في موضعه الأصلي (بعد الترويسة)",
      h.layout.indexOf(h.editor) == 1)
check("اللافتة أُزيلت", getattr(h, "_expanded_placeholder", None) is None)
check("الصورة باقية بعد الرجوع", h.editor.has_image())
check("التعديلات باقية بعد الرجوع", h.editor.has_edits() == had_edits)
check("الأدوات المتقدمة عادت لحالتها الأصلية",
      not h.editor.advanced_toggle_btn.isChecked())
check("نص الزر عاد للتوسيع", "توسيع" in h.editor_expand_button.text())

# ------------------------------------------------------- [4] تكرار العملية
print("\n[4] تكرار التوسيع/الرجوع 3 مرات")

ok_cycles = True
for i in range(3):
    h._toggle_expanded_editor()
    app.processEvents()
    if h._expanded_editor_window is None or not h.editor.has_image():
        ok_cycles = False
        break
    h._toggle_expanded_editor()
    app.processEvents()
    if (h._expanded_editor_window is not None
            or h.layout.indexOf(h.editor) != 1
            or h.layout.indexOf(h.footer) != h.layout.count() - 1
            or not h.editor.has_image()):
        ok_cycles = False
        break
check("3 دورات متتالية بلا كسر في الترتيب أو فقد الصورة", ok_cycles)
check("عدد عناصر التخطيط ثابت (لا تسريب)", h.layout.count() == 3,
      f"count={h.layout.count()}")

# ------------------------------------------- [5] وحدة الترويسة من الإكسل
print("\n[5] وحدة الترويسة تُقرأ من الإكسل لا نصًا مثبتًا")

src = (ROOT / "windows_app" / "native_app.py").read_text(encoding="utf-8")
check("النص المثبّت «حبة» أُزيل من ترويسة المحرّر",
      'unit = "حبة" if item.item_code else' not in src)
check("الترويسة تستدعي _units_label_for_code",
      "unit = self._units_label_for_code(item.item_code)" in src)


class _FakeIndex:
    def units_for_code(self, code: str):
        return {"10001633": ["حبه", "كرتون", "شدة"],
                "10008272": ["باكت", "حبه", "كرتون", "كرتون 1"]}.get(code, [])


h.v2_catalog_index = _FakeIndex()
check("وحدات مجموعة بالترتيب",
      h._units_label_for_code("10001633") == "حبه + كرتون + شدة",
      h._units_label_for_code("10001633"))
check("«كرتون 1» يُطبّع إلى «كرتون1»",
      "كرتون1" in h._units_label_for_code("10008272"),
      h._units_label_for_code("10008272"))
check("صنف غير موجود في الإكسل يُبلَّغ بوضوح",
      h._units_label_for_code("99999") == "غير موجودة في الإكسل")
check("بلا رقم صنف → غير محددة",
      h._units_label_for_code(None) == "غير محددة")
h.v2_catalog_index = None
check("بلا إكسل → رسالة واضحة لا انهيار",
      "الإكسل" in h._units_label_for_code("10001633"))


class _BrokenIndex:
    def units_for_code(self, code: str):
        raise RuntimeError("فهرس تالف")


h.v2_catalog_index = _BrokenIndex()
check("فهرس تالف لا يُسقط الواجهة",
      h._units_label_for_code("10001633") == "غير موجودة في الإكسل")

# --------------------------------------------------- [6] تكامل الكود العام
print("\n[6] تكامل الكود")

check("زر التوسيع مُعرَّف في التذييل", "self.editor_expand_button = QPushButton" in src)
check("الزر موصول بالدالة",
      "self.editor_expand_button.clicked.connect(self._toggle_expanded_editor)" in src)
check("الزر مضاف إلى تخطيط التذييل",
      src.count("self.editor_expand_button,") >= 2)
check("اختصار F11 مُفعّل", "Qt.Key_F11" in src)
check("إنهاء الجلسة يغلق النافذة الموسّعة",
      "لا تُترك النافذة الموسّعة معلقة" in src)
check("أنماط النافذة الموسّعة موجودة", "QDialog#expandedEditorWindow" in src)

print(f"\n===== {PASS} passed / {FAIL} failed =====")
if FAIL == 0:
    print("ALL_EXPANDED_EDITOR_TESTS_OK")
sys.exit(1 if FAIL else 0)
