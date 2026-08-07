# -*- coding: utf-8 -*-
"""اختبار `straighten_v2` — التقويم بزوايا معروفة (حقيقة أرضية).

نبني منتجًا مستقيمًا بنص مطبوع، ندوّره بزاوية معلومة، ثم نطلب
من الوحدة تقديرها. الخطأ المقبول ≤1.5°.
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine_v2.straighten_v2 import (  # noqa: E402
    estimate_tilt, min_rect_angle, straighten, text_line_angle)

FAILS: list[str] = []


def check(c: bool, msg: str) -> None:
    print(("  ✓ " if c else "  ✗ ") + msg)
    if not c:
        FAILS.append(msg)


def make_product(with_text: bool = True) -> np.ndarray:
    """علبة مستقيمة عليها سطور نص أفقية."""
    img = np.full((700, 700, 3), 255, np.uint8)
    cv2.rectangle(img, (220, 160), (480, 540), (150, 70, 40), -1)
    if with_text:
        # سطور نص أفقية بيضاء
        for i, yy in enumerate(range(210, 500, 42)):
            wid = 200 if i % 2 == 0 else 150
            cv2.rectangle(img, (245, yy), (245 + wid, yy + 13),
                          (250, 250, 250), -1)
            # فواصل كلمات
            for xx in range(255, 245 + wid, 34):
                cv2.rectangle(img, (xx, yy), (xx + 5, yy + 13),
                              (150, 70, 40), -1)
    return img


def rotate(img: np.ndarray, deg: float) -> np.ndarray:
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1.0)
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_CONSTANT,
                          borderValue=(255, 255, 255))


def test_text_signal():
    print("\n[1] إشارة النص وحدها")
    base = make_product(True)
    for truth in (-8.0, -3.0, 4.0, 9.0):
        img = rotate(base, truth)
        ang, conf = text_line_angle(img)
        err = abs(ang - truth)
        check(err <= 1.5 and conf > 0.2,
              f"ميل {truth:+.0f}° ⇒ قُدّر {ang:+.2f}° "
              f"(خطأ {err:.2f}° ثقة {conf:.2f})")


def test_merged_estimate():
    print("\n[2] التقدير المدمج (أربع إشارات)")
    base = make_product(True)
    for truth in (-11.0, -5.0, 0.0, 6.0, 13.0):
        img = rotate(base, truth)
        est = estimate_tilt(img)
        err = abs(est.angle - truth)
        ok = err <= 1.5
        check(ok, f"ميل {truth:+.0f}° ⇒ {est.angle:+.2f}° "
                  f"(خطأ {err:.2f}° ثقة {est.confidence:.2f})")
        if not ok:
            print(f"      الإشارات: {est.signals}")


def test_no_text():
    print("\n[3] منتج بلا نص — الهندسة تتولّى")
    base = make_product(False)
    img = rotate(base, 7.0)
    est = estimate_tilt(img)
    err = abs(est.angle - 7.0)
    check(err <= 2.0, f"بلا نص: قُدّر {est.angle:+.2f}° (خطأ {err:.2f}°)")
    ang, conf = min_rect_angle(
        (255 - img.astype(np.int16)).max(axis=2).astype(np.uint8))
    check(conf > 0.0, f"إشارة المستطيل نشطة (ثقة {conf:.2f})")


def test_guards():
    print("\n[4] حدود السلامة")
    base = make_product(True)
    img = rotate(base, 31.0)
    est = estimate_tilt(img, max_auto_deg=20.0)
    check(est.needs_review,
          f"زاوية كبيرة {est.angle:+.1f}° ⇒ تحتاج مراجعة")
    blank = np.full((300, 300, 3), 255, np.uint8)
    est2 = estimate_tilt(blank)
    check(est2.angle == 0.0, "صورة فارغة ⇒ لا تقويم")


def test_apply():
    print("\n[5] تطبيق التقويم")
    base = make_product(True)
    img = rotate(base, -9.0)
    est = estimate_tilt(img)
    out, _ = straighten(img, -est.angle)
    check(out.shape[0] >= img.shape[0] and out.shape[1] >= img.shape[1],
          f"الإطار وُسّع {out.shape[1]}x{out.shape[0]}")
    est2 = estimate_tilt(out)
    check(abs(est2.angle) <= 1.5,
          f"بعد التقويم صار الميل {est2.angle:+.2f}° (≈0)")


def main():
    print("=" * 66)
    print("اختبار تقويم وضعية المنتج — زوايا معروفة")
    print("=" * 66)
    test_text_signal()
    test_merged_estimate()
    test_no_text()
    test_guards()
    test_apply()
    print("\n" + "=" * 66)
    if FAILS:
        print(f"إخفاقات: {len(FAILS)}")
        for f in FAILS:
            print(f"  · {f}")
        return 1
    print("كل الفحوص نجحت")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
