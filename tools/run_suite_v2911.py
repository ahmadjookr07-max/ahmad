#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""مشغّل حزمة الاختبارات الكاملة لـ2.9.11.

يشغّل كل `tests/test_*.py` في عملية مستقلة (لأن اختبارات Qt لا تتحمّل
مشاركة QApplication)، ويكتب تقريرًا مرتبًا: ناجح / فاشل / متجاوَز.
المتجاوَز = يحتاج عتادًا أو بيانات مالك غير متوفرة في الصندوق.
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

# اختبارات تحتاج بيئة ويندوز فعلية أو بيانات مالك خاصة
ENV_LIMITED = {
    "test_installer_encoding.py",   # يحتاج makensis
    "test_pyc_magic.py",            # يحتاج مجلد بناء مُجمَّد
    "test_package_integrity.py",    # يحتاج مخرجات PyInstaller
}

TIMEOUT = int(os.environ.get("SUITE_TIMEOUT", "900"))


def main() -> int:
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    # مغرس بيانات المالك: بدونه تتخطّى سبعة اختبارات مساراتها
    # الحقيقية (المعالجة الكاملة، سرعة المطابقة، ترقية المنجز)
    fixture = Path("/home/ubuntu/owner_data")
    if "MIS_OWNER_DATA" not in env and fixture.is_dir():
        env["MIS_OWNER_DATA"] = str(fixture)
        print(f"مغرس بيانات المالك: {fixture}\n")
    env["PYTHONPATH"] = f"{ROOT / 'windows_app'}:{ROOT / 'src'}:{env.get('PYTHONPATH', '')}"

    files = sorted(p.name for p in TESTS.glob("test_*.py"))
    results = []
    t_all = time.perf_counter()

    for i, name in enumerate(files, 1):
        if name in ENV_LIMITED:
            print(f"[{i:2d}/{len(files)}] SKIP  {name}  (يحتاج أدوات بناء ويندوز)")
            results.append({"test": name, "status": "skip", "sec": 0.0, "tail": ""})
            continue
        t = time.perf_counter()
        try:
            proc = subprocess.run(
                [sys.executable, str(TESTS / name)],
                cwd=str(ROOT), env=env, capture_output=True,
                text=True, timeout=TIMEOUT,
            )
            rc, out = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
        except subprocess.TimeoutExpired:
            rc, out = 124, "TIMEOUT"
        sec = time.perf_counter() - t
        status = "pass" if rc == 0 else "fail"
        lines = [ln for ln in out.splitlines()
                 if ln.strip() and "propagateSize" not in ln]
        tail = "\n".join(lines[-14:])
        mark = "OK  " if status == "pass" else "FAIL"
        print(f"[{i:2d}/{len(files)}] {mark} {name}  ({sec:.1f}s)")
        if status == "fail":
            for ln in lines[-6:]:
                print(f"        | {ln}")
        results.append({"test": name, "status": status,
                        "sec": round(sec, 1), "tail": tail})

    total = time.perf_counter() - t_all
    npass = sum(1 for r in results if r["status"] == "pass")
    nfail = sum(1 for r in results if r["status"] == "fail")
    nskip = sum(1 for r in results if r["status"] == "skip")

    print("\n" + "=" * 60)
    print(f"ناجح {npass} / فاشل {nfail} / متجاوَز {nskip}   —  {total/60:.1f} دقيقة")
    if nfail:
        print("\nالفاشلة:")
        for r in results:
            if r["status"] == "fail":
                print(f"  - {r['test']}")
    out_json = ROOT / "suite_report_v2911.json"
    out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"\nالتقرير: {out_json}")
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
