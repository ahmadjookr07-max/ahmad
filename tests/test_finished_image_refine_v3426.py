# -*- coding: utf-8 -*-
"""حارس v3.4.26: تحسين الصور المنجزة يفحص الكل ويصلح العيوب الآمنة فقط."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "windows_app"), str(ROOT / "src")]
from pipeline_patch import (apply_completion_to_finished, apply_shadow_to_finished,
                            batch_process_finished)

FAILS: list[str] = []


def check(condition: bool, label: str) -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        FAILS.append(label)


def product_canvas() -> np.ndarray:
    image = np.full((260, 260, 3), 255, np.uint8)
    cv2.rectangle(image, (55, 36), (205, 220), (55, 115, 205), -1)
    return image


# ظل: القناع يجب أن يكون 0..255، لا 0..1؛ وتظهر بكسلات ظل تحت المنتج.
base = product_canvas()
shadowed = apply_shadow_to_finished(base)
check(shadowed.shape == base.shape, "الظل يحافظ على أبعاد الصورة")
check(not np.array_equal(shadowed, base), "الظل يغير الخلفية تحت المنتج فعليًا")
check(int(shadowed[222:250, 55:205].min()) < 248, "يوجد تدرج ظل خفيف أسفل القاعدة")

# ثقب داخلي كبير نسبيًا وغير نصي: يصلحه المسار المحافظ بالنسيج لا بالأبيض.
hole_image = product_canvas()
hole_image[105:137, 110:142] = (255, 255, 255)
repaired = apply_completion_to_finished(hole_image)
check(repaired.shape == hole_image.shape, "إكمال النقص يحافظ على الأبعاد")
check(int(repaired[116:126, 121:131].mean()) < 245, "الفجوة الداخلية الآمنة لا تبقى بيضاء")

# عنصران منفصلان: لا دمج تلقائي ولا حذف لأحدهما.
multi = np.full((260, 260, 3), 255, np.uint8)
cv2.rectangle(multi, (25, 45), (105, 210), (30, 90, 200), -1)
cv2.rectangle(multi, (155, 60), (235, 195), (20, 150, 80), -1)
unchanged_multi = apply_completion_to_finished(multi)
check(np.array_equal(unchanged_multi, multi), "العناصر المنفصلة لا تُدمج أو تُحذف تلقائيًا")

with tempfile.TemporaryDirectory(prefix="finished_refine_") as td:
    folder = Path(td)
    cv2.imwrite(str(folder / "100001_حبه.webp"), hole_image, [cv2.IMWRITE_WEBP_QUALITY, 100])
    cv2.imwrite(str(folder / "100002_حبه.webp"), multi, [cv2.IMWRITE_WEBP_QUALITY, 100])
    before = sorted(path.name for path in folder.glob("*.webp"))
    result = batch_process_finished(folder, add_shadow=False, complete=True)
    after = sorted(path.name for path in folder.glob("*.webp"))
    check(result["examined"] == 2, "تفحص الدفعة كل الصور المنجزة")
    check(result["processed"] >= 1, "تُحسن الدفعة العيب المؤكد")
    check(result["unchanged"] >= 1, "تسجل الصورة غير الآمنة كغير متغيرة لا كمتخطاة")
    check(result["skipped"] == 0 and not result["errors"], "لا أخطاء أو تخطٍ للصور القابلة للقراءة")
    check(before == after, "يعاد الحفظ فوق الاسم نفسه بلا نسخ أو ترقيم جديد")

print("ALL:", "PASS" if not FAILS else "FAIL")
sys.exit(0 if not FAILS else 1)
