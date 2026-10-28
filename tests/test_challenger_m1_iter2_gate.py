import unittest
from typing import List, Any
from src.catalog_reader import (
    classify_column_role,
    analyze_table_geometry,
    detect_product_groups,
    parse_structural_table,
    TableGeometry,
    ProductGroup,
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


class TestChallengerM1Iter2Gate(unittest.TestCase):
    """
    Independent Empirical Verification Suite for Milestone 1 Iteration 2 Gate Check.
    Authored by Challenger 1.
    """

    # ------------------------------------------------------------------------
    # TASK 1: DEFECT 1 RESOLUTION (DIVISIBILITY & MULTI-GROUP RECOGNITION)
    # ------------------------------------------------------------------------

    def test_task1_10_column_table_serial_plus_three_groups_of_three(self):
        """
        10-column table: Col 0 serial + 3 groups of 3 (Price, Discount, Name).
        Verify 3 groups detected and 6 items extracted without collapse.
        """
        data = [
            ["م", "سعر", "خصم", "صنف", "سعر", "خصم", "صنف", "سعر", "خصم", "صنف"],
            ["1", "50.0", "20%", "دواء 1", "70.0", "30%", "دواء 2", "90.0", "25%", "دواء 3"],
            ["2", "60.0", "22%", "دواء 4", "80.0", "32%", "دواء 5", "100.0", "28%", "دواء 6"],
        ]
        table = MockTable(data)
        items, geom, groups, diag = parse_structural_table(table, 0, "test_vendor")

        self.assertEqual(len(groups), 3, f"Expected 3 groups, got {len(groups)}")
        self.assertEqual(len(items), 6, f"Expected 6 items, got {len(items)}")
        self.assertEqual(diag.accepted_rows, 6)
        self.assertEqual(sum(g.rejected_rows for g in diag.groups), 0)

        # Check group 0 spans cols 1..3, group 1 spans 4..6, group 2 spans 7..9
        self.assertEqual(groups[0].raw_cols, [1, 2, 3])
        self.assertEqual(groups[1].raw_cols, [4, 5, 6])
        self.assertEqual(groups[2].raw_cols, [7, 8, 9])

        # Verify extracted items values (items are extracted group-by-group: G0 rows, then G1 rows, etc.)
        item_names = [it["item_name"] for it in items]
        self.assertEqual(item_names, ["دواء 1", "دواء 4", "دواء 2", "دواء 5", "دواء 3", "دواء 6"])

    def test_task1_7_column_table_serial_plus_two_groups_of_three(self):
        """
        7-column table: Col 0 serial + 2 groups of 3 (Price, Discount, Name).
        Verify 2 groups detected and 4 items extracted.
        """
        data = [
            ["م", "سعر", "خصم", "صنف", "سعر", "خصم", "صنف"],
            ["1", "50.0", "20%", "دواء 1", "70.0", "30%", "دواء 2"],
            ["2", "60.0", "22%", "دواء 3", "80.0", "32%", "دواء 4"],
        ]
        table = MockTable(data)
        items, geom, groups, diag = parse_structural_table(table, 0, "test_vendor")

        self.assertEqual(len(groups), 2, f"Expected 2 groups, got {len(groups)}")
        self.assertEqual(len(items), 4, f"Expected 4 items, got {len(items)}")
        self.assertEqual(diag.accepted_rows, 4)
        self.assertEqual(sum(g.rejected_rows for g in diag.groups), 0)
        self.assertEqual(groups[0].raw_cols, [1, 2, 3])
        self.assertEqual(groups[1].raw_cols, [4, 5, 6])

    def test_task1_13_column_table_serial_plus_three_groups_of_four(self):
        """
        13-column table: Col 0 serial + 3 groups of 4 (Code, Name, Price, Discount).
        Verify 3 groups detected and 6 items extracted.
        """
        data = [
            ["م", "كود", "صنف", "سعر", "خصم", "كود", "صنف", "سعر", "خصم", "كود", "صنف", "سعر", "خصم"],
            ["1", "C1", "دواء 1", "50.0", "20%", "C2", "دواء 2", "70.0", "30%", "C3", "دواء 3", "90.0", "25%"],
            ["2", "C4", "دواء 4", "60.0", "22%", "C5", "دواء 5", "80.0", "32%", "C6", "دواء 6", "100.0", "28%"],
        ]
        table = MockTable(data)
        items, geom, groups, diag = parse_structural_table(table, 0, "test_vendor")

        self.assertEqual(len(groups), 3, f"Expected 3 groups, got {len(groups)}")
        self.assertEqual(len(items), 6, f"Expected 6 items, got {len(items)}")
        self.assertEqual(diag.accepted_rows, 6)
        self.assertEqual(groups[0].raw_cols, [1, 2, 3, 4])
        self.assertEqual(groups[1].raw_cols, [5, 6, 7, 8])
        self.assertEqual(groups[2].raw_cols, [9, 10, 11, 12])

    def test_task1_13_column_table_serial_plus_four_groups_of_three(self):
        """
        13-column table: Col 0 serial + 4 groups of 3 (Price, Discount, Name).
        Verify 4 groups detected and 8 items extracted.
        """
        data = [
            ["م", "سعر", "خصم", "صنف", "سعر", "خصم", "صنف", "سعر", "خصم", "صنف", "سعر", "خصم", "صنف"],
            ["1", "10.0", "10%", "د1", "20.0", "20%", "د2", "30.0", "30%", "د3", "40.0", "40%", "د4"],
            ["2", "11.0", "11%", "د5", "21.0", "21%", "د6", "31.0", "31%", "د7", "41.0", "41%", "د8"],
        ]
        table = MockTable(data)
        items, geom, groups, diag = parse_structural_table(table, 0, "test_vendor")

        self.assertEqual(len(groups), 4, f"Expected 4 groups, got {len(groups)}")
        self.assertEqual(len(items), 8, f"Expected 8 items, got {len(items)}")

    def test_task1_10_column_table_trailing_code_column(self):
        """
        10-column table: 3 groups of 3 (Price, Discount, Name) + 1 trailing code column.
        Start offset is 0, trailing column at index 9.
        Verify 3 groups detected and 6 items extracted.
        """
        data = [
            ["سعر", "خصم", "صنف", "سعر", "خصم", "صنف", "سعر", "خصم", "صنف", "ملاحظات"],
            ["50.0", "20%", "دواء 1", "70.0", "30%", "دواء 2", "90.0", "25%", "دواء 3", "ملاحظة 1"],
            ["60.0", "22%", "دواء 4", "80.0", "32%", "دواء 5", "100.0", "28%", "دواء 6", "ملاحظة 2"],
        ]
        table = MockTable(data)
        items, geom, groups, diag = parse_structural_table(table, 0, "test_vendor")

        self.assertEqual(len(groups), 3, f"Expected 3 groups, got {len(groups)}")
        self.assertEqual(len(items), 6, f"Expected 6 items, got {len(items)}")

    def test_task1_11_column_table_leading_serial_and_trailing_notes(self):
        """
        11-column table: Col 0 serial + 3 groups of 3 + Col 10 notes.
        Start offset is 1, trailing column at index 10.
        Verify 3 groups detected and 6 items extracted.
        """
        data = [
            ["م", "سعر", "خصم", "صنف", "سعر", "خصم", "صنف", "سعر", "خصم", "صنف", "ملاحظات"],
            ["1", "50.0", "20%", "دواء 1", "70.0", "30%", "دواء 2", "90.0", "25%", "دواء 3", "N1"],
            ["2", "60.0", "22%", "دواء 4", "80.0", "32%", "دواء 5", "100.0", "28%", "دواء 6", "N2"],
        ]
        table = MockTable(data)
        items, geom, groups, diag = parse_structural_table(table, 0, "test_vendor")

        self.assertEqual(len(groups), 3, f"Expected 3 groups, got {len(groups)}")
        self.assertEqual(len(items), 6, f"Expected 6 items, got {len(items)}")

    # ------------------------------------------------------------------------
    # TASK 2: DEFECT 2 RESOLUTION (SERIAL ROLE CLASSIFICATION & DISCOUNT GATING)
    # ------------------------------------------------------------------------

    def test_task2_serial_abbreviations_classified_as_code(self):
        """
        Verify all standard serial header abbreviations classify as 'code', NOT 'discount'.
        """
        serial_tokens = ["م", "م.", "م/", "م /", "م .", "ت", "ت.", "ت/", "ت /", "#", "no", "no.", "id", "sn", "seq", "sr"]
        sample_integers = ["1", "2", "3", "4", "5"]

        for token in serial_tokens:
            role = classify_column_role(token, sample_integers)
            self.assertEqual(role, "code", f"Header token '{token}' should be 'code', got '{role}'")

    def test_task2_compound_code_headers_priority(self):
        """
        Verify compound code headers return 'code' despite containing 'صنف' (name keyword).
        """
        compound_headers = [
            "رقم الصنف",
            "كود الصنف",
            "item code",
            "product code",
            "فنصلا مقر",
            "مقر فنصلا",
            "دوك فنصلا",
            "فنصلا دوك",
        ]
        for h in compound_headers:
            role = classify_column_role(h, ["1001", "1002"])
            self.assertEqual(role, "code", f"Compound header '{h}' should classify as 'code', got '{role}'")

    def test_task2_single_group_serial_plus_discount(self):
        """
        Test table with ['م', 'اسم الصنف', 'سعر الجمهور', 'الخصم']:
        Verify discount_col is 3, code_col is 0, and items are NOT rejected.
        """
        data = [
            ["م", "اسم الصنف", "سعر الجمهور", "الخصم"],
            ["1", "كونكور 5 مجم", "40.0", "20%"],
            ["2", "بنادول 500", "50.0", "15%"],
        ]
        table = MockTable(data)
        items, geom, groups, diag = parse_structural_table(table, 0, "مخزن تجريبي")

        self.assertEqual(len(groups), 1)
        g = groups[0]
        self.assertEqual(g.code_col, 0, f"Expected code_col to be 0, got {g.code_col}")
        self.assertEqual(g.discount_col, 3, f"Expected discount_col to be 3, got {g.discount_col}")
        self.assertEqual(g.name_col, 1, f"Expected name_col to be 1, got {g.name_col}")
        self.assertEqual(g.price_col, 2, f"Expected price_col to be 2, got {g.price_col}")

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["discount_rate"], 0.20)
        self.assertEqual(items[1]["discount_rate"], 0.15)
        self.assertEqual(diag.accepted_rows, 2)
        self.assertEqual(sum(g.rejected_rows for g in diag.groups), 0)

    def test_task2_sequential_integers_without_header_classified_as_code(self):
        """
        When header is empty or unknown, sequential positive integers (1, 2, 3...)
        should be classified as 'code', never 'discount'.
        """
        role = classify_column_role("", ["1", "2", "3", "4"])
        self.assertEqual(role, "code", f"Empty header with sequential ints should be 'code', got '{role}'")

        role_unknown = classify_column_role("col_x", ["1", "2", "3"])
        self.assertEqual(role_unknown, "code", f"Unknown header with sequential ints should be 'code', got '{role_unknown}'")

    def test_task2_plain_numbers_never_classified_as_discount_without_percent(self):
        """
        Plain numbers (like prices 40.0, 50.0) without % sign or discount header
        should classify as 'price', never 'discount'.
        """
        role = classify_column_role("", ["40.0", "55.5", "120.0"])
        self.assertEqual(role, "price", f"Plain numbers without % should classify as 'price', got '{role}'")

        # Explicit percent sign should classify as discount
        role_pct = classify_column_role("", ["20%", "15%", "30%"])
        self.assertEqual(role_pct, "discount", f"Percent values should classify as 'discount', got '{role_pct}'")

    def test_task2_explicit_zero_discount_terms_classified_as_discount(self):
        """
        Explicit zero discount terms ('صافي', 'صافى', 'نقدى') without discount header
        should classify as 'discount'.
        """
        role = classify_column_role("", ["صافي", "صافى", "نقدى"])
        self.assertEqual(role, "discount")

    # ------------------------------------------------------------------------
    # ADVERSARIAL STRESS TESTS: BOUNDARIES, OFFSETS & AMBIGUOUS HEADERS
    # ------------------------------------------------------------------------

    def test_stress_8_column_table_with_offset_2(self):
        """
        8 columns: Col 0 Serial ('م'), Col 1 Code ('كود'), followed by 2 groups of 3 (Price, Disc, Name).
        Requires start_offset = 2.
        Verify 2 groups detected and 4 items extracted.
        """
        data = [
            ["م", "كود", "سعر", "خصم", "صنف", "سعر", "خصم", "صنف"],
            ["1", "C01", "50.0", "20%", "دواء 1", "70.0", "30%", "دواء 2"],
            ["2", "C02", "60.0", "22%", "دواء 3", "80.0", "32%", "دواء 4"],
        ]
        table = MockTable(data)
        items, geom, groups, diag = parse_structural_table(table, 0, "test_vendor")

        self.assertEqual(len(groups), 2)
        self.assertEqual(len(items), 4)
        self.assertEqual(groups[0].raw_cols, [2, 3, 4])
        self.assertEqual(groups[1].raw_cols, [5, 6, 7])

    def test_stress_reversed_arabic_compound_header(self):
        """
        Reversed Arabic compound code header: 'فنصلا مقر' ('رقم الصنف' reversed).
        Verify it classifies as 'code', not 'name'.
        """
        role = classify_column_role("فنصلا مقر", ["1001", "1002"])
        self.assertEqual(role, "code")

        role_reversed_code = classify_column_role("دوك فنصلا", ["C1", "C2"])
        self.assertEqual(role_reversed_code, "code")

    def test_stress_headerless_multi_group_table(self):
        """
        Table with completely blank headers: Col 0 serial, followed by 2 groups of 3.
        Headers are all empty strings. Roles inferred purely from body cells.
        """
        data = [
            ["", "", "", "", "", "", ""],
            ["1", "50.0", "20%", "دواء أول", "70.0", "30%", "دواء ثان"],
            ["2", "60.0", "22%", "دواء ثالث", "80.0", "32%", "دواء رابع"],
            ["3", "65.0", "25%", "دواء خامس", "85.0", "35%", "دواء سادس"],
        ]
        table = MockTable(data)
        items, geom, groups, diag = parse_structural_table(table, 0, "test_vendor")

        self.assertEqual(len(groups), 2)
        self.assertEqual(len(items), 6)
        self.assertEqual(diag.accepted_rows, 6)

    def test_stress_non_1_starting_sequential_code(self):
        """
        Sequential codes starting at 101, 102, 103 with empty header.
        Should classify as 'code', not 'price' or 'discount'.
        """
        role = classify_column_role("", ["101", "102", "103", "104"])
        self.assertEqual(role, "code")

    def test_stress_discount_never_assigned_to_small_prices_without_percent(self):
        """
        Prices in small range (e.g. 5.0, 10.0, 15.0 EGP) without percent or discount header
        must NOT be classified as discount, even though 5.0 <= 85.0.
        """
        role = classify_column_role("", ["5.0", "12.5", "8.0", "15.0"])
        self.assertEqual(role, "price")


if __name__ == "__main__":
    unittest.main()
