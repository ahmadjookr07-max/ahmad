# -*- coding: utf-8 -*-
"""اختبارات معالجة الحواف الصعبة والتعلم المحلي."""
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from engine_v2.edge_refine_v2 import (detect_uncertain_edges,  # noqa
                                      feather_edges, refine_alpha,
                                      remove_halo, smart_suggestions)
from engine_v2 import learning_v2 as L  # noqa


def _product_with_alpha():
    """منتج دائري على خلفية خضراء + alpha حادة."""
    img = np.full((300, 300, 3), (60, 170, 90), np.uint8)   # خلفية خضراء
    cv2.circle(img, (150, 150), 90, (30, 60, 200), -1)      # منتج أحمر
    alpha = np.zeros((300, 300), np.uint8)
    cv2.circle(alpha, (150, 150), 90, 255, -1)
    return img, alpha


def test_refine_alpha_keeps_solid_interior():
    img, alpha = _product_with_alpha()
    refined = refine_alpha(img, alpha)
    assert refined.dtype == np.uint8 and refined.shape == alpha.shape
    assert refined[150, 150] == 255          # الداخل الصلب لم يتغير
    assert refined[10, 10] <= 5              # الخارج بقي شفافًا
    # الحافة أصبحت متدرجة (يوجد قيم وسطية)
    band = refined[(alpha > 0) ^ cv2.erode(alpha, np.ones((9, 9),
                                           np.uint8)).astype(bool)]
    assert ((band > 5) & (band < 250)).any()


def test_remove_halo_pulls_bg_color_out():
    img, alpha = _product_with_alpha()
    # لوّث الحافة بلون الخلفية
    edge = cv2.morphologyEx(alpha, cv2.MORPH_GRADIENT,
                            np.ones((5, 5), np.uint8)) > 0
    img[edge] = (60, 170, 90)
    soft = feather_edges(alpha, 3)
    out = remove_halo(img, soft)
    ys, xs = np.nonzero(edge)
    # المتوسط الأخضر على الحافة انخفض (تلوث أقل)
    assert int(out[ys, xs, 1].mean()) < int(img[ys, xs, 1].mean())


def test_detect_uncertain_edges_finds_weak_regions():
    # منتج بلون الخلفية نفسه تقريبًا = حواف مشكوك فيها
    img = np.full((300, 300, 3), 245, np.uint8)
    cv2.circle(img, (150, 150), 90, (238, 238, 238), -1)
    alpha = np.zeros((300, 300), np.uint8)
    cv2.circle(alpha, (150, 150), 90, 255, -1)
    rects = detect_uncertain_edges(img, alpha)
    assert rects, "يجب كشف مناطق حواف ضعيفة التباين"


def test_smart_suggestions_dark_image():
    img = np.full((200, 200, 3), 40, np.uint8)
    sugg = smart_suggestions(img)
    keys = [s["key"] for s in sugg]
    assert "brightness" in keys
    assert all("label_ar" in s and "reason_ar" in s for s in sugg)


def test_learning_roundtrip():
    L.reset()
    L.record_enhance_strength(0.7)
    L.record_enhance_strength(0.7)
    assert abs(L.suggest_enhance_strength() - 0.7) < 0.01
    L.record_nutrition_placement("top_right", 0.35)
    assert L.suggest_nutrition_anchor() == "top_right"
    text = L.summary_ar()
    assert "محلي" in text
    L.reset()
    assert L.suggest_nutrition_anchor() == "bottom_left"


if __name__ == "__main__":
    for name in list(globals()):
        if name.startswith("test_"):
            globals()[name]()
            print("OK ", name)
    print("\nall edge/learning tests passed")
