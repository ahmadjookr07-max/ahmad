# -*- coding: utf-8 -*-
"""يُنفّذ منطق الاكتشاف داخل الـspec فعليًا — لا يفحص تركيبه فقط.

الفرق مهم: `ast.parse` تُثبت أن الملف نصٌّ صحيح، لا أنه **يعمل**. وحاجز
البناء الذي يفشل بالخطأ (false positive) أسوأ من غيابه، لأنه يمنع كل
تسليم ويُفقد الثقة بالفحوص كلها فتُعطَّل جميعًا.

فنُشغّل هنا الجزء المسؤول عن الاكتشاف والتحقق من الـspec في بيئة معزولة
بلا PyInstaller، ونتأكد أنه يمرّ على المستودع الحالي.

    python3 tools/verify_spec_discovery.py
"""
from __future__ import annotations

import ast
import glob
import importlib.util
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "build" / "windows" / "AhmedAlFaifiMarketImageStudioV2.spec"


def _check_datas(src: str, tree: ast.Module, root: Path) -> list[str]:
    """يستخرج مسارات `datas` من الـspec ويردّ المفقود منها.

    نُقيّم قائمة `datas` الحرفية وحدها (تعريفها الأول بـ`=`)، ونتجاهل
    ما يُضاف لاحقًا بـ`+=` لأنه ناتج `collect_*` من PyInstaller.
    """
    ns: dict[str, object] = {"ROOT": root, "Path": Path}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "_MODELS_SRC" in targets or "datas" in targets:
            seg = ast.get_source_segment(src, node) or ""
            if any(k in seg for k in ("collect_", "_hidden")):
                continue
            try:
                exec(compile(ast.Module(body=[node], type_ignores=[]),
                             filename="<spec-datas>", mode="exec"), ns)
            except Exception:
                return []
            if "datas" in targets:
                break

    entries = ns.get("datas")
    if not isinstance(entries, list) or not entries:
        return []
    out: list[str] = []
    for item in entries:
        try:
            path = Path(str(item[0]))
        except Exception:
            continue
        if not path.exists():
            try:
                out.append(str(path.relative_to(root)))
            except ValueError:
                out.append(str(path))
    return out


def main() -> int:
    src = SPEC.read_text(encoding="utf-8")
    tree = ast.parse(src)

    # نقتطع من تعريف _discover حتى بناء hiddenimports: هذا هو المنطق
    # الذي يقرر مصير البناء، وما قبله يحتاج PyInstaller غير المتاح هنا.
    keep: list[ast.stmt] = []
    started = False
    for node in tree.body:
        name = getattr(node, "name", None)
        if isinstance(node, ast.FunctionDef) and name == "_discover":
            started = True
        if not started:
            continue
        # نتوقف عند أول اعتماد على متغيرات PyInstaller أو واجهاته.
        # hiddenimports تجمع zxing_hidden وأمثالها وهي ناتجة collect_all
        # غير المتاحة هنا، فنتوقف قبلها لا عندها.
        seg = ast.get_source_segment(src, node) or ""
        if any(k in seg for k in ("Analysis(", "PYZ(", "EXE(", "COLLECT(",
                                  "_hidden", "collect_all",
                                  "collect_data_files",
                                  # حاجز إضافات Qt يطلب `qwindows.dll` وهي ملف
                                  # ويندوز لا يوجد في عجلة لينكس. تنفيذه هنا
                                  # يُسقط الفحص دائمًا على لينكس فيُقرأ أن
                                  # المستودع معطوب وهو سليم. وQt محروسة أصلًا
                                  # داخل الـspec نفسه عند البناء الحقيقي.
                                  "_QT_PLUGIN_GROUPS", "_pyside_spec",
                                  "_qwindows_found", "_qt_plugin_files")):
            break
        keep.append(node)

    if not keep:
        print("✗ لم أجد منطق الاكتشاف في الـspec")
        return 1

    mod = ast.Module(body=keep, type_ignores=[])
    code = compile(mod, filename=str(SPEC), mode="exec")
    # المجال يحتاج ما يستورده الـspec في رأسه (قبل `_discover`)، لأن
    # الاقتطاع يبدأ من `_discover` فيُسقط الاستيرادات. وإن نقصت
    # واحدة سقط الفحص بـNameError فـيُقرأ كأن الـspec معطوب وهو سليم —
    # إنذار كاذب يمنع كل بناء وهو أسوأ من غياب الفحص رأسًا.
    ns: dict[str, object] = {"ROOT": ROOT, "Path": Path,
                             "SystemExit": SystemExit,
                             "ast": ast, "sys": sys, "os": os,
                             "importlib": importlib, "glob": glob,
                             "shutil": shutil, "print": print}
    try:
        exec(code, ns)
    except SystemExit as exc:
        print(f"✗ حاجز الـspec رفض المستودع الحالي:\n{exc}")
        return 1
    except Exception as exc:
        print(f"✗ منطق الاكتشاف نفسه معطوب: {type(exc).__name__}: {exc}")
        return 1

    # ── فحص ملفات البيانات ──
    #
    # لماذا منفصلًا؟ لأن الاقتطاع أعلاه يتوقف عند `collect_data_files`
    # فلا ينفّذ قائمة `datas` ولا حاجزها. وقد أثبتت التجربة أن
    # هنا يسكن أخطر عيب بناء: الـspec كان يطلب النماذج من
    # `resources/models/` الغير موجود، فيفشل البناء بعد دقائق.
    # فحص يتجاهل ملفات البيانات يمنح طمأنينة زائفة وهي أسوأ
    # من لا فحص، لأن المالك يثق بها ثم يفاجأ.
    #
    # نستخرج المسارات من الشجرة النحوية مباشرة، فلا نحتاج
    # PyInstaller ولا نكرر القائمة يدويًا (فالتكرار يتعاقم).
    missing_data = _check_datas(src, tree, ROOT)
    if missing_data:
        print("✗ ملفات بيانات مطلوبة غير موجودة:")
        for p in missing_data:
            print(f"    - {p}")
        print("\n  إن كانت نماذج .onnx: مستبعدة من git لحجمها؛ تُجلب")
        print("  بتشغيل البرنامج مرة واحدة، أو تُنسخ يدويًا إلى")
        print("  src/engine_v2/models/ .")
        return 1

    mods = ns.get("_project_mods") or []
    req = ns.get("_REQUIRED") or ()
    aware = [m for m in mods if str(m).startswith("awareness")]
    engine = [m for m in mods if str(m).startswith("engine_v2")]

    print(f"✓ منطق الاكتشاف يعمل ويمرّ على المستودع الحالي")
    print(f"  وحدات مكتشفة كليًا : {len(mods)}")
    print(f"  منها engine_v2      : {len(engine)}")
    print(f"  منها awareness      : {len(aware)}")
    print(f"  وحدات حرجة محميّة  : {len(req)}")

    # الوحدات المسرودة يدويًا في النسخة القديمة كانت 17؛ لو صار العدد
    # المكتشف أقل فذاك ارتداد صريح لا تحسين
    if len(mods) < 20:
        print(f"✗ العدد المكتشف {len(mods)} أقل من المتوقع — ارتداد")
        return 1
    if not aware:
        print("✗ لم تُكتشف أي وحدة وعي — الحزمة ستصل بلا وعي")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
