#!/usr/bin/env python3
"""محاكاة جافة لعملية الجرّاح: يعاين الرقع دون لمس أي ملف.

الاستخدام:
    python3 tools/surgery_dry_run.py <code> [max_files]

مثال:
    python3 tools/surgery_dry_run.py unguarded_optional_import 20
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from src.awareness import surgeon as sg  # noqa: E402


def _snapshot(paths: list[str]) -> dict[str, float]:
    out = {}
    for p in paths:
        try:
            out[p] = os.path.getmtime(p)
        except OSError:
            pass
    return out


def main() -> int:
    code = sys.argv[1] if len(sys.argv) > 1 else "unguarded_optional_import"
    max_files = int(sys.argv[2]) if len(sys.argv) > 2 else 20

    # بصمة قبل: نُثبت أن المحاكاة الجافة لا تلمس القرص فعلًا
    watch = []
    for base, _dirs, files in os.walk(os.path.join(ROOT, "src")):
        if "__pycache__" in base:
            continue
        for f in files:
            if f.endswith(".py"):
                watch.append(os.path.join(base, f))
    for base, _dirs, files in os.walk(os.path.join(ROOT, "windows_app")):
        if "__pycache__" in base:
            continue
        for f in files:
            if f.endswith(".py"):
                watch.append(os.path.join(base, f))
    before = _snapshot(watch)

    print(f"الرمز: {code} | سقف الملفات: {max_files}")
    print(f"ملفات مرصودة: {len(watch)}\n")

    res = sg.operate(codes=[code], apply=False, max_files=max_files)

    print(f"ok = {res.get('ok')} | applied = {res.get('applied')}")
    print(f"الرسالة: {res.get('message_ar')}\n")
    issues = res.get("issues") or []
    patches = res.get("patches") or []
    print(f"علل مشخّصة: {len(issues)} | رقع مُجهّزة: {len(patches)}")
    if res.get("quarantined"):
        q = res["quarantined"]
        print(f"معزولة: {len(q)} → {q}")

    print("\n=== بوابات التحقق ===")
    for c in res.get("verification") or []:
        mark = "نجحت" if c.get("ok") else "فشلت"
        print(f"  [{mark}] {c.get('gate', c.get('name', '?'))}: "
              f"{c.get('message_ar', '')}")

    print("\n=== الرقع ===")
    for p in patches:
        raw = p.get("path", "?")
        rel = os.path.relpath(str(raw), ROOT) if raw != "?" else "?"
        add = p.get("added", p.get("stats", [0, 0])[0])
        rem = p.get("removed", p.get("stats", [0, 0])[1])
        print(f"\n--- {rel}  (+{add}/-{rem}) ---")
        diff = p.get("diff", "") or ""
        lines = diff.splitlines()
        for ln in lines[:40]:
            print(f"  {ln}")
        if len(lines) > 40:
            print(f"  ... ({len(lines) - 40} سطرًا إضافيًا)")

    after = _snapshot(watch)
    touched = [p for p in before if before.get(p) != after.get(p)]
    print("\n=== إثبات أن المحاكاة جافة ===")
    if touched:
        print(f"خطر: تغيّرت {len(touched)} ملفات! {touched[:5]}")
        return 1
    print(f"لم يُلمَس أي ملف من {len(watch)} ملفًا مرصودًا.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
