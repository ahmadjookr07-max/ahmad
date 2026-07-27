"""End-to-end test of ProcessorV2 on user's sample images."""
import sys, time
from pathlib import Path

sys.path.insert(0, "/home/ubuntu/v2_project/v2")
from engine_v2.processor_v2 import ProcessorV2, ProcessOptionsV2
from engine_v2.enhancement_v2 import EnhanceSettings

OUT = Path("/home/ubuntu/v2_project/v2_out")
OUT.mkdir(exist_ok=True)
MODELS = "/home/ubuntu/v2_project/models_v2"

# 1) product front photo (screenshot of kefir bottle)
opts = ProcessOptionsV2(enhance_settings=EnhanceSettings(strength=55, descreen=True))
proc = ProcessorV2(MODELS, opts)
t0 = time.time()
r1 = proc.process("/home/ubuntu/upload/3988D8E6-BF91-4876-9438-C7D2E931A303.jpeg",
                  OUT / "10001234_حبه.webp")
print(f"product: {time.time()-t0:.2f}s model={r1.model_name} conf={r1.confidence:.3f} rot={r1.applied_rotation:.2f} warn={r1.warnings}")

# 2) nutrition standalone from back-side photo (IMG_4816 has clear table)
opts2 = ProcessOptionsV2(remove_background=False, enhance=False,
                         nutrition_mode="standalone")
proc2 = ProcessorV2(MODELS, opts2)
t0 = time.time()
r2 = proc2.process("/home/ubuntu/upload/IMG_4816.jpeg", OUT / "10001043_حبه.webp")
print(f"nutrition standalone: {time.time()-t0:.2f}s -> {r2.nutrition_output_path} warn={r2.warnings}")

# 3) merge_small: product with nutrition inset (use bottle image for both as demo)
opts3 = ProcessOptionsV2(enhance_settings=EnhanceSettings(strength=55, descreen=True),
                         nutrition_mode="merge_small")
proc3 = ProcessorV2(MODELS, opts3)
t0 = time.time()
r3 = proc3.process("/home/ubuntu/upload/IMG_4816.jpeg", OUT / "10001043_2_حبه.webp")
print(f"merge_small: {time.time()-t0:.2f}s warn={r3.warnings}")
