# -*- coding: utf-8 -*-
"""batch_refine_v2 — الضبط التلقائي الجماعي للصور القديمة (1000+ دفعة واحدة).

يعالج مجلدًا كاملًا من الصور المنتجة سابقًا بمحرك V2:
- إعادة قص نظيف (ISNet) + تحسين تلقائي + تأطير 800×700 + ظل اختياري.
- ضبط الأسماء حسب نظام التسمية الموحد ومطابقة الوحدات مع ملف الإكسل.
- معالجة متوازية بعدة خيوط، إيقاف/استئناف عبر checkpoint JSON.
"""
from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import cv2

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
CHECKPOINT_NAME = ".batch_refine_checkpoint.json"


@dataclass
class RefineOptions:
    """خيارات الضبط الجماعي."""
    recut: bool = True              # إعادة قص الخلفية بـ ISNet
    enhance: bool = True            # تحسين تلقائي
    frame: bool = True              # تأطير 800×700 أبيض
    width: int = 800
    height: int = 700
    margin_ratio: float = 0.06
    shadow_preset: str = ""         # اسم preset من SHADOW_PRESETS أو فارغ
    fix_names: bool = False         # اختياري: ضبط الأسماء من الإكسل
    excel_path: str = ""            # اختياري: أي ملف إكسل يختاره المستخدم
    recursive: bool = False         # معالجة المجلدات الفرعية أيضًا
    workers: int = 0                # 0 = تلقائي
    webp_quality: int = 101         # lossless


@dataclass
class RefineItemResult:
    source: str
    output: str = ""
    new_name: str = ""
    name_note: str = ""
    status: str = "pending"   # done | skipped | error
    error: str = ""
    elapsed: float = 0.0


class BatchRefiner:
    """منسق المعالجة الجماعية المتوازية مع checkpoint للإيقاف/الاستئناف."""

    def __init__(self, model_dir: str | Path, options: RefineOptions | None = None):
        self.options = options or RefineOptions()
        self._model_dir = str(model_dir)
        self._segmenter = None
        self._seg_lock = threading.Lock()
        self._stop = threading.Event()
        self._catalog = None

    # ------------------------------------------------------------ control
    def stop(self) -> None:
        self._stop.set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    # ------------------------------------------------------------ helpers
    def _get_segmenter(self):
        if self._segmenter is None:
            with self._seg_lock:
                if self._segmenter is None:
                    from engine_v2.segmentation_v2 import ProductSegmenterV2
                    self._segmenter = ProductSegmenterV2(self._model_dir)
        return self._segmenter

    def _get_catalog(self):
        if self._catalog is None and self.options.excel_path:
            from engine_v2.catalog_index_v2 import CatalogIndex
            idx = CatalogIndex()
            idx.load_excel(self.options.excel_path)
            self._catalog = idx
        return self._catalog

    @staticmethod
    def list_images(folder: str | Path, recursive: bool = False) -> list[Path]:
        """كل الصور بأي مسمى وأي صيغة مدعومة — لا يشترط نمط تسمية."""
        folder = Path(folder)
        it = folder.rglob("*") if recursive else folder.iterdir()
        files = [p for p in sorted(it)
                 if p.is_file() and p.suffix.lower() in IMAGE_EXTS
                 and not p.name.startswith(".")]
        return files

    # --------------------------------------------------------- checkpoint
    @staticmethod
    def _checkpoint_path(out_dir: Path) -> Path:
        return out_dir / CHECKPOINT_NAME

    @staticmethod
    def load_checkpoint(out_dir: str | Path) -> dict:
        p = BatchRefiner._checkpoint_path(Path(out_dir))
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    @staticmethod
    def _save_checkpoint(out_dir: Path, done: dict) -> None:
        try:
            BatchRefiner._checkpoint_path(out_dir).write_text(
                json.dumps(done, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    # ------------------------------------------------------------- naming
    def _fixed_name(self, stem: str) -> tuple[str, str]:
        """يعيد (الاسم المضبوط بدون امتداد، ملاحظة).

        الوضع الحر (fix_names=False أو بلا إكسل): الاسم الأصلي يُحفظ كما هو
        مهما كان المسمى — لا يُشترط أي نمط تسمية ولا ملف إكسل.
        """
        if not self.options.fix_names:
            return stem, ""
        if not self.options.excel_path:
            return stem, "وضع حر — لم يُحدد إكسل، أُبقي الاسم"
        try:
            from engine_v2.naming_v2 import parse_name
            parsed = parse_name(stem)
        except Exception:
            return stem, ""
        if not parsed or not getattr(parsed, "item", None):
            return stem, "اسم غير قياسي — أُبقي كما هو"
        code = str(parsed.item)
        unit = (getattr(parsed, "unit", "") or "").strip()
        seq = int(getattr(parsed, "seq", 1) or 1)
        note = ""
        idx = self._get_catalog()
        if idx is not None:
            try:
                units = list(dict.fromkeys(idx.units_for_code(code)))
            except Exception:
                units = []
            if not units:
                note = "الصنف غير موجود في الإكسل"
            elif unit not in units:
                old_unit = unit or "بدون"
                unit = units[0]
                note = f"صُححت الوحدة: {old_unit} ← {unit}"
        if not unit:
            unit = "حبه"
            note = note or "أُضيفت الوحدة الافتراضية حبه"
        try:
            from engine_v2.naming_v2 import build_name
            new_stem = build_name(code, seq, unit)
        except Exception:
            new_stem = f"{code}_{unit}" if seq <= 1 else f"{code}_{seq}_{unit}"
        return new_stem, note

    # ------------------------------------------------------------ process
    def _process_one(self, src: Path, out_dir: Path) -> RefineItemResult:
        t0 = time.time()
        r = RefineItemResult(source=str(src))
        try:
            o = self.options
            data = np.fromfile(str(src), dtype=np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_COLOR)
            if img is None:
                r.status, r.error = "error", "تعذر قراءة الصورة"
                return r
            h, w = img.shape[:2]
            if max(h, w) > 2400:
                sc = 2400 / max(h, w)
                img = cv2.resize(img, (int(w * sc), int(h * sc)),
                                 interpolation=cv2.INTER_AREA)

            rgba = None
            if o.recut:
                seg = self._get_segmenter()
                res = seg.segment(img)
                alpha = (np.clip(res.alpha, 0, 1) * 255).astype(np.uint8)
                if alpha.max() < 30:   # فشل القص — أبقِ الأصل
                    rgba = None
                else:
                    rgba = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
                    rgba[:, :, 3] = alpha

            if o.enhance:
                from engine_v2.enhancement_v2 import auto_enhance
                if rgba is not None:
                    rgba[:, :, :3] = auto_enhance(rgba[:, :, :3])
                else:
                    img = auto_enhance(img)

            # الظل الاختياري
            if o.shadow_preset and rgba is not None:
                from engine_v2.shadow_v2 import SHADOW_PRESETS, apply_shadow
                preset = SHADOW_PRESETS.get(o.shadow_preset)
                if preset is not None and getattr(preset, "kind", "") != "none":
                    pad = int(rgba.shape[1] * 0.06)
                    rgba = cv2.copyMakeBorder(rgba, 0, 0, pad, pad,
                                              cv2.BORDER_CONSTANT,
                                              value=(0, 0, 0, 0))
                    rgba = apply_shadow(rgba, preset,
                                        pad_bottom=int(rgba.shape[0] * 0.05))

            # التأطير على أبيض
            if o.frame:
                final = self._frame_on_white(rgba if rgba is not None else img)
            else:
                if rgba is not None:
                    a = rgba[:, :, 3:4].astype(np.float32) / 255.0
                    final = np.clip(rgba[:, :, :3].astype(np.float32) * a +
                                    255.0 * (1 - a), 0, 255).astype(np.uint8)
                else:
                    final = img

            # الاسم المضبوط
            new_stem, note = self._fixed_name(src.stem)
            r.new_name = new_stem + ".webp"
            r.name_note = note
            out_path = out_dir / r.new_name
            # تفادى الكتابة فوق ملف مختلف بنفس الاسم
            counter = 2
            while out_path.exists() and str(out_path) != str(src):
                out_path = out_dir / f"{new_stem}__{counter}.webp"
                counter += 1
            ok, buf = cv2.imencode(".webp", final,
                                   [cv2.IMWRITE_WEBP_QUALITY, o.webp_quality])
            if not ok:
                r.status, r.error = "error", "فشل ترميز WebP"
                return r
            buf.tofile(str(out_path))
            r.output = str(out_path)
            r.status = "done"
            return r
        except Exception as exc:
            r.status, r.error = "error", str(exc)
            return r
        finally:
            r.elapsed = time.time() - t0

    def _frame_on_white(self, img: np.ndarray) -> np.ndarray:
        o = self.options
        if img.ndim == 3 and img.shape[2] == 4:
            a = img[:, :, 3]
            ys, xs = np.where(a > 10)
            if len(xs) == 0:
                rgb = img[:, :, :3]
            else:
                x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
                img = img[y0:y1 + 1, x0:x1 + 1]
                rgb = None
        else:
            # صورة بخلفية بيضاء: اقتصاص حول غير الأبيض
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            mask = gray < 247
            ys, xs = np.where(mask)
            if len(xs) > 20:
                x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
                img = img[y0:y1 + 1, x0:x1 + 1]
            rgb = img

        th, tw = o.height, o.width
        m = o.margin_ratio
        ih, iw = img.shape[:2]
        sc = min(tw * (1 - 2 * m) / iw, th * (1 - 2 * m) / ih)
        nw, nh = max(1, int(iw * sc)), max(1, int(ih * sc))
        resized = cv2.resize(img, (nw, nh),
                             interpolation=cv2.INTER_AREA if sc < 1
                             else cv2.INTER_CUBIC)
        canvas = np.full((th, tw, 3), 255, np.uint8)
        ox, oy = (tw - nw) // 2, (th - nh) // 2
        if resized.ndim == 3 and resized.shape[2] == 4:
            a = resized[:, :, 3:4].astype(np.float32) / 255.0
            region = canvas[oy:oy + nh, ox:ox + nw].astype(np.float32)
            canvas[oy:oy + nh, ox:ox + nw] = np.clip(
                resized[:, :, :3].astype(np.float32) * a + region * (1 - a),
                0, 255).astype(np.uint8)
        else:
            canvas[oy:oy + nh, ox:ox + nw] = resized
        return canvas

    # ---------------------------------------------------------------- run
    def run(self, folder: str | Path, out_dir: str | Path,
            progress: Optional[Callable[[int, int, RefineItemResult], None]] = None,
            resume: bool = True) -> list[RefineItemResult]:
        """يعالج كل صور المجلد بالتوازي. progress(i, total, result) لكل صورة."""
        self._stop.clear()
        folder, out_dir = Path(folder), Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        files = self.list_images(folder, recursive=self.options.recursive)
        done_map = self.load_checkpoint(out_dir) if resume else {}

        results: list[RefineItemResult] = []
        todo: list[Path] = []
        for p in files:
            key = p.name
            if resume and key in done_map:
                r = RefineItemResult(source=str(p), status="skipped",
                                     output=done_map[key].get("output", ""),
                                     new_name=done_map[key].get("new_name", ""))
                results.append(r)
            else:
                todo.append(p)

        total = len(files)
        counter = {"i": len(results)}
        lock = threading.Lock()

        # حمّل الموارد المشتركة مرة واحدة قبل الخيوط
        if self.options.recut:
            self._get_segmenter()
        if self.options.fix_names and self.options.excel_path:
            self._get_catalog()

        # التوازي الافتراضي محدود لتفادي ضغط الذاكرة (ISNet يستهلك كثيرًا لكل خيط)
        workers = self.options.workers or max(2, min(3, (os.cpu_count() or 4) - 1))

        def worker(p: Path) -> RefineItemResult:
            if self._stop.is_set():
                r = RefineItemResult(source=str(p), status="skipped",
                                     error="أُوقفت المعالجة")
                return r
            return self._process_one(p, out_dir)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(worker, p): p for p in todo}
            for fut in as_completed(futures):
                r = fut.result()
                with lock:
                    results.append(r)
                    counter["i"] += 1
                    if r.status == "done":
                        done_map[Path(r.source).name] = {
                            "output": r.output, "new_name": r.new_name}
                        if counter["i"] % 10 == 0:
                            self._save_checkpoint(out_dir, done_map)
                if progress:
                    progress(counter["i"], total, r)

        self._save_checkpoint(out_dir, done_map)
        return results
