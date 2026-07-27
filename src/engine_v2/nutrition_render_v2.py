# -*- coding: utf-8 -*-
"""nutrition_render_v2 — إعادة بناء جدول حقائق التغذية كتصميم عربي قياسي.

يرسم النمط الأسود/الأبيض القياسي: عنوان "الحقائق الغذائية" عريض، عدد الحصص،
حجم الحصة، السعرات بخط كبير، صفوف % القيمة اليومية بخطوط فاصلة، هامش سفلي.
ملاحظة رموز مؤكدة: NotoNaskhArabic لا يحوي % — استخدم ٪ (U+066A)
و٭ (U+066D) بدل *.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .nutrition_ocr_v2 import NutritionData, FOOTNOTE_AR

_ASSETS = Path(__file__).parent / "assets"

_AR_DIGITS_OUT = str.maketrans("0123456789.", "٠١٢٣٤٥٦٧٨٩٫")


def _to_ar_digits(s: str) -> str:
    return str(s).translate(_AR_DIGITS_OUT)


def _find_font(bold: bool) -> str:
    name = "NotoNaskhArabic-Bold.ttf" if bold else "NotoNaskhArabic-Regular.ttf"
    try:
        from .paths_v2 import assets_dir
        packed = Path(assets_dir()) / name
    except Exception:
        packed = _ASSETS / name
    for cand in [packed, _ASSETS / name,
                 Path("/usr/share/fonts/truetype/noto") / name]:
        if cand.is_file():
            return str(cand)
    # fallback: أي خط عربي بالنظام
    import glob
    hits = glob.glob("/usr/share/fonts/**/*Arabic*.ttf", recursive=True) or \
        glob.glob("/usr/share/fonts/**/*askh*.ttf", recursive=True)
    if hits:
        return hits[0]
    raise FileNotFoundError("لا يوجد خط عربي متاح للرسم")


def render_nutrition_table(data: NutritionData, width: int = 640) -> np.ndarray:
    """يرسم الجدول القياسي ويعيد صورة BGR."""
    from PIL import Image, ImageDraw, ImageFont

    pad = 22
    inner_w = width - 2 * pad

    f_title = ImageFont.truetype(_find_font(True), 46)
    f_big = ImageFont.truetype(_find_font(True), 40)
    f_bold = ImageFont.truetype(_find_font(True), 26)
    f_reg = ImageFont.truetype(_find_font(False), 25)
    f_small = ImageFont.truetype(_find_font(False), 19)

    kw = {}
    try:
        from PIL import features
        if features.check("raqm"):
            kw = {"direction": "rtl", "features": ["rtla"], "language": "ar"}
    except Exception:
        pass

    def text_size(draw, txt, font):
        bbox = draw.textbbox((0, 0), txt, font=font, **kw)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    # تقدير الارتفاع
    n_rows = len(data.rows)
    est_h = 300 + n_rows * 44 + 160
    img = Image.new("RGB", (width, est_h), "white")
    d = ImageDraw.Draw(img)

    y = pad

    def line(th=1, yy=None):
        nonlocal y
        if yy is None:
            yy = y
        d.rectangle([pad, yy, width - pad, yy + th], fill="black")
        y = yy + th + 8

    def rtl_text(x_right, yy, txt, font, fill="black"):
        w, _ = text_size(d, txt, font)
        d.text((x_right - w, yy), txt, font=font, fill=fill, **kw)

    # العنوان
    title = "الحقائق الغذائية"
    tw, th = text_size(d, title, f_title)
    d.text(((width - tw) // 2, y), title, font=f_title, fill="black", **kw)
    y += th + 14
    line(6)

    # الحصص
    if data.servings:
        rtl_text(width - pad, y, f"عدد الحصص: {_to_ar_digits(data.servings)}",
                 f_reg)
        y += 36
    if data.serving_size:
        rtl_text(width - pad, y,
                 f"حجم الحصة: {_to_ar_digits(data.serving_size)}", f_reg)
        y += 36
    line(3)

    # السعرات
    rtl_text(width - pad, y, "السعرات الحرارية", f_bold)
    cal = _to_ar_digits(data.calories or "٠")
    d.text((pad, y - 8), cal, font=f_big, fill="black", **kw)
    y += 56
    line(5)

    # رأس النسبة
    rtl_text(width - pad, y, "٪ القيمة اليومية٭", f_bold)
    y += 40
    line(2)

    # الصفوف
    indent_keys = {"saturated_fat", "trans_fat", "fiber", "sugars",
                   "added_sugars"}
    for row in data.rows:
        label = row.label_ar
        amount = ""
        if row.amount:
            amount = _to_ar_digits(row.amount) + (row.unit or "")
        pct = (_to_ar_digits(row.percent) + "٪") if row.percent else ""
        x_right = width - pad - (26 if row.key in indent_keys else 0)
        font = f_reg if row.key in indent_keys else f_bold
        txt = label + (f" {amount}" if amount else "")
        rtl_text(x_right, y, txt, font)
        if pct:
            d.text((pad, y), pct, font=f_bold, fill="black", **kw)
        y += 34
        line(1)

    # الهامش السفلي
    y += 4
    words = FOOTNOTE_AR.split()
    cur = ""
    for wd in words:
        trial = (cur + " " + wd).strip()
        w, _ = text_size(d, trial, f_small)
        if w > inner_w and cur:
            rtl_text(width - pad, y, cur, f_small)
            y += 26
            cur = wd
        else:
            cur = trial
    if cur:
        rtl_text(width - pad, y, cur, f_small)
        y += 30

    # إطار خارجي وقص للارتفاع الفعلي
    final_h = y + pad
    img = img.crop((0, 0, width, min(est_h, final_h)))
    d = ImageDraw.Draw(img)
    d.rectangle([2, 2, width - 3, img.height - 3], outline="black", width=4)

    arr = np.array(img)
    return arr[:, :, ::-1].copy()  # RGB -> BGR
