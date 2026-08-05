#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبار التحميل التدريجي لجدول الأصناف — 2.9.11.

الشكوى: «الجدول يجمد التطبيق مع الدفعات الكبيرة ولا مؤشر تقدم».
هذا الاختبار يتحقق من:
  1. دفعة صغيرة (< الحد) تُعبّأ كاملة فورًا بلا مؤقت ولا مؤشر.
  2. دفعة كبيرة تظهر منها الدفعة الأولى فورًا ويُختار أول صف.
  3. مؤشر التقدم يظهر ويتقدم ثم يختفي عند الاكتمال.
  4. كل الصفوف تكتمل في النهاية ولا يضيع صنف واحد.
  5. لا صفوف مثقوبة (كل صف مبني له 3 خلايا).
  6. استدعاء تعبئة جديدة أثناء الجريان لا يخلط الدفعتين.
  7. الإغلاق أثناء الجريان لا يرمي استثناءً.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows_app"))
sys.path.insert(0, str(ROOT / "src"))

PASS = 0
FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS {label}" + (f" — {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL {label}" + (f" — {detail}" if detail else ""))
    return bool(ok)


from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import native_app  # noqa: E402


@dataclass
class FakeItem:
    source_name: str
    item_code: str = ""
    product_name: str = ""
    barcode: str = ""
    status: str = "matched"
    explanation: str = ""
    final_path: Path | None = None
    source_path: Path | None = None
    output_path: str = ""
    review_path: str = ""
    confidence: float = 0.0
    unit: str = ""


@dataclass
class FakeResult:
    items: list = field(default_factory=list)

    @property
    def summary(self) -> dict:
        return {
            "total": len(self.items),
            "matched": sum(1 for i in self.items if i.status == "matched"),
            "review": sum(1 for i in self.items if i.status == "review"),
            "errors": sum(1 for i in self.items if i.status == "error"),
        }


def make_items(n: int) -> list:
    out = []
    for i in range(n):
        out.append(
            FakeItem(
                source_name=f"img_{i:05d}.jpg",
                item_code=f"1001{i:04d}",
                product_name=f"صنف تجريبي رقم {i}",
                barcode=f"628000{i:06d}",
                status=("review" if i % 7 == 0 else "matched"),
                explanation="ربط بالباركود",
            )
        )
    return out


def new_window():
    win = native_app.MainWindow()
    win.resize(1366, 768)
    win.show()          # لازم ليعمل isVisible() على الأبناء
    # المصغرات تقرأ ملفات غير موجودة — نعطّلها لتركيز الاختبار على التعبئة
    win._start_lazy_thumbnails = lambda: None  # type: ignore[assignment]
    return win


def freeze(win) -> None:
    """يوقف نبض المؤقت ليكون القياس حتميًا.

    `setInterval(0)` يجعل المؤقت ينبض عدة مرات داخل نداء `processEvents`
    الواحد — وهو المطلوب في الإنتاج (أسرع ما يمكن دون تجميد)
    لكنه يمنع قياس حجم الدفعة بدقة، فنوقفه وننبض يدويًا.
    """
    timer = getattr(win, "_fill_timer", None)
    if timer is not None:
        timer.stop()


print("[1] دفعة صغيرة: تعبئة فورية كاملة بلا مؤشر")
win = new_window()
small = make_items(40)
win.current_result = FakeResult(small)
win._populate_results()
app.processEvents()
check("كل الصفوف عُبّئت فورًا", win.results_table.rowCount() == 40,
      str(win.results_table.rowCount()))
check("لا مؤقت تعبئة معلّق", getattr(win, "_fill_timer", None) is None)
check("مؤشر التقدم مخفي",
      not win.table_load_progress.isVisibleTo(win.table_load_progress.parentWidget()))
check("النص ليس «جارٍ التحميل»", "جارٍ التحميل" not in win.table_position_label.text(),
      win.table_position_label.text())
check("صف أول محدد", win.results_table.currentRow() == 0,
      str(win.results_table.currentRow()))
win.close()

print("\n[2] دفعة كبيرة: الدفعة الأولى فورًا ثم تقدم")
win = new_window()
big = make_items(1000)
win.current_result = FakeResult(big)
win._populate_results()
freeze(win)          # قبل أي processEvents لئلا يسبقنا المؤقت

first = win._TABLE_FIRST_CHUNK
check("الدفعة الأولى ظهرت فورًا", win.results_table.rowCount() == first,
      str(win.results_table.rowCount()))
check("مؤقت التعبئة موجود للبقية", getattr(win, "_fill_timer", None) is not None)
check("المتبقي محفوظ للدفعات", len(getattr(win, "_fill_pending", [])) == 1000 - first,
      str(len(getattr(win, "_fill_pending", []))))
# ملاحظة: صفحة «المراجعة» داخل QStackedWidget؛ ما دامت غير الصفحة
# النشطة يرجع isVisible() لكل أبنائها False. المعيار الصحيح
# هو isVisibleTo(الأب): أي «لو فُتحت الصفحة أأظهر؟»
check("مؤشر التقدم مُفعّل للعرض",
      win.table_load_progress.isVisibleTo(win.table_load_progress.parentWidget()))
check("مدى المؤشر = الإجمالي", win.table_load_progress.maximum() == 1000,
      str(win.table_load_progress.maximum()))
check("قيمة المؤشر = الدفعة الأولى", win.table_load_progress.value() == first,
      str(win.table_load_progress.value()))
check("نص التقدم عربي وواضح",
      win.table_position_label.text() == f"جارٍ التحميل… {first} من 1000",
      win.table_position_label.text())
check("أول صف محدد قبل اكتمال التحميل", win.results_table.currentRow() == 0,
      str(win.results_table.currentRow()))
check("عمل المستخدم ممكن فورًا: خلايا الصف الأول مبنية",
      all(win.results_table.item(0, c) is not None for c in range(3)))

print("\n[3] التقدم يزحف مع كل نبضة")
before = win.results_table.rowCount()
win._populate_next_chunk()
freeze(win)
after = win.results_table.rowCount()
check("عدد الصفوف زاد بعد نبضة", after > before, f"{before} -> {after}")
check("قيمة المؤشر زادت", win.table_load_progress.value() == after, str(win.table_load_progress.value()))
check("حجم الدفعة = _TABLE_CHUNK", after - before == win._TABLE_CHUNK,
      str(after - before))

print("\n[4] الاكتمال: كل الأصناف موجودة والمؤشر يختفي")
guard = 0
while getattr(win, "_fill_timer", None) is not None and guard < 500:
    win._populate_next_chunk()
    freeze(win)
    guard += 1
app.processEvents()
check("انتهت التعبئة دون حلقة لا نهائية", guard < 500, f"نبضات={guard}")
check("كل الـ1000 صف موجودة", win.results_table.rowCount() == 1000,
      str(win.results_table.rowCount()))
check("مؤشر التقدم اختفى",
      not win.table_load_progress.isVisibleTo(win.table_load_progress.parentWidget()))
check("نص العدّاد عاد طبيعيًا", "جارٍ التحميل" not in win.table_position_label.text(),
      win.table_position_label.text())

holes = [r for r in range(win.results_table.rowCount())
         if any(win.results_table.item(r, c) is None for c in range(3))]
check("لا صف مثقوب (كل صف 3 خلايا)", not holes, f"عدد الثقوب={len(holes)}")

names = {str(win.results_table.item(r, 0).data(native_app.Qt.UserRole))
         for r in range(win.results_table.rowCount())}
check("لا صنف ضائع ولا مكرر", names == {i.source_name for i in big},
      f"مبني={len(names)} أصل={len(big)}")

print("\n[5] الترتيب محفوظ (الصف n = الصنف n)")
order_ok = all(
    str(win.results_table.item(r, 0).data(native_app.Qt.UserRole)) == big[r].source_name
    for r in range(0, 1000, 37)
)
check("ترتيب الأصناف كما ورد من المحرك", order_ok)

print("\n[6] تعبئة جديدة أثناء الجريان لا تخلط الدفعتين")
win2 = new_window()
win2.current_result = FakeResult(make_items(800))
win2._populate_results()
freeze(win2)
win2._populate_next_chunk()
freeze(win2)
mid_rows = win2.results_table.rowCount()
check("الجريان الأول بدأ فعلًا", 0 < mid_rows < 800, str(mid_rows))

second = make_items(50)
for it in second:
    it.source_name = "NEW_" + it.source_name
win2.current_result = FakeResult(second)
win2._populate_results()
app.processEvents()
check("الجدول أُعيد ضبطه للدفعة الجديدة فقط",
      win2.results_table.rowCount() == 50, str(win2.results_table.rowCount()))
check("مؤقت الجريان القديم أُوقف", getattr(win2, "_fill_timer", None) is None)
check("المؤشر مخفي بعد الاستبدال",
      not win2.table_load_progress.isVisibleTo(win2.table_load_progress.parentWidget()))
new_names = {str(win2.results_table.item(r, 0).data(native_app.Qt.UserRole))
             for r in range(win2.results_table.rowCount())}
check("لا بقايا من الدفعة القديمة",
      all(n.startswith("NEW_") for n in new_names))

print("\n[7] الإغلاق أثناء الجريان آمن")
win3 = new_window()
win3.current_result = FakeResult(make_items(600))
win3._populate_results()
app.processEvents()
crash = ""
try:
    win3.close()
    for _ in range(5):
        app.processEvents()
except Exception as exc:  # noqa: BLE001
    crash = f"{type(exc).__name__}: {exc}"
check("الإغلاق أثناء التعبئة لا يرمي استثناء", not crash, crash)

print("\n[8] الدوال والثوابت موصولة")
src = (ROOT / "windows_app" / "native_app.py").read_text(encoding="utf-8")
check("_fill_timer يُوقف عند إنهاء الجلسة", '"_fill_timer"' in src)
check("مؤشر التقدم مضاف للتخطيط", "list_layout.addWidget(self.table_load_progress)" in src)
check("للمؤشر تلميح عربي", "تقدم تحميل الأصناف" in src)
check("_build_result_row_cells مستخدمة", src.count("_build_result_row_cells") >= 2)
check("حد التدريج معقول",
      100 <= native_app.MainWindow._TABLE_PROGRESSIVE_MIN <= 400,
      str(native_app.MainWindow._TABLE_PROGRESSIVE_MIN))
check("الدفعة الأولى تملأ شاشة", native_app.MainWindow._TABLE_FIRST_CHUNK >= 30,
      str(native_app.MainWindow._TABLE_FIRST_CHUNK))

print(f"\n===== {PASS} passed / {FAIL} failed =====")
if FAIL == 0:
    print("ALL_PROGRESSIVE_TABLE_V2911_TESTS_OK")
sys.exit(1 if FAIL else 0)
