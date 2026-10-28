"""
Empirical Challenger Milestone 1 Iteration 2 Stress Test Suite.
Authored by Challenger 1 (Milestone 1 Iteration 2).

Focus Areas:
1. Corrupt mapping indices (None, str, float, list, tuple, dict, bool, NaN, Inf, out-of-range, negative)
   tested thoroughly with BOTH preview_table_column_mapping AND apply_table_column_mapping.
2. Boundary strings, Unicode variants, edge cases, and attack vectors for validate_catalog_item.
3. Verification that apply_table_column_mapping and apply_field_correction maintain schema integrity
   without crashing, row inflation, or internal metadata leakage.
"""
import copy
import math
import os
import unittest
import pandas as pd

from src.catalog_diagnostics import (
    CatalogResult,
    FileFingerprint,
    GroupDiagnostics,
    ImportDiagnostics,
    PageDiagnostics,
    ReviewIssue,
    RowDiagnostic,
    SourceIdentity,
    METADATA_KEY,
)
from src.catalog_reader import validate_catalog_item
from src.catalog_service import CatalogCorrectionService, STANDARD_COLUMNS


class TestAdversarialCorruptMappingIndices(unittest.TestCase):
    """
    Stress-testing preview_table_column_mapping and apply_table_column_mapping
    with corrupt mapping indices (None, str, float, list, tuple, dict, bool, negative, out-of-range).
    """

    def setUp(self):
        self.service = CatalogCorrectionService("adversarial_iter2_catalog.pdf")
        cols = STANDARD_COLUMNS
        sample_df = pd.DataFrame([
            ["Warehouse A", "Panadol Extra 24tab", "panadol extra 24tab", "standard", "24tab", 45.0, 0.10, True],
            ["Warehouse A", "Augmentin 1g 14tab", "augmentin 1g 14tab", "1g", "14tab", 120.0, 0.15, True],
        ], columns=cols)

        # Table 0 has 2 accepted rows and 2 rejected rows
        r0 = RowDiagnostic(
            page=1, group=0, row=0, table=0, outcome="accepted",
            item_name="Panadol Extra 24tab", raw_cells=["Panadol Extra 24tab", "45.0", "10%", "1"]
        )
        r1 = RowDiagnostic(
            page=1, group=0, row=1, table=0, outcome="accepted",
            item_name="Augmentin 1g 14tab", raw_cells=["Augmentin 1g 14tab", "120.0", "15%", "1"]
        )
        r2 = RowDiagnostic(
            page=1, group=0, row=2, table=0, outcome="rejected", reason="unmapped_columns",
            raw_cells=["100234", "Voltaren 100mg", "75.0", "20%", "1"]
        )
        r3 = RowDiagnostic(
            page=1, group=0, row=3, table=0, outcome="rejected", reason="truncated_row",
            raw_cells=["ShortRow"]
        )

        g = GroupDiagnostics(group=0, strategy="structural", rows=[r0, r1, r2, r3])
        p = PageDiagnostics(page=1, groups=[g])
        diag = ImportDiagnostics(pages=[p], accepted_rows=2, unique_records=2)

        self.service._base_catalog_result = CatalogResult(
            dataframe=sample_df,
            diagnostics=diag,
            fingerprint=FileFingerprint(path="adversarial_iter2_catalog.pdf", sha256="1234567890abcdef"),
        )

        self.corrupt_index_cases = [
            ("None index", {"item_name": None, "base_price": 1, "discount_rate": 2}),
            ("str index", {"item_name": "col_zero", "base_price": "price_col", "discount_rate": "disc"}),
            ("float index", {"item_name": 0.5, "base_price": 1.9, "discount_rate": 2.2}),
            ("float nan/inf", {"item_name": float("nan"), "base_price": float("inf")}),
            ("list index", {"item_name": [0], "base_price": [1, 2]}),
            ("tuple index", {"item_name": (0,), "base_price": (1,)}),
            ("dict index", {"item_name": {"idx": 0}, "base_price": {"idx": 1}}),
            ("bool index True/False", {"item_name": True, "base_price": False}),
            ("negative index", {"item_name": -1, "base_price": -2}),
            ("huge out-of-range index", {"item_name": 999999, "base_price": 888888}),
            ("empty dict mapping", {}),
            ("all None mapping", {"item_name": None, "base_price": None, "discount_rate": None, "stock_status": None}),
        ]

    def test_preview_table_column_mapping_handles_all_corrupt_indices(self):
        """preview_table_column_mapping must not raise any exception for any corrupt index type."""
        for label, mapping in self.corrupt_index_cases:
            with self.subTest(label=label):
                preview = self.service.preview_table_column_mapping(table_id=0, mapping=mapping)
                self.assertIsInstance(preview, list)
                self.assertEqual(len(preview), 4, f"Failed for {label}: expected 4 preview records")
                for rec in preview:
                    self.assertIn("source_id", rec)
                    self.assertIn("raw_cells", rec)
                    self.assertIn("candidate", rec)
                    self.assertIn("valid", rec)
                    self.assertIn("validation_error", rec)
                    self.assertIn("was_previously_accepted", rec)

                    # For corrupt mappings where item_name or base_price are not valid integers,
                    # candidate fields should be None, and valid should be False
                    if label != "empty dict mapping":
                        cand = rec["candidate"]
                        self.assertIsNone(cand.get("item_name"))
                        self.assertFalse(rec["valid"])
                        self.assertIsNotNone(rec["validation_error"])

    def test_apply_table_column_mapping_handles_all_corrupt_indices_atomically(self):
        """
        apply_table_column_mapping with corrupt mapping indices must:
        1. Not crash with TypeError, IndexError, AttributeError.
        2. Safely remove previously accepted rows whose mapped fields are now invalid.
        3. Maintain exactly the 8 STANDARD_COLUMNS in the returned DataFrame.
        4. Accurately update diagnostics (accepted_rows=0 when all rows become invalid).
        5. Successfully recover when reset_corrections() is called.
        """
        for label, mapping in self.corrupt_index_cases:
            with self.subTest(label=label):
                res = self.service.apply_table_column_mapping(table_id=0, mapping=mapping)
                self.assertIsInstance(res, CatalogResult)
                self.assertIsInstance(res.dataframe, pd.DataFrame)

                # Ensure canonical 8 columns without internal metadata leakage
                self.assertEqual(list(res.dataframe.columns), STANDARD_COLUMNS)

                # Because corrupt mappings map item_name to None, all 4 rows in table 0 fail validation
                self.assertEqual(len(res.dataframe), 0, f"Failed for {label}: all invalid rows should be removed")
                self.assertEqual(res.diagnostics.accepted_rows, 0)

                # Verify issues are tracked and unresolved
                unresolved = self.service.list_unresolved_issues()
                self.assertGreaterEqual(len(unresolved), 4)

                # Reset must cleanly restore pristine state
                reset_res = self.service.reset_corrections()
                self.assertEqual(len(reset_res.dataframe), 2)
                self.assertEqual(list(reset_res.dataframe.columns), STANDARD_COLUMNS)
                self.assertEqual(reset_res.diagnostics.accepted_rows, 2)

    def test_apply_table_column_mapping_valid_mapping_after_corrupt_mapping(self):
        """Applying a valid mapping after a corrupt mapping cleanly restores and remaps rows."""
        # 1. Apply corrupt mapping
        self.service.apply_table_column_mapping(table_id=0, mapping={"item_name": "bad", "base_price": None})
        self.assertEqual(len(self.service.get_refreshed_catalog_result().dataframe), 0)

        # 2. Apply valid mapping for Table 0:
        valid_mapping = {"item_name": 0, "base_price": 1, "discount_rate": 2, "stock_status": 3}
        res = self.service.apply_table_column_mapping(table_id=0, mapping=valid_mapping)
        self.assertEqual(len(res.dataframe), 2)
        self.assertEqual(list(res.dataframe.columns), STANDARD_COLUMNS)
        self.assertIn("Panadol Extra 24tab", res.dataframe["item_name"].values)
        self.assertIn("Augmentin 1g 14tab", res.dataframe["item_name"].values)


class TestAdversarialValidateCatalogItemBoundaryStrings(unittest.TestCase):
    """
    Exhaustive empirical testing of validate_catalog_item against boundary strings,
    Unicode representations, control characters, extreme values, and security edge cases.
    """

    def test_name_empty_and_whitespace_boundary_strings(self):
        """Names that are empty or whitespace-only must be rejected."""
        empty_cases = [
            "",
            " ",
            "   ",
            "\t",
            "\n",
            "\r\n",
            "   \t\n  ",
            "\u00A0",          # Non-breaking space
            "\u2000",          # En quad
            "\u200B",          # Zero-width space
            "\u3000",          # Ideographic space
        ]
        for s in empty_cases:
            valid, err = validate_catalog_item({"item_name": s, "base_price": 50.0})
            self.assertFalse(valid, f"Expected empty/whitespace string {repr(s)} to be rejected")
            self.assertIn(err, ["empty_item_name", "name_too_short"])

    def test_name_short_boundary_strings(self):
        """Single-character names must be rejected as name_too_short."""
        short_cases = ["A", "1", "د", "x", "!", ".", "-"]
        for s in short_cases:
            valid, err = validate_catalog_item({"item_name": s, "base_price": 50.0})
            self.assertFalse(valid, f"Expected 1-char name {repr(s)} to be rejected")
            self.assertEqual(err, "name_too_short")

    def test_name_header_token_boundary_strings(self):
        """Exact header tokens and variations with surrounding punctuation must be rejected."""
        header_cases = [
            "name", "NAME", "Name", "item", "ITEM", "Item Name", "PRODUCT", "Description",
            "سعر", "السعر", "سعر الجمهور", "جمهور", "رسمي", "price", "PRICE", "Base Price",
            "خصم", "الخصم", "نسبة", "نسبة الخصم", "discount", "DISCOUNT", "disc%", "disc %",
            "رصيد", "كمية", "الكمية", "حالة", "توفر", "متاح", "stock", "qty", "Status",
            "كود", "code", "item code", "باركود", "barcode", "مسلسل",
            # Reversed Arabic header tokens from right-to-left PDF extraction
            "فنصلا", "فنصلا مسا", "رعسلا", "رعس", "مصخلا", "مصخ", "منسصالا", "فنصلفا",
            # Tokens with punctuation
            "name:", "item#", "--price--", "سعر:", "[الخصم]", "code.",
        ]
        for s in header_cases:
            valid, err = validate_catalog_item({"item_name": s, "base_price": 50.0})
            self.assertFalse(valid, f"Expected header token {repr(s)} to be rejected")
            self.assertIn("header_token_in_name", err)

    def test_name_catalog_noise_boundary_strings(self):
        """Catalog noise (page numbers, dates, vendor software credits) must be rejected."""
        noise_cases = [
            "صفحة 1 من 10",
            "Page 1 of 5",
            "اورجا سوفت لتجارة وتوزيع الأدوية",
            "مخزن الفارس لتجارة الادوية",
            "تليفون: 01012345678",
            "هاتف: 0223456789",
            "سجل تجاري 12345",
            "بطاقة ضريبية 67890",
            "12/10/2026",
            "09:30 AM",
            "05:02:58 م",
            "السبت 10 سبتمبر 2026",
        ]
        for s in noise_cases:
            valid, err = validate_catalog_item({"item_name": s, "base_price": 50.0})
            self.assertFalse(valid, f"Expected catalog noise {repr(s)} to be rejected")
            self.assertIn("catalog_noise_in_name", err)

    def test_name_valid_complex_multilingual_strings(self):
        """Valid Arabic, English, and mixed pharmaceutical names within length limits must be accepted."""
        valid_cases = [
            "Panadol Extra 24tab",
            "بانادول اكسترا 24 قرص",
            "Augmentin 1g 14tab (أوجمنتين)",
            "Cataflam 50mg / كافلام",
            "Amoxil 500mg Cap (أموسيل)",
            "CONGESTAL 20 TAB",
            "Omega 3 Plus 30 Cap",
            "Vit C 1000mg Effervescent",
            "Antinal 24 Cap (أنتينال)",
            # 80-character valid long medication name (within 90-char boundary)
            "Amoxicillin and Clavulanate Potassium Tablets USP 875mg / 125mg 14 Film-Coated Tab",
        ]
        for s in valid_cases:
            valid, err = validate_catalog_item({"item_name": s, "base_price": 50.0})
            self.assertTrue(valid, f"Expected valid name {repr(s)} to be accepted, err={err}")
            self.assertIsNone(err)

    def test_name_length_safeguard_beyond_90_chars_rejected_as_noise(self):
        """Item names longer than 90 characters are treated as non-product catalog noise/banners."""
        long_name = "Panadol " * 20 + "500mg"  # > 90 characters
        self.assertGreater(len(long_name), 90)
        valid, err = validate_catalog_item({"item_name": long_name, "base_price": 50.0})
        self.assertFalse(valid)
        self.assertIn("catalog_noise_in_name", err)

    def test_price_boundary_strings(self):
        """Exhaustive boundary testing for price strings."""
        # Price == 0 or negative: Must be rejected
        zero_and_neg_strings = [
            "0", "0.0", "0.00", "0.000", "-0", "-0.0", "-0.00",
            "-0.001", "-1", "-1.0", "-50.5", "-9999.99",
            "٠", "٠.٠", "٠.٠٠", "-٥٠", "-١٠٠.٥",
        ]
        for p in zero_and_neg_strings:
            valid, err = validate_catalog_item({"item_name": "Panadol 500mg", "base_price": p})
            self.assertFalse(valid, f"Expected zero/negative price {repr(p)} to be rejected")
            self.assertIn("invalid_price_zero_or_negative", err)

        # Price >= 10000: Must be rejected
        upper_bound_strings = [
            "10000", "10000.0", "10000.00", "10000.01", "10001", "50000", "999999",
            "١٠٠٠٠", "١٠٠٠٠.٠", "١٠٠٠١", "٥٠٠٠٠",
        ]
        for p in upper_bound_strings:
            valid, err = validate_catalog_item({"item_name": "Panadol 500mg", "base_price": p})
            self.assertFalse(valid, f"Expected out-of-bounds price {repr(p)} to be rejected")
            self.assertIn("invalid_price_out_of_bounds", err)

        # Valid price strings: Must be accepted
        valid_price_strings = [
            "0.01", "0.5", "1", "1.0", "45.00", "120.75", "9999.99",
            "١", "٤٥.٠", "١٢٠.٧٥", "٩٩٩٩.٩٩",
            "45,50", "١٢٠,٧٥",  # Comma decimal separator
            "  45.0  ",          # Leading/trailing whitespace
        ]
        for p in valid_price_strings:
            valid, err = validate_catalog_item({"item_name": "Panadol 500mg", "base_price": p})
            self.assertTrue(valid, f"Expected valid price {repr(p)} to be accepted, err={err}")
            self.assertIsNone(err)

        # Malformed price strings: Must be rejected with invalid_price_format or invalid_price_nan_or_inf
        malformed_price_strings = [
            "free", "مجانا", "N/A", "EGP 50", "50 LE", "price: 45",
            "1.2.3", "45..0", "abc", "", "   ", "\t",
            "nan", "NaN", "inf", "-inf", "Infinity",
        ]
        for p in malformed_price_strings:
            valid, err = validate_catalog_item({"item_name": "Panadol 500mg", "base_price": p})
            self.assertFalse(valid, f"Expected malformed price {repr(p)} to be rejected")
            self.assertTrue(
                "invalid_price_format" in err or "invalid_price_nan_or_inf" in err,
                f"Unexpected err message for {repr(p)}: {err}"
            )

    def test_discount_explicit_zero_boundary_strings(self):
        """Explicit zero discount representations must be accepted and recognized."""
        explicit_zero_strings = [
            "0", "0%", "0.0", "0.00%", "0.0%",
            "٠", "٠%", "٠.٠%",
            "صافي", "صافى", "صا في", "بدون خصم", "نقدى",
            "  صافي  ", " 0% ", " 0.0 ",
        ]
        for d in explicit_zero_strings:
            valid, err = validate_catalog_item({
                "item_name": "Panadol 500mg", "base_price": 50.0, "discount_rate": d
            })
            self.assertTrue(valid, f"Expected explicit zero discount {repr(d)} to be accepted, err={err}")
            self.assertIsNone(err)

    def test_discount_blank_strings_treated_as_blank(self):
        """Blank or whitespace-only discount strings must be treated as valid blank discount (None)."""
        blank_discount_strings = ["", " ", "   ", "\t", "\n"]
        for d in blank_discount_strings:
            valid, err = validate_catalog_item({
                "item_name": "Panadol 500mg", "base_price": 50.0, "discount_rate": d
            })
            self.assertTrue(valid, f"Expected blank discount {repr(d)} to be accepted as blank, err={err}")
            self.assertIsNone(err)

    def test_discount_valid_percentage_and_decimal_boundary_strings(self):
        """Discounts from 0.01% through 85% must be accepted."""
        valid_discount_strings = [
            # Explicit percentages
            "0.01%", "1%", "5%", "10%", "15.5%", "20%", "33.33%", "50%", "85%", "85.0%", "85.00%",
            # Eastern Arabic percentages
            "١%", "١٠%", "١٥.٥%", "٨٥%", "٨٥.٠%",
            # Comma decimal percentages
            "15,5%", "85,0%", "١٥,٥%",
            # Decimal forms <= 0.85
            "0.01", "0.10", "0.155", "0.50", "0.85", "0.8500",
            # Wholesale whole numbers without % scaled by 100
            "15", "20", "85", "١٥", "٨٥",
            # Wholesale decimal percentages without % scaled by 100 (e.g., 1.5% discount)
            "1.5", "2.5",
            # Whitespace padded
            "  15%  ", " 0.20 ", " 85% ",
        ]
        for d in valid_discount_strings:
            valid, err = validate_catalog_item({
                "item_name": "Panadol 500mg", "base_price": 50.0, "discount_rate": d
            })
            self.assertTrue(valid, f"Expected valid discount {repr(d)} to be accepted, err={err}")
            self.assertIsNone(err)

    def test_discount_out_of_bounds_high_strings(self):
        """Discounts strictly greater than 85% (0.85) must be rejected."""
        high_discount_strings = [
            # Percentages > 85%
            "85.01%", "85.1%", "86%", "90%", "95%", "99%", "100%", "150%", "200%",
            "٨٥.١%", "٩٠%", "١٠٠%",
            # Decimal strings > 0.85
            "0.8501", "0.851", "0.86", "0.90", "1.0",
            # Whole numbers without % > 85 (scaled by 100 > 0.85)
            "86", "90", "100", "150", "200",
            "85,01%", "85,1%",
        ]
        for d in high_discount_strings:
            valid, err = validate_catalog_item({
                "item_name": "Panadol 500mg", "base_price": 50.0, "discount_rate": d
            })
            self.assertFalse(valid, f"Expected high discount {repr(d)} to be rejected")
            self.assertIn("invalid_discount_out_of_bounds", err)

    def test_discount_negative_boundary_strings(self):
        """Negative discounts must be rejected."""
        negative_discount_strings = [
            "-0.001%", "-0.01%", "-1%", "-5%", "-10%", "-85%",
            "-0.01", "-0.1", "-0.5",
            "-١%", "-٥%", "-١٠%",
        ]
        for d in negative_discount_strings:
            valid, err = validate_catalog_item({
                "item_name": "Panadol 500mg", "base_price": 50.0, "discount_rate": d
            })
            self.assertFalse(valid, f"Expected negative discount {repr(d)} to be rejected")
            self.assertIn("invalid_discount_negative", err)

    def test_discount_malformed_and_special_strings(self):
        """Malformed, non-numeric, or NaN/Inf discount strings must be rejected."""
        malformed_cases = [
            "free", "special", "N/A", "%", "%%", "1.2.3%", "abc",
            "nan", "NaN", "inf", "-inf", "Infinity",
            "nan%", "NaN%", "inf%",
        ]
        for d in malformed_cases:
            valid, err = validate_catalog_item({
                "item_name": "Panadol 500mg", "base_price": 50.0, "discount_rate": d
            })
            self.assertFalse(valid, f"Expected malformed discount {repr(d)} to be rejected")
            self.assertTrue(
                "invalid_discount_format" in err or "invalid_discount_nan_or_inf" in err,
                f"Unexpected err message for {repr(d)}: {err}"
            )

    def test_boolean_rejection_for_price_and_discount(self):
        """Booleans True/False must be strictly rejected for price and discount."""
        # Price boolean
        valid, err = validate_catalog_item({"item_name": "Panadol 500mg", "base_price": True})
        self.assertFalse(valid)
        self.assertEqual(err, "invalid_price_boolean")

        valid, err = validate_catalog_item({"item_name": "Panadol 500mg", "base_price": False})
        self.assertFalse(valid)
        self.assertEqual(err, "invalid_price_boolean")

        # Discount boolean
        valid, err = validate_catalog_item({"item_name": "Panadol 500mg", "base_price": 50.0, "discount_rate": True})
        self.assertFalse(valid)
        self.assertEqual(err, "invalid_discount_boolean")

        valid, err = validate_catalog_item({"item_name": "Panadol 500mg", "base_price": 50.0, "discount_rate": False})
        self.assertFalse(valid)
        self.assertEqual(err, "invalid_discount_boolean")


class TestAdversarialApplyFieldCorrectionStress(unittest.TestCase):
    """Stress-testing apply_field_correction with boundary and corrupt field values."""

    def setUp(self):
        self.service = CatalogCorrectionService("adversarial_stress_corrections.pdf")
        cols = STANDARD_COLUMNS
        sample_df = pd.DataFrame([
            ["Warehouse 1", "Concor 5mg 30tab", "concor 5mg 30tab", "5mg", "30tab", 60.0, 0.10, True],
        ], columns=cols)

        r0 = RowDiagnostic(
            page=1, group=0, row=0, table=0, outcome="accepted",
            item_name="Concor 5mg 30tab", raw_cells=["Concor 5mg 30tab", "60.0", "10%"]
        )
        r1 = RowDiagnostic(
            page=1, group=0, row=1, table=0, outcome="rejected", reason="invalid_price",
            raw_cells=["Concor 10mg 30tab", "-60.0", "10%"]
        )

        g = GroupDiagnostics(group=0, strategy="structural", rows=[r0, r1])
        p = PageDiagnostics(page=1, groups=[g])
        diag = ImportDiagnostics(pages=[p], accepted_rows=1, unique_records=1)

        self.service._base_catalog_result = CatalogResult(
            dataframe=sample_df,
            diagnostics=diag,
            fingerprint=FileFingerprint(path="adversarial_stress_corrections.pdf", sha256="aabbccddeeff"),
        )

    def test_invalid_field_corrections_raise_value_error(self):
        """apply_field_correction must raise ValueError and not mutate state when given invalid inputs."""
        invalid_corrections = [
            ("boolean price", {"item_name": "Concor 5mg", "base_price": True}),
            ("boolean discount", {"item_name": "Concor 5mg", "base_price": 60.0, "discount_rate": False}),
            ("zero price", {"item_name": "Concor 5mg", "base_price": 0.0}),
            ("negative price", {"item_name": "Concor 5mg", "base_price": -10.0}),
            ("out of bounds price", {"item_name": "Concor 5mg", "base_price": 15000.0}),
            ("negative discount", {"item_name": "Concor 5mg", "base_price": 60.0, "discount_rate": "-5%"}),
            ("high discount", {"item_name": "Concor 5mg", "base_price": 60.0, "discount_rate": "90%"}),
            ("malformed discount", {"item_name": "Concor 5mg", "base_price": 60.0, "discount_rate": "invalid_str"}),
            ("header token name", {"item_name": "اسم الصنف", "base_price": 60.0}),
            ("empty name", {"item_name": "   ", "base_price": 60.0}),
            ("short name", {"item_name": "C", "base_price": 60.0}),
        ]
        orig_df = self.service.get_refreshed_catalog_result().dataframe.copy()
        orig_unresolved = len(self.service.list_unresolved_issues())

        for label, update in invalid_corrections:
            with self.subTest(label=label):
                with self.assertRaises(ValueError):
                    self.service.apply_field_correction("p1_t0_r1", update)

                # State must remain identical
                current_df = self.service.get_refreshed_catalog_result().dataframe
                self.assertEqual(len(current_df), len(orig_df))
                self.assertEqual(len(self.service.list_unresolved_issues()), orig_unresolved)

    def test_valid_boundary_corrections_succeed_without_row_inflation(self):
        """Valid boundary corrections succeed, resolve issues, and do not duplicate rows."""
        # Correct the rejected issue p1_t0_r1 with boundary values: price=9999.99, discount=85%
        valid_update = {
            "item_name": "Concor 10mg 30tab",
            "base_price": 9999.99,
            "discount_rate": "85%",
            "stock_status": True,
        }
        res = self.service.apply_field_correction("p1_t0_r1", valid_update)
        self.assertEqual(len(res.dataframe), 2)
        self.assertEqual(list(res.dataframe.columns), STANDARD_COLUMNS)
        self.assertEqual(res.diagnostics.accepted_rows, 2)

        # Repeatedly update the same item name (rename stress)
        rename_1 = {"item_name": "Concor Cor 2.5mg", "base_price": 40.0, "discount_rate": "15%"}
        res2 = self.service.apply_field_correction("p1_t0_r1", rename_1)
        self.assertEqual(len(res2.dataframe), 2, "Row count must remain 2 after rename")
        self.assertIn("Concor Cor 2.5mg", res2.dataframe["item_name"].values)
        self.assertNotIn("Concor 10mg 30tab", res2.dataframe["item_name"].values)

        rename_2 = {"item_name": "Bisoprolol 2.5mg", "base_price": 30.0, "discount_rate": "0%"}
        res3 = self.service.apply_field_correction("p1_t0_r1", rename_2)
        self.assertEqual(len(res3.dataframe), 2, "Row count must remain 2 after second rename")
        self.assertIn("Bisoprolol 2.5mg", res3.dataframe["item_name"].values)


if __name__ == "__main__":
    unittest.main()
