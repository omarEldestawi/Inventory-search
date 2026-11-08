# -*- coding: utf-8 -*-
"""
Empirical Verification & Stress Test Suite for Milestone 1 (Features F01-F16).
Author: challenger_m1_o3_2
Focus:
  1. Catalog Ingestion Stress (old-price exclusion, alignment artifacts, all-old-price empty schema)
  2. Procurement Pipeline Isolation (all-old-price order rejection, mixed-order report & OOS isolation)
  3. Reference Dataset Schema Stress (small file loading, missing columns, invalid rate bounds)
"""
import os
import shutil
import tempfile
import pytest
import openpyxl
import pandas as pd
import numpy as np

from src.order_parser import is_old_price_item, ExcludedItem
from src.excel_parser import load_purchase_order
from src.pipeline import (
    parse_excel_catalog,
    run_procurement_pipeline,
    PipelineExecutionError,
    ArabicExcelReportGenerator,
)
from src.average_discounts import (
    load_average_discounts_file,
    _normalize_discount_rate,
)


# ============================================================================
# Task 1: Catalog Ingestion Stress
# ============================================================================

class TestCatalogIngestionStress:
    """Stress tests parse_excel_catalog with corrupted rows, old-price rows, and alignment invariants."""

    def test_parse_excel_catalog_stress_mixed_and_corrupted(self, tmp_path):
        """
        Verify that in a catalog with clean, old-price, and corrupted rows:
        1. All old-price rows are completely excluded.
        2. Corrupted / header / empty rows are cleanly handled.
        3. Clean valid rows are extracted.
        4. No NaN alignment artifacts exist in any column (specifically warehouse_name and base_price).
        """
        cat_file = str(tmp_path / "mixed_catalog.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "SupplierCatalog"

        # Headers
        ws.append(["اسم الصنف", "الخصم", "سعر الجمهور"])

        # Clean rows
        ws.append(["بانادول اكسترا 24 قرص", "25%", 45.0])
        ws.append(["كونكور 5 مجم 30 قرص", "20%", 60.0])
        ws.append(["اماريل 2 مجم 30 قرص", "15%", 30.0])

        # Old-price rows (various suffixes and encodings)
        ws.append(["فوليك اسيد 20 قرص س ق", "30%", 20.0])
        ws.append(["كتافلام 50 مجم ق س", "20%", 50.0])
        ws.append(["اسبرين بروتكت س.ق", "10%", 15.0])
        ws.append(["بانادول 24 قرص س ق\ufeff", "25%", 40.0])
        ws.append(["كونكور 10 مجم س ق\u200e", "20%", 70.0])

        # Corrupted / noisy rows
        ws.append([None, "10%", 10.0])                 # Null name
        ws.append(["", "10%", 10.0])                   # Empty string
        ws.append(["a", "10%", 10.0])                  # Length <= 1
        ws.append(["صنف", "10%", 10.0])                # Header keyword noise
        ws.append(["nan", "10%", 10.0])                # String NaN
        ws.append(["اوجمانتين 1 جم 14 قرص", "bad_disc", "not_a_price"])  # Corrupted values

        wb.save(cat_file)

        target_warehouse = "مخزن النور للادوية"
        df_clean = parse_excel_catalog(cat_file, warehouse_name=target_warehouse)

        # 1. Old price exclusion check
        for name in df_clean["item_name"]:
            assert not is_old_price_item(name), f"Old-price item leaked into catalog: {name}"

        # 2. Corrupted rows exclusion check
        raw_names = set(df_clean["item_name"])
        assert "" not in raw_names
        assert "a" not in raw_names
        assert "صنف" not in raw_names
        assert "nan" not in raw_names

        # 3. Clean rows presence
        assert "بانادول اكسترا 24 قرص" in raw_names
        assert "كونكور 5 مجم 30 قرص" in raw_names
        assert "اماريل 2 مجم 30 قرص" in raw_names
        # Row with corrupted discount/price is kept if name is valid, but base_price coerced to 0.0 and discount NaN
        assert "اوجمانتين 1 جم 14 قرص" in raw_names
        aug_row = df_clean[df_clean["item_name"] == "اوجمانتين 1 جم 14 قرص"].iloc[0]
        assert aug_row["base_price"] == 0.0
        assert pd.isna(aug_row["discount_rate"])

        # 4. Zero NaN alignment artifacts in warehouse_name and base_price
        assert not df_clean["warehouse_name"].isna().any(), "Found NaN in warehouse_name column!"
        assert (df_clean["warehouse_name"] == target_warehouse).all(), "Warehouse name mismatch!"
        assert not df_clean["base_price"].isna().any(), "Found NaN in base_price column!"
        assert len(df_clean) == 4

    def test_parse_excel_catalog_index_alignment_invariants(self, tmp_path):
        """
        Verify that when rows at arbitrary non-contiguous positions are excluded,
        the internal .reset_index(drop=True) guarantees 100% index alignment
        between Series assignments and clean_df.
        """
        cat_file = str(tmp_path / "interleaved_catalog.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Catalog"
        ws.append(["اسم الصنف", "الخصم", "سعر الجمهور"])

        # Interleave old-price and valid rows
        for i in range(20):
            if i % 2 == 0:
                ws.append([f"صنف تجريبي {i} س ق", "20%", 100.0 + i])
            else:
                ws.append([f"صنف صالح {i}", f"{10 + i}%", 50.0 + i])

        wb.save(cat_file)

        df = parse_excel_catalog(cat_file, warehouse_name="مخزن المحاذاة")

        # Must have exactly 10 valid rows
        assert len(df) == 10
        # Indices must be strictly 0..9 without gaps
        assert list(df.index) == list(range(10))
        # Every warehouse_name must be populated and non-null
        assert (df["warehouse_name"] == "مخزن المحاذاة").all()
        # Ensure prices align correctly with items (e.g. i=1 -> 51.0, i=3 -> 53.0 ...)
        for _, row in df.iterrows():
            item_num = int(row["item_name"].split()[-1])
            expected_price = 50.0 + item_num
            assert row["base_price"] == expected_price, f"Misaligned price for {row['item_name']}"

    def test_parse_excel_catalog_all_old_price_returns_empty_schema(self, tmp_path):
        """
        Verify an all-old-price catalog returns empty standard schema without crashing or raising.
        """
        cat_file = str(tmp_path / "all_old_price_catalog.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Catalog"
        ws.append(["اسم الصنف", "الخصم", "سعر الجمهور"])
        ws.append(["بانادول س ق", "20%", 40.0])
        ws.append(["كونكور س.ق", "15%", 50.0])
        ws.append(["كتافلام ق س", "10%", 30.0])
        ws.append(["فوليك اسيد ق.س", "30%", 20.0])
        wb.save(cat_file)

        df = parse_excel_catalog(cat_file, warehouse_name="مخزن مستبعد بالكامل")

        assert df.empty, "Expected empty DataFrame for all-old-price catalog"
        expected_columns = [
            'warehouse_name', 'item_name', 'normalized_name',
            'dosage', 'unit_size', 'base_price', 'discount_rate', 'stock_status'
        ]
        assert list(df.columns) == expected_columns, f"Expected standard catalog schema, got {list(df.columns)}"


# ============================================================================
# Task 2: Procurement Pipeline Isolation
# ============================================================================

class TestProcurementPipelineIsolation:
    """Stress tests run_procurement_pipeline with all-old-price orders and mixed orders."""

    def test_all_old_price_order_raises_pipeline_execution_error_cleanly(self, tmp_path):
        """
        Verify that an order file containing exclusively old-price items:
        1. Raises PipelineExecutionError.
        2. Contains diagnostics['outcome'] == 'all_items_excluded'.
        3. Accurately reports diagnostics['order_exclusions_count'].
        4. Does NOT report false procurement success.
        """
        order_file = str(tmp_path / "order_all_old_price.xlsx")
        wb_o = openpyxl.Workbook()
        ws_o = wb_o.active
        ws_o.title = "Order"
        ws_o.append(["اسم الصنف", "الكمية المطلوبة"])
        ws_o.append(["بانادول اكسترا 24 قرص س ق", 15])
        ws_o.append(["كونكور 5 مجم 30 قرص س.ق", 10])
        ws_o.append(["كتافلام 50 مجم ق س", 20])
        wb_o.save(order_file)

        # Active catalog with valid inventory
        cat_file = str(tmp_path / "active_catalog.xlsx")
        wb_c = openpyxl.Workbook()
        ws_c = wb_c.active
        ws_c.title = "Catalog"
        ws_c.append(["اسم الصنف", "الخصم", "سعر الجمهور"])
        ws_c.append(["بانادول اكسترا 24 قرص", "25%", 45.0])
        ws_c.append(["كونكور 5 مجم 30 قرص", "20%", 60.0])
        wb_c.save(cat_file)

        out_dir = str(tmp_path / "procurement_out")
        os.makedirs(out_dir, exist_ok=True)

        with pytest.raises(PipelineExecutionError) as exc_info:
            run_procurement_pipeline(
                order_files=[order_file],
                catalog_files=[cat_file],
                output_dir=out_dir,
            )

        err = exc_info.value
        assert err.diagnostics is not None
        assert err.diagnostics.get("outcome") == "all_items_excluded"
        assert err.diagnostics.get("order_exclusions_count") == 3
        assert len(err.diagnostics.get("order_exclusions", [])) == 3
        # Ensure error message clearly states intentional exclusion
        err_msg = str(err).lower()
        assert "all 3 item(s)" in err_msg or "intentionally excluded" in err_msg
        # Ensure no output report was generated
        assert len(os.listdir(out_dir)) == 0

    def test_mixed_order_isolation_from_reports_and_out_of_stock(self, tmp_path):
        """
        Verify that in a mixed order (eligible items + old-price items):
        1. Pipeline executes successfully to completion.
        2. Eligible items in stock are allocated.
        3. Eligible items NOT in stock appear in out_of_stock ('الأصناف غير المتوفرة (نواقص)').
        4. Excluded old-price items NEVER appear in ANY sheet of the generated Excel report.
        5. Excluded old-price items NEVER appear in out_of_stock.
        """
        order_file = str(tmp_path / "order_mixed.xlsx")
        wb_o = openpyxl.Workbook()
        ws_o = wb_o.active
        ws_o.title = "Order"
        ws_o.append(["اسم الصنف", "الكمية المطلوبة"])
        # Eligible items:
        # Item 1: In stock in catalog
        ws_o.append(["بانادول اكسترا 24 قرص", 10])
        # Item 2: NOT in stock in catalog (should become out_of_stock)
        ws_o.append(["دواء نادر غير متوفر 100 مجم", 5])
        # Old-price excluded items:
        ws_o.append(["كتافلام 50 مجم س ق", 25])
        ws_o.append(["اسبرين بروتكت 100 مجم ق س", 40])
        wb_o.save(order_file)

        # Active catalog containing Item 1 and a catalog-side old-price row
        cat_file = str(tmp_path / "supplier_catalog.xlsx")
        wb_c = openpyxl.Workbook()
        ws_c = wb_c.active
        ws_c.title = "Catalog"
        ws_c.append(["اسم الصنف", "الخصم", "سعر الجمهور"])
        ws_c.append(["بانادول اكسترا 24 قرص", "25%", 45.0])
        ws_c.append(["كتافلام 50 مجم س ق", "30%", 50.0])  # Catalog-side old price
        wb_c.save(cat_file)

        out_dir = str(tmp_path / "procurement_out_mixed")
        os.makedirs(out_dir, exist_ok=True)

        res = run_procurement_pipeline(
            order_files=[order_file],
            catalog_files=[cat_file],
            output_dir=out_dir,
            custom_date_str="2026-11-07",
        )

        assert res is not None
        assert "report_path" in res
        report_path = res["report_path"]
        assert os.path.isfile(report_path), f"Report not generated: {report_path}"

        # Inspect generated Excel workbook across ALL sheets
        wb_rep = openpyxl.load_workbook(report_path, data_only=True)
        sheet_names = wb_rep.sheetnames

        excluded_names = ["كتافلام 50 مجم س ق", "اسبرين بروتكت 100 مجم ق س"]

        for sname in sheet_names:
            ws = wb_rep[sname]
            for row in ws.iter_rows(values_only=True):
                for cell in row:
                    if cell is not None:
                        cell_str = str(cell).strip()
                        for ex_name in excluded_names:
                            assert ex_name not in cell_str, (
                                f"LEAK DETECTED: Excluded item '{ex_name}' found in sheet '{sname}' cell '{cell_str}'"
                            )

        # Inspect out_of_stock specifically
        results = res.get("results", {})
        oos_df = results.get("out_of_stock")
        if isinstance(oos_df, pd.DataFrame) and not oos_df.empty:
            oos_items = list(oos_df["اسم الصنف المطلوب"].astype(str))
            # Genuinely missing item MUST be present
            assert any("دواء نادر غير متوفر" in item for item in oos_items)
            # Excluded items MUST NOT be present
            for item in oos_items:
                for ex_name in excluded_names:
                    assert ex_name not in item, f"LEAK DETECTED: Excluded item '{ex_name}' found in out_of_stock DataFrame"

        # Check diagnostics
        diag = res.get("diagnostics", {})
        assert diag.get("order_exclusions_count") == 2
        assert len(diag.get("order_exclusions", [])) == 2

        # Verify exclusions directly via load_purchase_order
        df_ord, exclusions = load_purchase_order(order_file, return_exclusions=True)
        assert len(exclusions) == 2
        assert {e.raw_name for e in exclusions} == set(excluded_names)


# ============================================================================
# Task 3: Reference Dataset Schema Stress
# ============================================================================

class TestReferenceDatasetSchemaStress:
    """Stress tests load_average_discounts_file with small valid files, missing columns, and bounds."""

    def test_small_valid_excel_3_rows_named_average_discounts_loads_cleanly(self, tmp_path):
        """
        Verify that a small valid Excel file (3 rows) named 'average_discounts.xlsx':
        1. Loads cleanly without AssertionError (proving >2100 assertion is permanently removed).
        2. Retains valid rows.
        3. Returns expected schema ['raw_name', 'clean_name', 'avg_discount_rate'].
        """
        ref_path = str(tmp_path / "average_discounts.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Discounts"
        ws.append(["اسم الصنف", "خصم مرجح"])
        ws.append(["بانادول اكسترا 24 قرص", "25%"])
        ws.append(["كونكور 5 مجم 30 قرص", "20%"])
        ws.append(["اماريل 2 مجم 30 قرص", "15%"])
        wb.save(ref_path)

        df = load_average_discounts_file(ref_path)
        assert len(df) == 3
        assert list(df.columns) == ["raw_name", "clean_name", "avg_discount_rate"]
        assert (df["avg_discount_rate"] >= 0.0).all()
        assert (df["avg_discount_rate"] <= 1.0).all()

    def test_missing_required_columns_raises_value_error(self, tmp_path):
        """
        Verify that missing required columns raises ValueError for both Excel and CSV.
        """
        # 1. Excel missing discount column
        ref_excel_no_disc = str(tmp_path / "missing_disc.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["اسم الصنف", "سعر الجمهور"])
        ws.append(["بانادول", 50.0])
        wb.save(ref_excel_no_disc)

        with pytest.raises(ValueError, match="Could not locate"):
            load_average_discounts_file(ref_excel_no_disc)

        # 2. Excel missing name column
        ref_excel_no_name = str(tmp_path / "missing_name.xlsx")
        wb2 = openpyxl.Workbook()
        ws2 = wb2.active
        ws2.append(["خصم مرجح", "سعر الجمهور"])
        ws2.append(["25%", 50.0])
        wb2.save(ref_excel_no_name)

        with pytest.raises(ValueError, match="Could not locate"):
            load_average_discounts_file(ref_excel_no_name)

        # 3. CSV missing discount column
        ref_csv_no_disc = str(tmp_path / "missing_disc.csv")
        with open(ref_csv_no_disc, "w", encoding="utf-8") as f:
            f.write("اسم الصنف,سعر الجمهور\nبانادول,50.0\n")

        with pytest.raises(ValueError, match="Could not locate"):
            load_average_discounts_file(ref_csv_no_disc)

    def test_schema_and_rate_bounds_validation_on_dataframe(self, monkeypatch, tmp_path):
        """
        Verify that the schema validation block in load_average_discounts_file (lines 367-387)
        rigorously validates clean_name, missing columns, and discount bounds:
        - Missing raw_name -> ValueError
        - Missing clean_name or avg_discount_rate -> KeyError (due to sort_values preceding schema check)
        - Empty clean_name -> ValueError
        - Non-numeric discount rates -> ValueError
        - Discount rates < 0.0 or > 1.0 -> ValueError
        """
        dummy_file = str(tmp_path / "dummy.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["اسم الصنف", "خصم مرجح"])
        ws.append(["بانادول", "20%"])
        wb.save(dummy_file)

        # Test A: Parser returns DataFrame missing raw_name column -> raises ValueError
        def mock_load_missing_raw_name(path):
            return pd.DataFrame([{"clean_name": "بانادول", "avg_discount_rate": 0.20}])
        monkeypatch.setattr("src.average_discounts._load_excel_discounts", mock_load_missing_raw_name)
        with pytest.raises(ValueError, match="missing required columns"):
            load_average_discounts_file(dummy_file)

        # Test B: Parser returns DataFrame missing clean_name -> KeyError at sort_values
        def mock_load_missing_clean_name(path):
            return pd.DataFrame([{"raw_name": "بانادول", "avg_discount_rate": 0.20}])
        monkeypatch.setattr("src.average_discounts._load_excel_discounts", mock_load_missing_clean_name)
        with pytest.raises((KeyError, ValueError)):
            load_average_discounts_file(dummy_file)

        # Test C: Parser returns DataFrame missing avg_discount_rate -> KeyError at sort_values
        def mock_load_missing_rate(path):
            return pd.DataFrame([{"raw_name": "بانادول", "clean_name": "بانادول"}])
        monkeypatch.setattr("src.average_discounts._load_excel_discounts", mock_load_missing_rate)
        with pytest.raises((KeyError, ValueError)):
            load_average_discounts_file(dummy_file)

        # Test D: Parser returns DataFrame with empty clean_name -> ValueError
        def mock_load_empty_clean_name(path):
            return pd.DataFrame([{"raw_name": "بانادول", "clean_name": "", "avg_discount_rate": 0.20}])
        monkeypatch.setattr("src.average_discounts._load_excel_discounts", mock_load_empty_clean_name)
        with pytest.raises(ValueError, match="records with empty clean_name"):
            load_average_discounts_file(dummy_file)

        # Test E: Parser returns DataFrame with non-numeric discount rate -> ValueError
        def mock_load_non_numeric_rate(path):
            return pd.DataFrame([{"raw_name": "بانادول", "clean_name": "بانادول", "avg_discount_rate": "invalid_rate"}])
        monkeypatch.setattr("src.average_discounts._load_excel_discounts", mock_load_non_numeric_rate)
        with pytest.raises(ValueError, match="invalid \\(non-numeric\\) discount rates"):
            load_average_discounts_file(dummy_file)

        # Test F: Parser returns DataFrame with negative discount rate (< 0.0) -> ValueError
        def mock_load_negative_rate(path):
            return pd.DataFrame([{"raw_name": "بانادول", "clean_name": "بانادول", "avg_discount_rate": -0.15}])
        monkeypatch.setattr("src.average_discounts._load_excel_discounts", mock_load_negative_rate)
        with pytest.raises(ValueError, match="discount rates outside \\[0.0, 1.0\\]"):
            load_average_discounts_file(dummy_file)

        # Test G: Parser returns DataFrame with discount rate > 1.0 -> ValueError
        def mock_load_overflow_rate(path):
            return pd.DataFrame([{"raw_name": "بانادول", "clean_name": "بانادول", "avg_discount_rate": 1.25}])
        monkeypatch.setattr("src.average_discounts._load_excel_discounts", mock_load_overflow_rate)
        with pytest.raises(ValueError, match="discount rates outside \\[0.0, 1.0\\]"):
            load_average_discounts_file(dummy_file)

    def test_file_level_discount_normalization_behavior(self, tmp_path):
        """
        Document empirical file-level parser behavior:
        _normalize_discount_rate clamps numeric values into [0.0, 1.0] and skips unparseable strings.
        Therefore, an Excel file with negative discount (-15%) gets clamped to 0.0, and an Excel file
        with all unparseable strings returns an empty DataFrame.
        """
        # Excel with negative numeric discount
        neg_file = str(tmp_path / "negative_disc.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["اسم الصنف", "خصم مرجح"])
        ws.append(["بانادول", -0.15])
        wb.save(neg_file)

        df_neg = load_average_discounts_file(neg_file)
        # Clamped to 0.0 by _normalize_discount_rate
        assert len(df_neg) == 1
        assert df_neg.iloc[0]["avg_discount_rate"] == 0.0

        # Excel with completely unparseable discount string
        bad_file = str(tmp_path / "unparseable_disc.xlsx")
        wb2 = openpyxl.Workbook()
        ws2 = wb2.active
        ws2.append(["اسم الصنف", "خصم مرجح"])
        ws2.append(["بانادول", "unparseable_text"])
        wb2.save(bad_file)

        df_bad = load_average_discounts_file(bad_file)
        assert df_bad.empty
        assert list(df_bad.columns) == ["raw_name", "clean_name", "avg_discount_rate"]
