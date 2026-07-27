# -*- coding: utf-8 -*-
"""اختبارات المحرك الذكي للحقائق الغذائية — صور جداول اصطناعية."""
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from engine_v2.nutrition_ocr_v2 import NutritionData, NutritionRow  # noqa
from engine_v2.nutrition_smart_v2 import (detect_table_region,  # noqa
                                          smart_extract,
                                          validate_consistency)


def _make_table_image() -> np.ndarray:
    """جدول حقائق إنجليزي بسيط أبيض بخط واضح (OCR-friendly)."""
    img = np.full((640, 520, 3), 255, np.uint8)
    f = cv2.FONT_HERSHEY_SIMPLEX
    rows = [
        ("Nutrition Facts", 1.0, 3),
        ("Serving Size 30 g", 0.7, 2),
        ("Servings Per Container 8", 0.6, 2),
        ("Calories 120", 0.9, 2),
        ("Total Fat 4 g 6%", 0.7, 2),
        ("Saturated Fat 1 g 5%", 0.6, 1),
        ("Sodium 150 mg 7%", 0.7, 2),
        ("Total Carbohydrate 18 g 6%", 0.7, 2),
        ("Sugars 9 g", 0.6, 1),
        ("Protein 3 g", 0.7, 2),
    ]
    y = 50
    for text, scale, th in rows:
        cv2.putText(img, text, (20, y), f, scale, (0, 0, 0), th, cv2.LINE_AA)
        y += 55
        cv2.line(img, (15, y - 38), (505, y - 38), (0, 0, 0), 2)
    cv2.rectangle(img, (10, 10), (510, y - 20), (0, 0, 0), 3)
    return img


def test_smart_extract_reads_values():
    res = smart_extract(_make_table_image())
    assert res.ok, "لم يُستخرج أي شيء"
    assert res.data.calories == "120", f"calories={res.data.calories!r}"
    keys = {r.key: r for r in res.data.rows}
    assert "total_fat" in keys and keys["total_fat"].amount == "4"
    assert "protein" in keys and keys["protein"].amount == "3"
    # القيم المتفق عليها بين تمريرات متعددة يجب ألا تكون كلها للمراجعة
    assert res.passes_used >= 2


def test_no_invention_on_blank():
    """صورة فارغة = لا قيم مخترعة إطلاقًا (قاعدة المصداقية)."""
    blank = np.full((400, 400, 3), 255, np.uint8)
    res = smart_extract(blank)
    assert not res.data.rows and not res.data.calories


def test_validate_consistency_flags_impossible():
    d = NutritionData(calories="10")
    d.rows = [NutritionRow("total_fat", "الدهون الكلية", "50"),
              NutritionRow("total_carbs", "الكربوهيدرات الكلية", "50"),
              NutritionRow("protein", "البروتين", "50"),
              NutritionRow("saturated_fat", "الدهون المشبعة", "60")]
    warns = validate_consistency(d)
    assert any("السعرات" in w for w in warns)
    assert any("المشبعة" in w for w in warns)
    # التحقق لا يعدل القيم — تنبيه فقط
    assert d.rows[0].amount == "50"


def test_detect_region_never_loses_all():
    img = _make_table_image()
    region = detect_table_region(img)
    assert region.shape[0] >= 80 and region.shape[1] >= 80


if __name__ == "__main__":
    for name in ["test_smart_extract_reads_values", "test_no_invention_on_blank",
                 "test_validate_consistency_flags_impossible",
                 "test_detect_region_never_loses_all"]:
        globals()[name]()
        print("OK ", name)
    print("\nall nutrition smart tests passed")
