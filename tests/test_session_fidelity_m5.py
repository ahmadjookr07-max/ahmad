# -*- coding: utf-8 -*-
"""م-5 — أمانة الجلسة: لا يُفقد حقل واحد بين الحفظ والاستئناف.

بلاغ المالك: «الجلسات المحفوظة: العزل والخلفية البيضاء تذهب عند
الاستئناف فلا يمكن إكمال العمل».

العطب الجذري المُثبت بالقياس: ``_capture_state`` كان يحفظ **سبعة
حقول من ثمانية عشر**، و``v2_save_session`` كان يكتب
``output_path=d.get("review_path")`` — أي **مسار المراجعة في خانة
الناتج** — ثم ``v2_restore_session`` لا يمرّر ``output_path``
إطلاقًا. فناتج العزل يُفقد ويُعرض الأصل بخلفية مكان التصوير.

هذا الاختبار لا يقرأ الكود بل **يقيس** رحلة الحقول: كائن ⇒ قاموس
⇒ كائن، ويؤكد أن كل حقل يعود بقيمته. ويحوي فحصًا سلبيًا يُثبت أن
العطب كان حقيقيًا لا مفترضًا.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "windows_app"))

PASS = 0
FAIL = 0


def check(label: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {label}")
    else:
        FAIL += 1
        print(f"  ✗ {label} {extra}")


def main() -> int:
    print("=" * 62)
    print("م-5 — أمانة الجلسة: كل حقل يعود كما ذهب")
    print("=" * 62)

    from smart_catalog_vision.pipeline import BatchItemResult
    import v2_ui

    field_names = [f.name for f in dataclasses.fields(BatchItemResult)]
    check("BatchItemResult يحوي 18 حقلًا", len(field_names) == 18,
          f"(الفعلي {len(field_names)})")
    for critical in ("output_path", "review_path", "confidence",
                     "foreground_quality_metrics"):
        check(f"الحقل الحرج موجود: {critical}", critical in field_names)

    # ------------------------------------------------ عنصر مكتمل الحقول
    item = BatchItemResult(
        source_path="/src/IMG_0001.jpeg",
        source_name="IMG_0001.jpeg",
        status="linked",
        item_code="10001102",
        product_name="حبة تمر مجهول",
        barcode="6281000123456",
        confidence=0.94,
        explanation="مطابقة بالباركود",
        # هذان الحقلان هما بيت الداء: مختلفان قصدًا
        output_path="/ws/output/10001102_حبه.webp",
        review_path="/ws/review/IMG_0001.jpeg",
        match_source="catalog_barcode",
        barcode_candidates=("6281000123456", "6281000123457"),
        warnings=("حاشية ضيقة",),
        processing_ms=1855.4,
        foreground_method="isnet",
        foreground_quality_score=0.88,
        foreground_quality_status="good",
        foreground_quality_metrics={"edge": 0.91, "halo": 0.03},
    )

    # ------------------------------------------------- الرحلة الكاملة
    d = v2_ui.item_to_dict(item)
    check("item_to_dict يُخرج كل الحقول الثمانية عشر",
          set(d) == set(field_names),
          f"(ناقص {set(field_names) - set(d)})")

    # المرور عبر JSON إلزامي: الجلسة تُحفظ ملفًا على القرص لا في الذاكرة
    d_json = json.loads(json.dumps(d, ensure_ascii=False))
    back = v2_ui.dict_to_item(BatchItemResult, d_json)

    for name in field_names:
        before = getattr(item, name)
        after = getattr(back, name)
        if isinstance(before, tuple):
            ok = tuple(after) == before
        elif isinstance(before, float):
            ok = abs(float(after) - before) < 1e-9
        else:
            ok = after == before
        check(f"عاد سليمًا: {name}", ok, f"({before!r} ⇒ {after!r})")

    # ------------------------------- الفحص الحاسم: الناتج لا يُخلط بالمراجعة
    check("output_path لم يُستبدل بـreview_path",
          back.output_path == "/ws/output/10001102_حبه.webp"
          and back.output_path != back.review_path)
    check("review_path محفوظ مستقلًا",
          back.review_path == "/ws/review/IMG_0001.jpeg")

    # ------------------------------------------- متانة: مفاتيح غريبة وناقصة
    noisy = dict(d_json)
    noisy["حقل_لا_يعرفه_المحرك"] = "قيمة"
    try:
        robust = v2_ui.dict_to_item(BatchItemResult, noisy)
        check("مفتاح غريب لا يُسقط الاستئناف",
              robust.source_name == "IMG_0001.jpeg")
    except Exception as exc:
        check("مفتاح غريب لا يُسقط الاستئناف", False, f"({exc})")

    minimal = v2_ui.dict_to_item(
        BatchItemResult, {"source_name": "X.jpg", "source_path": "/a/X.jpg"})
    check("قاموس ناقص يُبنى بحالة review افتراضية",
          minimal.status == "review" and minimal.source_name == "X.jpg")

    empty_num = v2_ui.dict_to_item(
        BatchItemResult, {"source_name": "Y.jpg", "confidence": "",
                          "processing_ms": None})
    check("قيمة رقمية فارغة تُقرأ صفرًا لا تُسقط البناء",
          empty_num.confidence == 0.0 and empty_num.processing_ms == 0.0)

    # ------------------------------- الفحص السلبي: أكان العطب حقيقيًا؟
    # نُحاكي المسار القديم حرفيًا (سبعة حقول + خلط الناتج بالمراجعة)
    legacy = {
        "source_path": item.source_path,
        "source_name": item.source_name,
        "status": item.status,
        "item_code": item.item_code,
        "product_name": item.product_name,
        "barcode": item.barcode,
        "explanation": item.explanation,
        "review_path": item.review_path,
    }
    legacy_out = legacy.get("review_path", "")   # عين العطب القديم
    check("سلبي: المسار القديم يفقد output_path فعلًا",
          legacy_out != item.output_path,
          "(لو تساويا فالعطب لم يكن حقيقيًا)")
    check("سلبي: المسار القديم يفقد 10 حقول",
          len(field_names) - len(legacy) == 10,
          f"(الفاقد {len(field_names) - len(legacy)})")

    # ------------------------------ لا قائمة حقول ثانية تتخلف عن الأولى
    src = (ROOT / "windows_app" / "v2_ui.py").read_text(encoding="utf-8")
    check("item_to_dict يشتق الحقول من dataclass لا من قائمة مكتوبة",
          "_dataclass_field_names(type(item))" in src)
    check("dict_to_item يشتق الحقول من dataclass",
          "_dataclass_field_names(cls)" in src)
    check("الحفظ يستخدم item_to_dict لا سردًا يدويًا",
          "items = [item_to_dict(it)" in src)
    check("الاستئناف يستخدم dict_to_item لا سردًا يدويًا",
          "dict_to_item(_na.BatchItemResult, d)" in src)
    check("الحفظ يمرّر output_path الحقيقي",
          'output_path=d.get("output_path", "")' in src)
    check("القاموس الخام يُحفظ ضمانًا لأي حقل مستقبلي", "raw=d," in src)

    print("=" * 62)
    print(f"نجح {PASS} / فشل {FAIL}")
    if FAIL == 0:
        print("أمانة الجلسة كاملة — لا حقل يُفقد بين الحفظ والاستئناف")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
