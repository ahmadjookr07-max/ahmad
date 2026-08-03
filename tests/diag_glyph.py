# -*- coding: utf-8 -*-
"""يتحقق من وضع الرموز: يُطبَّق عند الشدة وحدها ويعود النص حرفيًا.

يفحص أيضًا الذهاب والعودة عدة مرات (800→1920→800) للتأكد من عدم
تراكم أو فقد النصوص الأصلية.
"""
import sys
from pathlib import Path

ROOT = Path("/home/ubuntu/market-image-studio-v2")
for _p in (ROOT, ROOT / "src", ROOT / "windows_app"):
    sys.path.insert(0, str(_p))

from PySide6.QtWidgets import QApplication  # noqa: E402
from windows_app.native_app import (BatchItemResult, BatchRunResult,  # noqa: E402
                                    MainWindow)

NAMES = ["منظف ومعقم متعدد الاستخدامات برائحة الليمون عبوة اقتصادية",
         "عصير برتقال طبيعي معصور طازج بدون سكر مضاف لتر واحد",
         "بسكويت محشو بكريمة الشوكولاتة الفاخرة عبوة عائلية",
         "زيت زيتون بكر ممتاز معصور على البارد من مزارع مختارة",
         "حبوب إفطار كاملة القمح مدعمة بالفيتامينات والحديد"]

EXPECTED = {
    # 2.9.6 — أُزيل tap_link_button مع وضع «اربط بالنقر» بطلب المالك.
    "use_reference_button": "اعتماد مرجع",
    "suggest_group_button": "اقتراح قريب",
    "reference_group_link_button": "ربط بالمرجع",
    "link_same_item_button": "ضم للصنف الأعلى",
    "link_by_image_button": "ربط بصورة أخرى",
    "nutrition_button": "🍎 حقائق التغذية",
    "delete_output_button": "🗑 حذف الصورة",
    "jump_to_previews_button": "عرض الصورة",
}


def build_items():
    fx = ROOT / "windows_app" / "assets" / "app_icon.png"
    st = ["matched", "manual", "review", "error", "unmatched"]
    return [BatchItemResult(
        source_path=str(fx), source_name=f"PHOTO-{i:03d}.jpg", status=s,
        item_code=f"{10001100 + i}", product_name=n,
        barcode=f"628100612345{i}", explanation="قياس", review_path=str(fx))
        for i, (n, s) in enumerate(zip(NAMES, st), start=1)]


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.current_result = BatchRunResult(
        workspace="/tmp/w", database_path="", catalog_summary={},
        items=build_items(), elapsed_ms=0.0, delivery_zip="",
        report_json="", report_csv="")
    win.current_workspace = Path("/tmp/w")
    win.show()
    app.processEvents()
    win._populate_results()
    win._show_results_page()
    app.processEvents()

    fails = 0
    # ذهاب وعودة ثلاث مرات
    for cycle in range(1, 4):
        for w, h in [(800, 600), (1920, 1080), (1366, 768), (800, 600)]:
            win.resize(w, h)
            for _ in range(3):
                app.processEvents()
                win._refresh_ui_scale()
                app.processEvents()
            factor = win.ui_scale.factor
            compact = factor <= 0.70
            print(f"--- دورة {cycle}  {w}x{h}  factor={factor:.3f}"
                  f"  متوقع={'رموز' if compact else 'نصوص'}")
            for attr, full in EXPECTED.items():
                btn = getattr(win, attr, None)
                if btn is None:
                    print(f"  [FAIL] {attr} غير موجود")
                    fails += 1
                    continue
                txt = btn.text()
                tip = btn.toolTip()
                if compact:
                    # الرمز فقط، والتلميح يحمل الاسم الكامل
                    if txt == full:
                        print(f"  [FAIL] {attr} لم ينتقل للرمز: {txt!r}")
                        fails += 1
                    elif full not in tip:
                        print(f"  [FAIL] {attr} التلميح بلا الاسم الكامل")
                        fails += 1
                else:
                    if txt != full:
                        print(f"  [FAIL] {attr} النص لم يعد كاملًا: "
                              f"{txt!r} != {full!r}")
                        fails += 1
            if not compact:
                print("  [OK] كل النصوص كاملة")
            else:
                print("  [OK] كل الأزرار رموز مع تلميح كامل")
    print()
    print(f"failures={fails}")
    app.quit()


main()
