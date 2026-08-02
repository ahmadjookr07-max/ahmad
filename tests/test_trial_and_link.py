# -*- coding: utf-8 -*-
"""اختبار الفترة التجريبية والربط بين برنامج المالك وبرنامج المستخدم.

يتحقق من:
1. التجربة التلقائية 3 أيام تبدأ عند أول تشغيل بكامل الميزات.
2. حذف ملف التجربة أو إعادة إنشائه لا يمدد المدة (أثر ثانوي موازٍ).
3. إرجاع ساعة النظام يُكتشف ويُرفض.
4. انتهاء التجربة يمنع التشغيل ويطلب مفتاح تفعيل.
5. مفاتيح المالك لكل مدة (أسبوع/شهر/سنة/دائم) تُفعّل وتعرض المدة الصحيحة.
6. المفتاح مرتبط ببصمة الجهاز فلا يعمل على جهاز آخر.
7. الاشتراك المدفوع المنتهي لا يعيد فتح فترة تجريبية جديدة.
"""
import json
import os
import shutil
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


def _clear_attrs(path):
    """يزيل سمة hidden/readonly على ويندوز قبل الكتابة أو الحذف.

    الإنتاج يضع ملف الأثر الثانوي (.trial.dat) مخفيًا عبر
    SetFileAttributesW(0x02)، وويندوز يرفض فتحه للكتابة مباشرة
    فيرمي PermissionError. لذلك نعيده NORMAL(0x80) قبل أي عملية،
    وهو نفس ما يفعله license_v2 في الإنتاج.
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x80)
    except Exception:
        pass


def fwrite(path, blob):
    """كتابة قسرية تعمل على ويندوز ولينكس معًا."""
    _clear_attrs(path)
    Path(path).write_bytes(blob)


def fdelete(path):
    """حذف قسري يعمل على ويندوز ولينكس معًا."""
    _clear_attrs(path)
    Path(path).unlink()


def clean_state():
    """يمسح كل آثار الترخيص/التجربة/الساعة لبدء حالة جهاز جديد."""
    d = lv._license_dir()
    for p in list(d.iterdir()):
        try:
            _clear_attrs(p)
            p.unlink()
        except Exception:
            shutil.rmtree(p, ignore_errors=True)


# مفاتيح مالك تجريبية (كلاسيكي + مقاوم للكم) تُغرس كما في نسخة الإنتاج
priv, pub = lv.generate_owner_keypair()
pqc_priv, pqc_pub = lv.generate_pqc_keypair()
lv.OWNER_PUBLIC_KEY_B64 = pub
lv.OWNER_PQC_PUBLIC_KEY_B64 = pqc_pub


def issue(plan, days, fp=None, note=""):
    return lv.make_activation_key(priv, fp or lv.machine_fingerprint(),
                                  plan, days, note,
                                  pqc_private_key_b64=pqc_priv)


# ---------------------------------------------------------- 1) بداية التجربة
clean_state()
t1 = lv.start_or_check_trial()
check("trial_starts", t1.valid and t1.plan == "trial", t1.status)
check("trial_days_3", t1.days_left == lv.TRIAL_DAYS,
      f"{t1.days_left} من {lv.TRIAL_DAYS}")

# التجربة هي الحالة الفعلية عندما لا يوجد ترخيص
eff = lv.effective_license()
check("trial_is_effective", eff.valid and eff.plan == "trial", eff.status)

# ------------------------------------------- 2) الحذف لا يمدد المدة
d = lv._license_dir()
main_trial = d / lv.TRIAL_FILENAME
shadow_trial = d / ("." + lv.TRIAL_FILENAME)
check("trial_shadow_exists", shadow_trial.is_file(), str(shadow_trial.name))

# اجعل بداية التجربة قديمة (يومان) في كلا الأثرين
old_start = int(time.time()) - 2 * 86400
blob = lv._encrypt(json.dumps({"start": old_start}).encode(), b"trial")
fwrite(main_trial, blob)
fwrite(shadow_trial, blob)
t2 = lv.start_or_check_trial()
check("trial_counts_elapsed", t2.valid and t2.days_left <= 1,
      f"متبق {t2.days_left}")

# احذف الملف الرئيسي فقط: الأثر الثانوي يحفظ التاريخ الأقدم
fdelete(main_trial)
t3 = lv.start_or_check_trial()
check("trial_delete_no_reset", t3.days_left == t2.days_left,
      f"قبل {t2.days_left} بعد {t3.days_left}")

# احذف الأثر الثانوي أيضًا وأعد الرئيسي بتاريخ قديم: يبقى الأقدم معتمدًا
fdelete(shadow_trial)
fwrite(main_trial, blob)
t4 = lv.start_or_check_trial()
check("trial_oldest_wins", t4.days_left == t2.days_left,
      f"متبق {t4.days_left}")

# ------------------------------------------- 3) التلاعب بالساعة يُكتشف
clock = d / lv.CLOCK_FILENAME if hasattr(lv, "CLOCK_FILENAME") else None
future = int(time.time()) + 30 * 86400
if clock is not None:
    fwrite(clock, lv._encrypt(str(future).encode(), b"clock"))
    t5 = lv.start_or_check_trial()
    check("clock_tamper_detected", not t5.valid and "ساعة" in t5.status,
          t5.status)
    fdelete(clock)
else:
    check("clock_tamper_detected", False, "CLOCK_FILENAME غير معرّف")

# ------------------------------------------- 4) انتهاء التجربة يمنع التشغيل
clean_state()
expired = int(time.time()) - (lv.TRIAL_DAYS + 1) * 86400
blob_exp = lv._encrypt(json.dumps({"start": expired}).encode(), b"trial")
fwrite(main_trial, blob_exp)
fwrite(shadow_trial, blob_exp)
t6 = lv.start_or_check_trial()
check("trial_expired_blocks", not t6.valid and t6.days_left == 0, t6.status)
check("trial_expired_msg", "تفعيل" in t6.status or "المالك" in t6.status,
      t6.status)

# ------------------------------- 5) مفاتيح المالك لكل مدة تُفعّل بمدة صحيحة
durations = [("weekly", 7), ("monthly", 30), ("yearly", 365),
             ("lifetime", 0)]
for plan, days in durations:
    clean_state()
    info = lv.activate_with_key(issue(plan, days), pub)
    if days == 0:
        ok = info.valid and info.days_left == -1
        note = info.status
    else:
        ok = info.valid and (days - 2) <= info.days_left <= days
        note = f"{info.status} | متبق {info.days_left} من {days}"
    check(f"activate_{plan}", ok, note)
    # الشارة المعروضة للمستخدم تحمل المدة الحقيقية
    eff2 = lv.effective_license()
    check(f"effective_{plan}", eff2.valid and eff2.plan == plan,
          eff2.status)

# ------------------------------- 6) الربط بالجهاز: مفتاح جهاز آخر يُرفض
clean_state()
other = lv.activate_with_key(issue("yearly", 365, fp="AAAA-BBBB-CCCC-DDDD"),
                             pub)
check("device_bound", not other.valid and "جهاز آخر" in other.status,
      other.status)

# مفتاح موقّع بمفتاح مالك مزيف يُرفض
fake_priv, fake_pub = lv.generate_owner_keypair()
fake_key = lv.make_activation_key(fake_priv, lv.machine_fingerprint(),
                                  "yearly", 365,
                                  pqc_private_key_b64=pqc_priv)
bad = lv.activate_with_key(fake_key, pub)
check("reject_fake_owner", not bad.valid and "مرفوض" in bad.status,
      bad.status)

# مفتاح بلا توقيع مقاوم للكم يُرفض (الهجين إلزامي)
no_pqc = lv.make_activation_key(priv, lv.machine_fingerprint(),
                                "yearly", 365)
bad2 = lv.activate_with_key(no_pqc, pub)
check("reject_missing_pqc",
      not bad2.valid and "مقاوم للكم" in bad2.status, bad2.status)

# ------------------------- 7) اشتراك مدفوع منتهٍ لا يفتح تجربة جديدة
clean_state()
info = lv.activate_with_key(issue("monthly", 30), pub)
check("paid_then_expire_setup", info.valid, info.status)
# اجعل الاشتراك المخزن منتهيًا فعلًا
lic_path = d / lv.LICENSE_FILENAME
raw = lv._decrypt(lic_path.read_bytes(), b"license")
payload = json.loads(raw.decode("utf-8"))
payload["exp"] = int(time.time()) - 10
fwrite(lic_path, lv._encrypt(
    json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
    b"license"))
eff3 = lv.effective_license()
check("expired_paid_no_new_trial",
      not eff3.valid and eff3.plan != "trial", eff3.status)

# ------------------------- 8) الإلغاء من جهة المالك يبطل الترخيص فورًا
clean_state()
info = lv.activate_with_key(issue("yearly", 365), pub)
lv.revoke_license_id(info.license_id)
# فحص الترخيص نفسه يجب أن يعلن الإلغاء صراحة
revoked = lv.check_license(pub)
check("owner_revoke_blocks", not revoked.valid and "ملغى" in revoked.status,
      revoked.status)
# والحالة الفعلية لا تبقى اشتراكًا مدفوعًا بعد الإلغاء
after = lv.effective_license()
check("owner_revoke_no_paid", after.plan != "yearly", after.status)

clean_state()
print(f"\n===== {len(PASS)} passed / {len(FAIL)} failed =====")
if FAIL:
    print("FAILED:", FAIL)
sys.exit(0 if not FAIL else 1)
