from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MIS_SKIP_LICENSE", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "windows_app"), str(ROOT / "src")]

import native_app as app_module
from native_app import ManualLinkWorker, auto_finish_linked_outputs


@dataclass
class Item:
    output_path: str


@dataclass
class Result:
    items: list[Item]


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ✓ {message}")


def foreground_center(image: np.ndarray) -> tuple[float, float]:
    mask = (cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) < 246).astype(np.uint8)
    moments = cv2.moments(mask, binaryImage=True)
    return moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]


def run() -> None:
    with tempfile.TemporaryDirectory() as td:
        workspace = Path(td)
        target = workspace / "processed" / "10003933_حبه.webp"
        target.parent.mkdir(parents=True)
        image = np.full((700, 800, 3), 255, np.uint8)
        # منتج منحرف عن الوسط كما قد يصل بعد الربط؛ التأطير التلقائي
        # يعيده إلى الوسط مع 106% آمنًا.
        cv2.rectangle(image, (105, 180), (350, 600), (32, 130, 214), -1)
        ok, encoded = cv2.imencode(".webp", image, [cv2.IMWRITE_WEBP_QUALITY, 101])
        if not ok:
            raise RuntimeError("تعذر إنشاء صورة الاختبار")
        encoded.tofile(str(target))
        before = cv2.imread(str(target), cv2.IMREAD_COLOR)
        before_center = foreground_center(before)

        count = auto_finish_linked_outputs(
            Result([Item("processed/10003933_حبه.webp")]), workspace)
        after = cv2.imread(str(target), cv2.IMREAD_COLOR)
        after_center = foreground_center(after)
        check(count == 1, "تنفذ خطوة الإنهاء التلقائي لصورة الربط")
        check(target.is_file(), "يبقى الاسم والملف نفسهما بعد المعالجة")
        check(not list(target.parent.glob("*.frame.tmp*")),
              "لا تبقى ملفات مؤقتة أو نسخ إضافية")
        check(abs(after_center[0] - 400) < abs(before_center[0] - 400),
              "يتمركز المنتج تلقائيًا أفقيًا في النتيجة")
        check(abs(after_center[1] - 350) < abs(before_center[1] - 350),
              "يتمركز المنتج تلقائيًا رأسيًا في النتيجة")
        check(auto_finish_linked_outputs(Result([Item(str(target))])) == 1,
              "تقبل العملية المسار المطلق للربط المفرد")

        # اختبار خط الربط نفسه: لا نكتفي بفحص المساعد المنفصل، بل نثبت
        # أن النجاح في apply_manual_link يستدعي خطوة الفيديو تلقائيًا.
        original_apply = app_module.apply_manual_link
        original_restore = app_module._vault_restore_sources
        original_finish = app_module.auto_finish_linked_outputs
        calls: list[tuple[object, object]] = []
        try:
            app_module._vault_restore_sources = lambda _workspace: None
            app_module.apply_manual_link = lambda *args, **kwargs: Result([Item(str(target))])
            app_module.auto_finish_linked_outputs = lambda result, workspace: (calls.append((result, workspace)) or 1)
            worker = ManualLinkWorker(workspace, "source.jpg", "10003933", True, True)
            worker.run()
            check(len(calls) == 1 and calls[0][1] == workspace,
                  "نجاح ربط الباركود يشغّل التأطير التلقائي فورًا")
            calls.clear()
            worker_without_cutout = ManualLinkWorker(
                workspace, "source.jpg", "10003933", False, True)
            worker_without_cutout.run()
            check(not calls,
                  "لا يُفرض التأطير على صورة اختار المستخدم إبقاء خلفيتها")
        finally:
            app_module.apply_manual_link = original_apply
            app_module._vault_restore_sources = original_restore
            app_module.auto_finish_linked_outputs = original_finish
    print("OK: manual link automatically frames its output in place")


if __name__ == "__main__":
    run()
