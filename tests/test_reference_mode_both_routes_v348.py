from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MIS_SKIP_LICENSE", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "windows_app"), str(ROOT / "src")]

from PySide6.QtWidgets import QApplication
from native_app import MainWindow
from engine_v2.catalog_index_v2 import CatalogIndex
from engine_v2 import integration_v2 as integration
from engine_v2.legacy_folder_v2 import plan_legacy_renames, scan_legacy_folder


def make_index() -> CatalogIndex:
    index = CatalogIndex()
    # أول صف ليس وحدة العبوة المفردة عمدًا؛ الحبة يجب أن تفوز في المسارين.
    index.rows = [
        {"code": "10000001", "name": "صنف اختبار", "unit": "كرتون", "size": "12", "barcode": "6280000000000"},
        {"code": "10000001", "name": "صنف اختبار", "unit": "حبه", "size": "1", "barcode": "6280000000000"},
    ]
    index._build_maps()
    return index


def run() -> None:
    app = QApplication.instance() or QApplication([])
    old_root = integration.NAMING_DATA_ROOT
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            index = make_index()
            window = MainWindow()
            window.v2_data_root = root
            window.v2_catalog_index = index
            integration.set_catalog_index(index)

            # اختيار الواجهة -> حفظ -> صور جديدة.
            window.reference_mode_combo.setCurrentIndex(1)
            app.processEvents()
            output = root / "new-output"
            output.mkdir()
            names = integration.build_output_stems(output, "10000001", unit="حبه")
            assert names == ["6280000000000_حبه"], names

            # نفس الاختيار وملف الإعداد نفسه -> مجلد منجز سابق.
            legacy = root / "legacy"
            legacy.mkdir()
            (legacy / "10000001_حبه.webp").write_bytes(b"image")
            groups, bad = scan_legacy_folder(legacy, index=index)
            plan = plan_legacy_renames(groups, index=index, unparsed=bad)
            assert not bad and plan.rows[0].new_stem == "6280000000000_حبه", plan.rows

            # الرجوع إلى رقم الصنف من نفس القائمة ينعكس على المسارين فورًا.
            window.reference_mode_combo.setCurrentIndex(0)
            app.processEvents()
            names = integration.build_output_stems(output, "10000001", unit="حبه")
            assert names == ["10000001_حبه"], names
            plan = plan_legacy_renames(groups, index=index, unparsed=bad)
            assert plan.rows[0].new_stem == "10000001_حبه", plan.rows
            window.close()
        print("OK: one UI reference option drives new and legacy image naming")
    finally:
        integration.NAMING_DATA_ROOT = old_root
        integration.set_catalog_index(None)


if __name__ == "__main__":
    run()
