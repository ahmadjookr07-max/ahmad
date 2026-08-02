# -*- coding: utf-8 -*-
"""اختبار المعالج ProcessorV2 من طرف إلى طرف على الواجهة الحالية."""
import sys
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine_v2.processor_v2 import ProcessOptionsV2, ProcessorV2

PASS, FAIL = [], []


def check(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name +
          (f" — {note}" if note else ""))


SRC = Path("/home/ubuntu/upload/3988D8E6-BF91-4876-9438-C7D2E931A303.jpeg")
if not SRC.is_file():
    print("لا توجد صورة اختبار — شغّل tests/make_test_assets.py أولًا")
    sys.exit(1)

OUT = Path(tempfile.mkdtemp(prefix="mis_proc_"))
MODELS = ROOT / "models_v2"
proc = ProcessorV2(MODELS)

# 1) المسار الكامل: عزل + تحسين + مقاس المنصة
out1 = OUT / "10001234_حبه.webp"
t0 = time.time()
r1 = proc.process(SRC, out1, ProcessOptionsV2())
dt1 = time.time() - t0
check("process_runs", r1 is not None, f"{dt1:.2f}s warn={r1.warnings}")
check("output_created", out1.is_file(), f"{out1.stat().st_size // 1024} KB"
      if out1.is_file() else "مفقود")

img = cv2.imdecode(np.fromfile(str(out1), np.uint8), cv2.IMREAD_UNCHANGED) \
    if out1.is_file() else None
opts_default = ProcessOptionsV2()
check("output_size",
      img is not None
      and img.shape[1] == opts_default.width
      and img.shape[0] == opts_default.height,
      str(None if img is None else img.shape))
check("output_white_bg",
      img is not None and bool((img[2, 2][:3] > 200).all()),
      str(None if img is None else img[2, 2]))

# 2) مقاس مخصص يُحترم
out2 = OUT / "custom.webp"
r2 = proc.process(SRC, out2, ProcessOptionsV2(width=1000, height=1000,
                                              margin=40))
img2 = cv2.imdecode(np.fromfile(str(out2), np.uint8), cv2.IMREAD_UNCHANGED) \
    if out2.is_file() else None
check("custom_size", img2 is not None and img2.shape[:2] == (1000, 1000),
      str(None if img2 is None else img2.shape))

# 3) بلا تحسين: ينتج مخرجًا صالحًا أيضًا
out3 = OUT / "noenh.webp"
r3 = proc.process(SRC, out3, ProcessOptionsV2(enhance=False))
check("no_enhance", out3.is_file(), str(r3.warnings))

# 4) تدوير يدوي يُطبق دون كسر
out4 = OUT / "rot.webp"
r4 = proc.process(SRC, out4, ProcessOptionsV2(manual_rotation_degrees=7.5))
check("manual_rotation", out4.is_file(), str(r4.warnings))

# 5) WebP بلا فقدان اختياريًا
out5 = OUT / "lossless.webp"
proc.process(SRC, out5, ProcessOptionsV2(webp_lossless=True))
check("webp_lossless_opt", out5.is_file(),
      f"{out5.stat().st_size // 1024} KB" if out5.is_file() else "مفقود")

print(f"\n===== {len(PASS)} passed / {len(FAIL)} failed =====")
print("out dir:", OUT)
if FAIL:
    print("FAILED:", FAIL)
sys.exit(0 if not FAIL else 1)
