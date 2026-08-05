# -*- coding: utf-8 -*-
"""حاجز تناسق الإصدار — مصدر وحيد هو ملف `VERSION`.

**العطب الذي يحرسه هذا الملف** تكرّر مرتين في المشروع:

1. في 2.9.8 كان `version_info.txt` يعلن 2.9.8 بينما التطبيق 2.9.9.
2. وبعد إصلاح ذاك بقي `version_info_owner.txt` على **2.9.5** — أربعة
   إصدارات خلف الحقيقة — لأن أحدًا لم يتذكّر نسخة المالك.

وثالثًا: ثماني نسخ من مثبّت NSIS، كل واحدة تثبّت إصدارها نصيًا، فكانت
ورشة GitHub تبني مُثبِّت **2.0.0** لتطبيق 2.9.9 بلا أن يلاحظ أحد.

الجذر واحد: رقم الإصدار مكتوب في أماكن متعددة يدويًا. والحراسة هنا
طبقية — تفحص كل قناة يظهر فيها الإصدار للمستخدم أو للبناء.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIN = ROOT / "build" / "windows"

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def check(cond: bool, label: str, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {label} {extra}")
    else:
        FAIL += 1
        FAILURES.append(label)
        print(f"  ✗ {label} {extra}")


def head(title: str) -> None:
    print(f"── {title} ──")


def version() -> str:
    return (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def t_version_file() -> None:
    head("1) ملف VERSION هو المصدر الوحيد")
    f = ROOT / "VERSION"
    check(f.is_file(), "ملف VERSION موجود")
    if not f.is_file():
        return
    ver = version()
    check(bool(re.fullmatch(r"\d+\.\d+\.\d+", ver)),
          "صيغة VERSION صحيحة x.y.z", ver)


def t_app_declares_same() -> None:
    """التطبيق يعلن نفس الإصدار — وإلا ظهر للعميل رقم غير الحقيقي."""
    head("2) التطبيق يعلن إصدار VERSION")
    ver = version()
    for rel in ("windows_app/native_app.py", "windows_app/native_app_v2.py"):
        p = ROOT / rel
        if not p.is_file():
            check(False, f"{rel} موجود")
            continue
        txt = p.read_text(encoding="utf-8", errors="ignore")
        # أي إصدار من صيغة x.y.z مذكور في تعريف ثابت للنسخة.
        #
        # إصلاح عمى قياس: كان النمط `APP_VERSION\s*[:=]` يلزم أن يلي
        # الاسمَ فراغٌ أو فاصلة مباشرة، فلم يطابق `APP_VERSION_V2`
        # في مُشغِّل V2 لوجود اللاحقة. فأعلن الحاجز عن ذلك الملف
        # «لا تعريف نصي للنسخة (يقرأ VERSION)» ومرّ أخضر، بينما كان
        # الملف يحمل `"2.9.9"` متجمّدًا ويكتبه فوق الإصدار الحقيقي
        # عند الإطلاق. أي أن الحاجز كان يستر العطب الذي وُضع لصيده،
        # وهذا أضرّ من غياب الحاجز لأنه يمنح طمأنينة كاذبة.
        # النمط الآن يقبل أي لاحقة على الاسم (`\w*`).
        found = re.findall(
            r'APP_VERSION\w*\s*[:=]\s*["\'](\d+\.\d+\.\d+)', txt)
        if not found:
            check(True, f"{rel}: لا تعريف نصي للنسخة (يقرأ VERSION)")
            continue
        bad = [v for v in found if v != ver]
        check(not bad, f"{rel}: النسخة المعلنة تطابق {ver}",
              f"مخالف: {bad}" if bad else "")


def _vi_structure_ok(txt: str, want: tuple) -> tuple[bool, str]:
    """يتحقق من بنية ملف بيانات إصدار PyInstaller بلا تنفيذه.

    يفحص ما يطلبه PyInstaller فعلًا: تعبير `VSVersionInfo` واحد،
    `FixedFileInfo` بحقلي `filevers`/`prodvers` رباعيين ومتطابقين مع
    `VERSION`، و`StringFileInfo` يحوي المفاتيح التي يعرضها ويندوز في
    خصائص الملف.
    """
    if "VSVersionInfo" not in txt:
        return False, "لا يحوي VSVersionInfo"
    body = txt[txt.index("VSVersionInfo"):]
    try:
        tree = ast.parse(body, mode="eval")
    except SyntaxError as exc:
        return False, f"خطأ نحوي: السطر {exc.lineno}: {exc.msg}"

    call = tree.body
    if not (isinstance(call, ast.Call)
            and getattr(call.func, "id", "") == "VSVersionInfo"):
        return False, "الجذر ليس نداء VSVersionInfo"

    kw = {k.arg: k.value for k in call.keywords}
    if "ffi" not in kw or "kids" not in kw:
        return False, f"حقول ناقصة: {sorted(kw)}"

    ffi = kw["ffi"]
    if not (isinstance(ffi, ast.Call)
            and getattr(ffi.func, "id", "") == "FixedFileInfo"):
        return False, "ffi ليس FixedFileInfo"

    fkw = {k.arg: k.value for k in ffi.keywords}
    for field in ("filevers", "prodvers"):
        node = fkw.get(field)
        if node is None:
            return False, f"{field} مفقود"
        try:
            val = ast.literal_eval(node)
        except (ValueError, SyntaxError):
            return False, f"{field} ليس ثابتًا"
        if not (isinstance(val, tuple) and len(val) == 4):
            return False, f"{field} ليس رباعيًا: {val}"
        if val != want:
            return False, f"{field}={val} والمطلوب {want}"

    # المفاتيح النصية التي يعرضها ويندوز في خصائص الملف
    keys = set(re.findall(r"StringStruct\('([A-Za-z]+)'", txt))
    required = {"CompanyName", "FileDescription", "FileVersion",
                "InternalName", "LegalCopyright", "OriginalFilename",
                "ProductName", "ProductVersion"}
    missing = required - keys
    if missing:
        return False, f"مفاتيح ناقصة: {sorted(missing)}"

    return True, f"filevers={want}، {len(keys)} مفتاحًا"


def t_pyinstaller_version_info() -> None:
    """ملفا بيانات الإصدار مولَّدان من VERSION ويقرأهما PyInstaller فعلًا."""
    head("3) بيانات إصدار PyInstaller مطابقة وصالحة")
    ver = version()
    tup = tuple(int(x) for x in ver.split(".")) + (0,)

    gen = WIN / "توليد_بيانات_الإصدار.py"
    check(gen.is_file(), "مولّد بيانات الإصدار موجود")

    for name in ("version_info.txt", "version_info_owner.txt"):
        p = WIN / name
        if not p.is_file():
            check(False, f"{name} موجود")
            continue
        txt = p.read_text(encoding="utf-8")

        # الأرقام النصية كلها تطابق VERSION
        strs = re.findall(r"StringStruct\('(?:File|Product)Version',\s*"
                          r"'([\d.]+)'\)", txt)
        bad = [s for s in strs if not s.startswith(ver)]
        check(bool(strs) and not bad, f"{name}: الأرقام النصية = {ver}",
              f"مخالف: {bad}" if bad else f"{len(strs)} موضعًا")

        # وحقول filevers/prodvers الثنائية أيضًا
        tups = re.findall(r"(?:filevers|prodvers)=\(([\d,\s]+)\)", txt)
        parsed = [tuple(int(n) for n in t.replace(" ", "").split(","))
                  for t in tups]
        check(bool(parsed) and all(t == tup for t in parsed),
              f"{name}: filevers/prodvers = {tup}", f"{parsed}")

        # صلاحية بنيوية: يُحلَّل بـast بلا تنفيذ وبلا تبعيات.
        # لا نستورد PyInstaller.utils.win32.versioninfo لأنها تعتمد
        # على win32api فلا تعمل خارج ويندوز، وابتلاع فشلها كان
        # يعطّل هذا الفحص صامتًا.
        ok, why = _vi_structure_ok(txt, tup)
        check(ok, f"{name}: بنية VSVersionInfo صالحة", why)

    # المولّد نفسه يجب أن يُقرّ بالتطابق (يمنع تعديلًا يدويًا يخالف القالب)
    if gen.is_file():
        r = subprocess.run([sys.executable, str(gen), "--تحقق"],
                           capture_output=True, text=True, cwd=str(ROOT))
        check(r.returncode == 0, "المولّد يُقرّ بتطابق الملفين",
              (r.stdout or r.stderr).strip().splitlines()[-1:][0]
              if (r.stdout or r.stderr).strip() else "")


def t_installers_read_version() -> None:
    """المثبتات تقرأ الإصدار ولا تثبّته نصيًا."""
    head("4) مثبتات NSIS تقرأ VERSION")
    nsis = sorted(WIN.glob("*.nsi"))
    check(bool(nsis), "توجد مثبتات", f"{[f.name for f in nsis]}")
    for f in nsis:
        txt = f.read_text(encoding="utf-8", errors="ignore")
        hard = re.search(r'!define\s+APP_VERSION\s+"\d', txt)
        check(hard is None, f"{f.name}: لا إصدار نصي",
              hard.group(0) if hard else "")
        # ملف الجسر لا يقرأ VERSION بنفسه لأنه لا يملك منطقًا أصلًا:
        # كل ما فيه `!include` للسكربت الحقيقي، فالقراءة تأتي منه.
        # ولو أُلزم بـsearchparse لصار تكرارًا لمصدر الحقيقة — وهو
        # عين ما تمنعه هذه الحراسة. فالشرط عليه أن يُضمّن الأصل.
        includes_real = re.search(r'^\s*!include\s+"?installer\.nsi',
                                  txt, re.M) is not None
        check("searchparse" in txt or includes_real,
              f"{f.name}: يقرأ VERSION بـsearchparse (أو يُضمّن من يقرأه)")
        # `__FILEDIR__` في سطر فعّال = عطب توافق مُثبت، لا مطلوبًا.
        # makensis ينقل مجلد عمله إلى مجلد السكربت قبل التحليل
        # (مُثبت بـ`!system 'pwd'`)، لكن `__FILEDIR__` يبقى كما ورد في
        # سطر الأوامر؛ فالنداء بمسار نسبي من جذر المشروع يُنتج
        # `build/windows/\..\..\VERSION` فيُحلّ مرتين ويخفق. ينجو منه
        # windows-latest وحده، فيُسلّم مشروع لا يمكن بناءه محليًا.
        bad = [ln.strip() for ln in txt.splitlines()
               if "__FILEDIR__" in ln and not ln.lstrip().startswith(";")]
        check(not bad,
              f"{f.name}: لا __FILEDIR__ في سطر فعّال (يخفق على لينكس)",
              f"{bad[:1]}" if bad else "")
        # رقم إصدار قديم متسرّب في أي سطر فعّال (لا تعليق)
        live = [ln for ln in txt.splitlines()
                if not ln.lstrip().startswith(";")]
        # استثناء واحد واعٍ: سطر `!finalize` التوافقي. ورشة GitHub
        # القائمة تتحقق من اسم ثابت من عهد 2.0.0 وترفع الأثر به،
        # وتصحيحها محجوب (الدفع إلى `.github/workflows` يستلزم صلاحية
        # `workflows`). فينسخ السطر المُثبِّت الحقيقي نسخةً ثانية
        # بالاسم القديم. فـ«2.0.0» هنا ليست إصدارًا متسرّبًا بل اسم
        # واجهة خارجية لا نملك تغييرها — والملفان متطابقان بايتًا
        # ببايت. ويُلغى هذا الاستثناء متى لُصقت الورشة المصحّحة من
        # `build/ci/build-windows.yml.جاهز-للرفع`.
        leaked = [ln.strip() for ln in live
                  if re.search(r"\b\d+\.\d+\.\d+\b", ln)
                  and version() not in ln
                  and "!finalize" not in ln]
        check(not leaked, f"{f.name}: لا إصدار قديم متسرّب",
              f"{leaked[:2]}" if leaked else "")


def t_workflows_consistent() -> None:
    """ورشات البناء لا تثبّت إصدار المنتج نصيًا.

    ثلاث علل اجتمعت قبل الإصلاح:

    * `build-windows.yml` كانت عالقة على **2.0.0** (العنوان والتحقق
      واسم المخرج) وهي **الوحيدة** التي يشغّلها GitHub فعلًا.
    * `build-owner-studio.yml` ترفع مخرجًا باسم 1.0.0.
    * الورشة الأكمل كانت في `build/ci/` — خارج `.github/workflows/`
      فلا تعمل إطلاقًا — وتعلن `APP_VERSION: "2.9.5"` وتتحقق من وجود
      `...Setup-2.9.5.exe` بينما المُثبِّت ينتج 2.9.9، فتفشل برسالة
      مضلّلة «مُثبِّت المستخدم مفقود».

    الفحص يستهدف إصدار **المنتج** فقط: تثبيتات التبعيات مثل
    `PySide6==6.8.1` مشروعة ولا تُعدّ مخالفة.
    """
    head("5) ورشات البناء متسقة مع VERSION")
    ver = version()
    wfdir = ROOT / ".github" / "workflows"
    wf = sorted(wfdir.glob("*.yml")) if wfdir.is_dir() else []
    check(bool(wf), "توجد ورشات في .github/workflows", f"{len(wf)} ملفًا")

    # الورشة الكاملة يجب أن تكون حيث يشغّلها GitHub، لا في build/ci
    stray = list((ROOT / "build" / "ci").glob("*.yml"))         if (ROOT / "build" / "ci").is_dir() else []
    check(not stray, "لا ورشة معطّلة في build/ci",
          f"{[f.name for f in stray]}" if stray else "")

    # الأنماط التي يظهر فيها إصدار المنتج تحديدًا
    prod = re.compile(
        r"""(?x)
        ^\s*name:\s*.*?(?P<a>\d+\.\d+\.\d+)          # عنوان الورشة/المخرج
        | APP_VERSION\s*:\s*["']?(?P<b>\d+\.\d+\.\d+)  # متغير الإصدار
        | (?:Setup|Portable|OwnerStudio|Studio)-(?P<c>\d+\.\d+\.\d+)
        | -Setup-(?P<d>\d+\.\d+\.\d+)\.exe            # مسار المُثبِّت
        """)

    for f in wf:
        txt = f.read_text(encoding="utf-8", errors="ignore")
        bad = []
        for ln in txt.splitlines():
            if ln.lstrip().startswith("#"):
                continue
            m = prod.search(ln)
            if not m:
                continue
            found = next(g for g in m.groups() if g)
            if found != ver:
                bad.append(f"{ln.strip()[:60]} ⇐ {found}")
        check(not bad, f"{f.name}: لا إصدار منتج يخالف {ver}",
              f"{bad[:3]}" if bad else "")

        # ويجب أن تقرأ VERSION فعلًا لا أن تكتفي بغياب الرقم
        check("VERSION" in txt,
              f"{f.name}: تقرأ ملف VERSION")


def t_eula_no_version() -> None:
    """الاتفاقية لا تحمل رقم إصدار، وتُقرأ سليمة على ويندوز.

    الاتفاقية أول ما يراه العميل (صفحة الترخيص في المثبت). وقد وُجدت
    تعلن «الإصدار 2.9.5» والبرنامج 2.9.9 — فالعميل يوافق على وثيقة
    قانونية برقم مغلوط. القاعدة المعتمدة: **لا رقم إصدار في نص
    الاتفاقية** إطلاقًا، لأنه يتخلّف مع كل إصدار جديد.
    """
    head("6) اتفاقية الترخيص (EULA)")
    eula = WIN / "EULA_ar.txt"
    check(eula.is_file(), "EULA_ar.txt موجودة")
    if not eula.is_file():
        return

    raw = eula.read_bytes()
    # تُقبل UTF-16LE (BOM ff fe) أو UTF-8 مع BOM: بلا أحدهما يقرأ
    # ويندوز الملف بترميز المحلية فتتشوّه العربية في وجه العميل.
    if raw.startswith(b"\xff\xfe"):
        enc, kind = "utf-16-le", "UTF-16LE + BOM"
        body = raw[2:].decode(enc, "replace")
    elif raw.startswith(b"\xfe\xff"):
        enc, kind = "utf-16-be", "UTF-16BE + BOM"
        body = raw[2:].decode(enc, "replace")
    elif raw.startswith(b"\xef\xbb\xbf"):
        enc, kind = "utf-8-sig", "UTF-8 + BOM"
        body = raw.decode(enc, "replace")
    else:
        enc, kind, body = "", "بلا BOM", raw.decode("utf-8", "replace")
    check(bool(enc), "تحمل BOM يمنع تشوّه العربية", kind)

    # لا رقم إصدار في النص
    hits = [f"سطر {i}" for i, ln in enumerate(body.splitlines(), 1)
            if re.search(r"الإصدار\s*\d+\.\d+\.\d+"
                         r"|النسخة\s*\d+\.\d+\.\d+"
                         r"|\bv?\d+\.\d+\.\d+\b", ln)]
    check(not hits, "لا رقم إصدار في نص الاتفاقية",
          "متسقة مع أي إصدار" if not hits else ", ".join(hits))

    # نهايات CRLF: نافذة ترخيص NSIS تتوقعها، وبلاها تظهر
    # الاتفاقية كتلة متلاصقة.
    crlf = body.count("\r\n")
    lone = body.count("\n") - crlf
    check(lone == 0, "نهايات الأسطر CRLF كما تتوقع نافذة الترخيص",
          f"CRLF={crlf}، LF منفرد={lone}")

    # المثبت يشير إليها فعلًا (وإلا فالفحص يحرس ملفًا مهجورًا)
    nsi = WIN / "installer.nsi"
    if nsi.is_file():
        txt = nsi.read_text(encoding="utf-8-sig", errors="replace")
        check("EULA_ar.txt" in txt,
              "المثبت يعرض الاتفاقية فعلًا", "MUI_PAGE_LICENSE")


def main() -> int:
    print("═" * 58)
    print("حاجز تناسق الإصدار — استوديو صور المتجر")
    print("═" * 58)
    for fn in (t_version_file, t_app_declares_same,
               t_pyinstaller_version_info, t_installers_read_version,
               t_workflows_consistent, t_eula_no_version):
        try:
            fn()
        except Exception as exc:
            global FAIL
            FAIL += 1
            FAILURES.append(f"{fn.__name__} (استثناء)")
            print(f"  ✗ {fn.__name__} رفع استثناء: {exc}")
            import traceback
            traceback.print_exc(limit=3)
    print("\n" + "═" * 58)
    print(f"نجح {PASS} / فشل {FAIL}")
    if FAILURES:
        print("الإخفاقات:")
        for x in FAILURES:
            print(f"  - {x}")
        return 1
    print("الإصدار متسق في كل القنوات — مصدره الوحيد ملف VERSION")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
