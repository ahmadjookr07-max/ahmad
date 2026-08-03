# -*- coding: utf-8 -*-
"""flow_layout — تخطيط ملتف خفيف بلا أي تبعية ثقيلة.

لماذا وحدة مستقلة
-----------------
كان ``_FlowLayout`` يعيش داخل ``unified_editor``، ولوحة النتائج في
``native_app`` تستورده من هناك أثناء بناء الواجهة. لكن استيراد
``unified_editor`` يجرّ ``photo_editor_v2`` ومعه ``numpy`` كاملًا،
فكان مجرّد الحاجة إلى صنف تخطيط من ~80 سطرًا يكلّف مئات المللي ثانية
قبل ظهور النافذة.

بنقل الصنف إلى هنا يعتمد على ``PySide6`` فقط (مُحمَّل أصلًا)، ويبقى
``unified_editor`` يعيد تصديره حفاظًا على أي كود أو اختبار يستورده
بالمسار القديم.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout

__all__ = ["FlowLayout"]


class FlowLayout(QLayout):
    """تخطيط أفقي يلتف تلقائيًا لسطر جديد عند ضيق المساحة (RTL).

    يمنع قص الأزرار نهائيًا على الشاشات الضيقة — ما لا يتسع في السطر
    ينزل للسطر التالي مع احترام اتجاه الواجهة العربية.
    """

    def __init__(self, parent=None, margin: int = 6, spacing: int = 5):
        super().__init__(parent)
        self._items: list = []
        self.setContentsMargins(margin, margin, margin, margin)
        self._spacing = spacing

    def addItem(self, item):  # noqa: N802
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientations(0)

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, width):  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):  # noqa: N802
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect, *, test_only: bool) -> int:
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0
        rtl = True  # التطبيق عربي — نرص من اليمين لليسار
        positions: list = []
        # 2.8: العرض المرجعي للالتفاف يجب أن يكون موجبًا دائمًا. عند أول تخطيط
        # (قبل استقرار الأب) يأتي rect بعرض صفري أو سالب فيصبح ``effective.right()``
        # أصغر من ``effective.x()``، فيفشل شرط الالتفاف ويُرصّ كل الأزرار في نقطة
        # واحدة فتتراكب فوق بعضها — وهو سبب تراكب «حقائق التغذية» مع «حفظ واعتماد».
        line_limit = max(effective.right(), effective.x())
        for item in self._items:
            hint = item.sizeHint()
            w = hint.width()
            h = hint.height()
            # عنصر أوسع من السطر كله يُقلَّص للعرض المتاح بدل أن يتجاوز الحافة
            max_w = line_limit - effective.x() + 1
            if max_w > 0 and w > max_w:
                w = max_w
            if x > effective.x() and x + w > line_limit + 1:
                x = effective.x()
                y += line_height + self._spacing
                line_height = 0
            positions.append((x, y, w, h))
            x += w + self._spacing
            line_height = max(line_height, h)
        if not test_only:
            for item, (px, py, w, h) in zip(self._items, positions):
                if rtl:
                    px = effective.right() - (px - effective.x()) - w + 1
                item.setGeometry(QRect(QPoint(px, py), QSize(w, h)))
        return y + line_height - rect.y() + m.bottom()
