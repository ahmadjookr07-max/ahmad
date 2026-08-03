# -*- coding: utf-8 -*-
"""identity — نموذج الذات: من أنا، ولماذا أعمل، وما حدودي.

فلسفة الوحدة
------------
البرنامج التقليدي ينفّذ تعليمات بلا معرفة بمعناها؛ فإذا تعطّل جزء منه لم يعرف
هل تعطّل شيء جوهري أم هامشي، فيعامل كل الأخطاء سواءً. هذه الوحدة تعطي
البرنامج **نموذجًا صريحًا عن نفسه**: هدفه الأعلى، القدرات التي يملكها، تبعية
كل قدرة، وأثر تعطّلها على الهدف. ومن هذا النموذج تُشتق كل الأحكام لاحقًا:

- ``vitals`` يفحص تبعيات كل قدرة فيعرف أي قدرة معطّلة **فعلًا**.
- ``healer`` يرتّب العلاجات بأولوية أثرها على الهدف لا بترتيب ورودها.
- ``dialogue`` يربط طلب المستخدم بأقرب قدرة معروفة.
- ``introspect()`` يجيب المستخدم بالعربية: من أنا، وما حالتي، وما يعطّلني.

الوحدة **نصّية خالصة**: لا تستورد شيئًا خارج المكتبة القياسية، ولا تلمس قرصًا
ولا شبكة. هذا يجعلها آمنة للاستيراد في أي لحظة (بما فيها أثناء الإقلاع
الحسّاس للسرعة) ويجعلها الطبقة الصفرية التي تعتمد عليها بقية الوحدات.
"""
from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "APP_NAME",
    "APP_NAME_AR",
    "APP_ID",
    "AWARENESS_VERSION",
    "OWNER_NAME",
    "OWNER_EMAIL",
    "OWNER_PHONE",
    "Impact",
    "Capability",
    "SelfModel",
    "self_model",
    "app_version",
    "app_data_dir",
    "awareness_dir",
    "repo_root",
    "is_frozen",
    "runtime_facts",
    "purpose_statement",
    "describe_self",
]

# ───────────────────────── ثوابت الهوية ─────────────────────────

APP_NAME = "Ahmed Al-Faifi Market Image Studio"
APP_NAME_AR = "استوديو صور المتجر — أحمد الفيفي"
APP_ID = "AhmedAlFaifiMarketImageStudio"
AWARENESS_VERSION = "3.0.0"

OWNER_NAME = "أحمد الفيفي"
OWNER_EMAIL = "ahmadjookr06@gmail.com"
OWNER_PHONE = "0582381000"

#: الهدف الأعلى — المرجع الذي تُقاس به خطورة كل عطل.
PURPOSE = (
    "تحويل صور المنتجات الخام إلى صور كتالوج نهائية جاهزة للنشر: تُعزل خلفيتها "
    "وتُحسَّن جودتها وتُسمَّى بأرقام أصنافها المأخوذة من ملف الإكسل، بأدنى قدر من "
    "تفاعل المستخدم وبأقصى سرعة ودقة ممكنة، بحيث لا يبقى على المستخدم إلا "
    "المراجعة والاعتماد."
)

#: ما لا يفعله البرنامج — حدود معلنة تمنع «الذكاء الضار».
BOUNDARIES: tuple[str, ...] = (
    "لا يخترع قيمًا لجدول الحقائق الغذائية لم تُقرأ فعلًا من الصورة.",
    "لا يرسل صور المستخدم ولا ملفات الإكسل الخاصة به إلى أي جهة خارجية.",
    "لا يعدّل ملف الإكسل الأصلي للمستخدم؛ يقرأ منه فقط.",
    "لا يحذف صورة أصلية إلا بأمر صريح من المستخدم.",
    "لا يطبّق تعديلًا على شفرته إلا بعد تحقّق نحوي واختباري ناجح ومع نسخة تراجع.",
    "لا يرفع أي تعديل خطر (invasive) دون موافقة صريحة من المالك.",
)


class Impact:
    """أثر تعطّل القدرة على الهدف الأعلى."""

    CRITICAL = "critical"   # الهدف يتوقف تمامًا
    DEGRADED = "degraded"   # الهدف يتحقق بجودة أقل
    OPTIONAL = "optional"   # كماليات لا تمس الهدف

    ORDER = {CRITICAL: 0, DEGRADED: 1, OPTIONAL: 2}

    LABELS_AR = {
        CRITICAL: "حَرِج — الهدف يتوقف",
        DEGRADED: "منقوص — الهدف يتحقق بجودة أقل",
        OPTIONAL: "اختياري — لا يمس الهدف",
    }


@dataclass(frozen=True)
class Capability:
    """قدرة واحدة يعرف البرنامج أنه يملكها، ويعرف شرط عملها وأثر فقدها."""

    key: str
    title_ar: str
    purpose_ar: str
    module: str
    impact: str = Impact.DEGRADED
    required_packages: tuple[str, ...] = ()
    optional_packages: tuple[str, ...] = ()
    required_binaries: tuple[str, ...] = ()
    required_assets: tuple[str, ...] = ()
    fallback_ar: str = ""

    @property
    def impact_label_ar(self) -> str:
        return Impact.LABELS_AR.get(self.impact, self.impact)


# ───────────────────────── خريطة القدرات ─────────────────────────
# كل قدرة هنا تعبّر عن وظيفة حقيقية موجودة في الشفرة، مع تبعياتها الفعلية.

CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        key="read_catalog",
        title_ar="قراءة كتالوج الإكسل",
        purpose_ar="استخراج أرقام الأصناف وأسمائها ووحداتها لتسمية الصور تسمية صحيحة.",
        module="engine_v2.catalog_index_v2",
        impact=Impact.CRITICAL,
        required_packages=("openpyxl",),
        optional_packages=("xlrd",),
        fallback_ar="بلا كتالوج لا يمكن تسمية الصور بأرقام الأصناف، وهو جوهر عمل البرنامج.",
    ),
    Capability(
        key="image_io",
        title_ar="قراءة الصور وكتابتها",
        purpose_ar="فتح صور المنتجات الخام وحفظ المخرجات النهائية بصيغ JPEG وPNG وWebP.",
        module="engine_v2.processor_v2",
        impact=Impact.CRITICAL,
        required_packages=("PIL", "numpy"),
        fallback_ar="بلا قراءة الصور لا يوجد عمل أصلًا.",
    ),
    Capability(
        key="ui",
        title_ar="واجهة المستخدم",
        purpose_ar="عرض جدول المراجعة والمحرر والإعدادات للمستخدم.",
        module="windows_app.native_app",
        impact=Impact.CRITICAL,
        required_packages=("PySide6",),
        fallback_ar="بلا واجهة لا يستطيع المستخدم التعامل مع البرنامج.",
    ),
    Capability(
        key="cutout",
        title_ar="عزل الخلفية الذكي",
        purpose_ar="فصل المنتج عن خلفيته بدقة عالية ووضعه على خلفية بيضاء نظيفة.",
        module="engine_v2.segmentation_v2",
        impact=Impact.DEGRADED,
        required_packages=("cv2", "numpy"),
        optional_packages=("onnxruntime",),
        required_assets=("onnx_model",),
        fallback_ar=(
            "بلا نموذج العزل يُستخدم العزل الكلاسيكي بالعتبات اللونية: أسرع لكن "
            "أقل دقة في الحواف الشعرية والمنتجات الشفافة."
        ),
    ),
    Capability(
        key="edge_refine",
        title_ar="تنقية الحواف والظل",
        purpose_ar="إزالة الهالات وبقايا الخلفية وإضافة ظل طبيعي أسفل المنتج.",
        module="engine_v2.edge_refine_v2",
        impact=Impact.DEGRADED,
        required_packages=("cv2", "numpy"),
        fallback_ar="بدونها تظهر حواف خشنة أو هالة رمادية حول المنتج.",
    ),
    Capability(
        key="enhance",
        title_ar="التحسين التلقائي",
        purpose_ar="تصحيح السطوع والتباين والحدة وتوازن الألوان دون إفساد النصوص.",
        module="engine_v2.enhancement_v2",
        impact=Impact.DEGRADED,
        required_packages=("cv2", "numpy"),
        fallback_ar="تُسلَّم الصور بجودتها الأصلية بلا تحسين.",
    ),
    Capability(
        key="nutrition_ocr",
        title_ar="قراءة جدول الحقائق الغذائية",
        purpose_ar="قراءة قيم الجدول من الصورة وإعادة رسمه بخط عربي واضح.",
        module="engine_v2.nutrition_ocr_v2",
        impact=Impact.DEGRADED,
        required_packages=("pytesseract", "cv2"),
        required_binaries=("tesseract",),
        required_assets=("arabic_font", "tessdata_ara"),
        fallback_ar=(
            "بلا محرك Tesseract يُنقل ملصق الحقائق كما هو من الصورة الأصلية بلا "
            "إعادة رسم، ولا تُستخرج قيم رقمية."
        ),
    ),
    Capability(
        key="date_blur",
        title_ar="طمس تواريخ الإنتاج والانتهاء",
        purpose_ar="كشف التواريخ المطبوعة على العلبة وطمسها بلون العلبة نفسه.",
        module="engine_v2.date_blur_v2",
        impact=Impact.DEGRADED,
        required_packages=("cv2", "numpy"),
        optional_packages=("pytesseract",),
        required_binaries=("tesseract",),
        fallback_ar="يبقى الطمس اليدوي متاحًا من المحرر، لكن الكشف التلقائي يتوقف.",
    ),
    Capability(
        key="naming",
        title_ar="التسمية الموحدة",
        purpose_ar="تسمية كل ملف برقم الصنف ووحداته المجمّعة من الإكسل.",
        module="engine_v2.naming_v2",
        impact=Impact.CRITICAL,
        required_packages=(),
        fallback_ar="بلا التسمية الموحدة تفقد المخرجات قيمتها للمتجر.",
    ),
    Capability(
        key="visual_match",
        title_ar="المطابقة البصرية",
        purpose_ar="اقتراح الصنف المناسب لكل صورة بمقارنة بصمتها البصرية.",
        module="engine_v2.visual_match_v2",
        impact=Impact.OPTIONAL,
        required_packages=("cv2", "numpy"),
        fallback_ar="يربط المستخدم الصور بالأصناف يدويًا.",
    ),
    Capability(
        key="barcode",
        title_ar="قراءة الباركود",
        purpose_ar="قراءة باركود المنتج لمطابقته برقم الصنف تلقائيًا.",
        module="engine_v2.integration_v2",
        impact=Impact.OPTIONAL,
        optional_packages=("zxingcpp",),
        fallback_ar="تعتمد المطابقة على البصمة البصرية والاسم بدل الباركود.",
    ),
    Capability(
        key="license",
        title_ar="الترخيص والاشتراك",
        purpose_ar="التحقق من صلاحية الاشتراك وربط الجهاز بشفرة المالك.",
        module="engine_v2.license_v2",
        impact=Impact.CRITICAL,
        required_packages=("cryptography",),
        optional_packages=("dilithium_py",),
        fallback_ar=(
            "بلا مكتبة التشفير لا يمكن التحقق من الاشتراك؛ ومع فقد مكتبة PQC "
            "يعمل التحقق بالتوقيع الكلاسيكي وحده."
        ),
    ),
    Capability(
        key="owner_studio",
        title_ar="استوديو المالك",
        purpose_ar="إصدار مفاتيح الاشتراك وإدارة العملاء والأجهزة المصرَّح لها.",
        module="owner_studio.owner_studio",
        impact=Impact.OPTIONAL,
        required_packages=("tkinter",),
        optional_packages=("qrcode", "segno"),
        fallback_ar="أداة خاصة بالمالك فقط؛ تعطّلها لا يمنع المستخدم من العمل.",
    ),
    Capability(
        key="sessions",
        title_ar="الجلسات والاستئناف",
        purpose_ar="حفظ تقدّم العمل واستئناف الدفعة بعد الإغلاق أو الانقطاع.",
        module="engine_v2.session_v2",
        impact=Impact.DEGRADED,
        fallback_ar="تُفقد إمكانية الاستئناف فيلزم إعادة الدفعة من أولها.",
    ),
    Capability(
        key="learning",
        title_ar="التعلّم من المستخدم",
        purpose_ar="تعلّم تفضيلات المستخدم من تعديلاته وتطبيقها تلقائيًا لاحقًا.",
        module="engine_v2.learning_v2",
        impact=Impact.OPTIONAL,
        fallback_ar="تُستخدم الإعدادات الافتراضية بلا تخصيص.",
    ),
    Capability(
        key="self_healing",
        title_ar="الشفاء الذاتي",
        purpose_ar="كشف الأعطال وإصلاحها تلقائيًا قبل أن تصل إلى المستخدم.",
        module="awareness.healer",
        impact=Impact.DEGRADED,
        fallback_ar="تظهر الأعطال للمستخدم برسائل إرشادية بدل إصلاحها تلقائيًا.",
    ),
    Capability(
        key="self_surgery",
        title_ar="الجراحة الذاتية للشفرة",
        purpose_ar="تعديل بنية الشفرة المصدرية لإصلاح عطب بنيوي مع تحقّق وتراجع.",
        module="awareness.surgeon",
        impact=Impact.OPTIONAL,
        fallback_ar="يُصدر البرنامج تقرير رقعة موصى بها بدل تطبيقها بنفسه.",
    ),
    Capability(
        key="dialogue",
        title_ar="قناة الحوار مع المستخدم",
        purpose_ar="فهم طلب المستخدم بالعربية وتحويله إلى تعديل فعلي في البرنامج.",
        module="awareness.dialogue",
        impact=Impact.OPTIONAL,
        fallback_ar="يضبط المستخدم الإعدادات يدويًا من نوافذ الإعدادات.",
    ),
)

CAPABILITY_BY_KEY: dict[str, Capability] = {c.key: c for c in CAPABILITIES}


# ───────────────────────── حقائق التشغيل ─────────────────────────

def is_frozen() -> bool:
    """هل نعمل داخل حزمة PyInstaller؟ (تحدّد إن كانت الشفرة قابلة للتعديل)."""
    return bool(getattr(sys, "frozen", False))


def repo_root() -> Path:
    """جذر المشروع في وضع التطوير (src/awareness -> ../..)."""
    return Path(__file__).resolve().parents[2]


def app_version() -> str:
    """إصدار التطبيق من ملف VERSION، مع بديل ثابت إن غاب الملف."""
    for base in (repo_root(), Path(getattr(sys, "_MEIPASS", "") or ".")):
        try:
            f = Path(base) / "VERSION"
            if f.is_file():
                txt = f.read_text(encoding="utf-8-sig").strip()
                if txt:
                    return txt.splitlines()[0].strip()
        except Exception:
            continue
    return "3.0.0"


def app_data_dir() -> Path:
    """مجلد بيانات التطبيق — نفس مسار بقية الوحدات لتوحيد مكان الحالة.

    يطابق ``DATA_ROOT`` في ``windows_app/native_app.py`` حتى لا تتفرق حالة
    البرنامج في مسارين. ويسمح بتجاوزه عبر ``MIS_DATA_ROOT`` للاختبارات.
    """
    override = os.environ.get("MIS_DATA_ROOT", "").strip()
    if override:
        base = Path(override)
    else:
        home = Path(os.environ.get("USERPROFILE", "") or str(Path.home()))
        base = home / "Documents" / "SmartCatalogVision"
    try:
        base.mkdir(parents=True, exist_ok=True)
        return base
    except Exception:
        # آخر ملاذ: مجلد مؤقت قابل للكتابة دائمًا — لا ننهار لأن المسار محجوب.
        import tempfile
        alt = Path(tempfile.gettempdir()) / "SmartCatalogVision"
        try:
            alt.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return alt


def awareness_dir() -> Path:
    """مجلد حالة نواة الوعي (السجل، الذاكرة، نسخ الجراحة)."""
    d = app_data_dir() / "awareness"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


def runtime_facts() -> dict:
    """صورة موجزة عن بيئة التشغيل الحالية — رخيصة الحساب."""
    try:
        py = ".".join(str(x) for x in sys.version_info[:3])
    except Exception:
        py = "?"
    return {
        "app_version": app_version(),
        "awareness_version": AWARENESS_VERSION,
        "python": py,
        "platform": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "frozen": is_frozen(),
        "executable": sys.executable,
        "data_dir": str(app_data_dir()),
        "editable_source": (not is_frozen()) and (repo_root() / "src").is_dir(),
    }


@dataclass
class SelfModel:
    """نموذج الذات الكامل — يُبنى مرة ويُخزَّن."""

    name: str = APP_NAME
    name_ar: str = APP_NAME_AR
    app_id: str = APP_ID
    owner: str = OWNER_NAME
    owner_email: str = OWNER_EMAIL
    owner_phone: str = OWNER_PHONE
    purpose: str = PURPOSE
    boundaries: tuple[str, ...] = BOUNDARIES
    capabilities: tuple[Capability, ...] = CAPABILITIES
    facts: dict = field(default_factory=runtime_facts)

    # ── استعلامات ──
    def capability(self, key: str) -> Capability | None:
        return CAPABILITY_BY_KEY.get(key)

    def critical_keys(self) -> tuple[str, ...]:
        return tuple(c.key for c in self.capabilities if c.impact == Impact.CRITICAL)

    def capabilities_needing(self, package: str) -> tuple[Capability, ...]:
        """أي القدرات تعتمد على حزمة معيّنة — يُستخدم لتقدير أثر نقصها."""
        out = []
        for c in self.capabilities:
            if package in c.required_packages or package in c.optional_packages:
                out.append(c)
        return tuple(out)

    def capabilities_needing_binary(self, binary: str) -> tuple[Capability, ...]:
        return tuple(c for c in self.capabilities if binary in c.required_binaries)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "name_ar": self.name_ar,
            "app_id": self.app_id,
            "owner": self.owner,
            "contact": {"email": self.owner_email, "phone": self.owner_phone},
            "purpose": self.purpose,
            "boundaries": list(self.boundaries),
            "facts": self.facts,
            "capabilities": [
                {
                    "key": c.key,
                    "title_ar": c.title_ar,
                    "purpose_ar": c.purpose_ar,
                    "module": c.module,
                    "impact": c.impact,
                    "required_packages": list(c.required_packages),
                    "optional_packages": list(c.optional_packages),
                    "required_binaries": list(c.required_binaries),
                    "required_assets": list(c.required_assets),
                    "fallback_ar": c.fallback_ar,
                }
                for c in self.capabilities
            ],
        }


_MODEL: SelfModel | None = None


def self_model(refresh: bool = False) -> SelfModel:
    """نموذج الذات المفرد (يُبنى مرة واحدة)."""
    global _MODEL
    if _MODEL is None or refresh:
        _MODEL = SelfModel(facts=runtime_facts())
    return _MODEL


def purpose_statement() -> str:
    return PURPOSE


def describe_self() -> str:
    """بطاقة تعريف عربية موجزة — تُعرض في واجهة الوعي وتُطبع في السجل."""
    m = self_model()
    f = m.facts
    lines = [
        f"أنا {m.name_ar} — الإصدار {f['app_version']} (نواة وعي {f['awareness_version']}).",
        f"مالكي: {m.owner} · {m.owner_email} · {m.owner_phone}",
        "",
        "هدفي:",
        f"  {m.purpose}",
        "",
        f"أعمل الآن على {f['platform']} {f['release']} ({f['machine']}) "
        f"ببايثون {f['python']}"
        + (" داخل حزمة تنفيذية." if f["frozen"] else " من الشفرة المصدرية."),
        f"شفرتي {'قابلة للتعديل الذاتي.' if f['editable_source'] else 'غير قابلة للتعديل المباشر، فأعمل بوضع التوصية وطبقة تجاوزات وقت التشغيل.'}",
        f"مجلد بياناتي: {f['data_dir']}",
        "",
        f"أملك {len(m.capabilities)} قدرة معلنة، منها "
        f"{len(m.critical_keys())} قدرة حرجة لا يتحقق هدفي بدونها.",
        "",
        "حدودي التي لا أتجاوزها:",
    ]
    lines += [f"  • {b}" for b in m.boundaries]
    return "\n".join(lines)
