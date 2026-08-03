# -*- coding: utf-8 -*-
"""journal — السجل الموحد وعيون البرنامج على نفسه.

المشكلة التي تحلها
------------------
الشفرة الحالية تحوي 305 موضع ``except Exception`` وصفر استخدام لـ``logging``.
النتيجة: الأعطال **تمرّ صامتة**. لا يعرف البرنامج أنه تعطّل، ولا يعرف المالك
لماذا تباطأ، ولا يمكن لأي طبقة تعلّم أن تتعلم من شيء لم يُسجَّل.

ما تقدّمه
---------
- سجل JSONL دوّار في ``<AppData>/awareness/journal.jsonl`` — قابل للتحليل آليًا.
- خطافات عامة (``sys.excepthook`` و``threading.excepthook`` و``unraisablehook``
  ومعالج رسائل Qt) فلا يضيع انهيار.
- ``capture()`` مدير سياق يمسك الاستثناء ويسجّله ويسلّمه لطبقة الشفاء.
- ``instrument()`` مزخرف يقيس زمن الدوال الحسّاسة ويرصد التباطؤ.
- ``fingerprint()`` بصمة عطل مستقرة: نفس العطل يعطي نفس البصمة على كل الأجهزة
  وفي كل الإصدارات، فتصلح مفتاحًا للذاكرة الدائمة.
- تنقية الخصوصية: أسماء المستخدم والمسارات وأسماء ملفات المنتجات تُقنَّع قبل
  أي كتابة، لأن السجل قد يُصدَّر أو يُشارك.

كل الدوال آمنة: لا ترمي استثناءً أبدًا. سجلٌّ ينهار أسوأ من سجلٍّ غائب.
"""
from __future__ import annotations

import contextlib
import functools
import hashlib
import json
import os
import re
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

from . import identity

__all__ = [
    "DEBUG",
    "INFO",
    "WARN",
    "ERROR",
    "FATAL",
    "log",
    "debug",
    "info",
    "warn",
    "error",
    "fatal",
    "capture",
    "instrument",
    "fingerprint",
    "exception_facts",
    "install_global_hooks",
    "recent",
    "stats",
    "journal_path",
    "set_sink",
    "sanitize",
    "PerfSample",
    "perf_samples",
]

DEBUG, INFO, WARN, ERROR, FATAL = "debug", "info", "warn", "error", "fatal"

_LEVELS = {DEBUG: 10, INFO: 20, WARN: 30, ERROR: 40, FATAL: 50}
_MIN_LEVEL = _LEVELS.get(os.environ.get("MIS_LOG_LEVEL", INFO).lower(), 20)

_MAX_BYTES = 5 * 1024 * 1024
_KEEP_FILES = 3

_LOCK = threading.RLock()
_RING: list[dict] = []          # آخر الأحداث في الذاكرة (للواجهة، بلا قراءة قرص)
_RING_MAX = 400
_HOOKS_INSTALLED = False
_SINKS: list = []               # مستقبلات إضافية (طبقة الشفاء، الواجهة)
_START = time.time()


# ───────────────────────── الخصوصية ─────────────────────────

_USER = os.environ.get("USERNAME") or os.environ.get("USER") or ""

_SENSITIVE_KEYS = ("password", "secret", "token", "key", "license", "serial")


def sanitize(text: str) -> str:
    """يُقنّع ما يمكن أن يعرّف المستخدم أو يفضح مسارات جهازه.

    نُبقي اسم الملف الأخير مفيدًا للتشخيص لكن نحذف الشجرة الكاملة، ونستبدل
    اسم المستخدم بـ``<user>``. هذا يجعل السجل قابلًا للمشاركة بأمان.
    """
    s = str(text or "")
    try:
        if _USER and len(_USER) > 2:
            s = re.sub(re.escape(_USER), "<user>", s, flags=re.IGNORECASE)
        # مسارات ويندوز الكاملة -> <path>\اسم_الملف
        s = re.sub(r"[A-Za-z]:\\(?:[^\\\n\"']+\\)+", r"<path>\\", s)
        # مسارات بوسكس -> <path>/اسم_الملف
        s = re.sub(r"/(?:home|Users|root)/[^/\n\"']+/(?:[^/\n\"']+/)*", "<path>/", s)
    except Exception:
        return s
    return s


def _clean_fields(fields: dict) -> dict:
    out = {}
    for k, v in (fields or {}).items():
        try:
            lk = str(k).lower()
            if any(t in lk for t in _SENSITIVE_KEYS):
                out[k] = "<محجوب>"
                continue
            if isinstance(v, (str, Path)):
                out[k] = sanitize(str(v))
            elif isinstance(v, (int, float, bool)) or v is None:
                out[k] = v
            elif isinstance(v, (list, tuple)):
                out[k] = [sanitize(str(x)) if isinstance(x, (str, Path)) else x
                          for x in list(v)[:40]]
            elif isinstance(v, dict):
                out[k] = _clean_fields(v)
            else:
                out[k] = sanitize(repr(v)[:400])
        except Exception:
            continue
    return out


# ───────────────────────── الكتابة ─────────────────────────

def journal_path() -> Path:
    return identity.awareness_dir() / "journal.jsonl"


def _rotate(p: Path) -> None:
    try:
        if not p.exists() or p.stat().st_size < _MAX_BYTES:
            return
        for i in range(_KEEP_FILES - 1, 0, -1):
            src = p.with_suffix(p.suffix + f".{i}")
            dst = p.with_suffix(p.suffix + f".{i + 1}")
            if src.exists():
                with contextlib.suppress(Exception):
                    if dst.exists():
                        dst.unlink()
                    src.rename(dst)
        with contextlib.suppress(Exception):
            p.rename(p.with_suffix(p.suffix + ".1"))
    except Exception:
        pass


def set_sink(fn) -> None:
    """تسجيل مستقبل إضافي للأحداث (مثل طبقة الشفاء أو شريط حالة الواجهة)."""
    with _LOCK:
        if fn not in _SINKS:
            _SINKS.append(fn)


def log(level: str, event: str, **fields) -> dict:
    """يكتب حدثًا واحدًا. يُرجع الحدث كما كُتب (مفيد للاختبارات)."""
    rec = {
        "ts": round(time.time(), 3),
        "uptime": round(time.time() - _START, 3),
        "level": level,
        "event": str(event),
        "thread": threading.current_thread().name,
    }
    try:
        rec.update(_clean_fields(fields))
    except Exception:
        pass

    try:
        with _LOCK:
            _RING.append(rec)
            if len(_RING) > _RING_MAX:
                del _RING[: len(_RING) - _RING_MAX]
            sinks = list(_SINKS)

        if _LEVELS.get(level, 20) >= _MIN_LEVEL:
            p = journal_path()
            _rotate(p)
            line = json.dumps(rec, ensure_ascii=False)
            with open(p, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")

        for fn in sinks:
            with contextlib.suppress(Exception):
                fn(rec)
    except Exception:
        pass
    return rec


def debug(event: str, **f) -> dict:  # noqa: D401
    return log(DEBUG, event, **f)


def info(event: str, **f) -> dict:
    return log(INFO, event, **f)


def warn(event: str, **f) -> dict:
    return log(WARN, event, **f)


def error(event: str, **f) -> dict:
    return log(ERROR, event, **f)


def fatal(event: str, **f) -> dict:
    return log(FATAL, event, **f)


# ───────────────────────── بصمة العطل ─────────────────────────

_NUM_RE = re.compile(r"\d+")
_QUOTED_RE = re.compile(r"['\"][^'\"]{0,200}['\"]")
_HEX_RE = re.compile(r"0x[0-9a-fA-F]+")
_PROJECT_MARKERS = ("engine_v2", "windows_app", "awareness", "owner_studio",
                    "smart_catalog_vision")


def _normalize_message(msg: str) -> str:
    """يجعل الرسائل المتشابهة متطابقة: تُزال الأرقام والمسارات والمقتبسات."""
    s = str(msg or "")
    s = _QUOTED_RE.sub("'…'", s)
    s = _HEX_RE.sub("0x…", s)
    s = _NUM_RE.sub("#", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s[:300]


def _own_frame(tb) -> tuple[str, str, int]:
    """آخر إطار ينتمي لشفرتنا — أدق من آخر إطار مطلقًا (قد يكون داخل مكتبة)."""
    best = ("", "", 0)
    try:
        for fr in traceback.extract_tb(tb):
            fn = str(fr.filename).replace("\\", "/")
            if any(m in fn for m in _PROJECT_MARKERS):
                best = (Path(fn).name, fr.name or "", int(fr.lineno or 0))
    except Exception:
        pass
    if not best[0]:
        try:
            frames = traceback.extract_tb(tb)
            if frames:
                fr = frames[-1]
                best = (Path(str(fr.filename)).name, fr.name or "", int(fr.lineno or 0))
        except Exception:
            pass
    return best


#: أنواع أعطال يكون الاسم المقتبس فيها جوهر العطل لا تفصيلًا عارضًا.
#: التطبيع يحوّل «No module named 'zxingcpp'» و«No module named 'numpy'» إلى نفس النص،
#: فتتطابق بصمتاهما ويطبّق البرنامج علاج الأول على الثاني — وهذا أسوأ من
#: الجهل: يقول «أصلحتُ» وهو لم يفعل. لذا نحفظ الاسم الجوهري في البصمة.
_IDENTITY_BEARING = frozenset({
    "ModuleNotFoundError", "ImportError", "FileNotFoundError",
    "KeyError", "AttributeError", "NameError", "TesseractNotFoundError",
})


def _salient_token(exc: BaseException) -> str:
    """الاسم الجوهري للعطل (الوحدة، الملف، المفتاح) — يُميّز البصمة دون أن
    يربطها بمسار جهاز معيّن (نأخذ اسم الملف لا شجرته) لتبقى الخبرة قابلة
    للمشاركة بين الأجهزة.
    """
    et = type(exc).__name__
    if et not in _IDENTITY_BEARING:
        return ""
    try:
        if et in ("ModuleNotFoundError", "ImportError"):
            name = getattr(exc, "name", None)
            if name:
                return f"mod:{str(name).split('.')[0]}"
            m = re.search(r"['\"]([\w\.]+)['\"]", str(exc))
            return f"mod:{m.group(1).split('.')[0]}" if m else ""
        if et == "FileNotFoundError":
            fn = getattr(exc, "filename", None) or ""
            if not fn:
                m = re.search(r"['\"]([^'\"]{3,300})['\"]", str(exc))
                fn = m.group(1) if m else ""
            return f"file:{Path(str(fn)).name.lower()}" if fn else ""
        m = re.search(r"['\"]([\w\.\- ]{1,80})['\"]", str(exc))
        return f"key:{m.group(1)}" if m else ""
    except Exception:
        return ""


def fingerprint(exc: BaseException | None = None, *, extra: str = "") -> str:
    """بصمة مستقرة لعطل: 16 حرفًا سِتّة عشرية.

    تُبنى من نوع الاستثناء + الملف والدالة داخل شفرتنا + رسالة مُطبّعة
    + الاسم الجوهري إن وجد. لا تدخل فيها أرقام الأسطر لأنها تتغير مع كل
    تعديل فتُفقد الذاكرة، ولا المسارات الكاملة لأنها تختلف بين الأجهزة.
    """
    try:
        if exc is None:
            exc = sys.exc_info()[1]
        etype = type(exc).__name__ if exc is not None else "None"
        tb = getattr(exc, "__traceback__", None)
        fname, func, _ = _own_frame(tb) if tb is not None else ("", "", 0)
        msg = _normalize_message(str(exc) if exc is not None else "")
        token = _salient_token(exc) if exc is not None else ""
        raw = "|".join((etype, fname, func, msg, token, str(extra or "")))
        return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:16]
    except Exception:
        return "0" * 16


def exception_facts(exc: BaseException) -> dict:
    """حقائق منظَّمة عن استثناء — مدخل موحّد للشفاء والذاكرة."""
    tb = getattr(exc, "__traceback__", None)
    fname, func, lineno = _own_frame(tb) if tb is not None else ("", "", 0)
    try:
        tb_text = "".join(traceback.format_exception(type(exc), exc, tb))
    except Exception:
        tb_text = ""
    return {
        "fingerprint": fingerprint(exc),
        "type": type(exc).__name__,
        "message": str(exc)[:600],
        "message_norm": _normalize_message(str(exc)),
        "file": fname,
        "func": func,
        "line": lineno,
        "traceback": sanitize(tb_text)[-4000:],
        "module_path": getattr(getattr(exc, "__traceback__", None), "tb_frame", None)
        and sanitize(str(getattr(exc.__traceback__.tb_frame.f_code, "co_filename", ""))),
    }


# ───────────────────────── الالتقاط ─────────────────────────

_EXC_LISTENERS: list = []


def add_exception_listener(fn) -> None:
    """تسجيل مستقبل للاستثناءات (طبقة الشفاء تسجّل نفسها هنا)."""
    with _LOCK:
        if fn not in _EXC_LISTENERS:
            _EXC_LISTENERS.append(fn)


def _notify_exception(exc: BaseException, context: dict) -> None:
    for fn in list(_EXC_LISTENERS):
        with contextlib.suppress(Exception):
            fn(exc, context)


@contextlib.contextmanager
def capture(event: str, *, swallow: bool = False, **fields):
    """مدير سياق يسجّل أي استثناء ويبلّغ طبقة الشفاء.

    ``swallow=True`` يكتم الاستثناء (للعمليات غير الحرجة)، والافتراضي إعادة رفعه
    بعد التسجيل حتى لا نغيّر سلوك الشفرة القائمة.
    """
    t0 = time.perf_counter()
    try:
        yield
    except Exception as exc:  # noqa: BLE001 — هذا موضعه الصحيح
        facts = exception_facts(exc)
        facts.update(_clean_fields(fields))
        facts["event_context"] = event
        facts["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        log(ERROR, "exception", **facts)
        _notify_exception(exc, facts)
        if not swallow:
            raise
    else:
        dt = (time.perf_counter() - t0) * 1000
        if dt > 1500:
            log(WARN, "slow_block", event_context=event, elapsed_ms=round(dt, 1))


# ───────────────────────── القياس ─────────────────────────

@dataclass
class PerfSample:
    name: str
    calls: int = 0
    total_ms: float = 0.0
    worst_ms: float = 0.0

    @property
    def avg_ms(self) -> float:
        return (self.total_ms / self.calls) if self.calls else 0.0


_PERF: dict[str, PerfSample] = {}


def instrument(name: str = "", *, warn_ms: float = 1200.0):
    """مزخرف يقيس زمن التنفيذ ويحذّر عند التباطؤ.

    السرعة أولوية في هذا المشروع، فالقياس ليس ترفًا: التباطؤ الذي رصدته الجلسة
    السابقة (5.2 ثانية تجمّد واجهة) كان سيُكتشف فورًا لو كان القياس موجودًا.
    """
    def deco(fn):
        label = name or getattr(fn, "__qualname__", getattr(fn, "__name__", "fn"))

        @functools.wraps(fn)
        def wrapper(*a, **kw):
            t0 = time.perf_counter()
            try:
                return fn(*a, **kw)
            finally:
                dt = (time.perf_counter() - t0) * 1000
                try:
                    with _LOCK:
                        s = _PERF.get(label)
                        if s is None:
                            s = _PERF[label] = PerfSample(label)
                        s.calls += 1
                        s.total_ms += dt
                        if dt > s.worst_ms:
                            s.worst_ms = dt
                    if dt >= warn_ms:
                        log(WARN, "slow_call", name=label, elapsed_ms=round(dt, 1))
                except Exception:
                    pass
        return wrapper
    return deco


def perf_samples() -> list[dict]:
    with _LOCK:
        items = list(_PERF.values())
    items.sort(key=lambda s: s.total_ms, reverse=True)
    return [
        {"name": s.name, "calls": s.calls, "total_ms": round(s.total_ms, 1),
         "avg_ms": round(s.avg_ms, 2), "worst_ms": round(s.worst_ms, 1)}
        for s in items
    ]


# ───────────────────────── الخطافات العامة ─────────────────────────

def install_global_hooks() -> bool:
    """يثبّت خطافات الالتقاط العامة. آمن للنداء المتكرر."""
    global _HOOKS_INSTALLED
    if _HOOKS_INSTALLED:
        return True

    prev_excepthook = sys.excepthook

    def _hook(etype, value, tb):
        try:
            if value is not None:
                if tb is not None and getattr(value, "__traceback__", None) is None:
                    with contextlib.suppress(Exception):
                        value = value.with_traceback(tb)
                facts = exception_facts(value)
                facts["event_context"] = "uncaught"
                log(FATAL, "uncaught_exception", **facts)
                _notify_exception(value, facts)
        except Exception:
            pass
        with contextlib.suppress(Exception):
            prev_excepthook(etype, value, tb)

    with contextlib.suppress(Exception):
        sys.excepthook = _hook

    def _thread_hook(args):
        try:
            exc = getattr(args, "exc_value", None)
            if exc is not None:
                facts = exception_facts(exc)
                facts["event_context"] = "thread"
                facts["thread_name"] = getattr(getattr(args, "thread", None), "name", "?")
                log(ERROR, "thread_exception", **facts)
                _notify_exception(exc, facts)
        except Exception:
            pass

    with contextlib.suppress(Exception):
        threading.excepthook = _thread_hook

    def _unraisable(args):
        with contextlib.suppress(Exception):
            log(WARN, "unraisable",
                type=type(getattr(args, "exc_value", None)).__name__,
                detail=sanitize(str(getattr(args, "exc_value", ""))))

    with contextlib.suppress(Exception):
        sys.unraisablehook = _unraisable

    _install_qt_handler()

    _HOOKS_INSTALLED = True
    info("journal_ready", journal=str(journal_path()), **identity.runtime_facts())
    return True


def _install_qt_handler() -> None:
    """يوجّه تحذيرات Qt إلى سجلنا — كثير من عيوب الواجهة تظهر هنا فقط."""
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except Exception:
        return

    level_map = {
        getattr(QtMsgType, "QtDebugMsg", None): DEBUG,
        getattr(QtMsgType, "QtInfoMsg", None): DEBUG,
        getattr(QtMsgType, "QtWarningMsg", None): WARN,
        getattr(QtMsgType, "QtCriticalMsg", None): ERROR,
        getattr(QtMsgType, "QtFatalMsg", None): FATAL,
    }

    def handler(mode, context, message):
        with contextlib.suppress(Exception):
            msg = str(message or "")
            # ضجيج معروف لا قيمة له
            if "QPixmap::scaled" in msg or "propagateSizeHints" in msg:
                return
            log(level_map.get(mode, WARN), "qt_message", detail=sanitize(msg)[:500])

    with contextlib.suppress(Exception):
        qInstallMessageHandler(handler)


# ───────────────────────── الاستعلام ─────────────────────────

def recent(limit: int = 60, level: str | None = None) -> list[dict]:
    with _LOCK:
        items = list(_RING)
    if level:
        floor = _LEVELS.get(level, 0)
        items = [r for r in items if _LEVELS.get(r.get("level", INFO), 20) >= floor]
    return items[-limit:]


def stats() -> dict:
    with _LOCK:
        items = list(_RING)
    counts: dict[str, int] = {}
    for r in items:
        lv = r.get("level", INFO)
        counts[lv] = counts.get(lv, 0) + 1
    return {
        "uptime_s": round(time.time() - _START, 1),
        "events_in_memory": len(items),
        "by_level": counts,
        "errors": counts.get(ERROR, 0) + counts.get(FATAL, 0),
        "journal": str(journal_path()),
        "hooks_installed": _HOOKS_INSTALLED,
    }
