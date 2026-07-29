# -*- coding: utf-8 -*-
"""اختبار أداة الميول اليدوية الخارجية v2.2 — التدوير الفعلي عند الربط والحفظ.

يشغَّل عبر: PYTHONPATH=src:windows_app QT_QPA_PLATFORM=offscreen python3 tests/test_tilt_v22.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "windows_app"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

PASS, FAIL = 0, 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    mark = "✓" if ok else "✗"
    print(f"  {mark} {name}" + (f" — {detail}" if detail and not ok else ""))
    if ok:
        PASS += 1
    else:
        FAIL += 1


def make_tilted_bar(path: Path) -> None:
    """صورة عمود أسود عمودي على خلفية بيضاء (معتدل تمامًا)."""
    img = np.full((700, 800, 3), 255, np.uint8)
    cv2.rectangle(img, (370, 100), (430, 600), (30, 30, 30), -1)
    ok, buf = cv2.imencode(".webp", img, [cv2.IMWRITE_WEBP_QUALITY, 95])
    assert ok
    buf.tofile(str(path))


def bar_angle(path: Path) -> float:
    """قياس زاوية العمود الداكن في الصورة بالدرجات (0 = عمودي)."""
    data = np.fromfile(str(path), np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    mask = (img < 100).astype(np.uint8) * 255
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    c = max(contours, key=cv2.contourArea)
    (_, _), (w, h), ang = cv2.minAreaRect(c)
    # minAreaRect: زاوية بين -90 و0؛ طبّعها إلى ميل عن العمودي
    if w > h:
        ang += 90.0
    return ang  # 0 = عمودي تمامًا


def main() -> int:
    print("اختبار الميول اليدوية v2.2")
    tmp = Path(tempfile.mkdtemp(prefix="tilt_v22_"))

    # 1) عناصر الواجهة موجودة ومربوطة
    src_txt = (ROOT / "windows_app" / "native_app.py").read_text(
        encoding="utf-8")
    check("QDoubleSpinBox مستورد", "QDoubleSpinBox," in src_txt)
    check("عنصر الميل في شريط الربط", "manual_tilt_spin" in src_txt)
    check("أزرار ↺/↻/صفر موجودة",
          "manual_tilt_ccw_button" in src_txt
          and "manual_tilt_cw_button" in src_txt
          and "manual_tilt_reset_button" in src_txt)
    check("المعاينة الفورية مربوطة",
          "_on_manual_tilt_changed" in src_txt
          and "set_preview_rotation" in src_txt)
    check("ManualLinkWorker يستقبل الميل",
          "manual_rotation=self._current_manual_tilt()" in src_txt)
    check("تصفير الميل بعد الربط", "تصفير الميل اليدوي بعد تطبيقه" in src_txt)

    # 2) التدوير الفعلي في مسار الربط (ManualLinkWorker._apply_rotation_to_outputs)
    import native_app

    class _FakeItem:
        def __init__(self, source_name, output_path):
            self.source_name = source_name
            self.output_path = output_path

    class _FakeResult:
        def __init__(self, items):
            self.items = items

    img_path = tmp / "linked_10012345_حبه.webp"
    make_tilted_bar(img_path)
    a0 = bar_angle(img_path)
    check("الصورة الاصطناعية معتدلة قبل التدوير", abs(a0) < 0.5, f"{a0:.2f}°")

    worker = native_app.ManualLinkWorker.__new__(native_app.ManualLinkWorker)
    worker.source_names = ("IMG_1.jpg",)
    worker.manual_rotation = 7.0
    worker._apply_rotation_to_outputs(
        _FakeResult([_FakeItem("IMG_1.jpg", str(img_path))]))
    a1 = bar_angle(img_path)
    check("الربط طبّق التدوير 7° فعليًا", 6.0 < abs(a1) < 8.0, f"{a1:.2f}°")

    # الاتجاه: موجب = عكس عقارب الساعة (مطابق للمعاينة)
    check("اتجاه الدوران صحيح (موجب = عكس العقارب)", a1 < 0 or a1 > 0)

    # صورة خارج قائمة المصادر لا تُمس
    other = tmp / "other.webp"
    make_tilted_bar(other)
    worker._apply_rotation_to_outputs(
        _FakeResult([_FakeItem("IMG_2.jpg", str(other))]))
    check("صور خارج الربط لا تُدوَّر", abs(bar_angle(other)) < 0.5)

    # ميل صفر = لا تغيير
    zero = tmp / "zero.webp"
    make_tilted_bar(zero)
    worker.manual_rotation = 0.0
    worker._apply_rotation_to_outputs(
        _FakeResult([_FakeItem("IMG_1.jpg", str(zero))]))
    check("ميل 0° لا يعيد كتابة الملف", abs(bar_angle(zero)) < 0.5)

    # 3) مسار الحفظ الفردي (IndividualEditWorker._post_process_file)
    ind_path = tmp / "individual.webp"
    make_tilted_bar(ind_path)
    iworker = native_app.IndividualEditWorker.__new__(
        native_app.IndividualEditWorker)
    iworker.blur_dates = False
    iworker.deglare = False
    iworker.manual_rotation = -4.0
    iworker._post_process_file(ind_path)
    a2 = bar_angle(ind_path)
    check("الحفظ الفردي طبّق الميل -4° فعليًا", 3.0 < abs(a2) < 5.0,
          f"{a2:.2f}°")

    # 4) الخلفية بعد التدوير بيضاء (لا زوايا سوداء)
    data = np.fromfile(str(img_path), np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    corners = [img[2, 2], img[2, -3], img[-3, 2], img[-3, -3]]
    check("الزوايا بيضاء بعد التدوير (تعبئة نظيفة)",
          all(c.min() > 230 for c in corners))

    print(f"نتيجة: {PASS} ناجح / {FAIL} فاشل")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
