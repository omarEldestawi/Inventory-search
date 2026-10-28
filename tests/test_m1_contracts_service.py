"""
Comprehensive Unit Tests for Milestone 1 (R1) Contracts & Service.
Verifies SourceIdentity, ReviewIssue, RowDiagnostic extension, ImportDiagnostics extension,
CatalogResult metadata plumbing, validate_catalog_item, and CatalogCorrectionService.
"""
import copy
import os
import unittest
import pandas as pd

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


class TestM1SourceIdentityAndReviewIssue(unittest.TestCase):
    """Test suite for SourceIdentity and ReviewIssue contracts."""

    def test_source_identity_row_format(self):
        ident = SourceIdentity(page=2, table=1, row=5, bbox=[10.0, 20.0, 100.0, 50.0])
        self.assertEqual(ident.source_id, "p2_t1_r5")
        self.assertFalse(ident.is_region_issue)
        self.assertEqual(ident.page, 2)
        self.assertEqual(ident.table, 1)
        self.assertEqual(ident.row, 5)

    def test_source_identity_region_format(self):
        ident = SourceIdentity(page=3, table=0, row=None, bbox=[0.0, 0.0, 500.0, 700.0])
        self.assertEqual(ident.source_id, "p3_t0_region")
        self.assertTrue(ident.is_region_issue)

    def test_source_identity_explicit_is_region_issue(self):
        ident = SourceIdentity(page=1, table=2, row=0, is_region_issue=True)
        self.assertEqual(ident.source_id, "p1_t2_region")

    def test_source_identity_roundtrip(self):
        ident = SourceIdentity(page=4, table=2, row=10, bbox=[5.0, 10.0, 20.0, 30.0])
        d = ident.to_dict()
        recovered = SourceIdentity.from_dict(d)
        self.assertEqual(ident, recovered)
        self.assertEqual(recovered.source_id, "p4_t2_r10")

    def test_review_issue_auto_source_id_from_identity(self):
        ident = SourceIdentity(page=1, table=0, row=3)
        issue = ReviewIssue(identity=ident, raw_cells=["foo", "bar"], rejection_reason="bad_price")
        self.assertEqual(issue.source_id, "p1_t0_r3")
        self.assertEqual(issue.identity.page, 1)
        self.assertEqual(issue.rejection_reason, "bad_price")
        self.assertFalse(issue.resolved)
        self.assertEqual(issue.provenance, "original_extraction")

    def test_review_issue_reconstruct_identity_from_source_id(self):
        issue = ReviewIssue(source_id="p3_t1_r7", raw_cells=[1, 2], rejection_reason="missing_name")
        self.assertIsNotNone(issue.identity)
        self.assertEqual(issue.identity.page, 3)
        self.assertEqual(issue.identity.table, 1)
        self.assertEqual(issue.identity.row, 7)
        self.assertFalse(issue.identity.is_region_issue)

    def test_review_issue_reconstruct_region_identity(self):
        issue = ReviewIssue(source_id="p2_t0_region", raw_cells=[], rejection_reason="unmapped_table")
        self.assertIsNotNone(issue.identity)
        self.assertEqual(issue.identity.page, 2)
        self.assertEqual(issue.identity.table, 0)
        self.assertIsNone(issue.identity.row)
        self.assertTrue(issue.identity.is_region_issue)

    def test_review_issue_roundtrip(self):
        ident = SourceIdentity(page=1, table=1, row=2)
        issue = ReviewIssue(
            source_id="p1_t1_r2",
            identity=ident,
            raw_cells=["A", "B", "C"],
            bbox=[1.0, 2.0, 3.0, 4.0],
            rejection_reason="test_reason",
            attempted_strategies=["coord_reextract"],
            strategy_outcomes={"coord_reextract": "failed"},
            provenance="automatic_recovery",
            resolved=True,
            item={"item_name": "Panadol"},
        )
        d = issue.to_dict()
        recovered = ReviewIssue.from_dict(d)
        self.assertEqual(recovered.source_id, "p1_t1_r2")
        self.assertEqual(recovered.identity.page, 1)
        self.assertEqual(recovered.attempted_strategies, ["coord_reextract"])
        self.assertTrue(recovered.resolved)
        self.assertEqual(recovered.item, {"item_name": "Panadol"})


class TestM1DiagnosticExtensions(unittest.TestCase):
    """Test suite for RowDiagnostic, ImportDiagnostics, and CatalogResult extensions."""

    def test_row_diagnostic_backward_compatible(self):
        """Calling RowDiagnostic with original 8 arguments works identically."""
        r = RowDiagnostic(
            page=1,
            group=0,
            row=2,
            outcome="rejected",
            reason="invalid_price",
            bbox=[0.0, 0.0, 10.0, 10.0],
            raw_cells=["cell1", "cell2"],
            item_name="Drug A",
        )
        self.assertEqual(r.page, 1)
        self.assertEqual(r.group, 0)
        self.assertEqual(r.row, 2)
        self.assertEqual(r.outcome, "rejected")
        self.assertEqual(r.table, 0)
        self.assertEqual(r.source_id, "p1_t0_r2")
        self.assertEqual(r.provenance, "original_extraction")

    def test_row_diagnostic_to_review_issue(self):
        r = RowDiagnostic(
            page=2,
            group=1,
            row=4,
            outcome="rejected",
            reason="zero_price",
            table=1,
            item_name="Ketofan 50mg",
        )
        self.assertEqual(r.source_id, "p2_t1_r4")
        issue = r.to_review_issue()
        self.assertIsInstance(issue, ReviewIssue)
        self.assertEqual(issue.source_id, "p2_t1_r4")
        self.assertEqual(issue.identity.page, 2)
        self.assertEqual(issue.identity.table, 1)
        self.assertEqual(issue.identity.row, 4)
        self.assertEqual(issue.rejection_reason, "zero_price")
        self.assertFalse(issue.resolved)

    def test_import_diagnostics_new_fields(self):
        diag = ImportDiagnostics(
            unresolved_region_count=2,
            attempted_recovery_count=5,
            successful_recovery_count=3,
        )
        self.assertEqual(diag.unresolved_region_count, 2)
        self.assertEqual(diag.attempted_recovery_count, 5)
        self.assertEqual(diag.successful_recovery_count, 3)
        self.assertEqual(diag.status, "failed")

    def test_import_diagnostics_roundtrip_with_new_fields(self):
        diag = ImportDiagnostics(
            accepted_rows=10,
            unique_records=10,
            unresolved_region_count=1,
            attempted_recovery_count=4,
            successful_recovery_count=2,
        )
        d = diag.to_dict()
        recovered = ImportDiagnostics.from_dict(d)
        self.assertEqual(recovered.unresolved_region_count, 1)
        self.assertEqual(recovered.attempted_recovery_count, 4)
        self.assertEqual(recovered.successful_recovery_count, 2)

    def test_catalog_result_review_issues_auto_indexing(self):
        ident = SourceIdentity(page=1, table=0, row=1)
        issue = ReviewIssue(source_id="p1_t0_r1", identity=ident, rejection_reason="bad_disc")
        res = CatalogResult(
            dataframe=pd.DataFrame(columns=STANDARD_COLUMNS),
            diagnostics=ImportDiagnostics(),
            review_issues=[issue],
        )
        self.assertIn("p1_t0_r1", res.issues_by_source_id)
        self.assertEqual(res.issues_by_source_id["p1_t0_r1"], issue)

    def test_catalog_result_roundtrip_through_dataframe_with_review_issues(self):
        df = pd.DataFrame([
            ["Warehouse A", "Panadol 500mg", "panadol 500mg", "500mg", "24tab", 30.0, 0.10, True]
        ], columns=STANDARD_COLUMNS)
        ident = SourceIdentity(page=1, table=0, row=2)
        issue = ReviewIssue(source_id="p1_t0_r2", identity=ident, rejection_reason="bad_price")
        res = CatalogResult(
            dataframe=df,
            diagnostics=ImportDiagnostics(unique_records=1, accepted_rows=1),
            review_issues=[issue],
        )

        df_out = res.to_dataframe()
        self.assertEqual(list(df_out.columns), STANDARD_COLUMNS)

        recovered = CatalogResult.from_dataframe(df_out)
        self.assertIsNotNone(recovered)
        self.assertEqual(len(recovered.dataframe), 1)
        self.assertEqual(len(recovered.review_issues), 1)
        self.assertIn("p1_t0_r2", recovered.issues_by_source_id)
        self.assertEqual(recovered.issues_by_source_id["p1_t0_r2"].rejection_reason, "bad_price")


class TestM1ValidateCatalogItem(unittest.TestCase):
    """Test suite for canonical validate_catalog_item."""

    def test_valid_item_standard(self):
        item = {
            "item_name": "Panadol Extra 500mg",
            "base_price": 45.0,
            "discount_rate": 0.20,
            "stock_status": True,
        }
        valid, err = validate_catalog_item(item)
        self.assertTrue(valid)
        self.assertIsNone(err)

    def test_valid_item_with_explicit_zero_discount(self):
        # 0.0 is explicitly allowed
        item = {
            "item_name": "Cataflam 50mg",
            "base_price": 33.5,
            "discount_rate": 0.0,
        }
        valid, err = validate_catalog_item(item)
        self.assertTrue(valid)
        self.assertIsNone(err)

    def test_valid_item_with_blank_discount_none(self):
        # None is blank discount, distinct from 0.0, explicitly allowed
        item = {
            "item_name": "Amoxil 500mg",
            "base_price": 28.0,
            "discount_rate": None,
        }
        valid, err = validate_catalog_item(item)
        self.assertTrue(valid)
        self.assertIsNone(err)

    def test_valid_item_with_string_explicit_zero_discount(self):
        item = {
            "item_name": "Brufen 400mg",
            "base_price": 50.0,
            "discount_rate": "صافي",
        }
        valid, err = validate_catalog_item(item)
        self.assertTrue(valid)
        self.assertIsNone(err)

    def test_valid_boundary_discounts(self):
        # 0.85 max valid discount
        item = {"item_name": "Vitamin C 1000mg", "base_price": 100.0, "discount_rate": 0.85}
        self.assertTrue(validate_catalog_item(item)[0])

        # > 0.85 must fail
        item_high = {"item_name": "Vitamin C 1000mg", "base_price": 100.0, "discount_rate": 0.851}
        valid, err = validate_catalog_item(item_high)
        self.assertFalse(valid)
        self.assertIn("invalid_discount", err)

        # Negative discount must fail
        item_neg = {"item_name": "Vitamin C 1000mg", "base_price": 100.0, "discount_rate": -0.01}
        valid, err = validate_catalog_item(item_neg)
        self.assertFalse(valid)
        self.assertIn("invalid_discount_negative", err)

    def test_price_boundaries(self):
        # price == 0.0 must fail (strictly 0.0 < price < 10000.0)
        item_zero = {"item_name": "Test Med", "base_price": 0.0}
        valid, err = validate_catalog_item(item_zero)
        self.assertFalse(valid)
        self.assertIn("invalid_price_zero_or_negative", err)

        # price < 0.0 must fail
        item_neg = {"item_name": "Test Med", "base_price": -10.0}
        valid, err = validate_catalog_item(item_neg)
        self.assertFalse(valid)
        self.assertIn("invalid_price_zero_or_negative", err)

        # price == 10000.0 must fail (strictly < 10000.0)
        item_10k = {"item_name": "Test Med", "base_price": 10000.0}
        valid, err = validate_catalog_item(item_10k)
        self.assertFalse(valid)
        self.assertIn("invalid_price_out_of_bounds", err)

        # price 9999.99 is valid
        item_max = {"item_name": "Test Med", "base_price": 9999.99}
        self.assertTrue(validate_catalog_item(item_max)[0])

    def test_header_token_in_name_rejected(self):
        for header in ["اسم الصنف", "سعر الجمهور", "نسبة الخصم", "Item Name", "Price", "فنصلا"]:
            item = {"item_name": header, "base_price": 50.0}
            valid, err = validate_catalog_item(item)
            self.assertFalse(valid, f"Expected header '{header}' to be rejected")
            self.assertIn("header_token_in_name", err)

    def test_empty_or_missing_name_rejected(self):
        valid, err = validate_catalog_item({"item_name": "", "base_price": 50.0})
        self.assertFalse(valid)
        self.assertEqual(err, "empty_item_name")

        valid, err = validate_catalog_item({"base_price": 50.0})
        self.assertFalse(valid)
        self.assertEqual(err, "missing_item_name")

    def test_missing_price_rejected(self):
        valid, err = validate_catalog_item({"item_name": "Valid Drug"})
        self.assertFalse(valid)
        self.assertEqual(err, "missing_price")

    def test_price_boolean_rejected(self):
        """Boolean price inputs (True/False) must be rejected."""
        valid_true, err_true = validate_catalog_item({"item_name": "Panadol", "base_price": True})
        self.assertFalse(valid_true)
        self.assertEqual(err_true, "invalid_price_boolean")

        valid_false, err_false = validate_catalog_item({"item_name": "Panadol", "base_price": False})
        self.assertFalse(valid_false)
        self.assertEqual(err_false, "invalid_price_boolean")

    def test_string_discount_valid_parsing(self):
        """Valid string discounts must be correctly parsed into [0.0, 0.85] floats."""
        valid_cases = [
            ("15%", 0.15),
            ("15", 0.15),
            ("0.15", 0.15),
            ("85%", 0.85),
            ("0.85", 0.85),
            ("0%", 0.0),
            ("0", 0.0),
            ("0.0", 0.0),
            ("صافي", 0.0),
            ("نقدى", 0.0),
            ("١٥%", 0.15),
            ("١٥", 0.15),
            ("٠%", 0.0),
        ]
        for s_val, _ in valid_cases:
            valid, err = validate_catalog_item({"item_name": "Panadol", "base_price": 50.0, "discount_rate": s_val})
            self.assertTrue(valid, f"Expected '{s_val}' to be valid, but got error: {err}")

    def test_string_discount_out_of_bounds_rejected(self):
        """String discounts > 0.85 must be rejected with invalid_discount_out_of_bounds."""
        invalid_high = ["85.1%", "90%", "95%", "99%", "100%", "150%", "0.851", "0.90"]
        for bad_disc in invalid_high:
            valid, err = validate_catalog_item({"item_name": "Panadol", "base_price": 50.0, "discount_rate": bad_disc})
            self.assertFalse(valid, f"Expected '{bad_disc}' to fail validation, but it passed")
            self.assertIn("invalid_discount_out_of_bounds", err)

    def test_string_discount_negative_rejected(self):
        """Negative string discounts must be rejected with invalid_discount_negative."""
        invalid_neg = ["-0.01", "-5%", "-10%", "-50%", "-150%"]
        for bad_disc in invalid_neg:
            valid, err = validate_catalog_item({"item_name": "Panadol", "base_price": 50.0, "discount_rate": bad_disc})
            self.assertFalse(valid, f"Expected '{bad_disc}' to fail validation, but it passed")
            self.assertIn("invalid_discount_negative", err)

    def test_string_discount_malformed_and_boolean_rejected(self):
        """Malformed string discounts and boolean discount inputs must be rejected."""
        invalid_fmt = ["invalid_text", "garbage", "abc", "%", "xyz_123"]
        for bad_fmt in invalid_fmt:
            valid, err = validate_catalog_item({"item_name": "Panadol", "base_price": 50.0, "discount_rate": bad_fmt})
            self.assertFalse(valid, f"Expected '{bad_fmt}' to fail validation, but it passed")
            self.assertIn("invalid_discount_format", err)

        # Boolean discount values must be rejected
        valid_b, err_b = validate_catalog_item({"item_name": "Panadol", "base_price": 50.0, "discount_rate": False})
        self.assertFalse(valid_b)
        self.assertEqual(err_b, "invalid_discount_boolean")


class TestM1CatalogCorrectionService(unittest.TestCase):
    """Test suite for unified CatalogCorrectionService."""

    def setUp(self):
        # Create a mock catalog service with synthetic data
        self.service = CatalogCorrectionService("non_existent_dummy.pdf")
        # Initialize a synthetic base result
        cols = STANDARD_COLUMNS
        sample_df = pd.DataFrame([
            ["Warehouse X", "Accepted Med 1", "accepted med 1", "500mg", "20tab", 60.0, 0.15, True],
            ["Warehouse X", "Accepted Med 2", "accepted med 2", "1g", "10tab", 120.0, 0.20, True],
        ], columns=cols)

        # Page with 1 accepted group and 1 rejected row
        row_acc1 = RowDiagnostic(page=1, group=0, row=0, outcome="accepted", item_name="Accepted Med 1", raw_cells=["Accepted Med 1", "60", "15%"])
        row_acc2 = RowDiagnostic(page=1, group=0, row=1, outcome="accepted", item_name="Accepted Med 2", raw_cells=["Accepted Med 2", "120", "20%"])
        row_rej1 = RowDiagnostic(page=1, group=0, row=2, outcome="rejected", reason="invalid_price_zero", raw_cells=["Rej Med 3", "0.0", "10%"])

        g_diag = GroupDiagnostics(group=0, strategy="structural_table", candidate_rows=3, accepted_rows=2, rejected_rows=1, rows=[row_acc1, row_acc2, row_rej1])
        p_diag = PageDiagnostics(page=1, groups=[g_diag], accepted_rows=2)
        diag = ImportDiagnostics(pages=[p_diag], accepted_rows=2, unique_records=2)

        self.service._base_catalog_result = CatalogResult(
            dataframe=sample_df,
            diagnostics=diag,
            fingerprint=FileFingerprint(path="non_existent_dummy.pdf", sha256="1234567890abcdef"),
        )

    def test_list_unresolved_issues(self):
        issues = self.service.list_unresolved_issues()
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].source_id, "p1_t0_r2")
        self.assertFalse(issues[0].resolved)
        self.assertEqual(issues[0].rejection_reason, "invalid_price_zero")

    def test_preview_table_column_mapping_previews_all_rows(self):
        # Preview mapping for table 0
        mapping = {"item_name": 0, "base_price": 1, "discount_rate": 2}
        preview = self.service.preview_table_column_mapping(table_id=0, mapping=mapping)
        self.assertEqual(len(preview), 3)

        # First two were previously accepted
        self.assertTrue(preview[0]["was_previously_accepted"])
        self.assertTrue(preview[0]["valid"])
        self.assertTrue(preview[1]["was_previously_accepted"])
        self.assertTrue(preview[1]["valid"])

        # Third was rejected due to price 0.0
        self.assertFalse(preview[2]["was_previously_accepted"])
        self.assertFalse(preview[2]["valid"])

    def test_apply_field_correction_rejects_invalid_data(self):
        bad_update = {"item_name": "Fixed Name", "base_price": -50.0}
        with self.assertRaises(ValueError):
            self.service.apply_field_correction("p1_t0_r2", bad_update)

    def test_apply_field_correction_succeeds(self):
        good_update = {
            "item_name": "Corrected Med 3",
            "base_price": 85.0,
            "discount_rate": 0.12,
            "stock_status": True,
        }
        res = self.service.apply_field_correction("p1_t0_r2", good_update)
        self.assertEqual(len(res.dataframe), 3)
        self.assertIn("Corrected Med 3", res.dataframe["item_name"].values)

        # Check issue is resolved
        self.assertTrue(res.issues_by_source_id["p1_t0_r2"].resolved)
        self.assertEqual(res.issues_by_source_id["p1_t0_r2"].provenance, "manual_correction")
        self.assertEqual(len(self.service.list_unresolved_issues()), 0)

    def test_reset_corrections_restores_pristine_state(self):
        # Apply correction
        good_update = {"item_name": "Corrected Med 3", "base_price": 85.0, "discount_rate": 0.12}
        self.service.apply_field_correction("p1_t0_r2", good_update)
        self.assertEqual(len(self.service.list_unresolved_issues()), 0)

        # Reset
        res = self.service.reset_corrections()
        self.assertEqual(len(res.dataframe), 2)
        self.assertEqual(len(self.service.list_unresolved_issues()), 1)

    def test_apply_field_correction_rejects_invalid_string_discounts_and_boolean_price(self):
        """apply_field_correction must raise ValueError when given invalid string discounts or boolean price."""
        # Bad string discount: negative
        with self.assertRaises(ValueError):
            self.service.apply_field_correction("p1_t0_r2", {"item_name": "Med", "base_price": 50.0, "discount_rate": "-5%"})

        # Bad string discount: out of bounds
        with self.assertRaises(ValueError):
            self.service.apply_field_correction("p1_t0_r2", {"item_name": "Med", "base_price": 50.0, "discount_rate": "90%"})

        # Bad string discount: unparseable text
        with self.assertRaises(ValueError):
            self.service.apply_field_correction("p1_t0_r2", {"item_name": "Med", "base_price": 50.0, "discount_rate": "invalid_text"})

        # Bad price: boolean True
        with self.assertRaises(ValueError):
            self.service.apply_field_correction("p1_t0_r2", {"item_name": "Med", "base_price": True, "discount_rate": 0.10})

    def test_apply_table_column_mapping_updates_accepted_and_rejected_rows(self):
        """
        Verify apply_table_column_mapping re-maps ALL rows in the table:
        1. Previously accepted rows have swapped columns updated in-place in the DataFrame.
        2. Rejected review issues that become valid are resolved and appended.
        """
        service = CatalogCorrectionService("test_table_mapping.pdf")
        cols = STANDARD_COLUMNS
        # Initial incorrect extraction (price and discount swapped):
        # Med A was extracted with price=0.15 (from col 1) and discount=0.0
        initial_df = pd.DataFrame([
            ["Warehouse X", "Med A", "med a", "500mg", "20tab", 0.15, 0.0, True],
        ], columns=cols)

        # Diagnostics reflect raw cells: ["Med A", "15%", "60.0"]
        # r0 was accepted at price 0.15; r1 was rejected due to bad price '0.0'
        r0 = RowDiagnostic(page=1, group=0, row=0, table=0, outcome="accepted", item_name="Med A", raw_cells=["Med A", "15%", "60.0"])
        r1 = RowDiagnostic(page=1, group=0, row=1, table=0, outcome="rejected", reason="invalid_price", raw_cells=["Med B", "20%", "120.0"])

        g = GroupDiagnostics(group=0, strategy="structural", rows=[r0, r1])
        p = PageDiagnostics(page=1, groups=[g])
        diag = ImportDiagnostics(pages=[p], accepted_rows=1)

        service._base_catalog_result = CatalogResult(
            dataframe=initial_df,
            diagnostics=diag,
            fingerprint=FileFingerprint(path="test_table_mapping.pdf", sha256="abc123"),
        )

        # Apply mapping: item_name=0, discount_rate=1, base_price=2
        mapping = {"item_name": 0, "discount_rate": 1, "base_price": 2}
        res = service.apply_table_column_mapping(table_id=0, mapping=mapping)

        # DataFrame must contain both rows with corrected prices
        self.assertEqual(len(res.dataframe), 2)
        med_a = res.dataframe[res.dataframe["item_name"] == "Med A"].iloc[0]
        self.assertEqual(med_a["base_price"], 60.0)
        self.assertAlmostEqual(med_a["discount_rate"], 0.15, places=2)

        med_b = res.dataframe[res.dataframe["item_name"] == "Med B"].iloc[0]
        self.assertEqual(med_b["base_price"], 120.0)
        self.assertAlmostEqual(med_b["discount_rate"], 0.20, places=2)

        # Rejected issue for r1 must now be resolved
        self.assertEqual(len(service.list_unresolved_issues()), 0)
        self.assertTrue(res.issues_by_source_id["p1_t0_r1"].resolved)

    def test_apply_and_preview_table_column_mapping_non_integer_indices_handled_gracefully(self):
        """
        Verify non-integer indices (str, None, float, list, bool) do not raise TypeError
        and fail validation cleanly.
        """
        corrupt_mappings = [
            {"item_name": "col0", "base_price": 1},
            {"item_name": None, "base_price": 1},
            {"item_name": 1.5, "base_price": 1},
            {"item_name": [0], "base_price": 1},
            {"item_name": True, "base_price": 1},
        ]
        for bad_m in corrupt_mappings:
            # Preview does not raise TypeError
            preview = self.service.preview_table_column_mapping(table_id=0, mapping=bad_m)
            self.assertEqual(len(preview), 3)
            for p in preview:
                self.assertFalse(p["valid"])
                self.assertIn("missing_item_name", p["validation_error"])

            # Apply does not raise TypeError
            res = self.service.apply_table_column_mapping(table_id=0, mapping=bad_m)
            self.assertIsInstance(res, CatalogResult)

    def test_apply_field_correction_renamed_item_replaces_row_without_duplication(self):
        """
        Verify correcting a medication's name replaces the original row rather than creating a duplicate.
        """
        res_before = self.service.get_refreshed_catalog_result()
        self.assertEqual(len(res_before.dataframe), 2)
        self.assertIn("Accepted Med 1", res_before.dataframe["item_name"].values)

        rename_update = {
            "item_name": "Accepted Med 1 Renamed",
            "base_price": 60.0,
            "discount_rate": 0.15,
            "stock_status": True,
        }
        res_after = self.service.apply_field_correction("p1_t0_r0", rename_update)

        # Must remain exactly 2 rows
        self.assertEqual(len(res_after.dataframe), 2)
        self.assertIn("Accepted Med 1 Renamed", res_after.dataframe["item_name"].values)
        self.assertNotIn("Accepted Med 1", res_after.dataframe["item_name"].values)
        self.assertEqual(list(res_after.dataframe.columns), STANDARD_COLUMNS)

    def test_apply_field_correction_multiple_renames_idempotent(self):
        """Sequential renames on the same row must not leak prior names or duplicate rows."""
        self.service.apply_field_correction("p1_t0_r0", {"item_name": "First Rename", "base_price": 60.0})
        res2 = self.service.apply_field_correction("p1_t0_r0", {"item_name": "Second Rename", "base_price": 62.0})

        self.assertEqual(len(res2.dataframe), 2)
        self.assertNotIn("Accepted Med 1", res2.dataframe["item_name"].values)
        self.assertNotIn("First Rename", res2.dataframe["item_name"].values)
        self.assertIn("Second Rename", res2.dataframe["item_name"].values)
        self.assertEqual(res2.dataframe.loc[res2.dataframe["item_name"] == "Second Rename", "base_price"].iloc[0], 62.0)
        self.assertEqual(list(res2.dataframe.columns), STANDARD_COLUMNS)


if __name__ == "__main__":
    unittest.main()
