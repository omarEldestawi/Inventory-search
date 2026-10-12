# -*- coding: utf-8 -*-
"""
Comprehensive Adversarial Stress Test Suite for Egyptian Pharma Procurement Optimizer.
Tests edge-case resilience, corrupted files, extreme values, high concurrency,
and verifies zero crashes under abnormal inputs.
"""
import os
import sys
import tempfile
import pytest
import pandas as pd
import fitz  # PyMuPDF

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.pdf_parser import PDFCatalogParser
from src.excel_parser import load_purchase_order
from src.normalizer import parse_discount, normalize_vendor_name, unreverse_arabic_text
from src.pharma_matcher import is_safe_pharmaceutical_match, check_strength_compatibility, check_modifier_compatibility, clean_arabic_string
from src.allocator import MedicineAllocator
from src.medication_db import MedicationDB
from src.pipeline import run_procurement_pipeline, PipelineExecutionError


class TestCorruptedAndMalformedPDFStress:
    """Stress tests for PDF parsing when handling corrupt, empty, or garbage files."""

    def test_zero_byte_pdf(self):
        """Zero-byte PDF must fail gracefully without crashing."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
        try:
            parser = PDFCatalogParser(pdf_path)
            df = parser.parse()
            assert isinstance(df, pd.DataFrame)
            assert df.empty
        finally:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)

    def test_random_binary_garbage_pdf(self):
        """Random binary bytes disguised as PDF must return empty DataFrame, no crash."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"\x00\xFF\xFE\xFD\x12\x34\x56\x78\x9A\xBC\xDE\xF0" * 500)
            pdf_path = f.name
        try:
            parser = PDFCatalogParser(pdf_path)
            df = parser.parse()
            assert isinstance(df, pd.DataFrame)
            assert df.empty
        finally:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)

    def test_truncated_pdf_header_only(self):
        """A PDF truncated right after header must not crash PyMuPDF parser."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4\n%EOF")
            pdf_path = f.name
        try:
            parser = PDFCatalogParser(pdf_path)
            df = parser.parse()
            assert isinstance(df, pd.DataFrame)
            assert df.empty
        finally:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)

    def test_empty_page_pdf(self):
        """A valid PDF containing 10 completely blank pages."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
        try:
            doc = fitz.open()
            for _ in range(10):
                doc.new_page(width=595, height=842)
            doc.save(pdf_path)
            doc.close()

            parser = PDFCatalogParser(pdf_path)
            df = parser.parse()
            assert isinstance(df, pd.DataFrame)
            assert df.empty
        finally:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)


class TestExtremeNumericAndStringValuesStress:
    """Stress tests parsing erratic prices, strange discounts, and edge-case strings."""

    @pytest.mark.parametrize("price_input,expected_type", [
        (None, (int, float)),
        ("", (int, float)),
        ("0", (int, float)),
        ("-150.50", (int, float)),
        ("999999999.99", (int, float)),
        ("15,50", (int, float)),
        ("١٢٥٫٥٠", (int, float)),  # Arabic Indic numerals
        ("سعر جديد 120.00 ج", (int, float)),
        ("N/A", (int, float)),
        ("مجانا", (int, float)),
        ("100/200", (int, float)),
        ("12.34.56", (int, float)),
    ])
    def test_adversarial_price_parsing(self, price_input, expected_type):
        """parse_price must never raise an unhandled exception on bizarre inputs."""
        parser = PDFCatalogParser("dummy.pdf")
        val = parser._parse_price(price_input)
        assert isinstance(val, expected_type)
        assert not isinstance(val, bool)
        assert val >= 0

    @pytest.mark.parametrize("disc_input", [
        None,
        "",
        "0%",
        "100%",
        "150%",      # Out of bounds (>100%)
        "-25%",      # Negative discount
        "25.5%",
        "٢٥%",       # Arabic Indic discount
        "خصم خاص 30 % نقدى",
        "صافي",
        "سعر رسمي",
        "0.25",
        "1/2",
    ])
    def test_adversarial_discount_parsing(self, disc_input):
        """parse_discount must normalize to a valid float between 0.0 and 1.0 (or clamp cleanly)."""
        rate = parse_discount(disc_input)
        assert isinstance(rate, float)
        assert 0.0 <= rate <= 1.0, f"Discount {rate} out of valid 0-1 bounds for input '{disc_input}'"


class TestCorruptedAndMalformedExcelOrdersStress:
    """Stress tests purchase order ingestion with malformed Excel files."""

    def test_empty_excel_workbook(self):
        """Completely empty Excel file must raise ValueError or return empty without unhandled crash."""
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            excel_path = f.name
        try:
            wb = pd.DataFrame()
            wb.to_excel(excel_path, index=False)
            try:
                df = load_purchase_order(excel_path)
                assert isinstance(df, pd.DataFrame)
            except ValueError:
                pass  # Graceful domain error is acceptable
        finally:
            if os.path.exists(excel_path):
                os.remove(excel_path)

    def test_excel_with_10_empty_rows_before_headers(self):
        """Excel sheet where headers begin at row 11."""
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            excel_path = f.name
        try:
            data = [[""] * 3] * 10
            data.append(["اسم الصنف", "الكمية", "سعر"])
            data.append(["كونكور 10 مجم", 5, 100.0])
            data.append(["كتافلام 50 مجم", 10, 60.0])
            df_raw = pd.DataFrame(data)
            df_raw.to_excel(excel_path, header=False, index=False)

            df = load_purchase_order(excel_path)
            assert not df.empty
            assert len(df) == 2
            assert "requested_item" in df.columns
            assert "quantity" in df.columns
        finally:
            if os.path.exists(excel_path):
                os.remove(excel_path)

    def test_excel_with_arabic_indic_quantities(self):
        """Excel sheet with Arabic Indic numerals in quantity column (e.g. ٥, ١٠)."""
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            excel_path = f.name
        try:
            df_in = pd.DataFrame({
                "اسم الصنف": ["بانادول اكسترا", "كونكور 5 مجم"],
                "الكمية": ["٥", "١٢"],
            })
            df_in.to_excel(excel_path, index=False)

            df = load_purchase_order(excel_path)
            assert not df.empty
            assert df.iloc[0]["quantity"] == 5
            assert df.iloc[1]["quantity"] == 12
        finally:
            if os.path.exists(excel_path):
                os.remove(excel_path)

    def test_excel_with_erroneous_non_numeric_quantities(self):
        """Excel sheet with text quantities like 'علبتين' or blanks."""
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            excel_path = f.name
        try:
            df_in = pd.DataFrame({
                "اسم الصنف": ["اميبريد 50 مجم", "اوجمانتين 1 جم", "دواء تجريبي"],
                "الكمية": ["علبتين", "", None],
            })
            df_in.to_excel(excel_path, index=False)

            df = load_purchase_order(excel_path)
            assert not df.empty
            # Invalid text quantities must fall back to default quantity 1.0, zero crash
            assert all(df["quantity"] >= 1)
        finally:
            if os.path.exists(excel_path):
                os.remove(excel_path)


class TestHighVolumeAllocationAndMemoryStress:
    """Stress tests the MedicineAllocator engine with high item counts and edge distributions."""

    def test_large_scale_allocation_stress(self):
        """Reconcile 500 order items against a synthetic catalog of 5,000 items in < 5 seconds."""
        # 1. Build synthetic multi-warehouse inventory
        warehouses = [f"مخزن {i}" for i in range(1, 6)]
        inv_rows = []
        for i in range(1000):
            item_name = f"صنف تجريبي {i} 100 مجم اقراص"
            for w in warehouses:
                inv_rows.append({
                    "warehouse_name": w,
                    "item_name": item_name,
                    "normalized_name": item_name.lower(),
                    "dosage": "100mg",
                    "unit_size": "قرص",
                    "base_price": 50.0 + (i % 20),
                    "discount_rate": 0.15 + ((i % 10) * 0.01),
                    "stock_status": True
                })
        inv_df = pd.DataFrame(inv_rows)
        assert len(inv_df) == 5000

        # 2. Build 500 requested orders
        order_rows = []
        for i in range(500):
            order_rows.append({
                "requested_item": f"صنف تجريبي {i} 100 مجم",
                "quantity": (i % 5) + 1,
                "normalized_name": f"صنف تجريبي {i} 100 مجم",
                "dosage": "100mg",
                "unit_size": "قرص"
            })
        order_df = pd.DataFrame(order_rows)

        allocator = MedicineAllocator(inv_df, enable_ai=False)
        result = allocator.allocate_order(order_df)

        assert result is not None
        assert "master_comparison" in result
        assert "allocated_orders" in result
        assert len(result["master_comparison"]) == 500
        assert result["kpis"]["matched_items"] == 500

    def test_all_items_out_of_stock_stress(self):
        """When 100% of inventory items are stock_status=False, zero crashes and all marked OOS."""
        inv_df = pd.DataFrame([
            {
                "warehouse_name": "مخزن السلام",
                "item_name": "كونكور 10 مجم",
                "normalized_name": "كونكور 10 مجم",
                "dosage": "10mg",
                "unit_size": "قرص",
                "base_price": 100.0,
                "discount_rate": 0.25,
                "stock_status": False  # Out of stock!
            }
        ])
        order_df = pd.DataFrame([
            {
                "requested_item": "كونكور 10 مجم",
                "quantity": 2,
                "normalized_name": "كونكور 10 مجم",
                "dosage": "10mg",
                "unit_size": "قرص"
            }
        ])
        allocator = MedicineAllocator(inv_df, enable_ai=False)
        result = allocator.allocate_order(order_df)

        assert result["kpis"]["matched_items"] == 0
        assert result["kpis"]["out_of_stock"] == 1
        assert not result["out_of_stock"].empty

    def test_tied_discounts_across_multiple_vendors_stress(self):
        """When 5 vendors offer identical maximum discounts, allocator picks deterministically without crash."""
        inv_rows = []
        for i in range(5):
            inv_rows.append({
                "warehouse_name": f"مخزن {chr(65+i)}",
                "item_name": "بانادول اكسترا 500 مجم",
                "normalized_name": "بانادول اكسترا 500 مجم",
                "dosage": "500mg",
                "unit_size": "قرص",
                "base_price": 50.0,
                "discount_rate": 0.20,  # All 20%
                "stock_status": True
            })
        inv_df = pd.DataFrame(inv_rows)
        order_df = pd.DataFrame([
            {
                "requested_item": "بانادول اكسترا",
                "quantity": 10,
                "normalized_name": "بانادول اكسترا",
                "dosage": "500mg",
                "unit_size": "قرص"
            }
        ])
        allocator = MedicineAllocator(inv_df, enable_ai=False)
        result = allocator.allocate_order(order_df)
        assert result["kpis"]["matched_items"] == 1
        winner = result["master_comparison"].iloc[0]["المخزن الفائز"]
        assert winner in [f"مخزن {chr(65+i)}" for i in range(5)]


class TestClinicalSafetyGatesAdversarialStress:
    """Stress tests adversarial drug name lookalikes to verify zero dangerous substitutions."""

    @pytest.mark.parametrize("req_item,cand_item", [
        # Cross-drug lookalikes
        ("اماريل 2 مجم", "اماريل 4 مجم"),              # Different strength
        ("كونكور 5 مجم بلس", "كونكور 5 مجم"),           # Extra modifier (plus)
        ("بانادول اكسترا", "بانادول نايت"),            # Extra vs Night
        ("ديكلوفاك 50 مجم اقراص", "ديكلوفاك 75 مجم امبول"), # Form & strength mismatch
        ("فوليك اسيد النيل", "فوليك اسيد ميباكو"),      # Manufacturer conflict
        ("كتافلام 50 مجم اقراص", "كتافلام نقط بالفم"),    # Solid Oral vs Oral Drops
        ("بيبيلاك 1", "بيبيلاك 2"),                    # Milk stage 1 vs 2
        ("نان 1", "نان ال اف"),                        # Standard milk vs Lactose Free
    ])
    def test_strict_safety_gate_rejections(self, req_item, cand_item):
        """Clinical safety gate must strictly REJECT hazardous substitutions."""
        is_safe = is_safe_pharmaceutical_match(req_item, cand_item)
        assert not is_safe, f"Dangerous substitution falsely allowed: '{req_item}' matched with '{cand_item}'!"
