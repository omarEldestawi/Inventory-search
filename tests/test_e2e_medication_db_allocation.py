# -*- coding: utf-8 -*-
"""
End-to-End Test for Medication Knowledge Base & Dynamic Discount Allocation.
Verifies that:
1. Aliases and standard entities resolve correctly.
2. Tier 0 standard ID matching in MedicineAllocator selects highest discount across vendors.
3. Static drug identity is decoupled from changing vendor discount rates.
"""
import os
import pytest
import tempfile
import pandas as pd
from src.medication_db import MedicationDB
from src.allocator import MedicineAllocator


@pytest.fixture
def populated_test_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_alloc_meds.db")
        db = MedicationDB(db_path)

        # Drug 1: Concor 10mg
        concor_id = db.add_standard_medication(
            canonical_name="كونكور 10 مجم اقراص",
            canonical_brand="concor",
            form_category="SOLID_ORAL",
            strength="10mg"
        )
        db.register_alias(concor_id, "CONCOR 10MG TAB", source="vendor_english")
        db.register_alias(concor_id, "كونكور 10 مجم 30 قرص", source="pharmacy_po")
        db.register_alias(concor_id, "ركونوك 10 مجم", source="reversed_pdf")

        # Drug 2: Cataflam 50mg
        cataflam_id = db.add_standard_medication(
            canonical_name="كتافلام 50 مجم اقراص",
            canonical_brand="cataflam",
            form_category="SOLID_ORAL",
            strength="50mg"
        )
        db.register_alias(cataflam_id, "كتافلام 50 مجم", source="pharmacy_po")
        db.register_alias(cataflam_id, "CATAFLAM 50MG", source="vendor_english")
        db.register_alias(cataflam_id, "مالفاتك 50", source="reversed_pdf")

        try:
            yield db
        finally:
            db.close()


def test_allocation_with_medication_db(populated_test_db):
    """
    Test scenario:
    Two wholesalers offer 'Concor 10mg' under wildly different spellings and fluctuating discount rates:
      - Warehouse A ('مخزن السلام') calls it 'CONCOR 10MG TAB' with discount 18%
      - Warehouse B ('مخزن الهضبة') calls it 'ركونوك 10 مجم' (reversed Arabic) with discount 24%
    Order sheet asks for: 'كونكور 10 مجم 30 قرص'.

    Expected outcome:
    1. Both vendor items map to standard entity (Concor 10mg).
    2. Order item maps to standard entity (Concor 10mg).
    3. Allocator picks Warehouse B ('مخزن الهضبة') because of higher discount (24% vs 18%).
    """
    inventory_data = pd.DataFrame([
        {
            'warehouse_name': 'مخزن السلام',
            'item_name': 'CONCOR 10MG TAB',
            'normalized_name': 'concor 10mg tab',
            'dosage': '10mg',
            'unit_size': 'tab',
            'base_price': 100.0,
            'discount_rate': 0.18,
            'stock_status': True
        },
        {
            'warehouse_name': 'مخزن الهضبة',
            'item_name': 'ركونوك 10 مجم',
            'normalized_name': 'ركونوك 10 مجم',
            'dosage': '10mg',
            'unit_size': 'قرص',
            'base_price': 100.0,
            'discount_rate': 0.24,
            'stock_status': True
        },
        {
            'warehouse_name': 'مخزن الفرسان',
            'item_name': 'مالفاتك 50',
            'normalized_name': 'مالفاتك 50',
            'dosage': '50mg',
            'unit_size': 'قرص',
            'base_price': 60.0,
            'discount_rate': 0.20,
            'stock_status': True
        }
    ])

    order_data = pd.DataFrame([
        {
            'requested_item': 'كونكور 10 مجم 30 قرص',
            'quantity': 5,
            'normalized_name': 'كونكور 10 مجم 30 قرص',
            'dosage': '10mg',
            'unit_size': 'قرص'
        },
        {
            'requested_item': 'كتافلام 50 مجم',
            'quantity': 10,
            'normalized_name': 'كتافلام 50 مجم',
            'dosage': '50mg',
            'unit_size': 'قرص'
        }
    ])

    allocator = MedicineAllocator(inventory_data, medication_db=populated_test_db)
    result = allocator.allocate_order(order_data)

    kpis = result['kpis']
    assert kpis['matched_items'] == 2, f"Expected 2 matches, got {kpis['matched_items']}"

    records = result['master_comparison'].to_dict(orient='records')
    concor_match = next(r for r in records if 'كونكور' in r['اسم الصنف المطلوب (في طلب الشراء)'])
    cataflam_match = next(r for r in records if 'كتافلام' in r['اسم الصنف المطلوب (في طلب الشراء)'])

    # Concor should be awarded to مخزن الهضبة (24% discount) despite the reversed name!
    assert concor_match['المخزن الفائز'] == 'مخزن الهضبة'
    assert concor_match['أعلى خصم %'] == 0.24
    assert concor_match['اسم الصنف في كشف المخزن الفائز'] == 'ركونوك 10 مجم'

    # Cataflam should be matched to مخزن الفرسان
    assert cataflam_match['المخزن الفائز'] == 'مخزن الفرسان'
    assert cataflam_match['أعلى خصم %'] == 0.20
