# -*- coding: utf-8 -*-
"""runtime_deps_v2 — اكتفاء ذاتي: يجعل التطبيق يعمل في **أي بيئة**.

فلسفة الوحدة
------------
لا يجوز أن ينهار التطبيق لأن حزمة اختيارية غائبة أو نموذج ONNX مفقود.
كل تبعية خارجية تُفحص هنا **مرة واحدة** (نتيجة مُخزَّنة)، وتُعاد كحالة
منظَّمة يفهمها بقية الكود، مع رسالة عربية صريحة قابلة للتنفيذ بدل
استثناء خام يصل للمستخدم.

المكوّنات
---------
- ``have_onnx()`` / ``have_ocr()`` / ``have_pqc()`` / ``have_tk()``
  فحوص رخيصة مخزَّنة (لا تتكرر).
- ``writable_models_dir()`` مجلد نماذج قابل للكتابة داخل بيانات المستخدم.
- ``ensure_model()`` يبحث في كل المسارات، وإن غاب النموذج يُنزّله تلقائياً
  من مرايا موثوقة (إن توفر إنترنت) إلى المجلد القابل للكتابة.
- ``describe_missing()`` رسالة عربية واحدة تشرح الناقص وكيفية حله.
- ``environment_report()`` تقرير كامل لحالة البيئة (للتشخيص وواجهة المالك).

كل الدوال آمنة تماماً: لا ترمي استثناءات، بل تُرجع قيماً.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "have_onnx",
    "have_ocr",
    "have_pqc",
    "have_tk",
    "writable_models_dir",
    "find_model",
    "ensure_model",
    "model_status",
    "describe_missing",
    "environment_report",
    "reset_cache",
    "MODEL_FILENAMES",
]

# ترتيب الأفضلية: ISNet أدق، u2net متوسط، u2netp الأخف للبيئات المحدودة
MODEL_FILENAMES = ("isnet-general-use.onnx", "u2net.onnx", "u2netp.onnx")

# مرايا التنزيل التلقائي — إصدارات ثابتة معروفة الحجم (بايت)
_MODEL_SOURCES: dict[str, tuple[tuple[str, ...], int]] = {
    "u2netp.onnx": (
        (
            "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx",
            "https://huggingface.co/tomjackson2023/rembg/resolve/main/u2netp.onnx",
        ),
        4_574_861,
    ),
    "u2net.onnx": (
        (
            "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx",
            "https://huggingface.co/tomjackson2023/rembg/resolve/main/u2net.onnx",
        ),
        176_305_324,
    ),
    "isnet-general-use.onnx": (
        (
            "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx",
        ),
        178_648_008,
    ),
}

# أخف نموذج يُنزَّل تلقائياً عند غياب الجميع (4.5MB فقط — سريع ومقبول)
_AUTO_DOWNLOAD_DEFAULT = "u2netp.onnx"

_lock = threading.Lock()
_cache: dict[str, object] = {}


# ----------------------------------------------------------------- probes
def _probe(key: str, fn) -> bool:
    """يشغّل فحصاً مرة واحدة ويخزّن النتيجة (thread-safe)."""
    if key in _cache:
        return bool(_cache[key])
    with _lock:
        if key in _cache:
            return bool(_cache[key])
        try:
            value = bool(fn())
        except Exception:
            value = False
        _cache[key] = value
        return value


def _module_exists(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def have_onnx() -> bool:
    """هل محرك onnxruntime متاح فعلياً (وليس مجرد موجود في المسار)؟"""
    def _check() -> bool:
        if not _module_exists("onnxruntime"):
            return False
        try:
            import onnxruntime  # noqa: F401
            return True
        except Exception:
            return False
    return _probe("onnx", _check)


def have_ocr() -> bool:
    """هل pytesseract **ومحرك tesseract** متاحان معاً؟"""
    def _check() -> bool:
        if not _module_exists("pytesseract"):
            return False
        try:
            import pytesseract
        except Exception:
            return False
        try:
            from .nutrition_ocr_v2 import _configure_tesseract
            _configure_tesseract(pytesseract)
        except Exception:
            pass
        if shutil.which("tesseract"):
            return True
        cmd = getattr(getattr(pytesseract, "pytesseract", None),
                      "tesseract_cmd", "")
        try:
            return bool(cmd) and Path(str(cmd)).is_file()
        except Exception:
            return False
    return _probe("ocr", _check)


def have_pqc() -> bool:
    """هل توقيع ما بعد الكم (dilithium-py) متاح؟"""
    return _probe("pqc", lambda: _module_exists("dilithium_py"))


def have_tk() -> bool:
    """هل tkinter متاح (يخص استوديو المالك فقط)؟"""
    return _probe("tk", lambda: _module_exists("tkinter"))


def reset_cache() -> None:
    """يمسح نتائج الفحوص (بعد تثبيت تبعية أثناء التشغيل)."""
    with _lock:
        _cache.clear()


# ------------------------------------------------------------ model paths
def writable_models_dir() -> Path:
    """مجلد نماذج **قابل للكتابة** داخل بيانات المستخدم.

    يُستخدم للتنزيل التلقائي: مجلد التثبيت في ويندوز يقع تحت
    ``Program Files`` ولا يمكن الكتابة فيه بلا صلاحيات مدير.
    """
    override = os.environ.get("MIS_MODELS_CACHE", "").strip()
    if override:
        base = Path(override)
    else:
        root = os.environ.get("USERPROFILE") or os.environ.get("HOME") or ""
        home = Path(root) if root else Path.home()
        base = home / "Documents" / "SmartCatalogVision" / "models"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception:
        base = Path(os.environ.get("TEMP", "/tmp")) / "SmartCatalogVisionModels"
        try:
            base.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
    return base


def _search_dirs(extra: "str | Path | None" = None) -> list[Path]:
    """كل مجلدات البحث المحتملة عن النماذج، بلا تكرار."""
    dirs: list[Path] = []
    if extra:
        dirs.append(Path(extra))
        dirs.append(Path(extra) / "models")
    try:
        from .paths_v2 import models_dir
        d = Path(models_dir())
        dirs += [d, d / "models"]
    except Exception:
        pass
    dirs.append(writable_models_dir())
    out: list[Path] = []
    seen: set[str] = set()
    for d in dirs:
        key = str(d)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def find_model(extra_dir: "str | Path | None" = None) -> "Path | None":
    """أول نموذج قص موجود فعلياً حسب ترتيب الأفضلية."""
    for fname in MODEL_FILENAMES:
        for d in _search_dirs(extra_dir):
            try:
                candidate = d / fname
                if candidate.is_file() and candidate.stat().st_size > 1024:
                    return candidate
            except Exception:
                continue
    return None


def _download(url: str, dest: Path, expected: int, progress=None) -> bool:
    """تنزيل إلى ملف مؤقت ثم نقل ذرّي. يُرجع True عند النجاح."""
    import urllib.request

    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "MarketImageStudio/2.9.6"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length") or expected or 0)
            done = 0
            with open(tmp, "wb") as fh:
                while True:
                    chunk = resp.read(262144)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    if progress is not None and total > 0:
                        try:
                            progress(done, total)
                        except Exception:
                            pass
        size = tmp.stat().st_size
        # تحقق حجم متساهل (±5%) — يحمي من ملف HTML خطأ بدل النموذج
        if expected and abs(size - expected) > max(65536, expected * 0.05):
            tmp.unlink(missing_ok=True)
            return False
        if size < 1_000_000:
            tmp.unlink(missing_ok=True)
            return False
        tmp.replace(dest)
        return True
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return False


def ensure_model(extra_dir: "str | Path | None" = None,
                 allow_download: bool = True,
                 progress=None) -> "Path | None":
    """يضمن توفر نموذج قص.

    1) يبحث في كل المسارات المعروفة.
    2) إن غاب وسُمح بالتنزيل ووُجد إنترنت: ينزّل الأخف تلقائياً إلى
       مجلد بيانات المستخدم القابل للكتابة.
    3) يُرجع المسار أو ``None`` بلا أي استثناء.
    """
    found = find_model(extra_dir)
    if found is not None:
        return found
    if not allow_download:
        return None
    if os.environ.get("MIS_NO_DOWNLOAD", "").strip() in {"1", "true", "yes"}:
        return None

    fname = _AUTO_DOWNLOAD_DEFAULT
    urls, expected = _MODEL_SOURCES.get(fname, ((), 0))
    dest = writable_models_dir() / fname
    with _lock:
        # قد يكون خيط آخر أنهى التنزيل أثناء الانتظار
        if dest.is_file() and dest.stat().st_size > 1_000_000:
            return dest
        for url in urls:
            if _download(url, dest, expected, progress):
                return dest
    return None


def model_status(extra_dir: "str | Path | None" = None) -> dict:
    """حالة نموذج القص دون محاولة تنزيل (فحص سريع للواجهة)."""
    path = find_model(extra_dir)
    return {
        "available": path is not None,
        "path": str(path) if path else "",
        "name": path.stem if path else "",
        "cache_dir": str(writable_models_dir()),
    }


# --------------------------------------------------------------- messages
@dataclass
class EnvironmentReport:
    """تقرير حالة البيئة — كل حقل مستقل وقابل للعرض."""
    onnx: bool = False
    ocr: bool = False
    pqc: bool = False
    tk: bool = False
    model_path: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def smart_cutout_ready(self) -> bool:
        return self.onnx and bool(self.model_path)

    def summary_ar(self) -> str:
        def mark(ok: bool) -> str:
            return "متاح" if ok else "غير متاح"
        lines = [
            "حالة بيئة التشغيل:",
            f"• عزل الخلفية الذكي: {mark(self.smart_cutout_ready)}"
            + (f" ({Path(self.model_path).stem})" if self.model_path else ""),
            f"• محرك onnxruntime: {mark(self.onnx)}",
            f"• قراءة النصوص OCR: {mark(self.ocr)}",
            f"• التوقيع المقاوم للكم: {mark(self.pqc)}",
        ]
        lines += [f"• {n}" for n in self.notes]
        return "\n".join(lines)


def environment_report(extra_dir: "str | Path | None" = None,
                       allow_download: bool = False) -> EnvironmentReport:
    """تقرير شامل عن جاهزية البيئة. لا يُنزّل شيئاً افتراضياً."""
    rep = EnvironmentReport(
        onnx=have_onnx(),
        ocr=have_ocr(),
        pqc=have_pqc(),
        tk=have_tk(),
    )
    path = ensure_model(extra_dir, allow_download=allow_download)
    rep.model_path = str(path) if path else ""
    if not rep.onnx:
        rep.notes.append(
            "العزل الذكي معطّل: حزمة onnxruntime غير مثبّتة — "
            "المعالجة تستمر بالطريقة التقليدية.")
    elif not rep.model_path:
        rep.notes.append(
            "العزل الذكي معطّل: ملف النموذج مفقود — سيُنزَّل تلقائياً عند "
            "أول استخدام إذا توفّر الإنترنت.")
    if not rep.ocr:
        rep.notes.append(
            "قراءة جدول القيم الغذائية والتواريخ معطّلة: محرك Tesseract "
            "غير مثبّت — بقية الميزات تعمل طبيعياً.")
    return rep


def describe_missing(feature: str) -> str:
    """رسالة عربية واحدة صريحة تشرح سبب تعطّل ميزة وكيفية حلها."""
    if feature == "cutout":
        if not have_onnx():
            return (
                "تعذّر تشغيل عزل الخلفية الذكي لأن محرك الذكاء المحلي "
                "(onnxruntime) غير متاح في هذا الجهاز. تابع بالمعالجة "
                "التقليدية، أو أعد تثبيت التطبيق من المُثبِّت الرسمي "
                "لاستعادة الملفات الناقصة.")
        return (
            "ملف نموذج العزل غير موجود على هذا الجهاز. سيحاول التطبيق "
            "تنزيله تلقائياً عند توفر الإنترنت، ويمكنك متابعة العمل الآن "
            "بالمعالجة التقليدية دون انتظار.")
    if feature == "ocr":
        return (
            "قراءة النصوص من الصور غير متاحة لأن محرك Tesseract غير مثبّت "
            "على هذا الجهاز. أدخل قيم جدول القيم الغذائية يدوياً، أو ثبّت "
            "المحرك لتفعيل القراءة التلقائية.")
    if feature == "pqc":
        return (
            "التوقيع المقاوم للحوسبة الكمية غير متاح في هذه البيئة. "
            "التحقق من الترخيص يستمر بالتوقيع الأساسي.")
    if feature == "tk":
        return (
            "واجهة استوديو المالك تحتاج مكتبة الرسوم tkinter وهي غير مثبّتة "
            "في هذه البيئة. على لينكس: sudo apt install python3-tk")
    return "الميزة المطلوبة غير متاحة في هذه البيئة."
