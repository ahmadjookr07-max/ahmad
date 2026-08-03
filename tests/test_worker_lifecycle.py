"""اختبار انحدار: دورة حياة الخيوط العاملة (منع SIGABRT).

يثبت أن النمط الذي كان يُغلق التطبيق تلقائيًا أثناء الربط اليدوي
(«QThread: Destroyed while thread is still running» => abort) لم يعد
ممكنًا بعد إضافة `_live_workers` + `_track_worker` + حرّاس isRunning.

يُشغّل في عملية فرعية معزولة: لو عاد الانهيار يظهر كرمز خروج 134.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CHILD = r'''
import gc, sys, time
from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QApplication

app = QApplication([])

class Slow(QThread):
    def run(self):
        time.sleep(1.5)

class Host:
    """يحاكي MainWindow بعد الإصلاح."""
    def __init__(self):
        self._live_workers = set()
        self.worker = None

    def _track_worker(self, worker):
        try:
            workers = self._live_workers
        except AttributeError:
            workers = self._live_workers = set()
        workers.add(worker)

        def _release():
            workers.discard(worker)

        try:
            worker.finished.connect(_release)
        except Exception:
            pass

    def start(self):
        # الحارس: لا نستبدل عاملا يعمل
        if self.worker is not None and self.worker.isRunning():
            return "rejected"
        self.worker = Slow()
        self._track_worker(self.worker)
        self.worker.start()
        return "started"

host = Host()
results = []

# 1) محاولة تشغيل 30 عاملا متتاليا بسرعة (نمط نقر المالك المتكرر)
for _ in range(30):
    results.append(host.start())

assert results[0] == "started", results[0]
assert results.count("rejected") >= 25, results

# 2) نمط الانهيار الأصلي: إسقاط المرجع عمدا وإجبار جمع القمامة
#    قبل الإصلاح كان هذا يقتل العملية فورا.
host.worker = None
gc.collect()
app.processEvents()

# 3) الانتظار حتى ينتهي الخيط ثم التأكد من تحرره من المجموعة
deadline = time.time() + 8
while host._live_workers and time.time() < deadline:
    app.processEvents()
    time.sleep(0.05)

assert not host._live_workers, "الخيط لم يتحرر من _live_workers"

print("CHILD_OK")
'''


def main() -> int:
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = f"{ROOT}:{ROOT / 'src'}:{env.get('PYTHONPATH', '')}"

    proc = subprocess.run(
        [sys.executable, "-c", CHILD],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(ROOT),
    )

    out = (proc.stdout or "") + (proc.stderr or "")
    print(out.strip())

    failures: list[str] = []

    if proc.returncode == -6 or proc.returncode == 134:
        failures.append("انهيار SIGABRT عاد للظهور (رمز 134)")
    elif proc.returncode != 0:
        failures.append(f"رمز خروج غير متوقع: {proc.returncode}")

    if "Destroyed while thread" in out:
        failures.append("تحذير Qt: QThread دُمّر أثناء عمله")

    if "CHILD_OK" not in out:
        failures.append("لم يكتمل سيناريو الاختبار")

    # فحص ثابت: كل بدء عامل في التطبيق مقترن بـ _track_worker
    source = (ROOT / "windows_app" / "native_app.py").read_text(encoding="utf-8")
    for needle in (
        "self._live_workers: set = set()",
        "self._track_worker(self.manual_worker)",
        "self._track_worker(self.batch_worker)",
        "self._track_worker(self.individual_worker)",
        "if self.manual_worker is not None and self.manual_worker.isRunning():",
        "if self.batch_worker is not None and self.batch_worker.isRunning():",
    ):
        if needle not in source:
            failures.append(f"مفقود في native_app.py: {needle}")

    if failures:
        for item in failures:
            print(f"FAIL: {item}")
        return 1

    print("ALL_WORKER_LIFECYCLE_TESTS_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
