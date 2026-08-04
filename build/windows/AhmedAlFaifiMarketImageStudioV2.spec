# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — Ahmed Al-Faifi Market Image Studio V2.0.0."""
from pathlib import Path
import importlib.util
import os
from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(os.getcwd()).resolve()
APP_ID = "AhmedAlFaifiMarketImageStudio"
ENTRY = ROOT / "windows_app" / "native_app_v2.py"
ICON = ROOT / "windows_app" / "assets" / "app_icon.ico"
VERSION_INFO = ROOT / "build" / "windows" / "version_info.txt"

# ───────────── نماذج القص ─────────────
#
# كانت النسخة السابقة تطلب النماذج من ``resources/models/`` وهو
# مجلد **غير موجود** (بقية من بنية 1.2.1)؛ والنماذج الثلاثة
# تسكن فعلًا في ``src/engine_v2/models/``. وPyInstaller يفشل عند غياب
# ملف بيانات مسرود، فكان البناء يتوقف قبل أن يبدأ.
#
# والمسار المقصود داخل الحزمة هو ``engine_v2/models`` لأن
# ``paths_v2._candidates()`` يبحث في ``_MEIPASS/engine_v2/models``.
#
# أي نموذج يُحزَم؟ ``runtime_deps_v2.MODEL_FILENAMES`` يرتّب الأفضلية:
# isnet (أدق) ـ u2net (متوسط) ـ u2netp (الأخف). فنحزم isnet إلزامًا
# وu2netp (4.4م.ب فقط) كشبكة أمان خفيفة تضمن عمل القص دائمًا،
# ونستثني u2net (168م.ب) لأن منفعته حدية أمام isnet وآلية
# التنزيل التلقائي تجلبه عند الحاجة — توفير 168م.ب من المُثبِّت.
_MODELS_SRC = ROOT / "src" / "engine_v2" / "models"

datas = [
    (str(_MODELS_SRC / "isnet-general-use.onnx"), "engine_v2/models"),
    (str(_MODELS_SRC / "u2netp.onnx"), "engine_v2/models"),
    (str(ROOT / "src" / "engine_v2" / "assets" / "NotoNaskhArabic-Regular.ttf"),
     "engine_v2/assets"),
    (str(ROOT / "src" / "engine_v2" / "assets" / "NotoNaskhArabic-Bold.ttf"),
     "engine_v2/assets"),
    # app assets
    (str(ROOT / "windows_app" / "assets" / "app_icon.png"), "windows_app/assets"),
    (str(ROOT / "windows_app" / "assets" / "app_icon.ico"), "windows_app/assets"),
    # legacy compiled pipeline (1.2.1 proven engine)
    #
    # `__init__.py` و`pipeline.pyc` كانا ناقصين حتى 2.9.8 فكان
    # `from smart_catalog_vision import pipeline` يفشل في الحزمة
    # المجمَّدة وحدها، فتُعطَّل تسريعات state_cache وmatch_speed
    # بصمت («speedup unavailable») ويسقط معهما مسار المجلد
    # المنجز الذي يستورد `_CatalogIndex` و`FinalImageOptions`.
    # المجلد بلا `__init__.py` ليس حزمة فلا يُرى `pipeline` أصلًا.
    (str(ROOT / "src" / "smart_catalog_vision" / "__init__.py"), "smart_catalog_vision"),
    (str(ROOT / "src" / "smart_catalog_vision" / "pipeline.pyc"), "smart_catalog_vision"),
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

# الحاجز الأول: ملفات البيانات.
#
# PyInstaller يفشل عند غياب ملف مسرود، لكن رسالته غامضة وتأتي
# بعد دقائق من التحليل. نفحص مقدمًا ونقول بالعربية ما الناقص
# ومن أين يُجلب، لأن النماذج مستبعدة من git (انظر .gitignore)
# فيجد المالك نفسه أمام مجلد نماذج فارغ بعد الاستنساخ.
_missing_data = [src for src, _ in datas if not Path(src).exists()]
if _missing_data:
    raise SystemExit(
        "\nفشل البناء: ملفات مطلوبة غير موجودة:\n  - "
        + "\n  - ".join(_missing_data)
        + "\n\nإن كانت نماذج .onnx: هي مستبعدة من git لحجمها، وتُجلب\n"
        "بتشغيل البرنامج مرة واحدة (يُنزّلها تلقائيًا)، أو بنسخها يدويًا\n"
        "إلى src/engine_v2/models/ .\n")

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

# ───────────── إضافات منصّة Qt — جمع صريح إلزامي وحاجز مطلق ─────────────
#
# أخطر عطل وُجد في هذا المشروع: خرجت الحزمة مرةً بلا أي
# مجلد `PySide6/plugins` — 14 ملفًا فقط في `_internal/PySide6/`.
# وبلا `platforms/qwindows.dll` لا تستطيع Qt إنشاء أي نافذة
# فيموت البرنامج عند الإقلاع برسالة:
#   "no Qt platform plugin could be initialized"
# على **كل جهاز** بما فيه ويندوز 11 حقيقي. أي أن العطل كان
# سيصل للمالك.
#
# السبب: خُطّاف PySide6 المدمج في PyInstaller يعرف بنية نسخ Qt
# التي صدرت قبله؛ فإن تغيرت بنية عجلة PySide6 (وقد تغيرت فى 6.11)
# يعجز الخطّاف عن جمع الإضافات **ولا يُصدر أي تحذير**.
# فلا يجوز الاعتماد عليه: نجمع الإضافات صراحةً من القرص ونفشل
# البناء إن غابت `qwindows.dll`.
#
# لماذا مجموعات منتقاة لا الكل: البرنامج Widgets خالص بلا QML
# ولا 3D ولا وسائط؛ فنستبعد qmltooling وsceneparsers وassetimporters
# وmultimedia وdesigner وgeoservices… (مئات الميجابايت بلا منفعة).
_QT_PLUGIN_GROUPS = (
    "platforms",              # إلزامي مطلقًا — qwindows.dll
    "styles",                 # مطابقة مظهر ويندوز
    "imageformats",           # قراءة/كتابة WebP وJPEG وICO
    "iconengines",            # أيقونات SVG في الواجهة
    "platforminputcontexts",  # إدخال العربية
    "tls",                    # HTTPS للترخيص وتنزيل النماذج
    "networkinformation",     # كشف توفر الشبكة
    "generic",                # أجهزة إدخال عامة
)

_qt_plugin_files = 0
_qwindows_found = False
_pyside_spec = importlib.util.find_spec("PySide6")
if _pyside_spec and _pyside_spec.submodule_search_locations:
    _pyside_dir = Path(list(_pyside_spec.submodule_search_locations)[0])
    _plugins_root = _pyside_dir / "plugins"
    for _grp in _QT_PLUGIN_GROUPS:
        _grp_dir = _plugins_root / _grp
        if not _grp_dir.is_dir():
            continue
        for _dll in sorted(_grp_dir.rglob("*.dll")):
            _rel = _dll.relative_to(_plugins_root).parent
            binaries.append((str(_dll), str(Path("PySide6/plugins") / _rel)))
            _qt_plugin_files += 1
            if _dll.name.lower() == "qwindows.dll":
                _qwindows_found = True

if not _qwindows_found:
    raise SystemExit(
        "\nفشل البناء متعمّدًا: إضافة منصّة Qt `qwindows.dll` غير موجودة.\n"
        "بلاها لا تستطيع Qt إنشاء نافذة فلا يُقلع البرنامج على أي جهاز\n"
        "ويموت برسالة 'no Qt platform plugin could be initialized'.\n\n"
        "الموضع المتوقع: <site-packages>/PySide6/plugins/platforms/qwindows.dll\n"
        "أعد تركيب PySide6 كاملة (لا PySide6-Essentials وحدها إن كانت مقطوعة).\n")

print(f"[spec] إضافات Qt المحزومة: {_qt_plugin_files} ملفًا")

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
