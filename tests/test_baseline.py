"""Reproduce baseline processing quality of the 1.2.1 engine on a sample image.

Uses FinalImageProcessor directly with the bundled U2Net models.
"""
import sys, time
from pathlib import Path

sys.path.insert(0, "/home/ubuntu/v2_project/src_121/smart_image_matcher/src")
from smart_catalog_vision.final_images import FinalImageOptions, FinalImageProcessor

MODEL_DIR = Path("/home/ubuntu/v2_project/src_121/smart_image_matcher/resources/models")
print("models:", [p.name for p in MODEL_DIR.glob("*")])

out = Path("/home/ubuntu/v2_project/baseline_out")
out.mkdir(exist_ok=True)

# Use one of the user's screenshots that contains a real product photo as test input
# Better: extract a test image from the project's fixtures if any
fixtures = list(Path("/home/ubuntu/v2_project/src_121/smart_image_matcher/tests").rglob("*.jpg")) + \
           list(Path("/home/ubuntu/v2_project/src_121/smart_image_matcher/tests").rglob("*.png")) + \
           list(Path("/home/ubuntu/v2_project/src_121/smart_image_matcher/analysis_output").rglob("*.jpg"))[:5]
print("fixtures found:", [str(f) for f in fixtures[:10]])

src = fixtures[0] if fixtures else Path("/home/ubuntu/upload/3988D8E6-BF91-4876-9438-C7D2E931A303.jpeg")
print("using source:", src)

proc = FinalImageProcessor(FinalImageOptions(), model_dir=MODEL_DIR)
t0 = time.time()
res = proc.process(src, out, item_number="TEST001", unit="حبه", product_name="اختبار", overwrite=True)
print("elapsed:", round(time.time() - t0, 2), "s")
print("result:", res)
