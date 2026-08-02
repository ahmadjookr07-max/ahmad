# -*- coding: utf-8 -*-
"""اختبار مدمج: الظل الواقعي + خط المعالجة الكامل من الأصل إلى WebP.

يعوّض الاختبارات القديمة (test_shadow_v2 / test_shadow_single /
test_engine_rebuild / test_integration / test_rebuild_mode) التي كانت مربوطة
بمسارات ساندبوكس محذوفة `/home/ubuntu/v2_project/`. هنا تُولَّد كل الأصول
محليًا فلا يعتمد الاختبار على أي شيء خارج المستودع.
"""
import shutil
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine_v2.shadow_v2 import (ShadowOptions, apply_shadow,
                                 apply_shadow_on_white, build_shadow_layer,
                                 make_contact_shadow, make_drop_shadow)

PASS, FAIL = [], []


def check(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name +
          (f" — {note}" if note else ""))


def make_product(w=800, h=700):
    """منتج صناعي: زجاجة مستطيلة وسط لوحة شفافة، مع قناع ألفا حاد."""
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    x0, x1 = int(w * 0.35), int(w * 0.65)
    y0, y1 = int(h * 0.15), int(h * 0.88)
    rgba[y0:y1, x0:x1, :3] = (40, 120, 200)
    rgba[y0:y1, x0:x1, 3] = 255
    # عنق أضيق أعلى المنتج
    nx0, nx1 = int(w * 0.45), int(w * 0.55)
    rgba[int(h * 0.08):y0, nx0:nx1, :3] = (30, 100, 170)
    rgba[int(h * 0.08):y0, nx0:nx1, 3] = 255
    return rgba, (x0, y0, x1, y1)


D = Path(tempfile.mkdtemp(prefix="mis_shadow_"))
try:
    rgba, (x0, y0, x1, y1) = make_product()
    alpha = rgba[:, :, 3]
    H, W = alpha.shape

    # ---------------------------------------------------- ظل التلامس
    o = ShadowOptions(kind="contact", opacity=0.4)
    contact = make_contact_shadow(alpha, o, (H, W))
    check("contact_shape", contact.shape == (H, W), str(contact.shape))
    check("contact_nonempty", int(contact.max()) > 0, str(int(contact.max())))
    # ظل التلامس يجب أن يتمركز عند قاعدة المنتج لا أعلاه
    top_half = int(contact[:y0, :].sum())
    base_band = int(contact[max(0, y1 - 40):min(H, y1 + 40), :].sum())
    check("contact_at_base", base_band > top_half,
          f"base={base_band} top={top_half}")

    # ---------------------------------------------------- الظل المسقط
    o2 = ShadowOptions(kind="drop", opacity=0.45, drop_angle_deg=35.0)
    drop = make_drop_shadow(alpha, o2, (H, W))
    check("drop_nonempty", int(drop.max()) > 0, str(int(drop.max())))
    # بزاوية 35° الظل يميل يمينًا: كثافته يمين المنتج أكبر من يساره
    right = int(drop[:, x1:].sum())
    left = int(drop[:, :x0].sum())
    check("drop_direction_right", right > left, f"يمين={right} يسار={left}")

    # الزاوية المعاكسة تعكس الاتجاه فعلًا
    o3 = ShadowOptions(kind="drop", opacity=0.45, drop_angle_deg=145.0)
    drop2 = make_drop_shadow(alpha, o3, (H, W))
    check("drop_direction_flips",
          int(drop2[:, :x0].sum()) > int(drop2[:, x1:].sum()),
          f"يسار={int(drop2[:, :x0].sum())} يمين={int(drop2[:, x1:].sum())}")

    # ---------------------------------------------------- الشدة والطبقة
    # ملاحظة: build_shadow_layer يبني الشكل فقط؛ الشدة تُطبّق عند
    # التركيب في apply_shadow — لذا نقيسها على الناتج النهائي
    lo = apply_shadow_on_white(rgba.copy(),
                               ShadowOptions(kind="both", opacity=0.15))
    hi = apply_shadow_on_white(rgba.copy(),
                               ShadowOptions(kind="both", opacity=0.75))
    # كلما ارتفعت الشدة قلّ مجموع السطوع (الصورة تعتم أكثر)
    check("opacity_monotonic", int(hi.sum()) < int(lo.sum()),
          f"0.75={int(hi.sum())} < 0.15={int(lo.sum())}")

    layer = build_shadow_layer(alpha, ShadowOptions(kind="both"), (H, W))
    check("layer_both_nonempty", int(layer.max()) > 0, str(int(layer.max())))

    none_layer = build_shadow_layer(alpha, ShadowOptions(kind="none"), (H, W))
    check("kind_none_empty", int(none_layer.sum()) == 0,
          str(int(none_layer.sum())))

    # ---------------------------------------------------- التركيب
    composed = apply_shadow(rgba.copy(), ShadowOptions(kind="both"))
    check("apply_shadow_rgba", composed.shape[2] == 4, str(composed.shape))
    # المنتج نفسه لا يتغير: بكسلات داخله تبقى كما هي
    inner = (slice(y0 + 20, y1 - 20), slice(x0 + 20, x1 - 20))
    check("product_untouched",
          np.array_equal(composed[inner][:, :, :3], rgba[inner][:, :, :3]))

    on_white = apply_shadow_on_white(rgba.copy(), ShadowOptions(kind="contact"))
    check("on_white_is_bgr", on_white.ndim == 3 and on_white.shape[2] == 3,
          str(on_white.shape))
    # الخلفية بيضاء لكن ليست بيضاء تمامًا في منطقة الظل
    corner = on_white[0:10, 0:10]
    check("white_bg_corner", int(corner.min()) >= 250, str(int(corner.min())))
    shadow_zone = on_white[min(H - 1, y1 + 5):min(H, y1 + 25), x0:x1]
    check("shadow_darkens_bg", int(shadow_zone.min()) < 250,
          str(int(shadow_zone.min())))

    # ---------------------------------------------------- تسلسل الخيارات
    d = ShadowOptions(kind="drop", opacity=0.5, drop_angle_deg=42.0).to_dict()
    back = ShadowOptions.from_dict(d)
    check("options_roundtrip",
          back.kind == "drop" and abs(back.opacity - 0.5) < 1e-9
          and abs(back.drop_angle_deg - 42.0) < 1e-9)
    check("options_ignores_unknown",
          ShadowOptions.from_dict({"kind": "contact", "zzz": 1}).kind
          == "contact")

    # ---------------------------------------------------- خط المعالجة الكامل
    # يعمل فقط بوجود نموذج القص؛ يُتخطى بأمان في بيئة بلا نماذج
    src = D / "منتج_اختبار.jpg"
    bgr = np.full((900, 1200, 3), 245, dtype=np.uint8)
    cv2.rectangle(bgr, (400, 200), (800, 780), (60, 130, 210), -1)
    cv2.imwrite(str(src), bgr)

    model_found = False
    try:
        from engine_v2.paths_v2 import models_dir
        md = models_dir()
        model_found = bool(md) and any(Path(md).glob("*.onnx"))
    except Exception:
        model_found = False

    if not model_found:
        print("  SKIP pipeline_end_to_end — لا نماذج ONNX في هذه البيئة "
              "(تُنزَّل في خط البناء)")
    else:
        from engine_v2.processor_v2 import ProcessOptionsV2, ProcessorV2
        proc = ProcessorV2(md)
        out = D / "10001043_حبه.webp"
        res = proc.process(src, out, ProcessOptionsV2(
            width=800, height=700, margin=40, enhance=True,
            webp_lossless=True, shadow_preset="contact"))
        check("pipeline_no_error", not res.error, res.error or "")
        check("pipeline_wrote_file", out.exists() and out.stat().st_size > 0,
              f"{out.stat().st_size // 1024} KB" if out.exists() else "مفقود")
        if out.exists():
            got = cv2.imread(str(out), cv2.IMREAD_UNCHANGED)
            check("pipeline_exact_size", got is not None
                  and got.shape[0] == 700 and got.shape[1] == 800,
                  str(None if got is None else got.shape))
            # خلفية بيضاء في الزوايا
            check("pipeline_white_bg",
                  got is not None and int(got[0:8, 0:8, :3].min()) >= 245,
                  str(None if got is None else int(got[0:8, 0:8, :3].min())))
            # الأسم العربي كُتب وقُرئ بلا تلف (imread/imwrite unicode)
            check("pipeline_unicode_name", "حبه" in out.name)
finally:
    shutil.rmtree(D, ignore_errors=True)

print(f"\n===== {len(PASS)} passed / {len(FAIL)} failed =====")
if FAIL:
    print("FAILED:", FAIL)
sys.exit(0 if not FAIL else 1)
