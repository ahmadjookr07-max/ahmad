# -*- coding: utf-8 -*-
"""اختبار الظل على منتج واحد (صورة webp معالجة بخلفية بيضاء)."""
import sys, os
sys.path.insert(0, "/home/ubuntu/v2_project/app_v2/src")
import numpy as np
import cv2
from PIL import Image
from engine_v2.shadow_v2 import apply_shadow_on_white, SHADOW_PRESETS

OUT = "/home/ubuntu/v2_project/v2_out/shadow_single"
os.makedirs(OUT, exist_ok=True)

src = "/home/ubuntu/v2_project/old_results/processed/10000001_حبه.webp"
img = np.array(Image.open(src).convert("RGB"))[:, :, ::-1].copy()  # BGR

# استخراج alpha من الخلفية البيضاء (المنتج على أبيض نقي)
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
_, mask = cv2.threshold(gray, 246, 255, cv2.THRESH_BINARY_INV)
mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
# أكبر مكون
n, lab, stats, _ = cv2.connectedComponentsWithStats(mask)
if n > 1:
    biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    mask = np.where(lab == biggest, 255, 0).astype(np.uint8)
mask = cv2.GaussianBlur(mask, (5, 5), 0)

rgba = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
rgba[:, :, 3] = mask

# إضافة هامش سفلي للظل
rgba = cv2.copyMakeBorder(rgba, 20, 60, 60, 60, cv2.BORDER_CONSTANT, value=(0, 0, 0, 0))

thumbs = []
for name, opts in SHADOW_PRESETS.items():
    out = apply_shadow_on_white(rgba, opts)
    cv2.imwrite(os.path.join(OUT, f"{name}.png"), out)
    thumbs.append((name, out))

# شبكة
w = 380
ims = []
for name, out in thumbs:
    im = Image.fromarray(out[:, :, ::-1])
    im = im.resize((w, int(im.height * w / im.width)))
    ims.append(im)
h = max(im.height for im in ims)
grid = Image.new("RGB", (w * 3 + 40, h * 2 + 30), (215, 215, 222))
for i, im in enumerate(ims):
    grid.paste(im, ((i % 3) * (w + 10) + 10, (i // 3) * (h + 10) + 10))
grid.save(os.path.join(OUT, "grid.png"))
print("DONE", grid.size)
