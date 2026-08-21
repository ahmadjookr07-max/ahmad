from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MIS_SKIP_LICENSE", "1")

import cv2
import numpy as np
from PySide6.QtCore import QCoreApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "windows_app"), str(ROOT / "src")]
from native_app import EditorDirectSaveResult, IndividualEditWorker  # noqa: E402


def run() -> None:
    QCoreApplication.instance() or QCoreApplication([])
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        target = root / "10000001_حبه.webp"
        before = np.full((700, 800, 3), 230, np.uint8)
        assert cv2.imwrite(str(target), before, [cv2.IMWRITE_WEBP_QUALITY, 101])
        raw_before = target.read_bytes()
        edited = np.full((700, 800, 3), 255, np.uint8)
        edited[120:600, 250:550] = (40, 120, 210)
        worker = IndividualEditWorker(
            root, "front.jpg", preview_only=False, manual_crop=None,
            smart_enhance=False, enhancement_strength=0, smart_crop=False,
            auto_straighten=False, remove_background=False,
            previous_output=str(target), editor_output=edited,
        )
        results = []
        worker.completed.connect(results.append)
        assert worker._save_editor_output_directly()
        assert len(results) == 1 and isinstance(results[0], EditorDirectSaveResult)
        assert results[0].output_path == str(target)
        assert target.is_file() and target.read_bytes() != raw_before
        loaded = cv2.imread(str(target), cv2.IMREAD_COLOR)
        assert loaded is not None and np.array_equal(loaded[300, 400], edited[300, 400])
        assert len(list(root.glob("*.webp"))) == 1
        assert not list(root.glob("*.editor.tmp*"))
    print("OK: editor output saves atomically over the existing product image without pipeline")


if __name__ == "__main__":
    run()
