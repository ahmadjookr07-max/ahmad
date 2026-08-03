#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبار بوابات الجرّاح — يُثبت أنها ترفض **الرقعة الزائفة** فعلًا.

الرقعة الزائفة هي الخطر الأول الموثّق في أدبيات الإصلاح الآلي: رقعة تجتاز
كل الاختبارات وتكون خاطئة. وبوابتا النحو والبنية عاجزتان عن رصدها لأنهما
تفحصان الهيكل الخارجي لا المعنى.

منهج هذا الاختبار: نُصنّع رقعًا خاطئة **متعمّدة** ونتأكد أنها تُرفض، ثم
نتأكد أن الرقع السليمة تمرّ. اختبار لم نره يفشل مرة واحدة لا يُوثق به.

يشمل كذلك: تصنيف التبعيات الإلزامية مقابل الاختيارية، وهو الدرس الذي
كان سيُدمّر البرنامج (حماية cv2 المستدعاة 270 مرة بـ``= None``).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("MIS_HEADLESS", "1")

_ok = 0
_fail = 0


def check(name: str, cond: bool, note: str = "") -> bool:
    """يطبع نتيجة تحقق واحد. ``note`` يوصف الفشل فلا يُطبع عند النجاح."""
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  PASS  {name}")
    else:
        _fail += 1
        print(f"  FAIL  {name}" + (f" — {note}" if note else ""))
    return cond


# ───────────── 1. تصنيف التبعيات: الدرس مدفوع الثمن ─────────────

def test_dependency_classification() -> None:
    print("\n[1] تصنيف التبعيات الإلزامية مقابل الاختيارية")
    from awareness import identity
    from awareness.surgeon import (
        _heavily_used,
        _optional_packages,
        _required_packages,
    )

    root = str(identity.repo_root())
    required = _required_packages(root)
    heavy = _heavily_used(root)
    optional = _optional_packages(root)

    check("requirements_parsed", len(required) >= 5,
          f"لم تُقرأ التبعيات الإلزامية: {sorted(required)}")

    # cv2 مُعلنة في requirements.txt ومستدعاة مئات المرات.
    check("cv2_is_required", "cv2" in required,
          "cv2 غير معدودة إلزامية مع أنها في requirements.txt")
    check("cv2_is_heavy", "cv2" in heavy,
          f"cv2 غير معدودة كثيفة الاستخدام: {sorted(heavy)}")

    # الحكم الحاسم: لا تُحمى تبعية أساسية أبدًا.
    for pkg in ("cv2", "onnxruntime", "pytesseract", "xlrd"):
        check(f"not_optional_{pkg}", pkg not in optional,
              f"«{pkg}» تبعية إلزامية لكنها مُصنّفة اختيارية — حمايتها "
              "تُحوّل عطل إقلاع واضحًا إلى انهيارات NoneType غامضة")

    # وفي المقابل: الاختيارية الحقيقية يجب أن تبقى مرشّحة للحماية.
    check("real_optional_kept", len(optional) >= 3,
          f"لم تبق حزم اختيارية حقيقية للحماية: {sorted(optional)}")
    for pkg in ("rembg", "psutil"):
        check(f"is_optional_{pkg}", pkg in optional,
              f"«{pkg}» ليست في requirements.txt فيجب أن تبقى اختيارية")


def test_no_false_import_issues() -> None:
    """التشخيص لا يجوز أن يُبلّغ عن استيراد غير محمي لتبعية إلزامية."""
    print("\n[2] التشخيص لا يُنتج علل استيراد زائفة")
    from awareness.surgeon import Surgeon

    s = Surgeon()
    issues = s.diagnose()
    guard = [i for i in issues if i.code == "unguarded_optional_import"]
    bad = [i for i in guard if i.context.get("module") == "cv2"]
    check("no_cv2_guard_issue", not bad,
          f"ما زال يشخّص حماية cv2 في {len(bad)} موضع — رقعة كارثية")
    check("diagnose_still_works", len(issues) > 50,
          f"التشخيص انهار أو صار فارغًا: {len(issues)} علّة فقط")
    print(f"       (إجمالي العلل المُشخّصة: {len(issues)})")


# ───────────── 3. بوابة المعنى: رقع خاطئة متعمّدة ─────────────

_BASE = '''\
def pick(a, b):
    if a > b:
        return "a"
    if a < b:
        return "b"
    return None


def load(path):
    try:
        return open(path).read()
    except Exception:
        pass
    return ""
'''


def _patch(new_text: str):
    """يبني رقعة صناعية للتحقق منها بلا لمس المستودع."""
    from awareness.surgeon import Patch
    return Patch(path="fake_module.py", old_text=_BASE, new_text=new_text,
                 issues=[], transform="test", note_ar="")


def test_semantics_gate_rejects_bad_patches() -> None:
    print("\n[3] بوابة المعنى ترفض الرقع الزائفة")
    from awareness.surgeon import Surgeon

    s = Surgeon()

    # (أ) رقعة تحذف شرطًا: نحوها سليم، بنيتها سليمة، معناها مختلف.
    drop_cond = _BASE.replace('    if a < b:\n        return "b"\n', "")
    ok, why = s._semantics_preserved(_BASE, drop_cond)
    check("rejects_dropped_condition", not ok,
          "قبلت رقعة حذفت شرطًا كاملًا من دالة القرار")
    print(f"       سبب الرفض: {why[:80]}")

    # (ب) رقعة تستحدث raise: تقلب مسارًا صامتًا مقصودًا إلى انهيار.
    add_raise = _BASE.replace("    except Exception:\n        pass\n",
                              "    except Exception:\n        raise\n")
    ok, why = s._semantics_preserved(_BASE, add_raise)
    check("rejects_new_raise", not ok,
          "قبلت رقعة تُحوّل ابتلاع العطل إلى انهيار أمام المالك")
    print(f"       سبب الرفض: {why[:80]}")

    # (ج) رقعة تُبدّل قيمة مُرجعة: أخطر الأنواع لأنها صامتة تمامًا.
    swap_ret = _BASE.replace('        return "a"', '        return "A"')
    ok, why = s._semantics_preserved(_BASE, swap_ret)
    check("rejects_changed_return", not ok,
          "قبلت رقعة بدّلت قيمة مُرجعة ثابتة")
    print(f"       سبب الرفض: {why[:80]}")

    # (د) نص معطوب نحويًا يُرفض لا يُقبل بالخطأ.
    ok, _ = s._semantics_preserved(_BASE, "def broken(:\n    pass\n")
    check("rejects_unparsable", not ok, "قبلت نصًا لا يُحلَّل")


def test_semantics_gate_accepts_good_patches() -> None:
    """البوابة الصارمة عديمة النفع إن رفضت الرقع السليمة أيضًا."""
    print("\n[4] بوابة المعنى تقبل الرقع السليمة")
    from awareness.surgeon import Surgeon

    s = Surgeon()

    # (أ) إضافة تسجيل صامت محفوف بـtry — ما يفعله محوّلنا فعلًا.
    logged = _BASE.replace(
        "    except Exception:\n        pass\n",
        "    except Exception:\n"
        "        try:\n"
        "            from awareness import journal as _j\n"
        "            _j.debug('swallowed_exception', where=__name__)\n"
        "        except Exception:\n"
        "            pass\n",
    )
    ok, why = s._semantics_preserved(_BASE, logged)
    check("accepts_added_logging", ok, f"رفضت إضافة تسجيل سليمة: {why}")

    # (ب) ضبط الترميز: لا يمسّ المنطق إطلاقًا.
    enc = _BASE.replace("open(path)", "open(path, encoding='utf-8')")
    ok, why = s._semantics_preserved(_BASE, enc)
    check("accepts_encoding_fix", ok, f"رفضت ضبط الترميز: {why}")

    # (ج) نص لم يتغيّر: يجب أن يمرّ بلا شكوى.
    ok, why = s._semantics_preserved(_BASE, _BASE)
    check("accepts_identical", ok, f"رفضت نصًا مطابقًا: {why}")


def test_gate_wired_into_verify() -> None:
    """البوابة يجب أن تكون موصولة بمسار التحقق لا معلّقة وحدها."""
    print("\n[5] البوابة موصولة بمسار التحقق الفعلي")
    from awareness.surgeon import Surgeon

    s = Surgeon()
    bad = _patch(_BASE.replace('    if a < b:\n        return "b"\n', ""))
    ok, checks = s._verify_uncached([bad])
    gates = {c.get("gate") for c in checks}
    check("semantics_gate_present", "semantics" in gates,
          f"بوابة المعنى غير مُستدعاة في التحقق؛ البوابات: {sorted(gates)}")
    check("verify_rejects_bad_patch", not ok,
          "مسار التحقق الكامل قبل رقعة حذفت شرطًا")
    sem = [c for c in checks if c.get("gate") == "semantics"]
    check("semantics_reported_failure", sem and not sem[0].get("ok"),
          "بوابة المعنى أبلغت نجاحًا لرقعة خاطئة")


def main() -> int:
    print("=" * 62)
    print("اختبار بوابات الجرّاح ومناعتها من الرقعة الزائفة")
    print("=" * 62)
    for fn in (test_dependency_classification,
               test_no_false_import_issues,
               test_semantics_gate_rejects_bad_patches,
               test_semantics_gate_accepts_good_patches,
               test_gate_wired_into_verify):
        try:
            fn()
        except Exception as exc:               # noqa: BLE001
            global _fail
            _fail += 1
            print(f"  FAIL  {fn.__name__} — استثناء: {type(exc).__name__}: {exc}")
    print("\n" + "=" * 62)
    print(f"نجح {_ok} / فشل {_fail}")
    print("=" * 62)
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
