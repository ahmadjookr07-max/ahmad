"""مسار دفعة سريع: باركود خطي فقط بلا مطابقة أسماء أو OCR لكل صورة.

الصور التي لا تحتوي باركودًا تبقى للمراجعة أو لربط الوجه/الخلف اللاحق.
هذا مطابق لسير عمل المالك: الخلف يثبت الصنف بالباركود، والوجه لا يجب أن
يتأخر في مطابقة اسم ملف الكاميرا أو OCR عند الرفع.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = ["install_linear_barcode_fast_path"]


def install_linear_barcode_fast_path(pipeline: Any) -> bool:
    """يرقّع `_match_source` لمسار الباركود الخطي المؤكد فقط.

    لا يستدعي QR ولا OCR ولا filename matching. يعيد حالة مراجعة سليمة إن
    لم يُوجد باركود خطي أو كان مرشحًا ملتبسًا، ولا يخمّن هوية صورة أمامية.
    """
    if getattr(pipeline, "_mis_linear_fast_path", False):
        return True
    lookup = getattr(pipeline, "_lookup_barcode", None)
    if not callable(lookup):
        return False
    try:
        from barcode_linear_v32 import read_linear_barcodes
    except Exception:
        return False

    def fast_match(source: str | Path, index: Any, *, maximum_barcode_tier: int = 3):
        try:
            candidates = tuple(read_linear_barcodes(Path(source)))
        except Exception:
            candidates = ()
        for candidate in candidates:
            try:
                record, ambiguous = lookup(candidate, index)
            except Exception:
                continue
            if record is not None and not ambiguous:
                return record, "catalog_barcode", 1.0, candidates
        return None, "", 0.0, candidates

    pipeline._match_source = fast_match
    pipeline._mis_linear_fast_path = True
    return True
