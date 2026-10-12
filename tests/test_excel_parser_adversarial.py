# -*- coding: utf-8 -*-
"""
Adversarial Stress Test Suite for Milestone M2 Purchase Order Parser (src/excel_parser.py).
Tests integrity, edge cases, boundary conditions, and adversarial inputs.
"""
import os
import re
import pytest
import pandas as pd
import numpy as np
from src.excel_parser import (
    load_purchase_order,
    find_order_header_row,
    is_metadata_or_header,
    clean_state_suffix,
    parse_quantity_value,
    map_table_columns,
)


class TestIntegrityViolations:
    """Verifies that src/excel_parser.py contains no hardcoded test outputs or file checks."""

    def test_no_hardcoded_file_branches(self):
        import io
        import tokenize
        with open(os.path.join("src", "excel_parser.py"), "r", encoding="utf-8") as f:
            source = f.read()

        # Tokenize and extract only executable tokens (strip comments and docstrings)
        tokens = []
        io_obj = io.StringIO(source)
        prev_toktype = tokenize.INDENT
        for tok in tokenize.generate_tokens(io_obj.readline):
            token_type = tok[0]
            token_string = tok[1]
            if token_type == tokenize.COMMENT:
                continue
            if token_type == tokenize.STRING:
                # Top-level or function-level docstring
                if prev_toktype in (tokenize.INDENT, tokenize.NEWLINE, tokenize.NL):
                    continue
            tokens.append(token_string)
            prev_toktype = token_type
        
        executable_code = " ".join(tokens)

        # Check for hardcoded file names
        assert "0911" not in executable_code, "INTEGRITY VIOLATION: Hardcoded '0911' found in executable code"
        assert "0912" not in executable_code, "INTEGRITY VIOLATION: Hardcoded '0912' found in executable code"

        # Check for hardcoded target counts or totals
        assert "202" not in executable_code, "INTEGRITY VIOLATION: Hardcoded '202' found in executable code"
        assert "5553" not in executable_code, "INTEGRITY VIOLATION: Hardcoded '5553' found in executable code"
        assert "743" not in executable_code, "INTEGRITY VIOLATION: Hardcoded '743' found in executable code"
        assert "21676" not in executable_code, "INTEGRITY VIOLATION: Hardcoded '21676' found in executable code"


class TestAdversarialMetadataRejection:
    """Tests that metadata rows are rejected but valid medicines are preserved."""

    def test_legitimate_drugs_starting_with_sad_are_preserved(self):
        """Medicines starting with letter Sad (ص) MUST NOT be rejected as pharmacy names."""
        legitimate_sad_drugs = [
            "صوديوم كلوريد 0.9% 500 مل",
            "صبغة يود 50 مل",
            "صودا بايكربونات 8.4% امبول",
            "صوفالدي 400 مجم 28 قرص",
            "صوفيكس 100 مجم شراب",
            "صنوبر زيت 30 مل",
        ]
        for drug in legitimate_sad_drugs:
            assert not is_metadata_or_header(drug), f"Legitimate drug falsely rejected: {drug}"

    def test_pharmacy_customer_names_are_rejected(self):
        """Customer names and pharmacy prefixes MUST be rejected."""
        customer_names = [
            "صيدلية النور والامل",
            "صيدليه د. مصطفى",
            "ص علي يوسف/ مغنين6",
            "ص / عبد الرحمن طنطا",
            "ص : الوفاء الحديثة",
            "صيدلية د/ هاني الدلنجات",
            "العميل: صيدلية البركة",
            "زبون: صيدلية الإيمان",
        ]
        for name in customer_names:
            assert is_metadata_or_header(name), f"Customer name was NOT rejected: {name}"

    def test_financial_totals_and_dividers_rejected(self):
        """Section dividers and financial totals MUST be rejected."""
        metadata_lines = [
            "إجمالي الفاتورة",
            "اجمالي المطلوب",
            "المجموع الكلي",
            "Total Amount",
            "Grand Total",
            "Subtotal",
            "-------------------",
            "===================",
            "*** قسم أدوية السكر ***",
            "أصناف النواقص العاجلة",
            "مجموعة أدوية الثلاجة",
            "مندوب: أحمد خليل",
            "المندوب / حسام عادل",
            "مشرف المبيعات: ياسر",
            "توقيع المستلم",
            "ملاحظات: توريد عاجل غدا",
            "مخزن المحلة الكبرى",
            "شركة الأهرام للأدوية",
        ]
        for line in metadata_lines:
            assert is_metadata_or_header(line), f"Metadata line was NOT rejected: {line}"

    def test_date_tokens_rejected(self):
        """Dates formatted as strings or timestamp objects MUST be rejected."""
        dates = [
            "2026-09-12",
            "2026/09/12",
            "12-09-2026",
            "12/09/2026",
            "2026-09-12 14:30:00",
            pd.Timestamp("2026-09-12"),
        ]
        for d in dates:
            assert is_metadata_or_header(d), f"Date was NOT rejected: {d}"


class TestAdversarialQuantityParsing:
    """Stress tests quantity parsing with extreme, null, string, and zero values."""

    def test_explicit_zero_preservation(self):
        assert parse_quantity_value(0) == 0
        assert parse_quantity_value("0") == 0
        assert parse_quantity_value(0.0) == 0
        assert parse_quantity_value("0.0") == 0

    def test_nan_and_empty_defaults_to_one(self):
        assert parse_quantity_value(None) == 1
        assert parse_quantity_value(np.nan) == 1
        assert parse_quantity_value("") == 1
        assert parse_quantity_value("   ") == 1
        assert parse_quantity_value("None") == 1
        assert parse_quantity_value("nan") == 1

    def test_string_numeric_and_float_conversion(self):
        assert parse_quantity_value("15") == 15
        assert parse_quantity_value(12.9) == 12
        assert parse_quantity_value("3.5") == 3
        assert parse_quantity_value("abc") == 1  # non-numeric defaults to 1

    def test_negative_quantity_handling_in_loader(self, tmp_path):
        """Negative quantities (credits / returns) should be filtered out after aggregation."""
        fpath = str(tmp_path / "negative_qty.xlsx")
        data = [
            ["أسم الصنف", "الكمية"],
            ["بانادول اكسترا", -5],  # net negative -> discarded
            ["كونكور 5 مجم", 10],
            ["كونكور 5 مجم", -3],    # net = 7 -> kept
        ]
        pd.DataFrame(data).to_excel(fpath, index=False, header=False)
        df = load_purchase_order(fpath)
        assert len(df) == 1
        assert df['requested_item'].iloc[0] == "كونكور 5 مجم"
        assert df['quantity'].iloc[0] == 7


class TestAdversarialWorkbookStructures:
    """Tests extreme and edge-case workbook layouts."""

    def test_deep_header_search(self, tmp_path):
        """Real header located at row 40 after 39 rows of empty space and notes."""
        fpath = str(tmp_path / "deep_header.xlsx")
        rows = [["ملاحظة عامة", f"سطر {i}"] for i in range(39)]
        rows.append(["أسم الصنف", "الكمية"])
        rows.append(["بانادول اكسترا 24 قرص", 10])
        rows.append(["أوجمنتين 1 جم", 5])

        pd.DataFrame(rows).to_excel(fpath, index=False, header=False)
        df = load_purchase_order(fpath)
        assert len(df) == 2
        assert df['quantity'].sum() == 15

    def test_completely_empty_or_corrupt_workbook(self, tmp_path):
        """Workbook with only empty sheets returns empty dataframe without crashing."""
        fpath = str(tmp_path / "empty_wb.xlsx")
        with pd.ExcelWriter(fpath, engine="openpyxl") as writer:
            pd.DataFrame().to_excel(writer, sheet_name="Blank1")
            pd.DataFrame([[None, None]]).to_excel(writer, sheet_name="Blank2")

        df = load_purchase_order(fpath)
        assert df.empty
        assert "requested_item" in df.columns
        assert "quantity" in df.columns

    def test_duplicate_column_headers(self, tmp_path):
        """Verifies sheets where columns share duplicate names are handled safely without unhandled crashes."""
        fpath = str(tmp_path / "duplicate_cols.xlsx")
        data = [
            ["أسم الصنف", "الكمية", "الكمية"],  # Duplicate quantity header
            ["بانادول اكسترا", 10, 20],
        ]
        pd.DataFrame(data).to_excel(fpath, index=False, header=False)
        # Should execute safely without unhandled exception
        df = load_purchase_order(fpath)
        assert isinstance(df, pd.DataFrame)
        assert "requested_item" in df.columns
        assert "quantity" in df.columns


class TestStateSuffixCleaning:
    """Verifies ERP state suffix cleaning."""

    def test_suffix_patterns(self):
        assert clean_state_suffix("كونكور 5 مجم س ج") == "كونكور 5 مجم"
        assert clean_state_suffix("كونكور 5 مجم س.ج") == "كونكور 5 مجم"
        assert clean_state_suffix("بانادول اكسترا جديد") == "بانادول اكسترا"
        assert clean_state_suffix("أوجمنتين 1 جم س ق") == "أوجمنتين 1 جم"
        assert clean_state_suffix("أوجمنتين 1 جم س.ق") == "أوجمنتين 1 جم"
        assert clean_state_suffix("كتافلام 50 مجم قديم") == "كتافلام 50 مجم"
        assert clean_state_suffix("بروفين 400 سعر جديد") == "بروفين 400"
        assert clean_state_suffix("بروفين 400 سعر قديم") == "بروفين 400"
