# -*- coding: utf-8 -*-
"""حارس v3.4.23: الظل في المعاينة قد يُصغّر لتخفيف الذاكرة،
لكن الحفظ يجب أن يعيد تركيب المنتج كامل الدقة بلا إعادة تحجيم مدمّرة."""
from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "windows_app"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import cv2
import numpy as np
from PySide6.QtWidgets import QApplication

from engine_v2.shadow_v2 import ShadowOptions, apply_shadow
from photo_editor_v2 import V2PhotoEditorDialog

app = QApplication.instance() or QApplication(sys.argv)
FAILS: list[str] = []


def check(condition: bool, name: str) -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {name}")
    if not condition:
        FAILS.append(name)


with tempfile.TemporaryDirectory(prefix="shadow_hq_") as tmp:
    # أكبر من حد معاينة الظل (800px): حواف ونص دقيقان لكشف أي تصغير-تكبير.
    h, w = 1280, 1520
    image = np.full((h, w, 3), 245, np.uint8)
    cv2.rectangle(image, (300, 130), (1220, 1110), (35, 45, 65), -1)
    for y in range(170, 1060, 16):
        for x in range(340, 1180, 16):
            if ((x // 16) + (y // 16)) % 2:
                image[y:y + 8, x:x + 8] = (210, 215, 220)
    cv2.putText(image, "DETAIL-123456789", (420, 620),
                cv2.FONT_HERSHEY_SIMPLEX, 1.25, (245, 245, 245), 3,
                cv2.LINE_AA)
    source = os.path.join(tmp, "large_source.png")
    cv2.imwrite(source, image)

    dlg = V2PhotoEditorDialog(source)
    base = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
    alpha = np.zeros((h, w), np.uint8)
    alpha[130:1111, 300:1221] = 255
    base[:, :, 3] = alpha
    dlg._base = base
    dlg._cutout_applied = True
    dlg._shadow_opts = ShadowOptions(kind="contact", opacity=0.40, blur=29)

    # المعاينة تبقى خفيفة وسريعة؛ لا نستخدمها مرجعًا للحفظ.
    dlg._recompose()
    preview = dlg._composited.copy()
    actual = dlg.get_result_bgr()

    rgba = dlg._compose_rgba()
    pad = max(1, int(round(rgba.shape[1] * 0.06)))
    expected = dlg._flatten_white(apply_shadow(
        cv2.copyMakeBorder(rgba, 0, pad, pad, pad, cv2.BORDER_CONSTANT,
                           value=(0, 0, 0, 0)),
        dlg._shadow_opts,
    ))

    check(actual is not None, "يوجد ناتج حفظ عالي الدقة")
    check(actual.shape == expected.shape, "أبعاد الحفظ تشمل هامش الظل الكامل")
    check(bool(np.array_equal(actual, expected)),
          "الحفظ يطابق تركيب الظل الكامل لا معاينة الشاشة")
    check(preview.shape != actual.shape or not np.array_equal(preview, actual),
          "معاينة الظل لا تُستخدم كمصدر الحفظ")

    out = os.path.join(tmp, "saved.webp")
    ok, buf = cv2.imencode(".webp", actual, [cv2.IMWRITE_WEBP_QUALITY, 101])
    if ok:
        buf.tofile(out)
    restored = cv2.imdecode(np.fromfile(out, np.uint8), cv2.IMREAD_COLOR)
    check(restored is not None and restored.shape == actual.shape,
          "WebP اللافقدي يحتفظ بدقة المنتج النهائية")

print("ALL:", "PASS" if not FAILS else "FAIL")
sys.exit(0 if not FAILS else 1)
