"""اختبار الطريق الموحّد للمجلدات المنجزة سابقًا (يحلّ محلّ
test_rename_excel.py الذي كان يختبر نافذة BulkRenameDialog الملغاة).

قرار المالك (2.9.4):
- كل شيء في **واجهة واحدة**: لا نافذة تعديل منفصلة.
- **الإكسل مرجع كل شيء**: الوحدة تُقرأ حرفيًا كما كُتبت فيه
  (حبه/حبة/شدة/شده/ربطة) بلا تطبيع، وتُختار الوحدة ذات العبوة = 1.
- قاعدة التسمية (2.9.12): الواجهة `رقم_الوحدة` بلا رقم،
  ثم `-1`، `-2`، `-3`. (تغيير مقصود عن 2.9.9 التي كانت تبدأ
  من `-2` وتمنع `-1`.)
- إضافة الإكسل تُصحّح التسميات **مباشرة بلا زر**.

يعمل الاختبار على بيانات مُصنّعة فلا يعتمد على مجلد المالك.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "windows_app"))

from engine_v2.legacy_folder_v2 import (  # noqa: E402
    scan_legacy_folder, plan_legacy_renames, apply_legacy_plan)

FAILURES: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        FAILURES.append(label)


class FakeIndex:
    """فهرس مصغّر يحاكي CatalogIndex: الوحدة ذات العبوة=1 هي الأساسية."""

    def __init__(self, table: dict[str, list[tuple[str, float]]]) -> None:
        self._t = table

    def primary_unit_for_code(self, code: str) -> str | None:
        rows = self._t.get(str(code))
        if not rows:
            return None
        ones = [u for u, p in rows if abs(p - 1.0) < 1e-9]
        return ones[0] if ones else rows[0][0]

    def lookup_code(self, code: str):
        rows = self._t.get(str(code))
        if not rows:
            return None
        return {"name": f"صنف {code}", "barcode": "", "unit": rows[0][0]}


def make_folder(base: Path, names: list[str]) -> Path:
    folder = base / "processed"
    folder.mkdir(parents=True, exist_ok=True)
    for i, n in enumerate(names):
        # محتوى مميّز لكل ملف حتى تُكشف أي مبادلة خاطئة
        (folder / n).write_bytes(b"IMG" + bytes([i]) * 8)
    return folder


def _plan(folder: Path, idx):
    """يمسح ثم يبني الخطة (groups, index, unparsed)."""
    groups, unparsed = scan_legacy_folder(folder)
    return plan_legacy_renames(groups, idx, unparsed)


def stems(folder: Path) -> list[str]:
    return sorted(p.stem for p in folder.iterdir() if p.is_file())


def run() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="legacy_unified_"))
    try:
        # ---- 1) النمط القديم _N يتحول إلى قاعدة المالك -N ----
        folder = make_folder(tmp / "a", [
            "10000015_حبه.webp",
            "10000015_حبه_2.webp",
            "10000015_حبه_3.webp",
        ])
        idx = FakeIndex({"10000015": [("حبه", 1.0), ("باكت", 4.0)]})
        groups, unparsed = scan_legacy_folder(folder)
        check(len(groups) == 1, "التجميع برقم الصنف: مجموعة واحدة")
        plan = plan_legacy_renames(groups, idx, unparsed)
        apply_legacy_plan(plan)
        got = stems(folder)
        check(got == ["10000015_حبه", "10000015_حبه-1", "10000015_حبه-2"],
              f"النمط القديم _N صار قاعدة المالك -N ({got})")
        check(not any("_2" in s or "_3" in s for s in got),
              "لم يبق أثر للنمط القديم")

        # ---- 2) الوحدة تُصحّح من الإكسل (العبوة = 1) ----
        folder = make_folder(tmp / "b", ["10011250_حبه.webp"])
        idx = FakeIndex({"10011250": [("باكت", 1.0), ("حبه", 12.0)]})
        plan = _plan(folder, idx)
        apply_legacy_plan(plan)
        check(stems(folder) == ["10011250_باكت"],
              f"الإكسل مرجع الوحدة حتى لصنف صورة واحدة ({stems(folder)})")

        # ---- 3) الإملاء الحرفي يُحفظ بلا تطبيع همزة ----
        for unit in ("حبه", "حبة", "شدة", "شده", "ربطة"):
            folder = make_folder(tmp / f"c_{unit}", [f"555_كرتون.webp"])
            idx = FakeIndex({"555": [(unit, 1.0)]})
            plan = _plan(folder, idx)
            apply_legacy_plan(plan)
            check(stems(folder) == [f"555_{unit}"],
                  f"الإملاء الحرفي محفوظ: {unit}")

        # ---- 4) لا فقد ولا ملفات مؤقتة ولا تصادم ----
        names = ["777_حبه.webp"] + [f"777_حبه_{i}.webp" for i in range(2, 18)]
        folder = make_folder(tmp / "d", names)
        idx = FakeIndex({"777": [("حبه", 1.0)]})
        before = len(list(folder.iterdir()))
        plan = _plan(folder, idx)
        apply_legacy_plan(plan)
        after = [p for p in folder.iterdir() if p.is_file()]
        check(len(after) == before, f"لا فقد ملفات ({before} ⇒ {len(after)})")
        check(not any(p.name.startswith("__") for p in after),
              "لا ملفات مؤقتة متبقية")
        # 2.9.12 — الواجهة بلا رقم، والبقية -1 .. -16.
        # `-1` صار مشروعًا (يعني الصورة الثانية) بعدما كان
        # محظورًا في 2.9.9 — بأمر المالك الصريح.
        seq = sorted(s for s in stems(folder) if "-" in s)
        expect = [f"777_حبه-{i}" for i in range(1, 17)]
        check(sorted(seq) == sorted(expect),
              "تسلسل 16 صورة متصل بلا ثغرة ولا تصادم")
        check(sum(1 for s in stems(folder) if "-" not in s) == 1,
              "الواجهة وحدها بلا رقم")

        # ---- 5) صنف غائب عن الإكسل يُترك كما هو (لا إفساد) ----
        folder = make_folder(tmp / "e", ["99999_حبه.webp"])
        idx = FakeIndex({})
        plan = _plan(folder, idx)
        apply_legacy_plan(plan)
        check(stems(folder) == ["99999_حبه"],
              "صنف غائب عن الإكسل يبقى بلا تغيير")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nإجمالي: نجاح={0}  فشل={len(FAILURES)}"
          .replace("نجاح=0", f"فشل_قائمة={FAILURES}" if FAILURES else "نجاح=كل"))
    if FAILURES:
        raise SystemExit(1)
    print("LEGACY FOLDER UNIFIED TESTS PASSED")


if __name__ == "__main__":
    run()
