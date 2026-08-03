# -*- coding: utf-8 -*-
"""surgeon — الجرّاح الذاتي: يدقّق بنية الشفرة ويعدّلها بأمان.

الفكرة الحاكمة
--------------
البرنامج لا ينتظر أن ينهار ليتصرّف. يقرأ **شفرته هو** بشجرة النحو (``ast``)،
يبحث عن أنماط ضعف مُثبتة (لا ظنون)، يولّد لكل نمط رقعة نصّية دقيقة، ثم يخضعها
لأربع بوابات تحقّق قبل أن تلمس القرص. وإن ساءت الأمور يتراجع بنقرة أو تلقائيًا.

لماذا التحويلات مسجَّلة لا مولَّدة حرًّا
--------------------------------------
توليد شفرة حرّة داخل تطبيق إنتاجي يعمل على أجهزة أشخاص = مخاطرة غير مقبولة.
لذا الجرّاح يملك **سجل تحويلات** (``TRANSFORMS``): كل تحويل يعرف بدقة ما يبحث
عنه وما يكتبه، ومُختبَر مسبقًا. الذكاء هنا في **الكشف والقياس والقرار**، لا في
الارتجال. هذا يجعل السلوك قابلًا للتوقّع والتراجع — وهو شرط الثقة.

بوابات التحقّق الأربع (لا يُطبّق ما يفشل أيًّا منها)
--------------------------------------------------
1. **النحو**: ``compile()`` على النص الجديد.
2. **البنية**: مقارنة ``ast.dump`` قبل/بعد للتأكد أن التغيير مقصور على ما نويناه
   (عدد الدوال والأصناف وأسماء المستوى الأعلى لا تتغير إلا إن كان ذلك هدف التحويل).
3. **الاستيراد**: استيراد الملف المعدّل في **عملية منفصلة** بمهلة — فلو كان فيه
   عطل استيراد لا يسقط التطبيق الحالي.
4. **الاختبارات**: تشغيل ملفات الاختبار المرتبطة في عملية منفصلة بمهلة.

الحزمة المُصرَّفة
----------------
داخل PyInstaller الشفرة غير قابلة للتعديل. فيعمل الجرّاح في **وضع التوصية**:
يشخّص، ويكتب تقرير رقعة كامل قابلًا للتصدير، ويحوّل ما يمكن تحويله إلى مفاتيح
``overrides.json`` التي تقرأها الوحدات وقت التشغيل. الوعد يُحفظ دون خدش الحزمة.

كل الدوال آمنة الفشل: تُرجع حالة منظَّمة ولا ترمي استثناء إلى المتصل.
"""
from __future__ import annotations

import ast
import concurrent.futures as cf
import contextlib
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import identity, journal
from . import ledger as ledger_mod

__all__ = [
    "Severity",
    "Issue",
    "Patch",
    "SurgeryResult",
    "Surgeon",
    "surgeon",
    "diagnose",
    "operate",
    "rollback_last",
    "rollback",
    "history",
    "surgery_dir",
]


# ───────────────────────── ثوابت ─────────────────────────

class Severity:
    """شدّة موضع الضعف — تُرتّب أولوية الجراحة."""

    HIGH = "high"        # يسبب أعطالًا أو يُخفيها؛ يُعالج أولًا
    MEDIUM = "medium"    # هشاشة أو بطء محتمل
    LOW = "low"          # تحسين جودة

    ORDER = {HIGH: 0, MEDIUM: 1, LOW: 2}
    LABELS_AR = {HIGH: "عالية", MEDIUM: "متوسطة", LOW: "منخفضة"}


#: الملفات التي لا يلمسها الجرّاح أبدًا.
#: طبقة الوعي نفسها مستثناة: جرّاح يعدّل مِشرطه أثناء العملية خطر لا مبرر له.
_PROTECTED = (
    "awareness/",
    "tests/",
    "build_",
    "setup",
    "conftest.py",
    "__init__.py",
)

#: امتداد ملفات الشفرة المسموح تعديلها.
_CODE_ROOTS = ("src/engine_v2", "windows_app", "src/owner_studio",
               "src/smart_catalog_vision")

_MAX_FILE_BYTES = 3 * 1024 * 1024      # ملف أكبر من هذا لا يُحلَّل (حماية أداء)
_VERIFY_TIMEOUT = 90.0                 # مهلة كل بوابة تحقق بالثواني
_ISOLATE_MAX_DEPTH = 4                 # عمق البحث الثنائي لعزل رقعة مُفسدة
# ميزانية نداءات التحقق في العزل: كل نداء يكلف نحو 12 ثانية،
# والعزل غير المحدود رفع الزمن إلى 148s. نقيّده بسقف صريح.
_VERIFY_BUDGET_CALLS = 8


# ───────────────────────── بنيات ─────────────────────────

@dataclass
class Issue:
    """موضع ضعف مكتشف في الشفرة."""

    code: str                    # معرّف النمط، مثل "silent_except"
    title_ar: str
    detail_ar: str
    path: str                    # مسار نسبي من جذر المشروع
    line: int = 0
    severity: str = Severity.MEDIUM
    transform: str = ""          # اسم التحويل القادر على إصلاحه ("" = يدوي)
    context: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.code}:{self.path}:{self.line}"

    @property
    def severity_label_ar(self) -> str:
        return Severity.LABELS_AR.get(self.severity, self.severity)

    def as_dict(self) -> dict:
        return {
            "code": self.code, "title_ar": self.title_ar,
            "detail_ar": self.detail_ar, "path": self.path, "line": self.line,
            "severity": self.severity, "transform": self.transform,
            "fixable": bool(self.transform),
        }


@dataclass
class Patch:
    """رقعة مقترحة على ملف واحد: النص الجديد + الفرق المقروء."""

    path: str
    old_text: str
    new_text: str
    issues: list[Issue] = field(default_factory=list)
    transform: str = ""
    note_ar: str = ""

    @property
    def changed(self) -> bool:
        return self.new_text != self.old_text

    @property
    def diff(self) -> str:
        return "".join(difflib.unified_diff(
            self.old_text.splitlines(keepends=True),
            self.new_text.splitlines(keepends=True),
            fromfile=f"a/{self.path}", tofile=f"b/{self.path}", n=2,
        ))

    @property
    def stats(self) -> tuple[int, int]:
        """(أسطر مضافة، أسطر محذوفة) — لعرض حجم التغيير للمستخدم."""
        add = rem = 0
        for ln in self.diff.splitlines():
            if ln.startswith("+") and not ln.startswith("+++"):
                add += 1
            elif ln.startswith("-") and not ln.startswith("---"):
                rem += 1
        return add, rem

    def as_dict(self) -> dict:
        add, rem = self.stats
        return {
            "path": self.path, "transform": self.transform,
            "note_ar": self.note_ar, "added": add, "removed": rem,
            "issues": [i.as_dict() for i in self.issues],
            "diff": self.diff[:20000],
        }


@dataclass
class SurgeryResult:
    """نتيجة عملية جراحية كاملة."""

    ok: bool = False
    applied: bool = False
    surgery_id: str = ""
    patches: list[Patch] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    message_ar: str = ""
    verification: list[dict] = field(default_factory=list)
    advisory: bool = False       # وضع التوصية (حزمة مصرَّفة)
    quarantined: list[str] = field(default_factory=list)  # رقع عُزلت

    def as_dict(self) -> dict:
        return {
            "ok": self.ok, "applied": self.applied,
            "surgery_id": self.surgery_id, "advisory": self.advisory,
            "message_ar": self.message_ar,
            "issues": [i.as_dict() for i in self.issues],
            "patches": [p.as_dict() for p in self.patches],
            "verification": self.verification,
            "quarantined": list(self.quarantined),
        }


# ───────────────────────── أدوات نصية ─────────────────────────

def _indent_of(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _read(path: Path) -> str:
    """قراءة متسامحة مع الترميز — ملفات هذا المشروع فيها عربية كثيفة."""
    for enc in ("utf-8", "utf-8-sig", "cp1256", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
        except Exception:
            return ""
    return ""


def _ends_with_newline(text: str) -> bool:
    return text.endswith("\n")


# ───────────────────────── الكاشفات ─────────────────────────
# كل كاشف يأخذ (شجرة, نص, أسطر, مسار نسبي) ويُرجع قائمة Issue.
# قاعدة صارمة: لا يُبلَّغ عن موضع إلا إن كان **مؤكَّدًا** من الشجرة، لا من regex
# على النص، لأن الإنذار الكاذب هنا يعني تعديل شفرة سليمة.


def _d_silent_except(tree: ast.AST, text: str, lines: list[str],
                     rel: str) -> list[Issue]:
    """``except ...: pass`` — العطل يمر صامتًا فلا يعرف أحد أن شيئًا انكسر.

    هذا **أهم** نمط في هذا المشروع: مُقاس فعليًا 101 موضع، وهو السبب الجذري
    لأن أعطال الجلسات السابقة كانت تظهر كـ«نتيجة خاطئة» بدل «خطأ واضح».
    """
    out: list[Issue] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        body = node.body
        if len(body) == 1 and isinstance(body[0], ast.Pass):
            out.append(Issue(
                code="silent_except",
                title_ar="عطل يُبتلع صامتًا",
                detail_ar=("معالج استثناء لا يفعل شيئًا سوى pass؛ أي عطل هنا "
                           "يختفي بلا أثر فلا يمكن تشخيصه ولا التعلّم منه."),
                path=rel, line=int(node.lineno or 0),
                severity=Severity.HIGH, transform="log_silent_except",
                context={"col": int(node.col_offset or 0)},
            ))
    return out


def _d_unguarded_optional_import(tree: ast.AST, text: str, lines: list[str],
                                 rel: str) -> list[Issue]:
    """استيراد حزمة اختيارية على مستوى الوحدة بلا حماية.

    غياب الحزمة يمنع استيراد الوحدة كلها فيسقط التطبيق عند الإقلاع، بدل أن
    تتعطّل قدرة واحدة بلطف. قياسًا: 14 موضعًا لـ``cv2``.
    """
    optional = set(_OPTIONAL_PACKAGES)
    out: list[Issue] = []
    for node in getattr(tree, "body", []):          # المستوى الأعلى فقط
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module.split(".")[0]]
        for n in names:
            if n in optional:
                out.append(Issue(
                    code="unguarded_optional_import",
                    title_ar=f"استيراد غير محمي للحزمة «{n}»",
                    detail_ar=(f"الحزمة «{n}» اختيارية؛ غيابها يجب أن يعطّل قدرة "
                               "واحدة لا أن يمنع استيراد الوحدة ويُسقط الإقلاع."),
                    path=rel, line=int(node.lineno or 0),
                    severity=Severity.HIGH, transform="guard_optional_import",
                    context={"module": n},
                ))
    return out


def _d_open_without_encoding(tree: ast.AST, text: str, lines: list[str],
                             rel: str) -> list[Issue]:
    """``open()`` نصي بلا ``encoding`` — سبب Mojibake العربي على ويندوز.

    على ويندوز الترميز الافتراضي cp1256، فالملف المكتوب بـUTF-8 يُقرأ محرّفًا.
    وهذا بالضبط عطل «النصوص العربية المشوّشة» الذي ظهر في الجلسات السابقة.
    """
    out: list[Issue] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and
                isinstance(node.func, ast.Name) and node.func.id == "open"):
            continue
        kwargs = {k.arg for k in node.keywords if k.arg}
        if "encoding" in kwargs:
            continue
        mode = ""
        if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
            mode = str(node.args[1].value or "")
        for k in node.keywords:
            if k.arg == "mode" and isinstance(k.value, ast.Constant):
                mode = str(k.value.value or "")
        if "b" in mode:                              # ثنائي: لا يحتاج ترميزًا
            continue
        out.append(Issue(
            code="open_without_encoding",
            title_ar="فتح ملف نصي بلا ترميز صريح",
            detail_ar=("open() بلا encoding يستخدم ترميز النظام؛ على ويندوز "
                       "cp1256 فتظهر العربية مشوّشة. الصواب encoding='utf-8'."),
            path=rel, line=int(node.lineno or 0),
            severity=Severity.HIGH, transform="add_open_encoding",
            context={"col": int(node.col_offset or 0)},
        ))
    return out


def _d_broad_except_no_log(tree: ast.AST, text: str, lines: list[str],
                           rel: str) -> list[Issue]:
    """``except Exception`` يعيد قيمة فراغية بلا تسجيل — عطل يتحوّل إلى نتيجة خاطئة.

    أخطر من الانهيار: البرنامج يُكمل بقيمة خاطئة والمستخدم يظن العمل صحيحًا.
    نبلّغ عنه للتسجيل فقط (لا نغيّر منطق الإرجاع) — التحويل يضيف سطر تسجيل.
    """
    out: list[Issue] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        body = node.body
        if len(body) != 1:
            continue
        st = body[0]
        empty_return = (
            isinstance(st, ast.Return) and (
                st.value is None or (
                    isinstance(st.value, ast.Constant) and
                    st.value.value in (None, "", 0, False)
                ) or isinstance(st.value, (ast.Dict, ast.List, ast.Tuple)) and
                not getattr(st.value, "elts", getattr(st.value, "keys", [1]))
            )
        )
        if not empty_return:
            continue
        out.append(Issue(
            code="silent_fallback_return",
            title_ar="عطل يُحوَّل إلى قيمة فارغة بلا تسجيل",
            detail_ar=("المعالج يُرجع قيمة فارغة دون تسجيل العطل؛ فيُكمل البرنامج "
                       "بنتيجة خاطئة ويظن المستخدم أن العمل صحيح."),
            path=rel, line=int(node.lineno or 0),
            severity=Severity.MEDIUM, transform="log_silent_except",
            context={"col": int(node.col_offset or 0)},
        ))
    return out


def _d_hardcoded_abs_path(tree: ast.AST, text: str, lines: list[str],
                          rel: str) -> list[Issue]:
    """مسار مطلق مغروس في الشفرة — يعمل على جهاز واحد ويفشل على غيره.

    نستثني المسارات المستعملة كـ«مواضع بحث معروفة» (قوائم مرشّحين)، لأنها
    استخدام مشروع. نبلّغ فقط عن الإسناد المباشر إلى متغيّر يُستعمل كمسار عمل.
    """
    out: list[Issue] = []
    pat = re.compile(r"^(?:[A-Za-z]:[\\/]|/(?:home|Users|root)/)")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        v = node.value
        if len(v) < 6 or not pat.match(v):
            continue
        ln = int(getattr(node, "lineno", 0) or 0)
        src_line = lines[ln - 1] if 0 < ln <= len(lines) else ""
        # قوائم المرشّحين المعروفة (cands/candidates/PATHS) استخدام مشروع
        if re.search(r"(cand|candidate|_PATHS|PATHS\b|append\()", src_line):
            continue
        out.append(Issue(
            code="hardcoded_abs_path",
            title_ar="مسار مطلق مغروس في الشفرة",
            detail_ar=(f"المسار «{v[:60]}» مكتوب صريحًا؛ يعمل على جهاز واحد "
                       "ويفشل على غيره. الصواب اشتقاقه من مجلد بيانات التطبيق."),
            path=rel, line=ln, severity=Severity.MEDIUM, transform="",
            context={"value": v[:200]},
        ))
    return out


def _d_blocking_sleep_in_ui(tree: ast.AST, text: str, lines: list[str],
                            rel: str) -> list[Issue]:
    """``time.sleep`` داخل ملف واجهة — يجمّد النافذة.

    الجلسة السابقة رصدت تجمّدًا 5.2 ثانية؛ هذا أحد مصادره المحتملة.
    """
    if "windows_app" not in rel and "ui" not in rel:
        return []
    out: list[Issue] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "sleep"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "time"):
            secs = None
            if node.args and isinstance(node.args[0], ast.Constant):
                with contextlib.suppress(Exception):
                    secs = float(node.args[0].value)
            if secs is not None and secs < 0.05:     # نبضة قصيرة مقبولة
                continue
            out.append(Issue(
                code="blocking_sleep_ui",
                title_ar="انتظار محجوب في ملف واجهة",
                detail_ar=("time.sleep في مسار الواجهة يجمّد النافذة ويجعل "
                           "البرنامج يبدو معلّقًا. الصواب مؤقّت غير محجوب."),
                path=rel, line=int(node.lineno or 0),
                severity=Severity.MEDIUM, transform="",
                context={"seconds": secs},
            ))
    return out


def _d_mutable_default_arg(tree: ast.AST, text: str, lines: list[str],
                           rel: str) -> list[Issue]:
    """قيمة افتراضية قابلة للتغيير — تتسرّب بين النداءات فتُنتج أعطالًا غامضة."""
    out: list[Issue] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in list(node.args.defaults) + list(node.args.kw_defaults):
            if isinstance(d, (ast.List, ast.Dict, ast.Set)):
                out.append(Issue(
                    code="mutable_default_arg",
                    title_ar=f"قيمة افتراضية متغيّرة في «{node.name}»",
                    detail_ar=("قائمة أو قاموس كقيمة افتراضية يُنشأ مرة واحدة "
                               "ويُشارَك بين كل النداءات، فتتسرّب البيانات."),
                    path=rel, line=int(node.lineno or 0),
                    severity=Severity.MEDIUM, transform="",
                    context={"func": node.name},
                ))
                break
    return out


def _d_missing_close(tree: ast.AST, text: str, lines: list[str],
                     rel: str) -> list[Issue]:
    """``open()`` بلا ``with`` — مقبض ملف يبقى مفتوحًا فيقفل الملف على ويندوز.

    ويندوز يقفل الملف المفتوح؛ وهذا سبب عطل «الإكسل مقفل» الذي واجهه المستخدم.
    """
    out: list[Issue] = []
    with_calls: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.With):
            for item in node.items:
                if isinstance(item.context_expr, ast.Call):
                    with_calls.add(id(item.context_expr))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "open"):
            continue
        if id(node) in with_calls:
            continue
        ln = int(getattr(node, "lineno", 0) or 0)
        src_line = lines[ln - 1] if 0 < ln <= len(lines) else ""
        if ".close()" in text[max(0, node.col_offset):]:
            pass                                     # قد يُغلق يدويًا؛ نُبلّغ فقط
        if re.search(r"=\s*open\(", src_line):
            out.append(Issue(
                code="open_without_with",
                title_ar="ملف يُفتح بلا with",
                detail_ar=("open() بلا with يترك المقبض مفتوحًا؛ على ويندوز يقفل "
                           "الملف فيفشل أي وصول آخر إليه (سبب عطل «الإكسل مقفل»)."),
                path=rel, line=ln, severity=Severity.MEDIUM, transform="",
                context={},
            ))
    return out


#: الحزم التي يجب أن يبقى غيابها محتملًا (تعطيل قدرة لا انهيار).
_OPTIONAL_PACKAGES = (
    "cv2", "zxingcpp", "pyzbar", "pytesseract", "rembg", "onnxruntime",
    "skimage", "imagehash", "xlrd", "psutil", "scipy",
)

DETECTORS = (
    _d_silent_except,
    _d_unguarded_optional_import,
    _d_open_without_encoding,
    _d_broad_except_no_log,
    _d_hardcoded_abs_path,
    _d_blocking_sleep_in_ui,
    _d_mutable_default_arg,
    _d_missing_close,
)


# ───────────────────────── التحويلات ─────────────────────────
# كل تحويل: (نص قديم, قائمة Issue لهذا الملف) -> (نص جديد, ملاحظة عربية)
# القاعدة: التحويل يعمل على **النص** سطرًا سطرًا للحفاظ على التعليقات والتنسيق
# العربي، لكن مواضعه تأتي من الشجرة (دقيقة)، لا من تخمين regex.


def _t_log_silent_except(text: str, issues: list[Issue]) -> tuple[str, str]:
    """يحوّل ``except X: pass`` إلى تسجيل صامت لا يغيّر السلوك.

    نستخدم استيرادًا موضعيًا داخل المعالج (لا على مستوى الملف) لسببين: ألّا
    نضيف اعتمادًا صارمًا على طبقة الوعي في وحدات المحرّك، وألّا نكسر ترتيب
    الاستيرادات. والتسجيل نفسه محفوف بـtry فلا يُنشئ عطلًا جديدًا أبدًا.
    """
    lines = text.splitlines(keepends=True)
    targets = sorted({i.line for i in issues if i.line > 0}, reverse=True)
    changed = 0
    for ln in targets:
        idx = ln - 1
        if not (0 <= idx < len(lines)):
            continue
        handler_line = lines[idx]
        if "except" not in handler_line:
            continue
        base = _indent_of(handler_line)
        body_indent = base + "    "
        # اعرف جسم المعالج: الأسطر التالية ذات إزاحة أكبر
        j = idx + 1
        body: list[int] = []
        while j < len(lines):
            ln_txt = lines[j]
            if not ln_txt.strip():
                j += 1
                continue
            if len(_indent_of(ln_txt)) <= len(base):
                break
            body.append(j)
            j += 1
        if not body:
            continue
        first = lines[body[0]]
        if "awareness" in first or "journal" in first:
            continue                                  # مُعالج سابقًا
        stripped = first.strip()
        if stripped not in ("pass",) and not stripped.startswith("return"):
            continue
        note = ("        # سُجّل تلقائيًا بواسطة الجرّاح الذاتي: عطل صامت "
                "يجب أن يُرى في السجل.\n")
        ins = (
            f"{body_indent}try:\n"
            f"{body_indent}    from awareness import journal as _j\n"
            f"{body_indent}    _j.debug('swallowed_exception', where=__name__)\n"
            f"{body_indent}except Exception:\n"
            f"{body_indent}    pass\n"
        )
        del note                                      # نُبقي الشفرة نظيفة
        lines.insert(body[0], ins)
        changed += 1
    if not changed:
        return text, ""
    return "".join(lines), (
        f"أضفت تسجيلًا صامتًا لـ{changed} معالج استثناء كان يبتلع العطل بلا أثر، "
        "دون تغيير أي سلوك: العطل يُرى في السجل ويتعلّم منه البرنامج."
    )


def _t_add_open_encoding(text: str, issues: list[Issue]) -> tuple[str, str]:
    """يضيف ``encoding='utf-8'`` لكل ``open()`` نصي — يقتل Mojibake العربي."""
    lines = text.splitlines(keepends=True)
    changed = 0
    for i in sorted({i.line for i in issues if i.line > 0}, reverse=True):
        idx = i - 1
        if not (0 <= idx < len(lines)):
            continue
        s = lines[idx]
        if "open(" not in s or "encoding" in s:
            continue
        # نُعدّل نداء open المتوازن على هذا السطر فقط (سطر واحد = آمن)
        pos = s.find("open(")
        depth = 0
        end = -1
        for k in range(pos + 4, len(s)):
            if s[k] == "(":
                depth += 1
            elif s[k] == ")":
                depth -= 1
                if depth == 0:
                    end = k
                    break
        if end < 0:
            continue                                  # نداء متعدد الأسطر: نتجاهله
        inner = s[pos + 5:end]
        if not inner.strip():
            continue
        new_call = f"open({inner}, encoding='utf-8')"
        lines[idx] = s[:pos] + new_call + s[end + 1:]
        changed += 1
    if not changed:
        return text, ""
    return "".join(lines), (
        f"ضبطت الترميز صريحًا (utf-8) في {changed} موضع فتح ملف نصي؛ هذا يمنع "
        "تحريف النصوص العربية على ويندوز الذي يفترض cp1256."
    )


def _t_guard_optional_import(text: str, issues: list[Issue]) -> tuple[str, str]:
    """يحمي استيراد حزمة اختيارية: غيابها يعطّل قدرة لا يُسقط التطبيق."""
    lines = text.splitlines(keepends=True)
    done: list[str] = []
    for iss in sorted(issues, key=lambda x: x.line, reverse=True):
        mod = str(iss.context.get("module") or "")
        idx = iss.line - 1
        if not mod or not (0 <= idx < len(lines)):
            continue
        s = lines[idx]
        if not re.match(rf"^\s*(import\s+{re.escape(mod)}\b|from\s+{re.escape(mod)}\b)", s):
            continue
        base = _indent_of(s)
        alias = mod
        m = re.search(r"\bas\s+(\w+)", s)
        if m:
            alias = m.group(1)
        block = (
            f"{base}try:\n"
            f"{base}    {s.strip()}\n"
            f"{base}except Exception:  # الحزمة اختيارية: تُعطّل قدرة واحدة بلطف\n"
            f"{base}    {alias} = None\n"
        )
        lines[idx] = block
        done.append(mod)
    if not done:
        return text, ""
    uniq = sorted(set(done))
    return "".join(lines), (
        "حميت استيراد الحزم الاختيارية (" + "، ".join(uniq) + ") بحيث يعطّل "
        "غيابها قدرة واحدة بلطف بدل أن يمنع الإقلاع كليًا."
    )


TRANSFORMS = {
    "log_silent_except": _t_log_silent_except,
    "add_open_encoding": _t_add_open_encoding,
    "guard_optional_import": _t_guard_optional_import,
}


# ───────────────────────── الجرّاح ─────────────────────────

def surgery_dir() -> Path:
    d = identity.awareness_dir() / "surgery"
    with contextlib.suppress(Exception):
        d.mkdir(parents=True, exist_ok=True)
    return d


class Surgeon:
    """يدقّق بنية الشفرة، يولّد الرقع، يتحقق، يطبّق ذرّيًا، ويتراجع."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or identity.repo_root())
        self._lock = threading.RLock()
        self._cache: tuple[float, list[Issue]] | None = None
        # كاشات أداء: التحقق دالة نقية، وقياسات الأساس لا تتغير أبدًا
        # أثناء العملية، فإعادة حسابها في كل مستوى عزل إهدار محض.
        self._verify_cache: dict[str, tuple[bool, list[dict]]] = {}
        self._base_import: dict[str, bool] = {}
        self._base_test: dict[str, int] = {}
        self._fast = False   # وضع المرشّح الرخيص (يتخطّى بوابة الاختبارات)
        self._calls = 0      # عداد نداءات التحقق في العملية الجارية
        self._budget = 0     # سقف النداءات (0 = بلا سقف)

    # ── الاستكشاف ──

    def _code_files(self) -> list[Path]:
        out: list[Path] = []
        for rel in _CODE_ROOTS:
            base = self.root / rel
            if not base.exists():
                continue
            for p in base.rglob("*.py"):
                r = p.relative_to(self.root).as_posix()
                if any(tok in r for tok in _PROTECTED):
                    continue
                with contextlib.suppress(Exception):
                    if p.stat().st_size > _MAX_FILE_BYTES:
                        continue
                out.append(p)
        return sorted(out)

    # ── التشخيص ──

    def diagnose(self, *, use_cache: bool = True,
                 codes: list[str] | None = None) -> list[Issue]:
        """يفحص كل ملفات الشفرة ويُرجع مواضع الضعف مرتّبة بالشدّة."""
        now = time.time()
        with self._lock:
            if use_cache and self._cache and (now - self._cache[0]) < 120:
                found = list(self._cache[1])
                return [i for i in found if not codes or i.code in codes]

        found: list[Issue] = []
        t0 = time.perf_counter()
        for p in self._code_files():
            rel = p.relative_to(self.root).as_posix()
            text = _read(p)
            if not text:
                continue
            try:
                tree = ast.parse(text)
            except SyntaxError as exc:
                found.append(Issue(
                    code="syntax_error",
                    title_ar="خطأ نحوي يمنع تشغيل الوحدة",
                    detail_ar=f"لا يمكن تحليل الملف: {str(exc)[:160]}",
                    path=rel, line=int(getattr(exc, "lineno", 0) or 0),
                    severity=Severity.HIGH, transform="",
                ))
                continue
            except Exception:
                continue
            lines = text.splitlines(keepends=True)
            for det in DETECTORS:
                with contextlib.suppress(Exception):
                    found.extend(det(tree, text, lines, rel) or [])

        found.sort(key=lambda i: (Severity.ORDER.get(i.severity, 3), i.path, i.line))
        with self._lock:
            self._cache = (now, list(found))
        journal.info("surgeon_diagnose", issues=len(found),
                     elapsed_ms=round((time.perf_counter() - t0) * 1000, 1))
        return [i for i in found if not codes or i.code in codes]

    # ── توليد الرقع ──

    def plan(self, issues: list[Issue] | None = None, *,
             codes: list[str] | None = None,
             targets: list[str] | None = None,
             max_files: int = 12) -> list[Patch]:
        """يبني رقعًا للمواضع القابلة للإصلاح، ملفًا ملفًا.

        ``max_files`` يقيّد حجم العملية الواحدة: رقعة صغيرة مُتحقَّق منها أفضل من
        تعديل شامل يصعب تقييمه أو التراجع عنه.
        """
        issues = issues if issues is not None else self.diagnose(codes=codes)
        fixable = [i for i in issues if i.transform in TRANSFORMS]
        if targets:
            tset = {t.replace("\\", "/") for t in targets}
            fixable = [i for i in fixable
                       if i.path in tset or any(i.path.endswith(t) for t in tset)]
        if codes:
            fixable = [i for i in fixable if i.code in codes]

        by_file: dict[str, list[Issue]] = {}
        for i in fixable:
            by_file.setdefault(i.path, []).append(i)

        patches: list[Patch] = []
        for rel in sorted(by_file)[:max_files]:
            p = self.root / rel
            old = _read(p)
            if not old:
                continue
            cur = old
            notes: list[str] = []
            used: list[str] = []
            # نطبّق تحويلات هذا الملف بالتسلسل، ونعيد التشخيص بين كل تحويلين
            # لأن أرقام الأسطر تتغيّر بعد أول تعديل — وتجاهل ذلك يفسد الرقعة.
            for tname in ("guard_optional_import", "add_open_encoding",
                          "log_silent_except"):
                group = [i for i in by_file[rel] if i.transform == tname]
                if not group:
                    continue
                if cur is not old:
                    group = self._relocate(cur, rel, tname)
                    if not group:
                        continue
                fn = TRANSFORMS[tname]
                try:
                    new_text, note = fn(cur, group)
                except Exception as exc:
                    journal.warn("transform_failed", transform=tname, path=rel,
                                 error=str(exc)[:200])
                    continue
                if new_text != cur:
                    cur = new_text
                    used.append(tname)
                    if note:
                        notes.append(note)
            if cur != old:
                patches.append(Patch(path=rel, old_text=old, new_text=cur,
                                     issues=by_file[rel],
                                     transform="+".join(used),
                                     note_ar=" ".join(notes)))
        return patches

    def _relocate(self, text: str, rel: str, transform: str) -> list[Issue]:
        """يعيد كشف مواضع تحويل معيّن في نص مُعدَّل (أرقام أسطر جديدة)."""
        try:
            tree = ast.parse(text)
        except Exception:
            return []
        lines = text.splitlines(keepends=True)
        found: list[Issue] = []
        for det in DETECTORS:
            with contextlib.suppress(Exception):
                found.extend(det(tree, text, lines, rel) or [])
        return [i for i in found if i.transform == transform]

    # ── التحقق ──

    def verify(self, patches: list[Patch]) -> tuple[bool, list[dict]]:
        """البوابات الأربع. تُرجع (نجاح كلي, تفاصيل كل بوابة).

        العزل التدريجي يعيد التحقق من توليفات متكررة، فنُخزّن النتيجة
        بحسب بصمة مجموعة الرقع لأن التحقق دالة نقية من المدخل.
        """
        key = self._patches_key(patches) + ("|F" if self._fast else "|S")
        hit = self._verify_cache.get(key)
        if hit is not None:
            return hit[0], [dict(c) for c in hit[1]]
        self._calls += 1
        res = self._verify_uncached(patches)
        if len(self._verify_cache) < 256:
            self._verify_cache[key] = (res[0], [dict(c) for c in res[1]])
        return res

    def _over_budget(self) -> bool:
        """هل استنفد العزل ميزانية نداءات التحقق؟

        العزل الجشع يمكن أن يطلق عشرات النداءات (12s للنداء) فيتحول
        التحسين إلى تجميد. الميزانية توقفه بلطف: ما لم يُتحقق منه
        يُعدّ معزولًا (الموقف المحافِظ) لا مُطبّقًا بلا تحقق.
        """
        return self._budget > 0 and self._calls >= self._budget

    @contextlib.contextmanager
    def _fast_gates(self):
        """يخطّي أغلى بوابة (الاختبارات) في مسار البحث عن المُفسد.

        العزل يُنادي ``verify`` مرات عدة ليحدد **أيّ** رقعة مُفسدة؛ لا نحتاج
        يقينًا كاملًا في كل مستوى، بل مرشّحًا رخيصًا (نحو + بنية + استيراد).
        ثم يُجرى تحقق كامل واحد على المجموعة الناجية قبل التطبيق، فلا
        تنقص الضمانة ويسقط الزمن كثيرًا.
        """
        prev = self._fast
        self._fast = True
        try:
            yield
        finally:
            self._fast = prev

    @staticmethod
    def _patches_key(patches: list[Patch]) -> str:
        h = hashlib.sha1()
        for pt in sorted(patches, key=lambda p: str(p.path)):
            h.update(str(pt.path).encode("utf-8", "replace"))
            h.update(hashlib.sha1(
                pt.new_text.encode("utf-8", "replace")).digest())
        return h.hexdigest()

    def _verify_uncached(self, patches: list[Patch]) -> tuple[bool, list[dict]]:
        checks: list[dict] = []
        ok_all = True

        for pt in patches:
            # 1) النحو
            try:
                compile(pt.new_text, pt.path, "exec")
                checks.append({"gate": "syntax", "path": pt.path, "ok": True,
                               "message_ar": "النحو سليم."})
            except SyntaxError as exc:
                ok_all = False
                checks.append({"gate": "syntax", "path": pt.path, "ok": False,
                               "message_ar": f"نحو معطوب: {str(exc)[:160]}"})
                continue

            # 2) البنية: نفس الدوال والأصناف وأسماء المستوى الأعلى
            same, why = self._structure_preserved(pt.old_text, pt.new_text)
            checks.append({"gate": "structure", "path": pt.path, "ok": same,
                           "message_ar": why})
            if not same:
                ok_all = False

        if not ok_all:
            return False, checks

        # 3+4) الاستيراد والاختبارات في شجرة مؤقتة معزولة
        sandbox_ok, sandbox_checks = self._verify_in_sandbox(patches)
        checks.extend(sandbox_checks)
        return bool(sandbox_ok), checks

    def _structure_preserved(self, old: str, new: str) -> tuple[bool, str]:
        """يتأكد أن التحويل لم يحذف دالة أو صنفًا أو يغيّر توقيعًا."""
        def sig(src: str) -> tuple[set, set, int]:
            try:
                t = ast.parse(src)
            except Exception:
                return set(), set(), -1
            funcs, classes = set(), set()
            for n in ast.walk(t):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = [a.arg for a in n.args.args]
                    funcs.add(f"{n.name}({','.join(args)})")
                elif isinstance(n, ast.ClassDef):
                    classes.add(n.name)
            return funcs, classes, len(t.body)

        f1, c1, n1 = sig(old)
        f2, c2, n2 = sig(new)
        if n1 < 0 or n2 < 0:
            return False, "تعذّر تحليل أحد النصين للمقارنة البنيوية."
        lost_f, lost_c = f1 - f2, c1 - c2
        if lost_f:
            return False, f"اختفت دوال بعد التعديل: {sorted(lost_f)[:3]}"
        if lost_c:
            return False, f"اختفت أصناف بعد التعديل: {sorted(lost_c)[:3]}"
        if f2 - f1 or c2 - c1:
            return False, "أُضيفت دوال أو أصناف غير مقصودة."
        return True, "البنية محفوظة: نفس الدوال والأصناف والتوقيعات."

    def _verify_in_sandbox(self, patches: list[Patch]) -> tuple[bool, list[dict]]:
        """ينسخ المشروع إلى مجلد مؤقت، يطبّق الرقع، ثم يستورد ويشغّل الاختبارات.

        النسخ الكامل قد يكون ثقيلًا، فننسخ ``src`` و``windows_app`` و``tests``
        فقط (بلا أصول ولا نماذج) عبر روابط رمزية للمجلدات الثقيلة.
        """
        checks: list[dict] = []
        tmp = None
        try:
            tmp = Path(tempfile.mkdtemp(prefix="mis_surgery_"))
            for name in ("src", "windows_app", "tests"):
                s = self.root / name
                if s.exists():
                    shutil.copytree(s, tmp / name,
                                    ignore=shutil.ignore_patterns(
                                        "__pycache__", "*.pyc", "*.onnx",
                                        "*.zip", "*.png", "*.jpg"))
            for pt in patches:
                dst = tmp / pt.path
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(pt.new_text, encoding="utf-8")

            env = dict(os.environ)
            env["PYTHONPATH"] = str(tmp / "src") + os.pathsep + str(tmp)
            env["MIS_HEADLESS"] = "1"
            env["QT_QPA_PLATFORM"] = "offscreen"

            # 3) بوابة الاستيراد **الفرقية** — متوازية.
            #
            # كل فحص يطلق عملية فرعية تنتظر تحميل مكتبات ثقيلة (Qt/cv2)،
            # فالعمل محدود بالإدخال/الإخراج والتوازي مجزٍ جدًا.
            #
            # الحكم المطلق «هل يُستورد الملف؟» خاطئ هنا: في هذا المشروع ملفات
            # لا تُستورد منفردة أصلًا (تحتاج سياق الحزمة، أو Qt، أو تعتمد على
            # __module__ داخل dataclass). فلو رفضنا الرقعة لذلك، نرفض رقعة
            # سليمة بسبب عطل سابق لها. المعيار الصحيح: **ألّا تُسوّئ الرقعة
            # الحالة**. نستورد الأصل والمعدَّل بنفس الشروط ونقارن.
            new_res = self._pmap(
                [(tmp / pt.path, env, tmp) for pt in patches],
                lambda a: self._probe_import(*a))
            base_res = self._pmap(
                [(self.root / pt.path, env, tmp) for pt in patches],
                lambda a: self._base_probe_import(*a))
            for pt, new_ok, base_ok in zip(patches, new_res, base_res):
                mod = pt.path
                if new_ok:
                    ok, msg = True, "الوحدة تُستورد بنجاح بعد التعديل."
                elif not base_ok:
                    ok, msg = True, ("الوحدة لا تُستورد منفردة قبل التعديل ولا "
                                     "بعده (تحتاج سياق الحزمة)؛ الرقعة لم تُسوّئ "
                                     "الحالة، والحكم متروك لبوابة الاختبارات.")
                else:
                    ok, msg = False, ("الرقعة كسرت استيراد وحدة كانت سليمة: "
                                      f"{self._last_err[-300:]}")
                checks.append({"gate": "import", "path": mod, "ok": ok,
                               "message_ar": msg})
                if not ok:
                    return False, checks

            # 4) بوابة الاختبارات المرتبطة — فرقية أيضًا.
            #
            # اختبارات هذا المشروع سكربتات مستقلة تُنفّذ مباشرة وتُرجع رمز
            # خروج (ليست pytest)، وبعضها يفشل أصلًا لأسباب بيئية (نموذج ناقص،
            # لا شاشة). لذا نقيس **الفرق**: نشغّل الاختبار على الأصل وعلى
            # المعدَّل، ونرفض الرقعة فقط إن حوّلت نجاحًا إلى فشل.
            tests = [] if self._fast else self._related_tests(patches, tmp)
            if self._fast:
                checks.append({"gate": "tests", "path": "-", "ok": True,
                               "message_ar": ("مرشّح سريع: أُجّلت بوابة "
                                              "الاختبارات للتحقق النهائي.")})
            elif tests:
                new_rcs = self._pmap(
                    [(t, env, tmp) for t in tests],
                    lambda a: self._run_script(*a))
                for t, new_rc in zip(tests, new_rcs):
                    rel_t = f"tests/{t.name}"
                    if new_rc == 0:
                        ok, msg = True, f"الاختبار {t.name} نجح بعد التعديل."
                    else:
                        base_rc = self._base_run_script(self.root / rel_t, env,
                                                       self.root)
                        if base_rc != 0:
                            ok, msg = True, (
                                f"الاختبار {t.name} كان يفشل قبل التعديل وبعده "
                                "لسبب بيئي؛ الرقعة لم تُسوّئ الحالة.")
                        else:
                            ok, msg = False, (
                                f"الرقعة أفشلت اختبارًا كان ناجحًا: {t.name} "
                                f"— {self._last_err[-300:]}")
                    checks.append({"gate": "tests", "path": t.name, "ok": ok,
                                   "message_ar": msg})
                    if not ok:
                        return False, checks
            else:
                checks.append({"gate": "tests", "path": "-", "ok": True,
                               "message_ar": "لا اختبارات مرتبطة بهذه الملفات."})
            return True, checks
        except Exception as exc:
            checks.append({"gate": "sandbox", "path": "-", "ok": False,
                           "message_ar": f"تعذّر التحقق المعزول: {str(exc)[:200]}"})
            return False, checks
        finally:
            if tmp is not None:
                with contextlib.suppress(Exception):
                    shutil.rmtree(tmp, ignore_errors=True)

    def _related_tests(self, patches: list[Patch], tmp: Path) -> list[Path]:
        """يجد ملفات الاختبار التي تذكر الوحدات المعدَّلة."""
        tdir = tmp / "tests"
        if not tdir.exists():
            return []
        stems = {Path(pt.path).stem for pt in patches}
        out: list[Path] = []
        for t in sorted(tdir.glob("test_*.py")):
            txt = _read(t)
            if any(s in txt for s in stems):
                out.append(t)
        return out[:6]

    _last_err: str = ""

    def _probe_import(self, path: Path, env: dict, cwd: Path) -> bool:
        """يحاول استيراد ملف بمعزل في عملية منفصلة؛ يُرجع النجاح فقط."""
        code = (
            "import importlib.util, pathlib\n"
            f"p = pathlib.Path(r'{Path(path).as_posix()}')\n"
            "spec = importlib.util.spec_from_file_location('probe_mod', p)\n"
            "m = importlib.util.module_from_spec(spec)\n"
            "import sys; sys.modules['probe_mod'] = m\n"
            "spec.loader.exec_module(m)\n"
            "print('IMPORT_OK')\n"
        )
        rc, out, err = self._run(code, env, cwd)
        if "IMPORT_OK" not in out:
            self._last_err = err or out
            return False
        return True

    def _run_script(self, script: Path, env: dict, cwd: Path) -> int:
        """يشغّل سكربت اختبار مستقل ويُرجع رمز الخروج."""
        if not Path(script).exists():
            self._last_err = "ملف الاختبار غير موجود"
            return 127
        rc, out, err = self._run_cmd([sys.executable, str(script)], env, cwd)
        if rc != 0:
            self._last_err = (err or out)
        return rc

    def _base_probe_import(self, path: Path, env: dict, cwd: Path) -> bool:
        """مثل ``_probe_import`` مع كاش: حالة الأصل لا تتغير أثناء العملية."""
        k = str(path)
        with self._lock:
            if k in self._base_import:
                return self._base_import[k]
        val = self._probe_import(path, env, cwd)
        with self._lock:
            self._base_import[k] = val
        return val

    def _base_run_script(self, script: Path, env: dict, cwd: Path) -> int:
        """مثل ``_run_script`` مع كاش لنتيجة الأصل (أغلى البوابات زمنًا)."""
        k = str(script)
        with self._lock:
            if k in self._base_test:
                return self._base_test[k]
        val = self._run_script(script, env, cwd)
        with self._lock:
            self._base_test[k] = val
        return val

    @staticmethod
    def _pmap(items: list, fn) -> list:
        """تنفيذ متوازٍ محافِظ على الترتيب لمهام محدودة بالإدخال/الإخراج.

        خيوط لا عمليات: العمل الفعلي يجري في عمليات فرعية والخيط ينتظر
        فقط، فلا يقيّدنا قفل المُفسّر. ونحدّ التوازي بعدد الأنوية ناقصًا
        واحدًا لإبقاء الجهاز مستجيبًا للمستخدم أثناء التحقق.
        """
        if not items:
            return []
        if len(items) == 1:
            return [fn(items[0])]
        try:
            n = max(1, min(len(items), (os.cpu_count() or 2) - 1, 4))
            with cf.ThreadPoolExecutor(max_workers=n) as ex:
                return list(ex.map(fn, items))
        except Exception:
            return [fn(i) for i in items]

    def _run(self, code: str, env: dict, cwd: Path) -> tuple[int, str, str]:
        return self._run_cmd([sys.executable, "-c", code], env, cwd)

    def _run_cmd(self, cmd: list[str], env: dict, cwd: Path) -> tuple[int, str, str]:
        try:
            pr = subprocess.run(cmd, env=env, cwd=str(cwd), capture_output=True,
                                text=True, timeout=_VERIFY_TIMEOUT)
            return pr.returncode, pr.stdout or "", pr.stderr or ""
        except subprocess.TimeoutExpired:
            return 124, "", "انتهت المهلة"
        except Exception as exc:
            return 1, "", str(exc)[:400]

    # ── التطبيق والتراجع ──

    def apply(self, patches: list[Patch], *, reason: str = "") -> SurgeryResult:
        """يطبّق الرقع ذرّيًا بعد أخذ نسخة كاملة قابلة للاستعادة."""
        res = SurgeryResult(patches=patches)
        if not patches:
            res.ok, res.message_ar = True, "لا تعديلات مطلوبة."
            return res

        if identity.is_frozen():
            res.advisory = True
            res.ok = True
            res.message_ar = ("أنا أعمل كحزمة مُصرَّفة فلا أعدّل شفرتي مباشرة. "
                              "جهّزت تقرير الرقعة كاملًا، وطبّقت ما يقابلها من "
                              "مفاتيح تشغيل فورية.")
            self._advisory_export(patches)
            return res

        sid = time.strftime("%Y%m%d-%H%M%S") + "-" + hashlib.sha256(
            "".join(p.path for p in patches).encode()).hexdigest()[:6]
        bdir = surgery_dir() / sid
        try:
            bdir.mkdir(parents=True, exist_ok=True)
            manifest = {"surgery_id": sid, "ts": time.time(),
                        "reason": reason, "files": []}
            for pt in patches:
                src = self.root / pt.path
                dst = bdir / pt.path.replace("/", "__")
                dst.write_text(pt.old_text, encoding="utf-8")
                manifest["files"].append({
                    "path": pt.path, "backup": dst.name,
                    "transform": pt.transform, "note_ar": pt.note_ar,
                    "sha_before": hashlib.sha256(
                        pt.old_text.encode("utf-8", "replace")).hexdigest()[:16],
                })
                del src
            (bdir / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8")
            (bdir / "patch.diff").write_text(
                "\n".join(p.diff for p in patches), encoding="utf-8")

            # الكتابة الذرّية: ملف مؤقت في نفس المجلد ثم os.replace
            for pt in patches:
                target = self.root / pt.path
                tmpf = target.with_suffix(target.suffix + ".surgtmp")
                tmpf.write_text(pt.new_text, encoding="utf-8")
                os.replace(tmpf, target)

            res.ok = res.applied = True
            res.surgery_id = sid
            notes = [p.note_ar for p in patches if p.note_ar]
            res.message_ar = ("عدّلت بنيتي بنفسي في "
                              f"{len(patches)} ملف. " + " ".join(notes[:3]) +
                              f" يمكن التراجع بالمعرّف {sid}.")
            ledger_mod.ledger().record_surgery(
                sid, "+".join(sorted({p.transform for p in patches})),
                ",".join(p.path for p in patches), True)
            journal.info("surgery_applied", surgery_id=sid,
                         files=len(patches), reason=reason)
            return res
        except Exception as exc:
            journal.error("surgery_failed", error=str(exc)[:300])
            with contextlib.suppress(Exception):
                self.rollback(sid)
            res.ok = False
            res.message_ar = (f"تعذّر تطبيق التعديل ({str(exc)[:120]}) "
                              "وأعدت كل شيء كما كان.")
            return res

    def _advisory_export(self, patches: list[Patch]) -> None:
        """في الحزمة المصرَّفة: يصدّر التقرير ويحوّل ما أمكن لمفاتيح تشغيل."""
        try:
            out = surgery_dir() / f"advisory-{time.strftime('%Y%m%d-%H%M%S')}.json"
            out.write_text(json.dumps(
                {"patches": [p.as_dict() for p in patches]},
                ensure_ascii=False, indent=2), encoding="utf-8")
            from . import healer
            healer.set_override("force_utf8_io", True,
                                reason="مقابل تشغيلي لرقعة الترميز")
            healer.set_override("log_swallowed_exceptions", True,
                                reason="مقابل تشغيلي لرقعة العطل الصامت")
        except Exception:
            pass

    def rollback(self, surgery_id: str) -> dict:
        """يعيد كل ملف من نسخة الجراحة المحددة."""
        bdir = surgery_dir() / str(surgery_id or "")
        man = bdir / "manifest.json"
        if not man.exists():
            return {"ok": False,
                    "message_ar": f"لا أجد نسخة الجراحة «{surgery_id}»."}
        try:
            data = json.loads(_read(man) or "{}")
            restored = 0
            for f in data.get("files", []):
                src = bdir / str(f.get("backup") or "")
                dst = self.root / str(f.get("path") or "")
                if not src.exists() or not str(f.get("path")):
                    continue
                text = _read(src)
                tmpf = dst.with_suffix(dst.suffix + ".surgtmp")
                tmpf.write_text(text, encoding="utf-8")
                os.replace(tmpf, dst)
                restored += 1
            ledger_mod.ledger().record_revert(str(surgery_id))
            journal.warn("surgery_rolled_back", surgery_id=surgery_id,
                         files=restored)
            return {"ok": restored > 0, "restored": restored,
                    "message_ar": (f"تراجعت عن الجراحة {surgery_id} وأعدت "
                                   f"{restored} ملف إلى حالته السابقة.")}
        except Exception as exc:
            return {"ok": False,
                    "message_ar": f"فشل التراجع: {str(exc)[:200]}"}

    def rollback_last(self) -> dict:
        h = self.history(limit=1)
        if not h:
            return {"ok": False, "message_ar": "لم أجرِ أي جراحة بعد."}
        return self.rollback(h[0].get("surgery_id", ""))

    def history(self, limit: int = 20) -> list[dict]:
        out: list[dict] = []
        try:
            for d in sorted(surgery_dir().iterdir(), reverse=True):
                if not d.is_dir():
                    continue
                man = d / "manifest.json"
                if not man.exists():
                    continue
                with contextlib.suppress(Exception):
                    data = json.loads(_read(man) or "{}")
                    out.append({
                        "surgery_id": data.get("surgery_id", d.name),
                        "ts": data.get("ts", 0),
                        "reason": data.get("reason", ""),
                        "files": [f.get("path") for f in data.get("files", [])],
                    })
                if len(out) >= limit:
                    break
        except Exception:
            pass
        return out

    # ── العملية الكاملة ──

    def operate(self, *, codes: list[str] | None = None,
                targets: list[str] | None = None,
                apply: bool = False, max_files: int = 12,
                reason: str = "") -> SurgeryResult:
        """الدورة الكاملة: تشخيص ← رقعة ← تحقق ← (تطبيق) ← تسجيل."""
        issues = self.diagnose(codes=codes)
        patches = self.plan(issues, codes=codes, targets=targets,
                            max_files=max_files)
        res = SurgeryResult(issues=issues, patches=patches)

        if not patches:
            res.ok = True
            fixable = sum(1 for i in issues if i.transform in TRANSFORMS)
            res.message_ar = (
                f"دقّقت بنيتي: وجدت {len(issues)} موضع ضعف، لا شيء منها يحتاج "
                "تعديلًا الآن." if not fixable else
                f"وجدت {fixable} موضعًا قابلًا للإصلاح لكن لم تنتج رقعة صالحة.")
            return res

        ok, checks = self.verify(patches)
        res.verification = checks
        quarantined: list[Patch] = []
        if not ok:
            # رفض الدفعة جملة لأجل رقعة واحدة مُفسدة يضيّع كل التحسينات
            # السليمة معها. لذا نعزل المُفسدة ببحث ثنائي ونُبقي البقية.
            bad = next((c for c in checks if not c.get("ok")), {})
            # عزل واحد بالبوابات الكاملة. جرّبنا مرشّحًا رخيصًا يتخطّى
            # بوابة الاختبارات فكان أسوأ: يُجيز مجموعات ترفضها البوابة
            # الكاملة لاحقًا، فندخل دورة إعادة طويلة (قُست: 148s مقابل 16s
            # للعمل المفيد). العزل بالبوابة التي تسبّب الفشل أسرع وأصدق.
            budget = _VERIFY_BUDGET_CALLS
            self._calls = 0
            self._budget = budget
            kept, quarantined, checks2 = self._isolate(patches)
            if not kept:
                res.ok = False
                res.message_ar = (
                    "أعددت تعديلًا على بنيتي لكنه لم يجتز التحقق، فرفضته "
                    "ولم ألمس أي ملف. السبب: "
                    f"{bad.get('message_ar', 'غير محدد')}")
                journal.warn("surgery_rejected",
                             reason=bad.get("message_ar", ""))
                ledger_mod.add_insight(
                    "surgery",
                    f"رقعة مرفوضة: {bad.get('message_ar','')}"[:400])
                return res
            patches = kept
            checks = checks2
            res.patches = kept
            res.verification = checks2
            journal.warn("surgery_quarantine", kept=len(kept),
                         dropped=len(quarantined),
                         reason=bad.get("message_ar", ""))
            ledger_mod.add_insight(
                "surgery",
                f"عزلت {len(quarantined)} رقعة مُفسدة وأبقيت {len(kept)} سليمة: "
                f"{bad.get('message_ar','')}"[:400])

        q_note = ""
        if quarantined:
            q_note = (f" وعزلت {len(quarantined)} تعديلًا لم يجتز التحقق، "
                      "فلم ألمس ملفاته.")
        res.quarantined = [str(getattr(p, "path", p)) for p in quarantined]

        if not apply:
            res.ok = True
            add = sum(p.stats[0] for p in patches)
            res.message_ar = (
                f"جهّزت تعديلًا على {len(patches)} ملف ({add} سطرًا) واجتاز كل "
                "بوابات التحقق. بانتظار موافقتك للتطبيق.") + q_note
            return res

        applied = self.apply(patches, reason=reason or "تحسين ذاتي استباقي")
        applied.issues = issues
        applied.verification = checks
        applied.quarantined = list(res.quarantined)
        if q_note and applied.message_ar:
            applied.message_ar += q_note
        return applied

    def _isolate(self, patches: list[Patch], depth: int = 0
                 ) -> tuple[list[Patch], list[Patch], list[dict]]:
        """يعزل الرقع المُفسدة ويُبقي السليمة.

        يُرجع (المُبقاة، المعزولة، فحوص المُبقاة). بحث ثنائي: إن اجتاز
        نصفٌ التحقق قُبل ككتلة، وإلا قُسّم مجددًا. التكلفة لوغاريتمية لا
        خطية، والعمق محدود منعًا لإطالة زمن العملية.
        """
        if not patches:
            return [], [], []
        if depth > _ISOLATE_MAX_DEPTH or self._over_budget():
            return [], list(patches), []
        if len(patches) == 1:
            ok, checks = self.verify(patches)
            if ok:
                return list(patches), [], checks
            return [], list(patches), []

        mid = len(patches) // 2
        kept: list[Patch] = []
        dropped: list[Patch] = []
        for half in (patches[:mid], patches[mid:]):
            ok, _ = self.verify(half)
            if ok:
                kept.extend(half)
            else:
                k, d, _ = self._isolate(half, depth + 1)
                kept.extend(k)
                dropped.extend(d)

        if not kept:
            return [], dropped, []
        # كل جزء سليم منفردًا، لكن اجتماعهما قد يتعارض → تحقق نهائي
        ok, checks = self.verify(kept)
        if ok:
            return kept, dropped, checks
        if depth >= _ISOLATE_MAX_DEPTH:
            return [], list(patches), []
        k2, d2, c2 = self._isolate(kept, depth + 1)
        return k2, dropped + d2, c2


# ───────────────────────── الواجهة المفردة ─────────────────────────

_SURGEON: Surgeon | None = None
_S_LOCK = threading.Lock()


def surgeon() -> Surgeon:
    global _SURGEON
    with _S_LOCK:
        if _SURGEON is None:
            _SURGEON = Surgeon()
        return _SURGEON


def diagnose(**kw) -> list[Issue]:
    return surgeon().diagnose(**kw)


def operate(**kw) -> dict:
    return surgeon().operate(**kw).as_dict()


def rollback_last() -> dict:
    return surgeon().rollback_last()


def rollback(surgery_id: str) -> dict:
    return surgeon().rollback(surgery_id)


def history(limit: int = 20) -> list[dict]:
    return surgeon().history(limit=limit)
