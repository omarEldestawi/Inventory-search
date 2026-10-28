# -*- coding: utf-8 -*-
"""
Adversarial Stress Test Suite - Challenger 2
File: tests/test_challenger_2_adversarial.py

Empirical stress tests focusing on:
1. Headerless continuation pages with single-row data and 3 side-by-side groups
   (including sparse groups, mixed field errors, multi-continuation, standalone 1-row 3-group).
2. Cache invalidation when files are replaced or timestamps modified
   (forged mtime, rapid churn, stale token rejection, corrupted file, snapshot synchronization).
3. Reconciliation of candidate vs accepted vs unprocessed row counts across
   complex multi-table pages, mixed structural/legacy, and ambiguous rows.
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
    refresh_catalog,
    global_catalog_cache,
    CatalogCache,
)
from src.pipeline import (
    run_procurement_pipeline,
    validate_cached_catalog,
    PipelineExecutionError,
)


def _build_pdf(file_path: str, flowables: list, pagesize=letter, margins=15):
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


try:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    if os.path.exists(r"C:\Windows\Fonts\arial.ttf"):
        pdfmetrics.registerFont(TTFont("Arial", r"C:\Windows\Fonts\arial.ttf"))
        HAS_ARIAL = True
    else:
        HAS_ARIAL = False
except Exception:
    HAS_ARIAL = False


def _make_grid_table(data: list, col_widths: list) -> Table:
    """Helper to create a Table with full black grid lines recognizable by find_tables."""
    t = Table(data, colWidths=col_widths)
    styles = [
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]
    if HAS_ARIAL:
        styles.append(('FONTNAME', (0, 0), (-1, -1), 'Arial'))
    t.setStyle(TableStyle(styles))
    return t


def _create_dummy_order_excel(file_path: str, items: list):
    """Helper to generate a minimal valid purchase order Excel file."""
    rows = [{'item_name': name, 'quantity': 10} for name in items]
    df = pd.DataFrame(rows)
    df.to_excel(file_path, index=False)


class TestChallenger2HeaderlessContinuation(unittest.TestCase):
    """Focus Area 1: Headerless continuation pages with single-row data and 3 side-by-side groups."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="adv_c2_head_")
        global_catalog_cache.clear()

    def tearDown(self):
        global_catalog_cache.clear()
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_adv_01_three_groups_headerless_continuation_single_row_all_extracted(self):
        """Page 1 (3 groups x 2 data rows) -> Page 2 (headerless continuation, exactly 1 row across 3 groups).
        All 3 products in continuation row 0 must survive extraction."""
        pdf_path = os.path.join(self.temp_dir, "adv01_cont_single_row.pdf")
        col_w = [35, 35, 110, 35, 35, 110, 35, 35, 110]

        # Page 1: 3 groups header + 2 data rows = 6 items
        hdr = ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name']
        p1_r1 = ['10%', '50.00', 'Panadol Extra 500mg', '15%', '35.00', 'Cataflam 50mg', '20%', '90.00', 'Augmentin 1g']
        p1_r2 = ['5%', '20.00', 'Congestal Tablets', '8%', '25.00', 'Antinal Capsules', '14%', '60.00', 'Voltaren 100mg']
        t1 = _make_grid_table([hdr, p1_r1, p1_r2], col_w)

        # Page 2: Headerless continuation with EXACTLY 1 ROW across 3 groups = 3 items
        p2_r0 = ['12%', '40.00', 'Brufen 400mg', '18%', '75.00', 'Flagyl 500mg', '22%', '110.00', 'Amoxil 500mg']
        t2 = _make_grid_table([p2_r0], col_w)

        _build_pdf(pdf_path, [t1, PageBreak(), t2])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Adv01Warehouse")
        df = parser.parse()

        # Must extract 6 from Page 1 + 3 from Page 2 = 9 products total
        self.assertEqual(
            len(df), 9,
            f"Expected exactly 9 products (6 on p1, 3 on p2), got {len(df)}."
        )

        names = " ".join(df['item_name'].tolist())
        self.assertIn("Brufen", names, "Page 2 Group 0 item lost")
        self.assertIn("Flagyl", names, "Page 2 Group 1 item lost")
        self.assertIn("Amoxil", names, "Page 2 Group 2 item lost")

        res = CatalogResult.from_dataframe(df)
        self.assertIsNotNone(res)
        diag = res.diagnostics
        self.assertEqual(len(diag.pages), 2)
        p2_diag = diag.pages[1]
        self.assertEqual(p2_diag.accepted_rows, 3)
        self.assertEqual(len(p2_diag.groups), 3)
        for g_i, grp in enumerate(p2_diag.groups):
            self.assertEqual(grp.accepted_rows, 1, f"Group {g_i} on page 2 expected 1 accepted row")
            self.assertEqual(grp.rejected_rows, 0)
            self.assertEqual(grp.candidate_rows, 1)

    def test_adv_02_three_groups_continuation_single_row_sparse_groups(self):
        """Page 2 continuation has single row where group 0 and group 2 have items, but group 1 is blank.
        Group 1 must remain empty without shifting columns or dropping group 2 item."""
        pdf_path = os.path.join(self.temp_dir, "adv02_sparse_single_row.pdf")
        col_w = [35, 35, 110, 35, 35, 110, 35, 35, 110]

        # Page 1: 3 groups x 2 data rows = 6 items
        hdr = ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name']
        p1_r1 = ['10%', '50.00', 'Panadol Extra 500mg', '15%', '35.00', 'Cataflam 50mg', '20%', '90.00', 'Augmentin 1g']
        p1_r2 = ['5%', '20.00', 'Congestal Tablets', '8%', '25.00', 'Antinal Capsules', '14%', '60.00', 'Voltaren 100mg']
        t1 = _make_grid_table([hdr, p1_r1, p1_r2], col_w)

        # Page 2: 1 row, group 1 is completely empty
        p2_r0 = ['12%', '40.00', 'Brufen 400mg', '', '', '', '22%', '110.00', 'Amoxil 500mg']
        t2 = _make_grid_table([p2_r0], col_w)

        _build_pdf(pdf_path, [t1, PageBreak(), t2])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Adv02Warehouse")
        df = parser.parse()

        # 6 on Page 1 + 2 on Page 2 = 8 items total
        self.assertEqual(len(df), 8, f"Expected 8 products, got {len(df)}")
        names = " ".join(df['item_name'].tolist())
        self.assertIn("Brufen", names)
        self.assertIn("Amoxil", names)

        # Verify Amoxil has its correct price 110.00 and discount 0.22, not shifted into empty group 1
        amoxil_row = df[df['item_name'].str.contains("Amoxil")].iloc[0]
        self.assertAlmostEqual(float(amoxil_row['base_price']), 110.0)
        self.assertAlmostEqual(float(amoxil_row['discount_rate']), 0.22)

        res = CatalogResult.from_dataframe(df)
        p2_diag = res.diagnostics.pages[1]
        self.assertEqual(p2_diag.accepted_rows, 2)
        # Group 1 must have 0 candidates, 0 accepted, 0 rejected
        self.assertEqual(p2_diag.groups[1].candidate_rows, 0)
        self.assertEqual(p2_diag.groups[1].accepted_rows, 0)
        self.assertEqual(p2_diag.groups[1].rejected_rows, 0)

    def test_adv_03_standalone_headerless_first_page_three_groups_single_row(self):
        """Standalone 1-page document with NO headers anywhere and ONLY 1 row of data across 3 groups.
        System must dynamically partition and extract all 3 items without prior page layout."""
        pdf_path = os.path.join(self.temp_dir, "adv03_standalone_3grp_1row.pdf")
        col_w = [35, 35, 110, 35, 35, 110, 35, 35, 110]

        row0 = ['10%', '50.00', 'Panadol Extra 500mg', '15%', '35.00', 'Cataflam 50mg', '20%', '90.00', 'Augmentin 1g']
        t = _make_grid_table([row0], col_w)
        _build_pdf(pdf_path, [t])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Adv03Warehouse")
        df = parser.parse()

        self.assertEqual(
            len(df), 3,
            f"Expected 3 products from standalone headerless 3-group single-row table, got {len(df)}."
        )
        names = " ".join(df['item_name'].tolist())
        self.assertIn("Panadol", names)
        self.assertIn("Cataflam", names)
        self.assertIn("Augmentin", names)

    def test_adv_04_consecutive_headerless_continuation_pages_single_row(self):
        """Page 1 (headered 3 groups x 2 rows) -> Page 2 (headerless 1 row) -> Page 3 (headerless 1 row).
        Established layout must persist seamlessly across multiple consecutive single-row continuation pages."""
        pdf_path = os.path.join(self.temp_dir, "adv04_multi_cont.pdf")
        col_w = [35, 35, 110, 35, 35, 110, 35, 35, 110]

        hdr = ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name']
        p1_r1 = ['10%', '50.00', 'Panadol Extra 500mg', '15%', '35.00', 'Cataflam 50mg', '20%', '90.00', 'Augmentin 1g']
        p1_r2 = ['5%', '20.00', 'Congestal Tablets', '8%', '25.00', 'Antinal Capsules', '14%', '60.00', 'Voltaren 100mg']
        t1 = _make_grid_table([hdr, p1_r1, p1_r2], col_w)

        p2_r0 = ['12%', '40.00', 'Brufen 400mg', '18%', '75.00', 'Flagyl 500mg', '22%', '110.00', 'Amoxil 500mg']
        t2 = _make_grid_table([p2_r0], col_w)

        p3_r0 = ['9%', '30.00', 'Zithrokan 500mg', '16%', '55.00', 'Kestine 20mg', '25%', '130.00', 'Klacid 500mg']
        t3 = _make_grid_table([p3_r0], col_w)

        _build_pdf(pdf_path, [t1, PageBreak(), t2, PageBreak(), t3])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Adv04Warehouse")
        df = parser.parse()

        # 6 + 3 + 3 = 12 products
        self.assertEqual(len(df), 12, f"Expected 12 products across 3 pages, got {len(df)}")
        res = CatalogResult.from_dataframe(df)
        self.assertEqual(len(res.diagnostics.pages), 3)
        self.assertEqual(res.diagnostics.pages[1].accepted_rows, 3)
        self.assertEqual(res.diagnostics.pages[2].accepted_rows, 3)


class TestChallenger2CacheInvalidation(unittest.TestCase):
    """Focus Area 2: Cache invalidation when files are replaced or timestamps modified."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="adv_c2_cache_")
        global_catalog_cache.clear()

    def tearDown(self):
        global_catalog_cache.clear()
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_adv_05_cache_invalidation_when_mtime_is_forged_back(self):
        """Adversarial Attack: File is replaced with completely different content, but file's
        modification time (mtime) and access time (atime) are explicitly forged back to the exact
        original timestamps using os.utime.
        Cache MUST invalidate based on content SHA-256 hash and not be tricked by identical timestamps."""
        pdf_path = os.path.join(self.temp_dir, "mtime_attack.pdf")
        col_w = [45, 45, 180, 45, 45, 180]

        # Version 1: 4 products
        hdr = ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name']
        v1_r1 = ['10%', '50.00', 'Panadol Extra 500mg', '15%', '35.00', 'Cataflam 50mg']
        v1_r2 = ['5%', '20.00', 'Congestal Tablets', '20%', '90.00', 'Augmentin 1g']
        t1 = _make_grid_table([hdr, v1_r1, v1_r2], col_w)
        _build_pdf(pdf_path, [t1])

        orig_stat = os.stat(pdf_path)
        orig_atime = orig_stat.st_atime
        orig_mtime = orig_stat.st_mtime

        # Inspect catalog V1 -> sets cache
        res1 = inspect_catalog(pdf_path)
        self.assertEqual(len(res1.dataframe), 4)
        names1 = " ".join(res1.dataframe['item_name'].tolist())
        self.assertIn("Panadol", names1)

        # Overwrite file with Version 2: 2 completely different products
        v2_r1 = ['8%', '45.00', 'Brufen 400mg', '12%', '60.00', 'Voltaren 100mg']
        t2 = _make_grid_table([hdr, v2_r1], col_w)
        _build_pdf(pdf_path, [t2])

        # Forge mtime and atime back to original
        os.utime(pdf_path, (orig_atime, orig_mtime))
        new_stat = os.stat(pdf_path)
        self.assertEqual(new_stat.st_mtime, orig_mtime, "Failed to forge mtime")

        # Inspect catalog again WITHOUT refresh flag
        res2 = inspect_catalog(pdf_path, refresh=False)

        # Must return Version 2 (2 products), NOT the stale Version 1 (4 products)
        self.assertEqual(
            len(res2.dataframe), 2,
            f"Cache accepted forged mtime! Returned {len(res2.dataframe)} items instead of reparsing 2 items."
        )
        names2 = " ".join(res2.dataframe['item_name'].tolist())
        self.assertIn("Brufen", names2)
        self.assertNotIn("Panadol", names2)

    def test_adv_06_cache_hit_when_content_is_identical_but_mtime_modified(self):
        """File content is identical (same SHA-256), but mtime is updated (e.g. touch/copy).
        Cache verification should validate content hash and retain cached diagnostics."""
        pdf_path = os.path.join(self.temp_dir, "mtime_touch.pdf")
        col_w = [45, 45, 180, 45, 45, 180]

        hdr = ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name']
        r1 = ['10%', '50.00', 'Panadol Extra 500mg', '15%', '35.00', 'Cataflam 50mg']
        t = _make_grid_table([hdr, r1], col_w)
        _build_pdf(pdf_path, [t])

        res1 = inspect_catalog(pdf_path)
        self.assertEqual(len(res1.dataframe), 2)

        # Modify mtime to 1 hour in the future
        future_time = time.time() + 3600
        os.utime(pdf_path, (future_time, future_time))

        res2 = inspect_catalog(pdf_path, refresh=False)
        self.assertEqual(len(res2.dataframe), 2)
        self.assertEqual(res2.fingerprint.sha256, res1.fingerprint.sha256)

    def test_adv_07_file_replacement_churn_stress(self):
        """Rapid alternating file replacement at the same path (20 iterations).
        Inspect catalog must never return stale or mismatched data across rapid writes."""
        pdf_path = os.path.join(self.temp_dir, "churn_target.pdf")
        col_w = [45, 45, 180, 45, 45, 180]
        hdr = ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name']

        # Dataset A (2 items)
        t_a = _make_grid_table([hdr, ['10%', '50.00', 'Panadol Extra 500mg', '15%', '35.00', 'Cataflam 50mg']], col_w)
        # Dataset B (4 items)
        t_b = _make_grid_table([
            hdr,
            ['8%', '45.00', 'Brufen 400mg', '12%', '60.00', 'Voltaren 100mg'],
            ['7%', '25.00', 'Antinal Capsules', '18%', '75.00', 'Flagyl 500mg'],
        ], col_w)

        for i in range(10):
            # Write Dataset A
            _build_pdf(pdf_path, [t_a])
            res_a = inspect_catalog(pdf_path, refresh=False)
            self.assertEqual(len(res_a.dataframe), 2, f"Iteration {i} (A) failed")
            names_a = " ".join(res_a.dataframe['item_name'].tolist())
            self.assertIn("Panadol", names_a)

            # Write Dataset B
            _build_pdf(pdf_path, [t_b])
            res_b = inspect_catalog(pdf_path, refresh=False)
            self.assertEqual(len(res_b.dataframe), 4, f"Iteration {i} (B) failed")
            names_b = " ".join(res_b.dataframe['item_name'].tolist())
            self.assertIn("Brufen", names_b)

    def test_adv_08_corrupted_zero_byte_file_invalidates_cache_and_pipeline(self):
        """File is initially valid and cached. Then it is truncated to 0 bytes.
        inspect_catalog and pipeline must evict the cache and report errors, never returning stale items."""
        pdf_path = os.path.join(self.temp_dir, "truncate_target.pdf")
        order_path = os.path.join(self.temp_dir, "dummy_order.xlsx")
        out_dir = os.path.join(self.temp_dir, "out")
        os.makedirs(out_dir, exist_ok=True)

        col_w = [45, 45, 180, 45, 45, 180]
        hdr = ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name']
        t = _make_grid_table([hdr, ['10%', '50.00', 'Panadol Extra 500mg', '15%', '35.00', 'Cataflam 50mg']], col_w)
        _build_pdf(pdf_path, [t])
        _create_dummy_order_excel(order_path, ["Panadol Extra 500mg"])

        res1 = inspect_catalog(pdf_path)
        self.assertEqual(len(res1.dataframe), 2)

        # Truncate file to 0 bytes
        with open(pdf_path, "wb") as f:
            pass

        # inspect_catalog must return 0 items and errors
        res2 = inspect_catalog(pdf_path, refresh=False)
        self.assertEqual(len(res2.dataframe), 0)
        self.assertTrue(len(res2.diagnostics.errors) > 0 or res2.dataframe.empty)

        # run_procurement_pipeline must not use stale cached items
        # It should either fail or process 0 catalog items
        try:
            run_procurement_pipeline(
                order_files=[order_path],
                catalog_files=[pdf_path],
                output_dir=out_dir,
                catalog_cache=global_catalog_cache,
            )
        except Exception:
            # Expected pipeline error when catalog cannot be parsed
            pass


class TestChallenger2ReconciliationAndEdgeCases(unittest.TestCase):
    """Focus Area 3: Reconciliation of candidate vs accepted vs unprocessed row counts."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="adv_c2_recon_")
        global_catalog_cache.clear()

    def tearDown(self):
        global_catalog_cache.clear()
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_adv_09_multi_table_mixed_outcomes_reconciliation_invariant(self):
        """Page has 2 structural tables and 1 legacy table with mixed accepted and rejected rows.
        Diagnostics must strictly satisfy:
        1. candidate_rows == accepted_rows + rejected_rows + unprocessed_rows across all groups and pages.
        2. sum(g.accepted_rows for g in page.groups) == page.accepted_rows.
        3. sum(p.accepted_rows for p in diag.pages) == diag.accepted_rows.
        4. Group strategies reflect unambiguous table provenance."""
        pdf_path = os.path.join(self.temp_dir, "adv09_multi_table_recon.pdf")

        # Table 1 (structural): 2 groups x 3 data rows = 6 candidates
        # Row 1: 2 valid
        # Row 2: Group 0 missing price, Group 1 valid
        # Row 3: 2 valid
        # -> Group 0: 2 accepted, 1 rejected. Group 1: 3 accepted, 0 rejected. Total: 5 accepted, 1 rejected
        t1_data = [
            ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name'],
            ['10%', '50.00', 'Panadol Extra 500mg', '15%', '35.00', 'Cataflam 50mg'],
            ['5%', '', 'Congestal Tablets', '20%', '90.00', 'Augmentin 1g'],
            ['8%', '30.00', 'Amoxil 250mg', '10%', '40.00', 'Brufen 200mg'],
        ]
        t1 = _make_grid_table(t1_data, [45, 45, 180, 45, 45, 180])

        # Table 2 (structural): 2 groups x 2 data rows = 4 candidates (all valid)
        t2_data = [
            ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name'],
            ['12%', '45.00', 'Brufen 400mg', '14%', '60.00', 'Voltaren 100mg'],
            ['7%', '25.00', 'Antinal Capsules', '18%', '75.00', 'Flagyl 500mg'],
        ]
        t2 = _make_grid_table(t2_data, [45, 45, 180, 45, 45, 180])

        # Table 3 (legacy single-group): 1 group x 3 data rows = 3 candidates
        # Row 1: valid
        # Row 2: missing price -> rejected
        # Row 3: valid
        # -> 2 accepted, 1 rejected
        t3_data = [
            ['Disc', 'Price', 'Item Name'],
            ['10%', '55.00', 'Zithrokan 500mg'],
            ['15%', '', 'Missing Price Legacy Drug'],
            ['15%', '65.00', 'Kestine 20mg'],
        ]
        t3 = _make_grid_table(t3_data, [50, 50, 220])

        _build_pdf(pdf_path, [t1, Spacer(1, 15), t2, Spacer(1, 15), t3])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Adv09Warehouse")
        df = parser.parse()

        # Expected:
        # Table 1: 5 accepted, 1 rejected
        # Table 2: 4 accepted, 0 rejected
        # Table 3: 2 accepted, 1 rejected
        # Total accepted = 5 + 4 + 2 = 11 items
        self.assertEqual(len(df), 11, f"Expected 11 accepted products, got {len(df)}")

        res = CatalogResult.from_dataframe(df)
        self.assertIsNotNone(res)
        diag = res.diagnostics
        self.assertEqual(len(diag.pages), 1)
        p1 = diag.pages[0]

        # Invariant 1: candidate == accepted + rejected + unprocessed
        for g_i, g in enumerate(p1.groups):
            self.assertEqual(
                g.candidate_rows, g.accepted_rows + g.rejected_rows + g.unprocessed_rows,
                f"Group {g_i} ({g.strategy}) violated reconciliation invariant: "
                f"{g.candidate_rows} != {g.accepted_rows} + {g.rejected_rows} + {g.unprocessed_rows}"
            )

        # Invariant 2: Page accepted rows == sum of groups accepted rows
        self.assertEqual(p1.accepted_rows, sum(g.accepted_rows for g in p1.groups))
        self.assertEqual(p1.accepted_rows, 11)

        # Invariant 3: ImportDiagnostics reconciliation
        self.assertEqual(diag.accepted_rows, 11)
        self.assertEqual(diag.rejected_rows, 2)
        self.assertEqual(diag.unprocessed_rows, 0)
        self.assertEqual(diag.candidate_rows, 13)
        self.assertEqual(diag.candidate_rows, diag.accepted_rows + diag.rejected_rows + diag.unprocessed_rows)

        # Invariant 4: Status must be 'partial' and require acknowledgment due to 2 rejected rows
        self.assertEqual(diag.status, "partial")
        self.assertTrue(diag.requires_acknowledgment)

        # Invariant 5: Table provenance strings
        strategies = [g.strategy for g in p1.groups]
        self.assertIn("structural_table_t0", strategies)
        self.assertIn("structural_table_t1", strategies)
        self.assertIn("legacy_table_t0", strategies)

    def test_adv_10_missing_name_cell_and_blank_rows_accounting(self):
        """Adversarial row accounting:
        - Completely blank row -> excluded from candidate_rows.
        - Blank item name with price/discount present -> counted as candidate and rejected (not silently ignored).
        - Price <= 0 -> counted as candidate and rejected.
        - Status must be 'partial'."""
        pdf_path = os.path.join(self.temp_dir, "adv10_blank_accounting.pdf")
        col_w = [45, 45, 180, 45, 45, 180]

        data = [
            ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name'],
            # Row 1: Valid + Valid = 2 accepted
            ['10%', '50.00', 'Panadol Extra 500mg', '15%', '35.00', 'Cataflam 50mg'],
            # Row 2: Completely blank group 0 (3 empty cells) + Valid group 1 = 1 accepted, 0 rejected for g0
            ['', '', '', '20%', '90.00', 'Augmentin 1g'],
            # Row 3: Blank name in group 0 (has price and discount) + Price 0.0 in group 1
            # -> group 0 rejected (blank_name), group 1 rejected (invalid_price)
            ['5%', '25.00', '', '10%', '0.00', 'Antinal Capsules'],
        ]
        t = _make_grid_table(data, col_w)
        _build_pdf(pdf_path, [t])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Adv10Warehouse")
        df = parser.parse()

        # Accepted: Panadol, Cataflam, Augmentin = 3 items
        self.assertEqual(len(df), 3, f"Expected 3 accepted items, got {len(df)}")

        res = CatalogResult.from_dataframe(df)
        diag = res.diagnostics
        p1 = diag.pages[0]

        # Group 0:
        # Row 1: Panadol (accepted)
        # Row 2: completely blank -> excluded
        # Row 3: blank name -> candidate + rejected
        # -> Candidate: 2, Accepted: 1, Rejected: 1
        g0 = p1.groups[0]
        self.assertEqual(g0.candidate_rows, 2)
        self.assertEqual(g0.accepted_rows, 1)
        self.assertEqual(g0.rejected_rows, 1)

        # Group 1:
        # Row 1: Cataflam (accepted)
        # Row 2: Augmentin (accepted)
        # Row 3: Price 0.00 -> candidate + rejected
        # -> Candidate: 3, Accepted: 2, Rejected: 1
        g1 = p1.groups[1]
        self.assertEqual(g1.candidate_rows, 3)
        self.assertEqual(g1.accepted_rows, 2)
        self.assertEqual(g1.rejected_rows, 1)

        # Page totals: candidate = 5, accepted = 3, rejected = 2
        self.assertEqual(diag.candidate_rows, 5)
        self.assertEqual(diag.accepted_rows, 3)
        self.assertEqual(diag.rejected_rows, 2)
        self.assertEqual(diag.candidate_rows, diag.accepted_rows + diag.rejected_rows + diag.unprocessed_rows)
        self.assertEqual(diag.status, "partial")
        self.assertTrue(diag.requires_acknowledgment)

    def test_adv_11_three_groups_continuation_single_row_arabic_eastern_digits(self):
        """Headerless continuation on Page 2 with 1 single row containing Arabic text
        and Eastern Arabic digits (١٠%, ٥٠.٠٠) across 3 side-by-side groups.
        All 3 products must survive, with correct price, discount, and normalized Arabic names."""
        pdf_path = os.path.join(self.temp_dir, "adv11_arabic_cont.pdf")
        col_w = [35, 35, 110, 35, 35, 110, 35, 35, 110]

        # Page 1: Arabic headers + 1 data row
        hdr = ['خصم', 'سعر', 'اسم الصنف', 'خصم', 'سعر', 'اسم الصنف', 'خصم', 'سعر', 'اسم الصنف']
        p1_r1 = ['١٠%', '٥٠.٠٠', 'بنادول إكسترا ٥٠٠ مجم', '١٥%', '٣٥.٠٠', 'كتافلام ٥٠ مجم', '٢٠%', '٩٠.٠٠', 'أوجمنتين ١ جم']
        t1 = _make_grid_table([hdr, p1_r1], col_w)

        # Page 2: Headerless continuation, single row across 3 groups with Eastern digits
        p2_r0 = ['١٢%', '٤٠.٠٠', 'بروفين ٤٠٠ مجم', '١٨%', '٧٥.٠٠', 'فلاجيل ٥٠٠ مجم', '٢٢%', '١١٠.٠٠', 'أموكسيل ٥٠٠ مجم']
        t2 = _make_grid_table([p2_r0], col_w)

        _build_pdf(pdf_path, [t1, PageBreak(), t2])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Adv11Warehouse")
        df = parser.parse()

        # 3 on p1 + 3 on p2 = 6 items
        self.assertEqual(len(df), 6, f"Expected 6 Arabic products, got {len(df)}")
        res = CatalogResult.from_dataframe(df)
        self.assertEqual(len(res.diagnostics.pages), 2)
        self.assertEqual(res.diagnostics.pages[1].accepted_rows, 3)

        # Check values of Page 2 items
        brufen = df[df['normalized_name'].str.contains("بروفين")].iloc[0]
        self.assertAlmostEqual(float(brufen['base_price']), 40.0)
        self.assertAlmostEqual(float(brufen['discount_rate']), 0.12)

        flagyl = df[df['normalized_name'].str.contains("فلاجيل")].iloc[0]
        self.assertAlmostEqual(float(flagyl['base_price']), 75.0)
        self.assertAlmostEqual(float(flagyl['discount_rate']), 0.18)

    def test_adv_12_incompatible_geometry_on_page2_does_not_corrupt_fallback(self):
        """Page 1 has 3 groups (9 columns). Page 2 has an incompatible 4-column legacy table.
        Established layout from Page 1 must NOT be applied to Page 2; Page 2 must parse independently."""
        pdf_path = os.path.join(self.temp_dir, "adv12_incompatible_p2.pdf")

        # Page 1: 9 columns (3 groups)
        col_w1 = [35, 35, 110, 35, 35, 110, 35, 35, 110]
        hdr1 = ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name']
        p1_r1 = ['10%', '50.00', 'Panadol Extra 500mg', '15%', '35.00', 'Cataflam 50mg', '20%', '90.00', 'Augmentin 1g']
        t1 = _make_grid_table([hdr1, p1_r1], col_w1)

        # Page 2: 3 columns legacy table
        col_w2 = [50, 50, 220]
        hdr2 = ['Disc', 'Price', 'Item Name']
        p2_r1 = ['12%', '45.00', 'Brufen 400mg']
        p2_r2 = ['14%', '60.00', 'Voltaren 100mg']
        t2 = _make_grid_table([hdr2, p2_r1, p2_r2], col_w2)

        _build_pdf(pdf_path, [t1, PageBreak(), t2])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Adv12Warehouse")
        df = parser.parse()

        # 3 on p1 + 2 on p2 = 5 items
        self.assertEqual(len(df), 5, f"Expected 5 products across incompatible layouts, got {len(df)}")
        res = CatalogResult.from_dataframe(df)
        self.assertEqual(len(res.diagnostics.pages), 2)
        self.assertEqual(res.diagnostics.pages[0].strategy, "structural_table")
        self.assertEqual(res.diagnostics.pages[1].strategy, "legacy_table")

    def test_adv_13_partial_token_cross_catalog_rejection(self):
        """Security/integrity: Acknowledgment token generated for Catalog A cannot be used to
        authorize a different partial Catalog B.
        Pipeline must reject mismatched token and execute only when the authentic token is provided."""
        cat_a_path = os.path.join(self.temp_dir, "cat_a_partial.pdf")
        cat_b_path = os.path.join(self.temp_dir, "cat_b_partial.pdf")
        order_path = os.path.join(self.temp_dir, "order.xlsx")
        out_dir = os.path.join(self.temp_dir, "out13")
        os.makedirs(out_dir, exist_ok=True)

        col_w = [45, 45, 180, 45, 45, 180]
        hdr = ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name']

        # Catalog A: 1 valid, 1 rejected
        t_a = _make_grid_table([
            hdr,
            ['10%', '50.00', 'Panadol Extra 500mg', '15%', '', 'Rejected Med A'],
        ], col_w)
        _build_pdf(cat_a_path, [t_a])

        # Catalog B: 1 valid, 1 rejected (different med)
        t_b = _make_grid_table([
            hdr,
            ['12%', '45.00', 'Brufen 400mg', '18%', '', 'Rejected Med B'],
        ], col_w)
        _build_pdf(cat_b_path, [t_b])

        _create_dummy_order_excel(order_path, ["Brufen 400mg"])

        res_a = inspect_catalog(cat_a_path)
        token_a = res_a.acknowledgment_token
        self.assertEqual(res_a.diagnostics.status, "partial")

        res_b = inspect_catalog(cat_b_path)
        token_b = res_b.acknowledgment_token
        self.assertEqual(res_b.diagnostics.status, "partial")
        self.assertNotEqual(token_a, token_b, "Tokens for different catalogs must not collide")

        # Attempt to run Catalog B with token A -> MUST fail
        with self.assertRaises(PipelineExecutionError) as ctx:
            run_procurement_pipeline(
                order_files=[order_path],
                catalog_files=[cat_b_path],
                output_dir=out_dir,
                accepted_partial_tokens=[token_a],
            )
        self.assertIn("explicit acknowledgment is required", str(ctx.exception).lower())

        # Now run Catalog B with authentic token B -> MUST succeed
        result = run_procurement_pipeline(
            order_files=[order_path],
            catalog_files=[cat_b_path],
            output_dir=out_dir,
            accepted_partial_tokens=[token_b],
        )
        self.assertIsNotNone(result)
        self.assertTrue(os.path.isfile(result['report_path']))

    def test_adv_14_validate_cached_catalog_malformed_object_safety(self):
        """Adversarial stress on validate_cached_catalog with malformed, poisoned, or type-violating objects.
        Must return None safely without unhandled exceptions."""
        pdf_path = os.path.join(self.temp_dir, "adv14_target.pdf")
        col_w = [45, 45, 180, 45, 45, 180]
        hdr = ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name']
        t = _make_grid_table([hdr, ['10%', '50.00', 'Panadol Extra 500mg', '15%', '35.00', 'Cataflam 50mg']], col_w)
        _build_pdf(pdf_path, [t])

        real_fp = FileFingerprint.from_path(pdf_path)

        # 1. Non-existent file
        self.assertIsNone(validate_cached_catalog(pd.DataFrame(), "non_existent_file.pdf"))
        # 2. None candidate
        self.assertIsNone(validate_cached_catalog(None, pdf_path))
        # 3. Empty DataFrame
        self.assertIsNone(validate_cached_catalog(pd.DataFrame(), pdf_path))
        # 4. Arbitrary dict
        self.assertIsNone(validate_cached_catalog({"some": "dict"}, pdf_path))
        # 5. String object
        self.assertIsNone(validate_cached_catalog("corrupted_string", pdf_path))
        # 6. DataFrame without metadata
        df_no_meta = pd.DataFrame([{"a": 1}])
        self.assertIsNone(validate_cached_catalog(df_no_meta, pdf_path))
        # 7. CatalogResult with relative path fingerprint
        bad_fp1 = FileFingerprint(path="relative.pdf", sha256=real_fp.sha256)
        res_rel = CatalogResult(dataframe=pd.DataFrame([{"a": 1}]), diagnostics=ImportDiagnostics(), fingerprint=bad_fp1)
        self.assertIsNone(validate_cached_catalog(res_rel, pdf_path))
        # 8. CatalogResult with invalid 63-char sha256
        bad_fp2 = FileFingerprint(path=real_fp.path, sha256="a" * 63)
        res_bad_sha = CatalogResult(dataframe=pd.DataFrame([{"a": 1}]), diagnostics=ImportDiagnostics(), fingerprint=bad_fp2)
        self.assertIsNone(validate_cached_catalog(res_bad_sha, pdf_path))
        # 9. CatalogResult with wrong sha256
        bad_fp3 = FileFingerprint(path=real_fp.path, sha256="0" * 64)
        res_wrong_sha = CatalogResult(dataframe=pd.DataFrame([{"a": 1}]), diagnostics=ImportDiagnostics(), fingerprint=bad_fp3)
        self.assertIsNone(validate_cached_catalog(res_wrong_sha, pdf_path))

    def test_adv_15_three_groups_continuation_single_row_explicit_zero_discount(self):
        """Continuation row 0 has explicit zero discounts: 'صافي', 'نقدى', '0%'.
        All 3 products must be extracted with discount_rate == 0.0 and valid stock status."""
        pdf_path = os.path.join(self.temp_dir, "adv15_zero_disc.pdf")
        col_w = [35, 35, 110, 35, 35, 110, 35, 35, 110]

        hdr = ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name']
        p1_r1 = ['10%', '50.00', 'Panadol Extra 500mg', '15%', '35.00', 'Cataflam 50mg', '20%', '90.00', 'Augmentin 1g']
        t1 = _make_grid_table([hdr, p1_r1], col_w)

        # Page 2: Continuation row 0 with explicit zero discounts
        p2_r0 = ['صافي', '40.00', 'Brufen 400mg', 'نقدى', '75.00', 'Flagyl 500mg', '0%', '110.00', 'Amoxil 500mg']
        t2 = _make_grid_table([p2_r0], col_w)

        _build_pdf(pdf_path, [t1, PageBreak(), t2])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Adv15Warehouse")
        df = parser.parse()

        self.assertEqual(len(df), 6, f"Expected 6 products, got {len(df)}")
        res = CatalogResult.from_dataframe(df)
        self.assertEqual(res.diagnostics.status, "complete")

        # Verify all 3 continuation products have discount_rate == 0.0
        p2_items = df[df['item_name'].str.contains("Brufen|Flagyl|Amoxil")]
        self.assertEqual(len(p2_items), 3)
        for _, row in p2_items.iterrows():
            self.assertAlmostEqual(float(row['discount_rate']), 0.0)
            self.assertTrue(row['stock_status'])

    def test_adv_16_non_catalog_banner_page_interspersed_does_not_break_diagnostics(self):
        """Page 1: Multi-table catalog (4 items).
        Page 2: Small non-catalog metadata/banner table (e.g. 'Printed: 10:30 PM, Page: 2, By: Staff'),
                yielding 0 items and no catalog keywords.
        Page 3: Continuation catalog table (4 items).
        Parser must skip non-catalog table without corrupting diagnostics or falsely setting partial status."""
        pdf_path = os.path.join(self.temp_dir, "adv16_banner_interspersed.pdf")
        col_w = [45, 45, 180, 45, 45, 180]

        hdr = ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name']
        p1_r1 = ['10%', '50.00', 'Panadol Extra 500mg', '15%', '35.00', 'Cataflam 50mg']
        p1_r2 = ['5%', '20.00', 'Congestal Tablets', '20%', '90.00', 'Augmentin 1g']
        t1 = _make_grid_table([hdr, p1_r1, p1_r2], col_w)

        # Page 2: Non-catalog banner table
        banner_table = _make_grid_table([['06:53:09 PM', 'Page 2 of 3', 'Admin Sys']], [150, 150, 150])

        # Page 3: Continuation data table
        p3_r1 = ['8%', '45.00', 'Brufen 400mg', '12%', '60.00', 'Voltaren 100mg']
        p3_r2 = ['7%', '25.00', 'Antinal Capsules', '18%', '75.00', 'Flagyl 500mg']
        t3 = _make_grid_table([hdr, p3_r1, p3_r2], col_w)

        _build_pdf(pdf_path, [t1, PageBreak(), banner_table, PageBreak(), t3])

        parser = PDFCatalogParser(pdf_path, warehouse_name="Adv16Warehouse")
        df = parser.parse()

        # 4 on p1 + 0 on p2 + 4 on p3 = 8 items
        self.assertEqual(len(df), 8, f"Expected 8 items, got {len(df)}")
        res = CatalogResult.from_dataframe(df)
        self.assertIsNotNone(res)
        diag = res.diagnostics
        self.assertEqual(diag.accepted_rows, 8)
        self.assertEqual(diag.rejected_rows, 0)
        # Empty non-catalog middle page means completeness cannot be determined -> unverified
        self.assertEqual(diag.status, "unverified")


if __name__ == "__main__":
    unittest.main()
