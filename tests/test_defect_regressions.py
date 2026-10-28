# -*- coding: utf-8 -*-
"""
Defect Regression Test Suite (Acceptance Criteria Cases 1-16)
File: tests/test_defect_regressions.py

Authoritative independent regression tests demonstrating existing defects before fixes
and verifying production paths using real generated PDFs via ReportLab.

Test Cases:
- Case 1: Two structural tables on one page -> 8 expected products returned, correct page-wide diagnostics.
- Case 2: Mixed structural and legacy tables -> neither table skipped nor processed twice.
- Case 3: Headerless continuation -> 8 expected products across two pages; all 8 returned.
- Case 4: Headerless continuation with one data row -> row survives extraction.
- Case 5: Headerless first page & single-row table -> table with no headers anywhere and only 1 product row extracts cleanly without requiring a previous page layout.
- Case 6: Actual repeated headers -> header text not parsed as product.
- Case 7: Sparse final page -> empty groups remain empty without shifting fields.
- Case 8: Missing field -> retain column alignment and record rejection accurately.
- Case 9: Ambiguous content & skipped products -> preserve unresolved product-like cells and locations; produce partial status requiring acknowledgment (unverified only when completeness is indeterminate).
- Case 10: Unversioned cache -> parser executes; stale cached rows do not enter procurement.
- Case 11: Malformed/relative-path fingerprint -> reparse triggered.
- Case 12: Changed file at same path -> cache and prior acknowledgment invalidated.
- Case 13: Valid cache hit -> unnecessary parsing avoided, diagnostics preserved.
- Case 14: Partial-import gating -> exercised with no token, matching token, and outdated token.
- Case 15: Diagnostics assert reconciliation and completeness status, not just item count.
- Case 16: Real PDF regression with three side-by-side groups where only one group has a header in row 0 (tested across all 3 header positions).
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
    METADATA_KEY,
    PARSER_REVISION,
)
from src.controller import (
    inspect_catalog,
    global_catalog_cache,
    CatalogCache,
)
from src.pipeline import (
    run_procurement_pipeline,
    PipelineExecutionError,
)


def _build_pdf(file_path: str, flowables: list, pagesize=letter, margins=20):
    """Helper to generate real PDF file using ReportLab."""
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
    """Helper to create a Table with full black grid lines recognizable by find_tables."""
    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    return t


def _create_dummy_order_excel(file_path: str, items: list[str]):
    """Helper to generate a minimal valid purchase order Excel file."""
    rows = [{'item_name': name, 'quantity': 10} for name in items]
    df = pd.DataFrame(rows)
    df.to_excel(file_path, index=False)


class TestDefectRegressionsCases1To16(unittest.TestCase):
    """Authoritative regression test suite covering Acceptance Criteria Cases 1-16."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="defect_reg_")
        global_catalog_cache.clear()

    def tearDown(self):
        global_catalog_cache.clear()
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ------------------------------------------------------------------------
    # Case 1: Two structural tables on one page -> 8 expected products returned,
    # correct page-wide diagnostics.
    # ------------------------------------------------------------------------
    def test_case_01_two_structural_tables_on_one_page(self):
        """Case 1: Both structural tables on a single page must be parsed, yielding 8 products."""
        pdf_path = os.path.join(self.temp_dir, "case01_two_tables.pdf")

        # Table 1 (top): 2 groups x 2 data rows = 4 products
        data1 = [
            ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name'],
            ['10%', '50.00', 'Panadol Extra 500mg', '15%', '35.00', 'Cataflam 50mg'],
            ['5%', '20.00', 'Congestal Tablets', '20%', '90.00', 'Augmentin 1g'],
        ]
        t1 = _make_grid_table(data1, [45, 45, 180, 45, 45, 180])

        # Table 2 (bottom): 2 groups x 2 data rows = 4 products
        data2 = [
            ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name'],
            ['8%', '45.00', 'Brufen 400mg', '12%', '60.00', 'Voltaren 100mg'],
            ['7%', '25.00', 'Antinal Capsules', '18%', '75.00', 'Flagyl 500mg'],
        ]
        t2 = _make_grid_table(data2, [45, 45, 180, 45, 45, 180])

        _build_pdf(pdf_path, [t1, Spacer(1, 25), t2])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Case01Warehouse")
        df = parser.parse()

        # Both tables must be processed -> exactly 8 products returned
        self.assertEqual(
            len(df), 8,
            f"Expected exactly 8 products from two structural tables on one page, but got {len(df)}."
        )

        extracted_names = " ".join(df['item_name'].tolist())
        for expected in ["Panadol", "Cataflam", "Congestal", "Augmentin", "Brufen", "Voltaren", "Antinal", "Flagyl"]:
            self.assertIn(expected, extracted_names, f"Expected product {expected} missing from extraction.")

        # Page diagnostics must reflect all candidate and accepted rows across both tables
        res = CatalogResult.from_dataframe(df)
        self.assertIsNotNone(res)
        self.assertGreaterEqual(len(res.diagnostics.pages), 1)
        p1 = res.diagnostics.pages[0]
        self.assertEqual(
            p1.accepted_rows, 8,
            f"Expected page 1 diagnostics to report 8 accepted rows, got {p1.accepted_rows}."
        )

    # ------------------------------------------------------------------------
    # Case 2: Mixed structural and legacy tables -> neither table skipped nor processed twice.
    # ------------------------------------------------------------------------
    def test_case_02_mixed_structural_and_legacy_tables(self):
        """Case 2: Neither structural nor legacy table should be skipped or duplicate-processed."""
        pdf_path = os.path.join(self.temp_dir, "case02_mixed_tables.pdf")

        # Table 1: Structural multi-group table (2 groups x 2 data rows = 4 products)
        data1 = [
            ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name'],
            ['10%', '50.00', 'Panadol Extra 500mg', '15%', '35.00', 'Cataflam 50mg'],
            ['5%', '20.00', 'Congestal Tablets', '20%', '90.00', 'Augmentin 1g'],
        ]
        t1 = _make_grid_table(data1, [45, 45, 180, 45, 45, 180])

        # Table 2: Legacy single-group table (1 group x 3 data rows = 3 products)
        data2 = [
            ['Disc', 'Price', 'Item Name'],
            ['8%', '45.00', 'Brufen 400mg'],
            ['12%', '60.00', 'Voltaren 100mg'],
            ['7%', '25.00', 'Antinal Capsules'],
        ]
        t2 = _make_grid_table(data2, [50, 50, 220])

        _build_pdf(pdf_path, [t1, Spacer(1, 25), t2])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Case02Warehouse")
        df = parser.parse()

        # Both tables must be extracted: 4 structural + 3 legacy = 7 total products
        self.assertEqual(
            len(df), 7,
            f"Expected 7 products from mixed structural and legacy tables, got {len(df)}."
        )

        names = df['item_name'].tolist()
        # Verify no item processed twice
        self.assertEqual(len(names), len(set(names)), "Detected duplicate processed products.")

    # ------------------------------------------------------------------------
    # Case 3: Headerless continuation -> 8 expected products across two pages; all 8 returned.
    # ------------------------------------------------------------------------
    def test_case_03_headerless_continuation(self):
        """Case 3: Headerless continuation page must retain row 0 and extract all 8 products."""
        pdf_path = os.path.join(self.temp_dir, "case03_continuation.pdf")

        # Page 1: Header row + 2 data rows (4 products)
        data1 = [
            ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name'],
            ['10%', '50.00', 'Panadol Extra 500mg', '15%', '35.00', 'Cataflam 50mg'],
            ['5%', '20.00', 'Congestal Tablets', '20%', '90.00', 'Augmentin 1g'],
        ]
        t1 = _make_grid_table(data1, [45, 45, 180, 45, 45, 180])

        # Page 2: Headerless continuation table + 2 data rows (4 products, starting directly at row 0)
        data2 = [
            ['8%', '45.00', 'Brufen 400mg', '12%', '60.00', 'Voltaren 100mg'],
            ['7%', '25.00', 'Antinal Capsules', '18%', '75.00', 'Flagyl 500mg'],
        ]
        t2 = _make_grid_table(data2, [45, 45, 180, 45, 45, 180])

        _build_pdf(pdf_path, [t1, PageBreak(), t2])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Case03Warehouse")
        df = parser.parse()

        self.assertEqual(
            len(df), 8,
            f"Expected 8 products across headered page 1 and headerless continuation page 2, got {len(df)}."
        )
        extracted_names = " ".join(df['item_name'].tolist())
        self.assertIn("Brufen", extracted_names, "Row 0 item Brufen 400mg on continuation page was lost.")
        self.assertIn("Voltaren", extracted_names, "Row 0 item Voltaren 100mg on continuation page was lost.")

    # ------------------------------------------------------------------------
    # Case 4: Headerless continuation with one data row -> row survives extraction.
    # ------------------------------------------------------------------------
    def test_case_04_headerless_continuation_single_data_row(self):
        """Case 4: Single data row on headerless continuation page must survive extraction."""
        pdf_path = os.path.join(self.temp_dir, "case04_continuation_one_row.pdf")

        # Page 1: 4 products
        data1 = [
            ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name'],
            ['10%', '50.00', 'Panadol Extra 500mg', '15%', '35.00', 'Cataflam 50mg'],
            ['5%', '20.00', 'Congestal Tablets', '20%', '90.00', 'Augmentin 1g'],
        ]
        t1 = _make_grid_table(data1, [45, 45, 180, 45, 45, 180])

        # Page 2: Headerless table with exactly 1 data row (2 products)
        data2 = [
            ['8%', '45.00', 'Brufen 400mg', '12%', '60.00', 'Voltaren 100mg'],
        ]
        t2 = _make_grid_table(data2, [45, 45, 180, 45, 45, 180])

        _build_pdf(pdf_path, [t1, PageBreak(), t2])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Case04Warehouse")
        df = parser.parse()

        self.assertEqual(
            len(df), 6,
            f"Expected 6 products (4 on page 1, 2 on single-row continuation page 2), got {len(df)}."
        )
        extracted_names = " ".join(df['item_name'].tolist())
        self.assertIn("Brufen", extracted_names, "Single continuation row Brufen was lost.")
        self.assertIn("Voltaren", extracted_names, "Single continuation row Voltaren was lost.")

    # ------------------------------------------------------------------------
    # Case 5: Headerless first page & single-row table -> table with no headers anywhere
    # and only 1 product row extracts cleanly without requiring a previous page layout.
    # ------------------------------------------------------------------------
    def test_case_05_headerless_first_page_single_row_table(self):
        """Case 5: Standalone single-row table with no headers must extract cleanly without prior layout."""
        pdf_path = os.path.join(self.temp_dir, "case05_single_row.pdf")

        # No headers anywhere, only 1 single product row
        data = [
            ['10%', '50.00', 'Panadol Extra 500mg'],
        ]
        t = _make_grid_table(data, [60, 60, 220])
        _build_pdf(pdf_path, [t])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Case05Warehouse")
        df = parser.parse()

        self.assertEqual(
            len(df), 1,
            f"Expected exactly 1 product from standalone headerless single-row table, got {len(df)}."
        )
        self.assertIn("Panadol", df.iloc[0]['item_name'])
        self.assertAlmostEqual(float(df.iloc[0]['base_price']), 50.0)
        self.assertAlmostEqual(float(df.iloc[0]['discount_rate']), 0.10)

    # ------------------------------------------------------------------------
    # Case 6: Actual repeated headers -> header text not parsed as product.
    # ------------------------------------------------------------------------
    def test_case_06_actual_repeated_headers(self):
        """Case 6: Repeated headers across pages must not be parsed as product rows."""
        pdf_path = os.path.join(self.temp_dir, "case06_repeated_headers.pdf")

        # Page 1: Header + 2 data rows
        data1 = [
            ['Disc', 'Price', 'Item Name'],
            ['10%', '50.00', 'Panadol Extra 500mg'],
            ['15%', '35.00', 'Cataflam 50mg'],
        ]
        t1 = _make_grid_table(data1, [60, 60, 220])

        # Page 2: Repeated header + 2 data rows
        data2 = [
            ['Disc', 'Price', 'Item Name'],
            ['8%', '45.00', 'Brufen 400mg'],
            ['12%', '60.00', 'Voltaren 100mg'],
        ]
        t2 = _make_grid_table(data2, [60, 60, 220])

        _build_pdf(pdf_path, [t1, PageBreak(), t2])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Case06Warehouse")
        df = parser.parse()

        self.assertEqual(len(df), 4, f"Expected 4 products across 2 pages with repeated headers, got {len(df)}.")
        for name in df['item_name']:
            self.assertNotIn("Item Name", name)
            self.assertNotIn("Disc", name)
            self.assertNotIn("Price", name)

    # ------------------------------------------------------------------------
    # Case 7: Sparse final page -> empty groups remain empty without shifting fields.
    # ------------------------------------------------------------------------
    def test_case_07_sparse_final_page_empty_groups(self):
        """Case 7: Sparse final page with empty groups must not shift columns or misalign fields."""
        pdf_path = os.path.join(self.temp_dir, "case07_sparse_final_page.pdf")

        # Page 1: 3 full groups with headers + 2 rows = 6 items
        data1 = [
            ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name'],
            ['10%', '50.00', 'Panadol Extra 500mg', '15%', '35.00', 'Cataflam 50mg', '20%', '90.00', 'Augmentin 1g'],
            ['5%', '20.00', 'Congestal Tablets', '12%', '40.00', 'Brufen 400mg', '18%', '75.00', 'Flagyl 500mg'],
        ]
        t1 = _make_grid_table(data1, [35, 35, 110, 35, 35, 110, 35, 35, 110])

        # Page 2: Sparse final page. Group 0 has 2 rows. Group 1 and Group 2 are completely empty cells ("").
        data2 = [
            ['Disc', 'Price', 'Item Name', '', '', '', '', '', ''],
            ['8%', '25.00', 'Antinal Capsules', '', '', '', '', '', ''],
            ['14%', '60.00', 'Voltaren 100mg', '', '', '', '', '', ''],
        ]
        t2 = _make_grid_table(data2, [35, 35, 110, 35, 35, 110, 35, 35, 110])

        _build_pdf(pdf_path, [t1, PageBreak(), t2])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Case07Warehouse")
        df = parser.parse()

        # Page 1 (6) + Page 2 (2) = 8 products total
        self.assertEqual(len(df), 8, f"Expected 8 products, got {len(df)}.")

        # Verify Antinal and Voltaren fields are not shifted or corrupted
        antinal_rows = df[df['item_name'].str.contains("Antinal", na=False)]
        self.assertEqual(len(antinal_rows), 1)
        self.assertAlmostEqual(float(antinal_rows.iloc[0]['base_price']), 25.0)
        self.assertAlmostEqual(float(antinal_rows.iloc[0]['discount_rate']), 0.08)

        voltaren_rows = df[df['item_name'].str.contains("Voltaren", na=False)]
        self.assertEqual(len(voltaren_rows), 1)
        self.assertAlmostEqual(float(voltaren_rows.iloc[0]['base_price']), 60.0)
        self.assertAlmostEqual(float(voltaren_rows.iloc[0]['discount_rate']), 0.14)

    # ------------------------------------------------------------------------
    # Case 8: Missing field -> retain column alignment and record rejection accurately.
    # ------------------------------------------------------------------------
    def test_case_08_missing_field_alignment_and_rejection(self):
        """Case 8: Missing field must retain alignment for other rows and record rejection in diagnostics."""
        pdf_path = os.path.join(self.temp_dir, "case08_missing_field.pdf")

        # Row 1: Valid
        # Row 2: Missing price ("")
        # Row 3: Valid
        data = [
            ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name'],
            ['10%', '50.00', 'Panadol Extra 500mg', '15%', '35.00', 'Cataflam 50mg'],
            ['5%', '', 'Congestal Tablets', '20%', '90.00', 'Augmentin 1g'],
            ['8%', '45.00', 'Brufen 400mg', '12%', '60.00', 'Voltaren 100mg'],
        ]
        t = _make_grid_table(data, [45, 45, 180, 45, 45, 180])
        _build_pdf(pdf_path, [t])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Case08Warehouse")
        df = parser.parse()

        # 6 candidate rows, 1 rejected (Congestal missing price) -> 5 accepted
        self.assertEqual(len(df), 5, f"Expected 5 accepted products, got {len(df)}.")

        res = CatalogResult.from_dataframe(df)
        self.assertIsNotNone(res)
        self.assertEqual(res.diagnostics.candidate_rows, 6)
        self.assertEqual(res.diagnostics.accepted_rows, 5)
        self.assertEqual(res.diagnostics.rejected_rows, 1)

        # Brufen in Row 3 must retain exact alignment and valid values
        brufen = df[df['item_name'].str.contains("Brufen", na=False)].iloc[0]
        self.assertAlmostEqual(float(brufen['base_price']), 45.0)
        self.assertAlmostEqual(float(brufen['discount_rate']), 0.08)

    # ------------------------------------------------------------------------
    # Case 9: Ambiguous content & skipped products -> preserve unresolved product-like
    # cells and locations; produce partial status requiring acknowledgment
    # (unverified only when completeness is indeterminate).
    # ------------------------------------------------------------------------
    def test_case_09_ambiguous_content_skipped_products_partial_status(self):
        """Case 9: Skipped products or unprocessed tables must produce partial status requiring acknowledgment."""
        pdf_path = os.path.join(self.temp_dir, "case09_skipped_table.pdf")

        # Two tables on one page:
        # Table 1: 4 valid products
        data1 = [
            ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name'],
            ['10%', '50.00', 'Panadol Extra 500mg', '15%', '35.00', 'Cataflam 50mg'],
            ['5%', '20.00', 'Congestal Tablets', '20%', '90.00', 'Augmentin 1g'],
        ]
        t1 = _make_grid_table(data1, [45, 45, 180, 45, 45, 180])

        # Table 2: 4 products
        data2 = [
            ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name'],
            ['8%', '45.00', 'Brufen 400mg', '12%', '60.00', 'Voltaren 100mg'],
            ['7%', '25.00', 'Antinal Capsules', '18%', '75.00', 'Flagyl 500mg'],
        ]
        t2 = _make_grid_table(data2, [45, 45, 180, 45, 45, 180])

        _build_pdf(pdf_path, [t1, Spacer(1, 25), t2])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Case09Warehouse")
        df = parser.parse()
        res = CatalogResult.from_dataframe(df)
        self.assertIsNotNone(res)

        # If any products were skipped, the catalog MUST NOT be declared 'complete'
        if len(df) < 8:
            self.assertNotEqual(
                res.diagnostics.status, "complete",
                "Catalog with skipped products/unprocessed table was falsely declared 'complete'!"
            )
            self.assertEqual(
                res.diagnostics.status, "partial",
                "Catalog with skipped products must have 'partial' status requiring acknowledgment."
            )
            self.assertTrue(
                res.diagnostics.requires_acknowledgment,
                "Partial catalog must require acknowledgment."
            )
        else:
            # If all 8 products were extracted, completeness must be validated with all 8 accepted
            self.assertEqual(len(df), 8)

    # ------------------------------------------------------------------------
    # Case 10: Unversioned cache -> parser executes; stale cached rows do not enter procurement.
    # ------------------------------------------------------------------------
    def test_case_10_unversioned_cache_rejection(self):
        """Case 10: Cache entry lacking version fingerprint metadata must be rejected and fresh file parsed."""
        pdf_path = os.path.join(self.temp_dir, "case10_fresh_catalog.pdf")

        # Real PDF on disk contains genuine drug
        data = [
            ['Disc', 'Price', 'Item Name'],
            ['10%', '50.00', 'Panadol Extra 500mg'],
        ]
        t = _make_grid_table(data, [60, 60, 220])
        _build_pdf(pdf_path, [t])

        # Stale unversioned cache DataFrame (no attrs['catalog_import'] metadata)
        stale_df = pd.DataFrame([{
            'warehouse_name': 'Case10Warehouse',
            'item_name': 'STALE FAKE MEDICINE 999MG',
            'normalized_name': 'stale fake medicine 999mg',
            'dosage': '999mg',
            'unit_size': '1',
            'base_price': 999.0,
            'discount_rate': 0.99,
            'stock_status': 'available'
        }])

        # Put unversioned dataframe into cache
        norm_pdf = os.path.normpath(os.path.abspath(pdf_path))
        global_catalog_cache.set(norm_pdf, stale_df)

        # Inspect catalog without refresh
        res = inspect_catalog(pdf_path, refresh=False)

        # The stale unversioned cached row MUST NOT be returned!
        extracted_names = res.dataframe['item_name'].tolist()
        self.assertNotIn(
            "STALE FAKE MEDICINE 999MG", extracted_names,
            "Unversioned stale cache was accepted without running parser!"
        )
        self.assertTrue(
            any("Panadol" in name for name in extracted_names),
            "Parser was not executed to parse fresh PDF on disk."
        )

    # ------------------------------------------------------------------------
    # Case 11: Malformed/relative-path fingerprint -> reparse triggered.
    # ------------------------------------------------------------------------
    def test_case_11_malformed_relative_path_fingerprint(self):
        """Case 11: Cached entry with relative-path or malformed fingerprint must trigger reparse."""
        pdf_path = os.path.join(self.temp_dir, "case11_relative_fp.pdf")

        # Real PDF on disk
        data = [
            ['Disc', 'Price', 'Item Name'],
            ['10%', '50.00', 'Panadol Extra 500mg'],
        ]
        t = _make_grid_table(data, [60, 60, 220])
        _build_pdf(pdf_path, [t])

        # Stale DataFrame with relative-path fingerprint
        stale_df = pd.DataFrame([{
            'warehouse_name': 'Case11Warehouse',
            'item_name': 'STALE RELATIVE FP ITEM',
            'normalized_name': 'stale relative fp item',
            'dosage': '100mg',
            'unit_size': '1',
            'base_price': 100.0,
            'discount_rate': 0.10,
            'stock_status': 'available'
        }])
        fp_relative = FileFingerprint(path="relative/path/case11.pdf", sha256="0" * 64)
        diag = ImportDiagnostics(unique_records=1, accepted_rows=1)
        stale_res = CatalogResult(dataframe=stale_df, diagnostics=diag, fingerprint=fp_relative)
        stale_df_with_meta = stale_res.to_dataframe()

        norm_pdf = os.path.normpath(os.path.abspath(pdf_path))
        cache_dict = {norm_pdf: stale_df_with_meta}

        order_path = os.path.join(self.temp_dir, "case11_order.xlsx")
        _create_dummy_order_excel(order_path, ["Panadol Extra 500mg"])

        out_dir = os.path.join(self.temp_dir, "case11_out")
        os.makedirs(out_dir, exist_ok=True)

        wh_name = os.path.splitext(os.path.basename(pdf_path))[0]
        stale_df['warehouse_name'] = wh_name

        res = run_procurement_pipeline(
            order_files=[order_path],
            catalog_files=[pdf_path],
            output_dir=out_dir,
            catalog_cache=cache_dict
        )

        # Reparse must have been triggered: fresh Panadol extracted and matched with order!
        self.assertEqual(
            res['kpis']['matched_items'], 1,
            "Pipeline accepted stale relative-path fingerprint instead of reparsing fresh PDF!"
        )

    # ------------------------------------------------------------------------
    # Case 12: Changed file at same path -> cache and prior acknowledgment invalidated.
    # ------------------------------------------------------------------------
    def test_case_12_changed_file_invalidates_cache_and_acknowledgment(self):
        """Case 12: Content changes at same path must invalidate cache and prior acknowledgment token."""
        pdf_path = os.path.join(self.temp_dir, "case12_changing_catalog.pdf")

        # Version 1: Panadol 500mg
        data1 = [
            ['Disc', 'Price', 'Item Name'],
            ['10%', '50.00', 'Panadol Extra 500mg'],
        ]
        t1 = _make_grid_table(data1, [60, 60, 220])
        _build_pdf(pdf_path, [t1])

        res1 = inspect_catalog(pdf_path, refresh=True)
        token1 = res1.acknowledgment_token
        self.assertIn("Panadol", res1.dataframe.iloc[0]['item_name'])

        # Sleep briefly to ensure filesystem timestamp update
        time.sleep(0.05)

        # Version 2: Cataflam 50mg at SAME path
        data2 = [
            ['Disc', 'Price', 'Item Name'],
            ['15%', '35.00', 'Cataflam 50mg'],
        ]
        t2 = _make_grid_table(data2, [60, 60, 220])
        _build_pdf(pdf_path, [t2])

        # Inspect WITHOUT refresh=True
        res2 = inspect_catalog(pdf_path, refresh=False)
        token2 = res2.acknowledgment_token

        # Cache must have been invalidated due to file content change
        self.assertIn("Cataflam", res2.dataframe.iloc[0]['item_name'], "Cache was not invalidated on file change!")
        self.assertNotEqual(token1, token2, "Acknowledgment token did not change when file changed!")

    # ------------------------------------------------------------------------
    # Case 13: Valid cache hit -> unnecessary parsing avoided, diagnostics preserved.
    # ------------------------------------------------------------------------
    def test_case_13_valid_cache_hit_preserves_diagnostics(self):
        """Case 13: Valid cache hit must avoid redundant parsing and preserve diagnostics exactly."""
        pdf_path = os.path.join(self.temp_dir, "case13_cache_hit.pdf")

        data = [
            ['Disc', 'Price', 'Item Name'],
            ['10%', '50.00', 'Panadol Extra 500mg'],
            ['15%', '35.00', 'Cataflam 50mg'],
        ]
        t = _make_grid_table(data, [60, 60, 220])
        _build_pdf(pdf_path, [t])

        # First inspection populates cache
        res1 = inspect_catalog(pdf_path, refresh=True)
        self.assertEqual(len(res1.dataframe), 2)
        token1 = res1.acknowledgment_token

        # Second inspection should hit cache cleanly
        res2 = inspect_catalog(pdf_path, refresh=False)
        self.assertEqual(len(res2.dataframe), 2)
        self.assertEqual(res2.acknowledgment_token, token1)
        self.assertEqual(res2.diagnostics.accepted_rows, res1.diagnostics.accepted_rows)
        self.assertEqual(res2.diagnostics.status, res1.diagnostics.status)

    # ------------------------------------------------------------------------
    # Case 14: Partial-import gating -> exercised with no token, matching token,
    # and outdated token.
    # ------------------------------------------------------------------------
    def test_case_14_partial_import_gating(self):
        """Case 14: Partial import gating must require explicit matching token and reject missing/outdated tokens."""
        pdf_path = os.path.join(self.temp_dir, "case14_partial.pdf")

        # Multi-group table with 1 rejected row (missing price) -> produces 'partial' status
        data = [
            ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name'],
            ['10%', '50.00', 'Panadol Extra 500mg', '15%', '35.00', 'Cataflam 50mg'],
            ['5%', '', 'Congestal Tablets', '20%', '90.00', 'Augmentin 1g'],
        ]
        t = _make_grid_table(data, [45, 45, 180, 45, 45, 180])
        _build_pdf(pdf_path, [t])

        order_path = os.path.join(self.temp_dir, "case14_order.xlsx")
        _create_dummy_order_excel(order_path, ["Panadol Extra 500mg"])

        res = inspect_catalog(pdf_path, refresh=True)
        self.assertEqual(res.diagnostics.status, "partial")
        self.assertTrue(res.diagnostics.requires_acknowledgment)
        valid_token = res.acknowledgment_token

        out_dir = os.path.join(self.temp_dir, "case14_out")
        os.makedirs(out_dir, exist_ok=True)

        # 1. No token -> must raise PipelineExecutionError
        with self.assertRaises(PipelineExecutionError) as ctx_none:
            run_procurement_pipeline(
                order_files=[order_path],
                catalog_files=[pdf_path],
                output_dir=out_dir,
                accepted_partial_tokens=None
            )
        self.assertIn("Explicit acknowledgment is required", str(ctx_none.exception))

        # 2. Outdated / invalid token -> must raise PipelineExecutionError
        with self.assertRaises(PipelineExecutionError) as ctx_outdated:
            run_procurement_pipeline(
                order_files=[order_path],
                catalog_files=[pdf_path],
                output_dir=out_dir,
                accepted_partial_tokens=["outdated_fake_token_12345"]
            )
        self.assertIn("Explicit acknowledgment is required", str(ctx_outdated.exception))

        # 3. Matching valid token -> must succeed
        res_ok = run_procurement_pipeline(
            order_files=[order_path],
            catalog_files=[pdf_path],
            output_dir=out_dir,
            accepted_partial_tokens=[valid_token]
        )
        self.assertEqual(res_ok['kpis']['total_items'], 1)

    # ------------------------------------------------------------------------
    # Case 15: Diagnostics assert reconciliation and completeness status, not just item count.
    # ------------------------------------------------------------------------
    def test_case_15_diagnostics_reconciliation_and_completeness(self):
        """Case 15: Diagnostics must enforce candidate_rows == accepted + rejected + unprocessed."""
        pdf_path = os.path.join(self.temp_dir, "case15_reconciliation.pdf")

        # Multi-group table with 1 rejected row
        data = [
            ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name'],
            ['10%', '50.00', 'Panadol Extra 500mg', '15%', '35.00', 'Cataflam 50mg'],
            ['5%', '', 'Congestal Tablets', '20%', '90.00', 'Augmentin 1g'],
        ]
        t = _make_grid_table(data, [45, 45, 180, 45, 45, 180])
        _build_pdf(pdf_path, [t])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Case15Warehouse")
        df = parser.parse()
        res = CatalogResult.from_dataframe(df)
        self.assertIsNotNone(res)

        diag = res.diagnostics
        # Reconciliation invariant
        total_accounted = diag.accepted_rows + diag.rejected_rows + diag.unprocessed_rows
        self.assertEqual(
            diag.candidate_rows, total_accounted,
            f"Candidate rows ({diag.candidate_rows}) != accepted + rejected + unprocessed ({total_accounted})."
        )
        # Completeness status check
        self.assertEqual(diag.status, "partial")
        self.assertTrue(diag.requires_acknowledgment)

    # ------------------------------------------------------------------------
    # Case 16: Real PDF regression with three side-by-side groups where only one group
    # has a header in row 0 (tested across all 3 header positions).
    # ------------------------------------------------------------------------
    def test_case_16_three_groups_single_header_all_positions(self):
        """Case 16: Three side-by-side groups where only one group has header in row 0 across all 3 positions."""
        hdr = ['Disc', 'Price', 'Item Name']
        g0_prod = ['10%', '50.00', 'Panadol Extra 500mg']
        g1_prod = ['15%', '35.00', 'Cataflam 50mg']
        g2_prod = ['20%', '90.00', 'Augmentin 1g']

        row1 = ['10%', '50.00', 'Panadol Extra 500mg', '12%', '40.00', 'Brufen 400mg', '18%', '75.00', 'Flagyl 500mg']
        row2 = ['5%', '20.00', 'Congestal Tablets', '8%', '25.00', 'Antinal Capsules', '14%', '60.00', 'Voltaren 100mg']

        for pos in [0, 1, 2]:
            with self.subTest(header_position=pos):
                pdf_path = os.path.join(self.temp_dir, f"case16_pos{pos}.pdf")

                if pos == 0:
                    row0 = hdr + g1_prod + g2_prod
                elif pos == 1:
                    row0 = g0_prod + hdr + g2_prod
                else:
                    row0 = g0_prod + g1_prod + hdr

                data = [row0, row1, row2]
                t = _make_grid_table(data, [35, 35, 110, 35, 35, 110, 35, 35, 110])
                _build_pdf(pdf_path, [t], margins=15)

                parser = PDFCatalogParser(pdf_path, warehouse_name=f"Case16Pos{pos}Warehouse")
                df = parser.parse()

                # Row 0 has 2 products + Row 1 has 3 products + Row 2 has 3 products = 8 products total
                self.assertEqual(
                    len(df), 8,
                    f"Position {pos}: Expected 8 products, but got {len(df)}. "
                    f"Row 0 product data in non-header groups must not be discarded!"
                )
                # Verify header text was not parsed as product
                for name in df['item_name']:
                    self.assertNotIn("Item Name", name)

    # ------------------------------------------------------------------------
    # Case 17: Changed column roles between tables on same page
    # (Discount | Price | Name -> Price | Discount | Name)
    # ------------------------------------------------------------------------
    def test_case_17_changed_column_roles_same_page(self):
        """Case 17: Changing column order between tables on same page must not corrupt prices and discounts."""
        pdf_path = os.path.join(self.temp_dir, "case17_swapped_roles_same_page.pdf")

        # Table 1: Disc | Price | Name (2 groups x 1 product row = 2 products)
        data1 = [
            ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name'],
            ['10%', '100.00', 'Panadol Extra 500mg', '15%', '80.00', 'Cataflam 50mg'],
        ]
        t1 = _make_grid_table(data1, [45, 45, 180, 45, 45, 180])

        # Table 2: Price | Disc | Name (SWAPPED column order: 2 groups x 1 product row = 2 products)
        data2 = [
            ['Price', 'Disc', 'Item Name', 'Price', 'Disc', 'Item Name'],
            ['50.00', '20%', 'Zyrtec 10mg', '60.00', '30%', 'Claritin 10mg'],
        ]
        t2 = _make_grid_table(data2, [45, 45, 180, 45, 45, 180])

        _build_pdf(pdf_path, [t1, Spacer(1, 25), t2])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Case17Warehouse")
        df = parser.parse()

        self.assertEqual(len(df), 4, f"Expected 4 products across both tables, got {len(df)}")

        # Verify Table 1 products
        panadol = df[df['item_name'].str.contains("Panadol")].iloc[0]
        self.assertAlmostEqual(panadol['base_price'], 100.0, places=2)
        self.assertAlmostEqual(panadol['discount_rate'], 0.10, places=2)

        cataflam = df[df['item_name'].str.contains("Cataflam")].iloc[0]
        self.assertAlmostEqual(cataflam['base_price'], 80.0, places=2)
        self.assertAlmostEqual(cataflam['discount_rate'], 0.15, places=2)

        # Verify Table 2 products with swapped columns (must not be corrupted to price 20/30, discount 50%/60%)
        zyrtec = df[df['item_name'].str.contains("Zyrtec")].iloc[0]
        self.assertAlmostEqual(zyrtec['base_price'], 50.0, places=2, msg="Zyrtec base price corrupted!")
        self.assertAlmostEqual(zyrtec['discount_rate'], 0.20, places=2, msg="Zyrtec discount rate corrupted!")

        claritin = df[df['item_name'].str.contains("Claritin")].iloc[0]
        self.assertAlmostEqual(claritin['base_price'], 60.0, places=2, msg="Claritin base price corrupted!")
        self.assertAlmostEqual(claritin['discount_rate'], 0.30, places=2, msg="Claritin discount rate corrupted!")

    # ------------------------------------------------------------------------
    # Case 18: Changed column roles cross-page
    # (Page 1: Disc | Price | Name, Page 2: Price | Disc | Name)
    # ------------------------------------------------------------------------
    def test_case_18_changed_column_roles_cross_page(self):
        """Case 18: Changing column order across pages must not allow earlier page layout to corrupt subsequent pages."""
        pdf_path = os.path.join(self.temp_dir, "case18_swapped_roles_cross_page.pdf")

        # Page 1: Disc | Price | Name
        data1 = [
            ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name'],
            ['10%', '100.00', 'Panadol Extra 500mg', '15%', '80.00', 'Cataflam 50mg'],
        ]
        t1 = _make_grid_table(data1, [45, 45, 180, 45, 45, 180])

        # Page 2: Price | Disc | Name (SWAPPED column order)
        data2 = [
            ['Price', 'Disc', 'Item Name', 'Price', 'Disc', 'Item Name'],
            ['50.00', '20%', 'Zyrtec 10mg', '60.00', '30%', 'Claritin 10mg'],
        ]
        t2 = _make_grid_table(data2, [45, 45, 180, 45, 45, 180])

        _build_pdf(pdf_path, [t1, PageBreak(), t2])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Case18Warehouse")
        df = parser.parse()

        self.assertEqual(len(df), 4, f"Expected 4 products across both pages, got {len(df)}")

        zyrtec = df[df['item_name'].str.contains("Zyrtec")].iloc[0]
        self.assertAlmostEqual(zyrtec['base_price'], 50.0, places=2, msg="Cross-page Zyrtec base price corrupted!")
        self.assertAlmostEqual(zyrtec['discount_rate'], 0.20, places=2, msg="Cross-page Zyrtec discount rate corrupted!")

        claritin = df[df['item_name'].str.contains("Claritin")].iloc[0]
        self.assertAlmostEqual(claritin['base_price'], 60.0, places=2, msg="Cross-page Claritin base price corrupted!")
        self.assertAlmostEqual(claritin['discount_rate'], 0.30, places=2, msg="Cross-page Claritin discount rate corrupted!")

    # ------------------------------------------------------------------------
    # Case 19: Mixed-header repeated groups with plain numeric discounts (without %)
    # Tested across Left, Middle, Right header positions
    # ------------------------------------------------------------------------
    def test_case_19_mixed_headers_plain_numeric_discounts_all_positions(self):
        """Case 19: Infer missing discount role from compatible header-bearing group when discounts lack % signs."""
        hdr = ['Disc', 'Price', 'Item Name']
        g0_prod = ['10', '50.00', 'Panadol Extra 500mg']
        g1_prod = ['15', '35.00', 'Cataflam 50mg']
        g2_prod = ['20', '90.00', 'Augmentin 1g']

        row1 = ['12', '40.00', 'Brufen 400mg', '18', '75.00', 'Flagyl 500mg', '25', '60.00', 'Voltaren 100mg']

        for pos_name, pos in [("Left", 0), ("Middle", 1), ("Right", 2)]:
            with self.subTest(header_position=pos_name):
                pdf_path = os.path.join(self.temp_dir, f"case19_pos_{pos_name}.pdf")

                if pos == 0:
                    row0 = hdr + g1_prod + g2_prod
                elif pos == 1:
                    row0 = g0_prod + hdr + g2_prod
                else:
                    row0 = g0_prod + g1_prod + hdr

                data = [row0, row1]
                t = _make_grid_table(data, [35, 35, 110, 35, 35, 110, 35, 35, 110])
                _build_pdf(pdf_path, [t], margins=15)

                parser = PDFCatalogParser(pdf_path, warehouse_name=f"Case19_{pos_name}")
                df = parser.parse()

                # Row 0 has 2 products + Row 1 has 3 products = 5 products total
                self.assertEqual(
                    len(df), 5,
                    f"Position {pos_name}: Expected 5 products, but got {len(df)}. "
                    f"Plain numeric discounts without % must not prevent group recognition or reject products!"
                )

                # Diagnostics must report complete and 0 rejected
                res = CatalogResult.from_dataframe(df)
                self.assertEqual(res.diagnostics.status, "complete")
                self.assertEqual(res.diagnostics.rejected_rows, 0)
                self.assertEqual(res.diagnostics.accepted_rows, 5)

                # Spot-check values
                for _, r in df.iterrows():
                    self.assertGreater(r['base_price'], 0.0)
                    self.assertGreater(r['discount_rate'], 0.0)
                    self.assertLessEqual(r['discount_rate'], 0.85)

    # ------------------------------------------------------------------------
    # Case 20: Single Consolidated Popup for Multiple Partial Catalogs
    # ------------------------------------------------------------------------
    def test_case_20_single_consolidated_popup_for_multiple_partial_catalogs(self):
        """Case 20: Verifies that multiple partial catalogs trigger exactly 1 consolidated popup."""
        from unittest.mock import patch, MagicMock
        from app_gui import PharmaProcurementApp, FileItem

        # Build 3 partial catalogs
        pdf_paths = []
        for i in range(1, 4):
            p = os.path.join(self.temp_dir, f"case20_partial_catalog_{i}.pdf")
            data = [
                ['Discount', 'Price', 'Item Name'],
                ['20%', '50.00', f'Panadol Extra {i}'],
                ['??', 'N/A', f'Malformed Product {i}'],  # rejected -> causes partial status
            ]
            t = _make_grid_table(data, [60, 60, 200])
            _build_pdf(p, [t])
            pdf_paths.append(p)

        order_path = os.path.join(self.temp_dir, "case20_order.xlsx")
        order_df = pd.DataFrame({'Item Name': ['Panadol Extra 1'], 'Qty': [10]})
        order_df.to_excel(order_path, index=False)

        # Use a mock instance to invoke _on_run_optimization without headless Tk issues
        app = MagicMock()
        app.file_model = MagicMock()
        app.file_model.validate.return_value = (True, "")
        app.file_model.get_order_files.return_value = [order_path]
        app.file_model.get_catalog_files.return_value = pdf_paths
        app.file_model.get_avg_discounts_files.return_value = []
        app.output_dir_var = MagicMock()
        app.output_dir_var.get.return_value = self.temp_dir
        app.status_label = MagicMock()
        app.progress_bar = MagicMock()
        app.open_report_btn = MagicMock()
        app.open_folder_btn = MagicMock()
        app._update_file_card_badge = MagicMock()

        # Set up 3 catalog FileItems
        file_items = []
        for p in pdf_paths:
            f_item = FileItem(path=p, category="Catalog")
            file_items.append(f_item)
        order_item = FileItem(path=order_path, category="Order")
        file_items.append(order_item)
        app.file_model.files = file_items

        with patch("app_gui.messagebox.askyesno", return_value=True) as mock_askyesno, \
             patch("app_gui.ProcurementEngineBridge") as mock_bridge_cls:
            mock_bridge_inst = MagicMock()
            mock_bridge_cls.return_value = mock_bridge_inst

            # Trigger the procurement method containing the acknowledgment gate
            PharmaProcurementApp._on_run_optimization(app)

            # MUST be called exactly ONCE, not 3 times!
            self.assertEqual(
                mock_askyesno.call_count, 1,
                f"Expected exactly 1 consolidated popup for all partial catalogs, but got {mock_askyesno.call_count}!"
            )

            # The dialog message must mention all 3 catalogs
            dialog_title, dialog_msg = mock_askyesno.call_args[0]
            self.assertIn("Partial Catalog", dialog_title)
            for i in range(1, 4):
                self.assertIn(f"case20_partial_catalog_{i}.pdf", dialog_msg)

            # All 3 catalog FileItems must now have valid acknowledged tokens
            for f_item in file_items[:3]:
                self.assertIsNotNone(f_item.acknowledged_token)

            # The bridge must have been started with all 3 tokens accepted
            call_kwargs = mock_bridge_inst.start.call_args[1]
            accepted_tokens = call_kwargs["accepted_partial_tokens"]
            self.assertEqual(len(accepted_tokens), 3)

        # Subtest: If user clicks 'No' on the single popup, execution halts and bridge is NOT started
        for f_item in file_items[:3]:
            f_item.acknowledged_token = None
        with patch("app_gui.messagebox.askyesno", return_value=False) as mock_askyesno, \
             patch("app_gui.ProcurementEngineBridge") as mock_bridge_cls:
            mock_bridge_inst = MagicMock()
            mock_bridge_cls.return_value = mock_bridge_inst

            PharmaProcurementApp._on_run_optimization(app)

            self.assertEqual(mock_askyesno.call_count, 1)
            mock_bridge_inst.start.assert_not_called()
            for f_item in file_items[:3]:
                self.assertIsNone(f_item.acknowledged_token)


if __name__ == "__main__":
    unittest.main()
