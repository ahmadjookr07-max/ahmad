# -*- coding: utf-8 -*-
"""برهان عملي على قاعدة المالك الكاملة — على بياناته الحقيقية.

قاعدة المالك (بنصّه):
  «حبة وباكت وأغلب المنتجات يجب أن تكون هكذا، مثال الببسي له شدة
   وباكت وكرتون وكثير — استخرجها ثم أضفها»
  «إذا كان للمنتج أكثر من صورة فالمسمى يكون بترقيم والأولى بدون رقم،
   لهذا أضفنا النجمة»

فالاسم المطلوب: {رقم}_{كل وحدات الإكسل}[-{تسلسل}]
  الواجهة (★) بلا رقم | الثانية -2 | الثالثة -3 …

يعمل على نسخة من مجلد المالك المنجز (992 ملفًا) + كتالوجه (50,311 صفًا).
لا يلمس الأصل إطلاقًا. يتخطّى بـrc=77 إن غابت البيانات.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "windows_app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("MIS_SKIP_LICENSE", "1")
os.environ.setdefault("MIS_HEADLESS", "1")

from owner_data_guard import find_catalog, find_legacy_dir, skip  # noqa: E402

OK = FAIL = 0
IMG_EXTS = {".webp", ".jpg", ".jpeg", ".png"}


def say(msg: str) -> None:
    print(msg, flush=True)


def check(label: str, cond: bool, detail: str = "") -> bool:
    global OK, FAIL
    if cond:
        OK += 1
        say(f"  ✓ {label}" + (f" — {detail}" if detail else ""))
    else:
        FAIL += 1
        say(f"  ✗ {label}" + (f" — {detail}" if detail else ""))
    return bool(cond)


def main() -> int:
    catalog = find_catalog()
    legacy = find_legacy_dir()
    if catalog is None or legacy is None:
        skip("يحتاج كتالوج المالك ومجلده المنجز الحقيقي")

    from engine_v2 import naming_v2 as N
    from engine_v2.catalog_index_v2 import CatalogIndex
    from engine_v2 import legacy_folder_v2 as LF

    say(f"الكتالوج: {catalog}")
    say(f"المجلد المنجز: {legacy}")

    # ── نسخة عمل معزولة ────────────────────────────────────────────
    tmp = Path(tempfile.mkdtemp(prefix="owner_units_"))
    work = tmp / "منجز"
    work.mkdir(parents=True, exist_ok=True)
    # مسودات المحرر (`editor_drafts/*.edited.png`) ليست مخرجات
    # نهائية بل نسخ عمل جانبية؛ إدخالها في خطة التسمية
    # يجعل المحرك يحاول إعادة تسمية ملف مزدوج اللاحقة
    # (`.edited.png`) فيقع خطأ مسار غير موجود، وهو خطأ لا يمسّ
    # مخرجات المالك الفعلية. نستثنيها كما تفعل الواجهة.
    def _is_final_output(p: Path) -> bool:
        if p.suffix.lower() not in IMG_EXTS:
            return False
        if "editor_drafts" in {part for part in p.parts}:
            return False
        if p.name.lower().endswith(".edited.png"):
            return False
        return True

    srcs = sorted(p for p in Path(legacy).rglob("*") if _is_final_output(p))
    if not srcs:
        skip("لا صور في المجلد المنجز")
    for p in srcs:
        shutil.copy2(p, work / p.name)
    before = sorted(q.name for q in work.iterdir() if q.is_file())
    say(f"نسخة العمل: {len(before)} ملفًا في {work}")

    # ── الكتالوج الحقيقي ───────────────────────────────────────────
    say("\n[1] الكتالوج الحقيقي: كل الوحدات لكل صنف")
    idx = CatalogIndex()
    idx.load_excel(str(catalog))
    codes_all = list(getattr(idx, "by_code_all", {}) or {})
    check("فُهرس الكتالوج", len(codes_all) > 1000, f"{len(codes_all)} صنفًا")
    multi = [c for c in codes_all if len(idx.units_for_code(c)) > 1]
    check("أصناف متعددة الوحدات موجودة فعلًا", len(multi) > 100,
          f"{len(multi)} من {len(codes_all)}")

    # ── السياسة الافتراضية ────────────────────────────────────────
    say("\n[2] السياسة الافتراضية = جمع كل الوحدات (بلا ضبط يدوي)")
    s = N.NamingSettings()
    check("unit_policy الافتراضي join_all_units",
          s.unit_policy == N.UNIT_POLICY_JOIN_ALL, repr(s.unit_policy))
    check("نظام التسمية مفعَّل افتراضيًا", bool(s.enabled))

    # ── قاعدة الترقيم: الواجهة بلا رقم ثم -2 ──────────────────────
    # الترقيم يوافق رتبة الصورة: الأولى بلا رقم، الثانية -2،
    # الثالثة -3 — فلا يوجد ـ-1 إطلاقًا (قرار المالك).
    say("\n[3] قاعدة المالك للصور المتعددة (★ الواجهة بلا رقم ثم -2، -3)")
    u4 = ["باكت", "حبه", "كرتون", "كرتون 1"]
    n1 = N.build_name_join_all("10008272", u4, seq=1, total=3)
    n2 = N.build_name_join_all("10008272", u4, seq=2, total=3)
    n3 = N.build_name_join_all("10008272", u4, seq=3, total=3)
    check("الواجهة تحمل كل الوحدات وبلا رقم",
          n1 == "10008272_باكت_حبه_كرتون_كرتون1", n1)
    check("الثانية تأخذ -2 بعد كل الوحدات",
          n2 == "10008272_باكت_حبه_كرتون_كرتون1-2", n2)
    check("الثالثة تأخذ -3", n3 == "10008272_باكت_حبه_كرتون_كرتون1-3", n3)
    check("لا يوجد ـ-1 في أي اسم (الرئيسية بلا رقم)",
          not any(x.endswith("-1") for x in (n1, n2, n3)),
          f"{n1} | {n2} | {n3}")
    check("المسافة داخل الوحدة تُحذف (كرتون 1 ⇒ كرتون1)",
          "كرتون1" in n1 and "كرتون 1" not in n1)
    check("وحدة واحدة تبقى وحدة واحدة",
          N.build_name_join_all("10001102", ["حبه"], 1) == "10001102_حبه")

    # ── البرهان العملي: خطة التصحيح على مجلد المالك ───────────────
    say("\n[4] البرهان العملي: خطة التصحيح على 992 ملفًا حقيقيًا")
    groups, unparsed = LF.scan_legacy_folder(work)
    check("قُرئ المجلد المنجز إلى مجموعات", len(groups) > 100,
          f"{len(groups)} صنفًا، {len(unparsed)} غير مفهوم")
    plan = LF.plan_legacy_renames(groups, index=idx, unparsed=unparsed)
    rows = list(plan.rows)
    check("بُنيت خطة لكل الصور", len(rows) == len(before),
          f"{len(rows)} صف مقابل {len(before)} ملفًا")

    changed = [r for r in rows
               if (r.new_stem + Path(r.old_path).suffix.lower())
               != Path(r.old_path).name]
    multi_rows = [r for r in rows if r.new_stem.count("_") >= 2]
    say(f"    أسماء ستتغيّر: {len(changed)}")
    say(f"    أسماء بأكثر من وحدة: {len(multi_rows)}")
    check("الخطة تصحّح الأسماء الناقصة الوحدات", len(changed) > 100,
          f"{len(changed)} اسمًا")
    check("الخطة تولّد أسماء متعددة الوحدات فعلًا", len(multi_rows) > 100,
          f"{len(multi_rows)} اسمًا")
    for r in rows[:5]:
        say(f"    {Path(r.old_path).name} ⇒ {r.new_stem}")

    # ── مطابقة الخطة مع الإكسل 100% ───────────────────────────────
    say("\n[5] مطابقة الخطة مع الإكسل (لا اسم يخالف وحدات الإكسل)")
    pat = re.compile(r"^(\d+)_(.+?)(?:-(\d+))?$")
    mism: list[str] = []
    for r in rows:
        m = pat.match(r.new_stem)
        if not m:
            mism.append(f"نمط غير مطابق: {r.new_stem}")
            continue
        code, unit_part, _ = m.groups()
        file_u = {N.unit_key(u) for u in unit_part.split("_") if u}
        xl_u = {N.unit_key(u) for u in idx.units_for_code(code)}
        if xl_u and file_u != xl_u:
            mism.append(f"{r.new_stem}: ملف={sorted(file_u)} إكسل={sorted(xl_u)}")
    check("كل الأسماء المخطَّطة مطابقة لوحدات الإكسل 100%",
          not mism, f"{len(mism)} شاذًا" + (f" مثل {mism[:3]}" if mism else ""))

    # ── قاعدة الترقيم داخل كل مجموعة ──────────────────────────────
    say("\n[6] داخل كل صنف: واجهة واحدة بلا رقم والبقية -2، -3 متتالية")
    by_item: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        by_item[r.item].append(r.new_stem)
    bad_seq: list[str] = []
    for item, stems in by_item.items():
        bases = [x for x in stems if not re.search(r"-\d+$", x)]
        nums = sorted(int(re.search(r"-(\d+)$", x).group(1))
                      for x in stems if re.search(r"-\d+$", x))
        if len(bases) != 1:
            bad_seq.append(f"{item}: {len(bases)} واجهة")
        elif nums and nums != list(range(2, len(nums) + 2)):
            # الرئيسية بلا رقم تشغل الرتبة 1، فأول لاحقة -2.
            bad_seq.append(f"{item}: تسلسل {nums}")
    check("كل صنف له واجهة واحدة بلا رقم وترقيم متصل من 2",
          not bad_seq, f"{len(bad_seq)} شاذًا" +
          (f" مثل {bad_seq[:3]}" if bad_seq else ""))

    # ── تنفيذ الخطة فعليًا على القرص ───────────────────────────────
    say("\n[7] تنفيذ الخطة على القرص (نسخة معزولة)")
    res = LF.apply_legacy_plan(plan)
    errs = list(res.get("errors") or [])
    after = sorted(q.name for q in work.iterdir() if q.is_file())
    check("التنفيذ بلا أخطاء", not errs, f"{len(errs)} خطأ" +
          (f" مثل {errs[:2]}" if errs else ""))
    check("لا فقد ولا تكرار ملفات", len(after) == len(before),
          f"{len(before)} ⇒ {len(after)}")
    check("لا ملفات مؤقتة متبقية",
          not [x for x in after if ".tmp_rn" in x])
    check("لا تصادم أسماء", len(set(after)) == len(after))

    real_multi = [x for x in after if x.count("_") >= 2]
    check("أسماء متعددة الوحدات موجودة فعلًا على القرص",
          len(real_multi) > 100, f"{len(real_multi)} ملفًا")
    say(f"    أمثلة: {sorted(real_multi)[:5]}")

    # ── القياس النهائي: هل زال النقص الذي رُصد (428 ملفًا)؟ ────────
    say("\n[8] القياس الفاصل: نسبة المطابقة قبل وبعد")

    def agree_count(names: list[str]) -> int:
        n = 0
        for nm in names:
            m = pat.match(Path(nm).stem)
            if not m:
                continue
            code, unit_part, _ = m.groups()
            f = {N.unit_key(u) for u in unit_part.split("_") if u}
            x = {N.unit_key(u) for u in idx.units_for_code(code)}
            if x and f == x:
                n += 1
        return n

    a_before = agree_count(before)
    a_after = agree_count(after)
    say(f"    مطابق لكل وحدات الإكسل: قبل {a_before}/{len(before)}"
        f" ⇒ بعد {a_after}/{len(after)}")
    check("المطابقة تحسّنت فعليًا", a_after > a_before,
          f"{a_before} ⇒ {a_after}")
    check("المطابقة صارت كاملة 100%", a_after == len(after),
          f"{a_after}/{len(after)}")

    shutil.rmtree(tmp, ignore_errors=True)
    say("\n" + "═" * 62)
    say(f"النتيجة: {OK}/{OK + FAIL}")
    if FAIL:
        say(f"فشل: {FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
