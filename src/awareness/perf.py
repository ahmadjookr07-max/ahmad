# -*- coding: utf-8 -*-
"""محرك الأداء: القياس، كشف الاختناق، والتسريع الذاتي.

المبدأ الحاكم: **لا نُحسّن ما لا نقيس**. تعلّمنا هذا بالتجربة داخل هذا
المشروع نفسه: أضفنا "مرشّحًا سريعًا" للجراح بحدسٍ أنه يسرّع، فقاسنا
فوجدناه يرفع الزمن من 136s إلى 148s لأنه يُجيز عملًا يُرفض لاحقًا.
القياس وحده كشف أن 90% من الزمن كان في دورة إعادة لا في العمل المفيد.
لذا كل تسريع هنا يُقاس قبله وبعده، ولا يُثبَّت إلا إن أثبت نفعه.

ما يقدّمه:
    - ``@timed(name)`` و ``with span(name)``: قياس زمن أي عمل.
    - توزيع إحصائي لكل مقطع (count/p50/p95/max/total) في ذاكرة حلقية.
    - ``hotspots()``: ترتيب الاختناقات بالزمن الكلي (متوسط × تكرار)،
      لأن دالة 5ms تُنادى 10⁴ مرة أسوأ من دالة 2s تُنادى مرة.
    - ``recommend()``: يحوّل الأرقام إلى تشخيص عربي وإجراء مقترح.
    - أدوات تسريع جاهزة: ``memo`` (بذاكرة وTTL)، ``parallel_map``
      (توازٍ يحترم عدد الأنوية)، ``lazy`` (تحميل متأخر)، ``budget``
      (سقف زمني يحمي الواجهة من التجمد).
    - ``persist()`` / ``load()``: يبقى القياس عبر التشغيلات، فيتراكم
      وعي البرنامج بأدائه بدل أن يبدأ من الصفر كل مرة.

بلا أي تبعية خارجية، ويعمل بلا شبكة.
"""

from __future__ import annotations

import contextlib
import functools
import json
import math
import os
import statistics
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

try:
    from . import journal
except Exception:  # pragma: no cover - يعمل مستقلاً عند الاختبار
    journal = None  # type: ignore

try:
    from . import identity as _identity
except Exception:  # pragma: no cover
    _identity = None  # type: ignore


# ───────────────────────── ثوابت ─────────────────────────

_MAX_SAMPLES = 512          # عينات لكل مقطع (ذاكرة حلقية، حدّ ثابت)
_SLOW_MS = 400.0            # مقطع أبطأ من هذا يُعدّ بطيئًا للمستخدم
_UI_BUDGET_MS = 120.0       # سقف أي عمل على خيط الواجهة قبل أن يُحسّ التجمد
_HEAVY_IMPORT_MS = 250.0    # استيراد أثقل من هذا يستحق تحميلًا متأخرًا
_HOT_CALLS = 50             # تكرار يجعل المقطع مرشحًا للتذكير (memoize)
_REGRESS_FACTOR = 1.35      # تدهور بهذه النسبة عن الأساس = ارتداد أداء
_REGRESS_WINDOW = 20        # عدد أحدث القياسات التي يُحكم عليها الارتداد
_REGRESS_MIN_MS = 3.0       # دون هذا الزمن الضجيج أكبر من الإشارة


def _now() -> float:
    return time.perf_counter()


def _cpu_count() -> int:
    try:
        n = len(os.sched_getaffinity(0))  # type: ignore[attr-defined]
    except Exception:
        n = os.cpu_count() or 1
    return max(1, n)


# ───────────────────────── بنيات ─────────────────────────

@dataclass
class Segment:
    """قياسات مقطع واحد من العمل."""

    name: str
    samples: list[float] = field(default_factory=list)   # بالميلي ثانية
    count: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0
    errors: int = 0
    baseline_ms: float | None = None   # متوسط مرجعي من تشغيلات سابقة

    def add(self, ms: float, ok: bool = True) -> None:
        self.count += 1
        self.total_ms += ms
        self.max_ms = max(self.max_ms, ms)
        if not ok:
            self.errors += 1
        self.samples.append(ms)
        if len(self.samples) > _MAX_SAMPLES:
            # نُسقط النصف الأقدم لا عينة واحدة: يحفظ توزيعًا تمثيليًا
            # بتكلفة مُستهلَكة (amortized) بدل نسخ القائمة في كل نداء.
            del self.samples[:_MAX_SAMPLES // 2]

    @property
    def mean_ms(self) -> float:
        return self.total_ms / self.count if self.count else 0.0

    def pct(self, q: float) -> float:
        if not self.samples:
            return 0.0
        s = sorted(self.samples)
        i = min(len(s) - 1, max(0, int(math.ceil(q * len(s))) - 1))
        return s[i]

    @property
    def p50(self) -> float:
        return self.pct(0.50)

    @property
    def p95(self) -> float:
        return self.pct(0.95)

    @property
    def stdev_ms(self) -> float:
        return statistics.pstdev(self.samples) if len(self.samples) > 1 else 0.0

    def recent_ms(self, window: int = 20) -> float:
        """متوسط أحدث القياسات لا متوسط العمر كله.

        هذا الفرق حرج وليس تفصيلًا: لو سُجّلت 3000 قياس سريع
        ثم صار المسار أبطأ ثلاث مرات، فإن المتوسط التراكمي
        سيُغرق التباطؤ في التاريخ ولن يتجاوز العتبة أبدًا — فيشتكي
        المالك من البطء والبرنامج يقول «أدائي طبيعي». الارتداد حادث
        زمني، فيجب قياسه على نافذة متحركة لا على متوسط أبدي.
        """
        if not self.samples:
            return self.mean_ms
        w = self.samples[-max(1, int(window)):]
        return sum(w) / len(w)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "count": self.count,
            "mean_ms": round(self.mean_ms, 2), "p50_ms": round(self.p50, 2),
            "p95_ms": round(self.p95, 2), "max_ms": round(self.max_ms, 2),
            "total_ms": round(self.total_ms, 2), "errors": self.errors,
            "baseline_ms": (round(self.baseline_ms, 2)
                            if self.baseline_ms else None),
        }


@dataclass
class Advice:
    """توصية تسريع مبنية على قياس، لا على حدس."""

    segment: str
    kind: str            # lazy_import | memoize | parallel | offload | regress
    severity: str        # info | warn | high
    evidence_ar: str     # الرقم الذي بنى الحكم
    action_ar: str       # ما يجب فعله
    gain_hint_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"segment": self.segment, "kind": self.kind,
                "severity": self.severity, "evidence_ar": self.evidence_ar,
                "action_ar": self.action_ar,
                "gain_hint_ms": round(self.gain_hint_ms, 1)}


# ───────────────────────── المحرك ─────────────────────────

class PerfEngine:
    """يقيس، يكشف، ويقترح — ويحفظ وعيه بأدائه بين التشغيلات."""

    def __init__(self, store: Path | None = None) -> None:
        self._segs: dict[str, Segment] = {}
        self._lock = threading.RLock()
        self._store = store
        self._t0 = _now()
        self._enabled = os.environ.get("MIS_PERF_OFF") != "1"
        if store:
            self.load()

    # ── القياس ──

    def record(self, name: str, ms: float, ok: bool = True) -> None:
        if not self._enabled:
            return
        with self._lock:
            seg = self._segs.get(name)
            if seg is None:
                seg = self._segs[name] = Segment(name)
            seg.add(ms, ok)

    @contextlib.contextmanager
    def span(self, name: str):
        """يقيس كتلة عمل. يسجّل الزمن حتى لو رُفع استثناء."""
        if not self._enabled:
            yield
            return
        t = _now()
        ok = True
        try:
            yield
        except BaseException:
            ok = False
            raise
        finally:
            self.record(name, (_now() - t) * 1000.0, ok)

    def timed(self, name: str | None = None) -> Callable:
        """مُزخرِف يقيس دالة. الاسم الافتراضي وحدة.دالة."""
        def deco(fn: Callable) -> Callable:
            label = name or f"{getattr(fn, '__module__', '?')}.{fn.__name__}"

            @functools.wraps(fn)
            def wrap(*a, **kw):
                with self.span(label):
                    return fn(*a, **kw)
            return wrap
        return deco

    # ── القراءة ──

    def segments(self) -> list[Segment]:
        with self._lock:
            return list(self._segs.values())

    def get(self, name: str) -> Segment | None:
        with self._lock:
            return self._segs.get(name)

    def hotspots(self, top: int = 10) -> list[Segment]:
        """أهم الاختناقات بالزمن الكلي.

        الترتيب بالزمن الكلي (متوسط × تكرار) لا بالمتوسط وحده: دالة
        تستهلك 5ms لكنها تُنادى عشرة آلاف مرة (50s) أسوأ بكثير من دالة
        تستهلك 2s وتُنادى مرة. هذا أكثر مقاييس الأداء إساءةَ فهم.
        """
        segs = [s for s in self.segments() if s.count]
        segs.sort(key=lambda s: s.total_ms, reverse=True)
        return segs[:top]

    def summary(self) -> dict[str, Any]:
        segs = self.segments()
        return {
            "uptime_s": round(_now() - self._t0, 1),
            "segments": len(segs),
            "calls": sum(s.count for s in segs),
            "total_ms": round(sum(s.total_ms for s in segs), 1),
            "errors": sum(s.errors for s in segs),
            "hotspots": [s.to_dict() for s in self.hotspots(5)],
        }

    # ── التشخيص ──

    def recommend(self) -> list[Advice]:
        """يحوّل الأرقام إلى توصيات مفهومة قابلة للتنفيذ."""
        out: list[Advice] = []
        for s in self.segments():
            if not s.count:
                continue
            nm, mean, p95 = s.name, s.mean_ms, s.p95

            # 1) ارتداد أداء عن أساس محفوظ من تشغيلات سابقة.
            # نقارن أحدث القياسات لا المتوسط التراكمي، وإلا أغرق
            # التاريخ الطويل أي تباطؤ جديد ومرّ دون إنذار.
            recent = s.recent_ms(_REGRESS_WINDOW)
            if (s.baseline_ms
                    and recent > s.baseline_ms * _REGRESS_FACTOR
                    and recent > _REGRESS_MIN_MS):
                out.append(Advice(
                    nm, "regress", "high",
                    f"صار {recent:.0f}ms بعد أن كان {s.baseline_ms:.0f}ms "
                    f"(أبطأ {recent / max(s.baseline_ms, 1e-9):.1f}× في أحدث "
                    f"{min(s.count, _REGRESS_WINDOW)} قياسًا).",
                    "أراجع آخر تغيير مسّ هذا المسار وأتراجع عنه إن لم "
                    "يُفِد.", recent - s.baseline_ms))

            # 2) استيراد ثقيل → تحميل متأخر
            if nm.startswith("import.") and mean > _HEAVY_IMPORT_MS:
                out.append(Advice(
                    nm, "lazy_import", "warn",
                    f"استيراد يستهلك {mean:.0f}ms عند الإقلاع.",
                    "أنقله إلى تحميل متأخر داخل أول استخدام فعلي، "
                    "فيقلّ زمن فتح البرنامج.", mean))

            # 3) دالة متكررة قصيرة → تذكير النتائج
            if s.count >= _HOT_CALLS and mean < 50 and s.total_ms > 1000:
                out.append(Advice(
                    nm, "memoize", "warn",
                    f"نُوديت {s.count} مرة بمتوسط {mean:.1f}ms "
                    f"(المجموع {s.total_ms / 1000:.1f}s).",
                    "أُخزّن نتائجها مؤقتًا فالمدخلات تتكرر، ويسقط "
                    "الزمن الكلي.", s.total_ms * 0.6))

            # 4) عمل ثقيل قابل للتوازي
            if mean > 1500 and s.count >= 2 and _cpu_count() > 1:
                out.append(Advice(
                    nm, "parallel", "warn",
                    f"عمل ثقيل {mean:.0f}ms × {s.count} على "
                    f"{_cpu_count()} نواة متاحة.",
                    "أُوزّعه على الأنوية المتاحة بدل تنفيذه تسلسليًا.",
                    s.total_ms * (1 - 1 / min(_cpu_count(), 4))))

            # 5) عمل يجمّد الواجهة
            if nm.startswith("ui.") and p95 > _UI_BUDGET_MS:
                out.append(Advice(
                    nm, "offload", "high",
                    f"يستهلك {p95:.0f}ms على خيط الواجهة "
                    f"(السقف {_UI_BUDGET_MS:.0f}ms).",
                    "أنقله إلى خيط خلفي مع مؤشر تقدم، فلا تتجمد "
                    "الواجهة.", p95))

            # 6) تباين عالٍ = سلوك غير مستقر
            if s.count >= 10 and s.stdev_ms > mean and mean > _SLOW_MS:
                out.append(Advice(
                    nm, "unstable", "info",
                    f"زمنه متقلب جدًا (متوسط {mean:.0f}ms، تشتّت "
                    f"{s.stdev_ms:.0f}ms).",
                    "أفحص إن كان يعتمد على قرص أو شبكة، وأضيف كاشًا "
                    "أو مهلة واضحة.", 0.0))

        rank = {"high": 0, "warn": 1, "info": 2}
        out.sort(key=lambda a: (rank.get(a.severity, 3), -a.gain_hint_ms))
        return out

    def report_ar(self, top: int = 5) -> str:
        """تقرير عربي موجز يفهمه غير المبرمج."""
        segs = self.hotspots(top)
        if not segs:
            return "لم أقِس عملًا كافيًا بعد لأحكم على سرعتي."
        lines = ["أبطأ ما لديّ الآن:"]
        for i, s in enumerate(segs, 1):
            lines.append(
                f"{i}. {s.name}: متوسط {s.mean_ms:.0f}ms، "
                f"أسوأ حالة {s.max_ms:.0f}ms، تكرار {s.count}، "
                f"المجموع {s.total_ms / 1000:.1f}s")
        adv = self.recommend()
        if adv:
            lines.append("")
            lines.append("وما أنوي فعله:")
            for a in adv[:top]:
                lines.append(f"• {a.segment}: {a.evidence_ar} {a.action_ar}")
        return "\n".join(lines)

    # ── البقاء بين التشغيلات ──

    def promote_baseline(self) -> int:
        """يعتمد القياس الحالي أساسًا يُقاس عليه الارتداد لاحقًا."""
        n = 0
        with self._lock:
            for s in self._segs.values():
                if s.count >= 3:
                    s.baseline_ms = s.mean_ms
                    n += 1
        self.persist()
        return n

    def persist(self) -> bool:
        if not self._store:
            return False
        try:
            self._store.parent.mkdir(parents=True, exist_ok=True)
            data = {"v": 1, "saved_at": time.time(),
                    "segments": [s.to_dict() for s in self.segments()]}
            tmp = self._store.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            tmp.replace(self._store)   # كتابة ذرّية: لا ملف نصف مكتوب
            return True
        except Exception as exc:
            if journal:
                journal.debug("perf_persist_failed", error=str(exc)[:200])
            return False

    def load(self) -> bool:
        """يستعيد الأساس المرجعي فقط، لا العينات.

        العينات القديمة لا تصف التشغيل الحالي (جهاز مختلف، حِمل مختلف)،
        لكن **الأساس** ضروري لكشف الارتداد. لذا نستعيده وحده.
        """
        if not self._store or not self._store.exists():
            return False
        try:
            data = json.loads(self._store.read_text(encoding="utf-8"))
            with self._lock:
                for d in data.get("segments", []):
                    nm = d.get("name")
                    if not nm:
                        continue
                    seg = self._segs.get(nm) or Segment(nm)
                    seg.baseline_ms = d.get("baseline_ms") or d.get("mean_ms")
                    self._segs[nm] = seg
            return True
        except Exception:
            return False

    def reset(self) -> None:
        with self._lock:
            for s in self._segs.values():
                s.samples.clear()
                s.count = 0
                s.total_ms = 0.0
                s.max_ms = 0.0
                s.errors = 0


# ───────────────────────── أدوات التسريع ─────────────────────────

def parallel_map(fn: Callable, items: Sequence, *,
                 workers: int | None = None,
                 threshold: int = 2) -> list:
    """ينفّذ ``fn`` على العناصر متوازيًا مع حفظ الترتيب.

    يحترم عدد الأنوية ويترك نواة للنظام والواجهة. تحت ``threshold``
    ينفّذ تسلسليًا لأن كلفة إنشاء الخيوط تفوق الفائدة. أي استثناء
    يُرجَع كقيمة لا يُرفع، فلا يُسقط عنصرٌ فاشل بقية الدفعة.
    """
    items = list(items)
    if len(items) < max(2, threshold):
        return [_safe(fn, x) for x in items]
    n = workers or min(len(items), max(1, _cpu_count() - 1), 8)
    if n <= 1:
        return [_safe(fn, x) for x in items]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=n) as ex:
        return list(ex.map(lambda x: _safe(fn, x), items))


def _safe(fn: Callable, x) -> Any:
    try:
        return fn(x)
    except Exception as exc:
        return exc


def memo(ttl_s: float = 0.0, maxsize: int = 256) -> Callable:
    """تذكير نتائج بمهلة اختيارية وحدٍّ للحجم.

    ``functools.lru_cache`` لا يدعم انتهاء الصلاحية، وهو مطلوب لقيم
    تعتمد على القرص أو البيئة (وجود نموذج، مساحة حرة). الحد يمنع
    تسرب الذاكرة في تشغيل طويل.
    """
    def deco(fn: Callable) -> Callable:
        cache: dict[Any, tuple[float, Any]] = {}
        lock = threading.Lock()

        @functools.wraps(fn)
        def wrap(*a, **kw):
            key = (a, tuple(sorted(kw.items()))) if kw else a
            try:
                hash(key)
            except TypeError:
                return fn(*a, **kw)     # مدخل غير قابل للتخزين
            now = time.time()
            with lock:
                hit = cache.get(key)
                if hit and (not ttl_s or now - hit[0] < ttl_s):
                    return hit[1]
            val = fn(*a, **kw)
            with lock:
                if len(cache) >= maxsize:
                    cache.pop(next(iter(cache)), None)   # FIFO بسيط
                cache[key] = (now, val)
            return val

        wrap.cache_clear = cache.clear   # type: ignore[attr-defined]
        return wrap
    return deco


class lazy:
    """قيمة تُحسب عند أول استخدام فعلي فقط.

    تُستخدم للاستيرادات والنماذج الثقيلة: زمن الإقلاع لا يدفع ثمن ما
    قد لا يُستخدم في هذه الجلسة أصلًا.
    """

    __slots__ = ("_fn", "_val", "_done", "_lock", "_name")

    def __init__(self, fn: Callable[[], Any], name: str = "") -> None:
        self._fn, self._val, self._done = fn, None, False
        self._lock = threading.Lock()
        self._name = name or getattr(fn, "__name__", "lazy")

    def get(self) -> Any:
        if self._done:
            return self._val
        with self._lock:
            if not self._done:
                t = _now()
                self._val = self._fn()
                self._done = True
                engine().record(f"lazy.{self._name}", (_now() - t) * 1000.0)
        return self._val

    def __call__(self) -> Any:
        return self.get()

    @property
    def ready(self) -> bool:
        return self._done


@contextlib.contextmanager
def budget(name: str, ms: float, on_exceed: Callable[[float], None] | None = None):
    """يقيس كتلة ويُنبّه إن تجاوزت سقفها الزمني.

    لا يقطع العمل (القطع القسري يترك حالة نصفية خطِرة)، بل يسجّل
    التجاوز ليعرف البرنامج أن هذا المسار يحتاج نقلًا لخيط خلفي.
    """
    t = _now()
    try:
        yield
    finally:
        el = (_now() - t) * 1000.0
        engine().record(name, el)
        if el > ms:
            if journal:
                journal.warn("perf_budget_exceeded", segment=name,
                             elapsed_ms=round(el, 1), budget_ms=ms)
            if on_exceed:
                try:
                    on_exceed(el)
                except Exception:
                    pass


# ───────────────────────── الواجهة المفردة ─────────────────────────

_ENGINE: PerfEngine | None = None
_E_LOCK = threading.Lock()


def _store_path() -> Path | None:
    """موضع حفظ القياسات: نفس مجلد الوعي الذي تستخدمه بقية الطبقة."""
    try:
        from . import identity
        return identity.awareness_dir() / "perf.json"
    except Exception:
        env = os.environ.get("MIS_DATA_ROOT", "").strip()
        return Path(env) / "awareness" / "perf.json" if env else None


def engine() -> PerfEngine:
    global _ENGINE
    with _E_LOCK:
        if _ENGINE is None:
            _ENGINE = PerfEngine(_store_path())
        return _ENGINE


def span(name: str):
    return engine().span(name)


def timed(name: str | None = None) -> Callable:
    return engine().timed(name)


def record(name: str, ms: float, ok: bool = True) -> None:
    engine().record(name, ms, ok)


def hotspots(top: int = 10) -> list[dict]:
    return [s.to_dict() for s in engine().hotspots(top)]


def recommend() -> list[dict]:
    return [a.to_dict() for a in engine().recommend()]


def report_ar(top: int = 5) -> str:
    return engine().report_ar(top)


def summary() -> dict:
    return engine().summary()


def persist() -> bool:
    return engine().persist()


def promote_baseline() -> int:
    return engine().promote_baseline()


def measure(fn: Callable, *a, **kw) -> tuple[Any, float]:
    """ينفّذ ويُرجع (النتيجة، الزمن بالميلي ثانية). للمقارنة قبل/بعد."""
    t = _now()
    try:
        return fn(*a, **kw), (_now() - t) * 1000.0
    except Exception:
        return None, (_now() - t) * 1000.0


def compare(label: str, before: Callable, after: Callable,
            rounds: int = 3) -> dict:
    """يقيس بديلين ويحكم بينهما بالأرقام.

    هذه الدالة هي ترجمة الدرس الذي كلّفنا وقتًا: التسريع المُفترَض قد
    يكون تبطيئًا. نأخذ **أفضل** زمن لكل بديل لا المتوسط، لأن الضجيج
    البيئي يضيف زمنًا ولا ينقصه، فالأدنى أقرب للكلفة الحقيقية.
    """
    b = min(measure(before)[1] for _ in range(max(1, rounds)))
    a = min(measure(after)[1] for _ in range(max(1, rounds)))
    gain = (b - a) / b * 100.0 if b else 0.0
    better = a < b
    return {"label": label, "before_ms": round(b, 2), "after_ms": round(a, 2),
            "gain_pct": round(gain, 1), "better": better,
            "verdict_ar": (f"البديل أسرع بنسبة {gain:.0f}% "
                           f"({b:.0f}ms ← {a:.0f}ms)" if better else
                           f"البديل أبطأ بنسبة {-gain:.0f}% "
                           f"({b:.0f}ms ← {a:.0f}ms)، فلا أعتمده")}
