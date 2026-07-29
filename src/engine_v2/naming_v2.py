# -*- coding: utf-8 -*-
"""Unified naming system for V2.2.

Two ready-made schemes plus a custom template:

1. ``dash`` (الجديد — الافتراضي بطلب المستخدم):
       صورة واحدة فقط -> {item}_{unit}
       أكثر من صورة   -> {item}_{unit}-1 , {item}_{unit}-2 ...
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
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

UNIT_SUFFIX_DEFAULT = "حبه"

# canonical 2.1: 10018435_حبه / 10018435_2_حبه / 10018435_3_حبه
NAME_RE = re.compile(
    r"^(?P<item>[A-Za-z0-9\-]+?)(?:_(?P<seq>\d+))?_(?P<unit>[^_.]+)$"
)
# legacy variant produced by 1.2.1: 10018435_حبه_2 (suffix before number)
LEGACY_NAME_RE = re.compile(
    r"^(?P<item>[A-Za-z0-9\-]+?)_(?P<unit>[^_.]+?)(?:_(?P<seq>\d+))?$"
)
# new 2.2 dash scheme: 10018435_حبه-2 (dash before the sequence)
DASH_NAME_RE = re.compile(
    r"^(?P<item>[A-Za-z0-9]+?)_(?P<unit>[^_.\-]+?)-(?P<seq>\d+)$"
)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}

SCHEME_DASH = "dash"        # الجديد الموصى به
SCHEME_CLASSIC = "classic"  # نمط 2.1
SCHEME_CUSTOM = "custom"
VALID_SCHEMES = (SCHEME_DASH, SCHEME_CLASSIC, SCHEME_CUSTOM)


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


def clean_unit(unit: str) -> str:
    """تعقيم قيمة الوحدة القادمة من الإكسل أو الإدخال اليدوي:
    إزالة الشرطات السفلية والمسافات الطرفية التي كانت تولّد `__حبه`."""
    return str(unit or "").strip().strip("_").strip()


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
    """النمط الجديد (2.2) بالشرطة:

    - صورة واحدة فقط (total<=1):     {item}_{unit}
    - أكثر من صورة: كل صورة تأخذ رقمًا {item}_{unit}-{seq} بدءًا من -1.
    """
    item = sanitize_item(item)
    unit = clean_unit(sanitize_item(str(unit))) if unit else ""
    unit = unit or UNIT_SUFFIX_DEFAULT
    if total <= 1 and seq <= 1:
        return normalize_stem(f"{item}_{unit}")
    return normalize_stem(f"{item}_{unit}") + f"-{max(1, seq)}"


def parse_name(stem: str) -> ParsedName | None:
    """Parse an existing file stem back into (item, seq, unit).

    Accepts the dash pattern (item_unit-2), the canonical V2 pattern
    (item_2_unit) and the legacy 1.2.1 pattern (item_unit_2).
    """
    stem = normalize_stem(stem)
    m = DASH_NAME_RE.match(stem)
    if m and not m.group("unit").isdigit():
        return ParsedName(m.group("item"), int(m.group("seq")),
                          m.group("unit"))
    m = NAME_RE.match(stem)
    if m and not m.group("unit").isdigit():
        seq = int(m.group("seq")) if m.group("seq") else 1
        return ParsedName(m.group("item"), seq, m.group("unit"))
    m = LEGACY_NAME_RE.match(stem)
    if m and not m.group("unit").isdigit():
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
VALID_POLICIES = (UNIT_POLICY_PER_IMAGE, UNIT_POLICY_REPLICATE,
                  UNIT_POLICY_DEFAULT)

TEMPLATE_DASH = "{item}_{unit}-{seq}"
TEMPLATE_CLASSIC = "{item}_{seq}_{unit}"

SCHEME_LABELS_AR = {
    SCHEME_DASH: "النمط الجديد (موصى به): رقم الصنف_الوحدة-1 / -2 — وبلا رقم للصورة الوحيدة",
    SCHEME_CLASSIC: "النمط الكلاسيكي 2.1: رقم الصنف_الوحدة ثم رقم الصنف_2_الوحدة",
    SCHEME_CUSTOM: "قالب مخصص أكتبه بنفسي أو أختاره من القوالب الجاهزة",
}

# قوالب جاهزة للمتاجر والمواقع — تظهر في قائمة الاختيار السريع
# المتغيرات المتاحة: {item} {unit} {seq} {barcode} {name}
STORE_TEMPLATES: list[tuple[str, str]] = [
    ("رقم الصنف_الوحدة-رقم الصورة (الموصى به)", "{item}_{unit}-{seq}"),
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
    unit_policy: str = "per_image"       # per_image | replicate_all_units | default_unit
    default_unit: str = UNIT_SUFFIX_DEFAULT
    template: str = TEMPLATE_DASH
    scheme: str = SCHEME_DASH
    enabled: bool = True
    seq_start: int = 1            # بدء الترقيم (1 أو 0)
    seq_pad: int = 0              # أصفار بادئة: 0=بلا، 2=01،02...
    always_number_single: bool = False  # رقّم حتى الصورة الوحيدة

    def _fmt_seq(self, seq: int) -> str:
        n = max(0, seq - 1) + max(0, int(self.seq_start))
        return str(n).zfill(int(self.seq_pad)) if self.seq_pad else str(n)

    def render(self, item: str, seq: int, unit: str, total: int = 0,
               barcode: str = "", name: str = "") -> str:
        """اسم صورة واحدة. ``total`` = عدد صور المجموعة إن عُرف (لنمط الشرطة)."""
        item = sanitize_item(item)
        unit = clean_unit(unit) or self.default_unit or UNIT_SUFFIX_DEFAULT
        if self.scheme == SCHEME_DASH:
            if self.always_number_single and total <= 1 and seq <= 1:
                return normalize_stem(f"{item}_{unit}") + \
                    f"-{self._fmt_seq(seq)}"
            return build_name_dash(item, seq, unit, total=total or seq)
        if self.scheme == SCHEME_CLASSIC:
            return build_name(item, seq, unit)
        # custom template — يدعم {item} {unit} {seq} {barcode} {name}
        safe_name = sanitize_item(str(name or "")).replace(" ", "-")
        values = {"item": item, "unit": unit,
                  "seq": self._fmt_seq(seq),
                  "barcode": sanitize_item(str(barcode or "")),
                  "name": safe_name}
        single = (total <= 1 and seq <= 1
                  and not self.always_number_single)
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
                "default_unit": self.default_unit,
                "template": self.template,
                "scheme": self.scheme,
                "enabled": bool(self.enabled),
                "seq_start": int(self.seq_start),
                "seq_pad": int(self.seq_pad),
                "always_number_single": bool(self.always_number_single)}

    @classmethod
    def from_dict(cls, d: dict) -> "NamingSettings":
        s = cls()
        s.unit_policy = d.get("unit_policy", s.unit_policy)
        if s.unit_policy not in VALID_POLICIES:
            s.unit_policy = "per_image"
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


def plan_names_for_item(item: str, image_count: int, units: list[str],
                        settings: NamingSettings,
                        chosen_unit: str = "") -> list[list[str]]:
    """أسماء صور صنف واحد وفق السياسة.

    يعيد قائمة لكل صورة: قائمة الأسماء المطلوبة لها (قد تتعدد مع replicate —
    الأصناف التي لها حبة وشدة وكرتون معًا تأخذ اسمًا لكل وحدة).
    """
    units = [u for u in units if u] or [settings.default_unit]
    result: list[list[str]] = []
    for i in range(image_count):
        seq = i + 1
        if settings.unit_policy == "replicate_all_units":
            result.append([settings.render(item, seq, u, total=image_count)
                           for u in units])
        elif settings.unit_policy == "default_unit":
            result.append([settings.render(item, seq, settings.default_unit,
                                           total=image_count)])
        else:  # per_image
            unit = chosen_unit or units[0]
            result.append([settings.render(item, seq, unit,
                                           total=image_count)])
    return result


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
