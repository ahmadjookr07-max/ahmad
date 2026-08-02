# -*- coding: utf-8 -*-
"""مسارات موارد V2 الموحدة — تعمل في وضع التطوير وفي البناء المجمّع.

ترتيب البحث عن مجلد النماذج:
1. `<MEIPASS>/engine_v2/models` (PyInstaller onedir/onefile — أصول مضمنة)
2. `<exe_dir>/engine_v2/models` (بجوار التنفيذي)
3. `<package_dir>/models` (وضع التطوير: src/engine_v2/models)
4. `<repo_root>/resources/models` (وضع التطوير من المستودع)
5. `MIS_MODELS_DIR` من متغيرات البيئة (تجاوز صريح للاختبارات والتشخيص)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _candidates() -> list[Path]:
    here = Path(__file__).resolve().parent
    cands: list[Path] = []
    override = os.environ.get("MIS_MODELS_DIR", "").strip()
    if override:
        cands.append(Path(override))
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        cands.append(Path(meipass) / "engine_v2" / "models")
        cands.append(Path(meipass) / "models_v2")
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        cands.append(exe_dir / "engine_v2" / "models")
        cands.append(exe_dir / "_internal" / "engine_v2" / "models")
    cands.append(here / "models")
    # جذر المستودع في وضع التطوير: src/engine_v2 -> ../../resources/models
    cands.append(here.parents[1] / "resources" / "models")
    cands.append(here.parents[2] / "resources" / "models")
    return cands


def models_dir() -> str:
    """أول مجلد نماذج موجود فعليًا (أو مسار الحزمة كافتراضي)."""
    for c in _candidates():
        try:
            if c.is_dir() and any(c.glob("*.onnx")):
                return str(c)
        except Exception:
            continue
    return str(Path(__file__).resolve().parent / "models")


def assets_dir() -> str:
    """مجلد أصول المحرك (الخطوط العربية)."""
    here = Path(__file__).resolve().parent
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass and (Path(meipass) / "engine_v2" / "assets").is_dir():
        return str(Path(meipass) / "engine_v2" / "assets")
    return str(here / "assets")
