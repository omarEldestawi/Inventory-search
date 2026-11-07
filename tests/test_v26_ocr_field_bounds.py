import unittest
from unittest.mock import MagicMock
import numpy as np

from src.catalog_diagnostics import ReviewIssue, SourceIdentity
from src.catalog_recovery import _evaluate_ocr_candidate_on_crop, recover_by_coordinates
from src.ocr_engine import ArabicOCREngine


class TestOCRFieldBounds(unittest.TestCase):
    """
    Unit tests verifying that OCR field assignment strictly uses source-column bounds
    rather than value heuristics, prevents price/discount collisions, ignores nearby codes,
    and preserves missing discount as None unless explicitly zero.
    """

    def setUp(self):
        self.mock_ocr = MagicMock(spec=ArabicOCREngine)
        # Dummy 100x500 image with ink
        self.dummy_img = np.zeros((100, 500, 3), dtype=np.uint8)

    def test_equal_price_and_discount_numbers_not_skipped(self):
        """
        Verify that when price value equals discount percentage (e.g. price 20.0 and discount 20%),
        the price is NOT skipped and neither field overwrites the other.
        """
        # Column bounds in points: discount [0, 100], name [100, 350], code [350, 420], price [420, 500]
        col_bounds = {
            "discount": (0.0, 100.0),
            "name": (100.0, 350.0),
            "code": (350.0, 420.0),
            "price": (420.0, 500.0),
        }
        issue = ReviewIssue(
            source_id="p1_t0_r1",
            identity=SourceIdentity(page=1, table=0, row=1),
            bbox=[0.0, 10.0, 500.0, 40.0],
            column_bounds=col_bounds,
            rejection_reason="ocr_recovery_needed",
        )

        # Boxes:
        # Discount column [0, 100]: "20%" at x=50
        # Name column [100, 350]: "كونكور 5 مجم" at x=200
        # Price column [420, 500]: "20.00" at x=460
        self.mock_ocr.extract_text_boxes.return_value = [
            {"bbox": [30, 10, 70, 30], "text": "20%", "confidence": 0.95, "engine": "test"},
            {"bbox": [150, 10, 250, 30], "text": "كونكور 5 مجم", "confidence": 0.95, "engine": "test"},
            {"bbox": [440, 10, 480, 30], "text": "20.00", "confidence": 0.95, "engine": "test"},
        ]

        cand = _evaluate_ocr_candidate_on_crop(
            self.dummy_img, self.mock_ocr, default_wh="TestWholesaler", issue=issue
        )
        self.assertIsNotNone(cand)
        self.assertEqual(cand["base_price"], 20.0)
        self.assertAlmostEqual(cand["discount_rate"], 0.20, places=4)
        self.assertIn("كونكور", cand["item_name"])

    def test_nearby_product_code_does_not_overwrite_price(self):
        """
        Verify that a product code (e.g. 4501) adjacent to price (45.00) in coordinate bounds
        is categorized as 'code' and does not overwrite or replace the price.
        """
        col_bounds = {
            "discount": (0.0, 100.0),
            "name": (100.0, 330.0),
            "code": (330.0, 410.0),
            "price": (410.0, 500.0),
        }
        issue = ReviewIssue(
            source_id="p1_t0_r2",
            identity=SourceIdentity(page=1, table=0, row=2),
            bbox=[0.0, 10.0, 500.0, 40.0],
            column_bounds=col_bounds,
            rejection_reason="ocr_recovery_needed",
        )

        # Code box at x=370, Price box at x=455
        self.mock_ocr.extract_text_boxes.return_value = [
            {"bbox": [20, 10, 60, 30], "text": "10%", "confidence": 0.95, "engine": "test"},
            {"bbox": [120, 10, 240, 30], "text": "بنادول اكسترا", "confidence": 0.95, "engine": "test"},
            {"bbox": [350, 10, 390, 30], "text": "4501", "confidence": 0.95, "engine": "test"},  # Code
            {"bbox": [435, 10, 475, 30], "text": "45.00", "confidence": 0.95, "engine": "test"}, # Price
        ]

        cand = _evaluate_ocr_candidate_on_crop(
            self.dummy_img, self.mock_ocr, default_wh="TestWholesaler", issue=issue
        )
        self.assertIsNotNone(cand)
        self.assertEqual(cand["base_price"], 45.0)  # Must be 45.0, NOT 4501
        self.assertAlmostEqual(cand["discount_rate"], 0.10, places=4)

    def test_multiple_numeric_tokens_in_row_band(self):
        """
        Verify that multiple numeric tokens across different columns
        (pack size 10 in name, code 9920 in code, price 120.0, discount 15%)
        are correctly bound to their columns without bleeding.
        """
        col_bounds = {
            "discount": (0.0, 100.0),
            "name": (100.0, 350.0),
            "code": (350.0, 420.0),
            "price": (420.0, 500.0),
        }
        issue = ReviewIssue(
            source_id="p1_t0_r3",
            identity=SourceIdentity(page=1, table=0, row=3),
            bbox=[0.0, 10.0, 500.0, 40.0],
            column_bounds=col_bounds,
            rejection_reason="ocr_recovery_needed",
        )

        self.mock_ocr.extract_text_boxes.return_value = [
            {"bbox": [30, 10, 70, 30], "text": "15%", "confidence": 0.95, "engine": "test"},
            {"bbox": [120, 10, 300, 30], "text": "اماريل 2 مجم 30 قرص", "confidence": 0.95, "engine": "test"},
            {"bbox": [360, 10, 400, 30], "text": "9920", "confidence": 0.95, "engine": "test"},
            {"bbox": [430, 10, 490, 30], "text": "120.00", "confidence": 0.95, "engine": "test"},
        ]

        cand = _evaluate_ocr_candidate_on_crop(
            self.dummy_img, self.mock_ocr, default_wh="TestWholesaler", issue=issue
        )
        self.assertIsNotNone(cand)
        self.assertEqual(cand["base_price"], 120.0)
        self.assertAlmostEqual(cand["discount_rate"], 0.15, places=4)
        self.assertIn(cand["dosage"], ("2مجم", "2mg"))
        self.assertIn(cand["unit_size"], ("30قرص", "30 قرص"))

    def test_preserve_missing_discount_as_none(self):
        """
        Verify that an unreadable or missing discount is preserved as None,
        NOT converted to 0.0. Explicit zero discount (0%, صافي) must be preserved as 0.0.
        """
        col_bounds = {
            "discount": (0.0, 100.0),
            "name": (100.0, 350.0),
            "code": (350.0, 420.0),
            "price": (420.0, 500.0),
        }
        # Case A: Missing discount
        issue_missing = ReviewIssue(
            source_id="p1_t0_r4a",
            identity=SourceIdentity(page=1, table=0, row=4),
            bbox=[0.0, 10.0, 500.0, 40.0],
            column_bounds=col_bounds,
            rejection_reason="missing_discount",
        )
        self.mock_ocr.extract_text_boxes.return_value = [
            # No discount box at all
            {"bbox": [120, 10, 250, 30], "text": "اسبرين بروتكت", "confidence": 0.95, "engine": "test"},
            {"bbox": [430, 10, 470, 30], "text": "35.00", "confidence": 0.95, "engine": "test"},
        ]
        cand_a = _evaluate_ocr_candidate_on_crop(
            self.dummy_img, self.mock_ocr, default_wh="TestWholesaler", issue=issue_missing
        )
        self.assertIsNotNone(cand_a)
        self.assertEqual(cand_a["base_price"], 35.0)
        self.assertIsNone(cand_a["discount_rate"])  # Must be None, NOT 0.0

        # Case B: Explicit zero discount ("صافي" or "0%")
        issue_explicit = ReviewIssue(
            source_id="p1_t0_r4b",
            identity=SourceIdentity(page=1, table=0, row=5),
            bbox=[0.0, 10.0, 500.0, 40.0],
            column_bounds=col_bounds,
            rejection_reason="ocr_recovery_needed",
        )
        self.mock_ocr.extract_text_boxes.return_value = [
            {"bbox": [20, 10, 60, 30], "text": "صافي", "confidence": 0.95, "engine": "test"},
            {"bbox": [120, 10, 250, 30], "text": "اسبرين بروتكت", "confidence": 0.95, "engine": "test"},
            {"bbox": [430, 10, 470, 30], "text": "35.00", "confidence": 0.95, "engine": "test"},
        ]
        cand_b = _evaluate_ocr_candidate_on_crop(
            self.dummy_img, self.mock_ocr, default_wh="TestWholesaler", issue=issue_explicit
        )
        self.assertIsNotNone(cand_b)
        self.assertEqual(cand_b["base_price"], 35.0)
        self.assertEqual(cand_b["discount_rate"], 0.0)  # Must be 0.0 because source explicitly stated صافي


if __name__ == "__main__":
    unittest.main()
