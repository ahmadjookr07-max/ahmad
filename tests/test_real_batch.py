# -*- coding: utf-8 -*-
"""دفعة جديدة حقيقية على بيانات المالك + تجريب الأزرار المُفعَّلة.

هذا هو السياق الذي يكشف A2 («خلل عند رفع الصور») ويُفعِّل أزرار
التشغيل والربط والحفظ التي كانت معطّلة في الاختبار السابق.

المدخلات الحقيقية:
  - إكسل المالك: /home/ubuntu/owner_data/اصنافعالمعنترة.xlsx (50311 سجل)
  - صور خام:     /home/ubuntu/owner_data/زيت/زيت/ (109 صورة، 37 بمسافة)

يقيس كل مرحلة ويرصد أي استثناء أو بطء.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MIS_HEADLESS", "1")
os.environ.setdefault("MIS_LICENSE_BYPASS", "1")

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT / "src", ROOT / "windows_app"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

# حرّاس بيانات المالك — تخطٍّ صريح بدل النجاح/الفشل الزائف.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from owner_data_guard import (  # noqa: E402
    list_images, require_owner_data)

CATALOG, RAW = require_owner_data(need_catalog=True, need_raw=True,
                                  minimum_images=3)
LOG = Path("/home/ubuntu/real_batch.log")

FAILURES: list[str] = []
CHECKS = 0
DIALOGS: list[str] = []


def say(msg: str) -> None:
    print(msg, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(msg + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def check(label: str, cond: bool, detail: str = "",
          ok_detail: str = "") -> bool:
    """تأكيد مقاس.

    ``detail`` توصيف الفشل وحده، و``ok_detail`` توصيف النجاح.
    فصلهما يمنع طباعة تقارير متناقضة من نوع «✓ نجح — مفقود 0».
    """
    global CHECKS
    CHECKS += 1
    if cond:
        _d = ok_detail or detail
        say(f"  ✓ {label}" + (f" — {_d}" if _d else ""))
        return True
    FAILURES.append(f"{label}{(' — ' + detail) if detail else ''}")
    say(f"  ✗ {label}" + (f" — {detail}" if detail else ""))
    return False


def install_traps() -> None:
    from PySide6.QtWidgets import (QDialog, QFileDialog, QInputDialog,
                                   QMessageBox)

    def _exec_trap(self, *a, **k):
        DIALOGS.append(f"dialog:{type(self).__name__}")
        try:
            self.close()
        except Exception:
            pass
        return int(QDialog.DialogCode.Rejected)

    QDialog.exec = _exec_trap
    QDialog.exec_ = _exec_trap

    def trap(kind):
        def _fn(*a, **k):
            txt = ""
            for arg in a:
                if isinstance(arg, str) and len(arg) > len(txt):
                    txt = arg
            DIALOGS.append(f"{kind}: {txt[:250]}")
            return QMessageBox.StandardButton.Ok
        return staticmethod(_fn)

    QMessageBox.information = trap("info")
    QMessageBox.warning = trap("warn")
    QMessageBox.critical = trap("error")
    QMessageBox.question = trap("ask")
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ("", ""))
    QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([], ""))
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
    QInputDialog.getText = staticmethod(lambda *a, **k: ("", False))


def main() -> int:
    LOG.write_text("", "utf-8")
    say("═" * 64)
    say(" دفعة جديدة حقيقية على بيانات المالك")
    say("═" * 64)

    say("\n[0] توفر المدخلات")
    check("إكسل المالك موجود", CATALOG.is_file(), str(CATALOG))
    raw_imgs = list_images(RAW) if RAW.is_dir() else []
    check("صور خام متوفرة", len(raw_imgs) >= 20, f"{len(raw_imgs)} صورة")
    spaced = [p for p in raw_imgs if " " in p.name]
    say(f"    منها {len(spaced)} اسمًا يحتوي مسافة (مرشّح لكسر المطابقة)")
    if not raw_imgs:
        say("لا صور — توقف")
        return 1

    install_traps()
    from PySide6.QtWidgets import QApplication
    import native_app as na
    app = QApplication.instance() or QApplication([])

    work = Path(tempfile.mkdtemp(prefix="real_batch_"))
    # ننسخ عينة معقولة تشمل الأسماء بمسافات
    sample_dir = work / "خام"
    sample_dir.mkdir(parents=True)
    sample = spaced[:8] + [p for p in raw_imgs if " " not in p.name][:8]
    for p in sample:
        shutil.copy2(p, sample_dir / p.name)
    say(f"\n[1] عينة اختبار: {len(sample)} صورة "
        f"({len([p for p in sample if ' ' in p.name])} بمسافة)")

    t0 = time.perf_counter()
    win = na.MainWindow()
    say(f"  زمن إنشاء النافذة: {(time.perf_counter()-t0)*1000:.0f} مث")

    # ── تحميل الإكسل عبر المسار الحقيقي ────────────────────────────
    say("\n[2] تحميل إكسل المالك (50311 سجل)")
    t0 = time.perf_counter()
    try:
        win.catalog_path = CATALOG
        win.catalog_edit.setText(str(CATALOG))
        if hasattr(win, "_on_catalog_chosen"):
            win._on_catalog_chosen(CATALOG)
        app.processEvents()
        ms = (time.perf_counter() - t0) * 1000
        check("قُبل الإكسل بلا استثناء", True, f"{ms:.0f} مث")
        check("زمن تحميل الإكسل مقبول (<15 ث)", ms < 15000, f"{ms:.0f} مث")
    except Exception as exc:
        check("قُبل الإكسل بلا استثناء", False,
              f"{type(exc).__name__}: {exc}")
        say(traceback.format_exc(limit=6))

    # ── رفع الصور (A2) ─────────────────────────────────────────────
    say("\n[3] رفع الصور — نقطة A2")
    t0 = time.perf_counter()
    try:
        paths = list_images(sample_dir)
        win._add_paths([str(p) for p in paths])
        app.processEvents()
        ms = (time.perf_counter() - t0) * 1000
        listed = win.image_list.count()
        check("رُفعت كل الصور بلا فقدان", listed == len(paths),
              f"مرفوع {listed} من {len(paths)}")
        check("زمن الرفع مقبول (<5 ث)", ms < 5000, f"{ms:.0f} مث")
        say(f"    زمن رفع {len(paths)} صورة: {ms:.0f} مث")
        # هل الأسماء بمسافات نجت؟
        # إصلاح قصور قياس: كان الشرط يبحث عن النمط الحرفي
        # " 2.jpg" فاعتمد على مصادفة ترتيب أبجدي لا علاقة لها
        # بصحة التطبيق: إن لم تقع "صورة 2.jpg" في أول العينة
        # أُعلن إخفاق زائف مع أن الرفع سليم. الفكرة المقصودة أن
        # كل اسم فيه مسافة ينجو باسمه الكامل، وهذا ما يُقاس الآن.
        texts = [win.image_list.item(i).text()
                 for i in range(win.image_list.count())]
        spaced_paths = [p for p in paths if " " in p.name]
        missing_spaced = [p.name for p in spaced_paths
                          if not any(p.name in t for t in texts)]
        check("الأسماء التي تحتوي مسافة لم تُهمَل",
              bool(spaced_paths) and not missing_spaced,
              f"مفقود {len(missing_spaced)} من {len(spaced_paths)}: "
              f"{missing_spaced[:3]}" if spaced_paths
              else "لا أسماء بمسافات في العينة",
              ok_detail=f"{len(spaced_paths)} اسمًا بمسافات نجت كلها")
    except Exception as exc:
        check("رُفعت كل الصور بلا فقدان", False,
              f"{type(exc).__name__}: {exc}")
        say(traceback.format_exc(limit=6))

    # ── حالة زر التشغيل ────────────────────────────────────────────
    say("\n[4] جاهزية زر التشغيل بعد الرفع")
    run_btn = getattr(win, "run_button", None)
    check("زر التشغيل موجود", run_btn is not None)
    if run_btn is not None:
        check("زر التشغيل مُفعَّل بعد رفع إكسل وصور",
              run_btn.isEnabled(),
              "معطّل — يمنع بدء المعالجة" if not run_btn.isEnabled()
              else "مُفعَّل")

    # ── الأزرار التي صارت مُفعَّلة الآن ─────────────────────────────
    say("\n[5] ضغط الأزرار التي فُعِّلت بعد التحميل")
    names = ["select_catalog_button", "select_images_button",
             "select_folder_button", "clear_images_button",
             "remove_images_button", "naming_policy_button",
             "manual_toggle_button", "open_link_panel_button",
             "smart_link_button", "suggest_group_button",
             "link_same_item_button", "reference_group_link_button",
             "link_by_image_button", "manual_link_button"]
    errs = 0
    for nm in names:
        b = getattr(win, nm, None)
        if b is None or not hasattr(b, "click"):
            continue
        if not b.isEnabled():
            say(f"      ○ {nm}: معطّل")
            continue
        t0 = time.perf_counter()
        try:
            b.click()
            app.processEvents()
            ms = (time.perf_counter() - t0) * 1000
            flag = " ⏱بطيء" if ms > 1200 else ""
            say(f"      ✓ {nm}: {ms:.0f} مث{flag}")
        except Exception as exc:
            errs += 1
            say(f"      ✗ {nm}: {type(exc).__name__}: {exc}")
    check("لا استثناء في أزرار ما بعد التحميل", errs == 0, f"{errs} خطأ")

    say("\n[6] نوافذ الرسائل التي ظهرت (قد تكشف رسائل خطأ زائفة)")
    for d in DIALOGS[-12:]:
        say(f"    • {d}")

    say("\n" + "═" * 64)
    passed = CHECKS - len(FAILURES)
    say(f"النتيجة: {passed}/{CHECKS}")
    if FAILURES:
        say("\nفشل:")
        for f in FAILURES:
            say(f"  ✗ {f}")
    shutil.rmtree(work, ignore_errors=True)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
