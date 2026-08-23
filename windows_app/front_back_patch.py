"""ربط صور وجهي المنتج: باركود الخلف يعرّف الصنف، وOCR الوجه يثبت الاسم.

الربط لا يُنفَّذ إلا إذا طابق OCR توقيعًا متعدد الكلمات من الإكسل (علامة +
وصف فارق + وزن/عدد عند وجود بدائل) بدرجة وثقة فارق كافيين؛ أما الحالات
الضعيفة فتظل في المراجعة اليدوية بلا أي تعديل أو تسمية خاطئة.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import sys

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "src", ROOT / "windows_app"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

__all__ = ["install_front_back_linking"]


@dataclass(frozen=True)
class _CatalogRecord:
    item_code: str
    product_name: str
    barcode: str = ""


def _source_path(item: object, workspace: Path) -> Path | None:
    value = str(getattr(item, "source_path", "") or "")
    path = Path(value)
    if path.is_file():
        return path
    # المصادر قد تكون أودعت داخل مساحة العمل بعد تشغيل دفعة سابقة.
    name = str(getattr(item, "source_name", "") or path.name)
    for candidate in (workspace / "sources" / name, workspace / name):
        if candidate.is_file():
            return candidate
    return None


def _catalog_records(index: object, item_codes: set[str]) -> list[_CatalogRecord]:
    rows = getattr(index, "rows", []) or []
    seen: set[str] = set()
    out: list[_CatalogRecord] = []
    for row in rows:
        code = str(row.get("code", "") or "")
        name = str(row.get("name", "") or "").strip()
        if code not in item_codes or not name or code in seen:
            continue
        seen.add(code)
        out.append(_CatalogRecord(code, name, str(row.get("barcode", "") or "")))
    return out


def _apply_auto_links(result: object, links: list[tuple[str, str]],
                      *, remove_background: bool, enhance_product: bool,
                      image_options: object | None) -> object:
    """يعيد معالجة الصور المؤكدة فقط عبر مسار الربط الرسمي.

    لذلك تحصل الصور الأمامية على العزل والتسمية والتسلسل نفسها التي يحصل
    عليها وجه الباركود، ولا نُعدّل بنية النتائج في الذاكرة بغير ملفات فعلية.
    """
    if not links:
        return result
    from smart_catalog_vision.pipeline import apply_manual_links
    workspace = Path(getattr(result, "workspace", ""))
    grouped: dict[str, list[str]] = {}
    for source_name, item_code in links:
        grouped.setdefault(item_code, []).append(source_name)
    for item_code, names in grouped.items():
        result = apply_manual_links(
            workspace, tuple(names), item_code,
            remove_background=remove_background,
            enhance_product=enhance_product,
            final_image_options=image_options,
        )
        if remove_background:
            # يعيد زر «توسيط 800×700» من المصدر لكل وجه تم ربطه بثقة؛
            # لا يغير الاسم أو قائمة النتائج، ويترك أي ملف مفقود كما هو.
            from native_app import auto_finish_linked_outputs
            auto_finish_linked_outputs(result, workspace)
    return result


def install_front_back_linking(window: Any) -> bool:
    """يلفّ اكتمال الدفعة ويضيف مرحلة OCR خلفية لا تعطل الواجهة."""
    original = getattr(window, "_on_batch_completed", None)
    if not callable(original) or getattr(original, "_front_back_patched", False):
        return False

    from PySide6.QtCore import QThread, Signal

    class FrontBackWorker(QThread):
        progress = Signal(int, int)
        completed = Signal(object, object)
        failed = Signal(str)

        def __init__(self, result: object, index: object, remove_background: bool,
                     enhance_product: bool, image_options: object | None):
            super().__init__()
            self.result = result
            self.index = index
            self.remove_background = remove_background
            self.enhance_product = enhance_product
            self.image_options = image_options

        def run(self) -> None:
            try:
                import cv2
                from engine_v2.front_back_link_v2 import (
                    extract_product_ocr, extract_weight_hints, make_signature,
                    match_product_name,
                )

                items = list(getattr(self.result, "items", []) or [])
                workspace = Path(getattr(self.result, "workspace", ""))
                # صور الباركود الموثوقة فقط تصنع قائمة الأصناف المرجعية.
                anchored_codes = {
                    str(getattr(item, "item_code", "") or "")
                    for item in items
                    if str(getattr(item, "status", "")) in {"matched", "manual"}
                    and str(getattr(item, "item_code", "") or "")
                    and str(getattr(item, "barcode", "") or "")
                }
                references = _catalog_records(self.index, anchored_codes)
                candidates = [
                    item for item in items
                    if str(getattr(item, "status", "")) not in {"matched", "manual"}
                ]
                report = {"anchors": len(references), "reviewed": len(candidates),
                          "linked": 0, "rejected": 0, "details": []}
                if not references or not candidates:
                    self.completed.emit(self.result, report)
                    return

                links: list[tuple[str, str]] = []
                expected_quantities = {
                    quantity for record in references
                    for quantity in make_signature(record.product_name).quantities
                }
                for number, item in enumerate(candidates, 1):
                    self.progress.emit(number, len(candidates))
                    source = _source_path(item, workspace)
                    if source is None:
                        report["rejected"] += 1
                        continue
                    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
                    ocr_text = extract_product_ocr(image)
                    match = match_product_name(ocr_text, references)
                    # إذا تطابق اسم/علامة المنتج في عنصرين فارقين على الأقل
                    # لكن بقيت أحجام متعددة متشابهة، نقرأ ملصق الوزن فقط.
                    if (not match.accepted and len(match.shared_tokens) >= 2
                            and image is not None):
                        hints = extract_weight_hints(
                            image, expected_quantities=expected_quantities)
                        if hints:
                            match = match_product_name(
                                ocr_text + "\n" + "\n".join(hints), references)
                    if not match.accepted or match.record is None:
                        report["rejected"] += 1
                        continue
                    source_name = str(getattr(item, "source_name", "") or source.name)
                    links.append((source_name, str(match.record.item_code)))
                    report["details"].append({
                        "source": source_name,
                        "item_code": str(match.record.item_code),
                        "score": round(float(match.score), 3),
                        "shared": list(match.shared_tokens),
                    })

                linked_result = _apply_auto_links(
                    self.result, links,
                    remove_background=self.remove_background,
                    enhance_product=self.enhance_product,
                    image_options=self.image_options,
                )
                report["linked"] = len(links)
                self.completed.emit(linked_result, report)
            except Exception as exc:
                self.failed.emit(str(exc))

    def patched(result: object) -> None:
        original(result)
        index = getattr(window, "v2_catalog_index", None)
        if index is None:
            return
        items = list(getattr(result, "items", []) or [])
        anchors = [i for i in items if getattr(i, "item_code", "") and getattr(i, "barcode", "")]
        reviews = [i for i in items if str(getattr(i, "status", "")) not in {"matched", "manual"}]
        if not anchors or not reviews:
            return
        worker = FrontBackWorker(
            result, index,
            bool(window.remove_background_check.isChecked()),
            bool(window.enhance_product_check.isChecked()),
            window._final_image_options(),
        )
        window._front_back_worker = worker
        try:
            window._set_busy(True)
            window.status_label.setText("التحقق من صور الوجه الأمامي بالاسم والوزن…")
        except Exception:
            pass

        def on_progress(done: int, total: int) -> None:
            try:
                window.status_label.setText(f"ربط الوجهين: {done}/{total} — فحص الاسم والوزن")
            except Exception:
                pass

        def on_completed(new_result: object, report: dict) -> None:
            try:
                window.current_result = new_result
                window._populate_results()
                message = (f"ربط ذكي للوجهين: {report['linked']} صورة موثوقة، "
                           f"{report['rejected']} تُركت للمراجعة اليدوية.")
                window.status_label.setText(message)
                guard = getattr(window, "_work_guard_save_now", None)
                if callable(guard):
                    guard("front_back_ocr")
            finally:
                try:
                    window._set_busy(False)
                    window._update_controls()
                except Exception:
                    pass

        def on_failed(error: str) -> None:
            try:
                window.status_label.setText("تعذر ربط الوجهين تلقائيًا؛ بقيت الصور للمراجعة اليدوية.")
            finally:
                try:
                    window._set_busy(False)
                    window._update_controls()
                except Exception:
                    pass

        worker.progress.connect(on_progress)
        worker.completed.connect(on_completed)
        worker.failed.connect(on_failed)
        try:
            window._track_worker(worker)
        except Exception:
            pass
        worker.start()

    patched._front_back_patched = True
    window._on_batch_completed = patched
    return True
