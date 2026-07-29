"""تشخيص: أي عناصر شريط الربط تتداخل مستطيلاتها — محاكاة دقيقة لمسار الاختبار الدخاني."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QRect  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from windows_app import native_app  # noqa: E402
from windows_app.native_app import BatchItemResult, BatchRunResult, MainWindow  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
fixture_path = ROOT / "windows_app" / "assets" / "app_icon.png"
window = MainWindow()
window.resize(1180, 760)
for index in range(1, 83):
    window.image_list.addItem(f"{index:02d} — PHOTO-2026-07-14-19-{index:02d}.jpg")
window.show()
app.processEvents()

result_items = [
    BatchItemResult(
        source_path=str(fixture_path),
        source_name=f"PHOTO-{i:03d}.jpg",
        status="review",
        item_code=f"{100000 + i}",
        product_name=f"منظف ومعقم متعدد الاستخدامات برائحة الليمون — عبوة اقتصادية رقم {i}",
        barcode=f"6281000{i:06d}",
        explanation="حالة غير مؤكدة وتحتاج مراجعة",
        review_path=str(fixture_path),
    )
    for i in range(1, 83)
]
window.current_result = BatchRunResult(
    workspace="/tmp/diag-ws",
    database_path="",
    catalog_summary={},
    items=result_items,
    elapsed_ms=0.0,
    delivery_zip="",
    report_json="",
    report_csv="",
)
window.current_workspace = Path(window.current_result.workspace)
window._populate_results()
window._show_results_page()
app.processEvents()
window._select_last_result()
window._render_selected_preview()
window.preview_tabs.setCurrentWidget(window.output_preview)
app.processEvents()
window._set_manual_panel_expanded(False)
window._select_last_result()
window._render_selected_preview()
app.processEvents()

controls = {
    "manual_item_edit": window.manual_item_edit,
    "manual_link_button": window.manual_link_button,
    "use_reference_button": window.use_reference_button,
    "suggest_group_button": window.suggest_group_button,
    "reference_group_link_button": window.reference_group_link_button,
    "jump_to_previews_button": window.jump_to_previews_button,
    "manual_reference_badge": window.manual_reference_badge,
}
rects = {
    name: QRect(c.mapTo(window.manual_group, QPoint(0, 0)), c.size())
    for name, c in controls.items()
}
for name, r in rects.items():
    print(f"{name}: x={r.x()} y={r.y()} w={r.width()} h={r.height()}")
names = list(rects)
overlap = False
for i, a in enumerate(names):
    for b in names[i + 1:]:
        if rects[a].intersects(rects[b]):
            print(f"INTERSECT: {a} <-> {b}")
            overlap = True
contained = all(window.manual_group.rect().contains(r) for r in rects.values())
print("group:", window.manual_group.rect(), "height:", window.manual_group.height())
print("accessible:", contained, "separated:", not overlap)
window.grab().save("/tmp/diag_link_bar.png", "PNG")
window.close()
