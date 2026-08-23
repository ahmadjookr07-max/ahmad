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

# ──────── قياس الأداء (اختياري وغير مُعيق) ────────
# المحرك يجب أن يعمل حتى لو غابت طبقة الوعي تمامًا؛ لذا نستورد
# بحماية ونسقط إلى مدير سياق فارغ لا يفعل شيئًا عند التعذر.
try:  # pragma: no cover - مسار بيئي
    from awareness import perf as _perf

    def _span(name: str):
        return _perf.span(name)
except Exception:  # pragma: no cover
    import contextlib as _ctx

    def _span(name: str):
        return _ctx.nullcontext()


@dataclass
class ProcessOptionsV2:
    width: int = 800
    height: int = 700
    margin: int = 40
    # عند ضبطها تستخدم نفس قاعدة المحرر: 6% من كل بُعد، بدل هامش
    # بكسلي موحّد لا يطابق لوحة 800×700 أفقيًا وعموديًا.
    frame_margin_ratio: float | None = None
    enhance: bool = True
    webp_lossless: bool = True
    # حقائق التغذية
    nutrition_mode: str = "none"
    nutrition_bbox: tuple | None = None          # (x,y,w,h) يدوي
    nutrition_source_path: str = ""              # صورة منفصلة للجدول
    nutrition_placement: InsetPlacement | None = None
    nutrition_values: dict | None = None         # قيم معتمدة بعد مراجعة المستخدم
    # تعديلات يدوية
    manual_rotation_degrees: float = 0.0
    manual_crop_corners: list | None = None      # 8 قيم منظور
    # ظل
    shadow_preset: str = ""                      # اسم preset من shadow_v2
    # محرك الجودة الواعي بالنص + طمس التواريخ
    quality: int | None = None                    # 50–100؛ None = السلوك القديم
    output_format: str = ""                      # webp | png | jpeg؛ "" = دون تغيير
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
                    lossless_webp: bool = True,
                    quality: int | None = None) -> bool:
    """يكتب الصورة محترمًا الجودة المطلوبة لا المفروضة.

    كان المحرك يقبل حالتين فقط (101 بلا فقدان أو 95 ثابتة)،
    فأي أمر من المالك مثل «خلي الجودة 80» لم يكن له موضع
    يُستقبل فيه فيُهمل صمتًا. والإهمال الصامت أسوأ من الرفض
    الصريح، لأنه يوهم المالك أن البرنامج أطاعه وهو لم يفعل.
    """
    path = Path(path)
    ext = path.suffix.lower()
    params: list[int] = []
    if ext == ".webp":
        if quality is not None:
            q = max(1, min(100, int(quality)))
            # 101 تعني بلا فقدان في OpenCV
            params = [cv2.IMWRITE_WEBP_QUALITY, 101 if q >= 100 else q]
        else:
            params = [cv2.IMWRITE_WEBP_QUALITY, 101 if lossless_webp else 95]
    elif ext in (".jpg", ".jpeg"):
        q = 95 if quality is None else max(1, min(100, int(quality)))
        params = [cv2.IMWRITE_JPEG_QUALITY, q]
    elif ext == ".png":
        # في PNG الرقم مستوى ضغط (0–9) لا جودة؛ المخرج بلا فقدان
        # دائمًا، لكن جودة أقل تعني رضًا بملف أصغر فنرفع الضغط.
        lvl = 6 if quality is None else max(
            0, min(9, round((100 - int(quality)) / 11)))
        params = [cv2.IMWRITE_PNG_COMPRESSION, int(lvl)]
    ok, buf = cv2.imencode(ext, img, params)
    if not ok:
        return False
    buf.tofile(str(path))
    return True


class ProcessorV2:
    """المعالج الرئيسي V2."""

    def __init__(self, model_dir: str | Path):
        self.segmenter = ProductSegmenterV2(model_dir)

    # -------------------------------------------------- prescale (م-1)
    @staticmethod
    def _prescale_to_target(img: np.ndarray, alpha: np.ndarray,
                           opts: ProcessOptionsV2):
        """اقتصاص حول القناع وتصغير إلى مقاس الهدف (بند م-1).

        يُرجع ``(img, alpha, True)`` عند التطبيق، و``None`` حين لا
        مكسب فيه فيُمضى في المسار القديم دون تغيير.

        ولماذا هذا أسرع بلا خسارة جودة: الخطوتان التاليتان
        (التركيب على أبيض والتحسين الواعي بالنص) تكلفتان
        طرديًّا مع عدد البكسلات، وكانتا تعملان على 12.2
        ميجابكسل لتُرمى إلى 0.56 ميجابكسل بعدهما.

        ويُحتفظ بهامش أمان (`PRESCALE_SLACK`) فوق مقاس الهدف
        لأن `_frame_on_canvas` سيعيد التأطير لاحقًا، وربّ الظل
        يوسّع القناع، فلا نريد تصغيرًا مرتين على الحدّ.
        """
        if img is None or alpha is None:
            return None
        h, w = img.shape[:2]
        bbox = ProductSegmenterV2.alpha_bbox(alpha)
        if bbox is None:
            return None
        x0, y0, x1, y1 = bbox
        # هامش حول المنتج: لا نقصّ على الحافة تمامًا لأن
        # الظل وإزالة الهالة يحتاجان متنفّسًا حول الجسم.
        prod_w, prod_h = x1 - x0 + 1, y1 - y0 + 1
        pad = int(max(prod_w, prod_h) * 0.10) + 8
        cx0 = max(0, x0 - pad)
        cy0 = max(0, y0 - pad)
        cx1 = min(w - 1, x1 + pad)
        cy1 = min(h - 1, y1 + pad)
        cw, chh = cx1 - cx0 + 1, cy1 - cy0 + 1
        if cw < 8 or chh < 8:
            return None

        # مقاس الهدف مع هامش أمان
        slack = ProcessorV2.PRESCALE_SLACK
        tw = int(opts.width * slack)
        th = int(opts.height * slack)
        sc = min(tw / cw, th / chh)
        # لا تكبير أبدًا، ولا تصغير طفيف لا يستحق العملية
        if sc >= 0.9:
            return None
        nw = max(8, int(round(cw * sc)))
        nh = max(8, int(round(chh * sc)))

        img_c = img[cy0:cy1 + 1, cx0:cx1 + 1]
        alpha_c = alpha[cy0:cy1 + 1, cx0:cx1 + 1]

        # الصورة: بنفس التصغير الواعي بالنص المستخدم في
        # التأطير، لا بتصغير قاسٍ — وهذا ما يحفط المقروئية.
        if getattr(opts, "text_aware", True):
            try:
                from .quality_v2 import smart_downscale
                img_s = smart_downscale(img_c, nw, nh, text_aware=True)
            except Exception:
                img_s = cv2.resize(img_c, (nw, nh),
                                   interpolation=cv2.INTER_AREA)
        else:
            img_s = cv2.resize(img_c, (nw, nh),
                               interpolation=cv2.INTER_AREA)

        # القناع: INTER_AREA يحفط تدرج الحافة (القناع عشري في
        # 0..1 ويجب أن يبقى كذلك لا أن يُعتّب فتخشن الحواف).
        alpha_s = cv2.resize(alpha_c.astype(np.float32), (nw, nh),
                             interpolation=cv2.INTER_AREA)
        alpha_s = np.clip(alpha_s, 0.0, 1.0)
        return img_s, alpha_s, True

    # هامش الأمان فوق مقاس الهدف قبل التأطير النهائي.
    # 1.6 مختار لا مخمّن: يترك دقة كافية للتأطير الثاني
    # ولتوسعة القناع بالظل، ومع ذلك يخفّض البكسلات إلى
    # حدود 1.4 ميجابكسل بدل 12.2.
    PRESCALE_SLACK = 1.6

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
        ratio = getattr(opts, "frame_margin_ratio", None)
        if ratio is None:
            margin_x = margin_y = int(opts.margin)
        else:
            ratio = float(np.clip(ratio, 0.0, 0.45))
            margin_x = int(round(opts.width * ratio))
            margin_y = int(round(opts.height * ratio))
        avail_w = max(1, opts.width - 2 * margin_x)
        avail_h = max(1, opts.height - 2 * margin_y)
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
        with _span("read_input"):
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

            # وضع الإزالة: ترميم موضع الجدول من صورة المنتج نفسها
            elif opts.nutrition_mode == "remove":
                box = (tuple(opts.nutrition_bbox) if opts.nutrition_bbox
                       else detect_nutrition_table(img))
                if box:
                    try:
                        x, y, bw, bh = (int(v) for v in box)
                        H, W = img.shape[:2]
                        x = max(0, min(W - 1, x)); y = max(0, min(H - 1, y))
                        bw = max(1, min(W - x, bw)); bh = max(1, min(H - y, bh))
                        mask = np.zeros((H, W), np.uint8)
                        mask[y:y + bh, x:x + bw] = 255
                        img = cv2.inpaint(img, mask, 7, cv2.INPAINT_TELEA)
                        res.warnings.append("أُزيل جدول حقائق التغذية من الصورة")
                    except Exception as exc:
                        res.warnings.append(f"تعذرت إزالة الجدول: {exc}")
                else:
                    res.warnings.append("لم يُكشف جدول لإزالته")

            # القص — أغلى خطوة في الخط؛ قياسها منفردة يكشف اختناق النموذج
            with _span("segment"):
                seg = self.segmenter.segment(img)
            res.confidence = seg.confidence
            res.warnings.extend(seg.warnings)
            alpha = seg.alpha
            # تدوير يدوي
            if abs(opts.manual_rotation_degrees) > 0.05:
                img, alpha = rotate_with_alpha(img, alpha,
                                               opts.manual_rotation_degrees)

            # ============ 2.9.13 (م-1) — إعادة ترتيب الخط ============
            #
            # الترتيب القديم كان:
            #     segment → compose_on_white(12MP) → enhance(12MP)
            #             → shadow → frame(→0.56MP)
            #
            # والمقيس داخل `process` نفسه على مقاس صور المالك
            # 4032×3024 (بعد تسخين النموذج، ثلاث جولات):
            #     الإجمالي           5786 مللي/صورة
            #     enhance           3617 مللي  (62.5%)
            #     compose_on_white   893 مللي  (15.4%)
            # → 217 صورة = 20.9 دقيقة، مطابق لبلاغ المالك.
            #
            # والعلة ليست العتاد بل **ترتيب العمليات**: الخطوتان
            # تعملان على 12.2 ميجابكسل والمخرَج 0.56 ميجابكسل فقط
            # (نسبة 21.8×)، أي أن **95.4% من حسابهما يُرمى** في
            # `frame_on_canvas` بعدهما.
            #
            # الترتيب الجديد: اقتصاص حول القناع ثم تصغير إلى
            # مقاس الهدف **قبل** التركيب والتحسين. ولماذا لا يضر
            # هذا بالجودة:
            #   • التصغير يجري بنفس `smart_downscale` الواعي بالنص
            #     الذي كان يجري في `frame_on_canvas`، لا بتصغير قاسٍ.
            #   • التحسين والواعي بالنص يعمل على البكسلات التي
            #     ستُرى فعلًا، وهذا أدق لا أردأ: حدة تُحسب على
            #     12MP ثم يُرمى 95% منها ليست حدة مرئية.
            #   • إزالة الهالة (`decontaminate`) تعمل على شريط الحافة،
            #     والحافة تبقى حافة بعد التصغير.
            #
            # ولأن الجودة لا تُفترض بل تُقاس، لهذا التغيير اختبار
            # يقارن مقروئية النص قبله وبعده:
            # `tests/test_pipeline_order_m1.py`.
            #
            # ولا يُطبّق الترتيب الجديد إلا حين يكون مفيدًا فعلًا
            # (المنتج أكبر من مقاس الهدف)؛ وإلا فالمسار القديم
            # أسلم ولا مكسب في تغييره.
            _pre_scaled = False
            with _span("prescale"):
                _pre = self._prescale_to_target(img, alpha, opts)
                if _pre is not None:
                    img, alpha, _pre_scaled = _pre

            # تركيب على أبيض + تحسين
            with _span("compose_on_white"):
                white = self.segmenter.compose_on_white(img, alpha)
            if opts.enhance:
              with _span("enhance"):
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
            with _span("frame_on_canvas"):
                final = self._frame_on_canvas(white, alpha, opts)

            # حقائق التغذية على الناتج
            out_path = Path(output_path)
            if opts.nutrition_mode == "merge_small" and label_img is not None:
                final = merge_label_inset(final, label_img,
                                          opts.nutrition_placement)
            elif opts.nutrition_mode == "standalone" and label_img is not None:
                # 2.3: الصورة المنفردة تُحفظ بجانب صور الصنف وتُرقّم ضمنها
                # وفق سياسة التسمية (مثل 10001102_حبة-2) لترفع للمتجر مباشرة،
                # مع الحفاظ على الدقة الكاملة (hq).
                nut_path = None
                try:
                    from .integration_v2 import build_output_stem
                    from .naming_v2 import parse_name
                    parsed = parse_name(out_path.stem)
                    if parsed and parsed.item:
                        # الناتج الرئيسي يُحفظ لاحقًا في هذه الدالة — اكتب ملفًا
                        # مؤقتًا باسمه أولًا ليحتسبه build_output_stem في الترقيم
                        placeholder = None
                        if not out_path.exists():
                            out_path.parent.mkdir(parents=True, exist_ok=True)
                            out_path.touch()
                            placeholder = out_path
                        try:
                            stem = build_output_stem(out_path.parent,
                                                     parsed.item)
                        finally:
                            if placeholder is not None:
                                try:
                                    placeholder.unlink()
                                except OSError:
                                    pass
                        nut_path = out_path.parent / f"{stem}.webp"
                except Exception:
                    nut_path = None
                if nut_path is None:
                    nut_dir = out_path.parent / "حقائق التغذية"
                    nut_dir.mkdir(parents=True, exist_ok=True)
                    nut_path = nut_dir / (out_path.stem + "_تغذية.webp")
                nut_img = render_standalone_label(label_img, opts.width,
                                                  opts.height)
                if imwrite_unicode(nut_path, nut_img, opts.webp_lossless,
                                   quality=getattr(opts, "quality", None)):
                    res.nutrition_output_path = str(nut_path)
            elif opts.nutrition_mode == "rebuild" and label_img is not None:
                try:
                    from .nutrition_ocr_v2 import (NutritionData,
                                                   extract_nutrition_data)
                    from .nutrition_render_v2 import render_nutrition_table
                    if opts.nutrition_values:
                        # قيم معتمدة بعد مراجعة المستخدم — تطابق 100%،
                        # لا يعاد OCR مرة أخرى
                        data = NutritionData.from_dict(opts.nutrition_values)
                    else:
                        data = extract_nutrition_data(label_img)
                    table = render_nutrition_table(data)
                    nut_dir = out_path.parent / "حقائق التغذية"
                    nut_dir.mkdir(parents=True, exist_ok=True)
                    nut_path = nut_dir / (out_path.stem + "_تغذية.webp")
                    nut_img = render_standalone_label(table, opts.width,
                                                      opts.height,
                                                      enhance=False, hq=False)
                    if imwrite_unicode(nut_path, nut_img, opts.webp_lossless,
                                       quality=getattr(opts, "quality", None)):
                        res.nutrition_output_path = str(nut_path)
                    # حفظ JSON للقيم للتحرير لاحقًا
                    import json
                    (nut_dir / (out_path.stem + "_تغذية.json")).write_text(
                        json.dumps(data.to_dict(), ensure_ascii=False,
                                   indent=2), encoding="utf-8")
                except Exception as exc:
                    res.warnings.append(f"تعذرت إعادة بناء الجدول: {exc}")

            # حفظ الناتج الرئيسي — الكتابة بـWebP اللافقدي مكلفة، نقيسها
            # الصيغة تُطبّق هنا لا في المسمّي، لأن المالك قد يطلب
            # PNG بعد أن بُني المسار بـwebp، فنحترم أحدث أمر لا أقدمه.
            fmt = str(getattr(opts, "output_format", "") or "").lower().lstrip(".")
            if fmt in ("webp", "png", "jpeg", "jpg"):
                _ext = ".jpg" if fmt in ("jpeg", "jpg") else f".{fmt}"
                if out_path.suffix.lower() != _ext:
                    out_path = out_path.with_suffix(_ext)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with _span("write_output"):
                _saved = imwrite_unicode(out_path, final, opts.webp_lossless,
                                         quality=getattr(opts, "quality", None))
            if not _saved:
                res.error = "فشل حفظ الملف الناتج"
                return res
            res.output_path = str(out_path)
            res.ok = True
        except Exception as exc:  # noqa: BLE001
            res.error = str(exc)
        res.elapsed = time.time() - t0
        return res
