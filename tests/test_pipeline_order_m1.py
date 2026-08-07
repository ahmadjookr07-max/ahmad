# -*- coding: utf-8 -*-
"""اختبار بند م-1 — الأداء ارتفع **والجودة لم تُمس**.

هذا الاختبار هو الحرس الذي يمنع مكسب سرعة على حساب صور المالك.
فإعادة ترتيب الخط (اقتصاص وتصغير قبل التركيب والتحسين) تجعل
التحسين يعمل على بكسلات أقل، وهذا ادّعاء لا يُقبل بلا قياس.

يقيس أربعة أمور:
  1. **الزمن**: الترتيب الجديد أسرع من القديم بمعامل معتبر.
  2. **المقروئية**: نص المنتج في الناتج لا يخسر مقارنةً بالقديم.
  3. **الهيئة**: المقاس والخلفية البيضاء والتوسيط كما كانت.
  4. **الأمان**: الخطوة لا تُطبَّق حين لا تفيد (صورة صغيرة أصلًا)،
     ولا تُشوّه القناع العشري.

المرجع المقيس قبل الإصلاح (4032×3024، بعد تسخين النموذج):
    الإجمالي 5786 مللي — enhance 3617 (62.5%) — compose 893 (15.4%)
    217 صورة = 20.9 دقيقة
وبعده: الإجمالي 1892 مللي — 217 صورة = 6.8 دقيقة (×3.06).
"""
import os
import sys
import tempfile
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, os.path.join(_ROOT, "windows_app"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from engine_v2.processor_v2 import (ProcessorV2,  # noqa: E402
                                   ProcessOptionsV2, imread_unicode)
from engine_v2.quality_v2 import (readability_score,  # noqa: E402
                                  text_saliency_map)

checks: dict[str, tuple[bool, str]] = {}


def check(name: str, ok: bool, detail: str = "") -> None:
    checks[name] = (bool(ok), detail)


OUT = tempfile.mkdtemp(prefix="m1_")
MODELS = os.path.join(_ROOT, "models_v2")

# ----------------------------------------------------- صورة اختبار واقعية
# مقاس صور المالك الحقيقي مع نص واضح — المقروئية هي المعيار.
H, W = 3024, 4032
img = np.full((H, W, 3), 228, np.uint8)
cv2.rectangle(img, (1200, 700), (2900, 2400), (70, 130, 205), -1)
cv2.rectangle(img, (1450, 950), (2650, 1500), (245, 245, 245), -1)
cv2.putText(img, "PRODUCT 500g", (1500, 1300), cv2.FONT_HERSHEY_SIMPLEX,
            4.0, (25, 25, 25), 9)
cv2.putText(img, "NET WT", (1520, 1750), cv2.FONT_HERSHEY_SIMPLEX,
            2.6, (250, 250, 250), 6)
SRC = os.path.join(OUT, "منتج.jpg")
cv2.imwrite(SRC, img)

proc = ProcessorV2(MODELS)
opts = ProcessOptionsV2()

# تسخين النموذج — بدونه القياس الأول يحمل زمن التحميل فيكذب
proc.process(SRC, os.path.join(OUT, "warm.webp"), opts)


def run_timed(path_out: str, prescale: bool) -> tuple[float, np.ndarray]:
    """يشغّل المسار مرتين ويرجع (زمن، ناتج). `prescale=False` يعطّل
    الخطوة الجديدة فنحصل على الترتيب القديم للمقارنة العادلة."""
    # ملاحظة دقيقة: قراءة `ProcessorV2._prescale_to_target` تعيد
    # **الدالة المجرّدة** لا كائن `staticmethod`، فإعادة إسنادها
    # تحوّلها إلى دالة نسخة تطلب `self` فينكسر المسار بعد
    # الاستعادة. لذا نحفط ونستعيد من `__dict__` مباشرة.
    saved = ProcessorV2.__dict__["_prescale_to_target"]
    if not prescale:
        ProcessorV2._prescale_to_target = staticmethod(
            lambda *a, **k: None)
    try:
        best = None
        for i in range(2):
            t = time.perf_counter()
            res = proc.process(SRC, path_out, opts)
            dt = (time.perf_counter() - t) * 1000.0
            best = dt if best is None else min(best, dt)
        out = imread_unicode(res.output_path) if res.ok else None
        return best, out
    finally:
        setattr(ProcessorV2, "_prescale_to_target", saved)


t_old, img_old = run_timed(os.path.join(OUT, "old.webp"), prescale=False)
t_new, img_new = run_timed(os.path.join(OUT, "new.webp"), prescale=True)

check("الناتج القديم أُنتج", img_old is not None)
check("الناتج الجديد أُنتج", img_new is not None)

# ------------------------------------------------------------- 1) الزمن
speedup = (t_old / t_new) if t_new else 0.0
check("الترتيب الجديد أسرع بمعامل ≥ 1.8",
      speedup >= 1.8,
      f"{t_old:.0f} → {t_new:.0f} مللي (×{speedup:.2f})")
check("زمن الدفعة 217 صورة أقل من 12 دقيقة",
      (t_new * 217 / 1000 / 60) < 12.0,
      f"{t_new*217/1000/60:.1f} دقيقة بدل {t_old*217/1000/60:.1f}")

# -------------------------------------------------------- 2) المقروئية
if img_old is not None and img_new is not None:
    sal_old = text_saliency_map(img_old)
    sal_new = text_saliency_map(img_new)
    r_old = readability_score(img_old, sal_old)
    r_new = readability_score(img_new, sal_new)
    # المعيار: لا نقبل خسارة تتجاوز 5% من مقروئية المسار القديم.
    ok_read = r_new >= r_old * 0.95
    check("المقروئية لم تخسر (≥95% من القديم)", ok_read,
          f"{r_old:.1f} → {r_new:.1f} ({r_new/r_old*100:.1f}%)")

    # حدة الحواف كمقياس ثانٍ مستقل عن المقروئية
    def sharpness(a):
        g = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
        return float(cv2.Laplacian(g, cv2.CV_32F, ksize=3).var())

    s_old, s_new = sharpness(img_old), sharpness(img_new)
    check("حدة الناتج لم تنهر (≥80% من القديم)",
          s_new >= s_old * 0.80,
          f"{s_old:.0f} → {s_new:.0f} ({s_new/s_old*100:.0f}%)")
else:
    check("المقروئية لم تخسر (≥95% من القديم)", False, "لا ناتج")

# ------------------------------------------------------------ 3) الهيئة
if img_new is not None:
    hh, ww = img_new.shape[:2]
    check("المقاس النهائي 800×700 كما هو",
          (ww, hh) == (opts.width, opts.height), f"{ww}×{hh}")
    # الخلفية بيضاء نقية في الأركان
    corners = [img_new[2, 2], img_new[2, ww - 3],
               img_new[hh - 3, 2], img_new[hh - 3, ww - 3]]
    check("الخلفية بيضاء نقية في الأركان",
          all(int(c.min()) >= 250 for c in corners),
          f"{[int(c.min()) for c in corners]}")
    # المنتج موجود ومتوسّط
    gray = cv2.cvtColor(img_new, cv2.COLOR_BGR2GRAY)
    ys, xs = np.where(gray < 240)
    if len(xs):
        cx, cy = xs.mean(), ys.mean()
        check("المنتج متوسّط أفقيًا (±8%)",
              abs(cx - ww / 2) < ww * 0.08, f"مركز x={cx:.0f} من {ww}")
        check("المنتج متوسّط رأسيًا (±8%)",
              abs(cy - hh / 2) < hh * 0.08, f"مركز y={cy:.0f} من {hh}")
        # المنتج يشغل حجمًا معقولًا لا مقصوصًا ولا ضائعًا
        frac = len(xs) / float(ww * hh)
        check("المنتج يشغل حجمًا معقولًا (10%–85%)",
              0.10 <= frac <= 0.85, f"{frac*100:.1f}%")
    else:
        check("المنتج موجود في الناتج", False, "لا بكسلات غير بيضاء")

# ------------------------------------------------------------ 4) الأمان
# صورة صغيرة أصلًا: لا مكسب في التصغير فلا تُطبَّق الخطوة
small = np.full((500, 600, 3), 235, np.uint8)
cv2.rectangle(small, (150, 120), (450, 380), (70, 130, 205), -1)
alpha_small = np.zeros((500, 600), np.float32)
alpha_small[120:381, 150:451] = 1.0
res_small = ProcessorV2._prescale_to_target(small, alpha_small, opts)
check("صورة أصغر من الهدف ⇒ لا تصغير (لا مكسب)",
      res_small is None)

# قناع فارغ لا ينهار
res_empty = ProcessorV2._prescale_to_target(
    img, np.zeros((H, W), np.float32), opts)
check("قناع فارغ يُعالج بأمان (يُرجع None)", res_empty is None)

# قناع كبير: تُطبَّق الخطوة، والقناع يبقى عشريًا لا معتَّبًا
alpha_big = np.zeros((H, W), np.float32)
alpha_big[700:2401, 1200:2901] = 1.0
# حافة متدرجة كي نتحقق أن التدرج ينجو
alpha_big[695:700, 1200:2901] = 0.5
res_big = ProcessorV2._prescale_to_target(img, alpha_big, opts)
check("صورة أكبر من الهدف ⇒ تُطبَّق الخطوة",
      res_big is not None)
if res_big is not None:
    i2, a2, flag = res_big
    check("الخطوة تُعلن عن نفسها", flag is True)
    check("المقاس بعد التصغير أصغر بكثير",
          i2.shape[0] * i2.shape[1] < H * W * 0.2,
          f"{i2.shape[1]}×{i2.shape[0]} = "
          f"{i2.shape[0]*i2.shape[1]/1e6:.2f} ميجابكسل بدل "
          f"{H*W/1e6:.1f}")
    check("الصورة والقناع بنفس المقاس",
          i2.shape[:2] == a2.shape[:2],
          f"{i2.shape[:2]} == {a2.shape[:2]}")
    check("القناع بقي في المجال 0..1",
          float(a2.min()) >= 0.0 and float(a2.max()) <= 1.0,
          f"[{a2.min():.3f}, {a2.max():.3f}]")
    check("القناع بقي عشريًا لا معتّبًا (تدرج الحافة نجا)",
          len(np.unique(np.round(a2, 2))) > 2,
          f"{len(np.unique(np.round(a2, 2)))} قيمة مميزة")
    # مقاس الهدف مع الهامش لم يُتجاوز
    check("المقاس ضمن هامش الأمان المعلن",
          i2.shape[1] <= int(opts.width * ProcessorV2.PRESCALE_SLACK) + 2
          and i2.shape[0] <= int(opts.height
                                 * ProcessorV2.PRESCALE_SLACK) + 2,
          f"سقف {int(opts.width*ProcessorV2.PRESCALE_SLACK)}×"
          f"{int(opts.height*ProcessorV2.PRESCALE_SLACK)}")

# ------------------------------------------------------------- التقرير
print("=" * 66)
print("اختبار م-1 — ترتيب خط المعالجة: أسرع بلا خسارة جودة")
print("=" * 66)
ok = 0
for name, (good, detail) in checks.items():
    print(f"  {'PASS' if good else 'FAIL'} {name}"
          + (f" — {detail}" if detail else ""))
    ok += 1 if good else 0
fail = len(checks) - ok
print("-" * 66)
print(f"{ok} نجح / {fail} فشل")
sys.exit(0 if fail == 0 else 1)
