#!/usr/bin/env python3
"""تصنيف العلل التي يشخّصها الجرّاح، لمعرفة ما نواجه قبل أي إصلاح.

يطبع توزيعًا بالرمز والخطورة والملف، ويحفظ التفصيل في JSON.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from src.awareness import surgeon  # noqa: E402


def main() -> int:
    issues = surgeon.diagnose()
    print(f"عدد العلل: {len(issues)}")
    if not issues:
        return 0

    first = issues[0]
    print(f"\nحقول العلّة: {list(vars(first).keys())}")
    print(f"مثال: {vars(first)}")

    by_code: Counter = Counter()
    by_sev: Counter = Counter()
    by_file: Counter = Counter()
    fixable = 0
    detail = defaultdict(list)

    for it in issues:
        d = vars(it)
        code = d.get("code", "?")
        sev = d.get("severity", "?")
        sev = getattr(sev, "value", sev)
        path = d.get("path") or d.get("file") or "?"
        rel = os.path.relpath(str(path), ROOT) if path != "?" else "?"
        by_code[code] += 1
        by_sev[str(sev)] += 1
        by_file[rel] += 1
        if code in surgeon.TRANSFORMS:
            fixable += 1
        detail[code].append(
            {
                "file": rel,
                "line": d.get("line") or d.get("lineno"),
                "severity": str(sev),
                "message": d.get("message") or d.get("detail") or "",
            }
        )

    print("\n=== بالرمز ===")
    for code, n in by_code.most_common():
        mark = "قابل للإصلاح آليًا" if code in surgeon.TRANSFORMS else "يدوي"
        print(f"{n:4d}  {code:32s} {mark}")

    print("\n=== بالخطورة ===")
    for sev, n in by_sev.most_common():
        print(f"{n:4d}  {sev}")

    print("\n=== أكثر 15 ملفًا ===")
    for f, n in by_file.most_common(15):
        print(f"{n:4d}  {f}")

    print(f"\nمحوّلات آلية متاحة: {sorted(surgeon.TRANSFORMS.keys())}")
    print(f"علل قابلة للإصلاح آليًا: {fixable} من {len(issues)}")

    out = os.path.join(ROOT, "tools", "_issues_triage.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "total": len(issues),
                "by_code": dict(by_code),
                "by_severity": dict(by_sev),
                "by_file": dict(by_file),
                "auto_fixable": fixable,
                "transforms": sorted(surgeon.TRANSFORMS.keys()),
                "detail": {k: v for k, v in detail.items()},
            },
            fh,
            ensure_ascii=False,
            indent=2,
        )
    print(f"\nحُفظ التفصيل في {os.path.relpath(out, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
