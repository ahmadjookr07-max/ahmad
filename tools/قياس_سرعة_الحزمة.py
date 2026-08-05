"""قياس أثر إصلاح البطء في كتابة حزمة التسليم (2.9.12).

يقارن الطريقة الأصلية (DEFLATE مستوى 6 على كل الصور) بالطريقة
الجديدة (STORED للصور، DEFLATE للتقارير وحدها).

يُشغَّل: ``python3 tools/قياس_سرعة_الحزمة.py [عدد_الصور]``
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import time
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]
                       / "windows_app"))

import numpy as np                                       # noqa: E402
from PIL import Image                                    # noqa: E402

from delivery_zip_fast import write_delivery_zip          # noqa: E402


class _Item:
    def __init__(self, path: pathlib.Path) -> None:
        self.output_path = str(path)


class _Result:
    def __init__(self, items, zip_path) -> None:
        self.items = items
        self.report_json = ""
        self.report_csv = ""
        self.delivery_zip = str(zip_path)


def main() -> int:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    root = pathlib.Path(tempfile.mkdtemp())
    out = root / "out"
    out.mkdir()

    # صورة واقعية: ضوضاء ممهّدة تشبه صورة منتج على خلفية بيضاء
    rng = np.random.default_rng(0)
    base = (rng.random((700, 800, 3)) * 60 + 195).astype("uint8")
    image = Image.fromarray(base)
    for index in range(count):
        image.save(out / f"1000{index:04d}_حبه.webp", "WEBP", quality=92)

    total = sum(p.stat().st_size for p in out.glob("*.webp"))
    print(f"عدد الصور: {count} | الحجم الكلي: {total / 1e6:.1f} م.ب")

    items = [_Item(p) for p in sorted(out.glob("*.webp"))]
    result = _Result(items, root / "delivery.zip")

    # الطريقة الأصلية
    started = time.time()
    temporary = root / "old.zip.tmp"
    with zipfile.ZipFile(temporary, "w",
                         compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6) as archive:
        for item in items:
            archive.write(item.output_path,
                          f"processed/{os.path.basename(item.output_path)}")
    os.replace(temporary, root / "old.zip")
    old_seconds = time.time() - started

    # الطريقة الجديدة
    started = time.time()
    write_delivery_zip(result, root)
    new_seconds = time.time() - started

    old_size = os.path.getsize(root / "old.zip") / 1e6
    new_size = os.path.getsize(root / "delivery.zip") / 1e6
    print(f"الأصلية (DEFLATE 6): {old_seconds:6.2f} ث | {old_size:5.1f} م.ب")
    print(f"الجديدة (STORED)   : {new_seconds:6.2f} ث | {new_size:5.1f} م.ب")
    print(f"التسريع: {old_seconds / max(new_seconds, 1e-6):.1f}x"
          f" | فرق الحجم: {new_size - old_size:+.1f} م.ب")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
