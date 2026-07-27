# -*- coding: utf-8 -*-
"""استوديو المالك — Ahmed Al-Faifi Owner Studio 1.0

برنامج رسومي عربي مبسط يجمع كل أعمال المالك في مكان واحد:
  • إصدار مفاتيح التفعيل للمشترين (بنقرة واحدة)
  • سجل العملاء والأجهزة والتراخيص مع البحث
  • تمديد الاشتراكات وتسجيل الإلغاء
  • رمز TOTP الحي + رمز QR لإضافته إلى Google Authenticator
  • نسخ احتياطي واستعادة لشفرة المالك
  • توليد ملفات إلغاء موقّعة

سري للغاية — هذا البرنامج للمالك (أحمد الفيفي) وحده، لا يُوزَّع أبدًا.
جميع الحقوق محفوظة © أحمد الفيفي 2026.
"""
from __future__ import annotations

import json
import os
import sys
import time
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# ------------------------------------------------------------------ paths
def _base_dir() -> Path:
    """مجلد البرنامج (يدعم PyInstaller onefile/onedir والتشغيل المباشر)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def _data_dir() -> Path:
    """مجلد بيانات المالك: بجانب البرنامج (محمول) لسهولة النسخ الاحتياطي."""
    d = _base_dir() / "بيانات_المالك"
    d.mkdir(parents=True, exist_ok=True)
    return d


BASE = _base_dir()
DATA = _data_dir()
SECRETS_FILE = DATA / "owner_secrets.json"
CUSTOMERS_FILE = DATA / "customers.json"

# ------------------------------------------------- license engine imports
# يعمل من داخل المشروع (بجانب src) أو نسخة مجمّعة تحمل license_v2 داخلها
_src_candidates = [
    BASE.parent / "src",                      # app_v2/owner_studio -> app_v2/src
    BASE / "src",
    BASE.parent.parent / "app_v2" / "src",
]
for _c in _src_candidates:
    if (_c / "engine_v2").is_dir():
        sys.path.insert(0, str(_c))
        break

try:
    from engine_v2 import license_v2 as lv
except Exception:  # pragma: no cover
    lv = None

APP_TITLE = "استوديو المالك — Market Image Studio"
VERSION = "1.0.0"

# ------------------------------------------------------------------ ألوان
C_BG = "#101418"          # خلفية داكنة أنيقة
C_PANEL = "#1a2129"
C_CARD = "#212a35"
C_GOLD = "#d4a843"        # ذهبي — هوية المالك
C_TEXT = "#e8e6e3"
C_SUB = "#9aa5b1"
C_GREEN = "#3ddc84"
C_RED = "#ff5c5c"
C_BLUE = "#4da3ff"

F_TITLE = ("Segoe UI", 17, "bold")
F_H = ("Segoe UI", 13, "bold")
F_BODY = ("Segoe UI", 11)
F_SMALL = ("Segoe UI", 9)
F_MONO = ("Consolas", 10)
F_CODE_BIG = ("Consolas", 26, "bold")


# ================================================================== data
def load_secrets() -> dict | None:
    """يبحث عن شفرة المالك في مجلد البيانات ثم بجانب البرنامج."""
    for p in (SECRETS_FILE, BASE / "owner_secrets.json",
              BASE.parent.parent / "owner_tool" / "owner_secrets.json"):
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
    return None


def save_secrets(sec: dict) -> None:
    SECRETS_FILE.write_text(
        json.dumps(sec, ensure_ascii=False, indent=2), encoding="utf-8")


def load_customers() -> list[dict]:
    if CUSTOMERS_FILE.is_file():
        try:
            return json.loads(CUSTOMERS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    # ترحيل تلقائي من سجل الأداة القديمة devices_log.json إن وجد
    old = BASE.parent.parent / "owner_tool" / "devices_log.json"
    if old.is_file():
        try:
            legacy = json.loads(old.read_text(encoding="utf-8"))
            migrated = [{
                "name": d.get("note", "") or "عميل",
                "phone": "", "fingerprint": d.get("fingerprint", ""),
                "plan": d.get("plan", ""), "days": d.get("days", 0),
                "license_id": d.get("license_id", ""),
                "issued_at": d.get("issued_at", 0),
                "revoked": d.get("revoked", False),
                "key": "", "note": d.get("note", ""),
            } for d in legacy]
            save_customers(migrated)
            return migrated
        except Exception:
            pass
    return []


def save_customers(rows: list[dict]) -> None:
    CUSTOMERS_FILE.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


PLAN_AR = {"monthly": "شهري", "yearly": "سنوي",
           "lifetime": "دائم", "trial": "تجريبي"}
PLAN_DAYS = {"monthly": 30, "yearly": 365, "lifetime": 0, "trial": 7}


def fmt_expiry(issued_at: int, days: int) -> str:
    if days <= 0:
        return "دائم"
    return time.strftime("%Y-%m-%d",
                         time.localtime(issued_at + days * 86400))


def days_left(issued_at: int, days: int) -> int:
    if days <= 0:
        return -1
    return max(0, int((issued_at + days * 86400 - time.time()) // 86400))


# ============================================================ QR (ذاتي)
def qr_matrix(text: str):
    """توليد مصفوفة QR — يحاول qrcode ثم segno ثم يعيد None."""
    try:
        import qrcode
        qr = qrcode.QRCode(border=2,
                           error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(text)
        qr.make(fit=True)
        return [[bool(c) for c in row] for row in qr.get_matrix()]
    except Exception:
        pass
    try:
        import segno
        q = segno.make(text, error="m")
        return [[bool(c) for c in row] for row in q.matrix]
    except Exception:
        return None


# =============================================================== widgets
class Card(tk.Frame):
    def __init__(self, master, **kw):
        super().__init__(master, bg=C_CARD, bd=0,
                         highlightbackground="#2e3947",
                         highlightthickness=1, **kw)


def gold_button(master, text, command, big=False, color=C_GOLD,
                fg="#161005") -> tk.Button:
    return tk.Button(
        master, text=text, command=command, bg=color, fg=fg,
        activebackground="#e8c063", activeforeground=fg,
        font=("Segoe UI", 12 if big else 10, "bold"),
        relief="flat", cursor="hand2", padx=18, pady=10 if big else 6, bd=0)


def ghost_button(master, text, command) -> tk.Button:
    return tk.Button(
        master, text=text, command=command, bg=C_PANEL, fg=C_TEXT,
        activebackground=C_CARD, activeforeground=C_TEXT,
        font=("Segoe UI", 10), relief="flat", cursor="hand2",
        padx=12, pady=6, bd=0, highlightbackground="#2e3947",
        highlightthickness=1)


def copy_to_clipboard(root: tk.Tk, text: str) -> None:
    root.clipboard_clear()
    root.clipboard_append(text)
    root.update()


# ============================================================== main app
class OwnerStudio(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_TITLE} {VERSION}")
        self.configure(bg=C_BG)
        self.geometry("1180x760")
        self.minsize(1024, 660)
        try:
            icon = BASE / "assets" / "owner_icon.png"
            if not icon.is_file():
                icon = (BASE.parent / "windows_app" / "assets"
                        / "app_icon_v2.png")
            if icon.is_file():
                self.iconphoto(True, tk.PhotoImage(file=str(icon)))
        except Exception:
            pass

        self.secrets = load_secrets()
        self.customers = load_customers()
        self._totp_job = None

        if lv is None:
            messagebox.showerror(
                "خطأ", "تعذر تحميل منظومة الترخيص license_v2 — "
                "تأكد أن البرنامج داخل مجلد المشروع أو أن النسخة مجمّعة "
                "بشكل صحيح.")
            self.destroy()
            return

        if not self.secrets:
            self._first_run_screen()
        else:
            self._build_main_ui()

    # ---------------------------------------------------- أول تشغيل
    def _first_run_screen(self):
        for w in self.winfo_children():
            w.destroy()
        wrap = tk.Frame(self, bg=C_BG)
        wrap.pack(expand=True)
        tk.Label(wrap, text="مرحبًا بك في استوديو المالك",
                 font=F_TITLE, bg=C_BG, fg=C_GOLD).pack(pady=(30, 6))
        tk.Label(wrap, text="لم أجد شفرة المالك (owner_secrets.json) — اختر أحد الخيارين:",
                 font=F_BODY, bg=C_BG, fg=C_TEXT).pack(pady=(0, 24))

        c1 = Card(wrap)
        c1.pack(pady=8, ipadx=16, ipady=10, fill="x", padx=40)
        tk.Label(c1, text="لدي ملف owner_secrets.json (الحالة الطبيعية)",
                 font=F_H, bg=C_CARD, fg=C_TEXT).pack(anchor="e",
                                                      padx=14, pady=(10, 2))
        tk.Label(c1, text="استورد الملف الذي استلمته في حزمة التسليم — ستبقى كل تراخيصك السارية تعمل.",
                 font=F_BODY, bg=C_CARD, fg=C_SUB).pack(anchor="e", padx=14)
        gold_button(c1, "📂 استيراد شفرة المالك",
                    self._import_secrets, big=True).pack(pady=12)

        c2 = Card(wrap)
        c2.pack(pady=8, ipadx=16, ipady=10, fill="x", padx=40)
        tk.Label(c2, text="توليد شفرة مالك جديدة (لأول مرة فقط)",
                 font=F_H, bg=C_CARD, fg=C_TEXT).pack(anchor="e",
                                                      padx=14, pady=(10, 2))
        tk.Label(c2, text="تحذير: الشفرة الجديدة تبطل كل المفاتيح القديمة وتتطلب إعادة بناء البرنامج بالمفاتيح الجديدة.",
                 font=F_BODY, bg=C_CARD, fg=C_RED).pack(anchor="e", padx=14)
        ghost_button(c2, "توليد شفرة جديدة",
                     self._generate_new_secrets).pack(pady=12)

    def _import_secrets(self):
        p = filedialog.askopenfilename(
            title="اختر ملف owner_secrets.json",
            filetypes=[("ملف الشفرة", "*.json")])
        if not p:
            return
        try:
            sec = json.loads(Path(p).read_text(encoding="utf-8"))
            assert "ed25519_private" in sec and "totp_secret" in sec
        except Exception:
            messagebox.showerror("خطأ", "الملف المختار ليس شفرة مالك صالحة.")
            return
        save_secrets(sec)
        self.secrets = sec
        messagebox.showinfo("تم", "استُوردت شفرة المالك بنجاح وحُفظت في مجلد بيانات_المالك بجانب البرنامج.")
        self._build_main_ui()

    def _generate_new_secrets(self):
        if not messagebox.askyesno(
                "تأكيد", "هل أنت متأكد؟ الشفرة الجديدة تبطل كل مفاتيح "
                "التفعيل القديمة، ويجب إعادة بناء برنامج العملاء "
                "بالمفاتيح العامة الجديدة.\n\nهل تريد المتابعة؟"):
            return
        try:
            priv, pub = lv.generate_owner_keypair()
            pqc_priv, pqc_pub = lv.generate_pqc_keypair()
        except Exception as e:
            messagebox.showerror("خطأ", f"تعذر توليد المفاتيح: {e}")
            return
        sec = {
            "ed25519_private": priv, "ed25519_public": pub,
            "mldsa65_private": pqc_priv, "mldsa65_public": pqc_pub,
            "totp_secret": lv.generate_totp_secret(),
            "created_at": int(time.time()),
        }
        save_secrets(sec)
        self.secrets = sec
        messagebox.showinfo(
            "تم", "وُلدت شفرة مالك جديدة وحُفظت في مجلد بيانات_المالك.\n"
            "مهم: انسخ المفاتيح العامة من تبويب (الإعدادات) واغرسها في "
            "برنامج العملاء قبل البناء القادم.")
        self._build_main_ui()

    # ---------------------------------------------------- الواجهة الرئيسية
    def _build_main_ui(self):
        for w in self.winfo_children():
            w.destroy()

        # الشريط العلوي
        top = tk.Frame(self, bg=C_PANEL, height=64)
        top.pack(fill="x")
        top.pack_propagate(False)
        tk.Label(top, text="👑 استوديو المالك", font=F_TITLE,
                 bg=C_PANEL, fg=C_GOLD).pack(side="right", padx=18)
        tk.Label(top, text="Ahmed Al-Faifi Market Image Studio — إدارة كاملة بيدك وحدك",
                 font=F_SMALL, bg=C_PANEL, fg=C_SUB).pack(side="right")
        self.totp_top = tk.Label(top, text="", font=("Consolas", 15, "bold"),
                                 bg=C_PANEL, fg=C_GREEN, cursor="hand2")
        self.totp_top.pack(side="left", padx=18)
        self.totp_top.bind("<Button-1>", lambda e: self._copy_totp())

        # التبويبات
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TNotebook", background=C_BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=C_PANEL, foreground=C_TEXT,
                        font=("Segoe UI", 11, "bold"), padding=[18, 9])
        style.map("TNotebook.Tab",
                  background=[("selected", C_GOLD)],
                  foreground=[("selected", "#161005")])
        style.configure("Treeview", background=C_CARD, fieldbackground=C_CARD,
                        foreground=C_TEXT, rowheight=30,
                        font=("Segoe UI", 10))
        style.configure("Treeview.Heading", background=C_PANEL,
                        foreground=C_GOLD, font=("Segoe UI", 10, "bold"))
        style.map("Treeview", background=[("selected", "#33475e")])

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=8)

        self.tab_issue = tk.Frame(self.nb, bg=C_BG)
        self.tab_customers = tk.Frame(self.nb, bg=C_BG)
        self.tab_totp = tk.Frame(self.nb, bg=C_BG)
        self.tab_backup = tk.Frame(self.nb, bg=C_BG)
        self.tab_settings = tk.Frame(self.nb, bg=C_BG)

        self.nb.add(self.tab_issue, text="  🔑 إصدار مفتاح تفعيل  ")
        self.nb.add(self.tab_customers, text="  👥 العملاء والأجهزة  ")
        self.nb.add(self.tab_totp, text="  📱 رمز المالك TOTP  ")
        self.nb.add(self.tab_backup, text="  💾 النسخ الاحتياطي  ")
        self.nb.add(self.tab_settings, text="  ⚙️ الإعدادات  ")

        self._build_tab_issue()
        self._build_tab_customers()
        self._build_tab_totp()
        self._build_tab_backup()
        self._build_tab_settings()

        # شريط الحالة
        bar = tk.Frame(self, bg=C_PANEL, height=30)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)
        tk.Label(bar, text="جميع الحقوق محفوظة © أحمد الفيفي — سري: لا تشارك هذا البرنامج أو مجلد بيانات_المالك مع أي أحد",
                 font=F_SMALL, bg=C_PANEL, fg=C_SUB).pack(side="right",
                                                          padx=12)
        self._tick_totp()

    def _copy_totp(self):
        code = lv.totp_now(self.secrets["totp_secret"])
        copy_to_clipboard(self, code)

    def _tick_totp(self):
        try:
            code = lv.totp_now(self.secrets["totp_secret"])
            remain = 30 - int(time.time()) % 30
            self.totp_top.config(text=f"TOTP: {code} ({remain}ث)")
            if hasattr(self, "totp_big"):
                self.totp_big.config(text=code)
                self.totp_remain.config(
                    text=f"يتغير خلال {remain} ثانية — انقر الرمز لنسخه")
        except Exception:
            pass
        self._totp_job = self.after(1000, self._tick_totp)

    # =============================================== تبويب إصدار مفتاح
    def _build_tab_issue(self):
        t = self.tab_issue
        right = tk.Frame(t, bg=C_BG)
        right.pack(side="right", fill="both", expand=True, padx=(4, 12),
                   pady=10)
        left = tk.Frame(t, bg=C_BG)
        left.pack(side="left", fill="both", expand=True, padx=(12, 4),
                  pady=10)

        # --- نموذج الإصدار (يمين — يبدأ به العربي)
        form = Card(right)
        form.pack(fill="both", expand=True)
        tk.Label(form, text="إصدار مفتاح تفعيل جديد", font=F_H,
                 bg=C_CARD, fg=C_GOLD).pack(anchor="e", padx=16,
                                            pady=(14, 2))
        tk.Label(form,
                 text="املأ البيانات الثلاثة ثم اضغط (إصدار المفتاح) — يظهر المفتاح فورًا وتنسخه للمشتري",
                 font=F_SMALL, bg=C_CARD, fg=C_SUB).pack(anchor="e", padx=16)

        def field(label, hint=""):
            tk.Label(form, text=label, font=F_BODY, bg=C_CARD,
                     fg=C_TEXT).pack(anchor="e", padx=16, pady=(12, 2))
            e = tk.Entry(form, font=F_MONO, bg=C_PANEL, fg=C_TEXT,
                         insertbackground=C_TEXT, relief="flat",
                         justify="center")
            e.pack(fill="x", padx=16, ipady=8)
            if hint:
                tk.Label(form, text=hint, font=F_SMALL, bg=C_CARD,
                         fg=C_SUB).pack(anchor="e", padx=16)
            return e

        self.e_fp = field("١. بصمة جهاز المشتري",
                          "يرسلها لك المشتري من نافذة التفعيل — مثل: A3F2-9K1B-77CD-E2A0")
        self.e_name = field("٢. اسم العميل (اختياري لكنه مفيد للسجل)",
                            "مثال: محل النور للتموينات — أبها")
        self.e_phone = field("٣. جوال/واتساب العميل (اختياري)",
                             "مثال: 0501234567")

        tk.Label(form, text="٤. نوع الاشتراك", font=F_BODY, bg=C_CARD,
                 fg=C_TEXT).pack(anchor="e", padx=16, pady=(12, 4))
        pf = tk.Frame(form, bg=C_CARD)
        pf.pack(fill="x", padx=16)
        self.plan_var = tk.StringVar(value="yearly")
        self.days_var = tk.StringVar(value="365")

        def mk_plan(key, label, col):
            rb = tk.Radiobutton(
                pf, text=label, value=key, variable=self.plan_var,
                command=self._plan_changed, bg=C_CARD, fg=C_TEXT,
                selectcolor=C_PANEL, activebackground=C_CARD,
                activeforeground=C_GOLD, font=F_BODY, indicatoron=True)
            rb.grid(row=0, column=col, sticky="e", padx=6)

        mk_plan("trial", "تجريبي (7 أيام)", 3)
        mk_plan("monthly", "شهري (30)", 2)
        mk_plan("yearly", "سنوي (365)", 1)
        mk_plan("lifetime", "دائم", 0)

        df = tk.Frame(form, bg=C_CARD)
        df.pack(fill="x", padx=16, pady=(10, 0))
        tk.Label(df, text="عدد الأيام (تستطيع تغييره بحرّية — 0 يعني دائم):",
                 font=F_SMALL, bg=C_CARD, fg=C_SUB).pack(side="right")
        self.e_days = tk.Entry(df, textvariable=self.days_var, width=8,
                               font=F_MONO, bg=C_PANEL, fg=C_GOLD,
                               insertbackground=C_TEXT, relief="flat",
                               justify="center")
        self.e_days.pack(side="right", padx=8, ipady=4)

        gold_button(form, "🔑 إصدار المفتاح الآن", self._issue_key,
                    big=True).pack(pady=18, padx=16, fill="x")

        # --- ناتج المفتاح (يسار)
        out = Card(left)
        out.pack(fill="both", expand=True)
        tk.Label(out, text="مفتاح التفعيل الناتج", font=F_H, bg=C_CARD,
                 fg=C_GOLD).pack(anchor="e", padx=16, pady=(14, 4))
        self.key_text = tk.Text(out, height=11, font=("Consolas", 9),
                                bg=C_PANEL, fg=C_GREEN, relief="flat",
                                wrap="char", insertbackground=C_TEXT)
        self.key_text.pack(fill="both", expand=True, padx=16, pady=4)
        self.key_text.insert("1.0", "سيظهر المفتاح هنا بعد الإصدار…")
        self.key_text.config(state="disabled")

        self.lbl_key_info = tk.Label(out, text="", font=F_BODY, bg=C_CARD,
                                     fg=C_SUB, justify="right")
        self.lbl_key_info.pack(anchor="e", padx=16)

        bf = tk.Frame(out, bg=C_CARD)
        bf.pack(fill="x", padx=16, pady=(6, 14))
        gold_button(bf, "📋 نسخ المفتاح", self._copy_key).pack(
            side="right", padx=(0, 6))
        ghost_button(bf, "💬 نسخ رسالة جاهزة للعميل",
                     self._copy_customer_msg).pack(side="right", padx=6)
        ghost_button(bf, "🗑 مسح", self._clear_key).pack(side="left")
        self._last_key = ""
        self._last_payload = None

    def _plan_changed(self):
        self.days_var.set(str(PLAN_DAYS[self.plan_var.get()]))

    def _issue_key(self):
        fp = self.e_fp.get().strip().upper()
        if not fp or len(fp.replace("-", "")) < 8:
            messagebox.showwarning(
                "تنبيه", "أدخل بصمة جهاز المشتري أولًا — يرسلها لك من "
                "نافذة التفعيل في البرنامج (مثل A3F2-9K1B-77CD-E2A0).")
            return
        plan = self.plan_var.get()
        try:
            days = int(self.days_var.get().strip() or "0")
        except ValueError:
            messagebox.showwarning("تنبيه", "عدد الأيام يجب أن يكون رقمًا.")
            return
        if plan == "lifetime":
            days = 0
        name = self.e_name.get().strip()
        phone = self.e_phone.get().strip()
        note = name or "عميل"
        try:
            key = lv.make_activation_key(
                self.secrets["ed25519_private"], fp, plan, days, note,
                pqc_private_key_b64=self.secrets.get("mldsa65_private", ""))
            payload, _, _ = lv.parse_activation_key(key)
        except Exception as e:
            messagebox.showerror("خطأ", f"تعذر إصدار المفتاح: {e}")
            return
        self._last_key = key
        self._last_payload = payload
        self.key_text.config(state="normal")
        self.key_text.delete("1.0", "end")
        self.key_text.insert("1.0", key)
        self.key_text.config(state="disabled")
        exp = ("دائم" if not payload["exp"] else
               time.strftime("%Y-%m-%d", time.localtime(payload["exp"])))
        self.lbl_key_info.config(
            text=f"رقم الترخيص: {payload['lid']}   |   "
                 f"الخطة: {PLAN_AR.get(plan, plan)}   |   ينتهي: {exp}",
            fg=C_GREEN)
        # سجل العميل
        self.customers.append({
            "name": name or "عميل", "phone": phone, "fingerprint": fp,
            "plan": plan, "days": days, "license_id": payload["lid"],
            "issued_at": int(time.time()), "revoked": False,
            "key": key, "note": note,
        })
        save_customers(self.customers)
        self._refresh_customers()
        copy_to_clipboard(self, key)
        messagebox.showinfo(
            "تم الإصدار ✅",
            f"صدر المفتاح ونُسخ تلقائيًا — أرسله الآن إلى "
            f"{name or 'المشتري'}.\n\nسُجل العميل في تبويب "
            f"(العملاء والأجهزة).")

    def _copy_key(self):
        if not self._last_key:
            return
        copy_to_clipboard(self, self._last_key)
        messagebox.showinfo("تم", "نُسخ المفتاح إلى الحافظة.")

    def _copy_customer_msg(self):
        if not self._last_key or not self._last_payload:
            messagebox.showwarning("تنبيه", "أصدر مفتاحًا أولًا.")
            return
        p = self._last_payload
        exp = ("دائم" if not p["exp"] else
               time.strftime("%Y-%m-%d", time.localtime(p["exp"])))
        msg = (
            "أهلًا بك 🌟\n"
            "هذا مفتاح تفعيل برنامج Ahmed Al-Faifi Market Image Studio:\n\n"
            f"{self._last_key}\n\n"
            "طريقة التفعيل:\n"
            "1) افتح البرنامج — ستظهر نافذة التفعيل.\n"
            "2) الصق المفتاح كاملًا في خانة (مفتاح التفعيل).\n"
            "3) اضغط (تفعيل) — وسيعمل البرنامج فورًا بإذن الله.\n\n"
            f"نوع الاشتراك: {PLAN_AR.get(p['plan'], p['plan'])} — "
            f"صالح حتى: {exp}\n"
            "ملاحظة: المفتاح يعمل على جهازك هذا فقط.\n"
            "لأي مساعدة تواصل معي مباشرة. — أحمد الفيفي")
        copy_to_clipboard(self, msg)
        messagebox.showinfo("تم", "نُسخت رسالة كاملة جاهزة للإرسال "
                                  "للعميل (واتساب/رسائل).")

    def _clear_key(self):
        self._last_key = ""
        self._last_payload = None
        self.key_text.config(state="normal")
        self.key_text.delete("1.0", "end")
        self.key_text.insert("1.0", "سيظهر المفتاح هنا بعد الإصدار…")
        self.key_text.config(state="disabled")
        self.lbl_key_info.config(text="")

    # ============================================ تبويب العملاء والأجهزة
    def _build_tab_customers(self):
        t = self.tab_customers
        top = tk.Frame(t, bg=C_BG)
        top.pack(fill="x", padx=12, pady=(12, 4))
        tk.Label(top, text="🔎", font=F_BODY, bg=C_BG,
                 fg=C_SUB).pack(side="right")
        self.search_var = tk.StringVar()
        se = tk.Entry(top, textvariable=self.search_var, font=F_BODY,
                      bg=C_PANEL, fg=C_TEXT, insertbackground=C_TEXT,
                      relief="flat", justify="right", width=34)
        se.pack(side="right", padx=6, ipady=6)
        se.insert(0, "")
        self.search_var.trace_add("write",
                                  lambda *a: self._refresh_customers())
        tk.Label(top, text="ابحث بالاسم أو البصمة أو الجوال:", font=F_BODY,
                 bg=C_BG, fg=C_TEXT).pack(side="right")

        self.lbl_count = tk.Label(top, text="", font=F_SMALL, bg=C_BG,
                                  fg=C_SUB)
        self.lbl_count.pack(side="left")

        cols = ("name", "phone", "fp", "plan", "expiry", "left", "status")
        self.tree = ttk.Treeview(t, columns=cols, show="headings",
                                 selectmode="browse")
        heads = {"name": ("العميل", 190), "phone": ("الجوال", 110),
                 "fp": ("بصمة الجهاز", 170), "plan": ("الخطة", 80),
                 "expiry": ("ينتهي في", 100), "left": ("المتبقي", 80),
                 "status": ("الحالة", 110)}
        for c in cols:
            self.tree.heading(c, text=heads[c][0])
            self.tree.column(c, width=heads[c][1], anchor="center")
        self.tree.pack(fill="both", expand=True, padx=12, pady=6)
        self.tree.tag_configure("ok", foreground=C_GREEN)
        self.tree.tag_configure("warn", foreground="#ffcc66")
        self.tree.tag_configure("bad", foreground=C_RED)

        bf = tk.Frame(t, bg=C_BG)
        bf.pack(fill="x", padx=12, pady=(2, 12))
        gold_button(bf, "⏳ تمديد/تجديد الاشتراك",
                    self._extend_selected).pack(side="right", padx=(0, 6))
        ghost_button(bf, "📋 نسخ مفتاح العميل",
                     self._copy_selected_key).pack(side="right", padx=6)
        ghost_button(bf, "🧾 تفاصيل العميل",
                     self._show_selected_details).pack(side="right", padx=6)
        tk.Button(bf, text="⛔ تسجيل إلغاء الترخيص",
                  command=self._revoke_selected, bg="#5c2b2b", fg=C_TEXT,
                  activebackground="#7a3737", activeforeground=C_TEXT,
                  font=("Segoe UI", 10), relief="flat", cursor="hand2",
                  padx=12, pady=6, bd=0).pack(side="left", padx=6)
        ghost_button(bf, "🗑 حذف من السجل",
                     self._delete_selected).pack(side="left")
        self._refresh_customers()

    def _visible_rows(self) -> list[tuple[int, dict]]:
        q = (self.search_var.get() if hasattr(self, "search_var")
             else "").strip().lower()
        rows = []
        for i, d in enumerate(self.customers):
            blob = " ".join([d.get("name", ""), d.get("phone", ""),
                             d.get("fingerprint", ""),
                             d.get("license_id", "")]).lower()
            if not q or q in blob:
                rows.append((i, d))
        return rows

    def _refresh_customers(self):
        if not hasattr(self, "tree"):
            return
        self.tree.delete(*self.tree.get_children())
        rows = self._visible_rows()
        active = 0
        for i, d in rows:
            lft = days_left(d.get("issued_at", 0), d.get("days", 0))
            if d.get("revoked"):
                status, tag = "ملغى", "bad"
            elif lft == -1:
                status, tag = "دائم ✅", "ok"
                active += 1
            elif lft == 0:
                status, tag = "منتهٍ", "bad"
            elif lft <= 7:
                status, tag = f"يوشك ({lft} أيام)", "warn"
                active += 1
            else:
                status, tag = "فعال ✅", "ok"
                active += 1
            self.tree.insert(
                "", "end", iid=str(i), tags=(tag,),
                values=(d.get("name", ""), d.get("phone", ""),
                        d.get("fingerprint", ""),
                        PLAN_AR.get(d.get("plan", ""), d.get("plan", "")),
                        fmt_expiry(d.get("issued_at", 0), d.get("days", 0)),
                        ("∞" if lft == -1 else f"{lft} يوم"), status))
        self.lbl_count.config(
            text=f"الإجمالي: {len(self.customers)} | الظاهر: {len(rows)} "
                 f"| الفعال: {active}")

    def _selected(self) -> int | None:
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("تنبيه", "اختر عميلًا من الجدول أولًا.")
            return None
        return int(sel[0])

    def _extend_selected(self):
        i = self._selected()
        if i is None:
            return
        d = self.customers[i]
        win = tk.Toplevel(self)
        win.title("تمديد/تجديد الاشتراك")
        win.configure(bg=C_BG)
        win.geometry("520x340")
        win.grab_set()
        tk.Label(win, text=f"تجديد اشتراك: {d.get('name', '')}",
                 font=F_H, bg=C_BG, fg=C_GOLD).pack(pady=(18, 4))
        tk.Label(win, text=f"بصمة الجهاز: {d.get('fingerprint', '')}",
                 font=F_MONO, bg=C_BG, fg=C_SUB).pack()
        tk.Label(win, text="مدة التجديد الجديدة (بالأيام من اليوم — 0 = دائم):",
                 font=F_BODY, bg=C_BG, fg=C_TEXT).pack(pady=(16, 4))
        dv = tk.StringVar(value=str(d.get("days", 30) or 0))
        tk.Entry(win, textvariable=dv, font=F_MONO, bg=C_PANEL, fg=C_GOLD,
                 insertbackground=C_TEXT, relief="flat", justify="center",
                 width=10).pack(ipady=6)

        def do_extend():
            try:
                nd = int(dv.get().strip())
            except ValueError:
                messagebox.showwarning("تنبيه", "أدخل رقمًا صحيحًا.",
                                       parent=win)
                return
            plan = d.get("plan", "monthly")
            if nd == 0:
                plan = "lifetime"
            try:
                key = lv.make_activation_key(
                    self.secrets["ed25519_private"], d["fingerprint"],
                    plan, nd, d.get("name", ""),
                    pqc_private_key_b64=self.secrets.get(
                        "mldsa65_private", ""))
                payload, _, _ = lv.parse_activation_key(key)
            except Exception as e:
                messagebox.showerror("خطأ", f"تعذر التجديد: {e}",
                                     parent=win)
                return
            d.update({"plan": plan, "days": nd, "key": key,
                      "license_id": payload["lid"],
                      "issued_at": int(time.time()), "revoked": False})
            save_customers(self.customers)
            self._refresh_customers()
            copy_to_clipboard(self, key)
            win.destroy()
            messagebox.showinfo(
                "تم التجديد ✅",
                "صدر مفتاح تجديد جديد ونُسخ للحافظة — أرسله للعميل "
                "ليلصقه في نافذة التفعيل (أو لوحة المالك > تفعيل بمفتاح).")

        gold_button(win, "🔑 إصدار مفتاح التجديد", do_extend,
                    big=True).pack(pady=18, padx=30, fill="x")

    def _copy_selected_key(self):
        i = self._selected()
        if i is None:
            return
        key = self.customers[i].get("key", "")
        if not key:
            messagebox.showwarning(
                "تنبيه", "لا يوجد مفتاح محفوظ لهذا السجل (ربما رُحّل من "
                "الأداة القديمة) — استخدم (تمديد/تجديد) لإصدار مفتاح جديد.")
            return
        copy_to_clipboard(self, key)
        messagebox.showinfo("تم", "نُسخ مفتاح العميل إلى الحافظة.")

    def _show_selected_details(self):
        i = self._selected()
        if i is None:
            return
        d = self.customers[i]
        lft = days_left(d.get("issued_at", 0), d.get("days", 0))
        info = (
            f"العميل: {d.get('name', '')}\n"
            f"الجوال: {d.get('phone', '') or '—'}\n"
            f"بصمة الجهاز: {d.get('fingerprint', '')}\n"
            f"الخطة: {PLAN_AR.get(d.get('plan', ''), d.get('plan', ''))}\n"
            f"تاريخ الإصدار: "
            f"{time.strftime('%Y-%m-%d', time.localtime(d.get('issued_at', 0)))}\n"
            f"ينتهي: {fmt_expiry(d.get('issued_at', 0), d.get('days', 0))}\n"
            f"المتبقي: {'دائم' if lft == -1 else str(lft) + ' يوم'}\n"
            f"رقم الترخيص: {d.get('license_id', '')}\n"
            f"الحالة: {'ملغى ⛔' if d.get('revoked') else 'فعال ✅'}")
        messagebox.showinfo("تفاصيل العميل", info)

    def _revoke_selected(self):
        i = self._selected()
        if i is None:
            return
        d = self.customers[i]
        if not messagebox.askyesno(
                "تأكيد الإلغاء",
                f"تسجيل إلغاء ترخيص ({d.get('name', '')})؟\n\n"
                "سيُعلَّم ملغى في سجلك ولن تصدر له مفاتيح جديدة.\n"
                "لإيقافه على جهاز العميل نفسه: افتح لوحة المالك في برنامج "
                "العميل برمز TOTP واختر (إلغاء الترخيص)."):
            return
        d["revoked"] = True
        save_customers(self.customers)
        self._refresh_customers()
        messagebox.showinfo("تم", "سُجل الإلغاء في السجل.")

    def _delete_selected(self):
        i = self._selected()
        if i is None:
            return
        d = self.customers[i]
        if not messagebox.askyesno(
                "تأكيد الحذف", f"حذف سجل ({d.get('name', '')}) نهائيًا "
                "من القائمة؟ (لا يؤثر على جهاز العميل)"):
            return
        self.customers.pop(i)
        save_customers(self.customers)
        self._refresh_customers()

    # ==================================================== تبويب TOTP
    def _build_tab_totp(self):
        t = self.tab_totp
        wrap = tk.Frame(t, bg=C_BG)
        wrap.pack(expand=True, fill="both", padx=16, pady=12)

        right = Card(wrap)
        right.pack(side="right", fill="both", expand=True, padx=(6, 0))
        tk.Label(right, text="رمز المالك الحي", font=F_H, bg=C_CARD,
                 fg=C_GOLD).pack(anchor="e", padx=16, pady=(16, 2))
        tk.Label(right,
                 text="استخدم هذا الرمز لدخول (لوحة المالك) داخل برنامج العملاء على أي جهاز",
                 font=F_SMALL, bg=C_CARD, fg=C_SUB).pack(anchor="e", padx=16)
        self.totp_big = tk.Label(right, text="——————", font=F_CODE_BIG,
                                 bg=C_CARD, fg=C_GREEN, cursor="hand2")
        self.totp_big.pack(pady=(28, 4))
        self.totp_big.bind("<Button-1>", lambda e: self._copy_totp_big())
        self.totp_remain = tk.Label(right, text="", font=F_SMALL,
                                    bg=C_CARD, fg=C_SUB)
        self.totp_remain.pack()
        gold_button(right, "📋 نسخ الرمز", self._copy_totp_big).pack(pady=16)
        tk.Label(right,
                 text="ماذا تفعل لوحة المالك في برنامج العميل؟\n"
                      "• عرض حالة الترخيص وبصمة الجهاز\n"
                      "• تفعيل/تجديد بمفتاح جديد\n"
                      "• إلغاء الترخيص على ذلك الجهاز فورًا\n"
                      "• إعدادات متقدمة لا يراها العميل",
                 font=F_BODY, bg=C_CARD, fg=C_TEXT,
                 justify="right").pack(anchor="e", padx=16, pady=(8, 16))

        left = Card(wrap)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        tk.Label(left, text="إضافة الرمز إلى جوالك (مرة واحدة)", font=F_H,
                 bg=C_CARD, fg=C_GOLD).pack(anchor="e", padx=16,
                                            pady=(16, 2))
        tk.Label(left,
                 text="امسح رمز QR بتطبيق Google Authenticator وستحصل على رموز المالك في جيبك دائمًا",
                 font=F_SMALL, bg=C_CARD, fg=C_SUB).pack(anchor="e", padx=16)
        self.qr_canvas = tk.Canvas(left, width=260, height=260, bg="white",
                                   highlightthickness=0)
        self.qr_canvas.pack(pady=14)
        self._draw_qr()
        bf = tk.Frame(left, bg=C_CARD)
        bf.pack(pady=(0, 16))
        ghost_button(bf, "📋 نسخ رابط الإضافة (otpauth)",
                     self._copy_otpauth).pack(side="right", padx=6)
        ghost_button(bf, "📋 نسخ السر (إدخال يدوي)",
                     self._copy_totp_secret).pack(side="right", padx=6)

    def _draw_qr(self):
        uri = lv.totp_provisioning_uri(self.secrets["totp_secret"],
                                       account="Ahmed",
                                       issuer="MarketImageStudio")
        m = qr_matrix(uri)
        self.qr_canvas.delete("all")
        if m is None:
            self.qr_canvas.create_text(
                130, 130, text="مكتبة QR غير متاحة\nاستخدم زر نسخ السر\n"
                               "وأدخله يدويًا في التطبيق",
                font=F_BODY, fill="#333", justify="center")
            return
        n = len(m)
        size = 260 // n
        off = (260 - size * n) // 2
        for r, row in enumerate(m):
            for c, v in enumerate(row):
                if v:
                    x, y = off + c * size, off + r * size
                    self.qr_canvas.create_rectangle(
                        x, y, x + size, y + size, fill="black", width=0)

    def _copy_totp_big(self):
        code = lv.totp_now(self.secrets["totp_secret"])
        copy_to_clipboard(self, code)
        messagebox.showinfo("تم", f"نُسخ الرمز: {code}")

    def _copy_otpauth(self):
        copy_to_clipboard(self, lv.totp_provisioning_uri(
            self.secrets["totp_secret"], account="Ahmed",
            issuer="MarketImageStudio"))
        messagebox.showinfo("تم", "نُسخ رابط otpauth — ألصقه في تطبيق "
                                  "Authenticator (إضافة عبر الرابط).")

    def _copy_totp_secret(self):
        copy_to_clipboard(self, self.secrets["totp_secret"])
        messagebox.showinfo("تم", "نُسخ سر TOTP — في التطبيق اختر "
                                  "(إدخال مفتاح الإعداد) والصقه.")

    # ================================================ تبويب النسخ الاحتياطي
    def _build_tab_backup(self):
        t = self.tab_backup
        wrap = tk.Frame(t, bg=C_BG)
        wrap.pack(expand=True, fill="both", padx=16, pady=12)

        c1 = Card(wrap)
        c1.pack(fill="x", pady=6)
        tk.Label(c1, text="نسخة احتياطية كاملة (الشفرة + سجل العملاء)",
                 font=F_H, bg=C_CARD, fg=C_GOLD).pack(anchor="e", padx=16,
                                                      pady=(14, 2))
        tk.Label(c1,
                 text="ينشئ ملفًا واحدًا يحوي شفرة المالك وسجل العملاء — خزّنه في فلاشة وسحابة خاصة. بدون الشفرة لا يمكن إصدار أي مفتاح جديد!",
                 font=F_SMALL, bg=C_CARD, fg=C_SUB,
                 wraplength=900, justify="right").pack(anchor="e", padx=16)
        bf1 = tk.Frame(c1, bg=C_CARD)
        bf1.pack(pady=12)
        gold_button(bf1, "💾 إنشاء نسخة احتياطية الآن",
                    self._backup_now, big=True).pack(side="right", padx=8)
        ghost_button(bf1, "📥 استعادة من نسخة احتياطية",
                     self._restore_backup).pack(side="right", padx=8)

        c2 = Card(wrap)
        c2.pack(fill="x", pady=6)
        tk.Label(c2, text="أين تُحفظ بياناتي؟", font=F_H, bg=C_CARD,
                 fg=C_GOLD).pack(anchor="e", padx=16, pady=(14, 2))
        tk.Label(c2,
                 text=f"كل شيء في مجلد واحد بجانب البرنامج:\n{DATA}\n"
                      "انسخ هذا المجلد كاملًا = نسخة احتياطية يدوية كاملة.",
                 font=F_BODY, bg=C_CARD, fg=C_TEXT,
                 justify="right").pack(anchor="e", padx=16, pady=(0, 8))
        ghost_button(c2, "📂 فتح مجلد البيانات",
                     self._open_data_dir).pack(pady=(0, 14))

        c3 = Card(wrap)
        c3.pack(fill="x", pady=6)
        tk.Label(c3, text="تنبيهات أمان مهمة", font=F_H, bg=C_CARD,
                 fg=C_RED).pack(anchor="e", padx=16, pady=(14, 2))
        tk.Label(c3,
                 text="• لا تشارك هذا البرنامج أو مجلد بيانات_المالك مع أي شخص إطلاقًا.\n"
                      "• من يحصل على owner_secrets.json يستطيع إصدار تراخيص لبرنامجك.\n"
                      "• احتفظ بنسختين احتياطيتين على الأقل في مكانين منفصلين.\n"
                      "• عند بيع جهازك القديم: احذف مجلد البرنامج والبيانات نهائيًا.",
                 font=F_BODY, bg=C_CARD, fg=C_TEXT,
                 justify="right").pack(anchor="e", padx=16, pady=(0, 14))

    def _backup_now(self):
        default = f"نسخة_مالك_احتياطية_{time.strftime('%Y-%m-%d_%H%M')}.json"
        p = filedialog.asksaveasfilename(
            title="حفظ النسخة الاحتياطية", initialfile=default,
            defaultextension=".json",
            filetypes=[("نسخة احتياطية", "*.json")])
        if not p:
            return
        blob = {
            "type": "owner_studio_backup", "version": VERSION,
            "created_at": int(time.time()),
            "secrets": self.secrets, "customers": self.customers,
        }
        Path(p).write_text(json.dumps(blob, ensure_ascii=False, indent=2),
                           encoding="utf-8")
        messagebox.showinfo("تم ✅", f"حُفظت النسخة الاحتياطية في:\n{p}\n\n"
                                     "خزّنها الآن في فلاشة أو سحابة خاصة.")

    def _restore_backup(self):
        p = filedialog.askopenfilename(
            title="اختر ملف النسخة الاحتياطية",
            filetypes=[("نسخة احتياطية", "*.json")])
        if not p:
            return
        try:
            blob = json.loads(Path(p).read_text(encoding="utf-8"))
            assert blob.get("type") == "owner_studio_backup"
        except Exception:
            messagebox.showerror("خطأ", "الملف ليس نسخة احتياطية صالحة.")
            return
        if not messagebox.askyesno(
                "تأكيد", "ستستبدل الاستعادة الشفرة وسجل العملاء الحاليين. "
                "متابعة؟"):
            return
        self.secrets = blob.get("secrets") or self.secrets
        self.customers = blob.get("customers") or []
        save_secrets(self.secrets)
        save_customers(self.customers)
        self._refresh_customers()
        messagebox.showinfo("تم ✅", "استُعيدت البيانات بنجاح.")

    def _open_data_dir(self):
        try:
            if os.name == "nt":
                os.startfile(str(DATA))  # noqa: S606
            else:
                webbrowser.open(f"file://{DATA}")
        except Exception:
            messagebox.showinfo("المسار", str(DATA))

    # ==================================================== تبويب الإعدادات
    def _build_tab_settings(self):
        t = self.tab_settings
        wrap = tk.Frame(t, bg=C_BG)
        wrap.pack(expand=True, fill="both", padx=16, pady=12)

        c1 = Card(wrap)
        c1.pack(fill="x", pady=6)
        tk.Label(c1, text="حالة شفرة المالك", font=F_H, bg=C_CARD,
                 fg=C_GOLD).pack(anchor="e", padx=16, pady=(14, 2))
        created = self.secrets.get("created_at", 0)
        created_s = (time.strftime("%Y-%m-%d",
                                   time.localtime(created))
                     if created else "غير معروف")
        has_pqc = bool(self.secrets.get("mldsa65_private"))
        tk.Label(c1,
                 text=f"تاريخ إنشاء الشفرة: {created_s}\n"
                      f"توقيع Ed25519: متوفر ✅\n"
                      f"التوقيع المقاوم للكم ML-DSA-65: "
                      f"{'متوفر ✅' if has_pqc else 'غير متوفر ⚠️'}\n"
                      f"سر TOTP: متوفر ✅",
                 font=F_BODY, bg=C_CARD, fg=C_TEXT,
                 justify="right").pack(anchor="e", padx=16, pady=(0, 14))

        c2 = Card(wrap)
        c2.pack(fill="x", pady=6)
        tk.Label(c2, text="المفاتيح العامة (للغرس في برنامج العملاء قبل البناء)",
                 font=F_H, bg=C_CARD, fg=C_GOLD).pack(anchor="e", padx=16,
                                                      pady=(14, 2))
        tk.Label(c2,
                 text="تحتاجها فقط إن ولّدت شفرة جديدة وأردت إعادة بناء برنامج العملاء — تُلصق في ملف license_v2.py أو عبر أداة inject_keys.py",
                 font=F_SMALL, bg=C_CARD, fg=C_SUB, wraplength=900,
                 justify="right").pack(anchor="e", padx=16)
        bf2 = tk.Frame(c2, bg=C_CARD)
        bf2.pack(pady=12)
        ghost_button(bf2, "📋 نسخ المفتاح العام Ed25519",
                     lambda: (copy_to_clipboard(
                         self, self.secrets.get("ed25519_public", "")),
                         messagebox.showinfo("تم", "نُسخ."))).pack(
            side="right", padx=6)
        ghost_button(bf2, "📋 نسخ المفتاح العام ML-DSA-65",
                     lambda: (copy_to_clipboard(
                         self, self.secrets.get("mldsa65_public", "")),
                         messagebox.showinfo("تم", "نُسخ."))).pack(
            side="right", padx=6)

        c3 = Card(wrap)
        c3.pack(fill="x", pady=6)
        tk.Label(c3, text="عن البرنامج", font=F_H, bg=C_CARD,
                 fg=C_GOLD).pack(anchor="e", padx=16, pady=(14, 2))
        tk.Label(c3,
                 text=f"استوديو المالك {VERSION} — مركز إدارة "
                      "Ahmed Al-Faifi Market Image Studio 2.0.0\n"
                      "إصدار التراخيص يستخدم توقيعًا هجينًا: Ed25519 + "
                      "ML-DSA-65 المقاوم للحواسيب الكمومية.\n"
                      "جميع الحقوق محفوظة © أحمد الفيفي 2026 — سري وخاص "
                      "بالمالك.",
                 font=F_BODY, bg=C_CARD, fg=C_TEXT,
                 justify="right").pack(anchor="e", padx=16, pady=(0, 14))


def main() -> None:
    app = OwnerStudio()
    app.mainloop()


if __name__ == "__main__":
    main()
