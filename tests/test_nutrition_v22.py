# -*- coding: utf-8 -*-
"""اختبار v2.2.0 لميزة حقائق التغذية — تحقق فعلي وليس مجرد استيراد.

يبني صورة منتج اصطناعية بجدول حقائق تغذية شبكي واضح، ثم:
1. كشف الجدول تلقائيًا (detect_nutrition_table)
2. تحويل خيارات نافذة الحقائق (dict) إلى ProcessOptionsV2 (_coerce_options)
3. معالجة كاملة بالأوضاع: merge_small / standalone / rebuild / remove
4. التحقق من مخرجات مجلد "حقائق التغذية" وملفات _تغذية.webp/json
5. rebuild بقيم معتمدة (nutrition_values) لا يعيد OCR
6. الوضع الافتراضي للدفعة set_default_nutrition
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "windows_app"))

import numpy as np
import cv2

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} — {detail}")


def make_product_with_table(path: Path) -> None:
    """صورة منتج 900×1200 عليها جدول شبكي أسفل اليمين."""
    img = np.full((1200, 900, 3), 245, np.uint8)
    # جسم المنتج (مستطيل ملون بارز على خلفية فاتحة)
    cv2.rectangle(img, (150, 100), (750, 1100), (60, 90, 200), -1)
    cv2.rectangle(img, (150, 100), (750, 1100), (30, 40, 90), 8)
    # جدول حقائق التغذية: شبكة خطوط داكنة داخل مساحة بيضاء
    x0, y0, x1, y1 = 420, 640, 730, 1060
    cv2.rectangle(img, (x0, y0), (x1, y1), (255, 255, 255), -1)
    cv2.rectangle(img, (x0, y0), (x1, y1), (0, 0, 0), 3)
    for i in range(1, 10):
        y = y0 + i * (y1 - y0) // 10
        cv2.line(img, (x0, y), (x1, y), (0, 0, 0), 2)
    cv2.line(img, ((x0 + x1) // 2, y0), ((x0 + x1) // 2, y1), (0, 0, 0), 2)
    # نص وهمي (خطوط قصيرة كأسطر نص)
    for i in range(10):
        y = y0 + 12 + i * (y1 - y0) // 10
        cv2.line(img, (x0 + 10, y + 8), (x0 + 120, y + 8), (20, 20, 20), 3)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    path.write_bytes(buf.tobytes())


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="nutri22_"))
    src = tmp / "منتج_10014649.png"
    make_product_with_table(src)
    out_dir = tmp / "out"
    out_dir.mkdir()

    # 1) كشف الجدول
    from engine_v2.nutrition_v2 import detect_nutrition_table
    img = cv2.imdecode(np.fromfile(str(src), np.uint8), 1)
    box = detect_nutrition_table(img)
    check("detect_nutrition_table يجد الجدول", box is not None, str(box))
    if box:
        x, y, w, h = box
        # يكفي أن المستطيل المكتشف يتقاطع مع منطقة الجدول الحقيقية
        # (الصورة الاصطناعية لها إطار منتج قد يُلتقط أيضًا —
        #  في الواقع المستخدم يؤكد/يصحح التحديد في النافذة)
        ix0, iy0 = max(x, 420), max(y, 640)
        ix1, iy1 = min(x + w, 730), min(y + h, 1060)
        inter = max(0, ix1 - ix0) * max(0, iy1 - iy0)
        table_area = (730 - 420) * (1060 - 640)
        check("موضع الكشف يغطي منطقة الجدول",
              inter >= table_area * 0.6, f"got {box}")

    # 2) تحويل dict نافذة الحقائق إلى ProcessOptionsV2
    from engine_v2.integration_v2 import (_coerce_options,
                                          set_default_nutrition,
                                          set_override, clear_overrides,
                                          IMAGE_OVERRIDES, DEFAULT_NUTRITION)
    dlg_settings = {
        "nutrition_mode": "merge_small",
        "nutrition_bbox": (420 / 900, 640 / 1200, 730 / 900, 1060 / 1200),
        "nutrition_source": str(src),
        "nutrition_anchor": "bottom_left",
        "nutrition_scale": 0.3,
        "nutrition_offset": (0.0, 0.0),
        "nutrition_values": None,
    }
    opts = _coerce_options(dict(dlg_settings), str(src))
    from engine_v2.processor_v2 import ProcessOptionsV2
    check("_coerce_options يعيد ProcessOptionsV2",
          isinstance(opts, ProcessOptionsV2), type(opts).__name__)
    check("الوضع منقول", opts.nutrition_mode == "merge_small",
          opts.nutrition_mode)
    check("bbox محول من نسب إلى بكسلات (x,y,w,h)",
          opts.nutrition_bbox is not None and
          abs(opts.nutrition_bbox[0] - 420) <= 2 and
          abs(opts.nutrition_bbox[2] - 310) <= 3,
          str(opts.nutrition_bbox))
    check("InsetPlacement مبني", opts.nutrition_placement is not None and
          opts.nutrition_placement.anchor == "bottom_left" and
          abs(opts.nutrition_placement.scale - 0.3) < 1e-6,
          str(opts.nutrition_placement))

    # set_override يقبل dict ويحوله
    clear_overrides()
    set_override(str(src), dict(dlg_settings))
    check("set_override يخزن ProcessOptionsV2 وليس dict",
          isinstance(IMAGE_OVERRIDES.get(str(src)), ProcessOptionsV2))
    clear_overrides()

    # 3) معالجة فعلية بالأوضاع الأربعة
    from engine_v2.paths_v2 import models_dir
    from engine_v2.processor_v2 import ProcessorV2
    proc = ProcessorV2(models_dir())

    # merge_small
    o1 = _coerce_options(dict(dlg_settings), str(src))
    r1 = proc.process(str(src), str(out_dir / "10014649_حبه.webp"), o1)
    check("merge_small: المعالجة نجحت", r1.ok, r1.error)
    check("merge_small: الناتج موجود",
          (out_dir / "10014649_حبه.webp").is_file())

    # standalone → مجلد "حقائق التغذية"
    s2 = dict(dlg_settings); s2["nutrition_mode"] = "standalone"
    o2 = _coerce_options(s2, str(src))
    r2 = proc.process(str(src), str(out_dir / "10014649_قوة.webp"), o2)
    nut_dir = out_dir / "حقائق التغذية"
    check("standalone: المعالجة نجحت", r2.ok, r2.error)
    check("standalone: صورة الجدول المستقلة أنتجت",
          bool(r2.nutrition_output_path) and
          Path(r2.nutrition_output_path).is_file(),
          r2.nutrition_output_path)
    # من 2.3: الصورة المنفردة تُحفظ **بجانب صور الصنف** وتُرقّم ضمنها
    # وفق سياسة التسمية (10014649_قوة-1) لتُرفع للمتجر مباشرة،
    # وترجع لمجلد "حقائق التغذية" فقط إن تعذر تحليل الاسم.
    _np = Path(r2.nutrition_output_path) if r2.nutrition_output_path else None
    _beside = bool(_np) and _np.parent == out_dir and "10014649" in _np.stem
    _legacy = nut_dir.is_dir() and any(nut_dir.glob("*_تغذية.webp"))
    check("standalone: تُرقّم بجانب صور الصنف (أو مجلد التغذية)",
          _beside or _legacy,
          f"path={r2.nutrition_output_path} beside={_beside} "
          f"legacy={_legacy}")
    if _beside:
        check("standalone: لا تدوس الناتج الرئيسي",
              _np.name != "10014649_قوة.webp", _np.name)

    # rebuild بقيم معتمدة (لا OCR — تطابق 100%)
    from engine_v2.nutrition_ocr_v2 import blank_template
    data = blank_template()
    data.calories = "250"
    data.serving_size = "30 غ"
    s3 = dict(dlg_settings)
    s3["nutrition_mode"] = "rebuild"
    s3["nutrition_values"] = data.to_dict()
    o3 = _coerce_options(s3, str(src))
    check("rebuild: القيم المعتمدة منقولة للمعالج",
          o3.nutrition_values and o3.nutrition_values.get("calories") == "250")
    r3 = proc.process(str(src), str(out_dir / "10014649_كرتون.webp"), o3)
    check("rebuild: المعالجة نجحت", r3.ok, r3.error)
    check("rebuild: جدول معاد الصياغة أنتج",
          bool(r3.nutrition_output_path) and
          Path(r3.nutrition_output_path).is_file(),
          r3.nutrition_output_path or ";".join(r3.warnings))
    json_files = list(nut_dir.glob("*_تغذية.json"))
    check("rebuild: JSON القيم محفوظ", bool(json_files))
    if json_files:
        import json
        saved = json.loads(json_files[-1].read_text(encoding="utf-8"))
        check("rebuild: القيم المعتمدة نفسها في JSON (تطابق 100%)",
              saved.get("calories") == "250", str(saved.get("calories")))

    # remove: إزالة الجدول من الصورة
    s4 = dict(dlg_settings); s4["nutrition_mode"] = "remove"
    o4 = _coerce_options(s4, str(src))
    r4 = proc.process(str(src), str(out_dir / "10014649_ربطة.webp"), o4)
    check("remove: المعالجة نجحت", r4.ok, r4.error)
    check("remove: تحذير الإزالة مسجل",
          any("أُزيل" in w for w in r4.warnings), ";".join(r4.warnings))

    # 4) الوضع الافتراضي للدفعة
    set_default_nutrition({"nutrition_mode": "standalone",
                           "nutrition_anchor": "bottom_left",
                           "nutrition_scale": 0.28})
    o5 = _coerce_options(None, str(src))
    check("default batch: يطبق على الصور بلا override",
          o5.nutrition_mode == "standalone", o5.nutrition_mode)
    set_default_nutrition(None)
    o6 = _coerce_options(None, str(src))
    check("default batch: التعطيل يعيد الوضع none",
          o6.nutrition_mode == "none", o6.nutrition_mode)

    # 5) OCR الذكي متاح (بنية فقط — دقة OCR تعتمد على tesseract)
    try:
        from engine_v2.nutrition_smart_v2 import smart_extract  # noqa
        check("smart_extract متاح للاستدعاء", callable(smart_extract))
    except Exception as exc:
        check("smart_extract متاح للاستدعاء", False, str(exc))

    print(f"\nنتيجة: {PASS} ناجح / {FAIL} فاشل")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
