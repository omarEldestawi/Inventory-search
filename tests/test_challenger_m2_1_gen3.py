# -*- coding: utf-8 -*-
"""
Empirical Adversarial Stress Test Suite for src/excel_parser.py.
Author: Challenger M2_1 gen3

Tests:
1. Exact target yield verification on train/0911.xlsx (202 items, 5,553 units) & train/0912.xlsx (743 items, 21,676 units).
2. Deep metadata headers (25+ rows of nested sales reps, warehouse headers, dates, customers).
3. Header at extreme depth (row 45).
4. Category dividers and embedded totals (--- ثلاجة ---, قسم الأدوية المستوردة, إجمالي الفاتورة, etc.).
5. Customer branch names disguised as items (صيدلية السلام, ص محمد أحمد, etc.) vs genuine medicines starting with Saad.
6. Mixed quantity formats (explicit 0, float, blank/None, corrupted strings, net-negative returns, net-positive returns).
7. Arabic-Indic digits in quantity column (evaluating behavior and robustness).
8. Adversarial multi-sheet workbooks (empty first sheet, single-cell sheet, non-order tables, multiple valid order sheets, total sheets).
9. Corrupted/empty workbooks (all empty sheets, header without data, metadata-only sheets).
10. Code integrity check (AST / token level analysis ensuring zero hardcoded branches).
"""
import os
import re
import tokenize
import pytest
import pandas as pd
import numpy as np
from src.excel_parser import (
    load_purchase_order,
    find_order_header_row,
    is_metadata_or_header,
    parse_quantity_value,
    clean_state_suffix
)


# ============================================================================
# 1. Independent Verification of Real Orders (0911.xlsx & 0912.xlsx)
# ============================================================================

def test_0911_exact_target_yield_and_zero_inflation():
    """Verify train/0911.xlsx yields exactly 202 distinct items and 5,553 units."""
    fpath = os.path.join("train", "0911.xlsx")
    assert os.path.exists(fpath), f"File not found: {fpath}"
    df = load_purchase_order(fpath)

    # 1. Yield assertions
    assert len(df) == 202, f"Expected exactly 202 items in 0911, got {len(df)}"
    assert df['quantity'].sum() == 5553, f"Expected quantity sum 5553 in 0911, got {df['quantity'].sum()}"

    # 2. Verify explicit 0 quantity item is present without inflation
    # Row 256 in 0911 is 'دورفين 30كبسولة' with qty=0
    dorphin = df[df['canonical_item'] == 'دورفين 30كبسولة']
    assert not dorphin.empty, "Expected 'دورفين 30كبسولة' to be present in 0911"
    assert dorphin['quantity'].iloc[0] == 0, f"Expected 'دورفين 30كبسولة' qty=0, got {dorphin['quantity'].iloc[0]}"

    # 3. Verify drop_zero_qty=True excludes the 0-qty item
    df_no_zero = load_purchase_order(fpath, drop_zero_qty=True)
    assert len(df_no_zero) == 201, f"Expected 201 items with drop_zero_qty=True, got {len(df_no_zero)}"
    assert df_no_zero['quantity'].sum() == 5553, f"Expected sum 5553 with drop_zero_qty=True, got {df_no_zero['quantity'].sum()}"
    assert 'دورفين 30كبسولة' not in set(df_no_zero['canonical_item'])

    # 4. Verify 100% rejection of customer, date, and total tokens
    for item in df['requested_item']:
        assert not re.search(r'^(?:ص\s*[/:\s]|(?:صيدلية|صيدليه)\b)\s*[\u0600-\u06FFa-zA-Z]', item), f"Customer name misclassified: {item}"
        assert not re.match(r'^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}', item), f"Date misclassified: {item}"
        assert not re.search(r'^(?:إجمالي|اجمالي|المجموع)\b', item), f"Total misclassified: {item}"


def test_0912_exact_target_yield_and_zero_inflation():
    """Verify train/0912.xlsx yields exactly 743 distinct items and 21,676 units."""
    fpath = os.path.join("train", "0912.xlsx")
    assert os.path.exists(fpath), f"File not found: {fpath}"
    df = load_purchase_order(fpath)

    # 1. Yield assertions
    assert len(df) == 743, f"Expected exactly 743 items in 0912, got {len(df)}"
    assert df['quantity'].sum() == 21676, f"Expected quantity sum 21676 in 0912, got {df['quantity'].sum()}"

    # 2. Verify previously inflated item 'في اند كريم' (rows 986-988: 0, 0, 3)
    f_and_cream = df[df['canonical_item'] == 'في اند كريم']
    assert not f_and_cream.empty, "Expected 'في اند كريم' in 0912"
    assert f_and_cream['quantity'].iloc[0] == 3, f"Expected 'في اند كريم' qty=3, got {f_and_cream['quantity'].iloc[0]}"

    # 3. Verify drop_zero_qty=True
    df_no_zero = load_purchase_order(fpath, drop_zero_qty=True)
    assert len(df_no_zero) == 741, f"Expected 741 items with drop_zero_qty=True (2 zero-qty items removed), got {len(df_no_zero)}"
    assert df_no_zero['quantity'].sum() == 21676

    # 4. Verify 100% rejection of customer, date, and total tokens
    for item in df['requested_item']:
        assert not re.search(r'^(?:ص\s*[/:\s]|(?:صيدلية|صيدليه)\b)\s*[\u0600-\u06FFa-zA-Z]', item), f"Customer name misclassified: {item}"
        assert not re.match(r'^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}', item), f"Date misclassified: {item}"
        assert not re.search(r'^(?:إجمالي|اجمالي|المجموع)\b', item), f"Total misclassified: {item}"


# ============================================================================
# 2. Deep Metadata Headers (25+ Rows Before True Data)
# ============================================================================

def test_deep_metadata_headers(tmp_path):
    """Ensure parser bypasses 25 rows of realistic nested metadata headers and finds true header."""
    wb_path = str(tmp_path / "deep_metadata_order.xlsx")
    rows = [
        ["الشركة المصرية لتجارة وتوزيع الأدوية", None, None, None],
        ["قطاع القاهرة الكبرى - فرع المعادي", None, None, None],
        ["كود العميل: CLI-88219", None, "تاريخ الفاتورة:", "2026-09-24"],
        ["اسم العميل: صيدلية الأمل التخصصية", None, "رقم أمر الشراء:", "PO-99120"],
        ["العنوان: 15 شارع النصر، المعادي، القاهرة", None, None, None],
        ["اسم المندوب: أ. محمود عبد الفتاح", None, "هاتف المندوب:", "01001234567"],
        ["اسم المشرف: د. طارق رضوان", None, "الوردية:", "صباحية"],
        ["المخزن الرئيسي: مخزن التجمع الخامس", None, "كود المخزن:", "WH-01"],
        ["نوع الطلب: عاجل - كوتة أسبوعية", None, None, None],
        ["شروط الدفع: نقدي عند الاستلام مع خصم السداد النقدي", None, None, None],
        [None, None, None, None],
        ["ملاحظات التسليم: يرجى التوريد مع ثلاجة حفظ الأنسولين", None, None, None],
        ["تعليمات خاصة: استلام الفاتورة ممهورة بخاتم الصيدلية", None, None, None],
        ["سياسة الاسترجاع: خلال 14 يوما من تاريخ الاستلام", None, None, None],
        [None, None, None, None],
        ["توقيع المستلم المعتمد: ..........................", None, None, None],
        ["توقيع مدير الفرع: ................................", None, None, None],
        [None, None, None, None],
        ["--- بيان الأصناف والأدوية المطلوبة للفرع ---", None, None, None],
        ["تنبيه: الأسعار خاضعة للتسعيرة الجبرية الرسمية", None, None, None],
        [None, None, None, None],
        ["جدول التوريد الفعلي:", None, None, None],
        # True Header at Row 22
        ["كود الصنف", "أسم الصنف", "الوحدة", "الكمية المطلوبة"],
        ["1001", "أوجمنتين 1 جم 14 قرص", "علبة", 30],
        ["1002", "كونكور 5 مجم 30 قرص", "علبة", 15],
        ["1003", "كتافلام 50 مجم 20 قرص", "علبة", 20],
        ["1004", "لانتوس سولوستار", "قلم", 10],
    ]
    pd.DataFrame(rows).to_excel(wb_path, index=False, header=False)

    df = load_purchase_order(wb_path)
    assert len(df) == 4, f"Expected 4 items, got {len(df)}"
    assert df['quantity'].sum() == 75, f"Expected sum 75, got {df['quantity'].sum()}"

    item_names = set(df['requested_item'])
    assert "أوجمنتين 1 جم 14 قرص" in item_names
    assert "كونكور 5 مجم 30 قرص" in item_names
    assert "كتافلام 50 مجم 20 قرص" in item_names
    assert "لانتوس سولوستار" in item_names

    # Verify no metadata row slipped in
    for name in item_names:
        assert "المصرية" not in name
        assert "المعادي" not in name
        assert "CLI-88219" not in name
        assert "محمود" not in name
        assert "ملاحظات" not in name


def test_header_at_depth_45(tmp_path):
    """Test header at extreme scan depth (row 45 out of max_scan 50)."""
    wb_path = str(tmp_path / "extreme_depth_order.xlsx")
    rows = []
    # Fill 45 rows of filler metadata
    for i in range(45):
        rows.append([f"بيان إداري رقم {i+1}", f"ملاحظة إدارية {i+1}", None])

    # Header at Row 45
    rows.append(["كود الصنف", "اسم الدواء", "كمية"])
    rows.append(["201", "بانادول جوينت 18 قرص", 12])
    rows.append(["202", "سيبتازول أقراص", 8])

    pd.DataFrame(rows).to_excel(wb_path, index=False, header=False)

    df = load_purchase_order(wb_path)
    assert len(df) == 2, f"Expected 2 items at depth 45, got {len(df)}"
    assert df['quantity'].sum() == 20


# ============================================================================
# 3. Category Headers, Embedded Dividers, and Embedded Financial Totals
# ============================================================================

def test_category_dividers_and_embedded_totals(tmp_path):
    """Test rejection of complex embedded category headers, dashed lines, sub-totals, and grand totals."""
    wb_path = str(tmp_path / "category_dividers_order.xlsx")
    rows = [
        ["كود الصنف", "أسم الصنف", "الوحدة", "الكمية"],
        # Category 1
        ["--- ثلاجة ---", None, None, None],
        ["101", "ابيدرا خرطوشه", "قلم", 6],
        ["102", "ميكستارد 30 100 وحدة", "فيال", 14],
        # Category 2
        ["--- أصناف مستوردة ---", None, None, None],
        ["201", "نيكسيوم 40 مجم 28 قرص", "علبة", 10],
        # Embedded subtotal
        ["إجمالي قسم الأدوية المستوردة", None, None, 10],
        # Category 3 with alternative formatting
        ["قسم الأدوية المستوردة", None, None, None],
        ["202", "بلافيكس 75 مجم 28 قرص", "علبة", 5],
        # Category 4 with separator symbols
        ["=== مستلزمات طبية ===", None, None, None],
        ["301", "سرنجات أنسولين 100 وحدة", "علبة", 25],
        ["*** قطرات ومراهم ***", None, None, None],
        ["401", "توبرادكس قطرة", "زجاجة", 15],
        # Category 5: مجموعة
        ["مجموعة المسكنات والمضادات", None, None, None],
        ["501", "كتافلام 50 مجم 20 قرص", "علبة", 20],
        # Category 6: أصناف النواقص
        ["أصناف النواقص العاجلة", None, None, None],
        ["601", "بانادول اكسترا 24 قرص", "علبة", 50],
        # Repeated header in middle of sheet
        ["كود الصنف", "أسم الصنف", "الوحدة", "الكمية"],
        ["602", "أوجمنتين 1 جم 14 قرص", "علبة", 30],
        # Financial / quantity totals at the bottom
        ["المجموع الكلي للكميات", None, None, 170],
        ["إجمالي الفاتورة شامل الضريبة", None, None, 15420.50],
        ["المجموع الفرعي:", None, None, 13500],
        ["subtotal", None, None, 13500],
        ["Grand Total", None, None, 15420.50],
        ["مندوب التوزيع: حسام السيد", None, None, None],
        ["ملاحظات: تسليم فوري", None, None, None],
        ["توقيع المستلم:", None, None, None],
    ]
    pd.DataFrame(rows).to_excel(wb_path, index=False, header=False)

    df = load_purchase_order(wb_path)

    # Valid items:
    # 1. ابيدرا خرطوشه: 6
    # 2. ميكستارد 30 100 وحدة: 14
    # 3. نيكسيوم 40 مجم 28 قرص: 10
    # 4. بلافيكس 75 مجم 28 قرص: 5
    # 5. سرنجات أنسولين 100 وحدة: 25
    # 6. توبرادكس قطرة: 15
    # 7. كتافلام 50 مجم 20 قرص: 20
    # 8. بانادول اكسترا 24 قرص: 50
    # 9. أوجمنتين 1 جم 14 قرص: 30
    # Total distinct items = 9
    # Total sum = 6 + 14 + 10 + 5 + 25 + 15 + 20 + 50 + 30 = 175

    assert len(df) == 9, f"Expected exactly 9 items, got {len(df)}: {list(df['requested_item'])}"
    assert df['quantity'].sum() == 175, f"Expected sum 175, got {df['quantity'].sum()}"

    item_set = set(df['requested_item'])
    # Assert none of the category or total markers slipped through
    assert "--- ثلاجة ---" not in item_set
    assert "--- أصناف مستوردة ---" not in item_set
    assert "قسم الأدوية المستوردة" not in item_set
    assert "أصناف النواقص العاجلة" not in item_set
    assert "مجموعة المسكنات والمضادات" not in item_set
    assert "=== مستلزمات طبية ===" not in item_set
    assert "*** قطرات ومراهم ***" not in item_set
    assert "إجمالي الفاتورة شامل الضريبة" not in item_set
    assert "المجموع الكلي للكميات" not in item_set
    assert "إجمالي قسم الأدوية المستوردة" not in item_set


# ============================================================================
# 4. Customer Pharmacy Names Disguised as Items vs Legitimate Medicines
# ============================================================================

def test_disguised_customer_names_and_saad_medicines(tmp_path):
    """
    Verify rejection of disguised customer pharmacy branch names while
    preserving legitimate medicines that start with the letter Saad ('ص').
    """
    wb_path = str(tmp_path / "customer_names_order.xlsx")
    rows = [
        ["كود الصنف", "أسم الصنف", "الكمية"],
        # Disguised Customer Names (MUST BE REJECTED)
        ["C01", "صيدلية السلام الكبرى", 1],
        ["C02", "صيدليه النور الحديثة", 1],
        ["C03", "ص محمد أحمد", 1],
        ["C04", "ص/ الأمل والشفاء", 1],
        ["C05", "ص: دكتور طارق", 1],
        ["C06", "ص فاروق فرع الهرم", 1],
        ["C07", "عميل نقدي د. خالد", 1],
        ["C08", "الزبون: صيدلية المعادي", 1],
        ["C09", "customer: Dr. Ahmed", 1],
        # Legitimate Medicines starting with letter Saad (MUST BE PRESERVED)
        ["M01", "صوديوم بيكربونات 8.4% أمبول", 10],
        ["M02", "صن بلوك بوباي 50+ جل", 5],
        ["M03", "صبغة شعر كولستون بني غامق", 3],
        # Standard Medicines
        ["M04", "كونكور 5 مجم 30 قرص", 20],
        ["M05", "بانادول اكسترا 24 قرص", 15],
    ]
    pd.DataFrame(rows).to_excel(wb_path, index=False, header=False)

    df = load_purchase_order(wb_path)

    # Only M01..M05 should be extracted
    assert len(df) == 5, f"Expected exactly 5 items, got {len(df)}: {list(df['requested_item'])}"
    assert df['quantity'].sum() == 53  # 10 + 5 + 3 + 20 + 15

    extracted_items = set(df['requested_item'])
    # Assert genuine medicines starting with Saad are preserved
    assert "صوديوم بيكربونات 8.4% أمبول" in extracted_items
    assert "صن بلوك بوباي 50+ جل" in extracted_items
    assert "صبغة شعر كولستون بني غامق" in extracted_items

    # Assert all customer names are rejected 100%
    for cust in ["صيدلية السلام الكبرى", "صيدليه النور الحديثة", "ص محمد أحمد",
                 "ص/ الأمل والشفاء", "ص: دكتور طارق", "ص فاروق فرع الهرم",
                 "عميل نقدي د. خالد", "الزبون: صيدلية المعادي", "customer: Dr. Ahmed"]:
        assert cust not in extracted_items, f"Disguised customer name leaked into items: {cust}"


# ============================================================================
# 5. Mixed Quantity Formats (0, Floats, Strings, Negatives, Blanks)
# ============================================================================

def test_mixed_quantity_formats_and_returns(tmp_path):
    """
    Test mixed quantity formats:
    - Explicit 0 preserved without inflation
    - Float quantities truncated/parsed cleanly
    - None/blank defaulted to 1
    - Corrupted strings defaulted to 1
    - Negative aggregated quantities (returns/credits) filtered out
    - Net-positive aggregated quantities (order - return > 0) preserved correctly
    """
    wb_path = str(tmp_path / "mixed_quantities_order.xlsx")
    rows = [
        ["كود الصنف", "أسم الصنف", "الكمية"],
        # Item 1: Explicit 0
        ["101", "أوجمنتين 1 جم 14 قرص", 0],
        # Item 2: Multiple rows with 0 and positive: 0 + 10 = 10
        ["102", "كونكور 5 مجم 30 قرص", 0],
        ["102", "كونكور 5 مجم 30 قرص", 10],
        # Item 3: Float quantity: 12.0 -> 12
        ["103", "كتافلام 50 مجم 20 قرص", 12.0],
        # Item 4: Fractional float: 5.7 -> int(5.7) = 5
        ["104", "بانادول اكسترا 24 قرص", 5.7],
        # Item 5: Blank / None -> defaults to 1
        ["105", "ابيدرا خرطوشه", None],
        # Item 6: Corrupted non-numeric string -> defaults to 1
        ["106", "لانتوس سولوستار", "غير متوفر"],
        ["107", "نيكسيوم 40 مجم", "N/A"],
        # Item 8: Net-negative return: +3 order, -8 return -> sum = -5 (MUST BE FILTERED OUT)
        ["108", "سيرفيتام كبسول", 3],
        ["108", "سيرفيتام كبسول", -8],
        # Item 9: Net-positive with return: +20 order, -5 return -> sum = 15 (MUST BE KEPT)
        ["109", "أتور 20 مجم 28 قرص", 20],
        ["109", "أتور 20 مجم 28 قرص", -5],
    ]
    pd.DataFrame(rows).to_excel(wb_path, index=False, header=False)

    # 1. Test with drop_zero_qty=False (preserves explicit 0, filters net-negative)
    df = load_purchase_order(wb_path, drop_zero_qty=False)

    # Expected items:
    # 101: أوجمنتين -> qty = 0 (kept)
    # 102: كونكور -> qty = 10
    # 103: كتافلام -> qty = 12
    # 104: بانادول -> qty = 5
    # 105: ابيدرا -> qty = 1
    # 106: لانتوس -> qty = 1
    # 107: نيكسيوم -> qty = 1
    # 108: سيرفيتام -> net -5 (FILTERED OUT)
    # 109: أتور -> net 15 (KEPT)
    # Total kept items = 8

    assert len(df) == 8, f"Expected 8 items, got {len(df)}: {list(df['requested_item'])}"
    assert "سيرفيتام كبسول" not in set(df['requested_item']), "Net-negative item was not filtered out!"

    # Check quantities
    item_map = dict(zip(df['requested_item'], df['quantity']))
    assert item_map["أوجمنتين 1 جم 14 قرص"] == 0
    assert item_map["كونكور 5 مجم 30 قرص"] == 10
    assert item_map["كتافلام 50 مجم 20 قرص"] == 12
    assert item_map["بانادول اكسترا 24 قرص"] == 5
    assert item_map["ابيدرا خرطوشه"] == 1
    assert item_map["لانتوس سولوستار"] == 1
    assert item_map["نيكسيوم 40 مجم"] == 1
    assert item_map["أتور 20 مجم 28 قرص"] == 15

    # Total sum = 0 + 10 + 12 + 5 + 1 + 1 + 1 + 15 = 45
    assert df['quantity'].sum() == 45

    # 2. Test with drop_zero_qty=True
    df_no_zero = load_purchase_order(wb_path, drop_zero_qty=True)
    assert len(df_no_zero) == 7  # أوجمنتين with qty=0 dropped
    assert "أوجمنتين 1 جم 14 قرص" not in set(df_no_zero['requested_item'])
    assert df_no_zero['quantity'].sum() == 45


# ============================================================================
# 6. Arabic Digits Quantity Parsing Evaluation
# ============================================================================

def test_arabic_digits_quantity_handling():
    """
    Verify parse_quantity_value parses Arabic-Indic digits ('٥', '١٠')
    correctly to integers rather than crashing.
    """
    assert parse_quantity_value(5) == 5
    assert parse_quantity_value("5") == 5
    assert parse_quantity_value(0) == 0
    assert parse_quantity_value("0") == 0
    assert parse_quantity_value("٥") == 5
    assert parse_quantity_value("١٠") == 10
    assert parse_quantity_value("٢٥") == 25


# ============================================================================
# 7. Adversarial Multi-Sheet Workbooks
# ============================================================================

def test_adversarial_multisheet_workbook(tmp_path):
    """
    Test multi-sheet scanning robustness:
    - Sheet 1: Empty spacer
    - Sheet 2: Single cell
    - Sheet 3: Non-order table (sales reps contact list)
    - Sheet 4: Valid Order Sheet 1 (8 items)
    - Sheet 5: 50 empty rows
    - Sheet 6: Valid Order Sheet 2 (4 items, 2 overlapping with Sheet 1)
    - Sheet 7: Total / Summary sheet
    """
    wb_path = str(tmp_path / "complex_multisheet.xlsx")
    with pd.ExcelWriter(wb_path, engine="openpyxl") as writer:
        # Sheet 1: Empty
        pd.DataFrame().to_excel(writer, sheet_name="EmptySheet", header=False, index=False)

        # Sheet 2: Single cell
        pd.DataFrame([["ملاحظات عامة فقط"]]).to_excel(writer, sheet_name="SingleCell", header=False, index=False)

        # Sheet 3: Contacts Table (has headers like 'اسم', but no order structure)
        df_contacts = pd.DataFrame([
            ["اسم المندوب", "رقم التليفون", "المنطقة"],
            ["أحمد محمود", "01122334455", "الدقي"],
            ["خالد سعيد", "01099887766", "مدينة نصر"],
        ])
        df_contacts.to_excel(writer, sheet_name="Contacts", header=False, index=False)

        # Sheet 4: Order Sheet 1
        df_order1 = pd.DataFrame([
            ["كود الصنف", "أسم الصنف", "الوحدة", "الكمية"],
            ["001", "بانادول اكسترا 24 قرص", "علبة", 10],
            ["002", "كونكور 5 مجم 30 قرص", "علبة", 5],
            ["003", "كتافلام 50 مجم 20 قرص", "علبة", 12],
            ["004", "أوجمنتين 1 جم 14 قرص", "علبة", 20],
        ])
        df_order1.to_excel(writer, sheet_name="MainOrder", header=False, index=False)

        # Sheet 5: 50 empty rows
        pd.DataFrame([[None, None]] * 50).to_excel(writer, sheet_name="EmptyRows", header=False, index=False)

        # Sheet 6: Order Sheet 2 (Overlapping items + state suffix)
        df_order2 = pd.DataFrame([
            ["كود الصنف", "أسم الصنف", "الوحدة", "الكمية"],
            ["001", "بانادول اكسترا 24 قرص س ج", "علبة", 15],  # Overlaps with 001 in Sheet 4
            ["002", "كونكور 5 مجم 30 قرص", "علبة", 8],          # Overlaps with 002 in Sheet 4
            ["005", "لانتوس سولوستار", "قلم", 7],
            ["006", "ابيدرا خرطوشه", "قلم", 4],
        ])
        df_order2.to_excel(writer, sheet_name="UrgentOrder", header=False, index=False)

        # Sheet 7: Financial Summary Sheet
        df_summary = pd.DataFrame([
            ["إجمالي الطلبيات", 5000],
            ["المبلغ الصافي", 4200],
        ])
        df_summary.to_excel(writer, sheet_name="Summary", header=False, index=False)

    df = load_purchase_order(wb_path)

    # Distinct items expected:
    # 1. بانادول اكسترا 24 قرص: 10 + 15 = 25
    # 2. كونكور 5 مجم 30 قرص: 5 + 8 = 13
    # 3. كتافلام 50 مجم 20 قرص: 12
    # 4. أوجمنتين 1 جم 14 قرص: 20
    # 5. لانتوس سولوستار: 7
    # 6. ابيدرا خرطوشه: 4
    # Total distinct items = 6
    # Total quantity sum = 25 + 13 + 12 + 20 + 7 + 4 = 81

    assert len(df) == 6, f"Expected 6 items, got {len(df)}: {list(df['requested_item'])}"
    assert df['quantity'].sum() == 81, f"Expected sum 81, got {df['quantity'].sum()}"

    panadol = df[df['requested_item'] == "بانادول اكسترا 24 قرص"]
    assert panadol['quantity'].iloc[0] == 25

    concor = df[df['requested_item'] == "كونكور 5 مجم 30 قرص"]
    assert concor['quantity'].iloc[0] == 13


# ============================================================================
# 8. Empty or Corrupted Workbooks
# ============================================================================

def test_empty_and_metadata_only_workbooks(tmp_path):
    """Ensure load_purchase_order returns clean empty DataFrame and never crashes on non-order workbooks."""
    # 1. Completely empty workbook
    p1 = str(tmp_path / "empty.xlsx")
    pd.DataFrame().to_excel(p1, index=False, header=False)
    df1 = load_purchase_order(p1)
    assert isinstance(df1, pd.DataFrame)
    assert len(df1) == 0
    assert "requested_item" in df1.columns
    assert "quantity" in df1.columns

    # 2. Workbook with only metadata / no header
    p2 = str(tmp_path / "meta_only.xlsx")
    pd.DataFrame([
        ["شركة النور للتجارة"],
        ["مندوب المبيعات: محمد"],
        ["تاريخ اليوم: 2026-09-24"]
    ]).to_excel(p2, index=False, header=False)
    df2 = load_purchase_order(p2)
    assert len(df2) == 0

    # 3. Workbook with header row but 0 data rows
    p3 = str(tmp_path / "header_only.xlsx")
    pd.DataFrame([
        ["كود الصنف", "أسم الصنف", "الكمية"]
    ]).to_excel(p3, index=False, header=False)
    df3 = load_purchase_order(p3)
    assert len(df3) == 0


def test_clean_state_suffix():
    """Verify ERP state suffix stripping across variations."""
    assert clean_state_suffix("بانادول اكسترا س ج") == "بانادول اكسترا"
    assert clean_state_suffix("بانادول اكسترا س ق") == "بانادول اكسترا"
    assert clean_state_suffix("بانادول اكسترا س.ج") == "بانادول اكسترا"
    assert clean_state_suffix("بانادول اكسترا جديد") == "بانادول اكسترا"
    assert clean_state_suffix("بانادول اكسترا قديم") == "بانادول اكسترا"
    assert clean_state_suffix("بانادول اكسترا سعر جديد") == "بانادول اكسترا"
    assert clean_state_suffix("دابافيلداكتين بلس5/1000مجم س ج") == "دابافيلداكتين بلس5/1000مجم"


# ============================================================================
# 9. Code Integrity: Verification of Zero Hardcoded File Branches
# ============================================================================

def test_code_integrity_zero_hardcoding():
    """
    Ensure src/excel_parser.py contains zero hardcoded branches or file-specific logic
    at the AST / code token level (excluding comments and docstrings).
    """
    fpath = os.path.join("src", "excel_parser.py")
    with open(fpath, "rb") as f:
        tokens = list(tokenize.tokenize(f.readline))

    # Extract tokens that are not comments or string docstrings/literals
    code_tokens = [tok.string for tok in tokens if tok.type not in (tokenize.COMMENT, tokenize.STRING)]

    # Check for hardcoded target numbers or filenames in executable logic
    assert "0911" not in code_tokens, "Hardcoded '0911' found in code tokens!"
    assert "0912" not in code_tokens, "Hardcoded '0912' found in code tokens!"
    assert "5553" not in code_tokens, "Hardcoded '5553' found in code tokens!"
    assert "21676" not in code_tokens, "Hardcoded '21676' found in code tokens!"
