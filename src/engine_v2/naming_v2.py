# -*- coding: utf-8 -*-
"""Unified naming system for V2.

One flexible rule applied to every case (single image, pair, or many):
    first image  -> {item}_حبه.webp
    second image -> {item}_2_حبه.webp
    third image  -> {item}_3_حبه.webp  ... and so on.

The unit is written VERBATIM as it appears in the Excel file
(حبه/حبة/شده/شدة/كرتون/باكت...). Supports the legacy 1.2.1 pattern
(item_حبه_2) transparently for bulk-renaming old folders.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

UNIT_SUFFIX_DEFAULT = "حبه"

# canonical: 10018435_حبه / 10018435_2_حبه / 10018435_3_حبه
NAME_RE = re.compile(
    r"^(?P<item>[A-Za-z0-9\-]+?)(?:_(?P<seq>\d+))?_(?P<unit>[^_.]+)$"
)
# legacy variant produced by 1.2.1: 10018435_حبه_2 (suffix before number)
LEGACY_NAME_RE = re.compile(
    r"^(?P<item>[A-Za-z0-9\-]+?)_(?P<unit>[^_.]+?)(?:_(?P<seq>\d+))?$"
)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


@dataclass
class ParsedName:
    item: str
    seq: int          # 1 for the base image (no explicit number)
    unit: str

    def render(self) -> str:
        if self.seq <= 1:
            return f"{self.item}_{self.unit}"
        return f"{self.item}_{self.seq}_{self.unit}"


_UNSAFE_CHARS = '/\\:*?"<>|\x00'
_MAX_ITEM_LEN = 120  # يضمن اسمًا نهائيًا < 260 محرفًا على Windows


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
    """Build the canonical stem for image `seq` of item `item`."""
    item = sanitize_item(item)
    unit = sanitize_item(str(unit)) if unit else UNIT_SUFFIX_DEFAULT
    if seq <= 1:
        return f"{item}_{unit}"
    return f"{item}_{seq}_{unit}"


def parse_name(stem: str) -> ParsedName | None:
    """Parse an existing file stem back into (item, seq, unit).

    Accepts both the canonical V2 pattern (item_2_unit) and the legacy
    1.2.1 pattern (item_unit_2).
    """
    stem = stem.strip()
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
                     unit: str = UNIT_SUFFIX_DEFAULT) -> list[str]:
    """Names for a whole group of `count` images of one item (1-based order)."""
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
                     fix_encoding: bool = True) -> list[RenamePlanEntry]:
    """Plan the normalization of a previously produced results folder.

    - fixes mojibake names
    - normalizes legacy (item_unit_2) to canonical (item_2_unit)
    - applies old->new item-number mapping while keeping groups linked
    """
    folder = Path(folder)
    entries: list[RenamePlanEntry] = []
    taken: set[str] = set()
    files = [p for p in sorted(folder.iterdir())
             if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    for p in files:
        stem = p.stem
        if fix_encoding:
            stem = unmojibake(stem)
        parsed = parse_name(stem)
        if parsed is None:
            entries.append(RenamePlanEntry(p.name, "", "unparsed"))
            continue
        item = mapping.get(parsed.item, parsed.item)
        new_stem = build_name(item, parsed.seq, parsed.unit)
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
VALID_POLICIES = ("per_image", "replicate_all_units", "default_unit")


@dataclass
class NamingSettings:
    """سياسة الوحدات وقالب التسمية العام."""
    unit_policy: str = "per_image"       # per_image | replicate_all_units | default_unit
    default_unit: str = UNIT_SUFFIX_DEFAULT
    template: str = "{item}_{seq}_{unit}"   # seq يُحذف تلقائيًا للصورة الأولى

    def render(self, item: str, seq: int, unit: str) -> str:
        if seq <= 1:
            tpl = self.template.replace("_{seq}", "").replace("{seq}_", "") \
                               .replace("{seq}", "")
            return tpl.format(item=item, unit=unit)
        return self.template.format(item=item, seq=seq, unit=unit)

    def to_dict(self) -> dict:
        return {"unit_policy": self.unit_policy,
                "default_unit": self.default_unit,
                "template": self.template}

    @classmethod
    def from_dict(cls, d: dict) -> "NamingSettings":
        s = cls()
        s.unit_policy = d.get("unit_policy", s.unit_policy)
        if s.unit_policy not in VALID_POLICIES:
            s.unit_policy = "per_image"
        s.default_unit = d.get("default_unit", s.default_unit)
        s.template = d.get("template", s.template)
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


def plan_names_for_item(item: str, image_count: int, units: list[str],
                        settings: NamingSettings,
                        chosen_unit: str = "") -> list[list[str]]:
    """أسماء صور صنف واحد وفق السياسة.

    يعيد قائمة لكل صورة: قائمة الأسماء المطلوبة لها (قد تتعدد مع replicate).
    """
    units = [u for u in units if u] or [settings.default_unit]
    result: list[list[str]] = []
    for i in range(image_count):
        seq = i + 1
        if settings.unit_policy == "replicate_all_units":
            result.append([settings.render(item, seq, u) for u in units])
        elif settings.unit_policy == "default_unit":
            result.append([settings.render(item, seq, settings.default_unit)])
        else:  # per_image
            unit = chosen_unit or units[0]
            result.append([settings.render(item, seq, unit)])
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
