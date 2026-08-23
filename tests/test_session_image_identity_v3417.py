from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "windows_app"), str(ROOT / "src")]

from engine_v2.session_v2 import SessionStore, image_identity_key
from session_fidelity_patch import install_session_fidelity


@dataclass
class Item:
    source_path: str
    source_name: str
    barcode: str
    item_code: str
    output_path: str
    review_path: str = ""
    status: str = "manual"
    product_name: str = "منتج"
    confidence: float = 1.0
    explanation: str = "اختبار"
    match_source: str = "barcode"
    barcode_candidates: tuple = ()
    warnings: tuple = ()
    processing_ms: float = 0.0
    foreground_method: str = ""
    foreground_quality_score: float = 0.0
    foreground_quality_status: str = ""
    foreground_quality_metrics: dict | None = None


@dataclass
class Result:
    items: list[Item]


class Window:
    def __init__(self, store: SessionStore, result: Result) -> None:
        self.v2_session_store = store
        self.current_result = result

    def v2_save_session(self, name: str = "") -> str:
        return self.v2_session_store.state.session_id


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ✓ {message}")


def run() -> None:
    barcode = "4823077615009"
    front = "/raw/front/PHOTO-01.jpg"
    back = "/raw/back/PHOTO-01.jpg"
    check(image_identity_key(front, "PHOTO-01.jpg") !=
          image_identity_key(back, "PHOTO-01.jpg"),
          "مساران مختلفان يحملان الاسم والباركود نفسيهما لهما هويتان مستقلتان")
    check(barcode not in image_identity_key(front, "PHOTO-01.jpg"),
          "الباركود ليس جزءًا من مفتاح هوية الجلسة")

    with tempfile.TemporaryDirectory() as td:
        store = SessionStore(td)
        store.new_session("هوية الصور")
        items = [
            Item(front, "PHOTO-01.jpg", barcode, "10003933", "/out/a.webp"),
            Item(back, "PHOTO-01.jpg", barcode, "10003933", "/out/b.webp"),
        ]
        window = Window(store, Result(items))
        report = install_session_fidelity(window)
        check(report["save_wrapped"], "تركيب حفظ الجلسة بالحماية الجديدة")
        window.v2_save_session()
        saved = store.state.images
        first_key = image_identity_key(front, "PHOTO-01.jpg")
        second_key = image_identity_key(back, "PHOTO-01.jpg")
        check(len(saved) == 2, "تكرار الباركود لا يسقط أي صورة من الجلسة")
        check(saved[first_key]["output_path"] == "/out/a.webp",
              "مسار النتيجة للصورة الأولى محفوظ منفردًا")
        check(saved[second_key]["output_path"] == "/out/b.webp",
              "مسار النتيجة للصورة الثانية محفوظ منفردًا")
        check(saved[first_key]["barcode"] == saved[second_key]["barcode"] == barcode,
              "يسمح بتكرار الباركود كدليل ربط دون أن يكون مفتاحًا")

        # اقتصاص التغذية يشترك في source_path مع صورة المنتج، لكنه نتيجة
        # مستقلة يجب أن تبقى ظاهرة عند حفظ الجلسة واستعادتها.
        nutrition = Item(front, "nutrition-crop.webp", barcode, "10003933",
                         "/out/10003933_حبه-1.webp", match_source="nutrition_crop")
        nutrition_key = image_identity_key(
            nutrition.source_path, nutrition.source_name,
            nutrition.output_path, nutrition.match_source)
        primary_key = image_identity_key(
            items[0].source_path, items[0].source_name,
            items[0].output_path, items[0].match_source)
        check(nutrition_key != primary_key,
              "اقتصاص التغذية يملك هوية مستقلة رغم مشاركة المصدر")
        window.current_result = Result([items[0], nutrition])
        window.v2_save_session()
        saved = store.state.images
        check(len(saved) >= 3 and nutrition_key in saved,
              "حفظ الجلسة لا يسقط اقتصاص التغذية إلى أسفل أو يدمجه بالصورة")
        check(saved[nutrition_key]["output_path"] == nutrition.output_path,
              "مسار اقتصاص التغذية محفوظ منفردًا")
    print("OK: repeated barcodes never collapse distinct session images")


if __name__ == "__main__":
    run()
