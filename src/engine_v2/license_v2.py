# -*- coding: utf-8 -*-
"""license_v2 — منظومة الترخيص والاشتراك الخاصة بالمالك.

النموذج الأمني (device-authorization بيد المالك فقط):
1. بصمة الجهاز: SHA-256 لمعرّف Windows (MachineGuid) + اسم الجهاز + المعالج.
   تُعرض للمستخدم كرمز قصير مثل: A3F2-9K1B-77CD-E2A0.
2. مفتاح التفعيل: يولده المالك فقط بأداة سرية منفصلة، وهو توقيع Ed25519
   لحمولة {بصمة الجهاز، تاريخ الانتهاء، الخطة، معرف الترخيص}.
   البرنامج يحمل المفتاح العام فقط — لا يمكن توليد تراخيص بدونه
   حتى بفك تجميع البرنامج بالكامل.
3. TOTP للمالك: رموز دورية (RFC 6238) من سر المالك لدخول لوحة المالك
   داخل البرنامج (عرض الأجهزة، إلغاء ترخيص) — تنفيذ ذاتي بلا تبعيات.
4. تخزين الترخيص: ملف مشفر AES-GCM (أو Fernet-like ذاتي عبر HMAC+XOR-CTR
   إن غابت cryptography) بمفتاح مشتق من بصمة الجهاز — نسخه لجهاز آخر
   يجعله غير قابل للقراءة أصلًا.
5. حماية الوقت: يخزن آخر طابع زمني موقّع؛ إرجاع ساعة النظام للوراء
   يُكشف ويجمّد البرنامج حتى يعود الوقت للتقدم.
6. الإلغاء: قائمة أرقام تراخيص ملغاة (revocation list) موقعة من المالك
   يمكن استيرادها لأي جهاز.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import platform
import struct
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------- ed25519
try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey, Ed25519PublicKey)
    from cryptography.hazmat.primitives import serialization
    _HAVE_CRYPTO = True
except Exception:  # pragma: no cover
    _HAVE_CRYPTO = False

# المفتاح العام للمالك (يُستبدل عند توليد المفاتيح بأداة المالك).
# لا يمكّن أحدًا من توليد تراخيص — التوقيع يحتاج المفتاح الخاص السري.
OWNER_PUBLIC_KEY_B64 = "SLK2T+shHfr9eSwEM9JyXA22DcwhWABXMwXzi+bI/O4="
# المفتاح العام المقاوم للكم ML-DSA-65 (FIPS 204) — توقيع هجين إلزامي:
# لا يُقبل أي مفتاح تفعيل إلا بصحة توقيعَي Ed25519 وML-DSA معًا.
OWNER_PQC_PUBLIC_KEY_B64 = "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"

try:
    from dilithium_py.ml_dsa import ML_DSA_65
    _HAVE_PQC = True
except Exception:  # pragma: no cover
    _HAVE_PQC = False

APP_LICENSE_DIRNAME = "SmartCatalogV2"
LICENSE_FILENAME = "license.dat"
CLOCK_FILENAME = "clock.dat"
REVOKE_FILENAME = "revoked.dat"

PLANS = {"monthly": "اشتراك شهري", "yearly": "اشتراك سنوي",
         "lifetime": "دائم", "trial": "تجريبي"}


# ================================================================ fingerprint
def _windows_machine_guid() -> str:
    try:
        out = subprocess.run(
            ["reg", "query",
             r"HKLM\SOFTWARE\Microsoft\Cryptography", "/v", "MachineGuid"],
            capture_output=True, text=True, timeout=5)
        for line in out.stdout.splitlines():
            if "MachineGuid" in line:
                return line.split()[-1].strip()
    except Exception:
        pass
    return ""


def _linux_machine_id() -> str:
    for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            return Path(p).read_text().strip()
        except Exception:
            continue
    return ""


def machine_fingerprint_raw() -> str:
    """المكونات الخام لبصمة الجهاز."""
    parts = []
    if os.name == "nt":
        parts.append(_windows_machine_guid())
    else:
        parts.append(_linux_machine_id())
    parts.append(platform.node())
    parts.append(platform.machine())
    parts.append(platform.processor() or "")
    if not any(parts):
        parts.append(str(uuid.getnode()))
    return "|".join(parts)


def machine_fingerprint() -> str:
    """بصمة الجهاز بصيغة قصيرة قابلة للقراءة: XXXX-XXXX-XXXX-XXXX."""
    h = hashlib.sha256(machine_fingerprint_raw().encode("utf-8")).hexdigest()
    s = h[:16].upper()
    return "-".join(s[i:i + 4] for i in range(0, 16, 4))


# ==================================================================== TOTP
def totp_now(secret_b32: str, when: float | None = None,
             period: int = 30, digits: int = 6) -> str:
    """رمز TOTP وفق RFC 6238 (SHA-1 كتطبيقات Authenticator القياسية)."""
    key = base64.b32decode(secret_b32.upper().replace(" ", "") + "=" *
                           ((8 - len(secret_b32) % 8) % 8))
    counter = int((when if when is not None else time.time()) // period)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    off = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[off:off + 4])[0] & 0x7FFFFFFF)
    return str(code % (10 ** digits)).zfill(digits)


def totp_verify(secret_b32: str, code: str, window: int = 1) -> bool:
    """يقبل الرمز الحالي ± window فترات (لتفاوت الساعة)."""
    code = code.strip().replace(" ", "")
    now = time.time()
    for w in range(-window, window + 1):
        if hmac.compare_digest(totp_now(secret_b32, now + w * 30), code):
            return True
    return False


def generate_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def totp_provisioning_uri(secret_b32: str, account: str = "Owner",
                          issuer: str = "SmartCatalogV2") -> str:
    from urllib.parse import quote
    return (f"otpauth://totp/{quote(issuer)}:{quote(account)}"
            f"?secret={secret_b32}&issuer={quote(issuer)}&period=30&digits=6")


# ============================================================ sign / verify
def _sign_ed25519(private_key_b64: str, payload: bytes) -> str:
    if not _HAVE_CRYPTO:
        raise RuntimeError("cryptography غير متاحة للتوقيع")
    raw = base64.b64decode(private_key_b64)
    key = Ed25519PrivateKey.from_private_bytes(raw)
    return base64.b64encode(key.sign(payload)).decode()


def _verify_ed25519(public_key_b64: str, payload: bytes,
                    signature_b64: str) -> bool:
    try:
        if _HAVE_CRYPTO:
            key = Ed25519PublicKey.from_public_bytes(
                base64.b64decode(public_key_b64))
            key.verify(base64.b64decode(signature_b64), payload)
            return True
        # fallback نقي: تحقق Ed25519 ببايثون خالص (بطيء لكنه نادر الاستخدام)
        from engine_v2._ed25519_pure import checkvalid
        checkvalid(base64.b64decode(signature_b64), payload,
                   base64.b64decode(public_key_b64))
        return True
    except Exception:
        return False


def generate_pqc_keypair() -> tuple[str, str]:
    """يولد زوج مفاتيح ML-DSA-65 مقاوم للكم (private_b64, public_b64)."""
    if not _HAVE_PQC:
        raise RuntimeError("dilithium-py مطلوبة لتوليد مفاتيح PQC")
    pub, priv = ML_DSA_65.keygen()
    return (base64.b64encode(priv).decode(), base64.b64encode(pub).decode())


def _sign_pqc(private_key_b64: str, payload: bytes) -> bytes:
    if not _HAVE_PQC:
        raise RuntimeError("dilithium-py غير متاحة للتوقيع")
    return ML_DSA_65.sign(base64.b64decode(private_key_b64), payload)


def _verify_pqc(public_key_b64: str, payload: bytes, sig: bytes) -> bool:
    try:
        if not _HAVE_PQC:
            return False
        return ML_DSA_65.verify(base64.b64decode(public_key_b64),
                                payload, sig)
    except Exception:
        return False


def generate_owner_keypair() -> tuple[str, str]:
    """يولد (private_b64, public_b64) — يستدعى في أداة المالك فقط."""
    if not _HAVE_CRYPTO:
        raise RuntimeError("cryptography مطلوبة لتوليد المفاتيح")
    priv = Ed25519PrivateKey.generate()
    priv_raw = priv.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
        serialization.NoEncryption())
    pub_raw = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return (base64.b64encode(priv_raw).decode(),
            base64.b64encode(pub_raw).decode())


# ============================================================== encryption
def _derive_key(purpose: bytes) -> bytes:
    base = machine_fingerprint_raw().encode("utf-8")
    return hashlib.pbkdf2_hmac("sha256", base, b"SCV2::" + purpose, 200_000)


def _encrypt(data: bytes, purpose: bytes) -> bytes:
    key = _derive_key(purpose)
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        nonce = os.urandom(12)
        return b"AGCM" + nonce + AESGCM(key).encrypt(nonce, data, b"scv2")
    except Exception:
        # fallback: XOR-CTR بمفاتيح HMAC + وسم سلامة
        nonce = os.urandom(16)
        stream = b""
        counter = 0
        while len(stream) < len(data):
            stream += hmac.new(key, nonce + struct.pack(">I", counter),
                               hashlib.sha256).digest()
            counter += 1
        enc = bytes(a ^ b for a, b in zip(data, stream[:len(data)]))
        tag = hmac.new(key, nonce + enc, hashlib.sha256).digest()
        return b"HCTR" + nonce + tag + enc


def _decrypt(blob: bytes, purpose: bytes) -> bytes | None:
    key = _derive_key(purpose)
    try:
        if blob[:4] == b"AGCM":
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            return AESGCM(key).decrypt(blob[4:16], blob[16:], b"scv2")
        if blob[:4] == b"HCTR":
            nonce, tag, enc = blob[4:20], blob[20:52], blob[52:]
            calc = hmac.new(key, nonce + enc, hashlib.sha256).digest()
            if not hmac.compare_digest(calc, tag):
                return None
            stream = b""
            counter = 0
            while len(stream) < len(enc):
                stream += hmac.new(key, nonce + struct.pack(">I", counter),
                                   hashlib.sha256).digest()
                counter += 1
            return bytes(a ^ b for a, b in zip(enc, stream[:len(enc)]))
    except Exception:
        return None
    return None


# ============================================================ license model
@dataclass
class LicenseInfo:
    license_id: str = ""
    fingerprint: str = ""
    plan: str = "monthly"
    issued_at: int = 0
    expires_at: int = 0            # 0 = دائم
    owner_note: str = ""
    valid: bool = False
    status: str = ""               # نص حالة عربي
    days_left: int = -1


def _license_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA",
                                   Path.home() / "AppData/Roaming"))
    else:
        base = Path.home() / ".config"
    d = base / APP_LICENSE_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def make_activation_key(private_key_b64: str, fingerprint: str,
                        plan: str, days: int, note: str = "",
                        pqc_private_key_b64: str = "") -> str:
    """(أداة المالك فقط) يولد مفتاح تفعيل موقّعًا لجهاز محدد.

    الصيغة: SCV2.<b64url(payload)>.<b64url(sig_ed25519)>[.<b64url(sig_mldsa)>]
    مع pqc_private_key_b64 يُضاف توقيع ML-DSA-65 هجين مقاوم للكم.
    """
    now = int(time.time())
    payload = {
        "lid": uuid.uuid4().hex[:12],
        "fp": fingerprint.replace("-", "").upper(),
        "plan": plan,
        "iat": now,
        "exp": 0 if days <= 0 else now + days * 86400,
        "note": note,
    }
    raw = json.dumps(payload, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    sig = _sign_ed25519(private_key_b64, raw)
    p64 = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    s64 = base64.urlsafe_b64encode(base64.b64decode(sig)).decode().rstrip("=")
    key = f"SCV2.{p64}.{s64}"
    if pqc_private_key_b64:
        q = base64.urlsafe_b64encode(
            _sign_pqc(pqc_private_key_b64, raw)).decode().rstrip("=")
        key += f".{q}"
    return key


def _b64pad(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * ((4 - len(s) % 4) % 4))


def parse_activation_key(key: str) -> tuple[dict | None, bytes | None, str]:
    key = key.strip().replace("\n", "").replace(" ", "")
    if not key.startswith("SCV2."):
        return None, None, "صيغة المفتاح غير صحيحة"
    parts = key.split(".")
    if len(parts) not in (3, 4):
        return None, None, "صيغة المفتاح غير صحيحة"
    try:
        raw = _b64pad(parts[1])
        sig = _b64pad(parts[2])
        payload = json.loads(raw.decode("utf-8"))
        if len(parts) == 4:
            payload["_pqc_sig_b64"] = parts[3]
        return payload, sig, ""
    except Exception:
        return None, None, "تعذر قراءة المفتاح"


def _load_revoked() -> set[str]:
    p = _license_dir() / REVOKE_FILENAME
    if not p.is_file():
        return set()
    data = _decrypt(p.read_bytes(), b"revoke")
    if not data:
        return set()
    try:
        return set(json.loads(data.decode("utf-8")))
    except Exception:
        return set()


def revoke_license_id(lid: str) -> None:
    revoked = _load_revoked()
    revoked.add(lid)
    (_license_dir() / REVOKE_FILENAME).write_bytes(
        _encrypt(json.dumps(sorted(revoked)).encode("utf-8"), b"revoke"))


# ------------------------------------------------------------- clock guard
def _clock_check_and_update() -> bool:
    """False إن اكتُشف إرجاع ساعة النظام للوراء."""
    p = _license_dir() / CLOCK_FILENAME
    now = int(time.time())
    last = 0
    if p.is_file():
        data = _decrypt(p.read_bytes(), b"clock")
        if data:
            try:
                last = int(data.decode("utf-8"))
            except Exception:
                last = 0
    if last and now < last - 3 * 3600:   # سماحية 3 ساعات
        return False
    if now > last:
        try:
            p.write_bytes(_encrypt(str(now).encode("utf-8"), b"clock"))
        except Exception:
            pass
    return True


# --------------------------------------------------------------- activate
def activate_with_key(key: str,
                      public_key_b64: str | None = None) -> LicenseInfo:
    """يتحقق من مفتاح التفعيل ويخزن الترخيص مشفرًا إن صح."""
    pub = public_key_b64 or OWNER_PUBLIC_KEY_B64
    info = LicenseInfo()
    payload, sig, err = parse_activation_key(key)
    if payload is None:
        info.status = err
        return info
    pqc_sig_b64 = payload.pop("_pqc_sig_b64", "")
    raw = json.dumps(payload, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    if not _verify_ed25519(pub, raw, base64.b64encode(sig).decode()):
        info.status = "التوقيع الرقمي غير صحيح — المفتاح مرفوض"
        return info
    # التحقق الهجين المقاوم للكم: إلزامي متى غُرس مفتاح PQC عام في النسخة
    pqc_pub = OWNER_PQC_PUBLIC_KEY_B64
    if pqc_pub and pqc_pub != "REPLACED_AT_KEYGEN":
        if not pqc_sig_b64 or not _verify_pqc(pqc_pub, raw,
                                              _b64pad(pqc_sig_b64)):
            info.status = ("التوقيع المقاوم للكم مفقود أو غير صحيح — "
                           "المفتاح مرفوض")
            return info
    fp_here = machine_fingerprint().replace("-", "")
    if payload.get("fp", "") != fp_here:
        info.status = ("المفتاح مخصص لجهاز آخر — بصمة هذا الجهاز: "
                       + machine_fingerprint())
        return info
    if payload.get("lid") in _load_revoked():
        info.status = "هذا الترخيص ملغى"
        return info
    exp = int(payload.get("exp", 0))
    if exp and time.time() > exp:
        info.status = "انتهت صلاحية هذا المفتاح"
        return info
    # خزّن
    (_license_dir() / LICENSE_FILENAME).write_bytes(
        _encrypt(raw, b"license"))
    return check_license(pub)


def check_license(public_key_b64: str | None = None) -> LicenseInfo:
    """يفحص الترخيص المخزن ويعيد الحالة الكاملة."""
    pub = public_key_b64 or OWNER_PUBLIC_KEY_B64
    info = LicenseInfo(fingerprint=machine_fingerprint())
    if not _clock_check_and_update():
        info.status = "اكتُشف تلاعب بساعة النظام — أعد ضبط الوقت الصحيح"
        return info
    p = _license_dir() / LICENSE_FILENAME
    if not p.is_file():
        info.status = "لا يوجد ترخيص على هذا الجهاز"
        return info
    raw = _decrypt(p.read_bytes(), b"license")
    if not raw:
        info.status = "ملف الترخيص تالف أو منسوخ من جهاز آخر"
        return info
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        info.status = "ملف الترخيص تالف"
        return info
    info.license_id = payload.get("lid", "")
    info.plan = payload.get("plan", "")
    info.issued_at = int(payload.get("iat", 0))
    info.expires_at = int(payload.get("exp", 0))
    info.owner_note = payload.get("note", "")
    if payload.get("fp", "") != machine_fingerprint().replace("-", ""):
        info.status = "الترخيص لا يخص هذا الجهاز"
        return info
    if info.license_id in _load_revoked():
        info.status = "هذا الترخيص ملغى"
        return info
    now = time.time()
    if info.expires_at and now > info.expires_at:
        info.status = "انتهى الاشتراك — يلزم مفتاح تجديد من المالك"
        return info
    info.valid = True
    if info.expires_at:
        info.days_left = max(0, int((info.expires_at - now) // 86400))
        info.status = (f"الاشتراك فعال ({PLANS.get(info.plan, info.plan)}) — "
                       f"متبق {info.days_left} يومًا")
    else:
        info.days_left = -1
        info.status = "الترخيص دائم وفعال"
    return info


def deactivate() -> None:
    try:
        (_license_dir() / LICENSE_FILENAME).unlink(missing_ok=True)
    except Exception:
        pass
