from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "windows_app"), str(ROOT / "src")]

from integrity_patch import match_item_position


@dataclass
class Item:
    source_name: str
    source_path: str = ""
    output_path: str = ""
    review_path: str = ""


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ✓ {message}")


def run() -> None:
    items = [
        Item("front.jpg", "/raw/front.jpg", "/out/6287021750464_حبه.webp"),
        Item("back.jpg", "/raw/back.jpg", "/out/6287021750464_حبه-1.webp"),
        Item("side.jpg", "/raw/side.jpg", "/out/6287021750464_حبه-2.webp"),
        Item("label.jpg", "/raw/label.jpg", "/out/6287021750464_حبه-3.webp"),
    ]
    check(match_item_position(items, "back.jpg") == 1,
          "المطابقة التامة تعيد الصورة المطلوبة")
    check(match_item_position(items, "6287021750464_حبه-2.webp") == 2,
          "مطابقة مسار الإخراج المتفردة تعيد الصورة المطابقة")
    # الأساس المشترك للصور الأربع ليس هوية. اختيار أول صف هنا كان يربط
    # أو يعدل صورة شقيقة ثم تظهر معاينات مختلطة في الواجهة.
    check(match_item_position(items, "6287021750464_حبه-9.webp") is None,
          "التسلسل غير الموجود والقاعدة المشتركة لا يختاران صورة عشوائية")

    same_name = [
        Item("barcode.jpg", "/raw/front/barcode.jpg", "/out/a.webp"),
        Item("barcode.jpg", "/raw/back/barcode.jpg", "/out/b.webp"),
    ]
    check(match_item_position(same_name, "barcode.jpg") is None,
          "الاسم المكرر وحده غامض ولا يختار أول صورة")
    print("OK: ambiguous sibling images are never cross-linked")


if __name__ == "__main__":
    run()
