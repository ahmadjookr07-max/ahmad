# -*- coding: utf-8 -*-
"""اختبارات الربط البصري الذكي وكشف التكرارات بالمحتوى."""
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from engine_v2.visual_match_v2 import (ImageSignature, build_signature,  # noqa
                                       find_content_duplicates, hamming,
                                       pair_similarity, phash,
                                       suggest_links)


def _product(color, shape="circle", size=260, noise=0):
    img = np.full((size, size, 3), 255, np.uint8)
    if shape == "circle":
        cv2.circle(img, (size // 2, size // 2), size // 3, color, -1)
    else:
        cv2.rectangle(img, (size // 5, size // 5),
                      (size * 4 // 5, size * 4 // 5), color, -1)
    if noise:
        n = np.random.default_rng(7).integers(-noise, noise,
                                              img.shape, dtype=np.int16)
        img = np.clip(img.astype(np.int16) + n, 0, 255).astype(np.uint8)
    return img


def test_phash_stable_under_resize_and_jpeg():
    img = _product((30, 60, 200))
    h1 = phash(img)
    resized = cv2.resize(img, (128, 128))
    ok, enc = cv2.imencode(".jpg", resized,
                           [cv2.IMWRITE_JPEG_QUALITY, 70])
    dec = cv2.imdecode(enc, cv2.IMREAD_COLOR)
    assert hamming(h1, phash(dec)) <= 12


def test_same_product_two_faces_similar():
    # وجهان لنفس المنتج: نفس الألوان بشكلين مختلفين
    front = _product((30, 60, 200), "circle")
    back = _product((30, 60, 200), "rect")
    other = _product((200, 160, 40), "circle")
    sf = build_signature("front.png", front)
    sb = build_signature("back.png", back)
    so = build_signature("other.png", other)
    assert pair_similarity(sf, sb) > pair_similarity(sf, so)


def test_suggest_links_picks_right_item():
    front = build_signature("u1.png", _product((30, 60, 200), "circle"))
    linked = {
        "10001": [build_signature("a.png", _product((30, 60, 200), "rect"))],
        "10002": [build_signature("b.png", _product((40, 200, 60), "rect"))],
    }
    sugg = suggest_links([front], linked, threshold=0.5)
    assert sugg and sugg[0]["item_code"] == "10001"
    assert "level_ar" in sugg[0]


def test_find_content_duplicates():
    img = _product((90, 40, 170))
    dup = cv2.resize(cv2.resize(img, (200, 200)), (260, 260))
    diff = _product((10, 220, 220))
    sigs = [build_signature("x1.png", img),
            build_signature("x2.png", dup),
            build_signature("y.png", diff)]
    groups = find_content_duplicates(sigs)
    assert any(set(g) == {"x1.png", "x2.png"} for g in groups)


if __name__ == "__main__":
    for name in list(globals()):
        if name.startswith("test_"):
            globals()[name]()
            print("OK ", name)
    print("\nall visual match tests passed")
