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
        # إظهار النوع والموقع — بعض الاستثناءات (مثل AssertionError
        # بلا رسالة) تطبع فارغًا فيضيع السبب ويصعب الإصلاح.
        import traceback
        tb = traceback.extract_tb(exc.__traceback__)
        where = f"{tb[-1].filename.split('/')[-1]}:{tb[-1].lineno}" if tb else "?"
        detail = str(exc) or f"{type(exc).__name__} بلا رسالة"
        code = tb[-1].line if tb else ""
        print(f"FAIL {name}: {detail} @ {where}"
              + (f"\n      السطر: {code}" if code else ""))


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
    # v2.2: الأزرار انتقلت من الهيدر إلى شريط أدوات v2Toolbar مستقل (إصلاح التداخل)
    names = [w.objectName() for w in win.findChildren(
        __import__("PySide6.QtWidgets", fromlist=["QPushButton"]).QPushButton)]
    # 2.6+: زر «v2EditorBtn» (محرر الصور المنفصل) حُذف — أدواته
    # مدمجة في تبويب «تعديل الصورة» (editImageButton) داخل النافذة.
    for expected in ("v2HelpBtn", "v2SaveNowBtn", "v2RefineBtn",
                     "v2NutritionToolbarBtn", "editImageButton"):
        assert expected in names, f"{expected} not in window: {names[:20]}"
    # ولا يجوز عودة المحرر المنفصل كزر ثانٍ (تكرار)
    assert "v2EditorBtn" not in names, \
        "v2EditorBtn عاد — تكرار لمحرر الصور المدمج"
    # v2.2: أداة الميول اليدوية الخارجية في شريط الربط
    assert hasattr(win, "manual_tilt_spin"), "manual_tilt_spin missing"
    # جدول النتائج بمصغرات مكبرة — لكن القيمة **تكيفية** لا صلبة:
    # المرجع 80px يتقلّص تلقائيًا حتى 28px عند شاشة/نافذة ضيقة لمنع
    # قص الباركود أو الاسم (مطلب المالك: لا نص مقصوص ولا تمرير
    # أفقي). فرض == 80 يكسر التكيف ويفشل في offscreen (عرض صغير).
    icon_side = win.results_table.iconSize().width()
    assert 28 <= icon_side <= 80, \
        f"حجم المصغرة {icon_side} خارج المدى المقبول 28..80"
    assert win.results_table.iconSize().height() == icon_side, \
        "المصغرة غير مربعة — تشوه نسبة العرض"
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


def t_no_rename_duplicate():
    """2.9.5 — أداة إعادة التسمية المستقلة حُذفت نهائيًا.

    قرار المالك: لا تكرار — وظيفة واحدة في مكان واحد. هذا الاختبار
    يحرس القرار: أي محاولة مستقبلية لإعادة النافذة أو زرها تُفشله.
    """
    import v2_ui
    import native_app_v2
    import inspect
    assert not hasattr(v2_ui, "BulkRenameDialog"), \
        "BulkRenameDialog عادت للوجود — تكرار ممنوع"
    src = inspect.getsource(native_app_v2)
    assert 'QPushButton("أداة إعادة التسمية")' not in src, \
        "زر «أداة إعادة التسمية» عاد لشريط الأدوات — تكرار ممنوع"
    assert "v2_open_rename_tool" not in src, \
        "منفذ v2_open_rename_tool عاد — تكرار ممنوع"


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
check("no_rename_duplicate", t_no_rename_duplicate)
check("batch_refine_options", t_batch_refine_options)
check("platform_profiles", t_platform_profiles)

if failures:
    print(f"\n{len(failures)} FAILURES")
    sys.exit(1)
print("\nALL GUI SMOKE TESTS PASSED")
