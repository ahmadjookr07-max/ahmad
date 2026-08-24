from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "windows_app"), str(ROOT / "src")]

from PySide6.QtWidgets import QApplication, QLineEdit, QListWidget, QMainWindow, QTableWidget

from engine_v2.session_v2 import (
    SessionState,
    SessionStore,
    canonicalize_session_state,
    image_identity_key,
)
from session_fidelity_patch import install_session_fidelity
from v2_ui import install_v2


@dataclass
class Item:
    source_path: str
    source_name: str
    barcode: str
    item_code: str
    output_path: str
    review_path: str = ""
    status: str = "manual"
    product_name: str = "منتج اختبار"
    confidence: float = 0.98
    explanation: str = ""
    match_source: str = "barcode"
    barcode_candidates: tuple = ()
    warnings: tuple = ()
    processing_ms: float = 3.0
    foreground_method: str = "editor"
    foreground_quality_score: float = 0.91
    foreground_quality_status: str = "good"
    foreground_quality_metrics: dict | None = None


@dataclass
class Result:
    workspace: str
    items: list[Item]


class Window(QMainWindow):
    """نافذة دنيا تستدعي مسار V2 الحقيقي دون عرض الواجهة."""

    def __init__(self, root: Path, result: Result | None = None) -> None:
        super().__init__()
        self.catalog_edit = QLineEdit()
        self.images_list = QListWidget()
        self.results_table = QTableWidget()
        self.current_result = result
        self.current_workspace = Path(result.workspace) if result else None
        self.populate_calls = 0
        self.show_calls = 0
        install_v2(self, root)
        install_session_fidelity(self)

    def _populate_results(self, restore_position=None) -> None:
        self.populate_calls += 1
        self.restore_position = restore_position

    def _show_results_page(self) -> None:
        self.show_calls += 1


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ✓ {message}")


def item_key(item: Item) -> str:
    return image_identity_key(
        item.source_path, item.source_name, item.output_path, item.match_source)


def saved_keys(store: SessionStore) -> set[str]:
    return set((store.state.images or {}).keys())


def run() -> None:
    app = QApplication.instance() or QApplication([])
    _ = app

    # مسارات Windows النسبية تظهر كثيرًا في جلسات الإصدارات القديمة. لا
    # تُدمج الصورة الشقيقة ذات الاسم نفسه، لكن النسخة النسبية/المطلقة
    # للصورة ذاتها يجب أن تصبح سجلًا واحدًا مع اعتماد وموضع سليمين.
    source_root = r"C:\\Catalog\\Raw"
    output_root = r"C:\\Catalog\\Output"
    front_abs = r"C:\\Catalog\\Raw\\Packs\\PHOTO-01.jpg"
    nutrition_abs = r"C:\\Catalog\\Output\\Nutrition\\10003933.webp"
    expected_front = image_identity_key(front_abs, "PHOTO-01.jpg")
    expected_nutrition = image_identity_key(
        front_abs, "nutrition-crop.webp", nutrition_abs, "nutrition_crop")
    windows_state = SessionState(
        source_folder=source_root,
        output_folder=output_root,
        images={
            "name:PHOTO-01.jpg": {
                "source_path": r"Packs\\PHOTO-01.jpg",
                "source_name": "PHOTO-01.jpg",
                "status": "manual",
                "output_path": r"10003933_حبه-1.webp",
            },
            "path:C:/Catalog/Raw/Packs/PHOTO-01.jpg": {
                "source_path": front_abs,
                "source_name": "PHOTO-01.jpg",
                "status": "edited",
                "output_path": r"C:\\Catalog\\Output\\10003933_حبه-1.webp",
            },
            "path:C:/Catalog/Raw/Other/PHOTO-01.jpg": {
                "source_path": r"C:\\Catalog\\Raw\\Other\\PHOTO-01.jpg",
                "source_name": "PHOTO-01.jpg",
                "status": "manual",
                "output_path": r"C:\\Catalog\\Output\\10003933_حبه-2.webp",
            },
            "name:nutrition-crop.webp": {
                "source_path": r"Packs\\PHOTO-01.jpg",
                "source_name": "nutrition-crop.webp",
                "match_source": "nutrition_crop",
                "output_path": r"Nutrition\\10003933.webp",
            },
            "output:C:/Catalog/Output/Nutrition/10003933.webp": {
                "source_path": front_abs,
                "source_name": "nutrition-crop.webp",
                "match_source": "nutrition_crop",
                "output_path": nutrition_abs,
            },
        },
        approved={"name:PHOTO-01.jpg": True},
        position={"source_key": "name:PHOTO-01.jpg", "row": 0},
    )
    check(canonicalize_session_state(windows_state),
          "ترحيل جلسة Windows ذات المسارات النسبية والمطلقة تم")
    check(len(windows_state.images) == 3 and
          expected_front in windows_state.images and
          expected_nutrition in windows_state.images,
          "تُدمج aliases فقط وتبقى الصورة الشقيقة وقصّ التغذية مستقلين")
    check(windows_state.images[expected_front]["status"] == "edited" and
          windows_state.approved.get(expected_front) is True and
          windows_state.position.get("source_key") == expected_front,
          "ينتقل آخر تعديل والاعتماد وموضع المستخدم إلى الهوية الموحدة")
    check(not canonicalize_session_state(windows_state),
          "ترحيل المسارات ثابت عند تكراره ولا ينشئ تغييرًا إضافيًا")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        raw = root / "raw"
        out = root / "out"
        raw.mkdir()
        out.mkdir()
        # وجود الملفات يجعل استعادة المسارات مطابقة لواقع البرنامج.
        front_path = raw / "front" / "PHOTO-01.jpg"
        back_path = raw / "back" / "PHOTO-01.jpg"
        front_path.parent.mkdir()
        back_path.parent.mkdir()
        front_path.write_bytes(b"front")
        back_path.write_bytes(b"back")
        front_out = out / "10003933_حبه-1.webp"
        back_out = out / "10003933_حبه-2.webp"
        nutrition_out = out / "10003933_حقائق-1.webp"
        added_out = out / "10003933_حبه-3.webp"
        for p in (front_out, back_out, nutrition_out, added_out):
            p.write_bytes(b"result")

        front = Item(str(front_path), "PHOTO-01.jpg", "6280000000011",
                     "10003933", str(front_out), review_path=str(front_out))
        back = Item(str(back_path), "PHOTO-01.jpg", "6280000000011",
                    "10003933", str(back_out), review_path=str(back_out))
        nutrition = Item(str(front_path), "nutrition-crop.webp",
                         "6280000000011", "10003933", str(nutrition_out),
                         review_path=str(nutrition_out), match_source="nutrition_crop")
        added_path = raw / "extra" / "PHOTO-02.jpg"
        added_path.parent.mkdir()
        added_path.write_bytes(b"new-front")
        added = Item(str(added_path), "PHOTO-02.jpg", "6280000000011",
                     "10003933", str(added_out), review_path=str(added_out))
        original = [front, back, nutrition]
        expected_keys = {item_key(item) for item in original}
        expected_outputs = {item.output_path for item in original}
        check(len(expected_keys) == 3,
              "صورة الواجهة والخلف وقصّ التغذية تملك هويات مستقلة")

        first = Window(root, Result(str(out), list(original)))
        first.v2_save_session("جلسة التكرار")
        sid = first.v2_session_store.state.session_id
        check(saved_keys(first.v2_session_store) == expected_keys,
              "الحفظ الأول يكتب السجلات الثلاثة فقط")

        # يحاكي جلسة محفوظة بإصدار قديم: مدخل الاسم القديم هو نسخة من
        # الواجهة لكنه يحمل source_path صحيحًا. العيب السابق يبقيه فتظهر
        # الواجهة مرتين بعد الحفظ التالي.
        legacy_key = "PHOTO-01.jpg"
        legacy_entry = dict(first.v2_session_store.state.images[item_key(front)])
        first.v2_session_store.state.images[legacy_key] = legacy_entry
        # نكتب JSON قديمًا عمدًا: SessionStore.save الجديد يصححه قبل الكتابة
        # وهذا ما نريد اختباره عند القراءة، لذلك لا يجوز استعماله هنا.
        session_path = first.v2_session_store._path(sid)
        session_path.write_text(
            json.dumps(first.v2_session_store.state.to_dict(), ensure_ascii=False),
            encoding="utf-8",
        )
        check(len(first.v2_session_store.state.images) == 4,
              "تهيئة جلسة قديمة ذات alias مكرر لاختبار الترحيل")

        for cycle in range(1, 6):
            resumed = Window(root)
            state = resumed.v2_session_store.load(sid)
            check(state is not None, f"الدورة {cycle}: ملف الجلسة قابل للقراءة")
            resumed.v2_restore_session(state)
            items = list(resumed.current_result.items)
            restored_keys = {item_key(item) for item in items}
            restored_outputs = {item.output_path for item in items}
            check(len(items) == len(expected_keys) and restored_keys == expected_keys,
                  f"الدورة {cycle}: الاستعادة لا تعرض صورة أو صفًا مكررًا")
            check(restored_outputs == expected_outputs,
                  f"الدورة {cycle}: لا يفقد أي مسار ناتج أو قصّ تغذية")
            # بعد أول فتح، يعدل المستخدم ربط الصورة ثم يضيف صورة جديدة إلى
            # الجلسة نفسها. يجب أن يبقى التعديل والإضافة في كل حفظ لاحق.
            edited_index = next(
                index for index, item in enumerate(items)
                if item_key(item) == item_key(front)
            )
            edited = replace(
                items[edited_index],
                status="edited",
                product_name=f"منتج معدل في الدورة {cycle}",
            )
            resumed.current_result.items[edited_index] = edited
            if cycle == 1:
                resumed.current_result.items.append(added)
                expected_keys.add(item_key(added))
                expected_outputs.add(added.output_path)
            resumed.v2_save_session()
            check(saved_keys(resumed.v2_session_store) == expected_keys,
                  f"الدورة {cycle}: الحفظ التالي ثابت ولا يكرر أو يفقد الإضافة")
            edited_saved = resumed.v2_session_store.state.images[item_key(front)]
            check(edited_saved["status"] == "edited" and
                  edited_saved["item_name"] == f"منتج معدل في الدورة {cycle}",
                  f"الدورة {cycle}: تعديل المستخدم محفوظ في السجل القانوني")

        final = SessionStore(root / "SessionsV2")
        loaded = final.load(sid)
        check(loaded is not None and saved_keys(final) == expected_keys,
              "الملف النهائي ثابت بعد خمس دورات فتح وحفظ")
        check({v.get("output_path") for v in final.state.images.values()} == expected_outputs,
              "كل نتائج العزل والتغذية والإضافة الجديدة بقيت دون استبدال")
        final_front = final.state.images[item_key(front)]
        check(final_front["item_name"] == "منتج معدل في الدورة 5" and
              final_front["status"] == "edited",
              "آخر تعديل للمستخدم محفوظ بعد دورات الاستكمال المتكررة")
    print("OK: repeated save/restore is idempotent and lossless")


if __name__ == "__main__":
    run()
