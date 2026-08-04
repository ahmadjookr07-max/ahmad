# -*- coding: utf-8 -*-
"""2.9.8 — اختبار طبقة تسمية الدفعة (`batch_naming_patch`).

## لماذا هذا الاختبار موجود

قاعدة المالك: اسم الصورة يحمل **كل وحدات الصنف من الإكسل**
(``10000014_حبه_باكت``). وقد عملت في الربط اليدوي والمجلد المنجز، لكنها
**لم تعمل في مسار الدفعة** لأن الاسم يُبنى داخل محرّك مُصرَّف بلا مصدر
(``final_images.pyc``) يعرف وحدة واحدة فقط.

الحل: ``batch_naming_patch.apply_join_all_units`` يعيد التسمية بعد
الدفعة. ومشكلة التحقق منه عبر ``test_link_units_new_side`` أنه يعالج 109
صورة فعليًا (~70 دقيقة)، فحلقة التصحيح طويلة جدًا. هذا الاختبار يتحقق من
**منطق** الطبقة في ثوانٍ بنتائج دفعة مُصطنعة وملفات حقيقية على القرص،
مع وحدات مقروءة من كتالوج المالك الحقيقي حين يتوفر.

## ما يتحقق منه

1. الصنف متعدد الوحدات يُعاد تسميته: ``X_حبه`` ⇒ ``X_حبه_باكت``
2. الصنف بوحدة واحدة **لا يُلمَس** (اسم المحرّك صحيح أصلًا)
3. صورتان للصنف نفسه: الرئيسية بلا رقم والثانية ``-1``
4. ``output_path`` في النتيجة يُحدَّث ليشير للملف الجديد
5. ``state.json`` يُحدَّث فلا تشير التقارير لملفات غير موجودة
6. لا طمس لملف موجود
7. السياسة معطّلة ⇒ لا تغيير إطلاقًا
8. إخفاق داخلي لا يُسقط الدفعة (يُترك الاسم الأصلي)
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "windows_app"))

PASS = "\u2705"
FAIL = "\u274c"

_results: list[tuple[bool, str, str]] = []


def check(ok: bool, title: str, detail: str = "") -> None:
    _results.append((bool(ok), title, detail))
    mark = PASS if ok else FAIL
    print(f"  {mark} {title}" + (f" — {detail}" if detail else ""))


# ───────────── نماذج مصطنعة تحاكي نتائج المحرّك ─────────────

@dataclass
class FakeItem:
    """يحاكي ``BatchItemResult`` بالحقول التي تستعملها الطبقة."""
    item_code: str
    output_path: str
    product_name: str = ""
    warnings: list = field(default_factory=list)


@dataclass
class FakeBatch:
    """يحاكي ناتج ``run_batch``."""
    items: list
    workspace: str = ""


def _make_png(path: Path) -> None:
    """أصغر PNG صالح — الطبقة تفحص وجود الملف ولاحقته."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
        b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


def main() -> int:
    import tempfile

    from engine_v2 import integration_v2 as integ
    from engine_v2.naming_v2 import (NamingSettings, UNIT_POLICY_JOIN_ALL,
                                     UNIT_POLICY_PER_IMAGE, SCHEME_DASH,
                                     save_settings)
    from engine_v2.catalog_index_v2 import CatalogIndex
    from batch_naming_patch import apply_join_all_units

    def _index_from(mapping: dict[str, list[str]]) -> CatalogIndex:
        """يبني ``CatalogIndex`` حقيقيًا لا قاموسًا مبسّطًا.

        مهم: ``_units_from_catalog`` تستدعي ``units_for_code`` و
        ``primary_unit_for_code``، فلو مررنا ``dict`` لارتدت الدالة
        إلى ``[]`` بصمت في ``except`` ومرّ الاختبار بلا اختبار شيء.
        والوحدة الأولى تأخذ ``size="1"`` لتكون الوحدة الأساسية
        فيصير ترتيب الناتج متوقعًا.
        """
        idx = CatalogIndex()
        for code, units in mapping.items():
            for i, u in enumerate(units):
                idx.rows.append({"code": str(code), "name": "",
                                 "unit": u, "size": "1" if i == 0 else "",
                                 "barcode": ""})
        # نبني الخرائط بدالة الصنف نفسها لا يدويًا، لأن
        # ``rows_for_code`` تمرّ المفتاح على ``_clean_code`` وأي اختلاف
        # في التطبيع يجعل الفهرس يبدو فارغًا فيمر اختبار زائف.
        idx._build_maps()
        return idx

    print("=" * 62)
    print("اختبار طبقة تسمية الدفعة — 2.9.8")
    print("=" * 62)

    tmp = Path(tempfile.mkdtemp(prefix="batch_naming_"))
    out = tmp / "out"
    out.mkdir()

    # فهرس كتالوج مُصطنع: صنف بوحدتين، وصنف بوحدة واحدة.
    fake_index = {
        "10000014": ["حبه", "باكت"],
        "10000051": ["حبه", "كرتون", "كرتون1"],
        "10009999": ["حبه"],
    }

    # نُسجّل الفهرس بنفس الطريقة التي يستخدمها التطبيق.
    integ.set_catalog_index(_index_from(fake_index))

    # السياسة تُقرأ من ``NAMING_DATA_ROOT``؛ والافتراضية أصلاً
    # ``join_all_units`` (2.9.6). نترك الجذر فارغًا فتعمل الافتراضية —
    # وهو نفس ما يقع عند المالك قبل أي ضبط يدوي.
    integ.set_naming_data_root("")
    _sanity = integ._current_naming_settings()
    check(_sanity is not None
          and _sanity.unit_policy == UNIT_POLICY_JOIN_ALL,
          "السياسة الافتراضية join_all_units بلا ضبط يدوي",
          getattr(_sanity, "unit_policy", "لا شيء"))
    _u = integ._units_from_catalog("10000014")
    check(_u == ["حبه", "باكت"],
          "الفهرس يُرجع الوحدات الصحيحة", str(_u))

    print("\n[1] صنف متعدد الوحدات يُعاد تسميته بكل الوحدات")
    p = out / "10000014_حبه.png"
    _make_png(p)
    res = FakeBatch(items=[FakeItem("10000014", str(p))], workspace=str(tmp))
    apply_join_all_units(res)
    want = out / "10000014_حبه_باكت.png"
    check(want.is_file(), "الملف الجديد موجود", want.name)
    check(not p.is_file(), "الاسم القديم أُزيل")
    check(res.items[0].output_path == str(want),
          "output_path حُدِّث في النتيجة",
          Path(res.items[0].output_path).name)

    print("\n[2] صنف بوحدة واحدة لا يُلمَس")
    p1 = out / "10009999_حبه.png"
    _make_png(p1)
    res = FakeBatch(items=[FakeItem("10009999", str(p1))], workspace=str(tmp))
    apply_join_all_units(res)
    check(p1.is_file(), "الاسم بقي كما هو", p1.name)

    print("\n[3] صورتان لصنف واحد: الرئيسية بلا رقم والثانية -2 (2.9.9)")
    a = out / "10000051_حبه.png"
    b = out / "10000051_حبه~2.png"
    _make_png(a)
    _make_png(b)
    res = FakeBatch(items=[FakeItem("10000051", str(a)),
                           FakeItem("10000051", str(b))],
                    workspace=str(tmp))
    apply_join_all_units(res)
    main_name = out / "10000051_حبه_كرتون_كرتون1.png"
    # 2.9.9 — الثانية تأخذ ترتيبها الحقيقي `-2`؛ كان `-1`
    # يوهم أنها الأولى فيتداخل مع الرئيسية في نفس المجلد.
    second = out / "10000051_حبه_كرتون_كرتون1-2.png"
    check(main_name.is_file(), "الرئيسية بلا رقم", main_name.name)
    check(second.is_file(), "الثانية بـ-2", second.name)
    check(not (out / "10000051_حبه_كرتون_كرتون1-1.png").is_file(),
          "لا يوجد -1 المحظور")

    print("\n[4] عدم طمس ملف موجود")
    keep = out / "10000014_حبه_باكت.png"   # موجود من [1]
    keep_bytes = keep.read_bytes()
    p2 = out / "10000014_حبه~9.png"
    _make_png(p2)
    res = FakeBatch(items=[FakeItem("10000014", str(p2))], workspace=str(tmp))
    apply_join_all_units(res)
    check(keep.is_file() and keep.read_bytes() == keep_bytes,
          "الملف الأصلي لم يُطمَس")
    check((out / "10000014_حبه_باكت-2.png").is_file(),
          "الجديد أخذ التسلسل الحر", "…-2.png")

    print("\n[5] تحديث state.json")
    st = tmp / "state.json"
    p3 = out / "10000051_حبه~7.png"
    _make_png(p3)
    st.write_text(json.dumps(
        {"items": [{"output_path": p3.name, "item_code": "10000051"}]},
        ensure_ascii=False), encoding="utf-8")
    res = FakeBatch(items=[FakeItem("10000051", str(p3))], workspace=str(tmp))
    apply_join_all_units(res)
    raw = st.read_text(encoding="utf-8")
    check(p3.name not in raw, "الاسم القديم زال من state.json")
    check("10000051_حبه_كرتون_كرتون1" in raw,
          "الاسم الجديد كُتب في state.json")

    print("\n[6] السياسة معطّلة ⇒ لا تغيير")
    # نحاكي اختيار مالك لسياسة أخرى: نكتب ملف الإعدادات في جذر
    # بيانات مؤقت ونوجّه ``NAMING_DATA_ROOT`` إليه — لا نرقّع دالة
    # داخلية، لأن المراد اختبار المسار الحقيقي للإعدادات.
    cfg_root = tmp / "cfg"
    cfg_root.mkdir(exist_ok=True)
    try:
        save_settings(str(cfg_root),
                      NamingSettings(enabled=True, scheme=SCHEME_DASH,
                                     unit_policy=UNIT_POLICY_PER_IMAGE,
                                     default_unit="حبه"))
        integ.set_naming_data_root(str(cfg_root))
        active = integ._current_naming_settings()
        check(active is not None
              and active.unit_policy == UNIT_POLICY_PER_IMAGE,
              "سياسة المالك المحفوظة تُقرأ",
              getattr(active, "unit_policy", "لا شيء"))
        p4 = out / "10000014_حبه~5.png"
        _make_png(p4)
        res = FakeBatch(items=[FakeItem("10000014", str(p4))],
                        workspace=str(tmp))
        apply_join_all_units(res)
        check(p4.is_file(),
              "الاسم لم يتغير مع سياسة غير join_all", p4.name)
    except Exception as exc:  # noqa: BLE001
        check(False, "اختبار السياسة البديلة", str(exc)[:80])
    finally:
        integ.set_naming_data_root("")

    print("\n[7] الطبقة لا تُسقط الدفعة عند إخفاق")
    # ملف غير موجود على القرص + عنصر بلا item_code + عنصر بلا مسار.
    bad = FakeBatch(items=[
        FakeItem("10000014", str(out / "غير_موجود.png")),
        FakeItem("", str(out / "10000014_حبه_باكت.png")),
        FakeItem("10000014", ""),
    ], workspace=str(tmp))
    try:
        r = apply_join_all_units(bad)
        check(r is bad, "أُعيدت النتيجة نفسها بلا استثناء")
    except Exception as exc:  # noqa: BLE001
        check(False, "لا استثناء", f"رُفع: {exc}")

    print("\n[8] نتيجة بلا عناصر / بلا workspace")
    try:
        check(apply_join_all_units(FakeBatch(items=[])) is not None,
              "دفعة فارغة سليمة")
        check(apply_join_all_units(object()) is not None,
              "كائن غريب لا يُسقط الطبقة")
    except Exception as exc:  # noqa: BLE001
        check(False, "لا استثناء على المدخلات الشاذة", f"رُفع: {exc}")

    # ───────────── وحدات من كتالوج المالك الحقيقي ─────────────
    real_xlsx = Path("/home/ubuntu/owner_data/اصنافعالمعنترة.xlsx")
    if real_xlsx.is_file():
        print("\n[9] وحدات من كتالوج المالك الحقيقي")
        try:
            real_idx = CatalogIndex()
            real_idx.load_excel(str(real_xlsx), use_cache=False)
            codes = [c for c, rows in real_idx.by_code_all.items()
                     if len(real_idx.units_for_code(c)) > 1]
            check(len(codes) > 1000,
                  "أصناف متعددة الوحدات في كتالوج المالك",
                  f"{len(codes)} من {len(real_idx.by_code_all)}")
            integ.set_catalog_index(real_idx)
            code = codes[0]
            units = integ._units_from_catalog(code)
            pr = out / f"{code}_{units[0]}.png"
            _make_png(pr)
            res = FakeBatch(items=[FakeItem(code, str(pr))],
                            workspace=str(tmp))
            apply_join_all_units(res)
            newp = Path(res.items[0].output_path)
            ok = newp.is_file() and all(u.replace(" ", "") in newp.stem
                                        for u in units)
            check(ok, f"الصنف الحقيقي {code} حمل كل وحداته",
                  f"{newp.stem}  (الوحدات: {'،'.join(units)})")
        except Exception as exc:  # noqa: BLE001
            check(False, "قراءة كتالوج المالك", str(exc)[:80])
    else:
        print("\n[9] كتالوج المالك غير متوفر — تُخطّى")

    # ───── [10] العلة الحاسمة: كائنات مُجمَّدة frozen=True ─────
    #
    # المحرّك الحقيقي يرجع @dataclass(frozen=True). فـsetattr يرفع
    # FrozenInstanceError. ولو كُتِم الإخفاق لصار القرص يخالف
    # النتيجة ⇒ صور مفقودة في الواجهة. هذا أهم فحص في الملف.
    print("\n[10] كائنات مُجمَّدة (frozen=True) كما في المحرك الحقيقي")

    from dataclasses import dataclass as _dc

    @_dc(frozen=True)
    class FrozenItem:
        item_code: str
        output_path: str

    @_dc(frozen=True)
    class FrozenBatch:
        items: list
        workspace: str = ""

    fz = tmp / "frozen"
    code_fz = "20000001"
    # الفقرة [6] بدّلت السياسة إلى per_image — نعيد join_all_units
    # وإلا ارتدت الطبقة مباشرة ومرّ الفحص بلا اختبار شيء.
    save_settings(str(tmp), NamingSettings(
        enabled=True, scheme=SCHEME_DASH,
        unit_policy=UNIT_POLICY_JOIN_ALL, default_unit="حبه"))
    integ.set_catalog_index(_index_from({code_fz: ["حبه", "باكت"]}))
    p_fz = fz / f"{code_fz}_حبه.png"
    _make_png(p_fz)
    res_fz = FrozenBatch(items=[FrozenItem(code_fz, str(p_fz))],
                         workspace=str(fz))
    apply_join_all_units(res_fz)
    new_fz = Path(res_fz.items[0].output_path)
    check(new_fz.stem == f"{code_fz}_حبه_باكت",
          "النتيجة المُجمَّدة تُحدَّث (dataclasses.replace)",
          new_fz.stem)
    check(new_fz.is_file(),
          "الملف موجود على القرص بالاسم الجديد", new_fz.name)
    check(not p_fz.exists(), "الاسم القديم لم يبق مزدوجًا", p_fz.name)
    # أهم فحص: القرص والنتيجة متسقان — لا صورة مفقودة.
    check(Path(res_fz.items[0].output_path).is_file(),
          "اتساق القرص مع النتيجة (لا صور مفقودة)")

    # ───────────── الخلاصة ─────────────
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

    # تنظيف
    try:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception:
        pass

    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
