from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

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
    source_path: str = ""
    source_name: str = "source.jpg"
    status: str = "matched"


@dataclass
class Result:
    items: list[Item]


class RecordingProcessor:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, Path, object]] = []

    def process(self, source: str | Path, target: str | Path, options: object):
        source = Path(source)
        target = Path(target)
        self.calls.append((source, target, options))
        # محاكاة معالج ناجح: يكتب نتيجة مختلفة في الملف المؤقت فقط؛ الاختبار
        # يتحقق لاحقًا من الاستبدال الذري فوق اسم النتيجة الأصلي.
        image = np.full((700, 800, 3), (40, 180, 80), np.uint8)
        ok, encoded = cv2.imencode(".webp", image, [cv2.IMWRITE_WEBP_QUALITY, 101])
        if not ok:
            raise RuntimeError("تعذر كتابة ناتج المحاكاة")
        encoded.tofile(str(target))
        return SimpleNamespace(ok=True, output_path=str(target))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ✓ {message}")


def run() -> None:
    from engine_v2 import integration_v2

    with tempfile.TemporaryDirectory() as td:
        workspace = Path(td)
        source = workspace / "source.jpg"
        output = workspace / "processed" / "10003933_حبه.webp"
        output.parent.mkdir(parents=True)
        source_img = np.full((1100, 900, 3), (45, 95, 160), np.uint8)
        output_img = np.full((700, 800, 3), (10, 10, 180), np.uint8)
        cv2.imwrite(str(source), source_img)
        ok, encoded = cv2.imencode(".webp", output_img, [cv2.IMWRITE_WEBP_QUALITY, 101])
        if not ok:
            raise RuntimeError("تعذر إنشاء ناتج الاختبار")
        encoded.tofile(str(output))

        fake = RecordingProcessor()
        original_get_processor = integration_v2.get_processor
        try:
            integration_v2.get_processor = lambda: fake
            result = Result([Item(str(output), str(source))])
            count = auto_finish_linked_outputs(result, workspace)
        finally:
            integration_v2.get_processor = original_get_processor

        check(count == 1, "تنفذ إعادة التأطير الذكية لصورة الربط")
        check(len(fake.calls) == 1, "يستدعي المسار معالجًا واحدًا للصورة المستقلة")
        called_source, called_temp, opts = fake.calls[0]
        check(called_source == source, "يعالج مصدر الصورة الفريد لا نتيجة أو صورة شقيقة")
        check(called_temp.name.startswith(".10003933_حبه.auto-frame.tmp"),
              "تكتب المعالجة أولًا إلى ملف مؤقت ذري")
        check(getattr(opts, "width", 0) == 800 and getattr(opts, "height", 0) == 700,
              "يستخدم تأطير 800×700 المطابق لزر اعتماد الإطار")
        check(getattr(opts, "frame_margin_ratio", None) == 0.06,
              "يستخدم هوامش 6% من كل بُعد كما في محرر الصورة")
        check(bool(getattr(opts, "enhance", False)) and bool(getattr(opts, "text_aware", False)),
              "يعيد التحسين المحافظ الواعي بالنص من المصدر")
        check(output.is_file() and not called_temp.exists(),
              "يستبدل الناتج فوق اسمه نفسه بلا نسخة أو ملف مؤقت")
        final = cv2.imread(str(output), cv2.IMREAD_COLOR)
        check(int(final[0, 0, 1]) == 180, "ظهر ناتج إعادة التأطير محل نتيجة الربط السابقة")

        # إذا غاب المصدر لا تُخمن صورة شقيقة ولا تمس النتيجة القائمة.
        before = output.read_bytes()
        original_get_processor = integration_v2.get_processor
        try:
            integration_v2.get_processor = lambda: fake
            missing = Result([Item(str(output), str(workspace / "absent.jpg"), "same-name.jpg")])
            check(auto_finish_linked_outputs(missing, workspace) == 0,
                  "يتجاوز المصدر المفقود دون تخمين")
        finally:
            integration_v2.get_processor = original_get_processor
        check(output.read_bytes() == before, "تبقى النتيجة السابقة سليمة عند غياب المصدر")

        review = Result([Item(str(output), str(source), status="review")])
        original_get_processor = integration_v2.get_processor
        try:
            integration_v2.get_processor = lambda: fake
            check(auto_finish_linked_outputs(review, workspace) == 0,
                  "لا تعالج الأتمتة صورة مراجعة غير مرتبطة")
        finally:
            integration_v2.get_processor = original_get_processor
        check(len(fake.calls) == 1, "لا يستدعي المسار المعالج لصورة المراجعة")

        # تحقق عددي مستقل: نقطة التأطير نفسها تستعمل المساحة 88% من العرض
        # والارتفاع، وهو نص معادلة _smart_frame في محرر الفيديو.
        from engine_v2.processor_v2 import ProcessOptionsV2, ProcessorV2
        source_canvas = np.full((1200, 600, 3), 255, np.uint8)
        alpha = np.zeros((1200, 600), np.float32)
        source_canvas[100:1100, 200:400] = (20, 20, 20)
        alpha[100:1100, 200:400] = 1.0
        framed = ProcessorV2._frame_on_canvas(
            source_canvas, alpha,
            ProcessOptionsV2(width=800, height=700, frame_margin_ratio=0.06),
        )
        check(framed.shape[:2] == (700, 800), "تظل لوحة النتيجة 800×700")
        foreground = np.where(np.any(framed < 250, axis=2))
        fx0, fx1 = int(foreground[1].min()), int(foreground[1].max())
        fy0, fy1 = int(foreground[0].min()), int(foreground[0].max())
        check((fy1 - fy0 + 1) == 616 and abs((fx0 + fx1 + 1) - 800) <= 1,
              "يملأ المنتج 88% من الارتفاع ويتمركز أفقيًا مثل المحرر")

        # اختبار عامل الربط: نجاح الرابط يستدعي الأتمتة فقط حين يكون العزل مطلوبًا.
        original_apply = app_module.apply_manual_link
        original_restore = app_module._vault_restore_sources
        original_finish = app_module.auto_finish_linked_outputs
        calls: list[tuple[object, object]] = []
        try:
            app_module._vault_restore_sources = lambda _workspace: None
            app_module.apply_manual_link = lambda *args, **kwargs: Result([Item(str(output), str(source))])
            app_module.auto_finish_linked_outputs = lambda result, ws: (calls.append((result, ws)) or 1)
            worker = ManualLinkWorker(workspace, "source.jpg", "10003933", True, True)
            worker.run()
            check(len(calls) == 1 and calls[0][1] == workspace,
                  "نجاح ربط الباركود يشغّل اعتماد الإطار تلقائيًا")
            calls.clear()
            worker_without_cutout = ManualLinkWorker(workspace, "source.jpg", "10003933", False, True)
            worker_without_cutout.run()
            check(not calls, "لا يُفرض الإجراء حين يعطّل المستخدم العزل")
        finally:
            app_module.apply_manual_link = original_apply
            app_module._vault_restore_sources = original_restore
            app_module.auto_finish_linked_outputs = original_finish

        # مسار الدفعة الآلية يستخدم التأطير نفسه قبل تمريرة الجودة، وليس
        # الربط اليدوي وحده؛ وهذا هو المسار الذي أنتج الصورة الصغيرة بالفيديو.
        original_run_batch = app_module.run_batch
        original_finish = app_module.auto_finish_linked_outputs
        original_quality_pass = app_module.BatchWorker._quality_post_pass
        batch_calls: list[object] = []
        try:
            app_module.run_batch = lambda *args, **kwargs: Result([Item(str(output), str(source))])
            app_module.auto_finish_linked_outputs = lambda result, ws: (batch_calls.append((result, ws)) or 1)
            app_module.BatchWorker._quality_post_pass = lambda self, result: None
            BatchWorker = app_module.BatchWorker
            BatchWorker(Path("catalog.xlsx"), [], workspace, True, True).run()
            check(len(batch_calls) == 1 and batch_calls[0][1] == workspace,
                  "تمر المطابقة الآلية في الدفعة باعتماد الإطار من المصدر")
            batch_calls.clear()
            BatchWorker(Path("catalog.xlsx"), [], workspace, False, True).run()
            check(not batch_calls, "لا تؤطر الدفعة الصور عند تعطيل العزل")
        finally:
            app_module.run_batch = original_run_batch
            app_module.auto_finish_linked_outputs = original_finish
            app_module.BatchWorker._quality_post_pass = original_quality_pass

        # صور الوجه والخلف المرتبطة بثقة تمر بالطريق نفسه بعد ربط الاسم OCR.
        import smart_catalog_vision.pipeline as vision_pipeline
        from front_back_patch import _apply_auto_links
        original_apply_links = vision_pipeline.apply_manual_links
        original_finish = app_module.auto_finish_linked_outputs
        front_back_calls: list[object] = []
        try:
            vision_pipeline.apply_manual_links = lambda *args, **kwargs: Result([Item(str(output), str(source), "front.jpg")])
            app_module.auto_finish_linked_outputs = lambda result, ws: (front_back_calls.append((result, ws)) or 1)
            front_result = Result([])
            front_result.workspace = str(workspace)
            _apply_auto_links(front_result, [("front.jpg", "10003933")],
                              remove_background=True, enhance_product=True,
                              image_options=None)
            check(len(front_back_calls) == 1 and front_back_calls[0][1] == workspace,
                  "يرث ربط الوجه والخلف اعتماد الإطار دون إنشاء ملف ثانٍ")
        finally:
            vision_pipeline.apply_manual_links = original_apply_links
            app_module.auto_finish_linked_outputs = original_finish
    print("OK: every confirmed link reprocesses the unique source into an atomic 800x700 frame")


if __name__ == "__main__":
    run()
