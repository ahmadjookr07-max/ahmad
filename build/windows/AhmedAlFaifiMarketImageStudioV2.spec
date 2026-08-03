# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — Ahmed Al-Faifi Market Image Studio V2.0.0."""
from pathlib import Path
import os
from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(os.getcwd()).resolve()
APP_ID = "AhmedAlFaifiMarketImageStudio"
ENTRY = ROOT / "windows_app" / "native_app_v2.py"
ICON = ROOT / "windows_app" / "assets" / "app_icon.ico"
VERSION_INFO = ROOT / "build" / "windows" / "version_info.txt"

datas = [
    # legacy 1.2.1 models (fallback engine)
    (str(ROOT / "resources" / "models" / "u2net.onnx"), "resources/models"),
    (str(ROOT / "resources" / "models" / "u2netp.onnx"), "resources/models"),
    # V2 engine model + fonts
    (str(ROOT / "src" / "engine_v2" / "models" / "isnet-general-use.onnx"),
     "engine_v2/models"),
    (str(ROOT / "src" / "engine_v2" / "assets" / "NotoNaskhArabic-Regular.ttf"),
     "engine_v2/assets"),
    (str(ROOT / "src" / "engine_v2" / "assets" / "NotoNaskhArabic-Bold.ttf"),
     "engine_v2/assets"),
    # app assets
    (str(ROOT / "windows_app" / "assets" / "app_icon.png"), "windows_app/assets"),
    (str(ROOT / "windows_app" / "assets" / "app_icon.ico"), "windows_app/assets"),
    # legacy compiled pipeline (1.2.1 proven engine)
    (str(ROOT / "src" / "smart_catalog_vision" / "final_images.pyc"), "smart_catalog_vision"),
    (str(ROOT / "src" / "smart_catalog_vision" / "imaging.pyc"), "smart_catalog_vision"),
    (str(ROOT / "src" / "smart_catalog_vision" / "normalization.pyc"), "smart_catalog_vision"),
    (str(ROOT / "src" / "smart_catalog_vision" / "product_segmentation.pyc"), "smart_catalog_vision"),
    (str(ROOT / "src" / "smart_catalog_vision" / "thin_branch_pruner.pyc"), "smart_catalog_vision"),
    # docs
    (str(ROOT / "build" / "windows" / "EULA_ar.txt"), "."),
    (str(ROOT / "README.md"), "."),
    (str(ROOT / "RELEASE_NOTES_2.0.0.md"), "."),
    (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
    (str(ROOT / "VERSION"), "."),
]

datas += collect_data_files("openpyxl")

zxing_datas, zxing_binaries, zxing_hidden = collect_all("zxingcpp")
onnx_datas, onnx_binaries, onnx_hidden = collect_all("onnxruntime")
dil_datas, dil_binaries, dil_hidden = collect_all("dilithium_py")
datas += zxing_datas + onnx_datas + dil_datas
binaries = list(zxing_binaries) + list(onnx_binaries) + list(dil_binaries)
# ───────────── اكتشاف وحدات المشروع تلقائيًا ─────────────
#
# لماذا التوليد لا السرد اليدوي؟ لأن السرد اليدوي أخطأ فعلًا:
# كانت النسخة السابقة تسرد 14 وحدة engine_v2 وتنسى طبقة awareness
# بأكملها ووحدات واجهة قائمة (unified_editor ، flow_layout ، ui_scale ،
# nutrition_crop ، lazy_engine). والأخطر أن البناء لا يفشل عند النقص:
# طبقة الوعي مستوردة داخل try/except لتبقى المعالجة سليمة إن غابت،
# فيُنتج مُثبِّت يعمل بصمت بلا وعي: لا لوحة، ولا حوار عربي، ولا
# تنفيذ لأوامر المالك. عطل صامت لا يكتشفه إلا المالك بعد التسليم.
# لذا: نكتشف الوحدات من القرص، ونفشل صراحةً إن غابت واحدة حرجة.

def _discover(pkg_dir, prefix=""):
    """يسرد وحدات بايثون حقيقية في مجلد، متجاهلًا المولّد والمخفي."""
    out = []
    if not pkg_dir.is_dir():
        return out
    for f in sorted(pkg_dir.glob("*.py")):
        stem = f.stem
        if stem.startswith("_") and stem != "__init__":
            continue
        out.append(prefix + stem if stem != "__init__"
                   else prefix.rstrip("."))
    return [m for m in out if m]


_engine_mods = _discover(ROOT / "src" / "engine_v2", "engine_v2.")
_aware_mods = _discover(ROOT / "src" / "awareness", "awareness.")
_ui_mods = _discover(ROOT / "windows_app")

_project_mods = (["engine_v2"] + _engine_mods
                 + ["awareness"] + _aware_mods
                 + _ui_mods)

# الحاجز: وحدات بغيابها يصل للمالك برنامج ناقص بلا إنذار.
_REQUIRED = (
    "engine_v2.processor_v2", "engine_v2.integration_v2",
    "engine_v2.segmentation_v2", "engine_v2.license_v2",
    "engine_v2.awareness_bridge_v2",
    "awareness.core", "awareness.dialogue", "awareness.healer",
    "awareness.identity", "awareness.perf", "awareness.surgeon",
    "awareness.vitals", "awareness.journal", "awareness.optimizer",
    "awareness.ledger",
    "v2_ui", "photo_editor_v2", "license_ui", "awareness_ui",
    "unified_editor", "ui_scale", "flow_layout",
)
_missing = [m for m in _REQUIRED if m not in _project_mods]
if _missing:
    raise SystemExit(
        "\nفشل البناء متعمّدًا: وحدات حرجة لم تُكتشف على القرص:\n  - "
        + "\n  - ".join(_missing)
        + "\n\nلو مرّ البناء لوصل للمالك برنامج يعمل بلا هذه القدرات "
        "دون أي رسالة خطأ، لأن استيراداتها محمية ب try/except.\n")

print(f"[spec] وحدات مكتشفة: {len(_project_mods)} "
      f"(engine_v2={len(_engine_mods)}, awareness={len(_aware_mods)}, "
      f"ui={len(_ui_mods)})")

hiddenimports = (list(zxing_hidden) + list(onnx_hidden) + list(dil_hidden) + [
    "zxingcpp", "onnxruntime", "dilithium_py", "dilithium_py.ml_dsa",
    "pytesseract",
    "cryptography",
    "cryptography.hazmat.primitives.asymmetric.ed25519",
    "cryptography.hazmat.primitives.ciphers.aead",
    "PIL", "PIL.Image", "PIL.ImageDraw", "PIL.ImageFont", "PIL.features",
] + _project_mods)

a = Analysis(
    [str(ENTRY)],
    pathex=[str(ROOT / "src"), str(ROOT / "windows_app"), str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "pandas",
        "pytest",
        "scipy",
        "tkinter",
        "IPython",
        "notebook",
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
