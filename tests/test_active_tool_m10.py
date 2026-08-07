# -*- coding: utf-8 -*-
"""م-10 — مؤشر الأداة النشطة في المحرر.

بلاغ المالك: يضغط زر أداة ثم يرسم فلا يحدث ما يتوقعه، أو يرسم وهو
يظن أداة والفعل لأخرى. السبب أن حالة الأداة كانت تُرى في لون حافة
الزر وحده، والأزرار في لوحة «أدوات متقدمة» قد تكون **مطوية** أو
جانبية، وعين المستخدم على الصورة لا على الأزرار.

الفحص الحاسم هنا ليس وجود لافتة، بل أنها في **الواجهة المعروضة
فعلًا**: `UnifiedEditorWidget` يستبدل `_build_ui` بالكامل، فلافتة
مضافة إلى شريط `photo_editor_v2` وحده لا يراها المستخدم إطلاقًا.
لذا يُبنى المحرر الموحد نفسه ويُتحقق أن اللافتة داخل شجرة ودجتاته.
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
    print("م-10 — مؤشر الأداة النشطة")
    print("=" * 62)

    import shutil
    import tempfile

    import cv2
    import numpy as np
    from PySide6.QtWidgets import QApplication, QLabel

    app = QApplication.instance() or QApplication([])

    from photo_editor_v2 import EditorCanvas
    from unified_editor import UnifiedEditorWidget

    ed = UnifiedEditorWidget()

    # ---------------------------------------- اللافتة في الواجهة المعروضة
    label = getattr(ed, "active_tool_label", None)
    check("مؤشر الأداة موجود في المحرر الموحد", isinstance(label, QLabel))
    if label is None:
        print(f"نجح {PASS} / فشل {FAIL}")
        return 1

    # الفحص الجوهري: اللافتة **ضمن شجرة ودجتات المحرر المعروض**
    parents = []
    node = label.parentWidget()
    while node is not None:
        parents.append(node)
        node = node.parentWidget()
    check("المؤشر داخل شجرة المحرر الموحد لا في حوار غير معروض",
          ed in parents, f"({[type(p).__name__ for p in parents][:3]})")
    check("المؤشر ليس مخفيًا بخاصية hidden", not label.isHidden())

    # ---------------------------------------- الحالة الابتدائية غير فارغة
    check("المؤشر لا يبدأ فارغًا", label.text().strip() != "",
          f"({label.text()!r})")
    check("المؤشر يبدأ على أداة التحريك", "تحريك" in label.text(),
          f"({label.text()!r})")
    check("لون خلفية مضبوط لا نص عارٍ", "background" in label.styleSheet())

    # ---------------------------------------- كل أداة لها وصف كامل
    info = ed.TOOL_INFO
    tools = [EditorCanvas.TOOL_PAN, EditorCanvas.TOOL_ERASE,
             EditorCanvas.TOOL_RESTORE, EditorCanvas.TOOL_REGION,
             EditorCanvas.TOOL_REGION_RECT, EditorCanvas.TOOL_DATE_BLUR]
    check("كل الأدوات الست موصوفة", all(t in info for t in tools),
          f"(الناقص {[t for t in tools if t not in info]})")
    for t in tools:
        name, color, hint = info[t]
        check(f"وصف مكتمل: {t}",
              bool(name) and color.startswith("#") and len(hint) > 10,
              f"({name!r},{color!r},{hint!r})")

    # الألوان تطابق دائرة الفرشاة على اللوحة (أحمر تبييض، أخضر استرجاع)
    check("لون التبييض أحمر كدائرة الفرشاة",
          info[EditorCanvas.TOOL_ERASE][1].lower().startswith("#d"))
    check("لون الاسترجاع أخضر كدائرة الفرشاة",
          info[EditorCanvas.TOOL_RESTORE][1].lower().startswith("#1"))

    # ---------------------------------------- المؤشر يتبع الأداة فعليًا
    for tool in tools:
        ed.canvas.set_tool(tool)
        ed._update_active_tool_label()
        expected = info[tool][0]
        check(f"المؤشر يعرض «{expected}» بعد تعيين {tool}",
              expected in label.text(), f"({label.text()!r})")
        check(f"التلميح يشرح فعل الماوس لـ{tool}",
              label.toolTip() == info[tool][2])

    # ---------------------------------------- الضغط على زر يُحدّث المؤشر
    ed._pick_tool(EditorCanvas.TOOL_ERASE, True, ed.erase_btn)
    check("ضغط زر التبييض يُحدّث المؤشر",
          "قلم تبييض" in label.text(), f"({label.text()!r})")
    check("والأداة الفعلية على اللوحة تبدّلت",
          ed.canvas._tool == EditorCanvas.TOOL_ERASE)

    ed._pick_tool(EditorCanvas.TOOL_RESTORE, True, ed.restore_btn)
    check("التبديل إلى الاسترجاع يتبعه المؤشر",
          "استرجاع" in label.text(), f"({label.text()!r})")

    # إطفاء كل الأزرار يعيد التحريك — والمؤشر يتبع
    for b in (ed.erase_btn, ed.restore_btn, ed.region_brush_btn,
              ed.region_rect_btn, ed.date_blur_btn):
        b.blockSignals(True)
        b.setChecked(False)
        b.blockSignals(False)
    ed._pick_tool(EditorCanvas.TOOL_RESTORE, False, ed.restore_btn)
    check("إطفاء الأدوات يرجع المؤشر إلى تحريك",
          "تحريك" in label.text(), f"({label.text()!r})")
    check("والأداة الفعلية رجعت إلى التحريك",
          ed.canvas._tool == EditorCanvas.TOOL_PAN)

    # ---------------------------------------- تحميل صورة يُضبط المؤشر
    work = Path(tempfile.mkdtemp(prefix="m10_"))
    p = work / "t.png"
    cv2.imwrite(str(p), np.full((120, 160, 3), 200, np.uint8))
    ed.canvas.set_tool(EditorCanvas.TOOL_ERASE)
    ed.load_image(str(p))
    check("تحميل صورة يُبقي المؤشر صادقًا لا فارغًا",
          label.text().strip() != "", f"({label.text()!r})")

    # -------------------- الفحص السلبي: هل كانت اللافتة غائبة قبلًا؟
    src_unified = (ROOT / "windows_app" / "unified_editor.py").read_text(
        encoding="utf-8")
    src_editor = (ROOT / "windows_app" / "photo_editor_v2.py").read_text(
        encoding="utf-8")
    check("سلبي: المؤشر مضاف إلى info_row المعروض",
          "info_row.addWidget(self.active_tool_label)" in src_unified)
    check("_pick_tool يستدعي التحديث في كلا فرعيه",
          src_editor.count("_update_active_tool_label(") >= 3)
    check("التهيئة الأولى تُستدعى بعد ربط الأزرار",
          "_wire_manual_buttons(self)" in src_editor
          and src_editor.index("_wire_manual_buttons(self)")
          < src_editor.rindex("_update_active_tool_label()"))

    ed.close()
    shutil.rmtree(work, ignore_errors=True)

    print("=" * 62)
    print(f"نجح {PASS} / فشل {FAIL}")
    if FAIL == 0:
        print("الأداة النشطة ظاهرة دائمًا في مسار بصر المستخدم")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
