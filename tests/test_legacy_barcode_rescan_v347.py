from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine_v2.catalog_index_v2 import CatalogIndex
from engine_v2.legacy_folder_v2 import scan_legacy_folder


def make_index() -> CatalogIndex:
    index = CatalogIndex()
    index.rows = [
        {"code": "10001", "name": "أ", "unit": "حبه", "size": "1", "barcode": "006-090"},
        {"code": "10002", "name": "ب", "unit": "حبه", "size": "1", "barcode": "3P-DT-10"},
        {"code": "10003", "name": "ج", "unit": "حبه", "size": "1", "barcode": "HWL640"},
        {"code": "10004", "name": "د", "unit": "حبه", "size": "1", "barcode": "6287021750464"},
    ]
    index._build_maps()
    return index


def sequences(group) -> list[int]:
    return [image.seq for image in group.images]


def run() -> None:
    index = make_index()
    with tempfile.TemporaryDirectory() as td:
        folder = Path(td)
        for name in (
            "006-090.webp", "006-090-1.webp",
            "3P-DT-10.webp", "3P-DT-10-1.webp",
            "HWL640_حبه.webp", "6287021750464_حبه.webp", "6287021750464_حبه-1.webp",
            "غير_معروف.webp",
        ):
            (folder / name).write_bytes(b"image")
        groups, unparsed = scan_legacy_folder(folder, index=index)
        assert set(groups) == {"10001", "10002", "10003", "10004"}, groups
        assert [path.name for path in unparsed] == ["غير_معروف.webp"], unparsed
        assert sequences(groups["10001"]) == [0, 1]
        # المطابقة الكاملة لـ 3P-DT-10 لها أولوية على فصل -10 كتسلسل.
        assert sequences(groups["10002"]) == [0, 1]
        assert sequences(groups["10003"]) == [0]
        assert sequences(groups["10004"]) == [0, 1]
        assert [image.unit for image in groups["10004"].images] == ["حبه", "حبه"]
    print("OK: text and hyphenated Excel barcodes rescan to their item codes")


if __name__ == "__main__":
    run()
