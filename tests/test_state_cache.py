# -*- coding: utf-8 -*-
"""حاجز انحدار لتسريع حالة المهمة — `state_cache_v2` (2.9.7).

يثبت أن فصل سجلات الكاتالوج عن `job_state.json`:
1. يصغّر ملف الحالة من ميغابايتات إلى كيلوبايتات.
2. يحفظ السجلات كاملة بلا نقص ولا تحريف.
3. يقرأ الحالة القديمة (السجلات داخلها) بلا تدخّل — توافق خلفي.
4. لا يكتب الملف الجانبي مرتين لنفس السجلات.
5. يبقى سليمًا إن كانت مساحة العمل غير قابلة للكتابة.
6. يسرّع دورة التعديل تسريعًا مقيسًا.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from engine_v2 import state_cache_v2 as sc  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} — {detail}")


def make_records(n: int) -> list[dict]:
    """سجلات تحاكي بنية إكسل المالك (رقم، اسم، وحدة، باركود)."""
    return [
        {
            "code": f"{100000 + i}",
            "name": f"صنف رقم {i} — اختبار عربي",
            "unit": "حبه" if i % 2 else "كرتون",
            "barcode": f"628{i:010d}",
            "price": round(1.5 + i * 0.01, 2),
        }
        for i in range(n)
    ]


def base_state(records: list[dict]) -> dict:
    """حالة مهمة بنفس بنية ما تكتبه الحزمة الأصلية."""
    return {
        "schema_version": 3,
        "updated_at": "2026-08-03T18:00:00",
        "catalog_path": "/tmp/catalog.xlsx",
        "catalog_summary": {"rows": len(records)},
        "catalog_records": records,
        "profile_name": "متجر",
        "final_image_options": {"quality": 92},
        "result": {"ok": True, "images": []},
    }


def main() -> int:
    print("═" * 62)
    print("حاجز انحدار: تسريع حالة المهمة (state_cache_v2)")
    print("═" * 62)

    # ───────────────────────── 1. الفصل يصغّر الحالة
    print("\n[1] فصل السجلات يصغّر ملف الحالة")
    tmp = Path(tempfile.mkdtemp(prefix="sc_split_"))
    try:
        records = make_records(50000)
        payload = base_state(records)

        state_path = tmp / sc.STATE_NAME
        with state_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        fat_size = state_path.stat().st_size

        slim = sc.split_records(tmp, payload)
        with state_path.open("w", encoding="utf-8") as fh:
            json.dump(slim, fh, ensure_ascii=False)
        slim_size = state_path.stat().st_size

        check("السجلات نُقلت خارج الحالة",
              "catalog_records" not in slim)
        check("مرجع السجلات مكتوب في الحالة",
              sc.RECORDS_REF_KEY in slim)
        check("الملف الجانبي أُنشئ",
              sc.records_sidecar_path(tmp).is_file())
        check(f"الحالة صغرت ({fat_size/1e6:.1f}م.ب ← "
              f"{slim_size/1024:.1f}ك.ب)",
              slim_size < fat_size / 100,
              f"{slim_size} vs {fat_size}")
        check("الحقول الأخرى محفوظة",
              slim.get("profile_name") == "متجر"
              and slim.get("schema_version") == 3)

        # ───────────────────────── 2. الدمج يعيد السجلات كاملة
        print("\n[2] الدمج يعيد السجلات كاملة بلا تحريف")
        merged = sc.merge_records(tmp, slim)
        got = merged.get("catalog_records") or []
        check("عدد السجلات مطابق", len(got) == len(records),
              f"{len(got)} != {len(records)}")
        check("أول سجل مطابق", got and got[0] == records[0])
        check("آخر سجل مطابق", got and got[-1] == records[-1])
        check("العربية سليمة",
              got and "صنف رقم 0" in got[0]["name"])
        check("الوحدات سليمة",
              got and got[1]["unit"] == "حبه")

        # ───────────────────────── 3. لا كتابة مكرّرة
        print("\n[3] لا يُعاد كتابة الملف الجانبي لنفس السجلات")
        sidecar = sc.records_sidecar_path(tmp)
        before = sidecar.stat().st_mtime_ns
        time.sleep(0.01)
        sc.split_records(tmp, base_state(records))
        after = sidecar.stat().st_mtime_ns
        check("الملف الجانبي لم يُكتب ثانيةً", before == after,
              "أُعيدت الكتابة بلا داعٍ")

        # تغيّر السجلات ⇒ يجب أن يُكتب
        changed = make_records(50000)
        changed[-1]["name"] = "صنف مُعدَّل"
        time.sleep(0.01)
        sc.split_records(tmp, base_state(changed))
        check("الملف الجانبي يُكتب عند تغيّر السجلات",
              sidecar.stat().st_mtime_ns != after)
        remerged = sc.merge_records(tmp, sc.split_records(
            tmp, base_state(changed)))
        check("السجلات المحدَّثة تُقرأ صحيحة",
              remerged["catalog_records"][-1]["name"] == "صنف مُعدَّل")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ───────────────────────── 4. التوافق الخلفي
    print("\n[4] توافق خلفي: حالة قديمة تحمل السجلات داخلها")
    tmp2 = Path(tempfile.mkdtemp(prefix="sc_legacy_"))
    try:
        old_records = make_records(50)
        old_state = base_state(old_records)
        # لا ملف جانبي إطلاقًا — كما في مساحات العمل القديمة
        merged = sc.merge_records(tmp2, old_state)
        check("الحالة القديمة تُقرأ كما هي",
              len(merged.get("catalog_records") or []) == 50)
        check("لم يُطلب ملف جانبي غير موجود",
              not sc.records_sidecar_path(tmp2).exists())
    finally:
        shutil.rmtree(tmp2, ignore_errors=True)

    # ───────────────────────── 5. مساحة عمل غير قابلة للكتابة
    print("\n[5] السلامة عند تعذّر الكتابة الجانبية")
    tmp3 = Path(tempfile.mkdtemp(prefix="sc_ro_"))
    try:
        records = make_records(100)
        payload = base_state(records)
        os.chmod(tmp3, 0o500)  # قراءة وتنفيذ فقط
        try:
            slim = sc.split_records(tmp3, payload)
            check("السجلات لم تُفقد عند تعذّر الكتابة",
                  len(slim.get("catalog_records") or []) == 100,
                  "فُقدت السجلات — خطر فقدان بيانات")
        finally:
            os.chmod(tmp3, 0o700)
    finally:
        shutil.rmtree(tmp3, ignore_errors=True)

    # ───────────────────────── 6. قياس التسريع
    print("\n[6] قياس التسريع في دورة التعديل")
    tmp4 = Path(tempfile.mkdtemp(prefix="sc_bench_"))
    try:
        records = make_records(50000)
        payload = base_state(records)
        state_path = tmp4 / sc.STATE_NAME
        cycles = 5

        # الطريقة القديمة: كتابة وقراءة الحالة كاملة
        t0 = time.perf_counter()
        for _ in range(cycles):
            with state_path.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
            with state_path.open("r", encoding="utf-8") as fh:
                json.load(fh)
        old_ms = (time.perf_counter() - t0) / cycles * 1000

        # الطريقة الجديدة: الجانبي مكتوب مرة، ثم حالة مصغَّرة
        slim = sc.split_records(tmp4, payload)
        t0 = time.perf_counter()
        for _ in range(cycles):
            slim2 = sc.split_records(tmp4, dict(payload))
            with state_path.open("w", encoding="utf-8") as fh:
                json.dump(slim2, fh, ensure_ascii=False)
            with state_path.open("r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            sc.merge_records(tmp4, loaded)
        new_ms = (time.perf_counter() - t0) / cycles * 1000

        speedup = old_ms / new_ms if new_ms > 0 else 0
        print(f"      القديم: {old_ms:.1f}مث/دورة | "
              f"الجديد: {new_ms:.1f}مث/دورة | "
              f"التسريع: {speedup:.1f}×")
        check(f"دورة التعديل أسرع 5 أضعاف على الأقل "
              f"({speedup:.1f}×)",
              speedup >= 5.0,
              f"التسريع {speedup:.1f}× دون الهدف")
        check("دورة التعديل أقل من 150 مث",
              new_ms < 150, f"{new_ms:.1f}مث")
    finally:
        shutil.rmtree(tmp4, ignore_errors=True)

    print("\n" + "═" * 62)
    print(f"النتيجة: {PASS} ناجح، {FAIL} فاشل")
    print("═" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
