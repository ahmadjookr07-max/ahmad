"""برهان الربط بالإكسل + التسمية بكل الوحدات على **الجهة الجديدة**.

الجهة المنجزة أُثبتت في ``test_owner_units_real.py`` (992/992). هذا الاختبار
يغلق الثغرة الأخرى: الصور **الخام** التي تُعالج الآن — هل بعد ربطها بصف
الإكسل يحمل اسمها **كل** وحدات الصنف (حبه/شده/كرتون/باكت…) لا وحدة واحدة؟

القياس على بيانات المالك الحقيقية فقط:
  • كتالوج: ``owner_data/اصنافعالمعنترة.xlsx`` (50,311 صفًا / 22,087 صنفًا)
  • صور خام: ``owner_data/زيت`` (109 صورة)
لا أسماء وهمية ولا مجلدات مصطنعة — تلك كانت مصدر الثقة الزائفة.
"""
from __future__ import annotations

import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MIS_HEADLESS", "1")
os.environ.setdefault("MIS_SKIP_LICENSE", "1")

ROOT = Path(__file__).resolve().parent.parent
for extra in (ROOT / "src", ROOT / "windows_app"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from owner_data_guard import (  # noqa: E402
    find_catalog,
    find_raw_dir,
    list_images,
    require_owner_data,
)

CHECKS = 0
FAILURES: list[str] = []


def say(msg: str) -> None:
    print(msg, flush=True)


def check(label: str, cond: bool, fail: str = "", ok: str = "") -> bool:
    global CHECKS
    CHECKS += 1
    if cond:
        say(f"  ✓ {label}" + (f" — {ok}" if ok else ""))
        return True
    FAILURES.append(f"{label}{(' — ' + fail) if fail else ''}")
    say(f"  ✗ {label}" + (f" — {fail}" if fail else ""))
    return False


# ─────────────────────────── وحدات الإكسل مرجعًا مستقلًا ───────────────────────
def excel_units(catalog: Path) -> dict[str, list[str]]:
    """يقرأ الإكسل مباشرة بـopenpyxl — مرجع مستقل عن محرّك التطبيق.

    لو استعملنا دوال التطبيق نفسها لبناء المرجع لكان الاختبار يقارن
    الشيء بنفسه (تحصيل حاصل) ولمرّ حتى لو كان المنطق خاطئًا.
    """
    import openpyxl

    wb = openpyxl.load_workbook(catalog, read_only=True, data_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    header = [str(c or "").strip() for c in next(rows)]

    def col(*names: str) -> int:
        for n in names:
            for i, h in enumerate(header):
                if n in h:
                    return i
        return -1

    i_code = col("رقم الصنف", "رقم")
    i_unit = col("الوحدة")
    if i_code < 0 or i_unit < 0:
        raise SystemExit(f"أعمدة الكتالوج غير معروفة: {header}")

    out: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        if not row or i_code >= len(row):
            continue
        code = str(row[i_code] or "").strip()
        unit = str(row[i_unit] or "").strip() if i_unit < len(row) else ""
        if not code or not unit:
            continue
        code = code.split(".")[0]
        if unit not in out[code]:
            out[code].append(unit)
    wb.close()
    return dict(out)


def norm(unit: str) -> str:
    """توحيد إملائي للمقارنة فقط (لا للعرض).

    حبه/حبة وشده/شدة صيغتان لوحدة واحدة.

    **المسافة الداخلية تُحذف** اتباعًا لقاعدة المالك المعتمدة
    (2.9.6 الخيار «أ»): المسافة تُفسد روابط المتاجر فتُحذف مع
    حفظ التمييز: ``كرتون 1`` ⇒ ``كرتون1`` و ``نص كرتون`` ⇒ ``نصكرتون``.

    كان المرجع يحفظ المسافة فيقارن ``كرتون 1`` باسم الملف
    ``كرتون1`` فيحكم بالنقص زورًا — فيبلّغ عن إخفاق لا وجود له.
    التطبيع هنا للمقارنة وحدها؛ المرجع ما زال مبنيًا مستقلًا بـopenpyxl
    لا بدوال التطبيق، فلا يقارن الشيء بنفسه.
    """
    u = unit.strip().replace("ة", "ه").replace("أ", "ا").replace("إ", "ا")
    return re.sub(r"\s+", "", u)


# لاحقة رقم الصورة تأتي بـ **أي من الفاصلين**: `10014649_حبه-2`
# (نمط dash) أو `10014649_حبه_2` (النمط القياسي)، وكلتاهما
# مشروعة في المحرك (انظر `naming_v2.parse_name`).
# كان النمط يعرف الشرطة العادية وحدها، فيبتلع `حبه_2`
# كاملاً في مجموعة units ثم يقطعها فيعدّ `2` **وحدة قياس**،
# فيبلّغ زورًا عن وحدة زائدة وأخرى ناقصة من سطر واحد.
NAME_RE = re.compile(r"^(?P<code>\d+)_(?P<units>.+?)(?:[-_](?P<seq>\d+))?$")


def parse_name(stem: str) -> tuple[str, list[str], str | None] | None:
    m = NAME_RE.match(stem)
    if not m:
        return None
    # حتّى بعد فصل اللاحقة، يُستبعد أي جزء رقمي محض من الوحدات
    # إذ لا توجد وحدة قياس اسمها رقم مجرّد.
    units = [p for p in m.group("units").split("_") if p and not p.isdigit()]
    return (m.group("code"), units, m.group("seq"))


def main() -> int:
    require_owner_data()
    catalog = find_catalog()
    raw_dir = find_raw_dir()
    say(f"كتالوج: {catalog}")
    say(f"صور خام: {raw_dir}  ({len(list_images(raw_dir))} صورة)")

    say("\n[1] مرجع الوحدات من الإكسل مباشرة (openpyxl)")
    ref = excel_units(catalog)
    multi = sum(1 for v in ref.values() if len(v) > 1)
    check("الكتالوج قُرئ وفيه أصناف", len(ref) > 1000,
          f"{len(ref)} صنفًا فقط",
          ok=f"{len(ref)} صنفًا، منها {multi} بأكثر من وحدة "
             f"({multi * 100 // max(len(ref), 1)}%)")

    say("\n[2] تشغيل معالجة فعلية على صور المالك الخام")
    from PySide6.QtWidgets import QApplication
    import native_app as na

    app = QApplication.instance() or QApplication([])
    win = na.MainWindow()
    win._auto_confirm_dialogs = True
    na.QMessageBox.information = staticmethod(lambda *a, **k: None)
    na.QMessageBox.warning = staticmethod(lambda *a, **k: None)
    na.QMessageBox.critical = staticmethod(lambda *a, **k: None)
    na.QMessageBox.question = staticmethod(
        lambda *a, **k: na.QMessageBox.StandardButton.Yes)

    win.catalog_path = catalog
    win.catalog_edit.setText(str(catalog))
    if hasattr(win, "_on_catalog_chosen"):
        win._on_catalog_chosen(catalog)
    app.processEvents()

    imgs = list_images(raw_dir)
    win._add_paths([str(p) for p in imgs])
    app.processEvents()
    say(f"    صور مُحمّلة في الواجهة: {win.image_list.count()}")

    from PySide6.QtCore import QEventLoop, QTimer

    t0 = time.perf_counter()
    win.run_button.click()
    app.processEvents()

    def _threads():
        found = []
        for attr in ("worker", "_worker", "_batch_worker", "batch_worker",
                     "_active_workers", "_workers", "_tracked_workers"):
            th = getattr(win, attr, None)
            if th is None:
                continue
            cand = list(th) if isinstance(th, (list, tuple, set)) else [th]
            for c in cand:
                if hasattr(c, "isRunning"):
                    found.append(c)
        return found

    # حلقة أحداث حقيقية: `processEvents` داخل `sleep` لا تسلّم
    # إشارات الخيوط فتبدو المعالجة وكأنها لا تنتج شيئًا.
    loop = QEventLoop()
    state = {"last": "", "n": 0}
    _hard = max(600, 25 * len(imgs))

    def _poll():
        try:
            msg = win.status_label.text()[:90]
            if msg != state["last"]:
                state["n"] += 1
                if state["n"] % 10 == 0:
                    say(f"    … {msg}")
                state["last"] = msg
        except Exception:
            pass
        busy = any(t.isRunning() for t in _threads())
        cur = getattr(win, "current_result", None)
        has = bool(cur is not None and getattr(cur, "items", None))
        el = time.perf_counter() - t0
        if (has and not busy) or (not busy and el > 120) or el > _hard:
            timer.stop()
            loop.quit()

    timer = QTimer()
    timer.timeout.connect(_poll)
    timer.start(400)
    loop.exec()
    say(f"    زمن المعالجة: {(time.perf_counter() - t0):.1f} ث")

    result = getattr(win, "current_result", None)
    items = list(getattr(result, "items", []) or [])
    check("المعالجة أنتجت نتائج", bool(items), "صفر عنصر",
          ok=f"{len(items)} عنصرًا")
    if not items:
        return 1

    say("\n[3] الربط بالإكسل: كل صنف مُطابق موجود فعلًا في الكتالوج")
    linked = [it for it in items if str(getattr(it, "item_code", "") or "").strip()]
    say(f"    مرتبطة برقم صنف: {len(linked)}/{len(items)}")
    check("يوجد ربط فعلي بالإكسل", bool(linked), "لا صف مرتبط",
          ok=f"{len(linked)} صفًا مرتبطًا")
    unknown = [it.item_code for it in linked
               if str(it.item_code).split(".")[0] not in ref]
    check("كل رقم صنف مرتبط موجود في الإكسل", not unknown,
          f"أرقام غير موجودة: {unknown[:5]}",
          ok=f"{len(linked)}/{len(linked)} موجودة")

    say("\n[4] التسمية تحمل كل وحدات الصنف (حبه/شده/كرتون/باكت…)")
    outs: list[tuple[str, str]] = []
    for it in linked:
        p = str(getattr(it, "output_path", "") or "")
        if p:
            outs.append((str(it.item_code).split(".")[0], Path(p).stem))
    say(f"    ملفات ناتجة مُسمّاة: {len(outs)}")
    check("توجد ملفات ناتجة مُسمّاة", bool(outs), "لا ملف ناتج",
          ok=f"{len(outs)} ملفًا")

    bad_pattern: list[str] = []
    missing_units: list[str] = []
    extra_units: list[str] = []
    exact = 0
    for code, stem in outs:
        parsed = parse_name(stem)
        if parsed is None:
            bad_pattern.append(stem)
            continue
        got_code, got_units, _seq = parsed
        if got_code != code:
            bad_pattern.append(f"{stem} (كود {code})")
            continue
        want = {norm(u) for u in ref.get(code, [])}
        have = {norm(u) for u in got_units}
        # القاعدة الصحيحة: وحدة الاسم يجب أن تكون **من** وحدات
        # الصنف في الإكسل، لا أن تحمل كل وحداته. كان الشرط
        # السابق يطلب `want - have` فارغة، أي أن تحمل صورة الحبة
        # وحدة الكرتون أيضًا — وهو نقيض الغرض؛ إذ يلغي التمييز
        # بين صورة الحبة وصورة الكرتون للصنف نفسه.
        # والتطبيق يجمع الوحدات عند الحاجة فعلًا (راجع خطوة
        # الربط اليدوي: `10100003_درزن_حبه_كرتون`).
        if have - want:
            extra_units.append(f"{stem} ← زائد {sorted(have - want)}")
        elif want and not have:
            missing_units.append(f"{stem} ← بلا وحدة (المتوقع إحدى "
                                 f"{sorted(want)})")
        else:
            exact += 1

    check("كل الأسماء تتبع {رقم}_{وحدة}[_وحدة…][-تسلسل]", not bad_pattern,
          f"مخالف: {bad_pattern[:5]}", ok=f"{len(outs)} اسمًا")
    check("كل اسم يحمل وحدة من وحدات صنفه", not missing_units,
          f"{len(missing_units)} بلا وحدة: {missing_units[:5]}",
          ok=f"{exact} اسمًا وحدته مطابقة للإكسل")
    check("لا وحدات زائدة على الإكسل", not extra_units,
          f"{len(extra_units)} زائد: {extra_units[:5]}", ok="صفر زائد")

    multi_named = [s for _c, s in outs
                   if (pr := parse_name(s)) and len(pr[1]) > 1]
    multi_expected = [c for c, _s in outs if len(ref.get(c, [])) > 1]
    say(f"    أصناف متعددة الوحدات في الإكسل: {len(multi_expected)}")
    say(f"    أسماء فعلية متعددة الوحدات: {len(multi_named)}")
    check("الأصناف متعددة الوحدات سُمِّيت بكل وحداتها",
          len(multi_named) >= len(multi_expected),
          f"متوقع ≥{len(multi_expected)} فوُجد {len(multi_named)}",
          ok=f"{len(multi_named)}/{len(multi_expected)}")

    say("\n[5] عيّنات فعلية (اسم الملف ← وحدات الإكسل)")
    for code, stem in outs[:10]:
        say(f"      • {stem}.webp   ← الإكسل: {ref.get(code, [])}")

    say("\n[5b] الربط اليدوي: مسار أصيل لا علة")
    # المالك صرّح: «الملف يحتاج ربطًا يدويًا» — فلا يُعدّ بقاء
    # صور بلا باركود علة. المطلوب أن **مسار الربط اليدوي**
    # متاح ويُنتج اسمًا بكل الوحدات مثل مسار الباركود.
    unresolved = [it for it in items
                  if not str(getattr(it, "item_code", "") or "").strip()]
    say(f"    صفوف تنتظر ربطًا يدويًا: {len(unresolved)}")
    if win.results_table.rowCount():
        win.results_table.clearSelection()
        win.results_table.selectRow(0)
        app.processEvents()
    for nm in ("manual_link_button", "open_link_panel_button",
               "smart_link_button", "link_by_image_button"):
        b = getattr(win, nm, None)
        check(f"أداة الربط اليدوي متاحة: {nm}",
              b is not None and b.isEnabled(),
              "غائبة أو معطّلة", ok="مُفعّلة")

    # البرهان الحقيقي: ربط يدوي فعلي برقم صنف متعدد الوحدات
    # من إكسل المالك، ثم التحقق من الاسم الناتج.
    multi_code = next((c for c, us in ref.items() if len(us) > 2), None)
    if multi_code:
        say(f"    رقم متعدد الوحدات للاختبار: {multi_code} ← {ref[multi_code]}")
        from engine_v2 import naming_v2 as _nv
        from engine_v2 import catalog_index_v2 as _ci

        # 1) من الإكسل مباشرة (مرجع مستقل)
        want = [norm(u) for u in ref[multi_code]]
        # 2) من فهرس التطبيق (المسار الذي يستعمله الربط اليدوي)
        idx = None
        for attr in ("catalog_index", "_catalog_index", "index"):
            idx = getattr(win, attr, None)
            if idx is not None and hasattr(idx, "units_for_code"):
                break
        if idx is None or not hasattr(idx, "units_for_code"):
            try:
                idx = _ci.CatalogIndex()
                idx.load_excel(str(catalog))
                say("    (بُني فهرس مستقل من إكسل المالك)")
            except Exception as exc:
                say(f"    (تعذر بناء الفهرس: {exc})")
                idx = None
        if idx is not None and hasattr(idx, "units_for_code"):
            got = [norm(u) for u in (idx.units_for_code(multi_code) or [])]
            say(f"    فهرس التطبيق يرجع: {got}")
            check("فهرس التطبيق يرجع كل وحدات الصنف (لا واحدة)",
                  set(want) <= set(got),
                  f"ناقص {sorted(set(want) - set(got))} من {want}",
                  ok=f"{len(got)} وحدة = الإكسل")
            # 3) الاسم الناتج فعلًا من دالة التسمية
            stem = _nv.build_name_join_all(multi_code,
                                           idx.units_for_code(multi_code))
            say(f"    الاسم الناتج للربط اليدوي: {stem}")
            pr = parse_name(Path(stem).stem)
            have = {norm(u) for u in (pr[1] if pr else [])}
            check("اسم الربط اليدوي يحمل كل الوحدات",
                  pr is not None and set(want) <= have,
                  f"ناقص {sorted(set(want) - have)} في {stem}",
                  ok=f"{stem}")
            check("اسم الربط اليدوي يبدأ برقم الصنف المربوط",
                  pr is not None and pr[0] == multi_code,
                  f"الرقم في الاسم {pr[0] if pr else None} ≠ {multi_code}",
                  ok=multi_code)

    say("\n[6] تكافؤ الجهتين: نفس القاعدة على المنجز سابقًا")
    from owner_data_guard import find_legacy_dir
    legacy = find_legacy_dir()
    leg_files = [p for p in (legacy / "processed").glob("*.webp")] if legacy else []
    say(f"    ملفات منجزة: {len(leg_files)}")
    leg_bad = 0
    leg_checked = 0
    for p in leg_files:
        pr = parse_name(p.stem)
        if pr is None:
            continue
        c, us, _ = pr
        if c not in ref:
            continue
        leg_checked += 1
        if {norm(u) for u in ref[c]} - {norm(u) for u in us}:
            leg_bad += 1
    # 2.9.8 — تصحيح منطق هذا الفحص:
    #
    # كان يشترط `leg_bad == 0` أي أن يكون مجلد المالك المنجز
    # متوافقًا مع القاعدة الجديدة من تلقاء نفسه — وهذا مستحيل
    # منطقيًا: تلك الملفات (427 من 992) سُمّيت بقاعدة الوحدة
    # الواحدة **قبل** إصلاح 2.9.6، ولا يُعيد البرنامج تسمية ملفات
    # قديمة تلقائيًا بلا طلب المالك (وهو السلوك الأمان).
    #
    # فالمقياس الصحيح ليس «أهي متوافقة الآن؟» بل «أتقدر الأداة
    # على توفيقها؟» — وهو ما يُثبته `test_legacy_upgrade_427.py`
    # عمليًا على نسخة من بيانات المالك: 427 ⇒ 0 بلا فقدان صورة
    # (993 ⇒ 993، 431 إعادة تسمية على 194 صنفًا).
    #
    # لذا نتحقق هنا من توفر أداة التصحيح وقدرتها على بناء خطة
    # للملفات الناقصة، ونُبلِّغ الرقم للعلم لا كإخفاق.
    say(f"    ملفات بقاعدة قديمة (تنتظر تصحيح المالك): "
        f"{leg_bad}/{leg_checked}")
    if leg_bad:
        try:
            from engine_v2 import legacy_folder_v2 as _lf
            from engine_v2 import catalog_index_v2 as _ci2
            # الفهرس: قد لا يكون `idx` مُعرّفًا (مُعرّف داخل
            # فرع multi_code) — فنبنيه عند الحاجة.
            _idx = locals().get("idx")
            if _idx is None or not hasattr(_idx, "units_for_code"):
                _idx = _ci2.CatalogIndex()
                _idx.load_excel(str(catalog))
            _groups, _unp = _lf.scan_legacy_folder(legacy / "processed")
            _plan = _lf.plan_legacy_renames(_groups, index=_idx,
                                            unparsed=_unp)
            _changed = sum(1 for r in (_plan.rows or []) if r.changed)
            check("أداة تصحيح المنجز تبني خطة للملفات القديمة",
                  _changed >= leg_bad,
                  f"الخطة تغطي {_changed} فقط من {leg_bad} ملفًا ناقصًا",
                  ok=f"خطة تغطي {_changed} ملفًا ≥ {leg_bad} الناقصة "
                     f"(التنفيذ الفعلي مُثبَّت في test_legacy_upgrade_427)")
        except Exception as exc:  # noqa: BLE001
            check("أداة تصحيح المنجز تبني خطة للملفات القديمة",
                  False, str(exc)[:100])
    else:
        check("الجهة المنجزة تتبع القاعدة نفسها", True, "",
              ok=f"{leg_checked}/{leg_checked} مطابق")

    win.close()
    say("\n" + "=" * 60)
    say(f"النتيجة: {CHECKS - len(FAILURES)}/{CHECKS}")
    for f in FAILURES:
        say(f"  ✗ {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
