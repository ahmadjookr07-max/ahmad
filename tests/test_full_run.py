# -*- coding: utf-8 -*-
"""تشغيل دفعة كاملة فعلية (run_batch) على بيانات المالك.

هذه المرحلة تُفعّل أزرار الربط والحفظ التي كانت معطّلة، وتكشف
علة A2 الحقيقية إن كانت في المطابقة أو المعالجة لا في الرفع.

يقيس: زمن المعالجة لكل صورة، عدد المطابقات، الأسماء الناتجة،
سلامة ملفات المخرجات، ثم يضغط كل زر صار مُفعَّلًا.
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

# حرّاس بيانات المالك: عند غياب المدخلات يتخطّى برمز 77 بدل
# إعلان فشل زائف (معالجة 0 صورة تُقرأ خطأً كعلة في التطبيق).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from owner_data_guard import (  # noqa: E402
    describe, list_images, require_owner_data)

CATALOG, RAW = require_owner_data(need_catalog=True, need_raw=True,
                                  minimum_images=3)
LOG = Path("/home/ubuntu/full_run.log")

FAILURES: list[str] = []
CHECKS = 0
DIALOGS: list[str] = []


def say(msg: str) -> None:
    print(msg, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(msg + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def check(label: str, cond: bool, detail: str = "", ok_detail: str = "") -> bool:
    """تأكيد مقاس.

    ``detail`` توصيف الفشل وحده، و``ok_detail`` توصيف النجاح.
    فصلهما يمنع ما وقع فعلًا: طباعة «✓ مسار المطابقة يعمل
    — صفر مطابقة»، وهو تقرير متناقض يفتح باب النجاح الزائف.
    """
    global CHECKS
    CHECKS += 1
    if cond:
        say(f"  ✓ {label}" + (f" — {ok_detail}" if ok_detail else ""))
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
    say(" تشغيل دفعة كاملة فعلية على بيانات المالك")
    say("═" * 64)

    say(describe())
    install_traps()
    from PySide6.QtWidgets import QApplication
    import native_app as na
    app = QApplication.instance() or QApplication([])

    raw = list_images(RAW)
    spaced = [p for p in raw if " " in p.name]
    plain = [p for p in raw if " " not in p.name]
    work = Path(tempfile.mkdtemp(prefix="full_run_"))
    src = work / "خام"
    src.mkdir(parents=True)
    # حجم العينة قابل للضبط: ``MIS_FULL_SAMPLE=all`` يشغّل مجلد
    # المالك **كاملًا** (109 صورة) كما طلب صراحةً «مطابقة
    # كل شيء نفس السياق»، وإلا عينة سريعة تكفي لمنع الانحدار.
    _sample_env = os.environ.get("MIS_FULL_SAMPLE", "").strip().lower()
    if _sample_env in {"all", "full", "0"}:
        sample = list(raw)
    else:
        try:
            _per = max(1, int(_sample_env) // 2) if _sample_env else 6
        except ValueError:
            _per = 6
        sample = spaced[:_per] + plain[:_per]
    for p in sample:
        shutil.copy2(p, src / p.name)
    out = work / "مخرجات"
    say(f"\n[1] عينة: {len(sample)} صورة | مخرجات: {out}")

    win = na.MainWindow()
    win.catalog_path = CATALOG
    win.catalog_edit.setText(str(CATALOG))
    if hasattr(win, "_on_catalog_chosen"):
        win._on_catalog_chosen(CATALOG)
    win._add_paths([str(p) for p in list_images(src)])
    app.processEvents()
    say(f"    محمّل: إكسل ✓ | صور {win.image_list.count()}")

    # ── نُوجّه مجلد المخرجات ────────────────────────────────────────
    for attr in ("output_dir", "output_path", "out_dir"):
        if hasattr(win, attr):
            try:
                setattr(win, attr, out)
                say(f"    وُجّه المخرج عبر {attr}")
            except Exception:
                pass
    for attr in ("output_edit", "out_edit", "output_dir_edit"):
        w = getattr(win, attr, None)
        if w is not None and hasattr(w, "setText"):
            w.setText(str(out))
            say(f"    وُجّه المخرج عبر {attr}")

    # ── تشغيل الدفعة ───────────────────────────────────────────────
    say("\n[2] بدء المعالجة (ضغط زر التشغيل)")
    t0 = time.perf_counter()
    try:
        win.run_button.click()
        app.processEvents()
    except Exception as exc:
        check("بدأت المعالجة بلا استثناء", False,
              f"{type(exc).__name__}: {exc}")
        say(traceback.format_exc(limit=8))
    else:
        check("بدأت المعالجة بلا استثناء", True)

    # ── ننتظر انتهاء العامل ────────────────────────────────────────
    # ملاحظة حرجة: `processEvents` داخل حلقة `time.sleep` لا يدير حلقة
    # الأحداث التي يحتاجها الخيط لتسليم إشاراته، فتبدو المعالجة وكأنها
    # «لا تنتج شيئًا». نستخدم QEventLoop + QTimer كما يجري فعليًا عند المالك.
    from PySide6.QtCore import QEventLoop, QTimer

    def _threads():
        found = []
        # إصلاح قصور قياس حقيقي: كانت القائمة تغفل
        # `manual_worker` و`individual_worker` وهما الخيطان اللذان
        # يعتمد عليهما `_update_controls` فعلًا في حساب `busy`.
        # النتيجة كانت: `_reselect` لا يرى خيط المعاينة فلا
        # ينتطره، فتُقاس أزرار المحرر أثناء انشغال مشروع
        # فتُعلن «معطّلة» — إخفاق زائف لا عطب في التطبيق.
        for attr in ("worker", "_worker", "thread", "_thread",
                     "run_thread", "_batch_worker", "batch_worker",
                     "manual_worker", "individual_worker",
                     "_active_workers", "_workers", "_tracked_workers"):
            th = getattr(win, attr, None)
            if th is None:
                continue
            items_ = list(th) if isinstance(th, (list, tuple, set)) else [th]
            for c in items_:
                if hasattr(c, "isRunning"):
                    found.append(c)
        return found

    # المهل تتناسب مع حجم الدفعة: مهلة ثابتة (45/420 ث) كانت
    # ستقطع دفعة 109 صور قبل نهايتها وتُقرأ خطأً كعلة في التطبيق.
    _idle_limit = 45 if len(sample) <= 20 else 120
    _hard_limit = max(420, 25 * len(sample))
    loop = QEventLoop()
    state = {"last": "", "done": False}

    def _poll():
        try:
            msg = win.status_label.text()[:90]
            if msg != state["last"]:
                say(f"    … {msg}")
                state["last"] = msg
        except Exception:
            pass
        busy = False
        for th in _threads():
            try:
                busy = busy or bool(th.isRunning())
            except Exception:
                pass
        cur = getattr(win, "current_result", None)
        has = bool(cur is not None and getattr(cur, "items", None))
        elapsed = time.perf_counter() - t0
        if has and not busy:
            state["done"] = True
        elif not busy and elapsed > _idle_limit:
            state["done"] = True
        elif elapsed > _hard_limit:
            state["done"] = True
        if state["done"]:
            timer.stop()
            loop.quit()

    timer = QTimer()
    timer.timeout.connect(_poll)
    timer.start(400)
    loop.exec()
    ms = (time.perf_counter() - t0) * 1000
    say(f"    زمن المعالجة الكلي: {ms/1000:.1f} ث "
        f"({ms/max(1,len(sample)):.0f} مث/صورة)")

    res = getattr(win, "current_result", None)
    items = list(getattr(res, "items", []) or []) if res else []
    check("أنتجت المعالجة نتائج", len(items) > 0,
          f"{len(items)} عنصرًا")
    check("زمن المعالجة معقول (<20 ث/صورة)",
          ms / max(1, len(sample)) < 20000,
          f"{ms/max(1,len(sample)):.0f} مث/صورة")

    if items:
        say(f"\n[3] فحص النتائج ({len(items)} عنصرًا)")
        # علة نجاح زائف مُصلحة: كان يُقرأ ``item_number``/``code``
        # وهما غير موجودين في ``BatchItemResult``؛ الحقل الحقيقي
        # ``item_code``. فكان العداد يطبع 0 دائمًا حتى مع مطابقة
        # كاملة، ويمرّ الاختبار بلا اعتراض.
        matched = 0
        missing_files = 0
        names = []
        sources = {}
        _cap = len(items) if len(sample) > 20 else 40
        for it in items[:_cap]:
            code = (getattr(it, "item_code", None)
                    or getattr(it, "item_number", None)
                    or getattr(it, "code", None) or "")
            if code:
                matched += 1
            source = str(getattr(it, "match_source", "") or "unknown")
            sources[source] = sources.get(source, 0) + 1
            fp = (getattr(it, "output_path", None)
                  or getattr(it, "path", None))
            if fp:
                names.append(Path(str(fp)).name)
                if not Path(str(fp)).is_file():
                    missing_files += 1
        check("كل ملفات المخرجات موجودة فعلًا على القرص",
              missing_files == 0, f"{missing_files} مفقود")
        say(f"    مطابقات بأرقام أصناف: {matched}/{len(items[:_cap])}")
        say(f"    توزيع مصادر المطابقة: {sources}")
        # صفر مطابقة لا يجوز أن يُعدّ نجاحًا: معناه أن مسار
        # المطابقة معطّل بأكمله (مكتبة ناقصة أو كتالوج لم يُقرأ).
        check("مسار المطابقة يعمل (مطابقة واحدة على الأقل)",
              matched > 0,
              "صفر مطابقة — راجع zxingcpp وقراءة الكتالوج",
              ok_detail=f"{matched} مطابقة بالباركود")
        say("    أمثلة أسماء ناتجة:")
        for n in names[:6]:
            say(f"      • {n}")

        # ── الأزرار التي صارت مُفعَّلة الآن ──────────────────────────
        say("\n[4] ضغط الأزرار التي فُعِّلت بعد المعالجة")
        if win.results_table.rowCount():
            win.results_table.selectRow(0)
            app.processEvents()
        names_btn = ["save_zip_button", "open_folder_button",
                     "manual_link_button", "open_link_panel_button",
                     "suggest_group_button", "link_same_item_button",
                     "reference_group_link_button", "smart_link_button",
                     "link_by_image_button", "use_reference_button",
                     "set_primary_button", "edit_image_button",
                     "individual_preview_button",
                     "individual_apply_button",
                     "individual_auto_crop_button",
                     "individual_smart_button",
                     "first_item_button", "last_item_button",
                     "back_to_setup_button"]
        errs = 0
        slow = 0
        # إصلاح قياس: الأزرار تُضغط بالتوالي، وبعضها يغير التحديد
        # أو التبويب (manual_link / back_to_setup) فيسقط شرط «صف واحد
        # محدَّد» وتبدو أزرار المحرر «معطّلة» دون أن تُقاس فعلًا.
        # نُعيد التحديد قبل كل زر ليُقاس كل زر في سياقه الصحيح.
        def _reselect() -> None:
            # الزر السابق قد يكون أطلق خيطًا (معاينة/ربط)، وأثناء
            # الانشغال تُعطّل أزرار المحرر مشروعًا. القياس الصادق
            # ينتطر خمود الانشغال كما ينتطر المالك بصريًا.
            deadline = time.perf_counter() + 20
            while time.perf_counter() < deadline:
                app.processEvents()
                if not any(t.isRunning() for t in _threads()):
                    break
                time.sleep(0.1)
            try:
                if win.results_table.rowCount():
                    win.results_table.clearSelection()
                    win.results_table.selectRow(0)
                    app.processEvents()
                if hasattr(win, "_update_controls"):
                    win._update_controls()
                    app.processEvents()
            except Exception:
                pass

        skipped: list[str] = []
        for nm in names_btn:
            b = getattr(win, nm, None)
            if b is None or not hasattr(b, "click"):
                continue
            _reselect()
            if not b.isEnabled():
                # تشخيص مفصّل: التمييز بين «معطّل» و«مخفي» و«أبوه
                # مخفي» جوهري، لأن كل حالة لها حكم مختلف تمامًا
                # على وجود العطب: المخفي قد يكون مقصودًا للتوافق.
                parent = b.parentWidget()
                try:
                    editable = win._individual_editable_item() is not None
                except Exception:
                    editable = "?"
                try:
                    tab_index = win.preview_tabs.currentIndex()
                except Exception:
                    tab_index = "?"
                say(f"      ○ {nm}: معطّل — visible={b.isVisible()} "
                    f"parent={type(parent).__name__ if parent else 'NA'} "
                    f"parentVisible="
                    f"{parent.isVisible() if parent else 'NA'} "
                    f"editable={editable} tab={tab_index}")
                skipped.append(nm)
                continue
            t1 = time.perf_counter()
            try:
                b.click()
                app.processEvents()
                d = (time.perf_counter() - t1) * 1000
                if d > 1200:
                    slow += 1
                    say(f"      ⏱ {nm}: {d:.0f} مث (بطيء)")
                else:
                    say(f"      ✓ {nm}: {d:.0f} مث")
            except Exception as exc:
                errs += 1
                say(f"      ✗ {nm}: {type(exc).__name__}: {exc}")
                say("        " + traceback.format_exc(limit=4)
                    .replace("\n", "\n        ")[:600])
        check("لا استثناء في أزرار ما بعد المعالجة", errs == 0,
              f"{errs} خطأ")
        check("لا بطء في أزرار ما بعد المعالجة", slow == 0,
              f"{slow} بطيء")
        # أزرار المحرر بالذات يجب أن تُقاس مضغوطة، لا أن تُترك
        # معطّلة — فهي محل علة المالك «لا يحفظ أثناء التعديل».
        editor_btns = {"edit_image_button", "individual_apply_button",
                       "individual_preview_button"}
        left_off = sorted(editor_btns & set(skipped))
        check("أزرار محرر الصورة مُفعّلة ومقيسة فعلًا",
              not left_off, f"بقيت معطّلة: {left_off}",
              ok_detail="كلها ضُغِطت")

    say("\n[5] آخر نوافذ الرسائل")
    for d in DIALOGS[-15:]:
        say(f"    • {d}")

    say("\n" + "═" * 64)
    say(f"النتيجة: {CHECKS - len(FAILURES)}/{CHECKS}")
    if FAILURES:
        say("\nفشل:")
        for f in FAILURES:
            say(f"  ✗ {f}")
    say(f"\nمجلد العمل محفوظ للفحص: {work}")

    # ── إنهاء نظيف: انتظار كل خيط قبل الخروج ─────────────────────
    # بلا هذا يطبع Qt: `Destroyed while thread is still running` ثم
    # SIGABRT — وهو انهيار الاختبار نفسه، فيخفي النتيجة الحقيقية.
    try:
        if hasattr(win, "_shutdown_workers"):
            win._shutdown_workers()
        for th in _threads():
            try:
                if th.isRunning():
                    th.requestInterruption()
                    th.quit()
                    th.wait(15000)
            except Exception:
                pass
        app.processEvents()
        win.close()
        app.processEvents()
    except Exception as exc:
        say(f"    (تنظيف: {type(exc).__name__}: {exc})")

    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
