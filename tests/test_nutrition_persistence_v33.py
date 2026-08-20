from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows_app"))
sys.path.insert(0, str(ROOT / "src"))
from nutrition_patch import install_nutrition_patch
from engine_v2.nutrition_v2 import InsetPlacement


class _Status:
    def __init__(self):
        self.value = ""

    def setText(self, text):
        self.value = str(text)


class _Window:
    def __init__(self, root: Path):
        self.root = root
        self._nutrition_dialog = SimpleNamespace(
            _overwrite_cb=SimpleNamespace(isChecked=lambda: True))
        self.status_label = _Status()
        self.current_workspace = root
        self.rebuilt = 0
        self.saved = 0
        self.zipped = 0
        self._save_nutrition_result = self._unexpected_save

    def _unexpected_save(self, *args, **kwargs):
        raise AssertionError("لا يجب إنشاء صورة تغذية جديدة في وضع الاستبدال")

    def _result_path(self, value):
        return self.root / str(value)

    def _capture_results_position(self):
        return None

    def _populate_results(self, **kwargs):
        self.rebuilt += 1

    def v2_save_session(self):
        self.saved += 1

    def _refresh_delivery_zip(self):
        self.zipped += 1


def run() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "10000001_حبه.webp"
        product = np.full((700, 800, 3), 220, np.uint8)
        product[180:560, 210:590] = (40, 90, 190)
        assert cv2.imwrite(str(target), product)
        before = target.read_bytes()
        selected = SimpleNamespace(output_path=target.name, item_code="10000001")
        window = _Window(root)
        install_nutrition_patch(window)
        crop = np.full((110, 160, 3), 255, np.uint8)
        cv2.putText(crop, "Nutrition", (8, 62), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, (0, 0, 0), 2)
        saved_name = window._save_nutrition_result(
            selected, crop, False, product_img=product,
            placement=InsetPlacement(anchor="bottom_right", scale=0.26))
        assert saved_name == target.name
        assert target.is_file() and target.read_bytes() != before
        assert not list(root.glob("*.nutrition.tmp*"))
        assert window.rebuilt == 1 and window.saved == 1 and window.zipped == 1
        assert "داخل الصورة نفسها" in window.status_label.value
    print("OK: nutrition merges atomically into the original output and persists session")


if __name__ == "__main__":
    run()
