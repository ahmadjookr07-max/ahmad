from __future__ import annotations

import os
import math

# Qt 6 يدعم Per-Monitor DPI تلقائياً، وهذه القيم تمنع التقريب الخشن
# لعوامل 125% و150% عند تشغيل الحزمة على Windows.
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

import re
import shutil
import sys
import traceback
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, QItemSelectionModel, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QImageReader, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from smart_catalog_vision.final_images import FinalImageOptions
from smart_catalog_vision import pipeline as _vision_pipeline
from smart_catalog_vision.pipeline import (
    SUPPORTED_IMAGE_EXTENSIONS,
    BatchItemResult,
    BatchRunResult,
    IndividualImagePreview,
    apply_individual_image_edit,
    apply_manual_link,
    apply_manual_links,
    preview_individual_image_edit,
    run_batch,
)


_ORIGINAL_PREPARE_INDIVIDUAL_SOURCE = _vision_pipeline._prepare_individual_source


def _prepare_individual_perspective_source(
    source: Path,
    staging_dir: Path,
    crop_box: Iterable[float] | None,
):
    """Rectify an eight-coordinate manual crop while preserving legacy four-edge crops."""

    if crop_box is None:
        return _ORIGINAL_PREPARE_INDIVIDUAL_SOURCE(source, staging_dir, crop_box)
    values = tuple(float(value) for value in crop_box)
    if len(values) == 4:
        return _ORIGINAL_PREPARE_INDIVIDUAL_SOURCE(source, staging_dir, values)
    if len(values) not in (8, 9):
        raise ValueError("حدود القص المنظوري غير مكتملة؛ حدد الزوايا الأربع")

    coordinates = values[:8]
    if not all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in coordinates):
        raise ValueError("إحدى زوايا القص المنظوري تقع خارج الصورة")
    normalized = _vision_pipeline.np.asarray(coordinates, dtype=_vision_pipeline.np.float32).reshape(4, 2)
    if not bool(_vision_pipeline.cv2.isContourConvex(normalized)):
        raise ValueError("زوايا القص متقاطعة؛ رتّبها حول المنتج دون عبور الأضلاع")
    if abs(float(_vision_pipeline.cv2.contourArea(normalized))) < 0.0016:
        raise ValueError("مساحة القص المنظوري صغيرة جدًا؛ وسّع الزوايا حول المنتج")

    image = _vision_pipeline.read_image(source, _vision_pipeline.cv2.IMREAD_UNCHANGED)
    if image is None or image.size == 0:
        raise ValueError("تعذر قراءة الصورة الأصلية لتطبيق القص المنظوري")
    image_height, image_width = image.shape[:2]
    source_points = normalized.copy()
    source_points[:, 0] *= max(1, image_width - 1)
    source_points[:, 1] *= max(1, image_height - 1)

    top_left, top_right, bottom_right, bottom_left = source_points
    top_width = float(_vision_pipeline.np.linalg.norm(top_right - top_left))
    bottom_width = float(_vision_pipeline.np.linalg.norm(bottom_right - bottom_left))
    left_height = float(_vision_pipeline.np.linalg.norm(bottom_left - top_left))
    right_height = float(_vision_pipeline.np.linalg.norm(bottom_right - top_right))
    output_width = max(2.0, top_width, bottom_width)
    output_height = max(2.0, left_height, right_height)

    target_ratio = values[8] if len(values) == 9 else 0.0
    if math.isfinite(target_ratio) and target_ratio > 0.0:
        natural_area = max(4.0, output_width * output_height)
        output_width = math.sqrt(natural_area * target_ratio)
        output_height = output_width / target_ratio
    width_px = max(2, min(12_000, int(round(output_width))))
    height_px = max(2, min(12_000, int(round(output_height))))
    destination_points = _vision_pipeline.np.asarray(
        ((0.0, 0.0), (width_px - 1.0, 0.0), (width_px - 1.0, height_px - 1.0), (0.0, height_px - 1.0)),
        dtype=_vision_pipeline.np.float32,
    )
    transform = _vision_pipeline.cv2.getPerspectiveTransform(source_points, destination_points)
    rectified = _vision_pipeline.cv2.warpPerspective(
        image,
        transform,
        (width_px, height_px),
        flags=_vision_pipeline.cv2.INTER_CUBIC,
        borderMode=_vision_pipeline.cv2.BORDER_REPLICATE,
    )
    if rectified is None or rectified.size == 0:
        raise ValueError("تعذر تصحيح منظور الجزء المحدد من الصورة")

    staging_dir.mkdir(parents=True, exist_ok=True)
    prepared = staging_dir / "manual-perspective-source.png"
    _vision_pipeline._write_temporary_png(prepared, rectified)
    return prepared, coordinates


_vision_pipeline._prepare_individual_source = _prepare_individual_perspective_source


APP_NAME = "Ahmed Al-Faifi Market Image Studio"
APP_VERSION = "1.2.1"
COPYRIGHT = "حقوق النشر © 2026 احمد الفيفي"
DATA_ROOT = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents" / "SmartCatalogVision"
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def _normalize_search_text(value: object) -> str:
    """Normalize Arabic/Latin text and digits for forgiving local result search."""

    text = unicodedata.normalize("NFKD", str(value or "")).translate(_ARABIC_DIGITS).casefold()
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = text.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه"}))
    text = re.sub(r"[^0-9a-z\u0600-\u06ff]+", " ", text)
    return " ".join(text.split())


def _friendly_error_message(traceback_text: str) -> str:
    """Turn technical worker failures into safe, actionable Arabic guidance."""

    folded = str(traceback_text or "").casefold()
    if "permissionerror" in folded or "permission denied" in folded or "errno 13" in folded:
        return (
            "تعذر الوصول إلى أحد الملفات أو الكتابة في المجلد المحدد. "
            "أغلق ملف Excel إن كان مفتوحًا، وتأكد من صلاحية الكتابة ثم أعد المحاولة."
        )
    if "filenotfounderror" in folded or "no such file or directory" in folded:
        return (
            "تعذر العثور على أحد ملفات المهمة. تأكد من أن ملف Excel والصور لم تُنقل أو تُحذف، "
            "ثم اخترها من جديد."
        )
    if "memoryerror" in folded or "out of memory" in folded:
        return (
            "الذاكرة المتاحة لا تكفي لإكمال هذه الدفعة. أغلق البرامج غير المستخدمة أو قسّم الصور "
            "إلى دفعات أصغر ثم أعد المحاولة."
        )
    if "onnxruntime" in folded or "u2net" in folded:
        return (
            "تعذر تشغيل العزل المحلي لهذه المهمة. أعد تشغيل التطبيق وحاول مجددًا، أو عطّل عزل "
            "الخلفية مؤقتًا لإكمال تجهيز الصور."
        )

    last_line = next(
        (line.strip() for line in reversed(str(traceback_text or "").splitlines()) if line.strip()),
        "",
    )
    detail = last_line.split(":", 1)[1].strip() if ":" in last_line else last_line
    if detail and re.search(r"[\u0600-\u06ff]", detail):
        return f"{detail}\nراجع الملفات أو القيمة المذكورة ثم أعد المحاولة."
    return (
        "حدث خطأ غير متوقع أثناء تنفيذ المهمة. أعد المحاولة بعد التحقق من الملفات والمساحة المتاحة؛ "
        "وإذا تكرر الخطأ فأرسل سجل التفاصيل للدعم الفني."
    )


JOBS_ROOT = DATA_ROOT / "Jobs"
DATA_ROOT.mkdir(parents=True, exist_ok=True)
JOBS_ROOT.mkdir(parents=True, exist_ok=True)


def bundled_asset(filename: str) -> Path:
    """Return an application asset path in source and PyInstaller builds."""
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    candidates = (
        bundle_root / "windows_app" / "assets" / filename,
        bundle_root / "assets" / filename,
        Path(__file__).resolve().parent / "assets" / filename,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[-1]


STATUS_TEXT = {
    "matched": "مطابق آليًا",
    "manual": "مرتبط يدويًا",
    "review": "يحتاج مراجعة",
    "error": "خطأ",
}
STATUS_COLORS = {
    "matched": (16, 135, 92),
    "manual": (37, 99, 235),
    "review": (202, 138, 4),
    "error": (203, 45, 62),
}


class ImageListWidget(QListWidget):
    files_dropped = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QListWidget.ExtendedSelection)
        self.setToolTip("يمكنك سحب الصور أو مجلد صور وإفلاته هنا")

    def dragEnterEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if not event.mimeData().hasUrls():
            super().dropEvent(event)
            return
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        self.files_dropped.emit(paths)
        event.acceptProposedAction()


class BatchWorker(QThread):
    progress_changed = Signal(int, int, str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        catalog_path: Path,
        image_paths: list[Path],
        workspace: Path,
        remove_background: bool,
        enhance_product: bool,
        image_options: FinalImageOptions | None = None,
    ) -> None:
        super().__init__()
        self.catalog_path = catalog_path
        self.image_paths = image_paths
        self.workspace = workspace
        self.remove_background = remove_background
        self.enhance_product = enhance_product
        self.image_options = image_options

    def run(self) -> None:
        try:
            result = run_batch(
                self.catalog_path,
                self.image_paths,
                self.workspace,
                profile_name="كتالوج برنامج Windows",
                remove_background=self.remove_background,
                enhance_product=self.enhance_product,
                final_image_options=self.image_options,
                maximum_barcode_tier=3,
                progress=lambda done, total, name: self.progress_changed.emit(done, total, name),
            )
            self.completed.emit(result)
        except Exception:
            self.failed.emit(traceback.format_exc())


class ManualLinkWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        workspace: Path,
        source_names: str | Iterable[str],
        item_code: str,
        remove_background: bool,
        enhance_product: bool,
        image_options: FinalImageOptions | None = None,
    ) -> None:
        super().__init__()
        self.workspace = workspace
        if isinstance(source_names, str):
            self.source_names = (source_names,)
        else:
            self.source_names = tuple(dict.fromkeys(str(name) for name in source_names if str(name)))
        if not self.source_names:
            raise ValueError("لم تُحدد صور للربط")
        # يبقى الاسم المفرد متاحاً للتوافق مع اختبارات وملحقات الإصدار السابق.
        self.source_name = self.source_names[0]
        self.item_code = item_code
        self.remove_background = remove_background
        self.enhance_product = enhance_product
        self.image_options = image_options

    def run(self) -> None:
        try:
            if len(self.source_names) == 1:
                result = apply_manual_link(
                    self.workspace,
                    self.source_name,
                    self.item_code,
                    remove_background=self.remove_background,
                    enhance_product=self.enhance_product,
                    final_image_options=self.image_options,
                )
            else:
                result = apply_manual_links(
                    self.workspace,
                    self.source_names,
                    self.item_code,
                    remove_background=self.remove_background,
                    enhance_product=self.enhance_product,
                    final_image_options=self.image_options,
                )
            self.completed.emit(result)
        except Exception:
            self.failed.emit(traceback.format_exc())


class IndividualEditWorker(QThread):
    progress_changed = Signal(int, int, str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        workspace: Path,
        source_name: str,
        *,
        preview_only: bool,
        manual_crop: tuple[float, ...] | None,
        smart_enhance: bool,
        enhancement_strength: int,
        smart_crop: bool,
        auto_straighten: bool,
        remove_background: bool,
        image_options: FinalImageOptions | None = None,
    ) -> None:
        super().__init__()
        self.workspace = workspace
        self.source_name = source_name
        self.preview_only = bool(preview_only)
        self.manual_crop = manual_crop
        self.smart_enhance = bool(smart_enhance)
        self.enhancement_strength = int(enhancement_strength)
        self.smart_crop = bool(smart_crop)
        self.auto_straighten = bool(auto_straighten)
        self.remove_background = bool(remove_background)
        self.image_options = image_options

    def run(self) -> None:
        try:
            arguments = {
                "manual_crop": self.manual_crop,
                "smart_enhance": self.smart_enhance,
                "enhancement_strength": self.enhancement_strength,
                "smart_crop": self.smart_crop,
                "auto_straighten": self.auto_straighten,
                "remove_background": self.remove_background,
                "final_image_options": self.image_options,
            }
            if self.preview_only:
                self.progress_changed.emit(0, 1, "تحليل الصورة وتجهيز المعاينة")
                result = preview_individual_image_edit(
                    self.workspace,
                    self.source_name,
                    **arguments,
                )
                self.progress_changed.emit(1, 1, "المعاينة جاهزة قبل الحفظ")
            else:
                result = apply_individual_image_edit(
                    self.workspace,
                    self.source_name,
                    progress=lambda done, total, name: self.progress_changed.emit(done, total, name),
                    **arguments,
                )
            self.completed.emit(result)
        except Exception:
            self.failed.emit(traceback.format_exc())


class StatCard(QFrame):
    def __init__(self, title: str, color: str) -> None:
        super().__init__()
        self.setObjectName("statCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)
        self.value = QLabel("0")
        self.value.setAlignment(Qt.AlignCenter)
        self.value.setStyleSheet(f"font-size: 24px; font-weight: 800; color: {color};")
        label = QLabel(title)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: #64748b; font-size: 11px;")
        layout.addWidget(self.value)
        layout.addWidget(label)


class ZoomableImageView(QScrollArea):
    """Large product preview with a movable four-corner perspective crop."""

    crop_changed = Signal(object)
    _MIN_CROP_SIZE = 0.012
    _HANDLE_RADIUS = 7.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap = QPixmap()
        self._path: Path | None = None
        self._zoom = 1.0
        self._fit_to_view = True
        self._crop_enabled = False
        self._crop_box: tuple[float, ...] | None = None
        self._crop_aspect_ratio: float | None = None
        self._crop_drag_mode: str | None = None
        self._crop_drag_start: QPointF | None = None
        self._crop_origin_box: tuple[float, ...] | None = None
        self.setObjectName("previewScroll")
        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(285)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setToolTip(
            "اسحب إطارًا أوليًا حول المنتج، ثم حرّك كل زاوية مستقلة حتى تتبع ميل العبوة. "
            "اسحب من داخل الإطار لتحريكه، واستخدم Ctrl مع عجلة الفأرة للتكبير."
        )
        self.image_label = QLabel("لا توجد صورة")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setObjectName("previewImage")
        self.image_label.setMinimumSize(420, 270)
        self.image_label.setMouseTracking(True)
        self.image_label.setFocusPolicy(Qt.StrongFocus)
        self.image_label.installEventFilter(self)
        self.setWidget(self.image_label)

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def crop_box(self) -> tuple[float, ...] | None:
        return self._crop_box

    @property
    def crop_enabled(self) -> bool:
        return self._crop_enabled

    @property
    def crop_aspect_ratio(self) -> float | None:
        return self._crop_aspect_ratio

    @staticmethod
    def _quad_points(box: tuple[float, ...]) -> tuple[QPointF, QPointF, QPointF, QPointF]:
        return (
            QPointF(box[0], box[1]),
            QPointF(box[2], box[3]),
            QPointF(box[4], box[5]),
            QPointF(box[6], box[7]),
        )

    @staticmethod
    def _quad_tuple(points: Iterable[QPointF]) -> tuple[float, ...]:
        values: list[float] = []
        for point in points:
            values.extend((float(point.x()), float(point.y())))
        return tuple(values)

    @staticmethod
    def _edge_length(first: QPointF, second: QPointF, width: float, height: float) -> float:
        dx = (second.x() - first.x()) * width
        dy = (second.y() - first.y()) * height
        return (dx * dx + dy * dy) ** 0.5

    def crop_pixel_size(self) -> tuple[int, int] | None:
        if self._crop_box is None or self._pixmap.isNull():
            return None
        top_left, top_right, bottom_right, bottom_left = self._quad_points(self._crop_box)
        image_width = float(self._pixmap.width())
        image_height = float(self._pixmap.height())
        width = max(
            self._edge_length(top_left, top_right, image_width, image_height),
            self._edge_length(bottom_left, bottom_right, image_width, image_height),
        )
        height = max(
            self._edge_length(top_left, bottom_left, image_width, image_height),
            self._edge_length(top_right, bottom_right, image_width, image_height),
        )
        if self._crop_aspect_ratio is not None:
            natural_area = max(1.0, width * height)
            width = (natural_area * self._crop_aspect_ratio) ** 0.5
            height = width / self._crop_aspect_ratio
        return max(1, int(round(width))), max(1, int(round(height)))

    def crop_area_ratio(self) -> float:
        if self._crop_box is None:
            return 0.0
        points = self._quad_points(self._crop_box)
        twice_area = 0.0
        for index, point in enumerate(points):
            following = points[(index + 1) % 4]
            twice_area += point.x() * following.y() - following.x() * point.y()
        return min(1.0, max(0.0, abs(twice_area) / 2.0))

    def set_crop_mode(self, enabled: bool) -> None:
        self._crop_enabled = bool(enabled) and not self._pixmap.isNull()
        self._crop_drag_mode = None
        self._crop_drag_start = None
        self._crop_origin_box = None
        self._update_crop_cursor(None)
        self._render()

    def set_crop_aspect_ratio(self, ratio: float | None, *, emit: bool = True) -> None:
        value = float(ratio) if ratio not in (None, 0, 0.0) else None
        self._crop_aspect_ratio = value if value is not None and value > 0 else None
        self._render()
        if emit:
            self.crop_changed.emit(self._crop_box)

    @classmethod
    def _is_valid_quad(cls, points: tuple[QPointF, QPointF, QPointF, QPointF]) -> bool:
        xs = [point.x() for point in points]
        ys = [point.y() for point in points]
        if max(xs) - min(xs) < cls._MIN_CROP_SIZE or max(ys) - min(ys) < cls._MIN_CROP_SIZE:
            return False
        crosses: list[float] = []
        for index in range(4):
            first = points[index]
            second = points[(index + 1) % 4]
            third = points[(index + 2) % 4]
            crosses.append(
                (second.x() - first.x()) * (third.y() - second.y())
                - (second.y() - first.y()) * (third.x() - second.x())
            )
        epsilon = 1e-7
        if not (all(value > epsilon for value in crosses) or all(value < -epsilon for value in crosses)):
            return False
        twice_area = sum(
            points[index].x() * points[(index + 1) % 4].y()
            - points[(index + 1) % 4].x() * points[index].y()
            for index in range(4)
        )
        return abs(twice_area) >= cls._MIN_CROP_SIZE * cls._MIN_CROP_SIZE * 2.0

    def set_crop_box(
        self,
        box: tuple[float, ...] | None,
        *,
        emit: bool = False,
    ) -> None:
        candidate: tuple[float, ...] | None = None
        if box is not None:
            values = tuple(max(0.0, min(1.0, float(value))) for value in box)
            if len(values) == 4:
                left, top, right, bottom = values
                left, right = sorted((left, right))
                top, bottom = sorted((top, bottom))
                values = (left, top, right, top, right, bottom, left, bottom)
            if len(values) != 8:
                raise ValueError("يجب أن يحتوي إطار القص على أربع زوايا مستقلة")
            points = self._quad_points(values)
            if self._is_valid_quad(points):
                candidate = values
        self._crop_box = candidate
        self._render()
        if emit:
            self.crop_changed.emit(self._crop_box)

    def clear_crop(self, *, emit: bool = False) -> None:
        self.set_crop_box(None, emit=emit)

    def select_full_image(self, *, emit: bool = True) -> None:
        if self._pixmap.isNull():
            return
        self.set_crop_box((0.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0), emit=emit)

    def _displayed_pixmap_rect(self) -> QRectF:
        shown = self.image_label.pixmap()
        if shown.isNull():
            return QRectF()
        width = float(shown.width())
        height = float(shown.height())
        return QRectF(
            (self.image_label.width() - width) / 2.0,
            (self.image_label.height() - height) / 2.0,
            width,
            height,
        )

    def _normalized_image_point(self, position: QPointF, *, clamp: bool = False) -> QPointF | None:
        displayed = self._displayed_pixmap_rect()
        if displayed.isEmpty():
            return None
        if not clamp and not displayed.contains(position):
            return None
        return QPointF(
            max(0.0, min(1.0, (position.x() - displayed.left()) / displayed.width())),
            max(0.0, min(1.0, (position.y() - displayed.top()) / displayed.height())),
        )

    def _normalized_ratio(self) -> float | None:
        if self._crop_aspect_ratio is None or self._pixmap.isNull() or self._pixmap.width() <= 0:
            return None
        return self._crop_aspect_ratio * self._pixmap.height() / self._pixmap.width()

    def _quad_from_drag(self, first: QPointF, second: QPointF) -> tuple[float, ...]:
        dx = second.x() - first.x()
        dy = second.y() - first.y()
        target = self._normalized_ratio()
        if target is not None:
            width = abs(dx)
            height = abs(dy)
            if width < self._MIN_CROP_SIZE and height < self._MIN_CROP_SIZE:
                width = self._MIN_CROP_SIZE
                height = width / target
            elif width / max(height, 1e-9) > target:
                height = width / target
            else:
                width = height * target
            width = min(width, first.x() if dx < 0 else 1.0 - first.x())
            height = width / target
            max_height = first.y() if dy < 0 else 1.0 - first.y()
            if height > max_height:
                height = max_height
                width = height * target
            dx = -width if dx < 0 else width
            dy = -height if dy < 0 else height
        left = min(first.x(), first.x() + dx)
        right = max(first.x(), first.x() + dx)
        top = min(first.y(), first.y() + dy)
        bottom = max(first.y(), first.y() + dy)
        return left, top, right, top, right, bottom, left, bottom

    def _crop_hit_test(self, point: QPointF) -> str:
        if self._crop_box is None:
            return "new"
        displayed = self._displayed_pixmap_rect()
        threshold_x = 14.0 / max(1.0, displayed.width())
        threshold_y = 14.0 / max(1.0, displayed.height())
        points = self._quad_points(self._crop_box)
        for index, corner in enumerate(points):
            normalized_distance = (
                ((point.x() - corner.x()) / threshold_x) ** 2
                + ((point.y() - corner.y()) / threshold_y) ** 2
            )
            if normalized_distance <= 1.0:
                return f"corner_{index}"
        if QPolygonF(points).containsPoint(point, Qt.OddEvenFill):
            return "move"
        return "new"

    def _update_crop_cursor(self, mode: str | None) -> None:
        if not self._crop_enabled:
            self.image_label.setCursor(Qt.ArrowCursor)
            return
        cursor = {
            "move": Qt.SizeAllCursor,
            "corner_0": Qt.SizeFDiagCursor,
            "corner_2": Qt.SizeFDiagCursor,
            "corner_1": Qt.SizeBDiagCursor,
            "corner_3": Qt.SizeBDiagCursor,
        }.get(mode, Qt.CrossCursor)
        self.image_label.setCursor(cursor)

    def _resize_crop_quad(self, mode: str, point: QPointF) -> tuple[float, ...]:
        if self._crop_origin_box is None:
            return self._quad_from_drag(self._crop_drag_start or point, point)
        origin_points = list(self._quad_points(self._crop_origin_box))
        if mode == "move":
            start = self._crop_drag_start or point
            dx = point.x() - start.x()
            dy = point.y() - start.y()
            min_x = min(corner.x() for corner in origin_points)
            max_x = max(corner.x() for corner in origin_points)
            min_y = min(corner.y() for corner in origin_points)
            max_y = max(corner.y() for corner in origin_points)
            dx = max(-min_x, min(1.0 - max_x, dx))
            dy = max(-min_y, min(1.0 - max_y, dy))
            return self._quad_tuple(QPointF(corner.x() + dx, corner.y() + dy) for corner in origin_points)
        if mode.startswith("corner_"):
            index = int(mode.rsplit("_", 1)[1])
            origin_points[index] = QPointF(
                max(0.0, min(1.0, point.x())),
                max(0.0, min(1.0, point.y())),
            )
            points = tuple(origin_points)
            if self._is_valid_quad(points):
                return self._quad_tuple(points)
        return self._crop_origin_box

    def _nudge_crop(self, dx: float, dy: float) -> None:
        if self._crop_box is None:
            return
        points = self._quad_points(self._crop_box)
        min_x = min(corner.x() for corner in points)
        max_x = max(corner.x() for corner in points)
        min_y = min(corner.y() for corner in points)
        max_y = max(corner.y() for corner in points)
        dx = max(-min_x, min(1.0 - max_x, dx))
        dy = max(-min_y, min(1.0 - max_y, dy))
        self.set_crop_box(
            self._quad_tuple(QPointF(corner.x() + dx, corner.y() + dy) for corner in points),
            emit=True,
        )

    def eventFilter(self, watched, event) -> bool:  # type: ignore[no-untyped-def]
        if watched is self.image_label and self._crop_enabled and not self._pixmap.isNull():
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                point = self._normalized_image_point(event.position())
                if point is not None:
                    self.image_label.setFocus(Qt.MouseFocusReason)
                    self._crop_drag_mode = self._crop_hit_test(point)
                    self._crop_drag_start = point
                    self._crop_origin_box = self._crop_box
                    if self._crop_drag_mode == "new":
                        self._crop_box = None
                        self._render()
                    self._update_crop_cursor(self._crop_drag_mode)
                    event.accept()
                    return True
            elif event.type() == QEvent.MouseMove:
                point = self._normalized_image_point(
                    event.position(), clamp=self._crop_drag_mode is not None
                )
                if point is None:
                    return False
                if self._crop_drag_mode is None:
                    self._update_crop_cursor(self._crop_hit_test(point))
                    return False
                box = self._resize_crop_quad(self._crop_drag_mode, point)
                self.set_crop_box(box, emit=True)
                event.accept()
                return True
            elif event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                point = self._normalized_image_point(event.position(), clamp=True)
                if self._crop_drag_mode is not None and point is not None:
                    box = self._resize_crop_quad(self._crop_drag_mode, point)
                    self.set_crop_box(box, emit=True)
                self._crop_drag_mode = None
                self._crop_drag_start = None
                self._crop_origin_box = None
                self._update_crop_cursor(self._crop_hit_test(point) if point is not None else None)
                event.accept()
                return True
            elif event.type() == QEvent.Leave and self._crop_drag_mode is None:
                self._update_crop_cursor(None)
            elif event.type() == QEvent.KeyPress and self._crop_box is not None:
                step = 0.01 if event.modifiers() & Qt.ShiftModifier else 0.0025
                if event.key() == Qt.Key_Left:
                    self._nudge_crop(-step, 0.0)
                elif event.key() == Qt.Key_Right:
                    self._nudge_crop(step, 0.0)
                elif event.key() == Qt.Key_Up:
                    self._nudge_crop(0.0, -step)
                elif event.key() == Qt.Key_Down:
                    self._nudge_crop(0.0, step)
                elif event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
                    self.clear_crop(emit=True)
                else:
                    return False
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def set_image(self, path: Path | None) -> None:
        if path is None:
            self._path = None
            self._pixmap = QPixmap()
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText("لا توجد صورة")
            self.image_label.setToolTip("")
            self._resize_label_to_viewport()
            return

        candidate = path.expanduser()
        if not candidate.is_file():
            self._path = None
            self._pixmap = QPixmap()
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText(f"ملف الصورة غير موجود\n{candidate.name}")
            self.image_label.setToolTip(str(candidate))
            self._resize_label_to_viewport()
            return

        candidate = candidate.resolve()
        pixmap = QPixmap(str(candidate))
        if pixmap.isNull():
            self._path = None
            self._pixmap = QPixmap()
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText(f"تعذرت معاينة الصورة\n{candidate.name}\nاستخدم زر فتح كامل")
            self.image_label.setToolTip(str(candidate))
            self._resize_label_to_viewport()
            return
        self._path = candidate
        self._pixmap = pixmap
        self.image_label.setToolTip(str(candidate))
        self.fit_image()

    def _resize_label_to_viewport(self) -> None:
        viewport = self.viewport().size()
        self.image_label.resize(max(420, viewport.width() - 2), max(270, viewport.height() - 2))

    @staticmethod
    def _lerp(first: QPointF, second: QPointF, fraction: float) -> QPointF:
        return QPointF(
            first.x() + (second.x() - first.x()) * fraction,
            first.y() + (second.y() - first.y()) * fraction,
        )

    def _render(self) -> None:
        if self._pixmap.isNull():
            self._resize_label_to_viewport()
            return
        viewport = self.viewport().size()
        available_width = max(80, viewport.width() - 16)
        available_height = max(80, viewport.height() - 16)
        if self._fit_to_view:
            rendered = self._pixmap.scaled(
                available_width,
                available_height,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self._zoom = min(
                rendered.width() / max(1, self._pixmap.width()),
                rendered.height() / max(1, self._pixmap.height()),
            )
        else:
            target_width = max(1, min(14_000, int(round(self._pixmap.width() * self._zoom))))
            target_height = max(1, min(14_000, int(round(self._pixmap.height() * self._zoom))))
            rendered = self._pixmap.scaled(
                target_width,
                target_height,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        displayed = rendered
        if self._crop_enabled and self._crop_box is not None:
            displayed = rendered.copy()
            normalized = self._quad_points(self._crop_box)
            points = tuple(
                QPointF(point.x() * displayed.width(), point.y() * displayed.height())
                for point in normalized
            )
            polygon = QPolygonF(points)
            painter = QPainter(displayed)
            painter.setRenderHint(QPainter.Antialiasing, True)

            shade_path = QPainterPath()
            shade_path.setFillRule(Qt.OddEvenFill)
            shade_path.addRect(QRectF(0, 0, displayed.width(), displayed.height()))
            shade_path.addPolygon(polygon)
            shade_path.closeSubpath()
            painter.fillPath(shade_path, QColor(2, 8, 23, 158))

            painter.setPen(QPen(QColor(34, 211, 238), 3, Qt.SolidLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawPolygon(polygon)

            top_left, top_right, bottom_right, bottom_left = points
            painter.setPen(QPen(QColor(255, 255, 255, 145), 1, Qt.DashLine))
            for fraction in (1.0 / 3.0, 2.0 / 3.0):
                painter.drawLine(
                    self._lerp(top_left, top_right, fraction),
                    self._lerp(bottom_left, bottom_right, fraction),
                )
                painter.drawLine(
                    self._lerp(top_left, bottom_left, fraction),
                    self._lerp(top_right, bottom_right, fraction),
                )

            painter.setPen(QPen(QColor(8, 47, 73), 2))
            painter.setBrush(QColor(255, 255, 255))
            for handle in points:
                painter.drawRoundedRect(
                    QRectF(
                        handle.x() - self._HANDLE_RADIUS,
                        handle.y() - self._HANDLE_RADIUS,
                        self._HANDLE_RADIUS * 2.0,
                        self._HANDLE_RADIUS * 2.0,
                    ),
                    3.0,
                    3.0,
                )

            pixel_size = self.crop_pixel_size()
            bounds = polygon.boundingRect()
            if pixel_size is not None and bounds.width() >= 112 and bounds.height() >= 42:
                width_px, height_px = pixel_size
                badge_text = f"منظور {width_px} × {height_px} px"
                painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
                badge_width = min(190.0, max(132.0, bounds.width() - 16.0))
                text_rect = QRectF(bounds.left() + 8.0, bounds.top() + 8.0, badge_width, 26.0)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(8, 47, 73, 225))
                painter.drawRoundedRect(text_rect, 6, 6)
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(text_rect, Qt.AlignCenter, badge_text)
            painter.end()
        self.image_label.setText("")
        self.image_label.setPixmap(displayed)
        self.image_label.resize(
            max(rendered.width(), available_width),
            max(rendered.height(), available_height),
        )

    def zoom_in(self) -> None:
        if self._pixmap.isNull():
            return
        self._fit_to_view = False
        self._zoom = min(6.0, max(0.08, self._zoom) * 1.25)
        self._render()

    def zoom_out(self) -> None:
        if self._pixmap.isNull():
            return
        self._fit_to_view = False
        self._zoom = max(0.08, min(6.0, self._zoom) / 1.25)
        self._render()

    def actual_size(self) -> None:
        if self._pixmap.isNull():
            return
        self._fit_to_view = False
        self._zoom = 1.0
        self._render()

    def fit_image(self) -> None:
        if self._pixmap.isNull():
            return
        self._fit_to_view = True
        self._render()

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        if self._fit_to_view:
            self._render()

    def wheelEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.modifiers() & Qt.ControlModifier:
            if event.angleDelta().y() > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            event.accept()
            return

        vertical = self.verticalScrollBar()
        horizontal = self.horizontalScrollBar()
        can_scroll_image = vertical.maximum() > 0 or horizontal.maximum() > 0
        if can_scroll_image:
            super().wheelEvent(event)
            return

        event.ignore()


class ImagePreviewPane(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("previewFrame")
        self.setMinimumWidth(220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        label_title = QLabel(title)
        label_title.setObjectName("previewTitle")
        header.addWidget(label_title, 1)
        zoom_out = QPushButton("−")
        zoom_out.setObjectName("zoomButton")
        zoom_out.setToolTip("تصغير")
        zoom_in = QPushButton("+")
        zoom_in.setObjectName("zoomButton")
        zoom_in.setToolTip("تكبير")
        actual = QPushButton("100%")
        actual.setObjectName("zoomButton")
        actual.setToolTip("الحجم الأصلي لقراءة الباركود")
        fit = QPushButton("احتواء")
        fit.setObjectName("zoomButton")
        fit.setToolTip("احتواء الصورة داخل المساحة")
        self.open_button = QPushButton("فتح كامل")
        self.open_button.setObjectName("zoomButton")
        self.open_button.setToolTip("فتح الصورة في عارض Windows بالحجم الكامل")
        for button in (zoom_out, zoom_in, actual, fit, self.open_button):
            header.addWidget(button)
        layout.addLayout(header)

        self.viewer = ZoomableImageView()
        zoom_out.clicked.connect(self.viewer.zoom_out)
        zoom_in.clicked.connect(self.viewer.zoom_in)
        actual.clicked.connect(self.viewer.actual_size)
        fit.clicked.connect(self.viewer.fit_image)
        self.open_button.clicked.connect(self.open_image)
        self.open_button.setEnabled(False)
        layout.addWidget(self.viewer, 1)

        hint = QLabel("للقراءة الدقيقة: اضغط 100% ثم حرّك أشرطة التمرير، أو استخدم Ctrl + عجلة الفأرة.")
        hint.setObjectName("previewHint")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def set_image(self, path: Path | None) -> None:
        self.viewer.set_image(path)
        self.open_button.setEnabled(self.viewer.path is not None)

    def open_image(self) -> None:
        if self.viewer.path is not None and self.viewer.path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.viewer.path)))


class ProtectedEditDialog(QDialog):
    """Route every cancel path through the owner's unsaved-work confirmation."""

    close_requested = Signal()

    def reject(self) -> None:
        self.close_requested.emit()

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if not event.spontaneous():
            super().closeEvent(event)
            return
        event.ignore()
        self.close_requested.emit()

    def discard_and_close(self) -> None:
        super().reject()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.catalog_path: Path | None = None
        self.image_paths: list[Path] = []
        self.current_result: BatchRunResult | None = None
        self.current_workspace: Path | None = None
        self._pending_batch_workspace: Path | None = None
        self.batch_worker: BatchWorker | None = None
        self.manual_worker: ManualLinkWorker | None = None
        self.individual_worker: IndividualEditWorker | None = None
        self._pending_individual_position: tuple[str, int, int] | None = None
        self._individual_preview_active = False
        self._individual_preview_path: Path | None = None
        self._individual_editor_dirty = False
        self._pending_manual_position: tuple[str, int, int] | None = None
        self._pending_manual_source_names: tuple[str, ...] = ()
        self._manual_reference_source_name = ""
        self._result_items_by_name: dict[str, BatchItemResult] = {}
        self._result_thumbnail_cache: dict[str, QIcon] = {}
        self._visual_signature_cache: dict[str, tuple[float, ...]] = {}
        self._individual_edit_source_name = ""
        self._individual_crop_box: tuple[float, ...] | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(90)
        self._preview_timer.timeout.connect(self._render_selected_preview)
        self._setup_window()
        self._build_ui()
        self._apply_style()
        self._update_controls()

    def _setup_window(self) -> None:
        self.setWindowTitle(f"{APP_NAME} — {APP_VERSION}")
        # الحد المرن يناسب شاشة 1366×768 حتى مع تحجيم Windows بنسبة 150%؛
        # وتبقى الأقسام الطويلة داخل مناطق تمرير مستقلة بدلاً من الانضغاط.
        self.setMinimumSize(960, 600)
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(1380, 860)
        else:
            available = screen.availableGeometry()
            target_width = min(1380, max(840, int(available.width() * 0.94)))
            target_height = min(860, max(480, int(available.height() * 0.90)))
            self.resize(target_width, target_height)
        icon_path = bundled_asset("app_icon.png")
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setLayoutDirection(Qt.RightToLeft)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("applicationRoot")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(16, 12, 16, 10)
        root_layout.setSpacing(10)

        self.header_frame = QFrame()
        header = self.header_frame
        header.setObjectName("header")
        header.setFixedHeight(74)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 10, 20, 10)
        header_layout.setSpacing(14)
        title_block = QVBoxLayout()
        title_block.setSpacing(2)
        title = QLabel(APP_NAME)
        title.setObjectName("appTitle")
        subtitle = QLabel("مطابقة الكتالوج وتجهيز صور المنتجات باحتراف — محلي وآمن")
        subtitle.setObjectName("appSubtitle")
        subtitle.setWordWrap(False)
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        self.phase_label = QLabel("إعداد الدفعة")
        self.phase_label.setObjectName("phaseBadge")
        self.phase_label.setAlignment(Qt.AlignCenter)
        version = QLabel(f"Windows  •  الإصدار {APP_VERSION}")
        version.setObjectName("versionBadge")
        header_layout.addLayout(title_block, 1)
        header_layout.addWidget(self.phase_label)
        header_layout.addWidget(version)
        root_layout.addWidget(header)

        self.workflow_pages = QStackedWidget()
        self.workflow_pages.setObjectName("workflowPages")
        self.setup_page = self._build_inputs_panel()
        self.results_page = self._build_results_panel()
        self.individual_editor_dialog = self._build_individual_editor_dialog()
        self.workflow_pages.addWidget(self.setup_page)
        self.workflow_pages.addWidget(self.results_page)
        self.workflow_pages.setCurrentWidget(self.setup_page)
        root_layout.addWidget(self.workflow_pages, 1)

        footer = QHBoxLayout()
        footer.setSpacing(12)
        self.status_label = QLabel("جاهز. اختر ملف Excel ثم أضف الصور.")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setWordWrap(False)
        copyright_label = QLabel(COPYRIGHT)
        copyright_label.setObjectName("copyrightLabel")
        footer.addWidget(self.status_label, 1)
        footer.addWidget(copyright_label)
        root_layout.addLayout(footer)

        self.setCentralWidget(root)

    def _confirm_leave_results(self, destination: str) -> bool:
        if (
            self.workflow_pages.currentWidget() is not self.results_page
            or self.current_result is None
        ):
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(APP_NAME)
        box.setText("لديك نتائج مفتوحة قيد المراجعة")
        box.setInformativeText(
            f"سيؤدي {destination} إلى مغادرة صفحة المراجعة الحالية. "
            "النتائج المحفوظة لن تُحذف، لكن يُفضّل إنهاء الربط وتعديلات الصور أولًا."
        )
        stay_button = box.addButton("البقاء في المراجعة", QMessageBox.RejectRole)
        leave_button = box.addButton("المتابعة والمغادرة", QMessageBox.DestructiveRole)
        box.setDefaultButton(stay_button)
        box.exec()
        return box.clickedButton() is leave_button

    def _show_setup_page(self) -> None:
        if not self._confirm_leave_results("العودة إلى الإعداد"):
            return
        self.workflow_pages.setCurrentWidget(self.setup_page)
        self.phase_label.setText("إعداد الدفعة")
        self.status_label.setText("يمكنك تعديل الملفات والإعدادات ثم بدء المعالجة من جديد.")

    def _show_results_page(self) -> None:
        self.workflow_pages.setCurrentWidget(self.results_page)
        self.phase_label.setText("مراجعة النتائج")
        self._results_splitter_mode = ""
        QTimer.singleShot(0, self._update_results_splitter_for_width)
        QTimer.singleShot(0, self._render_selected_preview)

    def _update_results_splitter_for_width(self) -> None:
        """Keep the image dominant while preserving a readable three-column review list."""
        if not hasattr(self, "results_splitter") or not hasattr(self, "results_page"):
            return
        available = max(900, self.results_page.width() - 20)
        width_mode = "compact" if available < 1180 else "wide"
        height_mode = "short" if self.height() < 780 else "tall"
        mode = f"{width_mode}-{height_mode}"
        if getattr(self, "_results_splitter_mode", "") == mode:
            return
        self._results_splitter_mode = mode
        list_share = 0.40 if width_mode == "compact" else 0.36
        self.header_frame.setFixedHeight(52 if height_mode == "short" else 68)
        if hasattr(self, "result_subtitle"):
            self.result_subtitle.setVisible(height_mode != "short")
        for card in getattr(self, "summary_cards", ()):
            card.setFixedSize(72 if width_mode == "compact" else 78, 42 if height_mode == "short" else 46)
        if hasattr(self, "manual_group"):
            self.manual_group.setMaximumHeight(124 if height_mode == "short" else 142)
        list_width = max(390, int(available * list_share))
        preview_width = max(560, available - list_width)
        self.results_splitter.setSizes([list_width, preview_width])
        if hasattr(self, "output_preview"):
            minimum_preview_height = 260 if height_mode == "short" else 320
            self.output_preview.viewer.setMinimumHeight(minimum_preview_height)
            self.source_preview.viewer.setMinimumHeight(minimum_preview_height)

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        if (
            hasattr(self, "workflow_pages")
            and hasattr(self, "results_page")
            and self.workflow_pages.currentWidget() is self.results_page
        ):
            self._update_results_splitter_for_width()

    def _build_inputs_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setMinimumWidth(300)
        shell_layout = QVBoxLayout(panel)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        self.inputs_scroll = QScrollArea()
        self.inputs_scroll.setObjectName("inputsPageScroll")
        self.inputs_scroll.setWidgetResizable(True)
        self.inputs_scroll.setFrameShape(QFrame.NoFrame)
        self.inputs_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.inputs_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.inputs_scroll.setToolTip("حرّك عجلة الفأرة أو شريط التمرير للوصول إلى جميع الخيارات")

        content = QWidget()
        content.setObjectName("inputsScrollContent")
        content.setMinimumWidth(280)
        layout = QVBoxLayout(content)
        layout.setSizeConstraint(QLayout.SetMinimumSize)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        catalog_group = QGroupBox("1. ملف المنتجات")
        catalog_layout = QVBoxLayout(catalog_group)
        self.catalog_edit = QLineEdit()
        self.catalog_edit.setObjectName("catalogPath")
        self.catalog_edit.setReadOnly(True)
        self.catalog_edit.setLayoutDirection(Qt.LeftToRight)
        self.catalog_edit.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.catalog_edit.setMinimumHeight(38)
        self.catalog_edit.setPlaceholderText("لم يتم اختيار ملف Excel")
        self.catalog_status_label = QLabel("سيظهر اسم الملف هنا بعد اختياره")
        self.catalog_status_label.setObjectName("catalogStatus")
        catalog_button = QPushButton("اختيار ملف Excel")
        catalog_button.setObjectName("secondaryButton")
        catalog_button.clicked.connect(self._select_catalog)
        catalog_layout.addWidget(self.catalog_edit)
        catalog_layout.addWidget(self.catalog_status_label)
        catalog_layout.addWidget(catalog_button)
        layout.addWidget(catalog_group)

        images_group = QGroupBox("2. صور المنتجات")
        images_layout = QVBoxLayout(images_group)
        buttons = QHBoxLayout()
        add_images = QPushButton("إضافة صور")
        add_images.setObjectName("secondaryButton")
        add_images.clicked.connect(self._select_images)
        add_folder = QPushButton("إضافة مجلد")
        add_folder.setObjectName("secondaryButton")
        add_folder.clicked.connect(self._select_folder)
        buttons.addWidget(add_images)
        buttons.addWidget(add_folder)
        images_layout.addLayout(buttons)
        self.image_list = ImageListWidget()
        self.image_list.setObjectName("productImageList")
        self.image_list.setUniformItemSizes(True)
        self.image_list.setLayoutDirection(Qt.LeftToRight)
        self.image_list.setTextElideMode(Qt.ElideMiddle)
        self.image_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.image_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.image_list.setMinimumHeight(170)
        self.image_list.setMaximumHeight(250)
        self.image_list.files_dropped.connect(self._add_paths)
        images_layout.addWidget(self.image_list, 1)
        list_footer = QHBoxLayout()
        self.image_count_label = QLabel("0 صورة")
        remove_selected = QPushButton("حذف المحدد")
        remove_selected.setObjectName("textButton")
        remove_selected.clicked.connect(self._remove_selected_images)
        clear_all = QPushButton("مسح الكل")
        clear_all.setObjectName("textButton")
        clear_all.clicked.connect(self._clear_images)
        list_footer.addWidget(self.image_count_label, 1)
        list_footer.addWidget(remove_selected)
        list_footer.addWidget(clear_all)
        images_layout.addLayout(list_footer)
        layout.addWidget(images_group, 1)

        options_group = QGroupBox("3. تحسين المنتج والإخراج")
        options_group.setObjectName("enhancementGroup")
        options_layout = QVBoxLayout(options_group)
        options_layout.setSpacing(8)
        self.enhance_product_check = QCheckBox("تحسين صورة المنتج مع المحافظة على الكتابات")
        self.enhance_product_check.setObjectName("enhancementMaster")
        self.enhance_product_check.setChecked(True)
        self.enhance_product_check.setToolTip(
            "تحسين محافظ لا يولّد نصوصاً ولا يغيّر بيانات الملصق؛ يؤثر في نسخة الإخراج فقط"
        )
        self.enhance_product_check.toggled.connect(self._update_enhancement_controls)
        options_layout.addWidget(self.enhance_product_check)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("النمط الجاهز:"))
        self.enhancement_preset_combo = QComboBox()
        self.enhancement_preset_combo.setObjectName("enhancementPreset")
        self.enhancement_preset_combo.addItem("متوازن للمتجر — موصى به", "balanced")
        self.enhancement_preset_combo.addItem("محافظ للعبوات والنصوص", "label_safe")
        self.enhancement_preset_combo.addItem("قوي للصور الباهتة", "vivid")
        self.enhancement_preset_combo.addItem("مخصص", "custom")
        self.enhancement_preset_combo.currentIndexChanged.connect(self._apply_enhancement_preset)
        preset_row.addWidget(self.enhancement_preset_combo, 1)
        options_layout.addLayout(preset_row)

        strength_row = QHBoxLayout()
        strength_row.addWidget(QLabel("قوة التحسين:"))
        self.enhancement_strength_slider = QSlider(Qt.Horizontal)
        self.enhancement_strength_slider.setObjectName("enhancementStrength")
        self.enhancement_strength_slider.setRange(0, 100)
        self.enhancement_strength_slider.setSingleStep(5)
        self.enhancement_strength_slider.setPageStep(10)
        self.enhancement_strength_slider.setValue(55)
        self.enhancement_strength_slider.setToolTip("حرّك الشريط لاختيار مقدار التحسين؛ 55% قيمة متوازنة وآمنة")
        self.enhancement_strength_slider.valueChanged.connect(self._update_enhancement_strength_label)
        self.enhancement_strength_slider.sliderReleased.connect(self._mark_enhancement_custom)
        self.enhancement_strength_value = QLabel("55%")
        self.enhancement_strength_value.setObjectName("strengthValue")
        self.enhancement_strength_value.setMinimumWidth(42)
        self.enhancement_strength_value.setAlignment(Qt.AlignCenter)
        strength_row.addWidget(self.enhancement_strength_slider, 1)
        strength_row.addWidget(self.enhancement_strength_value)
        options_layout.addLayout(strength_row)

        enhancements_grid = QGridLayout()
        enhancements_grid.setHorizontalSpacing(10)
        enhancements_grid.setVerticalSpacing(5)
        self.enhance_lighting_check = QCheckBox("توازن الإضاءة")
        self.enhance_color_check = QCheckBox("تصحيح الألوان")
        self.enhance_details_check = QCheckBox("وضوح التفاصيل")
        self.reduce_noise_check = QCheckBox("تنقية التشويش")
        self.auto_straighten_check = QCheckBox("استقامة آمنة")
        self.enhance_lighting_check.setChecked(True)
        self.enhance_color_check.setChecked(True)
        self.enhance_details_check.setChecked(True)
        self.reduce_noise_check.setChecked(True)
        self.auto_straighten_check.setChecked(True)
        for option_check in (
            self.enhance_lighting_check,
            self.enhance_color_check,
            self.enhance_details_check,
            self.reduce_noise_check,
            self.auto_straighten_check,
        ):
            option_check.toggled.connect(self._mark_enhancement_custom)
        enhancements_grid.addWidget(self.enhance_lighting_check, 0, 0)
        enhancements_grid.addWidget(self.enhance_color_check, 0, 1)
        enhancements_grid.addWidget(self.enhance_details_check, 1, 0)
        enhancements_grid.addWidget(self.reduce_noise_check, 1, 1)
        enhancements_grid.addWidget(self.auto_straighten_check, 2, 0, 1, 2)
        options_layout.addLayout(enhancements_grid)

        framing_row = QHBoxLayout()
        framing_row.addWidget(QLabel("مساحة المنتج:"))
        self.framing_combo = QComboBox()
        self.framing_combo.setObjectName("framingPreset")
        self.framing_combo.addItem("متوازنة", (48, 40))
        self.framing_combo.addItem("أقرب وأكبر", (32, 28))
        self.framing_combo.addItem("هوامش أوسع", (70, 58))
        framing_row.addWidget(self.framing_combo, 1)
        framing_row.addWidget(QLabel("الجودة:"))
        self.webp_quality_combo = QComboBox()
        self.webp_quality_combo.setObjectName("webpQuality")
        self.webp_quality_combo.addItem("ممتازة 94", 94)
        self.webp_quality_combo.addItem("قصوى 97", 97)
        self.webp_quality_combo.addItem("اقتصادية 90", 90)
        framing_row.addWidget(self.webp_quality_combo, 1)
        options_layout.addLayout(framing_row)

        dimensions = QLabel("WebP ‏800×700 • خلفية بيضاء عند العزل • الاسم: رقم الصنف_حبه")
        dimensions.setWordWrap(True)
        dimensions.setObjectName("hintLabel")
        options_layout.addWidget(dimensions)
        layout.addWidget(options_group)
        self._update_enhancement_controls()

        ai_group = QGroupBox("4. الذكاء الاصطناعي المحلي")
        ai_group.setObjectName("aiGroup")
        ai_layout = QVBoxLayout(ai_group)
        ai_badge = QLabel("AI محلي  •  U2NetP  •  يعمل دون إنترنت")
        ai_badge.setObjectName("aiBadge")
        ai_badge.setAlignment(Qt.AlignCenter)
        self.ai_local_check = QCheckBox("تفعيل الذكاء الاصطناعي لعزل المنتج")
        self.ai_local_check.setObjectName("aiToggle")
        self.ai_local_check.setChecked(True)
        self.ai_local_check.setToolTip(
            "يشغّل نموذج U2NetP داخل جهازك، ويعزل المنتج إلى خلفية بيضاء مع بوابة أمان تمنع قص المنتج"
        )
        self.remove_background_check = self.ai_local_check
        ai_description = QLabel(
            "عند تفعيله يحلل النموذج الصورة محليًا ويجعل الخلفية بيضاء. عند انخفاض الثقة يحتفظ بالصورة الأصلية تلقائيًا."
        )
        ai_description.setObjectName("aiDescription")
        ai_description.setWordWrap(True)
        ai_layout.addWidget(ai_badge)
        ai_layout.addWidget(self.ai_local_check)
        ai_layout.addWidget(ai_description)
        layout.addWidget(ai_group)

        layout.addStretch(1)
        self.inputs_scroll.setWidget(content)
        shell_layout.addWidget(self.inputs_scroll, 1)

        setup_footer = QFrame()
        setup_footer.setObjectName("fixedActionBar")
        setup_footer_layout = QHBoxLayout(setup_footer)
        setup_footer_layout.setContentsMargins(16, 12, 16, 12)
        setup_footer_layout.setSpacing(14)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("جاهز")
        self.progress.setMinimumHeight(18)
        self.run_button = QPushButton("بدء المطابقة الذكية وتجهيز الصور")
        self.run_button.setObjectName("primaryButton")
        self.run_button.setMinimumSize(310, 48)
        self.run_button.clicked.connect(self._start_batch)
        setup_footer_layout.addWidget(self.progress, 1)
        setup_footer_layout.addWidget(self.run_button)
        shell_layout.addWidget(setup_footer)
        return panel

    def _update_enhancement_controls(self, _checked: bool | None = None) -> None:
        enabled = self.enhance_product_check.isChecked() and self.enhance_product_check.isEnabled()
        for control in (
            self.enhancement_preset_combo,
            self.enhancement_strength_slider,
            self.enhance_lighting_check,
            self.enhance_color_check,
            self.enhance_details_check,
            self.reduce_noise_check,
            self.auto_straighten_check,
        ):
            control.setEnabled(enabled)

    def _update_enhancement_strength_label(self, value: int) -> None:
        self.enhancement_strength_value.setText(f"{int(value)}%")

    def _mark_enhancement_custom(self, *_args) -> None:
        if getattr(self, "_applying_enhancement_preset", False):
            return
        custom_index = self.enhancement_preset_combo.findData("custom")
        if custom_index >= 0 and self.enhancement_preset_combo.currentIndex() != custom_index:
            self.enhancement_preset_combo.setCurrentIndex(custom_index)

    def _apply_enhancement_preset(self, _index: int) -> None:
        preset = self.enhancement_preset_combo.currentData()
        values = {
            "balanced": (55, True, True, True, True, True),
            "label_safe": (35, True, False, True, True, False),
            "vivid": (78, True, True, True, True, True),
        }.get(preset)
        if values is None:
            return
        self._applying_enhancement_preset = True
        try:
            strength, lighting, color, details, denoise, straighten = values
            self.enhancement_strength_slider.setValue(strength)
            self.enhance_lighting_check.setChecked(lighting)
            self.enhance_color_check.setChecked(color)
            self.enhance_details_check.setChecked(details)
            self.reduce_noise_check.setChecked(denoise)
            self.auto_straighten_check.setChecked(straighten)
        finally:
            self._applying_enhancement_preset = False

    def _final_image_options(self) -> FinalImageOptions:
        margin_x, margin_y = self.framing_combo.currentData()
        remove_background = self.remove_background_check.isChecked()
        return FinalImageOptions(
            width=800,
            height=700,
            margin_x=int(margin_x),
            margin_y=int(margin_y),
            remove_background=remove_background,
            crop_to_foreground=remove_background,
            enhance_for_display=self.enhance_product_check.isChecked(),
            enhancement_strength=self.enhancement_strength_slider.value(),
            enhance_lighting=self.enhance_lighting_check.isChecked(),
            enhance_color=self.enhance_color_check.isChecked(),
            enhance_details=self.enhance_details_check.isChecked(),
            reduce_noise=self.reduce_noise_check.isChecked(),
            auto_straighten=self.auto_straighten_check.isChecked(),
            foreground_method="auto" if remove_background else "none",
            webp_quality=int(self.webp_quality_combo.currentData()),
        )

    @staticmethod
    def _add_depth_effect(
        widget: QWidget,
        *,
        color: str = "#10233d",
        blur: float = 24.0,
        y_offset: float = 5.0,
        alpha: int = 52,
    ) -> None:
        """Apply a restrained card shadow that remains fast on Windows/Qt."""
        effect = QGraphicsDropShadowEffect(widget)
        effect.setBlurRadius(float(blur))
        effect.setOffset(0.0, float(y_offset))
        shadow = QColor(color)
        shadow.setAlpha(max(0, min(255, int(alpha))))
        effect.setColor(shadow)
        widget.setGraphicsEffect(effect)

    def _build_results_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("reviewPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        review_top_bar = QFrame()
        review_top_bar.setObjectName("reviewTopBar")
        review_top_bar.setMinimumHeight(58)
        top_layout = QHBoxLayout(review_top_bar)
        top_layout.setContentsMargins(14, 7, 14, 7)
        top_layout.setSpacing(10)

        title_stack = QVBoxLayout()
        title_stack.setSpacing(0)
        result_title = QLabel("استوديو المراجعة والربط")
        result_title.setObjectName("pageTitle")
        self.result_subtitle = QLabel("الصورة وبيانات الصنف وأدوات الربط أمامك في شاشة واحدة")
        self.result_subtitle.setObjectName("pageSubtitle")
        title_stack.addWidget(result_title)
        title_stack.addWidget(self.result_subtitle)
        top_layout.addLayout(title_stack, 1)

        compact_cards = QHBoxLayout()
        compact_cards.setSpacing(6)
        self.total_card = StatCard("إجمالي", "#334155")
        self.matched_card = StatCard("مطابق", "#059669")
        self.review_card = StatCard("مراجعة", "#d97706")
        self.error_card = StatCard("أخطاء", "#dc2626")
        self.summary_cards = (
            self.total_card,
            self.matched_card,
            self.review_card,
            self.error_card,
        )
        for card in self.summary_cards:
            card.setFixedSize(78, 46)
            compact_cards.addWidget(card)
        top_layout.addLayout(compact_cards)

        self.back_to_setup_button = QPushButton("العودة للإعداد")
        self.back_to_setup_button.setObjectName("backToSetupButton")
        self.back_to_setup_button.setMinimumHeight(36)
        self.back_to_setup_button.clicked.connect(self._show_setup_page)
        top_layout.addWidget(self.back_to_setup_button)
        layout.addWidget(review_top_bar)
        self._add_depth_effect(review_top_bar, color="#243b64", blur=20, y_offset=4, alpha=42)

        self.results_table = QTableWidget(0, 3)
        self.results_table.setObjectName("resultsTable")
        self.results_table.setHorizontalHeaderLabels(["الصورة / الحالة", "الصنف / الباركود", "اسم الصنف"])
        self.results_table.setIconSize(QSize(54, 54))
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setWordWrap(True)
        self.results_table.setTextElideMode(Qt.ElideNone)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.verticalHeader().setMinimumSectionSize(68)
        self.results_table.verticalHeader().setDefaultSectionSize(76)
        self.results_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.results_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.results_table.verticalScrollBar().setSingleStep(28)
        self.results_table.setToolTip(
            "حدد صفًا واحدًا للمعاينة أو عدة صفوف لربط صور الصنف نفسه؛ الاسم والباركود ظاهرَان دون أعمدة مزدحمة"
        )
        table_header = self.results_table.horizontalHeader()
        table_header.setMinimumSectionSize(82)
        table_header.setSectionResizeMode(0, QHeaderView.Fixed)
        table_header.setSectionResizeMode(1, QHeaderView.Fixed)
        table_header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.results_table.setColumnWidth(0, 136)
        self.results_table.setColumnWidth(1, 148)
        self.results_table.itemSelectionChanged.connect(self._show_selected_preview)
        self.results_table.doubleClicked.connect(self._open_selected_file)
        self.results_table.setMinimumHeight(250)

        self.result_search_edit = QLineEdit()
        self.result_search_edit.setObjectName("resultSearchEdit")
        self.result_search_edit.setPlaceholderText("ابحث بالاسم أو الصنف أو الباركود أو الصورة")
        self.result_search_edit.setClearButtonEnabled(True)
        self.result_search_edit.setToolTip("بحث فوري محلي يدعم الأرقام العربية والإنجليزية")
        self.result_search_edit.setMinimumHeight(36)
        self.result_search_edit.textChanged.connect(self._apply_result_filters)

        self.result_status_filter = QComboBox()
        self.result_status_filter.setObjectName("resultStatusFilter")
        self.result_status_filter.setMinimumHeight(36)
        self.result_status_filter.setToolTip("تصفية النتائج حسب الحالة")
        self.result_status_filter.addItem("كل الحالات", "all")
        self.result_status_filter.addItem("مطابق آليًا", "matched")
        self.result_status_filter.addItem("مرتبط يدويًا", "manual")
        self.result_status_filter.addItem("يحتاج إجراء", "action")
        self.result_status_filter.addItem("للمراجعة فقط", "review")
        self.result_status_filter.addItem("أخطاء فقط", "error")
        self.result_status_filter.currentIndexChanged.connect(self._apply_result_filters)

        self.clear_result_filter_button = QPushButton("مسح")
        self.clear_result_filter_button.setObjectName("tableNavButton")
        self.clear_result_filter_button.setMinimumHeight(36)
        self.clear_result_filter_button.setToolTip("إظهار كل النتائج")
        self.clear_result_filter_button.setEnabled(False)
        self.clear_result_filter_button.clicked.connect(self._clear_result_filters)

        result_filter_layout = QHBoxLayout()
        result_filter_layout.setSpacing(6)
        result_filter_layout.addWidget(self.result_search_edit, 1)
        result_filter_layout.addWidget(self.result_status_filter)
        result_filter_layout.addWidget(self.clear_result_filter_button)

        table_navigation = QHBoxLayout()
        table_navigation.setSpacing(6)
        self.table_position_label = QLabel("عدد الأصناف: 0")
        self.table_position_label.setObjectName("tablePosition")
        self.table_position_label.setToolTip("موضع الصنف المحدد داخل النتائج المصفاة")
        self.first_item_button = QPushButton("الأول")
        self.first_item_button.setObjectName("tableNavButton")
        self.first_item_button.setToolTip("الانتقال إلى أول صنف")
        self.first_item_button.clicked.connect(self._select_first_result)
        self.last_item_button = QPushButton("الأخير")
        self.last_item_button.setObjectName("tableNavButton")
        self.last_item_button.setToolTip("الانتقال إلى آخر صنف")
        self.last_item_button.clicked.connect(self._select_last_result)
        self.first_item_button.setEnabled(False)
        self.last_item_button.setEnabled(False)
        table_navigation.addWidget(self.table_position_label)
        table_navigation.addStretch(1)
        table_navigation.addWidget(self.first_item_button)
        table_navigation.addWidget(self.last_item_button)

        # شريط الربط ظاهر دائمًا ومضغوط؛ لا يوجد زر إظهار أو تمرير للوصول إليه.
        self.manual_group = QFrame()
        self.manual_group.setObjectName("alwaysVisibleLinkBar")
        self.manual_group.setMinimumHeight(110)
        self.manual_group.setMaximumHeight(124)
        manual_layout = QVBoxLayout(self.manual_group)
        manual_layout.setContentsMargins(8, 6, 8, 6)
        manual_layout.setSpacing(4)

        link_heading = QHBoxLayout()
        link_heading.setSpacing(6)
        link_title = QLabel("الربط المباشر")
        link_title.setObjectName("linkBarTitle")
        self.manual_context_label = QLabel("اختر صورة؛ يظهر رقم الصنف والباركود هنا.")
        self.manual_context_label.setObjectName("manualContext")
        self.manual_context_label.setWordWrap(False)
        self.manual_context_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.selected_count_badge = QLabel("المحدد: 0")
        self.selected_count_badge.setObjectName("selectedCountBadge")
        self.selected_count_badge.setAlignment(Qt.AlignCenter)
        link_heading.addWidget(link_title)
        link_heading.addWidget(self.manual_context_label, 1)
        link_heading.addWidget(self.selected_count_badge)
        manual_layout.addLayout(link_heading)

        manual_controls = QHBoxLayout()
        manual_controls.setSpacing(6)
        self.manual_item_edit = QLineEdit()
        self.manual_item_edit.setObjectName("manualItemEdit")
        self.manual_item_edit.setLayoutDirection(Qt.LeftToRight)
        self.manual_item_edit.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.manual_item_edit.setPlaceholderText("اسم، رقم صنف أو باركود")
        self.manual_item_edit.setToolTip(
            "يبحث أولًا عن رقم الصنف والباركود، ويمكن إدخال الاسم لتحديد الصنف الصحيح"
        )
        self.manual_item_edit.returnPressed.connect(self._start_manual_link)
        self.manual_item_edit.setMinimumHeight(36)
        self.manual_link_button = QPushButton("ربط الآن")
        self.manual_link_button.setObjectName("manualLinkPrimaryButton")
        self.manual_link_button.setMinimumHeight(36)
        self.manual_link_button.clicked.connect(self._start_manual_link)
        manual_controls.addWidget(self.manual_item_edit, 1)
        manual_controls.addWidget(self.manual_link_button)
        manual_layout.addLayout(manual_controls)

        quick_controls = QHBoxLayout()
        quick_controls.setSpacing(6)
        self.use_reference_button = QPushButton("اعتماد مرجع")
        self.use_reference_button.setObjectName("linkToolButton")
        self.use_reference_button.setToolTip(
            "يعتمد صفًا موثوقًا مرجعًا لربط الصور القريبة للصنف نفسه"
        )
        self.use_reference_button.clicked.connect(self._use_selected_reference)
        self.suggest_group_button = QPushButton("اقتراح قريب")
        self.suggest_group_button.setObjectName("suggestNearbyButton")
        self.suggest_group_button.setToolTip(
            "يحدد الصور غير المرتبطة المتجاورة والمتشابهة للمراجعة فقط"
        )
        self.suggest_group_button.clicked.connect(self._suggest_high_confidence_group)
        self.reference_group_link_button = QPushButton("ربط بالمرجع")
        self.reference_group_link_button.setObjectName("referenceLinkButton")
        self.reference_group_link_button.setToolTip(
            "يربط الصفوف غير المؤكدة المحددة بصنف المرجع مع إبقاء كل صورة مستقلة"
        )
        self.reference_group_link_button.clicked.connect(self._start_reference_group_link)
        self.manual_reference_badge = QLabel("لا يوجد مرجع")
        self.manual_reference_badge.setObjectName("manualReferenceBadge")
        self.manual_reference_badge.setAlignment(Qt.AlignCenter)
        self.jump_to_previews_button = QPushButton("عرض الصورة")
        self.jump_to_previews_button.setObjectName("linkToolButton")
        self.jump_to_previews_button.setToolTip("ينقل التركيز مباشرة إلى الصورة الحالية")
        self.jump_to_previews_button.clicked.connect(self._scroll_to_previews)
        for button in (
            self.use_reference_button,
            self.suggest_group_button,
            self.reference_group_link_button,
            self.jump_to_previews_button,
        ):
            button.setMinimumHeight(30)
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.manual_reference_badge.setMinimumWidth(76)
        self.manual_reference_badge.setMaximumWidth(112)
        quick_controls.addWidget(self.use_reference_button)
        quick_controls.addWidget(self.suggest_group_button)
        quick_controls.addWidget(self.reference_group_link_button)
        quick_controls.addWidget(self.jump_to_previews_button)
        quick_controls.addWidget(self.manual_reference_badge, 1)
        manual_layout.addLayout(quick_controls)

        # تُحفظ هذه الخاصية للتوافق مع ملحقات قديمة، لكن الأدوات لا يمكن طيها في 1.2.
        self.manual_toggle_button = QPushButton()
        self.manual_toggle_button.setCheckable(True)
        self.manual_toggle_button.setChecked(True)
        self.manual_toggle_button.setVisible(False)
        self.manual_selection_label = QLabel("لا يوجد مرجع — يمكن ربط الصف المحدد مباشرة.")
        self.manual_selection_label.setObjectName("manualSelection")
        self.manual_selection_label.setVisible(False)

        self.results_upper_widget = QFrame()
        self.results_upper_widget.setObjectName("resultsListPane")
        self.results_upper_widget.setMinimumWidth(410)
        list_layout = QVBoxLayout(self.results_upper_widget)
        list_layout.setContentsMargins(10, 10, 10, 10)
        list_layout.setSpacing(7)
        list_header = QHBoxLayout()
        list_title = QLabel("قائمة الصور والصنف")
        list_title.setObjectName("sectionTitle")
        list_header.addWidget(list_title)
        list_header.addStretch(1)
        list_header.addLayout(table_navigation)
        list_layout.addLayout(list_header)
        list_layout.addLayout(result_filter_layout)
        list_layout.addWidget(self.results_table, 1)
        list_layout.addWidget(self.manual_group)
        self.results_upper_content = self.results_upper_widget
        self._add_depth_effect(self.results_upper_widget, color="#293b5f", blur=24, y_offset=5, alpha=44)
        self._add_depth_effect(self.manual_group, color="#3730a3", blur=18, y_offset=4, alpha=48)

        self.previews_widget = QFrame()
        self.previews_widget.setObjectName("reviewStudio")
        self.previews_widget.setMinimumWidth(560)
        preview_layout = QVBoxLayout(self.previews_widget)
        preview_layout.setContentsMargins(10, 10, 10, 10)
        preview_layout.setSpacing(8)

        self.selected_product_card = QFrame()
        self.selected_product_card.setObjectName("selectedProductCard")
        self.selected_product_card.setMinimumHeight(88)
        self.selected_product_card.setMaximumHeight(116)
        product_card_layout = QVBoxLayout(self.selected_product_card)
        product_card_layout.setContentsMargins(12, 8, 12, 8)
        product_card_layout.setSpacing(5)
        product_heading = QHBoxLayout()
        product_heading.setSpacing(8)
        self.selected_product_label = QLabel("اختر صورة من القائمة لعرض اسم الصنف كاملًا")
        self.selected_product_label.setObjectName("selectedProductName")
        self.selected_product_label.setWordWrap(True)
        self.selected_product_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.selected_status_badge = QLabel("بانتظار الاختيار")
        self.selected_status_badge.setObjectName("selectedStatusBadge")
        self.selected_status_badge.setAlignment(Qt.AlignCenter)
        self.edit_image_button = QPushButton("تحرير احترافي")
        self.edit_image_button.setObjectName("editImageButton")
        self.edit_image_button.setMinimumHeight(34)
        self.edit_image_button.setEnabled(False)
        self.edit_image_button.clicked.connect(self._open_individual_editor)
        self.open_selected_file_button = QPushButton("فتح الصورة")
        self.open_selected_file_button.setObjectName("openImageButton")
        self.open_selected_file_button.setMinimumHeight(34)
        self.open_selected_file_button.clicked.connect(self._open_selected_file)
        self.open_link_panel_button = QPushButton("تغيير الصنف")
        self.open_link_panel_button.setObjectName("focusLinkButton")
        self.open_link_panel_button.setMinimumHeight(34)
        self.open_link_panel_button.clicked.connect(
            lambda: self.manual_item_edit.setFocus(Qt.OtherFocusReason)
        )
        product_heading.addWidget(self.selected_product_label, 1)
        product_heading.addWidget(self.selected_status_badge)
        product_heading.addWidget(self.edit_image_button)
        product_heading.addWidget(self.open_selected_file_button)
        product_heading.addWidget(self.open_link_panel_button)
        product_card_layout.addLayout(product_heading)

        def build_meta_tile(caption: str, object_name: str, *, ltr: bool = False) -> tuple[QFrame, QLabel]:
            tile = QFrame()
            tile.setObjectName("productMetaTile")
            tile_layout = QHBoxLayout(tile)
            tile_layout.setContentsMargins(8, 4, 8, 4)
            tile_layout.setSpacing(6)
            caption_label = QLabel(caption)
            caption_label.setObjectName("metaCaption")
            value_label = QLabel("—")
            value_label.setObjectName(object_name)
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            if ltr:
                value_label.setLayoutDirection(Qt.LeftToRight)
                value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            else:
                value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            tile_layout.addWidget(caption_label)
            tile_layout.addWidget(value_label, 1)
            return tile, value_label

        meta_row = QHBoxLayout()
        meta_row.setSpacing(6)
        item_tile, self.selected_item_code_label = build_meta_tile("رقم الصنف", "selectedItemCode", ltr=True)
        barcode_tile, self.selected_barcode_label = build_meta_tile("الباركود", "selectedBarcode", ltr=True)
        file_tile, self.selected_file_label = build_meta_tile("الملف", "selectedFileName")
        meta_row.addWidget(item_tile, 2)
        meta_row.addWidget(barcode_tile, 3)
        meta_row.addWidget(file_tile, 4)
        product_card_layout.addLayout(meta_row)
        preview_layout.addWidget(self.selected_product_card)
        self._add_depth_effect(self.selected_product_card, color="#334155", blur=18, y_offset=4, alpha=42)

        self.preview_tabs = QTabWidget()
        self.preview_tabs.setObjectName("studioPreviewTabs")
        self.preview_tabs.setDocumentMode(True)
        self.output_preview = self._preview_box("الصورة الناتجة — افحص التفاصيل قبل الاعتماد")
        self.source_preview = self._preview_box("الصورة الأصلية — مناسبة لفحص الباركود")
        for pane in (self.output_preview, self.source_preview):
            pane.setObjectName("studioPreviewFrame")
            pane.viewer.setMinimumHeight(300)
        self.preview_tabs.addTab(self.output_preview, "النتيجة")
        self.preview_tabs.addTab(self.source_preview, "الأصل")
        self.preview_tabs.setCurrentWidget(self.output_preview)
        preview_layout.addWidget(self.preview_tabs, 1)
        self._add_depth_effect(self.previews_widget, color="#111827", blur=26, y_offset=6, alpha=52)

        # تُبنى أدوات التحرير مرة واحدة وتستضيفها نافذة المحرر المستقلة.
        self.individual_editor_panel = self._build_individual_editor_panel()
        self.individual_editor_panel.setVisible(False)

        self.results_splitter = QSplitter(Qt.Horizontal)
        self.results_splitter.setObjectName("resultsHorizontalSplitter")
        self.results_splitter.setChildrenCollapsible(False)
        self.results_splitter.setHandleWidth(9)
        self.results_splitter.addWidget(self.results_upper_widget)
        self.results_splitter.addWidget(self.previews_widget)
        self.results_splitter.setStretchFactor(0, 4)
        self.results_splitter.setStretchFactor(1, 7)
        self.results_splitter.setSizes([460, 780])
        self.results_splitter.setToolTip("اسحب الفاصل أفقيًا لتكبير القائمة أو الصورة؛ تُحفظ أدوات الربط ظاهرة في الحالتين")
        layout.addWidget(self.results_splitter, 1)

        result_actions = QFrame()
        result_actions.setObjectName("fixedActionBar")
        result_actions.setMaximumHeight(48)
        actions = QHBoxLayout(result_actions)
        actions.setContentsMargins(10, 5, 10, 5)
        actions.setSpacing(8)
        self.open_folder_button = QPushButton("فتح مجلد النتائج")
        self.open_folder_button.setObjectName("secondaryButton")
        self.open_folder_button.clicked.connect(self._open_results_folder)
        delivery_hint = QLabel("راجِع الصور التي تحتاج قرارًا، ثم احفظ الحزمة النهائية")
        delivery_hint.setObjectName("deliveryHint")
        self.save_zip_button = QPushButton("حفظ حزمة النتائج ZIP")
        self.save_zip_button.setObjectName("saveDeliveryButton")
        self.save_zip_button.setMinimumHeight(36)
        self.save_zip_button.clicked.connect(self._save_delivery_zip)
        actions.addWidget(self.open_folder_button)
        actions.addWidget(delivery_hint, 1)
        actions.addWidget(self.save_zip_button)
        layout.addWidget(result_actions)
        return panel

    def _set_manual_panel_expanded(self, expanded: bool) -> None:
        """Compatibility hook: linking tools are permanently visible from version 1.2 onward."""
        self.manual_group.setVisible(True)
        self.manual_toggle_button.blockSignals(True)
        self.manual_toggle_button.setChecked(True)
        self.manual_toggle_button.blockSignals(False)
        if expanded:
            self.manual_item_edit.setFocus(Qt.OtherFocusReason)

    def _preview_box(self, title: str) -> ImagePreviewPane:
        return ImagePreviewPane(title)

    def _build_individual_editor_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("individualEditor")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(7)

        title = QLabel("أدوات التعديل المباشر")
        title.setObjectName("individualEditorTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        subtitle = QLabel("اختر تبويبًا واحدًا؛ تبقى الصورة كبيرة ولا تتزاحم الأدوات.")
        subtitle.setObjectName("editorToolSubtitle")
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)

        enhance_card = QFrame()
        enhance_card.setObjectName("editorEnhanceCard")
        enhance_layout = QVBoxLayout(enhance_card)
        enhance_layout.setContentsMargins(9, 8, 9, 8)
        enhance_layout.setSpacing(7)
        enhance_title = QLabel("1  التحسين والإضاءة")
        enhance_title.setObjectName("editorToolSectionTitle")
        enhance_layout.addWidget(enhance_title)
        self.individual_smart_button = QPushButton("تحسين ذكي محافظ")
        self.individual_smart_button.setObjectName("individualSmartButton")
        self.individual_smart_button.setCheckable(True)
        self.individual_smart_button.setChecked(True)
        self.individual_smart_button.setMinimumHeight(36)
        self.individual_smart_button.setToolTip(
            "يحسن الإضاءة والألوان والتفاصيل محليًا مع حماية الشعار والكتابات والباركود"
        )
        self.individual_strength_combo = QComboBox()
        self.individual_strength_combo.setObjectName("individualStrength")
        self.individual_strength_combo.addItem("متوازن — موصى به", 55)
        self.individual_strength_combo.addItem("قوي للصورة الباهتة", 78)
        self.individual_strength_combo.addItem("محافظ للملصقات", 35)
        self.individual_strength_combo.setMinimumHeight(34)
        self.individual_strength_combo.setToolTip("قوة تحسين الصورة المحددة فقط")
        enhance_layout.addWidget(self.individual_smart_button)
        enhance_layout.addWidget(self.individual_strength_combo)
        self._add_depth_effect(enhance_card, color="#1d4ed8", blur=14, y_offset=3, alpha=36)

        crop_card = QFrame()
        crop_card.setObjectName("editorCropCard")
        crop_layout = QVBoxLayout(crop_card)
        crop_layout.setContentsMargins(9, 8, 9, 8)
        crop_layout.setSpacing(7)
        crop_title = QLabel("2  الاقتصاص الدقيق")
        crop_title.setObjectName("editorToolSectionTitle")
        crop_layout.addWidget(crop_title)

        crop_mode_row = QHBoxLayout()
        crop_mode_row.setSpacing(6)
        self.individual_auto_crop_button = QPushButton("ذكي تلقائي")
        self.individual_auto_crop_button.setObjectName("individualAutoCropButton")
        self.individual_auto_crop_button.setCheckable(True)
        self.individual_auto_crop_button.setChecked(True)
        self.individual_auto_crop_button.setMinimumHeight(36)
        self.individual_auto_crop_button.setToolTip(
            "يكتشف حدود المنتج ويوازن المسافات البيضاء تلقائيًا داخل 800×700"
        )
        self.individual_manual_crop_button = QPushButton("يدوي حر")
        self.individual_manual_crop_button.setObjectName("individualManualCropButton")
        self.individual_manual_crop_button.setCheckable(True)
        self.individual_manual_crop_button.setMinimumHeight(36)
        self.individual_manual_crop_button.setToolTip(
            "اقتصاص منظور: اسحب إطارًا أوليًا ثم حرّك الزوايا الأربع مستقلة حتى تتبع ميل العبوة"
        )
        crop_mode_row.addWidget(self.individual_auto_crop_button, 1)
        crop_mode_row.addWidget(self.individual_manual_crop_button, 1)
        crop_layout.addLayout(crop_mode_row)

        ratio_label = QLabel("نسبة إطار القص")
        ratio_label.setObjectName("editorToolLabel")
        crop_layout.addWidget(ratio_label)
        self.individual_crop_ratio_combo = QComboBox()
        self.individual_crop_ratio_combo.setObjectName("individualCropRatio")
        self.individual_crop_ratio_combo.setMinimumHeight(34)
        self.individual_crop_ratio_combo.addItem("طبيعي — حسب حدود المنظور", None)
        self.individual_crop_ratio_combo.addItem("نسبة الإخراج 800 × 700", 800.0 / 700.0)
        self.individual_crop_ratio_combo.addItem("مربع 1 : 1", 1.0)
        self.individual_crop_ratio_combo.addItem("عمودي 3 : 4", 3.0 / 4.0)
        self.individual_crop_ratio_combo.addItem("أفقي 4 : 3", 4.0 / 3.0)
        self.individual_crop_ratio_combo.setToolTip(
            "الوضع الحر هو الافتراضي ولا يفرض مربعًا. اختر نسبة ثابتة فقط عند الحاجة."
        )
        crop_layout.addWidget(self.individual_crop_ratio_combo)

        crop_action_row = QHBoxLayout()
        crop_action_row.setSpacing(6)
        self.individual_crop_full_button = QPushButton("كامل الصورة")
        self.individual_crop_full_button.setObjectName("cropUtilityButton")
        self.individual_crop_full_button.setMinimumHeight(32)
        self.individual_crop_full_button.setToolTip("يضع إطار القص على أكبر مساحة ممكنة داخل الصورة")
        self.individual_crop_clear_button = QPushButton("مسح الإطار")
        self.individual_crop_clear_button.setObjectName("cropUtilityButton")
        self.individual_crop_clear_button.setMinimumHeight(32)
        self.individual_crop_clear_button.setToolTip("يمسح إطار القص لتستطيع رسم إطار جديد")
        crop_action_row.addWidget(self.individual_crop_full_button, 1)
        crop_action_row.addWidget(self.individual_crop_clear_button, 1)
        crop_layout.addLayout(crop_action_row)

        self.individual_crop_info_label = QLabel("القص التلقائي نشط")
        self.individual_crop_info_label.setObjectName("cropInfoLabel")
        self.individual_crop_info_label.setWordWrap(True)
        self.individual_crop_info_label.setAlignment(Qt.AlignCenter)
        crop_layout.addWidget(self.individual_crop_info_label)

        self.individual_straighten_check = QCheckBox("تصحيح الميل البسيط بأمان")
        self.individual_straighten_check.setObjectName("individualStraighten")
        self.individual_straighten_check.setChecked(True)
        self.individual_straighten_check.setToolTip(
            "يصحح الميل البسيط تلقائيًا من دون تشويه العبوة أو النص"
        )
        crop_layout.addWidget(self.individual_straighten_check)
        self._add_depth_effect(crop_card, color="#0891b2", blur=14, y_offset=3, alpha=36)

        compare_card = QFrame()
        compare_card.setObjectName("editorCompareCard")
        compare_layout = QVBoxLayout(compare_card)
        compare_layout.setContentsMargins(9, 8, 9, 8)
        compare_layout.setSpacing(7)
        compare_title = QLabel("3  المقارنة قبل الحفظ")
        compare_title.setObjectName("editorToolSectionTitle")
        compare_layout.addWidget(compare_title)
        compare_buttons = QHBoxLayout()
        compare_buttons.setSpacing(6)
        self.individual_show_source_button = QPushButton("عرض الأصل")
        self.individual_show_source_button.setObjectName("showSourceButton")
        self.individual_show_source_button.setMinimumHeight(34)
        self.individual_show_preview_button = QPushButton("عرض النتيجة")
        self.individual_show_preview_button.setObjectName("showPreviewButton")
        self.individual_show_preview_button.setMinimumHeight(34)
        self.individual_show_preview_button.setEnabled(False)
        compare_buttons.addWidget(self.individual_show_source_button, 1)
        compare_buttons.addWidget(self.individual_show_preview_button, 1)
        compare_layout.addLayout(compare_buttons)
        self._add_depth_effect(compare_card, color="#7c3aed", blur=14, y_offset=3, alpha=36)

        self.individual_editor_tabs = QTabWidget()
        self.individual_editor_tabs.setObjectName("individualEditorTabs")
        self.individual_editor_tabs.setDocumentMode(True)
        self.individual_editor_tabs.setUsesScrollButtons(False)

        def add_tool_tab(card: QFrame, label: str, object_name: str) -> None:
            scroll = QScrollArea()
            scroll.setObjectName("editorToolsScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            host = QWidget()
            host.setObjectName(object_name)
            host_layout = QVBoxLayout(host)
            host_layout.setContentsMargins(7, 8, 7, 8)
            host_layout.setSpacing(0)
            host_layout.addWidget(card)
            host_layout.addStretch(1)
            scroll.setWidget(host)
            self.individual_editor_tabs.addTab(scroll, label)

        add_tool_tab(crop_card, "الاقتصاص", "editorCropTab")
        add_tool_tab(enhance_card, "التحسين", "editorEnhanceTab")
        add_tool_tab(compare_card, "المقارنة", "editorCompareTab")
        self.individual_editor_tabs.setCurrentIndex(0)
        layout.addWidget(self.individual_editor_tabs, 1)

        self.individual_editor_hint = QLabel(
            "ابدأ بالقص الذكي، أو اختر «منظور يدوي» ثم ضع كل زاوية على ركن العبوة لتصحيح ميلها."
        )
        self.individual_editor_hint.setObjectName("individualEditorHint")
        self.individual_editor_hint.setWordWrap(True)
        self.individual_editor_hint.setAlignment(Qt.AlignCenter)
        self.individual_editor_hint.setMaximumHeight(58)
        layout.addWidget(self.individual_editor_hint)

        self.individual_reset_button = QPushButton("إعادة ضبط جميع الأدوات")
        self.individual_reset_button.setObjectName("secondaryButton")
        self.individual_reset_button.setMinimumHeight(34)
        self.individual_reset_button.setToolTip("يلغي حدود القص اليدوي ويعيد الخيارات الموصى بها")
        layout.addWidget(self.individual_reset_button)

        self.individual_smart_button.toggled.connect(self._update_individual_editor_hint)
        self.individual_smart_button.toggled.connect(self._invalidate_individual_preview)
        self.individual_strength_combo.currentIndexChanged.connect(self._update_individual_editor_hint)
        self.individual_strength_combo.currentIndexChanged.connect(self._invalidate_individual_preview)
        self.individual_auto_crop_button.clicked.connect(self._choose_individual_auto_crop)
        self.individual_manual_crop_button.toggled.connect(self._toggle_individual_manual_crop)
        self.individual_crop_ratio_combo.currentIndexChanged.connect(self._on_individual_crop_ratio_changed)
        self.individual_crop_full_button.clicked.connect(self._select_full_image_crop)
        self.individual_crop_clear_button.clicked.connect(self._clear_individual_crop)
        self.individual_straighten_check.toggled.connect(self._update_individual_editor_hint)
        self.individual_straighten_check.toggled.connect(self._invalidate_individual_preview)
        self.individual_show_source_button.clicked.connect(self._show_individual_source)
        self.individual_show_preview_button.clicked.connect(self._show_individual_preview)
        self.individual_reset_button.clicked.connect(self._reset_individual_editor)
        return panel

    def _build_individual_editor_dialog(self) -> QDialog:
        dialog = ProtectedEditDialog(self)
        dialog.setObjectName("individualEditorDialog")
        dialog.setWindowTitle(f"محرر صورة المنتج — {APP_NAME}")
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setModal(True)
        dialog.setMinimumSize(960, 620)
        dialog.resize(1280, 780)
        dialog.setSizeGripEnabled(True)

        shell = QVBoxLayout(dialog)
        shell.setContentsMargins(14, 12, 14, 12)
        shell.setSpacing(10)

        header = QFrame()
        header.setObjectName("editorHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 10, 16, 10)
        header_layout.setSpacing(12)
        heading = QVBoxLayout()
        heading.setSpacing(3)
        self.individual_editor_product_label = QLabel("لم يُحدد منتج")
        self.individual_editor_product_label.setObjectName("editorProductLabel")
        self.individual_editor_product_label.setWordWrap(True)
        self.individual_editor_meta_label = QLabel("رقم الصنف: —  •  الوحدة: —")
        self.individual_editor_meta_label.setObjectName("editorMetaLabel")
        self.individual_editor_meta_label.setWordWrap(True)
        heading.addWidget(self.individual_editor_product_label)
        heading.addWidget(self.individual_editor_meta_label)
        self.individual_editor_state_label = QLabel("جاهز للتحرير")
        self.individual_editor_state_label.setObjectName("editorStateBadge")
        self.individual_editor_state_label.setAlignment(Qt.AlignCenter)
        self.individual_tools_toggle_button = QPushButton("الأدوات ظاهرة")
        self.individual_tools_toggle_button.setObjectName("secondaryButton")
        self.individual_tools_toggle_button.setVisible(False)
        header_layout.addLayout(heading, 1)
        header_layout.addWidget(self.individual_editor_state_label)
        header_layout.addWidget(self.individual_tools_toggle_button)
        shell.addWidget(header)

        self.individual_editor_splitter = QSplitter(Qt.Horizontal)
        self.individual_editor_splitter.setObjectName("individualEditorSplitter")
        self.individual_editor_splitter.setLayoutDirection(Qt.LeftToRight)
        self.individual_editor_splitter.setChildrenCollapsible(False)
        self.individual_editor_splitter.setHandleWidth(8)
        self.individual_editor_preview = ImagePreviewPane(
            "مساحة الصورة — كبّر وافحص النص والباركود قبل الحفظ"
        )
        self.individual_editor_preview.setObjectName("editorPreviewFrame")
        self._add_depth_effect(self.individual_editor_preview, color="#020617", blur=24, y_offset=6, alpha=88)
        self.individual_editor_preview.setMinimumWidth(620)
        self.individual_editor_preview.viewer.setMinimumHeight(430)
        self.individual_editor_preview.viewer.crop_changed.connect(self._on_individual_crop_changed)
        self.individual_editor_panel.setVisible(True)
        self.individual_editor_panel.setMinimumWidth(330)
        self.individual_editor_panel.setMaximumWidth(400)
        self.individual_editor_splitter.addWidget(self.individual_editor_preview)
        self.individual_editor_splitter.addWidget(self.individual_editor_panel)
        self.individual_editor_splitter.setStretchFactor(0, 7)
        self.individual_editor_splitter.setStretchFactor(1, 0)
        self.individual_editor_splitter.setSizes([880, 370])
        shell.addWidget(self.individual_editor_splitter, 1)

        footer = QFrame()
        footer.setObjectName("editorFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(12, 8, 12, 8)
        footer_layout.setSpacing(10)
        self.individual_cancel_button = QPushButton("إلغاء وإغلاق")
        self.individual_cancel_button.setObjectName("secondaryButton")
        self.individual_cancel_button.clicked.connect(self._request_close_individual_editor)
        self.individual_preview_button = QPushButton("إنشاء معاينة")
        self.individual_preview_button.setObjectName("individualPreviewButton")
        self.individual_preview_button.setToolTip(
            "يعرض النتيجة المقترحة من دون تغيير الملف أو التقارير أو حزمة ZIP"
        )
        self.individual_preview_button.clicked.connect(self._start_individual_preview)
        self.individual_apply_button = QPushButton("حفظ واعتماد التعديل")
        self.individual_apply_button.setObjectName("individualApplyButton")
        self.individual_apply_button.setToolTip(
            "يحفظ هذا الصف وحده ويحدّث التقارير وحزمة ZIP من دون تغيير بقية الصور"
        )
        self.individual_apply_button.clicked.connect(self._start_individual_edit)
        footer_layout.addWidget(self.individual_cancel_button)
        footer_layout.addStretch(1)
        footer_layout.addWidget(self.individual_preview_button)
        footer_layout.addWidget(self.individual_apply_button)
        shell.addWidget(footer)

        dialog.close_requested.connect(self._request_close_individual_editor)
        dialog.finished.connect(self._on_individual_editor_closed)
        return dialog

    def _toggle_individual_tools_panel(self) -> None:
        visible = not self.individual_editor_panel.isVisible()
        self.individual_editor_panel.setVisible(visible)
        self.individual_tools_toggle_button.setText("إخفاء الأدوات" if visible else "إظهار الأدوات")
        if visible:
            self.individual_editor_splitter.setSizes(
                [max(580, self.individual_editor_dialog.width() - 430), 380]
            )

    def _individual_editor_image_pane(self) -> ImagePreviewPane:
        return self.individual_editor_preview

    def _invalidate_individual_preview(self, *_args) -> None:
        editor_open = bool(
            hasattr(self, "individual_editor_dialog")
            and self.individual_editor_dialog.isVisible()
            and self._individual_edit_source_name
        )
        if editor_open:
            self._individual_editor_dirty = True
        had_preview = self._individual_preview_active or self._individual_preview_path is not None
        self._individual_preview_active = False
        self._individual_preview_path = None
        self.individual_show_preview_button.setEnabled(False)
        if editor_open:
            message = (
                "تغيّرت الإعدادات — أنشئ معاينة جديدة"
                if had_preview
                else "تعديلات غير محفوظة — أنشئ معاينة ثم احفظ"
            )
            self.individual_editor_state_label.setText(message)
            self.individual_editor_state_label.setProperty("previewPending", True)
            self.individual_editor_state_label.style().unpolish(self.individual_editor_state_label)
            self.individual_editor_state_label.style().polish(self.individual_editor_state_label)

    def _update_individual_crop_info(self) -> None:
        if not self.individual_manual_crop_button.isChecked():
            self.individual_crop_info_label.setText("القص الذكي يحدد المنتج تلقائيًا ويوازن الفراغ حوله")
            self.individual_crop_full_button.setEnabled(False)
            self.individual_crop_clear_button.setEnabled(False)
            self.individual_crop_ratio_combo.setEnabled(False)
            return
        self.individual_crop_full_button.setEnabled(True)
        self.individual_crop_clear_button.setEnabled(self._individual_crop_box is not None)
        self.individual_crop_ratio_combo.setEnabled(True)
        if self._individual_crop_box is None:
            self.individual_crop_info_label.setText(
                "لا يوجد إطار — اسحب إطارًا أوليًا ثم ضع الزوايا الأربع على أركان المنتج"
            )
            return
        viewer = self._individual_editor_image_pane().viewer
        size = viewer.crop_pixel_size()
        kept = viewer.crop_area_ratio() * 100.0
        if size is None:
            self.individual_crop_info_label.setText(f"منظور رباعي جاهز — يحتفظ بنحو {kept:.0f}% من الصورة")
        else:
            width, height = size
            self.individual_crop_info_label.setText(
                f"الناتج المصحح: {width} × {height} بكسل  •  المساحة المحددة: {kept:.0f}%"
            )

    def _on_individual_crop_ratio_changed(self, *_args) -> None:
        ratio = self.individual_crop_ratio_combo.currentData()
        pane = self._individual_editor_image_pane()
        pane.viewer.set_crop_aspect_ratio(float(ratio) if ratio is not None else None)
        self._individual_crop_box = pane.viewer.crop_box
        self._invalidate_individual_preview()
        self._update_individual_crop_info()
        self._update_individual_editor_hint()

    def _select_full_image_crop(self) -> None:
        if not self.individual_manual_crop_button.isChecked():
            self.individual_manual_crop_button.setChecked(True)
        pane = self._individual_editor_image_pane()
        pane.viewer.select_full_image(emit=True)
        pane.viewer.set_crop_mode(True)
        pane.viewer.setFocus(Qt.OtherFocusReason)
        self.individual_editor_state_label.setText("إطار القص جاهز للتعديل")

    def _clear_individual_crop(self) -> None:
        pane = self._individual_editor_image_pane()
        pane.viewer.clear_crop(emit=True)
        pane.viewer.set_crop_mode(self.individual_manual_crop_button.isChecked())
        pane.viewer.setFocus(Qt.OtherFocusReason)
        self.individual_editor_state_label.setText("ارسم إطارًا أوليًا ثم اضبط زوايا المنظور الأربع")

    def _show_individual_source(self) -> None:
        item = self._individual_editable_item()
        source = self._result_path(item.source_path) if item is not None else None
        if source is None or not source.is_file():
            self.status_label.setText("تعذر العثور على الصورة الأصلية للمقارنة.")
            return
        pane = self._individual_editor_image_pane()
        pane.set_image(source)
        ratio = self.individual_crop_ratio_combo.currentData()
        pane.viewer.set_crop_aspect_ratio(float(ratio) if ratio is not None else None, emit=False)
        pane.viewer.set_crop_box(self._individual_crop_box)
        pane.viewer.set_crop_mode(self.individual_manual_crop_button.isChecked())
        pane.viewer.fit_image()
        self.individual_editor_state_label.setText(
            "عرض الأصل — توجد نتيجة غير محفوظة" if self._individual_preview_active else "عرض الصورة الأصلية"
        )
        self._update_individual_crop_info()

    def _show_individual_preview(self) -> None:
        preview_path = self._individual_preview_path
        if preview_path is None or not preview_path.is_file():
            self.individual_show_preview_button.setEnabled(False)
            self.status_label.setText("أنشئ معاينة أولاً لعرض النتيجة قبل الحفظ.")
            return
        pane = self._individual_editor_image_pane()
        pane.set_image(preview_path)
        pane.viewer.set_crop_mode(False)
        pane.viewer.fit_image()
        self.individual_editor_state_label.setText("عرض النتيجة — معاينة غير محفوظة")
        self.individual_editor_state_label.setProperty("previewPending", True)
        self.individual_editor_state_label.style().unpolish(self.individual_editor_state_label)
        self.individual_editor_state_label.style().polish(self.individual_editor_state_label)

    def _request_close_individual_editor(self) -> None:
        if self.individual_worker is not None and self.individual_worker.isRunning():
            QMessageBox.information(
                self.individual_editor_dialog,
                APP_NAME,
                "انتظر حتى تنتهي المعاينة أو عملية الحفظ الحالية؛ لن يُغلق المحرر أثناء المعالجة.",
            )
            return
        if self._individual_editor_dirty or self._individual_preview_active:
            box = QMessageBox(self.individual_editor_dialog)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle(APP_NAME)
            box.setText("توجد تعديلات على الصورة لم تُحفظ بعد")
            box.setInformativeText(
                "يمكنك حفظ التعديل الآن، أو تجاهله وإغلاق المحرر، أو العودة لمتابعة العمل."
            )
            save_button = box.addButton("حفظ واعتماد", QMessageBox.AcceptRole)
            discard_button = box.addButton("تجاهل وإغلاق", QMessageBox.DestructiveRole)
            continue_button = box.addButton("متابعة التعديل", QMessageBox.RejectRole)
            box.setDefaultButton(continue_button)
            box.exec()
            clicked = box.clickedButton()
            if clicked is save_button:
                self._start_individual_edit()
                return
            if clicked is not discard_button:
                return
        self._individual_editor_dirty = False
        self._individual_preview_active = False
        if isinstance(self.individual_editor_dialog, ProtectedEditDialog):
            self.individual_editor_dialog.discard_and_close()
        else:
            QDialog.reject(self.individual_editor_dialog)

    def _open_individual_editor(self) -> None:
        item = self._individual_editable_item()
        if item is None:
            QMessageBox.information(
                self,
                APP_NAME,
                "حدد صفًا مرتبطًا واحدًا فقط. اربط الصف برقم الصنف أولاً إذا كان للمراجعة.",
            )
            return
        source = self._result_path(item.source_path)
        if source is None or not source.is_file():
            QMessageBox.warning(self, APP_NAME, "تعذر العثور على الصورة الأصلية لهذا الصف.")
            return

        self._individual_edit_source_name = item.source_name
        self._individual_crop_box = None
        self._individual_preview_active = False
        self._individual_preview_path = None
        self._individual_editor_dirty = False
        self.individual_show_preview_button.setEnabled(False)
        self.individual_crop_ratio_combo.blockSignals(True)
        self.individual_crop_ratio_combo.setCurrentIndex(0)
        self.individual_crop_ratio_combo.blockSignals(False)
        self.individual_manual_crop_button.blockSignals(True)
        self.individual_manual_crop_button.setChecked(False)
        self.individual_manual_crop_button.blockSignals(False)
        self.individual_auto_crop_button.setChecked(True)
        self.individual_smart_button.setChecked(True)
        self.individual_strength_combo.setCurrentIndex(0)
        self.individual_straighten_check.setChecked(True)
        self.individual_crop_ratio_combo.blockSignals(True)
        self.individual_crop_ratio_combo.setCurrentIndex(0)
        self.individual_crop_ratio_combo.blockSignals(False)
        pane = self._individual_editor_image_pane()
        pane.set_image(source)
        pane.viewer.clear_crop()
        pane.viewer.set_crop_aspect_ratio(None, emit=False)
        pane.viewer.set_crop_mode(False)
        pane.viewer.fit_image()
        self.individual_editor_product_label.setText(item.product_name or item.source_name)
        unit = "حبة" if item.item_code else "غير محددة"
        self.individual_editor_meta_label.setText(
            f"رقم الصنف: {item.item_code or 'غير مرتبط'}  •  الوحدة: {unit}  •  الملف: {item.source_name}"
        )
        self.individual_editor_state_label.setText("جاهز للمعاينة")
        self.individual_editor_state_label.setProperty("previewPending", False)
        self.individual_editor_panel.setVisible(True)
        self.individual_tools_toggle_button.setText("الأدوات ظاهرة")
        self._update_individual_crop_info()
        self._update_individual_editor_hint()
        self._update_controls()

        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            if available.width() < 1440:
                self.individual_editor_dialog.showMaximized()
            else:
                width = max(1100, int(available.width() * 0.92))
                height = max(680, int(available.height() * 0.92))
                self.individual_editor_dialog.resize(width, height)
                self.individual_editor_dialog.move(
                    available.x() + (available.width() - width) // 2,
                    available.y() + (available.height() - height) // 2,
                )
                self.individual_editor_dialog.show()
        else:
            self.individual_editor_dialog.show()
        QTimer.singleShot(
            0,
            lambda: self.individual_editor_splitter.setSizes(
                [max(580, self.individual_editor_dialog.width() - 430), 380]
            ),
        )
        self.individual_editor_dialog.raise_()
        self.individual_editor_dialog.activateWindow()

    def _on_individual_editor_closed(self, _result: int) -> None:
        if self.individual_worker is not None and self.individual_worker.isRunning():
            return
        self._individual_editor_dirty = False
        self._individual_preview_active = False
        self._individual_preview_path = None
        self.individual_show_preview_button.setEnabled(False)
        self._individual_crop_box = None
        self.individual_manual_crop_button.blockSignals(True)
        self.individual_manual_crop_button.setChecked(False)
        self.individual_manual_crop_button.blockSignals(False)
        pane = self._individual_editor_image_pane()
        pane.viewer.clear_crop()
        pane.viewer.set_crop_mode(False)
        self._render_selected_preview()

    def _scroll_to_previews(self) -> None:
        self.preview_tabs.setCurrentWidget(self.output_preview)
        self.output_preview.viewer.setFocus(Qt.OtherFocusReason)

    def _individual_editable_item(self) -> BatchItemResult | None:
        selected = self._selected_result_items()
        if len(selected) != 1:
            return None
        item = selected[0]
        source = self._result_path(item.source_path)
        if not item.item_code or source is None or not source.is_file():
            return None
        return item

    def _choose_individual_auto_crop(self, _checked: bool = True) -> None:
        self.individual_auto_crop_button.setChecked(True)
        if self.individual_manual_crop_button.isChecked():
            self.individual_manual_crop_button.setChecked(False)
        self._individual_crop_box = None
        pane = self._individual_editor_image_pane()
        pane.viewer.clear_crop()
        pane.viewer.set_crop_aspect_ratio(None, emit=False)
        pane.viewer.set_crop_mode(False)
        item = self._individual_editable_item()
        source = self._result_path(item.source_path) if item is not None else None
        if source is not None and source.is_file():
            pane.set_image(source)
            pane.viewer.fit_image()
        self._invalidate_individual_preview()
        self.individual_editor_state_label.setText("القص الذكي جاهز للمعاينة")
        self._update_individual_crop_info()
        self._update_individual_editor_hint()

    def _toggle_individual_manual_crop(self, enabled: bool) -> None:
        pane = self._individual_editor_image_pane()
        if not enabled:
            pane.viewer.set_crop_mode(False)
            if not self.individual_auto_crop_button.isChecked():
                self.individual_auto_crop_button.setChecked(True)
            item = self._individual_editable_item()
            source = self._result_path(item.source_path) if item is not None else None
            if source is not None and source.is_file():
                pane.set_image(source)
                pane.viewer.fit_image()
            self._individual_preview_active = False
            self.individual_editor_state_label.setText("جاهز للمعاينة")
            self._update_individual_editor_hint()
            return

        item = self._individual_editable_item()
        if item is None:
            self.individual_manual_crop_button.setChecked(False)
            self.status_label.setText("حدد صفًا مرتبطًا واحدًا أولاً لاستخدام القص اليدوي.")
            return
        source = self._result_path(item.source_path)
        if source is None:
            self.individual_manual_crop_button.setChecked(False)
            return
        if self._individual_edit_source_name != item.source_name:
            self._individual_edit_source_name = item.source_name
            self._individual_crop_box = None
        self.individual_auto_crop_button.setChecked(False)
        pane.set_image(source)
        ratio = self.individual_crop_ratio_combo.currentData()
        pane.viewer.set_crop_aspect_ratio(float(ratio) if ratio is not None else None, emit=False)
        pane.viewer.set_crop_box(self._individual_crop_box)
        pane.viewer.set_crop_mode(True)
        pane.viewer.setFocus(Qt.OtherFocusReason)
        self._invalidate_individual_preview()
        self.individual_editor_state_label.setText("حدّد زوايا المنتج الأربع")
        self._update_individual_crop_info()
        self.individual_editor_hint.setText(
            "اقتصاص المنظور نشط: اسحب إطارًا أوليًا، ثم حرّك كل مقبض سماوي مستقلًا إلى ركن المنتج؛ اسحب من الداخل لتحريك الإطار كله."
        )

    def _on_individual_crop_changed(self, box: object) -> None:
        if box is None:
            self._individual_crop_box = None
        else:
            values = tuple(float(value) for value in box)  # type: ignore[arg-type]
            if len(values) == 4:
                left, top, right, bottom = values
                values = (left, top, right, top, right, bottom, left, bottom)
            if len(values) != 8:
                raise ValueError("إطار المنظور يجب أن يحتوي على أربع زوايا")
            self._individual_crop_box = values
        self._invalidate_individual_preview()
        self._update_individual_crop_info()
        self._update_individual_editor_hint()

    def _update_individual_editor_hint(self, *_args) -> None:
        if self.individual_manual_crop_button.isChecked():
            if self._individual_crop_box is None:
                self.individual_editor_hint.setText(
                    "اقتصاص المنظور نشط: اسحب إطارًا أوليًا، ثم ضع كل مقبض سماوي على ركن العبوة المقابل."
                )
                return
            kept = self._individual_editor_image_pane().viewer.crop_area_ratio() * 100.0
            self.individual_editor_hint.setText(
                f"زوايا المنظور جاهزة — المساحة المحددة {kept:.0f}% من الأصل. راجع ميل الأضلاع ثم أنشئ معاينة."
            )
            return
        mode = "تحسين ذكي محافظ" if self.individual_smart_button.isChecked() else "من دون تحسين لوني"
        strength = int(self.individual_strength_combo.currentData() or 55)
        straightening = "مع استقامة/كيّ آمن" if self.individual_straighten_check.isChecked() else "من دون استقامة"
        self.individual_editor_hint.setText(
            f"{mode} بقوة {strength}% + قص ذكي تلقائي {straightening}. لن تتغير الكتابات أو الباركود."
        )

    def _reset_individual_editor(self) -> None:
        self._individual_crop_box = None
        self.individual_manual_crop_button.setChecked(False)
        self.individual_auto_crop_button.setChecked(True)
        self.individual_smart_button.setChecked(True)
        self.individual_strength_combo.setCurrentIndex(0)
        self.individual_straighten_check.setChecked(True)
        pane = self._individual_editor_image_pane()
        pane.viewer.clear_crop()
        pane.viewer.set_crop_mode(False)
        item = self._individual_editable_item()
        source = self._result_path(item.source_path) if item is not None else None
        if source is not None and source.is_file():
            pane.set_image(source)
            pane.viewer.fit_image()
        self._individual_preview_active = False
        self._individual_preview_path = None
        self.individual_show_preview_button.setEnabled(False)
        self.individual_editor_state_label.setText("جاهز للمعاينة")
        self._update_individual_crop_info()
        self._update_individual_editor_hint()
        self.status_label.setText("أُعيدت خيارات تعديل الصورة المحددة إلى الإعدادات الذكية الموصى بها.")

    def _start_individual_preview(self) -> None:
        self._begin_individual_edit(preview_only=True)

    def _start_individual_edit(self) -> None:
        self._begin_individual_edit(preview_only=False)

    def _begin_individual_edit(self, *, preview_only: bool) -> None:
        if self.individual_worker is not None and self.individual_worker.isRunning():
            return
        item = self._individual_editable_item()
        if item is None:
            QMessageBox.information(
                self,
                APP_NAME,
                "حدد صفًا مرتبطًا واحدًا فقط لتعديل صورته. اربط الصف برقم الصنف أولاً إذا كان للمراجعة.",
            )
            return
        manual_crop_enabled = self.individual_manual_crop_button.isChecked()
        if manual_crop_enabled and self._individual_crop_box is None:
            QMessageBox.information(
                self,
                APP_NAME,
                "اسحب إطارًا أوليًا ثم ضع الزوايا الأربع على أركان المنتج، أو اختر القص الذكي التلقائي.",
            )
            return
        if self.current_workspace is None:
            QMessageBox.warning(self, APP_NAME, "مجلد المهمة الحالية غير متاح.")
            return

        self._pending_individual_position = self._capture_results_position()
        self._individual_preview_active = False
        manual_crop: tuple[float, ...] | None = None
        if manual_crop_enabled and self._individual_crop_box is not None:
            manual_crop = self._individual_crop_box
            target_ratio = self.individual_crop_ratio_combo.currentData()
            if target_ratio is not None:
                manual_crop = (*manual_crop, float(target_ratio))
        self.individual_worker = IndividualEditWorker(
            self.current_workspace,
            item.source_name,
            preview_only=preview_only,
            manual_crop=manual_crop,
            smart_enhance=self.individual_smart_button.isChecked(),
            enhancement_strength=int(self.individual_strength_combo.currentData() or 55),
            smart_crop=self.individual_auto_crop_button.isChecked() and not manual_crop_enabled,
            auto_straighten=self.individual_straighten_check.isChecked(),
            remove_background=self.remove_background_check.isChecked(),
            image_options=self._final_image_options(),
        )
        self.individual_worker.progress_changed.connect(self._on_progress)
        self.individual_worker.completed.connect(self._on_individual_edit_completed)
        self.individual_worker.failed.connect(self._on_individual_edit_failed)
        self.individual_worker.finished.connect(self._on_individual_worker_finished)
        self._set_busy(True)
        operation = "معاينة" if preview_only else "حفظ"
        self.individual_editor_state_label.setText(f"جارٍ {operation} الصورة…")
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setFormat(f"{operation} الصورة المحددة")
        self.status_label.setText(f"جارٍ {operation} الصورة: {item.source_name}")
        self.individual_worker.start()

    def _on_individual_edit_completed(self, payload: object) -> None:
        restore_position = self._pending_individual_position or self._capture_results_position()
        self._pending_individual_position = None
        self._set_busy(False)
        if isinstance(payload, IndividualImagePreview):
            preview_path = Path(payload.preview_path)
            pane = self._individual_editor_image_pane()
            self._individual_preview_path = preview_path if preview_path.is_file() else None
            self.individual_show_preview_button.setEnabled(self._individual_preview_path is not None)
            pane.set_image(self._individual_preview_path)
            pane.viewer.set_crop_mode(False)
            pane.viewer.fit_image()
            self._individual_preview_active = True
            self.individual_editor_state_label.setText("معاينة غير محفوظة")
            self.individual_editor_state_label.setProperty("previewPending", True)
            self.individual_editor_state_label.style().unpolish(self.individual_editor_state_label)
            self.individual_editor_state_label.style().polish(self.individual_editor_state_label)
            effective = int(payload.analysis.get("effective_strength", 0) or 0)
            automatic = int(payload.analysis.get("automatic_strength", 0) or 0)
            crop_kind = "القص اليدوي" if bool(payload.analysis.get("manual_crop")) else "القص الذكي"
            warning_text = f" — {len(payload.warnings)} تنبيه" if payload.warnings else ""
            self.progress.setRange(0, 1)
            self.progress.setValue(1)
            self.progress.setFormat("المعاينة جاهزة — لم يُحفظ شيء بعد")
            self.status_label.setText(
                f"معاينة {crop_kind}: قوة التحسين الفعلية {effective}% "
                f"(اختيار تلقائي {automatic}%){warning_text}. راجع الصورة ثم اضغط حفظ التعديل."
            )
            if restore_position is not None:
                self._restore_results_position(restore_position)
                pane.set_image(self._individual_preview_path)
            pane.viewer.setFocus(Qt.OtherFocusReason)
            self._update_controls()
            return

        if not isinstance(payload, BatchRunResult):
            self._on_individual_edit_failed("نتيجة غير متوقعة من عامل تعديل الصورة الفردية")
            return
        self.current_result = payload
        self.current_workspace = Path(payload.workspace)
        self._individual_editor_dirty = False
        self._individual_preview_active = False
        self._individual_preview_path = None
        self.individual_show_preview_button.setEnabled(False)
        self._individual_crop_box = None
        self.individual_manual_crop_button.setChecked(False)
        self.individual_auto_crop_button.setChecked(True)
        pane = self._individual_editor_image_pane()
        pane.viewer.clear_crop()
        pane.viewer.set_crop_mode(False)
        self._populate_results(restore_position=restore_position)
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.progress.setFormat("تم حفظ تعديل الصورة المحددة")
        self.status_label.setText(
            "تم تحسين المنتج المحدد وحفظه بمقاس 800×700 WebP، وتحديث التقارير وحزمة ZIP دون تغيير بقية الصور."
        )
        self.individual_editor_state_label.setText("تم حفظ التعديل")
        self.individual_editor_state_label.setProperty("previewPending", False)
        self._update_individual_editor_hint()
        self._update_controls()
        self.individual_editor_dialog.accept()

    def _on_individual_edit_failed(self, traceback_text: str) -> None:
        restore_position = self._pending_individual_position
        self._pending_individual_position = None
        self._set_busy(False)
        log_path = DATA_ROOT / "last_individual_edit_error.log"
        log_path.write_text(traceback_text, encoding="utf-8")
        guidance = _friendly_error_message(traceback_text)
        self.progress.setFormat("تعذر تعديل الصورة المحددة — لم تتغير النتائج")
        self.status_label.setText(f"لم يتغير أي ملف: {guidance.splitlines()[0]}")
        self.individual_editor_state_label.setText("تعذر التنفيذ — عدّل الخيارات وحاول مجددًا")
        self.individual_editor_state_label.setProperty("previewPending", False)
        if restore_position is not None:
            self._restore_results_position(restore_position)
        QMessageBox.warning(
            self,
            APP_NAME,
            "تعذر تجهيز الصورة المحددة.\n\n"
            f"{guidance}\n\n"
            "لم يتغير الناتج السابق أو التقارير أو حزمة ZIP، ويمكنك تعديل الخيارات والمحاولة مرة أخرى.\n"
            f"سجل التفاصيل محفوظ في:\n{log_path}",
        )
        self._update_controls()

    def _on_individual_worker_finished(self) -> None:
        worker = self.sender()
        if isinstance(worker, IndividualEditWorker):
            worker.deleteLater()
            if self.individual_worker is worker:
                self.individual_worker = None
            self._update_controls()

    def _apply_style(self) -> None:
        QApplication.setFont(QFont("Segoe UI", 10))
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #f4f7fb; color: #172033; }
            QFrame#header { background: #0f2747; border-radius: 12px; }
            QFrame#header QLabel { background: transparent; }
            QLabel#appTitle { color: white; font-size: 22px; font-weight: 800; }
            QLabel#appSubtitle { color: #c7d8ee; font-size: 11px; }
            QLabel#versionBadge { color: white; background: #1d4f83; border: 1px solid #4978a8; border-radius: 13px; padding: 6px 12px; }
            QLabel#phaseBadge { color: #0f2747; background: #d9ebff; border: 1px solid #82aed6; border-radius: 13px; padding: 6px 14px; font-weight: 900; }
            QLabel#pageTitle { color: #17324d; font-size: 19px; font-weight: 900; }
            QLabel#pageSubtitle { color: #60758b; font-size: 10px; }
            QFrame#panel { background: white; border: 1px solid #dce4ef; border-radius: 12px; }
            QScrollArea#resultsListPane, QFrame#previewWorkspace { background: #ffffff; border: 1px solid #d8e2ed; border-radius: 10px; }
            QFrame#resultsListPaneContent { background: #ffffff; border: none; }
            QFrame#fixedActionBar { background: #f7faff; border: 1px solid #d5e1ed; border-radius: 10px; }
            QDialog#individualEditorDialog { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #e7f1ff, stop:0.52 #f4f7fb, stop:1 #f4ecff); }
            QFrame#editorHeader { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0f2747, stop:0.55 #163d68, stop:1 #3b2575); border: 1px solid #355b83; border-radius: 13px; }
            QFrame#editorFooter { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ffffff, stop:1 #eef4ff); border: 1px solid #bdcde0; border-radius: 12px; }
            QLabel#editorProductLabel { color: #ffffff; font-size: 17px; font-weight: 900; background: transparent; }
            QLabel#editorMetaLabel { color: #d6e7f7; font-size: 10px; background: transparent; }
            QLabel#editorStateBadge { color: #07543c; background: #d9f8ec; border: 1px solid #70cfad; border-radius: 13px; padding: 7px 13px; font-weight: 900; }
            QLabel#editorStateBadge[previewPending="true"] { color: #7a4300; background: #fff0b8; border: 1px solid #e5ad26; }
            QSplitter#individualEditorSplitter::handle { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #9db5cb, stop:0.5 #d2deea, stop:1 #9db5cb); border-radius: 4px; margin: 5px 1px; }
            QSplitter#individualEditorSplitter::handle:hover { background: #50a8d6; }
            QFrame#editorPreviewFrame { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #17283b, stop:1 #09131f); border: 2px solid #2e526f; border-radius: 14px; }
            QFrame#editorPreviewFrame QLabel#previewTitle { color: #e6f4ff; background: transparent; font-size: 12px; font-weight: 900; }
            QFrame#editorPreviewFrame QScrollArea#previewScroll { background: #08121d; border: 1px solid #365b78; border-radius: 9px; }
            QFrame#editorPreviewFrame QLabel#previewImage { background: #08121d; color: #a8bfd3; }
            QFrame#editorPreviewFrame QLabel#previewHint { color: #bad0df; background: transparent; font-weight: 700; }
            QSplitter#resultsHorizontalSplitter::handle { background: #d9e4ef; border-radius: 4px; margin: 6px 1px; }
            QSplitter#resultsHorizontalSplitter::handle:hover { background: #7da5c8; }
            QLabel#selectedProductLabel { color: #17324d; background: #edf5fd; border: 1px solid #c8dced; border-radius: 7px; padding: 9px 12px; font-size: 12px; font-weight: 900; }
            QTabWidget#previewTabs::pane { background: #ffffff; border: 1px solid #ccd9e6; border-radius: 7px; top: -1px; }
            QTabWidget#previewTabs QTabBar::tab { background: #eaf0f6; color: #49647e; border: 1px solid #ccd9e6; padding: 8px 24px; min-width: 90px; font-weight: 800; }
            QTabWidget#previewTabs QTabBar::tab:selected { background: #ffffff; color: #125a93; border-bottom-color: #ffffff; }
            QTabWidget#previewTabs QTabBar::tab:hover:!selected { background: #dceaf6; }
            QPushButton#editImageButton { background: #087a63; color: white; border: 1px solid #087a63; padding: 9px 16px; font-weight: 900; }
            QPushButton#editImageButton:hover { background: #066753; }
            QGroupBox { background: #fbfcfe; border: 1px solid #dce4ef; border-radius: 8px; margin-top: 12px; padding-top: 10px; font-weight: 700; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top center; padding: 0 8px; color: #27496d; }
            QLineEdit, QComboBox, QListWidget, QTableWidget { background: white; border: 1px solid #ccd7e4; border-radius: 6px; padding: 6px; selection-background-color: #d8eaff; selection-color: #102a43; }
            QComboBox { min-height: 26px; padding-left: 8px; padding-right: 8px; }
            QComboBox::drop-down { border: none; width: 22px; }
            QLineEdit#catalogPath { background: #ffffff; color: #17324d; font-weight: 700; padding: 8px 10px; }
            QLabel#catalogStatus { color: #19704a; background: #edf9f3; border: 1px solid #bfe5d0; border-radius: 5px; padding: 5px 8px; font-size: 9px; }
            QListWidget#productImageList { padding: 4px; }
            QTableWidget { gridline-color: #e7edf5; }
            QTableWidget#resultsTable { padding: 0px; }
            QHeaderView::section { background: #eef3f8; color: #27496d; border: none; border-bottom: 1px solid #ccd7e4; padding: 8px; font-weight: 700; }
            QPushButton { border-radius: 7px; padding: 8px 13px; font-weight: 700; }
            QPushButton#primaryButton { background: #1769aa; color: white; border: 1px solid #1769aa; }
            QPushButton#primaryButton:hover { background: #125a93; }
            QPushButton#secondaryButton { background: #eef5fc; color: #165b91; border: 1px solid #b8cee2; }
            QPushButton#secondaryButton:hover { background: #dfeefa; }
            QPushButton#textButton { background: transparent; color: #566b80; border: none; padding: 5px; }
            QPushButton#textButton:hover { color: #b42335; }
            QPushButton:disabled { background: #e5eaf0; color: #96a3b1; border-color: #d5dce5; }
            QProgressBar { background: #e8eef5; border: none; border-radius: 7px; height: 15px; text-align: center; color: #27496d; }
            QProgressBar::chunk { background: #2c8ac6; border-radius: 7px; }
            QFrame#statCard { background: #f8fafc; border: 1px solid #dce4ef; border-radius: 9px; }
            QFrame#previewFrame { background: #f8fafc; border: 1px solid #dce4ef; border-radius: 8px; }
            QLabel#previewTitle { color: #49647e; font-weight: 700; }
            QFrame#individualEditor { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f4f1ff, stop:0.45 #eef8ff, stop:1 #f5fbff); border: 1px solid #a99bdc; border-radius: 14px; }
            QLabel#individualEditorTitle { color: #33206d; font-weight: 900; font-size: 15px; background: transparent; }
            QLabel#editorToolSubtitle { color: #64748b; background: transparent; font-size: 9px; }
            QTabWidget#individualEditorTabs { background: transparent; }
            QTabWidget#individualEditorTabs::pane { background: rgba(255, 255, 255, 150); border: 1px solid #b7c6da; border-radius: 10px; top: -1px; }
            QTabWidget#individualEditorTabs QTabBar::tab { background: #e7edf7; color: #53677f; border: 1px solid #b7c6da; padding: 7px 10px; min-width: 72px; font-size: 10px; font-weight: 900; }
            QTabWidget#individualEditorTabs QTabBar::tab:selected { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0e7490, stop:1 #2563eb); color: #ffffff; border-color: #0e7490; }
            QTabWidget#individualEditorTabs QTabBar::tab:hover:!selected { background: #d7e7f6; color: #17324d; }
            QScrollArea#editorToolsScroll { background: transparent; border: none; }
            QWidget#editorCropTab, QWidget#editorEnhanceTab, QWidget#editorCompareTab { background: transparent; }
            QScrollArea#editorToolsScroll QScrollBar:vertical { background: #e8eef7; width: 9px; margin: 3px 1px; border-radius: 4px; }
            QScrollArea#editorToolsScroll QScrollBar::handle:vertical { background: #7695b7; min-height: 28px; border-radius: 4px; }
            QScrollArea#editorToolsScroll QScrollBar::add-line:vertical, QScrollArea#editorToolsScroll QScrollBar::sub-line:vertical { height: 0px; }
            QLabel#editorToolSectionTitle { color: #183b56; font-weight: 900; font-size: 11px; background: transparent; }
            QFrame#editorEnhanceCard { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #e9f1ff, stop:1 #ffffff); border: 1px solid #8ab4f8; border-radius: 11px; }
            QFrame#editorCropCard { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #e1fbff, stop:1 #ffffff); border: 1px solid #63c5d6; border-radius: 11px; }
            QFrame#editorCompareCard { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #f0e9ff, stop:1 #ffffff); border: 1px solid #b59ae8; border-radius: 11px; }
            QLabel#cropInfoLabel { color: #075985; background: #e6f7ff; border: 1px solid #8fd3eb; border-radius: 7px; padding: 6px 8px; font-weight: 800; }
            QLabel#individualEditorHint { color: #36506b; background: #ffffff; border: 1px solid #bac9da; border-radius: 8px; padding: 7px; font-size: 9px; }
            QComboBox#individualStrength, QComboBox#individualStrengthCombo { background: #ffffff; color: #1e3a8a; border: 1px solid #93b4ee; font-weight: 800; }
            QComboBox#individualCropRatio, QComboBox#cropRatioCombo { background: #ffffff; color: #0e6378; border: 1px solid #70c3d3; font-weight: 800; }
            QPushButton#individualSmartButton { background: #ffffff; color: #1d4ed8; border: 1px solid #7da7ed; padding: 7px 9px; }
            QPushButton#individualSmartButton:checked { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1d4ed8, stop:1 #3b82f6); color: #ffffff; border: 2px solid #1644bd; }
            QPushButton#individualAutoCropButton { background: #ffffff; color: #087a63; border: 1px solid #66bea9; padding: 7px 9px; }
            QPushButton#individualAutoCropButton:checked { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #087a63, stop:1 #16a085); color: #ffffff; border: 2px solid #06634f; }
            QPushButton#individualManualCropButton { background: #ffffff; color: #08708a; border: 1px solid #64bfd1; padding: 7px 9px; }
            QPushButton#individualManualCropButton:checked { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #07829b, stop:1 #19b6c8); color: #ffffff; border: 2px solid #056a7e; }
            QPushButton#cropUtilityButton { background: #edfaff; color: #08677c; border: 1px solid #8dcfda; padding: 6px 8px; }
            QPushButton#cropUtilityButton:hover { background: #d4f5fb; border-color: #21a8bd; }
            QPushButton#showSourceButton { background: #ede9fe; color: #5b21b6; border: 1px solid #b6a0e5; padding: 7px 9px; }
            QPushButton#showSourceButton:hover { background: #ddd3fb; }
            QPushButton#showPreviewButton { background: #fff1c7; color: #8a4b00; border: 1px solid #e0ae3f; padding: 7px 9px; }
            QPushButton#showPreviewButton:hover { background: #ffe39a; }
            QPushButton#showPreviewButton:disabled { background: #e8ebef; color: #9aa4ae; border-color: #d2d7dd; }
            QPushButton#individualPreviewButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1d4ed8, stop:1 #287ed0); color: white; border: 1px solid #1647b7; padding: 11px 18px; min-width: 125px; font-weight: 900; }
            QPushButton#individualPreviewButton:hover { background: #1744bd; }
            QPushButton#individualApplyButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #087a63, stop:1 #10a37f); color: white; border: 1px solid #066653; padding: 11px 18px; min-width: 145px; font-weight: 900; }
            QPushButton#individualApplyButton:hover { background: #066753; }
            QScrollArea#inputsPageScroll, QScrollArea#resultsPageScroll { background: #f4f7fb; border: none; }
            QWidget#inputsScrollContent, QWidget#resultsScrollContent { background: #f4f7fb; }
            QScrollArea#inputsPageScroll QScrollBar:vertical, QScrollArea#resultsPageScroll QScrollBar:vertical { width: 18px; background: #e8eef5; margin: 2px; }
            QScrollArea#inputsPageScroll QScrollBar::handle:vertical, QScrollArea#resultsPageScroll QScrollBar::handle:vertical { background: #6f8eaa; min-height: 42px; border-radius: 7px; }
            QScrollArea#inputsPageScroll QScrollBar::handle:vertical:hover, QScrollArea#resultsPageScroll QScrollBar::handle:vertical:hover { background: #2c8ac6; }
            QListWidget#productImageList QScrollBar:vertical { width: 14px; background: #eef3f8; }
            QListWidget#productImageList QScrollBar::handle:vertical { background: #89a2b9; min-height: 28px; border-radius: 6px; }
            QPushButton#reviewPreviewButton { background: #eaf4fd; color: #174e78; border: 1px solid #8bb9dc; font-weight: 800; padding: 8px; }
            QPushButton#reviewPreviewButton:hover { background: #d9edfb; }
            QLabel#tablePosition { color: #385670; font-weight: 800; padding: 3px 5px; }
            QPushButton#tableNavButton { background: #ffffff; color: #165b91; border: 1px solid #b8cee2; padding: 5px 10px; }
            QPushButton#tableNavButton:hover { background: #e7f2fb; }
            QPushButton#manualToggleButton { background: #eaf4fd; color: #174e78; border: 1px solid #8bb9dc; font-weight: 900; padding: 7px 10px; text-align: right; }
            QPushButton#manualToggleButton:checked { background: #d7ebfa; color: #0f4f7a; }
            QGroupBox#manualLinkGroup { background: #f8fbfe; border: 1px solid #c6d9ea; }
            QScrollArea#previewScroll { background: white; border: 1px solid #c7d3df; border-radius: 6px; }
            QLabel#previewImage { background: white; color: #8b99a8; }
            QLabel#previewHint { color: #65788d; font-size: 9px; }
            QLabel#manualContext { color: #27496d; background: #edf5fd; border: 1px solid #c9dced; border-radius: 5px; padding: 6px; }
            QPushButton#zoomButton { background: #ffffff; color: #27496d; border: 1px solid #c4d2e0; padding: 4px 7px; min-width: 28px; }
            QPushButton#zoomButton:hover { background: #e9f3fc; }
            QLabel#hintLabel { color: #64748b; font-size: 10px; }
            QGroupBox#enhancementGroup { background: #f7fbff; border: 1px solid #a9c9e3; }
            QGroupBox#enhancementGroup::title { color: #135f91; font-weight: 900; }
            QCheckBox#enhancementMaster { color: #0d4f78; font-size: 11px; font-weight: 900; spacing: 8px; }
            QLabel#strengthValue { color: white; background: #1769aa; border-radius: 10px; padding: 3px 5px; font-weight: 800; }
            QSlider::groove:horizontal { height: 7px; background: #dbe8f3; border-radius: 3px; }
            QSlider::sub-page:horizontal { background: #2c8ac6; border-radius: 3px; }
            QSlider::handle:horizontal { background: #ffffff; border: 2px solid #1769aa; width: 17px; margin: -6px 0; border-radius: 9px; }
            QGroupBox#aiGroup { background: #eef8ff; border: 2px solid #2c8ac6; }
            QGroupBox#aiGroup::title { color: #075985; font-weight: 900; }
            QLabel#aiBadge { color: white; background: #0b74b8; border-radius: 10px; padding: 5px 8px; font-weight: 800; }
            QLabel#aiDescription { color: #35566f; font-size: 9px; }
            QCheckBox#aiToggle { color: #0b4f7a; font-size: 12px; font-weight: 900; spacing: 10px; padding: 5px; }
            QCheckBox#aiToggle::indicator { width: 22px; height: 22px; }
            QLabel#statusLabel { color: #465b70; }
            QLabel#copyrightLabel { color: #6b7f93; }
            QSplitter::handle:horizontal { background: transparent; width: 7px; }
            QSplitter#resultsVerticalSplitter::handle:vertical { background: #c7d6e5; height: 9px; margin: 2px 90px; border-radius: 4px; }
            QSplitter#resultsVerticalSplitter::handle:vertical:hover { background: #2c8ac6; }

            /* استوديو المراجعة 1.2: ألوان دلالية وعمق خفيف بدل اللون الموحد */
            QFrame#reviewPanel { background: #edf3f9; border: 1px solid #cbd8e6; border-radius: 15px; }
            QFrame#reviewTopBar {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #132a4a, stop:0.55 #1d3f70, stop:1 #3730a3);
                border: 1px solid #5574a4; border-radius: 13px;
            }
            QFrame#reviewTopBar QLabel#pageTitle { color: #ffffff; font-size: 18px; background: transparent; }
            QFrame#reviewTopBar QLabel#pageSubtitle { color: #dbeafe; background: transparent; }
            QFrame#reviewTopBar QFrame#statCard { background: rgba(255, 255, 255, 236); border: 1px solid #b9c9e2; border-radius: 10px; }
            QPushButton#backToSetupButton { background: #ffffff; color: #263b64; border: 1px solid #b8c7e0; padding: 7px 13px; }
            QPushButton#backToSetupButton:hover { background: #eaf2ff; border-color: #86a5d8; }

            QFrame#resultsListPane { background: #ffffff; border: 1px solid #c7d6e6; border-radius: 13px; }
            QLabel#sectionTitle { color: #17324d; font-size: 14px; font-weight: 900; }
            QTableWidget#resultsTable { background: #ffffff; border: 1px solid #cbd8e6; border-radius: 9px; padding: 0px; gridline-color: #e5ebf2; alternate-background-color: #f5f8fc; selection-background-color: #dbeafe; selection-color: #102a43; }
            QTableWidget#resultsTable::item { padding: 8px 6px; border-bottom: 1px solid #edf1f6; }
            QTableWidget#resultsTable::item:selected { background: #dbeafe; color: #0f2747; border: 1px solid #5b8fd6; }
            QTableWidget#resultsTable QHeaderView::section { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #334e72, stop:1 #243b5c); color: #ffffff; border: none; border-left: 1px solid #52719a; padding: 9px 5px; font-weight: 900; }
            QTableWidget#resultsTable QScrollBar:vertical { width: 15px; background: #e8eef5; margin: 2px; border-radius: 7px; }
            QTableWidget#resultsTable QScrollBar::handle:vertical { background: #6d8fb4; min-height: 36px; border-radius: 6px; }
            QTableWidget#resultsTable QScrollBar::handle:vertical:hover { background: #3b6fa8; }
            QLineEdit#resultSearchEdit { background: #f8fbff; border: 1px solid #9fb8d2; padding: 7px 10px; }
            QComboBox#resultStatusFilter { background: #fff8e8; color: #7a4a00; border: 1px solid #e7bd63; font-weight: 800; }

            QFrame#reviewStudio { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #16243a, stop:1 #0b1220); border: 1px solid #273c58; border-radius: 14px; }
            QFrame#selectedProductCard { background: #ffffff; border: 1px solid #b8c8da; border-radius: 12px; }
            QLabel#selectedProductName { color: #142f4b; background: transparent; font-size: 15px; font-weight: 900; }
            QLabel#selectedStatusBadge { background: #edf2f7; color: #475569; border: 1px solid #cbd5e1; border-radius: 11px; padding: 4px 9px; font-weight: 900; }
            QFrame#productMetaTile { background: #f4f8fc; border: 1px solid #d5e1ed; border-radius: 7px; }
            QLabel#metaCaption { color: #60758b; background: transparent; font-size: 9px; font-weight: 800; }
            QLabel#selectedItemCode, QLabel#selectedBarcode, QLabel#selectedFileName { color: #17324d; background: transparent; font-weight: 900; }
            QLabel#selectedFileName { color: #4b5f74; font-weight: 700; }
            QPushButton#editImageButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #8b5cf6, stop:1 #5b21b6); color: #ffffff; border: 1px solid #4c1d95; padding: 8px 13px; font-weight: 900; }
            QPushButton#editImageButton:hover { background: #6d28d9; }
            QPushButton#openImageButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #fb923c, stop:1 #ea580c); color: white; border: 1px solid #c2410c; padding: 8px 11px; }
            QPushButton#openImageButton:hover { background: #f97316; }
            QPushButton#focusLinkButton { background: #e0ecff; color: #1d4f91; border: 1px solid #8cb1e8; padding: 8px 11px; }
            QPushButton#focusLinkButton:hover { background: #cfe1ff; }

            QTabWidget#studioPreviewTabs::pane { background: #0a101b; border: 1px solid #334a68; border-radius: 9px; top: -1px; }
            QTabWidget#studioPreviewTabs QTabBar::tab { background: #243750; color: #c8d7e8; border: 1px solid #3c5573; padding: 7px 24px; min-width: 95px; font-weight: 900; }
            QTabWidget#studioPreviewTabs QTabBar::tab:selected { background: #0d1725; color: #ffffff; border-bottom-color: #0d1725; }
            QTabWidget#studioPreviewTabs QTabBar::tab:hover:!selected { background: #315071; }
            QFrame#studioPreviewFrame { background: #0d1725; border: 1px solid #334a68; border-radius: 8px; }
            QFrame#studioPreviewFrame QLabel#previewTitle { color: #e2e8f0; background: transparent; font-weight: 900; }
            QFrame#studioPreviewFrame QScrollArea#previewScroll { background: #090f19; border: 1px solid #293d57; border-radius: 7px; }
            QFrame#studioPreviewFrame QLabel#previewImage { background: #090f19; color: #93a6ba; }
            QFrame#studioPreviewFrame QLabel#previewHint { color: #9fb0c2; background: transparent; }
            QFrame#studioPreviewFrame QPushButton#zoomButton { background: #243750; color: #f8fafc; border: 1px solid #506b8b; padding: 5px 8px; }
            QFrame#studioPreviewFrame QPushButton#zoomButton:hover { background: #365577; }

            QFrame#alwaysVisibleLinkBar { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2563eb, stop:0.6 #4338ca, stop:1 #5b21b6); border: 1px solid #312e81; border-radius: 11px; }
            QLabel#linkBarTitle { color: #ffffff; background: transparent; font-size: 13px; font-weight: 900; }
            QFrame#alwaysVisibleLinkBar QLabel#manualContext { color: #e8edff; background: transparent; border: none; padding: 2px; font-weight: 700; }
            QLabel#selectedCountBadge, QLabel#manualReferenceBadge { color: #ffffff; background: rgba(10, 20, 60, 110); border: 1px solid #9caef8; border-radius: 10px; padding: 4px 8px; font-weight: 900; }
            QLineEdit#manualItemEdit { background: #ffffff; color: #15243c; border: 2px solid #b8c9ff; padding: 7px 10px; font-weight: 800; selection-background-color: #c7d2fe; }
            QLineEdit#manualItemEdit:focus { border: 2px solid #fbbf24; }
            QPushButton#manualLinkPrimaryButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #16a39a, stop:1 #047857); color: #ffffff; border: 1px solid #065f46; padding: 7px 13px; font-weight: 900; }
            QPushButton#manualLinkPrimaryButton:hover { background: #0d9488; }
            QPushButton#linkToolButton { background: #eef2ff; color: #3730a3; border: 1px solid #b8c2f4; padding: 5px 9px; }
            QPushButton#linkToolButton:hover { background: #dfe4ff; }
            QPushButton#suggestNearbyButton { background: #fff3d6; color: #8a5200; border: 1px solid #edbd55; padding: 5px 9px; }
            QPushButton#suggestNearbyButton:hover { background: #ffe5a8; }
            QPushButton#referenceLinkButton { background: #e7f8f2; color: #066a50; border: 1px solid #78cbb0; padding: 5px 9px; }
            QPushButton#referenceLinkButton:hover { background: #cef1e4; }

            QFrame#fixedActionBar { background: #ffffff; border: 1px solid #cbd8e6; border-radius: 10px; }
            QLabel#deliveryHint { color: #526b82; background: transparent; }
            QPushButton#saveDeliveryButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #14b8a6, stop:1 #047857); color: white; border: 1px solid #065f46; padding: 8px 16px; font-weight: 900; }
            QPushButton#saveDeliveryButton:hover { background: #0d9488; }
            """
        )

    def _select_catalog(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "اختيار ملف المنتجات",
            str(Path.home()),
            "ملفات Excel (*.xlsx *.xlsm)",
        )
        if filename:
            self.catalog_path = Path(filename)
            display_name = self.catalog_path.name
            self.catalog_edit.setText(display_name)
            self.catalog_edit.setCursorPosition(0)
            self.catalog_edit.setToolTip(f"المسار الكامل:\n{self.catalog_path}")
            self.catalog_status_label.setText("تم اختيار ملف Excel بنجاح")
            self.catalog_status_label.setToolTip(str(self.catalog_path))
            self._update_controls()

    def _select_images(self) -> None:
        filenames, _ = QFileDialog.getOpenFileNames(
            self,
            "إضافة صور المنتجات",
            str(Path.home()),
            "الصور (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff)",
        )
        self._add_paths(filenames)

    def _select_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "اختيار مجلد الصور", str(Path.home()))
        if folder:
            self._add_paths([folder])

    def _expand_image_paths(self, paths: Iterable[str]) -> list[Path]:
        expanded: list[Path] = []
        for raw in paths:
            path = Path(raw).expanduser()
            if path.is_dir():
                expanded.extend(
                    sorted(
                        child
                        for child in path.rglob("*")
                        if child.is_file() and child.suffix.casefold() in SUPPORTED_IMAGE_EXTENSIONS
                    )
                )
            elif path.is_file() and path.suffix.casefold() in SUPPORTED_IMAGE_EXTENSIONS:
                expanded.append(path)
        return expanded

    def _add_paths(self, paths: Iterable[str]) -> None:
        raw_paths = list(paths)
        known = {path.resolve() for path in self.image_paths}
        added = 0
        self.image_list.setUpdatesEnabled(False)
        try:
            for path in self._expand_image_paths(raw_paths):
                resolved = path.resolve()
                if resolved in known:
                    continue
                self.image_paths.append(resolved)
                item = QListWidgetItem(resolved.name)
                item.setToolTip(str(resolved))
                item.setData(Qt.UserRole, str(resolved))
                self.image_list.addItem(item)
                known.add(resolved)
                added += 1
        finally:
            self.image_list.setUpdatesEnabled(True)
            self.image_list.viewport().update()
        if added == 0 and raw_paths:
            self.status_label.setText("لم تُضف صور جديدة؛ قد تكون مكررة أو بصيغة غير مدعومة.")
        self._update_image_count()
        self._update_controls()

    def _remove_selected_images(self) -> None:
        for item in self.image_list.selectedItems():
            path = Path(item.data(Qt.UserRole)).resolve()
            self.image_paths = [candidate for candidate in self.image_paths if candidate.resolve() != path]
            self.image_list.takeItem(self.image_list.row(item))
        self._update_image_count()
        self._update_controls()

    def _clear_images(self) -> None:
        self.image_paths.clear()
        self.image_list.clear()
        self._update_image_count()
        self._update_controls()

    def _update_image_count(self) -> None:
        count = len(self.image_paths)
        self.image_count_label.setText(f"{count} صورة")

    def _new_workspace(self) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return JOBS_ROOT / f"{stamp}-{uuid.uuid4().hex[:6]}"

    def _start_batch(self) -> None:
        if self.catalog_path is None or not self.catalog_path.is_file():
            QMessageBox.warning(self, APP_NAME, "اختر ملف Excel صالحًا أولًا.")
            return
        if not self.image_paths:
            QMessageBox.warning(self, APP_NAME, "أضف صورة واحدة على الأقل.")
            return
        # لا تستبدل نتيجة ناجحة قبل أن تكتمل المهمة الجديدة. تبقى القائمة
        # ومساحة العمل السابقة متاحتين إذا فشل Excel أو تعذرت الكتابة.
        pending_workspace = self._new_workspace()
        self._pending_batch_workspace = pending_workspace
        self._set_busy(True)
        self.progress.setRange(0, len(self.image_paths))
        self.progress.setValue(0)
        self.progress.setFormat("تهيئة الكتالوج...")
        self.status_label.setText("جارٍ استيراد Excel وتشغيل قراءة الباركود...")
        self.batch_worker = BatchWorker(
            self.catalog_path,
            list(self.image_paths),
            pending_workspace,
            self.remove_background_check.isChecked(),
            self.enhance_product_check.isChecked(),
            self._final_image_options(),
        )
        self.batch_worker.progress_changed.connect(self._on_progress)
        self.batch_worker.completed.connect(self._on_batch_completed)
        self.batch_worker.failed.connect(self._on_worker_failed)
        self.batch_worker.start()

    def _on_progress(self, done: int, total: int, name: str) -> None:
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)
        self.progress.setFormat(f"{done}/{total} — {name}")
        self.status_label.setText(f"معالجة: {name}")

    def _on_batch_completed(self, result: BatchRunResult) -> None:
        self._pending_batch_workspace = None
        self.current_result = result
        self.current_workspace = Path(result.workspace)
        self.progress.setRange(0, max(result.summary["total"], 1))
        self.progress.setValue(result.summary["total"])
        self.progress.setFormat("اكتملت المعالجة")
        self.status_label.setText(
            f"اكتملت {result.summary['total']} صورة: {result.summary['matched']} مطابق، "
            f"{result.summary['review']} للمراجعة، {result.summary['errors']} أخطاء."
        )
        self._populate_results()
        self._show_results_page()
        self._set_busy(False)
        self._update_controls()
        QMessageBox.information(
            self,
            APP_NAME,
            "اكتملت المعالجة. راجع الحالات غير المؤكدة، ثم احفظ حزمة النتائج ZIP.",
        )

    def _on_worker_failed(self, traceback_text: str) -> None:
        failed_workspace = self._pending_batch_workspace
        self._pending_batch_workspace = None
        self._pending_manual_position = None
        self._set_busy(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("تعذرت المعالجة")

        log_root = failed_workspace or DATA_ROOT
        try:
            log_root.mkdir(parents=True, exist_ok=True)
            log_path = log_root / "last_error.log"
            log_path.write_text(traceback_text, encoding="utf-8")
        except OSError:
            log_path = DATA_ROOT / "last_error.log"
            try:
                DATA_ROOT.mkdir(parents=True, exist_ok=True)
                log_path.write_text(traceback_text, encoding="utf-8")
            except OSError:
                pass

        guidance = _friendly_error_message(traceback_text)
        previous_preserved = self.current_result is not None
        if previous_preserved:
            self.status_label.setText("تعذرت المهمة الجديدة — النتائج السابقة محفوظة ويمكن متابعتها.")
            preservation_note = "النتائج السابقة محفوظة ولم يتغير أي ملف منها."
        else:
            self.status_label.setText("تعذرت المعالجة — راجع الإرشاد ثم أعد المحاولة.")
            preservation_note = "لم تُنشأ نتائج جزئية معتمدة لهذه المهمة."
        QMessageBox.warning(
            self,
            APP_NAME,
            "تعذرت معالجة المهمة.\n\n"
            f"{guidance}\n\n"
            f"{preservation_note}\n"
            f"سجل التفاصيل محفوظ في:\n{log_path}",
        )
        self._update_controls()

    def _on_manual_failed(self, traceback_text: str) -> None:
        """Report an edit/link lookup error locally without marking the whole batch failed."""
        restore_position = self._pending_manual_position
        self._pending_manual_position = None
        self._pending_manual_source_names = ()
        self.manual_link_button.setText("ربط الآن")
        self._set_busy(False)
        log_path = DATA_ROOT / "last_manual_link_error.log"
        log_path.write_text(traceback_text, encoding="utf-8")
        guidance = _friendly_error_message(traceback_text)
        self.progress.setFormat("اكتملت المعالجة — تعذر تعديل الصف المحدد")
        self.status_label.setText(f"لم تتغير النتائج: {guidance.splitlines()[0]}")
        if restore_position is not None:
            self._restore_results_position(restore_position)
        QMessageBox.warning(
            self,
            APP_NAME,
            "تعذر تعديل/ربط الصف المحدد.\n\n"
            f"{guidance}\n\n"
            "لم يتغير أي ناتج، ويمكنك تصحيح الرقم والمحاولة مرة أخرى.\n"
            f"سجل التفاصيل محفوظ في:\n{log_path}",
        )
        self._update_controls()

    def _visible_result_rows(self) -> list[int]:
        return [
            row
            for row in range(self.results_table.rowCount())
            if not self.results_table.isRowHidden(row)
        ]

    def _update_result_position_label(self) -> None:
        total = self.results_table.rowCount()
        visible_rows = self._visible_result_rows()
        visible_count = len(visible_rows)
        current_row = self.results_table.currentRow()
        if total == 0:
            self.table_position_label.setText("عدد الأصناف: 0")
        elif visible_count == 0:
            self.table_position_label.setText(f"لا توجد نتائج مطابقة — إجمالي الدفعة: {total}")
        elif current_row in visible_rows:
            visible_position = visible_rows.index(current_row) + 1
            if visible_count == total:
                self.table_position_label.setText(f"الصنف {visible_position} من {total}")
            else:
                self.table_position_label.setText(
                    f"النتيجة {visible_position} من {visible_count} — عرض {visible_count} من {total}"
                )
        elif visible_count == total:
            self.table_position_label.setText(f"عدد الأصناف: {total}")
        else:
            self.table_position_label.setText(f"عرض {visible_count} من إجمالي {total}")

    def _apply_result_filters(self, *_args: object) -> None:
        query_tokens = _normalize_search_text(self.result_search_edit.text()).split()
        status_filter = str(self.result_status_filter.currentData() or "all")
        current_row = self.results_table.currentRow()

        self.results_table.blockSignals(True)
        try:
            for row in range(self.results_table.rowCount()):
                source_cell = self.results_table.item(row, 0)
                source_name = str(source_cell.data(Qt.UserRole) or "") if source_cell is not None else ""
                item = self._result_items_by_name.get(source_name)
                if item is None:
                    self.results_table.setRowHidden(row, True)
                    continue
                if status_filter == "action":
                    status_matches = item.status in {"review", "error"}
                else:
                    status_matches = status_filter == "all" or item.status == status_filter
                searchable = _normalize_search_text(
                    " ".join(
                        (
                            item.source_name,
                            item.item_code,
                            item.product_name,
                            item.barcode,
                            STATUS_TEXT.get(item.status, item.status),
                            item.explanation,
                        )
                    )
                )
                text_matches = all(token in searchable for token in query_tokens)
                self.results_table.setRowHidden(row, not (status_matches and text_matches))

            visible_rows = self._visible_result_rows()
            if current_row not in visible_rows:
                selection = self.results_table.selectionModel()
                selection.clearSelection()
                selection.clearCurrentIndex()
                if visible_rows:
                    target = visible_rows[0]
                    index = self.results_table.model().index(target, 0)
                    selection.setCurrentIndex(index, QItemSelectionModel.NoUpdate)
                    selection.select(index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
                    self.results_table.scrollTo(index)
        finally:
            self.results_table.blockSignals(False)

        has_visible = bool(self._visible_result_rows())
        self.first_item_button.setEnabled(has_visible)
        self.last_item_button.setEnabled(has_visible)
        self.clear_result_filter_button.setEnabled(bool(query_tokens) or status_filter != "all")
        self._update_result_position_label()
        self._show_selected_preview()

    def _clear_result_filters(self) -> None:
        self.result_search_edit.blockSignals(True)
        self.result_status_filter.blockSignals(True)
        try:
            self.result_search_edit.clear()
            self.result_status_filter.setCurrentIndex(0)
        finally:
            self.result_search_edit.blockSignals(False)
            self.result_status_filter.blockSignals(False)
        self._apply_result_filters()

    def _capture_results_position(self) -> tuple[str, int, int] | None:
        """Capture the selected source, row, and exact table scroll position."""
        row = self.results_table.currentRow()
        if row < 0:
            return None
        source_cell = self.results_table.item(row, 0)
        source_name = ""
        if source_cell is not None:
            source_name = str(source_cell.data(Qt.UserRole) or "")
        return source_name, row, self.results_table.verticalScrollBar().value()

    def _restore_results_position(self, position: tuple[str, int, int]) -> None:
        """Restore selection without jumping the user back to the first item."""
        source_name, fallback_row, scroll_value = position
        count = self.results_table.rowCount()
        if not count:
            return

        target_row = -1
        if source_name:
            for row in range(count):
                source_cell = self.results_table.item(row, 0)
                if source_cell is not None and source_cell.data(Qt.UserRole) == source_name:
                    target_row = row
                    break
        if target_row < 0:
            target_row = max(0, min(fallback_row, count - 1))
        visible_rows = self._visible_result_rows()
        if target_row not in visible_rows:
            if not visible_rows:
                self._update_result_position_label()
                return
            target_row = min(visible_rows, key=lambda row: abs(row - fallback_row))

        index = self.results_table.model().index(target_row, 0)
        selection = self.results_table.selectionModel()
        selection.setCurrentIndex(index, QItemSelectionModel.NoUpdate)
        selection.select(index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)

        scroll_bar = self.results_table.verticalScrollBar()
        scroll_bar.setValue(max(scroll_bar.minimum(), min(scroll_value, scroll_bar.maximum())))
        self._update_result_position_label()
        self._show_selected_preview()

    def _restore_results_position_if_still_selected(
        self,
        position: tuple[str, int, int],
    ) -> None:
        """Restore the delayed scroll range only if the user has not selected another row."""
        current = self._capture_results_position()
        if current is None or current[:2] != position[:2]:
            return
        self._restore_results_position(position)

    def _result_thumbnail_icon(self, item: BatchItemResult) -> QIcon:
        """Load a small source thumbnail without decoding the full camera image each time."""
        path = self._result_path(item.source_path)
        if path is None or not path.is_file():
            return QIcon()
        try:
            stat = path.stat()
            cache_key = f"{path}:{stat.st_mtime_ns}:{stat.st_size}"
        except OSError:
            return QIcon()
        cached = self._result_thumbnail_cache.get(cache_key)
        if cached is not None:
            return cached
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        source_size = reader.size()
        if source_size.isValid():
            reader.setScaledSize(source_size.scaled(QSize(58, 58), Qt.KeepAspectRatio))
        image = reader.read()
        if image.isNull():
            return QIcon()
        pixmap = QPixmap.fromImage(image)
        if pixmap.width() > 58 or pixmap.height() > 58:
            pixmap = pixmap.scaled(58, 58, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        icon = QIcon(pixmap)
        if len(self._result_thumbnail_cache) >= 320:
            self._result_thumbnail_cache.pop(next(iter(self._result_thumbnail_cache)), None)
        self._result_thumbnail_cache[cache_key] = icon
        return icon

    def _populate_results(self, restore_position: tuple[str, int, int] | None = None) -> None:
        self.results_table.setRowCount(0)
        self.table_position_label.setText("عدد الأصناف: 0")
        self.first_item_button.setEnabled(False)
        self.last_item_button.setEnabled(False)
        self._result_items_by_name = {}
        if self.current_result is None:
            self._update_summary(None)
            return

        result_items = self.current_result.items
        self._result_items_by_name = {item.source_name: item for item in result_items}
        sorting_enabled = self.results_table.isSortingEnabled()
        self.results_table.setSortingEnabled(False)
        self.results_table.blockSignals(True)
        self.results_table.setUpdatesEnabled(False)
        self.results_table.setRowCount(len(result_items))
        try:
            for row, result_item in enumerate(result_items):
                status_text = STATUS_TEXT.get(result_item.status, result_item.status)
                item_code = result_item.item_code or "غير مرتبط"
                barcode = result_item.barcode or "لا يوجد باركود"
                product_name = result_item.product_name or "صنف غير محدد"
                confidence = f"{result_item.confidence:.0%}" if result_item.confidence else "—"
                tooltip = (
                    f"الصورة: {result_item.source_name}\n"
                    f"اسم الصنف: {product_name}\n"
                    f"رقم الصنف: {item_code}\nالباركود: {barcode}\n"
                    f"الثقة: {confidence}\n{result_item.explanation or ''}"
                ).strip()

                status_cell = QTableWidgetItem(status_text)
                status_cell.setIcon(self._result_thumbnail_icon(result_item))
                status_cell.setData(Qt.UserRole, result_item.source_name)
                status_cell.setTextAlignment(Qt.AlignCenter)
                status_cell.setToolTip(tooltip)
                color = STATUS_COLORS.get(result_item.status)
                if color:
                    status_color = QColor(*color)
                    status_cell.setForeground(status_color)
                    status_background = QColor(*color)
                    status_background.setAlpha(24)
                    status_cell.setBackground(status_background)
                    status_font = status_cell.font()
                    status_font.setBold(True)
                    status_cell.setFont(status_font)

                identity_cell = QTableWidgetItem(f"{item_code}\n{barcode}")
                identity_cell.setTextAlignment(Qt.AlignCenter)
                identity_cell.setToolTip(tooltip)
                identity_font = identity_cell.font()
                identity_font.setBold(True)
                identity_cell.setFont(identity_font)

                name_cell = QTableWidgetItem(product_name)
                name_cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                name_cell.setToolTip(tooltip)
                name_font = name_cell.font()
                name_font.setBold(True)
                name_cell.setFont(name_font)

                self.results_table.setItem(row, 0, status_cell)
                self.results_table.setItem(row, 1, identity_cell)
                self.results_table.setItem(row, 2, name_cell)
        finally:
            self.results_table.blockSignals(False)
            self.results_table.setUpdatesEnabled(True)
            self.results_table.setSortingEnabled(sorting_enabled)
            self.results_table.viewport().update()
        self.results_table.resizeRowsToContents()
        for row in range(self.results_table.rowCount()):
            self.results_table.setRowHeight(row, max(70, min(104, self.results_table.rowHeight(row))))
        QTimer.singleShot(0, self.results_table.resizeRowsToContents)
        self._update_summary(self.current_result)
        result_count = self.results_table.rowCount()
        self._apply_result_filters()
        if result_count and self._visible_result_rows():
            if restore_position is None:
                self._select_first_result()
            else:
                self._restore_results_position(restore_position)
                QTimer.singleShot(
                    0,
                    lambda position=restore_position: self._restore_results_position_if_still_selected(position),
                )

    def _select_first_result(self) -> None:
        visible_rows = self._visible_result_rows()
        if not visible_rows:
            return
        row = visible_rows[0]
        index = self.results_table.model().index(row, 0)
        selection = self.results_table.selectionModel()
        selection.setCurrentIndex(index, QItemSelectionModel.NoUpdate)
        selection.select(index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        self.results_table.scrollTo(index, QTableWidget.PositionAtTop)
        self._update_result_position_label()
        self._show_selected_preview()

    def _select_last_result(self) -> None:
        visible_rows = self._visible_result_rows()
        if not visible_rows:
            return
        row = visible_rows[-1]
        index = self.results_table.model().index(row, 0)
        selection = self.results_table.selectionModel()
        selection.setCurrentIndex(index, QItemSelectionModel.NoUpdate)
        selection.select(index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        self.results_table.scrollTo(index, QTableWidget.PositionAtBottom)
        self._update_result_position_label()
        self._show_selected_preview()

    def _update_summary(self, result: BatchRunResult | None) -> None:
        summary = result.summary if result else {"total": 0, "matched": 0, "review": 0, "errors": 0}
        self.total_card.value.setText(str(summary["total"]))
        self.matched_card.value.setText(str(summary["matched"]))
        self.review_card.value.setText(str(summary["review"]))
        self.error_card.value.setText(str(summary["errors"]))

    def _selected_result_item(self):  # type: ignore[no-untyped-def]
        if self.current_result is None:
            return None
        row = self.results_table.currentRow()
        if row < 0:
            return None
        source_cell = self.results_table.item(row, 0)
        if source_cell is None:
            return None
        source_name = str(source_cell.data(Qt.UserRole) or "")
        return self._result_items_by_name.get(source_name)

    def _selected_result_items(self) -> list[BatchItemResult]:
        if self.current_result is None:
            return []
        selection = self.results_table.selectionModel()
        rows = sorted({index.row() for index in selection.selectedRows(0)})
        if not rows and self.results_table.currentRow() >= 0:
            rows = [self.results_table.currentRow()]
        selected: list[BatchItemResult] = []
        for row in rows:
            source_cell = self.results_table.item(row, 0)
            if source_cell is None:
                continue
            source_name = str(source_cell.data(Qt.UserRole) or "")
            item = self._result_items_by_name.get(source_name)
            if item is not None:
                selected.append(item)
        return selected

    def _selected_link_targets(self) -> list[BatchItemResult]:
        """Return every selected row so a wrong automatic/manual link remains editable."""
        return self._selected_result_items()

    def _selected_unresolved_link_targets(self) -> list[BatchItemResult]:
        """Keep reference-based group linking conservative: unresolved rows only."""
        return [item for item in self._selected_result_items() if item.status in {"review", "error"}]

    @staticmethod
    def _is_high_confidence_reference(item: BatchItemResult | None) -> bool:
        if item is None or not item.item_code:
            return False
        if item.status == "manual":
            return True
        return item.status == "matched" and float(item.confidence or 0.0) >= 0.98

    def _manual_reference_item(self) -> BatchItemResult | None:
        item = self._result_items_by_name.get(self._manual_reference_source_name)
        if not self._is_high_confidence_reference(item):
            self._manual_reference_source_name = ""
            return None
        return item

    def _row_for_source_name(self, source_name: str) -> int:
        for row in range(self.results_table.rowCount()):
            source_cell = self.results_table.item(row, 0)
            if source_cell is not None and str(source_cell.data(Qt.UserRole) or "") == source_name:
                return row
        return -1

    def _image_signature(self, item: BatchItemResult) -> tuple[float, ...]:
        """Small centre-focused visual signature used only to propose, never to auto-link."""
        path = self._result_path(item.source_path)
        if path is None or not path.is_file():
            return ()
        cache_key = f"{path}:{path.stat().st_mtime_ns}:{path.stat().st_size}"
        cached = self._visual_signature_cache.get(cache_key)
        if cached is not None:
            return cached
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return ()
        image = pixmap.toImage().scaled(36, 36, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        values: list[float] = []
        # ستة عشر موضعاً في مركز الصورة تقلل أثر الخلفية والحواف الخارجية.
        for y in (8, 14, 20, 26):
            for x in (8, 14, 20, 26):
                color = image.pixelColor(x, y)
                values.extend((float(color.red()), float(color.green()), float(color.blue())))
        signature = tuple(values)
        self._visual_signature_cache[cache_key] = signature
        return signature

    def _visual_similarity(self, left: BatchItemResult, right: BatchItemResult) -> float:
        first = self._image_signature(left)
        second = self._image_signature(right)
        if not first or len(first) != len(second):
            return 0.0
        mean_error = sum(abs(a - b) for a, b in zip(first, second)) / len(first)
        return max(0.0, 1.0 - mean_error / 255.0)

    @staticmethod
    def _filename_family(source_name: str) -> str:
        tokens = _normalize_search_text(Path(source_name).stem).split()
        suffixes = {
            "front",
            "back",
            "side",
            "rear",
            "left",
            "right",
            "top",
            "bottom",
            "barcode",
            "label",
            "واجهه",
            "امام",
            "خلف",
            "جانب",
            "يمين",
            "يسار",
            "اعلي",
            "اسفل",
            "باركود",
            "ملصق",
        }
        while tokens:
            tail = tokens[-1]
            if tail in suffixes or (tail.isdigit() and len(tail) <= 3):
                tokens.pop()
                continue
            break
        return " ".join(tokens)

    def _use_selected_reference(self) -> None:
        item = self._selected_result_item()
        if not self._is_high_confidence_reference(item):
            QMessageBox.information(
                self,
                APP_NAME,
                "لا يمكن اعتماد هذا الصف مرجعًا. اختر صورة باركود مطابقة بثقة 98% فأعلى، أو صورة سبق ربطها يدويًا.",
            )
            return
        self._manual_reference_source_name = item.source_name
        self._update_manual_selection_context()
        self.status_label.setText(
            f"تم اعتماد الصنف {item.item_code} مرجعًا. حدّد صور الواجهة والجانب غير المؤكدة ثم اربط المحدد."
        )
        self._update_controls()

    def _suggest_high_confidence_group(self) -> None:
        reference = self._manual_reference_item()
        if reference is None:
            current = self._selected_result_item()
            if self._is_high_confidence_reference(current):
                self._manual_reference_source_name = current.source_name
                reference = current
        if reference is None:
            QMessageBox.information(self, APP_NAME, "اعتمد أولًا صف صورة الباركود المطابقة كمرجع.")
            return
        anchor_row = self._row_for_source_name(reference.source_name)
        if anchor_row < 0:
            return
        all_items = self.current_result.items if self.current_result is not None else []
        competing = [
            item for item in all_items
            if item.source_name != reference.source_name and self._is_high_confidence_reference(item)
        ]
        family = self._filename_family(reference.source_name)
        proposed: list[tuple[float, int, BatchItemResult]] = []
        for row in range(max(0, anchor_row - 2), min(self.results_table.rowCount(), anchor_row + 3)):
            if row == anchor_row:
                continue
            cell = self.results_table.item(row, 0)
            if cell is None:
                continue
            candidate = self._result_items_by_name.get(str(cell.data(Qt.UserRole) or ""))
            if candidate is None or candidate.status not in {"review", "error"}:
                continue
            similarity = self._visual_similarity(reference, candidate)
            same_family = bool(family and family == self._filename_family(candidate.source_name))
            required = 0.88 if same_family else 0.92
            if similarity < required:
                continue
            nearest_competitor = max(
                (self._visual_similarity(other, candidate) for other in competing),
                default=0.0,
            )
            if nearest_competitor and similarity < nearest_competitor + 0.06:
                continue
            proposed.append((similarity + (0.04 if same_family else 0.0), row, candidate))
        proposed.sort(reverse=True, key=lambda entry: entry[0])
        proposed = proposed[:2]
        if not proposed:
            self.status_label.setText(
                "لم يصل اقتراح الصور إلى حد الثقة العالي؛ استخدم Ctrl أو Shift لتحديدها يدويًا، ثم اربطها بالمرجع."
            )
            QMessageBox.information(
                self,
                APP_NAME,
                "لم يُحدَّد شيء تلقائيًا لأن الثقة غير كافية. بقي الربط اليدوي الجماعي متاحًا وآمنًا.",
            )
            return
        selection = self.results_table.selectionModel()
        anchor_index = self.results_table.model().index(anchor_row, 0)
        selection.select(anchor_index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        for _score, row, _candidate in proposed:
            index = self.results_table.model().index(row, 0)
            selection.select(index, QItemSelectionModel.Select | QItemSelectionModel.Rows)
        selection.setCurrentIndex(anchor_index, QItemSelectionModel.NoUpdate)
        self._update_manual_selection_context()
        self.status_label.setText(
            f"اقتراح محافظ: {len(proposed)} صورة. راجع التحديد ثم اضغط ربط الصور المحددة بصنف المرجع."
        )
        self._update_controls()

    def _update_manual_selection_context(self) -> None:
        reference = self._manual_reference_item()
        selected_count = len(self._selected_link_targets())
        unresolved_count = len(self._selected_unresolved_link_targets())
        if hasattr(self, "selected_count_badge"):
            self.selected_count_badge.setText(f"المحدد: {selected_count}")
        if reference is None:
            self.manual_selection_label.setText(
                f"المحدد: {selected_count} — أدخل اسم الصنف أو رقمه أو الباركود للربط المباشر."
            )
            if hasattr(self, "manual_reference_badge"):
                self.manual_reference_badge.setText("لا يوجد مرجع")
                self.manual_reference_badge.setToolTip("اعتمد صفًا موثوقًا لتسريع ربط الصور القريبة")
            return
        reference_name = reference.product_name or reference.source_name
        self.manual_selection_label.setText(
            f"المرجع: {reference.item_code} — {reference_name} | "
            f"المحدد: {selected_count} | الجاهز للربط: {unresolved_count}"
        )
        if hasattr(self, "manual_reference_badge"):
            self.manual_reference_badge.setText(f"المرجع: {reference.item_code}")
            self.manual_reference_badge.setToolTip(reference_name)

    def _result_path(self, value: str) -> Path | None:
        if not value:
            return None
        candidate = Path(value).expanduser()
        if not candidate.is_absolute() and self.current_workspace is not None:
            candidate = self.current_workspace / candidate
        return candidate

    def _show_selected_preview(self) -> None:
        current = self._selected_result_item()
        current_name = current.source_name if current is not None else ""
        if current_name != self._individual_edit_source_name:
            self._individual_edit_source_name = current_name
            self._individual_crop_box = None
            self._individual_preview_active = False
            if self.individual_manual_crop_button.isChecked():
                self.individual_manual_crop_button.setChecked(False)
            self.output_preview.viewer.clear_crop()
            self.output_preview.viewer.set_crop_mode(False)

        count = self.results_table.rowCount()
        self._update_result_position_label()

        self._update_manual_selection_context()
        self._update_controls()
        # عند الدفعات الكبيرة ننتظر توقف التمرير 90 مللي ثانية، فلا نفك ترميز
        # صورتين عاليتي الدقة لكل صف يمر عليه المؤشر. الدفعات الصغيرة تبقى فورية.
        if count >= 100:
            self._preview_timer.start()
            return
        self._preview_timer.stop()
        self._render_selected_preview()

    def _render_selected_preview(self) -> None:
        item = self._selected_result_item()
        if item is None:
            visible_rows = self._visible_result_rows()
            if visible_rows:
                source_cell = self.results_table.item(visible_rows[0], 0)
                source_name = str(source_cell.data(Qt.UserRole) or "") if source_cell is not None else ""
                item = self._result_items_by_name.get(source_name)
        if item is None:
            self._set_preview(self.source_preview, None)
            self._set_preview(self.output_preview, None)
            self.selected_product_label.setText("اختر صورة من القائمة لعرض اسم الصنف كاملًا")
            self.selected_status_badge.setText("بانتظار الاختيار")
            self.selected_status_badge.setStyleSheet("")
            self.selected_item_code_label.setText("—")
            self.selected_barcode_label.setText("—")
            self.selected_file_label.setText("—")
            self.manual_context_label.setText("حدد صورة ثم اربطها مباشرة من الأدوات الظاهرة أدناه.")
            self._update_controls()
            return
        source = self._result_path(item.source_path)
        target = self._result_path(item.output_path or item.review_path)
        if target is None:
            target = source
        self._set_preview(self.source_preview, source)
        self._set_preview(self.output_preview, target)
        barcode = item.barcode or "لم يُقرأ آليًا — افحص الأصل بالتكبير"
        item_code = item.item_code or "غير مرتبط"
        status_text = STATUS_TEXT.get(item.status, item.status)
        product_name = item.product_name or item.source_name
        self.selected_product_label.setText(product_name)
        self.selected_product_label.setToolTip(product_name)
        self.selected_status_badge.setText(status_text)
        status_rgb = STATUS_COLORS.get(item.status, (71, 85, 105))
        status_color = QColor(*status_rgb).name()
        status_background = QColor(*status_rgb)
        status_background.setAlpha(28)
        self.selected_status_badge.setStyleSheet(
            f"color: {status_color}; background: {status_background.name(QColor.HexArgb)}; "
            f"border: 1px solid {status_color}; border-radius: 11px; padding: 4px 9px; font-weight: 900;"
        )
        self.selected_item_code_label.setText(item_code)
        self.selected_item_code_label.setToolTip(item_code)
        self.selected_barcode_label.setText(barcode)
        self.selected_barcode_label.setToolTip(barcode)
        self.selected_file_label.setText(item.source_name)
        self.selected_file_label.setToolTip(item.source_name)
        self.manual_context_label.setText(f"{status_text} • الصنف {item_code} • {barcode}")
        self.manual_context_label.setToolTip(product_name)
        self._update_controls()

    def _set_preview(self, preview: ImagePreviewPane, path: Path | None) -> None:
        preview.set_image(path)

    def _confirm_link_scope(
        self,
        targets: Iterable[BatchItemResult],
        lookup_value: str,
        *,
        reference_product: str = "",
    ) -> bool:
        target_list = list(targets)
        shown_names = "\n".join(f"• {item.source_name}" for item in target_list[:6])
        remaining = len(target_list) - 6
        if remaining > 0:
            shown_names += f"\n• و{remaining} صورة أخرى"
        product_line = f"\nالمنتج المرجعي: {reference_product}" if reference_product else ""
        answer = QMessageBox.question(
            self,
            APP_NAME,
            f"سيُطبّق الصنف/المرجع {lookup_value} على {len(target_list)} صورة محددة.{product_line}\n\n"
            f"نطاق العملية:\n{shown_names}\n\n"
            "ستُحفظ كل زاوية كملف مستقل، وستُحدّث التقارير وحزمة ZIP. هل تريد المتابعة؟",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return answer == QMessageBox.Yes

    def _start_manual_link(self) -> None:
        targets = self._selected_link_targets()
        if not targets:
            QMessageBox.warning(
                self,
                APP_NAME,
                "حدد صفًا واحدًا أو عدة صفوف من الجدول. يمكن تعديل الصف المطابق آليًا أو المرتبط يدويًا أو غير المؤكد.",
            )
            return
        reference = self.manual_item_edit.text().strip()
        if not reference:
            QMessageBox.warning(self, APP_NAME, "اكتب رقم الصنف أو رقم الباركود الموجود في ملف Excel.")
            return
        if len(targets) > 1 and not self._confirm_link_scope(targets, reference):
            self.status_label.setText("أُلغي الربط الجماعي؛ لم تتغير النتائج.")
            return
        self._begin_manual_links(
            targets,
            reference,
            f"جارٍ البحث عن {reference} في Excel وربط {len(targets)} صورة برقم الصنف النهائي...",
        )

    def _start_reference_group_link(self) -> None:
        reference = self._manual_reference_item()
        if reference is None:
            QMessageBox.warning(
                self,
                APP_NAME,
                "اعتمد أولًا صف صورة باركود مطابقة بثقة 98% فأعلى أو صفًا مرتبطًا يدويًا.",
            )
            return
        targets = self._selected_unresolved_link_targets()
        if not targets:
            QMessageBox.warning(
                self,
                APP_NAME,
                "حدد صور الواجهة أو الجانب غير المؤكدة باستخدام Ctrl أو Shift. صورة المرجع والصفوف المؤكدة لن تُعاد معالجتها.",
            )
            return
        if not self._confirm_link_scope(
            targets,
            reference.item_code,
            reference_product=reference.product_name or reference.source_name,
        ):
            self.status_label.setText("أُلغي ربط المجموعة بصنف المرجع؛ لم تتغير النتائج.")
            return
        self._begin_manual_links(
            targets,
            reference.item_code,
            f"جارٍ ربط {len(targets)} صورة بالصنف {reference.item_code} من المرجع المعتمد...",
        )

    def _begin_manual_links(
        self,
        targets: Iterable[BatchItemResult],
        lookup_value: str,
        status_text: str,
    ) -> None:
        if self.current_workspace is None:
            return
        source_names = tuple(dict.fromkeys(item.source_name for item in targets))
        if not source_names:
            return
        # ثبّت مكان المستخدم فور ضغط الحفظ؛ قد يتغير التحديد أثناء عمل
        # المعالجة الخلفية، لكن العودة يجب أن تكون إلى الصف والتمرير الأصليين.
        self._pending_manual_position = self._capture_results_position()
        self._pending_manual_source_names = source_names
        # الربط قد يتضمن عزلًا وتحسينًا وكتابة ZIP؛ لا نحجب الجدول أو التنقل
        # أثناء ذلك. تُعطل أوامر الربط وحدها لمنع عمليتين متزامنتين.
        self.manual_item_edit.setEnabled(False)
        self.manual_link_button.setEnabled(False)
        self.manual_link_button.setText("يُربط بالخلفية…")
        self.reference_group_link_button.setEnabled(False)
        self.status_label.setText("تم استلام الربط فورًا؛ الحفظ مستمر بالخلفية ويمكنك متابعة المراجعة.")
        self.manual_worker = ManualLinkWorker(
            self.current_workspace,
            source_names,
            lookup_value,
            self.remove_background_check.isChecked(),
            self.enhance_product_check.isChecked(),
            self._final_image_options(),
        )
        self.manual_worker.completed.connect(self._on_manual_completed)
        self.manual_worker.failed.connect(self._on_manual_failed)
        self.manual_worker.start()

    def _on_manual_completed(self, result: BatchRunResult) -> None:
        # احفظ مكان المستخدم قبل إعادة بناء الجدول؛ الربط اليدوي يغيّر بيانات
        # الصف نفسه، لكنه يجب ألا يعيده إلى أول صنف أو يغيّر موضع التمرير.
        restore_position = self._pending_manual_position or self._capture_results_position()
        self._pending_manual_position = None
        source_names = self._pending_manual_source_names
        if not source_names and self.manual_worker is not None:
            source_names = tuple(getattr(self.manual_worker, "source_names", ()))
            if not source_names:
                source_name = str(getattr(self.manual_worker, "source_name", "") or "")
                source_names = (source_name,) if source_name else ()
        self._pending_manual_source_names = ()
        linked_items = [item for item in result.items if item.source_name in set(source_names)]
        resolved_codes = sorted({item.item_code for item in linked_items if item.item_code})
        resolved_code = resolved_codes[0] if len(resolved_codes) == 1 else ""
        if linked_items:
            self._manual_reference_source_name = linked_items[0].source_name
        self.current_result = result
        self.manual_item_edit.clear()
        self._populate_results(restore_position=restore_position)
        self.manual_link_button.setText("ربط الآن")
        self._set_busy(False)
        self._update_manual_selection_context()
        self._update_controls()
        count = len(linked_items) or len(source_names)
        if count == 1 and resolved_code:
            message = f"تم تعديل/ربط الصورة. رقم الصنف النهائي: {resolved_code}"
        elif resolved_code:
            message = f"تم تعديل/ربط {count} صور دفعة واحدة. رقم الصنف النهائي: {resolved_code}"
        else:
            message = f"تم تعديل/ربط {count} صور وتحديث أرقام الأصناف النهائية."
        self.status_label.setText(f"{message} تم تحديث التقارير وحزمة ZIP في الخلفية.")

    def _open_results_folder(self) -> None:
        if self.current_workspace and self.current_workspace.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.current_workspace)))

    def _open_selected_file(self) -> None:
        item = self._selected_result_item()
        if item is None:
            return
        path_text = item.output_path or item.review_path or item.source_path
        path = Path(path_text)
        if path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _save_delivery_zip(self) -> None:
        if self.current_result is None:
            return
        source = Path(self.current_result.delivery_zip)
        if not source.is_file():
            QMessageBox.warning(self, APP_NAME, "حزمة النتائج غير موجودة.")
            return
        default_name = f"SmartCatalogVision-Results-{datetime.now().strftime('%Y%m%d-%H%M')}.zip"
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "حفظ حزمة النتائج",
            str(Path.home() / "Desktop" / default_name),
            "ملفات ZIP (*.zip)",
        )
        if not filename:
            return
        destination = Path(filename)
        if destination.suffix.casefold() != ".zip":
            destination = destination.with_suffix(".zip")
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, destination)
        except OSError:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            self.status_label.setText("تعذر حفظ حزمة ZIP — لم يتغير الملف السابق.")
            QMessageBox.warning(
                self,
                APP_NAME,
                "تعذر حفظ الحزمة في الموقع المحدد.\n\n"
                "لم يتغير الملف السابق. تأكد من توفر المساحة وصلاحية الكتابة، "
                "أو اختر مجلدًا آخر ثم حاول مجددًا.",
            )
            return
        self.status_label.setText(f"تم حفظ الحزمة: {destination}")
        QMessageBox.information(self, APP_NAME, f"تم حفظ حزمة النتائج بنجاح:\n{destination}")

    def _set_busy(self, busy: bool) -> None:
        selected = self._selected_result_item()
        self.run_button.setEnabled(not busy and self.catalog_path is not None and bool(self.image_paths))
        self.image_list.setEnabled(not busy)
        self.enhance_product_check.setEnabled(not busy)
        self.remove_background_check.setEnabled(not busy)
        self.framing_combo.setEnabled(not busy)
        self.webp_quality_combo.setEnabled(not busy)
        self._update_enhancement_controls()
        visible_results = bool(self._visible_result_rows())
        filters_active = bool(self.result_search_edit.text().strip()) or self.result_status_filter.currentData() != "all"
        self.result_search_edit.setEnabled(not busy)
        self.result_status_filter.setEnabled(not busy)
        self.clear_result_filter_button.setEnabled(not busy and filters_active)
        self.first_item_button.setEnabled(not busy and visible_results)
        self.last_item_button.setEnabled(not busy and visible_results)
        self.manual_item_edit.setEnabled(not busy)
        self.manual_link_button.setEnabled(not busy and self._selected_can_link())
        self.use_reference_button.setEnabled(not busy and self._is_high_confidence_reference(self._selected_result_item()))
        self.suggest_group_button.setEnabled(
            not busy and (self._manual_reference_item() is not None or self._is_high_confidence_reference(self._selected_result_item()))
        )
        self.reference_group_link_button.setEnabled(
            not busy and self._manual_reference_item() is not None and self._selected_can_group_link()
        )
        can_edit_one = self._individual_editable_item() is not None
        self.individual_editor_panel.setEnabled(not busy and can_edit_one)
        self.individual_preview_button.setEnabled(not busy and can_edit_one)
        self.individual_apply_button.setEnabled(not busy and can_edit_one)
        self.individual_cancel_button.setEnabled(not busy)
        self.individual_tools_toggle_button.setEnabled(not busy)
        self.edit_image_button.setEnabled(not busy and can_edit_one)
        self.open_selected_file_button.setEnabled(not busy and selected is not None)
        self.open_link_panel_button.setEnabled(not busy and selected is not None)
        self.open_folder_button.setEnabled(not busy and self.current_workspace is not None)
        self.save_zip_button.setEnabled(not busy and self.current_result is not None)

    def _selected_can_link(self) -> bool:
        return bool(self._selected_link_targets())

    def _selected_can_group_link(self) -> bool:
        return bool(self._selected_unresolved_link_targets())

    def _update_controls(self) -> None:
        busy = bool(
            (self.batch_worker and self.batch_worker.isRunning())
            or (self.manual_worker and self.manual_worker.isRunning())
            or (self.individual_worker and self.individual_worker.isRunning())
        )
        selected = self._selected_result_item()
        reference = self._manual_reference_item()
        can_link = self._selected_can_link()
        self.run_button.setEnabled(not busy and self.catalog_path is not None and bool(self.image_paths))
        visible_results = bool(self._visible_result_rows())
        filters_active = bool(self.result_search_edit.text().strip()) or self.result_status_filter.currentData() != "all"
        self.result_search_edit.setEnabled(not busy)
        self.result_status_filter.setEnabled(not busy)
        self.clear_result_filter_button.setEnabled(not busy and filters_active)
        self.first_item_button.setEnabled(not busy and visible_results)
        self.last_item_button.setEnabled(not busy and visible_results)
        self.manual_link_button.setEnabled(not busy and can_link)
        self.use_reference_button.setEnabled(not busy and self._is_high_confidence_reference(selected))
        self.suggest_group_button.setEnabled(
            not busy and (reference is not None or self._is_high_confidence_reference(selected))
        )
        self.reference_group_link_button.setEnabled(
            not busy and reference is not None and self._selected_can_group_link()
        )
        can_edit_one = self._individual_editable_item() is not None
        self.individual_editor_panel.setEnabled(not busy and can_edit_one)
        self.individual_preview_button.setEnabled(not busy and can_edit_one)
        self.individual_apply_button.setEnabled(not busy and can_edit_one)
        self.individual_cancel_button.setEnabled(not busy)
        self.individual_tools_toggle_button.setEnabled(not busy)
        self.edit_image_button.setEnabled(not busy and can_edit_one)
        self.open_selected_file_button.setEnabled(not busy and selected is not None)
        self.open_link_panel_button.setEnabled(not busy and selected is not None)
        self.open_folder_button.setEnabled(not busy and self.current_workspace is not None)
        self.save_zip_button.setEnabled(not busy and self.current_result is not None)

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        interactive_close = bool(event.spontaneous())
        if (
            interactive_close
            and hasattr(self, "individual_editor_dialog")
            and self.individual_editor_dialog.isVisible()
            and (self._individual_editor_dirty or self._individual_preview_active)
        ):
            event.ignore()
            self._request_close_individual_editor()
            return
        worker_running = bool(
            (self.batch_worker and self.batch_worker.isRunning())
            or (self.manual_worker and self.manual_worker.isRunning())
            or (self.individual_worker and self.individual_worker.isRunning())
        )
        if worker_running:
            answer = QMessageBox.question(
                self,
                APP_NAME,
                "المعالجة ما زالت مستمرة. هل تريد إغلاق البرنامج؟",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        if interactive_close and not self._confirm_leave_results("إغلاق البرنامج"):
            event.ignore()
            return
        event.accept()


def _self_test(output_path: Path) -> int:
    """Validate frozen imports, resources, and one real ONNX inference."""
    import numpy as np
    import onnxruntime as ort

    from smart_catalog_vision.final_images import FinalImageProcessor

    processor = FinalImageProcessor()
    model_path = processor.model_dir / "u2netp.onnx"
    icon_path = bundled_asset("app_icon.png")
    inference_ok = False
    inference_shape = ""
    inference_error = ""
    if model_path.is_file():
        try:
            session = ort.InferenceSession(
                str(model_path),
                providers=["CPUExecutionProvider"],
            )
            model_input = session.get_inputs()[0]
            input_shape = [
                int(dimension)
                if isinstance(dimension, int) and dimension > 0
                else (1 if index == 0 else 320)
                for index, dimension in enumerate(model_input.shape)
            ]
            outputs = session.run(
                None,
                {model_input.name: np.zeros(input_shape, dtype=np.float32)},
            )
            inference_ok = bool(outputs and np.asarray(outputs[0]).size)
            if outputs:
                inference_shape = "x".join(str(value) for value in np.asarray(outputs[0]).shape)
        except Exception as error:  # pragma: no cover - reported by the frozen smoke test
            inference_error = f"{type(error).__name__}: {error}"

    checks = {
        "application": APP_NAME,
        "version": APP_VERSION,
        "python": sys.version.split()[0],
        "executable": str(Path(sys.executable).resolve()),
        "frozen": str(bool(getattr(sys, "frozen", False))).lower(),
        "model_path": str(model_path),
        "model_exists": str(model_path.is_file()).lower(),
        "onnx_inference": str(inference_ok).lower(),
        "onnx_output_shape": inference_shape,
        "onnx_error": inference_error,
        "icon_path": str(icon_path),
        "icon_exists": str(icon_path.is_file()).lower(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "\n".join(f"{key}={value}" for key, value in checks.items()) + "\n",
        encoding="utf-8",
    )
    return 0 if model_path.is_file() and icon_path.is_file() and inference_ok else 2


def _batch_self_test(output_path: Path, fixture_dir: Path) -> int:
    """Run real auto-match and manual barcode-to-item acceptance paths."""
    import zipfile

    import cv2
    import numpy as np

    from smart_catalog_vision.imaging import read_image

    workspace = output_path.parent / "installed_batch_job"
    manual_workspace = output_path.parent / "installed_manual_barcode_job"
    for job_path in (workspace, manual_workspace):
        if job_path.exists():
            shutil.rmtree(job_path)

    checks: dict[str, str] = {
        "application": APP_NAME,
        "version": APP_VERSION,
        "fixture_dir": str(fixture_dir),
    }
    try:
        result = run_batch(
            fixture_dir / "catalog.xlsx",
            [fixture_dir / "product_ean13.png"],
            workspace,
            remove_background=True,
            enhance_product=True,
            maximum_barcode_tier=3,
        )
        item = result.items[0]
        final_path = Path(item.output_path)
        delivery_zip = Path(result.delivery_zip)
        final_image = read_image(final_path)
        height, width = final_image.shape[:2]
        image_size = f"{width}x{height}"
        corners_white = all(
            int(final_image[y, x].min()) >= 248
            for x, y in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1))
        )
        with zipfile.ZipFile(delivery_zip) as archive:
            zip_names = set(archive.namelist())

        manual_source = output_path.parent / "manual_barcode_input.png"
        manual_pixels = np.full((360, 420, 3), 255, dtype=np.uint8)
        cv2.rectangle(manual_pixels, (120, 90), (300, 285), (80, 130, 190), -1)
        encoded, buffer = cv2.imencode(".png", manual_pixels)
        if not encoded:
            raise RuntimeError("تعذر إنشاء صورة اختبار البحث بالباركود")
        buffer.tofile(str(manual_source))
        manual_initial = run_batch(
            fixture_dir / "catalog.xlsx",
            [manual_source],
            manual_workspace,
            remove_background=False,
            enhance_product=False,
            maximum_barcode_tier=1,
        )
        manual_result = apply_manual_link(
            manual_initial.workspace,
            manual_initial.items[0].source_name,
            "5901234123457",
            remove_background=False,
            enhance_product=False,
        )
        manual_item = manual_result.items[0]
        manual_output = Path(manual_item.output_path)
        manual_barcode_lookup_passed = all(
            (
                manual_initial.items[0].status == "review",
                manual_item.status == "manual",
                manual_item.barcode == "5901234123457",
                manual_item.item_code == "000123",
                manual_item.match_source == "manual_barcode_lookup",
                manual_output.name == "000123_حبه.webp",
                manual_output.is_file(),
            )
        )

        passed = all(
            (
                result.summary == {"total": 1, "matched": 1, "review": 0, "errors": 0},
                item.status == "matched",
                item.item_code == "000123",
                item.product_name == "منتج اختبار الذكاء",
                item.barcode == "5901234123457",
                item.match_source == "catalog_barcode",
                final_path.name == "000123_حبه.webp",
                final_path.is_file(),
                image_size == "800x700",
                corners_white,
                delivery_zip.is_file(),
                "processed/000123_حبه.webp" in zip_names,
                "reports/processing_report.json" in zip_names,
                "reports/processing_report.csv" in zip_names,
                manual_barcode_lookup_passed,
            )
        )
        checks.update(
            {
                "batch_completed": "true",
                "summary": str(result.summary),
                "status": item.status,
                "item_code": item.item_code,
                "product_name": item.product_name,
                "barcode": item.barcode,
                "match_source": item.match_source,
                "output_name": final_path.name,
                "output_exists": str(final_path.is_file()).lower(),
                "output_size": image_size,
                "corners_white": str(corners_white).lower(),
                "delivery_zip_exists": str(delivery_zip.is_file()).lower(),
                "manual_search_input": "5901234123457",
                "manual_search_output_item_code": manual_item.item_code,
                "manual_search_match_source": manual_item.match_source,
                "manual_search_output_name": manual_output.name,
                "manual_barcode_lookup_passed": str(manual_barcode_lookup_passed).lower(),
                "batch_test_passed": str(passed).lower(),
            }
        )
        exit_code = 0 if passed else 3
    except Exception as exc:
        checks.update(
            {
                "batch_completed": "false",
                "batch_test_passed": "false",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc().replace("\n", " | "),
            }
        )
        exit_code = 4

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "\n".join(f"{key}={value}" for key, value in checks.items()) + "\n",
        encoding="utf-8",
    )
    return exit_code


def _gui_smoke_test(output_path: Path) -> int:
    """Open the real main window under a realistic layout load, capture it, and exit."""
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("Ahmed Al-Faifi")
    icon_path = bundled_asset("app_icon.png")
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    fixture_value = os.environ.get("SMART_CATALOG_GUI_FIXTURE", "").strip()
    fixture_path = Path(fixture_value) if fixture_value else icon_path
    if not fixture_path.is_file():
        fixture_path = icon_path
    window = MainWindow()
    window.resize(1180, 760)

    catalog_name = "ملفات قديمة ليست الشغل النهائي بالتطبيق — الملف النهائي لمنتجات الصيف.xlsx"
    catalog_tooltip = rf"C:\ملفات المنتجات\الأرشيف القديم\{catalog_name}"
    window.catalog_edit.setText(catalog_name)
    window.catalog_edit.setCursorPosition(0)
    window.catalog_edit.setToolTip(f"المسار الكامل:\n{catalog_tooltip}")
    window.catalog_status_label.setText("تم اختيار ملف Excel بنجاح")
    window.catalog_status_label.setToolTip(catalog_tooltip)
    for index in range(1, 83):
        window.image_list.addItem(f"{index:02d} — PHOTO-2026-07-14-19-{index:02d}.jpg")
    window.image_count_label.setText("82 صورة")
    window.show()

    def finish() -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        screenshot_path = output_path.with_suffix(".png")
        enhancement_screenshot_path = output_path.with_name(f"{output_path.stem}_enhancements.png")
        screenshot_saved = window.grab().save(str(screenshot_path), "PNG")

        scroll_bar = window.inputs_scroll.verticalScrollBar()
        scroll_maximum = scroll_bar.maximum()
        scroll_bar.setValue(scroll_maximum)
        app.processEvents()
        enhancement_screenshot_saved = window.grab().save(str(enhancement_screenshot_path), "PNG")
        enhancement_panel_verified = bool(
            scroll_maximum > 0
            and scroll_bar.value() == scroll_maximum
            and window.enhancement_preset_combo.isVisible()
            and window.enhancement_strength_slider.isVisible()
            and window.enhancement_strength_slider.maximum() == 100
            and window.image_list.verticalScrollBar().maximum() > 0
        )

        result_items = [
            BatchItemResult(
                source_path=str(fixture_path),
                source_name=f"PHOTO-{item_index:03d}.jpg",
                status="review",
                item_code=f"{100000 + item_index}",
                product_name=(
                    f"منظف ومعقم متعدد الاستخدامات برائحة الليمون — عبوة اقتصادية رقم {item_index}"
                ),
                barcode=f"6281000{item_index:06d}",
                explanation="حالة غير مؤكدة وتحتاج مراجعة",
                review_path=str(fixture_path),
            )
            for item_index in range(1, 83)
        ]
        window.current_result = BatchRunResult(
            workspace=str(output_path.parent / "gui-results-workspace"),
            database_path="",
            catalog_summary={},
            items=result_items,
            elapsed_ms=0.0,
            delivery_zip="",
            report_json="",
            report_csv="",
        )
        window.current_workspace = Path(window.current_result.workspace)
        window._populate_results()
        window._show_results_page()
        app.processEvents()
        window._select_last_result()
        window._render_selected_preview()
        window.preview_tabs.setCurrentWidget(window.output_preview)
        app.processEvents()
        results_screenshot_path = output_path.with_name(f"{output_path.stem}_last_item.png")
        results_screenshot_saved = window.grab().save(str(results_screenshot_path), "PNG")
        last_item_verified = bool(
            window.results_table.rowCount() == 82
            and window.results_table.currentRow() == 81
            and window.results_table.verticalScrollBar().maximum() > 0
            and window.results_table.verticalScrollBar().value()
            == window.results_table.verticalScrollBar().maximum()
            and window.table_position_label.text() == "الصنف 82 من 82"
            and window.manual_toggle_button.isChecked()
            and window.manual_toggle_button.isHidden()
            and window.manual_group.isVisible()
        )

        window._set_manual_panel_expanded(False)
        window._select_last_result()
        window._render_selected_preview()
        app.processEvents()
        manual_table_scroll = window.results_table.verticalScrollBar()
        manual_screenshot_path = output_path.with_name(f"{output_path.stem}_link_bar.png")
        manual_screenshot_saved = window.grab().save(str(manual_screenshot_path), "PNG")
        manual_controls = [
            window.manual_item_edit,
            window.manual_link_button,
            window.use_reference_button,
            window.suggest_group_button,
            window.reference_group_link_button,
            window.jump_to_previews_button,
            window.manual_reference_badge,
        ]
        manual_rects = [
            QRect(control.mapTo(window.manual_group, QPoint(0, 0)), control.size())
            for control in manual_controls
        ]
        manual_controls_accessible = all(
            window.manual_group.rect().contains(control_rect)
            for control_rect in manual_rects
        )
        manual_controls_separated = all(
            not first.intersects(second)
            for index, first in enumerate(manual_rects)
            for second in manual_rects[index + 1 :]
        )
        preview_verified = bool(
            not window.output_preview.viewer._pixmap.isNull()
            and not window.source_preview.viewer._pixmap.isNull()
            and window.output_preview.viewer.minimumHeight() >= 260
            and window.selected_item_code_label.text() == "100082"
            and window.selected_barcode_label.text() == "6281000000082"
            and window.selected_file_label.text() == "PHOTO-082.jpg"
        )
        manual_panel_verified = bool(
            window.manual_group.isVisible()
            and 110 <= window.manual_group.height() <= 124
            and window.manual_toggle_button.isHidden()
            and window.manual_toggle_button.isChecked()
            and window.results_table.horizontalScrollBar().maximum() == 0
            and manual_controls_accessible
            and window.results_table.currentRow() == 81
            and window.results_table.height() >= window.results_table.minimumHeight()
            and window.manual_link_button.height() >= 36
            and window.use_reference_button.height() >= 30
            and window.suggest_group_button.height() >= 30
            and window.reference_group_link_button.height() >= 30
            and window.manual_item_edit.height() >= 36
            and window.jump_to_previews_button.height() >= 30
            and manual_controls_separated
            and window.table_position_label.text() == "الصنف 82 من 82"
        )

        window.edit_image_button.click()
        app.processEvents()
        editor_dialog = window.individual_editor_dialog
        editor_dialog.showNormal()
        editor_dialog.resize(1180, 760)
        app.processEvents()
        if not window.individual_manual_crop_button.isChecked():
            window.individual_manual_crop_button.click()
        editor_viewer = window.individual_editor_preview.viewer
        editor_viewer.set_crop_box((0.16, 0.10, 0.88, 0.18, 0.82, 0.92, 0.10, 0.84), emit=True)
        app.processEvents()
        editor_screenshot_path = output_path.with_name(f"{output_path.stem}_editor_crop.png")
        editor_screenshot_saved = editor_dialog.grab().save(str(editor_screenshot_path), "PNG")
        editor_crop_box = editor_viewer.crop_box
        editor_dirty_before_close = bool(window._individual_editor_dirty)
        editor_verified = bool(
            editor_dialog.isVisible()
            and window.individual_editor_panel.isVisible()
            and window.individual_editor_panel.maximumWidth() == 400
            and window.individual_editor_preview.minimumWidth() >= 620
            and not editor_viewer._pixmap.isNull()
            and editor_crop_box is not None
            and window.individual_manual_crop_button.isChecked()
            and editor_dirty_before_close
            and window.individual_editor_state_label.property("previewPending") is True
            and window.individual_cancel_button.isVisible()
            and window.individual_preview_button.isVisible()
            and window.individual_apply_button.isVisible()
        )
        if isinstance(editor_dialog, ProtectedEditDialog):
            editor_dialog.discard_and_close()
        else:
            editor_dialog.reject()
        app.processEvents()

        arabic_filename_verified = bool(
            window.catalog_edit.text() == catalog_name
            and "�" not in window.catalog_edit.text()
            and window.image_count_label.text() == "82 صورة"
        )
        gui_test_passed = all(
            (
                screenshot_saved,
                enhancement_screenshot_saved,
                results_screenshot_saved,
                manual_screenshot_saved,
                editor_screenshot_saved,
                enhancement_panel_verified,
                arabic_filename_verified,
                last_item_verified,
                preview_verified,
                manual_panel_verified,
                editor_verified,
            )
        )
        output_path.write_text(
            "\n".join(
                (
                    f"application={APP_NAME}",
                    f"version={APP_VERSION}",
                    "gui_started=true",
                    f"window_visible={str(window.isVisible()).lower()}",
                    f"window_title={window.windowTitle()}",
                    f"screenshot_saved={str(screenshot_saved).lower()}",
                    f"screenshot_path={screenshot_path}",
                    f"enhancement_screenshot_saved={str(enhancement_screenshot_saved).lower()}",
                    f"enhancement_screenshot_path={enhancement_screenshot_path}",
                    f"results_screenshot_saved={str(results_screenshot_saved).lower()}",
                    f"results_screenshot_path={results_screenshot_path}",
                    f"manual_screenshot_saved={str(manual_screenshot_saved).lower()}",
                    f"manual_screenshot_path={manual_screenshot_path}",
                    f"editor_screenshot_saved={str(editor_screenshot_saved).lower()}",
                    f"editor_screenshot_path={editor_screenshot_path}",
                    f"scale_factor={os.environ.get('QT_SCALE_FACTOR', '1.0')}",
                    f"device_pixel_ratio={window.devicePixelRatioF():.2f}",
                    f"input_scroll_maximum={scroll_maximum}",
                    f"enhancement_panel_verified={str(enhancement_panel_verified).lower()}",
                    f"arabic_filename_verified={str(arabic_filename_verified).lower()}",
                    f"last_item_verified={str(last_item_verified).lower()}",
                    f"preview_verified={str(preview_verified).lower()}",
                    f"source_preview_loaded={str(not window.source_preview.viewer._pixmap.isNull()).lower()}",
                    f"output_preview_loaded={str(not window.output_preview.viewer._pixmap.isNull()).lower()}",
                    f"output_preview_minimum_height={window.output_preview.viewer.minimumHeight()}",
                    f"selected_item_code={window.selected_item_code_label.text()}",
                    f"selected_barcode={window.selected_barcode_label.text()}",
                    f"selected_file={window.selected_file_label.text()}",
                    f"manual_controls_separated={str(manual_controls_separated).lower()}",
                    f"manual_controls_accessible={str(manual_controls_accessible).lower()}",
                    f"manual_panel_height={window.manual_group.height()}",
                    f"manual_table_scroll_maximum={manual_table_scroll.maximum()}",
                    f"manual_table_horizontal_scroll={window.results_table.horizontalScrollBar().maximum()}",
                    f"manual_table_height={window.results_table.height()}",
                    f"manual_table_minimum={window.results_table.minimumHeight()}",
                    f"manual_reference_button_height={window.use_reference_button.height()}",
                    f"manual_group_link_button_height={window.reference_group_link_button.height()}",
                    f"manual_search_height={window.manual_item_edit.height()}",
                    f"manual_preview_button_height={window.jump_to_previews_button.height()}",
                    f"manual_panel_verified={str(manual_panel_verified).lower()}",
                    f"editor_crop_box={editor_crop_box}",
                    f"editor_dirty_before_close={str(editor_dirty_before_close).lower()}",
                    f"editor_verified={str(editor_verified).lower()}",
                    f"gui_test_passed={str(gui_test_passed).lower()}",
                    "loaded_image_count=82",
                    "loaded_result_count=82",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        window.close()
        app.exit(0 if gui_test_passed else 5)

    QTimer.singleShot(1500, finish)
    return int(app.exec())


def main() -> int:
    if "--self-test-output" in sys.argv:
        index = sys.argv.index("--self-test-output")
        if index + 1 >= len(sys.argv):
            return 2
        return _self_test(Path(sys.argv[index + 1]))
    if "--batch-self-test-output" in sys.argv:
        index = sys.argv.index("--batch-self-test-output")
        if index + 2 >= len(sys.argv):
            return 2
        return _batch_self_test(Path(sys.argv[index + 1]), Path(sys.argv[index + 2]))
    if "--gui-smoke-test-output" in sys.argv:
        index = sys.argv.index("--gui-smoke-test-output")
        if index + 1 >= len(sys.argv):
            return 2
        return _gui_smoke_test(Path(sys.argv[index + 1]))

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("Ahmed Al-Faifi")
    icon_path = bundled_asset("app_icon.png")
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
