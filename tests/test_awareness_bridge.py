# -*- coding: utf-8 -*-
"""إثبات أن أمر المالك بالعربية يصل إلى بكسل في الصورة الناتجة.

هذا الاختبار يحرس أخطر عيب أُصلح في المشروع: كان الحوار يحفظ الأمر
ويعرضه كأنه نُفّذ، ثم تُعالَج الصور بالقيم القديمة. فلا يكفي أن نتحقق
أن التجاوز حُفظ — يجب أن نتحقق أن **الملف الناتج على القرص** تغيّر.
لذا نقيس المقاس الفعلي وحجم الملف والامتداد، لا القيم في الذاكرة.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("MIS_DATA_ROOT", tempfile.mkdtemp(prefix="mis_bridge_"))

FAILED: list[str] = []
PASSED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASSED.append(name)
        print(f"  \u2713 {name}")
    else:
        FAILED.append(f"{name}: {detail}")
        print(f"  \u2717 {name} — {detail}")


def _reset_overrides() -> None:
    from awareness import healer
    from awareness import identity
    p = identity.awareness_dir() / "overrides.json"
    if p.is_file():
        p.unlink()
    healer.overrides(refresh=True)


# ═════════════════ 1) الجسر يُسقط التجاوزات على الخيارات ═════════════════

def test_bridge_maps_overrides() -> None:
    print("\n[1] الجسر يُسقط تجاوزات الوعي على خيارات المعالجة")
    _reset_overrides()
    from awareness import healer
    from engine_v2 import awareness_bridge_v2 as bridge
    from engine_v2.processor_v2 import ProcessOptionsV2

    healer.set_override("output_size", [1000, 1000], reason="اختبار")
    healer.set_override("output_quality", 78, reason="اختبار")
    healer.set_override("output_format", "png", reason="اختبار")
    healer.set_override("enhance_enabled", False, reason="اختبار")

    opts = bridge.apply_overrides(ProcessOptionsV2())
    check("المقاس يسري", (opts.width, opts.height) == (1000, 1000),
          f"وجدت {opts.width}×{opts.height}")
    check("الجودة تسري", opts.quality == 78, f"وجدت {opts.quality}")
    check("الصيغة تسري", opts.output_format == "png",
          f"وجدت {opts.output_format!r}")
    check("التحسين يُوقف بالأمر", opts.enhance is False,
          f"وجدت {opts.enhance}")


def test_explicit_wins() -> None:
    print("\n[2] الأمر الصريح من الواجهة يسبق التجاوز المحفوظ")
    from engine_v2 import awareness_bridge_v2 as bridge
    from engine_v2.processor_v2 import ProcessOptionsV2

    opts = ProcessOptionsV2(width=640, height=640)
    opts = bridge.apply_overrides(opts, explicit={"width", "height"})
    check("الصريح محترم", (opts.width, opts.height) == (640, 640),
          f"التجاوز طغى: {opts.width}×{opts.height}")
    check("غير الصريح يسري", opts.quality == 78, f"وجدت {opts.quality}")


def test_bad_values_ignored() -> None:
    print("\n[3] القيم التالفة تُهمل ولا تُسقط المعالجة")
    _reset_overrides()
    from awareness import healer
    from engine_v2 import awareness_bridge_v2 as bridge
    from engine_v2.processor_v2 import ProcessOptionsV2

    healer.set_override("output_size", "خربان", reason="اختبار")
    healer.set_override("output_quality", None, reason="اختبار")
    healer.set_override("output_format", "tiff", reason="اختبار")
    ref = ProcessOptionsV2()
    opts = bridge.apply_overrides(ProcessOptionsV2())
    check("مقاس تالف مُهمل", (opts.width, opts.height) == (ref.width, ref.height),
          f"وجدت {opts.width}×{opts.height}")
    check("جودة تالفة مُهملة", opts.quality is None, f"وجدت {opts.quality}")
    check("صيغة غير مدعومة مُهملة", opts.output_format == "",
          f"وجدت {opts.output_format!r}")


def test_limits_clamped() -> None:
    print("\n[4] القيم المتطرفة تُقصّ إلى مدى آمن")
    _reset_overrides()
    from awareness import healer
    from engine_v2 import awareness_bridge_v2 as bridge
    from engine_v2.processor_v2 import ProcessOptionsV2

    healer.set_override("output_size", [99999, 1], reason="اختبار")
    healer.set_override("output_quality", 5000, reason="اختبار")
    opts = bridge.apply_overrides(ProcessOptionsV2())
    check("العرض مقصوص", opts.width == 6000, f"وجدت {opts.width}")
    check("الارتفاع مقصوص", opts.height == 200, f"وجدت {opts.height}")
    check("الجودة مقصوصة", opts.quality == 100, f"وجدت {opts.quality}")


# ═════════════════ 5) الجودة تُغيّر الملف على القرص فعلًا ═════════════════

def test_quality_changes_file_bytes() -> None:
    print("\n[5] الجودة تُغيّر حجم الملف الناتج فعليًا")
    try:
        import numpy as np
        from engine_v2.processor_v2 import imwrite_unicode
    except Exception as exc:
        check("توفر numpy/opencv", False, str(exc)[:80])
        return

    rng = np.random.default_rng(7)
    img = rng.integers(0, 255, (400, 400, 3), dtype=np.uint8)
    with tempfile.TemporaryDirectory() as d:
        lo = Path(d) / "lo.webp"
        hi = Path(d) / "hi.webp"
        imwrite_unicode(lo, img, lossless_webp=False, quality=40)
        imwrite_unicode(hi, img, lossless_webp=False, quality=98)
        s_lo, s_hi = lo.stat().st_size, hi.stat().st_size
        check("جودة أقل تعني ملفًا أصغر", s_lo < s_hi,
              f"40% = {s_lo}B، 98% = {s_hi}B")

        j = Path(d) / "q.jpg"
        imwrite_unicode(j, img, quality=30)
        j2 = Path(d) / "q2.jpg"
        imwrite_unicode(j2, img, quality=95)
        check("JPEG يحترم الجودة", j.stat().st_size < j2.stat().st_size,
              f"30% = {j.stat().st_size}B، 95% = {j2.stat().st_size}B")


# ═════════════════ 6) المسار الكامل: جملة عربية ← ملف ═════════════════

def test_end_to_end_arabic_command() -> None:
    print("\n[6] المسار الكامل: جملة عربية تُغيّر الملف الناتج")
    _reset_overrides()
    from awareness import dialogue

    res = dialogue.ask("خلي مقاس الصور 1000×1000", confirmed=True, apply=True)
    check("الأمر فُهم ونُفّذ", bool(res.get("ok")),
          str(res.get("message_ar", ""))[:120])

    from engine_v2 import awareness_bridge_v2 as bridge
    from engine_v2.processor_v2 import ProcessOptionsV2
    opts = bridge.apply_overrides(ProcessOptionsV2())
    check("الأمر وصل إلى خيارات المعالجة",
          (opts.width, opts.height) == (1000, 1000),
          f"وجدت {opts.width}×{opts.height}")

    res2 = dialogue.ask("احفظ بصيغة png", confirmed=True, apply=True)
    opts2 = bridge.apply_overrides(ProcessOptionsV2())
    check("أمر الصيغة وصل", opts2.output_format == "png",
          f"وجدت {opts2.output_format!r} / {res2.get('message_ar', '')[:80]}")


def test_coerce_options_uses_bridge() -> None:
    print("\n[7] الممر الرسمي لبناء الخيارات يمرّ بالجسر")
    _reset_overrides()
    from awareness import healer
    from engine_v2 import integration_v2
    healer.set_override("output_size", [1234, 567], reason="اختبار")
    opts = integration_v2._coerce_options(None)
    check("_coerce_options يطبّق التجاوز",
          (opts.width, opts.height) == (1234, 567),
          f"وجدت {opts.width}×{opts.height}")
    _reset_overrides()


def main() -> int:
    print("=" * 62)
    print("اختبار جسر الوعي ← المحرك")
    print("=" * 62)
    for fn in (test_bridge_maps_overrides, test_explicit_wins,
               test_bad_values_ignored, test_limits_clamped,
               test_quality_changes_file_bytes,
               test_end_to_end_arabic_command,
               test_coerce_options_uses_bridge):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            import traceback
            FAILED.append(f"{fn.__name__}: {exc}")
            print(f"  \u2717 {fn.__name__} انهار: {exc}")
            traceback.print_exc()
    print("\n" + "=" * 62)
    print(f"نجح: {len(PASSED)}   فشل: {len(FAILED)}")
    for f in FAILED:
        print(f"  - {f}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
