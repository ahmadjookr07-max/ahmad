"""Tests: unified naming, bulk-rename plan on real old results, instant catalog."""
import sys, time, shutil, os
sys.path.insert(0, "/home/ubuntu/v2_project/v2")

from engine_v2.naming_v2 import (build_name, parse_name, next_sequence,
                                 plan_group_names, plan_bulk_rename,
                                 apply_bulk_rename)
from engine_v2.catalog_index_v2 import CatalogIndex

# ---- naming unit tests
assert build_name("10018435") == "10018435_حبه"
assert build_name("10018435", 2) == "10018435_2_حبه"
assert build_name("10018435", 4) == "10018435_4_حبه"
p = parse_name("10018435_3_حبه"); assert p.item == "10018435" and p.seq == 3
p = parse_name("10018435_حبه"); assert p.item == "10018435" and p.seq == 1
assert parse_name("random-file") is None
stems = ["10018435_حبه", "10018435_2_حبه", "10018435_4_حبه"]
assert next_sequence(stems, "10018435") == 3
assert next_sequence(stems, "999") == 1
assert plan_group_names("77", 3) == ["77_حبه", "77_2_حبه", "77_3_حبه"]
print("naming OK")

# ---- bulk rename on a copy of the real old results
SRC = "/home/ubuntu/v2_project/old_results/processed"
WORK = "/home/ubuntu/v2_project/tmp_rename_test"
if os.path.isdir(WORK):
    shutil.rmtree(WORK)
files = sorted(os.listdir(SRC))[:60]
os.makedirs(WORK)
for f in files:
    shutil.copy2(os.path.join(SRC, f), WORK)

# build a mapping: rename two known items
items = set()
for f in files:
    pr = parse_name(os.path.splitext(f)[0])
    if pr:
        items.add(pr.item)
items = sorted(items)
mapping = {items[0]: "20000001", items[1]: "20000002"}
print("mapping:", mapping)

t0 = time.time()
plan = plan_bulk_rename(WORK, mapping)
ok = [e for e in plan if e.status == "ok"]
print(f"plan: {len(plan)} entries, ok={len(ok)}, "
      f"unparsed={sum(1 for e in plan if e.status=='unparsed')}, "
      f"conflict={sum(1 for e in plan if e.status=='conflict')}, "
      f"{time.time()-t0:.3f}s")
for e in ok[:6]:
    print("  ", e.source, "->", e.target)
count, errors = apply_bulk_rename(WORK, plan)
print(f"applied: {count}, errors: {errors}")
# verify grouped links preserved
renamed = sorted(f for f in os.listdir(WORK) if f.startswith("20000001"))
print("group 20000001:", renamed)

# ---- catalog instant index on the real 42k excel
XLSX = [f"/home/ubuntu/upload/{f}" for f in os.listdir("/home/ubuntu/upload") if f.endswith(".xlsx")][0]
cat = CatalogIndex()
t = cat.load_excel(XLSX, use_cache=False)
print(f"excel load (no cache): {t:.2f}s, items={len(cat.items)}")
t = cat.load_excel(XLSX, use_cache=True)   # writes cache on previous call? no—write happens in load; call again
t = cat.load_excel(XLSX, use_cache=True)
print(f"excel load (cache): {t:.2f}s")

t0 = time.time()
hit = cat.lookup_barcode("6281011421419")
t1 = (time.time() - t0) * 1000
print(f"barcode lookup: {t1:.2f}ms -> {hit.item_code if hit else None} {hit.name[:30] if hit else ''}")

t0 = time.time()
res = cat.search_name("زيت زيتون")
t1 = (time.time() - t0) * 1000
print(f"name search 'زيت زيتون': {t1:.1f}ms, {len(res)} hits")
for r in res[:5]:
    print("  ", r.item_code, r.name[:50])

t0 = time.time()
res = cat.search_name("10001043")
t1 = (time.time() - t0) * 1000
print(f"numeric search: {t1:.1f}ms, {len(res)} hits, first={res[0].name[:40] if res else None}")

shutil.rmtree(WORK)
print("ALL OK")
