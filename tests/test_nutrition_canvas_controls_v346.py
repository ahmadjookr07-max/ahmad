from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows_app"))
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication
from nutrition_crop import NutritionCropCanvas


def run() -> None:
    app = QApplication.instance() or QApplication([])
    canvas = NutritionCropCanvas()
    canvas.resize(520, 360)
    canvas.show()
    app.processEvents()
    image = np.full((900, 1400, 3), 220, dtype=np.uint8)
    canvas.set_image(image)
    canvas.set_selection_image_rect((320, 190, 520, 360))
    original = canvas.selection_image_rect()
    assert original == (320, 190, 520, 360)

    # التقريب الدقيق لا يقفز، ويحفظ موضع التحديد في إحداثيات الأصل.
    canvas.zoom_by(1.08, QPointF(260, 180))
    assert 1.07 < canvas._zoom < 1.09
    assert canvas.selection_image_rect() == original

    # تحريك متطرف لا يخرج الصورة عن مجال الرؤية المسموح به.
    canvas._offset = QPointF(99999, -99999)
    canvas._clamp_offset()
    scale = canvas._scale()
    shown_w = canvas._pixmap.width() * scale
    shown_h = canvas._pixmap.height() * scale
    assert canvas._offset.x() <= 0.01
    assert canvas._offset.x() >= canvas.width() - shown_w - 0.01
    assert canvas._offset.y() <= 0.01
    assert canvas._offset.y() >= canvas.height() - shown_h - 0.01

    # عرض كامل يعيد الصورة كاملة من دون مسح اقتصاص المستخدم.
    canvas.fit_image()
    assert abs(canvas._zoom - 1.0) < 1e-6
    assert canvas.selection_image_rect() == original
    canvas.close()
    print("OK: nutrition crop view is bounded, precise, and preserves selection")


if __name__ == "__main__":
    run()
