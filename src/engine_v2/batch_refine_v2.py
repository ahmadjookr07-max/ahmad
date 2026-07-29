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
    webp_quality: int = 101         # 101 = lossless (جودة كاملة)
    compress: bool = False          # ضغط الملفات: حجم أصغر بجودة عالية جدًا
    compress_quality: int = 95      # جودة الضغط (عالية جدًا — تحافظ على حقائق المنتج)
    out_format: str = "webp"        # صيغة الإخراج النهائية: webp | jpg | png (واحدة فقط يختارها المستخدم)
    polish: bool = False            # تنقيح استوديو نهائي للتسليم (حواف نظيفة + لمعة متجر)
    polish_strength: float = 0.5    # قوة التنقيح 0..1
    text_aware: bool = True         # محرك الجودة الواعي بالنص: حدة ذكية + تصغير تدريجي
    blur_dates: bool = True         # طمس تواريخ الإنتاج/الانتهاء المطبوعة تلقائيًا (تمويه طفيف بلون المنتج)
    naming_scheme: str = "dash"     # نمط التسمية: dash (رقم_وحدة-1) | classic (رقم_1_وحدة)
    naming_enabled: bool = True     # تفعيل نظام التسمية (مع fix_names)
    skip_approved: bool = True      # لا يلمس مخرجات موجودة معتمدة سابقًا (لا يعاد إنتاجها أو تغيير اسمها)


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
    def list_images(folder: str | Path, recursive: bool = False,
                    exclude_dir: str | Path | None = None) -> list[Path]:
        """كل الصور بأي مسمى وأي صيغة مدعومة — لا يشترط نمط تسمية.

        exclude_dir: مجلد الحفظ — يُستبعد من المصدر دائمًا حتى لو كان
        متداخلًا داخل شجرة المصدر (سبب رئيسي لتضخم 991 ← 1200 صورة)."""
        folder = Path(folder)
        excl = None
        if exclude_dir:
            try:
                excl = Path(exclude_dir).resolve()
            except Exception:
                excl = None
        it = folder.rglob("*") if recursive else folder.iterdir()
        files = []
        for p in sorted(it):
            if not (p.is_file() and p.suffix.lower() in IMAGE_EXTS
                    and not p.name.startswith(".")):
                continue
            if excl is not None:
                try:
                    if excl == p.parent.resolve() or \
                            excl in p.parent.resolve().parents:
                        continue
                except Exception:
                    pass
            files.append(p)
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
            p = BatchRefiner._checkpoint_path(out_dir)
            if os.name == "nt" and p.exists():
                # إزالة سمة الإخفاء مؤقتًا (الكتابة فوق ملف مخفي تفشل على ويندوز)
                import ctypes
                ctypes.windll.kernel32.SetFileAttributesW(str(p), 0x80)
            p.write_text(json.dumps(done, ensure_ascii=False),
                         encoding="utf-8")
            if os.name == "nt":
                # إخفاء ملف التقدم عن المستخدم داخل مجلد الصور
                import ctypes
                ctypes.windll.kernel32.SetFileAttributesW(str(p), 0x02)
        except Exception:
            pass

    # ------------------------------------------------------------- naming
    def _fixed_name(self, stem: str) -> tuple[str, str]:
        """يعيد (الاسم المضبوط بدون امتداد، ملاحظة).

        الوضع الحر (fix_names=False أو بلا إكسل): الاسم الأصلي يُحفظ كما هو
        مهما كان المسمى — لا يُشترط أي نمط تسمية ولا ملف إكسل.
        """
        try:
            from engine_v2.naming_v2 import normalize_stem
            stem = normalize_stem(stem)
        except Exception:
            pass
        if not self.options.fix_names or not self.options.naming_enabled:
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
            if (self.options.naming_scheme or "dash") == "dash":
                from engine_v2.naming_v2 import build_name_dash
                total = self._group_total(code, unit)
                new_stem = build_name_dash(code, seq, unit, total=total)
            else:
                from engine_v2.naming_v2 import build_name
                new_stem = build_name(code, seq, unit)
        except Exception:
            new_stem = (f"{code}_{unit}" if seq <= 1
                        else f"{code}_{unit}-{seq - 1}")
        return new_stem, note

    def _group_total(self, code: str, unit: str) -> int:
        """عدد صور نفس (الصنف، الوحدة) في الدفعة — لتحديد التسلسل -1/-2 أو بدونه."""
        totals = getattr(self, "_group_totals", None)
        if not totals:
            return 1
        return int(totals.get((str(code), str(unit or "")), 1) or 1)

    def _compute_group_totals(self, files: list[Path]) -> None:
        """تمريرة مسبقة: تحصي صور كل (صنف، وحدة) ليعرف النمط dash متى يضيف -1/-2."""
        totals: dict[tuple[str, str], int] = {}
        try:
            from engine_v2.naming_v2 import normalize_stem, parse_name
        except Exception:
            self._group_totals = {}
            return
        idx = self._get_catalog()
        for p in files:
            try:
                parsed = parse_name(normalize_stem(p.stem))
            except Exception:
                parsed = None
            if not parsed or not getattr(parsed, "item", None):
                continue
            code = str(parsed.item)
            unit = (getattr(parsed, "unit", "") or "").strip()
            if idx is not None:
                try:
                    units = list(dict.fromkeys(idx.units_for_code(code)))
                except Exception:
                    units = []
                if units and unit not in units:
                    unit = units[0]
            if not unit:
                unit = "حبه"
            key = (code, unit)
            totals[key] = totals.get(key, 0) + 1
        self._group_totals = totals

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
            # حد أعلى مرفوع (3600 بدل 2400) + تصغير ذكي حافظ للنص —
            # التصغير المبكر القاسي كان يفقد مقروئية كتابات المنتج
            if max(h, w) > 3600:
                sc = 3600 / max(h, w)
                try:
                    from engine_v2.quality_v2 import smart_downscale
                    img = smart_downscale(img, int(w * sc), int(h * sc),
                                          text_aware=o.text_aware)
                except Exception:
                    img = cv2.resize(img, (int(w * sc), int(h * sc)),
                                     interpolation=cv2.INTER_AREA)

            # طمس التواريخ المطبوعة تلقائيًا (قبل القص — على الصورة الأصلية)
            if o.blur_dates:
                try:
                    from engine_v2.date_blur_v2 import auto_blur_dates
                    img, _n = auto_blur_dates(img)
                except Exception:
                    pass  # ميزة تجميلية — لا توقف المعالجة

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
                # تحسين حافظ للنص: لا denoise فوق الكتابات — تبقى الحقائق واضحة
                try:
                    if o.text_aware:
                        from engine_v2.quality_v2 import enhance_preserving_text as _enh
                    else:
                        from engine_v2.enhancement_v2 import auto_enhance as _enh
                except Exception:
                    from engine_v2.enhancement_v2 import auto_enhance as _enh
                if rgba is not None:
                    rgba[:, :, :3] = _enh(rgba[:, :, :3])
                else:
                    img = _enh(img)

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

            # تنقيح استوديو نهائي للتسليم (اختياري): حواف نظيفة + لمعة متجر
            if o.polish:
                try:
                    from engine_v2.edge_refine_v2 import polish_for_store
                    st = float(max(0.0, min(1.0, o.polish_strength)))
                    if rgba is not None:
                        p_rgb, p_a = polish_for_store(rgba[:, :, :3],
                                                      rgba[:, :, 3], st)
                        rgba[:, :, :3] = p_rgb
                        if p_a is not None:
                            rgba[:, :, 3] = p_a
                    else:
                        p_rgb, _ = polish_for_store(img, None, st)
                        img = p_rgb
                except Exception:
                    pass  # التنقيح تجميلي — لا يوقف المعالجة

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

            # الاسم المضبوط (مطبّع نهائيًا — لا شرطات مزدوجة أبدًا)
            from engine_v2.naming_v2 import normalize_stem, parse_name
            fmt = (o.out_format or "webp").lower().lstrip(".")
            if fmt in ("jpeg",):
                fmt = "jpg"
            if fmt not in ("webp", "jpg", "png"):
                fmt = "webp"
            ext = "." + fmt
            new_stem, note = self._fixed_name(src.stem)
            new_stem = normalize_stem(new_stem)
            r.new_name = new_stem + ext
            r.name_note = note
            out_path = out_dir / r.new_name
            if out_path.exists() and str(out_path) != str(src):
                # لا تولّد نسخًا مكررة: إن كان الناتج موجودًا مسبقًا لنفس الاسم
                # (تشغيل ثانٍ لنفس المجلد) نتخطاه — هذا ما سبب تضخم
                # 991 صورة إلى 1200+ بأسماء مثل `10004696_2__حبه`.
                parsed_src = parse_name(src.stem)
                if parsed_src is None and src.parent != out_dir:
                    # مصدر غير قياسي اصطدم باسم موجود: أضف لاحقة تسلسل
                    # قانونية (رقم لقطة تالٍ) بدل الشرطة المزدوجة الفاسدة.
                    counter = 2
                    cand = normalize_stem(f"{new_stem}_{counter}")
                    while (out_dir / (cand + ext)).exists():
                        counter += 1
                        cand = normalize_stem(f"{new_stem}_{counter}")
                    new_stem = cand
                    r.new_name = new_stem + ext
                    out_path = out_dir / r.new_name
                else:
                    r.output = str(out_path)
                    r.status = "skipped"
                    r.name_note = note or "موجود مسبقًا — تُخُطّي لمنع التكرار"
                    return r
            quality = int(o.compress_quality) if o.compress else int(o.webp_quality)
            if fmt == "webp":
                enc_params = [cv2.IMWRITE_WEBP_QUALITY, quality]
            elif fmt == "jpg":
                # JPG لا يدعم lossless — نقص الجودة عند 100 كحد أقصى
                enc_params = [cv2.IMWRITE_JPEG_QUALITY, min(100, quality)]
            else:  # png — بلا فقدان دائمًا؛ مستوى الضغط يؤثر في الحجم فقط
                enc_params = [cv2.IMWRITE_PNG_COMPRESSION,
                              6 if o.compress else 3]
            ok, buf = cv2.imencode(ext, final, enc_params)
            if not ok:
                r.status, r.error = "error", f"فشل ترميز {fmt.upper()}"
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
        # محرك الجودة الواعي بالنص: تصغير تدريجي + حدة تعويضية —
        # يحافظ على مقروئية كتابات المنتج والحقائق الغذائية عند التأطير
        if sc < 1 and getattr(o, "text_aware", True) and \
                (img.ndim != 3 or img.shape[2] != 4):
            try:
                from engine_v2.quality_v2 import smart_downscale
                resized = smart_downscale(img, nw, nh, text_aware=True)
            except Exception:
                resized = cv2.resize(img, (nw, nh),
                                     interpolation=cv2.INTER_AREA)
        else:
            # قناة ألفا أو تكبير: LANCZOS4 يحافظ على حدة التفاصيل
            resized = cv2.resize(img, (nw, nh),
                                 interpolation=cv2.INTER_AREA if sc < 1
                                 else cv2.INTER_LANCZOS4)
            if sc < 1 and getattr(o, "text_aware", True) and \
                    resized.ndim == 3 and resized.shape[2] == 4:
                # حدة نصية لقنوات اللون فقط مع إبقاء ألفا
                try:
                    from engine_v2.quality_v2 import adaptive_text_sharpen
                    resized[:, :, :3] = adaptive_text_sharpen(
                        resized[:, :, :3], strength=0.6)
                except Exception:
                    pass
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
        # استبعد مجلد الحفظ من المصدر دائمًا (منع إعادة معالجة النواتج)
        files = self.list_images(folder, recursive=self.options.recursive,
                                 exclude_dir=out_dir)
        done_map = self.load_checkpoint(out_dir) if resume else {}

        # تمريرة مسبقة لإحصاء صور كل (صنف، وحدة) — يلزم للنمط dash (-1/-2)
        if self.options.fix_names and self.options.naming_enabled:
            try:
                self._compute_group_totals(files)
            except Exception:
                self._group_totals = {}

        results: list[RefineItemResult] = []
        todo: list[Path] = []
        for p in files:
            key = p.name
            if resume and key in done_map:
                r = RefineItemResult(source=str(p), status="skipped",
                                     output=done_map[key].get("output", ""),
                                     new_name=done_map[key].get("new_name", ""))
                results.append(r)
                continue
            if self.options.skip_approved:
                # حماية العمل المعتمد: لا يعاد إنتاج مخرج موجود مسبقًا
                stem, _ = self._fixed_name(p.stem)
                ext = (self.options.out_format or "webp").lower().strip(".")
                existing = out_dir / f"{stem}.{ext}"
                if existing.is_file():
                    r = RefineItemResult(
                        source=str(p), status="skipped",
                        output=str(existing), new_name=existing.name,
                        error="موجود مسبقًا — محمي (معتمد)")
                    results.append(r)
                    continue
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
