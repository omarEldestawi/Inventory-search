"""
Adversarial Stress Verification Test Suite for Milestone 3 (R2 & R3).
Authored by: challenger_m3_1 (Empirical Challenger)

Adversarially challenges Extraction Accountability (R2) and Deterministic Automatic Recovery (R3) in:
- src/catalog_reader.py
- src/catalog_recovery.py

Focus Areas:
1. Synthetic corrupted and edge-case geometries (extreme aspect ratios, inverted coordinates, overlapping bounding boxes, NaN/Inf).
2. Ambiguous numeric fields: ensure the engine NEVER guesses when values are ambiguous (e.g. two plain numbers in price range, two percentages, 3+ numeric tokens).
3. Multi-line wrapped Arabic, Latin, and mixed tokens: verify Latin characters never reversed, Arabic never mangled, and noise lines cleanly filtered.
4. Recovery idempotency: verify repeated execution produces identical outputs, stable counters, and zero duplicates.
5. Row count accounting: verify unmapped regions never hallucinate candidate row counts (candidate_rows=0, expected_count_known=False).
"""
from __future__ import annotations

import copy
import math
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
from src.catalog_reader import (
    is_explicit_zero_discount,
    normalize_arabic_text,
    parse_discount,
    parse_dosage_and_pack,
    validate_catalog_item,
)
from src.catalog_recovery import (
    _extract_words_from_pdf_bbox,
    reconstruct_wrapped_name,
    recover_by_column_roles,
    recover_by_coordinates,
    recover_by_wrapped_text,
    run_automatic_recovery,
)
from src.catalog_service import CatalogCorrectionService, STANDARD_COLUMNS

PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
HAYAH_PATH = os.path.join(PROJECT_ROOT, "tests", "fixtures", "hayah_shibin.pdf")


class TestAdversarialGeometryEdgeCases(unittest.TestCase):
    """1. Stress-testing synthetic corrupted and edge-case geometries in recovery."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.pdf_path = os.path.join(self.temp_dir, "geom_stress.pdf")
        self._create_sample_pdf(self.pdf_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_sample_pdf(self, path: str):
        doc = pymupdf.open()
        page = doc.new_page(width=600, height=800)
        # Insert target words at coordinates (100, 100, 500, 150)
        page.insert_text(pymupdf.Point(105, 125), "Augmentin 1g Tablets", fontname="helv", fontsize=10)
        page.insert_text(pymupdf.Point(350, 125), "95.00", fontname="helv", fontsize=10)
        page.insert_text(pymupdf.Point(450, 125), "10%", fontname="helv", fontsize=10)
        doc.save(path)
        doc.close()

    def test_inverted_coordinates_handling(self):
        """Verify inverted bounding boxes (x0 > x1, y0 > y1, or both) fail gracefully without unhandled exceptions."""
        inverted_boxes = [
            [500.0, 100.0, 100.0, 150.0],  # x0 > x1
            [100.0, 150.0, 500.0, 100.0],  # y0 > y1
            [500.0, 150.0, 100.0, 100.0],  # both inverted
        ]
        for box in inverted_boxes:
            words = _extract_words_from_pdf_bbox(self.pdf_path, 1, box)
            # PyMuPDF with inverted rect must return empty list without crashing
            self.assertEqual(words, [], f"Expected empty word list for inverted bbox {box}")

            ident = SourceIdentity(page=1, table=0, row=0, bbox=box)
            issue = ReviewIssue(
                source_id=ident.source_id,
                identity=ident,
                raw_cells=["Augmentin 1g", "", "10%"],
                bbox=box,
                rejection_reason="missing_price",
            )
            candidate = recover_by_coordinates(issue, self.pdf_path)
            self.assertIsNone(candidate, f"Inverted bbox {box} must not produce recovered candidate")

    def test_extreme_aspect_ratios_handling(self):
        """Verify degenerate and extreme aspect ratio boxes (flat, needle, zero area) do not crash or corrupt extraction."""
        extreme_boxes = [
            [100.0, 300.0, 500.0, 300.0001],  # width=400, height=0.0001 (extremely flat line at empty area)
            [10.0, 50.0, 10.0001, 750.0],     # width=0.0001, height=700 (extremely thin vertical needle)
            [100.0, 100.0, 100.0, 100.0],     # zero width and zero height
            [0.0, 0.0, 0.0, 0.0],             # point at origin
        ]
        for box in extreme_boxes:
            words = _extract_words_from_pdf_bbox(self.pdf_path, 1, box)
            self.assertEqual(words, [], f"Extreme aspect box {box} at empty coordinates must yield 0 words safely")

            ident = SourceIdentity(page=1, table=0, row=0, bbox=box)
            issue = ReviewIssue(
                source_id=ident.source_id,
                identity=ident,
                raw_cells=["Augmentin 1g", "", "10%"],
                bbox=box,
                rejection_reason="missing_price",
            )
            candidate = recover_by_coordinates(issue, self.pdf_path)
            self.assertIsNone(candidate)

    def test_negative_and_out_of_page_coordinates(self):
        """Verify coordinates outside the PDF page dimensions (negative or huge coordinates) return empty safely."""
        out_boxes = [
            [-500.0, -500.0, -100.0, -100.0],  # purely negative
            [-100.0, -50.0, 50.0, 50.0],       # partially negative
            [2000.0, 3000.0, 2500.0, 3500.0],  # far beyond page height/width
        ]
        for box in out_boxes:
            words = _extract_words_from_pdf_bbox(self.pdf_path, 1, box)
            self.assertEqual(words, [], f"Out-of-page bbox {box} must yield 0 words safely")

    def test_nan_and_inf_coordinates_handling(self):
        """Verify that NaN or Inf in bounding boxes fail safely without crashing with OverflowError or ValueError."""
        corrupted_boxes = [
            [float("nan"), 100.0, 500.0, 150.0],
            [100.0, float("nan"), 500.0, 150.0],
            [100.0, 100.0, float("inf"), 150.0],
            [100.0, 100.0, 500.0, float("-inf")],
        ]
        for box in corrupted_boxes:
            ident = SourceIdentity(page=1, table=0, row=0, bbox=box)
            issue = ReviewIssue(
                source_id=ident.source_id,
                identity=ident,
                raw_cells=["Augmentin 1g", "", "10%"],
                bbox=box,
                rejection_reason="corrupted_bbox",
            )
            # Must not crash when passed to coordinate recovery
            try:
                candidate = recover_by_coordinates(issue, self.pdf_path)
                self.assertIsNone(candidate, "Corrupted NaN/Inf bbox must not recover candidate")
            except Exception as e:
                self.fail(f"Corrupted bbox {box} raised unhandled exception: {type(e).__name__}: {e}")

    def test_overlapping_bounding_boxes_deduplication(self):
        """Verify multiple issues referencing the exact same spatial bounding box never produce duplicate DataFrame rows."""
        shared_bbox = [100.0, 100.0, 500.0, 150.0]
        # Three issues pointing to the same row coordinates
        issues = [
            ReviewIssue(
                source_id=f"p1_t0_r{i}",
                identity=SourceIdentity(page=1, table=0, row=i, bbox=shared_bbox),
                raw_cells=["Augmentin 1g Tablets", "", "10%"],
                bbox=shared_bbox,
                rejection_reason="missing_price",
            )
            for i in range(3)
        ]
        empty_df = pd.DataFrame(columns=STANDARD_COLUMNS)
        diag = ImportDiagnostics(accepted_rows=0, unique_records=0)
        res = CatalogResult(
            dataframe=empty_df,
            diagnostics=diag,
            fingerprint=FileFingerprint.from_path(self.pdf_path),
            review_issues=issues,
            issues_by_source_id={iss.source_id: iss for iss in issues},
        )

        recovered_res = run_automatic_recovery(res, pdf_path=self.pdf_path)

        # First issue should recover the row; remaining 2 overlapping issues must NOT append duplicate rows!
        augmentin_rows = recovered_res.dataframe[
            recovered_res.dataframe["item_name"].str.contains("Augmentin", na=False)
        ]
        self.assertEqual(len(augmentin_rows), 1, f"Expected exactly 1 recovered row, got {len(augmentin_rows)}")
        self.assertEqual(len(recovered_res.dataframe), 1, "No duplicate rows should be added for overlapping bboxes")


class TestAdversarialAmbiguousNumericFields(unittest.TestCase):
    """2. Stress-testing ambiguous numeric fields to ensure the engine NEVER guesses values."""

    def test_two_plain_prices_never_guessed(self):
        """Verify recovery returns None when two numeric values both fall in price range without percent indicator."""
        raw_cells = ["Amoxicillin 500mg 20 Cap", "65.00", "85.00"]
        ident = SourceIdentity(page=1, table=0, row=1)
        issue = ReviewIssue(
            source_id=ident.source_id,
            identity=ident,
            raw_cells=raw_cells,
            rejection_reason="ambiguous_prices",
        )

        candidate = recover_by_column_roles(issue)
        self.assertIsNone(candidate, "Recovery must NEVER guess when two plain numbers both fall in price range")

        res = CatalogResult(
            dataframe=pd.DataFrame(columns=STANDARD_COLUMNS),
            diagnostics=ImportDiagnostics(),
            review_issues=[issue],
            issues_by_source_id={issue.source_id: issue},
        )
        recovered_res = run_automatic_recovery(res)
        self.assertFalse(issue.resolved, "Ambiguous issue must remain unresolved")
        self.assertEqual(issue.strategy_outcomes.get("column_role_resolution"), "unresolved_ambiguity")

    def test_two_plain_discounts_never_guessed(self):
        """Verify recovery returns None when two numeric values both fall in discount range (<= 0.85) without % indicator."""
        # E.g. "0.20" and "0.35": neither has %, both are <= 0.85
        raw_cells = ["Cataflam 50mg 20 Tab", "0.20", "0.35"]
        ident = SourceIdentity(page=1, table=0, row=2)
        issue = ReviewIssue(
            source_id=ident.source_id,
            identity=ident,
            raw_cells=raw_cells,
            rejection_reason="ambiguous_discounts",
        )

        candidate = recover_by_column_roles(issue)
        self.assertIsNone(candidate, "Recovery must NEVER guess between two plain decimal values <= 0.85")

    def test_two_explicit_percentages_never_guessed(self):
        """Verify recovery returns None when two values both have '%' indicator (cannot guess which is price or discount)."""
        raw_cells = ["Concor 5mg 30 Tab", "15%", "25%"]
        ident = SourceIdentity(page=1, table=0, row=3)
        issue = ReviewIssue(
            source_id=ident.source_id,
            identity=ident,
            raw_cells=raw_cells,
            rejection_reason="two_percentages",
        )

        candidate = recover_by_column_roles(issue)
        self.assertIsNone(candidate, "Recovery must NEVER guess when both columns are percentages")

    def test_percent_paired_with_explicit_zero_must_never_promote_percent_to_price(self):
        """
        Adversarial Challenge (Finding 1):
        When a row contains an explicit percentage (e.g. '10%' or '20%') and an explicit zero discount ('0%'),
        the recovery engine must NOT strip '%' from '10%' and treat it as a base_price of 10.00 EGP!
        """
        raw_cells_a = ["Panadol Extra 24 Tab", "10%", "0%"]
        ident_a = SourceIdentity(page=1, table=0, row=4)
        issue_a = ReviewIssue(
            source_id=ident_a.source_id,
            identity=ident_a,
            raw_cells=raw_cells_a,
            rejection_reason="test_percentages",
        )
        cand_a = recover_by_column_roles(issue_a)
        # If candidate is returned, verify that a percentage string was NOT assigned as price
        if cand_a is not None:
            self.assertNotEqual(
                cand_a.get("base_price"),
                10.0,
                "CRITICAL BUG: '10%' was incorrectly stripped and treated as base_price 10.0 EGP!",
            )

        raw_cells_b = ["Panadol Extra 24 Tab", "0%", "20%"]
        ident_b = SourceIdentity(page=1, table=0, row=5)
        issue_b = ReviewIssue(
            source_id=ident_b.source_id,
            identity=ident_b,
            raw_cells=raw_cells_b,
            rejection_reason="test_percentages",
        )
        cand_b = recover_by_column_roles(issue_b)
        if cand_b is not None:
            self.assertNotEqual(
                cand_b.get("base_price"),
                20.0,
                "CRITICAL BUG: '20%' was incorrectly stripped and treated as base_price 20.0 EGP!",
            )

    def test_three_numeric_columns_never_arbitrarily_sliced(self):
        """
        Adversarial Challenge (Finding 2):
        When a row contains 3 numeric columns (e.g. Item Code '501', Discount '15%', and Base Price '50.00'),
        the recovery engine must NOT blindly truncate to num_candidates[:2] and treat Item Code '501' as base price 501.0!
        """
        raw_cells = ["Panadol Extra 24 Tab", "501", "15%", "50.00"]
        ident = SourceIdentity(page=1, table=0, row=6)
        issue = ReviewIssue(
            source_id=ident.source_id,
            identity=ident,
            raw_cells=raw_cells,
            rejection_reason="three_numbers",
        )
        candidate = recover_by_column_roles(issue)
        # It must either remain unresolved (None) OR correctly identify 50.00 as price (NOT 501.0)
        if candidate is not None:
            self.assertNotEqual(
                candidate.get("base_price"),
                501.0,
                "CRITICAL BUG: Slicing truncation treated item code '501' as base_price 501.0 EGP!",
            )

    def test_canonical_validation_rejects_out_of_bounds_numerics(self):
        """Verify shared validate_catalog_item rejects out-of-bounds prices and discounts."""
        # 1. Price <= 0.0
        v, err = validate_catalog_item({"item_name": "Aspirin", "base_price": 0.0, "discount_rate": 0.1})
        self.assertFalse(v)
        self.assertIn("invalid_price_zero_or_negative", err)

        # 2. Price >= 10000.0
        v, err = validate_catalog_item({"item_name": "Aspirin", "base_price": 10000.0, "discount_rate": 0.1})
        self.assertFalse(v)
        self.assertIn("invalid_price_out_of_bounds", err)

        # 3. Discount < 0.0
        v, err = validate_catalog_item({"item_name": "Aspirin", "base_price": 50.0, "discount_rate": -0.05})
        self.assertFalse(v)
        self.assertIn("invalid_discount_negative", err)

        # 4. Discount > 0.85 (85%)
        v, err = validate_catalog_item({"item_name": "Aspirin", "base_price": 50.0, "discount_rate": 0.90})
        self.assertFalse(v)
        self.assertIn("invalid_discount_out_of_bounds", err)

        # 5. Discount > 85% as string
        v, err = validate_catalog_item({"item_name": "Aspirin", "base_price": 50.0, "discount_rate": "95%"})
        self.assertFalse(v)
        self.assertIn("invalid_discount_out_of_bounds", err)


class TestAdversarialWrappedBiDiAndNoiseTokens(unittest.TestCase):
    """3. Stress-testing multi-line wrapped Arabic, Latin, and mixed tokens."""

    def test_wrapped_latin_text_order_preserved(self):
        """Verify wrapped Latin text preserves left-to-right character and token order without letter reversal."""
        wrapped_latin = "PANADOL ADVANCE 500MG\n24 FILM-COATED TABLETS\nGLAXOSMITHKLINE"
        cleaned = reconstruct_wrapped_name(wrapped_latin)

        self.assertIn("PANADOL ADVANCE 500MG", cleaned)
        self.assertIn("24 FILM-COATED TABLETS", cleaned)
        self.assertIn("GLAXOSMITHKLINE", cleaned)

        # Ensure no reverse artifacts like "GM005" or "STELBAT"
        self.assertNotIn("GM005", cleaned)
        self.assertNotIn("STELBAT", cleaned)
        self.assertNotIn("ENILKHTIMS", cleaned)

    def test_wrapped_mixed_arabic_latin_preserves_reading_order(self):
        """Verify wrapped lines with mixed Arabic and Latin keep Latin forward and Arabic intact."""
        mixed_input = "أوجمنتين 1 جم أقراص\nAugmentin 1g Tablets\n14 قرص"
        cleaned = reconstruct_wrapped_name(mixed_input)

        self.assertIn("أوجمنتين", cleaned)
        self.assertIn("Augmentin", cleaned)
        self.assertIn("1g Tablets", cleaned)
        self.assertIn("14 قرص", cleaned)

        # Verify Latin is forward
        self.assertNotIn("nitnemguA", cleaned)
        self.assertNotIn("g1", cleaned.lower().split("augmentin")[0])  # "1g" not reversed

        valid, err = validate_catalog_item({
            "item_name": cleaned,
            "base_price": 125.0,
            "discount_rate": 0.15,
            "stock_status": True,
        })
        self.assertTrue(valid, f"Reconstructed mixed medication failed validation: {err}")

    def test_wrapped_arabic_with_eastern_arabic_digits(self):
        """Verify wrapped Arabic lines containing Eastern Arabic-Indic digits (٥, ٣٠) parse cleanly."""
        arabic_eastern = "كونكور ٥ مجم\n٣٠ قرص"
        cleaned = reconstruct_wrapped_name(arabic_eastern)

        self.assertIn("كونكور", cleaned)
        dosage, pack = parse_dosage_and_pack(cleaned)
        self.assertEqual(dosage, "5مجم")
        self.assertEqual(pack, "30قرص")

    def test_wrapped_name_filters_embedded_noise(self):
        """Verify wrapped text containing embedded header labels or catalog noise strips noise lines cleanly."""
        noisy_wrap = "سعر الجمهور\nPanadol Extra 24 Tab\nGlaxoSmithKline"
        cleaned = reconstruct_wrapped_name(noisy_wrap)

        # "سعر الجمهور" is a header label and must be excluded from the medication name
        self.assertNotIn("سعر الجمهور", cleaned)
        self.assertIn("Panadol Extra 24 Tab", cleaned)
        self.assertIn("GlaxoSmithKline", cleaned)

    def test_reversed_arabic_catalog_unreversing(self):
        """Verify reversed Arabic catalog text (e.g. visual LTR order 'صرق ٠٣') un-reverses cleanly."""
        reversed_arabic = "صرق ٠٣\nطيرش ٢"
        cleaned = reconstruct_wrapped_name(reversed_arabic)

        self.assertIn("قرص", cleaned)
        self.assertIn("شريط", cleaned)
        self.assertNotIn("صرق", cleaned)
        self.assertNotIn("طيرش", cleaned)


class TestAdversarialRecoveryIdempotency(unittest.TestCase):
    """4. Stress-testing recovery idempotency across 10 repeat executions."""

    def test_idempotency_across_ten_iterations(self):
        """Verify 10 consecutive executions of run_automatic_recovery produce identical rows, counters, and status."""
        # Setup catalog result with:
        # - 1 already-accepted baseline row
        # - 1 recoverable wrapped issue
        # - 1 recoverable swapped column issue
        # - 1 unresolvable ambiguous issue
        baseline_df = pd.DataFrame([{
            "warehouse_name": "TestWh",
            "item_name": "Cataflam 50mg 20 Tab",
            "normalized_name": "cataflam 50mg 20 tab",
            "dosage": "50mg",
            "unit_size": "20 tab",
            "base_price": 45.0,
            "discount_rate": 0.15,
            "stock_status": True,
            "_source_id": "p1_t0_r0",
        }])
        diag = ImportDiagnostics(accepted_rows=1, unique_records=1)

        wrapped_issue = ReviewIssue(
            source_id="p1_t0_r1",
            identity=SourceIdentity(page=1, table=0, row=1),
            raw_cells=["كونكور 5 مجم\n30 قرص", "85.50", "20%"],
            rejection_reason="wrapped_name",
            resolved=False,
        )
        swapped_issue = ReviewIssue(
            source_id="p1_t0_r2",
            identity=SourceIdentity(page=1, table=0, row=2),
            raw_cells=["Panadol Extra 24 Tab", "15%", "55.00"],
            rejection_reason="swapped_columns",
            resolved=False,
        )
        unresolvable_issue = ReviewIssue(
            source_id="p1_t0_r3",
            identity=SourceIdentity(page=1, table=0, row=3),
            raw_cells=["Amoxicillin 500mg 20 Cap", "60.00", "70.00"],
            rejection_reason="ambiguous_prices",
            resolved=False,
        )

        all_issues = [wrapped_issue, swapped_issue, unresolvable_issue]
        res = CatalogResult(
            dataframe=baseline_df,
            diagnostics=diag,
            fingerprint=None,
            review_issues=all_issues,
            issues_by_source_id={iss.source_id: iss for iss in all_issues},
        )

        # Run 1st recovery
        res1 = run_automatic_recovery(res)
        count1 = len(res1.dataframe)
        unres1 = sum(1 for iss in res1.review_issues if not iss.resolved)
        rec1 = res1.diagnostics.successful_recovery_count
        att1 = res1.diagnostics.attempted_recovery_count

        self.assertEqual(count1, 3, "Expected 1 baseline + 2 recovered items = 3 items")
        self.assertEqual(unres1, 1, "Expected 1 unresolvable item remaining")
        self.assertEqual(rec1, 2, "Expected exactly 2 successful recoveries")

        # Run iterations 2 through 10
        prev_df = res1.dataframe.copy(deep=True)
        for i in range(2, 11):
            res_i = run_automatic_recovery(res1)

            # 1. Row count must not grow
            self.assertEqual(len(res_i.dataframe), count1, f"Iteration {i} altered DataFrame row count!")

            # 2. DataFrame values must remain identical
            pd.testing.assert_frame_equal(
                res_i.dataframe,
                prev_df,
                check_like=False,
                obj=f"Iteration {i} modified DataFrame content",
            )

            # 3. Unresolved issues count must not flip
            unres_i = sum(1 for iss in res_i.review_issues if not iss.resolved)
            self.assertEqual(unres_i, unres1, f"Iteration {i} changed unresolved count!")

            # 4. Attempted / successful counters must not double-count
            self.assertEqual(res_i.diagnostics.successful_recovery_count, rec1)
            self.assertEqual(res_i.diagnostics.attempted_recovery_count, att1)

            # 5. Attempted strategies must not contain duplicate strategy names
            for iss in res_i.review_issues:
                strat_list = iss.attempted_strategies
                self.assertEqual(
                    len(strat_list),
                    len(set(strat_list)),
                    f"Iteration {i} added duplicate strategy entries to {iss.source_id}: {strat_list}",
                )

    def test_service_level_idempotency_with_clean_columns(self):
        """Verify repeated calls to CatalogCorrectionService.run_bounded_automatic_recovery maintain standard columns."""
        service = CatalogCorrectionService("dummy_idempotent.pdf")
        baseline_df = pd.DataFrame([{
            "warehouse_name": "TestWh",
            "item_name": "Cataflam 50mg 20 Tab",
            "normalized_name": "cataflam 50mg 20 tab",
            "dosage": "50mg",
            "unit_size": "20 tab",
            "base_price": 45.0,
            "discount_rate": 0.15,
            "stock_status": True,
            "_source_id": "p1_t0_r0",
        }])
        diag = ImportDiagnostics(accepted_rows=1, unique_records=1)
        res = CatalogResult(dataframe=baseline_df, diagnostics=diag, fingerprint=None)
        service._base_catalog_result = res

        res1 = service.run_bounded_automatic_recovery()
        res2 = service.run_bounded_automatic_recovery()
        res3 = service.run_bounded_automatic_recovery()

        self.assertEqual(len(res1.dataframe), len(res2.dataframe))
        self.assertEqual(len(res2.dataframe), len(res3.dataframe))
        pd.testing.assert_frame_equal(res1.dataframe, res2.dataframe)
        pd.testing.assert_frame_equal(res2.dataframe, res3.dataframe)


class TestAdversarialRowCountAccounting(unittest.TestCase):
    """5. Stress-testing row count accounting to ensure unmapped regions never hallucinate candidate rows."""

    def test_unmapped_region_issue_accounting(self):
        """Verify unmapped region issue sets candidate_rows=0, expected_count_known=False, and tracks region count."""
        rem_bbox = [50.0, 100.0, 550.0, 700.0]
        region_diag = RowDiagnostic(
            page=2,
            table=1,
            group=0,
            row=None,
            outcome="rejected",
            reason="unmapped_table_layout",
            bbox=rem_bbox,
            raw_cells=[["Garbled col 1", "Garbled col 2"]],
            is_region_issue=True,
            source_id="p2_t1_region",
        )
        legacy_grp = GroupDiagnostics(
            group=0,
            strategy="unmapped_table_t1",
            candidate_rows=0,
            accepted_rows=0,
            rejected_rows=0,
            unprocessed_rows=0,
            bbox=rem_bbox,
            rows=[region_diag],
        )
        page_diag = PageDiagnostics(
            page=2,
            strategy="legacy",
            expected_count_known=False,
            accepted_rows=0,
            groups=[legacy_grp],
        )
        import_diag = ImportDiagnostics(
            pages=[page_diag],
            accepted_rows=0,
            unique_records=0,
            unresolved_region_count=1,
        )

        self.assertEqual(import_diag.candidate_rows, 0, "Unmapped region must not hallucinate candidate rows")
        self.assertEqual(import_diag.accepted_rows, 0)
        self.assertEqual(import_diag.rejected_rows, 0)
        self.assertEqual(import_diag.unresolved_region_count, 1)
        self.assertFalse(page_diag.expected_count_known)
        self.assertEqual(import_diag.status, "failed")

    def test_catalog_with_only_unmapped_regions(self):
        """Verify a catalog consisting entirely of unmapped tables never hallucinates candidate rows or marks complete."""
        groups = [
            GroupDiagnostics(
                group=i,
                strategy=f"unmapped_table_t{i}",
                candidate_rows=0,
                accepted_rows=0,
                rejected_rows=0,
                unprocessed_rows=0,
                bbox=[40.0, 100.0 * i, 560.0, 100.0 * (i + 1)],
                rows=[
                    RowDiagnostic(
                        page=1,
                        table=i,
                        group=i,
                        row=None,
                        outcome="rejected",
                        reason="unmapped_table_layout",
                        is_region_issue=True,
                        source_id=f"p1_t{i}_region",
                    )
                ],
            )
            for i in range(3)
        ]
        page = PageDiagnostics(page=1, strategy="legacy", expected_count_known=False, accepted_rows=0, groups=groups)
        diag = ImportDiagnostics(pages=[page], accepted_rows=0, unique_records=0, unresolved_region_count=3)

        self.assertEqual(diag.candidate_rows, 0)
        self.assertEqual(diag.accepted_rows, 0)
        self.assertEqual(diag.unresolved_region_count, 3)
        self.assertNotEqual(diag.status, "complete", "Unmapped regions must never be marked complete")

    def test_automatic_recovery_on_unmapped_regions_does_not_hallucinate(self):
        """Verify run_automatic_recovery on unmapped region issues does not invent rows or alter candidate counts."""
        ident = SourceIdentity(page=1, table=0, row=None, bbox=[50.0, 50.0, 550.0, 750.0], is_region_issue=True)
        issue = ReviewIssue(
            source_id="p1_t0_region",
            identity=ident,
            raw_cells=[["Header A", "Header B", "Header C"]],
            rejection_reason="unmapped_table_layout",
            resolved=False,
        )
        empty_df = pd.DataFrame(columns=STANDARD_COLUMNS)
        diag = ImportDiagnostics(
            pages=[PageDiagnostics(page=1, strategy="fallback", expected_count_known=False, accepted_rows=0)],
            accepted_rows=0,
            unique_records=0,
            unresolved_region_count=1,
        )
        res = CatalogResult(
            dataframe=empty_df,
            diagnostics=diag,
            fingerprint=None,
            review_issues=[issue],
            issues_by_source_id={issue.source_id: issue},
        )

        recovered_res = run_automatic_recovery(res)

        self.assertEqual(len(recovered_res.dataframe), 0, "No candidate rows should be hallucinated")
        self.assertFalse(issue.resolved, "Unmapped region issue must remain unresolved")
        self.assertEqual(recovered_res.diagnostics.accepted_rows, 0)
        self.assertEqual(recovered_res.diagnostics.candidate_rows, 0)
        self.assertFalse(recovered_res.diagnostics.pages[0].expected_count_known)

    def test_unverified_coverage_never_marked_complete(self):
        """Verify that any page where expected_count_known is False leaves the status as 'unverified', never 'complete'."""
        page_diag = PageDiagnostics(
            page=1,
            strategy="fallback",
            expected_count_known=False,
            accepted_rows=5,
            groups=[GroupDiagnostics(group=0, strategy="fallback", candidate_rows=5, accepted_rows=5)],
        )
        diag = ImportDiagnostics(
            pages=[page_diag],
            accepted_rows=5,
            unique_records=5,
            errors=[],
            warnings=[],
            unresolved_region_count=0,
        )
        self.assertEqual(diag.status, "unverified", "Status must be unverified when expected_count_known is False")


if __name__ == "__main__":
    unittest.main()
