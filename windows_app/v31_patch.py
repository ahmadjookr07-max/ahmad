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

    # ── 3. تحسين الباركود الخطي: مقاييس/مناطق/زوايا متعددة، بلا QR ──
    try:
        _patch_barcode_multiangle(window)
        report["barcode_linear_v32"] = True
    except Exception as e:
        report["barcode_linear_v32_err"] = str(e)

    # ── 4. إدخال دفعات الصور بتحديث واحد للقائمة ──
    try:
        from batch_input_v32 import install_batch_input_patch
        install_batch_input_patch(window)
        report["batch_input_v32"] = True
    except Exception as e:
        report["batch_input_v32_err"] = str(e)

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
    """يربط القارئ الخطي المتطور بالمحرك؛ QR والرموز الثنائية مرفوضة."""
    from barcode_linear_v32 import read_linear_barcodes

    def read_barcode_multiangle(img_path: str) -> str | None:
        values = read_linear_barcodes(img_path)
        return values[0] if values else None

    try:
        from smart_catalog_vision import pipeline as _pipeline
        if not getattr(_pipeline, "_v32_barcode_patched", False):
            original_decode = getattr(_pipeline, "_decode_barcodes", None)
            if callable(original_decode):
                def patched_decode(path: str, *args, **kwargs):
                    # القارئ الأصلي لا يعيد إلا الباركود الخطي. إن نجح فلا
                    # ندفع ثمن المسح الموسع؛ وإلا ننتقل إلى خطة V3.2.
                    result = original_decode(path, *args, **kwargs)
                    if result:
                        return result
                    return read_linear_barcodes(path)
                patched_decode._v32_barcode_patched = True
                _pipeline._decode_barcodes = patched_decode
                _pipeline._v32_barcode_patched = True
    except Exception:
        pass

    window._read_barcode_multiangle = read_barcode_multiangle
