# -*- coding: utf-8 -*-
"""حارس v3.4.27: خيارات التحسين مستقلة وتحمي النصوص والباركود."""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "windows_app"), str(ROOT / "src")]
from pipeline_patch import (FinishedEnhancementOptions, _safe_complete_finished,
                            apply_finished_enhancements)

FAILS: list[str] = []


def check(condition: bool, label: str) -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        FAILS.append(label)


def product_with_hole() -> np.ndarray:
    image = np.full((260, 260, 3), 255, np.uint8)
    cv2.rectangle(image, (48, 34), (212, 225), (55, 125, 205), -1)
    image[110:142, 112:144] = 255
    return image


source = product_with_hole()
# تنظيف الحواف وحده لا يملأ فجوة، لذلك لا توجد مفاجأة عند اختيار هذا النمط.
edge_only, edge_report = apply_finished_enhancements(
    source, FinishedEnhancementOptions(add_shadow=False, repair_edges=True,
                                       repair_gaps=False, restore_texture=False,
                                       preserve_text_and_barcodes=True))
check(int(edge_only[120:132, 122:134].mean()) > 248,
      "خيار الحواف فقط لا يملأ الفجوة")
check(edge_report.get("holes", 0) == 0, "لا يسجل ترميم فجوة عند تعطيلها")

# لا يسمح بسد فجوة بلا خيار استكمال النسيج، حتى لو فُعّل خيار الفجوات وحده.
no_texture, no_texture_report = apply_finished_enhancements(
    source, FinishedEnhancementOptions(add_shadow=False, repair_edges=False,
                                       repair_gaps=True, restore_texture=False,
                                       preserve_text_and_barcodes=True))
check(int(no_texture[120:132, 122:134].mean()) > 248,
      "فجوات بلا استكمال نسيج لا تُملأ بلون مصطنع")
check(no_texture_report.get("holes", 0) == 0, "الخياران مرتبطان بأمان")

# الترميم الكامل الآمن يعيد خامة محيط منتج متجانس داخل فجوة مؤكدة.
full, full_report = apply_finished_enhancements(
    source, FinishedEnhancementOptions(add_shadow=False, repair_edges=True,
                                       repair_gaps=True, restore_texture=True,
                                       preserve_text_and_barcodes=True))
check(int(full[120:132, 122:134].mean()) < 245,
      "ترميم النسيج يصلح الفجوة المؤكدة فعليًا")
check(full_report.get("holes", 0) > 0, "يسجل مساحة الفجوة المرممة")

# منطقة تشبه نصًا/باركودًا: كثافة الحواف تمنع الإكمال عند الحماية.
text_like = product_with_hole()
# خطوط كثيفة فوق وتحت الفجوة، لكن لا تدخل داخلها؛ تحاكي كتابة/باركودًا مجاورًا.
for y in range(94, 109, 3):
    cv2.line(text_like, (94, y), (162, y), (15, 15, 15), 1)
for y in range(144, 160, 3):
    cv2.line(text_like, (94, y), (162, y), (15, 15, 15), 1)
protected, protected_report = _safe_complete_finished(
    text_like, repair_edges=True, repair_gaps=True,
    preserve_text_and_barcodes=True)
check(protected_report.get("protected", 0) >= 1 or protected_report.get("holes", 0) == 0,
      "الحماية تمنع ترميم منطقة عالية الحواف تشبه نصًا أو باركودًا")
check(int(protected[120:132, 122:134].mean()) > 248,
      "لا تتغير منطقة النص أو الباركود المحتملة")

# تحسين مظهر اختياري يغير المنتج البسيط بخفة، ولا يغير أي نص أو باركود.
plain = product_with_hole()
plain[110:142, 112:144] = (55, 125, 205)
polished, polished_report = apply_finished_enhancements(
    plain, FinishedEnhancementOptions(add_shadow=False, repair_edges=False,
                                      repair_gaps=False, restore_texture=False,
                                      preserve_text_and_barcodes=True,
                                      understand_image_type=True,
                                      enhance_product_appearance=True))
check(polished_report.get("appearance", 0) > 0 and not np.array_equal(polished, plain),
      "خيار تحسين المظهر يطبق تغييرًا بصريًا خفيفًا على منتج بسيط")

# لوحة حقائق غذائية كثيفة النص لا تُحسن بصريًا في النمط الواعي.
facts = np.full((260, 260, 3), 255, np.uint8)
cv2.rectangle(facts, (42, 34), (218, 226), (180, 190, 195), -1)
for y in range(52, 212, 9):
    cv2.line(facts, (55, y), (205, y), (20, 20, 20), 2)
for x in range(58, 210, 24):
    cv2.line(facts, (x, 48), (x, 215), (20, 20, 20), 1)
facts_out, facts_report = apply_finished_enhancements(
    facts, FinishedEnhancementOptions(add_shadow=False, repair_edges=False,
                                      repair_gaps=False, restore_texture=False,
                                      preserve_text_and_barcodes=True,
                                      understand_image_type=True,
                                      enhance_product_appearance=True))
check(facts_report.get("information_panel", 0) == 1,
      "الفهم الواعي يتعرف على لوحة معلومات كثيفة النص")
check(np.array_equal(facts_out, facts), "لوحة الحقائق تبقى بلا تحسين مظهر")

safe = FinishedEnhancementOptions.safe_all()
check(safe.add_shadow and safe.repair_edges and safe.repair_gaps and safe.restore_texture and safe.preserve_text_and_barcodes,
      "المعالجة الشاملة الآمنة تفعل كل الخيارات مع الحماية")

print("ALL:", "PASS" if not FAILS else "FAIL")
sys.exit(0 if not FAILS else 1)
