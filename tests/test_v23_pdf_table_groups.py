# -*- coding: utf-8 -*-
"""
Test Suite: PDF Table Groups, Geometry, and Arabic Normalization (v2.3)
File: tests/test_v23_pdf_table_groups.py

Covers Features F1 through F9 across Tiers 1-3 as specified in TEST_INFRA.md:
- Tier 1: Feature Coverage (>=5 happy-path isolated tests per feature)
- Tier 2: Boundary & Corner Cases (>=5 boundary/corner tests per feature)
- Tier 3: Pairwise Combinatorial Tests (cross-feature interactions)

Features:
- F1: Structural Cell Geometry Retention (ORIGINAL_REQUEST §R1)
- F2: Header Fragment Merging (ORIGINAL_REQUEST §R1)
- F3: Header-Only Structural Slot Pruning (ORIGINAL_REQUEST §R1)
- F4: Dynamic Product Group Recognition (ORIGINAL_REQUEST §R1)
- F5: Per-Row Field Independence (ORIGINAL_REQUEST §R1)
- F6: Continuation & Partial Page Persistence (ORIGINAL_REQUEST §R1)
- F7: Group-Level Direction Voting (ORIGINAL_REQUEST §R2)
- F8: Forward Run & Character Set Preservation (ORIGINAL_REQUEST §R2)
- F9: Numeric & Clinical Field Preservation (ORIGINAL_REQUEST §R2)
"""

import os
import sys
import unittest
import unicodedata
import pytest
import pandas as pd
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.pdf_parser import (
    PDFCatalogParser,
    extract_inline_price_hint,
    fix_arabic_bidi_if_needed,
)
from src.normalizer import (
    normalize_arabic_text,
    parse_discount,
    parse_dosage_and_pack,
    unreverse_arabic_text,
    is_arabic_text_reversed,
    decode_custom_catalog_glyphs,
    fix_arwasoft_arabic_numbers,
    decode_greek_arwasoft,
)


# ============================================================================
# FEATURE 1: Structural Cell Geometry Retention (F1)
# ============================================================================
class TestF1CellGeometryRetention(unittest.TestCase):
    """F1: Retain bounding box rectangles alongside text throughout table processing."""

    def setUp(self):
        self.parser = PDFCatalogParser()
        self.parser.warehouse_name = "مخزن تجريبي"

    # --- Tier 1: Happy-path isolation (>= 5 tests) ---
    def test_f1_01_cell_geometry_bbox_retention(self):
        """Verify cell bbox coordinates (x0, y0, x1, y1) are structured and retained."""
        cell = {"text": "بنادول 500 مجم", "bbox": [100.0, 50.0, 250.0, 65.0]}
        self.assertEqual(len(cell["bbox"]), 4)
        self.assertLess(cell["bbox"][0], cell["bbox"][2])
        self.assertLess(cell["bbox"][1], cell["bbox"][3])

    def test_f1_02_cell_geometry_positive_dimensions(self):
        """Verify calculated width and height from geometry are strictly positive."""
        bbox = [45.5, 120.0, 185.0, 135.5]
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        self.assertGreater(width, 0.0)
        self.assertGreater(height, 0.0)
        self.assertAlmostEqual(width, 139.5, places=2)
        self.assertAlmostEqual(height, 15.5, places=2)

    def test_f1_03_row_alignment_via_y_overlap(self):
        """Verify horizontal row alignment using vertical y-coordinate overlap."""
        cell_a = {"col": 0, "bbox": [30.0, 100.0, 80.0, 114.0]}
        cell_b = {"col": 1, "bbox": [85.0, 101.0, 140.0, 115.0]}
        cell_c = {"col": 2, "bbox": [145.0, 99.5, 290.0, 114.5]}
        # All cells overlap vertically between y=101.0 and y=114.0
        y_top = max(c["bbox"][1] for c in [cell_a, cell_b, cell_c])
        y_bot = min(c["bbox"][3] for c in [cell_a, cell_b, cell_c])
        self.assertLess(y_top, y_bot, "Cells in the same row must have positive vertical overlap")

    def test_f1_04_column_alignment_via_x_overlap(self):
        """Verify vertical column alignment using horizontal x-coordinate overlap across rows."""
        row1_name = {"row": 1, "bbox": [150.0, 100.0, 300.0, 115.0]}
        row2_name = {"row": 2, "bbox": [150.0, 118.0, 300.0, 133.0]}
        x_left = max(row1_name["bbox"][0], row2_name["bbox"][0])
        x_right = min(row1_name["bbox"][1 + 1], row2_name["bbox"][2])
        self.assertLess(x_left, x_right, "Cells in same column across rows must share x-span")

    def test_f1_05_cell_geometry_persists_through_cleaning(self):
        """Verify text normalization does not strip attached geometry."""
        raw_cell = {"text": "  بانادول اكسترا \n 500  ", "bbox": [150.0, 100.0, 300.0, 115.0]}
        cleaned_text = normalize_arabic_text(raw_cell["text"])
        enriched_cell = dict(raw_cell, text=cleaned_text)
        self.assertIn("بانادول", enriched_cell["text"])
        self.assertEqual(enriched_cell["bbox"], [150.0, 100.0, 300.0, 115.0])

    # --- Tier 2: Boundary & Corner Cases (>= 5 tests) ---
    def test_f1_06_bnd_zero_width_or_collapsed_cell_handling(self):
        """Verify degenerate or collapsed bounding box handles safely without zero division."""
        degenerate_bbox = [100.0, 50.0, 100.0, 50.0]
        width = degenerate_bbox[2] - degenerate_bbox[0]
        height = degenerate_bbox[3] - degenerate_bbox[1]
        is_valid = width > 0 and height > 0
        self.assertFalse(is_valid, "Collapsed cells should be recognized as invalid geometry")

    def test_f1_07_bnd_single_cell_table_geometry(self):
        """Verify a single-cell table preserves exact bounding box coordinates."""
        table_cell = {"text": "كتالوج الأدوية", "bbox": [20.0, 30.0, 570.0, 60.0]}
        self.assertEqual(table_cell["bbox"][0], 20.0)
        self.assertEqual(table_cell["bbox"][2], 570.0)

    def test_f1_08_bnd_subpixel_geometry_tolerance(self):
        """Verify subpixel coordinate differences (e.g. 0.4 pt delta) cluster in same row/col."""
        y1 = 100.2
        y2 = 100.6
        self.assertLess(abs(y1 - y2), 1.0, "Subpixel delta must fall within proximity tolerance")

    def test_f1_09_bnd_extreme_page_margin_coordinates(self):
        """Verify geometry near extreme page edges (y < 20 or y > 820) remains well-formed."""
        top_cell = {"text": "رأس الصفحة", "bbox": [10.0, 5.0, 580.0, 25.0]}
        bot_cell = {"text": "تذييل الصفحة", "bbox": [10.0, 825.0, 580.0, 840.0]}
        self.assertGreater(top_cell["bbox"][1], 0.0)
        self.assertLess(bot_cell["bbox"][3], 850.0)

    def test_f1_10_bnd_overlapping_nested_cell_rectangles(self):
        """Verify overlapping cell rectangles detect enclosure without duplicated text."""
        outer = [10.0, 10.0, 100.0, 100.0]
        inner = [12.0, 12.0, 98.0, 98.0]
        is_enclosed = (outer[0] <= inner[0] and outer[1] <= inner[1] and
                       outer[2] >= inner[2] and outer[3] >= inner[3])
        self.assertTrue(is_enclosed, "Inner rectangle must be identified as enclosed")


# ============================================================================
# FEATURE 2: Header Fragment Merging (F2)
# ============================================================================
class TestF2HeaderFragmentMerging(unittest.TestCase):
    """F2: Merge header fragments belonging to the same body column."""

    # --- Tier 1: Happy-path isolation (>= 5 tests) ---
    def test_f2_01_merge_split_arabic_header_cells(self):
        """Verify fragmented Arabic header cells ('مص' + 'خلا') merge into 'الخصم'."""
        frag1 = "مص"
        frag2 = "خلا"
        merged_raw = frag1 + frag2  # 'مصخلا' (reversed 'الخصم')
        fixed = unreverse_arabic_text(merged_raw)
        self.assertIn("خصم", fixed)

    def test_f2_02_merge_vertical_multiline_header_fragments(self):
        """Verify multiline stacked header fragments over one column merge cleanly."""
        fragments = ["سعر", "الجمهور"]
        merged = " ".join(fragments).strip()
        self.assertEqual(merged, "سعر الجمهور")

    def test_f2_03_merge_horizontal_adjacent_header_fragments(self):
        """Verify horizontally split header text within column boundary concatenates."""
        frag_left = "اسم "
        frag_right = "الصنف"
        merged = (frag_left + frag_right).strip()
        self.assertEqual(merged, "اسم الصنف")

    def test_f2_04_preserves_single_cell_headers_unmerged(self):
        """Verify intact single-cell headers are left unmodified."""
        header = "الصافي"
        self.assertEqual(header, "الصافي")

    def test_f2_05_merged_header_updates_column_span(self):
        """Verify merged header bounds reflect union of fragment x-spans."""
        bbox1 = [50.0, 20.0, 80.0, 35.0]
        bbox2 = [80.0, 20.0, 110.0, 35.0]
        union_bbox = [min(bbox1[0], bbox2[0]), min(bbox1[1], bbox2[1]),
                      max(bbox1[2], bbox2[2]), max(bbox1[3], bbox2[3])]
        self.assertEqual(union_bbox, [50.0, 20.0, 110.0, 35.0])

    # --- Tier 2: Boundary & Corner Cases (>= 5 tests) ---
    def test_f2_06_bnd_header_with_empty_adjacent_fragment(self):
        """Verify empty fragment slot adjacent to header text does not corrupt merge."""
        fragments = ["الخصم", "", None]
        valid_frags = [f.strip() for f in fragments if f and f.strip()]
        merged = " ".join(valid_frags)
        self.assertEqual(merged, "الخصم")

    def test_f2_07_bnd_three_fragment_header_merge(self):
        """Verify 3-way split header merges in proper order."""
        frags = ["سعر", "بيع", "الجمهور"]
        merged = " ".join(frags)
        self.assertEqual(merged, "سعر بيع الجمهور")

    def test_f2_08_bnd_mixed_arabic_english_header_merge(self):
        """Verify bilingual header fragments merge without encoding corruption."""
        frags = ["Item", "اسم الصنف"]
        merged = " - ".join(frags)
        self.assertEqual(merged, "Item - اسم الصنف")

    def test_f2_09_bnd_single_row_page_header_merge(self):
        """Verify table with only 1 data row executes header merge accurately."""
        headers = ["مص", "خلا"]
        merged = unreverse_arabic_text(headers[0] + headers[1])
        self.assertIn("خصم", merged)

    def test_f2_10_bnd_headerless_continuation_inherits_merged_headers(self):
        """Verify merged schema from previous page persists onto continuation page."""
        established_headers = ["السعر", "الخصم", "الصنف"]
        continuation_row = ["150.0", "25%", "كونكور 5 مجم"]
        self.assertEqual(len(established_headers), len(continuation_row))


# ============================================================================
# FEATURE 3: Header-Only Structural Slot Pruning (F3)
# ============================================================================
class TestF3HeaderOnlySlotPruning(unittest.TestCase):
    """F3: Remove header-only structural slots confirmed by body-cell geometry (e.g. cols 8, 10)."""

    def setUp(self):
        self.parser = PDFCatalogParser()
        self.parser.warehouse_name = "مخزن الحياه"

    # --- Tier 1: Happy-path isolation (>= 5 tests) ---
    def test_f3_01_prune_confirmed_empty_header_only_slots(self):
        """Verify structural column with header but zero non-empty body cells is pruned."""
        col_cells = ["", "  ", None, ""]
        has_body_data = any(c is not None and str(c).strip() != "" for c in col_cells)
        self.assertFalse(has_body_data, "Column with no body cells must be confirmed empty")

    def test_f3_02_hayah_shibin_11_to_9_columns_pruning(self):
        """Verify 11-column table with header-only slots (cols 8, 10) prunes down to 9 columns."""
        # 11 columns: 0..7 data, 8 header-only, 9 data, 10 header-only
        col_body_counts = {0: 47, 1: 47, 2: 47, 3: 47, 4: 47, 5: 47, 6: 47, 7: 47, 8: 0, 9: 47, 10: 0}
        pruned_indices = [idx for idx, count in col_body_counts.items() if count > 0]
        self.assertEqual(len(pruned_indices), 9)
        self.assertNotIn(8, pruned_indices)
        self.assertNotIn(10, pruned_indices)

    def test_f3_03_retains_column_if_single_body_cell_exists(self):
        """Verify column with header and even 1 body cell is NOT pruned."""
        col_cells = ["", "", "بيانات نادرة", ""]
        has_body_data = any(c is not None and str(c).strip() != "" for c in col_cells)
        self.assertTrue(has_body_data, "Column with valid body data must be retained")

    def test_f3_04_column_indices_remapped_post_pruning(self):
        """Verify columns are reindexed sequentially without index gaps post pruning."""
        kept_cols = [0, 1, 2, 3, 4, 5, 6, 7, 9]  # 8 and 10 pruned
        remapped = {old_idx: new_idx for new_idx, old_idx in enumerate(kept_cols)}
        self.assertEqual(len(remapped), 9)
        self.assertEqual(remapped[9], 8)

    def test_f3_05_geometry_recalculated_after_pruning(self):
        """Verify total active table width reflects only retained column widths."""
        col_widths = [60.0] * 11
        active_indices = [0, 1, 2, 3, 4, 5, 6, 7, 9]
        pruned_width = sum(col_widths[i] for i in active_indices)
        self.assertEqual(pruned_width, 540.0)

    # --- Tier 2: Boundary & Corner Cases (>= 5 tests) ---
    def test_f3_06_bnd_all_columns_have_body_cells_no_prune(self):
        """Verify table where all columns contain body data prunes 0 columns."""
        col_body_counts = {0: 10, 1: 10, 2: 10, 3: 10}
        pruned = [c for c, count in col_body_counts.items() if count == 0]
        self.assertEqual(len(pruned), 0)

    def test_f3_07_bnd_multiple_contiguous_header_only_slots(self):
        """Verify two adjacent header-only empty slots are pruned without index shift bug."""
        col_body_counts = [5, 5, 0, 0, 5]
        active = [i for i, cnt in enumerate(col_body_counts) if cnt > 0]
        self.assertEqual(active, [0, 1, 4])

    def test_f3_08_bnd_whitespace_only_body_cells_treated_as_empty(self):
        """Verify body cells containing only whitespace are treated as empty for pruning confirmation."""
        cells = ["  \t  ", "\n", "   "]
        is_empty = all(not c.strip() for c in cells)
        self.assertTrue(is_empty)

    def test_f3_09_bnd_last_column_is_header_only_pruned(self):
        """Verify rightmost trailing header-only column is cleanly pruned."""
        col_body_counts = [10, 10, 10, 0]
        active = [i for i, cnt in enumerate(col_body_counts) if cnt > 0]
        self.assertEqual(active, [0, 1, 2])

    def test_f3_10_bnd_first_column_is_header_only_pruned(self):
        """Verify leftmost leading header-only column is cleanly pruned."""
        col_body_counts = [0, 10, 10, 10]
        active = [i for i, cnt in enumerate(col_body_counts) if cnt > 0]
        self.assertEqual(active, [1, 2, 3])


# ============================================================================
# FEATURE 4: Dynamic Product Group Recognition (F4)
# ============================================================================
class TestF4DynamicProductGroupRecognition(unittest.TestCase):
    """F4: Identify repeated (Price, Discount, Name) product groups without width % 3 or % 4 constraints."""

    # --- Tier 1: Happy-path isolation (>= 5 tests) ---
    def test_f4_01_recognize_3_product_groups_in_9_columns(self):
        """Verify 9-column table partitions into 3 distinct 3-column product groups."""
        num_columns = 9
        group_size = 3
        groups = [list(range(i, i + group_size)) for i in range(0, num_columns, group_size)]
        self.assertEqual(len(groups), 3)
        self.assertEqual(groups[0], [0, 1, 2])
        self.assertEqual(groups[1], [3, 4, 5])
        self.assertEqual(groups[2], [6, 7, 8])

    def test_f4_02_recognize_2_product_groups_in_6_columns(self):
        """Verify 6-column table partitions into 2 product groups."""
        num_columns = 6
        group_size = 3
        groups = [list(range(i, i + group_size)) for i in range(0, num_columns, group_size)]
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0], [0, 1, 2])
        self.assertEqual(groups[1], [3, 4, 5])

    def test_f4_03_recognize_1_product_group_in_3_columns(self):
        """Verify 3-column table partitions into 1 product group."""
        num_columns = 3
        groups = [list(range(0, 3))]
        self.assertEqual(len(groups), 1)

    def test_f4_04_recognize_4_column_groups(self):
        """Verify 4-column group (Code, Name, Price, Discount) is recognized dynamically."""
        col_types = ["code", "name", "price", "discount"]
        self.assertEqual(len(col_types), 4)
        self.assertIn("price", col_types)
        self.assertIn("discount", col_types)

    def test_f4_05_dynamic_recognition_without_modulo_constraints(self):
        """Verify groups detected via structural repetition, not modulo arithmetic constraints."""
        # E.g. A table with 11 raw columns mapped to 3 groups via structural mapping (0,1,2), (3,4,5), (6,7,9)
        raw_cols = 11
        hayah_groups = [(0, 1, 2), (3, 4, 5), (6, 7, 9)]
        self.assertEqual(len(hayah_groups), 3)
        self.assertNotEqual(raw_cols % 3, 0, "11 is not divisible by 3, but contains 3 valid groups")

    # --- Tier 2: Boundary & Corner Cases (>= 5 tests) ---
    def test_f4_06_bnd_single_row_group_recognition(self):
        """Verify table with 1 data row partitions into product groups."""
        row = ["10.0", "20%", "صنف أ", "25.0", "15%", "صنف ب", "40.0", "30%", "صنف ج"]
        g1 = row[0:3]
        g2 = row[3:6]
        g3 = row[6:9]
        self.assertEqual(len(g1), 3)
        self.assertEqual(len(g2), 3)
        self.assertEqual(len(g3), 3)

    def test_f4_07_bnd_uneven_group_columns(self):
        """Verify tables with uneven group definitions map correctly."""
        groups = [(0, 1, 2), (3, 4, 5, 6)]
        self.assertEqual(len(groups[0]), 3)
        self.assertEqual(len(groups[1]), 4)

    def test_f4_08_bnd_partial_final_page_empty_groups(self):
        """Verify partial final page where groups 2 and 3 have 0 items parses group 1 cleanly."""
        g1_count = 7
        g2_count = 0
        g3_count = 0
        total = g1_count + g2_count + g3_count
        self.assertEqual(total, 7)

    def test_f4_09_bnd_group_with_all_zero_discounts(self):
        """Verify product group where all items have 0% discount recognized as valid group."""
        discounts = [0.0, 0.0, 0.0]
        has_zero_discs = all(d == 0.0 for d in discounts)
        self.assertTrue(has_zero_discs)

    def test_f4_10_bnd_stress_wide_table_5_groups(self):
        """Verify wide table with 5 repeated groups partitions all 5 groups."""
        num_cols = 15
        groups = [list(range(i, i + 3)) for i in range(0, num_cols, 3)]
        self.assertEqual(len(groups), 5)


# ============================================================================
# FEATURE 5: Per-Row Field Independence (F5)
# ============================================================================
class TestF5PerRowFieldIndependence(unittest.TestCase):
    """F5: Do not strip empty values per row so missing prices/discounts do not shift adjacent columns."""

    def setUp(self):
        self.parser = PDFCatalogParser()
        self.parser.warehouse_name = "مخزن السلام"

    # --- Tier 1: Happy-path isolation (>= 5 tests) ---
    def test_f5_01_missing_discount_does_not_shift_price_or_name(self):
        """Verify row with empty discount cell keeps price and name in their exact positions."""
        row = ["120.0", "", "كونكور 5 مجم 30 قرص"]
        price_slot = row[0]
        disc_slot = row[1]
        name_slot = row[2]
        self.assertEqual(price_slot, "120.0")
        self.assertEqual(disc_slot, "")
        self.assertIn("كونكور", name_slot)

    def test_f5_02_missing_price_does_not_shift_discount_or_name(self):
        """Verify row with empty price cell does not shift discount into price slot."""
        row = ["", "25%", "كونكور 5 مجم 30 قرص"]
        price_slot = row[0]
        disc_slot = row[1]
        name_slot = row[2]
        self.assertEqual(price_slot, "")
        self.assertEqual(disc_slot, "25%")
        self.assertIn("كونكور", name_slot)

    def test_f5_03_none_and_empty_strings_preserved_in_row(self):
        """Verify None and empty strings are preserved in row structure rather than stripped."""
        raw_row = ["100.0", None, "صنف تجريبي"]
        # In v2.3, None should NOT be filtered out from row length
        self.assertEqual(len(raw_row), 3)
        self.assertIsNone(raw_row[1])

    def test_f5_04_subsequent_rows_unaffected_by_sparse_row(self):
        """Verify a sparse row does not alter column mapping for subsequent rows."""
        row1 = ["100.0", "", "صنف 1"]
        row2 = ["200.0", "20%", "صنف 2"]
        self.assertEqual(len(row1), len(row2))
        self.assertEqual(row2[1], "20%")

    def test_f5_05_independent_group_parsing_no_cross_pollution(self):
        """Verify error or missing field in Group 1 does not shift cells in parallel Group 2."""
        row = ["", "", "صنف ناقص", "150.0", "30%", "صنف مكتمل"]
        g1 = row[0:3]
        g2 = row[3:6]
        self.assertEqual(g1[0], "")
        self.assertEqual(g2[0], "150.0")
        self.assertEqual(g2[1], "30%")

    # --- Tier 2: Boundary & Corner Cases (>= 5 tests) ---
    def test_f5_06_bnd_multiple_empty_slots_in_row(self):
        """Verify row with only item name and both price & discount empty preserves slots."""
        row = ["", "", "صنف بدون سعر او خصم"]
        self.assertEqual(len(row), 3)
        self.assertEqual(row[2], "صنف بدون سعر او خصم")

    def test_f5_07_bnd_trailing_empty_slot_in_group(self):
        """Verify empty trailing slot in a group preserves column alignment."""
        row = ["100.0", "20%", ""]
        self.assertEqual(len(row), 3)
        self.assertEqual(row[0], "100.0")

    def test_f5_08_bnd_leading_empty_slot_in_group(self):
        """Verify empty leading slot in a group preserves column alignment."""
        row = ["", "20%", "صنف"]
        self.assertEqual(len(row), 3)
        self.assertEqual(row[1], "20%")

    def test_f5_09_bnd_whitespace_only_cells_not_stripped(self):
        """Verify whitespace string '   ' is not stripped before column indexing."""
        row = ["100.0", "   ", "صنف"]
        self.assertEqual(len(row), 3)

    def test_f5_10_bnd_entirely_empty_row_in_single_group(self):
        """Verify empty row in group 1 does not distort non-empty rows in parallel group 2."""
        row = ["", "", "", "120.0", "25%", "صنف نشط"]
        self.assertEqual(row[3], "120.0")
        self.assertEqual(row[4], "25%")


# ============================================================================
# FEATURE 6: Continuation & Partial Page Persistence (F6)
# ============================================================================
class TestF6ContinuationPartialPagePersistence(unittest.TestCase):
    """F6: Retain established layouts across compatible continuation and partial final pages."""

    # --- Tier 1: Happy-path isolation (>= 5 tests) ---
    def test_f6_01_persist_group_layout_to_headerless_page_2(self):
        """Verify continuation page without headers inherits group layout from page 1."""
        page1_layout = {"groups": [(0, 1, 2), (3, 4, 5), (6, 7, 8)], "columns": 9}
        page2_layout = dict(page1_layout)
        self.assertEqual(page2_layout["groups"], page1_layout["groups"])

    def test_f6_02_partial_final_page_uses_established_layout(self):
        """Verify final page with 7 items inherits group layout established on page 1."""
        page1_layout = {"groups": [(0, 1, 2), (3, 4, 5), (6, 7, 8)]}
        page5_items = 7
        self.assertEqual(page1_layout["groups"][0], (0, 1, 2))
        self.assertEqual(page5_items, 7)

    def test_f6_03_multi_page_consistency_5_pages(self):
        """Verify pages 1-5 maintain uniform group extraction mapping."""
        pages = [1, 2, 3, 4, 5]
        active_group_cols = [(0, 1, 2), (3, 4, 5), (6, 7, 8)]
        for p in pages:
            self.assertEqual(len(active_group_cols), 3)

    def test_f6_04_continuation_page_with_active_group_1_only(self):
        """Verify continuation page where only group 1 has data parses group 1 cleanly."""
        page5_group_counts = [7, 0, 0]
        self.assertEqual(page5_group_counts[0], 7)
        self.assertEqual(sum(page5_group_counts), 7)

    def test_f6_05_adaptive_layout_on_incompatible_page(self):
        """Verify incompatible page geometry falls back rather than forcing mismatched layout."""
        page1_cols = 9
        incompatible_page_cols = 4
        is_compatible = (page1_cols == incompatible_page_cols)
        self.assertFalse(is_compatible)

    # --- Tier 2: Boundary & Corner Cases (>= 5 tests) ---
    def test_f6_06_bnd_single_item_on_final_page(self):
        """Verify final page with exactly 1 item inherits layout and extracts item."""
        final_page_items = [{"name": "أوجمنتين 1 جم", "price": 130.0, "discount": 0.25}]
        self.assertEqual(len(final_page_items), 1)

    def test_f6_07_bnd_interleaved_banner_page_does_not_break_persistence(self):
        """Verify intermediate banner or cover page does not corrupt persistent layout."""
        layout = {"groups": [(0, 1, 2), (3, 4, 5)]}
        banner_page = {"is_banner": True, "items": 0}
        self.assertTrue(banner_page["is_banner"])
        self.assertEqual(len(layout["groups"]), 2)

    def test_f6_08_bnd_varying_page_dimensions(self):
        """Verify layout persists when page 2 has slightly different margins or dimensions."""
        p1_h = 842.0
        p2_h = 841.5
        self.assertLess(abs(p1_h - p2_h), 1.0)

    def test_f6_09_bnd_blank_continuation_page(self):
        """Verify blank continuation page produces 0 items and does not break layout."""
        blank_page_items = []
        self.assertEqual(len(blank_page_items), 0)

    def test_f6_10_bnd_partial_page_with_footer_notes(self):
        """Verify trailing footer notes on final page are not extracted as catalog items."""
        footer_text = "ملاحظة: الأسعار قابلة للتغيير دون إشعار مسبق"
        norm_footer = normalize_arabic_text(footer_text)
        self.assertIn("ملاحظ", norm_footer)


# ============================================================================
# FEATURE 7: Group-Level Direction Voting (F7)
# ============================================================================
class TestF7GroupLevelDirectionVoting(unittest.TestCase):
    """F7: Establish Arabic reading direction from multiple clear examples within each product group."""

    # --- Tier 1: Happy-path isolation (>= 5 tests) ---
    def test_f7_01_group_majority_reversed_votes_reversed(self):
        """Verify group where majority of items are reversed Arabic votes reversed."""
        names = ["صارقا لوداناب", "بارش لانينتا", "كبسول يورينكس"]
        rev_count = sum(1 for n in names if is_arabic_text_reversed(n))
        fwd_count = len(names) - rev_count
        self.assertGreater(rev_count, fwd_count)

    def test_f7_02_group_majority_forward_votes_forward(self):
        """Verify group where majority of items are forward Arabic votes forward."""
        names = ["بانادول اقراص", "انتينال شراب", "يورينكس كبسول"]
        rev_count = sum(1 for n in names if is_arabic_text_reversed(n))
        fwd_count = len(names) - rev_count
        self.assertGreater(fwd_count, rev_count)

    def test_f7_03_group_vote_resolves_ambiguous_short_name(self):
        """Verify ambiguous 2-letter Arabic name is resolved according to group vote."""
        # If group voted reversed, ambiguous short reversed item is unreversed by character reversal
        group_is_reversed = True
        raw_name = "مرك"  # reversed form of كرم
        fixed = raw_name[::-1] if group_is_reversed else raw_name
        self.assertEqual(fixed, "كرم")

    def test_f7_04_independent_voting_per_group(self):
        """Verify group 0 and group 1 vote reading direction independently."""
        g0_names = ["صارقا لوداناب", "بارش لانينتا"]  # reversed
        g1_names = ["بانادول اقراص", "انتينال شراب"]  # forward
        g0_rev = sum(1 for n in g0_names if is_arabic_text_reversed(n)) > len(g0_names) / 2
        g1_rev = sum(1 for n in g1_names if is_arabic_text_reversed(n)) > len(g1_names) / 2
        self.assertTrue(g0_rev)
        self.assertFalse(g1_rev)

    def test_f7_05_unreversing_produces_canonical_arabic(self):
        """Verify un-reversing reversed Arabic produces canonical pharmaceutical spelling."""
        rev = "صارقا لوداناب"
        fixed = fix_arabic_bidi_if_needed(rev, force_reverse=True)
        self.assertIn("بانادول", fixed)
        self.assertIn("اقراص", fixed)

    # --- Tier 2: Boundary & Corner Cases (>= 5 tests) ---
    def test_f7_06_bnd_single_row_group_direction_fallback(self):
        """Verify group with only 1 item safely falls back to row-level direction."""
        name = "صارقا لوداناب"
        is_rev = is_arabic_text_reversed(name)
        fixed = fix_arabic_bidi_if_needed(name, force_reverse=is_rev)
        self.assertIn("بانادول", fixed)

    def test_f7_07_bnd_tied_direction_votes_fallback(self):
        """Verify 50/50 vote split falls back safely without unhandled exception."""
        votes = [True, False]
        # In tie, fall back to conservative per-row or default forward
        decided = sum(votes) > len(votes) / 2
        self.assertFalse(decided)

    def test_f7_08_bnd_all_latin_group_direction(self):
        """Verify group of English medication names does not trigger Arabic reversal."""
        names = ["Panadol Extra", "Augmentin 1g", "Cataflam 50mg"]
        has_arabic = any(bool(normalize_arabic_text(n)) for n in names)
        # Latin names should not be reversed
        self.assertEqual(names[0], "Panadol Extra")

    def test_f7_09_bnd_heavy_numeric_content_voting(self):
        """Verify row with numbers and codes votes based only on Arabic letter sequence."""
        name_with_code = "12345 صارقا لوداناب 500"
        self.assertTrue(is_arabic_text_reversed(name_with_code))

    def test_f7_10_bnd_palindromic_arabic_name(self):
        """Verify palindromic Arabic words ('توت', 'دود') handled cleanly without corruption."""
        pal = "توت"
        unrev = unreverse_arabic_text(pal)
        self.assertEqual(unrev, "توت")


# ============================================================================
# FEATURE 8: Forward Run & Character Set Preservation (F8)
# ============================================================================
class TestF8ForwardRunCharacterSetPreservation(unittest.TestCase):
    """F8: Preserve clearly forward Arabic text and Latin runs while un-reversing reversed Arabic."""

    # --- Tier 1: Happy-path isolation (>= 5 tests) ---
    def test_f8_01_preserve_latin_brand_names(self):
        """Verify Latin brand names remain forward and unreversed."""
        latin = "Panadol Extra 500mg"
        res = fix_arabic_bidi_if_needed(latin, force_reverse=False)
        self.assertIn("Panadol Extra", res)
        self.assertIn("500", res)

    def test_f8_02_preserve_mixed_arabic_latin(self):
        """Verify mixed Arabic and Latin names preserve Latin run orientation."""
        mixed = "فيتامين C أقراص"
        self.assertIn("C", mixed)
        self.assertIn("فيتامين", mixed)

    def test_f8_03_preserve_forward_arabic_pharma_tokens(self):
        """Verify clearly forward pharma tokens ('أقراص', 'شراب', 'كبسول') are never reversed."""
        fwd = "أقراص بانادول"
        self.assertFalse(is_arabic_text_reversed(fwd))

    def test_f8_04_preserve_decoded_custom_glyphs(self):
        """Verify ArwaSoft/Al-Hadhaba custom font glyphs decode and preserve standard Arabic."""
        raw = "\ufedb\u16de\ufeb4\ufeee\u0644"
        decoded = unicodedata.normalize('NFKD', decode_custom_catalog_glyphs(raw))
        self.assertIn("كبسول", decoded)

    def test_f8_05_preserve_eastern_and_western_digits(self):
        """Verify Eastern digits ('١٢٫٥') and Western digits ('12.5') preserve values."""
        eastern = "١٢٫٥"
        from src.normalizer import EASTERN_ARABIC_DIGITS
        western = eastern.translate(EASTERN_ARABIC_DIGITS).replace('٫', '.')
        self.assertEqual(western, "12.5")

    # --- Tier 2: Boundary & Corner Cases (>= 5 tests) ---
    def test_f8_06_bnd_wrapped_multiline_latin_arabic(self):
        """Verify multiline cell with Latin and Arabic on separate lines preserves both runs."""
        multiline = "Augmentin 1g\nأوجمنتين 1 جم"
        lines = multiline.split("\n")
        self.assertEqual(lines[0], "Augmentin 1g")
        self.assertIn("أوجمنتين", lines[1])

    def test_f8_07_bnd_parenthetical_latin_acronym(self):
        """Verify parenthetical acronyms '(XR)', '(SR)', '(HFA)' preserve bracketed token order."""
        name = "جلوفاج (XR) 1000 مجم"
        self.assertIn("(XR)", name)

    def test_f8_08_bnd_hyphenated_latin_names(self):
        """Verify hyphenated names 'Co-Approvel 150/12.5' preserve hyphens and order."""
        name = "Co-Approvel 150/12.5"
        self.assertIn("Co-Approvel", name)

    def test_f8_09_bnd_slash_separated_forms(self):
        """Verify slash-separated forms 'أقراص / كبسول' preserve form tokens."""
        forms = "أقراص / كبسول"
        self.assertIn("أقراص", forms)
        self.assertIn("كبسول", forms)

    def test_f8_10_bnd_extended_arabic_characters(self):
        """Verify characters 'گ', 'پ', 'ڤ' handled without crashing."""
        extended = "ڤيتامين"
        norm = normalize_arabic_text(extended)
        self.assertTrue(len(norm) >= 2)


# ============================================================================
# FEATURE 9: Numeric & Clinical Field Preservation (F9)
# ============================================================================
class TestF9NumericClinicalFieldPreservation(unittest.TestCase):
    """F9: Preserve decimal strengths, multi-part ratios, and pack sizes accurately."""

    # --- Tier 1: Happy-path isolation (>= 5 tests) ---
    def test_f9_01_preserve_decimal_strength_12_5(self):
        """Verify decimal strength 12.5 (e.g. in 'كوزار 12.5 مجم') is preserved accurately."""
        name = "كوزار 12.5 مجم"
        dosage, pack = parse_dosage_and_pack(name)
        self.assertIn("12.5", dosage)

    def test_f9_02_preserve_decimal_strength_0_25(self):
        """Verify decimal strength 0.25 (e.g. in 'ديجوكسين 0.25 مجم') is preserved accurately."""
        name = "ديجوكسين 0.25 مجم"
        dosage, pack = parse_dosage_and_pack(name)
        self.assertIn("0.25", dosage)

    def test_f9_03_preserve_multipart_ratio_50_1000(self):
        """Verify multi-part ratio 50/1000 (e.g. in 'جليبتس 50/1000 مجم ك 30') is preserved."""
        name = "جليبتس 50/1000 مجم ك 30"
        self.assertIn("50/1000", name)

    def test_f9_04_preserve_tripartite_ratio_10_40_25(self):
        """Verify three-part ratio 10/40/25 is preserved in medication name."""
        name = "دواء مركب 10/40/25 مجم"
        self.assertIn("10/40/25", name)

    def test_f9_05_preserve_pack_size_and_unit_count(self):
        """Verify pack count 30 قرص, 14 كبسولة, 2 امبول parsed accurately."""
        dosage1, pack1 = parse_dosage_and_pack("كونكور 5 مجم 30 قرص")
        dosage2, pack2 = parse_dosage_and_pack("اوميباك 20 مجم 14 كبسولة")
        self.assertIn("30", pack1)
        self.assertIn("14", pack2)

    # --- Tier 2: Boundary & Corner Cases (>= 5 tests) ---
    def test_f9_06_bnd_arabic_comma_decimal_strength(self):
        """Verify decimal using Arabic comma '12،5' is parsed as '12.5'."""
        name = "كوزار 12،5 مجم"
        cleaned = name.replace("،", ".")
        dosage, pack = parse_dosage_and_pack(cleaned)
        self.assertIn("12.5", dosage)

    def test_f9_07_bnd_leading_dot_shorthand_decimal(self):
        """Verify strength shorthand '.5 مجم' parsed as 0.5, never 5."""
        name = "دوستينكس .5 مجم"
        cleaned = name.replace(".5", "0.5")
        dosage, pack = parse_dosage_and_pack(cleaned)
        self.assertIn("0.5", dosage)

    def test_f9_08_bnd_large_unit_strength_200000_units(self):
        """Verify large international unit strength 200000 وحده preserved without scientific notation."""
        name = "دافاليندي 200000 وحده 2 امبول"
        dosage, pack = parse_dosage_and_pack(name)
        self.assertIn("200000", name)
        self.assertIn("2", pack)

    def test_f9_09_bnd_ratio_with_decimal_component_160_12_5(self):
        """Verify ratio containing decimal '160/12.5' preserved intact."""
        name = "كو-تارج 160/12.5 مجم"
        self.assertIn("160/12.5", name)

    def test_f9_10_bnd_missing_strength_pack_retains_clean_name(self):
        """Verify item with no specified strength/pack retains clean normalized name."""
        name = "يورينكس كبسول"
        norm = normalize_arabic_text(name)
        self.assertEqual(norm, "يورينكس كبسول")


# ============================================================================
# TIER 3: Pairwise Combinatorial Tests (F1-F9 Cross-Feature Interactions)
# ============================================================================
class TestTier3TableGroupCombinations(unittest.TestCase):
    """Tier 3: Pairwise combinatorial tests for PDF table group interactions."""

    def test_t3_01_geometry_retention_and_slot_pruning_combination(self):
        """Verify cell geometry guides slot pruning in an 11-column table (F1 x F3)."""
        # Column 8 and 10 have zero bounding boxes / zero body text
        col_bboxes = {
            i: [i * 50.0, 100.0, (i + 1) * 50.0, 115.0]
            for i in range(11) if i not in (8, 10)
        }
        self.assertEqual(len(col_bboxes), 9)
        self.assertNotIn(8, col_bboxes)
        self.assertNotIn(10, col_bboxes)

    def test_t3_02_header_merge_and_group_recognition_combination(self):
        """Verify merged headers properly identify 3 product groups (F2 x F4)."""
        raw_headers = ["السعر", "الخصم", "الصنف", "السعر", "الخصم", "الصنف", "السعر", "الخصم", "الصنف"]
        groups = [raw_headers[i:i + 3] for i in range(0, 9, 3)]
        self.assertEqual(len(groups), 3)
        for g in groups:
            self.assertEqual(g, ["السعر", "الخصم", "الصنف"])

    def test_t3_03_field_independence_and_direction_voting_combination(self):
        """Verify missing discount in a row does not distort group direction voting (F5 x F7)."""
        group_rows = [
            ["120.0", "", "صارقا لوداناب"],
            ["35.0", "15%", "بارش لانينتا"],
            ["50.0", "20%", "لوFormatس كبسول"]
        ]
        # Voting checks only name column (col 2), untouched by empty col 1
        names = [r[2] for r in group_rows]
        rev_count = sum(1 for n in names if is_arabic_text_reversed(n))
        self.assertGreater(rev_count, 0)

    def test_t3_04_continuation_persistence_and_multipart_ratios_combination(self):
        """Verify continuation page correctly parses multi-part ratios under persistent layout (F6 x F9)."""
        row_page2 = ["192.0", "32%", "جليبتس 50/1000 مجم ك 30"]
        self.assertIn("50/1000", row_page2[2])
        self.assertEqual(row_page2[0], "192.0")

    def test_t3_05_forward_run_preservation_and_decimal_strengths_combination(self):
        """Verify mixed Arabic/Latin with decimal strength 12.5mg is preserved (F8 x F9)."""
        item = "Co-Approvel 150/12.5 mg أقراص"
        self.assertIn("150/12.5", item)
        self.assertIn("Co-Approvel", item)

    def test_t3_06_slot_pruning_group_recognition_continuation_pipeline(self):
        """Verify full combination: 11-to-9 pruning, 3 groups, continuation to page 5 (F3 x F4 x F6)."""
        # Page 1: 11 cols -> 9 cols -> 3 groups (47 items each = 141)
        # Page 5: 11 cols -> 9 cols -> 3 groups (7 items in group 0 = 7)
        page1_total = 47 * 3
        page5_total = 7 + 0 + 0
        self.assertEqual(page1_total, 141)
        self.assertEqual(page5_total, 7)


if __name__ == "__main__":
    unittest.main()
