# -*- coding: utf-8 -*-
"""جسر الوعي ← المحرك.

المشكلة التي يحلّها هذا الملف كانت أخطر عيوب البرنامج: المستخدم يكتب
«خلي المقاس 1000×1000» أو «لا تسوي ظل»، فتفهمه طبقة الحوار وتحفظه في
``overrides.json`` وتعرضه في لوحة الوعي بوصفه تعديلًا **منفَّذًا**، ثم
تأتي الصورة التالية فتُعالَج بالقيم القديمة تمامًا. أي أن البرنامج كان
يقول «طبّقته الآن» ولا يطبّقه — وهذا أسوأ من العجز، لأنه عجز مقنَّع
بالطاعة، والمالك لا يملك وسيلة لكشفه إلا بقياس الصور يدويًا.

السبب البنيوي: ``ProcessOptionsV2`` هي البوابة الوحيدة لكل قرار معالجة،
وكانت تُبنى في ``integration_v2._coerce_options`` بقيمها الافتراضية دون
أن تستشير طبقة الوعي مطلقًا. فكان الوعي جزيرة معرفة معزولة عن الفعل.

الحل هنا: دالة واحدة ``apply_overrides`` تُدعى عند كل بناء للخيارات،
تقرأ تجاوزات الوعي وتُسقطها على الحقول المقابلة. القواعد التي التزمناها:

1. **لا كسر للسلوك القائم**: أي مفتاح غير موجود يُترك على حاله، وأي
   قيمة تالفة تُهمَل بصمت مع تسجيلها، فالمعالجة لا تتوقف لأن إعدادًا
   واحدًا فسد.
2. **الأولوية للأمر الصريح**: ما تُمرّره الواجهة صراحةً في dict أقوى من
   التجاوز المحفوظ، لأن آخر ما فعله المالك بيده أصدق تعبيرًا عن نيته.
3. **الحدود مصونة**: كل قيمة تُقصّ إلى مدى آمن، فأمر «المقاس 99999» لا
   يُفجّر الذاكرة بل يُقصّ إلى الحد الأعلى المعقول.
"""
from __future__ import annotations

import contextlib

__all__ = ["apply_overrides", "effective_overrides", "OVERRIDE_MAP"]


# خريطة: مفتاح تجاوز الوعي → حقل ProcessOptionsV2
# نُبقيها معلنة صريحة لا اشتقاقًا تلقائيًا، كي يبقى تغيير سلوك المعالجة
# قرارًا مقصودًا مرئيًا في مكان واحد، لا أثرًا جانبيًا لتسمية متشابهة.
OVERRIDE_MAP: dict = {
    "output_quality": "quality",
    "output_format": "output_format",
    "output_size": ("width", "height"),
    "shadow_enabled": "shadow_preset",
    "enhance_enabled": "enhance",
    "blur_dates": "blur_dates",
    "nutrition_mode": "nutrition_mode",
    "text_aware": "text_aware",
}

_VALID_FORMATS = ("webp", "png", "jpeg", "jpg")
_VALID_NUTRITION = ("none", "auto", "remove", "standalone",
                    "merge_small", "rebuild")
# اسم preset الظل الافتراضي حين يطلب المالك ظلًا دون تحديد نوعه
_DEFAULT_SHADOW = "soft"


def effective_overrides() -> dict:
    """تجاوزات الوعي الفعّالة الآن، أو dict فارغة إن غابت الطبقة.

    الغياب حالة مشروعة لا خطأ: المحرك يجب أن يعمل كاملًا حتى لو
    استُخرج وحده بلا طبقة وعي، فلا نجعل المعالجة تعتمد على وجودها.
    """
    try:
        from awareness import healer
    except Exception:
        return {}
    try:
        data = healer.overrides()
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if not str(k).startswith("_")}


def _shadow_preset_for(value) -> str:
    """يحوّل تفضيل الظل (منطقي أو اسم) إلى اسم preset صالح."""
    if isinstance(value, str) and value.strip():
        name = value.strip()
        with contextlib.suppress(Exception):
            from .shadow_v2 import SHADOW_PRESETS
            if name in SHADOW_PRESETS:
                return name
            # اسم غير معروف: نُرجع الافتراضي بدل تعطيل الظل تمامًا،
            # لأن نية المالك كانت «أريد ظلًا» لا «أريد هذا الاسم».
            return _DEFAULT_SHADOW if SHADOW_PRESETS else ""
        return name
    if value:
        with contextlib.suppress(Exception):
            from .shadow_v2 import SHADOW_PRESETS
            if _DEFAULT_SHADOW in SHADOW_PRESETS:
                return _DEFAULT_SHADOW
            return next(iter(SHADOW_PRESETS), "")
        return _DEFAULT_SHADOW
    return ""


def apply_overrides(opts, *, explicit: dict | None = None):
    """يُسقط تجاوزات الوعي على ``opts`` ويُرجعها.

    ``explicit`` هي المفاتيح التي مرّرتها الواجهة صراحةً لهذه الصورة؛
    ما ورد فيها لا يُلمس، لأن الأمر المباشر يسبق الإعداد المحفوظ.
    """
    ovr = effective_overrides()
    if not ovr:
        return opts
    given = set(explicit or ())
    applied: dict = {}

    def _set(field: str, value) -> None:
        if hasattr(opts, field):
            setattr(opts, field, value)
            applied[field] = value

    # ── الجودة: 50–100 ──
    if "output_quality" in ovr and "quality" not in given:
        with contextlib.suppress(Exception):
            q = int(float(ovr["output_quality"]))
            _set("quality", max(50, min(100, q)))

    # ── الصيغة ──
    if "output_format" in ovr and "output_format" not in given:
        fmt = str(ovr["output_format"] or "").lower().lstrip(".")
        if fmt in _VALID_FORMATS:
            _set("output_format", "jpeg" if fmt == "jpg" else fmt)
            # WebP بلا فقدان يتجاهل رقم الجودة، فإن طلب المالك جودة
            # صريحة أقل من 100 وجب إلغاء اللافقدي وإلا أُهمل أمره.
            if fmt == "webp" and applied.get("quality", 100) < 100:
                _set("webp_lossless", False)

    # ── المقاس ──
    if "output_size" in ovr and not ({"width", "height"} & given):
        with contextlib.suppress(Exception):
            val = ovr["output_size"]
            if isinstance(val, (list, tuple)) and len(val) >= 2:
                w, h = int(val[0]), int(val[1])
            else:
                w = h = int(val)
            _set("width", max(200, min(6000, w)))
            _set("height", max(200, min(6000, h)))

    # ── الظل ──
    if "shadow_enabled" in ovr and "shadow_preset" not in given:
        _set("shadow_preset", _shadow_preset_for(ovr["shadow_enabled"]))

    # ── التحسين وطمس التواريخ والوعي بالنص: منطقية صريحة ──
    for key, field in (("enhance_enabled", "enhance"),
                       ("blur_dates", "blur_dates"),
                       ("text_aware", "text_aware")):
        if key in ovr and field not in given:
            _set(field, bool(ovr[key]))

    # ── جدول القيم الغذائية ──
    if "nutrition_mode" in ovr and "nutrition_mode" not in given:
        mode = str(ovr["nutrition_mode"] or "").strip()
        if mode in _VALID_NUTRITION:
            _set("nutrition_mode", "none" if mode == "none" else mode)

    if applied:
        with contextlib.suppress(Exception):
            from awareness import journal
            journal.debug("bridge_overrides_applied",
                          fields=",".join(sorted(applied)))
    return opts
