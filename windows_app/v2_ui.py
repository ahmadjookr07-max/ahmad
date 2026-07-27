# -*- coding: utf-8 -*-
"""V2 UI additions for Ahmed Al-Faifi Market Image Studio 2.0.0.

Provides three self-contained dialogs wired into the legacy MainWindow via
``install_v2`` (no invasive rewrite of the proven 1.2.1 UI):

1. NutritionDialog   — full nutrition-facts panel: detect / manual crop /
                       standalone / small inset (4 anchors + free drag +
                       scale) / OCR rebuild with a mandatory review editor /
                       remove / not-found.
2. BulkRenameDialog  — the external renaming tool for previously produced
                       result folders (fixes mojibake, maps old→new item
                       codes, preserves image-group linkage, dry-run table).
3. SessionDialog     — save & resume picker shown at startup.

All widgets are RTL, generously sized (min 1280x800 main window) and use
large hit targets to avoid the cramped/overlapping layout of 1.2.1.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QPointF, QRectF, QThread, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

# ----------------------------------------------------------------- helpers

def _engine_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "src"


def _ensure_engine_path() -> None:
    p = str(_engine_dir())
    if p not in sys.path:
        sys.path.insert(0, p)


def cv_to_qpixmap(img) -> QPixmap:
    import numpy as np
    import cv2
    if img is None:
        return QPixmap()
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 4:
        rgba = cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
        h, w = rgba.shape[:2]
        qimg = QImage(rgba.data, w, h, w * 4, QImage.Format_RGBA8888)
    else:
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        qimg = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


def read_image(path: str):
    import numpy as np
    import cv2
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


# ============================================================== crop widget
class CropSelectLabel(QLabel):
    """Image display with a draggable/resizable selection rectangle."""

    selection_changed = Signal()

    HANDLE = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(560, 420)
        self._pix = QPixmap()
        self._rect = QRectF(0.2, 0.2, 0.6, 0.6)   # normalized
        self._drag_mode = None
        self._drag_start = QPointF()
        self._rect_start = QRectF()
        self.setMouseTracking(True)

    def set_image(self, pixmap: QPixmap) -> None:
        self._pix = pixmap
        self.update()

    def selection(self) -> tuple[float, float, float, float]:
        r = self._rect.normalized()
        return (max(0.0, r.left()), max(0.0, r.top()),
                min(1.0, r.right()), min(1.0, r.bottom()))

    def set_selection(self, box) -> None:
        x1, y1, x2, y2 = box
        self._rect = QRectF(x1, y1, x2 - x1, y2 - y1)
        self.update()

    # ------------------------------------------------------------ painting
    def _image_rect(self) -> QRectF:
        if self._pix.isNull():
            return QRectF()
        scaled = self._pix.size().scaled(self.size(), Qt.KeepAspectRatio)
        x = (self.width() - scaled.width()) / 2
        y = (self.height() - scaled.height()) / 2
        return QRectF(x, y, scaled.width(), scaled.height())

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._pix.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        img_rect = self._image_rect()
        painter.drawPixmap(img_rect.toRect(), self._pix)
        # selection in widget coords
        sel = QRectF(
            img_rect.left() + self._rect.left() * img_rect.width(),
            img_rect.top() + self._rect.top() * img_rect.height(),
            self._rect.width() * img_rect.width(),
            self._rect.height() * img_rect.height(),
        )
        # dim outside
        painter.setBrush(QColor(0, 0, 0, 110))
        painter.setPen(Qt.NoPen)
        for region in (
            QRectF(img_rect.left(), img_rect.top(), img_rect.width(), sel.top() - img_rect.top()),
            QRectF(img_rect.left(), sel.bottom(), img_rect.width(), img_rect.bottom() - sel.bottom()),
            QRectF(img_rect.left(), sel.top(), sel.left() - img_rect.left(), sel.height()),
            QRectF(sel.right(), sel.top(), img_rect.right() - sel.right(), sel.height()),
        ):
            painter.drawRect(region)
        pen = QPen(QColor(0, 200, 255), 3)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(sel)
        painter.setBrush(QColor(0, 200, 255))
        h = self.HANDLE
        for corner in (sel.topLeft(), sel.topRight(), sel.bottomLeft(), sel.bottomRight()):
            painter.drawEllipse(corner, h / 2, h / 2)
        painter.end()

    # ------------------------------------------------------------- mouse
    def _hit(self, pos: QPointF) -> str | None:
        img_rect = self._image_rect()
        if img_rect.isEmpty():
            return None
        sel = QRectF(
            img_rect.left() + self._rect.left() * img_rect.width(),
            img_rect.top() + self._rect.top() * img_rect.height(),
            self._rect.width() * img_rect.width(),
            self._rect.height() * img_rect.height(),
        )
        h = self.HANDLE
        corners = {
            "tl": sel.topLeft(), "tr": sel.topRight(),
            "bl": sel.bottomLeft(), "br": sel.bottomRight(),
        }
        for name, c in corners.items():
            if (pos - c).manhattanLength() <= h * 1.6:
                return name
        if sel.contains(pos):
            return "move"
        return None

    def mousePressEvent(self, event):
        self._drag_mode = self._hit(event.position())
        self._drag_start = event.position()
        self._rect_start = QRectF(self._rect)

    def mouseMoveEvent(self, event):
        if not self._drag_mode:
            return
        img_rect = self._image_rect()
        if img_rect.isEmpty():
            return
        dx = (event.position().x() - self._drag_start.x()) / img_rect.width()
        dy = (event.position().y() - self._drag_start.y()) / img_rect.height()
        r = QRectF(self._rect_start)
        if self._drag_mode == "move":
            r.translate(dx, dy)
            r.moveLeft(min(max(r.left(), 0.0), 1.0 - r.width()))
            r.moveTop(min(max(r.top(), 0.0), 1.0 - r.height()))
        else:
            if "l" in self._drag_mode:
                r.setLeft(min(max(r.left() + dx, 0.0), r.right() - 0.03))
            if "r" in self._drag_mode:
                r.setRight(max(min(r.right() + dx, 1.0), r.left() + 0.03))
            if "t" in self._drag_mode:
                r.setTop(min(max(r.top() + dy, 0.0), r.bottom() - 0.03))
            if "b" in self._drag_mode:
                r.setBottom(max(min(r.bottom() + dy, 1.0), r.top() + 0.03))
        self._rect = r
        self.selection_changed.emit()
        self.update()

    def mouseReleaseEvent(self, event):
        self._drag_mode = None


# ========================================================= nutrition dialog
class OcrWorker(QThread):
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, image, parent=None):
        super().__init__(parent)
        self._image = image

    def run(self):
        try:
            _ensure_engine_path()
            # المحرك الذكي الجديد: قراءات متعددة + تصويت + تحقق منطقي —
            # لا يخترع أي قيمة، وكل قيمة غير مؤكدة تُعلّم للمراجعة
            try:
                from engine_v2.nutrition_smart_v2 import smart_extract
                res = smart_extract(self._image)
                self.finished_ok.emit(res)
                return
            except Exception:
                pass
            # fallback للمحرك القديم إن تعذر الذكي
            from engine_v2.nutrition_ocr_v2 import extract_nutrition_data
            data = extract_nutrition_data(self._image)
            self.finished_ok.emit(data)
        except Exception as exc:  # pragma: no cover
            self.failed.emit(str(exc))


class NutritionDialog(QDialog):
    """Complete nutrition-facts control center for one item."""

    MODES = [
        ("none", "بدون حقائق تغذية"),
        ("standalone", "صورة منفردة مستقلة"),
        ("merge_small", "دمج مصغر داخل صورة المنتج"),
        ("rebuild", "استخراج وإعادة صياغة (جدول عربي منسق)"),
        ("remove", "إزالة الجدول من الصورة"),
        ("not_found", "لم يُعثر عليه"),
    ]
    ANCHORS = [
        ("bottom_left", "أسفل يسار (افتراضي)"),
        ("bottom_right", "أسفل يمين"),
        ("top_left", "أعلى يسار"),
        ("top_right", "أعلى يمين"),
        ("free", "موضع حر (اسحب الملصق)"),
    ]

    def __init__(self, source_path: str, item_number: str = "",
                 nutrition_source: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("حقائق التغذية — التحكم الكامل")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumSize(1180, 760)
        self.source_path = source_path
        self.nutrition_source = nutrition_source or source_path
        self.item_number = item_number
        self.result_settings: dict = {}
        self._ocr_data = None
        self._build()
        self._load_image()
        self._auto_detect()

    # ---------------------------------------------------------------- UI
    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)

        # right: crop view
        view_box = QGroupBox("صورة المصدر — حدد منطقة جدول حقائق التغذية بالسحب")
        vb = QVBoxLayout(view_box)
        self.crop_view = CropSelectLabel()
        vb.addWidget(self.crop_view, 1)
        src_row = QHBoxLayout()
        self.src_label = QLabel(Path(self.nutrition_source).name)
        self.src_label.setStyleSheet("color:#555;")
        pick_btn = QPushButton("اختيار صورة أخرى للجدول (الوجه الخلفي)…")
        pick_btn.setMinimumHeight(40)
        pick_btn.clicked.connect(self._pick_source)
        detect_btn = QPushButton("كشف تلقائي")
        detect_btn.setMinimumHeight(40)
        detect_btn.clicked.connect(self._auto_detect)
        src_row.addWidget(pick_btn)
        src_row.addWidget(detect_btn)
        src_row.addWidget(self.src_label, 1)
        vb.addLayout(src_row)
        root.addWidget(view_box, 3)

        # left: controls
        side = QVBoxLayout()
        side.setSpacing(12)

        mode_box = QGroupBox("وضع الإخراج")
        mv = QVBoxLayout(mode_box)
        self.mode_radios: dict[str, QRadioButton] = {}
        for key, label in self.MODES:
            rb = QRadioButton(label)
            rb.setMinimumHeight(30)
            rb.toggled.connect(self._mode_changed)
            self.mode_radios[key] = rb
            mv.addWidget(rb)
        self.mode_radios["merge_small"].setChecked(True)
        side.addWidget(mode_box)

        # placement controls
        self.place_box = QGroupBox("موقع الملصق وحجمه")
        form = QFormLayout(self.place_box)
        form.setVerticalSpacing(10)
        self.anchor_combo = QComboBox()
        self.anchor_combo.setMinimumHeight(38)
        for key, label in self.ANCHORS:
            self.anchor_combo.addItem(label, key)
        form.addRow("المحاذاة:", self.anchor_combo)
        self.scale_slider = QSlider(Qt.Horizontal)
        self.scale_slider.setRange(12, 60)
        self.scale_slider.setValue(28)
        self.scale_value = QLabel("28%")
        self.scale_slider.valueChanged.connect(
            lambda v: self.scale_value.setText(f"{v}%"))
        srow = QHBoxLayout()
        srow.addWidget(self.scale_slider, 1)
        srow.addWidget(self.scale_value)
        w = QWidget(); w.setLayout(srow)
        form.addRow("حجم الملصق:", w)
        self.off_x = QDoubleSpinBox(); self.off_x.setRange(0.0, 1.0)
        self.off_x.setSingleStep(0.02); self.off_x.setMinimumHeight(34)
        self.off_y = QDoubleSpinBox(); self.off_y.setRange(0.0, 1.0)
        self.off_y.setSingleStep(0.02); self.off_y.setMinimumHeight(34)
        orow = QHBoxLayout()
        orow.addWidget(QLabel("أفقي")); orow.addWidget(self.off_x)
        orow.addWidget(QLabel("عمودي")); orow.addWidget(self.off_y)
        w2 = QWidget(); w2.setLayout(orow)
        form.addRow("الإزاحة الحرة:", w2)
        side.addWidget(self.place_box)

        # rebuild / OCR
        self.rebuild_box = QGroupBox("إعادة الصياغة (تطابق 100% بعد مراجعتك)")
        rv = QVBoxLayout(self.rebuild_box)
        self.ocr_btn = QPushButton("استخراج القيم من المنطقة المحددة (OCR)")
        self.ocr_btn.setMinimumHeight(44)
        self.ocr_btn.clicked.connect(self._run_ocr)
        rv.addWidget(self.ocr_btn)
        self.manual_btn = QPushButton("إدخال القيم يدويًا (قالب فارغ)")
        self.manual_btn.setMinimumHeight(40)
        self.manual_btn.clicked.connect(self._manual_template)
        rv.addWidget(self.manual_btn)
        self.ocr_status = QLabel("لم يتم الاستخراج بعد")
        self.ocr_status.setStyleSheet("color:#666;")
        rv.addWidget(self.ocr_status)
        side.addWidget(self.rebuild_box)

        side.addStretch(1)

        buttons = QDialogButtonBox()
        ok_btn = buttons.addButton("اعتماد الإعدادات", QDialogButtonBox.AcceptRole)
        cancel_btn = buttons.addButton("إلغاء", QDialogButtonBox.RejectRole)
        ok_btn.setMinimumSize(180, 46)
        cancel_btn.setMinimumSize(120, 46)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        side.addWidget(buttons)
        root.addLayout(side, 2)

    # ------------------------------------------------------------- logic
    def _load_image(self):
        self._image = read_image(self.nutrition_source)
        self.crop_view.set_image(cv_to_qpixmap(self._image))

    def _pick_source(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "اختر صورة جدول حقائق التغذية", str(Path(self.nutrition_source).parent),
            "صور (*.jpg *.jpeg *.png *.webp *.bmp)")
        if path:
            self.nutrition_source = path
            self.src_label.setText(Path(path).name)
            self._load_image()
            self._auto_detect()

    def _auto_detect(self):
        try:
            _ensure_engine_path()
            from engine_v2.nutrition_v2 import detect_nutrition_table
            bbox = detect_nutrition_table(self._image)
            if bbox:
                self.crop_view.set_selection(bbox)
                return
        except Exception:
            pass
        self.crop_view.set_selection((0.15, 0.25, 0.85, 0.85))

    def _mode_changed(self):
        if not hasattr(self, "place_box") or not hasattr(self, "rebuild_box"):
            return  # إشارة مبكرة أثناء البناء — الصناديق لم تُنشأ بعد
        mode = self.current_mode()
        self.place_box.setEnabled(mode in ("merge_small", "standalone"))
        self.rebuild_box.setEnabled(mode == "rebuild")

    def current_mode(self) -> str:
        for key, rb in self.mode_radios.items():
            if rb.isChecked():
                return key
        return "none"

    def _crop_image(self):
        import cv2
        x1, y1, x2, y2 = self.crop_view.selection()
        h, w = self._image.shape[:2]
        crop = self._image[int(y1 * h):int(y2 * h), int(x1 * w):int(x2 * w)]
        return crop

    def _run_ocr(self):
        crop = self._crop_image()
        if crop is None or crop.size == 0:
            QMessageBox.warning(self, "تنبيه", "حدد منطقة الجدول أولًا")
            return
        self.ocr_btn.setEnabled(False)
        self.ocr_status.setText("جارٍ الاستخراج…")
        self._worker = OcrWorker(crop, self)
        self._worker.finished_ok.connect(self._ocr_done)
        self._worker.failed.connect(self._ocr_failed)
        self._worker.start()

    def _ocr_failed(self, msg):
        self.ocr_btn.setEnabled(True)
        self.ocr_status.setText("فشل الاستخراج — يمكنك الإدخال اليدوي")
        QMessageBox.warning(self, "فشل OCR", msg)

    def _ocr_done(self, payload):
        self.ocr_btn.setEnabled(True)
        review_keys, warnings = [], []
        data = payload
        if hasattr(payload, "data"):          # SmartExtractionResult
            data = payload.data
            review_keys = list(getattr(payload, "review_keys", []) or [])
            warnings = list(getattr(payload, "warnings", []) or [])
        if not (getattr(data, "rows", None) or getattr(data, "calories", "")):
            self.ocr_status.setText(
                "تعذرت القراءة الآلية — أدخل القيم يدويًا والنظام ينسق تلقائيًا")
            self._manual_template()
            return
        if review_keys:
            self.ocr_status.setText(
                f"تم الاستخراج — {len(review_keys)} قيمة تحتاج تأكيدك (مظللة)")
        else:
            self.ocr_status.setText("تم الاستخراج — راجع القيم الآن")
        self._open_review(data, review_keys, warnings)

    def _manual_template(self):
        _ensure_engine_path()
        from engine_v2.nutrition_ocr_v2 import blank_template
        self._open_review(blank_template())

    def _open_review(self, data, review_keys=None, warnings=None):
        dlg = NutritionReviewDialog(data, self._crop_image(), self,
                                    review_keys=review_keys,
                                    warnings=warnings)
        if dlg.exec() == QDialog.Accepted:
            self._ocr_data = dlg.reviewed_data()
            self.ocr_status.setText("القيم معتمدة بعد المراجعة ✓")

    def _accept(self):
        mode = self.current_mode()
        if mode == "rebuild" and self._ocr_data is None:
            QMessageBox.warning(
                self, "المراجعة إلزامية",
                "وضع إعادة الصياغة يتطلب استخراج القيم ومراجعتها أولًا لضمان تطابق 100%.")
            return
        self.result_settings = {
            "nutrition_mode": mode,
            "nutrition_bbox": self.crop_view.selection(),
            "nutrition_source": self.nutrition_source,
            "nutrition_anchor": self.anchor_combo.currentData(),
            "nutrition_scale": self.scale_slider.value() / 100.0,
            "nutrition_offset": (self.off_x.value(), self.off_y.value()),
            "nutrition_values": (self._ocr_data.to_dict()
                                 if self._ocr_data is not None else None),
        }
        self.accept()


class NutritionReviewDialog(QDialog):
    """Mandatory review screen: original crop beside editable values."""

    def __init__(self, data, crop_image, parent=None,
                 review_keys=None, warnings=None):
        super().__init__(parent)
        self.setWindowTitle("مراجعة قيم حقائق التغذية — التطابق 100% مسؤوليتك هنا")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumSize(1100, 720)
        self._data = data
        self._review_keys = set(review_keys or [])
        self._warnings = list(warnings or [])
        root = QHBoxLayout(self)
        root.setSpacing(14)

        img_box = QGroupBox("الصورة الأصلية للمقارنة")
        iv = QVBoxLayout(img_box)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        lbl = QLabel(); lbl.setAlignment(Qt.AlignCenter)
        pix = cv_to_qpixmap(crop_image)
        if not pix.isNull():
            lbl.setPixmap(pix.scaledToWidth(520, Qt.SmoothTransformation))
        scroll.setWidget(lbl)
        iv.addWidget(scroll)
        root.addWidget(img_box, 1)

        edit_box = QGroupBox("القيم المستخرجة — حرر أي حقل قبل الاعتماد")
        ev = QVBoxLayout(edit_box)
        if self._warnings:
            warn_lbl = QLabel("⚠ " + "\n⚠ ".join(self._warnings[:4]))
            warn_lbl.setWordWrap(True)
            warn_lbl.setStyleSheet(
                "background:#fff3cd;color:#7a5c00;border:1px solid #ffe08a;"
                "border-radius:6px;padding:8px;font-weight:bold;")
            ev.addWidget(warn_lbl)
        if self._review_keys:
            hint = QLabel("الحقول المظللة بالأصفر قرأها النظام بثقة منخفضة — "
                          "قارنها بالصورة الأصلية وصحّحها قبل الاعتماد")
            hint.setWordWrap(True)
            hint.setStyleSheet("color:#8a6d00;")
            ev.addWidget(hint)
        form = QFormLayout()
        form.setVerticalSpacing(8)
        self.servings_edit = QLineEdit(str(getattr(data, "servings", "") or ""))
        self.serving_size_edit = QLineEdit(str(getattr(data, "serving_size", "") or ""))
        self.calories_edit = QLineEdit(str(getattr(data, "calories", "") or ""))
        for w in (self.servings_edit, self.serving_size_edit, self.calories_edit):
            w.setMinimumHeight(34)
        form.addRow("عدد الحصص:", self.servings_edit)
        form.addRow("حجم الحصة:", self.serving_size_edit)
        form.addRow("السعرات الحرارية:", self.calories_edit)
        ev.addLayout(form)

        self.table = QTableWidget()
        rows = list(getattr(data, "rows", []) or [])
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["الحقل", "الكمية", "الوحدة", "٪ القيمة اليومية"])
        self.table.setRowCount(max(len(rows), 14))
        from PySide6.QtGui import QColor
        review_bg = QColor("#fff8c4")
        for i, row in enumerate(rows):
            needs = str(getattr(row, "key", "") or "") in self._review_keys
            for col, attr in ((0, "label_ar"), (1, "amount"),
                              (2, "unit"), (3, "percent")):
                item = QTableWidgetItem(str(getattr(row, attr, "") or ""))
                if needs:
                    item.setBackground(review_bg)
                    item.setToolTip("قراءة بثقة منخفضة — قارن بالصورة الأصلية")
                self.table.setItem(i, col, item)
        # ظلل حقول الرأس إن كانت تحتاج مراجعة
        style_review = "background:#fff8c4;"
        if "calories" in self._review_keys:
            self.calories_edit.setStyleSheet(style_review)
        if "servings" in self._review_keys:
            self.servings_edit.setStyleSheet(style_review)
        if "serving_size" in self._review_keys:
            self.serving_size_edit.setStyleSheet(style_review)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(34)
        ev.addWidget(self.table, 1)

        buttons = QDialogButtonBox()
        ok = buttons.addButton("اعتماد القيم بعد المراجعة", QDialogButtonBox.AcceptRole)
        ok.setMinimumSize(220, 46)
        cancel = buttons.addButton("رجوع", QDialogButtonBox.RejectRole)
        cancel.setMinimumSize(110, 46)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        ev.addWidget(buttons)
        root.addWidget(edit_box, 1)

    def reviewed_data(self):
        _ensure_engine_path()
        from engine_v2.nutrition_ocr_v2 import NutritionData, NutritionRow
        rows = []
        for i in range(self.table.rowCount()):
            def _cell(c):
                item = self.table.item(i, c)
                return item.text().strip() if item else ""
            label = _cell(0)
            if not label:
                continue
            rows.append(NutritionRow(
                key=f"row_{i}", label_ar=label,
                amount=_cell(1), unit=_cell(2), percent=_cell(3)))
        data = self._data
        data.servings = self.servings_edit.text().strip()
        data.serving_size = self.serving_size_edit.text().strip()
        data.calories = self.calories_edit.text().strip()
        data.rows = rows
        return data


# ========================================================== rename dialog
class BulkRenameDialog(QDialog):
    """External tool: re-label previously produced result folders."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("أداة إعادة التسمية والتنظيف — تعمل على أي مجلد")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumSize(1150, 720)
        self._plan = []
        self._folder = ""
        root = QVBoxLayout(self)
        root.setSpacing(12)

        intro = QLabel(
            "تعمل هذه الأداة على مجلد نتائج سابق (مثل SmartCatalogVision-Results):"
            " تصلح الأسماء المشوهة، تنظف الصور حسب رقم اللقطة أو الوحدة،"
            " وتصدّر الأسماء بتنسيق أي منصة (سلة، زد، شوبيفاي، أمازون…)"
            " — كل عملية بمعاينة كاملة قبل التنفيذ والمحذوفات تنتقل لمجلد"
            " آمن يمكن استرجاعها منه.")
        intro.setWordWrap(True)
        root.addWidget(intro)

        top = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("مسار مجلد الصور المنجزة سابقًا…")
        self.folder_edit.setMinimumHeight(40)
        browse = QPushButton("استعراض…")
        browse.setMinimumSize(120, 40)
        browse.clicked.connect(self._browse)
        top.addWidget(self.folder_edit, 1)
        top.addWidget(browse)
        root.addLayout(top)

        # excel validation source (required for 100% matching, incl. old files)
        excel_row = QHBoxLayout()
        self.excel_edit = QLineEdit()
        self.excel_edit.setPlaceholderText(
            "ملف الإكسل للمطابقة (رقم الصنف + الوحدة الحرفية حبه/شدة/كرتون…)")
        self.excel_edit.setMinimumHeight(40)
        excel_browse = QPushButton("اختيار الإكسل…")
        excel_browse.setMinimumSize(140, 40)
        excel_browse.clicked.connect(self._browse_excel)
        excel_row.addWidget(self.excel_edit, 1)
        excel_row.addWidget(excel_browse)
        root.addLayout(excel_row)

        # ------------------------------------------------- تبويبات الأداة
        self.tabs = QTabWidget()
        self.tabs.setLayoutDirection(Qt.RightToLeft)
        root.addWidget(self.tabs, 1)

        # ==== تبويب 1: إصلاح وتوحيد الأسماء ====
        tab_fix = QWidget()
        fix_lay = QVBoxLayout(tab_fix)
        map_row = QHBoxLayout()
        self.map_edit = QLineEdit()
        self.map_edit.setPlaceholderText(
            "استبدال أرقام (اختياري): قديم=جديد, قديم=جديد  مثال: 10000001=20000001")
        self.map_edit.setMinimumHeight(40)
        map_row.addWidget(self.map_edit, 1)
        preview_btn = QPushButton("معاينة الخطة")
        preview_btn.setMinimumSize(150, 42)
        preview_btn.clicked.connect(self._preview)
        map_row.addWidget(preview_btn)
        fix_lay.addLayout(map_row)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["الاسم الحالي", "الاسم الجديد", "الحالة", "مطابقة الإكسل"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(32)
        fix_lay.addWidget(self.table, 1)

        self.status = QLabel("")
        fix_lay.addWidget(self.status)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.apply_btn = QPushButton("تنفيذ إعادة التسمية")
        self.apply_btn.setMinimumSize(220, 48)
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self._apply)
        btns.addWidget(self.apply_btn)
        fix_lay.addLayout(btns)
        self.tabs.addTab(tab_fix, "إصلاح وتوحيد الأسماء")

        # ==== تبويب 2: تنظيف حسب اللقطة/الوحدة ====
        self.tabs.addTab(self._build_cleanup_tab(), "تنظيف حسب اللقطة/الوحدة")

        # ==== تبويب 3: تصدير بتنسيق المنصات ====
        self.tabs.addTab(self._build_platform_tab(), "تصدير بتنسيق المنصات")

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close_btn = QPushButton("إغلاق")
        close_btn.setMinimumSize(120, 44)
        close_btn.clicked.connect(self.reject)
        bottom.addWidget(close_btn)
        root.addLayout(bottom)

    # ------------------------------------------------ تبويب التنظيف
    def _build_cleanup_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        hint = QLabel(
            "مثال: للإبقاء على الصورة الثانية فقط لكل الأصناف وحذف الباقي:"
            " اختر اللقطة = 2 والوضع = الاحتفاظ بالمطابق فقط. المتبقي يُعاد"
            " ترقيمه تلقائيًا ليصبح غلافًا صحيحًا، والمحذوف ينتقل لمجلد آمن.")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        row = QHBoxLayout()
        row.addWidget(QLabel("رقم اللقطة:"))
        self.cl_seq = QComboBox()
        self.cl_seq.addItem("الكل", None)
        for i in range(1, 11):
            label = "1 — الغلاف (بدون رقم)" if i == 1 else str(i)
            self.cl_seq.addItem(label, i)
        self.cl_seq.setMinimumHeight(38)
        row.addWidget(self.cl_seq)
        row.addWidget(QLabel("الوحدة:"))
        self.cl_unit = QComboBox()
        self.cl_unit.setEditable(True)
        self.cl_unit.addItems(["الكل", "حبه", "شدة", "ربطة", "كرتون", "صنف"])
        self.cl_unit.setMinimumHeight(38)
        row.addWidget(self.cl_unit)
        row.addWidget(QLabel("الوضع:"))
        self.cl_mode = QComboBox()
        self.cl_mode.addItem("الاحتفاظ بالمطابق فقط وحذف بقية صور كل صنف", "keep_only")
        self.cl_mode.addItem("حذف المطابق فقط والإبقاء على الباقي", "delete_only")
        self.cl_mode.setMinimumHeight(38)
        row.addWidget(self.cl_mode, 1)
        lay.addLayout(row)

        row2 = QHBoxLayout()
        self.cl_rename = QCheckBox("إعادة ترقيم المتبقي تلقائيًا (غلاف ثم 2، 3…)")
        self.cl_rename.setChecked(True)
        row2.addWidget(self.cl_rename)
        row2.addWidget(QLabel("تغيير وحدة المتبقي (اختياري):"))
        self.cl_new_unit = QComboBox()
        self.cl_new_unit.setEditable(True)
        self.cl_new_unit.addItems(["بلا تغيير", "حبه", "شدة", "ربطة", "كرتون", "صنف"])
        self.cl_new_unit.setMinimumHeight(38)
        row2.addWidget(self.cl_new_unit)
        self.cl_dups = QCheckBox("دمج التكرارات المتطابقة بالمحتوى أيضًا")
        self.cl_dups.setChecked(True)
        row2.addWidget(self.cl_dups)
        cl_preview = QPushButton("معاينة خطة التنظيف")
        cl_preview.setMinimumSize(170, 42)
        cl_preview.clicked.connect(self._cl_preview)
        row2.addWidget(cl_preview)
        lay.addLayout(row2)

        self.cl_table = QTableWidget()
        self.cl_table.setColumnCount(4)
        self.cl_table.setHorizontalHeaderLabels(
            ["الملف", "الإجراء", "الاسم الجديد", "ملاحظة"])
        self.cl_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.cl_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.cl_table.verticalHeader().setDefaultSectionSize(30)
        lay.addWidget(self.cl_table, 1)

        self.cl_status = QLabel("")
        lay.addWidget(self.cl_status)

        b = QHBoxLayout()
        b.addStretch(1)
        self.cl_apply = QPushButton("تنفيذ التنظيف (المحذوف إلى مجلد آمن)")
        self.cl_apply.setMinimumSize(280, 48)
        self.cl_apply.setEnabled(False)
        self.cl_apply.clicked.connect(self._cl_apply)
        b.addWidget(self.cl_apply)
        lay.addLayout(b)
        return tab

    def _cl_preview(self):
        folder = self.folder_edit.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "تنبيه", "اختر مجلدًا صالحًا أولًا (أعلى النافذة)")
            return
        _ensure_engine_path()
        from engine_v2.cleanup_v2 import plan_cleanup, plan_fix_duplicates
        seq = self.cl_seq.currentData()
        unit_txt = self.cl_unit.currentText().strip()
        unit = "" if unit_txt in ("الكل", "") else unit_txt
        new_unit_txt = self.cl_new_unit.currentText().strip()
        new_unit = "" if new_unit_txt in ("بلا تغيير", "") else new_unit_txt
        mode = self.cl_mode.currentData() or "keep_only"
        if seq is None and not unit and mode == "keep_only" and not self.cl_dups.isChecked():
            QMessageBox.information(
                self, "تنبيه",
                "بلا فلتر لقطة أو وحدة لن يُحذف شيء — حدد رقم لقطة أو وحدة.")
        try:
            if seq is None and not unit and self.cl_dups.isChecked():
                self._cl_plan = plan_fix_duplicates(folder)
            else:
                self._cl_plan = plan_cleanup(
                    folder, seq_filter=seq, unit_filter=unit, mode=mode,
                    rename_survivors=self.cl_rename.isChecked(),
                    new_unit=new_unit)
        except Exception as exc:
            QMessageBox.warning(self, "خطأ", f"تعذر بناء الخطة: {exc}")
            return
        entries = self._cl_plan.entries
        act_ar = {"keep": "يبقى", "delete": "يُحذف",
                  "rename": "يُعاد تسميته", "merge_duplicate": "تكرار — يُدمج"}
        self.cl_table.setRowCount(len(entries))
        for i, e in enumerate(entries):
            self.cl_table.setItem(i, 0, QTableWidgetItem(e.source))
            it = QTableWidgetItem(act_ar.get(e.action, e.action))
            if e.action in ("delete", "merge_duplicate"):
                it.setForeground(QColor("#b00020"))
            elif e.action == "rename":
                it.setForeground(QColor("#0b6e4f"))
            self.cl_table.setItem(i, 1, it)
            self.cl_table.setItem(i, 2, QTableWidgetItem(e.target or "—"))
            self.cl_table.setItem(i, 3, QTableWidgetItem(e.note or ""))
        self.cl_status.setText(
            f"سيبقى {self._cl_plan.n_keep} | سيُحذف {self._cl_plan.n_delete}"
            f" | سيُعاد تسمية {self._cl_plan.n_rename}"
            " — المحذوف ينتقل إلى مجلد آمن داخل المصدر")
        self.cl_apply.setEnabled(
            self._cl_plan.n_delete > 0 or self._cl_plan.n_rename > 0)

    def _cl_apply(self):
        plan = getattr(self, "_cl_plan", None)
        if plan is None:
            return
        if plan.n_delete > 0:
            ok = QMessageBox.question(
                self, "تأكيد",
                f"سيُنقل {plan.n_delete} ملفًا إلى المجلد الآمن وسيُعاد تسمية"
                f" {plan.n_rename}. متابعة؟",
                QMessageBox.Yes | QMessageBox.No)
            if ok != QMessageBox.Yes:
                return
        _ensure_engine_path()
        from engine_v2.cleanup_v2 import apply_plan
        deleted, renamed, errors = apply_plan(plan, to_trash=True)
        if errors:
            QMessageBox.warning(self, "اكتمل مع أخطاء",
                                f"نُقل {deleted} وأُعيد تسمية {renamed}.\n"
                                f"أخطاء: {errors[:5]}")
        else:
            QMessageBox.information(
                self, "تم",
                f"نُقل {deleted} ملفًا للمجلد الآمن وأُعيد تسمية {renamed} بنجاح.")
        self._cl_preview()

    # ------------------------------------------------ تبويب المنصات
    def _build_platform_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        hint = QLabel(
            "يُنشئ نسخة من الصور بأسماء متوافقة مع المنصة المختارة في مجلد"
            " فرعي جديد — ملفاتك الأصلية لا تُمس. المنصات التي لا تدعم"
            " العربية تُنقل الوحدة حرفيًا (حبه → habbah) تلقائيًا.")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        row = QHBoxLayout()
        row.addWidget(QLabel("المنصة:"))
        self.pf_combo = QComboBox()
        _ensure_engine_path()
        from engine_v2.platform_profiles_v2 import PLATFORM_PROFILES
        for key, prof in PLATFORM_PROFILES.items():
            self.pf_combo.addItem(prof.describe(), key)
        self.pf_combo.setMinimumHeight(38)
        self.pf_combo.currentIndexChanged.connect(self._pf_note)
        row.addWidget(self.pf_combo, 1)
        self.pf_template = QLineEdit()
        self.pf_template.setPlaceholderText(
            "القالب اليدوي: مثال {الرقم}-{الوحدة}-{التسلسل}")
        self.pf_template.setMinimumHeight(38)
        self.pf_template.setVisible(False)
        row.addWidget(self.pf_template, 1)
        pf_preview = QPushButton("معاينة الأسماء")
        pf_preview.setMinimumSize(150, 42)
        pf_preview.clicked.connect(self._pf_preview)
        row.addWidget(pf_preview)
        lay.addLayout(row)

        self.pf_note = QLabel("")
        self.pf_note.setWordWrap(True)
        lay.addWidget(self.pf_note)

        self.pf_table = QTableWidget()
        self.pf_table.setColumnCount(2)
        self.pf_table.setHorizontalHeaderLabels(["الاسم الحالي", "اسم المنصة"])
        self.pf_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.pf_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.pf_table.verticalHeader().setDefaultSectionSize(30)
        lay.addWidget(self.pf_table, 1)

        self.pf_status = QLabel("")
        lay.addWidget(self.pf_status)

        b = QHBoxLayout()
        b.addStretch(1)
        self.pf_apply = QPushButton("إنشاء نسخة المنصة")
        self.pf_apply.setMinimumSize(220, 48)
        self.pf_apply.setEnabled(False)
        self.pf_apply.clicked.connect(self._pf_apply)
        b.addWidget(self.pf_apply)
        lay.addLayout(b)
        self._pf_note()
        return tab

    def _pf_note(self):
        _ensure_engine_path()
        from engine_v2.platform_profiles_v2 import PLATFORM_PROFILES
        key = self.pf_combo.currentData()
        prof = PLATFORM_PROFILES.get(key)
        if prof:
            self.pf_note.setText("ℹ " + prof.note_ar)
        self.pf_template.setVisible(key == "custom")

    def _pf_preview(self):
        folder = self.folder_edit.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "تنبيه", "اختر مجلدًا صالحًا أولًا (أعلى النافذة)")
            return
        _ensure_engine_path()
        from engine_v2.cleanup_v2 import scan_folder
        from engine_v2.naming_v2 import unmojibake
        from engine_v2.platform_profiles_v2 import (PLATFORM_PROFILES,
                                                    plan_platform_export,
                                                    render_custom)
        key = self.pf_combo.currentData()
        prof = PLATFORM_PROFILES.get(key)
        files = scan_folder(folder)
        self._pf_files = files
        stems = [unmojibake(p.stem) for p in files]
        if key == "custom":
            tpl = self.pf_template.text().strip() or "{الرقم}_{التسلسل}_{الوحدة}"
            seen: dict[str, int] = {}
            pairs = []
            for stem in stems:
                new = render_custom(stem, tpl)
                if new and new in seen:
                    seen[new] += 1
                    new = f"{new}_{seen[new]}"
                elif new:
                    seen[new] = 1
                pairs.append((stem, new))
            self._pf_pairs = pairs
        else:
            self._pf_pairs = plan_platform_export(stems, prof)
        self.pf_table.setRowCount(len(self._pf_pairs))
        n_ok = 0
        for i, ((old, new), p) in enumerate(zip(self._pf_pairs, files)):
            self.pf_table.setItem(i, 0, QTableWidgetItem(p.name))
            if new:
                self.pf_table.setItem(
                    i, 1, QTableWidgetItem(new + p.suffix.lower()))
                n_ok += 1
            else:
                it = QTableWidgetItem("— اسم غير مفهوم — يُتجاهل")
                it.setForeground(QColor("#b00020"))
                self.pf_table.setItem(i, 1, it)
        self.pf_status.setText(f"جاهز للتصدير: {n_ok} من {len(files)}")
        self.pf_apply.setEnabled(n_ok > 0)

    def _pf_apply(self):
        import shutil
        folder = self.folder_edit.text().strip()
        pairs = getattr(self, "_pf_pairs", None)
        files = getattr(self, "_pf_files", None)
        if not pairs or not files:
            return
        key = self.pf_combo.currentData()
        out_dir = Path(folder) / f"_تصدير_{key}"
        out_dir.mkdir(exist_ok=True)
        n = 0
        errors = []
        for (old, new), p in zip(pairs, files):
            if not new:
                continue
            try:
                shutil.copy2(str(p), str(out_dir / (new + p.suffix.lower())))
                n += 1
            except OSError as exc:
                errors.append(f"{p.name}: {exc}")
        if errors:
            QMessageBox.warning(self, "اكتمل مع أخطاء",
                                f"نُسخ {n} ملفًا.\nأخطاء: {errors[:5]}")
        else:
            QMessageBox.information(
                self, "تم",
                f"نُسخ {n} ملفًا بأسماء {key} إلى:\n{out_dir}")

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "اختر مجلد النتائج السابقة")
        if folder:
            self.folder_edit.setText(folder)

    def _browse_excel(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "اختر ملف الإكسل", "", "Excel (*.xlsx *.xls)")
        if path:
            self.excel_edit.setText(path)

    def _load_catalog(self):
        """Load (and cache) the Excel catalog index for validation."""
        path = self.excel_edit.text().strip()
        if not path:
            # fall back to the main window's already-loaded index
            mw = self.parent()
            idx = getattr(mw, "v2_catalog_index", None) if mw else None
            return idx
        if getattr(self, "_catalog_path", None) == path and getattr(self, "_catalog", None):
            return self._catalog
        if not os.path.isfile(path):
            QMessageBox.warning(self, "تنبيه", "ملف الإكسل غير موجود")
            return None
        _ensure_engine_path()
        from engine_v2.catalog_index_v2 import CatalogIndex
        idx = CatalogIndex()
        idx.load_excel(path)
        self._catalog, self._catalog_path = idx, path
        return idx

    def _validate_against_excel(self, entry, idx):
        """Return (label, ok) checking item code + verbatim unit vs Excel."""
        if idx is None:
            return ("— (لم يُحدد إكسل)", True)
        name = getattr(entry, "target", "") or getattr(entry, "source", "")
        stem = os.path.splitext(name)[0]
        try:
            from engine_v2.naming_v2 import parse_name
            parsed = parse_name(stem)
        except Exception:
            parsed = None
        if not parsed or not getattr(parsed, "item", None):
            return ("اسم غير مفهوم", False)
        code = str(parsed.item)
        unit = (getattr(parsed, "unit", "") or "").strip()
        try:
            units = list(dict.fromkeys(idx.units_for_code(code)))
        except Exception:
            units = []
        if not units:
            return ("الصنف غير موجود في الإكسل", False)
        if unit and unit not in units:
            return (f"وحدة غير مطابقة — المتاح: {'، '.join(units)}", False)
        if not unit:
            return (f"بلا وحدة — المتاح: {'، '.join(units)}", False)
        return ("مطابق ✓", True)

    def _mapping(self) -> dict:
        text = self.map_edit.text().strip()
        mapping = {}
        if text:
            for pair in text.replace("،", ",").split(","):
                if "=" in pair:
                    old, new = pair.split("=", 1)
                    old, new = old.strip(), new.strip()
                    if old and new:
                        mapping[old] = new
        return mapping

    def _preview(self):
        folder = self.folder_edit.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "تنبيه", "اختر مجلدًا صالحًا أولًا")
            return
        _ensure_engine_path()
        from engine_v2.naming_v2 import plan_bulk_rename
        self._folder = folder
        self._plan = plan_bulk_rename(folder, self._mapping())
        idx = self._load_catalog()
        self.table.setRowCount(len(self._plan))
        counts = {"ok": 0, "unchanged": 0, "unparsed": 0, "conflict": 0}
        excel_bad = 0
        status_ar = {"ok": "سيُعاد تسميته", "unchanged": "بدون تغيير",
                     "unparsed": "اسم غير مفهوم — يُتجاهل", "conflict": "تعارض!"}
        for i, entry in enumerate(self._plan):
            self.table.setItem(i, 0, QTableWidgetItem(entry.source))
            self.table.setItem(i, 1, QTableWidgetItem(entry.target or "—"))
            self.table.setItem(i, 2, QTableWidgetItem(status_ar.get(entry.status, entry.status)))
            label, ok = self._validate_against_excel(entry, idx)
            cell = QTableWidgetItem(label)
            if not ok:
                cell.setForeground(QColor("#b00020"))
                excel_bad += 1
                entry.status = "excel_mismatch" if entry.status == "ok" else entry.status
            self.table.setItem(i, 3, cell)
            counts[entry.status] = counts.get(entry.status, 0) + 1
        self.status.setText(
            f"سيُعاد تسمية {counts.get('ok', 0)} | بدون تغيير {counts.get('unchanged', 0)}"
            f" | غير مفهوم {counts.get('unparsed', 0)} | تعارض {counts.get('conflict', 0)}"
            f" | غير مطابق للإكسل {excel_bad}")
        self.apply_btn.setEnabled(counts.get("ok", 0) > 0 and counts.get("conflict", 0) == 0)

    def _apply(self):
        _ensure_engine_path()
        from engine_v2.naming_v2 import apply_bulk_rename
        applied, errors = apply_bulk_rename(self._folder, self._plan)
        if errors:
            QMessageBox.warning(self, "اكتمل مع أخطاء",
                                f"أعيدت تسمية {applied} ملفًا.\nأخطاء: {errors[:5]}")
        else:
            QMessageBox.information(self, "تم", f"أعيدت تسمية {applied} ملفًا بنجاح.")
        self._preview()


# ========================================================== session dialog
class SessionDialog(QDialog):
    """Resume a previous session or start fresh."""

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.setWindowTitle("استئناف العمل — الجلسات المحفوظة")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumSize(860, 520)
        self.store = store
        self.selected_session_id: str | None = None
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.addWidget(QLabel("اختر جلسة سابقة لاستئناف العمل من حيث توقفت، أو ابدأ جلسة جديدة:"))

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["آخر تحديث", "مجلد الصور", "الإجمالي", "المكتمل"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(34)
        root.addWidget(self.table, 1)

        sessions = store.list_sessions()
        import datetime
        self.table.setRowCount(len(sessions))
        self._sessions = sessions
        for i, s in enumerate(sessions):
            dt = datetime.datetime.fromtimestamp(s["updated_at"]).strftime("%Y-%m-%d %H:%M")
            self.table.setItem(i, 0, QTableWidgetItem(dt))
            self.table.setItem(i, 1, QTableWidgetItem(s["source_folder"]))
            self.table.setItem(i, 2, QTableWidgetItem(str(s["total"])))
            self.table.setItem(i, 3, QTableWidgetItem(str(s["done"])))
        self.table.doubleClicked.connect(self._resume)

        btns = QHBoxLayout()
        btns.addStretch(1)
        resume_btn = QPushButton("استئناف الجلسة المحددة")
        resume_btn.setMinimumSize(210, 48)
        resume_btn.clicked.connect(self._resume)
        new_btn = QPushButton("جلسة جديدة")
        new_btn.setMinimumSize(150, 48)
        new_btn.clicked.connect(self.reject)
        btns.addWidget(resume_btn)
        btns.addWidget(new_btn)
        root.addLayout(btns)

    def _resume(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._sessions):
            QMessageBox.information(self, "تنبيه", "حدد جلسة من الجدول أولًا")
            return
        self.selected_session_id = self._sessions[row]["session_id"]
        self.accept()


# ============================================================ installation
def install_v2(main_window, data_root: Path) -> None:
    """Wire V2 features into the legacy MainWindow after it is built."""
    _ensure_engine_path()

    # 1) larger, overlap-free window (matches the layout the app is tuned for;
    #    prevents shrinking below the size where controls would overlap)
    main_window.setMinimumSize(1180, 760)
    if main_window.width() < 1280 or main_window.height() < 800:
        main_window.resize(max(main_window.width(), 1280),
                           max(main_window.height(), 800))

    # 2) touch-ups only for V2 buttons; the legacy stylesheet already sizes
    #    its own controls, a global min-height would break compact rows
    main_window.setStyleSheet(main_window.styleSheet() + """
        QPushButton#v2RenameBtn, QPushButton#v2SessionsBtn,
        QPushButton#v2SaveNowBtn, QPushButton#v2NamingBtn,
        QPushButton#v2HelpBtn {
            padding: 4px 14px; font-weight: 700;
            background: #16375e; color: #e8f2ff;
            border: 1px solid #3f6da0; border-radius: 8px;
        }
        QPushButton#v2RenameBtn:hover, QPushButton#v2SessionsBtn:hover,
        QPushButton#v2SaveNowBtn:hover, QPushButton#v2NamingBtn:hover,
        QPushButton#v2HelpBtn:hover {
            background: #1d4a7e; border-color: #5b9bd0;
        }
        QPushButton#v2EditorBtn {
            padding: 4px 14px; font-weight: 800;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #3b2575, stop:1 #5636a8);
            color: #ffffff; border: 1px solid #6d4fc4; border-radius: 8px;
        }
        QPushButton#v2EditorBtn:hover { background: #4a2d92; }
        QPushButton#v2RefineBtn {
            padding: 4px 14px; font-weight: 800;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #0b5e4c, stop:1 #0f8a67);
            color: #ffffff; border: 1px solid #23a37e; border-radius: 8px;
        }
        QPushButton#v2RefineBtn:hover { background: #0d7157; }
        QPushButton#v2NutritionBtn {
            background: #fff4e0; color: #8a4b00;
            border: 1px solid #e0ae3f; border-radius: 7px;
            font-weight: 800; padding: 6px 12px;
        }
        QPushButton#v2NutritionBtn:hover { background: #ffe9c2; }
    """)

    # 3) session store
    from engine_v2.session_v2 import SessionStore
    main_window.v2_session_store = SessionStore(data_root / "SessionsV2")

    # 4) toolbar-style buttons appended to the header row if present
    def open_rename_tool():
        dlg = BulkRenameDialog(main_window)
        dlg.exec()

    def open_sessions():
        dlg = SessionDialog(main_window.v2_session_store, main_window)
        if dlg.exec() == QDialog.Accepted and dlg.selected_session_id:
            state = main_window.v2_session_store.load(dlg.selected_session_id)
            restore = getattr(main_window, "v2_restore_session", None)
            if callable(restore):
                restore(state)

    main_window.v2_open_rename_tool = open_rename_tool
    main_window.v2_open_sessions = open_sessions

    # 5) real save/resume wiring — captures the review & linking state of the
    #    legacy window and restores it, so work can continue after a restart.
    def _capture_state() -> dict:
        state: dict = {"version": "2.0.0"}
        try:
            catalog = getattr(main_window, "catalog_edit", None)
            state["catalog_path"] = (catalog.toolTip() or catalog.text()) if catalog else ""
            result = getattr(main_window, "current_result", None)
            if result is not None:
                items = []
                for it in getattr(result, "items", []):
                    items.append({
                        "source_path": getattr(it, "source_path", ""),
                        "source_name": getattr(it, "source_name", ""),
                        "status": getattr(it, "status", ""),
                        "item_code": getattr(it, "item_code", ""),
                        "product_name": getattr(it, "product_name", ""),
                        "barcode": getattr(it, "barcode", ""),
                        "explanation": getattr(it, "explanation", ""),
                        "review_path": getattr(it, "review_path", ""),
                    })
                state["items"] = items
                state["workspace"] = getattr(result, "workspace", "")
            table = getattr(main_window, "results_table", None)
            state["current_row"] = table.currentRow() if table else -1
        except Exception:
            pass
        return state

    def v2_save_session(name: str = "") -> str:
        from engine_v2.session_v2 import SessionState
        store = main_window.v2_session_store
        snap = _capture_state()
        if store.state is None:
            import uuid, time as _t
            store.state = SessionState(session_id=uuid.uuid4().hex[:12],
                                       created_at=_t.time(),
                                       updated_at=_t.time())
        store.state.excel_path = snap.get("catalog_path", "")
        store.state.output_folder = snap.get("workspace", "")
        store.state.current_position = int(snap.get("current_row", 0) or 0)
        for d in snap.get("items", []):
            key = d.get("source_name") or d.get("source_path")
            if not key:
                continue
            store.upsert_image(
                key,
                source_path=d.get("source_path", ""),
                status=d.get("status", "pending"),
                barcode=d.get("barcode", ""),
                item_code=d.get("item_code", ""),
                item_name=d.get("product_name", ""),
                output_path=d.get("review_path", ""),
                error=d.get("explanation", ""),
            )
        store.save(force=True)
        return store.state.session_id

    def v2_restore_session(state) -> None:
        try:
            if hasattr(state, "images"):  # SessionState object
                items_data = [
                    {
                        "source_path": img.source_path,
                        "source_name": key if "." in key else Path(img.source_path).name,
                        "status": img.status or "review",
                        "item_code": img.item_code,
                        "product_name": img.item_name,
                        "barcode": img.barcode,
                        "explanation": img.error,
                        "review_path": img.output_path or img.source_path,
                    }
                    for key, img in state.images.items()
                ]
                state = {
                    "items": items_data,
                    "workspace": state.output_folder,
                    "current_row": state.current_position,
                }
            items_data = state.get("items") or []
            if not items_data:
                return
            import native_app as _na
            items = [
                _na.BatchItemResult(
                    source_path=d.get("source_path", ""),
                    source_name=d.get("source_name", ""),
                    status=d.get("status", "review"),
                    item_code=d.get("item_code", ""),
                    product_name=d.get("product_name", ""),
                    barcode=d.get("barcode", ""),
                    explanation=d.get("explanation", ""),
                    review_path=d.get("review_path", ""),
                )
                for d in items_data
            ]
            result = _na.BatchRunResult(
                workspace=state.get("workspace", ""),
                database_path="",
                catalog_summary={},
                items=items,
                elapsed_ms=0.0,
                delivery_zip="",
                report_json="",
                report_csv="",
            )
            main_window.current_result = result
            if state.get("workspace"):
                main_window.current_workspace = Path(state["workspace"])
            row = int(state.get("current_row", -1))
            restore_pos = None
            if 0 <= row < len(items):
                restore_pos = (items[row].source_name, row, 0)
            main_window._populate_results(restore_position=restore_pos)
            main_window._show_results_page()
            # guaranteed row restore: legacy _populate_results may re-select
            # row 0 via deferred handlers, so re-apply the selection after
            # the event queue settles.
            if restore_pos is not None:
                from PySide6.QtCore import QTimer

                def _reselect(row=restore_pos[1]):
                    try:
                        table = getattr(main_window, "results_table", None)
                        if table is not None and 0 <= row < table.rowCount():
                            from PySide6.QtCore import QItemSelectionModel
                            idx = table.model().index(row, 0)
                            table.selectionModel().setCurrentIndex(
                                idx,
                                QItemSelectionModel.ClearAndSelect
                                | QItemSelectionModel.Rows,
                            )
                            table.scrollToItem(table.item(row, 0))
                    except Exception:
                        pass

                QTimer.singleShot(0, _reselect)
                QTimer.singleShot(120, _reselect)
        except Exception as exc:  # pragma: no cover
            QMessageBox.warning(main_window, "استئناف الجلسة",
                                f"تعذر استئناف الجلسة بالكامل: {exc}")

    main_window.v2_capture_state = _capture_state
    main_window.v2_save_session = v2_save_session
    main_window.v2_restore_session = v2_restore_session

    # auto-save every 3 minutes while results exist
    from PySide6.QtCore import QTimer

    def _auto_save():
        try:
            if getattr(main_window, "current_result", None) is not None:
                v2_save_session()
        except Exception:
            pass

    timer = QTimer(main_window)
    timer.setInterval(3 * 60 * 1000)
    timer.timeout.connect(_auto_save)
    timer.start()
    main_window._v2_autosave_timer = timer

    # 6) unit & bulk naming policy (حبه/شدة/كرتون — verbatim from Excel)
    main_window.v2_data_root = data_root
    _install_unit_naming(main_window)


# ==================================================== unit naming (V2.0)
class UnitNamingDialog(QDialog):
    """Global unit & naming policy dialog.

    Lets the user decide once — for ALL items — how units (حبه/شدة/كرتون…,
    verbatim from the Excel file) are applied to file names, including
    replicating one image to every unit of the item, and a one-click
    "apply template to all" bulk naming action. Every name remains editable
    later (per image or via the external rename tool).
    """

    def __init__(self, main_window, parent=None):
        super().__init__(parent or main_window)
        self._mw = main_window
        self.setWindowTitle("سياسة الوحدات والتسمية الموحدة — V2")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumSize(720, 520)
        root = QVBoxLayout(self)
        root.setSpacing(14)

        intro = QLabel(
            "تُقرأ الوحدة حرفيًا من ملف الإكسل (حبه/حبة/شدة/شده/كرتون/باكت...) دون أي تعديل.\n"
            "اختر سياسة موحدة تُطبق على جميع الأصناف، مع إمكانية تعديل أي مسمى لاحقًا."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        pol_box = QGroupBox("سياسة الوحدات للأصناف متعددة الوحدات")
        pol_lay = QVBoxLayout(pol_box)
        self.rb_per_image = QRadioButton("اسألني لكل صورة (اختيار الوحدة يدويًا عند الربط)")
        self.rb_replicate = QRadioButton("توليد نسخة لكل وحدة تلقائيًا من نفس الصورة (حبه + شدة + كرتون...)")
        self.rb_default = QRadioButton("اعتماد وحدة افتراضية واحدة:")
        self.rb_free = QRadioButton("وضع حر — بلا وحدات ولا إكسل (اسم الملف كما أكتبه بنفسي)")
        default_row = QHBoxLayout()
        self.default_unit_combo = QComboBox()
        self.default_unit_combo.setMinimumWidth(180)
        default_row.addWidget(self.rb_default)
        default_row.addWidget(self.default_unit_combo)
        default_row.addStretch(1)
        pol_lay.addWidget(self.rb_per_image)
        pol_lay.addWidget(self.rb_replicate)
        pol_lay.addLayout(default_row)
        pol_lay.addWidget(self.rb_free)
        root.addWidget(pol_box)

        tpl_box = QGroupBox("قالب التسمية الموحد (تطبيق على الكل بنقرة واحدة)")
        tpl_lay = QFormLayout(tpl_box)
        self.template_edit = QLineEdit("{item}_{seq}_{unit}")
        self.template_edit.setToolTip(
            "{item}=رقم الصنف، {seq}=التسلسل (يُحذف للصورة الأولى)، {unit}=الوحدة الحرفية من الإكسل"
        )
        tpl_lay.addRow("القالب:", self.template_edit)
        self.preview_lbl = QLabel("")
        self.preview_lbl.setStyleSheet("color:#2c5aa0; font-weight:600;")
        tpl_lay.addRow("معاينة:", self.preview_lbl)
        root.addWidget(tpl_box)

        self.template_edit.textChanged.connect(self._update_preview)

        btns = QHBoxLayout()
        btns.addStretch(1)
        apply_all_btn = QPushButton("تطبيق التسمية على جميع الصور الآن")
        apply_all_btn.setObjectName("v2ApplyAllBtn")
        apply_all_btn.setMinimumSize(260, 48)
        apply_all_btn.clicked.connect(self._apply_all)
        save_btn = QPushButton("حفظ السياسة")
        save_btn.setMinimumSize(150, 48)
        save_btn.clicked.connect(self._save_policy)
        cancel_btn = QPushButton("إغلاق")
        cancel_btn.setMinimumSize(120, 48)
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(apply_all_btn)
        btns.addWidget(save_btn)
        btns.addWidget(cancel_btn)
        root.addLayout(btns)

        self._load_units()
        self._load_policy()
        self._update_preview()

    # -------------------------------------------------------------- helpers
    def _settings_path(self) -> Path:
        base = getattr(self._mw, "v2_data_root", None) or Path.home() / ".market_image_studio_v2"
        base = Path(base)
        base.mkdir(parents=True, exist_ok=True)
        return base / "naming_settings.json"

    def _load_units(self):
        units = []
        idx = getattr(self._mw, "v2_catalog_index", None)
        if idx is not None:
            try:
                seen = {}
                for rows in idx.by_code_all.values():
                    for r in rows:
                        u = (r.unit or "").strip()
                        if u:
                            seen[u] = seen.get(u, 0) + 1
                units = [u for u, _ in sorted(seen.items(), key=lambda kv: -kv[1])]
            except Exception:
                units = []
        if not units:
            units = ["حبه", "شده", "كرتون"]
        self.default_unit_combo.addItems(units)

    def _load_policy(self):
        try:
            data = json.loads(self._settings_path().read_text(encoding="utf-8"))
        except Exception:
            data = {}
        pol = data.get("unit_policy", "per_image")
        {"per_image": self.rb_per_image,
         "replicate_all_units": self.rb_replicate,
         "default_unit": self.rb_default,
         "free": self.rb_free}.get(pol, self.rb_per_image).setChecked(True)
        if data.get("default_unit"):
            i = self.default_unit_combo.findText(data["default_unit"])
            if i >= 0:
                self.default_unit_combo.setCurrentIndex(i)
        if data.get("template"):
            self.template_edit.setText(data["template"])

    def current_policy(self) -> dict:
        pol = ("replicate_all_units" if self.rb_replicate.isChecked()
               else "default_unit" if self.rb_default.isChecked()
               else "free" if self.rb_free.isChecked()
               else "per_image")
        return {
            "unit_policy": pol,
            "default_unit": self.default_unit_combo.currentText(),
            "template": self.template_edit.text().strip() or "{item}_{seq}_{unit}",
        }

    def _update_preview(self):
        tpl = self.template_edit.text().strip() or "{item}_{seq}_{unit}"
        try:
            first = tpl.replace("_{seq}", "").replace("{seq}", "").format(
                item="10014649", unit="حبه", seq="")
            second = tpl.format(item="10014649", seq="2", unit="حبه")
            self.preview_lbl.setText(f"{first}.webp   ،   {second}.webp")
        except Exception:
            self.preview_lbl.setText("قالب غير صالح — استخدم {item} و{seq} و{unit}")

    def _save_policy(self):
        data = self.current_policy()
        self._settings_path().write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self._mw.v2_naming_policy = data
        QMessageBox.information(self, "تم", "حُفظت سياسة الوحدات والتسمية وستُطبق على جميع الأصناف.")

    def _apply_all(self):
        data = self.current_policy()
        self._settings_path().write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self._mw.v2_naming_policy = data
        result = getattr(self._mw, "current_result", None)
        if result is None or not getattr(result, "items", None):
            QMessageBox.information(self, "تنبيه", "لا توجد نتائج حالية — حُفظت السياسة وستُطبق عند المعالجة.")
            return
        try:
            from engine_v2.naming_v2 import (
                NamingSettings, plan_names_for_item)
            settings = NamingSettings(
                unit_policy=data["unit_policy"],
                default_unit=data["default_unit"],
                template=data["template"],
            )
            idx = getattr(self._mw, "v2_catalog_index", None)
            groups: dict = {}
            for it in result.items:
                code = getattr(it, "item_code", "") or ""
                if code:
                    groups.setdefault(code, []).append(it)
            renamed = 0
            for code, its in groups.items():
                units = []
                if idx is not None:
                    try:
                        units = list(dict.fromkeys(idx.units_for_code(code)))
                    except Exception:
                        units = []
                plan = plan_names_for_item(code, len(its), units, settings)
                flat = []
                if isinstance(plan, dict):
                    unit0 = next(iter(plan)) if plan else None
                    flat = plan.get(unit0, []) if unit0 else []
                else:
                    flat = list(plan)
                for i, it in enumerate(its):
                    if i < len(flat):
                        setattr(it, "v2_final_name", flat[i])
                        renamed += 1
            self._mw.v2_bulk_plan = {"policy": data, "count": renamed}
            QMessageBox.information(
                self, "اكتمل",
                f"طُبق قالب التسمية الموحد على {renamed} صورة.\n"
                "يمكن تعديل أي مسمى لاحقًا من المحرر أو أداة إعادة التسمية.")
        except Exception as exc:
            QMessageBox.warning(self, "خطأ", f"تعذر تطبيق التسمية الجماعية: {exc}")


def _install_unit_naming(main_window) -> None:
    """Expose the unit-naming dialog on the main window."""
    def open_unit_naming():
        dlg = UnitNamingDialog(main_window)
        dlg.exec()
    main_window.v2_open_unit_naming = open_unit_naming
    # preload saved policy
    try:
        base = getattr(main_window, "v2_data_root", None) or Path.home() / ".market_image_studio_v2"
        p = Path(base) / "naming_settings.json"
        if p.exists():
            main_window.v2_naming_policy = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass


# ============================================== batch refine (V2.0) UI
class _BatchRefineWorker(QThread):
    """خيط خلفي للمعالجة الجماعية حتى لا تتجمد الواجهة."""
    progress = Signal(int, int, str, str)   # i, total, status, name
    finished_run = Signal(int, int, float)  # done, errors, elapsed

    def __init__(self, src, dst, options, models_dir, parent=None):
        super().__init__(parent)
        self._src, self._dst = src, dst
        self._opts = options
        self._models = models_dir
        self._stop = False

    def request_stop(self):
        self._stop = True

    def run(self):
        import time as _t
        _ensure_engine_path()
        from engine_v2.batch_refine_v2 import BatchRefiner
        refiner = BatchRefiner(self._models, self._opts)
        t0 = _t.time()
        done = err = 0

        def cb(i, total, r):
            nonlocal done, err
            if r.status == "done":
                done += 1
            elif r.status == "error":
                err += 1
            self.progress.emit(i, total, r.status,
                               r.new_name or os.path.basename(r.source))
            if self._stop:
                refiner.request_stop()

        try:
            refiner.run(self._src, self._dst, progress=cb)
        except Exception as exc:  # pragma: no cover
            self.progress.emit(0, 0, "error", str(exc))
        self.finished_run.emit(done, err, _t.time() - t0)


class BatchRefineDialog(QDialog):
    """أداة الضبط التلقائي الجماعي للصور القديمة (1000+ دفعة واحدة).

    تعيد معالجة مجلد نتائج قديم كاملًا بمحرك V2: قص نظيف، تحسين تلقائي,
    تأطير موحد 800×700، ظل اختياري، وتصحيح الأسماء من ملف الإكسل
    (الوحدات الحرفية حبه/شده/كرتون) مع الحفاظ على الترابط، مع استئناف
    تلقائي — الملفات المنجزة سابقًا تُتخطى.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ضبط الصور القديمة تلقائيًا — V2")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumSize(760, 620)
        self._worker = None
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(22, 18, 22, 18)

        intro = QLabel(
            "يستقبل أي مجلد صور بأي مسميات وأي صيغة (WebP/PNG/JPG…) ويضبطها "
            "دفعة واحدة (1000+ صورة): قص نظيف بلا هالات، تحسين تلقائي، "
            "تأطير موحد 800×700. تصحيح الأسماء والوحدات (حبه/شده/كرتون) من "
            "ملف إكسل تختاره بنفسك — وإن لم تحدد إكسل تُحفظ الأسماء الأصلية كما هي "
            "(وضع حر).")
        intro.setWordWrap(True)
        root.addWidget(intro)

        form = QFormLayout()
        # source folder
        src_row = QHBoxLayout()
        self.src_edit = QLineEdit()
        self.src_edit.setPlaceholderText("مجلد الصور القديمة...")
        src_btn = QPushButton("اختيار")
        src_btn.clicked.connect(lambda: self._pick_dir(self.src_edit))
        src_row.addWidget(self.src_edit, 1)
        src_row.addWidget(src_btn)
        form.addRow("مجلد المصدر:", src_row)
        # destination folder
        dst_row = QHBoxLayout()
        self.dst_edit = QLineEdit()
        self.dst_edit.setPlaceholderText("مجلد الحفظ (يُنشأ تلقائيًا)...")
        dst_btn = QPushButton("اختيار")
        dst_btn.clicked.connect(lambda: self._pick_dir(self.dst_edit))
        dst_row.addWidget(self.dst_edit, 1)
        dst_row.addWidget(dst_btn)
        form.addRow("مجلد الحفظ:", dst_row)
        # excel
        xls_row = QHBoxLayout()
        self.xls_edit = QLineEdit()
        self.xls_edit.setPlaceholderText(
            "أي ملف إكسل تختاره لتصحيح الأسماء (اختياري — بدونه تُحفظ الأسماء كما هي)")
        xls_btn = QPushButton("اختيار")
        xls_btn.clicked.connect(self._pick_excel)
        xls_row.addWidget(self.xls_edit, 1)
        xls_row.addWidget(xls_btn)
        form.addRow("ملف الإكسل:", xls_row)
        root.addLayout(form)

        opts_box = QGroupBox("خيارات الضبط")
        opts = QGridLayout(opts_box)
        from PySide6.QtWidgets import QCheckBox
        self.chk_recut = QCheckBox("إعادة القص الذكي (إزالة الخلفية والهالات)")
        self.chk_recut.setChecked(True)
        self.chk_enhance = QCheckBox("تحسين تلقائي (إضاءة/ألوان/حدة)")
        self.chk_enhance.setChecked(True)
        self.chk_frame = QCheckBox("تأطير موحد 800×700 خلفية بيضاء")
        self.chk_frame.setChecked(True)
        self.chk_names = QCheckBox("تصحيح الأسماء والوحدات من الإكسل (عند تحديد ملف)")
        self.chk_names.setChecked(True)
        self.chk_recursive = QCheckBox("شمول المجلدات الفرعية داخل المصدر")
        self.chk_recursive.setChecked(False)
        self.chk_compress = QCheckBox("ضغط الملفات (حجم أصغر بجودة عالية جدًا)")
        self.chk_compress.setChecked(False)
        self.chk_compress.setToolTip(
            "يصغّر حجم الملفات للرفع السريع للمواقع مع جودة عالية جدًا تحافظ"
            " على وضوح تفاصيل وحقائق المنتج. بدونه: جودة كاملة بلا فقدان.")
        self.chk_polish = QCheckBox("تنقيح استوديو نهائي للتسليم (لمعة متجر)")
        self.chk_polish.setChecked(False)
        self.chk_polish.setToolTip(
            "يعيد فحص كل صورة: حواف نظيفة بلا أطر داكنة، توازن أبيض، إضاءة"
            " استوديو ناعمة وألوان نضرة — مظهر تصوير استوديو للمتجر.")
        self.chk_text_aware = QCheckBox("وضوح فائق للكتابات (ذكي)")
        self.chk_text_aware.setChecked(True)
        self.chk_text_aware.setToolTip(
            "محرك حدة ذكي يتعرف على كتابات المنتج والحقائق الغذائية"
            " ويحافظ على وضوحها التام أثناء التأطير والتحسين.")
        self.chk_blur_dates = QCheckBox("طمس تواريخ الإنتاج/الانتهاء تلقائيًا")
        self.chk_blur_dates.setChecked(True)
        self.chk_blur_dates.setToolTip(
            "يكشف التواريخ المطبوعة على العبوة ويطمسها بتمويه طفيف بلون"
            " المنتج نفسه — دون المساس بالحقائق الغذائية أو الباركود.")
        self.shadow_combo = QComboBox()
        self.shadow_combo.addItems(["بدون ظل", "ظل أرضي ناعم", "ظل أرضي قوي",
                                    "ظل مسقط يمين", "ظل مسقط يسار",
                                    "ظل استوديو 3D"])
        self.fmt_combo = QComboBox()
        self.fmt_combo.addItems(["WebP — الأفضل للمتاجر (موصى به)",
                                 "JPG — التوافق الأوسع مع كل المواقع",
                                 "PNG — جودة كاملة بلا فقدان"])
        self.fmt_combo.setToolTip(
            "صيغة واحدة فقط للإخراج النهائي — اختر الأنسب لموقعك.")
        opts.addWidget(self.chk_recut, 0, 0)
        opts.addWidget(self.chk_enhance, 0, 1)
        opts.addWidget(self.chk_frame, 1, 0)
        opts.addWidget(self.chk_names, 1, 1)
        opts.addWidget(self.chk_recursive, 2, 0)
        opts.addWidget(self.chk_compress, 2, 1)
        opts.addWidget(self.chk_polish, 3, 0)
        opts.addWidget(self.chk_text_aware, 3, 1)
        opts.addWidget(self.chk_blur_dates, 4, 0)
        opts.addWidget(QLabel("الظل:"), 5, 0)
        opts.addWidget(self.shadow_combo, 5, 1)
        opts.addWidget(QLabel("صيغة الإخراج:"), 6, 0)
        opts.addWidget(self.fmt_combo, 6, 1)
        root.addWidget(opts_box)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimumHeight(30)
        self.progress_bar.setAlignment(Qt.AlignCenter)
        root.addWidget(self.progress_bar)
        self.status_lbl = QLabel("جاهز — اختر المجلدات ثم ابدأ.")
        self.status_lbl.setWordWrap(True)
        root.addWidget(self.status_lbl)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.start_btn = QPushButton("بدء الضبط الجماعي")
        self.start_btn.setMinimumSize(220, 48)
        self.start_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton("إيقاف")
        self.stop_btn.setMinimumSize(120, 48)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        close_btn = QPushButton("إغلاق")
        close_btn.setMinimumSize(120, 48)
        close_btn.clicked.connect(self.reject)
        btns.addWidget(self.start_btn)
        btns.addWidget(self.stop_btn)
        btns.addWidget(close_btn)
        root.addLayout(btns)

    # ---------------------------------------------------------------- picks
    def _pick_dir(self, edit):
        d = QFileDialog.getExistingDirectory(self, "اختر مجلدًا")
        if d:
            edit.setText(d)
            if edit is self.src_edit and not self.dst_edit.text().strip():
                self.dst_edit.setText(str(Path(d).parent / (Path(d).name + "_مضبوطة")))

    def _pick_excel(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "اختر ملف الإكسل", "", "Excel (*.xlsx *.xls)")
        if f:
            self.xls_edit.setText(f)

    # ---------------------------------------------------------------- run
    def _start(self):
        src = self.src_edit.text().strip()
        dst = self.dst_edit.text().strip()
        if not src or not Path(src).is_dir():
            QMessageBox.information(self, "تنبيه", "اختر مجلد المصدر أولًا.")
            return
        if not dst:
            QMessageBox.information(self, "تنبيه", "حدد مجلد الحفظ.")
            return
        _ensure_engine_path()
        from engine_v2.batch_refine_v2 import RefineOptions
        shadow_map = {0: "", 1: "soft_ground", 2: "strong_ground",
                      3: "cast_right", 4: "cast_left", 5: "studio_3d"}
        # إعدادات المالك إن وُجدت (workers)
        workers = 2
        try:
            import license_ui
            workers = int(license_ui.load_owner_settings()
                          .get("batch_workers", 2))
        except Exception:
            pass
        fmt_map = {0: "webp", 1: "jpg", 2: "png"}
        opts = RefineOptions(
            recut=self.chk_recut.isChecked(),
            enhance=self.chk_enhance.isChecked(),
            frame=self.chk_frame.isChecked(),
            shadow_preset=shadow_map.get(self.shadow_combo.currentIndex(), ""),
            fix_names=self.chk_names.isChecked(),
            excel_path=self.xls_edit.text().strip(),
            recursive=self.chk_recursive.isChecked(),
            workers=workers,
            compress=self.chk_compress.isChecked(),
            out_format=fmt_map.get(self.fmt_combo.currentIndex(), "webp"),
            polish=self.chk_polish.isChecked(),
            text_aware=self.chk_text_aware.isChecked(),
            blur_dates=self.chk_blur_dates.isChecked(),
        )
        from engine_v2.paths_v2 import models_dir as _models_dir
        models_dir = _models_dir()
        self._worker = _BatchRefineWorker(src, dst, opts, models_dir, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_run.connect(self._on_finished)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_lbl.setText("جارٍ الضبط الجماعي... (المنجز سابقًا يُتخطى تلقائيًا)")
        self._worker.start()

    def _stop(self):
        if self._worker:
            self._worker.request_stop()
            self.status_lbl.setText("جارٍ الإيقاف بعد الصورة الحالية... "
                                    "يمكنك الاستئناف لاحقًا من نفس المجلدين.")

    def _on_progress(self, i, total, status, name):
        if total:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(i)
        self.status_lbl.setText(f"{i}/{total} — {name} ({status})")

    def _on_finished(self, done, errors, elapsed):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        speed = f"{elapsed / max(1, done):.2f} ث/صورة" if done else "—"
        QMessageBox.information(
            self, "اكتمل الضبط الجماعي",
            f"تم ضبط {done} صورة بنجاح، أخطاء: {errors}.\n"
            f"الزمن: {elapsed:.0f} ثانية ({speed}).\n"
            "الملفات المنجزة تُتخطى تلقائيًا عند إعادة التشغيل (استئناف).")
        self.status_lbl.setText(f"اكتمل: {done} صورة، أخطاء: {errors}.")
