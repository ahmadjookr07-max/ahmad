# -*- coding: utf-8 -*-
"""alignment_v2 — ضبط ميول واستدارة المنتج.

estimate_tilt_degrees: تقدير الميل تلقائيًا من قناع alpha (PCA/minAreaRect).
rotate_with_alpha: تدوير الصورة مع القناع بدون قص أطراف.
perspective_rectify: تصحيح منظور بأربع نقاط (8 قيم).
"""
from __future__ import annotations

import cv2
import numpy as np


def estimate_tilt_degrees(alpha: np.ndarray, max_deg: float = 12.0) -> float:
    """يقدّر ميل المنتج بالدرجات (موجب = يحتاج تدويرًا عكس عقارب الساعة)."""
    mask = (alpha > 0.5).astype(np.uint8)
    if mask.sum() < 100:
        return 0.0
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return 0.0
    cnt = max(contours, key=cv2.contourArea)
    rect = cv2.minAreaRect(cnt)
    (_, _), (w, h), angle = rect
    if w < h:
        angle = angle + 90
    # angle الآن ميل المحور الطويل عن الأفقي؛ نريد أقرب استقامة
    angle = angle % 180
    if angle > 90:
        angle -= 180
    # الميل الفعلي عن العمودي/الأفقي الأقرب
    for base in (0, 90, -90):
        d = angle - base
        if abs(d) <= 45:
            tilt = d
            break
    else:
        tilt = 0.0
    if abs(tilt) > max_deg:
        return 0.0
    return float(round(-tilt, 2))


def rotate_with_alpha(image_bgr: np.ndarray, alpha: np.ndarray,
                      degrees: float) -> tuple[np.ndarray, np.ndarray]:
    """تدوير بدون قص: يوسّع اللوحة، ويملأ الفراغ بالأبيض/شفاف."""
    if abs(degrees) < 0.05:
        return image_bgr, alpha
    h, w = image_bgr.shape[:2]
    c = (w / 2, h / 2)
    m = cv2.getRotationMatrix2D(c, degrees, 1.0)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    nw = int(h * sin + w * cos)
    nh = int(h * cos + w * sin)
    m[0, 2] += nw / 2 - c[0]
    m[1, 2] += nh / 2 - c[1]
    img_r = cv2.warpAffine(image_bgr, m, (nw, nh), flags=cv2.INTER_LANCZOS4,
                           borderMode=cv2.BORDER_CONSTANT,
                           borderValue=(255, 255, 255))
    a_r = cv2.warpAffine(alpha, m, (nw, nh), flags=cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return img_r, np.clip(a_r, 0, 1)


def perspective_rectify(image_bgr: np.ndarray,
                        corners: list[float]) -> np.ndarray:
    """تصحيح منظور: corners = [x1,y1,x2,y2,x3,y3,x4,y4] (أعلى-يسار،
    أعلى-يمين، أسفل-يمين، أسفل-يسار)."""
    if len(corners) != 8:
        return image_bgr
    src = np.array(corners, np.float32).reshape(4, 2)
    wt = int(max(np.linalg.norm(src[1] - src[0]),
                 np.linalg.norm(src[2] - src[3])))
    ht = int(max(np.linalg.norm(src[3] - src[0]),
                 np.linalg.norm(src[2] - src[1])))
    if wt < 10 or ht < 10:
        return image_bgr
    dst = np.array([[0, 0], [wt - 1, 0], [wt - 1, ht - 1], [0, ht - 1]],
                   np.float32)
    m = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(image_bgr, m, (wt, ht),
                               flags=cv2.INTER_LANCZOS4,
                               borderMode=cv2.BORDER_CONSTANT,
                               borderValue=(255, 255, 255))
