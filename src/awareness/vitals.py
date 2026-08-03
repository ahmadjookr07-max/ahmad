# -*- coding: utf-8 -*-
"""vitals — مراقبة الحياة: البرنامج يفحص نفسه ويعرف أي قدراته معطّلة.

المبدأ
------
الفحص هنا **حقيقي لا شكلي**. الفرق جوهري: الجلسات السابقة أثبتت أن التحقق من
«وجود ملف النموذج» لا يكفي، لأن الملف قد يوجد بحجم صفر أو ناقص التنزيل فينهار
``onnxruntime`` عند التحميل. لذلك نفحص الحجم المعقول والترويسة، ونفحص استيراد
الحزمة فعليًا لا مجرد وجودها في ``sys.modules``.

المخرَج ``HealthReport`` يحتوي ``Finding`` لكل مشكلة: معرّف ثابت، شدة، القدرة
المتأثرة، وصف عربي دقيق، وهل هي قابلة للإصلاح تلقائيًا وبأي علاج. هذا ما يبني
عليه ``healer`` قراره، وما تعرضه واجهة الوعي للمستخدم.

سياسة السرعة: ``quick_scan()`` أقل من 40 مللي (يُنادى قبل ظهور النافذة)،
و``full_scan()`` يُنادى في خيط خلفي بعد ظهورها، مع كاش 60 ثانية.
"""
from __future__ import annotations

import contextlib
import importlib
import importlib.util
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import identity, journal
from .identity import Impact

__all__ = [
    "Severity",
    "Finding",
    "HealthReport",
    "quick_scan",
    "full_scan",
    "invalidate_cache",
    "probe_import",
    "find_tesseract",
    "MODEL_SPECS",
]


class Severity:
    FATAL = "fatal"   # الهدف متوقف الآن
    ERROR = "error"   # قدرة حرجة أو مهمة معطّلة
    WARN = "warn"     # تدهور في الجودة أو الأداء
    INFO = "info"     # ملاحظة

    ORDER = {FATAL: 0, ERROR: 1, WARN: 2, INFO: 3}
    LABELS_AR = {FATAL: "قاتل", ERROR: "خطأ", WARN: "تحذير", INFO: "معلومة"}


@dataclass
class Finding:
    """مشكلة واحدة مكتشفة، مع كل ما يحتاجه الشفاء لمعالجتها."""

    code: str                       # معرّف ثابت مثل "pkg_missing:cv2"
    severity: str
    title_ar: str
    detail_ar: str = ""
    capability: str = ""            # القدرة المتأثرة
    impact: str = Impact.DEGRADED
    auto_fixable: bool = False
    remedy_kind: str = ""           # اسم العلاج في healer
    remedy_params: dict = field(default_factory=dict)
    fallback_ar: str = ""
    data: dict = field(default_factory=dict)

    @property
    def severity_label_ar(self) -> str:
        return Severity.LABELS_AR.get(self.severity, self.severity)

    def as_dict(self) -> dict:
        return {
            "code": self.code, "severity": self.severity,
            "title_ar": self.title_ar, "detail_ar": self.detail_ar,
            "capability": self.capability, "impact": self.impact,
            "auto_fixable": self.auto_fixable, "remedy_kind": self.remedy_kind,
            "remedy_params": self.remedy_params, "fallback_ar": self.fallback_ar,
            "data": self.data,
        }


@dataclass
class HealthReport:
    findings: list[Finding] = field(default_factory=list)
    disabled_capabilities: dict[str, str] = field(default_factory=dict)
    elapsed_ms: float = 0.0
    scanned_at: float = field(default_factory=time.time)
    scope: str = "full"

    # ── استعلامات ──
    def by_severity(self, sev: str) -> list[Finding]:
        return [f for f in self.findings if f.severity == sev]

    @property
    def fatal(self) -> list[Finding]:
        return self.by_severity(Severity.FATAL)

    @property
    def errors(self) -> list[Finding]:
        return self.by_severity(Severity.ERROR)

    @property
    def fixable(self) -> list[Finding]:
        return [f for f in self.findings if f.auto_fixable]

    @property
    def healthy(self) -> bool:
        return not (self.fatal or self.errors)

    @property
    def score(self) -> int:
        """درجة صحة 0-100 — تُعرض للمستخدم كمؤشر واحد مفهوم."""
        penalty = 0
        for f in self.findings:
            penalty += {Severity.FATAL: 40, Severity.ERROR: 15,
                        Severity.WARN: 4, Severity.INFO: 0}.get(f.severity, 0)
        return max(0, 100 - penalty)

    def sorted_findings(self) -> list[Finding]:
        return sorted(self.findings,
                      key=lambda f: (Severity.ORDER.get(f.severity, 9),
                                     Impact.ORDER.get(f.impact, 9)))

    def summary_ar(self) -> str:
        if self.healthy and not self.findings:
            return "كل قدراتي تعمل بكفاءة تامة، ولا شيء يعطّل هدفي."
        parts = []
        if self.fatal:
            parts.append(f"{len(self.fatal)} عطل قاتل يوقف عملي")
        if self.errors:
            parts.append(f"{len(self.errors)} خطأ يعطّل قدرات مهمة")
        warns = self.by_severity(Severity.WARN)
        if warns:
            parts.append(f"{len(warns)} تحذير يخفض الجودة أو السرعة")
        head = "؛ ".join(parts) if parts else "لا مشاكل جوهرية"
        fixable = len(self.fixable)
        tail = f" وأستطيع إصلاح {fixable} منها بنفسي." if fixable else ""
        return f"درجة صحتي {self.score}/100: {head}.{tail}"

    def as_dict(self) -> dict:
        return {
            "score": self.score, "healthy": self.healthy,
            "elapsed_ms": round(self.elapsed_ms, 1), "scope": self.scope,
            "scanned_at": self.scanned_at,
            "summary_ar": self.summary_ar(),
            "disabled_capabilities": self.disabled_capabilities,
            "findings": [f.as_dict() for f in self.sorted_findings()],
        }


# ───────────────── مواصفات النماذج (فحص حقيقي لا شكلي) ─────────────────
# min_bytes مأخوذ من الأحجام الفعلية المعروفة: نموذج ناقص التنزيل يمر بفحص
# «الوجود» لكنه يُسقط onnxruntime عند التحميل — وهذا عطل واجهه المشروع فعلًا.

MODEL_SPECS: dict[str, dict] = {
    "u2net.onnx": {
        "min_bytes": 150 * 1024 * 1024,
        "purpose_ar": "عزل الخلفية بدقة عالية (النموذج الأساسي)",
        "capability": "cutout",
        "urls": (
            "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx",
            "https://huggingface.co/tomjackson2023/rembg/resolve/main/u2net.onnx",
        ),
    },
    "u2netp.onnx": {
        "min_bytes": 3 * 1024 * 1024,
        "purpose_ar": "عزل الخلفية الخفيف (بديل سريع عند شح الموارد)",
        "capability": "cutout",
        "urls": (
            "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx",
            "https://huggingface.co/tomjackson2023/rembg/resolve/main/u2netp.onnx",
        ),
    },
    "isnet-general-use.onnx": {
        "min_bytes": 150 * 1024 * 1024,
        "purpose_ar": "عزل الخلفية للحواف الشعرية والمنتجات الشفافة",
        "capability": "cutout",
        "urls": (
            "https://huggingface.co/tomjackson2023/rembg/resolve/main/isnet-general-use.onnx",
        ),
    },
}

#: مسارات Tesseract المعتادة على ويندوز — سبب شائع جدًا لتعطّل قراءة الجداول.
_TESS_WIN_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    r"C:\Tesseract-OCR\tesseract.exe",
)

_CACHE: dict[str, tuple[float, HealthReport]] = {}
_CACHE_TTL = 60.0


def invalidate_cache() -> None:
    """يُنادى بعد كل إصلاح ليُعاد الفحص بلا كاش."""
    _CACHE.clear()


# ───────────────────────── مجسّات أولية ─────────────────────────

def probe_import(module: str, *, deep: bool = False) -> tuple[bool, str]:
    """هل الوحدة قابلة للاستيراد فعلًا؟ يُرجع (نجاح، سبب الفشل).

    ``deep=False`` يستخدم ``find_spec`` وهو سريع جدًا (مناسب للفحص الخفيف).
    ``deep=True`` يستوردها فعلًا، فيكشف أعطالًا لا يكشفها ``find_spec`` مثل
    فشل تحميل DLL على ويندوز — وهو عطل حقيقي ومتكرر مع ``cv2`` و``onnxruntime``.
    """
    try:
        if not deep:
            spec = importlib.util.find_spec(module)
            return (spec is not None, "" if spec is not None else "غير موجودة")
        importlib.import_module(module)
        return True, ""
    except ImportError as exc:
        return False, str(exc)[:300]
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:280]}"


def find_tesseract() -> str:
    """يبحث عن محرك Tesseract في PATH ثم في مسارات ويندوز المعتادة ثم السجل."""
    p = shutil.which("tesseract")
    if p:
        return p
    for cand in _TESS_WIN_PATHS:
        with contextlib.suppress(Exception):
            if Path(cand).is_file():
                return cand
    # سجل ويندوز: بعض التثبيتات لا تضيف نفسها إلى PATH
    if os.name == "nt":
        with contextlib.suppress(Exception):
            import winreg  # type: ignore[import-not-found]
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                with contextlib.suppress(Exception):
                    with winreg.OpenKey(root, r"SOFTWARE\Tesseract-OCR") as k:
                        base = winreg.QueryValueEx(k, "Path")[0]
                        exe = Path(base) / "tesseract.exe"
                        if exe.is_file():
                            return str(exe)
    return ""


def _tessdata_langs(exe: str) -> set[str]:
    """اللغات المتاحة فعلًا — وجود المحرك لا يعني وجود العربية."""
    langs: set[str] = set()
    if not exe:
        return langs
    with contextlib.suppress(Exception):
        out = subprocess.run([exe, "--list-langs"], capture_output=True, text=True,
                            timeout=8)
        for line in (out.stdout or "").splitlines()[1:]:
            s = line.strip()
            if s:
                langs.add(s)
    if not langs:
        prefix = os.environ.get("TESSDATA_PREFIX", "")
        roots = [Path(prefix)] if prefix else []
        if exe:
            roots.append(Path(exe).parent / "tessdata")
        roots.append(Path("/usr/share/tesseract-ocr/5/tessdata"))
        roots.append(Path("/usr/share/tessdata"))
        for r in roots:
            with contextlib.suppress(Exception):
                if r.is_dir():
                    langs |= {f.stem for f in r.glob("*.traineddata")}
    return langs


def _models_dir() -> Path:
    with contextlib.suppress(Exception):
        from engine_v2 import paths_v2
        return Path(paths_v2.models_dir())
    return identity.repo_root() / "resources" / "models"


def _disk_free_mb(path: Path) -> float:
    with contextlib.suppress(Exception):
        return shutil.disk_usage(str(path)).free / (1024 * 1024)
    return -1.0


def _mem_available_mb() -> float:
    with contextlib.suppress(Exception):
        import psutil  # type: ignore[import-not-found]
        return psutil.virtual_memory().available / (1024 * 1024)
    with contextlib.suppress(Exception):
        if Path("/proc/meminfo").is_file():
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024
    if os.name == "nt":
        with contextlib.suppress(Exception):
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            st = MS()
            st.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return st.ullAvailPhys / (1024 * 1024)
    return -1.0


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".w{os.getpid()}.tmp"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:
        return False


# ───────────────────────── الفحوص ─────────────────────────

def _check_packages(findings: list[Finding], *, deep: bool) -> None:
    """فحص حزم كل قدرة، مع نسبة العطل إلى القدرة المتأثرة لا إلى الحزمة وحدها."""
    model = identity.self_model()
    seen: dict[str, tuple[bool, str]] = {}

    def probe(mod: str) -> tuple[bool, str]:
        if mod not in seen:
            seen[mod] = probe_import(mod, deep=deep)
        return seen[mod]

    for cap in model.capabilities:
        for pkg in cap.required_packages:
            ok, why = probe(pkg)
            if ok:
                continue
            sev = Severity.FATAL if cap.impact == Impact.CRITICAL else Severity.ERROR
            findings.append(Finding(
                code=f"pkg_missing:{pkg}",
                severity=sev,
                title_ar=f"الحزمة «{pkg}» غير متاحة",
                detail_ar=(f"القدرة «{cap.title_ar}» تعتمد عليها اعتمادًا صارمًا. "
                           f"سبب الفشل: {why or 'غير معروف'}."),
                capability=cap.key, impact=cap.impact,
                auto_fixable=True, remedy_kind="install_package",
                remedy_params={"module": pkg},
                fallback_ar=cap.fallback_ar,
                data={"module": pkg, "reason": why}))
        for pkg in cap.optional_packages:
            ok, why = probe(pkg)
            if ok:
                continue
            findings.append(Finding(
                code=f"pkg_optional_missing:{pkg}",
                severity=Severity.WARN,
                title_ar=f"الحزمة الاختيارية «{pkg}» غير متاحة",
                detail_ar=(f"القدرة «{cap.title_ar}» تعمل بدونها لكن بجودة أو "
                           f"سرعة أقل. {cap.fallback_ar}"),
                capability=cap.key, impact=Impact.OPTIONAL,
                auto_fixable=True, remedy_kind="install_package",
                remedy_params={"module": pkg, "optional": True},
                fallback_ar=cap.fallback_ar,
                data={"module": pkg, "reason": why}))


def _check_binaries(findings: list[Finding]) -> None:
    exe = find_tesseract()
    caps = identity.self_model().capabilities_needing_binary("tesseract")
    cap_keys = ",".join(c.key for c in caps)
    if not exe:
        findings.append(Finding(
            code="binary_missing:tesseract",
            severity=Severity.WARN,
            title_ar="محرك التعرف على النصوص Tesseract غير مثبَّت",
            detail_ar=("لم أجده في PATH ولا في مسارات ويندوز المعتادة ولا في سجل "
                       "النظام. القدرات المتأثرة: "
                       + "، ".join(c.title_ar for c in caps) + "."),
            capability=caps[0].key if caps else "nutrition_ocr",
            impact=Impact.DEGRADED,
            auto_fixable=True, remedy_kind="provision_tesseract",
            fallback_ar=(caps[0].fallback_ar if caps else ""),
            data={"capabilities": cap_keys}))
        return

    langs = _tessdata_langs(exe)
    if langs and "ara" not in langs:
        findings.append(Finding(
            code="tessdata_missing:ara",
            severity=Severity.WARN,
            title_ar="بيانات اللغة العربية مفقودة من Tesseract",
            detail_ar=(f"المحرك موجود في {exe} لكن حزمة اللغة «ara» غير مثبَّتة، "
                       "فلن تُقرأ الجداول العربية. اللغات المتاحة: "
                       + ", ".join(sorted(langs)[:8]) + "."),
            capability="nutrition_ocr", impact=Impact.DEGRADED,
            auto_fixable=True, remedy_kind="provision_tessdata",
            remedy_params={"lang": "ara", "exe": exe},
            data={"exe": exe, "langs": sorted(langs)}))


def _check_models(findings: list[Finding]) -> None:
    mdir = _models_dir()
    present = 0
    for name, spec in MODEL_SPECS.items():
        p = mdir / name
        try:
            exists = p.is_file()
            size = p.stat().st_size if exists else 0
        except Exception:
            exists, size = False, 0

        if exists and size >= spec["min_bytes"]:
            present += 1
            continue

        if exists and size < spec["min_bytes"]:
            findings.append(Finding(
                code=f"model_corrupt:{name}",
                severity=Severity.WARN,
                title_ar=f"نموذج «{name}» ناقص أو تالف",
                detail_ar=(f"حجمه {size / 1048576:.1f} ميغابايت وهو أقل من الحد "
                           f"المتوقع {spec['min_bytes'] / 1048576:.0f} ميغابايت. "
                           "تحميله سيفشل عند أول استخدام، فمن الأفضل إعادة تنزيله."),
                capability=spec["capability"], impact=Impact.DEGRADED,
                auto_fixable=True, remedy_kind="download_model",
                remedy_params={"name": name},
                data={"path": str(p), "size": size}))
        else:
            findings.append(Finding(
                code=f"model_missing:{name}",
                severity=Severity.WARN,
                title_ar=f"نموذج «{name}» غير موجود",
                detail_ar=f"الغرض منه: {spec['purpose_ar']}.",
                capability=spec["capability"], impact=Impact.DEGRADED,
                auto_fixable=True, remedy_kind="download_model",
                remedy_params={"name": name},
                data={"path": str(p)}))

    if present == 0:
        cap = identity.self_model().capability("cutout")
        findings.append(Finding(
            code="models_none",
            severity=Severity.ERROR,
            title_ar="لا يوجد أي نموذج عزل صالح",
            detail_ar=("سأعمل بالعزل الكلاسيكي بالعتبات اللونية: أسرع لكن أقل دقة "
                       "في الحواف الشعرية والمنتجات الشفافة. تنزيل النموذج الخفيف "
                       "u2netp (٤ ميغابايت) يكفي لتحسّن كبير."),
            capability="cutout", impact=Impact.DEGRADED,
            auto_fixable=True, remedy_kind="download_model",
            remedy_params={"name": "u2netp.onnx", "prefer_light": True},
            fallback_ar=(cap.fallback_ar if cap else ""),
            data={"models_dir": str(mdir)}))


def _check_assets(findings: list[Finding]) -> None:
    with contextlib.suppress(Exception):
        from engine_v2 import paths_v2
        adir = Path(paths_v2.assets_dir())
        fonts = list(adir.glob("*.ttf")) + list(adir.glob("*.otf"))
        if not fonts:
            sys_fonts = []
            for root in (Path("C:/Windows/Fonts"), Path("/usr/share/fonts")):
                with contextlib.suppress(Exception):
                    if root.is_dir():
                        sys_fonts = list(root.rglob("*.ttf"))[:1]
                if sys_fonts:
                    break
            findings.append(Finding(
                code="asset_missing:arabic_font",
                severity=Severity.WARN,
                title_ar="الخط العربي المحزَّم غير موجود",
                detail_ar=("إعادة رسم جدول الحقائق الغذائية تحتاج خطًا عربيًا. "
                           + ("وجدت خطوطًا في النظام يمكنني استخدامها بديلًا."
                              if sys_fonts else
                              "ولم أجد خطًا بديلًا في النظام، فسيُنقل الجدول كصورة.")),
                capability="nutrition_ocr", impact=Impact.DEGRADED,
                auto_fixable=bool(sys_fonts), remedy_kind="substitute_font",
                remedy_params={"assets_dir": str(adir)},
                data={"assets_dir": str(adir), "system_font": str(sys_fonts[0])
                      if sys_fonts else ""}))


def _check_storage(findings: list[Finding]) -> None:
    data = identity.app_data_dir()
    if not _writable(data):
        findings.append(Finding(
            code="dir_not_writable:data",
            severity=Severity.FATAL,
            title_ar="مجلد بياناتي غير قابل للكتابة",
            detail_ar=(f"لا أستطيع الكتابة في {data}. بدون ذلك لا أحفظ إعداداتك ولا "
                       "جلساتك ولا ذاكرتي. سأنتقل تلقائيًا إلى مجلد بديل."),
            capability="sessions", impact=Impact.CRITICAL,
            auto_fixable=True, remedy_kind="relocate_data_dir",
            remedy_params={"current": str(data)}, data={"path": str(data)}))
        return

    free = _disk_free_mb(data)
    if 0 <= free < 200:
        findings.append(Finding(
            code="disk_critical",
            severity=Severity.ERROR,
            title_ar="مساحة القرص على وشك النفاد",
            detail_ar=(f"المتاح {free:.0f} ميغابايت فقط. معالجة دفعة صور تحتاج "
                       "مساحة مؤقتة، وقد تفشل الكتابة في منتصف العمل. "
                       "سأنظّف الملفات المؤقتة والنسخ القديمة."),
            capability="image_io", impact=Impact.CRITICAL,
            auto_fixable=True, remedy_kind="free_disk_space",
            remedy_params={"need_mb": 500}, data={"free_mb": round(free, 1)}))
    elif 0 <= free < 1024:
        findings.append(Finding(
            code="disk_low",
            severity=Severity.WARN,
            title_ar="مساحة القرص منخفضة",
            detail_ar=f"المتاح {free:.0f} ميغابايت. يُستحسن التنظيف قبل دفعة كبيرة.",
            capability="image_io", impact=Impact.DEGRADED,
            auto_fixable=True, remedy_kind="free_disk_space",
            remedy_params={"need_mb": 1024}, data={"free_mb": round(free, 1)}))

    mem = _mem_available_mb()
    if 0 <= mem < 700:
        findings.append(Finding(
            code="memory_low",
            severity=Severity.WARN,
            title_ar="الذاكرة المتاحة شحيحة",
            detail_ar=(f"المتاح {mem:.0f} ميغابايت. نموذج العزل الكبير يحتاج نحو "
                       "٥٠٠ ميغابايت. سأخفض حجم الدفعة وعدد الخيوط تلقائيًا "
                       "وأفضّل النموذج الخفيف لأتجنب توقف النظام."),
            capability="cutout", impact=Impact.DEGRADED,
            auto_fixable=True, remedy_kind="reduce_footprint",
            remedy_params={"available_mb": round(mem)},
            data={"available_mb": round(mem, 1)}))


def _check_runtime(findings: list[Finding]) -> None:
    if sys.version_info < (3, 10):
        findings.append(Finding(
            code="python_too_old",
            severity=Severity.FATAL,
            title_ar="إصدار بايثون أقدم من المطلوب",
            detail_ar=(f"أعمل على {sys.version.split()[0]} وأحتاج 3.10 أو أحدث "
                       "لأن الشفرة تستخدم صيغة التعليقات الحديثة."),
            capability="ui", impact=Impact.CRITICAL, auto_fixable=False,
            data={"python": sys.version.split()[0]}))

    # tkinter: استوديو المالك فقط — تعطّله يجب أن يُدهور بلطف لا أن يُسقط شيئًا
    ok, why = probe_import("tkinter")
    if not ok:
        findings.append(Finding(
            code="pkg_missing:tkinter",
            severity=Severity.INFO,
            title_ar="مكتبة tkinter غير متاحة",
            detail_ar=("تُستخدم في استوديو المالك فقط لإصدار مفاتيح الاشتراك. "
                       "تطبيق المستخدم لا يتأثر بها إطلاقًا. "
                       f"({why or 'غير مثبّتة'})"),
            capability="owner_studio", impact=Impact.OPTIONAL,
            auto_fixable=True, remedy_kind="disable_capability",
            remedy_params={"capability": "owner_studio"},
            fallback_ar="أداة خاصة بالمالك؛ لا تمنع المستخدم من العمل."))


#: كاش سلامة الشفرة: (المسار -> (mtime, حجم)) — لا نُعيد تحليل ملف لم يتغير.
_SRC_CACHE: dict[str, tuple[float, int]] = {}


def _check_source_integrity(findings: list[Finding]) -> None:
    """تحليل نحوي لوحدات المشروع — يكشف ملفًا تالفًا قبل أن يُسقط التطبيق.

    التحليل الكامل مكلف (نحو ثانيتين لـ24 ألف سطر)، لذا نحتفظ ببصمة
    (زمن التعديل، الحجم) لكل ملف ونحلل المتغيّر فقط. أول تشغيل يدفع الثمن مرة
    واحدة في خيط خلفي، وما بعده يكاد يكون مجانيًا.
    """
    if identity.is_frozen():
        return
    root = identity.repo_root() / "src"
    if not root.is_dir():
        return
    import ast
    bad: list[str] = []
    for py in list(root.rglob("*.py"))[:600]:
        try:
            st = py.stat()
            sig = (st.st_mtime, st.st_size)
            key = str(py)
            if _SRC_CACHE.get(key) == sig:
                continue
            ast.parse(py.read_text(encoding="utf-8", errors="replace"),
                      filename=str(py))
            _SRC_CACHE[key] = sig
        except SyntaxError as exc:
            bad.append(f"{py.name}:{exc.lineno}")
        except Exception:
            continue
    if bad:
        findings.append(Finding(
            code="source_syntax_error",
            severity=Severity.FATAL,
            title_ar="خطأ نحوي في ملفات شفرتي",
            detail_ar=("لن أعمل بشكل صحيح حتى يُصلح. المواضع: "
                       + "، ".join(bad[:6])
                       + ("…" if len(bad) > 6 else "")
                       + ". إن كان سببه تعديلًا ذاتيًا سابقًا فسأتراجع عنه."),
            capability="ui", impact=Impact.CRITICAL,
            auto_fixable=True, remedy_kind="rollback_last_surgery",
            data={"files": bad[:20]}))


def _compute_disabled(findings: list[Finding]) -> dict[str, str]:
    """أي القدرات معطّلة الآن، وبأي سبب — تستخدمها الواجهة لتعطيل الأزرار بلطف."""
    disabled: dict[str, str] = {}
    for f in findings:
        if f.severity in (Severity.FATAL, Severity.ERROR) and f.capability:
            cap = identity.self_model().capability(f.capability)
            label = cap.title_ar if cap else f.capability
            disabled[f.capability] = f"{label}: {f.title_ar}"
    return disabled


# ───────────────────────── الواجهة العامة ─────────────────────────

def quick_scan() -> HealthReport:
    """فحص خفيف جدًا قبل ظهور الواجهة — الحرج فقط، بلا عمليات فرعية ولا قرص ثقيل."""
    t0 = time.perf_counter()
    findings: list[Finding] = []
    with contextlib.suppress(Exception):
        _check_runtime(findings)
    with contextlib.suppress(Exception):
        _check_packages(findings, deep=False)
    with contextlib.suppress(Exception):
        _check_storage(findings)

    rep = HealthReport(findings=findings, scope="quick",
                       disabled_capabilities=_compute_disabled(findings),
                       elapsed_ms=(time.perf_counter() - t0) * 1000)
    journal.debug("quick_scan", score=rep.score, findings=len(findings),
                  elapsed_ms=round(rep.elapsed_ms, 1))
    return rep


def full_scan(*, use_cache: bool = True, deep_imports: bool = True) -> HealthReport:
    """الفحص الشامل — يُنادى في خيط خلفي بعد ظهور الواجهة."""
    if use_cache:
        hit = _CACHE.get("full")
        if hit and (time.time() - hit[0]) < _CACHE_TTL:
            return hit[1]

    t0 = time.perf_counter()
    findings: list[Finding] = []
    for fn, name in ((_check_runtime, "runtime"),
                     (lambda f: _check_packages(f, deep=deep_imports), "packages"),
                     (_check_binaries, "binaries"),
                     (_check_models, "models"),
                     (_check_assets, "assets"),
                     (_check_storage, "storage"),
                     (_check_source_integrity, "source")):
        try:
            fn(findings)
        except Exception as exc:
            journal.warn("vitals_check_failed", check=name, detail=str(exc)[:200])

    rep = HealthReport(findings=findings, scope="full",
                       disabled_capabilities=_compute_disabled(findings),
                       elapsed_ms=(time.perf_counter() - t0) * 1000)
    _CACHE["full"] = (time.time(), rep)
    journal.info("full_scan", score=rep.score, findings=len(findings),
                 fatal=len(rep.fatal), errors=len(rep.errors),
                 fixable=len(rep.fixable), elapsed_ms=round(rep.elapsed_ms, 1))
    return rep
