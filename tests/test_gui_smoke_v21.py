# -*- coding: utf-8 -*-
"""سموك تيست 2.1.0: إقلاع الواجهة، الأزرار الجديدة، المحرر، الحوارات — offscreen."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "windows_app"))

failures = []


def check(name, fn):
    try:
        fn()
        print(f"PASS {name}")
    except Exception as exc:
        failures.append((name, exc))
        print(f"FAIL {name}: {exc}")


def t_imports():
    import native_app  # noqa
    import native_app_v2  # noqa
    import v2_ui  # noqa
    import photo_editor_v2  # noqa
    import license_ui  # noqa


def t_engine_imports():
    from engine_v2 import (naming_v2, batch_refine_v2, cleanup_v2,  # noqa
                           platform_profiles_v2, learning_v2, edge_refine_v2,
                           visual_match_v2, nutrition_smart_v2, license_v2)


def t_license_trial():
    from engine_v2 import license_v2 as lv
    info = lv.effective_license()
    assert info is not None, "effective_license returned None"
    # في بيئة نظيفة يجب أن تكون تجربة نشطة <= 3 أيام
    assert lv.TRIAL_DAYS == 3, f"TRIAL_DAYS={lv.TRIAL_DAYS}"


def t_mainwindow():
    from PySide6.QtWidgets import QApplication
    import native_app
    import native_app_v2
    native_app_v2._patch_ui(native_app)  # بدون _gate_startup: حوار الترخيص blocking في offscreen
    app = QApplication.instance() or QApplication(sys.argv[:1])
    win = native_app.MainWindow()
    # الأزرار الجديدة موجودة
    assert hasattr(win, "link_by_image_button"), "link_by_image_button missing"
    names = [w.objectName() for w in win.header_frame.findChildren(
        __import__("PySide6.QtWidgets", fromlist=["QPushButton"]).QPushButton)]
    for expected in ("v2HelpBtn", "v2SaveNowBtn", "v2RefineBtn", "v2EditorBtn"):
        assert expected in names, f"{expected} not in header: {names}"
    # جدول النتائج بمصغرات مكبرة
    assert win.results_table.iconSize().width() == 80
    win.close()


def t_editor():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])
    import photo_editor_v2 as pe
    dlg = pe.V2PhotoEditorDialog()
    # عناصر جديدة: إزالة الانعكاس، التوزين الدقيق، الشبكة
    for attr in ("glare_enable_cb", "glare_strength", "auto_level_btn"):
        assert hasattr(dlg, attr), f"editor missing {attr}"
    dlg.close()


def t_bulk_rename_tabs():
    from PySide6.QtWidgets import QApplication, QTabWidget
    app = QApplication.instance() or QApplication(sys.argv[:1])
    import v2_ui
    dlg = v2_ui.BulkRenameDialog(parent=None)
    tabs = dlg.findChildren(QTabWidget)
    assert tabs, "BulkRenameDialog has no tabs"
    assert tabs[0].count() >= 3, f"expected >=3 tabs, got {tabs[0].count()}"
    dlg.close()


def t_batch_refine_options():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])
    import v2_ui
    dlg = v2_ui.BatchRefineDialog(parent=None)
    for attr in ("fmt_combo", "chk_compress", "chk_polish"):
        assert hasattr(dlg, attr), f"BatchRefineDialog missing {attr}"
    dlg.close()


def t_platform_profiles():
    from engine_v2 import platform_profiles_v2 as pp
    keys = set(pp.PLATFORM_PROFILES.keys())
    for k in ("noon", "amazon", "salla", "zid", "shopify", "custom"):
        assert k in keys, f"profile {k} missing from {keys}"


check("imports_ui", t_imports)
check("imports_engine", t_engine_imports)
check("license_trial_3days", t_license_trial)
check("mainwindow_buttons", t_mainwindow)
check("editor_new_tools", t_editor)
check("bulk_rename_tabs", t_bulk_rename_tabs)
check("batch_refine_options", t_batch_refine_options)
check("platform_profiles", t_platform_profiles)

if failures:
    print(f"\n{len(failures)} FAILURES")
    sys.exit(1)
print("\nALL GUI SMOKE TESTS PASSED")
