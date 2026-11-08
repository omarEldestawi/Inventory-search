# -*- coding: utf-8 -*-
"""
Empirical verification suite by challenger_m1_iter2_1.
Focus:
  1. Success path: diagnostics["order_exclusions_count"] and diagnostics["order_exclusions"] presence & accuracy.
  2. Failure path 1: all-excluded order raises PipelineExecutionError with populated diagnostics.
  3. Failure path 2: downstream failure after order ingestion preserves diagnostics with order exclusions.
  4. Multiple order files: aggregation of exclusions across files.
  5. Zero-exclusion order: diagnostics count is 0 and list is empty.
  6. Zero-leakage verification: buying_list, out_of_stock, and generated Excel report workbook (all sheets/cells).
  7. Legitimate drug name preservation: ensure false positives are not excluded.
"""
import os
import tempfile
import pytest
import openpyxl
import pandas as pd
from unittest.mock import patch

from src.order_parser import is_old_price_item
from src.pipeline import (
    parse_excel_catalog,
    run_procurement_pipeline,
    PipelineExecutionError,
)


def _create_simple_catalog(path: str, items: list):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Catalog"
    ws.append(["اسم الصنف", "الخصم", "سعر الجمهور"])
    for name, disc, price in items:
        ws.append([name, disc, price])
    wb.save(path)


def _create_simple_order(path: str, items: list):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Order"
    ws.append(["اسم الصنف", "الكمية المطلوبة"])
    for name, qty in items:
        ws.append([name, qty])
    wb.save(path)


class TestEmpiricalProcurementPipelineDiagnostics:
    """Rigorous empirical tests for diagnostics and exclusion isolation in run_procurement_pipeline."""

    def test_success_path_diagnostics_and_isolation(self, tmp_path):
        """Verify success path returns diagnostics with exact exclusion accounting and no leakage."""
        cat_file = str(tmp_path / "cat1.xlsx")
        _create_simple_catalog(cat_file, [
            ("بانادول اكسترا 24 قرص", "20%", 50.0),
            ("كونكور 5 مجم 30 قرص", "15%", 40.0),
        ])

        ord_file = str(tmp_path / "ord1.xlsx")
        _create_simple_order(ord_file, [
            ("بانادول اكسترا 24 قرص", 10),      # eligible matched
            ("كونكور 5 مجم 30 قرص", 5),         # eligible matched
            ("دواء غير متوفر 10 مجم", 3),       # eligible unmatched -> out of stock
            ("كتافلام 50 مجم س ق", 2),          # excluded old-price
            ("اسبرين 100 مجم ق.س", 4),          # excluded old-price
            ("فيتافيرول كبسول س ق\u200e", 1),    # excluded old-price with directional mark
            ("س ج بلس اقراص", 7),               # legitimate drug name containing 'س ج' and 'اقراص'
        ])

        out_dir = str(tmp_path / "out_success")
        os.makedirs(out_dir, exist_ok=True)

        res = run_procurement_pipeline(
            order_files=[ord_file],
            catalog_files=[cat_file],
            output_dir=out_dir,
            custom_date_str="2026-11-07",
        )

        assert isinstance(res, dict), "run_procurement_pipeline must return a dict"
        assert "diagnostics" in res, "Return dict must contain 'diagnostics'"
        diag = res["diagnostics"]
        assert isinstance(diag, dict)

        # 1. Verification of diagnostics keys & values
        assert diag.get("order_exclusions_count") == 3, f"Expected 3 exclusions, got {diag.get('order_exclusions_count')}"
        exclusions = diag.get("order_exclusions", [])
        assert len(exclusions) == 3, f"Expected 3 exclusions in list, got {len(exclusions)}"

        excluded_names = {e["raw_name"] for e in exclusions}
        expected_excluded = {
            "كتافلام 50 مجم س ق",
            "اسبرين 100 مجم ق.س",
            "فيتافيرول كبسول س ق\u200e",
        }
        assert excluded_names == expected_excluded, f"Excluded names mismatch: {excluded_names} vs {expected_excluded}"

        for e in exclusions:
            assert e["reason"] == "old_price_suffix"
            assert e["sheet_name"] == "Order"
            assert e["quantity"] in [1, 2, 4]
            assert e["row_index"] >= 2

        # 2. Legitimate drug name must NOT be excluded
        assert "س ج بلس اقراص" not in excluded_names

        # 3. Verify zero-leakage into allocated results (master_comparison and allocated_orders)
        results = res.get("results", {})
        master_comp = results.get("master_comparison")
        if master_comp is not None and not master_comp.empty:
            for col in master_comp.columns:
                col_vals = master_comp[col].astype(str)
                for ex in expected_excluded:
                    assert not any(ex in val for val in col_vals), f"LEAK: Excluded item '{ex}' found in master_comparison column '{col}'"

        allocated_orders = results.get("allocated_orders", {})
        for wh, wh_df in allocated_orders.items():
            for col in wh_df.columns:
                col_vals = wh_df[col].astype(str)
                for ex in expected_excluded:
                    assert not any(ex in val for val in col_vals), f"LEAK: Excluded item '{ex}' found in allocated_orders[{wh}] column '{col}'"

        # 4. Verify zero-leakage into out_of_stock
        oos = results.get("out_of_stock")
        if oos is not None and not oos.empty:
            oos_items = set(oos["اسم الصنف المطلوب"].astype(str))
            for ex in expected_excluded:
                assert ex not in oos_items, f"LEAK: Excluded item '{ex}' found in out_of_stock"
            # Unmatched items should be here
            assert any("دواء غير متوفر 10 مجم" in item for item in oos_items)
            assert any("س ج بلس اقراص" in item for item in oos_items)

        # 5. Verify zero-leakage into generated Excel workbook across all sheets
        report_path = res["report_path"]
        assert os.path.isfile(report_path)
        wb = openpyxl.load_workbook(report_path, data_only=True)
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            for row in ws.iter_rows(values_only=True):
                for cell in row:
                    if cell is not None:
                        cell_str = str(cell).strip()
                        for ex in expected_excluded:
                            assert ex not in cell_str, (
                                f"LEAK DETECTED in report sheet '{sheet_name}': cell '{cell_str}' contains '{ex}'"
                            )

    def test_failure_all_excluded_order_populates_diagnostics(self, tmp_path):
        """Verify that when all items in an order are excluded, PipelineExecutionError has populated diagnostics."""
        cat_file = str(tmp_path / "cat_dummy.xlsx")
        _create_simple_catalog(cat_file, [
            ("بانادول اكسترا 24 قرص", "20%", 50.0),
        ])

        ord_file = str(tmp_path / "ord_all_old.xlsx")
        _create_simple_order(ord_file, [
            ("اماريل 2 مجم س ق", 5),
            ("فوليك اسيد 20 قرص ق س", 10),
            ("كتافلام 50 مجم س.ق", 3),
        ])

        out_dir = str(tmp_path / "out_fail_all")
        os.makedirs(out_dir, exist_ok=True)

        with pytest.raises(PipelineExecutionError) as exc_info:
            run_procurement_pipeline(
                order_files=[ord_file],
                catalog_files=[cat_file],
                output_dir=out_dir,
            )

        err = exc_info.value
        assert hasattr(err, "diagnostics"), "PipelineExecutionError must possess a 'diagnostics' attribute"
        diag = err.diagnostics
        assert isinstance(diag, dict), "err.diagnostics must be a dict"

        assert diag.get("outcome") == "all_items_excluded"
        assert diag.get("order_exclusions_count") == 3
        exclusions = diag.get("order_exclusions", [])
        assert len(exclusions) == 3

        excluded_names = {e["raw_name"] for e in exclusions}
        assert excluded_names == {
            "اماريل 2 مجم س ق",
            "فوليك اسيد 20 قرص ق س",
            "كتافلام 50 مجم س.ق",
        }

    def test_multiple_order_files_aggregate_diagnostics(self, tmp_path):
        """Verify that multiple order files aggregate exclusions correctly."""
        cat_file = str(tmp_path / "cat_multi.xlsx")
        _create_simple_catalog(cat_file, [
            ("بانادول 24 قرص", "20%", 30.0),
        ])

        ord1 = str(tmp_path / "ord1.xlsx")
        _create_simple_order(ord1, [
            ("بانادول 24 قرص", 5),
            ("صنف قديم 1 س ق", 2),
        ])

        ord2 = str(tmp_path / "ord2.xlsx")
        _create_simple_order(ord2, [
            ("بانادول 24 قرص", 3),
            ("صنف قديم 2 ق س", 4),
            ("صنف قديم 3 س.ق", 6),
        ])

        out_dir = str(tmp_path / "out_multi")
        os.makedirs(out_dir, exist_ok=True)

        res = run_procurement_pipeline(
            order_files=[ord1, ord2],
            catalog_files=[cat_file],
            output_dir=out_dir,
        )

        diag = res["diagnostics"]
        assert diag.get("order_exclusions_count") == 3
        exclusions = diag.get("order_exclusions", [])
        assert len(exclusions) == 3

        sources = {os.path.basename(e["source_file"]) for e in exclusions}
        assert sources == {"ord1.xlsx", "ord2.xlsx"}

        total_ex_qty = sum(e["quantity"] for e in exclusions)
        assert total_ex_qty == 12.0  # 2 + 4 + 6

    def test_zero_exclusions_order(self, tmp_path):
        """Verify that an order with 0 old-price items accurately has count 0 and empty list."""
        cat_file = str(tmp_path / "cat_clean.xlsx")
        _create_simple_catalog(cat_file, [
            ("بانادول 24 قرص", "20%", 30.0),
        ])

        ord_clean = str(tmp_path / "ord_clean.xlsx")
        _create_simple_order(ord_clean, [
            ("بانادول 24 قرص", 5),
        ])

        out_dir = str(tmp_path / "out_clean")
        os.makedirs(out_dir, exist_ok=True)

        res = run_procurement_pipeline(
            order_files=[ord_clean],
            catalog_files=[cat_file],
            output_dir=out_dir,
        )

        diag = res["diagnostics"]
        assert diag.get("order_exclusions_count") == 0
        assert diag.get("order_exclusions") == []

    def test_failure_downstream_preserves_order_exclusions_in_diagnostics(self, tmp_path):
        """
        Verify that if an error occurs AFTER order ingestion (e.g. in allocation or report generation),
        the raised PipelineExecutionError preserves order_exclusions_count and order_exclusions.
        """
        cat_file = str(tmp_path / "cat_downstream.xlsx")
        _create_simple_catalog(cat_file, [
            ("بانادول 24 قرص", "20%", 30.0),
        ])

        ord_file = str(tmp_path / "ord_downstream.xlsx")
        _create_simple_order(ord_file, [
            ("بانادول 24 قرص", 5),
            ("صنف ملغي قديم س ق", 2),
        ])

        out_dir = str(tmp_path / "out_downstream")
        os.makedirs(out_dir, exist_ok=True)

        # Mock report generator to simulate unexpected failure in report generation stage
        with patch("src.pipeline.ArabicExcelReportGenerator.generate", side_effect=RuntimeError("Simulated Report Failure")):
            with pytest.raises(PipelineExecutionError) as exc_info:
                run_procurement_pipeline(
                    order_files=[ord_file],
                    catalog_files=[cat_file],
                    output_dir=out_dir,
                )

        err = exc_info.value
        assert hasattr(err, "diagnostics")
        diag = err.diagnostics
        assert diag.get("order_exclusions_count") == 1
        assert len(diag.get("order_exclusions", [])) == 1
        assert diag["order_exclusions"][0]["raw_name"] == "صنف ملغي قديم س ق"
        assert diag.get("stage") == "report_generation"
