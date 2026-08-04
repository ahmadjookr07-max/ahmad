# -*- coding: utf-8 -*-
"""جهة التعديل القديمة على مجلد المالك المنجز **الحقيقي**.

سبب وجود هذا الملف: ``test_legacy_folder_unified`` يعلن نجاحًا كاملًا
لكنه يعمل على أصول مصنّعة داخل ``mkdtemp`` بأسماء وهمية (``555_كرتون``،
``99999_حبه``) ولا يلمس مجلد المالك المنجز إطلاقًا. فالنجاح صحيح شكلًا
ولا يبرهن شيئًا عن الملفات الحقيقية — وهذا نمط «الثقة الزائفة» بعينه.

هذا الاختبار يعمل على **نسخة من مجلد المالك المنجز الفعلي** (993 ملفًا)
مع **كتالوجه الحقيقي** (50,311 صنفًا)، ويغلق:

* A3 — حفظ التعديل: حالة المهمة تُكتب فعلًا في المجلد المنجز، وبلا
  ذلك يفشل تعديل الباركود بـ``FileNotFoundError``.
* A6 — محرر الصور: يُفتح على عنصر من المجلد المنجز ويعمل.
* N — التسميات: النمط ``{item_code}_{وحدة}`` و``-{n}`` للتسلسل،
  الإكسل مرجع الوحدة، لا فقد ملفات، لا تصادم أسماء.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows_app"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MIS_SKIP_LICENSE", "1")
os.environ.setdefault("MIS_HEADLESS", "1")

from owner_data_guard import (find_catalog, find_legacy_dir,  # noqa: E402
                              skip)

OK = FAIL = 0


def say(msg: str) -> None:
    print(msg, flush=True)


def check(label: str, cond: bool, detail: str = "") -> bool:
    global OK, FAIL
    if cond:
        OK += 1
        say(f"  ✓ {label}" + (f" — {detail}" if detail else ""))
    else:
        FAIL += 1
        say(f"  ✗ {label}" + (f" — {detail}" if detail else ""))
    return bool(cond)


def main() -> int:
    catalog = find_catalog()
    legacy = find_legacy_dir()
    if catalog is None or legacy is None:
        skip("يحتاج كتالوج المالك ومجلده المنجز الحقيقي")

    say(f"الكتالوج: {catalog}")
    say(f"المجلد المنجز الأصلي: {legacy}")

    # نسخة عمل: لا نلمس بيانات المالك الأصلية أبدًا.
    tmp = Path(tempfile.mkdtemp(prefix="legacy_real_"))
    work = tmp / "منجز"
    src_imgs = sorted([p for p in Path(legacy).rglob("*")
                       if p.suffix.lower() in {".webp", ".jpg", ".jpeg", ".png"}])
    if not src_imgs:
        skip("لا صور في المجلد المنجز")
    work.mkdir(parents=True, exist_ok=True)
    for p in src_imgs:
        shutil.copy2(p, work / p.name)
    before = sorted(q.name for q in work.iterdir() if q.is_file())
    say(f"نسخة العمل: {len(before)} ملفًا في {work}")

    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])

        import native_app
        # لا نوافذ حوارية تحجب الاختبار.
        native_app.QMessageBox.information = staticmethod(
            lambda *a, **k: None)
        native_app.QMessageBox.warning = staticmethod(lambda *a, **k: None)
        native_app.QMessageBox.critical = staticmethod(lambda *a, **k: None)

        win = native_app.MainWindow()

        say("\n[1] تحميل الكتالوج الحقيقي (مرجع الوحدة)")
        # 2.9.7: كان يكتفي بـ`_register_catalog_index` الخلفي ثم
        # يدور 400 دورة `processEvents` — وهي لا تسلّم خيطًا
        # خلفيًا يقرأ 22,087 صنفًا، فيبقى الفهرس None.
        # نستخدم الضمان المتزامن نفسه الذي صار التطبيق
        # يستدعيه قبل كل دفعة — فيختبر المسار الحقيقي.
        win.catalog_path = Path(catalog)
        win._register_catalog_index(Path(catalog))
        ensured = win._ensure_catalog_index()
        idx = getattr(win, "v2_catalog_index", None)
        say(f"    الضمان المتزامن أرجع: {ensured}")
        check("فُهرس الكتالوج الحقيقي", idx is not None,
              f"{getattr(idx, 'size', lambda: '?')() if hasattr(idx, 'size') else type(idx).__name__}")

        say("\n[2] فتح المجلد المنجز الحقيقي (تصحيح فوري بلا زر تطبيق)")
        win._load_legacy_folder(work, announce=False)
        for _ in range(200):
            app.processEvents()

        res = getattr(win, "current_result", None)
        items = list(getattr(res, "items", []) or []) if res else []
        check("بُنيت نتيجة من المجلد المنجز", len(items) > 0,
              f"{len(items)} عنصرًا")
        check("مساحة العمل صارت المجلد المنجز",
              str(getattr(win, "current_workspace", "")) == str(work))

        say("\n[3] A3 — حفظ التعديل: حالة المهمة مكتوبة على القرص")
        states = list(work.rglob("*.json"))
        check("ملف حالة موجود في المجلد المنجز", len(states) > 0,
              ", ".join(s.name for s in states[:3]) or "لا شيء")
        if states:
            import json
            payload = {}
            for s in states:
                try:
                    d = json.loads(s.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if isinstance(d, dict) and "result" in d:
                    payload = d
                    break
            check("الحالة تحمل نتيجة قابلة للاستئناف",
                  bool(payload.get("result")),
                  f"مفاتيح: {list(payload)[:6]}")
            check("الحالة تحمل مسار الكتالوج (الإكسل مرجع كل شيء)",
                  bool(payload.get("catalog_path")))

        say("\n[4] N — التسميات على ملفات المالك الحقيقية")
        after = sorted(q.name for q in work.iterdir() if q.is_file()
                       and q.suffix.lower() != ".json")
        imgs_after = [n for n in after if Path(n).suffix.lower() in
                      {".webp", ".jpg", ".jpeg", ".png"}]
        check("لا فقد ولا تكرار ملفات",
              len(imgs_after) == len(before),
              f"{len(before)} ⇒ {len(imgs_after)}")
        check("لا ملفات مؤقتة متبقية",
              not any(n.startswith("~") or n.endswith(".tmp")
                      for n in after))
        # النمط: {رقم}_{وحدة}[_وحدة…][-{تسلسل}]
        #
        # 2.9.7 — تصحيح اختبار مقلوب: كان النمط يرفض الوحدات
        # المتعددة (`10000014_حبه_باكت`) فيعدّ الصحيح شاذًا — مع
        # أن سياسة المالك المعتمدة (join_all_units، 2.9.6) توجب
        # إدراج **كل** وحدات الصنف مفصولة بشرطة سفلية.
        # ويُستثنى ملف مسودة المحرر `*.edited.png` لأنه ملف
        # عمل لا ناتج مُسمّى (يولّده زر «حفط واعتماد التعديل»).
        #
        # ويُقبل الرقم **داخل** اسم الوحدة لأن كتالوج المالك
        # يحوي فعلًا وحدة اسمها `كرتون 1` (تُكتب `كرتون١`
        # بعد حذف المسافة وفق قاعدة المالك)، فاسم مشروع مثل
        # `10000051_حبه_كرتون_كرتو١1` كان يُرفض بلا موجب.
        # لكن مقطعًا **رقميًا محضًا** يبقى مرفوضًا (`10000121_4`).
        import re
        pat = re.compile(r"^\d+_(?!\d+(?:_|$))[^\-]+(?:-\d+)?$")

        def _ok(stem: str) -> bool:
            if not pat.match(stem):
                return False
            # لا يجوز أن يكون أي مقطع وحدة رقمًا محضًا
            body = stem.split("-")[0]
            parts = body.split("_")[1:]
            return bool(parts) and not any(p.strip().isdigit() for p in parts)

        bad = [n for n in imgs_after
               if not n.lower().endswith(".edited.png")
               and not _ok(Path(n).stem)]
        check("كل الأسماء على قاعدة {رقم}_{وحدة}[_وحدة…][-{تسلسل}]",
              len(bad) == 0, f"{len(bad)} شاذًا: {bad[:5]}")
        # النمط القديم _N (شرطة سفلية قبل الرقم) يجب أن يزول
        old = [n for n in imgs_after
               if re.match(r"^\d+_[^\d\-_]+_\d+$", Path(n).stem)]
        check("لا أثر للنمط القديم {رقم}_{وحدة}_{تسلسل}",
              len(old) == 0, f"{len(old)}: {old[:5]}")
        check("لا تصادم أسماء (كلها فريدة)",
              len(set(imgs_after)) == len(imgs_after))
        say(f"    أمثلة: {imgs_after[:5]}")

        say("\n[5] A6 — محرر الصور يُفتح على عنصر من المجلد المنجز")
        opened = False
        detail = ""
        if win.results_table.rowCount():
            win.results_table.selectRow(0)
            app.processEvents()
            for name in ("edit_image_button", "individual_edit_button"):
                btn = getattr(win, name, None)
                if btn is not None and btn.isEnabled():
                    try:
                        btn.click()
                        app.processEvents()
                        opened = True
                        detail = name
                        break
                    except Exception as exc:      # pragma: no cover
                        detail = f"{name}: {exc}"
            if not opened:
                # المسار المباشر إن كان الزر معطّلًا في وضع الرأس المغلق
                fn = getattr(win, "_open_individual_editor", None) or \
                     getattr(win, "_edit_selected_image", None)
                if callable(fn):
                    try:
                        fn()
                        app.processEvents()
                        opened = True
                        detail = "مسار مباشر"
                    except Exception as exc:
                        detail = f"استثناء: {exc}"
        check("محرر الصور يعمل على المجلد المنجز", opened, detail)

        say("\n[6] ★ اختيار صورة الواجهة على المجلد المنجز")
        star = getattr(win, "set_primary_button", None)
        star_ok = False
        sdetail = ""
        if star is not None and win.results_table.rowCount():
            win.results_table.selectRow(0)
            app.processEvents()
            try:
                star.click()
                app.processEvents()
                star_ok = True
                sdetail = "بلا استثناء"
            except Exception as exc:
                sdetail = str(exc)
        check("زر ★ يعمل بلا انهيار", star_ok, sdetail)

        try:
            win.close()
        except Exception:
            pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    say("\n" + "═" * 62)
    say(f"النتيجة: {OK}/{OK + FAIL}")
    if FAIL:
        say(f"فشل: {FAIL}")
        return 1
    say("كل الفحوص نجحت على بيانات المالك الحقيقية ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
