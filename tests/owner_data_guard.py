#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""حرّاس بيانات المالك — يمنع «النجاح الزائف» في الاختبارات الحقيقية.

المشكلة التي يحلّها: الاختبارات التي تعتمد على بيانات المالك الفعلية
(ملف الأصناف + الصور الخام + مجلد منجز) كانت — عند غياب تلك البيانات —
تمرّ بلا أي فحص حقيقي وتُعلن نجاحًا في ثانيتين. فتُقفل نقاط في السجل
وهي لم تُفحص إطلاقًا. وهذا أخطر من الفشل الصريح، لأنه يُخفي نفسه.

القاعدة هنا: غياب المدخلات ⇒ خروج بالرمز 77 (SKIP) مع سبب مطبوع.
و`tests/run_all.py` يعرضه في خانة «متخطّى» المنفصلة عن «نجح»، فلا
يُحسب أبدًا ضمن الناجح.

الاستعمال في أعلى أي اختبار يحتاج بيانات المالك:

    from owner_data_guard import require_owner_data
    CATALOG, RAW = require_owner_data(need_catalog=True, need_raw=True)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

SKIP_RC = 77

# جذر بيانات المالك — قابل للتغيير بمتغير بيئة عند نقل الصندوق.
OWNER = Path(os.environ.get("MIS_OWNER_DATA", "/home/ubuntu/owner_data"))

# أسماء محتملة لملف الأصناف: نبحث بالنمط لا بالاسم الحرفي، لأن اسم
# ملف المالك عربي وقد يُعاد تسميته أو تنتقل مسافاته عند النقل.
CATALOG_GLOBS = ("*.xlsx", "*.xls")

# مجلدات محتملة للصور الخام (المالك يضعها متداخلة أحيانًا: زيت/زيت).
RAW_CANDIDATES = ("زيت/زيت", "زيت", "raw", "صور", ".")

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff")


def skip(reason: str) -> "None":
    """يُنهي الاختبار كمتخطّى — لا ناجحًا ولا فاشلًا."""
    print(f"SKIP: {reason}", flush=True)
    print("  (هذا ليس نجاحًا: النقطة لم تُفحص لغياب مدخلاتها.)", flush=True)
    sys.stdout.flush()
    raise SystemExit(SKIP_RC)


def find_catalog() -> Path | None:
    """يعيد أول ملف أصناف صالح داخل بيانات المالك، أو None."""
    if not OWNER.is_dir():
        return None
    for pattern in CATALOG_GLOBS:
        for candidate in sorted(OWNER.rglob(pattern)):
            name = candidate.name
            # تجاهل ملفات إكسل المؤقتة ومخرجات التطبيق نفسها
            if name.startswith("~$") or name.startswith("."):
                continue
            if "مخرجات" in str(candidate) or "output" in str(candidate).lower():
                continue
            if candidate.is_file() and candidate.stat().st_size > 1024:
                return candidate
    return None


def find_raw_dir(minimum: int = 1) -> Path | None:
    """يعيد أول مجلد يحوي عدد صور كافيًا للفحص، أو None."""
    if not OWNER.is_dir():
        return None
    for rel in RAW_CANDIDATES:
        candidate = OWNER / rel if rel != "." else OWNER
        if not candidate.is_dir():
            continue
        images = [p for p in candidate.iterdir()
                  if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
        if len(images) >= minimum:
            return candidate
    # بحث عميق كخيار أخير: أكثر مجلد يحوي صورًا
    best: tuple[int, Path] | None = None
    for directory in OWNER.rglob("*"):
        if not directory.is_dir():
            continue
        count = sum(1 for p in directory.iterdir()
                    if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
        if count >= minimum and (best is None or count > best[0]):
            best = (count, directory)
    return best[1] if best else None


def list_images(directory: Path) -> list[Path]:
    """صور المجلد مرتّبة — بكل الامتدادات المدعومة لا jpg وحده."""
    return sorted(p for p in directory.iterdir()
                  if p.is_file() and p.suffix.lower() in IMAGE_EXTS)


# علامات مجلد العمل المنجز. مخرجات التطبيق الحقيقية تأتي ببنية
# SmartCatalogVision-Results-*/{processed,reports}، وقد تأتي أيضًا بمجلد
# «منجز» أو مع job_state.json. نقبل كل هذه الأشكال.
LEGACY_MARKERS = ("job_state.json", "processed", "reports",
                  "مخرجات", "المخرجات", "منجز", "final")


def find_legacy_dir() -> Path | None:
    """مجلد منجز سابقًا: يُعرَف بمخرجاته أو بحالة عمله.

    نختار أغنى مرشّح بالصور المنجزة لا أول مرشّح، لأن أول مرشّح
    قد يكون مجلدًا حاويًا فارغًا فيُقرأ خطأً أنّ الفحص جرى ولم يجرٍ.
    """
    if not OWNER.is_dir():
        return None
    best: tuple[int, Path] | None = None
    for directory in [OWNER, *[d for d in OWNER.rglob("*") if d.is_dir()]]:
        try:
            names = {p.name for p in directory.iterdir()}
        except OSError:
            continue
        if not any(marker in names for marker in LEGACY_MARKERS):
            continue
        # وزن المرشّح = عدد المخرجات فيه أو داخل processed
        weight = 0
        for probe in (directory, directory / "processed",
                      directory / "مخرجات"):
            if probe.is_dir():
                try:
                    weight += sum(
                        1 for p in probe.iterdir()
                        if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
                except OSError:
                    pass
        if best is None or weight > best[0]:
            best = (weight, directory)
    return best[1] if best else None


def legacy_outputs(legacy: Path) -> list[Path]:
    """صور مجلد منجز — من جذره أو من processed/مخرجات."""
    for probe in (legacy / "processed", legacy / "مخرجات", legacy):
        if probe.is_dir():
            found = list_images(probe)
            if found:
                return found
    return []


def require_owner_data(need_catalog: bool = True,
                       need_raw: bool = True,
                       minimum_images: int = 1,
                       need_legacy: bool = False):
    """يتحقق من توفّر بيانات المالك أو يتخطّى الاختبار بسبب واضح.

    يعيد الموجودات فقط بالترتيب المطلوب (catalog, raw, legacy).
    """
    missing: list[str] = []
    catalog = find_catalog() if need_catalog else None
    raw = find_raw_dir(minimum_images) if need_raw else None
    legacy = find_legacy_dir() if need_legacy else None

    if not OWNER.is_dir():
        skip(f"مجلد بيانات المالك غير موجود: {OWNER}")
    if need_catalog and catalog is None:
        missing.append("ملف أصناف (xlsx)")
    if need_raw and raw is None:
        missing.append(f"مجلد صور خام (≥{minimum_images} صورة)")
    if need_legacy and legacy is None:
        missing.append("مجلد عمل منجز سابقًا")
    if missing:
        skip("بيانات المالك ناقصة — " + " ، ".join(missing)
             + f" (الجذر: {OWNER})")

    out: list[Path] = []
    if need_catalog:
        out.append(catalog)  # type: ignore[arg-type]
    if need_raw:
        out.append(raw)      # type: ignore[arg-type]
    if need_legacy:
        out.append(legacy)   # type: ignore[arg-type]
    return out[0] if len(out) == 1 else tuple(out)


def describe() -> str:
    """وصف موجز لما هو متوفر — للطباعة في رأس الاختبار."""
    catalog = find_catalog()
    raw = find_raw_dir()
    count = len(list_images(raw)) if raw else 0
    return (f"بيانات المالك: أصناف={'✓' if catalog else '✗'} "
            f"صور={count} مجلد={OWNER}")


if __name__ == "__main__":
    print(describe())
    print("catalog:", find_catalog())
    print("raw:", find_raw_dir())
    print("legacy:", find_legacy_dir())
