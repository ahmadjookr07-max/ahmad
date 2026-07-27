import sys, os, shutil
sys.path.insert(0, "/home/ubuntu/v2_project/app_v2/src")

from engine_v2.integration_v2 import activate, set_override
ok = activate()
print("activate:", ok)
assert ok

from smart_catalog_vision.pipeline import FinalImageProcessor, FinalImageOptions

out_dir = "/home/ubuntu/v2_project/v2_out/integration"
if os.path.isdir(out_dir):
    shutil.rmtree(out_dir)

proc = FinalImageProcessor(FinalImageOptions())
src = "/home/ubuntu/upload/3988D8E6-BF91-4876-9438-C7D2E931A303.jpeg"

# first image of the item
r1 = proc.process(src, out_dir, item_number="10018435", unit="حبه")
print("r1:", getattr(r1, "output_path", r1))

# second image of the same item -> must get _2_
r2 = proc.process(src, out_dir, item_number="10018435", unit="حبه")
print("r2:", getattr(r2, "output_path", r2))

# third
r3 = proc.process(src, out_dir, item_number="10018435", unit="حبه")
print("r3:", getattr(r3, "output_path", r3))

names = sorted(os.listdir(out_dir))
print("files:", names)
assert "10018435_حبه.webp" in names
assert "10018435_2_حبه.webp" in names
assert "10018435_3_حبه.webp" in names
print("INTEGRATION OK")
