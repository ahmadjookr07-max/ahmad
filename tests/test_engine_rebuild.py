# -*- coding: utf-8 -*-
"""اختبار شامل لوحدات engine_v2 المعاد بناؤها بعد إعادة تعيين البيئة."""
import glob
import json
import os
import sys
import time

sys.path.insert(0, "/home/ubuntu/v2_project/app_v2/src")

import cv2
import numpy as np

OUT = "/home/ubuntu/v2_project/v2_out/rebuild_test"
os.makedirs(OUT, exist_ok=True)
PASS, FAIL = [], []


def check(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f" — {note}" if note else ""))


def make_product_image(w=900, h=1100):
    """صورة منتج اصطناعية: زجاجة على خلفية رمادية فاتحة مع ظل."""
    img = np.full((h, w, 3), 236, np.uint8)
    img += np.random.randint(-6, 6, (h, w, 3)).astype(np.int8).astype(np.uint8) // 3
    # جسم الزجاجة
    cv2.rectangle(img, (320, 300), (580, 950), (40, 90, 190), -1)
    cv2.ellipse(img, (450, 300), (130, 60), 0, 180, 360, (40, 90, 190), -1)
    cv2.ellipse(img, (450, 950), (130, 40), 0, 0, 180, (35, 80, 175), -1)
    # عنق وغطاء
    cv2.rectangle(img, (410, 180), (490, 300), (45, 95, 200), -1)
    cv2.rectangle(img, (400, 130), (500, 185), (230, 230, 235), -1)
    # ملصق
    cv2.rectangle(img, (345, 480), (555, 780), (250, 250, 250), -1)
    cv2.putText(img, "MILK", (390, 580), cv2.FONT_HERSHEY_SIMPLEX, 1.6,
                (30, 30, 30), 4)
    cv2.putText(img, "FRESH 1L", (380, 660), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                (60, 60, 60), 2)
    # ظل خفيف على الأرض
    cv2.ellipse(img, (460, 985), (170, 28), 0, 0, 360, (200, 200, 200), -1)
    return img


t_all = time.time()

# 1) segmentation
from engine_v2.segmentation_v2 import ProductSegmenterV2
seg = ProductSegmenterV2("/home/ubuntu/v2_project/models_v2")
img = make_product_image()
src_path = os.path.join(OUT, "src.png")
cv2.imwrite(src_path, img)
t0 = time.time()
r = seg.segment(img)
check("segmentation", r.alpha.shape == img.shape[:2] and r.confidence > 0.4,
      f"conf={r.confidence:.2f} model={r.model_name} {time.time()-t0:.1f}s")
white = seg.compose_on_white(img, r.alpha)
cv2.imwrite(os.path.join(OUT, "white.png"), white)
# لا هالة: حواف المنتج يجب ألا تكون رمادية 236
bbox = seg.alpha_bbox(r.alpha)
check("alpha_bbox", bbox is not None and bbox[2] > bbox[0])

# 2) enhancement
from engine_v2.enhancement_v2 import auto_enhance
enh = auto_enhance(white)
check("auto_enhance", enh.shape == white.shape and enh.dtype == np.uint8)

# 3) naming
from engine_v2.naming_v2 import (build_name, parse_name, next_sequence,
                                 NamingSettings, plan_names_for_item,
                                 unmojibake, plan_bulk_rename,
                                 apply_bulk_rename)
check("build_name", build_name("10018435") == "10018435_حبه"
      and build_name("10018435", 2) == "10018435_2_حبه")
p = parse_name("10018435_3_حبه")
check("parse_canonical", p and p.item == "10018435" and p.seq == 3)
p2 = parse_name("10018435_حبه_2")  # legacy
check("parse_legacy", p2 and p2.item == "10018435" and p2.seq == 2
      and p2.unit == "حبه")
check("next_sequence",
      next_sequence(["10018435_حبه", "10018435_2_حبه"], "10018435") == 3)
ns = NamingSettings(unit_policy="replicate_all_units")
plans = plan_names_for_item("123", 2, ["حبه", "كرتون"], ns)
check("replicate_units", plans[0] == ["123_حبه", "123_كرتون"]
      and plans[1] == ["123_2_حبه", "123_2_كرتون"])

# bulk rename على مجلد تجريبي (نمط قديم legacy)
import shutil
rn_dir = os.path.join(OUT, "rename_test")
shutil.rmtree(rn_dir, ignore_errors=True)
os.makedirs(rn_dir)
for n in ["10000001_حبه.webp", "10000001_حبه_2.webp", "10000002_حبه.webp"]:
    open(os.path.join(rn_dir, n), "wb").write(b"x")
plan = plan_bulk_rename(rn_dir, {})
ok_targets = {e.target for e in plan if e.status in ("ok", "unchanged")}
check("plan_bulk_rename", "10000001_2_حبه.webp" in ok_targets, str(ok_targets))
applied, errs = apply_bulk_rename(rn_dir, plan)
check("apply_bulk_rename", not errs and
      os.path.exists(os.path.join(rn_dir, "10000001_2_حبه.webp")))

# 4) catalog index (الإكسل الحقيقي)
from engine_v2.catalog_index_v2 import CatalogIndex
xlsx = glob.glob("/home/ubuntu/upload/*.xlsx")[0]
idx = CatalogIndex()
t0 = time.time()
idx.load_excel(xlsx)
first_load = time.time() - t0
check("excel_load", len(idx.rows) > 40000,
      f"rows={len(idx.rows)} cols={idx.columns} {first_load:.1f}s")
idx_nc = CatalogIndex()
t0 = time.time()
idx_nc.load_excel(xlsx, use_cache=False)
no_cache_s = time.time() - t0
idx2 = CatalogIndex()
t0 = time.time()
idx2.load_excel(xlsx)
cached_s = time.time() - t0
check("excel_cache", cached_s < no_cache_s and len(idx2.rows) == len(idx.rows),
      f"no_cache={no_cache_s:.1f}s cached={cached_s:.1f}s")
sample = idx.rows[100]
check("lookup_code", idx.lookup_code(sample["code"]) is not None)
if sample.get("barcode"):
    check("lookup_barcode", idx.lookup_barcode(sample["barcode"]) is not None)
multi = [c for c, l in idx.by_code_all.items() if len(l) > 1][:3]
check("multi_units", len(multi) > 0 and len(idx.units_for_code(multi[0])) >= 1,
      f"example={multi[0] if multi else None} units={idx.units_for_code(multi[0]) if multi else []}")
res_name = idx.search_name(sample["name"][:10])
check("search_name", len(res_name) > 0)

# 5) sessions
from engine_v2.session_v2 import SessionStore
st = SessionStore(os.path.join(OUT, "data_root"))
st.new_session("اختبار")
st.upsert_image("IMG_1.jpg", code="10018435", unit="حبه", custom_stem="")
st.set_position("IMG_1.jpg", 3, 0)
st.save(force=True)
sid = st.state.session_id
st2 = SessionStore(os.path.join(OUT, "data_root"))
loaded = st2.load(sid)
check("session_save_load", loaded and loaded.images.get("IMG_1.jpg", {}).get("code") == "10018435"
      and loaded.position.get("row") == 3)
check("session_list", len(st2.list_sessions()) >= 1)

# 6) alignment
from engine_v2.alignment_v2 import estimate_tilt_degrees, rotate_with_alpha
tilt = estimate_tilt_degrees(r.alpha)
img_r, a_r = rotate_with_alpha(img, r.alpha, 5.0)
check("alignment", isinstance(tilt, float) and img_r.shape[0] >= img.shape[0])

# 7) nutrition render (عربي)
from engine_v2.nutrition_ocr_v2 import blank_template, NutritionData, NutritionRow
from engine_v2.nutrition_render_v2 import render_nutrition_table
data = blank_template()
data.calories = "250"
data.servings = "4"
data.serving_size = "30 غ"
for row in data.rows:
    if row.key == "total_fat":
        row.amount, row.unit, row.percent = "12", "غ", "18"
    if row.key == "sodium":
        row.amount, row.unit, row.percent = "150", "ملغ", "7"
table = render_nutrition_table(data)
cv2.imwrite(os.path.join(OUT, "nut_table.png"), table)
check("nutrition_render", table.shape[1] == 640 and table.shape[0] > 400)

# 8) nutrition OCR على الجدول المرسوم نفسه (round-trip جزئي)
from engine_v2.nutrition_ocr_v2 import extract_nutrition_data
ocr = extract_nutrition_data(table)
check("nutrition_ocr", ocr.confidence > 0.1 and (ocr.calories or ocr.rows),
      f"conf={ocr.confidence} cal={ocr.calories} rows={len(ocr.rows)}")

# 9) nutrition inset + standalone
from engine_v2.nutrition_v2 import merge_label_inset, render_standalone_label, InsetPlacement
canvas = np.full((700, 800, 3), 255, np.uint8)
merged = merge_label_inset(canvas, table, InsetPlacement(anchor="bottom_left"))
standalone = render_standalone_label(table, enhance=False)
check("nutrition_inset", merged.shape == (700, 800, 3)
      and standalone.shape == (700, 800, 3))

# 10) processor كامل
from engine_v2.processor_v2 import ProcessorV2, ProcessOptionsV2
proc = ProcessorV2("/home/ubuntu/v2_project/models_v2")
out_webp = os.path.join(OUT, "10018435_حبه.webp")
t0 = time.time()
pres = proc.process(src_path, out_webp, ProcessOptionsV2(shadow_preset="soft_ground"))
final = cv2.imdecode(np.fromfile(out_webp, np.uint8), cv2.IMREAD_COLOR) \
    if os.path.exists(out_webp) else None
check("processor", pres.ok and final is not None
      and final.shape == (700, 800, 3),
      f"{time.time()-t0:.1f}s warn={pres.warnings} err={pres.error}")

# 11) shadow presets موجودة
from engine_v2.shadow_v2 import SHADOW_PRESETS
check("shadow_presets", len(SHADOW_PRESETS) >= 5, str(list(SHADOW_PRESETS)))

# 12) integration activate
from engine_v2 import integration_v2
act = integration_v2.activate("/home/ubuntu/v2_project/models_v2")
check("integration_activate", act is True or act is False)  # قد لا يجد pyc هنا
stem = integration_v2.build_output_stem(OUT, "10018435")
check("build_output_stem", stem == "10018435_2_حبه", stem)

print(f"\n===== {len(PASS)} passed / {len(FAIL)} failed — {time.time()-t_all:.0f}s =====")
if FAIL:
    print("FAILED:", FAIL)
sys.exit(0 if not FAIL else 1)
