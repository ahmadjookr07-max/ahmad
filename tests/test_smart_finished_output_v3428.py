from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

import cv2
import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from windows_app import pipeline_patch as pp  # noqa: E402


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _product_image() -> np.ndarray:
    image = np.full((700, 800, 3), 255, np.uint8)
    cv2.rectangle(image, (280, 120), (530, 615), (32, 84, 184), -1)
    cv2.rectangle(image, (298, 235), (512, 420), (245, 245, 245), -1)
    cv2.putText(image, "PRODUCT 500g", (310, 320), cv2.FONT_HERSHEY_SIMPLEX, 0.70, (5, 5, 5), 2)
    cv2.putText(image, "ORIGINAL LABEL", (310, 370), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (5, 5, 5), 1)
    return image


def _split_image() -> np.ndarray:
    image = np.full((700, 800, 3), 255, np.uint8)
    cv2.rectangle(image, (175, 180), (285, 420), (22, 120, 200), -1)
    cv2.rectangle(image, (490, 250), (650, 500), (100, 70, 25), -1)
    return image


def test_new_folder_and_source_integrity() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / "مصدر"
        source.mkdir()
        first = source / "منتج_حبه.webp"
        second = source / "منتج_حبه-1.webp"
        assert pp._write_image_unicode(first, _product_image())
        assert pp._write_image_unicode(second, _split_image())
        before = {path.name: _digest(path) for path in source.glob("*.webp")}
        result = pp.batch_process_finished_to_new_folder(
            source, root, options=pp.SmartFinishedOptions(mode="radical", preserve_text=True))
        output = Path(result["output_folder"])
        assert output.is_dir()
        assert output.parent == root
        assert set(before) == {path.name for path in output.glob("*.webp")}
        assert before == {path.name: _digest(path) for path in source.glob("*.webp")}
        assert result["examined"] == 2
        assert result["written"] == 2
        assert result["skipped"] == 0
        assert not result["errors"]
        assert (output / "smart_processing_report.json").is_file()
        assert (output / "smart_processing_report.csv").is_file()


def test_radical_preserves_detected_text_area() -> None:
    original = _product_image()
    profile = pp._smart_image_profile(original)
    enhanced, detail = pp.apply_smart_finished_enhancements(
        original, pp.SmartFinishedOptions(mode="radical", preserve_text=True))
    protected = profile["text_mask"]
    assert protected.any()
    assert np.array_equal(enhanced[protected], original[protected])
    assert detail["mode"] == "radical"
    assert detail["scenario"] in {"standard_single_product", "text_heavy_packaging"}


def test_separate_components_are_never_joined() -> None:
    original = _split_image()
    profile = pp._smart_image_profile(original)
    enhanced, detail = pp.apply_smart_finished_enhancements(
        original, pp.SmartFinishedOptions(mode="radical", preserve_text=True))
    assert profile["scenario"] in {"split_or_double_component", "multiple_separate_components"}
    # الوسط بين المنتجين يبقى خلفية بيضاء؛ أي وصلة مولدة هنا خطأ.
    assert np.all(enhanced[330:390, 350:455] >= 248)
    assert detail["radical_pixels"] == 0


def test_smart_button_is_in_main_header() -> None:
    from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QMainWindow

    app = QApplication.instance() or QApplication([])
    window = QMainWindow()
    window.header_frame = QFrame()
    QHBoxLayout(window.header_frame)
    pp._install_smart_finished_tool(window)
    button = getattr(window, "_smart_finished_tool_btn", None)
    assert button is not None
    assert button.objectName() == "smartFinishedToolButton"
    assert button.parent() is window.header_frame
    assert "مجلد نتائج مستقل" in button.toolTip()
    app.processEvents()


if __name__ == "__main__":
    test_new_folder_and_source_integrity()
    test_radical_preserves_detected_text_area()
    test_separate_components_are_never_joined()
    test_smart_button_is_in_main_header()
    print("smart finished output tests passed")
