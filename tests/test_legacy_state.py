# -*- coding: utf-8 -*-
"""حاجز انحدار: حالة المهمة للمجلد المنجز (يغلق A1 + A4).

المشكلتان كما أبلغ عنهما المالك:
  A1 «التطبيق يقول إنه يفقد وهو لم يفقد شيء»
  A4 «لا أستطيع تعديل الباركود أثناء العمل على الملفات السابقة»

القياس قبل الإصلاح على 12 صورة من مخرجات المالك الحقيقية:
  job_state.json          : غير موجود ✗
  خزانة المصادر           : غير موجودة ✗
  pipeline._load_state    : FileNotFoundError ✗

بعد الإصلاح كل هذه تنجح، وهذا الملف يمنع رجوعها.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT / "src", ROOT / "windows_app"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

FAILURES: list[str] = []
CHECKS = 0


def check(label: str, condition: bool, detail: str = "") -> bool:
    global CHECKS
    CHECKS += 1
    if condition:
        print(f"  ✓ {label}")
        return True
    FAILURES.append(f"{label}{(' — ' + detail) if detail else ''}")
    print(f"  ✗ {label}" + (f" — {detail}" if detail else ""))
    return False


# ── بناء مجلد منجز اصطناعي بأسماء المالك الحقيقية ──────────────────
def make_legacy_folder(dest: Path, groups: int = 5) -> list[Path]:
    """ينشئ مجلدًا منجزًا بنمط تسمية المالك: رقم_وحدة و رقم_وحدة-N."""
    from PIL import Image

    dest.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    for g in range(groups):
        code = str(10000001 + g)
        names = [f"{code}_حبه.webp", f"{code}_حبه-1.webp"]
        if g % 2 == 0:
            names.append(f"{code}_حبه-2.webp")
        for nm in names:
            p = dest / nm
            Image.new("RGB", (800, 700), (250, 250, 250)).save(p, "WEBP")
            made.append(p)
    return made


def test_state_written() -> None:
    """الاختبار المركزي: الفتح ينتج حالة مهمة قابلة للقراءة."""
    print("\n[1] فتح مجلد منجز ينتج حالة مهمة صالحة")
    from engine_v2.legacy_folder_v2 import (ensure_legacy_job_state,
                                            plan_legacy_renames,
                                            scan_legacy_folder)

    work = Path(tempfile.mkdtemp(prefix="legacy_state_"))
    try:
        made = make_legacy_folder(work / "منجز")
        folder = work / "منجز"
        check("بُنيت صور الاختبار", len(made) >= 12, f"{len(made)} صورة")

        groups, unparsed = scan_legacy_folder(folder)
        check("مُسحت المجموعات", len(groups) == 5, f"{len(groups)}")
        plan = plan_legacy_renames(groups, None, unparsed)

        # نبني نتيجة مكافئة لما تبنيه الواجهة
        from smart_catalog_vision.pipeline import (BatchItemResult,
                                                   BatchRunResult)
        items = []
        for row in plan.rows:
            p = row.old_path
            items.append(BatchItemResult(
                source_path=str(p), source_name=p.name, status="manual",
                item_code=row.item, product_name=f"الصنف {row.item}",
                barcode="", confidence=1.0, explanation="مجلد منجز",
                output_path=p.name, match_source="legacy_folder"))
        result = BatchRunResult(
            workspace=str(folder), database_path="",
            catalog_summary={"source": "legacy_folder"}, items=items,
            elapsed_ms=0.0, delivery_zip="", report_json="", report_csv="")

        t0 = time.perf_counter()
        report = ensure_legacy_job_state(folder, result)
        ms = (time.perf_counter() - t0) * 1000.0

        check("كُتبت حالة المهمة", bool(report["state_written"]),
              report.get("error", ""))
        check("job_state.json موجود على القرص",
              (folder / "job_state.json").is_file())
        check("أُودعت المصادر في الخزانة", bool(report["vault_deposited"]),
              report.get("error", ""))
        check("زمن التثبيت مقبول (<3000 مث)", ms < 3000.0, f"{ms:.1f} مث")
        print(f"    زمن تثبيت الحالة: {ms:.1f} مث لـ{len(items)} صورة")

        # ── الاختبار الحاسم لـA4: هل يُقرأ الآن؟ ────────────────────
        print("\n[2] تعديل الباركود صار ممكنًا (_load_state تنجح)")
        import smart_catalog_vision.pipeline as p
        try:
            loaded = p._load_state(folder)
            check("pipeline._load_state نجحت", loaded is not None)
            ws, raw, cat, res, opts, prof = loaded
            check("النتيجة المُحمّلة تحمل نفس عدد الصور",
                  len(res.items) == len(items),
                  f"{len(res.items)} مقابل {len(items)}")
            check("مساحة العمل صحيحة", Path(ws) == folder, str(ws))
        except Exception as exc:
            check("pipeline._load_state نجحت", False,
                  f"{type(exc).__name__}: {exc}")

        # ── الاختبار الحاسم لـA1: لا فقدان زائف ────────────────────
        print("\n[3] لا إعلان فقدان زائف (الملفات موجودة)")
        from engine_v2.source_vault_v2 import repair_job_state
        rep = repair_job_state(folder)
        missing = list(getattr(rep, "missing", []) or [])
        check("لا ملفات مُعلنة مفقودة", not missing,
              f"{len(missing)} ملف: {missing[:2]}")
        for pth in made[:5]:
            check(f"الملف موجود فعلًا: {pth.name}", pth.is_file())

        # ── سلامة محتوى الحالة ─────────────────────────────────────
        print("\n[4] بنية ملف الحالة مطابقة لما ينتجه المسار الطبيعي")
        raw_state = json.loads(
            (folder / "job_state.json").read_text("utf-8"))
        for key in ("schema_version", "catalog_path", "profile_name",
                    "final_image_options", "result"):
            check(f"المفتاح موجود: {key}", key in raw_state)
        check("إصدار المخطط = 2", raw_state.get("schema_version") == 2,
              str(raw_state.get("schema_version")))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_no_crash_readonly() -> None:
    """الفتح ينجح ولا ينهار حتى إن تعذّرت الكتابة."""
    print("\n[5] لا انهيار إن تعذّرت الكتابة (قرص للقراءة فقط)")
    from engine_v2.legacy_folder_v2 import ensure_legacy_job_state

    work = Path(tempfile.mkdtemp(prefix="legacy_ro_"))
    folder = work / "ro"
    try:
        make_legacy_folder(folder, groups=1)
        from smart_catalog_vision.pipeline import BatchRunResult
        result = BatchRunResult(
            workspace=str(folder), database_path="", catalog_summary={},
            items=[], elapsed_ms=0.0, delivery_zip="", report_json="",
            report_csv="")
        os.chmod(folder, 0o500)          # قراءة وتنفيذ بلا كتابة
        rep = ensure_legacy_job_state(folder, result)
        check("أُعيد تقرير بلا استثناء", isinstance(rep, dict))
        check("التقرير يوضّح تعذّر الكتابة",
              not rep["state_written"] and bool(rep["error"]),
              str(rep))
    except Exception as exc:
        check("أُعيد تقرير بلا استثناء", False,
              f"{type(exc).__name__}: {exc}")
    finally:
        try:
            os.chmod(folder, 0o700)
        except Exception:
            pass
        shutil.rmtree(work, ignore_errors=True)


def test_none_result() -> None:
    """حراسة المدخلات: نتيجة None لا تُسقط التطبيق."""
    print("\n[6] حراسة المدخلات")
    from engine_v2.legacy_folder_v2 import ensure_legacy_job_state
    rep = ensure_legacy_job_state("/tmp", None)
    check("نتيجة None تُعاد بتقرير لا استثناء",
          isinstance(rep, dict) and not rep["state_written"])


def main() -> int:
    os.environ.setdefault("MIS_HEADLESS", "1")
    os.environ.setdefault("MIS_LICENSE_BYPASS", "1")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    print("═" * 62)
    print("حاجز انحدار: حالة المهمة للمجلد المنجز (A1 + A4)")
    print("═" * 62)
    test_state_written()
    test_no_crash_readonly()
    test_none_result()
    print("\n" + "═" * 62)
    passed = CHECKS - len(FAILURES)
    print(f"النتيجة: {passed}/{CHECKS}")
    if FAILURES:
        print("\nفشل:")
        for f in FAILURES:
            print(f"  ✗ {f}")
        return 1
    print("كل الفحوص نجحت ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
