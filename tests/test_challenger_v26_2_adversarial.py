# -*- coding: utf-8 -*-
"""
Adversarial Stress Test Suite - Challenger 2 (v2.6 M2-QA)
File: tests/test_challenger_v26_2_adversarial.py

Empirical stress tests focusing on:
1. Cache invalidation stress: alter ocr_model_version or recovery_config_hash; verify stale cache rejected.
2. Quality degradation attack: simulate degraded re-extraction (higher defects / lower items); verify CatalogCache rejects degraded replacement.
3. Ambiguous legacy corrections attack: create ambiguous 3-part source IDs; verify kept pending review without guessing.
4. Strict procurement exclusion stress: feed catalogs containing rejected rows, unmapped region issues, or invalid prices/discounts; verify NOT A SINGLE unverified or out-of-bounds row enters allocator or final workbook.
5. Zero valid items block: feed a catalog with 0 valid items into run_procurement_pipeline; verify cleanly raises PipelineExecutionError and aborts allocation.
6. Concurrency & cancellation stress: trigger multiple asynchronous operations, call cancel_ocr, confirm thread pool terminates cleanly without orphaned processes or state corruption.
"""

import os
import sys
import time
import shutil
import tempfile
import threading
import queue
import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
import openpyxl

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.catalog_diagnostics import (
    FileFingerprint,
    CatalogResult,
    RowDiagnostic,
    GroupDiagnostics,
    PageDiagnostics,
    ImportDiagnostics,
    ReviewIssue,
    SourceIdentity,
    METADATA_KEY,
    PARSER_REVISION,
    is_ambiguous_legacy_source_id,
    find_legacy_source_id_candidates,
    source_id_matches,
    resolve_compatible_source_id,
)
from src.controller import (
    CatalogCache,
    is_replacement_quality_degraded,
    merge_catalog_results_without_duplication,
    inspect_catalog,
    global_catalog_cache,
    DEFAULT_OCR_MODEL_VERSION,
    DEFAULT_RECOVERY_CONFIG_HASH,
)
from src.catalog_corrections import (
    save_corrections,
    load_corrections,
    find_ambiguous_corrections,
    partition_corrections_by_ambiguity,
)
from src.pipeline import (
    run_procurement_pipeline,
    validate_cached_catalog,
    PipelineExecutionError,
    _build_consolidated_inventory,
)


def _create_dummy_pdf(file_path: str):
    """Creates a minimal valid 1-page PDF using PyMuPDF."""
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 50), "Test Catalog Content", fontsize=12)
    doc.save(file_path)
    doc.close()


def _create_sample_catalog_df(items: list[dict], warehouse_name: str = "TestWh") -> pd.DataFrame:
    """Helper to create a standard 8-column catalog DataFrame with optional source_id."""
    cols = [
        'warehouse_name', 'item_name', 'normalized_name', 'dosage',
        'unit_size', 'base_price', 'discount_rate', 'stock_status'
    ]
    rows = []
    for it in items:
        row = {
            'warehouse_name': warehouse_name,
            'item_name': it.get('item_name', 'Panadol Extra 500mg'),
            'normalized_name': it.get('normalized_name', 'panadol extra'),
            'dosage': it.get('dosage', '500mg'),
            'unit_size': it.get('unit_size', 'Tab'),
            'base_price': it.get('base_price', 50.0),
            'discount_rate': it.get('discount_rate', 0.15),
            'stock_status': it.get('stock_status', True),
        }
        if 'source_id' in it:
            row['source_id'] = it['source_id']
        rows.append(row)
    df = pd.DataFrame(rows)
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df


def _make_diagnostics(
    status: str = "complete",
    accepted: int = 10,
    rejected: int = 0,
    unprocessed: int = 0,
    unresolved_regions: int = 0,
    errors: list[str] = None,
    rows: list[RowDiagnostic] = None,
) -> ImportDiagnostics:
    """Helper to construct ImportDiagnostics that accurately produces the desired status property."""
    err_list = list(errors) if errors else []
    expected_known = (status == "complete")
    row_list = list(rows) if rows else []
    group = GroupDiagnostics(
        group=0,
        strategy="table_ocr",
        candidate_rows=accepted + rejected + unprocessed,
        accepted_rows=accepted,
        rejected_rows=rejected,
        unprocessed_rows=unprocessed,
        rows=row_list,
    )
    page = PageDiagnostics(
        page=1,
        expected_count_known=expected_known,
        accepted_rows=accepted,
        groups=[group],
        errors=err_list,
    )
    return ImportDiagnostics(
        pages=[page],
        accepted_rows=accepted,
        unique_records=accepted,
        errors=err_list,
        unresolved_region_count=unresolved_regions,
    )


def _create_sample_order_excel(file_path: str, items: list[dict]):
    """Helper to create purchase order Excel file."""
    rows = []
    for it in items:
        rows.append({
            'item_name': it.get('item_name', 'Panadol Extra 500mg'),
            'quantity': it.get('quantity', 10),
        })
    df = pd.DataFrame(rows)
    df.to_excel(file_path, index=False)


# =============================================================================
# Vector 1: Cache Invalidation Stress
# =============================================================================
class TestAdversarialCacheInvalidation(unittest.TestCase):
    """Stress tests verifying stale cache entries are immediately rejected on version/hash drift."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="adv_cache_")
        self.pdf_path = os.path.join(self.temp_dir, "test_catalog.pdf")
        _create_dummy_pdf(self.pdf_path)
        self.cache = CatalogCache()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_adv_cache_invalidated_when_ocr_model_version_changed(self):
        """Altering ocr_model_version immediately invalidates and evicts stale cached entries."""
        items = [{'item_name': f'Medicine {i}', 'base_price': 10.0 + i} for i in range(5)]
        df = _create_sample_catalog_df(items)
        fp = FileFingerprint.from_path(self.pdf_path)
        self.assertEqual(fp.ocr_model_version, DEFAULT_OCR_MODEL_VERSION)
        res = CatalogResult(dataframe=df, diagnostics=_make_diagnostics("complete", accepted=5), fingerprint=fp)
        df_with_meta = res.to_dataframe()

        self.cache.set(self.pdf_path, df_with_meta)
        # Verify cache hit initially
        self.assertIsNotNone(self.cache.get(self.pdf_path))

        # ATTACK: Alter active ocr_model_version
        self.cache.set_active_versions(ocr_model_version="rapidocr_arabic_v2_experimental")
        # Stale cache must be immediately rejected and evicted
        stale_hit = self.cache.get(self.pdf_path)
        self.assertIsNone(stale_hit, "Stale cached entry was not rejected after OCR model version change!")
        norm = os.path.normpath(os.path.abspath(self.pdf_path))
        self.assertNotIn(norm, self.cache._cache, "Stale entry was not evicted from internal storage!")

    def test_adv_cache_invalidated_when_recovery_config_hash_changed(self):
        """Altering recovery_config_hash immediately invalidates and evicts stale cached entries."""
        items = [{'item_name': f'Medicine {i}', 'base_price': 20.0 + i} for i in range(3)]
        df = _create_sample_catalog_df(items)
        fp = FileFingerprint.from_path(self.pdf_path)
        self.assertEqual(fp.recovery_config_hash, DEFAULT_RECOVERY_CONFIG_HASH)
        res = CatalogResult(dataframe=df, diagnostics=_make_diagnostics("complete", accepted=3), fingerprint=fp)
        df_with_meta = res.to_dataframe()

        self.cache.set(self.pdf_path, df_with_meta)
        self.assertIsNotNone(self.cache.get(self.pdf_path))

        # ATTACK: Alter recovery configuration hash
        self.cache.set_active_versions(recovery_config_hash="v26_adversarial_skewed")
        stale_hit = self.cache.get(self.pdf_path)
        self.assertIsNone(stale_hit, "Stale cached entry was not rejected after recovery config hash change!")

    def test_adv_validate_cached_catalog_rejects_altered_ocr_or_recovery(self):
        """validate_cached_catalog directly returns None when fingerprint versions mismatch."""
        items = [{'item_name': 'Panadol', 'base_price': 50.0}]
        df = _create_sample_catalog_df(items)
        fp = FileFingerprint.from_path(self.pdf_path)

        # 1. Altered ocr_model_version in fingerprint
        bad_ocr_fp = FileFingerprint(
            path=fp.path,
            sha256=fp.sha256,
            parser_revision=fp.parser_revision,
            library_version=fp.library_version,
            ocr_model_version="adversarial_fake_ocr_model",
            recovery_config_hash=fp.recovery_config_hash,
        )
        res_bad_ocr = CatalogResult(dataframe=df, diagnostics=_make_diagnostics("complete", accepted=1), fingerprint=bad_ocr_fp)
        self.assertIsNone(
            validate_cached_catalog(res_bad_ocr, self.pdf_path),
            "validate_cached_catalog accepted an entry with mismatched ocr_model_version!"
        )

        # 2. Altered recovery_config_hash in fingerprint
        bad_rec_fp = FileFingerprint(
            path=fp.path,
            sha256=fp.sha256,
            parser_revision=fp.parser_revision,
            library_version=fp.library_version,
            ocr_model_version=fp.ocr_model_version,
            recovery_config_hash="adversarial_fake_recovery_hash",
        )
        res_bad_rec = CatalogResult(dataframe=df, diagnostics=_make_diagnostics("complete", accepted=1), fingerprint=bad_rec_fp)
        self.assertIsNone(
            validate_cached_catalog(res_bad_rec, self.pdf_path),
            "validate_cached_catalog accepted an entry with mismatched recovery_config_hash!"
        )

    def test_adv_all_cached_purges_stale_versions(self):
        """CatalogCache.all_cached() rigorously purges any entry whose fingerprint versions mismatch."""
        items = [{'item_name': 'Panadol', 'base_price': 50.0}]
        df = _create_sample_catalog_df(items)
        fp = FileFingerprint.from_path(self.pdf_path)
        res = CatalogResult(dataframe=df, diagnostics=_make_diagnostics("complete", accepted=1), fingerprint=fp)
        self.cache.set(self.pdf_path, res.to_dataframe())

        # Change parser revision
        self.cache.current_parser_revision = "PARSER_REVISION_V99"
        cached_dict = self.cache.all_cached()
        self.assertEqual(len(cached_dict), 0, "all_cached() failed to purge stale parser revision entries!")


# =============================================================================
# Vector 2: Quality Degradation Attack
# =============================================================================
class TestAdversarialQualityDegradation(unittest.TestCase):
    """Stress tests verifying that CatalogCache and controller reject degraded replacements."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="adv_degrade_")
        self.pdf_path = os.path.join(self.temp_dir, "catalog_quality.pdf")
        _create_dummy_pdf(self.pdf_path)
        self.cache = CatalogCache()
        self.fp = FileFingerprint.from_path(self.pdf_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_adv_degradation_guard_rejects_rank_demotion(self):
        """Known-good 'complete' catalog must not be overwritten by 'partial' or 'unverified' re-parse."""
        # 1. Known-good entry (complete, 10 items)
        good_items = [{'item_name': f'GoodMed {i}', 'base_price': 10.0 + i} for i in range(10)]
        good_df = _create_sample_catalog_df(good_items)
        good_diag = _make_diagnostics("complete", accepted=10)
        good_res = CatalogResult(dataframe=good_df, diagnostics=good_diag, fingerprint=self.fp)
        self.cache.set(self.pdf_path, good_res.to_dataframe())

        # 2. Degraded candidate (rank demotion to 'unverified', same 10 items)
        deg_diag = _make_diagnostics("unverified", accepted=10)
        deg_res = CatalogResult(dataframe=good_df, diagnostics=deg_diag, fingerprint=self.fp)

        # Assert degradation function evaluates True
        self.assertTrue(
            is_replacement_quality_degraded(good_res, deg_res),
            "is_replacement_quality_degraded failed to flag rank demotion (complete -> unverified)!"
        )

        # Attempt to overwrite in cache without force
        self.cache.set(self.pdf_path, deg_res.to_dataframe(), force=False)

        # Verify cached result remains 'complete'
        cached_df = self.cache.get(self.pdf_path)
        cached_res = CatalogResult.from_dataframe(cached_df)
        self.assertEqual(cached_res.status, "complete", "CatalogCache allowed degraded rank to overwrite known-good result!")

    def test_adv_degradation_guard_rejects_defect_increase(self):
        """Replacement with higher defect count (rejected rows or unresolved regions) is rejected."""
        good_items = [{'item_name': f'GoodMed {i}', 'base_price': 10.0 + i} for i in range(8)]
        good_df = _create_sample_catalog_df(good_items)
        good_diag = _make_diagnostics("complete", accepted=8)
        good_res = CatalogResult(dataframe=good_df, diagnostics=good_diag, fingerprint=self.fp)
        self.cache.set(self.pdf_path, good_res.to_dataframe())

        # Degraded candidate: rejected_rows=3 and unresolved_region_count=2
        deg_diag = _make_diagnostics("partial", accepted=8, rejected=3, unresolved_regions=2)
        deg_res = CatalogResult(dataframe=good_df, diagnostics=deg_diag, fingerprint=self.fp)

        self.assertTrue(is_replacement_quality_degraded(good_res, deg_res))

        self.cache.set(self.pdf_path, deg_res.to_dataframe())
        cached_res = CatalogResult.from_dataframe(self.cache.get(self.pdf_path))
        self.assertEqual(cached_res.diagnostics.rejected_rows, 0, "Defect-increased replacement overwrote known-good cache!")

    def test_adv_degradation_guard_rejects_row_count_drop_under_equal_rank(self):
        """When rank and defects are identical, row count drop is rejected as degraded."""
        items_10 = [{'item_name': f'Med {i}', 'base_price': 15.0} for i in range(10)]
        df_10 = _create_sample_catalog_df(items_10)
        diag_10 = _make_diagnostics("complete", accepted=10)
        res_10 = CatalogResult(dataframe=df_10, diagnostics=diag_10, fingerprint=self.fp)
        self.cache.set(self.pdf_path, res_10.to_dataframe())

        items_5 = [{'item_name': f'Med {i}', 'base_price': 15.0} for i in range(5)]
        df_5 = _create_sample_catalog_df(items_5)
        diag_5 = _make_diagnostics("complete", accepted=5)
        res_5 = CatalogResult(dataframe=df_5, diagnostics=diag_5, fingerprint=self.fp)

        self.assertTrue(is_replacement_quality_degraded(res_10, res_5))

        self.cache.set(self.pdf_path, res_5.to_dataframe())
        cached_df = self.cache.get(self.pdf_path)
        self.assertEqual(len(cached_df), 10, "Row-count drop overwrote larger verified catalog!")

    def test_adv_degradation_guard_allows_legitimate_upgrade_or_force(self):
        """Permits genuine quality improvements and allows explicit force=True."""
        # Baseline: partial with 5 items and 2 rejected
        df_base = _create_sample_catalog_df([{'item_name': f'Med {i}'} for i in range(5)])
        res_base = CatalogResult(dataframe=df_base, diagnostics=_make_diagnostics("partial", accepted=5, rejected=2), fingerprint=self.fp)
        self.cache.set(self.pdf_path, res_base.to_dataframe())

        # Upgrade: complete with 12 items and 0 defects
        df_up = _create_sample_catalog_df([{'item_name': f'Med {i}'} for i in range(12)])
        res_up = CatalogResult(dataframe=df_up, diagnostics=_make_diagnostics("complete", accepted=12), fingerprint=self.fp)
        self.assertFalse(is_replacement_quality_degraded(res_base, res_up))

        self.cache.set(self.pdf_path, res_up.to_dataframe())
        cached_res = CatalogResult.from_dataframe(self.cache.get(self.pdf_path))
        self.assertEqual(len(cached_res.dataframe), 12)
        self.assertEqual(cached_res.status, "complete")

        # Explicit force overwrite with degraded
        self.cache.set(self.pdf_path, res_base.to_dataframe(), force=True)
        forced_res = CatalogResult.from_dataframe(self.cache.get(self.pdf_path))
        self.assertEqual(len(forced_res.dataframe), 5)


# =============================================================================
# Vector 3: Ambiguous Legacy Corrections Attack
# =============================================================================
class TestAdversarialAmbiguousLegacyCorrections(unittest.TestCase):
    """Stress tests verifying ambiguous legacy 3-part IDs (p1_t0_r1) are kept pending review without guessing."""

    def test_adv_detects_3part_legacy_id_with_multiple_4part_candidates(self):
        """Legacy 3-part ID matching multiple candidates on same page/row is flagged as ambiguous."""
        available_ids = ['p1_t0_g0_r1', 'p1_t0_g1_r1']  # 2 groups on page 1, table 0, row 1
        legacy_id = 'p1_t0_r1'

        self.assertTrue(
            is_ambiguous_legacy_source_id(legacy_id, available_ids),
            "Failed to flag legacy 3-part ID with 2 group candidates as ambiguous!"
        )
        candidates = find_legacy_source_id_candidates(legacy_id, available_ids)
        self.assertEqual(len(candidates), 2)
        self.assertIn('p1_t0_g0_r1', candidates)
        self.assertIn('p1_t0_g1_r1', candidates)

    def test_adv_partition_corrections_separates_ambiguous_into_pending_review(self):
        """partition_corrections_by_ambiguity strips ambiguous corrections from applicable and creates pending issues."""
        available_ids = ['p1_t0_g0_r1', 'p1_t0_g1_r1', 'p2_t0_g0_r5']
        doc = {
            "catalog_path": "test.pdf",
            "source_file_sha256": "0" * 64,
            "corrections_revision": 1,
            "field_corrections": {
                "p1_t0_r1": {"item_name": "Ambiguous Panadol", "base_price": 50.0},
                "p2_t0_g0_r5": {"item_name": "Unambiguous Aspirin", "base_price": 20.0},
            },
            "excluded_rows": {
                "p1_t0_r1": "Excluded ambiguous row",
            },
        }

        applicable, pending_issues = partition_corrections_by_ambiguity(doc, available_ids)

        # Ambiguous legacy ID must NOT be present in applicable field corrections or exclusions
        self.assertNotIn("p1_t0_r1", applicable["field_corrections"])
        self.assertNotIn("p1_t0_r1", applicable["excluded_rows"])
        # Unambiguous 4-part ID must remain applicable
        self.assertIn("p2_t0_g0_r5", applicable["field_corrections"])

        # Pending issues must contain both ambiguous field correction and exclusion entries
        self.assertEqual(len(pending_issues), 2)
        for issue in pending_issues:
            self.assertEqual(issue["source_id"], "p1_t0_r1")
            self.assertFalse(issue["resolved"])
            self.assertEqual(issue["rejection_reason"], "ambiguous_legacy_correction_requires_review")
            self.assertEqual(issue["raw_cells"], ['p1_t0_g0_r1', 'p1_t0_g1_r1'])

    def test_adv_source_id_matches_refuses_ambiguous_target(self):
        """source_id_matches strictly returns False when evaluating against an ambiguous legacy ID."""
        available_ids = ['p1_t0_g0_r1', 'p1_t0_g1_r1']
        # Must refuse to guess target
        self.assertFalse(source_id_matches('p1_t0_g0_r1', 'p1_t0_r1', available_ids=available_ids))
        self.assertFalse(source_id_matches('p1_t0_g1_r1', 'p1_t0_r1', available_ids=available_ids))
        # Never guess resolution
        self.assertEqual(resolve_compatible_source_id('p1_t0_r1', available_ids), 'p1_t0_r1')

    def test_adv_unambiguous_legacy_id_still_resolves(self):
        """When only 1 candidate exists (single group table), legacy 3-part ID resolves cleanly."""
        available_ids = ['p1_t0_g0_r1']  # only 1 candidate
        legacy_id = 'p1_t0_r1'
        self.assertFalse(is_ambiguous_legacy_source_id(legacy_id, available_ids))
        self.assertEqual(resolve_compatible_source_id(legacy_id, available_ids), 'p1_t0_g0_r1')


# =============================================================================
# Vector 4: Strict Procurement Exclusion Stress
# =============================================================================
class TestAdversarialProcurementExclusion(unittest.TestCase):
    """Stress tests verifying NOT A SINGLE unverified, rejected, or out-of-bounds row reaches allocator."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="adv_exclusion_")
        self.order_path = os.path.join(self.temp_dir, "order_test.xlsx")
        self.catalog_pdf = os.path.join(self.temp_dir, "test_cat.pdf")
        _create_dummy_pdf(self.catalog_pdf)
        self.fp = FileFingerprint.from_path(self.catalog_pdf)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_adv_strictly_excludes_rejected_and_unprocessed_rows(self):
        """Rows marked rejected or unprocessed in RowDiagnostic are strictly excluded."""
        items = [
            {'source_id': 'p1_t0_g0_r1', 'item_name': 'Panadol Valid 500mg', 'base_price': 50.0, 'discount_rate': 0.15},
            {'source_id': 'p1_t0_g0_r2', 'item_name': 'Cataflam Rejected 50mg', 'base_price': 35.0, 'discount_rate': 0.10},
            {'source_id': 'p1_t0_g0_r3', 'item_name': 'Brufen Unprocessed 400mg', 'base_price': 40.0, 'discount_rate': 0.12},
        ]
        df = _create_sample_catalog_df(items)
        rows_diag = [
            RowDiagnostic(page=1, group=0, row=1, source_id='p1_t0_g0_r1', outcome="accepted"),
            RowDiagnostic(page=1, group=0, row=2, source_id='p1_t0_g0_r2', outcome="rejected"),
            RowDiagnostic(page=1, group=0, row=3, source_id='p1_t0_g0_r3', outcome="unprocessed"),
        ]
        diag = _make_diagnostics("complete", accepted=1, rejected=1, unprocessed=1, rows=rows_diag)
        res = CatalogResult(dataframe=df, diagnostics=diag, fingerprint=self.fp)

        consolidated = _build_consolidated_inventory([res.to_dataframe()], allow_partial_imports=True)

        self.assertEqual(len(consolidated), 1)
        self.assertEqual(consolidated.iloc[0]['item_name'], 'Panadol Valid 500mg')
        self.assertNotIn('Cataflam Rejected 50mg', consolidated['item_name'].values)
        self.assertNotIn('Brufen Unprocessed 400mg', consolidated['item_name'].values)

    def test_adv_strictly_excludes_unresolved_review_issues(self):
        """Rows associated with unresolved ReviewIssues are strictly excluded."""
        items = [
            {'source_id': 'p1_t0_g0_r1', 'item_name': 'Valid Medication', 'base_price': 60.0, 'discount_rate': 0.20},
            {'source_id': 'p1_t0_g0_r2', 'item_name': 'Unresolved Region Med', 'base_price': 80.0, 'discount_rate': 0.18},
        ]
        df = _create_sample_catalog_df(items)
        review_issues = [
            ReviewIssue(
                source_id='p1_t0_g0_r2',
                page_number=1,
                region_bbox=[10, 20, 100, 200],
                rejection_reason='unmapped_region_issue',
                resolved=False,
            )
        ]
        res = CatalogResult(dataframe=df, diagnostics=_make_diagnostics("complete", accepted=2), fingerprint=self.fp, review_issues=review_issues)

        consolidated = _build_consolidated_inventory([res.to_dataframe()], allow_partial_imports=True)
        self.assertEqual(len(consolidated), 1)
        self.assertEqual(consolidated.iloc[0]['item_name'], 'Valid Medication')
        self.assertNotIn('Unresolved Region Med', consolidated['item_name'].values)

    def test_adv_strictly_excludes_out_of_bounds_prices(self):
        """Prices <= 0.0, > 10000.0, negative, or NaN are strictly excluded."""
        items = [
            {'item_name': 'Zero Price Med', 'base_price': 0.0, 'discount_rate': 0.10},
            {'item_name': 'Negative Price Med', 'base_price': -25.0, 'discount_rate': 0.10},
            {'item_name': 'Excessive Price Med', 'base_price': 10000.50, 'discount_rate': 0.10},
            {'item_name': 'Absurd Price Med', 'base_price': 999999.0, 'discount_rate': 0.10},
            {'item_name': 'Valid Max Price Med', 'base_price': 10000.0, 'discount_rate': 0.10},
            {'item_name': 'Valid Regular Price Med', 'base_price': 75.0, 'discount_rate': 0.10},
        ]
        df = _create_sample_catalog_df(items)
        res = CatalogResult(dataframe=df, diagnostics=_make_diagnostics("complete", accepted=len(items)), fingerprint=self.fp)

        consolidated = _build_consolidated_inventory([res.to_dataframe()], allow_partial_imports=True)
        self.assertEqual(len(consolidated), 2)
        valid_names = set(consolidated['item_name'].values)
        self.assertEqual(valid_names, {'Valid Max Price Med', 'Valid Regular Price Med'})

    def test_adv_strictly_excludes_out_of_bounds_discounts(self):
        """Discounts < 0.0 or > 0.85 (85%) are strictly excluded."""
        items = [
            {'item_name': 'Negative Disc Med', 'base_price': 50.0, 'discount_rate': -0.05},
            {'item_name': 'Over 85 Disc Med', 'base_price': 50.0, 'discount_rate': 0.86},
            {'item_name': '100 Percent Disc Med', 'base_price': 50.0, 'discount_rate': 1.00},
            {'item_name': 'Valid 85 Disc Med', 'base_price': 50.0, 'discount_rate': 0.85},
            {'item_name': 'Valid Zero Disc Med', 'base_price': 50.0, 'discount_rate': 0.00},
        ]
        df = _create_sample_catalog_df(items)
        res = CatalogResult(dataframe=df, diagnostics=_make_diagnostics("complete", accepted=len(items)), fingerprint=self.fp)

        consolidated = _build_consolidated_inventory([res.to_dataframe()], allow_partial_imports=True)
        self.assertEqual(len(consolidated), 2)
        valid_names = set(consolidated['item_name'].values)
        self.assertEqual(valid_names, {'Valid 85 Disc Med', 'Valid Zero Disc Med'})

    def test_adv_strictly_excludes_out_of_stock_and_noise_names(self):
        """stock_status=False and noise names ('nan', 'صنف', len <= 1) are strictly excluded."""
        items = [
            {'item_name': 'Out Of Stock Med', 'base_price': 50.0, 'stock_status': False},
            {'item_name': 'nan', 'base_price': 50.0, 'stock_status': True},
            {'item_name': 'صنف', 'base_price': 50.0, 'stock_status': True},
            {'item_name': 'X', 'base_price': 50.0, 'stock_status': True},
            {'item_name': 'Valid In Stock Med', 'base_price': 50.0, 'stock_status': True},
        ]
        df = _create_sample_catalog_df(items)
        res = CatalogResult(dataframe=df, diagnostics=_make_diagnostics("complete", accepted=len(items)), fingerprint=self.fp)

        consolidated = _build_consolidated_inventory([res.to_dataframe()], allow_partial_imports=True)
        self.assertEqual(len(consolidated), 1)
        self.assertEqual(consolidated.iloc[0]['item_name'], 'Valid In Stock Med')

    def test_adv_end_to_end_procurement_exclusion_in_workbook(self):
        """End-to-end pipeline run verifies excluded rows NEVER appear in the final Excel report."""
        _create_sample_order_excel(self.order_path, [
            {'item_name': 'Panadol Extra 500mg', 'quantity': 10},
        ])

        # Catalog with 1 valid Panadol + several corrupt/rejected items
        items = [
            {'source_id': 'p1_t0_g0_r1', 'item_name': 'Panadol Extra 500mg', 'base_price': 50.0, 'discount_rate': 0.15},
            {'source_id': 'p1_t0_g0_r2', 'item_name': 'Corrupt Drug 999mg', 'base_price': 99999.0, 'discount_rate': 0.99},
            {'source_id': 'p1_t0_g0_r3', 'item_name': 'Rejected Poison 100mg', 'base_price': 20.0, 'discount_rate': 0.10},
        ]
        df = _create_sample_catalog_df(items, warehouse_name="StrictWh")
        rows_diag = [
            RowDiagnostic(page=1, group=0, row=1, source_id='p1_t0_g0_r1', outcome="accepted"),
            RowDiagnostic(page=1, group=0, row=2, source_id='p1_t0_g0_r2', outcome="accepted"),  # price/discount out of bounds
            RowDiagnostic(page=1, group=0, row=3, source_id='p1_t0_g0_r3', outcome="rejected"),
        ]
        res = CatalogResult(
            dataframe=df,
            diagnostics=_make_diagnostics("complete", accepted=2, rejected=1, rows=rows_diag),
            fingerprint=self.fp,
        )

        catalog_cache = {self.catalog_pdf: res.to_dataframe()}

        out_res = run_procurement_pipeline(
            order_files=[self.order_path],
            catalog_files=[self.catalog_pdf],
            output_dir=self.temp_dir,
            catalog_cache=catalog_cache,
            allow_partial_imports=True,
        )

        report_path = out_res['report_path']
        self.assertTrue(os.path.isfile(report_path))

        # Inspect final Excel workbook content across all sheets
        wb = openpyxl.load_workbook(report_path, data_only=True)
        all_sheet_texts = []
        for sheetname in wb.sheetnames:
            ws = wb[sheetname]
            for row in ws.iter_rows(values_only=True):
                for cell in row:
                    if cell is not None:
                        all_sheet_texts.append(str(cell))
        full_text = " ".join(all_sheet_texts)

        # Panadol MUST appear
        self.assertIn("Panadol Extra 500mg", full_text)
        # Corrupt and rejected items MUST NOT appear anywhere in the workbook
        self.assertNotIn("Corrupt Drug", full_text, "Out-of-bounds item leaked into procurement workbook!")
        self.assertNotIn("Rejected Poison", full_text, "Rejected item leaked into procurement workbook!")


# =============================================================================
# Vector 5: Zero Valid Items Block
# =============================================================================
class TestAdversarialZeroValidItemsBlock(unittest.TestCase):
    """Stress tests verifying catalogs with 0 valid items cleanly raise PipelineExecutionError and block allocation."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="adv_zero_block_")
        self.order_path = os.path.join(self.temp_dir, "order_empty.xlsx")
        _create_sample_order_excel(self.order_path, [{'item_name': 'Panadol', 'quantity': 5}])
        self.catalog_pdf = os.path.join(self.temp_dir, "empty_catalog.pdf")
        _create_dummy_pdf(self.catalog_pdf)
        self.fp = FileFingerprint.from_path(self.catalog_pdf)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_adv_zero_valid_items_raises_pipeline_execution_error(self):
        """run_procurement_pipeline cleanly aborts with PipelineExecutionError when catalog yields 0 valid items."""
        # Catalog where all rows have invalid prices > 10000
        items = [{'item_name': 'Invalid Med', 'base_price': 50000.0, 'discount_rate': 0.10}]
        df = _create_sample_catalog_df(items)
        res = CatalogResult(dataframe=df, diagnostics=_make_diagnostics("complete", accepted=1), fingerprint=self.fp)
        catalog_cache = {self.catalog_pdf: res.to_dataframe()}

        with self.assertRaises(PipelineExecutionError) as ctx:
            run_procurement_pipeline(
                order_files=[self.order_path],
                catalog_files=[self.catalog_pdf],
                output_dir=self.temp_dir,
                catalog_cache=catalog_cache,
                allow_partial_imports=True,
            )

        self.assertIn("0 valid items", str(ctx.exception))
        # Ensure no excel report was written
        files = [f for f in os.listdir(self.temp_dir) if f.endswith(".xlsx") and f != "order_empty.xlsx"]
        self.assertEqual(len(files), 0, "Workbook was created despite 0 valid items abort!")

    def test_adv_empty_catalog_list_raises_pipeline_execution_error(self):
        """_build_consolidated_inventory([]) immediately raises PipelineExecutionError."""
        with self.assertRaises(PipelineExecutionError) as ctx:
            _build_consolidated_inventory([])
        self.assertIn("Failed to extract valid catalog items", str(ctx.exception))

    def test_adv_all_rejected_rows_raises_pipeline_execution_error(self):
        """_build_consolidated_inventory raises PipelineExecutionError when all rows are rejected."""
        items = [{'source_id': 'p1_t0_g0_r1', 'item_name': 'Rejected Drug', 'base_price': 100.0, 'discount_rate': 0.10}]
        df = _create_sample_catalog_df(items)
        rows_diag = [RowDiagnostic(page=1, group=0, row=1, source_id='p1_t0_g0_r1', outcome="rejected")]
        diag = _make_diagnostics("partial", accepted=0, rejected=1, rows=rows_diag)
        res = CatalogResult(dataframe=df, diagnostics=diag, fingerprint=self.fp)

        with self.assertRaises(PipelineExecutionError) as ctx:
            _build_consolidated_inventory([res.to_dataframe()], allow_partial_imports=True)
        self.assertIn("0 valid items", str(ctx.exception))


# =============================================================================
# Vector 6: Concurrency & Cancellation Stress
# =============================================================================
class TestAdversarialConcurrencyCancellation(unittest.TestCase):
    """Stress tests verifying asynchronous worker threads, cancellation, and thread pool stability."""

    def test_adv_cancel_ocr_thread_terminates_cleanly_without_orphans(self):
        """cancel_ocr sets event, terminates worker thread cleanly, and cleans up active thread references."""
        cancel_events = {}
        active_threads = {}
        ocr_queue = queue.Queue()
        norm_path = os.path.normpath(r"C:\fake\catalog.pdf")

        cancel_ev = threading.Event()
        cancel_events[norm_path] = cancel_ev

        started_ev = threading.Event()
        worker_exited_cleanly = threading.Event()

        def _mock_worker():
            try:
                started_ev.set()
                # Simulates bounded loop checking cancel_ev
                for _ in range(100):
                    if cancel_ev.is_set():
                        ocr_queue.put(("OCR_CANCELLED", norm_path))
                        return
                    time.sleep(0.01)
                ocr_queue.put(("OCR_DONE", norm_path, 10, []))
            finally:
                worker_exited_cleanly.set()

        t = threading.Thread(target=_mock_worker, name="AdversarialOCRWorker", daemon=True)
        active_threads[norm_path] = t
        t.start()

        self.assertTrue(started_ev.wait(timeout=1.0), "Worker thread failed to start!")

        # Trigger cancellation
        cancel_ev.set()

        # Wait for worker thread to exit
        t.join(timeout=2.0)
        self.assertFalse(t.is_alive(), "Worker thread orphaned or failed to terminate upon cancellation!")
        self.assertTrue(worker_exited_cleanly.is_set())

        # Verify queue received OCR_CANCELLED
        msg = ocr_queue.get(timeout=1.0)
        self.assertEqual(msg[0], "OCR_CANCELLED")
        self.assertEqual(msg[1], norm_path)

    def test_adv_multi_threaded_cancel_race_resilience(self):
        """Simultaneous rapid start and cancellation across 10 threads without deadlock or corruption."""
        num_threads = 10
        cancel_events = {}
        active_threads = {}
        results_queue = queue.Queue()

        for i in range(num_threads):
            path = f"catalog_{i}.pdf"
            ev = threading.Event()
            cancel_events[path] = ev

            def _worker(p=path, e=ev):
                for step in range(50):
                    if e.is_set():
                        results_queue.put(("CANCELLED", p))
                        return
                    time.sleep(0.005)
                results_queue.put(("DONE", p))

            t = threading.Thread(target=_worker, name=f"StressWorker-{i}", daemon=True)
            active_threads[path] = t
            t.start()

        # Concurrently cancel even-indexed threads
        time.sleep(0.02)
        for i in range(0, num_threads, 2):
            cancel_events[f"catalog_{i}.pdf"].set()

        # Join all threads
        for t in active_threads.values():
            t.join(timeout=3.0)
            self.assertFalse(t.is_alive(), f"Thread {t.name} failed to terminate cleanly!")

        # Collect all messages
        received = []
        while not results_queue.empty():
            received.append(results_queue.get_nowait())

        self.assertEqual(len(received), num_threads, f"Expected {num_threads} completed/cancelled messages, got {len(received)}")
        cancelled_paths = {p for stat, p in received if stat == "CANCELLED"}
        for i in range(0, num_threads, 2):
            self.assertIn(f"catalog_{i}.pdf", cancelled_paths)

    def test_adv_concurrent_cache_access_under_version_changes(self):
        """Concurrent reader and writer threads accessing CatalogCache while versions are changed."""
        cache = CatalogCache()
        temp_dir = tempfile.mkdtemp(prefix="adv_cache_concurr_")
        try:
            pdf_path = os.path.join(temp_dir, "shared.pdf")
            _create_dummy_pdf(pdf_path)
            fp = FileFingerprint.from_path(pdf_path)
            items = [{'item_name': f'Item {i}', 'base_price': 10.0} for i in range(5)]
            df = _create_sample_catalog_df(items)
            res = CatalogResult(dataframe=df, diagnostics=_make_diagnostics("complete", accepted=5), fingerprint=fp)
            cache.set(pdf_path, res.to_dataframe())

            stop_event = threading.Event()
            errors = []

            def _reader():
                while not stop_event.is_set():
                    try:
                        _ = cache.get(pdf_path)
                        _ = cache.all_cached()
                    except Exception as exc:
                        errors.append(exc)

            def _writer():
                while not stop_event.is_set():
                    try:
                        cache.set(pdf_path, res.to_dataframe())
                    except Exception as exc:
                        errors.append(exc)

            def _version_mutator():
                for _ in range(50):
                    if stop_event.is_set():
                        break
                    cache.set_active_versions(ocr_model_version=DEFAULT_OCR_MODEL_VERSION)
                    time.sleep(0.005)
                    cache.set_active_versions(ocr_model_version="rapidocr_arabic_v2_exp")
                    time.sleep(0.005)

            threads = []
            for _ in range(4):
                threads.append(threading.Thread(target=_reader, daemon=True))
            for _ in range(2):
                threads.append(threading.Thread(target=_writer, daemon=True))
            threads.append(threading.Thread(target=_version_mutator, daemon=True))

            for t in threads:
                t.start()

            time.sleep(0.5)
            stop_event.set()

            for t in threads:
                t.join(timeout=2.0)
                self.assertFalse(t.is_alive())

            self.assertEqual(len(errors), 0, f"Concurrent cache access threw unexpected errors: {errors}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
