"""
Unit test suite for Milestone 2B:
Atomic, Fingerprinted Correction Persistence and Cache Invalidation.

Tests:
1. Atomic Disk Save and Reload (schema 2.5, canonical path, sha256 keying)
2. Atomic Write Safety (tempfile + flush + fsync + os.replace)
3. Hash Mismatch Rejection (non-transferability to modified/changed PDFs)
4. Corrupted/Truncated Storage Graceful Recovery (no crashes, clean review explanation)
5. Reset Action (atomic purge, restored pristine state)
6. Cache Invalidation Triggers (validate_cached_catalog & FileFingerprint.is_current)
7. CatalogCorrectionService Persistence Wiring (survives restart, auto-reloads)
8. Acknowledgment Token Invalidation (tokens refresh on edit or reset)
9. Local AppData Non-Elevated Path Resolution
"""
import copy
import json
import os
import shutil
import tempfile
import unittest

import pandas as pd
import pymupdf

from src.catalog_corrections import (
    compute_file_sha256,
    get_corrections_dir,
    get_corrections_file_path,
    get_corrections_revision,
    has_persisted_corrections,
    load_corrections,
    reset_corrections,
    save_corrections,
    set_corrections_dir,
    wire_catalog_correction_service,
    SCHEMA_VERSION,
)
from src.catalog_diagnostics import (
    CatalogResult,
    FileFingerprint,
    ImportDiagnostics,
    PageDiagnostics,
    GroupDiagnostics,
    RowDiagnostic,
    SourceIdentity,
    ReviewIssue,
    METADATA_KEY,
)
from src.catalog_service import CatalogCorrectionService
from src.controller import global_catalog_cache, inspect_catalog
from src.pipeline import validate_cached_catalog


class TestMilestone2BPersistence(unittest.TestCase):
    """Comprehensive test suite for catalog corrections persistence and cache invalidation."""

    def setUp(self):
        # Create isolated temporary directory for test storage
        self.test_dir = tempfile.mkdtemp(prefix="epo_m2b_test_")
        self.corrections_dir = os.path.join(self.test_dir, "corrections")
        os.makedirs(self.corrections_dir, exist_ok=True)
        set_corrections_dir(self.corrections_dir)

        # Clear global cache
        global_catalog_cache.clear()

        # Create a mock PDF file for testing
        self.mock_pdf_path = os.path.join(self.test_dir, "test_catalog.pdf")
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 50), "Panadol Extra 24 Tab  75.00  10%  Available")
        page.insert_text((50, 80), "Cataflam 50mg 20 Tab  45.00  15%  Available")
        doc.save(self.mock_pdf_path)
        doc.close()

        self.pdf_sha256 = compute_file_sha256(self.mock_pdf_path)
        self.assertIsNotNone(self.pdf_sha256)
        self.assertEqual(len(self.pdf_sha256), 64)

        # Ensure service is wired
        wire_catalog_correction_service()

    def tearDown(self):
        set_corrections_dir(None)
        global_catalog_cache.clear()
        if os.path.exists(self.test_dir):
            try:
                shutil.rmtree(self.test_dir)
            except OSError:
                pass

    # -------------------------------------------------------------------------
    # 1. Atomic Disk Save and Reload
    # -------------------------------------------------------------------------

    def test_save_and_load_corrections_roundtrip(self):
        """Verifies that save_corrections writes schema 2.5 JSON and load_corrections reloads it faithfully."""
        field_updates = {
            "p1_t0_r0": {
                "source_id": "p1_t0_r0",
                "item_name": "Panadol Extra 24 Tab Corrected",
                "base_price": 80.0,
                "discount_rate": 0.12,
                "stock_status": True,
            }
        }
        table_mappings = {0: {"item_name": 0, "base_price": 1, "discount_rate": 2, "stock_status": 3}}

        saved_doc = save_corrections(
            catalog_path=self.mock_pdf_path,
            corrections_data={
                "field_corrections": field_updates,
                "table_mappings": table_mappings,
            },
            corrections_dir=self.corrections_dir,
        )

        self.assertEqual(saved_doc["schema_version"], SCHEMA_VERSION)
        self.assertEqual(saved_doc["sha256"], self.pdf_sha256)
        self.assertEqual(saved_doc["corrections_revision"], 1)
        self.assertIn("created_at_utc", saved_doc)
        self.assertIn("updated_at_utc", saved_doc)

        # Target file must be named <sha256>.json
        expected_json = os.path.join(self.corrections_dir, f"{self.pdf_sha256}.json")
        self.assertTrue(os.path.isfile(expected_json))

        # Reload
        loaded = load_corrections(
            self.mock_pdf_path,
            expected_sha256=self.pdf_sha256,
            corrections_dir=self.corrections_dir,
        )
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["sha256"], self.pdf_sha256)
        self.assertEqual(loaded["corrections_revision"], 1)
        self.assertIn("p1_t0_r0", loaded["field_corrections"])
        self.assertEqual(loaded["field_corrections"]["p1_t0_r0"]["item_name"], "Panadol Extra 24 Tab Corrected")
        self.assertEqual(loaded["field_corrections"]["p1_t0_r0"]["base_price"], 80.0)

    def test_monotonically_increasing_revision(self):
        """Verifies that consecutive saves increment corrections_revision and preserve created_at_utc."""
        doc1 = save_corrections(
            self.mock_pdf_path,
            {"field_corrections": {"p1_t0_r0": {"item_name": "Name 1", "base_price": 10.0}}},
            corrections_dir=self.corrections_dir,
        )
        self.assertEqual(doc1["corrections_revision"], 1)
        created_at = doc1["created_at_utc"]

        doc2 = save_corrections(
            self.mock_pdf_path,
            {"field_corrections": {"p1_t0_r0": {"item_name": "Name 2", "base_price": 20.0}}},
            corrections_dir=self.corrections_dir,
        )
        self.assertEqual(doc2["corrections_revision"], 2)
        self.assertEqual(doc2["created_at_utc"], created_at)

        self.assertEqual(get_corrections_revision(self.mock_pdf_path, self.corrections_dir), 2)

    # -------------------------------------------------------------------------
    # 2. Atomic Write Safety
    # -------------------------------------------------------------------------

    def test_atomic_write_no_temp_leakage(self):
        """Verifies that atomic write uses temporary file and leaves no orphan .tmp files."""
        save_corrections(
            self.mock_pdf_path,
            {"field_corrections": {"p1_t0_r0": {"item_name": "Test", "base_price": 10.0}}},
            corrections_dir=self.corrections_dir,
        )
        # Check files in corrections_dir: should only contain <sha256>.json
        files = os.listdir(self.corrections_dir)
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].endswith(".json"))
        self.assertFalse(any(f.endswith(".tmp") for f in files))

    # -------------------------------------------------------------------------
    # 3. Hash Mismatch Rejection (Never transfer to changed PDF)
    # -------------------------------------------------------------------------

    def test_reject_when_expected_sha256_mismatches(self):
        """load_corrections must refuse to load when expected_sha256 does not match disk."""
        save_corrections(
            self.mock_pdf_path,
            {"field_corrections": {"p1_t0_r0": {"item_name": "Panadol", "base_price": 50.0}}},
            corrections_dir=self.corrections_dir,
        )
        mismatched_sha = "0" * 64
        loaded = load_corrections(
            self.mock_pdf_path,
            expected_sha256=mismatched_sha,
            corrections_dir=self.corrections_dir,
        )
        self.assertIsNone(loaded)

    def test_refuse_transfer_when_file_content_changes(self):
        """Modifying the catalog PDF on disk must immediately prevent old corrections from applying."""
        save_corrections(
            self.mock_pdf_path,
            {"field_corrections": {"p1_t0_r0": {"item_name": "Panadol", "base_price": 50.0}}},
            corrections_dir=self.corrections_dir,
        )
        self.assertTrue(has_persisted_corrections(self.mock_pdf_path, self.corrections_dir))

        # Modify PDF content on disk
        with open(self.mock_pdf_path, "ab") as f:
            f.write(b"\n% MODIFIED CONTENT BY USER\n")

        new_sha = compute_file_sha256(self.mock_pdf_path)
        self.assertNotEqual(new_sha, self.pdf_sha256)

        # load_corrections for current file path now computes new_sha, which has no corrections
        loaded = load_corrections(self.mock_pdf_path, corrections_dir=self.corrections_dir)
        self.assertIsNone(loaded)
        self.assertFalse(has_persisted_corrections(self.mock_pdf_path, self.corrections_dir))

    # -------------------------------------------------------------------------
    # 4. Corrupted Storage Graceful Recovery
    # -------------------------------------------------------------------------

    def test_corrupt_json_graceful_recovery(self):
        """Invalid JSON syntax must return None without raising JSONDecodeError or crashing."""
        json_path = os.path.join(self.corrections_dir, f"{self.pdf_sha256}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            f.write("{{{ INVALID JSON TRUNCATED CONTENT...")

        loaded = load_corrections(self.mock_pdf_path, corrections_dir=self.corrections_dir)
        self.assertIsNone(loaded)
        self.assertEqual(get_corrections_revision(self.mock_pdf_path, self.corrections_dir), 0)

    def test_empty_file_graceful_recovery(self):
        """Empty corrections file must return None without crashing."""
        json_path = os.path.join(self.corrections_dir, f"{self.pdf_sha256}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            f.write("")

        loaded = load_corrections(self.mock_pdf_path, corrections_dir=self.corrections_dir)
        self.assertIsNone(loaded)

    def test_invalid_schema_type_graceful_recovery(self):
        """JSON array instead of object must return None without crashing."""
        json_path = os.path.join(self.corrections_dir, f"{self.pdf_sha256}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump([1, 2, 3], f)

        loaded = load_corrections(self.mock_pdf_path, corrections_dir=self.corrections_dir)
        self.assertIsNone(loaded)

    def test_schema_version_mismatch_recovery(self):
        """Incompatible schema version must return None without crashing."""
        json_path = os.path.join(self.corrections_dir, f"{self.pdf_sha256}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({
                "schema_version": "1.0",
                "sha256": self.pdf_sha256,
                "corrections": {},
            }, f)

        loaded = load_corrections(self.mock_pdf_path, corrections_dir=self.corrections_dir)
        self.assertIsNone(loaded)

    def test_internal_sha_mismatch_recovery(self):
        """Internal SHA-256 field differing from disk file must return None without crashing."""
        json_path = os.path.join(self.corrections_dir, f"{self.pdf_sha256}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({
                "schema_version": SCHEMA_VERSION,
                "sha256": "f" * 64,  # different from self.pdf_sha256
                "corrections": {},
            }, f)

        loaded = load_corrections(self.mock_pdf_path, corrections_dir=self.corrections_dir)
        self.assertIsNone(loaded)

    # -------------------------------------------------------------------------
    # 5. Reset Action
    # -------------------------------------------------------------------------

    def test_reset_corrections_deletes_file_and_restores_revision_zero(self):
        """reset_corrections atomically removes file and resets revision to 0."""
        save_corrections(
            self.mock_pdf_path,
            {"field_corrections": {"p1_t0_r0": {"item_name": "Panadol", "base_price": 50.0}}},
            corrections_dir=self.corrections_dir,
        )
        self.assertTrue(has_persisted_corrections(self.mock_pdf_path, self.corrections_dir))
        self.assertEqual(get_corrections_revision(self.mock_pdf_path, self.corrections_dir), 1)

        res = reset_corrections(self.mock_pdf_path, corrections_dir=self.corrections_dir)
        self.assertTrue(res)

        self.assertFalse(has_persisted_corrections(self.mock_pdf_path, self.corrections_dir))
        self.assertEqual(get_corrections_revision(self.mock_pdf_path, self.corrections_dir), 0)

        # Second reset is a no-op returning False
        res2 = reset_corrections(self.mock_pdf_path, corrections_dir=self.corrections_dir)
        self.assertFalse(res2)

    # -------------------------------------------------------------------------
    # 6. Cache Invalidation Triggers (validate_cached_catalog & FileFingerprint)
    # -------------------------------------------------------------------------

    def test_cache_invalidation_when_corrections_modified(self):
        """validate_cached_catalog and CatalogCache.get must reject cache when corrections revision changes."""
        # 1. Create a baseline CatalogResult with revision 0
        df_base = pd.DataFrame([
            {
                "warehouse_name": "TestWH",
                "item_name": "Panadol Extra",
                "normalized_name": "panadol extra",
                "dosage": "500mg",
                "unit_size": "24 tab",
                "base_price": 75.0,
                "discount_rate": 0.10,
                "stock_status": True,
            }
        ])
        diag = ImportDiagnostics(
            pages=[PageDiagnostics(page=1, accepted_rows=1)],
            accepted_rows=1,
            unique_records=1,
        )
        fp = FileFingerprint.from_path(self.mock_pdf_path)
        cat_res = CatalogResult(dataframe=df_base, diagnostics=diag, fingerprint=fp)
        cached_df = cat_res.to_dataframe()

        # At revision 0, cache must be valid
        self.assertIsNotNone(validate_cached_catalog(cached_df, self.mock_pdf_path))
        global_catalog_cache.set(self.mock_pdf_path, cached_df)
        self.assertIsNotNone(global_catalog_cache.get(self.mock_pdf_path))

        # 2. Modify corrections on disk (revision becomes 1)
        save_corrections(
            self.mock_pdf_path,
            {"field_corrections": {"p1_t0_r0": {"item_name": "Panadol Extra Updated", "base_price": 85.0}}},
            corrections_dir=self.corrections_dir,
        )
        self.assertEqual(get_corrections_revision(self.mock_pdf_path, self.corrections_dir), 1)

        # 3. Old cached DataFrame has revision 0 -> must be rejected as stale!
        self.assertIsNone(validate_cached_catalog(cached_df, self.mock_pdf_path))
        self.assertIsNone(global_catalog_cache.get(self.mock_pdf_path))

        # 4. Now cache the updated DataFrame with revision 1
        fp_rev1 = FileFingerprint.from_path(self.mock_pdf_path)
        cat_res_rev1 = CatalogResult(dataframe=df_base, diagnostics=diag, fingerprint=fp_rev1)
        df_rev1 = cat_res_rev1.to_dataframe()
        global_catalog_cache.set(self.mock_pdf_path, df_rev1)
        self.assertIsNotNone(validate_cached_catalog(df_rev1, self.mock_pdf_path))
        self.assertIsNotNone(global_catalog_cache.get(self.mock_pdf_path))

        # 5. Reset corrections on disk (revision returns to 0)
        reset_corrections(self.mock_pdf_path, self.corrections_dir)
        self.assertEqual(get_corrections_revision(self.mock_pdf_path, self.corrections_dir), 0)

        # 6. Cached DataFrame with revision 1 must now be rejected as stale!
        self.assertIsNone(validate_cached_catalog(df_rev1, self.mock_pdf_path))
        self.assertIsNone(global_catalog_cache.get(self.mock_pdf_path))

    # -------------------------------------------------------------------------
    # 7. CatalogCorrectionService Persistence Wiring
    # -------------------------------------------------------------------------

    def test_service_applies_and_persists_field_correction(self):
        """Applying field correction through CatalogCorrectionService persists to disk and reloads on new instance."""
        service = CatalogCorrectionService(self.mock_pdf_path)
        initial_res = service.get_refreshed_catalog_result()
        self.assertIsNotNone(initial_res)

        # Apply correction
        corr_update = {
            "item_name": "Panadol Extra 24 Tab (Persisted Edit)",
            "base_price": 88.0,
            "discount_rate": 0.15,
            "stock_status": True,
        }
        refreshed_res = service.apply_field_correction("p1_t0_r0", corr_update)
        self.assertEqual(service.corrections_revision, 1)

        # Check that file exists on disk
        self.assertTrue(has_persisted_corrections(self.mock_pdf_path, self.corrections_dir))
        disk_doc = load_corrections(self.mock_pdf_path, corrections_dir=self.corrections_dir)
        self.assertIsNotNone(disk_doc)
        self.assertIn("p1_t0_r0", disk_doc["field_corrections"])
        self.assertEqual(disk_doc["field_corrections"]["p1_t0_r0"]["item_name"], corr_update["item_name"])

        # Simulate fresh restart: create brand new CatalogCorrectionService
        new_service = CatalogCorrectionService(self.mock_pdf_path)
        self.assertEqual(new_service.corrections_revision, 1)
        self.assertIn("p1_t0_r0", new_service._field_corrections)

        restart_res = new_service.get_refreshed_catalog_result()
        # Verify the corrected item name exists in the DataFrame
        df_items = restart_res.dataframe["item_name"].tolist()
        self.assertIn("Panadol Extra 24 Tab (Persisted Edit)", df_items)

        # Reset via service
        new_service.reset_corrections()
        self.assertFalse(has_persisted_corrections(self.mock_pdf_path, self.corrections_dir))
        self.assertEqual(new_service.corrections_revision, 0)

    def test_service_applies_and_persists_table_mapping(self):
        """Applying table column mapping through CatalogCorrectionService persists to disk and reloads."""
        service = CatalogCorrectionService(self.mock_pdf_path)
        mapping = {"item_name": 0, "base_price": 1, "discount_rate": 2, "stock_status": 3}
        service.apply_table_column_mapping(0, mapping)
        self.assertEqual(service.corrections_revision, 1)

        disk_doc = load_corrections(self.mock_pdf_path, corrections_dir=self.corrections_dir)
        self.assertIsNotNone(disk_doc)
        self.assertIn("0", disk_doc["table_mappings"])

        # Brand new service instance loads mapping
        new_service = CatalogCorrectionService(self.mock_pdf_path)
        self.assertIn(0, new_service._table_mappings)
        self.assertEqual(new_service._table_mappings[0], mapping)

    # -------------------------------------------------------------------------
    # 8. Acknowledgment Token Invalidation
    # -------------------------------------------------------------------------

    def test_acknowledgment_token_invalidates_on_correction_and_reset(self):
        """Acknowledgment token must change whenever corrections are applied or reset."""
        service = CatalogCorrectionService(self.mock_pdf_path)
        res_initial = service.get_refreshed_catalog_result()
        token_initial = res_initial.acknowledgment_token

        # Apply correction
        res_corrected = service.apply_field_correction(
            "p1_t0_r0",
            {"item_name": "New Name", "base_price": 99.0, "discount_rate": 0.20, "stock_status": True},
        )
        token_corrected = res_corrected.acknowledgment_token
        self.assertNotEqual(token_initial, token_corrected)

        # Reset corrections
        res_reset = service.reset_corrections()
        token_reset = res_reset.acknowledgment_token
        self.assertNotEqual(token_corrected, token_reset)

    # -------------------------------------------------------------------------
    # 9. Inspection and Local AppData Path Resolution
    # -------------------------------------------------------------------------

    def test_inspect_catalog_applies_persisted_corrections(self):
        """inspect_catalog must automatically return corrected items when persisted corrections exist."""
        # 1. Base inspection before corrections
        base_res = inspect_catalog(self.mock_pdf_path, refresh=True)
        self.assertNotIn("Amoxicillin 500mg 16 Cap", base_res.dataframe["item_name"].tolist())

        # 2. Persist a correction
        service = CatalogCorrectionService(self.mock_pdf_path)
        service.apply_field_correction(
            "p1_t0_r0",
            {"item_name": "Amoxicillin 500mg 16 Cap", "base_price": 55.0, "discount_rate": 0.10, "stock_status": True},
        )

        # 3. inspect_catalog must return the corrected row
        inspected = inspect_catalog(self.mock_pdf_path, refresh=False)
        self.assertIn("Amoxicillin 500mg 16 Cap", inspected.dataframe["item_name"].tolist())

    def test_default_corrections_dir_resolves_to_localappdata(self):
        """get_corrections_dir defaults to %LOCALAPPDATA%/EgyptianPharmaOptimizer/data/catalog_corrections."""
        set_corrections_dir(None)  # Clear override
        cdir = get_corrections_dir()
        self.assertTrue(cdir.endswith(os.path.join("EgyptianPharmaOptimizer", "data", "catalog_corrections")))
        # Re-set test directory for teardown safety
        set_corrections_dir(self.corrections_dir)

    def test_headless_procurement_pipeline_incorporates_persisted_corrections(self):
        """Headless procurement pipeline automatically consults CatalogCorrectionService and applies persisted edits."""
        from src.pipeline import run_procurement_pipeline
        import openpyxl

        # 1. Apply and persist a field correction to the catalog
        service = CatalogCorrectionService(self.mock_pdf_path)
        service.apply_field_correction(
            "p1_t0_r0",
            {
                "item_name": "Panadol Extra 24 Tab",
                "base_price": 70.0,
                "discount_rate": 0.30,
                "stock_status": True,
            },
        )
        self.assertTrue(has_persisted_corrections(self.mock_pdf_path, self.corrections_dir))

        # 2. Create purchase order requesting Panadol Extra 24 Tab
        order_path = os.path.join(self.test_dir, "order_test.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Order"
        ws.append(["اسم الصنف", "الكمية"])
        ws.append(["Panadol Extra 24 Tab", 10])
        wb.save(order_path)

        output_dir = os.path.join(self.test_dir, "output")
        os.makedirs(output_dir, exist_ok=True)

        # 3. Run procurement pipeline without pre-existing cache
        global_catalog_cache.clear()
        res = run_procurement_pipeline(
            order_files=[order_path],
            catalog_files=[self.mock_pdf_path],
            output_dir=output_dir,
            allow_partial_imports=True,
        )

        self.assertIn("report_path", res)
        self.assertTrue(os.path.isfile(res["report_path"]))
        self.assertIn("kpis", res)
        # Verify the corrected item was processed
        self.assertGreaterEqual(res["kpis"].get("total_items", 0), 1)

    def test_atomic_write_exception_cleanup(self):
        """If atomic rename fails, temporary files must be cleaned up without leaving orphan .tmp files."""
        from unittest.mock import patch

        with patch("os.replace", side_effect=OSError("Simulated filesystem I/O error")):
            with self.assertRaises(OSError):
                save_corrections(
                    self.mock_pdf_path,
                    {"field_corrections": {"p1_t0_r0": {"item_name": "Panadol", "base_price": 50.0}}},
                    corrections_dir=self.corrections_dir,
                )

        # Ensure no temp file remains
        remaining_files = os.listdir(self.corrections_dir)
        self.assertFalse(any(f.endswith(".tmp") for f in remaining_files))

    def test_corrupt_files_in_directory_ignored_cleanly(self):
        """Unrelated or corrupted files in the corrections directory do not cause failures."""
        # Drop junk files into the directory
        with open(os.path.join(self.corrections_dir, "junk.txt"), "w") as f:
            f.write("Random junk text")
        with open(os.path.join(self.corrections_dir, "not_a_hash.json"), "w") as f:
            f.write("{invalid}")

        # Proper save and load must still work flawlessly
        save_corrections(
            self.mock_pdf_path,
            {"field_corrections": {"p1_t0_r0": {"item_name": "Panadol 500mg", "base_price": 50.0}}},
            corrections_dir=self.corrections_dir,
        )
        loaded = load_corrections(self.mock_pdf_path, corrections_dir=self.corrections_dir)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["sha256"], self.pdf_sha256)

    def test_env_var_directory_override(self):
        """EPO_CORRECTIONS_DIR environment variable correctly overrides storage directory."""
        env_custom = os.path.join(self.test_dir, "env_corrections")
        os.makedirs(env_custom, exist_ok=True)
        set_corrections_dir(None)

        try:
            os.environ["EPO_CORRECTIONS_DIR"] = env_custom
            cdir = get_corrections_dir()
            self.assertEqual(os.path.normpath(cdir), os.path.normpath(env_custom))
        finally:
            os.environ.pop("EPO_CORRECTIONS_DIR", None)
            set_corrections_dir(self.corrections_dir)


if __name__ == "__main__":
    unittest.main()
