# -*- coding: utf-8 -*-
"""اختبار بند م-8 — الفرشاة تُطبَّق حيث المؤشر لا بعيدًا عنه.

العلة: `EditorCanvas._add_point` يحوّل الماوس بـ`mapToScene`، والمشهد
يعرض `_composited`. لكن `_on_stroke` يستخدم النقاط **كأنها إحداثيات
`_original`**. والمعروض أكبر من الأصل في حالتين:
  1. هامش الظل: `copyMakeBorder(rgba, 0, pad, pad, pad, ...)` ⇒ إزاحة
     أفقية بمقدار `pad` = 6% من العرض.
  2. التدوير: `warpAffine` إلى إطار موسّع `(nw, nh)` مع إزاحة مركز.

المقيس قبل الإصلاح على صورة عرضها 1600:
  بلا ظل بلا ميل  → 0 انزياح  (لهذا لم يُلاحَظ أولًا)
  ظل مفعَّل        → 96 بكسل أفقيًا
  ميل 7°           → 134 أفقيًا و186 رأسيًا
  ظل + ميل         → 342 و290

هذا الاختبار لا يقيس أحجام الصور بل **موضع الضربة نفسه**: يرسم في
نقطة معلومة من المشهد ويتحقق أن مركز الأثر في القناع يقع في الموضع
المكافئ من الأصل بدقة بكسلات معدودة.
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
for _k in ("warning", "critical", "information", "question", "about"):
    setattr(QMessageBox, _k, staticmethod(lambda *a, **k: None))

from photo_editor_v2 import V2PhotoEditorDialog, EditorCanvas  # noqa: E402

checks: dict[str, tuple[bool, str]] = {}


def check(name: str, ok: bool, detail: str = "") -> None:
    checks[name] = (bool(ok), detail)


OUT = tempfile.mkdtemp(prefix="m8_")
SRC = os.path.join(OUT, "منتج.jpg")
H, W = 1200, 1600
_img = np.full((H, W, 3), 235, np.uint8)
cv2.rectangle(_img, (500, 250), (1100, 950), (70, 130, 205), -1)
cv2.imwrite(SRC, _img)


def make_dialog():
    d = V2PhotoEditorDialog(SRC)
    d.feather_slider.setValue(0)   # بلا تمويه كي يبقى الأثر حادًا
    return d


def stroke_center(dlg) -> tuple[float, float] | None:
    """مركز أثر الفرشاة في `_alpha_manual` (القيم غير المحايدة)."""
    am = dlg._alpha_manual
    if am is None:
        return None
    ys, xs = np.where(am != 127)
    if len(xs) == 0:
        return None
    return float(xs.mean()), float(ys.mean())


def paint_at_scene(dlg, sx: float, sy: float) -> None:
    """يحاكي ضربة فرشاة في نقطة من **فضاء المشهد** (كما يفعل الماوس)."""
    dlg._alpha_manual = None
    dlg.canvas.set_brush_size(30)
    dlg._on_stroke([(sx, sy)], 30, EditorCanvas.TOOL_ERASE)


def scene_size(dlg) -> tuple[int, int]:
    return dlg._composited.shape[1], dlg._composited.shape[0]


TOL = 8.0   # هامش تحمّل بالبكسل (نصف قطر الفرشاة يبرر بعض التذبذب)

# =============================================== 1) الحالة المرجعية
dlg = make_dialog()
dlg._recompose()
oh, ow = dlg._original.shape[:2]
cw, ch = scene_size(dlg)
check("بلا ظل بلا ميل: المعروض = الأصل", (cw, ch) == (ow, oh),
      f"{cw}×{ch} مقابل {ow}×{oh}")
check("بلا تحويل ⇒ لا مصفوفة (لا تكلفة)",
      dlg._scene_to_image is None)

TX, TY = 800.0, 600.0   # نقطة اختبار في وسط الصورة
paint_at_scene(dlg, TX, TY)
c = stroke_center(dlg)
check("بلا تحويل: الضربة في مكان المؤشر",
      c is not None and abs(c[0] - TX) <= TOL and abs(c[1] - TY) <= TOL,
      f"المركز {c} والهدف ({TX}, {TY})")

# =============================================== 2) الظل مفعَّل
dlg2 = make_dialog()
dlg2._base = cv2.cvtColor(dlg2._original, cv2.COLOR_BGR2BGRA)
dlg2._base[:, :, 3] = 255
dlg2._cutout_applied = True
from engine_v2.shadow_v2 import SHADOW_PRESETS, ShadowOptions  # noqa: E402
_name = list(SHADOW_PRESETS)[0]
_p = SHADOW_PRESETS[_name]
dlg2._shadow_opts = _p if isinstance(_p, ShadowOptions) else (
    ShadowOptions(**_p) if isinstance(_p, dict) else _p)
dlg2._recompose()

oh2, ow2 = dlg2._original.shape[:2]
cw2, ch2 = scene_size(dlg2)
pad = int(ow2 * 0.06)
check("الظل يوسّع المعروض فعلًا (العطل موجود)",
      cw2 > ow2, f"{cw2} > {ow2} بفارق {cw2 - ow2}")
check("الظل ⇒ سُجِّلت مصفوفة تحويل",
      dlg2._scene_to_image is not None)

# نقطة في المشهد تقابل (TX, TY) من الأصل بعد إضافة الهامش
paint_at_scene(dlg2, TX + pad, TY)
c2 = stroke_center(dlg2)
check("مع الظل: الضربة في مكان المؤشر لا منزاحة",
      c2 is not None and abs(c2[0] - TX) <= TOL and abs(c2[1] - TY) <= TOL,
      f"المركز {c2} والهدف ({TX}, {TY}) — الهامش {pad}")

# ونثبت أن العطل كان حقيقيًا: بلا تحويل كان الانزياح = pad
saved = dlg2._scene_to_image
dlg2._scene_to_image = None
paint_at_scene(dlg2, TX + pad, TY)
c2b = stroke_center(dlg2)
check("بلا التحويل كان الانزياح = هامش الظل",
      c2b is not None and abs((c2b[0] - TX) - pad) <= TOL,
      f"انزياح {None if c2b is None else c2b[0] - TX:.0f} = pad {pad}")
dlg2._scene_to_image = saved

# =============================================== 3) الميل وحده
dlg3 = make_dialog()
dlg3.rotate_slider.setValue(70)     # 7.0 درجة
dlg3._recompose()
oh3, ow3 = dlg3._original.shape[:2]
cw3, ch3 = scene_size(dlg3)
check("الميل يوسّع الإطار فعلًا", cw3 > ow3 and ch3 > oh3,
      f"{cw3}×{ch3} مقابل {ow3}×{oh3}")
check("الميل ⇒ سُجِّلت مصفوفة تحويل",
      dlg3._scene_to_image is not None)

# نحسب الموضع المتوقع في المشهد للنقطة (TX, TY) من الأصل، بالتحويل
# الأمامي نفسه الذي يستخدمه الكود، ثم نتحقق أن العكس يردّها.
angle = 7.0
M = cv2.getRotationMatrix2D((ow3 / 2, oh3 / 2), -angle, 1.0)
cos, sin = abs(M[0, 0]), abs(M[0, 1])
nw, nh = int(oh3 * sin + ow3 * cos), int(oh3 * cos + ow3 * sin)
M[0, 2] += nw / 2 - ow3 / 2
M[1, 2] += nh / 2 - oh3 / 2
sx3 = M[0, 0] * TX + M[0, 1] * TY + M[0, 2]
sy3 = M[1, 0] * TX + M[1, 1] * TY + M[1, 2]

paint_at_scene(dlg3, sx3, sy3)
c3 = stroke_center(dlg3)
check("مع الميل 7°: الضربة في مكان المؤشر",
      c3 is not None and abs(c3[0] - TX) <= TOL and abs(c3[1] - TY) <= TOL,
      f"المركز {c3} والهدف ({TX}, {TY})")

# =============================================== 4) الظل + الميل معًا
dlg4 = make_dialog()
dlg4._base = cv2.cvtColor(dlg4._original, cv2.COLOR_BGR2BGRA)
dlg4._base[:, :, 3] = 255
dlg4._cutout_applied = True
dlg4._shadow_opts = dlg2._shadow_opts
dlg4.rotate_slider.setValue(70)
dlg4._recompose()
oh4, ow4 = dlg4._original.shape[:2]
cw4, ch4 = scene_size(dlg4)
check("الظل والميل معًا يوسّعان أكثر", cw4 > cw3,
      f"{cw4} > {cw3}")

# التحويل الأمامي: تدوير ثم إزاحة هامش أفقيًا
pad4 = int(cw3 * 0.06) if False else int(nw * 0.06)
sx4 = sx3 + pad4
sy4 = sy3
paint_at_scene(dlg4, sx4, sy4)
c4 = stroke_center(dlg4)
check("مع الظل والميل: الضربة في مكان المؤشر",
      c4 is not None and abs(c4[0] - TX) <= TOL and abs(c4[1] - TY) <= TOL,
      f"المركز {c4} والهدف ({TX}, {TY}) — الهامش {pad4}")

# =============================================== 5) نظافة الحالة
dlg5 = make_dialog()
dlg5.rotate_slider.setValue(70)
dlg5._recompose()
had = dlg5._scene_to_image is not None
dlg5._load_image(SRC)   # تحميل صورة جديدة
check("تحميل صورة جديدة يُصفّر التحويل",
      had and dlg5._scene_to_image is None)

dlg6 = make_dialog()
dlg6._base = cv2.cvtColor(dlg6._original, cv2.COLOR_BGR2BGRA)
dlg6._base[:, :, 3] = 255
dlg6._cutout_applied = True
dlg6.rotate_slider.setValue(70)
dlg6._recompose()
had6 = dlg6._scene_to_image is not None
dlg6._smart_frame()
check("التأطير يُصفّر التحويل (الميل اندمج في الأصل)",
      had6 and dlg6._scene_to_image is None)

# الاقتصاص للتحديد: المطلوب ليس التصفير بل **إعادة الحساب**.
# فالميل يبقى مفعّلًا بعد الاقتصاص (المنزلق لم يُلمَس)،
# و`_recompose` يعيد بناء التحويل على المقاس الجديد. والمعيار
# الحقيقي الوحيد: أن تقع الضربة في موضع المؤشر بعده.
dlg7 = make_dialog()
dlg7.rotate_slider.setValue(70)
dlg7._recompose()
dlg7._region_mask = np.zeros(dlg7._original.shape[:2], np.uint8)
dlg7._region_mask[300:800, 400:1000] = 255
dlg7._crop_to_region()

nh7, nw7 = dlg7._original.shape[:2]
M7 = cv2.getRotationMatrix2D((nw7 / 2, nh7 / 2), -7.0, 1.0)
_cos, _sin = abs(M7[0, 0]), abs(M7[0, 1])
_nw7, _nh7 = int(nh7 * _sin + nw7 * _cos), int(nh7 * _cos + nw7 * _sin)
M7[0, 2] += _nw7 / 2 - nw7 / 2
M7[1, 2] += _nh7 / 2 - nh7 / 2
TX7, TY7 = nw7 / 2.0, nh7 / 2.0
sx7 = M7[0, 0] * TX7 + M7[0, 1] * TY7 + M7[0, 2]
sy7 = M7[1, 0] * TX7 + M7[1, 1] * TY7 + M7[1, 2]
paint_at_scene(dlg7, sx7, sy7)
c7 = stroke_center(dlg7)
check("بعد الاقتصاص: التحويل أُعيد حسابه على المقاس الجديد",
      c7 is not None and abs(c7[0] - TX7) <= TOL
      and abs(c7[1] - TY7) <= TOL,
      f"المركز {c7} والهدف ({TX7:.0f}, {TY7:.0f}) على مقاس {nw7}×{nh7}")

# تحويل نقاط فارغ لا ينهار
check("قائمة نقاط فارغة تُعالج بأمان",
      dlg7._scene_points_to_image([]) == [])

# =============================================== التقرير
print("=" * 62)
print("اختبار م-8 — انزياح الفرشاة")
print("=" * 62)
ok = 0
for name, (good, detail) in checks.items():
    print(f"  {'PASS' if good else 'FAIL'} {name}"
          + (f" — {detail}" if detail else ""))
    ok += 1 if good else 0
fail = len(checks) - ok
print("-" * 62)
print(f"{ok} نجح / {fail} فشل")
sys.exit(0 if fail == 0 else 1)
