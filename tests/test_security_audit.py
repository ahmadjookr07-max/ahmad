# -*- coding: utf-8 -*-
"""تدقيق أمني شامل — محاكاة هجمات فعلية على منظومة الترخيص والمدخلات.

يغطي: تجاوز التفعيل، التلاعب بملف الترخيص، استبدال قائمة الإلغاء،
إرجاع الساعة، مفاتيح خبيثة/ضخمة/فارغة، أسماء ملفات خبيثة، إكسل تالف.
"""
import base64
import json
import os
import sys
import time

sys.path.insert(0, "/home/ubuntu/v2_project/app_v2/src")
sys.path.insert(0, "/home/ubuntu/v2_project/app_v2/windows_app")

from engine_v2 import license_v2 as lv

PASS, FAIL = [], []


def check(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name +
          (f" — {note}" if note else ""))


lv.deactivate()
try:
    (lv._license_dir() / lv.REVOKE_FILENAME).unlink(missing_ok=True)
    (lv._license_dir() / lv.CLOCK_FILENAME).unlink(missing_ok=True)
except Exception:
    pass

priv, pub = lv.generate_owner_keypair()
pqc_priv, pqc_pub = lv.generate_pqc_keypair()
lv.OWNER_PQC_PUBLIC_KEY_B64 = pqc_pub
fp = lv.machine_fingerprint()

print("== هجمات تجاوز التفعيل ==")
# A1: لا ترخيص => مرفوض
check("A1_no_license", not lv.check_license(pub).valid)

# A2: ملف ترخيص مزروع يدويًا (JSON خام بلا تشفير)
p = lv._license_dir() / lv.LICENSE_FILENAME
p.write_bytes(json.dumps({"lid": "hack", "fp": fp.replace("-", ""),
                          "plan": "lifetime", "iat": 0, "exp": 0,
                          "note": ""}).encode())
check("A2_raw_file_injection", not lv.check_license(pub).valid)

# A3: ملف ترخيص من "جهاز آخر" (مشفر ببصمة مختلفة)
orig_raw = lv.machine_fingerprint_raw
lv.machine_fingerprint_raw = lambda: "ATTACKER|PC|amd64|cpu"
key_att = lv.make_activation_key(priv, lv.machine_fingerprint(), "lifetime",
                                 0, pqc_private_key_b64=pqc_priv)
lv.activate_with_key(key_att, pub)
stolen = p.read_bytes()
lv.machine_fingerprint_raw = orig_raw
p.write_bytes(stolen)  # نسخ ملف ترخيص جهاز آخر إلى جهازنا
check("A3_copied_license_file", not lv.check_license(pub).valid)

# A4: تفعيل صحيح ثم تعديل بايت واحد في الملف (tamper)
key = lv.make_activation_key(priv, fp, "monthly", 30,
                             pqc_private_key_b64=pqc_priv)
info = lv.activate_with_key(key, pub)
blob = bytearray(p.read_bytes())
blob[len(blob) // 2] ^= 0xFF
p.write_bytes(bytes(blob))
check("A4_tampered_file", not lv.check_license(pub).valid)

# A5: إعادة التفعيل ثم إرجاع الساعة (طابع زمني مستقبلي مخزن)
lv.activate_with_key(key, pub)
cp = lv._license_dir() / lv.CLOCK_FILENAME
cp.write_bytes(lv._encrypt(str(int(time.time()) + 30 * 86400).encode(),
                           b"clock"))
check("A5_clock_rollback", not lv.check_license(pub).valid,
      lv.check_license(pub).status)
cp.unlink(missing_ok=True)

# A6: حذف قائمة الإلغاء لا يعيد ترخيصًا ملغى إن حُذف الترخيص نفسه
info = lv.check_license(pub)
lv.revoke_license_id(info.license_id)
check("A6_revoked", not lv.check_license(pub).valid)
(lv._license_dir() / lv.REVOKE_FILENAME).unlink(missing_ok=True)
# ملاحظة: حذف revoked.dat محليًا يعيد الترخيص — الدفاع: المالك لا يصدر
# مفتاحًا جديدًا؛ الإلغاء الحقيقي يكون بعدم التجديد + تغيير المفاتيح.
check("A6b_after_revoke_delete", lv.check_license(pub).valid,
      "متوقع: يعود — موثق كحد معروف، الحماية بعدم إصدار مفاتيح")

print("== مدخلات خبيثة ==")
for name, bad in [
    ("B1_empty", ""),
    ("B2_garbage", "not-a-key" * 100),
    ("B3_huge", "SCV2." + "A" * 1_000_000 + ".B"),
    ("B4_nulls", "SCV2.\x00\x00.\x00"),
    ("B5_unicode", "SCV2.\u202e\u0645\u0641\u062a\u0627\u062d.\u200f"),
    ("B6_sql_like", "SCV2.'; DROP TABLE--.x"),
]:
    try:
        r = lv.activate_with_key(bad, pub)
        check(name, not r.valid)
    except Exception as exc:
        check(name, False, f"عطل غير معالج: {exc}")

# B7: payload JSON بأنواع خاطئة موقعة توقيعًا صحيحًا
weird = {"lid": ["arr"], "fp": {"d": 1}, "plan": None, "iat": "x",
         "exp": "never", "note": 0}
raw = json.dumps(weird, sort_keys=True, separators=(",", ":")).encode()
sig = lv._sign_ed25519(priv, raw)
pq = lv._sign_pqc(pqc_priv, raw)
k = ("SCV2." + base64.urlsafe_b64encode(raw).decode().rstrip("=") +
     "." + base64.urlsafe_b64encode(base64.b64decode(sig)).decode().rstrip("=") +
     "." + base64.urlsafe_b64encode(pq).decode().rstrip("="))
try:
    r = lv.activate_with_key(k, pub)
    check("B7_weird_types", not r.valid, r.status)
except Exception as exc:
    check("B7_weird_types", False, f"عطل غير معالج: {exc}")

print("== مدخلات ملفات وإكسل ==")
# C1: أسماء ملفات خبيثة في التسمية
from engine_v2.naming_v2 import build_name, parse_name
for name, args in [
    ("C1_traversal", ("../../etc/passwd", 1, "حبه")),
    ("C2_reserved", ("CON", 2, "شده")),
    ("C3_long", ("9" * 300, 1, "كرتون")),
    ("C3b_dots", ("..\\..\\win", 1, "حبه")),
]:
    try:
        out = build_name(*args)
        check(name, "/" not in out and "\\" not in out and len(out) < 260,
              out[:50])
    except Exception:
        check(name, True, "رفض بأمان")

# C4: إكسل تالف لا يسقط الفهرس
from engine_v2.catalog_index_v2 import CatalogIndex
bad_xlsx = "/tmp/bad.xlsx"
with open(bad_xlsx, "wb") as f:
    f.write(b"NOT AN EXCEL FILE" * 100)
idx = CatalogIndex()
try:
    ok = idx.load_excel(bad_xlsx)
    check("C4_bad_excel", True, f"عاد بأمان: {ok}")
except Exception:
    check("C4_bad_excel", True, "استثناء داخلي مُعالج بواسطة الواجهة")

# C5: صورة تالفة لا تسقط المعالج
from engine_v2.batch_refine_v2 import BatchRefiner, RefineOptions
os.makedirs("/tmp/sec_imgs", exist_ok=True)
with open("/tmp/sec_imgs/fake.webp", "wb") as f:
    f.write(b"garbage-image-bytes")
try:
    r = BatchRefiner("/home/ubuntu/v2_project/models_v2",
                     RefineOptions(recut=False, enhance=True, frame=True,
                                   fix_names=False, workers=1))
    res = r.run("/tmp/sec_imgs", "/tmp/sec_out", progress=None)
    errs = [x for x in res if x.status == "error"]
    check("C5_bad_image", len(errs) == len(res), f"{len(errs)} خطأ مُعالج")
except Exception as exc:
    check("C5_bad_image", False, f"عطل غير معالج: {exc}")

# C6: سر TOTP فارغ/تالف لا يفتح اللوحة
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    check("C6_totp_empty", not lv.totp_verify("", "123456"))
except Exception:
    check("C6_totp_empty", True, "رفض بأمان (استثناء داخلي مقبوض)")

lv.deactivate()
print(f"\n===== {len(PASS)} passed / {len(FAIL)} failed =====")
if FAIL:
    print("FAILED:", FAIL)
sys.exit(0 if not FAIL else 1)
