# -*- coding: utf-8 -*-
"""اختبار `product_finish_v2` — استرجاع الحواف والاقتصاص والظل التلقائي."""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine_v2.product_finish_v2 import (  # noqa: E402
    auto_shadow_opts, drop_specks, fill_inner_holes, finish_product,
    reclaim_edges, smart_crop_box)

FAILS: list[str] = []


def check(c: bool, msg: str) -> None:
    print(("  ✓ " if c else "  ✗ ") + msg)
    if not c:
        FAILS.append(msg)


def test_reclaim():
    print("\n[1] استرجاع طرف مقطوع — النمو المتصل")
    img = np.full((500, 500, 3), 240, np.uint8)
    cv2.rectangle(img, (150, 120), (350, 400), (60, 120, 190), -1)
    truth = np.zeros((500, 500), np.uint8)
    cv2.rectangle(truth, (150, 120), (350, 400), 255, -1)
    a = truth.copy()
    a[:, 320:] = 0                        # قصّ الشريط الأيمن
    missing = int(((truth > 0) & (a == 0)).sum())

    out, got = reclaim_edges(img, a, max_grow_pct=20.0)
    before = int(((truth > 0) & (a > 127)).sum())
    after = int(((truth > 0) & (out > 127)).sum())
    ratio = (after - before) / max(1, missing)
    check(ratio >= 0.85, f"استُرجع {ratio*100:.0f}% من الطرف المقطوع")
    leak = int(((truth == 0) & (out > 127)).sum())
    check(leak <= missing * 0.12, f"جرّ الخلفية ضئيل ({leak} بكسل)")


def test_holes_and_specks():
    print("\n[2] ردم الثقوب وإسقاط البقع")
    a = np.zeros((400, 400), np.uint8)
    cv2.rectangle(a, (100, 100), (300, 300), 255, -1)
    cv2.circle(a, (200, 200), 15, 0, -1)
    cv2.circle(a, (30, 30), 5, 255, -1)
    filled, nh = fill_inner_holes(a)
    check(nh == 1, f"رُدم ثقب واحد ({nh})")
    check(filled[200, 200] > 127, "مركز الثقب صار منتجًا")
    clean, ns = drop_specks(a)
    check(ns == 1, f"أُسقطت بقعة واحدة ({ns})")
    check(clean[30, 30] == 0, "البقعة أُزيلت")


def test_crop():
    print("\n[3] الاقتصاص المحسوب يضيق بعد إسقاط البقع")
    a = np.zeros((700, 800), np.uint8)
    cv2.rectangle(a, (300, 250), (500, 450), 255, -1)
    cv2.circle(a, (20, 20), 4, 255, -1)
    x0, y0, w0, h0 = smart_crop_box(a)
    clean, _ = drop_specks(a)
    x1, y1, w1, h1 = smart_crop_box(clean)
    check(w1 * h1 < w0 * h0 * 0.6,
          f"ضاق الإطار من {w0}x{h0} إلى {w1}x{h1}")


def test_auto_shadow():
    print("\n[4] الظل التلقائي يتغير بشكل المنتج")
    flat = np.zeros((400, 400), np.uint8)
    cv2.rectangle(flat, (60, 180), (340, 260), 255, -1)
    tall = np.zeros((400, 400), np.uint8)
    cv2.rectangle(tall, (170, 60), (230, 340), 255, -1)

    of = auto_shadow_opts(flat)
    ot = auto_shadow_opts(tall)
    check(of.kind == "contact", "ظل تلامس للمفلطح")
    check(ot.opacity > of.opacity,
          f"الطولي أكثف ({ot.opacity:.2f} > {of.opacity:.2f})")
    check(of.contact_height_ratio > ot.contact_height_ratio,
          f"المفلطح أوسع ({of.contact_height_ratio:.3f} > "
          f"{ot.contact_height_ratio:.3f})")
    empty = auto_shadow_opts(np.zeros((50, 50), np.uint8))
    check(empty.kind == "none", "قناع فارغ ⇒ لا ظل")


def test_finish_pipeline():
    print("\n[5] التشطيب الكامل")
    img = np.full((700, 800, 3), 245, np.uint8)
    cv2.rectangle(img, (250, 200), (550, 500), (80, 150, 200), -1)
    a = np.zeros((700, 800), np.uint8)
    cv2.rectangle(a, (250, 200), (550, 500), 255, -1)
    cv2.circle(a, (400, 350), 14, 0, -1)
    cv2.circle(a, (40, 40), 4, 255, -1)

    out_img, out_a, rep = finish_product(img, a)
    check(out_img.shape[0] < 700 and out_img.shape[1] < 800,
          f"الصورة اقتُصّت إلى {out_img.shape[1]}x{out_img.shape[0]}")
    check(rep.specks_dropped >= 1, f"البقع أُسقطت ({rep.specks_dropped})")
    check(rep.holes_filled >= 1, f"الثقوب رُدمت ({rep.holes_filled})")
    check(rep.crop_shrink_pct > 40,
          f"ضاق الإطار {rep.crop_shrink_pct:.0f}%")
    check(out_img.shape[:2] == out_a.shape[:2],
          "الصورة والألفا متوافقتان في المقاس")


def main():
    print("=" * 64)
    print("اختبار تشطيب المنتج — الحواف والاقتصاص والظل التلقائي")
    print("=" * 64)
    test_reclaim()
    test_holes_and_specks()
    test_crop()
    test_auto_shadow()
    test_finish_pipeline()
    print("\n" + "=" * 64)
    if FAILS:
        print(f"إخفاقات: {len(FAILS)}")
        for f in FAILS:
            print(f"  · {f}")
        return 1
    print("كل الفحوص نجحت")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
