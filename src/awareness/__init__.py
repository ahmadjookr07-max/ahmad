# -*- coding: utf-8 -*-
"""awareness — طبقة الوعي الذاتي لـ Smart Catalog Vision.

هذه الحزمة تُمنح التطبيق ثلاث قدرات لم تكن فيه:

**يعرف نفسه** — `identity` يحمل هدفه وحدوده و18 قدرة مع تبعياتها وأثر
تعطّل كل واحدة، فيستطيع أن يقول «أنا معطّل جزئيًا لأن OCR ناقص» بدل أن
يفشل بصمت.

**يشفي نفسه** — `vitals` يفحص، `healer` يعالج بـ16 علاجًا فعليًا،
`surgeon` يعدّل بنية الكود نفسها برقع مُتحقَّق منها وتراجع ذرّي،
`optimizer` يضبط معاملاته بقياس الأثر لا بالتخمين، و`ledger` (السجل
الأكاشي) يحفظ كل ما تعلّمه فلا يكرر خطأً حلّه مرة.

**يفهم صاحبه** — `dialogue` يقبل العربية العامية («الصور تطلع مشوشه»)
فيحوّلها إلى تعديل فعلي في إعداداته أو كوده، مع تأكيد قبل الخطير وتراجع
بنقرة.

## الاستخدام من التطبيق
```python
from awareness import core

st = core.awake()               # عند الإقلاع (لا يُجمّد الواجهة)
core.start_pulse()              # مراقبة دورية
ok, res, msg = core.guard(fn)   # عملية محميّة بعلاج تلقائي
core.ask("خل الجوده 95")        # حوار المستخدم
core.sleep()                    # عند الإغلاق
```

**قاعدة تصميم حاكمة**: لا شيء في هذه الحزمة يُسمح له بأن يمنع التطبيق من
العمل. كل استيراد وكل تهيئة محاطة بحماية، والفشل يعني «بلا وعي» لا
«بلا تطبيق».
"""
from __future__ import annotations

import contextlib

AWARENESS_VERSION = "1.0.0"

__all__ = [
    "AWARENESS_VERSION", "available", "core", "identity", "journal",
    "ledger", "vitals", "healer", "surgeon", "optimizer", "dialogue",
    "awake", "guard", "ask", "introspect", "self_improve", "sleep",
]

_MODULES: dict[str, object] = {}

for _name in ("identity", "journal", "ledger", "vitals", "healer",
              "surgeon", "optimizer", "dialogue", "core"):
    with contextlib.suppress(Exception):
        _MODULES[_name] = __import__(f"{__name__}.{_name}", fromlist=[_name])

identity = _MODULES.get("identity")
journal = _MODULES.get("journal")
ledger = _MODULES.get("ledger")
vitals = _MODULES.get("vitals")
healer = _MODULES.get("healer")
surgeon = _MODULES.get("surgeon")
optimizer = _MODULES.get("optimizer")
dialogue = _MODULES.get("dialogue")
core = _MODULES.get("core")


def available() -> dict:
    """أي طبقات الوعي حُمّلت فعلًا — يُستخدم في التشخيص والتقارير."""
    return {n: (n in _MODULES) for n in
            ("identity", "journal", "ledger", "vitals", "healer",
             "surgeon", "optimizer", "dialogue", "core")}


def _stub(*_a, **_kw):
    return {"ok": False, "message_ar": "طبقة الوعي غير متاحة في هذه النسخة."}


awake = getattr(core, "awake", _stub)
guard = getattr(core, "guard", None) or (lambda fn, *a, **k: (True, fn(*a, **k), ""))
ask = getattr(core, "ask", _stub)
introspect = getattr(core, "introspect", _stub)
self_improve = getattr(core, "self_improve", _stub)
sleep = getattr(core, "sleep", lambda: None)
