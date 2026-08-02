# -*- coding: utf-8 -*-
"""اختبار مجلد بيانات المالك.

يتحقق من أن برنامج المالك يكتب شفرته وسجل عملائه في مجلد قابل للكتابة
دائمًا. الحالة الخطيرة: التثبيت في C:\\Program Files حيث يمنع ويندوز
الكتابة بجانب الـEXE للمستخدم العادي (أو يحوّلها إلى VirtualStore)،
فتضيع شفرة المالك وسجل العملاء صامتًا.

    python3 tests/test_owner_data_dir.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "owner_studio"))
sys.path.insert(0, str(ROOT / "src"))

import owner_studio as ow  # noqa: E402

PASSED = 0


def check(cond: bool, label: str) -> None:
    global PASSED
    if not cond:
        raise AssertionError(label)
    PASSED += 1
    print(f"  PASS {label}")


def test_portable_when_writable() -> None:
    print("1) مجلد بجانب البرنامج قابل للكتابة")
    check(ow.DATA == (ROOT / "owner_studio" / "بيانات_المالك").resolve(),
          f"يستخدم المجلد المحمول: {ow.DATA}")
    check(ow.SECRETS_FILE.parent == ow.DATA, "SECRETS_FILE داخل مجلد البيانات")
    check(ow.CUSTOMERS_FILE.parent == ow.DATA, "CUSTOMERS_FILE داخل مجلد البيانات")


def test_fallback_when_read_only(tmp: Path) -> None:
    print("2) محاكاة التثبيت في Program Files (قراءة فقط)")
    sim = tmp / "ProgramFiles" / "AhmedAlFaifiOwnerStudio"
    sim.mkdir(parents=True)
    old = sim / "بيانات_المالك"
    old.mkdir()
    (old / "owner_secrets.json").write_text(
        json.dumps({"ed25519_private": "PRIV", "totp_secret": "TOTP"}),
        encoding="utf-8")
    (old / "customers.json").write_text(
        json.dumps([{"name": "عميل تجربة"}], ensure_ascii=False),
        encoding="utf-8")
    os.chmod(old, 0o555)
    os.chmod(sim, 0o555)

    fake_home = tmp / "Users" / "owner"
    (fake_home / "AppData" / "Local").mkdir(parents=True)
    prev_local = os.environ.get("LOCALAPPDATA")
    prev_base = ow._base_dir
    os.environ["LOCALAPPDATA"] = str(fake_home / "AppData" / "Local")
    ow._base_dir = lambda: sim  # type: ignore[assignment]
    try:
        d = ow._data_dir()
        check("AppData" in str(d), f"انتقل لمجلد المستخدم: {d}")
        check(d.is_dir(), "المجلد البديل موجود")
        check((d / "owner_secrets.json").is_file(), "نُقلت شفرة المالك تلقائيًا")
        sec = json.loads((d / "owner_secrets.json").read_text(encoding="utf-8"))
        check(sec["ed25519_private"] == "PRIV", "محتوى الشفرة سليم بعد النقل")
        check(sec["totp_secret"] == "TOTP", "سر TOTP سليم بعد النقل")
        cust = json.loads((d / "customers.json").read_text(encoding="utf-8"))
        check(cust[0]["name"] == "عميل تجربة", "نُقل سجل العملاء بعربيته سليمًا")
        probe = d / "probe.json"
        probe.write_text("{}", encoding="utf-8")
        probe.unlink()
        check(True, "الكتابة في المجلد البديل تعمل فعليًا")
        # ثبات: نداء ثانٍ يعطي المسار نفسه ولا يكرر النقل
        check(ow._data_dir() == d, "المسار ثابت عبر النداءات")
    finally:
        ow._base_dir = prev_base  # type: ignore[assignment]
        if prev_local is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = prev_local
        os.chmod(old, 0o755)
        os.chmod(sim, 0o755)


def test_no_appdata_env(tmp: Path) -> None:
    print("3) بيئة بلا LOCALAPPDATA ولا APPDATA")
    sim = tmp / "ro2"
    sim.mkdir(parents=True)
    os.chmod(sim, 0o555)
    prev = {k: os.environ.pop(k, None) for k in ("LOCALAPPDATA", "APPDATA")}
    prev_base = ow._base_dir
    ow._base_dir = lambda: sim  # type: ignore[assignment]
    try:
        d = ow._data_dir()
        check(d.is_dir(), f"لا يرفع استثناء ويعيد مجلدًا صالحًا: {d}")
        probe = d / "probe.json"
        probe.write_text("{}", encoding="utf-8")
        probe.unlink()
        check(True, "المجلد الاحتياطي قابل للكتابة")
    finally:
        ow._base_dir = prev_base  # type: ignore[assignment]
        for k, v in prev.items():
            if v is not None:
                os.environ[k] = v
        os.chmod(sim, 0o755)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="owner_data_"))
    try:
        test_portable_when_writable()
        test_fallback_when_read_only(tmp)
        test_no_appdata_env(tmp)
    finally:
        for p in tmp.rglob("*"):
            try:
                os.chmod(p, 0o755)
            except Exception:
                pass
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nALL OWNER DATA DIR TESTS PASSED ({PASSED}/{PASSED})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
