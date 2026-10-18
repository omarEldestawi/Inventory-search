# -*- coding: utf-8 -*-
"""
Average Discounts Ingestion and Resolution Module.
Handles loading, dynamic header discovery, marker stripping, discount rate normalization,
and default dataset path resolution for Egyptian pharmacy inventory files ('أرصده المخازن' / 'خصم مرجح').
"""
import os
import sys
import re
import logging
from typing import Optional, List, Dict, Any, Tuple
import pandas as pd

logger = logging.getLogger("AverageDiscounts")


def resolve_default_avg_discounts_path() -> Optional[str]:
    """
    Resolves the default bundled average discounts reference dataset path.
    Checks in order:
      1. Development paths:
         - <project_root>/data/average_discounts.xlsx
         - <cwd>/data/average_discounts.xlsx
         - data/average_discounts.xlsx
      2. User local AppData:
         - %LOCALAPPDATA%/EgyptianPharmaOptimizer/data/average_discounts.xlsx
      3. PyInstaller sys._MEIPASS:
         - sys._MEIPASS/data/average_discounts.xlsx
      4. Frozen executable directory:
         - <exe_dir>/data/average_discounts.xlsx
         - <exe_dir>/_internal/data/average_discounts.xlsx

    Returns the absolute path if an existing file is found, else None.
    """
    candidates = []

    # 1. Project development root
    try:
        module_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(module_dir)
        candidates.append(os.path.join(project_root, "data", "average_discounts.xlsx"))
    except Exception:
        pass

    candidates.append(os.path.join(os.getcwd(), "data", "average_discounts.xlsx"))
    candidates.append(os.path.abspath("data/average_discounts.xlsx"))

    # 2. %LOCALAPPDATA%
    local_app_data = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    candidates.append(os.path.join(local_app_data, "EgyptianPharmaOptimizer", "data", "average_discounts.xlsx"))

    # 3. PyInstaller sys._MEIPASS
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, "data", "average_discounts.xlsx"))

    # 4. sys.executable directory (frozen / distributed app)
    if getattr(sys, "frozen", False) or sys.executable:
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidates.append(os.path.join(exe_dir, "data", "average_discounts.xlsx"))
        candidates.append(os.path.join(exe_dir, "_internal", "data", "average_discounts.xlsx"))

    for c in candidates:
        if c and os.path.isfile(c):
            return os.path.normpath(os.path.abspath(c))

    return None


def clean_medication_display_name(text: str) -> str:
    """
    Strips prefix and suffix marker tokens like 'xx...xx', 'x...x', or surrounding
    whitespace while preserving the core Arabic and English medication names.
    Preserves legitimate pharmaceutical brand names starting or ending in X/x
    (e.g., 'Xanax', 'Lasix', 'Celebrex', 'Zovirax').

    Example:
      'xxالفينترن30قرصxx' -> 'الفينترن30قرص'
      'xxXanaxxx' -> 'Xanax'
      'Xanax 0.5mg' -> 'Xanax 0.5mg'
      'Lasix' -> 'Lasix'
      'Celebrex' -> 'Celebrex'
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)

    cleaned = text.strip()

    # 1. Strip marker if adjacent to Arabic or whitespace
    cleaned = re.sub(r'(?i)^\s*x+\s*(?=[\u0600-\u06FF\s])', '', cleaned)
    cleaned = re.sub(r'(?i)(?<=[\u0600-\u06FF\s])\s*x+\s*$', '', cleaned)

    # 2. Strip leading x{2,} marker
    # If followed by capital letter + lowercase (e.g. xxXanax), strip marker without swallowing capital X
    cleaned = re.sub(r'^[xX]{2,}(?=[A-Z][a-z])', '', cleaned)
    # Otherwise strip leading x{2,}
    cleaned = re.sub(r'(?i)^\s*x{2,}\s*', '', cleaned)

    # 3. Strip trailing x{2,} marker
    # If preceded by a consonant/vowel + x (e.g. Lasix + xx -> Lasixxx, Xanax + xx -> Xanaxxx)
    cleaned = re.sub(r'(?<=[a-zA-Z]x)[xX]{2,}\s*$', '', cleaned)
    # Otherwise strip trailing x{2,}
    cleaned = re.sub(r'(?i)\s*x{2,}\s*$', '', cleaned)

    return cleaned.strip()


def _normalize_discount_rate(val: Any) -> Optional[float]:
    """
    Normalizes a discount rate into a float in [0.0, 1.0].
    If the string input contains '%', divides by 100.0 directly (e.g. '1%' -> 0.01).
    If numeric (or string without '%') and > 1.0, divides by 100.0 (e.g. 25.0 -> 0.25).
    """
    if val is None or pd.isna(val):
        return None

    is_pct_str = False
    if isinstance(val, str):
        val_clean = val.strip()
        if '%' in val_clean:
            is_pct_str = True
            val_clean = val_clean.replace('%', '').strip()
        try:
            val_float = float(val_clean)
        except ValueError:
            return None
    else:
        try:
            val_float = float(val)
        except (ValueError, TypeError):
            return None

    if is_pct_str:
        val_float = val_float / 100.0
    elif val_float > 1.0:
        val_float = val_float / 100.0

    return max(0.0, min(1.0, val_float))


def _find_excel_headers(file_path: str) -> Tuple[Optional[str], Optional[int], Optional[int], Optional[int]]:
    """
    Dynamically scans sheets and top rows of an Excel workbook to locate
    the target sheet, header row index (0-indexed), name column index, and discount column index.
    """
    name_keywords = ['إسم الصنف', 'اسم الصنف', 'الصنف', 'صنف', 'item_name', 'item name', 'اسم_الصنف', 'إسم_الصنف']
    disc_keywords = ['خصم مرجح', 'الخصم المرجح', 'مرجح', 'avg_discount', 'avg discount', 'weighted_discount', 'weighted discount', 'خصم_مرجح', 'الخصم_المرجح']

    # Try openpyxl first
    try:
        import openpyxl
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        try:
            for sname in wb.sheetnames:
                ws = wb[sname]
                for r_idx, row in enumerate(ws.iter_rows(values_only=True)):
                    if r_idx >= 30:
                        break
                    row_strs = [str(c).strip() if c is not None else "" for c in row]
                    n_col = next((i for i, s in enumerate(row_strs) if any(k in s for k in name_keywords)), None)
                    d_col = next((i for i, s in enumerate(row_strs) if any(k in s for k in disc_keywords)), None)
                    if n_col is not None and d_col is not None and n_col != d_col:
                        return sname, r_idx, n_col, d_col
        finally:
            wb.close()
    except Exception as exc:
        logger.debug(f"openpyxl scan failed for {file_path}: {exc}")

    # Fallback to pandas ExcelFile with context manager to prevent Windows file descriptor leak
    try:
        with pd.ExcelFile(file_path) as xl:
            for sname in xl.sheet_names:
                peek_df = pd.read_excel(xl, sheet_name=sname, header=None, nrows=30)
                for r_idx, row in peek_df.iterrows():
                    row_strs = [str(c).strip() if pd.notna(c) else "" for c in row]
                    n_col = next((i for i, s in enumerate(row_strs) if any(k in s for k in name_keywords)), None)
                    d_col = next((i for i, s in enumerate(row_strs) if any(k in s for k in disc_keywords)), None)
                    if n_col is not None and d_col is not None and n_col != d_col:
                        return sname, int(r_idx), n_col, d_col
    except Exception as exc:
        logger.debug(f"pandas ExcelFile scan failed for {file_path}: {exc}")

    return None, None, None, None


def _load_excel_discounts(file_path: str) -> pd.DataFrame:
    """Parses an Excel file (.xlsx, .xls) into a normalized DataFrame."""
    sname, header_row, n_col, d_col = _find_excel_headers(file_path)
    if sname is None or header_row is None:
        raise ValueError(f"Could not locate medication name and weighted discount columns in {file_path}")

    # Use openpyxl read_only stream for fast extraction
    records = []
    try:
        import openpyxl
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        try:
            ws = wb[sname]
            for r_idx, row in enumerate(ws.iter_rows(values_only=True)):
                if r_idx <= header_row:
                    continue
                if n_col >= len(row) or d_col >= len(row):
                    continue
                raw_name = row[n_col]
                raw_disc = row[d_col]
                if raw_name is None:
                    continue
                raw_name_str = str(raw_name).strip()
                if not raw_name_str or raw_name_str.lower() in ['none', 'nan']:
                    continue
                norm_rate = _normalize_discount_rate(raw_disc)
                if norm_rate is None:
                    continue
                clean_name = clean_medication_display_name(raw_name_str)
                if not clean_name:
                    continue
                records.append({
                    'raw_name': raw_name_str,
                    'clean_name': clean_name,
                    'avg_discount_rate': norm_rate
                })
        finally:
            wb.close()
    except Exception as exc:
        logger.debug(f"openpyxl stream read failed, falling back to pd.read_excel: {exc}")
        df_raw = pd.read_excel(file_path, sheet_name=sname, skiprows=header_row + 1, header=None)
        records = []
        for _, row in df_raw.iterrows():
            if n_col >= len(row) or d_col >= len(row):
                continue
            raw_name = row.iloc[n_col]
            raw_disc = row.iloc[d_col]
            if pd.isna(raw_name):
                continue
            raw_name_str = str(raw_name).strip()
            if not raw_name_str or raw_name_str.lower() in ['none', 'nan']:
                continue
            norm_rate = _normalize_discount_rate(raw_disc)
            if norm_rate is None:
                continue
            clean_name = clean_medication_display_name(raw_name_str)
            if not clean_name:
                continue
            records.append({
                'raw_name': raw_name_str,
                'clean_name': clean_name,
                'avg_discount_rate': norm_rate
            })

    return pd.DataFrame(records)


def _load_csv_discounts(file_path: str) -> pd.DataFrame:
    """Parses a CSV file into a normalized DataFrame."""
    name_keywords = ['إسم الصنف', 'اسم الصنف', 'الصنف', 'صنف', 'item_name', 'item name']
    disc_keywords = ['خصم مرجح', 'الخصم المرجح', 'مرجح', 'avg_discount', 'weighted_discount']

    encodings = ['utf-8-sig', 'cp1256', 'utf-8', 'latin1']
    content_df = None
    for enc in encodings:
        try:
            # Detect header row within first 20 lines
            header_row_idx = None
            with open(file_path, 'r', encoding=enc, errors='replace') as fp:
                for idx in range(25):
                    line = fp.readline()
                    if not line:
                        break
                    if any(k in line for k in name_keywords) and any(k in line for k in disc_keywords):
                        header_row_idx = idx
                        break
            if header_row_idx is not None:
                content_df = pd.read_csv(file_path, skiprows=header_row_idx, encoding=enc)
                break
            else:
                content_df = pd.read_csv(file_path, encoding=enc)
                break
        except Exception:
            continue

    if content_df is None or content_df.empty:
        raise ValueError(f"Could not read CSV file: {file_path}")

    # Identify name and discount columns
    name_col = None
    disc_col = None
    for col in content_df.columns:
        c_str = str(col).strip()
        if not name_col and any(k in c_str for k in name_keywords):
            name_col = col
        if not disc_col and any(k in c_str for k in disc_keywords):
            disc_col = col

    if not name_col or not disc_col:
        raise ValueError(f"Could not locate name and discount columns in CSV: {file_path}")

    records = []
    for _, row in content_df.iterrows():
        raw_name = row[name_col]
        raw_disc = row[disc_col]
        if pd.isna(raw_name):
            continue
        raw_name_str = str(raw_name).strip()
        if not raw_name_str or raw_name_str.lower() in ['none', 'nan']:
            continue
        norm_rate = _normalize_discount_rate(raw_disc)
        if norm_rate is None:
            continue
        clean_name = clean_medication_display_name(raw_name_str)
        if not clean_name:
            continue
        records.append({
            'raw_name': raw_name_str,
            'clean_name': clean_name,
            'avg_discount_rate': norm_rate
        })

    return pd.DataFrame(records)


def load_average_discounts_file(file_path: Optional[str] = None) -> pd.DataFrame:
    """
    Loads and normalizes an average discounts reference file (.xlsx, .xls, .csv).
    If file_path is None, automatically resolves the default bundled path.

    Returns a DataFrame with columns:
      - 'raw_name': Verbatim medication name from source file
      - 'clean_name': Medication name with 'xx...xx' markers stripped
      - 'avg_discount_rate': Normalized discount rate as decimal float in [0.0, 1.0]

    Deduplicates records keeping the maximum discount rate per clean medication name.
    """
    if file_path is None:
        file_path = resolve_default_avg_discounts_path()

    if not file_path or not os.path.isfile(file_path):
        raise FileNotFoundError(f"Average discounts reference file not found: {file_path}")

    ext = os.path.splitext(file_path)[1].lower()
    if ext in ['.xlsx', '.xls']:
        df = _load_excel_discounts(file_path)
    elif ext == '.csv':
        df = _load_csv_discounts(file_path)
    else:
        raise ValueError(f"Unsupported average discounts file extension: {ext} for {file_path}")

    if df.empty:
        return pd.DataFrame(columns=['raw_name', 'clean_name', 'avg_discount_rate'])

    # Deduplicate: Keep the highest average discount rate per clean_name
    df = df.sort_values(by=['clean_name', 'avg_discount_rate'], ascending=[True, False])
    df = df.drop_duplicates(subset=['clean_name'], keep='first').reset_index(drop=True)

    # Ensure required columns exist
    df = df[['raw_name', 'clean_name', 'avg_discount_rate']]

    # Verification assertion for default dataset
    if "average_discounts.xlsx" in os.path.basename(file_path) or "media_" in os.path.basename(file_path):
        assert len(df) > 2100, f"Expected >2,100 rows in reference average discounts, but found {len(df)}"

    return df
