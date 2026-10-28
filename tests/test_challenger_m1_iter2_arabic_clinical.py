# -*- coding: utf-8 -*-
"""
Milestone 1 Iteration 2 Gate Check - Challenger 2 Test Suite:
Arabic Clinical & Bidirectional Adversarial Stress Tests.

Verifies:
1. Arabic bidirectional text handling across multi-group tables:
   - Eastern Arabic digits ('١', '٢', '٣') in serial columns and prices.
   - RTL reading direction consistency within each group (price, discount, name order).
   - Reversed Arabic strings ('فنصلا', 'صارقا', 'طيرش') and mixed alphanumeric names.
2. Discount validation:
   - Zero discounts without explicit terms ('صافي', 'نقدى') rejected as invalid_discount_0.0.
   - Excessive discounts > 85% rejected.
   - Valid discounts parsed correctly as decimal ratios (20% -> 0.20).
"""
import unittest
from typing import Any, List

from src.catalog_reader import (
    ProductGroup,
    TableGeometry,
    classify_column_role,
    extract_item_from_group_row,
    extract_raw_float_value,
    is_explicit_zero_discount,
    parse_structural_table,
    resolve_group_arabic_direction,
)
from src.normalizer import (
    is_arabic_text_reversed,
    normalize_arabic_text,
    parse_discount,
    parse_dosage_and_pack,
    unreverse_arabic_text,
)


class MockRow:
    def __init__(self, cells):
        self.cells = cells


class MockTable:
    def __init__(self, data: List[List[Any]]):
        self._data = data
        self.col_count = len(data[0]) if data else 0
        self.rows = [
            MockRow(
                [(c * 50.0, r * 20.0, (c + 1) * 50.0, (r + 1) * 20.0) if v is not None else None for c, v in enumerate(row)]
            )
            for r, row in enumerate(data)
        ]
        self.bbox = (0.0, 0.0, float(self.col_count * 50.0), float(len(data) * 20.0))

    def extract(self) -> List[List[Any]]:
        return self._data


class TestArabicBidirectionalAndClinical(unittest.TestCase):
    """Adversarial stress-testing of Arabic Bidi handling and clinical discount validation."""

    # =========================================================================
    # TASK 1.1: Eastern Arabic Digits in Serial Columns and Prices
    # =========================================================================

    def test_eastern_arabic_digits_in_serial_column_classified_as_code(self):
        """Sequential Eastern Arabic digits in serial column must classify as 'code', never 'discount'."""
        eastern_samples = ["١", "٢", "٣", "٤", "٥"]
        persian_samples = ["۱۰", "۱۱", "۱۲", "۱۳", "۱۴"]

        # With standard serial headers
        for hdr in ["م", "م.", "مسلسل", "#", "ت"]:
            role = classify_column_role(hdr, eastern_samples)
            self.assertEqual(role, "code", f"Header '{hdr}' with Eastern digits should be 'code', got '{role}'")

        # Without header (empty or generic)
        role_empty = classify_column_role("", eastern_samples)
        self.assertEqual(role_empty, "code", f"Empty header with sequential Eastern digits should be 'code', got '{role_empty}'")

        role_persian = classify_column_role("", persian_samples)
        self.assertEqual(role_persian, "code", f"Empty header with Persian digits should be 'code', got '{role_persian}'")

    def test_eastern_arabic_digits_in_prices_parsed_accurately(self):
        """Prices containing Eastern Arabic digits and various decimal separators must parse accurately."""
        price_cases = [
            ("٥٠.٠", 50.0),
            ("٧٥.٥", 75.5),
            ("١٢٠.٧٥", 120.75),
            ("١٠٠", 100.0),
            ("٥٠٫٥", 50.5),     # Arabic decimal comma (U+066B)
            ("٤٥,٢٥", 45.25),   # Standard comma
            ("١٥٠٠.٠", 1500.0),
            ("٠.٧٥", 0.75),
        ]
        for raw, expected in price_cases:
            val = extract_raw_float_value(raw)
            self.assertAlmostEqual(val, expected, places=2, msg=f"Price '{raw}' failed to parse to {expected}")

    def test_10_column_table_with_eastern_arabic_digits(self):
        """
        10-column multi-group table with Eastern Arabic digits across serial, price, discount, and names.
        Verify 3 groups detected, 6 items cleanly extracted with exact numeric parity.
        """
        data = [
            ["م", "سعر", "خصم", "صنف", "سعر", "خصم", "صنف", "سعر", "خصم", "صنف"],
            ["١", "٥٠.٠", "٢٠%", "كونكور ٥ مجم", "٧٠.٠", "٣٠%", "بنادول ٥٠٠", "٩٠.٠", "٢٥%", "اموكسيل ٢٥٠"],
            ["٢", "٦٠.٠", "٢٢%", "اوجمانتين ١ جم", "٨٠.٠", "٣٢%", "كتفاست ٥٠ مجم", "١٠٠.٠", "٢٨%", "فولتارين ٧٥"],
        ]
        table = MockTable(data)
        items, geom, groups, diag = parse_structural_table(table, 0, "مخزن شرقي")

        self.assertEqual(len(groups), 3, f"Expected 3 groups, got {len(groups)}")
        self.assertEqual(len(items), 6, f"Expected 6 items, got {len(items)}")
        self.assertEqual(diag.accepted_rows, 6)
        self.assertEqual(sum(g.rejected_rows for g in diag.groups), 0)

        # Verify parsed numeric values and un-reversed medication names
        expected_items = [
            ("كونكور 5 مجم", 50.0, 0.20),
            ("اوجمانتين 1 جم", 60.0, 0.22),
            ("بنادول 500", 70.0, 0.30),
            ("كتفاست 50 مجم", 80.0, 0.32),
            ("اموكسيل 250", 90.0, 0.25),
            ("فولتارين 75", 100.0, 0.28),
        ]
        for it, (exp_name, exp_p, exp_d) in zip(items, expected_items):
            self.assertEqual(it["item_name"], exp_name)
            self.assertAlmostEqual(it["base_price"], exp_p, places=2)
            self.assertAlmostEqual(it["discount_rate"], exp_d, places=2)

    def test_7_column_table_with_eastern_arabic_digits(self):
        """
        7-column table with Eastern Arabic digits: Col 0 serial + 2 groups of 3 (Price, Discount, Name).
        Verify 2 groups detected, 4 items extracted.
        """
        data = [
            ["م", "سعر", "خصم", "صنف", "سعر", "خصم", "صنف"],
            ["١", "٤٥.٥", "١٥%", "نيبيليت ٥ مجم", "٦٥.٠", "٢٥%", "كابوتن ٢٥ مجم"],
            ["٢", "٥٥.٠", "١٨%", "داونيل ٥ مجم", "٧٥.٠", "٢٨%", "جلوفاج ٥٠٠ مجم"],
        ]
        table = MockTable(data)
        items, geom, groups, diag = parse_structural_table(table, 0, "مخزن الحكمة")

        self.assertEqual(len(groups), 2)
        self.assertEqual(len(items), 4)
        self.assertEqual(diag.accepted_rows, 4)
        self.assertEqual(items[0]["base_price"], 45.5)
        self.assertAlmostEqual(items[0]["discount_rate"], 0.15, places=2)
        self.assertEqual(items[1]["base_price"], 55.0)
        self.assertAlmostEqual(items[1]["discount_rate"], 0.18, places=2)

    # =========================================================================
    # TASK 1.2: RTL Reading Direction Consistency within Multi-Group Tables
    # =========================================================================

    def test_rtl_column_order_within_each_group(self):
        """
        Multi-group table in RTL reading order within each group:
        [م, صنف, خصم, سعر, صنف, خصم, سعر] -> Name is col 1 & 4, Disc is col 2 & 5, Price is col 3 & 6.
        Verify correct column mapping without role confusion.
        """
        data = [
            ["م", "صنف", "خصم", "سعر", "صنف", "خصم", "سعر"],
            ["1", "كونكور 5 مجم", "20%", "50.0", "بنادول 500", "30%", "70.0"],
            ["2", "اوجمانتين 1 جم", "22%", "60.0", "كتفاست 50 مجم", "32%", "80.0"],
        ]
        table = MockTable(data)
        items, geom, groups, diag = parse_structural_table(table, 0, "مخزن الهدى")

        self.assertEqual(len(groups), 2)
        g0, g1 = groups[0], groups[1]
        self.assertEqual(g0.name_col, 1)
        self.assertEqual(g0.discount_col, 2)
        self.assertEqual(g0.price_col, 3)
        self.assertEqual(g1.name_col, 4)
        self.assertEqual(g1.discount_col, 5)
        self.assertEqual(g1.price_col, 6)

        self.assertEqual(len(items), 4)
        self.assertEqual(items[0]["item_name"], "كونكور 5 مجم")
        self.assertEqual(items[0]["base_price"], 50.0)
        self.assertEqual(items[0]["discount_rate"], 0.20)

    def test_independent_group_level_direction_voting(self):
        """
        Multi-group table where Group 0 has reversed Arabic names and Group 1 has forward Arabic names.
        Verify independent group-level voting un-reverses Group 0 while preserving Group 1 in forward order.
        """
        data = [
            ["سعر", "خصم", "صنف", "سعر", "خصم", "صنف"],
            # G0 has reversed tokens ('صارقا', 'طيرش'), G1 has forward tokens ('اقراص', 'شريط')
            ["50.0", "20%", "فولتارين 50 مجم 20 صارقا", "70.0", "25%", "فولتارين 50 مجم 20 اقراص"],
            ["60.0", "22%", "كونكور 5 مجم 30 طيرش", "80.0", "28%", "كونكور 5 مجم 30 شريط"],
        ]
        table = MockTable(data)
        items, geom, groups, diag = parse_structural_table(table, 0, "مخزن مستقل")

        self.assertEqual(len(groups), 2)
        dir_g0 = resolve_group_arabic_direction(data[1:], groups[0].name_col)
        dir_g1 = resolve_group_arabic_direction(data[1:], groups[1].name_col)
        self.assertEqual(dir_g0, "reversed")
        self.assertEqual(dir_g1, "forward")

        self.assertEqual(len(items), 4)
        # Both groups must produce forward canonical names
        self.assertIn("اقراص", items[0]["item_name"])
        self.assertIn("اقراص", items[2]["item_name"])
        self.assertIn("شريط", items[1]["item_name"])
        self.assertIn("شريط", items[3]["item_name"])

    # =========================================================================
    # TASK 1.3: Reversed Arabic Strings and Mixed Alphanumeric Names
    # =========================================================================

    def test_reversed_header_tokens_classified_correctly(self):
        """Reversed Arabic header keywords must classify into their correct respective roles."""
        # Reversed name headers: 'فنصلا' (الصنف) directly without sample cells
        self.assertEqual(classify_column_role("فنصلا"), "name")

        # Reversed header 'مسإ' with text samples
        self.assertEqual(classify_column_role("مسإ", ["دواء 1", "دواء 2"]), "name")

        # Reversed price headers: 'رعسلا' (السعر), 'رعس' (سعر)
        self.assertEqual(classify_column_role("رعسلا"), "price")
        self.assertEqual(classify_column_role("رعس"), "price")

        # Reversed discount headers: 'مصخلا' (الخصم), 'مصخ' (خصم)
        self.assertEqual(classify_column_role("مصخلا"), "discount")
        self.assertEqual(classify_column_role("مصخ"), "discount")

        # Reversed code/serial headers: 'فنصلا مقر' (رقم الصنف), 'مقرلا' (الرقم), 'مقر' (رقم)
        self.assertEqual(classify_column_role("فنصلا مقر"), "code")
        self.assertEqual(classify_column_role("مقرلا"), "code")
        self.assertEqual(classify_column_role("مقر"), "code")

    def test_mixed_alphanumeric_names_preserved_without_scrambling(self):
        """Mixed English/Arabic pharmaceutical names must preserve Latin tokens and numbers in forward order."""
        mixed_names = [
            "Augmentin 1g 14 tab",
            "Concor 5mg 30 tab",
            "Panadol Extra 24 ق",
            "Cataflam 50mg 20 tab كتافلام",
            "Amoclan 1g 14 tab اموكلان",
        ]
        group = ProductGroup(group_index=0, raw_cols=[0, 1, 2], price_col=0, discount_col=1, name_col=2)
        for name in mixed_names:
            row = ["50.0", "20%", name]
            item, reason, _ = extract_item_from_group_row(row, group, "forward", "مخزن تجريبي")
            self.assertIsNotNone(item, f"Extraction failed for: '{name}'")
            self.assertEqual(reason, "accepted")
            # Latin character runs should be intact
            latin_extracted = "".join(c for c in item["item_name"] if c.isascii() and c.isalpha())
            latin_original = "".join(c for c in name if c.isascii() and c.isalpha())
            self.assertEqual(latin_extracted, latin_original, f"Latin run scrambled in '{name}'")

    def test_reversed_pharma_tokens_in_body_cells(self):
        """Reversed pharmaceutical forms in body cells must un-reverse to standard canonical forms."""
        tokens_map = {
            "صارقا": "اقراص",
            "صرق": "قرص",
            "طيرش": "شريط",
            "هلوسبك": "كبسوله",
            "لوبما": "امبول",
            "بارش": "شراب",
            "راوف": "فوار",
            "طقن": "نقط",
        }
        for rev_tok, fwd_tok in tokens_map.items():
            unrev = unreverse_arabic_text(f"دواء {rev_tok}")
            self.assertIn(fwd_tok, unrev, f"Token '{rev_tok}' was not converted to '{fwd_tok}'")

    # =========================================================================
    # TASK 2: Discount Validation Gate
    # =========================================================================

    def test_zero_discounts_without_explicit_terms_rejected_as_invalid_discount_0_0(self):
        """
        Missing or implicit zero discounts without explicit terms ('صافي', 'نقدى', '0%')
        must be rejected as invalid_discount_0.0.
        """
        group = ProductGroup(group_index=0, raw_cols=[0, 1, 2], price_col=0, discount_col=1, name_col=2)
        rejected_cases = [
            "",             # Empty cell
            None,           # None cell
            " ",            # Whitespace
            "-",            # Dash
            "N/A",          # Not applicable
            "بدون",         # Incomplete term
            "zero",         # Generic text without explicit pharma keyword
        ]
        for disc in rejected_cases:
            row = ["50.0", disc, "كونكور 5 مجم 30 قرص"]
            item, reason, _ = extract_item_from_group_row(row, group, "forward", "مخزن تجريبي")
            self.assertIsNone(item, f"Expected rejection for discount '{disc}', but item was accepted")
            self.assertEqual(reason, "invalid_discount_0.0", f"Expected reason invalid_discount_0.0 for '{disc}', got '{reason}'")

    def test_explicit_zero_discount_terms_accepted_with_zero_rate(self):
        """Explicit zero-discount terms ('صافي', 'صافى', 'نقدى', '0%', '0.0%') must be accepted."""
        group = ProductGroup(group_index=0, raw_cols=[0, 1, 2], price_col=0, discount_col=1, name_col=2)
        valid_zero_terms = [
            "صافي",
            "صافى",
            "صا في",
            "نقدى",
            "بدون خصم",
            "0%",
            "0.0%",
            "٠%",
            "٠.٠%",
        ]
        for term in valid_zero_terms:
            row = ["100.0", term, "انسولين لانتوس قلم"]
            item, reason, _ = extract_item_from_group_row(row, group, "forward", "مخزن تجريبي")
            self.assertIsNotNone(item, f"Failed for valid zero discount term '{term}'")
            self.assertEqual(reason, "accepted")
            self.assertEqual(item["base_price"], 100.0)
            self.assertEqual(item["discount_rate"], 0.0)

    def test_excessive_discounts_over_85_percent_rejected(self):
        """
        Wholesale discounts exceeding 85% (> 0.85) must be rejected as invalid_discount_0.0.
        Exact 85% must be accepted.
        """
        group = ProductGroup(group_index=0, raw_cols=[0, 1, 2], price_col=0, discount_col=1, name_col=2)

        # Excessive discounts -> rejected
        excessive_cases = [
            "85.1%",
            "86%",
            "90%",
            "95%",
            "100%",
            "120%",
            "150%",
            "0.86",
            "0.90",
        ]
        for exc in excessive_cases:
            row = ["50.0", exc, "كونكور 5 مجم 30 قرص"]
            item, reason, _ = extract_item_from_group_row(row, group, "forward", "مخزن تجريبي")
            self.assertIsNone(item, f"Excessive discount '{exc}' should be rejected")
            self.assertEqual(reason, "invalid_discount_0.0")

        # Boundary 85% -> accepted
        boundary_row = ["50.0", "85%", "كونكور 5 مجم 30 قرص"]
        item, reason, _ = extract_item_from_group_row(boundary_row, group, "forward", "مخزن تجريبي")
        self.assertIsNotNone(item, "Exact 85% discount should be accepted")
        self.assertEqual(reason, "accepted")
        self.assertAlmostEqual(item["discount_rate"], 0.85, places=2)

    def test_valid_discounts_parsed_correctly_as_decimal_ratios(self):
        """Valid discounts must be parsed correctly as decimal ratios strictly between 0.0 and 0.85."""
        valid_cases = [
            ("20%", 0.20),
            ("20", 0.20),
            ("0.20", 0.20),
            ("15.5%", 0.155),
            ("5%", 0.05),
            ("2.5%", 0.025),
            ("33.3%", 0.333),
            ("85%", 0.85),
            ("٢٠%", 0.20),
            ("١٠%", 0.10),
            ("٣٠%", 0.30),
            ("١٥.٥%", 0.155),
        ]
        for raw, expected in valid_cases:
            ratio = parse_discount(raw)
            self.assertAlmostEqual(ratio, expected, places=3, msg=f"Discount '{raw}' parsed to {ratio}, expected {expected}")


if __name__ == "__main__":
    unittest.main()
