# -*- coding: utf-8 -*-
"""اختبار عزل المنتج ProductSegmenterV2 على الواجهة الحالية.

يتحقق أن العزل يعمل بلا موديلات مثبتة (مسار احتياطي)، وأن قناع الشفافية
يعطي إطارًا منطقيًا، وأن التركيب على خلفية بيضاء ينتج صورة سليمة الأبعاد.
"""
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine_v2.segmentation_v2 import ProductSegmenterV2

PASS, FAIL = [], []


def check(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name +
          (f" — {note}" if note else ""))


SRC = Path("/home/ubuntu/upload/3988D8E6-BF91-4876-9438-C7D2E931A303.jpeg")
if not SRC.is_file():
    print("لا توجد صورة اختبار — شغّل tests/make_test_assets.py أولًا")
    sys.exit(1)

image = cv2.imread(str(SRC))
check("read_input", image is not None and image.ndim == 3,
      str(None if image is None else image.shape))

seg = ProductSegmenterV2(ROOT / "models_v2")
t0 = time.time()
res = seg.segment(image)
dt = time.time() - t0
check("segment_runs", res is not None and res.alpha is not None,
      f"{dt:.2f}s model={res.model_name} conf={res.confidence:.3f}")
check("alpha_shape", res.alpha.shape[:2] == image.shape[:2],
      str(res.alpha.shape))
# المحرك يعيد قناعًا float32 بمدى 0..1 (لا uint8) ليدعم الحواف الناعمة
check("alpha_dtype", res.alpha.dtype == np.float32, str(res.alpha.dtype))
check("alpha_range", 0.0 <= float(res.alpha.min())
      and float(res.alpha.max()) <= 1.0,
      f"{float(res.alpha.min()):.2f}..{float(res.alpha.max()):.2f}")

# القناع ليس فارغًا ولا يغطي كل الصورة (منتج حقيقي معزول)
cover = float((res.alpha > 0.03).mean())
check("alpha_coverage", 0.01 < cover < 0.999, f"{cover:.3f}")
check("segment_confidence", res.confidence > 0.5, f"{res.confidence:.3f}")

bbox = seg.alpha_bbox(res.alpha)
check("alpha_bbox", bbox is not None and bbox[2] > bbox[0]
      and bbox[3] > bbox[1], str(bbox))

composed = seg.compose_on_white(image, res.alpha)
check("compose_shape", composed.shape == image.shape, str(composed.shape))
check("compose_white_corner",
      bool((composed[0, 0] > 200).all()), str(composed[0, 0]))

decon = seg.decontaminate(image, res.alpha)
check("decontaminate", decon is not None
      and decon.shape[:2] == image.shape[:2],
      str(None if decon is None else decon.shape))

print(f"\n===== {len(PASS)} passed / {len(FAIL)} failed =====")
if FAIL:
    print("FAILED:", FAIL)
sys.exit(0 if not FAIL else 1)
