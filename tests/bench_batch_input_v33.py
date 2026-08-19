from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows_app"))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QListWidget, QListWidgetItem
from batch_input_v32 import install_batch_input_patch


class _Window:
    def __init__(self, paths):
        self.image_paths = []
        self.image_list = QListWidget()
        self.status_label = QLabel()
        self._paths = paths
    def _add_paths(self, _):
        raise AssertionError
    def _expand_image_paths(self, _):
        return self._paths
    def _update_image_count(self):
        pass
    def _update_controls(self):
        pass


def old_add(widget, paths):
    widget.setUpdatesEnabled(False)
    try:
        for path in paths:
            item = QListWidgetItem(path.name)
            item.setToolTip(str(path))
            item.setData(Qt.UserRole, str(path))
            widget.addItem(item)
    finally:
        widget.setUpdatesEnabled(True)
        widget.viewport().update()


def run():
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        paths = [Path(tmp) / f"product_{i:04d}.jpg" for i in range(600)]
        for p in paths:
            p.touch()
        old_list = QListWidget()
        start = time.perf_counter()
        old_add(old_list, paths)
        app.processEvents()
        old_seconds = time.perf_counter() - start

        window = _Window(paths)
        install_batch_input_patch(window)
        start = time.perf_counter()
        window._add_paths([tmp])
        app.processEvents()
        new_seconds = time.perf_counter() - start
        assert window.image_list.count() == 600
        assert new_seconds < old_seconds * 1.2, (old_seconds, new_seconds)
    print(f"OK: 600 images old={old_seconds:.4f}s batch={new_seconds:.4f}s")


if __name__ == "__main__":
    run()
