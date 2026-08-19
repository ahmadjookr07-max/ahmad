from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
import zxingcpp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows_app"))
from barcode_linear_v32 import read_linear_barcodes

BARCODE = "6281234567895"


def _barcode_image() -> np.ndarray:
    # zxing-cpp نفسه هو القارئ في التطبيق؛ ينشئ هنا رمز EAN حقيقي صالح
    # لاختبار التقاطه من صورة منتج كبيرة وبميل حقيقي.
    barcode = zxingcpp.create_barcode(BARCODE, zxingcpp.BarcodeFormat.EAN13)
    image = zxingcpp.write_barcode_to_image(
        barcode, scale=5, add_hrt=True, add_quiet_zones=True)
    return np.asarray(image)


def _product_scene(angle: float, scale: float) -> np.ndarray:
    canvas = np.full((2400, 1800, 3), 238, np.uint8)
    code = _barcode_image()
    if code.ndim == 2:
        code = cv2.cvtColor(code, cv2.COLOR_GRAY2BGR)
    h, w = code.shape[:2]
    code = cv2.resize(code, (round(w * scale), round(h * scale)),
                      interpolation=cv2.INTER_CUBIC)
    h, w = code.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    rotated = cv2.warpAffine(code, matrix, (w, h), borderValue=(255, 255, 255))
    y, x = 1650, 450
    canvas[y:y + h, x:x + w] = rotated
    return canvas


def run() -> None:
    cases = [(0.0, 0.75), (12.0, 0.55), (-24.0, 0.40)]
    with tempfile.TemporaryDirectory() as tmp:
        for idx, (angle, scale) in enumerate(cases):
            path = Path(tmp) / f"ean_{idx}.jpg"
            assert cv2.imwrite(str(path), _product_scene(angle, scale),
                               [cv2.IMWRITE_JPEG_QUALITY, 88])
            values = read_linear_barcodes(path, max_attempts=28)
            assert BARCODE in values, (angle, scale, values)
    print("OK: EAN-13 captured at straight, near-tilted, and distant-tilted cases")


if __name__ == "__main__":
    run()
