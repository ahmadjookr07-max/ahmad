# -*- coding: utf-8 -*-
"""يتحقق أن حاجز تناسق الإصدار **يكشف** العطب فعلًا، لا يمرّ دائمًا.

اختبار ينجح دائمًا لا قيمة له. فأزرع أعطابًا مماثلة للأعطاب الحقيقية
التي حدثت في المشروع، وأتأكد أن الحاجز يسقط عند كل واحد، ثم أستعيد
الحالة الأصلية.
"""
import shutil
import subprocess
import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST = Path(__file__).resolve().parent / "test_version_consistency.py"
BACKUP = Path(tempfile.mkdtemp(prefix="guard_backup_"))


def run_guard() -> int:
    r = subprocess.run([sys.executable, str(TEST)],
                       capture_output=True, text=True, cwd=str(ROOT))
    return r.returncode


CASES = [
    # (وصف، الملف، دالة التخريب)
    ("بيانات إصدار المالك متخلّفة (عطب 2.9.5 الحقيقي)",
     "build/windows/version_info_owner.txt",
     lambda s: s.replace("'2.9.9'", "'2.9.5'")),

    ("filevers الثنائي متخلّف بينما النص صحيح",
     "build/windows/version_info.txt",
     lambda s: s.replace("filevers=(2, 9, 9, 0)", "filevers=(2, 9, 8, 0)")),

    ("مثبت يثبّت الإصدار نصيًا (عطب النسخ الثماني)",
     "build/windows/installer.nsi",
     lambda s: s.replace(
         '!searchparse /file "${__FILEDIR__}\\..\\..\\VERSION" "" APP_VERSION "$\\n"',
         '!define APP_VERSION "2.0.0"')),

    ("ورشة تبني إصدارًا خاطئًا (عطب 2.0.0 الحقيقي)",
     ".github/workflows/build-windows.yml",
     lambda s: s.replace("name: Setup-User-${{ env.APP_VERSION }}",
                         "name: Setup-User-2.0.0")),

    ("بنية بيانات الإصدار معطوبة نحويًا",
     "build/windows/version_info.txt",
     lambda s: s.replace("StringFileInfo(", "StringFileInfo(((")),

    ("مفتاح ProductName محذوف",
     "build/windows/version_info_owner.txt",
     lambda s: s.replace(
         "            StringStruct('ProductName', "
         "'Ahmed Al-Faifi Owner Studio'),\n", "")),
]

# الاتفاقية ملف ثنائي (UTF-16LE) فيحتاج تخريبًا على مستوى البايت
EULA = "build/windows/EULA_ar.txt"


BIN_CASES = [
    ("الاتفاقية تعلن إصدارًا (عطب 2.9.5 الحقيقي)",
     lambda b: b.replace("(Market Image Studio)",
                         "(Market Image Studio) — الإصدار 2.9.5", 1)),
    ("نهايات الأسطر LF بدل CRLF",
     lambda b: b.replace("\r\n", "\n")),
]


def main() -> int:
    # نسخة احتياطية كاملة للملفات المعنية
    if BACKUP.exists():
        shutil.rmtree(BACKUP)
    BACKUP.mkdir(parents=True)
    files = {c[1] for c in CASES}
    for rel in files:
        dst = BACKUP / rel.replace("/", "__")
        shutil.copy2(ROOT / rel, dst)

    def restore():
        for rel in files:
            shutil.copy2(BACKUP / rel.replace("/", "__"), ROOT / rel)

    print("═" * 58)
    print("تحقق سلبي: هل يكشف الحاجز العطب فعلًا؟")
    print("═" * 58)

    base = run_guard()
    print(f"الحالة السليمة: rc={base} "
          f"{'✓ يمر' if base == 0 else '✗ يسقط وهو سليم!'}")
    if base != 0:
        restore()
        return 1

    failures = []
    for desc, rel, mutate in CASES:
        path = ROOT / rel
        orig = path.read_text(encoding="utf-8")
        new = mutate(orig)
        if new == orig:
            print(f"  ⚠ لم يُطبَّق التخريب: {desc}")
            failures.append(desc)
            continue
        path.write_text(new, encoding="utf-8")
        rc = run_guard()
        restore()
        if rc != 0:
            print(f"  ✓ كُشف: {desc}")
        else:
            print(f"  ✗ لم يُكشف: {desc}")
            failures.append(desc)

    # ── حالات الاتفاقية (ملف ثنائي UTF-16LE) ──
    eula_path = ROOT / EULA
    eula_bak = BACKUP / EULA.replace("/", "__")
    shutil.copy2(eula_path, eula_bak)
    for desc, mutate in BIN_CASES:
        orig = eula_path.read_bytes()
        body = orig[2:].decode("utf-16-le")
        new_body = mutate(body)
        if new_body == body:
            print(f"  ⚠ لم يُطبّق التخريب: {desc}")
            failures.append(desc)
            continue
        eula_path.write_bytes(b"\xff\xfe" + new_body.encode("utf-16-le"))
        rc = run_guard()
        shutil.copy2(eula_bak, eula_path)
        if rc != 0:
            print(f"  ✓ كُشف: {desc}")
        else:
            print(f"  ✗ لم يُكشف: {desc}")
            failures.append(desc)

    # تأكيد الاستعادة
    final = run_guard()
    print(f"\nبعد الاستعادة: rc={final} "
          f"{'✓ سليم' if final == 0 else '✗ بقي خراب!'}")

    print("═" * 58)
    if failures or final != 0:
        print(f"إخفاقات: {len(failures)}")
        for f in failures:
            print(f"  - {f}")
        return 1
    total = len(CASES) + len(BIN_CASES)
    print(f"الحاجز يكشف {total}/{total} من الأعطاب — فعّال")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
