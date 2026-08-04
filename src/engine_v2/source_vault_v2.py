# -*- coding: utf-8 -*-
"""خزانة المصادر (2.9.6) — تحصين مسارات المهمة ضد النقل والحذف.

## المشكلة التي تحلها
`job_state.json` يخزّن **المسار المطلق** لكل صورة أصلية وقت الدفعة
(`result.items[].source_path`) ومسار ملف الإكسل (`catalog_path`).
عند «حفظ واعتماد التعديل» أو «ربط الصنف بالرقم» يعود المحرك إلى المسار
المخزَّن؛ فإذا نُقلت الصور أو حُذفت أو تغيّر حرف القرص أو استُعيدت جلسة
قديمة يرتفع ``FileNotFoundError`` فتظهر للمالك رسالة عامة:
«تعذر العثور على أحد ملفات المهمة».

## الحل
1. **إيداع**: عند بدء الدفعة تُودَع كل صورة مصدر في
   ``<workspace>/source_vault/`` بربط صلب (hardlink) إن أمكن — تكلفة
   صفرية على نفس القرص — وإلا بنسخ فعلي. كما تُودَع نسخة من ملف الإكسل.
2. **استرجاع**: قبل أي تعديل فردي/ربط يدوي يُفحص `job_state.json`، وكل
   مسار مفقود يُستعاد من الخزانة أو يُعاد اكتشافه بالبحث في مجلدات
   مرشَّحة، ثم تُحدَّث الحالة كتابةً ذرّية.
3. **بصمة**: تُحفظ بصمة (الحجم + sha1 لأول 256KB) لكل مصدر في
   ``vault_manifest.json`` كي يصحّ الاسترجاع حتى لو تغيّر اسم الملف.

الوحدة **مستقلة تمامًا** عن Qt وعن `pipeline`، فتصلح للاختبار المباشر.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

VAULT_DIRNAME = "source_vault"
MANIFEST_NAME = "vault_manifest.json"
CATALOG_SNAPSHOT_NAME = "catalog_snapshot"
STATE_NAME = "job_state.json"

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
_FINGERPRINT_BYTES = 256 * 1024


# --------------------------------------------------------------- بصمة الملف
def fingerprint(path: str | Path) -> str:
    """بصمة رخيصة وحاسمة عمليًا: الحجم + sha1 لأول 256KB.

    لا نقرأ الملف كاملًا لأن الدفعة قد تحتوي آلاف الصور بأحجام كبيرة،
    واحتمال تصادم (نفس الحجم + نفس أول 256KB) لصورتين مختلفتين مهمل.
    """
    p = Path(path)
    try:
        size = p.stat().st_size
    except OSError:
        return ""
    digest = hashlib.sha1()
    digest.update(str(size).encode("ascii"))
    try:
        with p.open("rb") as handle:
            digest.update(handle.read(_FINGERPRINT_BYTES))
    except OSError:
        return ""
    return digest.hexdigest()


def _atomic_write_json(path: str | Path, payload: dict) -> None:
    """كتابة ذرّية: ملف مؤقت في نفس المجلد ثم os.replace.

    يمنع تلف `job_state.json` إذا انقطع التطبيق أثناء الكتابة — وهو
    خطر حقيقي لأن الحالة تُحدَّث بعد كل تعديل فردي.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent),
        prefix=path.name + ".", suffix=".tmp", delete=False)
    try:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    finally:
        handle.close()
    os.replace(handle.name, str(path))


def _link_or_copy(source: Path, target: Path) -> bool:
    """ربط صلب إن أمكن (بلا تكلفة مساحة) وإلا نسخ فعلي."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return True
    try:
        os.link(str(source), str(target))
        return True
    except (OSError, NotImplementedError, AttributeError):
        pass
    try:
        shutil.copy2(str(source), str(target))
        return True
    except OSError:
        return False


# ------------------------------------------------------------------ الخزانة
def entry_key(path: str | Path) -> str:
    r"""مفتاح المدخل: المسار المطلق المُطبّع لا اسم الملف.

    2.9.7 (إصلاح فقد صور): كان المفتاح اسم الملف، فصورتان
    مختلفتان تتشاركان الاسم من مجلدين (``A/PHOTO-1.png``
    و ``B/PHOTO-1.png``) تتصادمان في المانيفست وتُطمَس إحداهما
    — فيفقد المالك صورة بلا إنذار. المسار المُطبّع يميّزهما.

    ``normcase`` لأن الويندوز لا يفرق بين حالة الأحرف ويقبل ``/`` و ``\``.
    """
    text = str(path or "").strip()
    if not text:
        return ""
    try:
        resolved = str(Path(text).resolve())
    except (OSError, ValueError, RuntimeError):
        resolved = os.path.abspath(text)
    return os.path.normcase(os.path.normpath(resolved))


@dataclass
class VaultEntry:
    name: str
    vault_name: str
    fingerprint: str
    original_path: str

    @property
    def key(self) -> str:
        """مفتاح هذا المدخل في الخزانة (المسار المُطبّع)."""
        return entry_key(self.original_path)


@dataclass
class SourceVault:
    """خزانة مصادر مساحة عمل واحدة."""

    workspace: Path
    entries: dict[str, VaultEntry] = field(default_factory=dict)

    # --------------------------------------------------------------- مسارات
    def __post_init__(self) -> None:
        self.workspace = Path(self.workspace)

    @property
    def root(self) -> Path:
        return self.workspace / VAULT_DIRNAME

    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST_NAME

    @property
    def state_path(self) -> Path:
        return self.workspace / STATE_NAME

    # ---------------------------------------------------------------- تحميل
    @classmethod
    def load(cls, workspace: str | Path) -> "SourceVault":
        vault = cls(Path(workspace))
        data: dict = {}
        if vault.manifest_path.is_file():
            try:
                data = json.loads(vault.manifest_path.read_text(
                    encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
        for raw in data.get("entries", []) or []:
            try:
                entry = VaultEntry(
                    name=str(raw.get("name") or ""),
                    vault_name=str(raw.get("vault_name") or ""),
                    fingerprint=str(raw.get("fingerprint") or ""),
                    original_path=str(raw.get("original_path") or ""))
            except (TypeError, ValueError):
                continue
            if not entry.name:
                continue
            # 2.9.7: المفتاح المسار المُطبّع. مانيفست قديم بلا مسار
            # أصلي يُفترض بالاسم للتوافق الخلفي فلا تضيع خزانة قديمة.
            key = entry.key or entry.name
            vault.entries[key] = entry
        return vault

    def save(self) -> None:
        payload = {
            "schema_version": 1,
            "entries": [
                {"name": e.name, "vault_name": e.vault_name,
                 "fingerprint": e.fingerprint,
                 "original_path": e.original_path}
                for e in self.entries.values()
            ],
        }
        try:
            _atomic_write_json(self.manifest_path, payload)
        except OSError:
            pass

    # ---------------------------------------------------------------- إيداع
    def deposit(self, paths) -> int:
        """يودع صور المصدر في الخزانة. يعيد عدد المودَع فعليًا."""
        stored = 0
        self.root.mkdir(parents=True, exist_ok=True)
        for raw in paths or []:
            source = Path(str(raw))
            if not source.is_file():
                continue
            name = source.name
            key = entry_key(source)
            existing = self.entries.get(key)
            if existing is None:
                # توافق خلفي: مدخل قديم مفتوح بالاسم وله المسار نفسه
                legacy = self.entries.get(name)
                if legacy is not None and entry_key(
                        legacy.original_path) == key:
                    self.entries.pop(name, None)
                    self.entries[key] = legacy
                    existing = legacy
            if existing and (self.root / existing.vault_name).is_file():
                # مودَع مسبقًا؛ حدّث المسار الأصلي فقط
                existing.original_path = str(source)
                continue
            vault_name = self._unique_vault_name(name, key)
            target = self.root / vault_name
            if _link_or_copy(source, target):
                self.entries[key] = VaultEntry(
                    name=name, vault_name=vault_name,
                    fingerprint=fingerprint(source),
                    original_path=str(source))
                stored += 1
        self.save()
        return stored

    def _unique_vault_name(self, name: str, key: str = "") -> str:
        """اسم فريد داخل الخزانة (صورتان بنفس الاسم من مجلدين مختلفين)."""
        candidate = name
        stem = Path(name).stem
        suffix = Path(name).suffix
        index = 1
        used = {e.vault_name for e in self.entries.values()}
        while candidate in used or (self.root / candidate).exists():
            existing = self.entries.get(key or name)
            if existing and existing.vault_name == candidate:
                return candidate
            candidate = f"{stem}~{index}{suffix}"
            index += 1
        return candidate

    def deposit_catalog(self, catalog_path: str | Path) -> str:
        """يودع نسخة من ملف الإكسل ويعيد مسار النسخة (أو "")."""
        source = Path(str(catalog_path))
        if not source.is_file():
            return ""
        target = self.root / (CATALOG_SNAPSHOT_NAME + source.suffix.lower())
        self.root.mkdir(parents=True, exist_ok=True)
        if target.is_file():
            return str(target)
        return str(target) if _link_or_copy(source, target) else ""

    def catalog_snapshot(self) -> str:
        """مسار نسخة الإكسل المودعة إن وُجدت."""
        if not self.root.is_dir():
            return ""
        for candidate in sorted(self.root.glob(CATALOG_SNAPSHOT_NAME + ".*")):
            if candidate.is_file():
                return str(candidate)
        return ""

    # ------------------------------------------------------------- استرجاع
    def resolve(self, source_name: str, recorded_path: str = "",
                extra_dirs=None) -> str:
        """يعيد مسارًا موجودًا فعليًا لهذا المصدر، أو "" إذا تعذّر.

        ترتيب البحث: المسار المسجَّل ← الخزانة ← مجلد المسار المسجَّل
        ← مجلدات إضافية يمررها المتصل (المجلد الحالي المختار مثلًا).
        """
        if recorded_path and Path(recorded_path).is_file():
            return str(recorded_path)
        name = str(source_name or "").strip()
        # 2.9.7: المفتاح المسار المُطبّع؛ والمستدعون قد يمررون
        # اسمًا فقط — فالبحث تدريجي: المسار المسجل ⇐ الاسم
        # ⇐ مفتاح قديم مباشر، لكي يعمل مع النوعين.
        entry = None
        if recorded_path:
            entry = self.entries.get(entry_key(recorded_path))
        if entry is None and name:
            entry = self.entries.get(name)
        if entry is None and name:
            for candidate_entry in self.entries.values():
                if candidate_entry.name == name:
                    entry = candidate_entry
                    break
        if entry:
            candidate = self.root / entry.vault_name
            if candidate.is_file():
                return str(candidate)
        # الخزانة قد تحتوي الملف بلا مانيفست (مانيفست تالف)
        if name:
            candidate = self.root / name
            if candidate.is_file():
                return str(candidate)
        search_dirs: list[Path] = []
        if recorded_path:
            parent = Path(recorded_path).parent
            if parent.is_dir():
                search_dirs.append(parent)
        for raw in extra_dirs or []:
            directory = Path(str(raw))
            if directory.is_dir():
                search_dirs.append(directory)
        for directory in search_dirs:
            if not name:
                continue
            candidate = directory / name
            if candidate.is_file():
                return str(candidate)
        # آخر محاولة: مطابقة البصمة داخل المجلدات المرشحة
        wanted = entry.fingerprint if entry else ""
        if wanted:
            for directory in search_dirs:
                for candidate in directory.iterdir():
                    if not candidate.is_file():
                        continue
                    if candidate.suffix.lower() not in IMAGE_EXTS:
                        continue
                    if fingerprint(candidate) == wanted:
                        return str(candidate)
        return ""


# --------------------------------------------------- إصلاح حالة المهمة
@dataclass
class RepairReport:
    """تقرير إصلاح مسارات الحالة."""

    repaired: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    catalog_repaired: bool = False
    catalog_missing: bool = False
    state_written: bool = False

    @property
    def ok(self) -> bool:
        """هل كل المصادر متاحة الآن؟"""
        return not self.missing

    def summary_ar(self) -> str:
        parts: list[str] = []
        if self.repaired:
            parts.append(f"استُعيد مسار {len(self.repaired)} صورة")
        if self.catalog_repaired:
            parts.append("استُعيد ملف الإكسل من النسخة المحفوظة")
        if self.missing:
            names = "، ".join(self.missing[:5])
            more = "" if len(self.missing) <= 5 else \
                f" و{len(self.missing) - 5} أخرى"
            parts.append(f"تعذر العثور على: {names}{more}")
        return " — ".join(parts)


def repair_job_state(workspace: str | Path, extra_dirs=None) -> RepairReport:
    """يفحص `job_state.json` ويستعيد كل مسار مفقود.

    يُنفَّذ قبل أي تعديل فردي أو ربط يدوي. لا يرفع استثناءً أبدًا؛ يعيد
    تقريرًا كي تستطيع الواجهة عرض رسالة دقيقة تسمّي الملف المفقود.
    """
    report = RepairReport()
    workspace = Path(workspace)
    vault = SourceVault.load(workspace)
    state_path = vault.state_path
    if not state_path.is_file():
        return report
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return report
    if not isinstance(state, dict):
        return report

    changed = False
    result = state.get("result")
    items = (result or {}).get("items") if isinstance(result, dict) else None
    for item in items or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("source_name") or "")
        recorded = str(item.get("source_path") or "")
        if recorded and Path(recorded).is_file():
            continue
        resolved = vault.resolve(name, recorded, extra_dirs=extra_dirs)
        if resolved:
            item["source_path"] = resolved
            # review_path يشير عادةً لنفس الملف الأصلي
            review = str(item.get("review_path") or "")
            if review and not Path(review).is_file() and \
                    Path(review).name == name:
                item["review_path"] = resolved
            report.repaired.append(name or recorded)
            changed = True
        else:
            report.missing.append(name or recorded)

    catalog = str(state.get("catalog_path") or "")
    if catalog and not Path(catalog).is_file():
        snapshot = vault.catalog_snapshot()
        if snapshot:
            state["catalog_path"] = snapshot
            report.catalog_repaired = True
            changed = True
        else:
            report.catalog_missing = True

    if changed:
        try:
            _atomic_write_json(state_path, state)
            report.state_written = True
        except OSError:
            pass
    return report


def deposit_job_sources(workspace: str | Path, image_paths,
                        catalog_path: str | Path = "") -> int:
    """تُستدعى عند بدء الدفعة: تودع الصور والإكسل في الخزانة."""
    vault = SourceVault.load(workspace)
    stored = vault.deposit(image_paths)
    if catalog_path:
        vault.deposit_catalog(catalog_path)
    return stored


def missing_sources(workspace: str | Path) -> list[str]:
    """أسماء المصادر المفقودة فعليًا (بعد محاولة الاسترجاع)."""
    report = repair_job_state(workspace)
    return list(report.missing)
