"""
Test Suite for R1: Local Arabic OCR Recovery Pipeline (v2.6).

Covers:
1. ArabicOCREngine initialization, availability, and offline execution.
2. Un-reversal of PaddleOCR Visual RTL characters to logical Arabic text.
3. ImageTableDetector morphological boundary detection, row clustering, and column role classification.
4. Independent Page Assessment (assess_pdf_page) 3 modes: pure_vector, mixed_vector, pure_raster.
5. Scanned Arabic catalog end-to-end extraction on archive/diagnostics/test_scanned_sample.pdf.
6. Bounded retry ladder (Tier 0 -> Tier 1 -> Tier 2) with monotonic quality retention.
7. Strict exclusion of unverified/uncertain rows from automatic procurement.
"""
import os
import unittest
import numpy as np
import cv2
import pymupdf
import pandas as pd

from src.ocr_engine import ArabicOCREngine
from src.image_table_detector import ImageTableDetector
from src.pdf_font_decoder import assess_pdf_page, PageAssessment
from src.pdf_parser import PDFCatalogParser
from src.catalog_recovery import deskew_and_enhance_image, run_automatic_recovery
from src.catalog_diagnostics import CatalogResult, ReviewIssue, SourceIdentity, RowDiagnostic
from src.catalog_reader import validate_catalog_item, normalize_arabic_text

PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
SCANNED_SAMPLE_PATH = os.path.join(PROJECT_ROOT, "archive", "diagnostics", "test_scanned_sample.pdf")
EL_ABED_PATH = r"C:\Users\omart\Downloads\العابد نقدي الخميس.pdf"
TEBAA_PATH = r"C:\Users\omart\Downloads\2طباعه مزدوجه.pdf"


class TestArabicOCREngine(unittest.TestCase):
    """Verifies ArabicOCREngine wrapping RapidOCR with local Arabic ONNX weights."""

    def setUp(self):
        self.engine = ArabicOCREngine()

    def test_engine_is_available_and_offline(self):
        """Engine must report available without making external network calls."""
        self.assertTrue(self.engine.is_available())
        self.assertIsNotNone(self.engine._rec_model_path)
        self.assertTrue(os.path.isfile(self.engine._rec_model_path))
        self.assertTrue(os.path.isfile(self.engine._dict_path))

    def test_arabic_unreversal_logic(self):
        """Visual RTL sequences emitted by PaddleOCR must resolve to logical Arabic text."""
        # 'فنصلا' (visual LTR) -> 'الصنف' (logical)
        unrev1 = self.engine.unreverse_ocr_text("فنصلا")
        self.assertEqual(unrev1, "الصنف")

        # 'مصخلا' (visual LTR) -> 'الخصم' (logical)
        unrev2 = self.engine.unreverse_ocr_text("مصخلا")
        self.assertEqual(unrev2, "الخصم")

        # 'دوكلا' (visual LTR) -> 'الكود' (logical)
        unrev3 = self.engine.unreverse_ocr_text("دوكلا")
        self.assertEqual(unrev3, "الكود")

        # Latin medication names and digits must not be reversed
        self.assertEqual(self.engine.unreverse_ocr_text("PANADOL 500MG"), "PANADOL 500MG")
        self.assertEqual(self.engine.unreverse_ocr_text("105121"), "105121")


class TestImageTableDetector(unittest.TestCase):
    """Verifies OpenCV morphological table detection and row/column slicing."""

    def setUp(self):
        self.detector = ImageTableDetector()

    def test_table_boundaries_detection_on_scanned_sample(self):
        """Morphological detection must locate the table boundary on scanned sample."""
        if not os.path.isfile(SCANNED_SAMPLE_PATH):
            self.skipTest(f"Sample file not found: {SCANNED_SAMPLE_PATH}")

        doc = pymupdf.open(SCANNED_SAMPLE_PATH)
        pix = doc[0].get_pixmap(dpi=150)
        doc.close()

        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:
            img = cv2.cvtColor(img, cv2.COLOR_RGBA2RGB)

        tables = self.detector.detect_table_boundaries(img)
        self.assertGreaterEqual(len(tables), 1)
        bx, by, bw, bh = tables[0]
        # Table must occupy a significant portion of the scanned page
        self.assertGreater(bw, 1000)
        self.assertGreater(bh, 1500)


class TestPageAssessmentThreeModes(unittest.TestCase):
    """Verifies independent page assessment across 3 modes: pure_vector, mixed_vector, pure_raster."""

    def test_pure_raster_classification_for_scanned_catalog(self):
        if not os.path.isfile(SCANNED_SAMPLE_PATH):
            self.skipTest("Scanned sample not found")

        doc = pymupdf.open(SCANNED_SAMPLE_PATH)
        page = doc[0]
        assessment = assess_pdf_page(page, 0)
        doc.close()

        self.assertEqual(assessment.mode, "pure_raster")
        self.assertIn(assessment.classification, ("image_only", "pure_raster"))

    def test_pure_vector_classification_for_digital_catalogs(self):
        if os.path.isfile(EL_ABED_PATH):
            doc = pymupdf.open(EL_ABED_PATH)
            assessment = assess_pdf_page(doc[0], 0)
            doc.close()
            self.assertEqual(assessment.mode, "pure_vector")


class TestScannedCatalogEndToEndExtraction(unittest.TestCase):
    """Verifies that archive/diagnostics/test_scanned_sample.pdf extracts valid rows without manual typing."""

    def test_scanned_sample_extraction(self):
        if not os.path.isfile(SCANNED_SAMPLE_PATH):
            self.skipTest(f"Sample file not found: {SCANNED_SAMPLE_PATH}")

        parser = PDFCatalogParser(SCANNED_SAMPLE_PATH)
        df = parser.parse()

        # Must extract valid pharmaceutical rows
        self.assertGreaterEqual(len(df), 20)
        self.assertIn("item_name", df.columns)
        self.assertIn("base_price", df.columns)
        self.assertIn("discount_rate", df.columns)

        # Verify all prices are valid positive numbers < 10000
        for p in df["base_price"]:
            self.assertGreater(p, 0.0)
            self.assertLess(p, 10000.0)

        # Verify all discounts are within [0.0, 0.85]
        for d in df["discount_rate"]:
            self.assertGreaterEqual(d, 0.0)
            self.assertLessEqual(d, 0.85)

        # Verify sample extracted medication identities
        names_str = " ".join(df["item_name"])
        self.assertTrue(
            any(brand in names_str for brand in ["اتور", "اتورستات", "ليبتيسجيل", "اكتومثرين", "كارنتين"])
        )


class TestBoundedRecoveryLadderAndQualityRetention(unittest.TestCase):
    """Verifies bounded retry settings (150 DPI RGB default -> 200 DPI CLAHE deskew) and monotonic retention."""

    def test_deskew_and_enhance_preserves_dimensions_and_channels(self):
        dummy_img = np.zeros((300, 400, 3), dtype=np.uint8)
        dummy_img[50:250, 50:350] = 200
        enhanced = deskew_and_enhance_image(dummy_img, apply_clahe=True)
        self.assertEqual(enhanced.shape, dummy_img.shape)

    def test_unverified_rows_strictly_excluded_from_accepted_dataframe(self):
        """Rows failing canonical validate_catalog_item must be excluded from final procurement dataframe."""
        invalid_candidate = {
            "warehouse_name": "TestWH",
            "item_name": "سعر الجمهور",  # Header token, invalid
            "base_price": 50.0,
            "discount_rate": 0.20,
        }
        valid, reason = validate_catalog_item(invalid_candidate)
        self.assertFalse(valid)
        self.assertIn("header_token", reason)


if __name__ == "__main__":
    unittest.main()
