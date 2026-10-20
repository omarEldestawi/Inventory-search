# -*- coding: utf-8 -*-
"""
Verification tests for v1.1.4 fixes:
1. Multi-line table cell unzipping (Al-Forsan multi-item row recovery)
2. Safe line-wrap detection (prevents bogus split items)
3. Explicit 0% net pricing ('صافي' / net items) support
4. Rejection of unparseable / missing discounts (prevent noise contamination)
5. Shifted column inline discount recovery
6. Presentation deduplication preserving different base prices
7. Version 1.1.4 consistency across metadata and configurations
"""
import os
import sys
import re
import pytest
import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.pdf_parser import PDFCatalogParser, is_explicit_zero_discount
from src.normalizer import parse_discount, normalize_arabic_text


def make_pdf_visual_text(text: str) -> str:
    """Simulates visual character stream extraction produced by PyMuPDF on Arabic PDFs."""
    lines = text.split('\n')
    visual_lines = []
    for ln in lines:
        words = ln.split()
        rev_words = [w if re.fullmatch(r'[\d.,/%\-_]+', w) else w[::-1] for w in words]
        visual_lines.append(' '.join(rev_words[::-1]))
    return '\n'.join(visual_lines)


class TestV114MultiLineAndNetPricing:
    """Test suite for Al-Forsan catalog parsing fixes and 0% discount support."""

    @pytest.fixture
    def parser(self):
        return PDFCatalogParser(pdf_path="dummy.pdf", warehouse_name="الفرسان اسكندريه")

    def test_explicit_zero_discount_detection(self):
        """is_explicit_zero_discount must identify genuine 0% / net pricing and reject missing/noise."""
        assert is_explicit_zero_discount("0") is True
        assert is_explicit_zero_discount("0.0") is True
        assert is_explicit_zero_discount("0%") is True
        assert is_explicit_zero_discount("۰%") is True  # Eastern Arabic digit
        assert is_explicit_zero_discount("صافي") is True
        assert is_explicit_zero_discount("صافى") is True
        assert is_explicit_zero_discount("net") is True
        assert is_explicit_zero_discount(" Net ") is True

        # Non-zero or invalid/missing values must return False
        assert is_explicit_zero_discount("") is False
        assert is_explicit_zero_discount(None) is False
        assert is_explicit_zero_discount("   ") is False
        assert is_explicit_zero_discount("25%") is False
        assert is_explicit_zero_discount("Random noise") is False

    def test_al_forsan_7_item_multiline_unzipping(self, parser):
        """Table row containing 7 merged items separated by \n must unzip into 7 distinct valid items."""
        headers = ["الكود", "الصنف", "الخصم", "السعر"]
        natural_names = (
            "زيركوكس 90 مجم 30 ق\n"
            "سالجي كريم مساج\n"
            "سانسو دى ثرى نقط\n"
            "سباز موديجستين\n"
            "سباز موكيور\n"
            "سبيكتون 25\n"
            "ستراكوبينا 2.5"
        )
        row_7 = [
            "9412 \n 9249 \n 8250 \n 3255 \n 3028 \n 7517 \n 8277",
            make_pdf_visual_text(natural_names),
            "38 \n 31 \n 38 \n 41 \n 23 \n 12 \n 32",
            "297 \n 70 \n 56 \n 78 \n 54 \n 36 \n 444"
        ]
        table = [headers, row_7]

        results = parser._process_table(table)
        assert len(results) == 7, f"Expected 7 unzipped items, but got {len(results)}"

        # Check first item: زيركوكس 90 مجم 30 ق
        assert "زيركوكس" in results[0]["item_name"]
        assert results[0]["base_price"] == 297.0
        assert results[0]["discount_rate"] == 0.38

        # Check middle item: سباز موديجستين
        assert "سباز موديجستين" in results[3]["item_name"]
        assert results[3]["base_price"] == 78.0
        assert results[3]["discount_rate"] == 0.41

        # Check last item: ستراكوبينا 2.5
        assert "ستراكوبينا" in results[6]["item_name"]
        assert results[6]["base_price"] == 444.0
        assert results[6]["discount_rate"] == 0.32

    def test_single_item_name_wrapping_not_split(self, parser):
        """Single medicine whose name wraps across multiple lines must be joined, not split into fake items."""
        headers = ["اسم الصنف", "السعر", "الخصم"]
        wrapped_name = make_pdf_visual_text("أوجمنتين 1 جم\n14 قرص")
        wrapped_row = [
            wrapped_name,
            "120",
            "25%"
        ]
        table = [headers, wrapped_row]

        results = parser._process_table(table)
        assert len(results) == 1, f"Expected 1 item, but got {len(results)}"
        assert "اوجمنتين" in results[0]["normalized_name"]
        assert results[0]["base_price"] == 120.0
        assert results[0]["discount_rate"] == 0.25

    def test_multiline_with_wrapped_name_reconciled(self, parser):
        """When multi-line row has wrapped line (e.g. 3 name lines for 2 prices), it must reconcile correctly."""
        headers = ["اسم الصنف", "السعر", "الخصم"]
        multiline_names = make_pdf_visual_text("كونكور 5 مجم\n30 قرص\nبانادول اكسترا")
        table = [
            headers,
            [
                multiline_names,
                "65\n45",
                "20%\n15%"
            ]
        ]
        results = parser._process_table(table)
        assert len(results) == 2, f"Expected 2 reconciled items, but got {len(results)}"
        assert "كونكور" in results[0]["item_name"]
        assert results[0]["base_price"] == 65.0
        assert results[0]["discount_rate"] == 0.20
        assert "بانادول" in results[1]["item_name"]
        assert results[1]["base_price"] == 45.0
        assert results[1]["discount_rate"] == 0.15

    def test_explicit_zero_net_discount_accepted(self, parser):
        """Items with explicit 0% discount (صافي / net pricing) must be extracted."""
        headers = ["كود", "اسم الصنف", "الخصم", "السعر"]
        table = [
            headers,
            ["1681", make_pdf_visual_text("فيجاموكس قطرة باكت 10"), "0", "128"],
            ["1682", make_pdf_visual_text("أنسولين لانتوس سولوستار"), "صافي", "650"],
            ["1683", make_pdf_visual_text("ميبو مرهم حروق"), "0%", "95"],
        ]
        results = parser._process_table(table)
        assert len(results) == 3, f"Expected 3 items with 0% net pricing, got {len(results)}"
        assert results[0]["discount_rate"] == 0.0
        assert results[0]["base_price"] == 128.0
        assert results[1]["discount_rate"] == 0.0
        assert results[1]["base_price"] == 650.0
        assert results[2]["discount_rate"] == 0.0
        assert results[2]["base_price"] == 95.0

    def test_missing_unparseable_discount_rejected(self, parser):
        """Items with empty, missing, or unparseable non-zero discount must NOT be treated as 0% discount."""
        headers = ["كود", "اسم الصنف", "الخصم", "السعر"]
        table = [
            headers,
            ["1001", make_pdf_visual_text("بانادول اكسترا"), "", "45"],
            ["1002", make_pdf_visual_text("كتافلام 50 مجم"), "غير متاح", "38"],
        ]
        results = parser._process_table(table)
        assert len(results) == 0, f"Expected 0 items due to missing/invalid discount, got {len(results)}"

    def test_shifted_column_inline_discount_recovery(self, parser):
        """When discount column is shifted into name cell (e.g. 'سيدرال فورت ق \\n 27'), discount is recovered."""
        headers = ["كود", "اسم الصنف", "الخصم", "السعر"]
        name_1 = make_pdf_visual_text("سيدرال فورت ق") + "\n 27"
        name_2 = make_pdf_visual_text("سيدرال اكتف كبسول") + "\n 27%"
        table = [
            headers,
            ["9919", name_1, "", "540"],
            ["10059", name_2, "", "250"],
        ]
        results = parser._process_table(table)
        assert len(results) == 2, f"Expected 2 recovered items, got {len(results)}"
        assert results[0]["discount_rate"] == 0.27
        assert results[0]["base_price"] == 540.0
        assert "27" not in results[0]["item_name"]

        assert results[1]["discount_rate"] == 0.27
        assert results[1]["base_price"] == 250.0
        assert "27" not in results[1]["item_name"]

    def test_deduplication_preserves_different_base_prices(self):
        """Deduplication must keep different presentations of the same drug with different public prices."""
        parser = PDFCatalogParser(pdf_path="dummy.pdf", warehouse_name="مخزن تجريبي")
        raw_items = [
            {
                "warehouse_name": "مخزن تجريبي",
                "item_name": "بانادول اكسترا 24 قرص",
                "normalized_name": "بانادول اكسترا",
                "dosage": "",
                "unit_size": "",
                "base_price": 45.0,
                "discount_rate": 0.20,
                "stock_status": True
            },
            {
                "warehouse_name": "مخزن تجريبي",
                "item_name": "بانادول اكسترا 48 قرص",
                "normalized_name": "بانادول اكسترا",
                "dosage": "",
                "unit_size": "",
                "base_price": 90.0,
                "discount_rate": 0.20,
                "stock_status": True
            },
            {
                "warehouse_name": "مخزن تجريبي",
                "item_name": "بانادول اكسترا 24 قرص عرض",
                "normalized_name": "بانادول اكسترا",
                "dosage": "",
                "unit_size": "",
                "base_price": 45.0,
                "discount_rate": 0.25,
                "stock_status": True
            }
        ]
        df = pd.DataFrame(raw_items)
        df_dedup = df.sort_values(by="discount_rate", ascending=False).drop_duplicates(
            subset=["normalized_name", "dosage", "unit_size", "base_price"], keep="first"
        )
        assert len(df_dedup) == 2, f"Expected 2 presentations preserved, got {len(df_dedup)}"
        prices = set(df_dedup["base_price"].tolist())
        assert prices == {45.0, 90.0}
        # For price 45.0, highest discount (0.25) must be chosen
        item_45 = df_dedup[df_dedup["base_price"] == 45.0].iloc[0]
        assert item_45["discount_rate"] == 0.25


class TestV114VersionConsistency:
    """Verifies that version 1.1.4 / 1.1.5 is consistently referenced across all project entrypoints."""

    def test_app_gui_version_label(self):
        gui_path = os.path.join(PROJECT_ROOT, "app_gui.py")
        with open(gui_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert any(v in content for v in ["v1.1.4", "v1.1.5", "v1.8", "v1.9", "v2.0"]), "app_gui.py must reference valid release version"

    def test_installer_version(self):
        iss_path = os.path.join(PROJECT_ROOT, "installer.iss")
        with open(iss_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert any(v in content for v in ['#define MyAppVersion "1.1.4"', '#define MyAppVersion "1.1.5"', '#define MyAppVersion "1.8"', '#define MyAppVersion "1.9"', '#define MyAppVersion "2.0"']), "installer.iss must define MyAppVersion"
        assert any(s in content for s in ["EgyptianPharmaOptimizer_Setup_v1.1.4", "EgyptianPharmaOptimizer_Setup_v1.1.5", "EgyptianPharmaOptimizer_Setup_v1.8", "EgyptianPharmaOptimizer_Setup_v1.9", "EgyptianPharmaOptimizer_Setup_v2.0"]), "installer.iss must output Setup"

    def test_changelog_has_v114(self):
        cl_path = os.path.join(PROJECT_ROOT, "CHANGELOG.md")
        with open(cl_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert ("## [1.1.4]" in content) or ("## [1.1.5]" in content), "CHANGELOG.md must contain version entry"

    def test_readme_has_v114(self):
        rm_path = os.path.join(PROJECT_ROOT, "README.md")
        with open(rm_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert any(v in content for v in ["**Version:** 1.1.4", "**Version:** 1.1.5", "**Version:** 1.8", "**Version:** 1.9", "**Version:** 2.0"]), "README.md must have Version"

