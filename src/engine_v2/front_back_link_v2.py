"""ربط آمن لصور وجهي المنتج عبر OCR واسم الصنف في الإكسل.

لا يعتمد القرار على كلمة عامة واحدة. يلزم توقيع متعدد العناصر من العلامة
والوصف الفارق والوزن أو العدد إن وُجد؛ وكل نتيجة دون الثقة أو فارق الحسم
المطلوبين تُرفض وتبقى للمراجعة اليدوية.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable

__all__ = [
    "TextSignature", "NameMatch", "normalize_text", "make_signature",
    "match_product_name", "extract_product_ocr", "extract_weight_hints",
]

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_ARABIC_FOLD = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي",
    "ئ": "ي", "ؤ": "و", "ة": "ه", "ـ": " ",
})
_DIACRITICS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]")
_TOKEN_RE = re.compile(r"[a-zA-Z\u0600-\u06ff]+|\d+(?:[.,]\d+)?")

# ترجمات متواضعة للفئات الشائعة، تُستعمل فقط كإشارة مساندة لا كقرار منفرد.
_EQUIVALENTS = {
    "sugar": "سكر", "albayt": "البيت", "albait": "البيت", "rice": "ارز", "tea": "شاي", "flour": "طحين",
    "milk": "حليب", "oil": "زيت", "tuna": "تونه", "tomato": "طماطم",
    "البيث": "البيت", "الببت": "البيت", "البيتت": "البيت",
    "white": "ابيض", "fine": "ناعم", "black": "اسود", "red": "احمر",
    "green": "اخضر", "salt": "ملح", "coffee": "قهوه", "water": "ماء",
}
_GENERIC = {
    "منتج", "السعوديه", "عربي", "arabia", "saudi", "made", "food",
    "foods", "quality", "premium", "سكر", "ارز", "شاي", "حليب", "زيت",
    "طحين", "تونه", "product", "natural", "white", "fine", "sugar",
}
_UNIT_MAP = {
    "كجم": "kg", "كيلو": "kg", "كيلوجرام": "kg", "kg": "kg", "kgs": "kg",
    "جم": "g", "جرام": "g", "غ": "g", "g": "g", "gr": "g",
    "مل": "ml", "مليلتر": "ml", "ml": "ml",
    "لتر": "l", "litre": "l", "liter": "l", "l": "l",
    "اونز": "oz", "oz": "oz",
    "كيس": "bag", "اكياس": "bag", "ظرف": "sachet", "اظرف": "sachet",
    "حبه": "piece", "حبة": "piece", "قطعة": "piece", "piece": "piece",
    "pcs": "piece", "pc": "piece", "pack": "pack",
}


@dataclass(frozen=True)
class TextSignature:
    tokens: frozenset[str]
    key_tokens: frozenset[str]
    quantities: frozenset[tuple[str, str]]
    normalized: str


@dataclass(frozen=True)
class NameMatch:
    accepted: bool
    score: float
    margin: float
    shared_tokens: tuple[str, ...]
    quantity_match: bool
    reason: str
    record: object | None = None


def normalize_text(value: object) -> str:
    text = str(value or "").translate(_ARABIC_DIGITS).translate(_ARABIC_FOLD).casefold()
    text = _DIACRITICS.sub("", text)
    text = text.replace("×", " x ").replace("*", " x ")
    text = re.sub(r"[^a-z0-9\u0600-\u06ff.,]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _canonical(token: str) -> str:
    token = token.strip(".,").casefold()
    if token in _EQUIVALENTS:
        return _EQUIVALENTS[token]
    return token


def _tokens(text: str) -> list[str]:
    out: list[str] = []
    for value in _TOKEN_RE.findall(normalize_text(text)):
        value = _canonical(value)
        if len(value) >= 2 or value.isdigit():
            out.append(value)
    return out


def _quantity_signature(text: str) -> frozenset[tuple[str, str]]:
    source = normalize_text(text)
    # افصل الرقم والوحدة حتى لو ألصقهما OCR مثل 5kg أو 100كيس.
    pattern = re.compile(
        r"(\d+(?:[.,]\d+)?)\s*(كجم|كيلو(?:جرام)?|kg|kgs|جم|جرام|غ|gr|g|"
        r"مل|مليلتر|ml|لتر|lit(?:er|re)?|l|اونز|oz|كيس|اكياس|ظرف|اظرف|"
        r"حبه|حبة|قطعة|piece|pcs?|pack)")
    values: set[tuple[str, str]] = set()
    for number, raw_unit in pattern.findall(source):
        unit = _UNIT_MAP.get(raw_unit, raw_unit)
        number = number.replace(",", ".")
        try:
            value = float(number)
            if unit == "g" and value >= 1000:
                value, unit = value / 1000.0, "kg"
            values.add((f"{value:g}", unit))
        except ValueError:
            continue
    return frozenset(values)


def make_signature(text: object) -> TextSignature:
    normalized = normalize_text(text)
    tokens = frozenset(_tokens(normalized))
    # الوحدة والرقم يقاسان منفصلين في quantities؛ لا نعدّ «كجم» كلمة
    # اسم فارقة وإلا خفضت ثقة تطابق اسم صحيح عند قراءة الوزن بصيغة أخرى.
    key = frozenset(t for t in tokens if t not in _GENERIC and t not in _UNIT_MAP
                    and not t.isdigit() and len(t) >= 3)
    return TextSignature(tokens=tokens, key_tokens=key,
                         quantities=_quantity_signature(normalized),
                         normalized=normalized)


def _similar_token(token: str, candidates: Iterable[str]) -> str | None:
    if len(token) < 4:
        return None
    best, best_score = None, 0.0
    for candidate in candidates:
        if len(candidate) < 4:
            continue
        score = SequenceMatcher(None, token, candidate).ratio()
        if score > best_score:
            best, best_score = candidate, score
    # OCR العربي يبدّل أحيانًا حرفًا واحدًا في العلامة (البيث/البيت).
    # لا نستخدم التشابه وحده؛ هو مجرد كلمة من عدة كلمات لازمة للقبول.
    return best if best_score >= 0.78 else None


def _score(query: TextSignature, expected: TextSignature) -> tuple[float, tuple[str, ...], bool]:
    direct = set(query.key_tokens & expected.key_tokens)
    # تصحيح هادئ لأخطاء OCR: كلمة قريبة تعدّ كدليل واحد، ولا تضاعف الدليل.
    unmatched_query = query.key_tokens - direct
    unmatched_expected = set(expected.key_tokens - direct)
    fuzzy: set[str] = set()
    for token in unmatched_query:
        near = _similar_token(token, unmatched_expected)
        if near:
            fuzzy.add(near)
            unmatched_expected.discard(near)
    shared = direct | fuzzy
    expected_keys = max(1, len(expected.key_tokens))
    coverage = len(shared) / expected_keys
    precision = len(shared) / max(1, len(query.key_tokens))
    text_score = 0.72 * coverage + 0.28 * precision

    if expected.quantities:
        shared_quantities = query.quantities & expected.quantities
        # لا نثق بالوزن إذا أعاد OCR عدة أرقام مختلفة للوحدة نفسها؛ هذا
        # شائع في الأغلفة اللامعة، وقد يحوّل 5 كجم إلى 2/3/5 كجم معًا.
        expected_units = {unit for _, unit in expected.quantities}
        query_same_kind = {(value, unit) for value, unit in query.quantities
                           if unit in expected_units}
        quantity_ok = bool(shared_quantities) and len(query_same_kind) == len(shared_quantities)
        # إذا ظهر رقم/وحدة مختلف صراحةً أو أكثر من رقم للوحدة نفسها، نرفض
        # إسناد الحجم تلقائيًا ونبقي الصورة للمراجعة اليدوية.
        same_kind_conflict = bool(query_same_kind - shared_quantities)
        quantity_score = 1.0 if quantity_ok else (0.0 if same_kind_conflict else 0.35)
        score = 0.70 * text_score + 0.30 * quantity_score
    else:
        quantity_ok = True
        score = text_score
    return score, tuple(sorted(shared)), quantity_ok


def _record_name(record: object) -> str:
    return str(getattr(record, "product_name", "") or getattr(record, "name", "") or "")


def match_product_name(ocr_text: str, records: Iterable[object], *,
                       accept_threshold: float = 0.84,
                       ambiguity_margin: float = 0.16) -> NameMatch:
    """يطابق OCR مع سجلات الإكسل بحارس أمان لا يسمح بكلمة عامة وحيدة."""
    query = make_signature(ocr_text)
    if len(query.key_tokens) < 2:
        return NameMatch(False, 0.0, 0.0, (), False, "OCR لا يحمل كلمتين فارقتين", None)
    # قد يملك الصنف عدة باركودات وصفوفًا مكررة في الإكسل؛ نجمعها تحت
    # رقم الصنف حتى لا يصنع التكرار تعادلًا زائفًا ويمنع مطابقة صحيحة.
    best_by_item: dict[str, tuple[float, tuple[str, ...], bool, object]] = {}
    for record in records:
        expected = make_signature(_record_name(record))
        if not expected.key_tokens:
            continue
        score, shared, quantity_ok = _score(query, expected)
        # لا نعتمد تطابقًا قائمًا على كلمة واحدة حتى لو كان عالي التشابه.
        if len(shared) < 2:
            score *= 0.45
        key = str(getattr(record, "item_code", "") or _record_name(record))
        prior = best_by_item.get(key)
        if prior is None or score > prior[0]:
            best_by_item[key] = (score, shared, quantity_ok, record)
    ranked = list(best_by_item.values())
    if not ranked:
        return NameMatch(False, 0.0, 0.0, (), False, "لا توجد مرشحات", None)
    ranked.sort(key=lambda row: row[0], reverse=True)
    best_score, shared, quantity_ok, record = ranked[0]
    next_score = ranked[1][0] if len(ranked) > 1 else 0.0
    margin = best_score - next_score
    expected = make_signature(_record_name(record))
    if len(shared) < 2:
        return NameMatch(False, best_score, margin, shared, quantity_ok,
                         "أقل من كلمتين فارقتين متطابقتين", record)
    if expected.quantities and not quantity_ok:
        return NameMatch(False, best_score, margin, shared, quantity_ok,
                         "الوزن أو العدد غير مؤكد", record)
    if best_score < accept_threshold:
        return NameMatch(False, best_score, margin, shared, quantity_ok,
                         "الثقة دون الحد", record)
    # حين تتطابق ثلاث كلمات فارقة أو أكثر ومعها الوزن/العدد ذاته، يكون
    # التوقيع كاملاً عمليًا؛ نسمح بفارق أصغر قليلًا عن مرشح قريب بدل رفض
    # صورة صحيحة بلا داعٍ. أما دون ذلك فتبقى عتبة الالتباس الصارمة.
    required_margin = 0.10 if len(shared) >= 3 and quantity_ok else ambiguity_margin
    if margin < required_margin:
        return NameMatch(False, best_score, margin, shared, quantity_ok,
                         "الفرق عن المرشح التالي صغير", record)
    return NameMatch(True, best_score, margin, shared, quantity_ok,
                     "مطابقة متعددة العناصر موثوقة", record)


def _quantity_hints_from_positions(region, pytesseract, data=None, *, psm: int = 11) -> list[str]:
    """يبني تلميحات وزن/عدد من كلمات متقاربة مكانيًا في الصورة.

    Tesseract قد يقرأ «5» و«KG» كسطرين متباعدين في النص الناتج رغم أنهما
    متجاوران على الغلاف، لذا لا نثق بترتيب النص وحده.
    """
    if data is None:
        try:
            from pytesseract import Output
            data = pytesseract.image_to_data(
                region, lang="ara+eng", config=f"--psm {psm}", output_type=Output.DICT)
        except Exception:
            return []
    words = []
    for index, raw in enumerate(data.get("text", [])):
        value = normalize_text(raw)
        if not value:
            continue
        try:
            conf = float(data.get("conf", ["-1"])[index])
        except (ValueError, IndexError):
            conf = -1.0
        # نحتفظ بإشارات الوزن الضعيفة أيضًا؛ لا تُستعمل وحدها في قرار
        # الربط بل مع علامتين نصيتين فارقتين، وهذا يعالج لمعان أغلفة الأكياس.
        if conf < 0:
            continue
        try:
            x = float(data["left"][index]); y = float(data["top"][index])
            w = float(data["width"][index]); h = float(data["height"][index])
        except (KeyError, IndexError, ValueError):
            continue
        words.append((value, x + w / 2, y + h / 2, max(w, h)))
    numerals = [(word, x, y, size) for word, x, y, size in words
                if re.fullmatch(r"\d+(?:[.,]\d+)?", word)]
    # لا نعد الحرف l أو g وحدة منفردة هنا؛ ضوضاء OCR تخلطهما بالأرقام.
    # لكن KG ومل وجرام وعبوات/أكياس إشارات قوية بما يكفي لإسناد الرقم.
    strong_units = {"كجم", "كيلو", "kg", "kgs", "جرام", "gr", "ml", "مل", "لتر", "oz", "اونز", "كيس", "اكياس", "ظرف", "اظرف", "حبه", "حبة", "قطعة", "pack"}
    units = [(word, x, y, size) for word, x, y, size in words if word in strong_units]
    hints: list[str] = []
    for number, nx, ny, ns in numerals:
        if not 0 < float(number.replace(",", ".")) <= 999:
            continue
        for unit, ux, uy, us in units:
            # الرقم والوحدة قد يقطعهما OCR إلى سطرين؛ نطاق التلميح واسع
            # عمداً، لكنه لا يكفي للربط من دون كلمات اسم متعددة.
            limit = max(260.0, 8.0 * max(ns, us))
            if abs(nx - ux) <= limit and abs(ny - uy) <= limit:
                hints.append(f"{number} {unit}")
    return hints


def _foreground_crop(image):
    """يقص المنتج المركزي عن أرضية التصوير قبل OCR.

    GrabCut هنا لا يستبدل عزل الإنتاج النهائي؛ دوره فقط تقليل بلاط الخلفية
    والانعكاسات أثناء قراءة اسم المنتج ووزنه.
    """
    import cv2
    import numpy as np
    if image is None or image.size == 0:
        return image
    h, w = image.shape[:2]
    if h < 120 or w < 120:
        return image
    mask = np.zeros((h, w), np.uint8)
    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    try:
        rect = (int(w * .07), int(h * .05), int(w * .86), int(h * .91))
        cv2.grabCut(image, mask, rect, bgd, fgd, 2, cv2.GC_INIT_WITH_RECT)
        fg = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
        count, _, stats, _ = cv2.connectedComponentsWithStats(fg)
        if count <= 1:
            return image
        idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        x, y, bw, bh, area = stats[idx]
        if area < h * w * .08:
            return image
        pad = max(10, int(min(bw, bh) * .025))
        return image[max(0, y - pad):min(h, y + bh + pad),
                     max(0, x - pad):min(w, x + bw + pad)]
    except Exception:
        return image


def extract_weight_hints(image, *, expected_quantities: Iterable[tuple[str, str]] = (),
                         max_longest: int = 1500) -> tuple[str, ...]:
    """يقرأ الرقم والوحدة من مناطق وزن محتملة بعد نجاح جزء الاسم.

    لا يُستدعى في كل الصور: يستخدمه الرابط فقط عندما تتشابه العلامة والنوع
    بين عدة أحجام. وهذا يحافظ على السلاسة ويمنع رقمًا عشوائيًا من ترجيح صنف.
    """
    import cv2
    try:
        import pytesseract
    except Exception:
        return ()
    if image is None:
        return ()
    image = _foreground_crop(image)
    h, w = image.shape[:2]
    scale = min(1.5, max_longest / float(max(1, h, w)))
    if scale != 1.0:
        image = cv2.resize(image, (round(w * scale), round(h * scale)),
                           interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)
    h, w = image.shape[:2]
    # أوزان وأعداد العبوات تظهر غالبًا في أحد هذه المواضع على واجهة الغلاف.
    boxes = (
        (.12, .28, .47, .68), (.45, .28, .88, .68),
        (.12, .55, .88, .88), (.12, .08, .88, .42),
    )
    found: list[str] = []
    raw_numbers: list[str] = []
    strong_confirmed: list[str] = []
    # نطبع أوزان الإكسل مرة واحدة ونستخدمها كقائمة بيضاء. وجودها يعني أن
    # رقم OCR لا يكفي بذاته: لا نقبل إلا وزنًا/وحدة معروفين لهذا السياق.
    expected: set[tuple[str, str]] = set()
    for number, unit in expected_quantities:
        try:
            canonical_unit = _UNIT_MAP.get(normalize_text(unit), normalize_text(unit))
            expected.add((f"{float(str(number).replace(',', '.')):g}", canonical_unit))
        except (TypeError, ValueError):
            continue
    for x0, y0, x1, y1 in boxes:
        roi = image[int(h * y0):int(h * y1), int(w * x0):int(w * x1)]
        if roi.size == 0:
            continue
        roi = cv2.resize(roi, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        variants = (gray, cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1])
        for variant in variants:
            for psm in (6, 11):
                try:
                    from pytesseract import Output
                    data = pytesseract.image_to_data(
                        variant, lang="eng", config="--psm %d" % psm,
                        output_type=Output.DICT)
                except Exception:
                    continue
                found.extend(_quantity_hints_from_positions(
                    variant, pytesseract, data=data, psm=psm))
                # في شارات الوزن يقرأ Tesseract «5» و«KG» كسطرين؛ النص
                # المباشر يحتفظ بهذا التجاور أفضل من جدول الكلمات أحيانًا.
                try:
                    raw = pytesseract.image_to_string(
                        variant, lang="eng", config="--psm %d" % psm)
                except Exception:
                    raw = ""
                raw = raw.replace("O", "0").replace("o", "0")
                for raw_number in re.findall(r"\d+(?:[.,]\d+)?", raw):
                    try:
                        value = float(raw_number.replace(',', '.'))
                        if 0 < value <= 999 and (not expected or any(number == f"{value:g}" for number, _ in expected)):
                            raw_numbers.append(f"{value:g}")
                    except ValueError:
                        pass
                # قد يظهر وصف صغير بين الرقم والوحدة داخل الشارة (مثل
                # «5 / Net weight / KG»)، لذا نقبل الفصل المحدود بعد تكرار
                # النتيجة في تمرير آخر.
                pairs = re.findall(r"(\d+(?:[.,]\d+)?)\s*(kg|kgs|ml|oz)", raw, re.I)
                pairs += re.findall(r"(\d+(?:[.,]\d+)?)(?:\D{1,20}?)(kg|kgs|ml|oz)", raw, re.I)
                for number, unit in pairs:
                    canonical_unit = _UNIT_MAP.get(unit.lower(), unit.lower())
                    try:
                        canonical_number = f"{float(number.replace(',', '.')):g}"
                        found.append(f"{canonical_number} {canonical_unit}")
                    except ValueError:
                        continue
                    # قد يدمج Tesseract الرقم الكبير مع زخرفة/حرف مجاور، مثل
                    # «551 KG» بدلاً من «5 KG». ما دام يتلوه نوع وحدة واضح
                    # وكان رقم إكسل واحد فقط بادئة له، نستعيده كدليل موضعي قوي.
                    if expected and canonical_unit:
                        matching = [expected_number for expected_number, expected_unit in expected
                                    if expected_unit == canonical_unit
                                    and len(expected_number) < len(canonical_number)
                                    and canonical_number.startswith(expected_number)]
                        if len(matching) == 1:
                            strong_confirmed.append(f"{matching[0]} {canonical_unit}")
    # قد تأتي قراءة «551 kg» من جدول الكلمات المكاني لا النص المتسلسل؛
    # نطبق استعادة البادئة ذاتها عليها لأنها اقترنت بوحدة واضحة وبموضع قريب.
    if expected:
        for hint in found:
            for observed_number, observed_unit in _quantity_signature(hint):
                matching = [expected_number for expected_number, expected_unit in expected
                            if expected_unit == observed_unit
                            and len(expected_number) < len(observed_number)
                            and observed_number.startswith(expected_number)]
                if len(matching) == 1:
                    strong_confirmed.append(f"{matching[0]} {observed_unit}")
    # لا نثق إلا بتلميح تكرر في تمريرين مستقلين؛ الرقم العشوائي مرة واحدة
    # لا يجوز أن ينقل صورة إلى حجم صنف آخر.
    from collections import Counter
    counts = Counter(found)
    confirmed = [value for value, count in counts.items() if count >= 2]
    # الرقم الكبير قد يُقرأ بوضوح لكن الوحدة لا يلتقطها OCR؛ نسمح بضمها
    # فقط إذا كانت وحدة متوقعة في مرشحات الإكسل، وظهر الرقم مرتين مستقلتين.
    for number, count in Counter(raw_numbers).items():
        if count < 2:
            continue
        for expected_number, expected_unit in expected:
            if number == expected_number:
                confirmed.append(f"{number} {expected_unit}")
    # قراءة وحدة صريحة بجوار رقم مشوّه أقوى من رقم منفرد التقط من الزخارف؛
    # إن وُجدت نعيد هذه الإشارة وحدها حتى لا تنافسها أرقام عشوائية.
    if strong_confirmed:
        return tuple(dict.fromkeys(strong_confirmed))
    # نعتمد الزوج الدقيق (الرقم والوحدة) عند توفر بيانات الإكسل، فلا تتحول
    # قراءة خاطئة مثل 4 kg أو 5 g إلى تعارض مع وزن 5 kg الصحيح.
    if expected:
        filtered: list[str] = []
        for hint in confirmed:
            signature = _quantity_signature(hint)
            if signature & expected:
                filtered.append(hint)
        confirmed = filtered
    return tuple(dict.fromkeys(confirmed))


def extract_product_ocr(image, *, max_longest: int = 1800) -> str:
    """OCR سريع نسبيًا لصورة المنتج؛ يدمج تمريرين لتخفيف ضياع النص."""
    import cv2
    try:
        import pytesseract
    except Exception:
        return ""
    if image is None:
        return ""
    image = _foreground_crop(image)
    h, w = image.shape[:2]
    scale = min(1.8, max_longest / float(max(1, h, w)))
    if scale != 1.0:
        image = cv2.resize(image, (round(w * scale), round(h * scale)),
                           interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    # نص العلامة على الأغلفة يكون غالبًا أبيض/فاتح فوق لون قوي. قناعه يزيل
    # انعكاس البلاط ويقرأ «ALBAYT / سكر / ناعم» بوضوح أعلى من الصورة كاملة.
    if image.ndim == 3:
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        text_mask = cv2.inRange(hsv, (0, 0, 130), (180, 155, 255))
        # إن لم يوجد نص فاتح كافٍ نعود للصورة المحسنة المعتادة.
        ocr_image = text_mask if cv2.countNonZero(text_mask) > text_mask.size * .012 else clahe
    else:
        ocr_image = clahe
    # تمريرة Tesseract واحدة فقط: image_to_data يعيد النص وإحداثياته معًا.
    try:
        from pytesseract import Output
        data = pytesseract.image_to_data(
            ocr_image, lang="ara+eng", config="--psm 11", output_type=Output.DICT)
    except Exception:
        return ""
    # لا نمرر الأرقام/الوحدات الخام: لمعان الغلاف ينتج أوزانًا متضاربة.
    # وزن المنتج يُضاف لاحقًا من extract_weight_hints بعد تحقق الاسم جزئيًا.
    words = [str(v) for v in data.get("text", []) if str(v).strip()]
    words = [w for w in words if not re.fullmatch(r"[\d.,]+|kg|kgs|ml|oz|g|l", w, re.I)]
    return "\n".join(words)
