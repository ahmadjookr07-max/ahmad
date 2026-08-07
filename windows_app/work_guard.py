# -*- coding: utf-8 -*-
"""work_guard — حماية عمل المالك من الفقدان (م-14).

## البلاغ
«قام ب اخراجي في منتصف العمل وانا اقوم ب الربط والتعديل على الصور
و**قام ب حذف العمل**».

## العلل المقيسة
| العلة | الأثر |
| --- | --- |
| الحفظ التلقائي كل **90 ثانية** فقط | حتى 90 ثانية عمل تضيع |
| **لا حفظ إطلاقًا** عند الربط أو اعتماد تعديل | العمل الأهم بلا حماية |
| إخفاق الحفظ **يُبتلع صامتًا** (`except: pass`) | المالك يظن عمله محفوظًا |
| **لا مراقب انهيار ولا استرداد** | بعد الخروج المفاجئ لا شيء يُستأنف |

## ما تفعله هذه الوحدة
1. **حفظ فوري بالأحداث** بعد كل ربط وتعديل معتمَد وتعيين واجهة.
2. **كتابة ذرّية**: ملف مؤقت في نفس المجلد ثم `os.replace` — فلو
   مات البرنامج أثناء الكتابة بقي الملف السابق سليمًا.
3. **علامة جلسة حيّة**: وجودها عند الفتح التالي = انهيار ⇒ يُعرض
   «وجدنا عملًا غير مكتمل — استأنف؟».
4. **الإخفاق يُعلَن** في شريط الحالة ويُسجَّل، لا يُبتلع.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Callable

__all__ = [
    "atomic_write_json",
    "atomic_write_bytes",
    "CrashSentinel",
    "install_work_guard",
    "CRITICAL_METHODS",
]

# أسماء دوال الواجهة التي يجب أن يتلوها حفظ فوري
# (أُخذت من الأسماء الفعلية في `native_app.py` لا من التخمين)
CRITICAL_METHODS = (
    "_apply_manual_links",
    "_on_manual_links_done",
    "_set_primary_image",
    "_save_nutrition_result",
    "_on_individual_edit_done",
    "_commit_unified_edit",
    "_apply_rename_all",
    "_on_batch_done",
)


def _log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    p = (Path(base) / "MarketImageStudio" if base
         else Path.home() / ".market_image_studio")
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        p = Path(tempfile.gettempdir()) / "MarketImageStudio"
        p.mkdir(parents=True, exist_ok=True)
    return p


def _log(msg: str) -> None:
    try:
        with open(_log_dir() / "work_guard.log", "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


# ═══════════════════════ الكتابة الذرّية ═══════════════════════

def atomic_write_bytes(path: str | Path, data: bytes) -> None:
    """يكتب بايتات ذرّيًا: ملف مؤقت في نفس المجلد ثم `os.replace`.

    الملف المؤقت **يجب** أن يكون في نفس المجلد وإلا صار `replace`
    نقلًا بين أقسام فلا يبقى ذرّيًا.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=p.name + ".", suffix=".tmp",
                               dir=str(p.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(p))
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def atomic_write_json(path: str | Path, obj: Any) -> None:
    """يكتب JSON ذرّيًا بترميز UTF-8 بلا هروب للعربية."""
    data = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
    atomic_write_bytes(path, data)


# ═══════════════════════ مراقب الانهيار ═══════════════════════

class CrashSentinel:
    """علامة جلسة حيّة تكشف الخروج غير النظيف.

    ملف `.live` يُكتب عند البدء ويُحذف عند الإغلاق النظيف. فوجوده
    في التشغيل التالي يعني أن البرنامج مات دون إغلاق — وهذا بالضبط
    ما حدث للمالك.
    """

    def __init__(self, session_dir: str | Path | None = None) -> None:
        self.dir = Path(session_dir) if session_dir else _log_dir()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "session.live"
        self._prev: dict | None = None

    def check_previous(self) -> dict | None:
        """يقرأ علامة الجلسة السابقة إن وُجدت (= انهيار)."""
        if not self.path.exists():
            return None
        try:
            self._prev = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self._prev = {"session_id": "", "note": "علامة تالفة"}
        return self._prev

    def begin(self, session_id: str = "", extra: dict | None = None) -> None:
        payload = {
            "session_id": session_id,
            "pid": os.getpid(),
            "started_at": time.time(),
            "started_human": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        if extra:
            payload.update(extra)
        try:
            atomic_write_json(self.path, payload)
        except Exception as exc:
            _log(f"فشل فتح علامة الجلسة: {exc}")

    def touch(self, **fields: Any) -> None:
        """يحدّث العلامة (يُستدعى بعد كل حفظ فوري)."""
        try:
            cur: dict = {}
            if self.path.exists():
                cur = json.loads(self.path.read_text(encoding="utf-8"))
            cur.update(fields)
            cur["last_save"] = time.time()
            cur["last_save_human"] = time.strftime("%Y-%m-%d %H:%M:%S")
            atomic_write_json(self.path, cur)
        except Exception:
            pass

    def end(self) -> None:
        """يغلق العلامة (إغلاق نظيف)."""
        try:
            if self.path.exists():
                self.path.unlink()
        except Exception:
            pass


# ═══════════════════════ التركيب على الواجهة ═══════════════════════

def install_work_guard(window: Any,
                       save_fn: Callable[[], Any] | None = None,
                       autosave_seconds: int = 20,
                       ) -> dict:
    """يركّب حماية العمل على نافذة التطبيق.

    - يلفّ الدوال الحاسمة فيحفظ **بعد** كل واحدة منها فورًا
    - يقصّر الحفظ التلقائي من 90 ثانية إلى `autosave_seconds`
    - يفتح علامة جلسة ويكشف انهيار الجلسة السابقة
    - يُعلن إخفاق الحفظ في شريط الحالة ولا يبتلعه

    يعيد قاموس تقرير بما رُكّب فعلًا (للاختبار والتشخيص).
    """
    report: dict[str, Any] = {"wrapped": [], "autosave": False,
                              "sentinel": False, "crashed_before": None}

    if save_fn is None:
        for name in ("v2_save_session", "_save_session", "save_session"):
            fn = getattr(window, name, None)
            if callable(fn):
                save_fn = fn
                report["save_fn"] = name
                break
    if save_fn is None:
        _log("لم يُعثر على دالة حفظ — الحماية معطّلة")
        report["error"] = "no_save_fn"
        return report

    def _notify(msg: str) -> None:
        for attr in ("statusBar", "status_bar"):
            sb = getattr(window, attr, None)
            try:
                bar = sb() if callable(sb) else sb
                if bar is not None and hasattr(bar, "showMessage"):
                    bar.showMessage(msg, 6000)
                    return
            except Exception:
                pass
        lbl = getattr(window, "status_label", None)
        if lbl is not None and hasattr(lbl, "setText"):
            try:
                lbl.setText(msg)
            except Exception:
                pass

    sentinel = CrashSentinel()
    report["crashed_before"] = sentinel.check_previous()
    sid = ""
    try:
        st = getattr(window, "_v2_session", None) or getattr(
            window, "session", None)
        sid = str(getattr(st, "session_id", "") or "")
    except Exception:
        pass
    sentinel.begin(sid)
    report["sentinel"] = True
    window._work_guard_sentinel = sentinel

    def guarded_save(reason: str = "") -> bool:
        """حفظ محروس: يُعلن الإخفاق ولا يبتلعه."""
        try:
            save_fn()
            sentinel.touch(last_reason=reason)
            return True
        except Exception as exc:
            _log(f"فشل الحفظ ({reason}): {exc}\n{traceback.format_exc()}")
            _notify(f"⚠ تعذّر حفظ الجلسة ({reason}) — {exc}")
            return False

    window._guarded_save = guarded_save

    for name in CRITICAL_METHODS:
        orig = getattr(window, name, None)
        if not callable(orig):
            continue

        def make_wrapper(fn: Callable, label: str) -> Callable:
            def wrapper(*a: Any, **kw: Any) -> Any:
                out = fn(*a, **kw)
                guarded_save(label)
                return out
            wrapper.__name__ = getattr(fn, "__name__", label)
            wrapper._work_guard_wrapped = True
            return wrapper

        try:
            setattr(window, name, make_wrapper(orig, name))
            report["wrapped"].append(name)
        except Exception as exc:
            _log(f"تعذّر لفّ {name}: {exc}")

    for tname in ("_autosave_timer", "_v2_autosave_timer", "autosave_timer"):
        t = getattr(window, tname, None)
        if t is not None and hasattr(t, "setInterval"):
            try:
                t.setInterval(int(autosave_seconds * 1000))
                report["autosave"] = True
                report["autosave_timer"] = tname
                break
            except Exception:
                pass

    orig_close = getattr(window, "closeEvent", None)
    if callable(orig_close):
        def close_event(ev: Any) -> Any:
            guarded_save("closeEvent")
            sentinel.end()
            return orig_close(ev)
        try:
            window.closeEvent = close_event
            report["close_hooked"] = True
        except Exception:
            pass

    _log(f"رُكّبت حماية العمل: {report}")
    return report
