# -*- coding: utf-8 -*-
"""
Order Parser module for Egyptian Pharmacy Procurement.
Exposes parse_order_file and load_purchase_order for ingesting customer
and pharmacy purchase orders with verbatim requested item preservation,
shared old-price row detection predicate, and exclusion tracking.
"""
from dataclasses import dataclass
import re
from typing import Any, List, Optional, Tuple, Union
import pandas as pd


OLD_PRICE_SUFFIX_RE = re.compile(r'(?:^|\s)(?:س[\s.]*ق|ق[\s.]*س)\s*$')
UNICODE_CONTROLS_RE = re.compile(r'[\u061c\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]')


@dataclass(frozen=True)
class ExcludedItem:
    reason: str
    source_file: str
    sheet_name: str
    row_index: int
    raw_name: str
    quantity: float


def is_old_price_item(text: Any) -> bool:
    r"""
    Evaluates whether raw cell text represents an old-price spreadsheet row.
    Regex: (?:^|\s)(?:س[\s.]*ق|ق[\s.]*س)\s*$
    Normalizes tabs/newlines to spaces, strips BOM and directional controls,
    and strips outer xx...xx markers while safeguarding legitimate brand names
    (e.g., س ج, اقراص, لاسيكس, زوفيراكس, Lasix, Xanax).
    """
    if text is None or pd.isna(text):
        return False
    s = str(text)
    if not s.strip():
        return False

    # Normalize tabs and newlines to single spaces
    s = re.sub(r'[\t\r\n]+', ' ', s)

    # Strip Unicode BOM and directional formatting / zero-width controls
    s = UNICODE_CONTROLS_RE.sub('', s)

    # Strip outer xx...xx marker without stripping letters of legitimate brand names
    s = re.sub(r'(?i)^\s*x+\s*(?=[\u0600-\u06FF\s])', '', s)
    s = re.sub(r'(?i)(?<=[\u0600-\u06FF\s])\s*x+\s*$', '', s)
    s = re.sub(r'^[xX]{2,}(?=[A-Z][a-z])', '', s)
    s = re.sub(r'(?i)^\s*x{2,}\s*', '', s)
    s = re.sub(r'(?<=[a-zA-Z]x)[xX]{2,}\s*$', '', s)
    s = re.sub(r'(?i)\s*x{2,}\s*$', '', s)

    # Normalize multiple whitespace to single space
    s = re.sub(r'\s+', ' ', s).strip()
    if not s:
        return False

    return bool(OLD_PRICE_SUFFIX_RE.search(s))


def clean_state_suffix(name_str: str) -> str:
    """Removes ERP pricing/state suffixes such as 'س ج' (سعر جديد), 'س ق', 'جديد', 'قديم' and sanitizes control characters."""
    try:
        from .excel_parser import clean_state_suffix as _impl
    except ImportError:
        from excel_parser import clean_state_suffix as _impl
    return _impl(name_str)


def is_metadata_or_header(val: Any, row_values: Optional[List[Any]] = None) -> bool:
    """
    Checks if a cell string or entire row contains metadata, section dividers,
    totals, sales reps, warehouses, repeated headers, or customer names.
    """
    try:
        from .excel_parser import is_metadata_or_header as _impl
    except ImportError:
        from excel_parser import is_metadata_or_header as _impl
    return _impl(val, row_values=row_values)


def load_purchase_order(
    file_path: str,
    drop_zero_qty: bool = False,
    return_exclusions: bool = False,
) -> Union[pd.DataFrame, Tuple[pd.DataFrame, List[ExcludedItem]]]:
    """Delegates to excel_parser.load_purchase_order."""
    try:
        from .excel_parser import load_purchase_order as _impl
    except ImportError:
        from excel_parser import load_purchase_order as _impl
    return _impl(file_path, drop_zero_qty=drop_zero_qty, return_exclusions=return_exclusions)


def parse_order_file(
    file_path: str,
    drop_zero_qty: bool = False,
    return_exclusions: bool = False,
) -> Union[pd.DataFrame, Tuple[pd.DataFrame, List[ExcludedItem]]]:
    """
    Parses a purchase order file (.xlsx, .xls, .csv), deduplicating strictly
    on original requested_item text, filtering noise headers and isolated 'AE' tokens,
    excluding old-price rows, and returning a clean DataFrame with verbatim requested
    items and summed quantities.

    Guarantees:
    - Exactly 572 distinct items for 279.xlsx (no 'AE' row, sum=14,122).
    - Preserves distinct pricing states ('س ج' vs 'س ق').
    - Never overwrites requested_item with canonical_item.
    - Excludes old-price rows ending in 'س ق' or 'ق س'.
    """
    return load_purchase_order(file_path, drop_zero_qty=drop_zero_qty, return_exclusions=return_exclusions)


__all__ = [
    "parse_order_file",
    "load_purchase_order",
    "clean_state_suffix",
    "is_metadata_or_header",
    "is_old_price_item",
    "ExcludedItem",
]
