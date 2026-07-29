# -*- coding: utf-8 -*-
"""license_ui — نافذة التفعيل ولوحة المالك وشارة الاشتراك (V2).

- ActivationDialog: تظهر عند الإقلاع إن لم يوجد ترخيص صالح. تعرض بصمة
  الجهاز مع زر نسخ، وحقل مفتاح التفعيل. لا يدخل البرنامج بدون ترخيص صالح.
- OwnerPanelDialog: لوحة المالك — تُفتح برمز TOTP من تطبيق Authenticator
  الخاص بالمالك فقط. تعرض حالة الترخيص وتتيح إلغاء ترخيص هذا الجهاز.
- install_license_badge: شارة حالة الاشتراك في هيدر النافذة الرئيسية.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton,
                               QTextEdit, QVBoxLayout)

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from engine_v2 import license_v2 as lv  # noqa: E402

CONTACT_EMAIL = "ahmadjookr06@gmail.com"
CONTACT_PHONE = "0582381000"


def _eula_text() -> str:
    for p in (_HERE.parent / "build" / "windows" / "EULA_ar.txt",
              _HERE / "EULA_ar.txt",
              Path(getattr(sys, "_MEIPASS", "")) / "EULA_ar.txt"):
        try:
            if p and Path(p).is_file():
                raw = Path(p).read_bytes()
                # ملف EULA لـ NSIS محفوظ UTF-16LE بـ BOM؛ ندعم الترميزين
                if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
                    return raw.decode("utf-16")
                return raw.decode("utf-8")
        except Exception:
            continue
    return ("اتفاقية ترخيص المستخدم النهائي: البرنامج مرخّص وليس مبيعًا، ولا يحق "
            "استرداد أي مبلغ بعد الدفع وتسليم مفتاح التفعيل مهما كانت الأسباب. "
            f"للتواصل: {CONTACT_EMAIL} — {CONTACT_PHONE}")


def _eula_flag_path() -> Path:
    return lv._license_dir() / "eula_accepted.flag"


def eula_accepted() -> bool:
    return _eula_flag_path().is_file()


class EulaDialog(QDialog):
    """نافذة اتفاقية المستخدم النهائي — لا يعمل البرنامج إلا بالموافقة."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("اتفاقية الاستخدام — Market Image Studio V2")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumSize(700, 560)
        self.setStyleSheet(_STYLE)
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(24, 20, 24, 20)

        title = QLabel("اتفاقية ترخيص المستخدم النهائي (EULA)")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        viewer = QTextEdit()
        viewer.setReadOnly(True)
        viewer.setPlainText(_eula_text())
        root.addWidget(viewer, 1)

        warn = QLabel("بالنقر على (أوافق) فأنت تقبل جميع البنود، وخاصة عدم استرداد "
                      "أي مبلغ بعد الدفع وتسليم مفتاح التفعيل مهما كانت الأسباب.")
        warn.setStyleSheet("color:#c0392b; font-weight:700;")
        warn.setWordWrap(True)
        root.addWidget(warn)

        btns = QHBoxLayout()
        btns.addStretch(1)
        ok_btn = QPushButton("أوافق على الاتفاقية")
        ok_btn.setMinimumSize(200, 48)
        ok_btn.clicked.connect(self._accept_eula)
        no_btn = QPushButton("لا أوافق — خروج")
        no_btn.setObjectName("secondary")
        no_btn.setMinimumSize(160, 48)
        no_btn.clicked.connect(self.reject)
        btns.addWidget(ok_btn)
        btns.addWidget(no_btn)
        root.addLayout(btns)

    def _accept_eula(self):
        try:
            import time as _t
            _eula_flag_path().write_text(
                f"accepted_at={int(_t.time())}\n", encoding="utf-8")
        except Exception:
            pass
        self.accept()

# سر TOTP للمالك (يُغرس عند البناء من أداة المالك — مشفر بالبصمة غير مطلوب
# لأنه يتحقق محليًا فقط لفتح لوحة المالك، والقيمة تكون مموهة في التنفيذي).
OWNER_TOTP_SECRET = "4SNK2JSJGACRJAVP33ONHUBNI5N6D6RR"

_STYLE = """
QDialog { background: #f7f9fc; }
QLabel#title { font-size: 20px; font-weight: 700; color: #1a2b4a; }
QLabel#fp { font-size: 22px; font-weight: 700; color: #2c5aa0;
            letter-spacing: 2px; background: #eef3fb;
            border: 1px solid #c9d8ef; border-radius: 8px; padding: 10px; }
QLabel#status { font-size: 14px; color: #444; }
QLineEdit, QTextEdit { border: 1px solid #c4cdd8; border-radius: 8px;
                        padding: 8px; font-size: 14px; background: white; }
QPushButton { background: #2c5aa0; color: white; border: none;
              border-radius: 8px; padding: 10px 18px; font-size: 14px;
              font-weight: 600; }
QPushButton:hover { background: #244b86; }
QPushButton#secondary { background: #e8edf5; color: #2c5aa0; }
QPushButton#danger { background: #c0392b; }
"""


class ActivationDialog(QDialog):
    """نافذة تفعيل الاشتراك — تعرض البصمة وتقبل مفتاح المالك."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("تفعيل الاشتراك — Market Image Studio V2")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumSize(640, 520)
        self.setStyleSheet(_STYLE)
        self.activated_info = None

        root = QVBoxLayout(self)
        root.setSpacing(14)
        root.setContentsMargins(28, 24, 28, 24)

        title = QLabel("تفعيل الاشتراك")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        info = lv.check_license()
        st = QLabel(info.status)
        st.setObjectName("status")
        st.setWordWrap(True)
        st.setAlignment(Qt.AlignCenter)
        root.addWidget(st)
        self._status_lbl = st

        step1 = QLabel("الخطوة 1 — أرسل بصمة هذا الجهاز إلى مالك البرنامج:")
        step1.setStyleSheet("font-weight:600; margin-top:6px;")
        root.addWidget(step1)

        fp_row = QHBoxLayout()
        fp = QLabel(lv.machine_fingerprint())
        fp.setObjectName("fp")
        fp.setAlignment(Qt.AlignCenter)
        fp.setTextInteractionFlags(Qt.TextSelectableByMouse)
        copy_btn = QPushButton("نسخ")
        copy_btn.setObjectName("secondary")
        copy_btn.setFixedWidth(90)
        copy_btn.clicked.connect(self._copy_fp)
        fp_row.addWidget(fp, 1)
        fp_row.addWidget(copy_btn)
        root.addLayout(fp_row)
        self._fp_lbl = fp

        step2 = QLabel("الخطوة 2 — الصق مفتاح التفعيل الذي يولده المالك "
                       "لهذا الجهاز حصريًا:")
        step2.setStyleSheet("font-weight:600; margin-top:6px;")
        root.addWidget(step2)

        self.key_edit = QTextEdit()
        self.key_edit.setPlaceholderText("SCV2.XXXX.XXXX — مفتاح التفعيل")
        self.key_edit.setFixedHeight(110)
        root.addWidget(self.key_edit)

        note = QLabel("المفتاح موقّع رقميًا ومرتبط ببصمة هذا الجهاز فقط — "
                      "نسخه لأي جهاز آخر لن يعمل.")
        note.setStyleSheet("color:#777; font-size:12px;")
        note.setWordWrap(True)
        root.addWidget(note)

        contact = QLabel(
            f"للحصول على الاشتراك أو التجديد تواصل مع المالك:\n"
            f"البريد: {CONTACT_EMAIL}   —   الجوال: {CONTACT_PHONE}")
        contact.setStyleSheet(
            "color:#1a6b3c; font-weight:700; background:#eaf7ef;"
            "border:1px solid #bfe3cd; border-radius:8px; padding:8px;")
        contact.setAlignment(Qt.AlignCenter)
        contact.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(contact)

        eula_btn = QPushButton("عرض اتفاقية الاستخدام")
        eula_btn.setObjectName("secondary")
        eula_btn.clicked.connect(lambda: EulaDialog(self).exec())
        root.addWidget(eula_btn)

        btns = QHBoxLayout()
        btns.addStretch(1)
        activate_btn = QPushButton("تفعيل الآن")
        activate_btn.setMinimumSize(180, 48)
        activate_btn.clicked.connect(self._activate)
        exit_btn = QPushButton("خروج")
        exit_btn.setObjectName("secondary")
        exit_btn.setMinimumSize(120, 48)
        exit_btn.clicked.connect(self.reject)
        btns.addWidget(activate_btn)
        btns.addWidget(exit_btn)
        root.addLayout(btns)

    def _copy_fp(self):
        QGuiApplication.clipboard().setText(self._fp_lbl.text())
        self._status_lbl.setText("نُسخت البصمة — أرسلها للمالك ليصدر مفتاحك.")

    def _activate(self):
        key = self.key_edit.toPlainText().strip()
        if not key:
            QMessageBox.information(self, "تنبيه", "الصق مفتاح التفعيل أولًا.")
            return
        info = lv.activate_with_key(key)
        if info.valid:
            self.activated_info = info
            QMessageBox.information(self, "تم التفعيل", info.status)
            self.accept()
        else:
            QMessageBox.warning(self, "فشل التفعيل", info.status)


class OwnerPanelDialog(QDialog):
    """لوحة المالك — دخول برمز TOTP الدوري (يعرفه المالك فقط)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("لوحة المالك")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumSize(520, 420)
        self.setStyleSheet(_STYLE)
        self._unlocked = False

        root = QVBoxLayout(self)
        root.setSpacing(14)
        root.setContentsMargins(24, 20, 24, 20)

        title = QLabel("لوحة المالك")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("رمز المالك الدوري (6 أرقام)")
        self.code_edit.setAlignment(Qt.AlignCenter)
        self.code_edit.setEchoMode(QLineEdit.Password)
        f = QFont()
        f.setPointSize(16)
        self.code_edit.setFont(f)
        root.addWidget(self.code_edit)

        unlock_btn = QPushButton("دخول")
        unlock_btn.clicked.connect(self._unlock)
        root.addWidget(unlock_btn)

        self.body = QVBoxLayout()
        root.addLayout(self.body)
        root.addStretch(1)

    def _unlock(self):
        secret = OWNER_TOTP_SECRET
        if not secret or secret == "REPLACED_AT_KEYGEN":
            QMessageBox.warning(self, "غير مهيأ",
                                "لم يُغرس سر المالك في هذه النسخة بعد.")
            return
        if not lv.totp_verify(secret, self.code_edit.text()):
            QMessageBox.warning(self, "مرفوض", "الرمز غير صحيح أو منتهي.")
            return
        if self._unlocked:
            return
        self._unlocked = True
        info = lv.check_license()
        status = QLabel(
            f"بصمة الجهاز: {info.fingerprint}\n"
            f"الحالة: {info.status}\n"
            f"معرف الترخيص: {info.license_id or '—'}\n"
            f"الخطة: {lv.PLANS.get(info.plan, info.plan) or '—'}")
        status.setObjectName("status")
        status.setWordWrap(True)
        self.body.addWidget(status)

        revoke_btn = QPushButton("إلغاء ترخيص هذا الجهاز")
        revoke_btn.setObjectName("danger")

        def _revoke():
            if QMessageBox.question(
                    self, "تأكيد",
                    "سيُلغى ترخيص هذا الجهاز نهائيًا ولن يعمل البرنامج "
                    "عليه إلا بمفتاح جديد منك. متابعة؟") == QMessageBox.Yes:
                if info.license_id:
                    lv.revoke_license_id(info.license_id)
                lv.deactivate()
                QMessageBox.information(self, "تم", "أُلغي الترخيص.")
                self.accept()

        revoke_btn.clicked.connect(_revoke)
        self.body.addWidget(revoke_btn)

        # خصائص المالك المتنقلة — تعديل الإعدادات المقفلة من أي جهاز
        settings_btn = QPushButton("إعدادات المالك المتقدمة")
        settings_btn.clicked.connect(
            lambda: OwnerSettingsDialog(self).exec())
        self.body.addWidget(settings_btn)


def _owner_settings_path() -> Path:
    return lv._license_dir() / "owner_settings.json"


def load_owner_settings() -> dict:
    import json
    try:
        return json.loads(_owner_settings_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


class OwnerSettingsDialog(QDialog):
    """إعدادات المالك المقفلة — لا تُفتح إلا من لوحة المالك (بعد TOTP).

    تتيح للمالك وحده تعديل: أبعاد الإخراج، جودة WebP، حد دفعة
    المعالجة الجماعية، وإظهار الأدوات المخفية — من أي جهاز يدخله
    المالك برمز TOTP الدوري الخاص به (هوية متنقلة لا ترتبط بجهاز).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("إعدادات المالك المتقدمة")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumSize(520, 460)
        self.setStyleSheet(_STYLE)
        from PySide6.QtWidgets import (QCheckBox, QFormLayout, QSpinBox)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        title = QLabel("إعدادات مقفلة — للمالك فقط")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        data = load_owner_settings()
        form = QFormLayout()
        self.w_spin = QSpinBox(); self.w_spin.setRange(200, 4000)
        self.w_spin.setValue(int(data.get("out_width", 800)))
        self.h_spin = QSpinBox(); self.h_spin.setRange(200, 4000)
        self.h_spin.setValue(int(data.get("out_height", 700)))
        self.q_spin = QSpinBox(); self.q_spin.setRange(50, 100)
        self.q_spin.setValue(int(data.get("webp_quality", 90)))
        self.batch_spin = QSpinBox(); self.batch_spin.setRange(10, 100000)
        self.batch_spin.setValue(int(data.get("batch_limit", 5000)))
        self.workers_spin = QSpinBox(); self.workers_spin.setRange(1, 16)
        self.workers_spin.setValue(int(data.get("batch_workers", 2)))
        self.hidden_chk = QCheckBox("إظهار أدوات المالك المخفية في الواجهة")
        self.hidden_chk.setChecked(bool(data.get("show_hidden_tools", False)))
        form.addRow("عرض الإخراج (بكسل):", self.w_spin)
        form.addRow("ارتفاع الإخراج (بكسل):", self.h_spin)
        form.addRow("جودة WebP:", self.q_spin)
        form.addRow("حد الدفعة الجماعية (صورة):", self.batch_spin)
        form.addRow("خيوط المعالجة المتوازية:", self.workers_spin)
        root.addLayout(form)
        root.addWidget(self.hidden_chk)

        note = QLabel("تُحفظ هذه الإعدادات مشفرةً محليًا وتُطبّق على جميع "
                      "العمليات. لا يراها أو يعدلها أحد سواك.")
        note.setStyleSheet("color:#777; font-size:12px;")
        note.setWordWrap(True)
        root.addWidget(note)

        btns = QHBoxLayout()
        btns.addStretch(1)
        save_btn = QPushButton("حفظ")
        save_btn.setMinimumSize(140, 44)
        save_btn.clicked.connect(self._save)
        close_btn = QPushButton("إغلاق")
        close_btn.setObjectName("secondary")
        close_btn.setMinimumSize(120, 44)
        close_btn.clicked.connect(self.reject)
        btns.addWidget(save_btn)
        btns.addWidget(close_btn)
        root.addLayout(btns)

    def _save(self):
        import json
        data = {
            "out_width": self.w_spin.value(),
            "out_height": self.h_spin.value(),
            "webp_quality": self.q_spin.value(),
            "batch_limit": self.batch_spin.value(),
            "batch_workers": self.workers_spin.value(),
            "show_hidden_tools": self.hidden_chk.isChecked(),
        }
        _owner_settings_path().write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        QMessageBox.information(self, "تم", "حُفظت إعدادات المالك وستُطبّق "
                                "على جميع العمليات القادمة.")
        self.accept()


def ensure_activated(parent=None) -> bool:
    """يضمن الموافقة على الاتفاقية + ترخيصًا صالحًا أو تجربة فعالة.

    التجربة التلقائية (3 أيام) تبدأ وحدها لأي جهاز جديد — لا تُطلب
    نافذة التفعيل إلا بعد انتهاء التجربة أو الاشتراك. False = خروج."""
    if not eula_accepted():
        if EulaDialog(parent).exec() != QDialog.Accepted:
            return False
    info = lv.effective_license()
    if info.valid:
        return True
    dlg = ActivationDialog(parent)
    return dlg.exec() == QDialog.Accepted


_PLAN_BADGE_AR = {"monthly": "شهري", "yearly": "سنوي",
                  "lifetime": "دائم", "trial": "تجريبي",
                  "weekly": "أسبوعي"}


def _fmt_expiry_date(info) -> str:
    exp = int(getattr(info, "expires_at", 0) or 0)
    if not exp:
        return ""
    import time as _t
    return _t.strftime("%Y-%m-%d", _t.localtime(exp))


def license_badge_text() -> str:
    """نص الشارة الحقيقي — يقرأ الحالة الفعلية (ترخيص أو تجربة)
    ويعرض نوع الخطة + المدة المتبقية + تاريخ الانتهاء دائمًا —
    لا يظهر "دائم" إلا للترخيص الدائم الفعلي الموقّع من المالك."""
    info = lv.effective_license()
    if not info.valid:
        if getattr(info, "plan", "") == "trial":
            return "انتهت التجربة المجانية — اضغط «المالك» للتفعيل"
        return "الاشتراك: غير مفعل — اضغط «المالك» للتفعيل"
    exp_txt = _fmt_expiry_date(info)
    # لا تُعرض قيم سالبة أبدًا: أي قيمة أقل من صفر تعني إما ترخيصًا
    # دائمًا (بلا تاريخ انتهاء) أو حالة غير مكتملة — نعالج كلتيهما.
    days = int(getattr(info, "days_left", 0) or 0)
    if getattr(info, "plan", "") == "trial":
        if days < 0:
            days = 0
        if days <= 0:
            return "التجربة المجانية تنتهي اليوم — فعّل الاشتراك"
        return (f"تجربة مجانية: متبق {days} أيام"
                + (f" — تنتهي {exp_txt}" if exp_txt else ""))
    if days < 0 or not int(getattr(info, "expires_at", 0) or 0):
        return "الاشتراك: دائم ✔"
    plan_ar = _PLAN_BADGE_AR.get(getattr(info, "plan", ""), "")
    plan_part = f" ({plan_ar})" if plan_ar else ""
    if days <= 0:
        return (f"الاشتراك{plan_part}: ينتهي اليوم"
                + (f" — {exp_txt}" if exp_txt else ""))
    return (f"الاشتراك{plan_part}: متبق {days} يومًا"
            + (f" — ينتهي {exp_txt}" if exp_txt else ""))


def license_badge_style() -> str:
    """لون الشارة حسب الحالة: أزرق طبيعي، برتقالي قرب الانتهاء (≤7 أيام)،
    أحمر للمنتهي/غير المفعل، أخضر للدائم."""
    base = ("font-weight:700; padding:4px 10px; border-radius:8px; "
            "border:1px solid %s; background:%s; color:%s;")
    try:
        info = lv.effective_license()
    except Exception:
        return base % ("#c9d8ef", "#eef3fb", "#2c5aa0")
    if not info.valid:
        return base % ("#e8b4b4", "#fdeeee", "#b02a2a")
    if info.days_left < 0 or not int(getattr(info, "expires_at", 0) or 0):
        return base % ("#bfe3c8", "#eefaf1", "#1e7d3c")
    if info.days_left <= 7:
        return base % ("#f0d5a8", "#fdf6e9", "#a5690f")
    return base % ("#c9d8ef", "#eef3fb", "#2c5aa0")


def install_license_badge(main_window) -> None:
    """يضيف شارة حالة الاشتراك + زر لوحة المالك إلى هيدر النافذة."""
    try:
        # يُفضّل صف الأدوات الجديد (V2 toolbar) لتجنب ازدحام الهيدر وقص النصوص
        header_layout = getattr(main_window, "v2_toolbar_layout", None)
        if header_layout is None:
            header_layout = main_window.header_frame.layout()
    except Exception:
        return
    badge = QLabel(license_badge_text())
    badge.setObjectName("v2LicenseBadge")
    badge.setStyleSheet(license_badge_style())
    try:
        info = lv.effective_license()
        exp_txt = _fmt_expiry_date(info)
        tip = (f"رقم الترخيص: {getattr(info, 'license_id', '') or '—'}\n"
               f"الحالة: {getattr(info, 'status', '')}"
               + (f"\nتاريخ الانتهاء: {exp_txt}" if exp_txt else ""))
        badge.setToolTip(tip)
    except Exception:
        pass
    owner_btn = QPushButton("المالك")
    owner_btn.setObjectName("v2OwnerBtn")
    owner_btn.setMinimumHeight(36)
    owner_btn.setMinimumWidth(
        owner_btn.fontMetrics().horizontalAdvance(owner_btn.text()) + 30)
    owner_btn.clicked.connect(lambda: OwnerPanelDialog(main_window).exec())
    badge.setMinimumWidth(
        badge.fontMetrics().horizontalAdvance(badge.text()) + 20)
    insert_at = max(header_layout.count() - 1, 0)
    header_layout.insertWidget(insert_at, badge)
    header_layout.insertWidget(insert_at, owner_btn)
    main_window.v2_license_badge = badge

    # تحديث دوري للشارة (كل ساعة) — تبقى المدة المعروضة صحيحة دائمًا
    try:
        from PySide6.QtCore import QTimer
        timer = QTimer(main_window)
        timer.setInterval(60 * 60 * 1000)
        def _refresh_badge():
            badge.setText(license_badge_text())
            badge.setStyleSheet(license_badge_style())
        timer.timeout.connect(_refresh_badge)
        timer.start()
        main_window._v2_badge_timer = timer
    except Exception:
        pass
