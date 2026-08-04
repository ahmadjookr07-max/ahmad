# -*- coding: utf-8 -*-
"""تعيين الصورة الرئيسية للصنف وإعادة ترقيم بقية صوره (2.3).

السياسة المتفق عليها مع المالك (أمره النهائي):
- الصورة الرئيسية = **التي يعيّنها المالك بزر النجمة ★**
  (واجهة الصنف في المتجر): {item}_{unit} أو
  {item}_حبه_شدة_كرتون (join_all) — **بلا رقم**.
- بقية الصور: نفس الاسم + ‎-1، ‎-2، ‎-3 حسب ترتيبها.

الربط بالنجمة: `ordered_paths[0]` هي الصورة المعيّنة بـ★،
وهي وحدها التي تأخذ الاسم الأساسي بلا رقم؛ فالواجهة خيار
المالك لا ترتيب المعالجة.

تاريخ الترقيم (لمن يعدّل لاحقًا فلا يعكسه مرة أخرى):
المالك أمر نصًا بـ: الرئيسية بلا رقم، والثانية ‎-1، والثالثة ‎-2.
وفي 2.9.9 غُيّر إلى البدء من ‎-2 بحجة التداخل مع الرئيسية، وهي
حجة باطلة لأن الرئيسية بلا رقم أصلًا فلا يتصادم `base` مع `base-1`.
أُعيد إلى أمر المالك، ويحرسه `test_primary_image_v2`.

الوحدة تعمل على ملفات مجلد الإخراج مباشرة (rename ذري عبر مرحلة مؤقتة
لتجنب تصادم الأسماء)، وتعيد خريطة {المسار القديم: المسار الجديد}
لتحدّث بها الواجهة نتائجها.
"""
from __future__ import annotations

import os
from pathlib import Path

__all__ = ["renumber_item_images", "PrimaryRenameResult"]


class PrimaryRenameResult:
    def __init__(self) -> None:
        self.renames: dict[str, str] = {}
        self.primary_path: str = ""
        self.error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def _stem_names(item: str, units: list[str], count: int,
                settings) -> list[str]:
    """أسماء الصور المطلوبة بالترتيب: [الرئيسية، -1، -2…] وفق السياسة."""
    from engine_v2 import naming_v2 as nv

    units = [u for u in units if u] or [getattr(settings, "default_unit", "حبه")]
    if settings is not None and getattr(settings, "enabled", False) and \
            getattr(settings, "unit_policy", "") == nv.UNIT_POLICY_JOIN_ALL:
        return [
            nv.build_name_join_all(item, units, i + 1, total=count,
                                   default_unit=settings.default_unit)
            for i in range(count)
        ]
    # النمط dash الافتراضي: الرئيسية بلا رقم ثم -1/-2… (أمر المالك)
    unit = units[0]
    base = f"{item}_{unit}"
    return [base if i == 0 else f"{base}-{i}" for i in range(count)]


def renumber_item_images(
    out_dir: str | Path,
    item: str,
    ordered_paths: list[str | Path],
    units: list[str],
    settings=None,
    target_stems: list[str] | None = None,
) -> PrimaryRenameResult:
    """يعيد تسمية صور الصنف بحيث تكون ordered_paths[0] هي الرئيسية.

    ordered_paths: مسارات ملفات الإخراج الحالية لصور الصنف بالترتيب
    المطلوب (الرئيسية أولًا). تُعاد التسمية مع الحفاظ على الامتدادات،
    ويشمل ذلك الملفات الشقيقة بنفس الجذع (png/jpg بجانب webp إن وجدت).

    target_stems (2.9.6): جذوع جاهزة تُستخدم كما هي بدل إعادة بناء
    الاسم من `units`. لازمة لمسار المجلد المنجز حتى يطابق المنفّذ
    خطة المعاينة تمامًا ولا تُكرّر الوحدات المجموعة.
    """
    result = PrimaryRenameResult()
    out_dir = Path(out_dir)
    paths = [Path(p) for p in ordered_paths if str(p)]
    paths = [p for p in paths if p.is_file()]
    if not paths:
        result.error = "لا توجد ملفات صالحة لإعادة الترقيم"
        return result

    if settings is None:
        try:
            from engine_v2 import integration_v2 as iv
            settings = iv._current_naming_settings()
        except Exception:
            settings = None

    if target_stems:
        targets = [str(s) for s in target_stems if str(s or "").strip()]
        targets = targets[:len(paths)]
        if len(targets) < len(paths):
            fallback = _stem_names(item, units, len(paths), settings)
            targets += fallback[len(targets):]
    else:
        targets = _stem_names(item, units, len(paths), settings)

    # اجمع كل الملفات الفعلية المطلوب نقلها: لكل مسار، كل الأشقاء بنفس الجذع.
    moves: list[tuple[Path, str]] = []  # (ملف حالي، جذع جديد)
    for src, new_stem in zip(paths, targets):
        stem = src.stem
        siblings = [p for p in src.parent.glob(f"{stem}.*") if p.is_file()]
        if not siblings:
            siblings = [src]
        for sib in siblings:
            moves.append((sib, new_stem))

    # مرحلة مؤقتة لتجنب التصادم (قد يكون الاسم الجديد لملف هو القديم لآخر).
    staged: list[tuple[Path, Path, str]] = []
    try:
        for i, (src, new_stem) in enumerate(moves):
            tmp = src.with_name(f"__primary_tmp_{i}__{src.name}")
            os.replace(src, tmp)
            staged.append((tmp, src, new_stem))
        for tmp, src, new_stem in staged:
            final = src.with_name(f"{new_stem}{src.suffix}")
            os.replace(tmp, final)
            result.renames[str(src)] = str(final)
    except Exception as exc:  # استرجاع ما أمكن
        for tmp, src, _ in staged:
            try:
                if tmp.exists():
                    os.replace(tmp, src)
            except Exception:
                pass
        result.error = f"فشل إعادة التسمية: {exc}"
        result.renames.clear()
        return result

    first = paths[0]
    result.primary_path = result.renames.get(
        str(first), str(first.with_name(f"{targets[0]}{first.suffix}")))
    return result
