# -*- coding: utf-8 -*-
"""المحرر الموحد المدمج — كل أدوات تحرير الصورة في صفحة واحدة.

يعيد استخدام كامل منطق المعالجة في ``V2PhotoEditorDialog`` (photo_editor_v2.py)
لكن بواجهة معاد تنظيمها لتناسب الدمج داخل تبويب «تحرير مباشر»:

* الصورة (EditorCanvas) كبيرة في الأعلى وتأخذ معظم المساحة.
* شريط «الخيارات المهمة» أفقي أسفل الصورة مباشرة — الأدوات الأساسية ظاهرة
  دائمًا دون أي نقرة إضافية.
* زر «أدوات متقدمة ▾» يفتح/يطوي لوحة داخل الصفحة نفسها (ليست نافذة منفصلة)
  تحوي بطاقات التعديلات الدقيقة: الظل، الانعكاسات، المنزلقات، الفرشاة
  اليدوية، منطقة العزل، الحواف والهالة، تنقيح الاستوديو، الميل الدقيق،
  والمساعد الذكي.
* لا يوجد زر فتح/حفظ داخلي — التحميل عبر ``load_image()`` والنتيجة عبر
  ``get_result_bgr()`` ليتكامل مع مسار «حفظ واعتماد» في التطبيق الرئيسي.

بهذا يبقى photo_editor_v2.py مكتبة معالجة مختبرة (تعتمد عليها الاختبارات)،
بينما يختفي كنافذة مستقلة نهائيًا.
"""
from __future__ import annotations

# 2.9.6 — تسريع الإقلاع: `numpy` لا يُستعمل في هذه الوحدة إلا في
# تلميح نوعي واحد داخل سلسلة نصية (`get_result_bgr`)، فاستيراده
# على مستوى الوحدة كان يكلّف مئات المللي ثوانٍ دون مقابل. يبقى
# متاحًا لمدقّقات الأنواع عبر TYPE_CHECKING بلا أي كلفة وقت التشغيل.
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - للتحليل الساكن فقط
    import numpy as np

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from flow_layout import FlowLayout
from photo_editor_v2 import V2PhotoEditorDialog


# 2.9.6 — تسريع الإقلاع: تعريف ``_FlowLayout`` انتقل إلى ``flow_layout``
# لأن لوحة النتائج كانت تستورده من هنا أثناء بناء الواجهة، فيجرّ معه
# ``photo_editor_v2`` و``numpy`` قبل ظهور النافذة. المنطق لم يتغير حرفًا،
# والاسم القديم يبقى مُصدَّرًا هنا حفاظًا على أي كود أو اختبار قائم.
_FlowLayout = FlowLayout


class UnifiedEditorWidget(V2PhotoEditorDialog):
    """محرر مدمج بكامل قدرات V2PhotoEditorDialog لكن كصفحة واحدة موحدة.

    يرث كل منطق المعالجة (القص الذكي، التحسين، الظل، الفرشاة، المنزلقات،
    التراجع/الإعادة…) ويعيد ترتيب الواجهة فقط. يُدرج داخل layout كأي QWidget.
    """

    # تُطلق عند أي تعديل يغيّر الصورة — ليعلم التطبيق أن هناك عملًا غير محفوظ
    edited = Signal()

    def __init__(self, parent=None):
        # V2PhotoEditorDialog.__init__ يبني الواجهة القديمة عبر _build_ui؛
        # نعترض البناء ونستبدله بترتيبنا الجديد (انظر _build_ui أدناه).
        super().__init__("", parent)
        # QDialog يعمل كـ widget عادي عند إدراجه في layout — نزيل صفة النافذة
        self.setWindowFlags(Qt.Widget)
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:  # يستبدل واجهة النافذة القديمة بالكامل
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        # ---------- 1) الصورة الكبيرة (canvas بكامل قدرات الفرشاة والزوم)
        from photo_editor_v2 import EditorCanvas  # استيراد محلي لتفادي الدورات

        self.canvas = EditorCanvas()
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # الصورة لا تختفي أبدًا — حتى على أصغر الشاشات تبقى مرئية بارتفاع معقول
        self.canvas.setMinimumHeight(140)
        self.canvas.brush_stroke.connect(self._on_stroke)
        root.addWidget(self.canvas, 1)

        # شريط تقدم رفيع أسفل الصورة (للعمليات الذكية الثقيلة)
        from PySide6.QtWidgets import QProgressBar

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setMaximumHeight(6)
        self.progress.setTextVisible(False)
        root.addWidget(self.progress)

        # ---------- 2) شريط الحالة المصغر (زوم + حالة + وضع)
        info_row = QHBoxLayout()
        info_row.setContentsMargins(8, 0, 8, 0)
        info_row.setSpacing(10)
        self.status_label = QLabel("اختر صفًا من الجدول لبدء التحرير")
        self.status_label.setObjectName("unifiedEditorStatus")
        self.status_label.setStyleSheet("color:#555;font-size:11px;")
        self.zoom_label = QLabel("100%")
        self.zoom_label.setMinimumWidth(48)
        self.zoom_label.setAlignment(Qt.AlignCenter)
        self.zoom_label.setStyleSheet("color:#64748b;font-size:11px;")
        self.canvas.zoom_changed.connect(
            lambda z: self.zoom_label.setText(f"{int(z * 100)}%"))
        self.mode_label = QLabel("")
        self.mode_label.setStyleSheet(
            "color:#0a6e3a;font-weight:700;font-size:11px;")
        # 2.9.13 (م-10) — مؤشر الأداة النشطة في الشريط المعروض فعلًا.
        #
        # هذا الصف لا ترفيه: `UnifiedEditorWidget` يستبدل `_build_ui`
        # بالكامل، فما يُضاف إلى شريط حالة `photo_editor_v2` لا يُرى
        # هنا إطلاقًا. والمالك يعمل في هذا المحرر لا في الحوار
        # القديم، فوضع المؤشر هناك وحده كان سيكون إضافة لا يراها أحد.
        self.active_tool_label = QLabel("")
        self.active_tool_label.setObjectName("activeToolLabel")
        self.active_tool_label.setAlignment(Qt.AlignCenter)
        info_row.addWidget(self.status_label, 1)
        info_row.addWidget(self.active_tool_label)
        info_row.addWidget(self.mode_label)
        info_row.addWidget(self.zoom_label)
        root.addLayout(info_row)

        # ---------- 3) شريط «الخيارات المهمة» — ظاهر دائمًا
        root.addWidget(self._build_primary_bar())

        # ---------- 4) لوحة «أدوات متقدمة» قابلة للطي داخل الصفحة نفسها
        self.advanced_panel = self._build_advanced_panel()
        self.advanced_panel.setVisible(False)
        root.addWidget(self.advanced_panel)
        # مراجع التخطيط — تلزم لنقل اللوحة المتقدمة جانبيًا (2.9.11)
        self._root_layout = root

        self._apply_unified_style()
        self._install_zoom_shortcuts()

    # ------------------------------------------------------- zoom shortcuts
    def _install_zoom_shortcuts(self) -> None:
        """اختصارات زوم معيارية — ما يتوقعه أي مستخدم من محرر صور.

        ``Ctrl+=``/``Ctrl++`` تكبير، ``Ctrl+-`` تصغير، ``Ctrl+0``
        الحجم الحقيقي، ``Ctrl+9``/``F`` ملاءمة. النطاق
        ``WidgetWithChildrenShortcut`` لا ``ApplicationShortcut``، فلا
        تختلس الاختصارات من بقية التطبيق حين لا يكون المحرر في الواجهة.
        """
        from PySide6.QtGui import QKeySequence, QShortcut

        def add(keys: str, slot) -> None:
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)

        add("Ctrl+=", lambda: self.canvas.zoom_step(1.25))
        add("Ctrl++", lambda: self.canvas.zoom_step(1.25))
        add("Ctrl+-", lambda: self.canvas.zoom_step(1 / 1.25))
        add("Ctrl+0", lambda: self.canvas.zoom_actual())
        add("Ctrl+9", lambda: self.canvas.fit_view())

    # --------------------------------------------- advanced panel placement
    def set_advanced_side_mode(self, side: bool) -> None:
        """وضع اللوحة المتقدمة جانبًا بدل أسفل الصورة.

        لماذا (2.9.11 — شكوى المالك الثالثة): اللوحة أسفل الصورة
        تأكل حتى 240px من **الارتفاع**، ومعها الترويسة وشريط الأدوات
        والتذييل لا يبقى للصورة إلا ثلث الشاشة — وهو الذي أبلغ عنه
        حرفيًا («الصورة 35%»). الشاشات العريضة فيها عرض فاضل لا
        ارتفاع، فنقلها يمينًا يرد للصورة كل ارتفاعها دون إخفاء أي أداة.
        """
        side = bool(side)
        if side == bool(getattr(self, "_advanced_side", False)):
            return
        root = getattr(self, "_root_layout", None)
        if root is None:
            return
        scroll = getattr(self, "_advanced_scroll", None)
        if side:
            # المحاولة الأولى أضافت الحاوية إلى نفس التخطيط العمودي
            # فصارت صفًا رابعًا يأكل 410px من الارتفاع — أسوأ من قبل.
            # الصواب: ننقل **كل محتوى الجذر** (الصورة والأشرطة)
            # إلى ودجت عمود، ثم نضع [العمود | اللوحة] في صف أفقي واحد.
            items: list = []
            while root.count():
                items.append(root.takeAt(0))

            column = QWidget()
            col = QVBoxLayout(column)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(root.spacing() if root.spacing() >= 0 else 6)
            for it in items:
                w = it.widget()
                if w is self.advanced_panel:
                    continue
                if w is not None:
                    col.addWidget(w, 1 if w is self.canvas else 0)
                elif it.layout() is not None:
                    col.addLayout(it.layout())
                elif it.spacerItem() is not None:
                    col.addItem(it.spacerItem())
            self._side_column = column

            hl = QHBoxLayout()
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(6)
            hl.addWidget(column, 1)
            hl.addWidget(self.advanced_panel, 0)
            self._side_row = hl

            self.advanced_panel.setMaximumWidth(360)
            self.advanced_panel.setMinimumWidth(260)
            if scroll is not None:
                # جانبيًا لا معنى لسقف ارتفاع — تمتد بكامل الطول
                scroll.setMaximumHeight(16777215)
                scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self._reflow_advanced(vertical=True)
            root.addLayout(hl, 1)
        else:
            column = getattr(self, "_side_column", None)
            row = getattr(self, "_side_row", None)
            self.advanced_panel.setMaximumWidth(16777215)
            self.advanced_panel.setMinimumWidth(0)
            if scroll is not None:
                scroll.setMaximumHeight(240)
                scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self._reflow_advanced(vertical=False)
            if column is not None:
                col = column.layout()
                moved: list = []
                while col is not None and col.count():
                    moved.append(col.takeAt(0))
                # أفرغ الجذر من الصف الأفقي قبل إرجاع العناصر
                while root.count():
                    root.takeAt(0)
                for it in moved:
                    w = it.widget()
                    if w is not None:
                        root.addWidget(w, 1 if w is self.canvas else 0)
                    elif it.layout() is not None:
                        root.addLayout(it.layout())
                    elif it.spacerItem() is not None:
                        root.addItem(it.spacerItem())
                root.addWidget(self.advanced_panel)
                if row is not None:
                    row.setParent(None)
                column.setParent(None)
                column.deleteLater()
            self._side_column = None
            self._side_row = None
        self._advanced_side = side

    def _reflow_advanced(self, vertical: bool) -> None:
        """يعيد ترتيب بطاقات اللوحة المتقدمة أفقيًا أو عموديًا.

        البطاقات نفسها تُنقل بلا إعادة بناء، فلا تُفقد قيمة منزلقة
        ولا حالة مربع اختيار ولا تنقطع أي إشارة موصولة.
        """
        row = getattr(self, "_advanced_row", None)
        if row is None:
            return
        cards = [row.itemAt(i).widget() for i in range(row.count())]
        cards = [c for c in cards if c is not None]
        inner = getattr(self, "_advanced_inner", None)
        if inner is None:
            return
        new = QVBoxLayout() if vertical else QHBoxLayout()
        new.setContentsMargins(6, 6, 6, 6)
        new.setSpacing(8)
        for c in cards:
            new.addWidget(c)
        if vertical:
            new.addStretch(1)
        # إزالة التخطيط القديم ثم تركيب الجديد على نفس الحاوية
        old = inner.layout()
        if old is not None:
            QWidget().setLayout(old)   # ينقل ملكية التخطيط القديم فيُحرر
        inner.setLayout(new)
        self._advanced_row = new

    # ---------------------------------------------------- primary toolbar
    def _build_primary_bar(self) -> QWidget:
        """شريط أيقونات ثابتة العرض (مثل فوتوشوب) — كل أداة علامة
        مع تلميح عربي يظهر عند وضع الماوس فوقها. الأزرار تلتف تلقائيًا
        لسطر ثانٍ على الشاشات الضيقة — لا قص ولا نصوص مبتورة أبدًا."""
        bar = QFrame()
        bar.setObjectName("unifiedPrimaryBar")
        lay = _FlowLayout(bar, margin=6, spacing=5)

        def btn(icon: str, tooltip: str, slot=None, *,
                checkable: bool = False, accent: bool = False,
                wide: bool = False) -> QPushButton:
            b = QPushButton(icon)
            b.setFixedHeight(40)
            if wide:
                b.setMinimumWidth(64)
            else:
                b.setFixedWidth(48)
            b.setCheckable(checkable)
            b.setToolTip(tooltip)
            b.setCursor(Qt.PointingHandCursor)
            if accent:
                b.setObjectName("unifiedAccentBtn")
            if slot is not None:
                b.clicked.connect(slot)
            return b

        # الزر الأهم — معالجة كاملة بنقرة واحدة
        self.auto_all_btn = btn(
            "✦", "معالجة ذكية كاملة: إزالة الخلفية + تحسين + توسيط 800×700 بنقرة واحدة",
            self._smart_full, accent=True, wide=True)
        self.cutout_btn = btn("✂", "إزالة الخلفية: قص ذكي للمنتج مع خلفية بيضاء",
                              self._smart_cutout)
        self.enhance_btn = btn("☀", "تحسين تلقائي: إضاءة وألوان وحدة تلقائية محافظة",
                               self._smart_enhance)
        self.center_btn = btn("▣", "توسيط 800×700: توسيط المنتج وتأطيره بمقاس المتجر",
                              self._smart_frame)
        self.auto_date_btn = btn("⊘", "طمس التواريخ: يكشف التواريخ المطبوعة ويطمسها تلقائيًا",
                                 self._auto_blur_dates)
        self.auto_level_btn = btn("⚖", "توزين تلقائي: يكشف ميل المنتج ويصححه بدقة",
                                  self._auto_level)
        self.undo_btn = btn("↶", "تراجع عن آخر خطوة", self._undo)
        self.redo_btn = btn("↷", "إعادة الخطوة الملغاة", self._redo_action)
        self.before_btn = btn("◐", "قبل / بعد: اضغط باستمرار لعرض الصورة الأصلية",
                              checkable=True)
        self.before_btn.pressed.connect(lambda: self._toggle_before(True))
        self.before_btn.released.connect(lambda: self._toggle_before(False))
        # 2.9.11 — المالك طلب تكبيرًا وتحريكًا سهلًا وسلسًا. العجلة
        # والسحب كانا متوفرين في `EditorCanvas` لكن بلا أي زر مرئي،
        # ومن لا يعرف أن العجلة تزوّم يظن المحرر بلا زوم. فأُضيفت
        # ثلاثة أزرار صريحة مع اختصارات Ctrl+= / Ctrl+- / Ctrl+0.
        self.zoom_in_btn = btn("＋", "تكبير (Ctrl+=) — أو عجلة الفأرة للأعلى",
                               lambda: self.canvas.zoom_step(1.25))
        self.zoom_out_btn = btn("－", "تصغير (Ctrl+-) — أو عجلة الفأرة للأسفل",
                                lambda: self.canvas.zoom_step(1 / 1.25))
        self.zoom_reset_btn = btn(
            "1:1", "الحجم الحقيقي 100% (Ctrl+0) — لفحص النص والباركود بدقة",
            lambda: self.canvas.zoom_actual(), wide=True)
        self.fit_btn = btn("⛶", "ملاءمة الصورة لحجم النافذة (والتحريك بسحب الفأرة)",
                           lambda: self.canvas.fit_view())
        self.reset_btn = btn("↺", "إعادة ضبط: العودة إلى الصورة الأصلية",
                             self._reset_all)

        self.advanced_toggle_btn = btn(
            "⚙ ▾", "أدوات متقدمة: الظل والمنزلقات والفرشاة اليدوية والتعديلات الدقيقة",
            None, checkable=True, wide=True)
        self.advanced_toggle_btn.setObjectName("unifiedAdvancedToggle")
        self.advanced_toggle_btn.toggled.connect(self._toggle_advanced)

        for w in (self.auto_all_btn, self.cutout_btn, self.enhance_btn,
                  self.center_btn, self.auto_date_btn, self.auto_level_btn,
                  self.undo_btn, self.redo_btn, self.before_btn,
                  self.zoom_out_btn, self.zoom_reset_btn, self.zoom_in_btn,
                  self.fit_btn, self.reset_btn, self.advanced_toggle_btn):
            lay.addWidget(w)
        return bar

    def _toggle_advanced(self, on: bool) -> None:
        self.advanced_panel.setVisible(on)
        self.advanced_toggle_btn.setText("⚙ ▴" if on else "⚙ ▾")
        # إغلاق اللوحة في الوضع الجانبي يجعل البقاء جانبيًا بلا معنى؛
        # نعود للترتيب العمودي فتأخذ الصورة العرض كله أيضًا.
        if not on and getattr(self, "_advanced_side", False):
            self.set_advanced_side_mode(False)
        elif on and getattr(self, "_root_layout", None) is not None:
            want = self.width() >= 1120 and self.height() < 980
            if want != bool(getattr(self, "_advanced_side", False)):
                self.set_advanced_side_mode(want)

    # ---------------------------------------------------- advanced panel
    def _build_advanced_panel(self) -> QWidget:
        """لوحة داخل الصفحة (ليست نافذة): بطاقات أفقية قابلة للتمرير."""
        from PySide6.QtWidgets import QCheckBox, QComboBox, QSlider

        container = QFrame()
        container.setObjectName("unifiedAdvancedPanel")
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # تمرير عمودي داخلي عند الشاشات القصيرة — لا تُقص المنزلقات أبدًا
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setMaximumHeight(240)
        # ارتفاع أدنى يضمن أن اللوحة لا تنضغط لشريط غير قابل للاستخدام
        scroll.setMinimumHeight(96)
        self._advanced_scroll = scroll

        inner = QWidget()
        row = QHBoxLayout(inner)
        row.setContentsMargins(6, 6, 6, 6)
        row.setSpacing(8)
        # 2.9.11 — يُحتفظ بالمرجعين لأن `set_advanced_side_mode`
        # يعيد ترتيب البطاقات عموديًا حين تنتقل اللوحة للجانب.
        self._advanced_inner = inner
        self._advanced_row = row

        def card(title: str) -> tuple[QFrame, QVBoxLayout]:
            c = QFrame()
            c.setObjectName("unifiedAdvCard")
            v = QVBoxLayout(c)
            v.setContentsMargins(8, 6, 8, 6)
            v.setSpacing(4)
            t = QLabel(title)
            t.setObjectName("unifiedAdvCardTitle")
            t.setAlignment(Qt.AlignCenter)
            v.addWidget(t)
            c.setMinimumWidth(200)
            return c, v

        def hslider(lo: int, hi: int, val: int, slot=None) -> QSlider:
            s = QSlider(Qt.Horizontal)
            s.setLayoutDirection(Qt.LeftToRight)
            s.setRange(lo, hi)
            s.setValue(val)
            if slot is not None:
                s.valueChanged.connect(slot)
            return s

        # ── بطاقة الفرشاة اليدوية ──
        brush_card, bv = card("الفرشاة اليدوية")
        brow = QHBoxLayout()
        self.erase_btn = QPushButton("قلم تبييض")
        self.erase_btn.setCheckable(True)
        self.restore_btn = QPushButton("استرجاع")
        self.restore_btn.setCheckable(True)
        self.pan_btn = QPushButton("تحريك ✋")
        self.pan_btn.setCheckable(True)
        self.pan_btn.setChecked(True)
        for b in (self.erase_btn, self.restore_btn, self.pan_btn):
            b.setMinimumHeight(30)
            brow.addWidget(b)
        bv.addLayout(brow)
        self.date_blur_btn = QPushButton("طمس تاريخ يدوي")
        self.date_blur_btn.setCheckable(True)
        self.date_blur_btn.setMinimumHeight(30)
        self.date_blur_btn.setToolTip(
            "اسحب مستطيلًا فوق التاريخ المطبوع ليُطمس بلون المنتج")
        from photo_editor_v2 import EditorCanvas
        self.date_blur_btn.toggled.connect(
            lambda on: self._pick_tool(EditorCanvas.TOOL_DATE_BLUR, on,
                                       self.date_blur_btn))
        bv.addWidget(self.date_blur_btn)
        srow = QGridLayout()
        srow.addWidget(QLabel("حجم الفرشاة"), 0, 0)
        self.brush_slider = hslider(6, 200, 40, self.canvas.set_brush_size)
        srow.addWidget(self.brush_slider, 0, 1)
        self.brush_size_lbl = QLabel("40")
        self.brush_slider.valueChanged.connect(
            lambda v: self.brush_size_lbl.setText(str(v)))
        srow.addWidget(self.brush_size_lbl, 0, 2)
        srow.addWidget(QLabel("نعومة الحواف"), 1, 0)
        self.feather_slider = hslider(0, 30, 6, self._schedule_preview)
        srow.addWidget(self.feather_slider, 1, 1)
        bv.addLayout(srow)
        bv.addStretch(1)
        row.addWidget(brush_card)

        # ── بطاقة المنزلقات ──
        sliders_card, sv = card("منزلقات التحسين")
        grid = QGridLayout()
        self._sliders: dict = {}
        specs = [
            ("الإضاءة", "brightness", -100, 100, 0),
            ("التباين", "contrast", -100, 100, 0),
            ("الحدة", "sharpness", 0, 100, 0),
            ("التشبع", "saturation", -100, 100, 0),
            ("إزالة الضوضاء", "denoise", 0, 100, 0),
        ]
        for i, (label, key, lo, hi, dv) in enumerate(specs):
            grid.addWidget(QLabel(label), i, 0)
            s = hslider(lo, hi, dv, self._schedule_preview)
            s.setToolTip("اسحب يمينًا للزيادة ويسارًا للنقصان")
            self._sliders[key] = s
            grid.addWidget(s, i, 1)
            val = QLabel("0")
            val.setMinimumWidth(26)
            s.valueChanged.connect(lambda v, l=val: l.setText(str(v)))
            grid.addWidget(val, i, 2)
        sv.addLayout(grid)
        zero_btn = QPushButton("تصفير المنزلقات")
        zero_btn.setMinimumHeight(28)
        zero_btn.clicked.connect(self._zero_sliders)
        sv.addWidget(zero_btn)
        sliders_card.setMinimumWidth(260)
        row.addWidget(sliders_card)

        # ── بطاقة الميل الدقيق ──
        rot_card, rv = card("ميول دقيق 0.1°")
        rrow = QHBoxLayout()
        self.rotate_slider = hslider(-1800, 1800, 0, self._schedule_preview)
        self.rotate_slider.setSingleStep(1)
        self.rotate_slider.setPageStep(10)
        self.rotate_slider.setToolTip(
            "اسحب لتوزين المنتج بدقة 0.1° — تظهر شبكة إرشادية أثناء السحب")
        self.rotate_slider.sliderPressed.connect(
            lambda: setattr(self.canvas, "show_grid", True))
        self.rotate_slider.sliderReleased.connect(self._rot_released)
        rrow.addWidget(self.rotate_slider)
        self.rot_lbl = QLabel("0.0°")
        self.rot_lbl.setMinimumWidth(44)
        self.rotate_slider.valueChanged.connect(
            lambda v: self.rot_lbl.setText(f"{v / 10.0:.1f}°"))
        rrow.addWidget(self.rot_lbl)
        rv.addLayout(rrow)
        fine = QHBoxLayout()
        for txt, delta in (("−٠.٥°", -5), ("+٠.٥°", 5)):
            b = QPushButton(txt)
            b.setMinimumHeight(28)
            b.clicked.connect(lambda _, d=delta: self.rotate_slider.setValue(
                self.rotate_slider.value() + d))
            fine.addWidget(b)
        rz = QPushButton("تصفير")
        rz.setMinimumHeight(28)
        rz.clicked.connect(lambda: self.rotate_slider.setValue(0))
        fine.addWidget(rz)
        rv.addLayout(fine)
        self.crop_btn = QPushButton("اقتصاص للتحديد")
        self.crop_btn.setMinimumHeight(30)
        self.crop_btn.setToolTip("حدد منطقة بالمستطيل ثم اضغط للاقتصاص")
        self.crop_btn.clicked.connect(self._crop_to_region)
        rv.addWidget(self.crop_btn)
        rv.addStretch(1)
        row.addWidget(rot_card)

        # ── بطاقة الظل ──
        shadow_card, shv = card("الظل أسفل المنتج")
        self.shadow_enable_cb = QCheckBox("تفعيل ظل طبيعي")
        self.shadow_enable_cb.setToolTip("ظل أرضي ناعم أسفل المنتج")
        shv.addWidget(self.shadow_enable_cb)
        sh_row = QGridLayout()
        sh_row.addWidget(QLabel("قوة الظل"), 0, 0)
        self.shadow_strength = hslider(10, 100, 45)
        sh_row.addWidget(self.shadow_strength, 0, 1)
        self.shadow_strength_lbl = QLabel("45")
        self.shadow_strength.valueChanged.connect(
            lambda v: self.shadow_strength_lbl.setText(str(v)))
        sh_row.addWidget(self.shadow_strength_lbl, 0, 2)
        shv.addLayout(sh_row)
        self.shadow_combo = QComboBox()
        self.shadow_combo.setMinimumHeight(28)
        self.shadow_combo.setToolTip("أنماط الظل الجاهزة")
        shv.addWidget(self.shadow_combo)
        self.shadow_enable_cb.toggled.connect(self._shadow_changed)
        self.shadow_strength.valueChanged.connect(self._shadow_changed)
        self.shadow_combo.currentIndexChanged.connect(self._shadow_changed)
        shv.addStretch(1)
        row.addWidget(shadow_card)

        # ── بطاقة الانعكاسات والحواف ──
        clean_card, cv = card("الانعكاسات والحواف")
        self.glare_enable_cb = QCheckBox("إزالة الانعكاسات (اللمعان)")
        self.glare_enable_cb.setToolTip(
            "يكشف لمعان الفلاش ويزيله مع حفظ التفاصيل")
        self.glare_enable_cb.toggled.connect(self._schedule_preview)
        cv.addWidget(self.glare_enable_cb)
        gl_row = QGridLayout()
        gl_row.addWidget(QLabel("القوة"), 0, 0)
        self.glare_strength = hslider(10, 100, 60, self._schedule_preview)
        gl_row.addWidget(self.glare_strength, 0, 1)
        self.glare_strength_lbl = QLabel("60")
        self.glare_strength.valueChanged.connect(
            lambda v: self.glare_strength_lbl.setText(str(v)))
        gl_row.addWidget(self.glare_strength_lbl, 0, 2)
        cv.addLayout(gl_row)
        erow = QHBoxLayout()
        self.refine_edges_btn = QPushButton("تنعيم الحواف")
        self.refine_edges_btn.setMinimumHeight(30)
        self.refine_edges_btn.setToolTip(
            "للمنتجات الصعبة: أغلفة شفافة وانحناءات")
        self.refine_edges_btn.clicked.connect(self._refine_edges)
        self.dehalo_btn = QPushButton("إزالة الهالة")
        self.dehalo_btn.setMinimumHeight(30)
        self.dehalo_btn.setToolTip("يزيل بقايا لون الخلفية عن الحواف")
        self.dehalo_btn.clicked.connect(self._remove_halo)
        erow.addWidget(self.refine_edges_btn)
        erow.addWidget(self.dehalo_btn)
        cv.addLayout(erow)
        cv.addStretch(1)
        row.addWidget(clean_card)

        # ── بطاقة منطقة العزل ──
        region_card, rgv = card("منطقة العزل")
        hint = QLabel("حدد منطقة ثم طبّق أي أداة عليها فقط")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666;font-size:11px;")
        rgv.addWidget(hint)
        rg_row = QHBoxLayout()
        self.region_brush_btn = QPushButton("فرشاة تحديد")
        self.region_brush_btn.setCheckable(True)
        self.region_rect_btn = QPushButton("مستطيل تحديد")
        self.region_rect_btn.setCheckable(True)
        for b in (self.region_brush_btn, self.region_rect_btn):
            b.setMinimumHeight(30)
            rg_row.addWidget(b)
        rgv.addLayout(rg_row)
        self.region_clear_btn = QPushButton("مسح التحديد")
        self.region_clear_btn.setMinimumHeight(28)
        self.region_clear_btn.clicked.connect(self._clear_region)
        rgv.addWidget(self.region_clear_btn)
        self.region_only_cb = QCheckBox("تطبيق الأدوات على المنطقة فقط")
        rgv.addWidget(self.region_only_cb)
        self.region_brush_btn.toggled.connect(
            lambda on: self._pick_tool(EditorCanvas.TOOL_REGION, on,
                                       self.region_brush_btn))
        self.region_rect_btn.toggled.connect(
            lambda on: self._pick_tool(EditorCanvas.TOOL_REGION_RECT, on,
                                       self.region_rect_btn))
        rgv.addStretch(1)
        row.addWidget(region_card)

        # ── بطاقة تنقيح الاستوديو + المساعد الذكي ──
        studio_card, stv = card("تنقيح استوديو + مساعد ذكي")
        self.polish_enable_cb = QCheckBox("تفعيل تنقيح الاستوديو")
        self.polish_enable_cb.setToolTip(
            "حواف نظيفة + توازن أبيض + لمعة متجر — تظهر فورًا")
        self.polish_enable_cb.toggled.connect(self._schedule_preview)
        stv.addWidget(self.polish_enable_cb)
        po_row = QGridLayout()
        po_row.addWidget(QLabel("قوة اللمعة"), 0, 0)
        self.polish_strength = hslider(0, 100, 50, self._schedule_preview)
        po_row.addWidget(self.polish_strength, 0, 1)
        self.polish_strength_lbl = QLabel("50")
        self.polish_strength.valueChanged.connect(
            lambda v: self.polish_strength_lbl.setText(str(v)))
        po_row.addWidget(self.polish_strength_lbl, 0, 2)
        stv.addLayout(po_row)
        self.suggest_btn = QPushButton("حلل الصورة واقترح تحسينات ✦")
        self.suggest_btn.setMinimumHeight(30)
        self.suggest_btn.clicked.connect(self._show_suggestions)
        stv.addWidget(self.suggest_btn)
        self.suggestions_box = QVBoxLayout()
        stv.addLayout(self.suggestions_box)
        stv.addStretch(1)
        studio_card.setMinimumWidth(230)
        row.addWidget(studio_card)

        scroll.setWidget(inner)
        outer.addWidget(scroll)

        # عناصر مطلوبة من المنطق الموروث لكنها غير معروضة في الوضع المدمج
        self._build_hidden_compat_widgets()
        return container

    def resizeEvent(self, event):  # noqa: N802
        """توزيع متجاوب: على الشاشات القصيرة تنكمش اللوحة المتقدمة
        (مع تمرير داخلي) لتبقى الصورة كبيرة ومرئية دائمًا."""
        super().resizeEvent(event)
        # 2.9.11 — اختيار الموضع تلقائيًا: متى كان العرض واسعًا
        # والارتفاع محدودًا تنتقل اللوحة يمينًا فترد للصورة ارتفاعها.
        # العتبة عرض ≥ 1120 وارتفاع < 980 — تغطي 1366×768 و 1920×1080
        # وهما شاشتا العمل الغالبتان، وتستثني الشاشات الضيقة.
        if getattr(self, "_root_layout", None) is not None:
            # واللوحة مطوية لا معنى للوضع الجانبي — الصورة تأخذ كل شيء
            want_side = (self.advanced_panel.isVisible()
                         and self.width() >= 1120 and self.height() < 980)
            if want_side != bool(getattr(self, "_advanced_side", False)):
                self.set_advanced_side_mode(want_side)
        scroll = getattr(self, "_advanced_scroll", None)
        if scroll is not None and not getattr(self, "_advanced_side", False):
            # اللوحة المتقدمة لا تأخد أكثر من 30% من ارتفاع الصفحة
            cap = max(96, min(240, int(self.height() * 0.30)))
            if scroll.maximumHeight() != cap:
                scroll.setMaximumHeight(cap)

    def _build_hidden_compat_widgets(self) -> None:
        """عناصر يشير إليها المنطق الموروث (أوضاع/فتح/حفظ) دون عرضها.

        الوضع الافتراضي هو «الدمج» (ذكي + يدوي بالمناطق) — الأقوى والأشمل،
        ولا حاجة لإظهار أزرار الأوضاع لأن كل الأدوات متاحة معًا في صفحة واحدة.
        """
        from PySide6.QtWidgets import QButtonGroup, QRadioButton

        self.mode_smart_rb = QRadioButton("الوضع الذكي")
        self.mode_manual_rb = QRadioButton("الوضع اليدوي")
        self.mode_blend_rb = QRadioButton("وضع الدمج")
        self.mode_blend_rb.setChecked(True)
        self._mode_group = QButtonGroup(self)
        for rb in (self.mode_smart_rb, self.mode_manual_rb,
                   self.mode_blend_rb):
            self._mode_group.addButton(rb)
            rb.setVisible(False)
            rb.setParent(self)
        # أزرار فتح/حفظ يعطلها _busy الموروث — ننشئها مخفية للتوافق
        self.open_btn = QPushButton(self)
        self.open_btn.setVisible(False)
        self.save_btn = QPushButton(self)
        self.save_btn.setVisible(False)
        self.help_btn = QPushButton(self)
        self.help_btn.setVisible(False)

    # ------------------------------------------------------------- style
    def _apply_unified_style(self) -> None:
        self.setStyleSheet("""
            QFrame#unifiedPrimaryBar {
                background: #f8fafc; border: 1px solid #e2e8f0;
                border-radius: 8px;
            }
            QFrame#unifiedPrimaryBar QPushButton {
                padding: 2px; border: 1px solid #cbd5e1;
                border-radius: 8px; background: #ffffff; font-weight: 700;
                font-size: 17px; color: #334155;
            }
            QToolTip {
                background: #1e293b; color: #f8fafc;
                border: 1px solid #334155; border-radius: 6px;
                padding: 6px 10px; font-size: 13px; font-weight: 600;
            }
            QFrame#unifiedPrimaryBar QPushButton:hover { background: #eef2ff; }
            QFrame#unifiedPrimaryBar QPushButton:checked {
                background: #dbeafe; border-color: #2563eb;
            }
            QPushButton#unifiedAccentBtn {
                background: #2563eb; color: white; font-weight: 800;
                border: none;
            }
            QPushButton#unifiedAccentBtn:hover { background: #1d4ed8; }
            QPushButton#unifiedAdvancedToggle {
                color: #2563eb; font-weight: 700;
            }
            QFrame#unifiedAdvancedPanel {
                background: #f1f5f9; border: 1px solid #e2e8f0;
                border-radius: 8px;
            }
            QFrame#unifiedAdvCard {
                background: #ffffff; border: 1px solid #e2e8f0;
                border-radius: 8px;
            }
            QLabel#unifiedAdvCardTitle {
                font-weight: 800; color: #334155; font-size: 12px;
            }
            QFrame#unifiedAdvCard QPushButton {
                border: 1px solid #cbd5e1; border-radius: 6px;
                background: #f8fafc; padding: 2px 6px;
            }
            QFrame#unifiedAdvCard QPushButton:hover { background: #eef2ff; }
            QFrame#unifiedAdvCard QPushButton:checked {
                background: #dbeafe; border-color: #2563eb;
            }
            QSlider::groove:horizontal { height: 5px; background: #d7dbe2;
                                         border-radius: 2px; }
            QSlider::handle:horizontal { width: 16px; height: 16px;
                margin: -6px 0; background: #2563eb; border-radius: 8px; }
        """)

    # --------------------------------------------------------- public API
    def _recompose(self, fit: bool = False) -> None:  # noqa: D102
        super()._recompose(fit)
        # أي إعادة تركيب بعد وجود تعديلات = عمل غير محفوظ — أعلِم التطبيق
        if self._original is not None and self.has_edits():
            self.edited.emit()

    def load_image(self, path: str) -> None:
        """تحميل صورة للتحرير (يعيد ضبط كل الحالة السابقة)."""
        self._load_image(str(path))

    def clear(self) -> None:
        """تفريغ المحرر عند إنهاء الجلسة."""
        self._original = None
        self._base = None
        self._alpha_manual = None
        self._region_mask = None
        self._region_active = False
        self._cutout_applied = False
        self._shadow_opts = None
        self._composited = None
        self._history.clear()
        self._redo.clear()
        self._image_path = ""
        from PySide6.QtGui import QPixmap
        self.canvas._item.setPixmap(QPixmap())
        self.canvas._overlay_item.setPixmap(QPixmap())
        self.status_label.setText("اختر صفًا من الجدول لبدء التحرير")

    def has_image(self) -> bool:
        return self._original is not None

    def has_edits(self) -> bool:
        """هل أجرى المستخدم أي تعديل منذ تحميل الصورة؟"""
        if self._original is None:
            return False
        if self._history:
            return True
        if self._cutout_applied or self._shadow_opts is not None:
            return True
        if self._sliders_active():
            return True
        if self.rotate_slider.value() != 0:
            return True
        if self.glare_enable_cb.isChecked() or self.polish_enable_cb.isChecked():
            return True
        return False

    def get_result_bgr(self) -> "np.ndarray | None":
        """الناتج النهائي BGR (خلفية بيضاء مسطحة) للحفظ المباشر."""
        if self._composited is None and self._original is not None:
            self._recompose()
        return None if self._composited is None else self._composited.copy()

    # تجاوز إغلاق الحوار الموروث — الودجت المدمج لا يُغلق بـ ESC
    def reject(self) -> None:  # noqa: D102
        pass

    def accept(self) -> None:  # noqa: D102
        pass
