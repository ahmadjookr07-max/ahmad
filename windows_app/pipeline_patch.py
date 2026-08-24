# -*- coding: utf-8 -*-
"""pipeline_patch — وصل الوحدات الجديدة بكل مسارات المعالجة.

يُركَّب هذا الملف في `native_app_v2.py` بعد بناء الواجهة ليوصل:
- `product_finish_v2.finish_product` بمسار الدفعة (`processor_v2`)
- `straighten_v2.straighten` بمسار الدفعة والتحرير الفردي
- `shape_aware_v2.complete_product` بمسار الصور الجاهزة
- أداة الظل والإكمال للصور المنجزة (م-19 م-22)
- وحدة التقويم التلقائي في الدفعة (م-23)
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "src"), str(ROOT / "src" / "engine_v2"),
          str(ROOT / "windows_app")):
    if p not in sys.path:
        sys.path.insert(0, p)

__all__ = ["install_pipeline_patch", "apply_finish_to_image",
           "apply_shadow_to_finished", "apply_completion_to_finished",
           "FinishedEnhancementOptions", "SmartFinishedOptions",
           "apply_finished_enhancements", "apply_smart_finished_enhancements",
           "batch_process_finished", "batch_process_finished_to_new_folder"]

# خيار دفعات مشترك، ويكون الظل الخفيف مفعّلًا ابتداءً كما طلب المالك.
_AUTO_SHADOW_AFTER_ISOLATION = True
# مخزن لمحرك كشف النص العميق؛ إنشاؤه لكل صورة يبدد الوقت والذاكرة.
_DEEP_TEXT_DETECTOR = None
_DEEP_TEXT_DETECTOR_FAILED = False


@dataclass(frozen=True)
class FinishedEnhancementOptions:
    """خيارات مستقلة لتحسين الصور المنجزة بلا تخمين لمحتوى العبوة.

    الحماية مفعلة افتراضيًا. وعندما تكون فعالة لا يُصلح المسار فجوة ذات
    محيط غني بالنص/الباركود، ولا يدمج عناصر متعددة في صورة واحدة.
    """
    add_shadow: bool = True
    repair_edges: bool = True
    repair_gaps: bool = True
    restore_texture: bool = True
    preserve_text_and_barcodes: bool = True
    understand_image_type: bool = True
    enhance_product_appearance: bool = False

    def effective_gap_repair(self) -> bool:
        # سد فراغ أبيض بلا استكمال خامة يُنتج بقعة مصطنعة، لذلك لا يُنفذ.
        return bool(self.repair_gaps and self.restore_texture)

    @classmethod
    def safe_all(cls) -> "FinishedEnhancementOptions":
        return cls()


@dataclass(frozen=True)
class SmartFinishedOptions:
    """سياسة معالجة مستقلة لصور المتجر المنجزة.

    لا تعتمد على Excel أو barcode أو الجلسة. الوضع ``protect`` لا يغير إلا
    المناطق المؤكدة، بينما ``radical`` يطبّق تشطيبًا أقوى خارج النص والشعار
    ثم يثبت البكسلات المحمية ويعيد للوضع الآمن عند فشل التحقق.
    """
    mode: str = "protect"  # protect | radical
    preserve_text: bool = True
    clean_background: bool = True
    add_shadow: bool = True
    repair_edges: bool = True
    repair_gaps: bool = True
    restore_texture: bool = True
    enhance_appearance: bool = True
    audit_text: bool = True

    def is_radical(self) -> bool:
        return self.mode == "radical"

    def finished_options(self) -> FinishedEnhancementOptions:
        return FinishedEnhancementOptions(
            add_shadow=self.add_shadow,
            repair_edges=self.repair_edges,
            repair_gaps=self.repair_gaps,
            restore_texture=self.restore_texture,
            preserve_text_and_barcodes=self.preserve_text,
            understand_image_type=True,
            # الوضع الدقيق أبقى؛ الجذري يستخدم طبقة أقوى لاحقًا مع حماية نص.
            enhance_product_appearance=(self.enhance_appearance and not self.is_radical()),
        )


def _import_finish():
    from engine_v2.product_finish_v2 import finish_product, auto_shadow_opts
    return finish_product, auto_shadow_opts


def _import_straighten():
    from engine_v2.straighten_v2 import straighten, estimate_tilt
    return straighten, estimate_tilt


def _import_shape():
    from engine_v2.shape_aware_v2 import complete_product, mask_from_white
    return complete_product, mask_from_white


def _read_image_unicode(path: str | Path):
    """يقرأ صورة بمسار Unicode كامل، بما في ذلك العربية على Windows.

    ``cv2.imread(str(path))`` قد يعيد ``None`` في بعض حزم OpenCV على
    Windows عند وجود أحرف عربية في اسم الملف. القراءة الثنائية ثم
    ``imdecode`` لا تمرر الاسم إلى برنامج الترميز وتبقي نوع الصورة نفسه.
    """
    import cv2
    import numpy as np
    try:
        raw = np.fromfile(os.fspath(path), dtype=np.uint8)
        if raw.size == 0:
            return None
        return cv2.imdecode(raw, cv2.IMREAD_COLOR)
    except (OSError, ValueError):
        return None


def _write_image_unicode(path: str | Path, image) -> bool:
    """يحفظ صورة لمسار Unicode فوق الاسم نفسه وبطريقة ذرية آمنة."""
    import cv2
    target = Path(path)
    suffix = target.suffix.lower()
    if suffix not in {".webp", ".png"}:
        raise ValueError(f"صيغة غير مدعومة للصور المنجزة: {suffix or 'بلا امتداد'}")
    params = ([cv2.IMWRITE_WEBP_QUALITY, 100] if suffix == ".webp"
              else [cv2.IMWRITE_PNG_COMPRESSION, 3])
    ok, encoded = cv2.imencode(suffix, image, params)
    if not ok:
        return False
    temporary = target.with_name(f".{target.stem}.writing{suffix}")
    try:
        encoded.tofile(os.fspath(temporary))
        os.replace(os.fspath(temporary), os.fspath(target))
        return True
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


# ═══════════════════════ الدوال العامة ═══════════════════════

def apply_finish_to_image(
    img_bgr,
    alpha=None,
    *,
    auto_shadow: bool = True,
    straighten: bool = True,
) -> tuple:
    """يُطبّق التشطيب الكامل على صورة: استرجاع الحواف + اقتصاص + ظل.

    يعيد `(img_bgr, alpha)` المُشطَّبَين.
    """
    try:
        finish_product, auto_shadow_opts = _import_finish()
    except Exception:
        return img_bgr, alpha

    # تقويم اختياري قبل التشطيب
    if straighten and alpha is not None:
        try:
            from engine_v2.straighten_v2 import straighten as _str
            img_bgr, alpha = _str(img_bgr, alpha)
        except Exception:
            pass

    try:
        # finish_product يجهز القناع والاقتصاص؛ تركيب الظل يتم بعده على
        # خلفية بيضاء، كي يكون الظل خفيفًا وواقعًا تحت المنتج لا داخله.
        img_bgr, alpha, _ = finish_product(img_bgr, alpha)
        if auto_shadow and alpha is not None:
            from engine_v2.shadow_v2 import apply_shadow_on_white
            import cv2
            import numpy as np
            shadow_opts = auto_shadow_opts(alpha, subtle=True)
            if shadow_opts.kind != "none":
                rgba = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2BGRA)
                rgba[:, :, 3] = np.clip(alpha, 0, 255).astype(np.uint8)
                img_bgr = apply_shadow_on_white(rgba, shadow_opts)
    except Exception:
        pass
    return img_bgr, alpha


def _significant_components(mask, *, min_share: float = 0.12) -> list[tuple[int, int, int, int, int, int]]:
    """يعيد المكوّنات الحقيقية فقط، فلا تختلط شوائب الحافة بالمنتج."""
    import cv2
    import numpy as np
    n, _, stats, _ = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8), 8)
    if n <= 1:
        return []
    areas = stats[1:, cv2.CC_STAT_AREA]
    largest = int(areas.max()) if areas.size else 0
    minimum = max(90, int(largest * min_share))
    result = []
    for index in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[index])
        if area >= minimum:
            result.append((index, x, y, w, h, area))
    return sorted(result, key=lambda item: item[-1], reverse=True)


def _has_ground_shadow(img_bgr, mask) -> bool:
    """يكشف ظلًا أرضيًا موجودًا لتفادي إضافة ظل ثانٍ لنفس المنتج."""
    import cv2
    import numpy as np
    # قناع قوي يستبعد ظلًا رماديًا خفيفًا كي نحسب قاعدة المنتج الحقيقية.
    dev = (255 - img_bgr.astype(np.int16)).max(axis=2)
    strong = dev > 52
    ys, xs = np.where(strong)
    if xs.size == 0:
        return False
    h, w = mask.shape[:2]
    x0, x1 = int(xs.min()), int(xs.max())
    y1 = int(ys.max())
    # نبحث أسفل قاعدة المنتج فقط وبداخل عرضها الموسع؛ الكتابة أو الصور
    # المنفصلة في أماكن أخرى لا تُحسب ظلًا.
    top = min(h, y1 + 1)
    bottom = min(h, y1 + max(8, int((y1 - int(ys.min()) + 1) * 0.10)))
    left, right = max(0, x0 - 8), min(w, x1 + 9)
    if bottom <= top or right <= left:
        return False
    region_dev = dev[top:bottom, left:right]
    region_strong = strong[top:bottom, left:right]
    # الظل: انحراف خفيف عن الأبيض، تحت قاعدة قوية، وليس جزء تغليف داكنًا.
    shadow = (~region_strong) & (region_dev >= 8) & (region_dev <= 52)
    return int(shadow.sum()) >= max(16, int((x1 - x0 + 1) * 0.07))


def apply_shadow_to_finished(img_bgr):
    """يضيف ظلًا مرة واحدة فقط لصورة جاهزة بلا تغيير دقة المنتج.

    كان المسار القديم يحوّل القناع إلى 0/1 ثم يرسله إلى معايرة تتوقع
    Alpha من 0..255؛ فظهر القناع فارغًا وتُخطى كل الصور بلا أخطاء.
    """
    try:
        import cv2
        import numpy as np
        _, mask_from_white = _import_shape()
        mask = mask_from_white(img_bgr)
        if not mask.any() or _has_ground_shadow(img_bgr, mask):
            return img_bgr
        _, auto_shadow_opts = _import_finish()
        alpha_u8 = (mask > 0).astype(np.uint8) * 255
        shadow_opts = auto_shadow_opts(alpha_u8, subtle=True)
        if shadow_opts is None or getattr(shadow_opts, "kind", "none") == "none":
            return img_bgr
        from engine_v2.shadow_v2 import apply_shadow_on_white
        rgba = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2BGRA)
        rgba[:, :, 3] = alpha_u8
        return apply_shadow_on_white(rgba, shadow_opts)
    except Exception:
        return img_bgr


def _safe_complete_finished(
    img_bgr,
    *,
    repair_edges: bool = True,
    repair_gaps: bool = True,
    preserve_text_and_barcodes: bool = True,
):
    """يرمم النواقص المثبتة هندسيًا بلا اختراع كتابة أو أجزاء تغليف.

    لا يستخدم ``complete_product`` واسع المدى على الصورة المنجزة، لأنه
    مصمم لقناع العزل الخام وقد يحذف مكونات مقصودة مثل بطاقة حقائق غذائية.
    """
    import cv2
    import numpy as np
    _, mask_from_white = _import_shape()
    mask = mask_from_white(img_bgr)
    h, w = mask.shape[:2]
    base = int(mask.sum())
    report = {"bridge": 0, "holes": 0, "specks": 0,
              "protected": 0, "reason": ""}
    if not repair_edges and not repair_gaps:
        report["reason"] = "كل خيارات الحواف والفجوات متوقفة"
        return img_bgr, report
    if base < max(100, int(h * w * 0.004)) or base > int(h * w * 0.72):
        report["reason"] = "غير مناسب لإكمال تلقائي"
        return img_bgr, report

    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    components = _significant_components(mask)
    # الصور ذات ثلاث كتل حقيقية أو أكثر غالبًا صورة حقائق/عناصر متعددة؛
    # لا ندمجها تلقائيًا. كتلتان فقط قد تكونان كيسًا منقسمًا.
    if len(components) > 2:
        report["reason"] = "عناصر متعددة"
        return img_bgr, report

    refined = mask.copy()
    bridge = np.zeros_like(mask)
    if repair_gaps and len(components) == 2:
        _, ax, ay, aw, ah, aa = components[0]
        _, bx, by, bw, bh, ba = components[1]
        row_overlap = max(0, min(ay + ah, by + bh) - max(ay, by)) / float(max(1, min(ah, bh)))
        col_overlap = max(0, min(ax + aw, bx + bw) - max(ax, bx)) / float(max(1, min(aw, bw)))
        gap_x = max(0, max(ax, bx) - min(ax + aw, bx + bw))
        gap_y = max(0, max(ay, by) - min(ay + ah, by + bh))
        side_by_side = row_overlap >= 0.78 and gap_x <= max(3, int(min(aw, bw) * 0.06))
        stacked = col_overlap >= 0.78 and gap_y <= max(3, int(min(ah, bh) * 0.06))
        # تشابه حجم الكتلتين يمنع دمج بطاقة صغيرة أو ملصق منفصل مع المنتج.
        size_ratio = min(aa, ba) / float(max(1, max(aa, ba)))
        if size_ratio >= 0.18 and (side_by_side or stacked):
            if side_by_side:
                kernel = np.ones((3, max(3, gap_x + 1)), np.uint8)
            else:
                kernel = np.ones((max(3, gap_y + 1), 3), np.uint8)
            merged = cv2.morphologyEx(refined, cv2.MORPH_CLOSE, kernel)
            added = ((merged > 0) & (refined == 0)).astype(np.uint8)
            if int(added.sum()) <= int(base * 0.025):
                refined, bridge = merged, added
                report["bridge"] = int(added.sum())
        if not report["bridge"]:
            report["reason"] = "فصل غير آمن للدمج"
            return img_bgr, report

    # فراغات داخلية كبيرة نسبيًا وقليلة العدد فقط؛ فتحات النص الصغيرة
    # وأي مساحة واسعة من تصميم الغلاف تبقى كما هي.
    flood = refined.copy()
    cv2.floodFill(flood, np.zeros((h + 2, w + 2), np.uint8), (0, 0), 1)
    holes = (flood == 0).astype(np.uint8)
    hn, hlab, hstats, _ = cv2.connectedComponentsWithStats(holes, 8)
    fill = bridge.copy()
    min_hole = max(160, int(base * (0.0030 if preserve_text_and_barcodes else 0.0015)))
    # عند الحماية، تبقى الفجوة ضمن 4% ويُرفض أي محيط غني بالحواف؛
    # عند تعطيلها صراحةً تتسع المساحة إلى 7% للحالات الاستثنائية.
    max_hole = max(min_hole, int(base * (0.040 if preserve_text_and_barcodes else 0.070)))
    for index in range(1, hn):
        x, y, bw, bh, area = (int(v) for v in hstats[index])
        aspect = max(bw, bh) / float(max(1, min(bw, bh)))
        if repair_gaps and min_hole <= area <= max_hole and aspect <= 4.5:
            ring = cv2.dilate((hlab == index).astype(np.uint8), np.ones((5, 5), np.uint8))
            ring = (ring > 0) & (hlab != index) & (refined > 0)
            # استبعد بقايا ضغط WebP القريبة من الأبيض؛ هي هالة حول الفجوة
            # وليست خامة المنتج التي نحتاجها للحكم على الإكمال.
            strong_ring = (255 - img_bgr.astype(np.int16)).max(axis=2) > 40
            ring &= strong_ring
            # لون محيط متقلب جدًا يعني كتابة/رسمة؛ لا نرممها تلقائيًا.
            ring_pixels = img_bgr[ring]
            # نقيس التباين عبر البكسلات داخل كل قناة، لا الانحراف بين B/G/R
            # للون تغليف سليم واحد؛ اللون البرتقالي مثلًا مختلف القنوات لكنه متجانس مكانيًا.
            spatial_std = float(np.mean(np.std(ring_pixels.astype(np.float32), axis=0))) if ring_pixels.size else 999.0
            # كثافة حواف مرتفعة داخل الفجوة/حولها علامة نص أو باركود.
            # افحص نطاقًا محيطًا أوسع؛ النص أو الباركود غالبًا يكون ملاصقًا
            # للفجوة المتضررة لا داخلها فقط.
            top, bottom = max(0, y - 15), min(h, y + bh + 15)
            left, right = max(0, x - 15), min(w, x + bw + 15)
            roi = cv2.cvtColor(img_bgr[top:bottom, left:right], cv2.COLOR_BGR2GRAY)
            # لا تحسب حافة الفجوة نفسها؛ وإلا أصبحت كل فجوة مستطيلة «نصًا».
            local_hole = (hlab[top:bottom, left:right] == index).astype(np.uint8)
            ignored_border = cv2.dilate(local_hole, np.ones((5, 5), np.uint8)) > 0
            text_edges = (cv2.Canny(roi, 60, 150) > 0) & ~ignored_border if roi.size else np.zeros((0, 0), bool)
            edge_density = float(text_edges.mean()) if text_edges.size else 0.0
            allowed_std = 32.0 if preserve_text_and_barcodes else 48.0
            # النصوص والباركود تتكون من خطوط دقيقة؛ حد 3% بعد استبعاد حد
            # الفجوة يلتقطها قبل أن يسمح الترميم بملء مساحة معلومات مقروءة.
            protected = preserve_text_and_barcodes and edge_density > 0.03
            if int(ring.sum()) >= 30 and spatial_std < allowed_std and not protected:
                fill[hlab == index] = 1
                report["holes"] += area
            elif protected:
                report["protected"] += 1

    # شوائب منفصلة دقيقة فقط؛ لا نقص حواف متصل بالمنتج.
    if repair_edges:
        for index in range(1, n):
            area = int(stats[index, cv2.CC_STAT_AREA])
            if area < max(12, int(h * w * 0.00003)):
                refined[labels == index] = 0
                report["specks"] += area

    if not fill.any() and not report["specks"]:
        report["reason"] = report["reason"] or "لا عيب آمن"
        return img_bgr, report
    # يحتفظ القناع النهائي ببكسلات الإكمال؛ من دون هذا السطر كانت
    # الخلفية البيضاء تكتب فوق بكسلات INPAINT في نهاية الدالة.
    refined = np.maximum(refined, fill)
    out = img_bgr.copy()
    if fill.any():
        # INPAINT يكمّل خامة المحيط بدل ملئها بلون أو بياض مصطنع.
        out = cv2.inpaint(out, cv2.dilate(fill, np.ones((3, 3), np.uint8)), 3, cv2.INPAINT_TELEA)
    out[refined == 0] = (255, 255, 255)
    return out, report


def apply_completion_to_finished(img_bgr):
    """واجهة توافق تعيد الصورة فقط؛ التقرير التفصيلي تستعمله الدفعة."""
    return _safe_complete_finished(img_bgr)[0]


def _product_appearance_enhancement(
    image_bgr,
    *,
    preserve_text_and_barcodes: bool,
    understand_image_type: bool,
):
    """تحسين بصري لطيف داخل المنتج مع استثناء مناطق المعلومات المقروءة.

    لا يستدعي مولدًا خارجيًا ولا يبدل شكل العبوة. يحدد صور الحقائق الغذائية
    والمناطق الكثيفة بالنص/الباركود ثم يحافظ عليها كما هي؛ ويطبق فقط موازنة
    إضاءة خفيفة وتهيئة تباين دقيقة على بقية بكسلات المنتج.
    """
    import cv2
    import numpy as np
    _, mask_from_white = _import_shape()
    mask = mask_from_white(image_bgr)
    ys, xs = np.where(mask > 0)
    report = {"appearance": 0, "information_panel": 0, "protected_pixels": 0}
    if xs.size < 200:
        return image_bgr, report
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    box_area = max(1, (x1 - x0 + 1) * (y1 - y0 + 1))
    fill_ratio = float(mask[y0:y1 + 1, x0:x1 + 1].sum()) / box_area
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    edge = (cv2.Canny(gray, 60, 150) > 0).astype(np.uint8)
    product_edge_density = float(edge[mask > 0].mean()) if (mask > 0).any() else 0.0
    # اللوحة النصية المسطحة لا تستفيد من تحسين مظهر المنتج؛ لا تلمسها.
    if understand_image_type and fill_ratio >= 0.84 and product_edge_density >= 0.105:
        report["information_panel"] = 1
        return image_bgr, report

    protected = np.zeros_like(mask, dtype=bool)
    if preserve_text_and_barcodes:
        # قياس محلي للحواف يحدد الكتابة والباركود، ثم يوسع الحماية قليلًا.
        local_density = cv2.boxFilter(edge.astype(np.float32), -1, (17, 17), normalize=True)
        protected = (local_density > 0.13) & (mask > 0)
        protected = cv2.dilate(protected.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        protected &= mask > 0
        report["protected_pixels"] = int(protected.sum())

    editable = (mask > 0) & ~protected
    if int(editable.sum()) < 80:
        return image_bgr, report
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)
    l_ch, a_ch, b_ch = cv2.split(lab)
    # تباين متزن خفيف للغاية: يرفع وضوح الملمس بلا حدة قاسية أو تغيير لون.
    clahe = cv2.createCLAHE(clipLimit=1.15, tileGridSize=(8, 8))
    l_detail = clahe.apply(l_ch)
    l_mild = cv2.addWeighted(l_ch, 0.84, l_detail, 0.16, 0)
    enhanced = cv2.cvtColor(cv2.merge([l_mild, a_ch, b_ch]), cv2.COLOR_LAB2BGR)
    out = image_bgr.copy()
    out[editable] = enhanced[editable]
    report["appearance"] = int(np.any(out != image_bgr, axis=2).sum())
    return out, report


def apply_finished_enhancements(
    img_bgr,
    options: FinishedEnhancementOptions | None = None,
):
    """يطبّق الخيارات المختارة على الصورة في الذاكرة، مناسب للمعاينة قبل الحفظ."""
    import numpy as np
    active = options or FinishedEnhancementOptions.safe_all()
    image, report = _safe_complete_finished(
        img_bgr,
        repair_edges=active.repair_edges,
        repair_gaps=active.effective_gap_repair(),
        preserve_text_and_barcodes=active.preserve_text_and_barcodes,
    )
    if active.enhance_product_appearance:
        image, appearance = _product_appearance_enhancement(
            image,
            preserve_text_and_barcodes=active.preserve_text_and_barcodes,
            understand_image_type=active.understand_image_type,
        )
        report.update(appearance)
    else:
        report.update({"appearance": 0, "information_panel": 0, "protected_pixels": 0})
    if active.add_shadow:
        shadowed = apply_shadow_to_finished(image)
        if not np.array_equal(shadowed, image):
            image = shadowed
            report["shadow"] = 1
        else:
            report["shadow"] = 0
    else:
        report["shadow"] = 0
    return image, report


def _deep_text_detector():
    """يحمل كاشف PP-OCR v5 المجاني مرة واحدة عند توفر ملفاته محليًا."""
    global _DEEP_TEXT_DETECTOR, _DEEP_TEXT_DETECTOR_FAILED
    if _DEEP_TEXT_DETECTOR is not None:
        return _DEEP_TEXT_DETECTOR
    if _DEEP_TEXT_DETECTOR_FAILED:
        return None
    model_dir = ROOT / "src" / "engine_v2" / "models"
    det = model_dir / "ppocr-v5-det.onnx"
    rec = model_dir / "ppocr-arabic-rec.onnx"
    dictionary = model_dir / "ppocr-arabic-dict.txt"
    if not (det.is_file() and rec.is_file() and dictionary.is_file()):
        _DEEP_TEXT_DETECTOR_FAILED = True
        return None
    try:
        from rapidocr_onnxruntime import RapidOCR
        _DEEP_TEXT_DETECTOR = RapidOCR(
            det_model_path=str(det), rec_model_path=str(rec),
            rec_keys_path=str(dictionary), use_angle_cls=False)
        return _DEEP_TEXT_DETECTOR
    except Exception:
        _DEEP_TEXT_DETECTOR_FAILED = True
        return None


def _deep_text_protection_mask(image_bgr, foreground_mask):
    """يكشف أسطر النص بنموذج PP-OCR v5 مجاني ويعيد مناطقها دون تعديلها."""
    import cv2
    import numpy as np
    detector = _deep_text_detector()
    mask = np.zeros(foreground_mask.shape, dtype=np.uint8)
    if detector is None:
        return mask.astype(bool), 0
    try:
        boxes, _ = detector(image_bgr, use_rec=False, use_cls=False, box_thresh=0.12)
        h, w = foreground_mask.shape[:2]
        count = 0
        for box in boxes or []:
            points = np.asarray(box, dtype=np.int32).reshape(-1, 2)
            if points.size < 6:
                continue
            # وسع المضلع قليلًا حتى لا تلمس تحسينات الحافة حروف الملصق.
            x, y, bw, bh = cv2.boundingRect(points)
            pad = max(3, int(max(bw, bh) * 0.12))
            cv2.rectangle(mask, (max(0, x - pad), max(0, y - pad)),
                          (min(w - 1, x + bw + pad), min(h - 1, y + bh + pad)), 1, -1)
            count += 1
        return (mask > 0) & (foreground_mask > 0), count
    except Exception:
        return mask.astype(bool), 0


def _ocr_text_protection_mask(image_bgr, foreground_mask):
    """يقرأ كلمات العبوة محليًا ويعيد مناطقها فقط، لا نصًا مولدًا أو مصححًا.

    OCR إشارة إضافية فوق كشف الحواف: إذا لم تكن حزمة Tesseract متاحة في
    جهاز ما يعود المحرك بأمان إلى حارس الحواف، ولا يفشل تشغيل الدفعة.
    """
    import cv2
    import numpy as np
    mask = np.zeros(foreground_mask.shape, dtype=np.uint8)
    tokens = 0
    try:
        import pytesseract
        from pytesseract import Output
        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        data = pytesseract.image_to_data(
            rgb, lang="ara+eng", config="--psm 11", output_type=Output.DICT)
        h, w = foreground_mask.shape[:2]
        for index, raw in enumerate(data.get("text", ())):
            text = str(raw or "").strip()
            if not text:
                continue
            try:
                confidence = float(data["conf"][index])
                x = int(data["left"][index])
                y = int(data["top"][index])
                bw = int(data["width"][index])
                bh = int(data["height"][index])
            except (KeyError, ValueError, IndexError):
                continue
            if confidence < 12 or bw < 2 or bh < 2:
                continue
            pad = max(3, int(max(bw, bh) * 0.18))
            cv2.rectangle(mask, (max(0, x - pad), max(0, y - pad)),
                          (min(w - 1, x + bw + pad), min(h - 1, y + bh + pad)), 1, -1)
            tokens += 1
    except Exception:
        return mask.astype(bool), 0
    return (mask > 0) & (foreground_mask > 0), tokens


def _smart_image_profile(image_bgr, *, audit_text: bool = False) -> dict[str, Any]:
    """يفهم بنية الصورة محليًا قبل اختيار خطة التحسين.

    ليس مصنف أصناف أو مولدًا للنص؛ بل يحدد الحالة التي تسمح أو تمنع عملية
    بصرية بعينها. بذلك تبقى لوحة معلومات التغذية ومشهد العناصر المنفصلة
    خارج مسار التجميـل العام.
    """
    import numpy as np
    _, mask_from_white = _import_shape()
    mask = mask_from_white(image_bgr)
    h, w = mask.shape[:2]
    components = _significant_components(mask)
    area_ratio = float(mask.mean())
    bbox_fill_ratio = 0.0
    if mask.any():
        ys, xs = np.where(mask > 0)
        x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
        bbox_fill_ratio = float(mask[y0:y1 + 1, x0:x1 + 1].mean())
    gray = __import__("cv2").cvtColor(image_bgr, __import__("cv2").COLOR_BGR2GRAY)
    edge = (__import__("cv2").Canny(gray, 60, 150) > 0).astype(np.uint8)
    local = __import__("cv2").boxFilter(edge.astype(np.float32), -1, (17, 17), normalize=True)
    text_mask = (local > 0.13) & (mask > 0)
    text_mask = __import__("cv2").dilate(text_mask.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    text_mask &= mask > 0
    deep_text_mask, deep_boxes = _deep_text_protection_mask(image_bgr, mask) if audit_text else (np.zeros_like(text_mask, bool), 0)
    ocr_text_mask, ocr_tokens = _ocr_text_protection_mask(image_bgr, mask) if audit_text else (np.zeros_like(text_mask, bool), 0)
    text_mask |= deep_text_mask | ocr_text_mask
    protected_share = float(text_mask.sum()) / float(max(1, mask.sum()))
    information_panel = bool(bbox_fill_ratio >= 0.84 and protected_share >= 0.23)
    if area_ratio < 0.004:
        scenario = "small_or_ambiguous_foreground"
    elif information_panel:
        scenario = "information_or_dense_text_panel"
    elif len(components) >= 3:
        scenario = "multiple_separate_components"
    elif len(components) == 2:
        scenario = "split_or_double_component"
    elif protected_share >= 0.25:
        scenario = "text_heavy_packaging"
    elif area_ratio < 0.07:
        scenario = "small_centered_product"
    elif area_ratio > 0.50:
        scenario = "large_or_cropped_product"
    else:
        scenario = "standard_single_product"
    return {
        "scenario": scenario,
        "mask": mask,
        "text_mask": text_mask,
        "foreground_ratio": round(area_ratio, 5),
        "bbox_fill_ratio": round(bbox_fill_ratio, 5),
        "protected_share": round(protected_share, 5),
        "components": len(components),
        "information_panel": information_panel,
        "ocr_tokens": ocr_tokens,
        "deep_text_boxes": deep_boxes,
    }


def _radical_safe_appearance(image_bgr, profile: dict[str, Any], *, preserve_text: bool):
    """يعطي تحسنًا أوضح خارج النص، من دون إعادة رسم محتوى العبوة.

    تغيير L في Lab فقط يحسن الإضاءة والتباين من دون تبديل لون الشعار أو
    الغلاف. لا ينفذ على لوحات المعلومات أو المكونات المنفصلة.
    """
    import cv2
    import numpy as np
    scenario = str(profile.get("scenario", ""))
    if scenario in {"information_or_dense_text_panel", "multiple_separate_components",
                    "split_or_double_component", "small_or_ambiguous_foreground"}:
        return image_bgr, 0, "مستثنى حسب سيناريو الصورة"
    mask = profile["mask"] > 0
    protected = profile["text_mask"] if preserve_text else np.zeros_like(mask, bool)
    editable = mask & ~protected
    if int(editable.sum()) < 100:
        return image_bgr, 0, "لا توجد منطقة آمنة كافية"
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)
    l_ch, a_ch, b_ch = cv2.split(lab)
    # أقوى من وضع الحماية لكن بلا حدة أو saturation تخترع خامة/نصًا.
    detail = cv2.createCLAHE(clipLimit=1.75, tileGridSize=(8, 8)).apply(l_ch)
    improved_l = cv2.addWeighted(l_ch, 0.62, detail, 0.38, 0)
    improved = cv2.cvtColor(cv2.merge([improved_l, a_ch, b_ch]), cv2.COLOR_LAB2BGR)
    out = image_bgr.copy()
    out[editable] = improved[editable]
    return out, int(np.any(out != image_bgr, axis=2).sum()), "تحسين مظهر مقيد"


def _restore_protected_pixels(original, candidate, profile: dict[str, Any], *, preserve_text: bool):
    """يثبت النص والشعار قبل اختبار القبول، لا يكتفي بتوقع OCR."""
    import numpy as np
    if not preserve_text:
        return candidate, True, 0
    protected = profile["text_mask"]
    if profile.get("information_panel"):
        protected = profile["mask"] > 0
    if not protected.any():
        return candidate, True, 0
    out = candidate.copy()
    changed = int(np.any(out[protected] != original[protected], axis=1).sum())
    out[protected] = original[protected]
    valid = bool(np.array_equal(out[protected], original[protected]))
    return out, valid, changed


def apply_smart_finished_enhancements(
    img_bgr,
    options: SmartFinishedOptions | None = None,
):
    """يحلل صورة ثم يطبق خطة حماية أو تحسين جذري ويتحقق من النص قبل القبول."""
    import numpy as np
    active = options or SmartFinishedOptions()
    profile = _smart_image_profile(
        img_bgr, audit_text=bool(active.is_radical() and active.preserve_text and active.audit_text))
    # نوحّد الخلفية قبل توليد الظل حتى يبقى ظل التلامس الذي تضيفه المرحلة
    # الآمنة لاحقًا؛ تنظيفها بعد الظل كان يمسحه بالكامل.
    base_input = img_bgr.copy()
    if active.clean_background:
        base_input[profile["mask"] == 0] = (255, 255, 255)
    safe, base_report = apply_finished_enhancements(base_input, active.finished_options())
    detail: dict[str, Any] = {
        "mode": "radical" if active.is_radical() else "protect",
        "scenario": profile["scenario"],
        "foreground_ratio": profile["foreground_ratio"],
        "protected_share": profile["protected_share"],
        "text_pixels": int(profile["text_mask"].sum()),
        "ocr_tokens": int(profile.get("ocr_tokens", 0)),
        "deep_text_boxes": int(profile.get("deep_text_boxes", 0)),
        "radical_pixels": 0,
        "radical_reason": "وضع الحماية الدقيقة",
        "fallback_to_protect": False,
        "protected_changed_before_restore": 0,
    }
    out = safe
    if active.is_radical() and active.enhance_appearance:
        out, pixels, reason = _radical_safe_appearance(
            out, profile, preserve_text=active.preserve_text)
        detail["radical_pixels"] = pixels
        detail["radical_reason"] = reason
    out, text_ok, changed_protected = _restore_protected_pixels(
        img_bgr, out, profile, preserve_text=active.preserve_text)
    detail["protected_changed_before_restore"] = changed_protected
    if not text_ok:
        # لا يصدر مسار جذري غير متحقق؛ يرجع إلى المعالجة المحافظة.
        out, _, _ = _restore_protected_pixels(
            img_bgr, safe, profile, preserve_text=True)
        detail["fallback_to_protect"] = True
        detail["radical_reason"] = "فشل تحقق النص — رجوع للحماية الدقيقة"
    detail.update({f"safe_{key}": value for key, value in base_report.items()})
    detail["changed_pixels"] = int(np.any(out != img_bgr, axis=2).sum())
    return out, detail


def _new_smart_output_folder(parent: str | Path) -> Path:
    root = Path(parent)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    base = root / f"MarketImageStudio-Smart-{stamp}"
    candidate = base
    index = 2
    while candidate.exists():
        candidate = root / f"{base.name}-{index}"
        index += 1
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def batch_process_finished_to_new_folder(
    source_folder: str | Path,
    output_parent: str | Path,
    *,
    options: SmartFinishedOptions | None = None,
    progress_cb=None,
) -> dict:
    """ينتج نسخة معالجة كاملة في مجلد جديد ولا يكتب أبدًا فوق المدخل."""
    import numpy as np
    source = Path(source_folder)
    files = sorted(source.glob("*.webp")) + sorted(source.glob("*.png"))
    active = options or SmartFinishedOptions()
    output = _new_smart_output_folder(output_parent)
    records: list[dict[str, Any]] = []
    result = {"source_folder": str(source), "output_folder": str(output),
              "examined": 0, "written": 0, "unchanged": 0, "skipped": 0,
              "errors": [], "scenarios": {}, "fallbacks": 0}
    total = len(files)
    for index, path in enumerate(files, 1):
        if progress_cb is not None:
            try:
                progress_cb(index - 1, total)
            except Exception:
                pass
        record: dict[str, Any] = {"name": path.name}
        try:
            original = _read_image_unicode(path)
            if original is None:
                result["skipped"] += 1
                record["status"] = "unreadable"
                records.append(record)
                continue
            result["examined"] += 1
            enhanced, detail = apply_smart_finished_enhancements(original, active)
            record.update(detail)
            record["status"] = "changed" if not np.array_equal(original, enhanced) else "unchanged"
            target = output / path.name
            if not _write_image_unicode(target, enhanced):
                raise OSError("فشل حفظ نسخة النتيجة")
            result["written"] += 1
            if record["status"] == "unchanged":
                result["unchanged"] += 1
            scenario = str(detail.get("scenario", "unknown"))
            result["scenarios"][scenario] = int(result["scenarios"].get(scenario, 0)) + 1
            result["fallbacks"] += int(bool(detail.get("fallback_to_protect")))
            records.append(record)
        except Exception as exc:
            result["errors"].append(f"{path.name}: {exc}")
            record.update({"status": "error", "error": str(exc)})
            records.append(record)
    report_json = output / "smart_processing_report.json"
    report_csv = output / "smart_processing_report.csv"
    report_json.write_text(json.dumps({**result, "records": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    fieldnames = sorted({key for record in records for key in record}) or ["name", "status"]
    with report_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    if progress_cb is not None:
        try:
            progress_cb(total, total)
        except Exception:
            pass
    return result


def batch_process_finished(
    folder: str | Path,
    *,
    add_shadow: bool = True,
    complete: bool = False,
    progress_cb=None,
    options: FinishedEnhancementOptions | None = None,
) -> dict:
    """يفحص ويعالج صورًا منجزة مع حفظ الاسم والدقة دون نسخ مكررة.

    ``unchanged`` يعني أنها فُحصت ولم تحتاج إصلاحًا آمنًا، وليس تخطيًا.
    """
    import cv2
    import numpy as np
    folder = Path(folder)
    files = sorted(folder.glob("*.webp")) + sorted(folder.glob("*.png"))
    active = options or FinishedEnhancementOptions(
        add_shadow=add_shadow, repair_edges=complete, repair_gaps=complete,
        restore_texture=complete, preserve_text_and_barcodes=True,
        understand_image_type=True, enhance_product_appearance=False)
    result = {"examined": 0, "processed": 0, "unchanged": 0,
              "skipped": 0, "errors": [], "operations": {"shadow": 0,
              "bridge": 0, "holes": 0, "specks": 0, "protected": 0,
              "appearance": 0, "information_panel": 0, "protected_pixels": 0}}
    total = len(files)
    for i, path in enumerate(files):
        if progress_cb is not None:
            try:
                progress_cb(i, total)
            except Exception:
                pass
        try:
            original = _read_image_unicode(path)
            if original is None:
                result["skipped"] += 1
                continue
            result["examined"] += 1
            image, detail = apply_finished_enhancements(original, active)
            for key in ("bridge", "holes", "specks", "protected", "shadow",
                        "appearance", "information_panel", "protected_pixels"):
                result["operations"][key] += int(detail.get(key, 0) or 0)
            if np.array_equal(image, original):
                result["unchanged"] += 1
                continue
            # إعادة الكتابة فوق الاسم نفسه مع دعم العربية وUnicode؛
            # الجودة 100 تمنع تليين المنتج، والحفظ الذري لا يترك ملفًا نصف مكتوب.
            if not _write_image_unicode(path, image):
                raise OSError("فشل حفظ الصورة المنجزة")
            result["processed"] += 1
        except Exception as exc:
            result["errors"].append(f"{path.name}: {exc}")
    if progress_cb is not None:
        try:
            progress_cb(total, total)
        except Exception:
            pass
    return result


# ═══════════════════════ التركيب على processor_v2 ═══════════════════════

def _patch_processor() -> bool:
    """يُضيف التشطيب والتقويم إلى `processor_v2.ProcessorV2.process`."""
    try:
        from engine_v2 import processor_v2 as pv2
        if getattr(pv2.ProcessorV2.process, "_pipeline_patched", False):
            return True
        orig_process = pv2.ProcessorV2.process

        def patched_process(self, source_path, output_path, opts=None):
            """يمرر الظل إلى المعالجة الأولى بدل تعديل WebP بعد حفظه.

            المسار القديم كان يقرأ الناتج 800×700 من القرص، يستخرج قناعًا
            تقريبيًا من الأبيض، يقصه، ثم يحفظه بجودة 90. ذلك كسر أبعاد
            المحرر وأضاف كتابة ثانية لكل صورة. الآن يصل الظل إلى المعالج
            قبل التأطير، فتخرج لوحة 800×700 النهائية بكتابة واحدة.
            """
            try:
                from dataclasses import replace
                from engine_v2.processor_v2 import ProcessOptionsV2
                active_opts = opts if opts is not None else ProcessOptionsV2()
                if _AUTO_SHADOW_AFTER_ISOLATION and not getattr(
                        active_opts, "shadow_preset", ""):
                    active_opts = replace(active_opts, shadow_preset="ظل أرضي ناعم")
                return orig_process(self, source_path, output_path, active_opts)
            except Exception:
                # لا تمنع المعالجة الأساسية إن غابت طبقة الظل الاختيارية.
                return orig_process(self, source_path, output_path, opts)

        patched_process._pipeline_patched = True
        pv2.ProcessorV2.process = patched_process
        return True
    except Exception:
        return False


# ═══════════════════════ التركيب على الواجهة ═══════════════════════

def install_pipeline_patch(window: Any) -> dict:
    """يركّب كل الوحدات الجديدة على الواجهة ومسار الدفعة."""
    report: dict[str, Any] = {
        "processor_patched": False,
        "batch_tool_installed": False,
        "all_patches": [],
    }

    # ── وصل الدفعة ──
    report["processor_patched"] = _patch_processor()
    if report["processor_patched"]:
        report["all_patches"].append("processor_v2")

    # ── خيار الظل التلقائي للدفعة الجديدة: مفعّل افتراضيًا ──
    try:
        _install_auto_shadow_option(window)
        report["auto_shadow_option_installed"] = True
        report["all_patches"].append("auto_shadow_after_isolation")
    except Exception as exc:
        report["auto_shadow_option_error"] = str(exc)

    # ── تقريب المنتج اليدوي وحفظ موضعه على الصورة المحددة ──
    try:
        _install_product_framing_controls(window)
        report["product_framing_installed"] = True
        report["all_patches"].append("product_framing")
    except Exception as exc:
        report["product_framing_error"] = str(exc)

    # ── أداة الصور المنجزة الذكية: مدخل مستقل في رأس التطبيق ──
    # لا توضع في صفحة النتائج أو الجلسة؛ فلا تتداخل مع الربط أو الحفظ.
    try:
        _install_smart_finished_tool(window)
        report["smart_finished_tool_installed"] = True
        report["all_patches"].append("smart_finished_tool")
    except Exception as exc:
        report["smart_finished_tool_error"] = str(exc)

    # ── رقع الحماية والجلسات والمحرر ──
    for mod_name, install_fn_name in (
        ("windows_app.work_guard", "install_work_guard"),
        ("windows_app.session_fidelity_patch", "install_session_fidelity"),
        ("windows_app.editor_sync_patch", "install_editor_sync"),
        ("windows_app.editor_memory_patch", "install_memory_patch"),
    ):
        try:
            import importlib
            mod = importlib.import_module(mod_name)
            fn = getattr(mod, install_fn_name)
            if install_fn_name == "install_memory_patch":
                # تُركَّب على لوحة المحرر لا على النافذة
                editor = (getattr(window, "unified_editor", None)
                          or window.__dict__.get("_unified_editor_instance"))
                if editor is not None:
                    canvas = getattr(editor, "canvas", None)
                    if canvas is not None:
                        fn(canvas)
                        report["all_patches"].append(mod_name)
            else:
                fn(window)
                report["all_patches"].append(mod_name)
        except Exception as exc:
            report[f"{mod_name}_error"] = str(exc)

    return report


def _install_auto_shadow_option(window: Any) -> None:
    """يضيف مفتاحًا واضحًا للظل الخفيف في كل معالجة جديدة.

    القيمة الافتراضية مفعّلة؛ عند إلغائها لا يُمس الظل اليدوي في المحرر.
    """
    from PySide6.QtWidgets import QCheckBox

    toggle = QCheckBox("ظل تلقائي خفيف بعد عزل الخلفية")
    toggle.setObjectName("autoShadowAfterIsolation")
    toggle.setToolTip("يضيف ظل تلامس خفيفًا تلقائيًا لكل صورة تعزلها الدفعة")
    toggle.setChecked(True)

    def _apply(enabled: bool) -> None:
        global _AUTO_SHADOW_AFTER_ISOLATION
        _AUTO_SHADOW_AFTER_ISOLATION = bool(enabled)
        setattr(window, "auto_shadow_after_isolation", bool(enabled))
        # ProcessorV2 قد يُنشأ لاحقًا؛ نخزن التفضيل على النافذة أيضًا.
        try:
            processor = getattr(window, "processor", None)
            if processor is not None:
                processor.auto_shadow_after_isolation = bool(enabled)
        except Exception:
            pass

    _apply(True)
    toggle.toggled.connect(_apply)
    for attr in ("setup_panel", "options_panel", "controls_panel", "tools_panel"):
        panel = getattr(window, attr, None)
        if panel is not None and hasattr(panel, "layout") and panel.layout() is not None:
            panel.layout().addWidget(toggle)
            window._auto_shadow_after_isolation_cb = toggle
            return
    # الحاوية الفعلية في النافذة الأساسية: «3. تحسين المنتج والإخراج».
    try:
        from PySide6.QtWidgets import QGroupBox
        panel = window.findChild(QGroupBox, "enhancementGroup")
        if panel is not None and panel.layout() is not None:
            panel.layout().addWidget(toggle)
            window._auto_shadow_after_isolation_cb = toggle
            return
    except Exception:
        pass
    # الاحتفاظ بالمفتاح حتى لو اختلف تخطيط إصدار قديم من الواجهة.
    window._auto_shadow_after_isolation_cb = toggle


def _install_product_framing_controls(window: Any) -> None:
    """واجهة تقريب وحفظ موضع المنتج؛ الكتابة فوق نفس الملف فقط."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmapCache
    from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QPushButton,
                                   QSlider, QSpinBox, QVBoxLayout, QWidget)

    group = window.findChild(QGroupBox, "enhancementGroup")
    if group is None or group.layout() is None:
        return
    host = QWidget(group)
    host.setObjectName("productFramingControls")
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 4, 0, 0)
    layout.setSpacing(4)
    title = QLabel("تقريب وتمركز المنتج بعد العزل")
    title.setToolTip("يتم تمركز المنتج تلقائيًا في الدفعات؛ هذه الأدوات لتعديل الصورة المحددة وحفظها.")
    layout.addWidget(title)

    zoom_row = QHBoxLayout()
    zoom_row.addWidget(QLabel("التقريب:"))
    zoom = QSlider(Qt.Horizontal)
    zoom.setObjectName("productZoomPercent")
    zoom.setLayoutDirection(Qt.LeftToRight)
    zoom.setRange(100, 130)
    zoom.setValue(106)
    zoom.setSingleStep(1)
    value = QLabel("106%")
    value.setMinimumWidth(42)
    zoom.valueChanged.connect(lambda v: value.setText(f"{v}%"))
    zoom_row.addWidget(zoom, 1)
    zoom_row.addWidget(value)
    layout.addLayout(zoom_row)

    move_row = QHBoxLayout()
    move_row.addWidget(QLabel("الموضع:"))
    offset_x = QSpinBox(); offset_x.setRange(-20, 20); offset_x.setSuffix("% أفقي")
    offset_y = QSpinBox(); offset_y.setRange(-20, 20); offset_y.setSuffix("% رأسي")
    offset_x.setToolTip("قيمة موجبة = يمين، سالبة = يسار")
    offset_y.setToolTip("قيمة موجبة = أسفل، سالبة = أعلى")
    move_row.addWidget(offset_x)
    move_row.addWidget(offset_y)
    reset = QPushButton("توسيط")
    reset.setToolTip("يعيد المنتج إلى الوسط مع تقريب تلقائي خفيف")
    reset.clicked.connect(lambda: (zoom.setValue(106), offset_x.setValue(0), offset_y.setValue(0)))
    move_row.addWidget(reset)
    layout.addLayout(move_row)

    apply_btn = QPushButton("تطبيق وحفظ التقريب للصورة المحددة")
    apply_btn.setObjectName("saveProductFraming")
    apply_btn.setToolTip("يحفظ التقريب والموضع فوق نفس صورة الصنف بلا إنشاء ملف أو صف جديد")
    layout.addWidget(apply_btn)

    settings = getattr(window, "_product_frame_settings", None)
    if not isinstance(settings, dict):
        settings = {}
        window._product_frame_settings = settings

    def _selected():
        fn = getattr(window, "_selected_result_item", None)
        return fn() if callable(fn) else None

    def _key(item) -> str:
        return str(getattr(item, "output_path", "") or getattr(item, "source_name", ""))

    def _load_selected() -> None:
        item = _selected()
        data = settings.get(_key(item), {}) if item is not None else {}
        zoom.blockSignals(True); offset_x.blockSignals(True); offset_y.blockSignals(True)
        try:
            zoom.setValue(int(data.get("zoom_percent", 106)))
            offset_x.setValue(int(data.get("offset_x_percent", 0)))
            offset_y.setValue(int(data.get("offset_y_percent", 0)))
        finally:
            zoom.blockSignals(False); offset_x.blockSignals(False); offset_y.blockSignals(False)
        value.setText(f"{zoom.value()}%")

    def _save_current() -> None:
        item = _selected()
        if item is None:
            try:
                window.status_label.setText("حدد صورة من النتائج أولًا لتطبيق التقريب.")
            except Exception:
                pass
            return
        out_value = str(getattr(item, "output_path", "") or "")
        path = window._result_path(out_value) if out_value and hasattr(window, "_result_path") else Path(out_value)
        if not out_value or path is None or not Path(path).is_file():
            try:
                window.status_label.setText("لا توجد صورة ناتجة صالحة لحفظ التقريب عليها.")
            except Exception:
                pass
            return
        from framing_zoom_patch import ProductFrame, save_framed_image
        frame = ProductFrame(zoom.value(), offset_x.value(), offset_y.value()).normalized()
        if not save_framed_image(path, frame):
            try:
                window.status_label.setText("تعذر حفظ التقريب؛ بقيت الصورة الأصلية دون تغيير.")
            except Exception:
                pass
            return
        settings[_key(item)] = {
            "zoom_percent": frame.zoom_percent,
            "offset_x_percent": frame.offset_x_percent,
            "offset_y_percent": frame.offset_y_percent,
        }
        try:
            QPixmapCache.clear()
            position = window._capture_results_position()
            window._populate_results(restore_position=position)
            saver = getattr(window, "v2_save_session", None)
            if callable(saver):
                saver()
        except Exception:
            pass
        try:
            window.status_label.setText(
                f"حُفظ التقريب {frame.zoom_percent}% وموضعه داخل الصورة نفسها: {Path(path).name}")
        except Exception:
            pass

    apply_btn.clicked.connect(_save_current)
    table = getattr(window, "results_table", None)
    if table is not None and hasattr(table, "itemSelectionChanged"):
        table.itemSelectionChanged.connect(_load_selected)
    group.layout().addWidget(host)
    window._product_framing_controls = host
    window._product_zoom_slider = zoom
    window._product_offset_x = offset_x
    window._product_offset_y = offset_y
    window._save_product_framing = _save_current


def _install_smart_finished_tool(window: Any) -> None:
    """يضع معالجة الصور الجاهزة الذكية في رأس التطبيق، مستقلة عن الجلسات."""
    from PySide6.QtCore import Qt, QUrl
    from PySide6.QtGui import QImage, QPixmap, QDesktopServices
    from PySide6.QtWidgets import (
        QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
        QLabel, QMessageBox, QProgressDialog,
        QPushButton, QRadioButton, QVBoxLayout,
    )

    def _open() -> None:
        source_folder = QFileDialog.getExistingDirectory(
            window, "اختر مجلد الصور الجاهزة الأصلي")
        if not source_folder:
            return
        output_parent = QFileDialog.getExistingDirectory(
            window, "اختر مكان إنشاء مجلد نتائج جديد", str(Path(source_folder).parent))
        if not output_parent:
            return
        count = len(list(Path(source_folder).glob("*.webp"))) + len(list(Path(source_folder).glob("*.png")))
        dialog = QDialog(window)
        dialog.setWindowTitle("معالجة صور جاهزة بالذكاء")
        dialog.setMinimumWidth(480)
        layout = QVBoxLayout(dialog)
        source_label = QLabel(
            f"المدخل: {Path(source_folder).name} ({count} صورة)\n"
            f"النتيجة: سيُنشأ مجلد جديد داخل {Path(output_parent).name}")
        source_label.setWordWrap(True)
        layout.addWidget(source_label)
        note = QLabel(
            "هذه الأداة مستقلة عن Excel والباركود والجلسات. لا تكتب فوق المصدر، "
            "وتحتفظ باسم ودقة كل صورة داخل مجلد نتيجة جديد مع تقرير تفصيلي. "
            "النماذج المحلية مجانية ومضمّنة؛ لا حساب ولا اشتراك ولا اتصال وقت التشغيل.")
        note.setWordWrap(True)
        layout.addWidget(note)
        protect_radio = QRadioButton("حماية دقيقة — تنظيف متجر آمن مع تثبيت النص والشعار")
        radical_radio = QRadioButton("تحسين جذري مع حفظ النصوص — مظهر أقوى خارج مناطق النص")
        protect_radio.setChecked(True)
        protect_radio.setObjectName("smartFinishedProtectMode")
        radical_radio.setObjectName("smartFinishedRadicalMode")
        layout.addWidget(protect_radio)
        layout.addWidget(radical_radio)
        preserve = QCheckBox("تثبيت النصوص والشعارات قبل التصدير — موصى به")
        preserve.setChecked(True)
        preserve.setObjectName("smartFinishedPreserveText")
        preserve.setToolTip("يعيد بكسلات النص والشعار الأصلية بعد التحسين ويكتب نتيجة الحماية في التقرير.")
        layout.addWidget(preserve)
        preview_button = QPushButton("معاينة الصورة الأولى — دون حفظ")
        preview_button.setObjectName("smartFinishedPreview")
        layout.addWidget(preview_button)

        def _options() -> SmartFinishedOptions:
            return SmartFinishedOptions(
                mode="radical" if radical_radio.isChecked() else "protect",
                preserve_text=preserve.isChecked(),
            )

        def _preview() -> None:
            candidate = next(iter(sorted(Path(source_folder).glob("*.webp")) +
                                  sorted(Path(source_folder).glob("*.png"))), None)
            original = _read_image_unicode(candidate) if candidate is not None else None
            if original is None:
                QMessageBox.warning(dialog, "المعاينة", "تعذر قراءة صورة للمعاينة.")
                return
            enhanced, detail = apply_smart_finished_enhancements(original, _options())
            popup = QDialog(dialog)
            popup.setWindowTitle("معاينة صور المتجر الذكية — لا حفظ")
            popup_layout = QVBoxLayout(popup)
            row = QHBoxLayout()
            for title, image in (("الأصل", original), ("النتيجة", enhanced)):
                rgb = __import__("cv2").cvtColor(image, __import__("cv2").COLOR_BGR2RGB)
                height, width, channels = rgb.shape
                pixmap = QPixmap.fromImage(QImage(rgb.data, width, height, channels * width,
                                                   QImage.Format_RGB888).copy())
                label = QLabel(title)
                label.setAlignment(Qt.AlignCenter)
                label.setPixmap(pixmap.scaled(400, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                row.addWidget(label)
            popup_layout.addLayout(row)
            report = QLabel(
                f"السيناريو: {detail['scenario']} | وضع: {detail['mode']}\n"
                f"منطقة نص محمية: {detail['text_pixels']} بكسل | "
                f"مناطق كشف عميق: {detail['deep_text_boxes']} | "
                f"تحسين جذري: {detail['radical_pixels']} بكسل | "
                f"تغير قبل تثبيت النص: {detail['protected_changed_before_restore']} بكسل\n"
                f"القرار: {detail['radical_reason']}")
            report.setWordWrap(True)
            popup_layout.addWidget(report)
            close = QDialogButtonBox(QDialogButtonBox.Close)
            close.rejected.connect(popup.reject)
            popup_layout.addWidget(close)
            popup.exec()

        preview_button.clicked.connect(_preview)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        progress = QProgressDialog("جارٍ تحليل الصور وإنشاء النتائج…", "إلغاء", 0, 100, window)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        def _progress(done: int, total: int) -> None:
            if total:
                progress.setValue(int(done * 100 / total))
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()

        result = batch_process_finished_to_new_folder(
            source_folder, output_parent, options=_options(), progress_cb=_progress)
        progress.close()
        message = QMessageBox(window)
        message.setIcon(QMessageBox.Information)
        message.setWindowTitle("اكتملت المعالجة الذكية")
        message.setText(
            f"فُحصت: {result['examined']}\n"
            f"كُتبت في مجلد جديد: {result['written']}\n"
            f"نسخ بلا تغيير بصري: {result['unchanged']}\n"
            f"أخطاء: {len(result['errors'])}")
        message.setInformativeText(f"مجلد النتائج:\n{result['output_folder']}")
        open_button = message.addButton("فتح مجلد النتائج", QMessageBox.ActionRole)
        message.addButton(QMessageBox.Close)
        message.exec()
        if message.clickedButton() is open_button:
            QDesktopServices.openUrl(QUrl.fromLocalFile(result['output_folder']))

    button = QPushButton("صور جاهزة بالذكاء")
    button.setObjectName("smartFinishedToolButton")
    button.setToolTip(
        "تحليل وتحسين صور متجر جاهزة في مجلد نتائج مستقل: حماية دقيقة أو تحسين جذري مع حفظ النصوص. "
        "نماذج OCR محلية مجانية مضمّنة، بلا اشتراك أو اتصال وقت التشغيل.")
    button.clicked.connect(_open)
    header = getattr(window, "header_frame", None)
    header_layout = header.layout() if header is not None else None
    if header_layout is not None:
        # يوضع في رأس القائمة الرئيسية لا في صفحة النتائج أو قائمة الجلسات.
        header_layout.insertWidget(min(1, header_layout.count()), button)
    else:
        # احتياط للواجهات الأقدم، مع بقاء الأداة مستقلة عن النتائج.
        panel = getattr(window, "setup_panel", None)
        if panel is not None and panel.layout() is not None:
            panel.layout().insertWidget(0, button)
    window._smart_finished_tool_btn = button


def _install_finished_tool(window: Any) -> None:
    """يُضيف زر «معالجة الصور المنجزة» إلى لوحة الإعداد."""
    try:
        from PySide6.QtWidgets import (QPushButton, QProgressDialog,
                                       QFileDialog, QCheckBox, QGroupBox,
                                       QVBoxLayout, QHBoxLayout, QDialog, QLabel,
                                       QDialogButtonBox)
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage, QPixmap

        def _open_finished_tool():
            folder = QFileDialog.getExistingDirectory(
                window, "اختر مجلد الصور المنجزة")
            if not folder:
                return

            dlg = QDialog(window)
            dlg.setWindowTitle("معالجة الصور المنجزة")
            dlg.setMinimumWidth(380)
            layout = QVBoxLayout(dlg)
            layout.addWidget(QLabel(
                f"المجلد: {Path(folder).name}\n"
                f"الصور: {len(list(Path(folder).glob('*.webp')))} WebP"))
            note = QLabel(
                "لا يُعاد رسم العبوة أو توليد اسم/نص جديد. التحسين يعمل داخل "
                "قناع المنتج، ويترك الحالة غير المؤكدة دون تغيير.")
            note.setWordWrap(True)
            layout.addWidget(note)

            safe_all_cb = QCheckBox("معالجة شاملة آمنة: الحواف + الفجوات + الملمس + الظل")
            safe_all_cb.setObjectName("finishedSafeAll")
            safe_all_cb.setChecked(True)
            layout.addWidget(safe_all_cb)

            protect_cb = QCheckBox("الحفاظ على النصوص والباركود — موصى به")
            protect_cb.setObjectName("finishedPreserveTextBarcode")
            protect_cb.setToolTip(
                "يفحص كثافة الحواف؛ لا يرمم فجوة تشبه نصًا أو باركودًا.")
            protect_cb.setChecked(True)
            understand_cb = QCheckBox("فهم نوع الصورة تلقائيًا — موصى به")
            understand_cb.setObjectName("finishedUnderstandImageType")
            understand_cb.setToolTip(
                "يتعرف على اللوحات النصية وصور الحقائق الغذائية، ويمنع عليها التحسين البصري غير المناسب.")
            understand_cb.setChecked(True)

            refine_group = QGroupBox("خيارات مستقلة")
            refine_layout = QVBoxLayout(refine_group)
            edge_cb = QCheckBox("تنظيف الحواف والشوائب الدقيقة فقط")
            edge_cb.setObjectName("finishedRepairEdges")
            edge_cb.setToolTip("يزيل نقاطًا منفصلة صغيرة جدًا؛ لا يغير حافة العبوة المتصلة.")
            edge_cb.setChecked(True)
            gap_cb = QCheckBox("إصلاح الفجوات والقطع المؤكدة فقط")
            gap_cb.setObjectName("finishedRepairGaps")
            gap_cb.setToolTip("يوصل جزأين فقط عند وجود فجوة هندسية قصيرة مؤكدة.")
            gap_cb.setChecked(True)
            texture_cb = QCheckBox("ترميم نسيج المنتج داخل فجوة مؤكدة")
            texture_cb.setObjectName("finishedRestoreTexture")
            texture_cb.setToolTip(
                "يستكمل خامة محلية داخل فجوة محددة؛ لا ينشئ نصًا أو شعارًا أو باركودًا.")
            texture_cb.setChecked(True)
            shadow_cb = QCheckBox("إضافة ظل تلقائي للصور بلا ظل")
            shadow_cb.setObjectName("finishedAddShadow")
            shadow_cb.setChecked(True)
            appearance_cb = QCheckBox("تحسين مظهر المنتج بوعي — اختياري")
            appearance_cb.setObjectName("finishedEnhanceAppearance")
            appearance_cb.setToolTip(
                "تحسين بصري خفيف داخل المنتج فقط: إضاءة وتباين ناعم، مع استثناء النصوص والباركود وصور الحقائق الغذائية.")
            appearance_cb.setChecked(False)
            for control in (protect_cb, understand_cb, edge_cb, gap_cb, texture_cb, shadow_cb, appearance_cb):
                refine_layout.addWidget(control)
            layout.addWidget(refine_group)

            warning = QLabel("")
            warning.setWordWrap(True)
            layout.addWidget(warning)

            def _active_options() -> FinishedEnhancementOptions:
                return FinishedEnhancementOptions(
                    add_shadow=shadow_cb.isChecked(),
                    repair_edges=edge_cb.isChecked(),
                    repair_gaps=gap_cb.isChecked(),
                    restore_texture=texture_cb.isChecked(),
                    preserve_text_and_barcodes=protect_cb.isChecked(),
                    understand_image_type=understand_cb.isChecked(),
                    enhance_product_appearance=appearance_cb.isChecked(),
                )

            def _sync_texture() -> None:
                texture_cb.setEnabled(gap_cb.isChecked())
                if not gap_cb.isChecked():
                    texture_cb.setChecked(False)

            def _sync_warning() -> None:
                warning.setText(
                    "تنبيه: تعطيل حماية النصوص والباركود يسمح بترميم أوسع؛ "
                    "استخدمه فقط بعد معاينة صورة واحدة." if not protect_cb.isChecked() else "")

            def _enable_safe_all(enabled: bool) -> None:
                if not enabled:
                    return
                for control in (protect_cb, understand_cb, edge_cb, gap_cb, texture_cb, shadow_cb):
                    control.setChecked(True)
                _sync_texture()
                _sync_warning()

            def _mark_custom() -> None:
                if safe_all_cb.isChecked():
                    safe_all_cb.blockSignals(True)
                    safe_all_cb.setChecked(False)
                    safe_all_cb.blockSignals(False)
                _sync_texture()
                _sync_warning()

            safe_all_cb.toggled.connect(_enable_safe_all)
            for control in (protect_cb, understand_cb, edge_cb, gap_cb, texture_cb, shadow_cb, appearance_cb):
                control.toggled.connect(_mark_custom)
            _sync_texture()
            _sync_warning()

            preview_btn = QPushButton("معاينة آمنة للصورة المحددة — دون حفظ")
            preview_btn.setObjectName("previewFinishedEnhancement")
            preview_btn.setToolTip("يعرض الأصل والنتيجة المتوقعة ولا يكتب أي ملف.")

            def _preview() -> None:
                candidate = None
                selected = getattr(window, "_selected_result_item", None)
                item = selected() if callable(selected) else None
                output = str(getattr(item, "output_path", "") or "") if item is not None else ""
                if output and hasattr(window, "_result_path"):
                    candidate = window._result_path(output)
                if not candidate or not Path(candidate).is_file():
                    candidate = next(iter(sorted(Path(folder).glob("*.webp"))), None)
                original = _read_image_unicode(candidate) if candidate else None
                if original is None:
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.warning(window, "المعاينة", "تعذر قراءة صورة للمعاينة.")
                    return
                enhanced, report = apply_finished_enhancements(original, _active_options())
                popup = QDialog(dlg)
                popup.setWindowTitle("معاينة التحسين — لا حفظ")
                preview_layout = QVBoxLayout(popup)
                row = QHBoxLayout()
                for title, image in (("الأصل", original), ("النتيجة المتوقعة", enhanced)):
                    rgb = __import__("cv2").cvtColor(image, __import__("cv2").COLOR_BGR2RGB)
                    height, width, channels = rgb.shape
                    pixmap = QPixmap.fromImage(QImage(rgb.data, width, height, channels * width,
                                                       QImage.Format_RGB888).copy())
                    label = QLabel(title)
                    label.setAlignment(Qt.AlignCenter)
                    label.setPixmap(pixmap.scaled(390, 390, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                    row.addWidget(label)
                preview_layout.addLayout(row)
                preview_layout.addWidget(QLabel(
                    f"حواف: {report.get('specks', 0)} بكسل | فجوات: {report.get('holes', 0)} بكسل | "
                    f"نص/باركود محمي: {report.get('protected', 0)} | "
                    f"تحسين مظهر: {report.get('appearance', 0)} بكسل | ظل: {'نعم' if report.get('shadow') else 'لا'}"))
                close_btn = QDialogButtonBox(QDialogButtonBox.Close)
                close_btn.rejected.connect(popup.reject)
                preview_layout.addWidget(close_btn)
                popup.exec()

            preview_btn.clicked.connect(_preview)
            layout.addWidget(preview_btn)
            btns = QDialogButtonBox(
                QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            btns.accepted.connect(dlg.accept)
            btns.rejected.connect(dlg.reject)
            layout.addWidget(btns)
            if dlg.exec() != QDialog.Accepted:
                return

            prog = QProgressDialog("جارٍ المعالجة…", "إلغاء", 0, 100, window)
            prog.setWindowModality(Qt.WindowModal)
            prog.show()

            def _cb(done: int, total: int) -> None:
                if total > 0:
                    prog.setValue(int(done / total * 100))
                from PySide6.QtWidgets import QApplication
                QApplication.processEvents()

            res = batch_process_finished(
                folder,
                progress_cb=_cb,
                options=_active_options(),
            )
            prog.close()
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                window, "اكتملت المعالجة",
                f"فُحِصت: {res.get('examined', 0)}\n"
                f"حُسّنت: {res['processed']}\n"
                f"لا تحتاج تغييرًا آمنًا: {res.get('unchanged', 0)}\n"
                f"تعذر قراءتها: {res['skipped']}\n"
                f"حواف منظفة: {res['operations'].get('specks', 0)} بكسل\n"
                f"فجوات مرممة: {res['operations'].get('holes', 0)} بكسل\n"
                f"مناطق نص/باركود محمية: {res['operations'].get('protected', 0)}\n"
                f"ظلال مضافة: {res['operations'].get('shadow', 0)}\n"
                f"مظهر محسّن: {res['operations'].get('appearance', 0)} بكسل\n"
                f"لوحات معلومات محمية: {res['operations'].get('information_panel', 0)}\n"
                f"أخطاء: {len(res['errors'])}"
                + (f"\n\n{chr(10).join(res['errors'][:5])}"
                   if res["errors"] else ""),
            )

        # أضف الزر إلى شريط الإجراءات أو لوحة الإعداد
        btn = QPushButton("🖼 معالجة الصور المنجزة")
        btn.setToolTip("إضافة ظل وإكمال المنتجات الناقصة للصور الجاهزة")
        btn.clicked.connect(_open_finished_tool)

        for attr in ("results_action_bar", "setup_panel",
                     "delivery_panel", "tools_panel"):
            panel = getattr(window, attr, None)
            if panel is not None and hasattr(panel, "layout"):
                lay = panel.layout()
                if lay is not None:
                    lay.addWidget(btn)
                    window._finished_tool_btn = btn
                    return

        # احتياط: أضفه للنافذة الرئيسية
        window._finished_tool_btn = btn
    except Exception:
        pass
