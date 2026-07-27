# -*- coding: utf-8 -*-
"""اختبارات محرك الجودة الواعي بالنص + طمس التواريخ.

يبني صورة منتج اصطناعية بنص دقيق وتاريخ مطبوع، ثم يتحقق:
1) smart_downscale يحافظ على مقروئية أعلى من التصغير التقليدي.
2) enhance_preserving_text لا يقلل المقروئية.
3) detect_date_regions يجد التاريخ، وauto_blur_dates يجعله غير مقروء
   مع بقاء باقي النص واضحًا.
4) polish_output_file يعمل على ملف webp ناتج.
"""
import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import cv2
import numpy as np

PASS = []
FAIL = []


def check(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  ({note})" if note else ""))


def make_product_image(w=2000, h=1800):
    """عبوة منتج اصطناعية: مستطيل ملون + نص مكونات دقيق + تاريخ مطبوع."""
    img = np.full((h, w, 3), 255, np.uint8)
    # جسم العبوة
    cv2.rectangle(img, (400, 200), (1600, 1600), (60, 120, 200), -1)
    cv2.rectangle(img, (450, 260), (1550, 500), (240, 240, 245), -1)
    cv2.putText(img, "PREMIUM COOKIES", (480, 380),
                cv2.FONT_HERSHEY_SIMPLEX, 1.6, (30, 30, 30), 3, cv2.LINE_AA)
    # نص مكونات دقيق (محاكاة نص صغير على العبوة)
    small = ["INGREDIENTS: WHEAT FLOUR, SUGAR, PALM OIL,",
             "COCOA POWDER, SALT, RAISING AGENTS, LECITHIN",
             "ENERGY 480 KCAL  PROTEIN 6.2G  FAT 21G",
             "CARBOHYDRATE 68G  SUGARS 24G  SODIUM 0.3G"]
    y = 700
    for line in small:
        cv2.putText(img, line, (470, y), cv2.FONT_HERSHEY_SIMPLEX,
                    0.75, (25, 25, 25), 1, cv2.LINE_AA)
        y += 46
    # تاريخ مطبوع أسفل العبوة (محاكاة inkjet)
    cv2.putText(img, "PROD 12/03/2025", (520, 1480),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (20, 20, 20), 2, cv2.LINE_AA)
    cv2.putText(img, "EXP 12/03/2026", (520, 1540),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (20, 20, 20), 2, cv2.LINE_AA)
    return img


def main():
    from engine_v2.quality_v2 import (adaptive_text_sharpen,
                                      enhance_preserving_text,
                                      polish_output_file, readability_score,
                                      smart_downscale, text_saliency_map)
    from engine_v2.date_blur_v2 import (auto_blur_dates, blur_region_manual,
                                        detect_date_regions)

    img = make_product_image()

    # 1) saliency يجد نصًا
    sal = text_saliency_map(img)
    check("text_saliency_nonempty", float((sal > 0.35).mean()) > 0.005,
          f"coverage={(sal > 0.35).mean():.4f}")

    # 2) smart_downscale مقابل تصغير تقليدي
    naive = cv2.resize(img, (800, 700), interpolation=cv2.INTER_AREA)
    smart = smart_downscale(img, 800, 700)
    rs_naive = readability_score(naive)
    rs_smart = readability_score(smart)
    check("smart_downscale_better", rs_smart >= rs_naive,
          f"smart={rs_smart:.2f} naive={rs_naive:.2f}")

    # 3) OCR على النص الدقيق بعد التصغير الذكي — مقروء
    # (النص يصبح ~7px بعد التصغير؛ tesseract يحتاج تكبير القص للقراءة —
    # المهم أن التفاصيل محفوظة في البكسلات ويقرأها العميل عند التكبير)
    try:
        import pytesseract
        crop = smart[240:340, 180:390]
        crop = cv2.resize(crop, None, fx=3, fy=3,
                          interpolation=cv2.INTER_CUBIC)
        txt = pytesseract.image_to_string(crop, lang="eng").upper()
        crop_n = naive[240:340, 180:390]
        crop_n = cv2.resize(crop_n, None, fx=3, fy=3,
                            interpolation=cv2.INTER_CUBIC)
        txt_n = pytesseract.image_to_string(crop_n, lang="eng").upper()
        ok_smart = "INGREDIENTS" in txt or "WHEAT" in txt or "PROTEIN" in txt
        check("small_text_readable_after_smart", ok_smart,
              txt.replace("\n", " ")[:60])
    except Exception as e:
        check("small_text_readable_after_smart", False, str(e))

    # 4) التحسين الحافظ للنص لا يقلل المقروئية
    enh = enhance_preserving_text(img)
    check("enhance_preserving_text",
          readability_score(enh) >= readability_score(img) * 0.98,
          f"before={readability_score(img):.2f} after={readability_score(enh):.2f}")

    # 5) كشف التاريخ
    regions = detect_date_regions(img)
    found = any("EXP" in r.text.upper() or "PROD" in r.text.upper()
                or "2025" in r.text or "2026" in r.text for r in regions)
    check("date_detected", found,
          f"n={len(regions)} texts={[r.text[:20] for r in regions[:4]]}")

    # 6) الطمس التلقائي يجعل التاريخ غير مقروء والنص الآخر يبقى
    blurred, n = auto_blur_dates(img)
    check("auto_blur_applied", n > 0, f"n={n}")
    try:
        import pytesseract
        txt_b = pytesseract.image_to_string(blurred, lang="eng").upper()
        date_gone = "12/03/2025" not in txt_b and "12/03/2026" not in txt_b
        others_ok = "INGREDIENTS" in txt_b or "WHEAT" in txt_b or "COOKIES" in txt_b
        check("date_unreadable_after_blur", date_gone, txt_b.replace("\n", " ")[:60])
        check("other_text_preserved", others_ok)
    except Exception as e:
        check("date_unreadable_after_blur", False, str(e))

    # 7) الطمس اليدوي بلون المنتج
    manual = blur_region_manual(img, (500, 1440, 500, 130))
    diff = np.abs(manual.astype(int) - img.astype(int)).mean()
    check("manual_blur_works", diff > 0.05, f"diff={diff:.3f}")
    # المنطقة المطموسة قريبة من لون العبوة المحيط (وليست سوداء/بيضاء)
    patch = manual[1470:1520, 550:900].reshape(-1, 3).mean(axis=0)
    check("manual_blur_color_match",
          abs(int(patch[2]) - 200) < 70 and abs(int(patch[0]) - 60) < 70,
          f"bgr={patch.astype(int)}")

    # 8) polish_output_file على ملف ناتج
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "out.webp")
        ok, buf = cv2.imencode(".webp", naive, [cv2.IMWRITE_WEBP_QUALITY, 94])
        buf.tofile(p)
        rep = polish_output_file(p, quality=101)
        check("polish_output_file", rep.error == "" and rep.after >= rep.before,
              f"before={rep.before:.2f} after={rep.after:.2f} improved={rep.improved}")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
    print("ALL QUALITY/DATE TESTS PASSED")


if __name__ == "__main__":
    main()
