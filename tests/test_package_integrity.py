# -*- coding: utf-8 -*-
"""حاجز سلامة الحزمة — يمنع تسليم مُثبِّت ناقص بصمت.

سبب وجود هذا الملف حادثة حقيقية: ملف الـ`.spec` كان يسرد وحدات المشروع
**يدويًا**، فسرد 14 وحدة من `engine_v2` ونسي طبقة `awareness` بأكملها
ونسي وحدات واجهة قائمة (`unified_editor`, `flow_layout`, `ui_scale`,
`nutrition_crop`, `lazy_engine`).

والخطورة ليست في النقص بل في **صمته**: طبقة الوعي مستوردة داخل
`try/except` حتى تبقى المعالجة سليمة إن غابت. فلو بُني المُثبِّت ناقصًا
لما فشل البناء ولا اشتكى البرنامج — بل يعمل بلا لوحة وعي، وبلا حوار
عربي، وبلا تنفيذ لأوامر المالك. عطل لا يكتشفه إلا المالك بعد التثبيت.

فالدرس: **الاعتماد على الانتباه البشري في قائمة يدوية خطأ مؤكد الوقوع.**
هذا الفحص يقارن ما على القرص بما يسرده الـspec، ويفشل إن نقص شيء.

    python3 tests/test_package_integrity.py
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "build" / "windows" / "AhmedAlFaifiMarketImageStudioV2.spec"

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def check(cond: bool, label: str, note: str = "") -> bool:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {label} {note}")
    else:
        FAIL += 1
        FAILURES.append(label)
        print(f"  ✗ {label} {note}")
    return bool(cond)


def head(title: str) -> None:
    print(f"\n── {title} ──")


def _modules_on_disk() -> dict[str, list[str]]:
    """وحدات المشروع الفعلية كما هي على القرص."""
    def scan(d: Path, prefix: str) -> list[str]:
        if not d.is_dir():
            return []
        out = []
        for f in sorted(d.glob("*.py")):
            if f.stem.startswith("_"):
                continue
            out.append(prefix + f.stem)
        return out

    return {
        "engine_v2": scan(ROOT / "src" / "engine_v2", "engine_v2."),
        "awareness": scan(ROOT / "src" / "awareness", "awareness."),
        "ui": scan(ROOT / "windows_app", ""),
    }


def t_spec_covers_disk() -> None:
    head("1) الـspec يغطي كل وحدة على القرص")
    check(SPEC.is_file(), "ملف الـspec موجود", str(SPEC.name))
    if not SPEC.is_file():
        return

    src = SPEC.read_text(encoding="utf-8")

    # الـspec صار يكتشف تلقائيًا؛ نتحقق أن الاكتشاف قائم لا سرد ثابت
    check("_discover" in src, "الـspec يكتشف الوحدات تلقائيًا لا يسردها يدويًا")
    check("_REQUIRED" in src and "SystemExit" in src,
          "الـspec يفشل صراحةً عند غياب وحدة حرجة")

    # صحة تركيبية: spec معطوب يُفشل البناء كله
    try:
        ast.parse(src)
        ok_syntax = True
    except SyntaxError as exc:
        ok_syntax = False
        print(f"      SyntaxError: {exc}")
    check(ok_syntax, "الـspec صحيح تركيبيًا")

    disk = _modules_on_disk()
    total = sum(len(v) for v in disk.values())
    check(total > 0, "وُجدت وحدات على القرص", f"{total} وحدة")

    # الوحدات المذكورة في _REQUIRED يجب أن توجد فعلًا على القرص،
    # وإلا فالحاجز نفسه سيُفشل كل بناء بلا سبب حقيقي
    req = re.search(r"_REQUIRED\s*=\s*\((.*?)\)", src, re.S)
    listed = re.findall(r'"([^"]+)"', req.group(1)) if req else []
    check(bool(listed), "قائمة الوحدات الحرجة مقروءة", f"{len(listed)} وحدة")

    flat = set(disk["engine_v2"]) | set(disk["awareness"]) | set(disk["ui"])
    phantom = [m for m in listed if m not in flat]
    check(not phantom, "كل وحدة حرجة موجودة فعلًا على القرص",
          f"وهمية: {phantom}" if phantom else "")

    # كل وحدة وعي على القرص يجب أن تكون في الحاجز، فطبقة الوعي
    # بالتحديد هي التي تُفقد بصمت
    aware_missing = [m for m in disk["awareness"] if m not in listed]
    check(not aware_missing, "كل وحدات الوعي محميّة بالحاجز",
          f"غير محميّة: {aware_missing}" if aware_missing else
          f"{len(disk['awareness'])} وحدة")


def t_awareness_importable() -> None:
    head("2) طبقة الوعي تُستورد فعلًا")
    sys.path.insert(0, str(ROOT / "src"))
    mods = [p.stem for p in (ROOT / "src" / "awareness").glob("*.py")
            if not p.stem.startswith("_")]
    broken = []
    for m in mods:
        try:
            __import__(f"awareness.{m}")
        except Exception as exc:
            broken.append(f"{m}: {type(exc).__name__}")
    check(not broken, "كل وحدات الوعي تُستورد بلا عطل",
          f"معطوبة: {broken}" if broken else f"{len(mods)} وحدة")


def t_bridge_wired() -> None:
    head("3) الجسر موصول فعلًا بمسار المعالجة")
    integ = ROOT / "src" / "engine_v2" / "integration_v2.py"
    bridge = ROOT / "src" / "engine_v2" / "awareness_bridge_v2.py"
    check(bridge.is_file(), "ملف الجسر موجود")
    check(integ.is_file(), "ملف التكامل موجود")
    if not (integ.is_file() and bridge.is_file()):
        return

    src = integ.read_text(encoding="utf-8")
    # العزل السابق: الحوار يسجّل التجاوز و_coerce_options لا تقرؤه أبدًا،
    # فيقول البرنامج «نفّذت» ولا ينفّذ
    check("awareness_bridge" in src or "apply_awareness" in src,
          "مسار بناء الخيارات يستشير طبقة الوعي")

    m = re.search(r"def _coerce_options.*?(?=\ndef |\nclass |\Z)", src, re.S)
    check(bool(m) and ("awareness" in m.group(0)
                       or "apply_" in m.group(0)),
          "الاستشارة داخل _coerce_options نفسها لا في مكان معزول")


def t_installer_current() -> None:
    head("4) المُثبِّت يطابق نسخة المشروع")
    ver_file = ROOT / "VERSION"
    check(ver_file.is_file(), "ملف VERSION موجود")
    if not ver_file.is_file():
        return
    ver = ver_file.read_text(encoding="utf-8").strip()

    nsis = sorted((ROOT / "build" / "windows").glob("installer_v*.nsi"))
    check(bool(nsis), "توجد ملفات مُثبِّت", f"{len(nsis)} ملفًا")

    # مُثبِّت بنسخة قديمة يعني تسليم بناء لا يطابق الكود
    matching = []
    for f in nsis:
        txt = f.read_text(encoding="utf-8", errors="ignore")
        if re.search(rf'APP_VERSION\s+"{re.escape(ver)}"', txt):
            matching.append(f.name)
    check(bool(matching), f"مُثبِّت يطابق النسخة {ver}",
          f"{matching}" if matching else "لا مُثبِّت بهذه النسخة!")

    # الاتفاقية وبيانات الدعم شرط تعاقدي لا تفصيل
    eula = ROOT / "build" / "windows" / "EULA_ar.txt"
    check(eula.is_file() and eula.stat().st_size > 200,
          "الاتفاقية العربية موجودة وغير فارغة",
          f"{eula.stat().st_size if eula.is_file() else 0} بايت")
    if matching:
        txt = (ROOT / "build" / "windows" / matching[-1]).read_text(
            encoding="utf-8", errors="ignore")
        check("ahmadjookr06@gmail.com" in txt, "بريد الدعم مضمّن")
        check("0582381000" in txt, "هاتف الدعم مضمّن")
        check("MUI_PAGE_LICENSE" in txt, "صفحة الاتفاقية إلزامية في التثبيت")


def main() -> int:
    print("═" * 54)
    print("حاجز سلامة الحزمة — استوديو صور المتجر")
    print("═" * 54)
    for fn in (t_spec_covers_disk, t_awareness_importable,
               t_bridge_wired, t_installer_current):
        try:
            fn()
        except Exception as exc:
            global FAIL
            FAIL += 1
            FAILURES.append(f"{fn.__name__} (استثناء)")
            import traceback
            print(f"  ✗ {fn.__name__} رفع استثناء: {exc}")
            traceback.print_exc(limit=3)
    print("\n" + "═" * 54)
    print(f"نجح {PASS} / فشل {FAIL}")
    if FAILURES:
        print("الفاشل: " + " | ".join(FAILURES))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
