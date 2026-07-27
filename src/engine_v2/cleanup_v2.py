# -*- coding: utf-8 -*-
"""cleanup_v2 — أداة تنظيف وتصفية الصور حسب رقم اللقطة والوحدة.

تعمل على مجلد كامل (وكل الأصناف) دفعة واحدة:
- فلترة مزدوجة: رقم اللقطة (الكل/1/2/3...) × الوحدة (الكل/حبه/شده/كرتون/باكت...).
- إجراء: احتفاظ فقط (حذف بقية صور كل صنف) أو حذف فقط (إبقاء الباقي).
- إعادة تسمية تلقائية للصور المتبقية لتكون غلافًا صحيحًا (رقم_الصنف_حبه).
- تعديل الوحدة أثناء العملية اختياريًا.
- كشف وإصلاح التكرارات الفاسدة (`_2__حبه`) ودمجها مع الأصلية بالمحتوى.
- معاينة كاملة قبل التنفيذ (خطة بدون أي حذف فعلي حتى التأكيد).
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from .naming_v2 import (IMAGE_EXTS, build_name, clean_unit, normalize_stem,
                        parse_name, unmojibake)


@dataclass
class CleanupEntry:
    """عنصر واحد في خطة التنظيف."""
    source: str                 # اسم الملف الحالي
    action: str                 # keep | delete | rename | merge_duplicate
    target: str = ""            # الاسم الجديد عند rename
    item: str = ""
    seq: int = 1
    unit: str = ""
    note: str = ""


@dataclass
class CleanupPlan:
    folder: str = ""
    entries: list = field(default_factory=list)   # list[CleanupEntry]

    @property
    def n_delete(self) -> int:
        return sum(1 for e in self.entries
                   if e.action in ("delete", "merge_duplicate"))

    @property
    def n_rename(self) -> int:
        return sum(1 for e in self.entries if e.action == "rename")

    @property
    def n_keep(self) -> int:
        return sum(1 for e in self.entries if e.action == "keep")


def _file_digest(p: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha1()
    with open(p, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def scan_folder(folder: str | Path, recursive: bool = False) -> list[Path]:
    """كل الصور في المجلد (مرتبة)، مع تجاهل الملفات المخفية."""
    folder = Path(folder)
    it = folder.rglob("*") if recursive else folder.iterdir()
    return [p for p in sorted(it)
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS
            and not p.name.startswith(".")]


def available_units(folder: str | Path, recursive: bool = False) -> list[str]:
    """الوحدات الموجودة فعليًا في أسماء ملفات المجلد (للفلاتر)."""
    units: list[str] = []
    for p in scan_folder(folder, recursive):
        parsed = parse_name(unmojibake(p.stem))
        if parsed:
            u = clean_unit(parsed.unit)
            if u and u not in units:
                units.append(u)
    return units


def available_seqs(folder: str | Path, recursive: bool = False) -> list[int]:
    """أرقام اللقطات الموجودة فعليًا (1 = الغلاف بدون رقم)."""
    seqs: set[int] = set()
    for p in scan_folder(folder, recursive):
        parsed = parse_name(unmojibake(p.stem))
        if parsed:
            seqs.add(parsed.seq)
    return sorted(seqs)


def plan_fix_duplicates(folder: str | Path,
                        recursive: bool = False) -> CleanupPlan:
    """خطة إصلاح التكرارات الفاسدة: أسماء بشرطات مزدوجة `_2__حبه`
    المتطابقة محتوًى مع الأصلية تُحذف، والمختلفة تُعاد تسميتها قانونيًا."""
    folder = Path(folder)
    plan = CleanupPlan(folder=str(folder))
    files = scan_folder(folder, recursive)
    canonical: dict[str, Path] = {}
    mangled: list[Path] = []
    for p in files:
        stem = unmojibake(p.stem)
        norm = normalize_stem(stem)
        if norm != stem or "__" in p.stem:
            mangled.append(p)
        else:
            canonical.setdefault(norm.lower(), p)
    taken = {p.stem.lower() for p in files} - {m.stem.lower() for m in mangled}
    for p in mangled:
        norm = normalize_stem(unmojibake(p.stem))
        orig = canonical.get(norm.lower())
        parsed = parse_name(norm)
        item = parsed.item if parsed else ""
        seq = parsed.seq if parsed else 1
        unit = clean_unit(parsed.unit) if parsed else ""
        if orig is not None and orig.exists():
            try:
                same = (orig.stat().st_size == p.stat().st_size
                        and _file_digest(orig) == _file_digest(p))
            except OSError:
                same = False
            if same:
                plan.entries.append(CleanupEntry(
                    source=p.name, action="merge_duplicate", item=item,
                    seq=seq, unit=unit,
                    note=f"نسخة مكررة بالمحتوى من {orig.name} — تُحذف"))
                continue
            # نفس الاسم القانوني لكن محتوى مختلف: لقطة إضافية بتسلسل تالٍ
            if parsed:
                nseq = seq + 1
                cand = build_name(item, nseq, unit or "حبه")
                while cand.lower() in taken:
                    nseq += 1
                    cand = build_name(item, nseq, unit or "حبه")
                taken.add(cand.lower())
                plan.entries.append(CleanupEntry(
                    source=p.name, action="rename",
                    target=cand + p.suffix.lower(), item=item, seq=nseq,
                    unit=unit, note="اسم فاسد بمحتوى مختلف — لقطة إضافية"))
                continue
        target = norm + p.suffix.lower()
        if norm.lower() in taken:
            plan.entries.append(CleanupEntry(
                source=p.name, action="delete", item=item, seq=seq,
                unit=unit, note="اسم فاسد يصطدم باسم قائم"))
        else:
            taken.add(norm.lower())
            plan.entries.append(CleanupEntry(
                source=p.name, action="rename", target=target, item=item,
                seq=seq, unit=unit, note="تصحيح الاسم الفاسد"))
    return plan


def plan_cleanup(folder: str | Path, *,
                 seq_filter: int | None = None,
                 unit_filter: str = "",
                 mode: str = "keep_only",
                 rename_survivors: bool = True,
                 new_unit: str = "",
                 recursive: bool = False) -> CleanupPlan:
    """خطة التنظيف الرئيسية.

    seq_filter: رقم اللقطة المستهدف (None = الكل، 1 = الغلاف بدون رقم).
    unit_filter: الوحدة المستهدفة ("" = كل الوحدات).
    mode: keep_only (الاحتفاظ بالمطابق وحذف بقية صور كل صنف)
          أو delete_only (حذف المطابق فقط والإبقاء على الباقي).
    rename_survivors: إعادة تسمية المتبقي ليكون غلافًا/تسلسلًا صحيحًا.
    new_unit: تغيير وحدة المتبقي أثناء العملية (اختياري).
    """
    folder = Path(folder)
    plan = CleanupPlan(folder=str(folder))
    files = scan_folder(folder, recursive)
    unit_filter = clean_unit(unit_filter)
    new_unit = clean_unit(new_unit)

    groups: dict[str, list[tuple[Path, int, str]]] = {}
    for p in files:
        parsed = parse_name(unmojibake(p.stem))
        if not parsed:
            plan.entries.append(CleanupEntry(
                source=p.name, action="keep",
                note="اسم غير قياسي — لا يُمس"))
            continue
        u = clean_unit(parsed.unit)
        groups.setdefault(parsed.item, []).append((p, parsed.seq, u))

    def matches(seq: int, unit: str) -> bool:
        if seq_filter is not None and seq != seq_filter:
            return False
        if unit_filter and unit != unit_filter:
            return False
        return True

    for item, members in groups.items():
        members.sort(key=lambda t: t[1])
        hit = [(p, s, u) for (p, s, u) in members if matches(s, u)]
        if mode == "keep_only":
            if not hit:
                # لا مطابق في هذا الصنف — لا نحذف شيئًا احترازيًا
                for p, s, u in members:
                    plan.entries.append(CleanupEntry(
                        source=p.name, action="keep", item=item, seq=s,
                        unit=u, note="لا توجد لقطة مطابقة للفلتر — أُبقي"))
                continue
            survivors = hit
            victims = [(p, s, u) for (p, s, u) in members
                       if (p, s, u) not in hit]
        else:  # delete_only
            survivors = [(p, s, u) for (p, s, u) in members
                         if (p, s, u) not in hit]
            victims = hit
        for p, s, u in victims:
            plan.entries.append(CleanupEntry(
                source=p.name, action="delete", item=item, seq=s, unit=u,
                note="حذف حسب الفلتر"))
        # إعادة ترقيم المتبقي: الأول غلاف بلا رقم ثم 2، 3...
        taken: set[str] = set()
        for i, (p, s, u) in enumerate(sorted(survivors, key=lambda t: t[1])):
            unit_out = new_unit or u or "حبه"
            if rename_survivors:
                cand = build_name(item, i + 1, unit_out)
                while cand.lower() in taken:
                    i += 1
                    cand = build_name(item, i + 1, unit_out)
                taken.add(cand.lower())
                target = cand + p.suffix.lower()
                if target == p.name:
                    plan.entries.append(CleanupEntry(
                        source=p.name, action="keep", item=item, seq=i + 1,
                        unit=unit_out))
                else:
                    plan.entries.append(CleanupEntry(
                        source=p.name, action="rename", target=target,
                        item=item, seq=i + 1, unit=unit_out,
                        note="إعادة ترتيب التسلسل بعد التنظيف"))
            else:
                plan.entries.append(CleanupEntry(
                    source=p.name, action="keep", item=item, seq=s, unit=u))
    return plan


def apply_plan(plan: CleanupPlan,
               to_trash: bool = True) -> tuple[int, int, list[str]]:
    """تنفيذ الخطة. يعيد (عدد المحذوف، عدد المعاد تسميته، الأخطاء).

    to_trash: نقل المحذوفات إلى مجلد فرعي `_المحذوفات` بدل الحذف النهائي
    (أمان — يمكن للمستخدم إفراغه لاحقًا).
    """
    folder = Path(plan.folder)
    errors: list[str] = []
    deleted = renamed = 0
    trash = folder / "_المحذوفات"
    # مرحلة 1: الحذف/النقل
    for e in plan.entries:
        if e.action not in ("delete", "merge_duplicate"):
            continue
        src = folder / e.source
        try:
            if to_trash:
                trash.mkdir(exist_ok=True)
                dst = trash / e.source
                n = 2
                while dst.exists():
                    dst = trash / f"{Path(e.source).stem}_{n}{Path(e.source).suffix}"
                    n += 1
                src.rename(dst)
            else:
                src.unlink()
            deleted += 1
        except OSError as exc:
            errors.append(f"{e.source}: {exc}")
    # مرحلة 2: إعادة التسمية على مرحلتين لتفادي الاصطدام
    todo = [e for e in plan.entries if e.action == "rename" and e.target]
    temps: list[tuple[Path, Path]] = []
    for e in todo:
        src = folder / e.source
        tmp = folder / (e.target + ".tmp_cl")
        try:
            src.rename(tmp)
            temps.append((tmp, folder / e.target))
        except OSError as exc:
            errors.append(f"{e.source}: {exc}")
    for tmp, final in temps:
        try:
            if final.exists():
                tmp.rename(folder / ("conflict_" + final.name))
                errors.append(f"تعارض اسم: {final.name}")
                continue
            tmp.rename(final)
            renamed += 1
        except OSError as exc:
            errors.append(f"{tmp.name}: {exc}")
    return deleted, renamed, errors
