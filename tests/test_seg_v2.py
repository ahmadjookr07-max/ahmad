"""Compare V2 segmentation (ISNet / BiRefNet) against 1.2.1 baseline output."""
import sys, time
from pathlib import Path
import cv2
import numpy as np

sys.path.insert(0, "/home/ubuntu/v2_project/v2")
from engine_v2.segmentation_v2 import ProductSegmenterV2, alpha_bbox

SRC = Path("/home/ubuntu/upload/3988D8E6-BF91-4876-9438-C7D2E931A303.jpeg")
OUT = Path("/home/ubuntu/v2_project/seg_compare")
OUT.mkdir(exist_ok=True)

image = cv2.imread(str(SRC))
print("input:", image.shape)

seg = ProductSegmenterV2("/home/ubuntu/v2_project/models_v2")
for model in ["isnet", "birefnet"]:
    t0 = time.time()
    try:
        res = seg.segment(image, model=model)
    except Exception as e:
        print(model, "FAILED:", e)
        continue
    dt = time.time() - t0
    composed = seg.compose_on_white(image, res.alpha)
    bbox = alpha_bbox(res.alpha)
    if bbox:
        x0, y0, x1, y1 = bbox
        pad = 20
        x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
        x1, y1 = min(image.shape[1], x1 + pad), min(image.shape[0], y1 + pad)
        crop = composed[y0:y1, x0:x1]
    else:
        crop = composed
    # fit into 800x700 canvas with margins like the old engine
    canvas = np.full((700, 800, 3), 255, np.uint8)
    ch, cw = crop.shape[:2]
    scale = min((800 - 96) / cw, (700 - 80) / ch)
    nw, nh = int(cw * scale), int(ch * scale)
    resized = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
    ox, oy = (800 - nw) // 2, (700 - nh) // 2
    canvas[oy:oy + nh, ox:ox + nw] = resized
    out_path = OUT / f"result_{model}.png"
    cv2.imwrite(str(out_path), canvas)
    print(f"{model}: {dt:.2f}s conf={res.confidence:.3f} -> {out_path}")
