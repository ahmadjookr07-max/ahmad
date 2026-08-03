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
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "build" / "windows" / "AhmedAlFaifiMarketImageStudioV2.spec"


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
                                  "collect_data_files")):
            break
        keep.append(node)

    if not keep:
        print("✗ لم أجد منطق الاكتشاف في الـspec")
        return 1

    mod = ast.Module(body=keep, type_ignores=[])
    code = compile(mod, filename=str(SPEC), mode="exec")
    ns: dict[str, object] = {"ROOT": ROOT, "Path": Path,
                             "SystemExit": SystemExit}
    try:
        exec(code, ns)
    except SystemExit as exc:
        print(f"✗ حاجز الـspec رفض المستودع الحالي:\n{exc}")
        return 1
    except Exception as exc:
        print(f"✗ منطق الاكتشاف نفسه معطوب: {type(exc).__name__}: {exc}")
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
