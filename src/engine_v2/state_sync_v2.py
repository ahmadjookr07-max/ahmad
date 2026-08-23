# -*- coding: utf-8 -*-
"""state_sync_v2 — مزامنة `job_state.json` بعد إعادة تسمية المخرجات (2.9.12).

المشكلة التي تحلّها هذه الوحدة
------------------------------
زر ★ (تعيين صورة الواجهة) يعيد تسمية الملفات **على القرص** ثم يحدّث
النتائج **في ذاكرة الواجهة** عبر ``dataclasses.replace``. لكن المحرك
لا يقرأ ذاكرة الواجهة؛ يقرأ ``job_state.json`` من القرص. فينفصل
الاثنان، ويظهر الانفصال بعد ★ مباشرة في أول تحرير فردي:

    لم يُعثر على الصورة المحددة داخل نتائج المهمة: 10001099_حبه-4.webp

وهذا بعينه ما وصفه المالك بأن «الطمس لا يُحفظ»: العملية تفشل قبل أن
تبدأ لأن المحرك لا يعرف الاسم الجديد أصلًا.

لماذا وحدة مستقلة
-----------------
المزامنة تخصّ **الحالة على القرص** لا الواجهة، ومحلّها الطبيعي
``engine_v2`` بجوار ``source_vault_v2`` الذي يقرأ الملف نفسه ويكتبه
بالطريقة الذرّية نفسها. ووضعها هنا يجعلها قابلة للاختبار بلا Qt.

مبدأ التصميم: لا تُسقط العملية أبدًا
------------------------------------
فشل المزامنة يعني حالة قديمة، لا بيانات تالفة — والشبكة الاحتياطية
(``integrity_patch.match_item_position``) تلتقط الحالة. لذلك كل
الدوال هنا تبتلع أخطاءها وتعيد تقريرًا بدل رفع استثناء.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

__all__ = [
    "STATE_NAME",
    "sync_renamed_outputs",
    "sync_removed_outputs",
    "sync_result_items",
    "normalize_path_key",
]

STATE_NAME = "job_state.json"

# الحقول التي قد تحمل مسار ملف أُعيدت تسميته داخل سجل الصنف الواحد.
_PATH_FIELDS = ("output_path", "source_path", "review_path")


def normalize_path_key(path: str | Path) -> str:
    """مفتاح مقارنة موحّد للمسارات على ويندوز.

    ويندوز لا يفرّق بين حالة الأحرف ويقبل ``/`` و``\\`` معًا، فمقارنة
    النصوص الخام تفشل بصمت وتترك الحالة قديمة — وهو بالضبط نوع العطب
    الذي نغلقه هنا، فلا يجوز أن نقع فيه.
    """
    text = str(path)
    try:
        text = os.path.realpath(text)
    except Exception:                                   # noqa: BLE001
        text = os.path.abspath(text)
    return os.path.normcase(os.path.normpath(text))


def _atomic_write_json(path: Path, payload: Any) -> bool:
    """كتابة ذرّية: ملف مؤقت ثم ``os.replace``.

    الكتابة المباشرة على ``job_state.json`` تتركه مبتورًا إن انقطع
    التطبيق أثناءها، فتضيع الجلسة كلها لا سجل واحد.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent),
                                   prefix=path.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
            os.replace(tmp, path)
            return True
        except Exception:                               # noqa: BLE001
            try:
                os.unlink(tmp)
            except OSError:
                pass
            return False
    except Exception:                                   # noqa: BLE001
        return False


def _iter_state_items(state: Any) -> Iterable[dict]:
    """يمرّ على سجلات الأصناف أيًّا كان شكل الحالة.

    الشكل المعتاد ``state["result"]["items"]``، وقد تظهر ``items``
    في الجذر في حالات قديمة. نقبل الاثنين بدل أن نفشل بصمت.
    """
    if not isinstance(state, dict):
        return
    containers = []
    result = state.get("result")
    if isinstance(result, dict) and isinstance(result.get("items"), list):
        containers.append(result["items"])
    if isinstance(state.get("items"), list):
        containers.append(state["items"])
    for container in containers:
        for entry in container:
            if isinstance(entry, dict):
                yield entry


def sync_result_items(workspace: str | Path, items: Iterable[Any]) -> dict:
    """يستبدل عناصر نتيجة المهمة بالحالة الحية للواجهة كتابةً ذرية.

    يلزم ذلك بعد اقتصاص التغذية: الصورة تُضاف في الذاكرة فورًا، لكن
    العامل اللاحق لا يعرفها ما لم تُكتب أيضًا في ``job_state.json``.
    """
    report = {"count": 0, "written": False, "reason": ""}
    try:
        state_path = Path(workspace) / STATE_NAME
        if not state_path.is_file():
            report["reason"] = "لا توجد حالة محفوظة"
            return report
        state = json.loads(state_path.read_text(encoding="utf-8"))
        serial: list[dict] = []
        for item in items or ():
            if isinstance(item, dict):
                serial.append(dict(item))
                continue
            try:
                from dataclasses import asdict, is_dataclass
                value = asdict(item) if is_dataclass(item) else None
            except Exception:
                value = None
            if not isinstance(value, dict):
                value = {name: getattr(item, name) for name in (
                    "source_path", "source_name", "status", "item_code",
                    "product_name", "barcode", "confidence", "explanation",
                    "output_path", "review_path", "match_source")
                    if hasattr(item, name)}
            serial.append(value)
        result = state.get("result") if isinstance(state, dict) else None
        if isinstance(result, dict):
            result["items"] = serial
        elif isinstance(state, dict):
            state["items"] = serial
        else:
            report["reason"] = "شكل حالة غير مدعوم"
            return report
        report["count"] = len(serial)
        report["written"] = _atomic_write_json(state_path, state)
        if not report["written"]:
            report["reason"] = "تعذرت كتابة الحالة"
    except Exception as exc:  # noqa: BLE001
        report["reason"] = f"فشل غير متوقع: {exc}"
    return report


def sync_removed_outputs(workspace: str | Path,
                         source_names: Iterable[str] = (),
                         output_paths: Iterable[str] = ()) -> dict:
    """يحذف سجلات النتائج المحذوفة من ``job_state.json`` كتابةً ذرية.

    حذف الصف من الواجهة وحدها ينهزم أمام عامل خلفي أو استعادة جلسة تقرأ
    الحالة القديمة. لذلك يعدّ حذفًا نهائيًا فقط عندما يزال من الذاكرة
    **ومن الحالة على القرص** معًا.
    """
    report = {"removed": 0, "written": False, "reason": ""}
    try:
        state_path = Path(workspace) / STATE_NAME
        if not state_path.is_file():
            report["reason"] = "لا توجد حالة محفوظة"
            return report
        names = {str(name or "") for name in source_names if str(name or "")}
        paths = {normalize_path_key(path) for path in output_paths if str(path or "")}
        if not names and not paths:
            report["reason"] = "لا عناصر للحذف"
            return report
        state = json.loads(state_path.read_text(encoding="utf-8"))
        changed = 0
        containers: list[list] = []
        result = state.get("result") if isinstance(state, dict) else None
        if isinstance(result, dict) and isinstance(result.get("items"), list):
            containers.append(result["items"])
        if isinstance(state, dict) and isinstance(state.get("items"), list):
            containers.append(state["items"])
        def _matches_removed(value: str) -> bool:
            raw = str(value or "")
            if not raw:
                return False
            keys = {normalize_path_key(raw)}
            candidate = Path(raw)
            if not candidate.is_absolute():
                keys.add(normalize_path_key(Path(workspace) / candidate))
            return bool(keys & paths)

        for items in containers:
            kept = []
            for entry in items:
                if not isinstance(entry, dict):
                    kept.append(entry)
                    continue
                entry_has_output = any(str(entry.get(field) or "")
                                       for field in _PATH_FIELDS)
                # لا نحذف باسم المصدر إذا كان للسجل مخرج: اقتصاص التغذية
                # قد يشترك في source_name مع صورة الصنف الأساسية.
                by_name = (not entry_has_output
                           and str(entry.get("source_name") or "") in names)
                by_path = any(_matches_removed(str(entry.get(field) or ""))
                              for field in _PATH_FIELDS if entry.get(field))
                if by_name or by_path:
                    changed += 1
                else:
                    kept.append(entry)
            items[:] = kept
        report["removed"] = changed
        if changed:
            report["written"] = _atomic_write_json(state_path, state)
            if not report["written"]:
                report["reason"] = "تعذرت كتابة الحالة"
        else:
            report["reason"] = "لا سجل مطابق"
    except Exception as exc:  # noqa: BLE001
        report["reason"] = f"فشل غير متوقع: {exc}"
    return report


def sync_renamed_outputs(workspace: str | Path,
                         renames: Mapping[str, str],
                         name_changes: Mapping[str, str] | None = None
                         ) -> dict:
    """يطبّق إعادة التسمية على ``job_state.json`` ليطابق القرص.

    :param workspace: مجلد مساحة العمل الذي يحوي ``job_state.json``.
    :param renames: خريطة {المسار القديم: المسار الجديد} كما يعيدها
        ``renumber_item_images``.
    :param name_changes: خريطة اختيارية {``source_name`` القديم:
        الجديد} — تلزم في المجلدات المنجزة حيث الملف نفسه هو المصدر.
    :returns: قاموس ``{"updated": int, "written": bool, "reason": str}``.

    لا يرفع استثناءً أبدًا.
    """
    report = {"updated": 0, "written": False, "reason": ""}
    try:
        state_path = Path(workspace) / STATE_NAME
        if not state_path.is_file():
            report["reason"] = "لا توجد حالة محفوظة"
            return report
        if not renames and not name_changes:
            report["reason"] = "لا تغييرات"
            return report

        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            report["reason"] = f"تعذرت قراءة الحالة: {exc}"
            return report

        path_map = {normalize_path_key(old): str(new)
                    for old, new in (renames or {}).items()}
        names = dict(name_changes or {})

        changed = 0
        for entry in _iter_state_items(state):
            touched = False
            for field in _PATH_FIELDS:
                value = str(entry.get(field) or "")
                if not value:
                    continue
                target = path_map.get(normalize_path_key(value))
                if target and target != value:
                    entry[field] = target
                    touched = True
            old_name = str(entry.get("source_name") or "")
            new_name = names.get(old_name)
            if new_name and new_name != old_name:
                entry["source_name"] = new_name
                touched = True
            if touched:
                changed += 1

        report["updated"] = changed
        if changed:
            report["written"] = _atomic_write_json(state_path, state)
            if not report["written"]:
                report["reason"] = "تعذرت كتابة الحالة"
        else:
            report["reason"] = "لا سجل مطابق"
    except Exception as exc:                            # noqa: BLE001
        report["reason"] = f"فشل غير متوقع: {exc}"
    return report
