# فقدان تعديلات الجدول — المواصفات الكاملة لإعادة التنفيذ

## ما حدث
`windows_app/native_app.py` طابع زمنه **13:42:55** بينما تعديلات الجدول
كتبتها بين 14:00 و15:20. الملف عاد إلى حالة ما قبل إصلاحات الجدول:
- `grep -c "_fit_table_headers|_apply_status_text_mode|_sync_table_row_height|_useful_table_floor"` ⇒ **0**
- `tests/diag_table_real.py` **محذوف** (لم يبق إلا `diag_manual_rects.py`)
- `tests/diag_card_texts.py` محذوف أيضًا
- `git stash list` فارغ، و`git reflog` يحوي `clone` فقط ⇒ لا استرجاع من git

تعديلات الجلسات السابقة **سليمة**: `git diff --stat` يُظهر 701 سطرًا
مضافًا في `native_app.py` و16 في `unified_editor.py`، و`ui_scale.py` و
`test_responsive_audit.py` و`test_ui_scale.py` موجودة.

السبب المرجّح: `git stash` / `git stash pop` الذي استخدمته لعزل الأساس
أثناء التحقق من الانحدار أسقط تعديلات الجدول غير المتبعة.

## الحالة الحالية للكود (خط البداية لإعادة التنفيذ)
`_build_results_page` عند السطر ~2330:
```python
self.results_table.setColumnWidth(0, 168)
self.results_table.setColumnWidth(1, 148)
self.results_table.viewport().installEventFilter(self)
self._adjust_results_table_columns()
...
self._register_metric(self.results_table, "min_height", 250)
```
ودالة `_adjust_results_table_columns` موجودة بمنطق قديم: «الصورة 168 +
الباركود 148 والاسم يتمدد، وعلى الضيق ينكمشان ليضمنا للاسم ≥150px».

## المواصفات المقيسة الخمس المطلوب إعادة تنفيذها

### 1) ربط المصغّرة وارتفاع الصف بمحرك المقياس
العيب: `setIconSize(QSize(80,80))` و`rowHeight 88` أرقام صلبة لا تتبع
المقياس، فتبقى 88px على 800×600 = 15% من ارتفاع النافذة.
الحل: `self._register_metric(self.results_table, "icon", 80)` + دالة
`_sync_table_row_height()` تشتق ارتفاع الصف من `iconSize().height()`
وارتفاع سطر الخط، وتُستدعى في نهاية `_apply_scaled_metrics`.

### 2) أرضية الجدول من المحتوى لا من رقم
العيب: `min_height=250` (و`floor=scale.px(96)` في `_rebalance_list_pane`)
ينتج 60px على 800×600 مقابل صف 88px ⇒ **شريحة عمياء 25px**: لا صورة ولا
رقم ولا باركود.
الحل: `_useful_table_floor()` = ارتفاع الترويسة + (ارتفاع الصف × 2) +
إطار ⇒ رؤية **صنفين كاملين** مضمونة على أي شاشة.

### 3) توزيع الأعمدة من fontMetrics بأولوية انكماش صحيحة
الأرضيات تُحسب من النص الفعلي:
- الباركود: `horizontalAdvance("6281006123456") + 10`
- الاسم: `horizontalAdvance("منتج غذائي متوسط") + 16`
- الصورة: `iconSize().width() + horizontalAdvance("مطابق آليًا") + 14`

الأولوية: عمود الاسم يُقلَّص **أخيرًا**. (التجربة البصرية أثبتت أن
تقليصه أولًا — لأنه «يلتف» — يسحقه إلى 62px فينتهي بـ«…».)

### 4) الحسم البنيوي: إسقاط نص الحالة على الشاشات الضيقة
القياس الحاسم على 800×600: المتاح **259px** فقط، والأرضيات الثلاث تلزم
`115 + 99 + 98 = 312px` ⇒ **عجز 53px لا يُخفى بأي ترتيب انكماش**.
الحل (يوافق تفضيل المستخدم «مؤشر بصري + تلميح بدل النص المباشر»):
```python
icon_with_text = iconSize().width() + status_text_w + 14
icon_only = available < (icon_with_text + code_floor + name_floor)
icon_floor = iconSize().width() + 14 if icon_only else icon_with_text
self._table_status_icon_only = icon_only
```
ثم `_apply_status_text_mode()` تُفرغ نص خلية العمود 0 عند `icon_only`
وتحفظ الأصل في `Qt.UserRole + 1` فيعود تلقائيًا عند التوسّع. المصغّرة
ولونها الدلالي و`toolTip` الكامل تبقى. النتيجة: `64 + 99 + 96 = 259`
مطابق تمامًا للمتاح.

### 5) ملاءمة عناوين الترويسة
العيب: العناوين تُقص بلا «…» فتظهر «ـورة / الحـ» و«لصنف / الباركو».
الحل: `_fit_table_headers(icon_w, code_w, name_w)` تمرّ على بدائل
متدرّجة وتختار أول ما يتّسع، مع `toolTip` بالعنوان الكامل:
- عمود 0: `["الصورة / الحالة", "الصورة", "صورة"]`
- عمود 1: `["الصنف / الباركود", "الباركود", "الصنف"]`
- عمود 2: `["اسم الصنف", "الاسم"]`

**حرج**: الميزانية = `width - 24` لا `width - 10`. خصم 10px كان متفائلًا
فبقيت «الصنف / الباركود» مبتورة رغم «اتّساعها» حسابيًا (رُصد بصريًا).

## القياس المستهدف بعد إعادة التنفيذ
```
800×600   : 64 + 99 + 96   = 259 = viewport   iconSize=50  rowH=96
1024×700  : 124 + 110 + 112 = 346 = viewport   iconSize=59  rowH=86
1366×768  : 159 + 123 + 147 = 429 = viewport   iconSize=71  rowH=98
1920×1080 : 180 + 153 + 291 = 624 = viewport   iconSize=92  rowH=124
failures=0
```

## سكربت التحقق المطلوب إعادة إنشاؤه: tests/diag_table_real.py
يبني `BatchRunResult` من `BatchItemResult` حقيقية (5 أصناف: أسماء عربية
طويلة مثل «حليب المراعي طويل الأمد كامل الدسم 1 لتر»، باركودات 13 رقمًا
مثل 6281006123456، صور PNG مولّدة)، ثم لكل مقاس من
`[(800,600),(1024,700),(1366,768),(1920,1080)]`:
يعرض النافذة، ينتقل لصفحة النتائج، يطبع
`table WxH rows=N iconSize=.. rowH=..` و
`columns: img/status=.. code/barcode=.. name=.. sum=.. viewport=..`،
ويفحص القطع بمقارنة `heightForWidth` بالارتفاع المتاح لكل خلية، ويحفظ
لقطة في `/home/ubuntu/shots3/table_WxH.png`، ثم يطبع `failures=N`.

## تفاصيل إضافية مستعادة من ملفَّي تشخيص نجَوَا

من `diag_table_root.md` — المسار الدقيق للأرضية:
`_sync_manual_group_height()` (~1744) → `_rebalance_list_pane()` (~1926):
```python
floor = scale.px(96) if scale is not None else 96   # ← السطر 1958
if room >= floor: table.setMinimumHeight(room)
else:             table.setMinimumHeight(floor)      # ← 800×600 يسلك هذا
```
96 × 0.620 = 60px تمامًا (مقيس: `table.h == table.minH == 60`).
و`setIconSize(QSize(80,80))` عند السطر ~2438 غير مسجَّلة في `_scaled_metrics`.
الأرضية الصحيحة: `header.height() + rowHeight*2 + frame*2`.

من `diag_table_columns_result.md` — الفائض الأفقي والصيغ الفعلية:
| المقاس | قبل | بعد |
|---|---|---|
| 800×600 | **286 / 259** (فائض 27px) | **259 / 259** |
| البقية | مطابقة | مطابقة |

السبب: `name_min=150` وأرضيتا `108/96` مجموعها 354px مقابل 259px متاح،
مع `setMinimumSectionSize(82)` يمنع الانكماش. الصيغ البديلة:
- عمود الصورة = `iconSize().width() + 88` (أرضية `+16`)
- عمود الهوية = `horizontalAdvance("6281006123456") + 34` (أرضية `+10`)
- عمود الاسم = `horizontalAdvance("منتج غذائي متوسط") + 16`
- `minimumSectionSize` = `horizontalAdvance("0000000")` بدل 82

**تنبيه توثيقي**: هذا الملف يذكر ترتيب انكماش «الاسم أولًا»، لكن التحقق
البصري اللاحق نقضه وأثبت وجوب تقليص الاسم **أخيرًا** — الترتيب المعتمد
هو المذكور في البند 3 أعلاه.

كذلك `STATUS_TEXT` كان ينقصه 4 مفاتيح فظهرت بالإنجليزية الخام في واجهة
عربية — `unmatched` → «غير مرتبط» (ظهرت فعلًا في الجدول)، و`pending`
و`skipped` و`duplicate` احتياطًا، مع لون دلالي لكلٍّ في `STATUS_COLORS`.

## احتياط ملزم لما بعد
1. **لا `git stash` مطلقًا** مع وجود تعديلات غير متبعة.
2. نسخة احتياطية فور كل إصلاح:
   `cp windows_app/native_app.py /home/ubuntu/backup/native_app.$(date +%H%M%S).py`
3. سكربتات التشخيص تُكتب في `/home/ubuntu/diagscripts/` (خارج المستودع)
   لا في `tests/`.
