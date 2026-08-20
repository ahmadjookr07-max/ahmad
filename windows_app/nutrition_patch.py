# -*- coding: utf-8 -*-
"""nutrition_patch — إصلاح نافذة التغذية (م-7 م-18).

## البلاغات
- م-7: «حقائق التغذية بعض الصور تكون بالعرض أو الطول يجب أن يكون
  هناك خيار للضبط بيكون طولي أو عرضي بحيث أستطيع ضبط الميل»
- م-18: «أريد أن تكون الخيارات لحفظ الحقائق الغذائية بنفس الصورة
  الأساسية بدون إضافة صورة جديدة أو استنساخ»

## الإصلاح
1. **اتجاه الاقتصاص**: إضافة زر «تدوير حر» يُدوّر بزاوية دقيقة
   (شريط تمرير ±15°) بدل التدوير 90° فقط — لتصحيح الجداول المائلة.
2. **حفظ فوق نفس الصورة**: إضافة خيار «استبدال الصورة الأصلية» في
   وضع الدمج — يكتب الناتج فوق `output_path` الصنف مباشرةً بلا
   إنشاء صورة جديدة.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = ["install_nutrition_patch", "patch_nutrition_crop_dialog"]


def patch_nutrition_crop_dialog(dialog: Any) -> dict:
    """يُضيف التدوير الدقيق وخيار الاستبدال إلى نافذة التغذية."""
    report: dict[str, Any] = {"fine_rotate": False, "overwrite_mode": False}
    if getattr(dialog, "_nutrition_controls_patched", False):
        return {"fine_rotate": True, "overwrite_mode": True, "already_patched": True}
    dialog._nutrition_controls_patched = True

    # ── 1. التدوير الدقيق ──
    try:
        from PySide6.QtWidgets import (QHBoxLayout, QLabel, QSlider,
                                       QPushButton, QWidget)
        from PySide6.QtCore import Qt

        rotate_widget = QWidget()
        row = QHBoxLayout(rotate_widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("ميل دقيق:"))

        slider = QSlider(Qt.Horizontal)
        slider.setRange(-150, 150)    # ×0.1° ⇒ −15° إلى +15°
        slider.setValue(0)
        slider.setTickInterval(10)
        slider.setFixedWidth(180)
        row.addWidget(slider)

        angle_lbl = QLabel("0.0°")
        angle_lbl.setFixedWidth(42)
        row.addWidget(angle_lbl)

        reset_btn = QPushButton("↺")
        reset_btn.setFixedWidth(28)
        reset_btn.setToolTip("إعادة ضبط الميل")
        row.addWidget(reset_btn)

        def _on_slider(v: int) -> None:
            deg = v / 10.0
            angle_lbl.setText(f"{deg:+.1f}°")
            if hasattr(dialog, "_apply_fine_rotation"):
                dialog._apply_fine_rotation(deg)

        def _reset() -> None:
            slider.setValue(0)

        slider.valueChanged.connect(_on_slider)
        reset_btn.clicked.connect(_reset)

        # أضف الودجت بعد أزرار التدوير الموجودة
        toolbar = getattr(dialog, "toolbar", None) or getattr(
            dialog, "_toolbar", None)
        if toolbar is not None and hasattr(toolbar, "layout"):
            lay = toolbar.layout()
            if lay is not None:
                lay.addWidget(rotate_widget)
                report["fine_rotate"] = True
        else:
            # احتياط: أضفه للتخطيط الرئيسي
            main_lay = dialog.layout()
            if main_lay is not None:
                main_lay.insertWidget(1, rotate_widget)
                report["fine_rotate"] = True

        dialog._fine_rotate_slider = slider
        dialog._fine_rotate_angle = 0.0

        def _apply_fine_rotation(deg: float) -> None:
            """يُدوّر الصورة بزاوية دقيقة حول مركزها."""
            import cv2
            orig = getattr(dialog, "_original_img", None)
            if orig is None:
                orig = getattr(dialog, "_img", None)
                if orig is not None:
                    dialog._original_img = orig.copy()
            if orig is None:
                return
            h, w = orig.shape[:2]
            M = cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1.0)
            rotated = cv2.warpAffine(
                orig, M, (w, h),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REPLICATE,
            )
            dialog._img = rotated
            dialog._fine_rotate_angle = deg
            if hasattr(dialog, "canvas") and hasattr(dialog.canvas, "set_image"):
                dialog.canvas.set_image(rotated)

        dialog._apply_fine_rotation = _apply_fine_rotation
    except Exception as exc:
        report["fine_rotate_error"] = str(exc)

    # ── 2. خيار الاستبدال ──
    try:
        from PySide6.QtWidgets import QCheckBox
        overwrite_cb = QCheckBox("استبدال الصورة الأصلية (بلا نسخة جديدة)")
        overwrite_cb.setToolTip(
            "عند التفعيل يُكتب الناتج فوق صورة الصنف الحالية مباشرةً "
            "بدل إنشاء صورة جديدة في القائمة.")
        # الوضع الافتراضي المقصود: جدول التغذية يصبح جزءًا من الصورة
        # الحالية، فلا ينشأ صف أو ملف مكرر لنفس الصنف.
        overwrite_cb.setChecked(True)

        # أضفه قبل أزرار الحفظ
        btns_widget = getattr(dialog, "buttons_widget", None)
        if btns_widget is not None and hasattr(btns_widget, "layout"):
            lay = btns_widget.layout()
            if lay is not None:
                lay.insertWidget(0, overwrite_cb)
                report["overwrite_mode"] = True
        else:
            main_lay = dialog.layout()
            if main_lay is not None:
                main_lay.addWidget(overwrite_cb)
                report["overwrite_mode"] = True

        dialog._overwrite_cb = overwrite_cb
    except Exception as exc:
        report["overwrite_mode_error"] = str(exc)

    return report


def install_nutrition_patch(window: Any) -> dict:
    """يلفّ `_open_nutrition_crop` فيُركّب الرقعة على كل نافذة تغذية.

    ويلفّ `_save_nutrition_result` فيُطبّق الاستبدال عند طلبه.
    """
    report: dict[str, Any] = {"open_wrapped": False, "save_wrapped": False}

    # ── لفّ الفتح ──
    open_fn = getattr(window, "_open_nutrition_crop", None)
    if callable(open_fn):
        def patched_open(*a: Any, **kw: Any) -> Any:
            out = open_fn(*a, **kw)
            # ابحث عن النافذة المفتوحة حديثًا
            try:
                dlg = getattr(window, "_nutrition_dialog", None)
                if dlg is None:
                    # بعض الإصدارات تحفظها بأسماء مختلفة
                    for attr in ("_nutrition_crop_dlg", "_nutri_dlg",
                                 "nutrition_crop_dialog"):
                        dlg = getattr(window, attr, None)
                        if dlg is not None:
                            break
                if dlg is not None:
                    patch_nutrition_crop_dialog(dlg)
            except Exception:
                pass
            return out

        patched_open._nutrition_patched = True
        try:
            window._open_nutrition_crop = patched_open
            report["open_wrapped"] = True
        except Exception:
            pass

    # ── لفّ الحفظ: دعم الاستبدال ──
    save_fn = getattr(window, "_save_nutrition_result", None)
    if callable(save_fn):
        def patched_save(selected: Any, cropped: Any, on_canvas: bool,
                         product_img: Any = None,
                         placement: Any = None) -> str:
            # هل طلب المالك الاستبدال؟
            try:
                dlg = getattr(window, "_nutrition_dialog", None)
                cb = getattr(dlg, "_overwrite_cb", None)
                if (cb is not None and cb.isChecked()
                        and product_img is not None
                        and placement is not None):
                    # اكتب فوق output_path الصنف مباشرةً
                    out_path = str(getattr(selected, "output_path", "") or "")
                    if out_path:
                        p = window._result_path(out_path) if hasattr(
                            window, "_result_path") else Path(out_path)
                        if p is not None and p.is_file():
                            import cv2
                            from engine_v2.nutrition_v2 import merge_label_inset
                            final = merge_label_inset(product_img, cropped,
                                                      placement)
                            # كتابة ذرية ومتوافقة مع المسارات العربية: نرّمز
                            # أولًا ثم نكتب باسم مؤقت ونستبدله في اللحظة الأخيرة.
                            # بذلك لا تظهر صفحة بيضاء أو ملف مفقود إن انقطع الحفظ.
                            temp = p.with_name(f".{p.stem}.nutrition.tmp{p.suffix}")
                            ext = p.suffix.lower() or ".webp"
                            if ext == ".webp":
                                params = [cv2.IMWRITE_WEBP_QUALITY, 101]
                            elif ext in (".jpg", ".jpeg"):
                                params = [cv2.IMWRITE_JPEG_QUALITY, 100]
                            else:
                                params = [cv2.IMWRITE_PNG_COMPRESSION, 3]
                            ok, encoded = cv2.imencode(ext, final, params)
                            if not ok:
                                raise RuntimeError("تعذر ترميز صورة حقائق التغذية")
                            encoded.tofile(str(temp))
                            temp.replace(p)
                            # امسح معاينات Qt المحتفظ بها وأعد بناء الجدول؛
                            # المسار لم يتغير لكن البكسلات تغيّرت، لذلك لا نُنشئ
                            # عنصرًا جديدًا ولا نسمح للواجهة بعرض النسخة القديمة.
                            try:
                                from PySide6.QtGui import QPixmapCache
                                QPixmapCache.clear()
                                position = window._capture_results_position()
                                window._populate_results(restore_position=position)
                            except Exception:
                                pass
                            # حزمة التسليم قد تكون بُنيت قبل الدمج؛ نعيدها كي
                            # لا يحصل المستخدم على نسخة قديمة من الصورة المعدلة.
                            try:
                                refresh_zip = getattr(window, "_refresh_delivery_zip", None)
                                if callable(refresh_zip):
                                    refresh_zip()
                            except Exception:
                                pass
                            try:
                                saver = getattr(window, "v2_save_session", None)
                                if callable(saver):
                                    saver()
                            except Exception:
                                pass
                            try:
                                window.status_label.setText(
                                    f"تم حفظ حقائق التغذية داخل الصورة نفسها: {p.name}")
                            except Exception:
                                pass
                            return p.name
            except Exception:
                pass
            return save_fn(selected, cropped, on_canvas,
                           product_img=product_img, placement=placement)

        patched_save._nutrition_patched = True
        try:
            window._save_nutrition_result = patched_save
            report["save_wrapped"] = True
        except Exception:
            pass

    return report
