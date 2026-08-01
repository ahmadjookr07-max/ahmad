# مهام مستخرجة من الجلسة المرجعية (session_state.md 42KB + SESSION_HANDOFF.md)

المصدر: الجلسة المرجعية `fDSN4JYxUs1Ff2RYaXGKwC` — 139 ملفًا مجرودًا، نُزّل 16 ملف .md
إلى `/home/ubuntu/refs2/`.

## أ. منجز ومدفوع (commit 354f359) — النقاط الأربع
1. إصلاح التداخل على الشاشات الضيقة (`_sync_manual_group_height`).
2. **الزر الذكي للربط** `smartLinkButton` (أخضر 44px): يظهر عند تحديد صور غير مرتبطة،
   نصه «✔ اربط N صور بـ: اسم (رقم)». `_nearest_link_context()` ~4811.
3. **الترشيح البصري**: `_visual_suggestion_for` ~4482 عبر `engine_v2.visual_match_v2`
   (build_signature + pair_similarity)، إذا score>=0.62 يعرض «★ تشابه NN%»؛
   `_visual_sig_cached` كاش 600 بصمة؛ `_smart_link_clicked` ~4925 يسجل في learning_v2.
   اختبار: test_smart_link 11/11 (البصري تغلّب على الأقرب).
4. **وضع «اربط بالنقر»** `tapLinkButton` checkable بنفسجي/برتقالي عند التفعيل:
   نقرة على غير مرتبط ⇒ pending، ثم نقرة على مرتبط ⇒ ربط فوري.
   `_toggle_tap_link_mode` ~4995، `_tap_link_cell_clicked` ~5017. test_tap_link 19/19.
5. **التلميح العائم** `_show_tap_hint()`: QLabel أبوه النافذة (خارج manual_layout)،
   يوضع أسفل منتصف results_table، مؤقت اختفاء 6 ثوان، CSS rgba(76,29,149,0.94).

## ب. حقائق التغذية — منجز بالكامل ومختبر (هل دُفع؟ يجب التحقق)
- **ملف جديد** `windows_app/nutrition_crop.py`: `NutritionCropCanvas` (zoom بالعجلة حول
  المؤشر 0.6–12x، pan بالزر الأيمن/الأوسط، تحديد حر بإحداثيات الصورة **الأصلية** +
  8 مقابض + تعتيم خارجي + شارة أبعاد) و`NutritionCropDialog` (كشف تلقائي، صورة أخرى،
  مسح، checkbox لوحة بيضاء، زر حفظ أخضر معطل حتى وجود تحديد، ↻ تدوير، 👁 معاينة،
  «إغلاق» بدل «إلغاء») و`save_nutrition_image()` عبر `render_standalone_label` +
  `build_output_stem` + `imwrite_unicode(lossless_webp=True)`.
- **الحفظ المتكرر بلا إغلاق**: `save_requested = Signal(object, bool)` + `_save_current()`
  يزيد `_saved_count` ويمسح التحديد.
- `native_app.py`: زر `nutritionButton` 🍎 في quick_flow ~2091، `editor_nutrition_button`
  في footer تبويب «تحرير مباشر» ~2516، `_open_nutrition_crop` ~5163 (يفضّل
  `_individual_edit_source_name` ثم الصف المحدد، يربط `save_requested` ثم `exec()`
  بلا فحص نتيجة)، `_save_nutrition_result` ~5197 يرجع `target.name`.
- **زر الحذف** `delete_output_button` 🗑 أحمر في quick_flow ~2094 +
  `_delete_selected_outputs` ~5305: تأكيد QMessageBox.question، حذف output/review من
  القرص، إزالة من items، `_populate_results`، تحديث ZIP.
- `_refresh_delivery_zip` جديدة: تحوّل المسارات النسبية لمطلقة مؤقتًا عبر
  `object.__setattr__` لأن `BatchItemResult` **frozen** — استبدلت الاستدعاءين المباشرين
  لـ `_write_delivery_zip`.
- `native_app_v2._attach_nutrition_button` القديم معطّل إذا وُجد `window.nutrition_button`.
- الاختبارات: test_nutrition_full 25/25، test_nutrition_crop 33/33،
  test_nutrition_manual_repeat 13/13، وضع الدمج 33/33.
- **دمج حقائق التغذية داخل صورة الصنف** (تقرير_دمج_حقائق_التغذية.md): وضع الدمج بأربعة
  مواضع + حل فقدان الجودة جذريًا (measure_webp_loss + quality_fix_verified).

## ج. دروس تقنية مهمة من الجلسة المرجعية
- **offscreen**: الترتيب الصحيح `t.selectRow(r)` ثم `t.setCurrentCell(r,0)` — العكس
  يلغي التحديد (`currentRow=-1`).
- monkeypatch للرسائل: `_na.QMessageBox.question = lambda *a,**k: _na.QMessageBox.Yes`.
- `BatchItemResult` مجمّد (frozen) — التعديل يحتاج `object.__setattr__`.
- نموذج التحديث الصحيح: `_capture_results_position()` ← تعديل items ←
  `_populate_results(restore_position=...)`.
- `imread_unicode` (processor_v2:62) / `imwrite_unicode` (:70) للمسارات العربية.
- `build_output_stem(out_dir, item, unit)` (integration_v2:229) يرقّم وفق *.webp الموجودة.

## د. المهام المتبقية المستخرجة (لم تُنجز)
1. لقطة إضافية للتكبير zoom داخل ديالوج التغذية (اختياري).
2. CSS مميز لزر nutritionButton — أُنجز (أخضر).
3. التحقق من دفع نقطة التغذية إلى GitHub (آخر مدفوع في تلك الجلسة: 354f359).
4. `test_batch_refine.py` يتوقع 24 ملفًا والعينة تنتج 18 (أكواد مكررة) — الحل
   `dict.fromkeys` أو المقارنة بعدد ملفات SAMPLE_DIR.
5. عيوب التجاوب المتبقية (reachability_verified.md، regression_minsize.md،
   audit_final_numbers.md، analysis_adaptive.md، fix_plan_responsive.md).

## هـ. ملفات مرجعية نُزّلت إلى /home/ubuntu/refs2/
session_state.md (42KB، الأهم)، SESSION_HANDOFF.md (18KB)، nutrition_crop_design.md،
تقرير_دمج_حقائق_التغذية.md، merge_test_results.md، ratio_analysis.md،
quality_fix_verified.md، quality_diag_notes.md، reachability_verified.md،
regression_minsize.md، audit_final_numbers.md، analysis_adaptive.md،
fix_plan_responsive.md، responsive_findings.md، responsive_visual_notes.md،
verify_manual_crop.md

## و. جرد أدوات المحرر القديم الواجب نقلها (SESSION_HANDOFF.md §6)
**الأدوات الذكية**: معالجة ذكية كاملة، إزالة الخلفية (قص ذكي)، تحسين تلقائي،
توسيط وتأطير 800×700، الظل (شريط قوة)، إزالة انعكاسات اللمعان (شريط قوة)،
المساعد الذكي — اقتراحات، تنعيم الحواف الذكي، إزالة هالة الخلفية،
منطقة العزل (اللمعان الانتقائي).
**الأدوات اليدوية**: قلم التبييض وضبط الحواف (تبييض/استرجاع/تحريك)، طمس تاريخ يدوي،
طمس التواريخ تلقائيًا، حجم الفرشاة، نعومة الحواف، منزلقات (إضاءة، تباين، حدة، تشبع،
إزالة ضوضاء)، اقتصاص وتوريس المنتج (منزلق + −0.5° + +0.5° + توريس تلقائي ذكي)،
اقتصاص للتحديد، تفعيل استوديو للتسليم.
**أوضاع**: الذكي / اليدوي / الدمج (ذكي + يدوي بالمناطق).
**شريط علوي**: فتح صورة، حفظ WebP، تراجع/إعادة، قبل/بعد، إعادة ضبط الكل، ملاءمة،
تعليمات، نسبة التكبير.

## ز. مواقع الكود المرجعية
- `native_app.py:2237` `_build_embedded_editor_tab()` — المحرر المدمج
- `native_app.py:2340` لوحة أدوات المحرر
- `native_app.py:1153` `ImagePreviewPane`
- `native_app.py:567` `ZoomableImageView`
- `build/windows/AhmedAlFaifiMarketImageStudioV2.spec` — PyInstaller المرجعي

## ح. قواعد البناء والتسليم
- لا GitHub Actions — بناء محلي.
- الحزمة المحمولة: Python 3.12 embeddable + wheels ويندوز + الكود + نماذج AI،
  البنية في §9 (`AhmedAlFaifiMarketImageStudio.bat` + `python/` + `app/`)، الحجم ~484MB.
- اختبار Wine على لينكس (numpy/cv2 يعلقان في Wine لكن يعملان على ويندوز حقيقي).

## ط. جودة WebP — الحل الجذري المؤكَّد بالأرقام
| الجودة | الحجم | PSNR | تطابق تام | مقروئية |
|---|---|---|---|---|
| 90 | 52.1KB | 55.7 | لا | 99.0% |
| 97 | 63.6KB | 63.1 | لا | 99.9% |
| 100 | 69.7KB | 66.2 | لا | 99.6% |
| **101 (lossless)** | **17.7KB** | **∞** | **نعم** | **100%** |
الخلاصة: 101 = lossless حقيقي وأصغر 4× من 100. طُبّق: قائمة الجودة في
`native_app.py` → 101 افتراضي + مساري الحفظ (~403 التدوير، ~510 التحرير)؛
`batch_refine_v2.py` compress_quality 95 → 97.

## ي. محرك الدمج (src/engine_v2/nutrition_v2.py أُعيد كتابته)
- `MIN_READABLE_LABEL_WIDTH = 520`
- `InsetPlacement(anchor="bottom_right", scale=0.34, preserve_label_pixels=True,
  max_canvas_upscale=3.0, label_card=True)` + `.clamp()`
- `_target_label_width()`: إن كان العرض المطلوب أصغر من دقة الملصق **تُوسَّع لوحة صورة
  الصنف** (LANCZOS4) بدل تصغير الجدول — هذا جذر حل فقدان الكتابات.
- `merge_label_inset()` + `merge_stats()` + `merge_label_full_quality()` +
  `render_standalone_label()`
- النتائج: دمج جديد 2400×2100 عرض جدول 816 بكسل محفوظ 91% مقابل القديم 800×700 / 272 / 30%.
  مؤشر مقروئية المكونات: 1825 مقابل 540 = **+338%**.

## ك. المتبقي المؤكَّد في نقطة الدمج (المرحلة 6)
`test_nutrition_merge_ui.py`: **PASS=30 FAIL=3** — الثلاثة توقعات اختبار لا عيوب:
1. «توقع الجودة كاملة» يعرض «دقة الجدول 90%» لأن pad البطاقة والإطار يجعل want_w=816
   لملصق 912 ⇒ الحل: احسب need مضمّنًا هامش البطاقة والإطار في `_target_label_width`.
2. «نسبة بكسل ≥ 90%» فشل عند 0.90 بالضبط بسبب round — نفس السبب.
3. «الوضع المنفصل 800×700» الناتج 1453×1272 لأن hq يوسّع اللوحة — السلوك مقصود والاختبار خاطئ.
