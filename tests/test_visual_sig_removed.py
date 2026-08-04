# -*- coding: utf-8 -*-
"""2.9.9 — حراسة: منظومة البصمات البصرية ونسبة التشابه محذوفة نهائيًا.

خلفية القرار
============
في 2.9.6 كان اختبار ``test_visual_sig_async.py`` يحرس أن بناء البصمات
البصرية لا يقع على خيط الواجهة، لأن السلسلة ``_show_selected_preview →
_update_manual_selection_context → _refresh_smart_link_button →
_visual_suggestion_for`` كانت تقرأ كل صورة من القرص وتفكّ ترميزها
(~47 مللي ثانية للصورة)، فتُجمّد النافذة خمس ثوانٍ على دفعة من 109 صنف.

في 2.9.9 ألغى المالك **نسبة التشابه** بالكامل لأنها رقم غير موثوق ولا
مفهوم، فلم يبق للبصمات أي مستهلك. حُذفت المنظومة من الجذور طبقًا لقاعدة
«لا تكرار ولا شفرة ميتة»، ومعها اختفى سبب التجميد أصلًا: لم تبق أي
قراءة من القرص في مسار الواجهة.

ولهذا انقلب دور الاختبار: لم يعد يحرس أن العمل غير متزامن، بل يحرس أن
**الشفرة لا تعود**. أي إعادة لأي اسم من القائمة أدناه تُفشل الاختبار
وتنبّه المطور أنه يخالف قرار المالك.

الفحوص هيكلية على نص المصدر ثم سلوكية على الصنف، فلا تحتاج شاشة ولا صورًا.
"""
from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "windows_app" / "native_app.py"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "windows_app"))
os.environ.setdefault("MIS_SKIP_LICENSE", "1")
os.environ.setdefault("MIS_HEADLESS", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# كل اسم أُزيل نهائيًا في 2.9.9 — لا يجوز أن يعود أي منها.
REMOVED_NAMES = (
    "VisualSignatureWorker",
    "_visual_suggestion_for",
    "_visual_sig_lookup",
    "_queue_visual_signatures",
    "_flush_visual_signature_queue",
    "_on_visual_signatures_ready",
    "_warm_visual_signatures",
    "_visual_sig_lru",
    "_visual_sig_pending",
    "_visual_warm_timer",
)

# عبارات نسبة التشابه التي كانت تُعرض في الواجهة.
REMOVED_TEXTS = ("نسبة التشابه", "تشابه بصري", "التشابه البصري")

# الدوال الساخنة: تُنفَّذ عند كل نقرة صف فيجب أن تبقى خفيفة بلا قرص.
HOT_METHODS = (
    "_update_manual_selection_context",
    "_refresh_smart_link_button",
)

OK = FAIL = 0


def say(m: str) -> None:
    print(m, flush=True)


def check(label: str, cond: bool, detail: str = "") -> bool:
    global OK, FAIL
    if cond:
        OK += 1
        say(f"  PASS {label}" + (f" — {detail}" if detail else ""))
    else:
        FAIL += 1
        say(f"  FAIL {label}" + (f" — {detail}" if detail else ""))
    return bool(cond)


def executable_code(src: str) -> str:
    """يُزيل التعليقات ونصوص التوثيق ليبقى الكود التنفيذي وحده.

    ضروري لأن الشفرة تحتفظ بتعليقات تشرح **سبب** الحذف وتذكر الأسماء
    المحذوفة صراحةً حتى لا يعيدها أحد بحسن نية. البحث الساذج في النص
    الكامل سيعدّ هذه التعليقات «عودة للوظيفة» فيُفشل الاختبار ظلمًا.
    """
    src = re.sub(r'"""(?:.|\n)*?"""', '""', src)
    src = re.sub(r"'''(?:.|\n)*?'''", "''", src)
    out = []
    for line in src.splitlines():
        idx = line.find("#")
        if idx >= 0 and (line[:idx].count('"') + line[:idx].count("'")) % 2 == 0:
            line = line[:idx]
        out.append(line)
    return "\n".join(out)


def find_class(tree: ast.Module, name: str) -> ast.ClassDef | None:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


def find_method(cls: ast.ClassDef, name: str) -> ast.FunctionDef | None:
    for node in cls.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def calls_in(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            func = sub.func
            if isinstance(func, ast.Attribute):
                out.add(func.attr)
            elif isinstance(func, ast.Name):
                out.add(func.id)
    return out


def main() -> int:
    say("=== حراسة إزالة البصمات البصرية ونسبة التشابه (2.9.9) ===")

    say("\n[1] الملف المصدر متاح للتفتيش")
    if not check("native_app.py موجود", APP.is_file(), str(APP)):
        return 1
    raw = APP.read_text(encoding="utf-8")
    code = executable_code(raw)
    tree = ast.parse(raw)

    say("\n[2] كل أسماء المنظومة محذوفة من الكود التنفيذي")
    for name in REMOVED_NAMES:
        hits = code.count(name)
        check(f"{name} غير موجود", hits == 0,
              f"{hits} ورودًا" if hits else "")
    # `build_signature` قد تبقى في المحرك لاستخدامات أخرى، لكن يجب ألّا
    # تُستدعى من الواجهة إطلاقًا — وهذا هو مصدر التجميد الأصلي.
    check("build_signature غير مستدعاة في الواجهة",
          "build_signature" not in code, str(code.count("build_signature")))

    say("\n[3] لا نسبة تشابه تُعرض للمستخدم")
    for text in REMOVED_TEXTS:
        hits = code.count(text)
        check(f"«{text}» غير معروضة", hits == 0,
              f"{hits} ورودًا" if hits else "")

    say("\n[4] الزر الذكي باقٍ ويعمل بدليل بديل واضح")
    win = find_class(tree, "MainWindow")
    if not check("الصنف MainWindow موجود", win is not None):
        return 1
    assert win is not None
    refresh = find_method(win, "_refresh_smart_link_button")
    check("_refresh_smart_link_button موجودة", refresh is not None)
    check("زر الربط الذكي باقٍ في الواجهة", "smart_link_button" in code)
    if refresh is not None:
        body = ast.get_source_segment(raw, refresh) or ""
        check("لا يستدعي أي دالة بصرية محذوفة",
              not any(n in body for n in REMOVED_NAMES))
        # الدليل البديل الذي اختاره المالك: أقرب صورة مرتبطة أعلى القائمة.
        check("يعتمد أقرب صورة مرتبطة (ترتيب التصوير)",
              "أقرب" in body or "neighbor" in body.lower())

    say("\n[5] الدوال الساخنة بلا أي قراءة صور من القرص")
    for name in HOT_METHODS:
        method = find_method(win, name)
        if method is None:
            check(f"{name} موجودة", False, "غير موجودة")
            continue
        used = calls_in(method)
        heavy = {"imread", "open", "load", "build_signature"} & used
        # `open` قد يظهر لأغراض غير الصور، فنفحص نص الجسم للدقة.
        body = ast.get_source_segment(raw, method) or ""
        img_read = ("QImage(" in body or "Image.open" in body
                    or "cv2.imread" in body or "QPixmap(" in body)
        check(f"{name} لا تفكّ ترميز صورة", not img_read,
              str(sorted(heavy)) if heavy and img_read else "")

    say("\n[6] الواجهة تُقلع فعلًا بعد الحذف (لا مرجع معلّق)")
    try:
        import importlib
        mod = importlib.import_module("native_app")
        cls = getattr(mod, "MainWindow", None)
        check("MainWindow مستورد بلا أخطاء", cls is not None)
        check("لا صنف VisualSignatureWorker في الوحدة",
              not hasattr(mod, "VisualSignatureWorker"))
        if cls is not None:
            for name in REMOVED_NAMES:
                if name.startswith("_visual_sig_l") or name.startswith("_visual_sig_p") \
                        or name == "_visual_warm_timer":
                    continue      # سمات نسخة لا سمات صنف
                check(f"MainWindow بلا سمة {name}", not hasattr(cls, name))
    except Exception as exc:                       # pragma: no cover
        check("استيراد الواجهة", False, f"{type(exc).__name__}: {exc}")

    say("\n" + "═" * 62)
    say(f"===== {OK} passed / {FAIL} failed =====")
    if FAIL:
        say("أُعيدت شفرة محذوفة أو انكسر الزر الذكي — راجع قرار المالك 2.9.9")
    else:
        say("ALL_VISUAL_SIG_REMOVED_TESTS_OK")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
