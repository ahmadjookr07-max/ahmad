#!/usr/bin/env python3
"""اختبار الربط الموثوق بين استوديو المالك وبرنامج العملاء.

يتحقق من:
1. إصدار وتفعيل مفاتيح لكل الخطط (أسبوعي/شهري/سنوي/دائم) وعرض المدة الصحيحة
2. رفض مفتاح مُتلاعَب بمدته (توقيع Ed25519 + ML-DSA-65)
3. رفض مفتاح مخصص لجهاز آخر (بصمة الجهاز)
4. إلزامية التوقيع المقاوم للكم عند غرس مفتاح PQC عام
5. نص شارة الاشتراك للمستخدم يعرض الخطة والمدة وتاريخ الانتهاء
"""
import base64
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from engine_v2 import license_v2 as lv  # noqa: E402

RESULTS = []


def check(name, ok, note=""):
    RESULTS.append(ok)
    print(f"  {'PASS' if ok else 'FAIL'} {name}" + (f" — {note}" if note else ""))


priv, pub = lv.generate_owner_keypair()
pqc_priv, pqc_pub = lv.generate_pqc_keypair()
fp = lv.machine_fingerprint()

# غرس مفاتيح الاختبار صراحة (كما تُغرس مفاتيح المالك الحقيقية عند البناء)
lv.OWNER_PUBLIC_KEY_B64 = pub
lv.OWNER_PQC_PUBLIC_KEY_B64 = pqc_pub

# 1) كل الخطط تصدر وتُفعَّل وتعرض المدة الصحيحة
for plan, days in [("weekly", 7), ("monthly", 30),
                   ("yearly", 365), ("lifetime", 0)]:
    key = lv.make_activation_key(priv, fp, plan, days, "اختبار",
                                 pqc_private_key_b64=pqc_priv)
    info = lv.activate_with_key(key, public_key_b64=pub)
    if days:
        ok = info.valid and info.days_left in (days - 1, days)
    else:
        ok = info.valid and info.days_left == -1
    check(f"issue_activate_{plan}", ok,
          f"days_left={info.days_left} status={info.status}")

# 2) مفتاح مُتلاعَب بالمدة يُرفض
key = lv.make_activation_key(priv, fp, "weekly", 7,
                             pqc_private_key_b64=pqc_priv)
parts = key.split(".")
payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=="))
payload["exp"] = int(time.time()) + 10 * 365 * 86400
forged_p64 = base64.urlsafe_b64encode(
    json.dumps(payload, sort_keys=True,
               separators=(",", ":")).encode()).decode().rstrip("=")
forged = f"SCV2.{forged_p64}.{parts[2]}.{parts[3]}"
info = lv.activate_with_key(forged, public_key_b64=pub)
check("tampered_duration_rejected", not info.valid, info.status)

# 3) مفتاح لجهاز آخر يُرفض
key2 = lv.make_activation_key(priv, "AAAA-BBBB-CCCC-DDDD", "yearly", 365,
                              pqc_private_key_b64=pqc_priv)
info = lv.activate_with_key(key2, public_key_b64=pub)
check("other_device_rejected", not info.valid, info.status)

# 4) مفتاح بلا توقيع PQC يُرفض (الغرس مفعّل)
key3 = lv.make_activation_key(priv, fp, "monthly", 30)
info = lv.activate_with_key(key3, public_key_b64=pub)
check("missing_pqc_rejected", not info.valid, info.status)

# 5) مفتاح موقع بمفتاح مالك مختلف (مهاجم) يُرفض
apriv, apub = lv.generate_owner_keypair()
apqc_priv, _ = lv.generate_pqc_keypair()
key4 = lv.make_activation_key(apriv, fp, "yearly", 365,
                              pqc_private_key_b64=apqc_priv)
info = lv.activate_with_key(key4, public_key_b64=pub)
check("attacker_key_rejected", not info.valid, info.status)

# 6) شارة المستخدم تعرض الخطة والمدة وتاريخ الانتهاء
key5 = lv.make_activation_key(priv, fp, "yearly", 365, "عميل",
                              pqc_private_key_b64=pqc_priv)
info = lv.activate_with_key(key5, public_key_b64=pub)
check("badge_info_fields",
      info.valid and info.plan == "yearly" and info.expires_at > 0
      and info.days_left in (364, 365)
      and "متبق" in info.status,
      info.status)

# weekly في قاموس الخطط المعروضة
check("weekly_in_plans", "weekly" in lv.PLANS, lv.PLANS.get("weekly", ""))

n_pass = sum(RESULTS)
print(f"===== {n_pass}/{len(RESULTS)} passed =====")
sys.exit(0 if all(RESULTS) else 1)
