# -*- coding: utf-8 -*-
"""اختبار حفظ/استعادة الجلسة وجودة WebP بلا فقدان.

يتحقق أن الجلسة تُستأنف بعد إعادة تشغيل التطبيق بكل حالتها (الموضع الحالي،
حالة كل صورة، قيم التغذية)، وأن ترميز WebP المستخدم بلا فقدان فعلًا.
"""
import shutil
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine_v2.session_v2 import SessionStore

PASS, FAIL = [], []


def check(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name +
          (f" — {note}" if note else ""))


D = Path(tempfile.mkdtemp(prefix="mis_sessions_"))
try:
    store = SessionStore(D)
    s = store.new_session("جلسة اختبار")
    sid = s.session_id
    check("new_session", bool(sid), sid)

    store.upsert_image("a.jpg", source_path="a.jpg", status="matched",
                       barcode="628", item_code="10001043", sequence=1)
    store.upsert_image("b.jpg", source_path="b.jpg", status="done",
                       item_code="10001043", sequence=2,
                       nutrition_mode="rebuild",
                       nutrition_values={"calories": "135"})
    # الموضع قاموس {source_name,row,col} لا رقمًا مفردًا
    store.set_position("b.jpg", 7, 2)
    store.state.mark_approved("b.jpg")
    store.state.setup = {"excel": "list.xlsx", "size": 1000}
    store.state.phase = "results"
    store.save(force=True)

    # محاكاة إعادة تشغيل التطبيق من الصفر
    store2 = SessionStore(D)
    lst = store2.list_sessions()
    check("list_sessions", len(lst) == 1, str(lst))
    # done_count يعدّ matched وdone وapproved كلها مكتملة — فالصورتان معًا
    check("counts", lst and lst[0]["total"] == 2 and lst[0]["done"] == 2,
          str(lst[0] if lst else None))

    s2 = store2.load(sid)
    check("resume_position",
          s2.position.get("source_name") == "b.jpg"
          and s2.position.get("row") == 7 and s2.position.get("col") == 2,
          str(s2.position))
    check("resume_phase", s2.phase == "results", s2.phase)
    check("resume_setup", s2.setup.get("size") == 1000, str(s2.setup))
    check("resume_approved", s2.is_approved("b.jpg")
          and not s2.is_approved("a.jpg"), str(s2.approved))
    # بيانات كل صورة مخزنة قاموسًا (قابلة للتسلسل في JSON مباشرة)
    check("resume_nutrition",
          s2.images["b.jpg"].get("nutrition_values") == {"calories": "135"},
          str(s2.images["b.jpg"].get("nutrition_values")))
    check("resume_nutrition_mode",
          s2.images["b.jpg"].get("nutrition_mode") == "rebuild",
          str(s2.images["b.jpg"].get("nutrition_mode")))
    check("resume_item_code",
          s2.images["a.jpg"].get("item_code") == "10001043",
          str(s2.images["a.jpg"].get("item_code")))
    check("resume_barcode", s2.images["a.jpg"].get("barcode") == "628",
          str(s2.images["a.jpg"].get("barcode")))

    # حذف الجلسة يعمل
    store2.delete(sid)
    check("delete_session", len(SessionStore(D).list_sessions()) == 0)

    # WebP بلا فقدان: ترميز ثم فك يعيد نفس البكسلات تمامًا
    rng = np.random.default_rng(7)
    img = rng.integers(0, 256, (240, 320, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".webp", img, [cv2.IMWRITE_WEBP_QUALITY, 101])
    check("webp_encode", bool(ok), str(len(buf) if ok else 0))
    back = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
    check("webp_lossless", back is not None and np.array_equal(img, back))

    # الترميز بجودة أقل يفقد بيانات فعلًا (يثبت أن 101 هو اللاضاغط)
    ok2, buf2 = cv2.imencode(".webp", img, [cv2.IMWRITE_WEBP_QUALITY, 80])
    lossy = cv2.imdecode(buf2, cv2.IMREAD_UNCHANGED)
    check("webp_lossy_differs", ok2 and not np.array_equal(img, lossy))
finally:
    shutil.rmtree(D, ignore_errors=True)

print(f"\n===== {len(PASS)} passed / {len(FAIL)} failed =====")
if FAIL:
    print("FAILED:", FAIL)
sys.exit(0 if not FAIL else 1)
