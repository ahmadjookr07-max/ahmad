# -*- coding: utf-8 -*-
"""اختبار shadow_v2 على صورة منتج حقيقية بعد إزالة الخلفية."""
import sys, os, time
sys.path.insert(0, "/home/ubuntu/v2_project/app_v2/src")

import numpy as np
import cv2
from engine_v2.shadow_v2 import ShadowOptions, apply_shadow_on_white, SHADOW_PRESETS
from engine_v2.segmentation_v2 import ProductSegmenterV2

OUT = "/home/ubuntu/v2_project/v2_out/shadow_test"
os.makedirs(OUT, exist_ok=True)

# ابحث عن صورة عينة
candidates = [
    "/home/ubuntu/upload/3988D8E6-3B54-42D2-8E63-9CF97DF06CE8.jpeg",
    "/home/ubuntu/upload/7B13D871-C387-44D2-A5B2-93FBE761F7BC.jpeg",
]
src_path = None
for c in candidates:
    if os.path.exists(c):
        src_path = c
        break
if src_path is None:
    import glob
    imgs = glob.glob("/home/ubuntu/upload/*.jpeg") + glob.glob("/home/ubuntu/upload/*.jpg")
    imgs = [p for p in imgs if "IMG_48" not in p] or imgs
    src_path = imgs[0]
print("source:", src_path)

img = cv2.imread(src_path)
seg = ProductSegmenterV2("/home/ubuntu/v2_project/models_v2")
t0 = time.time()
res = seg.segment(img)
alpha = (np.clip(res.alpha, 0, 1) * 255).astype(np.uint8)
rgba = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
rgba[:, :, 3] = alpha
print(f"segmentation: {time.time()-t0:.2f}s, shape={rgba.shape}")

# اقتصاص حول المنتج مع هامش
a = rgba[:, :, 3]
ys, xs = np.where(a > 10)
x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
pad = int(0.12 * max(x1 - x0, y1 - y0))
h, w = rgba.shape[:2]
crop = rgba[max(0, y0 - pad):min(h, y1 + pad), max(0, x0 - pad):min(w, x1 + pad)]

for name, opts in SHADOW_PRESETS.items():
    t0 = time.time()
    out = apply_shadow_on_white(crop, opts)
    fn = os.path.join(OUT, f"{name}.png")
    cv2.imwrite(fn, out)
    print(f"{name}: {time.time()-t0:.3f}s -> {fn}")

print("DONE")
