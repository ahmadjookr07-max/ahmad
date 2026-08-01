# -*- coding: utf-8 -*-
"""قياس القص الفعلي لكل زر: هل يخرج أي زر عن حدود حاويته المرئية؟

الفحص السابق قاس ارتفاع الحاوية مقابل حاجتها، فأخفى القص الأفقي
وقص الأزرار الخارجة عن viewport منطقة التمرير. هذا يقيس كل زر
مقابل المستطيل المرئي فعلًا.
"""
import sys
from pathlib import Path

ROOT = Path("/home/ubuntu/market-image-studio-v2")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "windows_app"))

from PySide6.QtWidgets import QApplication, QAbstractButton  # noqa: E402
from windows_app.native_app import (BatchItemResult, BatchRunResult,  # noqa: E402
                                    MainWindow)

SIZES = [(800, 600), (1024, 700), (1366, 768), (1920, 1080)]
NAMES = ["منظف ومعقم متعدد الاستخدامات برائحة الليمون عبوة اقتصادية",
         "عصير برتقال طبيعي معصور طازج بدون سكر مضاف لتر واحد",
         "بسكويت محشو بكريمة الشوكولاتة الفاخرة عبوة عائلية",
         "زيت زيتون بكر ممتاز معصور على البارد من مزارع مختارة",
         "حبوب إفطار كاملة القمح مدعمة بالفيتامينات والحديد"]


def build_items():
    fx = ROOT / "windows_app" / "assets" / "app_icon.png"
    st = ["matched", "manual", "review", "error", "unmatched"]
    return [BatchItemResult(
        source_path=str(fx), source_name=f"PHOTO-{i:03d}.jpg", status=s,
        item_code=f"{10001100 + i}", product_name=n,
        barcode=f"628100612345{i}", explanation="قياس", review_path=str(fx))
        for i, (n, s) in enumerate(zip(NAMES, st), start=1)]


def visible_rect(w):
    """المستطيل المرئي فعلًا للعنصر في إحداثيات النافذة."""
    from PySide6.QtCore import QRect, QPoint
    win = w.window()
    r = QRect(w.mapTo(win, QPoint(0, 0)), w.size())
    p = w.parentWidget()
    child = w
    while p is not None and p is not win:
        # منطقة التمرير: المرئي هو viewport
        clip = p
        pr = QRect(clip.mapTo(win, QPoint(0, 0)), clip.size())
        r = r.intersected(pr)
        child = p
        p = p.parentWidget()
    return r


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.current_result = BatchRunResult(
        workspace="/tmp/diag-ws", database_path="", catalog_summary={},
        items=build_items(), elapsed_ms=0.0, delivery_zip="",
        report_json="", report_csv="")
    win.current_workspace = Path("/tmp/diag-ws")
    win.show()
    app.processEvents()
    win._populate_results()
    win._show_results_page()
    app.processEvents()

    fails = 0
    for w, h in SIZES:
        win.resize(w, h)
        for _ in range(3):
            app.processEvents()
            win._refresh_ui_scale()
            app.processEvents()
        print("=" * 66)
        print(f"{w}x{h}")
        print("=" * 66)
        host = getattr(win, "manual_group", None) or getattr(
            win, "manual_scroll", None)
        if host is None:
            print("  لا توجد لوحة ربط")
            continue
        clipped = []
        for b in host.findChildren(QAbstractButton):
            if not b.isVisible():
                continue
            vr = visible_rect(b)
            full = b.width() * b.height()
            seen = max(vr.width(), 0) * max(vr.height(), 0)
            if full <= 0:
                continue
            ratio = seen / full
            if ratio < 0.98:
                clipped.append((b.text()[:28] or b.objectName(),
                                round(ratio * 100), b.width(), b.height(),
                                vr.width(), vr.height()))
        if clipped:
            fails += len(clipped)
            for t, pct, bw, bh, vw, vh in clipped:
                print(f"  [CLIP] {t!r} مرئي {pct}%  "
                      f"({bw}x{bh} → {vw}x{vh})")
        else:
            print("  [OK] لا زر مقصوص")
    print()
    print(f"failures={fails}")
    app.quit()


main()
