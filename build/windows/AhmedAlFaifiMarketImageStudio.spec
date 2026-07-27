# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import os

from PyInstaller.utils.hooks import collect_all, collect_data_files


ROOT = Path(os.getcwd()).resolve()
APP_ID = "AhmedAlFaifiMarketImageStudio"
ENTRY = ROOT / "windows_app" / "native_app.py"
ICON = ROOT / "windows_app" / "assets" / "app_icon.ico"
VERSION_INFO = ROOT / "build" / "windows" / "version_info.txt"


datas = [
    (str(ROOT / "resources" / "models" / "u2net.onnx"), "resources/models"),
    (str(ROOT / "resources" / "models" / "u2netp.onnx"), "resources/models"),
    (str(ROOT / "windows_app" / "assets" / "app_icon.png"), "windows_app/assets"),
    (str(ROOT / "windows_app" / "assets" / "app_icon.ico"), "windows_app/assets"),
    (str(ROOT / "src" / "smart_catalog_vision" / "final_images.pyc"), "smart_catalog_vision"),
    (str(ROOT / "src" / "smart_catalog_vision" / "imaging.pyc"), "smart_catalog_vision"),
    (str(ROOT / "src" / "smart_catalog_vision" / "normalization.pyc"), "smart_catalog_vision"),
    (str(ROOT / "src" / "smart_catalog_vision" / "product_segmentation.pyc"), "smart_catalog_vision"),
    (str(ROOT / "src" / "smart_catalog_vision" / "thin_branch_pruner.pyc"), "smart_catalog_vision"),
    (str(ROOT / "README.md"), "."),
    (str(ROOT / "RELEASE_NOTES_1.2.1.md"), "."),
    (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
    (str(ROOT / "VERSION"), "."),
]
datas += collect_data_files("openpyxl")

zxing_datas, zxing_binaries, zxing_hidden = collect_all("zxingcpp")
onnx_datas, onnx_binaries, onnx_hidden = collect_all("onnxruntime")
datas += zxing_datas + onnx_datas
binaries = list(zxing_binaries) + list(onnx_binaries)
hiddenimports = list(zxing_hidden) + list(onnx_hidden) + ["zxingcpp", "onnxruntime"]


a = Analysis(
    [str(ENTRY)],
    pathex=[str(ROOT / "src"), str(ROOT)],
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
