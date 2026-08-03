"""اختبار انحدار: يمنع عودة تشوّه العربية (Mojibake) في المُثبِّت.

خلفية العطب
-----------
صوّر المالك شريط مهام ويندوز وفيه اسم البرنامج يظهر `Ø§Ù...` بدل
`استوديو المالك`. هذا التوقيع يعني بايتات UTF-8 قُرئت بصفحة ترميز
أحادية البايت. المتهم كان `makensis`: فهو يستنتج ترميز ملف `.nsi`
من علامة الترتيب BOM، وعند غيابها يقع على صفحة ترميز النظام
(1252 على أجهزة البناء الإنجليزية، 1256 على العربية).

وجود `Unicode true` لا يكفي: تلك التعليمة تحكم صيغة **إخراج**
المُثبِّت (UTF-16 داخليًا) ولا علاقة لها بترميز **المصدر**.

ما يفرضه هذا الاختبار
---------------------
1. كل ملف `.nsi` يبدأ بـBOM من نوع UTF-8.
2. كل ملف `.nsi` يعلن `Unicode true` (إخراج UTF-16).
3. لا ملف يحوي علامات تشوّه معروفة.
4. ملفات النصوص المرافقة (الاتفاقية) بترميز يفهمه NSIS ببداهة.
5. محاكاة قراءة makensis على صفحتي 1252 و1256 تعيد النص العربي
   سليمًا حرفيًا.

يُشغَّل مستقلاً: `python3 tests/test_installer_encoding.py`
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NSI_DIR = REPO / "build" / "windows"

UTF8_BOM = b"\xef\xbb\xbf"
UTF16LE_BOM = b"\xff\xfe"
UTF16BE_BOM = b"\xfe\xff"

ARABIC_CHAR = re.compile(r"[\u0600-\u06FF]")
ARABIC_RUN = re.compile(r"[\u0600-\u06FF][\u0600-\u06FF ]{2,}")
UNICODE_DIRECTIVE = re.compile(r"(?im)^\ufeff?[ \t]*Unicode[ \t]+(true|on|1)\b")

# توقيعات التشوّه: UTF-8 مقروء بـ1252، وUTF-8 مقروء بـ1256
MOJIBAKE_SIGNS = ("Ø§", "ÙØ", "Ø¥", "Ã˜", "Ø¹", "Ø±", "طھ", "ظ\u0084", "ط§")

# صفحات الترميز التي قد يقع عليها makensis عند غياب BOM
FALLBACK_CODEPAGES = {
    "cp1252": "مُشغِّل بناء إنجليزي (windows-latest)",
    "cp1256": "جهاز بلغة عربية",
}

_failures: list[str] = []
_checks = 0


def check(condition: bool, label: str) -> bool:
    global _checks
    _checks += 1
    if condition:
        print(f"  PASS  {label}")
        return True
    print(f"  FAIL  {label}")
    _failures.append(label)
    return False


def decode_like_makensis(raw: bytes, fallback: str) -> str:
    """يعيد إنتاج منطق كشف الترميز في makensis."""
    if raw.startswith(UTF8_BOM):
        return raw[3:].decode("utf-8", "replace")
    if raw.startswith(UTF16LE_BOM):
        return raw[2:].decode("utf-16-le", "replace")
    if raw.startswith(UTF16BE_BOM):
        return raw[2:].decode("utf-16-be", "replace")
    return raw.decode(fallback, "replace")


def first_arabic_run(text: str) -> str:
    match = ARABIC_RUN.search(text)
    return match.group(0).strip() if match else ""


def test_nsi_files() -> None:
    scripts = sorted(NSI_DIR.glob("*.nsi"))
    check(bool(scripts), f"وُجدت سكربتات NSIS ({len(scripts)})")

    for path in scripts:
        raw = path.read_bytes()
        name = path.name

        check(raw.startswith(UTF8_BOM), f"{name}: يبدأ بـUTF-8 BOM")

        body = raw[3:] if raw.startswith(UTF8_BOM) else raw
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            check(False, f"{name}: UTF-8 صالح ({exc})")
            continue
        check(True, f"{name}: UTF-8 صالح")

        check(bool(UNICODE_DIRECTIVE.search(text)),
              f"{name}: يعلن 'Unicode true'")

        dirty = [s for s in MOJIBAKE_SIGNS if s in text]
        check(not dirty, f"{name}: خالٍ من علامات التشوّه"
                         + (f" (وُجد {dirty})" if dirty else ""))


def test_makensis_simulation() -> None:
    """أهم اختبار: النص العربي يبقى سليمًا مهما كانت صفحة ترميز النظام."""
    for path in sorted(NSI_DIR.glob("*.nsi")):
        raw = path.read_bytes()
        truth = raw[3:].decode("utf-8") if raw.startswith(UTF8_BOM) \
            else raw.decode("utf-8", "replace")
        if not ARABIC_CHAR.search(truth):
            continue
        expected = first_arabic_run(truth)
        for cp, label in FALLBACK_CODEPAGES.items():
            decoded = decode_like_makensis(raw, cp)
            got = first_arabic_run(decoded)
            check(got == expected,
                  f"{path.name}: العربية سليمة على {label} [{cp}]"
                  + ("" if got == expected else f" — قرأ {got[:24]!r}"))


def test_regression_guard() -> None:
    """يتأكد أن الاختبار نفسه قادر على كشف العطب لو عاد."""
    sample = NSI_DIR / "installer_v295.nsi"
    if not sample.is_file():
        return
    raw = sample.read_bytes()
    truth = raw[3:].decode("utf-8")
    expected = first_arabic_run(truth)
    # انزع BOM ⇒ يجب أن يظهر التشوّه، وإلا فالاختبار عديم القيمة
    stripped = raw[3:]
    corrupted = decode_like_makensis(stripped, "cp1256")
    check(first_arabic_run(corrupted) != expected,
          "حارس الانحدار: نزع BOM يُنتج تشوّهًا (الاختبار فعّال)")


def test_companion_text_files() -> None:
    for path in sorted(NSI_DIR.glob("*.txt")):
        raw = path.read_bytes()
        text_ok = (raw.startswith(UTF8_BOM)
                   or raw.startswith(UTF16LE_BOM)
                   or raw.startswith(UTF16BE_BOM))
        try:
            sample = raw.decode("utf-16-le" if raw.startswith(UTF16LE_BOM)
                                else "utf-8-sig", "replace")
        except Exception:
            sample = ""
        if ARABIC_CHAR.search(sample):
            check(text_ok, f"{path.name}: ملف عربي مرافق يحمل BOM")
        else:
            check(True, f"{path.name}: لاتيني — لا يحتاج BOM")


def main() -> int:
    print("=== اختبار ترميز مُثبِّتات NSIS ===\n")
    print("[1] بنية ملفات .nsi")
    test_nsi_files()
    print("\n[2] محاكاة كشف الترميز في makensis")
    test_makensis_simulation()
    print("\n[3] الملفات النصية المرافقة")
    test_companion_text_files()
    print("\n[4] حارس فعالية الاختبار")
    test_regression_guard()

    print("\n" + "=" * 58)
    passed = _checks - len(_failures)
    print(f"النتيجة: {passed}/{_checks} فحصًا ناجحًا")
    if _failures:
        print("\nالإخفاقات:")
        for f in _failures:
            print(f"  · {f}")
        return 1
    print("كل فحوص الترميز نجحت — العربية لن تتشوّه في المُثبِّت")
    return 0


if __name__ == "__main__":
    sys.exit(main())
