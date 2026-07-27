"""End-to-end test of nutrition rebuild mode through ProcessorV2."""
import sys
sys.path.insert(0, "/home/ubuntu/v2_project/v2")

from engine_v2.processor_v2 import ProcessorV2, ProcessOptionsV2

opts = ProcessOptionsV2(
    nutrition_mode="rebuild",
    nutrition_source_path="/home/ubuntu/upload/IMG_4816.jpeg",
)
proc = ProcessorV2("/home/ubuntu/v2_project/models_v2", opts)
res = proc.process(
    "/home/ubuntu/upload/3988D8E6-BF91-4876-9438-C7D2E931A303.jpeg",
    "/home/ubuntu/v2_project/v2_out/rebuild/10009999_حبه.webp",
)
print("output:", res.output_path)
print("nutrition:", res.nutrition_output_path)
print("model:", res.model_name, "conf:", f"{res.confidence:.2f}")
print("warnings:", res.warnings)

import os
nut_dir = "/home/ubuntu/v2_project/v2_out/rebuild/حقائق التغذية"
if os.path.isdir(nut_dir):
    print("nut_dir:", os.listdir(nut_dir))
