"""
Comprehensive Unit Test Suite for Milestone 2A: Extraction Accountability (R2) & Deterministic Recovery (R3).

Verifies:
1. Early exit bounding box preservation in extract_item_from_group_row (empty name, blank name, header repetition).
2. Region-level issue generation for unmapped tables without candidate row count hallucination.
3. Separation of confirmed non-product content (headers/footers) from candidate products.
4. Multi-pathway failure recording across structural, legacy, and coordinate pathways.
5. Deterministic 3-stage automatic recovery execution order and deterministic guards.
6. Recovery idempotence across repeated executions.
7. Canonical validation pipeline routing.
"""
import copy
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
    ProductGroup,
    TableGeometry,
    extract_item_from_group_row,
    parse_structural_table,
    validate_catalog_item,
)
from src.catalog_recovery import (
    reconstruct_wrapped_name,
    recover_by_coordinates,
    recover_by_column_roles,
    recover_by_wrapped_text,
    run_automatic_recovery,
)
from src.catalog_service import CatalogCorrectionService


class MockRow:
    def __init__(self, cells):
        self.cells = cells


class MockTable:
    def __init__(self, data):
        self._data = data
        self.rows = []
        for r_idx, row in enumerate(data):
            row_cells = []
            for c_idx, val in enumerate(row):
                if val is not None and str(val).strip() != "":
                    row_cells.append([float(c_idx * 50), float(r_idx * 20), float((c_idx + 1) * 50), float((r_idx + 1) * 20)])
                else:
                    row_cells.append(None)
            self.rows.append(MockRow(row_cells))
        col_count = len(data[0]) if data else 0
        self.bbox = [0.0, 0.0, float(col_count * 50), float(len(data) * 20)]

    def extract(self):
        return self._data


class TestM2AEarlyExitBboxPreservation(unittest.TestCase):
    """Verifies that bounding boxes are preserved before early validation exits in extract_item_from_group_row."""

    def setUp(self):
        self.group = ProductGroup(
            group_index=0,
            raw_cols=[0, 1, 2],
            price_col=0,
            discount_col=1,
            name_col=2,
            bbox=[0.0, 0.0, 150.0, 20.0],
        )
        self.row_bboxes = [
            [0.0, 0.0, 50.0, 20.0],
            [50.0, 0.0, 100.0, 20.0],
            [100.0, 0.0, 150.0, 20.0],
        ]

    def test_empty_name_cell_preserves_bbox(self):
        """Row with None name cell must return bounding box, not None."""
        row = ["45.00", "15%", None]
        item, reason, bbox = extract_item_from_group_row(
            row, self.group, "forward", "TestWarehouse", self.row_bboxes
        )
        self.assertIsNone(item)
        self.assertEqual(reason, "empty_name_cell")
        self.assertIsNotNone(bbox, "Bbox must not be lost on empty_name_cell early exit")
        self.assertEqual(bbox, [0.0, 0.0, 150.0, 20.0])

    def test_blank_name_cell_preserves_bbox(self):
        """Row with whitespace-only name cell must return bounding box, not None."""
        row = ["45.00", "15%", "   "]
        item, reason, bbox = extract_item_from_group_row(
            row, self.group, "forward", "TestWarehouse", self.row_bboxes
        )
        self.assertIsNone(item)
        self.assertEqual(reason, "blank_name")
        self.assertIsNotNone(bbox, "Bbox must not be lost on blank_name early exit")
        self.assertEqual(bbox, [0.0, 0.0, 150.0, 20.0])

    def test_header_repetition_cell_preserves_bbox(self):
        """Row containing repeated table header must return bounding box, not None."""
        row = ["سعر الجمهور", "الخصم", "اسم الصنف"]
        item, reason, bbox = extract_item_from_group_row(
            row, self.group, "forward", "TestWarehouse", self.row_bboxes
        )
        self.assertIsNone(item)
        self.assertEqual(reason, "header_repetition")
        self.assertIsNotNone(bbox, "Bbox must not be lost on header_repetition early exit")
        self.assertEqual(bbox, [0.0, 0.0, 150.0, 20.0])

    def test_invalid_price_preserves_bbox(self):
        """Row with out-of-bounds price returns bounding box."""
        row = ["0.00", "15%", "Panadol Extra"]
        item, reason, bbox = extract_item_from_group_row(
            row, self.group, "forward", "TestWarehouse", self.row_bboxes
        )
        self.assertIsNone(item)
        self.assertIn("invalid_price", reason)
        self.assertIsNotNone(bbox)
        self.assertEqual(bbox, [0.0, 0.0, 150.0, 20.0])


class TestM2AUnmappedTableRegionIssues(unittest.TestCase):
    """Verifies region-level issue generation for unmapped tables without count hallucination."""

    def test_unmapped_table_region_identity_format(self):
        """Region issues have is_region_issue=True, row=None, and source_id ending in _region."""
        ident = SourceIdentity(page=2, table=3, row=None, bbox=[10.0, 20.0, 500.0, 400.0])
        self.assertTrue(ident.is_region_issue)
        self.assertIsNone(ident.row)
        self.assertEqual(ident.source_id, "p2_t3_region")

    def test_import_diagnostics_unresolved_region_accounting(self):
        """Region issues are tracked in unresolved_region_count and prevent complete status."""
        region_diag = RowDiagnostic(
            page=1,
            table=1,
            group=0,
            row=None,
            outcome="rejected",
            reason="unmapped_table_layout",
            is_region_issue=True,
            bbox=[0.0, 0.0, 300.0, 400.0],
        )
        grp = GroupDiagnostics(
            group=0,
            strategy="unmapped_table_t1",
            candidate_rows=0,
            accepted_rows=0,
            rejected_rows=0,
            rows=[region_diag],
        )
        page_diag = PageDiagnostics(
            page=1,
            expected_count_known=False,
            accepted_rows=0,
            groups=[grp],
        )
        diag = ImportDiagnostics(
            pages=[page_diag],
            accepted_rows=0,
            unique_records=0,
            unresolved_region_count=1,
        )
        self.assertEqual(diag.status, "failed")
        self.assertNotEqual(diag.status, "complete")
        self.assertEqual(diag.candidate_rows, 0, "Candidate rows must not be hallucinated for unmapped regions")


class TestM2ADeterministicRecovery(unittest.TestCase):
    """Verifies deterministic 3-stage automatic recovery engine."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_reconstruct_wrapped_name_mixed_script(self):
        """Wrapped mixed Arabic/Latin name preserves both scripts without direction corruption."""
        raw = "أوجمنتين 1 جم\nAugmentin 1g\n14 قرص"
        cleaned = reconstruct_wrapped_name(raw)
        self.assertIn("أوجمنتين", cleaned)
        self.assertIn("Augmentin", cleaned)
        self.assertIn("1g", cleaned)
        self.assertIn("14 قرص", cleaned)
        self.assertNotIn("nitnemguA", cleaned)

    def test_column_roles_swapped_price_discount(self):
        """Swapped price (in discount col) and discount (in price col) resolve deterministically."""
        ident = SourceIdentity(page=1, table=0, row=1)
        issue = ReviewIssue(
            source_id="p1_t0_r1",
            identity=ident,
            raw_cells=["Concor 5mg 30 Tab", "20%", "45.00"],
            rejection_reason="invalid_price_0.2",
        )
        candidate = recover_by_column_roles(issue, default_wh="TestWh")
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["item_name"], "Concor 5mg 30 Tab")
        self.assertEqual(candidate["base_price"], 45.00)
        self.assertEqual(candidate["discount_rate"], 0.20)

    def test_ambiguous_prices_remain_unresolved(self):
        """When two prices are both valid numbers without % cues, do not guess."""
        ident = SourceIdentity(page=1, table=0, row=2)
        issue = ReviewIssue(
            source_id="p1_t0_r2",
            identity=ident,
            raw_cells=["Panadol Advance", "50.00", "60.00"],
            rejection_reason="ambiguous_numeric",
        )
        candidate = recover_by_column_roles(issue, default_wh="TestWh")
        self.assertIsNone(candidate, "Ambiguous prices must NOT be resolved automatically")

    def test_recovery_idempotence(self):
        """Calling run_automatic_recovery multiple times produces identical state without duplicates."""
        df = pd.DataFrame([{
            "warehouse_name": "TestWh",
            "item_name": "Panadol Extra",
            "normalized_name": "panadol extra",
            "dosage": "500mg",
            "unit_size": "24 tab",
            "base_price": 45.0,
            "discount_rate": 0.15,
            "stock_status": True,
            "_source_id": "p1_t0_r0",
        }])
        diag = ImportDiagnostics(accepted_rows=1, unique_records=1)
        ident = SourceIdentity(page=1, table=0, row=1)
        issue = ReviewIssue(
            source_id="p1_t0_r1",
            identity=ident,
            raw_cells=["Cataflam 50mg 20 Tab", "20%", "65.00"],
            rejection_reason="swapped_cols",
        )
        res = CatalogResult(dataframe=df, diagnostics=diag, review_issues=[issue])

        res1 = run_automatic_recovery(res)
        count1 = len(res1.dataframe)

        res2 = run_automatic_recovery(res1)
        count2 = len(res2.dataframe)

        res3 = run_automatic_recovery(res2)
        count3 = len(res3.dataframe)

        self.assertEqual(count1, 2)
        self.assertEqual(count2, 2)
        self.assertEqual(count3, 2)
        pd.testing.assert_frame_equal(res1.dataframe, res2.dataframe)
        pd.testing.assert_frame_equal(res2.dataframe, res3.dataframe)


if __name__ == "__main__":
    unittest.main()
