# -*- coding: utf-8 -*-
"""اختبار nutrition_patch (م-7 م-18)."""
from __future__ import annotations
import sys, tempfile
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "windows_app"))

from windows_app.nutrition_patch import install_nutrition_patch

FAILS: list[str] = []
def check(c: bool, msg: str) -> None:
    print(("  ✓ " if c else "  ✗ ") + msg)
    if not c: FAILS.append(msg)

class FakeWin:
    def __init__(self):
        self.saves = []
        self.status = ""
    def _open_nutrition_crop(self): pass
    def _save_nutrition_result(self, sel, cropped, on_canvas, product_img=None, placement=None):
        self.saves.append({"sel": sel, "overwrite": False})
        return "new_file.webp"
    def status_label(self): pass

def test_install():
    print("\n[1] تركيب رقعة التغذية")
    w = FakeWin()
    rep = install_nutrition_patch(w)
    check(rep["open_wrapped"], "لفّ _open_nutrition_crop")
    check(rep["save_wrapped"], "لفّ _save_nutrition_result")
    check(hasattr(w._save_nutrition_result, "_nutrition_patched"),
          "الدالة مُعلَّمة")

def test_save_normal():
    print("\n[2] الحفظ العادي يعمل كما كان")
    w = FakeWin()
    install_nutrition_patch(w)
    img = np.zeros((100, 100, 3), np.uint8)
    result = w._save_nutrition_result(None, img, True)
    check(result == "new_file.webp", "الحفظ العادي يعيد اسم الملف")
    check(len(w.saves) == 1, "الحفظ الأصلي نُفِّذ")

def main():
    print("=" * 50)
    print("اختبار nutrition_patch")
    print("=" * 50)
    test_install()
    test_save_normal()
    print("\n" + "=" * 50)
    if FAILS:
        print(f"إخفاقات: {len(FAILS)}")
        for f in FAILS: print(f"  · {f}")
        return 1
    print("كل الفحوص نجحت")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
