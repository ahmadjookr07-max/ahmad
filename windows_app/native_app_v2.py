# -*- coding: utf-8 -*-
"""Ahmed Al-Faifi Market Image Studio — V2.0.0 launcher.

Non-invasive wrapper around the proven 1.2.1 ``native_app``:
it wires the V2 engine (high-precision cutout, auto-enhancement,
unified naming, nutrition-facts suite, instant Excel index, sessions)
and the V2 UI additions, then launches the app as version 2.0.0.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
for p in (str(_SRC), str(_HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

APP_VERSION_V2 = "2.0.0"


def _activate_engine() -> None:
    """Route final image production through ProcessorV2 (safe fallback)."""
    try:
        from engine_v2.integration_v2 import activate
        activate()
    except Exception as exc:  # pragma: no cover — never block startup
        print(f"[V2] engine activation failed, falling back to legacy: {exc}",
              file=sys.stderr)


def _patch_ui(native_app) -> None:
    """Extend MainWindow with V2 buttons/dialogs after it is constructed."""
    from PySide6.QtWidgets import QPushButton, QDialog

    import v2_ui

    original_init = native_app.MainWindow.__init__

    def v2_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        try:
            data_root = getattr(native_app, "DATA_ROOT", Path.home() / "Documents" / "SmartCatalogVision")
            v2_ui.install_v2(self, Path(data_root))
            header_layout = self.header_frame.layout()

            rename_btn = QPushButton("أداة إعادة التسمية")
            rename_btn.setObjectName("v2RenameBtn")
            rename_btn.setMinimumHeight(40)
            rename_btn.setCursor(native_app.Qt.PointingHandCursor)
            rename_btn.clicked.connect(self.v2_open_rename_tool)

            sessions_btn = QPushButton("الجلسات")
            sessions_btn.setObjectName("v2SessionsBtn")
            sessions_btn.setMinimumHeight(40)
            sessions_btn.setCursor(native_app.Qt.PointingHandCursor)
            sessions_btn.clicked.connect(self.v2_open_sessions)

            naming_btn = QPushButton("سياسة التسمية")
            naming_btn.setObjectName("v2NamingBtn")
            naming_btn.setMinimumHeight(40)
            naming_btn.setCursor(native_app.Qt.PointingHandCursor)
            naming_btn.clicked.connect(self.v2_open_unit_naming)

            editor_btn = QPushButton("محرر الصور")
            editor_btn.setObjectName("v2EditorBtn")
            editor_btn.setMinimumHeight(40)
            editor_btn.setCursor(native_app.Qt.PointingHandCursor)
            editor_btn.clicked.connect(lambda: _open_photo_editor(self))

            refine_btn = QPushButton("ضبط الصور القديمة")
            refine_btn.setObjectName("v2RefineBtn")
            refine_btn.setMinimumHeight(40)
            refine_btn.setCursor(native_app.Qt.PointingHandCursor)
            refine_btn.clicked.connect(lambda: _open_batch_refine(self))

            # insert before the version badge (last widget)
            insert_at = max(header_layout.count() - 1, 0)
            header_layout.insertWidget(insert_at, rename_btn)
            header_layout.insertWidget(insert_at, sessions_btn)
            header_layout.insertWidget(insert_at, naming_btn)
            header_layout.insertWidget(insert_at, editor_btn)
            header_layout.insertWidget(insert_at, refine_btn)

            # شارة الاشتراك + زر لوحة المالك
            try:
                import license_ui
                license_ui.install_license_badge(self)
            except Exception as exc:
                print(f"[V2] license badge failed: {exc}", file=sys.stderr)

            self.v2_nutrition_dialog_cls = v2_ui.NutritionDialog
            _attach_nutrition_button(self, native_app, v2_ui)
        except Exception as exc:  # pragma: no cover
            print(f"[V2] UI wiring failed: {exc}", file=sys.stderr)

    native_app.MainWindow.__init__ = v2_init


def _attach_nutrition_button(window, native_app, v2_ui) -> None:
    """Add a nutrition-facts button into the results-page manual group."""
    from PySide6.QtWidgets import QPushButton, QDialog, QMessageBox

    from PySide6.QtWidgets import QSizePolicy

    btn = QPushButton("حقائق التغذية")
    btn.setObjectName("v2NutritionBtn")
    btn.setMinimumHeight(36)
    btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    # place inside the manual_controls row (beside "ربط الآن") — the
    # quick_controls row already holds 5 widgets and gets cramped
    group = getattr(window, "manual_group", None)
    anchor = getattr(window, "manual_link_button", None)
    target_layout = None
    if group is not None and anchor is not None:
        layout = group.layout()
        for i in range(layout.count()):
            item = layout.itemAt(i)
            sub = item.layout()
            if sub is not None and sub.indexOf(anchor) >= 0:
                target_layout = sub
                break
    if target_layout is None:
        return

    def open_nutrition():
        source = _current_source_path(window)
        if not source:
            QMessageBox.information(window, "حقائق التغذية",
                                    "اختر صورة من قائمة النتائج أولًا.")
            return
        item_no = _current_item_number(window)
        dlg = v2_ui.NutritionDialog(source, item_no, parent=window)
        if dlg.exec() == QDialog.Accepted:
            settings = dlg.result_settings
            try:
                from engine_v2.integration_v2 import set_override
                set_override(source, settings)
                window.status_label.setText(
                    "تم اعتماد إعدادات حقائق التغذية — ستُطبق عند الحفظ التالي لهذه الصورة.")
            except Exception as exc:
                QMessageBox.warning(window, "خطأ", str(exc))

    btn.clicked.connect(open_nutrition)
    target_layout.insertWidget(target_layout.indexOf(anchor) + 1, btn)


def _open_photo_editor(window) -> None:
    """يفتح محرر الصور الاحترافي على الصورة المحددة أو صورة خارجية."""
    try:
        from photo_editor_v2 import V2PhotoEditorDialog
        source = _current_source_path(window)
        dlg = V2PhotoEditorDialog(source, parent=window)
        dlg.exec()
    except Exception as exc:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(window, "محرر الصور", f"تعذر فتح المحرر: {exc}")


def _open_batch_refine(window) -> None:
    """يفتح أداة الضبط التلقائي الجماعي للصور القديمة."""
    try:
        import v2_ui
        dlg = v2_ui.BatchRefineDialog(parent=window)
        dlg.exec()
    except Exception as exc:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(window, "ضبط الصور القديمة", f"تعذر فتح الأداة: {exc}")


def _current_source_path(window) -> str:
    for attr in ("current_source_path", "_current_source_path"):
        value = getattr(window, attr, None)
        if value:
            return str(value)
    result = getattr(window, "current_result", None)
    if result is not None:
        for attr in ("source_path", "image_path", "path"):
            value = getattr(result, attr, None)
            if value:
                return str(value)
    return ""


def _current_item_number(window) -> str:
    result = getattr(window, "current_result", None)
    if result is not None:
        for attr in ("item_number", "item_code", "code"):
            value = getattr(result, attr, None)
            if value:
                return str(value)
    return ""


def _gate_startup(native_app) -> None:
    """بوابة الترخيص الإلزامية قبل إظهار النافذة الرئيسية.

    تُطبّق داخل MainWindow.__init__ — إن لم تتحقق الموافقة على الاتفاقية
    والترخيص الصالح، يُغلق التطبيق فورًا (لا طريق لتجاوزها).
    """
    original_init = native_app.MainWindow.__init__

    def gated_init(self, *args, **kwargs):
        import license_ui
        if not license_ui.ensure_activated(None):
            raise SystemExit(0)
        original_init(self, *args, **kwargs)

    native_app.MainWindow.__init__ = gated_init


def main() -> int:
    _activate_engine()
    import native_app
    native_app.APP_VERSION = APP_VERSION_V2
    _gate_startup(native_app)   # أولاً: بوابة الترخيص (تلتف حول __init__ الأصلي)
    _patch_ui(native_app)       # ثانيًا: إضافات الواجهة (تلتف حول gated_init)
    return native_app.main()


if __name__ == "__main__":
    raise SystemExit(main())
