# -*- coding: utf-8 -*-
"""processor_v2 — خط المعالجة الكامل V2.

قص ISNet + تحسين تلقائي + تأطير 800×700 على أبيض + WebP lossless +
أوضاع حقائق التغذية (none|standalone|merge_small|rebuild|remove|not_found)
+ تدوير/اقتصاص يدوي + ظل اختياري.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .segmentation_v2 import ProductSegmenterV2
from .enhancement_v2 import auto_enhance
from .alignment_v2 import rotate_with_alpha, perspective_rectify
from .nutrition_v2 import (InsetPlacement, detect_nutrition_table,
                           crop_region, merge_label_inset,
                           render_standalone_label)

NUTRITION_MODES = ("none", "standalone", "merge_small", "rebuild",
                   "remove", "not_found")


@dataclass
class ProcessOptionsV2:
    width: int = 800
    height: int = 700
    margin: int = 40
    enhance: bool = True
    webp_lossless: bool = True
    # حقائق التغذية
    nutrition_mode: str = "none"
    nutrition_bbox: tuple | None = None          # (x,y,w,h) يدوي
    nutrition_source_path: str = ""              # صورة منفصلة للجدول
    nutrition_placement: InsetPlacement | None = None
    # تعديلات يدوية
    manual_rotation_degrees: float = 0.0
    manual_crop_corners: list | None = None      # 8 قيم منظور
    # ظل
    shadow_preset: str = ""                      # اسم preset من shadow_v2
    # محرك الجودة الواعي بالنص + طمس التواريخ
    text_aware: bool = True                      # حدة ذكية وتصغير تدريجي يحفظ الكتابات
    blur_dates: bool = True                      # طمس تواريخ الإنتاج/الانتهاء تلقائيًا


@dataclass
class ProcessResultV2:
    ok: bool = False
    output_path: str = ""
    nutrition_output_path: str = ""
    confidence: float = 0.0
    elapsed: float = 0.0
    warnings: list = field(default_factory=list)
    error: str = ""


def imread_unicode(path: str | Path) -> np.ndarray | None:
    try:
        data = np.fromfile(str(path), np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return None


def imwrite_unicode(path: str | Path, img: np.ndarray,
                    lossless_webp: bool = True) -> bool:
    path = Path(path)
    ext = path.suffix.lower()
    params = []
    if ext == ".webp":
        params = [cv2.IMWRITE_WEBP_QUALITY, 101 if lossless_webp else 95]
    ok, buf = cv2.imencode(ext, img, params)
    if not ok:
        return False
    buf.tofile(str(path))
    return True


class ProcessorV2:
    """المعالج الرئيسي V2."""

    def __init__(self, model_dir: str | Path):
        self.segmenter = ProductSegmenterV2(model_dir)

    # ------------------------------------------------------------ frame
    @staticmethod
    def _frame_on_canvas(img_white: np.ndarray, alpha: np.ndarray,
                         opts: ProcessOptionsV2) -> np.ndarray:
        bbox = ProductSegmenterV2.alpha_bbox(alpha)
        if bbox is None:
            crop = img_white
        else:
            x0, y0, x1, y1 = bbox
            crop = img_white[y0:y1 + 1, x0:x1 + 1]
        ch, cw = crop.shape[:2]
        avail_w = opts.width - 2 * opts.margin
        avail_h = opts.height - 2 * opts.margin
        sc = min(avail_w / cw, avail_h / ch)
        nw, nh = max(1, int(cw * sc)), max(1, int(ch * sc))
        if sc < 1 and getattr(opts, "text_aware", True):
            # تصغير ذكي حافظ للنص — كتابات المنتج تبقى مقروءة بعد التأطير
            try:
                from .quality_v2 import smart_downscale
                resized = smart_downscale(crop, nw, nh, text_aware=True)
            except Exception:
                resized = cv2.resize(crop, (nw, nh),
                                     interpolation=cv2.INTER_AREA)
        else:
            interp = cv2.INTER_AREA if sc < 1 else cv2.INTER_LANCZOS4
            resized = cv2.resize(crop, (nw, nh), interpolation=interp)
        canvas = np.full((opts.height, opts.width, 3), 255, np.uint8)
        x = (opts.width - nw) // 2
        y = (opts.height - nh) // 2
        canvas[y:y + nh, x:x + nw] = resized
        return canvas

    # ---------------------------------------------------------- process
    def process(self, source_path: str | Path, output_path: str | Path,
                opts: ProcessOptionsV2 | None = None) -> ProcessResultV2:
        t0 = time.time()
        opts = opts or ProcessOptionsV2()
        res = ProcessResultV2()
        img = imread_unicode(source_path)
        if img is None:
            res.error = f"تعذر قراءة الصورة: {source_path}"
            return res
        try:
            # اقتصاص منظور يدوي أولًا
            if opts.manual_crop_corners and len(opts.manual_crop_corners) == 8:
                img = perspective_rectify(img, list(opts.manual_crop_corners))

            # طمس تواريخ الإنتاج/الانتهاء تلقائيًا (تمويه طفيف بلون المنتج)
            if getattr(opts, "blur_dates", True):
                try:
                    from .date_blur_v2 import auto_blur_dates
                    img, _n = auto_blur_dates(img)
                    if _n:
                        res.warnings.append(f"طُمس {_n} تاريخ مطبوع")
                except Exception:
                    pass

            # حقائق التغذية: مصدر الجدول
            label_img = None
            if opts.nutrition_mode in ("standalone", "merge_small", "rebuild"):
                if opts.nutrition_source_path:
                    label_src = imread_unicode(opts.nutrition_source_path)
                else:
                    label_src = img
                if label_src is not None:
                    if opts.nutrition_bbox:
                        label_img = crop_region(label_src,
                                                tuple(opts.nutrition_bbox))
                    else:
                        box = detect_nutrition_table(label_src)
                        if box:
                            label_img = crop_region(label_src, box)
                        else:
                            res.warnings.append("لم يُكشف جدول حقائق التغذية")

            # القص
            seg = self.segmenter.segment(img)
            res.confidence = seg.confidence
            res.warnings.extend(seg.warnings)
            alpha = seg.alpha

            # تدوير يدوي
            if abs(opts.manual_rotation_degrees) > 0.05:
                img, alpha = rotate_with_alpha(img, alpha,
                                               opts.manual_rotation_degrees)

            # تركيب على أبيض + تحسين
            white = self.segmenter.compose_on_white(img, alpha)
            if opts.enhance:
                if getattr(opts, "text_aware", True):
                    try:
                        from .quality_v2 import enhance_preserving_text
                        white = enhance_preserving_text(white)
                    except Exception:
                        white = auto_enhance(white)
                else:
                    white = auto_enhance(white)
                # التحسين قد يغيّر البياض قليلًا — أعد فرض الخلفية
                a = alpha[:, :, None]
                white = np.clip(white.astype(np.float32) * a +
                                255.0 * (1 - a), 0, 255).astype(np.uint8)

            # ظل اختياري (قبل التأطير للحفاظ على القناع)
            if opts.shadow_preset:
                try:
                    from .shadow_v2 import (SHADOW_PRESETS,
                                            apply_shadow_on_white)
                    preset = SHADOW_PRESETS.get(opts.shadow_preset)
                    if preset is not None and preset.kind != "none":
                        rgba = cv2.cvtColor(white, cv2.COLOR_BGR2BGRA)
                        rgba[:, :, 3] = (np.clip(alpha, 0, 1) * 255).astype(np.uint8)
                        white = apply_shadow_on_white(rgba, preset)
                        # وسّع القناع ليشمل الظل في التأطير
                        gray = cv2.cvtColor(white, cv2.COLOR_BGR2GRAY)
                        alpha = np.maximum(alpha,
                                           ((255 - gray) > 8).astype(np.float32))
                except Exception as exc:
                    res.warnings.append(f"تعذر الظل: {exc}")

            # تأطير
            final = self._frame_on_canvas(white, alpha, opts)

            # حقائق التغذية على الناتج
            out_path = Path(output_path)
            if opts.nutrition_mode == "merge_small" and label_img is not None:
                final = merge_label_inset(final, label_img,
                                          opts.nutrition_placement)
            elif opts.nutrition_mode == "standalone" and label_img is not None:
                nut_dir = out_path.parent / "حقائق التغذية"
                nut_dir.mkdir(parents=True, exist_ok=True)
                nut_path = nut_dir / (out_path.stem + "_تغذية.webp")
                nut_img = render_standalone_label(label_img, opts.width,
                                                  opts.height)
                if imwrite_unicode(nut_path, nut_img, opts.webp_lossless):
                    res.nutrition_output_path = str(nut_path)
            elif opts.nutrition_mode == "rebuild" and label_img is not None:
                try:
                    from .nutrition_ocr_v2 import extract_nutrition_data
                    from .nutrition_render_v2 import render_nutrition_table
                    data = extract_nutrition_data(label_img)
                    table = render_nutrition_table(data)
                    nut_dir = out_path.parent / "حقائق التغذية"
                    nut_dir.mkdir(parents=True, exist_ok=True)
                    nut_path = nut_dir / (out_path.stem + "_تغذية.webp")
                    nut_img = render_standalone_label(table, opts.width,
                                                      opts.height,
                                                      enhance=False)
                    if imwrite_unicode(nut_path, nut_img, opts.webp_lossless):
                        res.nutrition_output_path = str(nut_path)
                    # حفظ JSON للقيم للتحرير لاحقًا
                    import json
                    (nut_dir / (out_path.stem + "_تغذية.json")).write_text(
                        json.dumps(data.to_dict(), ensure_ascii=False,
                                   indent=2), encoding="utf-8")
                except Exception as exc:
                    res.warnings.append(f"تعذرت إعادة بناء الجدول: {exc}")

            # حفظ الناتج الرئيسي
            out_path.parent.mkdir(parents=True, exist_ok=True)
            if not imwrite_unicode(out_path, final, opts.webp_lossless):
                res.error = "فشل حفظ الملف الناتج"
                return res
            res.output_path = str(out_path)
            res.ok = True
        except Exception as exc:  # noqa: BLE001
            res.error = str(exc)
        res.elapsed = time.time() - t0
        return res
