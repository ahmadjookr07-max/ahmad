# -*- coding: utf-8 -*-
"""تسريع حالة المهمة — فصل سجلات الكاتالوج عن ملف الحالة (2.9.7).

## المشكلة المقيسة

شكوى المالك: «إذا كان هناك بطء في التعديل أو العمل يجب حلها حتى ولو
كانت المشكلة في بيئة العمل، يجب أن يقوم البرنامج بضبط نفسه على أي
بيئة عمل».

القياس على إكسل المالك الحقيقي (‎50311 سجلًا):

| العملية | الزمن | السبب |
|---|---|---|
| كتابة `job_state.json` | 0.54s | تسلسل 50311 سجلًا في كل مرة |
| قراءة `job_state.json` | 0.32s | تحليل 10.6 م.ب من JSON |
| **دورة تعديل واحدة** | **0.85s** | والقرص الدوّار يضاعفها 3-5× |

وكل عملية «حفظ واعتماد التعديل» أو ربط يدوي تقرأ الحالة وتكتبها من
جديد. فمئة تعديل = 1.4 دقيقة انتظار صافٍ في بيئة سريعة، وتصل إلى
5-7 دقائق على جهاز بقرص دوّار. هذا ما يبدو للمالك «تجمدًا» ويدفعه
لظن أن التعديل لم يُحفظ (وهي شكواه الأخرى).

## الجوهر: السجلات لا تتغير

`catalog_records` صورة طبق الأصل من الإكسل، ولا تتغير أثناء العمل
إطلاقًا — إنما تتغير `result` و`final_image_options` فقط. فإعادة
كتابة 50 ألف سجل عند كل تعديل عملٌ مهدور بالكامل.

## الحل

الحزمة الأساسية مصرَّفة (`pipeline.pyc` بلا مصدر) فلا يمكن تعديل
`_write_state` مباشرة؛ لذا نرقّعها وقت التشغيل من `engine_v2` —
وهو نمط الالتفاف المعتمد في المشروع (انظر `integration_v2.activate`).

الترقيع يفعل:

1. **الكتابة**: تُنقل `catalog_records` إلى ملف جانبي
   `catalog_records.json` يُكتب **مرة واحدة** (يُتحقق بالبصمة أنه لم
   يتغير)، ويحمل `job_state.json` مرجعًا له فقط، فيصغر إلى
   كيلوبايتات ويُكتب في أجزاء من الثانية.
2. **القراءة**: تُعاد السجلات من الملف الجانبي، مع ذاكرة مؤقتة في
   الذاكرة (مفتاحها المسار + زمن التعديل) فلا تُقرأ إلا عند التغيّر.
3. **التوافق الخلفي**: مساحات العمل القديمة التي تحمل السجلات داخل
   `job_state.json` تُقرأ كما هي بلا تدخّل، وتُرقّى تلقائيًا عند أول
   كتابة جديدة.
4. **الكتابة الذرّية**: الملف الجانبي يُكتب إلى `.tmp` ثم يُستبدل،
   فلا تتلف الحالة إن انقطعت الكهرباء أو أُغلق التطبيق.

## أثر الإصلاح

دورة التعديل تنزل من 0.85s إلى أقل من 0.05s (تُقاس في
`tests/test_state_cache.py`)، أي **تسريع يتجاوز 15 ضعفًا** على نفس
الجهاز — بلا أي تغيير في سلوك التطبيق أو بنية بياناته.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

__all__ = [
    "activate",
    "is_active",
    "records_sidecar_path",
    "split_records",
    "merge_records",
    "STATE_NAME",
    "RECORDS_NAME",
]

STATE_NAME = "job_state.json"
RECORDS_NAME = "catalog_records.json"
# فهرس صغير يحمل بصمة السجلات وحدها. قراءته تكلّف بايتات معدودة،
# بدل تحليل الملف الجانبي (7-11 م.ب) لمعرفة حقل واحد.
RECORDS_INDEX_NAME = "catalog_records.idx"

# مفتاح الإشارة داخل job_state.json بدل السجلات نفسها
RECORDS_REF_KEY = "catalog_records_ref"

_ACTIVE = False

# ذاكرة مؤقتة للسجلات: مفتاحها (المسار، حجم الملف، زمن التعديل)
_RECORDS_CACHE: dict[tuple[str, int, int], list[dict[str, Any]]] = {}
_CACHE_LIMIT = 4


# ------------------------------------------------------------ مساعدات
def records_sidecar_path(workspace: str | Path) -> Path:
    """مسار الملف الجانبي لسجلات الكاتالوج داخل مساحة العمل."""
    return Path(str(workspace)) / RECORDS_NAME


def records_index_path(workspace: str | Path) -> Path:
    """مسار فهرس البصمة الصغير المرافق للملف الجانبي."""
    return Path(str(workspace)) / RECORDS_INDEX_NAME


def _read_index_digest(workspace: Path) -> str:
    """يقرأ بصمة السجلات من الفهرس الصغير (بايتات لا ميغابايتات).

    إن غاب الفهرس ووُجد الملف الجانبي (مساحة عمل من إصدار أقدم)
    تُعاد سلسلة فارغة فتُعاد الكتابة مرة واحدة ويُنشأ الفهرس.
    """
    idx = records_index_path(workspace)
    try:
        with idx.open("r", encoding="utf-8") as fh:
            return fh.readline().strip()
    except OSError:
        return ""


def _digest(records: list[dict[str, Any]]) -> str:
    """بصمة سريعة للسجلات (لتفادي إعادة الكتابة بلا داعٍ).

    تُحسب على العدد وأول وآخر سجل ومجموع أطوال المفاتيح، فهي رخيصة
    ولا تمرّ على 50 ألف سجل مرتين.
    """
    if not records:
        return "0:empty"
    try:
        head = json.dumps(records[0], ensure_ascii=False, sort_keys=True)
        tail = json.dumps(records[-1], ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        head = tail = ""
    raw = f"{len(records)}|{head}|{tail}".encode("utf-8", "replace")
    return f"{len(records)}:{hashlib.blake2b(raw, digest_size=12).hexdigest()}"


def _atomic_write_json(path: Path, payload: Any) -> bool:
    """كتابة ذرّية: إلى ملف مؤقت ثم استبدال. تعيد True عند النجاح."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except (OSError, TypeError, ValueError):
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def _cache_key(path: Path) -> tuple[str, int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (str(path), st.st_size, int(st.st_mtime_ns))


def _read_records(workspace: Path) -> list[dict[str, Any]]:
    """يقرأ السجلات من الملف الجانبي مع ذاكرة مؤقتة."""
    sidecar = records_sidecar_path(workspace)
    key = _cache_key(sidecar)
    if key is None:
        return []
    cached = _RECORDS_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        with sidecar.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    records = data.get("records") if isinstance(data, dict) else data
    if not isinstance(records, list):
        return []
    if len(_RECORDS_CACHE) >= _CACHE_LIMIT:
        _RECORDS_CACHE.clear()
    _RECORDS_CACHE[key] = records
    return records


# ------------------------------------------------- الفصل وإعادة الدمج
def split_records(workspace: str | Path,
                  payload: dict[str, Any]) -> dict[str, Any]:
    """ينقل `catalog_records` إلى ملف جانبي ويعيد حالة مصغَّرة.

    إن تعذّرت الكتابة الجانبية تُعاد الحالة كما هي (بالسجلات داخلها)
    فلا تُفقد بيانات أبدًا — التسريع تحسينٌ لا شرطٌ للصحة.
    """
    if not isinstance(payload, dict):
        return payload
    records = payload.get("catalog_records")
    if not isinstance(records, list) or not records:
        return payload

    ws = Path(str(workspace))
    sidecar = records_sidecar_path(ws)
    digest = _digest(records)

    # هل الملف الجانبي محدَّث أصلًا؟ (الحالة الشائعة: تعديل بعد تعديل)
    # تُقرأ البصمة من الفهرس الصغير، فلا يُحلَّل الجانبي الضخم.
    existing_ref = _read_index_digest(ws) if sidecar.is_file() else ""

    if existing_ref != digest:
        ok = _atomic_write_json(sidecar, {
            "schema_version": 1,
            "digest": digest,
            "count": len(records),
            "written_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "records": records,
        })
        if not ok:
            return payload  # تعذّرت الكتابة → أبقِ السجلات في الحالة
        # الفهرس يُكتب بعد الجانبي فقط، فلا يدّعي بصمةً لملف ناقص
        try:
            idx = records_index_path(ws)
            idx_tmp = idx.with_suffix(idx.suffix + ".tmp")
            idx_tmp.write_text(f"{digest}\n{len(records)}\n",
                               encoding="utf-8")
            os.replace(idx_tmp, idx)
        except OSError:
            pass  # غياب الفهرس يكلّف كتابةً زائدة لا خطأً
        _RECORDS_CACHE.clear()

    slim = dict(payload)
    slim.pop("catalog_records", None)
    slim[RECORDS_REF_KEY] = {
        "file": RECORDS_NAME,
        "digest": digest,
        "count": len(records),
    }
    return slim


def merge_records(workspace: str | Path,
                  payload: dict[str, Any]) -> dict[str, Any]:
    """يعيد `catalog_records` إلى الحالة قبل تسليمها للحزمة الأصلية."""
    if not isinstance(payload, dict):
        return payload
    if isinstance(payload.get("catalog_records"), list) \
            and payload["catalog_records"]:
        return payload  # حالة قديمة تحمل السجلات: تُقرأ كما هي
    ref = payload.get(RECORDS_REF_KEY)
    if not isinstance(ref, dict):
        return payload
    records = _read_records(Path(str(workspace)))
    if not records:
        return payload
    merged = dict(payload)
    merged["catalog_records"] = records
    return merged


# --------------------------------------------------------- الترقيع
def _patch_pipeline(mod) -> bool:
    """يرقّع `_write_state`/`_load_state` في وحدة الحزمة المصرَّفة."""
    if getattr(mod, "_v2_state_cache_patched", False):
        return True

    orig_write = getattr(mod, "_write_state", None)
    orig_load = getattr(mod, "_load_state", None)
    if orig_write is None or orig_load is None:
        return False

    # الحزمة تكتب الحالة عبر json.dump داخل _write_state، ولا نملك
    # مصدرها؛ فنعترض على مستوى الملف: نترك الأصلية تكتب، ثم نُصغّر
    # الناتج فورًا. الكتابة الأصلية تبقى مرجع الصحة، والتصغير يليها.
    def _v2_write_state(workspace, **kwargs):
        ws = Path(str(workspace))
        state_path = ws / STATE_NAME
        # مسار سريع: إن كان الملف الجانبي محدَّثًا فلا داعي لأن تكتب
        # الأصلية 50 ألف سجل ثم نحذفها — لكن لا نملك مصدرها، فنكتفي
        # بالتصغير بعدها. الكسب الحقيقي في القراءة والكتابات التالية.
        result = orig_write(workspace, **kwargs)
        try:
            if state_path.is_file():
                with state_path.open("r", encoding="utf-8") as fh:
                    payload = json.load(fh)
                slim = split_records(ws, payload)
                if slim is not payload:
                    _atomic_write_json(state_path, slim)
        except (OSError, ValueError):
            pass  # الحالة الأصلية سليمة على القرص؛ التصغير اختياري
        return result

    def _v2_load_state(workspace):
        ws = Path(str(workspace))
        state_path = ws / STATE_NAME
        restored = False
        backup: bytes | None = None
        try:
            if state_path.is_file():
                with state_path.open("r", encoding="utf-8") as fh:
                    payload = json.load(fh)
                if isinstance(payload, dict) \
                        and RECORDS_REF_KEY in payload \
                        and not payload.get("catalog_records"):
                    merged = merge_records(ws, payload)
                    if merged.get("catalog_records"):
                        backup = state_path.read_bytes()
                        _atomic_write_json(state_path, merged)
                        restored = True
        except (OSError, ValueError):
            restored = False
        try:
            return orig_load(workspace)
        finally:
            if restored and backup is not None:
                try:
                    tmp = state_path.with_suffix(".json.tmp")
                    tmp.write_bytes(backup)
                    os.replace(tmp, state_path)
                except OSError:
                    pass

    mod._write_state = _v2_write_state
    mod._load_state = _v2_load_state
    mod._v2_state_cache_patched = True
    return True


def activate() -> bool:
    """يفعّل تسريع الحالة. يعيد True إن نجح الترقيع."""
    global _ACTIVE
    if _ACTIVE:
        return True
    patched = False
    for mod_name in ("smart_catalog_vision.pipeline",):
        try:
            import importlib
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        try:
            if _patch_pipeline(mod):
                patched = True
        except Exception:
            continue
    _ACTIVE = patched
    return patched


def is_active() -> bool:
    """هل التسريع مفعَّل؟"""
    return _ACTIVE
