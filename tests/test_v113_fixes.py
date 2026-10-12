# -*- coding: utf-8 -*-
"""
Verification tests for v1.1.3 fixes:
1. OCR Fast Path and Non-Degradation Guarantee
2. Spreadsheet Order Auto-Classification Heuristics
3. Controller Cache Poisoning Prevention
4. Application Version 1.1.3 Consistency
"""
import os
import sys
import tempfile
import pytest
import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.controller import classify_files, reread_catalog_with_ocr, global_catalog_cache, inspect_single_catalog
from src.pdf_parser import PDFCatalogParser


class TestV113CatalogReadingAndClassification:
    """Tests for enhanced catalog ingestion, order classification, and OCR reliability."""

    def test_diverse_order_filename_patterns(self, tmp_path):
        """Orders named with dates, codes, suffixes, or Arabic/English order keywords must classify as orders."""
        test_names = [
            "9011.xlsx",
            "9011 (1).xlsx",
            "9011_copy.xlsx",
            "طلب 11-9.xlsx",
            "طلبية_الاربعاء.xlsx",
            "طلبيه.xlsx",
            "نواقص_الصيدلية.xlsx",
            "شراء_عاجل.xlsx",
            "مشتريات_اليوم.xlsx",
            "order.xlsx",
            "order_2026_09.xlsx",
            "11-09.xlsx",
            "2026-09-11.xlsx",
            "po_9011.xlsx",
            "shortage_list.csv",
        ]
        paths = []
        for name in test_names:
            p = str(tmp_path / name)
            if name.endswith(".csv"):
                with open(p, "w", encoding="utf-8") as f:
                    f.write("الصنف,الكمية\nPanadol,10\n")
            else:
                pd.DataFrame([{"الصنف": "Panadol", "الكمية": 10}]).to_excel(p, index=False)
            paths.append(p)

        classified = classify_files(paths)
        assert len(classified["orders"]) == len(test_names), (
            f"Expected all {len(test_names)} to be orders, but got {len(classified['orders'])}. "
            f"Misclassified: {[os.path.basename(f) for f in classified['catalogs']]}"
        )

    def test_content_peek_order_with_generic_name(self, tmp_path):
        """Excel with generic name but containing quantity column and no discount column must be an order."""
        p = str(tmp_path / "export_data.xlsx")
        pd.DataFrame([{"كود": 101, "اسم الصنف": "Cataflam", "الكمية": 5, "سعر الجمهور": 60}]).to_excel(p, index=False)
        classified = classify_files([p])
        assert p in classified["orders"], "File with quantity column and no discount should classify as order"

    def test_content_peek_catalog_with_discount_column(self, tmp_path):
        """Excel with discount column must classify as catalog."""
        p = str(tmp_path / "med_list.xlsx")
        pd.DataFrame([{"الصنف": "Cataflam", "سعر الجمهور": 60, "نسبة الخصم": "25%"}]).to_excel(p, index=False)
        classified = classify_files([p])
        assert p in classified["catalogs"], "File with discount column should classify as catalog"

    def test_parse_ocr_non_degradation_guarantee(self):
        """parse_ocr must return valid medication items on vector PDFs."""
        pdf_path = os.path.abspath(os.path.join(PROJECT_ROOT, "input", "catalogs", "الشركة_المتحدة.pdf"))
        if not os.path.isfile(pdf_path):
            pytest.skip("Sample PDF not found")

        parser = PDFCatalogParser(pdf_path)
        ocr_df = parser.parse_ocr()

        assert not ocr_df.empty, "parse_ocr must return non-empty DataFrame"
        assert len(ocr_df) > 0

    def test_reread_catalog_with_ocr_preserves_existing_cache(self, tmp_path):
        """reread_catalog_with_ocr must preserve previously cached items if OCR finds 0 items."""
        sample_pdf = str(tmp_path / "dummy_catalog.pdf")
        import pymupdf
        doc = pymupdf.open()
        doc.new_page(width=595, height=842)
        doc.save(sample_pdf)
        doc.close()

        # Seed the cache with pre-existing known items
        seeded_df = pd.DataFrame([{
            'warehouse_name': 'مخزن تجريبي',
            'item_name': 'Panadol Extra 24 Tab',
            'normalized_name': 'panadol extra 24 tab',
            'dosage': '500mg',
            'unit_size': '24 tab',
            'base_price': 50.0,
            'discount_rate': 0.25,
            'stock_status': True
        }])
        norm_key = os.path.normpath(os.path.abspath(sample_pdf))
        global_catalog_cache.set(norm_key, seeded_df)

        # Now re-read with OCR on the blank PDF
        ret_path, count, records = reread_catalog_with_ocr(sample_pdf)
        assert count > 0, "Cache must not be wiped out by blank PDF OCR"
        assert len(records) == 1
        assert records[0]["name"] == "Panadol Extra 24 Tab"

        # Verify global cache was not wiped
        cached_after = global_catalog_cache.get(norm_key)
        assert cached_after is not None and not cached_after.empty
        assert len(cached_after) == 1

    def test_version_113_in_gui_and_installer(self):
        """GUI title, installer script, and self-test must report v1.1.3 or higher."""
        # 1. Inno Setup installer
        iss_path = os.path.join(PROJECT_ROOT, "installer.iss")
        with open(iss_path, "r", encoding="utf-8", errors="ignore") as f:
            iss_text = f.read()
        assert ('#define MyAppVersion "1.1.3"' in iss_text) or ('#define MyAppVersion "1.1.4"' in iss_text) or ('#define MyAppVersion "1.1.5"' in iss_text)
        assert ("EgyptianPharmaOptimizer_Setup_v1.1.3" in iss_text) or ("EgyptianPharmaOptimizer_Setup_v1.1.4" in iss_text) or ("EgyptianPharmaOptimizer_Setup_v1.1.5" in iss_text)

        # 2. GUI Title & Label
        gui_path = os.path.join(PROJECT_ROOT, "app_gui.py")
        with open(gui_path, "r", encoding="utf-8", errors="ignore") as f:
            gui_text = f.read()
        assert ("v1.1.3" in gui_text) or ("v1.1.4" in gui_text) or ("v1.1.5" in gui_text)
        assert "v1.1.2" not in gui_text
        assert ("Windows 11 Edition • Engine Ready" in gui_text)

        # 3. Batch launcher script
        bat_path = os.path.join(PROJECT_ROOT, "تشغيل_البرنامج.bat")
        if os.path.exists(bat_path):
            with open(bat_path, "r", encoding="utf-8", errors="ignore") as f:
                bat_text = f.read()
            assert ("v1.1.3" in bat_text) or ("v1.1.4" in bat_text) or ("v1.1.5" in bat_text) or ("v1.1" in bat_text)

    def test_file_list_model_ignores_unknown_and_previous_reports(self, tmp_path):
        """FileListModel.add_paths must ignore previous reports and unknown files rather than adding them as Catalogs."""
        from app_gui import FileListModel

        # Valid order
        order_file = str(tmp_path / "9011.xlsx")
        pd.DataFrame([{"الصنف": "Panadol", "الكمية": 10}]).to_excel(order_file, index=False)

        # Valid catalog
        cat_file = str(tmp_path / "مخزن_الامانة.pdf")
        with open(cat_file, "wb") as f:
            f.write(b"%PDF-1.4 sample")

        # Previous output files that should NOT become catalogs
        prev_report1 = str(tmp_path / "Procurement_Order_Optimized_2026-09-11.xlsx")
        pd.DataFrame([{"Report": 1}]).to_excel(prev_report1, index=False)

        prev_report2 = str(tmp_path / "أفضل_اسعار_2026-09-11.xlsx")
        pd.DataFrame([{"Report": 2}]).to_excel(prev_report2, index=False)

        # Temporary lock file
        temp_lock = str(tmp_path / "~$temp_order.xlsx")
        with open(temp_lock, "wb") as f:
            f.write(b"lock")

        # Unsupported file
        unknown_txt = str(tmp_path / "notes.txt")
        with open(unknown_txt, "w") as f:
            f.write("notes")

        model = FileListModel()
        added, dups = model.add_paths([order_file, cat_file, prev_report1, prev_report2, temp_lock, unknown_txt])

        assert added == 2, f"Expected exactly 2 added files (1 order + 1 catalog), got {added}"
        assert len(model.get_order_files()) == 1
        assert len(model.get_catalog_files()) == 1
        assert model.get_order_files()[0] == os.path.normpath(order_file)
        assert model.get_catalog_files()[0] == os.path.normpath(cat_file)

    def test_discount_bounds_and_catalog_noise_filtering(self):
        """Discounts > 85% must be rejected as corrupt; software vendor ads and footers must be flagged as noise."""
        from src.normalizer import parse_discount, is_catalog_noise

        # Valid discounts
        assert parse_discount("25%") == 0.25
        assert parse_discount("33.5%") == 0.335
        assert parse_discount(0.20) == 0.20
        assert parse_discount(0.85) == 0.85

        # Corrupted / invalid discounts (> 85% or negative)
        assert parse_discount("120%") == 0.0
        assert parse_discount(120) == 0.0
        assert parse_discount(120.0) == 0.0
        assert parse_discount(95) == 0.0
        assert parse_discount("95%") == 0.0
        assert parse_discount("-10%") == 0.0

        # Noise patterns
        assert is_catalog_noise("0165541990 & 0165541991 شركة اورجا سوفت محمد فهمى") is True
        assert is_catalog_noise("اروا سوفت للبرمجيات 01012345678") is True
        assert is_catalog_noise("م 05:02:58") is True
        assert is_catalog_noise("ص 11:30:00") is True
        assert is_catalog_noise("2026-09-11 14:00") is True
        assert is_catalog_noise("01023456789") is True
        assert is_catalog_noise("Panadol Extra 24 Tab") is False
        assert is_catalog_noise("كتافلام 50 مجم 20 قرص") is False

    def test_gemini_quota_exhaustion_breaks_batch_loop(self):
        """GeminiMedicineMatcher.batch_match must break immediately upon 429 quota exhaustion without redundant calls."""
        from src.gemini_matcher import GeminiMedicineMatcher

        matcher = GeminiMedicineMatcher(api_key="dummy_key", enabled=True)
        matcher.enabled = True

        call_count = 0

        def mock_process_batch(batch, candidates):
            nonlocal call_count
            call_count += 1
            # Simulate quota exhaustion disabling the matcher
            matcher.enabled = False
            return {}

        matcher._process_batch = mock_process_batch

        catalog_df = pd.DataFrame([{"item_name": "Panadol 500mg"}])
        items = [f"Item_{i}" for i in range(150)]  # 150 items with batch_size=50 would take 3 calls

        results = matcher.batch_match(items, catalog_df, batch_size=50)
        assert call_count == 1, f"Expected exactly 1 call before breaking, but got {call_count}"
        assert results == {}
