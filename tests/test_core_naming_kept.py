# -*- coding: utf-8 -*-
"""التحقق أن الخاصية الأساسية (تصحيح الأسماء من الإكسل) لم تُمس بعد الوضع الحر."""
import glob
import sys

sys.path.insert(0, "app_v2/src")

from engine_v2.batch_refine_v2 import BatchRefiner, RefineOptions  # noqa: E402

xls = glob.glob("/home/ubuntu/upload/*.xlsx")
assert xls, "لا يوجد ملف إكسل في upload"
print("excel:", xls[0])

opts = RefineOptions(recut=False, enhance=False, frame=False,
                     fix_names=True, excel_path=xls[0], workers=1)
ref = BatchRefiner("/home/ubuntu/v2_project/models_v2", opts)

cases = ["10018435_حبه", "10018435_2_حبه", "10018435_كرتون", "اسم عشوائي حر"]
for stem in cases:
    new, note = ref._fixed_name(stem)
    print(f"{stem} -> {new} | {note or 'بلا ملاحظة'}")

# الاسم القياسي يجب أن يبقى قياسيًا، والاسم الحر يبقى كما هو
new1, _ = ref._fixed_name("10018435_حبه")
assert new1.startswith("10018435"), new1
new_free, note_free = ref._fixed_name("اسم عشوائي حر")
assert new_free == "اسم عشوائي حر", new_free
print("CORE NAMING KEPT — OK")
