# -*- coding: utf-8 -*-
"""
Empirical Adversarial Stress Test Suite: Milestone 1 (Pipeline & Controller Bridge)
Author: Challenger 1 (Milestone 1)
Integrity Mode: Empirical Verification

Stress-tests:
1. Boundary conditions: empty input lists, missing files, corrupted PDFs/Excel,
   zero items, unusual filenames, and concurrent pipeline calls.
2. Verification of PipelineExecutionError cleanliness without unhandled crashes.
3. Thread safety and concurrent execution stress testing.
"""
import os
import sys
import time
import shutil
import tempfile
import threading
import traceback
import unittest
import pandas as pd
import openpyxl

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.controller import classify_files, ProcurementEngineBridge
from src.pipeline import (
    run_procurement_pipeline,
    PipelineExecutionError,
    parse_excel_catalog,
)


class TestM1ChallengerBoundaryAndStress(unittest.TestCase):
    """Adversarial challenge test suite for Milestone 1."""

    @classmethod
    def setUpClass(cls):
        cls.sample_catalog_dir = os.path.join(PROJECT_ROOT, "input", "catalogs")
        cls.sample_order_dir = os.path.join(PROJECT_ROOT, "input", "orders")

        cls.catalog_pdfs = [
            os.path.join(cls.sample_catalog_dir, f)
            for f in os.listdir(cls.sample_catalog_dir)
            if f.endswith(".pdf")
        ]
        assert len(cls.catalog_pdfs) > 0, "No sample catalog PDFs found in input/catalogs"
        cls.valid_catalog_pdf = cls.catalog_pdfs[0]

        cls.valid_order_xlsx = os.path.join(cls.sample_order_dir, "طلبية_اليوم.xlsx")
        assert os.path.exists(cls.valid_order_xlsx), f"Missing order: {cls.valid_order_xlsx}"

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="m1_challenger_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ------------------------------------------------------------------------
    # 1. EMPTY INPUT LISTS & INVALID PATHS
    # ------------------------------------------------------------------------

    def test_01_empty_order_files_raises_clean_pipeline_error(self):
        """Pipeline must raise PipelineExecutionError with input_validation stage when order_files is empty."""
        with self.assertRaises(PipelineExecutionError) as ctx:
            run_procurement_pipeline(
                order_files=[],
                catalog_files=[self.valid_catalog_pdf],
                output_dir=self.tmpdir,
            )
        err = ctx.exception
        self.assertIn("input_validation", err.diagnostics.get("stage", ""))
        self.assertEqual(err.diagnostics.get("error_type"), "ValueError")
        self.assertIn("purchase order", err.diagnostics.get("error_message", "").lower())

    def test_02_empty_catalog_files_raises_clean_pipeline_error(self):
        """Pipeline must raise PipelineExecutionError with input_validation stage when catalog_files is empty."""
        with self.assertRaises(PipelineExecutionError) as ctx:
            run_procurement_pipeline(
                order_files=[self.valid_order_xlsx],
                catalog_files=[],
                output_dir=self.tmpdir,
            )
        err = ctx.exception
        self.assertIn("input_validation", err.diagnostics.get("stage", ""))
        self.assertEqual(err.diagnostics.get("error_type"), "ValueError")
        self.assertIn("catalog", err.diagnostics.get("error_message", "").lower())

    def test_03_empty_both_files_raises_clean_pipeline_error(self):
        """Pipeline must raise PipelineExecutionError when both orders and catalogs are empty."""
        with self.assertRaises(PipelineExecutionError) as ctx:
            run_procurement_pipeline(
                order_files=[],
                catalog_files=[],
                output_dir=self.tmpdir,
            )
        err = ctx.exception
        self.assertEqual(err.diagnostics.get("stage"), "input_validation")

    def test_04_empty_output_dir_raises_clean_pipeline_error(self):
        """Pipeline must raise PipelineExecutionError when output_dir is empty or None."""
        with self.assertRaises(PipelineExecutionError) as ctx:
            run_procurement_pipeline(
                order_files=[self.valid_order_xlsx],
                catalog_files=[self.valid_catalog_pdf],
                output_dir="",
            )
        err = ctx.exception
        self.assertEqual(err.diagnostics.get("stage"), "input_validation")

    def test_05_classify_files_empty_and_falsy_inputs(self):
        """classify_files must handle empty lists, None, non-strings, and empty strings gracefully."""
        res_empty = classify_files([])
        self.assertEqual(res_empty, {"orders": [], "catalogs": [], "unknown": []})

        dirty_inputs = [None, "", 12345, [], {}, "   ", False]
        res_dirty = classify_files(dirty_inputs)
        self.assertEqual(len(res_dirty["orders"]), 0)
        self.assertEqual(len(res_dirty["catalogs"]), 0)
        self.assertEqual(len(res_dirty["unknown"]), len(dirty_inputs))

    # ------------------------------------------------------------------------
    # 2. MISSING FILES
    # ------------------------------------------------------------------------

    def test_06_nonexistent_order_files_raises_pipeline_error(self):
        """Pipeline with exclusively missing order files must fail at order_ingestion with diagnostics."""
        missing_order = os.path.join(self.tmpdir, "missing_order_xyz.xlsx")
        with self.assertRaises(PipelineExecutionError) as ctx:
            run_procurement_pipeline(
                order_files=[missing_order],
                catalog_files=[self.valid_catalog_pdf],
                output_dir=self.tmpdir,
            )
        err = ctx.exception
        self.assertEqual(err.diagnostics.get("stage"), "order_ingestion")
        self.assertIn("Failed to load valid purchase order items", err.diagnostics.get("error_message", ""))

    def test_07_nonexistent_catalog_files_raises_pipeline_error(self):
        """Pipeline with exclusively missing catalog files must fail at catalog_ingestion with diagnostics."""
        missing_cat = os.path.join(self.tmpdir, "missing_catalog_xyz.pdf")
        with self.assertRaises(PipelineExecutionError) as ctx:
            run_procurement_pipeline(
                order_files=[self.valid_order_xlsx],
                catalog_files=[missing_cat],
                output_dir=self.tmpdir,
            )
        err = ctx.exception
        self.assertEqual(err.diagnostics.get("stage"), "catalog_ingestion")
        self.assertIn("Failed to extract valid catalog items", err.diagnostics.get("error_message", ""))

    def test_08_missing_file_resilience_partial_available(self):
        """Pipeline must be resilient: if 1 of 2 catalogs is missing, it logs warning and processes the valid catalog."""
        missing_cat = os.path.join(self.tmpdir, "missing_cat_nonexistent.pdf")
        res = run_procurement_pipeline(
            order_files=[self.valid_order_xlsx],
            catalog_files=[missing_cat, self.valid_catalog_pdf],
            output_dir=self.tmpdir,
        )
        self.assertIn("results", res)
        self.assertIn("report_path", res)
        self.assertTrue(os.path.isfile(res["report_path"]))
        self.assertGreater(res["kpis"]["matched_items"], 0)

    # ------------------------------------------------------------------------
    # 3. CORRUPTED FILES (PDFs, EXCEL, CSV)
    # ------------------------------------------------------------------------

    def test_09_corrupted_zero_byte_pdf_raises_clean_pipeline_error(self):
        """Zero-byte PDF catalog must not crash PyMuPDF with unhandled panic; should raise PipelineExecutionError."""
        corrupt_pdf = os.path.join(self.tmpdir, "zero_byte_catalog.pdf")
        with open(corrupt_pdf, "wb") as f:
            pass  # 0 bytes

        with self.assertRaises(PipelineExecutionError) as ctx:
            run_procurement_pipeline(
                order_files=[self.valid_order_xlsx],
                catalog_files=[corrupt_pdf],
                output_dir=self.tmpdir,
            )
        err = ctx.exception
        self.assertEqual(err.diagnostics.get("stage"), "catalog_ingestion")
        self.assertEqual(err.diagnostics.get("catalogs_processed"), 0)

    def test_10_corrupted_binary_garbage_pdf_raises_clean_pipeline_error(self):
        """Binary garbage PDF catalog must be safely rejected without unhandled crash."""
        corrupt_pdf = os.path.join(self.tmpdir, "garbage_data.pdf")
        with open(corrupt_pdf, "wb") as f:
            f.write(b"NOT_A_REAL_PDF_HEADER_JUST_GARBAGE_BYTES_1234567890" * 50)

        with self.assertRaises(PipelineExecutionError) as ctx:
            run_procurement_pipeline(
                order_files=[self.valid_order_xlsx],
                catalog_files=[corrupt_pdf],
                output_dir=self.tmpdir,
            )
        err = ctx.exception
        self.assertEqual(err.diagnostics.get("stage"), "catalog_ingestion")

    def test_11_mixed_corrupt_and_valid_catalogs_resilience(self):
        """When 1 catalog is corrupt garbage and 1 catalog is valid, pipeline gracefully uses the valid one."""
        corrupt_pdf = os.path.join(self.tmpdir, "corrupt_garbage.pdf")
        with open(corrupt_pdf, "wb") as f:
            f.write(b"GARBAGE_BYTES_HERE")

        res = run_procurement_pipeline(
            order_files=[self.valid_order_xlsx],
            catalog_files=[corrupt_pdf, self.valid_catalog_pdf],
            output_dir=self.tmpdir,
        )
        self.assertTrue(os.path.isfile(res["report_path"]))
        self.assertGreater(res["kpis"]["matched_items"], 0)

    def test_12_corrupted_zero_byte_excel_order_raises_clean_pipeline_error(self):
        """Zero-byte Excel order file must raise clean PipelineExecutionError without crashing."""
        corrupt_order = os.path.join(self.tmpdir, "zero_byte_order.xlsx")
        with open(corrupt_order, "wb") as f:
            pass

        with self.assertRaises(PipelineExecutionError) as ctx:
            run_procurement_pipeline(
                order_files=[corrupt_order],
                catalog_files=[self.valid_catalog_pdf],
                output_dir=self.tmpdir,
            )
        err = ctx.exception
        self.assertEqual(err.diagnostics.get("stage"), "order_ingestion")

    def test_13_corrupted_text_disguised_as_excel_order(self):
        """Text file renamed to .xlsx must fail cleanly at order_ingestion."""
        fake_excel = os.path.join(self.tmpdir, "fake_order.xlsx")
        with open(fake_excel, "w", encoding="utf-8") as f:
            f.write("This is plain text and definitely not a valid zip/xlsx archive.")

        with self.assertRaises(PipelineExecutionError) as ctx:
            run_procurement_pipeline(
                order_files=[fake_excel],
                catalog_files=[self.valid_catalog_pdf],
                output_dir=self.tmpdir,
            )
        err = ctx.exception
        self.assertEqual(err.diagnostics.get("stage"), "order_ingestion")

    def test_14_parse_excel_catalog_corrupted_files_safe(self):
        """parse_excel_catalog must return empty schema for non-existent, 0-byte, and corrupt files."""
        # Non-existent
        df1 = parse_excel_catalog("nonexistent.xlsx", "test_wh")
        self.assertTrue(df1.empty)
        self.assertIn("warehouse_name", df1.columns)

        # 0-byte
        p_zero = os.path.join(self.tmpdir, "zero_cat.xlsx")
        with open(p_zero, "wb") as f:
            pass
        df2 = parse_excel_catalog(p_zero, "test_wh")
        self.assertTrue(df2.empty)

        # Corrupted CSV
        p_csv = os.path.join(self.tmpdir, "corrupt_cat.csv")
        with open(p_csv, "wb") as f:
            f.write(b"\x00\xff\xfe\x00\x00\x00\x10\x20\x30\x40")
        df3 = parse_excel_catalog(p_csv, "test_wh")
        # Should not throw unhandled error
        self.assertTrue(isinstance(df3, pd.DataFrame))

    # ------------------------------------------------------------------------
    # 4. ZERO ITEMS (EMPTY DATA TABLES)
    # ------------------------------------------------------------------------

    def test_15_empty_order_sheet_only_headers_raises_clean_pipeline_error(self):
        """Order sheet with only column headers and zero data rows must raise PipelineExecutionError."""
        empty_order = os.path.join(self.tmpdir, "empty_headers_only.xlsx")
        pd.DataFrame(columns=["اسم الصنف", "الكمية المطلوبة"]).to_excel(empty_order, index=False)

        with self.assertRaises(PipelineExecutionError) as ctx:
            run_procurement_pipeline(
                order_files=[empty_order],
                catalog_files=[self.valid_catalog_pdf],
                output_dir=self.tmpdir,
            )
        err = ctx.exception
        self.assertEqual(err.diagnostics.get("stage"), "order_ingestion")

    def test_16_order_with_only_nan_rows_raises_clean_pipeline_error(self):
        """Order sheet where all rows are NaN / empty strings must raise PipelineExecutionError."""
        nan_order = os.path.join(self.tmpdir, "nan_order.xlsx")
        df_nan = pd.DataFrame([
            {"اسم الصنف": "", "الكمية المطلوبة": None},
            {"اسم الصنف": "   ", "الكمية المطلوبة": ""},
            {"اسم الصنف": None, "الكمية المطلوبة": None},
        ])
        df_nan.to_excel(nan_order, index=False)

        with self.assertRaises(PipelineExecutionError) as ctx:
            run_procurement_pipeline(
                order_files=[nan_order],
                catalog_files=[self.valid_catalog_pdf],
                output_dir=self.tmpdir,
            )
        err = ctx.exception
        self.assertEqual(err.diagnostics.get("stage"), "order_ingestion")

    def test_17_catalog_with_zero_items_raises_clean_pipeline_error(self):
        """Excel catalog containing headers only (0 items) as sole catalog must raise PipelineExecutionError."""
        empty_cat = os.path.join(self.tmpdir, "empty_catalog.xlsx")
        pd.DataFrame(columns=["اسم الصنف", "نسبة الخصم", "سعر الجمهور"]).to_excel(empty_cat, index=False)

        with self.assertRaises(PipelineExecutionError) as ctx:
            run_procurement_pipeline(
                order_files=[self.valid_order_xlsx],
                catalog_files=[empty_cat],
                output_dir=self.tmpdir,
            )
        err = ctx.exception
        self.assertEqual(err.diagnostics.get("stage"), "catalog_ingestion")

    # ------------------------------------------------------------------------
    # 5. UNUSUAL FILENAMES, PATHS, AND NESTED DIRECTORIES
    # ------------------------------------------------------------------------

    def test_18_unusual_filename_arabic_symbols_spaces(self):
        """Order file with spaces, parentheses, hash, and Arabic chars in filename must process cleanly."""
        unusual_name = "طلبية #1 & 2 (نواقص) [خاصة]!.xlsx"
        unusual_path = os.path.join(self.tmpdir, unusual_name)

        # Create valid order content
        df_order = pd.DataFrame([
            {"اسم الصنف": "Panadol Extra 24 Tab", "الكمية المطلوبة": 6},
            {"اسم الصنف": "Cataflam 50mg 20 Tab", "الكمية المطلوبة": 4},
        ])
        df_order.to_excel(unusual_path, index=False)

        # Test classify_files
        classified = classify_files([unusual_path])
        self.assertIn(unusual_path, classified["orders"], "Unusual filename should be classified as order")

        # Test pipeline execution
        res = run_procurement_pipeline(
            order_files=[unusual_path],
            catalog_files=[self.valid_catalog_pdf],
            output_dir=self.tmpdir,
        )
        self.assertTrue(os.path.isfile(res["report_path"]))
        self.assertEqual(res["kpis"]["total_items"], 2)

    def test_19_deeply_nested_nonexistent_output_dir_created(self):
        """Pipeline must automatically create deeply nested non-existent output directories."""
        deep_dir = os.path.join(self.tmpdir, "sub1", "sub2", "sub3", "تقرير_المشتريات")
        self.assertFalse(os.path.exists(deep_dir))

        res = run_procurement_pipeline(
            order_files=[self.valid_order_xlsx],
            catalog_files=[self.valid_catalog_pdf],
            output_dir=deep_dir,
        )
        self.assertTrue(os.path.isdir(deep_dir))
        self.assertTrue(os.path.isfile(res["report_path"]))
        self.assertTrue(res["report_path"].startswith(deep_dir))

    def test_20_double_extension_classification(self):
        """Files with compound extensions (.order.pdf, .pdf.xlsx) are classified according to terminal ext and heuristics."""
        p_pdf = os.path.join(self.tmpdir, "order_list.something.pdf")
        with open(p_pdf, "wb") as f:
            f.write(b"%PDF-1.4 dummy")

        p_xlsx = os.path.join(self.tmpdir, "catalog_prices.pdf.xlsx")
        pd.DataFrame([{"اسم الصنف": "Panadol", "الخصم": "20%", "السعر": 30}]).to_excel(p_xlsx, index=False)

        classified = classify_files([p_pdf, p_xlsx])
        # .pdf is unconditionally catalog
        self.assertIn(p_pdf, classified["catalogs"])
        # .xlsx with 'catalog' and 'خصم' in content is catalog
        self.assertIn(p_xlsx, classified["catalogs"])

    # ------------------------------------------------------------------------
    # 6. CONCURRENT PIPELINE CALLS & THREAD SAFETY
    # ------------------------------------------------------------------------

    def test_21_concurrent_pipeline_execution_same_directory(self):
        """Two threads executing run_procurement_pipeline simultaneously to the same directory must not crash."""
        results = [None, None]
        errors = [None, None]

        def run_thread(idx):
            try:
                results[idx] = run_procurement_pipeline(
                    order_files=[self.valid_order_xlsx],
                    catalog_files=[self.valid_catalog_pdf],
                    output_dir=self.tmpdir,
                )
            except Exception as e:
                errors[idx] = (e, traceback.format_exc())

        t1 = threading.Thread(target=run_thread, args=(0,))
        t2 = threading.Thread(target=run_thread, args=(1,))

        t1.start()
        t2.start()
        t1.join(timeout=60.0)
        t2.join(timeout=60.0)

        self.assertIsNone(errors[0], f"Thread 0 crashed: {errors[0]}")
        self.assertIsNone(errors[1], f"Thread 1 crashed: {errors[1]}")
        self.assertIsNotNone(results[0])
        self.assertIsNotNone(results[1])

        # Both output files must exist on disk and be non-empty
        self.assertTrue(os.path.isfile(results[0]["report_path"]))
        self.assertTrue(os.path.isfile(results[1]["report_path"]))
        self.assertGreater(os.path.getsize(results[0]["report_path"]), 1000)
        self.assertGreater(os.path.getsize(results[1]["report_path"]), 1000)

    def test_22_procurement_bridge_start_while_running_raises(self):
        """Calling bridge.start() when the bridge is already running must raise RuntimeError immediately."""
        bridge = ProcurementEngineBridge()
        bridge.start(
            order_files=[self.valid_order_xlsx],
            catalog_files=[self.valid_catalog_pdf],
            output_dir=self.tmpdir,
        )
        self.assertTrue(bridge.is_running)

        with self.assertRaises(RuntimeError) as ctx:
            bridge.start(
                order_files=[self.valid_order_xlsx],
                catalog_files=[self.valid_catalog_pdf],
                output_dir=self.tmpdir,
            )
        self.assertIn("already running", str(ctx.exception).lower())

        bridge.cancel()
        bridge.join(timeout=30.0)
        self.assertFalse(bridge.is_running)

    def test_23_concurrent_classify_files_thread_safety(self):
        """classify_files called concurrently from 10 threads must return identical, correct results without race conditions."""
        test_files = [
            self.valid_catalog_pdf,
            self.valid_order_xlsx,
            os.path.join(self.tmpdir, "nonexistent.xyz"),
        ]

        thread_results = [None] * 10
        thread_errors = [None] * 10

        def worker(i):
            try:
                thread_results[i] = classify_files(test_files)
            except Exception as e:
                thread_errors[i] = str(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        for i, err in enumerate(thread_errors):
            self.assertIsNone(err, f"Thread {i} failed: {err}")

        first_res = thread_results[0]
        self.assertIn(self.valid_catalog_pdf, first_res["catalogs"])
        self.assertIn(self.valid_order_xlsx, first_res["orders"])
        for i in range(1, 10):
            self.assertEqual(thread_results[i], first_res, f"Thread {i} had inconsistent result")

    # ------------------------------------------------------------------------
    # 7. CANCELLATION & DIAGNOSTICS INTEGRITY
    # ------------------------------------------------------------------------

    def test_24_cancellation_via_cancel_check(self):
        """When cancel_check returns True midway, pipeline cleanly aborts with InterruptedError."""
        call_count = [0]

        def cancel_after_few_calls():
            call_count[0] += 1
            # Cancel after catalog ingestion starts
            return call_count[0] >= 3

        with self.assertRaises((InterruptedError, PipelineExecutionError)):
            run_procurement_pipeline(
                order_files=[self.valid_order_xlsx],
                catalog_files=[self.valid_catalog_pdf],
                output_dir=self.tmpdir,
                cancel_check=cancel_after_few_calls,
            )

    def test_25_bridge_cancellation_posts_clean_error_message(self):
        """ProcurementEngineBridge.cancel() cancels execution and enqueues ERROR message without crashing."""
        bridge = ProcurementEngineBridge()
        bridge.start(
            order_files=[self.valid_order_xlsx],
            catalog_files=[self.valid_catalog_pdf],
            output_dir=self.tmpdir,
        )
        # Cancel immediately
        bridge.cancel()
        bridge.join(timeout=30.0)

        messages = []
        while True:
            msg = bridge.get_message(block=False)
            if msg is None:
                break
            messages.append(msg)

        msg_types = [m[0] for m in messages]
        # Should have received ERROR (due to cancellation) or DONE if it miraculously completed
        self.assertTrue("ERROR" in msg_types or "DONE" in msg_types)
        if "ERROR" in msg_types:
            err_msg = next(m[1] for m in messages if m[0] == "ERROR")
            self.assertIn("cancel", err_msg.lower())


if __name__ == "__main__":
    print(f"Executing Empirical Challenger Test Suite on Python {sys.version}...")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestM1ChallengerBoundaryAndStress)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if result.wasSuccessful():
        print(f"\nALL EMPIRICAL CHALLENGE TESTS PASSED ({result.testsRun}/{result.testsRun})")
        sys.exit(0)
    else:
        print(f"\nCHALLENGE FAILURES DETECTED: {len(result.failures)} failures, {len(result.errors)} errors")
        sys.exit(1)
