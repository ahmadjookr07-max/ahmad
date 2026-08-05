#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""بناء حزمة الويندوز تحت Wine — يعطّل آلية العزل في PyInstaller.

## المشكلة التي يحلّها هذا السكربت

PyInstaller يشغّل بعض دوال الجمع (`collect_all` وكشف مجلدات الخُطّافات
ومعالجة عجلة PySide6) في **عملية بايثون فرعية معزولة**، ويتواصل معها
عبر أنبوبين (pipes) بمقابض ويندوز موروثة.

تحت Wine تتعثّر هذه الآلية: العملية الأمّ تنتظر سطرًا من الأنبوب إلى
الأبد، والعملية الفرعية لا تكتب شيئًا، فيقف البناء بلا أي استهلاك
للمعالج وبلا رسالة خطأ. قيست الحالة فعليًا: توقّف عشرين دقيقة عند
`collect_all("onnxruntime")` بينما `collect_all("dilithium_py")`
يمرّ في 3.7 ثانية — الفرق حجم البيانات المنقولة عبر الأنبوب.

## الحل

PyInstaller نفسه يوفّر مخرجًا: `isolated.Python` تقرأ العلم
`sys._pyi_isolated_subprocess` عند **إنشاء الكائن** (السطر 215 من
`isolated/_parent.py`)، وإذا كان صحيحًا صارت `__enter__` و`__exit__`
بلا عمل و`call()` تنفّذ الدالة في العملية نفسها مباشرة.

ذلك العلم موجود أصلًا ليمنع التعشيش (عزل داخل عزل)، ونحن نستعمله
لمنع العزل من أصله. النتيجة **مطابقة تمامًا**: نفس الدوال تُنفَّذ بنفس
الوسائط وتعيد نفس القيم — الفرق الوحيد أنها لا تمرّ بأنبوب.

لماذا هذا آمن هنا: العزل يفيد حين تكون بيئة البناء ملوَّثة بحزم
تتعارض عند الاستيراد المشترك. بيئتنا محمولة ونظيفة ومخصّصة لهذا
البناء وحده، فلا شيء يُعزَل عنه.

**حرج**: يجب ضبط العلم **قبل** أول استيراد لـPyInstaller، لأن بعض
الكائنات تُنشأ في زمن الاستيراد.

## الاستعمال
    wine python.exe tools/بناء_ويندوز_عبر_واين.py [--clean]
مجلد العمل يجب أن يكون جذر المشروع (ملف الـspec يقرأ `os.getcwd()`).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# ── العلم أولًا: قبل أي استيراد لـPyInstaller ────────────────────────
sys._pyi_isolated_subprocess = True

ROOT = Path(os.getcwd()).resolve()
SPEC = ROOT / "build" / "windows" / "AhmedAlFaifiMarketImageStudioV2.spec"
DIST = ROOT / "dist" / "windows"
WORK = ROOT / "build_tmp"


def main() -> int:
    if not SPEC.is_file():
        print(f"فشل: ملف الـspec غير موجود: {SPEC}", flush=True)
        return 2

    # التحقق من أن العلم فعّال فعلًا قبل المتابعة: لو تغيّر تنفيذ
    # PyInstaller في إصدار قادم فلن يقرأ العلم، وسيتجمّد البناء بلا
    # سبب ظاهر. نفشل هنا صراحةً بدل الوقوف ساعة بلا رسالة.
    from PyInstaller import isolated

    probe = isolated.Python()
    if not getattr(probe, "_already_isolated", False):
        print(
            "فشل: PyInstaller لم يقرأ علم تعطيل العزل.\n"
            "هذا الإصدار غيّر آلية العزل، والبناء تحت Wine سيتجمّد.\n"
            "راجع PyInstaller/isolated/_parent.py وابحث عن\n"
            "`_pyi_isolated_subprocess` وحدّث هذا السكربت.",
            flush=True,
        )
        return 3
    print("[بناء] العزل معطّل — الدوال تُنفَّذ في العملية نفسها", flush=True)

    argv = [
        str(SPEC),
        "--noconfirm",
        "--distpath", str(DIST),
        "--workpath", str(WORK),
        "--log-level", "INFO",
    ]
    if "--clean" in sys.argv:
        argv.append("--clean")

    from PyInstaller import __main__ as pyi_main

    print(f"[بناء] البدء: {' '.join(argv)}", flush=True)
    try:
        pyi_main.run(argv)
    except SystemExit as exc:  # PyInstaller يخرج بـSystemExit
        code = exc.code if isinstance(exc.code, int) else (0 if not exc.code else 1)
        print(f"[بناء] انتهى برمز {code}", flush=True)
        return code
    print("[بناء] انتهى بنجاح", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
