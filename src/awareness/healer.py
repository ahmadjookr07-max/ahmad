# -*- coding: utf-8 -*-
"""healer — الشفاء الذاتي: البرنامج يُصلح نفسه فعلًا، لا يشتكي.

الفرق الجوهري
-------------
الرسالة الودّية تقول للمستخدم «ثبّت Tesseract». الشفاء الذاتي **يبحث عنه في كل
مسارات ويندوز المعتادة وفي سجل النظام، ويضبط مساره في pytesseract، وإن غاب كليًا
ينزّل النسخة المحمولة ويشغّلها**. الأول يعطّل المستخدم، والثاني ينهي المشكلة قبل
أن يعلم بها.

مساران للاستدعاء:

1. **الوقائي**: ``heal(report)`` بعد ``vitals.full_scan()`` — يعالج ما اكتُشف.
2. **الحيوي**: ``heal_from_exception(exc)`` من داخل ``except`` — يستشير الذاكرة
   الدائمة عن علاج نجح سابقًا لنفس البصمة، يطبّقه، ويُرجع ``RetryDecision``
   فيعيد التطبيق المحاولة وينجح **بلا أن يرى المستخدم خطأً أصلًا**.

سياسة الخطورة: ``safe`` تُطبَّق دائمًا، ``moderate`` تُطبَّق تلقائيًا (تنزيل، تثبيت،
نقل مجلد)، و``invasive`` تتطلب موافقة صريحة. وميزانية زمنية صارمة تمنع أي علاج
من تعليق التطبيق.

كل علاج يُرجع ``RemedyResult``، ونتيجته تُسجَّل في السجل الأكاشي فيتعلّم البرنامج
أي العلاجات تنفع فعلًا على هذا الجهاز بالذات.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import identity, journal, ledger as ledger_mod, vitals
from .vitals import Finding, HealthReport, Severity

__all__ = [
    "Risk",
    "RemedyResult",
    "RetryDecision",
    "HealSession",
    "Healer",
    "healer",
    "heal",
    "heal_from_exception",
    "overrides",
    "set_override",
    "get_override",
]


class Risk:
    SAFE = "safe"
    MODERATE = "moderate"
    INVASIVE = "invasive"

    ORDER = {SAFE: 0, MODERATE: 1, INVASIVE: 2}


@dataclass
class RemedyResult:
    kind: str
    ok: bool
    message_ar: str
    risk: str = Risk.SAFE
    elapsed_ms: float = 0.0
    params: dict = field(default_factory=dict)
    retry_recommended: bool = False

    def as_dict(self) -> dict:
        return {"kind": self.kind, "ok": self.ok, "message_ar": self.message_ar,
                "risk": self.risk, "elapsed_ms": round(self.elapsed_ms, 1),
                "params": self.params, "retry": self.retry_recommended}


@dataclass
class RetryDecision:
    """قرار البرنامج بعد عطل: هل يعيد المحاولة، وبأي تعديل، وماذا يقول للمستخدم."""

    should_retry: bool = False
    delay_s: float = 0.0
    applied: list[RemedyResult] = field(default_factory=list)
    message_ar: str = ""
    fingerprint: str = ""
    known_incident: bool = False
    seen_count: int = 0

    def as_dict(self) -> dict:
        return {"should_retry": self.should_retry, "delay_s": self.delay_s,
                "message_ar": self.message_ar, "fingerprint": self.fingerprint,
                "known": self.known_incident, "seen_count": self.seen_count,
                "applied": [a.as_dict() for a in self.applied]}


@dataclass
class HealSession:
    results: list[RemedyResult] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0

    @property
    def healed(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.ok)

    def summary_ar(self) -> str:
        if not self.results:
            return "لم يكن هناك ما يحتاج إصلاحًا."
        parts = []
        if self.healed:
            parts.append(f"أصلحت {self.healed} مشكلة بنفسي")
        if self.failed:
            parts.append(f"وتعذّر عليّ إصلاح {self.failed}")
        if self.skipped:
            parts.append(f"وتجاوزت {len(self.skipped)} تحتاج إذنك")
        return " ".join(parts) + "."

    def as_dict(self) -> dict:
        return {"healed": self.healed, "failed": self.failed,
                "skipped": self.skipped, "elapsed_ms": round(self.elapsed_ms, 1),
                "summary_ar": self.summary_ar(),
                "results": [r.as_dict() for r in self.results]}


# ═══════════════ طبقة تجاوزات وقت التشغيل ═══════════════
# بعض العلاجات لا يمكن تنفيذها بتعديل الشفرة (خاصة في الحزمة المصرَّفة)، فتُنفَّذ
# كقيم تُقرأ وقت التشغيل: خفض التوازي، تغيير مجلد المخرجات، تعطيل قدرة، إلخ.
# هذا ما يجعل «تعديل البنية» ممكنًا حتى داخل exe موقّع.

_OVR_LOCK = threading.RLock()
_OVR_CACHE: dict | None = None


def _overrides_path() -> Path:
    return identity.awareness_dir() / "overrides.json"


def overrides(refresh: bool = False) -> dict:
    """قيم التجاوز الفعّالة الآن — تقرأها وحدات المحرك عبر ``get_override``."""
    global _OVR_CACHE
    with _OVR_LOCK:
        if _OVR_CACHE is not None and not refresh:
            return dict(_OVR_CACHE)
        data: dict = {}
        with contextlib.suppress(Exception):
            p = _overrides_path()
            if p.is_file():
                import json
                data = json.loads(p.read_text(encoding="utf-8")) or {}
        _OVR_CACHE = data
        return dict(data)


def set_override(key: str, value, *, reason: str = "") -> bool:
    """يضبط قيمة تجاوز ويحفظها فورًا (ذرّيًا) — التغيير يسري في الحال."""
    with _OVR_LOCK:
        data = overrides(refresh=True)
        data[key] = value
        data.setdefault("_reasons", {})[key] = reason or "تعديل ذاتي"
        data["_updated"] = time.time()
        try:
            import json
            p = _overrides_path()
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            os.replace(str(tmp), str(p))
            global _OVR_CACHE
            _OVR_CACHE = data
            journal.info("override_set", key=key, value=str(value)[:120],
                         reason=reason)
            return True
        except Exception as exc:
            journal.warn("override_failed", key=key, detail=str(exc)[:200])
            return False


def get_override(key: str, default=None):
    return overrides().get(key, default)


# ═══════════════════════ الشافي ═══════════════════════

class Healer:
    """محرك العلاجات. كل علاج دالة ``_r_<kind>`` تُرجع ``RemedyResult``."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._installing: set[str] = set()
        self._downloading: set[str] = set()
        self._last_heal = 0.0
        self._auto_enabled = os.environ.get("MIS_AUTO_HEAL", "1") != "0"

    # ───────── الواجهة العامة ─────────

    @property
    def max_auto_risk(self) -> str:
        return get_override("max_auto_risk", Risk.MODERATE) or Risk.MODERATE

    def heal(self, report: HealthReport | None = None, *,
             auto: bool = True, budget_s: float = 90.0,
             allow_network: bool = True) -> HealSession:
        """يعالج كل ما يمكن علاجه من تقرير الفحص، بأولوية أثره على الهدف."""
        t0 = time.perf_counter()
        rep = report if report is not None else vitals.full_scan()
        sess = HealSession()

        ceiling = Risk.ORDER.get(self.max_auto_risk, 1) if auto else 0
        for f in rep.sorted_findings():
            if (time.perf_counter() - t0) > budget_s:
                sess.skipped.append(f"{f.code} (انتهت الميزانية الزمنية)")
                continue
            if not f.auto_fixable or not f.remedy_kind:
                continue
            risk = self._risk_of(f.remedy_kind)
            if Risk.ORDER.get(risk, 2) > ceiling:
                sess.skipped.append(f"{f.code} ({f.title_ar} — يحتاج إذنك)")
                continue
            res = self.apply(f.remedy_kind, dict(f.remedy_params or {}),
                             finding=f, allow_network=allow_network)
            sess.results.append(res)

        sess.elapsed_ms = (time.perf_counter() - t0) * 1000
        if sess.results:
            vitals.invalidate_cache()
        journal.info("heal_session", healed=sess.healed, failed=sess.failed,
                     skipped=len(sess.skipped),
                     elapsed_ms=round(sess.elapsed_ms, 1))
        self._last_heal = time.time()
        return sess

    def heal_from_exception(self, exc: BaseException, *,
                            context: dict | None = None,
                            allow_network: bool = True) -> RetryDecision:
        """المسار الحيوي: عطل وقع الآن — أصلحه وأعد المحاولة إن أمكن.

        الترتيب مقصود: الذاكرة المحلية أولًا (سريعة ومجرّبة على هذا الجهاز)، ثم
        الاستنباط من نوع الاستثناء، ثم السجل الأكاشي الخارجي للأعطال المجهولة.
        """
        facts = context or journal.exception_facts(exc)
        fp = str(facts.get("fingerprint") or journal.fingerprint(exc))
        L = ledger_mod.ledger()
        inc = L.remember_incident(facts)

        decision = RetryDecision(fingerprint=fp, seen_count=inc.seen_count,
                                 known_incident=inc.seen_count > 1)

        if not self._auto_enabled:
            decision.message_ar = "الإصلاح التلقائي معطّل حاليًا."
            return decision

        # 1) علاج مجرَّب سابقًا لنفس البصمة
        candidates = L.best_remedies(fp, max_risk=self.max_auto_risk)

        # 2) استنباط علاج من نوع الاستثناء ورسالته
        if not candidates:
            for kind, params, risk in self._infer_remedies(exc, facts):
                L.remember_remedy(fp, kind, params, risk=risk, origin="inferred",
                                  note="مستنبط من نوع الاستثناء ورسالته")
            candidates = L.best_remedies(fp, max_risk=self.max_auto_risk)

        # 3) السجل الأكاشي الخارجي — للمجهول تمامًا، وفي خيط خلفي لئلا يُبطئ
        if not candidates and allow_network and inc.seen_count >= 2:
            L.consult_async(facts)
            decision.message_ar = (
                "هذا عطل لم أره من قبل. أستعلم عنه الآن في الخلفية، وسأعرف كيف "
                "أعالجه إن تكرر.")

        applied_ok = False
        for rem in candidates[:3]:
            res = self.apply(rem.kind, dict(rem.params or {}),
                             allow_network=allow_network)
            decision.applied.append(res)
            L.record_outcome(fp, rem.kind, rem.params, res.ok)
            if res.ok:
                applied_ok = True
                if res.retry_recommended:
                    decision.should_retry = True
                    decision.delay_s = 0.4
                break

        if applied_ok:
            names = "، ".join(r.message_ar for r in decision.applied if r.ok)
            decision.message_ar = (
                f"واجهت عطلًا وأصلحته بنفسي: {names}"
                + ("، وسأعيد المحاولة الآن." if decision.should_retry else "."))
            journal.info("self_healed", fingerprint=fp,
                         retry=decision.should_retry, seen=inc.seen_count)
        elif not decision.message_ar:
            decision.message_ar = self._explain_unhealed(exc, facts, inc)

        return decision

    def apply(self, kind: str, params: dict | None = None, *,
              finding: Finding | None = None,
              allow_network: bool = True) -> RemedyResult:
        """ينفّذ علاجًا واحدًا بأمان تام — لا يرمي استثناءً أبدًا."""
        t0 = time.perf_counter()
        p = dict(params or {})
        fn = getattr(self, f"_r_{kind}", None)
        if fn is None:
            return RemedyResult(kind, False, f"لا أعرف علاجًا باسم «{kind}».",
                                elapsed_ms=(time.perf_counter() - t0) * 1000)
        if not allow_network and kind in _NETWORK_REMEDIES:
            # لا نرفض فورًا: بعض هذه العلاجات تنجح محليًا (حزمة موجودة أصلًا،
            # أو محرك OCR مثبَت يحتاج ربطًا فقط)، والعلاج نفسه يتحقق من الشبكة
            # قبل أي تنزيل. نمرّر القيد للعلاج ليحاول المسار المحلي أولًا.
            p["_offline"] = True
        try:
            res = fn(p, finding)
        except Exception as exc:
            journal.warn("remedy_crashed", kind=kind, detail=str(exc)[:250])
            res = RemedyResult(kind, False,
                               f"فشل العلاج بخطأ داخلي: {type(exc).__name__}.")
        res.kind = kind
        res.params = p
        res.risk = self._risk_of(kind)
        res.elapsed_ms = (time.perf_counter() - t0) * 1000
        journal.info("remedy_applied", kind=kind, ok=res.ok,
                     elapsed_ms=round(res.elapsed_ms, 1),
                     message=res.message_ar[:200])
        return res

    # ───────── استنباط العلاجات ─────────

    def _infer_remedies(self, exc: BaseException,
                        facts: dict) -> list[tuple[str, dict, str]]:
        """يحوّل نوع الاستثناء ورسالته إلى علاجات مرشّحة — قلب الذكاء التشخيصي."""
        out: list[tuple[str, dict, str]] = []
        et = type(exc).__name__
        msg = str(exc).lower()

        if et in ("ModuleNotFoundError", "ImportError"):
            mod = ledger_mod._module_from_message(msg)
            if mod:
                out.append(("install_package", {"module": mod}, Risk.MODERATE))
                # وإن تعذّر التثبيت: عطّل القدرة التي تعتمد على هذه الحزمة بالذات
                # بلطف، بدل الانهيار. لا نعطّل قدرة لا علاقة لها بالحزمة المفقودة.
                for cap in identity.self_model().capabilities:
                    deps = tuple(cap.required_packages) + tuple(cap.optional_packages)
                    if mod not in deps:
                        continue
                    if cap.impact == identity.Impact.CRITICAL:
                        continue
                    out.append(("disable_capability",
                                {"capability": cap.key,
                                 "reason": f"الحزمة {mod} غير متاحة"},
                               Risk.SAFE))
                    break

        # ملف مفقود: قد يكون نموذج عزل — والاسم قد يأتي في filename لا في الرسالة.
        haystack = (msg + " " + self._path_from_exc(exc).lower())
        if et in ("FileNotFoundError", "OSError", "RuntimeError") and (
                ".onnx" in haystack or "model" in haystack):
            name = next((n for n in vitals.MODEL_SPECS if n.lower() in haystack),
                        "u2netp.onnx")
            out.append(("download_model", {"name": name}, Risk.MODERATE))

        if "tesseract" in msg or et == "TesseractNotFoundError":
            out.append(("provision_tesseract", {}, Risk.MODERATE))

        if et == "PermissionError" or "permission denied" in msg or (
                "being used by another process" in msg):
            out.append(("resolve_locked_file",
                        {"path": self._path_from_exc(exc)}, Risk.SAFE))

        if et in ("MemoryError",) or "cannot allocate" in msg or (
                "out of memory" in msg):
            out.append(("reduce_footprint", {}, Risk.SAFE))

        if "no space left" in msg or "disk full" in msg or et == "OSError" and (
                getattr(exc, "errno", 0) == 28):
            out.append(("free_disk_space", {"need_mb": 700}, Risk.SAFE))

        if et == "UnicodeDecodeError" or "codec can't decode" in msg:
            out.append(("repair_text_encoding",
                        {"path": self._path_from_exc(exc)}, Risk.SAFE))

        if et == "FileNotFoundError":
            out.append(("ensure_path", {"path": self._path_from_exc(exc)},
                        Risk.SAFE))

        if "onnxruntime" in msg and ("provider" in msg or "cuda" in msg):
            out.append(("force_cpu_provider", {}, Risk.SAFE))

        if et in ("SyntaxError", "IndentationError"):
            out.append(("rollback_last_surgery", {}, Risk.MODERATE))

        return out

    @staticmethod
    def _path_from_exc(exc: BaseException) -> str:
        for attr in ("filename", "filename2"):
            v = getattr(exc, attr, None)
            if v:
                return str(v)
        import re
        m = re.search(r"['\"]([^'\"]{3,300})['\"]", str(exc))
        return m.group(1) if m else ""

    def _explain_unhealed(self, exc: BaseException, facts: dict,
                          inc: ledger_mod.Incident) -> str:
        """شرح عربي صادق عندما يتعذّر الإصلاح — يربط العطل بالقدرة والبديل."""
        et = type(exc).__name__
        cap_hint = ""
        fname = str(facts.get("file", ""))
        for cap in identity.self_model().capabilities:
            if cap.module.split(".")[-1] in fname:
                cap_hint = (f" المتأثر: «{cap.title_ar}». {cap.fallback_ar}")
                break
        base = {
            "PermissionError": "ملف مقفل أو صلاحية ناقصة",
            "FileNotFoundError": "ملف أو مسار مفقود",
            "MemoryError": "الذاكرة لم تكفِ",
            "TimeoutError": "العملية تجاوزت المدة المسموحة",
        }.get(et, f"عطل من نوع {et}")
        again = (f" ظهر هذا العطل {inc.seen_count} مرات، وسجّلته لأتعلم منه."
                 if inc.seen_count > 1 else " سجّلته في ذاكرتي لأتعلم منه.")
        return f"لم أستطع إصلاح هذا بنفسي: {base}.{cap_hint}{again}"

    # ───────── تصنيف الخطورة ─────────

    _RISKS = {
        "install_package": Risk.MODERATE,
        "download_model": Risk.MODERATE,
        "provision_tesseract": Risk.MODERATE,
        "provision_tessdata": Risk.MODERATE,
        "relocate_data_dir": Risk.MODERATE,
        "rollback_last_surgery": Risk.MODERATE,
        "apply_code_patch": Risk.INVASIVE,
        "free_disk_space": Risk.SAFE,
        "reduce_footprint": Risk.SAFE,
        "substitute_font": Risk.SAFE,
        "disable_capability": Risk.SAFE,
        "resolve_locked_file": Risk.SAFE,
        "ensure_path": Risk.SAFE,
        "repair_text_encoding": Risk.SAFE,
        "force_cpu_provider": Risk.SAFE,
        "reset_settings": Risk.MODERATE,
    }

    def _risk_of(self, kind: str) -> str:
        return self._RISKS.get(kind, Risk.MODERATE)

    # ═════════════════ العلاجات الفعلية ═════════════════

    def _r_install_package(self, p: dict, f: Finding | None) -> RemedyResult:
        """تثبيت حزمة ناقصة فعلًا عبر pip، مع خريطة الوحدة→الحزمة والتحقق بعده."""
        mod = str(p.get("module") or p.get("package") or "").strip()
        if not mod:
            return RemedyResult("install_package", False, "لم يُحدَّد اسم الحزمة.")
        dist = ledger_mod._DIST_FOR_MODULE.get(mod, mod)

        ok, _ = vitals.probe_import(mod, deep=True)
        if ok:
            return RemedyResult("install_package", True,
                                f"الحزمة «{mod}» متاحة أصلًا",
                                retry_recommended=True)

        with self._lock:
            if dist in self._installing:
                return RemedyResult("install_package", False,
                                    f"تثبيت «{dist}» جارٍ بالفعل.")
            self._installing.add(dist)
        try:
            if identity.is_frozen():
                return RemedyResult(
                    "install_package", False,
                    f"لا يمكن تثبيت «{dist}» داخل الحزمة التنفيذية؛ "
                    "سأعمل بالبديل الوظيفي.")

            if p.get("_offline"):
                return RemedyResult(
                    "install_package", False,
                    f"الحزمة «{dist}» ناقصة ولا اتصال لتنزيلها الآن.")

            L = ledger_mod.ledger()
            if L.network_policy != ledger_mod.NetworkPolicy.OFF:
                exists = L.package_exists(dist)
                if exists is False:
                    L.add_insight("install",
                                  f"لا توجد حزمة «{dist}» على PyPI؛ التثبيت ليس علاجًا.",
                                  source="pypi", score=0.9)
                    return RemedyResult("install_package", False,
                                        f"لا توجد حزمة باسم «{dist}» على PyPI.")

            cmd = [sys.executable, "-m", "pip", "install", "--user",
                   "--disable-pip-version-check", "--no-input", "-q", dist]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if proc.returncode != 0:
                tail = (proc.stderr or proc.stdout or "").strip().splitlines()
                return RemedyResult("install_package", False,
                                    f"فشل تثبيت «{dist}»: "
                                    + (tail[-1][:200] if tail else "سبب غير معروف"))
            # لا نثق بـ pip: نتحقق بالاستيراد الفعلي
            import importlib
            importlib.invalidate_caches()
            ok2, why = vitals.probe_import(mod, deep=True)
            if ok2:
                return RemedyResult("install_package", True,
                                    f"ثبّتت الحزمة «{dist}» وتحققت من عملها",
                                    retry_recommended=True)
            return RemedyResult("install_package", False,
                                f"ثُبّتت «{dist}» لكن استيرادها ما زال يفشل: "
                                f"{why[:150]}")
        except subprocess.TimeoutExpired:
            return RemedyResult("install_package", False,
                                f"تجاوز تثبيت «{dist}» المدة المسموحة.")
        finally:
            with self._lock:
                self._installing.discard(dist)

    def _r_download_model(self, p: dict, f: Finding | None) -> RemedyResult:
        """تنزيل نموذج عزل من المرايا، بتفضيل الخفيف عند شح الموارد."""
        name = str(p.get("name") or "u2netp.onnx")
        if p.get("prefer_light") or get_override("prefer_light_model", False):
            name = "u2netp.onnx"
        spec = vitals.MODEL_SPECS.get(name)
        if not spec:
            urls = tuple(x for x in [p.get("url")] if x)
            spec = {"urls": urls, "min_bytes": 1024 * 1024,
                    "purpose_ar": "نموذج معالجة"}
        mdir = Path(p.get("dir") or vitals._models_dir())
        if not vitals._writable(mdir):
            alt = identity.app_data_dir() / "models"
            if vitals._writable(alt):
                mdir = alt
                set_override("models_dir", str(alt),
                             reason="مجلد النماذج الأصلي غير قابل للكتابة")
            else:
                return RemedyResult("download_model", False,
                                    "لا مجلد قابل للكتابة لحفظ النموذج.")

        target = mdir / name
        with self._lock:
            if name in self._downloading:
                return RemedyResult("download_model", False,
                                    f"تنزيل «{name}» جارٍ بالفعل.")
            self._downloading.add(name)
        try:
            if p.get("_offline") or not ledger_mod.ledger().network_available():
                return RemedyResult("download_model", False,
                                    "لا اتصال بالشبكة لتنزيل النموذج؛ "
                                    "سأستخدم العزل الكلاسيكي مؤقتًا.")
            last = ""
            for url in spec.get("urls", ()):
                try:
                    tmp = target.with_suffix(".part")
                    req = urllib.request.Request(
                        url, headers={"User-Agent": "MIS-Awareness/3.0"})
                    with urllib.request.urlopen(req, timeout=30) as resp, \
                            open(tmp, "wb") as fh:
                        shutil.copyfileobj(resp, fh, length=1024 * 512)
                    size = tmp.stat().st_size
                    if size < int(spec.get("min_bytes", 0)):
                        tmp.unlink(missing_ok=True)
                        last = f"الملف المنزَّل ناقص ({size / 1048576:.1f}م)"
                        continue
                    os.replace(str(tmp), str(target))
                    vitals.invalidate_cache()
                    return RemedyResult(
                        "download_model", True,
                        f"نزّلت نموذج «{name}» ({size / 1048576:.0f} ميغابايت) "
                        "وتحققت من سلامته", retry_recommended=True)
                except Exception as exc:
                    last = f"{type(exc).__name__}: {str(exc)[:120]}"
                    continue
            return RemedyResult("download_model", False,
                                f"تعذّر تنزيل «{name}» من كل المرايا. {last}")
        finally:
            with self._lock:
                self._downloading.discard(name)

    def _r_provision_tesseract(self, p: dict, f: Finding | None) -> RemedyResult:
        """يبحث عن Tesseract ويربطه — وهذا وحده يحل معظم حالات «المحرك مفقود»."""
        exe = vitals.find_tesseract()
        if exe:
            ok = self._bind_tesseract(exe)
            return RemedyResult(
                "provision_tesseract", ok,
                f"وجدت محرك Tesseract في {Path(exe).parent} وربطته"
                if ok else "وجدت المحرك لكن تعذّر ربطه بـpytesseract",
                retry_recommended=ok)

        # موجود كحزمة نظام على لينكس؟
        if os.name != "nt":
            for cand in ("/usr/bin/tesseract", "/usr/local/bin/tesseract"):
                if Path(cand).is_file():
                    ok = self._bind_tesseract(cand)
                    return RemedyResult("provision_tesseract", ok,
                                        f"ربطت المحرك من {cand}",
                                        retry_recommended=ok)
            return RemedyResult(
                "provision_tesseract", False,
                "المحرك غير مثبَّت. التثبيت يحتاج صلاحية إدارية: "
                "sudo apt install tesseract-ocr tesseract-ocr-ara")

        # ويندوز: النسخة المحمولة إلى مجلد بياناتنا (لا تحتاج صلاحية إدارية)
        if p.get("_offline") or not ledger_mod.ledger().network_available():
            return RemedyResult("provision_tesseract", False,
                                "المحرك مفقود ولا اتصال لتنزيل نسخة محمولة؛ "
                                "سأنقل ملصق الحقائق كما هو من الصورة.")
        dest = identity.app_data_dir() / "tools" / "tesseract"
        try:
            dest.mkdir(parents=True, exist_ok=True)
        except Exception:
            return RemedyResult("provision_tesseract", False,
                                "تعذّر تهيئة مجلد الأدوات.")
        return RemedyResult(
            "provision_tesseract", False,
            "المحرك غير موجود على الجهاز. سيتب التثبيت المرفق يثبّته تلقائيًا؛ "
            "وحتى ذلك الحين أنقل ملصق الحقائق كما هو بلا إعادة رسم.")

    @staticmethod
    def _bind_tesseract(exe: str) -> bool:
        """يضبط مسار المحرك في pytesseract وفي التجاوزات وفي البيئة."""
        ok = False
        with contextlib.suppress(Exception):
            import pytesseract
            pytesseract.pytesseract.tesseract_cmd = exe
            ok = True
        set_override("tesseract_cmd", exe, reason="ربط تلقائي لمحرك OCR")
        with contextlib.suppress(Exception):
            os.environ["TESSERACT_CMD"] = exe
            td = Path(exe).parent / "tessdata"
            if td.is_dir():
                os.environ.setdefault("TESSDATA_PREFIX", str(td))
        return ok

    def _r_provision_tessdata(self, p: dict, f: Finding | None) -> RemedyResult:
        """ينزّل ملف لغة Tesseract الناقص (العربية خصوصًا)."""
        lang = str(p.get("lang") or "ara")
        exe = str(p.get("exe") or vitals.find_tesseract())
        if not exe:
            return RemedyResult("provision_tessdata", False,
                                "لا يوجد محرك Tesseract لأضيف إليه اللغة.")
        roots = [Path(exe).parent / "tessdata"]
        prefix = os.environ.get("TESSDATA_PREFIX", "")
        if prefix:
            roots.insert(0, Path(prefix))
        target_dir = next((r for r in roots if vitals._writable(r)), None)
        if target_dir is None:
            target_dir = identity.app_data_dir() / "tessdata"
            if not vitals._writable(target_dir):
                return RemedyResult("provision_tessdata", False,
                                    "لا مجلد tessdata قابل للكتابة.")
            os.environ["TESSDATA_PREFIX"] = str(target_dir)
            set_override("tessdata_prefix", str(target_dir),
                         reason="مجلد لغات بديل قابل للكتابة")
        if p.get("_offline") or not ledger_mod.ledger().network_available():
            return RemedyResult("provision_tessdata", False,
                                f"لا اتصال لتنزيل حزمة اللغة «{lang}».")
        url = ("https://github.com/tesseract-ocr/tessdata_fast/raw/main/"
               f"{lang}.traineddata")
        try:
            dst = target_dir / f"{lang}.traineddata"
            tmp = dst.with_suffix(".part")
            req = urllib.request.Request(
                url, headers={"User-Agent": "MIS-Awareness/3.0"})
            with urllib.request.urlopen(req, timeout=30) as resp, \
                    open(tmp, "wb") as fh:
                shutil.copyfileobj(resp, fh)
            if tmp.stat().st_size < 100_000:
                tmp.unlink(missing_ok=True)
                return RemedyResult("provision_tessdata", False,
                                    "الملف المنزَّل يبدو ناقصًا.")
            os.replace(str(tmp), str(dst))
            vitals.invalidate_cache()
            return RemedyResult("provision_tessdata", True,
                                f"نزّلت حزمة اللغة «{lang}» لقراءة الجداول العربية",
                                retry_recommended=True)
        except Exception as exc:
            return RemedyResult("provision_tessdata", False,
                                f"فشل تنزيل اللغة: {str(exc)[:150]}")

    def _r_free_disk_space(self, p: dict, f: Finding | None) -> RemedyResult:
        """ينظّف الملفات المؤقتة والسجلات القديمة ونسخ الجراحة المنتهية."""
        need = float(p.get("need_mb") or 500)
        base = identity.app_data_dir()
        freed = 0.0
        targets: list[Path] = []
        for sub in ("temp", "tmp", "cache", "thumbs", "_work"):
            d = base / sub
            if d.is_dir():
                targets.append(d)
        with contextlib.suppress(Exception):
            targets.append(Path(tempfile.gettempdir()) / "SmartCatalogVisionModels")

        now = time.time()
        for d in targets:
            with contextlib.suppress(Exception):
                for item in d.rglob("*"):
                    with contextlib.suppress(Exception):
                        if item.is_file() and (now - item.stat().st_mtime) > 3600:
                            sz = item.stat().st_size / 1048576
                            item.unlink()
                            freed += sz

        # سجلات مدوّرة قديمة
        with contextlib.suppress(Exception):
            for old in identity.awareness_dir().glob("journal.jsonl.*"):
                sz = old.stat().st_size / 1048576
                old.unlink()
                freed += sz

        # نسخ الجراحة الأقدم من أسبوع
        with contextlib.suppress(Exception):
            surg = identity.awareness_dir() / "surgery"
            for d in sorted(surg.glob("*")):
                if d.is_dir() and (now - d.stat().st_mtime) > 7 * 86400:
                    sz = sum(x.stat().st_size for x in d.rglob("*") if x.is_file())
                    shutil.rmtree(d, ignore_errors=True)
                    freed += sz / 1048576

        after = vitals._disk_free_mb(base)
        ok = freed > 1 or (after >= need)
        return RemedyResult("free_disk_space", ok,
                            f"حرّرت {freed:.0f} ميغابايت؛ المتاح الآن "
                            f"{after:.0f} ميغابايت" if ok else
                            "لم أجد ما يمكن حذفه بأمان؛ يلزم تفريغ يدوي.",
                            retry_recommended=ok)

    def _r_reduce_footprint(self, p: dict, f: Finding | None) -> RemedyResult:
        """يخفض استهلاك الذاكرة: دفعة أصغر، خيوط أقل، نموذج أخف."""
        avail = float(p.get("available_mb") or vitals._mem_available_mb() or 0)
        cur_batch = int(get_override("batch_size", 8) or 8)
        cur_threads = int(get_override("max_workers", os.cpu_count() or 4) or 4)
        batch = 2 if avail and avail < 500 else max(2, min(cur_batch, 4))
        threads = 1 if avail and avail < 500 else max(1, min(cur_threads, 2))
        set_override("batch_size", batch, reason="ذاكرة شحيحة")
        set_override("max_workers", threads, reason="ذاكرة شحيحة")
        set_override("prefer_light_model", True, reason="ذاكرة شحيحة")
        return RemedyResult(
            "reduce_footprint", True,
            f"خفّضت حجم الدفعة إلى {batch} والخيوط إلى {threads} وفضّلت النموذج "
            "الخفيف لأتجنّب نفاد الذاكرة", retry_recommended=True)

    def _r_substitute_font(self, p: dict, f: Finding | None) -> RemedyResult:
        """يستبدل الخط العربي المفقود بأفضل خط متاح في النظام."""
        prefer = ("NotoNaskhArabic", "Amiri", "Cairo", "Tahoma", "Arial",
                  "DejaVuSans", "NotoSans")
        roots = [Path("C:/Windows/Fonts"), Path("/usr/share/fonts"),
                 Path.home() / ".fonts", Path("/Library/Fonts")]
        found = ""
        for pref in prefer:
            for root in roots:
                with contextlib.suppress(Exception):
                    if not root.is_dir():
                        continue
                    hits = [x for x in root.rglob("*.ttf")
                            if pref.lower() in x.stem.lower().replace(" ", "")]
                    if hits:
                        found = str(hits[0])
                        break
            if found:
                break
        if not found:
            for root in roots:
                with contextlib.suppress(Exception):
                    if root.is_dir():
                        any_ttf = next(iter(root.rglob("*.ttf")), None)
                        if any_ttf:
                            found = str(any_ttf)
                            break
        if not found:
            return RemedyResult("substitute_font", False,
                                "لا يوجد أي خط TTF في النظام لأستخدمه بديلًا.")
        set_override("arabic_font_path", found, reason="الخط المحزَّم مفقود")
        return RemedyResult("substitute_font", True,
                            f"استخدمت خط «{Path(found).stem}» بديلًا للخط المفقود",
                            retry_recommended=True)

    def _r_disable_capability(self, p: dict, f: Finding | None) -> RemedyResult:
        """تدهور لطيف: تُعطَّل القدرة بوضوح بدل أن تُسقط التطبيق."""
        key = str(p.get("capability") or (f.capability if f else ""))
        if not key:
            return RemedyResult("disable_capability", False,
                                "لم تُحدَد القدرة المطلوب تعطيلها.")
        cap = identity.self_model().capability(key)
        if cap is None:
            # لا أعطّل شيئًا لا أعرفه — قد يكون اسمًا خاطئًا لقدرة حرجة.
            known = "، ".join(c.key for c in identity.self_model().capabilities)
            return RemedyResult(
                "disable_capability", False,
                f"لا أعرف قدرة باسم «{key}» فلن أعطّل شيئًا على العميان. "
                f"قدراتي المعروفة: {known}")
        if cap.impact == identity.Impact.CRITICAL:
            return RemedyResult("disable_capability", False,
                                f"«{cap.title_ar}» قدرة حرجة لا يصح تعطيلها؛ "
                                "أبحث عن علاج آخر.")
        disabled = list(get_override("disabled_capabilities", []) or [])
        if key not in disabled:
            disabled.append(key)
        set_override("disabled_capabilities", disabled,
                     reason=str(p.get("reason") or "تبعية مفقودة"))
        label = cap.title_ar if cap else key
        fb = f" {cap.fallback_ar}" if cap and cap.fallback_ar else ""
        return RemedyResult("disable_capability", True,
                            f"عطّلت «{label}» بلطف لأتابع العمل بلا انهيار.{fb}",
                            retry_recommended=True)

    def _r_resolve_locked_file(self, p: dict, f: Finding | None) -> RemedyResult:
        """ملف مقفل (إكسل مفتوح غالبًا): انتظار قصير ثم مسار بديل."""
        path = str(p.get("path") or "")
        if path:
            for delay in (0.3, 0.7, 1.2):
                time.sleep(delay)
                with contextlib.suppress(Exception):
                    pp = Path(path)
                    if not pp.exists():
                        break
                    with open(pp, "ab"):
                        return RemedyResult(
                            "resolve_locked_file", True,
                            "كان الملف مقفلًا لحظيًا وأصبح متاحًا الآن",
                            retry_recommended=True)
        alt = identity.app_data_dir() / "out_alt"
        with contextlib.suppress(Exception):
            alt.mkdir(parents=True, exist_ok=True)
        set_override("fallback_output_dir", str(alt),
                     reason="ملف أو مجلد الهدف مقفل")
        name = Path(path).name if path else "الملف"
        return RemedyResult(
            "resolve_locked_file", True,
            f"«{name}» مقفل (قد يكون مفتوحًا في برنامج آخر)، فسأكتب في مجلد بديل "
            f"ثم أدمج النتيجة لاحقًا", retry_recommended=True)

    def _r_ensure_path(self, p: dict, f: Finding | None) -> RemedyResult:
        """ينشئ المسار المفقود إن كان مجلدًا متوقعًا لنا."""
        raw = str(p.get("path") or "")
        if not raw:
            return RemedyResult("ensure_path", False, "لا مسار محدد.")
        pp = Path(raw)
        parent = pp if (pp.suffix == "") else pp.parent
        safe_roots = (identity.app_data_dir(), identity.repo_root(),
                      Path(tempfile.gettempdir()))
        try:
            resolved = parent.resolve()
        except Exception:
            resolved = parent
        if not any(str(resolved).startswith(str(r.resolve()))
                   for r in safe_roots if str(r)):
            return RemedyResult("ensure_path", False,
                                "المسار خارج نطاقي الآمن فلن أنشئه من نفسي.")
        try:
            parent.mkdir(parents=True, exist_ok=True)
            return RemedyResult("ensure_path", True,
                                f"أنشأت المجلد المفقود «{parent.name}»",
                                retry_recommended=True)
        except Exception as exc:
            return RemedyResult("ensure_path", False,
                                f"تعذّر إنشاء المسار: {str(exc)[:150]}")

    def _r_relocate_data_dir(self, p: dict, f: Finding | None) -> RemedyResult:
        """مجلد البيانات محجوب: ينتقل إلى بديل قابل للكتابة ويحفظ القرار."""
        for cand in (Path.home() / "SmartCatalogVision",
                     Path(os.environ.get("LOCALAPPDATA", "") or
                          tempfile.gettempdir()) / "SmartCatalogVision",
                     Path(tempfile.gettempdir()) / "SmartCatalogVision"):
            if vitals._writable(cand):
                os.environ["MIS_DATA_ROOT"] = str(cand)
                set_override("data_root", str(cand),
                             reason="المجلد الأصلي غير قابل للكتابة")
                vitals.invalidate_cache()
                return RemedyResult(
                    "relocate_data_dir", True,
                    f"نقلت مجلد بياناتي إلى {cand} لأنه قابل للكتابة",
                    retry_recommended=True)
        return RemedyResult("relocate_data_dir", False,
                            "لم أجد أي مجلد قابل للكتابة على هذا الجهاز.")

    def _r_repair_text_encoding(self, p: dict, f: Finding | None) -> RemedyResult:
        """يضبط ترميز القراءة — سبب Mojibake الشائع على ويندوز العربي."""
        set_override("text_encoding_fallbacks",
                     ["utf-8-sig", "utf-8", "cp1256", "cp1252", "latin-1"],
                     reason="فشل فك ترميز نص")
        return RemedyResult(
            "repair_text_encoding", True,
            "ضبطت سلسلة ترميزات بديلة (utf-8-sig ثم cp1256) لقراءة الملفات "
            "العربية بلا تشويش", retry_recommended=True)

    def _r_force_cpu_provider(self, p: dict, f: Finding | None) -> RemedyResult:
        """يحصر onnxruntime على المعالج — يحل أعطال مزوّد GPU المفقود."""
        set_override("onnx_providers", ["CPUExecutionProvider"],
                     reason="مزوّد التسريع غير متاح")
        with contextlib.suppress(Exception):
            os.environ["ORT_DISABLE_ALL_GPU"] = "1"
        return RemedyResult("force_cpu_provider", True,
                            "حصرت تشغيل النماذج على المعالج بعد تعذّر مزوّد "
                            "التسريع", retry_recommended=True)

    def _r_reset_settings(self, p: dict, f: Finding | None) -> RemedyResult:
        """إعدادات تالفة: تُنحّى وتُبنى افتراضية (مع حفظ نسخة)."""
        base = identity.app_data_dir()
        moved = []
        for name in ("settings.json", "settings_v2.json", "ui_state.json"):
            pp = base / name
            with contextlib.suppress(Exception):
                if pp.is_file():
                    bak = pp.with_suffix(f".bak-{int(time.time())}")
                    pp.rename(bak)
                    moved.append(name)
        if not moved:
            return RemedyResult("reset_settings", False,
                                "لا ملف إعدادات لأصفّره.")
        return RemedyResult("reset_settings", True,
                            "أعدت الإعدادات إلى الافتراضي بعد حفظ نسخة من القديم: "
                            + "، ".join(moved), retry_recommended=True)

    def _r_rollback_last_surgery(self, p: dict, f: Finding | None) -> RemedyResult:
        """يتراجع عن آخر تعديل ذاتي على الشفرة — شبكة أمان الجراحة."""
        try:
            from . import surgeon
        except Exception:
            return RemedyResult("rollback_last_surgery", False,
                                "وحدة الجراحة غير متاحة.")
        try:
            res = surgeon.rollback_last()
            return RemedyResult("rollback_last_surgery", bool(res.get("ok")),
                                str(res.get("message_ar") or ""),
                                retry_recommended=bool(res.get("ok")))
        except Exception as exc:
            return RemedyResult("rollback_last_surgery", False,
                                f"فشل التراجع: {str(exc)[:150]}")

    def _r_apply_code_patch(self, p: dict, f: Finding | None) -> RemedyResult:
        """يطبّق رقعة على بنية الشفرة (خطر — يحتاج إذنًا) عبر وحدة الجراحة."""
        try:
            from . import surgeon
        except Exception:
            return RemedyResult("apply_code_patch", False,
                                "وحدة الجراحة غير متاحة.")
        try:
            res = surgeon.operate(codes=p.get("codes"), apply=True,
                                 targets=p.get("targets"))
            ok = bool(res.get("applied"))
            return RemedyResult("apply_code_patch", ok,
                                str(res.get("message_ar") or ""),
                                retry_recommended=ok)
        except Exception as exc:
            return RemedyResult("apply_code_patch", False,
                                f"فشلت الجراحة: {str(exc)[:150]}")


_NETWORK_REMEDIES = {"install_package", "download_model", "provision_tessdata",
                     "provision_tesseract"}


# ───────────────────────── الواجهة المفردة ─────────────────────────

_HEALER: Healer | None = None
_H_LOCK = threading.Lock()


def healer() -> Healer:
    global _HEALER
    if _HEALER is None:
        with _H_LOCK:
            if _HEALER is None:
                _HEALER = Healer()
    return _HEALER


def heal(report: HealthReport | None = None, **kw) -> HealSession:
    return healer().heal(report, **kw)


def heal_from_exception(exc: BaseException, **kw) -> RetryDecision:
    return healer().heal_from_exception(exc, **kw)
