#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تطبيق رقع الجرّاح على دفعات مع إثبات عدم الانحدار.

الاستعمال:
    python3 tools/run_surgery.py --codes silent_except --apply
    python3 tools/run_surgery.py --codes silent_except            # معاينة

يعمل بالدفعات لأن ``max_files=12`` سقف مقصود في الجرّاح: رقعة صغيرة
مُتحقَّق منها أفضل من دفعة ضخمة يصعب تفسيرها أو التراجع عنها.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("MIS_HEADLESS", "1")

from awareness.surgeon import Surgeon  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", default="silent_except")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--max-files", type=int, default=12)
    args = ap.parse_args()

    codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    total_applied = 0

    for rnd in range(1, args.rounds + 1):
        s = Surgeon()
        remaining = [i for i in s.diagnose() if i.code in codes]
        if not remaining:
            print(f"\n[دفعة {rnd}] لا علل باقية من الرموز المطلوبة. توقّف.")
            break

        files = sorted({i.path for i in remaining})
        print(f"\n{'=' * 66}")
        print(f"[دفعة {rnd}] علل باقية: {len(remaining)} في {len(files)} ملف")
        print("=" * 66)

        t0 = time.time()
        res = s.operate(codes=codes, apply=args.apply,
                        max_files=args.max_files,
                        reason=f"إصلاح {','.join(codes)} — دفعة {rnd}")
        dt = time.time() - t0

        def g(obj, key, default=None):
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        ok = g(res, "ok")
        print(f"  ok={ok}  ({dt:.1f}s)")
        print(f"  {g(res, 'message_ar', '') or ''}")

        patches = g(res, "patches") or []
        for p in patches:
            print(f"    • {g(p, 'path', p)}  {g(p, 'stats')}")

        quar = g(res, "quarantined") or []
        if quar:
            print(f"  معزول ({len(quar)}):")
            for q in quar:
                print(f"    ! {q}")

        if not ok:
            print("  فشلت الدفعة — أتوقّف لفحص السبب بدل المضي عمياء.")
            return 1

        if not args.apply:
            print("\n(معاينة فقط: لم يُلمس أي ملف)")
            break

        total_applied += len(patches)
        if not patches:
            print("  لا رقع مُنتَجة رغم وجود علل — أتوقّف لفحص السبب.")
            break

    print(f"\nإجمالي الملفات المُعدَّلة: {total_applied}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
