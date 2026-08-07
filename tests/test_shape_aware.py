# -*- coding: utf-8 -*-
"""اختبار `shape_aware_v2` على حالات تحاكي أعطال المالك المقيسة.

الحالات مبنية على ما قِيس فعلًا في صور المالك السبع:
  1. كيس مقسوم كتلتين (10000017) — الفراغ يمتد طرفًا لطرف
  2. كيس فيه ثقوب داخلية (10000111-3: 16 ثقبًا)
  3. قنينة جانبها مقطوع (10000111: اكتمل بالتناظر +7143)
  4. علبة بشوائب حافية من الطاولة (م-24)
  5. صورة سليمة — لا يجوز أن تتغير (حرس عدم الإفساد)
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine_v2.shape_aware_v2 import (  # noqa: E402
    classify_shape, complete_product, mask_from_white, trim_edge_debris,
    unify_product_blocks)

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    if cond:
        print(f"  ✓ {msg}")
    else:
        print(f"  ✗ {msg}")
        FAILS.append(msg)


def _white(h=700, w=800) -> np.ndarray:
    return np.full((h, w, 3), 255, np.uint8)


# ═══════════════ 1. كيس مقسوم كتلتين (حالة 10000017) ═══════════════

def test_split_bag():
    print("\n[1] كيس مقسوم كتلتين — الفراغ من الطرف إلى الطرف")
    img = _white()
    # كتلتان زرقاوان متراصفتان يفصلهما شقّ أبيض عمودي 30px
    cv2.rectangle(img, (200, 120), (380, 560), (180, 60, 30), -1)
    cv2.rectangle(img, (412, 120), (600, 560), (180, 60, 30), -1)
    m = mask_from_white(img)

    n0, _, _, _ = cv2.connectedComponentsWithStats(m, 8)
    check(n0 - 1 == 2, f"القناع الأولي كتلتان ({n0 - 1})")

    uni, merged, bridged, bmask = unify_product_blocks(m)
    n1, _, _, _ = cv2.connectedComponentsWithStats(uni, 8)
    check(merged == 1, f"وُحّدت الكتلة الثانية (merged={merged})")
    check(n1 - 1 == 1, f"صار القناع كتلة واحدة ({n1 - 1})")
    check(bridged > 0, f"جُسر الفراغ ({bridged} بكسل)")
    check(int(bmask.sum()) > 0,
          f"قناع الجسر مُعاد للردم ({int(bmask.sum())} بكسل)")

    out, mm, rep = complete_product(img)
    area_ratio = int(mm.sum()) / max(1, int(m.sum()))
    check(1.02 <= area_ratio <= 1.30,
          f"المساحة نمت معقولًا ×{area_ratio:.2f} (لا نفخ)")
    # الفراغ المجسور يجب أن يُردم بنسيج لا يبقى أبيض
    strip = out[300:400, 385:410]
    check(strip.mean() < 240, f"الشقّ رُدم بنسيج (متوسط {strip.mean():.0f})")


# ═══════════════ 2. ثقوب داخلية (حالة 10000111-3) ═══════════════

def test_inner_holes():
    print("\n[2] كيس فيه ثقوب داخلية")
    img = _white()
    cv2.rectangle(img, (200, 120), (600, 560), (60, 140, 200), -1)
    for cx, cy, r in [(300, 250, 12), (420, 300, 16), (500, 420, 10),
                      (350, 480, 14)]:
        cv2.circle(img, (cx, cy), r, (255, 255, 255), -1)
    m0 = mask_from_white(img)
    out, mm, rep = complete_product(img)
    check(rep.holes_filled >= 4,
          f"رُدمت الثقوب الأربعة ({rep.holes_filled})")
    check(int(mm.sum()) > int(m0.sum()), "المساحة زادت بردم الثقوب")
    check(rep.grew_pct < 5.0, f"النمو ضئيل {rep.grew_pct:.2f}%")
    # موضع ثقب سابق يجب ألا يبقى أبيض
    check(out[300, 420].mean() < 245, "الثقب رُدم بنسيج المنتج")


# ═══════════════ 3. قنينة جانبها مقطوع (حالة 10000111) ═══════════════

def test_bottle_symmetry():
    print("\n[3] قنينة جانبها مقطوع — الإكمال بالتناظر")
    img = _white()
    # قنينة: عنق ضيق أعلى + جسم أوسع
    cv2.rectangle(img, (370, 100), (430, 190), (40, 90, 160), -1)
    cv2.rectangle(img, (300, 190), (500, 580), (40, 90, 160), -1)
    # قطع الجانب الأيمن من الجسم
    cv2.rectangle(img, (455, 300), (500, 430), (255, 255, 255), -1)

    m = mask_from_white(img)
    info = classify_shape(m)
    check(info.kind == "bottle",
          f"مُيّزت قنينة ({info.kind}، تناظر {info.v_symmetry:.2f})")

    out, mm, rep = complete_product(img)
    check(rep.symmetry_used, "استُعمل التناظر الرأسي للإكمال")
    check(int(mm.sum()) > int(m.sum()), "الجانب المقطوع اكتمل")
    check(mm[365, 470] > 0, "بكسل داخل القطع صار منتجًا")


# ═══════════════ 4. شوائب حافية (م-24) ═══════════════

def test_edge_debris():
    print("\n[4] شوائب الطاولة الملتصقة بحافة المنتج")
    img = _white()
    cv2.rectangle(img, (250, 150), (550, 550), (70, 160, 210), -1)
    # شائبة رمادية داكنة متصلة بالحافة السفلى (ظل طاولة)
    cv2.rectangle(img, (250, 550), (550, 566), (58, 58, 58), -1)
    # خطّ بلاط رمادي متصل بالحافة اليمنى
    cv2.rectangle(img, (550, 200), (562, 500), (72, 72, 72), -1)

    m = mask_from_white(img)
    before = int(m.sum())
    trimmed_mask, trimmed = trim_edge_debris(img, m)
    check(trimmed > 0, f"قُلّمت شوائب ({trimmed} بكسل)")
    lost = (before - int(trimmed_mask.sum())) / before * 100
    check(lost <= 4.5, f"الفقد داخل السقف {lost:.2f}% ≤ 4.5%")
    # جسم المنتج يجب أن يبقى سليمًا
    check(trimmed_mask[350, 400] > 0, "قلب المنتج لم يُمَس")
    # الشائبة السفلى يجب أن تُزال أو تُقلَّل
    band_before = int(m[551:566, 250:550].sum())
    band_after = int(trimmed_mask[551:566, 250:550].sum())
    check(band_after < band_before * 0.75,
          f"شائبة الظل قُلّمت ({band_before}→{band_after})")


# ═══════════════ 5. حرس عدم الإفساد ═══════════════

def test_clean_untouched():
    print("\n[5] صورة سليمة — حرس عدم الإفساد")
    img = _white()
    cv2.rectangle(img, (260, 160), (540, 540), (90, 150, 60), -1)
    m0 = mask_from_white(img)
    out, mm, rep = complete_product(img)
    delta = abs(int(mm.sum()) - int(m0.sum())) / max(1, int(m0.sum())) * 100
    check(delta < 2.0, f"القناع لم يتغير جوهريًا ({delta:.2f}%)")
    check(rep.holes_filled == 0, "لا ثقوب وهمية")
    check(rep.slits_filled == 0, "لا شقوق وهمية")
    diff = cv2.absdiff(img, out).mean()
    check(diff < 3.0, f"الصورة لم تتغير بصريًا (فرق {diff:.2f})")


def main():
    print("=" * 66)
    print("اختبار واعي الشكل والإكمال الذكي — حالات مبنية على قياس فعلي")
    print("=" * 66)
    test_split_bag()
    test_inner_holes()
    test_bottle_symmetry()
    test_edge_debris()
    test_clean_untouched()
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
