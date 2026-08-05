# -*- coding: utf-8 -*-
"""delivery_zip_fast — كتابة حزمة التسليم بلا تجميد وبلا ضغط عديم الجدوى.

المشكلة المقيسة (2.9.12)
------------------------
``pipeline._write_delivery_zip`` يفتح الأرشيف بالوضع ``'w'`` ثم يمرّ
على **كل** عناصر النتيجة ويكتبها بـ``ZIP_DEFLATED`` مستوى 6. أي أن
حفظ صورة واحدة يعيد ضغط المجلد كله. ويُستدعى متزامنًا من خيط
الواجهة، فتتجمّد النافذة حتى ينتهي.

في مجلد فيه 500 صورة يعني هذا إعادة ضغط 500 صورة عند كل حفظ — وهو
ما وصفه المالك: «هناك بطء عند الحفظ والتعديل على الصور».

الإصلاح: ثلاث طبقات
-------------------
1. **تأجيل (debounce)**: الطلبات المتتابعة تُجمع في كتابة واحدة.
2. **خيط خلفي**: الواجهة لا تنتظر الكتابة إطلاقًا.
3. **بلا ضغط للصور**: WebP مضغوط سلفًا، فـ``ZIP_STORED`` أسرع بمراحل
   ولا يكاد يزيد الحجم. التقارير النصية تبقى مضغوطة لأنها تنضغط جيدًا.

ما لم نغيّره عمدًا
------------------
- الكتابة ذرّية كما في الأصل (ملف ``.tmp`` ثم ``os.replace``)، فلا
  تُترك حزمة مبتورة إن انقطع التطبيق.
- بنية الأرشيف نفسها: ``processed/`` للصور و``reports/`` للتقارير.
  أي تغيير فيها يكسر توقّع المالك لشكل التسليم.
"""
from __future__ import annotations

import os
import sys
import threading
import zipfile
from pathlib import Path
from typing import Any, Callable

__all__ = [
    "write_delivery_zip",
    "DeliveryZipScheduler",
]


def _log(message: str) -> None:
    try:
        print(f"[delivery_zip] {message}", file=sys.stderr, flush=True)
    except Exception:                                   # noqa: BLE001
        pass


def _resolve(raw: Any, workspace: Path | None) -> Path | None:
    """يحوّل قيمة مسار (قد تكون نسبية لمساحة العمل) إلى مسار ملف قائم."""
    text = str(raw or "").strip()
    if not text:
        return None
    path = Path(text)
    if not path.is_absolute() and workspace is not None:
        candidate = workspace / path
        if candidate.is_file():
            return candidate
    return path if path.is_file() else None


def write_delivery_zip(result: Any, workspace: Path | None = None) -> bool:
    """يكتب حزمة التسليم كتابةً ذرّية سريعة. يعيد نجاح العملية.

    لا يرفع استثناءً: فشل كتابة الحزمة لا يجوز أن يُسقط التطبيق ولا
    أن يُفقد المالك عمله؛ الصور نفسها محفوظة على القرص أصلًا.
    """
    try:
        zip_raw = getattr(result, "delivery_zip", "") or ""
        if not zip_raw:
            return False
        zip_path = Path(str(zip_raw))
        if not zip_path.is_absolute() and workspace is not None:
            zip_path = workspace / zip_path
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = zip_path.with_suffix(zip_path.suffix + ".tmp")

        added: set[str] = set()
        with zipfile.ZipFile(temporary, "w") as archive:
            for item in getattr(result, "items", []) or []:
                output = _resolve(getattr(item, "output_path", ""), workspace)
                if output is None:
                    continue
                key = os.path.normcase(os.path.normpath(str(output)))
                if key in added:
                    continue
                added.add(key)
                # بلا ضغط: WebP/JPEG مضغوطة سلفًا فالضغط تكلفة بلا عائد.
                archive.write(output, f"processed/{output.name}",
                              compress_type=zipfile.ZIP_STORED)
            for attr in ("report_json", "report_csv"):
                report = _resolve(getattr(result, attr, ""), workspace)
                if report is None:
                    continue
                # التقارير نصية وتنضغط جيدًا، فيُبقى الضغط لها وحدها.
                archive.write(report, f"reports/{report.name}",
                              compress_type=zipfile.ZIP_DEFLATED,
                              compresslevel=6)
        os.replace(temporary, zip_path)
        return True
    except Exception as exc:                            # noqa: BLE001
        _log(f"تعذرت كتابة حزمة التسليم: {exc}")
        try:
            if temporary.exists():                      # type: ignore[name-defined]
                temporary.unlink()                      # type: ignore[name-defined]
        except Exception:                               # noqa: BLE001
            pass
        return False


class DeliveryZipScheduler:
    """يؤجّل كتابة الحزمة ويُجريها في خيط خلفي واحد.

    السلوك:
    - ``request()`` يسجّل رغبة في التحديث ويعود **فورًا**.
    - الطلبات خلال فترة التأجيل تُدمج في كتابة واحدة.
    - إن وصل طلب أثناء كتابة جارية، تُعاد الكتابة بعدها مرة واحدة
      فقط — فلا يضيع تحديث ولا تتراكم الكتابات.
    - ``flush()`` ينفّذ أي تحديث معلّق فورًا وينتظره (يُستدعى عند
      الإغلاق أو قبل التسليم) فلا تُسلَّم حزمة ناقصة.
    """

    def __init__(self, delay_seconds: float = 2.0) -> None:
        self._delay = float(delay_seconds)
        self._lock = threading.RLock()
        self._timer: threading.Timer | None = None
        self._pending: Callable[[], Any] | None = None
        self._running = False
        self._rerun = False
        self._done = threading.Event()
        self._done.set()

    def request(self, supplier: Callable[[], Any]) -> None:
        """يطلب تحديثًا مؤجَّلًا. ``supplier`` يعيد ``(result, workspace)``."""
        with self._lock:
            self._pending = supplier
            self._done.clear()
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._delay, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def _fire(self) -> None:
        with self._lock:
            self._timer = None
            if self._running:
                # كتابة جارية: اطلب إعادة واحدة بعدها بدل التوازي.
                self._rerun = True
                return
            supplier = self._pending
            self._pending = None
            if supplier is None:
                self._done.set()
                return
            self._running = True
        threading.Thread(target=self._run, args=(supplier,),
                         daemon=True).start()

    def _run(self, supplier: Callable[[], Any]) -> None:
        try:
            payload = supplier()
            if payload:
                result, workspace = payload
                if result is not None:
                    write_delivery_zip(result, workspace)
        except Exception as exc:                        # noqa: BLE001
            _log(f"فشل تحديث الحزمة بالخلفية: {exc}")
        finally:
            with self._lock:
                self._running = False
                again = self._rerun and self._pending is not None
                self._rerun = False
                if again:
                    self._timer = threading.Timer(0.1, self._fire)
                    self._timer.daemon = True
                    self._timer.start()
                else:
                    self._done.set()

    def flush(self, timeout: float = 30.0) -> None:
        """ينفّذ أي تحديث معلّق فورًا وينتظر انتهاءه."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            has_pending = self._pending is not None
        if has_pending:
            self._fire()
        self._done.wait(timeout)
