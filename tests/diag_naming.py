# -*- coding: utf-8 -*-
"""قياس مهمة التسمية (ت-9) — معيار مصحّح.

قرار المستخدم (2026-08-01): «يجب أن يكون المسمى كما ذكرنا سابقًا» —
الوحدة تُقرأ حرفيًا من الإكسل ولا يُغيَّر إملاؤها في اسم الملف.
لذلك التطبيع يُقاس على unit_key/same_unit (المقارنة الداخلية) لا على
clean_unit (الإملاء الظاهر). الفحص القديم كان يتوقع تغيير الإملاء وهو
عكس المطلوب، فصُحّح.

يقيس:
  A) هل NAMING_DATA_ROOT موصول من native_app عند البدء؟
  B) هل تُوحّد الاختلافات الإملائية للمقارنة مع حفظ الإملاء الأصلي؟
  C) هل نافذة سياسة التسمية موصولة بزر؟
  D) هل نافذة إعادة التسمية الجماعية موصولة بزر؟
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path("/home/ubuntu/market-image-studio-v2")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "windows_app"))

fails = 0


def check(name, ok, detail=""):
    global fails
    if not ok:
        fails += 1
    print(f"[{'PASS' if ok else 'FAIL'}] {name}"
          + (f" — {detail}" if detail else ""))


native = (ROOT / "windows_app" / "native_app.py").read_text(encoding="utf-8")


def _strip_comments(src: str) -> str:
    """يجرد تعليقات الأسطر — ذكر اسم محذوف في تعليق
    من نوع «حُذف كذا» ليس تكرارًا ولا منفذًا حقيقيًا."""
    out = []
    for line in src.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


native_code = _strip_comments(native)

print("=" * 70)
print("A) توصيل جذر بيانات التسمية")
print("=" * 70)
check("native_app ينادي set_naming_data_root",
      "set_naming_data_root" in native,
      "بدونها _current_naming_settings ترجع None دائمًا")

# التوصيل يجب أن يكون في __init__ لا في تحميل الإكسل وحده
init_slice = native[:native.find("def _setup_window")]
check("التوصيل يحدث عند بدء التطبيق لا عند تحميل الإكسل فقط",
      "set_naming_data_root" in init_slice,
      "لو كان في تحميل الإكسل فقط، السياسة تُهمل بلا إكسل")

tmp = Path("/tmp/naming_probe")
if tmp.exists():
    import shutil
    shutil.rmtree(tmp)
tmp.mkdir(parents=True)
(tmp / "naming_settings.json").write_text(json.dumps({
    "unit_policy": "per_image", "default_unit": "حبه",
    "template": "{item}_{unit}-{seq}", "scheme": "classic",
    "enabled": True, "seq_start": 1, "seq_pad": 0,
    "always_number_single": False}, ensure_ascii=False), encoding="utf-8")

from engine_v2 import integration_v2 as iv  # noqa: E402

iv.set_naming_data_root(str(tmp))
after = iv._current_naming_settings()
check("السياسة المحفوظة تُقرأ من القرص",
      after is not None and after.scheme == "classic",
      f"scheme={getattr(after, 'scheme', None)}")

print()
print("=" * 70)
print("B) تطبيع الإملاء للمقارنة مع حفظ الإملاء الأصلي في الاسم")
print("=" * 70)
from engine_v2.naming_v2 import (clean_unit, unit_key, same_unit,  # noqa: E402
                                 dedupe_units, join_units,
                                 build_name_join_all)

pairs = [("حبه", "حبة"), ("شده", "شدة"), ("علبه", "علبة"),
         ("كرتون", "كرتون"), ("باكت", "باكت")]
for a, b in pairs:
    check(f"المقارنة توحّد {a} == {b}", same_unit(a, b),
          f"key: {unit_key(a)!r} vs {unit_key(b)!r}")

# الشرط المعاكس: الإملاء الأصلي محفوظ حرفيًا في اسم الملف
check("clean_unit لا تغيّر إملاء الإكسل (حبه تبقى حبه)",
      clean_unit("حبه") == "حبه", f"={clean_unit('حبه')!r}")
check("clean_unit لا تغيّر إملاء الإكسل (حبة تبقى حبة)",
      clean_unit("حبة") == "حبة", f"={clean_unit('حبة')!r}")

# وحدات مختلفة فعلًا يجب ألا تُدمج
check("وحدات مختلفة لا تُدمج (حبة ≠ كرتون)", not same_unit("حبة", "كرتون"))
check("وحدات مختلفة لا تُدمج (شدة ≠ باكت)", not same_unit("شدة", "باكت"))

# إزالة التكرار الإملائي مع حفظ أول إملاء
d1 = dedupe_units(["حبه", "حبة", "كرتون"])
check("إزالة التكرار الإملائي تحفظ أول إملاء",
      d1 == ["حبه", "كرتون"], f"={d1}")
d2 = dedupe_units(["حبة", "حبه"])
check("أول إملاء في الإكسل هو الباقي (حبة قبل حبه)",
      d2 == ["حبة"], f"={d2}")

j1 = join_units(["حبه", "حبة", "كرتون"])
check("join_units لا تكرر الوحدة بإملاءين",
      j1 == "حبه_كرتون", f"={j1}")

full = build_name_join_all("10001102", ["حبه", "حبة", "كرتون"])
check("الاسم النهائي بلا تكرار إملائي",
      full == "10001102_حبه_كرتون", f"={full}")

print()
print("=" * 70)
print("C/D) ربط نوافذ التسمية بأزرار في الواجهة")
print("=" * 70)
check("نافذة سياسة التسمية موصولة",
      bool(re.search(r"UnitNamingDialog|v2_open_unit_naming", native)),
      "لا منفذ لنافذة سياسة التسمية")
check("زر سياسة التسمية موجود ومربوط بمعالج",
      "naming_policy_button" in native
      and "_open_naming_policy" in native,
      "الزر أو المعالج ناقص")
# 2.9.5 — أداة إعادة التسمية المستقلة حُذفت: قرار المالك «لا تكرار».
# الفحص انعكس: نتأكد من غيابها ومن وجود المنفذ الموحد بدلها.
check("أداة التسمية المستقلة محذوفة (لا تكرار)",
      "BulkRenameDialog" not in native_code
      and "_open_bulk_rename" not in native_code,
      "ما زال هناك منفذ قديم لأداة تسمية مستقلة")
check("زر «فتح مجلد منجز» هو المنفذ الموحد",
      "فتح مجلد منجز" in native
      and "_open_legacy_folder" in native,
      "الزر الموحد أو معالجه ناقص")
check("أزرار التسمية تتبع نظام المقياس (لا أرقام صلبة)",
      bool(re.search(
          r"_register_metric\(self\.naming_policy_button", native)),
      "زر بارتفاع صلب يُقص على الشاشات القصيرة")
check("السياسة تُعاد قراءتها بعد الحفظ بلا إعادة تشغيل",
      "_after_naming_policy_changed" in native,
      "المستخدم يحفظ ثم لا يرى الأثر حتى يعيد التشغيل")

print()
print(f"failures={fails}")
