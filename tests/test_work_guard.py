# -*- coding: utf-8 -*-
"""اختبار `work_guard` و`editor_memory_patch` (م-14).

يتحقق من: الكتابة الذرّية، كشف الانهيار، الحفظ بالأحداث، إعلان
الإخفاق، وتخفيض ذاكرة التاريخ مع **مطابقة الاستعادة تمامًا**.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "windows_app"))

from windows_app.editor_memory_patch import (  # noqa: E402
    compress_snapshot, install_memory_patch, restore_snapshot)
from windows_app.work_guard import (  # noqa: E402
    CrashSentinel, atomic_write_json, install_work_guard)

FAILS: list[str] = []


def check(c: bool, msg: str) -> None:
    print(("  ✓ " if c else "  ✗ ") + msg)
    if not c:
        FAILS.append(msg)


class FakeBar:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def showMessage(self, m: str, t: int = 0) -> None:
        self.messages.append(m)


class FakeTimer:
    def __init__(self, ms: int) -> None:
        self.ms = ms

    def setInterval(self, ms: int) -> None:
        self.ms = ms


class FakeWindow:
    def __init__(self, fail_save: bool = False) -> None:
        self.saves: list[str] = []
        self.fail_save = fail_save
        self._bar = FakeBar()
        self._autosave_timer = FakeTimer(90_000)
        self.closed = False

    def statusBar(self) -> FakeBar:
        return self._bar

    def v2_save_session(self) -> None:
        if self.fail_save:
            raise RuntimeError("القرص ممتلئ")
        self.saves.append("saved")

    def _apply_manual_links(self, n: int = 1) -> str:
        return f"ربط {n}"

    def _set_primary_image(self) -> str:
        return "واجهة"

    def _save_nutrition_result(self) -> str:
        return "تغذية"

    def closeEvent(self, ev: object) -> str:
        self.closed = True
        return "closed"


def test_atomic():
    print("\n[1] الكتابة الذرّية")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "sub" / "state.json"
        atomic_write_json(p, {"صنف": "لبنة", "عدد": 3})
        check(p.exists(), "الملف أُنشئ مع مجلده")
        data = json.loads(p.read_text(encoding="utf-8"))
        check(data["صنف"] == "لبنة", "العربية سليمة بلا هروب")
        atomic_write_json(p, {"v": 2})
        check(json.loads(p.read_text(encoding="utf-8"))["v"] == 2,
              "الاستبدال نجح")
        leftovers = list(Path(d).rglob("*.tmp"))
        check(not leftovers, "لا ملفات مؤقتة متبقّية")


def test_sentinel():
    print("\n[2] مراقب الانهيار")
    with tempfile.TemporaryDirectory() as d:
        s1 = CrashSentinel(d)
        check(s1.check_previous() is None, "أول تشغيل: لا انهيار سابق")
        s1.begin("sess-1")
        check(s1.path.exists(), "علامة الجلسة فُتحت")
        s2 = CrashSentinel(d)              # محاكاة انهيار: لا end()
        prev = s2.check_previous()
        check(prev is not None and prev.get("session_id") == "sess-1",
              "الانهيار كُشف والجلسة معروفة")
        s2.begin("sess-2")
        s2.end()
        s3 = CrashSentinel(d)
        check(s3.check_previous() is None,
              "إغلاق نظيف ⇒ لا انهيار في التشغيل التالي")


def test_event_saves():
    print("\n[3] الحفظ الفوري بالأحداث")
    w = FakeWindow()
    rep = install_work_guard(w, autosave_seconds=20)
    check(rep.get("save_fn") == "v2_save_session", "وُجدت دالة الحفظ")
    check(len(rep["wrapped"]) >= 3,
          f"لُفّت الدوال الحاسمة ({len(rep['wrapped'])})")
    check(w._autosave_timer.ms == 20_000,
          f"الحفظ التلقائي قُصّر إلى {w._autosave_timer.ms//1000}ث "
          f"(كان 90)")

    n0 = len(w.saves)
    out = w._apply_manual_links(5)
    check(out == "ربط 5", "الدالة الأصلية تعمل كما هي")
    check(len(w.saves) == n0 + 1, "الربط تلاه حفظ فوري")
    w._set_primary_image()
    w._save_nutrition_result()
    check(len(w.saves) == n0 + 3, "تعيين الواجهة والتغذية حُفظا")
    w.closeEvent(None)
    check(w.closed and len(w.saves) == n0 + 4, "الإغلاق حفظ ثم أغلق")
    check(not w._work_guard_sentinel.path.exists(),
          "العلامة أُزيلت بالإغلاق النظيف")


def test_failure_surfaced():
    print("\n[4] إخفاق الحفظ يُعلَن لا يُبتلع")
    w = FakeWindow(fail_save=True)
    install_work_guard(w)
    w._apply_manual_links()
    msgs = w._bar.messages
    check(bool(msgs), "ظهرت رسالة في شريط الحالة")
    check(any("تعذّر حفظ" in m for m in msgs),
          f"الرسالة تشرح العطل: {msgs[:1]}")


class FakeCanvas:
    def __init__(self, h: int = 1200, w: int = 1600) -> None:
        self._history: list = []
        self._redo: list = []
        self.mask = np.zeros((h, w), np.uint8)
        self.mask[100:900, 100:900] = 255
        self.base = np.full((h, w, 3), 200, np.uint8)

    def _push_history(self) -> None:
        # السلوك الأصلي: نسختان كاملتان في كل لقطة
        self._history.append({"mask": self.mask.copy(),
                              "base": self.base.copy()})


def test_memory():
    print("\n[5] ذاكرة تاريخ المحرر")
    c = FakeCanvas()
    c._push_history()
    raw = sum(v.nbytes for v in c._history[0].values()
              if isinstance(v, np.ndarray))
    c._history.clear()

    rep = install_memory_patch(c)
    check(rep["patched"], "الرقعة رُكّبت")
    c._push_history()
    snap = c._history[0]
    comp = sum(len(v["png"]) for v in snap.values()
               if isinstance(v, dict) and v.get("mode") == "png")
    check(comp < raw * 0.10,
          f"الذاكرة انخفضت من {raw/1e6:.1f}م إلى {comp/1e6:.3f}م "
          f"({(1-comp/raw)*100:.1f}%−)")

    back = restore_snapshot(snap["mask"])
    check(back is not None and np.array_equal(back, c.mask),
          "الاستعادة **مطابقة تمامًا** (بلا خسارة)")

    c._redo = [{"m": np.zeros((1200, 1600), np.uint8)} for _ in range(60)]
    before = sum(v["m"].nbytes for v in c._redo)
    c._push_history()
    total = sum(v["m"].nbytes for v in c._redo)
    cap = 48 * 1024 * 1024
    check(total <= cap,
          f"قائمة الإعادة داخل السقف "
          f"({before/1e6:.0f}م ⇒ {total/1e6:.1f}م ≤ {cap/1e6:.0f}م)")
    check(total < before, f"التقليم حدث فعلًا ({len(c._redo)} لقطة)")


def test_compress_edge_cases():
    print("\n[6] حالات حدّية للضغط")
    check(compress_snapshot(None) is None, "None ⇒ None")
    check(restore_snapshot(None) is None, "استعادة None ⇒ None")
    rgba = np.random.randint(0, 255, (60, 60, 4), dtype=np.uint8)
    back = restore_snapshot(compress_snapshot(rgba))
    check(back is not None and np.array_equal(back, rgba),
          "RGBA أربع قنوات تُستعاد مطابقة")


def main():
    print("=" * 64)
    print("اختبار حماية العمل وذاكرة المحرر")
    print("=" * 64)
    test_atomic()
    test_sentinel()
    test_event_saves()
    test_failure_surfaced()
    test_memory()
    test_compress_edge_cases()
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
