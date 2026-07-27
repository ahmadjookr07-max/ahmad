# -*- coding: utf-8 -*-
"""مسارات موارد V2 الموحدة — تعمل في وضع التطوير وفي البناء المجمّع.

ترتيب البحث عن مجلد النماذج:
1. `<MEIPASS>/engine_v2/models` (PyInstaller onedir/onefile — أصول مضمنة)
2. `<exe_dir>/engine_v2/models` (بجوار التنفيذي)
3. `<package_dir>/models` (وضع التطوير: src/engine_v2/models)
4. `/home/ubuntu/v2_project/models_v2` (ساندبوكس التطوير)
"""
from __future__ import annotations

import sys
from pathlib import Path


def _candidates() -> list[Path]:
    here = Path(__file__).resolve().parent
    cands: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        cands.append(Path(meipass) / "engine_v2" / "models")
        cands.append(Path(meipass) / "models_v2")
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        cands.append(exe_dir / "engine_v2" / "models")
        cands.append(exe_dir / "_internal" / "engine_v2" / "models")
    cands.append(here / "models")
    cands.append(Path("/home/ubuntu/v2_project/models_v2"))
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
