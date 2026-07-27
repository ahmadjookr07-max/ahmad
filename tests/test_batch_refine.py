# -*- coding: utf-8 -*-
"""اختبار BatchRefiner على عينة من الصور القديمة + قياس السرعة والتوازي."""
import os, sys, time, shutil, glob

sys.path.insert(0, "/home/ubuntu/v2_project/app_v2/src")

from engine_v2.batch_refine_v2 import BatchRefiner, RefineOptions

SAMPLE_DIR = "/home/ubuntu/v2_project/v2_out/batch_refine_sample_src"
OUT_DIR = "/home/ubuntu/v2_project/v2_out/batch_refine_sample_out"
EXCEL = None
# ابحث عن ملف الإكسل الأساسي
for cand in glob.glob("/home/ubuntu/upload/*.xlsx") + glob.glob("/home/ubuntu/v2_project/**/*.xlsx", recursive=True):
    if "أصناف" in cand or "اصناف" in cand or "items" in cand.lower() or True:
        EXCEL = cand
        break
print("excel:", EXCEL)

# جهز عينة اصطناعية 24 صورة بأسماء قديمة (legacy) وأكواد حقيقية من الإكسل
import cv2
import numpy as np

sys.path.insert(0, "/home/ubuntu/v2_project/app_v2/src")
from engine_v2.catalog_index_v2 import CatalogIndex

idx = CatalogIndex()
idx.load_excel(EXCEL)
codes = list(dict.fromkeys(r["code"] for r in idx.rows[50:80]))[:12]

shutil.rmtree(SAMPLE_DIR, ignore_errors=True)
shutil.rmtree(OUT_DIR, ignore_errors=True)
os.makedirs(SAMPLE_DIR, exist_ok=True)

rng = np.random.default_rng(7)
files = []
for gi, code in enumerate(codes):
    for seq in (1, 2):
        # منتج بسيط: علبة ملونة على خلفية فاتحة
        img = np.full((760, 820, 3), 240, np.uint8)
        c = tuple(int(v) for v in rng.integers(30, 200, 3))
        cv2.rectangle(img, (250, 160), (570, 620), c, -1)
        cv2.rectangle(img, (290, 260), (530, 420), (250, 250, 250), -1)
        cv2.putText(img, f"P{gi}", (330, 370), cv2.FONT_HERSHEY_SIMPLEX,
                    2.2, (20, 20, 20), 5)
        # نمط التسمية القديم legacy + وحدة خاطئة لبعضها
        unit = "حبه" if gi % 4 else "باكتوو"  # وحدة غير موجودة لاختبار التصحيح
        stem = f"{code}_{unit}" if seq == 1 else f"{code}_{unit}_{seq}"
        name = stem + ".webp"
        ok, buf = cv2.imencode(".webp", img, [cv2.IMWRITE_WEBP_QUALITY, 90])
        buf.tofile(os.path.join(SAMPLE_DIR, name))
        files.append(name)
print("sample files:", len(files))

opts = RefineOptions(recut=True, enhance=True, frame=True,
                     shadow_preset="", fix_names=True,
                     excel_path=EXCEL or "", workers=2)
refiner = BatchRefiner("/home/ubuntu/v2_project/models_v2", opts)

t0 = time.time()
prog = []

def on_progress(i, total, r):
    prog.append((i, total, r.status))
    if i % 6 == 0 or i == total:
        print(f"  {i}/{total}  {r.status}  {os.path.basename(r.source)} -> {r.new_name}  {r.name_note}")

results = refiner.run(SAMPLE_DIR, OUT_DIR, progress=on_progress)
el = time.time() - t0

done = [r for r in results if r.status == "done"]
err = [r for r in results if r.status == "error"]
print(f"\ntotal={len(results)} done={len(done)} err={len(err)} elapsed={el:.1f}s "
      f"({el/max(1,len(done)):.2f}s/img)")
for r in err[:5]:
    print("ERR:", r.source, r.error)

# اختبار الاستئناف: تشغيل ثانٍ يجب أن يتخطى الكل
t1 = time.time()
results2 = refiner.run(SAMPLE_DIR, OUT_DIR, progress=None)
skipped = sum(1 for r in results2 if r.status == "skipped")
print(f"resume: skipped={skipped}/{len(results2)} in {time.time()-t1:.2f}s")

# تحقق من الأبعاد
outs = [f for f in os.listdir(OUT_DIR) if f.endswith(".webp")]
img = cv2.imdecode(np.fromfile(os.path.join(OUT_DIR, outs[0]), np.uint8), cv2.IMREAD_COLOR)
print("first output:", outs[0], img.shape)

ok = len(err) == 0 and len(done) == len(files) and skipped == len(results2) \
    and img.shape[0] == 700 and img.shape[1] == 800
print("BATCH REFINE:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
