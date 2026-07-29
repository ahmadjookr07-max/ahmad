# -*- coding: utf-8 -*-
"""integration_v2 — دمج محرك V2 مع خط المعالجة القديم (pyc).

activate() يرقّع FinalImageProcessor.process في final_images وpipeline
لتوجيه إنتاج الصور النهائية عبر ProcessorV2 مع التسمية الموحدة الجديدة،
مع fallback للأصلي عند أي خطأ. IMAGE_OVERRIDES تسمح بتخصيص خيارات كل صورة.
"""
from __future__ import annotations

import dataclasses
import os
import threading
from pathlib import Path

from typing import TYPE_CHECKING

from .naming_v2 import (next_sequence, build_name, build_name_dash,
                        UNIT_SUFFIX_DEFAULT, SCHEME_DASH,
                        load_saved_settings, parse_name)

if TYPE_CHECKING:  # للتحليل الساكن فقط — لا يُحمّل عند التشغيل
    from .processor_v2 import ProcessorV2, ProcessOptionsV2


def _lazy_processor_mod():
    """استيراد كسول لـ processor_v2 (cv2/numpy ثقيلة) — يسرّع الإقلاع
    لأن activate() تُستدعى قبل ظهور النافذة، والمحرك لا يُحتاج فعليًا
    إلا عند معالجة أول صورة."""
    from . import processor_v2
    return processor_v2


def __getattr__(name):  # PEP 562 — توافق خلفي لمن يستورد الأسماء من هنا
    if name in ("ProcessorV2", "ProcessOptionsV2"):
        return getattr(_lazy_processor_mod(), name)
    raise AttributeError(name)


_LOCK = threading.Lock()
_PROCESSOR = None  # ProcessorV2 | None — يُنشأ كسوليًا
_MODEL_DIR = ""
_ACTIVE = False

# per-source-path overrides: {source_path: ProcessOptionsV2 | dict}
IMAGE_OVERRIDES: dict[str, object] = {}
# per-source-path unit override: {source_path: unit}
UNIT_OVERRIDES: dict[str, str] = {}
# إعدادات حقائق تغذية افتراضية تطبق على كل صور الدفعة (تفعلها الواجهة)
DEFAULT_NUTRITION: dict = {}


def set_default_nutrition(settings: dict | None) -> None:
    """يعتمد إعدادات حقائق التغذية كوضع افتراضي لكل الصور القادمة."""
    DEFAULT_NUTRITION.clear()
    if settings:
        DEFAULT_NUTRITION.update(settings)


def _coerce_options(obj, source_path: str = ""):
    """يحول dict قادمة من نافذة حقائق التغذية (أو أي مصدر) إلى
    ProcessOptionsV2 جاهزة للمعالج — مع تحويل bbox النسبي (x1,y1,x2,y2)
    إلى بكسلات (x,y,w,h) وبناء InsetPlacement من anchor/scale/offset."""
    mod = _lazy_processor_mod()
    if obj is None:
        opts = mod.ProcessOptionsV2()
        if DEFAULT_NUTRITION:
            return _apply_nutrition_dict(opts, DEFAULT_NUTRITION, source_path)
        return opts
    if isinstance(obj, mod.ProcessOptionsV2):
        return obj
    if isinstance(obj, dict):
        opts = mod.ProcessOptionsV2()
        return _apply_nutrition_dict(opts, obj, source_path)
    return obj


def _apply_nutrition_dict(opts, d: dict, source_path: str = ""):
    """يطبق مفاتيح نافذة حقائق التغذية على ProcessOptionsV2."""
    mode = str(d.get("nutrition_mode", "none") or "none")
    if mode in ("none", "not_found"):
        opts.nutrition_mode = "none"
    elif mode == "remove":
        # الإزالة تتم في طبقة لاحقة — المعالج لا يدمج شيئًا
        opts.nutrition_mode = "remove"
    else:
        opts.nutrition_mode = mode
    src = str(d.get("nutrition_source", "") or
              d.get("nutrition_source_path", "") or "")
    if src and src != str(source_path):
        opts.nutrition_source_path = src
    bbox = d.get("nutrition_bbox")
    if bbox and len(bbox) == 4:
        x1, y1, x2, y2 = (float(v) for v in bbox)
        if max(x1, y1, x2, y2) <= 1.0:
            # نسب — حولها لبكسلات عند المعالجة لاحقًا عبر مصدر الصورة
            try:
                import numpy as _np
                import cv2 as _cv2  # noqa: F401 — ضمان توفر القراءة
                ref = src or str(source_path)
                img = None
                if ref:
                    data = _np.fromfile(ref, _np.uint8)
                    img = _cv2.imdecode(data, 1)
                if img is not None:
                    H, W = img.shape[:2]
                    px = (int(x1 * W), int(y1 * H),
                          max(1, int((x2 - x1) * W)),
                          max(1, int((y2 - y1) * H)))
                    opts.nutrition_bbox = px
            except Exception:
                opts.nutrition_bbox = None
        else:
            # قيم بكسلية جاهزة بصيغة (x, y, w, h) — تمر كما هي
            opts.nutrition_bbox = (int(x1), int(y1), int(x2), int(y2))
    anchor = d.get("nutrition_anchor")
    scale = d.get("nutrition_scale")
    offset = d.get("nutrition_offset") or (0.0, 0.0)
    if anchor or scale:
        try:
            from .nutrition_v2 import InsetPlacement
            ox, oy = (float(offset[0]), float(offset[1]))
            opts.nutrition_placement = InsetPlacement(
                anchor=str(anchor or "bottom_left"),
                offset_x=int(ox * 800), offset_y=int(oy * 700),
                scale=float(scale or 0.28)).clamp()
        except Exception:
            pass
    values = d.get("nutrition_values")
    if values and hasattr(opts, "nutrition_values"):
        opts.nutrition_values = values
    return opts


def set_override(source_path: str, options) -> None:
    if isinstance(options, dict):
        options = _coerce_options(options, str(source_path))
    IMAGE_OVERRIDES[str(source_path)] = options


def set_unit_override(source_path: str, unit: str) -> None:
    UNIT_OVERRIDES[str(source_path)] = unit


def clear_overrides() -> None:
    IMAGE_OVERRIDES.clear()
    UNIT_OVERRIDES.clear()


def get_processor(model_dir: str = ""):
    global _PROCESSOR, _MODEL_DIR
    with _LOCK:
        if _PROCESSOR is None or (model_dir and model_dir != _MODEL_DIR):
            _MODEL_DIR = model_dir or _default_model_dir()
            _PROCESSOR = _lazy_processor_mod().ProcessorV2(_MODEL_DIR)
    return _PROCESSOR


def _default_model_dir() -> str:
    try:
        from .paths_v2 import models_dir
        return models_dir()
    except Exception:
        here = Path(__file__).parent
        for cand in [here / "models",
                     here.parent.parent / "resources" / "models",
                     Path("/home/ubuntu/v2_project/models_v2")]:
            if cand.is_dir():
                return str(cand)
        return str(here)


# مجلد بيانات التطبيق الذي تحفظ فيه سياسة التسمية (تعيّنه الواجهة عند الإقلاع)
NAMING_DATA_ROOT: str = ""


def set_naming_data_root(path: str | Path) -> None:
    global NAMING_DATA_ROOT
    NAMING_DATA_ROOT = str(path)


def _current_naming_settings():
    if NAMING_DATA_ROOT:
        try:
            return load_saved_settings(NAMING_DATA_ROOT)
        except Exception:
            pass
    return None


def build_output_stem(out_dir: str | Path, item: str,
                      unit: str = UNIT_SUFFIX_DEFAULT) -> str:
    """اسم الملف التالي للصنف وفق سياسة التسمية المحفوظة.

    النمط الجديد (dash): الصورة الأولى {item}_{unit} ثم عند وصول صورة
    ثانية تُرقّم الجديدة -2 (ويُعاد ترقيم الأولى إلى -1 عبر rename لاحق
    في طبقة الواجهة إن أمكن). النمط الكلاسيكي: حبه، 2_حبه، 3_حبه..."""
    out_dir = Path(out_dir)
    stems = [p.stem for p in out_dir.glob("*.webp")] if out_dir.is_dir() else []
    seq = next_sequence(stems, item)
    settings = _current_naming_settings()
    if settings is not None and settings.enabled and \
            settings.scheme == SCHEME_DASH:
        # عدد الصور الموجودة للصنف حتى الآن + هذه = total
        existing = sum(1 for s in stems
                       if (pn := parse_name(s)) and pn.item == str(item))
        return build_name_dash(item, seq, unit, total=existing + 1)
    if settings is not None and settings.enabled:
        return settings.render(item, seq, unit, total=seq)
    return build_name(item, seq, unit)


def _wrap_result(result_cls, ok: bool, output_path: str, error: str,
                 original_kwargs: dict):
    """يبني كائن نتيجة متوافقًا مع dataclass القديم ديناميكيًا."""
    if result_cls is None:
        return None
    try:
        fields = {f.name for f in dataclasses.fields(result_cls)}
    except TypeError:
        fields = set()
    kwargs = {}
    for name, value in [("success", ok), ("ok", ok),
                        ("output_path", output_path), ("path", output_path),
                        ("error", error), ("error_message", error)]:
        if name in fields:
            kwargs[name] = value
    for k, v in original_kwargs.items():
        if k in fields and k not in kwargs:
            kwargs[k] = v
    try:
        return result_cls(**kwargs)
    except Exception:
        return None


def activate(model_dir: str = "") -> bool:
    """يفعّل الترقيع على FinalImageProcessor في الوحدات القديمة."""
    global _ACTIVE
    if _ACTIVE:
        return True
    patched = False
    for mod_name in ("smart_catalog_vision.final_images",
                     "smart_catalog_vision.pipeline"):
        try:
            import importlib
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        cls = getattr(mod, "FinalImageProcessor", None)
        if cls is None or getattr(cls, "_v2_patched", False):
            continue
        original = cls.process

        def make_v2_process(orig):
            def _v2_process(self, source_path, output_path, *args, **kwargs):
                try:
                    src = str(source_path)
                    opts = _coerce_options(IMAGE_OVERRIDES.get(src), src)
                    proc = get_processor(model_dir)
                    res = proc.process(src, str(output_path), opts)
                    if res.ok:
                        try:
                            return orig(self, source_path, output_path,
                                        *args, **kwargs) \
                                if os.environ.get("V2_CHAIN_OLD") else \
                                _mk_result(orig, self, res)
                        except Exception:
                            return _mk_result(orig, self, res)
                    # فشل V2 → الأصلي
                    return orig(self, source_path, output_path,
                                *args, **kwargs)
                except Exception:
                    return orig(self, source_path, output_path,
                                *args, **kwargs)
            return _v2_process

        def _mk_result(orig, self_obj, res):
            # حاول استنتاج صنف النتيجة من أول تشغيل قديم أو من annotations
            result_cls = getattr(orig, "__annotations__", {}).get("return")
            if isinstance(result_cls, str) or result_cls is None:
                # ابحث في الوحدة عن *Result dataclass
                import sys
                mod2 = sys.modules.get(type(self_obj).__module__)
                for attr in dir(mod2):
                    if attr.endswith("Result"):
                        result_cls = getattr(mod2, attr)
                        break
            wrapped = _wrap_result(result_cls, True, res.output_path, "",
                                   {})
            return wrapped if wrapped is not None else res

        cls.process = make_v2_process(original)
        cls._v2_patched = True
        patched = True
    _ACTIVE = patched
    return patched
