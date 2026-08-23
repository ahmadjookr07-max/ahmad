from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MIS_SKIP_LICENSE", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "windows_app"), str(ROOT / "src")]

from native_app import MainWindow


@dataclass
class Item:
    source_name: str
    source_path: str
    output_path: str
    review_path: str
    item_code: str
    barcode: str


@dataclass
class Result:
    items: list[Item]


class WindowStub:
    _result_path = MainWindow._result_path
    _norm_path_key = staticmethod(MainWindow._norm_path_key)
    _recover_output_path = MainWindow._recover_output_path
    _repair_restored_result_paths = MainWindow._repair_restored_result_paths
    _editor_input_path = MainWindow._editor_input_path

    def __init__(self, workspace: Path, items: list[Item]) -> None:
        self.current_workspace = workspace
        self.current_result = Result(items)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ✓ {message}")


def touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"image")


def run() -> None:
    with tempfile.TemporaryDirectory() as td:
        workspace = Path(td)
        output = workspace / "output"
        source = workspace / "sources" / "barcode-view.jpg"
        touch(source)

        stale = Item("barcode-view.jpg", str(source),
                     str(output / "10003933_حبه.webp"), "",
                     "10003933", "4823077615009")
        recovered_file = output / "4823077615009_حبه.webp"
        touch(recovered_file)
        window = WindowStub(workspace, [stale])
        recovered = window._recover_output_path(stale, stale.item_code)
        check(recovered == recovered_file,
              "الجلسة تستعيد مخرج الباركود حين يحمل المسار القديم رقم الصنف")
        check(window._repair_restored_result_paths() == 1,
              "إصلاح الجلسة يثبت المسار الصحيح قبل بناء الجدول")
        check(window.current_result.items[0].output_path == str(recovered_file),
              "المسار المستعاد يبقى محفوظًا في نتيجة الجلسة")
        check(window._editor_input_path(window.current_result.items[0]) == recovered_file,
              "المحرر يفتح النتيجة المعالجة لا صورة المصدر الخام")

        # وجود أكثر من صورة شقيقة غير محجوزة للصنف نفسه ليس دليلًا كافيًا؛
        # لا يجوز اختيار أول ملف وخلط المعاينات.
        second_path = output / "4823077615009_حبه-1.webp"
        touch(second_path)
        ambiguous_stale = Item("another.jpg", str(source),
                               str(output / "10003933_حبه.webp"), "",
                               "10003933", "4823077615009")
        ambiguous_window = WindowStub(workspace, [ambiguous_stale])
        ambiguous = ambiguous_window._recover_output_path(
            ambiguous_stale, ambiguous_stale.item_code)
        check(ambiguous is None,
              "تعدد صور الباركود يمنع الاسترجاع العشوائي")

        # إذا كانت الصورة الثانية مستخدمة صراحة في صف آخر، يبقى المرشح
        # الوحيد للأولى قابلًا للاستعادة بأمان.
        stale_again = Item("barcode-view.jpg", str(source),
                           str(output / "10003933_حبه.webp"), "",
                           "10003933", "4823077615009")
        second = Item("front.jpg", str(workspace / "sources" / "front.jpg"),
                      str(second_path), "", "10003933", "4823077615009")
        window.current_result = Result([stale_again, second])
        recovered = window._recover_output_path(stale_again, stale_again.item_code)
        check(recovered == recovered_file,
              "مسار الصورة غير المستخدمة يُستعاد دون لمس الصورة الشقيقة")
    print("OK: barcode-reference output paths recover safely on session reopen")


if __name__ == "__main__":
    run()
