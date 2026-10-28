# -*- coding: utf-8 -*-
"""
Adversarial Stress Test Suite for Milestone 1: Table Geometry Normalization & Group Recognition
Author: Challenger 1 (Milestone 1)
Role: critic, specialist (egyptian-pharma-procurement)

Adversarial Dimensions Tested:
1. Synthetic tables with varying columns:
   - 7 columns: single wide product group, 7 columns with 1 header-only slot
   - 10 columns: 3 groups + 1 trailing empty column, 10 columns with 1 leading empty column
   - 11 columns: Hayah Shibin geometry, 11 columns with 2 contiguous header-only slots
   - 13 columns: 4 groups of 3 + 1 empty slot, 3 groups of 4 + 1 empty slot
2. Multiple header-only columns:
   - 2 contiguous header-only slots between groups
   - 3 contiguous header-only slots
   - Mixed header fragments with empty adjacent spacers
3. Missing discount or price cells in random rows:
   - Verification of strict column immutability (zero column shifting)
   - Missing price cell rejects with invalid_price_0.0 without shifting discount or name
   - Missing discount cell rejects with invalid_discount_0.0 without shifting price or name
   - Explicit zero discount ('صافي', 'نقدى', '0%') cleanly accepted as 0.0%
   - Interleaved valid/invalid cells across 3 parallel groups
4. Single items and partial final pages:
   - Partial final page with established layout: only 1 item in Group 0, empty Groups 1 & 2
   - Partial final page: empty slots excluded from candidate_rows, zero rejected rows
   - Single-page catalog with exactly 1 item
5. Production catalog extraction parity and schema conformance:
   - Dawlia (529 items)
   - Zahra (1,167 items)
   - Forsan, Hadhaba, Salam parity
6. Confirmed Defects & Failure Mode Demonstrations:
   - Defect 1: Divisibility constraint (n % cycle_len == 0) collapses non-divisible multi-group tables (7, 10, 13 cols)
   - Defect 2: Serial header 'م' / integers <= 85 misclassified as 'discount', corrupting item discount rates
"""

import os
import sys
import unittest
from typing import Any, List, Optional, Tuple

import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.catalog_reader import (
    TableGeometry,
    ProductGroup,
    analyze_table_geometry,
    detect_product_groups,
    classify_column_role,
    parse_structural_table,
    extract_item_from_group_row,
    extract_raw_float_value,
    is_explicit_zero_discount,
)
from src.pdf_parser import PDFCatalogParser
from src.normalizer import unreverse_arabic_text, normalize_arabic_text


class MockRow:
    """Mock PyMuPDF table row with cell bounding boxes."""
    def __init__(self, cells: List[Optional[Tuple[float, float, float, float]]]):
        self.cells = cells


class MockTable:
    """Mock PyMuPDF table object supporting .extract(), .rows, .col_count, and .bbox."""
    def __init__(self, data: List[List[Any]], cell_bboxes: Optional[List[List[Optional[Tuple[float, float, float, float]]]]] = None):
        self._data = data
        self.col_count = len(data[0]) if data else 0
        if cell_bboxes:
            self.rows = [MockRow(row_cells) for row_cells in cell_bboxes]
        else:
            self.rows = []
            for r_idx, row in enumerate(data):
                row_cells = []
                for c_idx, val in enumerate(row):
                    if val is not None and str(val).strip() != "":
                        row_cells.append((float(c_idx * 50), float(r_idx * 20), float((c_idx + 1) * 50), float((r_idx + 1) * 20)))
                    else:
                        row_cells.append(None)
                self.rows.append(MockRow(row_cells))
        self.bbox = (0.0, 0.0, float(self.col_count * 50), float(len(data) * 20))

    def extract(self) -> List[List[Any]]:
        return self._data


# ============================================================================
# 1. SYNTHETIC TABLES WITH VARYING COLUMNS (7, 10, 11, 13 COLUMNS)
# ============================================================================
class TestVaryingColumnGeometries(unittest.TestCase):
    """Stress tests for varying table column counts."""

    def test_7_columns_single_wide_group_with_explicit_headers(self):
        """Verify 7-column table with 1 wide product group (Code, Barcode, Name, Price, Disc, Stock, Note)."""
        headers = ["كود", "باركود", "اسم الصنف", "سعر الجمهور", "الخصم", "رصيد", "ملاحظات"]
        data = [
            headers,
            ["101", "622123", "كونكور 5 مجم 30 قرص", "40.50", "20%", "متوفر", "جديد"],
            ["102", "622456", "بنادول اكسترا 24 قرص", "55.00", "15%", "متوفر", ""],
        ]
        table = MockTable(data)
        geom = analyze_table_geometry(table)
        self.assertIsNotNone(geom)
        self.assertEqual(len(geom.retained_cols), 7)

        groups = detect_product_groups(geom, data)
        self.assertEqual(len(groups), 1)
        g = groups[0]
        self.assertTrue(g.is_valid)
        self.assertEqual(g.name_col, 2)
        self.assertEqual(g.price_col, 3)
        self.assertEqual(g.discount_col, 4)

        items, _, _, diag = parse_structural_table(table, page_idx=0, warehouse_name="مخزن تجريبي")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["base_price"], 40.50)
        self.assertAlmostEqual(items[0]["discount_rate"], 0.20)
        self.assertIn("كونكور", items[0]["item_name"])

    def test_7_columns_with_header_only_slot_forming_two_groups(self):
        """Verify 7-column table where 1 column has 0 body cells, pruning to 6 columns (2 groups of 3)."""
        headers = ["سعر", "خصم", "اسم الصنف", "فاصل", "سعر", "خصم", "اسم الصنف"]
        data = [
            headers,
            ["50.0", "20%", "اموكسيل 500 كبسول", "", "120.0", "25%", "اوجمانتين 1 جم 14 قرص"],
            ["75.0", "18%", "فلاجيل 500 قرص", "", "35.0", "10%", "انتينال كبسول"],
        ]
        table = MockTable(data)
        geom = analyze_table_geometry(table)
        self.assertIsNotNone(geom)
        # Col 3 has 0 body cells -> pruned
        self.assertIn(3, geom.header_only_cols)
        self.assertEqual(geom.retained_cols, [0, 1, 2, 4, 5, 6])

        groups = detect_product_groups(geom, data)
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0].raw_cols, [0, 1, 2])
        self.assertEqual(groups[1].raw_cols, [4, 5, 6])

        items, _, _, diag = parse_structural_table(table, page_idx=0, warehouse_name="مخزن تجريبي")
        self.assertEqual(len(items), 4)
        names = [it["item_name"] for it in items]
        self.assertTrue(any("اموكسيل" in n for n in names))
        self.assertTrue(any("اوجمانتين" in n for n in names))

    def test_10_columns_with_trailing_header_only_slot(self):
        """Verify 10-column table (3 groups of 3 + 1 trailing header-only column)."""
        headers = ["سعر", "خصم", "اسم الصنف", "سعر", "خصم", "اسم الصنف", "سعر", "خصم", "اسم الصنف", "ملاحظة"]
        data = [
            headers,
            ["30.0", "15%", "بنادول ادفانس", "45.0", "20%", "كاتافلام 50", "60.0", "25%", "فولتارين 100", ""],
            ["25.0", "10%", "بروفين 400", "80.0", "30%", "سيبتازول قرص", "95.0", "22%", "كلافيموكس 1 جم", None],
        ]
        table = MockTable(data)
        geom = analyze_table_geometry(table)
        self.assertIsNotNone(geom)
        self.assertIn(9, geom.header_only_cols)
        self.assertEqual(geom.retained_cols, [0, 1, 2, 3, 4, 5, 6, 7, 8])

        groups = detect_product_groups(geom, data)
        self.assertEqual(len(groups), 3)

        items, _, _, diag = parse_structural_table(table, page_idx=0, warehouse_name="مخزن تجريبي")
        self.assertEqual(len(items), 6)
        self.assertEqual(diag.accepted_rows, 6)

    def test_11_columns_hayah_shibin_geometry(self):
        """Verify 11-column table with split header merge (col 8->7) and pruned empty slot (col 10)."""
        headers = ["سعر", "خصم", "صنف", "سعر", "خصم", "صنف", "سعر", "مص", "خلا", "صنف", ""]
        data = [
            headers,
            ["70.0", "36%", "ابياموكس 400 مجم شراب", "33.0", "36%", "الزنتال 6 قرص", "50.0", "41%", "", "اوميباك 20 مجم 14 كبسولة", ""],
            ["192.0", "32%", "جليبتس 50/1000 مجم", "66.0", "28%", "يورينكس كبسول", "44.0", "20%", "", "كتافلاي معلق", ""],
        ]
        table = MockTable(data)
        geom = analyze_table_geometry(table)
        self.assertIsNotNone(geom)
        self.assertIn(8, geom.header_only_cols)
        self.assertIn(10, geom.header_only_cols)
        self.assertEqual(geom.merge_into.get(8), 7)
        self.assertEqual(geom.retained_cols, [0, 1, 2, 3, 4, 5, 6, 7, 9])

        groups = detect_product_groups(geom, data)
        self.assertEqual(len(groups), 3)
        self.assertEqual(groups[2].raw_cols, [6, 7, 9])

        items, _, _, diag = parse_structural_table(table, page_idx=0, warehouse_name="مخزن تجريبي")
        self.assertEqual(len(items), 6)

    def test_13_columns_four_groups_plus_header_only_slot(self):
        """Verify 13-column table (4 groups of 3 + 1 empty header-only column = 13 columns)."""
        headers = [
            "سعر", "خصم", "اسم الصنف",
            "سعر", "خصم", "اسم الصنف",
            "سعر", "خصم", "اسم الصنف",
            "سعر", "خصم", "اسم الصنف",
            "فارغ"
        ]
        data = [
            headers,
            ["10.0", "10%", "دواء 1", "20.0", "20%", "دواء 2", "30.0", "30%", "دواء 3", "40.0", "40%", "دواء 4", ""],
            ["15.0", "12%", "دواء 5", "25.0", "22%", "دواء 6", "35.0", "32%", "دواء 7", "45.0", "42%", "دواء 8", None],
        ]
        table = MockTable(data)
        geom = analyze_table_geometry(table)
        self.assertIsNotNone(geom)
        self.assertIn(12, geom.header_only_cols)
        self.assertEqual(len(geom.retained_cols), 12)

        groups = detect_product_groups(geom, data)
        self.assertEqual(len(groups), 4)

        items, _, _, diag = parse_structural_table(table, page_idx=0, warehouse_name="مخزن تجريبي")
        self.assertEqual(len(items), 8)
        self.assertEqual(diag.accepted_rows, 8)

    def test_13_columns_three_groups_of_four_plus_spacer(self):
        """Verify 13-column table: 3 groups of 4 (Code, Name, Price, Discount) + 1 spacer slot."""
        headers = [
            "كود", "اسم الصنف", "سعر الجمهور", "الخصم",
            "كود", "اسم الصنف", "سعر الجمهور", "الخصم",
            "كود", "اسم الصنف", "سعر الجمهور", "الخصم",
            ""
        ]
        data = [
            headers,
            ["101", "كونكور 5", "40.0", "20%", "102", "بنادول", "50.0", "15%", "103", "فلاجيل", "30.0", "25%", ""],
            ["104", "اموكسيل", "60.0", "18%", "105", "بروفين", "45.0", "22%", "106", "كاتافلام", "55.0", "30%", ""],
        ]
        table = MockTable(data)
        geom = analyze_table_geometry(table)
        self.assertIsNotNone(geom)
        self.assertIn(12, geom.header_only_cols)
        self.assertEqual(len(geom.retained_cols), 12)

        groups = detect_product_groups(geom, data)
        self.assertEqual(len(groups), 3)
        for g in groups:
            self.assertEqual(len(g.raw_cols), 4)
            self.assertTrue(g.is_valid)

        items, _, _, diag = parse_structural_table(table, page_idx=0, warehouse_name="مخزن تجريبي")
        self.assertEqual(len(items), 6)


# ============================================================================
# 2. MULTIPLE HEADER-ONLY COLUMNS (CONTIGUOUS SLOTS)
# ============================================================================
class TestMultipleHeaderOnlyColumns(unittest.TestCase):
    """Stress tests for tables with multiple and contiguous header-only structural slots."""

    def test_two_contiguous_empty_slots_between_groups(self):
        """Verify 2 contiguous empty columns between Group 0 and Group 1 are both cleanly pruned."""
        headers = ["سعر", "خصم", "صنف", "", "", "سعر", "خصم", "صنف"]
        data = [
            headers,
            ["40.0", "20%", "بنادول 500", "", "", "80.0", "25%", "اوجمانتين 1جم"],
            ["25.0", "15%", "فلاجيل 500", "", None, "35.0", "18%", "انتينال كبسول"],
        ]
        table = MockTable(data)
        geom = analyze_table_geometry(table)
        self.assertIsNotNone(geom)
        # Cols 3 and 4 have 0 body cells
        self.assertIn(3, geom.header_only_cols)
        self.assertIn(4, geom.header_only_cols)
        self.assertEqual(geom.retained_cols, [0, 1, 2, 5, 6, 7])

        groups = detect_product_groups(geom, data)
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0].raw_cols, [0, 1, 2])
        self.assertEqual(groups[1].raw_cols, [5, 6, 7])

        items, _, _, diag = parse_structural_table(table, page_idx=0, warehouse_name="مخزن تجريبي")
        self.assertEqual(len(items), 4)

    def test_three_contiguous_empty_slots_pruning(self):
        """Verify 3 contiguous empty columns are properly identified and pruned."""
        headers = ["سعر", "خصم", "صنف", "فاصل1", "فاصل2", "فاصل3", "سعر", "خصم", "صنف"]
        data = [
            headers,
            ["50.0", "20%", "دواء أ", "", "", "", "100.0", "30%", "دواء ب"],
            ["60.0", "22%", "دواء ج", None, "", None, "110.0", "32%", "دواء د"],
        ]
        table = MockTable(data)
        geom = analyze_table_geometry(table)
        self.assertIsNotNone(geom)
        self.assertTrue({3, 4, 5}.issubset(geom.header_only_cols))
        self.assertEqual(geom.retained_cols, [0, 1, 2, 6, 7, 8])

        groups = detect_product_groups(geom, data)
        self.assertEqual(len(groups), 2)
        items, _, _, diag = parse_structural_table(table, page_idx=0, warehouse_name="مخزن تجريبي")
        self.assertEqual(len(items), 4)

    def test_leading_and_trailing_header_only_slots(self):
        """Verify empty slots at column 0 and column N-1 are pruned without shifting middle columns."""
        headers = ["فارغ_بداية", "سعر", "خصم", "صنف", "فارغ_نهاية"]
        data = [
            headers,
            ["", "45.0", "20%", "كونكور 5 مجم", ""],
            [None, "70.0", "25%", "فولتارين 100", None],
        ]
        table = MockTable(data)
        geom = analyze_table_geometry(table)
        self.assertIsNotNone(geom)
        self.assertIn(0, geom.header_only_cols)
        self.assertIn(4, geom.header_only_cols)
        self.assertEqual(geom.retained_cols, [1, 2, 3])

        groups = detect_product_groups(geom, data)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].price_col, 1)
        self.assertEqual(groups[0].discount_col, 2)
        self.assertEqual(groups[0].name_col, 3)

        items, _, _, diag = parse_structural_table(table, page_idx=0, warehouse_name="مخزن تجريبي")
        self.assertEqual(len(items), 2)


# ============================================================================
# 3. MISSING DISCOUNT OR PRICE CELLS (PREVENTING COLUMN SHIFTING)
# ============================================================================
class TestMissingCellsNoColumnShifting(unittest.TestCase):
    """Stress tests verifying that missing prices/discounts reject cleanly without shifting adjacent cells."""

    def test_missing_price_does_not_shift_discount_into_price(self):
        """Verify row with empty price cell rejects as invalid_price_0.0 and does not shift discount into price."""
        group = ProductGroup(group_index=0, raw_cols=[0, 1, 2], price_col=0, discount_col=1, name_col=2)
        # Price is empty, discount is "25%", name is "بنادول"
        row = ["", "25%", "بنادول اكسترا 24 قرص"]
        item, reason, _ = extract_item_from_group_row(row, group, "forward", "مخزن تجريبي")
        self.assertIsNone(item)
        self.assertEqual(reason, "invalid_price_0.0")

    def test_missing_discount_does_not_shift_price_or_name(self):
        """Verify row with empty discount cell rejects as invalid_discount_0.0 without shifting price or name."""
        group = ProductGroup(group_index=0, raw_cols=[0, 1, 2], price_col=0, discount_col=1, name_col=2)
        # Price is "50.0", discount is empty, name is "كونكور"
        row = ["50.0", "", "كونكور 5 مجم 30 قرص"]
        item, reason, _ = extract_item_from_group_row(row, group, "forward", "مخزن تجريبي")
        self.assertIsNone(item)
        self.assertEqual(reason, "invalid_discount_0.0")

    def test_explicit_zero_discount_terms_accepted_as_zero(self):
        """Verify explicit zero discount terms ('صافي', 'صافى', 'نقدى', '0%') are accepted without rejection."""
        group = ProductGroup(group_index=0, raw_cols=[0, 1, 2], price_col=0, discount_col=1, name_col=2)
        for term in ["صافي", "صافى", "نقدى", "0%", "0.0%"]:
            row = ["100.0", term, "انسولين لانتوس قلم"]
            item, reason, _ = extract_item_from_group_row(row, group, "forward", "مخزن تجريبي")
            self.assertIsNotNone(item, f"Failed for zero-discount term: '{term}'")
            self.assertEqual(reason, "accepted")
            self.assertEqual(item["base_price"], 100.0)
            self.assertEqual(item["discount_rate"], 0.0)

    def test_interleaved_missing_cells_across_multiple_groups(self):
        """Verify parallel groups with missing cells in different rows do not cross-contaminate."""
        headers = ["سعر", "خصم", "صنف", "سعر", "خصم", "صنف", "سعر", "خصم", "صنف"]
        data = [
            headers,
            # Row 1: G0 has missing price, G1 has missing discount, G2 is valid
            ["", "20%", "دواء 1", "50.0", "", "دواء 2", "80.0", "30%", "دواء 3"],
            # Row 2: G0 is valid, G1 has explicit zero, G2 has missing price
            ["40.0", "15%", "دواء 4", "60.0", "صافي", "دواء 5", None, "25%", "دواء 6"],
            # Row 3: All 3 groups valid
            ["35.0", "10%", "دواء 7", "75.0", "22%", "دواء 8", "95.0", "18%", "دواء 9"],
        ]
        table = MockTable(data)
        items, _, _, diag = parse_structural_table(table, page_idx=0, warehouse_name="مخزن تجريبي")

        # Row 1: G2 accepted (1)
        # Row 2: G0 accepted, G1 accepted (2)
        # Row 3: G0, G1, G2 accepted (3)
        # Total accepted = 6
        self.assertEqual(len(items), 6)
        self.assertEqual(diag.accepted_rows, 6)
        # G0 rejected row 1 (missing price), G1 rejected row 1 (missing discount), G2 rejected row 2 (missing price)
        # Total rejected = 3
        total_rejected = sum(g.rejected_rows for g in diag.groups)
        self.assertEqual(total_rejected, 3)

        # Check candidate_rows invariant: candidate = accepted + rejected
        total_candidates = sum(g.candidate_rows for g in diag.groups)
        self.assertEqual(total_candidates, 9)
        self.assertEqual(total_candidates, diag.accepted_rows + total_rejected)


# ============================================================================
# 4. SINGLE ITEMS AND PARTIAL FINAL PAGES
# ============================================================================
class TestSingleItemsAndPartialPages(unittest.TestCase):
    """Stress tests for single item pages and partial final pages with established layouts."""

    def test_partial_final_page_with_established_layout(self):
        """Verify partial final page uses established layout; empty groups do NOT count as rejected rows."""
        headers = ["سعر", "خصم", "صنف", "سعر", "خصم", "صنف", "سعر", "خصم", "صنف"]

        # Page 1: Full table with 3 groups
        page1_data = [
            headers,
            ["50.0", "20%", "دواء أ1", "60.0", "25%", "دواء ب1", "70.0", "30%", "دواء ج1"],
            ["55.0", "22%", "دواء أ2", "65.0", "27%", "دواء ب2", "75.0", "32%", "دواء ج2"],
        ]
        p1_table = MockTable(page1_data)
        p1_items, est_geom, est_groups, p1_diag = parse_structural_table(p1_table, page_idx=0, warehouse_name="مخزن تجريبي")
        self.assertEqual(len(p1_items), 6)
        self.assertEqual(len(est_groups), 3)

        # Page 2: Partial final page with only 1 item in Group 0; Groups 1 & 2 are empty cells
        page2_data = [
            headers,
            ["80.0", "35%", "دواء اخير فريد", "", "", "", None, None, None],
            ["", "", "", "", "", "", "", "", ""],  # Completely blank row
        ]
        p2_table = MockTable(page2_data)
        p2_items, _, _, p2_diag = parse_structural_table(
            p2_table, page_idx=1, warehouse_name="مخزن تجريبي",
            established_layout=est_geom, established_groups=est_groups
        )

        # Exactly 1 item recovered
        self.assertEqual(len(p2_items), 1)
        self.assertEqual(p2_items[0]["base_price"], 80.0)
        self.assertIn("اخير", p2_items[0]["item_name"])
        self.assertEqual(p2_diag.accepted_rows, 1)

        # Genuinely empty slots must NOT be counted as rejected rows
        total_p2_rejected = sum(g.rejected_rows for g in p2_diag.groups)
        self.assertEqual(total_p2_rejected, 0)

        # Candidate rows must equal accepted rows (1 candidate = 1 accepted + 0 rejected)
        total_p2_candidates = sum(g.candidate_rows for g in p2_diag.groups)
        self.assertEqual(total_p2_candidates, 1)

    def test_single_item_catalog_without_prior_layout(self):
        """Verify catalog with only 1 page containing only 1 data row extracts cleanly."""
        headers = ["سعر", "خصم", "صنف"]
        data = [
            headers,
            ["125.0", "20%", "حقن فولتارين 75 مجم 6 امبول"],
        ]
        table = MockTable(data)
        items, geom, groups, diag = parse_structural_table(table, page_idx=0, warehouse_name="مخزن تجريبي")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["base_price"], 125.0)
        self.assertEqual(items[0]["discount_rate"], 0.20)
        self.assertIn("فولتارين", items[0]["item_name"])
        self.assertEqual(diag.accepted_rows, 1)
        self.assertEqual(sum(g.rejected_rows for g in diag.groups), 0)


# ============================================================================
# 5. PRODUCTION PDF CATALOGS EXTRACTION PARITY
# ============================================================================
class TestProductionCatalogParity(unittest.TestCase):
    """Verify production catalogs extract with exact parity and no regressions."""

    def test_dawlia_catalog_exact_529_items(self):
        """`شركة مخزن الدولية الحديثة للادوية.pdf` must extract exactly 529 items."""
        cat_path = os.path.join(PROJECT_ROOT, "input", "catalogs", "شركة مخزن الدولية الحديثة للادوية.pdf")
        self.assertTrue(os.path.exists(cat_path), f"Missing: {cat_path}")
        parser = PDFCatalogParser(cat_path)
        df = parser.parse()
        self.assertEqual(len(df), 529, f"Expected 529 items from Dawlia, got {len(df)}")
        # Check required columns
        expected_cols = ["warehouse_name", "item_name", "normalized_name", "dosage", "unit_size", "base_price", "discount_rate", "stock_status"]
        for col in expected_cols:
            self.assertIn(col, df.columns)

    def test_zahra_catalog_exact_1167_items(self):
        """`تحديث زهره.pdf` must extract exactly 1,167 items."""
        cat_path = os.path.join(PROJECT_ROOT, "input", "catalogs", "تحديث زهره.pdf")
        self.assertTrue(os.path.exists(cat_path), f"Missing: {cat_path}")
        parser = PDFCatalogParser(cat_path)
        df = parser.parse()
        self.assertEqual(len(df), 1167, f"Expected 1167 items from Zahra, got {len(df)}")

    def test_fursan_catalog_non_zero_items(self):
        """`الفرسان بنها نقدى.pdf` must extract > 300 valid items."""
        cat_path = os.path.join(PROJECT_ROOT, "input", "catalogs", "الفرسان بنها نقدى.pdf")
        self.assertTrue(os.path.exists(cat_path), f"Missing: {cat_path}")
        parser = PDFCatalogParser(cat_path)
        df = parser.parse()
        self.assertGreater(len(df), 300, f"Expected >300 items from Fursan, got {len(df)}")

    def test_hadhaba_catalog_non_zero_items(self):
        """`الهضبه الخميس نفدى.pdf` must extract > 300 valid items."""
        cat_path = os.path.join(PROJECT_ROOT, "input", "catalogs", "الهضبه الخميس نفدى.pdf")
        self.assertTrue(os.path.exists(cat_path), f"Missing: {cat_path}")
        parser = PDFCatalogParser(cat_path)
        df = parser.parse()
        self.assertGreater(len(df), 300, f"Expected >300 items from Hadhaba, got {len(df)}")

    def test_salam_catalog_non_zero_items(self):
        """`السلام شبين نقدي.pdf` must extract > 100 valid items."""
        cat_path = os.path.join(PROJECT_ROOT, "input", "catalogs", "السلام شبين نقدي.pdf")
        self.assertTrue(os.path.exists(cat_path), f"Missing: {cat_path}")
        parser = PDFCatalogParser(cat_path)
        df = parser.parse()
        self.assertGreater(len(df), 100, f"Expected >100 items from Salam, got {len(df)}")

    def test_hayah_shibin_exact_571_items(self):
        """`tests/fixtures/hayah_shibin.pdf` must extract exactly 571 items with complete diagnostics."""
        fixture_path = os.path.join(PROJECT_ROOT, "tests", "fixtures", "hayah_shibin.pdf")
        self.assertTrue(os.path.exists(fixture_path), f"Missing fixture: {fixture_path}")
        parser = PDFCatalogParser(fixture_path)
        df = parser.parse()
        self.assertEqual(len(df), 571, f"Expected 571 items from Hayah Shibin, got {len(df)}")
        diag = getattr(df, "diagnostics", None)
        self.assertIsNotNone(diag)
        self.assertEqual(diag.status, "complete")
        self.assertEqual(diag.candidate_rows, 571)
        self.assertEqual(diag.accepted_rows, 571)
        self.assertEqual(diag.rejected_rows, 0)
        self.assertEqual(diag.unprocessed_rows, 0)


# ============================================================================
# 6. CONFIRMED ADVERSARIAL DEFECTS & VULNERABILITIES
# ============================================================================
class TestAdversarialVulnerabilities(unittest.TestCase):
    """
    Direct empirical proofs of defects in Milestone 1 implementation.
    These tests demonstrate specific vulnerabilities found during challenge.
    """

    def test_defect_1_serial_header_misclassified_as_discount(self):
        """
        VERIFIES REMEDIATION 1:
        Universal Arabic serial abbreviation 'م' (without a dot) is classified as 'code'.
        """
        role = classify_column_role("م", ["1", "2", "3"])
        self.assertEqual(
            role,
            "code",
            "Remediation confirmed: Serial number column 'م' is correctly classified as 'code'."
        )

    def test_defect_2_serial_column_steals_discount_role_corrupting_prices(self):
        """
        VERIFIES REMEDIATION 2:
        When a table has a serial column ('م') and a discount column ('الخصم'),
        detect_product_groups correctly assigns discount_col to column 3 and code_col to column 0.
        All valid items are extracted with genuine discount rates without false rejections.
        """
        data = [
            ["م", "اسم الصنف", "سعر الجمهور", "الخصم"],
            ["1", "كونكور 5 مجم", "40.0", "20%"],
            ["2", "بنادول 500", "50.0", "15%"],
        ]
        table = MockTable(data)
        items, geom, groups, diag = parse_structural_table(table, 0, "مخزن تجريبي")
        g = groups[0]
        self.assertEqual(g.discount_col, 3)
        self.assertEqual(g.code_col, 0)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["discount_rate"], 0.20)

    def test_defect_3_non_divisible_column_counts_collapse_multi_groups(self):
        """
        VERIFIES REMEDIATION 3:
        detect_product_groups supports arbitrary offsets and non-divisible column counts.
        When a table has 7, 10, or 13 columns (e.g. Serial + 3 groups of 3 = 10 columns),
        all groups are recognized and all items extracted without collapsing into 1 group.
        """
        # 10 columns: Serial column + 3 groups of 3 = 10 columns
        data = [
            ["م", "سعر", "خصم", "صنف", "سعر", "خصم", "صنف", "سعر", "خصم", "صنف"],
            ["1", "50.0", "20%", "دواء 1", "70.0", "30%", "دواء 2", "90.0", "25%", "دواء 3"],
            ["2", "60.0", "22%", "دواء 4", "80.0", "32%", "دواء 5", "100.0", "28%", "دواء 6"],
        ]
        table = MockTable(data)
        items, geom, groups, diag = parse_structural_table(table, 0, "مخزن تجريبي")
        self.assertEqual(len(groups), 3)
        self.assertEqual(len(items), 6)
        self.assertEqual(diag.accepted_rows, 6)


if __name__ == "__main__":
    unittest.main()
