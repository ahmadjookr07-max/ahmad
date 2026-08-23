from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "windows_app")]

from engine_v2.catalog_index_v2 import CatalogIndex
from engine_v2 import integration_v2 as integ
from engine_v2.naming_v2 import NamingSettings, REFERENCE_BARCODE, save_settings
from engine_v2.legacy_folder_v2 import (plan_legacy_renames, scan_legacy_folder,
                                        write_legacy_barcode_review)


def build_index() -> CatalogIndex:
    index = CatalogIndex()
    index.rows = [
        # مرجع مورد نصي يجب ألا يظهر أبدًا كاسم باركود.
        {"code": "10007712", "unit": "كرتون", "size": "20", "barcode": "3P-DT-10"},
        {"code": "10007712", "unit": "شدة", "size": "1", "barcode": "6281187040285"},
        # عدة باركودات صحيحة لنفس الصنف والوحدة: لا اختيار عشوائي.
        {"code": "10002234", "unit": "حبه", "size": "1", "barcode": "6287039470071"},
        {"code": "10002234", "unit": "حبه", "size": "1", "barcode": "6287039470095"},
        {"code": "10002234", "unit": "باكت", "size": "2", "barcode": "6287039480353"},
    ]
    index._build_maps()
    return index


def run() -> None:
    index = build_index()
    assert index.resolve_retail_barcode("10007712", unit="شدة") == {
        "barcode": "6281187040285", "unit": "شدة",
        "status": "excel_single_candidate",
        "candidates": [{"code": "10007712", "unit": "شدة", "size": "1", "barcode": "6281187040285"}],
    }
    ambiguous = index.resolve_retail_barcode("10002234", unit="حبه")
    assert ambiguous["barcode"] == "" and ambiguous["status"] == "ambiguous", ambiguous
    observed = index.resolve_retail_barcode("10002234", observed="6287039470095")
    assert observed["barcode"] == "6287039470095" and observed["unit"] == "حبه", observed

    old_root = integ.NAMING_DATA_ROOT
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            save_settings(root, NamingSettings(reference_mode=REFERENCE_BARCODE))
            integ.set_naming_data_root(root)
            integ.set_catalog_index(index)
            # الصور الجديدة: يستخدم الباركود الحتمي ولا يقبل المرجع النصي.
            assert integ._barcode_from_catalog("10007712", unit="شدة") == "6281187040285"
            assert integ._barcode_from_catalog("10002234", unit="حبه") == ""
            # المجلد المنجز: يغير الحتمي فقط ويترك الملتبس كما هو.
            folder = root / "legacy"
            folder.mkdir()
            fixed = folder / "10007712_حبه.webp"
            ambiguous_file = folder / "10002234_حبه.webp"
            fixed.write_bytes(b"image")
            ambiguous_file.write_bytes(b"image")
            groups, bad = scan_legacy_folder(folder, index=index)
            plan = plan_legacy_renames(groups, index=index, unparsed=bad)
            rows = {row.item: row for row in plan.rows}
            assert rows["10007712"].new_stem == "6281187040285_شدة"
            assert rows["10002234"].new_stem == "10002234_حبه"
            assert "10002234" in plan.barcode_ambiguous
            assert "عدة باركودات" in rows["10002234"].note
            review = write_legacy_barcode_review(plan, index, folder)
            assert review is not None and review.name == "barcode_review_multiple_candidates.csv"
            review_text = review.read_text(encoding="utf-8-sig")
            assert "10002234" in review_text
            assert "6287039470071" in review_text and "6287039470095" in review_text
            assert "10002234_حبه.webp" in review_text

            # مخرج قديم خاطئ باسم مرجع نصي يُعاد إلى رقم الصنف ثم يُصحح.
            old_wrong = root / "legacy-old-wrong"
            old_wrong.mkdir()
            (old_wrong / "3P-DT-10_شدة.webp").write_bytes(b"image")
            old_groups, old_bad = scan_legacy_folder(old_wrong, index=index)
            assert set(old_groups) == {"10007712"} and not old_bad
            old_plan = plan_legacy_renames(old_groups, index=index, unparsed=old_bad)
            assert old_plan.rows[0].new_stem == "6281187040285_شدة"
    finally:
        integ.NAMING_DATA_ROOT = old_root
        integ.set_catalog_index(None)
    print("OK: barcode decisions reject supplier references and never guess ambiguous values")


if __name__ == "__main__":
    run()
