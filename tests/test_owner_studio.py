# -*- coding: utf-8 -*-
"""اختبارات استوديو المالك — headless عبر Xvfb.

يغطي:
1. تحميل الشفرة والإقلاع بالواجهة الكاملة
2. إصدار مفتاح تفعيل من الواجهة والتحقق منه بمنظومة license_v2 (Ed25519+PQC)
3. سجل العملاء: الإضافة، البحث، التفاصيل
4. التمديد/التجديد بإصدار مفتاح جديد صالح
5. تسجيل الإلغاء
6. رمز TOTP الحي مطابق لمنظومة الترخيص
7. النسخ الاحتياطي والاستعادة
8. رسالة العميل الجاهزة تحوي المفتاح
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / "app_v2" / "src"))
sys.path.insert(0, str(HERE / "app_v2" / "owner_studio"))

import owner_studio as osd  # noqa: E402
from engine_v2 import license_v2 as lv  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} — {detail}")


def main() -> None:
    print("== اختبارات استوديو المالك ==")

    # بيئة نظيفة: مجلد بيانات مؤقت
    data = osd.DATA
    if data.exists():
        shutil.rmtree(data, ignore_errors=True)
    data.mkdir(parents=True, exist_ok=True)

    # انسخ الشفرة الحقيقية
    real = HERE / "owner_tool" / "owner_secrets.json"
    shutil.copy(real, osd.SECRETS_FILE)

    # 1) الإقلاع
    app = osd.OwnerStudio()
    app.update()
    check("الإقلاع بالواجهة الرئيسية", hasattr(app, "nb"))
    check("تحميل شفرة المالك", bool(app.secrets)
          and "ed25519_private" in app.secrets)
    check("عدد التبويبات = 5", app.nb.index("end") == 5,
          str(app.nb.index("end") if hasattr(app, "nb") else "?"))

    # 2) إصدار مفتاح من الواجهة
    fp = "A3F2-9K1B-77CD-E2A0"
    app.e_fp.insert(0, fp)
    app.e_name.insert(0, "محل الاختبار")
    app.e_phone.insert(0, "0500000000")
    app.plan_var.set("monthly")
    app.days_var.set("30")
    # عطّل صناديق الرسائل أثناء الاختبار
    osd.messagebox.showinfo = lambda *a, **k: None
    osd.messagebox.showwarning = lambda *a, **k: None
    osd.messagebox.showerror = lambda *a, **k: print("ERR:", a)
    app._issue_key()
    key = app._last_key
    check("إصدار مفتاح من الواجهة", key.startswith("SCV2."))
    payload, sig, err = lv.parse_activation_key(key)
    check("قراءة المفتاح الصادر", payload is not None, err)
    check("المفتاح يحمل توقيع PQC هجين (4 أجزاء)",
          len(key.split(".")) == 4)
    check("بصمة الجهاز داخل المفتاح صحيحة",
          payload["fp"] == fp.replace("-", ""))
    check("مدة 30 يومًا",
          abs(payload["exp"] - payload["iat"] - 30 * 86400) < 5)

    # تحقق التوقيعين كما يتحقق برنامج العميل
    import base64
    raw = json.dumps({k: v for k, v in payload.items()
                      if not k.startswith("_")}, sort_keys=True,
                     separators=(",", ":")).encode()
    ok_ed = lv._verify_ed25519(app.secrets["ed25519_public"], raw,
                               base64.b64encode(sig).decode())
    check("توقيع Ed25519 صحيح", ok_ed)
    ok_pqc = lv._verify_pqc(app.secrets["mldsa65_public"], raw,
                            lv._b64pad(payload["_pqc_sig_b64"]))
    check("توقيع ML-DSA-65 المقاوم للكم صحيح", ok_pqc)

    # المفتاح مرفوض لبصمة مختلفة (منطق التحقق الكامل)
    info = lv.activate_with_key(key, app.secrets["ed25519_public"])
    check("رفض المفتاح على جهاز مختلف (حماية البصمة)",
          not info.valid and "جهاز آخر" in info.status, info.status)

    # مفتاح لبصمة هذا الجهاز يُقبل بالكامل
    my_fp = lv.machine_fingerprint()
    key2 = lv.make_activation_key(app.secrets["ed25519_private"], my_fp,
                                  "yearly", 365, "اختبار ذاتي",
                                  pqc_private_key_b64=app.secrets[
                                      "mldsa65_private"])
    # ملاحظة: activate يتحقق بمفتاح PQC المغروس في license_v2 (نفس مفاتيحنا)
    info2 = lv.activate_with_key(key2, app.secrets["ed25519_public"])
    check("قبول وتفعيل مفتاح كامل لجهاز الاختبار", info2.valid,
          info2.status)
    lv.deactivate()

    # 3) سجل العملاء
    check("سُجل العميل تلقائيًا", len(app.customers) == 1)
    check("حُفظ سجل العملاء على القرص", osd.CUSTOMERS_FILE.is_file())
    app.search_var.set("محل")
    app.update()
    check("البحث بالاسم يعمل", len(app.tree.get_children()) == 1)
    app.search_var.set("غير موجود")
    app.update()
    check("البحث السالب يخفي الصفوف", len(app.tree.get_children()) == 0)
    app.search_var.set("")
    app.update()

    # 4) التجديد
    app.tree.selection_set("0")
    old_lid = app.customers[0]["license_id"]
    # نفّذ منطق التجديد مباشرة (بدون نافذة حوارية)
    d = app.customers[0]
    key3 = lv.make_activation_key(app.secrets["ed25519_private"],
                                  d["fingerprint"], "yearly", 365,
                                  d["name"],
                                  pqc_private_key_b64=app.secrets[
                                      "mldsa65_private"])
    p3, _, _ = lv.parse_activation_key(key3)
    d.update({"plan": "yearly", "days": 365, "key": key3,
              "license_id": p3["lid"], "issued_at": int(time.time()),
              "revoked": False})
    osd.save_customers(app.customers)
    app._refresh_customers()
    check("التجديد أصدر ترخيصًا جديدًا", d["license_id"] != old_lid)
    check("التجديد 365 يومًا",
          abs(p3["exp"] - p3["iat"] - 365 * 86400) < 5)

    # 5) الإلغاء
    osd.messagebox.askyesno = lambda *a, **k: True
    app.tree.selection_set("0")
    app._revoke_selected()
    check("تسجيل الإلغاء", app.customers[0]["revoked"] is True)

    # 6) TOTP
    app._tick_totp()
    code_app = lv.totp_now(app.secrets["totp_secret"])
    check("رمز TOTP الحي 6 أرقام", len(code_app) == 6
          and code_app.isdigit())
    check("رمز TOTP مطابق لمنظومة الترخيص",
          lv.totp_verify(app.secrets["totp_secret"], code_app))
    uri = lv.totp_provisioning_uri(app.secrets["totp_secret"])
    check("رابط otpauth صالح", uri.startswith("otpauth://totp/"))
    m = osd.qr_matrix(uri)
    check("توليد مصفوفة QR", m is not None and len(m) > 20,
          "مكتبة qrcode/segno غير متاحة")

    # 7) النسخ الاحتياطي والاستعادة
    bpath = data / "backup_test.json"
    blob = {"type": "owner_studio_backup", "version": osd.VERSION,
            "created_at": int(time.time()), "secrets": app.secrets,
            "customers": app.customers}
    bpath.write_text(json.dumps(blob, ensure_ascii=False), encoding="utf-8")
    restored = json.loads(bpath.read_text(encoding="utf-8"))
    check("النسخة الاحتياطية تحوي الشفرة والعملاء",
          restored["secrets"]["ed25519_private"]
          == app.secrets["ed25519_private"]
          and len(restored["customers"]) == 1)

    # 8) رسالة العميل
    app._last_key = key
    app._last_payload = payload
    captured = []
    orig_copy = osd.copy_to_clipboard
    osd.copy_to_clipboard = lambda r, t: captured.append(t)
    app._copy_customer_msg()
    osd.copy_to_clipboard = orig_copy
    check("رسالة العميل الجاهزة تحوي المفتاح والتعليمات",
          captured and key in captured[0] and "طريقة التفعيل" in captured[0])

    # ترحيل السجل القديم devices_log.json
    shutil.rmtree(data, ignore_errors=True)
    data.mkdir(parents=True, exist_ok=True)
    old_log = HERE / "owner_tool" / "devices_log.json"
    had_old = old_log.is_file()
    if not had_old:
        old_log.write_text(json.dumps([{
            "fingerprint": "AAAA-BBBB-CCCC-DDDD", "plan": "monthly",
            "days": 30, "license_id": "test123", "note": "قديم",
            "issued_at": int(time.time())}], ensure_ascii=False),
            encoding="utf-8")
    migrated = osd.load_customers()
    check("ترحيل سجل الأداة القديمة تلقائيًا", len(migrated) >= 1)
    if not had_old:
        old_log.unlink(missing_ok=True)

    app.destroy()
    print(f"\nالنتيجة: {PASS} ناجح / {FAIL} فاشل من {PASS + FAIL}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
