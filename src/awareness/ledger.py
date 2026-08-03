# -*- coding: utf-8 -*-
"""ledger — السجل الأكاشي: ذاكرة البرنامج الدائمة ومصدر معرفته.

الفكرة
------
البرنامج العادي يُولد من جديد في كل تشغيل: ينسى كل عطل واجهه وكل حل نجح معه.
هذه الوحدة تكسر ذلك. كل عطل يُختزل إلى **بصمة مستقرة**، وكل علاج يُسجَّل مع
سجل نجاحه وفشله. فإذا تكرر العطل بعد شهر أو على جهاز آخر، لا يُعاد التشخيص من
الصفر: يُستدعى العلاج الذي نجح سابقًا مباشرة.

طبقتان:

1. **الذاكرة المحلية** (SQLite في ``<AppData>/awareness/akashic.db``):
   ``incidents`` الأعطال ببصماتها وتكرارها، ``remedies`` العلاجات ومعدل نجاحها،
   ``insights`` دروس نصية مستخلصة، ``lineage`` تاريخ الجراحات على الشفرة.
   تعمل دائمًا، بلا إنترنت، وهي المصدر الأساسي.

2. **جسر الشبكة** (اختياري، خيط خلفي، مهلة صارمة): عند عطل **مجهول تمامًا**
   يستعلم من مصادر تقنية عامة (فهرس PyPI، مرايا النماذج، توثيق الحزم) ليقترح
   علاجًا، ويحوّل ما يجده إلى ``insight`` محلي. لا يرسل أي بيانات مستخدم — فقط
   نص الخطأ المُطبَّع والمنقّى. وميزانيته الزمنية لا تلمس مسار العمل الساخن.

سياسة الشبكة (``network_policy``): ``off`` / ``resources_only`` / ``full``.
الافتراضي ``full`` بتفويض صريح من المالك، ويمكن خفضه من واجهة الوعي.

كل الدوال آمنة الفشل: قاعدة بيانات تالفة أو قرص ممتلئ يعني تعطّل الذاكرة، لا
تعطّل البرنامج. عند تعذّر SQLite تعمل الوحدة بذاكرة داخلية مؤقتة.
"""
from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import identity, journal

__all__ = [
    "NetworkPolicy",
    "Incident",
    "Remedy",
    "Ledger",
    "ledger",
    "remember_incident",
    "remember_remedy",
    "best_remedies",
    "add_insight",
    "consult",
    "network_available",
]


class NetworkPolicy:
    OFF = "off"
    RESOURCES_ONLY = "resources_only"   # تنزيل نماذج/حزم فقط، بلا استعلام معرفي
    FULL = "full"                       # تنزيل + استعلام معرفي

    ALL = (OFF, RESOURCES_ONLY, FULL)

    LABELS_AR = {
        OFF: "مغلقة — أعمل من ذاكرتي المحلية فقط",
        RESOURCES_ONLY: "الموارد فقط — أنزّل النماذج والحزم الناقصة دون استعلام معرفي",
        FULL: "كاملة — أنزّل الموارد وأستعلم عن حلول الأعطال المجهولة",
    }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    fingerprint   TEXT PRIMARY KEY,
    exc_type      TEXT,
    message_norm  TEXT,
    file          TEXT,
    func          TEXT,
    capability    TEXT,
    first_seen    REAL,
    last_seen     REAL,
    seen_count    INTEGER DEFAULT 1,
    resolved      INTEGER DEFAULT 0,
    context       TEXT
);
CREATE TABLE IF NOT EXISTS remedies (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint   TEXT,
    kind          TEXT,
    params        TEXT,
    risk          TEXT DEFAULT 'safe',
    successes     INTEGER DEFAULT 0,
    failures      INTEGER DEFAULT 0,
    last_used     REAL,
    origin        TEXT DEFAULT 'local',
    note          TEXT,
    UNIQUE(fingerprint, kind, params)
);
CREATE TABLE IF NOT EXISTS insights (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    topic         TEXT,
    fingerprint   TEXT,
    text          TEXT,
    source        TEXT,
    created       REAL,
    score         REAL DEFAULT 0.5
);
CREATE TABLE IF NOT EXISTS lineage (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    surgery_id    TEXT,
    kind          TEXT,
    target        TEXT,
    applied       REAL,
    reverted      REAL,
    outcome       TEXT,
    detail        TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    key           TEXT PRIMARY KEY,
    value         TEXT
);
CREATE INDEX IF NOT EXISTS idx_rem_fp ON remedies(fingerprint);
CREATE INDEX IF NOT EXISTS idx_ins_fp ON insights(fingerprint);
"""


@dataclass
class Incident:
    fingerprint: str
    exc_type: str = ""
    message_norm: str = ""
    file: str = ""
    func: str = ""
    capability: str = ""
    first_seen: float = 0.0
    last_seen: float = 0.0
    seen_count: int = 0
    resolved: bool = False
    context: dict = field(default_factory=dict)

    @property
    def is_recurring(self) -> bool:
        return self.seen_count >= 3


@dataclass
class Remedy:
    """علاج مرشّح لعطل، مع سجل أدائه التاريخي."""

    kind: str
    params: dict = field(default_factory=dict)
    risk: str = "safe"
    successes: int = 0
    failures: int = 0
    origin: str = "local"
    note: str = ""
    row_id: int = 0

    @property
    def attempts(self) -> int:
        return self.successes + self.failures

    @property
    def confidence(self) -> float:
        """تقدير لابلاس لمعدل النجاح — يمنع الثقة العمياء بعلاج جُرِّب مرة واحدة."""
        return (self.successes + 1.0) / (self.attempts + 2.0)

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "params": self.params,
            "risk": self.risk,
            "successes": self.successes,
            "failures": self.failures,
            "confidence": round(self.confidence, 3),
            "origin": self.origin,
            "note": self.note,
        }


class Ledger:
    """الذاكرة الدائمة. كائن واحد يُشارَك عبر الخيوط (SQLite بقفل داخلي)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else (identity.awareness_dir() / "akashic.db")
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._degraded = False           # وضع الذاكرة المؤقتة عند فشل SQLite
        self._mem: dict[str, dict] = {}
        self._net_cache: dict[str, tuple[float, list]] = {}
        self._net_checked_at = 0.0
        self._net_ok = False
        self._open()

    # ── الاتصال ──
    def _open(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.path), timeout=5.0,
                                   check_same_thread=False)
            conn.row_factory = sqlite3.Row
            with contextlib.suppress(Exception):
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(_SCHEMA)
            conn.commit()
            self._conn = conn
            self._degraded = False
        except Exception as exc:
            self._conn = None
            self._degraded = True
            journal.warn("ledger_degraded", detail=str(exc)[:200])
            self._try_recover()

    def _try_recover(self) -> None:
        """قاعدة تالفة: نُنحّيها ونبدأ نظيفة — الذاكرة أهم من محتواها القديم."""
        try:
            if self.path.exists():
                bad = self.path.with_suffix(f".corrupt-{int(time.time())}")
                with contextlib.suppress(Exception):
                    self.path.rename(bad)
                    journal.warn("ledger_reset", moved_to=bad.name)
                conn = sqlite3.connect(str(self.path), timeout=5.0,
                                       check_same_thread=False)
                conn.row_factory = sqlite3.Row
                conn.executescript(_SCHEMA)
                conn.commit()
                self._conn = conn
                self._degraded = False
        except Exception:
            self._degraded = True

    def _exec(self, sql: str, args: tuple = (), *, fetch: str = "none"):
        if self._conn is None:
            return [] if fetch == "all" else None
        with self._lock:
            try:
                cur = self._conn.execute(sql, args)
                if fetch == "all":
                    return cur.fetchall()
                if fetch == "one":
                    return cur.fetchone()
                self._conn.commit()
                return cur.lastrowid
            except sqlite3.DatabaseError as exc:
                journal.warn("ledger_sql_error", detail=str(exc)[:200])
                self._try_recover()
                return [] if fetch == "all" else None
            except Exception:
                return [] if fetch == "all" else None

    # ── الإعدادات ──
    def get_meta(self, key: str, default: str = "") -> str:
        row = self._exec("SELECT value FROM meta WHERE key=?", (key,), fetch="one")
        if row is None:
            return self._mem.get("meta", {}).get(key, default) if self._degraded else default
        return str(row["value"])

    def set_meta(self, key: str, value: str) -> None:
        if self._degraded:
            self._mem.setdefault("meta", {})[key] = value
            return
        self._exec("INSERT INTO meta(key,value) VALUES(?,?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (key, str(value)))

    @property
    def network_policy(self) -> str:
        pol = os.environ.get("MIS_NETWORK_POLICY", "").strip().lower()
        if pol in NetworkPolicy.ALL:
            return pol
        stored = self.get_meta("network_policy", "")
        return stored if stored in NetworkPolicy.ALL else NetworkPolicy.FULL

    def set_network_policy(self, policy: str) -> str:
        pol = policy if policy in NetworkPolicy.ALL else NetworkPolicy.FULL
        self.set_meta("network_policy", pol)
        journal.info("network_policy_set", policy=pol)
        return pol

    # ── الأعطال ──
    def remember_incident(self, facts: dict, *, capability: str = "") -> Incident:
        """يسجّل ظهور عطل أو يزيد عدّاده. يُرجع الحالة المحدَّثة."""
        fp = str(facts.get("fingerprint") or journal.fingerprint())
        now = time.time()
        if self._degraded:
            rec = self._mem.setdefault("inc", {}).setdefault(
                fp, {"seen_count": 0, "first_seen": now})
            rec["seen_count"] += 1
            rec["last_seen"] = now
            return Incident(fingerprint=fp, exc_type=str(facts.get("type", "")),
                            seen_count=rec["seen_count"], first_seen=rec["first_seen"],
                            last_seen=now)

        ctx = json.dumps({k: facts.get(k) for k in
                          ("event_context", "line", "elapsed_ms")},
                         ensure_ascii=False)
        self._exec(
            "INSERT INTO incidents(fingerprint,exc_type,message_norm,file,func,"
            "capability,first_seen,last_seen,seen_count,context) "
            "VALUES(?,?,?,?,?,?,?,?,1,?) "
            "ON CONFLICT(fingerprint) DO UPDATE SET "
            "last_seen=excluded.last_seen, seen_count=incidents.seen_count+1, "
            "context=excluded.context",
            (fp, str(facts.get("type", "")), str(facts.get("message_norm", "")),
             str(facts.get("file", "")), str(facts.get("func", "")),
             capability, now, now, ctx))
        return self.incident(fp) or Incident(fingerprint=fp, seen_count=1)

    def incident(self, fingerprint: str) -> Incident | None:
        row = self._exec("SELECT * FROM incidents WHERE fingerprint=?",
                         (fingerprint,), fetch="one")
        if not row:
            return None
        try:
            ctx = json.loads(row["context"] or "{}")
        except Exception:
            ctx = {}
        return Incident(
            fingerprint=row["fingerprint"], exc_type=row["exc_type"] or "",
            message_norm=row["message_norm"] or "", file=row["file"] or "",
            func=row["func"] or "", capability=row["capability"] or "",
            first_seen=row["first_seen"] or 0.0, last_seen=row["last_seen"] or 0.0,
            seen_count=int(row["seen_count"] or 0),
            resolved=bool(row["resolved"]), context=ctx)

    def mark_resolved(self, fingerprint: str, resolved: bool = True) -> None:
        self._exec("UPDATE incidents SET resolved=? WHERE fingerprint=?",
                   (1 if resolved else 0, fingerprint))

    # ── العلاجات ──
    def remember_remedy(self, fingerprint: str, kind: str, params: dict | None = None,
                        *, risk: str = "safe", origin: str = "local",
                        note: str = "") -> int:
        p = json.dumps(params or {}, ensure_ascii=False, sort_keys=True)
        rid = self._exec(
            "INSERT INTO remedies(fingerprint,kind,params,risk,origin,note,last_used) "
            "VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(fingerprint,kind,params) DO UPDATE SET "
            "note=excluded.note, risk=excluded.risk",
            (fingerprint, kind, p, risk, origin, note, time.time()))
        return int(rid or 0)

    def record_outcome(self, fingerprint: str, kind: str, params: dict | None,
                       success: bool) -> None:
        """التعزيز: كل استعمال يعدّل ثقتنا بالعلاج فيرتفع الناجح ويهبط الفاشل."""
        p = json.dumps(params or {}, ensure_ascii=False, sort_keys=True)
        col = "successes" if success else "failures"
        self._exec(
            f"UPDATE remedies SET {col}={col}+1, last_used=? "  # noqa: S608 - عمود ثابت
            "WHERE fingerprint=? AND kind=? AND params=?",
            (time.time(), fingerprint, kind, p))
        if success:
            self.mark_resolved(fingerprint, True)
        journal.info("remedy_outcome", fingerprint=fingerprint, kind=kind,
                     success=success)

    def best_remedies(self, fingerprint: str, *, limit: int = 4,
                      max_risk: str = "moderate") -> list[Remedy]:
        """العلاجات المرشّحة مرتّبة بالثقة تنازليًا، مع تصفية بالخطورة."""
        rows = self._exec(
            "SELECT * FROM remedies WHERE fingerprint=? ORDER BY successes DESC",
            (fingerprint,), fetch="all") or []
        rank = {"safe": 0, "moderate": 1, "invasive": 2}
        ceiling = rank.get(max_risk, 1)
        out: list[Remedy] = []
        for r in rows:
            try:
                if rank.get(r["risk"] or "safe", 0) > ceiling:
                    continue
                out.append(Remedy(
                    kind=r["kind"], params=json.loads(r["params"] or "{}"),
                    risk=r["risk"] or "safe", successes=int(r["successes"] or 0),
                    failures=int(r["failures"] or 0), origin=r["origin"] or "local",
                    note=r["note"] or "", row_id=int(r["id"])))
            except Exception:
                continue
        # نُسقط ما فشل كثيرًا ولم ينجح قط — لا نكرر ما ثبت فشله
        out = [r for r in out if not (r.failures >= 3 and r.successes == 0)]
        out.sort(key=lambda r: (r.confidence, r.successes), reverse=True)
        return out[:limit]

    # ── الدروس ──
    def add_insight(self, topic: str, text: str, *, fingerprint: str = "",
                    source: str = "local", score: float = 0.5) -> int:
        rid = self._exec(
            "INSERT INTO insights(topic,fingerprint,text,source,created,score) "
            "VALUES(?,?,?,?,?,?)",
            (topic, fingerprint, journal.sanitize(text)[:2000], source,
             time.time(), float(score)))
        return int(rid or 0)

    def insights(self, *, fingerprint: str = "", topic: str = "",
                 limit: int = 12) -> list[dict]:
        if fingerprint:
            rows = self._exec("SELECT * FROM insights WHERE fingerprint=? "
                              "ORDER BY score DESC, created DESC LIMIT ?",
                              (fingerprint, limit), fetch="all")
        elif topic:
            rows = self._exec("SELECT * FROM insights WHERE topic=? "
                              "ORDER BY score DESC, created DESC LIMIT ?",
                              (topic, limit), fetch="all")
        else:
            rows = self._exec("SELECT * FROM insights ORDER BY created DESC LIMIT ?",
                              (limit,), fetch="all")
        return [dict(r) for r in (rows or [])]

    # ── نسب الجراحة ──
    def record_surgery(self, surgery_id: str, kind: str, target: str,
                       outcome: str, detail: str = "") -> None:
        self._exec("INSERT INTO lineage(surgery_id,kind,target,applied,outcome,detail) "
                   "VALUES(?,?,?,?,?,?)",
                   (surgery_id, kind, target, time.time(), outcome,
                    journal.sanitize(detail)[:1500]))

    def record_revert(self, surgery_id: str) -> None:
        self._exec("UPDATE lineage SET reverted=?, outcome='reverted' "
                   "WHERE surgery_id=?", (time.time(), surgery_id))

    def surgeries(self, limit: int = 20) -> list[dict]:
        rows = self._exec("SELECT * FROM lineage ORDER BY applied DESC LIMIT ?",
                          (limit,), fetch="all")
        return [dict(r) for r in (rows or [])]

    # ── إحصاءات الذاكرة ──
    def summary(self) -> dict:
        def one(sql: str, args: tuple = ()) -> int:
            row = self._exec(sql, args, fetch="one")
            try:
                return int(row[0]) if row else 0
            except Exception:
                return 0

        return {
            "degraded": self._degraded,
            "db": str(self.path),
            "incidents": one("SELECT COUNT(*) FROM incidents"),
            "recurring": one("SELECT COUNT(*) FROM incidents WHERE seen_count>=3"),
            "resolved": one("SELECT COUNT(*) FROM incidents WHERE resolved=1"),
            "remedies": one("SELECT COUNT(*) FROM remedies"),
            "successful_remedies": one("SELECT COUNT(*) FROM remedies WHERE successes>0"),
            "insights": one("SELECT COUNT(*) FROM insights"),
            "surgeries": one("SELECT COUNT(*) FROM lineage"),
            "network_policy": self.network_policy,
            "network_available": self._net_ok,
        }

    def top_incidents(self, limit: int = 8) -> list[dict]:
        rows = self._exec("SELECT fingerprint,exc_type,message_norm,file,func,"
                          "seen_count,resolved FROM incidents "
                          "ORDER BY seen_count DESC LIMIT ?", (limit,), fetch="all")
        return [dict(r) for r in (rows or [])]

    # ────────────────── جسر الشبكة ──────────────────

    def network_available(self, *, force: bool = False) -> bool:
        """فحص اتصال سريع مع تخزين مؤقت 90 ثانية — لا نفحص في كل نداء."""
        if self.network_policy == NetworkPolicy.OFF:
            return False
        now = time.time()
        if not force and (now - self._net_checked_at) < 90:
            return self._net_ok
        self._net_checked_at = now
        ok = False
        for url in ("https://pypi.org/simple/", "https://github.com"):
            try:
                req = urllib.request.Request(url, method="HEAD",
                                             headers={"User-Agent": "MIS-Awareness/3.0"})
                with urllib.request.urlopen(req, timeout=3) as resp:
                    ok = 200 <= int(getattr(resp, "status", 200)) < 400
                if ok:
                    break
            except Exception:
                continue
        self._net_ok = ok
        journal.debug("network_probe", available=ok, policy=self.network_policy)
        return ok

    def _fetch(self, url: str, *, timeout: float = 6.0) -> str:
        req = urllib.request.Request(
            url, headers={"User-Agent": "MIS-Awareness/3.0 (self-diagnosis)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(300_000)
        try:
            return raw.decode("utf-8", "replace")
        except Exception:
            return ""

    def package_exists(self, name: str) -> bool | None:
        """هل الحزمة موجودة على PyPI؟ ``None`` تعني «لم أستطع التحقق».

        هذا يمنع محاولة تثبيت اسم خاطئ مرارًا: إن لم توجد الحزمة نسجّل درسًا
        بأن العلاج بالتثبيت غير مجدٍ ونتجه إلى البديل الوظيفي.
        """
        if self.network_policy == NetworkPolicy.OFF or not self.network_available():
            return None
        key = f"pypi:{name}"
        hit = self._net_cache.get(key)
        if hit and (time.time() - hit[0]) < 3600:
            return bool(hit[1])
        try:
            txt = self._fetch(f"https://pypi.org/pypi/{name}/json", timeout=5.0)
            ok = bool(txt) and '"info"' in txt
        except urllib.error.HTTPError as exc:
            ok = False if getattr(exc, "code", 0) == 404 else None
        except Exception:
            ok = None
        if ok is not None:
            self._net_cache[key] = (time.time(), [ok])
        return ok

    def consult(self, facts: dict, *, timeout: float = 6.0) -> list[Remedy]:
        """استعلام معرفي عن عطل مجهول — «قراءة السجل الأكاشي».

        يُنادى فقط بعد فشل الذاكرة المحلية، وفي خيط خلفي، وبميزانية زمنية صارمة.
        يُرجع علاجات مرشّحة من مصدر خارجي مع ``origin='network'`` وثقة مبدئية
        منخفضة — فالمعرفة الخارجية تُجرَّب بحذر ثم تُثبت نفسها بالتجربة.
        """
        if self.network_policy != NetworkPolicy.FULL:
            return []
        fp = str(facts.get("fingerprint") or "")
        cached = self._net_cache.get(f"cons:{fp}")
        if cached and (time.time() - cached[0]) < 1800:
            return list(cached[1])
        if not self.network_available():
            return []

        found: list[Remedy] = []
        etype = str(facts.get("type", ""))
        msg = str(facts.get("message_norm") or facts.get("message") or "")

        # 1) عطل استيراد: نستنتج اسم الحزمة ونتحقق من وجودها فعلًا على PyPI
        if etype in ("ModuleNotFoundError", "ImportError"):
            mod = _module_from_message(msg)
            if mod:
                dist = _DIST_FOR_MODULE.get(mod, mod)
                exists = self.package_exists(dist)
                if exists:
                    found.append(Remedy(
                        kind="install_package", params={"package": dist},
                        risk="moderate", origin="network",
                        note=f"الحزمة {dist} موجودة على PyPI؛ التثبيت علاج مباشر."))
                    self.add_insight(
                        "import", f"الوحدة {mod} تُوفّرها الحزمة {dist} المتاحة على PyPI.",
                        fingerprint=fp, source="pypi", score=0.8)
                elif exists is False:
                    self.add_insight(
                        "import",
                        f"لا توجد حزمة باسم {dist} على PyPI؛ التثبيت ليس علاجًا — "
                        "يجب التحويل إلى البديل الوظيفي أو تعطيل القدرة بلطف.",
                        fingerprint=fp, source="pypi", score=0.9)
                    found.append(Remedy(
                        kind="disable_capability", params={"reason": "package_absent"},
                        risk="safe", origin="network",
                        note="الحزمة غير موجودة أصلًا؛ الأفضل التدهور اللطيف."))

        # 2) عطل نموذج/ملف مفقود: نتحقق من صلاحية المرايا قبل ترشيح التنزيل
        if "onnx" in msg or "model" in msg or etype == "FileNotFoundError":
            for url in _MODEL_MIRROR_PROBES:
                try:
                    req = urllib.request.Request(
                        url, method="HEAD",
                        headers={"User-Agent": "MIS-Awareness/3.0"})
                    with urllib.request.urlopen(req, timeout=min(timeout, 4)) as r:
                        if 200 <= int(getattr(r, "status", 200)) < 400:
                            found.append(Remedy(
                                kind="download_model", params={"url": url},
                                risk="moderate", origin="network",
                                note="مرآة نموذج متاحة ومتحققة الآن."))
                            break
                except Exception:
                    continue

        self._net_cache[f"cons:{fp}"] = (time.time(), list(found))
        journal.info("akashic_consult", fingerprint=fp, candidates=len(found),
                     exc_type=etype)
        for r in found:
            self.remember_remedy(fp, r.kind, r.params, risk=r.risk,
                                 origin="network", note=r.note)
        return found

    def consult_async(self, facts: dict, callback=None) -> None:
        """استعلام في خيط خلفي — لا يُبطئ مسار العمل مطلقًا."""
        def run():
            try:
                res = self.consult(facts)
                if callback:
                    with contextlib.suppress(Exception):
                        callback(res)
            except Exception as exc:
                journal.warn("akashic_consult_failed", detail=str(exc)[:200])

        t = threading.Thread(target=run, name="akashic-consult", daemon=True)
        t.start()


# خريطة الوحدة إلى اسم الحزمة على PyPI (يختلفان كثيرًا وهذا سبب فشل تثبيت شائع)
_DIST_FOR_MODULE = {
    "cv2": "opencv-python-headless",
    "PIL": "Pillow",
    "PySide6": "PySide6",
    "onnxruntime": "onnxruntime",
    "pytesseract": "pytesseract",
    "openpyxl": "openpyxl",
    "numpy": "numpy",
    "zxingcpp": "zxing-cpp",
    "dilithium_py": "dilithium-py",
    "cryptography": "cryptography",
    "qrcode": "qrcode",
    "segno": "segno",
    "xlrd": "xlrd",
    "psutil": "psutil",
    "yaml": "PyYAML",
    "dateutil": "python-dateutil",
    "skimage": "scikit-image",
    "sklearn": "scikit-learn",
}

_MODEL_MIRROR_PROBES = (
    "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx",
    "https://huggingface.co/tomjackson2023/rembg/resolve/main/u2net.onnx",
)


def _module_from_message(msg: str) -> str:
    """يستخرج اسم الوحدة من رسالة ImportError بصيغها المختلفة."""
    import re
    for pat in (r"no module named ['\"]?([\w\.]+)",
                r"cannot import name ['\"]?([\w\.]+)",
                r"dll load failed while importing ([\w\.]+)"):
        m = re.search(pat, msg or "", re.IGNORECASE)
        if m:
            return m.group(1).split(".")[0]
    return ""


# ───────────────────────── الواجهة المفردة ─────────────────────────

_LEDGER: Ledger | None = None
_L_LOCK = threading.Lock()


def ledger() -> Ledger:
    global _LEDGER
    if _LEDGER is None:
        with _L_LOCK:
            if _LEDGER is None:
                _LEDGER = Ledger()
    return _LEDGER


def remember_incident(facts: dict, *, capability: str = "") -> Incident:
    return ledger().remember_incident(facts, capability=capability)


def remember_remedy(fingerprint: str, kind: str, params: dict | None = None,
                    **kw) -> int:
    return ledger().remember_remedy(fingerprint, kind, params, **kw)


def best_remedies(fingerprint: str, **kw) -> list[Remedy]:
    return ledger().best_remedies(fingerprint, **kw)


def add_insight(topic: str, text: str, **kw) -> int:
    return ledger().add_insight(topic, text, **kw)


def consult(facts: dict, **kw) -> list[Remedy]:
    return ledger().consult(facts, **kw)


def network_available(**kw) -> bool:
    return ledger().network_available(**kw)
