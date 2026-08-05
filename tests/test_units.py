# -*- coding: utf-8 -*-
"""اختبار قراءة الوحدات من الإكسل حرفيًا وخطة التسمية للأصناف متعددة الوحدات.

قاعدة المالك: الوحدة تُنقل كما وردت في الإكسل بلا أي تطبيع («حبه» تبقى «حبه»)،
والتطبيع مسموح للمقارنة الداخلية فقط لا في أسماء الملفات.
"""
import glob
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine_v2.catalog_index_v2 import CatalogIndex
from engine_v2.naming_v2 import (NamingSettings, UNIT_POLICY_REPLICATE,
                                 plan_names_for_item)

PASS, FAIL = [], []


def check(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name +
          (f" — {note}" if note else ""))


def asset_dirs():
    """مجلدات البحث عن أصول الاختبار، محايدة لنوع نظام التشغيل."""
    dirs = []
    env = os.environ.get("TEST_ASSETS_DIR", "").strip()
    if env:
        dirs.append(Path(env))
    dirs.append(Path("/home/ubuntu/upload"))
    dirs.append(ROOT / "test_assets")
    return dirs


cands = []
for d in asset_dirs():
    cands = sorted(glob.glob(str(d / "*.xlsx")))
    if cands:
        break
if not cands:
    print("لا يوجد ملف إكسل للاختبار — شغّل tests/make_test_assets.py أولًا")
    sys.exit(1)
xlsx = cands[0]

idx = CatalogIndex()
idx.load_excel(xlsx, use_cache=False)
check("load_excel", len(idx.rows) > 0,
      f"{len(idx.rows)} صفًا في {idx.load_seconds:.2f}s")

# الأعمدة العربية تُتعرف تلقائيًا
check("columns", bool(idx.columns), str(idx.columns)[:120])

# البحث برقم الصنف يعمل على الصفوف المحمّلة
any_code = next(iter(idx.by_code_all))
check("lookup_code", idx.lookup_code(any_code) is not None, str(any_code))
units = idx.units_for_code(any_code)
check("units_for_code", isinstance(units, list) and len(units) >= 1,
      str(units))

# الوحدة حرفية: بلا تطويل ولا مسافات زائدة ولا استبدال حروف
verbatim_ok = all(isinstance(u, str) and u == u.strip() and "\u0640" not in u
                  for u in units)
check("unit_verbatim", verbatim_ok, str(units))

# الوحدة الأساسية للصنف تُشتق دون كسر
primary = idx.primary_unit_for_code(any_code)
check("primary_unit", isinstance(primary, str) and primary in units,
      repr(primary))

# خطة التسمية (2.9.12): الواجهة بلا لاحقة ثم -1 -2 للباقي
s = NamingSettings(unit_policy=UNIT_POLICY_REPLICATE)
plan = plan_names_for_item(any_code, 3, list(dict.fromkeys(units)), s)
check("plan_len", len(plan) == 3, str(plan))
# كل عنصر في الخطة قائمة أسماء (اسم لكل وحدة عند سياسة التكرار)
flat0 = list(plan[0]) if plan else []
stem0 = str(flat0[0]).rsplit(".", 1)[0] if flat0 else ""
check("plan_primary_no_suffix",
      bool(stem0) and not stem0.rsplit("-", 1)[-1].isdigit(), stem0)
# 2.9.12 — الواجهة بلا رقم ثم -1 ثم -2 (أمر المالك الصريح:
# «الأولى بدون رقم والثانية 1 والثالثة 2»).
rest_ok = all(all(str(n).rsplit(".", 1)[0].endswith(f"-{i}")
                  for n in names)
              for i, names in enumerate(plan[1:], start=1))
check("plan_suffix_dash", rest_ok, str(plan))
flat_all = [str(n).rsplit(".", 1)[0] for names in plan for n in names]
# الصف الأول وحده بلا رقم ترتيب (اسم لكل وحدة في سياسة التكرار).
check("plan_one_unnumbered_row",
      sum(1 for s in flat_all if not s.rsplit("-", 1)[-1].isdigit())
      == len(flat0), str(flat_all))
check("plan_no_duplicates",
      len(flat_all) == len(set(flat_all)), str(flat_all))

# أصناف متعددة الوحدات (إن وُجدت) تُعرض للمعلومة
multi = [(c, idx.units_for_code(c)) for c, v in idx.by_code_all.items()
         if len(v) > 1]
print("  info: أصناف بأكثر من صف:", len(multi))

print(f"\n===== {len(PASS)} passed / {len(FAIL)} failed =====")
if FAIL:
    print("FAILED:", FAIL)
sys.exit(0 if not FAIL else 1)
