# -*- coding: utf-8 -*-
"""حارس v3.4.27: صور WebP بأسماء عربية لا تصبح «تعذر قراءتها» على Windows."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "windows_app"), str(ROOT / "src")]
from pipeline_patch import (_read_image_unicode, _write_image_unicode,
                            batch_process_finished)

FAILS: list[str] = []


def check(condition: bool, text: str) -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {text}")
    if not condition:
        FAILS.append(text)


with tempfile.TemporaryDirectory(prefix="مسار_صور_عربي_") as temp:
    folder = Path(temp) / "الصور المنجزة"
    folder.mkdir()
    path = folder / "054881018463_ربطة_صورة خلفية.webp"
    image = np.full((220, 220, 3), 255, np.uint8)
    cv2.rectangle(image, (42, 32), (178, 180), (70, 130, 210), -1)

    check(_write_image_unicode(path, image), "حفظ WebP في اسم عربي ينجح")
    loaded = _read_image_unicode(path)
    check(loaded is not None and loaded.shape == image.shape,
          "قراءة WebP من اسم عربي تعيد صورة صحيحة")

    # نُجبر cv2.imread التقليدي على الفشل لمحاكاة OpenCV على Windows مع Unicode.
    # الدفعة يجب أن تنجح لأن المسار الجديد لا يستدعيه.
    with patch.object(cv2, "imread", side_effect=AssertionError("لا يجوز استخدام imread")):
        result = batch_process_finished(folder, add_shadow=True, complete=False)
    check(result["examined"] == 1, "تُفحص الصورة العربية بدل عدّها غير قابلة للقراءة")
    check(result["processed"] + result.get("unchanged", 0) == 1 and result["skipped"] == 0,
          "تُعالج الصورة العربية أو تُسجل سليمة، ولا تُعد غير قابلة للقراءة")
    check(not result["errors"], f"لا خطأ Unicode: {result['errors']}")
    check(path.exists() and _read_image_unicode(path) is not None,
          "الملف العربي يبقى قابلاً للقراءة بعد الحفظ")
    check(not list(folder.glob("*.writing.*")), "لا يبقى ملف مؤقت بعد الحفظ الذري")

print("ALL:", "PASS" if not FAILS else "FAIL")
sys.exit(0 if not FAILS else 1)
