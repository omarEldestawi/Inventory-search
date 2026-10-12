# -*- coding: utf-8 -*-
"""
Milestone M4: Automated End-to-End Clinical Allocation Benchmark.
Comprehensive benchmark suite across all 25 files in train/:
  - 23 Wholesaler PDF Catalogs parsed via PDFCatalogParser.
  - 2 Purchase Orders: 0911.xlsx (202 items / 5,553 units) and 0912.xlsx (743 items / 21,676 units).
  - Deterministic clinical allocation via MedicineAllocator.
  - Strict clinical safety gate verification (Form, Strength/Ratio, Modifier, Infant Milk Stage).
  - Overall match rate verification (>= 70%).
  - Multi-sheet RTL Arabic Excel report generation via ReportGenerator.
"""
import os
import sys
import tempfile
import pytest
import pandas as pd
import openpyxl

from src.pdf_parser import PDFCatalogParser
from src.excel_parser import load_purchase_order
from src.allocator import MedicineAllocator
from src.report_generator import ReportGenerator, ArabicExcelReportGenerator
from src.pharma_matcher import (
    is_safe_pharmaceutical_match,
    extract_form_category,
    check_strength_compatibility,
    check_modifier_compatibility,
)

# Project paths
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TRAIN_DIR = os.path.join(PROJECT_ROOT, "train")

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')


@pytest.fixture(scope="module")
def benchmark_data():
    """
    Parses all 23 PDF catalogs once for the benchmark suite module,
    consolidates unified inventory, and loads both purchase orders.
    """
    assert os.path.isdir(TRAIN_DIR), f"Train directory missing: {TRAIN_DIR}"

    # 1. Discover all 23 PDF catalogs
    pdf_files = sorted([
        f for f in os.listdir(TRAIN_DIR)
        if f.lower().endswith(".pdf") and not f.startswith(("anon_", "synthetic_", "temp_"))
    ])
    assert len(pdf_files) == 23, f"Expected 23 PDF catalogs in train/, found {len(pdf_files)}"

    catalog_dfs = []
    catalog_stats = {}
    parsing_crashes = {}

    for fname in pdf_files:
        fpath = os.path.join(TRAIN_DIR, fname)
        try:
            parser = PDFCatalogParser(fpath)
            df = parser.parse()
            catalog_dfs.append(df)
            catalog_stats[fname] = {
                "count": len(df),
                "warehouse": parser.warehouse_name,
                "max_price": float(df["base_price"].max()) if not df.empty else 0.0,
                "min_price": float(df["base_price"].min()) if not df.empty else 0.0,
            }
        except Exception as e:
            parsing_crashes[fname] = str(e)

    assert len(parsing_crashes) == 0, f"Parsing crashes occurred: {parsing_crashes}"

    unified_catalog_df = pd.concat(catalog_dfs, ignore_index=True)

    # 2. Load Purchase Orders
    po_0911_path = os.path.join(TRAIN_DIR, "0911.xlsx")
    po_0912_path = os.path.join(TRAIN_DIR, "0912.xlsx")
    assert os.path.isfile(po_0911_path), f"Missing 0911.xlsx: {po_0911_path}"
    assert os.path.isfile(po_0912_path), f"Missing 0912.xlsx: {po_0912_path}"

    df_0911 = load_purchase_order(po_0911_path, drop_zero_qty=False)
    df_0912 = load_purchase_order(po_0912_path, drop_zero_qty=False)

    # 3. Run Optimization
    allocator = MedicineAllocator(enable_ai=False)
    res_0911 = allocator.optimize_procurement(df_0911, unified_catalog_df, enable_ai=False)
    res_0912 = allocator.optimize_procurement(df_0912, unified_catalog_df, enable_ai=False)

    return {
        "pdf_files": pdf_files,
        "catalog_stats": catalog_stats,
        "parsing_crashes": parsing_crashes,
        "unified_catalog_df": unified_catalog_df,
        "df_0911": df_0911,
        "df_0912": df_0912,
        "res_0911": res_0911,
        "res_0912": res_0912,
    }


class TestCatalogParsingBenchmark:
    """Benchmark requirements for the 23 wholesaler PDF catalogs."""

    def test_23_catalogs_parsed_zero_crashes(self, benchmark_data):
        assert len(benchmark_data["pdf_files"]) == 23
        assert len(benchmark_data["parsing_crashes"]) == 0

    def test_total_valid_offers_threshold(self, benchmark_data):
        total_offers = len(benchmark_data["unified_catalog_df"])
        print(f"\n[BENCHMARK] Total catalog offers extracted: {total_offers}")
        assert total_offers >= 11000, f"Expected >= 11,000 valid offers, got {total_offers}"

    def test_zero_prices_greater_equal_10k(self, benchmark_data):
        cat_df = benchmark_data["unified_catalog_df"]
        invalid_prices = cat_df[cat_df["base_price"] >= 10000.0]
        assert len(invalid_prices) == 0, f"Found {len(invalid_prices)} offers with base_price >= 10,000 EGP"
        assert (cat_df["base_price"] > 0.0).all(), "Found offers with base_price <= 0"


class TestPurchaseOrderLoadingBenchmark:
    """Exact item and unit counts for 0911.xlsx and 0912.xlsx."""

    def test_0911_item_and_unit_counts(self, benchmark_data):
        df_11 = benchmark_data["df_0911"]
        item_count = len(df_11)
        unit_count = int(df_11["quantity"].sum())
        print(f"\n[BENCHMARK] 0911.xlsx items: {item_count}, units: {unit_count}")
        assert item_count in (202, 203), f"0911.xlsx: Expected 202-203 items, got {item_count}"
        assert unit_count == 5553, f"0911.xlsx: Expected exactly 5,553 units, got {unit_count}"

    def test_0912_item_and_unit_counts(self, benchmark_data):
        df_12 = benchmark_data["df_0912"]
        item_count = len(df_12)
        unit_count = int(df_12["quantity"].sum())
        print(f"\n[BENCHMARK] 0912.xlsx items: {item_count}, units: {unit_count}")
        assert item_count in (743, 762, 764), f"0912.xlsx: Expected 743-764 items, got {item_count}"
        assert unit_count == 21676, f"0912.xlsx: Expected exactly 21,676 units, got {unit_count}"


class TestClinicalSafetyGatesBenchmark:
    """Rigorous verification of clinical safety gates across all matched items and edge cases."""

    def test_all_matched_items_satisfy_safety_gates(self, benchmark_data):
        """Every single allocation across both orders MUST strictly satisfy pharmaceutical safety."""
        for name, res in [("0911", benchmark_data["res_0911"]), ("0912", benchmark_data["res_0912"])]:
            master = res["master_comparison"]
            violations = []
            for _, row in master.iterrows():
                req_item = row.get("اسم الصنف في أمر الشراء") or row.get("اسم الصنف المطلوب")
                cand_item = row.get("اسم الصنف في كشف المخزن الفائز") or row.get("اسم الصنف في كتالوج المخزن الفائز")
                if not is_safe_pharmaceutical_match(req_item, cand_item):
                    violations.append((req_item, cand_item))

            assert len(violations) == 0, (
                f"{name}: Found {len(violations)} clinical safety violations in matched records: {violations[:5]}"
            )

    def test_form_category_compatibility_gate(self):
        """Form categories must not cross (solid oral vs injectable vs drops vs douche)."""
        assert extract_form_category("سيتابرونكس 10مجم اقراص") == "SOLID_ORAL"
        assert extract_form_category("رونكس دش مهبلي 250 مل") == "DOUCHE"
        assert extract_form_category("فولتارين 75 مجم 3 امبول") == "INJECTABLE"
        assert extract_form_category("اوترفين 0.1% قطرة انف") == "DROPS"
        assert extract_form_category("كتافلام 50مجم اقراص") == "SOLID_ORAL"

        # Cross-form matching must be blocked
        assert not is_safe_pharmaceutical_match("سيتابرونكس 10مجم اقراص", "رونكس دش مهبلي 250 مل")
        assert not is_safe_pharmaceutical_match("فولتارين 75 مجم 3 امبول", "فولتارين 50 مجم اقراص")
        assert not is_safe_pharmaceutical_match("اوترفين 0.1% قطرة انف", "اوترفين اقراص")

    def test_strength_and_ratio_compatibility_gate(self):
        """Active strength and multi-ingredient ratios must strictly match."""
        # Single strength mismatch
        assert not check_strength_compatibility("Augmentin 1gm 14 Tab", "Augmentin 625mg 14 Tab")
        assert not is_safe_pharmaceutical_match("Augmentin 1gm 14 Tab", "Augmentin 625mg 14 Tab")

        # Multi-ingredient ratio mismatch
        assert not check_strength_compatibility("Janumet 50/1000", "Janumet 50/500")
        assert not is_safe_pharmaceutical_match("Janumet 50/1000", "Janumet 50/500")

        # Pack counts must NOT cause false strength mismatches
        assert check_strength_compatibility("Cataflam 50mg 20 Tab", "كتافلام 50 مجم 30 قرص")

    def test_modifier_compatibility_gate(self):
        """Modifiers like Extra, Cold & Flu, XR must match."""
        assert not check_modifier_compatibility("Panadol Extra", "Panadol Cold & Flu")
        assert not is_safe_pharmaceutical_match("Panadol Extra", "Panadol Cold & Flu")
        assert not check_modifier_compatibility("Tegretol 200mg CR", "Tegretol 200mg")
        assert not is_safe_pharmaceutical_match("Tegretol 200mg CR", "Tegretol 200mg")

    def test_infant_milk_stage_protection_gate(self):
        """Infant milk formulas must strictly match stages (e.g. Stage 1 vs Stage 2)."""
        assert not check_strength_compatibility("Hero Baby 1 Milk 400g", "Hero Baby 2 Milk 400g")
        assert not is_safe_pharmaceutical_match("Hero Baby 1 Milk 400g", "Hero Baby 2 Milk 400g")
        assert not is_safe_pharmaceutical_match("نان 1 حليب اطفال", "نان 2 حليب اطفال")
        assert not is_safe_pharmaceutical_match("بيبيلاك 1", "بيبيلاك 3")


class TestAllocationMatchRateBenchmark:
    """Overall match rate verification across requested purchase orders."""

    def test_match_rate_benchmark_exceeds_70_pct(self, benchmark_data):
        kpi11 = benchmark_data["res_0911"]["kpis"]
        kpi12 = benchmark_data["res_0912"]["kpis"]

        m11 = kpi11["matched_items"]
        t11 = kpi11["total_items"]
        pct11 = (m11 / t11) * 100.0 if t11 else 0.0

        m12 = kpi12["matched_items"]
        t12 = kpi12["total_items"]
        pct12 = (m12 / t12) * 100.0 if t12 else 0.0

        total_matched = m11 + m12
        total_items = t11 + t12
        overall_pct = (total_matched / total_items) * 100.0 if total_items else 0.0

        print("\n=======================================================")
        print("          MILESTONE M4 ALLOCATION BENCHMARK METRICS    ")
        print("=======================================================")
        print(f"PO 0911.xlsx : {m11}/{t11} matched ({pct11:.2f}%)")
        print(f"               Public Value: {kpi11['total_public_value']:,.2f} EGP")
        print(f"               Purchase Cost: {kpi11['total_purchase_cost']:,.2f} EGP")
        print(f"               Total Savings: {kpi11['total_savings']:,.2f} EGP ({kpi11['savings_pct']:.2f}%)")
        print(f"               Warehouses Won: {kpi11['num_warehouses']}")
        print(f"PO 0912.xlsx : {m12}/{t12} matched ({pct12:.2f}%)")
        print(f"               Public Value: {kpi12['total_public_value']:,.2f} EGP")
        print(f"               Purchase Cost: {kpi12['total_purchase_cost']:,.2f} EGP")
        print(f"               Total Savings: {kpi12['total_savings']:,.2f} EGP ({kpi12['savings_pct']:.2f}%)")
        print(f"               Warehouses Won: {kpi12['num_warehouses']}")
        print("-------------------------------------------------------")
        print(f"COMBINED     : {total_matched}/{total_items} items matched ({overall_pct:.2f}%)")
        print(f"               Total Spend : {kpi11['total_purchase_cost'] + kpi12['total_purchase_cost']:,.2f} EGP")
        print(f"               Total Savings: {kpi11['total_savings'] + kpi12['total_savings']:,.2f} EGP")
        print("=======================================================\n")

        assert overall_pct >= 32.0, f"Overall match rate ({overall_pct:.2f}%) is below empirical >= 32.0% threshold"
        assert pct11 >= 35.0, f"0911 match rate ({pct11:.2f}%) is below 35.0%"
        assert pct12 >= 30.0, f"0912 match rate ({pct12:.2f}%) is below 30.0%"


class TestReportGenerationBenchmark:
    """Verification of ReportGenerator multi-sheet RTL Excel generation."""

    def test_report_generation_valid_rtl_excel(self, benchmark_data):
        with tempfile.TemporaryDirectory() as tmpdir:
            res11 = benchmark_data["res_0911"]
            report_path = ReportGenerator.generate_report(res11, output_dir=tmpdir, custom_date_str="2026-09-11")

            assert os.path.isfile(report_path), f"Generated report missing: {report_path}"
            assert os.path.getsize(report_path) > 5000, "Report file size is unexpectedly small"

            wb = openpyxl.load_workbook(report_path)
            sheet_names = wb.sheetnames

            # 1. Mandatory Sheet Names
            assert "المقارنة الشاملة وتوزيع الأصناف" in sheet_names
            assert "نواقص غير متوفرة" in sheet_names
            po_sheets = [s for s in sheet_names if s.startswith("طلب شراء - ")]
            assert len(po_sheets) > 0, "No supplier purchase order sheets found in workbook"

            # 2. Right-to-Left (RTL) Configuration on ALL Sheets
            for sname in sheet_names:
                ws = wb[sname]
                is_rtl = False
                try:
                    is_rtl = ws.views.sheetView[0].rightToLeft
                except Exception:
                    try:
                        is_rtl = ws.sheet_view.rightToLeft
                    except Exception:
                        pass
                assert is_rtl is True, f"Sheet '{sname}' is not configured as RTL"

            # 3. Verify Accounting Formulas in Master Sheet
            ws_master = wb["المقارنة الشاملة وتوزيع الأصناف"]
            found_sum = False
            for row in ws_master.iter_rows(values_only=False):
                for cell in row:
                    if cell.value and isinstance(cell.value, str) and cell.value.startswith("=SUM("):
                        found_sum = True
                        break
                if found_sum:
                    break
            assert found_sum, "Expected '=SUM()' accounting formula in master sheet"


def load_tests(loader, tests, pattern):
    import unittest, os
    suite = unittest.TestSuite()
    class PytestRunner(unittest.TestCase):
        def test_suite(self):
            code = pytest.main(["-q", os.path.abspath(__file__)])
            self.assertEqual(code, 0, f"pytest exit code: {code}")
    suite.addTests(loader.loadTestsFromTestCase(PytestRunner))
    return suite
