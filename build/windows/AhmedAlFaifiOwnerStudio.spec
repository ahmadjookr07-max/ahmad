# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — استوديو المالك (Ahmed Al-Faifi Owner Studio).

برنامج المالك وحده: يصدر مفاتيح التفعيل، يدير سجل العملاء والاشتراكات،
يولد رمز TOTP، ويصدر ملفات الإلغاء الموقّعة.

سري — لا يُوزَّع على العملاء إطلاقًا.
لا تُضمَّن شفرة المالك (owner_secrets.json) داخل الملف التنفيذي؛ تُوضع
بجانبه في مجلد (بيانات_المالك) ليبقى الملف التنفيذي قابلًا للتحديث بلا
مساس بالأسرار، ويسهل نسخها احتياطيًا.
"""
from pathlib import Path
import os
from PyInstaller.utils.hooks import collect_all

ROOT = Path(os.getcwd()).resolve()
APP_ID = "AhmedAlFaifiOwnerStudio"
ENTRY = ROOT / "owner_studio" / "owner_studio.py"
ICON = ROOT / "windows_app" / "assets" / "app_icon.ico"
VERSION_INFO = ROOT / "build" / "windows" / "version_info_owner.txt"

datas = [
    (str(ROOT / "windows_app" / "assets" / "app_icon.ico"), "windows_app/assets"),
    (str(ROOT / "windows_app" / "assets" / "app_icon.png"), "windows_app/assets"),
]

# محرك الترخيص ومكتبة التوقيع المقاوم للكم لازمة لإصدار المفاتيح
dil_datas, dil_binaries, dil_hidden = collect_all("dilithium_py")
datas += dil_datas
binaries = list(dil_binaries)

hiddenimports = list(dil_hidden) + [
    "dilithium_py", "dilithium_py.ml_dsa",
    "cryptography",
    "cryptography.hazmat.primitives.asymmetric.ed25519",
    "cryptography.hazmat.primitives.ciphers.aead",
    "engine_v2", "engine_v2.license_v2",
    "tkinter", "tkinter.ttk", "tkinter.filedialog", "tkinter.messagebox",
]

a = Analysis(
    [str(ENTRY)],
    pathex=[str(ROOT / "src"), str(ROOT / "owner_studio"), str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib", "pandas", "pytest", "scipy", "IPython", "notebook",
        "PySide6", "onnxruntime", "cv2", "zxingcpp", "openpyxl",
        "pytesseract",
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_ID,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON),
    version=str(VERSION_INFO),
    uac_admin=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_ID,
)
