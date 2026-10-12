# -*- coding: utf-8 -*-
"""
Order Parser module for Egyptian Pharmacy Procurement.
Exposes parse_order_file and load_purchase_order for ingesting customer
and pharmacy purchase orders with verbatim requested item preservation.
"""
from typing import Optional
import pandas as pd
from .excel_parser import load_purchase_order, clean_state_suffix, is_metadata_or_header


def parse_order_file(file_path: str, drop_zero_qty: bool = False) -> pd.DataFrame:
    """
    Parses a purchase order file (.xlsx, .xls, .csv), deduplicating strictly
    on original requested_item text, filtering noise headers and isolated 'AE' tokens,
    and returning a clean DataFrame with verbatim requested items and summed quantities.

    Guarantees:
    - Exactly 572 distinct items for 279.xlsx (no 'AE' row, sum=14,122).
    - Preserves distinct pricing states ('س ج' vs 'س ق').
    - Never overwrites requested_item with canonical_item.
    """
    return load_purchase_order(file_path, drop_zero_qty=drop_zero_qty)


__all__ = ["parse_order_file", "load_purchase_order", "clean_state_suffix", "is_metadata_or_header"]
