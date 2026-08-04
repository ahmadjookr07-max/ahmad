# -*- coding: utf-8 -*-
"""يولّد `version_info.txt` و`version_info_owner.txt` من ملف `VERSION`.

**لماذا هذا الملف موجود؟**

ملفات بيانات إصدار PyInstaller بيانات جامدة: يقرأها المُصرِّف حرفيًا ولا
تملك آلية تضمين تقرأ `VERSION`. فكان الرقم يُكتب فيها يدويًا، فتخلّف:

* في 2.9.8 كان `version_info.txt` يعلن 2.9.8 والتطبيق 2.9.9.
* وحين أُصلح ذاك، بقي `version_info_owner.txt` على **2.9.5** — أربعة
  إصدارات خلف الحقيقة — لأن أحدًا لم يفكّر في نسخة المالك.

النتيجة عمليًا: يُثبَّت البرنامج فتُظهر خصائص الملف على ويندوز إصدارًا
غير الذي يعلنه البرنامج، ويعجز الدعم عن تحديد نسخة العميل.

**الحل:** مصدر وحيد للإصدار هو `VERSION`، وهذان الملفان يُولَّدان منه.
يُشغَّل هذا المولّد في الورشة قبل PyInstaller. ويحرسه
`tests/test_version_consistency.py` فلو نُسي التوليد سقط الاختبار.

    python3 build/windows/توليد_بيانات_الإصدار.py            # توليد
    python3 build/windows/توليد_بيانات_الإصدار.py --تحقق     # فحص فقط
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WIN = ROOT / "build" / "windows"

# صيغة (n, n, n, 0) التي يطلبها PyInstaller مع الرقم النصي كما يظهر
# في خصائص الملف على ويندوز.
# يُكتب الملف بـUTF-8 **مع BOM**: PyInstaller ينفّذ هذا الملف كتعبير
# بايثون، وبلا BOM يقرأه ويندوز بترميز المحلية (cp1252/cp1256) فتتشوّه
# التعليقات العربية وقد يفسد التحليل فيسقط البناء. يحرسه
# `tests/test_installer_encoding.py`.
_TEMPLATE = """# UTF-8
# Generated automatically from the VERSION file. Do not edit by hand.
# مولَّد آليًا من ملف VERSION — لا تعدّله يدويًا.
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({t}),
    prodvers=({t}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '040904B0',
          [
            StringStruct('CompanyName', 'Ahmed Al-Faifi'),
            StringStruct('FileDescription', '{desc}'),
            StringStruct('FileVersion', '{v}'),
            StringStruct('InternalName', '{internal}'),
            StringStruct('LegalCopyright',
                         'Copyright (c) 2026 Ahmed Al-Faifi. \
All rights reserved.'),
            StringStruct('OriginalFilename', '{internal}.exe'),
            StringStruct('ProductName', '{product}'),
            StringStruct('ProductVersion', '{v}')
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""

# البرنامجان مختلفان: تطبيق العملاء، وبرنامج المالك السري.
TARGETS = {
    "version_info.txt": dict(
        desc="Ahmed Al-Faifi Market Image Studio",
        internal="AhmedAlFaifiMarketImageStudio",
        product="Ahmed Al-Faifi Market Image Studio",
    ),
    "version_info_owner.txt": dict(
        desc="Owner Studio - License Manager",
        internal="AhmedAlFaifiOwnerStudio",
        product="Ahmed Al-Faifi Owner Studio",
    ),
}


def read_version() -> str:
    """يقرأ الإصدار من `VERSION`؛ غيابه خطأ صريح لا افتراض صامت."""
    f = ROOT / "VERSION"
    if not f.is_file():
        raise SystemExit(f"ملف VERSION مفقود: {f}")
    ver = f.read_text(encoding="utf-8").strip()
    parts = ver.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise SystemExit(f"صيغة VERSION غير صالحة: {ver!r} (المتوقع x.y.z)")
    return ver


def render(ver: str, meta: dict) -> str:
    major, minor, patch = ver.split(".")
    tup = f"{major}, {minor}, {patch}, 0"
    return _TEMPLATE.format(t=tup, v=ver, **meta)


def main(argv: list[str]) -> int:
    check_only = "--تحقق" in argv or "--check" in argv
    ver = read_version()
    mismatched = []

    for name, meta in TARGETS.items():
        path = WIN / name
        want = render(ver, meta)
        # utf-8-sig في القراءة والكتابة: يجب أن يوجد BOM ويُقارَن
        # المحتوى بعده، وإلا اعتُبر ملف بلا BOM «مطابقًا» فبقي معطوبًا.
        raw = path.read_bytes() if path.is_file() else b""
        have = raw.decode("utf-8-sig") if raw else ""
        has_bom = raw.startswith(b"\xef\xbb\xbf")
        if have == want and has_bom:
            print(f"  ✓ {name} مطابق للإصدار {ver}")
            continue
        mismatched.append(name)
        if check_only:
            why = "لا يطابق" if have != want else "بلا BOM"
            print(f"  ✗ {name} {why} {ver}")
        else:
            path.write_text(want, encoding="utf-8-sig")
            print(f"  ✓ {name} وُلّد على {ver}")

    if check_only and mismatched:
        print(f"\nملفات غير مطابقة: {mismatched}")
        print("شغّل: python3 build/windows/توليد_بيانات_الإصدار.py")
        return 1
    print(f"\nبيانات الإصدار متسقة على {ver}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
