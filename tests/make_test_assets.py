# -*- coding: utf-8 -*-
"""توليد أصول اختبار بديلة: صورة منتج اصطناعية + ملف إكسل كتالوج صغير.

مجلد الأصول يُحدَّد بمتغير البيئة TEST_ASSETS_DIR؛ وإن غاب فيُستخدم
/home/ubuntu/upload على لينكس أو <جذر المشروع>/test_assets على ويندوز،
حتى يعمل الاختبار في الساندبوكس وعلى مُشغّل ويندوز في CI على حد سواء."""
import os
import sys
from pathlib import Path

import cv2
import numpy as np


def assets_dir() -> Path:
    env = os.environ.get("TEST_ASSETS_DIR", "").strip()
    if env:
        return Path(env)
    legacy = Path("/home/ubuntu/upload")
    if legacy.parent.is_dir():
        return legacy
    return Path(__file__).resolve().parent.parent / "test_assets"


UP = assets_dir()
UP.mkdir(parents=True, exist_ok=True)

# صورة منتج اصطناعية (عبوة على خلفية فاتحة)
img = np.full((1200, 900, 3), 235, np.uint8)
cv2.rectangle(img, (300, 200), (600, 900), (60, 90, 160), -1)   # جسم العبوة
cv2.rectangle(img, (330, 250), (570, 420), (255, 255, 255), -1)  # ملصق
cv2.putText(img, "PRODUCT", (350, 340), cv2.FONT_HERSHEY_SIMPLEX,
            1.0, (30, 30, 30), 2)
cv2.putText(img, "1L", (420, 400), cv2.FONT_HERSHEY_SIMPLEX,
            1.0, (30, 30, 30), 2)
names = ["3988D8E6-BF91-4876-9438-C7D2E931A303.jpeg",
         "test_product_a.jpeg", "test_product_b.jpeg"]
for n in names:
    p = UP / n
    if not p.exists():
        cv2.imwrite(str(p), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
        print("created", p)

# ملف إكسل كتالوج صغير
try:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["رقم الصنف", "الباركود", "اسم الصنف", "الوحدة"])
    rows = [
        ("10012345", "6281000000012", "بادك زيت زيتون 1لتر", "حبه"),
        ("10014649", "6281000000029", "شامبو صن سلك 400مل", "حبه"),
        ("10021777", "6281000000036", "ارز بشاور 5كيلو", "كيس"),
    ]
    for r in rows:
        ws.append(list(r))
    xlsx = UP / "test_catalog.xlsx"
    if not xlsx.exists():
        wb.save(str(xlsx))
        print("created", xlsx)
except Exception as e:
    print("excel skip:", e)
    sys.exit(1)
print("done")
