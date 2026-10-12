# -*- coding: utf-8 -*-
"""
Milestone M2 Unit and Integration Tests:
- Multi-sheet workbook scanning (skip empty/notes, concatenate valid order sheets).
- Scored multi-signal header detection (ignore sales rep/warehouse metadata rows, depth up to 50).
- Row-level metadata rejection (totals, categories, sales reps, warehouses, customer names, dates).
- Non-inflating quantity aggregation (explicit 0 remains 0, NaN defaults to 1).
- Exact target yields for train/0911.xlsx (202 items, 5,553 units) and train/0912.xlsx (743 items, 21,676 units).
"""
import os
import re
import pytest
import pandas as pd
from src.excel_parser import load_purchase_order, find_order_header_row, is_metadata_or_header, clean_state_suffix


def test_0911_target_yield():
    """Verify train/0911.xlsx yields exactly 202 distinct items and 5,553 units."""
    fpath = os.path.join("train", "0911.xlsx")
    assert os.path.exists(fpath), f"File not found: {fpath}"
    df = load_purchase_order(fpath)

    assert len(df) == 202, f"Expected 202 items, got {len(df)}"
    assert df['quantity'].sum() == 5553, f"Expected sum 5553, got {df['quantity'].sum()}"

    # Verify no customer names misclassified
    for name in df['requested_item']:
        assert not re.search(r'^(?:ص\s*[/:\s]|(?:صيدلية|صيدليه)\b)\s*[\u0600-\u06FFa-zA-Z]', name), f"Customer name misclassified: {name}"
        assert not re.match(r'^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}', name), f"Date misclassified: {name}"
        assert not re.search(r'^(?:إجمالي|اجمالي|المجموع)\b', name), f"Total misclassified: {name}"


def test_0912_target_yield():
    """Verify train/0912.xlsx yields exactly 743 distinct items and 21,676 units."""
    fpath = os.path.join("train", "0912.xlsx")
    assert os.path.exists(fpath), f"File not found: {fpath}"
    df = load_purchase_order(fpath)

    assert len(df) == 743, f"Expected 743 items, got {len(df)}"
    assert df['quantity'].sum() == 21676, f"Expected sum 21676, got {df['quantity'].sum()}"

    # Verify specific previously inflated items
    # 'في اند كريم' was previously inflated by +2 (rows 986, 987, 988: 0, 0, 3 -> previously 5)
    f_and_cream = df[df['canonical_item'] == 'في اند كريم']
    if not f_and_cream.empty:
        assert f_and_cream['quantity'].iloc[0] == 3, f"Expected 'في اند كريم' qty=3, got {f_and_cream['quantity'].iloc[0]}"

    # Verify no customer names misclassified
    for name in df['requested_item']:
        assert not re.search(r'^(?:ص\s*[/:\s]|(?:صيدلية|صيدليه)\b)\s*[\u0600-\u06FFa-zA-Z]', name), f"Customer name misclassified: {name}"
        assert not re.match(r'^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}', name), f"Date misclassified: {name}"
        assert not re.search(r'^(?:إجمالي|اجمالي|المجموع)\b', name), f"Total misclassified: {name}"


def test_multisheet_scanning_and_concatenation(tmp_path):
    """Multi-sheet scanning discards empty/notes sheets and concatenates valid order sheets."""
    wb_path = str(tmp_path / "multisheet_order.xlsx")
    with pd.ExcelWriter(wb_path, engine="openpyxl") as writer:
        # Sheet 1: Empty spacer
        pd.DataFrame([[None]]).to_excel(writer, sheet_name="EmptySpacer", header=False, index=False)
        # Sheet 2: Notes / metadata only (no order columns)
        pd.DataFrame([["ملاحظات الفاتورة", "تسليم سريع"]]).to_excel(writer, sheet_name="Notes", header=False, index=False)
        # Sheet 3: Table A
        df_a = pd.DataFrame([
            ["كود الصنف", "أسم الصنف", "الكمية"],
            ["001", "بانادول اكسترا 24 قرص", 10],
            ["002", "كونكور 5 مجم 30 قرص", 5],
        ])
        df_a.to_excel(writer, sheet_name="Medicines", header=False, index=False)
        # Sheet 4: Table B
        df_b = pd.DataFrame([
            ["كود الصنف", "أسم الصنف", "الكمية"],
            ["003", "سرنجات 3 سم", 50],
            ["001", "بانادول اكسترا 24 قرص س ج", 15],  # duplicate item with state suffix
        ])
        df_b.to_excel(writer, sheet_name="Supplies", header=False, index=False)

    df = load_purchase_order(wb_path)
    assert len(df) == 3  # Panadol Extra (merged), Concor, Syringes
    panadol_row = df[df['requested_item'] == 'بانادول اكسترا 24 قرص']
    assert not panadol_row.empty
    assert panadol_row['quantity'].iloc[0] == 25  # 10 + 15
    assert df['quantity'].sum() == 80  # 25 + 5 + 50


def test_scored_header_detection_and_metadata_rejection(tmp_path):
    """Header detection avoids metadata lines (rep, warehouse) and filters sub-headers/totals."""
    wb_path = str(tmp_path / "stacked_order.xlsx")
    data = [
        ["شركة توزيع الأدوية المتحدة", None, None, None],
        ["اسم المندوب: محمود أحمد", None, "التاريخ:", "2026-09-12"],
        ["المخزن: مخزن طنطا الرئيسي", None, "رقم الطلب:", "PO-9921"],
        [None, None, None, None],
        ["--- أصناف الأدوية العادية ---", None, None, None],
        ["كود الصنف", "أسم الصنف", "الوحدة", "الكمية"],
        ["101", "كونكور 5 مجم 30 قرص", "علبة", 10],
        ["102", "كتافلام 50 مجم 20 قرص", "علبة", 15],
        ["103", "بانادول اكسترا 24 قرص س ج", "علبة", 25],
        [None, None, None, None],
        ["--- أصناف الثلاجة والأنسولين ---", None, None, None],
        ["كود الصنف", "أسم الصنف", "الوحدة", "الكمية"],
        ["201", "ابيدرا خرطوشه", "قلم", 5],
        ["202", "لانتوس سولوستار", "قلم", 8],
        [None, None, None, None],
        ["--- أصناف النواقص المطلوبة عاجل ---", None, None, None],
        ["كود الصنف", "أسم الصنف", "الوحدة", "الكمية"],
        ["102", "كتافلام 50 مجم 20 قرص", "علبة", 5],  # Repeat of item 102
        ["301", "أوجمنتين 1 جم 14 قرص", "علبة", 20],
        [None, None, None, None],
        ["إجمالي الكميات:", None, None, 83],
        ["ملاحظات: تسليم قبل الساعة 4 عصرا", None, None, None],
        ["توقيع المستلم: د. مصطفى", None, None, None],
    ]
    pd.DataFrame(data).to_excel(wb_path, index=False, header=False)

    df = load_purchase_order(wb_path)
    assert len(df) == 6
    assert df['quantity'].sum() == 88

    items = set(df['requested_item'])
    assert "كونكور 5 مجم 30 قرص" in items
    assert "كتافلام 50 مجم 20 قرص" in items
    assert "بانادول اكسترا 24 قرص" in items
    assert "ابيدرا خرطوشه" in items
    assert "لانتوس سولوستار" in items
    assert "أوجمنتين 1 جم 14 قرص" in items

    cataflam = df[df['requested_item'] == "كتافلام 50 مجم 20 قرص"]
    assert cataflam['quantity'].iloc[0] == 20  # 15 + 5


def test_non_inflating_quantity_and_zero_preservation(tmp_path):
    """Explicit 0 remains 0 and does not inflate total; drop_zero_qty filters it."""
    wb_path = str(tmp_path / "zero_qty_order.xlsx")
    data = [
        ["أسم الصنف", "الكمية"],
        ["بانادول اكسترا", 0],
        ["بانادول اكسترا", 10],  # 0 + 10 = 10
        ["كونكور 5 مجم", None],   # NaN -> 1
        ["سيلجون نقط", 0],       # single row with 0
    ]
    pd.DataFrame(data).to_excel(wb_path, index=False, header=False)

    # Default: keeps 0 quantity without inflation
    df = load_purchase_order(wb_path, drop_zero_qty=False)
    assert len(df) == 3
    panadol = df[df['requested_item'] == "بانادول اكسترا"]
    assert panadol['quantity'].iloc[0] == 10
    concor = df[df['requested_item'] == "كونكور 5 مجم"]
    assert concor['quantity'].iloc[0] == 1
    selgon = df[df['requested_item'] == "سيلجون نقط"]
    assert selgon['quantity'].iloc[0] == 0

    # With drop_zero_qty=True: filters out zero quantity items
    df_filtered = load_purchase_order(wb_path, drop_zero_qty=True)
    assert len(df_filtered) == 2
    assert "سيلجون نقط" not in set(df_filtered['requested_item'])
