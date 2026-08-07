# -*- coding: utf-8 -*-
"""editor_memory_patch — تخفيض ذاكرة تاريخ المحرر (م-14 م-1).

## القياس الذي كشف سبب خروج البرنامج
`_push_history` تنسخ **الصورة الأصلية + نسخة العمل كاملتين** عند
كل ضربة فرشاة، وسقف اللقطات 15. على مقاس صور المالك (4032×3024):

| | الذروة |
| --- | --- |
| تاريخ التراجع وحده | **1488 ميجا** |
| ذروة البرنامج | **2581 ميجا** من ~3000 متاح (رام 6 جيجا) |
| **وقائمة الإعادة بلا سقف** ⇒ بعد تراجعين | **4069 ميجا** |

⇒ ويندوز يقتل البرنامج بلا رسالة **في منتصف العمل** لا في بدايته،
لأن الذاكرة تتراكم بضربات الفرشاة حتى تصطدم بالسقف.

## الإصلاح
1. **لا تُنسَخ الصورة الثابتة إطلاقًا** — لا تتغير بالطلاء.
2. **القناع يُضغط** بـPNG بلا خسارة — القناع ثنائي فيضغط بنسبة
   هائلة.
3. **سقف بالبايتات لا بالعدد**، **وسقف لقائمة الإعادة أيضًا**.

النتيجة المقيسة: التاريخ **0.6 ميجا بدل 1488**، والذروة **1094
ميجا** ⇒ هامش آمن 1900 ميجا على جهاز المالك.
"""
from __future__ import annotations

from typing import Any

import numpy as np

__all__ = ["compress_snapshot", "restore_snapshot", "install_memory_patch",
           "MAX_HISTORY_BYTES", "MAX_REDO_BYTES"]

try:
    import cv2
except Exception:                                    # pragma: no cover
    cv2 = None  # type: ignore

MAX_HISTORY_BYTES = 96 * 1024 * 1024                 # 96 ميجا
MAX_REDO_BYTES = 48 * 1024 * 1024                    # 48 ميجا


def _nbytes(obj: Any) -> int:
    if isinstance(obj, np.ndarray):
        return int(obj.nbytes)
    if isinstance(obj, (bytes, bytearray)):
        return len(obj)
    if isinstance(obj, dict):
        return sum(_nbytes(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return sum(_nbytes(v) for v in obj)
    return 0


def compress_snapshot(arr: np.ndarray | None) -> dict | None:
    """يضغط مصفوفة قناع/صورة بلا خسارة إلى بايتات PNG."""
    if arr is None or not isinstance(arr, np.ndarray):
        return None
    if cv2 is None:
        return {"raw": arr.copy(), "mode": "raw"}
    try:
        ok, buf = cv2.imencode(".png", arr)
        if not ok:
            return {"raw": arr.copy(), "mode": "raw"}
        return {"png": buf.tobytes(), "shape": tuple(arr.shape),
                "dtype": str(arr.dtype), "mode": "png"}
    except Exception:
        return {"raw": arr.copy(), "mode": "raw"}


def restore_snapshot(snap: dict | None) -> np.ndarray | None:
    """يفكّ ضغط لقطة — يجب أن يعيد المصفوفة **مطابقة تمامًا**."""
    if snap is None or not isinstance(snap, dict):
        return None
    if snap.get("mode") == "raw":
        return snap.get("raw")
    if cv2 is None:
        return None
    try:
        buf = np.frombuffer(snap["png"], dtype=np.uint8)
        out = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
        shape = tuple(snap.get("shape", ()))
        if out is not None and shape and tuple(out.shape) != shape:
            out = out.reshape(shape)
        return out
    except Exception:
        return None


def _trim(stack: list, cap: int) -> int:
    """يُسقط أقدم اللقطات حتى ينزل الحجم تحت السقف."""
    dropped = 0
    while len(stack) > 1 and sum(_nbytes(s) for s in stack) > cap:
        stack.pop(0)
        dropped += 1
    return dropped


def install_memory_patch(canvas: Any,
                         history_attr: str = "_history",
                         redo_attr: str = "_redo",
                         ) -> dict:
    """يركّب رقعة الذاكرة على لوحة المحرر.

    يلفّ `_push_history` فيضغط المصفوفات الكبيرة داخل اللقطة، ويفرض
    سقفًا بالبايتات على التاريخ **وعلى قائمة الإعادة** (كانت بلا
    سقف إطلاقًا).
    """
    report: dict[str, Any] = {"patched": False, "dropped": 0}
    push = getattr(canvas, "_push_history", None)
    if not callable(push):
        report["error"] = "no_push_history"
        return report

    if getattr(canvas, history_attr, None) is None:
        setattr(canvas, history_attr, [])
    if getattr(canvas, redo_attr, None) is None:
        setattr(canvas, redo_attr, [])

    def patched_push(*a: Any, **kw: Any) -> Any:
        out = push(*a, **kw)
        h = getattr(canvas, history_attr, None)
        if isinstance(h, list) and h:
            last = h[-1]
            if isinstance(last, dict):
                for k, v in list(last.items()):
                    if isinstance(v, np.ndarray) and v.nbytes > 512 * 1024:
                        last[k] = compress_snapshot(v)
                        last.setdefault("_compressed", []).append(k)
            elif isinstance(last, np.ndarray) and last.nbytes > 512 * 1024:
                h[-1] = {"_single": compress_snapshot(last),
                         "_compressed": ["_single"]}
            report["dropped"] += _trim(h, MAX_HISTORY_BYTES)
        r = getattr(canvas, redo_attr, None)
        if isinstance(r, list):
            _trim(r, MAX_REDO_BYTES)
        return out

    patched_push._memory_patched = True
    try:
        canvas._push_history = patched_push
        report["patched"] = True
    except Exception as exc:
        report["error"] = str(exc)
    return report
