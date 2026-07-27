# واجهة المحرك المجمّع (smart_catalog_vision) — Python 3.12

**مهم:** وحدات المحرك `.pyc` مجمعة لـ Python 3.12 وتستورد بنجاح تحت 3.12.3 في البيئة الحالية. لا مصدر لها (فك الترجمة فشل سابقًا). الاستراتيجية: **الاحتفاظ بالمحرك كما هو والبناء فوقه بطبقة V2 جديدة (wrapper/override)** بدل تعديل الداخل.

## الوحدات والرموز
- `pipeline`: run_batch, apply_manual_links, apply_manual_link, apply_individual_image_edit, preview_individual_image_edit, BatchRunResult, BatchItemResult, IndividualImagePreview, FinalImageOptions/Processor (re-export), read_image, normalize_unit
- `final_images`: FinalImageProcessor(options, model_dir), FinalImageOptions, FinalImageJob/Result, ForegroundMethod
- `product_segmentation`: refine_product_mask(image, probability, ...), assess_product_mask, prune_thin_branches
- `imaging`: read_image, file_sha256, ImageReadError
- `normalization`: normalize_unit, safe_filename_component

## FinalImageOptions (الافتراضيات)
width=800, height=700, margin_x=48, margin_y=40, background_bgr=(255,255,255), remove_background=True, crop_to_foreground=True, enhance_for_display=True, enhancement_strength=55, enhance_lighting/color/details=True, reduce_noise=True, auto_straighten=True, foreground_method='auto', webp_quality=94

## توقيعات مهمة
- `FinalImageProcessor.process(source_path, output_dir, *, item_number, unit='حبة', product_name='', overwrite=False)`
- `run_batch(catalog_path, image_paths, workspace, *, profile_name='كتالوج المنتجات', remove_background=True, enhance_product=True, final_image_options=None, maximum_barcode_tier=3, progress=None)`
- `apply_manual_links(workspace, source_names, item_code, *, remove_background=True, enhance_product=True, final_image_options=None, progress=None)`
- `apply_individual_image_edit(workspace, source_name, *, manual_crop=None, smart_enhance=True, enhancement_strength=55, smart_crop=True, auto_straighten=True, remove_background=True, ...)`
- `preview_individual_image_edit(...)` مثلها بدون تغيير الحالة

## واجهة windows_app/native_app.py (4618 سطر، PySide6)
Classes: ImageListWidget, BatchWorker(QThread), ManualLinkWorker, IndividualEditWorker, StatCard, ZoomableImageView(QScrollArea), ImagePreviewPane, ProtectedEditDialog, MainWindow. + _self_test/_batch_self_test/_gui_smoke_test + main()

## تشخيص 1.2.1 الموروث (DIAGNOSIS_1.2.1.md)
1. ازدحام لوحة المحرر: أقسام مكدسة بلا تمرير → تبويبات + لوحة قابلة للتمرير (نُفذ جزئيًا في 1.2.1)
2. اقتصاص محوري فقط (left,top,right,bottom) → أضيف وضع رباعي منظور 4 زوايا مع warpPerspective
3. الربط اليدوي بطيء (~2s، 97% منه تجهيز الصورة) → المطلوب ربط متفائل + معالجة خلفية
4. عقود قبول: ظهور الربط ≤150ms، الاقتصاص 8 قيم (4 زوايا)

## بنية النتائج القديمة (SmartCatalogVision-Results)
مجلد `processed/` يحوي 993 ملف webp بأسماء مثل `10000958_حبه.webp`, `10007435_حبه_2.webp`, `10000906_حبه_6.webp`.
**ملاحظة حرجة:** النمط القديم هو `[رقم]_حبه_N.webp` بينما المستخدم يطلب في V2: `[رقم]_N_حبه` (الرقم التسلسلي قبل الوحدة، كما في IMG_4815: 10018435_2_حبه). أداة إعادة التسمية الخارجية يجب أن تحول من النمط القديم للأنماط الجديدة وتتعرف على كليهما.
كما توجد أسماء ملفات معطوبة الترميز (╪н╪и┘З = حبه بترميز cp437/utf8 mixup من ZIP) — الأداة يجب أن تعالج إصلاح الترميز أيضًا.

## requirements.txt (1.2.1)
PySide6==6.8.3, numpy==1.26.4, opencv-python-headless==4.11.0.86, onnxruntime==1.20.1, openpyxl==3.1.5, Pillow==11.1.0, pyzbar==0.1.9, python-barcode==0.16.1, pytest, pyinstaller==6.21.0

## موارد
- `resources/models/` نماذج U²-Net ONNX
- `build/windows/installer_v121.nsi` + إعدادات PyInstaller
- بيئة السندبوكس: Python 3.12.3 متاح (python3) — متوافق مع pyc!

## نتيجة اختبار خط الأساس (test_baseline.py)
عولجت صورة العبوة (لقطة شاشة المستخدم 3988D8E6) بالمحرك 1.2.1 في 3.33 ثانية. **المشكلة مُعاد إنتاجها بوضوح**: الناتج `baseline_out/TEST001_حبه.webp` يظهر هالة بيضاء/رمادية متعرجة حول كامل المنتج، وحواف خشنة مسننة خاصة حول الغطاء وأسفل العبوة، وبقايا خلفية ملتصقة. كما أن الصورة باهتة قليلًا (لقطة شاشة من شاشة LCD أصلًا). خصائص FinalImageResult تعيد foreground_quality_score=1.0 رغم رداءة الحواف — أي أن مقياس الجودة الداخلي متساهل جدًا.

الخلاصة التقنية لـ V2: نحتاج مسار قص جديد كليًا في طبقة V2: تشغيل U2Net full + ISNet/BiRefNet إن أمكن، ثم alpha matting حقيقي (guided filter / FBA-style)، defringe (إزالة الهالة البيضاء عبر color decontamination)، وتنعيم الحواف sub-pixel. مع بقاء fallback للمحرك القديم.

## نتيجة اختبار ISNet V2 (seg_compare/result_isnet.png)
تحسّن كبير وواضح مقارنة بخط الأساس: الحواف نظيفة وناعمة بلا هالة بيضاء متعرجة، شكل العبوة كامل والقطع دقيق حول الغطاء والجسم. زمن المعالجة ~2s على CPU. بقايا طفيفة: ظل خفيف صغير أسفل يسار العبوة وبقعة صغيرة سفلية — سيعالجها تنظيف المكونات الصغيرة وقصّ الظلال في طبقة V2 (تحسين _largest_component بعتبة أعلى للمكونات المنفصلة عن الجسم الرئيسي).
**القرار المعتمد:** ISNet general-use (171MB) هو نموذج V2 الرئيسي؛ U2Net القديم يبقى fallback. BiRefNet مستبعد (928MB + OOM على أجهزة عادية).

## نتائج اختبار ProcessorV2 (v2_out/)
1. **المنتج (10001234_حبه.webp): ممتاز** — حواف نظيفة، لا هالة، تحسين إضاءة/حدة جيد، descreen يقلل نمط الشاشة. زمن 4.7s. ملاحظة: بقعة صغيرة أسفل يسار (فتات alpha) — يلزم رفع عتبة keep_ratio في _largest_component من 0.02 إلى ~0.05 وإزالة المكونات القريبة من الحافة السفلية.
2. **حقائق التغذية المنفردة (10001043_حبه_تغذية.webp): ممتازة وواضحة جدًا** — الكشف التلقائي التقط الجدول بدقة والتحسين جعل النص مقروءًا تمامًا.
3. **الدمج المصغر: يعمل منطقيًا** لكن اختبرته على صورة الظهر نفسها (العزل على صورة جدول لا معنى له). الإدراج المصغر أسفل يسار ظهر صحيحًا بإطار. في التطبيق الفعلي: صورة الواجهة للمنتج + صورة الظهر مصدر الجدول (صورتان مختلفتان) — الواجهة سترسل مصدر التغذية المنفصل. يلزم دعم `nutrition_source_path` منفصل في ProcessorV2.

### تحسينات مطلوبة على النواة (قبل المرحلة 6)
- keep_ratio 0.05 + قص فتات الحواف
- nutrition_source_path منفصل عن صورة المنتج في merge_small/standalone
- WebP lossless مفعل (IMWRITE_WEBP_QUALITY=101) ويعمل
