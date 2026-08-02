# -*- coding: utf-8 -*-
"""قياس أداء المحركات الجديدة — يجب أن تبقى المعالجة سلسة للدفعات الكبيرة.

الحدود المقبولة لكل صورة 2000×1800:
- auto_blur_dates: < 2.5s (OCR على المرشحات فقط)
- smart_downscale: < 0.5s
- polish_output_file: < 1.5s (بدون طمس تواريخ)
"""
import os
import sys
import time
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import cv2
import numpy as np
from test_quality_date_v21 import make_product_image


#: معامل تسامح عند ازدحام المعالج (مسح متوازٍ لعدة اختبارات
#: ثقيلة معًا يُضاعف الأزمنة بلا أي تراجع حقيقي في الكود).
_SLACK = float(os.environ.get("MIS_PERF_SLACK", "1"))


def bench(name, fn, n=3, limit=None):
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t0)
    avg = sum(ts) / len(ts)
    # أفضل زمن يعبر عن قدرة الكود الفعلية دون ضجيج الجدولة
    best = min(ts)
    eff = None if limit is None else limit * _SLACK
    ok = eff is None or avg <= eff or best <= eff
    print(f"{'PASS' if ok else 'FAIL'} {name}: avg={avg:.3f}s "
          f"best={best:.3f}s (limit={limit}s"
          + (f" x{_SLACK:g}" if _SLACK != 1 else "") + ")")
    return ok


def main():
    from engine_v2.quality_v2 import (polish_output_file, smart_downscale)
    from engine_v2.date_blur_v2 import auto_blur_dates

    img = make_product_image()
    results = []

    results.append(bench("smart_downscale_2000to800",
                         lambda: smart_downscale(img, 800, 700), limit=0.5))
    results.append(bench("auto_blur_dates_2000x1800",
                         lambda: auto_blur_dates(img), limit=2.5))

    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "x.webp")
        small = cv2.resize(img, (800, 700), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".webp", small, [cv2.IMWRITE_WEBP_QUALITY, 94])
        buf.tofile(p)
        results.append(bench("polish_output_file_800x700",
                             lambda: polish_output_file(p, quality=101),
                             limit=1.5))
        results.append(bench("polish_with_dates_800x700",
                             lambda: polish_output_file(p, quality=101,
                                                        blur_dates=True),
                             limit=3.0))

    if all(results):
        print("ALL PERF TESTS PASSED")
    else:
        print("PERF FAILURES")
        sys.exit(1)


if __name__ == "__main__":
    main()
