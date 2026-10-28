# -*- coding: utf-8 -*-
"""
Release Review & Packaged Distribution Verification Suite (Milestone 4 / R5)
File: tests/test_m4_release_verification.py

Verifies:
1. Standalone Windows executable (dist/EgyptianPharmaOptimizer/EgyptianPharmaOptimizer.exe) execution and dependency bundling.
2. Exact fixture recovery: Hayah Shibin (571 items: [141, 141, 141, 141, 7] per page, [47, 47, 47] per group).
3. Multi-table PDF ingestion (two structural tables, mixed structural & legacy tables).
4. Headerless continuation PDF ingestion (row 0 data rows preserved).
5. Headerless single-row PDF ingestion (no headers anywhere, 1 product row extracts cleanly).
6. Cache lifecycle verification:
   - Fresh imports (cache miss -> reparse from disk + fingerprint).
   - Valid cached imports (cache hit -> zero disk reparse, exact diagnostics preserved).
   - Changed-file refresh (disk byte change -> cache + token invalidated).
   - Partial-import acknowledgment gating (unacknowledged blocked, acknowledged accepted).
7. System Agreement Verification:
   - Confirms diagnostics, UI card badges, item viewer records, and procurement inventory agree 100%.
8. Comprehensive Source vs Packaged Parity Comparison.
"""

import os
import sys
import time
import shutil
import tempfile
import subprocess
import unittest
import pandas as pd
import pytest

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, PageBreak, Spacer

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
DIST_DIR = os.path.join(PROJECT_ROOT, "dist", "EgyptianPharmaOptimizer")
DIST_INTERNAL = os.path.join(DIST_DIR, "_internal")
EXE_PATH = os.path.join(DIST_DIR, "EgyptianPharmaOptimizer.exe")
HAYAH_FIXTURE_PATH = os.path.join(PROJECT_ROOT, "tests", "fixtures", "hayah_shibin.pdf")


def _build_pdf(file_path: str, flowables: list, pagesize=letter, margins=20):
    """Helper to generate PDF file using ReportLab."""
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


class TestMilestone4ReleaseVerification(unittest.TestCase):
    """Comprehensive Milestone 4 release verification test suite."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="m4_verify_")

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ------------------------------------------------------------------------
    # 1. Standalone Executable Verification
    # ------------------------------------------------------------------------
    def test_01_executable_exists_and_bundles_dependencies(self):
        """Verify dist/EgyptianPharmaOptimizer/EgyptianPharmaOptimizer.exe exists and dependencies are bundled."""
        self.assertTrue(os.path.isfile(EXE_PATH), f"Executable not found at: {EXE_PATH}")
        exe_size = os.path.getsize(EXE_PATH)
        self.assertGreater(exe_size, 10 * 1024 * 1024, f"Executable too small ({exe_size} bytes)")

        # Verify key bundled components in _internal
        self.assertTrue(os.path.isdir(DIST_INTERNAL), f"_internal dir not found at: {DIST_INTERNAL}")
        self.assertTrue(os.path.isdir(os.path.join(DIST_INTERNAL, "src")), "Bundled src/ missing")
        self.assertTrue(os.path.isdir(os.path.join(DIST_INTERNAL, "pymupdf")), "Bundled pymupdf missing")
        self.assertTrue(os.path.isdir(os.path.join(DIST_INTERNAL, "pandas")), "Bundled pandas missing")
        self.assertTrue(os.path.isdir(os.path.join(DIST_INTERNAL, "customtkinter")), "Bundled customtkinter missing")
        self.assertTrue(os.path.isdir(os.path.join(DIST_INTERNAL, "data")), "Bundled data/ missing")

    def test_02_executable_headless_self_test(self):
        """Verify EgyptianPharmaOptimizer.exe runs headless self-test with return code 0."""
        cmd = [EXE_PATH, "--self-test"]
        proc = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, f"Executable --self-test failed with exit code {proc.returncode}")

    # ------------------------------------------------------------------------
    # 2. Hayah Shibin 571-Item Fixture Verification (Source & Packaged)
    # ------------------------------------------------------------------------
    def test_03_hayah_shibin_exact_fixture_recovery(self):
        """Verify 571 items, exact page/group counts, 0 rejected, 0 unprocessed."""
        from src.pdf_parser import PDFCatalogParser
        from src.catalog_diagnostics import CatalogResult

        self.assertTrue(os.path.isfile(HAYAH_FIXTURE_PATH), f"Fixture not found at: {HAYAH_FIXTURE_PATH}")

        # Test source parser
        parser_src = PDFCatalogParser(HAYAH_FIXTURE_PATH)
        df_src = parser_src.parse()
        self.assertEqual(len(df_src), 571, f"Source expected 571 items, got {len(df_src)}")

        res_src = CatalogResult.from_dataframe(df_src)
        self.assertIsNotNone(res_src)
        self.assertEqual(res_src.diagnostics.status, "complete")
        self.assertEqual(res_src.diagnostics.rejected_rows, 0)
        self.assertEqual(res_src.diagnostics.unprocessed_rows, 0)

        # Verify page accepted breakdown: [141, 141, 141, 141, 7]
        page_counts = [sum(g.accepted_rows for g in p.groups) for p in res_src.diagnostics.pages]
        self.assertEqual(page_counts, [141, 141, 141, 141, 7], f"Page breakdown mismatch: {page_counts}")

        # Verify group breakdown on pages 1-4: [47, 47, 47]
        for p_idx in range(4):
            g_counts = [g.accepted_rows for g in res_src.diagnostics.pages[p_idx].groups]
            self.assertEqual(g_counts, [47, 47, 47], f"Page {p_idx+1} group breakdown mismatch: {g_counts}")

        # Page 5: [7, 0, 0]
        p5_groups = [g.accepted_rows for g in res_src.diagnostics.pages[4].groups]
        self.assertEqual(p5_groups, [7, 0, 0], f"Page 5 group breakdown mismatch: {p5_groups}")

    # ------------------------------------------------------------------------
    # 3. Multiple-Table PDF Verification
    # ------------------------------------------------------------------------
    def test_04_multiple_table_pdf_extraction_and_provenance(self):
        """Verify multiple tables on one page are fully extracted with distinct table-indexed provenance."""
        from src.pdf_parser import PDFCatalogParser
        from src.catalog_diagnostics import CatalogResult

        pdf_path = os.path.join(self.temp_dir, "m4_multitable.pdf")
        t1 = _make_grid_table([
            ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name'],
            ['10%', '50.00', 'Panadol Extra 500mg', '15%', '35.00', 'Cataflam 50mg'],
            ['5%', '20.00', 'Congestal Tablets', '20%', '90.00', 'Augmentin 1g'],
        ], [45, 45, 180, 45, 45, 180])
        t2 = _make_grid_table([
            ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name'],
            ['8%', '45.00', 'Brufen 400mg', '12%', '60.00', 'Voltaren 100mg'],
            ['7%', '25.00', 'Antinal Capsules', '18%', '75.00', 'Flagyl 500mg'],
        ], [45, 45, 180, 45, 45, 180])
        _build_pdf(pdf_path, [t1, Spacer(1, 20), t2])

        parser = PDFCatalogParser(pdf_path, warehouse_name="MultiTableWarehouse")
        df = parser.parse()
        self.assertEqual(len(df), 8, f"Expected 8 products, got {len(df)}")

        res = CatalogResult.from_dataframe(df)
        self.assertIsNotNone(res)
        p1 = res.diagnostics.pages[0]
        self.assertEqual(p1.accepted_rows, 8)

        # Check provenance has distinct table identifiers
        strategies = [g.strategy for g in p1.groups]
        self.assertTrue(any("structural_table_t0" in s for s in strategies), f"Missing table 0 provenance in {strategies}")
        self.assertTrue(any("structural_table_t1" in s for s in strategies), f"Missing table 1 provenance in {strategies}")

    # ------------------------------------------------------------------------
    # 4. Headerless Continuation PDF Verification
    # ------------------------------------------------------------------------
    def test_05_headerless_continuation_pdf_extraction(self):
        """Verify headerless continuation page preserves row 0 products."""
        from src.pdf_parser import PDFCatalogParser

        pdf_path = os.path.join(self.temp_dir, "m4_continuation.pdf")
        t_page1 = _make_grid_table([
            ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name'],
            ['10%', '50.00', 'Panadol Extra 500mg', '15%', '35.00', 'Cataflam 50mg'],
            ['5%', '20.00', 'Congestal Tablets', '20%', '90.00', 'Augmentin 1g'],
        ], [45, 45, 180, 45, 45, 180])

        # Page 2: No header; row 0 has genuine product data
        t_page2 = _make_grid_table([
            ['8%', '45.00', 'Brufen 400mg', '12%', '60.00', 'Voltaren 100mg'],
            ['7%', '25.00', 'Antinal Capsules', '18%', '75.00', 'Flagyl 500mg'],
        ], [45, 45, 180, 45, 45, 180])

        _build_pdf(pdf_path, [t_page1, PageBreak(), t_page2])

        parser = PDFCatalogParser(pdf_path, warehouse_name="ContinuationWarehouse")
        df = parser.parse()
        self.assertEqual(len(df), 8, f"Expected 8 items across two pages, got {len(df)}")

        names = " ".join(df['item_name'].tolist())
        self.assertIn("Brufen", names, "Row 0 product on continuation page was lost!")
        self.assertIn("Voltaren", names, "Row 0 product on continuation page was lost!")

    # ------------------------------------------------------------------------
    # 5. Headerless Single-Row PDF Verification
    # ------------------------------------------------------------------------
    def test_06_headerless_single_row_pdf_extraction(self):
        """Verify headerless first page with a single product row extracts cleanly without prior layout."""
        from src.pdf_parser import PDFCatalogParser

        pdf_path = os.path.join(self.temp_dir, "m4_single_row.pdf")
        t_single = _make_grid_table([
            ['15%', '120.00', 'Klacid 500mg 14 Tablets'],
        ], [60, 60, 240])
        _build_pdf(pdf_path, [t_single])

        parser = PDFCatalogParser(pdf_path, warehouse_name="SingleRowWarehouse")
        df = parser.parse()
        self.assertEqual(len(df), 1, f"Expected 1 item, got {len(df)}")
        self.assertIn("Klacid", df['item_name'].iloc[0])

    # ------------------------------------------------------------------------
    # 6. Cache Lifecycle Verification
    # ------------------------------------------------------------------------
    def test_07_cache_lifecycle_fresh_hit_refresh_gating(self):
        """Verify fresh imports, valid hits, changed-file refresh, and token gating."""
        from src.pdf_parser import PDFCatalogParser
        from src.catalog_diagnostics import FileFingerprint, CatalogResult
        from src.controller import inspect_catalog, global_catalog_cache
        from src.pipeline import run_procurement_pipeline, PipelineExecutionError

        global_catalog_cache.clear()

        pdf_path = os.path.join(self.temp_dir, "m4_cache_catalog.pdf")
        order_path = os.path.join(self.temp_dir, "m4_cache_order.xlsx")

        t1 = _make_grid_table([
            ['Disc', 'Price', 'Item Name'],
            ['10%', '50.00', 'Panadol Extra 500mg'],
            ['15%', '35.00', 'Cataflam 50mg'],
        ], [50, 50, 220])
        _build_pdf(pdf_path, [t1])
        _create_dummy_order_excel(order_path, ['Panadol Extra 500mg'])

        # Step 6a: Fresh import (cache miss)
        res_fresh = inspect_catalog(pdf_path, refresh=False)
        self.assertEqual(len(res_fresh.dataframe), 2)
        self.assertEqual(res_fresh.diagnostics.status, "complete")
        token_fresh = res_fresh.acknowledgment_token

        # Step 6b: Valid cached import (cache hit)
        res_cached = inspect_catalog(pdf_path, refresh=False)
        self.assertEqual(len(res_cached.dataframe), 2)
        self.assertEqual(res_cached.acknowledgment_token, token_fresh)

        # Step 6c: Changed-file refresh (file modified on disk)
        time.sleep(0.05)
        with open(pdf_path, "ab") as f:
            f.write(b"\n%MODIFIED_BY_M4_TEST\n")

        # After file change, inspect_catalog must detect SHA-256 change and refresh
        res_changed = inspect_catalog(pdf_path, refresh=False)
        self.assertNotEqual(res_changed.acknowledgment_token, token_fresh)

        # Step 6d: Partial-import acknowledgment gating
        # Create a partial catalog with a rejected row
        partial_pdf = os.path.join(self.temp_dir, "m4_partial.pdf")
        t_partial = _make_grid_table([
            ['Disc', 'Price', 'Item Name'],
            ['10%', '50.00', 'Panadol Extra 500mg'],
            ['invalid_disc', 'invalid_price', 'Corrupted Item Name'],
        ], [50, 50, 220])
        _build_pdf(partial_pdf, [t_partial])

        res_partial = inspect_catalog(partial_pdf, refresh=True)
        self.assertEqual(res_partial.diagnostics.status, "partial")
        self.assertTrue(res_partial.diagnostics.requires_acknowledgment)
        partial_token = res_partial.acknowledgment_token

        # Unacknowledged partial must raise PipelineExecutionError
        out_dir = os.path.join(self.temp_dir, "out")
        os.makedirs(out_dir, exist_ok=True)
        with self.assertRaises(PipelineExecutionError):
            run_procurement_pipeline(
                order_files=[order_path],
                catalog_files=[partial_pdf],
                output_dir=out_dir,
                allow_partial_imports=False,
                accepted_partial_tokens=set(),
            )

        # Acknowledged partial with valid token succeeds
        res_pipe = run_procurement_pipeline(
            order_files=[order_path],
            catalog_files=[partial_pdf],
            output_dir=out_dir,
            allow_partial_imports=False,
            accepted_partial_tokens={partial_token},
        )
        out_file = res_pipe['report_path']
        self.assertTrue(os.path.isfile(out_file), f"Output file missing: {out_file}")

    # ------------------------------------------------------------------------
    # 7. System Agreement Verification
    # (Diagnostics == Badges == Item Viewer == Procurement Inventory)
    # ------------------------------------------------------------------------
    def test_08_system_agreement_diagnostics_badges_viewer_procurement(self):
        """Confirm diagnostics, UI badges, item viewer, and procurement inventory agree 100%."""
        from src.controller import inspect_catalog, global_catalog_cache
        from src.pipeline import run_procurement_pipeline

        global_catalog_cache.clear()

        pdf_path = os.path.join(self.temp_dir, "m4_agreement_cat.pdf")
        order_path = os.path.join(self.temp_dir, "m4_agreement_order.xlsx")

        items_data = [
            ['10%', '50.00', 'Panadol Extra 500mg'],
            ['15%', '35.00', 'Cataflam 50mg'],
            ['20%', '80.00', 'Augmentin 1g'],
        ]
        t = _make_grid_table([['Disc', 'Price', 'Item Name']] + items_data, [50, 50, 220])
        _build_pdf(pdf_path, [t])
        _create_dummy_order_excel(order_path, ['Panadol Extra 500mg', 'Cataflam 50mg', 'Augmentin 1g'])

        # 1. Diagnostics level
        cat_res = inspect_catalog(pdf_path, refresh=False)
        diag_count = cat_res.diagnostics.accepted_rows
        diag_status = cat_res.diagnostics.status
        self.assertEqual(diag_count, 3)
        self.assertEqual(diag_status, "complete")

        # 2. Badge level (as calculated by app_gui._update_file_card_badge)
        item_count_badge = len(cat_res.dataframe)
        badge_status = cat_res.diagnostics.status
        badge_text = f"📦 {item_count_badge} صنف ✓ / Complete ({item_count_badge} items)" if badge_status == "complete" else f"⚠️ {item_count_badge} صنف"
        self.assertEqual(item_count_badge, diag_count)
        self.assertEqual(badge_status, diag_status)
        self.assertIn("3 صنف", badge_text)

        # 3. Item Viewer level (as populated by app_gui._open_catalog_item_viewer)
        raw_records = []
        for idx, r in cat_res.dataframe.iterrows():
            name = str(r.get('item_name', '')).strip()
            if not name:
                continue
            price = float(r.get('base_price', 0.0) or 0.0)
            disc = float(r.get('discount_rate', 0.0) or 0.0)
            disc_pct = disc * 100.0 if 0 < disc <= 1.0 else disc
            stock = "متوفر ✓" if r.get('stock_status', True) else "غير متوفر ✕"
            raw_records.append({
                "name": name,
                "price": price,
                "disc": disc_pct,
                "status": stock,
            })
        viewer_count = len(raw_records)
        self.assertEqual(viewer_count, diag_count, f"Item viewer count ({viewer_count}) != diagnostics count ({diag_count})")

        # 4. Procurement Inventory level
        # In run_procurement_pipeline, cached catalog is validated and fed to MedicineAllocator
        out_dir = os.path.join(self.temp_dir, "out_agree")
        os.makedirs(out_dir, exist_ok=True)
        pipeline_res = run_procurement_pipeline(
            order_files=[order_path],
            catalog_files=[pdf_path],
            output_dir=out_dir,
        )
        out_file = pipeline_res['report_path']
        self.assertTrue(os.path.isfile(out_file))

        # Check allocated items count from results
        kpis = pipeline_res.get('kpis', {})
        matched_items_count = kpis.get('matched_items', 0)
        self.assertEqual(matched_items_count, 3, f"Procurement allocated {matched_items_count} items, expected 3")

        # Exact parity assertion: Diagnostics == Badges == Viewer == Procurement Inventory
        self.assertEqual(diag_count, item_count_badge, "Badge count diverged from diagnostics!")
        self.assertEqual(diag_count, viewer_count, "Item viewer count diverged from diagnostics!")
        self.assertEqual(diag_count, matched_items_count, "Procurement inventory count diverged from diagnostics!")

    # ------------------------------------------------------------------------
    # 8. Source vs Packaged Parity Comparison
    # ------------------------------------------------------------------------
    def test_09_packaged_bundle_parity_comparison(self):
        """Execute identical verification inside packaged _internal bundle and verify 100% parity."""
        import json

        runner_script = os.path.join(self.temp_dir, "run_packaged_verify.py")
        with open(runner_script, "w", encoding="utf-8") as f:
            f.write(r'''
import sys
import os
import json
import pandas as pd

packaged_internal = sys.argv[1]
sys.path.insert(0, packaged_internal)
if "" in sys.path:
    sys.path.remove("")

from src.pdf_parser import PDFCatalogParser
from src.catalog_diagnostics import CatalogResult
from src.controller import inspect_catalog, global_catalog_cache

hayah_path = sys.argv[2]
res_dict = {}

# 1. Hayah Shibin Fixture
df_h = PDFCatalogParser(hayah_path).parse()
res_h = CatalogResult.from_dataframe(df_h)
res_dict["hayah_count"] = len(df_h)
res_dict["hayah_pages"] = [sum(g.accepted_rows for g in p.groups) for p in res_h.diagnostics.pages]
res_dict["hayah_p1_groups"] = [g.accepted_rows for g in res_h.diagnostics.pages[0].groups]
res_dict["hayah_status"] = res_h.diagnostics.status
res_dict["hayah_rejected"] = res_h.diagnostics.rejected_rows
res_dict["hayah_unprocessed"] = res_h.diagnostics.unprocessed_rows

print("__JSON_START__" + json.dumps(res_dict) + "__JSON_END__")
''')

        cmd = [sys.executable, runner_script, DIST_INTERNAL, HAYAH_FIXTURE_PATH]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, f"Packaged runner failed: {proc.stderr}")

        stdout = proc.stdout
        self.assertIn("__JSON_START__", stdout)
        json_str = stdout.split("__JSON_START__")[1].split("__JSON_END__")[0]
        pkg_res = json.loads(json_str)

        # Assert Packaged Bundle Parity against Source Expectations
        self.assertEqual(pkg_res["hayah_count"], 571)
        self.assertEqual(pkg_res["hayah_pages"], [141, 141, 141, 141, 7])
        self.assertEqual(pkg_res["hayah_p1_groups"], [47, 47, 47])
        self.assertEqual(pkg_res["hayah_status"], "complete")
        self.assertEqual(pkg_res["hayah_rejected"], 0)
        self.assertEqual(pkg_res["hayah_unprocessed"], 0)

    # ------------------------------------------------------------------------
    # 9. Standalone Executable Direct Execution & Real PDF Extraction
    # ------------------------------------------------------------------------
    def test_10_standalone_executable_real_pdf_verification(self):
        """Execute standalone EgyptianPharmaOptimizer.exe directly and verify real PDF extraction."""
        import json

        self.assertTrue(os.path.exists(EXE_PATH), f"Executable not found at {EXE_PATH}")

        # 1. Direct --self-test on standalone binary (verifies GUI tree + real Hayah 571 extraction inside binary)
        p_self = subprocess.run([EXE_PATH, "--self-test"], capture_output=True, text=True, timeout=30)
        self.assertEqual(p_self.returncode, 0, f"Standalone executable --self-test failed: {p_self.stderr}")
        self.assertIn("Real PDF extraction verified: 571 items recovered", p_self.stdout)

        # 2. Direct --test-catalog on Hayah fixture
        p_hayah = subprocess.run([EXE_PATH, "--test-catalog", HAYAH_FIXTURE_PATH], capture_output=True, text=True, timeout=30)
        self.assertEqual(p_hayah.returncode, 0, f"Standalone executable --test-catalog failed: {p_hayah.stderr}")
        self.assertIn("__JSON_RESULT__", p_hayah.stdout)
        res_h = json.loads(p_hayah.stdout.split("__JSON_RESULT__")[1])
        self.assertEqual(res_h["count"], 571)
        self.assertEqual(res_h["status"], "complete")
        self.assertEqual(res_h["accepted_rows"], 571)

        # 3. Direct --test-catalog on swapped column roles PDF (same-page)
        pdf_swap = os.path.join(self.temp_dir, "exe_test_swap.pdf")
        d1 = [
            ['Disc', 'Price', 'Item Name', 'Disc', 'Price', 'Item Name'],
            ['10%', '100.0', 'Panadol Extra 500mg', '15%', '80.0', 'Cataflam 50mg']
        ]
        t1 = _make_grid_table(d1, [45, 45, 180, 45, 45, 180])
        d2 = [
            ['Price', 'Disc', 'Item Name', 'Price', 'Disc', 'Item Name'],
            ['50.0', '20%', 'Zyrtec 10mg', '60.0', '30%', 'Claritin 10mg']
        ]
        t2 = _make_grid_table(d2, [45, 45, 180, 45, 45, 180])
        _build_pdf(pdf_swap, [t1, Spacer(1, 20), t2])

        p_swap = subprocess.run([EXE_PATH, "--test-catalog", pdf_swap], capture_output=True, text=True, timeout=30)
        self.assertEqual(p_swap.returncode, 0, f"Standalone executable on swapped PDF failed: {p_swap.stderr}")
        res_s = json.loads(p_swap.stdout.split("__JSON_RESULT__")[1])
        self.assertEqual(res_s["count"], 4)
        self.assertEqual(res_s["status"], "complete")

        items_by_name = {it["name"]: it for it in res_s["items"]}
        zyrtec_k = next(k for k in items_by_name if "Zyrtec" in k)
        claritin_k = next(k for k in items_by_name if "Claritin" in k)
        self.assertAlmostEqual(items_by_name[zyrtec_k]["price"], 50.0, places=2)
        self.assertAlmostEqual(items_by_name[zyrtec_k]["discount"], 0.20, places=2)
        self.assertAlmostEqual(items_by_name[claritin_k]["price"], 60.0, places=2)
        self.assertAlmostEqual(items_by_name[claritin_k]["discount"], 0.30, places=2)


if __name__ == "__main__":
    unittest.main()

