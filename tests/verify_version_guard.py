# -*- coding: utf-8 -*-
"""يتحقق أن حاجز تناسق الإصدار **يكشف** العطب فعلًا، لا يمرّ دائمًا.

اختبار ينجح دائمًا لا قيمة له. فأزرع أعطابًا مماثلة للأعطاب الحقيقية
التي حدثت في المشروع، وأتأكد أن الحاجز يسقط عند كل واحد، ثم أستعيد
الحالة الأصلية.
"""
import re
import shutil
import subprocess
import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST = Path(__file__).resolve().parent / "test_version_consistency.py"
BACKUP = Path(tempfile.mkdtemp(prefix="guard_backup_"))

# ── الرقم الحالي يُقرأ من VERSION لا يُكتب نصًا ────────────────────
#
# كانت التخريبات مكتوبة بالأرقام حرفيًا ('2.9.9'، filevers=(2, 9, 9, 0))،
# فحين ارتفع الإصدار صارت `str.replace` لا تجد ما تبدله فتُعيد النص
# كما هو، فيطبع الحارس «لم يُطبَّق التخريب» ويُحسَب إخفاقًا. أي أن أداة
# التحقق من الحاجز كانت تتعطّل بمجرد رفع رقم الإصدار — وهو بالضبط
# العطب الذي وُضعت لحرسه (رقم مكتوب في أكثر من موضع).
#
# الحل: تُشتق كل التخريبات من ملف VERSION، فتبقى فعّالة لأي إصدار.
VER = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
_MAJ, _MIN, _PATCH = (int(x) for x in VER.split(".")[:3])
OLD_VER = f"{_MAJ}.{_MIN}.{max(0, _PATCH - 1)}"        # إصدار متخلّف واحد
FILEVERS_NOW = f"filevers=({_MAJ}, {_MIN}, {_PATCH}, 0)"
FILEVERS_OLD = f"filevers=({_MAJ}, {_MIN}, {max(0, _PATCH - 1)}, 0)"


def run_guard() -> int:
    r = subprocess.run([sys.executable, str(TEST)],
                       capture_output=True, text=True, cwd=str(ROOT))
    return r.returncode


CASES = [
    # (وصف، الملف، دالة التخريب)
    ("بيانات إصدار المالك متخلّفة (عطب 2.9.5 الحقيقي)",
     "build/windows/version_info_owner.txt",
     lambda s: s.replace(f"'{VER}'", f"'{OLD_VER}'")),

    ("filevers الثنائي متخلّف بينما النص صحيح",
     "build/windows/version_info.txt",
     lambda s: s.replace(FILEVERS_NOW, FILEVERS_OLD)),

    ("مثبت يثبّت الإصدار نصيًا (عطب النسخ الثماني)",
     "build/windows/installer.nsi",
     lambda s: s.replace(
         '!searchparse /file "..\\..\\VERSION" "" APP_VERSION "$\\n"',
         '!define APP_VERSION "2.0.0"')),

    # العطب الحقيقي المكتشف في 2.9.9: `__FILEDIR__` يجعل المسار
    # يتضاعف عند النداء بمسار نسبي من الجذر، فينجح البناء على
    # windows-latest وحده ويخفق محليًا وعلى أي عامِل لينكس.
    ("مسار VERSION بـ__FILEDIR__ (عطب توافق لينكس الحقيقي)",
     "build/windows/installer.nsi",
     lambda s: s.replace(
         '!searchparse /file "..\\..\\VERSION"',
         '!searchparse /file "${__FILEDIR__}\\..\\..\\VERSION"')),

    ("مسار VERSION بـ__FILEDIR__ في مثبت المالك",
     "build/windows/installer_owner.nsi",
     lambda s: s.replace(
         '!searchparse /file "..\\..\\VERSION"',
         '!searchparse /file "${__FILEDIR__}\\..\\..\\VERSION"')),

    # الورشة تقرأ الإصدار من VERSION إلى `steps.ver.outputs.version`؛
    # تجميده نصيًا هو عين عطب 2.0.0 الذي أنتج مخرجًا باسم خاطئ.
    ("ورشة ترفع مخرجًا بإصدار مجمّد (عطب 2.0.0 الحقيقي)",
     ".github/workflows/build-windows.yml",
     # 2.9.13 — معرّف الخطوة في الورشة المفعَّلة هو `ver` والمخرَج
     # `value`. كان هذا التخريب يقرأ `steps.version.outputs.value`
     # فلا يطابق شيئًا في الملف، فيُخرَج «لم يُطبَّق التخريب» ويُحسب
     # إخفاقًا — وهو عين عطب الحارس المكتوب بأرقام حرفية الذي
     # صُحّح في 2.9.12، لكن هنا في **اسم المعرّف** لا في الرقم.
     # الآن يُشتق النمط من الملف نفسه فلا يتخلّف عن أي إعادة تسمية.
     lambda s: re.sub(
         r"name: Setup-\$\{\{ steps\.[A-Za-z0-9_-]+\.outputs\.value \}\}",
         "name: Setup-2.0.0", s, count=1)),

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
