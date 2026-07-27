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

from .naming_v2 import next_sequence, build_name, UNIT_SUFFIX_DEFAULT

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

# per-source-path overrides: {source_path: ProcessOptionsV2}
IMAGE_OVERRIDES: dict[str, object] = {}
# per-source-path unit override: {source_path: unit}
UNIT_OVERRIDES: dict[str, str] = {}


def set_override(source_path: str, options) -> None:
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


def build_output_stem(out_dir: str | Path, item: str,
                      unit: str = UNIT_SUFFIX_DEFAULT) -> str:
    """اسم الملف التالي للصنف وفق التسلسل الموحد (حبه، 2_حبه، 3_حبه...)."""
    out_dir = Path(out_dir)
    stems = [p.stem for p in out_dir.glob("*.webp")] if out_dir.is_dir() else []
    seq = next_sequence(stems, item)
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
                    opts = IMAGE_OVERRIDES.get(src) or \
                        _lazy_processor_mod().ProcessOptionsV2()
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
