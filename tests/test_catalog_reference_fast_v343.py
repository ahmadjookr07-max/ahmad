from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine_v2.catalog_index_v2 import CatalogIndex


def run() -> None:
    index = CatalogIndex()
    index.rows = [
        {"code": "10001", "name": "سكر البيت ناعم", "unit": "حبه", "size": "1", "barcode": "6287000000001"},
        {"code": "10002", "name": "شاي أحمر فاخر", "unit": "علبة", "size": "1", "barcode": "6287000000002"},
        {"code": "10003", "name": "اسم مكرر", "unit": "حبه", "size": "1", "barcode": "6287000000003"},
        {"code": "10004", "name": "اسم مكرر", "unit": "كرتون", "size": "12", "barcode": "6287000000004"},
    ]
    index._build_maps()
    assert index.resolve_reference("10001")["name"] == "سكر البيت ناعم"
    assert index.resolve_reference("6287000000002")["code"] == "10002"
    assert index.resolve_reference("سكر البيت ناعم")["code"] == "10001"
    assert index.resolve_reference("سكر البيت ناعم") is not None  # التطبيع العربي
    assert index.resolve_reference("اسم مكرر") is None
    assert index.resolve_reference("628700000000") is None  # لا تسامح باركود يدوي
    print("OK: exact Excel references resolve from maps while ambiguous names stay manual")


if __name__ == "__main__":
    run()
