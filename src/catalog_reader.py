# -*- coding: utf-8 -*-
"""
Structural PDF Table Reader & Normalizer for Egyptian Wholesaler Catalogs.
Handles dynamic product-group recognition, header-fragment merging, header-only slot pruning,
geometric cell retention, page layout persistence, and group-level Arabic direction voting.
"""
from __future__ import annotations

import logging
import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

try:
    from .normalizer import (
        ARABIC_CHAR_MAP,
        EASTERN_ARABIC_DIGITS,
        FORWARD_PHARMA_TOKENS,
        REVERSED_PHARMA_TOKENS,
        REVERSED_TOKEN_MAP,
        decode_custom_catalog_glyphs,
        is_arabic_text_reversed,
        is_catalog_noise,
        normalize_arabic_text,
        parse_discount,
        parse_dosage_and_pack,
        strip_illegal_characters,
        unreverse_arabic_text,
    )
except ImportError:
    from normalizer import (
        ARABIC_CHAR_MAP,
        EASTERN_ARABIC_DIGITS,
        FORWARD_PHARMA_TOKENS,
        REVERSED_PHARMA_TOKENS,
        REVERSED_TOKEN_MAP,
        decode_custom_catalog_glyphs,
        is_arabic_text_reversed,
        is_catalog_noise,
        normalize_arabic_text,
        parse_discount,
        parse_dosage_and_pack,
        strip_illegal_characters,
        unreverse_arabic_text,
    )

logger = logging.getLogger("CatalogReader")

ALL_EASTERN_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def is_genuine_header_cell(val: Any) -> bool:
    """
    Returns True if the cell text looks like a genuine table column header label
    rather than product data (e.g. price, discount, or medicine name).
    """
    if val is None:
        return False
    s = str(val).strip()
    if not s:
        return False

    # If it contains dosage units or strength numbers, it is product data, not header
    if re.search(r'\b\d+(?:\.\d+)?\s*(?:mg|gm|g|ml|mcg|iu|%)\b', s, re.IGNORECASE):
        return False
    if re.search(r'(?<![\u0600-\u06ff])(?:مجم|جم|مل|وحدة|أقراص|كبسول|شراب|مرهم|كريم|حقن)(?![\u0600-\u06ff])', s):
        return False

    # If it's a pure number or formatted float/currency, it is price/discount, not header
    s_clean = s.translate(ALL_EASTERN_DIGITS).replace(",", ".").strip()
    if re.fullmatch(r'[-+]?\d+(?:\.\d+)?\s*%?', s_clean):
        return False

    norm = unicodedata.normalize("NFKD", s).lower().strip()
    header_exact = {
        "اسم", "إسم", "صنف", "اسم الصنف", "الصنف", "البيان", "دواء", "اسم الدواء", "مسإ", "مسا",
        "name", "item", "item name", "product", "product name", "description",
        "سعر", "السعر", "سعر الجمهور", "جمهور", "رسمي", "price", "public", "base", "base price",
        "خصم", "الخصم", "نسبة", "نسبة الخصم", "disc", "disc%", "disc %", "discount",
        "رصيد", "كمية", "الكمية", "حالة", "توفر", "متاح", "stock", "qty", "status", "avail",
        "كود", "الكود", "code", "item code", "باركود", "barcode", "مسلسل", "م", "ت", "no", "sn", "#",
        "الرقم", "رقم", "مقرلا", "مقر", "لسلسلم", "لسلم", "تسلسل", "لسلست", "دوك",
        "فنصلا", "فنصلا مسا", "رعسلا", "رعس", "مصخلا", "مصخ", "مص", "منسصالا", "فنصلفا",
        "ملاحظات", "ملاحظة", "ملاحظه", "تاظحلام", "تاظحلا", "هظحلام", "ةظحلام", "notes", "note", "remark", "remarks",
        "اجمالى", "اجمالي", "اجمالى الفاتورة", "اجمالي الفاتورة", "حساب الفاتورة", "عدد الاصناف", "عدد الأصناف",
        "صافى الفاتورة", "صافي الفاتورة", "مجموع", "المجموع"
    }
    if norm in header_exact or norm.strip(".:/\\- #") in header_exact:
        return True

    tokens = set(re.findall(r'[\w%]+', norm))
    if tokens & {"disc", "discount", "price", "item", "product", "description", "stock", "qty", "barcode", "sn", "note", "notes", "remark", "remarks"}:
        return True
    arabic_header_kws = ["اسم الصنف", "سعر الجمهور", "نسبة الخصم", "رقم الصنف", "كود الصنف", "فنصلا مسا", "روهمجلا رعس", "مصخلا ةبسن"]
    if any(k in norm for k in arabic_header_kws):
        return True
    if any(k in norm for k in ["الصنف", "البيان", "الجمهور", "الخصم", "فنصلا", "رعسلا", "مصخلا", "منسصالا", "فنصلفا"]):
        return True

    return False


@dataclass
class TableGeometry:
    """Retains structural geometry and header normalization mappings for a PDF table."""
    raw_col_count: int
    retained_cols: List[int]
    header_only_cols: Set[int]
    merge_into: Dict[int, int]
    clean_headers: List[str]
    col_bboxes: List[Optional[Tuple[float, float, float, float]]] = field(default_factory=list)
    body_cell_counts: List[int] = field(default_factory=list)

    def is_compatible(
        self,
        other_col_count: int,
        other_headers: Optional[List[str]] = None,
        other_col_bboxes: Optional[List[Optional[Tuple[float, float, float, float]]]] = None,
        sample_rows: Optional[List[List[Any]]] = None,
    ) -> bool:
        """Determines if a subsequent continuation or partial page table shares this layout."""
        if self.raw_col_count != other_col_count:
            return False

        # Validate geometry via column bounding boxes if available
        if other_col_bboxes and self.col_bboxes:
            mismatches = 0
            comparisons = 0
            for c in range(min(len(self.col_bboxes), len(other_col_bboxes))):
                b1 = self.col_bboxes[c]
                b2 = other_col_bboxes[c]
                if b1 and b2:
                    comparisons += 1
                    # Check horizontal alignment (x0 and x1 within 25 pt tolerance)
                    if abs(b1[0] - b2[0]) > 25.0 or abs(b1[2] - b2[2]) > 25.0:
                        mismatches += 1
            if comparisons >= 2 and mismatches > comparisons / 2:
                return False

        if not other_headers:
            return True

        # Check if other_headers contains genuine header labels
        is_hdr = any(is_genuine_header_cell(c) for c in other_headers if c)
        if is_hdr:
            # Per-column role comparison: check if any explicit header changes role
            for c_idx, raw_c in enumerate(self.retained_cols):
                if c_idx < len(self.clean_headers):
                    est_hdr = self.clean_headers[c_idx]
                    est_role = classify_column_role(est_hdr)
                    if raw_c < len(other_headers):
                        other_cell = other_headers[raw_c]
                        if other_cell is not None and is_genuine_header_cell(other_cell):
                            other_role = classify_column_role(other_cell)
                            if est_role != "unknown" and other_role != "unknown" and est_role != other_role:
                                return False

            # Also check every column in other_headers against self
            for c in range(min(self.raw_col_count, len(other_headers))):
                other_cell = other_headers[c]
                if other_cell is not None and is_genuine_header_cell(other_cell):
                    other_role = classify_column_role(other_cell)
                    if c in self.retained_cols:
                        c_idx = self.retained_cols.index(c)
                        if c_idx < len(self.clean_headers):
                            est_role = classify_column_role(self.clean_headers[c_idx])
                            if est_role != "unknown" and other_role != "unknown" and est_role != other_role:
                                return False
                    else:
                        # An explicit functional header exists in a column previously pruned as non-retained
                        if other_role in ("price", "discount", "name"):
                            return False

        # Headerless continuation: validate that column roles from sample data do not conflict
        if not is_hdr and sample_rows:
            for c_idx, raw_c in enumerate(self.retained_cols):
                if c_idx < len(self.clean_headers):
                    est_role = classify_column_role(self.clean_headers[c_idx])
                    if est_role != "unknown":
                        cells = [r[raw_c] for r in sample_rows if raw_c < len(r) and r[raw_c] is not None]
                        if cells:
                            cur_role = classify_column_role("", cells)
                            if cur_role != "unknown" and cur_role != est_role:
                                if est_role == "discount" and cur_role == "price":
                                    vals = [extract_raw_float_value(c) for c in cells if str(c).strip()]
                                    if vals and all(0.0 <= v <= 85.0 for v in vals):
                                        continue
                                return False
        return True


@dataclass
class ProductGroup:
    """Represents a recognized (Price, Discount, Name, ...) product group within a table."""
    group_index: int
    raw_cols: List[int]
    price_col: Optional[int] = None
    discount_col: Optional[int] = None
    name_col: Optional[int] = None
    stock_col: Optional[int] = None
    code_col: Optional[int] = None
    bbox: Optional[List[float]] = None
    explicit_price_disc_headers: bool = False
    aligned_encoded_headers: bool = False

    @property
    def is_valid(self) -> bool:
        return self.name_col is not None and (self.price_col is not None or self.discount_col is not None)


def extract_raw_float_value(val: Any) -> float:
    """Extracts raw positive float from cell without clamping."""
    if val is None:
        return 0.0
    s = str(val).strip().replace(",", ".").replace("٫", ".").translate(ALL_EASTERN_DIGITS)
    m = re.search(r"[-+]?\d*\.?\d+", s)
    if not m:
        return 0.0
    try:
        v = float(m.group())
        return v if v > 0.0 else 0.0
    except ValueError:
        return 0.0


def is_explicit_zero_discount(cell_text: str) -> bool:
    """Detects explicit zero discount terms like 'صافي', 'نقدى', or '0%'."""
    if not cell_text:
        return False
    norm = unicodedata.normalize("NFKD", str(cell_text)).strip().lower().translate(ALL_EASTERN_DIGITS)
    if any(k in norm for k in ["صافي", "صافى", "صا في", "بدون خصم", "نقدى"]):
        return True
    if re.fullmatch(r"0+(?:\.0+)?\s*%?", norm):
        return True
    return False


def is_group_header_row(group: ProductGroup, row: List[Any]) -> bool:
    """
    Returns True if row 0 for this specific group is a genuine header row.
    """
    if not row or not group.raw_cols:
        return False
    group_cells = [row[c] for c in group.raw_cols if c < len(row)]
    if not any(c is not None and str(c).strip() for c in group_cells):
        return False

    header_cell_count = 0
    product_cell_count = 0

    for c in group.raw_cols:
        if c >= len(row) or row[c] is None:
            continue
        cell_str = str(row[c]).strip()
        if not cell_str:
            continue
        if is_genuine_header_cell(cell_str):
            header_cell_count += 1
        else:
            clean = cell_str.translate(ALL_EASTERN_DIGITS).replace(",", ".").strip()
            if re.fullmatch(r'[-+]?\d+(?:\.\d+)?\s*%?', clean):
                product_cell_count += 1
            elif is_explicit_zero_discount(cell_str):
                product_cell_count += 1
            elif len(cell_str) >= 2 and not is_catalog_noise(cell_str):
                product_cell_count += 1

    return header_cell_count > 0 and header_cell_count >= product_cell_count


def _get_table_extract(table_obj: Any) -> Any:
    cached = getattr(table_obj, "_cached_extract", None)
    if cached is not None:
        return cached
    raw = table_obj.extract()
    try:
        table_obj._cached_extract = raw
    except Exception:
        pass
    return raw


def _get_table_rows(table_obj: Any) -> Any:
    cached = getattr(table_obj, "_cached_rows", None)
    if cached is not None:
        return cached
    rows = table_obj.rows if hasattr(table_obj, "rows") else None
    try:
        table_obj._cached_rows = rows
    except Exception:
        pass
    return rows


def analyze_table_geometry(
    table_obj: Any,
    established_layout: Optional[TableGeometry] = None
) -> Optional[TableGeometry]:
    """
    Analyzes table geometry, merges header fragments belonging to the same body column,
    and prunes header-only structural slots confirmed to have 0 body cells.
    Persists established layout across compatible continuation and partial final pages.
    """
    t_rows = _get_table_rows(table_obj) if table_obj is not None else None
    if table_obj is None or not t_rows or len(t_rows) < 1:
        return None

    raw_data = _get_table_extract(table_obj)
    if not raw_data or len(raw_data) < 1:
        return None

    num_cols = table_obj.col_count
    if num_cols < 2:
        return None

    # Count body cells across body rows and extract col_bboxes across all rows
    col_bboxes: List[Optional[Tuple[float, float, float, float]]] = [None] * num_cols
    for r in t_rows:
        if hasattr(r, "cells") and r.cells:
            for c_idx, cell in enumerate(r.cells):
                if c_idx < num_cols and cell is not None:
                    if col_bboxes[c_idx] is None:
                        col_bboxes[c_idx] = tuple(cell)
                    else:
                        cur = col_bboxes[c_idx]
                        col_bboxes[c_idx] = (
                            min(cur[0], cell[0]),
                            min(cur[1], cell[1]),
                            max(cur[2], cell[2]),
                            max(cur[3], cell[3]),
                        )

    raw_header_row = [str(c).strip() if c is not None else "" for c in raw_data[0]]
    row0_has_headers = any(is_genuine_header_cell(c) for c in raw_header_row if c)
    data_start_row = 1 if (row0_has_headers and len(raw_data) > 1) else 0

    body_cell_counts = [0] * num_cols
    for row in raw_data[data_start_row:]:
        for c_idx, cell in enumerate(row):
            if c_idx < num_cols and cell is not None and str(cell).strip():
                body_cell_counts[c_idx] += 1

    sample_rows = raw_data[data_start_row:min(data_start_row + 10, len(raw_data))]

    # If an established layout exists from a compatible prior page, verify compatibility
    if established_layout and established_layout.is_compatible(
        num_cols, raw_header_row, other_col_bboxes=col_bboxes, sample_rows=sample_rows
    ):
        # On partial final pages where groups may be empty (e.g. Page 5: only group 0 has body cells),
        # reuse the established layout so empty columns on the partial page are preserved as empty groups.
        # If this table HAS its own genuine headers, honor the current explicit headers.
        if row0_has_headers:
            merged_headers = list(raw_header_row)
            for src_c, dst_c in sorted(established_layout.merge_into.items()):
                src_text = raw_header_row[src_c] if src_c < len(raw_header_row) else ""
                if src_text:
                    dst_text = merged_headers[dst_c] if dst_c < len(merged_headers) else ""
                    if src_text not in dst_text:
                        merged_headers[dst_c] = (dst_text + src_text).strip()
            clean_headers = [merged_headers[c] if c < len(merged_headers) else "" for c in established_layout.retained_cols]
        else:
            clean_headers = list(established_layout.clean_headers)

        return TableGeometry(
            raw_col_count=num_cols,
            retained_cols=list(established_layout.retained_cols),
            header_only_cols=set(established_layout.header_only_cols),
            merge_into=dict(established_layout.merge_into),
            clean_headers=clean_headers,
            col_bboxes=col_bboxes,
            body_cell_counts=body_cell_counts,
        )

    # Fresh page: identify header-only structural slots confirmed to have 0 body cells
    # while adjacent body columns have substantial body cells.
    has_body_cells = any(cnt > 0 for cnt in body_cell_counts)
    header_only_cols: Set[int] = set()
    merge_into: Dict[int, int] = {}

    if has_body_cells and len(raw_data) > 1 and row0_has_headers:
        for c in range(num_cols):
            if body_cell_counts[c] == 0:
                # Check if this column is a header-only fragment of an adjacent body column
                if c > 0 and body_cell_counts[c - 1] > 0:
                    header_only_cols.add(c)
                    merge_into[c] = c - 1
                elif c + 1 < num_cols and body_cell_counts[c + 1] > 0:
                    header_only_cols.add(c)
                    merge_into[c] = c + 1
                else:
                    # Trailing or isolated empty column
                    header_only_cols.add(c)

    retained_cols = [c for c in range(num_cols) if c not in header_only_cols]
    if not retained_cols:
        # Fallback if somehow all columns were empty
        retained_cols = list(range(num_cols))
        header_only_cols.clear()
        merge_into.clear()

    # Merge header fragments
    merged_headers = list(raw_header_row)
    for src_c, dst_c in sorted(merge_into.items()):
        src_text = raw_header_row[src_c] if src_c < len(raw_header_row) else ""
        if src_text:
            dst_text = merged_headers[dst_c] if dst_c < len(merged_headers) else ""
            # If src_text is already inside dst_text, avoid duplicate appending
            if src_text not in dst_text:
                merged_headers[dst_c] = (dst_text + src_text).strip()

    clean_headers = [merged_headers[c] if c < len(merged_headers) else "" for c in retained_cols]

    return TableGeometry(
        raw_col_count=num_cols,
        retained_cols=retained_cols,
        header_only_cols=header_only_cols,
        merge_into=merge_into,
        clean_headers=clean_headers,
        col_bboxes=col_bboxes,
        body_cell_counts=body_cell_counts,
    )


def classify_column_role(header_text: str, sample_cells: Optional[Sequence[Any]] = None) -> str:
    """
    Classifies the role of a table column as 'price', 'discount', 'name', 'stock', or 'code'
    using merged header text and sample body values.
    Distinguishes sequential serial indices from genuine discounts and prevents serial columns
    from hijacking discount roles.
    """
    h_norm = unicodedata.normalize("NFKD", str(header_text)).lower().strip() if header_text else ""

    # Only classify by header text if header_text looks like a genuine header (not product data)
    if h_norm and is_genuine_header_cell(h_norm):
        # Tier A: Exact Token Set for Short Code & Serial Abbreviations (must be exact token, not loose substring)
        code_exact_tokens = {
            "م", "م.", "م/", "م /", "م .", "ت", "ت.", "ت/", "ت /",
            "#", "no", "no.", "no/", "no /", "id", "sn", "s.n", "s/n", "seq", "sr", "sr.", "sr.no"
        }
        h_stripped = h_norm.strip(".:/\\- #")
        if h_norm in code_exact_tokens or h_stripped in {"م", "ت", "no", "id", "sn", "seq", "sr"}:
            return "code"

        # Tier B: Compound code keywords checked BEFORE generic name keywords
        code_compound_kws = [
            "رقم الصنف", "كود الصنف", "item code", "product code",
            "فنصلا مقر", "مقر فنصلا", "دوك فنصلا", "فنصلا دوك"
        ]
        if any(k in h_norm for k in code_compound_kws):
            return "code"

        # Standard header keywords
        name_kws = ["اسم", "صنف", "البيان", "دواء", "name", "item", "product", "description", "فنصلا", "مسإ", "مساف", "منسصالا"]
        price_kws = ["سعر", "جمهور", "رسمي", "price", "public", "base", "رعسلا", "رعس", "نلر"]
        disc_kws = ["خصم", "نسبة", "disc", "discount", "مصخلا", "مصخ", "ةلمج", "جملة", "ممم", "صافي", "صافى"]
        stock_kws = ["رصيد", "كمية", "حالة", "توفر", "متاح", "stock", "qty", "status", "avail"]
        code_kws = [
            "كود", "code", "باركود", "barcode", "مسلسل", "لسلسلم", "لسلم",
            "تسلسل", "لسلست", "الرقم", "رقم", "مقرلا", "مقر"
        ]
        notes_kws = ["ملاحظ", "تاظحلا", "هظحلام", "ةظحلام", "note", "remark"]

        tokens = set(re.findall(r'[\w%]+', h_norm))
        if any(k in h_norm for k in name_kws) or (tokens & {"name", "item", "product", "description"}):
            return "name"
        if any(k in h_norm for k in price_kws) or (tokens & {"price", "public", "base"}):
            return "price"
        if any(k in h_norm for k in disc_kws) or (tokens & {"disc", "discount"}):
            return "discount"
        if any(k in h_norm for k in stock_kws) or (tokens & {"stock", "qty", "avail"}):
            return "stock"
        if any(k in h_norm for k in code_kws) or (tokens & {"code", "barcode"}):
            return "code"
        if any(k in h_norm for k in notes_kws):
            return "unknown"

    # If header is ambiguous or missing, inspect sample body cells
    if sample_cells:
        numeric_count = 0
        explicit_discount_count = 0
        text_count = 0
        extracted_nums: List[float] = []

        for cell in sample_cells:
            if cell is None:
                continue
            s = str(cell).strip().translate(ALL_EASTERN_DIGITS)
            if not s:
                continue

            # Check explicit zero discount ('صافي', 'نقدى', etc.)
            if is_explicit_zero_discount(s):
                numeric_count += 1
                explicit_discount_count += 1
                extracted_nums.append(0.0)
                continue

            # Check numeric with or without '%'
            if re.fullmatch(r"[-+]?\d+(?:\.\d+)?\s*%?", s):
                numeric_count += 1
                try:
                    num_val = float(re.sub(r"[^\d.]", "", s))
                    extracted_nums.append(num_val)
                    if "%" in s:
                        explicit_discount_count += 1
                except ValueError:
                    pass
            elif len(re.findall(r"[\u0600-\u06ffA-Za-z]", s)) >= 2:
                text_count += 1

        total_samples = max(1, numeric_count + text_count)
        if text_count / total_samples >= 0.5:
            return "name"

        # Check for sequential serial integers (e.g. 1, 2, 3... or 10, 11, 12...)
        if len(extracted_nums) >= 2 and explicit_discount_count == 0:
            if all(v.is_integer() and v >= 0 for v in extracted_nums):
                diffs = [extracted_nums[i] - extracted_nums[i - 1] for i in range(1, len(extracted_nums))]
                # Strictly consecutive (+1 step)
                if all(d == 1.0 for d in diffs):
                    return "code"
                # Monotonically increasing with small steps (1..2 starting <= 10)
                if len(extracted_nums) >= 3 and all(d in (1.0, 2.0) for d in diffs) and extracted_nums[0] <= 10:
                    return "code"

        # Strict discount gate: discount role requires explicit discount header (checked above in disc_kws),
        # explicit '%' sign, or explicit zero discount terms ('صافي', 'نقدى')
        if explicit_discount_count / total_samples >= 0.5:
            return "discount"

        # Plain numeric -> price
        if numeric_count / total_samples >= 0.5:
            return "price"

    return "unknown"


def detect_product_groups(
    geometry: TableGeometry,
    raw_data: List[List[Any]],
    established_groups: Optional[List[ProductGroup]] = None
) -> List[ProductGroup]:
    """
    Dynamically discovers repeating product groups (Price, Discount, Name, ...)
    without relying on table column count being divisible by 3 or 4.
    Supports non-pruned structural columns (serial numbers, codes, notes) at
    arbitrary start offsets.
    """
    if not geometry or not geometry.retained_cols:
        return []

    retained = geometry.retained_cols
    clean_headers = geometry.clean_headers
    n = len(retained)

    # Sample rows for role confirmation
    # If row 0 contains product data (not genuine headers) or table has only 1 row, sample from row 0
    has_header_row0 = bool(raw_data and len(raw_data) > 1 and any(is_genuine_header_cell(c) for c in raw_data[0] if c))
    data_sample_start = 1 if has_header_row0 else 0
    sample_rows = raw_data[data_sample_start:min(data_sample_start + 10, len(raw_data))] if raw_data else []

    roles: List[str] = []
    for idx, raw_c in enumerate(retained):
        hdr = clean_headers[idx] if idx < len(clean_headers) else ""
        sample_cells = [r[raw_c] for r in sample_rows if raw_c < len(r)] if sample_rows else None
        role = classify_column_role(hdr, sample_cells)
        roles.append(role)

    has_explicit_header = [
        bool(c_idx < len(clean_headers) and clean_headers[c_idx] and is_genuine_header_cell(clean_headers[c_idx]))
        for c_idx in range(n)
    ]

    # Validate established groups against current detected roles
    if established_groups:
        all_raw_cols = [c for g in established_groups for c in g.raw_cols]
        if all_raw_cols == retained:
            role_conflict = False
            for g in established_groups:
                for col_name, col_idx in [
                    ("price", g.price_col),
                    ("discount", g.discount_col),
                    ("name", g.name_col),
                    ("stock", g.stock_col),
                    ("code", g.code_col),
                ]:
                    if col_idx is not None and col_idx in retained:
                        r_idx = retained.index(col_idx)
                        cur_role = roles[r_idx]
                        if cur_role != "unknown" and cur_role != col_name:
                            if (
                                not has_explicit_header[r_idx]
                                and col_name == "discount"
                                and cur_role == "price"
                                and sample_rows
                            ):
                                cells = [r[col_idx] for r in sample_rows if col_idx < len(r) and r[col_idx] is not None]
                                vals = [extract_raw_float_value(c) for c in cells if str(c).strip()]
                                if vals and all(0.0 <= v <= 85.0 for v in vals):
                                    continue
                            role_conflict = True
                            break
                if role_conflict:
                    break
            if not role_conflict:
                return established_groups

    # -----------------------------------------------------------------------
    # Step 1: Discover repeating cycles with arbitrary leading/trailing columns
    # -----------------------------------------------------------------------
    candidate_cycle_lengths = [3, 4, 2]
    best_candidate = None  # (score, cycle_len, start_offset, num_groups)

    has_any_price = "price" in roles
    has_any_disc = "discount" in roles

    for cycle_len in candidate_cycle_lengths:
        # Search starting offsets from 0 up to max possible offset that allows >= 2 groups
        max_offset = min(4, n - 2 * cycle_len)
        if max_offset < 0:
            continue

        for start_offset in range(max_offset + 1):
            num_groups = (n - start_offset) // cycle_len
            if num_groups < 2:
                continue

            # Check if there are mutually conflicting explicit headers at any relative cycle offset
            has_explicit_conflict = False
            cycle_explicit_roles: Dict[int, str] = {}
            for rel_i in range(cycle_len):
                exp_roles = [
                    roles[start_offset + g_i * cycle_len + rel_i]
                    for g_i in range(num_groups)
                    if has_explicit_header[start_offset + g_i * cycle_len + rel_i]
                    and roles[start_offset + g_i * cycle_len + rel_i] != "unknown"
                ]
                if len(set(exp_roles)) > 1:
                    has_explicit_conflict = True
                    break
                elif exp_roles:
                    cycle_explicit_roles[rel_i] = exp_roles[0]

            if has_explicit_conflict:
                continue

            valid = True
            name_rel_indices: List[int] = []

            for g_i in range(num_groups):
                g_start = start_offset + g_i * cycle_len
                group_raw_cols = retained[g_start : g_start + cycle_len]
                group_roles = roles[g_start : g_start + cycle_len]

                eff_group_roles: List[str] = []
                for rel_i in range(cycle_len):
                    c_idx = g_start + rel_i
                    raw_c = group_raw_cols[rel_i]
                    cur_role = group_roles[rel_i]

                    if has_explicit_header[c_idx]:
                        eff_group_roles.append(cur_role)
                    elif rel_i in cycle_explicit_roles:
                        inferred_role = cycle_explicit_roles[rel_i]
                        # Verify data compatibility in this column for the inferred role
                        cell_samples = [r[raw_c] for r in sample_rows if raw_c < len(r) and r[raw_c] is not None] if sample_rows else []
                        if inferred_role in ("price", "discount"):
                            is_compat_num = all(
                                re.search(r'\d', str(cell)) is not None or is_explicit_zero_discount(str(cell)) or not str(cell).strip()
                                for cell in cell_samples
                            ) if cell_samples else True
                            eff_group_roles.append(inferred_role if is_compat_num else cur_role)
                        elif inferred_role == "name":
                            is_compat_name = any(
                                len(re.findall(r'[\u0600-\u06ffA-Za-z]', str(cell))) >= 2
                                for cell in cell_samples
                            ) if cell_samples else True
                            eff_group_roles.append(inferred_role if is_compat_name else cur_role)
                        else:
                            eff_group_roles.append(inferred_role)
                    else:
                        eff_group_roles.append(cur_role)

                has_name = "name" in eff_group_roles
                has_price = "price" in eff_group_roles
                has_disc = "discount" in eff_group_roles

                if not has_name:
                    valid = False
                    break
                if has_any_price and not has_price:
                    valid = False
                    break
                if has_any_disc and cycle_len >= 3 and not has_disc:
                    valid = False
                    break
                name_rel_indices.append(eff_group_roles.index("name"))

            if not valid:
                continue

            # In a repeating tabular cycle, the 'name' column must appear at the exact same relative index
            if len(set(name_rel_indices)) != 1:
                continue

            # Score this candidate:
            # - num_groups (higher is better)
            # - columns covered: num_groups * cycle_len (higher is better)
            # - preference for cycle 3 or 4 over 2
            coverage = num_groups * cycle_len
            cycle_pref = 5 if cycle_len in (3, 4) else 0
            score = (num_groups * 100) + (coverage * 10) + cycle_pref

            if best_candidate is None or score > best_candidate[0]:
                best_candidate = (score, cycle_len, start_offset, num_groups)

    groups: List[ProductGroup] = []

    if best_candidate is not None:
        _, detected_cycle, start_offset, num_groups = best_candidate

        # Determine consensus role schema for the repeating cycle
        consensus_roles: List[Optional[str]] = []
        for rel_i in range(detected_cycle):
            exp_roles = [
                roles[start_offset + g_i * detected_cycle + rel_i]
                for g_i in range(num_groups)
                if has_explicit_header[start_offset + g_i * detected_cycle + rel_i]
                and roles[start_offset + g_i * detected_cycle + rel_i] != "unknown"
            ]
            if exp_roles:
                consensus_role = max(set(exp_roles), key=exp_roles.count)
            else:
                rel_roles = [roles[start_offset + g_i * detected_cycle + rel_i] for g_i in range(num_groups)]
                known = [r for r in rel_roles if r in ("price", "discount", "name", "stock", "code")]
                consensus_role = max(set(known), key=known.count) if known else None
            consensus_roles.append(consensus_role)

        for g_i in range(num_groups):
            start = start_offset + g_i * detected_cycle
            group_raw_cols = retained[start : start + detected_cycle]

            price_col = None
            discount_col = None
            name_col = None
            stock_col = None
            code_col = None

            # Map columns for this group: honor group's own explicit header, or infer from consensus schema
            for rel_i, c_raw in enumerate(group_raw_cols):
                c_idx = start + rel_i
                if has_explicit_header[c_idx]:
                    r_name = roles[c_idx]
                else:
                    r_name = consensus_roles[rel_i]

                if r_name == "price" and price_col is None:
                    price_col = c_raw
                elif r_name == "discount" and discount_col is None:
                    discount_col = c_raw
                elif r_name == "name" and name_col is None:
                    name_col = c_raw
                elif r_name == "stock" and stock_col is None:
                    stock_col = c_raw
                elif r_name == "code" and code_col is None:
                    code_col = c_raw

            # Compute bbox for this group
            g_bbox = None
            bboxes = [geometry.col_bboxes[c] for c in group_raw_cols if c < len(geometry.col_bboxes) and geometry.col_bboxes[c]]
            if bboxes:
                g_bbox = [
                    min(b[0] for b in bboxes),
                    min(b[1] for b in bboxes),
                    max(b[2] for b in bboxes),
                    max(b[3] for b in bboxes),
                ]

            exp_hdr_both = bool(
                price_col is not None
                and discount_col is not None
                and price_col in retained
                and discount_col in retained
                and (
                    (has_explicit_header[retained.index(price_col)] and has_explicit_header[retained.index(discount_col)])
                    or ("price" in consensus_roles and "discount" in consensus_roles and any(has_explicit_header))
                )
            )
            groups.append(
                ProductGroup(
                    group_index=g_i,
                    raw_cols=group_raw_cols,
                    price_col=price_col,
                    discount_col=discount_col,
                    name_col=name_col,
                    stock_col=stock_col,
                    code_col=code_col,
                    bbox=g_bbox,
                    explicit_price_disc_headers=exp_hdr_both,
                )
            )
        return groups

    # -----------------------------------------------------------------------
    # Step 2: Fallback path: partition around multiple 'name' columns or single group
    # -----------------------------------------------------------------------
    name_indices = [i for i, r in enumerate(roles) if r == "name"]

    if len(name_indices) >= 2:
        # Multiple name columns detected: partition retained columns into multiple groups
        m = len(name_indices)
        first_name_idx = name_indices[0]

        # Determine orientation: are price/discount columns before or after 'name'?
        has_num_before_first_name = any(roles[i] in ("price", "discount") for i in range(first_name_idx))

        slices: List[Tuple[int, int]] = []
        if has_num_before_first_name:
            # RTL layout: name is at the end of each group [..., price, discount, name]
            prev_end = 0
            for k in range(m):
                curr_name_idx = name_indices[k]
                if k == m - 1:
                    end_idx = n
                else:
                    end_idx = curr_name_idx + 1
                slices.append((prev_end, end_idx))
                prev_end = end_idx
        else:
            # LTR layout: name is at the start of each group [name, price, discount, ...]
            for k in range(m):
                curr_name_idx = name_indices[k]
                start_idx = curr_name_idx if k > 0 else 0
                if k == m - 1:
                    end_idx = n
                else:
                    end_idx = name_indices[k + 1]
                slices.append((start_idx, end_idx))

        for g_i, (s_start, s_end) in enumerate(slices):
            g_raw_cols = retained[s_start:s_end]
            g_roles = roles[s_start:s_end]

            price_col = None
            discount_col = None
            name_col = None
            stock_col = None
            code_col = None

            for c_raw, r_name in zip(g_raw_cols, g_roles):
                if r_name == "price" and price_col is None:
                    price_col = c_raw
                elif r_name == "discount" and discount_col is None:
                    discount_col = c_raw
                elif r_name == "name" and name_col is None:
                    name_col = c_raw
                elif r_name == "stock" and stock_col is None:
                    stock_col = c_raw
                elif r_name == "code" and code_col is None:
                    code_col = c_raw

            g_bbox = None
            bboxes = [geometry.col_bboxes[c] for c in g_raw_cols if c < len(geometry.col_bboxes) and geometry.col_bboxes[c]]
            if bboxes:
                g_bbox = [
                    min(b[0] for b in bboxes),
                    min(b[1] for b in bboxes),
                    max(b[2] for b in bboxes),
                    max(b[3] for b in bboxes),
                ]

            exp_hdr_both = bool(
                price_col is not None
                and discount_col is not None
                and price_col in retained
                and discount_col in retained
                and has_explicit_header[retained.index(price_col)]
                and has_explicit_header[retained.index(discount_col)]
            )
            groups.append(
                ProductGroup(
                    group_index=g_i,
                    raw_cols=g_raw_cols,
                    price_col=price_col,
                    discount_col=discount_col,
                    name_col=name_col,
                    stock_col=stock_col,
                    code_col=code_col,
                    bbox=g_bbox,
                    explicit_price_disc_headers=exp_hdr_both,
                )
            )
        return groups

    # Single group fallback
    price_col = None
    discount_col = None
    name_col = None
    stock_col = None
    code_col = None

    for c_raw, r_name in zip(retained, roles):
        if r_name == "price" and price_col is None:
            price_col = c_raw
        elif r_name == "discount" and discount_col is None:
            discount_col = c_raw
        elif r_name == "name" and name_col is None:
            name_col = c_raw
        elif r_name == "stock" and stock_col is None:
            stock_col = c_raw
        elif r_name == "code" and code_col is None:
            code_col = c_raw

    # If name is still None, inspect sample rows to find a column with genuine product text/letters
    if name_col is None and retained and sample_rows:
        for c_cand in reversed(retained):
            c_cells = [str(r[c_cand]).strip() for r in sample_rows if c_cand < len(r) and r[c_cand]]
            if any(len(re.findall(r'[\u0600-\u06ffA-Za-z]', s)) >= 2 for s in c_cells):
                name_col = c_cand
                break
        if name_col is not None:
            if price_col is None and len(retained) >= 2:
                for c_cand in retained:
                    if c_cand != name_col:
                        price_col = c_cand
                        break
            if discount_col is None and len(retained) >= 3:
                for c_cand in retained:
                    if c_cand != name_col and c_cand != price_col:
                        discount_col = c_cand
                        break

    g_bbox = None
    bboxes = [geometry.col_bboxes[c] for c in retained if c < len(geometry.col_bboxes) and geometry.col_bboxes[c]]
    if bboxes:
        g_bbox = [
            min(b[0] for b in bboxes),
            min(b[1] for b in bboxes),
            max(b[2] for b in bboxes),
            max(b[3] for b in bboxes),
        ]

    exp_hdr_both = bool(
        price_col is not None
        and discount_col is not None
        and price_col in retained
        and discount_col in retained
        and has_explicit_header[retained.index(price_col)]
        and has_explicit_header[retained.index(discount_col)]
    )
    groups.append(
        ProductGroup(
            group_index=0,
            raw_cols=list(retained),
            price_col=price_col,
            discount_col=discount_col,
            name_col=name_col,
            stock_col=stock_col,
            code_col=code_col,
            bbox=g_bbox,
            explicit_price_disc_headers=exp_hdr_both,
        )
    )

    return groups


def resolve_group_arabic_direction(rows: List[List[Any]], name_col: int) -> str:
    """
    Establishes group-level Arabic reading direction from multiple clear examples within the group.
    Returns 'reversed', 'forward', or 'unknown'.
    """
    if name_col is None or not rows:
        return "unknown"

    rev_votes = 0
    fwd_votes = 0

    for r in rows:
        if name_col >= len(r) or r[name_col] is None:
            continue
        val = str(r[name_col]).strip()
        if not val or len(val) < 2 or val.isdigit():
            continue
        decoded = decode_custom_catalog_glyphs(val)
        if is_catalog_noise(decoded):
            continue

        if is_arabic_text_reversed(decoded):
            rev_votes += 1
        elif any(w in decoded for w in FORWARD_PHARMA_TOKENS):
            fwd_votes += 1

    if rev_votes >= 2 and rev_votes > fwd_votes * 1.5:
        return "reversed"
    if fwd_votes >= 2 and fwd_votes > rev_votes * 1.5:
        return "forward"
    return "unknown"


def extract_item_from_group_row(
    row: List[Any],
    group: ProductGroup,
    group_direction: str,
    warehouse_name: str,
    row_bboxes: Optional[List[Any]] = None,
    sanity_checker: Optional[Any] = None,
    page_chars: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Optional[Dict[str, Any]], str, Optional[List[float]]]:
    """
    Parses a single row independently from a ProductGroup without stripping empty cells,
    applying group-level Arabic direction voting while preserving forward Arabic and Latin runs,
    decimal strengths, and multi-part ratios.
    Returns (item_dict_or_None, outcome_reason, item_bbox).
    """
    # Compute bounding box for this row from cell bboxes before early validation exits (R2)
    item_bbox = None
    if row_bboxes:
        relevant_bboxes = [row_bboxes[c] for c in group.raw_cols if c < len(row_bboxes) and row_bboxes[c] is not None]
        if relevant_bboxes:
            item_bbox = [
                min(b[0] for b in relevant_bboxes),
                min(b[1] for b in relevant_bboxes),
                max(b[2] for b in relevant_bboxes),
                max(b[3] for b in relevant_bboxes),
            ]

    if not group.is_valid:
        return None, "invalid_group", item_bbox

    # 1. Extract raw name cell
    name_idx = group.name_col
    if name_idx is None or name_idx >= len(row) or row[name_idx] is None:
        return None, "empty_name_cell", item_bbox

    raw_name_cell = str(row[name_idx]).strip()
    if not raw_name_cell:
        return None, "blank_name", item_bbox

    # Check for header repetition inside body rows
    if any(h in raw_name_cell for h in ["اسم الصنف", "الصنف", "Item Name", "Product", "البيان", "فنصلا", "مسإ", "مساف", "منسصالا"]):
        return None, "header_repetition", item_bbox

    # 2. Extract price and discount without shifting adjacent columns
    raw_price_cell = str(row[group.price_col]).strip() if group.price_col is not None and group.price_col < len(row) and row[group.price_col] is not None else ""
    raw_discount_cell = str(row[group.discount_col]).strip() if group.discount_col is not None and group.discount_col < len(row) and row[group.discount_col] is not None else ""

    price_val = extract_raw_float_value(raw_price_cell)
    discount_val = parse_discount(raw_discount_cell)
    if discount_val == 0.0 and not is_explicit_zero_discount(raw_discount_cell):
        raw_d_num_early = extract_raw_float_value(raw_discount_cell)
        if 0.85 < raw_d_num_early <= 1.0:
            discount_val = round(raw_d_num_early / 100.0, 4)

    # 3. Handle stock status
    stock_status = True
    if group.stock_col is not None and group.stock_col < len(row) and row[group.stock_col]:
        stock_text = str(row[group.stock_col]).strip().lower()
        if any(kw in stock_text for kw in ["غير متوفر", "نفذ", "out", "0", "لا يوجد"]):
            stock_status = False

    # 4. Clean and normalize name
    reconstructed_from_chars = False
    if page_chars and row_bboxes and name_idx < len(row_bboxes) and row_bboxes[name_idx] is not None:
        try:
            from .pdf_font_decoder import reconstruct_cell_text_from_chars
        except ImportError:
            from pdf_font_decoder import reconstruct_cell_text_from_chars
        coord_text = reconstruct_cell_text_from_chars(page_chars, row_bboxes[name_idx])
        if coord_text and len(coord_text) >= 2:
            decoded_name = decode_custom_catalog_glyphs(coord_text)
            item_name = unreverse_arabic_text(decoded_name, force_reverse=False)
            reconstructed_from_chars = True

    if not reconstructed_from_chars:
        cleaned_name = re.sub(r"^\s*[\u1800-\u18af\s]+\n", "", raw_name_cell)
        decoded_name = decode_custom_catalog_glyphs(cleaned_name)

        latin_chars = len(re.findall(r"[a-zA-Z]", decoded_name))
        arabic_chars = len(re.findall(r"[\u0600-\u06ff\ufb50-\ufdff\ufe70-\ufeff]", decoded_name))

        # Apply group-level reading direction voting
        if latin_chars > arabic_chars:
            # Predominantly Latin text: preserve forward order
            item_name = unreverse_arabic_text(decoded_name, force_reverse=False)
        elif any(w in decoded_name for w in FORWARD_PHARMA_TOKENS) and not is_arabic_text_reversed(decoded_name):
            # Clearly forward Arabic text: preserve forward order
            item_name = unreverse_arabic_text(decoded_name, force_reverse=False)
        elif group_direction == "reversed":
            # Group is reversed: un-reverse ambiguous or reversed rows
            item_name = unreverse_arabic_text(decoded_name, force_reverse=True)
        elif is_arabic_text_reversed(decoded_name):
            # Group is not reversed, but this individual row is reversed
            item_name = unreverse_arabic_text(decoded_name, force_reverse=True)
        else:
            # Default forward
            item_name = unreverse_arabic_text(decoded_name, force_reverse=False)

    # Check for unmapped or suspicious characters remaining in item_name
    try:
        from .pdf_font_decoder import has_suspicious_characters
    except ImportError:
        from pdf_font_decoder import has_suspicious_characters
    has_susp, susp_reasons = has_suspicious_characters(item_name)
    if has_susp:
        return None, f"suspicious_characters_{susp_reasons[0]}", item_bbox

    norm_name = normalize_arabic_text(item_name)
    if is_catalog_noise(norm_name) or is_catalog_noise(item_name):
        return None, "catalog_noise", item_bbox

    if len(norm_name) < 2:
        return None, "name_too_short", item_bbox

    # Check that search normalization did not mutate or drop digit sequences present in display item_name
    disp_digits = re.findall(r"\d+", item_name.translate(ALL_EASTERN_DIGITS))
    norm_digits = re.findall(r"\d+", norm_name.translate(ALL_EASTERN_DIGITS))
    if disp_digits and disp_digits != norm_digits:
        return None, "numeric_mutation_in_normalization", item_bbox

    # 5. Sanity check price and discount ONLY when explicit headers / '%' markers do not establish column roles
    raw_p_num = extract_raw_float_value(raw_price_cell)
    raw_d_num = extract_raw_float_value(raw_discount_cell)
    has_explicit_disc_marker = ("%" in raw_discount_cell) or is_explicit_zero_discount(raw_discount_cell)

    if (
        not getattr(group, "explicit_price_disc_headers", False)
        and not has_explicit_disc_marker
        and sanity_checker is not None
        and hasattr(sanity_checker, "_sanity_check_item_price_and_discount")
    ):
        price_val, discount_val = sanity_checker._sanity_check_item_price_and_discount(
            item_name, price_val, discount_val, raw_price_num=raw_p_num, raw_disc_num=raw_d_num
        )

    # Validate price and discount boundaries
    is_valid_zero = (discount_val == 0.0 and is_explicit_zero_discount(raw_discount_cell))
    valid_discount = (0.0 < discount_val <= 0.85) or is_valid_zero
    valid_price = (0.0 < price_val <= 10000.0)

    if not valid_price:
        return None, f"invalid_price_{price_val}", item_bbox
    if not valid_discount:
        if raw_d_num > 85.0:
            return None, f"invalid_discount_{round(raw_d_num / 100.0, 4)}", item_bbox
        return None, f"invalid_discount_{discount_val}", item_bbox

    dosage, unit_size = parse_dosage_and_pack(item_name)

    item_dict = {
        "warehouse_name": warehouse_name,
        "item_name": item_name,
        "normalized_name": norm_name,
        "dosage": dosage,
        "unit_size": unit_size,
        "base_price": price_val,
        "discount_rate": discount_val,
        "stock_status": stock_status,
    }
    return item_dict, "accepted", item_bbox


class CatalogImportMetadata(dict):
    """
    Metadata dictionary stored in frame.attrs['catalog_import'] that provides both dict access
    and object attribute access (diagnostics, fingerprint, acknowledgment_token, status, etc.)
    without circular references.
    """
    def __init__(self, diagnostics: Any, fingerprint: Optional[Any], acknowledgment_token: str):
        from dataclasses import asdict
        super().__init__({
            "fingerprint": asdict(fingerprint) if fingerprint else None,
            "diagnostics": diagnostics.to_dict() if hasattr(diagnostics, "to_dict") else diagnostics,
        })
        self.diagnostics = diagnostics
        self.fingerprint = fingerprint
        self.acknowledgment_token = acknowledgment_token

    def __deepcopy__(self, memo):
        memo[id(self)] = self
        return self

    @property
    def status(self) -> str:
        return getattr(self.diagnostics, "status", "unknown")

    @property
    def candidate_rows(self) -> int:
        return getattr(self.diagnostics, "candidate_rows", 0)

    @property
    def accepted_rows(self) -> int:
        return getattr(self.diagnostics, "accepted_rows", 0)

    @property
    def unique_records(self) -> int:
        return getattr(self.diagnostics, "unique_records", 0)

    @property
    def duplicate_records(self) -> int:
        return getattr(self.diagnostics, "duplicate_records", 0)

    @property
    def rejected_rows(self) -> int:
        return getattr(self.diagnostics, "rejected_rows", 0)

    @property
    def unprocessed_rows(self) -> int:
        return getattr(self.diagnostics, "unprocessed_rows", 0)



def _apply_aligned_source_headers(page, table_obj, raw_data, group):
    """Verify a repeated three-column group against a visible header above its first body row."""
    if page is None or len(group.raw_cols) != 3:
        return False
    if group.explicit_price_disc_headers:
        return group.aligned_encoded_headers
    try:
        from pymupdf import Rect
    except ImportError:
        return False

    for raw, table_row in zip(raw_data[:10], table_obj.rows[:10]):
        available = [col for col, cell in enumerate(table_row.cells)
                     if cell and col < len(raw) and str(raw[col] or "").strip()]
        if group.name_col not in available:
            continue
        name_index = available.index(group.name_col)
        matches = []
        for start in range(max(0, name_index - 2), min(name_index + 1, len(available) - 2)):
            cols = available[start:start + 3]
            if len(set(cols) & set(group.raw_cols)) < 2:
                continue
            if cols.index(group.name_col) == 1:
                continue
            numeric = [bool(re.fullmatch(r"\d+(?:[.,٫]\d+)?\s*%?", str(raw[col]).strip())) for col in cols]
            if sum(numeric) != 2 or numeric[cols.index(group.name_col)]:
                continue
            cells = [table_row.cells[col] for col in cols]
            header_text = [page.get_text("text", clip=Rect(x0, max(0, y0 - 22), x1, y0)).strip()
                           for x0, y0, x1, _ in cells]
            custom_roles = {"ا نلر": "price", "ممم": "discount", "انم ا مسف": "name"}
            encoded = set(header_text) == custom_roles.keys()
            roles = {}
            for col, header in zip(cols, header_text):
                options = {classify_column_role(line) for line in header.splitlines()}
                options &= {"price", "discount", "name"}
                if encoded:
                    options = {custom_roles[header]}
                if len(options) == 1:
                    roles[next(iter(options))] = col
            if roles.keys() == {"price", "discount", "name"} and roles["name"] == group.name_col:
                matches.append((cols, roles, encoded))
        if len(matches) == 1:
            cols, roles, encoded = matches[0]
            group.raw_cols = cols
            group.price_col = roles["price"]
            group.discount_col = roles["discount"]
            group.explicit_price_disc_headers = True
            group.aligned_encoded_headers = encoded
            return encoded
        if matches:
            return False
    return False


def parse_structural_table(
    table_obj: Any,
    page_idx: int,
    warehouse_name: str,
    established_layout: Optional[TableGeometry] = None,
    established_groups: Optional[List[ProductGroup]] = None,
    sanity_checker: Optional[Any] = None,
    table_idx: int = 0,
    page_chars: Optional[List[Dict[str, Any]]] = None,
    page: Any = None,
) -> Tuple[List[Dict[str, Any]], Optional[TableGeometry], Optional[List[ProductGroup]], Any]:
    """
    Extracts catalog items from a structural PDF table object, retaining cell bounding boxes,
    persisting page layout, voting on group-level Arabic direction, and recording rich diagnostics.
    """
    try:
        from .catalog_diagnostics import GroupDiagnostics, PageDiagnostics, RowDiagnostic, build_source_id
    except ImportError:
        from catalog_diagnostics import GroupDiagnostics, PageDiagnostics, RowDiagnostic, build_source_id

    raw_data = _get_table_extract(table_obj)
    t_rows = _get_table_rows(table_obj)
    geometry = analyze_table_geometry(table_obj, established_layout=established_layout)
    if not geometry:
        return [], established_layout, established_groups, PageDiagnostics(page=page_idx + 1, strategy="empty")

    groups = detect_product_groups(geometry, raw_data, established_groups=established_groups)
    if not groups:
        return [], geometry, established_groups, PageDiagnostics(page=page_idx + 1, strategy="no_groups")

    page_items: List[Dict[str, Any]] = []
    group_diagnostics_list: List[GroupDiagnostics] = []

    for group in groups:
        encoded_header = _apply_aligned_source_headers(page, table_obj, raw_data, group)
        # Determine whether this specific group has a genuine header in row 0
        group_has_hdr = is_group_header_row(group, raw_data[0]) if raw_data else False
        start_row = 1 if group_has_hdr else 0
        group_rows = raw_data[start_row:]

        group_diag = GroupDiagnostics(
            group=group.group_index,
            strategy="structural_table",
            bbox=group.bbox,
        )
        group_direction = resolve_group_arabic_direction(group_rows, group.name_col)

        for r_idx in range(start_row, len(raw_data)):
            row = raw_data[r_idx]
            name_val = row[group.name_col] if group.name_col is not None and group.name_col < len(row) else None
            price_val = row[group.price_col] if group.price_col is not None and group.price_col < len(row) else None
            disc_val = row[group.discount_col] if group.discount_col is not None and group.discount_col < len(row) else None

            is_name_empty = (name_val is None or not str(name_val).strip())
            is_price_empty = (price_val is None or not str(price_val).strip())
            is_disc_empty = (disc_val is None or not str(disc_val).strip())

            if is_name_empty and is_price_empty and is_disc_empty:
                # Genuinely empty slot: exclude from candidate rows
                continue

            group_diag.candidate_rows += 1
            row_bboxes = t_rows[r_idx].cells if (t_rows and r_idx < len(t_rows) and hasattr(t_rows[r_idx], "cells")) else None

            item, outcome_reason, item_bbox = extract_item_from_group_row(
                row, group, group_direction, warehouse_name, row_bboxes, sanity_checker,
                page_chars=None if encoded_header else page_chars,
            )

            raw_cells_data = [row[c] for c in group.raw_cols if c < len(row)]
            raw_item_name = str(name_val).strip() if name_val is not None else ""

            row_sid = build_source_id(
                page=page_idx + 1,
                table=table_idx,
                group=group.group_index,
                row=r_idx,
            )

            col_bounds_map = {}
            if row_bboxes:
                if group.name_col is not None and group.name_col < len(row_bboxes) and row_bboxes[group.name_col]:
                    col_bounds_map["name"] = (float(row_bboxes[group.name_col][0]), float(row_bboxes[group.name_col][2]))
                if group.price_col is not None and group.price_col < len(row_bboxes) and row_bboxes[group.price_col]:
                    col_bounds_map["price"] = (float(row_bboxes[group.price_col][0]), float(row_bboxes[group.price_col][2]))
                if group.discount_col is not None and group.discount_col < len(row_bboxes) and row_bboxes[group.discount_col]:
                    col_bounds_map["discount"] = (float(row_bboxes[group.discount_col][0]), float(row_bboxes[group.discount_col][2]))

            if item is not None:
                group_diag.accepted_rows += 1
                group_diag.rows.append(
                    RowDiagnostic(
                        page=page_idx + 1,
                        group=group.group_index,
                        row=r_idx,
                        outcome="accepted",
                        bbox=item_bbox,
                        raw_cells=raw_cells_data,
                        item_name=item["item_name"],
                        table=table_idx,
                        source_id=row_sid,
                        column_bounds=col_bounds_map if col_bounds_map else None,
                        validation_results={"verified_column_roles": group.explicit_price_disc_headers},
                    )
                )
                page_items.append(item)
            else:
                group_diag.rejected_rows += 1
                rej_p = extract_raw_float_value(price_val) if price_val is not None else 0.0
                rej_d_raw = extract_raw_float_value(disc_val) if disc_val is not None else 0.0
                rej_d = parse_discount(str(disc_val)) if disc_val is not None else 0.0
                if rej_d == 0.0 and rej_d_raw > 85.0:
                    rej_d = round(rej_d_raw / 100.0, 4)
                elif rej_d == 0.0 and 0.85 < rej_d_raw <= 1.0:
                    rej_d = round(rej_d_raw / 100.0, 4)

                disp_item_name = raw_item_name
                if disp_item_name:
                    cleaned_disp = re.sub(r"^\s*[\u1800-\u18af\s]+\n", "", disp_item_name)
                    decoded_disp = decode_custom_catalog_glyphs(cleaned_disp)
                    if group_direction == "reversed" or is_arabic_text_reversed(decoded_disp):
                        disp_item_name = unreverse_arabic_text(decoded_disp, force_reverse=True)
                    else:
                        disp_item_name = unreverse_arabic_text(decoded_disp, force_reverse=False)

                rej_item_dict = {
                    "warehouse_name": warehouse_name,
                    "item_name": disp_item_name or raw_item_name,
                    "base_price": rej_p,
                    "discount_rate": rej_d,
                } if raw_item_name else None

                target_cell_bbox = None
                if row_bboxes:
                    if outcome_reason in ("blank_name", "empty_name_cell", "name_too_short", "suspicious_characters_in_name"):
                        if group.name_col is not None and group.name_col < len(row_bboxes):
                            target_cell_bbox = row_bboxes[group.name_col]
                    elif "price" in outcome_reason:
                        if group.price_col is not None and group.price_col < len(row_bboxes):
                            target_cell_bbox = row_bboxes[group.price_col]
                    elif "discount" in outcome_reason:
                        if group.discount_col is not None and group.discount_col < len(row_bboxes):
                            target_cell_bbox = row_bboxes[group.discount_col]

                group_diag.rows.append(
                    RowDiagnostic(
                        page=page_idx + 1,
                        group=group.group_index,
                        row=r_idx,
                        outcome="rejected",
                        reason=outcome_reason,
                        bbox=item_bbox,
                        region_bbox=target_cell_bbox or item_bbox,
                        raw_cells=raw_cells_data,
                        item_name=disp_item_name or raw_item_name,
                        table=table_idx,
                        source_id=row_sid,
                        item=rej_item_dict,
                        column_bounds=col_bounds_map if col_bounds_map else None,
                        validation_results={"verified_column_roles": group.explicit_price_disc_headers},
                    )
                )

        group_diagnostics_list.append(group_diag)

    page_accepted = sum(g.accepted_rows for g in group_diagnostics_list)
    page_diag = PageDiagnostics(
        page=page_idx + 1,
        strategy="structural_table",
        expected_count_known=True,
        accepted_rows=page_accepted,
        groups=group_diagnostics_list,
    )

    return page_items, geometry, groups, page_diag


def validate_catalog_item(item_data: dict[str, Any]) -> tuple[bool, Optional[str]]:
    """
    Canonical pharmaceutical and numeric validation pipeline shared across initial extraction,
    deterministic automatic recovery, and manual user correction.

    Enforces:
    - Medication name: non-empty, stripped, no header tokens, not catalog noise, len >= 2.
    - Price: float, 0.0 < price < 10000.0.
    - Discount: Optional[float], 0.0 <= discount <= 0.85 (blank discount as None, distinct from 0.0).
    - Stock: valid boolean, integer, or recognized status string.

    Returns:
        tuple[bool, Optional[str]]: (True, None) if valid, (False, error_reason) if invalid.
    """
    if not isinstance(item_data, dict):
        return False, "invalid_item_data_type"

    # 1. Medication Name Validation
    raw_name = (
        item_data.get("item_name")
        if item_data.get("item_name") is not None
        else item_data.get("name", item_data.get("normalized_name"))
    )
    if raw_name is None:
        return False, "missing_item_name"

    name_str = str(raw_name).strip()
    if not name_str:
        return False, "empty_item_name"
    if len(name_str) < 2:
        return False, "name_too_short"

    if is_genuine_header_cell(name_str):
        return False, f"header_token_in_name: {name_str}"

    if is_catalog_noise(name_str) or re.search(r'مخزن\s+.*(?:تجاره|تجارة|ادويه|أدوية|فارما|جمله)', name_str):
        return False, f"catalog_noise_in_name: {name_str}"

    try:
        from .pdf_font_decoder import has_suspicious_characters
    except ImportError:
        from pdf_font_decoder import has_suspicious_characters
    has_susp, susp_reasons = has_suspicious_characters(name_str)
    if has_susp:
        return False, f"suspicious_characters_in_name: {susp_reasons[0]}"

    norm_lower = unicodedata.normalize("NFKD", name_str).lower().strip()
    header_exact_tokens = {
        "اسم", "صنف", "اسم الصنف", "الصنف", "البيان", "دواء", "اسم الدواء",
        "name", "item", "item name", "product", "product name", "description",
        "سعر", "السعر", "سعر الجمهور", "جمهور", "رسمي", "price", "public", "base", "base price",
        "خصم", "الخصم", "نسبة", "نسبة الخصم", "disc", "disc%", "disc %", "discount",
        "رصيد", "كمية", "الكمية", "حالة", "توفر", "متاح", "stock", "qty", "status", "avail",
        "كود", "الكود", "code", "item code", "باركود", "barcode", "مسلسل", "م", "ت", "no", "sn", "#",
        "فنصلا", "فنصلا مسا", "رعسلا", "رعس", "مصخلا", "مصخ", "منسصالا", "فنصلفا"
    }
    if norm_lower in header_exact_tokens or norm_lower.strip(".:/\\- #") in header_exact_tokens:
        return False, f"header_token_in_name: {name_str}"

    # OCR Digit Reversal and Loss Suspicion Signals
    # Flags critical numeric corruption in packs and strengths (e.g. 14->41, 17->71, 28->82 or dropped zero)
    m_pack = re.search(r'(\d+)\s*(?:قرص|كبسول|كيس|امبول|فيال|شريط|تاب)', name_str)
    pack_num = int(m_pack.group(1)) if m_pack else None
    if pack_num in (41, 71, 82):
        return False, "suspicious_pack_size"

    norm_brand = unicodedata.normalize("NFKD", name_str).strip()
    if re.search(r'\b(?:اتور|اتورستات)\s+1\s*(?:مجم|mg)\b', norm_brand):
        return False, "suspicious_pack_size" if pack_num in (41, 71, 82) else "suspicious_ocr_strength"
    if re.search(r'\b(?:اتورستات)\s+[48]\s*(?:مجم|mg)\b', norm_brand):
        return False, "suspicious_pack_size" if pack_num in (41, 71, 82) else "suspicious_ocr_strength"
    if re.search(r'\b(?:اجركس)\s+57\s*(?:مجم|mg)\b', norm_brand):
        return False, "suspicious_ocr_strength"
    if re.search(r'\b(?:اركوكسيا)\s+21\s*(?:مجم|mg)\b', norm_brand):
        return False, "suspicious_ocr_strength"
    if re.search(r'\b(?:افيفافاسك)\s+[68]/\d+\s*(?:مجم|mg)\b', norm_brand):
        return False, "suspicious_pack_size" if pack_num in (41, 71, 82) else "suspicious_ocr_strength"
    if re.search(r'\b(?:اكساميد)\s+[12]\s*(?:مجم|mg)\b', norm_brand):
        return False, "suspicious_ocr_strength"
    if re.search(r'\b(?:البيندازول)\s+4\s*(?:مجم|mg)\b', norm_brand):
        return False, "suspicious_ocr_strength"

    # Import-only uncertainty checks. Do not impose a universal strength limit
    # on digital source text, and do not change shared search normalization.
    is_ocr = bool(item_data.get("_ocr_engine_used")) or "ocr" in str(item_data.get("_extraction_method", "")).lower()
    if is_ocr:
        if item_data.get("_ocr_engine_used") == "rapidocr":
            return False, "unverified_ocr_engine"
        if re.search(r'\d+[.\u066b]\s+\d', name_str):
            return False, "ambiguous_ocr_decimal"
        ratio = re.search(r'\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)+', name_str)
        if ratio and item_data.get("_ocr_strength_verified") is not True:
            return False, "unverified_ocr_strength_sequence"

    # 2. Price Validation
    raw_price = (
        item_data.get("base_price")
        if "base_price" in item_data
        else item_data.get("price", item_data.get("Price"))
    )
    if raw_price is None:
        return False, "missing_price"
    if isinstance(raw_price, bool):
        return False, "invalid_price_boolean"

    try:
        if isinstance(raw_price, str):
            clean_p = raw_price.translate(ALL_EASTERN_DIGITS).replace(",", ".").strip()
            price_val = float(clean_p)
        else:
            price_val = float(raw_price)
    except (ValueError, TypeError):
        return False, f"invalid_price_format: {raw_price}"

    if math.isnan(price_val) or math.isinf(price_val):
        return False, "invalid_price_nan_or_inf"

    if price_val <= 0.0:
        return False, f"invalid_price_zero_or_negative: {price_val}"
    if price_val >= 10000.0:
        return False, f"invalid_price_out_of_bounds: {price_val}"

    # 3. Discount Validation
    raw_discount = None
    has_discount_key = False
    for k in ("discount_rate", "discount", "Discount", "disc"):
        if k in item_data:
            raw_discount = item_data[k]
            has_discount_key = True
            break

    if has_discount_key and raw_discount is not None:
        if isinstance(raw_discount, bool):
            return False, "invalid_discount_boolean"
        if isinstance(raw_discount, str) and not raw_discount.strip():
            # Blank discount represented as empty string -> treated as None (blank discount)
            discount_val = None
        else:
            try:
                if isinstance(raw_discount, str):
                    s_disc = raw_discount.strip()
                    if is_explicit_zero_discount(s_disc):
                        discount_val = 0.0
                    else:
                        is_pct = "%" in s_disc
                        clean_disc = s_disc.replace("%", "").replace(",", ".").translate(ALL_EASTERN_DIGITS).strip()
                        raw_num = float(clean_disc)
                        if is_pct or raw_num > 1.0:
                            discount_val = raw_num / 100.0
                        else:
                            discount_val = raw_num
                else:
                    discount_val = float(raw_discount)
            except (ValueError, TypeError):
                return False, f"invalid_discount_format: {raw_discount}"

            if discount_val is not None:
                if math.isnan(discount_val) or math.isinf(discount_val):
                    return False, "invalid_discount_nan_or_inf"
                if discount_val < 0.0:
                    return False, f"invalid_discount_negative: {discount_val}"
                if discount_val > 0.85:
                    return False, f"invalid_discount_out_of_bounds: {discount_val}"

    # 4. Stock Validation (optional field)
    raw_stock = (
        item_data.get("stock_status")
        if "stock_status" in item_data
        else item_data.get("stock", item_data.get("Stock"))
    )
    if raw_stock is not None:
        if not isinstance(raw_stock, (bool, int, str)):
            return False, f"invalid_stock_type: {type(raw_stock).__name__}"

    return True, None

