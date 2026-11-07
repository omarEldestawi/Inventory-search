import unittest
import pandas as pd

from src.allocator import MedicineAllocator
from src.catalog_diagnostics import (
    CatalogResult, ImportDiagnostics, PageDiagnostics, GroupDiagnostics,
    RowDiagnostic, ReviewIssue
)
from src.pipeline import _build_consolidated_inventory, PipelineExecutionError


class TestReviewIssueProcurementExclusion(unittest.TestCase):
    """
    Demonstrates and formally tests that an unresolved ReviewIssue:
    1. Persists with resolved=False on CatalogResult.review_issues.
    2. Blocks unacknowledged pipeline execution if diagnostics require acknowledgment.
    3. When partial import is explicitly acknowledged (allow_partial_imports=True),
       the clean rows are imported, BUT the unresolved row is STRICTLY EXCLUDED from
       consolidated inventory and CANNOT enter automatic procurement allocation.
    4. Proves that acknowledgment alone NEVER admits the unresolved item into procurement.
    """

    def setUp(self):
        # 1. Catalog with 2 clean items and 1 item with an unresolved ReviewIssue
        self.catalog_data = [
            {
                "warehouse_name": "Warehouse_Alpha",
                "item_name": "CONCOR 5 MG 30 TAB",
                "base_price": 40.50,
                "discount_rate": 0.20,
                "stock_status": True,
                "source_id": "item_001",
            },
            {
                "warehouse_name": "Warehouse_Alpha",
                "item_name": "AUGMENTIN 1 GM 14 TAB",
                "base_price": 99.00,
                "discount_rate": 0.25,
                "stock_status": True,
                "source_id": "item_002",
            },
            {
                "warehouse_name": "Warehouse_Alpha",
                "item_name": "ANOMALOUS DRUG 120 GM 10 TAB",
                "base_price": 120.00,
                "discount_rate": 0.30,
                "stock_status": True,
                "source_id": "item_003_anomalous",
            },
        ]
        self.df = pd.DataFrame(self.catalog_data)

        # 2. Attach an unresolved ReviewIssue for item_003_anomalous
        self.unresolved_issue = ReviewIssue(
            source_id="item_003_anomalous",
            rejection_reason="clinical_dose_anomaly",
            resolved=False,
        )

        row_group = GroupDiagnostics(
            group=0,
            strategy="table",
            candidate_rows=3,
            accepted_rows=2,
            rejected_rows=1,
            rows=[
                RowDiagnostic(page=1, group=0, row=0, source_id="item_001", outcome="accepted"),
                RowDiagnostic(page=1, group=0, row=1, source_id="item_002", outcome="accepted"),
                RowDiagnostic(page=1, group=0, row=2, source_id="item_003_anomalous", outcome="rejected", reason="clinical_dose_anomaly"),
            ]
        )
        page = PageDiagnostics(page=1, groups=[row_group])
        self.diag = ImportDiagnostics(
            pages=[page],
            accepted_rows=2,
            unique_records=2,
            unresolved_region_count=1,
        )

        self.catalog_result = CatalogResult(
            dataframe=self.df.copy(),
            diagnostics=self.diag,
            review_issues=[self.unresolved_issue],
        )

    def test_review_issue_persists_unresolved_status(self):
        """Verifies that the ReviewIssue preserves its unresolved state."""
        self.assertEqual(len(self.catalog_result.review_issues), 1)
        issue = self.catalog_result.review_issues[0]
        self.assertEqual(issue.source_id, "item_003_anomalous")
        self.assertFalse(issue.resolved)
        self.assertEqual(issue.rejection_reason, "clinical_dose_anomaly")

    def test_unacknowledged_import_is_blocked(self):
        """Verifies that unacknowledged partial import raises PipelineExecutionError."""
        serialized_df = self.catalog_result.to_dataframe()
        with self.assertRaises(PipelineExecutionError) as ctx:
            _build_consolidated_inventory([serialized_df], allow_partial_imports=False)
        self.assertIn("Explicit acknowledgment is required", str(ctx.exception))

    def test_acknowledgment_admits_clean_rows_but_strictly_excludes_unresolved_row(self):
        """
        CRITICAL SAFETY INVARIANT:
        User acknowledgment allows the pipeline to proceed with clean rows,
        but the unresolved row (source_id='item_003_anomalous') is strictly filtered out.
        Acknowledgment ALONE can NEVER admit an unresolved row into procurement!
        """
        serialized_df = self.catalog_result.to_dataframe()
        
        # User explicitly acknowledges partial import
        consolidated = _build_consolidated_inventory([serialized_df], allow_partial_imports=True)
        
        # 1. Total items should be 2 (only the clean rows)
        self.assertEqual(len(consolidated), 2)
        
        # 2. Clean items are admitted
        admitted_sids = set(consolidated["source_id"].tolist())
        self.assertIn("item_001", admitted_sids)
        self.assertIn("item_002", admitted_sids)
        
        # 3. Unresolved item is strictly excluded
        self.assertNotIn("item_003_anomalous", admitted_sids)
        self.assertFalse(any("ANOMALOUS" in name for name in consolidated["item_name"]))

    def test_automatic_procurement_cannot_allocate_excluded_unresolved_row(self):
        """
        Demonstrates that downstream MedicineAllocator cannot purchase or allocate
        an unresolved item because it was excluded from consolidated inventory.
        """
        serialized_df = self.catalog_result.to_dataframe()
        consolidated = _build_consolidated_inventory([serialized_df], allow_partial_imports=True)
        consolidated["normalized_name"] = consolidated["item_name"]
        
        allocator = MedicineAllocator(warehouse_inventory=consolidated, enable_ai=False)
        
        # User order requesting the anomalous item
        order_df = pd.DataFrame([
            {"requested_item": "ANOMALOUS DRUG 120 GM 10 TAB", "quantity": 5},
            {"requested_item": "CONCOR 5 MG 30 TAB", "quantity": 10},
        ])
        
        alloc_res = allocator.allocate_order(order_df)
        master = alloc_res["master_comparison"]
        oos = alloc_res["out_of_stock"]
        
        # CONCOR was clean and is allocated to Warehouse_Alpha
        concor_row = master[master["اسم الصنف المطلوب (في طلب الشراء)"] == "CONCOR 5 MG 30 TAB"]
        self.assertEqual(len(concor_row), 1)
        self.assertEqual(concor_row["المخزن الفائز"].iloc[0], "Warehouse_Alpha")
        
        # ANOMALOUS DRUG was excluded from inventory and therefore cannot be procured (routes to Out-of-Stock)
        anom_master = master[master["اسم الصنف المطلوب (في طلب الشراء)"] == "ANOMALOUS DRUG 120 GM 10 TAB"]
        self.assertEqual(len(anom_master), 0, "Excluded item must not appear as an allocated order in master comparison")
        
        self.assertFalse(oos.empty)
        anom_oos = oos[oos["اسم الصنف المطلوب"].str.contains("ANOMALOUS")]
        self.assertEqual(len(anom_oos), 1, "Excluded item must be routed to out_of_stock")


if __name__ == "__main__":
    unittest.main()
