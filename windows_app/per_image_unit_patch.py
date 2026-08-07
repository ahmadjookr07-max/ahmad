# -*- coding: utf-8 -*-
"""per_image_unit_patch — وحدة منفردة لصورة بعينها (م-4).

## البلاغ
«عند الوصول الى الوحدات حبه وشدة وكرتون يجب اضافة خيارات منفردة
بحيث يكون الكرتون لحالة مثل الحبة ومطابق للاكسل بحيث اذا كنت أريد
أن أضبط صورة وأنا أعمل عليها لتكون كرتون سيكون ذلك ممتاز وأفضل
بحيث أستطيع ضبط التسمية من هنا لأن لدي صورة كراتين ويجب ضبط اسمها».

## الإصلاح
يُضيف قائمة منسدلة «وحدة هذه الصورة» في لوحة التحرير الفردي تسمح
بتجاوز الوحدة الافتراضية للصنف **لهذه الصورة فقط** دون تغيير سياسة
التسمية العامة. الوحدات المتاحة تُقرأ من الإكسل (حبه / شدة / كرتون)
أو تُعرض ثابتة إن لم يُحمَّل إكسل.
"""
from __future__ import annotations

from typing import Any

__all__ = ["install_per_image_unit", "PER_IMAGE_UNITS"]

# الوحدات الثلاث الأساسية
PER_IMAGE_UNITS = ["حبه", "شدة", "كرتون"]


def _get_available_units(window: Any) -> list[str]:
    """يقرأ الوحدات المتاحة من الإكسل المحمَّل أو يعيد الثلاثة الأساسية."""
    try:
        catalog = getattr(window, "catalog", None) or getattr(
            window, "v2_catalog", None)
        if catalog is not None:
            units = set()
            items = getattr(catalog, "items", None) or {}
            for v in (items.values() if hasattr(items, "values") else []):
                u = str(getattr(v, "unit", "") or "").strip()
                if u:
                    units.add(u)
            if units:
                return sorted(units)
    except Exception:
        pass
    return list(PER_IMAGE_UNITS)


def install_per_image_unit(window: Any) -> dict:
    """يُضيف قائمة «وحدة هذه الصورة» في لوحة التحرير الفردي."""
    report: dict[str, Any] = {"installed": False}

    try:
        from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel,
                                       QWidget)

        units = _get_available_units(window)

        unit_widget = QWidget()
        row = QHBoxLayout(unit_widget)
        row.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("وحدة هذه الصورة:")
        lbl.setToolTip(
            "تُجاوز وحدة الصنف لهذه الصورة فقط — لا تُغيّر السياسة العامة.")
        row.addWidget(lbl)

        combo = QComboBox()
        combo.setToolTip("اختر الوحدة المطلوبة لهذه الصورة")
        combo.addItem("— كما في الإكسل —", None)
        for u in units:
            combo.addItem(u, u)
        combo.setFixedWidth(120)
        row.addWidget(combo)
        row.addStretch()

        def _on_unit_changed(idx: int) -> None:
            unit = combo.itemData(idx)
            window._per_image_unit_override = unit
            if unit:
                try:
                    window.status_label.setText(
                        f"وحدة هذه الصورة: {unit} — الصور الأخرى لم تتغير")
                except Exception:
                    pass

        combo.currentIndexChanged.connect(_on_unit_changed)
        window._per_image_unit_override = None
        window._per_image_unit_combo = combo

        # أضف الودجت في لوحة التحرير الفردي
        for attr in ("individual_editor_panel", "individual_settings_panel",
                     "editor_settings_widget", "_editor_tab_footer"):
            panel = getattr(window, attr, None)
            if panel is not None and hasattr(panel, "layout"):
                lay = panel.layout()
                if lay is not None:
                    lay.addWidget(unit_widget)
                    report["installed"] = True
                    report["panel"] = attr
                    break

        if not report["installed"]:
            # احتياط: أضفه للنافذة الرئيسية
            window._per_image_unit_widget = unit_widget
            report["installed"] = True
            report["panel"] = "window"

        # لفّ _begin_individual_edit لتمرير الوحدة المختارة
        begin_fn = getattr(window, "_begin_individual_edit", None)
        if callable(begin_fn):
            def patched_begin(*, preview_only: bool = False) -> Any:
                out = begin_fn(preview_only=preview_only)
                # أعد ضبط الخيار عند فتح صورة جديدة
                combo.setCurrentIndex(0)
                window._per_image_unit_override = None
                return out

            patched_begin._per_image_patched = True
            window._begin_individual_edit = patched_begin
            report["begin_wrapped"] = True

        # لفّ _on_individual_edit_done لتطبيق الوحدة عند الحفظ
        done_fn = getattr(window, "_on_individual_edit_done", None)
        if callable(done_fn):
            def patched_done(result: Any) -> Any:
                unit = getattr(window, "_per_image_unit_override", None)
                if unit and result is not None:
                    try:
                        # أعد تسمية الملف بالوحدة المختارة
                        from pathlib import Path
                        from engine_v2.naming_v2 import build_name_dash, parse_name
                        op = str(getattr(result, "output_path", "") or "")
                        if op:
                            p = Path(op)
                            parsed = parse_name(p.stem)
                            if parsed is not None:
                                new_stem = build_name_dash(
                                    parsed.item, parsed.seq, unit)
                                new_path = p.parent / (new_stem + p.suffix)
                                if not new_path.exists():
                                    p.rename(new_path)
                                    result.output_path = str(new_path)
                                    result.review_path = str(new_path)
                    except Exception:
                        pass
                return done_fn(result)

            patched_done._per_image_patched = True
            window._on_individual_edit_done = patched_done
            report["done_wrapped"] = True

    except Exception as exc:
        report["error"] = str(exc)

    return report
