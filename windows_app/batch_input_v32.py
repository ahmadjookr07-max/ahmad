"""إدخال صور دفعي سريع: تحديث واحد للقائمة بدل تحديث لكل صورة."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable


def install_batch_input_patch(window: Any) -> None:
    original = getattr(window, "_add_paths", None)
    if not callable(original) or getattr(original, "_v32_patched", False):
        return

    def path_key(path: Path) -> str:
        # resolve() يلمس القرص لكل صورة ويبطئ آلاف الصور أو القرص الشبكي.
        return str(path.absolute()).casefold()

    def patched_add_paths(paths: Iterable[str]) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QListView, QListWidgetItem

        # تفويض رسم الصفوف للدفعات بدل محاولة تخطيط آلاف الصفوف دفعة واحدة.
        window.image_list.setUniformItemSizes(True)
        window.image_list.setLayoutMode(QListView.Batched)
        window.image_list.setBatchSize(120)

        raw_paths = list(paths)
        known = {path_key(Path(path)) for path in getattr(window, "image_paths", [])}
        candidates = window._expand_image_paths(raw_paths)
        fresh = [path.absolute() for path in candidates
                 if path_key(path) not in known]
        if not fresh:
            if raw_paths:
                window.status_label.setText(
                    "لم تُضف صور جديدة؛ قد تكون مكررة أو بصيغة غير مدعومة.")
            window._update_image_count()
            window._update_controls()
            return

        image_list = window.image_list
        image_list.setUpdatesEnabled(False)
        image_list.setSortingEnabled(False)
        try:
            # أضف النصوص دفعة واحدة؛ هذا يلغي إعادة تخطيط النافذة لكل صورة.
            image_list.addItems([path.name for path in fresh])
            first_row = image_list.count() - len(fresh)
            for offset, path in enumerate(fresh):
                item = image_list.item(first_row + offset)
                item.setToolTip(str(path))
                item.setData(Qt.UserRole, str(path))
            window.image_paths.extend(fresh)
        finally:
            image_list.setUpdatesEnabled(True)
            image_list.setSortingEnabled(True)
            image_list.viewport().update()

        window._update_image_count()
        window._update_controls()
        window.status_label.setText(f"أُضيفت {len(fresh)} صورة — جاهزة للمعالجة.")

    patched_add_paths._v32_patched = True
    window._add_paths = patched_add_paths
