from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "windows_app"), str(ROOT / "src")]

from v2_ui import _resolve_session_position, _session_item_identity


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ✓ {message}")


def run() -> None:
    front = {
        "source_path": "/raw/front/PHOTO-01.jpg",
        "source_name": "PHOTO-01.jpg",
        "output_path": "/out/1001_حبه-1.webp",
        "match_source": "manual",
        "item_code": "1001",
        "barcode": "6280000000011",
    }
    barcode = {
        "source_path": "/raw/back/PHOTO-01.jpg",
        "source_name": "PHOTO-01.jpg",
        "output_path": "/out/1001_حبه.webp",
        "match_source": "barcode",
        "item_code": "1001",
        "barcode": "6280000000011",
    }
    # ترتيب العناصر يتغير كما يحدث بعد الفرز أو إعادة فتح الجلسة.
    reordered = [barcode, front]
    front_key = _session_item_identity(front)
    barcode_key = _session_item_identity(barcode)
    check(front_key != barcode_key,
          "صورتا الواجهة والباركود المتشابهتا الاسم تملكان مفتاحين مستقلين")
    chosen = _resolve_session_position(
        reordered, {"source_key": front_key, "source_name": front["source_name"], "row": 0})
    check(chosen == 1,
          "استعادة الجلسة تعود إلى صورة الواجهة المقصودة بعد تغير ترتيب الصفوف")
    chosen = _resolve_session_position(reordered, {"source_name": "PHOTO-01.jpg", "row": 1})
    check(chosen == 1,
          "جلسة قديمة ذات اسم مصدر ملتبس لا تختار صورة شقيقة بل تحتفظ بالصف المحفوظ")
    chosen = _resolve_session_position(reordered, {"source_key": barcode_key, "row": 1})
    check(chosen == 0,
          "المفتاح الكامل يستعيد صف الباركود عند اختياره صراحةً")
    print("OK: session position never switches a sibling image")


if __name__ == "__main__":
    run()
