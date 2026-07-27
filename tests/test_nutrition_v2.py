"""Test nutrition OCR extraction + Arabic table re-rendering (rebuild mode)."""
import sys, time
sys.path.insert(0, "/home/ubuntu/v2_project/v2")

import cv2
from engine_v2.nutrition_ocr_v2 import extract_nutrition_data, blank_template
from engine_v2.nutrition_render_v2 import render_nutrition_table
from engine_v2.nutrition_v2 import detect_nutrition_table, crop_region, merge_label_inset, InsetPlacement, render_standalone_label

SRC = "/home/ubuntu/upload/IMG_4816.jpeg"  # clear nutrition label screenshot
OUT = "/home/ubuntu/v2_project/v2_out"

img = cv2.imread(SRC)
print("src:", img.shape)

# 1) detect + crop
t0 = time.time()
region = detect_nutrition_table(img)
print(f"detect: {time.time()-t0:.2f}s region={region.bbox_normalized if region else None} conf={region.confidence if region else 0:.2f}")
bbox = region.bbox_normalized if region else (0.05, 0.25, 0.95, 0.75)
crop = crop_region(img, bbox)
cv2.imwrite(f"{OUT}/nut_crop.png", crop)

# 2) OCR extraction
t0 = time.time()
data = extract_nutrition_data(crop)
print(f"ocr: {time.time()-t0:.2f}s conf={data.ocr_confidence:.2f} servings={data.servings_per_container!r} size={data.serving_size!r} cal={data.calories!r}")
for r in data.rows:
    print(f"  {r.key}: amount={r.amount!r} dv={r.daily_value!r}")

# 3) rebuild render
if not data.rows:
    print("OCR found no rows; using blank template with sample values")
    data = blank_template()
    data.calories = "230"
t0 = time.time()
table = render_nutrition_table(data)
print(f"render: {time.time()-t0:.2f}s -> {table.shape}")
cv2.imwrite(f"{OUT}/nut_rebuilt.png", table)

# 4) placement variants
canvas = cv2.imread(f"{OUT}/10001234_حبه.webp")
if canvas is not None:
    for anchor in ("bottom_left", "bottom_right", "free"):
        p = InsetPlacement(anchor=anchor, scale=0.28,
                           offset_x=0.35 if anchor == "free" else 0.0,
                           offset_y=0.05 if anchor == "free" else 0.0)
        merged = merge_label_inset(canvas, crop, p)
        cv2.imwrite(f"{OUT}/nut_inset_{anchor}.png", merged)
    print("insets done")

standalone = render_standalone_label(img, bbox, align="center")
cv2.imwrite(f"{OUT}/nut_standalone.png", standalone)
print("done")
