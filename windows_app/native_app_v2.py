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

APP_VERSION_V2 = "2.1.0"

_SPLASH = None  # مرجع شاشة البدء الفورية


def _show_splash() -> None:
    """شاشة بدء فورية تظهر خلال أجزاء من الثانية — يرى المستخدم
    اسم البرنامج مباشرة بدل شاشة سوداء/انتظار طويل بلا أي مؤشر."""
    global _SPLASH
    try:
        from PySide6.QtWidgets import QApplication, QSplashScreen
        from PySide6.QtGui import QPixmap, QPainter, QColor, QFont
        from PySide6.QtCore import Qt
        app = QApplication.instance() or QApplication(sys.argv)
        pix = QPixmap(520, 300)
        pix.fill(QColor("#12203a"))
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor("#ffffff"))
        f = QFont();  f.setPointSize(20);  f.setBold(True)
        p.setFont(f)
        p.drawText(pix.rect().adjusted(0, -30, 0, -30), Qt.AlignCenter,
                   "استوديو صور المتجر")
        f2 = QFont();  f2.setPointSize(11)
        p.setPen(QColor("#9fb6dc"))
        p.setFont(f2)
        p.drawText(pix.rect().adjusted(0, 40, 0, 40), Qt.AlignCenter,
                   f"Ahmed Al-Faifi Market Image Studio — {APP_VERSION_V2}\n"
                   "جارٍ التحميل… لحظات من فضلك")
        p.end()
        _SPLASH = QSplashScreen(pix, Qt.WindowStaysOnTopHint)
        _SPLASH.show()
        app.processEvents()
    except Exception:
        _SPLASH = None


def _close_splash(window=None) -> None:
    global _SPLASH
    try:
        if _SPLASH is not None:
            if window is not None:
                _SPLASH.finish(window)
            else:
                _SPLASH.close()
    except Exception:
        pass
    _SPLASH = None


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

            save_now_btn = QPushButton("حفظ الجلسة الآن")
            save_now_btn.setObjectName("v2SaveNowBtn")
            save_now_btn.setMinimumHeight(40)
            save_now_btn.setCursor(native_app.Qt.PointingHandCursor)

            def _save_now():
                try:
                    saver = getattr(self, "v2_save_session", None)
                    if callable(saver) and getattr(self, "current_result", None) is not None:
                        saver()
                        from PySide6.QtWidgets import QMessageBox
                        QMessageBox.information(
                            self, "تم الحفظ",
                            "حُفظت الجلسة بنجاح — يمكنك استئنافها من زر (الجلسات)")
                    else:
                        from PySide6.QtWidgets import QMessageBox
                        QMessageBox.information(
                            self, "لا يوجد عمل مفتوح",
                            "لا توجد نتائج مفتوحة لحفظها حاليًا")
                except Exception as exc:
                    print(f"[V2] save now failed: {exc}", file=sys.stderr)

            save_now_btn.clicked.connect(_save_now)

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

            help_btn = QPushButton("؟ تعليمات")
            help_btn.setObjectName("v2HelpBtn")
            help_btn.setMinimumHeight(40)
            help_btn.setCursor(native_app.Qt.PointingHandCursor)
            help_btn.setToolTip("دليل استخدام مختصر لكل أدوات البرنامج")
            help_btn.clicked.connect(lambda: _show_app_help(self))

            # insert before the version badge (last widget)
            insert_at = max(header_layout.count() - 1, 0)
            header_layout.insertWidget(insert_at, help_btn)
            header_layout.insertWidget(insert_at, rename_btn)
            header_layout.insertWidget(insert_at, save_now_btn)
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

    # ------------------------------------------------ حفظ عند الإغلاق
    original_close = getattr(native_app.MainWindow, "closeEvent", None)

    def v2_close_event(self, event):
        """عند الإغلاق مع عمل مفتوح: حفظ / إغلاق بلا حفظ / إلغاء."""
        try:
            from PySide6.QtWidgets import QMessageBox
            has_work = getattr(self, "current_result", None) is not None
            saver = getattr(self, "v2_save_session", None)
            if has_work and callable(saver):
                box = QMessageBox(self)
                box.setWindowTitle("حفظ العمل قبل الإغلاق")
                box.setText("لديك عمل مفتوح — ماذا تريد؟")
                box.setInformativeText(
                    "حفظ الجلسة يتيح لك استئناف العمل من نفس النقطة"
                    " عند فتح البرنامج مرة أخرى (زر الجلسات).")
                save_btn = box.addButton("حفظ الجلسة والإغلاق",
                                         QMessageBox.AcceptRole)
                discard_btn = box.addButton("إغلاق بدون حفظ",
                                            QMessageBox.DestructiveRole)
                cancel_btn = box.addButton("إلغاء والبقاء",
                                           QMessageBox.RejectRole)
                box.setDefaultButton(save_btn)
                box.setLayoutDirection(native_app.Qt.RightToLeft)
                box.exec()
                clicked = box.clickedButton()
                if clicked is cancel_btn:
                    event.ignore()
                    return
                if clicked is save_btn:
                    try:
                        saver()
                    except Exception as exc:
                        print(f"[V2] save on close failed: {exc}",
                              file=sys.stderr)
        except Exception as exc:  # pragma: no cover — never block closing
            print(f"[V2] close handler failed: {exc}", file=sys.stderr)
        if callable(original_close):
            original_close(self, event)
        else:
            event.accept()

    native_app.MainWindow.closeEvent = v2_close_event


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


def _show_app_help(window) -> None:
    """دليل استخدام مختصر داخل البرنامج — بالعربي الواضح."""
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel,
                                       QScrollArea, QVBoxLayout, QWidget,
                                       QPushButton, QMessageBox)

        dlg = QDialog(window)
        dlg.setWindowTitle("تعليمات الاستخدام")
        dlg.setLayoutDirection(Qt.RightToLeft)
        dlg.resize(640, 700)
        lay = QVBoxLayout(dlg)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body_lay = QVBoxLayout(body)

        text = QLabel(
            "<h2>خطوات العمل الأساسية</h2>"
            "<ol>"
            "<li><b>إضافة مجلد:</b> اختر مجلد صور المنتجات وملف Excel للأصناف، ثم ابدأ المعالجة — البرنامج يعزل الخلفية ويقرأ الباركود ويربط ويسمي تلقائيًا.</li>"
            "<li><b>المراجعة والربط:</b> المصغرات بخلفية بيضاء = مربوطة وجاهزة. للصور غير المرتبطة: اكتب الرقم ثم (ربط الآن)، أو استخدم (ربط بصورة أخرى) لاختيار أي صورة مرتبطة — ولو بعيدة — وربط المحدد بصنفها.</li>"
            "<li><b>محرر الصور:</b> تحرير احترافي كامل — قص ذكي، فرشاة تبييض/استرجاع، توزين دقيق 0.1° مع شبكة، إزالة انعكاسات التصوير، تنقيح استوديو، وظل أسفل المنتج اختياري. جديد: زر (طمس التواريخ تلقائيًا) يكشف تواريخ الإنتاج/الانتهاء ويطمسها بتمويه طفيف بلون المنتج، وأداة (طمس تاريخ يدوي) للسحب فوق أي تاريخ لم يُكشف.</li>"
            "<li><b>وضوح فائق للكتابات:</b> محرك جودة ذكي يتعرف على نصوص المنتج والحقائق الغذائية ويحافظ على مقروئيتها التامة في كل مراحل المعالجة — مفعّل افتراضيًا مع جودة (فائقة — بلا فقدان).</li>"
            "<li><b>ضبط الصور القديمة:</b> يعالج مجلدات كاملة دفعة واحدة دون تكرار — المعالَج سابقًا يُتخطى تلقائيًا، مع خيار الضغط والصيغة (WebP/JPG/PNG) والتنقيح النهائي.</li>"
            "<li><b>أداة إعادة التسمية:</b> ثلاثة تبويبات — إصلاح الأسماء والتكرارات، تنظيف حسب رقم اللقطة/الوحدة (احتفاظ أو حذف مع معاينة)، وتصدير بتنسيقات المنصات (نون، أمازون، سلة، زد، شوبيفاي، قالب يدوي حر).</li>"
            "<li><b>سياسة التسمية:</b> تحكم بأسماء الوحدات (حبة/ربطة/شدة/كرتون) بالعربي وحتى 10 صور لكل صنف بترقيم موحد مطابق للإكسل.</li>"
            "<li><b>حقائق التغذية:</b> استخراج ذكي من صورة المنتج — أي قيمة غير مؤكدة تُظلل للمراجعة ولن يخترع البرنامج أي رقم. إن فشل الاستخراج أدخل القيم يدويًا والتنسيق الاحترافي تلقائي. ضع الجدول داخل الصورة بالسحب أو أخرجه صورة منفردة.</li>"
            "<li><b>الجلسات:</b> عملك يُحفظ تلقائيًا، وعند الإغلاق تختار: حفظ وإغلاق / إغلاق بلا حفظ / البقاء. استأنف من زر (الجلسات).</li>"
            "</ol>"
            "<h2>التطبيق يتعلم منك</h2>"
            "<p>كل تعديل تقوم به (حجم الفرشاة، قوة التحسين، مواضع جدول التغذية، تصحيحات القص) يُحفظ كتفضيل محلي ويُقترح تلقائيًا للصور المشابهة — كلما استخدمت البرنامج أصبح أذكى وأسرع لعملك.</p>"
            "<p><b>خصوصية كاملة:</b> التعلم محلي 100% داخل جهازك — لا يُرسل أي شيء للخارج.</p>"
            "<h2>الاشتراك والتجربة</h2>"
            "<p>عند أول تشغيل تحصل على تجربة مجانية كاملة الميزات لمدة 3 أيام — الشارة أعلى الشاشة تعرض المدة المتبقية بدقة. للتفعيل الدائم أو الاشتراك تواصل مع المالك للحصول على مفتاح التفعيل.</p>"
        )
        text.setWordWrap(True)
        text.setTextFormat(Qt.RichText)
        body_lay.addWidget(text)

        reset_btn = QPushButton("عرض / إعادة ضبط ما تعلمه التطبيق")
        reset_btn.setMinimumHeight(38)

        def _learning_info():
            try:
                import engine_v2.learning_v2 as lv
                summary = lv.summary_ar()
                box = QMessageBox(window)
                box.setLayoutDirection(Qt.RightToLeft)
                box.setWindowTitle("ما تعلمه التطبيق")
                box.setText(summary or "لم يتعلم التطبيق شيئًا بعد — ابدأ بالتعديل وسيتعلم منك.")
                reset = box.addButton("إعادة الضبط", QMessageBox.DestructiveRole)
                box.addButton("إغلاق", QMessageBox.RejectRole)
                box.exec()
                if box.clickedButton() is reset:
                    lv.reset()
                    QMessageBox.information(window, "تم", "أُعيد ضبط التعلم بالكامل.")
            except Exception as exc:
                QMessageBox.information(window, "التعلم", f"تعذر الوصول لبيانات التعلم: {exc}")

        reset_btn.clicked.connect(_learning_info)
        body_lay.addWidget(reset_btn)
        body_lay.addStretch(1)

        scroll.setWidget(body)
        lay.addWidget(scroll, 1)
        buttons = QDialogButtonBox()
        close_btn = buttons.addButton("إغلاق", QDialogButtonBox.RejectRole)
        close_btn.setMinimumHeight(38)
        buttons.rejected.connect(dlg.reject)
        lay.addWidget(buttons)
        dlg.exec()
    except Exception as exc:
        print(f"[V2] help dialog failed: {exc}", file=sys.stderr)


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
        _close_splash(self)   # أغلق شاشة البدء فور جاهزية النافذة

    native_app.MainWindow.__init__ = gated_init


def main() -> int:
    _show_splash()              # فورًا: شاشة بدء مرئية خلال أجزاء من الثانية
    _activate_engine()
    import native_app
    native_app.APP_VERSION = APP_VERSION_V2
    _gate_startup(native_app)   # أولاً: بوابة الترخيص (تلتف حول __init__ الأصلي)
    _patch_ui(native_app)       # ثانيًا: إضافات الواجهة (تلتف حول gated_init)
    try:
        return native_app.main()
    finally:
        _close_splash()


if __name__ == "__main__":
    raise SystemExit(main())
