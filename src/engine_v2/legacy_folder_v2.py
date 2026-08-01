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

import os
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
                 "is_primary", "changed", "note")

    def __init__(self, item: str, old_path: Path, new_stem: str, unit: str,
                 is_primary: bool, note: str = "") -> None:
        self.item = item
        self.old_path = old_path
        self.new_stem = new_stem
        self.new_name = f"{new_stem}{old_path.suffix}"
        self.unit = unit
        self.is_primary = is_primary
        self.changed = old_path.name != self.new_name
        self.note = note

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
        return (m.group("item"), m.group("unit"), 0, "plain")
    m = _RE_BARE.match(s)
    if m:
        return (m.group("item"), "", 0, "bare")
    return None


def scan_legacy_folder(folder: str | Path,
                       suffixes: tuple[str, ...] = IMAGE_SUFFIXES
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
        stem = path.stem
        if stem in seen_stems:
            continue
        parsed = parse_legacy_stem(stem)
        if parsed is None:
            unparsed.append(path)
            continue
        seen_stems.add(stem)
        item, unit, seq, pattern = parsed
        grp = groups.get(item)
        if grp is None:
            grp = groups[item] = LegacyGroup(item)
        grp.images.append(LegacyImage(path, item, unit, seq, pattern))

    for grp in groups.values():
        grp.sort()
    return groups, unparsed


def _target_stems(item: str, unit: str, count: int) -> list[str]:
    """أسماء المجموعة وفق قاعدة المالك: الواجهة بلا رقم ثم -1، -2…"""
    base = f"{item}_{unit}" if unit else str(item)
    return [base if i == 0 else f"{base}-{i}" for i in range(count)]


def plan_legacy_renames(groups: dict[str, LegacyGroup], index=None,
                        unparsed: list[Path] | None = None) -> LegacyPlan:
    """يبني خطة التصحيح من الإكسل بلا أي كتابة على القرص.

    index: `CatalogIndex` محمّل. إن كان None تُستخدم الوحدة الموجودة
    في اسم الملف (فلا يتعطل العمل بغياب الإكسل).
    """
    plan = LegacyPlan()
    plan.groups = groups
    plan.unparsed = list(unparsed or [])

    for item in sorted(groups):
        grp = groups[item]
        unit_in_name = grp.unit_in_names
        unit = unit_in_name
        note = ""
        if index is not None:
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

        stems = _target_stems(item, unit, grp.count)
        for i, im in enumerate(grp.images):
            plan.rows.append(RenamePlanRow(
                item=item, old_path=im.path, new_stem=stems[i], unit=unit,
                is_primary=(i == 0), note=note if i == 0 else ""))
    return plan


def apply_legacy_plan(plan: LegacyPlan,
                      items: list[str] | None = None) -> dict:
    """ينفّذ الخطة على القرص عبر إعادة تسمية ذرية لكل صنف.

    items: أرقام أصناف محددة، أو None لكل المجلد.
    يعيد {"renames": {...}, "errors": [...], "items_done": n}.
    """
    from .primary_image_v2 import renumber_item_images

    wanted = set(items) if items else None
    renames: dict[str, str] = {}
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
        res = renumber_item_images(out_dir, item, paths, [unit] if unit
                                   else [], settings=None)
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

    return {"renames": renames, "errors": errors, "items_done": done}
