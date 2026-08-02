#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""توليد شفرة المالك وغرس المفاتيح العامة في برنامج المستخدم.

يُشغَّل مرة واحدة لإنشاء زوج مفاتيح المالك (Ed25519 + ML-DSA-65 المقاوم
للكم) وسر TOTP، ثم يغرس المفتاحين **العامين** داخل
src/engine_v2/license_v2.py حتى يقبل برنامج المستخدم المفاتيح الصادرة من
برنامج المالك.

الاستخدام:
    python3 tools/generate_owner_secrets.py            # توليد + غرس
    python3 tools/generate_owner_secrets.py --verify   # تحقق فقط

مخرجات:
    owner_studio/بيانات_المالك/owner_secrets.json   ← سري للغاية (المالك وحده)
    src/engine_v2/license_v2.py                      ← تُحدَّث المفاتيح العامة

تحذير: الملف السري لا يُرفع إلى GitHub ولا يُوزَّع مع البرنامج. من يملكه
يستطيع إصدار تراخيص. احفظ منه نسخة احتياطية في مكان آمن؛ فقدانه يعني
عدم القدرة على إصدار مفاتيح جديدة إلا بإعادة بناء البرنامج.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine_v2 import license_v2 as lv  # noqa: E402

LICENSE_SRC = ROOT / "src" / "engine_v2" / "license_v2.py"
SECRETS_DIR = ROOT / "owner_studio" / "بيانات_المالك"
SECRETS_FILE = SECRETS_DIR / "owner_secrets.json"


def embed_public_keys(pub: str, pqc_pub: str) -> None:
    """يستبدل قيمتي المفتاحين العامين في license_v2.py استبدالًا آمنًا."""
    src = LICENSE_SRC.read_text(encoding="utf-8")
    new, n1 = re.subn(r'^OWNER_PUBLIC_KEY_B64 = "[^"]*"',
                      f'OWNER_PUBLIC_KEY_B64 = "{pub}"', src,
                      count=1, flags=re.MULTILINE)
    new, n2 = re.subn(r'^OWNER_PQC_PUBLIC_KEY_B64 = "[^"]*"',
                      f'OWNER_PQC_PUBLIC_KEY_B64 = "{pqc_pub}"', new,
                      count=1, flags=re.MULTILINE)
    if n1 != 1 or n2 != 1:
        raise SystemExit(f"فشل الغرس: OWNER={n1} PQC={n2} — راجع الملف يدويًا")
    LICENSE_SRC.write_text(new, encoding="utf-8")


def verify(secrets: dict) -> bool:
    """يشغّل التحقق في عملية بايثون نظيفة.

    لا يجوز التحقق داخل هذه العملية لأن license_v2 مُحمّلة في الذاكرة
    بالمفاتيح القديمة قبل الغرس، وإعادة التحميل لا تضمن تحديث الثوابت
    في كل المواضع فيفشل التحقق زورًا.
    """
    import subprocess
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "verify_owner_link.py")],
        capture_output=True, text=True, timeout=900)
    print((proc.stdout or "").rstrip())
    if proc.returncode != 0 and proc.stderr:
        print(proc.stderr.strip()[:500])
    return proc.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true",
                    help="تحقق من الربط بالشفرة الموجودة دون توليد جديد")
    ap.add_argument("--force", action="store_true",
                    help="أعد التوليد حتى لو وُجدت شفرة (يبطل المفاتيح القديمة)")
    args = ap.parse_args()

    if args.verify:
        if not SECRETS_FILE.is_file():
            print("لا توجد شفرة مالك — شغّل السكربت بلا --verify للتوليد.")
            return 1
        sec = json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
        print("التحقق من ربط برنامج المالك ببرنامج المستخدم:")
        ok = verify(sec)
        print("\nالنتيجة: " + ("الربط سليم ✅" if ok else "الربط مكسور ❌"))
        return 0 if ok else 1

    if SECRETS_FILE.is_file() and not args.force:
        print(f"توجد شفرة مالك بالفعل: {SECRETS_FILE}")
        print("استخدم --force لإعادة التوليد (يبطل كل المفاتيح المُصدَرة).")
        return 1

    print("توليد شفرة المالك…")
    priv, pub = lv.generate_owner_keypair()
    pqc_priv, pqc_pub = lv.generate_pqc_keypair()
    secrets = {
        "ed25519_private": priv,
        "ed25519_public": pub,
        "mldsa65_private": pqc_priv,
        "mldsa65_public": pqc_pub,
        "totp_secret": lv.generate_totp_secret(),
        "created_at": int(time.time()),
        "owner": "Ahmed Al-Faifi",
        "note": "سري للغاية — لا يُرفع ولا يُوزَّع. من يملكه يصدر تراخيص.",
    }
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    SECRETS_FILE.write_text(
        json.dumps(secrets, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        SECRETS_FILE.chmod(0o600)
    except Exception:
        pass
    print(f"  حُفظت الشفرة: {SECRETS_FILE}")

    print("غرس المفاتيح العامة في برنامج المستخدم…")
    embed_public_keys(pub, pqc_pub)
    print(f"  حُدِّث: {LICENSE_SRC.relative_to(ROOT)}")

    print("\nالتحقق من الربط:")
    ok = verify(secrets)
    print("\nالنتيجة: " + ("الربط سليم ✅" if ok else "الربط مكسور ❌"))
    if ok:
        print("\nخطوات المالك:")
        print("  1. احفظ owner_secrets.json في مكان آمن (نسخة احتياطية).")
        print("  2. ضعه في مجلد (بيانات_المالك) بجانب برنامج المالك.")
        print("  3. أضف سر TOTP إلى Google Authenticator من تبويب رمز المالك.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
