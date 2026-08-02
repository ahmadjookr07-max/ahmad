#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""التحقق من ربط برنامج المالك ببرنامج المستخدم.

يصدر مفتاح تفعيل حقيقيًا بالمفاتيح الخاصة من شفرة المالك، ثم يتحقق منه
بالمفاتيح العامة المغروسة داخل src/engine_v2/license_v2.py. نجاح التوقيعين
معًا (Ed25519 + ML-DSA-65) يعني أن البرنامجين مرتبطان ارتباطًا صحيحًا.

يجب تشغيله كعملية مستقلة (لا استيراده بعد تعديل license_v2 في نفس العملية).

    python3 tools/verify_owner_link.py
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SECRETS_FILE = ROOT / "owner_studio" / "بيانات_المالك" / "owner_secrets.json"


def main() -> int:
    if not SECRETS_FILE.is_file():
        print("لا توجد شفرة مالك — شغّل tools/generate_owner_secrets.py أولًا.")
        return 1

    from engine_v2 import license_v2 as lv

    sec = json.loads(SECRETS_FILE.read_text(encoding="utf-8"))

    ok_pub_ed = lv.OWNER_PUBLIC_KEY_B64 == sec["ed25519_public"]
    ok_pub_pqc = lv.OWNER_PQC_PUBLIC_KEY_B64 == sec["mldsa65_public"]
    print("مطابقة المفاتيح العامة المغروسة لشفرة المالك:")
    print(f"  Ed25519    : {'مطابق' if ok_pub_ed else 'غير مطابق'}")
    print(f"  ML-DSA-65  : {'مطابق' if ok_pub_pqc else 'غير مطابق'}")
    if not (ok_pub_ed and ok_pub_pqc):
        print("\nالنتيجة: الربط مكسور — أعد الغرس بـ generate_owner_secrets.py")
        return 1

    fp = lv.machine_fingerprint()
    key = lv.make_activation_key(
        sec["ed25519_private"], fp, "yearly", 365, "تحقق الربط",
        pqc_private_key_b64=sec["mldsa65_private"])
    parts = key.split(".")
    raw = lv._b64pad(parts[1])
    payload = json.loads(raw.decode("utf-8"))

    ok_ed = lv._verify_ed25519(
        lv.OWNER_PUBLIC_KEY_B64, raw,
        base64.b64encode(lv._b64pad(parts[2])).decode())
    ok_pqc = (lv._verify_pqc(lv.OWNER_PQC_PUBLIC_KEY_B64, raw,
                             lv._b64pad(parts[3]))
              if len(parts) == 4 else False)

    print("\nإصدار مفتاح تفعيل حقيقي والتحقق منه:")
    print(f"  بصمة هذا الجهاز       : {fp}")
    print(f"  رقم الترخيص المُصدَر    : {payload['lid']}")
    print(f"  الخطة                 : {payload['plan']}")
    print(f"  طول المفتاح           : {len(key)} حرفًا ({len(parts)} أجزاء)")
    print(f"  توقيع Ed25519         : {'صحيح' if ok_ed else 'فاشل'}")
    print(f"  توقيع ML-DSA-65 (كمي) : {'صحيح' if ok_pqc else 'فاشل'}")

    # اختبار سلبي: تحريف بايت واحد في الحمولة يجب أن يُسقط التوقيعين
    bad = bytearray(raw)
    bad[10] ^= 0x01
    tampered_ed = lv._verify_ed25519(
        lv.OWNER_PUBLIC_KEY_B64, bytes(bad),
        base64.b64encode(lv._b64pad(parts[2])).decode())
    tampered_pqc = lv._verify_pqc(lv.OWNER_PQC_PUBLIC_KEY_B64, bytes(bad),
                                  lv._b64pad(parts[3]))
    print("\nاختبار مقاومة التزوير (تحريف بايت واحد):")
    print(f"  Ed25519 يرفض المحرَّف   : {'نعم' if not tampered_ed else 'لا'}")
    print(f"  ML-DSA يرفض المحرَّف    : {'نعم' if not tampered_pqc else 'لا'}")

    ok = ok_ed and ok_pqc and not tampered_ed and not tampered_pqc
    print("\nالنتيجة: " + ("الربط سليم ومحمي" if ok else "الربط مكسور"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
