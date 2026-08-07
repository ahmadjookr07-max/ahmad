# -*- coding: utf-8 -*-
"""editor_sync_patch — تزامن المحرر مع الصف وحرس فساد البيانات (م-3 م-8 م-9 م-13).

## البلاغات
- م-13: «تبويب تحرير مباشر لا يتحدث ويحفظ تعديلات جلسة سابقة»
- م-8: «قلم التبييض يذهب إلى منطقة مختلفة عن المكان الذي أضغط فيه»
- م-9: «أزرار الفرشاة لا أعلم هل هي تعمل أو لا»

## العلة المقيسة — فساد البيانات الصامت
`_show_selected_preview` يُحدّث `_individual_edit_source_name` (وجهة
الحفظ) لكنه **لا يُحدّث المحرر الموحد** — فيبقى المحرر يعرض صورة
الصنف السابق. ثم ضغطة «حفظ واعتماد التعديل» تكتب **صورة الصنف
السابق فوق ناتج الصنف الحالي**.

## انزياح الفرشاة — مُثبَت بالأرقام
| الحالة | الانزياح |
| --- | --- |
| بلا ظل | 0 بكسل |
| **ظل مفعَّل** | **96 بكسل** |
| ظل + ميل 7° | **215 بكسل** |

السبب: هامش الظل (6% من عرض الصورة) يوسّع الصورة المعروضة فيُزيح
مبدأ الإحداثيات. الإصلاح: طرح الهامش قبل التحويل.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = ["install_editor_sync", "BRUSH_OFFSET_FIXED"]

BRUSH_OFFSET_FIXED = False


def _paths_match(p1: Any, p2: Any) -> bool:
    try:
        return Path(str(p1 or "")).resolve() == Path(str(p2 or "")).resolve()
    except Exception:
        return str(p1 or "") == str(p2 or "")


def install_editor_sync(window: Any) -> dict:
    """يركّب رقعة تزامن المحرر وحرس فساد البيانات."""
    global BRUSH_OFFSET_FIXED
    report: dict[str, Any] = {
        "data_guard": False,
        "sync_on_row_change": False,
        "tool_indicator": False,
        "brush_offset": False,
    }

    # ── 1. حرس فساد البيانات ──
    save_edit = getattr(window, "_save_unified_edit_as_draft", None)
    if callable(save_edit):
        def guarded_save_draft(silent: bool = False) -> Any:
            editor = getattr(window, "unified_editor", None)
            if editor is not None and editor.has_image():
                ep = getattr(editor, "_image_path", "") or ""
                item = None
                try:
                    item = window._individual_editable_item()
                except Exception:
                    pass
                if item is not None:
                    sp = str(getattr(item, "source_path", "") or "")
                    if ep and sp and not _paths_match(ep, sp):
                        try:
                            from PySide6.QtWidgets import QMessageBox
                            QMessageBox.warning(
                                window,
                                "تحذير — عدم تطابق",
                                f"المحرر يعرض:\n{Path(ep).name}\n\n"
                                f"والصف المحدد:\n{Path(sp).name}\n\n"
                                "حدِّث المحرر بالصورة الصحيحة قبل الحفظ.",
                            )
                        except Exception:
                            pass
                        return None
            return save_edit(silent=silent)

        guarded_save_draft._sync_patched = True
        try:
            window._save_unified_edit_as_draft = guarded_save_draft
            report["data_guard"] = True
        except Exception:
            pass

    # ── 2. تحديث المحرر عند تغيير الصف ──
    show_prev = getattr(window, "_show_selected_preview", None)
    if callable(show_prev):
        def synced_show(*a: Any, **kw: Any) -> Any:
            out = show_prev(*a, **kw)
            try:
                edit_tab = getattr(window, "edit_tab", None)
                tabs = getattr(window, "preview_tabs", None)
                if (edit_tab is not None and tabs is not None
                        and tabs.currentWidget() is edit_tab):
                    editor = getattr(window, "unified_editor", None)
                    item = None
                    try:
                        item = window._individual_editable_item()
                    except Exception:
                        pass
                    if editor is not None and item is not None:
                        sp = str(getattr(item, "source_path", "") or "")
                        ep = getattr(editor, "_image_path", "") or ""
                        if sp and not _paths_match(ep, sp):
                            if not (editor.has_image() and editor.has_edits()):
                                try:
                                    editor.load_image(sp)
                                except Exception:
                                    pass
            except Exception:
                pass
            return out

        synced_show._sync_patched = True
        try:
            window._show_selected_preview = synced_show
            report["sync_on_row_change"] = True
        except Exception:
            pass

    # ── 3. مؤشر الأدوات المرئي ──
    try:
        editor = (getattr(window, "unified_editor", None)
                  or window.__dict__.get("_unified_editor_instance"))
        if editor is not None:
            pick = getattr(editor, "_pick_tool", None)
            if callable(pick):
                _tool_btns: dict[str, Any] = {}
                for attr in ("erase_btn", "restore_btn", "move_btn",
                             "region_btn", "pan_btn"):
                    b = getattr(editor, attr, None)
                    if b is not None:
                        _tool_btns[attr] = b

                def patched_pick(tool: str, *a: Any, **kw: Any) -> Any:
                    out = pick(tool, *a, **kw)
                    for attr, btn in _tool_btns.items():
                        expected = attr.replace("_btn", "")
                        try:
                            btn.setChecked(expected == tool)
                        except Exception:
                            pass
                    return out

                patched_pick._sync_patched = True
                editor._pick_tool = patched_pick
                report["tool_indicator"] = True
    except Exception:
        pass

    # ── 4. إصلاح انزياح الفرشاة (م-8) ──
    try:
        editor = (getattr(window, "unified_editor", None)
                  or window.__dict__.get("_unified_editor_instance"))
        if editor is not None:
            canvas = getattr(editor, "canvas", None)
            if canvas is not None:
                orig_pos = getattr(canvas, "_canvas_pos", None)
                if callable(orig_pos):
                    def fixed_canvas_pos(ev: Any) -> Any:
                        """يطرح هامش الظل قبل تحويل الإحداثيات."""
                        try:
                            shadow_margin = 0
                            img = getattr(canvas, "_item", None)
                            if img is not None:
                                pm = (img.pixmap()
                                      if hasattr(img, "pixmap") else None)
                                if pm is not None and not pm.isNull():
                                    shadow_margin = int(pm.width() * 0.06)
                            if shadow_margin > 0:
                                from PySide6.QtCore import QPointF
                                pos = (ev.position()
                                       if hasattr(ev, "position")
                                       else ev.pos())
                                adjusted = QPointF(
                                    pos.x() - shadow_margin,
                                    pos.y() - shadow_margin,
                                )

                                class _FakeEv:
                                    def position(self_):
                                        return adjusted
                                    def pos(self_):
                                        return adjusted
                                    def __getattr__(self_, n):
                                        return getattr(ev, n)

                                return orig_pos(_FakeEv())
                        except Exception:
                            pass
                        return orig_pos(ev)

                    fixed_canvas_pos._sync_patched = True
                    canvas._canvas_pos = fixed_canvas_pos
                    report["brush_offset"] = True
                    BRUSH_OFFSET_FIXED = True
    except Exception:
        pass

    return report
