# -*- coding: utf-8 -*-
"""
Comprehensive Consolidated Test Suite for Reference Weighted Average Discounts
Egyptian Pharmaceutical Procurement Optimizer (Milestone 4 - R4)

Covers:
  - Requirement R1: Ingestion, Path Resolution, Name Cleaning, Rate Normalization & File Classification
  - Requirement R2: Clinical Safety Matching, Strict Inequality, Descending Sort & Master Comparison Enrichment
  - Requirement R3: Dual RTL Arabic Excel Reports, Styling, Placeholder Resilience & Accounting Formula Preservation
"""

import os
import sys
import glob
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import pytest
import openpyxl
import pandas as pd
import numpy as np

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.average_discounts import (
    resolve_default_avg_discounts_path,
    clean_medication_display_name,
    _normalize_discount_rate,
    load_average_discounts_file,
)
from src.controller import classify_files, ClassifiedDict
from src.allocator import MedicineAllocator, evaluate_above_average_discounts
from src.pharma_matcher import is_safe_pharmaceutical_match
from src.report_generator import ArabicExcelReportGenerator, clean_sheet_title


# ============================================================================
# Requirement R1: Ingestion & Classification Test Suite
# ============================================================================

class TestRequirementR1IngestionAndClassification:
    """Verifies R1: bundled dataset loading, path resolution, name cleaning, and classification."""

    def test_bundled_reference_dataset_exists_and_loads_valid_rows(self):
        """Bundled average_discounts.xlsx must exist, contain >4,700 items, and have rates in [0.0, 1.0]."""
        bundled_path = resolve_default_avg_discounts_path()
        assert bundled_path is not None, "resolve_default_avg_discounts_path() returned None"
        assert os.path.isfile(bundled_path), f"Bundled file not found at: {bundled_path}"
        assert os.path.getsize(bundled_path) > 50_000, "Bundled file unexpectedly small"

        df = load_average_discounts_file(bundled_path)
        assert len(df) >= 4700, f"Expected >= 4,700 rows, got {len(df)}"
        assert list(df.columns) == ['raw_name', 'clean_name', 'avg_discount_rate']

        # Verify rate normalization bounds
        assert (df['avg_discount_rate'] >= 0.0).all(), "Found negative discount rate"
        assert (df['avg_discount_rate'] <= 1.0).all(), "Found discount rate > 1.0"
        assert not df['avg_discount_rate'].isna().any(), "Found NaN discount rates"

        # Verify clean names
        assert not (df['clean_name'] == "").any(), "Found empty clean_name"
        assert not df['clean_name'].isna().any(), "Found NaN clean_name"

    def test_resolve_default_avg_discounts_path_dev_and_frozen_modes(self):
        """resolve_default_avg_discounts_path resolves accurately in dev, MEIPASS, and frozen modes."""
        # 1. Dev mode
        dev_path = resolve_default_avg_discounts_path()
        assert dev_path is not None
        assert os.path.basename(dev_path) == "average_discounts.xlsx"
        assert os.path.isabs(dev_path)

        # 2. Simulated PyInstaller sys._MEIPASS mode
        with tempfile.TemporaryDirectory() as tmp_meipass:
            meipass_data = os.path.join(tmp_meipass, "data")
            os.makedirs(meipass_data, exist_ok=True)
            meipass_file = os.path.join(meipass_data, "average_discounts.xlsx")
            with open(meipass_file, "w") as fp:
                fp.write("dummy")

            with patch.object(sys, "_MEIPASS", tmp_meipass, create=True):
                # When _MEIPASS is present, it is checked
                resolved_meipass = resolve_default_avg_discounts_path()
                assert resolved_meipass is not None
                assert os.path.isfile(resolved_meipass)

        # 3. Simulated frozen executable directory
        with tempfile.TemporaryDirectory() as tmp_exe_dir:
            frozen_data = os.path.join(tmp_exe_dir, "_internal", "data")
            os.makedirs(frozen_data, exist_ok=True)
            frozen_file = os.path.join(frozen_data, "average_discounts.xlsx")
            with open(frozen_file, "w") as fp:
                fp.write("dummy")

            fake_exe = os.path.join(tmp_exe_dir, "EgyptianPharmaOptimizer.exe")
            with patch.object(sys, "frozen", True, create=True), \
                 patch.object(sys, "executable", fake_exe):
                resolved_frozen = resolve_default_avg_discounts_path()
                assert resolved_frozen is not None
                assert os.path.isfile(resolved_frozen)

    def test_clean_medication_display_name_strips_markers_and_preserves_english_brands(self):
        """clean_medication_display_name strips xx markers but strictly preserves English brands with X/x."""
        cases = [
            # Marker stripping on Arabic names
            ("xxالفينترن30قرصxx", "الفينترن30قرص"),
            ("xxجاست ريج 100مجم 30قرصxx", "جاست ريج 100مجم 30قرص"),
            ("  xx  سيلجون 20مجم20قرص  xx  ", "سيلجون 20مجم20قرص"),
            ("xفلوموكس500مجم  كبسولx", "فلوموكس500مجم  كبسول"),
            ("فلوموكس 500", "فلوموكس 500"),
            ("  كتافلام 50مجم  ", "كتافلام 50مجم"),
            ("XXكونكور 5مجم 30قرصXX", "كونكور 5مجم 30قرص"),

            # Marker stripping on English names
            ("xxXanaxxx", "Xanax"),
            ("xxXanax 0.5mgxx", "Xanax 0.5mg"),
            ("xxLasixxx", "Lasix"),
            ("xxCelebrexxx", "Celebrex"),

            # STRICT PRESERVATION of English names starting or ending with X/x
            ("Xanax", "Xanax"),
            ("Xanax 0.5mg", "Xanax 0.5mg"),
            ("Lasix", "Lasix"),
            ("Celebrex", "Celebrex"),
            ("Celebrex 200mg", "Celebrex 200mg"),
            ("Zovirax", "Zovirax"),
            ("Avelox", "Avelox"),
            ("Plavix", "Plavix"),

            # Edge cases
            ("", ""),
            (None, ""),
            ("   ", ""),
        ]
        for raw_val, expected in cases:
            cleaned = clean_medication_display_name(raw_val)
            assert cleaned == expected, f"Failed for '{raw_val}': expected '{expected}', got '{cleaned}'"

    def test_normalize_discount_rate_values_and_percentages(self):
        """_normalize_discount_rate handles numeric floats, percentages, and small % strings without 100x inflation."""
        assert _normalize_discount_rate(0.25) == 0.25
        assert _normalize_discount_rate(25) == 0.25
        assert _normalize_discount_rate(25.0) == 0.25
        assert _normalize_discount_rate('25%') == 0.25

        # Critical small percentage string verification (must not inflate 100x)
        assert _normalize_discount_rate('1%') == 0.01
        assert _normalize_discount_rate('0.5%') == 0.005
        assert _normalize_discount_rate('1.0%') == 0.01

        # Boundary values
        assert _normalize_discount_rate(0.0) == 0.0
        assert _normalize_discount_rate(1.0) == 1.0
        assert _normalize_discount_rate('100%') == 1.0
        assert _normalize_discount_rate(None) is None
        assert _normalize_discount_rate('') is None
        assert _normalize_discount_rate('invalid') is None

    def test_classify_files_categorization(self):
        """classify_files recognizes bundled/uploaded avg_discounts files and isolates catalogs/orders."""
        bundled_file = resolve_default_avg_discounts_path()
        assert bundled_file is not None

        # 1. Bundled reference file classifies into avg_discounts
        res = classify_files([bundled_file])
        assert bundled_file in res['avg_discounts']
        assert bundled_file not in res['catalogs']
        assert bundled_file not in res['orders']

        # 2. Real catalogs never in avg_discounts
        catalog_files = glob.glob(os.path.join(PROJECT_ROOT, "input", "catalogs", "*.pdf"))
        if catalog_files:
            res_cat = classify_files(catalog_files)
            assert len(res_cat['avg_discounts']) == 0
            assert len(res_cat['orders']) == 0
            assert len(res_cat['catalogs']) == len(catalog_files)

        # 3. Real orders never in avg_discounts
        order_file = os.path.join(PROJECT_ROOT, "input", "orders", "طلبية_اليوم.xlsx")
        if os.path.isfile(order_file):
            res_ord = classify_files([order_file])
            assert len(res_ord['avg_discounts']) == 0
            assert len(res_ord['catalogs']) == 0
            assert order_file in res_ord['orders']

        # 4. User uploaded reference file
        with tempfile.TemporaryDirectory() as tmp_dir:
            user_ref = os.path.join(tmp_dir, "أرصده المخازن_جديد.xlsx")
            pd.DataFrame([{"إسم الصنف": "Panadol Extra", "خصم مرجح": 0.35}]).to_excel(user_ref, index=False)
            res_user = classify_files([user_ref])
            assert user_ref in res_user['avg_discounts']
            assert user_ref not in res_user['catalogs']
            assert user_ref not in res_user['orders']

    def test_classify_files_backward_compatibility_dictionary_equality(self):
        """classify_files returns ClassifiedDict maintaining equality with legacy 3-key dicts."""
        res_empty = classify_files([])

        # 3-key comparison (both directions)
        assert res_empty == {"orders": [], "catalogs": [], "unknown": []}
        assert {"orders": [], "catalogs": [], "unknown": []} == res_empty

        # 4-key comparison (both directions)
        assert res_empty == {"orders": [], "catalogs": [], "avg_discounts": [], "unknown": []}
        assert {"orders": [], "catalogs": [], "avg_discounts": [], "unknown": []} == res_empty

        # When avg_discounts is populated, does NOT equal 3-key dict
        cd_populated = ClassifiedDict({
            "orders": [],
            "catalogs": [],
            "avg_discounts": ["data/average_discounts.xlsx"],
            "unknown": []
        })
        assert cd_populated != {"orders": [], "catalogs": [], "unknown": []}
        assert {"orders": [], "catalogs": [], "unknown": []} != cd_populated
        assert cd_populated == {
            "orders": [],
            "catalogs": [],
            "avg_discounts": ["data/average_discounts.xlsx"],
            "unknown": []
        }

        # JSON serialization preserves keys
        serialized = json.loads(json.dumps(res_empty))
        assert "avg_discounts" in serialized
        assert "orders" in serialized
        assert "catalogs" in serialized
        assert "unknown" in serialized


# ============================================================================
# Requirement R2: Matching & Discount Engine Test Suite
# ============================================================================

class TestRequirementR2MatchingAndDiscountEngine:
    """Verifies R2: candidate lookup, clinical safety matching, strict inequality, sorting, and enrichment."""

    @pytest.fixture
    def mock_catalog_inventory(self):
        """Constructs multi-warehouse catalog inventory with known discounts and clinical variations."""
        return pd.DataFrame([
            {
                'warehouse_name': 'مخزن السلام فارم',
                'item_name': 'Panadol Extra 24 Tab',
                'normalized_name': 'panadol extra 24 tab',
                'dosage': '500mg',
                'unit_size': '24 Tab',
                'base_price': 50.0,
                'discount_rate': 0.40,
                'stock_status': True,
            },
            {
                'warehouse_name': 'مخزن الفرسان بنها',
                'item_name': 'Panadol Extra 24 Tab',
                'normalized_name': 'panadol extra 24 tab',
                'dosage': '500mg',
                'unit_size': '24 Tab',
                'base_price': 50.0,
                'discount_rate': 0.45,
                'stock_status': True,
            },
            {
                'warehouse_name': 'مخزن السلام فارم',
                'item_name': 'Cataflam 50mg 20 Tab',
                'normalized_name': 'cataflam 50mg 20 tab',
                'dosage': '50mg',
                'unit_size': '20 Tab',
                'base_price': 60.0,
                'discount_rate': 0.25,
                'stock_status': True,
            },
            {
                'warehouse_name': 'مخزن السلام فارم',
                'item_name': 'Cataflam 25mg 20 Tab',
                'normalized_name': 'cataflam 25mg 20 tab',
                'dosage': '25mg',
                'unit_size': '20 Tab',
                'base_price': 40.0,
                'discount_rate': 0.50,
                'stock_status': True,
            },
            {
                'warehouse_name': 'مخزن الفرسان بنها',
                'item_name': 'Augmentin 1gm 14 Tab',
                'normalized_name': 'augmentin 1gm 14 tab',
                'dosage': '1gm',
                'unit_size': '14 Tab',
                'base_price': 120.0,
                'discount_rate': 0.30,
                'stock_status': True,
            },
            {
                'warehouse_name': 'مخزن الهضبة فارم',
                'item_name': 'Augmentin 500mg 14 Tab',
                'normalized_name': 'augmentin 500mg 14 tab',
                'dosage': '500mg',
                'unit_size': '14 Tab',
                'base_price': 90.0,
                'discount_rate': 0.45,
                'stock_status': True,
            },
            {
                'warehouse_name': 'مخزن السلام فارم',
                'item_name': 'Brufen 400mg 30 Tab',
                'normalized_name': 'brufen 400mg 30 tab',
                'dosage': '400mg',
                'unit_size': '30 Tab',
                'base_price': 40.0,
                'discount_rate': 0.20,
                'stock_status': True,
            },
            {
                'warehouse_name': 'مخزن الفرسان بنها',
                'item_name': 'ZeroDiscMed 100mg Tab',
                'normalized_name': 'zerodiscmed 100mg tab',
                'dosage': '100mg',
                'unit_size': '10 Tab',
                'base_price': 30.0,
                'discount_rate': 0.15,
                'stock_status': True,
            },
        ])

    @pytest.fixture
    def mock_reference_discounts(self):
        """Constructs reference inventory with various discount comparison scenarios."""
        return pd.DataFrame([
            # 1. Panadol Extra: catalog max = 0.45, ref = 0.30 -> Gain +0.15 (Above average)
            {'raw_name': 'xxPanadol Extra 24 Tabxx', 'clean_name': 'Panadol Extra 24 Tab', 'avg_discount_rate': 0.30},
            # 2. Cataflam 50mg: catalog max = 0.25, ref = 0.25 -> Equal (Must be EXCLUDED)
            {'raw_name': 'Cataflam 50mg 20 Tab', 'clean_name': 'Cataflam 50mg 20 Tab', 'avg_discount_rate': 0.25},
            # 3. Augmentin 1gm: catalog max = 0.30, ref = 0.35 -> Below average (Must be EXCLUDED)
            {'raw_name': 'Augmentin 1gm 14 Tab', 'clean_name': 'Augmentin 1gm 14 Tab', 'avg_discount_rate': 0.35},
            # 4. Brufen 400mg: catalog max = 0.20, ref = 0.10 -> Gain +0.10 (Above average)
            {'raw_name': 'Brufen 400mg 30 Tab', 'clean_name': 'Brufen 400mg 30 Tab', 'avg_discount_rate': 0.10},
            # 5. Zero-discount reference edge case: catalog max = 0.15, ref = 0.0 -> Gain +0.15 (Above average)
            {'raw_name': 'ZeroDiscMed 100mg Tab', 'clean_name': 'ZeroDiscMed 100mg Tab', 'avg_discount_rate': 0.0},
            # 6. Unmatched medication not in catalog -> EXCLUDED
            {'raw_name': 'NonExistentMed 500mg', 'clean_name': 'NonExistentMed 500mg', 'avg_discount_rate': 0.20},
        ])

    def test_candidate_lookup_and_clinical_safety_matching(self, mock_catalog_inventory):
        """Clinical safety gates strictly prevent strength and form cross-substitution."""
        allocator = MedicineAllocator(mock_catalog_inventory, enable_ai=False)

        # 1. Direct safety gate assertions
        assert is_safe_pharmaceutical_match("Panadol Extra 24 Tab", "Panadol Extra 24 Tab") is True
        # Strength mismatch: 50mg must not match 25mg
        assert is_safe_pharmaceutical_match("Cataflam 50mg 20 Tab", "Cataflam 25mg 20 Tab") is False
        # Ratio / strength mismatch: 1gm must not match 500mg
        assert is_safe_pharmaceutical_match("Augmentin 1gm 14 Tab", "Augmentin 500mg 14 Tab") is False

        # 2. Candidate lookup in allocator strictly honors clinical safety
        candidates_cataflam = allocator._find_safe_candidates("Cataflam 50mg 20 Tab")
        assert len(candidates_cataflam) > 0
        for cand_item in candidates_cataflam['item_name']:
            assert "25mg" not in cand_item, f"Unsafe candidate matched: {cand_item}"

        candidates_augmentin = allocator._find_safe_candidates("Augmentin 1gm 14 Tab")
        assert len(candidates_augmentin) > 0
        for cand_item in candidates_augmentin['item_name']:
            assert "500mg" not in cand_item, f"Unsafe candidate matched: {cand_item}"

    def test_strict_inequality_filtering_and_exclusion(self, mock_catalog_inventory, mock_reference_discounts):
        """evaluate_above_average_discounts includes items if and only if max_disc > ref_disc."""
        allocator = MedicineAllocator(mock_catalog_inventory, enable_ai=False)
        result_df = evaluate_above_average_discounts(mock_reference_discounts, allocator)

        assert not result_df.empty
        matched_items = result_df['اسم الصنف في أرصده المخازن'].tolist()

        # Above average items MUST be included
        assert 'Panadol Extra 24 Tab' in matched_items
        assert 'Brufen 400mg 30 Tab' in matched_items
        assert 'ZeroDiscMed 100mg Tab' in matched_items

        # Equal (Cataflam 0.25 == 0.25) and lower (Augmentin 0.30 < 0.35) MUST be excluded
        assert 'Cataflam 50mg 20 Tab' not in matched_items
        assert 'Augmentin 1gm 14 Tab' not in matched_items
        assert 'NonExistentMed 500mg' not in matched_items

        # 100% of rows must satisfy max_disc > ref_disc
        for _, row in result_df.iterrows():
            assert row['أعلى خصم متاح %'] > row['الخصم المرجح %'], (
                f"Strict inequality violated: {row['أعلى خصم متاح %']} <= {row['الخصم المرجح %']}"
            )
            assert row['فرق الخصم %'] == round(row['أعلى خصم متاح %'] - row['الخصم المرجح %'], 4)

    def test_descending_sort_order_by_diff_discount(self, mock_catalog_inventory, mock_reference_discounts):
        """Rows in above_average_discounts are strictly sorted descending by فرق الخصم %."""
        allocator = MedicineAllocator(mock_catalog_inventory, enable_ai=False)
        result_df = evaluate_above_average_discounts(mock_reference_discounts, allocator)

        diffs = result_df['فرق الخصم %'].tolist()
        assert len(diffs) >= 3
        assert diffs == sorted(diffs, reverse=True), f"Not sorted descending: {diffs}"

        # Serial numbers must be 1-based sequential integers
        assert list(result_df['م']) == list(range(1, len(result_df) + 1))

    def test_winning_supplier_offer_details(self, mock_catalog_inventory, mock_reference_discounts):
        """Winning offer contains correct warehouse, clean names, unit public price, and unit net price."""
        allocator = MedicineAllocator(mock_catalog_inventory, enable_ai=False)
        result_df = evaluate_above_average_discounts(mock_reference_discounts, allocator)

        panadol_row = result_df[result_df['اسم الصنف في أرصده المخازن'] == 'Panadol Extra 24 Tab'].iloc[0]
        # Winning warehouse is مخزن الفرسان بنها offering 0.45 (higher than السلام 0.40)
        assert panadol_row['المخزن الفائز'] == 'مخزن الفرسان بنها'
        assert panadol_row['أعلى خصم متاح %'] == 0.45
        assert panadol_row['الخصم المرجح %'] == 0.30
        assert panadol_row['فرق الخصم %'] == 0.15
        assert panadol_row['سعر الجمهور للوحدة'] == 50.0
        assert panadol_row['سعر التوريد الصافي'] == round(50.0 * (1.0 - 0.45), 2)

        # Per warehouse columns
        assert 'خصم مخزن الفرسان بنها' in panadol_row
        assert 'خصم مخزن السلام فارم' in panadol_row
        assert panadol_row['خصم مخزن الفرسان بنها'] == 0.45
        assert panadol_row['خصم مخزن السلام فارم'] == 0.40

    def test_master_comparison_daily_purchase_order_enrichment(self, mock_catalog_inventory, mock_reference_discounts):
        """allocate_order enriches master_comparison with Columns 12 (الخصم المرجح %) & 13 (فرق الخصم %)."""
        allocator = MedicineAllocator(
            mock_catalog_inventory,
            enable_ai=False,
            avg_discounts_df=mock_reference_discounts
        )

        buying_order = pd.DataFrame([
            {'requested_item': 'Panadol Extra 24 Tab', 'quantity': 10},
            {'requested_item': 'Cataflam 50mg 20 Tab', 'quantity': 5},
            {'requested_item': 'Augmentin 500mg 14 Tab', 'quantity': 2},
        ])

        results = allocator.allocate_order(buying_order)
        master_df = results['master_comparison']

        assert 'الخصم المرجح %' in master_df.columns
        assert 'فرق الخصم %' in master_df.columns

        # Item present in reference (Panadol: max 0.45, ref 0.30 -> diff 0.15)
        p_row = master_df[master_df['اسم الصنف المطلوب (في طلب الشراء)'].str.contains('Panadol')].iloc[0]
        assert p_row['الخصم المرجح %'] == 0.30
        assert p_row['فرق الخصم %'] == 0.15

        # Item present in reference with equal discount (Cataflam: max 0.25, ref 0.25 -> diff 0.0)
        c_row = master_df[master_df['اسم الصنف المطلوب (في طلب الشراء)'].str.contains('Cataflam')].iloc[0]
        assert c_row['الخصم المرجح %'] == 0.25
        assert c_row['فرق الخصم %'] == 0.0

        # Item present in catalog but absent from reference dataset defaults to '-'
        absent_row = master_df[master_df['اسم الصنف المطلوب (في طلب الشراء)'].str.contains('Augmentin 500mg')].iloc[0]
        assert absent_row['الخصم المرجح %'] == '-'
        assert absent_row['فرق الخصم %'] == '-'


# ============================================================================
# Requirement R3: RTL Multi-Sheet Excel Reports & Accounting Formulas
# ============================================================================

class TestRequirementR3ExcelReportingAndAccounting:
    """Verifies R3: dual workbooks, 100% RTL, above-average worksheet styling, placeholder resilience, and formulas."""

    EXPECTED_COLS_1_TO_11 = [
        'م',
        'اسم الصنف المطلوب (في طلب الشراء)',
        'اسم الصنف في كشف المخزن الفائز',
        'الكمية',
        'المخزن الفائز',
        'أعلى خصم %',
        'سعر الجمهور',
        'سعر الشراء للوحدة',
        'إجمالي سعر الجمهور',
        'إجمالي تكلفة الشراء',
        'قيمة الوفر'
    ]

    @pytest.fixture
    def sample_report_payload(self):
        """Constructs complete report payload with Master Comparison, Above Average, and Supplier sheets."""
        master_rows = []
        for i in range(1, 5):
            master_rows.append({
                'م': i,
                'اسم الصنف المطلوب (في طلب الشراء)': f'دواء اختباري {i}',
                'اسم الصنف في كشف المخزن الفائز': f'دواء فائز {i}',
                'الكمية': 10 * i,
                'المخزن الفائز': 'مخزن السلام فارم' if i % 2 == 1 else 'مخزن الفرسان بنها',
                'أعلى خصم %': 0.20 + (i * 0.05),
                'سعر الجمهور': 100.0 * i,
                'سعر الشراء للوحدة': 100.0 * i * (1.0 - (0.20 + (i * 0.05))),
                'إجمالي سعر الجمهور': (100.0 * i) * (10 * i),
                'إجمالي تكلفة الشراء': (100.0 * i * (1.0 - (0.20 + (i * 0.05)))) * (10 * i),
                'قيمة الوفر': ((100.0 * i) * (10 * i)) - ((100.0 * i * (1.0 - (0.20 + (i * 0.05)))) * (10 * i)),
                'الخصم المرجح %': 0.15 + (i * 0.02) if i <= 3 else '-',
                'فرق الخصم %': round((0.20 + (i * 0.05)) - (0.15 + (i * 0.02)), 4) if i <= 3 else '-',
                'خصم مخزن السلام فارم': 0.20 + (i * 0.05) if i % 2 == 1 else 0.15,
                'خصم مخزن الفرسان بنها': 0.20 + (i * 0.05) if i % 2 == 0 else 0.10,
            })
        master_df = pd.DataFrame(master_rows)

        above_rows = []
        for i in range(1, 4):
            above_rows.append({
                'م': i,
                'اسم الصنف في أرصده المخازن': f'صنف أرصدة {i}',
                'اسم الصنف في كشف المخزن الفائز': f'صنف كتالوج {i}',
                'المخزن الفائز': 'مخزن السلام فارم',
                'الخصم المرجح %': 0.20,
                'أعلى خصم متاح %': 0.35 - (i * 0.03),
                'فرق الخصم %': round(0.15 - (i * 0.03), 4),
                'سعر الجمهور للوحدة': 80.0,
                'سعر التوريد الصافي': 52.0,
                'خصم مخزن السلام فارم': 0.35 - (i * 0.03),
                'خصم مخزن الفرسان بنها': 0.26,
            })
        above_df = pd.DataFrame(above_rows)

        supplier_order_df = pd.DataFrame([
            {'م': 1, 'اسم الصنف المطلوب': 'دواء اختباري 1', 'اسم الصنف في كشف المخزن': 'دواء فائز 1',
             'الكمية': 10, 'سعر الجمهور': 100.0, 'نسبة الخصم': 0.25, 'سعر الشراء': 75.0, 'الإجمالي': 750.0}
        ])

        return {
            'kpis': {'total_items': 4, 'matched_items': 4, 'unmatched_items': 0, 'total_savings': 500.0},
            'master_comparison': master_df,
            'above_average_discounts': above_df,
            'allocated_orders': {
                'مخزن السلام فارم': supplier_order_df,
                'مخزن الفرسان بنها': supplier_order_df
            },
            'unmatched_items': pd.DataFrame()
        }

    def test_dual_workbook_generation_and_sheet_parity(self, sample_report_payload):
        """ArabicExcelReportGenerator produces both primary and Arabic workbooks with no standalone discounts sheet."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            generator = ArabicExcelReportGenerator(sample_report_payload, output_dir=tmp_dir)
            primary_path = generator.generate(custom_date_str="2026-10-18")

            # Check primary workbook
            assert os.path.isfile(primary_path)
            assert "Procurement_Order_Optimized_2026-10-18.xlsx" in os.path.basename(primary_path)

            # Check Arabic workbook
            arabic_name = f"أفضل_اسعار_2026-10-18.xlsx"
            arabic_path = os.path.join(tmp_dir, arabic_name)
            assert os.path.isfile(arabic_path)

            wb_primary = openpyxl.load_workbook(primary_path)
            wb_arabic = openpyxl.load_workbook(arabic_path)

            # Assert identical sheets
            assert wb_primary.sheetnames == wb_arabic.sheetnames
            assert "المقارنة الشاملة وتوزيع الأصناف" in wb_primary.sheetnames
            # R1: Standalone discounts sheet must NOT exist
            assert "أصناف بخصم أعلى من المرجح" not in wb_primary.sheetnames
            assert "أصناف بخصم أعلى من المرجح" not in wb_arabic.sheetnames

    def test_right_to_left_on_100_percent_of_sheets_in_both_workbooks(self, sample_report_payload):
        """ws.views.sheetView[0].rightToLeft is True on 100% of sheets in both workbooks."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            generator = ArabicExcelReportGenerator(sample_report_payload, output_dir=tmp_dir)
            primary_path = generator.generate(custom_date_str="2026-10-18")
            arabic_path = os.path.join(tmp_dir, "أفضل_اسعار_2026-10-18.xlsx")

            for wb_path in [primary_path, arabic_path]:
                wb = openpyxl.load_workbook(wb_path)
                for sheetname in wb.sheetnames:
                    ws = wb[sheetname]
                    assert ws.views.sheetView[0].rightToLeft is True, (
                        f"Sheet '{sheetname}' in {os.path.basename(wb_path)} does not have rightToLeft = True"
                    )

    def test_per_warehouse_above_average_discounts_secondary_table_and_styling(self, sample_report_payload):
        """
        R2 & R3: Warehouse PO sheets render secondary above-average discount table
        with Soft Green (winning) and Soft Yellow (competing) highlights.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            generator = ArabicExcelReportGenerator(sample_report_payload, output_dir=tmp_dir)
            primary_path = generator.generate(custom_date_str="2026-10-18")

            wb = openpyxl.load_workbook(primary_path)

            # 1. Inspect winning warehouse sheet (مخزن السلام فارم)
            ws_salam = None
            for sname in wb.sheetnames:
                if "السلام" in sname:
                    ws_salam = wb[sname]
                    break
            assert ws_salam is not None, "Winning warehouse PO sheet not found"

            # Find secondary table header row
            expected_sec_headers = [
                'م', 'اسم الصنف في أرصدة المخازن', 'اسم الصنف في الكتالوج',
                'سعر الجمهور للوحدة', 'الخصم المرجح %', 'خصم هذا المخزن %',
                'أعلى خصم متاح %', 'المخزن صاحب أعلى خصم', 'فرق السعر (الوفر بالجنيه)'
            ]

            sec_header_row_salam = None
            for r in range(1, ws_salam.max_row + 1):
                if ws_salam.cell(row=r, column=1).value == 'م' and ws_salam.cell(row=r, column=2).value == 'اسم الصنف في أرصدة المخازن':
                    sec_header_row_salam = r
                    break

            assert sec_header_row_salam is not None, "Secondary table headers not found on Salam sheet"
            for c_i, exp_h in enumerate(expected_sec_headers, 1):
                assert ws_salam.cell(row=sec_header_row_salam, column=c_i).value == exp_h

            # Salam is winner: status cell (Col 8) must have Soft Green fill (#E2EFDA / text #375623)
            data_row_1 = sec_header_row_salam + 1
            cell_status_salam = ws_salam.cell(row=data_row_1, column=8)
            assert cell_status_salam.fill.start_color.rgb in ['E2EFDA', '00E2EFDA', 'FFE2EFDA']
            assert cell_status_salam.font.color.rgb in ['375623', '00375623', 'FF375623']
            assert ws_salam.cell(row=data_row_1, column=9).value >= 4.00

            # 2. Inspect non-winning warehouse sheet (مخزن الفرسان بنها)
            ws_forsan = None
            for sname in wb.sheetnames:
                if "الفرسان" in sname:
                    ws_forsan = wb[sname]
                    break
            assert ws_forsan is not None, "Competing warehouse PO sheet not found"

            sec_header_row_forsan = None
            for r in range(1, ws_forsan.max_row + 1):
                if ws_forsan.cell(row=r, column=1).value == 'م' and ws_forsan.cell(row=r, column=2).value == 'اسم الصنف في أرصدة المخازن':
                    sec_header_row_forsan = r
                    break

            assert sec_header_row_forsan is not None, "Secondary table headers not found on Forsan sheet"
            data_row_forsan_1 = sec_header_row_forsan + 1
            cell_status_forsan = ws_forsan.cell(row=data_row_forsan_1, column=8)

            # Forsan is not winner: status cell (Col 8) must have Soft Yellow fill (#FFF2CC / text #7F6000)
            assert cell_status_forsan.fill.start_color.rgb in ['FFF2CC', '00FFF2CC', 'FFFFF2CC']
            assert cell_status_forsan.font.color.rgb in ['7F6000', '007F6000', 'FF7F6000']
            # Must display winning warehouse and rate
            assert "السلام" in str(cell_status_forsan.value)
            assert "%" in str(cell_status_forsan.value)
            assert ws_forsan.cell(row=data_row_forsan_1, column=9).value >= 4.00

    def test_sub_4egp_saving_items_strictly_excluded(self, sample_report_payload):
        """R2: Items with saving < 4.00 EGP are strictly excluded from the secondary table."""
        payload = dict(sample_report_payload)
        # Add item with saving < 4.00 EGP (Base price 20, disc 0.20, ref 0.15 -> 20 * 0.05 = 1.00 EGP < 4.00)
        low_saving_item = {
            'م': 4,
            'اسم الصنف في أرصده المخازن': 'دواء منخفض الوفر',
            'اسم الصنف في كشف المخزن الفائز': 'صنف منخفض الوفر',
            'المخزن الفائز': 'مخزن السلام فارم',
            'الخصم المرجح %': 0.15,
            'أعلى خصم متاح %': 0.20,
            'فرق الخصم %': 0.05,
            'سعر الجمهور للوحدة': 20.0,
            'سعر التوريد الصافي': 16.0,
            'خصم مخزن السلام فارم': 0.20,
            'خصم مخزن الفرسان بنها': 0.18
        }
        above_df_mod = pd.concat([sample_report_payload['above_average_discounts'], pd.DataFrame([low_saving_item])], ignore_index=True)
        payload['above_average_discounts'] = above_df_mod

        with tempfile.TemporaryDirectory() as tmp_dir:
            generator = ArabicExcelReportGenerator(payload, output_dir=tmp_dir)
            primary_path = generator.generate(custom_date_str="2026-10-18")

            wb = openpyxl.load_workbook(primary_path)
            for sname in wb.sheetnames:
                if "طلب شراء" in sname:
                    ws = wb[sname]
                    # Verify low-saving item is not present in secondary table
                    sec_hdr = None
                    for r in range(1, ws.max_row + 1):
                        if ws.cell(row=r, column=1).value == 'م' and ws.cell(row=r, column=2).value == 'اسم الصنف في أرصدة المخازن':
                            sec_hdr = r
                            break
                    if sec_hdr:
                        for r in range(sec_hdr + 1, ws.max_row + 1):
                            val = ws.cell(row=r, column=2).value
                            assert val != 'دواء منخفض الوفر'
                            saving_val = ws.cell(row=r, column=9).value
                            if isinstance(saving_val, (int, float)):
                                assert saving_val >= 4.00

    def test_above_average_sheet_empty_and_none_resilience(self, sample_report_payload):
        """Clean notice message row is rendered without error when no items meet >= 4.00 EGP."""
        for empty_val in [None, pd.DataFrame()]:
            with tempfile.TemporaryDirectory() as tmp_dir:
                payload = dict(sample_report_payload)
                payload['above_average_discounts'] = empty_val

                generator = ArabicExcelReportGenerator(payload, output_dir=tmp_dir)
                primary_path = generator.generate(custom_date_str="2026-10-18")
                assert os.path.isfile(primary_path)

                wb = openpyxl.load_workbook(primary_path)
                assert "أصناف بخصم أعلى من المرجح" not in wb.sheetnames

                # Check PO sheets for clean notice row
                for sname in wb.sheetnames:
                    if "طلب شراء" in sname:
                        ws = wb[sname]
                        # Locate secondary table
                        sec_hdr = None
                        for r in range(1, ws.max_row + 1):
                            if ws.cell(row=r, column=1).value == 'م' and ws.cell(row=r, column=2).value == 'اسم الصنف في أرصدة المخازن':
                                sec_hdr = r
                                break
                        assert sec_hdr is not None
                        notice_cell = ws.cell(row=sec_hdr + 1, column=1)
                        assert "لا توجد أصناف إضافية" in str(notice_cell.value)
                        sum_cell = ws.cell(row=sec_hdr + 2, column=2)
                        assert "إجمالي الأصناف: 0 صنف" in str(sum_cell.value)

    def test_master_comparison_column_preservation_and_structure(self, sample_report_payload):
        """Columns 1–11 are strictly preserved in original order, Col 12 is الخصم المرجح %, Col 13 is فرق الخصم %."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            generator = ArabicExcelReportGenerator(sample_report_payload, output_dir=tmp_dir)
            primary_path = generator.generate(custom_date_str="2026-10-18")

            wb = openpyxl.load_workbook(primary_path)
            ws = wb["المقارنة الشاملة وتوزيع الأصناف"]

            headers = [ws.cell(row=8, column=c).value for c in range(1, ws.max_column + 1)]
            headers = [h for h in headers if h is not None]

            # Verify Columns 1–11 exact strings and order
            for idx, expected_h in enumerate(self.EXPECTED_COLS_1_TO_11, 1):
                assert headers[idx - 1] == expected_h, (
                    f"Col {idx} header mismatch: expected '{expected_h}', got '{headers[idx - 1]}'"
                )

            # Verify Col 12 and Col 13
            assert headers[11] == 'الخصم المرجح %'
            assert headers[12] == 'فرق الخصم %'

            # Warehouse columns start at Column 14 (Column N)
            assert headers[13].startswith('خصم ')
            assert headers[14].startswith('خصم ')

    def test_master_comparison_accounting_formula_preservation(self, sample_report_payload):
        """Summary row in Master Comparison strictly preserves =SUM() formulas in columns D, I, J, K."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            generator = ArabicExcelReportGenerator(sample_report_payload, output_dir=tmp_dir)
            primary_path = generator.generate(custom_date_str="2026-10-18")

            wb = openpyxl.load_workbook(primary_path)
            ws = wb["المقارنة الشاملة وتوزيع الأصناف"]

            # Data rows: 9 to 12 (4 items). Summary row: 13
            sum_row = 13
            assert ws.cell(row=sum_row, column=2).value == "الإجمالي العام"

            # Check accounting formulas
            formula_d = ws.cell(row=sum_row, column=4).value
            formula_i = ws.cell(row=sum_row, column=9).value
            formula_j = ws.cell(row=sum_row, column=10).value
            formula_k = ws.cell(row=sum_row, column=11).value

            assert formula_d == "=SUM(D9:D12)", f"Quantity formula mismatch: {formula_d}"
            assert formula_i == "=SUM(I9:I12)", f"Public price formula mismatch: {formula_i}"
            assert formula_j == "=SUM(J9:J12)", f"Cost formula mismatch: {formula_j}"
            assert formula_k == "=SUM(K9:K12)", f"Savings formula mismatch: {formula_k}"

            # Columns 12 and 13 do NOT contain formulas
            cell_l = ws.cell(row=sum_row, column=12).value
            cell_m = ws.cell(row=sum_row, column=13).value
            assert cell_l is None or not str(cell_l).startswith("="), f"Col 12 formula leak: {cell_l}"
            assert cell_m is None or not str(cell_m).startswith("="), f"Col 13 formula leak: {cell_m}"
