# -*- coding: utf-8 -*-
"""نافذة «حقائق التغذية» المبسطة — اقتصاص يدوي حر بجودة كاملة.

الفكرة (طلب المستخدم في SESSION_HANDOFF — مشكلة 5):
- بلا Tesseract وبلا OCR إطلاقًا — أدوات مدمجة فقط (OpenCV + Qt).
- تُعرض الصورة الأصلية بدقتها الكاملة مع مستطيل تحديد حر:
  سحب لإنشاء تحديد جديد، مقابض 8 لضبط الحواف، تحريك من الداخل،
  تكبير/تصغير بعجلة الماوس، وتحريك العرض بالسحب بالزر الأيمن.
- زر «كشف تلقائي» اختياري يقترح مكان الجدول (بنية الخطوط الشبكية).
- «اقتصاص وحفظ» يقتص من مصفوفة الصورة الأصلية الكاملة مباشرة
  (لا من نسخة العرض) — صفر فقدان جودة — ثم يحفظ ضمن صور الصنف.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QImage,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

__all__ = ["NutritionCropDialog", "NutritionCropCanvas"]

_HANDLE = 12  # نصف قطر التقاط المقبض بالبكسل (إحداثيات الشاشة)


def _np_to_qimage(img: np.ndarray) -> QImage:
    """تحويل مصفوفة BGR إلى QImage RGB مع نسخة مستقلة للذاكرة."""
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, rgb.strides[0], QImage.Format_RGB888).copy()


class NutritionCropCanvas(QWidget):
    """كانفس عرض الصورة الكاملة مع تحديد حر + تكبير بعجلة الماوس.

    التحديد يُخزَّن بإحداثيات **الصورة الأصلية** (بكسل حقيقي) دائمًا،
    فالاقتصاص لاحقًا يكون بدقة كاملة مهما كان مستوى العرض/التكبير.
    """

    selection_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._img: np.ndarray | None = None
        self._pixmap: QPixmap | None = None
        self._zoom = 1.0          # معامل التكبير فوق قياس الملاءمة
        self._fit_scale = 1.0     # قياس ملاءمة الصورة للنافذة
        self._offset = QPointF(0, 0)  # إزاحة العرض (بكسل شاشة)
        self._sel: QRectF | None = None  # التحديد بإحداثيات الصورة
        self._mode: str | None = None    # draw | move | pan | مقبض
        self._press_pos = QPointF()
        self._press_sel: QRectF | None = None
        self._press_offset = QPointF()
        self.setMouseTracking(True)
        self.setMinimumSize(420, 320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.CrossCursor)

    # ---------- واجهة عامة ----------
    def set_image(self, img: np.ndarray) -> None:
        self._img = img
        self._pixmap = QPixmap.fromImage(_np_to_qimage(img))
        self._zoom = 1.0
        self._offset = QPointF(0, 0)
        self._sel = None
        self._update_fit()
        self.update()
        self.selection_changed.emit()

    def image_size(self) -> tuple[int, int]:
        if self._img is None:
            return (0, 0)
        h, w = self._img.shape[:2]
        return (w, h)

    def selection_image_rect(self) -> tuple[int, int, int, int] | None:
        """التحديد الحالي بإحداثيات الصورة الأصلية (x, y, w, h) أو None."""
        if self._sel is None or self._img is None:
            return None
        r = self._sel.normalized()
        H, W = self._img.shape[:2]
        x0 = max(0, min(W - 1, int(round(r.left()))))
        y0 = max(0, min(H - 1, int(round(r.top()))))
        x1 = max(0, min(W, int(round(r.right()))))
        y1 = max(0, min(H, int(round(r.bottom()))))
        if x1 - x0 < 8 or y1 - y0 < 8:
            return None
        return (x0, y0, x1 - x0, y1 - y0)

    def set_selection_image_rect(self, box: tuple[int, int, int, int]) -> None:
        x, y, w, h = box
        self._sel = QRectF(float(x), float(y), float(w), float(h))
        self.update()
        self.selection_changed.emit()

    def clear_selection(self) -> None:
        self._sel = None
        self.update()
        self.selection_changed.emit()

    # ---------- تحويلات الإحداثيات ----------
    def _scale(self) -> float:
        return self._fit_scale * self._zoom

    def _update_fit(self) -> None:
        if self._pixmap is None or self._pixmap.width() == 0:
            self._fit_scale = 1.0
            return
        sw = max(1, self.width())
        sh = max(1, self.height())
        self._fit_scale = min(sw / self._pixmap.width(),
                              sh / self._pixmap.height())

    def _image_to_screen(self, p: QPointF) -> QPointF:
        s = self._scale()
        return QPointF(p.x() * s + self._offset.x(),
                       p.y() * s + self._offset.y())

    def _screen_to_image(self, p: QPointF) -> QPointF:
        s = self._scale() or 1.0
        return QPointF((p.x() - self._offset.x()) / s,
                       (p.y() - self._offset.y()) / s)

    def _sel_screen_rect(self) -> QRectF | None:
        if self._sel is None:
            return None
        r = self._sel.normalized()
        tl = self._image_to_screen(r.topLeft())
        br = self._image_to_screen(r.bottomRight())
        return QRectF(tl, br)

    def _center_image(self) -> None:
        """توسيط الصورة عند الملاءمة الأولى أو تغيير الحجم."""
        if self._pixmap is None:
            return
        s = self._scale()
        w = self._pixmap.width() * s
        h = self._pixmap.height() * s
        self._offset = QPointF((self.width() - w) / 2.0,
                               (self.height() - h) / 2.0)

    # ---------- أحداث ----------
    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        old = self._fit_scale
        self._update_fit()
        if self._pixmap is not None and (self._zoom <= 1.001 or old <= 0):
            self._center_image()
        super().resizeEvent(event)

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._update_fit()
        self._center_image()
        super().showEvent(event)

    def wheelEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._pixmap is None:
            return
        delta = event.angleDelta().y()
        factor = 1.15 if delta > 0 else 1 / 1.15
        new_zoom = max(0.6, min(12.0, self._zoom * factor))
        if abs(new_zoom - self._zoom) < 1e-6:
            return
        # تكبير حول موضع المؤشر: نثبت نقطة الصورة تحت المؤشر
        mouse = QPointF(event.position())
        img_pt = self._screen_to_image(mouse)
        self._zoom = new_zoom
        s = self._scale()
        self._offset = QPointF(mouse.x() - img_pt.x() * s,
                               mouse.y() - img_pt.y() * s)
        self.update()

    def _hit_test(self, pos: QPointF) -> str | None:
        """يحدد ماذا تحت المؤشر: مقبض (tl,tr,bl,br,l,r,t,b) أو inside."""
        r = self._sel_screen_rect()
        if r is None:
            return None
        handles = {
            "tl": r.topLeft(), "tr": r.topRight(),
            "bl": r.bottomLeft(), "br": r.bottomRight(),
            "t": QPointF(r.center().x(), r.top()),
            "b": QPointF(r.center().x(), r.bottom()),
            "l": QPointF(r.left(), r.center().y()),
            "r": QPointF(r.right(), r.center().y()),
        }
        for name, hp in handles.items():
            if (abs(pos.x() - hp.x()) <= _HANDLE
                    and abs(pos.y() - hp.y()) <= _HANDLE):
                return name
        if r.adjusted(-2, -2, 2, 2).contains(pos):
            return "inside"
        return None

    _CURSORS = {
        "tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor,
        "tr": Qt.SizeBDiagCursor, "bl": Qt.SizeBDiagCursor,
        "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor,
        "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor,
        "inside": Qt.SizeAllCursor,
    }

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        pos = QPointF(event.position())
        if event.button() in (Qt.RightButton, Qt.MiddleButton):
            self._mode = "pan"
            self._press_pos = pos
            self._press_offset = QPointF(self._offset)
            self.setCursor(Qt.ClosedHandCursor)
            return
        if event.button() != Qt.LeftButton or self._img is None:
            return
        hit = self._hit_test(pos)
        self._press_pos = pos
        if hit == "inside":
            self._mode = "move"
            self._press_sel = QRectF(self._sel.normalized())
        elif hit is not None:
            self._mode = hit
            self._press_sel = QRectF(self._sel.normalized())
        else:
            self._mode = "draw"
            start = self._screen_to_image(pos)
            self._sel = QRectF(start, start)
        self.update()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        pos = QPointF(event.position())
        if self._mode is None:
            hit = self._hit_test(pos)
            self.setCursor(self._CURSORS.get(hit, Qt.CrossCursor))
            return
        if self._mode == "pan":
            d = pos - self._press_pos
            self._offset = self._press_offset + d
            self.update()
            return
        if self._img is None:
            return
        img_pt = self._screen_to_image(pos)
        H, W = self._img.shape[:2]
        img_pt.setX(max(0.0, min(float(W), img_pt.x())))
        img_pt.setY(max(0.0, min(float(H), img_pt.y())))
        if self._mode == "draw":
            self._sel = QRectF(self._sel.topLeft(), img_pt)
        elif self._mode == "move" and self._press_sel is not None:
            s = self._scale() or 1.0
            d = (pos - self._press_pos) / s
            moved = self._press_sel.translated(d)
            # لا يخرج التحديد عن حدود الصورة
            dx = min(0.0, moved.left()) or max(0.0, moved.right() - W)
            dy = min(0.0, moved.top()) or max(0.0, moved.bottom() - H)
            self._sel = moved.translated(-dx, -dy)
        elif self._press_sel is not None:
            r = QRectF(self._press_sel)
            if "l" in self._mode or self._mode in ("tl", "bl"):
                r.setLeft(img_pt.x())
            if "r" in self._mode or self._mode in ("tr", "br"):
                r.setRight(img_pt.x())
            if "t" in self._mode or self._mode in ("tl", "tr"):
                r.setTop(img_pt.y())
            if "b" in self._mode or self._mode in ("bl", "br"):
                r.setBottom(img_pt.y())
            self._sel = r
        self.update()
        self.selection_changed.emit()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._mode == "pan":
            self.setCursor(Qt.CrossCursor)
        if self._mode == "draw" and self.selection_image_rect() is None:
            self._sel = None  # نقرة بلا سحب — لا تحديد شبحي
        self._mode = None
        self.update()
        self.selection_changed.emit()

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(24, 30, 42))
        if self._pixmap is None:
            painter.setPen(QColor(148, 163, 184))
            painter.drawText(self.rect(), Qt.AlignCenter, "لا توجد صورة")
            painter.end()
            return
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        s = self._scale()
        target = QRectF(self._offset.x(), self._offset.y(),
                        self._pixmap.width() * s, self._pixmap.height() * s)
        painter.drawPixmap(target, self._pixmap,
                           QRectF(self._pixmap.rect()))
        sel = self._sel_screen_rect()
        if sel is not None and sel.width() > 2 and sel.height() > 2:
            # تعتيم خارج التحديد
            overlay = QColor(8, 12, 20, 120)
            full = QRectF(self.rect())
            for shade in (
                QRectF(full.left(), full.top(), full.width(), sel.top()),
                QRectF(full.left(), sel.bottom(), full.width(),
                       full.bottom() - sel.bottom()),
                QRectF(full.left(), sel.top(), sel.left(), sel.height()),
                QRectF(sel.right(), sel.top(), full.right() - sel.right(),
                       sel.height()),
            ):
                painter.fillRect(shade, overlay)
            pen = QPen(QColor(52, 211, 153), 2)
            painter.setPen(pen)
            painter.drawRect(sel)
            # مقابض
            painter.setBrush(QColor(52, 211, 153))
            for hp in (
                sel.topLeft(), sel.topRight(), sel.bottomLeft(),
                sel.bottomRight(),
                QPointF(sel.center().x(), sel.top()),
                QPointF(sel.center().x(), sel.bottom()),
                QPointF(sel.left(), sel.center().y()),
                QPointF(sel.right(), sel.center().y()),
            ):
                painter.drawEllipse(hp, 5, 5)
            # شارة أبعاد الاقتصاص الفعلية (بكسل الصورة الأصلية)
            box = self.selection_image_rect()
            if box is not None:
                text = f"{box[2]} × {box[3]} بكسل"
                painter.setPen(QColor(226, 232, 240))
                badge = QRectF(sel.left(), max(2.0, sel.top() - 24),
                               max(120.0, sel.width()), 20)
                painter.fillRect(
                    QRectF(badge.left(), badge.top(), 128, 20),
                    QColor(15, 23, 42, 200))
                painter.drawText(
                    QRectF(badge.left() + 4, badge.top(), 124, 20),
                    Qt.AlignVCenter | Qt.AlignLeft, text)
        painter.end()


class NutritionCropDialog(QDialog):
    """نافذة اقتصاص حقائق التغذية — 3 خطوات: حدد، اضبط، احفظ.

    تستقبل مسار الصورة الأصلية (بدقة كاملة) وقائمة صور بديلة اختيارية
    (بقية صور الصنف — إذا كان الجدول على صورة أخرى). عند القبول تُرجع
    ``cropped_image()`` مصفوفة الاقتصاص من الأصل مباشرة و
    ``render_on_canvas()`` خيار المستخدم للوحة البيضاء.
    """

    #: تُطلق عند كل طلب حفظ (المصفوفة المقتصة، لوحة بيضاء؟) — تسمح بالحفظ
    #: المتكرر دون إغلاق النافذة (عدة اقتصاصات من نفس الصورة).
    save_requested = Signal(object, bool, object)

    def __init__(self, source_path: str | Path,
                 alternatives: list[tuple[str, str]] | None = None,
                 product_name: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("حقائق التغذية — اقتصاص بجودة كاملة")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setModal(True)
        self.resize(880, 660)
        self._alternatives = list(alternatives or [])
        self._current_path = str(source_path)
        self._img: np.ndarray | None = None
        self._alt_index = -1
        self._rotation = 0  # دوران العرض الحالي (0/90/180/270)
        self._saved_count = 0  # عدد الصور المحفوظة في هذه الجلسة
        self._merge_product_img: np.ndarray | None = None  # صورة الصنف الهدف
        self._merge_target_text = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(8)

        title = QLabel(
            f"حدد جدول حقائق التغذية على الصورة{'' if not product_name else ' — ' + product_name}")
        title.setObjectName("nutritionCropTitle")
        title.setWordWrap(True)
        root.addWidget(title)

        hint = QLabel(
            "اسحب لتحديد الجدول • حرّك الحواف بالمقابض • عجلة الماوس للتكبير"
            " • السحب بالزر الأيمن لتحريك العرض")
        hint.setObjectName("nutritionCropHint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.canvas = NutritionCropCanvas(self)
        self.canvas.selection_changed.connect(self._refresh_state)
        root.addWidget(self.canvas, 1)

        root.addWidget(self._build_mode_bar())

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.detect_button = QPushButton("🔍 كشف تلقائي")
        self.detect_button.setToolTip(
            "يقترح مكان الجدول تلقائيًا (بنية الخطوط) — يمكنك تعديله بعدها")
        self.detect_button.clicked.connect(self._auto_detect)
        self.rotate_button = QPushButton("↻ تدوير")
        self.rotate_button.setToolTip(
            "الصورة ملتقطة بالعرض؟ دوّرها 90° حتى يستقيم الجدول —\n"
            "التدوير يطبّق على الاقتصاص المحفوظ أيضًا ولا يمس الصورة الأصلية")
        self.rotate_button.clicked.connect(self._rotate90)
        self.preview_button = QPushButton("👁 معاينة")
        self.preview_button.setToolTip(
            "معاينة الناتج النهائي (باللوحة البيضاء إن كانت مفعلة) قبل الحفظ")
        self.preview_button.setEnabled(False)
        self.preview_button.clicked.connect(self._preview_result)
        self.switch_button = QPushButton("🖼 صورة أخرى")
        self.switch_button.setToolTip(
            "الجدول على صورة أخرى للصنف؟ بدّل بين صور الصنف هنا")
        self.switch_button.clicked.connect(self._switch_image)
        self.switch_button.setVisible(bool(self._alternatives))
        self.clear_button = QPushButton("مسح التحديد")
        self.clear_button.clicked.connect(self.canvas.clear_selection)
        self.cancel_button = QPushButton("إغلاق")
        self.cancel_button.setToolTip(
            "يغلق النافذة — ما حُفظ يبقى محفوظًا")
        self.cancel_button.clicked.connect(self.reject)
        self.save_button = QPushButton("✂ اقتصاص وحفظ ضمن صور الصنف")
        self.save_button.setObjectName("nutritionSaveButton")
        self.save_button.setEnabled(False)
        self.save_button.setToolTip(
            "يحفظ الاقتصاص كصورة جديدة مرتبطة برقم الصنف —\n"
            "النافذة تبقى مفتوحة لتقتص وتحفظ المزيد من نفس الصورة")
        self.save_button.clicked.connect(self._save_current)
        for b in (self.detect_button, self.rotate_button,
                  self.preview_button, self.switch_button, self.clear_button,
                  self.cancel_button, self.save_button):
            b.setMinimumHeight(36)
            b.setMinimumWidth(
                b.fontMetrics().horizontalAdvance(b.text()) + 30)
        buttons.addWidget(self.detect_button)
        buttons.addWidget(self.rotate_button)
        buttons.addWidget(self.preview_button)
        buttons.addWidget(self.switch_button)
        buttons.addWidget(self.clear_button)
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.save_button)
        root.addLayout(buttons)

        self.status_label = QLabel("")
        self.status_label.setObjectName("nutritionCropStatus")
        root.addWidget(self.status_label)

        self.setStyleSheet(
            """
            QDialog { background: #f3f6fb; }
            QLabel#nutritionCropTitle {
                font-size: 15px; font-weight: 700; color: #1e293b; }
            QLabel#nutritionCropHint { color: #64748b; font-size: 12px; }
            QLabel#nutritionCropStatus { color: #0f766e; font-weight: 600; }
            QPushButton {
                background: #ffffff; border: 1px solid #cbd5e1;
                border-radius: 8px; padding: 6px 14px; color: #1e293b;
                font-weight: 600; }
            QPushButton:hover { border-color: #64748b; }
            QPushButton#nutritionSaveButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #10b981, stop:1 #059669);
                border: 1px solid #047857; color: white; }
            QPushButton#nutritionSaveButton:disabled {
                background: #cbd5e1; border-color: #b6c2d1; color: #7c8aa0; }
            QCheckBox { color: #334155; font-weight: 600; }
            QFrame#nutritionModeBar {
                background: #ffffff; border: 1px solid #d7e0ec;
                border-radius: 10px; }
            QRadioButton {
                color: #1e293b; font-weight: 700; font-size: 13px;
                padding: 2px 4px; }
            QRadioButton:disabled { color: #94a3b8; }
            QLabel#nutritionMergeTarget {
                color: #0f766e; font-weight: 700; font-size: 12px; }
            QComboBox {
                background: #f8fafc; border: 1px solid #cbd5e1;
                border-radius: 7px; padding: 4px 10px; color: #1e293b;
                font-weight: 600; min-height: 24px; }
            QComboBox:hover { border-color: #64748b; }
            """
        )
        self._load(self._current_path)
        self._refresh_state()

    # ---------- شريط وضع الحفظ ----------
    def _build_mode_bar(self) -> QWidget:
        """شريط اختيار وجهة الناتج: دمج داخل صورة الصنف (الافتراضي)
        أو صورة منفصلة، مع الزاوية والحجم ومعاينة فورية."""
        box = QFrame()
        box.setObjectName("nutritionModeBar")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)

        row1 = QHBoxLayout()
        row1.setSpacing(10)
        self.mode_merge_radio = QRadioButton("🧷 دمج داخل صورة الصنف")
        self.mode_merge_radio.setChecked(True)
        self.mode_merge_radio.setToolTip(
            "الوضع المعتمد: يلصق جدول الحقائق في زاوية من صورة الصنف\n"
            "نفسها وينتج صورة واحدة — والأصل لا يُمس.")
        self.mode_separate_radio = QRadioButton("🖼 صورة منفصلة للحقائق")
        self.mode_separate_radio.setToolTip(
            "يحفظ الجدول وحده على لوحة بيضاء كصورة إضافية للصنف.")
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self.mode_merge_radio, 0)
        self._mode_group.addButton(self.mode_separate_radio, 1)
        self._mode_group.idToggled.connect(lambda *_: self._refresh_state())
        row1.addWidget(self.mode_merge_radio)
        row1.addWidget(self.mode_separate_radio)
        row1.addStretch(1)
        lay.addLayout(row1)

        # إعدادات وضع الدمج
        self.merge_options = QWidget()
        row2 = QHBoxLayout(self.merge_options)
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(8)
        row2.addWidget(QLabel("الزاوية:"))
        self.anchor_combo = QComboBox()
        for text, val in (
            ("أسفل يمين", "bottom_right"),
            ("أسفل يسار", "bottom_left"),
            ("أعلى يمين", "top_right"),
            ("أعلى يسار", "top_left"),
        ):
            self.anchor_combo.addItem(text, val)
        self.anchor_combo.setToolTip(
            "موضع جدول الحقائق داخل صورة الصنف — الأشهر: أسفل يمين")
        row2.addWidget(self.anchor_combo)
        row2.addSpacing(8)
        row2.addWidget(QLabel("الحجم:"))
        self.size_combo = QComboBox()
        for text, val in (("متوسط (34%)", 0.34), ("صغير (26%)", 0.26),
                          ("كبير (44%)", 0.44), ("كبير جدًا (55%)", 0.55)):
            self.size_combo.addItem(text, val)
        self.size_combo.setToolTip(
            "نسبة عرض الجدول من عرض الصورة الناتجة.\n"
            "ملاحظة: الجودة محفوظة دائمًا — إن لزم تُرقّى دقة اللوحة\n"
            "بدل تصغير الجدول وفقدان الكتابات.")
        row2.addWidget(self.size_combo)
        row2.addStretch(1)
        self.merge_target_label = QLabel("")
        self.merge_target_label.setObjectName("nutritionMergeTarget")
        row2.addWidget(self.merge_target_label)
        lay.addWidget(self.merge_options)

        self.white_canvas_check = QCheckBox(
            "تجهيز على لوحة بيضاء مع تحسين وضوح (منصات التسوق)")
        self.white_canvas_check.setChecked(True)
        self.white_canvas_check.setToolTip(
            "مفعل: يوضع الجدول المقتص على لوحة بيضاء أنيقة مع تحسين التباين\n"
            "معطل: يُحفظ الاقتصاص الخام كما هو تمامًا")
        lay.addWidget(self.white_canvas_check)

        self.anchor_combo.currentIndexChanged.connect(self._refresh_state)
        self.size_combo.currentIndexChanged.connect(self._refresh_state)
        return box

    # ---------- خيارات المستخدم ----------
    def merge_mode(self) -> bool:
        """True = دمج داخل صورة الصنف (الافتراضي)."""
        return bool(self.mode_merge_radio.isChecked())

    def merge_anchor(self) -> str:
        return str(self.anchor_combo.currentData() or "bottom_right")

    def merge_scale(self) -> float:
        try:
            return float(self.size_combo.currentData())
        except Exception:
            return 0.34

    def set_merge_target_info(self, text: str) -> None:
        """يعرض اسم صورة الصنف التي سيجري الدمج عليها."""
        self._merge_target_text = text
        self.merge_target_label.setText(text)

    def merge_placement(self):
        """يبني InsetPlacement من خيارات الواجهة."""
        from engine_v2.nutrition_v2 import InsetPlacement
        return InsetPlacement(anchor=self.merge_anchor(),
                              scale=self.merge_scale()).clamp()

    # ---------- تحميل الصور ----------
    def _load(self, path: str) -> bool:
        from engine_v2.processor_v2 import imread_unicode
        img = imread_unicode(path)
        if img is None:
            QMessageBox.warning(self, "حقائق التغذية",
                                f"تعذر قراءة الصورة:\n{path}")
            return False
        self._img = img
        self._current_path = path
        self._rotation = 0
        self.canvas.set_image(img)
        h, w = img.shape[:2]
        self.status_label.setText(
            f"الصورة الأصلية: {w}×{h} بكسل — الاقتصاص سيكون من هذه الدقة الكاملة")
        return True

    def current_source_path(self) -> str:
        return self._current_path

    # ---------- أفعال ----------
    def _refresh_state(self) -> None:
        box = self.canvas.selection_image_rect()
        self.save_button.setEnabled(box is not None)
        self.preview_button.setEnabled(box is not None)
        merge = self.merge_mode()
        self.merge_options.setVisible(merge)
        self.white_canvas_check.setVisible(not merge)
        self.save_button.setText("🧷 دمج وحفظ في صورة الصنف"
                                 if merge else
                                 "✂ اقتصاص وحفظ كصورة منفصلة")
        if merge and box is not None:
            self._update_merge_forecast(box)
        elif merge:
            self.merge_target_label.setText(self._merge_target_text)

    def _update_merge_forecast(self, box) -> None:
        """يعرض أرقام الناتج المتوقعة (اللوحة ونسبة البكسل
        المحفوظ) قبل الحفظ حتى يطمئن المستخدم للجودة."""
        target = self._merge_product_img
        if target is None:
            self.merge_target_label.setText(self._merge_target_text)
            return
        cropped = self.cropped_image()
        if cropped is None:
            self.merge_target_label.setText(self._merge_target_text)
            return
        try:
            from engine_v2.nutrition_v2 import merge_stats
            st = merge_stats(target, cropped, self.merge_placement())
            ratio = int(round(st["label_pixel_ratio"] * 100))
            cw, ch = st["canvas"]
            mark = "✓ جودة كاملة" if ratio >= 96 else f"دقة الجدول {ratio}%"
            self.merge_target_label.setText(
                f"{self._merge_target_text}  •  الناتج {cw}×{ch}  •  {mark}")
        except Exception:
            self.merge_target_label.setText(self._merge_target_text)

    def set_merge_product(self, img, label: str = "") -> None:
        """تحدد صورة الصنف النهائية التي سيدمج فيها الجدول."""
        self._merge_product_img = img
        if label:
            self.set_merge_target_info(label)
        if img is None:
            self.mode_merge_radio.setEnabled(False)
            self.mode_separate_radio.setChecked(True)
            self.set_merge_target_info(
                "لا توجد صورة ناتجة للصنف — الوضع المنفصل فقط")
        self._refresh_state()

    def merged_result(self):
        """يبني الناتج المدموج النهائي أو None."""
        cropped = self.cropped_image()
        if cropped is None or self._merge_product_img is None:
            return None
        from engine_v2.nutrition_v2 import merge_label_inset
        return merge_label_inset(self._merge_product_img, cropped,
                                 self.merge_placement())

    def _rotate90(self) -> None:
        """تدوير العرض 90° مع الساعة — يطبّق على مصفوفة العمل
        فقط (الاقتصاصات اللاحقة تخرج مدوّرة)، الملف الأصلي لا يُمس."""
        if self._img is None:
            return
        self._img = cv2.rotate(self._img, cv2.ROTATE_90_CLOCKWISE)
        self._rotation = (self._rotation + 90) % 360
        self.canvas.set_image(self._img)
        self.status_label.setText(
            f"دوران العرض: {self._rotation}° — الصورة الأصلية لم تتغير")

    def _preview_result(self) -> None:
        """معاينة الناتج النهائي قبل الحفظ — كما سيُحفظ تمامًا."""
        cropped = self.cropped_image()
        if cropped is None:
            return
        final = cropped
        if self.merge_mode():
            merged = self.merged_result()
            if merged is not None:
                final = merged
        elif self.render_on_canvas():
            try:
                from engine_v2.nutrition_v2 import render_standalone_label
                final = render_standalone_label(cropped, 800, 700, hq=True)
            except Exception:
                final = cropped
        dlg = QDialog(self)
        dlg.setWindowTitle("معاينة الناتج قبل الحفظ")
        dlg.setLayoutDirection(Qt.RightToLeft)
        lay = QVBoxLayout(dlg)
        fh, fw = final.shape[:2]
        info = QLabel(f"الناتج النهائي: {fw}×{fh} بكسل")
        info.setStyleSheet("font-weight:700;color:#0f766e;")
        lay.addWidget(info)
        pic = QLabel()
        pix = QPixmap.fromImage(_np_to_qimage(final))
        pic.setPixmap(pix.scaled(720, 520, Qt.KeepAspectRatio,
                                 Qt.SmoothTransformation))
        pic.setAlignment(Qt.AlignCenter)
        lay.addWidget(pic)
        row = QHBoxLayout()
        save_now = QPushButton("✂ احفظ الآن")
        save_now.setStyleSheet(
            "background:#059669;color:white;font-weight:800;padding:8px 18px;"
            "border-radius:8px;")
        close_btn = QPushButton("رجوع")
        row.addStretch(1)
        row.addWidget(close_btn)
        row.addWidget(save_now)
        lay.addLayout(row)
        save_now.clicked.connect(lambda: (dlg.accept(), self._save_current()))
        close_btn.clicked.connect(dlg.reject)
        dlg.exec()

    def _save_current(self) -> None:
        """حفظ الاقتصاص الحالي دون إغلاق النافذة — يمكن تكرار
        الاقتصاص والحفظ عدة مرات من نفس الصورة."""
        cropped = self.cropped_image()
        if cropped is None:
            return
        self._saved_count += 1
        merge_opts = None
        if self.merge_mode() and self._merge_product_img is not None:
            merge_opts = self.merge_placement()
        self.save_requested.emit(cropped, self.render_on_canvas(), merge_opts)
        self.status_label.setText(
            (f"✓ دُمجت الحقائق داخل صورة الصنف ({self._saved_count})"
             if merge_opts is not None else
             f"✓ حُفظت الصورة المنفصلة {self._saved_count}")
            + " — يمكنك تحديد جزء آخر وحفظه، أو إغلاق النافذة")
        self.canvas.clear_selection()

    def saved_count(self) -> int:
        return self._saved_count

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _auto_detect(self) -> None:
        if self._img is None:
            return
        try:
            from engine_v2.nutrition_v2 import detect_nutrition_table
            box = detect_nutrition_table(self._img)
        except Exception:
            box = None
        if box is None:
            self.status_label.setText(
                "لم يُعثر على جدول واضح تلقائيًا — حدده يدويًا بالسحب")
            return
        self.canvas.set_selection_image_rect(box)
        self.status_label.setText(
            "اقتراح تلقائي — عدّل الحواف بالمقابض إن لزم ثم احفظ")

    def _switch_image(self) -> None:
        if not self._alternatives:
            return
        self._alt_index = (self._alt_index + 1) % len(self._alternatives)
        path, label = self._alternatives[self._alt_index]
        if self._load(path) and label:
            self.status_label.setText(f"الصورة الحالية: {label}")

    # ---------- النتائج ----------
    def cropped_image(self, pad: int = 6) -> np.ndarray | None:
        """الاقتصاص من مصفوفة الصورة الأصلية الكاملة — بلا أي تصغير."""
        box = self.canvas.selection_image_rect()
        if box is None or self._img is None:
            return None
        from engine_v2.nutrition_v2 import crop_region
        return crop_region(self._img, box, pad=pad)

    def render_on_canvas(self) -> bool:
        return self.white_canvas_check.isChecked()


def save_nutrition_image(cropped: np.ndarray, out_dir: str | Path,
                         item_code: str, *, on_canvas: bool = True,
                         product_img: np.ndarray | None = None,
                         placement=None) -> Path:
    """يجهز ناتج حقائق التغذية ويحفظه ضمن مجلد صور الصنف.

    وضعان:
    - الدمج (المعتمد): يُمرر `product_img` و`placement` فيُلصق الجدول
      في زاوية من صورة الصنف ويُحفظ كصورة واحدة.
    - المنفصل: جدول وحده على لوحة بيضاء.

    الحفظ دائمًا WebP بلا فقدان (lossless) لأن النصوص لا تتحمل أي ضغط.
    يعيد مسار الملف.
    """
    from engine_v2.nutrition_v2 import (merge_label_inset,
                                        render_standalone_label)
    from engine_v2.processor_v2 import imwrite_unicode
    from engine_v2 import integration_v2

    if product_img is not None and placement is not None:
        final = merge_label_inset(product_img, cropped, placement)
    elif on_canvas:
        final = render_standalone_label(cropped, 800, 700, hq=True)
    else:
        final = cropped
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = integration_v2.build_output_stem(out_dir, str(item_code))
    target = out_dir / f"{stem}.webp"
    counter = 2
    while target.exists():
        target = out_dir / f"{stem}({counter}).webp"
        counter += 1
    if not imwrite_unicode(target, final, lossless_webp=True):
        raise OSError(f"فشل حفظ صورة حقائق التغذية: {target}")
    return target
