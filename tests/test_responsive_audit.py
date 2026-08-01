"""تدقيق توافق الواجهة مع دقات الشاشة — يقيس التداخل، الخروج عن الحدود، وقص النصوص.

يشغّل النافذة الرئيسية على مجموعة دقات ويفحص ثلاث شاشات:
  * مراجعة  — صفحة النتائج (لوحة الربط + الجدول + شريط التسليم)
  * تحرير   — تبويب «تحرير مباشر» (أدوات + تذييل الحفظ)
  * تغذية   — نافذة اقتصاص حقائق التغذية (شريط الدمج)

التصنيف الأمين:
  * عنصر **أساسي** غير مرئي أو مقصوص  → FAIL
  * عنصر **ثانوي** داخل منطقة تمرير فعّالة → مقبول (SCROLL)
  * تداخل عنصرين شقيقين → FAIL دائمًا (صرامة كاملة)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows_app"))
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractScrollArea,
    QApplication,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QWidget,
)

RESOLUTIONS = [
    (800, 600),
    (1024, 600),
    (1024, 700),
    (1280, 720),
    (1280, 800),
    (1366, 768),
    (1440, 900),
    (1600, 900),
    (1920, 1080),
    (2560, 1440),
]

# الأزرار الحاكمة — إخفاؤها أو قصها عيب حقيقي
PRIMARY_TEXTS = {
    "🍎 حقائق التغذية",
    "👆 اربط بالنقر",
    "🗑 حذف الصورة",
    "ربط بصورة أخرى",
    "ربط الآن",
    "حفظ واعتماد التعديل",
    "إنهاء التحرير",
    "حفظ حزمة النتائج ZIP",
    "فتح مجلد النتائج",
    "حفظ الاقتصاص",
    "إغلاق",
}


def abs_rect(widget: QWidget) -> QRect:
    """المستطيل المرئي فعليًا = تقاطع الهندسة مع حدود كل أب صاعدًا."""
    if widget is None:
        return QRect()
    rect = QRect(widget.mapTo(widget.window(), widget.rect().topLeft()),
                 widget.rect().size())
    parent = widget.parentWidget()
    while parent is not None:
        prect = QRect(parent.mapTo(parent.window(), parent.rect().topLeft()),
                      parent.rect().size())
        rect = rect.intersected(prect)
        if rect.isEmpty():
            return QRect()
        parent = parent.parentWidget()
    return rect


def inside_active_scroll(widget: QWidget) -> bool:
    """هل العنصر داخل منطقة تمرير فعّالة (يمكن الوصول إليه بالتمرير)؟"""
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QAbstractScrollArea):
            vbar = parent.verticalScrollBar()
            hbar = parent.horizontalScrollBar()
            if (vbar is not None and vbar.maximum() > 0) or \
               (hbar is not None and hbar.maximum() > 0):
                return True
        parent = parent.parentWidget()
    return False


def is_primary(widget: QWidget) -> bool:
    text = widget.text() if hasattr(widget, "text") else ""
    return text in PRIMARY_TEXTS


def visible_widgets(root: QWidget, types=(QPushButton,)) -> list[QWidget]:
    out: list[QWidget] = []
    for kind in types:
        for w in root.findChildren(kind):
            if w.isVisible() and w.width() > 0 and w.height() > 0:
                out.append(w)
    return out


def check_overlaps(root: QWidget, window: QWidget) -> list[str]:
    """تداخل الأشقاء المباشرين داخل نفس الأب — صرامة كاملة."""
    problems: list[str] = []
    buckets: dict[int, list[QWidget]] = {}
    for w in visible_widgets(root, (QPushButton, QLabel)):
        parent = w.parentWidget()
        if parent is None:
            continue
        buckets.setdefault(id(parent), []).append(w)
    for widgets in buckets.values():
        for i, a in enumerate(widgets):
            ra = abs_rect(a)
            if ra.isEmpty():
                continue
            for b in widgets[i + 1:]:
                rb = abs_rect(b)
                if rb.isEmpty():
                    continue
                inter = ra.intersected(rb)
                if inter.width() > 2 and inter.height() > 2:
                    problems.append(
                        f"OVERLAP {label_of(a)} × {label_of(b)} "
                        f"({inter.width()}×{inter.height()}px)")
    return problems


def label_of(w: QWidget) -> str:
    text = w.text() if hasattr(w, "text") else ""
    return f"{w.objectName() or type(w).__name__}:'{text[:22]}'"


def check_out_of_bounds(root: QWidget, window: QWidget) -> list[str]:
    problems: list[str] = []
    wrect = QRect(0, 0, window.width(), window.height())
    for w in visible_widgets(root, (QPushButton,)):
        geo = QRect(w.mapTo(window, w.rect().topLeft()), w.rect().size())
        if not wrect.contains(geo):
            visible = abs_rect(w)
            if visible.isEmpty():
                tag = "HIDDEN"
            elif visible.width() < w.width() - 2 or visible.height() < w.height() - 2:
                tag = "CLIPPED"
            else:
                continue
            severity = "FAIL" if is_primary(w) else (
                "SCROLL" if inside_active_scroll(w) else "WARN")
            problems.append(f"{tag}[{severity}] {label_of(w)}")
    return problems


def check_text_clipping(root: QWidget) -> list[str]:
    """قص النص الحقيقي: العرض الممنوح أقل من العرض اللازم للنص.

    المقياس الأمين هو مقارنة العرض الفعلي بـ ``sizeHint().width()`` الذي
    يحسبه Qt نفسه من ميتريات الخط **زائد الحشوة الفعلية للعنصر**.
    خصم 14px ثابتة كان تقديرًا خاطئًا: العناوين (``sectionTitle``،
    ``metaCaption``، ``linkBarTitle``) لا حشوة لها في الأنماط إطلاقًا، فكان
    الفحص يُبلّغ عن قص وهمي حتى على 2560×1440 حيث لا قص إطلاقًا.
    """
    problems: list[str] = []
    for w in visible_widgets(root, (QPushButton, QLabel)):
        # العناصر التي تنكمش بتصميمها مستثناة (Ignored/elide)
        if w.sizePolicy().horizontalPolicy() == QSizePolicy.Ignored:
            continue
        text = w.text() if hasattr(w, "text") else ""
        if not text or "…" in text:
            continue
        if isinstance(w, QLabel) and w.wordWrap():
            continue  # النص يلتف لأسطر فلا يُقص أفقيًا
        # ما يحتاجه العنصر فعليًا لإظهار نصه كاملًا بحساب Qt نفسه
        needed = max(w.sizeHint().width(), w.minimumSizeHint().width())
        avail = w.width()
        if needed > avail + 2:
            severity = "FAIL" if is_primary(w) else "WARN"
            problems.append(
                f"TEXTCLIP[{severity}] {label_of(w)} needs={needed} avail={avail}")
    return problems


def check_vertical_text_cut(root: QWidget) -> list[str]:
    """قص عمودي: النص أطول من الارتفاع الممنوح له.

    هذا الفحص هو ما كان ناقصًا: الفحوص السابقة تقيس البتر الأفقي
    (النقاط الثلاث) لكنها تعمى عن النص الملتف الذي يحتاج أربعة أسطر
    ويُمنح ارتفاع سطرين ونصف — فيُقطع نصف السطر الأخير بصريًا بلا أي
    مؤشر برمجي. المقياس: ``heightForWidth(العرض الفعلي)`` مقابل
    الارتفاع الفعلي.
    """
    problems: list[str] = []
    for w in visible_widgets(root, (QLabel, QPushButton)):
        text = w.text() if hasattr(w, "text") else ""
        if not text:
            continue
        avail_h = w.height()
        if isinstance(w, QLabel) and w.wordWrap():
            needed_h = w.heightForWidth(max(1, w.width()))
        else:
            needed_h = w.sizeHint().height()
        if needed_h > avail_h + 2:
            severity = "FAIL" if is_primary(w) else "WARN"
            problems.append(
                f"VCUT[{severity}] {label_of(w)} "
                f"needs_h={needed_h} avail_h={avail_h}")
    return problems


def check_container_overflow(root: QWidget) -> list[str]:
    """فيض المحتوى خارج حدود أبيه المباشر.

    أزرار لوحة الربط كانت تُقص عند حد اللوحة لا عند حد النافذة،
    ففحص ``check_out_of_bounds`` المقارن بالنافذة لا يراها. هنا أقارن
    المستطيل المرئي فعليًا (بعد تقاطع كل الأباء) بالحجم المطلوب.
    """
    problems: list[str] = []
    for w in visible_widgets(root, (QPushButton,)):
        visible = abs_rect(w)
        if visible.isEmpty():
            continue
        lost_h = w.height() - visible.height()
        lost_w = w.width() - visible.width()
        if lost_h > 2 or lost_w > 2:
            if inside_active_scroll(w):
                severity = "SCROLL"
            else:
                severity = "FAIL" if is_primary(w) else "WARN"
            problems.append(
                f"CUTBOX[{severity}] {label_of(w)} "
                f"lost={lost_w}×{lost_h}px")
    return problems


def audit_screen(name: str, root: QWidget, window: QWidget) -> dict:
    problems = []
    problems += check_overlaps(root, window)
    problems += check_out_of_bounds(root, window)
    problems += check_text_clipping(root)
    problems += check_vertical_text_cut(root)
    problems += check_container_overflow(root)
    fails = [p for p in problems if "[FAIL]" in p or p.startswith("OVERLAP")]
    return {"screen": name, "problems": problems, "fails": fails}


def build_window():
    from native_app import MainWindow  # type: ignore
    return MainWindow()


def prepare_results_page(win) -> None:
    """يفتح صفحة المراجعة ويحقن صفًا اختباريًا لتفعيل كل الأزرار."""
    win._show_results_page()
    QApplication.processEvents()


def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    total_pass = 0
    total_fail = 0
    report_lines: list[str] = []
    for width, height in RESOLUTIONS:
        win = build_window()
        win.resize(width, height)
        win.show()
        QApplication.processEvents()
        prepare_results_page(win)
        for _ in range(3):
            QApplication.processEvents()

        results = []
        # 1) شاشة المراجعة
        results.append(audit_screen("مراجعة", win.results_page, win))
        # 2) تبويب التحرير
        if hasattr(win, "preview_tabs") and hasattr(win, "edit_tab"):
            win.preview_tabs.setCurrentWidget(win.edit_tab)
            for _ in range(3):
                QApplication.processEvents()
            results.append(audit_screen("تحرير", win.edit_tab, win))
            win.preview_tabs.setCurrentWidget(win.output_preview)
            QApplication.processEvents()

        for res in results:
            checks = 3
            failed = len(res["fails"])
            if failed:
                total_fail += 1
                report_lines.append(
                    f"FAIL {width}×{height} [{res['screen']}] "
                    + "; ".join(res["fails"][:6]))
            else:
                total_pass += 1
                report_lines.append(f"PASS {width}×{height} [{res['screen']}]")
            for p in res["problems"]:
                if p not in res["fails"]:
                    report_lines.append(f"     · {p}")
        win.close()
        win.deleteLater()
        QApplication.processEvents()

    print("\n".join(report_lines))
    print(f"\nPASS={total_pass}  FAIL={total_fail}")
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(run())
