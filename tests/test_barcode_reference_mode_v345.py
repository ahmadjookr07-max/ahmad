from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "windows_app")]

from engine_v2.catalog_index_v2 import CatalogIndex
from engine_v2 import integration_v2 as integ
from engine_v2.naming_v2 import (NamingSettings, REFERENCE_BARCODE,
                                  save_settings)
from engine_v2.legacy_folder_v2 import (apply_legacy_plan,
                                        plan_legacy_renames,
                                        scan_legacy_folder)
from batch_naming_patch import apply_join_all_units


@dataclass
class Item:
    item_code: str
    output_path: str
    barcode: str = ""


@dataclass
class Result:
    items: list[Item]
    workspace: str


def _index() -> CatalogIndex:
    index = CatalogIndex()
    index.rows = [{"code": "10015986", "name": "سكر البيت ناعم",
                   "unit": "حبه", "size": "1",
                   "barcode": "6287021750464"}]
    index._build_maps()
    return index


def run() -> None:
    old_root = integ.NAMING_DATA_ROOT
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = root / "out"
            out.mkdir()
            settings = NamingSettings(reference_mode=REFERENCE_BARCODE)
            save_settings(root, settings)
            integ.set_naming_data_root(root)
            index = _index()
            integ.set_catalog_index(index)

            # مصدر الحقيقة: الباركود من Excel، الأولى بلا رقم ثم -1.
            assert settings.render("10015986", 1, "حبه", total=2,
                                   barcode="6287021750464") == "6287021750464"
            assert settings.render("10015986", 2, "حبه", total=2,
                                   barcode="6287021750464") == "6287021750464-1"

            old = out / "10015986_حبه.webp"
            old.write_bytes(b"image")
            result = Result([Item("10015986", str(old), "6287021750464")], str(root))
            apply_join_all_units(result)
            renamed = out / "6287021750464.webp"
            assert renamed.is_file() and not old.exists()
            assert result.items[0].output_path == str(renamed)

            # المجلد المنجز القديم يعاد ربطه من code في Excel ثم يسمى بالباركود.
            legacy = root / "legacy"
            legacy.mkdir()
            prior = legacy / "10015986_حبه.webp"
            prior.write_bytes(b"image")
            groups, unparsed = scan_legacy_folder(legacy, index=index)
            assert set(groups) == {"10015986"} and not unparsed
            plan = plan_legacy_renames(groups, index=index, unparsed=unparsed)
            assert plan.rows[0].new_stem == "6287021750464"
            applied = apply_legacy_plan(plan)
            assert not applied["errors"]
            final = legacy / "6287021750464.webp"
            assert final.is_file() and not prior.exists()
            # إعادة فتح الاسم الجديد تعيده إلى item code من Excel.
            again, bad = scan_legacy_folder(legacy, index=index)
            assert set(again) == {"10015986"} and not bad
        print("OK: barcode reference comes from Excel for batch and legacy folders")
    finally:
        integ.NAMING_DATA_ROOT = old_root
        integ.set_catalog_index(None)


if __name__ == "__main__":
    run()
