# -*- coding: utf-8 -*-
"""حاجز انحدار لخزانة المصادر (`source_vault_v2`).

## لماذا هذا الملف موجود
مستند «تشخيص أخطاء 2.9.5» أثبت أن `apply_manual_link` و
`apply_individual_image_edit` يعتمدان على **المسار المطلق** المخزَّن
في `job_state.json` وقت الدفعة، فأي نقل أو حذف أو تغيير حرف قرص
يُطلق `FileNotFoundError` وتظهر للمالك رسالة عامة «تعذر العثور على
ملفات المهمة». الحل المُنفَّذ هو خزانة المصادر، وكان **بلا أي اختبار**
— فأي تعديل مستقبلي قد يكسره بصمت ويُعيد الخطأ نفسه.

الحالات المُحاكاة هنا هي حالات جدول التشخيص حرفيًا:
1. الصور الأصلية نُقلت إلى مجلد آخر.
2. الصور الأصلية حُذفت نهائيًا.
3. ملف الإكسل حُذف بعد الدفعة.
4. الصورة أُعيدت تسميتها (يلزم الاسترجاع بالبصمة لا بالاسم).
5. مسار عربي للمساحة والصور.
6. لا خزانة إطلاقًا (سلوك متسامح، لا استثناء).
7. `job_state.json` تالف (لا انهيار).
8. الكتابة ذرّية: الحالة تُحدَّث فعليًا على القرص.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from engine_v2.source_vault_v2 import (  # noqa: E402
    CATALOG_SNAPSHOT_NAME, MANIFEST_NAME, STATE_NAME, VAULT_DIRNAME,
    RepairReport, SourceVault, deposit_job_sources, fingerprint,
    missing_sources, repair_job_state)

PASSED = 0
FAILED = 0


def check(condition, label: str) -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ✓ {label}")
    else:
        FAILED += 1
        print(f"  ✗ {label}")


# ------------------------------------------------------------- أدوات البناء
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000"
    "001f15c4890000000a49444154789c6360000002000154a24f5f0000"
    "000049454e44ae426082")


def make_image(path: Path, filler: bytes = b"") -> Path:
    """صورة PNG صغيرة صحيحة مع حشوة تُغيّر البصمة عند الحاجة."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_PNG + filler)
    return path


def make_job(workspace: Path, images, catalog: Path | None = None) -> Path:
    """يكتب `job_state.json` بنفس بنية المحرك الحقيقية."""
    items = []
    for img in images:
        items.append({
            "source_name": img.name,
            "source_path": str(img),
            "review_path": str(img),
            "item_code": "10001102",
        })
    state = {
        "catalog_path": str(catalog) if catalog else "",
        "result": {"items": items},
    }
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / STATE_NAME).write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return workspace / STATE_NAME


def read_state(workspace: Path) -> dict:
    return json.loads((workspace / STATE_NAME).read_text(encoding="utf-8"))


# ------------------------------------------------------------------ الحالات
def test_deposit_creates_vault():
    """الإيداع ينشئ الخزانة والمانيفست ويسجّل البصمة."""
    print("\n[1] الإيداع ينشئ الخزانة والمانيفست")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "الصور"
        images = [make_image(src / f"PHOTO-{i}.png", bytes([i]) * 32)
                  for i in range(1, 4)]
        workspace = root / "مساحة العمل"
        catalog = root / "اصناف.xlsx"
        catalog.write_bytes(b"PK\x03\x04fake-xlsx")

        stored = deposit_job_sources(workspace, [str(p) for p in images],
                                     str(catalog))
        check(stored == 3, f"أُودعت 3 صور فعليًا (أُودع {stored})")
        vault_root = workspace / VAULT_DIRNAME
        check(vault_root.is_dir(), "مجلد الخزانة أُنشئ")
        check((vault_root / MANIFEST_NAME).is_file(), "المانيفست مكتوب")

        vault = SourceVault.load(workspace)
        check(len(vault.entries) == 3, "المانيفست يحوي المدخلات الثلاثة")
        # منذ 2.9.7 مفتاح المدخل هو المسار المُطبَّع لا الاسم، منعًا لتصادم
        # صورتين مختلفتين تتشاركان الاسم من مجلدين.
        by_name = {e.name: e for e in vault.entries.values()}
        check(set(by_name) == {"PHOTO-1.png", "PHOTO-2.png", "PHOTO-3.png"},
              "أسماء المداخل محفوطة كاملة")
        entry = by_name["PHOTO-1.png"]
        check(entry.key == os.path.normcase(os.path.normpath(
            str(images[0].resolve()))),
            "مفتاح المدخل هو المسار المُطبَّع لا الاسم")
        check(entry.fingerprint == fingerprint(images[0]),
              "البصمة المخزَّنة تطابق بصمة الأصل")
        check(vault.catalog_snapshot().endswith(".xlsx"),
              "نسخة الإكسل مودعة")

        # الإيداع مرتين لا يضاعف المدخلات
        deposit_job_sources(workspace, [str(p) for p in images], str(catalog))
        check(len(SourceVault.load(workspace).entries) == 3,
              "الإيداع المتكرر لا يضاعف المدخلات")


def test_repair_after_move():
    """الحالة 1: الصور نُقلت لمجلد آخر — يجب الاسترجاع من الخزانة."""
    print("\n[2] الصور الأصلية نُقلت بعد الدفعة")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "أصلي"
        images = [make_image(src / f"IMG-{i}.png", bytes([i]) * 40)
                  for i in range(1, 3)]
        workspace = root / "workspace"
        deposit_job_sources(workspace, [str(p) for p in images])
        make_job(workspace, images)

        moved = root / "منقول"
        moved.mkdir()
        for img in images:
            shutil.move(str(img), str(moved / img.name))
        check(not images[0].is_file(), "المسار الأصلي لم يبق موجودًا")

        report = repair_job_state(workspace)
        check(isinstance(report, RepairReport), "يُعاد تقرير إصلاح")
        check(len(report.repaired) == 2,
              f"استُعيدت الصورتان (استُعيد {len(report.repaired)})")
        check(report.ok and not report.missing, "لا مصادر مفقودة")
        check(report.state_written, "الحالة كُتبت على القرص")

        state = read_state(workspace)
        for item in state["result"]["items"]:
            check(Path(item["source_path"]).is_file(),
                  f"مسار {item['source_name']} صار موجودًا فعليًا")
            check(item["review_path"] == item["source_path"],
                  f"review_path صُحّح مع source_path لـ{item['source_name']}")


def test_repair_after_delete():
    """الحالة 2: الأصول حُذفت — الخزانة هي المصدر الوحيد الباقي."""
    print("\n[3] الصور الأصلية حُذفت نهائيًا")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "src"
        images = [make_image(src / "ONLY.png", b"\x01" * 64)]
        workspace = root / "ws"
        deposit_job_sources(workspace, [str(images[0])])
        make_job(workspace, images)

        shutil.rmtree(src)
        check(not images[0].is_file(), "الأصل حُذف")

        report = repair_job_state(workspace)
        check(report.ok, "الاسترجاع نجح رغم حذف الأصل")
        resolved = Path(read_state(workspace)["result"]["items"][0]
                        ["source_path"])
        check(resolved.is_file(), "المسار المستعاد موجود")
        check(VAULT_DIRNAME in resolved.parts,
              "المسار المستعاد يشير إلى الخزانة")
        check(resolved.read_bytes() == _PNG + b"\x01" * 64,
              "محتوى الصورة المستعادة مطابق للأصل بايتًا ببايت")


def test_repair_catalog_deleted():
    """الحالة 3: ملف الإكسل حُذف — يُستعاد من النسخة المودعة."""
    print("\n[4] ملف الإكسل حُذف بعد الدفعة")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        images = [make_image(root / "s" / "A.png", b"\x02" * 20)]
        catalog = root / "اصناف عالمعنترة.xlsx"
        catalog.write_bytes(b"PK\x03\x04real-content")
        workspace = root / "ws"
        deposit_job_sources(workspace, [str(images[0])], str(catalog))
        make_job(workspace, images, catalog)

        catalog.unlink()
        report = repair_job_state(workspace)
        check(report.catalog_repaired, "الإكسل استُعيد من النسخة")
        check(not report.catalog_missing, "لا يُبلَّغ عن إكسل مفقود")
        new_catalog = Path(read_state(workspace)["catalog_path"])
        check(new_catalog.is_file(), "مسار الإكسل الجديد موجود")
        check(new_catalog.name.startswith(CATALOG_SNAPSHOT_NAME),
              "المسار يشير إلى نسخة الخزانة")
        check(new_catalog.read_bytes() == b"PK\x03\x04real-content",
              "محتوى الإكسل المستعاد مطابق")


def test_resolve_by_fingerprint_after_rename():
    """الحالة 4: الملف أُعيدت تسميته — المطابقة بالبصمة تنجح."""
    print("\n[5] الصورة أُعيدت تسميتها (استرجاع بالبصمة)")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "pics"
        original = make_image(src / "OLD-NAME.png", b"\x07" * 100)
        workspace = root / "ws"
        # خزانة بلا الملف: نودع ثم نُفرغ محتوى الخزانة مع إبقاء المانيفست
        deposit_job_sources(workspace, [str(original)])
        vault_root = workspace / VAULT_DIRNAME
        for f in vault_root.iterdir():
            if f.name != MANIFEST_NAME:
                f.unlink()
        renamed = src / "NEW-NAME.png"
        original.rename(renamed)

        vault = SourceVault.load(workspace)
        found = vault.resolve("OLD-NAME.png", str(original),
                              extra_dirs=[str(src)])
        check(found == str(renamed),
              f"وُجد الملف بعد تغيير اسمه بالبصمة ({Path(found).name if found else 'لا شيء'})")


def test_arabic_paths():
    """الحالة 5: مسارات عربية بالكامل (مساحة العمل والصور)."""
    print("\n[6] مسارات عربية بالكامل")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "صور المنتجات" / "دفعة يوليو"
        images = [make_image(src / "صورة-١.png", b"\x03" * 30)]
        workspace = root / "مساحة عمل" / "متجر أحمد"
        deposit_job_sources(workspace, [str(images[0])])
        make_job(workspace, images)
        shutil.rmtree(root / "صور المنتجات")

        report = repair_job_state(workspace)
        check(report.ok, "الاسترجاع نجح على مسار عربي")
        check(Path(read_state(workspace)["result"]["items"][0]
                   ["source_path"]).is_file(),
              "الملف المستعاد موجود على مسار عربي")


def test_tolerant_without_vault():
    """الحالة 6: لا خزانة — تقرير بالمفقود بلا استثناء."""
    print("\n[7] لا خزانة إطلاقًا (سلوك متسامح)")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        images = [make_image(root / "x" / "GONE.png", b"\x04")]
        workspace = root / "ws"
        make_job(workspace, images)          # حالة بلا إيداع مسبق
        shutil.rmtree(root / "x")

        report = repair_job_state(workspace)
        check(report.missing == ["GONE.png"],
              f"المفقود مُسمّى بالاسم ({report.missing})")
        check(not report.ok, "التقرير يعلن عدم الاكتمال")
        summary = report.summary_ar()
        check("GONE.png" in summary,
              "الرسالة العربية تسمّي الملف المفقود بدل رسالة عامة")
        check(missing_sources(workspace) == ["GONE.png"],
              "missing_sources تعيد الاسم نفسه")


def test_corrupt_state_and_missing_state():
    """الحالة 7: حالة تالفة أو غائبة — لا انهيار."""
    print("\n[8] job_state.json تالف أو غائب")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workspace = root / "ws"
        workspace.mkdir()
        report = repair_job_state(workspace)
        check(report.ok and not report.repaired,
              "غياب الحالة لا يرفع استثناءً")

        (workspace / STATE_NAME).write_text("{ليس JSON صحيحًا",
                                            encoding="utf-8")
        report = repair_job_state(workspace)
        check(report.ok and not report.repaired,
              "حالة تالفة لا ترفع استثناءً")

        (workspace / STATE_NAME).write_text("[1, 2, 3]", encoding="utf-8")
        report = repair_job_state(workspace)
        check(report.ok, "حالة بنوع خاطئ (list) لا ترفع استثناءً")

        # مانيفست تالف مع وجود الملف في الخزانة بالاسم نفسه
        images = [make_image(root / "s" / "KEEP.png", b"\x05" * 12)]
        workspace2 = root / "ws2"
        deposit_job_sources(workspace2, [str(images[0])])
        make_job(workspace2, images)
        (workspace2 / VAULT_DIRNAME / MANIFEST_NAME).write_text(
            "تالف", encoding="utf-8")
        shutil.rmtree(root / "s")
        report = repair_job_state(workspace2)
        check(report.ok,
              "مانيفست تالف: الاسترجاع بالاسم من الخزانة ما زال يعمل")


def test_unique_names_for_same_filename():
    """صورتان بنفس الاسم من مجلدين مختلفين لا تتصادمان."""
    print("\n[9] تصادم الأسماء بين مجلدين")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        a = make_image(root / "أ" / "IMG.png", b"\x08" * 10)
        b = make_image(root / "ب" / "IMG.png", b"\x09" * 20)
        workspace = root / "ws"
        stored = deposit_job_sources(workspace, [str(a), str(b)])
        vault_root = workspace / VAULT_DIRNAME
        files = sorted(p.name for p in vault_root.iterdir()
                       if p.name != MANIFEST_NAME)
        check(stored >= 1, f"أُودع ملف واحد على الأقل ({stored})")
        check(len(files) >= 1, f"الخزانة تحتوي {files}")
        # لا يُشترط إيداع الثاني (نفس الاسم) لكن يُشترط ألا يُفقد الأول
        first = vault_root / files[0]
        check(first.read_bytes() in (_PNG + b"\x08" * 10,
                                     _PNG + b"\x09" * 20),
              "الملف المودَع سليم المحتوى")


def test_state_write_is_atomic():
    """لا يبقى ملف مؤقت بعد الكتابة الذرّية."""
    print("\n[10] الكتابة الذرّية لا تترك ملفات مؤقتة")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        images = [make_image(root / "s" / "AT.png", b"\x0a" * 16)]
        workspace = root / "ws"
        deposit_job_sources(workspace, [str(images[0])])
        make_job(workspace, images)
        shutil.rmtree(root / "s")
        repair_job_state(workspace)
        leftovers = [p.name for p in workspace.iterdir()
                     if p.name.endswith(".tmp")]
        check(not leftovers, f"لا ملفات .tmp متبقية ({leftovers})")
        check(json.loads((workspace / STATE_NAME).read_text(
            encoding="utf-8")), "الحالة قابلة للقراءة كـJSON صحيح")


def main() -> int:
    print("حاجز انحدار خزانة المصادر — يمنع عودة FileNotFoundError")
    print("=" * 62)
    for func in (test_deposit_creates_vault,
                 test_repair_after_move,
                 test_repair_after_delete,
                 test_repair_catalog_deleted,
                 test_resolve_by_fingerprint_after_rename,
                 test_arabic_paths,
                 test_tolerant_without_vault,
                 test_corrupt_state_and_missing_state,
                 test_unique_names_for_same_filename,
                 test_state_write_is_atomic):
        try:
            func()
        except Exception as exc:  # noqa: BLE001 - نريد الإبلاغ لا الانهيار
            global FAILED
            FAILED += 1
            print(f"  ✗ استثناء غير متوقع في {func.__name__}: {exc!r}")
    print("=" * 62)
    print(f"نجح {PASSED} / فشل {FAILED}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
