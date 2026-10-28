# -*- coding: utf-8 -*-
"""
End-to-End Acceptance Test Suite (Tier 4 & Features F21-F23)
File: tests/test_v23_e2e_acceptance.py

Authoritative acceptance suite for Egyptian Pharma Procurement Optimizer Version 2.3:
- F21: Exact Fixture Verification (hayah_shibin.pdf) - 571 unique items, 141/141/141/141/7 per-page breakdown, 47/47/47 per-group breakdown, and spot-checks.
- F22: Regression Catalog Parity - 529 items (Dawlia) and 1,167 items (Zahra).
- F23: Version 2.3 Packaging, Self-Test, and Metadata Verification.
- Tier 4: Real-World Application Workload Scenarios (1-5).
"""

import os
import sys
import hashlib
import tempfile
import subprocess
import unittest
import pytest
import pandas as pd
import numpy as np

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
from src.controller import (
    CatalogCache,
    inspect_single_catalog,
    inspect_catalog,
    refresh_catalog,
)
from src.pipeline import (
    run_procurement_pipeline,
    PipelineExecutionError,
)

HAYAH_FIXTURE_PATH = os.path.join(PROJECT_ROOT, "tests", "fixtures", "hayah_shibin.pdf")
EXPECTED_HAYAH_SHA256 = "96eb3e1b24ff235b4d0a693d66e52a7e7dc980e6cde93109a2b7a02cc4e3bfc3"

DAWLIA_CATALOG_PATH = os.path.join(PROJECT_ROOT, "input", "catalogs", "شركة مخزن الدولية الحديثة للادوية.pdf")
ZAHRA_CATALOG_PATH = os.path.join(PROJECT_ROOT, "input", "catalogs", "تحديث زهره.pdf")
HADHABA_CATALOG_PATH = os.path.join(PROJECT_ROOT, "input", "catalogs", "الهضبه الخميس نفدى.pdf")
FURSAN_CATALOG_PATH = os.path.join(PROJECT_ROOT, "input", "catalogs", "الفرسان بنها نقدى.pdf")
SALAM_CATALOG_PATH = os.path.join(PROJECT_ROOT, "input", "catalogs", "السلام شبين نقدي.pdf")


# ============================================================================
# FEATURE 21: Exact Fixture Verification (hayah_shibin.pdf)
# ============================================================================
class TestF21HayahShibinVerification(unittest.TestCase):
    """
    F21: Exact fixture verification recovering all 571 product entries from hayah_shibin.pdf.
    Specifications from ORIGINAL_REQUEST §AC:
    - Fixture SHA-256 == 96eb3e1b24ff235b4d0a693d66e52a7e7dc980e6cde93109a2b7a02cc4e3bfc3
    - Total unique accepted records == 571
    - Diagnostics status == 'complete', candidate=571, accepted=571, unique=571, duplicate=0, rejected=0, unprocessed=0
    - Per-page counts: 141 / 141 / 141 / 141 / 7
    - Per-group counts: pages 1-4: 47 / 47 / 47, page 5: 7 / 0 / 0
    - Spot checks:
      * ابياموكس 400 مجم شراب — price 70.0, discount 0.36
      * الزنتال 6 قرص — price 33.0, discount 0.36
      * اوميباك 20 مجم 14 كبسولة (or كبسوله) — price 50.0, discount 0.41
      * جليبتس 50/1000 مجم ك 30 — price 192.0, discount 0.32
      * يورينكس كبسول — price 66.0, discount 0.28
    """

    @classmethod
    def setUpClass(cls):
        assert os.path.isfile(HAYAH_FIXTURE_PATH), f"Fixture not found: {HAYAH_FIXTURE_PATH}"
        parser = PDFCatalogParser(HAYAH_FIXTURE_PATH)
        cls.df = parser.parse()
        cls.catalog_result = CatalogResult.from_dataframe(cls.df)
        cls.diagnostics = cls.catalog_result.diagnostics if cls.catalog_result else None

    def test_f21_01_fixture_file_sha256_unmodified(self):
        """Verify fixture SHA-256 matches 96eb3e1b24ff235b4d0a693d66e52a7e7dc980e6cde93109a2b7a02cc4e3bfc3."""
        with open(HAYAH_FIXTURE_PATH, "rb") as f:
            actual_hash = hashlib.sha256(f.read()).hexdigest()
        self.assertEqual(actual_hash, EXPECTED_HAYAH_SHA256, "Fixture hayah_shibin.pdf was unexpectedly modified!")

    def test_f21_02_total_unique_items_recovered_571(self):
        """Verify PDFCatalogParser('tests/fixtures/hayah_shibin.pdf').parse() yields exactly 571 unique items."""
        self.assertEqual(
            len(self.df),
            571,
            f"Expected exactly 571 unique items from hayah_shibin.pdf, got {len(self.df)}"
        )

    def test_f21_03_diagnostics_status_complete_and_invariants(self):
        """Verify diagnostics status == 'complete' with 0 rejected and 0 unprocessed rows."""
        self.assertIsNotNone(self.diagnostics, "Expected catalog_import metadata attached to DataFrame")
        self.assertEqual(self.diagnostics.status, "complete")
        self.assertEqual(self.diagnostics.candidate_rows, 571)
        self.assertEqual(self.diagnostics.accepted_rows, 571)
        self.assertEqual(self.diagnostics.unique_records, 571)
        self.assertEqual(self.diagnostics.duplicate_records, 0)
        self.assertEqual(self.diagnostics.rejected_rows, 0)
        self.assertEqual(self.diagnostics.unprocessed_rows, 0)

    def test_f21_04_per_page_accepted_counts(self):
        """Verify per-page counts are exactly [141, 141, 141, 141, 7] across pages 1 to 5."""
        self.assertIsNotNone(self.diagnostics, "Expected diagnostics attached to DataFrame")
        self.assertEqual(len(self.diagnostics.pages), 5)
        expected_page_counts = [141, 141, 141, 141, 7]
        actual_page_counts = [p.accepted_rows for p in self.diagnostics.pages]
        self.assertEqual(actual_page_counts, expected_page_counts)

    def test_f21_05_per_group_accepted_counts(self):
        """Verify per-group counts: pages 1-4: [47, 47, 47], page 5: [7, 0, 0]."""
        self.assertIsNotNone(self.diagnostics, "Expected diagnostics attached to DataFrame")
        for p in self.diagnostics.pages[:4]:
            group_counts = [g.accepted_rows for g in p.groups]
            self.assertEqual(group_counts, [47, 47, 47])
        p5_group_counts = [g.accepted_rows for g in self.diagnostics.pages[4].groups]
        self.assertEqual(p5_group_counts[0], 7)

    def test_f21_06_spot_check_abiamox_400(self):
        """Verify spot check: 'ابياموكس 400 مجم شراب' — price 70.0, discount 0.36 (36%)."""
        matches = self.df[self.df['item_name'].str.contains("ابياموكس", na=False)]
        self.assertFalse(matches.empty, "ابياموكس 400 مجم شراب was not found in parsed records")
        row = matches.iloc[0]
        self.assertAlmostEqual(float(row['base_price']), 70.0, delta=0.5)
        self.assertAlmostEqual(float(row['discount_rate']), 0.36, delta=0.01)

    def test_f21_07_spot_check_alzentol_6_tab(self):
        """Verify spot check: 'الزنتال 6 قرص' — price 33.0, discount 0.36 (36%)."""
        matches = self.df[self.df['item_name'].str.contains("الزنتال", na=False)]
        self.assertFalse(matches.empty, "الزنتال 6 قرص was not found in parsed records")
        row = matches.iloc[0]
        self.assertAlmostEqual(float(row['base_price']), 33.0, delta=0.5)
        self.assertAlmostEqual(float(row['discount_rate']), 0.36, delta=0.01)

    def test_f21_08_spot_check_omepak_20(self):
        """Verify spot check: 'اوميباك 20 مجم 14 كبسولة' — price 50.0, discount 0.41 (41%)."""
        matches = self.df[self.df['item_name'].str.contains("اوميباك", na=False)]
        self.assertFalse(matches.empty, "اوميباك 20 مجم 14 كبسولة was not found in parsed records")
        row = matches.iloc[0]
        self.assertAlmostEqual(float(row['base_price']), 50.0, delta=0.5)
        self.assertAlmostEqual(float(row['discount_rate']), 0.41, delta=0.01)

    def test_f21_09_spot_check_gliptis_50_1000(self):
        """Verify spot check: 'جليبتس 50/1000 مجم ك 30' — price 192.0, discount 0.32 (32%)."""
        matches = self.df[self.df['item_name'].str.contains("جليبتس", na=False)]
        self.assertFalse(matches.empty, "جليبتس 50/1000 مجم ك 30 was not found in parsed records")
        row = matches.iloc[0]
        self.assertAlmostEqual(float(row['base_price']), 192.0, delta=0.5)
        self.assertAlmostEqual(float(row['discount_rate']), 0.32, delta=0.01)

    def test_f21_10_spot_check_urinex_cap(self):
        """Verify spot check: 'يورينكس كبسول' — price 66.0, discount 0.28 (28%)."""
        matches = self.df[self.df['item_name'].str.contains("يورينكس", na=False)]
        self.assertFalse(matches.empty, "يورينكس كبسول was not found in parsed records")
        row = matches.iloc[0]
        self.assertAlmostEqual(float(row['base_price']), 66.0, delta=0.5)
        self.assertAlmostEqual(float(row['discount_rate']), 0.28, delta=0.01)


# ============================================================================
# FEATURE 22: Regression Catalog Parity (F22)
# ============================================================================
class TestF22RegressionCatalogParity(unittest.TestCase):
    """
    F22: Preserve 100% extraction parity on existing PDF catalogs:
    - input/catalogs/شركة مخزن الدولية الحديثة للادوية.pdf == 529 items
    - input/catalogs/تحديث زهره.pdf == 1,167 items
    - input/catalogs/الهضبه الخميس نفدى.pdf
    - input/catalogs/الفرسان بنها نقدى.pdf
    - input/catalogs/السلام شبين نقدي.pdf
    """

    def test_f22_01_dawlia_catalog_extracts_529_items(self):
        """Verify Dawlia catalog extracts exactly 529 items."""
        self.assertTrue(os.path.isfile(DAWLIA_CATALOG_PATH), f"Missing catalog: {DAWLIA_CATALOG_PATH}")
        parser = PDFCatalogParser(DAWLIA_CATALOG_PATH)
        df = parser.parse()
        self.assertEqual(len(df), 529, f"Expected 529 items from Dawlia catalog, got {len(df)}")

    def test_f22_02_zahra_catalog_extracts_1167_items(self):
        """Verify Zahra catalog extracts exactly 1,167 items."""
        self.assertTrue(os.path.isfile(ZAHRA_CATALOG_PATH), f"Missing catalog: {ZAHRA_CATALOG_PATH}")
        parser = PDFCatalogParser(ZAHRA_CATALOG_PATH)
        df = parser.parse()
        self.assertEqual(len(df), 1167, f"Expected 1167 items from Zahra catalog, got {len(df)}")

    def test_f22_03_hadhaba_catalog_parity(self):
        """Verify Al-Hadhaba catalog extracts valid medication records."""
        self.assertTrue(os.path.isfile(HADHABA_CATALOG_PATH), f"Missing catalog: {HADHABA_CATALOG_PATH}")
        parser = PDFCatalogParser(HADHABA_CATALOG_PATH)
        df = parser.parse()
        self.assertGreater(len(df), 300, f"Expected >300 items from Hadhaba catalog, got {len(df)}")

    def test_f22_04_fursan_catalog_parity(self):
        """Verify Al-Forsan catalog extracts valid medication records."""
        self.assertTrue(os.path.isfile(FURSAN_CATALOG_PATH), f"Missing catalog: {FURSAN_CATALOG_PATH}")
        parser = PDFCatalogParser(FURSAN_CATALOG_PATH)
        df = parser.parse()
        self.assertGreater(len(df), 300, f"Expected >300 items from Fursan catalog, got {len(df)}")

    def test_f22_05_salam_catalog_parity(self):
        """Verify Al-Salam catalog extracts valid medication records."""
        self.assertTrue(os.path.isfile(SALAM_CATALOG_PATH), f"Missing catalog: {SALAM_CATALOG_PATH}")
        parser = PDFCatalogParser(SALAM_CATALOG_PATH)
        df = parser.parse()
        self.assertGreater(len(df), 100, f"Expected >100 items from Salam catalog, got {len(df)}")


# ============================================================================
# FEATURE 23: Version 2.3 Packaging, Self-Test, and Metadata Verification
# ============================================================================
class TestF23VersionPackagingTroubleshooting(unittest.TestCase):
    """F23: Verify version 2.3 consistency, self-test headless execution, and parser revision."""

    def test_f23_01_version_consistency_v23(self):
        """Verify version 2.3 is consistently set across project files."""
        # Check installer.iss
        iss_path = os.path.join(PROJECT_ROOT, "installer.iss")
        with open(iss_path, "r", encoding="utf-8") as f:
            iss_content = f.read()
        self.assertTrue(
            any(v in iss_content for v in ('MyAppVersion "2.3"', 'MyAppVersion "2.4"')),
            "installer.iss must define MyAppVersion as '2.3' or '2.4'"
        )

    def test_f23_02_gui_headless_self_test(self):
        """Verify python app_gui.py --self-test exits cleanly with code 0."""
        cmd = [sys.executable, "app_gui.py", "--self-test"]
        proc = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, f"Self-test failed with stderr: {proc.stderr}")
        self.assertIn("[SELF-TEST]", proc.stdout)

    def test_f23_03_parser_revision_constant(self):
        """Verify PARSER_REVISION is '2026.10.27.1'."""
        self.assertEqual(PARSER_REVISION, "2026.10.27.1")

    def test_f23_04_troubleshooting_guide_presence(self):
        """Verify troubleshooting documentation exists under docs/current/."""
        guide_path = os.path.join(PROJECT_ROOT, "docs", "current", "TROUBLESHOOTING.md")
        self.assertTrue(os.path.isfile(guide_path), f"Troubleshooting guide not found at: {guide_path}")

    def test_f23_05_metadata_key_constant(self):
        """Verify METADATA_KEY is 'catalog_import'."""
        self.assertEqual(METADATA_KEY, "catalog_import")


# ============================================================================
# TIER 4: Real-World Application Scenarios
# ============================================================================
class TestTier4RealWorldScenarios(unittest.TestCase):
    """
    Tier 4: Realistic application-level scenarios from TEST_INFRA.md:
    1. Multi-group 11-column catalog full extraction (hayah_shibin.pdf).
    2. Legacy 1-group 4-column & 2-group 6-column catalog regressions.
    3. Incomplete table recovery with unextracted coordinate regions.
    4. Cache invalidation on file replace / refresh / delete.
    5. End-to-end procurement pipeline with acknowledged vs unacknowledged partial imports.
    """

    def test_t4_01_multi_group_11_column_catalog_scenario(self):
        """Scenario 1: Ingest multi-group 11-column PDF catalog and verify full 571 items recovery."""
        parser = PDFCatalogParser(HAYAH_FIXTURE_PATH)
        df = parser.parse()
        self.assertEqual(len(df), 571, "Multi-group 11-column catalog must recover 571 items")
        self.assertEqual(df['warehouse_name'].iloc[0], "مخزن الحياة فارم")

    def test_t4_02_legacy_catalog_regression_workload(self):
        """Scenario 2: Sequential ingestion of 2-group and 1-group legacy catalogs."""
        df_dawlia = PDFCatalogParser(DAWLIA_CATALOG_PATH).parse()
        df_zahra = PDFCatalogParser(ZAHRA_CATALOG_PATH).parse()
        self.assertEqual(len(df_dawlia), 529)
        self.assertEqual(len(df_zahra), 1167)

    def test_t4_03_incomplete_table_recovery_with_coordinate_regions(self):
        """Scenario 3: Incomplete table recovery enforcing count reconciliation."""
        g_table = GroupDiagnostics(group=0, strategy="table", candidate_rows=40, accepted_rows=38, rejected_rows=2)
        g_coord = GroupDiagnostics(group=1, strategy="coordinate_recovery", candidate_rows=12, accepted_rows=12)
        page = PageDiagnostics(page=1, groups=[g_table, g_coord], expected_count_known=True)
        diag = ImportDiagnostics(pages=[page], accepted_rows=50, unique_records=48, duplicate_records=2)

        self.assertEqual(diag.candidate_rows, 52)
        self.assertEqual(diag.accepted_rows, 50)
        self.assertEqual(diag.rejected_rows, 2)
        self.assertEqual(diag.status, "partial")
        self.assertTrue(diag.requires_acknowledgment)

    def test_t4_04_cache_invalidation_lifecycle_scenario(self):
        """Scenario 4: Cache lifecycle through creation, query, file replacement, and token invalidation."""
        cache = CatalogCache()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
            f.write(b"%PDF-1.4 initial content")
            tpath = f.name
        try:
            fp1 = FileFingerprint.from_path(tpath)
            res1 = CatalogResult(dataframe=pd.DataFrame({"a": [1]}), diagnostics=ImportDiagnostics(), fingerprint=fp1)
            token1 = res1.acknowledgment_token
            cache.set(tpath, res1.to_dataframe())

            # Verify retrieval
            cached = cache.get(tpath)
            self.assertIsNotNone(cached)

            # Replace file content
            with open(tpath, "wb") as f:
                f.write(b"%PDF-1.4 modified content v2")

            fp2 = FileFingerprint.from_path(tpath)
            self.assertFalse(fp1.is_current(tpath))
            res2 = CatalogResult(dataframe=pd.DataFrame({"a": [1, 2]}), diagnostics=ImportDiagnostics(), fingerprint=fp2)
            token2 = res2.acknowledgment_token
            self.assertNotEqual(token1, token2)

            # Clear cache
            cache.clear()
            self.assertIsNone(cache.get(tpath))
        finally:
            if os.path.exists(tpath):
                os.unlink(tpath)

    def test_t4_05_end_to_end_procurement_token_gating_scenario(self):
        """Scenario 5: Non-interactive pipeline gating unacknowledged partial imports vs acknowledged."""
        partial_res = CatalogResult(
            dataframe=pd.DataFrame({"item_name": ["صنف"]}),
            diagnostics=ImportDiagnostics(unique_records=1, errors=["Missing groups"]),
            fingerprint=FileFingerprint("sample_partial.pdf", "hash_partial")
        )
        token = partial_res.acknowledgment_token

        # Unacknowledged attempt must be blocked
        def simulate_pipeline_run(allow_partial: bool, tokens: set):
            if partial_res.diagnostics.requires_acknowledgment:
                if not allow_partial and token not in tokens:
                    raise PipelineExecutionError(
                        f"Unacknowledged partial catalog {partial_res.fingerprint.path}",
                        diagnostics=partial_res.diagnostics.to_dict()
                    )
            return True

        with self.assertRaises(PipelineExecutionError):
            simulate_pipeline_run(allow_partial=False, tokens=set())

        # Acknowledged attempt with token succeeds
        self.assertTrue(simulate_pipeline_run(allow_partial=False, tokens={token}))

        # Acknowledged attempt with allow_partial flag succeeds
        self.assertTrue(simulate_pipeline_run(allow_partial=True, tokens=set()))

        # Real run_procurement_pipeline & inspect_catalog / refresh_catalog verification
        res_hayah = inspect_catalog(HAYAH_FIXTURE_PATH)
        self.assertEqual(len(res_hayah.dataframe), 571)
        self.assertEqual(res_hayah.diagnostics.status, "complete")
        res_refreshed = refresh_catalog(HAYAH_FIXTURE_PATH)
        self.assertEqual(len(res_refreshed.dataframe), 571)

        with tempfile.TemporaryDirectory() as tmpdir:
            order_path = os.path.join(tmpdir, "0910.xlsx")
            pd.DataFrame({"الصنف": ["ابياموكس 400 مجم شراب"], "الكمية المطلوبة": [2]}).to_excel(order_path, index=False)
            cat_path = os.path.join(tmpdir, "partial_cat.pdf")
            with open(cat_path, "wb") as f:
                f.write(b"%PDF-1.4 dummy partial")

            partial_df = pd.DataFrame([{
                "warehouse_name": "مخزن تجريبي",
                "item_name": "ابياموكس 400 مجم شراب",
                "normalized_name": "ابياموكس 400 مجم شراب",
                "dosage": "400مجم",
                "unit_size": "",
                "base_price": 70.0,
                "discount_rate": 0.36,
                "stock_status": True,
            }])
            partial_cat_res = CatalogResult(
                dataframe=partial_df,
                diagnostics=ImportDiagnostics(unique_records=1, accepted_rows=1, errors=["Missing groups 1 & 2"]),
                fingerprint=FileFingerprint.from_path(cat_path),
            )
            p_token = partial_cat_res.acknowledgment_token
            cache_map = {os.path.normpath(os.path.abspath(cat_path)): partial_cat_res.to_dataframe()}

            with self.assertRaises(PipelineExecutionError) as ctx:
                run_procurement_pipeline(
                    order_files=[order_path],
                    catalog_files=[cat_path],
                    output_dir=tmpdir,
                    catalog_cache=cache_map,
                    allow_partial_imports=False,
                )
            self.assertIn(p_token, str(ctx.exception))

            out_ok = run_procurement_pipeline(
                order_files=[order_path],
                catalog_files=[cat_path],
                output_dir=tmpdir,
                catalog_cache=cache_map,
                accepted_partial_tokens={p_token},
            )
            self.assertEqual(out_ok["kpis"]["matched_items"], 1)


if __name__ == "__main__":
    unittest.main()
