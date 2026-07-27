# سياق المهمة الكامل — تطوير V2.0

## المطلوب النهائي
تطوير النسخة V2.0 من تطبيق "Ahmed Al-Faifi Market Image Studio" (حاليًا 1.2.1) بالبناء على الكود السابق، وتسليم **ملف Setup exe واحد فقط** جاهز للعمل. الخطة الكاملة في `/home/ubuntu/plan.md` واعتمدها المستخدم.

## الملفات المرفوعة في /home/ubuntu/upload/
- `AhmedAlFaifiMarketImageStudio-1.2.1-FULL-PROJECT.zip` — كود المشروع الكامل (948MB)
- `AhmedAlFaifiMarketImageStudio-Setup-1.2.1.exe` — المثبت الحالي
- `��الملفالنهائياصنافالمتجر�.xlsx` — ملف الأصناف (41,936 صف × 5 أعمدة، Sheet1)
- `SmartCatalogVision-Results-20260725-0417.zip` — عينة مخرجات منجزة سابقًا (لأداة إعادة التسمية الخارجية)
- صور JPEG (لقطات شاشة للأخطاء): 3988D8E6(قص متعرج لعبوة كفير ندى)، 7B13D871(تشوه لوني أزرق + حواف سوداء)، IMG_4819(واجهة الربط)، IMG_4818(محرر الاقتصاص)، IMG_4817(نتيجة حقائق تغذية رديئة)، IMG_4816(حقائق تغذية أصلية واضحة)، IMG_4815 و92E19735(نمط التسمية في مجلد النتائج: 10018435_حبه، 10018435_2_حبه، _3_، _4_)، IMG_4814(حواف قص سيئة مقربة)

## المتطلبات العشرة (ملخص)
1. قص حواف مثالي ناعم بدون آثار بيضاء متعرجة (استبدال الخوارزمية بـ segmentation أدق + alpha matting + defringe)
2. Auto-Enhancement (إضاءة/تباين/حدة) مع حفاظ على الدقة + حقائق تغذية واضحة جدًا مع خيار اقتصاصها ووضعها بجانب المنتج
3. أداة مرئية لضبط ميول واستدارة المنتج يدويًا
4. تسمية تسلسلية: [باركود]_حبه ثم [باركود]_2_حبه... + تعديل يدوي قبل الحفظ — تطبق موحدًا على كل الحالات (صورة/صورتين/عدة صور)
5. عرض مخصص لحقائق التغذية بجودة عالية للعميل
6. تصدير WebP Lossless بأعلى جودة، نصوص مقروءة حتى بعد ضغط RAR
7. أداة Bulk Rename مستقلة (نافذة/زر خارجي) لإعادة تسمية ملفات منجزة سابقًا (مثل SmartCatalogVision-Results) بناءً على رقم الصنف مع الحفاظ على الترابط
8. Save & Resume للجلسات
9. ربط لحظي مع الإكسل (42 ألف صنف) + واجهة سريعة الاستجابة
10. UI/UX واسعة بدون تداخل نصوص/أزرار

## طلبات إضافية من المستخدم
- تقليل استهلاك النقاط (عمل مباشر بدون تكرار)
- التوحيد الشامل لمنطق التسمية على كل الحالات، مختبر على 1000+ صورة
- مراجعة الجلسة السابقة (تمت — انظر previous_session_notes.md)
- تفضيلات معروفة: WebP 800×700 خلفية بيضاء، اسم الغلاف رقم_الصنف_حبه، حقوق النشر "احمد الفيفي"، تطبيق سطح مكتب ويندوز بدون واجهة ويب، عرض الاسم الكامل للصنف في الربط اليدوي، الاحتفاظ بموضع المستخدم بعد التعديل اليدوي، حقل ربط يدوي للأصناف غير المؤكدة

## بنية المشروع السابق (مؤكدة)
- Python + مجلد `smart_image_matcher/`
- `windows_app/native_app.py` — الواجهة (native)
- `src/smart_catalog_vision/pipeline.pyc` — المحرك مجمّع PYC (تحقق من توفر المصدر!)
- `build/windows/installer_v121.nsi` — NSIS installer
- `dist/installer/AhmedAlFaifiMarketImageStudio-Setup-1.2.1.exe`
- إزالة الخلفية: U2NetP + OpenCV
- باركود: ZXing-C++ (حزمة Python zxing-cpp)

## الحالة الحالية
- المرحلة 1 من الخطة: تمت مراجعة الجلسة. التالي: فك ضغط ZIP وفحص الكود وتشخيص الأخطاء، فحص SmartCatalogVision-Results zip، فحص ملف الإكسل (سكربت جاهز في /home/ubuntu/inspect_xlsx.py).

## تقدم التنفيذ (آخر تحديث: بعد فحص المحرك)
- المرحلة 1 شبه مكتملة: روجعت الجلسة السابقة (previous_session_notes.md)، فُك ضغط المشروع إلى `/home/ubuntu/v2_project/src_121/smart_image_matcher/` والنتائج القديمة إلى `/home/ubuntu/v2_project/old_results/processed/` (993 ملف webp).
- المحرك pyc يعمل تحت Python 3.12.3 المتوفر في السندبوكس (تم اختبار الاستيراد بنجاح). التفاصيل الكاملة في `notes/engine_api.md`.
- الاعتماديات المثبتة: numpy 1.26.4, opencv-headless, onnxruntime, openpyxl, Pillow. لم يثبت بعد: PySide6, pyzbar, pyinstaller.
- سكربتات الفحص: probe_engine.py, probe_engine2.py في v2_project/.
- المتبقي في المرحلة 1: فحص ملف الإكسل (inspect_xlsx.py موجود في /home/ubuntu لكن يفحص أيضًا zip؛ يحتاج تبسيط)، فحص native_app.py بالتفصيل (4618 سطر)، اختبار المعالجة على صورة عينة لإعادة إنتاج خطأ الحواف، ثم قرار معماري.

## القرار المعماري المبدئي لـ V2
- الإبقاء على المحرك pyc كما هو + بناء طبقة V2 جديدة `v2_enhancements` (قص محسّن، defringe، تحسين، تسمية، جلسات، أداة rename خارجية) فوق native_app.py الذي مصدره متوفر بالكامل.
- البناء النهائي: PyInstaller + NSIS (ملفات build/windows موجودة) — البناء يحتاج ويندوز أو Wine؛ خيار بديل: GitHub Actions runner ويندوز.

## متطلب إضافي (رسالة المستخدم أثناء المرحلة 2)
حقائق التغذية يجب أن تدعم في الواجهة: (أ) إضافة الجدول للصورة النهائية، (ب) إزالته، (ج) حفظه كصورة منفردة مستقلة، (د) حالة "لم يُعثر عليه"، (هـ) اقتصاص وتعديل يدوي كامل على منطقة حقائق التغذية. يُنفذ ضمن المرحلة 2 (النواة) والمرحلة 5 (الواجهة).

## متطلب إضافي 2 (حقائق التغذية — دمج مصغر)
إضافة خيار دمج جدول حقائق التغذية كصورة مصغرة في **الزاوية اليسرى السفلية** من صورة المنتج النهائية (بنفس صورة المنتج). أي أن أوضاع حقائق التغذية النهائية هي: إضافة/إزالة/صورة منفردة مستقلة/دمج مصغر أسفل يسار/لم يُعثر عليه + اقتصاص وتعديل يدوي.

## ملاحظة بيئة (بعد reset)
السندبوكس أُعيد ضبطه: الملفات استُعيدت لكن الحزم المثبتة (numpy/opencv/onnxruntime/openpyxl) تحتاج إعادة تثبيت، ويجب التحقق من وجود models_v2 (isnet وBiRefNet تم تنزيلهما سابقًا) وseg_compare/result_isnet.png (نتيجة ISNet كانت ممتازة conf=0.625، BiRefNet لم يكتمل بسبب ضغط الذاكرة — يُفضّل الاكتفاء بـ ISNet كنموذج V2 الرئيسي لتجنب OOM وحجم 928MB).

## تقدم المرحلة 2 (نواة المعالجة V2) — الحالة: شبه مكتملة
البنية الجديدة في `/home/ubuntu/v2_project/v2/engine_v2/`:
- `segmentation_v2.py`: ProductSegmenterV2 (ISNet رئيسي 171MB في models_v2/isnet-general-use.onnx + fallback u2net القديم)، guided refine، snap alpha، تنظيف مكونات (keep_ratio=0.05)، decontaminate (defringe)، compose_on_white، alpha_bbox.
- `enhancement_v2.py`: auto_enhance (white balance, CLAHE, contrast, unsharp محدود بلا هالات, denoise, descreen لصور الشاشات) + enhance_nutrition_label (قوي للجداول).
- `alignment_v2.py`: estimate_tilt_degrees (PCA/minAreaRect ≤12°)، rotate_with_alpha، perspective_rectify (8 قيم).
- `nutrition_v2.py`: detect_nutrition_table (morphology grid)، crop_region، render_standalone_label، merge_label_inset (أسفل يسار، إطار رمادي، 30% عرض كحد أقصى).
- `processor_v2.py`: ProcessorV2 + ProcessOptionsV2 (width/height 800×700، webp_lossless=True عبر IMWRITE_WEBP_QUALITY=101، nutrition_mode: none|standalone|merge_small|remove|not_found، nutrition_source_path منفصل، manual_crop_corners، manual_rotation_degrees) + ProcessResultV2.

نتائج الاختبار (v2_out/): المنتج ممتاز بلا هالة (4.7s)، حقائق التغذية المنفردة ممتازة، الدمج المصغر يعمل. سكربتات الاختبار: test_processor_v2.py، test_seg_v2.py.

المتبقي: اختبار سريع بعد تعديل keep_ratio وnutrition_source_path، ثم الانتقال للمرحلة 3 (التسمية + أداة rename الخارجية + الربط السريع مع الإكسل).

## خطة التكامل مع التطبيق القديم (مهم للمراحل 3-5)
- الواجهة: `src_121/smart_image_matcher/windows_app/native_app.py` (4618 سطر، مصدر كامل، PySide6). APP_VERSION="1.2.1" في السطر ~147، DATA_ROOT=Documents/SmartCatalogVision.
- native_app يستورد من smart_catalog_vision.pipeline (pyc مجمع 3.12): run_batch, apply_manual_links, apply_individual_image_edit, preview_individual_image_edit + FinalImageOptions.
- استراتيجية V2: نسخ المشروع إلى v2_project/app_v2/، إضافة حزمة engine_v2 بجانب smart_catalog_vision داخل src/، ثم monkey-patch لخط المعالجة النهائي (مثل ما فعل native_app نفسه مع _prepare_individual_source) لتوجيه إنتاج الصور النهائية عبر ProcessorV2، مع إبقاء pipeline القديم للفهرسة/الباركود/التقارير/ZIP.
- الباركود: pyzbar (قديم) — يعمل. الإكسل: I_CODE, I_NAME, ITM_UNT, P_SIZE, BARCODE — 41,936 صف.
- البناء النهائي: PyInstaller 6.21 + NSIS (build/windows/installer_v121.nsi موجود). يتطلب بيئة ويندوز — الخيار: GitHub Actions windows runner، أو Wine في السندبوكس.

## المرحلة 2 مكتملة
البقعة السفلية اختفت بعد _remove_faint_debris. الناتج الآن أكبر وأنظف (المنتج يملأ الإطار، حواف ناعمة بلا هالة، descreen فعال). كل وحدات engine_v2 مختبرة وتعمل. الانتقال للمرحلة 3: نظام التسمية الموحد + أداة إعادة التسمية الخارجية + الربط السريع مع الإكسل.

## متطلب إضافي 3 (حقائق التغذية — إعادة صياغة كاملة)
وضع جديد "rebuild": استخراج نصوص وقيم جدول حقائق التغذية عبر OCR ثم **إعادة بنائه كجدول عربي مصمم نظيف** (نمط "الحقائق الغذائية" الأسود/الأبيض القياسي كما في IMG_4824.PNG: عنوان عريض، عدد الحصص، حجم الحصة، السعرات بخط كبير، صفوف % القيمة اليومية بخطوط فاصلة، فيتامينات في الأسفل)، ويُحفظ الناتج في مجلد مستقل مثل "حقائق التغذية". 
ملاحظة تنفيذية: OCR أوفلاين للعربية صعب — الخطة: Tesseract (ara+eng) مضمّن في المثبّت + قاموس مصطلحات تغذية عربي/إنجليزي لتطبيع الحقول + قالب رسم Pillow/QPainter للجدول القياسي، مع محرر يدوي للقيم قبل الحفظ (لأن دقة OCR على صور الجوال متفاوتة). يُنفذ في نواة V2 (nutrition_v2) + الواجهة (المرحلة 5).

## متطلب إضافي 4 (حقائق التغذية — الموقع والتحكم الكامل)
1. عند "لم يُعثر عليه": تبقى خيارات الإضافة اليدوية (تحديد منطقة يدويًا بالاقتصاص أو تعبئة قالب القيم يدويًا) متاحة.
2. خيار **موقع الملصق** على الصورة النهائية: زوايا أربع (أسفل يسار افتراضي، أسفل يمين، أعلى يسار، أعلى يمين) + موضع حر (تحريك بالسحب) + تغيير الحجم، ينطبق على وضع الدمج المصغر وعلى الصورة المنفردة (محاذاة الجدول داخل اللوحة). تنفيذ النواة: معامل position/scale/offset في merge_label_inset وrender_standalone_label. الواجهة: أدوات سحب وتحريك في محرر حقائق التغذية.

## تقدم المرحلة 3 (نظام حقائق التغذية الموسع)
- Tesseract 5.3.4 + ara + eng مثبت في السندبوكس (apt: tesseract-ocr tesseract-ocr-ara، pip: pytesseract). للويندوز: يجب تضمين tesseract portable + tessdata (ara/eng) داخل المثبت.
- `nutrition_ocr_v2.py` (جديد): FIELD_SPECS قاموس ثنائي اللغة لكل حقول الجدول القياسي، NutritionData/NutritionRow (to_dict/from_dict)، _prepare_for_ocr (upscale+binarize)، extract_nutrition_data (tesseract ara+eng psm6 + مطابقة أسماء الحقول + استخراج الأرقام والنسب مع تحويل أرقام عربية)، blank_template للإدخال اليدوي، FOOTNOTE_AR.
- `nutrition_v2.py` (أعيدت كتابته): InsetPlacement (anchor: bottom_left/bottom_right/top_left/top_right/free + offset_x/y + scale 0.12-0.6 + border + margin)، merge_label_inset بتحكم كامل بالموقع، render_standalone_label مع align (center/left/right/top/bottom)، enhance اختياري.
- `nutrition_render_v2.py` (جديد): render_nutrition_table يرسم الجدول العربي القياسي (عنوان "الحقائق الغذائية"، حصص، سعرات كبيرة، صفوف %، هامش سفلي) عبر Pillow + arabic_reshaper/bidi، بحث خطوط: assets/NotoNaskhArabic ثم نظام. **يلزم**: pip arabic_reshaper python-bidi + تنزيل خط NotoNaskhArabic إلى v2/engine_v2/assets/.
- المتبقي في المرحلة 3: تثبيت الحزم والخط، اختبار OCR على IMG_4816 (جدول واضح)، اختبار الرسم، ثم ربط أوضاع rebuild في processor_v2 (nutrition_mode="rebuild" يحفظ في مجلد "حقائق التغذية").

## المرحلة 3 — حالة متقدمة (قرب الاكتمال)
تم إنجاز واختبار:
- OCR يعمل: بعد إصلاح _prepare_for_ocr (medianBlur+Gaussian descreen ثم upscale 2000 + NlMeans + CLAHE + Otsu — moiré كان يفسد adaptiveThreshold). على IMG_4816: conf=0.80، استخرج servings=67، total_fat=100غ 21%، saturated=20غ، trans=0غ، sugars=0غ. إصلاح _GLUED_G_RE (20G→206). _extract_numbers ترجع (amount, unit_ar, pct) مع _UNIT_MAP.
- الرسم العربي ممتاز: nutrition_render_v2.py يعمل عبر Pillow+raqm (raqm=True في السندبوكس، _TEXT_KW direction=rtl). **رموز مهمة**: % غير موجود في NotoNaskhArabic — استخدم ٪ (U+066A) و٭ (U+066D) بدل *. الناتج v2_out/nut_rebuilt.png مطابق للنمط القياسي.
- الخطوط منزلة في v2/engine_v2/assets/ (NotoNaskhArabic Bold+Regular). حزم: arabic_reshaper python-bidi pytesseract مثبتة، tesseract 5.3.4 (ara+eng).
- nutrition_v2.py: InsetPlacement كامل (4 زوايا+free+scale+offset)، render_standalone_label مع align، merge_label_inset مختبرة (nut_inset_*.png).
- شاشة مراجعة إلزامية بعد OCR (وعد للمستخدم — تطابق 100%): تُنفذ في الواجهة (المرحلة 6).

المتبقي في المرحلة 3: ربط وضع "rebuild" في processor_v2 (nutrition_mode=rebuild → extract_nutrition_data ثم render_nutrition_table ويُحفظ في مجلد "حقائق التغذية" مستقل + حفظ JSON للقيم للتحرير)، ثم advance للمرحلة 4 (التسمية+rename خارجي+ربط إكسل سريع).

## المرحلة 4 — نظام التسمية والفهرس السريع (شبه مكتملة)
وحدات جديدة مختبرة في v2/engine_v2/:
- `naming_v2.py`: build_name/parse_name (يدعم النمطين: الجديد item_2_حبه والقديم item_حبه_2 من 1.2.1)، next_sequence، plan_group_names، plan_bulk_rename (mapping قديم→جديد يحافظ على الترابط) + apply_bulk_rename ثنائي المرحلة لتجنب التصادمات. RenamePlanEntry (ok|conflict|unparsed|unchanged).
- `catalog_index_v2.py`: CatalogIndex — تحميل الإكسل 41,935 صنف في 4.5s أول مرة، 1.4s مع الكاش (.catalog_cache.json بجانب xlsx مفتاحه mtime)، lookup_barcode 0.02ms (مع تسامح check digit)، search_name n-gram 14ms، بحث رقمي 4ms مع بادئات. normalize_text (أرقام عربية→لاتينية، توحيد ألف/تاء/ياء، إزالة حركات).
- **مهم**: أسماء ملفات النتائج القديمة في zip كانت double-mojibake (UTF-8→cp866) — fix_old_names.py يصلحها (991 ملف أصلح). أداة rename الخارجية يجب أن تتضمن unmojibake (cp866/cp437/cp850→utf-8) تلقائيًا.
- النمط الحقيقي القديم: `10000001_حبه.webp`, `10000001_حبه_2.webp` (اللاحقة قبل الرقم!) — النمط الجديد المطلوب: `10018435_حبه`, `10018435_2_حبه`.
- الاختبارات: test_naming_catalog.py كلها OK (بعد دعم legacy يجب إعادة تشغيلها للتأكد أن unparsed=0).
المتبقي بالمرحلة 4: إعادة تشغيل الاختبار للتحقق من legacy parsing، ثم advance للمرحلة 5 (WebP جودة قصوى منجز فعليًا في processor_v2 + نظام الجلسات Save/Resume).

## المرحلة 6 — التكامل مع الواجهة (جارية)
- app_v2/ أنشئ: src/ (smart_catalog_vision pyc + engine_v2 الجديدة) + windows_app/native_app.py + build/ + resources/. الحجم 177MB (يشمل النموذج isnet 171MB إذا نسخ لاحقًا إلى engine_v2/models/).
- integration_v2.py يعمل ومختبر: activate() يرقّع FinalImageProcessor.process في final_images وpipeline معًا؛ _v2_process يستخدم build_output_stem (next_sequence → 10018435_حبه ثم _2_حبه ثم _3_حبه تلقائيًا) وProcessOptionsV2(enhance=...) وIMAGE_OVERRIDES per-source-path (set_override/clear_overrides) وfallback للأصلي عند الخطأ. _wrap_result يبني FinalImageResult ديناميكيًا بحقول dataclass المتاحة.
- test_integration.py: INTEGRATION OK (ثلاث صور لنفس الصنف سُميت تسلسليًا وأنتجت webp).
- ملاحظة: ProcessOptionsV2 الحقول: enhance (وليس auto_enhance)، width/height/margin، nutrition_mode/bbox/source_path، manual_rotation_degrees/manual_crop_corners، webp_lossless.
- المتبقي بالمرحلة 6: تعديل native_app.py → native_app_v2: (1) استدعاء activate() عند البدء، (2) رفع APP_VERSION إلى 2.0.0، (3) لوحة حقائق التغذية الكاملة (أوضاع none|standalone|merge_small|rebuild|remove|not_found + موقع/مقياس/سحب + شاشة مراجعة OCR إلزامية بحقول قابلة للتحرير)، (4) زر "أداة إعادة التسمية" خارجي (نافذة مستقلة تستخدم naming_v2.plan/apply_bulk_rename + unmojibake)، (5) Save/Resume عبر session_v2.SessionStore (منتقي جلسات عند البدء)، (6) الربط اللحظي عبر catalog_index_v2 (استبدال البحث القديم)، (7) توسيع النوافذ/الهوامش لمنع تداخل النصوص (window min 1280x800، تكبير الأزرار العربية).

## نقاط الدمج في native_app.py (مؤكدة بالفحص)
بنية `_build_ui` (سطر ~1122): header_frame ثابت الارتفاع 74 ويحوي header_layout (QHBoxLayout) بترتيب: title_block(1) ثم phase_label ثم version — **نقطة إضافة أزرار V2**: إدراج زرين قبل version في header_layout: "أداة إعادة التسمية" و"الجلسات". دالة main() في نهاية الملف (~4604): `window = MainWindow()` ثم show — **نقطة الحقن**: بعد إنشاء window نستدعي install_v2(window, DATA_ROOT) + integration activate. لا يوجد sys.path منشئ في native_app — يعتمد على PyInstaller؛ يجب إضافة sys.path لـ ../src في ملف تشغيل جديد `native_app_v2.py` (wrapper) بدل تعديل الملف الأصلي بكثافة:
- wrapper يعمل: sys.path.insert(src) → engine_v2.integration_v2.activate() → import native_app → patch APP_VERSION="2.0.0" قبل main → install_v2 عبر monkeypatch على MainWindow.__init__ (بعد استدعاء الأصلي).
- v2_ui.py (في windows_app/) جاهز: NutritionDialog (كل الأوضاع + CropSelectLabel سحب/تحجيم + OcrWorker + NutritionReviewDialog إلزامية)، BulkRenameDialog (معاينة خطة + تنفيذ عبر naming_v2.plan/apply_bulk_rename + خريطة قديم=جديد)، SessionDialog (استئناف)، install_v2(main_window, data_root) يوسع النافذة 1280x800 ويضيف stylesheet ويجهز v2_open_rename_tool/v2_open_sessions.
- widgets الرئيسية في MainWindow: workflow_pages (QStackedWidget)، setup_page، results_page، individual_editor_dialog، status_label، phase_label، header_frame.
- ملاحظة: NutritionDialog يحتاج ربطًا بزر في صفحة النتائج (بجانب "تحرير احترافي") — يُنفذ في wrapper عبر البحث عن أزرار موجودة أو إضافة زر في manual_group.
- الاختبار المطلوب تاليًا: تثبيت PySide6 في السندبوكس، ثم gui smoke test عبر offscreen: QT_QPA_PLATFORM=offscreen python3 native_app_v2.py --gui-smoke-test-output /tmp/smoke.json (الخيار مدعوم في native_app).
- fields NutritionRow: key,label_ar,amount,unit,percent — NutritionData: servings,serving_size,calories,rows + to_dict/from_dict + blank_template().

## المرحلة 6 — حالة متقدمة (السموك تيست ناجح)
native_app_v2.py (wrapper) + v2_ui.py مكتملان ويعملان: `QT_QPA_PLATFORM=offscreen python3 native_app_v2.py --gui-smoke-test-output /tmp/smoke_v2.json` → EXIT=0، gui_test_passed=true، version=2.0.0، manual_controls_separated=true. الدروس: (1) لا تستخدم stylesheet عام min-height — يكسر صفوف manual_group المضغوطة؛ (2) الحد الأدنى للنافذة 1180x760 (نفس ما صمم له 1.2.1) مع resize افتراضي 1280x800؛ (3) زر "حقائق التغذية" يُدرج في صف quick_controls بجانب jump_to_previews_button (بحث عن sub-layout يحوي الزر). أزرار الهيدر: "أداة إعادة التسمية" + "الجلسات" مدرجة قبل شارة الإصدار.
ملاحظة بصرية من اللقطة عند 1180px: صف quick_controls أصبح مزدحمًا (6 عناصر: اعتماد مرجع/اقتراح قريب/ربط بالمرجع/عرض الصورة/حقائق التغذية/لا يوجد مرجع) والنصوص تُقتطع ("راج فر"، "ماد مر") — التحسين المقترح: نقل زر حقائق التغذية لصف manual_controls بجانب "ربط الآن" بدلًا من quick_controls المزدحم، أو تقصير نص الشارة. عند 1280px قد يكون مقبولًا لكن يجب التحقق.
المتبقي بالمرحلة 6: إصلاح ازدحام الصف، ربط Save/Resume فعليًا بحالة النتائج (v2_restore_session)، حفظ الجلسة تلقائيًا عند التغييرات، ثم المرحلة 7 (اختبارات شاملة) والمرحلة 8 (بناء exe عبر GitHub Actions windows runner أو Wine — ملفات build/windows/installer_v121.nsi موجودة، يجب تحديثها لـ2.0.0 وإضافة tesseract portable + isnet model + خطوط Noto للأصول المضمنة).
مسارات مهمة: المشروع app_v2 في /home/ubuntu/v2_project/app_v2/ (windows_app/native_app.py الأصلي 4618 سطر بدون تعديل + native_app_v2.py + v2_ui.py، src/smart_catalog_vision pyc + src/engine_v2)، النموذج isnet في /home/ubuntu/v2_project/models_v2/isnet-general-use.onnx (يجب نسخه إلى app_v2/src/engine_v2/models/ قبل البناء)، الخطوط في v2/engine_v2/assets (يجب التأكد من نسخها إلى app_v2/src/engine_v2/assets/).

## المرحلة 6 — تشخيص الحفظ/الاستئناف (جارٍ)
- السموك تيست ناجح EXIT=0 بعد نقل زر "حقائق التغذية" إلى صف manual_controls بجانب "ربط الآن" (anchor=manual_link_button، insertWidget بعد الزر).
- v2_ui.py: install_v2 يضيف الآن v2_capture_state/v2_save_session/v2_restore_session + autosave QTimer كل 3 دقائق. SessionStore واجهة داخلية (state, upsert_image(key,...), save(force), load(sid), list_sessions). المفتاح = source_name (فريد).
- test_session_ui.py: يحفظ 5 عناصر وهمية من نافذة ثم يستعيدها في نافذة أخرى. الحفظ والبيانات صحيحة (rows=5, item4_code=10004) لكن استعادة الموضع تفشل: currentRow=0 بدل 3.
- السبب المرجح: _restore_results_position يبحث عن source_cell.data(Qt.UserRole)==source_name في العمود 0. يجب التحقق من قيمة UserRole المخزنة في العمود 0 عند _populate_results — قد تكون source_path وليس source_name، أو العمود مختلف. الحل البديل الآمن: استدعاء selectRow متأخر عبر QTimer.singleShot(0,...) بعد _show_results_page (لأن _show_results_page يجدول _render_selected_preview فقط ولا يغير التحديد) — لكن _populate_results مع restore_position=None يستدعي _select_first_result فورًا؛ مع restore_position يستدعي _restore_results_position(position) مباشرة. إذن fallback_row=3 يجب أن يعمل حتى لو لم يطابق الاسم... تحقق: ربما items في الجدول لا تُدرج فورًا (rowCount=0 وقت الاستدعاء) بسبب معالجة مؤجلة، أو _visible_result_rows فارغ وقتها فيعيد الدالة مبكرًا ويؤخذ أقرب صف. يجب تشخيص بطباعة rowCount وUserRole.
- أوامر الاختبار: `cd /home/ubuntu/v2_project && python3 test_session_ui.py`، السموك: `cd app_v2/windows_app && QT_QPA_PLATFORM=offscreen python3 native_app_v2.py --gui-smoke-test-output /tmp/smoke_v2.json`

## متطلب جديد (مؤكد): دعم أي ملف إكسل مستقبلي
كشف تلقائي مرن لأعمدة الإكسل (رقم الصنف/الباركود/الاسم/الوحدة) بغضّ النظر عن الترتيب أو المسميات؛ يجب التحقق أن catalog_index_v2.py يعتمد على header detection heuristics وليس على مواقع أعمدة ثابتة، وأن الواجهة تتيح اختيار ملف إكسل جديد في أي وقت (زر اختيار الملف القديم موجود في native_app — الفهرس V2 يجب أن يُبنى عند كل تحميل).

## متطلب جديد (مؤكد): وحدات التسمية حبه/شده/كرتون من الإكسل
عند الربط تُقرأ وحدة الصنف من عمود الوحدة في الإكسل وتدخل في اسم الملف (10014649_حبه.webp). إذا كان الصنف بأكثر من وحدة في الإكسل: خيار للمستخدم لكل صورة + إعداد عام يطبق على كل الأصناف (توليد نسخة لكل وحدة من نفس الصورة تلقائيًا أو اعتماد وحدة افتراضية). النمط: code_unit, code_2_unit, code_3_unit. يتطلب: (أ) group_units في CatalogIndex (by_code يحتفظ الآن بأول idx فقط — يجب by_code_all list)، (ب) خيارات في naming_v2: unit_policy = per_image|replicate_all_units|default_unit، (ج) UI: combo وحدة في شريط الربط + إعداد عام في نافذة V2.

### قاعدة مؤكدة من المستخدم: الوحدة تُكتب في اسم الملف حرفيًا كما وردت في الإكسل (حبه/حبة/شده/شدة/كرتون...) بدون أي توحيد إملائي أو تطبيع — التطبيع يُستخدم داخليًا للمطابقة فقط، أما الإخراج فحرفي 100%.

### متطلبات تسمية إضافية مؤكدة:
1. زر "تطبيق التسمية على الكل": قالب تنسيق موحد (code_seq_unit) يُعتمد بنقرة واحدة على جميع الصور/الوحدات دفعة واحدة، مع استثناء يدوي لاحق لأي صورة.
2. التعديل المستقبلي دائم: تعديل مسمى أي صورة في أي وقت — داخل الجلسة قبل/بعد الحفظ، وعلى الملفات المنجزة على القرص عبر أداة إعادة التسمية الخارجية (فردي وجماعي).

## حالة المرحلة 6 (تحديث ما قبل الضغط الثاني)
تم إنجاز: (1) catalog_index_v2.py محدّث بالكامل — detect_columns مرن لأي إكسل مستقبلي (رؤوس عربية/إنجليزية أو ملف بلا رؤوس)، by_code_all + units_for_code (نص حرفي) + rows_for_code + إصلاح code .0. (2) السموك تيست ناجح EXIT=0. (3) v2_ui.py يحوي capture/save/restore + autosave.

المتبقي في المرحلة 6:
1. **مشكلة استعادة الموضع** في test_session_ui: currentRow=0 بدل 3 رغم استدعاء _populate_results(restore_position=("PHOTO-004.jpg",3,0)). UserRole values صحيحة. يجب تشخيص: هل _apply_result_filters (يُستدعى داخل _populate_results قبل الاستعادة) يمسح التحديد ثم selection.setCurrentIndex في _restore_results_position لا يحدّث currentRow بسبب blockSignals؟ لاحظ: selectionModel().currentIndex().row() أيضًا 0. جرّب: results_table.setCurrentCell(3,0) مباشرة بعد _populate_results في v2_restore_session كحل مضمون.
2. **naming_v2.py**: إضافة unit_policy (per_image|replicate_all_units|default_unit) + قالب جماعي apply-to-all + دوال توليد أسماء لكل الوحدات replicate. الوحدة حرفية من الإكسل.
3. **UI للوحدات**: combo وحدة في NutritionDialog غير مطلوب — بل في شريط الربط/نافذة التسمية؛ + زر "تطبيق التسمية على الكل" بقالب موحد؛ + إمكانية تعديل المسمى لاحقًا (custom_stem في ImageState + أداة BulkRename موجودة).
4. اختبار شامل (مرحلة 7)، ثم بناء exe setup على ويندوز (مرحلة 8) — راجع قسم البناء أدناه إن وجد، وإلا: البناء عبر PyInstaller + Inno Setup في Wine أو GitHub Actions (المشروع الأصلي يحوي build scripts في app_v2/build أو windows_app — تحقق من vendor/ وbuild_installer).
- ملفات المشروع: /home/ubuntu/v2_project/app_v2 (windows_app/native_app.py الأصلي 1.2.1 + native_app_v2.py wrapper + v2_ui.py؛ src/engine_v2/*).
- ملف الإكسل: "/home/ubuntu/upload/الملفالنهائياصنافالمتجر.xlsx" (اسم يحوي محارف تالفة — استخدم glob /home/ubuntu/upload/*.xlsx). أعمدته: رقم الصنف، اسم الصنف، الوحده، حجم العبوه، الباركود (بالترتيب 0-4).
- نموذج القص: models_v2/isnet-general-use.onnx (43MB) يجب تضمينه في الحزمة.

## حالة المرحلة 6 (تحديث 3)
منجز حديثًا:
- naming_v2.py في app_v2/src/engine_v2: أُضيف NamingSettings (unit_policy: per_image|replicate_all_units|default_unit + default_unit + template قابل للتخصيص "{item}_{seq}_{unit}" مع حذف seq للصورة الأولى) + plan_names_for_item + apply_template_to_all (تطبيق على الكل بنقرة واحدة). مختبر ويعمل.
- catalog_index_v2.py: detect_columns مرن؛ أُصلح كشف عمود الوحدة (أضيف itm_unt/unt للـ hints — رأس الملف الحقيقي: I_CODE, I_NAME, Table5.ITM_UNT, Table5.P_SIZE, Table5.BARCODE). **يجب إعادة اختبار diag_units.py وحذف كاش .catalog_cache.json القديم إن وجد**.
- الملف الحقيقي: 41,935 صنفًا، 12,954 كود متعدد الصفوف (وحدات متعددة: حبه/باكت/كرتون...). الوحدات حرفية.
- ملاحظة تشخيص جلسات معلقة: currentRow=0 بدل 3 — الحل المقترح: في v2_restore_session استدعاء setCurrentCell(row,0) مؤجلًا بـ QTimer.singleShot(50) بعد processEvents، أو تمرير fallback عبر selectRow بعد اكتمال populate. (غير حاجز — الوظيفة الأساسية تعمل).

المتبقي:
1. إعادة اختبار diag_units + test الوحدات بعد إصلاح hint.
2. إصلاح استعادة موضع الجلسة (setCurrentCell مؤجل في v2_ui.py::v2_restore_session).
3. UI: combo وحدة عند الربط عندما يكون الصنف متعدد الوحدات + إعداد عام unit_policy + زر "تطبيق التسمية على الكل" + تعديل المسمى المستقبلي (BulkRenameDialog موجود).
4. مرحلة 7: اختبار شامل. مرحلة 8: بناء exe (PyInstaller+NSIS عبر GitHub Actions windows أو Wine؛ installer_v121.nsi في app_v2/build/windows).

## حالة المرحلة 6 (تحديث 4 — إصلاح الجلسات)
- الوحدات مكتملة ومختبرة (test_units.py PASS): 41,935 صنفًا، 10,528 كودًا بوحدات متعددة (حبه/كرتون/شدة/شوال/باكت/درزن/جالون... حرفية). naming_v2 NamingSettings + plan_names_for_item + apply_template_to_all تعمل.
- catalog_index_v2 detect_columns أصلح (itm_unt hint) — يكشف I_CODE/I_NAME/Table5.ITM_UNT/P_SIZE/BARCODE بنجاح.
- **درس Qt مؤكد (diag_qt_select.py)**: على جدول غير مرئي selectRow() لا يغيّر currentRow، بينما setCurrentCell وselectionModel().setCurrentIndex(ClearAndSelect|Rows) يعملان. أصلحت v2_ui.py::_reselect لاستخدام selectionModel، وtest_session_ui.py يستخدم setCurrentCell(3,0) قبل الحفظ.
- الاختبار التالي: `python3 test_session_ui.py` — إن نجح: rows=5 current_row=3 → SESSION SAVE/RESUME TEST PASSED، ثم سموك تيست نهائي، ثم UI الوحدات (combo وحدة + زر تطبيق التسمية على الكل في نافذة/شريط الربط عبر v2_ui.py)، ثم مرحلة 7 (اختبار شامل) و8 (بناء exe).
- سكربتات تشخيص: diag_units.py، diag_session_row.py، diag_qt_select.py، test_units.py.

## متطلب جديد (مؤكد من المستخدم): مطابقة إعادة التسمية مع الإكسل
أداة إعادة التسمية BulkRenameDialog يجب أن تتحقق من كل اسم جديد مقابل ملف الإكسل (رقم الصنف موجود + الوحدة صحيحة حرفيًا)، مع معاينة حالة لكل ملف (مطابق/غير موجود/وحدة خاطئة) وتصحيح مقترح، ويسري ذلك على الملفات القديمة المنجزة سابقًا أيضًا.

## حالة المرحلة 6 (تحديث 5)
منجز: (1) اختبار الجلسات نجح PASS (current_row=3 بعد الاستعادة — الحل: selectionModel().setCurrentIndex في _reselect المؤجل بـ QTimer). (2) UnitNamingDialog أُضيفت في نهاية v2_ui.py (سياسة الوحدات per_image/replicate/default + قالب {item}_{seq}_{unit} + معاينة + تطبيق على الكل + حفظ في naming_settings.json تحت v2_data_root) وربطت عبر _install_unit_naming ضمن install_v2، وزر "سياسة التسمية" (v2NamingBtn) أُضيف للهيدر في native_app_v2.py. (3) BulkRenameDialog وسّعت: حقل اختيار ملف إكسل + عمود "مطابقة الإكسل" يتحقق من كل اسم (parse_name → code + unit حرفية) مقابل units_for_code، حالات: مطابق ✓ / الصنف غير موجود / وحدة غير مطابقة مع عرض المتاح / بلا وحدة، والملفات غير المطابقة تُعلّم excel_mismatch.
ملاحظة تحقق مطلوبة: التأكد أن parse_name في naming_v2 يعيد dict فيه item وunit (وليس كائنًا) — إن كان كائنًا يجب توفيق _validate_against_excel.
المتبقي: سموك تيست كامل (كان timeout عند 180s — استخدم timeout 420)، ثم مرحلة 7 اختبار شامل، مرحلة 8 بناء setup.exe (PyInstaller + NSIS installer_v121.nsi في app_v2/build/windows — الطريقة السابقة كانت عبر GitHub Actions windows runner أو wine)، مرحلة 9 التسليم.
أوامر مفيدة: السموك: cd app_v2/windows_app && QT_QPA_PLATFORM=offscreen python3 native_app_v2.py --gui-smoke-test /tmp/smoke_v2.json

## متطلب جديد: محرر احترافي شامل (قديم + جديد)
- كل خيارات التحرير متاحة للملفات الجديدة والمنتجة والقديمة (فتح مجلد قديم وتعديل صوره مباشرة).
- اقتصاص يدوي حر بمقابض + معاينة real-time قبل/بعد + إمكانية تعديل الاقتصاص لاحقًا (غير نهائي).
- فرشاة ضبط الحواف يدويًا باللون الأبيض (مسح بقايا/استعادة) + تنعيم حواف قابل للتحكم.
- منزلقات تحسين (إضاءة/تباين/حدة/تشبع/ضوضاء) بمعاينة لحظية + زر تحسين تلقائي.
- خطة التنفيذ: إضافة V2PhotoEditorDialog في v2_ui.py يعمل على أي ملف صورة (يفتح من نتائج الجلسة أو من مجلد قديم عبر زر "تحرير صورة خارجية")، يستخدم engine_v2 (segmentation/enhancement) مع طبقات alpha قابلة للتعديل.

## متطلب تفاعل المحرر (مؤكد)
قلم/فرشاة تبييض الخلفية وضبط الحواف بحجم متغير؛ zoom بعجلة الماوس نحو المؤشر؛ pan بالسحب في كل الاتجاهات؛ معاينة لحظية أثناء الرسم. يُنفذ في V2PhotoEditorDialog (QGraphicsView مع ScrollHandDrag + wheelEvent مخصص + Brush على قناة alpha/لون أبيض).

## حالة + متطلب جديد (محرر متاجر احترافي)
- السموك تيست الكامل نجح PASS بالوسيط الصحيح: `--gui-smoke-test-output /tmp/smoke_v2.json` (وليس --gui-smoke-test). النتيجة: gui_test_passed=true، version=2.0.0، كل الفحوصات true.
- اختبار مطابقة الإكسل في أداة إعادة التسمية نجح: 991 ملفًا قديمًا، 986 مطابق، 5 كُشفت وحدة خاطئة (حبه بدل باكت) مع عرض المتاح. RenamePlanEntry حقوله: source/target/status. parse_name يعيد ParsedName(item,seq,unit).
- متطلب المحرر الجديد: قسمان منفصلان بنفس النافذة — أدوات ذكية (إزالة خلفية تلقائية، تحسين بنقرة، توسيط/تأطير تلقائي) وأدوات يدوية (قلم تبييض بحجم متغير، اقتصاص حر بمقابض، ضبط حواف، منزلقات إضاءة/تباين/حدة/تشبع/ضوضاء) + **ظل واقعي للمنتج قريب من 3D** (contact/drop shadow قابل للتخصيص: اتجاه، شفافية، ضبابية، إزاحة). يعمل على الملفات الجديدة والمنتجة والقديمة (زر فتح صورة خارجية).
- zoom بعجلة الماوس نحو المؤشر + pan بالسحب بكل الاتجاهات + معاينة لحظية قبل/بعد.
- الخطة: V2PhotoEditorDialog في v2_ui.py + shadow_v2.py في engine_v2 (توليد ظل من قناع alpha: إسقاط عمودي مُمال + Gaussian blur + تدرج شفافية). ثم إعادة السموك تيست، ثم البناء النهائي setup.exe عبر GitHub Actions (كما في 1.2.1) أو PyInstaller+NSIS.
- بناء 1.2.1 السابق: app_v2/build/windows فيه installer NSIS وسكربتات — يجب فحصها عند مرحلة البناء.

## حالة إعادة البناء بعد sandbox reset الثاني (مهم جدًا)
البيئة أعيد ضبطها أثناء test_batch_refine.py (OOM). ما استُعيد تلقائيًا: v2_ui.py, native_app_v2.py, photo_editor_v2.py, batch_refine_v2.py, shadow_v2.py, ملفات الاختبار، notes/. ما فُقد وأعيد بناؤه يدويًا:
- استعيد من zip: app_v2/src/smart_catalog_vision (pyc) + windows_app/native_app.py + assets + build/ + resources/ (فيها u2net.onnx).
- نزّل من جديد: models_v2/isnet-general-use.onnx (178MB من rembg releases).
- حزم مثبتة: numpy 1.26.4, opencv-headless, onnxruntime, openpyxl, pillow, PySide6, arabic_reshaper, python-bidi, pytesseract + tesseract-ocr 5.3.4 (ara/eng عبر apt بعد apt-get update).
- أعيد بناء (كتابة جديدة حسب مواصفات notes): segmentation_v2.py (ISNet 1024 + snap+keep_components+remove_faint_debris+decontaminate)، enhancement_v2.py (auto_enhance+EnhanceSettings+enhance_nutrition_label+descreen FFT)، naming_v2.py (كامل: build/parse/legacy/unmojibake/plan+apply_bulk_rename/NamingSettings/plan_names_for_item/apply_template_to_all)، catalog_index_v2.py (detect_columns مرن+كاش+by_code_all+units_for_code+search_name n-gram+lookup_barcode)، session_v2.py (SessionStore/SessionState upsert_image/set_position/list_sessions).
- **لم يُعد بناؤه بعد**: processor_v2.py (ProcessorV2/ProcessOptionsV2/ProcessResultV2 — الحقول موثقة أعلاه)، alignment_v2.py (estimate_tilt_degrees/rotate_with_alpha/perspective_rectify)، nutrition_v2.py (InsetPlacement/merge_label_inset/render_standalone_label/detect_nutrition_table/crop_region)، nutrition_ocr_v2.py (FIELD_SPECS/NutritionData/NutritionRow/extract_nutrition_data/blank_template/FOOTNOTE_AR)، nutrition_render_v2.py (render_nutrition_table عربي — يحتاج خطوط NotoNaskhArabic في src/engine_v2/assets/)، integration_v2.py (activate/set_override/clear_overrides يرقع FinalImageProcessor.process).
- الصور القديمة (993 webp) فُقدت — لا يوجد SmartCatalogVision-Results zip في upload الآن! upload يحوي فقط: FULL-PROJECT.zip + Setup exe + xlsx. **بديل للاختبار الجماعي**: توليد عينات من صور upload القديمة غير موجودة أيضًا (صور JPEG اختفت من upload). يجب الاختبار بصور اصطناعية أو طلب إعادة رفع لاحقًا — الأولوية: الأدوات تعمل.
- خطوط عربية: يجب تنزيل NotoNaskhArabic-Regular/Bold إلى app_v2/src/engine_v2/assets/ (رموز: استخدم ٪ U+066A و٭ U+066D).
- ذاكرة: احرص على تقليل التوازي في batch_refine افتراضيًا (workers=2-3) واستخدام إدخال ISNet 1024 يستهلك كثيرًا — خفض إلى 768 قد يلزم إن تكرر OOM. السموك تيست: cd app_v2/windows_app && QT_QPA_PLATFORM=offscreen python3 native_app_v2.py --gui-smoke-test-output /tmp/smoke_v2.json

## إعادة البناء اكتملت — test_engine_rebuild.py: 26/26 PASS (13s)
كل الوحدات أعيد بناؤها وتعمل: segmentation (ISNet conf=1.0)، enhancement، naming (canonical+legacy+bulk)، catalog (41935 صفًا، كاش 1.0s، أعمدة 0-4)، sessions، alignment، nutrition render+OCR (conf=0.9)+inset، processor كامل مع ظل soft_ground (مفاتيح SHADOW_PRESETS عربية: 'بدون ظل','ظل أرضي ناعم','ظل أرضي قوي','ظل مسقط يمين','ظل مسقط يسار','ظل استوديو 3D')، integration، build_output_stem. ملاحظة: shadow_preset في ProcessOptionsV2 يجب أن يكون بالمفتاح العربي.
التالي: ضبط batch_refine_v2 workers للذاكرة، سموك تيست الواجهة، test_batch_refine بعينات اصطناعية (الصور القديمة 993 فُقدت)، ثم مرحلة الاختبار الشامل والبناء.

## حالة المرحلة 2 (أداة الضبط الجماعي) — تشخيص فشل الاختبار
test_batch_refine.py: المعالجة نفسها نجحت 18/18 done، 0 خطأ، 1.06s/صورة، الاستئناف skipped=18/18، الأبعاد 700×800، تصحيح الوحدات من الإكسل يعمل (حبه←كيس، باكتوو←كرتون). سبب FAIL الوحيد: الاختبار يتوقع len(done)==len(files)==24 لكن العينة أنتجت 18 ملفًا فقط لأن idx.rows[50:62] فيها أكواد مكررة (صفوف متعددة الوحدات لنفس الكود) فكتبت الملفات فوق بعضها. الإصلاح: استخدام أكواد فريدة dict.fromkeys أو مقارنة done مع عدد ملفات SAMPLE_DIR الفعلي (18). ملاحظة مهمة: توقيع apply_shadow هو apply_shadow(rgba, opts, pad_bottom) وSHADOW_PRESETS مفاتيحها عربية — تم إصلاح الاستدعاء في batch_refine_v2 وprocessor_v2 (يستخدم apply_shadow_on_white). workers الافتراضي خُفض إلى 2-3 لتفادي OOM.

## متطلب جديد كبير: منظومة ترخيص واشتراك خاصة بالمالك (المرحلة 3 من الخطة المحدثة)
المستخدم طلب: "أفضل خاصية اشتراك للبرنامج خاصة بي أنا، متغيرة ولا يعرفها إلا أنا، غير قابلة للاختراق بأحدث الطرق". التصميم المعتمد:
- license_v2.py في engine_v2: Ed25519 signing (مكتبة cryptography أو pynacl؛ إن تعذر التضمين استخدم HMAC-SHA256 بسر مشتق) + TOTP (رمز دوري كل 30 ثانية من سر خاص بالمالك، RFC 6238، pyotp أو تنفيذ يدوي hmac+struct بلا تبعيات) + بصمة جهاز (MachineGuid من HKLM\SOFTWARE\Microsoft\Cryptography + اسم المستخدم + المعالج، هاش SHA256) + ملف ترخيص مشفر AES-GCM (مفتاح مشتق PBKDF2 من سر المالك+بصمة الجهاز) + حماية ضد إرجاع الساعة (تخزين آخر timestamp مشفر) + قفل بعد محاولات فاشلة.
- أداة توليد منفصلة للمالك: owner_license_tool.py (سكربت/نافذة) يولّد QR/سر TOTP + ملفات ترخيص موقعة بمدة صلاحية (شهر/سنة/دائم).
- الواجهة: نافذة تفعيل عند الإقلاع إن لم يوجد ترخيص صالح؛ إدخال رمز TOTP الحالي من تطبيق Authenticator (Google Authenticator) أو مفتاح تفعيل موقّع؛ شاشة حالة الاشتراك في الهيدر.
- شرح كامل للمستخدم في التسليم: كيفية توليد المفاتيح، تفعيل جهاز جديد، تجديد/إيقاف اشتراك.
- يجب تضمين أي تبعيات (cryptography) في PyInstaller build.

## تذكير خطة البناء (مرحلة 5)
Setup.exe عبر PyInstaller + NSIS (app_v2/build/windows/installer_v121.nsi يجب تحديثه لـ2.0.0 وأصول جديدة: isnet model 178MB، tesseract portable + tessdata ara/eng، خطوط Noto، engine_v2). البناء يتطلب Windows: الخيار الأساسي GitHub Actions windows runner (كما بُني 1.2.1)، بديل Wine.

## تأكيد متطلب الترخيص (رسالة المستخدم الأخيرة)
"عند البناء ضع لي صلاحية أنا فقط بتوثيق الأجهزة التي أريدها أنا فقط واشرحها لي" — إذن نموذج device-authorization إلزامي: البرنامج يعرض بصمة الجهاز، المالك يولد مفتاح تفعيل موقّع Ed25519 مرتبطًا بالبصمة عبر أداة مالك سرية منفصلة (لا توزع مع Setup.exe)، مع إمكانية إلغاء جهاز، وشرح كامل بالعربية عند التسليم.

## المرحلة 3 مكتملة الوحدة: license_v2.py — test_license.py 14/14 PASS
- الصيغة: SCV2.<b64url payload>.<b64url sig> (فاصل نقطة وليس شرطة لأن base64url يحوي "-").
- activate_with_key(key, pub) / check_license(pub) / deactivate() / revoke_license_id(lid).
- machine_fingerprint() => XXXX-XXXX-XXXX-XXXX (19 حرفًا).
- totp_now/totp_verify/generate_totp_secret/totp_provisioning_uri — متوافق RFC6238 وGoogle Authenticator.
- OWNER_PUBLIC_KEY_B64 placeholder "REPLACED_AT_KEYGEN" — قبل البناء: شغّل owner_tool/owner_license_tool.py init واغرس المفتاح العام في license_v2.py.
- أداة المالك: /home/ubuntu/v2_project/owner_tool/owner_license_tool.py (init/issue/totp/qr/devices/revoke) + owner_secrets.json (سرية، لا توزع).
المتبقي للمرحلة 3: نافذة تفعيل في الواجهة عند الإقلاع (تعرض البصمة + حقل مفتاح) + شارة حالة الاشتراك في الهيدر + لوحة مالك بTOTP (عرض الحالة/إلغاء الترخيص). ثم مرحلة 4 اختبارات شاملة.

## متطلب جديد: اتفاقية مستخدم نهائي (EULA) قبل التثبيت
- تُعرض في NSIS Setup (صفحة ترخيص إلزامية، زر أوافق) وداخل نافذة التفعيل عند أول تشغيل.
- متوافقة مع أنظمة المملكة (نظام التجارة الإلكترونية) والأعراف العالمية.
- بنود إلزامية: عدم استرداد أي مبلغ نهائيًا بعد الدفع وتسليم مفتاح التفعيل مهما كانت الأسباب (منتج رقمي يُستهلك بالتسليم)؛ مدة الاشتراك وصلاحيته يحددها المالك وحده عبر مفتاح التفعيل؛ الترخيص مرتبط بجهاز واحد؛ يحق للمالك إلغاء الترخيص عند مخالفة الشروط.
- بيانات التواصل للاشتراك/التجديد: ahmadjookr06@gmail.com — جوال 0582381000.
- الملفات: app_v2/build/windows/EULA_ar.rtf (للمثبت NSIS MUI_PAGE_LICENSE) + عرض نصي في ActivationDialog (license_ui.py) مع زر "أوافق على الاتفاقية" قبل أول تفعيل.

## متطلب جديد: صلاحيات المالك المتنقلة (رسالة المستخدم الأخيرة)
"خاصية التعديل أنا وحدي بخواص واشرحها لي حتى لو غيرت جهازي وفي أي مكان" — التنفيذ:
- OwnerPanelDialog (license_ui.py موجودة) تُفتح برمز TOTP فقط (هوية متنقلة عبر Google Authenticator على جوال المالك — تعمل على أي جهاز).
- توسيع اللوحة بخصائص مالك: تحرير الإعدادات المقفلة (مسارات، أبعاد الإخراج، جودة WebP)، تمديد الترخيص محليًا (بإصدار مفتاح، لا تعديل مباشر)، إلغاء ترخيص الجهاز، عرض بصمة/حالة، فتح أدوات مخفية (أداة الدفعة بلا قيود). المالك على جهاز جديد: يفعّل بمفتاح تفعيل يولده من owner_license_tool على أي حاسب لديه owner_secrets.json + يدخل لوحة المالك بTOTP.
- الشرح الكامل في دليل التسليم OWNER_GUIDE.md.

## حالة الملفات الآن (بعد المرحلة 3 جزئيًا)
- license_v2.py مكتمل ومختبر 14/14 (test_license.py). أداة المالك owner_tool/owner_license_tool.py جاهزة (init/issue/totp/qr/devices/revoke).
- license_ui.py أُنشئ: ActivationDialog (بصمة+مفتاح)، OwnerPanelDialog (TOTP، إلغاء)، ensure_activated()، install_license_badge(). placeholders: OWNER_TOTP_SECRET وOWNER_PUBLIC_KEY_B64 = "REPLACED_AT_KEYGEN" تُغرس قبل البناء.
- المتبقي: EULA (نافذة موافقة أول تشغيل + ملف للمثبت)، ربط ensure_activated+badge+owner btn في native_app_v2.main()، BatchRefineDialog غير موجودة في v2_ui.py بعد (native_app_v2 يستدعيها!) — يجب إنشاؤها، توسيع OwnerPanel بالخصائص، ثم مرحلة 4 اختبارات شاملة فمرحلة 5 بناء Setup.exe (PyInstaller+NSIS عبر GitHub Actions windows runner كما 1.2.1) فمرحلة 6 تسليم مع OWNER_GUIDE وEULA وشرح الاشتراك.
- بيانات التواصل في EULA ونافذة التفعيل: ahmadjookr06@gmail.com — 0582381000.

## متطلب جديد: دليل النشر الشامل (PUBLISHING_GUIDE.md) يُسلم في النهاية
- شرح النشر على: Microsoft Store (حساب مطور، MSIX)، توزيع مباشر، Code Signing (شهادة OV/EV، SmartScreen)، اشتراطات السعودية (سجل تجاري إلكتروني، منصة معروف، ضريبة القيمة المضافة على المنتجات الرقمية)، حماية العلامة التجارية، وخيارات مستقبلية (تحديثات تلقائية، موقع تعريفي).
- حقوق النشر باسم: احمد الفيفي.

## متطلب جديد: هوية بصرية فريدة لا تتطابق مع أحد
- اسم مميز + أيقونة حصرية مصممة (AI gen) + لوحة ألوان/خطوط مميزة + Splash + GUID فريد للتطبيق والمثبت + حقوق باسم احمد الفيفي.
- تُطبق قبل البناء النهائي (مرحلة 6).

## متطلب جديد: شفرة مالك مقاومة للكم (رسالة المستخدم)
- توقيع هجين: Ed25519 + ML-DSA/Dilithium (FIPS 204) — لا يقبل مفتاح التفعيل إلا بصحة التوقيعين معًا.
- تسليم "شفرة المالك": owner_secrets.json (مفاتيح خاصة + TOTP) + أداة الإصدار + دليل إصدار ترخيص بعد الدفع.

## PQC مكتمل: test_license_pqc.py 6/6 PASS
- ML-DSA-65 (dilithium-py) توقيع هجين إلزامي مع Ed25519. المفتاح الهجين ~4650 حرفًا (يُلصق في QTextEdit).
- أداة المالك تولّد وتوقّع بالاثنين تلقائيًا. backward compat عند عدم غرس PQC.
- ملاحظة بناء: يجب تضمين dilithium_py في PyInstaller hiddenimports.

## حالة المرحلة 4 (تدقيق أمني) — جارية
- الملفات المنجزة حتى الآن: license_v2.py (Ed25519+ML-DSA65+TOTP+AES-GCM+clock guard) مختبر 14/14 و6/6 PQC؛ license_ui.py (EULA+ActivationDialog+OwnerPanel+OwnerSettings+badge) مختبر 14/14؛ native_app_v2.py مربوط (بوابة _gate_startup + badge + أزرار: rename/sessions/naming/editor/refine)؛ v2_ui.py يحوي BatchRefineDialog كاملة (خيط خلفي، workers من إعدادات المالك، ظل 6 أنماط)؛ owner_tool/owner_license_tool.py (init/issue مع PQC/totp/qr/devices/revoke).
- test_security_audit.py أُنشئ: A1-A6 تجاوز الترخيص، B1-B7 مدخلات خبيثة، C1-C6 ملفات/إكسل/صور تالفة.
- حد معروف موثق: حذف revoked.dat محليًا يعيد ترخيصًا ملغى غير منتهي — الدفاع: عدم إصدار مفاتيح جديدة (يوثق في OWNER_GUIDE).
- التالي: تشغيل التدقيق، إصلاحات، ثم مرحلة 5 (سموك تيست شامل بالواجهة xvfb + لقطات) فمرحلة 6 (البناء: غرس المفاتيح بأداة inject قبل PyInstaller، dilithium_py hiddenimport، EULA في NSIS) فمرحلة 7 تسليم (Setup.exe + owner_secrets + OWNER_GUIDE.md + PUBLISHING_GUIDE.md + هوية بصرية فريدة GUID).

## متطلب جديد: تسجيل الحقوق والحماية من التقليد
- لا صلاحية للتسجيل نيابة عن المستخدم — بدلًا منه: (أ) تجهيز البرنامج مؤهلًا للتسجيل (هوية فريدة، GUID، إشعار حقوق باسم احمد الفيفي في كل ملف/نافذة حول/EULA)، (ب) قسم في PUBLISHING_GUIDE.md: خطوات تسجيل مصنف رقمي لدى SAIP السعودية + WIPO دوليًا + علامة تجارية.

## مرحلة 4 مكتملة: تدقيق أمني 21/21 PASS + engine rebuild 26/26 PASS
- سُدت ثغرتا naming (sanitize_item ضد traversal/طول). excel_cache أُصلح شرط اختباره (كاش 0.96s ضد 3.9s).
- مرحلة 5 الآن: سموك تيست شامل واجهة headless/xvfb + لقطات لكل النوافذ (رئيسية/محرر/دفعة/تغذية/تسمية/جلسات/تفعيل/EULA/مالك) + معالجة عينات حقيقية end-to-end.

## مرحلة 5: سموك تيست شامل 24/24 PASS + لقطات
- test_full_ui_smoke.py: إقلاع كامل ببوابة ترخيص مفعلة، شارة اشتراك، 5 أزرار هيدر، محرر (فتح/ذكي/دمج)، دفعة، تغذية، تسمية، جلسات، EULA، تفعيل، مالك، إعدادات مالك.
- أصلح: NutritionDialog._mode_changed حماية hasattr. لقطة 01_main و02_editor نظيفتان RTL بلا تداخل.
- ملاحظة: زر "فتح صورة" في المحرر معطل النص "...فتح صورة" — نص عادي مقبول. قِيَم editor: معالجة ذكية اكتملت (52% زوم، فرش يمين، ذكي يسار).

## ملخص شامل — حالة المشروع قبل مرحلة 6 (البناء)
### الاختبارات المكتملة بنجاح:
- test_engine_rebuild.py: 26/26 PASS (seg/enhance/naming/catalog/session/align/nutrition/processor/shadow/integration)
- test_license.py: 14/14 PASS (Ed25519+AES-GCM+TOTP+clock guard+revoke)
- test_license_pqc.py: 6/6 PASS (ML-DSA-65 هجين مقاوم للكم)
- test_license_ui.py: 14/14 PASS (EULA/activation/badge/owner panel/settings/ensure_activated)
- test_security_audit.py: 21/21 PASS (تجاوز/تلاعب/مدخلات خبيثة/ملفات تالفة)
- test_full_ui_smoke.py: 24/24 PASS (إقلاع كامل+كل النوافذ+لقطات)

### بنية الملفات الرئيسية:
- app_v2/src/engine_v2/: segmentation_v2, enhancement_v2, naming_v2, catalog_index_v2, session_v2, alignment_v2, nutrition_ocr_v2, nutrition_v2, nutrition_render_v2, processor_v2, shadow_v2, batch_refine_v2, license_v2, integration_v2
- app_v2/windows_app/: native_app_v2.py (إقلاع+بوابة+patch), v2_ui.py (NutritionDialog+BulkRenameDialog+SessionDialog+BatchRefineDialog), photo_editor_v2.py (V2PhotoEditorDialog 3 أوضاع), license_ui.py (EulaDialog+ActivationDialog+OwnerPanelDialog+OwnerSettingsDialog+badge)
- app_v2/build/windows/EULA_ar.txt
- owner_tool/owner_license_tool.py (init/issue/totp/qr/devices/revoke مع PQC)
- models_v2/isnet_general_use.onnx (44MB)

### المتطلبات المتبقية (مرحلة 6+7):
1. بناء Setup.exe: PyInstaller spec (hiddenimports: dilithium_py, PySide6, cv2, onnxruntime, openpyxl, cryptography) + NSIS installer مع EULA + أيقونة حصرية + GUID فريد
2. غرس مفاتيح المالك: أداة inject تستبدل OWNER_PUBLIC_KEY_B64 وOWNER_PQC_PUBLIC_KEY_B64 وOWNER_TOTP_SECRET في license_v2.py وlicense_ui.py قبل البناء
3. هوية بصرية فريدة: أيقونة مصممة AI + splash + ألوان
4. تسليم: Setup.exe + owner_tool/ + owner_secrets.json (يولّد عند init) + OWNER_GUIDE.md + PUBLISHING_GUIDE.md (نشر+حقوق SAIP/WIPO) + requirements.txt + الشيفرة المصدرية كاملة
5. ملاحظة تفضيل المستخدم: يريد الشيفرة المصدرية الكاملة وكل الملفات بدلًا من exe فقط.

## مرحلة 6 — تقدم
- GitHub connector مفعل (حساب ahmad121232414-collab، لا ريبوهات — سننشئ ريبو خاص جديد).
- owner_secrets.json وُلّد (ed25519_private/public, mldsa65_private/public, totp_secret=4SNK2JSJGACRJAVP33ONHUBNI5N6D6RR).
- inject_keys.py نفذ: غرس OWNER_PUBLIC_KEY_B64+OWNER_PQC_PUBLIC_KEY_B64 في license_v2.py وOWNER_TOTP_SECRET في license_ui.py. اختبار end-to-end بالمفاتيح المغروسة PASS.
- التالي: أيقونة حصرية + version_info 2.0.0 + spec جديد (entry native_app_v2.py, isnet, dilithium_py, engine_v2, tesseract, خطوط) + NSIS مع صفحة EULA عربية + GitHub Actions workflow windows.

## متطلب جديد (قبل البناء): الوضع الحر بلا إكسل
- البرنامج يجب أن يعمل على أي صورة بأي مسمى دون الحاجة لملف الإكسل إطلاقًا.
- المحرر: حفظ باسم حر يكتبه المستخدم (أو اقتراح من الإكسل اختياريًا إن وجد).
- أداة الضبط الجماعي: تعمل بلا إكسل — تحافظ على الأسماء الأصلية؛ تصحيح الأسماء من الإكسل يبقى خيارًا.
- الواجهة الرئيسية: عدم إجبار اختيار الإكسل للمعالجة الحرة.

## حالة مرحلة البناء (تحديث مهم — قبل ضغط السياق)
### ما أُنجز في مرحلة 6 حتى الآن:
1. GitHub connector مفعل (ahmad121232414-collab، لا ريبوهات). البناء سيتم عبر ريبو خاص جديد + GitHub Actions windows runner.
2. owner_secrets.json ولّد في owner_tool/ (ed25519_private/public، mldsa65_private/public، totp_secret=4SNK2JSJGACRJAVP33ONHUBNI5N6D6RR).
3. inject_keys.py أنشئ ونُفذ: غرس المفاتيح العامة في license_v2.py وOWNER_TOTP_SECRET في license_ui.py. اختبار end-to-end PASS.
4. أيقونة حصرية جديدة ولدت: app_icon_v2.png → استبدلت app_icon.png/ico (multi-size) عبر make_icon.py.
5. version_info.txt حُدث إلى 2.0.0.
6. نموذج ISNet نسخ إلى app_v2/src/engine_v2/models/isnet-general-use.onnx (178MB).
7. paths_v2.py أنشئ في engine_v2: models_dir() وassets_dir() موحدة تدعم MEIPASS/frozen/dev.
8. photo_editor_v2._segmenter وv2_ui BatchRefine _start وintegration_v2._default_model_dir وnutrition_render_v2._find_font حُدثت لاستخدام paths_v2.
9. nutrition_ocr_v2: _configure_tesseract() أضيفت — تبحث عن tesseract.exe في MEIPASS/tesseract وexe_dir/tesseract وProgram Files/Tesseract-OCR.
10. test_engine_rebuild.py أعيد تشغيله بعد التعديلات: 26/26 PASS.

### متطلبات جديدة من المستخدم (يجب تنفيذها):
- الوضع الحر: البرنامج يستقبل أي صور بأي مسميات وأي صيغ للتعديل/العزل، بلا اشتراط إكسل. الإكسل حر الاختيار (أي ملف).
- **الأهم (تأكيد المستخدم الأخير): عدم إزالة الخاصية الأساسية إطلاقًا** — منظومة الإكسل والوحدات الحرفية (حبه/شده/كرتون) والتسلسل تبقى الوضع الأساسي كما اتفقنا. الوضع الحر خيار إضافي فقط.
- قرار التنفيذ في batch_refine_v2.py: fix_names غيّرت افتراضيًا إلى False في الوحدة لكن **الواجهة BatchRefineDialog تبقي chk_names مفعلًا افتراضيًا** (يحافظ على الأساس) — عند عدم تحديد إكسل أو إلغاء التفعيل يعمل الوضع الحر ويحفظ الاسم الأصلي كما هو. أضيف recursive option وlist_images حرة (أي مسمى، تتجاهل الملفات المخفية).
- المحرر photo_editor_v2._save: الحفظ حر بالفعل (getSaveFileName بأي اسم) — مكتمل.
- المتبقي في هذا المتطلب: تحديث نصوص BatchRefineDialog (intro + placeholder) لتوضيح أن الإكسل اختياري والوضع الحر متاح + checkbox "شمول المجلدات الفرعية" + تمرير recursive في RefineOptions من الواجهة + التأكد أن chk_names يبقى default checked.

### خطة البناء المتبقية (مرحلة 6):
1. إكمال تعديلات الوضع الحر في BatchRefineDialog (v2_ui.py).
2. سموك تيست سريع بعد التعديلات (xvfb): test_full_ui_smoke.py — 24/24 سابقًا. أوامر: cd /home/ubuntu/v2_project && xvfb-run -a -s "-screen 0 1920x1080x24" timeout 420 python3 test_full_ui_smoke.py
3. تحديث spec: app_v2/build/windows/AhmedAlFaifiMarketImageStudio.spec — entry يجب أن يصبح windows_app/native_app_v2.py، إضافة datas: engine_v2/models/isnet-general-use.onnx → engine_v2/models، engine_v2/assets/*.ttf → engine_v2/assets، EULA_ar.txt، hiddenimports: dilithium_py (collect_all)، pytesseract، arabic_reshaper، bidi. excludes تبقى (matplotlib, pandas...) لكن انتبه: catalog_index_v2 يستخدم openpyxl فقط.
4. تحديث installer NSIS: نسخ installer_v121.nsi → installer_v200.nsi، تحديث APP_VERSION 2.0.0، إضافة صفحة ترخيص MUI_PAGE_LICENSE مع EULA_ar.txt (تحويل إلى Windows-1256 أو UTF-16LE مع BOM لعرض عربي صحيح في NSIS)، تنزيل tesseract portable (يُحزم في installer أو مع PyInstaller datas)، GUID جديد فريد.
5. GitHub Actions workflow: .github/workflows/build.yml — windows-latest، خطوات: setup-python 3.12، pip install (PySide6 opencv-python-headless onnxruntime openpyxl pillow pytesseract arabic_reshaper python-bidi dilithium-py cryptography pyinstaller zxing-cpp)، تنزيل tesseract portable (UB-Mannheim installer /S أو نسخة portable من GitHub)، pyinstaller spec، makensis، upload-artifact: Setup exe. ملاحظة: نموذج ISNet 178MB أكبر من حد git العادي 100MB → استخدم Git LFS أو حمّله في الworkflow من HuggingFace: https://huggingface.co/skytnt/anime-seg/resolve/main/isnet_is.onnx غير صحيح — الصحيح: https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx
6. tessdata: ara.traineddata + eng.traineddata من https://github.com/tesseract-ocr/tessdata_fast
7. بعد البناء: تنزيل artifact، فحصه، ثم التسليم مع: owner_secrets.json + owner_license_tool.py + دليل المالك (إصدار تراخيص خطوة بخطوة + TOTP في Google Authenticator) + دليل النشر (Microsoft Store، توزيع مباشر، توقيع رقمي، SAIP تسجيل حقوق، معروف، VAT) + EULA + شرح المنظومة.

### تذكيرات التسليم (مرحلة 7):
- المستخدم يفضل تسليم كود المصدر كاملًا مع requirements.txt وليس فقط setup (تفضيل معروف مسبقًا).
- حقوق باسم: احمد الفيفي. بيانات التواصل: ahmadjookr06@gmail.com / 0582381000.
- EULA: عدم استرداد المبلغ نهائيًا، الصلاحية يحددها المالك عبر مفتاح التفعيل.

## متطلب: جميع الاحتمالات في الخيارات (قبل البناء)
- كل نافذة يجب أن تعرض كل الخيارات الممكنة: دفعة (صيغ/إكسل اختياري/قص/تحسين/تأطير/ظل×6/فرعية/استئناف/خيوط)، محرر (3 أوضاع/فرش/حفظ webp,png,jpg باسم حر)، تسمية (كل الوحدات من الإكسل + حر)، تغذية (OCR/يدوي/دمج أو مستقل).

## اكتمل قبل البناء: وضع حر شامل
- rb_free أضيف لسياسة التسمية (unit_policy=free) مع الحفظ/التحميل. دفعة: recursive + إكسل اختياري + احتفاظ بالأسماء. المحرر: حفظ webp/png/jpg باسم حر. اختبارات: FREE MODE OK + CORE NAMING KEPT OK + سموك 24/24.
- متطلب السرعة مؤكد: قياس أداء نهائي قبل التسليم.

## حالة البناء (آخر تحديث)
- spec جديد: app_v2/build/windows/AhmedAlFaifiMarketImageStudioV2.spec — entry=native_app_v2.py، datas: isnet+u2net+fonts+EULA+pyc القديمة، collect_all: zxingcpp/onnxruntime/dilithium_py، hiddenimports كل engine_v2 + v2_ui + photo_editor_v2 + license_ui. VERSION/README/THIRD_PARTY/RELEASE_NOTES_2.0.0 أنشئت في app_v2/.
- NSIS: installer_v200.nsi أنشئ — MUI_PAGE_LICENSE مع EULA_ar.txt (يجب أن يكون UTF-16LE BOM)، GUID فريد {B7E4A9D2-5C31-4F8E-9A6B-2D7F0C4E8A15}، OutFile: dist/installer/AhmedAlFaifiMarketImageStudio-Setup-2.0.0.exe، المصدر: dist/windows/AhmedAlFaifiMarketImageStudio.
- خطوات متبقية: (1) تحويل EULA_ar.txt إلى UTF-16LE BOM (نسخة للـNSIS)؛ (2) workflow بناء GitHub Actions windows-latest: python 3.12 + pip install + تنزيل isnet من https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx (لا نرفع 178MB للريبو — استثنِ src/engine_v2/models في .gitignore) + tesseract portable + tessdata ara+eng من tessdata_fast + pyinstaller spec + makensis + artifact. (3) ريبو خاص جديد: gh repo create market-image-studio-v2 --private. (4) بعد البناء: تنزيل artifact وفحصه وربما اختبار headless. (5) قياس أداء نهائي وتسليم.
- requirements البناء على Windows: PySide6==6.8.1 opencv-python-headless numpy onnxruntime openpyxl pillow pytesseract arabic-reshaper python-bidi dilithium-py cryptography zxing-cpp pyinstaller.
- ملاحظة: native_app.py (الأصلي 1.2.1) موجود في windows_appويستورد smart_catalog_vision من pyc — pathex يشمل src. python 3.12 مطلوب لأن pyc جُمعت بـ؟ — تحقق: pyc القديمة بنيت على 3.12 في بناء 1.2.1 (GitHub Actions السابق استخدم 3.12).
- تذكير مهم: قبل الرفع للريبو لا ترفع owner_tool/owner_secrets.json أبدًا (أسرار المالك) — .gitignore.
- المستخدم شدد: صفر أخطاء + كل الاحتمالات في الخيارات + سرعة في جميع المهام + عدم إزالة خاصية الإكسل الأساسية.

## تحديث 27 يوليو — تسجيل دخول GitHub عبر Google (جارٍ)
- البناء انطلق فعلًا: المستخدم أرسل لقطة تُظهر 3 تشغيلات "Build Windows Setup 2.0.0" كلها In progress (بدأت ~00:41-00:47).
- توكن GH_TOKEN للجلسة بلا صلاحية Actions (403، يتطلب actions=read) — لا يمكن متابعة البناء/تنزيل artifacts عبر API.
- الحل الجاري: تسجيل دخول GitHub في متصفح الساندبوكس عبر "Continue with Google" بحساب ahmad121232414@gmail.com — المستخدم سيوافق من هاتفه (لا كلمة مرور).
- الحالة: صفحة Google Sign-in، أُدخل البريد، بانتظار الضغط على Next ثم تحقق الهاتف.
- بعد الدخول: فتح https://github.com/ahmad121232414-collab/market-image-studio-v2/actions ومتابعة أول تشغيل ناجح، ثم تنزيل artifact باسم Setup-2.0.0 (فيه AhmedAlFaifiMarketImageStudio-Setup-2.0.0.exe).
- بعد التنزيل: فحص الملف، تجهيز حزمة التسليم: owner_secrets.json + أداة المالك (/home/ubuntu/v2_project/owner_tool/) + دليل المالك + دليل النشر + دليل المستخدم + تقرير الاختبارات (105+).
