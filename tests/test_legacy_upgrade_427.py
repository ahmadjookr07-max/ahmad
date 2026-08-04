#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبار 2.9.8 — أداة تصحيح المجلد المنجز تُغلق فجوة الـ427 ملفًا.

الخلفية
-------
`test_link_units_new_side` [6] يبلغ: «الجهة المنجزة تتبع القاعدة نفسها
— 427/992 ناقص الوحدات». وهذا **ليس علة برمجية**: تلك الملفات سُمّيت
بالقاعدة القديمة (وحدة واحدة) *قبل* إصلاح 2.9.6، فالفحص يقيسها
بالقاعدة الجديدة فيراها ناقصة.

الأداة الصحيحة موجودة أصلًا: ``plan_legacy_renames`` +
``apply_legacy_plan``. هذا الاختبار يثبت عمليًا — على **نسخة من بيانات
المالك الحقيقية** — أن تشغيل الأداة يُغلق الفجوة فعلًا، فلا يبقى
الرقم 427 غامضًا ولا يُسلَّم المشروع بإخفاق غير مُفسَّر.

لا يكتب شيئًا على بيانات المالك: يعمل على نسخة مؤقتة ويحذفها.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _p in (_ROOT / "src", _ROOT / "windows_app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

OK, FAIL = "\u2705", "\u274c"
_results: list[tuple[bool, str, str]] = []


def check(cond: bool, title: str, detail: str = "") -> bool:
    _results.append((bool(cond), title, detail))
    print(f"  {OK if cond else FAIL} {title}" + (f" — {detail}" if detail else ""))
    return bool(cond)


def _owner_paths() -> tuple[Path | None, Path | None]:
    """مجلد المنجز وملف الإكسل من بيانات المالك."""
    root = Path(os.environ.get("MIS_OWNER_DATA", "/home/ubuntu/owner_data"))
    done = None
    for cand in root.rglob("*"):
        if cand.is_dir() and any(
            p.suffix.lower() in (".webp", ".png", ".jpg")
            for p in cand.glob("*")
        ):
            names = [p.stem for p in cand.glob("*") if p.is_file()]
            # مجلد المنجز: أسماؤه تبدأ بأرقام أصناف
            if sum(1 for n in names if n[:8].isdigit()) > 50:
                done = cand
                break
    xls = None
    for cand in root.rglob("*.xlsx"):
        xls = cand
        break
    return done, xls


def main() -> int:
    print("=" * 62)
    print("اختبار أداة تصحيح المجلد المنجز — فجوة 427 ملفًا")
    print("=" * 62)

    from engine_v2 import legacy_folder_v2 as lf
    from engine_v2.catalog_index_v2 import CatalogIndex
    from engine_v2.naming_v2 import (NamingSettings, UNIT_POLICY_JOIN_ALL,
                                     SCHEME_DASH, save_settings, clean_unit)

    done, xls = _owner_paths()
    if not done or not xls:
        print("\nبيانات المالك غير متوفرة — يُخطّى الاختبار")
        return 0

    print(f"\n[1] بيانات المالك")
    check(True, "مجلد المنجز", str(done))
    check(True, "كتالوج الإكسل", xls.name)

    # ── نسخة معزولة: لا نلمس بيانات المالك ──
    tmp = Path(tempfile.mkdtemp(prefix="legacy_upgrade_"))
    work = tmp / "done"
    shutil.copytree(done, work)
    total_files = sum(1 for p in work.iterdir() if p.is_file())
    print(f"\n[2] نسخة معزولة: {total_files} ملفًا")

    # ── سياسة كل الوحدات (قاعدة المالك 2.9.6) ──
    save_settings(str(tmp), NamingSettings(
        enabled=True, scheme=SCHEME_DASH,
        unit_policy=UNIT_POLICY_JOIN_ALL, default_unit="حبه"))
    os.environ["NAMING_DATA_ROOT"] = str(tmp)

    # ── فهرس الإكسل الحقيقي ──
    idx = CatalogIndex()
    idx.load_excel(str(xls))
    print(f"\n[3] الفهرس: {len(idx.rows)} صفًا")

    # ── قياس الفجوة قبل التصحيح ──
    def _gap(folder: Path) -> tuple[int, int]:
        """(ناقص الوحدات، الكل) بنفس منطق فحص الربط."""
        short = 0
        seen = 0
        for p in sorted(folder.iterdir()):
            if not p.is_file() or p.suffix.lower() not in (
                    ".webp", ".png", ".jpg", ".jpeg"):
                continue
            stem = p.stem
            if ".edited" in stem or stem.endswith(".edited"):
                continue
            code = stem[:8]
            if not code.isdigit():
                continue
            seen += 1
            units = idx.units_for_code(code)
            if len(units) < 2:
                continue
            if not all(clean_unit(u) in stem for u in units):
                short += 1
        return short, seen

    before_short, before_seen = _gap(work)
    print(f"\n[4] قبل التصحيح")
    check(before_short > 0,
          "الفجوة موجودة فعلًا (تأكيد أن الاختبار يقيس شيئًا)",
          f"{before_short}/{before_seen} ناقص الوحدات")

    # ── بناء الخطة وتطبيقها ──
    print(f"\n[5] بناء خطة التصحيح")
    groups, unparsed = lf.scan_legacy_folder(work)
    check(len(groups) > 0, "المجلد مقروء", f"{len(groups)} مجموعة")

    plan = lf.plan_legacy_renames(groups, index=idx, unparsed=unparsed)
    n_rows = len(getattr(plan, "rows", []) or [])
    check(n_rows > 0, "الخطة غير فارغة", f"{n_rows} صفًا للتصحيح")

    # التوقيع: apply_legacy_plan(plan, items=None) — الوسيط الثاني
    # أرقام أصناف لا مجلّد (المسارات محفوظة داخل الخطة نفسها).
    print(f"\n[6] تطبيق الخطة")
    try:
        res = lf.apply_legacy_plan(plan)
        applied = True
    except Exception as exc:  # noqa: BLE001
        applied = False
        res = {}
        check(False, "تطبيق الخطة", str(exc)[:120])
    if applied:
        n_ren = len(res.get("renames") or {})
        errs = res.get("errors") or []
        check(True, "الخطة طُبّقت بلا استثناء",
              f"{res.get('items_done', 0)} صنفًا، {n_ren} إعادة تسمية")
        check(not errs, "بلا أخطاء في التنفيذ",
              "؛".join(errs[:3]) if errs else "")

    # ── قياس الفجوة بعد التصحيح ──
    after_short, after_seen = _gap(work)
    print(f"\n[7] بعد التصحيح")
    check(after_short < before_short,
          "الفجوة انخفضت",
          f"{before_short} ⇒ {after_short}")
    check(after_short == 0,
          "الفجوة أُغلقت بالكامل",
          f"{after_short}/{after_seen} ناقص الوحدات")

    # ── لا فقدان صور: العدد ثابت ──
    after_files = sum(1 for p in work.iterdir() if p.is_file())
    check(after_files == total_files,
          "لا صورة مفقودة بعد التصحيح",
          f"{total_files} ⇒ {after_files}")

    # ── الخلاصة ──
    passed = sum(1 for ok, _, _ in _results if ok)
    total = len(_results)
    print("\n" + "=" * 62)
    print(f"النتيجة: {passed}/{total}")
    failed = [(t, d) for ok, t, d in _results if not ok]
    if failed:
        print("\nالإخفاقات:")
        for t, d in failed:
            print(f"  {FAIL} {t}" + (f" — {d}" if d else ""))
    print("=" * 62)

    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
