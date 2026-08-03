# حالة الجلسة — المرحلة الثالثة (إصلاح العلل فعليًا)

## الهدف الجاري
إصلاح العلل الـ136 فعليًا بالجرّاح مع إثبات عدم الانحدار، ثم بناء
الفهم الدلالي العربي، ثم التحقق من ويندوز.

## ما أُنجز في هذه الجلسة

### 1. تصنيف التبعيات: منع رقعة كارثية
- **المشكلة**: `_OPTIONAL_PACKAGES` قائمة يدوية أدرجت `cv2` و`onnxruntime`
  و`pytesseract` و`xlrd` كـ«اختيارية» مع أنها إلزامية في `requirements.txt`.
  `cv2` مستدعاة **270 مرة**. حمايتها بـ`= None` كانت ستُحوّل خطأ استيراد
  واضحًا عند الإقلاع إلى مئات انهيارات `NoneType` غامضة وسط معالجة الصور.
- **الحل**: `_required_packages(root)` تقرأ `requirements.txt`، و
  `_heavily_used(root)` تعدّ الاستدعاءات (حد 40)، و`_optional_packages()`
  = المرشّحون − الإلزامية − الكثيفة.
- **النتيجة المقيسة**: التشخيص 150 ← **136** علّة (اختفت 14 علّة زائفة).
  الاختيارية الحقيقية: imagehash, psutil, pyzbar, rembg, scipy, skimage, zxingcpp.

### 2. بوابة المعنى (البوابة الخامسة)
`Surgeon._semantics_preserved(old, new)` في `src/awareness/surgeon.py`،
موصولة في `_verify_uncached` بعد بوابة البنية. ثلاثة فحوص:
1. عدّ هياكل التحكّم (`if/for/while/IfExp/Compare/BoolOp`) لا ينقص.
2. لا `raise` جديد (لا يُقلب مسار صامت مقصود إلى انهيار).
3. بصمة القيم المُرجعة الثابتة لا تتغير.

### 3. إصلاح محوّل `log_silent_except`
- كان يُدرج التسجيل **قبل** `pass` فيُخلّف **203 سطر `pass` ميت**.
  الآن يستبدل `pass` بالتسجيل (`lines[body[0]] = ins`).
- كان يسجّل `where=__name__` فقط — 35 سطرًا متطابقًا لا يُميّز موضعًا.
  الآن يُضيف `at='{func}:{line}'` و`err=repr(e)[:200]` إن وُجد `as e`.

### 4. الاختبارات المضافة
- `tests/test_surgeon_gates.py` — **22 تحققًا، صفر فشل**. يشمل رقعًا
  خاطئة متعمّدة (حذف شرط، `raise` مستحدث، تبديل قيمة مُرجعة) وتتأكد
  من رفضها، ورقعًا سليمة وتتأكد من قبولها.
- `tools/dry_run_silent_except.py` — محاكاة جافة: **23 ملفًا نظيفًا،
  صفر مشكلة، صفر pass ميت**.

## توزيع العلل الحالي (136)
| الرمز | العدد |
|---|---:|
| silent_except | 105 |
| silent_fallback_return | 30 |
| hardcoded_abs_path | 1 |

الملفات الأكثر تضررًا: `windows_app/native_app.py` (35)،
`windows_app/v2_ui.py` (17)، `batch_refine_v2.py` (6)،
`photo_editor_v2.py` (6)، `license_v2.py` (5)، `runtime_deps_v2.py` (5).

## واجهات مهمة
- `Surgeon.operate(codes=, reason=, apply=False, max_files=12)` — سطر 1450.
- `Surgeon.plan(issues=None, max_files=12)` — سطر 839.
- `Surgeon._isolate(patches)` — عزل بالبحث الثنائي، يُبقي السليم.
- `TRANSFORMS`: log_silent_except, add_open_encoding, guard_optional_import.
- جذر المشروع: `identity.repo_root()`.
- `max_files=12` سقف الدفعة → 23 ملفًا يحتاج **دفعتين على الأقل**.

### 5. إصلاح بيئة التحقق: رفع عجز هيكلي عن الجرّاح
- **المشكلة**: `_verify_in_sandbox` تنسخ المشروع لشجرة مؤقتة مع
  `ignore_patterns(..., "*.pyc", ...)`. لكن حزمة `src/smart_catalog_vision/`
  مكوّنة من **وحدات مُصرّفة فقط** (`pipeline.pyc`, `final_images.pyc`,
  `product_segmentation.pyc`... كود مملوك بلا مصدر؛ `__init__.py`
  فيه 3 أسطر فقط). فكانت تُنسخ **فارغة** → `cannot import name
  'pipeline' from 'smart_catalog_vision'` → تُرفض كل رقعة تلمس ملفًا
  يعتمد عليها. **رقع سليمة تُرفض لعيب في بيئة التحقق لا فيها.**
- **الحل**: دالة `_stage_ignore(dirpath, names)` و`_STAGE_SKIP_SUFFIX`
  (سطر ~779) — تستبعد `__pycache__` والأوزان الثقيلة و**تحفظ**
  `.pyc` خارج `__pycache__`.
- **النتيجة المقيسة**: `naming_v2.py` صارت تجتاز البوابات الـ٨ كلها
  بعد أن كانت معزولة.

### 6. تشخيص العزل: سببان مختلفان تمامًا
المعاينة الأولى: 5 ملفات مقبولة و**7 معزولة**. بالفحص المنفرد:
- `processor_v2.py`: **سليمة تمامًا** (8 بوابات ✓). عُزلت لأنها كانت في
  دفعة مع رقعة مُفسدة → البحث الثنائي أسقط مجموعتها.
- `license_v2.py`: **مرفوضة بحق** — تُفشل `test_license.py::deactivate`
  (`11 passed / 3 failed`). البوابات الأربع الأخرى أجازتها؛
  بوابة الاختبارات وحدها رصدت الانحدار.
  مواضع علله الخمس: 95, 106, 405, 501, 555. الموقع الحرج هو
  **سطر 501 داخل `def deactivate()`**: `unlink(missing_ok=True)` داخل
  try/except — والاختبار `tests/test_license.py:115-117` يتحقق أن
  `not info9.valid and "لا يوجد" in info9.status`.

## أدوات مُنشأة في هذه المرحلة
- `tools/dry_run_silent_except.py` — محاكاة جافة (`SHOW_DIFF_FOR=n`).
- `tools/run_surgery.py` — تطبيق على دفعات (`--codes`, `--apply`, `--rounds`).
- `tools/why_rejected.py` — يستنطق كل بوابة لملف مرفوض.
- `tools/triage_issues.py` — تصنيف العلل.
- **ملاحظة**: `_verify_uncached` تُرجع `(bool, list[dict])` لا قاموسًا.
  و`operate` تُرجع `SurgeryResult` (كائن) من المُتعلّقة وقاموسًا من
  دالة الوحدة `operate(**kw)`.

## نقاط أمان git
- `4c3dfcf` — قبل تطبيق أي رقعة (تقوية المحرك وبوابة المعنى).
- `423d44c` — طبقة الوعي الأولى.

## الخطوة التالية
فحص لماذا يكسر التسجيل الصامت `deactivate` (سطر 501)، ثم تطبيق
الرقع فعليًا (`apply=True`) على دفعات، وقياس الاختبارات قبل/بعد.

## المصادر الخارجية
محفوظة في `docs/بحث_محركات_الذكاء.md` (أدبيات الإصلاح الآلي والرقعة
الزائفة، وأساليب فهم العربية الخفيفة ومُجذّع ISRI).
