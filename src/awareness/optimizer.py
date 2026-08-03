# -*- coding: utf-8 -*-
"""optimizer — محرّك التحسين الذاتي: يتعلّم من تشغيله ويصبح أفضل.

الفرق بينه وبين الشافي والجرّاح
------------------------------
* ``healer``  يتصرّف عند **عطل**: شيء انكسر فأعيده للعمل.
* ``surgeon`` يتصرّف على **بنية الشفرة**: يجد أنماط ضعف ويعدّل الملفات.
* ``optimizer`` يتصرّف على **السلوك وقت التشغيل**: لا شيء مكسور، لكن الأداء
  أو الجودة أقل مما يمكن. فيغيّر إعداداته، **يقيس الأثر**، ويُبقي ما يُثبت
  تحسّنًا ويتراجع عمّا يضر.

المبدأ الحاكم: لا تحسين بلا قياس
--------------------------------
كل تحسين يمر بدورة مغلقة:

    ملاحظة (قياسات فعلية) ← فرضية (knob مقترح) ← تجربة (تطبيق مؤقت)
        ← قياس بعدي ← قرار (تثبيت / تراجع) ← تسجيل في السجل الأكاشي

هذا يجعل «الذكاء» قابلًا للإثبات: لا نقول «حسّنت» بل نقول «كان 4.8 ثانية،
أصبح 2.9 ثانية، بفارق 39% على 30 قياسًا». وإن لم يتحسّن، نتراجع ونسجّل أن
هذه الفرضية لا تنفع على هذا الجهاز — فلا نجرّبها مرة أخرى.

لماذا القياس على النِسب لا القيم المطلقة
---------------------------------------
جهاز المستخدم ليس مثل جهاز التطوير: قد يكون أبطأ بخمس مرات. فحكمنا يقوم على
**التحسّن النسبي داخل نفس الجهاز** (قبل/بعد)، لا على عتبات مطلقة يستوردها
المطوّر من بيئته. وهذا هو الفرق بين برنامج يتكيّف وبرنامج يفرض.

حماية من ضرر التجريب
--------------------
* كل knob له حدود دنيا وعليا؛ لا يخرج المحرّك عنها أبدًا.
* التجربة لا تبدأ إلا بعد ``MIN_SAMPLES`` قياسًا لخط الأساس (وإلا نقارن ضجيجًا).
* التراجع تلقائي إن ساء المقياس بأكثر من ``REGRESSION_TOLERANCE``.
* كل شيء يُسجَّل، فالمستخدم يرى ماذا غيّر البرنامج في نفسه ولماذا.
"""
from __future__ import annotations

import contextlib
import json
import math
import os
import statistics
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import identity, journal
from . import ledger as ledger_mod

__all__ = [
    "Metric",
    "Knob",
    "KNOBS",
    "Experiment",
    "Optimizer",
    "optimizer",
    "observe",
    "timed",
    "tune",
    "report",
    "current_settings",
]


# ───────────────────────── المقاييس ─────────────────────────

class Metric:
    """أسماء المقاييس التي يتعلّم منها البرنامج.

    ``LOWER_IS_BETTER`` يحدّد اتجاه التحسّن لكل مقياس — بدونه يعكس المحرّك
    الحكم فيثبّت الأسوأ ظانًّا أنه الأفضل.
    """

    BATCH_SECONDS_PER_IMAGE = "batch_seconds_per_image"
    UI_RESPONSE_MS = "ui_response_ms"
    STARTUP_SECONDS = "startup_seconds"
    PEAK_MEMORY_MB = "peak_memory_mb"
    OCR_SECONDS = "ocr_seconds"
    BARCODE_HIT_RATE = "barcode_hit_rate"
    EDGE_QUALITY = "edge_quality"
    MANUAL_FIX_RATE = "manual_fix_rate"
    FAILURE_RATE = "failure_rate"

    LOWER_IS_BETTER = {
        BATCH_SECONDS_PER_IMAGE: True,
        UI_RESPONSE_MS: True,
        STARTUP_SECONDS: True,
        PEAK_MEMORY_MB: True,
        OCR_SECONDS: True,
        BARCODE_HIT_RATE: False,      # نسبة نجاح: الأعلى أفضل
        EDGE_QUALITY: False,
        MANUAL_FIX_RATE: True,        # تدخّل المستخدم اليدوي: الأقل أفضل
        FAILURE_RATE: True,
    }

    LABELS_AR = {
        BATCH_SECONDS_PER_IMAGE: "ثانية لكل صورة في الدفعة",
        UI_RESPONSE_MS: "زمن استجابة الواجهة (مللي)",
        STARTUP_SECONDS: "زمن الإقلاع (ثانية)",
        PEAK_MEMORY_MB: "أقصى ذاكرة مستخدمة (م.ب)",
        OCR_SECONDS: "زمن قراءة النص (ثانية)",
        BARCODE_HIT_RATE: "نسبة نجاح قراءة الباركود",
        EDGE_QUALITY: "جودة كشف الحدود",
        MANUAL_FIX_RATE: "نسبة التصحيح اليدوي",
        FAILURE_RATE: "نسبة الفشل",
    }


# ───────────────────────── المفاتيح القابلة للضبط ─────────────────────────

@dataclass(frozen=True)
class Knob:
    """مفتاح ضبط: قيمة يملكها البرنامج ويجرّب تغييرها لتحسين مقياس."""

    key: str
    title_ar: str
    metric: str                 # المقياس الذي يُقاس عليه أثر هذا المفتاح
    default: object
    candidates: tuple           # القيم المسموح تجربتها (مرتّبة من المحافظ للجسور)
    rationale_ar: str = ""      # لماذا قد يُحسّن هذا المفتاح — يُعرض للمستخدم
    requires: tuple = ()        # قدرات لازمة؛ لا يُجرَّب المفتاح بدونها

    def clamp(self, value):
        """يمنع أي قيمة خارج المرشّحين — حماية من ضرر التجريب."""
        return value if value in self.candidates else self.default


def _cpu_count() -> int:
    try:
        return max(1, os.cpu_count() or 1)
    except Exception:
        return 1


def _worker_candidates() -> tuple:
    """مرشّحو عدد العمّال مشتقّون من الجهاز الفعلي لا من رقم ثابت.

    اقتراح 16 عاملًا على جهاز بنواتين يُبطئ العمل بسبب تنافس السياق؛ ولهذا
    نبني القائمة من ``os.cpu_count()``.
    """
    n = _cpu_count()
    cands = sorted({1, 2, max(1, n // 2), n, min(n * 2, 16)})
    return tuple(c for c in cands if c >= 1)


#: سجل المفاتيح. كل مفتاح مربوط بمقياس واحد صريح — فبلا ذلك لا يمكن الحكم.
KNOBS: dict[str, Knob] = {
    "batch_workers": Knob(
        key="batch_workers",
        title_ar="عدد العمّال المتوازين في الدفعة",
        metric=Metric.BATCH_SECONDS_PER_IMAGE,
        default=max(1, _cpu_count() // 2),
        candidates=_worker_candidates(),
        rationale_ar=("التوازي يسرّع الدفعة حتى حدّ معيّن، ثم يبدأ التنافس على "
                      "النوى والذاكرة فيُبطئها. العدد الأمثل يختلف من جهاز لآخر، "
                      "فأقيسه على جهازك بدل افتراضه."),
    ),
    "onnx_providers": Knob(
        key="onnx_providers",
        title_ar="مسار تنفيذ نماذج الذكاء",
        metric=Metric.BATCH_SECONDS_PER_IMAGE,
        default="cpu",
        candidates=("cpu", "dml", "cuda"),
        rationale_ar=("تشغيل النموذج على كرت الرسوم أسرع كثيرًا حين يكون مدعومًا، "
                      "لكنه يفشل أو يتباطأ على بعض الكروت. أجرّب وأقيس."),
        requires=("bg_removal",),
    ),
    "ocr_downscale": Knob(
        key="ocr_downscale",
        title_ar="تصغير الصورة قبل قراءة النص",
        metric=Metric.OCR_SECONDS,
        default=1.0,
        candidates=(1.0, 0.75, 0.5),
        rationale_ar=("قراءة النص من صورة مصغّرة أسرع بكثير؛ ما دامت الدقة لا "
                      "تنخفض، فالتصغير مكسب صافٍ. أراقب الدقة مع السرعة."),
        requires=("ocr",),
    ),
    "barcode_engines": Knob(
        key="barcode_engines",
        title_ar="ترتيب محرّكات قراءة الباركود",
        metric=Metric.BARCODE_HIT_RATE,
        default="auto",
        candidates=("auto", "zxing_first", "pyzbar_first", "opencv_first"),
        rationale_ar=("لكل محرّك باركود نقاط قوة تختلف بحسب نوع الطباعة "
                      "والإضاءة في صورك. أرتّبها بحسب ما ينجح فعلًا معك."),
        requires=("barcode",),
    ),
    "preview_scale": Knob(
        key="preview_scale",
        title_ar="دقة المعاينة في الواجهة",
        metric=Metric.UI_RESPONSE_MS,
        default=1.0,
        candidates=(1.0, 0.75, 0.5),
        rationale_ar=("معاينة بدقة كاملة تُثقل الواجهة على الأجهزة المتوسطة. "
                      "تصغيرها يجعل التنقّل فوريًا دون أثر على الملف النهائي."),
    ),
    "cache_decoded": Knob(
        key="cache_decoded",
        title_ar="الاحتفاظ بالصور المفكوكة في الذاكرة",
        metric=Metric.BATCH_SECONDS_PER_IMAGE,
        default=True,
        candidates=(True, False),
        rationale_ar=("التخزين المؤقت يوفّر إعادة فك الصور، لكنه يستهلك ذاكرة؛ "
                      "على جهاز محدود الذاكرة قد يكون تعطيله أسرع."),
    ),
    "edge_refine_passes": Knob(
        key="edge_refine_passes",
        title_ar="عدد مرّات تنقيح الحدود",
        metric=Metric.EDGE_QUALITY,
        default=1,
        candidates=(1, 2, 3),
        rationale_ar=("كل مرّة تنقيح تُحسّن الحدود قليلًا وتزيد الزمن. أوازن "
                      "بين الجودة والسرعة بحسب ما تعمل عليه فعلًا."),
    ),
}

MIN_SAMPLES = 8                  # أقل عدد قياسات يُبنى عليه حكم
REGRESSION_TOLERANCE = 0.05      # تدهور > 5% ⇒ تراجع فوري
MIN_IMPROVEMENT = 0.08           # تحسّن < 8% لا يستحق تثبيت تغيير
MAX_HISTORY = 400                # قياسات محفوظة لكل مقياس
RECENT_WINDOW = 25               # نافذة الحكم الراهن: ماضٍ بعيد لا يدين الحال الآن


# ───────────────────────── التجربة ─────────────────────────

@dataclass
class Experiment:
    """تجربة جارية على مفتاح واحد."""

    knob: str
    baseline_value: object
    trial_value: object
    metric: str
    baseline_stats: dict
    started: float = field(default_factory=time.time)
    samples: list[float] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "knob": self.knob, "metric": self.metric,
            "baseline_value": self.baseline_value,
            "trial_value": self.trial_value,
            "baseline_median": self.baseline_stats.get("median"),
            "samples": len(self.samples), "started": self.started,
        }


# ───────────────────────── المحرّك ─────────────────────────

class Optimizer:
    """يراقب المقاييس، يقترح تحسينات، يجرّبها، ويثبّت ما ينفع فقط."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._dir = identity.awareness_dir() / "optimizer"
        with contextlib.suppress(Exception):
            self._dir.mkdir(parents=True, exist_ok=True)
        self._state_path = self._dir / "state.json"
        self._samples: dict[str, list[dict]] = {}
        self._settings: dict[str, object] = {}
        self._experiment: Experiment | None = None
        self._rejected: dict[str, list] = {}     # knob -> قيم ثبت ضررها
        self._last_change_at: float = 0.0        # لحظة آخر تعديل ذاتي على الإعدادات
        self._load()

    # ── الحالة الدائمة ──

    def _load(self) -> None:
        try:
            if self._state_path.exists():
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
                self._samples = data.get("samples", {}) or {}
                self._settings = data.get("settings", {}) or {}
                self._rejected = data.get("rejected", {}) or {}
                self._last_change_at = float(data.get("last_change_at", 0) or 0)
                exp = data.get("experiment")
                if exp:
                    self._experiment = Experiment(
                        knob=exp["knob"], metric=exp["metric"],
                        baseline_value=exp["baseline_value"],
                        trial_value=exp["trial_value"],
                        baseline_stats=exp.get("baseline_stats", {}),
                        started=exp.get("started", time.time()),
                        samples=exp.get("samples", []),
                    )
        except Exception as exc:
            journal.warn("optimizer_state_load_failed", error=str(exc)[:200])
            self._samples, self._settings, self._rejected = {}, {}, {}
            self._last_change_at = 0.0

    def _save(self) -> None:
        try:
            data = {
                "samples": {k: v[-MAX_HISTORY:] for k, v in self._samples.items()},
                "settings": self._settings,
                "rejected": self._rejected,
                "last_change_at": self._last_change_at,
                "experiment": (
                    {**self._experiment.as_dict(),
                     "baseline_stats": self._experiment.baseline_stats,
                     "samples": self._experiment.samples}
                    if self._experiment else None
                ),
                "saved": time.time(),
            }
            tmp = self._state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            os.replace(tmp, self._state_path)
        except Exception as exc:
            journal.warn("optimizer_state_save_failed", error=str(exc)[:200])

    # ── الإعدادات الحالية ──

    def setting(self, key: str, default=None):
        """القيمة الفعّالة لمفتاح — يستدعيها المحرّك وقت التشغيل."""
        knob = KNOBS.get(key)
        with self._lock:
            if self._experiment and self._experiment.knob == key:
                return self._experiment.trial_value      # تجربة جارية
            if key in self._settings:
                val = self._settings[key]
                return knob.clamp(val) if knob else val
        if knob:
            return knob.default
        return default

    def current_settings(self) -> dict:
        out = {}
        for k, kn in KNOBS.items():
            out[k] = {
                "title_ar": kn.title_ar,
                "value": self.setting(k),
                "default": kn.default,
                "tuned": k in self._settings,
                "under_test": bool(self._experiment and
                                   self._experiment.knob == k),
            }
        return out

    # ── الملاحظة ──

    def observe(self, metric: str, value: float, **context) -> None:
        """يسجّل قياسًا واحدًا. آمن الفشل تمامًا: لا يعطّل عمل المستخدم أبدًا."""
        try:
            v = float(value)
            if not math.isfinite(v):
                return
        except Exception:
            return
        rec = {"v": v, "t": time.time()}
        if context:
            rec["c"] = {k: str(val)[:60] for k, val in list(context.items())[:5]}
        with self._lock:
            self._samples.setdefault(metric, []).append(rec)
            if len(self._samples[metric]) > MAX_HISTORY:
                self._samples[metric] = self._samples[metric][-MAX_HISTORY:]
            exp = self._experiment
            if exp and exp.metric == metric:
                exp.samples.append(v)
                enough = len(exp.samples) >= MIN_SAMPLES
            else:
                enough = False
        if enough:
            self._evaluate_experiment()
        with contextlib.suppress(Exception):
            if len(self._samples.get(metric, [])) % 10 == 0:
                self._save()

    @contextlib.contextmanager
    def timed(self, metric: str, *, divisor: float = 1.0, **context):
        """مِقياس زمني جاهز: ``with optimizer().timed(Metric.X): ...``"""
        t0 = time.perf_counter()
        try:
            yield
        finally:
            with contextlib.suppress(Exception):
                dt = time.perf_counter() - t0
                d = float(divisor) if divisor else 1.0
                self.observe(metric, dt / max(d, 1e-9), **context)

    # ── الإحصاء ──

    def stats(self, metric: str, *, last: int | None = None,
              since: float | None = None) -> dict:
        """وسيط ومدى القياسات. الوسيط لا المتوسط: قياسة شاذّة لا تُضلّلنا.

        ``since`` يقصر الحساب على ما بعد لحظة معيّنة — ضروري لأن الحكم على
        الحال الراهن لا يجوز أن تلوّثه قياسات ما قبل الإصلاح.
        """
        with self._lock:
            recs = list(self._samples.get(metric, []))
        if since:
            recs = [r for r in recs if r.get("t", 0) >= since]
        vals = [r["v"] for r in recs]
        if last:
            vals = vals[-last:]
        if not vals:
            return {"n": 0}
        try:
            med = statistics.median(vals)
            spread = (statistics.stdev(vals) if len(vals) > 1 else 0.0)
        except Exception:
            med, spread = vals[-1], 0.0
        return {"n": len(vals), "median": round(med, 4),
                "min": round(min(vals), 4), "max": round(max(vals), 4),
                "stdev": round(spread, 4)}

    # ── الفرضية ──

    def _disabled_capabilities(self) -> dict:
        """القدرات المعطّلة حاليًا — نتجنّب تجربة مفاتيح تعتمد عليها.

        نقرأ من الفحص المُكيَّش في ``vitals`` بدل فحص جديد: التحسين لا يجوز
        أن يكون هو نفسه عبئًا على الأداء الذي يحاول تحسينه.
        """
        try:
            from . import vitals
            return dict(vitals.full_scan(use_cache=True,
                                         deep_imports=False).disabled_capabilities)
        except Exception:
            return {}

    def _eligible_knobs(self) -> list[Knob]:
        """المفاتيح الجاهزة للتجربة: لها بيانات كافية، وقدراتها متاحة."""
        out: list[Knob] = []
        disabled = None
        for kn in KNOBS.values():
            st = self.stats(kn.metric)
            if st.get("n", 0) < MIN_SAMPLES:
                continue                       # لا نقارن ضجيجًا
            if kn.requires:
                if disabled is None:
                    disabled = self._disabled_capabilities()
                if any(c in disabled for c in kn.requires):
                    continue                   # قدرة غير متاحة: لا معنى للتجربة
            remaining = [c for c in kn.candidates
                         if c != self.setting(kn.key)
                         and c not in self._rejected.get(kn.key, [])]
            if remaining:
                out.append(kn)
        return out

    def _next_candidate(self, knob: Knob):
        """يختار القيمة التالية: الأقرب للحالي أولًا (تغيير تدريجي أكثر أمانًا)."""
        cur = self.setting(knob.key)
        rejected = set(map(str, self._rejected.get(knob.key, [])))
        cands = [c for c in knob.candidates
                 if c != cur and str(c) not in rejected]
        if not cands:
            return None
        if all(isinstance(c, (int, float)) and not isinstance(c, bool)
               for c in cands) and isinstance(cur, (int, float)):
            cands.sort(key=lambda c: abs(float(c) - float(cur)))
        return cands[0]

    # ── التجربة ──

    def start_experiment(self, knob_key: str | None = None) -> dict:
        """يبدأ تجربة على مفتاح واحد فقط (تجربتان معًا تُفسدان القياس)."""
        with self._lock:
            if self._experiment:
                return {"ok": False, "message_ar":
                        f"تجربة جارية بالفعل على «{self._experiment.knob}»."}
        cands = self._eligible_knobs()
        knob = None
        if knob_key:
            knob = KNOBS.get(knob_key)
            if knob is None:
                return {"ok": False,
                        "message_ar": f"لا أعرف مفتاحًا اسمه «{knob_key}»."}
        elif cands:
            # نبدأ بالمقياس الأكثر تشتّتًا: فيه أكبر فرصة مكسب
            knob = max(cands, key=lambda k: (self.stats(k.metric).get("stdev", 0)))
        if knob is None:
            return {"ok": False, "message_ar":
                    ("لا أملك قياسات كافية بعد لأجرّب تحسينًا موثوقًا. "
                     f"أحتاج {MIN_SAMPLES} قياسات على الأقل لكل مقياس.")}

        trial = self._next_candidate(knob)
        if trial is None:
            return {"ok": False, "message_ar":
                    f"جرّبت كل القيم الممكنة لـ«{knob.title_ar}»."}
        base = self.stats(knob.metric, last=40)
        previous = self.setting(knob.key)   # يُقرأ قبل تسجيل التجربة، وإلا أعاد قيمتها
        with self._lock:
            self._experiment = Experiment(
                knob=knob.key, baseline_value=previous,
                trial_value=trial, metric=knob.metric, baseline_stats=base)
            self._save()
        journal.info("experiment_started", knob=knob.key, trial=str(trial),
                     metric=knob.metric, baseline=base.get("median"))
        return {
            "ok": True, "knob": knob.key, "trial_value": trial,
            "previous_value": previous,
            "message_ar": (
                f"بدأت تجربة على «{knob.title_ar}»: أغيرها من "
                f"{previous} إلى {trial} وأقيس أثرها على "
                f"{Metric.LABELS_AR.get(knob.metric, knob.metric)}. "
                f"{knob.rationale_ar}"),
        }

    def _evaluate_experiment(self) -> dict:
        """يحكم على التجربة بمقارنة الوسيط قبل/بعد، ثم يثبّت أو يتراجع."""
        with self._lock:
            exp = self._experiment
            if exp is None or len(exp.samples) < MIN_SAMPLES:
                return {"ok": False, "message_ar": "لا تجربة جاهزة للحكم."}
            trial_vals = list(exp.samples)
            self._experiment = None

        knob = KNOBS.get(exp.knob)
        base_med = float(exp.baseline_stats.get("median") or 0.0)
        try:
            trial_med = statistics.median(trial_vals)
        except Exception:
            trial_med = trial_vals[-1]

        lower_better = Metric.LOWER_IS_BETTER.get(exp.metric, True)
        if base_med <= 0:
            delta = 0.0
        elif lower_better:
            delta = (base_med - trial_med) / base_med       # + = تحسّن
        else:
            delta = (trial_med - base_med) / max(base_med, 1e-9)

        label = Metric.LABELS_AR.get(exp.metric, exp.metric)
        pct = round(delta * 100, 1)

        if delta >= MIN_IMPROVEMENT:
            with self._lock:
                self._settings[exp.knob] = exp.trial_value
                self._last_change_at = time.time()
                self._save()
            msg = (f"ثبّتت تحسينًا: غيّرت «{knob.title_ar if knob else exp.knob}» "
                   f"إلى {exp.trial_value} فتحسّن {label} بنسبة {abs(pct)}% "
                   f"({round(base_med, 3)} ← {round(trial_med, 3)}) "
                   f"على {len(trial_vals)} قياسًا.")
            journal.info("experiment_adopted", knob=exp.knob,
                         value=str(exp.trial_value), gain_pct=pct)
            ledger_mod.add_insight(
                "optimization",
                f"{exp.knob}={exp.trial_value} حسّن {exp.metric} بـ{pct}%",
                confidence=min(0.95, 0.5 + abs(delta)))
            ok, adopted = True, True
        elif delta <= -REGRESSION_TOLERANCE:
            with self._lock:
                self._rejected.setdefault(exp.knob, [])
                if exp.trial_value not in self._rejected[exp.knob]:
                    self._rejected[exp.knob].append(exp.trial_value)
                self._save()
            msg = (f"تراجعت: القيمة {exp.trial_value} لـ"
                   f"«{knob.title_ar if knob else exp.knob}» أسوأت {label} بنسبة "
                   f"{abs(pct)}%، فأعدت الإعداد كما كان ولن أجرّبها مرة أخرى "
                   "على هذا الجهاز.")
            journal.warn("experiment_rejected", knob=exp.knob,
                         value=str(exp.trial_value), loss_pct=pct)
            ledger_mod.add_insight(
                "optimization",
                f"{exp.knob}={exp.trial_value} أسوأ {exp.metric} بـ{abs(pct)}%",
                confidence=min(0.9, 0.5 + abs(delta)))
            ok, adopted = True, False
        else:
            with self._lock:
                self._rejected.setdefault(exp.knob, [])
                if exp.trial_value not in self._rejected[exp.knob]:
                    self._rejected[exp.knob].append(exp.trial_value)
                self._save()
            msg = (f"لا فرق يُعتد به: {exp.trial_value} غيّرت {label} بـ{pct}% "
                   "فقط، وهذا داخل حدود الضجيج. أبقيت الإعداد الأبسط.")
            journal.info("experiment_neutral", knob=exp.knob, delta_pct=pct)
            ok, adopted = True, False

        return {"ok": ok, "adopted": adopted, "knob": exp.knob,
                "delta_pct": pct, "baseline": round(base_med, 4),
                "trial": round(trial_med, 4), "samples": len(trial_vals),
                "message_ar": msg}

    def abort_experiment(self, reason: str = "") -> dict:
        """يوقف التجربة الجارية فورًا ويعيد الإعداد الأصلي (للأعطال)."""
        with self._lock:
            exp = self._experiment
            self._experiment = None
            self._save()
        if exp is None:
            return {"ok": True, "message_ar": "لا تجربة جارية."}
        journal.warn("experiment_aborted", knob=exp.knob, reason=reason[:200])
        return {"ok": True, "message_ar":
                (f"أوقفت تجربة «{exp.knob}» وأعدت الإعداد الأصلي"
                 + (f" بسبب: {reason}" if reason else "") + ".")}

    # ── التوصيات بلا تجريب ──

    def recommendations(self) -> list[dict]:
        """استنتاجات مباشرة من القياسات، تُعرض للمستخدم كنصائح مفهومة.

        بعض الحقائق لا تحتاج تجربة: إن كان زمن الإقلاع 12 ثانية فالمشكلة
        واضحة. هذه الطبقة تحوّل الأرقام إلى كلام يفهمه غير التقني.
        """
        out: list[dict] = []
        W = RECENT_WINDOW
        # لا نحاسب البرنامج على قياسات سابقة لآخر تعديل أجراه على نفسه:
        # مشكلة حُلَّت فعلًا لا يجوز أن تظل معروضة لأن التاريخ يذكرها.
        since = self._last_change_at or None

        st = self.stats(Metric.BATCH_SECONDS_PER_IMAGE, last=W, since=since)
        if st.get("n", 0) >= 5 and st.get("median", 0) > 3.0:
            out.append({
                "severity": "medium",
                "title_ar": "معالجة الصور أبطأ من المتوقّع",
                "detail_ar": (f"الوسيط {st['median']} ثانية لكل صورة. سأجرّب "
                              "زيادة التوازي وتقليل التخزين المؤقت وأقيس الأثر."),
                "action": "start_experiment:batch_workers",
            })

        st = self.stats(Metric.UI_RESPONSE_MS, last=W, since=since)
        if st.get("n", 0) >= 5 and st.get("median", 0) > 400:
            out.append({
                "severity": "medium",
                "title_ar": "الواجهة تتأخّر في الاستجابة",
                "detail_ar": (f"زمن الاستجابة الوسيط {int(st['median'])} مللي. "
                              "تقليل دقة المعاينة يجعل التنقّل فوريًا دون أي "
                              "أثر على الملفات النهائية."),
                "action": "start_experiment:preview_scale",
            })

        st = self.stats(Metric.FAILURE_RATE, last=W, since=since)
        if st.get("n", 0) >= 5 and st.get("median", 0) > 0.1:
            out.append({
                "severity": "high",
                "title_ar": "نسبة الفشل مرتفعة",
                "detail_ar": (f"يفشل نحو {int(st['median'] * 100)}% من العمليات. "
                              "هذا ليس مسألة أداء بل خلل يستحق تشخيصًا كاملًا."),
                "action": "full_scan",
            })

        st = self.stats(Metric.MANUAL_FIX_RATE, last=W, since=since)
        if st.get("n", 0) >= 5 and st.get("median", 0) > 0.3:
            out.append({
                "severity": "medium",
                "title_ar": "تصحّح النتائج يدويًا أكثر من اللازم",
                "detail_ar": (f"تعدّل نحو {int(st['median'] * 100)}% من النتائج "
                              "بنفسك. سأزيد دقّة تنقيح الحدود وأتعلّم من "
                              "تصحيحاتك لتقلّ الحاجة لذلك."),
                "action": "start_experiment:edge_refine_passes",
            })

        st = self.stats(Metric.BARCODE_HIT_RATE, last=W, since=since)
        if st.get("n", 0) >= 5 and st.get("median", 1) < 0.7:
            out.append({
                "severity": "medium",
                "title_ar": "قراءة الباركود تفشل كثيرًا",
                "detail_ar": (f"نسبة النجاح {int(st['median'] * 100)}%. سأعيد "
                              "ترتيب محرّكات القراءة بحسب ما ينجح مع صورك."),
                "action": "start_experiment:barcode_engines",
            })

        st = self.stats(Metric.STARTUP_SECONDS, last=W, since=since)
        if st.get("n", 0) >= 3 and st.get("median", 0) > 8:
            out.append({
                "severity": "low",
                "title_ar": "الإقلاع بطيء",
                "detail_ar": (f"يستغرق {round(st['median'], 1)} ثانية. سأؤجّل "
                              "تحميل ما لا يُستخدم في أول شاشة."),
                "action": "defer_heavy_imports",
            })
        return out

    # ── الدورة الكاملة ──

    def tune(self, *, auto: bool = True) -> dict:
        """دورة واحدة: احكم على التجربة الجارية، أو ابدأ واحدة جديدة."""
        with self._lock:
            exp = self._experiment
            ready = bool(exp and len(exp.samples) >= MIN_SAMPLES)
        if ready:
            return self._evaluate_experiment()
        if exp is not None:
            need = MIN_SAMPLES - len(exp.samples)
            return {"ok": True, "pending": True, "message_ar":
                    (f"تجربة «{exp.knob}» جارية؛ أحتاج {need} قياسًا إضافيًا "
                     "قبل أن أحكم عليها بثقة.")}
        if not auto:
            return {"ok": True, "message_ar": "لا تجربة جارية."}
        return self.start_experiment()

    def report(self) -> dict:
        """تقرير كامل يُعرض في تبويب الوعي: قياسات، إعدادات، تجربة، توصيات."""
        metrics = {}
        for m in list(Metric.LOWER_IS_BETTER):
            st = self.stats(m)
            if st.get("n", 0):
                metrics[m] = {**st, "label_ar": Metric.LABELS_AR.get(m, m),
                              "lower_is_better":
                                  Metric.LOWER_IS_BETTER.get(m, True)}
        with self._lock:
            exp = self._experiment.as_dict() if self._experiment else None
            tuned = dict(self._settings)
            rejected = {k: list(v) for k, v in self._rejected.items()}
        return {
            "metrics": metrics, "settings": self.current_settings(),
            "tuned": tuned, "rejected": rejected, "experiment": exp,
            "recommendations": self.recommendations(),
            "summary_ar": self._summary_ar(metrics, tuned, exp),
        }

    def _summary_ar(self, metrics: dict, tuned: dict, exp: dict | None) -> str:
        parts: list[str] = []
        if not metrics:
            parts.append("لم أجمع قياسات بعد؛ سأتعلّم من أول استخدام فعلي.")
        else:
            parts.append(f"أراقب {len(metrics)} مقياسًا من تشغيلك الفعلي.")
        if tuned:
            names = [KNOBS[k].title_ar for k in tuned if k in KNOBS]
            parts.append("ضبطت بنفسي: " + "، ".join(names[:4]) + ".")
        else:
            parts.append("لم أغيّر أي إعداد بعد؛ أنتظر بيانات كافية لأقرّر بثقة.")
        if exp:
            parts.append(f"تجربة جارية على «{exp['knob']}» "
                         f"({exp['samples']}/{MIN_SAMPLES} قياسات).")
        return " ".join(parts)


# ───────────────────────── الواجهة المفردة ─────────────────────────

_OPT: Optimizer | None = None
_O_LOCK = threading.Lock()


def optimizer() -> Optimizer:
    global _OPT
    with _O_LOCK:
        if _OPT is None:
            _OPT = Optimizer()
        return _OPT


def observe(metric: str, value: float, **context) -> None:
    with contextlib.suppress(Exception):
        optimizer().observe(metric, value, **context)


def timed(metric: str, *, divisor: float = 1.0, **context):
    return optimizer().timed(metric, divisor=divisor, **context)


def setting(key: str, default=None):
    try:
        return optimizer().setting(key, default)
    except Exception:
        kn = KNOBS.get(key)
        return kn.default if kn else default


def tune(**kw) -> dict:
    try:
        return optimizer().tune(**kw)
    except Exception as exc:
        return {"ok": False, "message_ar": f"تعذّر التحسين: {str(exc)[:160]}"}


def report() -> dict:
    try:
        return optimizer().report()
    except Exception as exc:
        return {"metrics": {}, "summary_ar": f"تعذّر التقرير: {str(exc)[:160]}"}


def current_settings() -> dict:
    try:
        return optimizer().current_settings()
    except Exception:
        return {}
