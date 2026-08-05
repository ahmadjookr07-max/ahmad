# -*- coding: utf-8 -*-
"""حارس إصلاحات 2.9.12 — كل عطب أبلغ عنه المالك له فحص هنا.

الغرض من هذا الملف أن يمنع **تراجع** أي إصلاح من إصلاحات هذا
الإصدار. كل قسم يذكر العطب الأصلي بلسان المالك، ثم يفحص
السلوك الصحيح على القرص لا على النية.

الأعطال المغطّاة:
  ع-1  اختفاء الأصناف/الصور عند «اربط صورة بندك»
  ع-3  فشل حفظ التحرير بعد الطمس (★ لا يُحدّث القرص)
  ع-4  صور حقائق التغذية تنزل أسفل القائمة باسم شاذ
  ع-5  البطء عند الحفظ والتعديل (كتابة حزمة التسليم)
  ع-6  الترقيم: الأولى بلا رقم ثم 1 ثم 2
  ع-7  ترحيل المجلدات القديمة مع نسخة احتياطية

يعمل على بيانات مُصنّعة، فلا يحتاج مجلد المالك ولا محركًا ثقيلًا.
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
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "windows_app"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MIS_SKIP_LICENSE", "1")
os.environ.setdefault("MIS_HEADLESS", "1")

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, note: str = "") -> bool:
    (PASS if cond else FAIL).append(name)
    print(("  ✓ " if cond else "  ✗ ") + name + (f" — {note}" if note else ""))
    return bool(cond)


def head(title: str) -> None:
    print(f"\n{title}")


# ═══════════════ ع-6: اصطلاح الترقيم ═══════════════

def t_numbering() -> None:
    head("[ع-6] الترقيم: الأولى بلا رقم ثم 1 ثم 2")
    from engine_v2 import naming_v2 as N

    seq = [N.build_name_join_all("777", ["حبه"], i) for i in (1, 2, 3, 4)]
    check("التسلسل الصحيح",
          seq == ["777_حبه", "777_حبه-1", "777_حبه-2", "777_حبه-3"], str(seq))

    # الكتابة والقراءة متلازمتان: ما يُكتب يُقرأ برتبته نفسها.
    # انفصامهما هو ما جعل الصور «تختفي» فعليًا.
    for rank in (1, 2, 3, 7):
        stem = N.build_name_join_all("555", ["حبه"], rank)
        parsed = N.parse_name(stem)
        got = getattr(parsed, "seq", None) if parsed else None
        check(f"القراءة تُرجع الرتبة {rank}", got == rank,
              f"{stem} ⇒ {got}")

    check("لا تصادم بين الواجهة والثانية",
          N.build_name_join_all("9", ["حبه"], 1)
          != N.build_name_join_all("9", ["حبه"], 2))


# ═══════════════ ع-1: سياق إعادة المعالجة ═══════════════

def t_reprocess_scope() -> None:
    head("[ع-1] إعادة المعالجة تكتب فوق الملف نفسه لا تُنشئ اسمًا جديدًا")
    from engine_v2 import integration_v2 as I

    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        first = out / "10001102_حبه.webp"
        second = out / "10001102_حبه-1.webp"
        other = out / "10002222_حبه.webp"
        for p in (first, second, other):
            p.write_bytes(b"x")

        # داخل السياق: إعادة معالجة الصورة نفسها تحتفظ باسمها.
        with I.reprocess_scope("10001102", first.stem):
            again = I.build_output_stem(str(out), "10001102", "حبه")
        check("إعادة المعالجة تحتفظ بالاسم", again == "10001102_حبه", again)

        with I.reprocess_scope("10001102", second.stem):
            again2 = I.build_output_stem(str(out), "10001102", "حبه")
        check("إعادة معالجة الصورة الثانية تحتفظ برقمها",
              again2 == "10001102_حبه-1", again2)

        # خارج السياق: صورة جديدة تأخذ رقمًا جديدًا لا تطمس شيئًا.
        fresh = I.build_output_stem(str(out), "10001102", "حبه")
        check("الصورة الجديدة لا تطمس القائم",
              not (out / f"{fresh}.webp").exists(), fresh)

        # السياق مقيّد برمز الصنف؛ وإلا لطمست إعادة
        # معالجة صنفٍ صورةَ صنفٍ آخر.
        with I.reprocess_scope("10001102", first.stem):
            unrelated = I.build_output_stem(str(out), "10002222", "حبه")
        check("صنف آخر لا يرث اسم السياق",
              unrelated != first.stem, unrelated)


# ═══════════════ ع-3: مزامنة الحالة على القرص ═══════════════

def t_state_sync() -> None:
    head("[ع-3] ★ تكتب إعادة التسمية في job_state.json لا في الذاكرة فقط")
    from engine_v2.state_sync_v2 import sync_renamed_outputs

    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        out = ws / "out"
        out.mkdir()
        old = out / "10001102_حبه-1.webp"
        new = out / "10001102_حبه.webp"
        new.write_bytes(b"x")

        state = ws / "job_state.json"
        state.write_text(json.dumps({
            "items": [{"item_code": "10001102",
                       "output_path": str(old),
                       "source_name": "a.jpg"}]
        }, ensure_ascii=False), encoding="utf-8")

        report = sync_renamed_outputs(str(ws), {str(old): str(new)})
        raw = state.read_text(encoding="utf-8")
        check("الحالة كُتبت فعلًا",
              bool(report.get("written")) and report.get("updated", 0) >= 1,
              str(report))
        check("المسار الجديد في الملف", str(new) in raw or new.name in raw)
        check("المسار القديم زال", old.name not in raw)

        # الكتابة ذرّية: لا يبقى ملف مؤقت معلّق بعد النجاح.
        leftovers = [p.name for p in ws.iterdir()
                     if p.name.startswith(".") or p.suffix == ".tmp"]
        check("لا ملفات مؤقتة معلّقة", not leftovers, str(leftovers))


# ═══════════════ ع-4: تسمية صور التغذية ═══════════════

def t_nutrition_naming() -> None:
    head("[ع-4] صورة حقائق التغذية بالنمط الرسمي لا `(2)`")
    from engine_v2 import naming_v2 as N
    import nutrition_crop as NC

    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        base = out / "10001102_حبه.webp"
        base.write_bytes(b"x")

        p1 = Path(NC._next_nutrition_path(out, "10001102"))
        p1.write_bytes(b"y")
        p2 = Path(NC._next_nutrition_path(out, "10001102"))

        check("لا قوس في الاسم", "(" not in p1.name and "(" not in p2.name,
              f"{p1.name} | {p2.name}")
        check("الاسمان مختلفان", p1.name != p2.name, f"{p1.name} {p2.name}")
        for p in (p1, p2):
            parsed = N.parse_name(p.stem)
            check(f"أداة الفرز تقرأ {p.stem}", parsed is not None)


# ═══════════════ ع-5: سرعة كتابة حزمة التسليم ═══════════════

def t_delivery_zip_speed() -> None:
    head("[ع-5] كتابة حزمة التسليم سريعة ولا تفقد ملفًا")
    import zipfile

    from delivery_zip_fast import write_delivery_zip

    class _Item:
        def __init__(self, path: str) -> None:
            self.output_path = path

    class _Result:
        def __init__(self, zip_path: str, items: list) -> None:
            self.delivery_zip = zip_path
            self.items = items

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "out"
        out.mkdir()
        # 120 صورة webp مصغّرة تكفي لقياس الفارق بلا إبطاء الحزمة.
        payload = b"RIFF" + b"\0" * 4096
        items = []
        for i in range(120):
            p = out / f"1000{i:04d}_حبه.webp"
            p.write_bytes(payload)
            items.append(_Item(str(p)))

        zip_path = Path(td) / "تسليم.zip"
        t0 = time.perf_counter()
        ok = write_delivery_zip(_Result(str(zip_path), items), Path(td))
        elapsed = time.perf_counter() - t0

        check("الحزمة كُتبت", bool(ok) and zip_path.is_file())
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            bad = zf.testzip()
        check("لا صورة مفقودة", len(names) == 120, f"{len(names)}/120")
        check("الحزمة سليمة", bad is None, str(bad))
        check("الكتابة سريعة (أقل من ثانيتين)", elapsed < 2.0,
              f"{elapsed:.3f} ث")


# ═══════════════ ع-7: ترحيل الأسماء القديمة ═══════════════

def t_migration() -> None:
    head("[ع-7] ترحيل المجلد القديم (-2,-3) إلى الجديد (-1,-2) بنسخة احتياطية")
    from engine_v2 import naming_v2 as N

    tmp = Path(tempfile.mkdtemp(prefix="migrate_"))
    try:
        folder = tmp / "منجز"
        folder.mkdir()
        for name, body in (("10001102_حبه.webp", b"a"),
                           ("10001102_حبه-2.webp", b"b"),
                           ("10001102_حبه-3.webp", b"c")):
            (folder / name).write_bytes(body)

        check("المجلد يحتاج ترحيلًا",
              N.folder_needs_dash_migration(folder))

        res = N.migrate_legacy_dash_names(folder)
        names = sorted(p.name for p in folder.glob("*.webp"))
        backup_dir = str(res.get("backup_dir", ""))
        check("الأسماء رُحِّلت",
              names == ["10001102_حبه-1.webp", "10001102_حبه-2.webp",
                        "10001102_حبه.webp"], str(names))
        # المحتوى تبع اسمه: لا مبادلة صامتة بين الصور.
        check("المحتوى لم يُبادَل",
              (folder / "10001102_حبه-1.webp").read_bytes() == b"b"
              and (folder / "10001102_حبه-2.webp").read_bytes() == b"c")
        check("النسخة الاحتياطية موجودة",
              bool(backup_dir) and Path(backup_dir).is_dir(), backup_dir)
        check("النسخة الاحتياطية كاملة",
              bool(backup_dir)
              and len(list(Path(backup_dir).glob("*.webp"))) == 3)
        # النسخة خارج مجلد المخرجات لئلا تدخل في حزمة التسليم.
        check("النسخة خارج مجلد المخرجات",
              bool(backup_dir) and folder not in Path(backup_dir).parents,
              backup_dir)

        # الترحيل لا يتكرر: تشغيله ثانيةً لا يزحزح شيئًا.
        check("لا يحتاج ترحيلًا ثانيًا",
              not N.folder_needs_dash_migration(folder))
        N.migrate_legacy_dash_names(folder)
        names2 = sorted(p.name for p in folder.glob("*.webp"))
        check("الترحيل المزدوج آمن", names2 == names, str(names2))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ═══════════════ سلامة الربط في الواجهة ═══════════════

def t_wiring() -> None:
    head("[ربط] الإصلاحات موصولة فعلًا بالواجهة لا معلّقة في الفراغ")
    app_src = (ROOT / "windows_app" / "native_app.py").read_text(
        encoding="utf-8", errors="ignore")
    lazy_src = (ROOT / "windows_app" / "lazy_engine.py").read_text(
        encoding="utf-8", errors="ignore")

    check("ترقيعات السلامة مربوطة بتحميل المحرك",
          "integrity_patch" in lazy_src)
    check("الربط اليدوي يستعمل سياق إعادة المعالجة",
          "_reprocess_scope" in app_src)
    check("التحرير الفردي يستقبل المخرَج السابق",
          "previous_output" in app_src)
    check("★ تزامن الحالة على القرص",
          "sync_renamed_outputs" in app_src)
    check("الترحيل يُستدعى عند فتح مجلد منجَز",
          "_migrate_legacy_naming" in app_src)
    check("حزمة التسليم تُكتب بالوحدة السريعة",
          "delivery_zip_fast" in app_src)
    check("الحزمة تُفرَّغ قبل التسليم والإغلاق",
          app_src.count("scheduler.flush") >= 2,
          f"{app_src.count('scheduler.flush')} موضعًا")


def main() -> int:
    print("=" * 62)
    print("حارس إصلاحات 2.9.12")
    print("=" * 62)
    for fn in (t_numbering, t_reprocess_scope, t_state_sync,
               t_nutrition_naming, t_delivery_zip_speed, t_migration,
               t_wiring):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            check(f"{fn.__name__} اكتمل بلا استثناء", False,
                  f"{type(exc).__name__}: {exc}")
    print("\n" + "=" * 62)
    print(f"النتيجة: {len(PASS)} ناجح / {len(FAIL)} فاشل")
    if FAIL:
        print("الفاشل:", FAIL)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
