# -*- coding: utf-8 -*-
"""اختبار pipeline_patch (م-19 م-21 م-22)."""
from __future__ import annotations
import sys, tempfile
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "windows_app"))

# تهيئة Qt قبل أي استيراد يستخدمها
try:
    from PySide6.QtWidgets import QApplication as _QApp
    _app = _QApp.instance() or _QApp(sys.argv)
except Exception:
    pass

from windows_app.pipeline_patch import (
    apply_shadow_to_finished, apply_completion_to_finished,
    batch_process_finished, install_pipeline_patch,
)

FAILS: list[str] = []

def check(c: bool, msg: str) -> None:
    print(("  ✓ " if c else "  ✗ ") + msg)
    if not c: FAILS.append(msg)

def _make_white_product(h=200, w=200):
    """صورة بيضاء بمستطيل رمادي في المنتصف (محاكاة منتج على أبيض)."""
    img = np.full((h, w, 3), 255, np.uint8)
    img[40:160, 40:160] = 120
    return img

def test_shadow_to_finished():
    print("\n[1] إضافة الظل لصورة منجزة")
    img = _make_white_product()
    out = apply_shadow_to_finished(img)
    check(isinstance(out, np.ndarray), "الناتج مصفوفة")
    check(out.shape[:2] == img.shape[:2] or out.shape[0] >= img.shape[0],
          "الأبعاد معقولة")

def test_completion_to_finished():
    print("\n[2] إكمال المنتجات الناقصة")
    img = _make_white_product()
    out = apply_completion_to_finished(img)
    check(isinstance(out, np.ndarray), "الناتج مصفوفة")
    check(out.shape == img.shape, "الأبعاد محفوظة")

def test_batch_empty_folder():
    print("\n[3] معالجة دفعية لمجلد فارغ")
    with tempfile.TemporaryDirectory() as d:
        res = batch_process_finished(d, add_shadow=True, complete=False)
        check(res["processed"] == 0, "لا معالجة في مجلد فارغ")
        check(res["skipped"] == 0, "لا تخطٍّ في مجلد فارغ")
        check(not res["errors"], "لا أخطاء")

def test_batch_with_images():
    print("\n[4] معالجة دفعية لصور WebP")
    import cv2
    with tempfile.TemporaryDirectory() as d:
        for i in range(3):
            img = _make_white_product()
            cv2.imwrite(str(Path(d) / f"img_{i}.webp"), img,
                        [cv2.IMWRITE_WEBP_QUALITY, 90])
        progress = []
        res = batch_process_finished(
            d, add_shadow=True, complete=False,
            progress_cb=lambda d, t: progress.append((d, t)))
        check(res["processed"] + res["skipped"] == 3,
              f"معالجة 3 صور (معالجة={res['processed']} تخطٍّ={res['skipped']})")
        check(not res["errors"], f"لا أخطاء: {res['errors']}")
        check(len(progress) >= 3, "استدعاء التقدم")

def test_install_pipeline_patch():
    print("\n[5] تركيب pipeline_patch على نافذة وهمية")
    class FakeWin:
        pass
    rep = install_pipeline_patch(FakeWin())
    check(isinstance(rep, dict), "يعيد قاموس تقرير")
    check("all_patches" in rep, "يحتوي all_patches")

def main():
    print("=" * 60)
    print("اختبار pipeline_patch")
    print("=" * 60)
    test_shadow_to_finished()
    test_completion_to_finished()
    test_batch_empty_folder()
    test_batch_with_images()
    test_install_pipeline_patch()
    print("\n" + "=" * 60)
    if FAILS:
        print(f"إخفاقات: {len(FAILS)}")
        for f in FAILS: print(f"  · {f}")
        return 1
    print("كل الفحوص نجحت")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
