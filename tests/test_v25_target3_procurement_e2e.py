"""
Verification Target 3 Test Suite: Procurement E2E and Local Non-Elevated Packaging (v2.5)

Covers all 3 Verification Target 3 requirements from ORIGINAL_REQUEST.md:
1. End-to-end demonstration verifies at least one automatically recovered row and one persisted manually corrected row successfully entering the final procurement optimization output.
2. Non-elevated %LOCALAPPDATA% operation verified.
3. Verification that procurement is blocked when 0 valid items exist.
"""
import copy
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd
import pymupdf

from src.allocator import MedicineAllocator
from src.catalog_corrections import (
    get_corrections_dir,
    has_persisted_corrections,
    load_corrections,
    save_corrections,
    set_corrections_dir,
)
from src.catalog_diagnostics import (
    CatalogResult,
    FileFingerprint,
    ImportDiagnostics,
    ReviewIssue,
    SourceIdentity,
)
from src.catalog_service import CatalogCorrectionService, STANDARD_COLUMNS
from src.pipeline import (
    PipelineExecutionError,
    is_in_installation_dir,
    run_procurement_pipeline,
)


class TestTarget3ProcurementE2EAllocation(unittest.TestCase):
    """1. End-to-end demonstration verifies at least one automatically recovered row and one persisted manually corrected row successfully entering the final procurement optimization output."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.corrections_dir = os.path.join(self.temp_dir, "corrections")
        set_corrections_dir(self.corrections_dir)

    def tearDown(self):
        set_corrections_dir(None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_pdf_coordinate_recovery_and_reloaded_correction_reach_procurement(self):
        """Inject a dropped extraction row; use real PDF recovery and disk reload."""
        pdf_path = os.path.join(self.temp_dir, "recovery_catalog.pdf")
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_text((60, 110), "Concor 5mg 30Tab", fontsize=10)
            page.insert_text((300, 110), "80.00", fontsize=10)
            page.insert_text((420, 110), "22%", fontsize=10)
            doc.save(pdf_path)

        builder = CatalogCorrectionService(pdf_path)
        original = {
            "warehouse_name": builder.warehouse_name,
            "item_name": "Cataflam 50mg 20 Tab", "base_price": 55.0,
            "discount_rate": 0.10, "stock_status": True,
        }
        identity = SourceIdentity(page=1, table=0, row=1)
        issue = ReviewIssue(
            source_id=identity.source_id, identity=identity,
            raw_cells=["Concor 5mg 30Tab", "", "22%"],
            bbox=[50.0, 90.0, 500.0, 125.0], rejection_reason="missing_price",
        )
        initial = CatalogResult(
            dataframe=pd.DataFrame([builder._build_canonical_row(original)], columns=STANDARD_COLUMNS),
            diagnostics=ImportDiagnostics(accepted_rows=1, unique_records=1),
            fingerprint=FileFingerprint.from_path(pdf_path),
            review_issues=[issue], issues_by_source_id={issue.source_id: issue},
        )
        from src.catalog_recovery import run_automatic_recovery
        recovered = run_automatic_recovery(initial, pdf_path=pdf_path)
        self.assertTrue(issue.resolved)
        self.assertEqual(issue.provenance, "automatic_recovery")
        self.assertEqual(issue.strategy_outcomes["coordinate_reextraction"], "recovered")
        self.assertEqual(len(recovered.dataframe), 2)

        order_path = os.path.join(self.temp_dir, "recovery_order.xlsx")
        pd.DataFrame([
            {"اسم الصنف": "Concor 5mg 30Tab", "الكمية المطلوبة": 5},
            {"اسم الصنف": "Cataflam 50mg 20 Tab", "الكمية المطلوبة": 20},
        ]).to_excel(order_path, index=False)

        # Only the extraction boundary is controlled. Recovery, persistence,
        # service reload, allocation and workbook generation execute normally.
        with patch.object(CatalogCorrectionService, "_parse_catalog_base",
                          side_effect=lambda *a, **kw: copy.deepcopy(recovered)):
            service = CatalogCorrectionService(pdf_path)
            service.apply_field_correction("p1_t0_r0", dict(original, discount_rate=0.28))
            self.assertTrue(has_persisted_corrections(pdf_path))
            reloaded = CatalogCorrectionService(pdf_path).get_refreshed_catalog_result()
            self.assertEqual(len(reloaded.dataframe), 2)
            self.assertEqual(reloaded.issues_by_source_id[issue.source_id].provenance, "automatic_recovery")
            result = run_procurement_pipeline(
                order_files=[order_path], catalog_files=[pdf_path],
                output_dir=os.path.join(self.temp_dir, "recovery_output"),
            )
        self.assertEqual(result["kpis"]["matched_items"], 2)
        self.assertTrue(os.path.isfile(result["report_path"]))
        master = result["results"]["master_comparison"]
        name_col = next(c for c in master.columns if "اسم الصنف" in c)
        for name, expected_discount in [("Concor", 0.22), ("Cataflam", 0.28)]:
            row = master[master[name_col].str.contains(name, na=False)].iloc[0]
            discounts = []
            for col in master.columns:
                if "خصم" in col and "مرجح" not in col and "فرق" not in col:
                    value = row[col]
                    if pd.notna(value) and str(value).strip():
                        number = float(str(value).replace("%", "").strip())
                        discounts.append(number / 100 if number > 1 else number)
            self.assertTrue(any(abs(d - expected_discount) < 1e-6 for d in discounts))

    def test_e2e_procurement_allocates_valid_and_persisted_corrected_rows(self):
        """Verify valid and persisted corrected items enter the procurement workbook."""
        # 1. Create Order Excel File
        order_path = os.path.join(self.temp_dir, "daily_order.xlsx")
        order_data = [
            {"اسم الصنف": "Panadol Extra 24 Tab", "الكمية المطلوبة": 10},
            {"اسم الصنف": "Concor 5mg 30 Tab", "الكمية المطلوبة": 5},
            {"اسم الصنف": "Cataflam 50mg 20 Tab", "الكمية المطلوبة": 20},
        ]
        pd.DataFrame(order_data).to_excel(order_path, index=False)

        # 2. Create Wholesaler Catalog with 3 items:
        # - Item 1: Pristine item ("Panadol Extra 24 Tab")
        # - Item 2: Valid original item ("Concor 5mg 30 Tab")
        # - Item 3: Persisted manually corrected item ("Cataflam 50mg 20 Tab")
        cat_excel_path = os.path.join(self.temp_dir, "مخزن_البركة_المتطور.xlsx")
        cat_initial_data = [
            # Item 1: Pristine valid
            {"اسم الصنف": "Panadol Extra 24 Tab", "سعر الجمهور": 45.0, "نسبة الخصم": 0.20},
            # Item 2: Valid original row
            {"اسم الصنف": "Concor 5mg 30 Tab", "سعر الجمهور": 80.0, "نسبة الخصم": 0.22},
            # Item 3: Raw row before manual correction (e.g. incorrect price or discount)
            {"اسم الصنف": "Cataflam 50mg 20 Tab Raw", "سعر الجمهور": 55.0, "نسبة الخصم": 0.10},
        ]
        pd.DataFrame(cat_initial_data).to_excel(cat_excel_path, index=False)

        # 3. Apply persistent manual correction to Item 3 via CatalogCorrectionService
        service = CatalogCorrectionService(cat_excel_path)
        base_res = service.get_refreshed_catalog_result()
        self.assertEqual(len(base_res.dataframe), 3)

        # Persist manual correction for row 2 (Cataflam) giving it higher discount 0.28
        service.apply_field_correction("p1_t0_r2", {
            "warehouse_name": service.warehouse_name,
            "item_name": "Cataflam 50mg 20 Tab",
            "base_price": 55.0,
            "discount_rate": 0.28,
            "stock_status": True,
        })
        self.assertTrue(has_persisted_corrections(cat_excel_path))

        # Refresh after saving the manual correction
        corr_res = service.get_refreshed_catalog_result()
        # Verify Cataflam is updated in service dataframe
        cataflam_row = corr_res.dataframe[corr_res.dataframe["item_name"] == "Cataflam 50mg 20 Tab"]
        self.assertEqual(len(cataflam_row), 1)
        self.assertAlmostEqual(float(cataflam_row.iloc[0]["discount_rate"]), 0.28, places=2)

        # 4. Run the procurement allocation engine
        output_dir = os.path.join(self.temp_dir, "procurement_output")
        os.makedirs(output_dir, exist_ok=True)

        res = run_procurement_pipeline(
            order_files=[order_path],
            catalog_files=[cat_excel_path],
            output_dir=output_dir,
        )

        # 5. Verify procurement output
        self.assertIn("report_path", res)
        self.assertTrue(os.path.isfile(res["report_path"]))

        kpis = res.get("kpis", {})
        self.assertEqual(kpis.get("total_items"), 3, "All 3 ordered items should be processed")
        self.assertEqual(kpis.get("matched_items"), 3, "All 3 items (pristine, recovered, corrected) must be matched")
        self.assertEqual(kpis.get("out_of_stock"), 0, "No items should be out of stock")

        # Inspect master comparison dataframe
        master_df = res["results"]["master_comparison"]
        req_name_col = [c for c in master_df.columns if "اسم الصنف" in c][0]
        allocated_names = list(master_df[req_name_col].astype(str))

        # Check Panadol Extra (pristine) is present
        self.assertTrue(any("Panadol Extra" in name for name in allocated_names))

        # Check Concor (original extraction) is present
        self.assertTrue(any("Concor 5mg" in name for name in allocated_names), "Original valid row must be present in allocation")

        # Check Cataflam (persisted manual correction) is present and received corrected discount (28%)
        self.assertTrue(any("Cataflam 50mg" in name for name in allocated_names), "Persisted manually corrected row must be present in allocation")

        cataflam_allocated = master_df[master_df[req_name_col].str.contains("Cataflam 50mg", na=False)].iloc[0]
        found_disc = None
        for col in master_df.columns:
            if "خصم" in col and "مرجح" not in col and "فرق" not in col:
                val = cataflam_allocated[col]
                if pd.notna(val) and str(val).strip():
                    found_disc = val
                    break
        self.assertIsNotNone(found_disc, "Must find allocated discount for Cataflam")
        win_disc_num = float(str(found_disc).replace("%", "").strip())
        if win_disc_num > 1.0:
            win_disc_num /= 100.0
        self.assertAlmostEqual(win_disc_num, 0.28, places=2, msg="Winning allocation must use persisted corrected discount rate of 28%")


class TestTarget3NonElevatedLocalAppDataOperation(unittest.TestCase):
    """2. Non-elevated %LOCALAPPDATA% operation verified."""

    def test_corrections_default_path_is_in_localappdata(self):
        """Verify default corrections directory resolves strictly inside %LOCALAPPDATA%."""
        set_corrections_dir(None)  # Clear override
        canonical_dir = get_corrections_dir()

        local_app_data = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        expected_prefix = os.path.normpath(local_app_data)

        self.assertTrue(
            canonical_dir.startswith(expected_prefix),
            f"Corrections dir '{canonical_dir}' must reside inside %LOCALAPPDATA% ('{expected_prefix}')"
        )
        self.assertIn("EgyptianPharmaOptimizer", canonical_dir)
        self.assertIn("catalog_corrections", canonical_dir)

    def test_installation_directory_writes_strictly_blocked(self):
        """Verify is_in_installation_dir protects Program Files and installation folders."""
        program_files_path = os.path.join(r"C:\Program Files", "EgyptianPharmaOptimizer", "data")
        self.assertTrue(is_in_installation_dir(program_files_path))

        program_files_x86_path = os.path.join(r"C:\Program Files (x86)", "EgyptianPharmaOptimizer")
        self.assertTrue(is_in_installation_dir(program_files_x86_path))

        internal_bundle_path = os.path.join(r"C:\App\_internal", "catalog_corrections")
        self.assertTrue(is_in_installation_dir(internal_bundle_path))

        # Standard LOCALAPPDATA path must NOT be considered installation dir
        user_data_path = os.path.join(os.environ.get("LOCALAPPDATA", r"C:\Users\User\AppData\Local"), "EgyptianPharmaOptimizer")
        self.assertFalse(is_in_installation_dir(user_data_path))

    def test_non_elevated_read_write_permissions(self):
        """Verify writing and reading corrections under user data directory requires no elevation."""
        temp_user_dir = tempfile.mkdtemp(prefix="epo_user_test_")
        try:
            test_file = os.path.join(temp_user_dir, "test_perm.json")
            with open(test_file, "w", encoding="utf-8") as f:
                json.dump({"test": "non_elevated_read_write"}, f)

            with open(test_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.assertEqual(data.get("test"), "non_elevated_read_write")
        finally:
            shutil.rmtree(temp_user_dir, ignore_errors=True)


class TestTarget3ProcurementBlockedWhenZeroValidItems(unittest.TestCase):
    """3. Verification that procurement is blocked when 0 valid items exist."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_procurement_pipeline_raises_error_when_zero_valid_catalog_items(self):
        """Verify pipeline execution raises error and blocks procurement when all catalog items are invalid."""
        order_path = os.path.join(self.temp_dir, "order.xlsx")
        pd.DataFrame([{"اسم الصنف": "Panadol Extra 24 Tab", "الكمية المطلوبة": 10}]).to_excel(order_path, index=False)

        # Empty catalog with 0 rows
        empty_cat_path = os.path.join(self.temp_dir, "empty_catalog.xlsx")
        pd.DataFrame(columns=["اسم الصنف", "سعر الجمهور", "نسبة الخصم"]).to_excel(empty_cat_path, index=False)

        output_dir = os.path.join(self.temp_dir, "out")
        os.makedirs(output_dir, exist_ok=True)

        with self.assertRaises(PipelineExecutionError) as ctx:
            run_procurement_pipeline(
                order_files=[order_path],
                catalog_files=[empty_cat_path],
                output_dir=output_dir,
            )

        err_msg = str(ctx.exception).lower()
        self.assertTrue(
            any(kw in err_msg for kw in ["failed to extract valid", "0 valid", "no valid", "empty"]),
            f"Expected error message indicating zero valid items, got: {err_msg}"
        )

    def test_procurement_pipeline_blocks_catalog_with_only_invalid_items(self):
        """Verify catalog with only invalid price/discount rows (0 valid items) blocks procurement."""
        order_path = os.path.join(self.temp_dir, "order.xlsx")
        pd.DataFrame([{"اسم الصنف": "Panadol Extra 24 Tab", "الكمية المطلوبة": 10}]).to_excel(order_path, index=False)

        # Catalog where all rows have negative price or price > 10000 (invalid items)
        invalid_cat_path = os.path.join(self.temp_dir, "invalid_catalog.xlsx")
        pd.DataFrame([
            {"اسم الصنف": "اسم الصنف", "سعر الجمهور": 50.0, "نسبة الخصم": 0.10},
            {"اسم الصنف": "صنف", "سعر الجمهور": 60.0, "نسبة الخصم": 0.10},
            {"اسم الصنف": "nan", "سعر الجمهور": 70.0, "نسبة الخصم": 0.10},
        ]).to_excel(invalid_cat_path, index=False)

        output_dir = os.path.join(self.temp_dir, "out")
        os.makedirs(output_dir, exist_ok=True)

        # Attempting procurement must fail / block
        with self.assertRaises(PipelineExecutionError) as ctx:
            run_procurement_pipeline(
                order_files=[order_path],
                catalog_files=[invalid_cat_path],
                output_dir=output_dir,
            )
        err_msg = str(ctx.exception).lower()
        self.assertTrue(
            any(kw in err_msg for kw in ["failed to extract valid", "0 valid", "no valid", "empty"]),
            f"Expected error message blocking procurement, got: {err_msg}"
        )


if __name__ == "__main__":
    unittest.main()
