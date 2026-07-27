import sys, glob
sys.path.insert(0, "app_v2/src")
from engine_v2.catalog_index_v2 import CatalogIndex
from engine_v2.naming_v2 import NamingSettings, plan_names_for_item, UNIT_POLICY_REPLICATE

xlsx = glob.glob("/home/ubuntu/upload/*.xlsx")[0]
idx = CatalogIndex()
el = idx.load_excel(xlsx, use_cache=False)
print(f"loaded {len(idx.items)} in {el:.1f}s")

multi = [(c, idx.units_for_code(c)) for c, v in idx.by_code_all.items() if len(v) > 1]
multi_units = [(c, u) for c, u in multi if len(set(u)) > 1]
print("codes with >1 row:", len(multi), "| with distinct units:", len(multi_units))
print("samples:", multi_units[:5])

c, units = multi_units[0]
s = NamingSettings(unit_policy=UNIT_POLICY_REPLICATE)
plan = plan_names_for_item(c, 2, list(dict.fromkeys(units)), s)
print("replicate plan for", c, "->", plan)

# check unit verbatim (no normalization)
weird = [u for _, us in multi_units for u in us if u not in ("حبه", "كرتون")]
print("distinct non-standard units (verbatim):", sorted(set(weird))[:15])
print("ALL UNITS OK")
