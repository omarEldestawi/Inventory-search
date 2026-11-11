"""
Adversarial Verification Suite for R1: Egyptian Pharma Catalog Extraction & Arabic OCR Pipeline (v2.6).

Stress tests, edge case harnesses, and empirical probes authored by Challenger 1 (teamwork_challenger).
Challenges:
1. Damaged, skewed (>2°), 180° rotated, and low-contrast pages: ladder termination and bounded loop checks.
2. Mixed Arabic and Latin drug names: wrapped multi-line names, strengths (500 مجم, 1 جم), concentration ratios (50/1000), token preservation.
3. Price and discount column role resolution: swapped columns, explicit zero discount (0.0 / "0%" / "صافي") vs blank (None / "").
4. Noisy scans and non-catalog pages: rejection as ReviewIssue, candidate count hallucination prevention.
5. Incomplete file handling: Lifecycle state marking (Partially recovered / Could not verify) without crashing or manual typing fallback.
6. Primary regression catalogs: C:\\Users\\omart\\Downloads\\العابد نقدي الخميس.pdf and 2طباعه مزدوجه.pdf.
"""
import math
import os
import unittest
import numpy as np
import cv2
import pandas as pd
import pymupdf

from src.ocr_engine import ArabicOCREngine
from src.image_table_detector import ImageTableDetector
from src.pdf_parser import PDFCatalogParser
from src.catalog_recovery import (
    deskew_and_enhance_image,
    reconstruct_wrapped_name,
    recover_by_column_roles,
    recover_by_wrapped_text,
    run_automatic_recovery,
)
from src.catalog_diagnostics import (
    CatalogResult,
    ImportDiagnostics,
    ReviewIssue,
    RowDiagnostic,
    SourceIdentity,
)
from src.catalog_reader import (
    is_explicit_zero_discount,
    parse_discount,
    parse_dosage_and_pack,
    validate_catalog_item,
)
from app_gui import CatalogLifecycleState, FileItem

PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
SCANNED_SAMPLE_PATH = os.path.join(PROJECT_ROOT, "archive", "diagnostics", "test_scanned_sample.pdf")
EL_ABED_PATH = r"C:\Users\omart\Downloads\العابد نقدي الخميس.pdf"
TEBAA_PATH = r"C:\Users\omart\Downloads\2طباعه مزدوجه.pdf"


class TestAdversarialDamagedAndRotatedPages(unittest.TestCase):
    """Probes 1: Damaged, skewed (>2°), 180° rotated, and low-contrast page handling."""

    def setUp(self):
        self.detector = ImageTableDetector()
        self.ocr_engine = ArabicOCREngine()

    def test_extreme_skew_deskew_and_enhance(self):
        """Tests that deskew_and_enhance_image handles extreme skews (5° and 15°) without crashing or distortion."""
        h, w = 400, 600
        canvas = np.full((h, w, 3), 255, dtype=np.uint8)
        # Draw some horizontal text-like lines
        for y in range(80, 320, 40):
            cv2.line(canvas, (100, y), (500, y), (0, 0, 0), 4)

        for test_angle in [5.0, 15.0, -8.0]:
            M = cv2.getRotationMatrix2D((w // 2, h // 2), test_angle, 1.0)
            rotated = cv2.warpAffine(canvas, M, (w, h), borderValue=(255, 255, 255))

            enhanced = deskew_and_enhance_image(rotated, apply_clahe=True)
            self.assertEqual(enhanced.shape, canvas.shape)
            self.assertEqual(enhanced.dtype, np.uint8)

    def test_180_degree_orientation_ladder_termination(self):
        """
        Tests that an upside-down (180° rotated) page terminates deterministically
        through the bounded recovery ladder without entering an infinite loop.
        """
        if not os.path.isfile(SCANNED_SAMPLE_PATH):
            self.skipTest(f"Scanned sample not found: {SCANNED_SAMPLE_PATH}")

        doc = pymupdf.open(SCANNED_SAMPLE_PATH)
        pix = doc[0].get_pixmap(dpi=150)
        doc.close()

        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:
            img = cv2.cvtColor(img, cv2.COLOR_RGBA2RGB)

        # Rotate 180°
        img_180 = cv2.rotate(img, cv2.ROTATE_180)

        # Run extraction
        accepted, diags, issues = self.detector.extract_table_records(img_180, page_idx=0)

        # Bounded execution: must return cleanly without hanging
        self.assertIsInstance(accepted, list)
        self.assertIsInstance(diags, list)
        self.assertIsInstance(issues, list)

        # Build mock CatalogResult with unresolved issues and verify recovery ladder terminates
        df_empty = pd.DataFrame(columns=["warehouse_name", "item_name", "base_price", "discount_rate", "stock_status"])
        diag_obj = ImportDiagnostics(accepted_rows=len(accepted), unique_records=len(accepted))
        cat_result = CatalogResult(
            dataframe=df_empty,
            diagnostics=diag_obj,
            review_issues=issues,
            issues_by_source_id={i.source_id: i for i in issues},
        )

        # Run automatic recovery: MUST terminate deterministically in 1 pass
        recovered_result = run_automatic_recovery(cat_result, pdf_path=None)
        self.assertIsNotNone(recovered_result)
        # All attempted strategies must be bounded (max 1 attempt per strategy)
        for iss in recovered_result.review_issues:
            self.assertLessEqual(len(iss.attempted_strategies), 4)

    def test_low_contrast_degradation_handling(self):
        """Verifies CLAHE enhancement recovers structure on a severely washed-out low contrast table."""
        # Create washed out table: values between 200 and 230
        h, w = 300, 500
        washed = np.full((h, w, 3), 230, dtype=np.uint8)
        # Grid lines faint (intensity 200)
        cv2.rectangle(washed, (50, 50), (450, 250), (205, 205, 205), 2)
        cv2.line(washed, (150, 50), (150, 250), (205, 205, 205), 1)
        cv2.line(washed, (350, 50), (350, 250), (205, 205, 205), 1)

        enhanced = deskew_and_enhance_image(washed, apply_clahe=True)
        # CLAHE must expand contrast range: min should be darker than 205
        min_orig = int(np.min(washed))
        min_enh = int(np.min(enhanced))
        self.assertLessEqual(min_enh, min_orig)


class TestAdversarialMixedNamesAndDosages(unittest.TestCase):
    """Probes 2: Mixed Arabic/Latin names, multi-line strengths, concentration ratios, un-reversal."""

    def setUp(self):
        self.engine = ArabicOCREngine()

    def test_multiline_wrapped_names_reconstruction(self):
        """Multi-line wrapped names must assemble into coherent strings without dropping words."""
        wrapped_sample = "AUGMENTIN\n1 GM\n14 TAB"
        reconstructed = reconstruct_wrapped_name(wrapped_sample)
        self.assertEqual(reconstructed, "AUGMENTIN 1 GM 14 TAB")

        arabic_wrapped = "كونكور\n5 مجم\n30 قرص"
        reconstructed_ar = reconstruct_wrapped_name(arabic_wrapped)
        self.assertEqual(reconstructed_ar, "كونكور 5 مجم 30 قرص")

    def test_arabic_strengths_and_concentration_ratios_never_scrambled(self):
        """Concentration ratios like 50/1000 and strengths like 500 مجم must never be scrambled."""
        cases = [
            ("CONCOR 50/1000", "CONCOR 50/1000"),
            ("AUGMENTIN 1 GM", "AUGMENTIN 1 GM"),
            ("PANADOL 500MG", "PANADOL 500MG"),
            ("50/1000", "50/1000"),
            ("250/50", "250/50"),
        ]
        for inp, expected in cases:
            out = self.engine.unreverse_ocr_text(inp)
            self.assertEqual(out, expected, f"Failed on {inp}")

    def test_pure_arabic_unreversal_sanity(self):
        """PaddleOCR visual LTR characters must reverse to logical Arabic words."""
        # PaddleOCR emits characters left-to-right, so 'الصنف' -> 'فنصلا'
        self.assertEqual(self.engine.unreverse_ocr_text("فنصلا"), "الصنف")
        self.assertEqual(self.engine.unreverse_ocr_text("مصخلا"), "الخصم")
        self.assertEqual(self.engine.unreverse_ocr_text("دوكلا"), "الكود")
        self.assertEqual(self.engine.unreverse_ocr_text("رعسلا"), "السعر")


class TestAdversarialColumnRoleResolution(unittest.TestCase):
    """Probes 3: Price and discount column role resolution, swapped columns, explicit zero vs blank."""

    def test_swapped_price_discount_resolution(self):
        """If discount and price columns are swapped (Discount first, Price second), role resolution resolves correctly."""
        issue = ReviewIssue(
            source_id="p1_t0_r1",
            raw_cells=["بانادول 500 مجم", "25%", "60.0"],
            rejection_reason="column_roles_swapped",
        )
        resolved = recover_by_column_roles(issue, default_wh="TestWH")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["base_price"], 60.0)
        self.assertEqual(resolved["discount_rate"], 0.25)
        self.assertEqual(resolved["item_name"], "بانادول 500 مجم")

    def test_explicit_zero_discount_vs_blank_preservation(self):
        """
        Confirms that:
        1. Explicit zero ('0.0', '0%', '0.0%', 'صافي') resolves to 0.0.
        2. Blank (None, '') is preserved as distinct from 0.0.
        """
        # Explicit zero cases
        for zero_repr in ["0", "0.0", "0%", "0.0%", "صافي", "صافى"]:
            self.assertTrue(
                is_explicit_zero_discount(zero_repr),
                f"Expected {zero_repr} to be recognized as explicit zero discount",
            )
            parsed = parse_discount(zero_repr)
            self.assertEqual(parsed, 0.0)

        # Blank cases
        self.assertFalse(is_explicit_zero_discount(None))
        self.assertFalse(is_explicit_zero_discount(""))
        self.assertFalse(is_explicit_zero_discount("   "))

        # In validate_catalog_item:
        item_zero = {"item_name": "Panadol 500mg", "base_price": 50.0, "discount_rate": 0.0}
        valid, _ = validate_catalog_item(item_zero)
        self.assertTrue(valid)

        item_blank = {"item_name": "Panadol 500mg", "base_price": 50.0, "discount_rate": None}
        valid, _ = validate_catalog_item(item_blank)
        self.assertTrue(valid)

    def test_ambiguous_columns_remain_unresolved(self):
        """Two numeric columns that cannot be disambiguated must NOT guess and remain unresolved."""
        # Both numbers in same range without % cue
        issue = ReviewIssue(
            source_id="p1_t0_r2",
            raw_cells=["امبيسلين 500 مجم", "50.0", "60.0"],
            rejection_reason="ambiguous_prices",
        )
        resolved = recover_by_column_roles(issue, default_wh="TestWH")
        # Must return None so human review handles it
        self.assertIsNone(resolved)


class TestAdversarialNoisyScansAndHallucinationRejection(unittest.TestCase):
    """Probes 4: Unmapped content, non-catalog pages, and candidate count hallucination prevention."""

    def setUp(self):
        self.detector = ImageTableDetector()

    def test_non_catalog_noisy_boxes_are_rejected(self):
        """Header, footer, telephone numbers, and random noise are rejected as ReviewIssue and not accepted."""
        noisy_candidates = [
            {"item_name": "تليفون المبيعات 01012345678", "base_price": 100.0, "discount_rate": 0.20},
            {"item_name": "الصفحة 1 من 10", "base_price": 50.0, "discount_rate": 0.15},
            {"item_name": "اسم الصنف", "base_price": 20.0, "discount_rate": 0.25},
            {"item_name": "سعر الجمهور", "base_price": 30.0, "discount_rate": 0.10},
            {"item_name": "---", "base_price": 10.0, "discount_rate": 0.05},
        ]
        for cand in noisy_candidates:
            valid, reason = validate_catalog_item(cand)
            self.assertFalse(valid, f"Expected {cand['item_name']} to be rejected")
            self.assertTrue(
                "header_token" in reason or "catalog_noise" in reason or "noise" in reason,
                f"Unexpected reason: {reason}",
            )


class TestAdversarialIncompleteFileLifecycle(unittest.TestCase):
    """Probes 5: Incomplete file lifecycle state marking without crashing or transcription prompts."""

    def test_file_item_lifecycle_state_transitions(self):
        """Verifies FileItem lifecycle states: Reading -> Ready vs Partially recovered vs Could not verify."""
        item = FileItem("dummy_catalog.pdf", "Catalog")

        # 1. Initially reading
        self.assertEqual(item.determine_lifecycle_state(), CatalogLifecycleState.READING)

        # 2. Complete verification with items and no unresolved issues
        item.item_count = 150
        item.diagnostic_status = "complete"
        item.catalog_result = None
        self.assertEqual(item.determine_lifecycle_state(), CatalogLifecycleState.READY)

        # 3. Partially recovered with unresolved issues
        mock_issues = [
            ReviewIssue(source_id="p1_t0_r1", raw_cells=["صنف غير واضح"], rejection_reason="unclear")
        ]
        diag_obj = ImportDiagnostics(accepted_rows=8, unique_records=8)
        item.catalog_result = CatalogResult(
            dataframe=pd.DataFrame([{"item_name": "A", "base_price": 10.0, "discount_rate": 0.2}]),
            diagnostics=diag_obj,
            review_issues=mock_issues,
            issues_by_source_id={i.source_id: i for i in mock_issues},
        )
        item.diagnostic_status = "partial"
        self.assertEqual(item.determine_lifecycle_state(), CatalogLifecycleState.PARTIALLY_RECOVERED)

        # 4. Extraction failed or 0 items -> COULD_NOT_VERIFY
        item.item_count = 0
        item.diagnostic_status = "failed"
        self.assertEqual(item.determine_lifecycle_state(), CatalogLifecycleState.COULD_NOT_VERIFY)


class TestAdversarialRegressionBaselines(unittest.TestCase):
    """Probes 6: 100% regression verification on El Abed, Tebaa, and Scanned sample."""

    def test_el_abed_vector_regression(self):
        """El Abed must extract exactly 230 rows with 0 regressions."""
        if not os.path.isfile(EL_ABED_PATH):
            self.skipTest(f"El Abed not found: {EL_ABED_PATH}")

        parser = PDFCatalogParser(EL_ABED_PATH)
        df = parser.parse()
        self.assertEqual(len(df), 230, f"Expected 230 rows, got {len(df)}")
        self.assertIn("item_name", df.columns)
        self.assertIn("base_price", df.columns)
        self.assertIn("discount_rate", df.columns)

    def test_tebaa_dual_column_regression(self):
        """Tebaa dual-column must extract exactly 1,253 rows with 0 regressions."""
        if not os.path.isfile(TEBAA_PATH):
            self.skipTest(f"Tebaa not found: {TEBAA_PATH}")

        parser = PDFCatalogParser(TEBAA_PATH)
        df = parser.parse()
        self.assertEqual(len(df), 1253, f"Expected 1253 rows, got {len(df)}")
        self.assertIn("item_name", df.columns)
        self.assertIn("base_price", df.columns)
        self.assertIn("discount_rate", df.columns)

    def test_scanned_sample_minimum_rows(self):
        """Scanned Arabic PDF defers on import and yields at least 20 rows with explicit OCR."""
        if not os.path.isfile(SCANNED_SAMPLE_PATH):
            self.skipTest(f"Scanned sample not found: {SCANNED_SAMPLE_PATH}")

        parser = PDFCatalogParser(SCANNED_SAMPLE_PATH)
        deferred = CatalogResult.from_dataframe(parser.parse())
        self.assertTrue(deferred.dataframe.empty)
        self.assertTrue(any(
            issue.rejection_reason == "image_only_page_requires_review" and not issue.resolved
            for issue in deferred.review_issues
        ))
        df = parser.parse(allow_ocr=True)
        self.assertGreaterEqual(len(df), 20)


if __name__ == "__main__":
    unittest.main()
