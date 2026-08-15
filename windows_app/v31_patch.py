# -*- coding: utf-8 -*-
"""v31_patch — إصلاحات الإصدار 3.1
- م-ت1: التغذية تنشئ صورتين — الاستبدال يصير افتراضيًا عند الدمج
- م-ت2: الجلستان تتدمجان — إعادة تهيئة current_result عند استئناف جلسة جديدة
- م-ب1: تحسين قراءة الباركود بتدوير الصورة بزوايا متعددة
"""
from __future__ import annotations
from typing import Any

__all__ = ["install_v31_patch"]


def install_v31_patch(window: Any) -> dict:
    report: dict[str, Any] = {}

    # ── 1. إصلاح التغذية: الاستبدال افتراضيًا ──
    try:
        _patch_nutrition_overwrite_default(window)
        report["nutrition_overwrite_default"] = True
    except Exception as e:
        report["nutrition_overwrite_default_err"] = str(e)

    # ── 2. إصلاح الجلسات: إعادة تهيئة عند استئناف جديد ──
    try:
        _patch_session_reset(window)
        report["session_reset"] = True
    except Exception as e:
        report["session_reset_err"] = str(e)

    # ── 3. تحسين الباركود: تدوير متعدد ──
    try:
        _patch_barcode_multiangle(window)
        report["barcode_multiangle"] = True
    except Exception as e:
        report["barcode_multiangle_err"] = str(e)

    return report


def _patch_nutrition_overwrite_default(window: Any) -> None:
    """يجعل وضع الدمج يكتب فوق الصورة الأصلية مباشرةً بدل إنشاء جديدة."""
    save_fn = getattr(window, "_save_nutrition_result", None)
    if not callable(save_fn) or getattr(save_fn, "_v31_patched", False):
        return

    def patched_save(selected: Any, cropped: Any, on_canvas: bool,
                     product_img: Any = None,
                     placement: Any = None) -> str:
        # عند الدمج (placement موجود) — اكتب فوق الأصل مباشرةً
        if product_img is not None and placement is not None:
            try:
                out_path = str(getattr(selected, "output_path", "") or "")
                if out_path:
                    p = (window._result_path(out_path)
                         if hasattr(window, "_result_path")
                         else None)
                    if p is not None and p.is_file():
                        import cv2
                        from engine_v2.nutrition_v2 import merge_label_inset
                        final = merge_label_inset(product_img, cropped, placement)
                        cv2.imwrite(str(p), final,
                                    [cv2.IMWRITE_WEBP_QUALITY, 100])
                        try:
                            window.status_label.setText(
                                f"تم دمج حقائق التغذية في: {p.name}")
                        except Exception:
                            pass
                        return p.name
            except Exception:
                pass
        # وضع منفصل أو فشل الاستبدال — أنشئ صورة جديدة
        return save_fn(selected, cropped, on_canvas,
                       product_img=product_img, placement=placement)

    patched_save._v31_patched = True
    window._save_nutrition_result = patched_save


def _patch_session_reset(window: Any) -> None:
    """يُعيد تهيئة current_result عند بدء جلسة جديدة لمنع الدمج."""
    # لفّ _begin_new_session أو ما يُعادلها
    for fn_name in ("_begin_new_session", "_start_new_session",
                    "_new_session", "new_session"):
        fn = getattr(window, fn_name, None)
        if callable(fn) and not getattr(fn, "_v31_patched", False):
            def make_patched(orig):
                def patched(*args, **kwargs):
                    # أعد تهيئة النتائج قبل بدء الجلسة الجديدة
                    try:
                        window.current_result = None
                    except Exception:
                        pass
                    return orig(*args, **kwargs)
                patched._v31_patched = True
                return patched
            setattr(window, fn_name, make_patched(fn))
            break

    # لفّ الدالة *المربوطة بالنافذة*؛ ترقيع الوحدة وحدها لا يكفي لأن
    # install_v2 ينسخ الدالة إلى main_window قبل وصول هذه الرقعة.
    orig_restore = getattr(window, "v2_restore_session", None)
    if callable(orig_restore) and not getattr(orig_restore, "_v31_patched", False):
        def patched_restore(session_id: str, *args, **kwargs):
            # أعد تهيئة جميع المراجع المرئية قبل استئناف جلسة مختلفة.
            try:
                window.current_result = None
                window._result_items_by_name = {}
                window._manual_reference_source_name = ""
                window._editor_drafts = {}
            except Exception:
                pass
            return orig_restore(session_id, *args, **kwargs)
        patched_restore._v31_patched = True
        window.v2_restore_session = patched_restore


def _patch_barcode_multiangle(window: Any) -> None:
    """يُحسّن قراءة الباركود بتدوير الصورة بزوايا متعددة."""
    import sys
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    try:
        import zxingcpp
    except ImportError:
        return

    import cv2
    import numpy as np

    def read_barcode_multiangle(img_path: str) -> str | None:
        """يقرأ الباركود بتدوير الصورة بزوايا متعددة للحصول على أفضل نتيجة."""
        try:
            data = np.fromfile(img_path, dtype=np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_COLOR)
            if img is None:
                return None
        except Exception:
            return None

        # تصغير للسرعة إذا كانت كبيرة
        h, w = img.shape[:2]
        if max(h, w) > 1500:
            scale = 1500 / max(h, w)
            img = cv2.resize(img, (int(w * scale), int(h * scale)))
            h, w = img.shape[:2]

        angles = [0, 90, 180, 270, 45, -45, 15, -15, 30, -30]
        for angle in angles:
            if angle == 0:
                rotated = img
            else:
                M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
                rotated = cv2.warpAffine(img, M, (w, h),
                                         borderMode=cv2.BORDER_REPLICATE)
            try:
                results = zxingcpp.read_barcodes(rotated)
                for r in results:
                    text = getattr(r, "text", "") or ""
                    fmt = str(getattr(r, "format", "")).lower()
                    # رفض QR و2D
                    if any(x in fmt for x in ("qr", "data", "aztec",
                                               "pdf", "maxi")):
                        continue
                    if text and len(text) >= 6:
                        return text
            except Exception:
                continue
        return None

    # تسجيل الدالة للاستخدام من المحرك
    try:
        from smart_catalog_vision import pipeline as _pipeline
        if not getattr(_pipeline, "_v31_barcode_patched", False):
            _orig_decode = getattr(_pipeline, "_decode_barcodes", None)
            if callable(_orig_decode):
                def _patched_decode(path: str, *args, **kwargs):
                    result = _orig_decode(path, *args, **kwargs)
                    if result:
                        return result
                    # محاولة بالتدوير المتعدد
                    text = read_barcode_multiangle(path)
                    return [text] if text else []
                _patched_decode._v31_barcode_patched = True
                _pipeline._decode_barcodes = _patched_decode
                _pipeline._v31_barcode_patched = True
    except Exception:
        pass

    # تسجيل على الواجهة للاستخدام المباشر
    window._read_barcode_multiangle = read_barcode_multiangle
