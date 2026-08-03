# -*- coding: utf-8 -*-
"""awareness_ui — واجهة الوعي داخل التطبيق.

تعرض ما يعرفه البرنامج عن نفسه وتمنح المستخدم قناة حوار مباشرة معه:

* **شارة الوعي** في صف الأدوات: لون ونسبة صحة تتحدّث ذاتيًا، وتفتح اللوحة.
* **لوحة الوعي** (نافذة غير معيقة) بخمسة تبويبات: مَن أنا، صحّتي،
  حوار، أدائي، وسجل التغييرات.
* **تنبيهات ذكية**: البرنامج يخبر المستخدم بما أصلحه بنفسه بدل أن يصمت.

قاعدة حاكمة: هذه الوحدة **لا يجوز أن تُسقط التطبيق**. كل استيراد وكل
اتصال بطبقة الوعي محاط بحماية، وإن غابت الطبقة تُعرض رسالة مهذّبة.
"""
from __future__ import annotations

import contextlib
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
for _p in (str(_SRC), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PySide6.QtCore import Qt, QObject, Signal, QTimer          # noqa: E402
from PySide6.QtGui import QFont                                  # noqa: E402
from PySide6.QtWidgets import (                                   # noqa: E402
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTabWidget,
    QTextEdit, QLineEdit, QWidget, QMessageBox, QProgressBar, QScrollArea,
    QFrame, QTableWidget, QTableWidgetItem, QHeaderView,
)

_core = None
with contextlib.suppress(Exception):
    from awareness import core as _core          # type: ignore

AWARENESS_READY = _core is not None


# ════════════════════════ جسر الإشارات ════════════════════════
# طبقة الوعي تُبلّغ من خيوط خلفية؛ ولمس عناصر Qt من خيط غير خيط الواجهة
# يُسقط التطبيق. لذا كل حدث يمر عبر Signal لينفّذ في خيط الواجهة.

class _Bridge(QObject):
    event = Signal(str, dict)


_BRIDGE = _Bridge()


def _on_awareness_event(name: str, payload: dict) -> None:
    with contextlib.suppress(Exception):
        _BRIDGE.event.emit(str(name), dict(payload or {}))


# ════════════════════════ عناصر مساعدة ════════════════════════

def _score_color(score: int) -> str:
    if score >= 90:
        return "#1a7f37"        # أخضر: سليم
    if score >= 70:
        return "#9a6700"        # كهرماني: يعمل بنقص
    if score >= 40:
        return "#bc4c00"        # برتقالي: متدهور
    return "#b91c1c"            # أحمر: الهدف متوقف


def _score_word(score: int) -> str:
    if score >= 90:
        return "سليم"
    if score >= 70:
        return "يعمل بنقص"
    if score >= 40:
        return "متدهور"
    return "يحتاج تدخلًا"


def _mono(widget) -> None:
    f = QFont("Consolas" if sys.platform == "win32" else "monospace")
    f.setPointSize(10)
    widget.setFont(f)


class _Section(QFrame):
    """بطاقة عنوان + محتوى نصي — تُستخدم في تبويب «مَن أنا»."""

    def __init__(self, title: str, body: str, parent=None):
        super().__init__(parent)
        self.setObjectName("awSection")
        self.setStyleSheet(
            "#awSection{background:#fbfbfd;border:1px solid #e3e3ea;"
            "border-radius:8px;} QLabel{background:transparent;}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        head = QLabel(title)
        head.setStyleSheet("font-weight:700;font-size:13px;color:#1f2328;")
        lay.addWidget(head)
        txt = QLabel(body)
        txt.setWordWrap(True)
        txt.setTextInteractionFlags(Qt.TextSelectableByMouse)
        txt.setStyleSheet("font-size:12px;color:#3c4149;line-height:150%;")
        lay.addWidget(txt)


# ════════════════════════ لوحة الوعي ════════════════════════

class AwarenessPanel(QDialog):
    """نافذة الوعي: يفهم البرنامج نفسه ويشرحها، ويستقبل أوامر المستخدم."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("وعي البرنامج — يعرف نفسه ويصلح نفسه")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setModal(False)                       # لا يعيق العمل
        self.resize(760, 620)
        self._pending: dict | None = None          # طلب ينتظر تأكيدًا

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ── رأس: درجة الصحة ──
        head = QHBoxLayout()
        self.score_lbl = QLabel("…")
        self.score_lbl.setStyleSheet("font-size:15px;font-weight:700;")
        head.addWidget(self.score_lbl)
        head.addStretch(1)
        self.refresh_btn = QPushButton("افحص نفسك الآن")
        self.refresh_btn.setMinimumHeight(34)
        self.refresh_btn.clicked.connect(self._deep_scan)
        head.addWidget(self.refresh_btn)
        self.heal_btn = QPushButton("أصلح ما تجده")
        self.heal_btn.setMinimumHeight(34)
        self.heal_btn.clicked.connect(self._heal_now)
        head.addWidget(self.heal_btn)
        root.addLayout(head)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        root.addWidget(self.bar)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self._build_identity_tab()
        self._build_health_tab()
        self._build_dialogue_tab()
        self._build_perf_tab()
        self._build_changes_tab()

        _BRIDGE.event.connect(self._on_event)
        self.refresh()

    # ── تبويب: مَن أنا ──
    def _build_identity_tab(self) -> None:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        self._id_layout = QVBoxLayout(host)
        self._id_layout.setContentsMargins(4, 4, 4, 4)
        self._id_layout.setSpacing(10)
        area.setWidget(host)
        self.tabs.addTab(area, "مَن أنا")

    # ── تبويب: صحّتي ──
    def _build_health_tab(self) -> None:
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(4, 4, 4, 4)
        self.health_txt = QTextEdit()
        self.health_txt.setReadOnly(True)
        _mono(self.health_txt)
        lay.addWidget(self.health_txt)
        row = QHBoxLayout()
        self.improve_btn = QPushButton("حسّن نفسك (تجربة مقيسة)")
        self.improve_btn.setMinimumHeight(34)
        self.improve_btn.setToolTip(
            "يجرّب تعديلًا على معاملاته ويقيس أثره فعليًا: يُثبته إن تحسّن "
            "ويتراجع عنه إن ضرّ")
        self.improve_btn.clicked.connect(self._self_improve)
        row.addWidget(self.improve_btn)
        self.surgery_btn = QPushButton("دقّق بنيتك البرمجية")
        self.surgery_btn.setMinimumHeight(34)
        self.surgery_btn.setToolTip(
            "يفحص شفرته بحثًا عن مواضع ضعف (أخطاء مكتومة، ترميز، هشاشة) "
            "ويقترح رقعًا مُتحقَّقًا منها")
        self.surgery_btn.clicked.connect(self._audit_code)
        row.addWidget(self.surgery_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.tabs.addTab(host, "صحّتي")

    # ── تبويب: حوار ──
    def _build_dialogue_tab(self) -> None:
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(8)

        hint = QLabel(
            "اكتب ما تريد بلغتك العادية — أفهم قصدك وأعدّل نفسي عليه.\n"
            "أمثلة: «الصور تطلع مشوشه» · «خل الجوده 95» · «سرّع المعالجة» · "
            "«الخط صغير ما اشوفه» · «رجّع آخر تعديل» · «وش تعرف عن نفسك»")
        hint.setWordWrap(True)
        hint.setStyleSheet(
            "background:#f0f6ff;border:1px solid #cfe0ff;border-radius:8px;"
            "padding:10px;font-size:12px;color:#24406e;")
        lay.addWidget(hint)

        self.chat = QTextEdit()
        self.chat.setReadOnly(True)
        self.chat.setStyleSheet("font-size:13px;line-height:165%;")
        lay.addWidget(self.chat, 1)

        row = QHBoxLayout()
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("اكتب طلبك هنا ثم اضغط Enter…")
        self.entry.setMinimumHeight(38)
        self.entry.setStyleSheet("font-size:13px;padding:4px 8px;")
        self.entry.returnPressed.connect(self._send)
        row.addWidget(self.entry, 1)
        send = QPushButton("أرسل")
        send.setMinimumHeight(38)
        send.setMinimumWidth(90)
        send.clicked.connect(self._send)
        row.addWidget(send)
        lay.addLayout(row)

        self._confirm_row = QWidget()
        crow = QHBoxLayout(self._confirm_row)
        crow.setContentsMargins(0, 0, 0, 0)
        self._confirm_lbl = QLabel("")
        self._confirm_lbl.setWordWrap(True)
        self._confirm_lbl.setStyleSheet(
            "color:#8a4b00;font-size:12px;font-weight:600;")
        crow.addWidget(self._confirm_lbl, 1)
        yes = QPushButton("نفّذ")
        yes.setMinimumHeight(32)
        yes.clicked.connect(self._confirm_yes)
        crow.addWidget(yes)
        no = QPushButton("إلغاء")
        no.setMinimumHeight(32)
        no.clicked.connect(self._confirm_no)
        crow.addWidget(no)
        self._confirm_row.setVisible(False)
        lay.addWidget(self._confirm_row)

        self.tabs.addTab(host, "حوار")
        self._say("brain", "أنا جاهز. اسألني عن نفسي أو أخبرني بما تريد تغييره.")

    # ── تبويب: أدائي ──
    def _build_perf_tab(self) -> None:
        """يعرض أين يضيع الزمن فعليًا وما ينوي البرنامج فعله.

        الترتيب بالزمن الكلي لا بالمتوسط، لأن خطوة تأخذ 20ms
        وتُنادى 300 مرة أسوأ من خطوة تأخد 2s مرة واحدة.
        """
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(8)

        self.perf_head = QLabel("لم أقِس عملًا كافيًا بعد.")
        self.perf_head.setWordWrap(True)
        self.perf_head.setStyleSheet("font-size:12px;color:#4b5563;")
        lay.addWidget(self.perf_head)

        self.perf_tbl = QTableWidget(0, 5)
        self.perf_tbl.setHorizontalHeaderLabels(
            ["الخطوة", "المجموع", "المتوسط", "أسوأ 5%", "مرات"])
        self.perf_tbl.verticalHeader().setVisible(False)
        self.perf_tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        self.perf_tbl.setSelectionMode(QTableWidget.NoSelection)
        self.perf_tbl.setAlternatingRowColors(True)
        hh = self.perf_tbl.horizontalHeader()
        hh.setStretchLastSection(False)
        with contextlib.suppress(Exception):
            hh.setSectionResizeMode(0, QHeaderView.Stretch)
            for c in range(1, 5):
                hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.perf_tbl.setMaximumHeight(240)
        lay.addWidget(self.perf_tbl)

        adv_lbl = QLabel("توصياتي مبنية على القياس:")
        adv_lbl.setStyleSheet("font-weight:700;")
        lay.addWidget(adv_lbl)
        self.perf_advice = QTextEdit()
        self.perf_advice.setReadOnly(True)
        _mono(self.perf_advice)
        lay.addWidget(self.perf_advice, 1)

        row = QHBoxLayout()
        base_btn = QPushButton("اعتمد أدائي الحالي أساسًا")
        base_btn.setMinimumHeight(34)
        base_btn.setToolTip(
            "يحفظ الأزمنة الحالية مرجعًا؛ فإن تباطأت لاحقًا أكثر من "
            "المسموح أنبهتُك إلى الارتداد")
        base_btn.clicked.connect(self._promote_baseline)
        row.addWidget(base_btn)
        ref_btn = QPushButton("حدِّث القياس")
        ref_btn.setMinimumHeight(34)
        ref_btn.clicked.connect(self._refresh_perf)
        row.addWidget(ref_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.tabs.addTab(host, "أدائي")

    # ── تبويب: سجل التغييرات ──
    def _build_changes_tab(self) -> None:
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(4, 4, 4, 4)
        self.changes_txt = QTextEdit()
        self.changes_txt.setReadOnly(True)
        _mono(self.changes_txt)
        lay.addWidget(self.changes_txt)
        row = QHBoxLayout()
        undo = QPushButton("تراجع عن آخر تعديل")
        undo.setMinimumHeight(34)
        undo.clicked.connect(self._undo_last)
        row.addWidget(undo)
        row.addStretch(1)
        lay.addLayout(row)
        self.tabs.addTab(host, "ما غيّرته")

    # ═══════════════ منطق العرض ═══════════════

    def refresh(self) -> None:
        if not AWARENESS_READY:
            self.score_lbl.setText("طبقة الوعي غير متاحة في هذه النسخة")
            return
        card: dict = {}
        with contextlib.suppress(Exception):
            card = _core.introspect()
        st = card.get("state") or {}
        score = int(st.get("health_score") or 0)
        self._set_score(score)
        self._fill_identity(card)
        self._fill_health(card)
        self._fill_perf(card)
        self._fill_changes(card)

    def _set_score(self, score: int) -> None:
        color = _score_color(score)
        self.score_lbl.setText(
            f"صحّتي الآن {score}/100 — {_score_word(score)}")
        self.score_lbl.setStyleSheet(
            f"font-size:15px;font-weight:700;color:{color};")
        self.bar.setValue(score)
        self.bar.setStyleSheet(
            "QProgressBar{background:#eceef2;border:none;border-radius:4px;}"
            f"QProgressBar::chunk{{background:{color};border-radius:4px;}}")

    def _fill_identity(self, card: dict) -> None:
        while self._id_layout.count():
            it = self._id_layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        text = str(card.get("identity_ar") or "").strip()
        if text:
            self._id_layout.addWidget(_Section("تعريفي بنفسي", text))
        caps = card.get("capabilities") or []
        if caps:
            lines = []
            for c in caps[:40]:
                if isinstance(c, dict):
                    nm = c.get("title_ar") or c.get("key") or "?"
                    ok = c.get("available")
                    mark = "متاحة" if ok else "غير متاحة"
                    lines.append(f"• {nm} — {mark}")
                else:
                    lines.append(f"• {c}")
            self._id_layout.addWidget(
                _Section("قدراتي وحالتها الآن", "\n".join(lines)))
        kn = card.get("knowledge") or {}
        if kn:
            body = (
                f"حوادث تعلّمت منها: {kn.get('incidents', 0)}\n"
                f"أعطال متكررة أعرفها مسبقًا: {kn.get('recurring', 0)}\n"
                f"أعطال حللتها نهائيًا: {kn.get('resolved', 0)}\n"
                f"علاجات جرّبتها: {kn.get('remedies', 0)} "
                f"(نجح منها {kn.get('successful_remedies', 0)})\n"
                f"استنتاجات مخزّنة: {kn.get('insights', 0)}")
            self._id_layout.addWidget(_Section("سجلي الأكاشي — خبرتي", body))
        self._id_layout.addStretch(1)

    def _fill_health(self, card: dict) -> None:
        st = card.get("state") or {}
        out = [f"درجة الصحة: {st.get('health_score', '?')}/100",
               f"إصدار التطبيق: {st.get('version', '?')}",
               f"أعطال رأيتها هذه الجلسة: {st.get('exceptions_seen', 0)}",
               f"مشاكل أصلحتها بنفسي: {st.get('healed', 0)}"]
        dis = st.get("disabled") or {}
        if dis:
            out.append("")
            out.append("قدرات معطّلة الآن وسببها:")
            for k, v in dis.items():
                out.append(f"  - {k}: {v}")
        else:
            out.append("")
            out.append("لا توجد قدرة معطّلة — كل شيء يعمل.")
        msgs = st.get("messages") or []
        if msgs:
            out.append("")
            out.append("ما أريد أن أخبرك به:")
            out.extend(f"  • {m}" for m in msgs[-6:])
        opt = card.get("optimizer") or {}
        recs = opt.get("recommendations") or []
        if recs:
            out.append("")
            out.append("تحسينات أراها مفيدة:")
            out.extend(f"  • {r}" for r in recs[:6])
        self.health_txt.setPlainText("\n".join(out))

    def _fill_perf(self, card: dict) -> None:
        """يحوّل أرقام محرك الأداء إلى جدول ونصّ يفهمهما غير المبرمج."""
        p = card.get("perf") or {}
        summ = p.get("summary") or {}
        spots = p.get("hotspots") or []
        advice = p.get("advice") or []

        calls = int(summ.get("calls") or 0)
        if calls:
            total_s = float(summ.get("total_ms") or 0) / 1000.0
            errs = int(summ.get("errors") or 0)
            head = (f"راقبتُ {summ.get('segments', 0)} خطوة عبر {calls} "
                    f"نداء، بمجموع زمن {total_s:.1f} ثانية.")
            if errs:
                head += f" وقع فيها {errs} خطأ."
            self.perf_head.setText(head)
        else:
            self.perf_head.setText(
                "لم أقِس عملًا كافيًا بعد — عالِج بعض الصور ثم عُد إلى هنا.")

        self.perf_tbl.setRowCount(len(spots))
        for r, s in enumerate(spots):
            if not isinstance(s, dict):
                continue
            base = s.get("baseline_ms")
            mean = float(s.get("mean_ms") or 0)
            cells = [
                str(s.get("name") or "؟"),
                f"{float(s.get('total_ms') or 0) / 1000:.2f}s",
                f"{mean:.0f}ms",
                f"{float(s.get('p95_ms') or 0):.0f}ms",
                str(s.get("count") or 0),
            ]
            for c, txt in enumerate(cells):
                item = QTableWidgetItem(txt)
                if c:
                    item.setTextAlignment(Qt.AlignCenter)
                # تلوين الارتداد: أبطأ من الأساس المعتمد بـً25%+
                if base and mean > float(base) * 1.25:
                    item.setForeground(Qt.red)
                    item.setToolTip(
                        f"كان {float(base):.0f}ms وأصبح {mean:.0f}ms — تباطأ")
                self.perf_tbl.setItem(r, c, item)

        if advice:
            lines = []
            rank = {"high": "مهم", "warn": "يُنصح", "info": "ملاحظة"}
            for a in advice[:8]:
                if not isinstance(a, dict):
                    continue
                gain = float(a.get("gain_hint_ms") or 0)
                tail = f"  (توفير متوقع ≈{gain:.0f}ms)" if gain > 1 else ""
                lines.append(
                    f"[{rank.get(a.get('severity'), 'ملاحظة')}] "
                    f"{a.get('segment', '')}\n"
                    f"    الدليل: {a.get('evidence_ar', '')}\n"
                    f"    الإجراء: {a.get('action_ar', '')}{tail}")
            self.perf_advice.setPlainText("\n\n".join(lines))
        else:
            self.perf_advice.setPlainText(
                p.get("report_ar")
                or "لا أرى اختناقًا يستحق التدخل الآن؛ أدائي في المدى المقبول.")

    def _refresh_perf(self) -> None:
        if not AWARENESS_READY:
            return
        card: dict = {}
        with contextlib.suppress(Exception):
            card = _core.introspect()
        self._fill_perf(card)

    def _promote_baseline(self) -> None:
        """يجعل القياس الحالي مرجعًا يُكتشف به التباطء مستقبلاً."""
        if not AWARENESS_READY:
            return
        n = 0
        try:
            from awareness import perf as _perf     # type: ignore
            n = int(_perf.promote_baseline())
        except Exception as exc:
            QMessageBox.warning(self, "أدائي",
                                f"تعذّر اعتماد الأساس: {exc}")
            return
        if n:
            QMessageBox.information(
                self, "أدائي",
                f"اعتمدتُ {n} خطوة أساسًا للقياس. إن تباطأت إحداها "
                "لاحقًا سأرفع لك تحذير ارتداد.")
        else:
            QMessageBox.information(
                self, "أدائي",
                "لم أجمع قياسات كافية بعد (أحتاج 3 نداءات لكل خطوة). "
                "عالِج بعض الصور ثم أعد المحاولة.")
        self._refresh_perf()

    def _fill_changes(self, card: dict) -> None:
        rows = card.get("changes") or []
        if not rows:
            self.changes_txt.setPlainText("لم أُجرِ أي تعديل على نفسي بعد.")
            return
        out = []
        for r in rows[:40]:
            if not isinstance(r, dict):
                out.append(str(r))
                continue
            when = str(r.get("at") or r.get("ts") or "")[:19]
            what = r.get("title_ar") or r.get("kind") or r.get("key") or "تعديل"
            how = r.get("message_ar") or r.get("detail") or ""
            out.append(f"[{when}] {what}\n    {how}")
        self.changes_txt.setPlainText("\n".join(out))

    # ═══════════════ أفعال ═══════════════

    def _say(self, who: str, text: str) -> None:
        if who == "user":
            html = (f'<div style="margin:6px 0;color:#0b3d91;">'
                    f'<b>أنت:</b> {text}</div>')
        elif who == "warn":
            html = (f'<div style="margin:6px 0;color:#8a4b00;">'
                    f'<b>تنبيه:</b> {text}</div>')
        else:
            html = (f'<div style="margin:6px 0;color:#1f2328;">'
                    f'<b>البرنامج:</b> {text}</div>')
        self.chat.append(html)

    def _send(self) -> None:
        text = self.entry.text().strip()
        if not text:
            return
        self.entry.clear()
        self._say("user", text)
        if not AWARENESS_READY:
            self._say("brain", "طبقة الوعي غير متاحة، فلا أستطيع تنفيذ ذلك.")
            return
        res: dict = {}
        try:
            res = _core.ask(text)
        except Exception as exc:
            self._say("warn", f"تعذّر عليّ فهم ذلك: {str(exc)[:150]}")
            return
        msg = str(res.get("message_ar") or "لم أفهم طلبك تمامًا.")
        self._say("brain", msg)
        if res.get("needs_confirmation"):
            self._pending = {"text": text}
            self._confirm_lbl.setText("هذا تعديل مؤثّر — أؤكّد قبل التنفيذ:")
            self._confirm_row.setVisible(True)
        else:
            self._pending = None
            self._confirm_row.setVisible(False)
            if res.get("applied"):
                self.refresh()

    def _confirm_yes(self) -> None:
        pend, self._pending = self._pending, None
        self._confirm_row.setVisible(False)
        if not pend:
            return
        try:
            res = _core.ask(pend["text"], confirmed=True)
        except Exception as exc:
            self._say("warn", f"تعذّر التنفيذ: {str(exc)[:150]}")
            return
        self._say("brain", str(res.get("message_ar") or "نُفّذ."))
        self.refresh()

    def _confirm_no(self) -> None:
        self._pending = None
        self._confirm_row.setVisible(False)
        self._say("brain", "حسنًا، لم أُغيّر شيئًا.")

    def _deep_scan(self) -> None:
        if not AWARENESS_READY:
            return
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("أفحص نفسي…")
        with contextlib.suppress(Exception):
            _core.deep_scan(heal=False)
        QTimer.singleShot(1200, self._scan_done)

    def _scan_done(self) -> None:
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("افحص نفسك الآن")
        self.refresh()

    def _heal_now(self) -> None:
        if not AWARENESS_READY:
            return
        self.heal_btn.setEnabled(False)
        self.heal_btn.setText("أصلح نفسي…")
        with contextlib.suppress(Exception):
            _core.deep_scan(heal=True)
        QTimer.singleShot(1500, self._heal_done)

    def _heal_done(self) -> None:
        self.heal_btn.setEnabled(True)
        self.heal_btn.setText("أصلح ما تجده")
        self.refresh()
        self.tabs.setCurrentIndex(1)

    def _self_improve(self) -> None:
        if not AWARENESS_READY:
            return
        self.improve_btn.setEnabled(False)
        try:
            res = _core.self_improve(include_code=False)
            QMessageBox.information(
                self, "تحسين ذاتي",
                str(res.get("message_ar") or "لا يوجد ما أحسّنه الآن."))
        except Exception as exc:
            QMessageBox.warning(self, "تعذّر التحسين", str(exc)[:250])
        finally:
            self.improve_btn.setEnabled(True)
            self.refresh()

    def _audit_code(self) -> None:
        if not AWARENESS_READY:
            return
        self.surgery_btn.setEnabled(False)
        try:
            res = _core.audit_code()
            msg = str(res.get("message_ar") or "لم أجد ما يستحق التعديل.")
            box = QMessageBox(self)
            box.setWindowTitle("تدقيق البنية البرمجية")
            box.setText(msg)
            box.setIcon(QMessageBox.Information)
            if res.get("patches"):
                box.setInformativeText(
                    "هذه رقع مُتحقَّق منها (نحو + استيراد + اختبارات). "
                    "لن أطبّق شيئًا دون أمرك: اكتب في تبويب الحوار "
                    "«عدّل بنيتك» لتطبيقها، ويمكنك التراجع بعدها.")
            box.exec()
        except Exception as exc:
            QMessageBox.warning(self, "تعذّر التدقيق", str(exc)[:250])
        finally:
            self.surgery_btn.setEnabled(True)

    def _undo_last(self) -> None:
        if not AWARENESS_READY:
            return
        try:
            res = _core.ask("رجّع آخر تعديل", confirmed=True)
            QMessageBox.information(
                self, "تراجع",
                str(res.get("message_ar") or "لا يوجد تعديل للتراجع عنه."))
        except Exception as exc:
            QMessageBox.warning(self, "تعذّر التراجع", str(exc)[:250])
        finally:
            self.refresh()

    # ═══════════════ أحداث طبقة الوعي ═══════════════

    def _on_event(self, name: str, payload: dict) -> None:
        if name in ("deep_scan_done", "healed", "surgery_applied",
                    "optimizer_promoted"):
            msg = str(payload.get("message_ar") or "")
            if msg:
                self._say("brain", msg)
            self.refresh()


# ════════════════════════ شارة الوعي ════════════════════════

class AwarenessBadge(QPushButton):
    """زر في صف الأدوات: نبض حالة البرنامج + مدخل لوحة الوعي."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("awarenessBadge")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(36)
        self.setToolTip(
            "وعي البرنامج: يعرف نفسه، يفحص صحّته، يصلح مشاكله بنفسه، "
            "ويفهم أوامرك بالعربية")
        self._panel: AwarenessPanel | None = None
        self.clicked.connect(self.open_panel)
        self._set_score(100 if AWARENESS_READY else 0)
        _BRIDGE.event.connect(self._on_event)
        self._timer = QTimer(self)
        self._timer.setInterval(30_000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._tick()

    def _set_score(self, score: int) -> None:
        if not AWARENESS_READY:
            self.setText("الوعي: غير متاح")
            self.setStyleSheet(
                "#awarenessBadge{color:#6b7280;border:1px solid #d1d5db;"
                "border-radius:8px;padding:4px 10px;font-weight:600;}")
            return
        color = _score_color(score)
        self.setText(f"وعي البرنامج · {score}%")
        self.setStyleSheet(
            f"#awarenessBadge{{color:{color};border:1px solid {color};"
            "border-radius:8px;padding:4px 10px;font-weight:700;"
            "background:rgba(255,255,255,0.65);}"
            f"#awarenessBadge:hover{{background:{color};color:#ffffff;}}")
        self.setMinimumWidth(
            self.fontMetrics().horizontalAdvance(self.text()) + 34)

    def _tick(self) -> None:
        if not AWARENESS_READY:
            return
        with contextlib.suppress(Exception):
            st = _core.state()
            self._set_score(int(getattr(st, "health_score", 0) or 0))

    def _on_event(self, name: str, payload: dict) -> None:
        self._tick()

    def open_panel(self) -> None:
        if self._panel is None:
            self._panel = AwarenessPanel(self.window())
        self._panel.refresh()
        self._panel.show()
        self._panel.raise_()
        self._panel.activateWindow()


# ════════════════════════ التركيب ════════════════════════

def install(window) -> bool:
    """يركّب الوعي على النافذة الرئيسية. يُرجع True إن نجح.

    التركيب متسامح: إن غابت طبقة الوعي أو تعذّر إيجاد صف الأدوات، يبقى
    التطبيق يعمل كما هو تمامًا.
    """
    if not AWARENESS_READY:
        return False
    try:
        with contextlib.suppress(Exception):
            _core.awake(deep=True, heal=True)
            _core.add_observer(_on_awareness_event)
            _core.start_pulse()

        badge = AwarenessBadge(window)
        window.awareness_badge = badge

        layout = getattr(window, "v2_toolbar_layout", None)
        placed = False
        if layout is not None:
            with contextlib.suppress(Exception):
                # قبل الـ stretch الأخير ليظهر مع بقية الأزرار
                layout.insertWidget(max(0, layout.count() - 1), badge)
                placed = True
        if not placed:
            with contextlib.suppress(Exception):
                window.statusBar().addPermanentWidget(badge)
                placed = True
        if not placed:
            badge.setParent(window)
            badge.move(12, 12)
            badge.show()

        window.awareness_open_panel = badge.open_panel

        # تنبيه أولي: إن كان البرنامج قد أصلح شيئًا عند الإقلاع فليقُلها
        def _startup_note() -> None:
            with contextlib.suppress(Exception):
                st = _core.state()
                msgs = list(getattr(st, "messages", []) or [])
                if getattr(st, "healed", 0) and msgs:
                    from PySide6.QtWidgets import QMessageBox as _QMB
                    _QMB.information(
                        window, "أصلحت نفسي قبل أن تبدأ",
                        "\n".join(msgs[:4]) +
                        "\n\nالتفاصيل في «وعي البرنامج».")
        QTimer.singleShot(4000, _startup_note)
        return True
    except Exception as exc:                        # pragma: no cover
        print(f"[AW] install failed: {exc}", file=sys.stderr)
        return False


def shutdown() -> None:
    """يُنادى عند إغلاق التطبيق: إغلاق نطيف لطبقة الوعي."""
    if AWARENESS_READY:
        with contextlib.suppress(Exception):
            _core.sleep()
