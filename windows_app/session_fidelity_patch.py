# -*- coding: utf-8 -*-
"""session_fidelity_patch — أمانة الجلسة واسترجاع العزل (م-5).

## البلاغ
«الرجوع الى الجلسات السابقة التي تم ربطها والعمل عليها وحفظها يوجد
فيها خلل… **لان العزل والخلفية البيضاء في جميع الصور ذهب**».

## العلة المقيسة — العزل لم يذهب، الجلسة تنساه
`BatchItemResult` فيه **18 حقلًا**، والجلسة تحفظ **ثمانية** فقط،
و**`output_path` ليس بينها** — وهو مسار الصورة المعزولة النهائية.
ثم عند الاستعادة يُكتب في مكانه:

```python
"review_path": str(_g(img, "output_path") or _sp)   # ← _sp = الخام!
```

فإذا خلا `output_path` (وهو يخلو لأنه لم يُحفظ) وقع الاحتياط على
**مسار الصورة الأصلية** ⇒ فتُعرض الصورة الخام بخلفية البلاط،
فيظن المالك أن العزل «ذهب». **وصور العزل سليمة على القرص كلها.**

## علة ثانية: `done_count` يتجاهل الربط اليدوي
يعدّ `matched/done/approved` فقط، والربط اليدوي يضع `manual` ⇒
عدّاد المنجز يقلّ عن الحقيقة فيظن المالك أن عمله ضاع.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = ["FULL_FIELDS", "DONE_STATUSES", "install_session_fidelity",
           "pick_display_path"]

# حقول `BatchItemResult` الثمانية عشر كاملة
FULL_FIELDS = (
    "source_path", "source_name", "status", "item_code", "product_name",
    "barcode", "confidence", "explanation", "output_path", "review_path",
    "match_source", "barcode_candidates", "warnings", "processing_ms",
    "foreground_method", "foreground_quality_score",
    "foreground_quality_status", "foreground_quality_metrics",
)

# الحالات التي تُعدّ «منجزة» — **مع الربط اليدوي**
DONE_STATUSES = {
    "matched", "done", "approved", "manual", "manual_linked",
    "linked", "edited", "primary",
}


def _exists(p: Any) -> bool:
    try:
        s = str(p or "")
        return bool(s) and Path(s).exists()
    except Exception:
        return False


def pick_display_path(output_path: str, review_path: str,
                      source_path: str) -> str:
    """يختار مسار العرض بأولوية صحيحة: **المعزول أولًا**.

    الأصل كان يسقط إلى الصورة الخام فورًا إذا خلا `output_path` —
    وهو ما جعل العزل «يذهب». هنا لا نسقط إلى الخام إلا إذا كان
    المعزول والمراجعة **مفقودين على القرص فعلًا**.
    """
    for cand in (output_path, review_path):
        if _exists(cand):
            return str(cand)
    for cand in (output_path, review_path):
        if str(cand or "").strip():
            return str(cand)
    return str(source_path or "")


def install_session_fidelity(main_window: Any) -> dict:
    """يركّب أمانة الجلسة: حفظ كامل واسترجاع صحيح وعدّاد سليم."""
    report: dict[str, Any] = {"save_wrapped": False,
                              "restore_wrapped": False,
                              "done_count_fixed": False}

    # ── 1. إكمال الحقول عند الحفظ ──
    save_fn = getattr(main_window, "v2_save_session", None)
    if callable(save_fn):
        def patched_save(name: str = "") -> Any:
            sid = save_fn(name) if name else save_fn()
            try:
                store = getattr(main_window, "v2_session_store", None)
                result = getattr(main_window, "current_result", None)
                if store is not None and result is not None:
                    for it in getattr(result, "items", []) or []:
                        key = (getattr(it, "source_name", "")
                               or getattr(it, "source_path", ""))
                        if not key:
                            continue
                        fields: dict[str, Any] = {}
                        for f in FULL_FIELDS:
                            if hasattr(it, f):
                                v = getattr(it, f)
                                if isinstance(v, (list, tuple)):
                                    v = list(v)
                                elif isinstance(v, dict):
                                    v = dict(v)
                                fields[f] = v
                        fields["item_name"] = getattr(it, "product_name", "")
                        fields["error"] = getattr(it, "explanation", "")
                        store.upsert_image(key, **fields)
                    store.save(force=True)
            except Exception:
                pass
            return sid

        patched_save._fidelity_patched = True
        main_window.v2_save_session = patched_save
        report["save_wrapped"] = True

    # ── 2. تصحيح مسارات العرض بعد الاستعادة ──
    restore_fn = getattr(main_window, "v2_restore_session", None)
    if callable(restore_fn):
        def patched_restore(state: Any) -> Any:
            out = restore_fn(state)
            try:
                result = getattr(main_window, "current_result", None)
                store = getattr(main_window, "v2_session_store", None)
                imgs: dict = {}
                if store is not None:
                    imgs = getattr(getattr(store, "state", None),
                                   "images", {}) or {}
                elif hasattr(state, "images"):
                    imgs = state.images or {}
                if result is not None and imgs:
                    for it in getattr(result, "items", []) or []:
                        key = (getattr(it, "source_name", "")
                               or getattr(it, "source_path", ""))
                        d = imgs.get(key) or {}
                        if not isinstance(d, dict):
                            continue
                        op = str(d.get("output_path", "") or "")
                        rp = str(d.get("review_path", "") or "")
                        sp = str(getattr(it, "source_path", "") or "")
                        best = pick_display_path(op, rp, sp)
                        if op:
                            try:
                                it.output_path = op
                            except Exception:
                                pass
                        if best:
                            try:
                                it.review_path = best
                            except Exception:
                                pass
                        for f in ("confidence", "match_source",
                                  "foreground_method",
                                  "foreground_quality_score",
                                  "foreground_quality_status"):
                            if f in d and hasattr(it, f):
                                try:
                                    setattr(it, f, d[f])
                                except Exception:
                                    pass
            except Exception:
                pass
            return out

        patched_restore._fidelity_patched = True
        main_window.v2_restore_session = patched_restore
        report["restore_wrapped"] = True

    # ── 3. عدّاد المنجز يعتدّ بالربط اليدوي ──
    try:
        from engine_v2.session_v2 import SessionState

        def done_count(self) -> int:
            done = 0
            for v in (self.images or {}).values():
                if not isinstance(v, dict):
                    continue
                st = str(v.get("status", "")).strip().lower()
                if st in DONE_STATUSES or v.get("approved"):
                    done += 1
                    continue
                if _exists(v.get("output_path")):
                    done += 1
            return done

        done_count._fidelity_patched = True
        SessionState.done_count = done_count
        report["done_count_fixed"] = True
    except Exception as exc:
        report["done_count_error"] = str(exc)

    return report
