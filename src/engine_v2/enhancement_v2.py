# -*- coding: utf-8 -*-
"""enhancement_v2 — التحسين التلقائي V2.

auto_enhance: توازن أبيض + CLAHE + تباين + unsharp محدود بلا هالات + denoise
+ descreen لصور الشاشات (moiré). يحافظ على الدقة والألوان الطبيعية.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class EnhanceSettings:
    white_balance: bool = True
    clahe_clip: float = 1.6
    contrast: float = 1.06
    sharpen_amount: float = 0.55
    denoise: bool = True
    descreen: bool = True


def _is_screen_photo(gray: np.ndarray) -> bool:
    """كشف moiré/شبكة الشاشة عبر طاقة الترددات العالية الدورية."""
    small = cv2.resize(gray, (256, 256), interpolation=cv2.INTER_AREA)
    f = np.fft.fftshift(np.abs(np.fft.fft2(small.astype(np.float32))))
    f = np.log1p(f)
    c = 128
    ring = f[c - 90:c + 90, c - 90:c + 90].copy()
    ring[60:120, 60:120] = 0
    return float(ring.mean()) > 8.2


def _white_balance(img: np.ndarray) -> np.ndarray:
    """Gray-world مخفف على القناة a/b في LAB."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    a_mean = lab[:, :, 1].mean()
    b_mean = lab[:, :, 2].mean()
    lab[:, :, 1] -= (a_mean - 128) * 0.6
    lab[:, :, 2] -= (b_mean - 128) * 0.6
    return cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)


def auto_enhance(img: np.ndarray,
                 settings: EnhanceSettings | None = None) -> np.ndarray:
    s = settings or EnhanceSettings()
    out = img.copy()
    gray = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)

    # descreen لصور الشاشات
    if s.descreen and _is_screen_photo(gray):
        out = cv2.medianBlur(out, 3)
        out = cv2.GaussianBlur(out, (3, 3), 0)

    if s.white_balance:
        out = _white_balance(out)

    # CLAHE على قناة L فقط
    lab = cv2.cvtColor(out, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=s.clahe_clip, tileGridSize=(8, 8))
    l = clahe.apply(l)
    out = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)

    # تباين خفيف
    if s.contrast != 1.0:
        out = np.clip((out.astype(np.float32) - 127.5) * s.contrast + 127.5,
                      0, 255).astype(np.uint8)

    # denoise خفيف يحافظ على الحواف
    if s.denoise:
        out = cv2.bilateralFilter(out, 5, 28, 28)

    # unsharp محدود (بلا هالات: قناع حواف)
    if s.sharpen_amount > 0:
        blur = cv2.GaussianBlur(out, (0, 0), 1.6)
        sharp = cv2.addWeighted(out, 1 + s.sharpen_amount, blur,
                                -s.sharpen_amount, 0)
        edges = cv2.Canny(cv2.cvtColor(out, cv2.COLOR_BGR2GRAY), 40, 130)
        edge_mask = cv2.dilate(edges, np.ones((3, 3), np.uint8))
        edge_mask = cv2.GaussianBlur(edge_mask, (5, 5), 0).astype(np.float32) / 255.0
        m = edge_mask[:, :, None]
        out = np.clip(sharp.astype(np.float32) * m +
                      out.astype(np.float32) * (1 - m), 0, 255).astype(np.uint8)
    return out


def enhance_nutrition_label(img: np.ndarray) -> np.ndarray:
    """تحسين قوي لجداول حقائق التغذية: تكبير + إزالة ضوضاء + تباين نص."""
    h, w = img.shape[:2]
    if max(h, w) < 1200:
        sc = 1200 / max(h, w)
        img = cv2.resize(img, (int(w * sc), int(h * sc)),
                         interpolation=cv2.INTER_CUBIC)
    img = cv2.fastNlMeansDenoisingColored(img, None, 5, 5, 7, 21)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.4, tileGridSize=(8, 8))
    l = clahe.apply(l)
    img = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)
    blur = cv2.GaussianBlur(img, (0, 0), 1.2)
    return cv2.addWeighted(img, 1.5, blur, -0.5, 0)
