"""قارئ باركود خطي سريع ومتسامح للصور البعيدة أو المائلة.

لا يعيد هذه الوحدة أي QR أو أي رمز ثنائي الأبعاد؛ النتيجة مقتصرة على
EAN/UPC/Code128/Code39/ITF/Codabar. تُستدعى فقط كخطة احتياطية بعد القارئ
الأصلي، لتبقى الدفعات العادية سريعة.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Iterable
import os

import cv2
import numpy as np


_2D_MARKERS = ("qr", "data", "aztec", "pdf", "maxi", "micro")
_LINEAR_MARKERS = (
    "ean", "upc", "code_128", "code128", "code_39", "code39",
    "code_93", "code93", "itf", "codabar", "rss", "gs1",
)


def _read_unicode(path: str | Path) -> np.ndarray | None:
    try:
        raw = np.fromfile(os.fspath(path), dtype=np.uint8)
        return cv2.imdecode(raw, cv2.IMREAD_COLOR)
    except Exception:
        return None


def _is_linear(result: object) -> bool:
    fmt = str(getattr(result, "format", "")).strip().lower()
    normalized = fmt.replace("-", "_").replace(" ", "_")
    if any(marker in normalized for marker in _2D_MARKERS):
        return False
    return any(marker in normalized for marker in _LINEAR_MARKERS)


def _clean_text(text: object) -> str:
    value = str(text or "").strip().replace(" ", "").replace("-", "")
    # أرقام EAN/UPC/GTIN قد تصل بأرقام عربية في بعض مصادر الصور.
    return value.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))


def _looks_usable(text: str) -> bool:
    if len(text) < 6 or len(text) > 64:
        return False
    # أرقام الباركود القياسية، أو Code128/39 الصناعي (حروف وأرقام فقط).
    return text.isdigit() or text.replace("_", "").isalnum()


def _resize_for_scan(image: np.ndarray, target_longest: int) -> np.ndarray:
    h, w = image.shape[:2]
    longest = max(h, w)
    if longest == target_longest:
        return image
    scale = target_longest / float(max(1, longest))
    method = cv2.INTER_CUBIC if scale > 1.0 else cv2.INTER_AREA
    return cv2.resize(image, (max(1, round(w * scale)), max(1, round(h * scale))),
                      interpolation=method)


def _barcode_regions(image: np.ndarray) -> Iterable[np.ndarray]:
    """يستخرج مناطق ذات خطوط متوازية شبيهة بالباركود الخطي.

    هذا لا يقرأ QR ولا يبحث عنه: يعتمد على تباين الخطوط الرأسية ونسبة العرض
    إلى الارتفاع، ثم يرسل قصاصات صغيرة للقارئ. يفيد الباركود البعيد والملتوي
    ويخفض كلفة مسح صورة المنتج كاملة مرارًا.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    h, w = gray.shape[:2]
    if h < 80 or w < 80:
        return
    grad = cv2.Sobel(gray, cv2.CV_16S, 1, 0, ksize=3)
    grad = cv2.convertScaleAbs(grad)
    grad = cv2.GaussianBlur(grad, (5, 5), 0)
    binary = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 7))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
    binary = cv2.erode(binary, None, iterations=1)
    binary = cv2.dilate(binary, None, iterations=2)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    ranked = []
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        if bw < 45 or bh < 12 or bw * bh < 800:
            continue
        ratio = max(bw / max(1, bh), bh / max(1, bw))
        if ratio < 1.35:
            continue
        ranked.append((bw * bh * ratio, x, y, bw, bh))
    for _, x, y, bw, bh in sorted(ranked, reverse=True)[:5]:
        pad_x, pad_y = max(12, bw // 5), max(12, bh * 2)
        x0, y0 = max(0, x - pad_x), max(0, y - pad_y)
        x1, y1 = min(w, x + bw + pad_x), min(h, y + bh + pad_y)
        crop = image[y0:y1, x0:x1]
        if crop.size:
            yield crop


def _candidate_regions(image: np.ndarray) -> Iterable[np.ndarray]:
    """يرتب المناطق الأكثر احتمالًا للباركود قبل المسح الكامل المكلف."""
    h, w = image.shape[:2]
    # نبدأ بالمناطق المرشحة هندسيًا، ثم نلجأ إلى مسح الصورة والسفلي.
    yield from _barcode_regions(image)
    yield image
    if h < 80 or w < 80:
        return
    top = h // 3
    yield image[top:, :]
    yield image[h // 2:, :]
    for x0, x1 in ((0, w * 2 // 3), (w // 6, w * 5 // 6), (w // 3, w)):
        yield image[top:, x0:x1]


def _variants(region: np.ndarray) -> Iterable[np.ndarray]:
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.4, tileGridSize=(8, 8)).apply(gray)
    sharp = cv2.addWeighted(clahe, 1.8, cv2.GaussianBlur(clahe, (0, 0), 1.2), -0.8, 0)
    otsu = cv2.threshold(sharp, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    yield region
    yield clahe
    yield sharp
    yield otsu


def _rotations(image: np.ndarray, include_fine: bool) -> Iterable[np.ndarray]:
    yield image
    yield cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    yield cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    if not include_fine:
        return
    h, w = image.shape[:2]
    for angle in (-12, 12, -24, 24):
        matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        yield cv2.warpAffine(image, matrix, (w, h), flags=cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_REPLICATE)


def _read_variant(zxingcpp: object, image: np.ndarray) -> list[str]:
    values: list[str] = []
    try:
        # formats=AllLinear يمنع QR وكل الرموز الثنائية من أصل الفحص،
        # وليس مجرد تصفيتها بعد القراءة. تدوير/عكس/تصغير داخلي للمكتبة.
        formats = getattr(getattr(zxingcpp, "BarcodeFormat", None), "AllLinear", None)
        if formats is None:
            # توافق مع بيئات الاختبار/الإصدارات القديمة فقط. تبقى نتيجة QR
            # مرفوضة صراحةً أدناه؛ أما الإصدار المضمّن فيستخدم AllLinear.
            results = zxingcpp.read_barcodes(image)
        else:
            results = zxingcpp.read_barcodes(
                image,
                formats=formats,
                try_rotate=True,
                try_downscale=True,
                try_invert=True,
            )
    except Exception:
        return values
    for result in results:
        if not _is_linear(result):
            continue
        text = _clean_text(getattr(result, "text", ""))
        if _looks_usable(text):
            values.append(text)
    return values


def read_linear_barcodes(path: str | Path, *, max_attempts: int = 38) -> tuple[str, ...]:
    """يعيد مرشحات الباركود الخطي مرتبة بالثقة، ولا يقرأ QR مطلقًا."""
    try:
        import zxingcpp
    except Exception:
        return ()
    image = _read_unicode(path)
    if image is None:
        return ()

    # التدرج مهم: مسح اقتصادي أولًا، ثم توسعة للباركود البعيد إن لم يظهر شيء.
    votes: Counter[str] = Counter()
    attempts = 0
    for scan_size, fine_angles in ((1200, False), (1900, True)):
        base = _resize_for_scan(image, scan_size)
        for region in _candidate_regions(base):
            if region.size == 0:
                continue
            for variant in _variants(region):
                for rotated in _rotations(variant, fine_angles):
                    votes.update(_read_variant(zxingcpp, rotated))
                    attempts += 1
                    # تكرار القراءة يزيد الثقة ويوقف المسح مبكرًا.
                    if votes and max(votes.values()) >= 2:
                        return tuple(v for v, _ in votes.most_common())
                    if attempts >= max_attempts:
                        break
                if attempts >= max_attempts:
                    break
            if attempts >= max_attempts:
                break
        if votes:
            return tuple(v for v, _ in votes.most_common())
    return ()
