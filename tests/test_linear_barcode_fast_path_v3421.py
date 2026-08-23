from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "windows_app"), str(ROOT / "src")]

import barcode_linear_v32
from linear_barcode_fast_path import install_linear_barcode_fast_path


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ✓ {message}")


def run() -> None:
    calls: list[str] = []

    def lookup(value, _index):
        calls.append(value)
        if value == "6281234567890":
            return SimpleNamespace(item_code="10000001"), False
        if value == "6280000000000":
            return SimpleNamespace(item_code="duplicate"), True
        return None, False

    pipeline = SimpleNamespace(_lookup_barcode=lookup)
    original_reader = barcode_linear_v32.read_linear_barcodes
    try:
        barcode_linear_v32.read_linear_barcodes = lambda _path: (
            "6280000000000", "6281234567890")
        check(install_linear_barcode_fast_path(pipeline), "تُركّب رقعة الباركود الخطي")
        record, source, confidence, candidates = pipeline._match_source("front.jpg", object())
        check(record.item_code == "10000001", "يتخطى المرشح الملتبس ويقبل باركودًا خطيًا مؤكدًا")
        check(source == "catalog_barcode" and confidence == 1.0,
              "المطابقة المؤكدة تظل دليل باركود فقط")
        check(candidates == ("6280000000000", "6281234567890"), "يحفظ المرشحات للشفافية")
        check(calls == ["6280000000000", "6281234567890"], "لا يستدعي OCR أو مطابقة اسم الملف")

        barcode_linear_v32.read_linear_barcodes = lambda _path: ()
        no_code_pipeline = SimpleNamespace(_lookup_barcode=lookup)
        check(install_linear_barcode_fast_path(no_code_pipeline),
              "يمكن تركيب المسار سريعًا في تشغيل جديد")
        record, source, confidence, candidates = no_code_pipeline._match_source("no-code.jpg", object())
        check(record is None and source == "" and confidence == 0.0 and not candidates,
              "الصورة بلا باركود تبقى للمراجعة بلا تخمين")
    finally:
        barcode_linear_v32.read_linear_barcodes = original_reader

    print("OK: fast path is linear-barcode-only and review-safe")


if __name__ == "__main__":
    run()
