# -*- coding: utf-8 -*-
"""يشغّل كل ملفات الاختبار في `tests/` ويُلخّص النتيجة.

لماذا لا `pytest tests/`؟ لأن عدة ملفات في هذا المشروع تُدير حالة
عالمية (مجلد الترخيص في `~/.config`، متغيّرات البيئة، ملفات مؤقتة).
تشغيلها في عملية واحدة يجعلها تتلوّث ببعضها، وهذا ما أنتج سابقًا
فشلًا وهميًا في اختبارات الترخيص. لذا: عملية مستقلة لكل ملف،
و`HOME` معزول لكل واحدة.

    python3 tools/run_all_tests.py           # الكل
    python3 tools/run_all_tests.py -k license  # ما يطابق نصًا
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"


def _env_for(home: str) -> dict:
    """بيئة معزولة: HOME خاص يمنع التنازع على ملف الترخيص."""
    env = os.environ.copy()
    sep = ";" if os.name == "nt" else ":"
    env["PYTHONPATH"] = sep.join(
        str(ROOT / p) for p in ("src", "windows_app", "owner_studio", "."))
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONUTF8"] = "1"
    env["HOME"] = home
    env["USERPROFILE"] = home          # ويندوز
    env["XDG_CONFIG_HOME"] = str(Path(home) / ".config")
    env["MIS_LICENSE_BYPASS"] = "1"
    return env


def main() -> int:
    ap = argparse.ArgumentParser(description="تشغيل كل الاختبارات")
    ap.add_argument("-k", "--filter", default="",
                    help="تشغيل الملفات التي تطابق هذا النص فقط")
    ap.add_argument("--timeout", type=int, default=300,
                    help="أقصى ثوانٍ لكل ملف (افتراضي 300)")
    args = ap.parse_args()

    files = sorted(p for p in TESTS.glob("test_*.py")
                   if args.filter in p.name)
    if not files:
        print("لا ملفات اختبار مطابقة")
        return 1

    print(f"تشغيل {len(files)} ملف اختبار — كل ملف في عملية وبيئة معزولة\n")
    passed: list[str] = []
    failed: list[tuple[str, str]] = []
    t0 = time.time()

    for i, path in enumerate(files, 1):
        with tempfile.TemporaryDirectory(prefix="mis_test_home_") as home:
            (Path(home) / ".config").mkdir(exist_ok=True)
            try:
                res = subprocess.run(
                    [sys.executable, str(path)],
                    cwd=str(ROOT), env=_env_for(home),
                    capture_output=True, text=True,
                    encoding="utf-8", errors="replace",
                    timeout=args.timeout,
                )
                ok = res.returncode == 0
                detail = (res.stdout + res.stderr).strip().splitlines()
                tail = detail[-1] if detail else f"رمز {res.returncode}"
            except subprocess.TimeoutExpired:
                ok, tail = False, f"تجاوز {args.timeout} ثانية"

        mark = "✓" if ok else "✗"
        print(f"  [{i:2}/{len(files)}] {mark} {path.name}")
        if ok:
            passed.append(path.name)
        else:
            failed.append((path.name, tail[:200]))
            print(f"        └ {tail[:200]}")

    dur = time.time() - t0
    print(f"\n{'=' * 58}")
    print(f"ناجح: {len(passed)}/{len(files)}  |  فاشل: {len(failed)}"
          f"  |  الزمن: {dur:.0f}ث")
    if failed:
        print("\nالفاشل:")
        for name, why in failed:
            print(f"  ✗ {name}: {why}")
        return 1
    print("\n✓ كل الاختبارات ناجحة")
    return 0


if __name__ == "__main__":
    sys.exit(main())
