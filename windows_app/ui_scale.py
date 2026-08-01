"""2.9: محرك المقياس التلقائي الذكي — واجهة واحدة تناسب كل الشاشات.

المشكلة التي يحلها
------------------
كانت أحجام الواجهة (الخطوط، الحشوات، ارتفاعات الأزرار، أنصاف الأقطار)
مكتوبة كأرقام ثابتة بالبكسل مضبوطة على شاشة عريضة. على شاشة أصغر يقلّص Qt
عرض العنصر لكن **حجم الخط يبقى كما هو**، فلا يجد النص مكانًا فيبتره Qt
(``…``) أو يقص العنصر من الأسفل. لذلك لم يكن كافيًا منع التراكب: يجب
تصغير *كل شيء* بمعامل واحد متناسق حتى تبدو الواجهة كاملة لا مضغوطة.

كيف يعمل
--------
``ScaleEngine.for_size()`` يحسب معاملًا واحدًا من نسبة المساحة المتاحة إلى
المساحة المرجعية (1380×860 التي صُمّمت عليها الواجهة أصلًا):

* معامل العرض = العرض المتاح ÷ العرض المرجعي
* معامل الارتفاع = الارتفاع المتاح ÷ الارتفاع المرجعي
* المعامل النهائي = **أصغرهما** (فلا يفيض شيء في أي محور)، مثبّتًا بين
  ``MIN_FACTOR`` و ``MAX_FACTOR``.

الارتفاع يُوزن أقوى قليلًا لأن الازدحام العمودي (تكدّس الصفوف) هو ما يسبّب
القص الفعلي في هذا التطبيق.

ثم تُمرّر كل قيمة عبر:

* ``px()``   للأبعاد (حشوات، ارتفاعات، أنصاف أقطار) — تصغير خطي.
* ``font()`` لأحجام الخطوط — تصغير **مخفّف** (جذر المعامل) مع حد أدنى
  مقروء لكل حجم، لأن الخط أسرع فقدانًا للقراءة من المسافات. نتيجة ذلك أن
  المسافات تتقلص أولًا والخط يتبع بلطف — وهو ما يفعله المصمم البشري.

الذكاء التلقائي
---------------
لا توجد قائمة دقات ثابتة. أي حجم — بما فيه ما لم يُختبر — يُعطي معاملًا
محسوبًا. والمحرك يعيد الحساب عند كل تغيير حجم أو انتقال لشاشة أخرى، ويُبلغ
عن التغيير فقط عند تجاوز عتبة ملموسة (``_STEP``) لتجنّب إعادة التنسيق
المستمرة أثناء السحب.
"""
from __future__ import annotations

import math
import re


class ScaleEngine:
    """حاسبة معامل المقياس ومحوّل القيم — بلا أي اعتماد على Qt (قابلة للاختبار)."""

    #: المساحة المرجعية التي ضُبطت عليها الأرقام الأصلية في الأنماط
    REF_WIDTH = 1380
    REF_HEIGHT = 860

    #: حدود المعامل: لا نصغّر لدرجة تفقد القراءة، ولا نكبّر فتبدو الواجهة فجّة
    MIN_FACTOR = 0.62
    MAX_FACTOR = 1.15

    #: أصغر حجم خط مقبول للقراءة بالبكسل (قبل تحجيم نظام التشغيل)
    MIN_FONT_PX = 8

    #: عتبة إعادة التنسيق — تغيّر أصغر منها لا يستحق إعادة بناء الأنماط
    _STEP = 0.03

    def __init__(self, factor: float = 1.0) -> None:
        self.factor = self._clamp(factor)

    # ————————————————— الحساب —————————————————
    @classmethod
    def _clamp(cls, value: float) -> float:
        return max(cls.MIN_FACTOR, min(cls.MAX_FACTOR, value))

    @classmethod
    def compute_factor(cls, width: int, height: int,
                       dpi_ratio: float = 1.0) -> float:
        """المعامل الأمثل لمساحة (width × height) بمنطق ذكي لا قائمة ثابتة.

        ``dpi_ratio`` هو تحجيم نظام التشغيل (1.0 / 1.25 / 1.5 ...). كلما زاد
        صار كل بكسل منطقي أكبر فعليًا، فنقلّص المعامل بنفس النسبة حتى لا
        تفيض الواجهة على شاشات Windows المحجّمة 150%.
        """
        if width <= 0 or height <= 0:
            return 1.0
        effective_w = width / max(dpi_ratio, 0.1)
        effective_h = height / max(dpi_ratio, 0.1)
        by_width = effective_w / cls.REF_WIDTH
        by_height = effective_h / cls.REF_HEIGHT
        # الارتفاع أحرج: تكدّس الصفوف عموديًا هو مصدر القص في هذا التطبيق،
        # لذا يأخذ وزنًا أعلى في المتوسط المرجّح بعد اختيار الأصغر.
        base = min(by_width, by_height)
        weighted = (by_height * 0.62) + (by_width * 0.38)
        factor = min(base, weighted)
        return cls._clamp(round(factor, 4))

    @classmethod
    def for_size(cls, width: int, height: int,
                 dpi_ratio: float = 1.0) -> "ScaleEngine":
        return cls(cls.compute_factor(width, height, dpi_ratio))

    def differs_from(self, other_factor: float) -> bool:
        """هل الفرق يستحق إعادة تنسيق فعلية؟"""
        return abs(self.factor - other_factor) >= self._STEP

    # ————————————————— التحويل —————————————————
    def px(self, value: float, minimum: int = 1) -> int:
        """بُعد (حشوة/ارتفاع/نصف قطر) مقيس خطيًا."""
        return max(minimum, int(round(value * self.factor)))

    def gap(self, value: float) -> int:
        """تباعد بين العناصر — يُسمح له بالوصول إلى صفر على الشاشات الضيقة جدًا."""
        return max(0, int(round(value * self.factor)))

    def font(self, value: float) -> int:
        """حجم خط مقيس **بلطف**: جذر المعامل، مع أرضية قراءة.

        الجذر يعني أن معامل 0.70 للمسافات يقابل نحو 0.84 للخط، فتتقلص
        المسافات أولًا ويبقى النص مقروءًا — وهذا ما يمنع بتر الكلمات بدل
        أن يسبّبه.
        """
        eased = math.sqrt(self.factor) if self.factor < 1 else self.factor
        scaled = int(round(value * eased))
        floor = min(int(value), self.MIN_FONT_PX)
        return max(floor, scaled)

    # ————————————————— تحويل ورقة الأنماط —————————————————
    _FONT_RE = re.compile(r"font-size:\s*(\d+)px")
    _DIM_RE = re.compile(
        r"(padding|padding-top|padding-bottom|padding-left|padding-right|"
        r"margin|border-radius|min-height|max-height|min-width|max-width|"
        r"height|width):\s*([^;}]+)")
    _NUM_RE = re.compile(r"(\d+)px")

    def scale_stylesheet(self, sheet: str) -> str:
        """يمرّر ورقة أنماط Qt كاملة عبر المقياس.

        يعالج ``font-size`` بمنطق الخط اللطيف، وبقية الأبعاد خطيًا. الألوان
        وسماكات الحدود (``border: 1px solid``) تُترك كما هي: تصغير سماكة
        الحد إلى صفر يُخفي الإطارات ويُفسد الشكل.
        """
        def _font_sub(match: re.Match) -> str:
            return f"font-size: {self.font(int(match.group(1)))}px"

        def _dim_sub(match: re.Match) -> str:
            prop, body = match.group(1), match.group(2)
            new_body = self._NUM_RE.sub(
                lambda m: f"{self.px(int(m.group(1)))}px", body)
            return f"{prop}:{new_body}"

        scaled = self._FONT_RE.sub(_font_sub, sheet)
        scaled = self._DIM_RE.sub(_dim_sub, scaled)
        return scaled

    def __repr__(self) -> str:  # pragma: no cover - تشخيص فقط
        return f"ScaleEngine(factor={self.factor:.3f})"
