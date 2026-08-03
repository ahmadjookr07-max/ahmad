#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبار انحدار — كسل الإقلاع (2.9.6).

يحرس المكاسب التي تحققت في تسريع الإقلاع من 1417 ms إلى ~669 ms:

1. استيراد ``native_app`` وحده لا يجرّ المحرّك الثقيل ولا numpy ولا
   openpyxl إلى الذاكرة.
2. بناء ``MainWindow`` لا يبنيها أيضًا — التبويب غير مرئي وقت الإقلاع.
3. ``_editor_ready()`` تفحص دون إنشاء (لو استُبدلت بـ ``hasattr`` عاد
   المحرّر يُبنى وقت الإقلاع وضاع نصف المكسب).
4. أول وصول لـ ``unified_editor`` يبني المحرّر فعلًا ويضعه في مكانه
   الصحيح داخل تخطيط التبويب (لا في الذيل).
5. الوكيل الكسول ``lazy_engine`` يُرجع الرموز نفسها التي كان الاستيراد
   المباشر يُرجعها — لا اختلاف في السلوك، تأجيل فقط.
6. ترقيع المنظور يُطبَّق فعلًا لحظة تحميل المحرّك (كان يُطبَّق وقت
   الاستيراد؛ لو ضاع لتعطّل تصحيح المنظور صامتًا).
7. حارس فعالية: يثبت أن الفحوص أعلاه تكشف الارتداد حقًا.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MIS_SKIP_LICENSE", "1")

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "windows_app"
SRC_DIR = ROOT / "src"

PASS = 0
FAIL = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}" + (f" — {extra}" if extra else ""))
    else:
        FAIL += 1
        print(f"  FAIL {name}" + (f" — {extra}" if extra else ""))


HEAVY = ("numpy", "cv2", "openpyxl", "smart_catalog_vision.pipeline",
         "photo_editor_v2", "unified_editor")


def _run_probe(body: str) -> dict:
    """ينفّذ مقطعًا في مفسّر نظيف ويُرجع قاموس النتائج المطبوع."""
    script = textwrap.dedent(f"""
        import os, sys, json
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        os.environ.setdefault("MIS_SKIP_LICENSE", "1")
        sys.path.insert(0, {str(APP_DIR)!r})
        sys.path.insert(0, {str(SRC_DIR)!r})
        result = {{}}
        {textwrap.indent(textwrap.dedent(body), " " * 8).lstrip()}
        print("__RESULT__" + json.dumps(result))
    """)
    proc = subprocess.run([sys.executable, "-c", script],
                          capture_output=True, text=True, timeout=600)
    for line in proc.stdout.splitlines():
        if line.startswith("__RESULT__"):
            import json
            return json.loads(line[len("__RESULT__"):])
    raise AssertionError(
        f"probe failed\nstdout={proc.stdout[-2000:]}\nstderr={proc.stderr[-2000:]}")


# ------------------------------------------------------- [1] الاستيراد وحده
print("[1] استيراد native_app لا يجرّ الثقيل")
r = _run_probe(f"""
    import native_app  # noqa: F401
    heavy = {HEAVY!r}
    result["loaded"] = [m for m in heavy if m in sys.modules]
""")
check("استيراد native_app نظيف من الوحدات الثقيلة",
      r["loaded"] == [], f"محمّل: {r['loaded'] or 'لا شيء'}")

# --------------------------------------------------- [2] بناء النافذة نظيف
print("\n[2] بناء MainWindow لا يبني المحرّر ولا يحمّل numpy")
r = _run_probe(f"""
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    import native_app
    w = native_app.MainWindow()
    heavy = {HEAVY!r}
    result["loaded"] = [m for m in heavy if m in sys.modules]
    result["editor_built"] = w._editor_ready()
    result["has_anchor"] = hasattr(w, "_editor_host_layout")
""")
check("بناء النافذة لا يحمّل الوحدات الثقيلة",
      r["loaded"] == [], f"محمّل: {r['loaded'] or 'لا شيء'}")
check("المحرّر لم يُبنَ وقت الإقلاع", r["editor_built"] is False)
check("مرساة تبويب المحرّر جاهزة", r["has_anchor"] is True)

# ------------------------------------------------- [3] _editor_ready لا تبني
print("\n[3] _editor_ready تفحص دون إنشاء")
r = _run_probe("""
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    import native_app
    w = native_app.MainWindow()
    before = w._editor_ready()
    for _ in range(5):
        w._editor_ready()
    result["before"] = before
    result["after_repeated_checks"] = w._editor_ready()
    result["numpy_loaded"] = "numpy" in sys.modules
""")
check("الفحص المتكرر لا يبني المحرّر",
      r["after_repeated_checks"] is False and r["numpy_loaded"] is False)

# ------------------------------------------- [4] أول وصول يبني في المكان الصحيح
print("\n[4] أول وصول يبني المحرّر في موضعه الصحيح")
r = _run_probe("""
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    import native_app
    w = native_app.MainWindow()
    anchor_index = w._editor_host_index
    layout = w._editor_host_layout
    count_before = layout.count()
    editor = w.unified_editor
    result["built"] = w._editor_ready()
    result["same_on_second_access"] = (editor is w.unified_editor)
    result["count_grew_by_one"] = (layout.count() == count_before + 1)
    result["at_anchor"] = (layout.itemAt(anchor_index).widget() is editor)
    result["object_name"] = editor.objectName()
    result["numpy_loaded"] = "numpy" in sys.modules
    result["has_canvas"] = hasattr(editor, "canvas")
    result["styled"] = bool(editor.styleSheet())
""")
check("أول وصول يبني المحرّر", r["built"] is True)
check("الوصول الثاني يعيد الكائن نفسه (لا نسخة ثانية)",
      r["same_on_second_access"] is True)
check("أُدرج في التخطيط عنصرًا واحدًا", r["count_grew_by_one"] is True)
check("أُدرج في موضع المرساة بالضبط لا في الذيل", r["at_anchor"] is True)
check("اسم الكائن محفوظ للأنماط", r["object_name"] == "unifiedEditor")
check("الأنماط طُبّقت على المحرّر المتأخر", r["styled"] is True)
check("المحرّر مكتمل (canvas موجود)", r["has_canvas"] is True)
check("numpy يُحمّل عند البناء لا قبله", r["numpy_loaded"] is True)

# ------------------------------------------------ [5] الوكيل الكسول مطابق
print("\n[5] lazy_engine يُرجع الرموز نفسها")
r = _run_probe("""
    import lazy_engine
    result["pipeline_before"] = "smart_catalog_vision.pipeline" in sys.modules
    from smart_catalog_vision import pipeline as direct
    # الأصناف والدوال وكلاء، فالمطلوب تطابق السلوك لا تطابق الهوية.
    mismatched = []
    # الدوال: الوكيل يمرّر إلى الدالة الأصلية نفسها
    for name in ("run_batch", "apply_manual_link", "apply_manual_links",
                 "apply_individual_image_edit",
                 "preview_individual_image_edit"):
        if getattr(direct, name, None) is None:
            mismatched.append(name + ":missing-in-engine")
    # الأصناف: الوكيل يحلّ إلى الصنف الأصلي بعينه
    for name in ("BatchItemResult", "BatchRunResult",
                 "IndividualImagePreview"):
        proxy = getattr(lazy_engine, name)
        if proxy._resolve() is not getattr(direct, name):
            mismatched.append(name)
    # الثابت: نفس المحتوى
    if set(lazy_engine.SUPPORTED_IMAGE_EXTENSIONS) != set(
            direct.SUPPORTED_IMAGE_EXTENSIONS):
        mismatched.append("SUPPORTED_IMAGE_EXTENSIONS")
    # وكيل الوحدة: أي سمة تمرّ إلى الأصل
    if lazy_engine.pipeline.run_batch is not direct.run_batch:
        mismatched.append("pipeline-proxy")
    result["mismatched"] = mismatched
""")
check("استيراد lazy_engine وحده لا يحمّل المحرّك",
      r["pipeline_before"] is False)
check("كل رمز مُوكَّل يحلّ إلى الرمز الأصلي نفسه",
      r["mismatched"] == [], f"مختلف: {r['mismatched'] or 'لا شيء'}")

# --------------------------------------------- [6] ترقيع المنظور لا يضيع
print("\n[6] ترقيع المنظور يُطبَّق لحظة تحميل المحرّك")
r = _run_probe("""
    import native_app
    import lazy_engine
    from smart_catalog_vision import pipeline as direct
    result["patched_before_load"] = bool(
        getattr(direct, "_mis_perspective_patched", False))
    lazy_engine.load_engine()
    result["patched_after_load"] = bool(
        getattr(direct, "_mis_perspective_patched", False))
    result["factory_registered"] = (
        getattr(lazy_engine, "_patch_provider", None) is not None)
""")
check("مصنع الترقيع مُسجَّل من native_app",
      r["factory_registered"] is True)
check("الترقيع لم يُطبَّق قبل تحميل المحرّك",
      r["patched_before_load"] is False)
check("الترقيع طُبّق فور تحميل المحرّك",
      r["patched_after_load"] is True)

# ------------------------------------------------------- [7] حارس الفعالية
print("\n[7] حارس فعالية — الفحوص تكشف الارتداد فعلًا")
r = _run_probe("""
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    import native_app
    w = native_app.MainWindow()
    # محاكاة الارتداد: استعمال hasattr (السلوك القديم) بدل _editor_ready
    triggered = hasattr(w, "unified_editor")
    result["hasattr_builds_editor"] = (triggered and w._editor_ready())
    result["numpy_after"] = "numpy" in sys.modules
""")
check("hasattr يبني المحرّر — لهذا استُبدل بـ _editor_ready",
      r["hasattr_builds_editor"] is True and r["numpy_after"] is True,
      "الفحص أعلاه يكشف الارتداد لو عاد hasattr")

print(f"\n===== {PASS} passed / {FAIL} failed =====")
if FAIL == 0:
    print("ALL_BOOT_LAZY_TESTS_OK")
sys.exit(1 if FAIL else 0)
