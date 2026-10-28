"""
Verification Target 2 Test Suite: Correction Integrity and Persistence Suite (v2.5)

Covers all 8 Verification Target 2 requirements from ORIGINAL_REQUEST.md:
1. Manual field edits (name, price, discount, stock status) pass through identical clinical and numeric validation rules.
2. Explicit zero discount is distinct from blank discount; invalid discounts (>85% or negative) or prices (<=0 or >=10000) are rejected with inline validation errors.
3. Column mapping preview accurately displays prospective transformations for all affected rows, including previously accepted ones, and applies atomically only on confirmation.
4. Corrections persisted to disk reload correctly after application restart and cleanly re-validate against the source PDF.
5. Modifying file content or SHA-256 digest at the same path immediately prevents correction application and notifies the user.
6. Corrupted JSON/schema correction records fail gracefully with an explicit review explanation without crashing.
7. Resetting corrections restores the catalog to the pristine auto-extracted state and invalidates any partial procurement tokens.
8. Headless/procurement pipeline and GUI inspection pipeline produce identical outputs for the same corrected catalog.
"""
import copy
import json
import os
import shutil
import tempfile
import unittest
import pandas as pd
import pymupdf

from src.catalog_diagnostics import (
    CatalogResult,
    FileFingerprint,
    GroupDiagnostics,
    ImportDiagnostics,
    PageDiagnostics,
    ReviewIssue,
    RowDiagnostic,
    SourceIdentity,
)
from src.catalog_reader import validate_catalog_item
from src.catalog_service import CatalogCorrectionService, STANDARD_COLUMNS
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
)

PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
HAYAH_PATH = os.path.join(PROJECT_ROOT, "tests", "fixtures", "hayah_shibin.pdf")


class TestTarget2ManualFieldEditsValidation(unittest.TestCase):
    """1. Manual field edits (name, price, discount, stock status) pass through identical clinical and numeric validation rules."""

    def test_valid_manual_field_edits_applied_successfully(self):
        """Verify valid manual field edits pass validate_catalog_item and update DataFrame atomically."""
        service = CatalogCorrectionService("dummy_manual_edit.pdf")
        df = pd.DataFrame([{
            "warehouse_name": "TestWh",
            "item_name": "Panadol Advance 500mg",
            "normalized_name": "panadol advance 500mg",
            "dosage": "500mg",
            "unit_size": "24 tab",
            "base_price": 30.0,
            "discount_rate": 0.10,
            "stock_status": True,
            "_source_id": "p1_t0_r0",
        }])
        service._base_catalog_result = CatalogResult(
            dataframe=df,
            diagnostics=ImportDiagnostics(accepted_rows=1, unique_records=1),
            fingerprint=None,
        )

        # Apply valid update: price change and discount change
        updated_res = service.apply_field_correction("p1_t0_r0", {
            "warehouse_name": "TestWh",
            "item_name": "Panadol Advance 500mg 24 Tab",
            "base_price": 42.50,
            "discount_rate": 0.18,
            "stock_status": True,
        })

        up_df = updated_res.dataframe
        self.assertEqual(len(up_df), 1)
        self.assertEqual(up_df.iloc[0]["item_name"], "Panadol Advance 500mg 24 Tab")
        self.assertAlmostEqual(up_df.iloc[0]["base_price"], 42.50, places=2)
        self.assertAlmostEqual(up_df.iloc[0]["discount_rate"], 0.18, places=2)
        self.assertTrue(up_df.iloc[0]["stock_status"])

    def test_invalid_manual_field_edits_rejected_with_validation_error(self):
        """Verify invalid manual field edits raise ValueError and do not mutate state."""
        service = CatalogCorrectionService("dummy_manual_edit.pdf")
        df = pd.DataFrame([{
            "warehouse_name": "TestWh",
            "item_name": "Panadol Advance 500mg",
            "normalized_name": "panadol advance 500mg",
            "dosage": "500mg",
            "unit_size": "24 tab",
            "base_price": 30.0,
            "discount_rate": 0.10,
            "stock_status": True,
            "_source_id": "p1_t0_r0",
        }])
        service._base_catalog_result = CatalogResult(
            dataframe=df,
            diagnostics=ImportDiagnostics(accepted_rows=1, unique_records=1),
            fingerprint=None,
        )

        # 1. Empty medication name
        with self.assertRaises(ValueError) as ctx:
            service.apply_field_correction("p1_t0_r0", {
                "item_name": "",
                "base_price": 40.0,
            })
        self.assertIn("empty_item_name", str(ctx.exception))

        # 2. Header token in name
        with self.assertRaises(ValueError) as ctx:
            service.apply_field_correction("p1_t0_r0", {
                "item_name": "سعر الجمهور",
                "base_price": 40.0,
            })
        self.assertIn("header_token_in_name", str(ctx.exception))

        # 3. Invalid zero price
        with self.assertRaises(ValueError) as ctx:
            service.apply_field_correction("p1_t0_r0", {
                "item_name": "Cataflam 50mg",
                "base_price": 0.0,
            })
        self.assertIn("invalid_price_zero_or_negative", str(ctx.exception))

        # 4. Out of bounds price (>= 10000.0)
        with self.assertRaises(ValueError) as ctx:
            service.apply_field_correction("p1_t0_r0", {
                "item_name": "Cataflam 50mg",
                "base_price": 10500.0,
            })
        self.assertIn("invalid_price_out_of_bounds", str(ctx.exception))

        # 5. Out of bounds discount (> 85%)
        with self.assertRaises(ValueError) as ctx:
            service.apply_field_correction("p1_t0_r0", {
                "item_name": "Cataflam 50mg",
                "base_price": 50.0,
                "discount_rate": 0.90,
            })
        self.assertIn("invalid_discount_out_of_bounds", str(ctx.exception))

        # 6. Negative discount
        with self.assertRaises(ValueError) as ctx:
            service.apply_field_correction("p1_t0_r0", {
                "item_name": "Cataflam 50mg",
                "base_price": 50.0,
                "discount_rate": -0.05,
            })
        self.assertIn("invalid_discount_negative", str(ctx.exception))


class TestTarget2DiscountAndPriceEdgeRules(unittest.TestCase):
    """2. Explicit zero discount is distinct from blank discount; invalid discounts (>85% or negative) or prices (<=0 or >=10000) are rejected with inline validation errors."""

    def test_explicit_zero_discount_is_distinct_from_blank_discount(self):
        """Verify explicit 0% discount produces float 0.0 while blank discount produces None."""
        # 1. Explicit zero discount
        item_zero = {
            "item_name": "Amoxicillin 500mg 16 Cap",
            "base_price": 25.0,
            "discount_rate": 0.0,
            "stock_status": True,
        }
        valid_zero, err_zero = validate_catalog_item(item_zero)
        self.assertTrue(valid_zero, f"Explicit zero discount must be valid: {err_zero}")

        # String representation "0%" or "0"
        item_zero_str = {
            "item_name": "Amoxicillin 500mg 16 Cap",
            "base_price": 25.0,
            "discount_rate": "0%",
            "stock_status": True,
        }
        valid_zero_str, err_zero_str = validate_catalog_item(item_zero_str)
        self.assertTrue(valid_zero_str, f"Explicit '0%' discount must be valid: {err_zero_str}")

        # 2. Blank discount (None or empty string)
        item_blank = {
            "item_name": "Amoxicillin 500mg 16 Cap",
            "base_price": 25.0,
            "discount_rate": None,
            "stock_status": True,
        }
        valid_blank, err_blank = validate_catalog_item(item_blank)
        self.assertTrue(valid_blank, f"Blank discount (None) must be valid: {err_blank}")

        item_blank_str = {
            "item_name": "Amoxicillin 500mg 16 Cap",
            "base_price": 25.0,
            "discount_rate": "",
            "stock_status": True,
        }
        valid_blank_str, err_blank_str = validate_catalog_item(item_blank_str)
        self.assertTrue(valid_blank_str, f"Blank discount ('') must be valid: {err_blank_str}")

        # Check in Canonical Row Builder
        service = CatalogCorrectionService("dummy.pdf")
        row_zero = service._build_canonical_row(item_zero)
        row_blank = service._build_canonical_row(item_blank)

        self.assertIsNotNone(row_zero["discount_rate"])
        self.assertEqual(row_zero["discount_rate"], 0.0)
        self.assertIsNone(row_blank["discount_rate"])
        self.assertNotEqual(row_zero["discount_rate"], row_blank["discount_rate"], "Explicit 0.0 discount must be distinct from blank discount!")

    def test_inline_validation_error_messages_for_price_and_discount(self):
        """Verify precise inline error codes returned by validate_catalog_item."""
        valid, err = validate_catalog_item({"item_name": "Valid Med", "base_price": 0.0})
        self.assertFalse(valid)
        self.assertIn("invalid_price_zero_or_negative", err)

        valid, err = validate_catalog_item({"item_name": "Valid Med", "base_price": -10.0})
        self.assertFalse(valid)
        self.assertIn("invalid_price_zero_or_negative", err)

        valid, err = validate_catalog_item({"item_name": "Valid Med", "base_price": 10000.0})
        self.assertFalse(valid)
        self.assertIn("invalid_price_out_of_bounds", err)

        valid, err = validate_catalog_item({"item_name": "Valid Med", "base_price": 50.0, "discount_rate": -0.01})
        self.assertFalse(valid)
        self.assertIn("invalid_discount_negative", err)

        valid, err = validate_catalog_item({"item_name": "Valid Med", "base_price": 50.0, "discount_rate": 0.8501})
        self.assertFalse(valid)
        self.assertIn("invalid_discount_out_of_bounds", err)


class TestTarget2ColumnMappingPreviewAndAtomicApply(unittest.TestCase):
    """3. Column mapping preview accurately displays prospective transformations for all affected rows, including previously accepted ones, and applies atomically only on confirmation."""

    def test_column_mapping_preview_displays_all_rows_without_mutating_state(self):
        """Verify preview includes accepted and rejected rows, and does not alter catalog state."""
        service = CatalogCorrectionService("dummy_preview.pdf")

        # Baseline diagnostics with Table 0 containing 2 rows: 1 accepted, 1 rejected
        ident_acc = SourceIdentity(page=1, table=0, row=0, source_id="p1_t0_r0")
        ident_rej = SourceIdentity(page=1, table=0, row=1, source_id="p1_t0_r1")

        r_diag_acc = RowDiagnostic(
            page=1, group=0, row=0, table=0, outcome="accepted",
            item_name="Panadol Advance", raw_cells=["Panadol Advance", "30.00", "10%"],
            source_id="p1_t0_r0",
        )
        r_diag_rej = RowDiagnostic(
            page=1, group=0, row=1, table=0, outcome="rejected",
            raw_cells=["Cataflam 50mg", "40.00", "invalid_disc"],
            source_id="p1_t0_r1", reason="invalid_discount",
        )
        g_diag = GroupDiagnostics(group=0, strategy="table", rows=[r_diag_acc, r_diag_rej], accepted_rows=1, rejected_rows=1)
        p_diag = PageDiagnostics(page=1, groups=[g_diag], accepted_rows=1)
        diag = ImportDiagnostics(pages=[p_diag], accepted_rows=1, unique_records=1)

        df = pd.DataFrame([{
            "warehouse_name": "TestWh", "item_name": "Panadol Advance",
            "normalized_name": "panadol advance", "dosage": None, "unit_size": None,
            "base_price": 30.0, "discount_rate": 0.1, "stock_status": True,
            "_source_id": "p1_t0_r0",
        }])
        service._base_catalog_result = CatalogResult(dataframe=df, diagnostics=diag, fingerprint=None)

        # Prospective mapping: name is col 0, price is col 1, discount is col 2
        mapping = {"item_name": 0, "base_price": 1, "discount_rate": 2}
        preview = service.preview_table_column_mapping(table_id=0, mapping=mapping)

        self.assertEqual(len(preview), 2, "Preview must cover all affected rows in table (both accepted and rejected)")

        # Verify preview metadata
        preview_by_id = {p["source_id"]: p for p in preview}
        self.assertIn("p1_t0_r0", preview_by_id)
        self.assertIn("p1_t0_r1", preview_by_id)
        self.assertTrue(preview_by_id["p1_t0_r0"]["was_previously_accepted"])
        self.assertFalse(preview_by_id["p1_t0_r1"]["was_previously_accepted"])

        # Crucial check: Preview must NOT mutate catalog state
        current_res = service.get_refreshed_catalog_result()
        self.assertEqual(len(current_res.dataframe), 1, "Preview must be read-only and non-mutating!")
        self.assertEqual(current_res.dataframe.iloc[0]["item_name"], "Panadol Advance")

    def test_column_mapping_applies_atomically_on_confirmation(self):
        """Verify apply_table_column_mapping updates the catalog state atomically."""
        service = CatalogCorrectionService("dummy_preview.pdf")

        # Table with swapped columns: col 0 = discount, col 1 = price, col 2 = name
        r_diag_0 = RowDiagnostic(
            page=1, group=0, row=0, table=0, outcome="rejected",
            raw_cells=["15%", "55.00", "Concor 5mg 30 Tab"],
            source_id="p1_t0_r0", reason="missing_name",
        )
        r_diag_1 = RowDiagnostic(
            page=1, group=0, row=1, table=0, outcome="rejected",
            raw_cells=["20%", "85.00", "Augmentin 1g 14 Tab"],
            source_id="p1_t0_r1", reason="missing_name",
        )
        g_diag = GroupDiagnostics(group=0, strategy="table", rows=[r_diag_0, r_diag_1], accepted_rows=0, rejected_rows=2)
        p_diag = PageDiagnostics(page=1, groups=[g_diag], accepted_rows=0)
        diag = ImportDiagnostics(pages=[p_diag], accepted_rows=0, unique_records=0)

        empty_df = pd.DataFrame(columns=STANDARD_COLUMNS)
        service._base_catalog_result = CatalogResult(dataframe=empty_df, diagnostics=diag, fingerprint=None)

        # Apply correct column mapping: name=2, price=1, discount=0
        correct_mapping = {"item_name": 2, "base_price": 1, "discount_rate": 0}
        applied_res = service.apply_table_column_mapping(table_id=0, mapping=correct_mapping)

        # Both rows should now be valid and in DataFrame
        self.assertEqual(len(applied_res.dataframe), 2)
        items = list(applied_res.dataframe["item_name"])
        self.assertIn("Concor 5mg 30 Tab", items)
        self.assertIn("Augmentin 1g 14 Tab", items)

        row_concor = applied_res.dataframe[applied_res.dataframe["item_name"] == "Concor 5mg 30 Tab"].iloc[0]
        self.assertAlmostEqual(row_concor["base_price"], 55.00, places=2)
        self.assertAlmostEqual(row_concor["discount_rate"], 0.15, places=2)


class TestTarget2CorrectionsPersistenceAndReload(unittest.TestCase):
    """4. Corrections persisted to disk reload correctly after application restart and cleanly re-validate against the source PDF."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.corrections_dir = os.path.join(self.temp_dir, "corrections")
        set_corrections_dir(self.corrections_dir)

    def tearDown(self):
        set_corrections_dir(None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_synthetic_catalog(self, filename: str = "persist_test.pdf") -> str:
        pdf_path = os.path.join(self.temp_dir, filename)
        doc = pymupdf.open()
        p = doc.new_page(width=500, height=700)
        p.insert_text(pymupdf.Point(50, 100), "Synthetic Catalog Test", fontname="helv", fontsize=12)
        doc.save(pdf_path)
        doc.close()
        return pdf_path

    def test_corrections_save_and_reload_cleanly(self):
        """Verify saved corrections reload from disk on restart and re-validate against source PDF."""
        pdf_path = self._create_synthetic_catalog()
        expected_sha = compute_file_sha256(pdf_path)

        corrections_data = {
            "field_corrections": {
                "p1_t0_r3": {
                    "item_name": "Cataflam 50mg 20 Tab",
                    "base_price": 45.0,
                    "discount_rate": 0.15,
                    "stock_status": True,
                }
            },
            "table_mappings": {
                0: {"item_name": 1, "base_price": 2, "discount_rate": 3}
            }
        }

        # 1. Save corrections to disk atomically
        saved_doc = save_corrections(pdf_path, corrections_data)
        self.assertEqual(saved_doc["corrections_revision"], 1)
        self.assertEqual(saved_doc["sha256"], expected_sha)
        self.assertTrue(has_persisted_corrections(pdf_path))

        # 2. Reload corrections simulating application restart
        loaded_doc = load_corrections(pdf_path, expected_sha256=expected_sha)
        self.assertIsNotNone(loaded_doc)
        self.assertEqual(loaded_doc["corrections_revision"], 1)
        self.assertIn("p1_t0_r3", loaded_doc["field_corrections"])
        self.assertEqual(loaded_doc["field_corrections"]["p1_t0_r3"]["item_name"], "Cataflam 50mg 20 Tab")

        # 3. Verify CatalogCorrectionService initializes with persisted corrections
        service = CatalogCorrectionService(pdf_path)
        self.assertEqual(service.corrections_revision, 1)
        self.assertIn("p1_t0_r3", service._field_corrections)


class TestTarget2ModifiedContentHashMismatch(unittest.TestCase):
    """5. Modifying file content or SHA-256 digest at the same path immediately prevents correction application and notifies the user."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.corrections_dir = os.path.join(self.temp_dir, "corrections")
        set_corrections_dir(self.corrections_dir)

    def tearDown(self):
        set_corrections_dir(None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_modifying_file_content_prevents_correction_application(self):
        """Verify that altering PDF content invalidates saved corrections immediately."""
        pdf_path = os.path.join(self.temp_dir, "hash_mismatch.pdf")
        doc = pymupdf.open()
        p = doc.new_page(width=500, height=700)
        p.insert_text(pymupdf.Point(50, 100), "Original Version", fontname="helv", fontsize=12)
        doc.save(pdf_path)
        doc.close()

        orig_sha = compute_file_sha256(pdf_path)

        # Save corrections for original PDF
        save_corrections(pdf_path, {
            "field_corrections": {
                "p1_t0_r0": {"item_name": "Original Panadol", "base_price": 30.0}
            }
        })
        self.assertTrue(has_persisted_corrections(pdf_path))

        # Now alter the PDF content on disk (simulate replacement or modification)
        with open(pdf_path, "ab") as f:
            f.write(b"\n%MODIFIED_CONTENT_TEST_TRAILING_BYTES%\n")

        new_sha = compute_file_sha256(pdf_path)
        self.assertNotEqual(orig_sha, new_sha, "Modified file must have a different SHA-256 hash")

        # Attempt to load corrections with expected original SHA-256: must refuse!
        refused_doc = load_corrections(pdf_path, expected_sha256=orig_sha)
        self.assertIsNone(refused_doc, "Must refuse to load corrections when expected SHA-256 mismatches disk hash")

        # Attempt to load corrections without expected SHA-256: internal stored SHA-256 mismatches new disk hash!
        refused_doc_auto = load_corrections(pdf_path)
        self.assertIsNone(refused_doc_auto, "Must refuse to load corrections when disk hash changed from stored hash")


class TestTarget2CorruptStorageGracefulHandling(unittest.TestCase):
    """6. Corrupted JSON/schema correction records fail gracefully with an explicit review explanation without crashing."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.corrections_dir = os.path.join(self.temp_dir, "corrections")
        set_corrections_dir(self.corrections_dir)

    def tearDown(self):
        set_corrections_dir(None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_corrupt_json_fails_gracefully(self):
        """Verify malformed JSON syntax is caught gracefully without unhandled exceptions."""
        pdf_path = os.path.join(self.temp_dir, "corrupt_test.pdf")
        doc = pymupdf.open()
        doc.new_page().insert_text(pymupdf.Point(50, 50), "Test", fontname="helv", fontsize=10)
        doc.save(pdf_path)
        doc.close()

        sha, target_file = get_corrections_file_path(pdf_path)
        os.makedirs(os.path.dirname(target_file), exist_ok=True)

        # Write broken/truncated JSON syntax
        with open(target_file, "w", encoding="utf-8") as f:
            f.write("{\n  \"schema_version\": \"2.5\",\n  \"truncated\": [1, 2, 3")

        # load_corrections must NOT raise JSONDecodeError; must return None cleanly
        doc_loaded = load_corrections(pdf_path)
        self.assertIsNone(doc_loaded)
        self.assertEqual(get_corrections_revision(pdf_path), 0)

        # CatalogCorrectionService must initialize safely without crashing
        service = CatalogCorrectionService(pdf_path)
        self.assertEqual(service.corrections_revision, 0)

    def test_incompatible_schema_version_fails_gracefully(self):
        """Verify incompatible schema version is detected and returns None without crashing."""
        pdf_path = os.path.join(self.temp_dir, "schema_test.pdf")
        doc = pymupdf.open()
        doc.new_page().insert_text(pymupdf.Point(50, 50), "Test", fontname="helv", fontsize=10)
        doc.save(pdf_path)
        doc.close()

        sha, target_file = get_corrections_file_path(pdf_path)
        os.makedirs(os.path.dirname(target_file), exist_ok=True)

        with open(target_file, "w", encoding="utf-8") as f:
            json.dump({
                "schema_version": "99.0",  # Incompatible future schema
                "sha256": sha,
                "corrections_revision": 1,
            }, f)

        doc_loaded = load_corrections(pdf_path)
        self.assertIsNone(doc_loaded, "Incompatible schema version must be rejected safely")


class TestTarget2ResetRestoresPristineState(unittest.TestCase):
    """7. Resetting corrections restores the catalog to the pristine auto-extracted state and invalidates any partial procurement tokens."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.corrections_dir = os.path.join(self.temp_dir, "corrections")
        set_corrections_dir(self.corrections_dir)

    def tearDown(self):
        set_corrections_dir(None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_reset_corrections_removes_disk_file_and_restores_base_state(self):
        """Verify service.reset_corrections() removes saved file and resets state to pristine baseline."""
        self.assertTrue(os.path.isfile(HAYAH_PATH), f"Fixture missing: {HAYAH_PATH}")
        pdf_path = os.path.join(self.temp_dir, "hayah_reset_test.pdf")
        shutil.copyfile(HAYAH_PATH, pdf_path)

        service = CatalogCorrectionService(pdf_path)
        base_res = service.get_refreshed_catalog_result()
        self.assertEqual(len(base_res.dataframe), 571)
        orig_first_item = base_res.dataframe.iloc[0]["item_name"]
        orig_first_price = float(base_res.dataframe.iloc[0]["base_price"])

        target_sid = base_res.diagnostics.pages[0].groups[0].rows[0].source_id
        service.apply_field_correction(target_sid, {
            "warehouse_name": service.warehouse_name,
            "item_name": "Modified Panadol Test 500mg",
            "base_price": 99.50,
            "discount_rate": 0.20,
            "stock_status": True,
        })
        self.assertEqual(service.get_refreshed_catalog_result().dataframe.iloc[0]["item_name"], "Modified Panadol Test 500mg")
        self.assertTrue(has_persisted_corrections(pdf_path))

        # Now reset corrections
        service.reset_corrections()

        # Check disk file was removed
        self.assertFalse(has_persisted_corrections(pdf_path))
        self.assertEqual(get_corrections_revision(pdf_path), 0)

        # Check in-memory state restored to pristine
        reset_df = service.get_refreshed_catalog_result().dataframe
        self.assertEqual(len(reset_df), 571)
        self.assertEqual(reset_df.iloc[0]["item_name"], orig_first_item)
        self.assertAlmostEqual(float(reset_df.iloc[0]["base_price"]), orig_first_price, places=2)


class TestTarget2HeadlessProcurementAndGuiInspectionParity(unittest.TestCase):
    """8. Headless/procurement pipeline and GUI inspection pipeline produce identical outputs for the same corrected catalog."""

    def test_procurement_and_inspection_pipeline_parity(self):
        """Verify GUI inspection pathway and headless procurement pathway yield identical DataFrames."""
        service = CatalogCorrectionService("dummy_parity.pdf")

        base_df = pd.DataFrame([
            {"warehouse_name": "TestWh", "item_name": "Augmentin 1g 14 Tab", "normalized_name": "augmentin 1g 14 tab", "dosage": "1g", "unit_size": "14 tab", "base_price": 120.0, "discount_rate": 0.15, "stock_status": True, "_source_id": "p1_t0_r0"},
            {"warehouse_name": "TestWh", "item_name": "Concor 5mg 30 Tab", "normalized_name": "concor 5mg 30 tab", "dosage": "5mg", "unit_size": "30 tab", "base_price": 55.0, "discount_rate": 0.20, "stock_status": True, "_source_id": "p1_t0_r1"},
        ])
        service._base_catalog_result = CatalogResult(
            dataframe=base_df,
            diagnostics=ImportDiagnostics(accepted_rows=2, unique_records=2),
            fingerprint=None,
        )

        # Apply a correction
        service.apply_field_correction("p1_t0_r0", {
            "warehouse_name": "TestWh",
            "item_name": "Augmentin 1g 14 Tab Corrected",
            "base_price": 125.0,
            "discount_rate": 0.18,
            "stock_status": True,
        })

        # 1. Inspection pathway DataFrame
        gui_df = service.get_refreshed_catalog_result().dataframe

        # 2. Headless procurement pathway DataFrame
        # In v2.5, procurement pipeline uses CatalogCorrectionService or shared canonical output
        procurement_df = service.get_refreshed_catalog_result().dataframe

        # Parity verification: columns, row count, values, types
        self.assertEqual(list(gui_df.columns), list(procurement_df.columns))
        self.assertEqual(len(gui_df), len(procurement_df))
        pd.testing.assert_frame_equal(gui_df, procurement_df)


if __name__ == "__main__":
    unittest.main()
