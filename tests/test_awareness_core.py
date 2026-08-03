# -*- coding: utf-8 -*-
"""اختبار طبقة الوعي — مبنيّ على التوقيعات الفعلية لا على التخمين.

الدرس الذي أنتج هذا الملف: نسخته الأولى نادت ``intent.name`` وهو حقل غير
موجود (الحقل الفعلي ``key``)، فأبلغت عن فشل ذريع في مُفسّر سليم. الاختبار
الذي يخطئ في أسماء الواجهة أخطر من غياب الاختبار، لأنه يُنذر بأعطال
وهمية ويُطمئن على أعطال حقيقية. لذا كل اسم هنا مُستخرج بالتفتيش المباشر
ومُدوَّن في ``docs/api_signatures.md``.

ونقيس السلوك المرئي للمالك — «هل فهم أمري؟ هل نفّذه؟ هل يعترف بما لا
يعرف؟» — لا التفاصيل الداخلية، فالاختبار الذي يُقيّد البنية الداخلية
يمنع تحسينها لاحقًا.

    PYTHONPATH=src python3 tests/test_awareness_core.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _p in (_ROOT / "src", _ROOT / "windows_app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_TMP = tempfile.mkdtemp(prefix="mis_aw_test_")
os.environ.setdefault("MIS_DATA_ROOT", _TMP)
os.environ.setdefault("MIS_LICENSE_BYPASS", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def check(cond: bool, label: str, note: str = "") -> bool:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {label} {note}")
    else:
        FAIL += 1
        FAILURES.append(label)
        print(f"  ✗ {label} {note}")
    return bool(cond)


def head(title: str) -> None:
    print(f"\n── {title} ──")


# ═════════════════ 1) الهوية ═════════════════
def t_identity() -> None:
    head("1) نموذج الذات")
    from awareness import identity

    check(bool(identity.PURPOSE), "يعرف هدفه")
    check(len(identity.CAPABILITIES) >= 10,
          "يعرف قدراته", f"{len(identity.CAPABILITIES)} قدرة")
    check(bool(identity.BOUNDARIES), "يعرف حدوده",
          f"{len(identity.BOUNDARIES)} حدًّا")

    sm = identity.self_model()
    check(sm is not None, "يبني نموذج ذاته")

    txt = identity.describe_self()
    check(isinstance(txt, str) and len(txt) > 60,
          "يصف نفسه بالعربية", f"{len(txt)} حرفًا")
    check("أحمد" in txt or identity.OWNER_NAME in txt, "يعرف مالكه")

    facts = identity.runtime_facts()
    check(isinstance(facts, dict) and len(facts) >= 3,
          "يعرف بيئة تشغيله", f"{len(facts) if isinstance(facts, dict) else 0} حقيقة")

    # كل قدرة يجب أن تُصرّح بأثر تعطلها، وإلا لا يمكن ترتيب الأولويات
    caps = (identity.CAPABILITIES.values()
            if isinstance(identity.CAPABILITIES, dict)
            else identity.CAPABILITIES)
    missing = [getattr(c, "key", "?") for c in caps
               if not (getattr(c, "impact", None)
                       or getattr(c, "impact_ar", ""))]
    check(not missing, "كل قدرة تُصرّح بأثر تعطلها",
          f"ناقصة: {missing[:3]}" if missing else "")


# ═════════════════ 2) السجل والبصمة ═════════════════
def t_journal() -> None:
    head("2) السجل وبصمة العطل")
    from awareness import journal

    journal.info("test_event", detail="رسالة اختبار")
    check(True, "يكتب بلا استثناء")

    rec = journal.recent(limit=5)
    check(isinstance(rec, list), "يقرأ آخر ما كتب",
          f"{len(rec) if isinstance(rec, list) else '?'} سطرًا")

    # جوهر البصمة: عطلان مختلفان لا يندمجان
    try:
        raise ValueError("no such file: alpha.onnx")
    except ValueError as e1:
        f1 = journal.fingerprint(e1)
    try:
        raise ValueError("no such file: beta.onnx")
    except ValueError as e2:
        f2 = journal.fingerprint(e2)
    check(f1 != f2, "يميّز عطلين مختلفين", f"{str(f1)[:8]} ≠ {str(f2)[:8]}")

    # ونفس العطل يعطي نفس البصمة (وإلا لا يتعلّم من التكرار)
    try:
        raise ValueError("no such file: alpha.onnx")
    except ValueError as e3:
        f3 = journal.fingerprint(e3)
    check(f1 == f3, "يوحّد بصمة العطل المتكرر")

    dirty = {"path": "C:/Users/Ahmad/secret.png", "email": "a@b.com"}
    clean = journal.sanitize(dirty)
    check("Ahmad" not in str(clean), "يُخفي بيانات المستخدم قبل الإرسال")

    st = journal.stats()
    check(isinstance(st, dict), "يُحصي سجله")


# ═════════════════ 3) الفحص الحيوي ═════════════════
def t_vitals() -> None:
    head("3) الفحص الحيوي")
    from awareness import vitals

    quick = vitals.quick_scan()
    check(quick is not None, "فحص سريع يعمل")

    rep = vitals.full_scan(use_cache=False, deep_imports=False)
    check(rep is not None, "فحص شامل يُنتج تقريرًا")

    findings = list(getattr(rep, "findings", []) or [])
    check(isinstance(findings, list), "النتائج قائمة",
          f"{len(findings)} نتيجة")

    score = getattr(rep, "score", None)
    if score is not None:
        check(0 <= float(score) <= 100, "الدرجة في المدى الصحيح",
              f"{score}/100")

    # كل نتيجة يجب أن تُشرح بالعربية وتُصنّف خطورتها، وإلا فهي بلا قيمة
    mute = [f for f in findings
            if not (getattr(f, "message_ar", "") or getattr(f, "title_ar", "")
                    or getattr(f, "detail_ar", ""))]
    check(not mute, "كل نتيجة مشروحة بالعربية",
          f"صامتة: {len(mute)}" if mute else "")
    unranked = [f for f in findings if getattr(f, "severity", None) is None]
    check(not unranked, "كل نتيجة مُصنّفة الخطورة",
          f"بلا تصنيف: {len(unranked)}" if unranked else "")


# ═════════════════ 4) الشفاء ═════════════════
def t_healer() -> None:
    head("4) الشفاء الذاتي")
    from awareness import healer

    healer.set_override("output_quality", 95, reason="اختبار")
    check(healer.get_override("output_quality") == 95,
          "يحفظ قرار تعديل ويستعيده")
    check(isinstance(healer.overrides(refresh=True), dict),
          "التجاوزات قابلة للقراءة ككل")

    # نفاد الذاكرة عطل معروف قابل للمعالجة بتقليل التوازي
    try:
        raise MemoryError("cannot allocate 4.2 GiB")
    except MemoryError as exc:
        dec = healer.heal_from_exception(exc)
    check(dec is not None, "يُنتج قرارًا لعطل الذاكرة")
    if dec is not None:
        check(hasattr(dec, "retry") or hasattr(dec, "should_retry"),
              "القرار يحدّد هل يُعاد المحاولة")
        msg = (getattr(dec, "message_ar", "")
               or getattr(dec, "reason_ar", ""))
        check(bool(msg), "يشرح للمستخدم بالعربية", f"«{str(msg)[:40]}»")

    # عطل مجهول تمامًا: يجب ألّا يسقط، بل يعترف بعدم المعرفة
    class WeirdError(Exception):
        pass
    try:
        raise WeirdError("انفجار كوني غير مفهوم 0xZZ")
    except WeirdError as exc:
        dec2 = healer.heal_from_exception(exc)
    check(dec2 is None or hasattr(dec2, "retry")
          or hasattr(dec2, "should_retry"),
          "لا يسقط أمام عطل مجهول")


# ═════════════════ 5) الجراحة ═════════════════
def t_surgeon() -> None:
    head("5) جراحة الكود")
    from awareness import surgeon

    issues = surgeon.diagnose(use_cache=False)
    check(isinstance(issues, list), "يشخّص الكود",
          f"{len(issues) if isinstance(issues, list) else '?'} علّة")

    # كل علّة يجب أن تحمل موقعًا وشرحًا عربيًا يفهمه المالك
    weak = [it for it in issues
            if not getattr(it, "path", None)
            or not getattr(it, "title_ar", "")]
    check(not weak, "كل علّة موثّقة بموقع وعنوان عربي",
          f"ناقصة: {len(weak)}" if weak else "")

    codes = {getattr(it, "code", "") for it in issues}
    check(bool(codes - {""}), "يصنّف العلل برموز", f"{sorted(codes)[:4]}")

    # المحاكاة الجافة يجب ألا تلمس القرص — ضمان أمان لا رفاهية
    watch = [p for p in
             {getattr(it, "path", "") for it in issues[:4]} if p]
    before = {}
    for p in watch:
        try:
            before[p] = Path(p).read_bytes()
        except Exception:
            pass
    res = surgeon.operate(apply=False, max_files=3, reason="اختبار جاف")
    check(res is not None, "المحاكاة الجافة تُرجع نتيجة")
    unchanged = all(Path(p).read_bytes() == b for p, b in before.items())
    check(unchanged, "المحاكاة الجافة لا تكتب على القرص",
          "" if unchanged else "تغيّر ملف في وضع المحاكاة!")

    check(isinstance(surgeon.history(limit=5), list),
          "يوثّق تاريخ عملياته")


# ═════════════════ 6) الحوار العربي ═════════════════
def t_dialogue() -> None:
    head("6) فهم أوامر المالك بالعربية")
    from awareness import dialogue

    # الحقل الفعلي في Intent هو `key`، وحدّ الفهم confidence >= 0.35
    cases = [
        "مين انت",
        "من أنت؟",
        "وش تقدر تسوي",
        "انت تعبان؟ افحص نفسك",
        "البرنامج بطيء جدا سرعه",
        "خلي الجودة ٩٥",
        "لا تسوي خلفية بيضاء",
        "رجع اللي قبله",
        "صلح نفسك",
        "شغل القص الذكي",
    ]
    hits, misses = 0, []
    for text in cases:
        intent = dialogue.understand(text)
        key = getattr(intent, "key", "")
        conf = float(getattr(intent, "confidence", 0.0) or 0.0)
        if key and conf >= 0.35:
            hits += 1
        else:
            misses.append(f"«{text}»→{key or 'لا شيء'}({conf:.2f})")
    check(hits >= len(cases) - 1, "يفهم العامية والفصحى",
          f"{hits}/{len(cases)}" + ("  " + " | ".join(misses) if misses else ""))

    # النفي: أهم مكان يُخطئ فيه فهم الأوامر
    pos = dialogue.understand("شغل القص الذكي")
    neg = dialogue.understand("لا تشغل القص الذكي")
    pv = (getattr(pos, "params", {}) or {}).get("value")
    nv = (getattr(neg, "params", {}) or {}).get("value")
    check(pv != nv, "يميّز الأمر من نفيه", f"{pv} ≠ {nv}")

    # استخراج الأرقام الهندية الشائعة في لوحات المفاتيح العربية
    q = dialogue.understand("اجعل الجودة ٨٨")
    val = (getattr(q, "params", {}) or {}).get("value")
    check(val in (88, "88"), "يقرأ الأرقام الهندية", f"value={val}")

    # حدود الكلمة: «نت» داخل «انت» صنّفت سؤال «مين انت» أمرًا
    # بتغيير سياسة الشبكة — عيب مطابقة بالـsubstring أُصلح
    who = dialogue.understand("مين انت")
    wkey = str(getattr(who, "key", "")).lower()
    wttl = str(getattr(who, "title_ar", ""))
    check("net" not in wkey and "شبك" not in wttl and "نت" not in wttl,
          "لا يخلط «انت» بـ«نت»", f"صنّفه: {wkey}")

    # المجهول يُعترف به لا يُخترع له معنى
    unk = dialogue.understand("اطبخ لي كبسة بالدجاج")
    ukey = getattr(unk, "key", "")
    uconf = float(getattr(unk, "confidence", 0.0) or 0.0)
    check((not ukey) or uconf < 0.35,
          "يعترف بما لا يفهمه بدل تخمينه", f"→ {ukey}({uconf:.2f})")

    # تدرّج الخطورة: «صلح نفسك» تشخيص آمن يمسّ الإعدادات، أما
    # «عدل الكود» فيعيد كتابة البرنامج نفسه. خلطهما خطر: فإمّا
    # يُنفّذ تعديل كود بلا تأكيد، أو يُزعج المالك بتأكيد لكل فحص.
    soft = dialogue.understand("صلح نفسك")
    hard = dialogue.understand("عدل الكود وسوي جراحه لنفسك")
    check(str(getattr(soft, "key", "")) != str(getattr(hard, "key", "")),
          "يفصل التشخيص من جراحة الكود",
          f"{getattr(soft, 'key', '')} ≠ {getattr(hard, 'key', '')}")
    check(bool(getattr(hard, "needs_confirmation", False))
          or str(getattr(hard, "risk", "")) in ("moderate", "medium",
                                                "high", "invasive"),
          "جراحة الكود تطلب تأكيدًا",
          f"risk={getattr(hard, 'risk', '')}")


# ═════════════════ 7) محرك الأداء ═════════════════
def t_perf() -> None:
    head("7) محرك الأداء")
    from awareness import perf

    eng = perf.PerfEngine()
    # خطوة سريعة كثيرة التكرار مقابل خطوة بطيئة نادرة:
    # المالك يشعر بالأولى لا الثانية، فالترتيب بالزمن الكلي هو الصحيح
    for _ in range(300):
        eng.record("سريعة_متكررة", 20.0)
    eng.record("بطيئة_نادرة", 2000.0)

    spots = eng.hotspots(2)
    first = ""
    if spots:
        s0 = spots[0]
        first = s0.get("name") if isinstance(s0, dict) else getattr(s0, "name", "")
    check(bool(spots) and first == "سريعة_متكررة",
          "يرتّب بالزمن الكلي لا بالمتوسط", f"الأول: {first or '—'}")

    eng.promote_baseline()
    for _ in range(8):
        eng.record("سريعة_متكررة", 60.0)      # تباطؤ ×3
    adv = eng.recommend()
    kinds = [getattr(a, "kind", "") for a in (adv or [])]
    check(any("regress" in str(k) for k in kinds)
          or any("ارتداد" in str(getattr(a, "message_ar", ""))
                 for a in (adv or [])),
          "يكشف الارتداد بعد اعتماد الأساس", f"{kinds[:4]}")

    rep = eng.report_ar(3)
    check(isinstance(rep, str) and ("أبطأ" in rep or "ms" in rep
                                    or "مللي" in rep),
          "يشرح أدائه بالعربية")


# ═════════════════ 8) المنسّق ═════════════════
def t_core() -> None:
    head("8) المنسّق (core)")
    from awareness import core

    st = core.awake()
    check(st is not None, "يستيقظ")

    card = core.introspect()
    check(isinstance(card, dict) and len(card) >= 3,
          "يقدّم بطاقة تأمل ذاتي",
          f"مفاتيح: {sorted(card)[:5] if isinstance(card, dict) else '—'}")
    if isinstance(card, dict):
        for key in ("state", "perf"):
            check(key in card, f"البطاقة تشمل {key}")
        check(any(k in card for k in ("identity", "identity_ar", "self",
                                      "self_model", "capabilities")),
              "البطاقة تشمل الهوية")

    # guard: العقد الحرج — يُرجع (ok, result, message_ar) ولا يرفع أبدًا،
    # لأن نافذة تسقط أسوأ من دفعة تُكمل بأقل جودة
    out = core.guard(lambda: 6 * 7, name="t_ok")
    ok, val = (out[0], out[1]) if isinstance(out, tuple) else (True, out)
    check(bool(ok) and val == 42, "guard يمرّر النتيجة سليمة", f"{out!r}"[:60])

    def boom():
        raise RuntimeError("عطل مُصطنَع للاختبار")

    out2 = core.guard(boom, name="t_boom", retry=False)
    if isinstance(out2, tuple):
        ok2, _v2, msg2 = (list(out2) + ["", "", ""])[:3]
        check(ok2 is False, "guard يُعلن الفشل بلا انهيار", f"ok={ok2}")
        check(bool(msg2), "guard يشرح العطل بالعربية", f"«{str(msg2)[:40]}»")
    else:
        check(False, "guard يُرجع ثلاثية (ok, result, message_ar)",
              f"أرجع {type(out2)}")

    ans = core.ask("مين انت")
    txt = ""
    if isinstance(ans, dict):
        txt = (ans.get("message_ar") or ans.get("text_ar")
               or ans.get("answer_ar") or "")
    check(bool(txt), "يجيب على سؤال المالك", f"«{str(txt)[:40]}»")

    core.sleep()
    check(True, "ينام بلا استثناء")


def main() -> int:
    print("═" * 54)
    print("اختبار طبقة الوعي — استوديو صور المتجر")
    print("═" * 54)
    for fn in (t_identity, t_journal, t_vitals, t_healer, t_surgeon,
               t_dialogue, t_perf, t_core):
        try:
            fn()
        except Exception as exc:            # عطل في الاختبار نفسه
            global FAIL
            FAIL += 1
            FAILURES.append(f"{fn.__name__} (استثناء)")
            import traceback
            print(f"  ✗ {fn.__name__} رفع استثناء: {exc}")
            traceback.print_exc(limit=4)
    print("\n" + "═" * 54)
    print(f"نجح {PASS} / فشل {FAIL}")
    if FAILURES:
        print("الفاشل: " + " | ".join(FAILURES))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
