#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""حذف كتلة «نسخة التوافق 2.0.0» من installer.nsi بحفظ ترميز BOM.

## لماذا تُحذف

حتى 2.9.11 كان في نهاية `installer.nsi` سطر `!finalize` ينسخ المُثبِّت
نسخةً ثانية بالاسم الثابت `Setup-2.0.0.exe`، لأن ورشة GitHub كانت تبحث
عن ذلك الاسم حرفيًا وتفشل بـ«Installer missing» بدونه، وتصحيح الورشة
كان محجوبًا لغياب صلاحية `workflows`.

الورشتان صُحّحتا فعلًا في 2.9.12: كلتاهما تقرأ الرقم من `VERSION`
وتبحث عن الاسم المشتق منه. فلم يبقَ للنسخة الثانية من ينتظرها، ووجودها
ضرر محقّق لا نفع: ملف بحجم 300 م.ب يدّعي إصدارًا لا يطابق ما بداخله،
فإن وصل للمالك أو رُفع بالخطأ عادت المشكلة التي أُغلقت.

الملف بترميز UTF-8 مع BOM (شرط يحرسه `test_version_consistency`)،
لذا نقرأ ونكتب بـ`utf-8-sig` حتى لا نتلف الترميز ولا نُسقِط الـBOM.
"""
from __future__ import annotations

from pathlib import Path

NSI = Path(__file__).resolve().parent.parent / "build" / "windows" / "installer.nsi"

HEADER = "؛  توافق اسم المخرَج مع ورشة البناء"  # للبحث الاحتياطي
MARK_START = ";  توافق اسم المخرَج مع ورشة البناء"
NEW_BLOCK = """; ════════════════════════════════════════════════════════════════
;  اسم المخرَج: مصدر واحد بلا نسخة توافق
; ════════════════════════════════════════════════════════════════
;  حتّى 2.9.11 كان هنا سطر ‎!finalize‎ ينسخ المُثبِّت نسخةً ثانية
;  بالاسم الثابت ‎Setup-2.0.0.exe‎، لأن ورشة GitHub كانت تبحث عن ذلك
;  الاسم حرفيًا وتفشل بـ«‏Installer missing» بدونه، وتصحيح الورشة كان
;  محجوبًا لغياب صلاحية ‎workflows‎.
;
;  الورشتان صُحّحتا في 2.9.12: كلتاهما تقرأ الرقم من ملف VERSION وتبحث
;  عن الاسم المشتق منه. فلم يبقَ للنسخة الثانية من ينتظرها، ووجودها ضرر
;  محقّق لا نفع: ملف بحجم 300 م.ب يدّعي إصدارًا لا يطابق ما بداخله، فإن
;  وصل للمالك أو رُفع بالخطأ عادت المشكلة التي أُغلقت.
;
;  لا تُعد إضافة أي نسخة باسم ثابت: إن فشلت ورشة، فالإصلاح في الورشة
;  لا في مضاعفة المخرَجات.
"""


def main() -> int:
    text = NSI.read_text(encoding="utf-8-sig")
    idx = text.find(MARK_START)
    if idx < 0:
        print("لم تُوجد كتلة التوافق — الملف نظيف أصلًا.")
        return 0
    # نرجع إلى بداية سطر الخط المزخرف الذي يسبق العنوان
    lines = text.splitlines(keepends=True)
    start = None
    for i, ln in enumerate(lines):
        if MARK_START in ln:
            start = max(0, i - 1)  # سطر الـ ═ قبل العنوان
            break
    if start is None:
        print("تعذّر تحديد بداية الكتلة.")
        return 2
    end = None
    for j in range(start, len(lines)):
        if lines[j].strip() == "!endif":
            end = j + 1
            break
    if end is None:
        print("تعذّر تحديد نهاية الكتلة (!endif مفقود).")
        return 3

    new = "".join(lines[:start]) + NEW_BLOCK + "".join(lines[end:])
    NSI.write_text(new, encoding="utf-8-sig")
    print(f"حُذفت كتلة التوافق (الأسطر {start + 1}–{end}) وحُفظ الترميز مع BOM.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
