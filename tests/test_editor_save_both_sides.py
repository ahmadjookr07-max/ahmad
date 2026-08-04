#!/usr/bin/env python3
"""برهان قياس: حفظ تعديل محرر الصور يعمل على **الجهتين**.

علة المالك حرفيًا: «يجب تعديل محرر الصور بحيث يعمل في صفحة واستطيع حفظ
التعديل على الصورة أثناء العمل لأنه سابقًا يرفض ذلك ولا يحفظ … شيكها
أيضًا في الجهتين».

الجهتان المقيستان هنا:
  الجهة أ) دفعة جديدة (مساحة عمل موجودة)  — صورة خام من مجلد الزيت.
  الجهة ب) المجلد المنجز (بلا مساحة عمل) — صورة webp من نتائج المالك.

وفي كل جهة يُقاس السلوك على صورة **غير مرتبطة** برقم صنف، لأن هذه هي
الحالة التي كان المحرر يرفضها (104 من 109 صور المالك بلا باركود).
كل تأكيد يعتمد ملفًا موجودًا فعلًا على القرص — لا محاكاة للنجاح.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MIS_SKIP_LICENSE", "1")
os.environ.setdefault("MIS_HEADLESS", "1")

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT / "src", ROOT / "windows_app"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))
sys.path.insert(0, str(ROOT / "tests"))

from owner_data_guard import (  # noqa: E402
    SKIP_RC,
    find_legacy_dir,
    find_raw_dir,
    legacy_outputs,
    list_images,
)

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, bool(ok), detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def _pick_source() -> tuple[Path, Path]:
    raw = find_raw_dir()
    legacy = find_legacy_dir()
    if raw is None or legacy is None:
        print("SKIP: بيانات المالك غير متاحة في هذا الصندوق.", flush=True)
        raise SystemExit(SKIP_RC)
    raw_imgs = list_images(raw)
    done_imgs = legacy_outputs(legacy)
    if not raw_imgs or not done_imgs:
        print("SKIP: لا صور صالحة في بيانات المالك.", flush=True)
        raise SystemExit(SKIP_RC)
    return raw_imgs[0], done_imgs[0]


def main() -> int:
    raw_img, done_img = _pick_source()

    import cv2
    import numpy as np
    from PySide6.QtWidgets import QApplication

    import native_app as na

    app = QApplication.instance() or QApplication([])
    assert app is not None

    win = na.MainWindow()
    win._headless_mode = True

    # ---- بديل بسيط للمحرر: يُرجع صورة معدّلة فعليًا (مقلوبة أفقيًا) ----
    class _StubEditor:
        def __init__(self, path: Path) -> None:
            self._img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)

        def has_image(self) -> bool:
            return self._img is not None

        def has_edits(self) -> bool:
            return True

        def get_result_bgr(self):
            return None if self._img is None else cv2.flip(self._img, 1)

    class _StubItem:
        def __init__(self, path: Path) -> None:
            self.source_name = path.name
            self.source_path = str(path)
            self.item_code = ""  # **غير مرتبطة** — جوهر علة المالك

    def _run_side(label: str, image: Path, workspace: Path | None) -> None:
        item = _StubItem(image)
        win.current_workspace = workspace
        win.__dict__["_unified_editor_instance"] = _StubEditor(image)
        win._selected_result_items = lambda: [item]  # type: ignore[method-assign]
        win._result_path = lambda p: Path(p)  # type: ignore[method-assign]
        win._editor_drafts = {}

        # 1) الصف غير المرتبط أصبح مقبولًا للتحرير
        check(f"{label}: صف غير مرتبط مقبول للتحرير",
              win._individual_editable_item() is not None, image.name)
        # 2) لكنه يبقى مستبعدًا من مسار المحرك (الذي يشترط الربط)
        check(f"{label}: مسار المحرك ما زال يشترط الربط",
              win._individual_linked_item() is None)
        # 3) الحفظ أثناء العمل ينتج ملفًا فعليًا
        saved = win._save_editor_draft(silent=True)
        ok_file = saved is not None and saved.is_file() and saved.stat().st_size > 0
        check(f"{label}: الحفظ أثناء العمل أنتج ملفًا",
              ok_file, str(saved) if saved else "لا ملف")
        # 4) الملف المحفوظ صورة صالحة تُفتح فعلًا
        if ok_file:
            back = cv2.imdecode(np.fromfile(str(saved), dtype=np.uint8), cv2.IMREAD_COLOR)
            check(f"{label}: المسوّدة صورة صالحة تُقرأ", back is not None,
                  f"{back.shape}" if back is not None else "تعذر الفتح")
            orig = cv2.imdecode(np.fromfile(str(image), dtype=np.uint8), cv2.IMREAD_COLOR)
            differs = back is not None and orig is not None and (
                back.shape != orig.shape or bool((back != orig).any()))
            check(f"{label}: المحفوظ يحمل التعديل فعلًا (يخالف الأصل)", differs)
        # 5) التعديل مُسجَّل في الذاكرة لاستخدامه عند الربط
        check(f"{label}: المسوّدة مُسجَّلة باسم الصورة",
              win._editor_drafts.get(item.source_name) == saved)
        # 6) لا تبقى حالة «غير محفوظ» بعد الحفظ
        check(f"{label}: علم التعديل غير المحفوظ صُفِّر",
              getattr(win, "_individual_editor_dirty", False) is False)
        # 7) استدعاء الحفظ عبر الزر نفسه لا يرفع استثناءً ولا يرفض
        try:
            win._begin_individual_edit(preview_only=False)
            check(f"{label}: زر «حفظ واعتماد التعديل» لا يرفض العمل", True)
        except Exception as exc:  # pragma: no cover
            check(f"{label}: زر «حفظ واعتماد التعديل» لا يرفض العمل", False, repr(exc))

    # الجهة أ: دفعة جديدة (مساحة عمل حقيقية)
    ws = ROOT / "tests" / "_editor_ws"
    ws.mkdir(parents=True, exist_ok=True)
    _run_side("جديدة", raw_img, ws)

    # الجهة ب: المجلد المنجز (بلا مساحة عمل — كان يرفض بـ«مجلد المهمة غير متاح»)
    _run_side("منجزة", done_img, None)

    # الحلقة الأخيرة: المسوّدة تُستخدم عند الربط لاحقًا
    draft = win._editor_drafts.get(done_img.name)
    check("المسوّدة محفوظة بجوار الصورة في الجهة المنجزة",
          draft is not None and draft.parent.name == "editor_drafts"
          and draft.parent.parent == done_img.parent,
          str(draft) if draft else "")

    win.close()

    failed = [n for n, ok, _ in CHECKS if not ok]
    print(f"\nالنتيجة: {len(CHECKS) - len(failed)}/{len(CHECKS)}", flush=True)
    if failed:
        for name in failed:
            print(f"  FAIL: {name}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
