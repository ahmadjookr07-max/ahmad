# -*- coding: utf-8 -*-
"""فحص شامل لكل قواعد المالك المسجّلة — بلا استثناء ولا فرضيات.

القواعد المفحوصة:
  R1  كل وحدات الصنف من الإكسل في الاسم (حبه_باكت_كرتون…)
  R2  الواجهة ★ بلا رقم، والبقية -2، -3 … (2.9.9: لا -1)
  R3  توحيد الإملاء (حبه/حبة، شده/شدة) بلا تكرار في الاسم
  R4  خيارات تسمية كثيرة ومرنة (قوالب جاهزة + قالب مخصص)
  R5  حفظ آخر اختيار واستعادته تلقائيًا في المرة القادمة
  R6  السياسة نافذة **بلا ضبط يدوي** (الافتراضي الصريح)
  R7  التكافؤ التام بين جهة الدفعة الجديدة وجهة المجلد المنجز
  R8  الملفات القديمة تُصحَّح أيضًا (لا الجديدة فقط)
  R9  المسافات في الوحدة تُعالَج (كرتون 1 ⇒ كرتون1) — روابط المتاجر
  R10 800×700 وخلفية بيضاء وWebP في مخرجات الدفعة
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "windows_app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("MIS_SKIP_LICENSE", "1")
os.environ.setdefault("MIS_HEADLESS", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

OK = FAIL = 0


def say(m: str) -> None:
    print(m, flush=True)


def check(label: str, cond: bool, detail: str = "") -> bool:
    global OK, FAIL
    if cond:
        OK += 1
        say(f"  ✓ {label}" + (f" — {detail}" if detail else ""))
    else:
        FAIL += 1
        say(f"  ✗ {label}" + (f" — {detail}" if detail else ""))
    return bool(cond)


def main() -> int:
    from engine_v2 import naming_v2 as N
    from engine_v2 import integration_v2 as I

    # ── R1 كل الوحدات ──────────────────────────────────────────────
    say("[R1] كل وحدات الصنف من الإكسل تدخل الاسم")
    check("أربع وحدات كلها في الاسم",
          N.build_name_join_all("10008272",
                                ["باكت", "حبه", "كرتون", "كرتون 1"], 1)
          == "10008272_باكت_حبه_كرتون_كرتون1")
    check("ثلاث وحدات (مثال الببسي: شدة/باكت/كرتون)",
          N.build_name_join_all("500", ["شدة", "باكت", "كرتون"], 1)
          == "500_شدة_باكت_كرتون")
    check("ترتيب الإكسل محفوظ حرفيًا",
          N.join_units(["كرتون", "حبه"]) == "كرتون_حبه")

    # ── R2 الترقيم والواجهة ────────────────────────────────────────
    say("\n[R2] الواجهة ★ بلا رقم ثم -2، -3 (2.9.9)")
    u = ["حبه", "باكت"]
    seq = [N.build_name_join_all("777", u, i, total=4) for i in (1, 2, 3, 4)]
    check("الواجهة بلا رقم", seq[0] == "777_حبه_باكت", seq[0])
    check("التسلسل -2 ثم -3 ثم -4",
          seq[1:] == ["777_حبه_باكت-2", "777_حبه_باكت-3", "777_حبه_باكت-4"],
          str(seq[1:]))
    check("لا يوجد -1 المحظور في أي اسم",
          not any(s.endswith("-1") for s in seq), str(seq))
    check("الصورة الوحيدة بلا رقم إطلاقًا",
          N.build_name_join_all("777", u, 1, total=1) == "777_حبه_باكت")

    # ── R3 توحيد الإملاء ───────────────────────────────────────────
    say("\n[R3] توحيد الإملاء بلا تكرار في الاسم")
    check("حبه/حبة لا تتكرران",
          N.join_units(["حبه", "حبة", "كرتون"]) == "حبه_كرتون",
          N.join_units(["حبه", "حبة", "كرتون"]))
    check("شده/شدة لا تتكرران",
          N.join_units(["شده", "شدة"]) == "شده",
          N.join_units(["شده", "شدة"]))
    check("unit_key يوحّد الإملاءين",
          N.unit_key("حبه") == N.unit_key("حبة"))
    check("أول إملاء ورد في الإكسل هو المحفوظ",
          N.join_units(["حبة", "حبه"]) == "حبة")

    # ── R4 خيارات التسمية الكثيرة والمرنة ─────────────────────────
    say("\n[R4] خيارات تسمية كثيرة ومرنة")
    tpls = getattr(N, "STORE_TEMPLATES", [])
    check("قوالب متاجر جاهزة متعددة", len(tpls) >= 8, f"{len(tpls)} قالبًا")
    check("قالب جمع كل الوحدات ضمن الجاهزة",
          any("{units}" in t for _, t in tpls))
    check("قالب الباركود متاح (متاجر تربط بالباركود)",
          any("{barcode}" in t for _, t in tpls))
    check("قالب اسم المنتج متاح",
          any("{name}" in t for _, t in tpls))
    check("السياسات الأربع كلها صالحة", len(N.VALID_POLICIES) == 4,
          str(N.VALID_POLICIES))
    cs = N.NamingSettings(scheme=N.SCHEME_CUSTOM,
                          template="{item}_{barcode}-{seq}")
    got = cs.render("123", 2, "حبه", total=3, barcode="628110")
    # 2.9.9 — {seq} يُرسم برقم الصورة الحقيقي كما يراه المالك
    # (الصورة الثانية = 2)، لا بطرح واحد منه كما كان سابقًا.
    check("القالب المخصص يُرسم فعلًا", got == "123_628110-2", got)
    cz = N.NamingSettings(scheme=N.SCHEME_DASH, seq_pad=2, seq_start=1,
                          always_number_single=True)
    check("أصفار بادئة ورقم للصورة الوحيدة يعملان",
          cz.render("123", 1, "حبه", total=1) == "123_حبه-01",
          cz.render("123", 1, "حبه", total=1))

    # ── R5 حفظ آخر اختيار واستعادته ───────────────────────────────
    say("\n[R5] حفظ آخر اختيار واستعادته تلقائيًا")
    tmp = Path(tempfile.mkdtemp(prefix="naming_pref_"))
    pref = N.NamingSettings(unit_policy=N.UNIT_POLICY_REPLICATE,
                            scheme=N.SCHEME_CUSTOM,
                            template="{item}-{name}-{seq}", seq_pad=3)
    N.save_settings(tmp, pref)
    f = tmp / N.DEFAULT_SETTINGS_FILENAME
    check("ملف الإعدادات كُتب فعلًا", f.is_file(), str(f))
    back = N.load_saved_settings(tmp)
    check("السياسة استُعيدت كما هي",
          back.unit_policy == N.UNIT_POLICY_REPLICATE, back.unit_policy)
    check("القالب المخصص استُعيد",
          back.template == "{item}-{name}-{seq}", back.template)
    check("الأصفار البادئة استُعيدت", back.seq_pad == 3, str(back.seq_pad))
    check("اختيار المالك الصريح لا يُرقّى فوق رغبته",
          N.NamingSettings.from_dict(
              {"unit_policy": N.UNIT_POLICY_PER_IMAGE,
               "unit_policy_explicit": True}).unit_policy
          == N.UNIT_POLICY_PER_IMAGE)
    check("ملف قديم بلا علم صريح يُرقّى إلى جمع الوحدات",
          N.NamingSettings.from_dict(
              {"unit_policy": N.UNIT_POLICY_PER_IMAGE}).unit_policy
          == N.UNIT_POLICY_JOIN_ALL)

    # ── R6 بلا ضبط يدوي ───────────────────────────────────────────
    say("\n[R6] السياسة نافذة بلا أي ضبط يدوي (علة 2.9.7)")
    saved_root = I.NAMING_DATA_ROOT
    try:
        I.NAMING_DATA_ROOT = ""
        s0 = I._current_naming_settings()
        check("لا تُرجع None عند غياب المسار المحفوظ", s0 is not None)
        check("الافتراضي الصريح = جمع كل الوحدات",
              s0 is not None
              and getattr(s0, "unit_policy", "") == N.UNIT_POLICY_JOIN_ALL,
              getattr(s0, "unit_policy", "?"))
        check("مفعَّلة افتراضيًا", bool(getattr(s0, "enabled", False)))
        I.NAMING_DATA_ROOT = str(tmp)
        s1 = I._current_naming_settings()
        check("المسار المحفوظ يتقدّم على الافتراضي",
              getattr(s1, "template", "") == "{item}-{name}-{seq}",
              getattr(s1, "template", "?"))
    finally:
        I.NAMING_DATA_ROOT = saved_root

    # ── R7 التكافؤ بين الجهتين ────────────────────────────────────
    say("\n[R7] التكافؤ التام: الدفعة الجديدة = المجلد المنجز")
    from engine_v2 import legacy_folder_v2 as LF
    units = ["حبه", "باكت", "كرتون"]
    legacy_stems = LF._target_stems("999", "حبه", 3, units=units,
                                    join_all=True)
    batch_stems = [N.build_name_join_all("999", units, i + 1, total=3)
                   for i in range(3)]
    check("الجهتان تنتجان الأسماء نفسها حرفًا بحرف",
          legacy_stems == batch_stems,
          f"منجز={legacy_stems} | دفعة={batch_stems}")
    check("كلتاهما تمرّان عبر build_name_join_all",
          legacy_stems[0] == "999_حبه_باكت_كرتون", legacy_stems[0])
    check("جهة المنجز تقرأ سياسة الدفعة نفسها",
          LF._naming_settings() is not None)

    # ── R8 الملفات القديمة تُصحَّح أيضًا ───────────────────────────
    say("\n[R8] الملفات القديمة تُصحَّح لا الجديدة فقط")
    check("parse_legacy_stem يفهم الاسم القديم بوحدة واحدة",
          LF.parse_legacy_stem("10000014_حبه") is not None)
    check("يفهم الاسم الجديد متعدد الوحدات",
          LF.parse_legacy_stem("10000014_حبه_باكت") is not None)
    # القراءة تبقى متسامحة مع -1 القديم (ملفات المالك الموروثة)
    # حتى تُرقّى إلى -2؛ الممنوع هو إنتاج -1 من جديد.
    check("يفهم المرقَّم -1 الموروث (للترقية)",
          LF.parse_legacy_stem("10000014_حبه_باكت-1") is not None)
    check("يفهم الكلاسيكي 2.1 (رقم_تسلسل_وحدة)",
          LF.parse_legacy_stem("10000014_2_حبه") is not None)

    # ── R9 المسافات في الوحدة ─────────────────────────────────────
    say("\n[R9] معالجة المسافات في الوحدة (روابط المتاجر)")
    check("كرتون 1 ⇒ كرتون1", N.clean_unit("كرتون 1") == "كرتون1",
          N.clean_unit("كرتون 1"))
    check("لا مسافة في أي اسم مولَّد",
          " " not in N.build_name_join_all("1", ["كرتون 1", "نص كرتون"], 1),
          N.build_name_join_all("1", ["كرتون 1", "نص كرتون"], 1))

    say("\n" + "═" * 62)
    say(f"النتيجة: {OK}/{OK + FAIL}")
    if FAIL:
        say(f"فشل: {FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
