# -*- coding: utf-8 -*-
"""Unified naming system for V2.2.

Two ready-made schemes plus a custom template:

1. ``dash`` (الجديد — الافتراضي بطلب المستخدم):
       الواجهة (الأولى) -> {item}_{unit}          بلا رقم
       الإضافية        -> {item}_{unit}-2 , {item}_{unit}-3 ...
       (2.9.9: كانت الثانية تأخذ -1 فيتداخل مع الواجهة)
2. ``classic`` (نمط 2.1):
       الصورة الأولى  -> {item}_{unit}
       الثانية        -> {item}_2_{unit} ...
3. ``custom``: قالب حر يكتبه المستخدم.

The unit is written VERBATIM as it appears in the Excel file
(حبه/حبة/شده/شدة/كرتون/باكت...). Parsing accepts all historic patterns
(item_2_unit, item_unit_2, item_unit-2) transparently so bulk renaming of
old folders keeps working.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

UNIT_SUFFIX_DEFAULT = "حبه"

# الوحدة قد تكون **مركّبة** بقاعدة المالك (2.9.10): دمج كل
# وحدات الصنف من الإكسل بشرطة سفلية — `حبه_شدة_كرتون`.
# لذلك تقبل الوحدة الشرطة السفلية داخلها. ولأن `re` جشع
# يلزم منع الوحدة من ابتلاع رقم الترتيب في الأنماط التي تحمل
# الرقم في الوسط أو الأخير، فيُشترط أن لا يكون أي جزء من
# الوحدة المركّبة رقمًا محضًا (يحرسه `_unit_has_digit_part`).
_UNIT_PART = r"[^_.\-]+"                      # جزء وحدة واحد بلا `_` ولا `-`
_UNIT_MULTI = rf"{_UNIT_PART}(?:_{_UNIT_PART})*"   # حبه أو حبه_شدة_كرتون

# canonical 2.1: 10018435_حبه / 10018435_2_حبه / 10018435_3_حبه
# ومعها الوحدات المركّبة: 10018435_حبه_شدة_كرتون
NAME_RE = re.compile(
    rf"^(?P<item>[A-Za-z0-9\-]+?)(?:_(?P<seq>\d+))?_(?P<unit>{_UNIT_MULTI})$"
)
# legacy variant produced by 1.2.1: 10018435_حبه_2 (suffix before number)
LEGACY_NAME_RE = re.compile(
    rf"^(?P<item>[A-Za-z0-9\-]+?)_(?P<unit>{_UNIT_MULTI}?)(?:_(?P<seq>\d+))?$"
)
# new 2.2 dash scheme: 10018435_حبه-2 (dash before the sequence)
# وقاعدة المالك: 10011205_حبه_شدة_كرتون-1
DASH_NAME_RE = re.compile(
    rf"^(?P<item>[A-Za-z0-9]+?)_(?P<unit>{_UNIT_MULTI})-(?P<seq>\d+)$"
)


def _unit_has_digit_part(unit: str) -> bool:
    """أفي جزء من الوحدة المركّبة رقمٌ محض؟

    أخطر ما جرّته الوحدات المركّبة (2.9.10): حين أُذن للوحدة
    أن تحمل `_` داخلها لتقبل `حبه_شدة_كرتون`، صار `re` الجشع
    يبتلع **رقم الترتيب** أيضًا: فالاسم القديم `10012345_حبه_2`
    (من الإصدار 1.2.1 وموجود بكثرة في مجلدات المالك) يُقرأ
    وحدته `حبه_2` وترتيبه 1، لا `حبه` والترتيب 2.

    وأفدح ما يترتّب عليه: تُصحّح الوحدة لاحقًا إلى `حبه` ويبقى
    الترتيب 1، فيُنتج للصورة الثانية **نفس اسم الأولى** فتُطمس
    أو تُتخطّى بصمت دون أي رسالة خطأ — فقدان صور لا يراه المالك.

    لذلك نرفض أي مطابقة يكون في وحدتها جزء رقمي محض، فيُعاد
    الاسم للأنماط الأدق التي تفصل الرقم عن الوحدة صحيحًا.
    ولا توجد وحدة قياس حقيقية اسمها رقم محض، فلا خسارة في الرفض.
    """
    return any(part.isdigit() for part in str(unit).split("_"))


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}

SCHEME_DASH = "dash"        # الجديد الموصى به
SCHEME_CLASSIC = "classic"  # نمط 2.1
SCHEME_CUSTOM = "custom"
VALID_SCHEMES = (SCHEME_DASH, SCHEME_CLASSIC, SCHEME_CUSTOM)

# مرجع الربط والتسمية النهائي من سجل Excel. يبقى item_code افتراضيًا
# لتتوافق الجلسات والمجلدات السابقة، والباركود خيار صريح قبل المعالجة.
REFERENCE_ITEM_CODE = "item_code"
REFERENCE_BARCODE = "barcode"
VALID_REFERENCE_MODES = (REFERENCE_ITEM_CODE, REFERENCE_BARCODE)


@dataclass
class ParsedName:
    item: str
    seq: int          # 1 for the base image (no explicit number)
    unit: str

    def render(self, scheme: str = SCHEME_CLASSIC, total: int = 0) -> str:
        unit = str(self.unit or "").strip().strip("_").strip()
        if scheme == SCHEME_DASH:
            return build_name_dash(self.item, self.seq, unit, total=total)
        if self.seq <= 1:
            return f"{self.item}_{unit}".strip("_")
        return f"{self.item}_{self.seq}_{unit}".strip("_")


def _safe_format(tpl: str, values: dict) -> str:
    """format آمن للقوالب: المتغير غير المعروف يُترك كما هو بلا انهيار."""
    class _D(dict):
        def __missing__(self, k):
            return "{" + k + "}"
    try:
        out = tpl.format_map(_D(values))
    except (ValueError, IndexError):
        out = tpl
    # نظف الفواصل المكررة الناتجة عن متغيرات فارغة
    out = re.sub(r"[-_]{2,}", lambda m: m.group(0)[0], out)
    return out.strip("-_ ") or "item"


_UNSAFE_CHARS = '/\\:*?"<>|\x00'
_MAX_ITEM_LEN = 120  # يضمن اسمًا نهائيًا < 260 محرفًا على Windows
_MULTI_UNDERSCORE_RE = re.compile(r"_{2,}")


def normalize_stem(stem: str) -> str:
    """تطبيع نهائي لأي اسم ملف قبل الحفظ: يمنع الشرطات السفلية المزدوجة
    (سبب تكرار `10004696_2__حبه`) والشرطات والمسافات الطرفية نهائيًا."""
    stem = str(stem).strip()
    stem = _MULTI_UNDERSCORE_RE.sub("_", stem)
    return stem.strip("_ ").strip() or "item"


_INNER_SPACE_RE = re.compile(r"\s+")


def clean_unit(unit: str) -> str:
    """تعقيم قيمة الوحدة القادمة من الإكسل أو الإدخال اليدوي:
    إزالة الشرطات السفلية والمسافات الطرفية التي كانت تولّد `__حبه`.

    ملاحظة: تحفظ الإملاء كما ورد في الإكسل حرفيًا (قرار المالك).
    للمقارنة بين إملاءين لنفس الوحدة استخدم `unit_key`.

    2.9.6 (قرار المالك — الخيار «أ»): **المسافة الداخلية تُحذف**.
    الإكسل يحتوي وحدات بمسافة (`كرتون 1` في 594 صفًا، `نص كرتون` في 4)
    وهي وحدات حقيقية مميزة لا أخطاء إملائية — فحص عبواتها يثبت ذلك
    (10008272: كرتون=64 مقابل كرتون 1=256). لكن المسافة في اسم الملف
    تُفسد روابط المتاجر، فتُحذف مع حفظ التمييز:
        `كرتون 1` -> `كرتون1`   |   `نص كرتون` -> `نصكرتون`
    """
    text = str(unit or "").strip().strip("_").strip()
    if not text:
        return ""
    return _INNER_SPACE_RE.sub("", text)


# ------------------------------------------------- مفتاح المقارنة للوحدات
# الإكسل يكتب الوحدة بإملاءات مختلفة (حبه/حبة، شده/شدة،
# علبه/علبة) وهي **وحدة واحدة** فعليًا. اسم الملف يحفظ الإملاء
# الأصلي كما في الإكسل، لكن المقارنة والتجميع ومنع التكرار تعتمد
# هذا المفتاح حتى لا يُعامل `حبه` و`حبة` كوحدتين منفصلتين.
_UNIT_KEY_TRANS = str.maketrans({
    "ة": "ه",   # تاء مربوطة -> هاء   (حبة = حبه)
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
    "ى": "ي",   # ألف مقصورة -> ياء
    "ـ": "",    # تطويل
})
_TASHKEEL_RE = re.compile(r"[\u064B-\u0652\u0670\u0640]")
_UNIT_SPACE_RE = re.compile(r"[\s_\-]+")


def unit_key(unit: str) -> str:
    """مفتاح موحّد للمقارنة بين إملاءات الوحدة المختلفة.

    لا يُستخدم في اسم الملف إطلاقًا — اسم الملف يحفظ إملاء الإكسل.
    مثال: unit_key("حبة") == unit_key("حبه") == "حبه"
    """
    text = clean_unit(unit)
    if not text:
        return ""
    text = _TASHKEEL_RE.sub("", text)
    text = text.translate(_UNIT_KEY_TRANS)
    text = _UNIT_SPACE_RE.sub("", text)
    return text.casefold()


def same_unit(first: str, second: str) -> bool:
    """هل الوحدتان واحدة فعليًا مع اختلاف الإملاء؟ (حبه وحبة)"""
    return unit_key(first) == unit_key(second)


def dedupe_units(units: list[str] | tuple[str, ...]) -> list[str]:
    """يحذف الوحدات المكررة إملائيًا مع الاحتفاظ بأول إملاء ورد
    في الإكسل حرفيًا وبنفس الترتيب.

    مثال: ["حبه", "حبة", "كرتون"] -> ["حبه", "كرتون"]
    """
    out: list[str] = []
    seen: set[str] = set()
    for u in units or []:
        cu = clean_unit(u)
        if not cu:
            continue
        key = unit_key(cu)
        if key in seen:
            continue
        seen.add(key)
        out.append(cu)
    return out


def sanitize_item(item: str) -> str:
    """تعقيم اسم الصنف: إزالة فواصل المسارات والمحارف الخطرة والنقاط
    البادئة (ضد path traversal) وتقييد الطول (ضد تجاوز حد Windows)."""
    item = str(item).strip()
    for ch in _UNSAFE_CHARS:
        item = item.replace(ch, "")
    while item.startswith("."):
        item = item[1:]
    item = item.strip() or "item"
    return item[:_MAX_ITEM_LEN]


def build_name(item: str, seq: int = 1, unit: str = UNIT_SUFFIX_DEFAULT) -> str:
    """Build the classic (2.1) stem for image `seq` of item `item`."""
    item = sanitize_item(item)
    unit = clean_unit(sanitize_item(str(unit))) if unit else ""
    unit = unit or UNIT_SUFFIX_DEFAULT
    if seq <= 1:
        return normalize_stem(f"{item}_{unit}")
    return normalize_stem(f"{item}_{seq}_{unit}")


def build_name_dash(item: str, seq: int = 1, unit: str = UNIT_SUFFIX_DEFAULT,
                    total: int = 1) -> str:
    """النمط الجديد بالشرطة — قاعدة المالك النهائية (2.9.12):

    - الصورة الرئيسية (الواجهة المعيّنة بـ★) بلا رقم: ``{item}_{unit}``
    - الصورة الثانية تحمل ``-1``
    - الثالثة ``-2``، الرابعة ``-3`` … وهكذا
    - الرقم في **نهاية الاسم دائمًا** بعد الوحدة، بشرطة، ولا شيء بعده.

    أمر المالك نصًا (2026-08-05): «عند التسمية البداية تكون
    بدون رقم ثم واحد اثنين 3 الخـ.. عدلها».

    تاريخ هذا القرار (مهم لمن يعدّل لاحقًا):
    تبدّل هذا الاصطلاح مرتين قبل 2.9.12 (كان ``-1`` ثم صار ``-2``
    ثم عاد ``-1``). لا تعكسه من تلقاء نفسك بحجة «الرقم يجب أن
    يطابق الرتبة» — المالك حسمه صراحة ومعه ترحيل تلقائي
    للمجلدات القديمة (``migrate_legacy_dash_names``).

    ملاحظة معمارية: ``seq`` هنا هو **الرتبة الداخلية** (1 للرئيسية،
    2 للثانية) ويبقى كما هو في كل منطق الترتيب والفرز. التغيير
    في **طبقة العرض فقط**: الرقم الظاهر = ``seq - 1``.
    ومقابله في القراءة ``parse_name`` يردّ ``shown + 1``، فيبقى
    round-trip متسقًا. لا تعدّل أحدهما دون الآخر.
    (يحرسه ``test_owner_units_real`` و``test_naming_join_all``).
    """
    item = sanitize_item(item)
    unit = clean_unit(sanitize_item(str(unit))) if unit else ""
    unit = unit or UNIT_SUFFIX_DEFAULT
    base = normalize_stem(f"{item}_{unit}")
    if seq <= 1:
        return base
    # الرقم الظاهر يبدأ من 1 للصورة الثانية — أمر المالك.
    return f"{base}-{seq - 1}"


def parse_name(stem: str) -> ParsedName | None:
    """Parse an existing file stem back into (item, seq, unit).

    Accepts the dash pattern (item_unit-2), the canonical V2 pattern
    (item_2_unit) and the legacy 1.2.1 pattern (item_unit_2).
    """
    stem = normalize_stem(stem)
    m = DASH_NAME_RE.match(stem)
    if m and not _unit_has_digit_part(m.group("unit")):
        # 2.9.12 — الرقم الظاهر في نمط dash يبدأ من 1 للصورة
        # **الثانية** (الرئيسية بلا رقم)، فالرتبة الداخلية =
        # ``shown + 1`` — عكس ``build_name_dash`` تمامًا ليبقى
        # round-trip متسقًا. لا تعدّل أحدهما دون الآخر.
        shown = int(m.group("seq"))
        return ParsedName(m.group("item"), shown + 1 if shown >= 1 else 2,
                          m.group("unit"))
    m = NAME_RE.match(stem)
    # الحارس هنا أوجب ما يكون: `10012345_حبه_2` يطابق هذا النمط
    # بوحدة `حبه_2` وترتيب 1 (خطأ)، فيُرفض ليسقط على
    # `LEGACY_NAME_RE` الذي يقرأ `حبه` والترتيب 2 صحيحًا.
    if m and not _unit_has_digit_part(m.group("unit")):
        seq = int(m.group("seq")) if m.group("seq") else 1
        return ParsedName(m.group("item"), seq, m.group("unit"))
    m = LEGACY_NAME_RE.match(stem)
    if m and not _unit_has_digit_part(m.group("unit")):
        seq = int(m.group("seq")) if m.group("seq") else 1
        return ParsedName(m.group("item"), seq, m.group("unit"))
    return None


def next_sequence(existing_stems: list[str], item: str) -> int:
    """Return the next free sequence number for `item` among existing stems."""
    item = str(item).strip()
    used: set[int] = set()
    for stem in existing_stems:
        parsed = parse_name(stem)
        if parsed and parsed.item == item:
            used.add(parsed.seq)
    seq = 1
    while seq in used:
        seq += 1
    return seq


def plan_group_names(item: str, count: int,
                     unit: str = UNIT_SUFFIX_DEFAULT,
                     scheme: str = SCHEME_CLASSIC) -> list[str]:
    """Names for a whole group of `count` images of one item (1-based order)."""
    if scheme == SCHEME_DASH:
        return [build_name_dash(item, i + 1, unit, total=count)
                for i in range(count)]
    return [build_name(item, i + 1, unit) for i in range(count)]


# --------------------------------------------- 2.9.12 legacy dash migration
# المشكلة: قبل 2.9.12 كان الرقم الظاهر = الرتبة نفسها
# (الرئيسية بلا رقم، الثانية -2، الثالثة -3)، وصار الآن
# (الثانية -1، الثالثة -2). فمجلدات المالك القديمة تحتاج
# إزاحة واحدة لأسفل. المالك اختار صراحةً الترحيل التلقائي
# مع نسخة احتياطية («الثاني أفضل بحيث يصبح كل شيء ممتاز»).
#
# الخطر الحقيقي: المجلد المُرحَّل مرتين يفقد صورًا (الإزاحة
# تصطدم بالرئيسية بلا رقم)، لذلك نضع علامة إنجاز في المجلد
# ونكشف المجلدات المُرحَّلة أصلًا بوجود `-1` فيها.
MIGRATION_MARKER = ".naming_migrated_2912"


def _dash_shown_number(stem: str) -> int | None:
    """الرقم الظاهر في نمط الشرطة، أو ``None`` إن لم يكن منه."""
    m = DASH_NAME_RE.match(normalize_stem(stem))
    if not m or _unit_has_digit_part(m.group("unit")):
        return None
    return int(m.group("seq"))


def folder_needs_dash_migration(folder: str | Path) -> bool:
    """أيحتاج هذا المجلد ترحيلًا إلى اصطلاح 2.9.12؟

    الحكم محافظ: لا نرحّل إلا إذا كانت كل الأرقام الظاهرة
    ≥ 2 ولا يوجد أي `-1`، لأن وجود `-1` دليل قاطع على أن
    المجلد بالاصطلاح الجديد أصلًا. والشك يُفسّر لمصلحة
    عدم المساس بملفات المالك.
    """
    folder = Path(folder)
    if not folder.is_dir() or (folder / MIGRATION_MARKER).exists():
        return False
    shown_numbers: list[int] = []
    for p in folder.iterdir():
        if not p.is_file() or p.suffix.lower() not in IMAGE_EXTS:
            continue
        n = _dash_shown_number(p.stem)
        if n is not None:
            shown_numbers.append(n)
    if not shown_numbers:
        return False
    return min(shown_numbers) >= 2


def plan_dash_migration(folder: str | Path) -> list[RenamePlanEntry]:
    """خطة إنقاص واحد من كل رقم ظاهر في نمط الشرطة.

    ``item_حبه-2`` ← ``item_حبه-1`` ، ``-3`` ← ``-2`` … والرئيسية
    بلا رقم تبقى كما هي.
    """
    folder = Path(folder)
    entries: list[RenamePlanEntry] = []
    files = [p for p in sorted(folder.iterdir())
             if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    # نرتّب تصاعديًا بالرقم الظاهر لينزل -2 قبل -3.
    files.sort(key=lambda p: (_dash_shown_number(p.stem) or 0))

    # ملاحظة دقيقة: لا يجوز الحكم بالتصادم لمجرد وجود الهدف
    # على القرص، لأن الهدف نفسه قد يكون ملفًا سيُزاح هو الآخر
    # في هذه الخطة (`-3` يريد `-2` و`-2` نازل إلى `-1`).
    # و``apply_bulk_rename`` ينفّذ على مرحلتين بأسماء مؤقتة فلا
    # تتصادم السلسلة. فالمعيار الصحيح: الهدف مشغول إن كان
    # موجودًا و**لن يتحرك** من مكانه.
    moving: set[str] = set()
    for p in files:
        shown = _dash_shown_number(p.stem)
        if shown is not None and shown >= 2:
            moving.add(p.name)

    taken: set[str] = set()
    for p in files:
        shown = _dash_shown_number(p.stem)
        if shown is None or shown < 2:
            entries.append(RenamePlanEntry(p.name, p.name, "unchanged"))
            taken.add(p.name)
            continue
        m = DASH_NAME_RE.match(normalize_stem(p.stem))
        base = f"{m.group('item')}_{m.group('unit')}"
        target = f"{base}-{shown - 1}{p.suffix.lower()}"
        occupied = ((folder / target).exists() and target != p.name
                    and target not in moving)
        if target in taken or occupied:
            entries.append(RenamePlanEntry(p.name, target, "conflict"))
            continue
        taken.add(target)
        entries.append(RenamePlanEntry(p.name, target, "ok"))
    return entries


def migrate_legacy_dash_names(folder: str | Path,
                              backup: bool = True,
                              force: bool = False
                              ) -> dict:
    """يرحّل مجلد مخرَجات قديمًا إلى اصطلاح الترقيم الجديد.

    يُعيد قاموسًا فيه ``migrated`` و``renamed`` و``backup_dir``
    و``errors`` و``reason``. لا يرمي استثناءً أبدًا — فشل الترحيل
    لا يجوز أن يمنع المالك من فتح مجلده.

    النسخة الاحتياطية تُأخذ قبل أي تغيير وتُوضع **خارج**
    مجلد المخرَجات لئلا تدخل في ملف التسليم المضغوط.
    """
    import shutil as _shutil
    from datetime import datetime as _dt

    folder = Path(folder)
    result: dict = {"migrated": False, "renamed": 0, "backup_dir": "",
                    "errors": [], "reason": ""}
    try:
        if not folder.is_dir():
            result["reason"] = "المجلد غير موجود"
            return result
        if not force and not folder_needs_dash_migration(folder):
            result["reason"] = "لا حاجة للترحيل"
            return result
        plan = [e for e in plan_dash_migration(folder)
                if e.status == "ok" and e.target]
        if not plan:
            result["reason"] = "لا ملفات قابلة للترحيل"
            return result
        if backup:
            stamp = _dt.now().strftime("%Y%m%d_%H%M%S")
            bdir = folder.parent / f"{folder.name}_نسخة_قبل_الترحيل_{stamp}"
            bdir.mkdir(parents=True, exist_ok=True)
            # تُنسخ **كل صور المجلد** لا المتحركة وحدها. لو نُسخت
            # المتحركة فقط لما كانت النسخة صورة صادقة عن المجلد قبل
            # الترحيل، فتغيب عنها الواجهة (الصورة بلا رقم) وتفقد
            # النسخة معناها: استرجاع الحالة السابقة كاملة.
            sources = sorted({e.source for e in plan}
                             | {p.name for p in folder.iterdir()
                                if p.is_file()
                                and p.suffix.lower() in IMAGE_EXTS})
            for name in sources:
                try:
                    _shutil.copy2(folder / name, bdir / name)
                except OSError as exc:
                    result["errors"].append(f"نسخ {name}: {exc}")
            # إن فشلت النسخة الاحتياطية كلها فلا نخاطر بملفات المالك.
            if sources and len(result["errors"]) == len(sources):
                result["reason"] = "تعذرت النسخة الاحتياطية — أُلغي الترحيل"
                return result
            result["backup_dir"] = str(bdir)
        applied, errors = apply_bulk_rename(folder, plan)
        result["renamed"] = applied
        result["errors"].extend(errors)
        result["migrated"] = applied > 0
        try:
            (folder / MIGRATION_MARKER).write_text(
                f"migrated={applied}\n", encoding="utf-8")
        except OSError:
            pass
    except Exception as exc:            # noqa: BLE001 - الترحيل لا يُسقط التطبيق
        result["errors"].append(str(exc))
        result["reason"] = "فشل غير متوقع"
    return result


# ------------------------------------------------------------ mojibake fix
def unmojibake(name: str) -> str:
    """Repair double-encoded Arabic file names (UTF-8 seen as cp866/cp437...)."""
    if re.search(r"[\u0600-\u06FF]", name):
        return name  # already fine
    for enc in ("cp866", "cp437", "cp850", "cp1252"):
        try:
            fixed = name.encode(enc).decode("utf-8")
            if re.search(r"[\u0600-\u06FF]", fixed):
                return fixed
        except (UnicodeDecodeError, UnicodeEncodeError):
            continue
    return name


# --------------------------------------------------------------- bulk rename
@dataclass
class RenamePlanEntry:
    source: str
    target: str
    status: str        # ok | conflict | unparsed | unchanged | excel_mismatch


def plan_bulk_rename(folder: str | Path, mapping: dict[str, str],
                     fix_encoding: bool = True,
                     scheme: str = "",
                     settings: "NamingSettings | None" = None
                     ) -> list[RenamePlanEntry]:
    """Plan the normalization of a previously produced results folder.

    - fixes mojibake names
    - normalizes legacy (item_unit_2) to the target scheme
    - applies old->new item-number mapping while keeping groups linked
    - when ``scheme``/``settings`` specify the dash scheme, whole groups are
      renamed to {item}_{unit}-N (and a lone image loses its number).
    """
    folder = Path(folder)
    if settings is not None and not scheme:
        scheme = settings.scheme
    scheme = scheme or SCHEME_CLASSIC
    entries: list[RenamePlanEntry] = []
    taken: set[str] = set()
    files = [p for p in sorted(folder.iterdir())
             if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    # أول تمريرة: تحليل الكل وحساب حجم كل مجموعة (item+unit) لأجل نمط الشرطة
    parsed_all: list[tuple[Path, ParsedName | None]] = []
    group_total: dict[tuple[str, str], int] = {}
    for p in files:
        stem = p.stem
        if fix_encoding:
            stem = unmojibake(stem)
        parsed = parse_name(stem)
        parsed_all.append((p, parsed))
        if parsed:
            item = mapping.get(parsed.item, parsed.item)
            key = (item, clean_unit(parsed.unit))
            group_total[key] = group_total.get(key, 0) + 1
    for p, parsed in parsed_all:
        if parsed is None:
            entries.append(RenamePlanEntry(p.name, "", "unparsed"))
            continue
        item = mapping.get(parsed.item, parsed.item)
        unit = clean_unit(parsed.unit)
        total = group_total.get((item, unit), 1)
        if scheme == SCHEME_DASH:
            new_stem = build_name_dash(item, parsed.seq, unit, total=total)
        else:
            new_stem = build_name(item, parsed.seq, unit)
        target = new_stem + p.suffix.lower()
        if target == p.name:
            entries.append(RenamePlanEntry(p.name, target, "unchanged"))
            taken.add(target)
            continue
        if target in taken or (folder / target).exists() and \
                (folder / target) != p:
            entries.append(RenamePlanEntry(p.name, target, "conflict"))
            continue
        taken.add(target)
        entries.append(RenamePlanEntry(p.name, target, "ok"))
    return entries


def apply_bulk_rename(folder: str | Path,
                      plan: list[RenamePlanEntry]) -> tuple[int, list[str]]:
    """Two-phase rename to avoid collisions. Returns (applied, errors)."""
    folder = Path(folder)
    errors: list[str] = []
    todo = [e for e in plan if e.status == "ok" and e.target]
    # phase 1: to temp names
    temps: list[tuple[Path, Path]] = []
    for e in todo:
        src = folder / e.source
        tmp = folder / (e.target + ".tmp_rn")
        try:
            src.rename(tmp)
            temps.append((tmp, folder / e.target))
        except OSError as exc:
            errors.append(f"{e.source}: {exc}")
    # phase 2: temp -> final
    applied = 0
    for tmp, final in temps:
        try:
            tmp.rename(final)
            applied += 1
        except OSError as exc:
            errors.append(f"{tmp.name}: {exc}")
    return applied, errors


# --------------------------------------------------------- naming settings
UNIT_POLICY_PER_IMAGE = "per_image"
UNIT_POLICY_REPLICATE = "replicate_all_units"
UNIT_POLICY_DEFAULT = "default_unit"
# join_all_units (جديد 2.3): الصنف المكرر في الإكسل بعدة وحدات (حبة/شدة/كرتون)
# تُجمع كل وحداته حرفيًا وبنفس ترتيب الإكسل في اسم واحد:
#   الرئيسية: 10001102_حبة_شدة_كرتون — الإضافية: ...-1 ثم -2 ثم -3
# (أمر المالك 2.9.12: الأولى بلا رقم، ثم 1، 2، 3 — الرقم
#  الظاهر = الرتبة ناقص واحد)
UNIT_POLICY_JOIN_ALL = "join_all_units"
VALID_POLICIES = (UNIT_POLICY_PER_IMAGE, UNIT_POLICY_REPLICATE,
                  UNIT_POLICY_DEFAULT, UNIT_POLICY_JOIN_ALL)


def join_units(units: list[str] | tuple[str, ...],
               default_unit: str = UNIT_SUFFIX_DEFAULT) -> str:
    """يجمع وحدات الصنف كما وردت في الإكسل حرفيًا وبنفس الترتيب
    (مع إزالة التكرار فقط) في مقطع واحد: حبة_شدة_كرتون.

    2.9.3: إزالة التكرار تعتمد `unit_key` لا النص الخام، لأن الإكسل
    قد يكتب الوحدة الواحدة بإملاءين (حبه/حبة) فيخرج الاسم
    `10001102_حبه_حبة_كرتون` وفيه الوحدة نفسها مرتين. الإملاء
    المحفوظ في الاسم هو **أول إملاء ورد في الإكسل** حرفيًا.
    """
    seen = dedupe_units([clean_unit(sanitize_item(str(u))) for u in (units or [])])
    if not seen:
        seen = [clean_unit(default_unit) or UNIT_SUFFIX_DEFAULT]
    return "_".join(seen)


def build_name_join_all(item: str, units: list[str] | tuple[str, ...],
                        seq: int = 1, total: int = 1,
                        default_unit: str = UNIT_SUFFIX_DEFAULT) -> str:
    """اسم الصورة بسياسة جمع كل الوحدات (قاعدة المالك النهائية):

    - الصورة الرئيسية (الأولى/الواجهة): ``{item}_{u1}_{u2}_{u3}`` بلا رقم
    - ثم ``…-1`` ثم ``…-2`` … (الرقم الظاهر = الرتبة ناقص واحد)
    - الرقم في **نهاية الاسم دائمًا** بعد كل الوحدات.

    مثال (الصنف 10011205 وله في الإكسل حبه/شدة/كرتون)::

        10011205_حبه_شدة_كرتون        ← الرئيسية بلا رقم
        10011205_حبه_شدة_كرتون-1      ← الثانية
        10011205_حبه_شدة_كرتون-2      ← الثالثة

    مثال الوحدة الواحدة (10001205 وله `حبه` فقط)::

        10001205_حبه    ثم    10001205_حبه-1

    2.9.12 — تغيير مقصود بأمر المالك الصريح: «الأولى بدون رقم
    والثانية 1 والثالثة 2». قبل ذلك كانت الثانية ``-2``.

    تنبيه لمن يعدّل لاحقًا: ``build_name_join_all`` و``parse_name``
    متلازمان. إن غيّرت الإزاحة هنا فغيّر ``parse_name``
    معها وإلا انفصم الكتابة عن القراءة وضاعت الصور
    (يحرسه ``test_naming_join_all`` و``test_owner_units_real``).
    """
    item = sanitize_item(item)
    joined = join_units(units, default_unit)
    base = normalize_stem(f"{item}_{joined}")
    if seq <= 1:
        return base
    # الرئيسية بلا رقم، ثم 1، 2، 3 — الظاهر = الرتبة − 1.
    return f"{base}-{seq - 1}"


TEMPLATE_DASH = "{item}_{unit}-{seq}"
TEMPLATE_CLASSIC = "{item}_{seq}_{unit}"

SCHEME_LABELS_AR = {
    SCHEME_DASH: "النمط الجديد (موصى به): الواجهة رقم الصنف_الوحدة بلا رقم، ثم -1 / -2",
    SCHEME_CLASSIC: "النمط الكلاسيكي 2.1: رقم الصنف_الوحدة ثم رقم الصنف_2_الوحدة",
    SCHEME_CUSTOM: "قالب مخصص أكتبه بنفسي أو أختاره من القوالب الجاهزة",
}

# قوالب جاهزة للمتاجر والمواقع — تظهر في قائمة الاختيار السريع
# المتغيرات المتاحة: {item} {unit} {seq} {barcode} {name}
STORE_TEMPLATES: list[tuple[str, str]] = [
    ("رقم الصنف_الوحدة-رقم الصورة (الموصى به)", "{item}_{unit}-{seq}"),
    ("رقم الصنف_كل الوحدات من الإكسل (حبة_شدة_كرتون) — الرئيسية بلا رقم والبقية -1/-2", "{item}_{units}-{seq}"),
    ("رقم الصنف_رقم الصورة_الوحدة (كلاسيكي 2.1)", "{item}_{seq}_{unit}"),
    ("رقم الصنف فقط (مواقع تطلب رقم الصنف فقط)", "{item}-{seq}"),
    ("الباركود فقط (مواقع تطلب الباركود)", "{barcode}-{seq}"),
    ("الباركود_الوحدة (متاجر تربط بالباركود)", "{barcode}_{unit}-{seq}"),
    ("رقم الصنف_الباركود (مطابقة مزدوجة)", "{item}_{barcode}-{seq}"),
    ("رقم الصنف-اسم المنتج (متاجر تعرض الاسم في الرابط)", "{item}-{name}-{seq}"),
    ("اسم المنتج فقط (معارض/كتالوجات)", "{name}-{seq}"),
]


@dataclass
class NamingSettings:
    """سياسة الوحدات وقالب التسمية العام + مخطط التسمية المختار.

    - ``enabled``: خانة تفعيل نظام التسمية (عند التعطيل تبقى الأسماء كما هي).
    - ``scheme``: dash (الجديد الافتراضي) | classic | custom.
    - آخر اختيار يُحفظ تلقائيًا عبر save() ويُعتمد في المرات القادمة.
    """
    # 2.9.10 (أمر المالك الأخير، حرفيًا): «دع الخيارين موجودة لها.
    # الوحدة تكون حبه كما السابق. وأيضًا أمري الجديد لك الآن يكون له
    # خيار تفعيل وخيار إلغاء» ⇒ الافتراضي رجع إلى الوحدة الواحدة
    # (`default_unit` = حبه) والدمج صار **خيارًا** يُفعّله المالك من
    # الواجهة الرئيسية قبل بدء المعالجة.
    #
    # لماذا لا join_all_units افتراضًا: 2.9.6 جعلته الافتراضي لأن 74.4%
    # من الأصناف لها أكثر من وحدة، وكان ذلك استنتاجًا صحيحًا لكنه فرض
    # سلوكًا لم يطلبه المالك. الآن الاختيار له لا لنا، والحالتان
    # مدعومتان بقاعدة الترقيم نفسها (الواجهة بلا رقم ثم -1 ثم -2).
    unit_policy: str = UNIT_POLICY_DEFAULT  # per_image | replicate_all_units | default_unit | join_all_units
    default_unit: str = UNIT_SUFFIX_DEFAULT
    template: str = TEMPLATE_DASH
    scheme: str = SCHEME_DASH
    enabled: bool = True
    seq_start: int = 1            # بدء الترقيم (1 أو 0)
    seq_pad: int = 0              # أصفار بادئة: 0=بلا، 2=01،02...
    always_number_single: bool = False  # رقّم حتى الصورة الوحيدة
    # ``barcode`` يبدّل رقم الصنف بباركود Excel فقط، مع بقاء الوحدة
    # والتسلسل كما في قاعدة الصور المنجزة: barcode_unit ثم -1، -2…
    reference_mode: str = REFERENCE_ITEM_CODE

    def _fmt_seq(self, seq: int) -> str:
        """رقم الصورة الإضافية — قاعدة المالك.

        نص أمر المالك حرفيًا: «إذا كان للمنتج أكثر من صورة
        فالمسمى يكون بترقيم والأولى بدون رقم، لهذا أضفنا
        النجمة». فالنجمة ★ تعيّن الواجهة التي لا تحمل رقمًا.

        - الصورة الأولى (الواجهة ★): بلا رقم إطلاقًا
        - الصورة الثانية: ``-2``، الثالثة: ``-3`` …وهكذا

        أي أن الرقم يطابق **رتبة الصورة نفسها** لا رتبتها بين
        الإضافيات: ``seq=2`` ⇒ ``-2`` و``seq=3`` ⇒ ``-3``.

        تنبيه لمن يعدّل لاحقًا (وقع فعلًا مرتين): لا تطرح 1
        إضافيًا هنا. طرحه يُعطي الثانية ``-1`` فيوهم أنها الأولى،
        ويخالف نص المالك أعلاه.

        ``seq_start`` يبقى محترمًا كإزاحة: 1 = قاعدة المالك،
        وقيمة أخرى تُزيح العدّ (إعداد متقدّم).
        """
        n = max(0, seq) + int(self.seq_start) - 1
        if n < 0:
            n = 0
        return str(n).zfill(int(self.seq_pad)) if self.seq_pad else str(n)

    def _fmt_seq_single(self, seq: int) -> str:
        """رقم الصورة الوحيدة حين يطلب المالك ترقيمها قسرًا.

        هنا لا توجد «رئيسية بلا رقم» تُقاس عليها الإضافية، فالعدّ
        يبدأ من ``seq_start`` مباشرة (1 افتراضيًا ، أو 0 إن اختاره).
        فصلها عن ``_fmt_seq`` يمنع خروج الصورة الوحيدة بالرقم ``-0``.
        """
        n = max(0, seq - 1) + int(self.seq_start)
        if n < 0:
            n = 0
        return str(n).zfill(int(self.seq_pad)) if self.seq_pad else str(n)

    def render(self, item: str, seq: int, unit: str, total: int = 0,
               barcode: str = "", name: str = "") -> str:
        """اسم صورة واحدة. ``total`` = عدد صور المجموعة إن عُرف (لنمط الشرطة)."""
        item = sanitize_item(item)
        unit = clean_unit(unit) or self.default_unit or UNIT_SUFFIX_DEFAULT
        if self.reference_mode == REFERENCE_BARCODE:
            # اختيار الباركود يبدّل *المرجع* فقط، ولا يلغي وحدة Excel.
            # هذا يحفظ بنية الملفات المنجزة نفسها: 628…_حبه ثم
            # 628…_حبه-1، 628…_حبه-2…
            ref = sanitize_item(str(barcode or ""))
            if not ref:
                return item  # حارس توافق؛ طبقة الإنتاج ترفضه وتبقي الأصل.
            base = normalize_stem(f"{ref}_{unit}")
            if self.always_number_single and total <= 1 and seq <= 1:
                return f"{base}-{self._fmt_seq_single(seq)}"
            # الواجهة بلا رقم، ثم الإضافيات -1، -2…
            shown = max(0, int(seq) + int(self.seq_start) - 2)
            suffix = str(shown).zfill(int(self.seq_pad)) if self.seq_pad else str(shown)
            return base if seq <= 1 else f"{base}-{suffix}"
        if self.scheme == SCHEME_DASH:
            if self.always_number_single and total <= 1 and seq <= 1:
                return normalize_stem(f"{item}_{unit}") + \
                    f"-{self._fmt_seq_single(seq)}"
            return build_name_dash(item, seq, unit, total=total or seq)
        if self.scheme == SCHEME_CLASSIC:
            return build_name(item, seq, unit)
        # custom template — يدعم {item} {unit} {seq} {barcode} {name}
        safe_name = sanitize_item(str(name or "")).replace(" ", "-")
        # الصورة الوحيدة المُرقّمة قسرًا تأخذ عدًّا يبدأ من seq_start،
        # وغيرها يتبع قاعدة الشرطة (الإضافية الأولى = 1).
        lone_numbered = (self.always_number_single and total <= 1
                         and seq <= 1)
        seq_text = (self._fmt_seq_single(seq) if lone_numbered
                    else self._fmt_seq(seq))
        values = {"item": item, "unit": unit,
                  "seq": seq_text,
                  "barcode": sanitize_item(str(barcode or "")),
                  "name": safe_name}
        # 2.9.10 — قاعدة المالك تسري على القالب المخصص أيضًا:
        # **الرئيسية بلا رقم** والإضافية -1، -2… كان الشرط
        # مقيّدًا بـ`total <= 1` فقط، فصنف له ثلاث صور يُخرج
        # `900_حبه-1` للرئيسية خلافًا للقاعدة، فيخرج المجلد
        # بصيغتين مختلفتين حسب النمط المختار. الأولى الآن
        # بلا رقم مطلقًا إلا إن طلب المالك الترقيم القسري.
        single = seq <= 1 and not self.always_number_single
        if single and "{seq}" in self.template:
            tpl = self.template.replace("-{seq}", "").replace("_{seq}", "") \
                               .replace("{seq}_", "").replace("{seq}", "")
            stem = _safe_format(tpl, values)
            return stem if "-" in stem else normalize_stem(stem)
        stem = _safe_format(self.template, values)
        # normalize underscores but keep dashes intact
        return stem if "-" in stem else normalize_stem(stem)

    def to_dict(self) -> dict:
        return {"unit_policy": self.unit_policy,
                # يدلّ على أن السياسة اختيار صريح لا افتراضي قديم،
                # فلا تُرقّى فوق رغبة المالك في الإصدارات القادمة.
                "unit_policy_explicit": True,
                "default_unit": self.default_unit,
                "template": self.template,
                "scheme": self.scheme,
                "enabled": bool(self.enabled),
                "seq_start": int(self.seq_start),
                "seq_pad": int(self.seq_pad),
                "always_number_single": bool(self.always_number_single),
                "reference_mode": self.reference_mode}

    @classmethod
    def from_dict(cls, d: dict) -> "NamingSettings":
        s = cls()
        s.unit_policy = d.get("unit_policy", s.unit_policy)
        if s.unit_policy not in VALID_POLICIES:
            s.unit_policy = UNIT_POLICY_DEFAULT
        # 2.9.10: أُلغيت ترقية 2.9.6 القسرية (per_image ⇒ join_all_units).
        # كانت تفرض الدمج على كل ملف إعدادات لا يحمل علم الاختيار الصريح،
        # فلو ألغى المالك الخيار من الواجهة ثم فُقد العلم لأي سبب عاد
        # الدمج من تلقاء نفسه — أي أن «الإلغاء» لا يصمد. الآن السياسة
        # المحفوظة تُحترم كما هي، ولا يغيّرها إلا المالك من الواجهة.
        s.default_unit = d.get("default_unit", s.default_unit)
        s.scheme = d.get("scheme", "")
        if s.scheme not in VALID_SCHEMES:
            # ملفات 2.1 القديمة لا تحمل scheme: استنتاجه من القالب المحفوظ
            tpl = d.get("template", "")
            s.scheme = SCHEME_CLASSIC if tpl == TEMPLATE_CLASSIC else SCHEME_DASH
        s.template = d.get("template", "") or (
            TEMPLATE_CLASSIC if s.scheme == SCHEME_CLASSIC else TEMPLATE_DASH)
        s.enabled = bool(d.get("enabled", True))
        try:
            s.seq_start = max(0, int(d.get("seq_start", 1)))
        except (TypeError, ValueError):
            s.seq_start = 1
        try:
            s.seq_pad = min(4, max(0, int(d.get("seq_pad", 0))))
        except (TypeError, ValueError):
            s.seq_pad = 0
        s.always_number_single = bool(d.get("always_number_single", False))
        s.reference_mode = str(d.get("reference_mode", REFERENCE_ITEM_CODE) or REFERENCE_ITEM_CODE)
        if s.reference_mode not in VALID_REFERENCE_MODES:
            s.reference_mode = REFERENCE_ITEM_CODE
        return s

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False,
                                         indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "NamingSettings":
        p = Path(path)
        if p.is_file():
            try:
                return cls.from_dict(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                pass
        return cls()


DEFAULT_SETTINGS_FILENAME = "naming_settings.json"


def load_saved_settings(data_root: str | Path) -> NamingSettings:
    """تحميل آخر سياسة تسمية اختارها المستخدم من مجلد البيانات."""
    return NamingSettings.load(Path(data_root) / DEFAULT_SETTINGS_FILENAME)


def save_settings(data_root: str | Path, settings: NamingSettings) -> None:
    """حفظ سياسة التسمية لتُعتمد تلقائيًا في المرات القادمة."""
    try:
        Path(data_root).mkdir(parents=True, exist_ok=True)
        settings.save(Path(data_root) / DEFAULT_SETTINGS_FILENAME)
    except OSError:
        pass


def plan_stems_for_policy(item: str, units: list[str] | tuple[str, ...],
                          seq: int, total: int,
                          settings: NamingSettings,
                          chosen_unit: str = "", barcode: str = "") -> list[str]:
    """أسماء صورة **واحدة** وفق السياسة — مصدر الحقيقة الوحيد.

    يعيد قائمة: اسمًا واحدًا في السياسات الثلاث، و**اسمًا لكل وحدة**
    في ``replicate_all_units`` (الصنف الذي له حبه/شدة/كرتون يأخذ
    ثلاث نسخ من الصورة نفسها، وحدة لكل نسخة).

    لماذا وُجدت (2.9.11 — عطب أبلغ عنه المالك): كان كل مسار إنتاج
    يفرّع على «دمج أم لا» فقط، فتسقط ``replicate_all_units`` و
    ``default_unit`` و``per_image`` في فرع واحد بالوحدة الافتراضية
    ``حبه``. النتيجة التي رآها المالك: يختار «توليد نسخة لكل وحدة»
    فتُحفظ السياسة ثم يخرج المجلد كله ``10011205_حبه`` وتُعلن
    الواجهة «مُلغى — وحدة واحدة (حبه)». المنطق الصحيح كان موجودًا في
    ``plan_names_for_item`` لكنه معزول عن الإنتاج (معاينة واختبارات
    فقط). فمن اليوم: مسارات الإنتاج الثلاثة (الدفعة، الملف المفرد،
    المجلد المنجز/القديم) تستدعي هذه الدالة، ولا تفرّع على السياسة
    بنفسها. أي تعديل على قاعدة الوحدات يحدث **هنا وحدها**.

    ``units`` وحدات الصنف من الإكسل بترتيب الإكسل حرفيًا.
    ``seq`` رتبة الصورة الحقيقية (1 = الواجهة ★ بلا رقم).
    """
    # الباركود مرجع للاسم فقط؛ سياسة الوحدة تبقى فعّالة كما في
    # رقم الصنف. فلا يسقط «حبه/كرتون/شدة…» عند تفعيل الباركود.
    barcode_mode = settings.reference_mode == REFERENCE_BARCODE
    if barcode_mode and not str(barcode or "").strip():
        return []
    clean = [u for u in (units or []) if str(u).strip()]
    if not clean:
        clean = [settings.default_unit or UNIT_SUFFIX_DEFAULT]
    policy = settings.unit_policy
    if policy == UNIT_POLICY_JOIN_ALL:
        if barcode_mode:
            return [settings.render(item, seq, join_units(clean), total=total,
                                    barcode=barcode)]
        return [build_name_join_all(item, clean, seq, total=total,
                                    default_unit=settings.default_unit)]
    if policy == UNIT_POLICY_REPLICATE:
        # نسخة لكل وحدة من وحدات الإكسل، بترتيب الإكسل، بلا تكرار.
        out: list[str] = []
        for u in dedupe_units([clean_unit(sanitize_item(str(u)))
                              for u in clean]):
            stem = settings.render(item, seq, u, total=total, barcode=barcode)
            if stem not in out:
                out.append(stem)
        return out or [settings.render(item, seq, clean[0], total=total,
                                       barcode=barcode)]
    # للوحدة الواحدة: chosen_unit هو وحدة Excel المحلولة (العبوة=1)
    # إن مررها المسار؛ وإلا نأخذ أول قائمة مرتبة لهذه السياسة.
    preferred = clean_unit(sanitize_item(str(chosen_unit))) if chosen_unit else ""
    preferred = preferred or clean_unit(sanitize_item(str(clean[0]))) or \
        settings.default_unit or UNIT_SUFFIX_DEFAULT
    if policy == UNIT_POLICY_DEFAULT:
        return [settings.render(item, seq, preferred, total=total,
                                barcode=barcode)]
    # per_image: وحدة اختارها المالك لهذه الصورة، أو وحدة Excel المحلولة.
    return [settings.render(item, seq, preferred, total=total, barcode=barcode)]


def plan_names_for_item(item: str, image_count: int, units: list[str],
                        settings: NamingSettings,
                        chosen_unit: str = "") -> list[list[str]]:
    """أسماء صور صنف واحد وفق السياسة.

    يعيد قائمة لكل صورة: قائمة الأسماء المطلوبة لها (قد تتعدد مع replicate —
    الأصناف التي لها حبة وشدة وكرتون معًا تأخذ اسمًا لكل وحدة).
    """
    # 2.9.11: صار غلافًا رقيقًا حول ``plan_stems_for_policy`` بعد أن
    # كان يكرّر منطق السياسات. التكرار هو ما سمح للمعاينة أن تُظهر
    # قاعدة والإنتاج يُنفّذ أخرى.
    units = [u for u in units if u] or [settings.default_unit]
    return [plan_stems_for_policy(item, units, i + 1, image_count,
                                  settings, chosen_unit)
            for i in range(image_count)]


def apply_template_to_all(groups: dict[str, int], units_by_item: dict[str, list[str]],
                          settings: NamingSettings) -> dict[str, list[list[str]]]:
    """تطبيق قالب التسمية على كل المجموعات بنقرة واحدة.

    groups: item -> image_count. يعيد item -> أسماء كل صورة.
    """
    out: dict[str, list[list[str]]] = {}
    for item, count in groups.items():
        units = units_by_item.get(item, [])
        out[item] = plan_names_for_item(item, count, units, settings)
    return out
