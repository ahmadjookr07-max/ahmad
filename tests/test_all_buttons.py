# -*- coding: utf-8 -*-
"""تجريب فعلي لكل زر ووظيفة على مساري العمل.

متطلب المالك: «جرب كل شيء في الملفات المنجزة والملفات الجديدة، كل
وظيفة وكل زر، إذا كان فيه خطأ أصلحه» + «أي بطء أصلحه فورًا».

لا يقرأ الكود ويحكم، بل **يضغط الأزرار فعليًا** في بيئة بلا شاشة
ويرصد: الاستثناءات، نوافذ الخطأ، والزمن. كل ضغطة تتجاوز حد البطء
تُسجَّل كإخفاق أداء.

يُعترض `QMessageBox` و`QFileDialog` تلقائيًا حتى لا تتعلّق الاختبارات.
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

SLOW_MS = 1200.0          # حد البطء المقبول لضغطة زر واحدة
HANG_MS = 20000.0         # فوقه نعدّ الزر مُعلّقًا (حجب الواجهة)
LOG = Path("/home/ubuntu/button_probe.log")


def say(msg: str) -> None:
    """يطبع ويُفرِغ فورًا حتى لا يضيع السجل إن تعلّق زر."""
    print(msg, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(msg + "\n")
        fh.flush()
        os.fsync(fh.fileno())


RESULTS: list[dict] = []
DIALOGS: list[str] = []   # نوافذ الرسائل الملتقطة


# ── اعتراض النوافذ الحاجزة ─────────────────────────────────────────
def install_dialog_traps() -> None:
    from PySide6.QtWidgets import (QDialog, QFileDialog, QInputDialog,
                                   QMessageBox)

    # الأهم: النوافذ المخصصة (سياسة التسمية، اقتصاص التغدية …)
    # تستدعي exec() وهي حاجبة تمامًا في بيئة بلا شاشة.
    def _exec_trap(self, *a, **k):
        DIALOGS.append(f"dialog: {type(self).__name__}")
        try:
            self.close()
        except Exception:
            pass
        return int(QDialog.DialogCode.Rejected)

    QDialog.exec = _exec_trap
    QDialog.exec_ = _exec_trap
    QDialog.open = lambda self, *a, **k: None

    def trap(kind):
        def _fn(*a, **k):
            txt = ""
            for arg in a:
                if isinstance(arg, str):
                    txt = arg if len(arg) > len(txt) else txt
            DIALOGS.append(f"{kind}: {txt[:200]}")
            return QMessageBox.StandardButton.Ok
        return staticmethod(_fn)

    QMessageBox.information = trap("info")
    QMessageBox.warning = trap("warn")
    QMessageBox.critical = trap("error")
    QMessageBox.question = trap("ask")
    QMessageBox.about = trap("about")

    QFileDialog.getOpenFileName = staticmethod(
        lambda *a, **k: ("", ""))
    QFileDialog.getOpenFileNames = staticmethod(
        lambda *a, **k: ([], ""))
    QFileDialog.getExistingDirectory = staticmethod(
        lambda *a, **k: "")
    QFileDialog.getSaveFileName = staticmethod(
        lambda *a, **k: ("", ""))
    QInputDialog.getText = staticmethod(lambda *a, **k: ("", False))
    QInputDialog.getItem = staticmethod(lambda *a, **k: ("", False))


def press(win, name: str, ctx: str, app) -> dict:
    """يضغط زرًا واحدًا ويقيس ويرصد."""
    rec = {"ctx": ctx, "button": name, "ok": True, "ms": 0.0,
           "error": "", "dialogs": 0, "skipped": ""}
    btn = getattr(win, name, None)
    if btn is None:
        rec["skipped"] = "غير موجود"
        RESULTS.append(rec)
        return rec
    if not hasattr(btn, "click"):
        rec["skipped"] = "ليس زرًا"
        RESULTS.append(rec)
        return rec
    if not btn.isEnabled():
        rec["skipped"] = "معطّل"
        RESULTS.append(rec)
        return rec

    before = len(DIALOGS)
    say(f"    → أضغط: {name}")
    t0 = time.perf_counter()
    try:
        btn.click()
        app.processEvents()
    except Exception as exc:
        rec["ok"] = False
        rec["error"] = f"{type(exc).__name__}: {exc}"
        rec["trace"] = traceback.format_exc(limit=6)
    rec["ms"] = (time.perf_counter() - t0) * 1000.0
    rec["dialogs"] = len(DIALOGS) - before
    if rec["dialogs"]:
        rec["dialog_text"] = " | ".join(DIALOGS[before:])[:300]
    RESULTS.append(rec)
    return rec


ALL_BUTTONS = [
    "run_button", "open_folder_button", "open_legacy_button",
    "save_zip_button", "naming_policy_button", "back_to_setup_button",
    "select_catalog_button", "select_images_button", "select_folder_button",
    "clear_images_button", "remove_images_button",
    "manual_link_button", "manual_toggle_button", "smart_link_button",
    "link_by_image_button", "link_same_item_button",
    "reference_group_link_button", "suggest_group_button",
    "open_link_panel_button", "use_reference_button",
    "manual_tilt_cw_button", "manual_tilt_ccw_button",
    "manual_tilt_reset_button",
    "edit_image_button", "editor_expand_button", "editor_nutrition_button",
    "nutrition_button", "individual_apply_button",
    "individual_preview_button", "individual_reset_button",
    "individual_cancel_button", "individual_auto_crop_button",
    "individual_crop_clear_button", "individual_crop_full_button",
    "individual_manual_crop_button", "individual_smart_button",
    "individual_show_preview_button", "individual_show_source_button",
    "set_primary_button", "delete_output_button",
    "open_selected_file_button", "first_item_button", "last_item_button",
    "jump_to_previews_button", "clear_result_filter_button",
    "open_button",
]


def make_legacy(dest: Path, groups: int = 4) -> Path:
    from PIL import Image
    dest.mkdir(parents=True, exist_ok=True)
    for g in range(groups):
        code = str(10000001 + g)
        for suf in ("", "-1", "-2"):
            Image.new("RGB", (800, 700), (245, 245, 245)).save(
                dest / f"{code}_حبه{suf}.webp", "WEBP")
    return dest


def run_context(label: str, prepare) -> None:
    """ينشئ نافذة، يهيّئ سياقًا، ثم يضغط كل الأزرار."""
    from PySide6.QtWidgets import QApplication
    import native_app as na

    app = QApplication.instance() or QApplication([])
    say(f"\n{'═' * 64}\n سياق: {label}\n{'═' * 64}")
    t0 = time.perf_counter()
    win = na.MainWindow()
    boot = (time.perf_counter() - t0) * 1000.0
    say(f"  زمن إنشاء النافذة: {boot:.0f} مث"
        + ("  ⚠ بطيء" if boot > 3000 else ""))
    try:
        t1 = time.perf_counter()
        prepare(win, app)
        say(f"  زمن تهيئة السياق: "
            f"{(time.perf_counter() - t1) * 1000.0:.0f} مث")
    except Exception as exc:
        say(f"  ✗ فشل تهيئة السياق: {type(exc).__name__}: {exc}")
        say(traceback.format_exc(limit=8))

    errs = slows = pressed = hangs = 0
    for name in ALL_BUTTONS:
        rec = press(win, name, label, app)
        if rec["skipped"]:
            continue
        pressed += 1
        if not rec["ok"]:
            errs += 1
            say(f"  ✗ {name}: {rec['error']}")
        elif rec["ms"] > HANG_MS:
            hangs += 1
            say(f"  ☠ {name}: {rec['ms']:.0f} مث — يحجب الواجهة!")
        elif rec["ms"] > SLOW_MS:
            slows += 1
            say(f"  ⏱ {name}: {rec['ms']:.0f} مث (بطيء)")
        else:
            say(f"      ✓ {name}: {rec['ms']:.0f} مث"
                + (f" [نوافد {rec['dialogs']}]" if rec["dialogs"] else ""))
    say(f"  ── ضُغط {pressed} زرًا | أخطاء {errs} | بطيء {slows} | "
        f"حاجب {hangs}")
    # 2.9.9 — يجب إنهاء الخيوط **قبل** هدم النافذة. بعض الأزرار
    # تُطلق عاملًا في الخلفية (معاينة، تحرير فردي)، وإن جمع
    # بايثون النافذة والخيط لا يزال يعمل يرفع Qt
    # «QThread: Destroyed while thread is still running» ثم SIGABRT،
    # فيموت الاختبار برمته بعد طباعة نتائجه الناجحة
    # فيُقرأ وكأنه فاشل. النافذة توفر مسار الإغلاق الرسمي
    # نفسه الذي تستخدمه عند إغلاق المستخدم للبرنامج.
    try:
        shutdown = getattr(win, "_shutdown_workers", None)
        if callable(shutdown):
            shutdown(2000)
        app.processEvents()
    except Exception as exc:
        say(f"  ⚠ تعذر إغلاق الخيوط: {exc}")
    try:
        win.close()
        win.deleteLater()
        app.processEvents()
    except Exception:
        pass


def ctx_empty(win, app) -> None:
    """السياق الأول: تطبيق فارغ كما يفتحه المالك أول مرة."""
    return None


def ctx_legacy(win, app) -> None:
    """السياق الثاني: مجلد منجز مفتوح (ملفات المالك السابقة)."""
    work = Path(tempfile.mkdtemp(prefix="btn_legacy_"))
    folder = make_legacy(work / "منجز")
    # نستدعي مسار الفتح الحقيقي مباشرة
    win._load_legacy_folder(folder)
    app.processEvents()
    n = len(getattr(win.current_result, "items", []) or [])
    say(f"  حُمّل مجلد منجز: {n} عنصرًا | "
        f"job_state={bool((folder / 'job_state.json').is_file())}")
    if win.results_table.rowCount():
        win.results_table.selectRow(0)
        app.processEvents()
        say(f"  حُدّد الصف 0 من {win.results_table.rowCount()}")


def main() -> int:
    LOG.write_text("", "utf-8")
    install_dialog_traps()
    say("═" * 64)
    say(" تجريب فعلي لكل زر — الملفات الجديدة والمنجزة")
    say("═" * 64)
    run_context("تطبيق فارغ (قبل أي تحميل)", ctx_empty)
    run_context("مجلد منجز مفتوح", ctx_legacy)

    print("\n" + "═" * 64)
    total = [r for r in RESULTS if not r["skipped"]]
    errs = [r for r in RESULTS if not r["ok"]]
    slows = [r for r in total if r["ms"] > SLOW_MS]
    print(f"إجمالي الضغطات المنفّذة: {len(total)}")
    print(f"أخطاء: {len(errs)} | بطيئة: {len(slows)}")

    # ── تقرير التغطية (منع النجاح الزائف) ──────────────────
    # الملف كان يطبع «أخطاء: 0» ويُعلن نجاحًا حتى لو لم يُضغط
    # إلا نصف الأزرار؛ فأزرار لا تُفعّل إلا بعد معالجة حقيقية
    # تبقى معطّلة فتُتخطّى بصمت. الأن نطبعها بالاسم.
    tested = {r["button"] for r in total}
    never = [b for b in ALL_BUTTONS if b not in tested]
    missing = sorted({r["button"] for r in RESULTS
                      if r["skipped"] == "غير موجود"})
    coverage = 100.0 * len(tested) / max(1, len(ALL_BUTTONS))
    print(f"\nالتغطية: {len(tested)}/{len(ALL_BUTTONS)} زرًا "
          f"({coverage:.0f}%)")
    if never:
        print("لم يُضغط في أي سياق (معطّل أو غير موجود) — غير مفحوص:")
        for b in never:
            why = "غير موجود" if b in missing else "معطّل في كل السياقات"
            print(f"  − {b}: {why}")
        print("  (يُفحص هذه الأزرار سياق ما بعد المعالجة في "
              "tests/test_full_run.py مع بيانات المالك.)")
    if errs:
        print("\nالأخطاء:")
        for r in errs:
            print(f"  ✗ [{r['ctx']}] {r['button']}: {r['error']}")
    if slows:
        print("\nالبطيئة:")
        for r in sorted(slows, key=lambda x: -x["ms"]):
            print(f"  ⏱ [{r['ctx']}] {r['button']}: {r['ms']:.0f} مث")

    # أبطأ 8 عمليات عمومًا (للرصد الاستباقي)
    print("\nأبطأ 8 ضغطات:")
    for r in sorted(total, key=lambda x: -x["ms"])[:8]:
        print(f"  {r['ms']:7.1f} مث  [{r['ctx']}] {r['button']}")
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main())
