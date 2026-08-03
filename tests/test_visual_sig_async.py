"""2.9.6 — اختبار انحدار: بناء البصمات البصرية لا يقع أبدًا على خيط الواجهة.

الخلل الذي يعالجه هذا الاختبار: عند اختيار أي صف في لوحة الربط كانت سلسلة
``_show_selected_preview → _update_manual_selection_context →
_refresh_smart_link_button → _visual_suggestion_for`` تبني بصمة بصرية لكل
صورة في الدفعة على خيط الواجهة نفسه (~47 مللي ثانية للصورة)، فتُجمّد النافذة
خمس ثوانٍ كاملة على دفعة من 109 صنف ويعرضها ويندوز بيضاء مع «لا يستجيب».

الفحوص هنا هيكلية وسلوكية معًا، ولا تحتاج شاشة ولا صورًا حقيقية:
  1. ``VisualSignatureWorker`` موجود، وريث ``QThread``، ويبني داخل ``run`` فقط.
  2. لا يوجد أي استدعاء لـ ``build_signature`` داخل دوال مسار الواجهة.
  3. ``_visual_sig_lookup`` يقرأ من الكاش ولا يبني، ويسجّل الناقص للخلفية.
  4. ``_queue_visual_signatures`` يملأ قائمة الانتظار ويشغّل المؤقّت.
  5. ``_on_visual_signatures_ready`` يودع الناجح، ويعزل الفاشل، ويحترم السعة.
  6. التسخين المسبق مُستدعى بعد الدفعة وبعد كل ربط.
"""
from __future__ import annotations

import ast
import os
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows_app"))
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SOURCE_PATH = ROOT / "windows_app" / "native_app.py"
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)

PASS = 0
FAIL = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}{(' — ' + detail) if detail else ''}")


def find_class(name: str) -> ast.ClassDef | None:
    for node in TREE.body:
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


# ----------------------------------------------------------------------
# 1) العامل الخلفي
# ----------------------------------------------------------------------
def test_worker_shape() -> None:
    print("\n[1] عامل البصمات الخلفي")
    cls = find_class("VisualSignatureWorker")
    check("الصنف VisualSignatureWorker موجود", cls is not None)
    if cls is None:
        return
    bases = {b.id if isinstance(b, ast.Name) else getattr(b, "attr", "")
             for b in cls.bases}
    check("يرث QThread", "QThread" in bases, str(bases))
    run = find_method(cls, "run")
    check("يملك run()", run is not None)
    check("يملك cancel() للإيقاف التعاوني",
          find_method(cls, "cancel") is not None)
    if run is not None:
        check("البناء يقع داخل run فقط",
              "build_signature" in calls_in(run))
    check("يبثّ إشارة ready",
          any(isinstance(n, ast.Assign)
              and any(getattr(t, "id", "") == "ready" for t in n.targets)
              for n in cls.body))


# ----------------------------------------------------------------------
# 2) لا بناء على خيط الواجهة
# ----------------------------------------------------------------------
UI_PATH_METHODS = [
    "_visual_suggestion_for",
    "_refresh_smart_link_button",
    "_update_manual_selection_context",
    "_show_selected_preview",
    "_start_link_by_image",
    "_visual_sig_lookup",
    "_populate_results",
]


def test_no_ui_thread_build() -> None:
    print("\n[2] لا بناء بصمات على خيط الواجهة")
    win = find_class("MainWindow")
    check("الصنف MainWindow موجود", win is not None)
    if win is None:
        return
    for name in UI_PATH_METHODS:
        method = find_method(win, name)
        if method is None:
            check(f"{name} موجودة", False, "غير موجودة")
            continue
        check(f"{name} لا تستدعي build_signature",
              "build_signature" not in calls_in(method))


# ----------------------------------------------------------------------
# 3) سلوك الكاش والطابور — بمحاكاة خفيفة بلا Qt
# ----------------------------------------------------------------------
class _Timer:
    def __init__(self) -> None:
        self.active = False
        self.starts = 0

    def isActive(self) -> bool:
        return self.active

    def start(self) -> None:
        self.active = True
        self.starts += 1

    def stop(self) -> None:
        self.active = False


class _Sig:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok


class _FakeWindow:
    """كائن خفيف يستعير دوال MainWindow الحقيقية غير المرتبطة بـ Qt."""

    def __init__(self) -> None:
        self._visual_sig_lru: "OrderedDict[str, object]" = OrderedDict()
        self._visual_sig_capacity = 3
        self._visual_sig_pending: set[str] = set()
        self._visual_sig_failed: set[str] = set()
        self._visual_warm_timer = _Timer()
        self._refreshed = 0

    def _refresh_smart_link_button(self) -> None:
        self._refreshed += 1


def _bind(name: str):
    from native_app import MainWindow  # type: ignore
    return getattr(MainWindow, name)


def test_cache_and_queue() -> None:
    print("\n[3] سلوك الكاش وطابور الخلفية")
    lookup = _bind("_visual_sig_lookup")
    queue = _bind("_queue_visual_signatures")
    ready = _bind("_on_visual_signatures_ready")

    win = _FakeWindow()

    # قراءة مسار غير مُخزّن: لا بناء، ويُسجَّل ناقصًا
    missing: list[str] = []
    check("قراءة مسار غير مخزّن ترجع None",
          lookup(win, "/a.jpg", missing) is None)
    check("المسار الناقص يُسجَّل للخلفية", missing == ["/a.jpg"], str(missing))

    # المسار الفارغ يُتجاهل
    check("المسار الفارغ يُتجاهل بلا تسجيل",
          lookup(win, "", missing) is None and missing == ["/a.jpg"])

    # الجدولة تملأ الطابور وتُشعل المؤقّت
    queue(win, missing)
    check("الطابور امتلأ", win._visual_sig_pending == {"/a.jpg"})
    check("المؤقّت اشتعل مرة واحدة", win._visual_warm_timer.starts == 1)

    # لا ازدواج في الجدولة
    queue(win, ["/a.jpg"])
    check("لا يُعاد جدولة مسار قيد الانتظار",
          win._visual_warm_timer.starts == 1)

    # وصول النتائج: الناجح يُخزّن، الفاشل يُعزل
    win._visual_sig_pending.clear()
    win._visual_warm_timer.active = False
    ready(win, {"/a.jpg": _Sig(True), "/b.jpg": _Sig(False), "/c.jpg": None})
    check("الناجح دخل الكاش", "/a.jpg" in win._visual_sig_lru)
    check("الفاشل عُزل في قائمة الفشل",
          {"/b.jpg", "/c.jpg"} <= win._visual_sig_failed)
    check("الواجهة تُحدَّث مرة واحدة عند الجاهزية", win._refreshed == 1)

    # الفاشل لا يُعاد طلبه أبدًا (منع حلقة لا نهائية)
    missing2: list[str] = []
    lookup(win, "/b.jpg", missing2)
    check("الفاشل لا يُعاد جدولته", missing2 == [], str(missing2))

    # القراءة من الكاش لا تُسجّل ناقصًا
    missing3: list[str] = []
    check("القراءة من الكاش ترجع البصمة",
          lookup(win, "/a.jpg", missing3) is not None)
    check("القراءة من الكاش لا تُسجّل ناقصًا", missing3 == [])

    # سعة LRU محترمة
    ready(win, {f"/x{i}.jpg": _Sig(True) for i in range(6)})
    check("سعة الكاش محترمة",
          len(win._visual_sig_lru) <= win._visual_sig_capacity,
          f"len={len(win._visual_sig_lru)}")


# ----------------------------------------------------------------------
# 4) التسخين المسبق
# ----------------------------------------------------------------------
def test_warm_hooks() -> None:
    print("\n[4] التسخين المسبق بعد الدفعة وبعد الربط")
    win = find_class("MainWindow")
    if win is None:
        check("MainWindow موجود", False)
        return
    warm = find_method(win, "_warm_visual_signatures")
    check("_warm_visual_signatures موجودة", warm is not None)
    if warm is not None:
        check("التسخين يجدول ولا يبني",
              "_queue_visual_signatures" in calls_in(warm)
              and "build_signature" not in calls_in(warm))
    for hook in ("_on_batch_completed", "_on_manual_completed"):
        method = find_method(win, hook)
        if method is None:
            check(f"{hook} موجودة", False)
            continue
        src = ast.get_source_segment(SOURCE, method) or ""
        check(f"{hook} تستدعي التسخين",
              "_warm_visual_signatures" in src)

    shutdown = find_method(win, "_shutdown_workers")
    if shutdown is not None:
        src = ast.get_source_segment(SOURCE, shutdown) or ""
        check("الإغلاق يوقف مؤقّت التسخين",
              "_visual_warm_timer" in src)


# ----------------------------------------------------------------------
# 5) دورة حياة العامل — لا عامل ثانٍ فوق عامل يعمل
# ----------------------------------------------------------------------
def test_worker_lifecycle_guard() -> None:
    print("\n[5] حراسة دورة حياة العامل")
    win = find_class("MainWindow")
    if win is None:
        check("MainWindow موجود", False)
        return
    flush = find_method(win, "_flush_visual_signature_queue")
    check("_flush_visual_signature_queue موجودة", flush is not None)
    if flush is None:
        return
    src = ast.get_source_segment(SOURCE, flush) or ""
    check("يفحص isRunning قبل إنشاء عامل جديد", "isRunning" in src)
    check("يتتبّع العامل لمنع جمعه أثناء العمل", "_track_worker" in src)
    check("يعيد الجدولة بدل إنشاء عامل ثانٍ",
          "_visual_warm_timer.start" in src)


def main() -> int:
    print("=== اختبار عدم تجمّد الواجهة ببناء البصمات البصرية ===")
    test_worker_shape()
    test_no_ui_thread_build()
    test_cache_and_queue()
    test_warm_hooks()
    test_worker_lifecycle_guard()
    print(f"\n===== {PASS} passed / {FAIL} failed =====")
    if FAIL == 0:
        print("ALL_VISUAL_SIG_ASYNC_TESTS_OK")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
