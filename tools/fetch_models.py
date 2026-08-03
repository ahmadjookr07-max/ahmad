# -*- coding: utf-8 -*-
"""ينزّل نماذج القص إلى `src/engine_v2/models/` ويتحقق من بصماتها.

لماذا سكربت مستقل لا أوامر داخل خط البناء؟ لأن نفس المنطق يحتاجه
ثلاثة: خط البناء السحابي، والمالك على جهازه، وأي مستنسخ للمستودع.
وتكرار الأوامر في ثلاثة أماكن يعني تباعدها حتمًا.

ولماذا التحقق بالبصمة لا بالحجم؟ لأن الحجم يخدع: ملف مقطوع قد يوافق
الحجم المتوقع، وملف مبدَّل من مصدر مخترق يوافقه بالضرورة. والنموذج
يُنفَّذ داخل onnxruntime، فتحميل ملف غير موثوق ليس مجرد خطأ جودة.

    python3 tools/fetch_models.py            # الإلزامي فقط (isnet + u2netp)
    python3 tools/fetch_models.py --all      # يضيف u2net (176م.ب، اختياري)
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "src" / "engine_v2" / "models"

_BASE = "https://github.com/danielgatis/rembg/releases/download/v0.0.0"

# البصمات مأخوذة من النسخ العاملة المُختبَرة في هذا المشروع، وتأكّد
# تطابق أحجامها مع المصدر الرسمي بايتًا ببايت قبل التسجيل.
MODELS: dict[str, dict] = {
    "isnet-general-use.onnx": {
        "size": 178648008,
        "sha256": "60920e99c45464f2ba57bee2ad08c919a"
                  "52bbf852739e96947fbb4358c0d964a",
        "required": True,
        "why": "النموذج الأدق — أساس القص",
    },
    "u2netp.onnx": {
        "size": 4574861,
        "sha256": "309c8469258dda742793dce0ebea8e6d"
                  "d393174f89934733ecc8b14c76f4ddd8",
        "required": True,
        "why": "شبكة أمان خفيفة (4.4م.ب) تضمن عمل القص دائمًا",
    },
    "u2net.onnx": {
        "size": 175997641,
        "sha256": "8d10d2f3bb75ae3b6d527c77944fc5e7"
                  "dcd94b29809d47a739a7a728a912b491",
        "required": False,
        "why": "احتياطي متوسط — منفعته حدية أمام isnet",
    },
}


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _ok(path: Path, meta: dict) -> bool:
    """هل الملف موجود وسليم؟ نفحص الحجم أولًا لأنه رخيص."""
    if not path.is_file():
        return False
    if path.stat().st_size != meta["size"]:
        return False
    return _sha256(path) == meta["sha256"]


def _download(name: str, meta: dict, dest: Path) -> bool:
    url = f"{_BASE}/{name}"
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"  تنزيل {name} ({meta['size'] / 1048576:.1f} م.ب) ...", flush=True)
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "MarketImageStudio/2.9.5"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            done = 0
            step = max(meta["size"] // 10, 1)
            nxt = step
            with open(tmp, "wb") as fh:
                while True:
                    block = resp.read(1 << 18)
                    if not block:
                        break
                    fh.write(block)
                    done += len(block)
                    if done >= nxt:
                        print(f"    {done * 100 // meta['size']}%", flush=True)
                        nxt += step
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        print(f"  ✗ فشل التنزيل: {exc}")
        tmp.unlink(missing_ok=True)
        return False

    # التحقق قبل النقل الذرّي: لا نضع ملفًا مشبوهًا في مكانه النهائي.
    if tmp.stat().st_size != meta["size"]:
        print(f"  ✗ حجم غير متوقع: {tmp.stat().st_size} بدل {meta['size']}")
        tmp.unlink(missing_ok=True)
        return False
    got = _sha256(tmp)
    if got != meta["sha256"]:
        print("  ✗ البصمة لا تطابق — الملف غير موثوق، حُذف.")
        print(f"    المتوقع: {meta['sha256']}")
        print(f"    الفعلي : {got}")
        tmp.unlink(missing_ok=True)
        return False

    tmp.replace(dest)
    print(f"  ✓ {name} — البصمة مطابقة")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="تنزيل نماذج القص والتحقق منها")
    ap.add_argument("--all", action="store_true",
                    help="يضيف u2net الاختياري (176م.ب)")
    args = ap.parse_args()

    DEST.mkdir(parents=True, exist_ok=True)
    wanted = {n: m for n, m in MODELS.items() if m["required"] or args.all}

    print(f"مجلد النماذج: {DEST}")
    failed: list[str] = []
    for name, meta in wanted.items():
        path = DEST / name
        if _ok(path, meta):
            print(f"  ✓ {name} — موجود وسليم ({meta['why']})")
            continue
        if path.exists():
            print(f"  ! {name} موجود لكن غير مطابق — سيُستبدل")
        if not _download(name, meta, path):
            failed.append(name)

    if failed:
        print("\n✗ تعذّر تجهيز: " + ", ".join(failed))
        print("  تحقّق من الاتصال، أو انسخ النماذج يدويًا إلى")
        print(f"  {DEST}")
        return 1
    print("\n✓ كل النماذج المطلوبة جاهزة ومُتحقَّق منها")
    return 0


if __name__ == "__main__":
    sys.exit(main())
