# -*- coding: utf-8 -*-
"""اختبار توازي تمريرة الجودة اللاحقة (2.9.6 — تسريع الدفعة).

يتحقق من:
1. `_quality_pass_workers` تعطي عددًا معقولًا ومحكومًا بالبيئة.
2. التمريرة تعالج **كل** الصور بلا تكرار ولا نقصان.
3. التوازي فعليًا أسرع من التسلسل على عبء محاكى.
4. فشل صورة واحدة لا يوقف بقية الدفعة.
5. المسار التسلسلي (عامل واحد) يبقى صحيحًا.
"""
import os
import sys
import time
import types
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MIS_SKIP_LICENSE", "1")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, os.path.join(_ROOT, "windows_app"))

import native_app  # noqa: E402


class _FakeItem:
    def __init__(self, path):
        self.output_path = path


class _FakeResult:
    def __init__(self, paths):
        self.items = [_FakeItem(p) for p in paths]


def _make_worker(blur=True, polish=True):
    """ينشئ BatchWorker دون تشغيل QThread فعلي."""
    w = native_app.BatchWorker.__new__(native_app.BatchWorker)
    w.blur_dates = blur
    w.text_polish = polish
    emitted = []
    w.progress_changed = types.SimpleNamespace(
        emit=lambda *a: emitted.append(a))
    w._emitted = emitted
    return w


def _install_fake_polish(monkey_delay=0.05, fail_on=()):
    """يزرع polish_output_file وهميًا داخل engine_v2.quality_v2."""
    from engine_v2 import quality_v2
    calls = []
    lock = threading.Lock()
    peak = {"now": 0, "max": 0}

    def fake(path, quality=101, blur_dates=True):
        with lock:
            peak["now"] += 1
            peak["max"] = max(peak["max"], peak["now"])
            calls.append(path)
        try:
            if os.path.basename(path) in fail_on:
                raise RuntimeError("صورة تالفة متعمدة")
            time.sleep(monkey_delay)
        finally:
            with lock:
                peak["now"] -= 1

    original = quality_v2.polish_output_file
    quality_v2.polish_output_file = fake
    return calls, peak, (lambda: setattr(
        quality_v2, "polish_output_file", original))


def _touch(tmpdir, n):
    paths = []
    for i in range(n):
        p = os.path.join(tmpdir, f"out_{i:03d}.jpg")
        with open(p, "wb") as fh:
            fh.write(b"\xff\xd8\xff\xd9")
        paths.append(p)
    return paths


def _real_workload_speedup(check):
    """يقيس التسريع على صور حقيقية ويتحقق من عدم التدهور.

    الشرط الحاسم ليس «أسرع كثيرًا» بل «لا يتدهور أبدًا»، لأن
    التدهور (×0.06) هو الخطر الذي وقع فعليًا في المحاولة الأولى
    حين كان عدد العمال يُحسب من النوى وحدها بلا وعي بالذاكرة.
    """
    import shutil
    import tempfile
    try:
        import cv2
        sys.path.insert(0, os.path.join(_ROOT, "tests"))
        from test_quality_date_v21 import make_product_image
    except Exception as exc:
        check("[4] قياس العبء الحقيقي (تخطٍ)", True, f"غير متاح: {exc}")
        return 0.0

    n = int(os.environ.get("MIS_PARALLEL_BENCH_N", "8"))
    img = make_product_image()
    td = tempfile.mkdtemp()
    try:
        paths = [os.path.join(td, f"real_{i}.jpg") for i in range(n)]

        def reset():
            for p in paths:
                cv2.imwrite(p, img)

        reset()
        os.environ["MIS_QUALITY_WORKERS"] = "1"
        w = _make_worker()
        t0 = time.perf_counter()
        w._quality_post_pass(_FakeResult(paths))
        seq = time.perf_counter() - t0
        os.environ.pop("MIS_QUALITY_WORKERS", None)

        reset()
        w = _make_worker()
        t0 = time.perf_counter()
        w._quality_post_pass(_FakeResult(paths))
        par = time.perf_counter() - t0
    finally:
        os.environ.pop("MIS_QUALITY_WORKERS", None)
        shutil.rmtree(td, ignore_errors=True)

    speedup = seq / par if par else 0.0
    workers = native_app._quality_pass_workers(n)
    detail = (f"تسلسلي={seq:.1f}s متوازٍ={par:.1f}s "
              f"×{speedup:.2f} (workers={workers}, n={n})")
    check("[4] التوازي لا يتدهور على عبء حقيقي", speedup >= 0.95, detail)
    if workers > 1:
        check("[4أ] التوازي يحقق مكسبًا فعليًا", speedup >= 1.3, detail)
    return speedup


def main():
    import tempfile
    results = []

    def check(name, ok, detail=""):
        results.append(ok)
        print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail else ""))

    # [1] حساب عدد العمال — مسقوف وواعٍ بالذاكرة
    n = native_app._quality_pass_workers(100)
    cpu = os.cpu_count() or 1
    check("[1] عدد العمال مسقوف بـ 4 ولا يتجاوز نصف النوى",
          1 <= n <= 4 and (cpu <= 2 or n <= max(1, cpu // 2)),
          f"workers={n} cpu={cpu} mem={native_app._available_memory_gb():.1f}GB")

    check("[1هـ] قياس الذاكرة يعمل في هذه البيئة",
          native_app._available_memory_gb() > 0,
          f"{native_app._available_memory_gb():.2f} GB")

    # ذاكرة شحيحة ⇒ يجب أن يتراجع إلى مسار واحد
    _orig_mem = native_app._available_memory_gb
    try:
        native_app._available_memory_gb = lambda: 1.2
        check("[1و] ذاكرة شحيحة تفرض التسلسل",
              native_app._quality_pass_workers(100) == 1)
        native_app._available_memory_gb = lambda: 32.0
        big = native_app._quality_pass_workers(100)
        check("[1ز] جهاز قوي يستفيد لكن لا يتجاوز السقف",
              2 <= big <= 4 if cpu >= 4 else big >= 1, f"workers={big}")
        native_app._available_memory_gb = lambda: 0.0
        check("[1ح] فشل قياس الذاكرة يُبقي السلوك محافظًا",
              1 <= native_app._quality_pass_workers(100) <= 2)
    finally:
        native_app._available_memory_gb = _orig_mem

    os.environ["MIS_QUALITY_WORKERS"] = "1"
    check("[1ب] متغير البيئة يفرض التسلسل",
          native_app._quality_pass_workers(50) == 1)
    os.environ["MIS_QUALITY_WORKERS"] = "3"
    check("[1ج] متغير البيئة يفرض عددًا محددًا",
          native_app._quality_pass_workers(50) == 3)
    os.environ.pop("MIS_QUALITY_WORKERS", None)

    check("[1د] صورة واحدة لا تُوازى",
          native_app._quality_pass_workers(1) == 1)

    with tempfile.TemporaryDirectory() as td:
        paths = _touch(td, 24)

        # [2] التغطية الكاملة بلا تكرار
        calls, peak, restore = _install_fake_polish(0.02)
        try:
            w = _make_worker()
            w._quality_post_pass(_FakeResult(paths))
        finally:
            restore()
        check("[2] كل الصور عولجت بلا تكرار",
              sorted(calls) == sorted(paths) and len(calls) == len(set(calls)),
              f"{len(calls)}/{len(paths)}")

        # [3] التوازي حقيقي (تداخل فعلي)
        #
        # لا يقاس التداخل إلا إن قرّر المنتج أصلًا أن يوازي. ودالة
        # `_quality_pass_workers` واعية بالذاكرة بقصد، فتتراجع إلى مسار
        # واحد حين تقل المتاحة عن ~1.75 جيجا — وهو سلوك مطلوب تحميه
        # التحققات [1و] و[1ح] نفسها. فكان هذا التحقق يشترط التداخل دون
        # مراعاة ذلك، فيعلن فشلًا على أي آلة مزدحمة الذاكرة والمنتج
        # يعمل كما صُمّم تمامًا. وهذا فشل كاذب يُفقد الظن بالحزمة
        # كلها: من رأى حاجزًا أحمر بلا علة لم يعد يثق بالأحمر حين يصدق.
        # فنُقيّد الشرط بقرار المنتج نفسه، وإن قرر التسلسل نفرض
        # التوازي قسرًا عبر `MIS_QUALITY_WORKERS` لنختبر التداخل فعلًا
        # بدل أن نتخطّى النقطة — فلا تُفلت علة توازٍ حقيقية بحجة البيئة.
        planned = native_app._quality_pass_workers(len(paths))
        if planned > 1:
            check("[3] المسارات تعمل متوازية فعلًا", peak["max"] > 1,
                  f"ذروة التزامن={peak['max']} (مخطط={planned})")
        else:
            os.environ["MIS_QUALITY_WORKERS"] = "3"
            calls2, peak2, restore2 = _install_fake_polish(0.02)
            try:
                _make_worker()._quality_post_pass(_FakeResult(paths))
            finally:
                restore2()
                os.environ.pop("MIS_QUALITY_WORKERS", None)
            check("[3] المسارات تعمل متوازية فعلًا (توازٍ مفروض)",
                  peak2["max"] > 1 and len(calls2) == len(paths),
                  f"ذروة التزامن={peak2['max']} — الآلة اختارت التسلسل "
                  f"(متاح {native_app._available_memory_gb():.1f}GB)")

        # [4] التوازي أسرع على **عبء حقيقي** لا على sleep
        # (درس مهم: القياس بـsleep أظهر تسريعًا خياليًا ×4.7 بينما
        # العبء الحقيقي كان يتدهور ×15 بسبب اكتظاظ النوى والذاكرة)
        speedup = _real_workload_speedup(check)

        # [4ب] ميزانية خيوط OpenCV تُعاد بعد الخروج
        try:
            import cv2
            before = cv2.getNumThreads()
            with native_app._OpenCVThreadBudget(3):
                inside = cv2.getNumThreads()
            after = cv2.getNumThreads()
            check("[4ب] ميزانية خيوط OpenCV تُقيّد ثم تُعاد",
                  inside <= max(1, before) and after == before,
                  f"قبل={before} داخل={inside} بعد={after}")
        except Exception as exc:
            check("[4ب] ميزانية خيوط OpenCV", False, str(exc))

        # [5] صورة تالفة لا توقف الدفعة
        bad = os.path.basename(paths[5])
        calls3, _, restore3 = _install_fake_polish(0.01, fail_on=(bad,))
        try:
            w = _make_worker()
            w._quality_post_pass(_FakeResult(paths))
        finally:
            restore3()
        check("[5] فشل صورة لا يوقف الباقي", len(calls3) == len(paths),
              f"{len(calls3)}/{len(paths)}")

        # [6] المسار التسلسلي صحيح أيضًا
        calls4, _, restore4 = _install_fake_polish(0.001)
        try:
            os.environ["MIS_QUALITY_WORKERS"] = "1"
            w = _make_worker()
            w._quality_post_pass(_FakeResult(paths))
        finally:
            os.environ.pop("MIS_QUALITY_WORKERS", None)
            restore4()
        check("[6] المسار التسلسلي يغطي كل الصور",
              sorted(calls4) == sorted(paths))

        # [7] التقدم يصل للنهاية
        w = _make_worker()
        calls5, _, restore5 = _install_fake_polish(0.001)
        try:
            w._quality_post_pass(_FakeResult(paths))
        finally:
            restore5()
        last = w._emitted[-1] if w._emitted else None
        check("[7] آخر تقدّم يعلن اكتمال كل الصور",
              bool(last) and f"{len(paths)}/{len(paths)}" in last[2],
              str(last))

        # [8] إيقاف الخيارين يتخطى التمريرة كليًا
        calls6, _, restore6 = _install_fake_polish(0.001)
        try:
            w = _make_worker(blur=False, polish=False)
            w._quality_post_pass(_FakeResult(paths))
        finally:
            restore6()
        check("[8] تعطيل الخيارين يتخطى التمريرة", calls6 == [])

    print()
    ok = all(results)
    print(("ALL PASS " if ok else "SOME FAILED ")
          + f"({sum(results)}/{len(results)})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
