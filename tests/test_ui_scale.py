"""اختبارات محرك المقياس التلقائي — بلا Qt، سريعة وحاسمة."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows_app"))

from ui_scale import ScaleEngine  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, label: str) -> None:
    print(("PASS  " if condition else "FAIL  ") + label)
    if not condition:
        FAILURES.append(label)


def main() -> int:
    # 1) المعامل يقل مع صغر الشاشة ويزيد مع كبرها — سلوك رتيب
    sizes = [(800, 600), (1024, 600), (1024, 700), (1280, 800),
             (1366, 768), (1440, 900), (1600, 900), (1920, 1080), (2560, 1440)]
    factors = [ScaleEngine.compute_factor(w, h) for w, h in sizes]
    for (w, h), f in zip(sizes, factors):
        print(f"    {w}x{h} -> factor={f:.3f}")
    check(factors[0] < factors[3] < factors[-1],
          "المعامل يتصاعد مع اتساع الشاشة (رتيب)")
    check(all(ScaleEngine.MIN_FACTOR <= f <= ScaleEngine.MAX_FACTOR
              for f in factors), "كل المعاملات داخل الحدود المسموحة")

    # 2) شاشة صغيرة تُصغّر فعليًا، وشاشة مرجعية تبقى 1.0
    check(ScaleEngine.compute_factor(800, 600) < 0.80,
          "800×600 يحصل على تصغير ملموس (<0.80)")
    ref = ScaleEngine.compute_factor(ScaleEngine.REF_WIDTH,
                                     ScaleEngine.REF_HEIGHT)
    check(abs(ref - 1.0) < 0.02, "المساحة المرجعية تبقى بمعامل 1.0 تقريبًا")

    # 3) أي حجم غير مختبر يعطي معاملًا صالحًا — الذكاء التلقائي
    odd = [(937, 641), (1111, 733), (1723, 981), (3840, 2160), (640, 480)]
    ok = True
    for w, h in odd:
        f = ScaleEngine.compute_factor(w, h)
        if not (ScaleEngine.MIN_FACTOR <= f <= ScaleEngine.MAX_FACTOR):
            ok = False
        print(f"    غير مختبر {w}x{h} -> {f:.3f}")
    check(ok, "أحجام غير مختبرة كلها تُعطي معاملًا صالحًا (بلا قائمة ثابتة)")

    # 4) تحجيم نظام التشغيل يقلّص المعامل
    plain = ScaleEngine.compute_factor(1920, 1080, 1.0)
    scaled150 = ScaleEngine.compute_factor(1920, 1080, 1.5)
    check(scaled150 < plain, "تحجيم Windows 150% يقلّص المعامل تلقائيًا")

    # 5) الخط لا ينزل تحت أرضية القراءة
    small = ScaleEngine.for_size(800, 600)
    check(small.font(22) >= ScaleEngine.MIN_FONT_PX
          and small.font(9) >= ScaleEngine.MIN_FONT_PX,
          "لا خط ينزل تحت أرضية القراءة")
    check(small.font(22) < 22, "الخط الكبير يُصغّر فعليًا على شاشة صغيرة")
    # الخط يتقلص أقل من المسافة (تصغير لطيف)
    ratio_font = small.font(20) / 20
    ratio_dim = small.px(20) / 20
    print(f"    نسبة الخط={ratio_font:.3f} نسبة البُعد={ratio_dim:.3f}")
    check(ratio_font > ratio_dim,
          "الخط يتقلص أقل من المسافات (المسافة تُفرَّج أولًا)")

    # 6) تحويل ورقة الأنماط
    sheet = ("QLabel#a { font-size: 22px; padding: 6px 12px; "
             "border: 1px solid #fff; border-radius: 13px; }")
    out = small.scale_stylesheet(sheet)
    print(f"    {out}")
    check("font-size: 22px" not in out, "حجم الخط في الورقة تغيّر")
    check("border: 1px solid #fff" in out,
          "سماكة الحد لم تُمس (تفادي اختفاء الإطارات)")
    check("#fff" in out, "الألوان سليمة بعد التحويل")
    check("border-radius: 13px" not in out, "نصف القطر تقلّص")

    # 7) عتبة إعادة التنسيق
    eng = ScaleEngine(0.80)
    check(not eng.differs_from(0.81), "فرق ضئيل لا يستدعي إعادة تنسيق")
    check(eng.differs_from(0.90), "فرق ملموس يستدعي إعادة تنسيق")

    print(f"\nإجمالي: نجاح={7 * 0 + (17 - len(FAILURES))}  فشل={len(FAILURES)}")
    if FAILURES:
        for f in FAILURES:
            print("  - " + f)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
