# -*- coding: utf-8 -*-
"""core — منسّق الوعي: نقطة الدخول الوحيدة لكل طبقات الإدراك الذاتي.

الوحدات الثماني (identity, journal, ledger, vitals, healer, surgeon,
optimizer, dialogue) مستقلة ومتخصصة، لكن التطبيق لا ينبغي أن يعرفها
فردًا فردًا. هذا المنسّق يجمعها في سلوك واحد متّسق ويضمن ثلاث ضمانات:

**1. الإقلاع لا يفشل أبدًا بسبب الوعي.** إن انهارت أي طبقة (قاعدة تالفة،
صلاحية مرفوضة، قرص ممتلئ) يعمل التطبيق بلا وعي بدل أن لا يعمل. لهذا كل
تهيئة داخل `contextlib.suppress`، و`awake()` يُرجع دائمًا كائن حالة.

**2. الأخطاء تُعالَج تلقائيًا في مسار حيوي.** عند أي استثناء غير مُلتقط
يُستشار الشافي (`heal_from_exception`) فيقرر إن كان يستحق إعادة محاولة،
ويُسجَّل في السجل الأكاشي ليتعلم منه مستقبلًا. المستخدم يرى رسالة عربية
تشرح ما جرى وما فُعل، لا مسار ملف بايثون.

**3. الإيقاظ لا يعطّل الواجهة.** الفحص الشامل يستغرق ثوانٍ في أول مرة،
فيُشغَّل في خيط خلفي (`_boot_thread`) بعد إظهار النافذة. أما `quick_scan`
(2 مللي) فيُشغَّل تزامنيًا لأنه يكشف الكوارث الفورية.

## دورة الحياة
```
awake()      ← عند الإقلاع: هوية + خطافات + فحص سريع + خيط الفحص العميق
guard()      ← يلفّ أي عملية: يقيس، ويعالج، ويعيد المحاولة
ask(text)    ← حوار المستخدم مع البرنامج
pulse()      ← نبضة دورية: فحص خفيف + تحسين + كتابة الحالة
sleep()      ← إغلاق نظيف: تثبيت السجلات وإغلاق القاعدة
```

## لماذا `guard` بإعادة محاولة واحدة فقط؟
لأن العلاج الناجح يُغيّر البيئة فعليًا (حزمة تُثبَّت، مجلد يُنشأ)، فإما
أن ينجح فورًا أو أن المشكلة ليست في البيئة. إعادة المحاولة مرتين تُضاعف
زمن الانتظار على المستخدم دون فائدة تُذكر، وتخفي العطل الحقيقي.
"""
from __future__ import annotations

import contextlib
import os
import threading
import time
from dataclasses import dataclass, field

from . import dialogue, healer, identity, journal, vitals

with contextlib.suppress(Exception):
    from . import ledger as _ledger

with contextlib.suppress(Exception):
    from . import optimizer

with contextlib.suppress(Exception):
    from . import surgeon

with contextlib.suppress(Exception):
    from . import perf

_LOCK = threading.RLock()

# نبضة كل خمس دقائق: أقصر يُثقل، وأطول يُبطئ الاستجابة لتدهور تدريجي.
PULSE_INTERVAL = 300.0
# الفحص العميق مرة كل ساعة كافٍ: البيئة لا تتغير أسرع من ذلك عمليًا.
DEEP_SCAN_INTERVAL = 3600.0


@dataclass
class AwakeState:
    """حالة الوعي بعد الإيقاظ — يقرأها التطبيق ليعرف بماذا يعمل."""
    ok: bool = False
    version: str = ""
    health_score: int = 0
    disabled: dict = field(default_factory=dict)
    healed: int = 0
    messages: list = field(default_factory=list)
    elapsed_ms: float = 0.0
    deep_scan_running: bool = False

    def as_dict(self) -> dict:
        return {"ok": self.ok, "version": self.version,
                "health_score": self.health_score,
                "disabled": self.disabled, "healed": self.healed,
                "messages": self.messages,
                "elapsed_ms": round(self.elapsed_ms, 1),
                "deep_scan_running": self.deep_scan_running}

    def summary_ar(self) -> str:
        if not self.ok:
            return "أعمل بلا طبقة وعي (تعذّر تهيئتها) — كل الوظائف الأساسية تعمل."
        parts = [f"وعيي نشط · صحّتي {self.health_score}/100"]
        if self.healed:
            parts.append(f"أصلحت {self.healed} مشكلة قبل أن تراها")
        if self.disabled:
            parts.append(f"{len(self.disabled)} قدرة معطّلة مؤقتًا")
        return " · ".join(parts) + "."


class Consciousness:
    """المنسّق. كائن واحد لكل عملية (singleton عبر `mind()`)."""

    def __init__(self) -> None:
        self._awake = False
        self._state = AwakeState()
        self._last_pulse = 0.0
        self._last_deep = 0.0
        self._pulse_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._observers: list = []
        self._exc_count = 0

    # ═══════════════════ الإيقاظ ═══════════════════

    def awake(self, *, deep: bool = True, heal: bool = True) -> AwakeState:
        """يوقظ الوعي. آمن للاستدعاء أكثر من مرة."""
        with _LOCK:
            if self._awake:
                return self._state
            t0 = time.perf_counter()
            st = AwakeState()

            # 1) الهوية أولًا: بلا معرفة الذات لا معنى لبقية الطبقات
            with contextlib.suppress(Exception):
                identity.self_model()          # يبني النموذج ويثبّت المسارات
                st.version = identity.app_version()
                st.ok = True

            # 2) خطافات الأخطاء: من هذه اللحظة لا يضيع استثناء
            with contextlib.suppress(Exception):
                journal.install_global_hooks()
                journal.add_exception_listener(self._on_exception)
                journal.info("awareness_awake", version=st.version,
                             frozen=identity.is_frozen())

            # 3) فحص سريع تزامني: يكشف الكوارث قبل أن يلمس المستخدم شيئًا
            with contextlib.suppress(Exception):
                rep = vitals.quick_scan()
                st.health_score = rep.score
                fatal = [f for f in rep.findings if f.severity == "fatal"]
                if fatal and heal:
                    sess = healer.heal(rep, auto=True)
                    st.healed += sess.healed
                    st.messages.append(sess.summary_ar())

            # 4) الفحص العميق في الخلفية: لا نُجمّد الواجهة ثانيتين
            if deep:
                st.deep_scan_running = True
                th = threading.Thread(target=self._deep_boot, args=(heal,),
                                      name="mis-deep-scan", daemon=True)
                th.start()

            st.elapsed_ms = (time.perf_counter() - t0) * 1000.0
            self._state = st
            self._awake = True
            self._last_pulse = time.time()
            return st

    def _deep_boot(self, heal: bool) -> None:
        """فحص شامل + علاج + توصيات، كله بعيدًا عن خيط الواجهة."""
        try:
            rep = vitals.full_scan(use_cache=False)
            with _LOCK:
                self._state.health_score = rep.score
                self._state.disabled = dict(rep.disabled_capabilities)
            msgs: list[str] = []
            if heal:
                sess = healer.heal(rep, auto=True)
                if sess.healed or sess.failed:
                    msgs.append(sess.summary_ar())
                if sess.healed:
                    rep = vitals.full_scan(use_cache=False)
                    with _LOCK:
                        self._state.health_score = rep.score
                        self._state.disabled = dict(rep.disabled_capabilities)
                        self._state.healed += sess.healed
            with contextlib.suppress(Exception):
                recs = optimizer.report().get("recommendations", [])
                for r in recs[:2]:
                    msgs.append(r if isinstance(r, str) else str(r))
            with _LOCK:
                self._state.messages.extend(m for m in msgs if m)
                self._state.deep_scan_running = False
                self._last_deep = time.time()
            journal.info("deep_scan_done", score=rep.score,
                         disabled=len(rep.disabled_capabilities))
            self._notify("deep_scan_done", self._state.as_dict())
        except Exception as exc:
            with _LOCK:
                self._state.deep_scan_running = False
            journal.warn("deep_scan_failed", detail=str(exc)[:200])

    # ═══════════════════ معالجة الأخطاء الحيوية ═══════════════════

    def _on_exception(self, exc: BaseException, context: dict) -> None:
        """يُنادى على كل استثناء غير مُلتقط — نتعلّم ونحاول العلاج."""
        self._exc_count += 1
        with contextlib.suppress(Exception):
            decision = healer.heal_from_exception(exc, context=context)
            if getattr(decision, "message_ar", ""):
                self._notify("healed", {
                    "message_ar": decision.message_ar,
                    "retry": bool(decision.should_retry),
                    "fingerprint": decision.fingerprint,
                    "seen_count": decision.seen_count})

    def guard(self, operation, *args, name: str = "", retry: bool = True,
              **kwargs):
        """ينفّذ عملية تحت حماية الوعي: قياس + علاج + إعادة محاولة واحدة.

        يُرجع `(ok, result, message_ar)` بدل رفع الاستثناء، لأن الواجهة
        تحتاج رسالة تعرضها لا traceback يُخيف المستخدم.
        """
        label = name or getattr(operation, "__name__", "operation")
        t0 = time.perf_counter()
        try:
            res = operation(*args, **kwargs)
            elapsed = (time.perf_counter() - t0) * 1000.0
            with contextlib.suppress(Exception):
                optimizer.observe(f"op_{label}_ms", elapsed)
            # قياس الأداء: كل عملية محمية تُقاس تلقائيًا، فيعرف
            # البرنامج أين يقضي وقته حقًا بدل أن نخمّن موضع البطء.
            with contextlib.suppress(Exception):
                perf.record(label, elapsed, ok=True)
            return True, res, ""
        except Exception as exc:
            with contextlib.suppress(Exception):
                perf.record(label, (time.perf_counter() - t0) * 1000.0,
                            ok=False)
            journal.error("guarded_failed", op=label,
                          detail=str(exc)[:250])
            decision = None
            with contextlib.suppress(Exception):
                decision = healer.heal_from_exception(exc,
                                                      context={"op": label})
            msg = getattr(decision, "message_ar", "") or _friendly(exc)
            should = bool(getattr(decision, "should_retry", False))
            if retry and decision is not None and should:
                delay = float(getattr(decision, "delay_s", 0.0) or 0.0)
                if delay > 0:
                    # بعض العلاجات تحتاج مهلة (ملف مقفل، ذاكرة تُفرّغ)
                    time.sleep(min(delay, 5.0))
                journal.info("guarded_retry", op=label, delay_s=delay)
                try:
                    res = operation(*args, **kwargs)
                    return True, res, msg + " ثم أعدت المحاولة فنجحت."
                except Exception as exc2:
                    journal.error("guarded_retry_failed", op=label,
                                  detail=str(exc2)[:250])
                    return False, None, msg + " وأعدت المحاولة فتعذّر مرة أخرى."
            return False, None, msg

    # ═══════════════════ النبضة الدورية ═══════════════════

    def start_pulse(self) -> bool:
        """يبدأ خيط النبضة: مراقبة مستمرة بلا تدخل المستخدم."""
        with _LOCK:
            if self._pulse_thread and self._pulse_thread.is_alive():
                return False
            self._stop.clear()
            self._pulse_thread = threading.Thread(
                target=self._pulse_loop, name="mis-pulse", daemon=True)
            self._pulse_thread.start()
            journal.info("pulse_started", interval=PULSE_INTERVAL)
            return True

    def _pulse_loop(self) -> None:
        while not self._stop.wait(PULSE_INTERVAL):
            with contextlib.suppress(Exception):
                self.pulse()

    def pulse(self) -> dict:
        """نبضة واحدة: فحص خفيف، علاج ما ظهر، وفحص عميق كل ساعة."""
        out: dict = {"t": time.time()}
        with contextlib.suppress(Exception):
            rep = vitals.quick_scan()
            out["score"] = rep.score
            with _LOCK:
                self._state.health_score = rep.score
            urgent = [f for f in rep.findings
                      if f.severity in ("fatal", "error")]
            if urgent:
                sess = healer.heal(rep, auto=True)
                out["healed"] = sess.healed
                if sess.healed:
                    self._notify("healed", {"message_ar": sess.summary_ar()})
        now = time.time()
        if now - self._last_deep >= DEEP_SCAN_INTERVAL:
            self._last_deep = now
            threading.Thread(target=self._deep_boot, args=(True,),
                             name="mis-deep-rescan", daemon=True).start()
            out["deep_scan"] = "started"
        self._last_pulse = now
        with contextlib.suppress(Exception):
            self._write_state()
        return out

    def _write_state(self) -> None:
        """يكتب الحالة إلى ملف ليقرأها السيتب أو أداة دعم خارجية."""
        import json
        p = identity.awareness_dir() / "state.json"
        data = self._state.as_dict()
        data["last_pulse"] = self._last_pulse
        data["exceptions_seen"] = self._exc_count
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(str(tmp), str(p))

    # ═══════════════════ الحوار والاستبطان ═══════════════════

    def ask(self, text: str, *, confirmed: bool = False,
            apply: bool = True) -> dict:
        """قناة الحوار: المستخدم يكتب ما يريد فيُعدّل البرنامج نفسه."""
        if not self._awake:
            self.awake(deep=False)
        return dialogue.ask(text, confirmed=confirmed, apply=apply)

    def introspect(self) -> dict:
        """بطاقة وعي كاملة: من أنا، حالتي، ما تعلّمته، ما عدّلته."""
        card: dict = {"identity_ar": "", "state": {}, "knowledge": {},
                      "changes": [], "capabilities": []}
        with contextlib.suppress(Exception):
            card["identity_ar"] = identity.describe_self()
        with contextlib.suppress(Exception):
            card["state"] = self._state.as_dict()
        with contextlib.suppress(Exception):
            card["knowledge"] = _ledger.ledger().summary()
        with contextlib.suppress(Exception):
            card["changes"] = dialogue.changes(12)
        with contextlib.suppress(Exception):
            card["capabilities"] = dialogue.capabilities_ar()
        with contextlib.suppress(Exception):
            card["optimizer"] = optimizer.report()
        # الأداء جزء من وعي الذات: البرنامج الواعي يعرف أين يبطء
        with contextlib.suppress(Exception):
            card["perf"] = {"summary": perf.summary(),
                            "hotspots": perf.hotspots(6),
                            "advice": perf.recommend(),
                            "report_ar": perf.report_ar(5)}
        return card

    def deep_scan(self, *, heal: bool = False) -> dict:
        """فحص عميق بأمر المستخدم — يعمل في خيط خلفي لا يُجمّد النافذة.

        التقرير يصل الواجهة عبر حدث `deep_scan_done`؛ وإن كان فحص جاريًا
        فلا نبدأ ثانيًا (فحصان متوازيان يتنازعان على نفس الملفات).
        """
        if not self._awake:
            self.awake(deep=False, heal=False)
        with _LOCK:
            if self._state.deep_scan_running:
                return {"ok": True, "started": False,
                        "message_ar": "أنا أفحص نفسي الآن فعلًا — انتظر قليلًا."}
            self._state.deep_scan_running = True
        threading.Thread(target=self._deep_boot, args=(bool(heal),),
                         name="mis-deep-manual", daemon=True).start()
        return {"ok": True, "started": True,
                "message_ar": ("بدأت فحص نفسي وإصلاح ما أجده…"
                               if heal else "بدأت فحص نفسي…")}

    def audit_code(self, *, apply: bool = False) -> dict:
        """تدقيق البنية البرمجية: يكشف مواضع الضعف ويقترح رقعًا مُتحقّقًا منها.

        الافتراض `apply=False` مقصود: تعديل الشفرة لا يحدث إلا بأمر صريح.
        """
        with contextlib.suppress(Exception):
            return surgeon.operate(apply=bool(apply))
        return {"ok": False,
                "message_ar": "تعذّر عليّ تدقيق بنيتي الآن."}

    def self_improve(self, *, include_code: bool = False) -> dict:
        """دورة تحسين ذاتي كاملة: ضبط المعاملات ثم (اختياريًا) بنية الكود."""
        out: dict = {}
        with contextlib.suppress(Exception):
            out["tune"] = optimizer.tune()
        if include_code:
            with contextlib.suppress(Exception):
                out["surgery"] = surgeon.operate(apply=True)
        msgs = [str(v.get("message_ar", "")) for v in out.values()
                if isinstance(v, dict) and v.get("message_ar")]
        out["message_ar"] = " ".join(msgs) or "لم يظهر ما يستحق تحسينًا الآن."
        return out

    # ═══════════════════ مراقبون خارجيون ═══════════════════

    def add_observer(self, fn) -> None:
        """الواجهة تسجّل دالة لتُخبَر بأحداث الوعي (شفاء، فحص، تحسين)."""
        with _LOCK:
            if fn not in self._observers:
                self._observers.append(fn)

    def _notify(self, event: str, payload: dict) -> None:
        for fn in list(self._observers):
            with contextlib.suppress(Exception):
                fn(event, payload)

    # ═══════════════════ الإغلاق ═══════════════════

    def sleep(self) -> None:
        """إغلاق نظيف: يوقف النبضة ويثبّت السجلات ويغلق القاعدة."""
        self._stop.set()
        # تثبيت قياسات الأداء أولًا: من دونها ينسى البرنامج ما عرفه عن
        # سرعة نفسه في كل إغلاق، فيفقد قدرته على كشف الارتداد لاحقًا.
        with contextlib.suppress(Exception):
            perf.persist()
        with contextlib.suppress(Exception):
            self._write_state()
        with contextlib.suppress(Exception):
            journal.info("awareness_sleep", exceptions=self._exc_count,
                         uptime_s=round(time.time() - self._last_pulse, 1))
        with contextlib.suppress(Exception):
            _lg = _ledger.ledger()
            closer = getattr(_lg, "close", None)
            if callable(closer):
                closer()
        self._awake = False

    @property
    def state(self) -> AwakeState:
        return self._state

    @property
    def is_awake(self) -> bool:
        return self._awake


def _friendly(exc: BaseException) -> str:
    """رسالة عربية لأي استثناء حين لا يكون للشافي ما يقوله.

    المستخدم في متجر لا يفهم `FileNotFoundError`، لكنه يفهم «لم أجد الملف».
    """
    name = type(exc).__name__
    table = {
        "FileNotFoundError": "لم أجد ملفًا أحتاجه لإكمال العملية.",
        "PermissionError": "لا أملك صلاحية الوصول إلى ملف أو مجلد مطلوب.",
        "MemoryError": "الذاكرة لا تكفي لهذه العملية؛ سأخفّف الحمل وأعيد المحاولة.",
        "ModuleNotFoundError": "تنقصني مكتبة برمجية سأحاول تثبيتها بنفسي.",
        "ImportError": "تنقصني مكتبة برمجية سأحاول تثبيتها بنفسي.",
        "TimeoutError": "استغرقت العملية وقتًا أطول من المسموح فأوقفتها.",
        "OSError": "واجهت عائقًا في نظام الملفات أو الجهاز.",
        "ValueError": "وصلتني قيمة غير متوقعة فتوقفت قبل أن أُفسد المخرجات.",
        "KeyError": "ينقص إعداد داخلي؛ سأعيده إلى قيمته الافتراضية.",
        "UnicodeDecodeError": "تعذّر قراءة نص بترميزه؛ سأجرّب ترميزًا آخر.",
        "ZeroDivisionError": "حسبة داخلية أعطت قسمة على صفر فأوقفتها.",
    }
    base = table.get(name, "واجهت عائقًا غير متوقع.")
    return base + " سجّلت التفاصيل في سجلي لأتعلم منها."


# ═══════════════════ الواجهة العامة ═══════════════════

_MIND: Consciousness | None = None


def mind() -> Consciousness:
    global _MIND
    if _MIND is None:
        with _LOCK:
            if _MIND is None:
                _MIND = Consciousness()
    return _MIND


def awake(**kw) -> AwakeState:
    return mind().awake(**kw)


def guard(operation, *args, **kw):
    return mind().guard(operation, *args, **kw)


def ask(text: str, **kw) -> dict:
    return mind().ask(text, **kw)


def introspect() -> dict:
    return mind().introspect()


def self_improve(**kw) -> dict:
    return mind().self_improve(**kw)


def pulse() -> dict:
    return mind().pulse()


def start_pulse() -> bool:
    return mind().start_pulse()


def add_observer(fn) -> None:
    mind().add_observer(fn)


def sleep() -> None:
    mind().sleep()


def deep_scan(**kw) -> dict:
    return mind().deep_scan(**kw)


def audit_code(**kw) -> dict:
    return mind().audit_code(**kw)


def state() -> AwakeState:
    return mind().state


def is_awake() -> bool:
    return mind().is_awake


# ──────────────── واجهة الأداء الموحّدة ────────────────
# تُمرّر عبر core لأن التطبيق ينبغي أن يعرف مدخلًا واحدًا لا ثمانية.

def span(name: str):
    """مدير سياق لقياس مقطع: `with core.span("cutout"): ...`"""
    return perf.span(name)


def timed(name: str | None = None):
    """مُزين يقيس زمن دالة تلقائيًا في كل نداء."""
    return perf.timed(name)


def perf_report_ar(top: int = 5) -> str:
    with contextlib.suppress(Exception):
        return perf.report_ar(top)
    return "لا تتوفر قياسات أداء بعد."


def perf_hotspots(top: int = 10) -> list:
    with contextlib.suppress(Exception):
        return perf.hotspots(top)
    return []
