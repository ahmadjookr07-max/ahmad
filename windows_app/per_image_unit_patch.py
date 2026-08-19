"""اختيار وحدة تخص صورة واحدة وفق وحدات الصنف الفعلية في الإكسل.

يخدم المسارات الجديدة والمجلدات المنجزة: يختار المستخدم من وحدات الصنف
المطابقة في الإكسل (حبة/شدة/كرتون/ربطة أو الإملاء الحرفي الموجود فيه)، ثم
يعتمد الاسم ويعيد ترقيم صور الوحدة نفسها بلا التأثير في بقية وحدات الصنف.
"""
from __future__ import annotations

import dataclasses
import os
from pathlib import Path
from typing import Any

__all__ = ["install_per_image_unit", "PER_IMAGE_UNITS"]

# احتياط فقط عندما لا يوجد إكسل؛ الإكسل يظل مصدر الحقيقة عند وجوده.
PER_IMAGE_UNITS = ["حبه", "شدة", "كرتون", "ربطة"]


def _item_units(window: Any, item: Any | None) -> list[str]:
    code = str(getattr(item, "item_code", "") or "").strip()
    index = getattr(window, "v2_catalog_index", None)
    if code and index is not None:
        try:
            units = [str(u).strip() for u in index.units_for_code(code)
                     if str(u or "").strip()]
            if units:
                return units
        except Exception:
            pass
    return list(PER_IMAGE_UNITS)


def _output_path(window: Any, item: Any) -> Path | None:
    raw = str(getattr(item, "output_path", "") or "")
    if not raw:
        return None
    try:
        path = window._result_path(raw)
    except Exception:
        path = Path(raw)
    return Path(path) if path else None


def _stem(item_code: str, unit: str, seq: int) -> str:
    base = f"{str(item_code).strip()}_{str(unit).strip()}"
    return base if seq <= 0 else f"{base}-{seq}"


def _sequence_for_path(item_code: str, unit: str, path: Path) -> int:
    stem = path.stem
    base = f"{item_code}_{unit}"
    if stem == base:
        return 0
    prefix = base + "-"
    if stem.startswith(prefix):
        try:
            return max(1, int(stem[len(prefix):]))
        except ValueError:
            pass
    return 0


def _safe_target(folder: Path, item_code: str, unit: str, preferred: int,
                 current: Path) -> Path:
    seq = max(0, int(preferred))
    while True:
        candidate = folder / f"{_stem(item_code, unit, seq)}{current.suffix}"
        if candidate == current or not candidate.exists():
            return candidate
        seq += 1


def _relative(window: Any, path: Path) -> str:
    workspace = getattr(window, "current_workspace", None)
    if workspace is not None:
        try:
            return str(path.relative_to(Path(workspace)))
        except ValueError:
            pass
    return str(path)


def _replace_result_path(window: Any, old_path: Path, new_path: Path,
                         selected: Any) -> None:
    result = getattr(window, "current_result", None)
    if result is None:
        return
    changed = []
    for item in result.items:
        path = _output_path(window, item)
        if path is None or os.path.normcase(str(path)) != os.path.normcase(str(old_path)):
            changed.append(item)
            continue
        fields = {"output_path": _relative(window, new_path),
                  "review_path": _relative(window, new_path)}
        # المجلد المنجز يعتبر الملف نفسه مصدرًا؛ يجب تحديث المصدر أيضًا.
        if getattr(item, "match_source", "") == "legacy_folder":
            fields.update({"source_path": str(new_path), "source_name": new_path.name})
        changed.append(dataclasses.replace(item, **fields))
    result.items[:] = changed


def _renumber_unit_group(window: Any, item_code: str, unit: str) -> None:
    """يرتب صور الوحدة فقط: الغلاف بلا رقم ثم -1/-2؛ لا يخلط الوحدات."""
    result = getattr(window, "current_result", None)
    if result is None:
        return
    members: list[tuple[int, Any, Path]] = []
    for index, item in enumerate(result.items):
        if str(getattr(item, "item_code", "") or "") != str(item_code):
            continue
        path = _output_path(window, item)
        if path is None or not path.is_file():
            continue
        if _sequence_for_path(str(item_code), str(unit), path) >= 0 and \
                path.stem.startswith(f"{item_code}_{unit}"):
            members.append((index, item, path))
    if len(members) < 2:
        return
    members.sort(key=lambda row: (_sequence_for_path(item_code, unit, row[2]), row[2].name))
    folder = members[0][2].parent
    staged: list[tuple[Path, Path]] = []
    try:
        for index, (_row, _item, source) in enumerate(members):
            temp = source.with_name(f".__unit_tmp_{index}__{source.name}")
            os.replace(source, temp)
            staged.append((temp, source))
        for index, (temp, old) in enumerate(staged):
            target = old.with_name(f"{_stem(item_code, unit, index)}{old.suffix}")
            os.replace(temp, target)
            _replace_result_path(window, old, target, None)
    except Exception:
        for temp, old in staged:
            try:
                if temp.exists():
                    os.replace(temp, old)
            except Exception:
                pass
        raise


def _apply_unit(window: Any, item: Any, unit: str) -> bool:
    code = str(getattr(item, "item_code", "") or "").strip()
    source = _output_path(window, item)
    if not code or source is None or not source.is_file() or not unit:
        return False
    preferred = _sequence_for_path(code, unit, source)
    target = _safe_target(source.parent, code, unit, preferred, source)
    if target != source:
        os.replace(source, target)
        _replace_result_path(window, source, target, item)
    _renumber_unit_group(window, code, unit)
    try:
        position = window._capture_results_position()
        window._populate_results(restore_position=position)
    except Exception:
        pass
    try:
        saver = getattr(window, "v2_save_session", None)
        if callable(saver):
            saver()
    except Exception:
        pass
    return True


def install_per_image_unit(window: Any) -> dict:
    """يركب اختيار وحدة ظاهرًا في لوحة التحرير المباشر."""
    report: dict[str, Any] = {"installed": False}
    if getattr(window, "_per_image_unit_v33", False):
        return report
    try:
        from PySide6.QtCore import QSignalBlocker
        from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget

        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(6, 4, 6, 4)
        row.setSpacing(7)
        label = QLabel("وحدة تسمية هذه الصورة:")
        combo = QComboBox()
        combo.setMinimumWidth(150)
        combo.setToolTip("تظهر فقط الوحدات المتاحة لهذا الصنف في ملف الإكسل")
        apply_btn = QPushButton("اعتماد الوحدة وإعادة ترقيمها")
        apply_btn.setToolTip("يحفظ اسم هذه الصورة وفق الوحدة المختارة ثم يرتب صور الوحدة نفسها")
        row.addWidget(label)
        row.addWidget(combo)
        row.addWidget(apply_btn)
        row.addStretch(1)

        window._per_image_unit_override = None
        window._per_image_unit_combo = combo
        window._per_image_unit_widget = box

        def selected_item():
            try:
                return window._individual_editable_item()
            except Exception:
                return None

        def refresh_units() -> None:
            item = selected_item()
            units = _item_units(window, item)
            blocker = QSignalBlocker(combo)
            combo.clear()
            combo.addItem("— كما في الإكسل —", None)
            for unit in units:
                combo.addItem(unit, unit)
            del blocker
            multi = len(units) > 1
            box.setVisible(multi or item is not None)
            label.setText("وحدة تسمية هذه الصورة:" if multi else "وحدة الصنف في الإكسل:")
            apply_btn.setEnabled(item is not None and bool(getattr(item, "item_code", "")))
            window._per_image_unit_override = None

        def changed(index: int) -> None:
            unit = combo.itemData(index)
            window._per_image_unit_override = unit
            if unit:
                window.status_label.setText(
                    f"الوحدة المختارة: {unit} — ستتغير هذه الصورة فقط وتُرتّب صور الوحدة.")

        def apply() -> None:
            item = selected_item()
            unit = combo.currentData()
            if item is None or not unit:
                return
            if _apply_unit(window, item, str(unit)):
                window.status_label.setText(f"اعتمدت وحدة {unit} وأعيد ترتيب صورها.")
            else:
                window.status_label.setText("تعذر اعتماد الوحدة: تحقق من وجود ملف الصورة على القرص.")

        combo.currentIndexChanged.connect(changed)
        apply_btn.clicked.connect(apply)

        panel = getattr(window, "individual_editor_panel", None)
        layout = panel.layout() if panel is not None and hasattr(panel, "layout") else None
        if layout is not None:
            layout.addWidget(box)
            report.update({"installed": True, "panel": "individual_editor_panel"})
        else:
            report["error"] = "لم تُوجد لوحة التحرير الفردي"
            return report

        original_open = getattr(window, "_open_individual_editor", None)
        if callable(original_open):
            def patched_open(*args, **kwargs):
                value = original_open(*args, **kwargs)
                refresh_units()
                return value
            patched_open._unit_choice_patched = True
            window._open_individual_editor = patched_open

        window._refresh_per_image_units = refresh_units
        window._per_image_unit_v33 = True
        refresh_units()
    except Exception as exc:
        report["error"] = str(exc)
    return report
