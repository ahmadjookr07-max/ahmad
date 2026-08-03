#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""محاكاة جافة لرقع الاستثناء الصامت — معاينة قبل لمس كود يعمل.

الغرض: رؤية النص المُعدَّل فعلًا (لا تخمينه من قراءة المحوّل) قبل تطبيق
105 تعديلات على وحدات محرّك ومنظومة واجهة تعمل.

يفحص لكل ملف: هل تُحلَّل الرقعة نحويًا، وهل تجتاز بوابة المعنى، وما
شكل الفرق الفعلي في أول موضعين.
"""
from __future__ import annotations

import ast
import difflib
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("MIS_HEADLESS", "1")

from awareness.surgeon import TRANSFORMS, Surgeon  # noqa: E402

SHOW_DIFF_FOR = int(os.environ.get("SHOW_DIFF_FOR", "2"))


def main() -> int:
    s = Surgeon()
    issues = [i for i in s.diagnose() if i.code == "silent_except"]
    by_file: dict[str, list] = {}
    for i in issues:
        by_file.setdefault(i.path, []).append(i)

    print(f"علل الاستثناء الصامت: {len(issues)} في {len(by_file)} ملف\n")
    print("الملفات الأكثر تضررًا:")
    for path, items in sorted(by_file.items(), key=lambda kv: -len(kv[1]))[:8]:
        print(f"  {len(items):3d}  {path}")

    fn = TRANSFORMS["log_silent_except"]
    stats = Counter()
    problems: list[str] = []
    shown = 0

    print("\n" + "=" * 66)
    print("المحاكاة الجافة لكل ملف")
    print("=" * 66)

    for path, items in sorted(by_file.items(), key=lambda kv: -len(kv[1])):
        src_path = ROOT / path
        try:
            old = src_path.read_text(encoding="utf-8")
        except Exception as exc:
            problems.append(f"{path}: تعذّرت القراءة ({exc})")
            stats["read_error"] += 1
            continue

        new, note = fn(old, items)
        if new == old:
            stats["no_change"] += 1
            problems.append(f"{path}: المحوّل لم يُغيّر شيئًا رغم {len(items)} علّة")
            continue

        # 1) بوابة النحو
        try:
            ast.parse(new)
        except SyntaxError as exc:
            stats["syntax_broken"] += 1
            problems.append(f"{path}: نحو معطوب سطر {exc.lineno} — {exc.msg}")
            continue

        # 2) بوابة المعنى
        ok, why = s._semantics_preserved(old, new)
        if not ok:
            stats["semantics_failed"] += 1
            problems.append(f"{path}: بوابة المعنى رفضت — {why[:100]}")
            continue

        # 3) فحص إضافي: pass ميت حقيقيًا بعد التسجيل.
        #
        # يُستبعد pass الحامي للتسجيل نفسه (داخل
        # ``except Exception:`` التابع مباشرةً لـ``_j.debug``) لأنه مقصود:
        # التسجيل لا يجوز أن يُنشئ عطلًا جديدًا أبدًا.
        dead = 0
        nl = new.splitlines()
        for k, line in enumerate(nl):
            if line.strip() != "pass":
                continue
            prev = nl[k - 1].strip() if k else ""
            prev2 = nl[k - 2].strip() if k >= 2 else ""
            if prev.startswith("except") and "_j.debug" in prev2:
                continue                       # pass الحامي: مقصود
            if "_j.debug" in "\n".join(nl[max(0, k - 5):k]):
                dead += 1

        stats["clean"] += 1
        if dead:
            stats["dead_pass"] += dead

        if shown < SHOW_DIFF_FOR:
            shown += 1
            print(f"\n--- {path} ({len(items)} علّة) ---")
            print(f"    {note[:120]}")
            diff = list(difflib.unified_diff(
                old.splitlines(), new.splitlines(),
                fromfile="قبل", tofile="بعد", lineterm="", n=3))
            for line in diff[:34]:
                print("   " + line)
            if len(diff) > 34:
                print(f"   ... ({len(diff) - 34} سطر فرق إضافي)")

    print("\n" + "=" * 66)
    print("الخلاصة")
    print("=" * 66)
    for k, v in stats.most_common():
        print(f"  {k}: {v}")
    if problems:
        print(f"\nمشكلات ({len(problems)}):")
        for p in problems[:15]:
            print("  •", p)
    else:
        print("\nلا مشكلات: كل الرقع تجتاز النحو والمعنى.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
