# -*- coding: utf-8 -*-
"""
Empirical Challenger Verification Suite for Milestone M2 Purchase Order Extraction.
Author: Challenger M2_2 gen3
Purpose: Independently and empirically verify:
  1. Exact yields on 0911.xlsx (202 items / 5,553 units) and 0912.xlsx (743 items / 21,676 units).
  2. Zero customer name, sales rep, warehouse, date, or total contamination.
  3. Zero quantity inflation (+0.0) compared to raw row sums.
  4. Complete schema compliance (canonical_item, requested_item, quantity, normalized_name, dosage, unit_size).
  5. Correct handling of zero-quantity items and suffix deduplication.
"""
import os
import re
import pytest
import pandas as pd
import numpy as np
from src.excel_parser import load_purchase_order, clean_state_suffix, is_metadata_or_header

TRAIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "train")
FILE_0911 = os.path.join(TRAIN_DIR, "0911.xlsx")
FILE_0912 = os.path.join(TRAIN_DIR, "0912.xlsx")

REQUIRED_COLUMNS = [
    'canonical_item',
    'requested_item',
    'quantity',
    'normalized_name',
    'dosage',
    'unit_size'
]

CONTAMINATION_PATTERNS = [
    (r'^(?:ص\s*[/:\s]|(?:صيدلية|صيدليه)\b)\s*[\u0600-\u06FFa-zA-Z]', "Customer Pharmacy Name"),
    (r'^(?:عميل|العميل|زبون|الزبون|customer|client)\b', "Customer Token"),
    (r'^(?:مندوب|المندوب|مشرف|المشرف|توقيع|المستلم)\b', "Sales Rep / Signature"),
    (r'^(?:مخزن|المخزن|مورد|المورد|شركة|الشركة)\b', "Warehouse / Company"),
    (r'^(?:إجمالي|اجمالي|المجموع|مجموع|total|subtotal|grand\s*total)\b', "Total Line"),
    (r'^[-_=\s*~#]{3,}', "Divider Line"),
    (r'^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?$', "Date String"),
    (r'^\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}$', "Date String"),
    (r'^(?:أسم الصنف|اسم الصنف|إسم الصنف|كود الصنف|الكمية|الكميه|الوحدة|الوحده)$', "Repeated Header Token"),
]


class TestM2EmpiricalYields:
    """Empirical verification of purchase orders 0911.xlsx and 0912.xlsx."""

    def test_0911_exact_yield_and_schema(self):
        assert os.path.exists(FILE_0911), f"File missing: {FILE_0911}"
        df = load_purchase_order(FILE_0911)

        # 1. Exact Item Count
        assert len(df) == 202, f"0911.xlsx: Expected exactly 202 distinct items, got {len(df)}"

        # 2. Exact Quantity Sum
        total_qty = df['quantity'].sum()
        assert total_qty == 5553, f"0911.xlsx: Expected exactly 5,553 units, got {total_qty}"

        # 3. Schema Completeness
        for col in REQUIRED_COLUMNS:
            assert col in df.columns, f"Missing required column '{col}' in 0911.xlsx output"

        # 4. No Nulls in Essential Fields
        assert df['canonical_item'].notna().all(), "Null found in canonical_item for 0911.xlsx"
        assert df['requested_item'].notna().all(), "Null found in requested_item for 0911.xlsx"
        assert df['quantity'].notna().all(), "Null found in quantity for 0911.xlsx"
        assert df['normalized_name'].notna().all(), "Null found in normalized_name for 0911.xlsx"

        # 5. Non-negative Integer Quantities
        assert (df['quantity'] >= 0).all(), "Negative quantity found in 0911.xlsx"
        assert np.issubdtype(df['quantity'].dtype, np.integer), "Quantity column is not integer type"

    def test_0912_exact_yield_and_schema(self):
        assert os.path.exists(FILE_0912), f"File missing: {FILE_0912}"
        df = load_purchase_order(FILE_0912)

        # 1. Exact Item Count
        assert len(df) == 743, f"0912.xlsx: Expected exactly 743 distinct items, got {len(df)}"

        # 2. Exact Quantity Sum
        total_qty = df['quantity'].sum()
        assert total_qty == 21676, f"0912.xlsx: Expected exactly 21,676 units, got {total_qty}"

        # 3. Schema Completeness
        for col in REQUIRED_COLUMNS:
            assert col in df.columns, f"Missing required column '{col}' in 0912.xlsx output"

        # 4. No Nulls in Essential Fields
        assert df['canonical_item'].notna().all(), "Null found in canonical_item for 0912.xlsx"
        assert df['requested_item'].notna().all(), "Null found in requested_item for 0912.xlsx"
        assert df['quantity'].notna().all(), "Null found in quantity for 0912.xlsx"
        assert df['normalized_name'].notna().all(), "Null found in normalized_name for 0912.xlsx"

        # 5. Non-negative Integer Quantities
        assert (df['quantity'] >= 0).all(), "Negative quantity found in 0912.xlsx"
        assert np.issubdtype(df['quantity'].dtype, np.integer), "Quantity column is not integer type"


class TestZeroContamination:
    """Comprehensive contamination check across all extracted items."""

    def test_0911_zero_contamination(self):
        df = load_purchase_order(FILE_0911)
        contaminated = []
        for idx, row in df.iterrows():
            item_name = str(row['requested_item']).strip()
            canonical = str(row['canonical_item']).strip()
            for pattern, desc in CONTAMINATION_PATTERNS:
                if re.search(pattern, item_name, re.IGNORECASE) or re.search(pattern, canonical, re.IGNORECASE):
                    contaminated.append((item_name, desc))
        assert len(contaminated) == 0, f"Contaminated items found in 0911.xlsx: {contaminated}"

    def test_0912_zero_contamination(self):
        df = load_purchase_order(FILE_0912)
        contaminated = []
        for idx, row in df.iterrows():
            item_name = str(row['requested_item']).strip()
            canonical = str(row['canonical_item']).strip()
            for pattern, desc in CONTAMINATION_PATTERNS:
                if re.search(pattern, item_name, re.IGNORECASE) or re.search(pattern, canonical, re.IGNORECASE):
                    contaminated.append((item_name, desc))
        assert len(contaminated) == 0, f"Contaminated items found in 0912.xlsx: {contaminated}"


class TestZeroQuantityInflation:
    """Verify zero quantity inflation against raw Excel files directly."""

    def test_0911_raw_sum_comparison(self):
        """Read raw sheets directly, sum raw quantities, and verify inflation is exactly 0.0."""
        # Directly read raw sheets from 0911.xlsx
        raw_items = []
        with pd.ExcelFile(FILE_0911) as ef:
            for sname in ef.sheet_names:
                sheet_df = pd.read_excel(ef, sheet_name=sname, header=None)
                # Find header row
                for r in range(min(50, len(sheet_df))):
                    row_vals = [str(x).strip() for x in sheet_df.iloc[r].values if pd.notna(x)]
                    if any('اسم' in x or 'صنف' in x for x in row_vals) and any('الكمية' in x or 'كمية' in x for x in row_vals):
                        # Identified header
                        name_col = None
                        qty_col = None
                        for c_idx, val in enumerate(sheet_df.iloc[r].values):
                            s = str(val).strip()
                            if ('اسم' in s or 'صنف' in s) and name_col is None:
                                name_col = c_idx
                            if ('الكمية' in s or 'كمية' in s or 'عدد' in s) and qty_col is None:
                                qty_col = c_idx

                        if name_col is not None and qty_col is not None:
                            for data_r in range(r + 1, len(sheet_df)):
                                n_val = sheet_df.iloc[data_r, name_col]
                                q_val = sheet_df.iloc[data_r, qty_col]
                                if pd.notna(n_val) and str(n_val).strip() != '':
                                    if not is_metadata_or_header(n_val, sheet_df.iloc[data_r].values):
                                        try:
                                            q_num = float(q_val) if pd.notna(q_val) else 1.0
                                        except (ValueError, TypeError):
                                            q_num = 1.0
                                        raw_items.append((str(n_val).strip(), q_num))
                        break

        raw_sum = sum(q for _, q in raw_items)
        assert raw_sum == 5553.0, f"Raw data sum expected 5553.0, got {raw_sum}"

        df = load_purchase_order(FILE_0911)
        parsed_sum = df['quantity'].sum()
        inflation = parsed_sum - raw_sum
        assert inflation == 0.0, f"Quantity inflation detected in 0911.xlsx: +{inflation}"

    def test_0912_raw_sum_comparison(self):
        """Read raw sheets directly, sum raw quantities, and verify inflation is exactly 0.0."""
        raw_items = []
        with pd.ExcelFile(FILE_0912) as ef:
            for sname in ef.sheet_names:
                sheet_df = pd.read_excel(ef, sheet_name=sname, header=None)
                # Find header row
                for r in range(min(50, len(sheet_df))):
                    row_vals = [str(x).strip() for x in sheet_df.iloc[r].values if pd.notna(x)]
                    if any('اسم' in x or 'صنف' in x for x in row_vals) and any('الكمية' in x or 'كمية' in x for x in row_vals):
                        name_col = None
                        qty_col = None
                        for c_idx, val in enumerate(sheet_df.iloc[r].values):
                            s = str(val).strip()
                            if ('اسم' in s or 'صنف' in s) and name_col is None:
                                name_col = c_idx
                            if ('الكمية' in s or 'كمية' in s or 'عدد' in s) and qty_col is None:
                                qty_col = c_idx

                        if name_col is not None and qty_col is not None:
                            for data_r in range(r + 1, len(sheet_df)):
                                n_val = sheet_df.iloc[data_r, name_col]
                                q_val = sheet_df.iloc[data_r, qty_col]
                                if pd.notna(n_val) and str(n_val).strip() != '':
                                    if not is_metadata_or_header(n_val, sheet_df.iloc[data_r].values):
                                        try:
                                            q_num = float(q_val) if pd.notna(q_val) else 1.0
                                        except (ValueError, TypeError):
                                            q_num = 1.0
                                        raw_items.append((str(n_val).strip(), q_num))
                        break

        raw_sum = sum(q for _, q in raw_items)
        assert raw_sum == 21676.0, f"Raw data sum expected 21676.0, got {raw_sum}"

        df = load_purchase_order(FILE_0912)
        parsed_sum = df['quantity'].sum()
        inflation = parsed_sum - raw_sum
        assert inflation == 0.0, f"Quantity inflation detected in 0912.xlsx: +{inflation}"


class TestZeroQuantityAndSuffixDeduplication:
    """Verify specific edge cases: explicit 0 quantities and state suffix merges."""

    def test_0911_zero_quantity_item_dorfen(self):
        """In 0911, 'دورفين 30كبسولة' has explicit qty=0 in raw row 256."""
        df = load_purchase_order(FILE_0911, drop_zero_qty=False)
        dorfen = df[df['canonical_item'].str.contains("دورفين", na=False)]
        assert not dorfen.empty, "'دورفين' should be present in 0911.xlsx"
        assert dorfen['quantity'].iloc[0] == 0, f"Expected Dorfen qty=0, got {dorfen['quantity'].iloc[0]}"

        # With drop_zero_qty=True, it should be dropped leaving exactly 201 items
        df_dropped = load_purchase_order(FILE_0911, drop_zero_qty=True)
        assert len(df_dropped) == 201
        assert df_dropped['quantity'].sum() == 5553

    def test_0912_zero_quantity_items_fi_and_cream(self):
        """In 0912, 'في اند كريم' ordered across rows with quantities 0, 0, 3 -> sum must be 3."""
        df = load_purchase_order(FILE_0912)
        fi_cream = df[df['canonical_item'].str.contains("في اند كريم", na=False)]
        assert not fi_cream.empty, "'في اند كريم' should be present in 0912.xlsx"
        assert fi_cream['quantity'].iloc[0] == 3, f"Expected 'في اند كريم' qty=3, got {fi_cream['quantity'].iloc[0]}"

    def test_0911_suffix_merges(self):
        """In 0911, 'ديبافالي بلاس50\\1000مجم اقراص س ج' in rows 166, 167, 253 merges to 'ديبافالي بلاس50\\1000مجم اقراص' with qty=66."""
        df = load_purchase_order(FILE_0911)
        dapa = df[df['canonical_item'].str.contains("ديبافالي", na=False)]
        assert len(dapa) == 1, "Should be merged into 1 canonical item"
        assert not dapa['canonical_item'].iloc[0].endswith("س ج"), "State suffix 'س ج' should be stripped"
        assert dapa['quantity'].iloc[0] == 66, f"Expected merged quantity 66, got {dapa['quantity'].iloc[0]}"
