"""
Adversarial Storage, Cache Invalidation, and Procurement Pipeline Safety Suite.
Challenger M3-2 Verification Suite.

Adversarially challenges:
1. Atomic write safety under simulated crash/write failures (verify no corrupted files or orphaned temporary files).
2. File tampering & hash verification: verify modifying even a single byte of source PDF immediately causes rejection of saved corrections.
3. Stale cache eviction: verify cache candidate is discarded when corrections revision changes or is reset.
4. Multi-threaded concurrent reads/writes to CatalogCorrectionService and CatalogCache.
5. Zero-item procurement blocking: ensure 0 valid item catalogs strictly raise PipelineExecutionError / block procurement.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock
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
    SCHEMA_VERSION,
)
from src.catalog_diagnostics import (
    CatalogResult,
    FileFingerprint,
    ImportDiagnostics,
    ReviewIssue,
    SourceIdentity,
)
from src.catalog_service import CatalogCorrectionService, STANDARD_COLUMNS
from src.controller import CatalogCache, global_catalog_cache, inspect_catalog
from src.pipeline import (
    PipelineExecutionError,
    run_procurement_pipeline,
)

PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
HAYAH_PATH = os.path.join(PROJECT_ROOT, "tests", "fixtures", "hayah_shibin.pdf")


def create_minimal_pdf(file_path: str, page_texts: list[str]) -> str:
    """Creates a minimal vector PDF containing page_texts."""
    doc = pymupdf.open()
    for text in page_texts:
        page = doc.new_page(width=595, height=842)
        if text:
            page.insert_text((50, 100), text, fontsize=12)
    doc.save(file_path)
    doc.close()
    return file_path


class TestAdversarialAtomicWriteSafety(unittest.TestCase):
    """
    Stress-tests atomic write safety under simulated crash/write failures.
    Verifies that no corrupted files or orphaned temporary files remain.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.corrections_dir = os.path.join(self.temp_dir, "corrections")
        set_corrections_dir(self.corrections_dir)

        # Create a sample PDF file
        self.pdf_path = os.path.join(self.temp_dir, "sample_catalog.pdf")
        create_minimal_pdf(self.pdf_path, ["Panadol Extra 24 Tab 45.0 0.20"])

    def tearDown(self):
        set_corrections_dir(None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_atomic_write_crash_during_dump_leaves_no_orphans_and_preserves_target(self):
        """Simulate power crash / disk full during json.dump: verify zero orphaned temp files and target integrity."""
        # 1. Establish an initial valid target file at revision 1
        initial_payload = {
            "field_corrections": {
                "p1_t0_r0": {"item_name": "Panadol 500mg", "base_price": 30.0}
            }
        }
        save_corrections(self.pdf_path, initial_payload)
        _, target_file = get_corrections_file_path(self.pdf_path)
        self.assertTrue(os.path.isfile(target_file))
        initial_mtime = os.path.getmtime(target_file)
        self.assertEqual(get_corrections_revision(self.pdf_path), 1)

        # 2. Simulate crash during json.dump on next save attempt
        with mock.patch("json.dump", side_effect=IOError("Simulated write failure / disk full")):
            with self.assertRaises(IOError):
                save_corrections(self.pdf_path, {
                    "field_corrections": {
                        "p1_t0_r0": {"item_name": "Panadol Crash", "base_price": 99.0}
                    }
                })

        # 3. Verify no orphaned .tmp files exist in the corrections directory
        all_files = os.listdir(self.corrections_dir)
        tmp_files = [f for f in all_files if f.endswith(".tmp") or f.startswith(".tmp_")]
        self.assertEqual(tmp_files, [], f"Orphaned temporary files found after crash: {tmp_files}")

        # 4. Verify existing target file was NOT corrupted and retains original revision 1
        self.assertTrue(os.path.isfile(target_file))
        doc = load_corrections(self.pdf_path)
        self.assertIsNotNone(doc)
        self.assertEqual(doc.get("corrections_revision"), 1)
        self.assertEqual(
            doc["field_corrections"]["p1_t0_r0"]["item_name"],
            "Panadol 500mg"
        )

    def test_atomic_write_failure_during_os_replace_cleans_up_temp_file(self):
        """Simulate failure during atomic rename (os.replace): verify temp file unlinked and target intact."""
        # Establish valid revision 1
        save_corrections(self.pdf_path, {"field_corrections": {"p1_t0_r0": {"item_name": "V1"}}})
        _, target_file = get_corrections_file_path(self.pdf_path)

        # Simulate PermissionError / OSError during os.replace
        with mock.patch("os.replace", side_effect=OSError("Simulated rename lock failure")):
            with self.assertRaises(OSError):
                save_corrections(self.pdf_path, {"field_corrections": {"p1_t0_r0": {"item_name": "V2"}}})

        # Verify zero temporary files left behind
        tmp_files = [f for f in os.listdir(self.corrections_dir) if f.endswith(".tmp") or f.startswith(".tmp_")]
        self.assertEqual(tmp_files, [], f"Orphaned temporary files found: {tmp_files}")

        # Target remains uncorrupted at revision 1
        doc = load_corrections(self.pdf_path)
        self.assertEqual(doc.get("corrections_revision"), 1)
        self.assertEqual(doc["field_corrections"]["p1_t0_r0"]["item_name"], "V1")

    def test_atomic_write_failure_during_fsync_cleans_up_temp_file(self):
        """Simulate failure during os.fsync: verify temp file unlinked and zero orphans."""
        with mock.patch("os.fsync", side_effect=OSError("Simulated fsync failure")):
            with self.assertRaises(OSError):
                save_corrections(self.pdf_path, {"field_corrections": {"p1_t0_r0": {"item_name": "V1"}}})

        tmp_files = [f for f in os.listdir(self.corrections_dir) if f.endswith(".tmp") or f.startswith(".tmp_")]
        self.assertEqual(tmp_files, [], f"Orphaned temporary files found: {tmp_files}")

    def test_repeated_write_crashes_accumulate_zero_garbage_files(self):
        """Execute 20 consecutive simulated crashes during save: verify zero garbage file accumulation."""
        for i in range(20):
            with mock.patch("json.dump", side_effect=IOError(f"Crash cycle {i}")):
                try:
                    save_corrections(self.pdf_path, {"field_corrections": {f"r_{i}": {"price": 10.0}}})
                except IOError:
                    pass

        files_in_dir = os.listdir(self.corrections_dir)
        tmp_files = [f for f in files_in_dir if f.endswith(".tmp") or f.startswith(".tmp_")]
        self.assertEqual(tmp_files, [], f"Garbage temporary files accumulated across crashes: {tmp_files}")


class TestAdversarialFileTamperingAndHashVerification(unittest.TestCase):
    """
    Stress-tests file tampering and hash verification.
    Verifies that mutating even a single byte of source PDF immediately causes rejection.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.corrections_dir = os.path.join(self.temp_dir, "corrections")
        set_corrections_dir(self.corrections_dir)

        # Create original PDF
        self.pdf_path = os.path.join(self.temp_dir, "catalog_secure.pdf")
        create_minimal_pdf(self.pdf_path, ["Panadol Advance 500mg 24 Tab 30.0 0.10"])

        # Persist valid corrections
        save_corrections(self.pdf_path, {
            "field_corrections": {
                "p1_t0_r0": {
                    "item_name": "Panadol Advance 500mg 24 Tab Corrected",
                    "base_price": 35.0,
                    "discount_rate": 0.15,
                    "stock_status": True,
                }
            }
        })
        self.assertTrue(has_persisted_corrections(self.pdf_path))

    def tearDown(self):
        set_corrections_dir(None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_single_byte_mutation_of_source_pdf_strictly_rejects_corrections(self):
        """Mutate a single byte in the source PDF: verify immediate rejection of saved corrections."""
        # 1. Verify corrections load cleanly before mutation
        doc_before = load_corrections(self.pdf_path)
        self.assertIsNotNone(doc_before)
        orig_sha = compute_file_sha256(self.pdf_path)

        # 2. Mutate exactly one byte in the PDF file
        with open(self.pdf_path, "r+b") as f:
            f.seek(64)
            original_byte = f.read(1)
            f.seek(64)
            # Invert the byte
            f.write(bytes([original_byte[0] ^ 0xFF]))

        mutated_sha = compute_file_sha256(self.pdf_path)
        self.assertNotEqual(orig_sha, mutated_sha, "SHA-256 must change after byte mutation.")

        # 3. Verify load_corrections strictly returns None
        doc_after = load_corrections(self.pdf_path)
        self.assertIsNone(doc_after, "Saved corrections must be rejected after single byte mutation.")

        # 4. Verify CatalogCorrectionService does NOT apply stale corrections from pre-tampered PDF
        service = CatalogCorrectionService(self.pdf_path)
        self.assertEqual(len(service._field_corrections), 0)
        self.assertEqual(service.corrections_revision, 0)

    def test_appended_trailing_byte_to_source_pdf_strictly_rejects_corrections(self):
        """Append trailing bytes to source PDF: verify hash mismatch and immediate rejection."""
        with open(self.pdf_path, "ab") as f:
            f.write(b"\n%EOF_EXTRA_TRAILING_BYTES\n")

        doc = load_corrections(self.pdf_path)
        self.assertIsNone(doc, "Corrections must be rejected when trailing bytes are appended to source PDF.")

    def test_forged_hash_filename_with_tampered_payload_strictly_rejected(self):
        """
        Adversary copies a valid corrections file to match the new SHA-256 filename,
        but internal 'sha256' or 'canonical_path' does not match disk file.
        Verify load_corrections detects internal mismatch and returns None.
        """
        # Create a second, different PDF
        other_pdf = os.path.join(self.temp_dir, "other_catalog.pdf")
        create_minimal_pdf(other_pdf, ["Other Medication 100mg 50.0 0.05"])
        other_sha = compute_file_sha256(other_pdf)

        # Attacker tries to transfer corrections: creates other_sha.json with first PDF's internal hash
        forged_file = os.path.join(self.corrections_dir, f"{other_sha}.json")
        forged_doc = {
            "schema_version": SCHEMA_VERSION,
            "canonical_path": os.path.normcase(os.path.realpath(self.pdf_path)),
            "sha256": compute_file_sha256(self.pdf_path),  # mismatch!
            "corrections_revision": 1,
            "field_corrections": {"p1_t0_r0": {"item_name": "Forged Panadol"}},
        }
        with open(forged_file, "w", encoding="utf-8") as f:
            json.dump(forged_doc, f)

        # Loading corrections for other_pdf must reject forged file
        res = load_corrections(other_pdf)
        self.assertIsNone(res, "Forged corrections file with mismatched internal SHA-256 must be rejected.")

    def test_corrupted_json_syntax_in_storage_handled_gracefully(self):
        """Truncated or corrupted JSON syntax in storage must not crash and returns None."""
        _, target_file = get_corrections_file_path(self.pdf_path)
        with open(target_file, "w", encoding="utf-8") as f:
            f.write('{"schema_version": "2.5", "table_mappings": {TRUNCATED_SYNTAX_ERROR')

        res = load_corrections(self.pdf_path)
        self.assertIsNone(res, "Corrupted JSON in corrections storage must fail gracefully returning None.")

    def test_incompatible_schema_version_in_storage_strictly_rejected(self):
        """Future schema version ('3.0') must be gracefully rejected without crash."""
        _, target_file = get_corrections_file_path(self.pdf_path)
        with open(target_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["schema_version"] = "3.0"
        with open(target_file, "w", encoding="utf-8") as f:
            json.dump(data, f)

        res = load_corrections(self.pdf_path)
        self.assertIsNone(res, "Incompatible schema version must be rejected returning None.")


class TestAdversarialStaleCacheEviction(unittest.TestCase):
    """
    Stress-tests cache invalidation triggers.
    Verifies that cache candidates are immediately evicted when corrections revision changes or is reset.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.corrections_dir = os.path.join(self.temp_dir, "corrections")
        set_corrections_dir(self.corrections_dir)

        self.pdf_path = os.path.join(self.temp_dir, "cache_catalog.pdf")
        create_minimal_pdf(self.pdf_path, ["Amoxicillin 500mg 20 Cap 25.0 0.15"])

        self.cache = CatalogCache()

    def tearDown(self):
        set_corrections_dir(None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cache_candidate_discarded_when_correction_applied(self):
        """Verify cache entry is invalidated when a new field correction is applied (revision increments)."""
        # 1. Populate both global_catalog_cache and local CatalogCache at revision 0
        df = pd.DataFrame([{
            "warehouse_name": "TestWh",
            "item_name": "Amoxicillin 500mg 20 Cap",
            "normalized_name": "amoxicillin 500mg 20 cap",
            "dosage": "500mg",
            "unit_size": "20 cap",
            "base_price": 25.0,
            "discount_rate": 0.15,
            "stock_status": True,
            "_source_id": "p1_t0_r0",
        }])
        fp = FileFingerprint.from_path(self.pdf_path)
        res0 = CatalogResult(dataframe=df, diagnostics=ImportDiagnostics(accepted_rows=1), fingerprint=fp)
        self.cache.set(self.pdf_path, res0.to_dataframe())
        global_catalog_cache.set(self.pdf_path, res0.to_dataframe())

        # Verify initial cache hits
        self.assertIsNotNone(self.cache.get(self.pdf_path))
        self.assertIsNotNone(global_catalog_cache.get(self.pdf_path))

        # 2. Apply field correction via service (revision becomes 1)
        # Using deepcopy so service has independent result copy
        service = CatalogCorrectionService(self.pdf_path)
        service._base_catalog_result = copy.deepcopy(res0)
        service.apply_field_correction("p1_t0_r0", {
            "warehouse_name": "TestWh",
            "item_name": "Amoxicillin 500mg 20 Cap Corrected",
            "base_price": 28.0,
            "discount_rate": 0.20,
            "stock_status": True,
        })
        self.assertEqual(service.corrections_revision, 1)

        # 3. Verify global_catalog_cache was explicitly evicted by service
        self.assertIsNone(
            global_catalog_cache.get(self.pdf_path),
            "global_catalog_cache must be evicted when field correction is applied."
        )

        # 4. Verify local CatalogCache detects the disk revision mismatch and returns None (eviction)
        cached_after = self.cache.get(self.pdf_path)
        self.assertIsNone(
            cached_after,
            "Stale cache candidate must be evicted after corrections revision increments on disk."
        )

    def test_cache_candidate_discarded_when_corrections_reset(self):
        """Verify cache entry is invalidated when corrections are reset back to 0."""
        # Save correction first
        save_corrections(self.pdf_path, {
            "field_corrections": {"p1_t0_r0": {"item_name": "Amoxicillin Corrected", "base_price": 28.0}}
        })
        self.assertEqual(get_corrections_revision(self.pdf_path), 1)

        # Cache result with revision 1
        df = pd.DataFrame([{
            "warehouse_name": "TestWh",
            "item_name": "Amoxicillin Corrected",
            "normalized_name": "amoxicillin corrected",
            "dosage": "500mg",
            "unit_size": "20 cap",
            "base_price": 28.0,
            "discount_rate": 0.20,
            "stock_status": True,
            "_source_id": "p1_t0_r0",
        }])
        fp = FileFingerprint.from_path(self.pdf_path)
        self.assertEqual(getattr(fp, "corrections_revision", 0), 1)

        res1 = CatalogResult(dataframe=df, diagnostics=ImportDiagnostics(accepted_rows=1), fingerprint=fp)
        self.cache.set(self.pdf_path, res1.to_dataframe())
        global_catalog_cache.set(self.pdf_path, res1.to_dataframe())
        self.assertIsNotNone(self.cache.get(self.pdf_path))
        self.assertIsNotNone(global_catalog_cache.get(self.pdf_path))

        # Reset corrections
        service = CatalogCorrectionService(self.pdf_path)
        service._base_catalog_result = copy.deepcopy(res1)
        service.reset_corrections()
        self.assertEqual(get_corrections_revision(self.pdf_path), 0)

        # Cache must evict stale revision 1 candidate
        self.assertIsNone(
            self.cache.get(self.pdf_path),
            "Local CatalogCache must evict stale revision 1 candidate when disk revision is reset to 0."
        )

        # global_catalog_cache is re-populated with pristine auto-extracted result at revision 0
        refreshed_global = global_catalog_cache.get(self.pdf_path)
        self.assertIsNotNone(
            refreshed_global,
            "global_catalog_cache should reflect pristine auto-extracted catalog after reset."
        )
        # Ensure stale correction is NOT in the restored catalog
        self.assertNotIn(
            "Amoxicillin Corrected",
            refreshed_global["item_name"].values,
            "Pristine restored catalog in cache must not contain stale corrected values."
        )

    def test_file_fingerprint_is_current_detects_revision_divergence(self):
        """Verify FileFingerprint.is_current returns False whenever persisted revision diverges."""
        # Initial fingerprint at rev 0
        fp = FileFingerprint.from_path(self.pdf_path)
        self.assertTrue(fp.is_current(self.pdf_path))

        # Bump revision
        save_corrections(self.pdf_path, {"field_corrections": {"p1_t0_r0": {"item_name": "New"}}})
        self.assertFalse(
            fp.is_current(self.pdf_path),
            "FileFingerprint.is_current must return False when disk corrections revision changes."
        )

        # New fingerprint at rev 1
        fp_rev1 = FileFingerprint.from_path(self.pdf_path)
        self.assertTrue(fp_rev1.is_current(self.pdf_path))

        # Reset corrections back to 0
        reset_corrections(self.pdf_path)
        self.assertFalse(
            fp_rev1.is_current(self.pdf_path),
            "FileFingerprint.is_current must return False after corrections are reset."
        )


class TestAdversarialMultiThreadedConcurrency(unittest.TestCase):
    """
    Stress-tests multi-threaded concurrent reads and writes to CatalogCorrectionService
    and CatalogCache under high contention.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.corrections_dir = os.path.join(self.temp_dir, "corrections")
        set_corrections_dir(self.corrections_dir)

        self.pdf_path = os.path.join(self.temp_dir, "concurrency_catalog.pdf")
        create_minimal_pdf(self.pdf_path, ["Cataflam 50mg 20 Tab 40.0 0.12"])

        # Initial baseline correction
        save_corrections(self.pdf_path, {
            "field_corrections": {
                "p1_t0_r0": {"item_name": "Cataflam Init", "base_price": 40.0}
            }
        })

    def tearDown(self):
        set_corrections_dir(None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_multithreaded_concurrent_service_corrections_and_catalog_cache(self):
        """
        Concurrently execute service.apply_field_correction, service.get_refreshed_catalog_result,
        and CatalogCache operations from multiple threads without race corruption.
        """
        service = CatalogCorrectionService(self.pdf_path)
        base_df = pd.DataFrame([{
            "warehouse_name": "TestWh",
            "item_name": "Cataflam 50mg 20 Tab",
            "normalized_name": "cataflam 50mg 20 tab",
            "dosage": "500mg",
            "unit_size": "20 tab",
            "base_price": 40.0,
            "discount_rate": 0.12,
            "stock_status": True,
            "_source_id": "p1_t0_r0",
        }])
        service._base_catalog_result = CatalogResult(
            dataframe=base_df,
            diagnostics=ImportDiagnostics(accepted_rows=1),
            fingerprint=FileFingerprint.from_path(self.pdf_path),
        )

        test_cache = CatalogCache()
        thread_errors: list[Exception] = []

        def worker_service(tid: int):
            for i in range(15):
                try:
                    res = service.apply_field_correction("p1_t0_r0", {
                        "warehouse_name": "TestWh",
                        "item_name": f"Cataflam Thread {tid} Run {i}",
                        "base_price": float(40 + tid),
                        "discount_rate": 0.15,
                        "stock_status": True,
                    })
                    assert res is not None
                    # Update cache
                    test_cache.set(self.pdf_path, res.to_dataframe())
                    # Refresh result
                    refreshed = service.get_refreshed_catalog_result()
                    assert refreshed is not None
                    # Read from cache
                    cached = test_cache.get(self.pdf_path)
                except Exception as exc:
                    thread_errors.append(exc)
                time.sleep(0.002)

        threads = [threading.Thread(target=worker_service, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15.0)

        self.assertEqual(
            thread_errors,
            [],
            f"Encountered exceptions in concurrent service/cache access: {thread_errors}"
        )

    def test_multithreaded_concurrent_save_and_load_with_retry(self):
        """
        Verify multi-threaded concurrent saves and loads across independent catalogs
        or with transient Windows file sharing retry:
        - No corrupted JSON documents are ever produced or read.
        - Zero orphaned temporary files remain.
        """
        thread_errors: list[Exception] = []
        stop_event = threading.Event()

        def writer_task(tid: int):
            for i in range(15):
                if stop_event.is_set():
                    break
                # Standard Windows retry on transient file locks
                for attempt in range(5):
                    try:
                        save_corrections(self.pdf_path, {
                            "field_corrections": {
                                "p1_t0_r0": {
                                    "item_name": f"Cataflam Thread {tid} Iter {i}",
                                    "base_price": float(40 + (tid * 10) + i),
                                    "discount_rate": 0.15,
                                }
                            }
                        })
                        break
                    except PermissionError:
                        time.sleep(0.01 * (attempt + 1))
                    except Exception as exc:
                        thread_errors.append(exc)
                        break
                time.sleep(0.005)

        def reader_task():
            for _ in range(25):
                if stop_event.is_set():
                    break
                try:
                    doc = load_corrections(self.pdf_path)
                    if doc is not None:
                        assert "field_corrections" in doc
                        assert "corrections_revision" in doc
                except Exception as exc:
                    thread_errors.append(exc)
                time.sleep(0.003)

        threads = []
        for t_idx in range(4):
            threads.append(threading.Thread(target=writer_task, args=(t_idx,)))
        for _ in range(4):
            threads.append(threading.Thread(target=reader_task))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15.0)
        stop_event.set()

        self.assertEqual(
            thread_errors,
            [],
            f"Encountered concurrency exceptions: {thread_errors}"
        )

        # Verify zero temporary files left behind
        tmp_files = [f for f in os.listdir(self.corrections_dir) if f.endswith(".tmp") or f.startswith(".tmp_")]
        self.assertEqual(tmp_files, [], f"Orphaned temporary files found: {tmp_files}")


class TestAdversarialZeroItemProcurementBlocking(unittest.TestCase):
    """
    Stress-tests procurement pipeline safety against zero-item catalogs.
    Ensures that any catalog resulting in 0 valid items strictly raises
    PipelineExecutionError and blocks procurement execution.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.order_path = os.path.join(self.temp_dir, "valid_order.xlsx")
        pd.DataFrame([{"اسم الصنف": "Panadol Extra 24 Tab", "الكمية المطلوبة": 10}]).to_excel(
            self.order_path, index=False
        )
        self.output_dir = os.path.join(self.temp_dir, "procurement_output")
        os.makedirs(self.output_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_zero_item_empty_excel_catalog_blocks_procurement(self):
        """0-row Excel catalog with standard headers must strictly raise PipelineExecutionError."""
        cat_path = os.path.join(self.temp_dir, "empty_catalog.xlsx")
        pd.DataFrame(columns=["اسم الصنف", "سعر الجمهور", "نسبة الخصم"]).to_excel(cat_path, index=False)

        with self.assertRaises(PipelineExecutionError) as ctx:
            run_procurement_pipeline(
                order_files=[self.order_path],
                catalog_files=[cat_path],
                output_dir=self.output_dir,
            )

        err_msg = str(ctx.exception).lower()
        self.assertTrue(
            any(k in err_msg for k in ["failed to extract valid", "0 valid", "no valid", "empty"]),
            f"Expected 0-item blocking error, got: {err_msg}"
        )

    def test_zero_item_pdf_catalog_with_invalid_prices_strictly_blocks_procurement(self):
        """Digital PDF catalog with rows having price <= 0 or price >= 10000 blocks procurement."""
        pdf_path = os.path.join(self.temp_dir, "invalid_prices.pdf")
        # Text with 0.00 price and 15000 price
        create_minimal_pdf(pdf_path, ["Med A 0.00 10%", "Med B 15000.00 10%"])

        with self.assertRaises(PipelineExecutionError) as ctx:
            run_procurement_pipeline(
                order_files=[self.order_path],
                catalog_files=[pdf_path],
                output_dir=self.output_dir,
            )
        err_msg = str(ctx.exception).lower()
        self.assertTrue(
            any(k in err_msg for k in ["failed to extract valid", "0 valid", "no valid"]),
            f"Expected 0-item blocking error, got: {err_msg}"
        )

    def test_zero_item_pdf_catalog_with_invalid_discounts_strictly_blocks_procurement(self):
        """Digital PDF catalog with rows where discount > 85% (0 valid items) blocks procurement."""
        pdf_path = os.path.join(self.temp_dir, "invalid_discounts.pdf")
        create_minimal_pdf(pdf_path, ["Med A 50.00 95%", "Med B 60.00 99%"])

        with self.assertRaises(PipelineExecutionError) as ctx:
            run_procurement_pipeline(
                order_files=[self.order_path],
                catalog_files=[pdf_path],
                output_dir=self.output_dir,
            )
        err_msg = str(ctx.exception).lower()
        self.assertTrue(
            any(k in err_msg for k in ["failed to extract valid", "0 valid", "no valid"]),
            f"Expected 0-item blocking error, got: {err_msg}"
        )

    def test_zero_item_all_noise_or_blank_names_blocks_procurement(self):
        """Catalog with rows having empty, NaN, or non-medication header names blocks procurement."""
        cat_path = os.path.join(self.temp_dir, "noise_names.xlsx")
        pd.DataFrame([
            {"اسم الصنف": "اسم الصنف", "سعر الجمهور": 50.0, "نسبة الخصم": 0.10},
            {"اسم الصنف": "   ", "سعر الجمهور": 60.0, "نسبة الخصم": 0.10},
            {"اسم الصنف": "صنف", "سعر الجمهور": 70.0, "نسبة الخصم": 0.10},
        ]).to_excel(cat_path, index=False)

        with self.assertRaises(PipelineExecutionError):
            run_procurement_pipeline(
                order_files=[self.order_path],
                catalog_files=[cat_path],
                output_dir=self.output_dir,
            )

    def test_zero_item_blank_vector_pdf_blocks_procurement(self):
        """Completely blank vector PDF (0 valid items extracted) strictly blocks procurement."""
        pdf_path = os.path.join(self.temp_dir, "blank_catalog.pdf")
        create_minimal_pdf(pdf_path, [""])

        with self.assertRaises(PipelineExecutionError):
            run_procurement_pipeline(
                order_files=[self.order_path],
                catalog_files=[pdf_path],
                output_dir=self.output_dir,
            )

    def test_zero_item_multi_catalog_all_zero_blocks_procurement(self):
        """When multiple catalogs are provided and ALL have 0 valid items, procurement is blocked."""
        cat1 = os.path.join(self.temp_dir, "empty_cat1.xlsx")
        pd.DataFrame(columns=["اسم الصنف", "سعر الجمهور"]).to_excel(cat1, index=False)
        cat2 = os.path.join(self.temp_dir, "empty_cat2.xlsx")
        pd.DataFrame(columns=["اسم الصنف", "سعر الجمهور"]).to_excel(cat2, index=False)

        with self.assertRaises(PipelineExecutionError):
            run_procurement_pipeline(
                order_files=[self.order_path],
                catalog_files=[cat1, cat2],
                output_dir=self.output_dir,
            )


if __name__ == "__main__":
    unittest.main()

