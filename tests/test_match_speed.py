# -*- coding: utf-8 -*-
"""حاجز تكافؤ + تسريع لمطابقة أسماء الملفات مع الكتالوج.

المالك يشترط **مطابقة 100%** مع الإكسل، فالتسريع لا يُقبل إن اختلفت
نتيجة واحدة. هذا الاختبار:

1. يحمّل كتالوج المالك الحقيقي (اصنافعالمعنترة.xlsx، 50,311 صنفًا).
2. يشغّل `_filename_match` الأصلية والسريعة على **كل** أسماء صور
   دفعة الزيت (109 صورة) ويقارن (رقم الصنف، الاسم، السبب، الدرجة).
3. يفشل إن اختلفت نتيجة واحدة، أو إن لم يتحقق تسريع فعلي.

التشغيل:
    PYTHONPATH=src:windows_app python3 tests/test_match_speed.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("MIS_HEADLESS", "1")

ROOT = Path(__file__).resolve().parent.parent
for extra in (ROOT / "src", ROOT / "windows_app"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

# حرّاس بيانات المالك — تخطٍّ برمز 77 لا فشل زائف برمز 1.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from owner_data_guard import (  # noqa: E402
    describe, list_images, require_owner_data)

CATALOG, RAW = require_owner_data(need_catalog=True, need_raw=True,
                                  minimum_images=5)

PASS = "\u2713"
FAIL = "\u2717"
_results: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: str = "") -> bool:
    _results.append((bool(ok), label))
    mark = PASS if ok else FAIL
    line = f"  {mark} {label}"
    if detail:
        line += f" — {detail}"
    print(line, flush=True)
    return bool(ok)


def main() -> int:
    print("=" * 68)
    print(" حاجز تكافؤ وتسريع المطابقة على بيانات المالك")
    print("=" * 68)

    print(describe())
    images = list_images(RAW)

    from smart_catalog_vision import pipeline as P
    from engine_v2 import match_speed_v2

    print(f"\n[1] تحميل الكتالوج ({CATALOG.name})")
    t0 = time.perf_counter()
    index = P._load_catalog(CATALOG)
    load_seconds = time.perf_counter() - t0
    records = list(getattr(index, "records", ()) or ())
    print(f"    {len(records)} سجلًا في {load_seconds:.2f} ث")
    check(len(records) > 1000, "الكتالوج محمّل",
          f"{len(records)} سجلًا")

    print(f"\n[2] تثبيت ترقيع التسريع")
    installed = match_speed_v2.install(P)
    check(installed, "الترقيع مثبَّت")
    if not installed:
        return 1

    print(f"\n[3] بناء الكاش (تطبيع الكتالوج مرة واحدة)")
    cache = match_speed_v2.CatalogMatchCache(index, P._normalize_header)
    print(f"    {cache.record_count} سجلًا | قابل للمطابقة "
          f"{len(cache.usable)} | ثلاثيات {len(cache.by_gram)} "
          f"| كلمات {len(cache.by_token)}")
    check(cache.build_seconds < 30.0, "بناء الكاش سريع",
          f"{cache.build_seconds:.2f} ث")

    print(f"\n[4] مقارنة النتائج على {len(images)} صورة حقيقية")
    report = match_speed_v2.verify_equivalence(P, index, images)
    if "error" in report:
        check(False, "التحقق تعذّر", report["error"])
        return 1

    total = report["total"]
    matched = report["matched"]
    mism = report["mismatches"]
    print(f"    الأصلية: {report['original_seconds']:.2f} ث "
          f"| السريعة: {report['fast_seconds']:.2f} ث "
          f"| تسريع ×{report['speedup']:.1f}")
    check(matched == total, "تكافؤ النتائج 100%",
          f"{matched}/{total} متطابق")
    if mism:
        print(f"\n    اختلافات ({len(mism)}) — أول 10:")
        for row in mism[:10]:
            print(f"      • {row['file']}")
            print(f"        متوقع: {row['expected']}")
            print(f"        فعلي : {row['actual']}")

    per_orig = report["original_seconds"] / max(1, total)
    per_fast = report["fast_seconds"] / max(1, total)
    print(f"\n[5] الأثر على دفعة 109 صورة (المطابقة وحدها)")
    print(f"    قبل: {per_orig * 109 / 60:.1f} دقيقة "
          f"| بعد: {per_fast * 109 / 60:.2f} دقيقة")
    check(report["speedup"] >= 3.0, "تسريع لا يقل عن ×3",
          f"×{report['speedup']:.1f}")

    passed = sum(1 for ok, _ in _results if ok)
    print("\n" + "=" * 68)
    print(f"النتيجة: {passed}/{len(_results)}")
    if passed != len(_results):
        print("فشل:")
        for ok, label in _results:
            if not ok:
                print(f"  {FAIL} {label}")
    print("=" * 68)
    return 0 if passed == len(_results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
