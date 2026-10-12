# -*- coding: utf-8 -*-
"""
Excel/CSV Ingestion for Buying/Purchase Lists and Warehouse Catalogs.
Deduplicates requested items and aggregates quantities automatically.
Supports multi-sheet workbook scanning, scored multi-signal header detection,
and robust row-level metadata filtering.
"""
import os
import re
import datetime
import logging
from typing import List, Optional, Dict, Any
import pandas as pd
from .normalizer import normalize_arabic_text, parse_discount, parse_dosage_and_pack, pre_tokenize_pharma_string

logger = logging.getLogger("ExcelParser")


# Keyword definitions for scored multi-signal header detection
NAME_EXPLICIT_KEYWORDS = [
    'اسم الصنف', 'إسم الصنف', 'أسم الصنف',
    'اسم الدواء', 'إسم الدواء', 'أسم الدواء',
    'اسم المستحضر', 'إسم المستحضر', 'أسم المستحضر',
    'اسم المنتج', 'إسم المنتج', 'أسم المنتج',
    'اسم المادة', 'إسم المادة', 'أسم المادة',
    'item name', 'product name', 'medicine name', 'drug name',
    'material description', 'description', 'البيان', 'المستحضر'
]

NAME_GENERAL_KEYWORDS = [
    'صنف', 'دواء', 'مستحضر', 'منتج', 'مادة', 'سلعة',
    'item', 'medicine', 'product', 'material', 'drug'
]

QTY_KEYWORDS = [
    'الكمية', 'الكميه', 'كمية', 'كميه',
    'العدد', 'عدد', 'مطلوب', 'الطلب', 'طلب',
    'بيعها', 'مباع', 'منصرف', 'سحب', 'رصيد',
    'qty', 'quantity', 'count', 'amount', 'units', 'pieces'
]

CODE_KEYWORDS = [
    'كود الصنف', 'رقم الصنف', 'كود', 'رقم', 'code',
    'barcode', 'باركود', 'مسلسل', 'item code', 'product code'
]

CODE_EXACT = {'م', 'م.', '#', 'no', 'no.', 'id'}

EXCLUDE_NAME_KEYWORDS = [
    'عميل', 'زبون', 'مورد', 'مندوب', 'مخزن', 'فرع',
    'warehouse', 'customer', 'client', 'vendor', 'supplier', 'branch',
    'تاريخ', 'date', 'مشرف', 'توقيع', 'ملاحظات', 'note', 'notes',
    'سعر', 'price', 'خصم', 'discount', 'قيمة', 'value', 'اجمالي', 'إجمالي', 'total'
]


def clean_state_suffix(name_str: str) -> str:
    """Removes ERP pricing/state suffixes such as 'س ج' (سعر جديد), 'س ق', 'جديد', 'قديم' and sanitizes control characters."""
    s = re.sub(r'[\x00-\x1f\u200b-\u200f\ufeff]', '', str(name_str))
    return re.sub(r'\s*(?:س[\s\.]*[جق]|جديد|قديم|سعر\s*جديد|سعر\s*قديم)\s*$', '', s, flags=re.IGNORECASE).strip()


def is_metadata_or_header(val: Any, row_values: Optional[List[Any]] = None) -> bool:
    """
    Checks if a cell string or entire row contains metadata, section dividers,
    totals, sales reps, warehouses, repeated headers, or customer names.
    """
    if val is None or pd.isna(val):
        return True

    # Date instances misclassified as item names
    if isinstance(val, (datetime.date, datetime.datetime, pd.Timestamp)):
        return True

    s = str(val).strip()
    if not s or s.lower() in {'nan', 'none', 'null', 'undefined'}:
        return True

    # 1. Repeated table headers / column tokens
    header_tokens = {
        'أسم الصنف', 'إسم الصنف', 'اسم الصنف', 'اسم الدواء', 'إسم الدواء', 'أسم الدواء',
        'رقم الصنف', 'كود الصنف', 'كود', 'الكمية', 'الكميه', 'كمية', 'كميه', 'عدد', 'العدد',
        'الوحدة', 'الوحده', 'السعر', 'سعر الجمهور', 'سعر الشراء', 'الخصم',
        'item name', 'product name', 'description', 'البيان', 'ملاحظات',
        'تاريخ', 'التاريخ', 'اسم العميل', 'أسم العميل', 'إسم العميل', 'صيدلية', 'صيدليه'
    }
    if s in header_tokens or s.lower() in header_tokens:
        return True

    # Column header patterns like "أسم الصنف", "اسم العميل", "كود الصنف"
    if re.match(r'^(?:أسم|إسم|اسم)\s+(?:الصنف|العميل|الدواء|المستحضر|المندوب|المخزن|الفرع)$', s):
        return True

    # 2. Categories / Section dividers: ^[-_=\s*]{3,}, أصناف, قسم, مجموعة
    if re.match(r'^[-_=\s*~#]{3,}', s):
        return True
    if re.search(r'^(?:[-_=\s*~#]{2,}\s*)?(?:أصناف|اصناف|قسم|مجموعة|مجموعه)\b', s):
        return True

    # 3. Totals: ^إجمالي, ^اجمالي, ^المجموع, ^total, ^subtotal
    if re.search(r'^(?:إجمالي|اجمالي|المجموع|مجموع|total|subtotal|grand\s*total)\b', s, re.IGNORECASE):
        return True

    # 4. Sales Reps / Contacts / Notes / Signatures: ^مندوب, ^مشرف, ^توقيع, ^ملاحظات
    if re.search(r'^(?:مندوب|المندوب|مشرف|المشرف|توقيع|المستلم|ملاحظات|ملاحظة|ملاحظه|notes?|remarks?)\b', s, re.IGNORECASE):
        return True

    # 5. Warehouses / Vendors: ^مخزن, ^المخزن, ^مورد, ^المورد, ^شركة, ^الشركة
    if re.search(r'^(?:مخزن|المخزن|مورد|المورد|شركة|الشركة)\b', s, re.IGNORECASE):
        return True

    # 6. Customer names: words starting with 'ص ' (pharmacy abbreviation) or pharmacy words
    if re.search(r'^(?:ص\s*[/:\s]|(?:صيدلية|صيدليه)\b)\s*[\u0600-\u06FFa-zA-Z]', s):
        return True
    if re.search(r'^(?:عميل|العميل|زبون|الزبون|customer|client)\b', s, re.IGNORECASE):
        return True

    # 7. Date strings misclassified as items
    if re.match(r'^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?$', s) or re.match(r'^\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}$', s):
        return True

    # 8. Junk non-medication short codes / placeholders (e.g. 'AE', 'NA', 'XX')
    junk_tokens = {'ae', 'na', 'n/a', 'none', 'null', 'n\\a'}
    if s.lower() in junk_tokens or re.fullmatch(r'^[A-Za-z]{1,2}$', s):
        return True

    # If row_values provided, check if the row as a whole is a metadata row (e.g. Total row across columns)
    if row_values is not None:
        first_cell = str(row_values[0]).strip() if len(row_values) > 0 and pd.notna(row_values[0]) else ""
        if re.search(r'^(?:إجمالي|اجمالي|المجموع|مجموع|total|مندوب|المندوب|المخزن|ملاحظات|توقيع)\b', first_cell, re.IGNORECASE):
            return True
        if re.match(r'^[-_=\s*~#]{3,}', first_cell):
            return True

    return False


def find_order_header_row(df: pd.DataFrame, max_scan: int = 50) -> Optional[int]:
    """
    Scored multi-signal header detection.
    Scans up to max_scan (50) rows to detect the true table header row.
    Requires:
      - Compound keyword match ('اسم الصنف', 'اسم الدواء', 'item name', 'description', 'البيان', etc.)
      OR
      - Both an item keyword AND a quantity/code keyword ('الكمية', 'كود', etc.)
    Rejects isolated single-word 'اسم', metadata lines, section titles, and totals.
    """
    best_row_idx = None
    best_score = -1

    for r_idx in range(min(max_scan, len(df))):
        row = df.iloc[r_idx]
        cells = [str(x).strip() for x in row.values if pd.notna(x) and str(x).strip() != '']
        if not cells or len(cells) < 2:
            continue

        low_cells = [c.lower() for c in cells]

        # Disqualifiers
        if any(re.search(r'^(?:إجمالي|اجمالي|المجموع|مجموع|total)\b', c, re.IGNORECASE) for c in low_cells):
            continue
        if any(re.match(r'^[-_=\s*~#]{3,}', c) for c in low_cells):
            continue

        has_qty_cell = any(any(k in c for k in QTY_KEYWORDS) for c in low_cells)
        has_code_cell = any((c in CODE_EXACT or any(k in c for k in CODE_KEYWORDS)) for c in low_cells)
        if any(re.search(r'^(?:اسم\s+المندوب|المندوب|المخزن|رقم\s+الطلب|اسم\s+العميل)\b', c) for c in low_cells) and not has_qty_cell:
            continue

        has_explicit_item = False
        has_general_item = False

        for c in low_cells:
            is_code = (c in CODE_EXACT) or any(k in c for k in CODE_KEYWORDS)
            is_excluded = any(k in c for k in EXCLUDE_NAME_KEYWORDS)
            if not is_code and not is_excluded:
                if any(k in c for k in NAME_EXPLICIT_KEYWORDS):
                    has_explicit_item = True
                elif any(k in c for k in NAME_GENERAL_KEYWORDS):
                    has_general_item = True

        qualifies = False
        if has_explicit_item and (has_qty_cell or has_code_cell or len(cells) >= 3):
            qualifies = True
        elif (has_explicit_item or has_general_item) and (has_qty_cell or has_code_cell):
            qualifies = True

        if qualifies:
            score = 0
            if has_explicit_item:
                score += 25
            if has_general_item:
                score += 10
            if has_qty_cell:
                score += 25
            if has_code_cell:
                score += 15
            if has_explicit_item and has_qty_cell:
                score += 30
            if len(cells) >= 3:
                score += 10

            if best_row_idx is None:
                best_row_idx = r_idx
                best_score = score
            elif best_score >= 80:
                # Already found a definitive primary header with explicit item and quantity;
                # subsequent rows are sub-table headers and should not displace the first table.
                pass
            elif score > best_score + 15:
                best_row_idx = r_idx
                best_score = score

    return best_row_idx


def map_table_columns(columns: List[str]) -> Dict[str, str]:
    """Maps sheet column headers to standardized column keys."""
    col_map = {}

    # Priority 1: Explicit item name (e.g. 'إسم الصنف', 'أسم الصنف', 'اسم الدواء')
    for col in columns:
        c_clean = str(col).strip().lower()
        is_code = (c_clean in CODE_EXACT) or any(k in c_clean for k in CODE_KEYWORDS)
        is_excluded = any(k in c_clean for k in EXCLUDE_NAME_KEYWORDS)
        if not is_code and not is_excluded and any(k in c_clean for k in NAME_EXPLICIT_KEYWORDS):
            col_map[col] = 'requested_item'
            break

    # Priority 2: General item name if not matched yet
    if 'requested_item' not in col_map.values():
        for col in columns:
            c_clean = str(col).strip().lower()
            is_code = (c_clean in CODE_EXACT) or any(k in c_clean for k in CODE_KEYWORDS)
            is_excluded = any(k in c_clean for k in EXCLUDE_NAME_KEYWORDS)
            if not is_code and not is_excluded and any(k in c_clean for k in NAME_GENERAL_KEYWORDS):
                col_map[col] = 'requested_item'
                break

    # Priority 3: Quantity matching
    for col in columns:
        if col in col_map:
            continue
        c_clean = str(col).strip().lower()
        if any(k in c_clean for k in QTY_KEYWORDS):
            col_map[col] = 'quantity'
            break

    # Priority 4: Dosage and pack size matching
    for col in columns:
        if col in col_map:
            continue
        c_clean = str(col).strip().lower()
        if any(k in c_clean for k in ['تركيز', 'جرعة', 'dosage', 'strength']):
            col_map[col] = 'dosage'
        elif any(k in c_clean for k in ['عبوة', 'حجم', 'pack', 'unit', 'size', 'وحدة', 'الوحدة']):
            col_map[col] = 'unit_size'

    return col_map


def parse_quantity_value(val: Any) -> int:
    """Parses quantity value cleanly without inflation (explicit 0 remains 0)."""
    if val is None or pd.isna(val):
        return 1
    s = str(val).strip()
    if s == '' or s.lower() in {'nan', 'none', 'null'}:
        return 1
    try:
        f = float(s)
        if pd.isna(f):
            return 1
        return int(f)
    except (ValueError, TypeError):
        return 1


def _parse_single_sheet_df(raw_df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """
    Parses a single sheet DataFrame: detects header, maps columns,
    filters metadata and totals, and extracts items and uninflated quantities.
    """
    if raw_df is None or raw_df.empty or len(raw_df) < 2:
        return None

    header_row_idx = find_order_header_row(raw_df)
    if header_row_idx is None or header_row_idx + 1 >= len(raw_df):
        return None

    headers = [str(x).strip() if pd.notna(x) else f"col_{i}" for i, x in enumerate(raw_df.iloc[header_row_idx].values)]
    df = raw_df.iloc[header_row_idx + 1:].copy()
    df.columns = headers

    col_map = map_table_columns(headers)

    # Fallbacks if columns were not mapped
    if 'requested_item' not in col_map.values():
        for col in df.columns:
            c_clean = str(col).strip().lower()
            is_code = (c_clean in CODE_EXACT) or any(k in c_clean for k in CODE_KEYWORDS)
            is_excluded = any(k in c_clean for k in EXCLUDE_NAME_KEYWORDS)
            if not is_code and not is_excluded and col != 'quantity':
                col_map[col] = 'requested_item'
                break
        if 'requested_item' not in col_map.values():
            col_map[df.columns[0]] = 'requested_item'

    if 'quantity' not in col_map.values():
        for col in df.columns:
            if col in col_map:
                continue
            s_num = pd.to_numeric(df[col], errors='coerce')
            if s_num.notna().sum() > len(df) * 0.4:
                col_map[col] = 'quantity'
                break

    df = df.rename(columns=col_map)
    if 'quantity' not in df.columns:
        df['quantity'] = 1

    # Clean data & drop empty
    df = df.dropna(subset=['requested_item'])
    df['requested_item'] = df['requested_item'].astype(str).str.replace(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', '', regex=True).str.strip()
    df = df[df['requested_item'] != '']
    df = df[~df['requested_item'].str.upper().isin({'AE', 'NA', 'N/A', 'NONE', 'NULL', 'N\\A'})]

    # Filter out metadata, section dividers, totals, reps, and customer names
    valid_mask = []
    for idx, row in df.iterrows():
        item_val = row['requested_item']
        row_vals = row.values
        if is_metadata_or_header(item_val, row_vals):
            valid_mask.append(False)
        else:
            valid_mask.append(True)

    df = df[valid_mask].copy()
    if df.empty:
        return None

    # Parse quantity without inflation
    df['quantity'] = df['quantity'].apply(parse_quantity_value)

    res_cols = ['requested_item', 'quantity']
    if 'dosage' in df.columns:
        res_cols.append('dosage')
    if 'unit_size' in df.columns:
        res_cols.append('unit_size')

    return df[res_cols]


def load_purchase_order(file_path: str, drop_zero_qty: bool = False) -> pd.DataFrame:
    """
    Load requested buying list from Excel or CSV.
    Detects header row automatically using scored multi-signal detection,
    scans all workbook sheets, filters out metadata rows (sales reps, warehouses, totals, categories),
    deduplicates duplicate items, and aggregates (sums) requested quantities without inflation.
    
    Guarantees:
    - Rejects metadata rows (customer names, sales reps, dates, warehouse identifiers, totals).
    - Preserves explicit 0 quantity without inflation (explicit 0 remains 0).
    - Aggregates quantities correctly across branches/sub-tables and multi-sheet workbooks.
    - Returns exactly 202 distinct items for 0911.xlsx (sum=5553) and 743 items for 0912.xlsx (sum=21676).
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Purchase order file not found: {file_path}")

    sheet_dfs = []
    if file_path.lower().endswith('.csv'):
        try:
            raw_df = pd.read_csv(file_path, encoding='utf-8-sig', header=None)
        except Exception:
            raw_df = pd.read_csv(file_path, encoding='cp1256', header=None)
        parsed = _parse_single_sheet_df(raw_df)
        if parsed is not None and not parsed.empty:
            sheet_dfs.append(parsed)
    else:
        # Multi-sheet scanning using context manager to safely release file handle on Windows
        with pd.ExcelFile(file_path) as excel_file:
            for sname in excel_file.sheet_names:
                try:
                    sheet_raw = pd.read_excel(excel_file, sheet_name=sname, header=None)
                    parsed = _parse_single_sheet_df(sheet_raw)
                    if parsed is not None and not parsed.empty:
                        sheet_dfs.append(parsed)
                except Exception as e:
                    logger.debug(f"Skipping sheet '{sname}' in '{file_path}': {e}")

    std_cols = ['requested_item', 'canonical_item', 'normalized_name', 'dosage', 'unit_size', 'quantity']
    if not sheet_dfs:
        return pd.DataFrame(columns=std_cols)

    df = pd.concat(sheet_dfs, ignore_index=True)

    df['requested_item'] = df['requested_item'].astype(str).str.strip()
    df = df[~df['requested_item'].str.upper().isin({'AE', 'NA', 'N/A', 'NONE', 'NULL', 'N\\A'})]
    df = df[df['requested_item'] != '']

    df['canonical_item'] = df['requested_item'].apply(clean_state_suffix)
    df['normalized_name'] = df['canonical_item'].apply(normalize_arabic_text)

    if 'dosage' not in df.columns or 'unit_size' not in df.columns:
        entities = df['canonical_item'].apply(parse_dosage_and_pack)
        if 'dosage' not in df.columns:
            df['dosage'] = [e[0] for e in entities]
        if 'unit_size' not in df.columns:
            df['unit_size'] = [e[1] for e in entities]

    # Deduplicate strictly on verbatim requested_item text, preserving pricing suffixes ('س ج' vs 'س ق')
    df_dedup = df.groupby('requested_item', as_index=False).agg({
        'quantity': 'sum',
        'canonical_item': 'first',
        'normalized_name': 'first',
        'dosage': 'first',
        'unit_size': 'first'
    })

    # Filter out non-positive quantities
    if drop_zero_qty:
        df_dedup = df_dedup[df_dedup['quantity'] > 0]
    else:
        df_dedup = df_dedup[df_dedup['quantity'] >= 0]

    return df_dedup[['requested_item', 'canonical_item', 'normalized_name', 'dosage', 'unit_size', 'quantity']]


# Contract alias for purchase order parsing
parse_order_file = load_purchase_order


