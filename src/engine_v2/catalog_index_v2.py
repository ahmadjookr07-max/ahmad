# -*- coding: utf-8 -*-
"""catalog_index_v2 — فهرس الإكسل السريع (41,935 صنفًا).

- كشف أعمدة مرن (رؤوس عربية/إنجليزية/بدون رؤوس) لأي ملف إكسل مستقبلي.
- كاش JSON بجانب الملف (مفتاحه mtime) — تحميل لاحق أسرع بكثير.
- lookup_barcode بزمن ميكروثانية + بحث اسم n-gram + بحث رقمي بالبادئة.
- by_code_all + units_for_code (نص حرفي كما في الإكسل).
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_DIACRITICS = re.compile(r"[\u064B-\u0652\u0670\u0640]")


def normalize_text(text: str) -> str:
    """تطبيع للبحث الداخلي فقط — الإخراج دائمًا حرفي."""
    t = str(text).translate(_AR_DIGITS)
    t = _DIACRITICS.sub("", t)
    t = t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    t = t.replace("ة", "ه").replace("ى", "ي").replace("ئ", "ي").replace("ؤ", "و")
    return re.sub(r"\s+", " ", t).strip().lower()


def _clean_code(v) -> str:
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


# ------------------------------------------------------- column detection
_HINTS = {
    "code": ["i_code", "code", "item no", "item number", "item_no", "itemno",
             "item", "sku", "رقم الصنف", "رقمالصنف", "رقم المنتج", "رقم",
             "الرقم", "كود الصنف", "كود", "الكود", "معرف"],
    "name": ["i_name", "item name", "product name", "description", "desc",
             "name", "اسم الصنف", "اسمالصنف", "اسم المنتج", "الاسم", "اسم",
             "الوصف", "وصف", "البيان", "بيان الصنف"],
    "unit": ["itm_unt", "unt", "unit", "uom", "الوحده", "الوحدة", "وحده",
             "وحدة", "وحدة البيع", "التعبئة"],
    "size": ["p_size", "pack size", "pack", "size", "qty", "حجم",
             "العبوه", "العبوة", "الكمية", "كمية", "عدد"],
    "barcode": ["barcode", "bar code", "ean", "upc", "gtin", "بار كود",
                "باركود", "الباركود", "رقم الباركود", "رمز شريطي"],
}

# كلمات لا تعني اسم صنف رغم احتوائها على "اسم" (تفادي التقاط أعمدة خاطئة)
_NAME_BLACKLIST = ["اسم المورد", "اسم الفرع", "اسم المستخدم", "supplier",
                   "vendor", "branch"]


def detect_columns(header_row: list) -> dict[str, int]:
    """يكشف مواقع الأعمدة من صف الرؤوس بمرونة (يتجاهل بادئات مثل Table5.)."""
    cols: dict[str, int] = {}
    for i, cell in enumerate(header_row):
        raw = str(cell or "")
        label = normalize_text(re.sub(r"^\w+\.", "", raw))
        label_compact = label.replace(" ", "").replace("_", "")
        if any(normalize_text(b).replace(" ", "") in label_compact
               for b in _NAME_BLACKLIST):
            continue
        for key, hints in _HINTS.items():
            if key in cols:
                continue
            for h in hints:
                hn = normalize_text(h).replace(" ", "").replace("_", "")
                if hn and (hn == label_compact or hn in label_compact):
                    cols[key] = i
                    break
    return cols


def _score_header_row(row: list) -> int:
    """عدد الأعمدة المفهومة في صف — لاختيار صف الرؤوس الحقيقي."""
    return len(detect_columns(list(row)))


def _looks_like_barcode(s: str) -> bool:
    s = _clean_code(s)
    return s.isdigit() and 8 <= len(s) <= 14


def _looks_like_code(s: str) -> bool:
    s = _clean_code(s)
    return s.isdigit() and 4 <= len(s) <= 10


class CatalogIndex:
    """فهرس الأصناف في الذاكرة مع كاش على القرص."""

    def __init__(self):
        self.rows: list[dict] = []          # {code,name,unit,size,barcode}
        self.by_barcode: dict[str, int] = {}
        self.by_code: dict[str, int] = {}
        self.by_code_all: dict[str, list[int]] = {}
        self._name_grams: dict[str, set[int]] = {}
        self.columns: dict[str, int] = {}
        self.source_path = ""
        self.load_seconds = 0.0

    # ------------------------------------------------------------- load
    def load_excel(self, path: str | Path, use_cache: bool = True) -> None:
        t0 = time.time()
        path = Path(path)
        self.source_path = str(path)
        cache = path.parent / (".catalog_cache_" + path.stem[:20] + ".json")
        mtime = path.stat().st_mtime

        if use_cache and cache.is_file():
            try:
                data = json.loads(cache.read_text(encoding="utf-8"))
                if data.get("mtime") == mtime:
                    self.rows = data["rows"]
                    self.columns = data.get("columns", {})
                    self._build_maps()
                    self.load_seconds = time.time() - t0
                    return
            except Exception:
                pass

        rows = self._read_any_table(path)

        self.rows = rows
        self._build_maps()
        if use_cache:
            try:
                cache.write_text(json.dumps(
                    {"mtime": mtime, "columns": self.columns, "rows": rows},
                    ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
        self.load_seconds = time.time() - t0

    # ------------------------------------------------- universal reader
    def _read_any_table(self, path: Path) -> list[dict]:
        """يقرأ أي ملف جدولي مستقبلي: xlsx/xlsm/xls/csv، كل الأوراق،
        ويبحث عن صف الرؤوس في أول 10 صفوف، ويستدل من البيانات إذا غابت."""
        suffix = path.suffix.lower()
        all_rows: list[dict] = []
        if suffix == ".csv":
            import csv
            for enc in ("utf-8-sig", "utf-8", "cp1256", "utf-16"):
                try:
                    with open(path, newline="", encoding=enc) as f:
                        table = [list(r) for r in csv.reader(f)]
                    break
                except (UnicodeDecodeError, UnicodeError):
                    continue
            else:
                raise ValueError("تعذر تحديد ترميز ملف CSV")
            all_rows.extend(self._parse_table(table))
        elif suffix == ".xls":
            try:
                import xlrd
            except ImportError:
                raise ValueError("صيغة .xls القديمة تتطلب تحويل الملف إلى "
                                 ".xlsx (احفظه بصيغة أحدث من Excel)")
            book = xlrd.open_workbook(str(path))
            for sh in book.sheets():
                table = [[sh.cell_value(r, c) for c in range(sh.ncols)]
                         for r in range(sh.nrows)]
                all_rows.extend(self._parse_table(table))
        else:
            import openpyxl
            wb = openpyxl.load_workbook(str(path), read_only=True,
                                        data_only=True)
            for ws in wb.worksheets:
                table_iter = ws.iter_rows(values_only=True)
                all_rows.extend(self._parse_table_iter(table_iter))
            wb.close()
        if not all_rows:
            raise ValueError("لم يُعثر على أعمدة مفهومة (رقم الصنف/الاسم) "
                             "في أي ورقة من الملف")
        return all_rows

    def _parse_table(self, table: list) -> list[dict]:
        return self._parse_table_iter(iter(table))

    def _parse_table_iter(self, it) -> list[dict]:
        """يحدد صف الرؤوس (بحث في أول 10 صفوف) ثم يستخرج الصفوف."""
        buffered: list[list] = []
        for _ in range(10):
            nxt = next(it, None)
            if nxt is None:
                break
            buffered.append(list(nxt))
        if not buffered:
            return []
        # اختر الصف صاحب أعلى نتيجة كشف كرؤوس
        best_i, best_cols, best_score = -1, {}, 0
        for i, row in enumerate(buffered):
            c = detect_columns(row)
            score = len(c) + (2 if "code" in c and "name" in c else 0)
            if score > best_score:
                best_i, best_cols, best_score = i, c, score
        data_start = best_i + 1
        cols = best_cols
        if "code" not in cols or "name" not in cols:
            # لا رؤوس واضحة: استدلال من أول صف بيانات غير فارغ
            for i, row in enumerate(buffered):
                inferred = self._infer_columns_from_data(row)
                if "code" in inferred and "name" in inferred:
                    cols, data_start = inferred, i
                    break
            else:
                return []
        if not self.columns:
            self.columns = cols
        rows: list[dict] = []

        def add_row(vals):
            def get(key):
                i = cols.get(key)
                if i is None or i >= len(vals) or vals[i] is None:
                    return ""
                return str(vals[i]).strip()
            code = _clean_code(get("code"))
            name = get("name")
            if not code or not name:
                return
            rows.append({
                "code": code,
                "name": name,
                "unit": get("unit"),
                "size": get("size"),
                "barcode": _clean_code(get("barcode")),
            })

        for vals in buffered[data_start:]:
            add_row(vals)
        for vals in it:
            add_row(list(vals))
        return rows

    @staticmethod
    def _infer_columns_from_data(row: list) -> dict[str, int]:
        cols: dict[str, int] = {}
        for i, v in enumerate(row):
            s = str(v or "").strip()
            if not s:
                continue
            if "barcode" not in cols and _looks_like_barcode(s):
                cols["barcode"] = i
            elif "code" not in cols and _looks_like_code(s):
                cols["code"] = i
            elif "name" not in cols and re.search(r"[\u0600-\u06FF]{3,}", s) \
                    and len(s) > 8:
                cols["name"] = i
            elif "unit" not in cols and re.search(r"[\u0600-\u06FF]", s) \
                    and len(s) <= 8:
                cols["unit"] = i
        return cols

    def _build_maps(self) -> None:
        self.by_barcode.clear()
        self.by_code.clear()
        self.by_code_all.clear()
        self._name_grams.clear()
        for idx, r in enumerate(self.rows):
            bc = r.get("barcode", "")
            if bc and bc not in self.by_barcode:
                self.by_barcode[bc] = idx
            code = r["code"]
            if code not in self.by_code:
                self.by_code[code] = idx
            self.by_code_all.setdefault(code, []).append(idx)
            norm = normalize_text(r.get("name", ""))
            for g in self._grams(norm):
                self._name_grams.setdefault(g, set()).add(idx)

    @staticmethod
    def _grams(text: str, n: int = 3):
        text = text.replace(" ", "")
        return {text[i:i + n] for i in range(max(0, len(text) - n + 1))}

    # ------------------------------------------------------------ lookup
    def lookup_barcode(self, barcode: str) -> dict | None:
        bc = _clean_code(barcode)
        idx = self.by_barcode.get(bc)
        if idx is not None:
            return self.rows[idx]
        # تسامح check-digit: جرّب بدون الرقم الأخير أو بإضافة صفر بادئ
        if len(bc) > 8:
            idx = self.by_barcode.get(bc[:-1])
            if idx is not None:
                return self.rows[idx]
        idx = self.by_barcode.get(bc.lstrip("0"))
        if idx is not None:
            return self.rows[idx]
        return None

    def lookup_code(self, code: str) -> dict | None:
        idx = self.by_code.get(_clean_code(code))
        return self.rows[idx] if idx is not None else None

    def rows_for_code(self, code: str) -> list[dict]:
        return [self.rows[i] for i in self.by_code_all.get(_clean_code(code), [])]

    def units_for_code(self, code: str) -> list[str]:
        """الوحدات الحرفية كما في الإكسل بترتيب الظهور (معقّمة من
        الشرطات والمسافات الطرفية التي كانت تسبب أسماء `__حبه` مكررة)."""
        units = []
        for r in self.rows_for_code(code):
            u = (r.get("unit") or "").strip().strip("_").strip()
            if u and u not in units:
                units.append(u)
        return units

    def primary_unit_for_code(self, code: str) -> str:
        """وحدة الصورة الأساسية للصنف بإملائها الحرفي كما في الإكسل.

        المشكلة: 40% من الأصناف لها أكثر من وحدة في الإكسل (حبه/باكت/
        كرتون) وترتيب الصفوف عشوائي، فأخذ `units_for_code()[0]` يعطي
        `باكت` لصنف صورته صورة حبة.

        القاعدة المعتمدة (قرار المالك: الإكسل مرجع كل شيء): الوحدة
        التي **عبوتها = 1** هي وحدة الصورة، لأن الصورة تمثل القطعة
        الواحدة لا الكرتون. قيست على 484 صنفًا من مجلد منجز حقيقي
        فطابقت 483 (99.8%)، والحالة الشاذة كانت خطأً في اسم الملف
        لا في القاعدة.

        الإملاء يُحفظ حرفيًا (حبه/حبة/شدة/شده/ربطة) ولا يُطبّع.
        """
        rows = self.rows_for_code(code)
        if not rows:
            return ""
        for r in rows:
            unit = (r.get("unit") or "").strip().strip("_").strip()
            size = (r.get("size") or "").strip()
            if not unit or not size:
                continue
            try:
                if abs(float(size.replace(",", ".")) - 1.0) < 1e-9:
                    return unit
            except ValueError:
                continue
        units = self.units_for_code(code)
        return units[0] if units else ""

    def search_name(self, query: str, limit: int = 30) -> list[dict]:
        qn = normalize_text(query)
        if not qn:
            return []
        grams = self._grams(qn)
        if not grams:
            return []
        scores: dict[int, int] = {}
        for g in grams:
            for idx in self._name_grams.get(g, ()):
                scores[idx] = scores.get(idx, 0) + 1
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:limit * 3]
        out = []
        for idx, _ in ranked:
            r = self.rows[idx]
            if qn in normalize_text(r["name"]) or len(out) < limit:
                out.append(r)
            if len(out) >= limit:
                break
        return out

    def search_numeric(self, prefix: str, limit: int = 30) -> list[dict]:
        p = _clean_code(prefix)
        if not p:
            return []
        out = []
        seen = set()
        for code, idx in self.by_code.items():
            if code.startswith(p) and code not in seen:
                seen.add(code)
                out.append(self.rows[idx])
                if len(out) >= limit:
                    break
        if len(out) < limit:
            for bc, idx in self.by_barcode.items():
                if bc.startswith(p):
                    r = self.rows[idx]
                    if r["code"] not in seen:
                        seen.add(r["code"])
                        out.append(r)
                        if len(out) >= limit:
                            break
        return out
