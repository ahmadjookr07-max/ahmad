#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""يكشف سبب رفض كل رقعة على حدة — لماذا تعارضت المحاكاة مع التحقق الفعلي.

المحاكاة الجافة أجازت 23 ملفًا (نحو + معنى)، لكن التحقق الكامل عزل 7.
الفرق لا بد أن يكون من بوابة الاستيراد أو بوابة الاختبارات، وهذا
السكربت يستنطق كل بوابة على حدة لكل ملف مرفوض.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("MIS_HEADLESS", "1")

from awareness.surgeon import Surgeon  # noqa: E402

TARGETS = sys.argv[1:] or [
    "src/engine_v2/date_blur_v2.py",
    "src/engine_v2/license_v2.py",
    "src/engine_v2/naming_v2.py",
    "src/engine_v2/nutrition_render_v2.py",
    "src/engine_v2/nutrition_smart_v2.py",
    "src/engine_v2/primary_image_v2.py",
    "src/engine_v2/processor_v2.py",
]


def main() -> int:
    s = Surgeon()
    issues = [i for i in s.diagnose() if i.code == "silent_except"]
    patches = s.plan(issues, max_files=40)
    by_path = {str(p.path): p for p in patches}

    print(f"رقع مُخطَّطة: {len(patches)}")
    print(f"مطلوب فحصها: {len(TARGETS)}\n")

    for t in TARGETS:
        p = by_path.get(t)
        print("=" * 66)
        print(t)
        print("=" * 66)
        if p is None:
            print("  لا رقعة مُخطَّطة لهذا الملف (قد يكون خارج الدفعة).")
            continue

        old = (ROOT / t).read_text(encoding="utf-8")
        new = getattr(p, "new_text", None) or getattr(p, "new", "")
        if not new:
            print(f"  الرقعة بلا نص جديد. الحقول: {list(vars(p).keys())}")
            continue

        # بوابة 1: النحو
        try:
            compile(new, t, "exec")
            print("  نحو: سليم")
        except SyntaxError as exc:
            print(f"  نحو: معطوب سطر {exc.lineno} — {exc.msg}")
            continue

        # بوابة 2: البنية
        try:
            ok_s, why_s = s._structure_preserved(old, new)
            print(f"  بنية: {'سليمة' if ok_s else 'مرفوضة — ' + str(why_s)[:160]}")
        except Exception as exc:
            print(f"  بنية: تعذّر الفحص ({exc})")

        # بوابة 3: المعنى
        try:
            ok_m, why_m = s._semantics_preserved(old, new)
            print(f"  معنى: {'سليم' if ok_m else 'مرفوض — ' + str(why_m)[:160]}")
        except Exception as exc:
            print(f"  معنى: تعذّر الفحص ({exc})")

        # التحقق الكامل لهذه الرقعة وحدها
        s._calls = 0
        s._budget = 999
        try:
            ok, checks = s._verify_uncached([p])   # تُرجع (bool, list[dict])
            print(f"  تحقق كامل: ok={ok}")
            for c in checks or []:
                cok = c.get("ok")
                name = c.get("gate") or c.get("name") or "?"
                mark = "✓" if cok else "✗"
                print(f"    {mark} {name}: {str(c.get('message_ar', ''))[:300]}")
                if not cok:
                    for k, v in c.items():
                        if k in ("ok", "gate", "name", "message_ar"):
                            continue
                        print(f"        {k}: {str(v)[:400]}")
        except Exception as exc:
            print(f"  تحقق كامل: انهار ({type(exc).__name__}: {exc})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
