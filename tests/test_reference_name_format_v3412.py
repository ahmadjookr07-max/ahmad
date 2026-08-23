from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine_v2.naming_v2 import SCHEME_DASH, parse_name, plan_group_names


def assert_format(reference: str) -> None:
    expected = [
        f"{reference}_حبه",
        f"{reference}_حبه-1",
        f"{reference}_حبه-2",
    ]
    actual = plan_group_names(reference, 3, "حبه", scheme=SCHEME_DASH)
    assert actual == expected, actual
    for rank, stem in enumerate(actual, start=1):
        parsed = parse_name(stem)
        assert parsed is not None and parsed.item == reference, stem
        assert parsed.unit == "حبه" and parsed.seq == rank, (stem, parsed)


def run() -> None:
    # لا يتغير التنسيق عند تبديل المرجع؛ يتغير المرجع وحده.
    assert_format("10002037")
    assert_format("6281044993549")
    print("OK: item-code and barcode modes preserve reference_unit then -1/-2")


if __name__ == "__main__":
    run()
