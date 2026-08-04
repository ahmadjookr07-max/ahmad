# -*- coding: utf-8 -*-
"""حاجز بايت-كود المحرك المُترجَم — يمنع عطلًا صامتًا يقتل التسريعات.

## المشكلة التي يحرسها هذا الاختبار

المجلد ``src/smart_catalog_vision/`` لا يحوي مصدر بايثون بل ملفات
``.pyc`` مترجَمة مسبقًا (محرك 1.2.1 المُجرَّب). وملف ``.pyc`` مربوط
بإصدار مفسّر بعينه عبر «رقم سحري» (magic number) في أول أربعة بايت؛
فإن بُني التطبيق بإصدار بايثون مختلف يرفض المفسّر تحميل الملف.

والأخطر أن الرفض **صامت**: الاستيراد في التطبيق محمي بـ``try/except``
حتى تبقى المعالجة الأساسية سليمة عند غياب المحرك القديم، فلا يرى أحد
خطأً — فقط تنهار تسريعات ``state_cache`` و``match_speed`` ويسقط مسار
المجلد المنجز، ويصل للمالك برنامج أبطأ وأنقص بلا أي رسالة.

حدث هذا فعلًا: بُني التطبيق ببايثون 3.11 بينما ملفات ``.pyc`` بايت-كود
3.12، فظهرت التسريعات ``off`` وضاع وقت في تشخيص وهمي.

## ما يفحصه

1. الرقم السحري لكل ``.pyc`` واحد ومتسق.
2. الإصدار الذي يقابله يطابق ما تعلنه ورشة البناء (``python-version``).
3. ملف المواصفات يحزم ``__init__.py`` و``pipeline.pyc`` (بلا ``__init__``
   ليس المجلد حزمة فلا يُرى ``pipeline`` أصلًا).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCV = ROOT / "src" / "smart_catalog_vision"
SPEC = ROOT / "build" / "windows" / "AhmedAlFaifiMarketImageStudioV2.spec"
WORKFLOWS = ROOT / ".github" / "workflows"

# خرائط الأرقام السحرية المعروفة (Lib/importlib/_bootstrap_external.py)
MAGIC_TO_PY = {
    3495: "3.11",
    3531: "3.12",
    3571: "3.13",
    3621: "3.14",
}

_passed: list[str] = []
_failed: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        _passed.append(name)
        print(f"  ✓ {name} {detail}")
    else:
        _failed.append(name)
        print(f"  ✗ {name} {detail}")


def read_magic(path: Path) -> int:
    """الرقم السحري = أول بايتين، ويتبعه دائمًا ``\\r\\n`` في ملف pyc سليم."""
    with path.open("rb") as fh:
        return int.from_bytes(fh.read(2), "little")


def has_pyc_header(path: Path) -> bool:
    """هل للملف ترويسة pyc حقيقية؟

    ترويسة pyc: بايتان سحريان ثم ``0d 0a`` (CR LF) حرفيًا. غياب هذين
    البايتين يعني أن الملف ليس pyc بل كائن ``code`` خام مُسلسَل بـ``marshal``
    (أثر أداة استخراج). مثل هذا الملف لا يُحمَّل بالاستيراد العادي، ولولا
    هذا الفحص لظهر رقمه الأول كأنه «رقم سحري غريب» فيُشخَّص خطأً على أنه
    تعارض إصدارات بايثون.
    """
    with path.open("rb") as fh:
        return fh.read(4)[2:4] == b"\r\n"


def main() -> int:
    print("═" * 58)
    print("حاجز بايت-كود smart_catalog_vision")
    print("═" * 58)

    print("── 1) الملفات موجودة ──")
    check("مجلد smart_catalog_vision موجود", SCV.is_dir(), str(SCV))
    if not SCV.is_dir():
        print("لا يمكن المتابعة بلا المجلد.")
        return 1

    pycs = sorted(SCV.glob("*.pyc"))
    check("توجد ملفات .pyc", len(pycs) > 0, f"{len(pycs)} ملفًا")

    # كل ملف بلاحقة .pyc يجب أن يحمل ترويسة pyc سليمة. الملف الذي لا
    # يحملها هو كائن code خام لا يُستورَد أبدًا ⇒ نسخة زائدة مضلِّلة
    # (وُجد فعلًا `pipeline.extracted.pyc` = جسم `pipeline.pyc` بلا
    # ترويسته، مطابق حرفيًا لآخر 79,119 بايت منه، بلا أي مرجع في المشروع).
    headerless = [p.name for p in pycs if not has_pyc_header(p)]
    check(
        "كل ملفات .pyc تحمل ترويسة pyc سليمة",
        not headerless,
        f"بلا ترويسة (كائن marshal خام): {headerless}" if headerless else "",
    )
    pycs = [p for p in pycs if has_pyc_header(p)]
    check(
        "__init__.py موجود (وإلا فالمجلد ليس حزمة)",
        (SCV / "__init__.py").exists(),
    )
    check("pipeline.pyc موجود", (SCV / "pipeline.pyc").exists())

    print("── 2) الأرقام السحرية متسقة ──")
    magics = {p.name: read_magic(p) for p in pycs}
    uniq = sorted(set(magics.values()))
    check(
        "رقم سحري واحد لكل الملفات",
        len(uniq) == 1,
        f"{uniq}" if len(uniq) != 1 else f"magic={uniq[0]}",
    )
    if len(uniq) != 1:
        for n, m in sorted(magics.items()):
            print(f"      {n}: {m}")
        return 1

    magic = uniq[0]
    pyver = MAGIC_TO_PY.get(magic)
    check(
        "الرقم السحري معروف ويقابل إصدار بايثون",
        pyver is not None,
        f"magic={magic} ⇒ بايثون {pyver}" if pyver else f"magic={magic} مجهول",
    )
    if pyver is None:
        return 1

    print("── 3) ورشات البناء تستخدم الإصدار نفسه ──")
    wf_files = sorted(WORKFLOWS.glob("*.yml")) if WORKFLOWS.is_dir() else []
    check("توجد ورشات بناء", len(wf_files) > 0, f"{len(wf_files)} ملفًا")
    for wf in wf_files:
        text = wf.read_text(encoding="utf-8")
        found = re.findall(r'python-version:\s*"?([0-9]+\.[0-9]+)"?', text)
        if not found:
            continue
        bad = [v for v in found if v != pyver]
        check(
            f"{wf.name}: بايثون {pyver}",
            not bad,
            f"وجدت {sorted(set(found))}" if bad else f"{sorted(set(found))}",
        )

    print("── 4) ملف المواصفات يحزم المحرك ──")
    if SPEC.exists():
        spec_text = SPEC.read_text(encoding="utf-8")
        for needed in ("__init__.py", "pipeline.pyc"):
            check(
                f"المواصفات تحزم {needed}",
                f'"smart_catalog_vision" / "{needed}"' in spec_text
                or f"smart_catalog_vision/{needed}" in spec_text
                or (needed in spec_text and "smart_catalog_vision" in spec_text),
            )
        # كل .pyc على القرص يجب أن يُذكر في المواصفات وإلا يُفقد صامتًا
        missing_in_spec = [p.name for p in pycs if p.name not in spec_text]
        check(
            "كل ملفات .pyc مذكورة في المواصفات",
            not missing_in_spec,
            f"ناقص: {missing_in_spec}" if missing_in_spec else "",
        )
    else:
        check("ملف المواصفات موجود", False, str(SPEC))

    print("── 5) مفسّر هذا الصندوق (تنويه لا حاجز) ──")
    local = f"{sys.version_info.major}.{sys.version_info.minor}"
    if local == pyver:
        print(f"  ✓ المفسّر المحلي {local} يطابق بايت-كود المحرك")
    else:
        print(
            f"  ℹ المفسّر المحلي {local} ≠ {pyver}؛ لا يهم للاختبارات "
            f"لأن الاستيراد محمي، لكن **بناء الحزمة يجب أن يكون بـ{pyver}**"
        )

    print("═" * 58)
    print(f"نجح {len(_passed)} / فشل {len(_failed)}")
    if _failed:
        print("الإخفاقات:")
        for f in _failed:
            print(f"  - {f}")
        return 1
    print(f"بايت-كود المحرك متسق على بايثون {pyver} وورشات البناء تطابقه")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
