# -*- coding: utf-8 -*-
"""
Automated Verification Suite for Release 2.0:
1. Switched Price/Discount Column Extraction & Sanity Check on
   `input/catalogs/شركة مخزن الدولية الحديثة للادوية.pdf` (529 items, 6 pages, 2-column ArwaSoft).
2. Batch/Column-Level (`_should_swap_price_and_discount`) & Per-Item Row-Level
   (`_sanity_check_item_price_and_discount`) Sanity Checks across merged single-cell rows,
   standard multi-column tables, headerless continuation pages, and inline price hints.
3. Medication Knowledge Base (`data/medications.db`) registration of the new catalog's
   medications and aliases.
4. Version 2.0 consistency across `app_gui.py`, `installer.iss`, `README.md`, and `CHANGELOG.md`.
"""
import os
import pytest
import pandas as pd

from src.pdf_parser import (
    PDFCatalogParser,
    extract_inline_price_hint,
    fix_arabic_bidi_if_needed,
    get_ocr_engine,
    get_table_engine,
)
from src.medication_db import MedicationDB
from src.normalizer import normalize_vendor_name, unreverse_arabic_text

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEW_CATALOG_PATH = os.path.join(PROJECT_ROOT, "input", "catalogs", "شركة مخزن الدولية الحديثة للادوية.pdf")
ZAHRA_CATALOG_PATH = os.path.join(PROJECT_ROOT, "input", "catalogs", "تحديث زهره.pdf")


class TestV20PriceDiscountSanityChecks:
    """Tests for switched Price & Discount detection and automatic correction."""

    def test_inline_price_hint_extraction(self):
        assert extract_inline_price_hint("اريك اقراص سعر 144") == 144.0
        assert extract_inline_price_hint("انتينال شراب سعر /24امون") == 24.0
        assert extract_inline_price_hint("ابيرزول 40 مجم 41.5ج") == 41.5
        assert extract_inline_price_hint("انريتش بلس شراب س 81 س ج") == 81.0
        assert extract_inline_price_hint("ايبروفين 400 مجم 20 قرص") is None

    def test_arabic_decimal_separator_preserved_in_unreverse(self):
        raw = "ج٤١٫٥ مجم ٤٠ لوزاريبا"
        unrev = fix_arabic_bidi_if_needed(raw, force_reverse=True)
        assert "41.5" in unrev
        assert "40" in unrev
        assert "ابيرازول" in unrev

    def test_vendor_normalization_for_modern_international_warehouse(self):
        assert normalize_vendor_name("شركة مخزن الدولية الحديثة للادوية") == "مخزن الدولية الحديثة"
        # Existing generic rule must remain intact
        assert normalize_vendor_name("مخزن الدولية للأدوية") == "الدولية فارما"

    def test_switched_merged_table_auto_corrected(self):
        """
        Simulates a merged single-cell table where [Price, Discount, Name] is switched
        instead of standard [Discount, Price, Name], even without a header row.
        """
        parser = PDFCatalogParser()
        parser.warehouse_name = "مخزن اختبار"
        table = [
            ["رعسلا مصخلا فنصلا مسإ", None],
            ["321 22 وكيبأ/لوبمأ 75 لانوجيبأ", None],
            ["35 41 نومأ بارش نوديبا", None],
            ["76 34 76 رعس صارقا تسافيبا", None],
            ["80 42 شد وسنلك", None],
        ]
        items = parser._process_table(table)
        assert len(items) == 4
        by_price = {it["base_price"]: it for it in items}
        assert by_price[321.0]["discount_rate"] == 0.22
        assert by_price[35.0]["discount_rate"] == 0.41
        assert by_price[76.0]["discount_rate"] == 0.34
        assert by_price[80.0]["discount_rate"] == 0.42
        assert by_price[80.0]["item_name"] == "كلنسو دش"

    def test_switched_standard_columns_auto_corrected(self):
        """
        Simulates a multi-column table where the header or column order has Price and Discount switched,
        or where a headerless table has Price in column 0 and Discount in column 1.
        """
        parser = PDFCatalogParser()
        parser.warehouse_name = "مخزن اختبار"
        # Headerless table where col 0 is Price (with values > 85 and inline price hints) and col 1 is Discount
        table = [
            ["240", "28", "بانادول اكسترا اقراص سعر 240"],
            ["155", "33", "اوجمنتين 1 جم اقراص سعر 155"],
            ["48", "36", "انتينال كبسول سعر 48"],
            ["65", "40", "كتافلام 50 مجم اقراص سعر 65"],
        ]
        items = parser._process_table(table)
        assert len(items) == 4
        prices = [it["base_price"] for it in items]
        discounts = [it["discount_rate"] for it in items]
        assert prices == [240.0, 155.0, 48.0, 65.0]
        assert discounts == [0.28, 0.33, 0.36, 0.40]

    def test_per_item_sanity_check_recovers_single_inverted_row(self):
        """
        Even in a normal table, if an individual row has its price and discount accidentally swapped
        (e.g. raw discount cell has 180 and price cell has 32, or inline hint says سعر 79),
        _sanity_check_item_price_and_discount corrects that item.
        """
        parser = PDFCatalogParser()
        p1, d1 = parser._sanity_check_item_price_and_discount(
            "دواء تجريبي اقراص", price_val=32.0, discount_val=0.0, raw_price_num=32.0, raw_disc_num=180.0
        )
        assert p1 == 180.0
        assert d1 == 0.32

        p2, d2 = parser._sanity_check_item_price_and_discount(
            "دواء تجريبي سعر 79 جديد", price_val=35.0, discount_val=0.79, raw_price_num=35.0, raw_disc_num=79.0
        )
        assert p2 == 79.0
        assert d2 == 0.35

    def test_new_catalog_extraction_and_database_registration(self):
        """Verifies 100% extraction of `شركة مخزن الدولية الحديثة للادوية.pdf` and DB registration."""
        assert os.path.exists(NEW_CATALOG_PATH), f"Expected catalog at {NEW_CATALOG_PATH}"
        parser = PDFCatalogParser(NEW_CATALOG_PATH)
        df = parser.parse()

        assert parser.warehouse_name == "مخزن الدولية الحديثة"
        assert len(df) == 529

        # Spot-check left-column and right-column items across pages 1-6
        epigonal = df[df["item_name"].str.contains("ابيجونال")]
        assert not epigonal.empty
        assert float(epigonal.iloc[0]["base_price"]) == 321.0
        assert float(epigonal.iloc[0]["discount_rate"]) == 0.22

        apidone = df[df["item_name"].str.contains("ابيدون")]
        assert not apidone.empty
        assert float(apidone.iloc[0]["base_price"]) == 35.0
        assert float(apidone.iloc[0]["discount_rate"]) == 0.41

        acne = df[df["normalized_name"].str.contains("اكني اكتي")]
        assert not acne.empty
        assert float(acne.iloc[0]["base_price"]) == 39.0
        assert float(acne.iloc[0]["discount_rate"]) == 0.33

        clenso = df[df["item_name"].str.contains("كلنسو دش")]
        assert not clenso.empty
        assert float(clenso.iloc[0]["base_price"]) == 80.0
        assert float(clenso.iloc[0]["discount_rate"]) == 0.42

        broncho = df[df["item_name"].str.contains("برونكوفاكسوم")]
        assert not broncho.empty
        assert float(broncho.iloc[0]["base_price"]) == 158.0
        assert float(broncho.iloc[0]["discount_rate"]) == 0.32

        # Verify that no item has its inline price matching the discount rate instead of base_price
        swapped_errors = []
        for _, row in df.iterrows():
            hint = extract_inline_price_hint(row["item_name"])
            if hint is not None:
                disc_pct = round(float(row["discount_rate"]) * 100.0, 2)
                if abs(disc_pct - hint) <= 0.15 and abs(float(row["base_price"]) - hint) > 0.5:
                    swapped_errors.append((row["item_name"], row["base_price"], row["discount_rate"]))
        assert swapped_errors == [], f"Found items with swapped price/discount: {swapped_errors}"

        # Verify MedicationDB contains the new catalog's items
        db = MedicationDB()
        assert db.count_standards() >= 6200
        assert db.count_aliases() >= 107000
        assert db.resolve("ابيجونال 75 امبول / ابيكو") is not None
        assert db.resolve("برونكوفاكسوم للاطفال / ممفيس") is not None
        assert db.resolve("كلنسو دش") is not None

    def test_version_20_consistency(self):
        """Verifies version 2.2 across app_gui.py, installer.iss, README.md, and CHANGELOG.md."""
        with open(os.path.join(PROJECT_ROOT, "app_gui.py"), "r", encoding="utf-8") as f:
            gui_content = f.read()
        assert 'self.app_version = "2.2"' in gui_content
        assert "v2.2" in gui_content

        with open(os.path.join(PROJECT_ROOT, "installer.iss"), "r", encoding="utf-8") as f:
            iss_content = f.read()
        assert '#define MyAppVersion "2.2"' in iss_content
        assert "OutputBaseFilename=EgyptianPharmaOptimizer_Setup_v2.2" in iss_content

        with open(os.path.join(PROJECT_ROOT, "README.md"), "r", encoding="utf-8") as f:
            readme_content = f.read()
        assert "**Version:** 2.2" in readme_content

        with open(os.path.join(PROJECT_ROOT, "CHANGELOG.md"), "r", encoding="utf-8") as f:
            changelog_content = f.read()
        assert "## [2.2]" in changelog_content
        assert "## [2.1]" in changelog_content
        assert "## [2.0]" in changelog_content

    def test_zahra_pharm_3col_arwasoft_extraction_and_db_registration(self):
        """
        Verifies that `input/catalogs/تحديث زهره.pdf` (3-column ArwaSoft row-rectangle layout)
        extracts all 1,167 items across all 9 pages (fixing the 5-item bug) and is registered in MedicationDB.
        """
        assert os.path.exists(ZAHRA_CATALOG_PATH), f"Expected Zahra catalog at {ZAHRA_CATALOG_PATH}"
        assert normalize_vendor_name("تحديث زهره.pdf") == "زهرة فارم"

        parser = PDFCatalogParser(ZAHRA_CATALOG_PATH)
        df = parser.parse()

        assert parser.warehouse_name == "زهرة فارم"
        assert len(df) == 1167, f"Expected 1,167 items from تحديث زهره.pdf, got {len(df)}"

        # Spot-check items across all 3 columns and multi-line wrapped rows
        panadol = df[df["item_name"] == "بانادول ادفانس قرص"]
        assert not panadol.empty
        assert float(panadol.iloc[0]["base_price"]) == 92.0
        assert float(panadol.iloc[0]["discount_rate"]) == 0.365

        augram = df[df["item_name"] == "اوجرام 457 مجم شراب 80 مل"]
        assert not augram.empty
        assert float(augram.iloc[0]["base_price"]) == 81.0
        assert float(augram.iloc[0]["discount_rate"]) == 0.37

        centrum_wrap = df[df["item_name"].str.contains("سنترم سيدات عرض")]
        assert not centrum_wrap.empty
        assert float(centrum_wrap.iloc[0]["base_price"]) == 560.0
        assert float(centrum_wrap.iloc[0]["discount_rate"]) == 0.23

        militofix = df[df["item_name"].str.contains("ميليتوفكس تريو 1000 / 5 / 25")]
        assert not militofix.empty
        assert float(militofix.iloc[0]["base_price"]) == 486.0
        assert float(militofix.iloc[0]["discount_rate"]) == 0.26

        # Verify MedicationDB contains Zahra Pharm items
        db = MedicationDB()
        assert db.count_standards() >= 6800
        assert db.count_aliases() >= 117000
        assert db.resolve("ميليتوفكس تريو 1000 / 5 / 25 مجم قرص") is not None
        assert db.resolve("ليمتلس اوسوفورتين 5000 وحده قرص") is not None

    def test_failed_ocr_feature_archived(self):
        """
        Verifies that the failed RapidOCR/RapidTable feature is archived under
        `archive/failed_ocr_feature/`, engines return None, and the active GUI
        no longer renders the broken OCR button.
        """
        readme_path = os.path.join(PROJECT_ROOT, "archive", "failed_ocr_feature", "README_FAILED_OCR.md")
        legacy_code_path = os.path.join(PROJECT_ROOT, "archive", "failed_ocr_feature", "legacy_ocr_parser.py")
        archived_test_path = os.path.join(PROJECT_ROOT, "archive", "failed_ocr_feature", "test_ocr_parser.py")

        assert os.path.isfile(readme_path), "Expected README_FAILED_OCR.md in archive/failed_ocr_feature/"
        assert os.path.isfile(legacy_code_path), "Expected legacy_ocr_parser.py in archive/failed_ocr_feature/"
        assert os.path.isfile(archived_test_path), "Expected test_ocr_parser.py moved to archive/failed_ocr_feature/"
        assert not os.path.exists(os.path.join(PROJECT_ROOT, "tests", "test_ocr_parser.py"))

        with open(readme_path, "r", encoding="utf-8") as f:
            readme_text = f.read()
        assert "FAILED" in readme_text
        assert "ARCHIVED" in readme_text

        assert get_ocr_engine() is None

    def test_v22_updater_relaunch_and_verification(self):
        """
        Verifies v2.2 updater fixes:
        1. installer.iss has NO 'skipifsilent' on MyAppExeName run entry, ensuring silent update relaunch.
        2. installer.iss defines MyAppVersion '2.2' and OutputBaseFilename Setup_v2.2.
        3. updater.py contains supervisor batch generator with /SILENT and download integrity check.
        """
        iss_path = os.path.join(PROJECT_ROOT, "installer.iss")
        with open(iss_path, "r", encoding="utf-8") as f:
            iss_text = f.read()

        assert "skipifsilent" not in iss_text, "installer.iss must NOT contain skipifsilent so silent update relaunches"
        assert '#define MyAppVersion "2.2"' in iss_text
        assert "OutputBaseFilename=EgyptianPharmaOptimizer_Setup_v2.2" in iss_text

        updater_path = os.path.join(PROJECT_ROOT, "src", "updater.py")
        with open(updater_path, "r", encoding="utf-8") as f:
            updater_text = f.read()

        assert "run_pharma_update.bat" in updater_text
        assert "/SILENT" in updater_text
        assert "Incomplete download" in updater_text
        assert get_table_engine() is None
