"""
Milestone 3 Iteration 2 Adversarial Stress Suite for Catalog Recovery Engine
Agent: challenger_m3_iter2_1 (critic, specialist)

Stress-tests the three remediated vulnerabilities in src/catalog_recovery.py:
1. NaN and Inf coordinates handling in bounding boxes.
2. Percentage tokens paired with explicit zero never promoted to base price.
3. Three or more numeric columns never arbitrarily sliced or guessed.
Plus regression checks ensuring genuine recoverable items remain recovered.
"""

import math
import os
import tempfile
import unittest
import fitz  # pymupdf
import pandas as pd

from src.catalog_diagnostics import (
    CatalogResult,
    ImportDiagnostics,
    ReviewIssue,
    SourceIdentity,
)
from src.catalog_recovery import (
    _extract_words_from_pdf_bbox,
    recover_by_column_roles,
    recover_by_coordinates,
    run_automatic_recovery,
)
from src.catalog_reader import validate_catalog_item


class TestMilestone3Iter2RecoveryStress(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create a small valid PDF file for coordinate extraction tests
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.pdf_path = os.path.join(cls.temp_dir.name, "stress_sample.pdf")
        doc = fitz.open()
        page = doc.new_page(width=600, height=800)
        page.insert_text(fitz.Point(100, 100), "Augmentin 1g 14 Tab 95.00 10%", fontsize=12)
        doc.save(cls.pdf_path)
        doc.close()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    # =========================================================================
    # VULNERABILITY 1: NaN and Inf coordinate handling in bounding boxes
    # =========================================================================

    def test_nan_in_all_bbox_positions(self):
        """Verify float('nan') at any index (0, 1, 2, 3) safely returns [] and None."""
        test_boxes = [
            [float("nan"), 100.0, 500.0, 150.0],
            [100.0, float("nan"), 500.0, 150.0],
            [100.0, 100.0, float("nan"), 150.0],
            [100.0, 100.0, 500.0, float("nan")],
            [float("nan"), float("nan"), float("nan"), float("nan")],
        ]
        for box in test_boxes:
            words = _extract_words_from_pdf_bbox(self.pdf_path, 1, box)
            self.assertEqual(words, [], f"Expected empty word list for NaN bbox: {box}")

            ident = SourceIdentity(page=1, table=0, row=0, bbox=box)
            issue = ReviewIssue(
                source_id=ident.source_id,
                identity=ident,
                raw_cells=["Augmentin 1g", "", "10%"],
                bbox=box,
                rejection_reason="test_nan",
            )
            candidate = recover_by_coordinates(issue, self.pdf_path)
            self.assertIsNone(candidate, f"NaN bbox {box} must not produce a candidate")

    def test_pos_and_neg_inf_in_all_bbox_positions(self):
        """Verify float('inf') and float('-inf') at any index safely returns [] and None."""
        test_boxes = [
            [float("inf"), 100.0, 500.0, 150.0],
            [100.0, float("-inf"), 500.0, 150.0],
            [100.0, 100.0, float("inf"), 150.0],
            [100.0, 100.0, 500.0, float("-inf")],
            [float("-inf"), float("-inf"), float("inf"), float("inf")],
        ]
        for box in test_boxes:
            words = _extract_words_from_pdf_bbox(self.pdf_path, 1, box)
            self.assertEqual(words, [], f"Expected empty word list for Inf bbox: {box}")

            ident = SourceIdentity(page=1, table=0, row=0, bbox=box)
            issue = ReviewIssue(
                source_id=ident.source_id,
                identity=ident,
                raw_cells=["Augmentin 1g", "", "10%"],
                bbox=box,
                rejection_reason="test_inf",
            )
            candidate = recover_by_coordinates(issue, self.pdf_path)
            self.assertIsNone(candidate, f"Inf bbox {box} must not produce a candidate")

    def test_malformed_type_elements_in_bbox(self):
        """Verify non-numeric types in bbox (None, str, list, dict) return [] without unhandled crash."""
        corrupted_boxes = [
            [None, 100.0, 500.0, 150.0],
            ["100.0", 100.0, 500.0, 150.0],
            [100.0, [100.0], 500.0, 150.0],
            [100.0, 100.0, {"val": 500.0}, 150.0],
            [100.0, 100.0],  # len < 4
            [100.0],
            [],
            None,
        ]
        for box in corrupted_boxes:
            words = _extract_words_from_pdf_bbox(self.pdf_path, 1, box)
            self.assertEqual(words, [], f"Expected empty word list for malformed bbox: {box}")

    # =========================================================================
    # VULNERABILITY 2: Percent paired with explicit zero never promoted to price
    # =========================================================================

    def test_percent_zero_combinations_never_promote_percentage(self):
        """
        Exhaustively test combinations of explicit percentages and explicit zero tokens.
        No percentage value may ever be extracted or promoted to base_price.
        """
        zero_tokens = ["0%", "0.0%", " 0 % ", "0", "0.0", "٠%", "٠"]
        pct_tokens = ["10%", "20%", "15.5%", " 30 % ", "١٠%", "٢٥%"]

        for z in zero_tokens:
            for p in pct_tokens:
                # Test order (p, z)
                issue_a = ReviewIssue(
                    source_id="p1_t0_r1",
                    identity=SourceIdentity(page=1, table=0, row=1),
                    raw_cells=["Panadol Extra 24 Tab", p, z],
                    rejection_reason="test_pair",
                )
                cand_a = recover_by_column_roles(issue_a)
                if cand_a is not None:
                    # If recovered, base_price MUST NOT be the percentage
                    self.assertNotIn("%", str(cand_a.get("base_price")))
                    # And base_price cannot be the numerical value of the percentage
                    p_num = float(p.replace("%", "").replace(" ", "").translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")))
                    self.assertNotEqual(
                        cand_a.get("base_price"),
                        p_num,
                        f"CRITICAL: Percentage '{p}' was promoted to base_price {p_num} when paired with '{z}'!",
                    )
                    # And validate_catalog_item must pass
                    v, err = validate_catalog_item(cand_a)
                    self.assertTrue(v, f"Recovered candidate must be valid, got error: {err}")

                # Test order (z, p)
                issue_b = ReviewIssue(
                    source_id="p1_t0_r2",
                    identity=SourceIdentity(page=1, table=0, row=2),
                    raw_cells=["Panadol Extra 24 Tab", z, p],
                    rejection_reason="test_pair",
                )
                cand_b = recover_by_column_roles(issue_b)
                if cand_b is not None:
                    p_num = float(p.replace("%", "").replace(" ", "").translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")))
                    self.assertNotEqual(
                        cand_b.get("base_price"),
                        p_num,
                        f"CRITICAL: Percentage '{p}' was promoted to base_price {p_num} when paired with '{z}' (inverted)!",
                    )
                    v, err = validate_catalog_item(cand_b)
                    self.assertTrue(v, f"Recovered candidate must be valid, got error: {err}")

    def test_two_zeros_never_produce_candidate(self):
        """Two explicit zeros (e.g. '0%' and '0', or '0' and '0') must remain unresolved."""
        zero_pairs = [
            ("0%", "0%"),
            ("0%", "0"),
            ("0", "0%"),
            ("0", "0"),
            ("0.0%", "0.0%"),
        ]
        for z1, z2 in zero_pairs:
            issue = ReviewIssue(
                source_id="p1_t0_r3",
                identity=SourceIdentity(page=1, table=0, row=3),
                raw_cells=["Congestal 20 Tab", z1, z2],
                rejection_reason="test_zeros",
            )
            cand = recover_by_column_roles(issue)
            self.assertIsNone(cand, f"Two zero tokens ({z1}, {z2}) must not produce a candidate")

    # =========================================================================
    # VULNERABILITY 3: Three or more numeric columns never arbitrarily sliced
    # =========================================================================

    def test_three_or_more_numeric_columns_remain_unresolved(self):
        """
        Rows containing 3 or more numeric tokens must remain unresolved
        in recover_by_column_roles to prevent guessing across item codes, barcodes, or quantities.
        """
        multi_num_rows = [
            ["Panadol Extra", "501", "15%", "50.00"],
            ["Panadol Extra", "50.00", "15%", "501"],
            ["Panadol Extra", "10001", "20002", "30003"],
            ["Panadol Extra", "1", "2", "3", "4"],
            ["Panadol Extra", "50.00", "0.10", "123456789"],
            ["Panadol Extra", "0.0", "50.00", "100"],
        ]
        for row in multi_num_rows:
            issue = ReviewIssue(
                source_id="p1_t0_r4",
                identity=SourceIdentity(page=1, table=0, row=4),
                raw_cells=row,
                rejection_reason="test_multi_numeric",
            )
            cand = recover_by_column_roles(issue)
            self.assertIsNone(
                cand,
                f"Row with {len(row)-1} numeric columns {row} must remain unresolved (return None)",
            )

    def test_fewer_than_two_numeric_columns_remain_unresolved(self):
        """Rows with 0 or 1 numeric tokens must return None in recover_by_column_roles."""
        insufficient_num_rows = [
            ["Panadol Extra 24 Tab"],  # 0 numbers
            ["Panadol Extra 24 Tab", "50.00"],  # 1 number
            ["Panadol Extra 24 Tab", "15%"],  # 1 number (percent)
        ]
        for row in insufficient_num_rows:
            issue = ReviewIssue(
                source_id="p1_t0_r5",
                identity=SourceIdentity(page=1, table=0, row=5),
                raw_cells=row,
                rejection_reason="test_insufficient_numeric",
            )
            cand = recover_by_column_roles(issue)
            self.assertIsNone(cand, f"Row with < 2 numbers {row} must return None")

    # =========================================================================
    # POSITIVE RECOVERY & REGRESSION PRESERVATION
    # =========================================================================

    def test_valid_swapped_columns_still_recover_successfully(self):
        """
        Verify that genuine swapped price/discount rows (exactly 1 text and 2 numbers)
        are correctly and safely recovered.
        """
        valid_cases = [
            # (raw_cells, expected_price, expected_discount)
            (["Cataflam 50mg 20 Tab", "15%", "65.00"], 65.0, 0.15),
            (["Cataflam 50mg 20 Tab", "65.00", "15%"], 65.0, 0.15),
            (["Amoxil 500mg 16 Cap", "0%", "45.00"], 45.0, 0.0),
            (["Amoxil 500mg 16 Cap", "45.00", "0%"], 45.0, 0.0),
            (["Brufen 400mg 30 Tab", "0", "38.50"], 38.5, 0.0),
            (["Brufen 400mg 30 Tab", "38.50", "0"], 38.5, 0.0),
            (["Concor 5mg 30 Tab", "0.15", "52.00"], 52.0, 0.15),
            (["Concor 5mg 30 Tab", "52.00", "0.15"], 52.0, 0.15),
        ]
        for raw, exp_price, exp_disc in valid_cases:
            issue = ReviewIssue(
                source_id="p1_t0_r6",
                identity=SourceIdentity(page=1, table=0, row=6),
                raw_cells=raw,
                rejection_reason="test_valid_swapped",
            )
            cand = recover_by_column_roles(issue)
            self.assertIsNotNone(cand, f"Expected recovery for valid case: {raw}")
            self.assertAlmostEqual(cand["base_price"], exp_price, places=2)
            self.assertAlmostEqual(cand["discount_rate"], exp_disc, places=3)
            self.assertEqual(cand["stock_status"], True)
            self.assertTrue(validate_catalog_item(cand)[0])

    def test_full_pipeline_run_automatic_recovery_idempotency_and_safety(self):
        """
        Verify end-to-end run_automatic_recovery:
        - Resolves genuine issues
        - Leaves ambiguous issues unresolved
        - Is 100% idempotent over multiple executions
        """
        valid_issue = ReviewIssue(
            source_id="p1_t0_r1",
            identity=SourceIdentity(page=1, table=0, row=1),
            raw_cells=["Antinal 24 Cap", "12%", "30.00"],
            rejection_reason="swapped_columns",
        )
        ambiguous_zeros_issue = ReviewIssue(
            source_id="p1_t0_r2",
            identity=SourceIdentity(page=1, table=0, row=2),
            raw_cells=["Panadol Cold & Flu", "10%", "0%"],
            rejection_reason="two_percentages",
        )
        three_nums_issue = ReviewIssue(
            source_id="p1_t0_r3",
            identity=SourceIdentity(page=1, table=0, row=3),
            raw_cells=["Panadol Sinus", "999", "15%", "45.00"],
            rejection_reason="three_numbers",
        )

        issues = [valid_issue, ambiguous_zeros_issue, three_nums_issue]
        cat_result = CatalogResult(
            dataframe=pd.DataFrame(columns=[
                "warehouse_name", "item_name", "normalized_name",
                "dosage", "unit_size", "base_price", "discount_rate", "stock_status",
            ]),
            diagnostics=ImportDiagnostics(),
            review_issues=issues,
            issues_by_source_id={i.source_id: i for i in issues},
        )

        # First recovery run
        run_1 = run_automatic_recovery(cat_result, self.pdf_path)
        self.assertEqual(len(run_1.dataframe), 1, "Only valid issue should be recovered into dataframe")
        self.assertEqual(run_1.dataframe.iloc[0]["item_name"], "Antinal 24 Cap")
        self.assertAlmostEqual(run_1.dataframe.iloc[0]["base_price"], 30.0)
        self.assertAlmostEqual(run_1.dataframe.iloc[0]["discount_rate"], 0.12)

        # Ambiguous issues remain unresolved
        self.assertFalse(run_1.issues_by_source_id["p1_t0_r2"].resolved)
        self.assertFalse(run_1.issues_by_source_id["p1_t0_r3"].resolved)

        # Second recovery run (idempotency)
        run_2 = run_automatic_recovery(run_1, self.pdf_path)
        self.assertEqual(len(run_2.dataframe), 1)
        pd.testing.assert_frame_equal(run_1.dataframe, run_2.dataframe)


if __name__ == "__main__":
    unittest.main()
