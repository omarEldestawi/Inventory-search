# -*- coding: utf-8 -*-
"""
Adversarial Stress Test Suite: Challenger 1
File: tests/test_adversarial_challenger_1.py

Adversarially challenges:
1. Multi-table processing (R1):
   - Empty/degenerate tables, single-cell tables, whitespace tables
   - Heterogeneous multi-tables (differing column counts and group schemas on one page)
   - Overlapping/nested bounding box tables
   - Non-catalog header/footer metadata banners
   - Disjoint banner stitching across page (vulnerability probe)
2. Headerless continuation & mixed-group layouts (R2):
   - Standalone single-row PDF with zero headers anywhere
   - All permutations of mixed-group header placement (3 groups side-by-side)
   - Edge case drug names containing header keywords across structural and legacy tables
   - Multi-page continuation with sparse final pages
   - Incompatible geometry/role rejection
3. Pricing & Discount boundaries:
   - Explicit zero discounts ('0%', '0.0%') vs blank vs negative discounts in structural tables
   - Single-row outlier swapping whole table in legacy extraction (vulnerability probe)
   - Zero price, negative price, extreme price (>10,000 EGP) rejection
4. Cache validation & security invariants (R3):
   - Content tampering & byte alterations
   - Timestamp touch with identical content
   - Malformed, relative-path, truncated, and mismatched fingerprints
   - Truth-value safety on multi-row DataFrames
   - Partial catalog acknowledgment token lifecycle and invalidation
"""

import os
import sys
import time
import shutil
import tempfile
import unittest
import pandas as pd
import pytest

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, PageBreak, Spacer

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.pdf_parser import PDFCatalogParser
from src.catalog_diagnostics import (
    FileFingerprint,
    CatalogResult,
    RowDiagnostic,
    GroupDiagnostics,
    PageDiagnostics,
    ImportDiagnostics,
    PARSER_REVISION,
    METADATA_KEY,
)
from src.catalog_reader import (
    is_genuine_header_cell,
    is_group_header_row,
    parse_structural_table,
    analyze_table_geometry,
    detect_product_groups,
    extract_item_from_group_row,
    TableGeometry,
)
from src.pipeline import (
    run_procurement_pipeline,
    PipelineExecutionError,
    validate_cached_catalog,
)
from src.controller import (
    inspect_catalog,
    global_catalog_cache,
    CatalogCache,
    refresh_catalog,
)


def _build_pdf(file_path: str, flowables: list, pagesize=letter, margins=20):
    doc = SimpleDocTemplate(
        file_path,
        pagesize=pagesize,
        leftMargin=margins,
        rightMargin=margins,
        topMargin=margins,
        bottomMargin=margins,
    )
    doc.build(flowables)


def _make_grid_table(data: list, col_widths: list) -> Table:
    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    return t


def _create_order_excel(file_path: str, items: list[str]):
    rows = [{'item_name': name, 'quantity': 5} for name in items]
    df = pd.DataFrame(rows)
    df.to_excel(file_path, index=False)


def _get_diagnostics(df: pd.DataFrame) -> ImportDiagnostics:
    res = CatalogResult.from_dataframe(df)
    if res is not None and res.diagnostics is not None:
        return res.diagnostics
    attrs_meta = df.attrs.get(METADATA_KEY)
    if attrs_meta is not None:
        if isinstance(attrs_meta, dict) and "diagnostics" in attrs_meta:
            diag = attrs_meta["diagnostics"]
            if isinstance(diag, ImportDiagnostics):
                return diag
            if hasattr(diag, "status"):
                return diag
    raise ValueError("Could not extract ImportDiagnostics from DataFrame")


class TestAdversarialChallenger1(unittest.TestCase):
    """Authoritative adversarial test suite for Challenger 1."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="adv_challenger1_")
        global_catalog_cache.clear()

    def tearDown(self):
        global_catalog_cache.clear()
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    # =========================================================================
    # R1: Multi-Table Extraction & Geometry Stress
    # =========================================================================

    def test_adv_01_empty_and_degenerate_tables(self):
        """Stress: Page with single-cell, empty, and whitespace tables must not crash."""
        pdf_path = os.path.join(self.temp_dir, "adv01_degenerate.pdf")

        # 1-cell table
        t1 = _make_grid_table([['Single Cell Note']], [200])
        # Table with empty strings
        t2 = _make_grid_table([['', ''], ['', '']], [100, 100])
        # Genuine 3-column table
        t3 = _make_grid_table([
            ['Disc', 'Price', 'Item Name'],
            ['10%', '50.00', 'Panadol Extra 500mg']
        ], [50, 50, 200])

        _build_pdf(pdf_path, [t1, Spacer(1, 10), t2, Spacer(1, 10), t3])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Adv Warehouse")
        df = parser.parse()

        self.assertFalse(df.empty, "Parser returned empty DataFrame despite valid table t3!")
        self.assertEqual(len(df), 1)
        self.assertIn('Panadol Extra', df.iloc[0]['item_name'])
        self.assertEqual(df.iloc[0]['base_price'], 50.0)

        diag = _get_diagnostics(df)
        self.assertEqual(diag.accepted_rows, 1)
        self.assertEqual(diag.status, "complete")

    def test_adv_02_three_heterogeneous_tables_on_single_page(self):
        """Stress: 3 tables on 1 page with differing column counts (6 cols, 3 cols, 9 cols)."""
        pdf_path = os.path.join(self.temp_dir, "adv02_heterogeneous.pdf")

        # Table 1: 6 columns (2 groups: 2 items)
        data1 = [
            ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name'],
            ['10%', '30.00', 'Cataflam 50mg', '12%', '40.00', 'Voltaren 100mg'],
        ]
        t1 = _make_grid_table(data1, [40, 40, 170, 40, 40, 170])

        # Table 2: 3 columns (1 group: 1 item)
        data2 = [
            ['Disc', 'Price', 'Item Name'],
            ['15%', '25.00', 'Antinal 200mg'],
        ]
        t2 = _make_grid_table(data2, [50, 50, 250])

        # Table 3: 9 columns (3 groups: 3 items)
        data3 = [
            ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name'],
            ['5%', '60.00', 'Augmentin 1g', '8%', '75.00', 'Curam 1g', '20%', '15.00', 'Strepsils Honey'],
        ]
        t3 = _make_grid_table(data3, [35, 35, 110, 35, 35, 110, 35, 35, 110])

        _build_pdf(pdf_path, [t1, Spacer(1, 15), t2, Spacer(1, 15), t3])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Hetero Warehouse")
        df = parser.parse()

        # Expected: 2 + 1 + 3 = 6 products
        self.assertEqual(len(df), 6, f"Expected 6 products from 3 tables, got {len(df)}")
        extracted_text = " ".join(df['item_name'])
        for expected in ['Cataflam', 'Voltaren', 'Antinal', 'Augmentin', 'Curam', 'Strepsils']:
            self.assertIn(expected, extracted_text)

        diag = _get_diagnostics(df)
        self.assertEqual(diag.accepted_rows, 6)
        self.assertEqual(diag.status, "complete")

        # Verify page diagnostics has distinct group provenance tracking
        p1 = diag.pages[0]
        self.assertGreaterEqual(len(p1.groups), 3)

    def test_adv_03_non_catalog_metadata_banners_ignored(self):
        """Stress: Non-catalog header and footer banners must not trigger dummy rejected rows."""
        pdf_path = os.path.join(self.temp_dir, "adv03_banners.pdf")

        # Top banner table (Print timestamp and branch metadata - 2 columns)
        banner_top = _make_grid_table([
            ['Printed: 2026-10-28 09:30:15 AM', 'Branch: Shibin El-Kom']
        ], [240, 240])

        # Catalog table (2 groups x 2 rows = 4 products)
        catalog_table = _make_grid_table([
            ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name'],
            ['10%', '20.00', 'Aspirin Protect 100mg', '15%', '45.00', 'Concor 5mg'],
            ['20%', '18.00', 'Amoclan 1g', '5%', '30.00', 'Flagyl 500mg'],
        ], [40, 40, 160, 40, 40, 160])

        # Footer banner table (General non-numeric terms)
        banner_bottom = _make_grid_table([
            ['Page 1 of 1', 'Terms: Official Cash Payment', 'Branch Office']
        ], [120, 200, 160])

        _build_pdf(pdf_path, [banner_top, Spacer(1, 10), catalog_table, Spacer(1, 10), banner_bottom])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Banner Warehouse")
        df = parser.parse()

        self.assertEqual(len(df), 4)
        diag = _get_diagnostics(df)
        self.assertEqual(diag.accepted_rows, 4)
        self.assertEqual(diag.rejected_rows, 0, f"Expected 0 rejected rows from banners, got {diag.rejected_rows}")
        self.assertEqual(diag.status, "complete")

    def test_adv_03b_vulnerability_disjoint_banner_stitching_across_page(self):
        """
        Adversarial Vulnerability Probe:
        When a top banner and bottom banner share column count and horizontal bounds,
        _stitch_contiguous_tables stitches them across the entire page height without
        checking vertical proximity. If one banner contains a hotline/phone number
        (e.g. Hotline: 19999), _is_likely_catalog_table misidentifies it as a catalog price,
        falsely registering rejected rows and demoting page status to 'partial'.
        """
        pdf_path = os.path.join(self.temp_dir, "adv03b_banner_stitch.pdf")

        # Top banner (y ~ 20..35)
        banner_top = _make_grid_table([
            ['Printed: 2026-10-28 09:30:15 AM', 'Branch: Shibin El-Kom', 'Operator: Admin']
        ], [160, 160, 160])

        # Catalog table in middle
        catalog_table = _make_grid_table([
            ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name'],
            ['10%', '20.00', 'Aspirin Protect 100mg', '15%', '45.00', 'Concor 5mg'],
        ], [40, 40, 160, 40, 40, 160])

        # Bottom banner (y ~ 700..715) containing hotline number
        banner_bottom = _make_grid_table([
            ['Page 1 of 1', 'Terms: Cash on Delivery', 'Hotline: 19999']
        ], [160, 160, 160])

        _build_pdf(pdf_path, [banner_top, Spacer(1, 20), catalog_table, Spacer(1, 20), banner_bottom])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Stitch Warehouse")
        df = parser.parse()

        self.assertEqual(len(df), 2)
        diag = _get_diagnostics(df)

        # Empirically verify the defect: stitched non-catalog banners falsely generate rejected rows
        self.assertGreater(
            diag.rejected_rows, 0,
            "Defect verified: Disjoint banners stitched across vertical height produced spurious rejected rows."
        )

    # =========================================================================
    # R2: Headerless Continuation, Single-Row Tables, & Mixed Headers
    # =========================================================================

    def test_adv_04_headerless_single_row_zero_headers(self):
        """Stress: Standalone PDF with no headers anywhere and only 1 product row."""
        pdf_path = os.path.join(self.temp_dir, "adv04_single_row_no_hdr.pdf")

        # 3 columns, 1 row of pure product data
        t = _make_grid_table([
            ['12.5%', '85.50', 'Augmentin 1g 14 Tab']
        ], [50, 50, 250])

        _build_pdf(pdf_path, [t])

        parser = PDFCatalogParser(pdf_path, warehouse_name="SingleRow Warehouse")
        df = parser.parse()

        self.assertEqual(len(df), 1)
        self.assertIn('Augmentin', df.iloc[0]['item_name'])
        self.assertAlmostEqual(df.iloc[0]['base_price'], 85.50)
        self.assertAlmostEqual(df.iloc[0]['discount_rate'], 0.125)

        diag = _get_diagnostics(df)
        self.assertEqual(diag.accepted_rows, 1)
        self.assertEqual(diag.rejected_rows, 0)
        self.assertEqual(diag.status, "complete")

    def test_adv_05_side_by_side_3group_all_mixed_header_permutations(self):
        """Stress: Permutations of mixed header placement across 3 side-by-side groups."""
        permutations = [
            # (name, group0_is_hdr, group1_is_hdr, group2_is_hdr)
            ("p1_H_D_D", True, False, False),
            ("p2_D_H_D", False, True, False),
            ("p3_D_D_H", False, False, True),
            ("p4_H_H_D", True, True, False),
            ("p5_H_D_H", True, False, True),
            ("p6_D_H_H", False, True, True),
        ]

        for p_name, g0_hdr, g1_hdr, g2_hdr in permutations:
            with self.subTest(perm=p_name):
                pdf_path = os.path.join(self.temp_dir, f"adv05_{p_name}.pdf")

                hdr_cells = ['Disc', 'Price', 'Item Name']
                data_cells_g0 = ['10%', '50.00', 'Panadol Extra 500mg']
                data_cells_g1 = ['15%', '35.00', 'Cataflam 50mg']
                data_cells_g2 = ['20%', '90.00', 'Augmentin 1g']

                # Row 0
                row0 = (
                    (hdr_cells if g0_hdr else data_cells_g0) +
                    (hdr_cells if g1_hdr else data_cells_g1) +
                    (hdr_cells if g2_hdr else data_cells_g2)
                )

                # Row 1 (all data rows)
                row1 = [
                    '5%', '22.00', 'Congestal Tab',
                    '8%', '18.00', 'Antinal 200mg',
                    '12%', '45.00', 'Amoclan 1g'
                ]

                # Row 2 (all data rows)
                row2 = [
                    '10%', '60.00', 'Brufen 400mg',
                    '7%', '30.00', 'Flagyl 500mg',
                    '25%', '15.00', 'Strepsils Honey'
                ]

                table_data = [row0, row1, row2]
                t = _make_grid_table(table_data, [35, 35, 110, 35, 35, 110, 35, 35, 110])
                _build_pdf(pdf_path, [t])

                parser = PDFCatalogParser(pdf_path, warehouse_name=f"Warehouse_{p_name}")
                df = parser.parse()

                # Expected items:
                # Row 1 and Row 2 have 3 items each = 6 items.
                # Row 0 has (not g0_hdr) + (not g1_hdr) + (not g2_hdr) items.
                expected_row0_count = (0 if g0_hdr else 1) + (0 if g1_hdr else 1) + (0 if g2_hdr else 1)
                expected_total = 6 + expected_row0_count

                self.assertEqual(
                    len(df), expected_total,
                    f"Permutation {p_name}: expected {expected_total} items, got {len(df)}"
                )

                # Invariant: Header text must NEVER be extracted as product name or price
                for item_name in df['item_name']:
                    self.assertNotIn("Item Name", item_name)
                    self.assertNotIn("Price", item_name)
                    self.assertNotIn("Disc", item_name)

                diag = _get_diagnostics(df)
                self.assertEqual(diag.accepted_rows, expected_total)
                self.assertEqual(diag.status, "complete")

    def test_adv_06_header_keyword_in_product_names_structural_multi_group(self):
        """Stress: Structural tables with product names containing 'Item', 'Price', 'Discount', 'Stock'."""
        pdf_path = os.path.join(self.temp_dir, "adv06_keyword_structural.pdf")

        # 2 groups x 2 rows = 4 products in a structural table
        table_data = [
            ['10%', '40.00', 'Item Care 50ml Cream', '12%', '35.00', 'Price Check 100mg Gel'],
            ['15%', '25.00', 'Discount Plus Syrup', '8%', '60.00', 'Stock Fresh 200ml Solution'],
        ]
        t = _make_grid_table(table_data, [40, 40, 160, 40, 40, 160])
        _build_pdf(pdf_path, [t])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Keyword Structural Warehouse")
        df = parser.parse()

        # Structural extraction using is_genuine_header_cell correctly identifies all 4 as products
        self.assertEqual(len(df), 4, f"Expected 4 products with keyword names, got {len(df)}")
        extracted = " ".join(df['item_name'])
        self.assertIn('Item Care', extracted)
        self.assertIn('Price Check', extracted)
        self.assertIn('Discount Plus', extracted)
        self.assertIn('Stock Fresh', extracted)

        diag = _get_diagnostics(df)
        self.assertEqual(diag.accepted_rows, 4)
        self.assertEqual(diag.status, "complete")

    def test_adv_07_multipage_sparse_final_page(self):
        """Stress: Multi-page catalog where final page has empty cells in groups 1 and 2."""
        pdf_path = os.path.join(self.temp_dir, "adv07_sparse_final.pdf")

        # Page 1: 3 groups x 2 rows = 6 items
        data_p1 = [
            ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name'],
            ['10%', '50.00', 'Panadol 500mg', '15%', '35.00', 'Cataflam 50mg', '20%', '90.00', 'Augmentin 1g'],
            ['5%', '22.00', 'Congestal Tab', '8%', '18.00', 'Antinal 200mg', '12%', '45.00', 'Amoclan 1g'],
        ]
        t1 = _make_grid_table(data_p1, [35, 35, 110, 35, 35, 110, 35, 35, 110])

        # Page 2: Continuation, only Group 0 has 1 product, Groups 1 & 2 are empty cells
        data_p2 = [
            ['10%', '60.00', 'Brufen 400mg', '', '', '', '', '', ''],
        ]
        t2 = _make_grid_table(data_p2, [35, 35, 110, 35, 35, 110, 35, 35, 110])

        _build_pdf(pdf_path, [t1, PageBreak(), t2])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Sparse Warehouse")
        df = parser.parse()

        # Expected: 6 items on page 1 + 1 item on page 2 = 7 items total
        self.assertEqual(len(df), 7)
        extracted = " ".join(df['item_name'])
        self.assertIn('Brufen', extracted)

        diag = _get_diagnostics(df)
        self.assertEqual(diag.accepted_rows, 7)
        self.assertEqual(diag.rejected_rows, 0, f"Sparse empty cells should not be counted as rejected rows!")
        self.assertEqual(diag.status, "complete")

    # =========================================================================
    # Pricing & Discount Boundaries
    # =========================================================================

    def test_adv_08_explicit_zero_discount_in_structural_table(self):
        """Stress: Explicit zero discounts ('0%', '0.0%') accepted; blank & negative rejected."""
        pdf_path = os.path.join(self.temp_dir, "adv08_discounts.pdf")

        # 2 groups x 3 rows in structural table:
        # Row 0: Valid 0% | Valid '0.0%' explicit zero discount
        # Row 1: Blank discount (rejected) | Negative discount (rejected)
        # Row 2: Excessive 95% discount with high price 150.0 (rejected) | Normal 10% discount (accepted)
        data = [
            ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name'],
            ['0%', '50.00', 'Panadol Zero Disc', '0.0%', '35.00', 'Cataflam Net Price'],
            ['', '40.00', 'Blank Discount Drug', '-5%', '30.00', 'Negative Discount Drug'],
            ['95%', '150.00', 'Excessive Discount Drug', '10%', '60.00', 'Brufen Normal Drug'],
        ]
        t = _make_grid_table(data, [40, 40, 160, 40, 40, 160])
        _build_pdf(pdf_path, [t])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Discount Structural Warehouse")
        df = parser.parse()

        # Accepted items: Panadol (0%), Cataflam (0.0%), Brufen (10%) = 3 items
        self.assertEqual(len(df), 3, f"Expected 3 accepted items, got {len(df)}")
        extracted_names = " ".join(df['item_name'])
        self.assertIn('Panadol Zero Disc', extracted_names)
        self.assertIn('Cataflam Net Price', extracted_names)
        self.assertIn('Brufen Normal Drug', extracted_names)

        # Check explicit zero discounts evaluated to 0.0
        panadol_row = df[df['item_name'].str.contains('Panadol Zero Disc')].iloc[0]
        cataflam_row = df[df['item_name'].str.contains('Cataflam Net Price')].iloc[0]
        self.assertEqual(panadol_row['discount_rate'], 0.0)
        self.assertEqual(cataflam_row['discount_rate'], 0.0)

        diag = _get_diagnostics(df)
        self.assertEqual(diag.accepted_rows, 3)
        self.assertEqual(diag.rejected_rows, 3)
        self.assertEqual(diag.status, "partial")
        self.assertTrue(diag.requires_acknowledgment)

    def test_adv_08b_vulnerability_single_row_outlier_swaps_whole_legacy_table(self):
        """
        Adversarial Vulnerability Probe:
        In legacy extraction (_find_column_indices & _should_swap_price_and_discount),
        when a table has 1 group (3 cols) with explicit headers ['Disc', 'Price', 'Item Name'],
        if a single row contains an extreme discount (e.g. '95%' and '80.00'), the swap detector
        swaps the Price and Discount columns for the entire table based on that single row,
        treating '95' as price and '80' as discount (80%), while invalidating genuine zero discounts.
        """
        pdf_path = os.path.join(self.temp_dir, "adv08b_swap_probe.pdf")

        data = [
            ['Disc', 'Price', 'Item Name'],
            ['0%', '50.00', 'Panadol Zero Disc'],
            ['95%', '80.00', 'Excessive Discount Drug'],
        ]
        t = _make_grid_table(data, [50, 50, 200])
        _build_pdf(pdf_path, [t])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Legacy Swap Warehouse")
        df = parser.parse()

        # Verify the defect: Excessive Discount Drug was accepted with swapped price 95.0 and discount 0.8
        self.assertEqual(len(df), 1)
        accepted_item = df.iloc[0]
        self.assertEqual(accepted_item['item_name'], 'Excessive Discount Drug')
        self.assertEqual(accepted_item['base_price'], 95.0)
        self.assertEqual(accepted_item['discount_rate'], 0.8)

    def test_adv_09_zero_price_and_negative_price_rejection(self):
        """Stress: Prices <= 0 or >= 10,000 must be rejected and result in partial status."""
        pdf_path = os.path.join(self.temp_dir, "adv09_prices.pdf")

        # 2 groups x 3 rows:
        # Row 0: Normal Price 50.0 | Normal Price 40.0
        # Row 1: Zero price 0.0 (rejected) | Negative price -25.0 (rejected)
        # Row 2: Excessive 15000.0 (rejected) | Blank name (rejected)
        data = [
            ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name'],
            ['10%', '50.00', 'Panadol Normal Price', '15%', '40.00', 'Cataflam Normal Price'],
            ['15%', '0.00', 'Free Price Drug', '12%', '-25.00', 'Negative Price Drug'],
            ['8%', '15000.00', 'Excessive Price Drug', '10%', '60.00', ''],
        ]
        t = _make_grid_table(data, [40, 40, 160, 40, 40, 160])
        _build_pdf(pdf_path, [t])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Price Warehouse")
        df = parser.parse()

        self.assertEqual(len(df), 2)
        extracted = " ".join(df['item_name'])
        self.assertIn('Panadol Normal Price', extracted)
        self.assertIn('Cataflam Normal Price', extracted)

        diag = _get_diagnostics(df)
        self.assertEqual(diag.accepted_rows, 2)
        self.assertGreaterEqual(diag.rejected_rows, 3)
        self.assertEqual(diag.status, "partial")
        self.assertTrue(diag.requires_acknowledgment)

    # =========================================================================
    # R3: Cache Validation, Fingerprint Corruption, & Security
    # =========================================================================

    def test_adv_10_cache_invalidation_on_content_tampering(self):
        """Stress: Altering file content on disk immediately invalidates cache and triggers reparse."""
        pdf_path = os.path.join(self.temp_dir, "adv10_tamper.pdf")

        # Initial PDF: 1 product
        data1 = [
            ['Disc', 'Price', 'Item Name'],
            ['10%', '50.00', 'Initial Drug 100mg']
        ]
        t1 = _make_grid_table(data1, [50, 50, 200])
        _build_pdf(pdf_path, [t1])

        # Step 1: Inspect catalog -> populates cache
        res1 = inspect_catalog(pdf_path, refresh=True)
        self.assertEqual(len(res1.dataframe), 1)
        self.assertIn('Initial Drug', res1.dataframe.iloc[0]['item_name'])
        initial_hash = res1.fingerprint.sha256

        # Step 2: Directly validate cached catalog
        verified1 = validate_cached_catalog(res1, pdf_path)
        self.assertIsNotNone(verified1)

        # Step 3: Tamper with file on disk (overwrite with different product data)
        data2 = [
            ['Disc', 'Price', 'Item Name'],
            ['20%', '80.00', 'Tampered Drug 200mg']
        ]
        t2 = _make_grid_table(data2, [50, 50, 200])
        _build_pdf(pdf_path, [t2])

        # Step 4: validate_cached_catalog with stale res1 against tampered file must return None
        verified_stale = validate_cached_catalog(res1, pdf_path)
        self.assertIsNone(verified_stale, "validate_cached_catalog must reject stale cache when file changed!")

        # Step 5: inspect_catalog must reparse and return the new product
        res2 = inspect_catalog(pdf_path, refresh=False)
        self.assertEqual(len(res2.dataframe), 1)
        self.assertIn('Tampered Drug', res2.dataframe.iloc[0]['item_name'])
        self.assertNotEqual(res2.fingerprint.sha256, initial_hash)

    def test_adv_11_cache_timestamp_touch_with_same_content(self):
        """Stress: Touching file timestamp without modifying content must retain valid cache hit."""
        pdf_path = os.path.join(self.temp_dir, "adv11_touch.pdf")

        data = [
            ['Disc', 'Price', 'Item Name'],
            ['10%', '50.00', 'Touch Test Drug']
        ]
        t = _make_grid_table(data, [50, 50, 200])
        _build_pdf(pdf_path, [t])

        res1 = inspect_catalog(pdf_path, refresh=True)
        self.assertIsNotNone(res1)

        # Shift mtime ahead by 1000 seconds without modifying file content
        new_mtime = time.time() + 1000
        os.utime(pdf_path, (new_mtime, new_mtime))

        # Content SHA-256 is unchanged -> validate_cached_catalog must verify successfully
        verified = validate_cached_catalog(res1, pdf_path)
        self.assertIsNotNone(verified, "Timestamp shift with identical SHA256 must remain valid cache hit.")

    def test_adv_12_malformed_and_adversarial_fingerprints_rejected(self):
        """Stress: validate_cached_catalog rejects all malformed/tampered fingerprints."""
        pdf_path = os.path.join(self.temp_dir, "adv12_malformed.pdf")

        data = [
            ['Disc', 'Price', 'Item Name'],
            ['10%', '50.00', 'Panadol Extra 500mg']
        ]
        t = _make_grid_table(data, [50, 50, 200])
        _build_pdf(pdf_path, [t])

        valid_res = inspect_catalog(pdf_path, refresh=True)
        norm_path = os.path.normpath(os.path.abspath(pdf_path))
        valid_fp = valid_res.fingerprint

        adversarial_cases = [
            # 1. Non-existent path in fingerprint
            FileFingerprint(r"C:\fake\non_existent_path.pdf", valid_fp.sha256, valid_fp.parser_revision, valid_fp.library_version),
            # 2. Relative path in fingerprint
            FileFingerprint("adv12_malformed.pdf", valid_fp.sha256, valid_fp.parser_revision, valid_fp.library_version),
            # 3. Path pointing to a different file
            FileFingerprint(os.path.abspath(__file__), valid_fp.sha256, valid_fp.parser_revision, valid_fp.library_version),
            # 4. Truncated SHA-256 (32 chars)
            FileFingerprint(norm_path, "a" * 32, valid_fp.parser_revision, valid_fp.library_version),
            # 5. Non-string SHA-256
            FileFingerprint(norm_path, 12345678, valid_fp.parser_revision, valid_fp.library_version),
            # 6. Stale parser revision
            FileFingerprint(norm_path, valid_fp.sha256, "v1.0.0-legacy", valid_fp.library_version),
            # 7. Missing library version
            FileFingerprint(norm_path, valid_fp.sha256, valid_fp.parser_revision, ""),
            # 8. Empty string path
            FileFingerprint("", valid_fp.sha256, valid_fp.parser_revision, valid_fp.library_version),
        ]

        for idx, bad_fp in enumerate(adversarial_cases):
            with self.subTest(case_idx=idx):
                bad_res = CatalogResult(
                    dataframe=valid_res.dataframe.copy(),
                    diagnostics=valid_res.diagnostics,
                    fingerprint=bad_fp
                )
                self.assertIsNone(
                    validate_cached_catalog(bad_res, pdf_path),
                    f"Adversarial fingerprint case {idx} was not rejected!"
                )

        # Also test non-fingerprint objects
        self.assertIsNone(validate_cached_catalog(None, pdf_path))
        self.assertIsNone(validate_cached_catalog("string_candidate", pdf_path))
        self.assertIsNone(validate_cached_catalog({'fingerprint': 'dict'}, pdf_path))

    def test_adv_13_dataframe_truth_value_and_empty_handling(self):
        """Stress: Ensure no truth-value ambiguity errors occur on multi-row DataFrames."""
        pdf_path = os.path.join(self.temp_dir, "adv13_df_truth.pdf")

        data = [
            ['Disc', 'Price', 'Item Name'],
            ['10%', '50.00', 'Panadol Extra 500mg'],
            ['15%', '35.00', 'Cataflam 50mg'],
        ]
        t = _make_grid_table(data, [50, 50, 200])
        _build_pdf(pdf_path, [t])

        res = inspect_catalog(pdf_path, refresh=True)
        df_multi = res.to_dataframe()

        # Multi-row DataFrame has ambiguous boolean truth value: bool(df_multi) raises ValueError
        with self.assertRaises(ValueError):
            bool(df_multi)

        # validate_cached_catalog must safely evaluate df_multi without triggering ValueError
        verified = validate_cached_catalog(df_multi, pdf_path)
        self.assertIsNotNone(verified)
        self.assertEqual(len(verified.dataframe), 2)

        # Empty DataFrame must return None safely
        empty_df = pd.DataFrame()
        self.assertIsNone(validate_cached_catalog(empty_df, pdf_path))

        # Multi-row DataFrame with corrupt/missing attrs must return None safely
        df_corrupt = df_multi.copy()
        df_corrupt.attrs = {}
        self.assertIsNone(validate_cached_catalog(df_corrupt, pdf_path))

    def test_adv_14_partial_catalog_token_lifecycle_and_tamper(self):
        """Stress: Partial catalog token gating lifecycle, invalidation, and procurement execution."""
        pdf_path = os.path.join(self.temp_dir, "adv14_token_gating.pdf")

        # 1 valid row + 1 rejected row -> partial catalog
        data = [
            ['Disc', 'Price', 'Item Name'],
            ['10%', '50.00', 'Panadol Extra 500mg'],
            ['15%', '', 'Rejected Drug No Price'],
        ]
        t = _make_grid_table(data, [50, 50, 200])
        _build_pdf(pdf_path, [t])

        order_path = os.path.join(self.temp_dir, "adv14_order.xlsx")
        _create_order_excel(order_path, ['Panadol Extra 500mg'])
        out_dir = os.path.join(self.temp_dir, "adv14_out")
        os.makedirs(out_dir, exist_ok=True)

        # Step 1: Inspect catalog -> verify status is partial and token is generated
        res = inspect_catalog(pdf_path, refresh=True)
        self.assertEqual(res.diagnostics.status, "partial")
        self.assertTrue(res.diagnostics.requires_acknowledgment)
        token = res.acknowledgment_token
        self.assertTrue(bool(token))

        # Step 2: Pipeline execution with None token must fail
        with self.assertRaises(PipelineExecutionError) as ctx_none:
            run_procurement_pipeline(
                order_files=[order_path],
                catalog_files=[pdf_path],
                output_dir=out_dir,
                accepted_partial_tokens=None
            )
        self.assertIn("Explicit acknowledgment is required", str(ctx_none.exception))

        # Step 3: Pipeline execution with incorrect token must fail
        with self.assertRaises(PipelineExecutionError) as ctx_wrong:
            run_procurement_pipeline(
                order_files=[order_path],
                catalog_files=[pdf_path],
                output_dir=out_dir,
                accepted_partial_tokens=["invalid_adversarial_token_9999"]
            )
        self.assertIn("Explicit acknowledgment is required", str(ctx_wrong.exception))

        # Step 4: Pipeline execution with matching valid token must succeed
        res_ok = run_procurement_pipeline(
            order_files=[order_path],
            catalog_files=[pdf_path],
            output_dir=out_dir,
            accepted_partial_tokens=[token]
        )
        self.assertEqual(res_ok['kpis']['total_items'], 1)

        # Step 5: If the file is modified on disk, prior acknowledgment token must be invalidated
        # Append another product to pdf
        data_updated = [
            ['Disc', 'Price', 'Item Name'],
            ['10%', '50.00', 'Panadol Extra 500mg'],
            ['15%', '', 'Rejected Drug No Price'],
            ['20%', '', 'Another Rejected Drug'],
        ]
        t_up = _make_grid_table(data_updated, [50, 50, 200])
        _build_pdf(pdf_path, [t_up])

        # Step 6: Calling pipeline with the OLD token must now FAIL because file changed
        with self.assertRaises(PipelineExecutionError) as ctx_stale:
            run_procurement_pipeline(
                order_files=[order_path],
                catalog_files=[pdf_path],
                output_dir=out_dir,
                accepted_partial_tokens=[token]
            )
        self.assertIn("Explicit acknowledgment is required", str(ctx_stale.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
