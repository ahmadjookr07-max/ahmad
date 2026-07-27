# -*- coding: utf-8 -*-
"""اختبار headless لواجهات الترخيص (EULA/تفعيل/لوحة مالك/بوابة إقلاع)."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "/home/ubuntu/v2_project/app_v2/src")
sys.path.insert(0, "/home/ubuntu/v2_project/app_v2/windows_app")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from engine_v2 import license_v2 as lv  # noqa: E402
import license_ui  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name +
          (f" — {note}" if note else ""))


# بيئة نظيفة
lv.deactivate()
try:
    license_ui._eula_flag_path().unlink(missing_ok=True)
except Exception:
    pass

# 1) مفاتيح مالك حقيقية مغروسة (محاكاة ما يحدث قبل البناء)
priv, pub = lv.generate_owner_keypair()
lv.OWNER_PUBLIC_KEY_B64 = pub
secret = lv.generate_totp_secret()
license_ui.OWNER_TOTP_SECRET = secret

# 2) EULA: نصها يحوي البنود الأساسية وبيانات التواصل
txt = license_ui._eula_text()
check("eula_text", "ahmadjookr06@gmail.com" in txt and "0582381000" in txt
      and "استرداد" in txt and "أوافق" in txt.replace("\u200f", ""))

dlg = license_ui.EulaDialog()
check("eula_dialog_build", dlg.windowTitle().startswith("اتفاقية"))
dlg._accept_eula()
check("eula_flag", license_ui.eula_accepted())

# 3) نافذة التفعيل: البصمة معروضة + مفتاح صحيح يفعل
adlg = license_ui.ActivationDialog()
check("activation_shows_fp",
      adlg._fp_lbl.text() == lv.machine_fingerprint())
key = lv.make_activation_key(priv, lv.machine_fingerprint(), "yearly", 365)
adlg.key_edit.setPlainText(key)
# _activate يعرض QMessageBox — نستدعي المنطق مباشرة
info = lv.activate_with_key(key, pub)
check("activation_valid", info.valid and info.plan == "yearly", info.status)

# 4) مفتاح تالف يُرفض
bad = lv.activate_with_key("SCV2.aaaa.bbbb", pub)
check("activation_reject_bad", not bad.valid, bad.status)

# 5) الشارة
badge = license_ui.license_badge_text()
check("badge_text", "الاشتراك" in badge and "36" in badge, badge)

# 6) لوحة المالك: رمز خاطئ لا يفتح، الصحيح يفتح
odlg = license_ui.OwnerPanelDialog()
odlg.code_edit.setText("000000")
# لا نستدعي _unlock مباشرة لأنه يعرض QMessageBox — نختبر التحقق نفسه
check("owner_reject_wrong", not lv.totp_verify(secret, "000000"))
check("owner_accept_right", lv.totp_verify(secret, lv.totp_now(secret)))

# 7) إعدادات المالك: حفظ واسترجاع
sdlg = license_ui.OwnerSettingsDialog()
sdlg.w_spin.setValue(900)
sdlg.q_spin.setValue(95)
import json as _json
license_ui._owner_settings_path().write_text(
    _json.dumps({"out_width": 900, "webp_quality": 95, "batch_workers": 3},
                ensure_ascii=False), encoding="utf-8")
data = license_ui.load_owner_settings()
check("owner_settings_roundtrip",
      data.get("out_width") == 900 and data.get("batch_workers") == 3)

# 8) ensure_activated مع ترخيص صالح = True دون أي نافذة
check("ensure_activated_valid", license_ui.ensure_activated(None))

# 9) بعد الإلغاء: ensure_activated يتطلب نافذة (لا يمكن اختبار exec headless
#    تفاعليًا — نتحقق أن check_license يرفض)
lv.revoke_license_id(info.license_id)
info2 = lv.check_license(pub)
check("revoked_blocks", not info2.valid, info2.status)

# 10) BatchRefineDialog تُبنى وworkers من إعدادات المالك
sys.path.insert(0, "/home/ubuntu/v2_project/app_v2/windows_app")
import v2_ui  # noqa: E402
bdlg = v2_ui.BatchRefineDialog()
check("batch_dialog_build", bdlg.windowTitle().startswith("ضبط الصور"))
check("batch_dialog_options",
      bdlg.chk_recut.isChecked() and bdlg.shadow_combo.count() == 6)

# تنظيف: إزالة الإلغاء حتى لا يؤثر على اختبارات لاحقة
lv.deactivate()
try:
    (lv._license_dir() / lv.REVOKE_FILENAME).unlink(missing_ok=True)
except Exception:
    pass

print(f"\n===== {len(PASS)} passed / {len(FAIL)} failed =====")
if FAIL:
    print("FAILED:", FAIL)
sys.exit(0 if not FAIL else 1)
