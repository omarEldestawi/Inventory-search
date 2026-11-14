# -*- coding: utf-8 -*-
"""
Milestone 1 Test Suite: Protected Baseline & Old-Price Ingestion Policy (Features F01-F16).
Tests canonical predicate, exclusion accounting, early raw evaluation, catalog filtering,
reference validation bounds, and procurement pipeline isolation.
"""
import os
import tempfile
import pytest
import pandas as pd
import openpyxl

from src.order_parser import is_old_price_item, ExcludedItem, parse_order_file
from src.excel_parser import load_purchase_order, clean_state_suffix
from src.average_discounts import load_average_discounts_file
from src.catalog_diagnostics import PARSER_REVISION, FileFingerprint
from src.pipeline import parse_excel_catalog, run_procurement_pipeline, PipelineExecutionError


# ============================================================================
# 1. Canonical Shared Predicate Tests (F06, F07, F08)
# ============================================================================

class TestOldPricePredicate:
    """Verifies canonical predicate behavior, unicode cleaning, markers, and brand safeguards."""

    @pytest.mark.parametrize("item_text", [
        "س ق",
        "ق س",
        "س.ق",
        "ق.س",
        "س . ق",
        "ق . س",
        "سق",
        "قس",
        "فوليك اسيد ميباكووو20قرص س ق",
        "فوليك اسيد ميباكووو20قرص س.ق",
        "فوليك اسيد ميباكووو20قرص ق س",
        "فوليك اسيد ميباكووو20قرص ق.س",
        "فوليك اسيد ميباكووو20قرص س . ق",
        "فوليك اسيد ميباكووو20قرص سق",
        "فوليك اسيد ميباكووو20قرص قس",
        "فوليك اسيد ميباكووو20قرص س ق\ufeff",          # BOM
        "فوليك اسيد ميباكووو20قرص س ق\u200e",          # LRM
        "فوليك اسيد ميباكووو20قرص س ق\u200f",          # RLM
        "فوليك اسيد ميباكووو20قرص س ق\u202a\u202c",    # Embedding / Pop
        "فوليك اسيد ميباكووو20قرص س ق\u2066\u2069",    # Isolates
        "فوليك اسيد ميباكووو20قرص س ق\t\n",            # Tabs and newlines
        "xxفوليك اسيد ميباكووو20قرص س قxx",            # Outer xx...xx marker
        "فوليك اسيد \u061cس ق\u061c",                 # Arabic Letter Mark
        "xxفوليك اسيد ميباكووو20قرص س ق",              # Leading xx marker
        "فوليك اسيد ميباكووو20قرص س قxx",              # Trailing xx marker
        "   فوليك اسيد ميباكووو20قرص س ق   ",          # Leading/trailing spaces
    ])
    def test_positive_old_price_detection(self, item_text):
        assert is_old_price_item(item_text) is True, f"Failed to detect old price in: {item_text!r}"

    @pytest.mark.parametrize("item_text", [
        None,
        pd.NA,
        float("nan"),
        "",
        "   ",
        "بانادول 20 قرص س ج",       # Valid New Price state (سعر جديد)
        "س ج",                      # Standalone New Price marker
        "اقراص",                    # Standard form token
        "لاسيكس",                   # Lasix in Arabic
        "زوفيراكس",                 # Zovirax in Arabic
        "Lasix",                    # English brand ending in x
        "Xanax",                    # English brand starting/ending in x
        "Celebrex",                 # English brand ending in x
        "xxLasixxx",                # Cleaned outer marker on English brand
        "xxXanaxxx",                # Cleaned outer marker on English brand
        "دمشق",                     # Arabic word containing sheen and qaf
        "سقراط",                    # Socrates (starts with سق but does not end with it)
        "س ق بانادول",              # Starts with marker, not suffix
    ])
    def test_negative_brand_safeguards(self, item_text):
        assert is_old_price_item(item_text) is False, f"Falsely excluded legitimate item: {item_text!r}"


# ============================================================================
# 2. ExcludedItem Dataclass Contract (F10)
# ============================================================================

class TestExcludedItemContract:
    def test_dataclass_fields_and_immutability(self):
        ex = ExcludedItem(
            reason="old_price_suffix",
            source_file="test_po.xlsx",
            sheet_name="Orders",
            row_index=15,
            raw_name="بانادول 20 قرص س ق",
            quantity=50.0,
        )
        assert ex.reason == "old_price_suffix"
        assert ex.source_file == "test_po.xlsx"
        assert ex.sheet_name == "Orders"
        assert ex.row_index == 15
        assert ex.raw_name == "بانادول 20 قرص س ق"
        assert ex.quantity == 50.0

        with pytest.raises(Exception):
            ex.quantity = 100.0  # Must be frozen


# ============================================================================
# 3. Excel Purchase Order Ingestion (F09, F10, F16)
# ============================================================================

class TestExcelOrderIngestion:

    def test_0911_target_yield_and_exclusion(self):
        """0911.xlsx contains 1 old-price item (folic acid, qty 22) and must yield 202 items."""
        fpath = os.path.join("train", "0911.xlsx")
        assert os.path.exists(fpath), f"File not found: {fpath}"

        df, exclusions = load_purchase_order(fpath, return_exclusions=True)
        assert len(df) == 202, f"Expected 202 distinct items, got {len(df)}"
        assert len(exclusions) == 1, f"Expected 1 excluded item, got {len(exclusions)}"
        assert exclusions[0].reason == "old_price_suffix"
        assert exclusions[0].quantity == 22.0
        assert is_old_price_item(exclusions[0].raw_name) is True

    def test_preserves_new_price_state_rows(self, tmp_path):
        """Verifies new-price rows ('س ج') are never excluded and preserved verbatim."""
        po_path = str(tmp_path / "po_states.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "OrderSheet"
        ws.append(["كود الصنف", "اسم الصنف", "الكمية"])
        ws.append(["101", "بانادول اكسترا 24 قرص س ج", 10])
        ws.append(["102", "بانادول اكسترا 24 قرص س ق", 25])
        ws.append(["103", "كونكور 5 مجم 30 قرص", 5])
        wb.save(po_path)

        df, exclusions = load_purchase_order(po_path, return_exclusions=True)
        items = list(df["requested_item"])
        assert "بانادول اكسترا 24 قرص س ج" in items
        assert "بانادول اكسترا 24 قرص س ق" not in items
        assert "كونكور 5 مجم 30 قرص" in items
        assert len(df) == 2
        assert len(exclusions) == 1
        assert exclusions[0].raw_name == "بانادول اكسترا 24 قرص س ق"
        assert exclusions[0].quantity == 25.0


# ============================================================================
# 4. Catalog Ingestion Filtering (F09, F13)
# ============================================================================

class TestCatalogIngestion:

    def test_parse_excel_catalog_filters_old_price(self, tmp_path):
        """parse_excel_catalog must exclude old-price items before standard schema construction."""
        cat_path = str(tmp_path / "supplier_catalog.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Catalog"
        ws.append(["اسم الصنف", "الخصم", "سعر الجمهور"])
        ws.append(["بانادول اكسترا 24 قرص", "25%", 45.0])
        ws.append(["بانادول اكسترا 24 قرص س ق", "30%", 40.0])  # Old price row in catalog
        ws.append(["كونكور 5 مجم 30 قرص", "20%", 60.0])
        wb.save(cat_path)

        cat_df = parse_excel_catalog(cat_path, warehouse_name="المخزن الرئيسي")
        cat_items = list(cat_df["item_name"])
        assert "بانادول اكسترا 24 قرص" in cat_items
        assert "كونكور 5 مجم 30 قرص" in cat_items
        assert not any(is_old_price_item(name) for name in cat_items)
        assert len(cat_df) == 2


# ============================================================================
# 5. Reference Average Discounts Validation (F14)
# ============================================================================

class TestAverageDiscountsValidation:

    def test_schema_and_value_bounds_validation(self, tmp_path):
        """Small valid custom reference files load cleanly without filename-dependent assertions."""
        ref_path = str(tmp_path / "average_discounts.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Discounts"
        ws.append(["اسم الصنف", "خصم مرجح"])
        ws.append(["بانادول اكسترا 24 قرص", "25%"])
        ws.append(["كونكور 5 مجم 30 قرص", "20%"])
        ws.append(["بانادول اكسترا 24 قرص س ق", "35%"])  # Old price row should be excluded
        wb.save(ref_path)

        df = load_average_discounts_file(ref_path)
        assert len(df) == 2  # Old price excluded, 2 valid items retained
        assert set(df.columns) == {"raw_name", "clean_name", "avg_discount_rate"}
        assert (df["avg_discount_rate"] <= 1.0).all()
        assert (df["avg_discount_rate"] >= 0.0).all()

    def test_invalid_discount_schema_raises_error(self, tmp_path):
        """Missing discount column raises ValueError."""
        ref_path = str(tmp_path / "invalid_discounts.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Discounts"
        ws.append(["اسم الصنف"])
        ws.append(["بانادول اكسترا 24 قرص"])
        wb.save(ref_path)

        with pytest.raises(ValueError, match="Could not locate"):
            load_average_discounts_file(ref_path)


# ============================================================================
# 6. Pipeline Isolation & All-Excluded Order Handling (F11, F12)
# ============================================================================

class TestPipelineSafeguards:

    def test_all_excluded_order_clean_rejection(self, tmp_path):
        """All-excluded purchase order reports intentional exclusion cleanly via PipelineExecutionError."""
        po_path = str(tmp_path / "all_old_price_order.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Order"
        ws.append(["اسم الصنف", "الكمية"])
        ws.append(["بانادول اكسترا س ق", 10])
        ws.append(["كونكور 5 مجم س.ق", 5])
        wb.save(po_path)

        cat_path = str(tmp_path / "catalog.xlsx")
        wb_c = openpyxl.Workbook()
        ws_c = wb_c.active
        ws_c.append(["اسم الصنف", "الخصم", "سعر الجمهور"])
        ws_c.append(["بانادول اكسترا", "25%", 40.0])
        wb_c.save(cat_path)

        with pytest.raises(PipelineExecutionError) as exc_info:
            run_procurement_pipeline(
                order_files=[po_path],
                catalog_files=[cat_path],
                output_dir=str(tmp_path / "out"),
            )

        err = exc_info.value
        assert err.diagnostics.get("outcome") == "all_items_excluded"
        assert err.diagnostics.get("order_exclusions_count") == 2
        assert "intentionally excluded" in str(err).lower() or "intentionally excluded" in err.diagnostics.get("message", "").lower()


# ============================================================================
# 7. Cache Fingerprint Revision (F15)
# ============================================================================

class TestDiagnosticsRevision:

    def test_parser_revision_is_bumped(self):
        assert PARSER_REVISION == "2026.11.11.1"
        fp = FileFingerprint(path="dummy.pdf", sha256="abc123")
        assert fp.parser_revision == "2026.11.11.1"
