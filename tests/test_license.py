# -*- coding: utf-8 -*-
"""اختبار منظومة الترخيص license_v2 من طرف إلى طرف."""
import base64
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine_v2 import license_v2 as lv

PASS, FAIL = [], []


def check(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name +
          (f" — {note}" if note else ""))


# 1) توليد مفاتيح المالك (كلاسيكي + مقاوم للكم)
priv, pub = lv.generate_owner_keypair()
check("keypair", len(base64.b64decode(priv)) == 32
      and len(base64.b64decode(pub)) == 32)

# التوقيع الهجين إلزامي في المحرك: اغرس مفتاح PQC عام تجريبيًا
# ومرر الخاص لكل مفتاح يُصدر، وإلا رُفض المفتاح بحق كما لو كان مزورًا.
pqc_priv, pqc_pub = lv.generate_pqc_keypair()
lv.OWNER_PQC_PUBLIC_KEY_B64 = pqc_pub


def issue(fp, plan, days, note=""):
    """يُصدر مفتاحًا موقعًا توقيعًا هجينًا كما يفعل استوديو المالك."""
    return lv.make_activation_key(priv, fp, plan, days, note,
                                  pqc_private_key_b64=pqc_priv)

# 2) بصمة الجهاز ثابتة وصيغتها صحيحة
fp1, fp2 = lv.machine_fingerprint(), lv.machine_fingerprint()
check("fingerprint", fp1 == fp2 and len(fp1) == 19 and fp1.count("-") == 3,
      fp1)

# 3) إصدار مفتاح شهري وتفعيله
key = issue(fp1, "monthly", 30, "جهاز المالك")
check("key_format", key.startswith("SCV2.") and key.count(".") == 3)
info = lv.activate_with_key(key, pub)
check("activate", info.valid and 28 <= info.days_left <= 30, info.status)

# 4) الفحص بعد التفعيل يقرأ الملف المشفر
info2 = lv.check_license(pub)
check("check_stored", info2.valid and info2.plan == "monthly", info2.status)

# 5) مفتاح لجهاز آخر يُرفض
key_other = issue("AAAA-BBBB-CCCC-DDDD", "yearly", 365)
info3 = lv.activate_with_key(key_other, pub)
check("reject_other_device", not info3.valid
      and "جهاز آخر" in info3.status, info3.status)

# 6) توقيع مزور يُرفض (عبث بالحمولة)
p, s, _ = lv.parse_activation_key(key)
p["exp"] = 0  # حوّله لدائم
raw = json.dumps(p, sort_keys=True, separators=(",", ":")).encode()
fake = ("SCV2." + base64.urlsafe_b64encode(raw).decode().rstrip("=")
        + "." + key.split(".")[2])
info4 = lv.activate_with_key(fake, pub)
check("reject_forged", not info4.valid and "مرفوض" in info4.status,
      info4.status)

# 7) مفتاح منتهي الصلاحية يُرفض
# يُوقع توقيعًا هجينًا صحيحًا حتى يكون سبب الرفض الانتهاء لا التوقيع
key_exp = issue(fp1, "trial", 30)
pl, sg, _ = lv.parse_activation_key(key_exp)
pl.pop("_pqc_sig_b64", None)
pl["exp"] = int(time.time()) - 10
raw = json.dumps(pl, sort_keys=True, separators=(",", ":")).encode()
sig = lv._sign_ed25519(priv, raw)
expired_key = ("SCV2." + base64.urlsafe_b64encode(raw).decode().rstrip("=")
               + "." + base64.urlsafe_b64encode(
                   base64.b64decode(sig)).decode().rstrip("=")
               + "." + base64.urlsafe_b64encode(
                   lv._sign_pqc(pqc_priv, raw)).decode().rstrip("="))
info5 = lv.activate_with_key(expired_key, pub)
check("reject_expired", not info5.valid and "انته" in info5.status,
      info5.status)

# 8) الإلغاء
lv.revoke_license_id(info2.license_id)
info6 = lv.check_license(pub)
check("revocation", not info6.valid and "ملغى" in info6.status, info6.status)

# 9) إعادة تفعيل بمفتاح جديد بعد الإلغاء (lid جديد)
key2 = issue(fp1, "lifetime", 0)
info7 = lv.activate_with_key(key2, pub)
check("reactivate_lifetime", info7.valid and info7.days_left == -1,
      info7.status)

# 10) TOTP: توليد وتحقق
secret = lv.generate_totp_secret()
code = lv.totp_now(secret)
check("totp_verify", lv.totp_verify(secret, code)
      and not lv.totp_verify(secret, "000000"))
# متجه اختبار RFC 6238 (SHA1, digits=8 مكيف إلى 6): سر ASCII "12345678901234567890"
rfc_secret = base64.b32encode(b"12345678901234567890").decode()
check("totp_rfc6238", lv.totp_now(rfc_secret, when=59) == "287082")

# 11) القراءة من جهاز آخر تفشل (محاكاة بتغيير بصمة الاشتقاق)
orig = lv.machine_fingerprint_raw
lv.machine_fingerprint_raw = lambda: "OTHER|MACHINE|x86|cpu"
info8 = lv.check_license(pub)
lv.machine_fingerprint_raw = orig
check("copy_protection", not info8.valid, info8.status)

# 12) التنظيف والتعطيل
lv.deactivate()
info9 = lv.check_license(pub)
check("deactivate", not info9.valid and "لا يوجد" in info9.status)

print(f"\n===== {len(PASS)} passed / {len(FAIL)} failed =====")
if FAIL:
    print("FAILED:", FAIL)
sys.exit(0 if not FAIL else 1)
