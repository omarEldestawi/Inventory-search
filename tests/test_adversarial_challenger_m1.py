"""
Adversarial Stress Test Suite for Milestone 1 Contracts.
Authored by Challenger 1 (Milestone 1).
Empirically stress-tests boundary inputs, serialization roundtrips, and table mapping resilience.
"""
import copy
import json
import math
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
    METADATA_KEY,
)
from src.catalog_reader import validate_catalog_item
from src.catalog_service import CatalogCorrectionService, STANDARD_COLUMNS


class TestAdversarialValidateCatalogItem(unittest.TestCase):
    """Adversarial stress-testing of validate_catalog_item boundary conditions."""

    def test_price_zero_boundary(self):
        """price == 0.0 must be rejected (strictly 0.0 < price < 10000.0)."""
        valid, err = validate_catalog_item({"item_name": "Panadol 500mg", "base_price": 0})
        self.assertFalse(valid)
        self.assertIn("invalid_price_zero_or_negative", err)

        valid_float_zero, err = validate_catalog_item({"item_name": "Panadol 500mg", "base_price": 0.0})
        self.assertFalse(valid_float_zero)
        self.assertIn("invalid_price_zero_or_negative", err)

        # price == "0" and "0.0" as string
        valid_s0, err = validate_catalog_item({"item_name": "Panadol 500mg", "base_price": "0"})
        self.assertFalse(valid_s0)
        self.assertIn("invalid_price_zero_or_negative", err)

        valid_s00, err = validate_catalog_item({"item_name": "Panadol 500mg", "base_price": "0.0"})
        self.assertFalse(valid_s00)
        self.assertIn("invalid_price_zero_or_negative", err)

        # Eastern Arabic zero "٠"
        valid_ar0, err = validate_catalog_item({"item_name": "Panadol 500mg", "base_price": "٠"})
        self.assertFalse(valid_ar0)
        self.assertIn("invalid_price_zero_or_negative", err)

    def test_price_upper_boundary_10000(self):
        """price == 10000.0 must be rejected (strictly < 10000.0)."""
        valid, err = validate_catalog_item({"item_name": "Panadol 500mg", "base_price": 10000})
        self.assertFalse(valid)
        self.assertIn("invalid_price_out_of_bounds", err)

        valid_float_10k, err = validate_catalog_item({"item_name": "Panadol 500mg", "base_price": 10000.0})
        self.assertFalse(valid_float_10k)
        self.assertIn("invalid_price_out_of_bounds", err)

        valid_s_10k, err = validate_catalog_item({"item_name": "Panadol 500mg", "base_price": "10000"})
        self.assertFalse(valid_s_10k)
        self.assertIn("invalid_price_out_of_bounds", err)

        # price slightly above 10000
        valid_above, err = validate_catalog_item({"item_name": "Panadol 500mg", "base_price": 10000.01})
        self.assertFalse(valid_above)
        self.assertIn("invalid_price_out_of_bounds", err)

        # price slightly below 10000 (9999.99) is valid
        valid_below, err = validate_catalog_item({"item_name": "Panadol 500mg", "base_price": 9999.99})
        self.assertTrue(valid_below)
        self.assertIsNone(err)

    def test_price_negative_boundary_minus_5(self):
        """price == -5 must be rejected."""
        valid, err = validate_catalog_item({"item_name": "Panadol 500mg", "base_price": -5})
        self.assertFalse(valid)
        self.assertIn("invalid_price_zero_or_negative", err)

        valid_float_neg, err = validate_catalog_item({"item_name": "Panadol 500mg", "base_price": -5.0})
        self.assertFalse(valid_float_neg)
        self.assertIn("invalid_price_zero_or_negative", err)

        valid_str_neg, err = validate_catalog_item({"item_name": "Panadol 500mg", "base_price": "-5"})
        self.assertFalse(valid_str_neg)
        self.assertIn("invalid_price_zero_or_negative", err)

    def test_numeric_discount_boundaries(self):
        """Numeric float boundaries: -0.01 rejected, 0.851 rejected, 0.85 accepted."""
        # discount == -0.01 (float) must fail
        valid_neg, err_neg = validate_catalog_item({"item_name": "Panadol 500mg", "base_price": 50.0, "discount_rate": -0.01})
        self.assertFalse(valid_neg)
        self.assertIn("invalid_discount_negative", err_neg)

        # discount == 0.851 (float) must fail (> 0.85)
        valid_high, err_high = validate_catalog_item({"item_name": "Panadol 500mg", "base_price": 50.0, "discount_rate": 0.851})
        self.assertFalse(valid_high)
        self.assertIn("invalid_discount_out_of_bounds", err_high)

        # discount exactly 0.85 (float) is valid
        valid_85, err_85 = validate_catalog_item({"item_name": "Panadol 500mg", "base_price": 50.0, "discount_rate": 0.85})
        self.assertTrue(valid_85)
        self.assertIsNone(err_85)

    def test_discount_zero_vs_none_distinct(self):
        """Explicit 0.0 discount and None (blank discount) are both valid and distinct."""
        # Explicit 0.0 discount is valid
        item_zero = {"item_name": "Panadol 500mg", "base_price": 50.0, "discount_rate": 0.0}
        valid_z, err_z = validate_catalog_item(item_zero)
        self.assertTrue(valid_z)
        self.assertIsNone(err_z)

        # Blank/None discount is valid
        item_none = {"item_name": "Panadol 500mg", "base_price": 50.0, "discount_rate": None}
        valid_n, err_n = validate_catalog_item(item_none)
        self.assertTrue(valid_n)
        self.assertIsNone(err_n)

        # Blank string discount "" treated as blank discount (None)
        item_blank_str = {"item_name": "Panadol 500mg", "base_price": 50.0, "discount_rate": "   "}
        valid_bs, err_bs = validate_catalog_item(item_blank_str)
        self.assertTrue(valid_bs)
        self.assertIsNone(err_bs)

        # Explicit zero string "صافي" is treated as 0.0
        item_safi = {"item_name": "Panadol 500mg", "base_price": 50.0, "discount_rate": "صافي"}
        valid_sf, err_sf = validate_catalog_item(item_safi)
        self.assertTrue(valid_sf)
        self.assertIsNone(err_sf)

        # Distinguishable in data dictionary: item_zero has 0.0, item_none has None
        self.assertEqual(item_zero["discount_rate"], 0.0)
        self.assertIsNone(item_none["discount_rate"])

    def test_extreme_numeric_values_nan_inf(self):
        """NaN and Inf in price or discount must be caught and rejected."""
        valid, err = validate_catalog_item({"item_name": "Panadol 500mg", "base_price": float("nan")})
        self.assertFalse(valid)
        self.assertIn("invalid_price_nan_or_inf", err)

        valid, err = validate_catalog_item({"item_name": "Panadol 500mg", "base_price": float("inf")})
        self.assertFalse(valid)
        self.assertIn("invalid_price_nan_or_inf", err)

        valid, err = validate_catalog_item({"item_name": "Panadol 500mg", "base_price": 50.0, "discount_rate": float("nan")})
        self.assertFalse(valid)
        self.assertIn("invalid_discount_nan_or_inf", err)

        valid, err = validate_catalog_item({"item_name": "Panadol 500mg", "base_price": 50.0, "discount_rate": float("inf")})
        self.assertFalse(valid)
        self.assertIn("invalid_discount_nan_or_inf", err)

    def test_vulnerability_string_discount_bounds_masked_by_parse_discount(self):
        """
        REMEDIATED BEHAVIOR:
        When raw_discount is an invalid string ('-0.01', '85.1%', '90%', '-5%'),
        validate_catalog_item rejects them strictly instead of clamping them to 0.0.
        """
        vulnerable_inputs = ["-0.01", "-5%", "85.1%", "90%", "0.851", "99%"]
        for d_str in vulnerable_inputs:
            valid, err = validate_catalog_item({"item_name": "Panadol 500mg", "base_price": 50.0, "discount_rate": d_str})
            self.assertFalse(
                valid,
                f"Expected invalid string discount '{d_str}' to be rejected, but passed"
            )


class TestAdversarialReviewIssueSerialization(unittest.TestCase):
    """Stress-testing ReviewIssue serialization and deserialization with complex nested structures."""

    def test_complex_nested_roundtrip_dict_and_json(self):
        ident = SourceIdentity(
            page=42,
            table=3,
            row=108,
            bbox=[12.3456, 78.9012, 345.6789, 567.8901],
            is_region_issue=False,
            source_id="p42_t3_r108",
        )

        complex_item = {
            "warehouse_name": "مخزن المتحدة للصيادلة",
            "item_name": "Augmentin 1g 14tab (أوجمنتين)",
            "normalized_name": "augmentin 1g 14tab",
            "dosage": "1g",
            "unit_size": "14tab",
            "base_price": 120.75,
            "discount_rate": 0.185,
            "stock_status": True,
            "extra_metadata": {
                "tags": ["antibiotic", "penicillin", "prescription_only"],
                "audit": {
                    "reviewed_by": "qa_agent_4",
                    "confidence_score": 0.9942,
                    "coordinates": {"x0": 12.3456, "y0": 78.9012, "x1": 345.6789, "y1": 567.8901},
                    "history": [
                        {"action": "extracted", "parser": "pymupdf_table"},
                        {"action": "recovered", "stage": 2, "rule": "wrapped_arabic_text"},
                    ]
                }
            }
        }

        issue = ReviewIssue(
            source_id="p42_t3_r108",
            identity=ident,
            raw_cells=["Augmentin 1g 14tab", "أوجمنتين", 120.75, "18.5%", None, {"internal_flag": True}],
            bbox=[12.3456, 78.9012, 345.6789, 567.8901],
            rejection_reason="initial_multiline_split: Arabic subtitle wrapped onto second cell",
            attempted_strategies=["coordinate_reextraction", "wrapped_text_reconstruction", "column_role_resolution"],
            strategy_outcomes={
                "coordinate_reextraction": "no_bbox_delta",
                "wrapped_text_reconstruction": "merged_arabic_latin_successfully",
                "column_role_resolution": "skipped_already_resolved"
            },
            provenance="automatic_recovery",
            resolved=True,
            item=complex_item,
        )

        # 1. to_dict() and from_dict() roundtrip
        d = issue.to_dict()
        recovered = ReviewIssue.from_dict(d)
        self.assertEqual(issue.source_id, recovered.source_id)
        self.assertEqual(issue.bbox, recovered.bbox)
        self.assertEqual(issue.provenance, recovered.provenance)
        self.assertTrue(recovered.resolved)
        self.assertEqual(recovered.identity.page, 42)
        self.assertEqual(recovered.identity.table, 3)
        self.assertEqual(recovered.identity.row, 108)
        self.assertEqual(recovered.item["extra_metadata"]["audit"]["confidence_score"], 0.9942)
        self.assertEqual(len(recovered.attempted_strategies), 3)

        # 2. JSON roundtrip serialization
        json_str = json.dumps(d, ensure_ascii=False)
        self.assertIn("مخزن المتحدة للصيادلة", json_str)
        self.assertIn("أوجمنتين", json_str)

        loaded_dict = json.loads(json_str)
        from_json_issue = ReviewIssue.from_dict(loaded_dict)
        self.assertEqual(from_json_issue.source_id, "p42_t3_r108")
        self.assertEqual(from_json_issue.item["item_name"], "Augmentin 1g 14tab (أوجمنتين)")
        self.assertEqual(from_json_issue.item["extra_metadata"]["tags"], ["antibiotic", "penicillin", "prescription_only"])

    def test_region_issue_serialization_with_none_row(self):
        ident = SourceIdentity(
            page=5,
            table=1,
            row=None,
            bbox=[0.0, 100.0, 595.0, 400.0],
            is_region_issue=True,
        )
        issue = ReviewIssue(
            source_id=ident.source_id,
            identity=ident,
            raw_cells=[],
            bbox=ident.bbox,
            rejection_reason="unmapped_table_region: layout has contradictory column widths",
            resolved=False,
        )
        self.assertEqual(issue.source_id, "p5_t1_region")
        self.assertTrue(issue.identity.is_region_issue)
        self.assertIsNone(issue.identity.row)

        d = issue.to_dict()
        recovered = ReviewIssue.from_dict(d)
        self.assertEqual(recovered.source_id, "p5_t1_region")
        self.assertTrue(recovered.identity.is_region_issue)
        self.assertIsNone(recovered.identity.row)
        self.assertEqual(recovered.bbox, [0.0, 100.0, 595.0, 400.0])

    def test_catalog_result_dataframe_metadata_roundtrip(self):
        """Verify that ReviewIssues persist losslessly through CatalogResult DataFrame attributes."""
        df = pd.DataFrame([
            ["Warehouse Y", "Congestal 20tab", "congestal 20tab", "standard", "20tab", 31.0, 0.10, True]
        ], columns=STANDARD_COLUMNS)

        issue1 = ReviewIssue(
            source_id="p1_t0_r1",
            identity=SourceIdentity(page=1, table=0, row=1),
            raw_cells=["Congestal 20tab", 31.0, 0.10],
            bbox=[10.0, 20.0, 30.0, 40.0],
            rejection_reason="none",
            resolved=True,
        )
        issue2 = ReviewIssue(
            source_id="p1_t1_region",
            identity=SourceIdentity(page=1, table=1, row=None, is_region_issue=True),
            raw_cells=[],
            bbox=[0.0, 500.0, 595.0, 842.0],
            rejection_reason="corrupt_table_geometry",
            resolved=False,
        )

        res = CatalogResult(
            dataframe=df,
            diagnostics=ImportDiagnostics(accepted_rows=1, unique_records=1, unresolved_region_count=1),
            review_issues=[issue1, issue2],
        )

        df_with_meta = res.to_dataframe()
        self.assertIn(METADATA_KEY, df_with_meta.attrs)
        self.assertIn("review_issues", df_with_meta.attrs[METADATA_KEY])
        self.assertEqual(len(df_with_meta.attrs[METADATA_KEY]["review_issues"]), 2)

        recovered_res = CatalogResult.from_dataframe(df_with_meta)
        self.assertIsNotNone(recovered_res)
        self.assertEqual(len(recovered_res.review_issues), 2)
        self.assertIn("p1_t0_r1", recovered_res.issues_by_source_id)
        self.assertIn("p1_t1_region", recovered_res.issues_by_source_id)
        self.assertTrue(recovered_res.issues_by_source_id["p1_t0_r1"].resolved)
        self.assertFalse(recovered_res.issues_by_source_id["p1_t1_region"].resolved)


class TestAdversarialPreviewTableColumnMapping(unittest.TestCase):
    """Stress-testing CatalogCorrectionService.preview_table_column_mapping with corrupt or out-of-range indices."""

    def setUp(self):
        self.service = CatalogCorrectionService("adversarial_test_catalog.pdf")
        cols = STANDARD_COLUMNS
        sample_df = pd.DataFrame([
            ["Warehouse Z", "Cataflam 50mg", "cataflam 50mg", "50mg", "20tab", 45.0, 0.10, True],
        ], columns=cols)

        r0 = RowDiagnostic(page=1, group=0, row=0, table=0, outcome="accepted", item_name="Cataflam 50mg", raw_cells=["Cataflam 50mg", "45.0", "10%"])
        r1 = RowDiagnostic(page=1, group=0, row=1, table=0, outcome="rejected", reason="unmapped_columns", raw_cells=["100234", "Voltaren 100mg", "75.0", "15%", "1"])
        r2 = RowDiagnostic(page=1, group=0, row=2, table=0, outcome="rejected", reason="truncated_row", raw_cells=["Only One Cell"])

        g = GroupDiagnostics(group=0, strategy="structural", rows=[r0, r1, r2])
        p = PageDiagnostics(page=1, groups=[g])
        diag = ImportDiagnostics(pages=[p], accepted_rows=1)

        self.service._base_catalog_result = CatalogResult(
            dataframe=sample_df,
            diagnostics=diag,
            fingerprint=FileFingerprint(path="adversarial_test_catalog.pdf", sha256="abcdef1234567890"),
        )

    def test_out_of_range_positive_indices(self):
        """Index far beyond row length should result in candidate[col]=None, rejected cleanly by validation without exception."""
        mapping_out_of_range = {
            "item_name": 9999,
            "base_price": 500,
            "discount_rate": 200,
        }
        preview = self.service.preview_table_column_mapping(table_id=0, mapping=mapping_out_of_range)
        self.assertEqual(len(preview), 3)

        for p_row in preview:
            self.assertIsNone(p_row["candidate"]["item_name"])
            self.assertIsNone(p_row["candidate"]["base_price"])
            self.assertFalse(p_row["valid"])
            self.assertEqual(p_row["validation_error"], "missing_item_name")

    def test_negative_indices(self):
        """Negative indices should be treated as out-of-range (candidate[col]=None) rather than Python wrap-around indexing."""
        mapping_neg = {
            "item_name": -1,
            "base_price": -2,
        }
        preview = self.service.preview_table_column_mapping(table_id=0, mapping=mapping_neg)
        self.assertEqual(len(preview), 3)

        for p_row in preview:
            self.assertIsNone(p_row["candidate"]["item_name"])
            self.assertIsNone(p_row["candidate"]["base_price"])
            self.assertFalse(p_row["valid"])
            self.assertEqual(p_row["validation_error"], "missing_item_name")

    def test_swapped_price_and_discount_indices_validation(self):
        """Mapping that mistakenly swaps price and discount indices fails validation."""
        # For row 0: raw_cells = ["Cataflam 50mg", "45.0", "10%"]
        # If mapping swaps price and discount: price takes index 2 ("10%"), discount takes index 1 ("45.0")
        mapping_swapped = {
            "item_name": 0,
            "base_price": 2,      # "10%" -> invalid price format
            "discount_rate": 1,
        }
        preview = self.service.preview_table_column_mapping(table_id=0, mapping=mapping_swapped)
        self.assertEqual(len(preview), 3)

        r0_prev = preview[0]
        # "10%" is invalid as a base_price
        self.assertFalse(r0_prev["valid"])
        self.assertIn("invalid_price_format: 10%", r0_prev["validation_error"])

    def test_empty_mapping_dictionary(self):
        """Empty mapping dictionary produces candidate with None for all fields, cleanly rejected."""
        preview = self.service.preview_table_column_mapping(table_id=0, mapping={})
        self.assertEqual(len(preview), 3)
        for p in preview:
            self.assertFalse(p["valid"])
            self.assertEqual(p["validation_error"], "missing_item_name")

    def test_non_existent_table_id(self):
        """Table ID that does not exist in catalog diagnostics returns an empty list, no crash."""
        preview = self.service.preview_table_column_mapping(table_id=99, mapping={"item_name": 0, "base_price": 1})
        self.assertEqual(preview, [])

    def test_preview_is_pure_and_does_not_mutate_state(self):
        """Calling preview_table_column_mapping multiple times must not alter service state or DataFrame."""
        orig_unresolved = len(self.service.list_unresolved_issues())
        orig_df_len = len(self.service.get_refreshed_catalog_result().dataframe)

        mapping = {"item_name": 1, "base_price": 2, "discount_rate": 3}
        self.service.preview_table_column_mapping(table_id=0, mapping=mapping)

        self.assertEqual(len(self.service.list_unresolved_issues()), orig_unresolved)
        self.assertEqual(len(self.service.get_refreshed_catalog_result().dataframe), orig_df_len)

    def test_vulnerability_corrupt_non_int_column_mapping_raises_type_error(self):
        """
        REMEDIATED BEHAVIOR:
        When mapping contains non-integer index values, preview_table_column_mapping
        handles them safely without raising TypeError and marks candidates invalid.
        """
        corrupt_cases = [
            ("string index", {"item_name": "col0", "base_price": 1}),
            ("None index", {"item_name": None, "base_price": 1}),
            ("float index", {"item_name": 1.5, "base_price": 1}),
            ("list index", {"item_name": [0], "base_price": 1}),
        ]
        for label, m in corrupt_cases:
            preview = self.service.preview_table_column_mapping(table_id=0, mapping=m)
            self.assertEqual(len(preview), 3)
            for p in preview:
                self.assertFalse(p["valid"])
                self.assertIn("missing_item_name", p["validation_error"])

    def test_vulnerability_apply_field_correction_accepts_invalid_string_discount(self):
        """
        REMEDIATED BEHAVIOR:
        apply_field_correction must raise ValueError when given invalid string discounts.
        """
        bad_field_update = {
            "item_name": "Panadol Extra",
            "base_price": 45.0,
            "discount_rate": "-5%",
        }
        with self.assertRaises(ValueError):
            self.service.apply_field_correction("p1_t0_r1", bad_field_update)


if __name__ == "__main__":
    unittest.main()
