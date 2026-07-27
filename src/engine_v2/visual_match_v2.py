# -*- coding: utf-8 -*-
"""visual_match_v2 — الربط الذكي بالتشابه البصري وكشف التكرارات بالمحتوى.

الخوارزميات (خفيفة وسريعة — بلا نماذج ثقيلة):
- بصمة إدراكية pHash (DCT 32×32 → 64 بت) لكشف الصور المتطابقة والمكررة.
- مدرج ألوان HSV مُطبَّع + مقارنة correlation لكشف صور نفس المنتج
  من زوايا مختلفة (الوجه الأمامي/الخلفي).
- suggest_links: يقترح ربط الصور غير المرتبطة بأصناف الصور المرتبطة
  مع درجة ثقة لكل اقتراح.
- find_content_duplicates: يكشف التكرارات حتى لو اختلفت الأسماء.
"""
from __future__ import annotations

import cv2
import numpy as np
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["phash", "hamming", "color_signature", "color_similarity",
           "ImageSignature", "build_signature", "pair_similarity",
           "suggest_links", "find_content_duplicates"]


# ------------------------------------------------------------------ pHash
def phash(img: np.ndarray) -> int:
    """بصمة إدراكية 128 بت (dHash + aHash) — مستقرة أمام التحجيم
    وضغط JPEG. dHash يلتقط التدرجات المحلية وaHash السطوع العام."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    blur = cv2.GaussianBlur(gray, (3, 3), 0)   # ثبات أمام ضوضاء JPEG
    # dHash: فروقات أفقية على شبكة 9×8
    d = cv2.resize(blur, (9, 8), interpolation=cv2.INTER_AREA)
    dbits = (d[:, 1:] > d[:, :-1]).flatten()
    # aHash: مقارنة بالمتوسط على شبكة 8×8
    a = cv2.resize(blur, (8, 8), interpolation=cv2.INTER_AREA)
    abits = (a > a.mean()).flatten()
    # cHash: بصمة لونية — قناتا a/b من Lab على شبكة 4×8 لكل قناة
    if img.ndim == 3:
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        ca = cv2.resize(lab[..., 1], (8, 4), interpolation=cv2.INTER_AREA)
        cb = cv2.resize(lab[..., 2], (8, 4), interpolation=cv2.INTER_AREA)
        cbits = np.concatenate([(ca > ca.mean()).flatten(),
                                (cb > cb.mean()).flatten()])
    else:
        cbits = np.zeros(64, dtype=bool)
    h = 0
    for b in np.concatenate([dbits, abits, cbits]):
        h = (h << 1) | int(b)
    return h


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


# --------------------------------------------------------- color signature
def color_signature(img: np.ndarray, mask: np.ndarray | None = None
                    ) -> np.ndarray:
    """مدرج HSV مُطبَّع (يتجاهل الخلفية البيضاء تلقائيًا إن لم يوجد قناع)."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    if mask is None:
        # استبعد الأبيض/الفاتح جدًا (خلفيات النتائج) والحواف السوداء
        s, v = hsv[..., 1], hsv[..., 2]
        mask = (((s > 25) | (v < 235)) & (v > 15)).astype(np.uint8) * 255
    hist = cv2.calcHist([hsv], [0, 1], mask, [24, 8],
                        [0, 180, 0, 256])
    cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
    return hist.flatten()


def color_similarity(sig_a: np.ndarray, sig_b: np.ndarray) -> float:
    """تشابه 0..1 عبر correlation."""
    a = sig_a.reshape(-1, 1).astype(np.float32)
    b = sig_b.reshape(-1, 1).astype(np.float32)
    val = cv2.compareHist(a, b, cv2.HISTCMP_CORREL)
    return float(max(0.0, min(1.0, (val + 1) / 2 if val < 0 else val)))


# ------------------------------------------------------------- signatures
@dataclass
class ImageSignature:
    path: str = ""
    ph: int = 0
    color: np.ndarray = field(default_factory=lambda: np.zeros(192,
                                                               np.float32))
    ok: bool = False


def build_signature(path: str | Path, img: np.ndarray | None = None
                    ) -> ImageSignature:
    sig = ImageSignature(path=str(path))
    try:
        if img is None:
            data = np.fromfile(str(path), dtype=np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is None:
            return sig
        # صغّر للسرعة — يكفي 256 عرضًا
        h, w = img.shape[:2]
        if max(h, w) > 256:
            scale = 256 / max(h, w)
            img = cv2.resize(img, (int(w * scale), int(h * scale)),
                             interpolation=cv2.INTER_AREA)
        sig.ph = phash(img)
        sig.color = color_signature(img)
        sig.ok = True
    except Exception:
        pass
    return sig


def pair_similarity(a: ImageSignature, b: ImageSignature) -> float:
    """درجة تشابه مدمجة 0..1 بين صورتين."""
    if not (a.ok and b.ok):
        return 0.0
    ham = hamming(a.ph, b.ph)
    ph_score = max(0.0, 1.0 - ham / 64.0)      # 192 بت — نطاق أوسع
    col_score = color_similarity(a.color, b.color)
    # وجهان لنفس المنتج: ألوان متشابهة جدًا وإن اختلف الشكل
    return round(0.45 * ph_score + 0.55 * col_score, 3)


# -------------------------------------------------------------- suggestions
def suggest_links(unlinked: list[ImageSignature],
                  linked: dict[str, list[ImageSignature]],
                  threshold: float = 0.62) -> list[dict]:
    """يقترح لكل صورة غير مرتبطة أفضل صنف مرشح.

    unlinked: بصمات الصور غير المرتبطة.
    linked: {item_code: [بصمات صور الصنف المرتبطة]}
    يعيد قائمة {path, item_code, score, level_ar} مرتبة بالثقة.
    """
    out: list[dict] = []
    for sig in unlinked:
        best_code, best_score = "", 0.0
        for code, sigs in linked.items():
            for ref in sigs:
                s = pair_similarity(sig, ref)
                if s > best_score:
                    best_code, best_score = code, s
        if best_code and best_score >= threshold:
            level = ("عالية جدًا" if best_score >= 0.85 else
                     "عالية" if best_score >= 0.74 else "متوسطة")
            out.append({"path": sig.path, "item_code": best_code,
                        "score": best_score, "level_ar": level})
    out.sort(key=lambda d: d["score"], reverse=True)
    return out


def find_content_duplicates(sigs: list[ImageSignature],
                            max_distance: int = 12) -> list[list[str]]:
    """مجموعات الصور المتطابقة بالمحتوى (حتى لو اختلفت الأسماء)."""
    n = len(sigs)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for i in range(n):
        if not sigs[i].ok:
            continue
        for j in range(i + 1, n):
            if not sigs[j].ok:
                continue
            if hamming(sigs[i].ph, sigs[j].ph) <= max_distance:
                union(i, j)
    groups: dict[int, list[str]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(sigs[i].path)
    return [g for g in groups.values() if len(g) > 1]
