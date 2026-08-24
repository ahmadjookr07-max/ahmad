# -*- coding: utf-8 -*-
"""session_v2 — حفظ واستئناف الجلسات (Save & Resume) — نسخة 2.2 موسعة.

SessionStore يحفظ حالة كل صورة (الربط، الاسم المخصص، حالة الاعتماد،
موضع المستخدم في الجدول) وكذلك حالة صفحة الإعداد (ملف الإكسل وقائمة
الصور المختارة والخيارات) في JSON تحت data_root/sessions/ حتى يمكن
العودة للعمل من حيث توقف المستخدم حتى قبل بدء المعالجة.

الكتابة ذرّية (tmp ثم replace) لمنع تلف ملف الجلسة عند انقطاع الطاقة.
"""
from __future__ import annotations

import json
import ntpath
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _normalise_identity_path(value: str) -> str:
    """يطبع مسارًا لمفتاح جلسة فقط، بلا لمس لمسار الملف المحفوظ.

    Windows لا يفرّق بين حالة الأحرف أو ``\\`` و``/``، بينما قد تصل
    الجلسة من إصدار قديم بمسار فيه ``..`` أو بفواصل مختلفة. هذا التطبيع
    يمنع أن تصبح الصورة نفسها سجلين. لا نحول المسار النسبي إلى مطلق، لأن
    موضع تشغيل التطبيق لا يكفي وحده لتحديد جذره بأمان.
    """
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    return os.path.normpath(raw).replace("\\", "/").casefold()


def image_identity_key(source_path: str = "", source_name: str = "",
                       output_path: str = "", match_source: str = "") -> str:
    """مفتاح جلسة ثابت للصورة، مستقل تمامًا عن الباركود ورقم الصنف.

    قد تظهر عدة صور للباركود نفسه أو حتى تحمل الاسم المجرد نفسه في
    مجلدات مختلفة. مسار المصدر هو الهوية الأقوى؛ الاسم لا يُستخدم إلا
    عندما يغيب المسار. البادئة تمنع التباس اسم ملف مع مسار كامل.
    """
    # اقتصاص التغذية يشارك source_path مع المنتج لكنه كيان مستقل؛ مخرجه
    # هو الهوية الوحيدة التي تمنع فقد الصف عند حفظ الجلسة أو استعادتها.
    if str(match_source or "").strip().casefold() == "nutrition_crop":
        output = _normalise_identity_path(output_path)
        if output:
            return "output:" + output
    path = _normalise_identity_path(source_path)
    if path:
        return "path:" + path
    name = _normalise_identity_path(source_name)
    return "name:" + name if name else ""


def _entry_value(entry: dict[str, Any], name: str) -> str:
    """يقرأ الحقول الحديثة أو ``raw`` في ملفات الجلسات القديمة."""
    value = entry.get(name, "")
    if value not in (None, ""):
        return str(value)
    raw = entry.get("raw")
    if isinstance(raw, dict):
        return str(raw.get(name, "") or "")
    return ""


def _is_absolute_like(path: str) -> bool:
    value = str(path or "")
    return os.path.isabs(value) or ntpath.isabs(value)


def _join_identity_root(root: str, value: str) -> str:
    """يربط نسبيًا بجذر معروف مع دعم مسارات Windows في أي منصة اختبار."""
    raw_root = str(root or "").strip()
    raw_value = str(value or "").strip()
    if not raw_root or not raw_value or _is_absolute_like(raw_value):
        return raw_value
    if ntpath.isabs(raw_root):
        return ntpath.normpath(ntpath.join(raw_root, raw_value))
    return os.path.normpath(os.path.join(raw_root, raw_value))


def canonical_image_key(key: str, entry: dict[str, Any] | None = None,
                        source_root: str = "", output_root: str = "") -> str:
    """يعيد المفتاح القانوني لسجل حديث أو قديم دون تخمين صورة شقيقة.

    لا نستعمل الباركود أو رقم الصنف أو اسم المنتج مطلقًا. لا يدمج هذا
    إلا سجلات تشترك في **مسار المصدر نفسه** (أو مخرج crop التغذية نفسه)،
    بينما تبقى الصور المتشابهة في الاسم ضمن مجلدات مختلفة مستقلة. وإذا
    عُرف جذر الجلسة، تتحد نسخة المسار النسبي والمطلق للصورة ذاتها فقط.
    """
    item = entry if isinstance(entry, dict) else {}
    source_path = _join_identity_root(source_root, _entry_value(item, "source_path"))
    source_name = _entry_value(item, "source_name")
    output_path = _join_identity_root(output_root, _entry_value(item, "output_path"))
    match_source = _entry_value(item, "match_source")
    canonical = image_identity_key(source_path, source_name,
                                   output_path, match_source)
    if canonical:
        return canonical

    legacy = str(key or "").strip()
    folded = legacy.casefold()
    if folded.startswith("path:"):
        return "path:" + _normalise_identity_path(
            _join_identity_root(source_root, legacy[5:]))
    if folded.startswith("output:"):
        return "output:" + _normalise_identity_path(
            _join_identity_root(output_root, legacy[7:]))
    if folded.startswith("name:"):
        return "name:" + _normalise_identity_path(legacy[5:])
    # بعض الإصدارات السابقة استخدمت مسار المصدر نفسه مفتاحًا بلا بادئة.
    if any(mark in legacy for mark in ("/", "\\", ":")):
        return image_identity_key(legacy, "", "", "")
    return image_identity_key("", legacy, "", "")


def _is_empty_value(value: Any) -> bool:
    return value is None or value == "" or value == () or value == [] or value == {}


def _entry_rank(original_key: str, canonical_key: str,
                entry: dict[str, Any]) -> tuple[int, int, int, int, int]:
    """يرجّح السجل القانوني والأكثر اكتمالًا عند دمج alias قديم."""
    status = str(_entry_value(entry, "status")).strip().casefold()
    return (
        int(str(original_key or "") == canonical_key),
        int(bool(_entry_value(entry, "source_path"))),
        int(bool(_entry_value(entry, "output_path"))),
        int(status not in ("", "pending", "review")),
        len(entry),
    )


def _merge_image_entries(canonical_key: str,
                         candidates: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    """يدمج aliases للسجل نفسه مع تقديم السجل الأقوى وحفظ كل الحقول."""
    ordered = sorted(
        candidates,
        key=lambda pair: _entry_rank(pair[0], canonical_key, pair[1]),
    )
    merged: dict[str, Any] = {}
    raw_merged: dict[str, Any] = {}
    approved = False
    # الترتيب من الأضعف إلى الأقوى يجعل القيم الأكمل/القانونية تتقدم عند
    # التعارض، بينما لا تضيع الحقول التي لم تكن موجودة في السجل الأحدث.
    for _, entry in ordered:
        for field, value in entry.items():
            if field == "raw" and isinstance(value, dict):
                raw_merged.update(dict(value))
                continue
            if field == "approved":
                approved = approved or bool(value)
                continue
            if field not in merged or _is_empty_value(merged.get(field)):
                merged[field] = value
            elif not _is_empty_value(value):
                merged[field] = value
    if raw_merged:
        for field, value in merged.items():
            if field != "raw" and not _is_empty_value(value):
                raw_merged[field] = value
        merged["raw"] = raw_merged
    if approved:
        merged["approved"] = True
    # تحفظ هوية المصدر الصريحة حتى لا يعود السجل إلى name: في حفظ لاحق.
    if canonical_key.startswith("path:") and not _entry_value(merged, "source_path"):
        merged["source_path"] = canonical_key[5:]
    if canonical_key.startswith("output:") and not _entry_value(merged, "output_path"):
        merged["output_path"] = canonical_key[7:]
    return merged


def canonicalize_session_state(state: Any) -> bool:
    """يهاجر حالة جلسة إلى مفاتيح قانونية دون فقد العمل أو مضاعفة الصفوف.

    الدالة idempotent: تشغيلها مرارًا لا يغير النتيجة بعد أول ترحيل. وهي
    تستبقي crops التغذية ككيانات مستقلة، وترحل مفاتيح الاعتماد والموضع
    المرتبطة بالمفاتيح القديمة إلى المفتاح القانوني نفسه.
    """
    images = getattr(state, "images", None)
    if not isinstance(images, dict):
        return False

    setup = getattr(state, "setup", {})
    safe_setup = setup if isinstance(setup, dict) else {}
    source_root = str(getattr(state, "source_folder", "") or
                      safe_setup.get("source_folder", "") or "")
    output_root = str(getattr(state, "output_folder", "") or "")

    groups: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    key_map: dict[str, str] = {}
    name_targets: dict[str, set[str]] = {}
    for original_key, original_entry in images.items():
        entry = dict(original_entry) if isinstance(original_entry, dict) else {}
        canonical = canonical_image_key(
            str(original_key), entry, source_root, output_root)
        if not canonical:
            # لا نحذف سجلاً غامضًا: نحفظه تحت مفتاح منعزل بدلاً من خلطه.
            canonical = "legacy:" + _normalise_identity_path(str(original_key))
        groups.setdefault(canonical, []).append((str(original_key), entry))
        key_map[str(original_key)] = canonical
        source_name = _entry_value(entry, "source_name")
        if source_name:
            name_targets.setdefault(_normalise_identity_path(source_name), set()).add(canonical)

    migrated: dict[str, dict[str, Any]] = {}
    for canonical, candidates in groups.items():
        migrated[canonical] = _merge_image_entries(canonical, candidates)

    approved = getattr(state, "approved", {})
    migrated_approved: dict[str, Any] = {}
    if isinstance(approved, dict):
        for legacy_key, value in approved.items():
            target = key_map.get(str(legacy_key))
            if target is None:
                targets = name_targets.get(_normalise_identity_path(str(legacy_key)), set())
                if len(targets) == 1:
                    target = next(iter(targets))
            # لا نمحو اعتمادًا غامضًا من جلسة قديمة؛ يبقى كبيان احتياطي.
            target = target or str(legacy_key)
            if value:
                migrated_approved[target] = True
                if target in migrated:
                    migrated[target]["approved"] = True

    position = getattr(state, "position", {})
    migrated_position = dict(position) if isinstance(position, dict) else {}
    old_position_key = str(migrated_position.get("source_key", "") or "")
    if old_position_key:
        target = key_map.get(old_position_key)
        if target is None:
            targets = name_targets.get(_normalise_identity_path(old_position_key), set())
            if len(targets) == 1:
                target = next(iter(targets))
        if target:
            migrated_position["source_key"] = target

    migrated_setup = dict(safe_setup)
    paths = migrated_setup.get("image_paths")
    if isinstance(paths, list):
        seen_paths: set[str] = set()
        unique_paths: list[Any] = []
        for path in paths:
            norm = _normalise_identity_path(str(path))
            if not norm or norm in seen_paths:
                continue
            seen_paths.add(norm)
            unique_paths.append(path)
        migrated_setup["image_paths"] = unique_paths

    changed = (images != migrated or
               (isinstance(approved, dict) and approved != migrated_approved) or
               (isinstance(position, dict) and position != migrated_position) or
               (isinstance(setup, dict) and setup != migrated_setup))
    if changed:
        state.images = migrated
        if isinstance(approved, dict):
            state.approved = migrated_approved
        if isinstance(position, dict):
            state.position = migrated_position
        if isinstance(setup, dict):
            state.setup = migrated_setup
    return changed


@dataclass
class SessionState:
    session_id: str = ""
    title: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    excel_path: str = ""
    source_folder: str = ""
    output_folder: str = ""
    images: dict = field(default_factory=dict)   # key=هوية مسار المصدر -> dict
    position: dict = field(default_factory=dict)  # {source_name,row,col}
    # --- جديد 2.2 ---
    setup: dict = field(default_factory=dict)     # حالة صفحة الإعداد كاملة
    approved: dict = field(default_factory=dict)  # source_name -> True للمعتمد
    phase: str = ""                               # setup | results

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id, "title": self.title,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "excel_path": self.excel_path, "source_folder": self.source_folder,
            "output_folder": self.output_folder, "images": self.images,
            "position": self.position, "setup": self.setup,
            "approved": self.approved, "phase": self.phase,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SessionState":
        s = cls()
        for k in ("session_id", "title", "excel_path", "source_folder",
                  "output_folder", "phase"):
            setattr(s, k, d.get(k, ""))
        s.created_at = d.get("created_at", 0.0)
        s.updated_at = d.get("updated_at", 0.0)
        s.images = d.get("images", {}) or {}
        s.position = d.get("position", {}) or {}
        s.setup = d.get("setup", {}) or {}
        s.approved = d.get("approved", {}) or {}
        return s

    # -------------------------------------------------------- helpers
    def done_count(self) -> int:
        done = 0
        for v in self.images.values():
            st = str(v.get("status", ""))
            if st in ("matched", "done", "approved") or \
                    v.get("approved"):
                done += 1
        return done

    def mark_approved(self, key: str, value: bool = True) -> None:
        if value:
            self.approved[key] = True
            entry = self.images.setdefault(key, {})
            entry["approved"] = True
        else:
            self.approved.pop(key, None)
            if key in self.images:
                self.images[key].pop("approved", None)

    def is_approved(self, key: str) -> bool:
        return bool(self.approved.get(key)) or \
            bool(self.images.get(key, {}).get("approved"))


class SessionStore:
    """مخزن الجلسات على القرص."""

    def __init__(self, data_root: str | Path):
        self.root = Path(data_root) / "sessions"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state = SessionState()
        self._last_save = 0.0

    # ------------------------------------------------------------ manage
    def new_session(self, title: str = "") -> SessionState:
        self.state = SessionState(
            session_id=uuid.uuid4().hex[:12],
            title=title or time.strftime("جلسة %Y-%m-%d %H:%M"),
            created_at=time.time(), updated_at=time.time())
        return self.state

    def ensure_session(self, title: str = "") -> SessionState:
        """يضمن وجود جلسة حالية (ينشئها إن لم توجد) — تُستخدم قبل أي حفظ."""
        if not self.state.session_id:
            self.new_session(title)
        return self.state

    def _path(self, sid: str) -> Path:
        return self.root / f"{sid}.json"

    def canonicalize_images(self, state: SessionState | None = None) -> bool:
        """يوحّد aliases القديمة قبل العرض أو الكتابة على القرص."""
        return canonicalize_session_state(state or self.state)

    def save(self, force: bool = False) -> bool:
        if not self.state.session_id:
            return False
        # لا تكتب ملفًا يحوي نسخة path: وأخرى name: للصورة نفسها.
        self.canonicalize_images()
        now = time.time()
        if not force and now - self._last_save < 2.0:
            return False
        self.state.updated_at = now
        try:
            final = self._path(self.state.session_id)
            tmp = final.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(self.state.to_dict(), ensure_ascii=False),
                encoding="utf-8")
            os.replace(tmp, final)  # كتابة ذرّية — لا ملفات جلسات تالفة
            self._last_save = now
            return True
        except OSError:
            return False

    def load(self, sid: str) -> SessionState | None:
        p = self._path(sid)
        if not p.is_file():
            return None
        try:
            self.state = SessionState.from_dict(
                json.loads(p.read_text(encoding="utf-8")))
            # تُعرض الجلسات القديمة بصورة سليمة حتى قبل أول تعديل يدوي، ثم
            # نكتب الترحيل الذرّي مرة واحدة كي لا تعود aliases في فتح لاحق.
            if self.canonicalize_images():
                self.save(force=True)
            return self.state
        except Exception:
            return None

    def delete(self, sid: str) -> bool:
        try:
            self._path(sid).unlink(missing_ok=True)
            return True
        except OSError:
            return False

    def list_sessions(self) -> list[dict]:
        out = []
        for p in sorted(self.root.glob("*.json"),
                        key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                images = d.get("images", {}) or {}
                setup = d.get("setup", {}) or {}
                src = d.get("source_folder", "") or \
                    setup.get("source_folder", "") or \
                    d.get("output_folder", "") or \
                    (setup.get("image_paths", [""]) or [""])[0]
                state = SessionState.from_dict(d)
                out.append({
                    "session_id": d.get("session_id", p.stem),
                    "title": d.get("title", p.stem),
                    "updated_at": d.get("updated_at", 0.0),
                    "image_count": len(images),
                    # المفاتيح التي يعرضها SessionDialog
                    "source_folder": src,
                    "total": len(images) or
                    len(setup.get("image_paths", []) or []),
                    "done": state.done_count(),
                    "phase": d.get("phase", ""),
                })
            except Exception:
                continue
        return out

    # ------------------------------------------------------------ images
    def upsert_image(self, key: str, **fields) -> None:
        # حتى منادٍ قديم يمرر source_name كمفتاح لا يستطيع إنشاء سجل ثانٍ
        # متى كان source_path أو output_path متاحًا في الحقول.
        canonical = canonical_image_key(key, fields)
        entry = self.state.images.setdefault(canonical or key, {})
        entry.update(fields)

    def set_position(self, source_name: str, row: int, col: int = 0) -> None:
        self.state.position = {"source_name": source_name,
                               "row": row, "col": col}
