#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""مُشغّل الفحص الشامل — يشغّل كل اختبارات المشروع ويلخّص النتائج.

الاستعمال:
    python3 tests/run_all.py            # الكل
    python3 tests/run_all.py ui         # ما يطابق الاسم فقط
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

ENV = dict(os.environ)
ENV.setdefault("QT_QPA_PLATFORM", "offscreen")
ENV.setdefault("MIS_SKIP_LICENSE", "1")
ENV.setdefault("PYTHONWARNINGS", "ignore")

TIMEOUT = int(os.environ.get("MIS_TEST_TIMEOUT", "900"))


def discover(filt: str | None) -> list[Path]:
    files = sorted(TESTS.glob("test_*.py"))
    if filt:
        files = [f for f in files if filt in f.name]
    return files


def verdict(name: str, rc: int, out: str) -> tuple[str, str]:
    """يحدّد النتيجة من رمز الخروج ومن نصّ المخرجات معًا.

    بعض الاختبارات تطبع ملخصًا ولا تضبط رمز الخروج، فالاعتماد على
    الرمز وحده يخفي إخفاقات حقيقية.
    """
    low = out.lower()
    # ملخص «N passed / M failed»
    import re
    m = re.search(r"(\d+)\s*passed\s*/\s*(\d+)\s*failed", low)
    if m:
        passed, failed = int(m.group(1)), int(m.group(2))
        detail = f"{passed} نجح / {failed} فشل"
        return ("PASS" if failed == 0 and rc == 0 else "FAIL", detail)
    if rc != 0:
        return ("FAIL", f"rc={rc}")
    # مؤشرات نصية
    fails = len(re.findall(r"^\s*FAIL\b", out, re.M))
    if fails:
        return ("FAIL", f"{fails} سطر FAIL")
    return ("PASS", "rc=0")


def main() -> int:
    filt = sys.argv[1] if len(sys.argv) > 1 else None
    files = discover(filt)
    print(f"تشغيل {len(files)} ملف اختبار\n" + "=" * 62)

    results = []
    t_all = time.time()
    for path in files:
        t0 = time.time()
        try:
            proc = subprocess.run(
                [sys.executable, str(path)], cwd=str(ROOT), env=ENV,
                capture_output=True, text=True, timeout=TIMEOUT)
            out = (proc.stdout or "") + (proc.stderr or "")
            status, detail = verdict(path.name, proc.returncode, out)
        except subprocess.TimeoutExpired:
            out, status, detail = "", "TIMEOUT", f">{TIMEOUT}s"
        dt = time.time() - t0
        mark = {"PASS": "✓", "FAIL": "✗", "TIMEOUT": "⏱"}[status]
        print(f"  {mark} {path.name:<38} {detail:<22} {dt:6.1f}s")
        results.append({"test": path.name, "status": status,
                        "detail": detail, "seconds": round(dt, 1),
                        "tail": out[-4000:] if status != "PASS" else ""})

    ok = sum(1 for r in results if r["status"] == "PASS")
    bad = [r for r in results if r["status"] != "PASS"]
    print("=" * 62)
    print(f"الإجمالي: {ok}/{len(results)} نجح — "
          f"الزمن {time.time() - t_all:.0f}s")
    if bad:
        print("\nالإخفاقات:")
        for r in bad:
            print(f"  - {r['test']}: {r['detail']}")

    report = ROOT / "tests" / "_run_all_report.json"
    report.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"\nالتقرير: {report}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
