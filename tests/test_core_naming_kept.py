# -*- coding: utf-8 -*-
"""حارس الخاصية الأساسية: تصحيح الأسماء من الإكسل بعد «الوضع الحر».

كان هذا الملف معطوبًا بثلاثة مسارات لا تصلح لأي بيئة:
  1. ``sys.path.insert(0, "app_v2/src")`` — مسار **نسبي** لمجلد غير
     موجود، فيتعلق بدليل التشغيل.
  2. ``glob("/home/ubuntu/upload/*.xlsx")`` + ``assert`` — ينهار إن
     خلا المسار الثابت من إكسل.
  3. ``BatchRefiner("/home/ubuntu/v2_project/models_v2")`` — مسار من
     بيئة جلسة قديمة محذوفة.
النتيجة أن حارس **قاعدة الترقيم** — وهي جوهر عمل المالك — لم يكن
يُنفَّذ فعليًا. أُصلح الآن ليستنبط الجذر من موقع الملف ويأخذ الإكسل
من ``MIS_OWNER_DATA`` أو ``upload``، ووُسِّعت حالاته لتغطي القاعدة
كاملة: الصورة الرئيسية **بلا رقم**، والإضافية ``_2`` / ``_3``.
"""
import glob
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _extra in (_ROOT / "src", _ROOT / "windows_app"):
    if _extra.is_dir() and str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

from engine_v2.batch_refine_v2 import (  # noqa: E402
    BatchRefiner, RefineOptions)
from engine_v2.paths_v2 import models_dir  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name +
          (f" — {note}" if note else ""))


def find_catalog() -> str | None:
    """يبحث عن كتالوج إكسل في المواضع المعتادة بدل مسار ثابت واحد."""
    roots = []
    owner = os.environ.get("MIS_OWNER_DATA")
    if owner:
        roots.append(Path(owner))
    roots += [Path("/home/ubuntu/upload"), Path.home() / "upload"]
    for root in roots:
        if not root.is_dir():
            continue
        hits = sorted(glob.glob(str(root / "**" / "*.xlsx"), recursive=True))
        hits = [h for h in hits if not Path(h).name.startswith("~$")]
        if hits:
            return hits[0]
    return None


xls = find_catalog()
if xls is None:
    print("تخطٍّ: لا كتالوج إكسل متاح (MIS_OWNER_DATA أو upload)")
    sys.exit(0)

print("excel:", xls)

opts = RefineOptions(recut=False, enhance=False, frame=False,
                     fix_names=True, excel_path=xls, workers=1)
ref = BatchRefiner(str(models_dir()), opts)

# استعراض تشخيصي
cases = ["10018435_حبه", "10018435_2_حبه", "10018435_كرتون",
         "اسم عشوائي حر"]
for stem in cases:
    new, note = ref._fixed_name(stem)
    print(f"    {stem} -> {new} | {note or 'بلا ملاحظة'}")

# 1) الاسم القياسي يبقى قياسيًا (رقم الصنف في المقدمة)
new1, _ = ref._fixed_name("10018435_حبه")
check("قياسي يبقى قياسيًا", new1.startswith("10018435"), new1)

# 2) الاسم الحر لا يُمس — جوهر «الوضع الحر»
new_free, _ = ref._fixed_name("اسم عشوائي حر")
check("الاسم الحر لا يُمس", new_free == "اسم عشوائي حر", new_free)

# 3) قاعدة الترقيم: الرئيسية بلا رقم، والإضافية مرقّمة من -1.
#    هذه هي القاعدة التي حدّدها المالك صراحةً، ويجب ألّا تنكسر.
main_name, _ = ref._fixed_name("10018435_حبه")
check("الرئيسية بلا رقم", "_1_" not in main_name
      and not main_name.endswith("_1"), main_name)

# 2.9.10 — نمط الإرث `_2` (أي: الصورة الثانية في العدّ القديم
# الذي يشمل الرئيسية) هي أوّل إضافية في قاعدة المالك، فتصير `-1`.
# المهمّ أنّها **تبقى مميّزة عن الرئيسية** فلا تطمسها.
second, _ = ref._fixed_name("10018435_2_حبه")
check("الإضافية تحمل رقمًا يميّزها عن الرئيسية (-1)",
      second != main_name and second.endswith("-1"), second)

# 4) الاسم بلا وحدة لا يُفسد ولا يُسقط المعالج
try:
    bare, note_bare = ref._fixed_name("10018435")
    check("رقم صنف مجرّد يُعالج بأمان", isinstance(bare, str) and bare,
          f"{bare} | {note_bare or 'بلا ملاحظة'}")
except Exception as exc:
    check("رقم صنف مجرّد يُعالج بأمان", False,
          f"{type(exc).__name__}: {exc}")

print(f"\n===== {len(PASS)} passed / {len(FAIL)} failed =====")
if FAIL:
    print("FAILED:", FAIL)
sys.exit(0 if not FAIL else 1)
