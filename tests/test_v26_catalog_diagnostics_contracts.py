"""
Unit and Contract Test Suite: v2.6 Catalog Diagnostics Foundation Contracts.

Verifies:
1. Extended FileFingerprint defaults (ocr_model_version, recovery_config_hash).
2. Positional and keyword backward compatibility for FileFingerprint callers.
3. FileFingerprint.from_path and is_current behavior.
4. SourceIdentity backward compatibility and page_number / region_bbox synchronization.
5. RowDiagnostic common field metadata schema:
   - source_file_hash
   - page_number
   - region_bbox
   - raw_digital_text
   - raw_ocr_text
   - extraction_method
   - validation_results
   - retry_history
   - final_acceptance_state
6. ReviewIssue common field metadata schema and plain_explanation translations.
7. Lossless to_dict() and from_dict() roundtrips for RowDiagnostic and ReviewIssue.
8. RowDiagnostic.to_review_issue() lossless metadata propagation.
9. CatalogResult and ImportDiagnostics serialization/deserialization.
"""
import copy
import json
import os
import tempfile
import unittest

import pandas as pd
import pymupdf

from src.catalog_diagnostics import (
    FileFingerprint,
    SourceIdentity,
    ReviewIssue,
    RowDiagnostic,
    GroupDiagnostics,
    PageDiagnostics,
    ImportDiagnostics,
    CatalogResult,
    PARSER_REVISION,
    explain_rejection_reason,
)


class TestV26FileFingerprintContracts(unittest.TestCase):
    """Verifies FileFingerprint contract extensions and backward compatibility."""

    def test_fingerprint_defaults(self):
        fp = FileFingerprint(path="C:\\dummy\\test.pdf", sha256="a" * 64)
        self.assertEqual(fp.path, "C:\\dummy\\test.pdf")
        self.assertEqual(fp.sha256, "a" * 64)
        self.assertEqual(fp.parser_revision, PARSER_REVISION)
        self.assertEqual(fp.library_version, pymupdf.__version__)
        self.assertEqual(fp.ocr_model_version, "rapidocr_arabic_ppocrv3_v1")
        self.assertEqual(fp.recovery_config_hash, "v26_bounded_default")

    def test_fingerprint_positional_arguments_compatibility(self):
        # 4-argument call (legacy style)
        fp4 = FileFingerprint("C:\\dummy\\test.pdf", "b" * 64, "rev1", "pymupdf_custom")
        self.assertEqual(fp4.parser_revision, "rev1")
        self.assertEqual(fp4.library_version, "pymupdf_custom")
        self.assertEqual(fp4.ocr_model_version, "rapidocr_arabic_ppocrv3_v1")
        self.assertEqual(fp4.recovery_config_hash, "v26_bounded_default")

        # 6-argument call (full explicit)
        fp6 = FileFingerprint("C:\\dummy\\test.pdf", "c" * 64, "rev2", "1.28.0", "custom_ocr_v2", "custom_hash_1")
        self.assertEqual(fp6.ocr_model_version, "custom_ocr_v2")
        self.assertEqual(fp6.recovery_config_hash, "custom_hash_1")

    def test_fingerprint_from_path_and_is_current(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(b"%PDF-1.4 sample test bytes")
            tmp_path = tmp.name

        try:
            fp = FileFingerprint.from_path(tmp_path)
            self.assertEqual(fp.ocr_model_version, "rapidocr_arabic_ppocrv3_v1")
            self.assertEqual(fp.recovery_config_hash, "v26_bounded_default")
            self.assertTrue(fp.is_current())
            self.assertTrue(fp.is_current(tmp_path))

            # Modify file content -> is_current should be False
            with open(tmp_path, "wb") as f:
                f.write(b"%PDF-1.4 modified bytes")
            self.assertFalse(fp.is_current())

            # Non-existent path -> is_current should be False
            self.assertFalse(fp.is_current("C:\\non_existent_path_test.pdf"))
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


class TestV26SourceIdentityContracts(unittest.TestCase):
    """Verifies SourceIdentity backward compatibility and field synchronization."""

    def test_source_identity_sync(self):
        ident = SourceIdentity(page=3, table=1, row=5, bbox=[10.0, 20.0, 100.0, 50.0])
        self.assertEqual(ident.page, 3)
        self.assertEqual(ident.page_number, 3)
        self.assertEqual(ident.bbox, [10.0, 20.0, 100.0, 50.0])
        self.assertEqual(ident.region_bbox, [10.0, 20.0, 100.0, 50.0])
        self.assertEqual(ident.source_id, "p3_t1_r5")

        d = ident.to_dict()
        recovered = SourceIdentity.from_dict(d)
        self.assertEqual(recovered.page_number, 3)
        self.assertEqual(recovered.region_bbox, [10.0, 20.0, 100.0, 50.0])


class TestV26RowDiagnosticAndReviewIssueContracts(unittest.TestCase):
    """Verifies RowDiagnostic and ReviewIssue common metadata schema."""

    def test_row_diagnostic_legacy_positional_and_kwargs(self):
        # Calling with existing 8 arguments
        r = RowDiagnostic(
            page=2,
            group=0,
            row=10,
            outcome="accepted",
            reason="",
            bbox=[5.0, 15.0, 80.0, 45.0],
            raw_cells=["Panadol 500mg", "45.0", "15%"],
            item_name="Panadol 500mg",
        )
        self.assertEqual(r.page, 2)
        self.assertEqual(r.page_number, 2)
        self.assertEqual(r.bbox, [5.0, 15.0, 80.0, 45.0])
        self.assertEqual(r.region_bbox, [5.0, 15.0, 80.0, 45.0])
        self.assertEqual(r.final_acceptance_state, "accepted")
        self.assertEqual(r.extraction_method, "digital_vector")
        self.assertEqual(r.validation_results, {})
        self.assertEqual(r.retry_history, [])

    def test_row_diagnostic_full_common_field_metadata(self):
        r = RowDiagnostic(
            page=1,
            group=0,
            row=3,
            outcome="rejected",
            reason="invalid_price",
            bbox=[0.0, 10.0, 200.0, 40.0],
            raw_cells=["Cataflam 50mg", "0.0", "10%"],
            item_name="Cataflam 50mg",
            table=1,
            source_file_hash="abcdef0123456789" * 4,
            raw_digital_text="Cataflam 50mg 0.0 10%",
            raw_ocr_text="Cataflam 50mg 0.0 10%",
            extraction_method="arabic_ocr_primary",
            validation_results={"price_valid": False, "discount_valid": True},
            retry_history=["tier0_150dpi", "tier1_200dpi_clahe"],
            final_acceptance_state="rejected",
        )
        self.assertEqual(r.source_file_hash, "abcdef0123456789" * 4)
        self.assertEqual(r.page_number, 1)
        self.assertEqual(r.extraction_method, "arabic_ocr_primary")
        self.assertEqual(r.validation_results["price_valid"], False)
        self.assertEqual(len(r.retry_history), 2)
        self.assertEqual(r.final_acceptance_state, "rejected")

        # Verify to_review_issue propagation
        issue = r.to_review_issue()
        self.assertEqual(issue.source_file_hash, "abcdef0123456789" * 4)
        self.assertEqual(issue.page_number, 1)
        self.assertEqual(issue.region_bbox, [0.0, 10.0, 200.0, 40.0])
        self.assertEqual(issue.raw_digital_text, "Cataflam 50mg 0.0 10%")
        self.assertEqual(issue.raw_ocr_text, "Cataflam 50mg 0.0 10%")
        self.assertEqual(issue.extraction_method, "arabic_ocr_primary")
        self.assertEqual(issue.validation_results["price_valid"], False)
        self.assertEqual(issue.retry_history, ["tier0_150dpi", "tier1_200dpi_clahe"])
        self.assertEqual(issue.final_acceptance_state, "rejected")

    def test_review_issue_serialization_roundtrip(self):
        issue = ReviewIssue(
            source_id="p2_t1_r4",
            source_file_hash="1122334455667788" * 4,
            page_number=2,
            region_bbox=[10.0, 20.0, 30.0, 40.0],
            raw_digital_text=None,
            raw_ocr_text="أوجمنتين 1 جم",
            extraction_method="table_recovery",
            validation_results={"price": 120.0, "discount": 0.15},
            retry_history=["tier0_150dpi"],
            final_acceptance_state="partially_recovered",
            rejection_reason="ocr_unreliable",
            resolved=False,
        )

        self.assertIn("التعرف الضوئي (OCR)", issue.plain_explanation)

        d = issue.to_dict()
        recovered = ReviewIssue.from_dict(d)
        self.assertEqual(recovered.source_file_hash, "1122334455667788" * 4)
        self.assertEqual(recovered.page_number, 2)
        self.assertEqual(recovered.region_bbox, [10.0, 20.0, 30.0, 40.0])
        self.assertIsNone(recovered.raw_digital_text)
        self.assertEqual(recovered.raw_ocr_text, "أوجمنتين 1 جم")
        self.assertEqual(recovered.extraction_method, "table_recovery")
        self.assertEqual(recovered.validation_results["price"], 120.0)
        self.assertEqual(recovered.retry_history, ["tier0_150dpi"])
        self.assertEqual(recovered.final_acceptance_state, "partially_recovered")

    def test_import_diagnostics_from_dict_preserves_new_fields(self):
        row = RowDiagnostic(
            page=1,
            group=0,
            row=1,
            outcome="accepted",
            source_file_hash="ffff" * 16,
            page_number=1,
            region_bbox=[1.0, 2.0, 3.0, 4.0],
            raw_digital_text="Digital text",
            raw_ocr_text="OCR text",
            extraction_method="windows_ocr_fast",
            validation_results={"valid": True},
            retry_history=["win_ocr_direct"],
            final_acceptance_state="accepted",
        )
        group = GroupDiagnostics(group=0, strategy="table", candidate_rows=1, accepted_rows=1, rows=[row])
        page = PageDiagnostics(page=1, groups=[group], accepted_rows=1)
        diag = ImportDiagnostics(pages=[page], accepted_rows=1, unique_records=1)

        d = diag.to_dict()
        recovered_diag = ImportDiagnostics.from_dict(d)

        rec_row = recovered_diag.pages[0].groups[0].rows[0]
        self.assertEqual(rec_row.source_file_hash, "ffff" * 16)
        self.assertEqual(rec_row.page_number, 1)
        self.assertEqual(rec_row.region_bbox, [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(rec_row.raw_digital_text, "Digital text")
        self.assertEqual(rec_row.raw_ocr_text, "OCR text")
        self.assertEqual(rec_row.extraction_method, "windows_ocr_fast")
        self.assertEqual(rec_row.validation_results, {"valid": True})
        self.assertEqual(rec_row.retry_history, ["win_ocr_direct"])
        self.assertEqual(rec_row.final_acceptance_state, "accepted")

    def test_catalog_result_dataframe_roundtrip_with_extended_metadata(self):
        df = pd.DataFrame([
            {"warehouse_name": "W1", "item_name": "Med 1", "base_price": 50.0, "discount_rate": 0.1}
        ])
        fp = FileFingerprint(
            path="C:\\test\\cat.pdf",
            sha256="99" * 32,
            ocr_model_version="rapidocr_arabic_ppocrv3_v1",
            recovery_config_hash="v26_bounded_default",
        )
        row = RowDiagnostic(
            page=1, group=0, row=0, outcome="rejected", reason="ocr_low_confidence",
            source_file_hash="99" * 32, extraction_method="arabic_ocr_primary"
        )
        issue = row.to_review_issue()
        group = GroupDiagnostics(group=0, strategy="table", rows=[row])
        page = PageDiagnostics(page=1, groups=[group])
        diag = ImportDiagnostics(pages=[page], unique_records=1)

        res = CatalogResult(
            dataframe=df,
            diagnostics=diag,
            fingerprint=fp,
            review_issues=[issue],
        )

        res_df = res.to_dataframe()
        loaded_res = CatalogResult.from_dataframe(res_df)

        self.assertIsNotNone(loaded_res)
        self.assertEqual(loaded_res.fingerprint.ocr_model_version, "rapidocr_arabic_ppocrv3_v1")
        self.assertEqual(loaded_res.fingerprint.recovery_config_hash, "v26_bounded_default")
        self.assertEqual(len(loaded_res.review_issues), 1)
        loaded_issue = loaded_res.review_issues[0]
        self.assertEqual(loaded_issue.source_file_hash, "99" * 32)
        self.assertEqual(loaded_issue.extraction_method, "arabic_ocr_primary")


if __name__ == "__main__":
    unittest.main()
