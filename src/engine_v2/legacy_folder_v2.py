# -*- coding: utf-8 -*-
"""قراءة المجلدات المنجزة سابقًا وتصحيح تسمياتها من الإكسل (2.9.4).

قرار المالك: «الإكسل مرجع كل شيء… حتى في ملف الصور الجاهزة سابقًا
تتعدل هنا لأنها جاهزة أساسًا ومربوطة بالمسمى».

## المشكلة المقيسة على مجلد منجز حقيقي (991 صورة / 484 صنفًا)
| النمط | العدد |
|---|---|
| `{item}_{unit}_N`  (قديم، شرطة سفلية، يبدأ من 2) | 507 |
| `{item}_{unit}-N`  (قاعدة المالك، يبدأ من 1)     | 0   |
| `{item}_{unit}`    (الواجهة، بلا رقم)            | 484 |

فالتحويل المطلوب إزاحة: `_2 ⇒ -1`، `_3 ⇒ -2`، `_4 ⇒ -3`.

## قاعدة التسمية المعتمدة
- صورة الواجهة: `{item}_{unit}`  (بلا رقم)
- بقية الصور  : `{item}_{unit}-1`، `-2`، `-3`…
- الوحدة تُقرأ من الإكسل بإملائها **الحرفي** (حبه/حبة/شدة/شده/ربطة)
  ولا تُطبّع، وتُختار الوحدة ذات **العبوة = 1**
  (`CatalogIndex.primary_unit_for_code`).

الكتابة على القرص تمر بمرحلة مؤقتة ذرية عبر
`primary_image_v2.renumber_item_images` فلا يتصادم اسم جديد باسم
قديم لملف آخر، وأي فشل يُرجع الملفات كما كانت.
"""
from __future__ import annotations

import re
from pathlib import Path

__all__ = [
    "IMAGE_SUFFIXES",
    "LegacyImage",
    "LegacyGroup",
    "RenamePlanRow",
    "LegacyPlan",
    "parse_legacy_stem",
    "scan_legacy_folder",
    "plan_legacy_renames",
    "apply_legacy_plan",
]

IMAGE_SUFFIXES = (".webp", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")

# {رقم}_{وحدة}          → واجهة
# {رقم}_{وحدة}_{عدد}    → نمط قديم (يبدأ من 2)
# {رقم}_{وحدة}-{عدد}    → قاعدة المالك (تبدأ من 1)
# اسم الباركود الجديد: 6287021750464 أو 6287021750464-1.
_RE_BARE_DASH = re.compile(r"^(?P<item>\d+)-(?P<seq>\d+)$")
_RE_DASH = re.compile(r"^(?P<item>\d+)_(?P<unit>.+?)-(?P<seq>\d+)$")
_RE_USCORE = re.compile(r"^(?P<item>\d+)_(?P<unit>.+?)_(?P<seq>\d+)$")
_RE_PLAIN = re.compile(r"^(?P<item>\d+)_(?P<unit>.+?)$")
_RE_BARE = re.compile(r"^(?P<item>\d+)$")


class LegacyImage:
    """صورة واحدة في مجلد منجز."""

    __slots__ = ("path", "item", "unit", "seq", "pattern")

    def __init__(self, path: Path, item: str, unit: str, seq: int,
                 pattern: str) -> None:
        self.path = path
        self.item = item
        self.unit = unit
        self.seq = seq          # 0 = صورة الواجهة
        self.pattern = pattern  # dash | underscore | plain | bare

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def stem(self) -> str:
        return self.path.stem

    def __repr__(self) -> str:  # pragma: no cover - تشخيص
        return (f"LegacyImage({self.path.name!r}, item={self.item!r}, "
                f"unit={self.unit!r}, seq={self.seq}, {self.pattern})")


class LegacyGroup:
    """كل صور صنف واحد مرتبة: الواجهة أولًا ثم البقية بترتيب رقمها."""

    __slots__ = ("item", "images", "unit_in_names")

    def __init__(self, item: str) -> None:
        self.item = item
        self.images: list[LegacyImage] = []
        self.unit_in_names: str = ""

    @property
    def count(self) -> int:
        return len(self.images)

    @property
    def primary(self) -> LegacyImage | None:
        return self.images[0] if self.images else None

    def sort(self) -> None:
        """الواجهة (seq=0) أولًا، ثم الأرقام تصاعديًا، ثم الاسم."""
        self.images.sort(key=lambda im: (im.seq, im.stem))
        if self.images and not self.unit_in_names:
            self.unit_in_names = self.images[0].unit

    def reorder_primary(self, path: Path) -> bool:
        """يجعل الصورة ذات المسار المعطى أول المجموعة (صورة الواجهة).

        يعيد True إن تغيّر الترتيب فعلًا.
        """
        target = str(path)
        for i, im in enumerate(self.images):
            if str(im.path) == target:
                if i == 0:
                    return False
                self.images.insert(0, self.images.pop(i))
                return True
        return False


class RenamePlanRow:
    """صف واحد في خطة التصحيح — بلا أي كتابة على القرص."""

    __slots__ = ("item", "old_path", "new_stem", "new_name", "unit",
                 "is_primary", "changed", "note", "copies")

    def __init__(self, item: str, old_path: Path, new_stem: str, unit: str,
                 is_primary: bool, note: str = "",
                 copies: list[str] | None = None) -> None:
        self.item = item
        self.old_path = old_path
        self.new_stem = new_stem
        self.new_name = f"{new_stem}{old_path.suffix}"
        self.unit = unit
        self.is_primary = is_primary
        self.changed = old_path.name != self.new_name
        self.note = note
        # 2.9.11 — جذوع إضافية تُستوفى بـ**نسخ** الملف لا بنقله
        # (سياسة «نسخة لكل وحدة» في مجلد منجز أصلًا).
        self.copies: list[str] = list(copies or [])

    def __repr__(self) -> str:  # pragma: no cover - تشخيص
        return f"{self.old_path.name} -> {self.new_name}"


class LegacyPlan:
    """خطة تصحيح كامل المجلد + إحصاءات وحالات شاذة."""

    def __init__(self) -> None:
        self.rows: list[RenamePlanRow] = []
        self.groups: dict[str, LegacyGroup] = {}
        self.missing_in_excel: list[str] = []
        self.unit_conflicts: list[tuple[str, str, str]] = []
        self.unparsed: list[Path] = []

    @property
    def changed_rows(self) -> list[RenamePlanRow]:
        return [r for r in self.rows if r.changed]

    @property
    def stats(self) -> dict:
        return {
            "images": len(self.rows),
            "items": len(self.groups),
            "changed": len(self.changed_rows),
            "missing_in_excel": len(self.missing_in_excel),
            "unit_conflicts": len(self.unit_conflicts),
            "unparsed": len(self.unparsed),
        }


def parse_legacy_stem(stem: str) -> tuple[str, str, int, str] | None:
    """يفكّك جذع الاسم إلى (رقم الصنف، الوحدة، الرقم، النمط).

    الرقم المُعاد موحّد: 0 لصورة الواجهة، و1، 2، 3… للبقية.
    النمط القديم `_2` يُترجم إلى 1 (إزاحة) حتى تتوافق المجموعتان.
    """
    s = (stem or "").strip()
    if not s:
        return None
    m = _RE_BARE_DASH.match(s)
    if m:
        return (m.group("item"), "", max(1, int(m.group("seq"))), "barcode_dash")
    m = _RE_DASH.match(s)
    if m:
        return (m.group("item"), m.group("unit"),
                max(1, int(m.group("seq"))), "dash")
    m = _RE_USCORE.match(s)
    if m:
        n = int(m.group("seq"))
        # النمط القديم يبدأ من 2 للصورة الثانية → الترتيب الموحد n-1
        return (m.group("item"), m.group("unit"), max(1, n - 1), "underscore")
    m = _RE_PLAIN.match(s)
    if m:
        unit = m.group("unit")
        # 2.9.7 — إصلاح اسم مشوّه: ملفات بالنمط البائد
        # `{رقم}_{تسلسل}` (مثل `10000121_4`) كانت تُقرأ وكأن
        # `4` **وحدة**، فتُلحَق بها الوحدة الحقيقية فينتج
        # `10000121_4_حبه` — وهو اسم لا وجود لوحدته `4` في
        # كتالوج المالك (وحدة الصنف `حبه` فقط، مفحوصًا).
        # الأرقام المحضة لا تكون وحدة قطعًا، فهي تسلسل.
        if unit.strip().isdigit():
            return (m.group("item"), "", max(1, int(unit.strip())),
                    "underscore")
        return (m.group("item"), unit, 0, "plain")
    m = _RE_BARE.match(s)
    if m:
        return (m.group("item"), "", 0, "bare")
    return None


def _parse_catalog_barcode_stem(stem: str, index) -> tuple[str, str, int, str] | None:
    """يفك اسمًا ناتجًا من وضع «باركود Excel» إلى رقم الصنف.

    لا تفترض أن الباركود رقمي فقط؛ بعض ملفات Excel التجارية تحتوي
    مراجع مثل ``006-090`` أو ``3P-DT-10``. نعطي المطابقة الكاملة
    أولوية، ثم نفصل لاحقة التسلسل النهائية ``-1`` فقط إذا كان المرجع
    قبلها باركودًا موجودًا حرفيًا في Excel. هكذا لا نخلط ``-10``
    الموجود داخل الباركود مع رقم صورة.
    """
    if index is None:
        return None
    raw = str(stem or "").strip()
    if not raw:
        return None

    def lookup(value: str):
        try:
            return index.lookup_barcode(value)
        except Exception:
            return None

    record = lookup(raw)
    if record and record.get("code"):
        return (str(record["code"]), "", 0, "catalog_barcode")

    # الصيغة المعتمدة الجديدة: ``barcode_unit`` ثم ``barcode_unit-1``.
    # نقسم من اليمين فقط كي لا نكسر باركودًا يحوي شرطات داخلية.
    ref, underscore, unit_part = raw.rpartition("_")
    if underscore and ref and unit_part:
        unit = unit_part
        seq = 0
        unit_base, dash, tail = unit_part.rpartition("-")
        if dash and unit_base and tail.isdigit():
            unit, seq = unit_base, max(1, int(tail))
        record = lookup(ref)
        if record and record.get("code"):
            return (str(record["code"]), unit, seq,
                    "catalog_barcode_unit")

    ref, dash, suffix = raw.rpartition("-")
    if dash and ref and suffix.isdigit():
        record = lookup(ref)
        if record and record.get("code"):
            return (str(record["code"]), "", max(1, int(suffix)),
                    "catalog_barcode_dash")
    return None


def scan_legacy_folder(folder: str | Path,
                       suffixes: tuple[str, ...] = IMAGE_SUFFIXES,
                       index=None
                       ) -> tuple[dict[str, LegacyGroup], list[Path]]:
    """يمسح مجلدًا منجزًا ويجمع صوره برقم الصنف.

    يعيد (المجموعات مرتبة، الملفات التي لم تُفهم أسماؤها).
    الملفات الشقيقة بنفس الجذع (png بجانب webp) تُعدّ صورة واحدة
    فيُختار الامتداد الأول أبجديًا ويُدار الباقي مع الجذع تلقائيًا.
    """
    folder = Path(folder)
    groups: dict[str, LegacyGroup] = {}
    unparsed: list[Path] = []
    if not folder.is_dir():
        return groups, unparsed

    seen_stems: set[str] = set()
    for path in sorted(folder.iterdir(), key=lambda p: p.name):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        if path.name.startswith("__primary_tmp_"):
            continue
        # مسودات المحرر ``*.edited.png`` ليست مخرجات نهائية بل
        # نسخ عمل جانبية يحفظها المحرر بجوار الأصل. لو دخلت
        # خطة التسمية لعُدَّت صورة ثانية للصنف (فتختل الأرقام)
        # ولأن لاحقتها مزدوجة يبقى ``.edited`` في الجذع فتفشل
        # إعادة التسمية بخطأ مسار غير موجود. نتجاوزها في
        # المحرك نفسه لا في الواجهة وحدها، لتسلم كل مسارات الاستدعاء.
        if path.name.lower().endswith(".edited.png"):
            continue
        stem = path.stem
        if stem in seen_stems:
            continue
        # مصدر Excel مقدّم على تحليل الاسم القديم: ``006-090-1``
        # قد يطابق شكليًا «رقم_وحدة-تسلسل» لكنه في الحقيقة باركود
        # ``006-090`` وصورته الثانية. لا تخمين ولا OCR هنا.
        parsed = _parse_catalog_barcode_stem(stem, index)
        if parsed is None:
            parsed = parse_legacy_stem(stem)
        if parsed is None:
            unparsed.append(path)
            continue
        seen_stems.add(stem)
        item, unit, seq, pattern = parsed
        # عند فتح مجلد سُمّي بالباركود، نعيده إلى code من Excel كي
        # تتجمع الصور وتُربط بنفس الصنف مثل سياق الملفات السابق.
        if index is not None:
            try:
                record = index.lookup_code(item) or index.lookup_barcode(item)
                if record and record.get("code"):
                    item = str(record["code"])
            except Exception:
                pass
        grp = groups.get(item)
        if grp is None:
            grp = groups[item] = LegacyGroup(item)
        grp.images.append(LegacyImage(path, item, unit, seq, pattern))

    for grp in groups.values():
        grp.sort()
    return groups, unparsed


def _naming_settings():
    """يقرأ إعدادات التسمية المحفوظة — **نفس مصدر الدفعة الجديدة**.

    2.9.6 (قرار المالك): «اجعله في الدفعة الجديدة والقديمة، كل
    التعديلات يجب أن تُنفّذ في الاثنين». كان هذا الملف
    يتجاهل `unit_policy` تمامًا فيبقى المجلد المنجز بوحدة واحدة
    مهما تغيرت الإعدادات.
    """
    try:
        from .integration_v2 import _current_naming_settings
        return _current_naming_settings()
    except Exception:
        return None


def _units_for_group(item: str, index, unit_in_name: str,
                     excel_order: bool = True) -> list[str]:
    """وحدات الصنف للتسمية — **منطق مطابق حرفًا بحرف**
    لما تفعله الدفعة الجديدة في `integration_v2._units_from_catalog`.

    2.9.10: الافتراضي ``excel_order=True`` لأن مستدعيها الوحيد
    هو مسار الدمج (``join_all``)، وأمر المالك فيه: الوحدات
    «بنفس ترتيبها» في الإكسل. تصدير وحدة العبوة=1 كان يقلب
    الترتيب، فيخرج المجلد المنجز ``حبه_كرتون_شدة`` حين يقول
    الإكسل ``حبه_شدة_كرتون``. يبقى ``excel_order=False`` متاحًا
    لمن يحتاج اختيار وحدة الصورة الواحدة.
    """
    from .naming_v2 import dedupe_units, unit_key
    if index is None:
        return [unit_in_name] if unit_in_name else []
    try:
        units = [str(u) for u in index.units_for_code(str(item))
                 if str(u or "").strip()]
    except Exception:
        units = []
    if not units:
        return []
    if not excel_order:
        primary = ""
        try:
            primary = str(index.primary_unit_for_code(str(item)) or "")
        except Exception:
            primary = ""
        if primary:
            key = unit_key(primary)
            units = [primary] + [u for u in units if unit_key(u) != key]
    return dedupe_units(units)


def _target_stems_policy(item: str, units: list[str], count: int,
                         settings, fallback_unit: str = "", barcode: str = ""
                         ) -> list[list[str]]:
    """أسماء المجموعة عبر **نفس دالة الدفعة الجديدة**.

    يعيد لكل صورة قائمة أسمائها (تتعدد فقط مع ``replicate_all_units``).

    2.9.11: قبله كان هذا الملف يختزل السياسة في علم منطقي
    ``join_all`` واحد، فلا يعرف ``replicate_all_units`` ولا
    ``default_unit`` — فيُعاملهما معاملة ``per_image`` بوحدة واحدة.
    وذلك خالف أمر المالك: «اجعله في الدفعة الجديدة والقديمة».
    """
    from .naming_v2 import plan_stems_for_policy, NamingSettings

    if settings is None:
        settings = NamingSettings()
    unit_list = [u for u in (units or []) if str(u or "").strip()]
    if not unit_list and fallback_unit:
        unit_list = [fallback_unit]
    return [plan_stems_for_policy(item, unit_list, seq=i + 1, total=count,
                                  settings=settings,
                                  chosen_unit=fallback_unit, barcode=barcode)
            for i in range(count)]


def _target_stems(item: str, unit: str, count: int,
                  units: list[str] | None = None,
                  join_all: bool = False) -> list[str]:
    """أسماء المجموعة وفق قاعدة المالك: الواجهة بلا رقم ثم -2، -3…

    2.9.6: يمر عبر `build_name_join_all` — **نفس دالة الدفعة
    الجديدة** — لا بناء يدوي، فيتطابق المخرجان حرفًا بحرف.
    وذلك يُكسب المجلد المنجز تلقائيًا كل معالجات `clean_unit`
    (حذف المسافة: `كرتون 1` ← `كرتون1`) و`normalize_stem`.
    """
    from .naming_v2 import build_name_join_all, clean_unit

    if join_all:
        unit_list = [u for u in (units or []) if str(u or "").strip()]
        if not unit_list and unit:
            unit_list = [unit]
        if unit_list:
            return [build_name_join_all(item, unit_list, seq=i + 1,
                                        total=count)
                    for i in range(count)]

    # سياسة الوحدة الواحدة — تمر بنفس الدالة بوحدة واحدة
    # لتكتسب clean_unit وnormalize_stem بدل الوصل النصي الخام.
    u = clean_unit(unit)
    if not u:
        # 2.9.9 — مسار الطوارئ (لا وحدة في الإكسل ولا في اسم
        # الملف). كان `f"{base}-{i}"` يُعطي الثانية `-1` خلافًا
        # لقاعدة المالك المقرّرة (الأولى بلا رقم، الثانية `-2`)،
        # وهو مسار المجلد المنجز الذي يستخدمه المالك فعلًا.
        base = str(item)
        return [base if i == 0 else f"{base}-{i + 1}"
                for i in range(count)]
    return [build_name_join_all(item, [u], seq=i + 1, total=count)
            for i in range(count)]


def plan_legacy_renames(groups: dict[str, LegacyGroup], index=None,
                        unparsed: list[Path] | None = None) -> LegacyPlan:
    """يبني خطة التصحيح من الإكسل بلا أي كتابة على القرص.

    index: `CatalogIndex` محمّل. إن كان None تُستخدم الوحدة الموجودة
    في اسم الملف (فلا يتعطل العمل بغياب الإكسل).
    """
    from .naming_v2 import (UNIT_POLICY_JOIN_ALL, UNIT_POLICY_REPLICATE,
                            UNIT_POLICY_DEFAULT)

    plan = LegacyPlan()
    plan.groups = groups
    plan.unparsed = list(unparsed or [])

    # 2.9.6: المجلد المنجز يتبع نفس سياسة الدفعة الجديدة.
    # 2.9.11: والسياسة تُقرأ كاملة لا كعلم منطقي واحد.
    settings = _naming_settings()
    active = bool(settings is not None and getattr(settings, "enabled", True))
    policy = str(getattr(settings, "unit_policy", "")) if active else ""
    join_all = policy == UNIT_POLICY_JOIN_ALL
    # السياسات التي تحتاج كل وحدات الإكسل بترتيبه الحرفي.
    needs_units = policy in (UNIT_POLICY_JOIN_ALL, UNIT_POLICY_REPLICATE,
                             UNIT_POLICY_DEFAULT)
    barcode_mode = str(getattr(settings, "reference_mode", "item_code")) == "barcode"

    for item in sorted(groups):
        grp = groups[item]
        unit_in_name = grp.unit_in_names
        unit = unit_in_name
        units: list[str] = []
        note = ""
        barcode = ""
        if index is not None:
            try:
                rows_for_code = list(index.rows_for_code(item) or [])
                barcode = next((str(r.get("barcode", "") or "").strip()
                                for r in rows_for_code if str(r.get("barcode", "") or "").strip()), "")
            except Exception:
                barcode = ""
            try:
                excel_unit = str(index.primary_unit_for_code(item) or "")
            except Exception:
                excel_unit = ""
            if excel_unit:
                unit = excel_unit
                if unit_in_name and excel_unit != unit_in_name:
                    from .naming_v2 import unit_key
                    if unit_key(excel_unit) != unit_key(unit_in_name):
                        plan.unit_conflicts.append(
                            (item, unit_in_name, excel_unit))
                        note = (f"الإكسل يقول {excel_unit} واسم الملف "
                                f"{unit_in_name} — اعتُمد الإكسل")
            else:
                plan.missing_in_excel.append(item)
                note = "غير موجود في الإكسل — أُبقيت وحدة اسم الملف"

        if needs_units:
            units = _units_for_group(item, index, unit_in_name)
            if units and join_all:
                # الوحدة المعروضة في الجدول = المجموع لا واحدة،
                # ليرى المالك ما سيكتَب فعلًا في اسم الملف.
                from .naming_v2 import join_units
                unit = join_units(units)
                if len(units) > 1 and not note:
                    note = (f"وحدات الإكسل المجموعة: "
                            f"{'، '.join(units)}")

        if barcode_mode and not barcode:
            plan.missing_in_excel.append(item)
            note = "لا باركود لهذا الصنف في Excel — لم يُعد تسمية الملف"
            names = [[im.stem] for im in grp.images]
        elif active:
            # مسار السياسات الأربع — نفس دالة الدفعة الجديدة.
            names = _target_stems_policy(item, units, grp.count, settings,
                                         fallback_unit=unit, barcode=barcode)
        else:
            names = [[s] for s in _target_stems(item, unit, grp.count,
                                                units=units,
                                                join_all=join_all)]

        extra_note = ""
        if policy == UNIT_POLICY_REPLICATE and units and len(units) > 1:
            extra_note = (f"نسخة لكل وحدة: {'، '.join(units)} — "
                          f"تُنشأ نُسخٌ إضافية من الصورة نفسها")

        for i, im in enumerate(grp.images):
            stems_i = names[i] if i < len(names) else [im.stem]
            row_note = note if i == 0 else ""
            if i == 0 and extra_note:
                row_note = f"{row_note} — {extra_note}" if row_note \
                    else extra_note
            row = RenamePlanRow(
                item=item, old_path=im.path, new_stem=stems_i[0], unit=unit,
                is_primary=(i == 0), note=row_note)
            # 2.9.11 — سياسة «نسخة لكل وحدة» في المجلد المنجز:
            # الملف القائم يُعاد تسميته للوحدة الأولى، وبقية
            # الوحدات تُستوفى بـ**نسخ** الملف لا بنقله، لأن
            # الصورة موجودة أصلًا ولا يجوز فقدانها.
            row.copies = list(stems_i[1:])
            plan.rows.append(row)
    return plan


def _materialize_copies(rows: list[RenamePlanRow],
                        renames: dict[str, str] | None = None
                        ) -> tuple[dict[str, list[str]], list[str]]:
    """يستوفي وحدات سياسة «نسخة لكل وحدة» بـ**نسخ** الملف.

    في الدفعة الجديدة تُكتب النسخ وقت المعالجة؛ أمّا المجلد
    المنجز فالصورة فيه موجودة أصلًا، فالوحدة الأولى تُستوفى
    بإعادة التسمية والبقية بالنسخ. **لا يُحذف ولا يُكتب فوق
    ملف قائم** بأي حال، فإن وجد الهدف عُدّ مستوفًى.

    ``renames`` خريطة إعادة التسمية التي تمّت توّا — لازمة لأن
    ``row.old_path`` يصير مسارًا معدومًا بعد النقل الذري، فلو
    نُسخ منه لما وجدنا ملفًا أصلًا (أو نُسخ من ملف صنف آخر
    صار يحمل ذات الاسم). ويُعاد القاموس مفتاحُه المصدر
    وقيمته **قائمة** النسخ، لا نسخة واحدة تطمس أختها.
    """
    import shutil

    made: dict[str, list[str]] = {}
    errs: list[str] = []
    renames = renames or {}
    for r in rows:
        wanted = list(getattr(r, "copies", ()) or ())
        if not wanted:
            continue
        # الملف بعد إعادة التسمية لا قبلها.
        src = Path(renames.get(str(r.old_path), str(r.old_path)))
        if not src.is_file():
            src = r.old_path.with_name(r.new_name)
        if not src.is_file():
            errs.append(f"{r.item}: مصدر النسخ غير موجود "
                        f"({r.new_name})")
            continue
        for stem in wanted:
            dst = src.with_name(f"{stem}{src.suffix}")
            if dst.exists():
                continue
            try:
                shutil.copy2(str(src), str(dst))
                made.setdefault(str(src), []).append(str(dst))
            except OSError as exc:
                errs.append(f"{r.item}: تعذّر نسخ {dst.name} — {exc}")
    return made, errs


def apply_legacy_plan(plan: LegacyPlan,
                      items: list[str] | None = None) -> dict:
    """ينفّذ الخطة على القرص عبر إعادة تسمية ذرية لكل صنف.

    items: أرقام أصناف محددة، أو None لكل المجلد.
    يعيد {"renames": {...}, "errors": [...], "items_done": n,
    "copies": {...}}. و`copies` تمتلئ فقط مع سياسة «نسخة لكل
    وحدة» (2.9.11).
    """
    from .primary_image_v2 import renumber_item_images

    wanted = set(items) if items else None
    renames: dict[str, str] = {}
    copies: dict[str, list[str]] = {}
    errors: list[str] = []
    done = 0

    for item in sorted(plan.groups):
        if wanted is not None and item not in wanted:
            continue
        grp = plan.groups[item]
        if not grp.images:
            continue
        rows = [r for r in plan.rows if r.item == item]
        if not any(r.changed for r in rows):
            continue
        unit = rows[0].unit if rows else grp.unit_in_names
        paths = [im.path for im in grp.images]
        out_dir = paths[0].parent
        # 2.9.6: تُمرّر جذوع الخطة نفسها لا الوحدة وحدها.
        # كان `renumber_item_images` يعيد بناء الاسم من الوحدة
        # فيختلف عن خطة المعاينة التي رأى المالك في الجدول
        # (ومع الوحدة المجموعة `حبه_كرتون_شدة` كان ينتج
        # `10001633_حبه_كرتون_شدة_حبه_كرتون_شدة` مكررًا).
        stems = [r.new_stem for r in rows]
        res = renumber_item_images(out_dir, item, paths, [unit] if unit
                                   else [], settings=None,
                                   target_stems=stems)
        if not res.ok:
            errors.append(f"{item}: {res.error}")
            continue
        renames.update(res.renames)
        done += 1
        # حدّث المسارات داخل المجموعة حتى تبقى الخطة صالحة بعد التنفيذ
        for im in grp.images:
            new = res.renames.get(str(im.path))
            if new:
                im.path = Path(new)
        # 2.9.11 — استيفاء الوحدات الباقية بالنسخ
        made, copy_errs = _materialize_copies(rows, res.renames)
        for k, v in made.items():
            copies.setdefault(k, []).extend(v)
        errors.extend(copy_errs)

    return {"renames": renames, "errors": errors, "items_done": done,
            "copies": copies}


# ═══════════════════════════════════════════════════════════════════
# 2.9.7 — تثبيت حالة المهمة للمجلد المنجز  (يغلق A1 + A4)
# ═══════════════════════════════════════════════════════════════════
# العلة المقيسة: `_load_legacy_folder` كان يبني `BatchRunResult` في
# الذاكرة فقط ولا يكتب `job_state.json` ولا يودع المصادر. فكانت
# النتيجة عرضين لعلة واحدة:
#
#   A4 — تعديل الباركود/التسمية على الملفات السابقة يفشل فورًا:
#        `_load_state` ترفع
#        `FileNotFoundError: ملف حالة المهمة غير موجود`.
#   A1 — «إعلان فقدان زائف»: `repair_job_state` لا تجد حالة فتُبلّغ
#        عن فقدان والصور موجودة سليمة على القرص.
#
# القياس قبل الإصلاح (12 صورة من مخرجات المالك، 5 أصناف):
#   job_state.json: غير موجود ✗ | .mis_sources: غير موجودة ✗
#   _load_state:    FileNotFoundError ✗
#
# الإصلاح يمر عبر `pipeline._write_state` **نفسها** التي تستخدمها
# الدفعة الجديدة، فيكون ملف الحالة مطابقًا حرفًا بحرف لما ينتجه
# المسار الطبيعي، وتقرأه كل الوظائف الموجودة بلا أي تعديل فيها.
#
# صمَّمناها لا ترفع استثناءً أبدًا: فتح المجلد لعرض الصور يجب أن
# ينجح حتى إن كان القرص للقراءة فقط، فتُعاد رسالة سبب لا انهيار.

__all__ += ["ensure_legacy_job_state"]


def _records_from_result(result):
    """يبني سجلات كاتالوج من الصور نفسها عند غياب الإكسل.

    قرار المالك: «الملف الرئيسي يجب أن يكون مرنًا لأي تعديل
    مهما كان مصدر المعلومة» — فلا يُشلّ التعديل لمجرد أن
    الإكسل لم يُحمّل. أرقام الأصناف موجودة أصلاً في أسماء
    الملفات المنجزة، فتكفي لبناء فهرس عامل.

    يُزال التكرار برقم الصنف لأن للصنف عدة صور.
    """
    from smart_catalog_vision.pipeline import _CatalogRecord

    seen: dict[str, _CatalogRecord] = {}
    row = 0
    for it in getattr(result, "items", ()) or ():
        code = str(getattr(it, "item_code", "") or "").strip()
        if not code or code in seen:
            continue
        row += 1
        name = str(getattr(it, "product_name", "") or "").strip()
        unit = ""
        # الوحدة مدوّنة في الشرح بصيغة «— الوحدة: حبه»
        expl = str(getattr(it, "explanation", "") or "")
        if " الوحدة: " in expl:
            unit = expl.split(" الوحدة: ", 1)[1].split("\n", 1)[0].strip()
        seen[code] = _CatalogRecord(
            item_code=code,
            product_name=name or f"الصنف {code}",
            barcode=str(getattr(it, "barcode", "") or "").strip(),
            unit=unit,
            sheet="legacy_folder",
            row=row)
    return tuple(seen.values())


def _legacy_catalog_for_state(index, result=None):
    """يعيد كاتالوجًا **غير فارغ** لـ`_write_state`.

    علة مقيسة (الحاجز الثاني تحت A4): بعد كتابة الحالة
    بكاتالوج فارغ ترفع `_load_state`
    `ValueError: فهرس الكتالوج في المهمة فارغ` فيبقى تعديل
    الباركود متعطلًا. فإن غاب الإكسل نبني الفهرس من أرقام
    الأصناف المستخرجة من أسماء الصور نفسها.
    """
    from smart_catalog_vision.pipeline import _CatalogIndex

    if index is not None:
        records = getattr(index, "records", None)
        if records:
            return index
    records = _records_from_result(result) if result is not None else ()
    return _CatalogIndex(
        records=records,
        summary={"source": "legacy_folder", "rows": len(records),
                 "origin": "مستخرج من أسماء الصور المنجزة"})


def ensure_legacy_job_state(folder, result, index=None, catalog_path="",
                            options=None,
                            profile_name="كتالوج برنامج Windows") -> dict:
    """يكتب `job_state.json` حقيقيًا لمجلد منجز ويودع مصادره.

    يُستدعى مرة واحدة عقب فتح المجلد المنجز، فيصبح المجلد مساحة عمل
    كاملة الصلاحية: تعديل الباركود يعمل، وفاحص السلامة يجد حالته
    فلا يُعلن فقدانًا زائفًا.

    يعيد تقريرًا: {"state_written": bool, "vault_deposited": bool,
    "images": int, "error": str}. ولا يرفع استثناءً أبدًا.
    """
    report = {"state_written": False, "vault_deposited": False,
              "images": 0, "error": ""}
    try:
        folder = Path(folder)
    except Exception as exc:  # pragma: no cover - مسار غير صالح
        report["error"] = f"مسار غير صالح: {exc}"
        return report
    if result is None:
        report["error"] = "لا نتيجة لكتابتها"
        return report

    # ── 1) إيداع الصور في الخزانة ──────────────────────────────────
    # في المجلد المنجز الملف نفسه هو المصدر وهو المخرج، فإيداعه
    # يحمي التعديل اللاحق إن نُقل المجلد أو حُذف أصله.
    image_paths: list[str] = []
    for it in getattr(result, "items", ()) or ():
        sp = getattr(it, "source_path", "") or ""
        if sp:
            image_paths.append(str(sp))
    report["images"] = len(image_paths)
    if image_paths:
        try:
            from .source_vault_v2 import deposit_job_sources
            deposit_job_sources(folder, image_paths, catalog_path or "")
            report["vault_deposited"] = True
        except Exception as exc:
            # الإيداع تحسين للمتانة لا شرط لعمل التعديل.
            report["error"] = f"تعذّر إيداع الخزانة: {exc}"

    # ── 2) كتابة حالة المهمة بنفس دالة الدفعة الجديدة ─────────────
    try:
        from smart_catalog_vision.pipeline import (FinalImageOptions,
                                                   _write_state)
        opts = options
        if opts is None:
            # افتراضات المالك المعتمدة: 800×700 بخلفية بيضاء.
            opts = FinalImageOptions(width=800, height=700)
        cat_p = Path(catalog_path) if catalog_path else folder / "catalog.xlsx"
        _write_state(folder,
                     catalog_path=cat_p,
                     catalog=_legacy_catalog_for_state(index, result),
                     result=result,
                     profile_name=profile_name,
                     options=opts)
        report["state_written"] = (folder / "job_state.json").is_file()
    except Exception as exc:
        report["error"] = f"تعذّر كتابة حالة المهمة: {exc}"
    return report
