# -*- coding: utf-8 -*-
"""اختبار التوقيع الهجين Ed25519 + ML-DSA-65 المقاوم للكم."""
import sys

sys.path.insert(0, "/home/ubuntu/v2_project/app_v2/src")

from engine_v2 import license_v2 as lv

PASS, FAIL = [], []


def check(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name +
          (f" — {note}" if note else ""))


lv.deactivate()
priv, pub = lv.generate_owner_keypair()
pqc_priv, pqc_pub = lv.generate_pqc_keypair()
lv.OWNER_PQC_PUBLIC_KEY_B64 = pqc_pub
fp = lv.machine_fingerprint()

# 1) مفتاح هجين (توقيعان) يُقبل
key = lv.make_activation_key(priv, fp, "yearly", 365,
                             pqc_private_key_b64=pqc_priv)
check("hybrid_key_format", key.count(".") == 3, f"{len(key)} حرفًا")
info = lv.activate_with_key(key, pub)
check("hybrid_accept", info.valid, info.status)

# 2) مفتاح بتوقيع Ed25519 فقط (بلا PQC) يُرفض عندما PQC مفروض
key_no_pqc = lv.make_activation_key(priv, fp, "yearly", 365)
info2 = lv.activate_with_key(key_no_pqc, pub)
check("reject_missing_pqc", not info2.valid and "مرفوض" in info2.status,
      info2.status)

# 3) توقيع PQC من مفتاح آخر (مزور) يُرفض
other_priv, _ = lv.generate_pqc_keypair()
key_forged = lv.make_activation_key(priv, fp, "yearly", 365,
                                    pqc_private_key_b64=other_priv)
info3 = lv.activate_with_key(key_forged, pub)
check("reject_forged_pqc", not info3.valid, info3.status)

# 4) بدون غرس مفتاح PQC (نسخة قديمة) يبقى Ed25519 وحده كافيًا
lv.OWNER_PQC_PUBLIC_KEY_B64 = "REPLACED_AT_KEYGEN"
info4 = lv.activate_with_key(key_no_pqc, pub)
check("backward_compat", info4.valid, info4.status)

# 5) الحجم العملي للمفتاح الهجين (يُلصق في النافذة)
check("key_size_ok", len(key) < 5000, f"{len(key)} حرفًا")

lv.deactivate()
print(f"\n===== {len(PASS)} passed / {len(FAIL)} failed =====")
if FAIL:
    print("FAILED:", FAIL)
sys.exit(0 if not FAIL else 1)
