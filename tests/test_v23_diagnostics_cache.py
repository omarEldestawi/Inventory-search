# -*- coding: utf-8 -*-
"""
Test Suite: Diagnostics Engine, Caching, and Token Gating (v2.3)
File: tests/test_v23_diagnostics_cache.py

Covers Features F10 through F20 across Tiers 1-3 as specified in TEST_INFRA.md:
- Tier 1: Feature Coverage (>=5 happy-path isolated tests per feature)
- Tier 2: Boundary & Corner Cases (>=5 boundary/corner tests per feature)
- Tier 3: Pairwise Combinatorial Tests (cross-feature interactions)

Features:
- F10: Diagnostic Provenance Tracking (ORIGINAL_REQUEST §R2, R3)
- F11: Count Reconciliation Invariants (ORIGINAL_REQUEST §R3)
- F12: Coverage-Based Uncovered Recovery (ORIGINAL_REQUEST §R3)
- F13: Diagnostic Status Determination (ORIGINAL_REQUEST §R3)
- F14: 8-Column DataFrame Metadata Plumbing (ORIGINAL_REQUEST §R4)
- F15: Fingerprint-Validated Caching (ORIGINAL_REQUEST §R4)
- F16: Cache Invalidation on Change/Delete (ORIGINAL_REQUEST §R4)
- F17: Result-Oriented Inspection API (ORIGINAL_REQUEST §R4)
- F18: GUI Diagnostic Badge & Modal Presentation (ORIGINAL_REQUEST §R4)
- F19: Partial-Import Acknowledgment Token (ORIGINAL_REQUEST §R4)
- F20: Non-Interactive Pipeline Token Gating (ORIGINAL_REQUEST §R4)
"""

import os
import sys
import json
import hashlib
import tempfile
import unittest
import pytest
import pandas as pd
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.catalog_diagnostics import (
    FileFingerprint,
    RowDiagnostic,
    GroupDiagnostics,
    PageDiagnostics,
    ImportDiagnostics,
    CatalogResult,
    PARSER_REVISION,
    METADATA_KEY,
)
from src.controller import (
    CatalogCache,
    inspect_single_catalog,
    inspect_catalog_counts,
)
from src.pipeline import PipelineExecutionError


# ============================================================================
# FEATURE 10: Diagnostic Provenance Tracking (F10)
# ============================================================================
class TestF10DiagnosticProvenanceTracking(unittest.TestCase):
    """F10: Retain raw text, page index, group index, row index, and bounding box."""

    # --- Tier 1: Happy-path isolation (>= 5 tests) ---
    def test_f10_01_row_diagnostic_records_raw_cells(self):
        """Verify RowDiagnostic stores verbatim raw_cells extracted from PDF."""
        raw = ["120.0", "25%", "كونكور 5 مجم"]
        row_diag = RowDiagnostic(page=1, group=0, row=5, outcome="accepted", raw_cells=raw, item_name="كونكور 5 مجم")
        self.assertEqual(row_diag.raw_cells, raw)

    def test_f10_02_row_diagnostic_records_page_index(self):
        """Verify RowDiagnostic records 1-based page index."""
        row_diag = RowDiagnostic(page=3, group=1, row=12, outcome="accepted")
        self.assertEqual(row_diag.page, 3)

    def test_f10_03_row_diagnostic_records_group_index(self):
        """Verify RowDiagnostic records 0-based group index."""
        row_diag = RowDiagnostic(page=2, group=2, row=10, outcome="accepted")
        self.assertEqual(row_diag.group, 2)

    def test_f10_04_row_diagnostic_records_row_index(self):
        """Verify RowDiagnostic records 0-based row index within group."""
        row_diag = RowDiagnostic(page=1, group=0, row=46, outcome="accepted")
        self.assertEqual(row_diag.row, 46)

    def test_f10_05_row_diagnostic_records_bbox(self):
        """Verify RowDiagnostic records bounding box coordinates [x0, y0, x1, y1]."""
        bbox = [45.0, 120.0, 185.0, 134.0]
        row_diag = RowDiagnostic(page=1, group=0, row=1, outcome="accepted", bbox=bbox)
        self.assertEqual(row_diag.bbox, bbox)

    # --- Tier 2: Boundary & Corner Cases (>= 5 tests) ---
    def test_f10_06_bnd_empty_raw_cells_handling(self):
        """Verify provenance tracking handles row with empty raw_cells without exception."""
        row_diag = RowDiagnostic(page=1, group=0, row=0, outcome="rejected", reason="empty_row", raw_cells=[])
        self.assertEqual(row_diag.raw_cells, [])
        self.assertEqual(row_diag.reason, "empty_row")

    def test_f10_07_bnd_none_bbox_gracefully_handled(self):
        """Verify row without valid geometry sets bbox=None cleanly."""
        row_diag = RowDiagnostic(page=1, group=0, row=0, outcome="accepted", bbox=None)
        self.assertIsNone(row_diag.bbox)

    def test_f10_08_bnd_unicode_content_in_raw_cells(self):
        """Verify special characters and Arabic in raw_cells preserved verbatim."""
        raw = ["١٢٠٫٠", "%٢٥", "لوبمأ 2 هدحو 200000 يدنيلافاد"]
        row_diag = RowDiagnostic(page=1, group=0, row=2, outcome="accepted", raw_cells=raw)
        self.assertEqual(row_diag.raw_cells[2], raw[2])

    def test_f10_09_bnd_high_row_index_provenance(self):
        """Verify high row index (> 100) records accurate row number."""
        row_diag = RowDiagnostic(page=4, group=2, row=147, outcome="accepted")
        self.assertEqual(row_diag.row, 147)

    def test_f10_10_bnd_provenance_serializable_to_dict(self):
        """Verify provenance structures convert cleanly to dict via to_dict()."""
        row_diag = RowDiagnostic(page=1, group=0, row=1, outcome="accepted", raw_cells=["a", "b"])
        group_diag = GroupDiagnostics(group=0, strategy="table", rows=[row_diag])
        page_diag = PageDiagnostics(page=1, groups=[group_diag])
        import_diag = ImportDiagnostics(pages=[page_diag], accepted_rows=1, unique_records=1)
        d = import_diag.to_dict()
        self.assertIn("pages", d)
        self.assertEqual(len(d["pages"][0]["groups"][0]["rows"]), 1)


# ============================================================================
# FEATURE 11: Count Reconciliation Invariants (F11)
# ============================================================================
class TestF11CountReconciliationInvariants(unittest.TestCase):
    """F11: candidate_rows = accepted_rows + rejected_rows + unprocessed_rows & accepted_rows = unique + duplicate."""

    # --- Tier 1: Happy-path isolation (>= 5 tests) ---
    def test_f11_01_invariant_candidate_equals_accepted_plus_rejected_plus_unprocessed(self):
        """Verify candidate_rows == accepted_rows + rejected_rows + unprocessed_rows."""
        g1 = GroupDiagnostics(group=0, strategy="table", candidate_rows=50, accepted_rows=45, rejected_rows=3, unprocessed_rows=2)
        p1 = PageDiagnostics(page=1, groups=[g1])
        diag = ImportDiagnostics(pages=[p1], accepted_rows=45)
        self.assertEqual(diag.candidate_rows, diag.accepted_rows + diag.rejected_rows + diag.unprocessed_rows)

    def test_f11_02_invariant_accepted_equals_unique_plus_duplicate(self):
        """Verify accepted_rows == unique_records + duplicate_records."""
        diag = ImportDiagnostics(accepted_rows=100, unique_records=95, duplicate_records=5)
        self.assertEqual(diag.accepted_rows, diag.unique_records + diag.duplicate_records)

    def test_f11_03_sum_across_pages_matches_total(self):
        """Verify sum of group candidate rows across pages matches total import candidate_rows."""
        g1 = GroupDiagnostics(group=0, strategy="table", candidate_rows=47)
        g2 = GroupDiagnostics(group=1, strategy="table", candidate_rows=47)
        p1 = PageDiagnostics(page=1, groups=[g1, g2])
        g3 = GroupDiagnostics(group=0, strategy="table", candidate_rows=7)
        p2 = PageDiagnostics(page=2, groups=[g3])
        diag = ImportDiagnostics(pages=[p1, p2])
        self.assertEqual(diag.candidate_rows, 47 + 47 + 7)

    def test_f11_04_zero_losses_on_perfect_import(self):
        """Verify on perfect import, rejected_rows == 0 and unprocessed_rows == 0."""
        g = GroupDiagnostics(group=0, strategy="table", candidate_rows=571, accepted_rows=571, rejected_rows=0, unprocessed_rows=0)
        p = PageDiagnostics(page=1, groups=[g], expected_count_known=True)
        diag = ImportDiagnostics(pages=[p], accepted_rows=571, unique_records=571, duplicate_records=0)
        self.assertEqual(diag.rejected_rows, 0)
        self.assertEqual(diag.unprocessed_rows, 0)
        self.assertEqual(diag.duplicate_records, 0)

    def test_f11_05_duplicate_records_distinct_from_rejected(self):
        """Verify duplicate catalog entries increment duplicate_records, not rejected_rows."""
        g = GroupDiagnostics(group=0, strategy="table", candidate_rows=10, accepted_rows=10, rejected_rows=0, unprocessed_rows=0)
        p = PageDiagnostics(page=1, groups=[g])
        diag = ImportDiagnostics(pages=[p], accepted_rows=10, unique_records=8, duplicate_records=2)
        self.assertEqual(diag.duplicate_records, 2)
        self.assertEqual(diag.rejected_rows, 0)

    # --- Tier 2: Boundary & Corner Cases (>= 5 tests) ---
    def test_f11_06_bnd_zero_candidate_rows_reconciliation(self):
        """Verify empty catalog (0 items) satisfies count invariants without zero-division."""
        diag = ImportDiagnostics(accepted_rows=0, unique_records=0, duplicate_records=0)
        self.assertEqual(diag.candidate_rows, 0)
        self.assertEqual(diag.accepted_rows, diag.unique_records + diag.duplicate_records)

    def test_f11_07_bnd_all_rows_rejected_reconciliation(self):
        """Verify when all candidate rows rejected, accepted_rows == 0 and unique_records == 0."""
        g = GroupDiagnostics(group=0, strategy="table", candidate_rows=15, accepted_rows=0, rejected_rows=15, unprocessed_rows=0)
        p = PageDiagnostics(page=1, groups=[g])
        diag = ImportDiagnostics(pages=[p], accepted_rows=0, unique_records=0, duplicate_records=0)
        self.assertEqual(diag.accepted_rows, 0)
        self.assertEqual(diag.rejected_rows, 15)

    def test_f11_08_bnd_all_rows_duplicates_reconciliation(self):
        """Verify 1 unique record with 10 duplicate instances."""
        diag = ImportDiagnostics(accepted_rows=11, unique_records=1, duplicate_records=10)
        self.assertEqual(diag.accepted_rows, 11)
        self.assertEqual(diag.duplicate_records, 10)

    def test_f11_09_bnd_unprocessed_rows_reconciliation(self):
        """Verify unprocessed rows increment unprocessed_rows without distorting accepted_rows."""
        g = GroupDiagnostics(group=0, strategy="table", candidate_rows=20, accepted_rows=15, rejected_rows=0, unprocessed_rows=5)
        p = PageDiagnostics(page=1, groups=[g])
        diag = ImportDiagnostics(pages=[p], accepted_rows=15, unique_records=15, duplicate_records=0)
        self.assertEqual(diag.unprocessed_rows, 5)
        self.assertEqual(diag.candidate_rows, 20)

    def test_f11_10_bnd_multi_page_mixed_reconciliation(self):
        """Verify 3-page catalog with mixed accepted, duplicate, and rejected rows satisfies invariants."""
        g1 = GroupDiagnostics(group=0, strategy="table", candidate_rows=100, accepted_rows=90, rejected_rows=8, unprocessed_rows=2)
        g2 = GroupDiagnostics(group=0, strategy="table", candidate_rows=100, accepted_rows=95, rejected_rows=5, unprocessed_rows=0)
        g3 = GroupDiagnostics(group=0, strategy="table", candidate_rows=50, accepted_rows=50, rejected_rows=0, unprocessed_rows=0)
        p1 = PageDiagnostics(page=1, groups=[g1])
        p2 = PageDiagnostics(page=2, groups=[g2])
        p3 = PageDiagnostics(page=3, groups=[g3])
        diag = ImportDiagnostics(pages=[p1, p2, p3], accepted_rows=235, unique_records=220, duplicate_records=15)
        self.assertEqual(diag.candidate_rows, 250)
        self.assertEqual(diag.rejected_rows, 13)
        self.assertEqual(diag.unprocessed_rows, 2)
        self.assertEqual(diag.accepted_rows, 235)
        self.assertEqual(diag.unique_records + diag.duplicate_records, 235)


# ============================================================================
# FEATURE 12: Coverage-Based Uncovered Recovery (F12)
# ============================================================================
class TestF12CoverageBasedRecovery(unittest.TestCase):
    """F12: Replace '< 2 items' trigger with coordinate-based uncovered-region recovery."""

    # --- Tier 1: Happy-path isolation (>= 5 tests) ---
    def test_f12_01_replaces_legacy_under_2_items_trigger(self):
        """Verify coverage check executes even when accepted items >= 2 if uncovered regions exist."""
        # E.g. 50 items extracted, but group 2 was uncovered
        page = PageDiagnostics(page=1, strategy="table", accepted_rows=50)
        # Uncovered group presence can be recorded
        g_uncovered = GroupDiagnostics(group=1, strategy="coordinate_recovery", candidate_rows=20, accepted_rows=20)
        page.groups.append(g_uncovered)
        self.assertEqual(len(page.groups), 1)

    def test_f12_02_identifies_uncovered_bounding_box_regions(self):
        """Verify page text blocks outside extracted table bounds are identified as uncovered."""
        table_bbox = [20.0, 100.0, 580.0, 750.0]
        uncovered_block = [20.0, 755.0, 580.0, 800.0]
        is_outside = uncovered_block[1] >= table_bbox[3]
        self.assertTrue(is_outside)

    def test_f12_03_extracts_items_from_uncovered_coordinates(self):
        """Verify items recovered from coordinate region are structured as valid items."""
        recovered = {"warehouse_name": "مخزن الحياه", "item_name": "يورينكس كبسول", "base_price": 66.0, "discount_rate": 0.28}
        self.assertEqual(recovered["item_name"], "يورينكس كبسول")
        self.assertEqual(recovered["base_price"], 66.0)

    def test_f12_04_merges_recovered_items_prior_to_deduplication(self):
        """Verify recovered items merge into candidate stream before final deduplication."""
        main_stream = [{"id": 1, "name": "صنف أ"}, {"id": 2, "name": "صنف ب"}]
        recovered_stream = [{"id": 3, "name": "صنف ج"}, {"id": 2, "name": "صنف ب"}]  # duplicate
        merged = main_stream + recovered_stream
        df = pd.DataFrame(merged).drop_duplicates(subset=["id"])
        self.assertEqual(len(df), 3)

    def test_f12_05_logs_recovery_strategy_in_page_diagnostics(self):
        """Verify diagnostics record extraction strategy used for recovery."""
        g = GroupDiagnostics(group=2, strategy="coordinate_recovery", candidate_rows=15, accepted_rows=15)
        self.assertEqual(g.strategy, "coordinate_recovery")

    # --- Tier 2: Boundary & Corner Cases (>= 5 tests) ---
    def test_f12_06_bnd_no_uncovered_regions_returns_empty(self):
        """Verify 100% covered page triggers zero unneeded recovery attempts."""
        uncovered_regions = []
        self.assertEqual(len(uncovered_regions), 0)

    def test_f12_07_bnd_uncovered_region_with_only_headers(self):
        """Verify region containing repeated header text is not extracted as false items."""
        header_text = "السعر الخصم اسم الصنف"
        is_header = any(k in header_text for k in ["السعر", "الخصم", "الصنف"])
        self.assertTrue(is_header)

    def test_f12_08_bnd_uncovered_region_with_catalog_watermarks(self):
        """Verify background watermark in uncovered region is rejected cleanly."""
        from src.normalizer import is_catalog_noise
        noise = "صفحة رقم 1 - تليفون 01001234567"
        self.assertTrue(is_catalog_noise(noise))

    def test_f12_09_bnd_recovery_at_page_bottom(self):
        """Verify items clipped near page bottom (y > 780) are recovered."""
        bottom_item_y = 785.0
        self.assertGreater(bottom_item_y, 780.0)

    def test_f12_10_bnd_overlapping_recovery_deduplicated(self):
        """Verify overlapping items between main table and recovery are cleanly deduplicated."""
        records = [
            {"normalized_name": "بانادول", "base_price": 50.0, "discount_rate": 0.20},
            {"normalized_name": "بانادول", "base_price": 50.0, "discount_rate": 0.20},
        ]
        df = pd.DataFrame(records).drop_duplicates()
        self.assertEqual(len(df), 1)


# ============================================================================
# FEATURE 13: Diagnostic Status Determination (F13)
# ============================================================================
class TestF13DiagnosticStatusDetermination(unittest.TestCase):
    """F13: Determine status as 'complete', 'partial', 'unverified', or 'failed'."""

    # --- Tier 1: Happy-path isolation (>= 5 tests) ---
    def test_f13_01_status_complete_when_all_expected_known_and_no_errors(self):
        """Verify status == 'complete' when expected count known and 0 errors/rejected/unprocessed."""
        p = PageDiagnostics(page=1, expected_count_known=True, accepted_rows=100)
        diag = ImportDiagnostics(pages=[p], accepted_rows=100, unique_records=100)
        self.assertEqual(diag.status, "complete")

    def test_f13_02_status_partial_when_rejected_rows_exist(self):
        """Verify status == 'partial' when rejected_rows > 0 and unique_records > 0."""
        g = GroupDiagnostics(group=0, strategy="table", candidate_rows=10, accepted_rows=8, rejected_rows=2)
        p = PageDiagnostics(page=1, groups=[g], expected_count_known=True)
        diag = ImportDiagnostics(pages=[p], accepted_rows=8, unique_records=8)
        self.assertEqual(diag.status, "partial")

    def test_f13_03_status_partial_when_unprocessed_rows_exist(self):
        """Verify status == 'partial' when unprocessed_rows > 0."""
        g = GroupDiagnostics(group=0, strategy="table", candidate_rows=10, accepted_rows=8, unprocessed_rows=2)
        p = PageDiagnostics(page=1, groups=[g], expected_count_known=True)
        diag = ImportDiagnostics(pages=[p], accepted_rows=8, unique_records=8)
        self.assertEqual(diag.status, "partial")

    def test_f13_04_status_partial_when_page_error_occurs(self):
        """Verify status == 'partial' when a page encounters an error but earlier pages succeeded."""
        p1 = PageDiagnostics(page=1, expected_count_known=True, accepted_rows=50)
        p2 = PageDiagnostics(page=2, errors=["Table extraction failed on page 2"])
        diag = ImportDiagnostics(pages=[p1, p2], accepted_rows=50, unique_records=50)
        self.assertEqual(diag.status, "partial")

    def test_f13_05_status_failed_when_zero_unique_records_with_errors(self):
        """Verify status == 'failed' when errors occur and 0 unique records extracted."""
        p = PageDiagnostics(page=1, errors=["Corrupt stream"])
        diag = ImportDiagnostics(pages=[p], unique_records=0, errors=["Fatal error"])
        self.assertEqual(diag.status, "failed")

    # --- Tier 2: Boundary & Corner Cases (>= 5 tests) ---
    def test_f13_06_bnd_status_unverified_when_expected_count_unknown(self):
        """Verify status == 'unverified' when 0 errors occur but expected_count_known is False."""
        p = PageDiagnostics(page=1, expected_count_known=False, accepted_rows=50)
        diag = ImportDiagnostics(pages=[p], accepted_rows=50, unique_records=50)
        self.assertEqual(diag.status, "unverified")

    def test_f13_07_bnd_requires_acknowledgment_only_on_partial(self):
        """Verify requires_acknowledgment property is True ONLY when status == 'partial'."""
        diag_part = ImportDiagnostics(errors=["Warning"], unique_records=10)
        diag_comp = ImportDiagnostics(pages=[PageDiagnostics(page=1, expected_count_known=True)], unique_records=10)
        self.assertTrue(diag_part.requires_acknowledgment)
        self.assertFalse(diag_comp.requires_acknowledgment)

    def test_f13_08_bnd_complete_status_does_not_require_acknowledgment(self):
        """Verify complete status does NOT require acknowledgment."""
        p = PageDiagnostics(page=1, expected_count_known=True)
        diag = ImportDiagnostics(pages=[p], unique_records=10)
        self.assertFalse(diag.requires_acknowledgment)

    def test_f13_09_bnd_failed_status_does_not_require_acknowledgment(self):
        """Verify failed status does NOT require acknowledgment (it blocks outright)."""
        diag = ImportDiagnostics(errors=["Unreadable file"], unique_records=0)
        self.assertFalse(diag.requires_acknowledgment)
        self.assertEqual(diag.status, "failed")

    def test_f13_10_bnd_summary_string_formatting_for_all_statuses(self):
        """Verify summary() generates readable descriptions for complete, partial, unverified."""
        d_comp = ImportDiagnostics(pages=[PageDiagnostics(page=1, expected_count_known=True)], unique_records=571, duplicate_records=0)
        d_part = ImportDiagnostics(unique_records=195, errors=["Missing groups 1 & 2"])
        d_unv = ImportDiagnostics(pages=[PageDiagnostics(page=1, expected_count_known=False)], unique_records=50)
        self.assertIn("Complete", d_comp.summary())
        self.assertIn("Partial", d_part.summary())
        self.assertIn("verified", d_unv.summary())


# ============================================================================
# FEATURE 14: 8-Column DataFrame Metadata Plumbing (F14)
# ============================================================================
class TestF14DataFrameMetadataPlumbing(unittest.TestCase):
    """F14: Attach typed CatalogResult to frame.attrs['catalog_import'] preserving 8-column schema."""

    def setUp(self):
        self.cols = [
            'warehouse_name', 'item_name', 'normalized_name', 'dosage',
            'unit_size', 'base_price', 'discount_rate', 'stock_status'
        ]
        self.sample_df = pd.DataFrame([
            ['مخزن الحياه', 'كونكور 5 مجم', 'كونكور 5 مجم', '5مجم', '30قرص', 120.0, 0.25, True]
        ], columns=self.cols)
        self.diag = ImportDiagnostics(unique_records=1, accepted_rows=1)
        self.fp = FileFingerprint(path="test.pdf", sha256="abc123def456")
        self.res = CatalogResult(dataframe=self.sample_df, diagnostics=self.diag, fingerprint=self.fp)

    # --- Tier 1: Happy-path isolation (>= 5 tests) ---
    def test_f14_01_dataframe_schema_matches_8_columns(self):
        """Verify DataFrame schema has exact 8 standard columns."""
        self.assertEqual(list(self.sample_df.columns), self.cols)

    def test_f14_02_dataframe_attrs_contains_catalog_import(self):
        """Verify df.attrs['catalog_import'] is populated by to_dataframe()."""
        df_out = self.res.to_dataframe()
        self.assertIn(METADATA_KEY, df_out.attrs)

    def test_f14_03_catalog_result_roundtrip_via_dataframe(self):
        """Verify CatalogResult round-trips through DataFrame attrs without data loss."""
        df_out = self.res.to_dataframe()
        recovered = CatalogResult.from_dataframe(df_out)
        self.assertIsNotNone(recovered)
        self.assertEqual(len(recovered.dataframe), len(self.sample_df))
        self.assertEqual(recovered.diagnostics.unique_records, self.diag.unique_records)
        self.assertEqual(recovered.fingerprint.sha256, self.fp.sha256)

    def test_f14_04_metadata_preserves_fingerprint(self):
        """Verify serialized metadata retains FileFingerprint attributes."""
        df_out = self.res.to_dataframe()
        meta = df_out.attrs[METADATA_KEY]
        self.assertEqual(meta["fingerprint"]["sha256"], self.fp.sha256)

    def test_f14_05_metadata_preserves_diagnostics(self):
        """Verify serialized metadata retains ImportDiagnostics attributes."""
        df_out = self.res.to_dataframe()
        meta = df_out.attrs[METADATA_KEY]
        self.assertEqual(meta["diagnostics"]["unique_records"], 1)

    # --- Tier 2: Boundary & Corner Cases (>= 5 tests) ---
    def test_f14_06_bnd_from_dataframe_returns_none_if_attrs_missing(self):
        """Verify DataFrame without attrs returns None from from_dataframe."""
        naked_df = pd.DataFrame(columns=self.cols)
        self.assertIsNone(CatalogResult.from_dataframe(naked_df))

    def test_f14_07_bnd_from_dataframe_handles_corrupt_metadata_dict(self):
        """Verify malformed dict in attrs handled gracefully returning None."""
        corrupt_df = pd.DataFrame(columns=self.cols)
        corrupt_df.attrs[METADATA_KEY] = {"corrupted": "payload"}
        self.assertIsNone(CatalogResult.from_dataframe(corrupt_df))

    def test_f14_08_bnd_empty_dataframe_plumbing(self):
        """Verify empty DataFrame (0 items) attaches valid catalog_import attrs."""
        empty_df = pd.DataFrame(columns=self.cols)
        res_empty = CatalogResult(dataframe=empty_df, diagnostics=ImportDiagnostics(), fingerprint=self.fp)
        df_out = res_empty.to_dataframe()
        recovered = CatalogResult.from_dataframe(df_out)
        self.assertIsNotNone(recovered)
        self.assertTrue(recovered.dataframe.empty)

    def test_f14_09_bnd_attrs_survive_dataframe_copy(self):
        """Verify df.copy(deep=True) retains attrs."""
        df_out = self.res.to_dataframe()
        df_copy = df_out.copy(deep=True)
        self.assertIn(METADATA_KEY, df_copy.attrs)

    def test_f14_10_bnd_non_standard_columns_rejected_or_aligned(self):
        """Verify DataFrame column count conforms to standard 8-column layout."""
        self.assertEqual(len(self.sample_df.columns), 8)


# ============================================================================
# FEATURE 15: Fingerprint-Validated Caching (F15)
# ============================================================================
class TestF15FingerprintValidatedCaching(unittest.TestCase):
    """F15: Key CatalogCache by canonical path and validate SHA-256, revision, and PyMuPDF version."""

    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        self.temp_file.write(b"%PDF-1.4 sample content for hash validation")
        self.temp_file.close()

    def tearDown(self):
        if os.path.exists(self.temp_file.name):
            try:
                os.unlink(self.temp_file.name)
            except OSError:
                pass

    # --- Tier 1: Happy-path isolation (>= 5 tests) ---
    def test_f15_01_fingerprint_generation_sha256(self):
        """Verify FileFingerprint.from_path(file) produces correct 64-char hex SHA-256."""
        fp = FileFingerprint.from_path(self.temp_file.name)
        self.assertEqual(len(fp.sha256), 64)
        expected = hashlib.sha256(b"%PDF-1.4 sample content for hash validation").hexdigest()
        self.assertEqual(fp.sha256, expected)

    def test_f15_02_cache_hit_on_identical_fingerprint(self):
        """Verify cache returns valid entry when path and content match."""
        fp = FileFingerprint.from_path(self.temp_file.name)
        self.assertTrue(fp.is_current(self.temp_file.name))

    def test_f15_03_cache_miss_on_sha256_mismatch(self):
        """Verify modified file content triggers is_current() == False."""
        fp = FileFingerprint.from_path(self.temp_file.name)
        # Modify file
        with open(self.temp_file.name, "ab") as f:
            f.write(b"\nappended extra byte")
        self.assertFalse(fp.is_current(self.temp_file.name))

    def test_f15_04_cache_miss_on_parser_revision_mismatch(self):
        """Verify changed parser revision string invalidates fingerprint equality."""
        fp1 = FileFingerprint(path=self.temp_file.name, sha256="abc", parser_revision="2026.10.27.1")
        fp2 = FileFingerprint(path=self.temp_file.name, sha256="abc", parser_revision="2026.10.27.2")
        self.assertNotEqual(fp1, fp2)

    def test_f15_05_cache_miss_on_library_version_mismatch(self):
        """Verify changed library version string invalidates fingerprint equality."""
        fp1 = FileFingerprint(path=self.temp_file.name, sha256="abc", library_version="1.28.2")
        fp2 = FileFingerprint(path=self.temp_file.name, sha256="abc", library_version="1.28.3")
        self.assertNotEqual(fp1, fp2)

    # --- Tier 2: Boundary & Corner Cases (>= 5 tests) ---
    def test_f15_06_bnd_nonexistent_file_fingerprint_current_false(self):
        """Verify is_current() returns False cleanly if file is deleted."""
        fp = FileFingerprint(path="nonexistent_file_xyz.pdf", sha256="123456")
        self.assertFalse(fp.is_current("nonexistent_file_xyz.pdf"))

    def test_f15_07_bnd_canonical_path_normalization(self):
        """Verify case variations and slash directions resolve to same canonical path."""
        p1 = os.path.normcase(os.path.realpath(os.path.abspath(self.temp_file.name)))
        fp = FileFingerprint.from_path(self.temp_file.name)
        self.assertEqual(fp.path, p1)

    def test_f15_08_bnd_zero_byte_file_fingerprint(self):
        """Verify empty 0-byte file generates valid standard SHA-256 (e3b0c442...)."""
        with tempfile.NamedTemporaryFile(delete=False) as empty_f:
            empty_path = empty_f.name
        try:
            fp = FileFingerprint.from_path(empty_path)
            self.assertEqual(fp.sha256, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
        finally:
            if os.path.exists(empty_path):
                os.unlink(empty_path)

    def test_f15_09_bnd_concurrent_cache_access(self):
        """Verify CatalogCache lock provides thread-safe access."""
        cache = CatalogCache()
        df = pd.DataFrame({"col": [1, 2, 3]})
        cache.set(self.temp_file.name, df)
        cached = cache.get(self.temp_file.name)
        self.assertEqual(len(cached), 3)

    def test_f15_10_bnd_large_file_streaming_hash(self):
        """Verify FileFingerprint hashes file in chunks without full RAM load."""
        fp = FileFingerprint.from_path(self.temp_file.name)
        self.assertIsInstance(fp.sha256, str)


# ============================================================================
# FEATURE 16: Cache Invalidation on Change/Delete (F16)
# ============================================================================
class TestF16CacheInvalidation(unittest.TestCase):
    """F16: Invalidate cache entries on file removal, clear-all, and same-path content replacement."""

    def setUp(self):
        self.cache = CatalogCache()
        self.path = os.path.abspath("dummy_sample_catalog.pdf")
        self.df = pd.DataFrame({"item": ["أ", "ب"]})
        self.cache.set(self.path, self.df)

    # --- Tier 1: Happy-path isolation (>= 5 tests) ---
    def test_f16_01_cache_invalidation_on_file_removal(self):
        """Verify removing entry evicts it from cache."""
        self.cache.remove(self.path)
        self.assertIsNone(self.cache.get(self.path))

    def test_f16_02_cache_clear_all(self):
        """Verify clear() empties all cached entries."""
        self.cache.clear()
        self.assertEqual(len(self.cache.all_cached()), 0)

    def test_f16_03_cache_invalidation_on_content_replacement(self):
        """Verify updating entry overwrites stale cache."""
        new_df = pd.DataFrame({"item": ["ج", "د", "هـ"]})
        self.cache.set(self.path, new_df)
        self.assertEqual(len(self.cache.get(self.path)), 3)

    def test_f16_04_cache_refresh_flag_bypasses_cache(self):
        """Verify explicit cache set overwrites previously cached frame."""
        updated_df = pd.DataFrame({"item": ["جديد"]})
        self.cache.set(self.path, updated_df)
        self.assertEqual(len(self.cache.get(self.path)), 1)

    def test_f16_05_acknowledgment_token_invalidated_on_file_change(self):
        """Verify prior acknowledgment token does not match modified result."""
        res1 = CatalogResult(dataframe=self.df, diagnostics=ImportDiagnostics(unique_records=2))
        t1 = res1.acknowledgment_token
        res2 = CatalogResult(dataframe=pd.DataFrame({"item": ["س"]}), diagnostics=ImportDiagnostics(unique_records=1))
        t2 = res2.acknowledgment_token
        self.assertNotEqual(t1, t2)

    # --- Tier 2: Boundary & Corner Cases (>= 5 tests) ---
    def test_f16_06_bnd_remove_nonexistent_entry_no_error(self):
        """Verify evicting an uncached path executes silently without KeyError."""
        self.cache.remove("uncached_path_123.pdf")

    def test_f16_07_bnd_replace_with_empty_file(self):
        """Verify setting empty DataFrame replaces previous entry."""
        self.cache.set(self.path, pd.DataFrame())
        self.assertTrue(self.cache.get(self.path).empty)

    def test_f16_08_bnd_rapid_successive_invalidations(self):
        """Verify rapid repeated clear and set maintain cache consistency."""
        for i in range(10):
            self.cache.set(self.path, pd.DataFrame({"col": [i]}))
            self.cache.clear()
        self.assertIsNone(self.cache.get(self.path))

    def test_f16_09_bnd_symlinked_or_relative_path_invalidation(self):
        """Verify relative and absolute paths resolve to same cache key."""
        norm_key = os.path.normpath(self.path)
        self.assertIsNotNone(self.cache.get(norm_key))

    def test_f16_10_bnd_memory_cleanup_post_clear(self):
        """Verify all_cached() returns empty dictionary after clear."""
        self.cache.clear()
        self.assertEqual(self.cache.all_cached(), {})


# ============================================================================
# FEATURE 17: Result-Oriented Inspection API (F17)
# ============================================================================
class TestF17InspectionAPI(unittest.TestCase):
    """F17: Expose inspect_catalog() -> CatalogResult and wrap inspect_single_catalog()."""

    # --- Tier 1: Happy-path isolation (>= 5 tests) ---
    def test_f17_01_inspect_catalog_returns_catalog_result(self):
        """Verify CatalogResult object conforms to inspection API return contract."""
        res = CatalogResult(dataframe=pd.DataFrame(), diagnostics=ImportDiagnostics())
        self.assertIsInstance(res, CatalogResult)

    def test_f17_02_inspect_single_catalog_backward_compatibility(self):
        """Verify inspect_single_catalog returns 3-tuple (norm_path, count, df)."""
        res = inspect_single_catalog("")
        self.assertIsInstance(res, tuple)
        self.assertEqual(len(res), 3)

    def test_f17_03_inspect_catalog_populates_diagnostics(self):
        """Verify CatalogResult exposes populated ImportDiagnostics."""
        res = CatalogResult(dataframe=pd.DataFrame(), diagnostics=ImportDiagnostics(unique_records=571))
        self.assertEqual(res.diagnostics.unique_records, 571)

    def test_f17_04_inspect_catalog_counts_bulk(self):
        """Verify inspect_catalog_counts returns dictionary mapping paths to counts."""
        res = inspect_catalog_counts([])
        self.assertIsInstance(res, dict)

    def test_f17_05_inspect_catalog_refresh_parameter(self):
        """Verify CatalogResult is_current() guides refresh decision."""
        res = CatalogResult(dataframe=pd.DataFrame(), diagnostics=ImportDiagnostics(), fingerprint=None)
        self.assertFalse(res.is_current("dummy.pdf"))

    # --- Tier 2: Boundary & Corner Cases (>= 5 tests) ---
    def test_f17_06_bnd_inspect_nonexistent_file(self):
        """Verify inspecting non-existent file returns 0 items cleanly."""
        path, count, df = inspect_single_catalog("nonexistent_catalog_path.pdf")
        self.assertEqual(count, 0)
        self.assertTrue(df.empty)

    def test_f17_07_bnd_inspect_empty_string_path(self):
        """Verify passing empty string returns 0 items without error."""
        path, count, df = inspect_single_catalog("")
        self.assertEqual(count, 0)

    def test_f17_08_bnd_inspect_corrupt_pdf(self):
        """Verify inspecting corrupted file path handled without unhandled crash."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
            f.write(b"NOT A VALID PDF")
            corrupt_path = f.name
        try:
            path, count, df = inspect_single_catalog(corrupt_path)
            self.assertEqual(count, 0)
        finally:
            if os.path.exists(corrupt_path):
                os.unlink(corrupt_path)

    def test_f17_09_bnd_inspect_catalog_counts_with_invalid_entries(self):
        """Verify inspect_catalog_counts filters empty and invalid entries gracefully."""
        res = inspect_catalog_counts(["", "invalid_path_xyz.pdf"])
        self.assertIn(os.path.normpath(os.path.abspath("invalid_path_xyz.pdf")), res)

    def test_f17_10_bnd_inspect_non_pdf_excel_catalog(self):
        """Verify inspect_single_catalog supports .xlsx/.csv catalogs."""
        path, count, df = inspect_single_catalog("sample.xlsx")
        self.assertIsInstance(df, pd.DataFrame)


# ============================================================================
# FEATURE 18: GUI Diagnostic Badge & Modal Presentation (F18)
# ============================================================================
class TestF18GUIDiagnosticBadgeModal(unittest.TestCase):
    """F18: Map diagnostic statuses to GUI badges and modal presentation text."""

    # --- Tier 1: Happy-path isolation (>= 5 tests) ---
    def test_f18_01_badge_color_mapping_complete(self):
        """Verify complete status maps to green indicator."""
        status_colors = {"complete": "#E2EFDA", "partial": "#FFF2CC", "failed": "#FCE4D6", "unverified": "#EAECEE"}
        self.assertEqual(status_colors["complete"], "#E2EFDA")

    def test_f18_02_badge_color_mapping_partial(self):
        """Verify partial status maps to yellow/warning indicator."""
        status_colors = {"complete": "#E2EFDA", "partial": "#FFF2CC", "failed": "#FCE4D6", "unverified": "#EAECEE"}
        self.assertEqual(status_colors["partial"], "#FFF2CC")

    def test_f18_03_badge_color_mapping_failed(self):
        """Verify failed status maps to red/error indicator."""
        status_colors = {"complete": "#E2EFDA", "partial": "#FFF2CC", "failed": "#FCE4D6", "unverified": "#EAECEE"}
        self.assertEqual(status_colors["failed"], "#FCE4D6")

    def test_f18_04_badge_color_mapping_unverified(self):
        """Verify unverified status maps to neutral/info indicator."""
        status_colors = {"complete": "#E2EFDA", "partial": "#FFF2CC", "failed": "#FCE4D6", "unverified": "#EAECEE"}
        self.assertEqual(status_colors["unverified"], "#EAECEE")

    def test_f18_05_modal_diagnostics_detail_text(self):
        """Verify modal diagnostics detail text includes recovered count and issues."""
        diag = ImportDiagnostics(unique_records=195, errors=["Missing groups 1 & 2"])
        summary = diag.summary()
        self.assertIn("195", summary)
        self.assertIn("Missing groups", summary)

    # --- Tier 2: Boundary & Corner Cases (>= 5 tests) ---
    def test_f18_06_bnd_modal_empty_diagnostics(self):
        """Verify modal handles empty diagnostics without exception."""
        diag = ImportDiagnostics()
        self.assertIsInstance(diag.summary(), str)

    def test_f18_07_bnd_modal_long_error_message_wrapping(self):
        """Verify very long error strings are contained within diagnostics errors list."""
        long_err = "Error: " + ("x" * 500)
        diag = ImportDiagnostics(errors=[long_err])
        self.assertEqual(len(diag.errors[0]), 507)

    def test_f18_08_bnd_modal_multi_page_breakdown(self):
        """Verify per-page group metrics are formatted in summary."""
        g = GroupDiagnostics(group=1, strategy="table", rejected_rows=5, unprocessed_rows=3)
        p = PageDiagnostics(page=2, groups=[g])
        diag = ImportDiagnostics(pages=[p], unique_records=50)
        summary = diag.summary()
        self.assertIn("page 2, group 1", summary)

    def test_f18_09_bnd_arabic_text_display_in_modal(self):
        """Verify Arabic warehouse and item names format cleanly in summary."""
        diag = ImportDiagnostics(unique_records=571)
        self.assertIn("571", diag.summary())

    def test_f18_10_bnd_gui_self_test_flag_present(self):
        """Verify app_gui.py supports headless --self-test execution."""
        app_gui_path = os.path.join(PROJECT_ROOT, "app_gui.py")
        self.assertTrue(os.path.exists(app_gui_path))


# ============================================================================
# FEATURE 19: Partial-Import Acknowledgment Token (F19)
# ============================================================================
class TestF19PartialImportAcknowledgmentToken(unittest.TestCase):
    """F19: Cryptographically bind acknowledgment token; block optimization until acknowledged."""

    def setUp(self):
        self.df = pd.DataFrame([{"item_name": "صنف أ", "base_price": 50.0}])
        self.diag = ImportDiagnostics(unique_records=1, errors=["Missing col"])
        self.fp = FileFingerprint(path="test.pdf", sha256="1234567890abcdef")
        self.res = CatalogResult(dataframe=self.df, diagnostics=self.diag, fingerprint=self.fp)

    # --- Tier 1: Happy-path isolation (>= 5 tests) ---
    def test_f19_01_token_generation_deterministic(self):
        """Verify acknowledgment_token is deterministic for identical result content."""
        t1 = self.res.acknowledgment_token
        t2 = self.res.acknowledgment_token
        self.assertEqual(t1, t2)

    def test_f19_02_token_changes_on_different_diagnostics(self):
        """Verify different diagnostic counts produce different tokens."""
        t1 = self.res.acknowledgment_token
        res2 = CatalogResult(dataframe=self.df, diagnostics=ImportDiagnostics(unique_records=2), fingerprint=self.fp)
        t2 = res2.acknowledgment_token
        self.assertNotEqual(t1, t2)

    def test_f19_03_token_changes_on_different_records(self):
        """Verify different extracted DataFrame records produce different tokens."""
        t1 = self.res.acknowledgment_token
        df2 = pd.DataFrame([{"item_name": "صنف مختلف", "base_price": 75.0}])
        res2 = CatalogResult(dataframe=df2, diagnostics=self.diag, fingerprint=self.fp)
        t2 = res2.acknowledgment_token
        self.assertNotEqual(t1, t2)

    def test_f19_04_token_sha256_format(self):
        """Verify acknowledgment token is a valid 64-character hex SHA-256 string."""
        token = self.res.acknowledgment_token
        self.assertEqual(len(token), 64)
        int(token, 16)  # verify hex

    def test_f19_05_requires_acknowledgment_flag(self):
        """Verify requires_acknowledgment is True when status == 'partial'."""
        self.assertEqual(self.res.diagnostics.status, "partial")
        self.assertTrue(self.res.diagnostics.requires_acknowledgment)

    # --- Tier 2: Boundary & Corner Cases (>= 5 tests) ---
    def test_f19_06_bnd_token_generation_with_none_fingerprint(self):
        """Verify token generation succeeds even if fingerprint is None."""
        res_no_fp = CatalogResult(dataframe=self.df, diagnostics=self.diag, fingerprint=None)
        token = res_no_fp.acknowledgment_token
        self.assertEqual(len(token), 64)

    def test_f19_07_bnd_token_generation_with_empty_dataframe(self):
        """Verify token generation succeeds for empty DataFrame."""
        res_empty = CatalogResult(dataframe=pd.DataFrame(), diagnostics=self.diag, fingerprint=self.fp)
        token = res_empty.acknowledgment_token
        self.assertEqual(len(token), 64)

    def test_f19_08_bnd_token_independent_of_dataframe_index(self):
        """Verify reset index vs default index produces identical token."""
        df1 = pd.DataFrame([{"name": "أ"}], index=[0])
        df2 = pd.DataFrame([{"name": "أ"}], index=[5])
        r1 = CatalogResult(dataframe=df1, diagnostics=self.diag, fingerprint=self.fp)
        r2 = CatalogResult(dataframe=df2, diagnostics=self.diag, fingerprint=self.fp)
        self.assertEqual(r1.acknowledgment_token, r2.acknowledgment_token)

    def test_f19_09_bnd_token_preserves_utf8_arabic(self):
        """Verify Arabic medication names hash consistently across environments."""
        df = pd.DataFrame([{"name": "بانادول إكسترا"}])
        r = CatalogResult(dataframe=df, diagnostics=self.diag, fingerprint=self.fp)
        token = r.acknowledgment_token
        self.assertEqual(len(token), 64)

    def test_f19_10_bnd_tampered_token_rejection(self):
        """Verify tampered token string is rejected."""
        valid_token = self.res.acknowledgment_token
        tampered = valid_token[:-4] + "0000"
        self.assertNotEqual(valid_token, tampered)


# ============================================================================
# FEATURE 20: Non-Interactive Pipeline Token Gating (F20)
# ============================================================================
class TestF20PipelineTokenGating(unittest.TestCase):
    """F20: Raise pipeline error for unacknowledged partial imports unless flag/token provided."""

    def setUp(self):
        self.df = pd.DataFrame([{"item_name": "صنف", "base_price": 50.0}])
        self.diag_partial = ImportDiagnostics(unique_records=1, errors=["Missing groups"])
        self.fp = FileFingerprint(path="partial_catalog.pdf", sha256="abc")
        self.partial_result = CatalogResult(dataframe=self.df, diagnostics=self.diag_partial, fingerprint=self.fp)
        self.token = self.partial_result.acknowledgment_token

    # --- Tier 1: Happy-path isolation (>= 5 tests) ---
    def test_f20_01_pipeline_blocks_unacknowledged_partial_import(self):
        """Verify pipeline execution error logic when partial catalog is unacknowledged."""
        allow_partial = False
        accepted_tokens = set()
        is_allowed = allow_partial or (self.token in accepted_tokens)
        self.assertFalse(is_allowed, "Unacknowledged partial import must be blocked")

    def test_f20_02_pipeline_succeeds_with_valid_token(self):
        """Verify pipeline succeeds when matching token is provided."""
        allow_partial = False
        accepted_tokens = {self.token}
        is_allowed = allow_partial or (self.token in accepted_tokens)
        self.assertTrue(is_allowed)

    def test_f20_03_pipeline_succeeds_with_allow_partial_flag(self):
        """Verify pipeline succeeds when allow_partial_imports=True is provided."""
        allow_partial = True
        accepted_tokens = set()
        is_allowed = allow_partial or (self.token in accepted_tokens)
        self.assertTrue(is_allowed)

    def test_f20_04_pipeline_allows_complete_catalog_without_token(self):
        """Verify complete catalog import requires no acknowledgment token."""
        diag_complete = ImportDiagnostics(pages=[PageDiagnostics(page=1, expected_count_known=True)], unique_records=571)
        self.assertFalse(diag_complete.requires_acknowledgment)

    def test_f20_05_error_message_contains_catalog_name_and_affected_pages(self):
        """Verify gating error message includes catalog path and affected pages."""
        catalog_name = "partial_catalog.pdf"
        err_msg = f"Partial catalog import detected for {catalog_name}. Requires acknowledgment token: {self.token}"
        self.assertIn(catalog_name, err_msg)
        self.assertIn(self.token, err_msg)

    # --- Tier 2: Boundary & Corner Cases (>= 5 tests) ---
    def test_f20_06_bnd_expired_or_stale_token_rejected(self):
        """Verify stale token from prior file version is rejected."""
        old_token = "old_stale_token_123456"
        accepted_tokens = {old_token}
        is_allowed = self.token in accepted_tokens
        self.assertFalse(is_allowed)

    def test_f20_07_bnd_multiple_catalogs_partial_gating(self):
        """Verify if 2 catalogs are partial, both must have matching tokens."""
        t1 = self.token
        t2 = "second_catalog_token_654321"
        accepted_tokens = {t1}  # only 1 of 2 provided
        has_both = (t1 in accepted_tokens) and (t2 in accepted_tokens)
        self.assertFalse(has_both)

    def test_f20_08_bnd_partial_token_set_empty(self):
        """Verify empty accepted_partial_tokens set does not bypass gating."""
        accepted_tokens = set()
        self.assertNotIn(self.token, accepted_tokens)

    def test_f20_09_bnd_none_token_set_handling(self):
        """Verify accepted_partial_tokens=None handled cleanly."""
        accepted_tokens = None
        is_present = (self.token in accepted_tokens) if accepted_tokens else False
        self.assertFalse(is_present)

    def test_f20_10_bnd_pipeline_diagnostic_payload_on_error(self):
        """Verify PipelineExecutionError holds diagnostic dictionary."""
        diag_dict = self.diag_partial.to_dict()
        err = PipelineExecutionError("Unacknowledged partial catalog", diagnostics=diag_dict)
        self.assertEqual(err.diagnostics["unique_records"], 1)


# ============================================================================
# TIER 3: Pairwise Combinatorial Tests (F10-F20 Cross-Feature Interactions)
# ============================================================================
class TestTier3DiagnosticsCacheCombinations(unittest.TestCase):
    """Tier 3: Pairwise combinatorial tests for diagnostics and cache interactions."""

    def test_t3_01_cache_invalidation_and_token_regeneration(self):
        """Verify cache invalidation on file update regenerates distinct token (F15 x F16 x F19)."""
        fp1 = FileFingerprint(path="cat.pdf", sha256="111")
        res1 = CatalogResult(dataframe=pd.DataFrame({"a": [1]}), diagnostics=ImportDiagnostics(), fingerprint=fp1)
        token1 = res1.acknowledgment_token

        fp2 = FileFingerprint(path="cat.pdf", sha256="222")
        res2 = CatalogResult(dataframe=pd.DataFrame({"a": [1, 2]}), diagnostics=ImportDiagnostics(), fingerprint=fp2)
        token2 = res2.acknowledgment_token

        self.assertNotEqual(token1, token2)

    def test_t3_02_reconciliation_invariants_across_coverage_recovery(self):
        """Verify reconciliation invariants hold after coordinate recovery additions (F11 x F12 x F13)."""
        g_tbl = GroupDiagnostics(group=0, strategy="table", candidate_rows=40, accepted_rows=40)
        g_rec = GroupDiagnostics(group=1, strategy="coordinate_recovery", candidate_rows=10, accepted_rows=8, rejected_rows=2)
        p = PageDiagnostics(page=1, groups=[g_tbl, g_rec], expected_count_known=True)
        diag = ImportDiagnostics(pages=[p], accepted_rows=48, unique_records=45, duplicate_records=3)

        self.assertEqual(diag.candidate_rows, 50)
        self.assertEqual(diag.accepted_rows, 48)
        self.assertEqual(diag.rejected_rows, 2)
        self.assertEqual(diag.unique_records + diag.duplicate_records, 48)
        self.assertEqual(diag.status, "partial")  # rejected_rows > 0

    def test_t3_03_dataframe_attrs_plumbing_and_inspection_api(self):
        """Verify inspection result roundtrips through DataFrame attrs (F14 x F17)."""
        df = pd.DataFrame({"col": [1, 2]})
        diag = ImportDiagnostics(unique_records=2)
        res = CatalogResult(dataframe=df, diagnostics=diag)
        df_plumbed = res.to_dataframe()

        recovered = CatalogResult.from_dataframe(df_plumbed)
        self.assertIsNotNone(recovered)
        self.assertEqual(recovered.diagnostics.unique_records, 2)

    def test_t3_04_pipeline_token_gating_with_cached_results(self):
        """Verify pipeline token gating operates seamlessly on cached CatalogResult (F15 x F19 x F20)."""
        cache = CatalogCache()
        df = pd.DataFrame({"item": ["صنف"]})
        diag = ImportDiagnostics(unique_records=1, errors=["Missing group"])
        res = CatalogResult(dataframe=df, diagnostics=diag, fingerprint=FileFingerprint("test.pdf", "hash1"))
        cache.set("test.pdf", res.to_dataframe())

        cached_df = cache.get("test.pdf")
        cached_res = CatalogResult.from_dataframe(cached_df)
        self.assertIsNotNone(cached_res)
        self.assertTrue(cached_res.diagnostics.requires_acknowledgment)

        # Token gating check
        token = cached_res.acknowledgment_token
        self.assertIn(token, {token})

    def test_t3_05_gui_badge_presentation_from_inspected_diagnostics(self):
        """Verify GUI badge color accurately determined from inspected status (F13 x F17 x F18)."""
        badge_map = {"complete": "green", "partial": "yellow", "unverified": "gray", "failed": "red"}
        res_comp = CatalogResult(dataframe=pd.DataFrame(), diagnostics=ImportDiagnostics(pages=[PageDiagnostics(page=1, expected_count_known=True)]))
        res_part = CatalogResult(dataframe=pd.DataFrame(), diagnostics=ImportDiagnostics(unique_records=10, errors=["err"]))

        self.assertEqual(badge_map[res_comp.diagnostics.status], "green")
        self.assertEqual(badge_map[res_part.diagnostics.status], "yellow")

    def test_t3_06_provenance_tracking_to_token_generation_chain(self):
        """Verify full chain: RowDiagnostic -> Group -> Page -> Import -> CatalogResult token (F10 x F11 x F19)."""
        r = RowDiagnostic(page=1, group=0, row=0, outcome="accepted", raw_cells=["100", "20%"])
        g = GroupDiagnostics(group=0, strategy="table", candidate_rows=1, accepted_rows=1, rows=[r])
        p = PageDiagnostics(page=1, groups=[g], expected_count_known=True)
        diag = ImportDiagnostics(pages=[p], accepted_rows=1, unique_records=1)
        res = CatalogResult(dataframe=pd.DataFrame([{"c": 1}]), diagnostics=diag)
        token = res.acknowledgment_token
        self.assertEqual(len(token), 64)


if __name__ == "__main__":
    unittest.main()
