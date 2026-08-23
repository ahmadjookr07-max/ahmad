from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MIS_SKIP_LICENSE", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "windows_app"), str(ROOT / "src")]

import native_app as app_module


@dataclass
class Item:
    output_path: str = ""
    source_path: str = ""
    source_name: str = "source.jpg"
    status: str = "matched"


@dataclass
class Result:
    items: list[Item]


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ✓ {message}")


def reject_duplicate(*_args, **_kwargs):
    raise AssertionError("لا يجوز استدعاء إعادة معالجة كاملة بعد الربط")


def run() -> None:
    from engine_v2.processor_v2 import ProcessOptionsV2, ProcessorV2

    # الحفظ الأول يحمل الآن إعدادات زر «توسيط 800×700»؛ لا يحتاج تمريرة
    # من المصدر بعد نجاح الربط.
    options = ProcessOptionsV2()
    check(options.frame_margin_ratio == 0.06,
          "الإطار الافتراضي يستعمل هوامش محرر الصورة 6%")
    check(options.finish_product is False,
          "الربط العادي يحافظ على قناع محرر الصور الخام دون تنقيح قديم")

    source_canvas = np.full((1200, 600, 3), 255, np.uint8)
    alpha = np.zeros((1200, 600), np.float32)
    source_canvas[100:1100, 200:400] = (20, 20, 20)
    alpha[100:1100, 200:400] = 1.0
    framed = ProcessorV2._frame_on_canvas(source_canvas, alpha, options)
    check(framed.shape[:2] == (700, 800), "الناتج النهائي يبقى لوحة 800×700")
    foreground = np.where(np.any(framed < 250, axis=2))
    fx0, fx1 = int(foreground[1].min()), int(foreground[1].max())
    fy0, fy1 = int(foreground[0].min()), int(foreground[0].max())
    check((fy1 - fy0 + 1) == 616 and abs((fx0 + fx1 + 1) - 800) <= 1,
          "المنتج يملأ 88% ويتمركز مثل اعتماد الإطار اليدوي")

    with tempfile.TemporaryDirectory() as td:
        workspace = Path(td)
        output = workspace / "10003933_حبه.webp"
        output.write_bytes(b"placeholder")
        result = Result([Item(str(output), str(workspace / "source.jpg"))])

        # الربط اليدوي يستدعي المعالجة الرسمية مرة واحدة ولا يتبعه عزل ثانٍ.
        original_apply = app_module.apply_manual_link
        original_restore = app_module._vault_restore_sources
        original_finish = getattr(app_module, "auto_finish_linked_outputs")
        manual_calls: list[object] = []
        try:
            app_module._vault_restore_sources = lambda _workspace: None
            app_module.apply_manual_link = lambda *args, **kwargs: (manual_calls.append(args) or result)
            app_module.auto_finish_linked_outputs = reject_duplicate
            worker = app_module.ManualLinkWorker(workspace, "source.jpg", "10003933", True, True)
            worker.run()
            check(len(manual_calls) == 1, "الربط اليدوي ينفذ معالجة المصدر الرسمية مرة واحدة")
            check(worker.auto_finished_count == 0, "لا توجد معالجة إضافية بعد الحفظ")
        finally:
            app_module.apply_manual_link = original_apply
            app_module._vault_restore_sources = original_restore
            app_module.auto_finish_linked_outputs = original_finish

        # الدفعة الآلية لا تعيد تشغيل المعالج بعد أن ينهي الربط المؤكد.
        original_run_batch = app_module.run_batch
        original_finish = app_module.auto_finish_linked_outputs
        original_quality = app_module.BatchWorker._quality_post_pass
        try:
            app_module.run_batch = lambda *args, **kwargs: result
            app_module.auto_finish_linked_outputs = reject_duplicate
            app_module.BatchWorker._quality_post_pass = reject_duplicate
            app_module.BatchWorker(Path("catalog.xlsx"), [], workspace, True, True).run()
            check(True, "المطابقة الآلية لا تعيد العزل أو الجودة بعد الحفظ الأول")
        finally:
            app_module.run_batch = original_run_batch
            app_module.auto_finish_linked_outputs = original_finish
            app_module.BatchWorker._quality_post_pass = original_quality

        # ربط الوجه والخلف يحتفظ بنفس الطريق الرسمي بلا تمريرة مصدر ثانية.
        import smart_catalog_vision.pipeline as vision_pipeline
        from front_back_patch import _apply_auto_links
        original_apply_links = vision_pipeline.apply_manual_links
        original_finish = app_module.auto_finish_linked_outputs
        front_result = Result([])
        front_result.workspace = str(workspace)
        try:
            vision_pipeline.apply_manual_links = lambda *args, **kwargs: result
            app_module.auto_finish_linked_outputs = reject_duplicate
            _apply_auto_links(front_result, [("source.jpg", "10003933")],
                              remove_background=True, enhance_product=True,
                              image_options=None)
            check(True, "ربط الوجه والخلف لا يعيد معالجة الصورة بعد الحفظ")
        finally:
            vision_pipeline.apply_manual_links = original_apply_links
            app_module.auto_finish_linked_outputs = original_finish

    print("OK: confirmed links perform one source pass into an exact 800x700 frame")


if __name__ == "__main__":
    run()
