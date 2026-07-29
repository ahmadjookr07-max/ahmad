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
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SessionState:
    session_id: str = ""
    title: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    excel_path: str = ""
    source_folder: str = ""
    output_folder: str = ""
    images: dict = field(default_factory=dict)   # key=source_name -> dict
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

    def save(self, force: bool = False) -> bool:
        if not self.state.session_id:
            return False
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
        entry = self.state.images.setdefault(key, {})
        entry.update(fields)

    def set_position(self, source_name: str, row: int, col: int = 0) -> None:
        self.state.position = {"source_name": source_name,
                               "row": row, "col": col}
