# -*- coding: utf-8 -*-
"""اختبار BatchRefiner: الضبط الجماعي، التسمية من الإكسل، الاستئناف، التوازي.

كل الأصول تُولَّد محليًا داخل مجلد مؤقت — لا اعتماد على أي مسار خارج المستودع.
يُتخطى جزء المعالجة الفعلية بأمان إن لم تتوفر نماذج ONNX (تُنزَّل في خط البناء).
"""
import shutil
import sys
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np
import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine_v2.batch_refine_v2 import BatchRefiner, RefineOptions

PASS, FAIL = [], []


def check(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name +
          (f" — {note}" if note else ""))


ITEMS = [
    ("10012345", "6281000000012", "بادك زيت زيتون 1لتر", "حبه"),
    ("10014649", "6281000000029", "شامبو صن سلك 400مل", "حبه"),
    ("10021777", "6281000000036", "ارز بشاور 5كيلو", "كيس"),
    ("10033001", "6281000000043", "معلبات فول مدمس", "كرتون"),
]

D = Path(tempfile.mkdtemp(prefix="mis_batch_"))
try:
    src_dir = D / "المصدر"
    out_dir = D / "الناتج"
    src_dir.mkdir(parents=True)

    xlsx = D / "أصناف.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["رقم الصنف", "الباركود", "اسم الصنف", "الوحدة"])
    for it in ITEMS:
        ws.append(list(it))
    wb.save(xlsx)

    # صور مصدر بأسماء قديمة تحمل رقم الصنف
    rng = np.random.default_rng(11)
    made = []
    for gi, (code, bc, _name, unit) in enumerate(ITEMS):
        for seq in (1, 2):
            img = np.full((760, 820, 3), 242, np.uint8)
            c = tuple(int(v) for v in rng.integers(30, 200, 3))
            cv2.rectangle(img, (250, 150), (570, 620), c, -1)
            cv2.rectangle(img, (290, 260), (530, 420), (250, 250, 250), -1)
            stem = f"{code}_{unit}" if seq == 1 else f"{code}_{unit}_{seq}"
            p = src_dir / f"{stem}.jpg"
            cv2.imwrite(str(p), img)
            made.append(p)
    check("source_prepared", len(made) == 8, f"{len(made)} صورة")

    listed = BatchRefiner.list_images(src_dir)
    check("list_images", len(listed) == 8, f"{len(listed)}")

    # سرد يستثني مجلد الناتج (منع إعادة معالجة المخرجات)
    out_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_dir / "سابق.webp"), np.full((10, 10, 3), 255, np.uint8))
    listed2 = BatchRefiner.list_images(src_dir, exclude_dir=out_dir)
    check("excludes_out_dir", len(listed2) == 8, f"{len(listed2)}")

    opts = RefineOptions(recut=True, enhance=True, frame=True,
                         width=800, height=700, fix_names=True,
                         excel_path=str(xlsx), naming_scheme="dash",
                         naming_enabled=True, webp_quality=101,
                         out_format="webp", workers=2)
    check("opts_lossless_default", opts.webp_quality == 101 and not opts.compress)

    model_ok = False
    md = ""
    try:
        from engine_v2.paths_v2 import models_dir
        md = models_dir()
        model_ok = bool(md) and any(Path(md).glob("*.onnx"))
    except Exception:
        model_ok = False

    if not model_ok:
        print("  SKIP batch_run — لا نماذج ONNX في هذه البيئة "
              "(تُنزَّل في خط البناء)")
    else:
        ref = BatchRefiner(md, opts)
        seen = []
        t0 = time.time()
        results = ref.run(src_dir, out_dir,
                          progress=lambda i, t, r: seen.append(i),
                          resume=False)
        elapsed = time.time() - t0

        done = [r for r in results if r.status == "done"]
        errs = [r for r in results if r.status == "error"]
        check("batch_all_processed", len(results) == 8, f"{len(results)}")
        check("batch_no_errors", not errs,
              str([r.error for r in errs][:2]))
        check("batch_done_count", len(done) == 8, f"{len(done)}/8")
        check("progress_called", len(seen) == 8, f"{len(seen)}")

        outs = sorted(p.name for p in out_dir.glob("*.webp")
                      if p.name != "سابق.webp")
        check("outputs_written", len(outs) == 8, f"{len(outs)}")

        # التسمية من الإكسل بنمط dash: الأولى بلا لاحقة ثم -2
        check("naming_primary", "10012345_حبه.webp" in outs,
              str([o for o in outs if o.startswith("10012345")]))
        # نمط dash: الرئيسية بلا رقم، والإضافية تبدأ من -1
        check("naming_dash_seq", "10012345_حبه-1.webp" in outs,
              str([o for o in outs if o.startswith("10012345")]))
        check("unit_literal_kees",
              any(o.startswith("10021777_كيس") for o in outs),
              str([o for o in outs if o.startswith("10021777")]))
        check("unit_literal_karton",
              any(o.startswith("10033001_كرتون") for o in outs),
              str([o for o in outs if o.startswith("10033001")]))

        first = out_dir / "10012345_حبه.webp"
        img = cv2.imdecode(np.fromfile(str(first), np.uint8), cv2.IMREAD_COLOR)
        check("output_exact_size",
              img is not None and img.shape[0] == 700 and img.shape[1] == 800,
              str(None if img is None else img.shape))
        check("output_white_bg",
              img is not None and int(img[0:8, 0:8].min()) >= 245,
              str(None if img is None else int(img[0:8, 0:8].min())))

        # نقطة التفتيش والاستئناف
        cp = BatchRefiner.load_checkpoint(out_dir)
        check("checkpoint_saved", isinstance(cp, dict) and len(cp) >= 8,
              f"{len(cp) if isinstance(cp, dict) else 'لا'}")

        t1 = time.time()
        results2 = ref.run(src_dir, out_dir, resume=True)
        elapsed2 = time.time() - t1
        skipped = [r for r in results2 if r.status == "skipped"]
        check("resume_skips_all", len(skipped) == len(results2),
              f"{len(skipped)}/{len(results2)}")
        check("resume_is_faster", elapsed2 < max(elapsed * 0.6, 0.5),
              f"أول={elapsed:.1f}s استئناف={elapsed2:.2f}s")

        ref.stop()
        check("stop_flag", ref.stopped)
finally:
    shutil.rmtree(D, ignore_errors=True)

print(f"\n===== {len(PASS)} passed / {len(FAIL)} failed =====")
if FAIL:
    print("FAILED:", FAIL)
sys.exit(0 if not FAIL else 1)
