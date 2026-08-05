#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""حاجز: لا اسم غير معرّف في أي ملف بايثون في المشروع.

سبب وجوده — عطب 2.9.11: ``windows_app/native_app.py`` كان يستعمل
``json.loads`` و``json.dumps`` في دالتَي حفظ واستعادة سياسة التسمية
بينما ``import json`` غير موجود في الملف إطلاقًا. النتيجة أن كل محاولة
حفظ لخيار الوحدات تفشل بـ ``NameError: name 'json' is not defined``،
ودالة الاستعادة تنفجر بالمثل لكنها **تكتم الاستثناء** وتطبع في stderr
غير المرئي ثم تُكمل بسياسة فارغة — فيعود التطبيق إلى الوحدة الواحدة عند
كل تشغيل، ويظل خيار المالك بلا أثر أبدًا.

الحزمة القائمة لم تُمسك العطب لأنها تختبر محرك التسمية مباشرة ولا تمرّ
على طبقة الواجهة. هذا الحاجز يفحص المشروع كله ساكنًا، فيمسك هذا الصنف
من الأعطاب (استيراد ناقص، اسم مكتوب خطأ) قبل أن يصل إلى المالك.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "build", "dist", "__pycache__", ".venv", "venv"}


def _py_files() -> list[Path]:
    out: list[Path] = []
    for p in ROOT.rglob("*.py"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        out.append(p)
    return sorted(out)


def main() -> int:
    files = _py_files()
    if not files:
        print("فشل: لم يُعثر على ملفات بايثون للفحص")
        return 1
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pyflakes", *[str(f) for f in files]],
            capture_output=True, text=True, timeout=600)
    except FileNotFoundError:
        print("تخطٍّ: pyflakes غير مثبّت")
        return 0
    except subprocess.TimeoutExpired:
        print("فشل: انتهت مهلة الفحص الساكن")
        return 1
    if proc.returncode != 0 and not (proc.stdout or proc.stderr):
        print("تخطٍّ: pyflakes غير متاح")
        return 0

    lines = [ln for ln in (proc.stdout or "").splitlines()
             if "undefined name" in ln]
    print(f"فُحص {len(files)} ملف بايثون")
    if lines:
        print(f"فشل: {len(lines)} اسم غير معرّف — كل واحد منها عطب "
              f"وقت تشغيل ينفجر عند أول استدعاء:")
        for ln in lines[:40]:
            print(f"   {ln}")
        return 1
    print("نجح: لا اسم غير معرّف في المشروع")
    return 0


if __name__ == "__main__":
    sys.exit(main())
