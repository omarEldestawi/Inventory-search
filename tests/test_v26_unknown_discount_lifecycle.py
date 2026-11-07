import io
import math
import os
import numpy as np
import pandas as pd
import unittest

from src.allocator import MedicineAllocator
from src.catalog_diagnostics import CatalogResult, ImportDiagnostics, FileFingerprint
from src.controller import CatalogCache, validate_cached_catalog
from src.pipeline import _build_consolidated_inventory


class TestUnknownDiscountLifecycle(unittest.TestCase):
    """
    Verifies that unknown or unreadable discounts remain explicitly unknown (None / NaN)
    throughout their complete lifecycle:
    1. Recovery representation (distinct from explicit zero discounts).
    2. Caching layer (CatalogCache & validate_cached_catalog).
    3. Pipeline inventory consolidation (_build_consolidated_inventory).
    4. Data export (to_dict and CSV serialization).
    5. Order allocation (MedicineAllocator multi-warehouse comparison).
    """

    def setUp(self):
        self.raw_data = [
            # Item 1: Explicit zero discount (e.g. net price / 0% / صافي)
            {
                "warehouse_name": "Warehouse_Alpha",
                "item_name": "CONCOR 5 MG 30 TAB",
                "base_price": 40.50,
                "discount_rate": 0.0,
                "stock_status": True,
            },
            # Item 2: Explicit positive discount (e.g. 20%)
            {
                "warehouse_name": "Warehouse_Alpha",
                "item_name": "AUGMENTIN 1 GM 14 TAB",
                "base_price": 99.00,
                "discount_rate": 0.20,
                "stock_status": True,
            },
            # Item 3: Unknown / Missing discount (OCR unreadable or empty cell)
            {
                "warehouse_name": "Warehouse_Alpha",
                "item_name": "PANADOL EXTRA 24 TAB",
                "base_price": 35.00,
                "discount_rate": None,
                "stock_status": True,
            },
        ]
        self.df = pd.DataFrame(self.raw_data)

    def test_unknown_discount_preserved_in_dataframe_representation(self):
        """Checks that None discount remains NaN/None and is distinct from explicit 0.0."""
        df = self.df.copy()
        
        # Item 1: explicit 0.0
        self.assertEqual(df.loc[0, "discount_rate"], 0.0)
        self.assertFalse(pd.isna(df.loc[0, "discount_rate"]))
        
        # Item 3: unknown discount
        self.assertTrue(pd.isna(df.loc[2, "discount_rate"]))
        self.assertNotEqual(df.loc[2, "discount_rate"], 0.0)

    def test_unknown_discount_preserved_through_caching(self):
        """Checks that CatalogCache and validate_cached_catalog preserve unknown discount as NaN/None."""
        import tempfile
        cache = CatalogCache()

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(b"%PDF-1.4 dummy content")
            tmp_path = tmp.name

        try:
            # Create CatalogResult with authentic FileFingerprint from disk
            fp = FileFingerprint.from_path(tmp_path)
            diag = ImportDiagnostics(pages=[])
            res = CatalogResult(dataframe=self.df.copy(), diagnostics=diag, fingerprint=fp)
            
            # Cache the dataframe
            cache.set(tmp_path, res.to_dataframe())
            
            # Retrieve from cache
            cached_df = cache.get(tmp_path)
            self.assertIsNotNone(cached_df)
            
            # Verify cached entries preserve NaN vs 0.0 distinction
            self.assertEqual(cached_df.loc[0, "discount_rate"], 0.0)
            self.assertTrue(pd.isna(cached_df.loc[2, "discount_rate"]))
            self.assertNotEqual(cached_df.loc[2, "discount_rate"], 0.0)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_unknown_discount_safeguard_in_consolidated_procurement(self):
        """
        Checks that _build_consolidated_inventory applies a strict procurement safeguard:
        Rows with unknown discounts cannot be safely procured (would require guessing net price).
        Therefore, they are excluded from consolidated procurement inventory, while clean rows
        with explicit zero or positive discounts are admitted.
        """
        consolidated = _build_consolidated_inventory([self.df.copy()])
        
        # Only 2 rows admitted (Item 1 with 0.0 and Item 2 with 0.20)
        self.assertEqual(len(consolidated), 2)
        self.assertEqual(consolidated.loc[0, "discount_rate"], 0.0)
        self.assertEqual(consolidated.loc[1, "discount_rate"], 0.20)
        
        # Item 3 (unknown discount) is safely excluded from automatic procurement
        self.assertFalse(any("PANADOL" in name for name in consolidated["item_name"]))

    def test_unknown_discount_export_fidelity(self):
        """Checks that exporting to dictionary and CSV keeps unknown discounts empty/null, never 0.0."""
        df = self.df.copy()
        
        # 1. Export to records dictionary
        records = df.to_dict(orient="records")
        # Explicit zero discount produces 0.0
        self.assertEqual(records[0]["discount_rate"], 0.0)
        # Unknown discount produces NaN / None
        self.assertTrue(
            records[2]["discount_rate"] is None or math.isnan(records[2]["discount_rate"]),
            f"Expected None or NaN, got {records[2]['discount_rate']}"
        )

        # 2. Export to CSV string
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        csv_lines = csv_buffer.getvalue().strip().split("\n")
        
        # CSV header: warehouse_name,item_name,base_price,discount_rate,stock_status
        # Line 1 (CONCOR with 0.0): discount column should have "0.0"
        self.assertIn(",0.0,", csv_lines[1])
        # Line 3 (PANADOL with unknown): discount column should be empty (",,")
        self.assertIn(",,", csv_lines[3])
        self.assertNotIn(",0.0,", csv_lines[3])

    def test_unknown_discount_in_order_allocation(self):
        """
        Checks that MedicineAllocator preserves unknown discounts in multi-warehouse comparison.
        Warehouse_Alpha has PANADOL with unknown discount (NaN).
        Warehouse_Beta has PANADOL with explicit 15% discount (0.15).
        Allocator allocates to Warehouse_Beta due to higher verifiable discount,
        and records Warehouse_Alpha's discount as [nan] (never coerced to 0.0).
        """
        wh_alpha_data = [
            {"warehouse_name": "W_Alpha", "item_name": "PANADOL EXTRA 24 TAB", "base_price": 35.0, "discount_rate": np.nan, "stock_status": True},
        ]
        wh_beta_data = [
            {"warehouse_name": "W_Beta", "item_name": "PANADOL EXTRA 24 TAB", "base_price": 35.0, "discount_rate": 0.15, "stock_status": True},
        ]
        combined_df = pd.DataFrame(wh_alpha_data + wh_beta_data)
        combined_df["normalized_name"] = combined_df["item_name"]

        allocator = MedicineAllocator(warehouse_inventory=combined_df, enable_ai=False)
        order_df = pd.DataFrame([{"requested_item": "PANADOL EXTRA 24 TAB", "quantity": 10}])
        
        alloc_res = allocator.allocate_order(order_df)
        master_df = alloc_res["master_comparison"]
        
        # Selected warehouse should be W_Beta (verifiable positive discount beats NaN)
        self.assertEqual(master_df.loc[0, "المخزن الفائز"], "W_Beta")
        
        # Check warehouse comparison discount columns
        # W_Beta should display 0.15
        self.assertEqual(master_df.loc[0, "خصم W_Beta"], 0.15)
        # W_Alpha should display nan (never 0.0)
        self.assertTrue(pd.isna(master_df.loc[0, "خصم W_Alpha"]))
        self.assertNotEqual(master_df.loc[0, "خصم W_Alpha"], 0.0)

    def test_unknown_discount_when_it_is_only_available_offer(self):
        """
        CRITICAL SAFEGUARD (Outside Search Algorithm):
        When an item has an unknown discount and is the ONLY available offer in any catalog:
        1. It must NOT be silently assumed to have zero discount (0.0).
        2. It must NOT be allocated with an unsupported net price.
        3. The safeguard in _build_consolidated_inventory excludes it from procurement inventory.
        4. When the user requests this item, MedicineAllocator routes it to out_of_stock.
        """
        # Catalog where SOLO DRUG has an unknown discount as its only listing
        solo_data = [
            {"warehouse_name": "Warehouse_Solo", "item_name": "SOLO DRUG 50 MG 30 TAB", "base_price": 80.0, "discount_rate": np.nan, "stock_status": True},
            {"warehouse_name": "Warehouse_Solo", "item_name": "OTHER DRUG 10 MG 20 TAB", "base_price": 40.0, "discount_rate": 0.10, "stock_status": True},
        ]
        solo_df = pd.DataFrame(solo_data)
        
        # 1. Pipeline consolidation excludes the unknown discount row from procurement
        consolidated = _build_consolidated_inventory([solo_df])
        self.assertEqual(len(consolidated), 1)
        self.assertEqual(consolidated.iloc[0]["item_name"], "OTHER DRUG 10 MG 20 TAB")
        
        # 2. Allocate order requesting both items
        consolidated["normalized_name"] = consolidated["item_name"]
        allocator = MedicineAllocator(warehouse_inventory=consolidated, enable_ai=False)
        order_df = pd.DataFrame([
            {"requested_item": "SOLO DRUG 50 MG 30 TAB", "quantity": 5},
            {"requested_item": "OTHER DRUG 10 MG 20 TAB", "quantity": 10},
        ])
        
        res = allocator.allocate_order(order_df)
        master = res["master_comparison"]
        oos = res["out_of_stock"]
        
        # OTHER DRUG had a verified discount and is safely allocated
        other_row = master[master["اسم الصنف المطلوب (في طلب الشراء)"] == "OTHER DRUG 10 MG 20 TAB"]
        self.assertEqual(len(other_row), 1)
        self.assertEqual(other_row["المخزن الفائز"].iloc[0], "Warehouse_Solo")
        self.assertEqual(other_row["أعلى خصم %"].iloc[0], 0.10)
        
        # SOLO DRUG had an unknown discount:
        # - Must NOT appear as an allocated order in master comparison
        solo_master = master[master["اسم الصنف المطلوب (في طلب الشراء)"] == "SOLO DRUG 50 MG 30 TAB"]
        self.assertEqual(len(solo_master), 0)
        
        # - Routed to out-of-stock without guessing or calculating unsupported net price
        self.assertFalse(oos.empty)
        solo_oos = oos[oos["اسم الصنف المطلوب"].str.contains("SOLO DRUG")]
        self.assertEqual(len(solo_oos), 1)

    def test_pipeline_distinguishes_unverified_discount_offer_from_generic_oos(self):
        """
        Verifies Directive 5:
        In the pipeline reporting layer, an item whose only catalog offer has an unverified discount
        is clearly distinguished as 'offer found, discount unverified' ('عرض متاح ولكن الخصم غير مؤكد (مستبعد للأمان)')
        rather than generic out-of-stock, while preserving the unknown-discount safeguard and 0 search changes.
        """
        import tempfile
        from src.pipeline import run_procurement_pipeline

        # Create temporary catalog Excel with an unverified discount item and a completely absent item
        cat_data = [
            {
                "اسم الصنف": "PANADOL EXTRA 24 TAB",
                "السعر": 50.0,
                "الخصم": None, # Unverified discount
            },
            {
                "اسم الصنف": "AUGMENTIN 1 GM 14 TAB",
                "السعر": 99.0,
                "الخصم": "20%",
            }
        ]
        cat_df = pd.DataFrame(cat_data)

        order_data = [
            {"اسم الصنف": "PANADOL EXTRA 24 TAB", "الكمية": 5},
            {"اسم الصنف": "CONCOR 5 MG 30 TAB", "الكمية": 2},
        ]
        order_df = pd.DataFrame(order_data)

        with tempfile.TemporaryDirectory() as tmpdir:
            cat_path = os.path.join(tmpdir, "test_cat.xlsx")
            order_path = os.path.join(tmpdir, "test_order.xlsx")
            out_dir = os.path.join(tmpdir, "output")
            os.makedirs(out_dir, exist_ok=True)

            cat_df.to_excel(cat_path, index=False)
            order_df.to_excel(order_path, index=False)

            pipe_res = run_procurement_pipeline(
                catalog_files=[cat_path],
                order_files=[order_path],
                output_dir=out_dir,
                progress_callback=lambda p, m: None,
            )

            results = pipe_res["results"]
            oos = results["out_of_stock"]
            self.assertEqual(len(oos), 2)

            unverified_row = oos[oos["اسم الصنف المطلوب"].str.contains("PANADOL")].iloc[0]
            self.assertEqual(unverified_row["حالة التوفر"], "عرض متاح ولكن الخصم غير مؤكد (مستبعد للأمان)")
            self.assertIn("نسبة الخصم غير مؤكدة", unverified_row["ملاحظات المتابعة والبحث"])

            absent_row = oos[oos["اسم الصنف المطلوب"].str.contains("CONCOR")].iloc[0]
            self.assertIn("غير متوفر", absent_row["حالة التوفر"])
            self.assertNotEqual(absent_row["حالة التوفر"], "عرض متاح ولكن الخصم غير مؤكد (مستبعد للأمان)")

            self.assertEqual(results["kpis"]["unverified_discount_items"], 1)


if __name__ == "__main__":
    unittest.main()
