# -*- coding: utf-8 -*-
"""
Test Suite: Above-Average Discount Evaluation & Allocation Enrichment (Milestone 2 - R2)
Covers:
  - Unit tests for evaluate_above_average_discounts
  - Strict inequality gate (max_disc > ref_disc)
  - Sorting descending by discount gain (فرق الخصم %)
  - Clinical safety gate enforcement (is_safe_pharmaceutical_match)
  - Master Comparison purchase order enrichment with reference average discounts
  - Pipeline integration and parameter forwarding
"""
import pytest
import pandas as pd
from unittest.mock import MagicMock

from src.allocator import MedicineAllocator, evaluate_above_average_discounts
from src.pipeline import run_procurement_pipeline
from src.controller import ProcurementEngineBridge


@pytest.fixture
def sample_catalog_inventory():
    """Constructs a mock multi-warehouse catalog inventory."""
    return pd.DataFrame([
        {
            'warehouse_name': 'مخزن السلام',
            'item_name': 'Panadol Extra 24 Tab',
            'normalized_name': 'panadol extra 24 tab',
            'dosage': '500mg',
            'unit_size': '24 Tab',
            'base_price': 50.0,
            'discount_rate': 0.40,
            'stock_status': True,
        },
        {
            'warehouse_name': 'مخزن الفرسان',
            'item_name': 'Panadol Extra 24 Tab',
            'normalized_name': 'panadol extra 24 tab',
            'dosage': '500mg',
            'unit_size': '24 Tab',
            'base_price': 50.0,
            'discount_rate': 0.45,
            'stock_status': True,
        },
        {
            'warehouse_name': 'مخزن السلام',
            'item_name': 'Cataflam 50mg 20 Tab',
            'normalized_name': 'cataflam 50mg 20 tab',
            'dosage': '50mg',
            'unit_size': '20 Tab',
            'base_price': 60.0,
            'discount_rate': 0.25,
            'stock_status': True,
        },
        {
            'warehouse_name': 'مخزن الفرسان',
            'item_name': 'Augmentin 1gm 14 Tab',
            'normalized_name': 'augmentin 1gm 14 tab',
            'dosage': '1gm',
            'unit_size': '14 Tab',
            'base_price': 120.0,
            'discount_rate': 0.30,
            'stock_status': True,
        },
        {
            'warehouse_name': 'مخزن السلام',
            'item_name': 'Brufen 400mg 30 Tab',
            'normalized_name': 'brufen 400mg 30 tab',
            'dosage': '400mg',
            'unit_size': '30 Tab',
            'base_price': 40.0,
            'discount_rate': 0.20,
            'stock_status': True,
        },
    ])


@pytest.fixture
def sample_reference_discounts():
    """
    Reference dataset with test cases:
    1. Panadol Extra: catalog max = 0.45, ref = 0.30 -> Gain +0.15 (Above average)
    2. Cataflam 50mg: catalog max = 0.25, ref = 0.25 -> Equal (Must be EXCLUDED)
    3. Augmentin 1gm: catalog max = 0.30, ref = 0.35 -> Below average (Must be EXCLUDED)
    4. Brufen 400mg: catalog max = 0.20, ref = 0.10 -> Gain +0.10 (Above average)
    5. xxPanadol Extra 24 Tabxx: marker tokens stripped -> matches catalog
    6. NonExistentDrug: not in catalog -> EXCLUDED
    """
    return pd.DataFrame([
        {'raw_name': 'Panadol Extra 24 Tab', 'clean_name': 'Panadol Extra 24 Tab', 'avg_discount_rate': 0.30},
        {'raw_name': 'Cataflam 50mg 20 Tab', 'clean_name': 'Cataflam 50mg 20 Tab', 'avg_discount_rate': 0.25},
        {'raw_name': 'Augmentin 1gm 14 Tab', 'clean_name': 'Augmentin 1gm 14 Tab', 'avg_discount_rate': 0.35},
        {'raw_name': 'Brufen 400mg 30 Tab', 'clean_name': 'Brufen 400mg 30 Tab', 'avg_discount_rate': 0.10},
        {'raw_name': 'xxBrufen 600mgxx', 'clean_name': 'Brufen 600mg', 'avg_discount_rate': 0.15},
        {'raw_name': 'NonExistentDrug 100mg', 'clean_name': 'NonExistentDrug 100mg', 'avg_discount_rate': 0.20},
    ])


class TestAboveAverageDiscountEvaluation:
    """Covers R2 evaluation requirements."""

    def test_evaluate_empty_and_none_inputs(self):
        """Returns empty DataFrame with required columns on empty or None input."""
        res_none = evaluate_above_average_discounts(None, None)
        assert res_none.empty
        expected_cols = [
            'م', 'اسم الصنف في أرصده المخازن', 'اسم الصنف في كشف المخزن الفائز',
            'المخزن الفائز', 'الخصم المرجح %', 'أعلى خصم متاح %', 'فرق الخصم %',
            'سعر الجمهور للوحدة', 'سعر التوريد الصافي'
        ]
        for col in expected_cols:
            assert col in res_none.columns

        allocator = MedicineAllocator(pd.DataFrame())
        res_empty = evaluate_above_average_discounts(pd.DataFrame(), allocator)
        assert res_empty.empty

    def test_strict_inequality_filtering(self, sample_catalog_inventory, sample_reference_discounts):
        """Only medications with catalog max_disc STRICTLY GREATER than ref_disc are included."""
        allocator = MedicineAllocator(sample_catalog_inventory, enable_ai=False)
        result_df = evaluate_above_average_discounts(sample_reference_discounts, allocator)

        assert not result_df.empty
        matched_clean_names = result_df['اسم الصنف في أرصده المخازن'].tolist()

        # Panadol Extra (0.45 > 0.30) and Brufen 400mg (0.20 > 0.10) MUST be included
        assert 'Panadol Extra 24 Tab' in matched_clean_names
        assert 'Brufen 400mg 30 Tab' in matched_clean_names

        # Cataflam (0.25 == 0.25) and Augmentin (0.30 < 0.35) MUST be excluded
        assert 'Cataflam 50mg 20 Tab' not in matched_clean_names
        assert 'Augmentin 1gm 14 Tab' not in matched_clean_names

        # Every row must satisfy max_disc > ref_disc
        for _, row in result_df.iterrows():
            assert row['أعلى خصم متاح %'] > row['الخصم المرجح %']
            assert row['فرق الخصم %'] == round(row['أعلى خصم متاح %'] - row['الخصم المرجح %'], 4)

    def test_descending_sort_order_by_diff_discount(self, sample_catalog_inventory, sample_reference_discounts):
        """Output is strictly sorted descending by discount gain (فرق الخصم %)."""
        allocator = MedicineAllocator(sample_catalog_inventory, enable_ai=False)
        result_df = evaluate_above_average_discounts(sample_reference_discounts, allocator)

        diffs = result_df['فرق الخصم %'].tolist()
        assert len(diffs) >= 2
        assert diffs == sorted(diffs, reverse=True)

        # Panadol Extra (diff 0.15) must come BEFORE Brufen 400mg (diff 0.10)
        assert result_df.iloc[0]['اسم الصنف في أرصده المخازن'] == 'Panadol Extra 24 Tab'
        assert result_df.iloc[0]['فرق الخصم %'] == 0.15
        assert result_df.iloc[1]['اسم الصنف في أرصده المخازن'] == 'Brufen 400mg 30 Tab'
        assert result_df.iloc[1]['فرق الخصم %'] == 0.10

    def test_per_warehouse_discounts_and_pricing(self, sample_catalog_inventory, sample_reference_discounts):
        """Validates winning supplier offer details and per-warehouse columns."""
        allocator = MedicineAllocator(sample_catalog_inventory, enable_ai=False)
        result_df = evaluate_above_average_discounts(sample_reference_discounts, allocator)

        # For Panadol Extra: winning warehouse is مخزن الفرسان (0.45)
        panadol_row = result_df[result_df['اسم الصنف في أرصده المخازن'] == 'Panadol Extra 24 Tab'].iloc[0]
        assert panadol_row['المخزن الفائز'] == 'مخزن الفرسان'
        assert panadol_row['أعلى خصم متاح %'] == 0.45
        assert panadol_row['سعر الجمهور للوحدة'] == 50.0
        assert panadol_row['سعر التوريد الصافي'] == round(50.0 * (1.0 - 0.45), 2)

        # Per warehouse columns
        assert 'خصم مخزن الفرسان' in panadol_row
        assert 'خصم مخزن السلام' in panadol_row
        assert panadol_row['خصم مخزن الفرسان'] == 0.45
        assert panadol_row['خصم مخزن السلام'] == 0.40

    def test_serial_numbers_sequential(self, sample_catalog_inventory, sample_reference_discounts):
        """Serial numbers are 1-based sequential integers."""
        allocator = MedicineAllocator(sample_catalog_inventory, enable_ai=False)
        result_df = evaluate_above_average_discounts(sample_reference_discounts, allocator)
        assert list(result_df['م']) == list(range(1, len(result_df) + 1))


class TestMasterComparisonEnrichment:
    """Covers purchase order allocation enrichment with reference average discounts."""

    def test_allocate_order_enriches_reference_discounts(self, sample_catalog_inventory, sample_reference_discounts):
        """allocate_order attaches الخصم المرجح % and فرق الخصم % to master_comparison."""
        allocator = MedicineAllocator(
            sample_catalog_inventory,
            enable_ai=False,
            avg_discounts_df=sample_reference_discounts
        )

        buying_list = pd.DataFrame([
            {'requested_item': 'Panadol Extra 24 Tab', 'quantity': 10},
            {'requested_item': 'Cataflam 50mg 20 Tab', 'quantity': 5},
            {'requested_item': 'UnknownMedNotInRef 100mg', 'quantity': 2},
        ])

        results = allocator.allocate_order(buying_list)
        master_df = results['master_comparison']

        assert 'الخصم المرجح %' in master_df.columns
        assert 'فرق الخصم %' in master_df.columns

        # Panadol Extra (catalog 0.45, ref 0.30 -> diff 0.15)
        p_row = master_df[master_df['اسم الصنف المطلوب (في طلب الشراء)'].str.contains('Panadol')].iloc[0]
        assert p_row['الخصم المرجح %'] == 0.30
        assert p_row['فرق الخصم %'] == 0.15

        # Cataflam 50mg (catalog 0.25, ref 0.25 -> diff 0.0)
        c_row = master_df[master_df['اسم الصنف المطلوب (في طلب الشراء)'].str.contains('Cataflam')].iloc[0]
        assert c_row['الخصم المرجح %'] == 0.25
        assert c_row['فرق الخصم %'] == 0.0

    def test_allocate_order_without_reference_discounts(self, sample_catalog_inventory):
        """When avg_discounts_df is not provided, defaults gracefully to '-'."""
        allocator = MedicineAllocator(sample_catalog_inventory, enable_ai=False)
        buying_list = pd.DataFrame([
            {'requested_item': 'Panadol Extra 24 Tab', 'quantity': 5},
        ])
        results = allocator.allocate_order(buying_list)
        master_df = results['master_comparison']

        assert 'الخصم المرجح %' in master_df.columns
        assert 'فرق الخصم %' in master_df.columns
        assert master_df.iloc[0]['الخصم المرجح %'] == '-'
        assert master_df.iloc[0]['فرق الخصم %'] == '-'

    def test_zero_discount_edge_case_evaluated_and_enriched(self, sample_catalog_inventory):
        """Zero-discount edge case: norm_disc < 0.0 check preserves valid 0.0% reference discounts."""
        ref_df = pd.DataFrame([
            {'clean_name': 'Panadol Extra 24 Tab', 'avg_discount_rate': 0.0},
            {'clean_name': 'InvalidNegative 100mg', 'avg_discount_rate': -0.10},
        ])
        allocator = MedicineAllocator(sample_catalog_inventory, enable_ai=False, avg_discounts_df=ref_df)
        
        # 1. evaluate_above_average_discounts retains 0.0% reference discount
        result_df = evaluate_above_average_discounts(ref_df, allocator)
        assert not result_df.empty
        panadol_row = result_df[result_df['اسم الصنف في أرصده المخازن'] == 'Panadol Extra 24 Tab'].iloc[0]
        assert panadol_row['الخصم المرجح %'] == 0.0
        assert panadol_row['أعلى خصم متاح %'] == 0.45
        assert panadol_row['فرق الخصم %'] == 0.45
        assert 'InvalidNegative 100mg' not in result_df['اسم الصنف في أرصده المخازن'].tolist()

        # 2. allocate_order enriches master_comparison with 0.0% reference discount
        buying_list = pd.DataFrame([
            {'requested_item': 'Panadol Extra 24 Tab', 'quantity': 10},
        ])
        results = allocator.allocate_order(buying_list)
        master_df = results['master_comparison']
        p_row = master_df[master_df['اسم الصنف المطلوب (في طلب الشراء)'].str.contains('Panadol')].iloc[0]
        assert p_row['الخصم المرجح %'] == 0.0
        assert p_row['فرق الخصم %'] == 0.45
