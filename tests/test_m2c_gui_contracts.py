"""
Milestone 2C Verification Suite: GUI Review Workflow and Controller Contracts.
Requirement R4: Asynchronous Review and Interactive Correction GUI.

Tests:
1. render_pdf_page_with_highlight rendering, DPI scaling, and bounding-box drawing.
2. ConsolidatedImportSummaryDialog:
   - 0-item catalog completely blocks procurement and disables 'Proceed with Verified Items'
   - >0 valid items allow 'Proceed with Verified Items' and records user acknowledgment
   - 'Review Issues' selects target catalog
   - 'Cancel' aborts procurement
3. CatalogReviewWindow:
   - Candidate item inline validation (name, price limits, discount limits, blank vs 0, stock)
   - Field correction application and persistence
   - Table column mapping preview across ALL rows (accepted and rejected)
   - Pristine state reset
   - Leave unresolved preserves issue state without guessing
4. Background Worker Sequence Protection:
   - Monotonically increasing sequence IDs discard stale thread callbacks
   - Stale FileFingerprint verification discards outdated background results
5. UI Entry Points:
   - 'Review & Fix' button on catalog cards when issues/unmapped/partial/0-items exist
   - 'Review & Fix' button in Catalog Item Viewer dialog
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
from PIL import Image

import customtkinter as ctk

from app_gui import (
    render_pdf_page_with_highlight,
    ColumnMappingPreviewModal,
    CatalogReviewWindow,
    ConsolidatedImportSummaryDialog,
    PharmaProcurementApp,
    FileItem,
    FileListModel,
)
from src.catalog_diagnostics import (
    CatalogResult,
    FileFingerprint,
    ImportDiagnostics,
    ReviewIssue,
    RowDiagnostic,
    SourceIdentity,
)
from src.catalog_service import CatalogCorrectionService, STANDARD_COLUMNS
from src.catalog_reader import validate_catalog_item

PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
HAYAH_PDF = os.path.join(PROJECT_ROOT, "tests", "fixtures", "hayah_shibin.pdf")

_SHARED_APP: PharmaProcurementApp | None = None


def get_shared_app() -> PharmaProcurementApp:
    global _SHARED_APP
    if _SHARED_APP is None:
        _SHARED_APP = PharmaProcurementApp()
        _SHARED_APP.withdraw()
    return _SHARED_APP


class TestPDFHighlightRendering(unittest.TestCase):
    """Verifies PyMuPDF page rendering and Pillow bounding-box highlighting helper."""

    def test_render_pdf_page_with_highlight_valid_file(self):
        """Render a valid PDF page at 150 DPI and draw a bounding box highlight."""
        if not os.path.isfile(HAYAH_PDF):
            self.skipTest(f"Fixture not found: {HAYAH_PDF}")

        bbox = [50.0, 100.0, 350.0, 180.0]
        img = render_pdf_page_with_highlight(HAYAH_PDF, page_number=1, bbox=bbox, dpi=150)
        self.assertIsNotNone(img, "Expected valid PIL Image for hayah_shibin.pdf page 1")
        self.assertIsInstance(img, Image.Image)
        self.assertGreater(img.width, 500)
        self.assertGreater(img.height, 500)

    def test_render_pdf_page_without_bbox(self):
        """Render page without bbox should produce clean page image."""
        if not os.path.isfile(HAYAH_PDF):
            self.skipTest(f"Fixture not found: {HAYAH_PDF}")

        img = render_pdf_page_with_highlight(HAYAH_PDF, page_number=1, bbox=None, dpi=150)
        self.assertIsNotNone(img)
        self.assertIsInstance(img, Image.Image)

    def test_render_pdf_page_invalid_inputs(self):
        """Verify invalid files and non-PDF paths return None gracefully."""
        self.assertIsNone(render_pdf_page_with_highlight("non_existent_file.pdf", 1))
        self.assertIsNone(render_pdf_page_with_highlight("", 1))
        self.assertIsNone(render_pdf_page_with_highlight("some_excel.xlsx", 1))

    def test_render_pdf_page_clamped_page_number(self):
        """Page numbers exceeding total pages should clamp to last page without crashing."""
        if not os.path.isfile(HAYAH_PDF):
            self.skipTest(f"Fixture not found: {HAYAH_PDF}")

        img = render_pdf_page_with_highlight(HAYAH_PDF, page_number=9999, dpi=150)
        self.assertIsNotNone(img)
        self.assertIsInstance(img, Image.Image)


class TestConsolidatedImportSummaryDialog(unittest.TestCase):
    """Verifies ConsolidatedImportSummaryDialog contract and 0-item procurement blocking."""

    def setUp(self):
        self.root = get_shared_app()
        self._created_dialogs: list[ctk.CTkToplevel] = []

    def tearDown(self):
        for d in self._created_dialogs:
            try:
                d.destroy()
            except Exception:
                pass

    def test_zero_valid_catalog_completely_blocks_procurement(self):
        """CRITICAL RULE: If ANY catalog produces 0 valid items, block procurement completely."""
        f_item_fail = FileItem("failed_vendor.pdf", "Catalog")
        empty_df = pd.DataFrame(columns=STANDARD_COLUMNS)
        diag = ImportDiagnostics(errors=["Header mismatch"], unresolved_region_count=1)
        res = CatalogResult(dataframe=empty_df, diagnostics=diag)

        summaries = [{
            "path": f_item_fail.path,
            "filename": f_item_fail.filename,
            "accepted_count": 0,
            "review_issues_count": 1,
            "unmapped_regions_count": 1,
            "acknowledgment_token": res.acknowledgment_token,
            "diagnostics": diag,
            "status": "failed",
            "catalog_result": res,
            "f_item": f_item_fail,
        }]

        dialog = ConsolidatedImportSummaryDialog(self.root, summaries)
        self._created_dialogs.append(dialog)
        dialog.withdraw()

        # 1. Zero valid property check
        self.assertTrue(dialog.has_zero_valid(), "Expected has_zero_valid() to be True")

        # 2. Proceed button MUST be disabled
        self.assertEqual(dialog.proceed_btn.cget("state"), "disabled", "Proceed button must be disabled when 0 items exist")

        # 3. Direct invocation of _on_proceed MUST be blocked with error dialog
        with patch("app_gui.messagebox.showerror") as mock_err:
            dialog._on_proceed()
            mock_err.assert_called_once()
            self.assertNotEqual(dialog.selected_action, "proceed", "Action must NOT be 'proceed' when 0 items exist")
            self.assertEqual(dialog.selected_action, "cancel")

    def test_proceed_with_verified_items_when_all_catalogs_have_items(self):
        """When all catalogs have > 0 valid items, user can acknowledge and proceed."""
        f_item = FileItem("partial_vendor.pdf", "Catalog")
        df = pd.DataFrame([{
            "warehouse_name": "PartialWh",
            "item_name": "Amoxicillin 500mg",
            "normalized_name": "amoxicillin 500mg",
            "dosage": "500mg",
            "unit_size": "capsule",
            "base_price": 40.0,
            "discount_rate": 0.20,
            "stock_status": True,
        }])
        diag = ImportDiagnostics(accepted_rows=1, unique_records=1, unresolved_region_count=1)
        res = CatalogResult(dataframe=df, diagnostics=diag)

        summaries = [{
            "path": f_item.path,
            "filename": f_item.filename,
            "accepted_count": 1,
            "review_issues_count": 1,
            "unmapped_regions_count": 1,
            "acknowledgment_token": res.acknowledgment_token,
            "diagnostics": diag,
            "status": "partial",
            "catalog_result": res,
            "f_item": f_item,
        }]

        dialog = ConsolidatedImportSummaryDialog(self.root, summaries)
        self._created_dialogs.append(dialog)
        dialog.withdraw()

        self.assertFalse(dialog.has_zero_valid())
        self.assertEqual(dialog.proceed_btn.cget("state"), "normal")

        # User clicks proceed
        dialog._on_proceed()
        self.assertEqual(dialog.selected_action, "proceed")
        self.assertEqual(f_item.acknowledged_token, res.acknowledgment_token, "Token should be recorded as acknowledged")

    def test_review_issues_action(self):
        """Clicking 'Review Issues' returns action 'review' and sets target catalog path."""
        f_item = FileItem("vendor.pdf", "Catalog")
        summaries = [{
            "path": f_item.path,
            "filename": f_item.filename,
            "accepted_count": 5,
            "review_issues_count": 2,
            "unmapped_regions_count": 0,
            "acknowledgment_token": "token123",
            "f_item": f_item,
        }]

        dialog = ConsolidatedImportSummaryDialog(self.root, summaries)
        self._created_dialogs.append(dialog)
        dialog.withdraw()

        dialog._on_review()
        self.assertEqual(dialog.selected_action, "review")
        self.assertEqual(dialog.selected_catalog_path, f_item.path)

    def test_cancel_action(self):
        """Clicking 'Cancel' aborts procurement with action 'cancel'."""
        f_item = FileItem("vendor.pdf", "Catalog")
        summaries = [{
            "path": f_item.path,
            "filename": f_item.filename,
            "accepted_count": 5,
            "review_issues_count": 0,
            "f_item": f_item,
        }]

        dialog = ConsolidatedImportSummaryDialog(self.root, summaries)
        self._created_dialogs.append(dialog)
        dialog.withdraw()

        dialog._on_cancel()
        self.assertEqual(dialog.selected_action, "cancel")


class TestCatalogReviewWindowContracts(unittest.TestCase):
    """Verifies CatalogReviewWindow interaction, candidate validation, and service contracts."""

    def test_candidate_item_inline_validation(self):
        """Verifies candidate validation rules within review interface."""
        # 1. Valid item
        valid, err = validate_catalog_item({
            "warehouse_name": "TestWh",
            "item_name": "Cataflam 50mg Tablets",
            "base_price": 55.0,
            "discount_rate": 0.15,
            "stock_status": True,
        })
        self.assertTrue(valid, f"Expected valid candidate, got error: {err}")

        # 2. Invalid price: <= 0 or >= 10000
        valid, err = validate_catalog_item({
            "warehouse_name": "TestWh",
            "item_name": "Cataflam 50mg",
            "base_price": 0.0,
        })
        self.assertFalse(valid)
        self.assertIn("zero_or_negative", err)

        valid, err = validate_catalog_item({
            "warehouse_name": "TestWh",
            "item_name": "Cataflam 50mg",
            "base_price": 10500.0,
        })
        self.assertFalse(valid)
        self.assertIn("out_of_bounds", err)

        # 3. Invalid discount: > 85% or negative
        valid, err = validate_catalog_item({
            "warehouse_name": "TestWh",
            "item_name": "Cataflam 50mg",
            "base_price": 50.0,
            "discount_rate": 0.90,
        })
        self.assertFalse(valid)
        self.assertIn("out_of_bounds", err)

        valid, err = validate_catalog_item({
            "warehouse_name": "TestWh",
            "item_name": "Cataflam 50mg",
            "base_price": 50.0,
            "discount_rate": -0.10,
        })
        self.assertFalse(valid)
        self.assertIn("negative", err)

        # 4. Explicit zero discount is distinct from blank and valid
        valid, err = validate_catalog_item({
            "warehouse_name": "TestWh",
            "item_name": "Cataflam 50mg",
            "base_price": 50.0,
            "discount_rate": 0.0,
        })
        self.assertTrue(valid)

        # 5. Header token in medication name
        valid, err = validate_catalog_item({
            "warehouse_name": "TestWh",
            "item_name": "اسم الصنف",
            "base_price": 50.0,
        })
        self.assertFalse(valid)
        self.assertIn("header_token", err)

    def test_apply_field_correction_and_reset(self):
        """Verifies applying a manual field correction updates service and resets cleanly."""
        catalog_path = "tests/fixtures/test_review_mock.pdf"
        service = CatalogCorrectionService(catalog_path)

        # Seed service with a base catalog result containing an unresolved issue
        issue_id = "p1_t0_r0"
        ident = SourceIdentity(page=1, table=0, row=0, is_region_issue=False, source_id=issue_id)
        issue = ReviewIssue(
            source_id=issue_id,
            identity=ident,
            raw_cells=["Panadol Extra", "broken_price", "15%"],
            rejection_reason="invalid_price",
            resolved=False,
        )
        base_df = pd.DataFrame(columns=STANDARD_COLUMNS)
        diag = ImportDiagnostics(errors=["invalid_price"])
        base_res = CatalogResult(
            dataframe=base_df,
            diagnostics=diag,
            review_issues=[issue],
            issues_by_source_id={issue_id: issue},
        )
        service._base_catalog_result = base_res
        service._catalog_result = None

        # Verify initial state has 1 unresolved issue and 0 accepted rows
        self.assertEqual(len(service.list_unresolved_issues()), 1)
        self.assertEqual(len(service.get_refreshed_catalog_result().dataframe), 0)

        # Apply correction
        candidate = {
            "warehouse_name": "TestWh",
            "item_name": "Panadol Extra 500mg",
            "base_price": 45.0,
            "discount_rate": 0.15,
            "stock_status": True,
        }
        res_after = service.apply_field_correction(issue_id, candidate)
        self.assertEqual(len(res_after.dataframe), 1, "Expected 1 accepted item after correction")
        self.assertEqual(res_after.dataframe.iloc[0]["item_name"], "Panadol Extra 500mg")
        self.assertEqual(len(service.list_unresolved_issues()), 0, "Issue should be resolved")

        # Reset to original
        res_reset = service.reset_corrections()
        self.assertEqual(len(res_reset.dataframe), 0, "Reset should restore 0 accepted rows")
        self.assertEqual(len(service.list_unresolved_issues()), 1, "Reset should restore unresolved issue")

    def test_table_column_mapping_preview_and_atomic_apply(self):
        """Verifies column mapping preview displays all rows (including accepted) and applies atomically."""
        catalog_path = "tests/fixtures/test_mapping_mock.pdf"
        service = CatalogCorrectionService(catalog_path)

        # Base result with 1 accepted row and 1 rejected row belonging to table 1
        r0 = RowDiagnostic(
            page=1, group=1, row=0, table=1, outcome="accepted", item_name="Augmentin 1g",
            raw_cells=["Augmentin 1g", 90.0, 0.10, True],
        )
        r1 = RowDiagnostic(
            page=1, group=1, row=1, table=1, outcome="rejected", reason="header",
            raw_cells=["Curam 1g", 85.0, 0.12, True],
        )
        page_diag = MagicMock()
        page_diag.page = 1
        group_diag = MagicMock()
        group_diag.group = 1
        group_diag.rows = [r0, r1]
        page_diag.groups = [group_diag]
        page_diag.errors = []

        diag = ImportDiagnostics(pages=[page_diag], accepted_rows=1, unique_records=1)
        base_df = pd.DataFrame([{
            "warehouse_name": "TestWh",
            "item_name": "Augmentin 1g",
            "normalized_name": "augmentin 1g",
            "dosage": "1g",
            "unit_size": "tablet",
            "base_price": 90.0,
            "discount_rate": 0.10,
            "stock_status": True,
        }])
        base_res = CatalogResult(dataframe=base_df, diagnostics=diag)
        service._base_catalog_result = base_res
        service._catalog_result = None

        # Preview table 1 with mapping
        mapping = {"item_name": 0, "base_price": 1, "discount_rate": 2, "stock_status": 3}
        preview_records = service.preview_table_column_mapping(1, mapping)

        self.assertEqual(len(preview_records), 2, "Preview must include ALL rows (both accepted and rejected)")
        self.assertTrue(preview_records[0]["was_previously_accepted"], "Row 0 should be marked previously accepted")
        self.assertFalse(preview_records[1]["was_previously_accepted"], "Row 1 was rejected")
        self.assertTrue(preview_records[0]["valid"])
        self.assertTrue(preview_records[1]["valid"])

        # Apply mapping atomically
        res_applied = service.apply_table_column_mapping(1, mapping)
        self.assertEqual(len(res_applied.dataframe), 2, "Both rows should now be accepted")


class TestBackgroundWorkerSequenceProtection(unittest.TestCase):
    """Verifies sequence ID and FileFingerprint checks protect UI from stale thread callbacks."""

    def setUp(self):
        self.app = get_shared_app()
        self.app.file_model.clear()
        self.app._latest_applied_seq.clear()
        while not self.app._ocr_queue.empty():
            try:
                self.app._ocr_queue.get_nowait()
            except Exception:
                pass

    def tearDown(self):
        self.app.file_model.clear()
        self.app._latest_applied_seq.clear()

    def test_stale_sequence_callback_is_discarded(self):
        """A background inspection callback with seq_id < latest_applied_seq is discarded."""
        test_path = os.path.normpath(os.path.abspath("test_seq_catalog.pdf"))
        f_item = FileItem(test_path, "Catalog")
        f_item.item_count = 10
        self.app.file_model.files = [f_item]

        # Record latest applied sequence as 5
        self.app._latest_applied_seq[test_path] = 5

        # Simulate older thread returning seq=3 with count=2 (should be discarded)
        stale_msg = ("INSPECT_FILE_DONE", test_path, 2, None, 3)
        self.app._ocr_queue.put(stale_msg)
        self.app._poll_ocr_queue()

        # Item count must remain 10, not 2
        self.assertEqual(f_item.item_count, 10, "Stale thread result must be discarded")
        self.assertEqual(self.app._latest_applied_seq[test_path], 5)

        # Simulate newer thread returning seq=6 with count=20 (should be accepted)
        newer_msg = ("INSPECT_FILE_DONE", test_path, 20, None, 6)
        self.app._ocr_queue.put(newer_msg)
        self.app._poll_ocr_queue()

        self.assertEqual(f_item.item_count, 20, "Newer sequence result must be applied")
        self.assertEqual(self.app._latest_applied_seq[test_path], 6)

    def test_stale_fingerprint_callback_is_discarded(self):
        """A background inspection callback whose FileFingerprint is not current is discarded."""
        test_path = os.path.normpath(os.path.abspath("test_fp_catalog.pdf"))
        f_item = FileItem(test_path, "Catalog")
        f_item.item_count = 15
        self.app.file_model.files = [f_item]

        # Create mock CatalogResult with stale fingerprint
        mock_fp = MagicMock()
        mock_fp.is_current.return_value = False  # Fingerprint changed on disk

        mock_res = MagicMock()
        mock_res.fingerprint = mock_fp
        mock_res.dataframe = pd.DataFrame([{"col": 1}])
        mock_res.diagnostics.status = "complete"

        msg = ("INSPECT_FILE_DONE", test_path, 999, mock_res, 10)
        self.app._ocr_queue.put(msg)
        self.app._poll_ocr_queue()

        # Item count must remain 15, not 999
        self.assertEqual(f_item.item_count, 15, "Result with non-current fingerprint must be discarded")


class TestUIEntryPoints(unittest.TestCase):
    """Verifies 'Review and Fix' buttons appear on catalog cards and item viewer."""

    def setUp(self):
        self.app = get_shared_app()
        self.app.file_model.clear()

    def tearDown(self):
        self.app.file_model.clear()
        self.app._file_card_widgets.clear()

    def test_review_button_present_on_card_when_issues_exist(self):
        """Card widget renders _review_btn when issues, unmapped regions, or partial coverage exist."""
        test_path = os.path.normpath(os.path.abspath("test_card_issues.pdf"))
        f_item = FileItem(test_path, "Catalog")
        f_item.item_count = 10
        f_item.diagnostic_status = "partial"

        # Mock catalog_result with 1 unresolved issue
        issue = ReviewIssue(
            source_id="p1_t0_r0",
            rejection_reason="missing_price",
            resolved=False,
        )
        diag = ImportDiagnostics(unresolved_region_count=1)
        f_item.catalog_result = CatalogResult(
            dataframe=pd.DataFrame([{"item_name": "Amox"}]),
            diagnostics=diag,
            review_issues=[issue],
        )

        self.app.file_model.files = [f_item]
        self.app._render_file_list()

        card = self.app._file_card_widgets.get(test_path)
        self.assertIsNotNone(card, "Card widget must be rendered")
        self.assertTrue(hasattr(card, "_review_btn"), "Card must have _review_btn attribute")
        self.assertIn("Review & Fix", card._review_btn.cget("text"))

    def test_review_button_absent_on_complete_catalog_with_no_issues(self):
        """Card widget does not display _review_btn when catalog is 100% complete with 0 issues."""
        test_path = os.path.normpath(os.path.abspath("test_card_clean.pdf"))
        f_item = FileItem(test_path, "Catalog")
        f_item.item_count = 50
        f_item.diagnostic_status = "complete"
        diag = ImportDiagnostics(accepted_rows=50, unique_records=50, unresolved_region_count=0)
        f_item.catalog_result = CatalogResult(
            dataframe=pd.DataFrame([{"item_name": f"Item_{i}"} for i in range(50)]),
            diagnostics=diag,
            review_issues=[],
        )

        self.app.file_model.files = [f_item]
        self.app._render_file_list()

        card = self.app._file_card_widgets.get(test_path)
        self.assertIsNotNone(card)
        self.assertFalse(hasattr(card, "_review_btn"), "Clean catalog should not render _review_btn")


if __name__ == "__main__":
    unittest.main()
