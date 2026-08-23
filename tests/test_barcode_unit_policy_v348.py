from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine_v2.naming_v2 import (
    NamingSettings,
    REFERENCE_BARCODE,
    REFERENCE_ITEM_CODE,
    UNIT_POLICY_DEFAULT,
    UNIT_POLICY_JOIN_ALL,
    UNIT_POLICY_REPLICATE,
    plan_stems_for_policy,
)


def names(settings, *, chosen="حبه"):
    return plan_stems_for_policy(
        "10000001", ["كرتون", "حبه"], seq=1, total=2,
        settings=settings, chosen_unit=chosen, barcode="6280000000000")


def run() -> None:
    # الوحدة الافتراضية تأخذ وحدة العبوة=1 الممررة، لا أول صف عشوائي.
    settings = NamingSettings(reference_mode=REFERENCE_BARCODE,
                              unit_policy=UNIT_POLICY_DEFAULT)
    assert names(settings) == ["6280000000000_حبه"]
    assert plan_stems_for_policy("10000001", ["كرتون", "حبه"], 2, 2,
                                 settings, chosen_unit="حبه",
                                 barcode="6280000000000") == ["6280000000000_حبه-1"]

    # سياسات دمج/نسخ قديمة لا تتجاوز قاعدة الاسم النهائي المفرد.
    settings.unit_policy = UNIT_POLICY_JOIN_ALL
    assert names(settings) == ["6280000000000_حبه"]
    settings.unit_policy = UNIT_POLICY_REPLICATE
    assert names(settings) == ["6280000000000_حبه"]

    # رقم الصنف لم يتغير: نفس وحدة Excel والتسلسل المعتادان.
    settings = NamingSettings(reference_mode=REFERENCE_ITEM_CODE,
                              unit_policy=UNIT_POLICY_DEFAULT)
    assert names(settings) == ["10000001_حبه"]
    print("OK: barcode mode preserves Excel units and item-code mode remains intact")


if __name__ == "__main__":
    run()
