# -*- coding: utf-8 -*-
"""توليد «بيانات مالك» اصطناعية لفكّ حجب الاختبارات الحقيقية.

المشكلة: سبعة اختبارات (test_full_run, test_real_batch, test_match_speed,
test_legacy_real_owner, test_owner_units_real, test_link_units_new_side,
test_editor_save_both_sides) تتخطّى نفسها لغياب `MIS_OWNER_DATA`.
فتبقى مساراتها الحقيقية (المعالجة الكاملة، سرعة المطابقة، ترقية المجلد
المنجز، تسمية الوحدات) **غير مفحوصة** — وهذا أخطر من الفشل الصريح.

الحل هنا: بناء تجويفة (fixture) بنفس **شكل** بيانات المالك:

    <root>/
      اصناف.xlsx                 كتالوج بأعمدة المالك العربية
      زيت/زيت/*.jpeg             صور خام (أسماء GUID مثل كاميرا الآيفون)
      منجز/processed/*.jpeg      مخرجات مجلد منجز سابقًا
      منجز/job_state.json        حالة عمل سابقة

هذه ليست بيانات المالك الحقيقية ولا تدّعي ذلك: هي بديل بنيوي يجعل
الكود يمرّ بمساره الحقيقي بدل أن يُتخطّى. الاختبارات الحقيقية تبقى
أقوى متى توفّرت بيانات المالك الفعلية.

الاستعمال:
    python3 tests/make_owner_fixture.py [الجذر]
    export MIS_OWNER_DATA=<الجذر>
"""
from __future__ import annotations

import json
import random
import sys
import uuid
from pathlib import Path

import cv2
import numpy as np

DEFAULT_ROOT = Path("/home/ubuntu/owner_data")

# أصناف بأنماط أسماء المالك الحقيقية: وحدة داخل الاسم، مقاسات متنوعة،
# وأسماء متشابهة بعضها ببعض (لاختبار المطابقة لا مجرد الوجود).
BASE_ITEMS: list[tuple[str, str, str, str]] = [
    ("10012345", "6281000000012", "بادك زيت زيتون بكر ممتاز 1لتر", "حبه"),
    ("10012346", "6281000000019", "بادك زيت زيتون بكر ممتاز 500مل", "حبه"),
    ("10012347", "6281000000026", "بادك زيت ذرة 1.5لتر", "حبه"),
    ("10014649", "6281000000033", "شامبو صن سلك ناعم 400مل", "حبه"),
    ("10014650", "6281000000040", "شامبو صن سلك كيرلي 400مل", "حبه"),
    ("10021777", "6281000000057", "ارز بشاور طويل 5كيلو", "كيس"),
    ("10021778", "6281000000064", "ارز بشاور طويل 10كيلو", "كيس"),
    ("10031002", "6281000000071", "تونة الشيف قطع بالزيت 185جم", "كرتون"),
    ("10031003", "6281000000088", "تونة الشيف قطع بالماء 185جم", "حبه"),
    ("10045511", "6281000000095", "معجون اسنان سيجنال 120مل", "حبه"),
    ("10045512", "6281000000101", "معجون اسنان سيجنال 75مل", "حبه"),
    ("10052233", "6281000000118", "حليب المراعي طويل الاجل 1لتر", "حبه"),
]

# مولد كتالوج بحجم إكسل المالك (نحو 50ألف سجل) — الاختبارات
# الحقيقية مكتوبة على الحجم لا الشكل وحده: تشترط >1000 سجل،
# و>100 صنف متعدد الوحدات، لأن مسار المطابقة والتسريع لا
# يُختبر فعليًا على عشرات الأسطر.
_BRANDS = ("بادك", "المراعي", "نادك", "الشيف", "سديم", "الوطنية",
           "الرابح", "قودي", "لورين", "فارمرز", "العلالي", "زين")
_KINDS = ("زيت زيتون", "زيت ذرة", "زيت عباد الشمس", "أرز بشاور",
          "أرز مزة", "تونة قطع", "تونة مفرومة", "شامبو", "بلسم",
          "معجون اسنان", "صابون سائل", "حليب طويل الاجل", "لبن زبادي",
          "جبن مبروش", "شاي أخضر", "قهوة سريعة التحضير", "عسل طبيعي",
          "مربى فراولة", "معكرونة اسباجتي", "شوربة دجاج", "كتشب",
          "مايونيز", "خل تفاح", "سكر ناعم", "دقيق فاخر", "ملح طعام",
          "مناديل ورقية", "منظف ارضيات", "مسحوق غسيل", "معطر جو")
_SIZES = ("100مل", "200مل", "400مل", "500مل", "750مل", "1لتر", "1.5لتر",
          "2لتر", "5لتر", "90جم", "185جم", "200جم", "400جم", "900جم",
          "1كيلو", "2كيلو", "5كيلو", "10كيلو", "12حبة", "24حبة")
_UNITS = ("حبه", "كيس", "كرتون", "شدة", "علبة", "درزن")


def build_catalog_rows(total: int = 50311) -> list[tuple[str, str, str, str]]:
    """يبني كتالوجًا بحجم واقعي: أسماء متشابهة ووحدات متعددة.

    التشابه مقصود: مسار المطابقة يُختبر فعليًا فقط حين توجد
    مرشّحات منافسة قريبة (نفس الماركة والنوع بمقاسات مختلفة).
    """
    rng = random.Random(913_004)
    rows: list[tuple[str, str, str, str]] = list(BASE_ITEMS)
    seen = {r[0] for r in rows}
    code = 10_100_000
    while len(rows) < total:
        brand = rng.choice(_BRANDS)
        kind = rng.choice(_KINDS)
        size = rng.choice(_SIZES)
        name = f"{brand} {kind} {size}"
        # للصنف الواحد أحيانًا عدة وحدات (حبه/شدة/كرتون) — وهو جوهر
        # قاعدة التسمية متعددة الوحدات
        unit_count = 1 if rng.random() < 0.55 else rng.randint(2, 3)
        units = rng.sample(_UNITS, unit_count)
        code += rng.randint(1, 4)
        item = str(code)
        if item in seen:
            continue
        seen.add(item)
        for unit_index, unit in enumerate(units):
            if len(rows) >= total:
                break
            barcode = ean13_checkdigit(f"628{code:07d}{unit_index}")
            rows.append((item, barcode, name, unit))
    return rows


def ean13_checkdigit(digits12: str) -> str:
    """يردّ باركود EAN-13 كاملًا (13 خانة) من 12 خانة.

    ضروري لأن الباركود المرسوم يُقرأ بخانة التحقق الصحيحة؛
    فإن خالفت ما في الكتالوج فشلت المطابقة بلا ذنب التطبيق.
    """
    digits = [int(ch) for ch in str(digits12)[:12]]
    check = (10 - sum(d * (3 if i % 2 else 1)
                      for i, d in enumerate(digits)) % 10) % 10
    return "".join(str(d) for d in digits) + str(check)


def _fix_barcodes(
        items: "list[tuple[str, str, str, str]]"
) -> "list[tuple[str, str, str, str]]":
    """يُعيد حساب خانة التحقق لكل باركود في القائمة."""
    return [(code, ean13_checkdigit(bar), name, unit)
            for code, bar, name, unit in items]


# تصحيح إلزامي: الأرقام المكتوبة يدويًا أعلاه لا تحمل خانة
# تحقق EAN-13 صحيحة، فكان الباركود المرسوم يُقرأ برقم مختلف
# عمّا في الكتالوج فتفشل المطابقة (صفر مطابقة) بلا ذنب التطبيق.
BASE_ITEMS = _fix_barcodes(BASE_ITEMS)

ITEMS = BASE_ITEMS   # يُستخدم لتوليد الصور (عينة مقروءة للعين)


def _ean13_bars(digits12: str) -> "list[int]":
    """يولّد نمط أعمدة EAN-13 (95 وحدة) من 12 رقمًا.

    التوليد يدوي لأن مسار المطابقة في التطبيق يقرأ الباركود
    بـ zxingcpp، فلا يُختبر فعليًا ما لم تحمل الصورة باركودًا
    حقيقيًا قابلًا للقراءة (لا خطوطًا عشوائية).
    """
    left_odd = ("0001101", "0011001", "0010011", "0111101", "0100011",
                "0110001", "0101111", "0111011", "0110111", "0001011")
    left_even = ("0100111", "0110011", "0011011", "0100001", "0011101",
                 "0111001", "0000101", "0010001", "0001001", "0010111")
    right = ("1110010", "1100110", "1101100", "1000010", "1011100",
             "1001110", "1010000", "1000100", "1001000", "1110100")
    parity = ("OOOOOO", "OOEOEE", "OOEEOE", "OOEEEO", "OEOOEE",
              "OEEOOE", "OEEEOO", "OEOEOE", "OEOEEO", "OEEOEO")
    digits = [int(ch) for ch in digits12[:12]]
    checksum = (10 - sum(d * (3 if i % 2 else 1)
                         for i, d in enumerate(digits)) % 10) % 10
    all_digits = digits + [checksum]
    pattern = "101"
    for i, d in enumerate(all_digits[1:7]):
        pattern += (left_odd[d] if parity[all_digits[0]][i] == "O"
                    else left_even[d])
    pattern += "01010"
    for d in all_digits[7:]:
        pattern += right[d]
    pattern += "101"
    return [int(ch) for ch in pattern]


def _draw_barcode(img: "np.ndarray", digits12: str, x0: int, y0: int,
                  width: int, height: int) -> None:
    """يرسم باركود EAN-13 حقيقيًا على أرضية بيضاء مع هوامش."""
    bars = _ean13_bars(digits12)
    # سماكة الوحدة لا تقل عن 3 بكسل: مع 95 وحدة يحتاج
    # الباركود عرضًا فعليًا كافيًا، وإلا عجز zxingcpp عن قراءته
    # (كان يفشل في 68 من 109 صورة بوحدة بكسلين).
    unit = max(3, width // (len(bars) + 8))
    quiet = unit * 9                      # هامش صامت إلزامي للقراءة
    real_w = unit * len(bars) + quiet * 2
    real_h = max(height, unit * 22)       # ارتفاع كافٍ للمسح
    cv2.rectangle(img, (x0, y0), (x0 + real_w, y0 + real_h),
                  (255, 255, 255), -1)
    for index, bit in enumerate(bars):
        if not bit:
            continue
        bx = x0 + quiet + index * unit
        cv2.rectangle(img, (bx, y0 + unit), (bx + unit - 1,
                                             y0 + real_h - unit),
                      (0, 0, 0), -1)


def _product_image(seed: int, label: str, unit: str,
                   barcode: str | None = None) -> "np.ndarray":
    """عبوة اصطناعية على خلفية فاتحة — بأبعاد وألوان مختلفة كل مرة."""
    rng = random.Random(seed)
    h, w = rng.choice([(1600, 1200), (1200, 900), (2000, 1500)])
    bg = rng.randint(228, 244)
    img = np.full((h, w, 3), bg, np.uint8)
    # ظل خفيف تحت العبوة ليشبه صورة كاميرا حقيقية
    cv2.ellipse(img, (w // 2, int(h * 0.86)), (int(w * 0.26), int(h * 0.03)),
                0, 0, 360, (bg - 22, bg - 22, bg - 20), -1)
    bw, bh = int(w * 0.34), int(h * 0.62)
    x0, y0 = (w - bw) // 2, int(h * 0.20)
    color = (rng.randint(40, 170), rng.randint(50, 170), rng.randint(60, 190))
    cv2.rectangle(img, (x0, y0), (x0 + bw, y0 + bh), color, -1)
    # ملصق أبيض عليه نص لاتيني (OCR العربي غير مضمون على صور اصطناعية)
    lx0, ly0 = x0 + int(bw * 0.08), y0 + int(bh * 0.10)
    lx1, ly1 = x0 + bw - int(bw * 0.08), y0 + int(bh * 0.42)
    cv2.rectangle(img, (lx0, ly0), (lx1, ly1), (252, 252, 252), -1)
    cv2.putText(img, label[:10], (lx0 + 10, ly0 + int((ly1 - ly0) * 0.45)),
                cv2.FONT_HERSHEY_SIMPLEX, w / 1400, (30, 30, 30), 2)
    cv2.putText(img, unit, (lx0 + 10, ly0 + int((ly1 - ly0) * 0.85)),
                cv2.FONT_HERSHEY_SIMPLEX, w / 1800, (60, 60, 60), 2)
    # تاريخ مطبوع أسفل العبوة — يغذّي مسار كشف/طمس التواريخ
    cv2.putText(img, "EXP 12/2027",
                (x0 + int(bw * 0.06), y0 + bh - int(bh * 0.06)),
                cv2.FONT_HERSHEY_SIMPLEX, w / 2200, (245, 245, 245), 2)
    # باركود EAN-13 حقيقي أسفل الملصق — بدونه يبقى مسار
    # المطابقة بالباركود غير مفحوص (صفر مطابقة)
    if barcode:
        digits = "".join(ch for ch in barcode if ch.isdigit())[:12]
        if len(digits) == 12:
            # الباركود يأخذ عرض الصورة لا عرض العبوة الضيق،
            # لأن 95 وحدة داخل 34% من العرض تنتج أعمدة رقيقة
            # جدًا لا تُقرأ.
            bc_w = int(w * 0.72)
            bc_h = max(90, int(h * 0.09))
            bx0 = (w - bc_w) // 2
            by0 = int(h * 0.87) - bc_h // 2
            _draw_barcode(img, digits, bx0, by0, bc_w, bc_h)
    return img


def build(root: Path, catalog_rows: int = 50311,
          raw_images: int = 109) -> None:
    raw = root / "زيت" / "زيت"
    legacy = root / "منجز"
    processed = legacy / "processed"
    for directory in (raw, processed):
        directory.mkdir(parents=True, exist_ok=True)

    # 1) كتالوج بأعمدة المالك وبحجمه الواقعي (write_only لتفادي ذاكرة ضخمة)
    import openpyxl
    rows = build_catalog_rows(catalog_rows)
    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet("الاصناف")
    ws.append(["رقم الصنف", "الباركود", "اسم الصنف", "الوحدة"])
    for row in rows:
        ws.append(list(row))
    catalog = root / "اصنافعالمعنترة.xlsx"
    wb.save(str(catalog))

    # 2) صور خام: أكثرها بأسماء GUID (كاميرا الآيفون)، وثلثها بأسماء
    #    تحوي مسافات — وهي الحالة التي كسرت المطابقة عند المالك
    #    ("صورة 2.jpg")، ويتحقق منها test_real_batch صراحةً.
    rng = random.Random(20260804)
    created: list[Path] = []
    spaced_target = max(1, raw_images // 3)
    for index in range(raw_images):
        _code, bar, name, unit = ITEMS[index % len(ITEMS)]
        # الباركود مرسوم فعليًا ليمرّ مسار المطابقة الحقيقي
        img = _product_image(index * 7, name.split()[0], unit, bar)
        if index < spaced_target:
            # ترقيم بلا أصفار بادئة مطابقًا لنمط المالك الحقيقي
            # ("صورة 2.jpg"). الصيغة المصفوفة السابقة (01؁02…)
            # أنتجت خلطًا بين صيغتين، فدفعت "صورة 2.jpg" خارج
            # أول عينة (spaced[:8]) فأعلن test_real_batch إخفاقًا زائفًا.
            path = raw / f"صورة {index + 1}.jpg"
        else:
            guid = str(uuid.UUID(int=rng.getrandbits(128))).upper()
            path = raw / f"{guid}.jpeg"
        cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
        created.append(path)

    # 3) مجلد منجز سابقًا: مخرجات بأسماء نهائية — نصفها ناقص الوحدة
    #    (رقم الصنف وحده) لأن الاختبارات تقيس قدرة الخطة على تصحيحها
    #    من الإكسل، وتشترط أكثر من 100 مجموعة ليُعدّ الفحص جادًّا.
    seen_stems: set[str] = set()
    legacy_count = 0
    for index, (code, _bar, name, unit) in enumerate(rows[:900]):
        if legacy_count >= 320:
            break
        # النصف ناقص الوحدة (رقم الصنف وحده) ليُختبر تصحيح
        # الخطة له، والنصف الآخر على القاعدة الصحيحة.
        bare = index % 2 == 0
        stem = code if bare else f"{code}_{unit}"
        if stem in seen_stems:
            continue
        seen_stems.add(stem)
        cv2.imwrite(str(processed / f"{stem}.jpeg"),
                    _product_image(500 + index, name.split()[0], unit, _bar),
                    [cv2.IMWRITE_JPEG_QUALITY, 88])
        legacy_count += 1
        # الصورة الإضافية بلاحقة -2 تُكتب فقط على جذع يحمل وحدة،
        # لأن `{رقم}-2` بلا وحدة صيغة لا ينتجها التطبيق أبدًا
        # ولا يملك ما يربطها به (أي وحدة هي الثانية؟).
        if not bare and index % 3 == 0:
            cv2.imwrite(str(processed / f"{stem}-2.jpeg"),
                        _product_image(900 + index, name.split()[0], unit,
                                       _bar),
                        [cv2.IMWRITE_JPEG_QUALITY, 88])
            legacy_count += 1

    state = {
        "version": "2.9.9",
        "catalog": str(catalog),
        "created_at": "2026-08-04T00:00:00",
        "items": [{"code": c, "name": n, "unit": u}
                  for c, _b, n, u in rows[:20]],
    }
    (legacy / "job_state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    spaced = sum(1 for p in created if " " in p.name)
    codes = len({r[0] for r in rows})
    print(f"جذر التجويفة : {root}")
    print(f"كتالوج       : {catalog.name} — {len(rows)} سجلًا / "
          f"{codes} رقم صنف")
    print(f"صور خام      : {len(created)} في {raw} "
          f"(منها {spaced} بمسافات)")
    print(f"مجلد منجز    : {processed} — "
          f"{len(list(processed.glob('*.jpeg')))} مخرجًا")
    print("\nصدِّر المسار ثم شغّل الاختبارات:")
    print(f"  export MIS_OWNER_DATA={root}")


if __name__ == "__main__":
    args = sys.argv[1:]
    target = Path(args[0]) if args else DEFAULT_ROOT
    rows_n = int(args[1]) if len(args) > 1 else 50311
    imgs_n = int(args[2]) if len(args) > 2 else 109
    build(target, rows_n, imgs_n)
