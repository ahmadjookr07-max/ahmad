#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبار انحدار لعلة «جودة WebP بلا فقدان تقتل الدفعة».

العلة المرصودة: خيار الواجهة «فائقة — بلا فقدان (lossless)» يحمل القيمة
101، و``FinalImageOptions.validated`` في المحرّك يشترط ``<= 100`` فيرفع
``ValueError`` قبل معالجة أي صورة. النتيجة: صفر مخرجات لدفعة كاملة.

هذا الاختبار يثبّت ثلاث حقائق حتى لا تعود العلة صامتة:

1. القيمة 101 تمرّ من ``validated`` وتبقى 101 (لا تُخفَض إلى 100).
2. القيم المشروعة تبقى مقبولة، والقيم الفاسدة تبقى مرفوضة — الترقيع
   لم يُسقط التحقق بل استثنى علم lossless وحده.
3. 101 تُنتج WebP مطابقًا بايت ببايت، و100 لا تفعل — أي أن الخيار
   يعني ما يقوله فعلًا.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "windows_app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MIS_SKIP_LICENSE", "1")

LOSSLESS = 101

failures: list[str] = []
passes: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    if ok:
        passes.append(label)
        print(f"  ✓ {label}")
    else:
        failures.append(f"{label} — {detail}" if detail else label)
        print(f"  ✗ {label}" + (f" — {detail}" if detail else ""))


def main() -> int:
    print("=" * 64)
    print(" اختبار جودة WebP بلا فقدان (101)")
    print("=" * 64)

    # ── 1) الترقيع يجعل validated يقبل 101 ويحفظها ──
    print("[1] طبقة التحقق في المحرّك")
    import lazy_engine
    from lazy_engine import load_engine

    try:
        load_engine()
    except Exception as exc:  # المحرّك غير متاح في هذه البيئة
        print(f"SKIP: تعذر تحميل المحرّك — {exc}")
        return 77

    from smart_catalog_vision.final_images import FinalImageOptions

    options = FinalImageOptions(webp_quality=LOSSLESS)
    try:
        validated = options.validated()
        check(True, "الجودة 101 تمرّ من validated بلا استثناء")
        check(validated.webp_quality == LOSSLESS,
              "الجودة تبقى 101 بعد التحقق (لم تُخفَض)",
              f"القيمة الناتجة: {validated.webp_quality}")
    except ValueError as exc:
        check(False, "الجودة 101 تمرّ من validated بلا استثناء", str(exc))
        check(False, "الجودة تبقى 101 بعد التحقق (لم تُخفَض)", "لم تُنفَّذ")

    # ── 2) التحقق المشروع لم يُسقَط ──
    print("[2] سلامة بقية التحقق")
    for good in (1, 50, 94, 100):
        try:
            result = FinalImageOptions(webp_quality=good).validated()
            check(result.webp_quality == good,
                  f"الجودة المشروعة {good} تبقى كما هي")
        except ValueError as exc:
            check(False, f"الجودة المشروعة {good} تبقى كما هي", str(exc))

    for bad in (0, -5, 102, 500):
        try:
            FinalImageOptions(webp_quality=bad).validated()
            check(False, f"الجودة الفاسدة {bad} تُرفَض",
                  "قُبلت وكان يجب رفضها")
        except ValueError:
            check(True, f"الجودة الفاسدة {bad} تُرفَض")

    # ── 3) المعنى الفعلي: 101 بلا فقدان و100 ليست كذلك ──
    print("[3] المعنى الفعلي للخيار على القرص")
    import cv2
    import numpy as np

    rng = np.random.default_rng(7)
    image = rng.integers(0, 256, size=(700, 800, 3), dtype=np.uint8)

    def roundtrip(quality: int) -> tuple[bool, int]:
        ok, encoded = cv2.imencode(
            ".webp", image, [cv2.IMWRITE_WEBP_QUALITY, int(quality)])
        if not ok:
            return False, 0
        decoded = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        return bool(np.array_equal(decoded, image)), len(encoded)

    lossless_ok, lossless_size = roundtrip(LOSSLESS)
    lossy_ok, lossy_size = roundtrip(100)
    check(lossless_ok, "الجودة 101 تُنتج WebP مطابقًا بايت ببايت",
          f"الحجم {lossless_size}")
    check(not lossy_ok, "الجودة 100 ليست بلا فقدان (فلا تصلح بديلًا)",
          f"الحجم {lossy_size}")

    # ── 4) خيار الواجهة يطابق ما يقبله المحرّك ──
    print("[4] تطابق الواجهة مع المحرّك")
    source = (ROOT / "windows_app" / "native_app.py").read_text(
        encoding="utf-8")
    check("lossless" in source and str(LOSSLESS) in source,
          "الواجهة ما زالت تعرض خيار 101 (لم يُحَل بحذف الميزة)")
    check(lazy_engine.LOSSLESS_WEBP_QUALITY == LOSSLESS,
          "قيمة العلم موحّدة في الحدّ الفاصل")

    print("=" * 64)
    print(f"النتيجة: {len(passes)}/{len(passes) + len(failures)}")
    if failures:
        print("فشل:")
        for item in failures:
            print(f"  ✗ {item}")
        return 1
    print("كل الفحوص نجحت — خيار «بلا فقدان» يعمل فعلًا.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
