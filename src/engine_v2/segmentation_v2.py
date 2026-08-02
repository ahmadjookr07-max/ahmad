# -*- coding: utf-8 -*-
"""segmentation_v2 — القص الذكي V2 (ISNet رئيسي + u2net احتياطي).

قص حواف مثالي ناعم بلا هالات بيضاء: ISNet-general-use + snap alpha +
تنظيف مكونات + إزالة تلوث الحواف (defringe) + إزالة البقايا الخافتة.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np


@dataclass
class SegmentationResult:
    alpha: np.ndarray            # float32 0..1 بنفس أبعاد الصورة
    confidence: float
    model_name: str
    warnings: list[str] = field(default_factory=list)


class ProductSegmenterV2:
    """مُقسّم المنتجات: ISNet أولًا ثم u2net احتياطيًا."""

    _lock = threading.Lock()

    def __init__(self, model_dir: str | Path):
        self.model_dir = Path(model_dir)
        self._session = None
        self._model_name = ""
        self._input_size = 1024

    # ----------------------------------------------------------- session
    def _search_dirs(self) -> list[Path]:
        """مجلدات البحث: الممرر صراحة ثم محدد المسارات الموحد."""
        dirs = [self.model_dir, self.model_dir / "models"]
        try:
            from engine_v2.paths_v2 import models_dir
            d = Path(models_dir())
            dirs += [d, d / "models"]
        except Exception:
            pass
        out, seen = [], set()
        for d in dirs:
            k = str(d)
            if k not in seen:
                seen.add(k)
                out.append(d)
        return out

    def _find_model(self) -> Path | None:
        # ISNet أولاً (أدق حواف)، ثم u2net فالأخف u2netp للبيئات المحدودة
        for fname in ("isnet-general-use.onnx", "u2net.onnx", "u2netp.onnx"):
            for d in self._search_dirs():
                c = d / fname
                try:
                    if c.is_file():
                        return c
                except Exception:
                    continue
        return None

    def _get_session(self):
        if self._session is None:
            with self._lock:
                if self._session is None:
                    import onnxruntime as ort
                    path = self._find_model()
                    if path is None:
                        raise FileNotFoundError(
                            f"لا يوجد نموذج قص في {self.model_dir}")
                    so = ort.SessionOptions()
                    so.intra_op_num_threads = max(2, (os.cpu_count() or 4) // 2)
                    self._session = ort.InferenceSession(
                        str(path), so, providers=["CPUExecutionProvider"])
                    self._model_name = path.stem
                    self._input_size = 1024 if "isnet" in path.stem else 320
        return self._session

    # ------------------------------------------------------------ infer
    def _raw_alpha(self, image_bgr: np.ndarray) -> np.ndarray:
        sess = self._get_session()
        size = self._input_size
        h, w = image_bgr.shape[:2]
        inp = cv2.resize(image_bgr, (size, size), interpolation=cv2.INTER_AREA)
        inp = cv2.cvtColor(inp, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        if "isnet" in self._model_name:
            inp = (inp - 0.5) / 1.0
        else:
            mean = np.array([0.485, 0.456, 0.406], np.float32)
            std = np.array([0.229, 0.224, 0.225], np.float32)
            inp = (inp - mean) / std
        blob = inp.transpose(2, 0, 1)[None]
        name = sess.get_inputs()[0].name
        out = sess.run(None, {name: blob})[0]
        pred = out[0][0] if out.ndim == 4 else out[0]
        pred = (pred - pred.min()) / (pred.max() - pred.min() + 1e-8)
        alpha = cv2.resize(pred.astype(np.float32), (w, h),
                           interpolation=cv2.INTER_LINEAR)
        return np.clip(alpha, 0, 1)

    # ------------------------------------------------------- refinements
    @staticmethod
    def _snap_alpha(alpha: np.ndarray, lo: float = 0.15, hi: float = 0.85) -> np.ndarray:
        """يشد القيم المتطرفة لـ 0/1 ويبقي انتقالًا ناعمًا في الوسط."""
        out = alpha.copy()
        out[out < lo] = 0.0
        out[out > hi] = 1.0
        mid = (out >= lo) & (out <= hi)
        out[mid] = (out[mid] - lo) / (hi - lo)
        return out

    @staticmethod
    def _keep_main_components(alpha: np.ndarray, keep_ratio: float = 0.05) -> np.ndarray:
        """يبقي المكونات الكبيرة فقط (نسبة من أكبر مكون)."""
        mask = (alpha > 0.5).astype(np.uint8)
        n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        if n <= 1:
            return alpha
        areas = stats[1:, cv2.CC_STAT_AREA]
        max_area = areas.max()
        keep = np.zeros_like(mask)
        for i in range(1, n):
            if stats[i, cv2.CC_STAT_AREA] >= max_area * keep_ratio:
                keep[labels == i] = 1
        keep = cv2.dilate(keep, np.ones((15, 15), np.uint8))
        return alpha * keep.astype(np.float32)

    @staticmethod
    def _remove_faint_debris(alpha: np.ndarray) -> np.ndarray:
        """يزيل البقع الخافتة المنفصلة (ظلال/بقايا) ذات ألفا منخفض."""
        faint = ((alpha > 0.03) & (alpha < 0.45)).astype(np.uint8)
        strong = (alpha >= 0.45).astype(np.uint8)
        strong_d = cv2.dilate(strong, np.ones((25, 25), np.uint8))
        n, labels = cv2.connectedComponents(faint, 8)
        out = alpha.copy()
        for i in range(1, n):
            comp = labels == i
            if not (strong_d[comp]).any():
                out[comp] = 0.0
        return out

    @staticmethod
    def decontaminate(image_bgr: np.ndarray, alpha: np.ndarray) -> np.ndarray:
        """defringe: يسحب ألوان الحافة من الداخل لإزالة الهالة البيضاء."""
        a8 = (alpha * 255).astype(np.uint8)
        edge = cv2.Canny(a8, 40, 120)
        band = cv2.dilate(edge, np.ones((5, 5), np.uint8)) > 0
        if not band.any():
            return image_bgr
        inner = cv2.erode((alpha > 0.9).astype(np.uint8),
                          np.ones((7, 7), np.uint8)).astype(bool)
        out = image_bgr.copy()
        blurred = cv2.blur(image_bgr, (9, 9))
        mixed = (image_bgr.astype(np.float32) * 0.35 +
                 blurred.astype(np.float32) * 0.65)
        band_only = band & ~inner
        out[band_only] = np.clip(mixed[band_only], 0, 255).astype(np.uint8)
        return out

    # ------------------------------------------------------------ public
    def segment(self, image_bgr: np.ndarray) -> SegmentationResult:
        warnings: list[str] = []
        alpha = self._raw_alpha(image_bgr)
        conf = float(alpha[alpha > 0.5].mean()) if (alpha > 0.5).any() else 0.0
        alpha = self._snap_alpha(alpha)
        alpha = self._keep_main_components(alpha)
        alpha = self._remove_faint_debris(alpha)
        # نعومة نهائية خفيفة على الحواف
        alpha = cv2.GaussianBlur(alpha, (3, 3), 0)
        if conf < 0.35:
            warnings.append("ثقة القص منخفضة — راجع النتيجة يدويًا")
        return SegmentationResult(alpha=np.clip(alpha, 0, 1), confidence=conf,
                                  model_name=self._model_name, warnings=warnings)

    def compose_on_white(self, image_bgr: np.ndarray,
                         alpha: np.ndarray) -> np.ndarray:
        img = self.decontaminate(image_bgr, alpha)
        a = alpha[:, :, None]
        return np.clip(img.astype(np.float32) * a + 255.0 * (1 - a),
                       0, 255).astype(np.uint8)

    @staticmethod
    def alpha_bbox(alpha: np.ndarray, thresh: float = 0.05):
        ys, xs = np.where(alpha > thresh)
        if len(xs) == 0:
            return None
        return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())
