# -*- coding: utf-8 -*-
"""اختبار صيغ الإخراج (webp/jpg/png) + التنقيح + عدم التكرار عند إعادة التشغيل."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import cv2
import numpy as np

from engine_v2.batch_refine_v2 import BatchRefiner, RefineOptions


def main() -> None:
    srcd = Path(tempfile.mkdtemp())
    dstd = Path(tempfile.mkdtemp())
    img = np.full((300, 300, 3), 255, np.uint8)
    cv2.circle(img, (150, 150), 90, (30, 90, 200), -1)
    cv2.imwrite(str(srcd / "10001234_حبه.png"), img)
    cv2.imwrite(str(srcd / "10001234_حبه_2.png"), img)

    for fmt in ("webp", "jpg", "png"):
        outd = dstd / fmt
        outd.mkdir()
        o = RefineOptions(recut=False, enhance=True, frame=True,
                          out_format=fmt, polish=True,
                          compress=(fmt == "jpg"), workers=1)
        br = BatchRefiner("/nonexistent-models", o)
        br.run(str(srcd), str(outd))
        files = sorted(p.name for p in outd.iterdir()
                       if not p.name.startswith("."))
        print(fmt, "->", files)
        assert files, "لا مخرجات!"
        assert all(f.endswith("." + fmt) for f in files), files
        # تشغيل ثانٍ: يجب التخطي بلا تكرار
        BatchRefiner("/nonexistent-models", o).run(str(srcd), str(outd))
        files2 = sorted(p.name for p in outd.iterdir()
                        if not p.name.startswith("."))
        assert files == files2, (files, files2)
    print("OK: الصيغ الثلاث + polish + عدم التكرار في التشغيل الثاني")


if __name__ == "__main__":
    main()
