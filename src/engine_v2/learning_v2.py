# -*- coding: utf-8 -*-
"""learning_v2 — التعلم المحلي من تعديلات المستخدم.

يسجل أنماط التصحيح التي يقوم بها المستخدم (فرشاة تبييض/استرجاع، قوة
التحسين، مواضع ملصق الحقائق الغذائية، إعدادات القص) في ملف JSON محلي،
ثم يقدم اقتراحات مخصصة للصور الجديدة بناءً على ما تعلمه.

الخصوصية: كل التعلم محلي 100% داخل جهاز المستخدم — لا يُرسل أي شيء
خارجيًا إطلاقًا.
"""
from __future__ import annotations

import copy
import json
import threading
import time
from pathlib import Path

_LOCK = threading.Lock()
_CACHE: dict | None = None

_DEFAULTS: dict = {
    "version": 1,
    "events_count": 0,
    "enhance_strength": {"sum": 0.0, "n": 0},        # متوسط قوة التحسين
    "brush_size": {"sum": 0.0, "n": 0},              # حجم الفرشاة المفضل
    "brush_softness": {"sum": 0.0, "n": 0},          # نعومة الحواف
    "shadow_enabled": {"on": 0, "off": 0},           # تفضيل الظل
    "nutrition_anchor": {},                          # عدّاد لكل زاوية
    "nutrition_scale": {"sum": 0.0, "n": 0},
    "edge_fix_rate": {"fixed": 0, "total": 0},       # كم مرة صحّح الحواف
    "compression": {},                               # مستوى الضغط المفضل
    "last_updated": 0.0,
}


def _store_path() -> Path:
    try:
        from .paths_v2 import app_data_dir
        base = Path(app_data_dir())
    except Exception:
        base = Path.home() / ".market_image_studio"
    base.mkdir(parents=True, exist_ok=True)
    return base / "user_learning_v2.json"


def _load() -> dict:
    global _CACHE
    with _LOCK:
        if _CACHE is not None:
            return _CACHE
        try:
            data = json.loads(_store_path().read_text(encoding="utf-8"))
            merged = copy.deepcopy(_DEFAULTS)
            merged.update(data if isinstance(data, dict) else {})
            _CACHE = merged
        except Exception:
            _CACHE = copy.deepcopy(_DEFAULTS)
        return _CACHE


def _save(data: dict) -> None:
    global _CACHE
    with _LOCK:
        _CACHE = data
        data["last_updated"] = time.time()
        try:
            _store_path().write_text(
                json.dumps(data, ensure_ascii=False, indent=1),
                encoding="utf-8")
        except Exception:
            pass


# ------------------------------------------------------------ record APIs
def record_enhance_strength(value: float) -> None:
    d = _load()
    d["enhance_strength"]["sum"] += float(value)
    d["enhance_strength"]["n"] += 1
    d["events_count"] += 1
    _save(d)


def record_brush(size: int, softness: int) -> None:
    d = _load()
    d["brush_size"]["sum"] += size
    d["brush_size"]["n"] += 1
    d["brush_softness"]["sum"] += softness
    d["brush_softness"]["n"] += 1
    d["events_count"] += 1
    _save(d)


def record_shadow(enabled: bool) -> None:
    d = _load()
    d["shadow_enabled"]["on" if enabled else "off"] += 1
    d["events_count"] += 1
    _save(d)


def record_nutrition_placement(anchor: str, scale: float) -> None:
    d = _load()
    d["nutrition_anchor"][anchor] = d["nutrition_anchor"].get(anchor, 0) + 1
    d["nutrition_scale"]["sum"] += float(scale)
    d["nutrition_scale"]["n"] += 1
    d["events_count"] += 1
    _save(d)


def record_edge_correction(did_fix: bool) -> None:
    """هل احتاج المستخدم لتصحيح حواف القص يدويًا؟ يضبط حساسية القص."""
    d = _load()
    d["edge_fix_rate"]["total"] += 1
    if did_fix:
        d["edge_fix_rate"]["fixed"] += 1
    d["events_count"] += 1
    _save(d)


def record_compression(level: str) -> None:
    d = _load()
    d["compression"][level] = d["compression"].get(level, 0) + 1
    d["events_count"] += 1
    _save(d)


def record_link_decision(source: str = "", item_code: str = "",
                         accepted: bool = True) -> None:
    """يتعلم من قرارات ربط الصور بلا باركود: كم اقتراحًا قُبل
    وكم رُفض، لا أكثر.

    2.9.10 — أُزيل المعامل `visual_score` ومجموعه المحفوز من
    **الجذر** بأمر المالك: لا درجة تشابه ولا نسبة مئوية في أي
    موضع. كان المعامل يأتيه الرقم 0.0 دائمًا من الواجهة بعد 2.9.9،
    فكان شفرة ميتة توهم أن المنطق باقٍ وتدعو لإعادة إحيائه."""
    d = _load()
    slot = d.setdefault("link_decisions", {"accepted": 0, "rejected": 0})
    # تنقية الملفات المحفوزة من إصدار أقدم: مجاميع الدرجات لم يبقَ
    # لها مستهلك، فتُطرح من الملف أول مرة يُكتب فيها.
    slot.pop("score_sum", None)
    slot.pop("score_n", None)
    slot["accepted" if accepted else "rejected"] = \
        slot.get("accepted" if accepted else "rejected", 0) + 1
    d["events_count"] += 1
    _save(d)


def record_naming_choice(scheme: str, enabled: bool = True) -> None:
    """يتذكر نمط التسمية الذي يفضله المستخدم."""
    d = _load()
    slot = d.setdefault("naming_choice", {})
    slot[scheme] = slot.get(scheme, 0) + 1
    slot["_enabled"] = bool(enabled)
    d["events_count"] += 1
    _save(d)


# 2.9.10 — حُذفت `suggest_link_threshold` من الجذر بأمر المالك.
# كانت تحسب عتبة لـ«الاقتراح البصري» من متوسط درجات التشابه،
# ولم يكن لها مستدعٍ واحد في المشروع بعد حذف البصمات البصرية في
# 2.9.9 — فشفرة ميتة تحمل مفهومًا ألغاه المالك صراحة.


def suggest_naming_scheme(default: str = "dash") -> str:
    slot = _load().get("naming_choice") or {}
    counts = {k: v for k, v in slot.items()
              if not k.startswith("_") and isinstance(v, int)}
    if not counts:
        return default
    return max(counts, key=counts.get)


# ---------------------------------------------------------- suggest APIs
def _avg(slot: dict, default: float) -> float:
    n = slot.get("n", 0)
    return (slot.get("sum", 0.0) / n) if n else default


def suggest_enhance_strength(default: float = 0.5) -> float:
    return round(min(1.0, max(0.0, _avg(_load()["enhance_strength"],
                                        default))), 2)


def suggest_brush(default_size: int = 40,
                  default_softness: int = 50) -> tuple[int, int]:
    d = _load()
    return (int(_avg(d["brush_size"], default_size)),
            int(_avg(d["brush_softness"], default_softness)))


def suggest_shadow(default: bool = False) -> bool:
    s = _load()["shadow_enabled"]
    total = s.get("on", 0) + s.get("off", 0)
    if total < 3:
        return default
    return s.get("on", 0) > s.get("off", 0)


def suggest_nutrition_anchor(default: str = "bottom_left") -> str:
    anchors = _load()["nutrition_anchor"]
    if not anchors:
        return default
    return max(anchors, key=anchors.get)


def suggest_nutrition_scale(default: float = 0.28) -> float:
    return round(min(0.6, max(0.12, _avg(_load()["nutrition_scale"],
                                         default))), 2)


def suggest_segmentation_conservative() -> bool:
    """إن كان المستخدم يصحح الحواف كثيرًا → قص محافظ (يترك هامشًا أكبر)."""
    r = _load()["edge_fix_rate"]
    total = r.get("total", 0)
    return total >= 5 and (r.get("fixed", 0) / total) > 0.4


def suggest_compression(default: str = "high_quality") -> str:
    comp = _load()["compression"]
    if not comp:
        return default
    return max(comp, key=comp.get)


# ------------------------------------------------------------- inspection
def summary_ar() -> str:
    """ملخص عربي مقروء لما تعلمه التطبيق — يُعرض للمستخدم في التعليمات."""
    d = _load()
    n = d.get("events_count", 0)
    if n == 0:
        return ("لم يتعلم التطبيق شيئًا بعد — ابدأ بالعمل وسيتذكر تفضيلاتك "
                "تلقائيًا (كل التعلم محلي داخل جهازك).")
    lines = [f"عدد التعديلات التي تعلم منها التطبيق: {n}"]
    es = d["enhance_strength"]
    if es["n"]:
        lines.append(f"قوة التحسين المفضلة لديك: {int(_avg(es, 0.5) * 100)}%")
    bs = d["brush_size"]
    if bs["n"]:
        lines.append(f"حجم الفرشاة المفضل: {int(_avg(bs, 40))}")
    sh = d["shadow_enabled"]
    if sh["on"] + sh["off"] >= 3:
        lines.append("تفضيلك للظل: " +
                     ("مفعّل" if sh["on"] > sh["off"] else "بدون ظل"))
    an = d["nutrition_anchor"]
    if an:
        best = max(an, key=an.get)
        names = {"bottom_left": "أسفل يسار", "bottom_right": "أسفل يمين",
                 "top_left": "أعلى يسار", "top_right": "أعلى يمين",
                 "free": "موضع حر"}
        lines.append(f"موضعك المفضل لملصق الحقائق: {names.get(best, best)}")
    r = d["edge_fix_rate"]
    if r["total"] >= 5:
        pct = int(r["fixed"] / r["total"] * 100)
        lines.append(f"نسبة تصحيحك اليدوي للحواف: {pct}%" +
                     (" — تم ضبط القص ليكون محافظًا أكثر"
                      if suggest_segmentation_conservative() else ""))
    lines.append("ملاحظة: التعلم محلي 100% داخل جهازك ولا يُرسل أي شيء "
                 "خارجيًا.")
    return "\n".join(lines)


def reset() -> None:
    """إعادة ضبط ما تعلمه التطبيق — بطلب المستخدم."""
    _save(copy.deepcopy(_DEFAULTS))
