from __future__ import annotations

import os
import dataclasses as _dc
import json  # 2.9.11: كان مفقودًا — فكل حفظ/استعادة لخيار التسمية
               # ينفجر بـ NameError، والاستعادة تكتمه وتعود للوحدة الواحدة
import math

# Qt 6 يدعم Per-Monitor DPI تلقائياً، وهذه القيم تمنع التقريب الخشن
# لعوامل 125% و150% عند تشغيل الحزمة على Windows.
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

import re
import shutil
import sys
import threading
import time
import traceback
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, QItemSelectionModel, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QImageReader, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QTransform
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
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

from ui_scale import ScaleEngine

# 2.9.6 — تسريع الإقلاع.
# محرّك الرؤية (`smart_catalog_vision.pipeline`) يجرّ خلفه cv2 وnumpy
# وopenpyxl وfinal_images. استيراده وقت الإقلاع كان يحجز الشاشة
# فارغة قبل رسم أول بكسل، ولا شيء منه مطلوب لبناء الواجهة.
# `lazy_engine` يقدّم وكلاء بنفس الأسماء تُحمّل المحرّك عند أول
# استعمال حقيقي، مع تسخين خلفي بعد ظهور النافذة.
import lazy_engine as _lazy_engine
from lazy_engine import (
    FinalImageOptions,
    SUPPORTED_IMAGE_EXTENSIONS,
    BatchItemResult,
    BatchRunResult,
    IndividualImagePreview,
    apply_individual_image_edit,
    apply_manual_link,
    apply_manual_links,
    pipeline as _vision_pipeline,
    preview_individual_image_edit,
    run_batch,
)


# 2.9.12 — سياق إعادة المعالجة: يُحيط بكل ربط أو تحرير لصفٍّ له
# مخرَج قائم، فيُكتب فوق الملف نفسه بدل توليد -2 ثم -3 ثم -4
# ثم حذف القديم — وهذا سبب «اختفاء الصور» الذي أبلغ عنه المالك.
# البديل الآمن يجعل الواجهة تعمل ولو غابت الوحدة.
try:
    from integrity_patch import reprocess_scope as _reprocess_scope
except Exception:  # pragma: no cover - حزمة بلا وحدة الترقيع
    from contextlib import nullcontext as _nullcontext

    def _reprocess_scope(_previous_output=None):    # type: ignore[misc]
        return _nullcontext()

try:
    from engine_v2.source_vault_v2 import (
        deposit_job_sources as _vault_deposit,
        repair_job_state as _vault_repair,
    )
except Exception:  # pragma: no cover - حزمة بلا المحرك الجديد
    _vault_deposit = None
    _vault_repair = None


def _vault_secure_sources(workspace, image_paths, catalog_path="") -> None:
    """إيداع صور الدفعة وملف الإكسل في خزانة مساحة العمل.

    بدونها يعتمد أي تعديل لاحق على بقاء الصور في موقعها الأصلي،
    فيفشل «حفظ واعتماد التعديل» إن نُقلت أو حُذفت. الإيداع رخيص
    (ربط صلب على نفس القرص) ولا يرفع استثناءً أبدًا.
    """
    if _vault_deposit is None:
        return
    try:
        _vault_deposit(workspace, image_paths, catalog_path)
    except Exception:
        pass


def _vault_restore_sources(workspace, extra_dirs=None):
    """استرجاع مسارات المصادر المفقودة قبل أي تعديل فردي/ربط يدوي.

    يعيد تقرير الإصلاح (أو None) لتستطيع الواجهة تسمية الملف
    المفقود بدل رسالة عامة غامضة.
    """
    if _vault_repair is None:
        return None
    try:
        return _vault_repair(workspace, extra_dirs=extra_dirs)
    except Exception:
        return None


# الدالة الأصلية تُلتقط لحظة تحميل المحرّك لا وقت استيراد هذه الوحدة؛
# قراءتها مبكرًا كانت ستُبطل التأجيل وتُعيد الإقلاع إلى بطئه.
_ORIGINAL_PREPARE_INDIVIDUAL_SOURCE = None


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


def _install_perspective_patch(original):
    """يُركّب القص المنظوري فور تحميل المحرّك لا قبله.

    يُستدعى مرة واحدة من `lazy_engine.load_engine`، فيحفظ الدالة
    الأصلية ثم يُعيد البديل. بهذا يبقى سلوك القص مطابقًا
    تمامًا لما كان قبل التأجيل.
    """
    global _ORIGINAL_PREPARE_INDIVIDUAL_SOURCE
    _ORIGINAL_PREPARE_INDIVIDUAL_SOURCE = original
    return _prepare_individual_perspective_source


_lazy_engine.register_perspective_patch(_install_perspective_patch)


APP_NAME = "Ahmed Al-Faifi Market Image Studio"
APP_VERSION = "3.4.13"
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
        # 2.9.6: كانت الرسالة عامة فلا يعرف المالك أي ملف مفقود.
        # نستخرج الملف من الأثر ومن تقرير خزانة المصادر إن أُرفق.
        raw = str(traceback_text or "")
        missing = ""
        vault_note = ""
        marker = "[تفاصيل المصادر]"
        if marker in raw:
            vault_note = raw.split(marker, 1)[1].strip()
        match = re.search(r"غير موجود[ة]?\s*:\s*(.+)", raw)
        if not match:
            match = re.search(r"No such file or directory:\s*'?\"?([^'\"\n]+)",
                              raw, re.IGNORECASE)
        if match:
            # يجب فصل مسارات ويندوز (\\) ولينكس (/) معًا، لأن Path
            # على منصة واحدة لا تفهم فاصل المنصة الأخرى.
            raw_path = match.group(1).strip().strip("'\"")
            missing = re.split(r"[\\/]", raw_path)[-1].strip()
        lines = ["تعذر العثور على ملف مطلوب لإكمال العملية."]
        if missing:
            lines.append(f"الملف المفقود: {missing}")
        if vault_note:
            lines.append(vault_note)
        lines.append(
            "الأغلب أن مجلد الصور أو ملف Excel نُقل أو حُذف بعد تشغيل الدفعة. "
            "أعد اختيار مجلد الصور الأصلية من جديد ثم أعد المحاولة؛ ولن يتكرر هذا "
            "للدفعات الجديدة لأن البرنامج أصبح يحفظ نسخة داخلية من المصادر."
        )
        return "\n".join(lines)
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
    # 2.9.2: مفاتيح كانت تظهر بالإنجليزية الخام في واجهة عربية.
    "unmatched": "غير مرتبط",
    "pending": "قيد المعالجة",
    "skipped": "متجاوز",
    "duplicate": "مكرر",
}
STATUS_COLORS = {
    "matched": (16, 135, 92),
    "manual": (37, 99, 235),
    "review": (202, 138, 4),
    "error": (203, 45, 62),
    "unmatched": (120, 113, 108),
    "pending": (100, 116, 139),
    "skipped": (148, 163, 184),
    "duplicate": (147, 51, 234),
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


def _available_memory_gb() -> float:
    """الذاكرة المتاحة فعليًا بالجيجابايت (0.0 إن تعذر القياس).

    تعمل على ويندوز ولينكس بلا تبعيات إضافية إلزامية.
    """
    try:  # الأدق إن توفر
        import psutil  # type: ignore
        return float(psutil.virtual_memory().available) / (1024 ** 3)
    except Exception:
        pass
    if sys.platform.startswith("win"):
        try:
            import ctypes

            class _MemStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _MemStatus()
            status.dwLength = ctypes.sizeof(_MemStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(  # type: ignore
                    ctypes.byref(status)):
                return float(status.ullAvailPhys) / (1024 ** 3)
        except Exception:
            pass
    else:
        try:
            with open("/proc/meminfo", "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("MemAvailable:"):
                        return float(line.split()[1]) / (1024 ** 2)
        except Exception:
            pass
    return 0.0


#: تقدير استهلاك الذاكرة لكل مسار جودة (صورة كبيرة + نسخ OCR وسيطة).
_QUALITY_WORKER_MEMORY_GB = 0.75


def _quality_pass_workers(total: int) -> int:
    """عدد المسارات المتوازية لتمريرة الجودة (2.9.6 — تسريع الدفعة).

    مقاس على صور حقيقية 2000×1800 مع طمس التواريخ:
    2–3 مسارات تعطي تسريعًا ×1.8–×2.3، بينما 5–6 مسارات تنهار
    إلى ×0.05 بسبب ضغط الذاكرة (كل مسار يحمل صورة كاملة
    ونسخًا وسيطة). لذلك الحساب واعٍ بالذاكرة لا بالنوى وحدها،
    ومسقوف بـ 4 مهما كان الجهاز قويًا.

    يُضبط يدويًا بمتغير البيئة ``MIS_QUALITY_WORKERS`` (1 = تسلسلي).
    """
    if total <= 1:
        return 1
    override = os.environ.get("MIS_QUALITY_WORKERS", "").strip()
    if override.isdigit() and int(override) >= 1:
        return max(1, min(int(override), total))
    try:
        cpu = os.cpu_count() or 1
    except Exception:
        cpu = 1
    if cpu <= 2:
        return 1
    by_cpu = cpu // 2
    memory_gb = _available_memory_gb()
    if memory_gb <= 0:  # تعذر القياس → محافظ جدًا
        by_memory = 2
    else:
        # نترك هامش جيجابايت واحد للواجهة والنظام
        by_memory = int(max(0.0, memory_gb - 1.0) / _QUALITY_WORKER_MEMORY_GB)
    return max(1, min(4, by_cpu, by_memory, total))


class _OpenCVThreadBudget:
    """يقيّد خيوط OpenCV الداخلية أثناء التوازي ثم يعيدها.

    بدونه يصير مجموع الخيوط = عدد المسارات × عدد النوى،
    فيحدث اكتظاظ (oversubscription) يبطئ المعالجة بدل أن يسرّعها.
    """

    def __init__(self, workers: int) -> None:
        self._workers = max(1, workers)
        self._previous = None

    def __enter__(self):
        try:
            import cv2  # متأخر عمدًا: لا داعي لتحميله إن لم تبدأ دفعة

            self._previous = cv2.getNumThreads()
            cpu = os.cpu_count() or 1
            cv2.setNumThreads(max(1, cpu // self._workers))
        except Exception:
            self._previous = None
        return self

    def __exit__(self, *exc) -> bool:
        if self._previous is not None:
            try:
                import cv2

                cv2.setNumThreads(self._previous)
            except Exception:
                pass
        return False


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
        blur_dates: bool = True,
        text_polish: bool = True,
    ) -> None:
        super().__init__()
        self.catalog_path = catalog_path
        self.image_paths = image_paths
        self.workspace = workspace
        self.remove_background = remove_background
        self.enhance_product = enhance_product
        self.image_options = image_options
        self.blur_dates = blur_dates
        self.text_polish = text_polish

    def run(self) -> None:
        try:
            # 2.9.6: إيداع المصادر قبل المعالجة لا بعدها، لأن الدفعة
            # الطويلة قد تُقاطع فيبقى ما أُودع متاحًا للتعديل لاحقًا.
            _vault_secure_sources(
                self.workspace, self.image_paths, self.catalog_path)
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
            self._quality_post_pass(result)
            self.completed.emit(result)
        except Exception:
            self.failed.emit(traceback.format_exc())

    def _quality_post_pass(self, result) -> None:
        """تمريرة جودة لاحقة على النواتج: حدة نصية ذكية تبقي كتابات
        المنتج والحقائق الغذائية واضحة + طمس التواريخ المطبوعة تلقائيًا.
        آمنة: لا تعيد الحفظ إلا إذا تحسّنت المقروئية أو طُمس تاريخ.

        2.9.6 (أداء): كانت تعمل تسلسليًا على نواة واحدة — ولأنّ طمس
        التواريخ يكلف ≈ 1.3 ثانية للصورة، فدفعة من 100 صورة كانت
        تضيف أكثر من دقيقتين. الآن تتوزّع على كل النوى المتاحة
        (OpenCV وOCR يحرران GIL) مع تقدّم حقيقي لكل صورة.
        """
        if not (self.text_polish or self.blur_dates):
            return
        try:
            from engine_v2.quality_v2 import polish_output_file
        except Exception:
            return
        items = getattr(result, "items", None) or []
        seen: set[str] = set()
        paths: list[str] = []
        for item in items:
            path = getattr(item, "output_path", "") or ""
            if not path or path in seen:
                continue
            seen.add(path)
            paths.append(path)
        total = len(paths)
        if not total:
            return

        def _polish_one(path: str) -> None:
            try:
                if Path(path).is_file():
                    polish_output_file(path, quality=101,
                                       blur_dates=self.blur_dates)
            except Exception:
                pass

        workers = _quality_pass_workers(total)
        if workers <= 1:
            for i, path in enumerate(paths):
                _polish_one(path)
                if i % 5 == 0 or i == total - 1:
                    self.progress_changed.emit(
                        total, total,
                        f"تحسين الوضوح النهائي {i + 1}/{total}")
            return

        from concurrent.futures import ThreadPoolExecutor, as_completed

        done = 0
        with _OpenCVThreadBudget(workers):
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(_polish_one, p) for p in paths]
                for _ in as_completed(futures):
                    done += 1
                    if done % 3 == 0 or done == total:
                        self.progress_changed.emit(
                            total, total,
                            f"تحسين الوضوح النهائي {done}/{total}"
                            f" — {workers} مسارات متوازية")


# 2.9.9 — حُذف `VisualSignatureWorker` نهائيًا مع إلغاء نسبة التشابه بطلب المالك.
# كان يبني بصمة بصرية لكل صورة في الخلفية (~47ms للصورة، وأضعافها لصور
# الكاميرا) لمجرد عرض نسبة مئوية لم تكن دقيقة ولا مفيدة. إزالته توفّر قراءة
# وفكّ ترميز كامل لكل صور الدفعة، فيصبح الربط أسرع وأخف على الذاكرة.


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
        manual_rotation: float = 0.0,
        previous_outputs: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self.workspace = workspace
        # 2.9.12: خريطة {اسم المصدر: مسار المخرَج القائم} — تُملأ من
        # الواجهة قبل الربط ليُكتب فوق الملف نفسه بدل توليد اسم جديد.
        self.previous_outputs = dict(previous_outputs or {})
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
        self.manual_rotation = float(manual_rotation)

    def _apply_rotation_to_outputs(self, result: object) -> None:
        """تطبيق الميل اليدوي على مخرجات الربط مباشرة —
        فتخرج الصورة معتدلة بالشكل المناسب فور الربط."""
        if abs(self.manual_rotation) < 0.05:
            return
        try:
            import cv2
            import numpy as np
            wanted = set(self.source_names)
            for it in getattr(result, "items", []) or []:
                if getattr(it, "source_name", None) not in wanted:
                    continue
                out = getattr(it, "output_path", None)
                if not out:
                    continue
                p = Path(out)
                if not p.is_file():
                    continue
                data = np.fromfile(str(p), dtype=np.uint8)
                img = cv2.imdecode(data, cv2.IMREAD_COLOR)
                if img is None:
                    continue
                h, w = img.shape[:2]
                m = cv2.getRotationMatrix2D((w / 2.0, h / 2.0),
                                            self.manual_rotation, 1.0)
                img = cv2.warpAffine(
                    img, m, (w, h), flags=cv2.INTER_LANCZOS4,
                    borderMode=cv2.BORDER_CONSTANT,
                    borderValue=(255, 255, 255))
                ext = p.suffix.lower() or ".webp"
                # 101 = lossless: يمنع فقدان حدة الكتابات والحقائق الغذائية
                # عند إعادة الحفظ بعد التدوير (الضغط المتكرر يتراكم).
                params = [cv2.IMWRITE_WEBP_QUALITY, 101] if ext == ".webp" \
                    else []
                ok, buf = cv2.imencode(ext, img, params)
                if ok:
                    buf.tofile(str(p))
        except Exception:
            pass

    def run(self) -> None:
        try:
            # 2.9.6: الربط اليدوي يقرأ المسار المطلق المخزّن في job_state؛
            # إن نُقلت الصور أو استُعيدت جلسة قديمة فشل بـFileNotFoundError.
            self._repair_report = _vault_restore_sources(self.workspace)
            # 2.9.12: إعادة معالجة صفٍّ له مخرَج قائم تكتب فوقه،
            # فلا يتصاعد الترقيم ولا يُحذف ملف مرجعي.
            # السياق يقبل مسارًا واحدًا، والربط الجماعي لصور متعددة
            # لصنف واحد يُترك للسلوك الطبيعي (أرقام جديدة مطلوبة).
            previous = None
            if len(self.source_names) == 1:
                previous = self.previous_outputs.get(self.source_name)
            with _reprocess_scope(previous):
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
            self._apply_rotation_to_outputs(result)
            self.completed.emit(result)
        except Exception:
            self.failed.emit(self._augment_failure(traceback.format_exc()))

    def _augment_failure(self, trace: str) -> str:
        """إرفاق أسماء الملفات المفقودة بالأثر لتكون الرسالة دقيقة."""
        report = getattr(self, "_repair_report", None)
        detail = getattr(report, "summary_ar", None)
        if callable(detail):
            text = detail()
            if text:
                return f"{trace}\n[تفاصيل المصادر] {text}"
        return trace


class EditorDirectSaveResult:
    """نتيجة حفظ مباشر لبكسلات المحرر فوق مخرج الصنف القائم."""

    def __init__(self, output_path: str) -> None:
        self.output_path = str(output_path)


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
        blur_dates: bool = False,
        deglare: bool = False,
        manual_rotation: float = 0.0,
        edited_source_path: "Path | None" = None,
        previous_output: str = "",
        editor_output=None,
    ) -> None:
        super().__init__()
        self.workspace = workspace
        self.source_name = source_name
        # 2.9.12: مسار المخرَج القائم لهذا الصف — يُكتب فوقه بدل
        # توليد اسم جديد، فيظهر الطمس فورًا في الصورة المعروضة.
        self.previous_output = str(previous_output or "")
        self.preview_only = bool(preview_only)
        self.manual_crop = manual_crop
        self.smart_enhance = bool(smart_enhance)
        self.enhancement_strength = int(enhancement_strength)
        self.smart_crop = bool(smart_crop)
        self.auto_straighten = bool(auto_straighten)
        self.remove_background = bool(remove_background)
        self.image_options = image_options
        self.blur_dates = bool(blur_dates)
        self.deglare = bool(deglare)
        self.manual_rotation = float(manual_rotation)
        # 2.6: مسار صورة معدّلة مسبقًا من المحرر الموحد — تحل محل المصدر الأصلي
        self.edited_source_path = Path(edited_source_path) if edited_source_path else None
        # إن كان المحرر أنتج بالفعل الصورة النهائية، لا نعيد إدخالها إلى
        # pipeline ثم نعيد تأطيرها وكتابتها مرة أخرى. نسخة مستقلة للخيط.
        self.editor_output = editor_output.copy() if editor_output is not None else None

    def _post_process_file(self, path: "Path | str | None") -> None:
        """تطبيق الميل اليدوي وطمس التواريخ وإزالة الانعكاسات على الملف الناتج."""
        needs_rotation = abs(self.manual_rotation) > 0.049
        if not (self.blur_dates or self.deglare or needs_rotation) or not path:
            return
        try:
            import cv2
            import numpy as np
            p = Path(path)
            if not p.is_file():
                return
            data = np.fromfile(str(p), dtype=np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_COLOR)
            if img is None:
                return
            if needs_rotation:
                # تدوير دقيق حول المركز مع تعبئة بيضاء — المنتج على
                # خلفية بيضاء أصلًا فتبقى النتيجة نظيفة بلا زوايا داكنة
                h, w = img.shape[:2]
                m = cv2.getRotationMatrix2D((w / 2.0, h / 2.0),
                                            self.manual_rotation, 1.0)
                img = cv2.warpAffine(
                    img, m, (w, h), flags=cv2.INTER_LANCZOS4,
                    borderMode=cv2.BORDER_CONSTANT,
                    borderValue=(255, 255, 255))
            if self.deglare:
                from engine_v2.edge_refine_v2 import remove_glare
                img = remove_glare(img, 0.6)
            if self.blur_dates:
                from engine_v2.date_blur_v2 import auto_blur_dates
                img, _count = auto_blur_dates(img)
            ext = p.suffix.lower() or ".webp"
            # 101 = lossless — حفاظًا على وضوح النصوص بعد المعالجات التحريرية.
            ok, buf = cv2.imencode(ext, img, [cv2.IMWRITE_WEBP_QUALITY, 101] if ext == ".webp" else [])
            if ok:
                buf.tofile(str(p))
        except Exception:
            pass

    def _save_editor_output_directly(self) -> bool:
        """كتابة بكسلات المحرر فوق الناتج القائم ذرّيًا وبلا pipeline."""
        if self.editor_output is None or self.preview_only or not self.previous_output:
            return False
        try:
            import cv2
            target = Path(self.previous_output)
            if not target.is_file():
                return False
            ext = target.suffix.lower() or ".webp"
            if ext == ".webp":
                params = [cv2.IMWRITE_WEBP_QUALITY, 101]
            elif ext in (".jpg", ".jpeg"):
                params = [cv2.IMWRITE_JPEG_QUALITY, 100]
            else:
                params = [cv2.IMWRITE_PNG_COMPRESSION, 3]
            ok, encoded = cv2.imencode(ext, self.editor_output, params)
            if not ok:
                return False
            temp = target.with_name(f".{target.stem}.editor.tmp{target.suffix}")
            encoded.tofile(str(temp))
            temp.replace(target)
            self.progress_changed.emit(1, 1, "حُفظ تعديل المحرر مباشرة")
            self.completed.emit(EditorDirectSaveResult(str(target)))
            return True
        except Exception:
            return False

    def run(self) -> None:
        try:
            # مسار سريع: الصورة عُزلت وأُطّرت داخل المحرر، فإعادة تشغيل
            # pipeline لا تضيف شيئًا وتؤخر الحفظ. نكتبها فوق الملف نفسه.
            if self._save_editor_output_directly():
                return
            # 2.9.6: أهم إصلاح في هذا المسار — «حفظ واعتماد التعديل» كان
            # يفشل لأن المحرك يعود للمسار المطلق المخزّن وقت الدفعة.
            # الاسترجاع يسبق أي قراءة للحالة.
            self._repair_report = _vault_restore_sources(self.workspace)
            arguments = {
                "manual_crop": self.manual_crop,
                "smart_enhance": self.smart_enhance,
                "enhancement_strength": self.enhancement_strength,
                "smart_crop": self.smart_crop,
                "auto_straighten": self.auto_straighten,
                "remove_background": self.remove_background,
                "final_image_options": self.image_options,
            }
            # 2.6: إن وُجد مصدر معدّل من المحرر الموحد، نعترض تجهيز المصدر
            # في الـ pipeline ليستخدم صورة المحرر بدل الملف الأصلي، ثم نعيد
            # الدالة الأصلية في كل الأحوال (try/finally)
            _override_active = self.edited_source_path is not None and self.edited_source_path.is_file()
            if _override_active:
                _prev_prepare = _vision_pipeline._prepare_individual_source
                _edited = self.edited_source_path

                def _use_edited_source(source, staging_dir, crop_box, *args, **kwargs):  # noqa: ANN001
                    return _edited, None

                _vision_pipeline._prepare_individual_source = _use_edited_source
            try:
                # المعاينة لا تكتب مخرَجًا نهائيًا، فلا تحتاج تثبيت الاسم.
                _previous = None if self.preview_only else \
                    (self.previous_output or None)
                with _reprocess_scope(_previous):
                    self._run_pipeline(arguments)
            finally:
                if _override_active:
                    _vision_pipeline._prepare_individual_source = _prev_prepare
        except Exception:
            self.failed.emit(self._augment_failure(traceback.format_exc()))

    def _augment_failure(self, trace: str) -> str:
        """إرفاق أسماء الملفات المفقودة بالأثر لتكون الرسالة دقيقة."""
        report = getattr(self, "_repair_report", None)
        detail = getattr(report, "summary_ar", None)
        if callable(detail):
            text = detail()
            if text:
                return f"{trace}\n[تفاصيل المصادر] {text}"
        return trace

    def _run_pipeline(self, arguments: dict) -> None:
        if self.preview_only:
            self.progress_changed.emit(0, 1, "تحليل الصورة وتجهيز المعاينة")
            result = preview_individual_image_edit(
                self.workspace,
                self.source_name,
                **arguments,
            )
            self._post_process_file(getattr(result, "preview_path", None))
            self.progress_changed.emit(1, 1, "المعاينة جاهزة قبل الحفظ")
        else:
            result = apply_individual_image_edit(
                self.workspace,
                self.source_name,
                progress=lambda done, total, name: self.progress_changed.emit(done, total, name),
                **arguments,
            )
            if self.blur_dates or self.deglare or \
                    abs(self.manual_rotation) > 0.049:
                for it in getattr(result, "items", []) or []:
                    if getattr(it, "source_name", None) == self.source_name:
                        self._post_process_file(getattr(it, "output_path", None))
                        break
        self.completed.emit(result)


class StatCard(QFrame):
    """بطاقة عدّاد تتحول من رأسية إلى أفقية حسب الارتفاع المتاح.

    2.9: كانت رأسية دائمًا بارتفاع ثابت 46px. على الشاشات القصيرة يقيس
    المحرك الارتفاع إلى ~32px فلا يتسع لسطرين، فتختفي التسمية
    («أخطاء/مراجعة/مطابق/إجمالي») ويبقى الرقم بلا معنى — وهو ما رصده
    المستخدم بصريًا. الحل: ``set_compact()`` يبدّل الاتجاه إلى أفقي
    (رقم ثم تسمية جوار بعض) فيكفي سطر واحد ويبقى النص كاملًا مقروءًا.
    """

    def __init__(self, title: str, color: str) -> None:
        super().__init__()
        self.setObjectName("statCard")
        self._title = title
        self._color = color
        self._compact = False
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 8, 10, 8)
        self._layout.setSpacing(2)
        self.value = QLabel("0")
        self.value.setAlignment(Qt.AlignCenter)
        self.value.setStyleSheet(f"font-size: 20px; font-weight: 800; color: {color};")
        self.caption = QLabel(title)
        self.caption.setAlignment(Qt.AlignCenter)
        self.caption.setStyleSheet("color: #64748b; font-size: 11px;")
        self._layout.addWidget(self.value)
        self._layout.addWidget(self.caption)
        # إصلاح قص النص: العرض الأدنى يراعي عرض العنوان الفعلي
        self.setMinimumWidth(
            max(64, self.caption.fontMetrics().horizontalAdvance(title) + 22))

    def set_compact(self, compact: bool) -> None:
        """يبدّل بين الترتيب الرأسي (واسع) والأفقي (قصير) بلا فقدان نص."""
        if compact == self._compact:
            return
        self._compact = compact
        old_layout = self._layout
        old_layout.removeWidget(self.value)
        old_layout.removeWidget(self.caption)
        QWidget().setLayout(old_layout)  # يفصل التخطيط القديم بأمان
        if compact:
            self._layout = QHBoxLayout(self)
            self._layout.setContentsMargins(8, 2, 8, 2)
            self._layout.setSpacing(5)
            self.value.setStyleSheet(
                f"font-size: 15px; font-weight: 800; color: {self._color};")
            self.caption.setStyleSheet("color: #64748b; font-size: 10px;")
        else:
            self._layout = QVBoxLayout(self)
            self._layout.setContentsMargins(10, 8, 10, 8)
            self._layout.setSpacing(2)
            self.value.setStyleSheet(
                f"font-size: 20px; font-weight: 800; color: {self._color};")
            self.caption.setStyleSheet("color: #64748b; font-size: 11px;")
        self._layout.addWidget(self.value)
        self._layout.addWidget(self.caption)
        needed = (self.caption.fontMetrics().horizontalAdvance(self._title)
                  + self.value.fontMetrics().horizontalAdvance("9999") + 30
                  if compact else
                  max(64, self.caption.fontMetrics().horizontalAdvance(self._title) + 22))
        self.setMinimumWidth(needed)
        self.updateGeometry()


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
        # 2.9: الحد الأدنى 420×270 كان يفرض على لوحة الصورة ارتفاعًا أكبر من
        # المساحة المتاحة على 800×600، فيتراكب نص «لا توجد صورة» مع تلميح
        # القراءة أسفله. الآن الحد الأدنى صغير ومرن، والصورة تحتوي نفسها،
        # فيبقى كل نص في مكانه على أي حجم شاشة.
        self.image_label.setMinimumSize(160, 110)
        self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
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
        self._base_pixmap = pixmap
        self._pixmap = self._apply_preview_rotation(pixmap)
        self.image_label.setToolTip(str(candidate))
        self.fit_image()

    def set_preview_rotation(self, degrees: float) -> None:
        """معاينة الميل اليدوي فوريًا — تدوير العرض فقط دون لمس الملف."""
        self._preview_rotation = float(degrees)
        base = getattr(self, "_base_pixmap", None)
        if base is None or base.isNull():
            return
        self._pixmap = self._apply_preview_rotation(base)
        self._render()

    def _apply_preview_rotation(self, pixmap: QPixmap) -> QPixmap:
        deg = float(getattr(self, "_preview_rotation", 0.0) or 0.0)
        if abs(deg) < 0.05 or pixmap.isNull():
            return pixmap
        from PySide6.QtGui import QTransform
        # القيمة الموجبة = عكس العقارب (مطابق لـ cv2.getRotationMatrix2D)
        rotated = pixmap.transformed(QTransform().rotate(-deg),
                                     Qt.SmoothTransformation)
        # تعبئة بيضاء خلف الدوران لمطابقة الناتج النهائي
        canvas = QPixmap(rotated.size())
        canvas.fill(Qt.white)
        painter = QPainter(canvas)
        painter.drawPixmap(0, 0, rotated)
        painter.end()
        return canvas

    def _resize_label_to_viewport(self) -> None:
        """يلائم اللوحة الفارغة منفذ العرض بلا فرض 420×270.

        2.9: الأرضية الصلبة 420×270 كانت تجعل اللوحة أطول من المنفذ على
        الشاشات القصيرة، فيُزاح نص «لا توجد صورة» إلى أسفل ويتراكب بصريًا
        مع تلميح القراءة. الآن اللوحة تساوي المنفذ تمامًا (بحدّ أدنى صغير
        للأمان)، فيبقى النص في مركز المساحة المرئية على أي شاشة.
        """
        viewport = self.viewport().size()
        self.image_label.resize(
            max(120, viewport.width() - 2), max(90, viewport.height() - 2))

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
        # 2.9: كان العنوان يُبتر إلى «الصورة الناتجة — افحص ا…» على الشاشات
        # الضيقة. الآن نحمل نسختين: كاملة للشاشات الواسعة، ومختصرة تُستخدم
        # تلقائيًا عند شحّ العرض، فلا تظهر نقاط بتر أبدًا والمعنى يبقى واضحًا.
        self._title_full = title
        self._title_short = title.split(" — ", 1)[0].strip() or title
        label_title = QLabel(title)
        label_title.setObjectName("previewTitle")
        label_title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._title_label = label_title
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
            # 2.6: لا قص — عرض أدنى مبني على النص الفعلي + هوامش الـ CSS
            button.setMinimumWidth(
                button.fontMetrics().horizontalAdvance(button.text()) + 22)
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

        self._hint_full = ("للقراءة الدقيقة: اضغط 100% ثم حرّك أشرطة التمرير، "
                           "أو استخدم Ctrl + عجلة الفأرة.")
        self._hint_short = "للقراءة الدقيقة: اضغط 100% أو Ctrl + عجلة الفأرة."
        hint = QLabel(self._hint_full)
        hint.setObjectName("previewHint")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        self._hint_label = hint
        layout.addWidget(hint)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        """يبدّل بين النص الكامل والمختصر حسب العرض الفعلي المتاح.

        2.9: القياس هنا حقيقي (عرض العنصر بعد التخطيط) لا تقديري، فلا
        يعتمد على قائمة دقات ثابتة ويعمل على أي حجم شاشة.
        """
        super().resizeEvent(event)
        title = getattr(self, "_title_label", None)
        if title is not None:
            available = max(0, title.width())
            metrics = title.fontMetrics()
            wanted = (self._title_full
                      if metrics.horizontalAdvance(self._title_full) <= available
                      else self._title_short)
            if title.text() != wanted:
                title.setText(wanted)
        hint = getattr(self, "_hint_label", None)
        if hint is not None:
            metrics = hint.fontMetrics()
            # سطران كحدّ أقصى للتلميح: إن لم يكفِ العرض نستخدم النسخة القصيرة
            fits = metrics.horizontalAdvance(self._hint_full) <= max(1, hint.width()) * 2
            wanted = self._hint_full if fits else self._hint_short
            if hint.text() != wanted:
                hint.setText(wanted)

    def set_image(self, path: Path | None) -> None:
        self.viewer.set_image(path)
        self.open_button.setEnabled(self.viewer.path is not None)

    def open_image(self) -> None:
        if self.viewer.path is not None and self.viewer.path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.viewer.path)))


class _EditorFlowLayout(QLayout):
    """2.8: تخطيط ملتف لشريط أزرار أفقي (RTL) — بلا تراكب ولا قص.

    يختلف عن ``unified_editor._FlowLayout`` بأمرين جوهريين:

    1. يمنح العناصر المرنة (``QSizePolicy.Ignored`` أفقيًا — مئل التلميح)
       ما تبقى من عرض السطر بدل عرض التلميح الطبيعي، فلا يدفع الأزرار.
    2. يحترم ``minimumSizeHint`` للأزرار فلا يُقص نص زر أبدًا.
    """

    def __init__(self, parent=None, margin: int = 0, spacing: int = 8) -> None:
        super().__init__(parent)
        self._items: list = []
        self._spacing = spacing
        self.setContentsMargins(margin, margin, margin, margin)

    # —— واجهة QLayout ——
    def addItem(self, item):  # noqa: N802
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientations(0)

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, width):  # noqa: N802
        return self._do_layout(QRect(0, 0, max(width, 0), 0), test_only=True)

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):  # noqa: N802
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(),
                      margins.top() + margins.bottom())
        return size

    # —— التخطيط الفعلي ——
    @staticmethod
    def _is_flexible(item) -> bool:
        widget = item.widget()
        if widget is None:
            return False
        return widget.sizePolicy().horizontalPolicy() in (
            QSizePolicy.Ignored, QSizePolicy.Expanding)

    def _item_widths(self, item) -> tuple[int, int]:
        """(العرض المطلوب، الحد الأدنى المقدّس) للعنصر."""
        widget = item.widget()
        hint_w = item.sizeHint().width()
        if widget is None:
            return hint_w, item.minimumSize().width()
        floor = max(widget.minimumSizeHint().width(), widget.minimumWidth())
        if self._is_flexible(item):
            # التلميح يقبل الانكماش حتى الاختفاء الفعلي
            floor = 0
        return max(hint_w, floor), floor

    def _do_layout(self, rect, *, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(),
                                  -margins.right(), -margins.bottom())
        line_width = max(effective.width(), 0)
        if line_width <= 0:
            # قبل استقرار الأب لا نرصّ شيئًا — الرصّ بعرض صفري هو ما يولّد التراكب
            return sum(item.sizeHint().height() for item in self._items[:1]) \
                + margins.top() + margins.bottom()

        # 1) تقسيم العناصر إلى أسطر وفق العروض المطلوبة
        lines: list[list] = []
        current: list = []
        used = 0
        for item in self._items:
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue
            want, floor = self._item_widths(item)
            need = min(want, line_width)
            extra = need + (self._spacing if current else 0)
            if current and used + extra > line_width:
                lines.append(current)
                current = [item]
                used = need
            else:
                current.append(item)
                used += extra
        if current:
            lines.append(current)

        # 2) توزيع العروض داخل كل سطر وترتيبها من اليمين
        y = effective.y()
        for line in lines:
            gaps = self._spacing * max(len(line) - 1, 0)
            wants = [min(self._item_widths(it)[0], line_width) for it in line]
            budget = line_width - gaps
            total_want = sum(wants)
            widths = list(wants)
            if total_want > budget:
                # الفارق يُخصم من العناصر المرنة فقط — الأزرار لا تُقص
                deficit = total_want - budget
                for index, item in enumerate(line):
                    if deficit <= 0:
                        break
                    if not self._is_flexible(item):
                        continue
                    give = min(deficit, widths[index])
                    widths[index] -= give
                    deficit -= give
                if deficit > 0:
                    for index in range(len(line)):
                        if deficit <= 0:
                            break
                        floor = self._item_widths(line[index])[1]
                        give = min(deficit, max(widths[index] - floor, 0))
                        widths[index] -= give
                        deficit -= give
            elif any(self._is_flexible(it) for it in line):
                # فائض المساحة يذهب للعناصر المرنة فيمتلأ السطر بلا فراغ أعمى
                flexible = [i for i, it in enumerate(line) if self._is_flexible(it)]
                share = (budget - total_want) // len(flexible)
                for index in flexible:
                    widths[index] += share
            line_height = max(item.sizeHint().height() for item in line)
            cursor = effective.x()
            if not test_only:
                for item, width in zip(line, widths):
                    px = effective.right() - (cursor - effective.x()) - width + 1
                    item.setGeometry(QRect(QPoint(px, y),
                                           QSize(max(width, 0), line_height)))
                    cursor += width + self._spacing
            y += line_height + self._spacing
        total = y - self._spacing if lines else effective.y()
        return total - rect.y() + margins.bottom()


class _FooterFlowFrame(QFrame):
    """2.8: إطار يطابق ارتفاعه مع التخطيط الملتف داخله.

    ``QFrame`` العادي لا ينقل ``heightForWidth`` للتخطيط الأب، فيبقى بارتفاع
    سطر واحد ويُقص السطر الثاني من الأزرار.
    """

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        layout_obj = self.layout()
        if layout_obj is None:
            return super().heightForWidth(width)
        return layout_obj.heightForWidth(width)

    def sizeHint(self):  # noqa: N802
        layout_obj = self.layout()
        if layout_obj is None:
            return super().sizeHint()
        width = self.width() if self.width() > 0 else super().sizeHint().width()
        return QSize(width, layout_obj.heightForWidth(width))

    def minimumSizeHint(self):  # noqa: N802
        """2.9.4 إصلاح 16: الحد الأدنى للعرض = أوسع زر منفرد، لا عرض الصف.

        العيب المقيس: إعادة ``sizeHint()`` كما هي تُعلن حدًا أدنى للعرض
        يساوي العرض الحالي كاملًا (640px)، فيصير ``layout minSize`` للوحة
        الربط 656px بينما viewport منطقة التمرير 640px. QScrollArea مع
        ``widgetResizable`` لا يقدر على تصغير المحتوى تحت حدّه الأدنى،
        والشريط الأفقي مطفأ (AlwaysOff)، فيُقص الفائض 31px بصمت.
        وفي واجهة يمين-لليسار يقع القص على أطراف الأزرار اليسرى، فقيس
        «ربط الآن» مرئيًا 78% حتى على 1920×1080، و«ضم للصنف الأعلى»
        و«عرض الصورة» 0% على 800×600.

        الحد الأدنى الحقيقي لتخطيط ملتف هو عرض أوسع عنصر فيه: أقل من ذلك
        يُقص العنصر، وما بينه وبين العرض الكامل يُعالج بالالتفاف لأسطر
        إضافية — وهو السلوك المطلوب.
        """
        layout_obj = self.layout()
        if layout_obj is None:
            return super().minimumSizeHint()
        widest = 0
        for index in range(layout_obj.count()):
            item = layout_obj.itemAt(index)
            if item is None:
                continue
            widget = item.widget()
            hint = (widget.sizeHint() if widget is not None
                    else item.sizeHint())
            widest = max(widest, hint.width())
        margins = self.contentsMargins()
        widest += margins.left() + margins.right()
        # الارتفاع يبقى محسوبًا بالعرض الفعلي حتى لا يُقص سطر رأسيًا
        return QSize(widest, self.sizeHint().height())

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        layout_obj = self.layout()
        if layout_obj is None:
            return
        needed = layout_obj.heightForWidth(self.width())
        if needed > 0 and self.minimumHeight() != needed:
            self.setMinimumHeight(needed)
            self.updateGeometry()


class MainWindow(QMainWindow):
    # 2.9.4: يُطلق من خيط تحميل الإكسل الخلفي ليُعاد تصحيح
    # المجلد المنجز على خيط الواجهة. لا يصلح `QTimer.singleShot`
    # هنا لأن الخيط الخلفي بلا حلقة أحداث فيُهمل النداء صامتًا
    # (مقيس: الدالة لم تُستدعَ أبدًا فبقيت الوحدة بلا تصحيح).
    legacy_recheck_requested = Signal()

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
        # 2.9.6 — حماية من انهيار «QThread: Destroyed while thread is still
        # running» (SIGABRT، يُغلق التطبيق فورًا بلا رسالة). إسناد عامل جديد
        # إلى نفس الحقل بينما القديم يعمل يُسقط آخر مرجع بايثون فيدمّره جامع
        # القمامة أثناء عمله. هذه المجموعة تحتفظ بمرجع قوي لكل عامل حتى
        # تُطلق إشارة finished، فيستحيل جمعه وهو يعمل.
        self._live_workers: set = set()
        self._pending_individual_position: tuple[str, int, int] | None = None
        self._individual_preview_active = False
        self._individual_preview_path: Path | None = None
        self._individual_editor_dirty = False
        self._pending_manual_position: tuple[str, int, int] | None = None
        self._pending_manual_source_names: tuple[str, ...] = ()
        self._manual_reference_source_name = ""
        self._result_items_by_name: dict[str, BatchItemResult] = {}
        # نص جاهز لكل صف؛ لا نعيد التطبيع الثقيل عند كل حرف في مربع البحث.
        self._result_search_cache: dict[str, str] = {}
        self._result_filter_timer = QTimer(self)
        self._result_filter_timer.setSingleShot(True)
        self._result_filter_timer.setInterval(80)
        self._result_filter_timer.timeout.connect(self._apply_result_filters)
        self._result_thumbnail_cache: dict[str, QIcon] = {}
        # 2.9.9 — أُلغيت نسبة التشابه من جذورها بطلب المالك، فحُذفت معها كل
        # منطقة البصمات البصرية: كاش LRU بسعة 2000، العامل الخلفي، مؤقّت
        # التسخين، ومجموعات المنتظر/الفاشل. الربط الآن بالباركود والاسم
        # والجيرة واليد وحدها — أدق وأسرع وبلا أي قراءة أقراص زائدة.
        self._individual_edit_source_name = ""
        # 2.9.13 (م-12) — وجهة المحرر الفعلية: اسم الملف المحمّل في
        # `unified_editor` الآن. وهو متغير مستقل عن
        # `_individual_edit_source_name` قصدًا: ذاك يتبع **التحديد**
        # وهذا يتبع **البكسلات**. خلطهما هو أصل فساد البيانات:
        # التحديد يتحوّل فيُحدَّث الأول وتبقى البكسلات للصنف القديم.
        self._editor_loaded_source_name = ""
        self._individual_crop_box: tuple[float, ...] | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(90)
        self._preview_timer.timeout.connect(self._render_selected_preview)
        # 2.9: المقياس التلقائي يُحسب **قبل** بناء الواجهة حتى تُولد كل
        # الأبعاد مقيسة من البداية بدل تصحيحها لاحقًا.
        self._scaled_metrics: list = []
        self._base_stylesheet = ""
        self.ui_scale = ScaleEngine(1.0)
        # 2.9.3: جذر بيانات التسمية يُوصل مرة واحدة عند البدء حتى تُقرأ
        # السياسة المحفوظة حتى لو لم يُحمّل ملف إكسل في هذه الجلسة.
        self.v2_data_root = DATA_ROOT
        self.v2_naming_policy: dict | None = None
        self.v2_bulk_plan: dict | None = None
        try:
            from engine_v2 import integration_v2 as _integ_boot
            _integ_boot.set_naming_data_root(str(DATA_ROOT))
        except Exception as exc:
            print(f"[naming] data root wiring failed: {exc}", file=sys.stderr)
        self._setup_window()
        self._refresh_ui_scale(initial=True)
        self._build_ui()
        self._apply_style()
        self._apply_scaled_metrics()
        self._update_controls()
        # 2.9.10: استعادة حالة خيار دمج الوحدات فور بناء الواجهة،
        # قبل أن يرى المالك النافذة، حتى توافق الخانة ما ستفعله
        # المعالجة فعلًا لا ما تفترضه الواجهة افتراضًا.
        try:
            self._load_join_units_state()
        except Exception as exc:
            print(f"[naming] restore join state failed: {exc}",
                  file=sys.stderr)
        # الإشارة تعبر من خيط تحميل الإكسل إلى خيط الواجهة
        # (Qt.AutoConnection يجعلها مطابورة تلقائيًا عبر الخيوط).
        self.legacy_recheck_requested.connect(
            self._refresh_legacy_after_catalog)
        # إعادة قياس بعد استقرار التخطيط الفعلي للنافذة
        QTimer.singleShot(0, self._refresh_ui_scale)
        # 2.9.6 — تسريع الإقلاع: المحرّك الثقيل لم يعد يُستورد قبل ظهور
        # النافذة، لكن أول دفعة تحتاجه. يُسخَّن في خيط خلفي بعد أن تصير
        # الواجهة مرئية ومستجيبة، فلا يشعر المستخدم بالتحميل في الحالتين.
        QTimer.singleShot(120, self._warm_engine_async)
        # وكذلك تبويب المحرّر: يُبنى بعد أول رسم لا قبله، فيظهر
        # التطبيق أسرع ويبقى فتح التبويب فوريًا عند أول تحرير.
        QTimer.singleShot(180, self._warm_editor_deferred)

    def _warm_engine_async(self) -> None:
        """يبدأ تحميل محرّك الرؤية في الخلفية بعد ظهور الواجهة.

        لا يمسّ خيط الواجهة إطلاقًا: `lazy_engine.warm_up_async` يشتغل في
        خيط عفريت واحد، وأي فشل يُسجَّل ولا يُوقف التطبيق — فالمحرّك
        سيُحمَّل عند أول استعمال حقيقي على أي حال ويُظهر الخطأ عندها.
        """
        def _report(ok: bool, message: str) -> None:
            if not ok:
                print(f"[boot] engine warm-up failed: {message}",
                      file=sys.stderr)

        try:
            _lazy_engine.warm_up_async(_report)
        except Exception as exc:  # pragma: no cover - دفاعي بحت
            print(f"[boot] engine warm-up not started: {exc}", file=sys.stderr)

    def _setup_window(self) -> None:
        self.setWindowTitle(f"{APP_NAME} — {APP_VERSION}")
        # الحد المرن يناسب شاشة 1366×768 حتى مع تحجيم Windows بنسبة 150%؛
        # وتبقى الأقسام الطويلة داخل مناطق تمرير مستقلة بدلاً من الانضغاط.
        # 2.9: الحد الأدنى يتبع المقياس التلقائي. حد صلب 960×600 كان يمنع
        # النافذة من ملاءمة شاشات 800×600 و 1024×600 فريُقص محتواها قسرًا.
        self.setMinimumSize(720, 460)
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
        available = max(360, self.results_page.width() - 20)
        # 2.6: وضع ضيق جدًا — اللوحتان لا تتسعان جنبًا إلى جنب فنرصهما عموديًا
        # (القائمة فوق والصورة تحت) — هذا يلغي التراكب والقص نهائيًا.
        if available < (self.results_upper_widget.minimumWidth()
                        + self.previews_widget.minimumWidth() + 40):
            width_mode = "narrow"
        elif available < 1180:
            width_mode = "compact"
        else:
            width_mode = "wide"
        height_mode = "short" if self.height() < 780 else "tall"
        mode = f"{width_mode}-{height_mode}"
        # 2.7: ارتفاع لوحة الربط يُحدّث مع كل تغيير حجم (خارج شرط الوضع)
        # لأن التفاف أزرار FlowLayout يعتمد على العرض الدقيق — كان
        # الخروج المبكر يترك سقفًا قديمًا يقص آخر زر (ملاحظة المستخدم).
        self._sync_manual_group_height()
        # ومرة بعد استقرار التخطيط — العرض النهائي للوحة قد يتغير
        # بعد إعادة توزيع الـ splitter في هذا الاستدعاء نفسه.
        QTimer.singleShot(0, self._sync_manual_group_height)
        if getattr(self, "_results_splitter_mode", "") == mode:
            return
        self._results_splitter_mode = mode
        self.header_frame.setFixedHeight(52 if height_mode == "short" else 68)
        if hasattr(self, "result_subtitle"):
            self.result_subtitle.setVisible(height_mode != "short")
        for card in getattr(self, "summary_cards", ()):
            # لا نثبت العرض حتى لا تُقص العناوين — ارتفاع ثابت فقط
            # 2.9: عند شحّ الارتفاع تتحول البطاقة لترتيب أفقي فيكفيها سطر
            # واحد وتبقى التسمية مقروءة، بدل بترها كما كان يحدث.
            scale = getattr(self, "ui_scale", None)
            factor = scale.factor if scale is not None else 1.0
            card.set_compact(height_mode == "short" or factor < 0.85)
            base = 46 if height_mode == "short" else 52
            target = scale.px(base) if scale is not None else base
            card.setFixedHeight(max(card.sizeHint().height(), target))
            card.setMinimumWidth(card.minimumWidth())
            # 2.9: السقف يتسع للترتيب الأفقي (رقم + تسمية) بلا بتر
            card.setMaximumWidth(160 if card._compact else 120)
        if width_mode == "narrow":
            self.results_splitter.setOrientation(Qt.Vertical)
            page_h = max(500, self.results_page.height() - 40)
            self.results_splitter.setSizes(
                [int(page_h * 0.45), int(page_h * 0.55)])
        else:
            self.results_splitter.setOrientation(Qt.Horizontal)
            list_share = 0.40 if width_mode == "compact" else 0.36
            list_width = max(self.results_upper_widget.minimumWidth(),
                             int(available * list_share))
            preview_width = max(self.previews_widget.minimumWidth(),
                                available - list_width)
            self.results_splitter.setSizes([list_width, preview_width])
        if hasattr(self, "output_preview"):
            minimum_preview_height = 260 if height_mode == "short" else 320
            self.output_preview.viewer.setMinimumHeight(minimum_preview_height)
            self.source_preview.viewer.setMinimumHeight(minimum_preview_height)

    def _sync_manual_group_height(self) -> None:
        """2.7: امنح لوحة الربط ارتفاعها الفعلي بعد التفاف الأزرار.

        صف الأزرار يستخدم FlowLayout فيزداد ارتفاعه كلما ضاق العرض،
        وsizeHint وحده لا يعكس ذلك — فنحسب heightForWidth عند العرض
        الحالي حتى لا يُقص آخر زر على الشاشات الضيقة.
        """
        if not hasattr(self, "manual_group"):
            return
        layout_obj = self.manual_group.layout()
        margins = self.manual_group.contentsMargins()
        inner_width = max(self.manual_group.width()
                          - margins.left() - margins.right(), 200)
        # ملاحزة 2.9.3: جُرّب الاعتماد على heightForWidth وحده فارتفع
        # الفشل المقيس من 9 إلى 18: الرقم يأتي أقل من الحاجة الحقيقية
        # فيختفي شريط التمرير مع بقاء العجز. فالـmax() مع sizeHint لازم.
        natural_height = self.manual_group.sizeHint().height()
        if layout_obj is not None and layout_obj.hasHeightForWidth():
            hfw = layout_obj.heightForWidth(inner_width)
            natural_height = max(natural_height,
                                 hfw + margins.top() + margins.bottom())
        # 2.9: لوحة الربط لها الأولوية على الجدول عند شحّ الارتفاع.
        # السبب: الجدول قابل للتمرير فلا يفقد المستخدم شيئًا بتقصيره، أما
        # أزرار الربط («حذف الصورة»، «حقائق التغذية») فتخرج خارج المنطقة
        # المرئية تمامًا فتصبح غير قابلة للوصول — وهذا ما رصده المستخدم.
        self.manual_group.setMinimumHeight(natural_height)
        self.manual_group.setMaximumHeight(natural_height + 12)
        self._rebalance_list_pane(natural_height)

    def _set_product_name_text(self, full_text: str) -> None:
        """2.9.1: يعرض اسم الصنف بلا قطع بصري مهما ضاقت الشاشة.

        المشكلة المقيسة على 800×600: النص الافتراضي يحتاج 84px بالالتفاف
        (أربعة أسطر) ولا يجد إلا 27px، فيُقطع نصف السطر الأخير بصريًا
        دون أي مؤشر برمجي — وهو ما رّصده المستخدم في اللقطة.

        الحل: نقيس كم سطرًا يتسع فعليًا في الارتفاع المتاح، ونلائم النص
        لينتهي بـ«…» عند حدّ السطر المتاح بدل أن يُقطع حرفيًا من الأسفل.
        النص الكامل يبقى دائمًا في التلميح، فلا تُفقد معلومة.
        """
        label = getattr(self, "selected_product_label", None)
        if label is None:
            return
        self._product_name_full = full_text
        label.setToolTip(full_text)
        width = label.width()
        if width <= 10:
            label.setText(full_text)
            return
        metrics = label.fontMetrics()
        line_h = max(1, metrics.lineSpacing())
        avail_h = label.height()
        if avail_h <= 0:
            parent_card = getattr(self, "selected_product_card", None)
            avail_h = parent_card.height() if parent_card is not None else line_h * 2
        max_lines = max(1, int(avail_h // line_h))
        rect = metrics.boundingRect(
            0, 0, width, 10000, int(Qt.TextWordWrap), full_text)
        if rect.height() <= avail_h:
            label.setText(full_text)
            return
        # لا يتسع: نُلائم النص لأكبر عدد أسطر متاح بإنهاء لطيف
        words = full_text.split()
        fitted = full_text
        for drop in range(1, len(words)):
            candidate = " ".join(words[: len(words) - drop]) + "…"
            probe = metrics.boundingRect(
                0, 0, width, 10000, int(Qt.TextWordWrap), candidate)
            if probe.height() <= max_lines * line_h:
                fitted = candidate
                break
        else:
            fitted = metrics.elidedText(full_text, Qt.ElideRight, width)
        label.setText(fitted)

    def _rebalance_list_pane(self, manual_height: int) -> None:
        """2.9: يوزّع ارتفاع لوحة القائمة بين الجدول ولوحة الربط بلا قص.

        المشكلة المقيسة: على 1024×600 المتاح 369px بينما تطلب العناصر 496px
        (عنوان 21 + مرشحات 36 + جدول 174 + ربط 265)، فيقص Qt آخر ما في
        العمود — أي سطر أزرار الربط الأخير — فيختفي كليًا.

        الحل: نحسب ما يتبقى للجدول بعد حجز حاجة لوحة الربط كاملة، ونضبط
        الحد الأدنى للجدول على هذا الباقي (بأرضية مقروءة). إن لم يكفِ
        المتاح حتى لذلك، نُفعّل تمريرًا رأسيًا حول لوحة الربط فتبقى كل
        الأزرار قابلة للوصول بالتمرير بدل أن تُقتطع.

        2.9.1 — تصحيح جذري: الحساب السابق قدّر ارتفاع صف العنوان برقم ثابت
        (24px)، لكن الصف أصبح ملتفًا فارتفاعه الحقيقي أكبر. فمُنحت لوحة الربط
        284px بينما المتاح فعليًا 268px، فقُصّ صفها الأخير 16px عند حدّ
        ``resultsListPane``. الآن نقيس **الهندسة الفعلية** بعد التخطيط:
        موضع لوحة الربط داخل اللوحة الأم هو المرجع، فلا تقدير ولا تخمين،
        ويصح الحساب على أي مقياس وأي التفاف للنصوص.
        """
        pane = getattr(self, "results_upper_widget", None)
        table = getattr(self, "results_table", None)
        holder = getattr(self, "manual_scroll", None)
        if pane is None or table is None:
            return
        available = pane.height()
        if available <= 0:
            return
        layout_obj = pane.layout()
        margins = layout_obj.contentsMargins() if layout_obj else None
        chrome = (margins.top() + margins.bottom()) if margins else 20
        spacing = layout_obj.spacing() if layout_obj else 7
        # 2.9.2 إصلاح 2: الأرضية من المحتوى (صنفان كاملان) لا من 96 مقيسة،
        # لأن 96 × 0.620 = 60px وهو أقل من صف واحد فيقبل Qt قصّ الجدول.
        floor = self._useful_table_floor()

        # القياس الحقيقي: كم بكسل يفصل أعلى لوحة الربط عن أعلى اللوحة الأم؟
        # هذا يشمل العنوان الملتف والمرشحات والجدول والفواصل — بلا تقدير.
        offset = -1
        if holder is not None and holder.isVisible():
            try:
                offset = holder.mapTo(pane, QPoint(0, 0)).y()
            except Exception:
                offset = -1
        if offset >= 0:
            # ما قبل لوحة الربط مقيس فعليًا؛ نطرح منه ارتفاع الجدول الحالي
            # لنعرف الثابت (العنوان + المرشحات + الفواصل) ثم نعيد التوزيع.
            static_above = max(0, offset - table.height() - spacing)
            bottom_reserve = (margins.bottom() if margins else 10) + spacing
            room = available - static_above - bottom_reserve - manual_height
        else:
            header_h = 0
            for attribute in ("result_search_edit",):
                widget = getattr(self, attribute, None)
                if widget is not None:
                    header_h += widget.sizeHint().height()
            header_h += 24
            static_above = chrome + header_h + (spacing * 3)
            bottom_reserve = 0
            room = available - static_above - manual_height

        if room >= floor:
            table.setMinimumHeight(room)
            self._set_manual_scroll_enabled(False)
        else:
            # حتى بأصغر جدول مقبول لا يتسع العمود: نمرر لوحة الربط ضمن
            # المساحة المتبقية الحقيقية بعد حجز الجدول الأدنى.
            #
            # 2.9.4 محاولتان مرفوضتان موّثقتان (لمنع تكرارهما):
            # 1) إنزال أرضية الجدول لصنف واحد عند الشدة — يُصفّر القص
            #    لكنه ينقل الجدول من 4 صفوف إلى صف واحد.
            # 2) فرض ``setMaximumHeight`` على الجدول لتحرير الفائض — أفسد
            #    التوزيع على كل الدقات (القص 0 ← 12، وشمل 1920×1080)
            #    لأن تقييد الحد الأقصى يمنع QSplitter من التوزيع الطبيعي.
            # المعتمد: حجز الأرضية فقط وترك الباقي للوحة الربط.
            table.setMinimumHeight(floor)
            usable = available - static_above - bottom_reserve - floor
            self._set_manual_scroll_enabled(True, usable)

    def _set_manual_scroll_enabled(self, enabled: bool, height: int = 0) -> None:
        """2.9: يفعّل/يطفئ التمرير الرأسي حول لوحة الربط عند الشدة القصوى."""
        holder = getattr(self, "manual_scroll", None)
        if holder is None:
            return
        if enabled:
            holder.setWidgetResizable(True)
            # 2.9.1: الأرضية تتبع المقياس لا رقمًا صلبًا (80px). والأهم: لا
            # نجبر الحاوية على ارتفاع أكبر مما تملكه اللوحة الأم فعليًا، لأن
            # فرض حد أدنى غير متوفر هو ما دفع Qt لقطع أزرار الصف الأخير
            # بدل إظهار شريط تمرير.
            scale = getattr(self, "ui_scale", None)
            base_floor = scale.px(80) if scale is not None else 80
            target = max(int(height), base_floor)
            holder.setMinimumHeight(0)
            holder.setMaximumHeight(target)
            holder.setMinimumHeight(min(target, base_floor))
            holder.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        else:
            # 2.9.3 إصلاح 8: الإطفاء القاطع (AlwaysOff) يخفي الشريط حتى
            # حين يبقى عجز صغير (قيس: 4px على 1920×1080) فيتعذر الوصول
            # لأسفل اللوحة بلا أي مؤشر. AsNeeded لا يظهر شريطًا متى
            # اتسع المحتوى، فهو أأمن من الإخفاء القاطع في كل الأحوال.
            holder.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            natural = self.manual_group.minimumHeight()
            holder.setMinimumHeight(natural)
            holder.setMaximumHeight(natural + 12)

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        if (
            hasattr(self, "workflow_pages")
            and hasattr(self, "results_page")
            and self.workflow_pages.currentWidget() is self.results_page
        ):
            self._update_results_splitter_for_width()
        # 2.9: المقياس التلقائي أولًا — أي حجم جديد (حتى الانتقال لشاشة
        # أخرى بدقة مختلفة) يُعيد ضبط الخطوط والحشوات والأبعاد معًا.
        self._refresh_ui_scale()
        # 2.5: إعادة ترتيب بطاقات أدوات المحرر حسب عرض النافذة — بلا قص ولا تمرير
        self._relayout_editor_tool_cards()
        # إعادة تموضع التلميح العائم حتى يبقى في الشريط السفلي بلا تداخل.
        hint = getattr(self, "tap_link_hint", None)
        if hint is not None and hint.isVisible():
            self._position_tap_hint()

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
        # 2.9.7: أزرار الإعداد كانت متغيرات محلية بلا مرجع على self،
        # فلم يكن لفحص الأزرار الآلي أي سبيل للوصول إليها — فكان يتخطّاها
        # بصمت ويُعلن نجاحًا، مع أنّها أول ما يلمسه المستخدم.
        catalog_button = self.select_catalog_button = QPushButton(
            "اختيار ملف Excel")
        catalog_button.setObjectName("secondaryButton")
        catalog_button.clicked.connect(self._select_catalog)
        catalog_layout.addWidget(self.catalog_edit)
        catalog_layout.addWidget(self.catalog_status_label)
        catalog_layout.addWidget(catalog_button)
        # 2.9.3: وصول مباشر لسياسة التسمية وأداة إعادة التسمية.
        # النافثتان موجودتان في v2_ui منذ البداية لكن لم يكن لهما
        # أي زر يفتحهما، فكان المستخدم يقرأ عن «قوالب المتاجر» بلا منفذ.
        naming_row = QHBoxLayout()
        naming_row.setSpacing(8)
        self.naming_policy_button = QPushButton("⚙ سياسة الوحدات والتسمية")
        self.naming_policy_button.setObjectName("secondaryButton")
        self.naming_policy_button.setToolTip(
            "اختر مرة واحدة كيف تُبنى أسماء الملفات لكل الأصناف:\n"
            "سياسة الوحدات، نمط الترقيم، وقوالب المتاجر الجاهزة —\n"
            "والوحدة تُقرأ حرفيًا من الإكسل دون تغيير.")
        self.naming_policy_button.clicked.connect(self._open_naming_policy)
        self._register_metric(self.naming_policy_button, "min_height", 34)
        # 2.9.5 (قرار المالك — منفّذ بالكامل): منفذ التعديل القديم
        # (نافذة التسمية المستقلة) لم يُخفَ فقط بل **حُذف من الجذور**:
        # النافذة ودالة فتحها وزرها وأنماطها — لأن الترك يعني وجود
        # الوظيفة في مكانين. المنفذ الوحيد الآن هو فتح المجلد المنجز
        # **داخل نفس استوديو المراجعة والربط**: «كل شيء يعمل في
        # واجهة واحدة». تبديل لا إضافة حتى لا ينكسر توازن الأزرار
        # المُعاير على 800×600.
        self.open_legacy_button = QPushButton("فتح مجلد منجز")
        self.open_legacy_button.setObjectName("secondaryButton")
        self.open_legacy_button.setToolTip(
            "افتح مجلد صور منجزة سابقًا في نفس استوديو المراجعة:\n"
            "تُجمّع الصور برقم الصنف، وتُصحّح التسميات من الإكسل فورًا\n"
            "(الواجهة بلا رقم، والبقية -2 ،-3 ،-4)، ثم تضغط ★ على أي صورة\n"
            "لتجعلها صورة الواجهة. حمّل الإكسل أولاً لتصحيح الوحدات.")
        self.open_legacy_button.clicked.connect(self._open_legacy_folder)
        self._register_metric(self.open_legacy_button, "min_height", 34)
        naming_row.addWidget(self.naming_policy_button)
        naming_row.addWidget(self.open_legacy_button)
        naming_row.addStretch(1)
        catalog_layout.addLayout(naming_row)
        # 2.9.10 (أمر المالك): خيار دمج الوحدات في **الواجهة الرئيسية**
        # لا في نافذة السياسة وحدها: «في الواجهة الرئيسية أفضل، قبل
        # عمل أي شيء». النافذة الكاملة تبقى للخيارات المتقدمة، والاثنتان
        # تقرأان وتكتبان ملف naming_settings.json نفسه فلا تتعارضان.
        self.join_units_check = QCheckBox(
            "وحدة Excel مفردة فقط في الاسم النهائي (الدمج معطّل)")
        self.join_units_check.setObjectName("joinUnitsCheck")
        self.join_units_check.setChecked(False)
        self.join_units_check.setEnabled(False)
        self.join_units_check.setToolTip(
            "الاسم النهائي يستخدم وحدة Excel واحدة فقط: 10011205_حبه\n"
            "عند اختيار الباركود تُؤخذ الوحدة من سجل الباركود المطابق.\n"
            "لا تُدمج حبه_شدة_كرتون ولا تُنشأ نسخ إضافية للوحدات.\n"
            "صورة الواجهة (★) بلا رقم، ثم -1 ثم -2.")
        self.join_units_check.toggled.connect(self._on_join_units_toggled)
        catalog_layout.addWidget(self.join_units_check)
        # خيار المرجع في الواجهة الرئيسية، بعد Excel وسياسة الوحدة مباشرة
        # وقبل إضافة الصور: اختيار واحد يسري على الدفعة الجديدة والمجلد
        # المنجز السابق من ملف الإعداد نفسه.
        reference_row = QHBoxLayout()
        reference_label = QLabel("الاسم النهائي للصور (من Excel):")
        self.reference_mode_combo = QComboBox()
        self.reference_mode_combo.setObjectName("referenceModeCombo")
        self.reference_mode_combo.addItem("رقم الصنف + وحدة Excel", "item_code")
        self.reference_mode_combo.addItem("باركود خطي مثبت من Excel + الوحدة", "barcode")
        self.reference_mode_combo.setToolTip(
            "رقم الصنف: 10011205_حبه ثم 10011205_حبه-1\n"
            "باركود Excel: 6287021750464_حبه ثم 6287021750464_حبه-1\n\n"
            "لا يقبل إلا باركودًا خطيًا رقميًا يطابق سجل Excel. عند تعدد\n"
            "باركودات الصنف للوحدة نفسها، يبقى الاسم للمراجعة ولا يُخمن.\n"
            "يسري الاختيار على الصور الجديدة و«فتح مجلد منجز».")
        self.reference_mode_combo.currentIndexChanged.connect(self._on_reference_mode_changed)
        reference_row.addWidget(reference_label)
        reference_row.addWidget(self.reference_mode_combo, 1)
        catalog_layout.addLayout(reference_row)
        self.reference_mode_hint = QLabel(
            "اختره قبل إضافة الصور أو فتح مجلد منجز؛ لا يغيّر الربط، بل المرجع الظاهر في الاسم فقط.")
        self.reference_mode_hint.setObjectName("referenceModeHint")
        self.reference_mode_hint.setWordWrap(True)
        catalog_layout.addWidget(self.reference_mode_hint)
        self.barcode_review_help = QLabel(
            "طريقة الباركود: إذا قرأت الصورة باركودًا خطيًا وطابق Excel، "
            "يُحفظ فورًا باسم باركود_الوحدة. أما إذا كان رقم الصنف يملك "
            "أكثر من باركود صحيح ولم تُحسم الصورة، تبقى باسم رقم_الصنف_الوحدة "
            "ويُحفظ بجانب الصور ملف barcode_review_multiple_candidates.csv للمراجعة. "
            "لا يُختار باركود عشوائي ولا يُستخدم QR.")
        self.barcode_review_help.setObjectName("barcodeReviewHelp")
        self.barcode_review_help.setWordWrap(True)
        self.barcode_review_help.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.barcode_review_help.setStyleSheet(
            "QLabel#barcodeReviewHelp { background:#eff6ff; color:#1e3a5f; "
            "border:1px solid #bfdbfe; border-radius:6px; padding:8px; }")
        catalog_layout.addWidget(self.barcode_review_help)
        # معاينة حيّة للاسم الناتج: المالك يرى أثر الخيار بعينه
        # قبل تشغيل المعالجة بدل أن يكتشفه في 991 ملفًا بعد فوات الأوان.
        self.naming_preview_label = QLabel("")
        self.naming_preview_label.setObjectName("namingPreview")
        self.naming_preview_label.setWordWrap(True)
        self.naming_preview_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse)
        catalog_layout.addWidget(self.naming_preview_label)
        layout.addWidget(catalog_group)

        images_group = QGroupBox("2. صور المنتجات")
        images_layout = QVBoxLayout(images_group)
        buttons = QHBoxLayout()
        add_images = self.select_images_button = QPushButton("إضافة صور")
        add_images.setObjectName("secondaryButton")
        add_images.clicked.connect(self._select_images)
        add_folder = self.select_folder_button = QPushButton("إضافة مجلد")
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
        self._register_metric(self.image_list, "min_height", 170)
        self.image_list.setMaximumHeight(250)
        self.image_list.files_dropped.connect(self._add_paths)
        images_layout.addWidget(self.image_list, 1)
        list_footer = QHBoxLayout()
        self.image_count_label = QLabel("0 صورة")
        remove_selected = self.remove_images_button = QPushButton(
            "حذف المحدد")
        remove_selected.setObjectName("textButton")
        remove_selected.clicked.connect(self._remove_selected_images)
        clear_all = self.clear_images_button = QPushButton("مسح الكل")
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
        # إصلاح الانعكاس: في واجهة RTL يظهر المقبض معكوسًا — نثبته LTR دائمًا
        self.enhancement_strength_slider.setLayoutDirection(Qt.LeftToRight)
        self.enhancement_strength_slider.setInvertedAppearance(False)
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
        # 101 في OpenCV = WebP lossless حقيقي (القيمة 100 تبقى ضغطًا مفقودًا).
        # قياسنا: lossless يعطي PSNR ≈ 361 بحجم أصغر من 100 (PSNR ≈ 52)
        # لصور المنتجات ذات النصوص — أي جودة أعلى وحجم أقل، بلا مقايضة.
        self.webp_quality_combo.addItem("فائقة — بلا فقدان (lossless)", 101)
        self.webp_quality_combo.addItem("قصوى 97", 97)
        self.webp_quality_combo.addItem("ممتازة 94", 94)
        self.webp_quality_combo.addItem("اقتصادية 90", 90)
        self.webp_quality_combo.setCurrentIndex(0)
        self.webp_quality_combo.setToolTip(
            "فائقة (بلا فقدان): تطابق تام مع الصورة المعالجة — كتابات المنتج\n"
            "والحقائق الغذائية تبقى بحدّتها الكاملة. مقاسنا يظهر أنها أيضًا\n"
            "أصغر حجمًا من الجودة 100 لصور المنتجات، فهي الخيار الأفضل دائمًا."
        )
        framing_row.addWidget(self.webp_quality_combo, 1)
        options_layout.addLayout(framing_row)
        quality_row = QHBoxLayout()
        self.blur_dates_check = QCheckBox("طمس تواريخ الإنتاج/الانتهاء تلقائيًا")
        self.blur_dates_check.setObjectName("blurDates")
        self.blur_dates_check.setChecked(True)
        self.blur_dates_check.setToolTip(
            "يكشف التواريخ المطبوعة على العبوة (EXP/PROD وأرقام التواريخ) ويطمسها\n"
            "بتمويه طفيف بلون المنتج نفسه — دون المساس بالحقائق الغذائية أو الباركود.\n"
            "إن لم يُكشف تاريخ تلقائيًا، استخدم أداة (طمس تاريخ) اليدوية في المحرر."
        )
        quality_row.addWidget(self.blur_dates_check)
        self.text_polish_check = QCheckBox("وضوح فائق للكتابات (ذكي)")
        self.text_polish_check.setObjectName("textPolish")
        self.text_polish_check.setChecked(True)
        self.text_polish_check.setToolTip(
            "محرك حدة ذكي يتعرف على مناطق النصوص والجداول على المنتج\n"
            "ويعزز وضوحها بعد المعالجة — لا يحفظ إلا إذا تحسّنت المقروئية فعليًا"
        )
        quality_row.addWidget(self.text_polish_check)
        options_layout.addLayout(quality_row)

        dimensions = QLabel(
            "WebP ‏800×700 • خلفية بيضاء عند العزل • "
            "الاسم: رقم_الصنف_الوحدة (صورة واحدة) أو رقم_الصنف_الوحدة-1/-2 (عدة صور) — "
            "قوالب متاجر جاهزة وتخصيص كامل من نافذة التسمية"
        )
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
        self._register_metric(review_top_bar, "min_height", 58)
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
            # 2.9: بلا عرض ثابت — العرض يتبع النص حتى لا تُبتر التسمية،
            # والارتفاع يُضبط لاحقًا في _update_results_splitter_for_width.
            card.setFixedHeight(46)
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
        # 2.9.2 إصلاح 1: المصغرة تتبع المقياس لا رقمًا صلبًا. المقيس أن 80px الثابتة
        # تفرض ارتفاع صف 124px على كل المقاسات، فيصبح ارتفاع الجدول
        # المتاح 26px على 800×600 ‹ صف واحد ‹ فلا يظهر رقم الصنف ولا الباركود.
        self._register_metric(self.results_table, "icon", 80)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setWordWrap(True)
        self.results_table.setTextElideMode(Qt.ElideNone)
        self.results_table.verticalHeader().setVisible(False)
        # 2.9.2 إصلاح 1: ارتفاع الصف يُشتق من المحتوى (المصغرة + سطري نص)
        # لا من 88/96 الصلبتين — يضبطه ``_sync_table_row_height`` بعد كل مقياس.
        self._sync_table_row_height()
        self.results_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.results_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.results_table.verticalScrollBar().setSingleStep(28)
        self.results_table.setToolTip(
            "حدد صفًا واحدًا للمعاينة أو عدة صفوف لربط صور الصنف نفسه؛ الاسم والباركود ظاهرَان دون أعمدة مزدحمة"
        )
        table_header = self.results_table.horizontalHeader()
        # 2.9.2: الحد الأدنى للقطاع كان 82px صلبة، فعلى 800×600 منع مجموع
        # الأعمدة من النزول دون 246px ففاض عن نافذة العرض (259px) رغم
        # كل الانكماش، فظهر شريط تمرير أفقي ممنوع أو قُطِع المحتوى.
        table_header.setMinimumSectionSize(36)
        table_header.setSectionResizeMode(0, QHeaderView.Fixed)
        table_header.setSectionResizeMode(1, QHeaderView.Fixed)
        table_header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.results_table.setColumnWidth(0, 168)
        self.results_table.setColumnWidth(1, 148)
        # 2.6: على الشاشات الضيقة كان عمود «اسم الصنف» يختفي لأن العمودين الثابتين
        # يستهلكان كامل العرض — نعيد توزيع الأعمدة ديناميكيًا مع ضمان حد أدنى للاسم.
        self.results_table.viewport().installEventFilter(self)
        self._adjust_results_table_columns()
        self.results_table.itemSelectionChanged.connect(self._show_selected_preview)
        self.results_table.doubleClicked.connect(self._open_selected_file)
        # 2.9.2 إصلاح 2: الحد الأدنى يُشتق من المحتوى (ترويسة + صفان) لا
        # من 250 المرجعية، فيُضمن رؤية صنفين كاملين على أي شاشة.
        self.results_table.setMinimumHeight(self._useful_table_floor())
        self._continue_build_results_page(layout)
        return panel

    # ------------------------------------------------------------------
    # 2.9.2 — جدول المراجعة: أربع دوال تشتق الأبعاد من المحتوى
    # ------------------------------------------------------------------
    def _sync_table_row_height(self) -> None:
        """يشتق ارتفاع صف الجدول من المصغرة وارتفاع سطر الخط.

        المشكلة المقيسة: ``setMinimumSectionSize(88)`` و``setDefaultSectionSize(96)``
        رقمان صلبان أنتجا ارتفاع صف 124px على كل المقاسات دون استثناء،
        فعلى 800×600 لم يتسع الجدول (26px) لأي صف، واختفى رقم الصنف
        والباركود كليًا — وهي الوظيفة الأساسية للشاشة.

        الحل: الصف = ما يلزم لإظهار المصغرة أو سطري نص (رقم الصنف فوق
        الباركود)، أيّهما أكبر، مع هامش تنفّس. فيتبع المقياس تلقائيًا
        لأن المصغرة مسجلة في ``_scaled_metrics`` والخط يتقلص مع المعامل.
        """
        table = getattr(self, "results_table", None)
        if table is None:
            return
        line_h = table.fontMetrics().height()
        # المحتوى الواجب: سطران لـ«رقم الصنف \n الباركود». هذا هو الأساس
        # الوظيفي الذي لا يجوز التنازل عنه، والمصغرة تابعة لا قائدة.
        text_need = line_h * 2 + max(4, line_h // 3)

        # ما يتسع له الجدول فعليًا لصفين كاملين؛ فإن ضاق قلّصنا المصغرة
        # لا النص — فرقم الصنف والباركود أولى من حجم الصورة.
        header_h = table.horizontalHeader().height() or (line_h + 12)
        budget = table.height() - header_h - table.frameWidth() * 2 - 2
        icon_h = table.iconSize().height()
        if budget > 0:
            per_row = budget // 2
            if per_row < icon_h + max(4, line_h // 3):
                # المصغرة تنكمش لتسمح بصفين، ولا تنزل تحت حد التمييز البصري.
                shrunk = max(28, per_row - max(4, line_h // 3))
                if shrunk < icon_h:
                    icon_h = shrunk
                    table.setIconSize(QSize(shrunk, shrunk))

        content = max(icon_h + max(4, line_h // 3), text_need)
        row_h = int(content)
        header = table.verticalHeader()
        header.setSectionResizeMode(QHeaderView.Fixed)
        header.setMinimumSectionSize(max(24, line_h + 4))
        header.setDefaultSectionSize(row_h)
        for row in range(table.rowCount()):
            table.setRowHeight(row, row_h)

    def _useful_table_floor(self) -> int:
        """أقل ارتفاع يُرى فيه **صنفان كاملان**، مشتقًا من المحتوى.

        يستبدل الرقمين المرجعيين 250 (حد الجدول) و 96 (أرضية التوزيع).
        مع معامل 0.620 كان 250 يصير 155px و 96 يصير 60px، وكلاهما أقل من
        صف واحد، فيقبل Qt أن يقص الجدول إلى شريحة عمياء.

        2.9.4: الأرضية تبقى صنفين على كل المقاييس. جُرّب إنزالها لصنف
        واحد عند الشدة لتحرير مساحة لأزرار الربط، فأنقص الجدول من
        4 صفوف إلى صف واحد — ثمن باهظ. الحل المعتمد بدله: تقاسم الفائض
        عن الأرضية في ``_rebalance_list_pane`` بدل استحواذ الجدول عليه.
        """
        table = getattr(self, "results_table", None)
        if table is None:
            return 96
        row_h = table.verticalHeader().defaultSectionSize()
        if row_h <= 0:
            row_h = max(table.iconSize().height(), table.fontMetrics().height() * 2)
        header_h = table.horizontalHeader().height()
        if header_h <= 0:
            header_h = table.fontMetrics().height() + 12
        frame = table.frameWidth() * 2
        return int(header_h + row_h * 2 + frame + 2)

    def _apply_status_text_mode(self, show_text: bool) -> None:
        """يُسقط نص الحالة عند الشدة ويترك الأيقونة والتلميح.

        الحسم البنيوي: على 800×600 المتاح 259px والأرضيات الثلاث تلزم 312px
        ، أي عجز 53px لا يُخفى بأي ترتيب انكماش. فيُستغنى عن النص لمصلحة
        مؤشر بصري ملوّن مع ``toolTip`` كامل — وهو المفضّل المسجل للمالك.
        النص الأصلي يُحفظ في ``Qt.UserRole + 1`` فيعود تلقائيًا عند التوسّع.
        """
        table = getattr(self, "results_table", None)
        if table is None:
            return
        if getattr(self, "_status_text_visible", None) == show_text:
            return
        self._status_text_visible = show_text
        for row in range(table.rowCount()):
            cell = table.item(row, 0)
            if cell is None:
                continue
            if show_text:
                saved = cell.data(Qt.UserRole + 1)
                if saved:
                    cell.setText(str(saved))
            else:
                if cell.text():
                    cell.setData(Qt.UserRole + 1, cell.text())
                cell.setText("")

    def _apply_link_button_text_mode(self, show_text: bool) -> None:
        """2.9.4 إصلاح 17: يُسقط نصوص أزرار الربط عند الشدة القصوى.

        الحسم البنيوي المقيس: على 800×600 تحتاج لوحة الربط 205px ولا
        تجد إلا 115px، وفائض الجدول كله 48px — فحتى الاستيلاء عليه
        كاملًا يبلغ 163px لا 205px. لذلك فشلت كل محاولات تقليص الجدول.

        العيب الحقيقي أفقي: عرض الحاوية 255px وأضيق زر يحتاج 93px
        بنصه العربي الكامل، فلا يسع السطر إلا زرين ⊇ تسعة أزرار
        تلتف على خمسة أسطر = 139px. وعلى 1920×1080 العرض 623px فيسع
        أربعة أزرار/سطر ⊇ ثلاثة أسطر فقط.

        فالحل تقليل العروض لا الارتفاعات: رمز بدل النص مع ``toolTip``
        يبدأ بالاسم الكامل — وهو المفضل المسجل للمالك صراحة:
        «مؤشر بصري مع تلميح بدل النص المباشر عند ضيق المساحة».
        يُطبّق على الشدة القصوى وحدها فتبقى النصوص كاملة في كل
        الدقات الأخرى، وتعود حرفيًا عند توسيع النافدة.
        """
        pairs = getattr(self, "_link_button_glyphs", None)
        if not pairs:
            return
        if getattr(self, "_link_text_visible", None) == show_text:
            return
        self._link_text_visible = show_text
        for button, glyph in pairs:
            try:
                full = getattr(button, "_full_label", button.text())
                if show_text:
                    button.setText(full)
                    button.setMinimumWidth(
                        getattr(button, "_full_min_width", 0))
                else:
                    button.setText(glyph)
                    # العرض الأدنى من الرمز نفسه لا من النص المُسقط
                    glyph_w = button.fontMetrics().horizontalAdvance(glyph)
                    button.setMinimumWidth(glyph_w + 18)
            except Exception:
                continue
        # التخطيط الملتف يُعيد الحساب من العروض الجديدة، واللوحة
        # تُعيد مزامنة ارتفاعها من الارتفاع-للعرض الناتج.
        host = getattr(self, "_link_flow_host", None)
        if host is not None:
            try:
                lay = host.layout()
                if lay is not None:
                    lay.invalidate()
                host.updateGeometry()
            except Exception:
                pass

    def _fit_table_headers(self) -> None:
        """يلائم عناوين الترويسة للعروض الفعلية ببدائل متدرّجة.

        الميزانية ``width - 24`` لا ``width - 10``: الخصم المتفائل أبقى «الصنف /
        الباركود» مبتورة رغم اتساعها حسابيًا، لأن الترويسة تحجز لمؤشر
        الترتيب والهامش الداخلي.
        """
        table = getattr(self, "results_table", None)
        if table is None:
            return
        alternatives = (
            ("الصورة / الحالة", "الصورة", "صورة"),
            ("الصنف / الباركود", "الصنف والباركود", "الصنف", "صنف"),
            ("اسم الصنف", "الاسم", "اسم"),
        )
        fm = table.horizontalHeader().fontMetrics()
        for col, options in enumerate(alternatives):
            budget = table.columnWidth(col) - 24
            chosen = options[-1]
            for option in options:
                if fm.horizontalAdvance(option) <= budget:
                    chosen = option
                    break
            header_item = table.horizontalHeaderItem(col)
            if header_item is not None:
                header_item.setText(chosen)
                header_item.setToolTip(options[0])

    def _adjust_results_table_columns(self) -> None:
        """يوزّع أعمدة جدول النتائج بحيث يبقى اسم الصنف مقروءًا دائمًا.

        على العروض الواسعة: الصورة 168 + الباركود 148 والاسم يتمدد.
        على العروض الضيقة: ينكمش عمودا الصورة والباركود تدريجيًا ليضمنا
        لـ «اسم الصنف» حدًا أدنى مقروءًا (≥150px) مع التفاف النص على أسطر.
        """
        table = getattr(self, "results_table", None)
        if table is None:
            return
        available = table.viewport().width()
        if available <= 0:
            return
        # 2.9.2 إصلاح 3: العروض تُشتق من ``fontMetrics`` لا من أرقام صلبة.
        # الرقم الصلب 168/148/150 تختل نسبته عند طرفي المدى، لأن الخط
        # يتقلص بالجذر والمسافات خطيًا.
        fm = table.fontMetrics()
        icon_side = table.iconSize().width()
        # عمود الباركود: أطول محتوى حقيقي هو باركود 13 رقمًا.
        code_w = fm.horizontalAdvance("6281006123456") + 10
        # عمود الاسم: عينة اسم متوسط تلتف على سطرين.
        name_min = fm.horizontalAdvance("منتج غذائي متوسط") + 16
        # عمود الصورة/الحالة: المصغرة + أطول نص حالة + هوامش.
        status_w = max(fm.horizontalAdvance(text) for text in STATUS_TEXT.values())
        icon_w = icon_side + status_w + 14
        icon_floor = icon_side + 8          # المصغرة وحدها بلا نص
        code_floor = fm.horizontalAdvance("6281006123456") + 6

        if available < icon_w + code_w + name_min:
            # انكماش متدرج: عمود الاسم يُقلّص **أخيرًا لا أولًا** — أثبت
            # القياس البصري أن تقليصه أولًا بحجة أنه «يلتف» يسحقه إلى 62px
            # فينتهي بـ«…». فنبدأ بإسقاط نص الحالة ثم الباركود.
            deficit = (icon_w + code_w + name_min) - available
            icon_shrink = min(deficit, max(0, icon_w - icon_floor))
            deficit -= icon_shrink
            icon_w -= icon_shrink
            code_shrink = min(max(0, deficit), max(0, code_w - code_floor))
            deficit -= code_shrink
            code_w -= code_shrink
            if deficit > 0:
                # لم يكفِ إسقاط نص الحالة ولا تقليم الباركود: الأولوية الأخيرة
                # للباركود كاملًا (13 رقمًا) لا للمصغرة — وهو مطلب وظيفي لا
                # تجميلي: رقم مقصوص يعني مراجعة خاطئة. فنقتطع من المصغرة
                # حتى تصل إلى حد التمييز (28px) قبل أن نمس الاسم.
                icon_min = 28 + 8
                extra = min(deficit, max(0, icon_w - icon_min))
                icon_w -= extra
                deficit -= extra
                if extra > 0:
                    side = max(28, int(icon_w) - 8)
                    table.setIconSize(QSize(side, side))
                    # ما اندفع من المصغرة يردّ للباركود حتى يكتمل، بلا تجاوز
                    # مجموع الأعمدة للمتاح — وإلا ظهر شريط تمرير أفقي ممنوع.
                    want = fm.horizontalAdvance("6281006123456") + 10
                    room = available - int(icon_w) - name_min
                    code_w = max(code_w, min(want, max(code_floor, room)))
            if deficit > 0:
                name_min = max(fm.averageCharWidth() * 6, name_min - deficit)
        # ضمان أخير: مجموع العمودين الثابتين لا يلتهم المتاح كله.
        min_name = max(int(fm.averageCharWidth() * 6), 40)
        overflow = (int(icon_w) + int(code_w) + min_name) - available
        if overflow > 0:
            trim = min(overflow, max(0, int(icon_w) - (28 + 8)))
            icon_w -= trim
            overflow -= trim
            if overflow > 0:
                code_w -= min(overflow, max(0, int(code_w) - code_floor))
        table.setColumnWidth(0, int(icon_w))
        table.setColumnWidth(1, int(code_w))
        # 2.9.2 إصلاح 4: عند الشدة يُسقط نص الحالة وتبقى الأيقونة والتلميح.
        self._apply_status_text_mode(int(icon_w) >= icon_side + status_w + 10)
        # 2.9.2 إصلاح 5: ملاءمة عناوين الترويسة للعروض الفعلية.
        self._fit_table_headers()

    def eventFilter(self, obj, event):  # noqa: ANN001
        try:
            from PySide6.QtCore import QEvent
            if (getattr(self, "results_table", None) is not None
                    and obj is self.results_table.viewport()
                    and event.type() == QEvent.Resize):
                self._adjust_results_table_columns()
            # 2.9.6: F11 داخل النافذة الموسّعة يرجع للتبويب المدمج
            if (event.type() == QEvent.KeyPress
                    and obj is getattr(self, "_expanded_editor_window", None)
                    and event.key() == Qt.Key_F11):
                obj.close()
                return True
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def _continue_build_results_page(self, layout) -> None:  # noqa: ANN001
        """تكملة بناء صفحة النتائج (فُصلت لتنظيم الكود 2.6)."""
        self.result_search_edit = QLineEdit()
        self.result_search_edit.setObjectName("resultSearchEdit")
        self.result_search_edit.setPlaceholderText("ابحث بالاسم أو الصنف أو الباركود أو الصورة")
        self.result_search_edit.setClearButtonEnabled(True)
        self.result_search_edit.setToolTip("بحث فوري محلي يدعم الأرقام العربية والإنجليزية")
        # 2.9.3 إصلاح 10: ثلاثة عناصر بـ36px صلبة في صف المرشحات لا تتبع
        # المقياس، فتفرض 36px على 800×600 حيث ينبغي ≈22px — وهي جزء من
        # عجز 54px في resultsListPane الذي يقص أسفل اللوحة.
        self._register_metric(self.result_search_edit, "min_height", 36)
        self.result_search_edit.textChanged.connect(self._schedule_result_filters)

        self.result_status_filter = QComboBox()
        self.result_status_filter.setObjectName("resultStatusFilter")
        self._register_metric(self.result_status_filter, "min_height", 36)
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
        self._register_metric(self.clear_result_filter_button, "min_height", 36)
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
        # 2.3: لا سقف للارتفاع — هذا كان سبب تراكب العناصر فوق بعضها في 2.2.
        self.manual_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        manual_layout = QVBoxLayout(self.manual_group)
        manual_layout.setContentsMargins(8, 6, 8, 6)
        manual_layout.setSpacing(5)

        link_heading = QHBoxLayout()
        link_heading.setSpacing(6)
        link_title = QLabel("الربط المباشر")
        link_title.setObjectName("linkBarTitle")
        link_title.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.manual_context_label = QLabel("اختر صورة؛ يظهر رقم الصنف والباركود هنا.")
        self.manual_context_label.setObjectName("manualContext")
        self.manual_context_label.setWordWrap(False)
        self.manual_context_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.selected_count_badge = QLabel("المحدد: 0")
        self.selected_count_badge.setObjectName("selectedCountBadge")
        self.selected_count_badge.setAlignment(Qt.AlignCenter)
        # 2.6: الشارات لا تُقص — النص السياقي هو ما ينكمش (SizePolicy.Ignored أعلاه)
        self.selected_count_badge.setMinimumWidth(
            self.selected_count_badge.fontMetrics().horizontalAdvance("المحدد: 999") + 18)
        # 2.9: الشارة تمتد عموديًا مع الصف فتصبح كتلة بارتفاع 100px تأكل
        # مساحة أزرار الربط — نثبّتها على ارتفاع نصها الطبيعي فقط.
        self.selected_count_badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
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
        # 2.9.3 إصلاح 6: الارتفاع الأدنى يتبع المقياس. القياس أثبت أن
        # 36px صلبة لم تنكمش أبدًا (من 800×600 إلى 1920×1080)، فبينما تنزل
        # الأزرار التسعة إلى 20–29px يبقى هذا الصف يأكل 36px كاملة.
        self._register_metric(self.manual_item_edit, "min_height", 36)
        self.manual_link_button = QPushButton("ربط الآن")
        self.manual_link_button.setObjectName("manualLinkPrimaryButton")
        self._register_metric(self.manual_link_button, "min_height", 36)
        self.manual_link_button.clicked.connect(self._start_manual_link)
        manual_controls.addWidget(self.manual_item_edit, 1)
        manual_controls.addWidget(self.manual_link_button)
        manual_layout.addLayout(manual_controls)

        # الزر الذكي: عند تحديد صور بلا باركود يعرض مباشرة اسم ورقم صنف
        # أقرب صورة مرتبطة أعلاها — ضغطة واحدة تربط الكل بلا تأكيد.
        self.smart_link_button = QPushButton("حدد صورة بلا باركود للربط السريع")
        self.smart_link_button.setObjectName("smartLinkButton")
        # 2.9.3 إصلاح 6: 44px صلبة ← المقياس. ومع سياسة Fixed رأسيًا حتى
        # لا يتمدد الزر المخفي إلى 480px (رقم قيس فعلًا) فينفجر ارتفاع
        # اللوحة لحطة إظهاره عند تحديد صورة بلا باركود.
        self._register_metric(self.smart_link_button, "min_height", 44)
        self.smart_link_button.setSizePolicy(QSizePolicy.Preferred,
                                            QSizePolicy.Fixed)
        self.smart_link_button.setVisible(False)
        self.smart_link_button.setToolTip(
            "يربط الصور المحددة (بلا باركود) بنفس رقم صنف أقرب صورة مرتبطة\n"
            "أعلاها في القائمة — بضغطة واحدة وبلا رسائل تأكيد.\n"
            "مثال: صورت المنتج من الأمام بلا باركود؟ حددها واضغط الزر\n"
            "فتُربط بصنف صورة الباركود التي فوقها مباشرة."
        )
        self.smart_link_button.clicked.connect(self._smart_link_clicked)
        manual_layout.addWidget(self.smart_link_button)

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
            "يحدد الصور غير المرتبطة المجاورة للمرجع أو المشتركة معه في اسم الملف، للمراجعة فقط"
        )
        self.suggest_group_button.clicked.connect(self._suggest_high_confidence_group)
        self.reference_group_link_button = QPushButton("ربط بالمرجع")
        self.reference_group_link_button.setObjectName("referenceLinkButton")
        self.reference_group_link_button.setToolTip(
            "يربط الصفوف غير المؤكدة المحددة بصنف المرجع مع إبقاء كل صورة مستقلة"
        )
        self.reference_group_link_button.clicked.connect(self._start_reference_group_link)
        self.link_by_image_button = QPushButton("ربط بصورة أخرى")
        self.link_by_image_button.setObjectName("linkToolButton")
        self.link_by_image_button.setToolTip(
            "حدد صورة/عدة صور غير مرتبطة ثم اختر أي صورة مرتبطة — حتى البعيدة — لربطها بنفس صنفها"
        )
        self.link_by_image_button.clicked.connect(self._start_link_by_image)
        self.link_same_item_button = QPushButton("ضم للصنف الأعلى")
        self.link_same_item_button.setObjectName("referenceLinkButton")
        self.link_same_item_button.setToolTip(
            "ربط سريع لصور الصنف الواحد: يربط الصور المحددة غير المرتبطة\n"
            "بنفس صنف أقرب صورة مرتبطة أعلاها في القائمة — مناسب لصنف له 2-4 صور\n"
            "(صورة الباركود + الجهات الأخرى) ملتقطة متتالية"
        )
        self.link_same_item_button.clicked.connect(self._link_selected_to_nearest_above)
        # 2.9.6 — أُزيل وضع «اربط بالنقر» بطلب المالك: كان يعتمد على ترتيب
        # نقرتين متتاليتين فينكسر بسهولة (نقرة خاطئة = ربط خاطئ)،
        # وبديله الموثوق هو حقل البحث + الاقتراح الذكي + الربط بالمرجع.
        # زر حقائق التغذية — اقتصاص يدوي حر من الصورة الأصلية بدقتها الكاملة
        # يُحفظ فورًا كصورة منفردة ضمن صور الصنف — بلا Tesseract ولا OCR.
        self.nutrition_button = QPushButton("🍎 حقائق التغذية")
        self.nutrition_button.setObjectName("nutritionButton")
        self.nutrition_button.setToolTip(
            "اقتصاص جدول حقائق التغذية من الصورة الأصلية بدقتها الكاملة:\n"
            "1) حدد صورة مرتبطة بصنف ثم اضغط الزر\n"
            "2) ارسم مستطيلًا حول الجدول (تكبير بعجلة الماوس)\n"
            "3) احفظ — تُضاف فورًا كصورة جديدة ضمن صور الصنف بالترقيم الصحيح"
        )
        self.nutrition_button.clicked.connect(self._open_nutrition_crop)
        # زر حذف صورة من صور الصنف — يحذف الملف الناتج ويزيل الصف
        # من القائمة وحزمة ZIP بعد تأكيد صريح — الصورة الأصلية لا تُمس.
        self.delete_output_button = QPushButton("🗑 حذف الصورة")
        self.delete_output_button.setObjectName("deleteOutputButton")
        self.delete_output_button.setToolTip(
            "يحذف الصورة المحددة من صور الصنف (بعد تأكيد):\n"
            "• يحذف الملف الناتج من مجلد الإخراج وحزمة ZIP\n"
            "• يزيل الصف من القائمة\n"
            "• الصورة الأصلية المصدر لا تُمس أبدًا")
        self.delete_output_button.clicked.connect(self._delete_selected_outputs)
        self.manual_reference_badge = QLabel("لا يوجد مرجع")
        self.manual_reference_badge.setObjectName("manualReferenceBadge")
        self.manual_reference_badge.setAlignment(Qt.AlignCenter)
        self.manual_reference_badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.jump_to_previews_button = QPushButton("عرض الصورة")
        self.jump_to_previews_button.setObjectName("linkToolButton")
        self.jump_to_previews_button.setToolTip("ينقل التركيز مباشرة إلى الصورة الحالية")
        self.jump_to_previews_button.clicked.connect(self._scroll_to_previews)
        # 2.9.4 إصلاح 17: رمز مختصر لكل زر يُستخدم بدل النص عند
        # الشدة القصوى وحدها. النص الأصلي يُحفظ في ``_full_label``
        # فيعود حرفيًا عند التوسّع، ويُضمّ للتلميح دائمًا.
        self._link_button_glyphs = [
            (self.use_reference_button, "⚑"),
            (self.suggest_group_button, "◎"),
            (self.reference_group_link_button, "⚓"),
            (self.link_same_item_button, "↑⊕"),
            (self.link_by_image_button, "⇄"),
            (self.nutrition_button, "🍎"),
            (self.delete_output_button, "🗑"),
            (self.jump_to_previews_button, "🔍"),
        ]
        for _btn, _glyph in self._link_button_glyphs:
            _btn._full_label = _btn.text()
            _btn._compact_glyph = _glyph
            _tip = _btn.toolTip()
            # التلميح يبدأ دائمًا بالاسم الكامل لأنه وحده الدليل في الوضع المختصر
            if not _tip.startswith(_btn._full_label):
                _btn.setToolTip(f"{_btn._full_label}\n{_tip}" if _tip
                                else _btn._full_label)

        for button in (
            self.use_reference_button,
            self.suggest_group_button,
            self.reference_group_link_button,
            self.link_by_image_button,
            self.link_same_item_button,
            self.nutrition_button,
            self.delete_output_button,
            self.jump_to_previews_button,
        ):
            # 2.9.1: الارتفاع الأدنى يتبع المقياس. رقم 32px صلبًا لتسعة أزرار
            # موزّعة على أربعة أسطر = 128px لا تتوفر على 800×600، فيُقصّ السطر
            # الأخير. مع المقياس (0.62) يصبح 20px فيتوفر المتسع كاملًا، ومع ذلك
            # يبقى الزر أطول من نصّه لأن sizeHint يفرض الحد الفعلي.
            self._register_metric(button, "min_height", 32)
            # 2.3: لا تُقص نصوص الأزرار أبدًا — الحد الأدنى للعرض هو عرض النص الفعلي
            # إصلاح قص النصوص: العرض الأدنى يُحسب من عرض النص الفعلي + هوامش
            text_w = button.fontMetrics().horizontalAdvance(button.text())
            # +32 = padding الـ CSS (9×2) + الحدود + هامش أمان — لا قص مطلقًا
            # 2.9.4 إصلاح 17: يُحفط مرجعًا ليُستعاد عند الرجوع للنص الكامل
            button._full_min_width = text_w + 32
            button.setMinimumWidth(text_w + 32)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.manual_reference_badge.setMinimumWidth(
            self.manual_reference_badge.fontMetrics().horizontalAdvance(
                self.manual_reference_badge.text()) + 20)
        self.manual_reference_badge.setMaximumWidth(160)
        # 2.6: صف واحد ملتف (FlowLayout) بدل صفّين ثابتين — الأزرار تنزل
        # لسطر جديد تلقائيًا عند ضيق العرض فلا يُقص أي زر مطلقًا.
        # 2.9.6 — تسريع الإقلاع: يُستورد من الوحدة الخفيفة لا من
        # ``unified_editor``، فالأخير يجرّ numpy قبل ظهور النافذة.
        from flow_layout import FlowLayout as _LinkFlowLayout
        # 2.9.3 إصلاح 7: QWidget العادي يبني sizeHint من heightForWidth
        # محسوبًا على عرض sizeHint الضيق (≈عرض أوسع زر) لا على عرضه
        # الفعلي، فيعلن 388px (ستة أسطر) بدل 130px (سطرين) على
        # 1920×1080 — وهو ما أعجز resultsListPane على كل الدقات.
        # _FooterFlowFrame يعيد تعريف sizeHint ليقيس بالعرض الحقيقي.
        quick_flow_host = _FooterFlowFrame()
        quick_flow_host.setObjectName("linkFlowHost")
        # 2.9.4 إصلاح 17: مرجع محفوظ لإبطال التخطيط عند تبديل الوضع
        self._link_flow_host = quick_flow_host
        quick_flow_host.setStyleSheet(
            "QFrame#linkFlowHost { background: transparent; border: none; }")
        quick_flow = _LinkFlowLayout(quick_flow_host, margin=0, spacing=6)
        for link_btn in (
            self.use_reference_button,
            self.suggest_group_button,
            self.reference_group_link_button,
            self.link_same_item_button,
            self.link_by_image_button,
            self.nutrition_button,
            self.delete_output_button,
            self.jump_to_previews_button,
        ):
            link_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            quick_flow.addWidget(link_btn)

        # 2.5: أدوات الميل انتقلت إلى صفحة التحرير الموحدة — كل ما يخص الصورة في مكان واحد
        # 2.3: شارة المرجع انتقلت إلى صف العنوان — وتنكمش عند الضيق بدل تجاوز الحافة
        self.manual_reference_badge.setMinimumWidth(0)
        link_heading.addWidget(self.manual_reference_badge)
        # تلميح عائم منبثق فوق القائمة — آلية إشعارات عامة (حفظ حقائق
        # التغذية، حذف الصور، وغيرها). لا يأخذ مساحة داخل اللوحة
        # فلا تنحشر الأزرار.
        self.tap_link_hint = QLabel("", self)
        self.tap_link_hint.setObjectName("tapLinkHint")
        self.tap_link_hint.setWordWrap(True)
        self.tap_link_hint.setAlignment(Qt.AlignCenter)
        self.tap_link_hint.setVisible(False)
        self.tap_link_hint.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.tap_link_hint.raise_()
        self._tap_hint_timer = QTimer(self)
        self._tap_hint_timer.setSingleShot(True)
        self._tap_hint_timer.timeout.connect(
            lambda: self.tap_link_hint.setVisible(False))
        manual_layout.addWidget(quick_flow_host)

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
        # 2.6: حد أدنى مرن — مع الوضع العمودي التلقائي للشاشات الضيقة لا تراكب أبدًا
        self._register_metric(self.results_upper_widget, "min_width", 330)
        list_layout = QVBoxLayout(self.results_upper_widget)
        # 2.9.3 إصلاح 11: الهوامش والتباعد تتبع المقياس. على 800×600
        # تستهلك (10×2 + 7×3) = 41px من 378px متاحة — أكثر من عشر اللوحة
        # لمجرد فراغ، وهي من أسباب عجز 40px المتبقي.
        _pane_pad = self.ui_scale.px(10) if hasattr(self, "ui_scale") else 10
        _pane_gap = self.ui_scale.px(7) if hasattr(self, "ui_scale") else 7
        list_layout.setContentsMargins(
            _pane_pad, _pane_pad, _pane_pad, _pane_pad)
        list_layout.setSpacing(_pane_gap)
        self._pane_layout_metrics = (list_layout, 10, 7)
        # 2.9: صف العنوان يلتف بدل أن يبتر. القياس أثبت أن «عدد الأصناف: 0»
        # يحتاج 104px ولا يجد إلا 47px على 800×600، فيظهر «عدد…» فقط.
        # التخطيط الملتف ينزل بأزرار التنقل لسطر ثانٍ فيُقرأ كل نص كاملًا.
        list_header_host = _FooterFlowFrame()
        list_header_host.setObjectName("listHeaderHost")
        list_header_host.setStyleSheet(
            "QFrame#listHeaderHost { background: transparent; border: none; }")
        list_header = _EditorFlowLayout(list_header_host, margin=0, spacing=6)
        list_title = QLabel("قائمة الصور والصنف")
        list_title.setObjectName("sectionTitle")
        list_title.setToolTip("قائمة الصور والصنف")
        # 2.9.3 إصلاح 12: على 800×600 يلتف صف الترويسة لسطرين فيأخذ
        # 48px — أكبر بند بعد الجدول في عجز اللوحة. العنوان تزييني
        # والأزرار وعدّاد الأصناف وظيفيان، فيُسقط العنوان عند الشدة
        # القصوى وحدها فيعود الصف لسطر واحد بلا فقد أي وظيفة.
        self.list_title_label = list_title
        list_header.addWidget(list_title)
        list_header.addWidget(self.table_position_label)
        list_header.addWidget(self.first_item_button)
        list_header.addWidget(self.last_item_button)
        list_layout.addWidget(list_header_host)
        list_layout.addLayout(result_filter_layout)
        # 2.9.11 — مؤشر تحميل الجدول: رفيع (6px) ومخفي إلا أثناء
        # تعبئة دفعة كبيرة، فلا يقضم من ارتفاع الجدول في العادة.
        self.table_load_progress = QProgressBar()
        self.table_load_progress.setObjectName("tableLoadProgress")
        self.table_load_progress.setTextVisible(False)
        self.table_load_progress.setMaximumHeight(6)
        self.table_load_progress.setVisible(False)
        self.table_load_progress.setToolTip(
            "تقدم تحميل الأصناف — يمكنك العمل على المعروض منها الآن"
        )
        list_layout.addWidget(self.table_load_progress)
        list_layout.addWidget(self.results_table, 1)
        # 2.9: حاوية تمرير حول لوحة الربط — تبقى شفافة تمامًا في الحالة
        # العادية (بلا شريط ولا إطار)، وتُفعّل التمرير فقط عندما يكون
        # الارتفاع المتاح أقل من حاجة الأزرار، فلا يختفي زر أبدًا.
        self.manual_scroll = QScrollArea()
        self.manual_scroll.setObjectName("manualScroll")
        self.manual_scroll.setWidget(self.manual_group)
        self.manual_scroll.setWidgetResizable(True)
        self.manual_scroll.setFrameShape(QFrame.NoFrame)
        self.manual_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.manual_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.manual_scroll.setStyleSheet(
            "QScrollArea#manualScroll { background: transparent; border: none; }")
        list_layout.addWidget(self.manual_scroll)
        self.results_upper_content = self.results_upper_widget
        self._add_depth_effect(self.results_upper_widget, color="#293b5f", blur=24, y_offset=5, alpha=44)
        self._add_depth_effect(self.manual_group, color="#3730a3", blur=18, y_offset=4, alpha=48)

        self.previews_widget = QFrame()
        self.previews_widget.setObjectName("reviewStudio")
        self.previews_widget.setMinimumWidth(360)
        preview_layout = QVBoxLayout(self.previews_widget)
        preview_layout.setContentsMargins(10, 10, 10, 10)
        preview_layout.setSpacing(8)

        self.selected_product_card = QFrame()
        self.selected_product_card.setObjectName("selectedProductCard")
        self._register_metric(self.selected_product_card, "min_height", 88)
        # 2.9: السقف يتبع المقياس بدل 116px صلبة. السقف الصلب كان يمنع البطاقة
        # من استيعاب عنوان الصنف الملتف على أربعة أسطر، فيُقص من الأسفل.
        self._register_metric(self.selected_product_card, "max_height", 124)
        product_card_layout = QVBoxLayout(self.selected_product_card)
        product_card_layout.setContentsMargins(12, 8, 12, 8)
        product_card_layout.setSpacing(5)
        product_heading = QHBoxLayout()
        product_heading.setSpacing(8)
        self.selected_product_label = QLabel("اختر صورة من القائمة لعرض اسم الصنف كاملًا")
        self.selected_product_label.setObjectName("selectedProductName")
        self.selected_product_label.setWordWrap(True)
        self.selected_product_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        # 2.9: النص الملتف كان يحتاج 84px ويُمنح 66px داخل بطاقة مسقوفة، فيُقطع
        # نصف سطره الأخير بصريًا («اسم الصنف» مبتور) بلا أي مؤشر برمجي. الحل:
        # سياسة رأسية تفضّل الحد الأدنى الحقيقي للنص، وارتفاع أدنى يساوي
        # سطرين من ميتريات الخط الفعلية، فيبقى النص كاملًا على أي مقياس.
        self.selected_product_label.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.selected_product_label.setAlignment(
            Qt.AlignRight | Qt.AlignVCenter)
        self._product_name_full = self.selected_product_label.text()
        self.selected_product_label.setToolTip(self._product_name_full)
        self._product_name_placeholder = self._product_name_full
        self.selected_status_badge = QLabel("بانتظار الاختيار")
        self.selected_status_badge.setObjectName("selectedStatusBadge")
        self.selected_status_badge.setAlignment(Qt.AlignCenter)
        # 2.6: أزرار البطاقة أيقونات مضغوطة ثابتة العرض مع تلميح عربي عند
        # وضع الماوس — لا تُقص نصوصها أبدًا مهما ضاقت النافذة.
        self.edit_image_button = QPushButton("✎ تحرير")
        self.edit_image_button.setObjectName("editImageButton")
        # 2.9.3 إصلاح 9: أربعة أزرار بـ34px صلبة داخل بطاقة مسقوفة
        # بالمقياس — فعلى 800×600 تطلب البطاقة 82px وتجد 77px فيُقص
        # السطر الأخير من اسم الصنف. الأرقام الصلبة ← نظام المقياس.
        self._register_metric(self.edit_image_button, "min_height", 34)
        self.edit_image_button.setEnabled(False)
        self.edit_image_button.setToolTip(
            "تحرير احترافي: يفتح الصورة في تبويب «تحرير مباشر» بكامل الأدوات")
        self.edit_image_button.clicked.connect(self._open_individual_editor)
        self.open_selected_file_button = QPushButton("🗁")
        self.open_selected_file_button.setObjectName("openImageButton")
        self._register_metric(self.open_selected_file_button, "min_height", 34)
        self.open_selected_file_button.setToolTip(
            "فتح الصورة: يفتح ملف الصورة الحالي في عارض النظام")
        self.open_selected_file_button.clicked.connect(self._open_selected_file)
        self.open_link_panel_button = QPushButton("⇄")
        self.open_link_panel_button.setObjectName("focusLinkButton")
        self._register_metric(self.open_link_panel_button, "min_height", 34)
        self.open_link_panel_button.setToolTip(
            "تغيير الصنف: ينقل التركيز لحقل الربط المباشر لربط الصورة بصنف آخر")
        self.open_link_panel_button.clicked.connect(
            lambda: self.manual_item_edit.setFocus(Qt.OtherFocusReason)
        )
        self.set_primary_button = QPushButton("★")
        self.set_primary_button.setObjectName("focusLinkButton")
        self._register_metric(self.set_primary_button, "min_height", 34)
        self.set_primary_button.setEnabled(False)
        self.set_primary_button.setToolTip(
            "تعيين كصورة رئيسية: يجعل هذه الصورة صورة الواجهة الأولى للصنف فتخرج بلا رقم\n"
            "(رقم الصنف_الوحدة)، وتُرقّم بقية صور الصنف تلقائيًا -1، -2…"
        )
        self.set_primary_button.clicked.connect(self._set_primary_image)
        for compact_btn in (self.open_selected_file_button,
                            self.open_link_panel_button,
                            self.set_primary_button):
            compact_btn.setFixedWidth(42)
        self.edit_image_button.setMinimumWidth(
            self.edit_image_button.fontMetrics().horizontalAdvance(
                self.edit_image_button.text()) + 24)
        product_heading.addWidget(self.selected_product_label, 1)
        product_heading.addWidget(self.selected_status_badge)
        product_heading.addWidget(self.edit_image_button)
        product_heading.addWidget(self.set_primary_button)
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
            self._register_metric(pane.viewer, "min_height", 300)
        self.preview_tabs.addTab(self.output_preview, "النتيجة")
        self.preview_tabs.addTab(self.source_preview, "الأصل")

        # 2.4: المحرر الموحد مدمج في مكان الصورة — تبويب «تحرير مباشر» بلا نوافذ منفصلة.
        self.edit_tab = self._build_embedded_editor_tab()
        self.preview_tabs.addTab(self.edit_tab, "تحرير مباشر")
        self.preview_tabs.setCurrentWidget(self.output_preview)
        self.preview_tabs.currentChanged.connect(self._on_preview_tab_changed)
        preview_layout.addWidget(self.preview_tabs, 1)
        self._add_depth_effect(self.previews_widget, color="#111827", blur=26, y_offset=6, alpha=52)

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
        # 2.9: لا سقف رقمي إطلاقًا. سقف 48px صلبًا كان يخنق الأزرار على الشاشات
        # الكبيرة (الخط ينمو فيحتاج الزر 42px ويُمنح 36)، وسقف مقيس خطيًا كان
        # يخنقها على الصغيرة لأن الخط يتقلص بالجذر لا خطيًا فتختل النسبة.
        # الحل: الشريط يأخذ ارتفاعه من محتواه الفعلي عبر sizeHint، فيصح على
        # أي مقياس بلا تخمين رقمي.
        result_actions.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        # 2.7: مرجع محفوظ — يُخفى الشريط أثناء وضع التحرير لتوفير مساحة عمودية
        self.results_action_bar = result_actions
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
        # 2.9: لا حد أدنى رقمي. الزر يحدد ارتفاعه من نصه وخطه الفعليين، فلا
        # يُقص نصه على شاشة كبيرة ولا يفرض ارتفاعًا زائدًا على شاشة صغيرة.
        for delivery_btn in (self.save_zip_button, self.open_folder_button):
            delivery_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.save_zip_button.clicked.connect(self._save_delivery_zip)
        actions.addWidget(self.open_folder_button)
        actions.addWidget(delivery_hint, 1)
        actions.addWidget(self.save_zip_button)
        layout.addWidget(result_actions)

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

    @staticmethod
    def _install_label_elide(label: QLabel) -> None:
        """يجعل الـ QLabel يقتطع نصه بـ … عند ضيق العرض بدل القص الصلب.

        النص الكامل يبقى متاحًا كتلميح (tooltip)، وأي تحديث لاحق عبر
        ``setText`` يمر بنفس المعالجة تلقائيًا.
        """
        label._full_text = label.text()  # type: ignore[attr-defined]
        label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        def _apply(event=None):  # noqa: ANN001
            metrics = label.fontMetrics()
            elided = metrics.elidedText(
                label._full_text, Qt.ElideLeft, max(0, label.width() - 6))
            QLabel.setText(label, elided)
            label.setToolTip(
                label._full_text if elided != label._full_text else "")
            if event is not None:
                QLabel.resizeEvent(label, event)

        def _set_text(text: str) -> None:
            label._full_text = text  # type: ignore[attr-defined]
            _apply()

        label.resizeEvent = _apply  # type: ignore[method-assign]
        label.setText = _set_text  # type: ignore[method-assign]

    def _build_embedded_editor_tab(self) -> QWidget:
        """2.4: صفحة التحرير الموحدة — كل أدوات الصورة في مكان واحد.

        الصورة كبيرة بكامل العرض في الأعلى، وشريط أدوات أفقي بسيط أسفلها؛
        كل أداة تفتح لوحة خيارات رفيعة تحتها مباشرة — بلا نوافذ منفصلة
        ولا تداخلات، ويتوافق التصميم مع جميع أحجام الشاشات.
        """
        tab = QFrame()
        tab.setObjectName("embeddedEditorTab")
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(6, 6, 6, 6)
        tab_layout.setSpacing(6)

        header = QFrame()
        header.setObjectName("editorHeader")
        header.setMaximumHeight(50)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 4, 10, 4)
        header_layout.setSpacing(8)
        heading = QVBoxLayout()
        heading.setSpacing(1)
        self.individual_editor_product_label = QLabel("اختر أي صف ثم اضغط «تحرير احترافي»")
        self.individual_editor_product_label.setObjectName("editorProductLabel")
        self.individual_editor_product_label.setWordWrap(False)
        self.individual_editor_meta_label = QLabel("رقم الصنف: —  •  الوحدة: —")
        self.individual_editor_meta_label.setObjectName("editorMetaLabel")
        self.individual_editor_meta_label.setWordWrap(False)
        # 2.7: لا قص صلب للعنوان على الشاشات الضيقة — اقتطاع أنيق بـ …
        # مع إبقاء النص الكامل متاحًا كتلميح عند وضع الماوس.
        self._install_label_elide(self.individual_editor_product_label)
        self._install_label_elide(self.individual_editor_meta_label)
        heading.addWidget(self.individual_editor_product_label)
        heading.addWidget(self.individual_editor_meta_label)
        self.individual_editor_state_label = QLabel("جاهز للتحرير")
        self.individual_editor_state_label.setObjectName("editorStateBadge")
        self.individual_editor_state_label.setAlignment(Qt.AlignCenter)
        header_layout.addLayout(heading, 1)
        header_layout.addWidget(self.individual_editor_state_label)
        tab_layout.addWidget(header)

        # 2.6: المحرر الموحد الكامل — كل أدوات المحرر الاحترافي القديم مدمجة
        # في هذه الصفحة: معالجة ذكية، إزالة خلفية، فرشاة، ظل، منزلقات…
        #
        # 2.9.6 — تسريع الإقلاع: المحرّر لا يُبنى هنا بعد اليوم.
        # بناؤه وقت الإقلاع كان يكلّف قرابة 400 مللي ثانية (استيراد
        # `photo_editor_v2` ومعه numpy ثم إنشاء عشرات الودجتات)، رغم أن
        # التبويب غير مرئي عند الإقلاع، ولا يُفتح إلا بعد دفعة وربط
        # واختيار صف. يُبنى الآن عند أول لمسة حقيقية عبر `unified_editor`
        # (خاصية كسولة)، ويُسخَّن مسبقًا بعد استقرار الواجهة في
        # `_warm_editor_deferred`، فلا يشعر المستخدم بأي تأخير لاحق.
        self._editor_host_layout = tab_layout
        self._editor_host_index = tab_layout.count()

        # عناصر الجيل السابق تبقى مُنشأة (يشير إليها منطق قديم واختبارات)
        # لكنها مخفية تمامًا — المحرر الموحد يعوضها كلها.
        self.individual_editor_preview = ImagePreviewPane(
            "مساحة الصورة — كبّر وافحص النص والباركود قبل الحفظ"
        )
        self.individual_editor_preview.setObjectName("editorPreviewFrame")
        self.individual_editor_preview.setMinimumWidth(300)
        self._register_metric(self.individual_editor_preview.viewer, "min_height", 260)
        self.individual_editor_preview.viewer.crop_changed.connect(self._on_individual_crop_changed)
        self.individual_editor_preview.setVisible(False)
        tab_layout.addWidget(self.individual_editor_preview)

        self.individual_editor_panel = self._build_individual_editor_panel()
        self.individual_editor_panel.setVisible(False)
        tab_layout.addWidget(self.individual_editor_panel)

        # 2.8: التذييل يلتف بدل أن يُقص — سقف 48px القديم مع QHBoxLayout لا يلتف
        # كان يدفع الأزرار فوق بعضها على 800×600 و 1024×600 و 1024×700.
        footer = _FooterFlowFrame()
        footer.setObjectName("editorFooter")
        footer.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.editor_footer = footer
        footer_layout = _EditorFlowLayout(footer, margin=0, spacing=8)
        footer_layout.setContentsMargins(8, 5, 8, 5)
        self.individual_cancel_button = QPushButton("إنهاء التحرير")
        self.individual_cancel_button.setObjectName("secondaryButton")
        self.individual_cancel_button.setMinimumHeight(34)
        self.individual_cancel_button.clicked.connect(self._request_close_individual_editor)
        self.individual_reset_button = QPushButton("إعادة ضبط الكل")
        self.individual_reset_button.setObjectName("secondaryButton")
        self.individual_reset_button.setMinimumHeight(34)
        self.individual_reset_button.setToolTip("يلغي حدود القص اليدوي ويعيد الخيارات الموصى بها")
        self.individual_reset_button.clicked.connect(self._reset_individual_editor)
        self.individual_editor_hint = QLabel(
            "كل التعديلات تظهر مباشرة على الصورة — اضغط «حفظ واعتماد» لتحديث الناتج والتقارير."
        )
        self.individual_editor_hint.setObjectName("individualEditorHint")
        self.individual_editor_hint.setWordWrap(False)
        self.individual_editor_hint.setAlignment(Qt.AlignCenter)
        # الـ hint هو العنصر الوحيد القابل للانكماش — الأزرار لا تُقص أبدًا على الشاشات الضيقة
        self.individual_editor_hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        # 2.6: عند الضيق الشديد لا نعرض نصًا مبتورًا — يُقتطع بعلامة … أو يختفي،
        # والنص الكامل متاح دائمًا كتلميح عند وضع الماوس فوقه.
        self._hint_full_text = self.individual_editor_hint.text()

        def _elide_hint(event=None):  # noqa: ANN001
            label = self.individual_editor_hint
            metrics = label.fontMetrics()
            elided = metrics.elidedText(
                self._hint_full_text, Qt.ElideLeft, max(0, label.width() - 8))
            # إن لم يتسع حتى لجزء مفيد — أخفِ النص والإطار معًا بدل مربع فارغ
            too_narrow = label.width() < 120
            if too_narrow:
                elided = ""
            label.setStyleSheet("background: transparent; border: none;" if too_narrow else "")
            QLabel.setText(label, elided)
            label.setToolTip(self._hint_full_text)
            if event is not None:
                QLabel.resizeEvent(label, event)

        self.individual_editor_hint.resizeEvent = _elide_hint  # type: ignore[method-assign]


        def _set_hint_text(text: str) -> None:
            self._hint_full_text = text
            _elide_hint()

        self.individual_editor_hint.setText = _set_hint_text  # type: ignore[method-assign]
        self.individual_preview_button = QPushButton("إنشاء معاينة")
        self.individual_preview_button.setObjectName("individualPreviewButton")
        self.individual_preview_button.setMinimumHeight(34)
        self.individual_preview_button.setToolTip(
            "يعرض النتيجة المقترحة من دون تغيير الملف أو التقارير أو حزمة ZIP"
        )
        self.individual_preview_button.clicked.connect(self._start_individual_preview)
        # 2.6: المعاينة أصبحت حية فورية داخل المحرر الموحد (زر قبل/بعد) — الزر مخفي للتوافق
        self.individual_preview_button.setVisible(False)
        self.individual_apply_button = QPushButton("حفظ واعتماد التعديل")
        self.individual_apply_button.setObjectName("individualApplyButton")
        self.individual_apply_button.setMinimumHeight(34)
        self.individual_apply_button.setToolTip(
            "يحفظ هذا الصف وحده ويحدّث التقارير وحزمة ZIP من دون تغيير بقية الصور"
        )
        self.individual_apply_button.clicked.connect(self._start_individual_edit)
        # حقائق التغذية مباشرة من مكان التحرير — تفتح نافذة اقتصاص سريعة
        # على الصورة الأصلية للصنف الجاري تحريره (نفس زر لوحة الربط).
        self.editor_nutrition_button = QPushButton("🍎 حقائق التغذية")
        self.editor_nutrition_button.setObjectName("nutritionButton")
        self.editor_nutrition_button.setMinimumHeight(34)
        self.editor_nutrition_button.setToolTip(
            "يفتح نافذة اقتصاص سريعة على الصورة الأصلية بدقتها الكاملة:\n"
            "حدد جدول حقائق التغذية بالسحب واحفظه كصورة جديدة\n"
            "مرتبطة برقم الصنف — يمكن حفظ عدة اقتصاصات دون إغلاق النافذة")
        self.editor_nutrition_button.clicked.connect(self._open_nutrition_crop)
        # 2.9.6 — النقطة 4: صفحة تحرير موسّعة بحرية أكبر.
        # المحرّر نفسه (لا نسخة ثانية) يُنقل إلى نافذة بملء الشاشة
        # فتبقى كل الحالة والتاريخ والتعديلات كما هي دون أي فقد.
        self.editor_expand_button = QPushButton("⛶ توسيع الصفحة")
        self.editor_expand_button.setObjectName("secondaryButton")
        self.editor_expand_button.setMinimumHeight(34)
        self.editor_expand_button.setToolTip(
            "يفتح المحرّر في صفحة بملء الشاشة مع الأدوات المتقدمة مفتوحة:\n"
            "مساحة أكبر للصورة وحرية أوسع في التعديل — لا تُفقد أي تعديلات\n"
            "عند التوسيع أو العودة (F11 أو إغلاق النافذة للرجوع)")
        self.editor_expand_button.clicked.connect(self._toggle_expanded_editor)
        # 2.6: لا قص لنصوص الأزرار — عرض أدنى مبني على النص الفعلي لكل زر
        for footer_btn in (self.individual_cancel_button,
                           self.individual_reset_button,
                           self.editor_nutrition_button,
                           self.editor_expand_button,
                           self.individual_apply_button):
            footer_btn.setMinimumWidth(
                footer_btn.fontMetrics().horizontalAdvance(footer_btn.text()) + 28)
        # 2.8: الترتيب حسب الأهمية — أزرار القرار أولًا فتبقى في السطر الأول
        # عند الالتفاف، والتلميح النصي أخيرًا لأنه العنصر القابل للانكماش.
        for footer_widget in (
            self.individual_apply_button,
            self.editor_expand_button,
            self.editor_nutrition_button,
            self.individual_reset_button,
            self.individual_cancel_button,
            self.individual_preview_button,
            self.individual_editor_hint,
        ):
            footer_layout.addWidget(footer_widget)
        tab_layout.addWidget(footer)
        # مرساة المحرّر داخل التبويب — يُعاد إليها بعد إغلاق النافذة الموسّعة
        self._editor_tab_layout = tab_layout
        self._editor_tab_footer = footer
        self._expanded_editor_window = None
        return tab

    # ------------------------------------------------- 2.9.6 المحرّر الكسول
    @property
    def unified_editor(self):
        """المحرّر الموحّد — يُبنى عند أول لمسة فعلية لا وقت الإقلاع.

        كل الكود القائم يكتب ``self.unified_editor.x`` كما كان تمامًا؛
        الفرق الوحيد أن البناء يحدث عند أول وصول. ملاحظة مهمة:
        الفحوصات القديمة ``hasattr(self, "unified_editor")`` كانت تعني
        «هل اكتمل بناء الواجهة؟»، لكن مع الخاصية الكسولة صار ``hasattr``
        نفسه يُنشئ المحرّر ويُلغي الفائدة؛ لذا استُبدلت كلها بـ
        ``_editor_ready()`` التي تفحص دون إنشاء.
        """
        editor = self.__dict__.get("_unified_editor_instance")
        if editor is not None:
            return editor
        layout = getattr(self, "_editor_host_layout", None)
        if layout is None:
            # مرساة التبويب لم تُنشأ بعد — نحن داخل بناء الواجهة.
            raise AttributeError("unified_editor")
        from unified_editor import UnifiedEditorWidget

        editor = UnifiedEditorWidget()
        editor.setObjectName("unifiedEditor")
        editor.setMinimumWidth(300)
        self.__dict__["_unified_editor_instance"] = editor
        layout.insertWidget(self._editor_host_index, editor, 1)
        # المحرّر يولد بعد تطبيق الأنماط والمقاييس، فيُعاد تطبيقهما
        # عليه وحده ليطابق مظهره ما كان يوم كان يُبنى وقت الإقلاع.
        sheet = getattr(self, "_base_stylesheet", None)
        scale = getattr(self, "ui_scale", None)
        if sheet and scale is not None:
            editor.setStyleSheet(scale.scale_stylesheet(sheet))
        busy = bool(getattr(self, "_busy", False))
        try:
            editor.setEnabled(
                not busy and self._individual_editable_item() is not None)
        except Exception:
            pass
        return editor

    def _editor_ready(self) -> bool:
        """هل المحرّر مبنيٌ فعلًا؟ — فحص لا يُنشئه.

        يحلّ محل ``hasattr(self, "unified_editor")`` القديمة، لأن ``hasattr``
        مع خاصية كسولة يستدعيها فيبني المحرّر حيث كان القصد مجرد
        السؤال عن وجوده.
        """
        return self.__dict__.get("_unified_editor_instance") is not None

    def _warm_editor_deferred(self) -> None:
        """يبني المحرّر بعد استقرار الواجهة فيصير فتح التبويب فوريًا.

        بناء ودجتات Qt يجب أن يبقى على خيط الواجهة، لكن تأخيره إلى ما بعد
        أول رسم ينقل الكلفة من «شاشة فارغة ينتظرها المستخدم» إلى لحظة
        الواجهة فيها معروضة وجاهزة.
        """
        try:
            self.unified_editor  # noqa: B018 - الوصول هو البناء
        except Exception as exc:  # pragma: no cover - دفاعي
            print(f"[boot] editor warm-up failed: {exc}", file=sys.stderr)

    def _on_preview_tab_changed(self, _index: int) -> None:
        """فتح تبويب «تحرير مباشر» مباشرة يجهّز الصورة المحددة للتحرير تلقائيًا."""
        if not hasattr(self, "edit_tab"):
            return
        if self.preview_tabs.currentWidget() is not self.edit_tab:
            # 2.7: مغادرة تبويب التحرير تُعيد بطاقة المنتج وشريط الإجراءات
            if hasattr(self, "selected_product_card"):
                self.selected_product_card.setVisible(True)
            if hasattr(self, "results_action_bar"):
                self.results_action_bar.setVisible(True)
            return
        if self._individual_edit_source_name:
            # جلسة قائمة — العودة للتبويب تعيد توسيع مساحة التحرير
            self.selected_product_card.setVisible(False)
            self.results_action_bar.setVisible(False)
            return
        item = self._individual_editable_item()
        if item is not None:
            self._open_individual_editor()

    @staticmethod
    def _make_rotate_icon(clockwise: bool) -> QIcon:
        """يرسم أيقونة سهم دوران واضحة (لا تعتمد على دعم الخط للرموز)."""
        size = 40
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor("#1d4ed8"))
        pen.setWidth(4)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        rect = QRectF(7, 7, size - 14, size - 14)
        # قوس دائري مفتوح من الأعلى
        start_angle = 60 * 16
        span = 250 * 16
        painter.drawArc(rect, start_angle, span)
        # رأس السهم عند نهاية القوس العلوية
        painter.setBrush(QColor("#1d4ed8"))
        painter.setPen(Qt.NoPen)
        arrow = QPolygonF()
        if clockwise:
            tip_x, tip_y = size - 6.0, 10.0
            arrow.append(QPointF(tip_x, tip_y))
            arrow.append(QPointF(tip_x - 11.0, tip_y - 3.0))
            arrow.append(QPointF(tip_x - 2.0, tip_y + 9.0))
        else:
            tip_x, tip_y = 6.0, 10.0
            arrow.append(QPointF(tip_x, tip_y))
            arrow.append(QPointF(tip_x + 11.0, tip_y - 3.0))
            arrow.append(QPointF(tip_x + 2.0, tip_y + 9.0))
        painter.drawPolygon(arrow)
        painter.end()
        if clockwise:
            # انعكاس أفقي للحصول على اتجاه عقارب الساعة
            pm = pm.transformed(QTransform().scale(-1, 1))
        return QIcon(pm)

    @staticmethod
    def _make_reset_icon() -> QIcon:
        """يرسم أيقونة تصفير (دائرة مع نقطة مركزية) واضحة بلا نصوص."""
        size = 40
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor("#0f766e"))
        pen.setWidth(4)
        painter.setPen(pen)
        painter.drawEllipse(QRectF(8, 8, size - 16, size - 16))
        painter.setBrush(QColor("#0f766e"))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(size / 2 - 4, size / 2 - 4, 8, 8))
        painter.end()
        return QIcon(pm)

    def _build_individual_editor_panel(self) -> QWidget:
        """شريط الأدوات الموحد — صف أفقي واحد أسفل الصورة يجمع كل الأدوات.

        أربع مجموعات أدوات (اقتصاص | تحسين | تنظيف | مقارنة) تظهر في شريط
        أفقي واحد قابل للتمرير أفقيًا على الشاشات الصغيرة — بلا تبويبات متراكمة
        ولا نوافذ منفصلة، فتبقى الصورة كبيرة والأدوات كلها مرئية في مكان واحد.
        """
        panel = QFrame()
        panel.setObjectName("individualEditor")
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(6, 4, 6, 4)
        outer.setSpacing(0)

        strip = QWidget()
        strip.setObjectName("editorToolsStrip")
        # 2.5: شبكة تلتف تلقائيًا — لا تمرير أفقي ولا قصّ على أي عرض شاشة
        row = QGridLayout(strip)
        row.setContentsMargins(4, 4, 4, 4)
        row.setHorizontalSpacing(8)
        row.setVerticalSpacing(8)

        # ── المجموعة 1: الاقتصاص والميل ──
        crop_card = QFrame()
        crop_card.setObjectName("editorCropCard")
        crop_layout = QVBoxLayout(crop_card)
        crop_layout.setContentsMargins(8, 6, 8, 6)
        crop_layout.setSpacing(5)
        crop_title = QLabel("الاقتصاص والميل")
        crop_title.setObjectName("editorToolSectionTitle")
        crop_title.setAlignment(Qt.AlignCenter)
        crop_layout.addWidget(crop_title)

        crop_mode_row = QHBoxLayout()
        crop_mode_row.setSpacing(5)
        self.individual_auto_crop_button = QPushButton("ذكي تلقائي")
        self.individual_auto_crop_button.setObjectName("individualAutoCropButton")
        self.individual_auto_crop_button.setCheckable(True)
        self.individual_auto_crop_button.setChecked(True)
        self.individual_auto_crop_button.setMinimumHeight(32)
        self.individual_auto_crop_button.setToolTip(
            "يكتشف حدود المنتج ويوازن المسافات البيضاء تلقائيًا داخل 800×700"
        )
        self.individual_manual_crop_button = QPushButton("يدوي حر")
        self.individual_manual_crop_button.setObjectName("individualManualCropButton")
        self.individual_manual_crop_button.setCheckable(True)
        self.individual_manual_crop_button.setMinimumHeight(32)
        self.individual_manual_crop_button.setToolTip(
            "اقتصاص منظور: اسحب إطارًا أوليًا ثم حرّك الزوايا الأربع مستقلة حتى تتبع ميل العبوة"
        )
        crop_mode_row.addWidget(self.individual_auto_crop_button, 1)
        crop_mode_row.addWidget(self.individual_manual_crop_button, 1)
        crop_layout.addLayout(crop_mode_row)

        crop_opts_row = QHBoxLayout()
        crop_opts_row.setSpacing(5)
        self.individual_crop_ratio_combo = QComboBox()
        self.individual_crop_ratio_combo.setObjectName("individualCropRatio")
        self.individual_crop_ratio_combo.setMinimumHeight(30)
        self.individual_crop_ratio_combo.addItem("طبيعي — حسب حدود المنظور", None)
        self.individual_crop_ratio_combo.addItem("نسبة الإخراج 800 × 700", 800.0 / 700.0)
        self.individual_crop_ratio_combo.addItem("مربع 1 : 1", 1.0)
        self.individual_crop_ratio_combo.addItem("عمودي 3 : 4", 3.0 / 4.0)
        self.individual_crop_ratio_combo.addItem("أفقي 4 : 3", 4.0 / 3.0)
        self.individual_crop_ratio_combo.setToolTip(
            "الوضع الحر هو الافتراضي ولا يفرض مربعًا. اختر نسبة ثابتة فقط عند الحاجة."
        )
        self.individual_crop_full_button = QPushButton("كامل الصورة")
        self.individual_crop_full_button.setObjectName("cropUtilityButton")
        self.individual_crop_full_button.setMinimumHeight(30)
        self.individual_crop_full_button.setToolTip("يضع إطار القص على أكبر مساحة ممكنة داخل الصورة")
        self.individual_crop_clear_button = QPushButton("مسح الإطار")
        self.individual_crop_clear_button.setObjectName("cropUtilityButton")
        self.individual_crop_clear_button.setMinimumHeight(30)
        self.individual_crop_clear_button.setToolTip("يمسح إطار القص لتستطيع رسم إطار جديد")
        crop_opts_row.addWidget(self.individual_crop_ratio_combo, 2)
        crop_opts_row.addWidget(self.individual_crop_full_button, 1)
        crop_opts_row.addWidget(self.individual_crop_clear_button, 1)
        crop_layout.addLayout(crop_opts_row)

        crop_extra_row = QHBoxLayout()
        crop_extra_row.setSpacing(5)
        self.individual_straighten_check = QCheckBox("تصحيح الميل تلقائيًا")
        self.individual_straighten_check.setObjectName("individualStraighten")
        self.individual_straighten_check.setChecked(True)
        self.individual_straighten_check.setToolTip(
            "يصحح الميل البسيط تلقائيًا من دون تشويه العبوة أو النص"
        )
        # ملصق معلومات القص — يُعرض في شريط footer السفلي (لا يزاحم البطاقة)
        self.individual_crop_info_label = QLabel("القص التلقائي نشط")
        self.individual_crop_info_label.setObjectName("cropInfoLabel")
        self.individual_crop_info_label.setWordWrap(False)
        self.individual_crop_info_label.setAlignment(Qt.AlignCenter)
        self.individual_crop_info_label.setVisible(False)
        # أدوات الميل اليدوي — انتقلت من لوحة الربط إلى هنا (كل ما يخص الصورة في مكان واحد)
        tilt_label = QLabel("الميل اليدوي:")
        tilt_label.setObjectName("manualTiltLabel")
        self.manual_tilt_spin = QDoubleSpinBox()
        self.manual_tilt_spin.setObjectName("manualTiltSpin")
        self.manual_tilt_spin.setRange(-45.0, 45.0)
        self.manual_tilt_spin.setDecimals(1)
        self.manual_tilt_spin.setSingleStep(0.5)
        self.manual_tilt_spin.setSuffix("°")
        self.manual_tilt_spin.setValue(0.0)
        self.manual_tilt_spin.setMinimumHeight(32)
        self.manual_tilt_spin.setMinimumWidth(96)
        self.manual_tilt_spin.setLayoutDirection(Qt.LeftToRight)
        self.manual_tilt_spin.setAlignment(Qt.AlignCenter)
        # إخفاء أسهم الـ spin المتداخلة — التحكم يتم بأزرار الدوران المرسومة حوله
        self.manual_tilt_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.manual_tilt_spin.setToolTip(
            "وزن الميل يدويًا من الأمام:\n"
            "موجب = دوران لليسار (عكس العقارب)، سالب = لليمين.\n"
            "المعاينة تتحدث فورًا والقيمة تُطبق عند الحفظ أو الربط")
        self.manual_tilt_ccw_button = QPushButton()
        self.manual_tilt_ccw_button.setObjectName("manualTiltButton")
        self.manual_tilt_ccw_button.setIcon(self._make_rotate_icon(clockwise=False))
        self.manual_tilt_ccw_button.setToolTip("إمالة لليسار 0.5°")
        self.manual_tilt_cw_button = QPushButton()
        self.manual_tilt_cw_button.setObjectName("manualTiltButton")
        self.manual_tilt_cw_button.setIcon(self._make_rotate_icon(clockwise=True))
        self.manual_tilt_cw_button.setToolTip("إمالة لليمين 0.5°")
        self.manual_tilt_reset_button = QPushButton()
        self.manual_tilt_reset_button.setObjectName("manualTiltButton")
        self.manual_tilt_reset_button.setIcon(self._make_reset_icon())
        self.manual_tilt_reset_button.setToolTip("إرجاع الميل إلى الصفر")
        for tb in (self.manual_tilt_ccw_button, self.manual_tilt_cw_button,
                   self.manual_tilt_reset_button):
            tb.setMinimumHeight(32)
            tb.setFixedWidth(40)
            tb.setIconSize(QSize(20, 20))
        self.manual_tilt_ccw_button.clicked.connect(
            lambda: self.manual_tilt_spin.setValue(
                self.manual_tilt_spin.value() + 0.5))
        self.manual_tilt_cw_button.clicked.connect(
            lambda: self.manual_tilt_spin.setValue(
                self.manual_tilt_spin.value() - 0.5))
        self.manual_tilt_reset_button.clicked.connect(
            lambda: self.manual_tilt_spin.setValue(0.0))
        self.manual_tilt_spin.valueChanged.connect(self._on_manual_tilt_changed)
        crop_extra_row.addWidget(self.individual_straighten_check)
        crop_extra_row.addWidget(tilt_label)
        crop_extra_row.addWidget(self.manual_tilt_ccw_button)
        crop_extra_row.addWidget(self.manual_tilt_spin)
        crop_extra_row.addWidget(self.manual_tilt_cw_button)
        crop_extra_row.addWidget(self.manual_tilt_reset_button)
        crop_extra_row.addStretch(1)
        crop_layout.addLayout(crop_extra_row)
        crop_layout.addStretch(1)

        # ── المجموعة 2: التحسين والإضاءة ──
        enhance_card = QFrame()
        enhance_card.setObjectName("editorEnhanceCard")
        enhance_layout = QVBoxLayout(enhance_card)
        enhance_layout.setContentsMargins(8, 6, 8, 6)
        enhance_layout.setSpacing(5)
        enhance_title = QLabel("التحسين والإضاءة")
        enhance_title.setObjectName("editorToolSectionTitle")
        enhance_title.setAlignment(Qt.AlignCenter)
        enhance_layout.addWidget(enhance_title)
        self.individual_smart_button = QPushButton("تحسين ذكي محافظ")
        self.individual_smart_button.setObjectName("individualSmartButton")
        self.individual_smart_button.setCheckable(True)
        self.individual_smart_button.setChecked(True)
        self.individual_smart_button.setMinimumHeight(32)
        self.individual_smart_button.setToolTip(
            "يحسن الإضاءة والألوان والتفاصيل محليًا مع حماية الشعار والكتابات والباركود"
        )
        enhance_layout.addWidget(self.individual_smart_button)
        self.individual_strength_combo = QComboBox()
        self.individual_strength_combo.setObjectName("individualStrength")
        self.individual_strength_combo.addItem("متوازن — موصى به", 55)
        self.individual_strength_combo.addItem("قوي للصورة الباهتة", 78)
        self.individual_strength_combo.addItem("محافظ للملصقات", 35)
        self.individual_strength_combo.setMinimumHeight(30)
        self.individual_strength_combo.setToolTip("قوة تحسين الصورة المحددة فقط")
        enhance_layout.addWidget(self.individual_strength_combo)
        enhance_layout.addStretch(1)

        # ── المجموعة 3: التنظيف (طمس التواريخ + إزالة الانعكاسات) ──
        clean_card = QFrame()
        clean_card.setObjectName("editorAdvancedCard")
        clean_layout = QVBoxLayout(clean_card)
        clean_layout.setContentsMargins(8, 6, 8, 6)
        clean_layout.setSpacing(5)
        clean_title = QLabel("تنظيف الصورة")
        clean_title.setObjectName("editorToolSectionTitle")
        clean_title.setAlignment(Qt.AlignCenter)
        clean_layout.addWidget(clean_title)
        self.individual_blur_dates_check = QCheckBox("طمس التواريخ تلقائيًا")
        self.individual_blur_dates_check.setObjectName("individualBlurDates")
        self.individual_blur_dates_check.setToolTip(
            "يكتشف مناطق تواريخ الإنتاج/الانتهاء ويطمسها بلون المنتج نفسه قبل الحفظ"
        )
        clean_layout.addWidget(self.individual_blur_dates_check)
        self.individual_deglare_check = QCheckBox("إزالة الانعكاسات (اللمعان)")
        self.individual_deglare_check.setObjectName("individualDeglare")
        self.individual_deglare_check.setToolTip(
            "يخفف اللمعان والانعكاسات الضوئية على العبوة من دون المساس بالكتابات"
        )
        clean_layout.addWidget(self.individual_deglare_check)
        clean_layout.addStretch(1)

        # ── المجموعة 4: المقارنة قبل الحفظ ──
        compare_card = QFrame()
        compare_card.setObjectName("editorCompareCard")
        compare_layout = QVBoxLayout(compare_card)
        compare_layout.setContentsMargins(8, 6, 8, 6)
        compare_layout.setSpacing(5)
        compare_title = QLabel("المقارنة قبل الحفظ")
        compare_title.setObjectName("editorToolSectionTitle")
        compare_title.setAlignment(Qt.AlignCenter)
        compare_layout.addWidget(compare_title)
        self.individual_show_source_button = QPushButton("عرض الأصل")
        self.individual_show_source_button.setObjectName("showSourceButton")
        self.individual_show_source_button.setMinimumHeight(32)
        compare_layout.addWidget(self.individual_show_source_button)
        self.individual_show_preview_button = QPushButton("عرض النتيجة")
        self.individual_show_preview_button.setObjectName("showPreviewButton")
        self.individual_show_preview_button.setMinimumHeight(32)
        self.individual_show_preview_button.setEnabled(False)
        compare_layout.addWidget(self.individual_show_preview_button)
        compare_layout.addStretch(1)

        # ترتيب متكيف: صف واحد على الشاشات الواسعة، صفّان على الضيقة — بلا قص ولا تمرير
        self._editor_tool_cards = (crop_card, enhance_card, clean_card, compare_card)
        self._editor_tools_grid = row
        self._editor_tools_columns = 0
        for card in self._editor_tool_cards:
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._relayout_editor_tool_cards(initial=True)
        outer.addWidget(strip)

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
        self.individual_blur_dates_check.toggled.connect(self._invalidate_individual_preview)
        self.individual_deglare_check.toggled.connect(self._invalidate_individual_preview)
        return panel

    def _relayout_editor_tool_cards(self, initial: bool = False) -> None:
        """2.5: ترتيب متكيف لبطاقات الأدوات — صف واحد على الشاشات الواسعة،
        صفّان (2×2) على الشاشات الضيقة — بلا قصّ ولا تمرير أفقي."""
        cards = getattr(self, "_editor_tool_cards", None)
        grid = getattr(self, "_editor_tools_grid", None)
        if not cards or grid is None:
            return
        try:
            available = self.width() if self.width() > 0 else 1280
        except Exception:
            available = 1280
        # أقل عرض مريح للبطاقات الأربع في صف واحد دون قص — أقل من ذلك نلتف إلى 2×2
        columns = 4 if available >= 1500 else 2
        if not initial and columns == self._editor_tools_columns:
            return
        self._editor_tools_columns = columns
        for card in cards:
            grid.removeWidget(card)
        # بطاقة الاقتصاص أوسع لأنها تحوي أدوات أكثر
        stretches = (3, 2, 2, 2)
        for index, card in enumerate(cards):
            r, c = divmod(index, columns)
            grid.addWidget(card, r, c)
        for c in range(columns):
            grid.setColumnStretch(c, stretches[c] if columns == 4 else 1)
        for c in range(columns, 4):
            grid.setColumnStretch(c, 0)

    def _individual_editor_image_pane(self) -> ImagePreviewPane:
        return self.individual_editor_preview

    def _is_individual_editor_active(self) -> bool:
        """2.3: جلسة تحرير مدمجة نشطة في تبويب «تحرير مباشر»."""
        return bool(self._individual_edit_source_name)

    def _invalidate_individual_preview(self, *_args) -> None:
        editor_open = self._is_individual_editor_active()
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

    def _set_crop_info_text(self, text: str) -> None:
        """يكتب معلومات القص في الملصق المخفي (للتوافق) وفي شريط التلميح السفلي المرئي."""
        self.individual_crop_info_label.setText(text)
        if hasattr(self, "individual_editor_hint"):
            self.individual_editor_hint.setText(text)

    def _update_individual_crop_info(self) -> None:
        if not self.individual_manual_crop_button.isChecked():
            self._set_crop_info_text("القص الذكي يحدد المنتج تلقائيًا ويوازن الفراغ حوله")
            self.individual_crop_full_button.setEnabled(False)
            self.individual_crop_clear_button.setEnabled(False)
            self.individual_crop_ratio_combo.setEnabled(False)
            return
        self.individual_crop_full_button.setEnabled(True)
        self.individual_crop_clear_button.setEnabled(self._individual_crop_box is not None)
        self.individual_crop_ratio_combo.setEnabled(True)
        if self._individual_crop_box is None:
            self._set_crop_info_text(
                "لا يوجد إطار — اسحب إطارًا أوليًا ثم ضع الزوايا الأربع على أركان المنتج"
            )
            return
        viewer = self._individual_editor_image_pane().viewer
        size = viewer.crop_pixel_size()
        kept = viewer.crop_area_ratio() * 100.0
        if size is None:
            self._set_crop_info_text(f"منظور رباعي جاهز — يحتفظ بنحو {kept:.0f}% من الصورة")
        else:
            width, height = size
            self._set_crop_info_text(
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
                self,
                APP_NAME,
                "انتظر حتى تنتهي المعاينة أو عملية الحفظ الحالية؛ لن يُغلق المحرر أثناء المعالجة.",
            )
            return
        unified_dirty = False
        editor = getattr(self, "unified_editor", None)
        if editor is not None:
            try:
                unified_dirty = editor.has_image() and editor.has_edits()
            except Exception:
                unified_dirty = False
        if self._individual_editor_dirty or self._individual_preview_active or unified_dirty:
            box = QMessageBox(self)
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
        self._exit_individual_edit_mode()

    def _open_individual_editor(self) -> None:
        item = self._individual_editable_item()
        if item is None:
            QMessageBox.information(
                self,
                APP_NAME,
                "حدد صفًا واحدًا فقط لفتح محرر الصورة.",
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
        # 2.6: تحميل الصورة في المحرر الموحد — كل الأدوات تعمل مباشرة على الصورة
        self.unified_editor.load_image(str(source))
        # 2.9.13 (م-12): تسجيل وجهة المحرر — عليها يعتمد حرس
        # فساد البيانات قبل اعتماد أي بكسلات.
        self._editor_loaded_source_name = item.source_name
        self.individual_editor_product_label.setText(item.product_name or item.source_name)
        unit = self._units_label_for_code(item.item_code)
        self.individual_editor_meta_label.setText(
            f"رقم الصنف: {item.item_code or 'غير مرتبط'}  •  الوحدة: {unit}  •  الملف: {item.source_name}"
        )
        self.individual_editor_state_label.setText("جاهز للتحرير")
        self.individual_editor_state_label.setProperty("previewPending", False)
        # 2.9.6: إن كانت الصفحة الموسّعة مفتوحة تتحدّث معلوماتها فورًا
        info_label = getattr(self, "_expanded_info_label", None)
        if info_label is not None and getattr(self, "_expanded_editor_window", None):
            info_label.setText(
                f"{item.product_name or item.source_name}  —  "
                f"رقم الصنف: {item.item_code or 'غير مرتبط'}  •  "
                f"الوحدة: {unit}  •  الملف: {item.source_name}"
            )
        # 2.6: اللوحة القديمة تبقى مخفية — المحرر الموحد يعوضها بالكامل
        self.individual_editor_panel.setVisible(False)
        self._update_individual_crop_info()
        self._update_individual_editor_hint()
        self._update_controls()

        # 2.4: التحرير مدمج في مكان الصورة — لا نوافذ منفصلة إطلاقًا.
        self.preview_tabs.blockSignals(True)
        self.preview_tabs.setCurrentWidget(self.edit_tab)
        self.preview_tabs.blockSignals(False)
        # 2.7: أثناء التحرير تُخفى بطاقة المنتج وشريط الـ ZIP — معلوماتهما
        # معروضة في ترويسة المحرر، وهذا يمنح الصورة مساحة أكبر
        # على الشاشات القصيرة من دون أي تداخل أو قص.
        self.selected_product_card.setVisible(False)
        self.results_action_bar.setVisible(False)
        self.unified_editor.canvas.setFocus(Qt.OtherFocusReason)

        # 2.9.11 — المالك أبلغ: «التحرير محشور في زاوية والصورة 35%».
        # النافذة الموسّعة كانت موجودة لكنها تحتاج نقرة زر يجهلها،
        # والمسار الافتراضي كان التبويب المدمج الضيق. فصار التحرير
        # يُفتح في نافذة مستقلة بحجم كامل مباشرة (يمكن إلغاء السلوك
        # من الإعدادات، والزر F11 يرجّعه للتبويب في أي لحظة).
        if self._prefers_standalone_editor():
            self._open_expanded_editor()

    def _prefers_standalone_editor(self) -> bool:
        """هل يُفتح التحرير في نافدة مستقلة تلقائيًا؟ (افتراضيًا: نعم)

        محفوظ في `QSettings` فمن يفضل التبويب المدمج لا يُفرض عليه
        سلوك جديد؛ والقراءة محمية لأن خطأ في الإعدادات لا يجوز أن
        يمنع التحرير من العمل أصلاً.
        """
        try:
            settings = getattr(self, "settings", None)
            if settings is None:
                from PySide6.QtCore import QSettings

                settings = QSettings("MarketImageStudio", "MarketImageStudio")
            raw = settings.value("editor/standalone_window", True)
            if isinstance(raw, str):
                return raw.strip().lower() not in ("false", "0", "no", "")
            return bool(raw)
        except Exception:
            return True

    # ------------------------------------------------ 2.9.6 صفحة تحرير موسّعة
    def _toggle_expanded_editor(self) -> None:
        """فتح/إغلاق صفحة التحرير الموسّعة (النقطة 4).

        الفكرة: لا ننشئ محرّرًا ثانيًا — ننقل ودجت المحرّر نفسه
        وتذييله إلى نافذة بملء الشاشة، فتبقى الصورة والتاريخ
        وكل التعديلات غير المحفوظة سليمة تمامًا في الاتجاهين.
        """
        window = getattr(self, "_expanded_editor_window", None)
        if window is not None and window.isVisible():
            window.close()
            return
        self._open_expanded_editor()

    def _open_expanded_editor(self) -> None:
        # الحارس: لا نوسّع قبل أن تكتمل مرساة التبويب. يقبل أيضًا
        # الحالة التي يُسنَد فيها المحرّر مباشرة (هياكل الاختبار)،
        # فالمطلوب فعليًا وجود محرّر وتخطيط تبويب يُرجَع إليه.
        if not (hasattr(self, "_editor_host_layout")
                or "unified_editor" in self.__dict__
                or self._editor_ready()):
            return
        if not hasattr(self, "_editor_tab_layout"):
            return
        if getattr(self, "_expanded_editor_window", None) is not None:
            self._expanded_editor_window.raise_()
            self._expanded_editor_window.activateWindow()
            return

        window = QDialog(self)
        window.setWindowTitle(f"{APP_NAME} — صفحة التحرير الموسّعة")
        window.setObjectName("expandedEditorWindow")
        window.setModal(False)
        window.setLayoutDirection(Qt.RightToLeft)
        window.setSizeGripEnabled(True)
        window.setWindowFlags(
            Qt.Window
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        layout = QVBoxLayout(window)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # شريط معلومات مصغّر يكرّر بيانات الصنف داخل النافذة الموسّعة
        info = QLabel(
            f"{self.individual_editor_product_label.toolTip() or self.individual_editor_product_label.text()}"
            f"  —  {self.individual_editor_meta_label.toolTip() or self.individual_editor_meta_label.text()}"
        )
        info.setObjectName("expandedEditorInfo")
        info.setWordWrap(True)
        layout.addWidget(info)
        self._expanded_info_label = info

        # نقل المحرّر والتذييل إلى النافذة (نفس الكائنات تمامًا)
        layout.addWidget(self.unified_editor, 1)
        layout.addWidget(self._editor_tab_footer)

        # لافتة داخل التبويب توضح أن المحرّر مفتوح في نافذة موسّعة
        placeholder = QLabel(
            "المحرّر مفتوح الآن في صفحة موسّعة.\n"
            "أغلق النافذة الموسّعة (أو اضغط F11) للعودة إلى التحرير المدمج."
        )
        placeholder.setObjectName("expandedEditorPlaceholder")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setWordWrap(True)
        self._editor_tab_layout.insertWidget(1, placeholder, 1)
        self._expanded_placeholder = placeholder

        # الأدوات المتقدمة تُفتح تلقائيًا — فالمساحة تتسع لها هنا
        self._expanded_prev_advanced = bool(
            self.unified_editor.advanced_toggle_btn.isChecked())
        if not self._expanded_prev_advanced:
            self.unified_editor.advanced_toggle_btn.setChecked(True)

        window.finished.connect(lambda _r: self._close_expanded_editor())
        window.installEventFilter(self)
        self._expanded_editor_window = window

        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            window.resize(int(available.width() * 0.94),
                          int(available.height() * 0.92))
            window.move(available.center() - window.rect().center())
        window.show()
        window.raise_()
        window.activateWindow()
        # 2.9.11 — في النافذة المستقلة الصورة هي المقصود، فنفرض لها
        # حدًا أدنى حقيقيًا (55% من ارتفاع النافذة) حتى لا تزحف الأشرطة
        # واللوحات على مساحتها كما كان يحدث (شكوى «الصورة 35%»).
        try:
            floor = max(320, int(window.height() * 0.55))
            self.unified_editor.canvas.setMinimumHeight(floor)
            self._expanded_canvas_floor = floor
        except Exception:
            self._expanded_canvas_floor = 0
        QTimer.singleShot(0, lambda: self.unified_editor.canvas.fit_view())
        self.editor_expand_button.setText("⤵ إرجاع للتبويب")

    def _close_expanded_editor(self) -> None:
        """إعادة المحرّر إلى التبويب بنفس حالته دون فقد أي تعديل."""
        window = getattr(self, "_expanded_editor_window", None)
        if window is None:
            return
        self._expanded_editor_window = None
        placeholder = getattr(self, "_expanded_placeholder", None)
        if placeholder is not None:
            self._editor_tab_layout.removeWidget(placeholder)
            placeholder.setParent(None)
            placeholder.deleteLater()
            self._expanded_placeholder = None
        # إعادة المحرّر والتذييل إلى موضعهما الأصلي في التبويب
        self._editor_tab_layout.insertWidget(1, self.unified_editor, 1)
        self._editor_tab_layout.addWidget(self._editor_tab_footer)
        self.unified_editor.show()
        self._editor_tab_footer.show()
        if not getattr(self, "_expanded_prev_advanced", False):
            self.unified_editor.advanced_toggle_btn.setChecked(False)
        # رفع الحد الأدنى الخاص بالنافذة الموسّعة؛ لو بقي لأفسد
        # تبويب التحرير المدمج على الشاشات القصيرة.
        if getattr(self, "_expanded_canvas_floor", 0):
            self.unified_editor.canvas.setMinimumHeight(140)
            self._expanded_canvas_floor = 0
        self.editor_expand_button.setText("⛶ توسيع الصفحة")
        window.deleteLater()
        QTimer.singleShot(0, lambda: self.unified_editor.canvas.fit_view())

    def _units_label_for_code(self, code: str | None) -> str:
        """2.9.6: وحدات الصنف الحقيقية من الإكسل لترويسة المحرّر.

        كانت الوحدة مثبتة نصّاً ("حبة") فتناقض اسم الملف الناتج الذي
        يجمع كل وحدات الإكسل (النقطة 3). الآن تُقرأ من نفس المصدر.
        """
        if not code:
            return "غير محددة"
        index = getattr(self, "v2_catalog_index", None)
        if index is None:
            return "— (الإكسل غير محمّل)"
        try:
            units = list(index.units_for_code(str(code)) or [])
        except Exception:
            units = []
        if not units:
            return "غير موجودة في الإكسل"
        try:
            from engine_v2.naming_v2 import clean_unit
            cleaned = [clean_unit(u) for u in units]
            units = [u for u in cleaned if u] or units
        except Exception:
            pass
        return " + ".join(units)

    def _exit_individual_edit_mode(self) -> None:
        """2.3: إنهاء جلسة التحرير المدمج والعودة لتبويب النتيجة."""
        if self.individual_worker is not None and self.individual_worker.isRunning():
            return
        # 2.9.6: لا تُترك النافذة الموسّعة معلقة بعد إنهاء الجلسة
        expanded = getattr(self, "_expanded_editor_window", None)
        if expanded is not None:
            expanded.close()
        self._individual_edit_source_name = None
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
        # 2.6: تفريغ المحرر الموحد عند إنهاء الجلسة
        if self._editor_ready():
            self.unified_editor.clear()
        self.individual_editor_state_label.setText("جاهز للتحرير")
        self.individual_editor_state_label.setProperty("previewPending", False)
        # 2.7: إعادة إظهار بطاقة المنتج وشريط الإجراءات بعد إنهاء التحرير
        if hasattr(self, "selected_product_card"):
            self.selected_product_card.setVisible(True)
        if hasattr(self, "results_action_bar"):
            self.results_action_bar.setVisible(True)
        if self.preview_tabs.currentWidget() is self.edit_tab:
            self.preview_tabs.blockSignals(True)
            self.preview_tabs.setCurrentWidget(self.output_preview)
            self.preview_tabs.blockSignals(False)
        self._render_selected_preview()

    def _on_individual_editor_closed(self, _result: int) -> None:
        """توافقية مع الملحقات القديمة — المحرر أصبح مدمجًا منذ 2.3."""
        self._exit_individual_edit_mode()

    def _scroll_to_previews(self) -> None:
        self.preview_tabs.setCurrentWidget(self.output_preview)
        self.output_preview.viewer.setFocus(Qt.OtherFocusReason)

    def _individual_editable_item(self) -> BatchItemResult | None:
        """الصف القابل للتحرير — **لا يشترط الربط برقم صنف**.

        العلة التي رصدها المالك («المحرر يرفض ولا يحفظ»): كان الشرط
        ``if not item.item_code`` يرفض كل صورة غير مرتبطة، وعند المالك
        104 من 109 صورة بلا باركود مقروء ⇒ المحرر مرفوض عمليًا على
        معظم عمله. والواقع معكوس: يحتاج **تعديل الصورة أولًا** (قص/
        تحسين/تنظيف) ثم يربطها بالصنف.

        الآن يكفي: صف واحد محدَّد + ملف مصدر موجود. أما الربط فيبقى
        شرطًا لمسار المحرك ``apply_individual_image_edit`` وحده (وهو
        يرفع «اربط الصورة برقم صنف صحيح قبل تحسينها»)، ولذلك يوجَّه
        غير المرتبط إلى مسار الحفظ المستقل ``_save_editor_draft``.
        """
        selected = self._selected_result_items()
        if len(selected) != 1:
            return None
        item = selected[0]
        source = self._result_path(item.source_path)
        if source is None or not source.is_file():
            return None
        return item

    def _individual_linked_item(self) -> BatchItemResult | None:
        """الصف المرتبط فعلًا — لمسار المحرك الذي يشترط رقم الصنف."""
        item = self._individual_editable_item()
        if item is None or not item.item_code:
            return None
        return item

    def _editor_draft_path(self, source_name: str) -> Path | None:
        """مسار حفظ مسوّدة المحرر لصورة غير مرتبطة.

        تُحفظ داخل مجلد المهمة إن وُجد، وإلا بجوار الصورة الأصلية —
        فجهة «المجلد المنجز» قد تعمل بلا ``current_workspace``.
        """
        base = self.current_workspace
        if base is None:
            item = self._individual_editable_item()
            source = self._result_path(item.source_path) if item is not None else None
            if source is None:
                return None
            base = source.parent
        draft_dir = Path(base) / "editor_drafts"
        try:
            draft_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return None
        return draft_dir / f"{Path(source_name).stem}.edited.png"

    def _save_editor_draft(self, *, silent: bool = False,
                           source_name: str = "") -> Path | None:
        """حفظ تعديلات المحرر **أثناء العمل** بلا اشتراط الربط.

        هذا هو إصلاح علة المالك: التعديل يُحفظ فورًا على القرص، فلا
        يُفقد عند الانتقال إلى صورة أخرى أو إغلاق الصفحة، وعند الربط
        لاحقًا يُعالج المصدر **المعدَّل** لا الأصلي.

        2.9.13 (م-12): ``source_name`` الصريح يسمح بحفظ مسودة الصف
        **السابق** قبل أن يتحول التحديد إلى صف آخر. بدونه كان
        الحفظ يستخرج الاسم من التحديد الجديد ─ فيُكتب عمل الصنف
        الأول في مسودة الصنف الثاني، وهو نفس فساد البيانات من باب
        آخر.
        """
        editor = getattr(self, "unified_editor", None)
        if source_name:
            key = str(source_name)
            if editor is None or not editor.has_image():
                return None
        else:
            item = self._individual_editable_item()
            if item is None or editor is None or not editor.has_image():
                if not silent:
                    QMessageBox.information(
                        self, APP_NAME,
                        "حدد صفًا واحدًا وحمّل صورته في المحرر قبل الحفظ.")
                return None
            key = item.source_name
        result_bgr = editor.get_result_bgr()
        if result_bgr is None:
            if not silent:
                QMessageBox.warning(self, APP_NAME, "تعذر قراءة ناتج المحرر.")
            return None
        target = self._editor_draft_path(key)
        if target is None:
            if not silent:
                QMessageBox.warning(self, APP_NAME, "تعذر تحديد مكان حفظ المسودة.")
            return None
        try:
            import cv2 as _cv2

            ok, buffer = _cv2.imencode(".png", result_bgr)
            if not ok:
                raise RuntimeError("imencode فشل")
            buffer.tofile(str(target))
        except Exception as exc:
            if not silent:
                QMessageBox.warning(self, APP_NAME, f"تعذر حفظ التعديل: {exc}")
            return None
        drafts = getattr(self, "_editor_drafts", None)
        if drafts is None:
            drafts = {}
            self._editor_drafts = drafts
        drafts[key] = target
        self._individual_editor_dirty = False
        label = getattr(self, "individual_editor_state_label", None)
        # لا تُغير لافتة الحالة حين يكون الحفظ للصف السابق
        # أثناء المزامنة، فاللافتة تخص الصف المعروض لا المنقول عنه.
        if label is not None and not source_name:
            label.setText(f"✓ حُفظ التعديل — {target.name}")
        return target

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
            self.status_label.setText("حدد صفًا واحدًا أولاً لاستخدام القص اليدوي.")
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
            # 2.6: إعادة تحميل الأصل في المحرر الموحد يلغي كل التعديلات غير المحفوظة
            if self._editor_ready():
                self.unified_editor.load_image(str(source))
                # 2.9.13 (م-12): الوجهة تُحدّث مع كل تحميل بلا استثناء
                self._editor_loaded_source_name = item.source_name
        self._individual_preview_active = False
        self._individual_preview_path = None
        self.individual_show_preview_button.setEnabled(False)
        self.individual_editor_state_label.setText("جاهز للتحرير")
        self._update_individual_crop_info()
        self._update_individual_editor_hint()
        self.status_label.setText("أُعيدت الصورة والخيارات إلى الحالة الأصلية — كل التعديلات غير المحفوظة أُلغيت.")

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
                "حدد صفًا واحدًا فقط لتعديل صورته.",
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
        # إصلاح علة المالك: الصورة **غير المرتبطة** لم تكن تُحفظ إطلاقًا
        # (المحرك يرفع «اربط الصورة برقم صنف صحيح قبل تحسينها»). الآن
        # تُحفظ تعديلاتها كمسوّدة على القرص فورًا، فلا يُفقد العمل،
        # ويُعالج المصدر المعدَّل عند الربط لاحقًا.
        if not item.item_code or self.current_workspace is None:
            if preview_only:
                self._invalidate_individual_preview()
                return
            saved = self._save_editor_draft()
            if saved is not None and not getattr(self, "_headless_mode", False):
                QMessageBox.information(
                    self,
                    APP_NAME,
                    "حُفظ التعديل. الصورة غير مرتبطة برقم صنف بعد، فعند ربطها"
                    " ستُعالَج الصورة المعدَّلة لا الأصلية.",
                )
            return

        self._pending_individual_position = self._capture_results_position()
        self._individual_preview_active = False
        manual_crop: tuple[float, ...] | None = None
        if manual_crop_enabled and self._individual_crop_box is not None:
            manual_crop = self._individual_crop_box
            target_ratio = self.individual_crop_ratio_combo.currentData()
            if target_ratio is not None:
                manual_crop = (*manual_crop, float(target_ratio))

        # 2.6: إذا عدّل المستخدم الصورة في المحرر الموحد، نحفظ ناتج المحرر
        # كمصدر معدّل ونمرره للـ pipeline (التأطير 800×700 + التقارير تبقى كما هي)
        edited_source_path: Path | None = None
        editor_output = None
        editor = getattr(self, "unified_editor", None)
        # 2.9.13 (م-12) — حرس فساد البيانات: لا تُعتمد بكسلات من
        # المحرر إلا إن كان محمّلًا على هذا الصف بعينه. قبل هذا
        # الشرط كانت بكسلات صنف تُكتب فوق ناتج صنف آخر بلا أي
        # رسالة — وهو أخطر ما في السجل لأنه يتلف العمل ولا يُعلم به.
        if editor is not None and editor.has_image() and \
                not self._editor_matches_selection(item):
            if not getattr(self, "_headless_mode", False):
                QMessageBox.warning(
                    self, APP_NAME,
                    "المحرر محمّل على صورة غير المحددة — لم يُعتمد أي تعديل"
                    " منعًا لكتابة صورة صنف فوق صنف آخر.\n\n"
                    "أُعيدت مزامنة المحرر مع الصف المحدد — أعد التعديل"
                    " ثم اضغط «حفظ واعتماد التعديل».")
            self._sync_editor_to_selection(item)
            return
        if editor is not None and editor.has_image() and editor.has_edits():
            try:
                result_bgr = editor.get_result_bgr()
                if result_bgr is not None:
                    # تؤجَّل الكتابة إلى ما بعد معرفة وجود مخرج سابق؛ عند
                    # وجوده يحفظ العامل البكسلات فوقه مباشرة بلا PNG مرحلي.
                    editor_output = result_bgr
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    APP_NAME,
                    f"تعذر تجهيز ناتج المحرر الموحد: {exc}",
                )
                return

        # إكمال إصلاح علة المالك: إن لم توجد تعديلات حيّة في المحرر
        # لكن هناك **مسوّدة محفوطة** لهذه الصورة (حُفِظت قبل الربط)،
        # فالمعالجة تعتمد المسوّدة لا الأصل — وهذا يمنع فقد العمل
        # اليدوي الذي كان يضيع سابقًا.
        if editor_output is None and edited_source_path is None:
            drafts = getattr(self, "_editor_drafts", None) or {}
            draft = drafts.get(item.source_name)
            if draft is None:
                candidate = self._editor_draft_path(item.source_name)
                if candidate is not None and candidate.is_file():
                    draft = candidate
            if draft is not None and Path(draft).is_file():
                edited_source_path = Path(draft)

        # 2.9.12 — إصلاح «لا يحفظ بعد الطمس»: التحرير الفردي إعادة
        # معالجة دائمًا لصفٍّ له مخرَج قائم، فيجب أن يُكتب فوق
        # الملف نفسه. بدون ذلك يُكتب الناتج في اسم جديد ويبقى
        # الصف مشيرًا للقديم، فيرى المالك أن الطمس لم يُحفظ.
        # م-تعديل-الصنف: المسارات الناتجة تُحفظ غالبًا نسبية لمساحة العمل.
        # فحص Path النسبي مباشرةً كان ينظر إلى مجلد تشغيل التطبيق، فيحكم
        # خطأً بأن الناتج غير موجود ثم يولّد نسخة جديدة (-2/-3) عند التعديل.
        # نحوله إلى مسار مطلق عبر _result_path قبل تمريره لمحرك إعادة المعالجة.
        _previous_raw = str(getattr(item, "output_path", "") or "")
        _previous_path = self._result_path(_previous_raw) if _previous_raw else None
        _previous_output = (str(_previous_path)
                            if _previous_path is not None and _previous_path.is_file()
                            else "")
        self._pending_individual_previous_output = _previous_output

        # لا يوجد مخرج سابق (أو المطلوب معاينة فقط): نحتاج pipeline
        # مرة واحدة. نخزن WebP بلا فقدان بدل PNG أبطأ وأكبر.
        if editor_output is not None and (preview_only or not _previous_output):
            staging_dir = Path(self.current_workspace) / "staging"
            staging_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = staging_dir / "unified-edited-source.webp"
            try:
                import cv2 as _cv2
                ok, buffer = _cv2.imencode(
                    ".webp", editor_output, [_cv2.IMWRITE_WEBP_QUALITY, 101])
                if not ok:
                    raise RuntimeError("فشل ترميز ناتج المحرر")
                buffer.tofile(str(tmp_path))
                edited_source_path = tmp_path
            except Exception as exc:
                QMessageBox.warning(self, APP_NAME,
                                    f"تعذر تجهيز ناتج المحرر الموحد: {exc}")
                return

        if edited_source_path is not None or editor_output is not None:
            # التعديلات طُبقت داخل المحرر — نعطل المعالجات المكررة في الـ pipeline
            self.individual_worker = IndividualEditWorker(
                self.current_workspace,
                item.source_name,
                preview_only=preview_only,
                manual_crop=None,
                smart_enhance=False,
                enhancement_strength=0,
                smart_crop=False,
                auto_straighten=False,
                remove_background=False,
                image_options=self._final_image_options(),
                blur_dates=False,
                deglare=False,
                manual_rotation=0.0,
                edited_source_path=edited_source_path,
                previous_output=_previous_output,
                editor_output=editor_output,
            )
        else:
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
                blur_dates=self.individual_blur_dates_check.isChecked(),
                deglare=self.individual_deglare_check.isChecked(),
                manual_rotation=self._current_manual_tilt(),
                previous_output=_previous_output,
            )
        self.individual_worker.progress_changed.connect(self._on_progress)
        self.individual_worker.completed.connect(self._on_individual_edit_completed)
        self.individual_worker.failed.connect(self._on_individual_edit_failed)
        self.individual_worker.finished.connect(self._on_individual_worker_finished)
        self._track_worker(self.individual_worker)
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

        if isinstance(payload, EditorDirectSaveResult):
            # المسار السريع: نفس output_path بقي كما هو، فلا نعيد تشغيل
            # pipeline ولا ننشئ صورة/صفًا جديدًا. نحدّث الواجهة فقط.
            self._individual_editor_dirty = False
            self._individual_preview_active = False
            self._individual_preview_path = None
            self.individual_show_preview_button.setEnabled(False)
            if self._editor_ready():
                self.unified_editor.clear()
            self._populate_results(restore_position=restore_position)
            self.progress.setRange(0, 1)
            self.progress.setValue(1)
            self.progress.setFormat("حُفظ تعديل المحرر مباشرة")
            self.status_label.setText(
                "تم حفظ تعديل المحرر فوق صورة الصنف نفسها سريعًا — دون إعادة معالجة أو نسخة جديدة.")
            self.individual_editor_state_label.setText("تم الحفظ المباشر")
            self.individual_editor_state_label.setProperty("previewPending", False)
            self._update_individual_editor_hint()
            try:
                saver = getattr(self, "v2_save_session", None)
                if callable(saver):
                    saver()
                # المجدول يحدّث ZIP بالخلفية ويجمع التعديلات المتلاحقة.
                self._refresh_delivery_zip()
            except Exception:
                pass
            self._update_controls()
            self._exit_individual_edit_mode()
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
        # 2.6: بعد الحفظ الناجح نفرغ المحرر الموحد (التعديلات اعتُمدت)
        if self._editor_ready():
            self.unified_editor.clear()
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
        self._exit_individual_edit_mode()

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
        # 2.9: خط التطبيق نفسه يخضع للمقياس التلقائي — لا رقم ثابت
        scale = getattr(self, "ui_scale", None)
        base_pt = 10 if scale is None else max(7, scale.font(10))
        QApplication.setFont(QFont("Segoe UI", base_pt))
        self._set_scaled_stylesheet(
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
            QFrame#editorHeader { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0f2747, stop:0.55 #163d68, stop:1 #3b2575); border: 1px solid #355b83; border-radius: 13px; }
            QFrame#editorFooter { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ffffff, stop:1 #eef4ff); border: 1px solid #bdcde0; border-radius: 12px; }
            QDialog#expandedEditorWindow { background: #f4f7fc; }
            QLabel#expandedEditorInfo { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0f2747, stop:1 #3b2575); color: #ffffff; font-weight: 700; font-size: 13px; padding: 8px 14px; border-radius: 10px; }
            QLabel#expandedEditorPlaceholder { color: #5a6a80; font-size: 13px; background: #ffffff; border: 2px dashed #bdcde0; border-radius: 12px; padding: 24px; }
            QLabel#editorProductLabel { color: #ffffff; font-size: 17px; font-weight: 900; background: transparent; }
            QLabel#editorMetaLabel { color: #d6e7f7; font-size: 10px; background: transparent; }
            QLabel#editorStateBadge { color: #07543c; background: #d9f8ec; border: 1px solid #70cfad; border-radius: 13px; padding: 7px 13px; font-weight: 900; }
            QLabel#editorStateBadge[previewPending="true"] { color: #7a4300; background: #fff0b8; border: 1px solid #e5ad26; }
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
            QToolTip { background: #10233d; color: #eaf3ff; border: 1px solid #3f6da0; border-radius: 6px; padding: 7px 10px; font-size: 11px; font-weight: 700; }
            QComboBox { min-height: 26px; padding-left: 8px; padding-right: 8px; background: #ffffff; border: 1px solid #c4d2e0; border-radius: 7px; }
            QComboBox:hover { border-color: #5b9bd0; }
            QComboBox:focus { border: 2px solid #2c8ac6; }
            QComboBox::drop-down { border: none; width: 22px; }
            QComboBox QAbstractItemView { background: #ffffff; color: #17324d; border: 1px solid #b9cbdd; border-radius: 7px; selection-background-color: #d9ebff; selection-color: #0f2747; padding: 4px; }
            QLineEdit { background: #ffffff; border: 1px solid #c4d2e0; border-radius: 7px; padding: 6px 9px; selection-background-color: #bcd9f2; }
            QLineEdit:hover { border-color: #5b9bd0; }
            QLineEdit:focus { border: 2px solid #2c8ac6; background: #fbfdff; }
            QMenu { background: #ffffff; color: #17324d; border: 1px solid #b9cbdd; border-radius: 8px; padding: 5px; }
            QMenu::item { padding: 7px 24px; border-radius: 5px; }
            QMenu::item:selected { background: #d9ebff; color: #0f2747; }
            QScrollBar:vertical { width: 12px; background: #edf2f8; border-radius: 6px; margin: 2px; }
            QScrollBar::handle:vertical { background: #a7bccf; min-height: 36px; border-radius: 5px; }
            QScrollBar::handle:vertical:hover { background: #2c8ac6; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar:horizontal { height: 12px; background: #edf2f8; border-radius: 6px; margin: 2px; }
            QScrollBar::handle:horizontal { background: #a7bccf; min-width: 36px; border-radius: 5px; }
            QScrollBar::handle:horizontal:hover { background: #2c8ac6; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
            QLineEdit#catalogPath { background: #ffffff; color: #17324d; font-weight: 700; padding: 8px 10px; }
            QLabel#catalogStatus { color: #19704a; background: #edf9f3; border: 1px solid #bfe5d0; border-radius: 5px; padding: 5px 8px; font-size: 9px; }
            QListWidget#productImageList { padding: 4px; }
            QTableWidget { gridline-color: #e7edf5; }
            QTableWidget#resultsTable { padding: 0px; }
            QHeaderView::section { background: #eef3f8; color: #27496d; border: none; border-bottom: 1px solid #ccd7e4; padding: 8px; font-weight: 700; }
            QPushButton { border-radius: 7px; padding: 8px 13px; font-weight: 700; }
            QPushButton:focus { outline: none; }
            QPushButton#primaryButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1e7ec2, stop:1 #1769aa); color: white; border: 1px solid #135f9a; }
            QPushButton#primaryButton:hover { background: #125a93; }
            QPushButton#primaryButton:pressed { background: #0e4c7d; }
            QPushButton#secondaryButton { background: #eef5fc; color: #165b91; border: 1px solid #b8cee2; }
            QPushButton#secondaryButton:hover { background: #dfeefa; }
            QPushButton#textButton { background: transparent; color: #566b80; border: none; padding: 5px; }
            QPushButton#textButton:hover { color: #b42335; }
            QPushButton:disabled { background: #e5eaf0; color: #96a3b1; border-color: #d5dce5; }
            QProgressBar { background: #e8eef5; border: none; border-radius: 7px; height: 15px; text-align: center; color: #27496d; font-weight: 800; }
            QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2c8ac6, stop:1 #35b3a5); border-radius: 7px; }
            QProgressBar#tableLoadProgress { background: #e8eef5; border: none; border-radius: 3px; height: 6px; max-height: 6px; }
            QProgressBar#tableLoadProgress::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2c8ac6, stop:1 #35b3a5); border-radius: 3px; }
            QTableWidget { selection-background-color: #d9ebff; selection-color: #0f2747; alternate-background-color: #f7fafd; }
            QCheckBox { spacing: 7px; }
            QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #9fb4c8; border-radius: 4px; background: #ffffff; }
            QCheckBox::indicator:hover { border-color: #2c8ac6; }
            QCheckBox::indicator:checked { background: #1769aa; border-color: #135f9a; }
            QFrame#statCard { background: #f8fafc; border: 1px solid #dce4ef; border-radius: 9px; }
            QFrame#previewFrame { background: #f8fafc; border: 1px solid #dce4ef; border-radius: 8px; }
            QLabel#previewTitle { color: #49647e; font-weight: 700; }
            QFrame#individualEditor { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f4f1ff, stop:0.45 #eef8ff, stop:1 #f5fbff); border: 1px solid #a99bdc; border-radius: 12px; }
            QWidget#editorToolsStrip { background: transparent; }
            QLabel#editorToolSectionTitle { color: #183b56; font-weight: 900; font-size: 11px; background: transparent; }
            QLabel#manualTiltLabel { color: #0f5c6e; font-weight: 800; background: transparent; }
            QDoubleSpinBox#manualTiltSpin { background: #ffffff; border: 1px solid #63c5d6; border-radius: 7px; padding: 2px 4px; font-weight: 800; color: #0f5c6e; }
            QPushButton#manualTiltButton { background: #ffffff; border: 1px solid #63c5d6; border-radius: 7px; color: #0f5c6e; font-weight: 900; }
            QPushButton#manualTiltButton:hover { background: #e1fbff; }
            QFrame#editorEnhanceCard { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #e9f1ff, stop:1 #ffffff); border: 1px solid #8ab4f8; border-radius: 11px; }
            QFrame#editorCropCard { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #e1fbff, stop:1 #ffffff); border: 1px solid #63c5d6; border-radius: 11px; }
            QFrame#editorCompareCard { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #f0e9ff, stop:1 #ffffff); border: 1px solid #b59ae8; border-radius: 11px; }
            QFrame#editorAdvancedCard { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #fff5e5, stop:1 #ffffff); border: 1px solid #e3b96f; border-radius: 11px; }
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
            QPushButton#openImageButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #fb923c, stop:1 #ea580c); color: white; border: 1px solid #c2410c; padding: 8px 6px; }
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
            QPushButton#smartLinkButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #22c55e, stop:1 #15803d); color: #ffffff; border: 2px solid #14532d; border-radius: 9px; padding: 9px 14px; font-weight: 900; font-size: 13px; }
            QPushButton#smartLinkButton:hover { background: #16a34a; border-color: #052e16; }
            QPushButton#linkToolButton { background: #eef2ff; color: #3730a3; border: 1px solid #b8c2f4; padding: 5px 9px; }
            QPushButton#linkToolButton:hover { background: #dfe4ff; }
            QPushButton#suggestNearbyButton { background: #fff3d6; color: #8a5200; border: 1px solid #edbd55; padding: 5px 9px; }
            QPushButton#suggestNearbyButton:hover { background: #ffe5a8; }
            QPushButton#referenceLinkButton { background: #e7f8f2; color: #066a50; border: 1px solid #78cbb0; padding: 5px 9px; }
            QPushButton#referenceLinkButton:hover { background: #cef1e4; }
            QLabel#tapLinkHint { background: rgba(76, 29, 149, 0.94); color: #ffffff; border: 1px solid #8b5cf6; border-radius: 10px; padding: 10px 14px; font-weight: 800; font-size: 13px; }
            QPushButton#nutritionButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #34d399, stop:1 #059669); color: #ffffff; border: 2px solid #065f46; border-radius: 9px; padding: 5px 12px; font-weight: 900; }
            QPushButton#nutritionButton:hover { background: #10b981; }
            QPushButton#deleteOutputButton { background: #ffffff; color: #b91c1c; border: 2px solid #fca5a5; border-radius: 9px; padding: 5px 12px; font-weight: 800; }
            QPushButton#deleteOutputButton:hover { background: #fef2f2; border-color: #dc2626; }

            QFrame#fixedActionBar { background: #ffffff; border: 1px solid #cbd8e6; border-radius: 10px; }
            QLabel#deliveryHint { color: #526b82; background: transparent; }
            QPushButton#saveDeliveryButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #14b8a6, stop:1 #047857); color: white; border: 1px solid #065f46; padding: 8px 16px; font-weight: 900; }
            QPushButton#saveDeliveryButton:hover { background: #0d9488; }
            """
        )

    def _set_scaled_stylesheet(self, sheet: str) -> None:
        """2.9: يحفظ الورقة الأصلية ثم يطبّقها مقيسة بالمعامل الحالي.

        حفظ الأصل ضروري: لو قسنا الورقة المقيسة مرة أخرى عند تغيير الحجم
        لتراكم التصغير حتى تختفي الواجهة — فالمقياس يُطبق دائمًا على الأصل.
        """
        self._base_stylesheet = sheet
        scale = getattr(self, "ui_scale", None)
        self.setStyleSheet(sheet if scale is None else scale.scale_stylesheet(sheet))

    def _refresh_ui_scale(self, *, initial: bool = False) -> bool:
        """2.9: القلب الذكي — يقيس المساحة الفعلية ويعيد ضبط كل شيء.

        يُنادى عند الإقلاع، وعند كل تغيير حجم، وعند نقل النافذة لشاشة أخرى.
        يرجع True إن تغير المعامل فعليًا وأُعيد التنسيق.
        """
        width = self.width()
        height = self.height()
        if width <= 0 or height <= 0:
            screen = self.screen() or QApplication.primaryScreen()
            if screen is not None:
                geo = screen.availableGeometry()
                width, height = geo.width(), geo.height()
        dpi_ratio = 1.0
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            try:
                dpi_ratio = max(1.0, float(screen.logicalDotsPerInch()) / 96.0)
            except Exception:
                dpi_ratio = 1.0
        engine = ScaleEngine.for_size(width, height, dpi_ratio)
        current = getattr(self, "ui_scale", None)
        if current is not None and not initial and not engine.differs_from(current.factor):
            return False
        self.ui_scale = engine
        if initial:
            return True
        # إعادة تطبيق الأنماط من الورقة الأصلية بالمعامل الجديد
        base_sheet = getattr(self, "_base_stylesheet", None)
        if base_sheet:
            QApplication.setFont(QFont("Segoe UI", max(7, engine.font(10))))
            self.setStyleSheet(engine.scale_stylesheet(base_sheet))
        self._apply_scaled_metrics()
        return True

    def _apply_scaled_metrics(self) -> None:
        """2.9: يمرّر الأبعاد المبرمجة (غير CSS) عبر المقياس.

        كل عنصر يُسجّل قيمته المرجعية مرة واحدة في ``_scaled_metrics``، فيُعاد
        حسابها من المرجع دائمًا لا من القيمة المقيسة — فلا يتراكم التصغير.
        """
        scale = getattr(self, "ui_scale", None)
        if scale is None:
            return
        for widget, kind, reference in getattr(self, "_scaled_metrics", []):
            try:
                if kind == "min_height":
                    widget.setMinimumHeight(scale.px(reference))
                elif kind == "max_height":
                    widget.setMaximumHeight(scale.px(reference))
                elif kind == "min_width":
                    widget.setMinimumWidth(scale.px(reference))
                elif kind == "fixed_height":
                    widget.setFixedHeight(scale.px(reference))
                elif kind == "icon":
                    widget.setIconSize(QSize(scale.px(reference), scale.px(reference)))
            except Exception:
                continue
        # 2.9.3 إصلاح 12: عنوان قسم القائمة يُسقط عند الشدة القصوى
        # فقط (معامل ≤ 0.70) لمنع التفاف الترويسة لسطرين.
        title_label = getattr(self, "list_title_label", None)
        if title_label is not None:
            try:
                title_label.setVisible(scale.factor > 0.70)
            except Exception:
                pass
        # 2.9.4 إصلاح 17: أزرار الربط تصير رموزًا مع تلميح عند
        # الشدة القصوى وحدها (نفس عتبة إسقاط عنوان القسم)، لأن
        # العجز أفقي: تسعة أزرار بنصوصها لا تلتف إلا على خمسة أسطر.
        try:
            self._apply_link_button_text_mode(scale.factor > 0.70)
        except Exception:
            pass
        # 2.9.3 إصلاح 11: هوامش لوحة القائمة وتباعدها يُعاد حسابهما من
        # المرجع لا من القيمة الحالية، فلا يتراكم التصغير.
        pane_metrics = getattr(self, "_pane_layout_metrics", None)
        if pane_metrics is not None:
            pane_layout, pad_ref, gap_ref = pane_metrics
            try:
                pad = scale.px(pad_ref)
                pane_layout.setContentsMargins(pad, pad, pad, pad)
                pane_layout.setSpacing(scale.px(gap_ref))
            except Exception:
                pass
        # 2.9.2: بعد تحديث المصغرة يُعاد اشتقاق ارتفاع الصف وأرضية الجدول
        # وتوزيع الأعمدة — والترتيب ملزم: الصف قبل الأرضية لأنها تقرأه.
        table = getattr(self, "results_table", None)
        if table is not None:
            self._sync_table_row_height()
            table.setMinimumHeight(self._useful_table_floor())
            self._adjust_results_table_columns()
        # الحد الأدنى للنافذة نفسها يتبع المقياس حتى لا يمنع التصغير
        self.setMinimumSize(max(680, scale.px(960)), max(430, scale.px(600)))

    def _register_metric(self, widget, kind: str, reference: int):
        """2.9: يسجّل بُعدًا مرجعيًا ويطبّقه فورًا مقيسًا."""
        if not hasattr(self, "_scaled_metrics"):
            self._scaled_metrics = []
        self._scaled_metrics.append((widget, kind, reference))
        scale = getattr(self, "ui_scale", None)
        value = reference if scale is None else scale.px(reference)
        if kind == "min_height":
            widget.setMinimumHeight(value)
        elif kind == "max_height":
            widget.setMaximumHeight(value)
        elif kind == "min_width":
            widget.setMinimumWidth(value)
        elif kind == "fixed_height":
            widget.setFixedHeight(value)
        elif kind == "icon":
            widget.setIconSize(QSize(value, value))
        return widget

    # ------------------------------------------------ 2.9.3: منافذ التسمية
    def _open_naming_policy(self) -> None:
        """يفتح نافذة سياسة الوحدات والتسمية الموحدة.

        الأولوية للدالة التي يثبّتها v2_ui على النافذة (v2_open_unit_naming)
        لأنها تحمّل السياسة المحفوظة مسبقًا؛ وإن لم تكن مثبّتة (تشغيل بلا
        تكامل v2_ui) يُستورد الديالوج مباشرة حتى يعمل الزر في كل الحالات.
        """
        opener = getattr(self, "v2_open_unit_naming", None)
        if callable(opener):
            try:
                opener()
                self._after_naming_policy_changed()
                # تزامن اتجاهي: لو غيّر المالك السياسة من النافذة
                # الكاملة فلا تبقى خانة الواجهة تعرض القديمة.
                self._load_join_units_state()
                return
            except Exception as exc:
                print(f"[naming] installed opener failed: {exc}",
                      file=sys.stderr)
        try:
            from v2_ui import UnitNamingDialog
        except Exception:
            try:
                from windows_app.v2_ui import UnitNamingDialog
            except Exception as exc:
                QMessageBox.warning(
                    self, "سياسة التسمية",
                    "تعذّر فتح نافذة سياسة التسمية.\n"
                    f"السبب: {exc}")
                return
        try:
            UnitNamingDialog(self, self).exec()
            self._after_naming_policy_changed()
            self._load_join_units_state()
        except Exception as exc:
            QMessageBox.warning(self, "سياسة التسمية",
                                f"تعذّر فتح النافذة.\nالسبب: {exc}")

    # ------------------------------------------- خيار دمج الوحدات (الواجهة)
    def _naming_settings_path(self) -> Path:
        """مسار ملف سياسة التسمية — **نفس** الملف الذي تقرأه وتكتبه نافذة
        السياسة الكاملة (v2_ui.UnitNamingDialog._settings_path)، حتى لا
        تنشأ حالتان متعارضتان: خانة الواجهة تقول شيئًا والنافذة شيئًا آخر."""
        base = Path(getattr(self, "v2_data_root", None) or DATA_ROOT)
        base.mkdir(parents=True, exist_ok=True)
        return base / "naming_settings.json"

    def _load_join_units_state(self) -> None:
        """يستعيد حالة الخيار المحفوظة عند بدء التشغيل.

        أمر المالك: «يُحفظ اختيارك ويُستعاد» — فلا يُعاد ضبطه كل تشغيل.
        الافتراضي عند غياب الملف: **مُلغى** (الوحدة الواحدة `حبه`) وفق
        أمره «الوحدة تكون حبه كما السابق».
        """
        policy = ""
        try:
            p = self._naming_settings_path()
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                policy = str(data.get("unit_policy", "") or "")
        except Exception as exc:
            print(f"[naming] load join state failed: {exc}", file=sys.stderr)
        # الدمج لم يعد مسموحًا في الاسم النهائي؛ نرحّل أي اختيار قديم
        # إلى وحدة Excel مفردة فورًا كي لا يظهر خيار الواجهة مخالفًا للإنتاج.
        if policy in {"join_all_units", "replicate_all_units"}:
            try:
                p = self._naming_settings_path()
                data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
                data["unit_policy"] = "default_unit"
                data["unit_policy_explicit"] = True
                p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                self.v2_naming_policy = data
            except Exception as exc:
                print(f"[naming] migrate single unit failed: {exc}", file=sys.stderr)
        if hasattr(self, "join_units_check"):
            self.join_units_check.blockSignals(True)
            self.join_units_check.setChecked(False)
            self.join_units_check.setEnabled(False)
            self.join_units_check.blockSignals(False)
        self._load_reference_mode_state()
        self._update_naming_preview()

    def _load_reference_mode_state(self) -> None:
        """استعادة مرجع Excel المختار دون كتابة الإعداد من جديد."""
        mode = "item_code"
        try:
            p = self._naming_settings_path()
            if p.exists():
                mode = str(json.loads(p.read_text(encoding="utf-8")).get(
                    "reference_mode", mode) or mode)
        except Exception as exc:
            print(f"[naming] load reference mode failed: {exc}", file=sys.stderr)
        if mode not in {"item_code", "barcode"}:
            mode = "item_code"
        combo = getattr(self, "reference_mode_combo", None)
        if combo is not None:
            combo.blockSignals(True)
            combo.setCurrentIndex(max(0, combo.findData(mode)))
            combo.blockSignals(False)

    def _on_reference_mode_changed(self, _index: int) -> None:
        """يحفظ خيار المرجع فورًا كي تبدأ الدفعة التالية بنفس الاختيار."""
        combo = getattr(self, "reference_mode_combo", None)
        mode = str(combo.currentData() or "item_code") if combo is not None else "item_code"
        if mode not in {"item_code", "barcode"}:
            mode = "item_code"
        try:
            p = self._naming_settings_path()
            data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
            data["reference_mode"] = mode
            data["unit_policy"] = "default_unit"
            data.setdefault("unit_policy_explicit", True)
            data.setdefault("default_unit", "حبه")
            data.setdefault("scheme", "dash")
            data.setdefault("template", "{item}_{unit}-{seq}")
            data.setdefault("enabled", True)
            p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            self.v2_naming_policy = data
        except Exception as exc:
            print(f"[naming] save reference mode failed: {exc}", file=sys.stderr)
            if hasattr(self, "status_label"):
                self.status_label.setText(f"تعذّر حفظ مرجع التسمية: {exc}")
            return
        self._after_naming_policy_changed()
        self._update_naming_preview()

    def _on_join_units_toggled(self, checked: bool) -> None:
        """يحفظ اختيار المالك فورًا ويعيد تحميله في مسار المعالجة.

        الحفظ فوري لا عند إغلاق نافذة: الخيار في الواجهة الرئيسية
        ليُختار «قبل عمل أي شيء»، فلو لم يُحفظ فورًا وبدأ المالك المعالجة
        لخرجت الصور بالسياسة القديمة مع أن الخانة تُظهر الجديدة.
        """
        try:
            p = self._naming_settings_path()
            data = {}
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    data = {}
            # الدمج والنسخ المتعددان معطّلان: هذه الدالة تبقى فقط
            # للتوافق مع واجهات قديمة قد تستدعيها برمجيًا.
            data["unit_policy"] = "default_unit"
            # علم الاختيار الصريح: يمنع أي ترقية تلقائية مستقبلية من
            # نقض اختيار المالك (كما فعلت ترقية 2.9.6 القسرية).
            data["unit_policy_explicit"] = True
            data.setdefault("default_unit", "حبه")
            data.setdefault("scheme", "dash")
            data.setdefault("template", "{item}_{unit}-{seq}")
            data.setdefault("enabled", True)
            data.setdefault("reference_mode", "item_code")
            p.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                         encoding="utf-8")
            self.v2_naming_policy = data
        except Exception as exc:
            print(f"[naming] save join state failed: {exc}", file=sys.stderr)
            if hasattr(self, "status_label"):
                self.status_label.setText(f"تعذّر حفظ خيار التسمية: {exc}")
            return
        self._after_naming_policy_changed()
        self._update_naming_preview()

    def _update_naming_preview(self) -> None:
        """يعرض الاسم الناتج فعليًا وفق الخيار الحالي.

        يستخدم وحدات صنف حقيقي من الإكسل إن كان محمَّلًا — لأن معاينة
        بمثال ثابت قد تُطابق حين يُخالف الواقع (صنف بوحدة واحدة يُعرض
        كأن له ثلاثًا).
        """
        if not hasattr(self, "naming_preview_label"):
            return
        join_on = False
        mode = (str(self.reference_mode_combo.currentData() or "item_code")
                if hasattr(self, "reference_mode_combo") else "item_code")
        item = "10011205"
        units: list[str] = []
        idx = getattr(self, "v2_catalog_index", None)
        if idx is not None:
            try:
                # by_code_all هو قاموس الأكواد الفعلي في CatalogIndex
                # (لا توجد دالة codes()). نقف عند 500 مفتاح حتى لا
                # تتجمد الواجهة على كتالوج بعشرات الآلاف.
                first = ""
                for n, code in enumerate(idx.by_code_all.keys()):
                    if n >= 500:
                        break
                    if not first:
                        first = str(code)
                    u = idx.units_for_code(code)
                    if len(u) > 1:
                        item, units = str(code), u
                        break
                if not units and first:
                    # كتالوج أصنافه بوحدة واحدة: نعرض صنفًا حقيقيًا
                    # منه بدل مثال مُختلق يوهم بوحدات لا وجود لها.
                    u = idx.units_for_code(first)
                    if u:
                        item, units = first, u
            except Exception:
                units = []
        if not units:
            units = ["حبه", "شدة", "كرتون"]
        try:
            from engine_v2.naming_v2 import NamingSettings, plan_stems_for_policy
            data = dict(getattr(self, "v2_naming_policy", {}) or {})
            settings = NamingSettings.from_dict(data)
            settings.reference_mode = mode
            # الاسم النهائي بوحدة Excel مفردة دائمًا؛ لا تعيد المعاينة
            # تفعيل سياسة دمج قديمة مخزنة من إصدار سابق.
            settings.unit_policy = "default_unit"
            barcode = ""
            decision_status = ""
            primary_unit = units[0] if units else "حبه"
            if idx is not None:
                try:
                    primary_unit = str(idx.primary_unit_for_code(item) or primary_unit)
                    resolver = getattr(idx, "resolve_retail_barcode", None)
                    decision = (resolver(item, unit=primary_unit)
                                if callable(resolver) else {})
                    barcode = str(decision.get("barcode", "") or "")
                    decision_status = str(decision.get("status", "") or "")
                except Exception:
                    barcode = ""
            if mode == "barcode" and not barcode:
                base, second, third = "باركود_Excel_غير_مثبت", "—", "—"
                head = ("مراجعة مطلوبة — للصنف عدة باركودات خطية ممكنة"
                        if decision_status == "ambiguous" else
                        "معلّق — لا يوجد باركود خطي مثبت للصنف في Excel")
            else:
                def preview_for(sequence: int) -> str:
                    stems = plan_stems_for_policy(
                        item, units, sequence, total=3, settings=settings,
                        chosen_unit=primary_unit, barcode=barcode)
                    return " / ".join(stems) if stems else "—"
                base, second, third = (preview_for(1), preview_for(2),
                                       preview_for(3))
                reference = ("باركود خطي مثبت من Excel + الوحدة"
                             if mode == "barcode" else "رقم الصنف + الوحدة")
                if settings.unit_policy == "join_all_units":
                    head = f"مُفعّل — {reference} مع دمج {len(units)} وحدات من Excel"
                elif settings.unit_policy == "replicate_all_units":
                    head = f"مُفعّل — {reference} بنسخة لكل وحدة من Excel"
                else:
                    head = f"مُفعّل — {reference} بوحدة Excel: {primary_unit}"
            self.naming_preview_label.setText(
                f"{head}\n"
                f"الواجهة ★: {base}.webp\n"
                f"الثانية: {second}.webp\n"
                f"الثالثة: {third}.webp")
        except Exception as exc:
            self.naming_preview_label.setText(f"تعذّر حساب المعاينة: {exc}")

    def _after_naming_policy_changed(self) -> None:
        """يعيد توصيل جذر التسمية بعد أي حفظ حتى تُقرأ السياسة الجديدة
        في مسار المعالجة فورًا بلا إعادة تشغيل التطبيق."""
        try:
            from engine_v2 import integration_v2 as _iv
            _iv.set_naming_data_root(str(self.v2_data_root))
            settings = _iv._current_naming_settings()
            if settings is not None:
                scheme = getattr(settings, "scheme", "")
                policy = getattr(settings, "unit_policy", "")
                reference = ("باركود Excel" if getattr(settings, "reference_mode", "item_code") == "barcode"
                             else "رقم الصنف")
                if hasattr(self, "status_label"):
                    self.status_label.setText(
                        f"تم اعتماد سياسة التسمية — المرجع: {reference}"
                        f"، النمط: {scheme}"
                        f"{'، الوحدات: ' + policy if policy else ''}")
        except Exception as exc:
            print(f"[naming] reload after save failed: {exc}",
                  file=sys.stderr)

    # ------------------------------------------------ المجلدات المنجزة
    def _open_legacy_folder(self) -> None:
        """يفتح مجلد صور منجزة سابقًا داخل نفس استوديو المراجعة.

        قرار المالك (2.9.4): «حتى في ملف الصور الجاهزة سابقًا تتعدل
        هنا لأنها جاهزة أساسًا ومربوطة بالمسمّى» و«كل شيء يعمل في
        واجهة واحدة»، و«الإكسل مرجع كل شيء»، و«بمجرد إضافة الملف
        للصور والتسميات أن تتعدل مباشرة» — فلا زر تطبيق ولا نافذة
        منفصلة: التصحيح يجري فور الفتح، ثم تبقى ★ لاختيار الواجهة.
        """
        start_dir = str(Path.home())
        ws = getattr(self, "current_workspace", None)
        if ws is not None:
            try:
                if Path(ws).is_dir():
                    start_dir = str(ws)
            except Exception:
                pass
        folder = QFileDialog.getExistingDirectory(
            self, "اختر مجلد الصور المنجزة سابقًا", start_dir)
        if not folder:
            return
        self._load_legacy_folder(Path(folder), announce=True)

    def _migrate_legacy_naming(self, folder: Path) -> dict:
        """يرحّل أسماء مجلد منجَز إلى اصطلاح الترقيم الجديد.

        خيار المالك صراحةً: الترحيل التلقائي مع نسخة احتياطية
        («الثاني أفضل بحيث يصبح كل شيء ممتاز»).

        محافظ عمدًا: لا يرحّل إلا مجلدًا كل أرقامه الظاهرة ≥ 2
        (أي لا يوجد فيه `-1` يدلّ على الاصطلاح الجديد)، ويضع
        علامة إنجاز تمنع الترحيل مرتين — والثاني يفقد صورًا.

        لا يرفع استثناءً: فشل الترحيل يجب ألا يمنع فتح المجلد.
        """
        empty = {"migrated": False, "renamed": 0, "backup_dir": "",
                 "errors": [], "reason": ""}
        try:
            from engine_v2.naming_v2 import migrate_legacy_dash_names
        except Exception as exc:            # pragma: no cover - حزمة قديمة
            empty["reason"] = str(exc)
            return empty
        try:
            report = migrate_legacy_dash_names(folder, backup=True)
        except Exception as exc:            # pragma: no cover - دفاع أخير
            empty["reason"] = str(exc)
            return empty
        if report.get("errors"):
            print(f"[migration] تحذيرات الترحيل: {report['errors'][:3]}",
                  file=sys.stderr)
        return report

    def _load_legacy_folder(self, folder: Path, announce: bool = False,
                            keep_position: bool = False) -> None:
        """يمسح المجلد، يصحّح التسميات من الإكسل فورًا، ويعرضها
        في جدول الاستوديو نفسه."""
        try:
            from engine_v2.legacy_folder_v2 import (apply_legacy_plan,
                                                    plan_legacy_renames,
                                                    scan_legacy_folder,
                                                    write_legacy_barcode_review)
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME,
                                f"تعذّر تحميل محرك المجلدات المنجزة.\n{exc}")
            return

        # 2.9.12 — ترحيل تلقائي لاصطلاح الترقيم الجديد (خيار المالك).
        # المجلدات القديمة تحمل (بلا رقم، -2، -3) والاصطلاح الجديد
        # (بلا رقم، -1، -2). يجري قبل المسح ليرى المالك الأسماء
        # النهائية مباشرة، ومعه نسخة احتياطية خارج المجلد.
        migration = self._migrate_legacy_naming(folder)

        index = getattr(self, "v2_catalog_index", None)
        # يمرر Excel للمسح نفسه: الاسم الذي أصبح باركودًا يُعاد إلى
        # رقم الصنف المناظر قبل بناء الصفوف وخطة إعادة الربط.
        groups, unparsed = scan_legacy_folder(folder, index=index)
        if not groups:
            QMessageBox.information(
                self, APP_NAME,
                "لم أجد صورًا قابلة للربط في هذا المجلد.\n"
                "الأسماء المدعومة: رقم_الوحدة أو باركودExcel_الوحدة،\n"
                "مع الأولى بلا رقم ثم -1 و-2 للصور الإضافية.")
            return

        plan = plan_legacy_renames(groups, index, unparsed)
        applied = {"renames": {}, "errors": [], "items_done": 0}
        if plan.changed_rows:
            applied = apply_legacy_plan(plan)
        review_path = None
        review_error = ""
        try:
            review_path = write_legacy_barcode_review(plan, index, folder)
        except Exception as exc:
            # لا يفشل فتح الصور لو تعذر فقط إنشاء ملف CSV الخارجي.
            review_error = str(exc)

        self._legacy_folder = folder
        self._clear_deleted_result_tombstones()
        self.current_workspace = folder
        self.current_result = self._legacy_result(plan, folder)
        # 2.9.7 (يغلق A1 + A4): يجب أن يصير المجلد المنجز مساحة
        # عمل كاملة الصلاحية. بدون حالة مهمة على القرص يفشل
        # تعديل الباركود بـFileNotFoundError ويُعلن فاحص السلامة
        # فقدانًا زائفًا لأنه لا يجد حالة يقارن بها.
        legacy_state = self._persist_legacy_state(folder)
        position = self._capture_results_position() if keep_position else None
        self._populate_results(restore_position=position)
        self._show_results_page()
        self._update_controls()

        st = plan.stats
        parts = [f"المجلد المنجز: {st['items']} صنفًا و{st['images']} صورة"]
        if applied["items_done"]:
            parts.append(f"صُحّحت تسمية {len(applied['renames'])} ملف")
        elif index is None:
            parts.append("حمّل ملف الإكسل لتصحيح الوحدات تلقائيًا")
        else:
            parts.append("التسميات مطابقة للقاعدة أصلاً")
        if migration.get("migrated"):
            parts.append(
                f"رُحّلت تسمية {migration['renamed']} ملف للترقيم الجديد")
        ambiguous = list(getattr(plan, "barcode_ambiguous", []) or [])
        if ambiguous:
            parts.append(
                f"{len(ambiguous)} صنفًا له عدة باركودات ممكنة — أُبقي اسم رقم الصنف دون تخمين")
        if review_path:
            parts.append(f"حُفظ تقرير المراجعة الخارجي: {Path(review_path).name}")
        elif review_error:
            parts.append("تعذر حفظ تقرير مراجعة الباركود")
        parts.append("اضغط ★ على أي صورة لتجعلها صورة الواجهة")
        self.status_label.setText(" — ".join(parts))

        if announce:
            lines = [f"فُتح المجلد: {st['items']} صنفًا، {st['images']} صورة."]
            if migration.get("migrated"):
                lines.append(
                    f"رُحّلت تسمية {migration['renamed']} ملف إلى الترقيم الجديد"
                    " (بلا رقم، ثم 1، 2، 3).\nوحُفظت نسخة احتياطية في:\n"
                    f"{migration.get('backup_dir', '')}")
            if applied["items_done"]:
                lines.append(f"صُحّحت تسمية {len(applied['renames'])} ملف في "
                             f"{applied['items_done']} صنفًا وفق الإكسل.")
            if index is None:
                lines.append("لم يُحمّل إكسل بعد، فاستُخدمت الوحدة من اسم الملف. "
                             "اختر الإكسل في صفحة الإعداد وستُصحّح الوحدات تلقائيًا.")
            if plan.unit_conflicts:
                sample = "، ".join(
                    f"{c} ({nm}→{xl})" for c, nm, xl in plan.unit_conflicts[:3])
                lines.append(f"وحدات خالفت الإكسل فاعتُمد الإكسل: "
                             f"{len(plan.unit_conflicts)} — {sample}")
            if plan.missing_in_excel:
                lines.append(f"أصناف غير موجودة في الإكسل: "
                             f"{len(plan.missing_in_excel)} (أُبقيت أسماءها).")
            ambiguous = list(getattr(plan, "barcode_ambiguous", []) or [])
            if ambiguous:
                lines.append(
                    f"باركودات متعددة تحتاج إثباتًا من الصورة: {len(ambiguous)} — "
                    "لم أضع باركودًا عشوائيًا، وبقيت الأسماء برقم الصنف.")
                if review_path:
                    lines.append(
                        "حُفظ ملف المراجعة الخارجي بجانب الصور:\n"
                        f"{Path(review_path).name}")
                elif review_error:
                    lines.append(f"تنبيه: تعذر حفظ ملف مراجعة الباركود: {review_error}")
            if unparsed:
                lines.append(f"ملفات تُجاوزت (لا تبدأ برقم صنف): {len(unparsed)}.")
            if applied["errors"]:
                lines.append(f"أخطاء: {len(applied['errors'])} — "
                             f"{applied['errors'][0]}")
            # 2.9.7: لا نصمت إن تعذر تثبيت الحالة، لأن المالك
            # سيكتشف ذلك متأخرًا عند فشل تعديل الباركود.
            if not legacy_state.get("state_written"):
                detail = legacy_state.get("error") or "سبب غير معروف"
                lines.append(
                    "تنبيه: تعذر حفظ حالة المهمة في هذا المجلد، فقد لا "
                    "يعمل تعديل الباركود. تأكد من صلاحية الكتابة في "
                    f"المجلد.\nالتفاصيل: {detail}")
            lines.append("\nاضغط ★ على أي صورة لتجعلها صورة الواجهة للصنف.")
            QMessageBox.information(self, APP_NAME, "\n".join(lines))

    def _legacy_result(self, plan, folder: Path) -> BatchRunResult:
        """يبني نتيجة صناعية من خطة المجلد المنجز.

        حزمة المعالجة مُصرّفة (pipeline.pyc بلا مصدر) فلا يمكن تعديل
        أصنافها؛ لكنها dataclasses عادية فيمكن بناء نتيجة مطابقة
        يتعامل معها الجدول والمعاينة والنجمة بلا أي تغيير فيها.
        """
        index = getattr(self, "v2_catalog_index", None)
        items: list[BatchItemResult] = []
        # يُقرأ القرص لا الخطة: الخطة تحمل الأسماء قبل التصحيح،
        # وبعد التنفيذ تصبح 508 منها مسارات ميتة فتفشل المعاينة
        # والنجمة بـ«ملف الإخراج غير موجود» (مقيس على 991 صورة).
        for row in plan.rows:
            path = row.old_path          # حُدِّث بعد التنفيذ في apply
            target = path.with_name(row.new_name)
            if target.is_file():
                path = target
            elif not path.is_file():
                continue
            name = ""
            barcode = ""
            if index is not None:
                try:
                    rec = index.lookup_code(row.item) or {}
                    name = str(rec.get("name") or "")
                    resolver = getattr(index, "resolve_retail_barcode", None)
                    decision = (resolver(row.item, unit=row.unit)
                                if callable(resolver) else {})
                    barcode = str(decision.get("barcode", "") or "")
                except Exception:
                    pass
            unit_txt = f" — الوحدة: {row.unit}" if row.unit else ""
            star = "★ صورة الواجهة" if row.is_primary else "صورة إضافية"
            items.append(BatchItemResult(
                source_path=str(path),
                source_name=path.name,
                status="manual",
                item_code=row.item,
                product_name=name or f"الصنف {row.item}",
                barcode=barcode,
                confidence=1.0,
                explanation=f"مجلد منجز — {star}{unit_txt}"
                            + (f"\n{row.note}" if row.note else ""),
                output_path=path.name,
                match_source="legacy_folder",
            ))
        return BatchRunResult(
            workspace=str(folder),
            database_path="",
            catalog_summary={"source": "legacy_folder",
                             "items": len(plan.groups)},
            items=items,
            elapsed_ms=0.0,
            delivery_zip="",
            report_json="",
            report_csv="",
        )

    def _persist_legacy_state(self, folder: Path) -> dict:
        """يثبّت حالة مهمة حقيقية للمجلد المنجز ويودع مصادره.

        2.9.7 — يغلق A1 (إعلان فقدان زائف) وA4 (تعذر تعديل
        الباركود للملفات السابقة). القياس قبل الإصلاح على 12
        صورة من مخرجات المالك: لا job_state.json ولا خزانة،
        و`_load_state` ترفع FileNotFoundError فورًا.

        لا ترفع استثناءً: فتح المجلد للعرض يجب أن ينجح حتى على
        قرص للقراءة فقط؛ يُعاد تقرير ويُكمل العرض.
        """
        empty = {"state_written": False, "vault_deposited": False,
                 "images": 0, "error": ""}
        result = getattr(self, "current_result", None)
        if result is None:
            return empty
        try:
            from engine_v2.legacy_folder_v2 import ensure_legacy_job_state
        except Exception as exc:  # pragma: no cover - حزمة بلا المحرك
            empty["error"] = str(exc)
            return empty

        catalog_path = ""
        cp = getattr(self, "catalog_path", None)
        if cp:
            catalog_path = str(cp)
        options = None
        try:
            options = self._final_image_options()
        except Exception:
            options = None
        try:
            return ensure_legacy_job_state(
                folder, result,
                index=getattr(self, "v2_catalog_index", None),
                catalog_path=catalog_path,
                options=options)
        except Exception as exc:  # pragma: no cover - دفاع أخير
            empty["error"] = str(exc)
            return empty

    # 2.9.5 — _open_bulk_rename حُذفت مع BulkRenameDialog نهائيًا.
    # قرار المالك: لا تكرار — مكان واحد للوظيفة. المجلدات
    # المنجزة تُفتح بـ_open_legacy_folder داخل جدول المراجعة نفسه.

    def _select_catalog(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "اختيار ملف المنتجات",
            str(Path.home()),
            "ملفات الأصناف (*.xlsx *.xlsm *.xls *.csv)",
        )
        if filename:
            self.catalog_path = Path(filename)
            display_name = self.catalog_path.name
            self.catalog_edit.setText(display_name)
            self.catalog_edit.setCursorPosition(0)
            self.catalog_edit.setToolTip(f"المسار الكامل:\n{self.catalog_path}")
            self.catalog_status_label.setText("تم اختيار ملف Excel بنجاح")
            self.catalog_status_label.setToolTip(str(self.catalog_path))
            self._register_catalog_index(self.catalog_path)
            self._update_controls()

    def _ensure_catalog_index(self, timeout: float = 180.0) -> bool:
        """يضمن توفر فهرس الإكسل **قبل** أي تسمية؛ يعيد نجاحه.

        2.9.7 — علة توقيت حقيقية تُفقد الوحدات:
        ``_register_catalog_index`` يحمل الفهرس في خيط خلفي، وكتالوج
        المالك (22,087 صنفًا) يستغرق ثوانٍ. فإن بدأت الدفعة قبل
        انتهائه كان ``_CATALOG_REF["index"] is None``، فتُرجع
        ``_units_from_catalog()`` قائمة فارغة، فيسقط ``join_all_units``
        إلى وحدة واحدة: ``10001043_حبه`` بدل ``10001043_حبه_كرتون``.

        ولأنها علة **توقيت**، تظهر وتختفي بحسب سرعة الجهاز
        وحجم الإكسل — وهذا أخطر من علة ثابتة لأنها تمر بالاختبار
        على جهاز سريع وتفسد أسماء المالك على جهازه.

        الحل: قبل كل دفعة ننتطر الفهرس الجاري، وإن لم يكن قد بدأ
        نحمله متزامنًا — مع إبقاء الواجهة حية بـ``processEvents``.
        """
        from engine_v2 import integration_v2 as _integ
        if getattr(self, "v2_catalog_index", None) is not None:
            _integ.set_catalog_index(self.v2_catalog_index)
            _integ.set_naming_data_root(str(DATA_ROOT))
            return True
        path = getattr(self, "catalog_path", None)
        if path is None or not Path(path).is_file():
            return False
        thread = getattr(self, "_catalog_index_thread", None)
        deadline = time.monotonic() + max(1.0, float(timeout))
        if thread is not None and thread.is_alive():
            # التحميل جارٍ بالخلفية: انتطره بلا تجميد الواجهة.
            while thread.is_alive() and time.monotonic() < deadline:
                thread.join(0.05)
                app = QApplication.instance()
                if app is not None:
                    app.processEvents()
            if getattr(self, "v2_catalog_index", None) is not None:
                return True
        # لم يبدأ أو أخفق: حمّل متزامنًا — التسمية أولى من الاستجابة.
        try:
            from engine_v2.catalog_index_v2 import CatalogIndex
            idx = CatalogIndex()
            idx.load_excel(str(path))
            self.v2_catalog_index = idx
            _integ.set_catalog_index(idx)
            _integ.set_naming_data_root(str(DATA_ROOT))
            return True
        except Exception as exc:  # pragma: no cover - دفاعي
            print(f"[catalog] sync index load failed: {exc}", file=sys.stderr)
            return False

    def _register_catalog_index(self, path: Path) -> None:
        """تحميل فهرس الإكسل وتسجيله لمحرك التسمية (join_all_units)
        ولواجهات V2 — بالخلفية كي لا تتوقف الواجهة."""
        def _load() -> None:
            try:
                from engine_v2.catalog_index_v2 import CatalogIndex
                from engine_v2 import integration_v2 as _integ
                idx = CatalogIndex()
                idx.load_excel(str(path))
                self.v2_catalog_index = idx
                _integ.set_catalog_index(idx)
                # 2.9.3: توصيل جذر بيانات التسمية — بدونه يبقى
                # NAMING_DATA_ROOT فارغًا فترجع _current_naming_settings()
                # None دائمًا، فلا تُقرأ سياسة التسمية التي حفظها المستخدم.
                _integ.set_naming_data_root(str(DATA_ROOT))
                # قرار المالك: «بمجرد إضافة الملف للصور والتسميات
                # أن تتعدل مباشرة» — فإن كان مجلد منجز مفتوحًا قبل
                # الإكسل، يُعاد التصحيح فورًا بلا زر ولا إعادة فتح.
                # يُستدعى على خيط الواجهة لأن `_load` خلفي.
                if getattr(self, "_legacy_folder", None) is not None:
                    self.legacy_recheck_requested.emit()
                # 2.9.10: معاينة خيار دمج الوحدات تُبنى من وحدات
                # الإكسل الحقيقية، فبمجرد وصول الفهرس تُحدَّث لتعرض
                # ما سيخرج فعلًا لا مثالًا عامًا. التأجيل إلى خيط الواجهة
                # لأن لمس عناصر Qt من خيط خلفي غير مأمون.
                QTimer.singleShot(0, self._update_naming_preview)
            except Exception as exc:
                print(f"[catalog] index load failed: {exc}", file=sys.stderr)
        # 2.9.7: نحفظ مقبض الخيط ليقدر `_ensure_catalog_index`
        # أن ينتطره بدل إعادة تحميل الإكسل مرة ثانية.
        thread = threading.Thread(target=_load, daemon=True)
        self._catalog_index_thread = thread
        thread.start()

    def _refresh_legacy_after_catalog(self) -> None:
        """يعيد تصحيح المجلد المنجز المفتوح بعد وصول الإكسل."""
        folder = getattr(self, "_legacy_folder", None)
        if folder is None or not Path(folder).is_dir():
            return
        try:
            self._load_legacy_folder(Path(folder), announce=False,
                                     keep_position=True)
            self.status_label.setText(
                "وصل ملف الإكسل فصُحّحت تسميات المجلد المنجز تلقائيًا — "
                "اضغط ★ على أي صورة لتجعلها صورة الواجهة.")
        except Exception as exc:
            print(f"[legacy] refresh failed: {exc}", file=sys.stderr)

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
        # 2.9.6 — منع تشغيل دفعتين معًا: إسناد عامل جديد فوق عامل يعمل
        # يُدمّر QThread أثناء تشغيله ⇒ SIGABRT وإغلاق التطبيق بلا رسالة.
        if self.batch_worker is not None and self.batch_worker.isRunning():
            self.status_label.setText("هناك دفعة قيد المعالجة بالفعل — انتظر اكتمالها.")
            return
        # لا تستبدل نتيجة ناجحة قبل أن تكتمل المهمة الجديدة. تبقى القائمة
        # ومساحة العمل السابقة متاحتين إذا فشل Excel أو تعذرت الكتابة.
        # 2.9.7: لا تبدأ دفعة قبل توفر فهرس الإكسل، وإلا سقطت
        # سياسة join_all_units إلى وحدة واحدة ففُقدت وحدات الأسماء.
        self.status_label.setText("تهيئة فهرس الأصناف قبل المعالجة...")
        self._ensure_catalog_index()
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
            blur_dates=self.blur_dates_check.isChecked(),
            text_polish=self.text_polish_check.isChecked(),
        )
        self.batch_worker.progress_changed.connect(self._on_progress)
        self.batch_worker.completed.connect(self._on_batch_completed)
        self.batch_worker.failed.connect(self._on_worker_failed)
        self._track_worker(self.batch_worker)
        self.batch_worker.start()

    def _on_progress(self, done: int, total: int, name: str) -> None:
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)
        self.progress.setFormat(f"{done}/{total} — {name}")
        self.status_label.setText(f"معالجة: {name}")

    def _on_batch_completed(self, result: BatchRunResult) -> None:
        self._pending_batch_workspace = None
        self._clear_deleted_result_tombstones()
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
        # 2.9.9 — أُلغي تسخين البصمات البصرية مع إلغاء نسبة التشابه:
        # كان يقرأ كل صور الدفعة من القرص لبناء بصمات لم يبق لها فائدة.
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

    def _schedule_result_filters(self, *_args: object) -> None:
        """يؤخر التصفية 80ms لتجميع ضغطات الكتابة المتتابعة بلا بطء."""
        timer = getattr(self, "_result_filter_timer", None)
        if timer is not None:
            timer.start()
        else:
            self._apply_result_filters()

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
                searchable = self._result_search_cache.get(source_name)
                if searchable is None:
                    searchable = _normalize_search_text(
                        " ".join((item.source_name, item.item_code,
                                  item.product_name, item.barcode,
                                  STATUS_TEXT.get(item.status, item.status),
                                  item.explanation)))
                    self._result_search_cache[source_name] = searchable
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

    def _current_manual_tilt(self) -> float:
        """قيمة الميل اليدوي الحالية من شريط الربط المباشر (بالدرجات)."""
        spin = getattr(self, "manual_tilt_spin", None)
        try:
            return float(spin.value()) if spin is not None else 0.0
        except Exception:
            return 0.0

    def _on_manual_tilt_changed(self, value: float) -> None:
        """معاينة فورية للميل على لوحة النتيجة والأصل معًا."""
        try:
            deg = float(value)
            for pane_name in ("output_preview", "source_preview"):
                pane = getattr(self, pane_name, None)
                viewer = getattr(pane, "viewer", None)
                if viewer is not None and hasattr(viewer,
                                                  "set_preview_rotation"):
                    viewer.set_preview_rotation(deg)
            editor_preview = getattr(self, "individual_editor_preview", None)
            viewer = getattr(editor_preview, "viewer", None)
            if viewer is not None and hasattr(viewer, "set_preview_rotation"):
                viewer.set_preview_rotation(deg)
            if abs(deg) > 0.049:
                self.status_label.setText(
                    f"ميل يدوي {deg:+.1f}° — سيُطبق على الصورة عند الحفظ أو الربط")
        except Exception:
            pass

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
        """مصغرة النتيجة المعالجة (خلفية بيضاء) إن وُجدت، وإلا المصدر — لتمييز المربوط بنظرة."""
        path = None
        for candidate in (item.output_path, item.review_path, item.source_path):
            if candidate:
                p = self._result_path(candidate)
                if p is not None and p.is_file():
                    path = p
                    break
        if path is None:
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
            reader.setScaledSize(source_size.scaled(QSize(84, 84), Qt.KeepAspectRatio))
        image = reader.read()
        if image.isNull():
            return QIcon()
        pixmap = QPixmap.fromImage(image)
        if pixmap.width() > 84 or pixmap.height() > 84:
            pixmap = pixmap.scaled(84, 84, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        icon = QIcon(pixmap)
        if len(self._result_thumbnail_cache) >= 1200:
            self._result_thumbnail_cache.pop(next(iter(self._result_thumbnail_cache)), None)
        self._result_thumbnail_cache[cache_key] = icon
        return icon

    def _start_lazy_thumbnails(self) -> None:
        """تعبئة مصغرات الجدول على دفعات صغيرة دون تجميد الواجهة — سلس حتى مع مئات الصور."""
        timer = getattr(self, "_thumb_timer", None)
        if timer is not None:
            timer.stop()
        self._thumb_next_row = 0
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setInterval(15)
        self._thumb_timer.timeout.connect(self._load_thumbnail_batch)
        self._thumb_timer.start()

    def _load_thumbnail_batch(self) -> None:
        table = self.results_table
        total = table.rowCount()
        row = getattr(self, "_thumb_next_row", 0)
        if row >= total or not self._result_items_by_name:
            if getattr(self, "_thumb_timer", None) is not None:
                self._thumb_timer.stop()
            return
        end = min(row + 16, total)
        table.setUpdatesEnabled(False)
        try:
            while row < end:
                cell = table.item(row, 0)
                if cell is not None and cell.icon().isNull():
                    name = cell.data(Qt.UserRole)
                    result_item = self._result_items_by_name.get(name)
                    if result_item is not None:
                        icon = self._result_thumbnail_icon(result_item)
                        if not icon.isNull():
                            cell.setIcon(icon)
                row += 1
        finally:
            table.setUpdatesEnabled(True)
        self._thumb_next_row = row

    # حجم الدفعة الأولى: ما يملأ الشاشة وزيادة، فيرى المستخدم
    # جدولاً مأهولاً فوراً ويبدأ العمل قبل اكتمال البقية.
    _TABLE_FIRST_CHUNK = 60
    _TABLE_CHUNK = 120
    # دون هذا العدد لا معنى للتدريج — دفعة واحدة أسرع وأبسط.
    _TABLE_PROGRESSIVE_MIN = 150

    def _build_result_row_cells(self, result_item):  # type: ignore[no-untyped-def]
        """يبني خلايا صف واحد. أُخرجت من الحلقة لتُستدعى من الدفعات."""
        status_text = STATUS_TEXT.get(result_item.status, result_item.status)
        item_code = result_item.item_code or "غير مرتبط"
        barcode = result_item.barcode or "لا يوجد باركود"
        product_name = result_item.product_name or "صنف غير محدد"
        # 2.9.10 — أُزيلت النسبة المئوية من العرض بأمر المالك:
        # كان التلميح يقول «الثقة: 84%» — رقم لا يفيد المستخدم في
        # قرار ولا يعرف مم اشتُق. المعلومة المفيدة هي **لماذا** رُبطت
        # الصورة (باركود؟ اسم؟ ربط يدوي؟) وهي ما يحمله `explanation`.
        tooltip = (
            f"الصورة: {result_item.source_name}\n"
            f"اسم الصنف: {product_name}\n"
            f"رقم الصنف: {item_code}\nالباركود: {barcode}\n"
            f"{result_item.explanation or ''}"
        ).strip()

        status_cell = QTableWidgetItem(status_text)
        # تحميل كسول للمصغرات: لا نقرأ الصورة هنا — تُعبأ على دفعات لاحقاً لسلاسة الواجهة
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
        return status_cell, identity_cell, name_cell

    def _stop_progressive_fill(self) -> None:
        """يوقف أي تعبئة تدريجية جارية ويخفي مؤشر التقدم."""
        timer = getattr(self, "_fill_timer", None)
        if timer is not None:
            try:
                timer.stop()
            except RuntimeError:
                pass
        self._fill_timer = None
        self._fill_pending = []
        bar = getattr(self, "table_load_progress", None)
        if bar is not None:
            bar.setVisible(False)

    def _fill_rows_range(self, items: list, start_row: int) -> None:
        """يكتب دفعة صفوف داخل الجدول مع توسيعه بالقدر اللازم فقط.

        ملاحظة جوهرية: لا نحجز الصفوف كلها مقدمًا؛ لأن `_apply_result_filters`
        يُخفي أي صف خلاياه فارغة، فلو حجزنا 3000 صف وملأنا 60 لرأى
        المستخدم جدولاً مثقوباً. الجدول ينمو دفعة بدفعة.
        """
        table = self.results_table
        table.blockSignals(True)
        table.setUpdatesEnabled(False)
        try:
            needed = start_row + len(items)
            if table.rowCount() < needed:
                table.setRowCount(needed)
            for offset, result_item in enumerate(items):
                row = start_row + offset
                status_cell, identity_cell, name_cell = self._build_result_row_cells(result_item)
                table.setItem(row, 0, status_cell)
                table.setItem(row, 1, identity_cell)
                table.setItem(row, 2, name_cell)
                # ارتفاع موحد من غير `resizeRowsToContents` على كل الجدول:
                # المرور الشامل مرتين كان أحد أسباب التجميد مع الدفعات الكبيرة.
                table.setRowHeight(row, 96)
        finally:
            table.blockSignals(False)
            table.setUpdatesEnabled(True)

    def _populate_next_chunk(self) -> None:
        """يعبّئ الدفعة التالية من الأصناف دون تجميد الواجهة."""
        pending = getattr(self, "_fill_pending", None)
        if not pending:
            self._finish_progressive_fill()
            return
        chunk = pending[: self._TABLE_CHUNK]
        del pending[: self._TABLE_CHUNK]
        start_row = getattr(self, "_fill_next_row", 0)
        try:
            self._fill_rows_range(chunk, start_row)
        except RuntimeError:
            # الجدول أُغلق أو النافذة تُهدم — لا داعي للانهيار
            self._stop_progressive_fill()
            return
        self._fill_next_row = start_row + len(chunk)
        done = self._fill_next_row
        total = getattr(self, "_fill_total", done)
        bar = getattr(self, "table_load_progress", None)
        if bar is not None:
            bar.setValue(done)
        self.table_position_label.setText(f"جارٍ التحميل… {done} من {total}")
        if not pending:
            self._finish_progressive_fill()

    def _finish_progressive_fill(self) -> None:
        """يُنهي التعبئة: يعيد الفرز والتصفية ويخفي المؤشر."""
        self._stop_progressive_fill()
        try:
            self.results_table.setSortingEnabled(
                bool(getattr(self, "_fill_sorting_was_enabled", False))
            )
        except RuntimeError:
            return
        self._apply_result_filters()
        self._update_result_position_label()
        restore_position = getattr(self, "_fill_restore_position", None)
        if restore_position is not None and self._visible_result_rows():
            self._restore_results_position(restore_position)
            QTimer.singleShot(
                0,
                lambda position=restore_position: self._restore_results_position_if_still_selected(position),
            )
        self._fill_restore_position = None

    def _remember_nutrition_result_item(self, item) -> None:
        """يحجز اقتصاص تغذية مستقلًا حتى تلحق به أي نتيجة عامل قديمة."""
        raw = str(getattr(item, "output_path", "") or "")
        if not raw:
            return
        p = self._result_path(raw)
        key = self._norm_path_key(str(p or raw))
        registry = getattr(self, "_nutrition_result_items", None)
        if not isinstance(registry, dict):
            registry = self._nutrition_result_items = {}
        registry[key] = item

    def _restore_nutrition_result_items(self, items):
        """يعيد فقط اقتصاصات التغذية الموجودة فعليًا إذا أسقطتها لقطة قديمة."""
        registry = getattr(self, "_nutrition_result_items", None)
        if not isinstance(registry, dict) or not registry:
            return list(items or ())
        result = list(items or ())
        seen = set()
        for item in result:
            for field in ("output_path", "review_path"):
                raw = str(getattr(item, field, "") or "")
                if raw:
                    p = self._result_path(raw)
                    seen.add(self._norm_path_key(str(p or raw)))
        for key, nutrition in list(registry.items()):
            raw = str(getattr(nutrition, "output_path", "") or "")
            p = self._result_path(raw) if raw else None
            if p is None or not p.is_file():
                registry.pop(key, None)
                continue
            if key in seen:
                continue
            code = str(getattr(nutrition, "item_code", "") or "")
            insert_at = -1
            for idx, existing in enumerate(result):
                if str(getattr(existing, "item_code", "") or "") == code:
                    insert_at = idx
            result.insert(insert_at + 1 if insert_at >= 0 else len(result), nutrition)
            seen.add(key)
        return result

    def _forget_deleted_nutrition_items(self, items) -> None:
        registry = getattr(self, "_nutrition_result_items", None)
        if not isinstance(registry, dict):
            return
        for item in items or ():
            for field in ("output_path", "review_path"):
                raw = str(getattr(item, field, "") or "")
                if raw:
                    p = self._result_path(raw)
                    registry.pop(self._norm_path_key(str(p or raw)), None)

    def _remember_deleted_result_items(self, items) -> tuple[set[str], set[str]]:
        """يسجل حذفًا مقصودًا حتى لا تعيده نتيجة عامل متأخرة أو جلسة قديمة."""
        path_keys = getattr(self, "_deleted_result_path_keys", None)
        if not isinstance(path_keys, set):
            path_keys = self._deleted_result_path_keys = set()
        names = getattr(self, "_deleted_result_source_names", None)
        if not isinstance(names, set):
            names = self._deleted_result_source_names = set()
        raw_paths: set[str] = set()
        for item in items or ():
            found_path = False
            for field in ("output_path", "review_path"):
                raw = str(getattr(item, field, "") or "")
                if not raw:
                    continue
                p = self._result_path(raw)
                key = self._norm_path_key(str(p or raw))
                path_keys.add(key)
                raw_paths.add(str(p or raw))
                found_path = True
            # لا نستعمل source_name حين توجد صورة ناتجة: اقتصاص التغذية
            # يشارك المصدر مع صورة الصنف، وحظره سيخفي الصورتين خطأً.
            if not found_path:
                names.add(str(getattr(item, "source_name", "") or ""))
        return names, raw_paths

    def _drop_deleted_result_items(self, items):
        """يحجب فقط الصفوف المحذوفة صراحةً من لقطة عامل قديمة."""
        path_keys = getattr(self, "_deleted_result_path_keys", set())
        names = getattr(self, "_deleted_result_source_names", set())
        if not path_keys and not names:
            return list(items or ())
        kept = []
        for item in items or ():
            paths = []
            for field in ("output_path", "review_path"):
                raw = str(getattr(item, field, "") or "")
                if raw:
                    p = self._result_path(raw)
                    paths.append(self._norm_path_key(str(p or raw)))
            if any(key in path_keys for key in paths):
                continue
            if not paths and str(getattr(item, "source_name", "") or "") in names:
                continue
            kept.append(item)
        return kept

    def _clear_deleted_result_tombstones(self) -> None:
        """دفعة/مجلد جديد مستقل، فلا ترث حذف مساحة العمل السابقة."""
        self._deleted_result_path_keys = set()
        self._deleted_result_source_names = set()
        self._nutrition_result_items = {}

    def _populate_results(self, restore_position: tuple[str, int, int] | None = None) -> None:
        self._stop_progressive_fill()
        self.results_table.setRowCount(0)
        self.table_position_label.setText("عدد الأصناف: 0")
        self.first_item_button.setEnabled(False)
        self.last_item_button.setEnabled(False)
        self._result_items_by_name = {}
        self._result_search_cache = {}
        if self.current_result is None:
            self._update_summary(None)
            return

        result_items = self._drop_deleted_result_items(list(self.current_result.items))
        result_items = self._restore_nutrition_result_items(result_items)
        if len(result_items) != len(self.current_result.items):
            # النتيجة قد تكون لقطة أقدم من عامل خلفي؛ نوحّد الذاكرة معها
            # حتى لا يحفظ autosave العناصر المحذوفة من جديد.
            try:
                self.current_result = _dc.replace(self.current_result, items=result_items)
            except Exception:
                try:
                    self.current_result.items[:] = result_items
                except Exception:
                    pass
        self._result_items_by_name = {item.source_name: item for item in result_items}
        self._result_search_cache = {
            item.source_name: _normalize_search_text(" ".join((
                item.source_name, item.item_code, item.product_name,
                item.barcode, STATUS_TEXT.get(item.status, item.status),
                item.explanation)))
            for item in result_items
        }
        total = len(result_items)
        sorting_enabled = self.results_table.isSortingEnabled()
        self._fill_sorting_was_enabled = sorting_enabled
        # الفرز يُعاد تفعيله في النهاية وحدها؛ تركه مفتوحًا أثناء الإدخال
        # التدريجي يخلط أرقام الصفوف فتكتب الدفعة التالية فوق سابقتها.
        self.results_table.setSortingEnabled(False)

        progressive = total > self._TABLE_PROGRESSIVE_MIN
        first_count = self._TABLE_FIRST_CHUNK if progressive else total
        self._fill_rows_range(result_items[:first_count], 0)
        self._fill_next_row = first_count
        self._fill_total = total
        self._fill_restore_position = restore_position
        self.results_table.viewport().update()

        # المصغرات والملخص يبدأان فورًا على ما ظهر، ويلحقان البقية
        self._start_lazy_thumbnails()
        self._update_summary(self.current_result)
        self._apply_result_filters()
        if self.results_table.rowCount() and self._visible_result_rows():
            if restore_position is None:
                self._select_first_result()
            elif not progressive:
                self._restore_results_position(restore_position)
                QTimer.singleShot(
                    0,
                    lambda position=restore_position: self._restore_results_position_if_still_selected(position),
                )

        if not progressive:
            self.results_table.setSortingEnabled(sorting_enabled)
            self._fill_restore_position = None
            return

        # ما تبقى يُعبّأ على دفعات مع مؤشر تقدم، والمستخدم يعمل من الآن
        self._fill_pending = result_items[first_count:]
        bar = getattr(self, "table_load_progress", None)
        if bar is not None:
            bar.setRange(0, total)
            bar.setValue(first_count)
            bar.setVisible(True)
        self.table_position_label.setText(f"جارٍ التحميل… {first_count} من {total}")
        self._fill_timer = QTimer(self)
        self._fill_timer.setInterval(0)
        self._fill_timer.timeout.connect(self._populate_next_chunk)
        self._fill_timer.start()

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

    # 2.9.9 — حُذفت `_image_signature` و`_visual_similarity` مع إلغاء نسبة
    # التشابه. كانتا تقرأان الصورة من القرص وتقيسانها إلى 36×36 وتقارنان
    # 16 نقطة مركزية فقط — مقياس هش يتأثر بأقل فرق إضاءة، لذلك لم يكن
    # يعطي نتائج موثوقة. الربط الآن على عائلة الاسم والجيرة والباركود.

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
        # 2.9.9 — بعد إلغاء نسبة التشابه، الاقتراح أصبح مبنيًا على دليلين
        # موضوعيين لا على تخمين بصري: تطابق عائلة اسم الملف (الكاميرا
        # تسمي صور المنتج الواحد بجذر مشترك) والتجاور المباشر في الترتيب.
        # القرار يبقى يدويًا: هذا تحديد للمراجعة لا ربط تلقائي.
        family = self._filename_family(reference.source_name)
        competing_families = {
            self._filename_family(other.source_name) for other in competing
        } - {family}
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
            candidate_family = self._filename_family(candidate.source_name)
            same_family = bool(family and family == candidate_family)
            # لا نقترح مرشحًا ينتمي لعائلة صنف موثوق آخر — حماية من خلط الأصناف.
            if candidate_family and candidate_family in competing_families:
                continue
            distance = abs(row - anchor_row)
            if same_family:
                score = 2.0 - (distance * 0.1)
            elif distance == 1:
                # مجاور مباشر بلا عائلة متعارضة: اقتراح أضعف لكن مفيد.
                score = 1.0
            else:
                continue
            proposed.append((score, row, candidate))
        proposed.sort(reverse=True, key=lambda entry: entry[0])
        proposed = proposed[:2]
        if not proposed:
            self.status_label.setText(
                "لا يوجد مرشح واضح مجاور للمرجع; استخدم Ctrl أو Shift لتحديد الصور يدويًا، ثم اربطها بالمرجع."
            )
            QMessageBox.information(
                self,
                APP_NAME,
                "لم يُحدَّد شيء تلقائيًا: لا توجد صورة مجاورة تشترك مع المرجع في اسم الملف أو الترتيب. بقي الربط اليدوي الجماعي متاحًا وآمنًا.",
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
            f"اقتراح محافز: {len(proposed)} صورة (حسب اسم الملف والترتيب). راجع التحديد ثم اضغط ربط الصور المحددة بصنف المرجع."
        )
        self._update_controls()

    def _update_manual_selection_context(self) -> None:
        reference = self._manual_reference_item()
        selected_count = len(self._selected_link_targets())
        unresolved_count = len(self._selected_unresolved_link_targets())
        if hasattr(self, "selected_count_badge"):
            self.selected_count_badge.setText(f"المحدد: {selected_count}")
        self._refresh_smart_link_button()
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

    # 2.9.9 — حُذفت منظومة البصمات البصرية بالكامل مع إلغاء نسبة التشابه:
    # `_visual_suggestion_for` و`_visual_sig_lookup` و`_queue_visual_signatures`
    # و`_flush_visual_signature_queue` و`_on_visual_signatures_ready`
    # و`_warm_visual_signatures` و`_visual_sig_cached`. كانت تقرأ كل صورة من
    # القرص وتفكّ ترميزها لبناء بصمة، ثم تعرض نسبة مئوية لم تكن موثوقة.
    # الربط الآن بالباركود والاسم والجيرة واليد — أسرع وأدق وبلا حسابات زائدة.

    def _refresh_smart_link_button(self) -> None:
        """يُحدّث الزر الذكي: يقترح صنف أقرب صورة مرتبطة أعلى القائمة.

        2.9.9 — أُلغي الترشيح البصري ونسبة التشابه بطلب المالك. الزر الآن
        يعتمد دليلاً واحداً واضحاً ومفهوماً للمستخدم: أقرب صورة مرتبطة فوق
        الصور المحددة — وهو ترتيب التصوير الطبيعي. ولأنه لم يبق أي حساب
        بصري، أصبح تحديث الزر فوريًا تمامًا بلا أي قراءة من القرص.
        القرار يبقى يدويًا بالكامل — الزر يقترح ولا يربط إلا بضغطة المستخدم."""
        if not hasattr(self, "smart_link_button"):
            return
        unresolved, nearest_item = self._nearest_link_context()
        if not unresolved or nearest_item is None:
            self.smart_link_button.setVisible(False)
            self._smart_link_target_code = ""
            return
        reference_item = nearest_item
        self._smart_link_target_code = reference_item.item_code
        display_name = reference_item.product_name or reference_item.item_code
        # اسم مختصر للزر — الاسم الكامل في التلميح وبطاقة الصنف أعلى المعاينة.
        short = display_name if len(display_name) <= 30 else display_name[:28] + "…"
        count_txt = "صورة" if len(unresolved) == 1 else f"{len(unresolved)} صور"
        self.smart_link_button.setText(
            f"✔ اربط {count_txt} بـ: {short} ({reference_item.item_code})")
        self.smart_link_button.setToolTip(
            f"ضغطة واحدة تربط {count_txt} بالصنف:\n"
            f"{display_name}\n"
            f"رقم الصنف: {reference_item.item_code}"
            + (f" • الباركود: {reference_item.barcode}" if reference_item.barcode else "")
            + "\nالترشيح حسب أقرب صورة مرتبطة أعلى القائمة."
            + "\nالتسمية النهائية (-1، -2…) تُطبّق تلقائيًا — والتراجع متاح من الجدول،\n"
            "وإن لم يكن هذا هو الصنف الصحيح استخدم (ربط بصورة أخرى) أو اكتب الصنف في (ربط الآن)."
        )
        self.smart_link_button.setVisible(True)

    def _result_path(self, value: str) -> Path | None:
        if not value:
            return None
        candidate = Path(value).expanduser()
        if not candidate.is_absolute() and self.current_workspace is not None:
            candidate = self.current_workspace / candidate
        return candidate

    def _sync_editor_to_selection(self, item) -> None:
        """يُزامن المحرر الموحّد مع الصف المحدد (بند م-12).

        لا يبني المحرر إن لم يكن مبنيًا أصلًا (`_editor_ready`) — فلا
        تكلفة إن لم يُفتح التبويب بعد. وإن كان في المحرر عمل غير
        محفوظ لصف آخر، فمسودة تُكتب على القرص قبل التحويل، فلا
        يُفقد عمل المالك بمجرد نقلة صف.
        """
        if not self._editor_ready():
            return
        editor = self.unified_editor
        # أولًا: لا يُفقد عمل غير محفوظ يخص الصف السابق
        try:
            previous = getattr(self, "_editor_loaded_source_name", "") or ""
            if previous and editor.has_image() and editor.has_edits():
                self._save_editor_draft(source_name=previous, silent=True)
        except Exception:
            pass
        if item is None:
            try:
                editor.clear()
            except Exception:
                pass
            self._editor_loaded_source_name = ""
            return
        source = self._result_path(item.source_path)
        # المسودة المحفوطة لهذا الصف أولى من الأصل إن وجدت
        try:
            drafts = getattr(self, "_editor_drafts", None) or {}
            draft = drafts.get(item.source_name)
            if draft is None:
                candidate = self._editor_draft_path(item.source_name)
                if candidate is not None and candidate.is_file():
                    draft = candidate
            if draft is not None and Path(draft).is_file():
                source = Path(draft)
        except Exception:
            pass
        if source is None or not source.is_file():
            try:
                editor.clear()
            except Exception:
                pass
            self._editor_loaded_source_name = ""
            return
        try:
            editor.load_image(str(source))
            self._editor_loaded_source_name = item.source_name
            self._individual_editor_dirty = False
        except Exception:
            self._editor_loaded_source_name = ""

    def _editor_matches_selection(self, item) -> bool:
        """حرس فساد البيانات: هل المحرر محمّل على الصف نفسه؟

        يُستدعى قبل اعتماد أي بكسلات من المحرر. وهو الطبقة
        الثانية بعد المزامنة: حتّى لو اختلت المزامنة لسبب لم
        نتوقّعه، لا تُكتب بكسلات صنف فوق صنف آخر أبدًا.
        """
        if item is None:
            return False
        loaded = getattr(self, "_editor_loaded_source_name", None)
        if not loaded:
            # لم تُسجّل وجهة بعد — مسار قديم يُعتبر مجهولًا لا مطابقًا
            return False
        return str(loaded) == str(item.source_name)

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
            # 2.9.13 (م-12) — أخطر عطل في السجل: فساد بيانات صامت.
            #
            # كان هذا الفرع يُحدِّث وجهة الحفظ (`_individual_edit_source_name`)
            # ثم يترك `unified_editor` محمّلًا على بكسلات **الصف السابق**.
            # و`_begin_individual_edit` يأخذ `editor.get_result_bgr()` ويكتبه
            # باسم الصنف الجديد ─ فتُكتب صورة صنف فوق صنف آخر.
            # وهذا هو تفسير بلاغ المالك «يتم تكرار الصورة نفسها؟؟
            # لم أكررها» — وهو محقّق، البرنامج كرّرها.
            #
            # والمزامنة كانت موجودة في `_open_individual_editor` وحدها،
            # أي في مسار الفتح لا في مسار تغيير الصف.
            self._sync_editor_to_selection(current)

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
            self._set_product_name_text(
                getattr(self, "_product_name_placeholder",
                        "اختر صورة من القائمة لعرض اسم الصنف كاملًا"))
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
        self._set_product_name_text(product_name)
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
        # مسار فوري من فهرس Excel المحمّل: الرقم والباركود والاسم المطابق
        # حرفيًا يتحولان إلى code مؤكد قبل العامل؛ الغامض يمر للمسار المحافظ.
        resolved = None
        index = getattr(self, "v2_catalog_index", None)
        resolver = getattr(index, "resolve_reference", None)
        if callable(resolver):
            try:
                resolved = resolver(reference)
            except Exception:
                resolved = None
        if resolved is not None and resolved.get("code"):
            reference = str(resolved["code"])
            self.manual_item_edit.setText(reference)
            self.status_label.setText("تم العثور على الصنف فورًا من فهرس Excel — جارٍ الربط.")
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

    def _start_link_by_image(self) -> None:
        """ربط حر: اختر أي صورة مرتبطة (ولو بعيدة) لربط الصور المحددة بصنفها."""
        targets = self._selected_link_targets()
        if not targets:
            QMessageBox.warning(
                self,
                APP_NAME,
                "حدد أولًا الصورة (أو عدة صور بـ Ctrl) التي تريد ربطها، ثم اضغط (ربط بصورة أخرى).",
            )
            return
        linked_items = [
            item for item in (self.current_result.items if self.current_result else [])
            if item.item_code and item.source_name not in {t.source_name for t in targets}
        ]
        if not linked_items:
            QMessageBox.information(
                self, APP_NAME, "لا توجد صور مرتبطة بعد لاختيار الصنف منها.")
            return

        # 2.9.9 — أُلغي الترتيب البصري ونسبة التشابه بطلب المالك. الترتيب
        # الآن بالقرب في الجدول من الصور المحددة: أقرب صورة مرتبطة تأتي أولاً،
        # وهو ترتيب التصوير الطبيعي ومفهوم للمستخدم بلا أرقام غامضة.
        # وفتح الحوار أصبح فوريًا تمامًا: لا قراءة أقراص ولا فكّ ترميز إطلاقًا.
        target_rows = [self._row_for_source_name(t.source_name) for t in targets]
        target_rows = [r for r in target_rows if r >= 0]

        def _row_distance(item) -> tuple[int, str]:
            row = self._row_for_source_name(item.source_name)
            if row < 0 or not target_rows:
                return (10**6, item.source_name)
            return (min(abs(row - tr) for tr in target_rows), item.source_name)

        linked_items = sorted(linked_items, key=_row_distance)

        from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QListWidget,
                                       QListWidgetItem, QVBoxLayout, QLineEdit,
                                       QLabel)
        dlg = QDialog(self)
        dlg.setWindowTitle("اختر الصورة المرتبطة مصدر الصنف")
        dlg.setLayoutDirection(Qt.RightToLeft)
        dlg.resize(600, 680)
        lay = QVBoxLayout(dlg)
        hint = QLabel(
            f"ستُربط {len(targets)} صورة بصنف الصورة التي تختارها هنا —"
            " القائمة مرتبة بالقرب في الجدول: أقرب صورة مرتبطة لصورتك تأتي أولاً."
            " بعد الربط ترث الصورة رقم الصنف والوحدة وتخرج بالتسمية النهائية"
            " تلقائيًا (رقم الصنف_الوحدة-1 و-2...).")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        search = QLineEdit()
        search.setPlaceholderText("ابحث: اسم الصنف أو رقمه أو الباركود…")
        search.setMinimumHeight(38)
        lay.addWidget(search)
        lst = QListWidget()
        lst.setIconSize(QSize(72, 72))
        lst.setSpacing(4)
        lay.addWidget(lst, 1)

        def _fill(text: str = "") -> None:
            lst.clear()
            needle = (text or "").strip()
            for item in linked_items:
                hay = f"{item.product_name} {item.item_code} {item.barcode}"
                if needle and needle not in hay:
                    continue
                # 2.9.9 — لا شارات نسبة تشابه بعد الآن: الاسم والرقم والباركود
                # والمصغرة هي الدليل الموثوق، والترتيب بالقرب في الجدول.
                label = (f"{item.product_name or 'صنف'}\n"
                         f"{item.item_code} • {item.barcode or 'بلا باركود'}")
                li = QListWidgetItem(self._result_thumbnail_icon(item), label)
                li.setData(Qt.UserRole, item.item_code)
                lst.addItem(li)
            if lst.count():
                lst.setCurrentRow(0)

        search.textChanged.connect(_fill)
        _fill()

        buttons = QDialogButtonBox()
        # 2.9.9 — حُذف زر "ربط بالأقرب بصريًا" مع إلغاء نسبة التشابه.
        # القائمة مرتّبة بالقرب والأول محدد مسبقًا، فـ"ربط الآن" يكفي.
        ok_btn = buttons.addButton("ربط الآن", QDialogButtonBox.AcceptRole)
        buttons.addButton("إلغاء", QDialogButtonBox.RejectRole)
        ok_btn.setMinimumHeight(40)
        for b in buttons.buttons():
            b.setMinimumWidth(
                b.fontMetrics().horizontalAdvance(b.text()) + 28)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        lst.itemDoubleClicked.connect(lambda _i: dlg.accept())
        lay.addWidget(buttons)
        if dlg.exec() != QDialog.Accepted:
            return
        chosen = lst.currentItem()
        if chosen is None:
            QMessageBox.information(self, APP_NAME, "لم تختر أي صورة — لم يتغير شيء.")
            return
        reference = str(chosen.data(Qt.UserRole) or "").strip()
        if not reference:
            return
        # تسجيل قرار الربط للتعلم الذاتي
        try:
            from engine_v2 import learning_v2 as _lrn
            for t in targets:
                _lrn.record_link_decision(
                    source=t.source_name, item_code=reference,
                    accepted=True)
        except Exception:
            pass
        self._begin_manual_links(
            targets,
            reference,
            f"جارٍ ربط {len(targets)} صورة بالصنف {reference} من الصورة المختارة…",
        )

    def _link_selected_to_nearest_above(self) -> None:
        """ربط سريع لصور الصنف الواحد: يربط المحدد بصنف أقرب صورة مرتبطة أعلاه.

        الاستخدام النموذجي: صورة الباركود مرتبطة والجهات الأخرى للمنتج نفسه
        ملتقطة بعدها مباشرة — حتى لو كانت 4 صور للصنف تُربط دفعة واحدة.
        """
        unresolved, reference_item = self._nearest_link_context()
        if not unresolved:
            QMessageBox.information(
                self,
                APP_NAME,
                "حدد أولًا الصورة (أو عدة صور بـ Ctrl) غير المرتبطة التابعة للصنف،\n"
                "ثم اضغط (ضم للصنف الأعلى) لتُربط بنفس صنف أقرب صورة مرتبطة فوقها.",
            )
            return
        if reference_item is None:
            QMessageBox.information(
                self,
                APP_NAME,
                "لا توجد صورة مرتبطة أعلى الصور المحددة.\n"
                "اربط صورة الباركود أولًا (ربط الآن أو مطابق آليًا)، ثم استخدم هذا الزر\n"
                "لضم بقية صور الصنف إليها دفعة واحدة.",
            )
            return
        # ربط فوري بضغطة واحدة — لا نافذة تأكيد؛ شريط الحالة يعرض التفاصيل
        # والتراجع متاح من الجدول (تعديل رقم الصنف) في أي وقت.
        try:
            from engine_v2 import learning_v2 as _lrn
            for t in unresolved:
                _lrn.record_link_decision(
                    source=t.source_name,
                    item_code=reference_item.item_code,
                    accepted=True,
                )
        except Exception:
            pass
        self._begin_manual_links(
            unresolved,
            reference_item.item_code,
            f"جارٍ ضم {len(unresolved)} صورة للصنف {reference_item.item_code}…",
        )

    def _smart_link_clicked(self) -> None:
        """تنفيذ اقتراح الزر الذكي — يربط بالصنف المعروض على الزر نفسه
        (صنف أقرب صورة مرتبطة أعلى القائمة). القرار يدوي: لا ربط إلا بهذه الضغطة."""
        unresolved, nearest_item = self._nearest_link_context()
        if not unresolved:
            QMessageBox.information(
                self,
                APP_NAME,
                "حدد أولًا الصورة (أو عدة صور بـ Ctrl) غير المرتبطة ثم اضغط زر الربط السريع.",
            )
            return
        target_code = str(getattr(self, "_smart_link_target_code", "") or "")
        # 2.9.9 — أُلغي المسار البصري: الاحتياط الوحيد هو أقرب صورة مرتبطة.
        if not target_code and nearest_item is not None:
            target_code = nearest_item.item_code
        if not target_code:
            QMessageBox.information(
                self,
                APP_NAME,
                "لا يوجد صنف مرشّح للربط بعد.\n"
                "اربط صورة الباركود أولًا، أو استخدم (ربط بصورة أخرى) أو اكتب الصنف في (ربط الآن).",
            )
            return
        # تسجيل القرار للتعلم الذاتي — يحسّن ترشيحات المستقبل.
        try:
            from engine_v2 import learning_v2 as _lrn
            for t in unresolved:
                _lrn.record_link_decision(
                    source=t.source_name,
                    item_code=target_code,
                    accepted=True,
                )
        except Exception:
            pass
        self._begin_manual_links(
            unresolved,
            target_code,
            f"جارٍ ربط {len(unresolved)} صورة بالصنف {target_code}…",
        )

    # 2.9.6 — حُذف `_toggle_tap_link_mode` مع وضع «اربط بالنقر» بطلب المالك.

    def _show_tap_hint(self, text: str, msec: int = 6000) -> None:
        """يعرض التلميح العائم في شريط سفلي فوق شريط الحالة مباشرة.

        هذا الموضع لا يغطي الرأس ولا تبويبات المحرر ولا أي زر تفاعلي،
        فيختفي التداخل نهائيًا على كل دقات الشاشة."""
        try:
            self.tap_link_hint.setText(text)
            self._position_tap_hint()
            self.tap_link_hint.setVisible(True)
            self.tap_link_hint.raise_()
            self._tap_hint_timer.start(msec)
        except Exception:
            pass

    def _position_tap_hint(self) -> None:
        """يضع التلميح العائم في موضع خالٍ لا يتداخل مع أي عنصر تفاعلي.

        يبدأ من شريط سفلي فوق شريط الحالة، وإن تقاطع مع أزرار مرئية
        (على الشاشات الضيقة) يرتفع تدريجيًا حتى يجد ممرًا خاليًا؛ فإن
        تعذّر ذلك يلتصق بأسفل النافذة فوق كل شيء بأقل تغطية ممكنة."""
        hint = getattr(self, "tap_link_hint", None)
        if hint is None:
            return
        margin = 12
        max_width = max(240, min(self.width() - 2 * margin, 720))
        hint.setFixedWidth(max_width)
        hint.adjustSize()
        x = max(margin, (self.width() - hint.width()) // 2)

        bottom = self.height() - margin
        status = getattr(self, "status_label", None)
        if status is not None and status.isVisible():
            try:
                status_top = status.mapTo(self, status.rect().topLeft()).y()
                if 0 < status_top <= self.height():
                    bottom = status_top - 8
            except Exception:
                pass

        # مستطيلات الأزرار المرئية (بإحداثيات النافذة) لتفادي تغطيتها.
        obstacles: list[tuple[int, int, int, int]] = []
        try:
            from PySide6.QtWidgets import QPushButton as _QPB
            for btn in self.findChildren(_QPB):
                if not btn.isVisible() or btn.width() <= 0:
                    continue
                tl = btn.mapTo(self, btn.rect().topLeft())
                br = btn.mapTo(self, btn.rect().bottomRight())
                obstacles.append((tl.x(), tl.y(), br.x(), br.y()))
        except Exception:
            obstacles = []

        def clashes(top: int) -> bool:
            left, right = x, x + hint.width()
            low = top + hint.height()
            for bx1, by1, bx2, by2 in obstacles:
                if left < bx2 and right > bx1 and top < by2 and low > by1:
                    return True
            return False

        y = max(margin, bottom - hint.height())
        if clashes(y):
            step = 6
            candidate = y
            limit = max(margin, int(self.height() * 0.25))
            while candidate > limit:
                candidate -= step
                if not clashes(candidate):
                    y = candidate
                    break
            else:
                # لا ممر خالٍ: ألصقه بأسفل النافذة تمامًا (فوق كل شيء).
                y = max(margin, self.height() - hint.height() - 2)
        hint.move(x, y)

    # 2.9.6 — حُذف `_tap_link_cell_clicked` مع وضع «اربط بالنقر» بطلب المالك.


    # ------------------------------------------------------------------
    # حقائق التغذية — اقتصاص يدوي حر بجودة كاملة (بلا OCR)
    # ------------------------------------------------------------------
    def _open_nutrition_crop(self) -> None:
        """يفتح نافذة اقتصاص حقائق التغذية للصورة/الصنف المحدد.

        الاقتصاص يكون من الصورة الأصلية (source_path) بدقتها الكاملة،
        والناتج يُحفظ فورًا كصورة منفردة ضمن مجلد صور الصنف نفسه
        بالترقيم التلقائي الصحيح ثم يظهر مباشرة في القائمة.

        يعمل من مكانين: لوحة الربط (الصف المحدد في الجدول) وتبويب
        «تحرير مباشر» (الصورة الجاري تحريرها في المحرر الموحد)."""
        selected = None
        # جلسة تحرير مدمج نشطة؟ استخدم صورتها مباشرة — هذا ما
        # يتوقعه المستخدم عند الضغط من داخل مكان التحرير.
        edit_name = getattr(self, "_individual_edit_source_name", "") or ""
        if edit_name:
            selected = self._result_items_by_name.get(edit_name)
        if selected is None:
            selected = self._selected_result_item()
        if selected is None:
            QMessageBox.information(
                self, APP_NAME,
                "حدد أولًا صورة الصنف التي عليها جدول حقائق التغذية.")
            return
        if not selected.item_code:
            QMessageBox.information(
                self, APP_NAME,
                "هذه الصورة غير مرتبطة بصنف بعد.\n"
                "اربطها أولًا (أو حدد صورة مرتبطة للصنف نفسه) حتى تُحفظ\n"
                "صورة حقائق التغذية ضمن صور الصنف الصحيح.")
            return
        source = self._result_path(selected.source_path)
        if source is None or not source.is_file():
            QMessageBox.warning(
                self, APP_NAME,
                "الصورة الأصلية غير متوفرة على القرص — لا يمكن الاقتصاص بدقة كاملة.")
            return
        # بقية صور الصنف نفسه كبدائل — قد يكون الجدول على الجهة الخلفية.
        alternatives: list[tuple[str, str]] = []
        if self.current_result is not None:
            for it in self.current_result.items:
                if it.item_code == selected.item_code \
                        and it.source_name != selected.source_name:
                    p = self._result_path(it.source_path)
                    if p is not None and p.is_file():
                        alternatives.append((str(p), it.source_name))
        from nutrition_crop import NutritionCropDialog
        dialog = NutritionCropDialog(
            str(source), alternatives=alternatives,
            product_name=selected.product_name or selected.item_code,
            parent=self)
        # يجب تركيب أدوات الميل والحفظ قبل exec()؛ تركيبها بعد الإغلاق
        # يجعل خيار الاستبدال غير مرئي ولا يعمل في الإصدارات المجمعة.
        self._nutrition_dialog = dialog
        try:
            from nutrition_patch import patch_nutrition_crop_dialog
            patch_nutrition_crop_dialog(dialog)
        except Exception as _nutrition_patch_error:
            print(f"[nutrition] dialog patch failed: {_nutrition_patch_error}", file=sys.stderr)

        # وضع الدمج (الافتراضي): نزود النافذة بصورة الصنف
        # الناتجة ليجري لصق الجدول داخلها في الزاوية المختارة.
        product_img, product_label = self._nutrition_merge_target(selected)
        dialog.set_merge_product(product_img, product_label)

        # حفظ متكرر دون إغلاق: كل ضغطة حفظ تضيف صورة جديدة للصنف
        # فورًا والنافذة تبقى مفتوحة لاقتصاصات إضافية من نفس الصورة.
        def _on_save(cropped, on_canvas: bool, placement=None) -> None:
            name = self._save_nutrition_result(
                selected, cropped, on_canvas,
                product_img=product_img if placement is not None else None,
                placement=placement)
            if name:
                mode = ("دمج داخل صورة الصنف" if placement is not None
                        else "صورة منفصلة")
                dialog.set_status(
                    f"✓ {mode} — {name} — مرتبطة بالصنف "
                    f"{selected.item_code} — يمكنك تحديد جزء آخر أو الإغلاق")

        dialog.save_requested.connect(_on_save)
        try:
            dialog.exec()
        finally:
            if getattr(self, "_nutrition_dialog", None) is dialog:
                self._nutrition_dialog = None

    def _nutrition_merge_target(self, selected: BatchItemResult):
        """يختار صورة الصنف الناتجة التي سيُدمج الجدول داخلها.

        الأفضلية للصورة الناتجة لنفس الصف (أي الوجه المعروض)،
        وإلا فأول صورة ناتجة لنفس الصنف. يرجع (المصفوفة، وصف نصي).
        """
        from engine_v2.processor_v2 import imread_unicode
        candidates: list[tuple[str, str]] = []
        if selected.output_path:
            p = self._result_path(selected.output_path)
            if p is not None and p.is_file():
                candidates.append((str(p), p.name))
        if self.current_result is not None:
            for it in self.current_result.items:
                if it.item_code != selected.item_code or not it.output_path:
                    continue
                if it.match_source == "nutrition_crop":
                    continue  # لا ندمج داخل ناتج تغذية سابق
                p = self._result_path(it.output_path)
                if p is not None and p.is_file():
                    candidates.append((str(p), p.name))
        for path, name in candidates:
            img = imread_unicode(path)
            if img is not None:
                return img, f"الدمج في: {name}"
        return None, ""

    def _insert_item_beside_group(self, new_item: BatchItemResult) -> None:
        """يُدرج الصف الجديد بعد آخر صفٍّ يحمل رمز الصنف نفسه.

        مطلب المالك حرفيًا: «يجب أن تكون قريبة من الصنف ولا تنزل
        إلى الأسفل ليعرف المستخدم ويفهم الترتيب، يجب أن تكون
        هناك خاصية للترتيب وليس عشوائيًا».

        وإن لم يُوجد صفٌّ للصنف (حالة نادرة) يُلحَق في الذيل
        كالسابق — لا نفقد الصف أبدًا.
        """
        if self.current_result is None:
            return
        # بعض محركات النتائج تستعمل dataclass مجمّدًا أو tuple؛ نعمل
        # على نسخة ثم نستبدل النتيجة كلها عند الحاجة بدل setattr هش.
        items = list(self.current_result.items or ())
        code = str(getattr(new_item, "item_code", "") or "")
        last = -1
        if code:
            for index, existing in enumerate(items):
                if str(getattr(existing, "item_code", "") or "") == code:
                    last = index
        items.insert(last + 1 if last >= 0 else len(items), new_item)
        try:
            self.current_result = _dc.replace(self.current_result, items=items)
        except Exception:
            try:
                self.current_result.items[:] = items
            except Exception:
                # لا نرمي خطأ بعد نجاح حفظ الصورة؛ ستلتقط الجلسة والحالة
                # الصف عند إعادة البناء بدل إتلاف الملف الموجود على القرص.
                pass

    def _save_nutrition_result(self, selected: BatchItemResult,
                               cropped, on_canvas: bool,
                               product_img=None, placement=None) -> str:
        """يحفظ الاقتصاص كصورة منفردة ضمن مجلد صور الصنف ويضيفها
        للقائمة فورًا مع تحديث حزمة التسليم. يرجع اسم الملف المحفوظ
        (أو نصًا فارغًا عند الفشل)."""
        out_dir = None
        anchor = self._result_path(selected.output_path) if selected.output_path else None
        if anchor is not None:
            out_dir = anchor.parent
        else:
            # صورة أخرى للصنف لها إخراج؟
            if self.current_result is not None:
                for it in self.current_result.items:
                    if it.item_code == selected.item_code and it.output_path:
                        p = self._result_path(it.output_path)
                        if p is not None:
                            out_dir = p.parent
                            break
        if out_dir is None:
            QMessageBox.warning(
                self, APP_NAME,
                "لم يُعثر على مجلد صور الصنف — أكمل معالجة الدفعة أولًا.")
            return ""
        try:
            from nutrition_crop import save_nutrition_image
            target = save_nutrition_image(
                cropped, out_dir, selected.item_code, on_canvas=on_canvas,
                product_img=product_img, placement=placement)
        except Exception as exc:
            QMessageBox.warning(
                self, APP_NAME,
                f"تعذر حفظ صورة حقائق التغذية:\n{exc}")
            return ""
        # مسار نسبي لمساحة العمل إن أمكن — مثل بقية العناصر.
        output_value = str(target)
        if self.current_workspace is not None:
            try:
                output_value = str(target.relative_to(self.current_workspace))
            except ValueError:
                pass
        new_item = BatchItemResult(
            source_path=selected.source_path,
            source_name=target.name,
            status="manual",
            item_code=selected.item_code,
            product_name=selected.product_name,
            barcode=selected.barcode,
            confidence=1.0,
            explanation=("حقائق التغذية — مدموجة داخل صورة الصنف بجودة كاملة"
                         if placement is not None else
                         "حقائق التغذية — اقتصاص يدوي بجودة كاملة"),
            output_path=output_value,
            review_path=output_value,
            match_source="nutrition_crop",
        )
        if self.current_result is not None:
            position = self._capture_results_position()
            # 2.9.12 — أمر المالك: «صورة حقائق التغذية يجب أن تكون
            # قريبة من الصنف ولا تنزل إلى الأسفل».
            # كان ``append`` يضعها في ذيل القائمة دائمًا مهما بعُد
            # صنفها، فتنقطع عن أخواتها ويضيع الترتيب المفهوم.
            # الآن تُدرَج بعد آخر صفٍّ يحمل رمز الصنف نفسه.
            self._insert_item_beside_group(new_item)
            # هوية مستقلة: لا تشارك source_name مع الصورة الأساسية،
            # وتبقى مرئية حتى إن وصلت نتيجة عامل أقدم بعد دقائق.
            self._remember_nutrition_result_item(new_item)
            if self.current_workspace is not None:
                try:
                    from engine_v2.state_sync_v2 import sync_result_items
                    sync_result_items(self.current_workspace, self.current_result.items)
                except Exception as exc:
                    print(f"[state_sync] تعذرت مزامنة حقائق التغذية: {exc}", file=sys.stderr)
            self._populate_results(restore_position=position)
            # تحديث حزمة التسليم ZIP لتشمل الصورة الجديدة — بصمت.
            self._refresh_delivery_zip()
            try:
                saver = getattr(self, "v2_save_session", None)
                if callable(saver):
                    saver()
            except Exception as exc:
                print(f"[session] تعذر حفظ حقائق التغذية: {exc}", file=sys.stderr)
        merged_note = ("مدموجة داخل صورة الصنف" if placement is not None
                       else "كصورة منفصلة")
        self.status_label.setText(
            f"حُفظت حقائق التغذية ({merged_note}): {target.name}")
        self._show_tap_hint(
            f"🍎 تم! حقائق التغذية {merged_note} ضمن صور الصنف "
            f"{selected.item_code} باسم: {target.name}")
        return target.name

    def _delete_selected_outputs(self) -> None:
        """يحذف الصور/الصفوف المحددة من صور الصنف بعد تأكيد صريح.

        يحذف الملف الناتج من مجلد الإخراج، يزيل الصف من القائمة،
        ويحدّث حزمة ZIP — الصورة الأصلية المصدر لا تُمس أبدًا."""
        if self.current_result is None:
            return
        selected_items = self._selected_result_items()
        if not selected_items:
            QMessageBox.information(
                self, APP_NAME, "حدد أولًا الصورة (أو الصور) المراد حذفها.")
            return
        names = "\n".join(
            f"• {it.source_name}" for it in selected_items[:8])
        extra = (f"\n… و{len(selected_items) - 8} أخرى"
                 if len(selected_items) > 8 else "")
        answer = QMessageBox.question(
            self, APP_NAME,
            f"حذف {len(selected_items)} صورة من النتائج؟\n\n{names}{extra}\n\n"
            "سيُحذف الملف الناتج من مجلد الإخراج وحزمة ZIP ويُزال"
            " الصف من القائمة.\nالصورة الأصلية المصدر لن تُمس.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        position = self._capture_results_position()
        deleted = 0
        deleted_sources: set[str] = set()
        # يسجل قبل إزالة العناصر؛ العامل المتأخر قد يحمل نتيجة أقدم.
        _deleted_names, deleted_output_paths = self._remember_deleted_result_items(selected_items)
        self._forget_deleted_nutrition_items(selected_items)

        # لا تحذف ملفًا يشير إليه صف آخر غير محدد. قد يحدث هذا بعد
        # تعديل/دمج تغذية أو استئناف جلسة قديمة حيث يتشارك صفان صورة واحدة.
        selected_ids = {id(it) for it in selected_items}
        retained_paths: set[str] = set()
        for other in self.current_result.items:
            if id(other) in selected_ids:
                continue
            for attr in ("output_path", "review_path"):
                raw = str(getattr(other, attr, "") or "")
                p = self._result_path(raw) if raw else None
                if p is not None:
                    try:
                        retained_paths.add(str(p.resolve()).casefold())
                    except OSError:
                        retained_paths.add(str(p).casefold())

        for it in selected_items:
            # حذف الملف الناتج من القرص (إن وجد) — ليس المصدر أبدًا.
            # وإن كان هناك صف محتفَظ به يشير للملف، يُزال الصف المحدد فقط.
            for attr in ("output_path", "review_path"):
                raw = getattr(it, attr, "") or ""
                if not raw:
                    continue
                p = self._result_path(raw)
                if p is not None and p.is_file():
                    try:
                        path_key = str(p.resolve()).casefold()
                    except OSError:
                        path_key = str(p).casefold()
                    if path_key in retained_paths:
                        continue
                    try:
                        p.unlink()
                    except OSError:
                        pass
            try:
                self.current_result.items.remove(it)
                deleted += 1
                deleted_sources.add(str(getattr(it, "source_name", "") or ""))
            except ValueError:
                pass
        if not deleted:
            return

        # م-حذف-الصنف: لا تترك محررًا/مسودة/مرجعًا يشير إلى صف حُذف.
        # بقاء هذه الحالة كان يجعل تعديل الصف التالي يعتمد صورة الصف المحذوف
        # أو يعيد مسودة قديمة إذا ظهر الاسم نفسه في جلسة جديدة.
        drafts = getattr(self, "_editor_drafts", None)
        if isinstance(drafts, dict):
            for source_name in deleted_sources:
                draft = drafts.pop(source_name, None)
                try:
                    if draft is not None and Path(draft).is_file():
                        Path(draft).unlink()
                except OSError:
                    pass
        if getattr(self, "_manual_reference_source_name", "") in deleted_sources:
            self._manual_reference_source_name = ""
        if getattr(self, "_editor_loaded_source_name", "") in deleted_sources:
            try:
                if self._editor_ready():
                    self.unified_editor.clear()
            except Exception:
                pass
            self._editor_loaded_source_name = ""
            self._individual_editor_dirty = False
        if getattr(self, "_individual_edit_source_name", "") in deleted_sources:
            self._individual_edit_source_name = ""
            self._individual_preview_path = None
            self._individual_preview_active = False
        # لا تبقَ الحالة المحفوظة أقدم من الواجهة؛ وإلا تعيد الجلسة
        # أو نتيجة عامل لاحقة الصفوف المحذوفة بعد دقائق.
        if self.current_workspace is not None:
            try:
                from engine_v2.state_sync_v2 import sync_removed_outputs
                sync_removed_outputs(self.current_workspace,
                                     source_names=_deleted_names,
                                     output_paths=deleted_output_paths)
            except Exception as exc:
                print(f"[state_sync] تعذرت مزامنة الحذف: {exc}", file=sys.stderr)
        try:
            saver = getattr(self, "v2_save_session", None)
            if callable(saver):
                saver()
        except Exception as exc:
            print(f"[session] تعذر حفظ الحذف: {exc}", file=sys.stderr)
        self._populate_results(restore_position=position)
        self._refresh_delivery_zip()
        self.status_label.setText(f"حُذفت {deleted} صورة من النتائج")
        self._show_tap_hint(
            f"🗑 حُذفت {deleted} صورة من النتائج وحُدّثت حزمة ZIP —"
            " الصور الأصلية لم تُمس")

    def _refresh_delivery_zip(self, immediate: bool = False) -> None:
        """يجدّد حزمة التسليم ZIP بلا تجميد الواجهة.

        2.9.12 — إصلاح «البطء عند الحفظ والتعديل»:

        الأصل (``pipeline._write_delivery_zip``) يفتح الأرشيف بالوضع
        ``'w'`` ويعيد ضغط **كل** الصور بـDEFLATE مستوى 6 في كل
        نداء، متزامنًا على خيط الواجهة. فحفظ صورة واحدة في
        مجلد فيه 500 صورة يعيد ضغط 500 صورة والنافذة مجمدة.

        والصور WebP مضغوطة أصلًا، فإعادة ضغطها تكلفة بلا عائد.

        الآن: تأجيل يدمج الطلبات المتتابعة + كتابة في خيط
        خلفي + تخزين بلا ضغط للصور. و``immediate=True`` تكتب
        فورًا وتنتظر (عند الإغلاق أو قبل التسليم).
        """
        result = self.current_result
        if result is None or not getattr(result, "delivery_zip", None):
            return
        scheduler = self._delivery_zip_scheduler()
        if scheduler is None:
            self._refresh_delivery_zip_blocking()
            return

        workspace = self.current_workspace

        def _supplier():
            return (self.current_result, workspace)

        scheduler.request(_supplier)
        if immediate:
            scheduler.flush()

    def _delivery_zip_scheduler(self):
        """مجدول كتابة الحزمة (يُنشأ عند أول حاجة)، أو ``None``."""
        scheduler = getattr(self, "_zip_scheduler", None)
        if scheduler is not None:
            return scheduler
        try:
            from delivery_zip_fast import DeliveryZipScheduler
        except Exception as exc:                        # noqa: BLE001
            print(f"[delivery_zip] تعذر تحميل المجدول: {exc}",
                  file=sys.stderr)
            self._zip_scheduler = None
            return None
        scheduler = DeliveryZipScheduler(delay_seconds=2.0)
        self._zip_scheduler = scheduler
        return scheduler

    def _refresh_delivery_zip_blocking(self) -> None:
        """المسار الأصلي المتزامن — شبكة أمان وحيدة.

        يبقى لأن غياب وحدة التسريع يجب ألا يعني أبدًا حزمة
        تسليم غير محدّثة — بطءٌ أهون من نقص في التسليم.

        يحوّل المسارات النسبية إلى مطلقة مؤقتًا لأن
        ``_write_delivery_zip`` تفحص ``is_file()`` مباشرة على القيمة.
        """
        result = self.current_result
        if result is None or not getattr(result, "delivery_zip", None):
            return
        original: list[tuple[object, str]] = []
        try:
            for it in result.items:
                raw = it.output_path or ""
                if raw and not Path(raw).is_absolute():
                    resolved = self._result_path(raw)
                    if resolved is not None and resolved.is_file():
                        original.append((it, raw))
                        # dataclass مجمّد (frozen) — نعدّل مؤقتًا بطريقة آمنة.
                        object.__setattr__(it, "output_path", str(resolved))
            _vision_pipeline._write_delivery_zip(result)
        except Exception:
            pass
        finally:
            for it, raw in original:
                object.__setattr__(it, "output_path", raw)

    def _nearest_link_context(self) -> tuple[list, "BatchItemResult | None"]:
        """يرجع (الصور المحددة غير المرتبطة، أقرب صورة مرتبطة أعلاها في القائمة).

        هذه هي حالة المستخدم اليومية: صورة الباركود تُربط آليًا، وبقية جهات
        المنتج نفسه (الواجهة الأمامية وغيرها) تُلتقط بعدها بلا باركود —
        فيكون أقرب صف مرتبط أعلاها هو صنفها الصحيح.
        """
        if self.current_result is None:
            return [], None
        selected = self._selected_result_items()
        unresolved = [item for item in selected if not item.item_code]
        if not unresolved:
            return [], None
        top_row = min(
            (self._row_for_source_name(item.source_name) for item in unresolved),
            default=-1,
        )
        if top_row < 0:
            return unresolved, None
        for row in range(top_row - 1, -1, -1):
            source_cell = self.results_table.item(row, 0)
            if source_cell is None:
                continue
            candidate = self._result_items_by_name.get(
                str(source_cell.data(Qt.UserRole) or ""))
            if candidate is not None and candidate.item_code:
                return unresolved, candidate
        return unresolved, None

    @staticmethod
    def _norm_path_key(path: Path | str) -> str:
        """مفتاح مسار موحّد للمقارنة بين المنصّات (2.9.9).

        ويندوز لا يفرق بين حالات الأحرف ويقبل الفاصلين معًا،
        فمقارنة النصوص الخام تفشل بصمت ويبقى `output_path`
        مشيرًا لملف أُعيدت تسميته ⇒ تختفي الصورة. يُحلّ الرابط
        الرمزي إن أمكن، ويُوحّد الفاصل وحالة الأحرف.
        """
        text = str(path)
        try:
            text = os.path.realpath(text)
        except Exception:
            text = os.path.abspath(text)
        return os.path.normcase(os.path.normpath(text))

    def _recover_output_path(self, item: BatchItemResult,
                             code: str) -> Path | None:
        """يبحث عن ملف إخراج الصورة حين يموت المسار المحفوظ (2.9.9).

        أبلغ المالك أن ضغط ★ يُنتج «ملف الإخراج غير موجود» ثم
        تُخفى الصورة. يحدث هذا متى تغير الملف على القرص دون أن
        يتبعه السجل (ضغطة سابقة، أو تعديل يدوي في مستكشف
        الملفات). بدل إعلان الفقد، نبحث في مجلد الإخراج بثلاث
        محاولات متدرجة حسب الدقة.

        ترجع المسار الموجود فعلًا أو ``None``.
        """
        exts = (".webp", ".png", ".jpg", ".jpeg")
        # مجلدات مرشّحة للبحث: مجلد المسار المحفوظ، ثم مجلد المصدر،
        # ثم مساحة العمل ومجلد `output` فيها.
        dirs: list[Path] = []
        for raw in (item.output_path, item.review_path, item.source_path):
            p = self._result_path(raw) if raw else None
            if p is not None and p.parent.is_dir() and p.parent not in dirs:
                dirs.append(p.parent)
        if self.current_workspace is not None:
            for extra in (self.current_workspace,
                          self.current_workspace / "output"):
                if extra.is_dir() and extra not in dirs:
                    dirs.append(extra)
        if not dirs:
            return None

        stored = Path(str(item.output_path or "")).name
        stem = Path(stored).stem if stored else ""
        for folder in dirs:
            # محاولة 1 — نفس الجذع بامتداد مختلف (webp ⇒ png…)
            if stem:
                for ext in exts:
                    cand = folder / f"{stem}{ext}"
                    if cand.is_file():
                        return cand
        # محاولة 2 — مطابقة رقم الصنف: أي ملف يبدأ بـ`{code}_`
        # ولم يُستهلَك من صف آخر في الجدول.
        if not code:
            return None
        taken = set()
        result = getattr(self, "current_result", None)
        if result is not None:
            for other in result.items:
                if other is item or not other.output_path:
                    continue
                q = self._result_path(other.output_path)
                if q is not None and q.is_file():
                    taken.add(self._norm_path_key(q))
        for folder in dirs:
            try:
                pool = sorted(folder.glob(f"{code}_*"))
            except OSError:
                continue
            for cand in pool:
                if not cand.is_file() or cand.suffix.lower() not in exts:
                    continue
                if self._norm_path_key(cand) in taken:
                    continue
                return cand
        return None

    def _set_primary_image(self) -> None:
        """يجعل الصورة المحددة صورة الواجهة الرئيسية للصنف (بلا رقم)،
        ويعيد ترقيم بقية صور الصنف -2، -3… على القرص وفي الجدول.

        2.9.9 — أُغلقت مشكلة المالك «بعد ضغط ★ يتعذر على البرنامج
        العثور على الصورة ويخفيها» بثلاثة إصلاحات مجتمعة:
        استرجاع المسار الميت من مجلد الإخراج، وتطبيع مفاتيح
        `renames` قبل المطابقة، وترجمة `source_name` القديم إلى
        الجديد عند استعادة موقع الجدول.
        """
        selected = self._selected_result_item()
        if selected is None or not selected.item_code or self.current_result is None:
            QMessageBox.information(
                self, APP_NAME,
                "حدد صورة مرتبطة بصنف أولًا لتعيينها كصورة رئيسية.")
            return
        code = selected.item_code
        # صور الصنف نفسه بترتيب الجدول، والمحددة تتصدرها.
        group = [item for item in self.current_result.items
                 if item.item_code == code and item.output_path]
        if len(group) < 2:
            QMessageBox.information(
                self, APP_NAME,
                "هذه الصورة هي الوحيدة للصنف — هي الرئيسية بالفعل.")
            return
        group_sorted = sorted(
            group,
            key=lambda it: (it.source_name != selected.source_name,
                            self._row_for_source_name(it.source_name)),
        )
        # 2.9.9 — استرجاع ذكي بدل الإجهاض: كان غياب ملف واحد
        # يُوقف العملية كلها بـ«ملف الإخراج غير موجود»، وهي أكثر
        # شكوى المالك. المسار قد يقدم لأن ضغطة سابقة أعادت
        # التسمية، أو لأن الملف نُقل يدويًا. الآن يُبحث عنه في
        # مجلد الإخراج بمطابقة رقم الصنف، ولا يُجهَض إلا إن بقيت
        # أقل من صورتين قابلتين للترقيم.
        paths = []
        recovered: list[str] = []
        skipped: list[str] = []
        selected_path: Path | None = None
        for it in group_sorted:
            p = self._result_path(it.output_path)
            if p is None or not p.is_file():
                p = self._recover_output_path(it, code)
                if p is not None:
                    recovered.append(it.source_name)
            if p is None or not p.is_file():
                skipped.append(it.source_name)
                continue
            if it.source_name == selected.source_name:
                selected_path = p
            paths.append(p)
        if selected_path is None:
            QMessageBox.warning(
                self, APP_NAME,
                "تعذر العثور على ملف الإخراج للصورة المحددة:\n"
                f"{selected.source_name}\n\n"
                "أعد تشغيل الدفعة أو افتح المجلد من جديد ثم أعد المحاولة.")
            return
        if len(paths) < 2:
            QMessageBox.information(
                self, APP_NAME,
                "لم يُوجد سوى ملف إخراج واحد للصنف — هو الرئيسي بالفعل.")
            return
        try:
            from engine_v2 import integration_v2 as _iv
            from engine_v2.primary_image_v2 import renumber_item_images
            # 2.9.10: ترتيب الإكسل الحرفي. إعادة الترقيم بعد ★
            # يجب أن تنتج الأسماء نفسها التي تكتبها الدفعة؛
            # ترتيب مختلف يعني أن مجرد ضغط ★ يغير الأسماء.
            try:
                units = _iv._units_from_catalog(code, excel_order=True) or []
            except TypeError:
                units = _iv._units_from_catalog(code) or []
            settings = _iv._current_naming_settings()
        except Exception:
            units, settings = [], None
            from engine_v2.primary_image_v2 import renumber_item_images
        res = renumber_item_images(paths[0].parent, code, paths, units, settings)
        if not res.ok:
            QMessageBox.warning(self, APP_NAME, res.error)
            return
        # حدّث مسارات الإخراج في النتائج ثم أعد بناء الجدول مع ثبات الموضع.
        # BatchItemResult وBatchRunResult مجمّدان (frozen dataclass)
        # فالإسناد المباشر يرفع FrozenInstanceError ويترك القرص
        # مُعاد التسمية والجدول قديمًا — ولذلك يُستبدل العنصر
        # بنسخة معدّلة عبر dataclasses.replace داخل قائمة جديدة.
        # 2.9.9 — تطبيع المسارات قبل المطابقة. مقارنة `str(old)`
        # الخام تفشل بصمت على ويندوز متى اختلفت حالة الأحرف أو
        # الفواصل أو وجد رابط رمزي — فيُعاد التسمية على القرص
        # ويبقى `output_path` قديمًا ⇒ الصورة تختفي. هذا أحد وجوه
        # مشكلة «ملف الإخراج غير موجود» التي أبلغ عنها المالك.
        renames_norm = {self._norm_path_key(k): v
                        for k, v in res.renames.items()}
        updated: dict[int, BatchItemResult] = {}
        renamed_names: dict[str, str] = {}   # source_name القديم ⇒ الجديد
        for it in group:
            old = self._result_path(it.output_path)
            if old is None:
                continue
            target = renames_norm.get(self._norm_path_key(old))
            if target is None:
                continue
            new_path = Path(target)
            rel = str(new_path)
            if self.current_workspace is not None:
                try:
                    rel = str(new_path.relative_to(self.current_workspace))
                except ValueError:
                    rel = str(new_path)
            fields = {"output_path": rel}
            # في المجلدات المنجزة الملف نفسه هو المصدر، فيجب أن
            # يتبعه المسار والاسم حتى لا ينكسر الجدول والمعاينة.
            if it.match_source == "legacy_folder":
                fields["source_path"] = str(new_path)
                fields["source_name"] = new_path.name
                is_primary = str(new_path) == str(res.primary_path)
                star = "★ صورة الواجهة" if is_primary else "صورة إضافية"
                base = (it.explanation or "").split("\n", 1)
                tail = f"\n{base[1]}" if len(base) > 1 else ""
                unit_txt = ""
                if " — الوحدة: " in base[0]:
                    unit_txt = " — الوحدة: " + base[0].split(
                        " — الوحدة: ", 1)[1]
                fields["explanation"] = f"مجلد منجز — {star}{unit_txt}{tail}"
                renamed_names[it.source_name] = new_path.name
            updated[id(it)] = _dc.replace(it, **fields)
        # 2.9.9 — يُلتقط الموقع **قبل** إعادة بناء الجدول، ويُترجم
        # `source_name` القديم إلى الجديد. كان التقاطه بلا ترجمة يجعل
        # `_restore_results_position` يبحث عن اسم لم يعد موجودًا فيقع على
        # `fallback_row` أو يُلغي التحديد ⇒ تُفرّغ المعاينة وتختفي
        # الصورة من أمام المالك بعد ضغط ★ مباشرة.
        position = self._capture_results_position()
        if position is not None and position[0] in renamed_names:
            position = (renamed_names[position[0]], position[1], position[2])
        # البحث النشط قد يُخفي الصف بعد تغير الاسم (الاسم الجديد لا
        # يطابق نص البحث) ⇒ تختفي الصورة. نُنبّه ونُفرغ البحث
        # لأن أولوية المالك أن يرى الصورة لا أن يُحفظ المُرشّح.
        search_cleared = False
        if renamed_names and self.result_search_edit.text().strip():
            self.result_search_edit.blockSignals(True)
            self.result_search_edit.clear()
            self.result_search_edit.blockSignals(False)
            search_cleared = True
        if updated:
            new_items = [updated.get(id(it), it)
                         for it in self.current_result.items]
            self.current_result = _dc.replace(self.current_result,
                                              items=new_items)
        # 2.9.12 — إغلاق الانفصال بين الذاكرة والقرص.
        # أعلاه حُدّثت النتائج في ذاكرة الواجهة فقط، بينما المحرك
        # يقرأ `job_state.json` من القرص. بدون هذه المزامنة يفشل
        # أول تحرير بعد ★ بـ«لم يُعثر على الصورة المحددة داخل
        # نتائج المهمة» — وهو ما وصفه المالك بأن الطمس لا يُحفظ.
        if self.current_workspace is not None:
            try:
                from engine_v2.state_sync_v2 import sync_renamed_outputs
                sync_renamed_outputs(self.current_workspace,
                                     res.renames, renamed_names)
            except Exception as exc:                    # noqa: BLE001
                print(f"[state_sync] تعذرت مزامنة الحالة: {exc}",
                      file=sys.stderr)
        self._populate_results(restore_position=position)
        extra = len(paths) - 1
        note = []
        if recovered:
            note.append(f"استُرجع مسار {len(recovered)} صورة تلقائيًا")
        if skipped:
            note.append(f"تُجاوزت {len(skipped)} صورة مفقودة")
        if search_cleared:
            note.append("أُفرغ مرشّح البحث لتبقى الصورة مرئية")
        note_txt = (" — " + "، ".join(note)) if note else ""
        self.status_label.setText(
            f"تم تعيين الصورة الرئيسية للصنف {code} وإعادة ترقيم "
            f"{extra} صورة إضافية (-1، -2…){note_txt}.")
        detail = ""
        if recovered:
            detail += ("\n\nملاحظة: استُرجع مسار "
                       f"{len(recovered)} صورة تلقائيًا من مجلد الإخراج.")
        if skipped:
            detail += ("\n\nتُجاوزت صور لم يُعثر على ملفات إخراجها: "
                       + "، ".join(skipped[:5])
                       + (" …" if len(skipped) > 5 else ""))
        QMessageBox.information(
            self, APP_NAME,
            "تم التعيين بنجاح — الصورة المحددة أصبحت واجهة الصنف بلا رقم،\n"
            f"وأعيد ترقيم بقية صور الصنف تلقائيًا (-1، -2…).\n"
            f"الملف الرئيسي: {Path(res.primary_path).name}{detail}")

    def _begin_manual_links(
        self,
        targets: Iterable[BatchItemResult],
        lookup_value: str,
        status_text: str,
    ) -> None:
        if self.current_workspace is None:
            return
        targets = list(targets)
        source_names = tuple(dict.fromkeys(item.source_name for item in targets))
        if not source_names:
            return
        # 2.9.12 — جوهر إصلاح «اختفاء الأصناف عند الربط»:
        # الصف المربوط قد يكون له مخرَج قائم من معالجة سابقة.
        # نمرّر هذا المسار للعامل ليُكتب فوقه بدل توليد
        # اسم جديد (-2 ثم -3…) ثم حذف القديم فتضيع الصورة.
        previous_outputs = {}
        for item in targets:
            out = str(getattr(item, "output_path", "") or "")
            name = str(getattr(item, "source_name", "") or "")
            if out and name and Path(out).is_file():
                previous_outputs[name] = out
        # 2.9.6 — حارس التزامن: بدء ربط جديد بينما السابق يعمل كان يستبدل
        # المرجع ويُسقط QThread عاملًا ⇒ SIGABRT وإغلاق التطبيق بلا رسالة.
        # الآن يُرفض الطلب بلطف مع إبقاء الأزرار معطلة حتى ينتهي الجاري.
        if self.manual_worker is not None and self.manual_worker.isRunning():
            self.status_label.setText(
                "هناك ربط قيد الحفظ بالخلفية — انتظر ثانية واحدة ثم أعد المحاولة.")
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
            manual_rotation=self._current_manual_tilt(),
            previous_outputs=previous_outputs,
        )
        self.manual_worker.completed.connect(self._on_manual_completed)
        self.manual_worker.failed.connect(self._on_manual_failed)
        self._track_worker(self.manual_worker)
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
        # تصفير الميل اليدوي بعد تطبيقه — كي لا ينتقل سهوًا للصورة التالية
        spin = getattr(self, "manual_tilt_spin", None)
        if spin is not None and abs(spin.value()) > 0.049:
            spin.blockSignals(True)
            spin.setValue(0.0)
            spin.blockSignals(False)
            self._on_manual_tilt_changed(0.0)
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
        # 2.9.9 — أُلغي تسخين البصمات البصرية مع إلغاء نسبة التشابه:
        # كان يقرأ كل صور الدفعة من القرص لبناء بصمات لم يبق لها فائدة.

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
        # 2.9.12 — قد يكون تحديث مؤجّل معلّقًا (تأجيل الكتابة لمنع
        # البطء)؛ ننفّذه قبل النسخ حتى يأخذ المالك أحدث نسخة.
        scheduler = getattr(self, "_zip_scheduler", None)
        if scheduler is not None:
            try:
                scheduler.flush(timeout=60.0)
            except Exception as exc:                    # noqa: BLE001
                print(f"[delivery_zip] تعذر تفريغ الحزمة قبل الحفظ: {exc}",
                      file=sys.stderr)
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
        if self._editor_ready():
            self.unified_editor.setEnabled(not busy and can_edit_one)
        self.individual_preview_button.setEnabled(not busy and can_edit_one)
        self.individual_apply_button.setEnabled(not busy and can_edit_one)
        self.individual_cancel_button.setEnabled(not busy)
        self.individual_reset_button.setEnabled(not busy and can_edit_one)
        self.edit_image_button.setEnabled(not busy and can_edit_one)
        self.set_primary_button.setEnabled(
            not busy and selected is not None and bool(selected.item_code)
        )
        if hasattr(self, "link_same_item_button"):
            self.link_same_item_button.setEnabled(
                not busy and bool(self._selected_unresolved_link_targets())
            )
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
        if self._editor_ready():
            self.unified_editor.setEnabled(not busy and can_edit_one)
        self.individual_preview_button.setEnabled(not busy and can_edit_one)
        self.individual_apply_button.setEnabled(not busy and can_edit_one)
        self.individual_cancel_button.setEnabled(not busy)
        self.individual_reset_button.setEnabled(not busy and can_edit_one)
        self.edit_image_button.setEnabled(not busy and can_edit_one)
        self.set_primary_button.setEnabled(
            not busy and selected is not None and bool(selected.item_code)
        )
        if hasattr(self, "link_same_item_button"):
            self.link_same_item_button.setEnabled(
                not busy and bool(self._selected_unresolved_link_targets())
            )
        self.open_selected_file_button.setEnabled(not busy and selected is not None)
        self.open_link_panel_button.setEnabled(not busy and selected is not None)
        self.open_folder_button.setEnabled(not busy and self.current_workspace is not None)
        self.save_zip_button.setEnabled(not busy and self.current_result is not None)

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        interactive_close = bool(event.spontaneous())
        if (
            interactive_close
            and self._is_individual_editor_active()
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
        # 2.9.12 — تحديث الحزمة صار مؤجّلًا لمنع البطء؛ فإن أُغلق
        # البرنامج خلال فترة التأجيل وجب تنفيذ المعلّق أولًا
        # وإلا سُلّمت حزمة ناقصة — وهذا أسوأ من البطء نفسه.
        scheduler = getattr(self, "_zip_scheduler", None)
        if scheduler is not None:
            try:
                scheduler.flush(timeout=30.0)
            except Exception as exc:                    # noqa: BLE001
                print(f"[delivery_zip] تعذر تفريغ الحزمة: {exc}",
                      file=sys.stderr)
        # إيقاف منظم للخيوط قبل الإغلاق: تدمير QThread وهو يعمل يسبب
        # تحذير "Destroyed while thread is still running" وقد ينهي
        # العملية فجأة (خصوصًا إن أُغلق البرنامج أثناء معالجة دفعة).
        self._shutdown_workers()
        event.accept()

    def _track_worker(self, worker) -> None:  # type: ignore[no-untyped-def]
        """الاحتفاظ بمرجع قوي للخيط حتى ينتهي فعليا.

        بدونها، إسناد عامل جديد إلى نفس الحقل (مثل self.manual_worker)
        يُسقط آخر مرجع للعامل القديم؛ فإن كان لا يزال يعمل يدمّره
        جامع القمامة وهو يعمل، ويطلق Qt انهيارا فوريا على مستوى C++
        («QThread: Destroyed while thread is still running» => SIGABRT)
        فيُغلق التطبيق نفسه بلا أي رسالة ويفقد المستخدم عمله.
        """
        try:
            workers = self._live_workers
        except AttributeError:  # توافق مع نوافذ أُنشئت قبل الترقية
            workers = self._live_workers = set()
        workers.add(worker)

        def _release() -> None:
            workers.discard(worker)

        try:
            worker.finished.connect(_release)
        except Exception:
            # إن تعذر الربط نحتفظ بالمرجع: تسريب ضئيل أرحم من انهيار.
            pass

    def _shutdown_workers(self, wait_ms: int = 4000) -> None:
        """يطلب إيقاف كل الخيوط العاملة وينتظرها ثم يقاطعها إن تعنّتت."""
        # 2.9.6 — نشمل أيضًا كل الخيوط الحية المتتبّعة حتى لو لم تعد مسندة
        # إلى حقول النافذة؛ وإلا قد تُدمّر مع النافذة وهي تعمل ⇒ SIGABRT.
        targets = []
        for attr in ("batch_worker", "manual_worker", "individual_worker"):
            candidate = getattr(self, attr, None)
            if candidate is not None:
                targets.append(candidate)
        for extra in tuple(getattr(self, "_live_workers", ()) or ()):
            if extra not in targets:
                targets.append(extra)
        for worker in targets:
            if worker is None:
                continue
            try:
                if not worker.isRunning():
                    continue
                # علم الإيقاف التعاوني إن كان الخيط يدعمه
                for flag in ("stop", "request_stop", "cancel"):
                    fn = getattr(worker, flag, None)
                    if callable(fn):
                        try:
                            fn()
                        except Exception:
                            pass
                        break
                else:
                    for flag in ("_stop", "_cancelled", "stopped"):
                        if hasattr(worker, flag):
                            try:
                                setattr(worker, flag, True)
                            except Exception:
                                pass
                            break
                worker.requestInterruption()
                if not worker.wait(wait_ms):
                    worker.terminate()
                    worker.wait(1000)
            except Exception:
                pass
        # مؤقتات الواجهة: إيقافها يمنع نبضات بعد التدمير
        # 2.9.9 — حُذف `_visual_warm_timer` مع إلغاء نسبة التشابه.
        # 2.9.11 — `_fill_timer` يعبّئ الجدول تدريجيًا؛ لو بقي ينبض بعد
        # تدمير الجدول لرمى RuntimeError عند الإغلاق.
        for attr in ("_thumb_timer", "_preview_timer", "_tap_hint_timer", "_fill_timer"):
            timer = getattr(self, attr, None)
            if timer is not None:
                try:
                    timer.stop()
                except Exception:
                    pass


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
    app = QApplication.instance() or QApplication(sys.argv)
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
            and window.manual_group.height() >= window.manual_group.sizeHint().height()
            and window.manual_group.height() <= window.manual_group.sizeHint().height() + 12
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
        # 2.6: المحرر الموحد — التحقق من تحميل الصورة والأدوات واللوحة المتقدمة
        ue = window.unified_editor
        unified_loaded = bool(ue.has_image())
        # تعديل حقيقي: ميل 15 درجة من منزلق الدوران ثم إعادة التركيب الفوري
        ue.rotate_slider.setValue(150)
        ue._recompose()
        app.processEvents()
        unified_edits_detected = bool(ue.has_edits())
        # اللوحة المتقدمة تفتح داخل الصفحة نفسها (ليست نافذة منفصلة)
        ue.advanced_toggle_btn.setChecked(True)
        app.processEvents()
        advanced_panel_visible = bool(ue.advanced_panel.isVisible())
        editor_screenshot_path = output_path.with_name(f"{output_path.stem}_editor_crop.png")
        editor_screenshot_saved = window.edit_tab.grab().save(str(editor_screenshot_path), "PNG")
        editor_verified = bool(
            window.preview_tabs.currentWidget() is window.edit_tab
            and window._is_individual_editor_active()
            and ue.isVisible()
            and unified_loaded
            and unified_edits_detected
            and advanced_panel_visible
            and ue.auto_all_btn.isVisible()
            and ue.cutout_btn.isVisible()
            and ue.canvas.isVisible()
            and not window.individual_editor_panel.isVisible()
            and not window.individual_editor_preview.isVisible()
            and not window.individual_preview_button.isVisible()
            and window.individual_cancel_button.isVisible()
            and window.individual_apply_button.isVisible()
        )
        window._individual_editor_dirty = False
        window._individual_preview_active = False
        ue.clear()
        window._exit_individual_edit_mode()
        app.processEvents()
        editor_verified = editor_verified and bool(
            window.preview_tabs.currentWidget() is window.output_preview
            and not window._is_individual_editor_active()
        )

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
                    f"unified_editor_loaded={str(unified_loaded).lower()}",
                    f"unified_edits_detected={str(unified_edits_detected).lower()}",
                    f"unified_advanced_panel_visible={str(advanced_panel_visible).lower()}",
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

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("Ahmed Al-Faifi")
    icon_path = bundled_asset("app_icon.png")
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()

    # حصانة الخروج: ``closeEvent`` وحده لا يكفي. إن انتهى التطبيق بمسار
    # آخر (``app.quit()`` من قائمة النظام، إشارة SIGTERM، أو إغلاق آخر
    # نافذة بلا حدث إغلاق) تُدمَّر ``MainWindow`` وخيوطها لا تزال تعمل
    # ⇒ «QThread: Destroyed while thread is still running» ⇒ SIGABRT
    # فيختفي التطبيق بلا رسالة ويفقد المالك عمله. ربط ``aboutToQuit``
    # يضمن إيقافًا منظمًا في **كل** مسارات الخروج لا في الإغلاق اليدوي وحده.
    def _quit_guard() -> None:
        try:
            window._shutdown_workers()
        except Exception:
            pass

    try:
        app.aboutToQuit.connect(_quit_guard)
    except Exception:
        pass

    window.show()
    exit_code = int(app.exec())
    # حزام أمان ثانٍ: إن لم تُطلق ``aboutToQuit`` (مسارات خروج شاذّة)
    # نوقف الخيوط هنا قبل أن يجمع بايثون النافذة.
    _quit_guard()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
