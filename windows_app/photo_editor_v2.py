# -*- coding: utf-8 -*-
"""محرر الصور الاحترافي للمتاجر — V2.0.

محرر بثلاثة أوضاع عمل حقيقية:
- ذكي:   إزالة خلفية ISNet بنقرة، تحسين تلقائي، توسيط وتأطير، ظل واقعي 3D.
- يدوي:  قلم تبييض/استرجاع، اقتصاص حر، منزلقات (إضاءة/تباين/حدة/تشبع/ضوضاء).
- دمج:   انتقائي بالمناطق — عزل منطقة (فرشاة أو مستطيل) وتطبيق أي أداة
         ذكية أو يدوية عليها فقط مع feathering ناعم.

المعمارية غير هدّامة: الأصل محفوظ دائمًا + طبقات (ذكية/يدوية/قناع منطقة/ظل)
يعاد تركيبها عند كل تغيير، مع undo/redo ومعاينة قبل/بعد لحظية.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np

from PySide6.QtCore import Qt, QPoint, QPointF, QRectF, QThread, Signal, QTimer
from PySide6.QtGui import (
    QColor,
    QCursor,
    QImage,
    QPainter,
    QPen,
    QPixmap,
    QBrush,
    QIcon,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


def _ensure_engine_path() -> None:
    src = Path(__file__).resolve().parent.parent / "src"
    p = str(src)
    if p not in sys.path:
        sys.path.insert(0, p)


_ensure_engine_path()


def _np_bgr_to_qimage(img: np.ndarray) -> QImage:
    import cv2
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 4:
        rgba = cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
        h, w = rgba.shape[:2]
        return QImage(rgba.data, w, h, w * 4, QImage.Format_RGBA8888).copy()
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888).copy()


def _read_any(path: str) -> np.ndarray | None:
    import cv2
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
        if img is None:
            return None
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        if img.shape[2] == 4:
            # ركب على أبيض واحتفظ بالألفا جانبًا؟ المحرر يبدأ من BGR
            a = img[:, :, 3:4].astype(np.float32) / 255.0
            rgb = img[:, :, :3].astype(np.float32)
            img = (rgb * a + 255.0 * (1 - a)).astype(np.uint8)
        return img
    except Exception:
        return None


# ============================================================ canvas widget
class EditorCanvas(QGraphicsView):
    """لوحة العرض: زووم بعجلة الماوس نحو المؤشر، تحريك بالسحب،
    ورسم فرشاة (تبييض/استرجاع/تحديد منطقة) فوق الصورة."""

    brush_stroke = Signal(list, int, str)   # نقاط بإحداثيات الصورة، الحجم، الأداة
    zoom_changed = Signal(float)

    TOOL_PAN = "pan"
    TOOL_ERASE = "erase"      # قلم التبييض (يمسح للخلفية البيضاء)
    TOOL_RESTORE = "restore"  # استرجاع من الأصل
    TOOL_REGION = "region"    # فرشاة تحديد منطقة العزل
    TOOL_REGION_RECT = "region_rect"  # مستطيل تحديد منطقة
    TOOL_DATE_BLUR = "date_blur"      # طمس تاريخ يدوي (سحب مستطيل — تمويه بلون المنتج)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._item = QGraphicsPixmapItem()
        self._item.setTransformationMode(Qt.SmoothTransformation)
        self._scene.addItem(self._item)
        self._overlay_item = QGraphicsPixmapItem()
        self._overlay_item.setZValue(5)
        self._scene.addItem(self._overlay_item)

        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.NoAnchor)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setBackgroundBrush(QBrush(QColor(232, 234, 238)))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self._zoom = 1.0
        self._tool = self.TOOL_PAN
        self._brush_size = 40
        self._stroke_points: list[tuple[float, float]] = []
        self._painting = False
        self._rect_start: QPointF | None = None
        self._rect_item = None
        self._first_fit_done = False
        self.show_grid = False   # شبكة إرشادية أثناء التوزين

    def drawForeground(self, painter, rect) -> None:  # noqa: N802
        super().drawForeground(painter, rect)
        if not self.show_grid or self._item.pixmap().isNull():
            return
        # شبكة شفافة ثابتة فوق الصورة لموازنة المنتج بصريًا
        br = self._scene.sceneRect()
        pen = QPen(QColor(30, 110, 220, 110), 0)
        painter.setPen(pen)
        step = max(br.width(), br.height()) / 12.0
        x = br.left()
        while x <= br.right():
            painter.drawLine(QPointF(x, br.top()), QPointF(x, br.bottom()))
            x += step
        y = br.top()
        while y <= br.bottom():
            painter.drawLine(QPointF(br.left(), y), QPointF(br.right(), y))
            y += step
        # خطا المنتصف أوضح
        pen2 = QPen(QColor(220, 60, 60, 150), 0)
        painter.setPen(pen2)
        cx, cy = br.center().x(), br.center().y()
        painter.drawLine(QPointF(cx, br.top()), QPointF(cx, br.bottom()))
        painter.drawLine(QPointF(br.left(), cy), QPointF(br.right(), cy))

    # ---------------------------------------------------------- image API
    def set_image(self, img_bgr_or_bgra: np.ndarray, fit: bool = False) -> None:
        pix = QPixmap.fromImage(_np_bgr_to_qimage(img_bgr_or_bgra))
        self._item.setPixmap(pix)
        self._scene.setSceneRect(QRectF(pix.rect()))
        if fit or not self._first_fit_done:
            self.fit_view()
            self._first_fit_done = True

    def set_overlay(self, overlay_rgba: np.ndarray | None) -> None:
        """طبقة تلوين حمراء نصف شفافة لعرض منطقة العزل المحددة."""
        if overlay_rgba is None:
            self._overlay_item.setPixmap(QPixmap())
            return
        h, w = overlay_rgba.shape[:2]
        qimg = QImage(overlay_rgba.data, w, h, w * 4, QImage.Format_RGBA8888).copy()
        self._overlay_item.setPixmap(QPixmap.fromImage(qimg))

    def fit_view(self) -> None:
        if self._item.pixmap().isNull():
            return
        self.fitInView(self._item, Qt.KeepAspectRatio)
        self._zoom = self.transform().m11()
        self.zoom_changed.emit(self._zoom)

    def set_tool(self, tool: str) -> None:
        self._tool = tool
        if tool == self.TOOL_PAN:
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            self.viewport().setCursor(Qt.OpenHandCursor)
        elif tool in (self.TOOL_ERASE, self.TOOL_RESTORE, self.TOOL_REGION):
            self.setDragMode(QGraphicsView.NoDrag)
            self._update_cursor_preview()
        else:
            self.setDragMode(QGraphicsView.NoDrag)
            self.viewport().setCursor(Qt.CrossCursor)

    def set_brush_size(self, size: int) -> None:
        self._brush_size = max(4, int(size))
        self._update_cursor_preview()

    def _update_cursor_preview(self) -> None:
        """مؤشر دائري حي بحجم الفرشاة الحقيقي أثناء التلوين."""
        if self._tool not in (self.TOOL_ERASE, self.TOOL_RESTORE,
                              self.TOOL_REGION):
            return
        d = max(6, int(self._brush_size * self._zoom))
        d = min(d, 260)
        pm = QPixmap(d + 2, d + 2)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        color = QColor(220, 60, 60) if self._tool == self.TOOL_ERASE \
            else QColor(30, 130, 60) if self._tool == self.TOOL_RESTORE \
            else QColor(230, 140, 30)
        pen = QPen(color, 2)
        p.setPen(pen)
        p.drawEllipse(1, 1, d, d)
        p.end()
        self.viewport().setCursor(QCursor(pm, d // 2 + 1, d // 2 + 1))

    # ------------------------------------------------------------- events
    def wheelEvent(self, event: QWheelEvent) -> None:
        # زووم نحو موضع المؤشر
        if self._item.pixmap().isNull():
            return
        factor = 1.18 if event.angleDelta().y() > 0 else 1 / 1.18
        new_zoom = self._zoom * factor
        if not (0.04 <= new_zoom <= 40.0):
            return
        old_pos = self.mapToScene(event.position().toPoint())
        self.scale(factor, factor)
        new_pos = self.mapToScene(event.position().toPoint())
        delta = new_pos - old_pos
        self.translate(delta.x(), delta.y())
        self._zoom = new_zoom
        self.zoom_changed.emit(self._zoom)
        self._update_cursor_preview()

    def mousePressEvent(self, event) -> None:
        if self._tool in (self.TOOL_ERASE, self.TOOL_RESTORE, self.TOOL_REGION) \
                and event.button() == Qt.LeftButton:
            self._painting = True
            self._stroke_points = []
            self._add_point(event.position())
            return
        if self._tool in (self.TOOL_REGION_RECT, self.TOOL_DATE_BLUR) \
                and event.button() == Qt.LeftButton:
            self._rect_start = self.mapToScene(event.position().toPoint())
            if self._rect_item is not None:
                self._scene.removeItem(self._rect_item)
                self._rect_item = None
            pen = QPen(QColor(220, 60, 60), 2, Qt.DashLine)
            pen.setCosmetic(True)
            self._rect_item = self._scene.addRect(QRectF(self._rect_start, self._rect_start), pen)
            self._rect_item.setZValue(10)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._painting:
            self._add_point(event.position())
            return
        if self._tool in (self.TOOL_REGION_RECT, self.TOOL_DATE_BLUR) \
                and self._rect_start is not None:
            cur = self.mapToScene(event.position().toPoint())
            self._rect_item.setRect(QRectF(self._rect_start, cur).normalized())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._painting and event.button() == Qt.LeftButton:
            self._painting = False
            if self._stroke_points:
                self.brush_stroke.emit(list(self._stroke_points),
                                       self._brush_size, self._tool)
            self._stroke_points = []
            return
        if self._tool in (self.TOOL_REGION_RECT, self.TOOL_DATE_BLUR) \
                and self._rect_start is not None \
                and event.button() == Qt.LeftButton:
            rect = self._rect_item.rect().normalized()
            self._scene.removeItem(self._rect_item)
            self._rect_item = None
            self._rect_start = None
            # أرسل زوايا المستطيل كنقطتين مع أداة خاصة
            pts = [(rect.left(), rect.top()), (rect.right(), rect.bottom())]
            self.brush_stroke.emit(pts, 0, self._tool)
            return
        super().mouseReleaseEvent(event)

    def _add_point(self, view_pos) -> None:
        sp = self.mapToScene(QPoint(int(view_pos.x()), int(view_pos.y())))
        self._stroke_points.append((sp.x(), sp.y()))
        # رسم فوري خفيف: يُحدث الـ overlay مباشرة عبر إشارة جزئية كل 4 نقاط
        if len(self._stroke_points) % 4 == 0:
            self.brush_stroke.emit(self._stroke_points[-4:],
                                   self._brush_size, self._tool + "_live")


# ========================================================== worker threads
class SmartWorker(QThread):
    """تشغيل العمليات الذكية الثقيلة (إزالة الخلفية) خارج خيط الواجهة."""
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            self.done.emit(self._fn())
        except Exception as exc:
            self.failed.emit(str(exc))


# ============================================================== the editor
class V2PhotoEditorDialog(QDialog):
    """محرر الصور الاحترافي للمتاجر — نافذة كاملة بثلاثة أوضاع."""

    _SEGMENTER = None  # مشترك بين النوافذ لتسريع الفتح

    def __init__(self, image_path: str = "", parent=None,
                 save_dir: str = "", suggested_name: str = ""):
        super().__init__(parent)
        self.setWindowTitle("محرر صور المتاجر الاحترافي — V2")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumSize(1360, 860)
        self.resize(1480, 900)

        self._image_path = image_path
        self._save_dir = save_dir
        self._suggested_name = suggested_name
        self._saved_path = ""

        # حالة الطبقات (غير هدّامة)
        self._original: np.ndarray | None = None      # BGR الأصل
        self._base: np.ndarray | None = None          # BGRA بعد الطبقة الذكية
        self._alpha_manual: np.ndarray | None = None  # تعديلات القلم على alpha
        self._region_mask: np.ndarray | None = None   # قناع منطقة العزل 0..255
        self._region_active = False
        self._shadow_opts = None
        self._cutout_applied = False
        self._history: list[dict] = []
        self._redo: list[dict] = []
        self._composited: np.ndarray | None = None    # الناتج النهائي BGR
        self._show_before = False

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(120)
        self._preview_timer.timeout.connect(self._recompose)

        self._build_ui()
        if image_path:
            self._load_image(image_path)

    # ---------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # ---------- الشريط العلوي: فتح/حفظ/تراجع/قبل-بعد/زووم
        top = QHBoxLayout()
        top.setSpacing(8)

        self.open_btn = QPushButton("فتح صورة…")
        self.open_btn.setMinimumHeight(38)
        self.open_btn.clicked.connect(self._pick_image)

        self.save_btn = QPushButton("حفظ WebP")
        self.save_btn.setMinimumHeight(38)
        self.save_btn.setObjectName("saveBtn")
        self.save_btn.clicked.connect(self._save)

        self.undo_btn = QPushButton("تراجع")
        self.undo_btn.setMinimumHeight(38)
        self.undo_btn.clicked.connect(self._undo)
        self.redo_btn = QPushButton("إعادة")
        self.redo_btn.setMinimumHeight(38)
        self.redo_btn.clicked.connect(self._redo_action)

        self.before_btn = QPushButton("قبل / بعد")
        self.before_btn.setMinimumHeight(38)
        self.before_btn.setCheckable(True)
        self.before_btn.pressed.connect(lambda: self._toggle_before(True))
        self.before_btn.released.connect(lambda: self._toggle_before(False))

        self.reset_btn = QPushButton("إعادة ضبط الكل")
        self.reset_btn.setMinimumHeight(38)
        self.reset_btn.clicked.connect(self._reset_all)

        self.fit_btn = QPushButton("ملاءمة")
        self.fit_btn.setMinimumHeight(38)
        self.fit_btn.clicked.connect(lambda: self.canvas.fit_view())

        self.zoom_label = QLabel("100%")
        self.zoom_label.setMinimumWidth(56)
        self.zoom_label.setAlignment(Qt.AlignCenter)

        self.mode_label = QLabel("")
        self.mode_label.setStyleSheet("color:#0a6e3a;font-weight:700;")

        self.help_btn = QPushButton("؟ تعليمات")
        self.help_btn.setMinimumHeight(38)
        self.help_btn.clicked.connect(self._show_help)

        for wdg in (self.open_btn, self.save_btn, self.undo_btn, self.redo_btn,
                    self.before_btn, self.reset_btn, self.fit_btn,
                    self.help_btn):
            top.addWidget(wdg)
        top.addWidget(self.zoom_label)
        top.addStretch(1)
        top.addWidget(self.mode_label)
        root.addLayout(top)

        # ---------- الجسم: أدوات ذكية | لوحة | أدوات يدوية
        body = QSplitter(Qt.Horizontal)
        body.setChildrenCollapsible(False)

        # أنشئ اللوحة أولًا لأن اللوحات الجانبية تربط إشاراتها بها
        self.canvas = EditorCanvas()
        self.canvas.brush_stroke.connect(self._on_stroke)
        self.canvas.zoom_changed.connect(
            lambda z: self.zoom_label.setText(f"{int(z * 100)}%"))

        smart_panel = self._build_smart_panel()
        manual_panel = self._build_manual_panel()

        center = QWidget()
        cv = QVBoxLayout(center)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(6)

        # شريط الأوضاع فوق اللوحة
        mode_bar = QHBoxLayout()
        mode_bar.setSpacing(6)
        self.mode_smart_rb = QRadioButton("الوضع الذكي")
        self.mode_manual_rb = QRadioButton("الوضع اليدوي")
        self.mode_blend_rb = QRadioButton("وضع الدمج (ذكي + يدوي بالمناطق)")
        self.mode_blend_rb.setChecked(True)
        self._mode_group = QButtonGroup(self)
        for rb in (self.mode_smart_rb, self.mode_manual_rb, self.mode_blend_rb):
            self._mode_group.addButton(rb)
            rb.toggled.connect(self._mode_changed)
            mode_bar.addWidget(rb)
        mode_bar.addStretch(1)
        self.status_label = QLabel("افتح صورة للبدء")
        self.status_label.setStyleSheet("color:#555;")
        mode_bar.addWidget(self.status_label)
        cv.addLayout(mode_bar)

        cv.addWidget(self.canvas, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setMaximumHeight(8)
        self.progress.setTextVisible(False)
        cv.addWidget(self.progress)

        body.addWidget(smart_panel)
        body.addWidget(center)
        body.addWidget(manual_panel)
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        body.setStretchFactor(2, 0)
        body.setSizes([300, 780, 320])
        root.addWidget(body, 1)

        self.setStyleSheet(self.styleSheet() + """
            QGroupBox { font-weight:700; border:1px solid #cfd4dc;
                        border-radius:8px; margin-top:12px; padding-top:6px; }
            QGroupBox::title { subcontrol-origin: margin; right:10px; padding:0 4px; }
            QPushButton { padding:6px 10px; }
            QPushButton#saveBtn { background:#0a6e3a; color:white; font-weight:700;
                                  border-radius:6px; }
            QPushButton#saveBtn:hover { background:#0c8446; }
            QSlider::groove:horizontal { height:6px; background:#d7dbe2;
                                         border-radius:3px; }
            QSlider::handle:horizontal { width:18px; height:18px; margin:-6px 0;
                                         background:#2563eb; border-radius:9px; }
        """)

    def _build_smart_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(280)
        panel.setMaximumWidth(330)
        lay = QVBoxLayout(panel)
        lay.setSpacing(10)

        title = QLabel("الأدوات الذكية (تلقائية)")
        title.setStyleSheet("font-size:15px;font-weight:800;color:#1d4ed8;")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)

        g1 = QGroupBox("معالجة بنقرة واحدة")
        v1 = QVBoxLayout(g1)
        self.auto_all_btn = QPushButton("معالجة ذكية كاملة ✦")
        self.auto_all_btn.setMinimumHeight(44)
        self.auto_all_btn.setStyleSheet(
            "background:#2563eb;color:white;font-weight:800;border-radius:8px;")
        self.auto_all_btn.clicked.connect(self._smart_full)
        v1.addWidget(self.auto_all_btn)

        self.cutout_btn = QPushButton("إزالة الخلفية (قص ذكي)")
        self.cutout_btn.setMinimumHeight(38)
        self.cutout_btn.clicked.connect(self._smart_cutout)
        v1.addWidget(self.cutout_btn)

        self.enhance_btn = QPushButton("تحسين تلقائي")
        self.enhance_btn.setMinimumHeight(38)
        self.enhance_btn.clicked.connect(self._smart_enhance)
        v1.addWidget(self.enhance_btn)

        self.center_btn = QPushButton("توسيط وتأطير 800×700")
        self.center_btn.setMinimumHeight(38)
        self.center_btn.clicked.connect(self._smart_frame)
        v1.addWidget(self.center_btn)
        lay.addWidget(g1)

        # الظل المبسّط: مفتاح واحد + منزلق قوة — دائمًا أسفل المنتج
        g2 = QGroupBox("الظل (أسفل المنتج)")
        v2 = QVBoxLayout(g2)
        self.shadow_enable_cb = QCheckBox("تفعيل ظل طبيعي أسفل المنتج")
        self.shadow_enable_cb.setToolTip(
            "ظل أرضي ناعم فقط — بلا اتجاهات معقدة")
        v2.addWidget(self.shadow_enable_cb)
        row = QGridLayout()
        row.addWidget(QLabel("قوة الظل"), 0, 0)
        self.shadow_strength = QSlider(Qt.Horizontal)
        self.shadow_strength.setLayoutDirection(Qt.LeftToRight)
        self.shadow_strength.setRange(10, 100)
        self.shadow_strength.setValue(45)
        self.shadow_strength.setToolTip("اسحب يمينًا لزيادة الظل")
        row.addWidget(self.shadow_strength, 0, 1)
        self.shadow_strength_lbl = QLabel("45")
        self.shadow_strength.valueChanged.connect(
            lambda v: self.shadow_strength_lbl.setText(str(v)))
        row.addWidget(self.shadow_strength_lbl, 0, 2)
        v2.addLayout(row)
        # متقدم (مطوي): القوالب القديمة لمن يريدها
        self.shadow_combo = QComboBox()
        self.shadow_combo.setMinimumHeight(30)
        self.shadow_combo.setVisible(False)
        adv_btn = QPushButton("خيارات متقدمة ▾")
        adv_btn.setFlat(True)
        adv_btn.setStyleSheet("color:#2563eb;text-align:right;")
        adv_btn.clicked.connect(
            lambda: self.shadow_combo.setVisible(
                not self.shadow_combo.isVisible()))
        v2.addWidget(adv_btn)
        v2.addWidget(self.shadow_combo)
        self.shadow_enable_cb.toggled.connect(self._shadow_changed)
        self.shadow_strength.valueChanged.connect(self._shadow_changed)
        self.shadow_combo.currentIndexChanged.connect(self._shadow_changed)
        lay.addWidget(g2)

        # إزالة الانعكاسات — في الشاشة الخارجية مباشرة
        g_glare = QGroupBox("إزالة انعكاسات التصوير (اللمعان)")
        vg = QVBoxLayout(g_glare)
        self.glare_enable_cb = QCheckBox("تفعيل إزالة الانعكاسات")
        self.glare_enable_cb.setToolTip(
            "يكشف لمعان الفلاش والإضاءة ويزيله مع حفظ تفاصيل العبوة")
        vg.addWidget(self.glare_enable_cb)
        grow = QGridLayout()
        grow.addWidget(QLabel("القوة"), 0, 0)
        self.glare_strength = QSlider(Qt.Horizontal)
        self.glare_strength.setLayoutDirection(Qt.LeftToRight)
        self.glare_strength.setRange(10, 100)
        self.glare_strength.setValue(60)
        self.glare_strength.setToolTip(
            "اسحب يمينًا للتقوية ويسارًا للتضعيف — النتيجة تظهر فورًا")
        grow.addWidget(self.glare_strength, 0, 1)
        self.glare_strength_lbl = QLabel("60")
        self.glare_strength.valueChanged.connect(
            lambda v: self.glare_strength_lbl.setText(str(v)))
        grow.addWidget(self.glare_strength_lbl, 0, 2)
        vg.addLayout(grow)
        self.glare_enable_cb.toggled.connect(self._schedule_preview)
        self.glare_strength.valueChanged.connect(self._schedule_preview)
        lay.addWidget(g_glare)

        # المساعد الذكي: اقتراحات تلقائية لكل صورة
        g_ai = QGroupBox("المساعد الذكي — اقتراحات")
        vai = QVBoxLayout(g_ai)
        self.suggest_btn = QPushButton("حلل الصورة واقترح تحسينات ✦")
        self.suggest_btn.setMinimumHeight(36)
        self.suggest_btn.clicked.connect(self._show_suggestions)
        vai.addWidget(self.suggest_btn)
        self.suggestions_box = QVBoxLayout()
        vai.addLayout(self.suggestions_box)
        erow = QHBoxLayout()
        self.refine_edges_btn = QPushButton("تنعيم الحواف الذكي")
        self.refine_edges_btn.setMinimumHeight(34)
        self.refine_edges_btn.setToolTip(
            "للمنتجات الصعبة: أغلفة شفافة وانحناءات (مثل الدجاج)")
        self.refine_edges_btn.clicked.connect(self._refine_edges)
        self.dehalo_btn = QPushButton("إزالة هالة الخلفية")
        self.dehalo_btn.setMinimumHeight(34)
        self.dehalo_btn.setToolTip("يزيل بقايا لون الخلفية العالقة على الحواف")
        self.dehalo_btn.clicked.connect(self._remove_halo)
        erow.addWidget(self.refine_edges_btn)
        erow.addWidget(self.dehalo_btn)
        vai.addLayout(erow)
        lay.addWidget(g_ai)

        g3 = QGroupBox("منطقة العزل (للدمج الانتقائي)")
        v3 = QVBoxLayout(g3)
        hint = QLabel("حدد منطقة ثم طبّق أي أداة عليها فقط")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666;")
        v3.addWidget(hint)
        rrow = QHBoxLayout()
        self.region_brush_btn = QPushButton("فرشاة تحديد")
        self.region_brush_btn.setCheckable(True)
        self.region_brush_btn.setMinimumHeight(36)
        self.region_rect_btn = QPushButton("مستطيل تحديد")
        self.region_rect_btn.setCheckable(True)
        self.region_rect_btn.setMinimumHeight(36)
        rrow.addWidget(self.region_brush_btn)
        rrow.addWidget(self.region_rect_btn)
        v3.addLayout(rrow)
        self.region_clear_btn = QPushButton("مسح التحديد")
        self.region_clear_btn.setMinimumHeight(32)
        self.region_clear_btn.clicked.connect(self._clear_region)
        v3.addWidget(self.region_clear_btn)
        self.region_only_cb = QCheckBox("تطبيق الأدوات على المنطقة المحددة فقط")
        v3.addWidget(self.region_only_cb)
        lay.addWidget(g3)

        self.region_brush_btn.toggled.connect(
            lambda on: self._pick_tool(EditorCanvas.TOOL_REGION, on,
                                       self.region_brush_btn))
        self.region_rect_btn.toggled.connect(
            lambda on: self._pick_tool(EditorCanvas.TOOL_REGION_RECT, on,
                                       self.region_rect_btn))

        lay.addStretch(1)
        return panel

    def _build_manual_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(300)
        panel.setMaximumWidth(350)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setSpacing(10)

        title = QLabel("الأدوات اليدوية (دقيقة)")
        title.setStyleSheet("font-size:15px;font-weight:800;color:#b45309;")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)

        g1 = QGroupBox("قلم التبييض وضبط الحواف")
        v1 = QVBoxLayout(g1)
        prow = QHBoxLayout()
        self.erase_btn = QPushButton("قلم تبييض")
        self.erase_btn.setCheckable(True)
        self.erase_btn.setMinimumHeight(38)
        self.restore_btn = QPushButton("استرجاع")
        self.restore_btn.setCheckable(True)
        self.restore_btn.setMinimumHeight(38)
        self.pan_btn = QPushButton("تحريك ✋")
        self.pan_btn.setCheckable(True)
        self.pan_btn.setChecked(True)
        self.pan_btn.setMinimumHeight(38)
        prow.addWidget(self.erase_btn)
        prow.addWidget(self.restore_btn)
        prow.addWidget(self.pan_btn)
        v1.addLayout(prow)

        drow = QHBoxLayout()
        self.date_blur_btn = QPushButton("طمس تاريخ يدوي")
        self.date_blur_btn.setCheckable(True)
        self.date_blur_btn.setMinimumHeight(38)
        self.date_blur_btn.setToolTip(
            "اسحب مستطيلًا فوق التاريخ المطبوع — يُطمس بتمويه طفيف\n"
            "بلون المنتج نفسه دون أثر واضح")
        self.date_blur_btn.toggled.connect(
            lambda on: self._pick_tool(EditorCanvas.TOOL_DATE_BLUR, on,
                                       self.date_blur_btn))
        drow.addWidget(self.date_blur_btn)
        self.auto_date_btn = QPushButton("طمس التواريخ تلقائيًا")
        self.auto_date_btn.setMinimumHeight(38)
        self.auto_date_btn.setToolTip(
            "يكشف تواريخ الإنتاج/الانتهاء المطبوعة في الصورة ويطمسها تلقائيًا")
        self.auto_date_btn.clicked.connect(self._auto_blur_dates)
        drow.addWidget(self.auto_date_btn)
        v1.addLayout(drow)

        srow = QHBoxLayout()
        srow.addWidget(QLabel("حجم الفرشاة"))
        self.brush_slider = QSlider(Qt.Horizontal)
        self.brush_slider.setLayoutDirection(Qt.LeftToRight)
        self.brush_slider.setRange(6, 200)
        self.brush_slider.setValue(40)
        self.brush_slider.valueChanged.connect(self.canvas.set_brush_size)
        srow.addWidget(self.brush_slider)
        self.brush_size_lbl = QLabel("40")
        self.brush_slider.valueChanged.connect(
            lambda v: self.brush_size_lbl.setText(str(v)))
        srow.addWidget(self.brush_size_lbl)
        v1.addLayout(srow)

        frow = QHBoxLayout()
        frow.addWidget(QLabel("نعومة الحواف"))
        self.feather_slider = QSlider(Qt.Horizontal)
        self.feather_slider.setLayoutDirection(Qt.LeftToRight)
        self.feather_slider.setRange(0, 30)
        self.feather_slider.setValue(6)
        self.feather_slider.valueChanged.connect(self._schedule_preview)
        frow.addWidget(self.feather_slider)
        v1.addLayout(frow)
        lay.addWidget(g1)

        g2 = QGroupBox("منزلقات التحسين")
        v2 = QGridLayout(g2)
        self._sliders: dict[str, QSlider] = {}
        specs = [
            ("الإضاءة", "brightness", -100, 100, 0),
            ("التباين", "contrast", -100, 100, 0),
            ("الحدة", "sharpness", 0, 100, 0),
            ("التشبع", "saturation", -100, 100, 0),
            ("إزالة الضوضاء", "denoise", 0, 100, 0),
        ]
        for i, (label, key, lo, hi, dv) in enumerate(specs):
            v2.addWidget(QLabel(label), i, 0)
            s = QSlider(Qt.Horizontal)
            # LTR ثابت حتى لا ينعكس السحب في واجهة RTL: يمين = زيادة
            s.setLayoutDirection(Qt.LeftToRight)
            s.setRange(lo, hi)
            s.setValue(dv)
            s.setToolTip("اسحب يمينًا للزيادة ويسارًا للنقصان")
            s.valueChanged.connect(self._schedule_preview)
            self._sliders[key] = s
            v2.addWidget(s, i, 1)
            val = QLabel("0")
            val.setMinimumWidth(30)
            s.valueChanged.connect(lambda v, l=val: l.setText(str(v)))
            v2.addWidget(val, i, 2)
        reset_sliders = QPushButton("تصفير المنزلقات")
        reset_sliders.clicked.connect(self._zero_sliders)
        v2.addWidget(reset_sliders, len(specs), 0, 1, 3)
        lay.addWidget(g2)

        g3 = QGroupBox("اقتصاص وتوزين المنتج (تدوير دقيق)")
        v3 = QVBoxLayout(g3)
        rot_row = QHBoxLayout()
        rot_row.addWidget(QLabel("ميول"))
        # دقة 0.1°: القيمة الداخلية بأعشار الدرجة (-1800..1800)
        self.rotate_slider = QSlider(Qt.Horizontal)
        self.rotate_slider.setLayoutDirection(Qt.LeftToRight)
        self.rotate_slider.setRange(-1800, 1800)
        self.rotate_slider.setValue(0)
        self.rotate_slider.setSingleStep(1)   # 0.1°
        self.rotate_slider.setPageStep(10)    # 1°
        self.rotate_slider.setToolTip(
            "اسحب لتوزين المنتج بدقة 0.1 درجة — تظهر شبكة إرشادية أثناء السحب")
        self.rotate_slider.valueChanged.connect(self._schedule_preview)
        self.rotate_slider.sliderPressed.connect(
            lambda: setattr(self.canvas, "show_grid", True))
        self.rotate_slider.sliderReleased.connect(self._rot_released)
        rot_row.addWidget(self.rotate_slider)
        self.rot_lbl = QLabel("0.0°")
        self.rot_lbl.setMinimumWidth(48)
        self.rotate_slider.valueChanged.connect(
            lambda v: self.rot_lbl.setText(f"{v / 10.0:.1f}°"))
        rot_row.addWidget(self.rot_lbl)
        v3.addLayout(rot_row)
        fine_row = QHBoxLayout()
        for txt, delta in (("−٠.٥", -5), ("+٠.٥", 5)):
            b = QPushButton(txt + "°")
            b.setMinimumHeight(30)
            b.setToolTip("ضبط دقيق نصف درجة")
            b.clicked.connect(lambda _, d=delta: self.rotate_slider.setValue(
                self.rotate_slider.value() + d))
            fine_row.addWidget(b)
        self.auto_level_btn = QPushButton("توزين تلقائي ذكي")
        self.auto_level_btn.setMinimumHeight(30)
        self.auto_level_btn.setToolTip(
            "يكشف ميل المنتج تلقائيًا ويصححه بدقة")
        self.auto_level_btn.clicked.connect(self._auto_level)
        fine_row.addWidget(self.auto_level_btn)
        rot_zero = QPushButton("تصفير")
        rot_zero.setMinimumHeight(30)
        rot_zero.clicked.connect(lambda: self.rotate_slider.setValue(0))
        fine_row.addWidget(rot_zero)
        v3.addLayout(fine_row)
        crop_row = QHBoxLayout()
        self.crop_btn = QPushButton("اقتصاص للتحديد")
        self.crop_btn.setMinimumHeight(34)
        self.crop_btn.setToolTip("حدد منطقة بالمستطيل ثم اضغط للاقتصاص")
        self.crop_btn.clicked.connect(self._crop_to_region)
        crop_row.addWidget(self.crop_btn)
        v3.addLayout(crop_row)
        lay.addWidget(g3)

        # تنقيح نهائي بمظهر الاستوديو — في الشاشة الخارجية مباشرة
        g4 = QGroupBox("تنقيح استوديو للتسليم (حواف نظيفة + لمعة متجر)")
        v4 = QVBoxLayout(g4)
        self.polish_enable_cb = QCheckBox("تفعيل تنقيح الاستوديو")
        self.polish_enable_cb.setToolTip(
            "ينظف الحواف من أي سواد وهالات ويضيف لمعة تصوير استوديو:\n"
            "توازن أبيض + إضاءة ناعمة + نضارة ألوان + حدة نظيفة —\n"
            "النتيجة تظهر فورًا في المعاينة")
        self.polish_enable_cb.toggled.connect(self._schedule_preview)
        v4.addWidget(self.polish_enable_cb)
        prow = QGridLayout()
        prow.addWidget(QLabel("قوة اللمعة"), 0, 0)
        self.polish_strength = QSlider(Qt.Horizontal)
        self.polish_strength.setLayoutDirection(Qt.LeftToRight)
        self.polish_strength.setRange(0, 100)
        self.polish_strength.setValue(50)
        self.polish_strength.setToolTip(
            "يمينًا = لمعة أقوى — تنظيف الحواف يتم دائمًا كاملًا")
        self.polish_strength.valueChanged.connect(self._schedule_preview)
        prow.addWidget(self.polish_strength, 0, 1)
        self.polish_strength_lbl = QLabel("50")
        self.polish_strength.valueChanged.connect(
            lambda v: self.polish_strength_lbl.setText(str(v)))
        prow.addWidget(self.polish_strength_lbl, 0, 2)
        v4.addLayout(prow)
        lay.addWidget(g4)

        lay.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        return panel

    # ------------------------------------------------------------ helpers
    def _pick_tool(self, tool: str, on: bool, source_btn) -> None:
        if not on:
            # لو أطفأ المستخدم الزر نرجع للتحريك
            _btns = [self.erase_btn, self.restore_btn,
                     self.region_brush_btn, self.region_rect_btn]
            if getattr(self, "date_blur_btn", None) is not None:
                _btns.append(self.date_blur_btn)
            if not any(b.isChecked() for b in _btns):
                self.pan_btn.setChecked(True)
                self.canvas.set_tool(EditorCanvas.TOOL_PAN)
            return
        # أطفئ بقية أزرار الأدوات
        for b in (self.erase_btn, self.restore_btn, self.pan_btn,
                  self.region_brush_btn, self.region_rect_btn,
                  getattr(self, "date_blur_btn", None)):
            if b is not None and b is not source_btn and b.isChecked():
                b.blockSignals(True)
                b.setChecked(False)
                b.blockSignals(False)
        self.canvas.set_tool(tool)

    def _mode_changed(self) -> None:
        smart = self.mode_smart_rb.isChecked()
        manual = self.mode_manual_rb.isChecked()
        blend = self.mode_blend_rb.isChecked()
        if smart:
            self.mode_label.setText("الوضع: ذكي تلقائي")
        elif manual:
            self.mode_label.setText("الوضع: يدوي دقيق")
        else:
            self.mode_label.setText("الوضع: دمج ذكي + يدوي")
        # الوضع الذكي: تُخفى الأدوات اليدوية بصريًا (تبقى النافذة نظيفة)
        # وضع الدمج: كل شيء متاح. اليدوي: الأدوات الذكية الفردية تبقى متاحة
        # لكن زر "معالجة كاملة" يُعطل حتى لا يفاجئ المستخدم.
        self.auto_all_btn.setEnabled(not manual)
        self.region_only_cb.setEnabled(blend)
        if blend:
            self.region_only_cb.setChecked(bool(self._region_active))

    # ---------------------------------------------------------- load/save
    def _pick_image(self) -> None:
        start = self._save_dir or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, "اختر صورة (جديدة أو قديمة أو منتجة)", start,
            "صور (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)")
        if path:
            self._load_image(path)

    def _load_image(self, path: str) -> None:
        img = _read_any(path)
        if img is None:
            QMessageBox.warning(self, "خطأ", f"تعذر فتح الصورة:\n{path}")
            return
        # حد أقصى معقول للأداء
        import cv2
        h, w = img.shape[:2]
        if max(h, w) > 2600:
            sc = 2600 / max(h, w)
            img = cv2.resize(img, (int(w * sc), int(h * sc)),
                             interpolation=cv2.INTER_AREA)
        self._image_path = path
        self._original = img
        self._base = None
        self._alpha_manual = None
        self._region_mask = None
        self._region_active = False
        self._cutout_applied = False
        self._shadow_opts = None
        self._history.clear()
        self._redo.clear()
        self._zero_sliders(silent=True)
        self.rotate_slider.blockSignals(True)
        self.rotate_slider.setValue(0)
        self.rotate_slider.blockSignals(False)
        self._populate_shadow_presets()
        # التعلم المحلي: اقترح حجم الفرشاة والنعومة المفضلين للمستخدم
        try:
            from engine_v2 import learning_v2
            size, soft = learning_v2.suggest_brush(
                self.brush_slider.value(), self.feather_slider.value())
            self.brush_slider.setValue(int(size))
            self.feather_slider.setValue(int(soft))
        except Exception:
            pass
        self.canvas._first_fit_done = False
        self._recompose(fit=True)
        self.status_label.setText(Path(path).name)

    def _populate_shadow_presets(self) -> None:
        if self.shadow_combo.count():
            return
        from engine_v2.shadow_v2 import SHADOW_PRESETS
        self.shadow_combo.blockSignals(True)
        for name in SHADOW_PRESETS:
            self.shadow_combo.addItem(name)
        self.shadow_combo.setCurrentIndex(0)
        self.shadow_combo.blockSignals(False)

    def _save(self) -> None:
        if self._composited is None:
            QMessageBox.information(self, "حفظ", "لا توجد صورة للحفظ.")
            return
        default_dir = self._save_dir or str(Path(self._image_path).parent)
        default_name = self._suggested_name or \
            (Path(self._image_path).stem + ".webp" if self._image_path else "edited.webp")
        if not default_name.endswith(".webp"):
            default_name = Path(default_name).stem + ".webp"
        path, _ = QFileDialog.getSaveFileName(
            self, "حفظ الصورة النهائية", str(Path(default_dir) / default_name),
            "WebP (*.webp);;PNG (*.png);;JPEG (*.jpg *.jpeg)")
        if not path:
            return
        import cv2
        img = self._composited
        ext = Path(path).suffix.lower()
        if ext == ".webp":
            ok, buf = cv2.imencode(".webp", img,
                                   [cv2.IMWRITE_WEBP_QUALITY, 101])
        else:
            ok, buf = cv2.imencode(ext or ".png", img)
        if not ok:
            QMessageBox.warning(self, "خطأ", "فشل ترميز الصورة.")
            return
        buf.tofile(path)
        self._saved_path = path
        self.status_label.setText(f"تم الحفظ: {Path(path).name}")
        # التعلم المحلي: احفظ تفضيلات الجلسة عند الحفظ الناجح
        try:
            from engine_v2 import learning_v2
            learning_v2.record_brush(self.brush_slider.value(),
                                     self.feather_slider.value())
            learning_v2.record_shadow(self._shadow_opts is not None)
            sh = self._sliders["sharpness"].value()
            if sh:
                learning_v2.record_enhance_strength(sh / 100.0)
        except Exception:
            pass

    # -------------------------------------------------------- smart tools
    def _segmenter(self):
        if V2PhotoEditorDialog._SEGMENTER is None:
            from engine_v2.segmentation_v2 import ProductSegmenterV2
            from engine_v2.paths_v2 import models_dir
            V2PhotoEditorDialog._SEGMENTER = ProductSegmenterV2(models_dir())
        return V2PhotoEditorDialog._SEGMENTER

    def _busy(self, on: bool) -> None:
        self.progress.setVisible(on)
        for b in (self.auto_all_btn, self.cutout_btn, self.enhance_btn,
                  self.center_btn, self.open_btn, self.save_btn):
            b.setEnabled(not on)

    def _smart_cutout(self, then=None) -> None:
        if self._original is None:
            return
        self._push_history()
        img = self._original.copy()

        def job():
            import cv2
            seg = self._segmenter()
            res = seg.segment(img)
            alpha = (np.clip(res.alpha, 0, 1) * 255).astype(np.uint8)
            rgba = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
            rgba[:, :, 3] = alpha
            return rgba

        self._busy(True)
        self.status_label.setText("جارٍ إزالة الخلفية…")
        self._worker = SmartWorker(job)

        def ok(rgba):
            self._busy(False)
            if self.region_only_cb.isChecked() and self._region_mask is not None:
                # قص ذكي على المنطقة فقط: خارج المنطقة يبقى ألفا 255
                m = self._region_mask.astype(np.float32) / 255.0
                full = np.full(rgba.shape[:2], 255, np.float32)
                rgba[:, :, 3] = (rgba[:, :, 3].astype(np.float32) * m +
                                 full * (1 - m)).astype(np.uint8)
            self._base = rgba
            self._cutout_applied = True
            self.status_label.setText("تمت إزالة الخلفية ✓")
            self._recompose()
            if then:
                then()

        def fail(msg):
            self._busy(False)
            QMessageBox.warning(self, "إزالة الخلفية", f"فشلت العملية: {msg}")

        self._worker.done.connect(ok)
        self._worker.failed.connect(fail)
        self._worker.start()

    def _smart_enhance(self) -> None:
        if self._original is None:
            return
        self._push_history()
        from engine_v2.enhancement_v2 import auto_enhance
        import cv2
        self.status_label.setText("جارٍ التحسين التلقائي…")
        QApplication.processEvents()
        if self._base is not None and self._cutout_applied:
            rgb = self._base[:, :, :3]
            enhanced = auto_enhance(rgb)
            if self.region_only_cb.isChecked() and self._region_mask is not None:
                enhanced = self._blend_region(rgb, enhanced)
            self._base = self._base.copy()
            self._base[:, :, :3] = enhanced
        else:
            enhanced = auto_enhance(self._original)
            if self.region_only_cb.isChecked() and self._region_mask is not None:
                enhanced = self._blend_region(self._original, enhanced)
            self._original = enhanced
        self.status_label.setText("تم التحسين التلقائي ✓")
        self._recompose()

    def _smart_frame(self) -> None:
        """توسيط المنتج وتأطيره في لوحة 800×700 بيضاء (مع الظل إنوُجد)."""
        if self._composited is None:
            return
        self._push_history()
        import cv2
        img = self._compose_rgba()  # BGRA بالنتائج الحالية
        a = img[:, :, 3]
        ys, xs = np.where(a > 10)
        if len(xs) == 0:
            QMessageBox.information(self, "تأطير",
                                    "لا يوجد منتج مقصوص — نفّذ إزالة الخلفية أولًا.")
            return
        x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
        crop = img[y0:y1 + 1, x0:x1 + 1]
        ch, cw = crop.shape[:2]
        target_w, target_h = 800, 700
        margin = 0.06
        sc = min((target_w * (1 - 2 * margin)) / cw,
                 (target_h * (1 - 2 * margin)) / ch)
        nw, nh = max(1, int(cw * sc)), max(1, int(ch * sc))
        crop = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_AREA
                          if sc < 1 else cv2.INTER_CUBIC)
        canvas = np.zeros((target_h, target_w, 4), np.uint8)
        ox, oy = (target_w - nw) // 2, (target_h - nh) // 2
        canvas[oy:oy + nh, ox:ox + nw] = crop
        # اجعلها الأساس الجديد وصفّر الطبقات المكررة
        self._original = self._flatten_white(canvas)
        self._base = canvas
        self._cutout_applied = True
        self._alpha_manual = None
        self._region_mask = None
        self._region_active = False
        self.canvas._first_fit_done = False
        self.status_label.setText("تم التوسيط والتأطير 800×700 ✓")
        self._recompose(fit=True)

    def _smart_full(self) -> None:
        """معالجة ذكية كاملة: قص ← تحسين ← ظل أرضي ← تأطير."""
        if self._original is None:
            return

        def after_cutout():
            self._smart_enhance()
            # ظل افتراضي طبيعي إن لم يفعّله المستخدم — وفق تفضيله المتعلّم
            if not self.shadow_enable_cb.isChecked():
                want_shadow = True
                try:
                    from engine_v2 import learning_v2
                    want_shadow = learning_v2.suggest_shadow(True)
                except Exception:
                    pass
                if want_shadow:
                    self.shadow_enable_cb.setChecked(True)  # يستدعي recompose
            self._smart_frame()
            self.status_label.setText("اكتملت المعالجة الذكية الكاملة ✓")

        self._smart_cutout(then=after_cutout)

    def _shadow_changed(self) -> None:
        """الظل المبسّط: مفتاح تفعيل + قوة واحدة — ظل أرضي أسفل المنتج دائمًا."""
        from engine_v2.shadow_v2 import SHADOW_PRESETS, ShadowOptions
        if not self.shadow_enable_cb.isChecked():
            self._shadow_opts = None
            self._schedule_preview()
            return
        # إن فتح المستخدم الخيارات المتقدمة واختار قالبًا، استخدمه كأساس
        base = None
        if self.shadow_combo.isVisible() and self.shadow_combo.currentText():
            base = SHADOW_PRESETS.get(self.shadow_combo.currentText())
        if base is None or getattr(base, "kind", "none") == "none":
            base = SHADOW_PRESETS.get("ظل أرضي ناعم")
        if base is None or getattr(base, "kind", "none") == "none":
            # أمان: ظل أرضي افتراضي
            base = ShadowOptions(kind="contact")
        opts = ShadowOptions.from_dict(base.to_dict())
        st = self.shadow_strength.value() / 100.0  # 0.10 .. 1.00
        opts.opacity = 0.15 + st * 0.55            # 0.21 .. 0.70
        opts.blur = int(12 + st * 34)              # 15 .. 46
        self._shadow_opts = opts
        try:
            from engine_v2 import learning_v2
            learning_v2.record_shadow(True)
        except Exception:
            pass
        self._schedule_preview()

    # ---------------------------------------------------- smart assistant
    def _show_help(self) -> None:
        QMessageBox.information(
            self, "تعليمات المحرر",
            "خطوات العمل المقترحة:\n"
            "1) افتح الصورة ثم اضغط َ‘معالجة ذكية كاملة’ للقص والتحسين تلقائيًا.\n"
            "2) استخدم َ‘حلل الصورة واقترح تحسينات’ ليقترح المساعد الذكي تحسينات جاهزة بنقرة.\n"
            "3) للحواف الصعبة (أغلفة شفافة، دجاج، انحناءات): ‘تنعيم الحواف الذكي’ ثم ‘إزالة هالة الخلفية’.\n"
            "4) اللمعان والانعكاسات: فعّل ‘إزالة الانعكاسات’ واضبط القوة — النتيجة تظهر فورًا.\n"
            "5) الفرشاة: قلم التبييض يمسح للخلفية البيضاء، والاسترجاع يعيد من الأصل. كبّر بعجلة الماوس للدقة.\n"
            "6) المنزلقات: السحب يمينًا زيادة ويسارًا نقصان — دائمًا.\n"
            "7) الظل: مفتاح واحد + قوة — ظل طبيعي أسفل المنتج فقط.\n"
            "8) احفظ بصيغة WebP لأفضل جودة وحجم.\n\n"
            "✦ التطبيق يتعلم منك: يحفظ تفضيلاتك (حجم الفرشاة، الظل، قوة التحسين) محليًا "
            "داخل جهازك فقط ويقترحها تلقائيًا للصور المشابهة.")

    def _clear_suggestions(self) -> None:
        while self.suggestions_box.count():
            item = self.suggestions_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _show_suggestions(self) -> None:
        """المساعد الذكي: تحليل الصورة وعرض اقتراحات تُطبَّق بنقرة."""
        if self._original is None:
            return
        from engine_v2.edge_refine_v2 import smart_suggestions
        alpha = self._base[:, :, 3] if (self._base is not None and
                                        self._cutout_applied) else None
        img = self._base[:, :, :3] if self._base is not None else self._original
        sugg = smart_suggestions(img, alpha)
        self._clear_suggestions()
        if not sugg:
            lbl = QLabel("الصورة ممتازة — لا توجد تحسينات مقترحة ✓")
            lbl.setStyleSheet("color:#0a6e3a;")
            self.suggestions_box.addWidget(lbl)
            return
        for s in sugg[:5]:
            btn = QPushButton("✦ " + s["label_ar"])
            btn.setToolTip(s.get("reason_ar", ""))
            btn.setMinimumHeight(32)
            btn.setStyleSheet(
                "text-align:right;padding:4px 10px;"
                "background:#eef6ff;border:1px solid #bfdcff;border-radius:6px;")
            btn.clicked.connect(
                lambda _=False, item=s: self._apply_suggestion(item))
            self.suggestions_box.addWidget(btn)
        self.status_label.setText(f"اقترح المساعد {len(sugg)} تحسينًا — اضغط للتطبيق")

    def _apply_suggestion(self, s: dict) -> None:
        key = s.get("key", "")
        params = s.get("params", {})
        if key == "brightness":
            self._sliders["brightness"].setValue(int(params.get("value", 15)))
        elif key == "contrast":
            self._sliders["contrast"].setValue(25)
        elif key == "sharpen":
            self._sliders["sharpness"].setValue(
                int(params.get("amount", 0.6) * 50))
        elif key == "denoise":
            self._sliders["denoise"].setValue(int(params.get("h", 7) * 5))
        elif key == "refine_alpha":
            self._refine_edges()
            return
        elif key == "remove_halo":
            self._remove_halo()
            return
        elif key == "edge_review":
            rects = params.get("rects", [])
            QMessageBox.information(
                self, "مراجعة الحواف",
                f"توجد {len(rects)} منطقة حواف غير مؤكدة.\n"
                "كبّر على أطراف المنتج واستخدم فرشاة الاسترجاع أو "
                "‘تنعيم الحواف الذكي’.")
            return
        self.status_label.setText(f"طُبّق: {s['label_ar']} ✓")
        self._schedule_preview()

    def _refine_edges(self) -> None:
        """تنعيم الحواف الذكي — للمنتجات الصعبة (شفافيات/انحناءات)."""
        if self._base is None or not self._cutout_applied:
            QMessageBox.information(self, "تنعيم الحواف",
                                    "نفّذ إزالة الخلفية أولًا.")
            return
        self._push_history()
        from engine_v2.edge_refine_v2 import refine_alpha
        self._base = self._base.copy()
        self._base[:, :, 3] = refine_alpha(self._base[:, :, :3],
                                           self._base[:, :, 3])
        try:
            from engine_v2 import learning_v2
            learning_v2.record_edge_correction(True)
        except Exception:
            pass
        self.status_label.setText("تم تنعيم الحواف الذكي ✓")
        self._recompose()

    def _remove_halo(self) -> None:
        """إزالة هالة لون الخلفية العالقة على الحواف."""
        if self._base is None or not self._cutout_applied:
            QMessageBox.information(self, "إزالة الهالة",
                                    "نفّذ إزالة الخلفية أولًا.")
            return
        self._push_history()
        from engine_v2.edge_refine_v2 import remove_halo
        self._base = self._base.copy()
        self._base[:, :, :3] = remove_halo(self._base[:, :, :3],
                                           self._base[:, :, 3])
        self.status_label.setText("تمت إزالة هالة الخلفية ✓")
        self._recompose()

    # ------------------------------------------------------- manual tools
    def _on_stroke(self, points: list, size: int, tool: str) -> None:
        live = tool.endswith("_live")
        tool_base = tool.replace("_live", "")
        if self._original is None or not points:
            return
        import cv2
        h, w = self._original.shape[:2]

        if tool_base == EditorCanvas.TOOL_DATE_BLUR:
            (x0, y0), (x1, y1) = points
            x0, y0 = max(0, int(x0)), max(0, int(y0))
            x1, y1 = min(w - 1, int(x1)), min(h - 1, int(y1))
            if x1 - x0 < 3 or y1 - y0 < 3:
                return
            self._push_history()
            try:
                from engine_v2.date_blur_v2 import blur_region_manual
                self._original = blur_region_manual(
                    self._original, (x0, y0, x1 - x0, y1 - y0))
                self.status_label.setText("طُمس التاريخ بتمويه طفيف بلون المنتج ✓")
            except Exception as exc:
                self.status_label.setText(f"تعذر الطمس: {exc}")
            self._schedule_preview()
            return

        if tool_base == EditorCanvas.TOOL_REGION_RECT:
            (x0, y0), (x1, y1) = points
            x0, y0 = max(0, int(x0)), max(0, int(y0))
            x1, y1 = min(w - 1, int(x1)), min(h - 1, int(y1))
            if x1 - x0 < 3 or y1 - y0 < 3:
                return
            self._push_history()
            if self._region_mask is None:
                self._region_mask = np.zeros((h, w), np.uint8)
            self._region_mask[y0:y1 + 1, x0:x1 + 1] = 255
            self._region_active = True
            self.region_only_cb.setChecked(True)
            self._update_region_overlay()
            self.status_label.setText("أُضيفت منطقة عزل مستطيلة ✓")
            return

        # فرش: نرسم خطوطًا بين النقاط
        pts = [(int(round(x)), int(round(y))) for x, y in points]
        if tool_base == EditorCanvas.TOOL_REGION:
            if not live:
                self._push_history()
            if self._region_mask is None:
                self._region_mask = np.zeros((h, w), np.uint8)
            for i in range(len(pts)):
                p0 = pts[max(0, i - 1)]
                cv2.line(self._region_mask, p0, pts[i], 255,
                         thickness=max(4, size), lineType=cv2.LINE_AA)
            self._region_active = True
            if not live:
                self.region_only_cb.setChecked(True)
            self._update_region_overlay()
            return

        if tool_base in (EditorCanvas.TOOL_ERASE, EditorCanvas.TOOL_RESTORE):
            if not live:
                self._push_history()
            if self._alpha_manual is None:
                self._alpha_manual = np.full((h, w), 127, np.uint8)  # 127=محايد
            value = 0 if tool_base == EditorCanvas.TOOL_ERASE else 255
            for i in range(len(pts)):
                p0 = pts[max(0, i - 1)]
                cv2.line(self._alpha_manual, p0, pts[i], value,
                         thickness=max(4, size), lineType=cv2.LINE_AA)
            self._schedule_preview()

    def _auto_blur_dates(self) -> None:
        """كشف وطمس التواريخ المطبوعة تلقائيًا في الصورة الحالية."""
        if self._original is None:
            return
        self.status_label.setText("جارٍ كشف التواريخ المطبوعة...")
        QApplication.processEvents()
        try:
            from engine_v2.date_blur_v2 import auto_blur_dates
            self._push_history()
            out, n = auto_blur_dates(self._original)
            if n > 0:
                self._original = out
                self._schedule_preview()
                self.status_label.setText(f"طُمس {n} تاريخ مطبوع ✓")
            else:
                self.status_label.setText(
                    "لم يُكشف تاريخ تلقائيًا — استخدم (طمس تاريخ يدوي) واسحب فوقه")
        except Exception as exc:
            self.status_label.setText(f"تعذر الكشف التلقائي: {exc}")

    def _clear_region(self) -> None:
        self._region_mask = None
        self._region_active = False
        self.region_only_cb.setChecked(False)
        self.canvas.set_overlay(None)
        self.status_label.setText("أُزيل تحديد المنطقة")

    def _update_region_overlay(self) -> None:
        if self._region_mask is None:
            self.canvas.set_overlay(None)
            return
        h, w = self._region_mask.shape
        overlay = np.zeros((h, w, 4), np.uint8)
        overlay[:, :, 0] = 235   # R
        overlay[:, :, 1] = 64
        overlay[:, :, 2] = 52
        overlay[:, :, 3] = (self._region_mask * 0.28).astype(np.uint8)
        self.canvas.set_overlay(overlay)

    def _blend_region(self, before: np.ndarray, after: np.ndarray) -> np.ndarray:
        """دمج نتيجة معالجة على المنطقة المحددة فقط مع feathering."""
        import cv2
        m = self._region_mask
        feather = self.feather_slider.value() * 2 + 1
        if feather > 1:
            m = cv2.GaussianBlur(m, (feather, feather), 0)
        mf = (m.astype(np.float32) / 255.0)[:, :, None]
        return (after.astype(np.float32) * mf +
                before.astype(np.float32) * (1 - mf)).astype(np.uint8)

    def _crop_to_region(self) -> None:
        if self._region_mask is None:
            QMessageBox.information(self, "اقتصاص",
                                    "حدد منطقة أولًا (مستطيل أو فرشاة تحديد).")
            return
        ys, xs = np.where(self._region_mask > 0)
        if len(xs) < 4:
            return
        self._push_history()
        x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
        self._original = self._original[y0:y1 + 1, x0:x1 + 1].copy()
        if self._base is not None:
            self._base = self._base[y0:y1 + 1, x0:x1 + 1].copy()
        if self._alpha_manual is not None:
            self._alpha_manual = self._alpha_manual[y0:y1 + 1, x0:x1 + 1].copy()
        self._region_mask = None
        self._region_active = False
        self.canvas.set_overlay(None)
        self.canvas._first_fit_done = False
        self.status_label.setText("تم الاقتصاص للتحديد ✓")
        self._recompose(fit=True)

    def _zero_sliders(self, silent: bool = False) -> None:
        for s in self._sliders.values():
            s.blockSignals(True)
            s.setValue(0)
            s.blockSignals(False)
        if not silent:
            self._schedule_preview()

    # -------------------------------------------------------- compositing
    def _schedule_preview(self) -> None:
        self._preview_timer.start()

    def _compose_rgba(self) -> np.ndarray:
        """يبني BGRA: الأساس (ذكي أو الأصل) + تعديلات القلم + المنزلقات."""
        import cv2
        if self._base is not None:
            rgba = self._base.copy()
        else:
            rgba = cv2.cvtColor(self._original, cv2.COLOR_BGR2BGRA)
            rgba[:, :, 3] = 255

        # تعديلات القلم على الألفا (تبييض = 0، استرجاع = 255، 127 = محايد)
        if self._alpha_manual is not None:
            am = self._alpha_manual
            feather = self.feather_slider.value() * 2 + 1
            if feather > 1:
                am = cv2.GaussianBlur(am, (feather, feather), 0)
            a = rgba[:, :, 3].astype(np.float32)
            erase_w = np.clip((127.0 - am.astype(np.float32)) / 127.0, 0, 1)
            restore_w = np.clip((am.astype(np.float32) - 127.0) / 128.0, 0, 1)
            a = a * (1 - erase_w)
            a = np.maximum(a, restore_w * 255.0)
            rgba[:, :, 3] = np.clip(a, 0, 255).astype(np.uint8)
            # الاسترجاع يعيد بكسلات الأصل الملونة
            rw = restore_w > 0.05
            if rw.any() and self._original is not None:
                rgba[:, :, :3][rw] = self._original[:, :, :3][rw]

        # منزلقات التحسين
        rgb = rgba[:, :, :3]
        adjusted = self._apply_sliders(rgb)
        if self.region_only_cb.isChecked() and self._region_mask is not None \
                and self._sliders_active():
            adjusted = self._blend_region(rgb, adjusted)
        rgba[:, :, :3] = adjusted

        # إزالة الانعكاسات (معاينة فورية عند التفعيل)
        if getattr(self, "glare_enable_cb", None) is not None and \
                self.glare_enable_cb.isChecked():
            from engine_v2.edge_refine_v2 import remove_glare
            st = self.glare_strength.value() / 100.0
            rgba[:, :, :3] = remove_glare(rgba[:, :, :3], st)

        # تنقيح الاستوديو (حواف نظيفة + لمعة متجر) — معاينة فورية
        if getattr(self, "polish_enable_cb", None) is not None and \
                self.polish_enable_cb.isChecked():
            from engine_v2.edge_refine_v2 import polish_for_store
            ps = self.polish_strength.value() / 100.0
            p_alpha = rgba[:, :, 3] if self._cutout_applied else None
            p_rgb, p_a = polish_for_store(rgba[:, :, :3], p_alpha, ps)
            rgba[:, :, :3] = p_rgb
            if p_a is not None:
                rgba[:, :, 3] = p_a

        # التدوير — القيمة الداخلية بأعشار الدرجة (دقة 0.1°)
        angle = self.rotate_slider.value() / 10.0
        if angle:
            h, w = rgba.shape[:2]
            M = cv2.getRotationMatrix2D((w / 2, h / 2), -angle, 1.0)
            cos, sin = abs(M[0, 0]), abs(M[0, 1])
            nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
            M[0, 2] += nw / 2 - w / 2
            M[1, 2] += nh / 2 - h / 2
            rgba = cv2.warpAffine(rgba, M, (nw, nh), flags=cv2.INTER_LINEAR,
                                  borderMode=cv2.BORDER_CONSTANT,
                                  borderValue=(0, 0, 0, 0) if self._cutout_applied
                                  else (255, 255, 255, 255))
        return rgba

    def _rot_released(self) -> None:
        """إخفاء الشبكة الإرشادية بعد انتهاء سحب منزلق التوزين."""
        try:
            self.canvas.show_grid = False
            self.canvas.viewport().update()
        except Exception:
            pass

    def _auto_level(self) -> None:
        """توزين تلقائي ذكي: يكشف ميل المنتج من قناع ألفا ويصححه."""
        if self._original is None:
            return
        try:
            from engine_v2.edge_refine_v2 import auto_straighten_angle
            # نستخدم ألفا بعد القص إن وجدت، وإلا نقدّر من السطوع
            if self._cutout_applied and self._base is not None:
                alpha = self._base[:, :, 3]
            else:
                import cv2 as _cv
                gray = _cv.cvtColor(self._original[:, :, :3],
                                    _cv.COLOR_BGR2GRAY)
                alpha = (gray < 245).astype("uint8") * 255
            ang = auto_straighten_angle(alpha)
            if abs(ang) < 0.1:
                QMessageBox.information(
                    self, "توزين تلقائي",
                    "المنتج متوازن بالفعل — لا حاجة للتصحيح.")
                return
            self.rotate_slider.setValue(int(round(ang * 10)))
            self.status_label.setText(f"تم التوزين التلقائي: {ang:+.1f}° ✓")
        except Exception as exc:
            QMessageBox.warning(self, "توزين تلقائي",
                                f"تعذر الكشف التلقائي: {exc}")

    def _sliders_active(self) -> bool:
        return any(s.value() != 0 for s in self._sliders.values())

    def _apply_sliders(self, rgb: np.ndarray) -> np.ndarray:
        import cv2
        out = rgb.astype(np.float32)
        b = self._sliders["brightness"].value()
        c = self._sliders["contrast"].value()
        sat = self._sliders["saturation"].value()
        sh = self._sliders["sharpness"].value()
        dn = self._sliders["denoise"].value()
        if b:
            out = out + b * 1.2
        if c:
            f = 1.0 + c / 130.0
            out = (out - 127.5) * f + 127.5
        out = np.clip(out, 0, 255).astype(np.uint8)
        if sat:
            hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV).astype(np.float32)
            hsv[:, :, 1] = np.clip(hsv[:, :, 1] * (1.0 + sat / 120.0), 0, 255)
            out = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
        if dn:
            k = 3 if dn < 50 else 5
            out = cv2.bilateralFilter(out, k * 2 + 1, 20 + dn, 20 + dn)
        if sh:
            blur = cv2.GaussianBlur(out, (0, 0), 2.2)
            amount = sh / 55.0
            out = cv2.addWeighted(out, 1 + amount, blur, -amount, 0)
        return out

    def _flatten_white(self, rgba: np.ndarray) -> np.ndarray:
        a = rgba[:, :, 3:4].astype(np.float32) / 255.0
        rgb = rgba[:, :, :3].astype(np.float32)
        return np.clip(rgb * a + 255.0 * (1 - a), 0, 255).astype(np.uint8)

    def _recompose(self, fit: bool = False) -> None:
        if self._original is None:
            return
        rgba = self._compose_rgba()
        # الظل
        if self._shadow_opts is not None and self._cutout_applied:
            from engine_v2.shadow_v2 import apply_shadow
            pad = int(rgba.shape[1] * 0.06)
            import cv2
            padded = cv2.copyMakeBorder(rgba, 0, pad, pad, pad,
                                        cv2.BORDER_CONSTANT,
                                        value=(0, 0, 0, 0))
            rgba = apply_shadow(padded, self._shadow_opts)
        self._composited = self._flatten_white(rgba)
        shown = self._original if self._show_before else self._composited
        self.canvas.set_image(shown, fit=fit)
        self._update_region_overlay()

    def _toggle_before(self, show_before: bool) -> None:
        self._show_before = show_before
        if self._original is None:
            return
        shown = self._original if show_before else (
            self._composited if self._composited is not None else self._original)
        self.canvas.set_image(shown)

    # ------------------------------------------------------- history
    def _snapshot(self) -> dict:
        return {
            "original": None if self._original is None else self._original.copy(),
            "base": None if self._base is None else self._base.copy(),
            "alpha": None if self._alpha_manual is None else self._alpha_manual.copy(),
            "region": None if self._region_mask is None else self._region_mask.copy(),
            "cutout": self._cutout_applied,
            "shadow": None if self._shadow_opts is None else self._shadow_opts.to_dict(),
        }

    def _restore(self, snap: dict) -> None:
        from engine_v2.shadow_v2 import ShadowOptions
        self._original = snap["original"]
        self._base = snap["base"]
        self._alpha_manual = snap["alpha"]
        self._region_mask = snap["region"]
        self._region_active = snap["region"] is not None
        self._cutout_applied = snap["cutout"]
        self._shadow_opts = None if snap["shadow"] is None \
            else ShadowOptions.from_dict(snap["shadow"])
        self._recompose()

    def _push_history(self) -> None:
        self._history.append(self._snapshot())
        if len(self._history) > 15:
            self._history.pop(0)
        self._redo.clear()

    def _undo(self) -> None:
        if not self._history:
            return
        self._redo.append(self._snapshot())
        self._restore(self._history.pop())
        self.status_label.setText("تراجع ✓")

    def _redo_action(self) -> None:
        if not self._redo:
            return
        self._history.append(self._snapshot())
        self._restore(self._redo.pop())
        self.status_label.setText("إعادة ✓")

    def _reset_all(self) -> None:
        if self._image_path:
            self._load_image(self._image_path)
            self.status_label.setText("أُعيد ضبط كل شيء للأصل")


# ربط أزرار الفرش اليدوية بعد إنشاء الأزرار (خارج init لتفادي forward refs)
def _wire_manual_buttons(dlg: V2PhotoEditorDialog) -> None:
    dlg.erase_btn.toggled.connect(
        lambda on: dlg._pick_tool(EditorCanvas.TOOL_ERASE, on, dlg.erase_btn))
    dlg.restore_btn.toggled.connect(
        lambda on: dlg._pick_tool(EditorCanvas.TOOL_RESTORE, on, dlg.restore_btn))
    dlg.pan_btn.toggled.connect(
        lambda on: dlg._pick_tool(EditorCanvas.TOOL_PAN, on, dlg.pan_btn))


_orig_init = V2PhotoEditorDialog.__init__


def _init_with_wiring(self, *a, **kw):
    _orig_init(self, *a, **kw)
    _wire_manual_buttons(self)


V2PhotoEditorDialog.__init__ = _init_with_wiring
