# -*- coding: utf-8 -*-
"""test_env_resilience — التطبيق يعمل في **أي بيئة** بلا انهيار.

يحاكي غياب كل تبعية اختيارية (onnxruntime، النموذج، Tesseract، PQC،
tkinter) ويتأكد أن التطبيق:
  1) لا يرمي استثناءً خاماً،
  2) يعرض رسالة عربية واضحة قابلة للتنفيذ،
  3) يتابع بقية العمل طبيعياً.

يُشغَّل: PYTHONPATH=src python3 tests/test_env_resilience.py
"""
from __future__ import annotations

import builtins
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "windows_app"))
sys.path.insert(0, str(ROOT / "owner_studio"))

import numpy as np  # noqa: E402

FAILED: list[str] = []
PASSED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASSED.append(name)
        print(f"  ✓ {name}")
    else:
        FAILED.append(f"{name} — {detail}")
        print(f"  ✗ {name} — {detail}")


class HideModules:
    """يخفي وحدات معيّنة عن الاستيراد داخل نطاق with."""

    def __init__(self, *names: str):
        self.names = set(names)
        self._real_import = builtins.__import__
        self._saved: dict[str, object] = {}

    def _fake_import(self, name, globals=None, locals=None,
                     fromlist=(), level=0):
        root = name.split(".")[0]
        if root in self.names:
            raise ImportError(f"وحدة مخفية للاختبار: {name}")
        return self._real_import(name, globals, locals, fromlist, level)

    def __enter__(self):
        for n in list(sys.modules):
            if n.split(".")[0] in self.names:
                self._saved[n] = sys.modules.pop(n)
        builtins.__import__ = self._fake_import
        return self

    def __exit__(self, *exc):
        builtins.__import__ = self._real_import
        sys.modules.update(self._saved)
        return False


def _sample_image() -> np.ndarray:
    img = np.full((180, 220, 3), 245, np.uint8)
    img[40:140, 50:170] = (60, 120, 200)
    return img


# ---------------------------------------------------------------- 1) probes
def test_probes_never_raise() -> None:
    print("\n[1] الفحوص الرخيصة لا ترمي استثناءً أبداً")
    from engine_v2 import runtime_deps_v2 as rd
    for fn in (rd.have_onnx, rd.have_ocr, rd.have_pqc, rd.have_tk):
        try:
            val = fn()
            check(f"{fn.__name__}() → {val}", isinstance(val, bool))
        except Exception as exc:  # pragma: no cover
            check(f"{fn.__name__}()", False, f"رمى {exc!r}")

    d = rd.writable_models_dir()
    check("مجلد النماذج قابل للكتابة", isinstance(d, Path) and d.is_dir(),
          str(d))

    st = rd.model_status()
    check("model_status يعيد قاموساً", isinstance(st, dict)
          and "available" in st)

    rep = rd.environment_report(allow_download=False)
    summary = rep.summary_ar()
    check("تقرير البيئة عربي وغير فارغ",
          isinstance(summary, str) and "حالة بيئة التشغيل" in summary)

    for feat in ("cutout", "ocr", "pqc", "tk", "unknown"):
        msg = rd.describe_missing(feat)
        check(f"رسالة عربية لـ{feat}", isinstance(msg, str) and len(msg) > 15)


# ------------------------------------------------------------- 2) no onnx
def test_cutout_without_onnx() -> None:
    print("\n[2] غياب onnxruntime — رسالة واضحة لا انهيار")
    from engine_v2 import runtime_deps_v2 as rd
    from engine_v2.segmentation_v2 import (ProductSegmenterV2,
                                           SmartCutoutUnavailable)
    rd.reset_cache()
    with tempfile.TemporaryDirectory() as td:
        seg = ProductSegmenterV2(td)
        with HideModules("onnxruntime"):
            os.environ["MIS_NO_DOWNLOAD"] = "1"
            try:
                seg.segment(_sample_image())
                check("رفع SmartCutoutUnavailable", False, "لم يُرفع شيء")
            except SmartCutoutUnavailable as exc:
                text = str(exc)
                check("رفع SmartCutoutUnavailable", True)
                check("الرسالة عربية مفهومة",
                      "تعذّر" in text or "غير" in text, text[:60])
            except Exception as exc:
                check("رفع SmartCutoutUnavailable", False,
                      f"استثناء آخر: {exc!r}")
            finally:
                os.environ.pop("MIS_NO_DOWNLOAD", None)
    rd.reset_cache()
    check("SmartCutoutUnavailable متوافق مع المعالجات القديمة",
          issubclass(SmartCutoutUnavailable, FileNotFoundError))


# ------------------------------------------------------------ 3) no model
def test_cutout_without_model() -> None:
    print("\n[3] غياب ملف النموذج مع منع التنزيل — لا انهيار")
    from engine_v2 import runtime_deps_v2 as rd
    with tempfile.TemporaryDirectory() as td:
        empty = Path(td) / "empty"
        empty.mkdir()
        os.environ["MIS_MODELS_CACHE"] = str(empty)
        os.environ["MIS_MODELS_DIR"] = str(empty)
        os.environ["MIS_NO_DOWNLOAD"] = "1"
        # اعزل مسارات البحث الحقيقية (النموذج قد يكون مثبتاً فعلاً)
        real_dirs = rd._search_dirs
        rd._search_dirs = lambda extra=None: [empty]  # type: ignore[assignment]
        try:
            path = rd.ensure_model(str(empty), allow_download=True)
            check("ensure_model يعيد None بلا استثناء", path is None,
                  str(path))
            status = rd.model_status(str(empty))
            check("model_status يقول غير متاح",
                  status["available"] is False, str(status))
            rep = rd.environment_report(str(empty), allow_download=False)
            check("التقرير يذكر أن العزل معطّل",
                  rep.smart_cutout_ready is False and bool(rep.notes))
        finally:
            rd._search_dirs = real_dirs  # type: ignore[assignment]
            os.environ.pop("MIS_MODELS_CACHE", None)
            os.environ.pop("MIS_MODELS_DIR", None)
            os.environ.pop("MIS_NO_DOWNLOAD", None)


# --------------------------------------------------------------- 4) no ocr
def test_nutrition_without_ocr() -> None:
    print("\n[4] غياب pytesseract — إدخال يدوي لا انهيار")
    with HideModules("pytesseract"):
        from engine_v2.nutrition_ocr_v2 import extract_nutrition_data
        from engine_v2.nutrition_smart_v2 import smart_extract
        img = _sample_image()
        try:
            data = extract_nutrition_data(img)
            check("extract_nutrition_data لا ينهار", data is not None)
            check("النتيجة فارغة بثقة صفر", data.confidence == 0.0
                  and not data.rows)
        except Exception as exc:
            check("extract_nutrition_data لا ينهار", False, repr(exc))
        try:
            res = smart_extract(img)
            check("smart_extract لا ينهار", res is not None)
            check("تنبيه عربي للإدخال اليدوي",
                  bool(res.warnings) and any("يدوي" in w or "غير متاح" in w
                                             for w in res.warnings),
                  str(res.warnings))
            check("ok=False عند غياب OCR", res.ok is False)
        except Exception as exc:
            check("smart_extract لا ينهار", False, repr(exc))


# ---------------------------------------------------------- 5) date blur
def test_date_blur_without_ocr() -> None:
    print("\n[5] طمس التواريخ بلا OCR — يتابع بلا كسر")
    with HideModules("pytesseract"):
        try:
            from engine_v2.date_blur_v2 import detect_date_regions
            regions = detect_date_regions(_sample_image())
            check("detect_date_regions يعيد قائمة", isinstance(regions, list))
        except Exception as exc:
            check("detect_date_regions لا ينهار", False, repr(exc))


# --------------------------------------------------------------- 6) no tk
def test_owner_studio_without_tk() -> None:
    print("\n[6] غياب tkinter — استوديو المالك يرسل رسالة لا تتبّعاً")
    import importlib
    with HideModules("tkinter"):
        sys.modules.pop("owner_studio", None)
        try:
            mod = importlib.import_module("owner_studio")
            check("استيراد owner_studio بلا tkinter ينجح", True)
            check("TK_AVAILABLE=False", mod.TK_AVAILABLE is False)
            msg = mod.tk_missing_message()
            check("رسالة tkinter عربية", "tkinter" in msg and "تعذّر" in msg)
            try:
                mod.main()
                check("main() يخرج بأمان", False, "لم يخرج")
            except SystemExit as exc:
                check("main() يخرج بأمان بكود 2", exc.code == 2)
        except Exception as exc:
            check("استيراد owner_studio بلا tkinter ينجح", False, repr(exc))
        finally:
            sys.modules.pop("owner_studio", None)


# -------------------------------------------------------------- 7) no pqc
def test_license_without_pqc() -> None:
    print("\n[7] غياب dilithium-py — الترخيص لا ينهار عند الاستيراد")
    with HideModules("dilithium_py"):
        sys.modules.pop("engine_v2.license_v2", None)
        try:
            import importlib
            lv = importlib.import_module("engine_v2.license_v2")
            check("استيراد license_v2 بلا PQC ينجح", True)
            check("_HAVE_PQC=False", getattr(lv, "_HAVE_PQC", True) is False)
            try:
                lv.generate_pqc_keypair()
                check("generate_pqc_keypair يرفع خطأ واضحاً", False,
                      "لم يرفع")
            except RuntimeError:
                check("generate_pqc_keypair يرفع RuntimeError واضحاً", True)
        except Exception as exc:
            check("استيراد license_v2 بلا PQC ينجح", False, repr(exc))
        finally:
            sys.modules.pop("engine_v2.license_v2", None)


def main() -> int:
    print("=" * 66)
    print("اختبار مرونة البيئة — التطبيق يعمل في أي بيئة")
    print("=" * 66)
    test_probes_never_raise()
    test_cutout_without_onnx()
    test_cutout_without_model()
    test_nutrition_without_ocr()
    test_date_blur_without_ocr()
    test_owner_studio_without_tk()
    test_license_without_pqc()
    print("\n" + "=" * 66)
    print(f"ناجح: {len(PASSED)} · فاشل: {len(FAILED)}")
    if FAILED:
        for f in FAILED:
            print(f"  ✗ {f}")
        print("ENV_RESILIENCE_FAILED")
        return 1
    print("ALL_ENV_RESILIENCE_TESTS_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
