# -*- coding: utf-8 -*-
"""ملفات تعريف تنسيق المنصات — التسمية الذكية للتصدير.

كل منصة (سلة، زد، شوبيفاي، ووكومرس، أمازون…) لها قواعد لأسماء ملفات الصور:
بعضها يدعم العربية في اسم الملف، وبعضها يتطلب لاتينيًا فقط، وبعضها يحدد
فاصلًا معينًا أو طولًا أقصى. هذه الوحدة تعرّف الملفات الشخصية وتحوّل أسماء
النمط الداخلي (رقم_الصنف_تسلسل_وحدة) إلى الاسم الأنسب لكل منصة تلقائيًا،
حتى 10 صور لكل صنف دون تكرار.

القاعدة الذهبية: لا يُخترع أي جزء من الاسم — رقم الصنف والوحدة والتسلسل
تأتي من التحليل الحرفي للاسم الداخلي المطابق للإكسل.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .naming_v2 import parse_name, clean_unit

__all__ = [
    "PlatformProfile", "PLATFORM_PROFILES", "render_for_platform",
    "plan_platform_export", "transliterate_ar", "render_custom",
]

# ------------------------------------------------------------ transliteration
_AR_MAP = {
    "ا": "a", "أ": "a", "إ": "i", "آ": "a", "ب": "b", "ت": "t", "ث": "th",
    "ج": "j", "ح": "h", "خ": "kh", "د": "d", "ذ": "th", "ر": "r", "ز": "z",
    "س": "s", "ش": "sh", "ص": "s", "ض": "d", "ط": "t", "ظ": "z", "ع": "a",
    "غ": "gh", "ف": "f", "ق": "q", "ك": "k", "ل": "l", "م": "m", "ن": "n",
    "ه": "h", "ة": "h", "و": "w", "ؤ": "w", "ي": "y", "ى": "a", "ئ": "y",
    "ء": "", "ﻻ": "la", "لا": "la",
}

# ترجمات الوحدات الشائعة — أدق من النقل الحرفي
_UNIT_EN = {
    "حبه": "piece", "حبة": "piece", "ربطة": "bundle", "ربطه": "bundle",
    "شدة": "pack", "شده": "pack", "كرتون": "carton", "درزن": "dozen",
    "كيس": "bag", "علبة": "box", "علبه": "box", "صنف": "item",
}


def transliterate_ar(text: str) -> str:
    """نقل حرفي عربي → لاتيني آمن لأسماء الملفات."""
    text = unicodedata.normalize("NFC", text or "")
    if text in _UNIT_EN:
        return _UNIT_EN[text]
    out = []
    for ch in text:
        if ch in _AR_MAP:
            out.append(_AR_MAP[ch])
        elif ch.isascii() and (ch.isalnum() or ch in "-_"):
            out.append(ch)
        elif ch in " \t":
            out.append("-")
        # يتجاهل التشكيل وأي رموز أخرى
    slug = "".join(out)
    slug = re.sub(r"[-_]{2,}", "-", slug).strip("-_")
    return slug or "img"


# ------------------------------------------------------------------ profiles
@dataclass
class PlatformProfile:
    """قواعد تسمية منصة واحدة."""
    key: str
    name_ar: str
    arabic_ok: bool          # هل تقبل المنصة العربية في اسم الملف؟
    separator: str = "_"     # الفاصل بين الأجزاء
    max_len: int = 80        # أقصى طول لاسم الملف (بدون الامتداد)
    lowercase: bool = False  # فرض الأحرف الصغيرة
    seq_style: str = "suffix"   # suffix: name_2 | dash: name-2
    note_ar: str = ""

    def describe(self) -> str:
        lang = "يدعم العربية" if self.arabic_ok else "لاتيني فقط (نقل حرفي تلقائي)"
        return f"{self.name_ar} — {lang}"


PLATFORM_PROFILES: dict[str, PlatformProfile] = {
    "internal": PlatformProfile(
        key="internal", name_ar="النمط الداخلي (مطابق للإكسل)",
        arabic_ok=True, separator="_", max_len=120,
        note_ar="رقم_الصنف_التسلسل_الوحدة كما في الإكسل حرفيًا — النمط الموصى به"),
    "salla": PlatformProfile(
        key="salla", name_ar="سلة Salla",
        arabic_ok=True, separator="-", max_len=100,
        note_ar="تقبل العربية؛ يفضل الشرطة بين الأجزاء"),
    "zid": PlatformProfile(
        key="zid", name_ar="زد Zid",
        arabic_ok=True, separator="-", max_len=100,
        note_ar="تقبل العربية؛ يفضل الشرطة بين الأجزاء"),
    "shopify": PlatformProfile(
        key="shopify", name_ar="شوبيفاي Shopify",
        arabic_ok=False, separator="-", max_len=60, lowercase=True,
        note_ar="لاتيني صغير فقط؛ يُنقل حرفيًا تلقائيًا"),
    "woocommerce": PlatformProfile(
        key="woocommerce", name_ar="ووكومرس WooCommerce",
        arabic_ok=False, separator="-", max_len=60, lowercase=True,
        note_ar="لاتيني صغير — يتوافق مع روابط ووردبريس"),
    "amazon": PlatformProfile(
        key="amazon", name_ar="أمازون Amazon",
        arabic_ok=False, separator=".", max_len=50, lowercase=False,
        seq_style="dot_index",
        note_ar="نمط أمازون: SKU.MAIN ثم SKU.PT01..PT09"),
    "noon": PlatformProfile(
        key="noon", name_ar="نون noon",
        arabic_ok=False, separator="_", max_len=60, lowercase=False,
        seq_style="noon_index",
        note_ar="النمط الرسمي لنون: SKU_1 للغلاف ثم SKU_2..SKU_10 للصور الإضافية"),
    "trendyol": PlatformProfile(
        key="trendyol", name_ar="ترنديول Trendyol",
        arabic_ok=False, separator="-", max_len=60, lowercase=True,
        note_ar="لاتيني صغير بشرطات — متوافق مع متطلبات ترنديول"),
    "instagram": PlatformProfile(
        key="instagram", name_ar="سوشال (إنستغرام/سناب/واتساب)",
        arabic_ok=True, separator="_", max_len=80,
        note_ar="أسماء عربية واضحة للمشاركة في قنوات التواصل والعروض"),
    "seo": PlatformProfile(
        key="seo", name_ar="ويب SEO (جوجل صور)",
        arabic_ok=False, separator="-", max_len=60, lowercase=True,
        note_ar="أسماء وصفية قصيرة بشرطات — أفضل لظهور الصور في بحث جوجل"),
    "generic": PlatformProfile(
        key="generic", name_ar="عام متوافق مع الكل",
        arabic_ok=False, separator="-", max_len=50, lowercase=True,
        note_ar="أوسع توافق: لاتيني صغير وشرطات فقط"),
    "custom": PlatformProfile(
        key="custom", name_ar="يدوي حر (قالب أكتبه بنفسي)",
        arabic_ok=True, separator="_", max_len=120,
        note_ar="اكتب قالبك: {الرقم} {التسلسل} {الوحدة} بأي ترتيب وفاصل"),
}


def render_custom(stem: str, template: str) -> str | None:
    """قالب يدوي حر: {الرقم} {التسلسل} {الوحدة} — يتجاهل التسلسل 1."""
    parsed = parse_name(stem)
    if parsed is None or not parsed.item:
        return None
    seq = max(1, int(getattr(parsed, "seq", 1) or 1))
    unit = clean_unit(getattr(parsed, "unit", "") or "")
    name = (template or "{الرقم}_{التسلسل}_{الوحدة}")
    name = name.replace("{الرقم}", str(parsed.item))
    name = name.replace("{التسلسل}", "" if seq == 1 else str(seq))
    name = name.replace("{الوحدة}", unit)
    name = re.sub(r"[_\-.]{2,}", "_", name).strip("_-. ")
    # تعقيم محارف محظورة في أسماء الملفات
    name = re.sub(r'[\\/:*?"<>|]+', "", name)
    return name[:120] or None


# ------------------------------------------------------------------ renderer
def render_for_platform(stem: str, profile: PlatformProfile) -> str | None:
    """يحوّل اسمًا داخليًا (رقم_تسلسل_وحدة) إلى اسم المنصة. None إن لم يُفهم."""
    parsed = parse_name(stem)
    if parsed is None or not parsed.item:
        return None
    item = str(parsed.item)
    seq = max(1, int(getattr(parsed, "seq", 1) or 1))
    unit = clean_unit(getattr(parsed, "unit", "") or "")

    if profile.key == "internal":
        return stem  # مطابق للإكسل حرفيًا — لا تغيير

    if profile.seq_style == "dot_index":
        # نمط أمازون الرسمي: <معرف>.MAIN ثم <معرف>.PT01..PT09 حتى 10 صور
        tag = "MAIN" if seq == 1 else f"PT{seq - 1:02d}"
        base = f"{item}.{tag}"
        return base[: profile.max_len]

    if profile.seq_style == "noon_index":
        # نمط نون الرسمي: SKU_1 للغلاف ثم SKU_2..SKU_10
        return f"{item}_{seq}"[: profile.max_len]

    unit_part = unit if profile.arabic_ok else transliterate_ar(unit)
    sep = profile.separator
    parts = [item]
    if seq > 1:
        parts.append(str(seq))
    if unit_part:
        parts.append(unit_part)
    name = sep.join(parts)
    if profile.lowercase:
        name = name.lower()
    # تعقيم نهائي ضد الفواصل المزدوجة
    name = re.sub(rf"[{re.escape(sep)}]{{2,}}", sep, name).strip(sep)
    return name[: profile.max_len]


def plan_platform_export(stems: list[str],
                         profile: PlatformProfile) -> list[tuple[str, str | None]]:
    """يخطط تحويل قائمة أسماء كاملة، ويضمن عدم التكرار (حتى 10 صور/صنف)."""
    seen: dict[str, int] = {}
    out: list[tuple[str, str | None]] = []
    for stem in stems:
        new = render_for_platform(stem, profile)
        if new is None:
            out.append((stem, None))
            continue
        if new in seen:
            seen[new] += 1
            sep = profile.separator if profile.separator != "." else "-"
            new = f"{new}{sep}{seen[new]}"
        else:
            seen[new] = 1
        out.append((stem, new))
    return out
