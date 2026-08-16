from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows_app"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QListWidget  # noqa: E402
import barcode_linear_v32  # noqa: E402
from batch_input_v32 import install_batch_input_patch  # noqa: E402


class _Result:
    def __init__(self, text: str, fmt: str):
        self.text = text
        self.format = fmt


def test_qr_is_always_rejected() -> None:
    fake = SimpleNamespace(
        read_barcodes=lambda _image: [
            _Result("https://example.invalid/qr", "QRCode"),
            _Result("6281234567890", "EAN13"),
        ]
    )
    original = sys.modules.get("zxingcpp")
    sys.modules["zxingcpp"] = fake
    try:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "photo.jpg"
            cv2.imwrite(str(image_path), np.full((320, 640, 3), 245, np.uint8))
            values = barcode_linear_v32.read_linear_barcodes(image_path, max_attempts=3)
            assert values == ("6281234567890",), values
    finally:
        if original is None:
            del sys.modules["zxingcpp"]
        else:
            sys.modules["zxingcpp"] = original


class _Window:
    def __init__(self, files):
        self.image_paths = []
        self.image_list = QListWidget()
        self.status_label = QLabel()
        self.files = files
        self.count_updated = 0
        self.controls_updated = 0

    def _add_paths(self, _paths):
        raise AssertionError("يجب أن تستبدل الرقعة الإدخال الأصلي")

    def _expand_image_paths(self, _paths):
        return self.files

    def _update_image_count(self):
        self.count_updated += 1

    def _update_controls(self):
        self.controls_updated += 1


def test_batch_add_uses_single_widget_update() -> None:
    app = QApplication.instance() or QApplication([])
    _ = app
    files = [Path(f"/tmp/product_{i:04d}.jpg") for i in range(600)]
    window = _Window(files)
    install_batch_input_patch(window)
    window._add_paths(["/tmp/folder"])
    assert window.image_list.count() == 600
    assert len(window.image_paths) == 600
    assert window.count_updated == 1 and window.controls_updated == 1
    assert "600" in window.status_label.text()


if __name__ == "__main__":
    test_qr_is_always_rejected()
    test_batch_add_uses_single_widget_update()
    print("OK: linear-only barcode + 600-image batch input")
