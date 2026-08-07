# -*- coding: utf-8 -*-
"""اختبار بند م-13 — تاريخ التراجع لا يقتل البرنامج.

العلة المقيسة في الكود القديم: ``_snapshot`` كان ينسخ أربع مصفوفات
كاملة في كل لقطة (``original``، ``base``، ``alpha``، ``region``). على
مقاس صور المالك 4032×3024 يعني ذلك 104.7 ميجا للقطة الواحدة،
و1569.8 ميجا للسقف 15، ثم 1883.7 ميجا مع ثلاث تراجعات لأن ``_redo``
كانت **بلا سقف إطلاقًا**. ورام المالك ست جيجا ⇒ ويندوز يقتل البرنامج
بلا رسالة في منتصف العمل.

هذا الاختبار يتحقق من ثلاثة أمور لا واحد:
  1. **الحجم**: التاريخ لا ينمو نموًا خطيًا مع المصفوفات الكاملة.
  2. **السقف**: ``_history`` و``_redo`` كلتاهما محدودتان.
  3. **الصحة**: التراجع والإعادة يستعيدان البكسلات الصحيحة فعلًا —
     فلا معنى لتوفير ذاكرة يُفسد سلامة العمل.
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "windows_app"))
sys.path.insert(0, os.path.join(_ROOT, "src"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

# حراسة ضد الحوارات المُودال في بيئة بلا شاشة
_DIALOGS = []


def _no_modal(kind):
    def _fn(*a, **kw):
        _DIALOGS.append((kind, [x for x in a if isinstance(x, str)]))
        return QMessageBox.StandardButton.Ok
    return _fn


for _k in ("warning", "critical", "information", "question", "about"):
    setattr(QMessageBox, _k, staticmethod(_no_modal(_k)))

from photo_editor_v2 import V2PhotoEditorDialog  # noqa: E402

checks: dict[str, tuple[bool, str]] = {}


def check(name: str, ok: bool, detail: str = "") -> None:
    checks[name] = (bool(ok), detail)


# ------------------------------------------------------------------ التهيئة
OUT = tempfile.mkdtemp(prefix="m13_")
SRC = os.path.join(OUT, "منتج.jpg")
# مقاس معتبر (لا 4032×3024 كي لا يُثقل الصندوق، لكنه كافٍ ليُظهر
# الفرق بوضوح: 2000×1500 = 3 ميجابكسل ⇒ 25.7 ميجا للقطة بالمنطق القديم)
H, W = 1500, 2000
_img = np.full((H, W, 3), 235, np.uint8)
cv2.rectangle(_img, (600, 300), (1400, 1200), (70, 130, 205), -1)
cv2.rectangle(_img, (720, 420), (1280, 700), (245, 245, 245), -1)
cv2.imwrite(SRC, _img)

dlg = V2PhotoEditorDialog(SRC)
check("تحميل الصورة", dlg._original is not None,
      f"{None if dlg._original is None else dlg._original.shape}")

per_snapshot_old = 0
if dlg._original is not None:
    # المنطق القديم كان ينسخ: original(BGR) + base(BGRA) + alpha + region
    per_snapshot_old = (
        dlg._original.nbytes            # original
        + H * W * 4                     # base BGRA
        + H * W                          # alpha
        + H * W                          # region
    )

# ---------------------------------------------------- 1) الحجم لا ينفجر
# نحاكي ثلاثين ضربة فرشاة: كل ضربة تدفع لقطة ثم تعدّل القناع اليدوي.
dlg._alpha_manual = np.full((H, W), 127, np.uint8)
dlg._region_mask = np.zeros((H, W), np.uint8)

for i in range(30):
    dlg._push_history()
    y = 400 + (i * 20) % 600
    cv2.line(dlg._alpha_manual, (650, y), (1350, y), 255, 24)

has_metric = hasattr(dlg, "history_bytes")
check("دالة القياس history_bytes موجودة", has_metric)

actual = dlg.history_bytes() if has_metric else -1
old_equivalent = per_snapshot_old * len(dlg._history)

check("التاريخ محدود بالسقف",
      len(dlg._history) <= dlg._HISTORY_LIMIT,
      f"{len(dlg._history)} ≤ {dlg._HISTORY_LIMIT}")

# الشرط الجوهري: الحجم الفعلي أقل من 5% من المنطق القديم.
# المقيس عمليًا أقل من 1%، والسقف 5% هامش أمان لا هدف.
ratio = (actual / old_equivalent) if old_equivalent else 1.0
check("حجم التاريخ أقل من 5% من القديم",
      actual >= 0 and ratio < 0.05,
      f"{actual/1e6:.3f} ميجا مقابل {old_equivalent/1e6:.1f} ميجا "
      f"({ratio*100:.3f}%)")

# سقف مطلق: لا يتجاوز التاريخ 30 ميجا مهما فعل المستخدم
check("التاريخ تحت 30 ميجا مطلقًا", 0 <= actual < 30e6,
      f"{actual/1e6:.3f} ميجا")

# ------------------------------------------- 2) `_redo` محدودة هي أيضًا
for _ in range(40):
    dlg._undo()

check("قائمة الإعادة محدودة بالسقف",
      len(dlg._redo) <= dlg._HISTORY_LIMIT,
      f"{len(dlg._redo)} ≤ {dlg._HISTORY_LIMIT}")

after_undo = dlg.history_bytes() if has_metric else -1
check("الحجم بعد التراجعات ما زال تحت 30 ميجا",
      0 <= after_undo < 30e6, f"{after_undo/1e6:.3f} ميجا")

check("التراجع على تاريخ فارغ لا ينهار", True)

# --------------------------------------------- 3) الصحة: البكسلات تنجو
dlg2 = V2PhotoEditorDialog(SRC)
dlg2._alpha_manual = np.full((H, W), 127, np.uint8)

state_a = dlg2._alpha_manual.copy()
dlg2._push_history()
cv2.rectangle(dlg2._alpha_manual, (700, 500), (900, 700), 255, -1)
state_b = dlg2._alpha_manual.copy()

check("الحالتان مختلفتان فعلًا قبل الاختبار",
      not np.array_equal(state_a, state_b))

dlg2._undo()
check("التراجع يستعيد القناع بدقة البكسل",
      np.array_equal(dlg2._alpha_manual, state_a))

dlg2._redo_action()
check("الإعادة تستعيد القناع بدقة البكسل",
      np.array_equal(dlg2._alpha_manual, state_b))

# الصورة الثابتة تنجو سليمة رغم أنها لا تُنسخ في اللقطة
check("الصورة الأصلية سليمة بعد التراجع والإعادة",
      dlg2._original is not None
      and dlg2._original.shape == (H, W, 3))

# القناع المسترجع قابل للكتابة (لا مرجع للقراءة فقط يُفشل الفرشاة)
writable = False
try:
    dlg2._alpha_manual[0, 0] = 200
    writable = True
except Exception:
    writable = False
check("القناع المسترجع قابل للكتابة", writable)

# الصورة الأصلية المسترجعة قابلة للكتابة أيضًا (مسارات تكتب في موضعها)
orig_writable = False
try:
    dlg2._original[0, 0, 0] = 111
    orig_writable = True
except Exception:
    orig_writable = False
check("الأصل المسترجع قابل للكتابة", orig_writable)

# ضغط/فك القناع دون خسارة
packed = dlg2._pack_mask(state_b)
unpacked = dlg2._unpack_mask(packed)
check("ضغط القناع بلا خسارة", np.array_equal(unpacked, state_b),
      f"مضغوط {len(packed[2])/1e3:.1f} كيلو من {state_b.nbytes/1e6:.1f} ميجا")
check("القناع الفارغ يُعالج بأمان",
      dlg2._pack_mask(None) is None and dlg2._unpack_mask(None) is None)

# ------------------------------------------------------------------ التقرير
print("=" * 62)
print("اختبار م-13 — تاريخ التراجع الخفيف")
print("=" * 62)
ok_count = 0
for name, (ok, detail) in checks.items():
    print(f"  {'PASS' if ok else 'FAIL'} {name}"
          + (f" — {detail}" if detail else ""))
    ok_count += 1 if ok else 0
fail = len(checks) - ok_count
print("-" * 62)
if per_snapshot_old:
    print(f"لقطة واحدة بالمنطق القديم: {per_snapshot_old/1e6:.1f} ميجا "
          f"(على 4032×3024 ≈ 104.7 ميجا)")
    print(f"التاريخ كله الآن: {actual/1e6:.3f} ميجا لـ"
          f"{len(dlg._history)} لقطة")
print(f"{ok_count} نجح / {fail} فشل")
sys.exit(0 if fail == 0 else 1)
