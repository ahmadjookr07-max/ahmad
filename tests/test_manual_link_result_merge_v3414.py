from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MIS_SKIP_LICENSE", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "windows_app"), str(ROOT / "src")]

from native_app import merge_manual_link_result


@dataclass(frozen=True)
class Item:
    source_name: str
    item_code: str
    output_path: str
    source_path: str = ""
    status: str = "matched"


@dataclass(frozen=True)
class Result:
    workspace: str
    items: list[Item]
    delivery_zip: str = ""
    report_json: str = ""
    report_csv: str = ""
    database_path: str = ""


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ✓ {message}")


def run() -> None:
    previous = Result(
        workspace="/workspace",
        items=[
            Item("front.webp", "1001", "/out/1001_حبه.webp"),
            Item("back.webp", "1001", "/out/1001_حبه-1.webp"),
            Item("other.webp", "1002", "/out/1002_حبه.webp"),
        ],
        delivery_zip="/out/old.zip",
        report_json="/out/old.json",
    )
    update = Result(
        workspace="/workspace",
        items=[Item("back.webp", "6287021750464",
                    "/out/6287021750464_كرتون.webp", status="manual")],
        delivery_zip="/out/new.zip",
        report_json="/out/new.json",
    )

    merged = merge_manual_link_result(previous, update, ("back.webp",))
    check(merged is not previous, "النتيجة المجمدة أُنشئت من جديد بأمان")
    check(len(merged.items) == 3, "ربط صورة واحدة لا يحذف بقية صفوف الجلسة")
    check([item.source_name for item in merged.items] == [
        "front.webp", "back.webp", "other.webp"], "ترتيب الصفوف الأصلي محفوظ")
    check(merged.items[0] is previous.items[0] and merged.items[2] is previous.items[2],
          "الصور غير المرتبطة تبقى كما هي")
    check(merged.items[1] is update.items[0]
          and merged.items[1].item_code == "6287021750464",
          "يُستبدل صف الصورة المرتبطة فقط بنتيجة الباركود الجديدة")
    check(merged.delivery_zip == "/out/new.zip" and merged.report_json == "/out/new.json",
          "تُحدّث مسارات تقارير النتيجة الجديدة دون فقد الصفوف")

    extra = Result(workspace="/workspace", items=[
        Item("restored.webp", "1003", "/out/1003_حبه.webp")])
    with_extra = merge_manual_link_result(previous, extra, ("restored.webp",))
    check(len(with_extra.items) == 4 and with_extra.items[-1] is extra.items[0],
          "مصدر مستعاد غير موجود سابقًا يُضاف ولا يُسقط")

    # صورتان قد تحملان الاسم أو الباركود نفسه، لكن كل واحدة لها مصدر
    # مستقل. يجب ألا يستبدل الربط إلا الصورة ذات المسار نفسه.
    repeated_previous = Result(workspace="/workspace", items=[
        Item("barcode.jpg", "1001", "/out/1001_حبه.webp",
             source_path="/raw/front/barcode.jpg"),
        Item("barcode.jpg", "1001", "/out/1001_حبه-1.webp",
             source_path="/raw/back/barcode.jpg"),
        Item("no-barcode.jpg", "", "",
             source_path="/raw/back/no-barcode.jpg", status="review"),
    ])
    repeated_update = Result(workspace="/workspace", items=[
        Item("barcode.jpg", "6287021750464", "/out/6287021750464_كرتون-1.webp",
             source_path="/raw/back/barcode.jpg", status="manual"),
    ])
    repeated_merged = merge_manual_link_result(repeated_previous, repeated_update)
    check(len(repeated_merged.items) == 3,
          "تكرار باركود/اسم لا يغير عدد صور الصنف")
    check(repeated_merged.items[0] is repeated_previous.items[0],
          "صورة الباركود الشقيقة الأولى لا تتبدل")
    check(repeated_merged.items[1] is repeated_update.items[0],
          "تتبدل فقط صورة الباركود ذات مسار المصدر المطابق")
    check(repeated_merged.items[2] is repeated_previous.items[2],
          "الصورة غير المقروءة تبقى مستقلة في الواجهة")

    # يحاكي محركًا يعيد لقطة جزئية تضم صورة الباركود الموجودة مع الصورة
    # اليدوية الجديدة. المفتاح المعلق للواجهة يجب أن يمنع تبدل الشقيقة.
    full_update = Result(workspace="/workspace", items=[
        Item("barcode.jpg", "1001", "/out/incorrect-replacement.webp",
             source_path="/raw/back/barcode.jpg", status="matched"),
        Item("no-barcode.jpg", "1001", "/out/1001_حبه-2.webp",
             source_path="/raw/back/no-barcode.jpg", status="manual"),
    ])
    target_key = "path:/raw/back/no-barcode.jpg"
    guarded = merge_manual_link_result(
        repeated_previous, full_update, ("no-barcode.jpg",), (target_key,))
    check(guarded.items[1] is repeated_previous.items[1],
          "لقطة العامل لا تستبدل صورة الباركود الشقيقة غير المحددة")
    check(guarded.items[2] is full_update.items[1],
          "تتبدل صورة الواجهة المحددة بهويتها الكاملة فقط")
    check(guarded.items[1].output_path == "/out/1001_حبه-1.webp",
          "مخرج صورة الباركود الشقيقة لا يُكتب فوقه")

    empty = Result(workspace="/workspace", items=[])
    check(merge_manual_link_result(previous, empty) is previous,
          "نتيجة ربط فارغة لا تغيّر قائمة الجلسة")
    print("OK: manual linking preserves all visible session rows")


if __name__ == "__main__":
    run()
