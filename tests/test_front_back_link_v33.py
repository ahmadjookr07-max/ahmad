from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from engine_v2.front_back_link_v2 import (
    extract_product_ocr, extract_weight_hints, make_signature, match_product_name,
)


@dataclass
class Record:
    product_name: str
    item_code: str = ""


def run() -> None:
    excel = Path('/home/ubuntu/upload/اصنافعالمعنترة.xlsx')
    front = Path('/home/ubuntu/upload/PHOTO-2026-07-15-11-09-03.jpg')
    df = pd.read_excel(excel, dtype=str).fillna("")
    # هذه عائلة حقيقية متقاربة من ملف المستخدم؛ وجود 1 كجم و5 كجم يختبر
    # أن الوزن يمنع الربط الخطأ بين منتجين بالعلامة والنوع نفسيهما.
    sugar = df[df['اسم الصنف'].str.contains('سكر', na=False)]
    records = [Record(row['اسم الصنف'], row['رقم الصنف'])
               for _, row in sugar.iterrows()]
    image = cv2.imread(str(front))
    ocr = extract_product_ocr(image)
    # هذه صورة حقيقية ذات لمعان قوي؛ لا يلتقط OCR وزن 5 كجم بيقين.
    # السلوك الصحيح هنا هو الرفض، لا ربطها خطأ بمنتج 2 كجم أو 500 جم.
    result = match_product_name(ocr, records)
    assert not result.accepted, result
    # قراءة الوزن موضعيًا بعد تطابق الاسم الجزئي: تربط الصورة الحقيقية
    # بعبوة 5 كجم لا الصنف القريب 2 كجم.
    expected_quantities = {
        quantity for record in records
        for quantity in make_signature(record.product_name).quantities
    }
    hints = extract_weight_hints(image, expected_quantities=expected_quantities)
    result2 = match_product_name(ocr + '\n' + '\n'.join(hints), records)
    assert result2.accepted, (result2, hints)
    assert '5كجم' in result2.record.product_name.replace(' ', ''), result2
    # إدخال OCR مشوه عمدًا: يظل يقبل بسبب العلامة + النوع + الوزن.
    damaged = 'ALBAYT SUGAR سكر ابيض ناعم 5 KG سكر البيت'
    result3 = match_product_name(damaged, records)
    assert result3.accepted, result3
    # كلمة عامة منفردة لا يمكن أن تربط أي صورة.
    rejected = match_product_name('سكر', records)
    assert not rejected.accepted and 'كلمتين' in rejected.reason
    print('OK: weak OCR rejected; actual front accepted:', result2.record.product_name,
          round(result2.score, 3), result2.shared_tokens, hints)


if __name__ == '__main__':
    run()
