from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MIS_SKIP_LICENSE", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "windows_app"), str(ROOT / "src")]

from native_app import MainWindow, _manual_source_key


@dataclass
class Item:
    source_name: str
    source_path: str
    barcode: str
    item_code: str = "10003933"


@dataclass
class Result:
    items: list[Item]


class WindowStub:
    _result_item_for_identity = MainWindow._result_item_for_identity

    def __init__(self, items: list[Item]) -> None:
        self.current_result = Result(items)
        self._result_items_by_name = {
            _manual_source_key(item): item for item in items
        }


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ✓ {message}")


def run() -> None:
    first = Item("PHOTO-01.jpg", "/raw/front/PHOTO-01.jpg", "4823077615009")
    second = Item("PHOTO-01.jpg", "/raw/back/PHOTO-01.jpg", "4823077615009")
    window = WindowStub([first, second])
    first_key = _manual_source_key(first)
    second_key = _manual_source_key(second)

    check(first_key != second_key,
          "هوية صف الواجهة تعتمد المسار لا الاسم المتكرر")
    check(len(window._result_items_by_name) == 2,
          "صفان بباركود واحد يظلان ظاهرين في خريطة الواجهة")
    check(window._result_item_for_identity(first_key) is first,
          "اختيار الصف الأول يعيد صورته الصحيحة")
    check(window._result_item_for_identity(second_key) is second,
          "اختيار الصف الثاني يعيد صورته الصحيحة")
    check(window._result_item_for_identity("PHOTO-01.jpg") is None,
          "الاسم المجرد المكرر لا يختار صورة عشوائية")
    print("OK: UI identity does not collapse repeated-barcode images")


if __name__ == "__main__":
    run()
