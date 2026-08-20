# -*- coding: utf-8 -*-
"""pipeline_patch — وصل الوحدات الجديدة بكل مسارات المعالجة.

يُركَّب هذا الملف في `native_app_v2.py` بعد بناء الواجهة ليوصل:
- `product_finish_v2.finish_product` بمسار الدفعة (`processor_v2`)
- `straighten_v2.straighten` بمسار الدفعة والتحرير الفردي
- `shape_aware_v2.complete_product` بمسار الصور الجاهزة
- أداة الظل والإكمال للصور المنجزة (م-19 م-22)
- وحدة التقويم التلقائي في الدفعة (م-23)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "src"), str(ROOT / "src" / "engine_v2"),
          str(ROOT / "windows_app")):
    if p not in sys.path:
        sys.path.insert(0, p)

__all__ = ["install_pipeline_patch", "apply_finish_to_image",
           "apply_shadow_to_finished", "apply_completion_to_finished",
           "batch_process_finished"]

# خيار دفعات مشترك، ويكون الظل الخفيف مفعّلًا ابتداءً كما طلب المالك.
_AUTO_SHADOW_AFTER_ISOLATION = True


def _import_finish():
    from engine_v2.product_finish_v2 import finish_product, auto_shadow_opts
    return finish_product, auto_shadow_opts


def _import_straighten():
    from engine_v2.straighten_v2 import straighten, estimate_tilt
    return straighten, estimate_tilt


def _import_shape():
    from engine_v2.shape_aware_v2 import complete_product, mask_from_white
    return complete_product, mask_from_white


# ═══════════════════════ الدوال العامة ═══════════════════════

def apply_finish_to_image(
    img_bgr,
    alpha=None,
    *,
    auto_shadow: bool = True,
    straighten: bool = True,
) -> tuple:
    """يُطبّق التشطيب الكامل على صورة: استرجاع الحواف + اقتصاص + ظل.

    يعيد `(img_bgr, alpha)` المُشطَّبَين.
    """
    try:
        finish_product, auto_shadow_opts = _import_finish()
    except Exception:
        return img_bgr, alpha

    # تقويم اختياري قبل التشطيب
    if straighten and alpha is not None:
        try:
            from engine_v2.straighten_v2 import straighten as _str
            img_bgr, alpha = _str(img_bgr, alpha)
        except Exception:
            pass

    try:
        # finish_product يجهز القناع والاقتصاص؛ تركيب الظل يتم بعده على
        # خلفية بيضاء، كي يكون الظل خفيفًا وواقعًا تحت المنتج لا داخله.
        img_bgr, alpha, _ = finish_product(img_bgr, alpha)
        if auto_shadow and alpha is not None:
            from engine_v2.shadow_v2 import apply_shadow_on_white
            import cv2
            import numpy as np
            shadow_opts = auto_shadow_opts(alpha, subtle=True)
            if shadow_opts.kind != "none":
                rgba = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2BGRA)
                rgba[:, :, 3] = np.clip(alpha, 0, 255).astype(np.uint8)
                img_bgr = apply_shadow_on_white(rgba, shadow_opts)
    except Exception:
        pass
    return img_bgr, alpha


def apply_shadow_to_finished(img_bgr):
    """يُضيف ظلًا لصورة منجزة ذات خلفية بيضاء (م-19).

    يستخرج القناع من الأبيض ثم يُطبّق الظل التلقائي.
    """
    try:
        import numpy as np
        import cv2
        _, mask_from_white = _import_shape()
        mask = mask_from_white(img_bgr)
        alpha = mask.astype(np.float32) / 255.0

        _, auto_shadow_opts = _import_finish()
        shadow_opts = auto_shadow_opts(alpha)
        if shadow_opts is None:
            return img_bgr

        from engine_v2.shadow_v2 import apply_shadow_on_white
        rgba = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2BGRA)
        rgba[:, :, 3] = (alpha * 255).astype(np.uint8)
        result = apply_shadow_on_white(rgba, shadow_opts)
        return result
    except Exception:
        return img_bgr


def apply_completion_to_finished(img_bgr):
    """يُكمل المنتجات الناقصة في صورة منجزة (م-21 م-22).

    يستخرج القناع من الأبيض ثم يُطبّق الإكمال الذكي.
    """
    try:
        import numpy as np
        complete_product, mask_from_white = _import_shape()
        mask = mask_from_white(img_bgr)
        result_mask, _ = complete_product(img_bgr, mask)
        # يُعيد الصورة بالقناع المُكمَّل على خلفية بيضاء
        alpha = (result_mask > 0).astype(np.float32)
        white = np.full_like(img_bgr, 255)
        out = (img_bgr.astype(np.float32) * alpha[:, :, None]
               + white.astype(np.float32) * (1 - alpha[:, :, None]))
        return np.clip(out, 0, 255).astype(np.uint8)
    except Exception:
        return img_bgr


def batch_process_finished(
    folder: str | Path,
    *,
    add_shadow: bool = True,
    complete: bool = False,
    progress_cb=None,
) -> dict:
    """يُعالج دفعيًا كل صور WebP في مجلد المنجزات (م-22).

    - `add_shadow`: يُضيف ظلًا لمن ليس لديه ظل
    - `complete`: يُكمل المنتجات الناقصة
    - `progress_cb(done, total)`: استدعاء اختياري للتقدم

    يعيد `{"processed": n, "skipped": m, "errors": [...]}`.
    """
    import cv2
    folder = Path(folder)
    files = sorted(folder.glob("*.webp")) + sorted(folder.glob("*.png"))
    result = {"processed": 0, "skipped": 0, "errors": []}
    total = len(files)

    for i, f in enumerate(files):
        if progress_cb is not None:
            try:
                progress_cb(i, total)
            except Exception:
                pass
        try:
            img = cv2.imread(str(f), cv2.IMREAD_COLOR)
            if img is None:
                result["skipped"] += 1
                continue
            changed = False
            if add_shadow:
                out = apply_shadow_to_finished(img)
                if out is not img:
                    img = out
                    changed = True
            if complete:
                out = apply_completion_to_finished(img)
                if out is not img:
                    img = out
                    changed = True
            if changed:
                cv2.imwrite(str(f), img, [cv2.IMWRITE_WEBP_QUALITY, 90])
                result["processed"] += 1
            else:
                result["skipped"] += 1
        except Exception as exc:
            result["errors"].append(f"{f.name}: {exc}")

    if progress_cb is not None:
        try:
            progress_cb(total, total)
        except Exception:
            pass
    return result


# ═══════════════════════ التركيب على processor_v2 ═══════════════════════

def _patch_processor() -> bool:
    """يُضيف التشطيب والتقويم إلى `processor_v2.ProcessorV2.process`."""
    try:
        from engine_v2 import processor_v2 as pv2
        if getattr(pv2.ProcessorV2.process, "_pipeline_patched", False):
            return True
        orig_process = pv2.ProcessorV2.process

        def patched_process(self, source_path, output_path, opts=None):
            # نُشغّل الخط الأصلي أولًا
            res = orig_process(self, source_path, output_path, opts)
            # ثم نُطبّق التشطيب على الناتج إن نجح
            try:
                if res is not None and _AUTO_SHADOW_AFTER_ISOLATION:
                    out = Path(output_path)
                    if out.is_file():
                        import cv2
                        import numpy as np
                        img = cv2.imread(str(out), cv2.IMREAD_COLOR)
                        if img is not None:
                            # نستخرج القناع من الخلفية البيضاء ونضيف ظل تلامس خفيف.
                            from engine_v2.shape_aware_v2 import mask_from_white
                            mask = mask_from_white(img)
                            alpha = mask.astype(np.float32) * 255.0
                            img2, _ = apply_finish_to_image(
                                img, alpha,
                                auto_shadow=True,
                                straighten=False,  # التقويم يحدث قبل العزل
                            )
                            cv2.imwrite(str(out), img2,
                                        [cv2.IMWRITE_WEBP_QUALITY, 90])
            except Exception:
                pass
            return res

        patched_process._pipeline_patched = True
        pv2.ProcessorV2.process = patched_process
        return True
    except Exception:
        return False


# ═══════════════════════ التركيب على الواجهة ═══════════════════════

def install_pipeline_patch(window: Any) -> dict:
    """يركّب كل الوحدات الجديدة على الواجهة ومسار الدفعة."""
    report: dict[str, Any] = {
        "processor_patched": False,
        "batch_tool_installed": False,
        "all_patches": [],
    }

    # ── وصل الدفعة ──
    report["processor_patched"] = _patch_processor()
    if report["processor_patched"]:
        report["all_patches"].append("processor_v2")

    # ── خيار الظل التلقائي للدفعة الجديدة: مفعّل افتراضيًا ──
    try:
        _install_auto_shadow_option(window)
        report["auto_shadow_option_installed"] = True
        report["all_patches"].append("auto_shadow_after_isolation")
    except Exception as exc:
        report["auto_shadow_option_error"] = str(exc)

    # ── تقريب المنتج اليدوي وحفظ موضعه على الصورة المحددة ──
    try:
        _install_product_framing_controls(window)
        report["product_framing_installed"] = True
        report["all_patches"].append("product_framing")
    except Exception as exc:
        report["product_framing_error"] = str(exc)

    # ── أداة الصور المنجزة في الواجهة ──
    try:
        _install_finished_tool(window)
        report["batch_tool_installed"] = True
        report["all_patches"].append("finished_tool")
    except Exception as exc:
        report["batch_tool_error"] = str(exc)

    # ── رقع الحماية والجلسات والمحرر ──
    for mod_name, install_fn_name in (
        ("windows_app.work_guard", "install_work_guard"),
        ("windows_app.session_fidelity_patch", "install_session_fidelity"),
        ("windows_app.editor_sync_patch", "install_editor_sync"),
        ("windows_app.editor_memory_patch", "install_memory_patch"),
    ):
        try:
            import importlib
            mod = importlib.import_module(mod_name)
            fn = getattr(mod, install_fn_name)
            if install_fn_name == "install_memory_patch":
                # تُركَّب على لوحة المحرر لا على النافذة
                editor = (getattr(window, "unified_editor", None)
                          or window.__dict__.get("_unified_editor_instance"))
                if editor is not None:
                    canvas = getattr(editor, "canvas", None)
                    if canvas is not None:
                        fn(canvas)
                        report["all_patches"].append(mod_name)
            else:
                fn(window)
                report["all_patches"].append(mod_name)
        except Exception as exc:
            report[f"{mod_name}_error"] = str(exc)

    return report


def _install_auto_shadow_option(window: Any) -> None:
    """يضيف مفتاحًا واضحًا للظل الخفيف في كل معالجة جديدة.

    القيمة الافتراضية مفعّلة؛ عند إلغائها لا يُمس الظل اليدوي في المحرر.
    """
    from PySide6.QtWidgets import QCheckBox

    toggle = QCheckBox("ظل تلقائي خفيف بعد عزل الخلفية")
    toggle.setObjectName("autoShadowAfterIsolation")
    toggle.setToolTip("يضيف ظل تلامس خفيفًا تلقائيًا لكل صورة تعزلها الدفعة")
    toggle.setChecked(True)

    def _apply(enabled: bool) -> None:
        global _AUTO_SHADOW_AFTER_ISOLATION
        _AUTO_SHADOW_AFTER_ISOLATION = bool(enabled)
        setattr(window, "auto_shadow_after_isolation", bool(enabled))
        # ProcessorV2 قد يُنشأ لاحقًا؛ نخزن التفضيل على النافذة أيضًا.
        try:
            processor = getattr(window, "processor", None)
            if processor is not None:
                processor.auto_shadow_after_isolation = bool(enabled)
        except Exception:
            pass

    _apply(True)
    toggle.toggled.connect(_apply)
    for attr in ("setup_panel", "options_panel", "controls_panel", "tools_panel"):
        panel = getattr(window, attr, None)
        if panel is not None and hasattr(panel, "layout") and panel.layout() is not None:
            panel.layout().addWidget(toggle)
            window._auto_shadow_after_isolation_cb = toggle
            return
    # الحاوية الفعلية في النافذة الأساسية: «3. تحسين المنتج والإخراج».
    try:
        from PySide6.QtWidgets import QGroupBox
        panel = window.findChild(QGroupBox, "enhancementGroup")
        if panel is not None and panel.layout() is not None:
            panel.layout().addWidget(toggle)
            window._auto_shadow_after_isolation_cb = toggle
            return
    except Exception:
        pass
    # الاحتفاظ بالمفتاح حتى لو اختلف تخطيط إصدار قديم من الواجهة.
    window._auto_shadow_after_isolation_cb = toggle


def _install_product_framing_controls(window: Any) -> None:
    """واجهة تقريب وحفظ موضع المنتج؛ الكتابة فوق نفس الملف فقط."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmapCache
    from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QPushButton,
                                   QSlider, QSpinBox, QVBoxLayout, QWidget)

    group = window.findChild(QGroupBox, "enhancementGroup")
    if group is None or group.layout() is None:
        return
    host = QWidget(group)
    host.setObjectName("productFramingControls")
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 4, 0, 0)
    layout.setSpacing(4)
    title = QLabel("تقريب وتمركز المنتج بعد العزل")
    title.setToolTip("يتم تمركز المنتج تلقائيًا في الدفعات؛ هذه الأدوات لتعديل الصورة المحددة وحفظها.")
    layout.addWidget(title)

    zoom_row = QHBoxLayout()
    zoom_row.addWidget(QLabel("التقريب:"))
    zoom = QSlider(Qt.Horizontal)
    zoom.setObjectName("productZoomPercent")
    zoom.setLayoutDirection(Qt.LeftToRight)
    zoom.setRange(100, 130)
    zoom.setValue(106)
    zoom.setSingleStep(1)
    value = QLabel("106%")
    value.setMinimumWidth(42)
    zoom.valueChanged.connect(lambda v: value.setText(f"{v}%"))
    zoom_row.addWidget(zoom, 1)
    zoom_row.addWidget(value)
    layout.addLayout(zoom_row)

    move_row = QHBoxLayout()
    move_row.addWidget(QLabel("الموضع:"))
    offset_x = QSpinBox(); offset_x.setRange(-20, 20); offset_x.setSuffix("% أفقي")
    offset_y = QSpinBox(); offset_y.setRange(-20, 20); offset_y.setSuffix("% رأسي")
    offset_x.setToolTip("قيمة موجبة = يمين، سالبة = يسار")
    offset_y.setToolTip("قيمة موجبة = أسفل، سالبة = أعلى")
    move_row.addWidget(offset_x)
    move_row.addWidget(offset_y)
    reset = QPushButton("توسيط")
    reset.setToolTip("يعيد المنتج إلى الوسط مع تقريب تلقائي خفيف")
    reset.clicked.connect(lambda: (zoom.setValue(106), offset_x.setValue(0), offset_y.setValue(0)))
    move_row.addWidget(reset)
    layout.addLayout(move_row)

    apply_btn = QPushButton("تطبيق وحفظ التقريب للصورة المحددة")
    apply_btn.setObjectName("saveProductFraming")
    apply_btn.setToolTip("يحفظ التقريب والموضع فوق نفس صورة الصنف بلا إنشاء ملف أو صف جديد")
    layout.addWidget(apply_btn)

    settings = getattr(window, "_product_frame_settings", None)
    if not isinstance(settings, dict):
        settings = {}
        window._product_frame_settings = settings

    def _selected():
        fn = getattr(window, "_selected_result_item", None)
        return fn() if callable(fn) else None

    def _key(item) -> str:
        return str(getattr(item, "output_path", "") or getattr(item, "source_name", ""))

    def _load_selected() -> None:
        item = _selected()
        data = settings.get(_key(item), {}) if item is not None else {}
        zoom.blockSignals(True); offset_x.blockSignals(True); offset_y.blockSignals(True)
        try:
            zoom.setValue(int(data.get("zoom_percent", 106)))
            offset_x.setValue(int(data.get("offset_x_percent", 0)))
            offset_y.setValue(int(data.get("offset_y_percent", 0)))
        finally:
            zoom.blockSignals(False); offset_x.blockSignals(False); offset_y.blockSignals(False)
        value.setText(f"{zoom.value()}%")

    def _save_current() -> None:
        item = _selected()
        if item is None:
            try:
                window.status_label.setText("حدد صورة من النتائج أولًا لتطبيق التقريب.")
            except Exception:
                pass
            return
        out_value = str(getattr(item, "output_path", "") or "")
        path = window._result_path(out_value) if out_value and hasattr(window, "_result_path") else Path(out_value)
        if not out_value or path is None or not Path(path).is_file():
            try:
                window.status_label.setText("لا توجد صورة ناتجة صالحة لحفظ التقريب عليها.")
            except Exception:
                pass
            return
        from framing_zoom_patch import ProductFrame, save_framed_image
        frame = ProductFrame(zoom.value(), offset_x.value(), offset_y.value()).normalized()
        if not save_framed_image(path, frame):
            try:
                window.status_label.setText("تعذر حفظ التقريب؛ بقيت الصورة الأصلية دون تغيير.")
            except Exception:
                pass
            return
        settings[_key(item)] = {
            "zoom_percent": frame.zoom_percent,
            "offset_x_percent": frame.offset_x_percent,
            "offset_y_percent": frame.offset_y_percent,
        }
        try:
            QPixmapCache.clear()
            position = window._capture_results_position()
            window._populate_results(restore_position=position)
            saver = getattr(window, "v2_save_session", None)
            if callable(saver):
                saver()
        except Exception:
            pass
        try:
            window.status_label.setText(
                f"حُفظ التقريب {frame.zoom_percent}% وموضعه داخل الصورة نفسها: {Path(path).name}")
        except Exception:
            pass

    apply_btn.clicked.connect(_save_current)
    table = getattr(window, "results_table", None)
    if table is not None and hasattr(table, "itemSelectionChanged"):
        table.itemSelectionChanged.connect(_load_selected)
    group.layout().addWidget(host)
    window._product_framing_controls = host
    window._product_zoom_slider = zoom
    window._product_offset_x = offset_x
    window._product_offset_y = offset_y
    window._save_product_framing = _save_current


def _install_finished_tool(window: Any) -> None:
    """يُضيف زر «معالجة الصور المنجزة» إلى لوحة الإعداد."""
    try:
        from PySide6.QtWidgets import (QPushButton, QProgressDialog,
                                       QFileDialog, QCheckBox,
                                       QVBoxLayout, QDialog, QLabel,
                                       QDialogButtonBox)
        from PySide6.QtCore import Qt

        def _open_finished_tool():
            folder = QFileDialog.getExistingDirectory(
                window, "اختر مجلد الصور المنجزة")
            if not folder:
                return

            dlg = QDialog(window)
            dlg.setWindowTitle("معالجة الصور المنجزة")
            dlg.setMinimumWidth(380)
            layout = QVBoxLayout(dlg)
            layout.addWidget(QLabel(
                f"المجلد: {Path(folder).name}\n"
                f"الصور: {len(list(Path(folder).glob('*.webp')))} WebP"))
            shadow_cb = QCheckBox("إضافة ظل تلقائي للصور بلا ظل")
            shadow_cb.setChecked(True)
            complete_cb = QCheckBox("إكمال المنتجات الناقصة (حواف وفراغات)")
            complete_cb.setChecked(False)
            layout.addWidget(shadow_cb)
            layout.addWidget(complete_cb)
            btns = QDialogButtonBox(
                QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            btns.accepted.connect(dlg.accept)
            btns.rejected.connect(dlg.reject)
            layout.addWidget(btns)
            if dlg.exec() != QDialog.Accepted:
                return

            prog = QProgressDialog("جارٍ المعالجة…", "إلغاء", 0, 100, window)
            prog.setWindowModality(Qt.WindowModal)
            prog.show()

            def _cb(done: int, total: int) -> None:
                if total > 0:
                    prog.setValue(int(done / total * 100))
                from PySide6.QtWidgets import QApplication
                QApplication.processEvents()

            res = batch_process_finished(
                folder,
                add_shadow=shadow_cb.isChecked(),
                complete=complete_cb.isChecked(),
                progress_cb=_cb,
            )
            prog.close()
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                window, "اكتملت المعالجة",
                f"مُعالَجة: {res['processed']}\n"
                f"مُتخطّاة: {res['skipped']}\n"
                f"أخطاء: {len(res['errors'])}"
                + (f"\n\n{chr(10).join(res['errors'][:5])}"
                   if res["errors"] else ""),
            )

        # أضف الزر إلى شريط الإجراءات أو لوحة الإعداد
        btn = QPushButton("🖼 معالجة الصور المنجزة")
        btn.setToolTip("إضافة ظل وإكمال المنتجات الناقصة للصور الجاهزة")
        btn.clicked.connect(_open_finished_tool)

        for attr in ("results_action_bar", "setup_panel",
                     "delivery_panel", "tools_panel"):
            panel = getattr(window, attr, None)
            if panel is not None and hasattr(panel, "layout"):
                lay = panel.layout()
                if lay is not None:
                    lay.addWidget(btn)
                    window._finished_tool_btn = btn
                    return

        # احتياط: أضفه للنافذة الرئيسية
        window._finished_tool_btn = btn
    except Exception:
        pass
