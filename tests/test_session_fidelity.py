# -*- coding: utf-8 -*-
"""اختبار `session_fidelity_patch` (م-5).

يتحقق من: حفظ الحقول الثمانية عشر، **استرجاع العزل** بدل السقوط
إلى الصورة الخام، وعدّاد المنجز الذي يعتدّ بالربط اليدوي.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "windows_app"))

from windows_app.session_fidelity_patch import (  # noqa: E402
    DONE_STATUSES, FULL_FIELDS, install_session_fidelity, pick_display_path)

FAILS: list[str] = []


def check(c: bool, msg: str) -> None:
    print(("  ✓ " if c else "  ✗ ") + msg)
    if not c:
        FAILS.append(msg)


class Item:
    """محاكاة `BatchItemResult` بحقوله الثمانية عشر."""

    def __init__(self, name: str, src: str, out: str = "",
                 status: str = "matched") -> None:
        self.source_path = src
        self.source_name = name
        self.status = status
        self.item_code = "10000029"
        self.product_name = "لبنة"
        self.barcode = "6281000123456"
        self.confidence = 0.93
        self.explanation = ""
        self.output_path = out
        self.review_path = ""
        self.match_source = "barcode"
        self.barcode_candidates = ["6281000123456"]
        self.warnings = []
        self.processing_ms = 1220.0
        self.foreground_method = "isnet"
        self.foreground_quality_score = 0.98
        self.foreground_quality_status = "good"
        self.foreground_quality_metrics = {"edge": 0.97}


class Store:
    class _S:
        def __init__(self) -> None:
            self.images: dict = {}
            self.session_id = "sess-x"

    def __init__(self) -> None:
        self.state = Store._S()
        self.saved = 0

    def upsert_image(self, key: str, **fields) -> None:
        self.state.images.setdefault(key, {}).update(fields)

    def save(self, force: bool = False) -> None:
        self.saved += 1


class Result:
    def __init__(self, items: list) -> None:
        self.items = items
        self.workspace = "/tmp/ws"


class Window:
    """محاكاة الواجهة بسلوك الحفظ/الاستعادة **الأصلي المعطوب**."""

    def __init__(self, result: Result) -> None:
        self.current_result = result
        self.v2_session_store = Store()

    def v2_save_session(self, name: str = "") -> str:
        # السلوك الأصلي: ثمانية حقول فقط، و`output_path` يأخذ المراجعة
        for it in self.current_result.items:
            self.v2_session_store.upsert_image(
                it.source_name,
                source_path=it.source_path,
                status=it.status,
                barcode=it.barcode,
                item_code=it.item_code,
                item_name=it.product_name,
                output_path=it.review_path,
                error=it.explanation,
            )
        self.v2_session_store.save(force=True)
        return "sess-x"

    def v2_restore_session(self, state) -> None:
        # السلوك الأصلي: يسقط إلى الصورة الخام
        imgs = self.v2_session_store.state.images
        for it in self.current_result.items:
            d = imgs.get(it.source_name) or {}
            it.review_path = str(d.get("output_path") or it.source_path)


def test_full_fields():
    print("\n[1] حفظ الحقول الثمانية عشر")
    check(len(FULL_FIELDS) == 18,
          f"القائمة تحمل 18 حقلًا ({len(FULL_FIELDS)})")
    with tempfile.TemporaryDirectory() as d:
        raw = Path(d) / "IMG_1.jpg"
        out = Path(d) / "10000029_حبه.webp"
        raw.write_bytes(b"x")
        out.write_bytes(b"y")
        it = Item("IMG_1.jpg", str(raw), str(out))
        w = Window(Result([it]))

        w.v2_save_session()
        saved = w.v2_session_store.state.images["IMG_1.jpg"]
        check("confidence" not in saved,
              "قبل الرقعة: الحقول ناقصة (لا confidence)")
        check(saved.get("output_path") == "",
              "قبل الرقعة: output_path **فارغ** — سبب ذهاب العزل")

        w.v2_session_store.state.images.clear()
        rep = install_session_fidelity(w)
        check(rep["save_wrapped"] and rep["restore_wrapped"],
              "الرقعة رُكّبت على الحفظ والاستعادة")
        w.v2_save_session()
        saved = w.v2_session_store.state.images["IMG_1.jpg"]
        missing = [f for f in FULL_FIELDS if f not in saved]
        check(not missing, f"كل الحقول الثمانية عشر حُفظت (ناقص: {missing})")
        check(saved["output_path"] == str(out),
              "**output_path محفوظ** — مسار الصورة المعزولة")
        check(saved["foreground_quality_metrics"] == {"edge": 0.97},
              "الحقول المركّبة (قواميس) حُفظت")


def test_restore_keeps_isolation():
    print("\n[2] الاستعادة تُبقي العزل ولا تسقط إلى الخام")
    with tempfile.TemporaryDirectory() as d:
        raw = Path(d) / "IMG_2.jpg"
        out = Path(d) / "10000030_حبه.webp"
        raw.write_bytes(b"x")
        out.write_bytes(b"y")
        it = Item("IMG_2.jpg", str(raw), str(out))
        w = Window(Result([it]))

        w.v2_save_session()
        w.v2_restore_session(None)
        check(it.review_path == str(raw),
              "قبل الرقعة: العرض سقط إلى **الصورة الخام** (العطل)")

        it2 = Item("IMG_2.jpg", str(raw), str(out))
        w2 = Window(Result([it2]))
        install_session_fidelity(w2)
        w2.v2_save_session()
        it2.review_path = ""
        w2.v2_restore_session(None)
        check(it2.review_path == str(out),
              "بعد الرقعة: العرض على **الصورة المعزولة**")
        check(it2.output_path == str(out), "output_path استُرجع")
        check(abs(it2.confidence - 0.93) < 1e-9,
              "بقية الحقول استُرجعت (confidence)")


def test_display_path_priority():
    print("\n[3] أولوية مسار العرض")
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "o.webp"
        rev = Path(d) / "r.webp"
        raw = Path(d) / "s.jpg"
        for p in (out, rev, raw):
            p.write_bytes(b"z")
        check(pick_display_path(str(out), str(rev), str(raw)) == str(out),
              "المعزول أولًا")
        check(pick_display_path("", str(rev), str(raw)) == str(rev),
              "ثم المراجعة")
        check(pick_display_path("", "", str(raw)) == str(raw),
              "ثم الخام كملاذ أخير")
        ghost = str(Path(d) / "missing.webp")
        check(pick_display_path(ghost, "", str(raw)) == ghost,
              "مسار مفقود مؤقتًا يُحتفظ به نصيًا (لا يسقط للخام)")


def test_done_count():
    print("\n[4] عدّاد المنجز يعتدّ بالربط اليدوي")
    check("manual" in DONE_STATUSES and "manual_linked" in DONE_STATUSES,
          "حالات الربط اليدوي مُعتَدّ بها")
    try:
        from engine_v2.session_v2 import SessionState
    except Exception as exc:                       # pragma: no cover
        check(False, f"تعذّر استيراد SessionState: {exc}")
        return
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "x.webp"
        out.write_bytes(b"q")
        s = SessionState()
        s.images = {
            "a.jpg": {"status": "matched"},
            "b.jpg": {"status": "manual"},
            "c.jpg": {"status": "review", "output_path": str(out)},
            "d.jpg": {"status": "review"},
        }
        # ملاحظة: الرقعة تُركّب على **الصنف** لا على نسخة، فلا
        # يمكن قياس «قبل» بعد التركيب في نفس العملية (رقعة
        # جلسة أخرى رُكّبت فعلًا في الفحوص السابقة). فنقيس
        # السلوك الأصلي بدالة مستقلة تحاكيه حرفيًا.
        def original_done_count(st) -> int:
            done = 0
            for v in st.images.values():
                s_ = str(v.get("status", ""))
                if s_ in ("matched", "done", "approved") or v.get("approved"):
                    done += 1
            return done

        before = original_done_count(s)
        check(before == 1,
              f"المنطق الأصلي يعُدّ {before} فقط من 3 منجزة فعلًا")
        install_session_fidelity(Window(Result([])))
        after = s.done_count()
        check(after == 3,
              f"بعد الرقعة: عُدّ {after} (matched + manual + ذو ناتج)")


def main():
    print("=" * 64)
    print("اختبار أمانة الجلسة واسترجاع العزل")
    print("=" * 64)
    test_full_fields()
    test_restore_keeps_isolation()
    test_display_path_priority()
    test_done_count()
    print("\n" + "=" * 64)
    if FAILS:
        print(f"إخفاقات: {len(FAILS)}")
        for f in FAILS:
            print(f"  · {f}")
        return 1
    print("كل الفحوص نجحت")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
