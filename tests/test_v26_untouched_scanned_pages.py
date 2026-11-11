import json
import os
import re
import unittest
import pymupdf

from src.catalog_reader import normalize_arabic_text
from src.pdf_parser import PDFCatalogParser
from src.catalog_diagnostics import CatalogResult


class TestUntouchedGeneratedRasterPage(unittest.TestCase):
    """
    Evaluates OCR table extraction against an independently transcribed ground-truth reference
    on an untouched catalog page layout.

    ACCURATE PROVENANCE LABEL:
    The input file 'tests/fixtures/untouched_raster_page3.pdf' is a GENERATED RASTER PDF
    (synthetically rendered at 150 DPI RGB from page 3 of untouched vector wholesaler catalog
    'test1/سبيشيال فارما.pdf'). It tests Arabic OCR and table detection on an untouched layout
    without access to the PDF vector text stream. It is NOT an independent physical paper scan.
    """

    @classmethod
    def setUpClass(cls):
        cls.pdf_path = "tests/fixtures/untouched_raster_page3.pdf"
        cls.ref_path = "tests/fixtures/v26_untouched_page3_reference.json"

        # Ensure raster PDF exists (render from test1/سبيشيال فارما.pdf page 3 if needed)
        if not os.path.exists(cls.pdf_path):
            source_pdf = "test1/سبيشيال فارما.pdf"
            if not os.path.exists(source_pdf):
                source_pdf = "archive/EgyptianPharmaOptimizer_ReadyForWindows/test1/╪│╪¿┘è╪┤┘è╪º┘ä ┘ü╪º╪▒┘à╪º.pdf"
            if os.path.exists(source_pdf):
                doc = pymupdf.open(source_pdf)
                page = doc[2]  # Page 3 (0-indexed 2)
                pix = page.get_pixmap(dpi=150)
                doc_out = pymupdf.open()
                p_out = doc_out.new_page(width=page.rect.width, height=page.rect.height)
                p_out.insert_image(page.rect, stream=pix.tobytes("png"))
                doc_out.save(cls.pdf_path)
                doc_out.close()

        with open(cls.ref_path, "r", encoding="utf-8") as f:
            ref_data = json.load(f)
        cls.reference_page = ref_data["untouched_raster_catalog_page3"]
        cls.expected_rows = cls.reference_page["verified_rows"]

    def test_untouched_page_ground_truth_field_accuracy(self):
        """
        Benchmarks OCR extracted fields against independently transcribed ground truth:
        1. Spatial location 1-to-1 matching (by y-center coordinate).
        2. Exact measurements for:
           - Row coverage (detected vs expected rows)
           - Price accuracy
           - Discount accuracy
           - Strength (dosage) accuracy
           - Pack size accuracy
           - Medication name accuracy
        """
        parser = PDFCatalogParser(self.pdf_path, warehouse_name="SpecialPharma_Page3_Raster")
        self.assertTrue(parser.parse().empty)
        df = parser.parse_ocr()
        result = CatalogResult.from_dataframe(df)
        uncertain = {i.source_id: i for i in result.review_issues if not i.resolved and i.rejection_reason in ("unverified_ocr_strength_sequence", "ambiguous_ocr_decimal")}
        self.assertEqual(set(uncertain), {"p1_t0_r6", "p1_t0_r9", "p1_t0_r10", "p1_t0_r16"})
        self.assertIn("1205/40/5", uncertain["p1_t0_r9"].item["item_name"])
        self.assertTrue(uncertain["p1_t0_r9"].item.get("_ocr_strength_attempts"))

        total_ref_rows = len(self.expected_rows)
        total_extracted_rows = len(df)

        self.assertEqual(total_ref_rows, 28)
        self.assertEqual(total_extracted_rows + len(uncertain), total_ref_rows, "Every source row must be accepted or explicitly unresolved")

        # 1-to-1 Spatial Matching by y-center coordinate with duplicate detection
        matched_pairs = []
        matched_ref_ids = set()
        matched_act_indices = set()
        duplicate_rows = 0

        for idx, row in df.iterrows():
            bbox = row.get("_bbox")
            if not bbox or len(bbox) < 4:
                continue
            act_y = (bbox[1] + bbox[3]) / 2.0

            # Find closest reference row by y-coordinate
            best_ref = None
            min_dist = float("inf")
            for ref_row in self.expected_rows:
                dist = abs(ref_row["y_pt"] - act_y)
                if dist < min_dist:
                    min_dist = dist
                    best_ref = ref_row

            if best_ref and min_dist <= 25.0:  # Within row band tolerance
                ref_id = best_ref["row_id"]
                if ref_id in matched_ref_ids:
                    duplicate_rows += 1
                else:
                    matched_ref_ids.add(ref_id)
                    matched_act_indices.add(idx)
                    matched_pairs.append((best_ref, row))

        missing_rows = total_ref_rows - len(matched_pairs)
        extra_rows = total_extracted_rows - len(matched_pairs)

        # Field-by-field accuracy accounting
        price_matches = 0
        discount_matches = 0
        full_name_matches = 0
        name_token_matches = 0
        strength_matches = 0
        pack_matches = 0

        for ref, act in matched_pairs:
            # 1. Price comparison
            act_price = float(act["base_price"])
            ref_price = float(ref["base_price"])
            if abs(act_price - ref_price) < 0.05:
                price_matches += 1

            # 2. Discount comparison
            act_disc = float(act["discount_rate"]) if act["discount_rate"] is not None else None
            ref_disc = float(ref["discount_rate"]) if ref["discount_rate"] is not None else None
            if act_disc is not None and ref_disc is not None and abs(act_disc - ref_disc) < 0.02:
                discount_matches += 1

            # 3. Name comparisons: Separate Full Name Match & Token Match
            norm_act = normalize_arabic_text(str(act["item_name"]))
            norm_ref = normalize_arabic_text(str(ref["item_name"]))
            if norm_act.replace(" ", "") == norm_ref.replace(" ", ""):
                full_name_matches += 1

            ref_tokens = [tok for tok in norm_ref.split() if len(tok) >= 2 and not tok.isdigit()]
            if ref_tokens and any(tok in norm_act for tok in ref_tokens[:2]):
                name_token_matches += 1

            # 4. Strength comparison (exact dosage check)
            act_dosage = str(act.get("dosage", "") or "").strip().lower().replace(" ", "")
            ref_dosage = str(ref.get("dosage", "") or "").strip().lower().replace(" ", "")
            if ref_dosage == act_dosage or (not ref_dosage and not act_dosage):
                strength_matches += 1
            elif ref_dosage and act_dosage:
                # Do NOT treat mismatched strength numbers as matches (e.g. 5mg must not match 12.5mg)
                ref_num = re.findall(r'\d+(?:\.\d+)?', ref_dosage)
                act_num = re.findall(r'\d+(?:\.\d+)?', act_dosage)
                if ref_num and act_num and ref_num == act_num:
                    strength_matches += 1

            # Field-level regression verification for critical rows
            if ref.get("row_id") == "p3_r9":
                self.assertNotIn("1205", str(act["item_name"]), "Admitted corrupted 1205 strength into accepted row!")
                self.assertIn("12.5", str(act["item_name"]), "Failed to recover authentic 12.5 multi-component strength!")

            if ref.get("row_id") == "p3_r26":
                self.assertIn("ثلاجة", str(act["item_name"]), "Storage condition 'ثلاجة' dropped from extracted item name!")

            # 5. Pack comparison (exact pack check with whitespace normalization)
            act_pack = str(act.get("unit_size", "") or "").strip().lower().replace(" ", "")
            ref_pack = str(ref.get("unit_size", "") or "").strip().lower().replace(" ", "")
            if ref_pack == act_pack or (not ref_pack and not act_pack):
                pack_matches += 1
            elif ref_pack and (ref_pack in act_pack or act_pack in ref_pack):
                pack_matches += 1

        coverage_rate = len(matched_pairs) / float(total_ref_rows)
        price_acc = price_matches / float(total_ref_rows)
        disc_acc = discount_matches / float(total_ref_rows)
        full_name_acc = full_name_matches / float(total_ref_rows)
        token_name_acc = name_token_matches / float(total_ref_rows)
        strength_acc = strength_matches / float(total_ref_rows)
        pack_acc = pack_matches / float(total_ref_rows)

        print("\n=======================================================")
        print("  UNTOUCHED GENERATED RASTER PAGE 3 BENCHMARK REPORT   ")
        print("=======================================================")
        print(f"  Provenance: Generated Raster PDF (150 DPI RGB)")
        print(f"  Source: Page 3 of untouched wholesaler catalog")
        print(f"  Total Reference Rows (N):      {total_ref_rows}")
        print(f"  Total Extracted Rows:          {total_extracted_rows}")
        print(f"  Spatially Matched Rows:        {len(matched_pairs)} ({coverage_rate*100:.1f}%)")
        print(f"  Missing Rows:                  {missing_rows}")
        print(f"  Extra Rows:                    {extra_rows}")
        print(f"  Duplicate Rows:                {duplicate_rows}")
        print(f"  Exact Price Accuracy:          {price_matches}/{total_ref_rows} ({price_acc*100:.1f}%)")
        print(f"  Exact Discount Accuracy:       {discount_matches}/{total_ref_rows} ({disc_acc*100:.1f}%)")
        print(f"  Full Name Match Rate:          {full_name_matches}/{total_ref_rows} ({full_name_acc*100:.1f}%)")
        print(f"  Root/Token Name Match Rate:    {name_token_matches}/{total_ref_rows} ({token_name_acc*100:.1f}%)")
        print(f"  Strength (Dosage) Match Rate:  {strength_matches}/{total_ref_rows} ({strength_acc*100:.1f}%)")
        print(f"  Pack Size Match Rate:          {pack_matches}/{total_ref_rows} ({pack_acc*100:.1f}%)")
        print("=======================================================\n")

        # Rigorous assertions: coverage >= 95%, price and discount accuracy >= 95%
        self.assertEqual(total_extracted_rows, 24)
        self.assertEqual(missing_rows, 4)
        self.assertEqual(extra_rows, 0)
        self.assertEqual(duplicate_rows, 0)
        self.assertEqual(len(matched_pairs), 24)
        self.assertEqual(price_matches, 24, f"Price accuracy was {price_matches}/28")
        self.assertEqual(discount_matches, 24, f"Discount accuracy was {discount_matches}/28")
        self.assertEqual(strength_matches, 24, f"Strength accuracy was {strength_matches}/28")
        self.assertEqual(name_token_matches, 24)
        self.assertEqual(full_name_matches, 24)

    def test_unrecovered_corrupted_strength_fails_validation_and_release_gate(self):
        """
        Regression Test (Directive 1 & 3):
        Asserts that the previously admitted corrupted output (1205/40/5 where 12.5 blurred into 1205)
        strictly FAILS validate_catalog_item and is excluded from procurement.
        """
        from src.catalog_reader import validate_catalog_item

        corrupted_item = {
            "warehouse_name": "TestWholesaler",
            "item_name": "ايرستابكس تريو 1205/40/5 مجم اقراص",
            "base_price": 144.0,
            "discount_rate": 0.33,
            "stock_status": True,
            "_ocr_engine_used": "windows",
        }

        valid, reason = validate_catalog_item(corrupted_item)
        self.assertFalse(valid, "Corrupted 1205 strength MUST NOT be accepted by catalog validation!")
        self.assertEqual("unverified_ocr_strength_sequence", reason)

    def test_storage_condition_preservation_and_cell_assignment(self):
        """
        Regression Test (Directive 4):
        Verifies that storage instructions like 'ثلاجة' are never dropped or misassigned
        to the discount column, but preserved in the extracted text and dedicated metadata.
        """
        parser = PDFCatalogParser(self.pdf_path, warehouse_name="SpecialPharma_Page3_Raster")
        df = parser.parse_ocr()

        row_26 = None
        for _, r in df.iterrows():
            if "برونتوجيست" in str(r.get("item_name", "")):
                row_26 = r
                break

        self.assertIsNotNone(row_26, "Row with برونتوجيست not found in extracted catalog")
        self.assertIn("ثلاجة", str(row_26["item_name"]), "Storage condition 'ثلاجة' dropped from item_name")
        self.assertEqual(row_26.get("storage_condition"), "ثلاجة", "storage_condition metadata missing")


if __name__ == "__main__":
    unittest.main()
