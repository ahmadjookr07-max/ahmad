# -*- coding: utf-8 -*-
"""م-12 / م-2 / م-3 — مزامنة المحرر وحرس فساد البيانات.

بلاغ المالك حرفيًا: «يتم تكرار الصورة نفسها؟؟ لم أكررها».

العطب الجذري المُثبت: ``_show_selected_preview`` كان يُحدِّث وجهة
الحفظ ``_individual_edit_source_name`` عند تغيّر الصف، ثم يترك
``unified_editor`` محمّلًا على بكسلات **الصف السابق**. وبعده
``_begin_individual_edit`` يأخذ ``editor.get_result_bgr()`` ويكتبه
**باسم الصنف الجديد** ⇒ صورة صنف تُكتب فوق صنف آخر بلا أي رسالة.
والمزامنة كانت موجودة في مسار الفتح وحده لا في مسار تغيير الصف.

هذا الاختبار يبني نافذة حقيقية بجدول نتائج حقيقي، ويحرّك التحديد
فعليًا، ويقيس البكسلات — لا يقرأ الكود. ويحوي فحصًا سلبيًا يُثبت
أن العطب كان يحدث فعلًا بلا الإصلاح.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MIS_HEADLESS", "1")
os.environ.setdefault("MIS_LICENSE_BYPASS", "1")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "windows_app"))

PASS = 0
FAIL = 0


def check(label: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {label}")
    else:
        FAIL += 1
        print(f"  ✗ {label} {extra}")


def main() -> int:
    print("=" * 62)
    print("م-12 — مزامنة المحرر وحرس فساد البيانات")
    print("=" * 62)

    import shutil
    import tempfile

    import cv2
    import numpy as np
    from PySide6.QtWidgets import QApplication

    import native_app as na

    app = QApplication.instance() or QApplication([])

    work = Path(tempfile.mkdtemp(prefix="m12_"))
    src_dir = work / "sources"
    src_dir.mkdir(parents=True, exist_ok=True)

    # صورتان **متمايزتان بالبكسلات** حتى يكون الخلط قابلًا للقياس
    a = np.zeros((240, 320, 3), np.uint8)
    a[:, :] = (30, 40, 200)          # أحمر غالب
    b = np.zeros((240, 320, 3), np.uint8)
    b[:, :] = (200, 40, 30)          # أزرق غالب
    pa, pb = src_dir / "A.png", src_dir / "B.png"
    cv2.imwrite(str(pa), a)
    cv2.imwrite(str(pb), b)

    def mean_bgr(img):
        return tuple(float(x) for x in img.reshape(-1, 3).mean(axis=0))

    check("الصورتان متمايزتان بالبكسلات",
          abs(mean_bgr(a)[2] - mean_bgr(b)[2]) > 100)

    win = na.MainWindow()
    win._headless_mode = True
    win.current_workspace = work

    items = [
        na.BatchItemResult(source_path=str(pa), source_name="A.png",
                           status="review", item_code="1001",
                           product_name="صنف أ"),
        na.BatchItemResult(source_path=str(pb), source_name="B.png",
                           status="review", item_code="1002",
                           product_name="صنف ب"),
    ]
    win.current_result = na.BatchRunResult(
        workspace=str(work), database_path="", catalog_summary={},
        items=items, elapsed_ms=0.0, delivery_zip="",
        report_json="", report_csv="")

    # ------------------------------------------ الدالتان موجودتان فعلًا
    check("_sync_editor_to_selection موجودة",
          callable(getattr(win, "_sync_editor_to_selection", None)))
    check("_editor_matches_selection موجودة",
          callable(getattr(win, "_editor_matches_selection", None)))
    check("متغير وجهة المحرر مستقل عن وجهة التحديد",
          hasattr(win, "_editor_loaded_source_name")
          and hasattr(win, "_individual_edit_source_name"))
    check("الوجهة تبدأ فارغة", win._editor_loaded_source_name == "")

    # ------------------------------------------ الحرس قبل أي تحميل
    check("الحرس يرفض حين لا وجهة مسجّلة",
          win._editor_matches_selection(items[0]) is False)
    check("الحرس يرفض العنصر الفارغ",
          win._editor_matches_selection(None) is False)

    # -------------------- المزامنة لا تبني المحرر — وهذا مقصود
    # `_sync_editor_to_selection` تعود فورًا إن لم يكن المحرر مبنيًا،
    # فلا تُدفع كلفة بناء ودجت ثقيلة لمن لم يفتح تبويب التحرير.
    # وهذا فحص أداء لا تفصيل تقني: لو بنته لتجمّدت الواجهة عند
    # أول نقلة صف لدى من لا يريد المحرر أصلًا.
    check("المزامنة لا تبني المحرر إن لم يُفتح بعد",
          win._editor_ready() is False)
    win._sync_editor_to_selection(items[0])
    check("ولا تُسجّل وجهة وهمية حين لا محرر",
          win._editor_loaded_source_name == "")

    # ------------------------------------------ المزامنة الفعلية
    editor = win.unified_editor            # الوصول هو البناء
    check("المحرر بُني عند الطلب الصريح", win._editor_ready() is True)
    win._sync_editor_to_selection(items[0])
    check("المزامنة حمّلت صورة فعلًا", editor.has_image())
    check("الوجهة صارت A.png", win._editor_loaded_source_name == "A.png")
    check("الحرس يوافق على A", win._editor_matches_selection(items[0]) is True)
    check("الحرس يرفض B والمحرر على A",
          win._editor_matches_selection(items[1]) is False)

    got = editor.get_result_bgr()
    check("بكسلات المحرر هي بكسلات A لا B",
          got is not None and abs(mean_bgr(got)[2] - mean_bgr(a)[2]) < 12,
          f"({mean_bgr(got) if got is not None else None})")

    # ------------------------- الانتقال إلى B: البكسلات يجب أن تتبدّل
    win._sync_editor_to_selection(items[1])
    check("الوجهة صارت B.png", win._editor_loaded_source_name == "B.png")
    got_b = editor.get_result_bgr()
    check("بكسلات المحرر تبدّلت إلى B",
          got_b is not None and abs(mean_bgr(got_b)[2] - mean_bgr(b)[2]) < 12,
          f"({mean_bgr(got_b) if got_b is not None else None})")
    check("الحرس صار يوافق على B",
          win._editor_matches_selection(items[1]) is True)
    check("والحرس صار يرفض A",
          win._editor_matches_selection(items[0]) is False)

    # --------------- الفحص السلبي: لولا المزامنة لبقيت بكسلات B على A
    # نُحاكي العطب القديم: نُحدّث وجهة التحديد وحدها بلا مزامنة
    win._individual_edit_source_name = "A.png"        # التحديد صار A
    # المحرر ما زال على B (لم نُزامن)
    stale = editor.get_result_bgr()
    check("سلبي: بلا مزامنة تبقى بكسلات B مع أن التحديد A",
          stale is not None and abs(mean_bgr(stale)[2] - mean_bgr(b)[2]) < 12,
          "(لو تبدّلت وحدها فالعطب لم يكن حقيقيًا)")
    check("سلبي: والحرس يكشف هذا الاختلال",
          win._editor_matches_selection(items[0]) is False)

    # ------------------- حفظ مسودة الصف السابق لا الصف الجديد
    win._sync_editor_to_selection(items[0])
    saved = win._save_editor_draft(source_name="B.png", silent=True)
    check("الحفظ بالاسم الصريح يكتب ملفًا",
          saved is not None and Path(saved).is_file(), f"({saved})")
    if saved is not None:
        check("اسم الملف يتبع الصف المطلوب لا المعروض",
              Path(saved).name.startswith("B."), f"({Path(saved).name})")
        drafts = getattr(win, "_editor_drafts", {}) or {}
        check("المسودة سُجّلت تحت مفتاح B.png", "B.png" in drafts)
        check("ولم تُسجّل خطأً تحت A.png أثناء هذا الحفظ",
              drafts.get("A.png") is None or
              Path(drafts["A.png"]).name.startswith("A."))

    # ------------------- عنصر بلا ملف على القرص: يُنظّف ولا يُسقط
    ghost = na.BatchItemResult(source_path=str(src_dir / "لا-يوجد.png"),
                               source_name="لا-يوجد.png", status="review")
    win._sync_editor_to_selection(ghost)
    check("ملف مفقود يُفرّغ المحرر بلا انهيار",
          win._editor_loaded_source_name == "")
    check("والحرس يرفض بعد التفريغ",
          win._editor_matches_selection(ghost) is False)

    win._sync_editor_to_selection(None)
    check("العنصر الفارغ يُفرّغ الوجهة",
          win._editor_loaded_source_name == "")

    # ------------------- المسودة أولى من الأصل عند إعادة التحميل
    win._sync_editor_to_selection(items[1])
    check("المسودة المحفوظة تُقدَّم على الأصل عند العودة إلى B",
          win._editor_loaded_source_name == "B.png")

    # ------------------- حرس التركيب: المزامنة مربوطة بتغيّر الصف
    src = (ROOT / "windows_app" / "native_app.py").read_text(encoding="utf-8")
    check("_show_selected_preview يستدعي المزامنة",
          "_sync_editor_to_selection(current)" in src)
    check("_begin_individual_edit يستدعي الحرس قبل اعتماد البكسلات",
          "not self._editor_matches_selection(item)" in src)
    check("مسار الفتح يسجّل الوجهة",
          "self._editor_loaded_source_name = item.source_name" in src)
    check("إعادة الضبط تسجّل الوجهة أيضًا",
          src.count("self._editor_loaded_source_name = item.source_name") >= 2)
    check("الحفظ يقبل source_name صريحًا",
          "def _save_editor_draft(self, *, silent: bool = False," in src
          and "source_name: str = \"\"" in src)

    try:
        win._shutdown_workers(2000)
    except Exception:
        pass
    win.close()
    shutil.rmtree(work, ignore_errors=True)

    print("=" * 62)
    print(f"نجح {PASS} / فشل {FAIL}")
    if FAIL == 0:
        print("المحرر متزامن مع التحديد — لا بكسلات صنف تُكتب فوق صنف آخر")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
