# -*- coding: utf-8 -*-
"""dialogue — قناة الحوار العربية بين المستخدم والبرنامج.

المستخدم يكتب بالعربية الطبيعية ما يريد، فيفهم البرنامج **النية** ويحوّلها
إلى تعديل فعلي على نفسه: قيمة إعداد، أو رقعة في بنية الكود، أو إجراء
تشخيصي. لا حاجة لمعرفة اسم إعداد ولا مكان زر.

## لماذا مُطابق نوايا محلي لا نموذج لغوي؟
ثلاثة أسباب قاطعة: (1) التطبيق يعمل على أجهزة بلا إنترنت في المتاجر،
والوعد أن يفهم دائمًا؛ (2) صور المستخدم وأسماء أصنافه لا تُرسل خارجًا،
وإرسال نص طلبه قد يكشف أسماء منتجاته؛ (3) الاستجابة يجب أن تكون فورية
(< 50 مللي) لأن الحقل داخل الواجهة. النموذج اللغوي — إن توفر ووافق
المالك — يعمل **مُكمّلًا** عند تعذّر الفهم المحلي فقط، لا بديلًا.

## معمارية الفهم: ثلاث مراحل
1. **التطبيع** (`normalize`): العربية تُكتب بصور كثيرة لنفس الكلمة
   (أ/إ/آ/ا، ى/ي، ة/ه، التشكيل، التطويل، الأرقام الهندية ٠١٢).
   بلا تطبيع يفشل «اعمل جوده اعلى» رغم وضوحه.
2. **المطابقة الموزونة**: كل نية لها مُشغّلات (triggers) بأوزان، وشروط
   منع (blockers). الدرجة = مجموع أوزان المُشغّلات المطابقة. هذا أدق من
   «أول نمط يطابق» لأن «لا تشغّل الظل» و«شغّل الظل» يتشاركان كلمة الظل.
3. **استخراج المعاملات**: أرقام («الجودة 95»)، أبعاد («800×700»)،
   كلمات كمية («أعلى/أقل/أسرع»)، ومسارات مجلدات.

## النفي: أخطر ما في الفهم العربي
«شغّل الظل» و«لا تشغّل الظل» يختلفان بحرفين ويعنيان العكس تمامًا.
`_polarity()` يكشف النفي (لا، بدون، ألغِ، أوقف، عطّل، ما أريد) ويقلب
القيمة المنطقية. وبلا هذا يفعل البرنامج نقيض ما طُلب — وهو أسوأ من
عدم الفهم، لأن المستخدم يفقد الثقة كليًا.

## الأمان
كل نية لها `risk`. ما كان `safe` وثقته عالية يُنفَّذ فورًا؛ وما كان
`moderate` أو `invasive` (كتعديل بنية الكود) يُرجع **بطاقة تأكيد**
فيها شرح عربي وdiff، فلا يُطبَّق شيء خطير دون موافقة صريحة.
كل تنفيذ يُسجَّل في `changes.jsonl` ويمكن التراجع بـ«تراجع».
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from . import identity, journal

with contextlib.suppress(Exception):
    from . import ledger as _ledger_mod

_LOCK = threading.RLock()


# ═══════════════════ تطبيع النص العربي ═══════════════════

_DIACRITICS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")
_TATWEEL = "\u0640"

# الأرقام العربية-الهندية والفارسية → لاتينية
_DIGIT_MAP = {ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")}
_DIGIT_MAP.update({ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")})

_LETTER_MAP = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
    "ى": "ي", "ئ": "ي", "ﻯ": "ي",
    "ة": "ه",
    "ؤ": "و",
    "ک": "ك", "گ": "ك",
    "ی": "ي",
})


def normalize(text: str) -> str:
    """يوحّد صور الحرف العربي ليصير النص قابلًا للمطابقة.

    «اَلْجَوْدَة» و«الجوده» و«الجودة» تصبح كلها «الجوده». بلا هذه الخطوة
    تفشل المطابقة على نص إنسان حقيقي يكتب بسرعة وبلا تشكيل.
    """
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", str(text))
    t = _DIACRITICS.sub("", t)
    t = t.replace(_TATWEEL, "")
    t = t.translate(_DIGIT_MAP)
    t = t.translate(_LETTER_MAP)
    t = re.sub(r"[^\w\s\u0600-\u06FF×xX*/.,%:\-+]", " ", t)
    # علامات الترقيم العربية تقع في مدى العربية فتنجو من التنقية
    # أعلاه، وتُفسد حدود الكلمة: «من انت؟» لم تطابق «من انت»
    # لأن «؟» (U+061F) حرف عربي في نظر النمط.
    t = re.sub(r"[\u060C\u061B\u061F\u0640\u066A-\u066D\u06D4]", " ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip().lower()


# ═════════════════ المطابقة بحدود الكلمة ═════════════════

# بادئات تتصل بالكلمة في العربية دون مسافة: الجوده، والجوده، بالجوده
_PREFIX = r"(?:ال|و|ف|ب|ل|وال|فال|بال|لل|وب|ول)?"
# لواصق تُلحق بالفعل/الاسم: تسويها، سرعته، جودتها
_SUFFIX = r"(?:ها|هم|هن|ه|ي|ك|نا|ون|ين|ات|ان)?"
_TRIG_CACHE: dict[str, re.Pattern] = {}


def _trigger_re(pattern: str) -> re.Pattern:
    """يبني مُطابقًا يحترم حدود الكلمة مع البادئات المتصلة.

    موطن عطب حقيقي وقع: المطابقة بـ``in`` الساذجة تجعل المثير
    القصير «نت» يُطابَق داخل كلمة «انت»، فتُفهم «مين انت؟»
    أمرًا بتغيير سياسة الشبكة — وهذا خطر: سؤال بريء يُفعّل
    إعدادًا. ومنه أيضًا «رجع» داخل «مرجع»، و«ظل» داخل «ظلام».
    لذا نُلزم بداية كلمة حقيقية، مع السماح ببادئة متصلة ولاحقة
    ضمير، فالعربية لا تفصل الأداة عن الاسم بمسافة.
    """
    hit = _TRIG_CACHE.get(pattern)
    if hit is not None:
        return hit
    words = [w for w in pattern.split() if w]
    if not words:
        rx = re.compile(r"(?!)")            # لا يُطابق شيئًا
        _TRIG_CACHE[pattern] = rx
        return rx
    parts = []
    for i, w in enumerate(words):
        esc = re.escape(w)
        if i == 0:
            parts.append(rf"{_PREFIX}{esc}")
        else:
            parts.append(esc)
    # اللاحقة تُسمح فقط بعد الكلمة الأخيرة
    body = r"\s+".join(parts) + _SUFFIX
    rx = re.compile(rf"(?<![\w\u0600-\u06FF]){body}(?![\w\u0600-\u06FF])")
    _TRIG_CACHE[pattern] = rx
    return rx


def _matches(pattern: str, text: str) -> bool:
    """هل يرد المفتاح كلمةً مستقلة في النص المطبّع؟"""
    return bool(_trigger_re(normalize(pattern)).search(text))


# ═══════════════════ النفي والاتجاه ═══════════════════

_NEG = ("لا ", "لا_", "بلا", "بدون", "الغ", "ألغ", "اوقف", "أوقف", "عطل",
        "ايقاف", "إيقاف", "توقف", "امنع", "اخف", "احذف", "شيل", "لاتريد",
        "ماريد", "ما اريد", "مااريد", "لااريد", "لا اريد", "مب", "مش", "غير مفعل")
_POS = ("شغل", "فعل", "اعمل", "ابدا", "ثبت", "اضف", "خل", "اريد", "ابغى",
        "ابغا", "احتاج", "طبق", "مكن", "مفعل")

_MORE = ("اكثر", "اعلى", "ازيد", "زد", "زود", "ارفع", "كبر", "اسرع", "افضل", "احسن")
_LESS = ("اقل", "اخفض", "قلل", "نقص", "صغر", "ابطا", "خفف", "انقص")


def _polarity(t: str) -> bool | None:
    """هل الطلب إثبات أم نفي؟ ``None`` إن لم يظهر أي منهما.

    النفي يُفحَص أولًا: «لا تشغّل الظل» تحتوي «شغل» أيضًا، فلو بدأنا
    بالإثبات لقلبنا معنى الجملة رأسًا على عقب.
    """
    for n in _NEG:
        if n in t:
            return False
    for p in _POS:
        if p in t:
            return True
    return None


def _direction(t: str) -> int:
    """+1 زيادة، -1 نقصان، 0 لا اتجاه — لطلبات بلا رقم صريح."""
    if any(w in t for w in _MORE):
        return 1
    if any(w in t for w in _LESS):
        return -1
    return 0


# ═══════════════════ استخراج المعاملات ═══════════════════

_RE_DIMS = re.compile(r"(\d{2,5})\s*[×xX*\u0640]\s*(\d{2,5})")
_RE_NUM = re.compile(r"(\d+(?:[.,]\d+)?)")
_RE_PCT = re.compile(r"(\d{1,3})\s*%")


def _numbers(t: str) -> list[float]:
    out = []
    for m in _RE_NUM.finditer(t):
        with contextlib.suppress(ValueError):
            out.append(float(m.group(1).replace(",", ".")))
    return out


def _dims(t: str) -> tuple[int, int] | None:
    m = _RE_DIMS.search(t)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _folder(raw: str) -> str:
    """يستخرج مسار مجلد من النص الأصلي (لا المطبَّع، فالتطبيع يفسد المسارات)."""
    m = re.search(r"[A-Za-z]:[\\/][^\"'،؛]+", raw)
    if m:
        return m.group(0).strip()
    m = re.search(r"(?:^|\s)(/[^\s\"'،؛]+)", raw)
    return m.group(1).strip() if m else ""


# ═══════════════════ تعريف النوايا ═══════════════════

SAFE, MODERATE, INVASIVE = "safe", "moderate", "invasive"
KIND_SETTING, KIND_ACTION, KIND_PATCH, KIND_QUERY = (
    "setting", "action", "code_patch", "query")


@dataclass
class IntentSpec:
    """وصف نية: كيف تُكتشف، ما خطرها، وكيف تُنفَّذ."""
    key: str
    title_ar: str
    kind: str
    risk: str
    triggers: tuple            # (نمط, وزن)
    blockers: tuple = ()       # كلمات تُلغي هذه النية
    needs: tuple = ()          # معاملات إلزامية
    setting_key: str = ""      # مفتاح التجاوز المقابل
    action: str = ""           # اسم الإجراء


@dataclass
class Intent:
    """نتيجة الفهم: نية واحدة بمعاملاتها وشرحها العربي."""
    key: str = ""
    title_ar: str = ""
    kind: str = ""
    risk: str = SAFE
    confidence: float = 0.0
    params: dict = field(default_factory=dict)
    explain_ar: str = ""
    needs_confirmation: bool = True
    alternatives: list = field(default_factory=list)
    raw: str = ""

    @property
    def understood(self) -> bool:
        return bool(self.key) and self.confidence >= 0.35

    def as_dict(self) -> dict:
        return {
            "key": self.key, "title_ar": self.title_ar, "kind": self.kind,
            "risk": self.risk, "confidence": round(self.confidence, 3),
            "params": self.params, "explain_ar": self.explain_ar,
            "needs_confirmation": self.needs_confirmation,
            "alternatives": self.alternatives, "understood": self.understood,
        }


# المفردات كما يكتبها مستخدم حقيقي في متجر، لا كما يكتبها مهندس.
SPECS: tuple = (
    IntentSpec(
        key="output_quality", title_ar="جودة المخرجات", kind=KIND_SETTING,
        risk=SAFE, setting_key="output_quality",
        triggers=(("جوده", 3), ("جودة", 3), ("دقه", 2), ("وضوح", 2),
                  ("نقاء", 1), ("quality", 3), ("اوضح", 3), ("واضح", 2),
                  ("مش واضح", 3), ("مبهم", 2), ("مشوش", 3), ("مطموس", 2),
                  ("رديءه", 2), ("رديه", 2), ("نقيه", 2), ("حاده", 1)),
        blockers=("سرعه", "بطي"),
    ),
    IntentSpec(
        key="output_size", title_ar="مقاس الصورة الناتجة", kind=KIND_SETTING,
        risk=SAFE, setting_key="output_size",
        triggers=(("مقاس", 3), ("حجم الصوره", 3), ("ابعاد", 3), ("قياس", 2),
                  ("عرض", 1), ("ارتفاع", 1), ("size", 2), ("بكسل", 2)),
    ),
    IntentSpec(
        key="output_format", title_ar="صيغة الملف الناتج", kind=KIND_SETTING,
        risk=SAFE, setting_key="output_format",
        triggers=(("صيغه", 3), ("امتداد", 2), ("webp", 3), ("png", 3),
                  ("jpg", 3), ("jpeg", 3), ("نوع الملف", 3)),
    ),
    IntentSpec(
        key="shadow", title_ar="الظل أسفل المنتج", kind=KIND_SETTING,
        risk=SAFE, setting_key="shadow_enabled",
        triggers=(("ظل", 3), ("shadow", 3), ("ظلال", 3)),
    ),
    IntentSpec(
        key="enhance", title_ar="تحسين الصورة", kind=KIND_SETTING,
        risk=SAFE, setting_key="enhance_enabled",
        triggers=(("تحسين", 3), ("تحسن", 2), ("حده", 2), ("سطوع", 2),
                  ("الوان", 2), ("enhance", 3)),
    ),
    IntentSpec(
        key="blur_dates", title_ar="طمس تواريخ الإنتاج", kind=KIND_SETTING,
        risk=SAFE, setting_key="blur_dates",
        triggers=(("تاريخ", 3), ("تواريخ", 3), ("انتهاء", 2), ("صلاحيه", 2),
                  ("طمس", 3), ("blur", 2)),
    ),
    IntentSpec(
        key="nutrition", title_ar="جدول القيم الغذائية", kind=KIND_SETTING,
        risk=SAFE, setting_key="nutrition_mode",
        triggers=(("غذائ", 3), ("تغذيه", 3), ("جدول القيم", 3),
                  ("سعرات", 2), ("مكونات", 2), ("nutrition", 3)),
    ),
    IntentSpec(
        key="naming", title_ar="نمط تسمية الملفات", kind=KIND_SETTING,
        risk=SAFE, setting_key="naming_pattern",
        triggers=(("تسميه", 3), ("اسم الملف", 3), ("سم الملفات", 3),
                  ("رقم الصنف", 2), ("باركود", 2), ("naming", 2)),
        blockers=("قراءه الباركود", "يقرا الباركود"),
    ),
    IntentSpec(
        key="speed", title_ar="سرعة المعالجة", kind=KIND_SETTING,
        risk=SAFE, setting_key="batch_workers",
        triggers=(("سرعه", 3), ("اسرع", 3), ("بطي", 3), ("بطء", 3),
                  ("خيوط", 2), ("توازي", 2), ("معالجه اسرع", 3),
                  ("ياخذ وقت", 2), ("طويل", 1)),
    ),
    IntentSpec(
        key="ui_scale", title_ar="حجم عناصر الواجهة", kind=KIND_SETTING,
        risk=SAFE, setting_key="ui_scale",
        triggers=(("الخط صغير", 3), ("كبر الخط", 3), ("حجم الخط", 3),
                  ("الواجهه صغيره", 3), ("كبر الواجهه", 3), ("تكبير", 2),
                  ("زوم", 2), ("ما اشوف", 2)),
    ),
    IntentSpec(
        key="output_folder", title_ar="مجلد المخرجات", kind=KIND_SETTING,
        risk=MODERATE, setting_key="output_dir",
        triggers=(("مجلد", 3), ("فولدر", 3), ("مسار الحفظ", 3),
                  ("احفظ في", 3), ("مكان الحفظ", 3)),
        needs=("path",),
    ),
    IntentSpec(
        key="diagnose", title_ar="تشخيص وإصلاح ذاتي", kind=KIND_ACTION,
        risk=SAFE, action="diagnose_heal",
        triggers=(("افحص", 3), ("تشخيص", 3), ("فحص", 3), ("اصلح", 3),
                  ("صلح", 3), ("راجع نفسك", 3), ("داوي نفسك", 3),
                  ("مشكله", 2), ("خلل", 2), ("عطل", 2), ("خربان", 2),
                  ("ما يعمل", 3), ("لا يعمل", 3), ("توقف", 2),
                  ("ما يشتغل", 3), ("ما يفتح", 3), ("وقف", 2)),
        blockers=("عدل بنيتك", "عدل الكود", "اصلح الكود", "عدل نفسك",
                  "عدل البرمجه", "جراحه"),
    ),
    IntentSpec(
        key="introspect", title_ar="بطاقة الوعي", kind=KIND_QUERY,
        risk=SAFE, action="introspect",
        triggers=(("من انت", 5), ("مين انت", 5), ("منو انت", 5),
                  ("عرفني بنفسك", 5), ("عرفني عن نفسك", 5),
                  ("ايش تسوي", 4), ("وش تسوي", 4), ("وش تقدر", 4),
                  ("ايش تقدر", 4), ("شو تسوي", 4), ("ماذا تفعل", 4),
                  ("ماذا تستطيع", 4), ("ما تستطيع", 3),
                  ("حالتك", 3), ("قدراتك", 4), ("قدرات", 3),
                  ("هدفك", 4), ("وعيك", 4), ("عن نفسك", 4),
                  ("من تكون", 4), ("تعرف نفسك", 4),
                  ("مهمتك", 3), ("وظيفتك", 3), ("تخصصك", 3)),
        blockers=("من انت المجلد",),
    ),
    IntentSpec(
        key="report", title_ar="تقرير مفصّل", kind=KIND_QUERY,
        risk=SAFE, action="report",
        triggers=(("تقرير", 3), ("سجل", 2), ("احصائيات", 3),
                  ("ماذا تعلمت", 3), ("ايش تعلمت", 3), ("تاريخ", 1)),
    ),
    IntentSpec(
        key="optimize", title_ar="تحسين الأداء ذاتيًا", kind=KIND_ACTION,
        risk=MODERATE, action="self_improve",
        triggers=(("حسن نفسك", 4), ("طور نفسك", 4), ("حسن الاداء", 3),
                  ("تحسين ذاتي", 4), ("optimize", 3), ("خفف الاستهلاك", 2)),
    ),
    IntentSpec(
        key="code_fix", title_ar="تعديل بنية الكود", kind=KIND_PATCH,
        risk=INVASIVE, action="operate",
        triggers=(("عدل الكود", 4), ("عدل بنيتك", 4), ("اصلح الكود", 4),
                  ("جراحه", 3), ("عدل نفسك", 4), ("رقعه", 3),
                  ("عدل البرمجه", 3)),
    ),
    IntentSpec(
        key="undo", title_ar="التراجع عن آخر تعديل", kind=KIND_ACTION,
        risk=SAFE, action="undo",
        triggers=(("تراجع", 4), ("رجع", 3), ("الغ التعديل", 4),
                  ("undo", 3), ("ارجع كما كنت", 4), ("خرب", 2)),
    ),
    IntentSpec(
        key="white_bg", title_ar="الخلفية البيضاء", kind=KIND_SETTING,
        risk=SAFE, setting_key="white_background",
        triggers=(("خلفيه بيضا", 4), ("خلفيه بيضاء", 4),
                  ("خلفيه", 3), ("بياض الخلفيه", 4),
                  ("ازاله الخلفيه", 3), ("background", 3),
                  ("ارضيه بيضا", 3), ("الخلفيه بيضا", 4)),
    ),
    IntentSpec(
        key="smart_cutout", title_ar="القص الذكي", kind=KIND_SETTING,
        risk=SAFE, setting_key="smart_cutout_enabled",
        triggers=(("القص الذكي", 5), ("قص ذكي", 4), ("قص", 3),
                  ("عزل المنتج", 4), ("عزل الخلفيه", 4),
                  ("تفريغ الخلفيه", 4), ("cutout", 3),
                  ("يقطع المنتج", 3), ("قص المنتج", 4)),
    ),
    IntentSpec(
        key="network_policy", title_ar="سياسة الاتصال بالشبكة", kind=KIND_SETTING,
        risk=MODERATE, setting_key="network_policy",
        triggers=(("انترنت", 4), ("شبكه", 3), ("النت", 3), ("اتصال", 2),
                  ("اونلاين", 3), ("network", 2), ("وايفاي", 3)),
        blockers=("من انت", "مين انت", "منو انت"),
    ),
)

_SPEC_BY_KEY = {s.key: s for s in SPECS}


# ═══════════════════ المُفسِّر ═══════════════════

class Interpreter:
    """يحوّل جملة عربية إلى `Intent` قابل للتنفيذ."""

    def understand(self, text: str) -> Intent:
        raw = str(text or "")
        t = normalize(raw)
        if not t:
            return Intent(explain_ar="لم أتلقَّ نصًا. اكتب ما تريد بالعربية.",
                          raw=raw)

        scored: list[tuple[float, IntentSpec]] = []
        for spec in SPECS:
            if any(_matches(b, t) for b in spec.blockers):
                continue
            score = sum(w for pat, w in spec.triggers if _matches(pat, t))
            if score > 0:
                scored.append((score, spec))

        if not scored:
            # لا كلمة مفتاحية، لكن قد يكون النص مجرد أبعاد أو نسبة
            if _RE_DIMS.search(t):
                return self._build(_SPEC_BY_KEY["output_size"], t, raw, 0.85)
            if _RE_PCT.search(t):
                return self._build(_SPEC_BY_KEY["output_quality"], t, raw, 0.6)
            return self._unknown(raw, t)

        scored.sort(key=lambda x: -x[0])
        top_score, spec = scored[0]
        # أبعاد صريحة «800×700» تحسم النية حتى بلا كلمة «مقاس»
        if _RE_DIMS.search(t) and spec.key != "output_size":
            spec, top_score = _SPEC_BY_KEY["output_size"], 6
        # الثقة: نسبة الدرجة إلى سقف معقول، مع خفضها إن نافسها بديل قريب
        conf = min(1.0, top_score / 6.0)
        if len(scored) > 1 and scored[1][0] >= top_score * 0.8:
            conf *= 0.72
        alts = [s.title_ar for _, s in scored[1:3]]

        intent = self._build(spec, t, raw, conf)
        intent.alternatives = alts
        journal.debug("dialogue_understood", key=intent.key,
                      confidence=round(intent.confidence, 2))
        return intent

    # ── بناء المعاملات والشرح لكل نية ──
    def _build(self, spec: IntentSpec, t: str, raw: str, conf: float) -> Intent:
        it = Intent(key=spec.key, title_ar=spec.title_ar, kind=spec.kind,
                    risk=spec.risk, confidence=conf, raw=raw)
        pol, direction, nums = _polarity(t), _direction(t), _numbers(t)
        builder = getattr(self, f"_p_{spec.key}", None)
        if builder:
            builder(it, t, raw, pol, direction, nums)
        else:
            it.params = {"value": pol if pol is not None else True}
            it.explain_ar = f"سأضبط «{spec.title_ar}»."

        for need in spec.needs:
            if not it.params.get(need):
                it.confidence *= 0.4
                it.explain_ar += " لكن لم أتبيّن القيمة المطلوبة بدقة."
        it.needs_confirmation = not (
            spec.risk == SAFE and it.confidence >= 0.72
            and spec.kind in (KIND_SETTING, KIND_QUERY, KIND_ACTION))
        if spec.kind == KIND_QUERY:
            it.needs_confirmation = False
        return it

    # جودة: رقم صريح، أو نسبة، أو اتجاه
    def _p_output_quality(self, it, t, raw, pol, d, nums):
        val = None
        pct = _RE_PCT.search(t)
        if pct:
            val = int(pct.group(1))
        elif nums:
            cand = [n for n in nums if 1 <= n <= 100]
            if cand:
                val = int(cand[0])
        if val is None:
            cur = _current("output_quality", 92)
            val = min(100, cur + 5) if d >= 0 else max(60, cur - 10)
        val = max(50, min(100, int(val)))
        it.params = {"value": val}
        it.explain_ar = (
            f"سأرفع جودة الصور الناتجة إلى {val}%. "
            "الجودة الأعلى تعني ملفات أكبر قليلًا ووضوحًا أدق في التفاصيل.")

    def _p_output_size(self, it, t, raw, pol, d, nums):
        dims = _dims(t)
        if dims:
            w, h = dims
        elif len([n for n in nums if n >= 100]) >= 2:
            big = [int(n) for n in nums if n >= 100][:2]
            w, h = big[0], big[1]
        elif nums and max(nums) >= 100:
            w = h = int(max(nums))
        else:
            cw, ch = _current("output_size", [800, 700])
            f = 1.25 if d >= 0 else 0.8
            w, h = int(cw * f), int(ch * f)
        w, h = max(200, min(6000, w)), max(200, min(6000, h))
        it.params = {"width": w, "height": h}
        it.explain_ar = (f"سأجعل مقاس الصورة الناتجة {w}×{h} بكسل. "
                         "الإطار يُعاد حسابه تلقائيًا ليبقى المنتج متمركزًا.")

    def _p_output_format(self, it, t, raw, pol, d, nums):
        fmt = next((f for f in ("webp", "png", "jpeg", "jpg") if f in t), "")
        fmt = {"jpg": "jpeg"}.get(fmt, fmt) or "webp"
        it.params = {"value": fmt}
        why = {"webp": "أصغر حجمًا بنفس الجودة وهي الأنسب للنشر",
               "png": "بلا فقدان مع دعم الشفافية",
               "jpeg": "متوافقة مع كل الأنظمة القديمة"}[fmt]
        it.explain_ar = f"سأحفظ المخرجات بصيغة {fmt.upper()} — {why}."

    def _p_shadow(self, it, t, raw, pol, d, nums):
        on = pol if pol is not None else (d >= 0)
        it.params = {"value": bool(on)}
        it.explain_ar = ("سأُضيف ظلًا طبيعيًا أسفل المنتج ليبدو قائمًا على سطح."
                         if on else "سأُلغي الظل فتظهر الصورة على خلفية نقية.")

    def _p_enhance(self, it, t, raw, pol, d, nums):
        on = pol if pol is not None else (d >= 0)
        it.params = {"value": bool(on)}
        it.explain_ar = ("سأُفعّل التحسين الواعي بالنص: حدة وسطوع محسوبان "
                         "دون إتلاف الكتابات على العلبة."
                         if on else "سأُوقف التحسين وأُخرج الصورة كما هي.")

    def _p_blur_dates(self, it, t, raw, pol, d, nums):
        on = pol if pol is not None else True
        it.params = {"value": bool(on)}
        it.explain_ar = ("سأطمس تواريخ الإنتاج والانتهاء تلقائيًا حتى تصلح "
                         "الصورة للنشر مدة أطول."
                         if on else "سأترك التواريخ ظاهرة كما هي في الصورة.")

    def _p_nutrition(self, it, t, raw, pol, d, nums):
        if any(w in t for w in ("احذف", "شيل", "ازل", "امسح", "remove")):
            mode, why = "remove", "سأحذف جدول القيم الغذائية من الصورة"
        elif pol is False:
            mode, why = "none", "سأتجاهل جدول القيم الغذائية تمامًا"
        else:
            mode, why = "auto", ("سأقرأ جدول القيم الغذائية تلقائيًا وأُعيد "
                                 "رسمه بخط عربي واضح")
        it.params = {"value": mode}
        it.explain_ar = why + "."

    def _p_naming(self, it, t, raw, pol, d, nums):
        if "باركود" in t:
            pat, why = "barcode", "الباركود المقروء من الصورة"
        elif any(w in t for w in ("رقم الصنف", "الصنف", "الكود")):
            pat, why = "item_code", "رقم الصنف من ملف الإكسل"
        elif "اسم" in t and "منتج" in t:
            pat, why = "product_name", "اسم المنتج من الإكسل"
        else:
            pat, why = "item_code", "رقم الصنف من ملف الإكسل"
        it.params = {"value": pat}
        it.explain_ar = f"سأُسمّي كل ملف ناتج بـ{why}."

    def _p_speed(self, it, t, raw, pol, d, nums):
        cur = _current("batch_workers", max(2, (os.cpu_count() or 4) // 2))
        want_faster = d >= 0 and not any(w in t for w in _LESS)
        val = int(nums[0]) if nums and 1 <= nums[0] <= 32 else (
            min((os.cpu_count() or 4), cur + 2) if want_faster else max(1, cur - 1))
        it.params = {"value": val, "faster": want_faster}
        it.explain_ar = (
            f"سأجعل عدد العمّال المتوازين {val}. "
            + ("التوازي الأعلى يسرّع الدفعة، وسأقيس الأثر فعليًا وأتراجع "
               "إن تبيّن أنه أبطأ على جهازك." if want_faster else
               "التوازي الأقل يخفّف الحمل على الجهاز ويجعل الواجهة أسلس."))

    def _p_ui_scale(self, it, t, raw, pol, d, nums):
        cur = float(_current("ui_scale", 1.0))
        if nums and 50 <= nums[0] <= 250:
            val = round(nums[0] / 100.0, 2)
        else:
            val = round(cur + (0.15 if d >= 0 else -0.15), 2)
        val = max(0.7, min(2.0, val))
        it.params = {"value": val}
        it.explain_ar = (f"سأضبط حجم الواجهة على {int(val * 100)}% "
                         "فتكبر الخطوط والأزرار دون قطع أي نص.")

    def _p_output_folder(self, it, t, raw, pol, d, nums):
        path = _folder(raw)
        it.params = {"path": path}
        it.explain_ar = (f"سأحفظ المخرجات في «{path}» بعد التأكد أنه قابل للكتابة."
                         if path else
                         "أفهم أنك تريد تغيير مجلد الحفظ، لكن اكتب المسار كاملًا.")

    def _p_diagnose(self, it, t, raw, pol, d, nums):
        it.params = {"auto": True}
        it.explain_ar = ("سأفحص نفسي بالكامل: الحزم والنماذج والقرص والذاكرة "
                         "والصلاحيات، ثم أُصلح كل ما يمكن إصلاحه بنفسي وأخبرك "
                         "بما تعذّر ولماذا.")

    def _p_introspect(self, it, t, raw, pol, d, nums):
        it.explain_ar = "سأعرض بطاقة وعيي: من أنا، وهدفي، وحالتي، وقدراتي الآن."

    def _p_report(self, it, t, raw, pol, d, nums):
        it.explain_ar = ("سأعرض تقريرًا بما مرّ بي: الأعطال التي تكررت، "
                         "والعلاجات التي نجحت، والتحسينات التي ثبّتها بنفسي.")

    def _p_optimize(self, it, t, raw, pol, d, nums):
        it.params = {"aggressive": any(w in t for w in ("قوي", "كامل", "بشده"))}
        it.explain_ar = ("سأبدأ دورة تحسين ذاتي: أقيس أدائي الحالي، أُجرّب "
                         "تعديلًا واحدًا، أقيس أثره، فأُثبّته إن نفع وأتراجع "
                         "عنه إن ضرّ.")

    def _p_code_fix(self, it, t, raw, pol, d, nums):
        it.params = {"dry_run": True}
        it.explain_ar = ("سأفحص بنية شفرتي وأستخرج مواضع الضعف، وأعرض عليك "
                         "الفرق (diff) قبل تطبيق أي تعديل. لا أُعدّل حرفًا "
                         "قبل موافقتك، ولكل تعديل نسخة تراجع.")

    def _p_undo(self, it, t, raw, pol, d, nums):
        it.explain_ar = "سأتراجع عن آخر تعديل أجريته وأُعيد الحالة السابقة."

    def _p_network_policy(self, it, t, raw, pol, d, nums):
        if pol is False:
            val, why = "off", "لن أتصل بالشبكة إطلاقًا؛ سأعمل بمعرفتي المحلية"
        elif any(w in t for w in ("موارد", "نماذج", "تحميل", "حزم")):
            val, why = ("resources_only",
                        "سأتصل فقط لتنزيل ما ينقصني من حزم ونماذج")
        else:
            val, why = "full", ("سأتصل لتنزيل ما ينقصني والاستفادة من السجل "
                                "المعرفي في حل الأعطال المجهولة")
        it.params = {"value": val}
        it.explain_ar = why + ". صور منتجاتك لا تُرسل خارج جهازك في كل الأحوال."

    # ── تعذّر الفهم: نرشد لا نصمت ──
    def _unknown(self, raw: str, t: str) -> Intent:
        hints = self.suggestions(t)
        msg = "لم أفهم طلبك بدقة كافية لأُعدّل نفسي بناءً عليه."
        if hints:
            msg += " هل تقصد أحد هذه؟ " + " • ".join(hints)
        journal.info("dialogue_not_understood", text=t[:120])
        return Intent(explain_ar=msg, raw=raw,
                      alternatives=hints, confidence=0.0)

    def suggestions(self, t: str, limit: int = 3) -> list[str]:
        """أقرب النوايا بمطابقة جزئية على مستوى الحروف — أفضل من لا شيء."""
        words = [w for w in t.split() if len(w) >= 3]
        scores: list[tuple[int, str]] = []
        for spec in SPECS:
            best = 0
            for pat, _w in spec.triggers:
                p = normalize(pat)
                for w in words:
                    if w[:4] and (w[:4] in p or p[:4] in w):
                        best = max(best, len(os.path.commonprefix([w, p])))
            if best >= 3:
                scores.append((best, spec.title_ar))
        scores.sort(key=lambda x: -x[0])
        seen, out = set(), []
        for _s, title in scores:
            if title not in seen:
                seen.add(title)
                out.append(title)
            if len(out) >= limit:
                break
        return out


def _current(key: str, default):
    """القيمة الفعّالة الآن لمفتاح — من التجاوزات ثم المحسّن ثم الافتراضي."""
    with contextlib.suppress(Exception):
        from . import healer
        val = healer.get_override(key, None)
        if val is not None:
            return val
    with contextlib.suppress(Exception):
        from . import optimizer
        val = optimizer.setting(key, None)
        if val is not None:
            return val
    return default


# ═══════════════════ سجل التغييرات والتراجع ═══════════════════

def _changes_path() -> Path:
    return identity.awareness_dir() / "changes.jsonl"


def record_change(entry: dict) -> None:
    with contextlib.suppress(Exception), _LOCK:
        p = _changes_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        entry = {"t": time.time(), **entry}
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def changes(limit: int = 30) -> list[dict]:
    out: list[dict] = []
    with contextlib.suppress(Exception):
        p = _changes_path()
        if p.is_file():
            lines = p.read_text(encoding="utf-8").splitlines()[-limit:]
            for ln in lines:
                with contextlib.suppress(Exception):
                    out.append(json.loads(ln))
    return out


def undo_last() -> dict:
    """يتراجع عن آخر تعديل قابل للتراجع: إعداد أو جراحة كود."""
    hist = [c for c in changes(80) if c.get("undoable")]
    if not hist:
        return {"ok": False, "message_ar": "لا يوجد تعديل حديث أتراجع عنه."}
    last = hist[-1]
    kind = last.get("kind")
    try:
        if kind == KIND_SETTING:
            from . import healer
            key, prev = last["setting_key"], last.get("previous")
            healer.set_override(key, prev, reason="تراجع بطلب المستخدم")
            record_change({"kind": "undo", "target": key, "undoable": False})
            return {"ok": True,
                    "message_ar": (f"تراجعت عن «{last.get('title_ar', key)}» "
                                   f"وأعدت القيمة السابقة ({prev}).")}
        if kind == KIND_PATCH:
            from . import surgeon
            res = surgeon.rollback(last.get("surgery_id", ""))
            record_change({"kind": "undo", "target": last.get("surgery_id"),
                           "undoable": False})
            ok = bool(res.get("ok"))
            return {"ok": ok,
                    "message_ar": ("تراجعت عن تعديل الكود وأعدت الملفات كما كانت."
                                   if ok else
                                   "تعذّر التراجع عن تعديل الكود: "
                                   + str(res.get("error", ""))[:160])}
    except Exception as exc:
        journal.warn("undo_failed", detail=str(exc)[:200])
        return {"ok": False, "message_ar": f"تعذّر التراجع: {str(exc)[:160]}"}
    return {"ok": False, "message_ar": "آخر تعديل لا يمكن التراجع عنه."}


# ═══════════════════ التنفيذ ═══════════════════

class Executor:
    """ينفّذ `Intent` معتمدًا، ويُرجع نتيجة عربية مفهومة."""

    def execute(self, intent: Intent, *, confirmed: bool = False) -> dict:
        if not intent.understood:
            return {"ok": False, "message_ar": intent.explain_ar,
                    "suggestions": intent.alternatives}
        if intent.needs_confirmation and not confirmed:
            return {"ok": False, "needs_confirmation": True,
                    "title_ar": intent.title_ar,
                    "message_ar": intent.explain_ar,
                    "risk": intent.risk, "intent": intent.as_dict()}
        try:
            if intent.kind == KIND_SETTING:
                return self._do_setting(intent)
            if intent.kind in (KIND_ACTION, KIND_QUERY):
                return self._do_action(intent)
            if intent.kind == KIND_PATCH:
                return self._do_patch(intent, confirmed)
        except Exception as exc:
            journal.error("dialogue_execute_failed", key=intent.key,
                          detail=str(exc)[:250])
            return {"ok": False,
                    "message_ar": f"حاولت التنفيذ فتعذّر: {str(exc)[:160]}"}
        return {"ok": False, "message_ar": "نوع تنفيذ غير معروف."}

    def _do_setting(self, intent: Intent) -> dict:
        from . import healer
        spec = _SPEC_BY_KEY[intent.key]
        key = spec.setting_key
        if intent.key == "output_size":
            value = [intent.params["width"], intent.params["height"]]
        elif intent.key == "output_folder":
            path = intent.params.get("path", "")
            if not path:
                return {"ok": False, "message_ar": intent.explain_ar}
            ok, why = _validate_folder(path)
            if not ok:
                return {"ok": False, "message_ar": why}
            value = path
        else:
            value = intent.params.get("value")

        previous = _current(key, None)
        if intent.key == "network_policy":
            with contextlib.suppress(Exception):
                _ledger_mod.ledger().set_network_policy(str(value))
        ok = healer.set_override(key, value, reason=f"حوار: {intent.raw[:80]}")
        if not ok:
            return {"ok": False,
                    "message_ar": "تعذّر حفظ التعديل. تحقّق من صلاحية مجلد البيانات."}
        record_change({"kind": KIND_SETTING, "setting_key": key,
                       "title_ar": intent.title_ar, "value": value,
                       "previous": previous, "undoable": True,
                       "request": intent.raw[:200]})
        journal.info("dialogue_setting_applied", key=key, value=str(value)[:80])
        return {"ok": True, "applied": {key: value},
                "message_ar": intent.explain_ar + " ✓ طبّقته الآن.",
                "undoable": True}

    def _do_action(self, intent: Intent) -> dict:
        action = _SPEC_BY_KEY[intent.key].action
        if action == "diagnose_heal":
            from . import healer, vitals
            rep = vitals.full_scan(use_cache=False)
            sess = healer.heal(rep, auto=True)
            lines = [f"فحصت نفسي: {rep.summary_ar()}", sess.summary_ar()]
            unresolved = [f.message_ar for f in rep.findings
                          if f.severity in ("fatal", "error")][:4]
            if unresolved:
                lines.append("ما يحتاج انتباهك: " + " | ".join(unresolved))
            return {"ok": True, "message_ar": "\n".join(lines),
                    "health": rep.as_dict(), "heal": sess.as_dict()}
        if action == "introspect":
            from . import vitals
            model = identity.self_model()
            rep = vitals.quick_scan()
            return {"ok": True, "message_ar": identity.describe_self(),
                    "identity": model.as_dict() if hasattr(model, "as_dict") else {},
                    "health": rep.as_dict()}
        if action == "report":
            return {"ok": True, "message_ar": _knowledge_summary()}
        if action == "self_improve":
            from . import optimizer
            res = optimizer.tune()
            return {"ok": bool(res.get("ok", True)),
                    "message_ar": res.get("message_ar", "بدأت دورة تحسين."),
                    "detail": res}
        if action == "undo":
            return undo_last()
        return {"ok": False, "message_ar": "إجراء غير معروف."}

    def _do_patch(self, intent: Intent, confirmed: bool) -> dict:
        from . import surgeon
        issues = surgeon.diagnose()
        if not issues:
            return {"ok": True,
                    "message_ar": ("فحصت بنية شفرتي فلم أجد موضع ضعف يستحق "
                                   "تعديلًا. البنية سليمة حاليًا.")}
        if not confirmed:
            top = issues[:5]
            body = "\n".join(f"• {getattr(i, 'message_ar', str(i))}" for i in top)
            return {"ok": False, "needs_confirmation": True,
                    "title_ar": "تعديل بنية الكود", "risk": INVASIVE,
                    "message_ar": (f"وجدت {len(issues)} موضع ضعف في بنيتي:\n"
                                   f"{body}\nأُصلحها الآن؟ لكل تعديل نسخة "
                                   "تراجع، ولن أُطبّق ما يفشل الاختبار."),
                    "issues": len(issues), "intent": intent.as_dict()}
        res = surgeon.operate(apply=True)
        sid = res.get("surgery_id", "")
        if sid:
            record_change({"kind": KIND_PATCH, "surgery_id": sid,
                           "title_ar": "تعديل بنية الكود", "undoable": True,
                           "request": intent.raw[:200]})
        applied = res.get("applied", 0)
        msg = (f"عدّلت بنيتي في {applied} موضع بعد التحقق من كل رقعة "
               f"(نحو + بنية + اختبار). يمكنك دائمًا أن تقول «تراجع»."
               if applied else
               "لم أُطبّق أي تعديل: كل الرقع المرشّحة فشلت في التحقق، "
               "والسلامة أولى من التحسين.")
        return {"ok": True, "message_ar": msg, "detail": res}


def _validate_folder(path: str) -> tuple[bool, str]:
    """لا نقبل مسارًا لا نستطيع الكتابة فيه: وعد كاذب أسوأ من رفض صريح."""
    try:
        p = Path(path).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        probe = p / ".mis_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True, ""
    except Exception as exc:
        return False, (f"لا أستطيع الكتابة في «{path}» ({str(exc)[:70]}). "
                       "اختر مجلدًا آخر أو شغّلني بصلاحية أعلى.")


def _knowledge_summary() -> str:
    """ملخص ما تعلّمه البرنامج — من السجل الأكاشي والمحسّن."""
    parts: list[str] = []
    with contextlib.suppress(Exception):
        s = _ledger_mod.ledger().summary()
        parts.append(
            f"مرّ بي {s.get('incidents', 0)} عطلًا مختلفًا، "
            f"حُلّ منها {s.get('resolved', 0)}، "
            f"وأعرف {s.get('remedies', 0)} علاجًا مجرّبًا، "
            f"واستخلصت {s.get('insights', 0)} درسًا.")
        top = _ledger_mod.ledger().top_incidents(3)
        if top:
            names = " | ".join(str(i.get("kind", ""))[:40] for i in top)
            parts.append(f"أكثر ما يتكرر: {names}.")
    with contextlib.suppress(Exception):
        from . import optimizer
        parts.append(optimizer.report().get("summary_ar", ""))
    ch = changes(200)
    if ch:
        parts.append(f"أجريت {len(ch)} تعديلًا على نفسي بناءً على طلبك وقياساتي.")
    return "\n".join(p for p in parts if p) or "لم أُسجّل بعد خبرة تُذكر."


# ═══════════════════ الواجهة العامة ═══════════════════

_INTERP: Interpreter | None = None
_EXEC: Executor | None = None


def interpreter() -> Interpreter:
    global _INTERP
    if _INTERP is None:
        _INTERP = Interpreter()
    return _INTERP


def executor() -> Executor:
    global _EXEC
    if _EXEC is None:
        _EXEC = Executor()
    return _EXEC


def understand(text: str) -> Intent:
    return interpreter().understand(text)


def ask(text: str, *, confirmed: bool = False, apply: bool = True) -> dict:
    """المدخل الوحيد من الواجهة: نص المستخدم ← نتيجة عربية.

    ``apply=False`` يعطي معاينة للنية دون تنفيذ (لعرضها أثناء الكتابة).
    """
    intent = understand(text)
    if not apply:
        return {"ok": intent.understood, "preview": True,
                "message_ar": intent.explain_ar, "intent": intent.as_dict()}
    res = executor().execute(intent, confirmed=confirmed)
    res.setdefault("intent", intent.as_dict())
    return res


def capabilities_ar() -> list[str]:
    """أمثلة حقيقية تُعرض للمستخدم ليعرف ما يمكن أن يطلبه."""
    return [
        "اجعل الجودة 95",
        "خلّ المقاس 1200×1000",
        "احفظ بصيغة PNG",
        "لا تضع ظل",
        "شغّل طمس التواريخ",
        "المعالجة بطيئة، سرّعها",
        "الخط صغير، كبّر الواجهة",
        "افحص نفسك وأصلح ما تجده",
        "من أنت وما هدفك؟",
        "ماذا تعلّمت حتى الآن؟",
        "عدّل بنيتك وأصلح مواضع الضعف",
        "تراجع عن آخر تعديل",
    ]
