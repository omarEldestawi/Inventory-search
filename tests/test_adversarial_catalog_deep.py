# -*- coding: utf-8 -*-
"""
Empirical Adversarial Deep Audit Suite: Milestone 1_2
Catalog Extraction, Boundaries, Glitches, Ligatures, and Error Handling across all 23 catalogs in train/
Author: Challenger M1_2 (Empirical Challenger)
"""
import os
import sys
import unittest
import tempfile
import pandas as pd
import numpy as np

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.pdf_parser import PDFCatalogParser
from src.normalizer import (
    AL_HADABA_FONT_MAP,
    REVERSED_TOKEN_MAP,
    CANONICAL_NOISE_WORDS,
)

EXPECTED_SCHEMA = [
    'warehouse_name', 'item_name', 'normalized_name', 'dosage',
    'unit_size', 'base_price', 'discount_rate', 'stock_status'
]

TRAIN_DIR = os.path.join(PROJECT_ROOT, "train")
if not os.path.isdir(TRAIN_DIR):
    TRAIN_DIR = os.getenv("TRAIN_DIR", os.path.join(os.path.expanduser("~"), "Desktop", "train"))


class TestAdversarialDeepCatalogAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert os.path.isdir(TRAIN_DIR), f"Train directory not found: {TRAIN_DIR}"
        cls.pdf_files = sorted([
            f for f in os.listdir(TRAIN_DIR)
            if f.lower().endswith(".pdf") and not f.startswith(("anon_", "synthetic_", "temp_"))
        ])
        assert len(cls.pdf_files) == 23, f"Expected 23 PDF catalogs, found {len(cls.pdf_files)}"

        cls.catalog_dfs = {}
        cls.catalog_stats = {}
        cls.parsing_crashes = {}

        print("\n" + "=" * 80)
        print("EMPIRICAL AUDIT: Parsing all 23 PDF catalogs in train/...")
        print("=" * 80)

        for fname in cls.pdf_files:
            fpath = os.path.join(TRAIN_DIR, fname)
            try:
                parser = PDFCatalogParser(fpath)
                df = parser.parse()
                cls.catalog_dfs[fname] = df
                cls.catalog_stats[fname] = {
                    "count": len(df),
                    "warehouse": parser.warehouse_name,
                    "min_price": float(df['base_price'].min()) if not df.empty else 0.0,
                    "max_price": float(df['base_price'].max()) if not df.empty else 0.0,
                    "mean_price": float(df['base_price'].mean()) if not df.empty else 0.0,
                    "min_discount": float(df['discount_rate'].min()) if not df.empty else 0.0,
                    "max_discount": float(df['discount_rate'].max()) if not df.empty else 0.0,
                    "mean_discount": float(df['discount_rate'].mean()) if not df.empty else 0.0,
                    "zero_discount_count": int((df['discount_rate'] == 0.0).sum()) if not df.empty else 0,
                    "discounted_count": int((df['discount_rate'] > 0.0).sum()) if not df.empty else 0,
                }
                safe_fname = fname.encode('ascii', 'backslashreplace').decode('ascii')
                print(f"  [OK] {safe_fname}: {len(df)} items | WH: {parser.warehouse_name} | Price [{cls.catalog_stats[fname]['min_price']:.2f} - {cls.catalog_stats[fname]['max_price']:.2f}] | Disc [{cls.catalog_stats[fname]['min_discount']*100:.1f}% - {cls.catalog_stats[fname]['max_discount']*100:.1f}%]")
            except Exception as e:
                cls.parsing_crashes[fname] = str(e)
                print(f"  [CRASH] {fname}: {e}")

        cls.total_extracted_items = sum(len(df) for df in cls.catalog_dfs.values())
        print("=" * 80)
        print(f"Total valid offers extracted across 23 catalogs: {cls.total_extracted_items}")
        print("=" * 80 + "\n")

    def test_01_all_23_catalogs_present_zero_crashes(self):
        """Verify exactly 23 catalogs exist and 0 crashes occurred."""
        self.assertEqual(len(self.pdf_files), 23, "Must discover exactly 23 PDF catalogs")
        self.assertEqual(len(self.parsing_crashes), 0, f"Encountered parsing crashes: {self.parsing_crashes}")
        self.assertEqual(len(self.catalog_dfs), 23, "All 23 catalogs must produce DataFrames")

    def test_02_zero_empty_tables(self):
        """Verify that NO catalog table is empty."""
        empty_catalogs = [fname for fname, df in self.catalog_dfs.items() if df.empty or len(df) == 0]
        self.assertEqual(len(empty_catalogs), 0, f"Found empty catalog tables: {empty_catalogs}")
        for fname, df in self.catalog_dfs.items():
            self.assertGreater(len(df), 0, f"Catalog {fname} has 0 extracted items")

    def test_03_total_valid_offers_threshold(self):
        """Verify total valid offers >= 11,000 threshold."""
        self.assertGreaterEqual(
            self.total_extracted_items,
            11000,
            f"Total offers ({self.total_extracted_items}) is below threshold 11,000"
        )

    def test_04_schema_and_column_conformance(self):
        """Verify exact schema and no null columns across all catalogs."""
        for fname, df in self.catalog_dfs.items():
            self.assertEqual(list(df.columns), EXPECTED_SCHEMA, f"Schema mismatch in {fname}")
            # Ensure no entirely null column
            for col in EXPECTED_SCHEMA:
                if col in ['dosage', 'unit_size']:
                    continue  # Optional attributes
                self.assertFalse(df[col].isna().all(), f"Column {col} is entirely null in {fname}")

    def test_05_price_boundaries_and_numeric_validity(self):
        """Verify prices are positive, non-negative, finite numbers within valid ranges."""
        for fname, df in self.catalog_dfs.items():
            prices = df['base_price']
            # Numeric and not null
            self.assertTrue(pd.api.types.is_numeric_dtype(prices), f"base_price not numeric in {fname}")
            self.assertFalse(prices.isna().any(), f"NaN base_price in {fname}")
            self.assertFalse(np.isinf(prices).any(), f"Infinite base_price in {fname}")

            # Non-negative and positive
            non_positive = df[df['base_price'] <= 0.0]
            self.assertTrue(non_positive.empty, f"Found base_price <= 0 in {fname}: {non_positive[['item_name', 'base_price']].to_dict(orient='records')}")

            # Extreme outliers check (prices >= 10,000 EGP are invalid pharmaceutical outliers in Egypt)
            high_prices = df[df['base_price'] >= 10000.0]
            self.assertTrue(high_prices.empty, f"Found base_price >= 10,000 in {fname}: {high_prices[['item_name', 'base_price']].to_dict(orient='records')}")

    def test_06_discount_boundaries_and_validity(self):
        """Verify discounts are within [0.0, 1.0] (0% to 100%), finite and not NaN."""
        for fname, df in self.catalog_dfs.items():
            discounts = df['discount_rate']
            self.assertTrue(pd.api.types.is_numeric_dtype(discounts), f"discount_rate not numeric in {fname}")
            self.assertFalse(discounts.isna().any(), f"NaN discount_rate in {fname}")
            self.assertFalse(np.isinf(discounts).any(), f"Infinite discount_rate in {fname}")

            negative_discounts = df[df['discount_rate'] < 0.0]
            self.assertTrue(negative_discounts.empty, f"Found negative discount in {fname}: {negative_discounts[['item_name', 'discount_rate']].to_dict(orient='records')}")

            excessive_discounts = df[df['discount_rate'] > 1.0]
            self.assertTrue(excessive_discounts.empty, f"Found discount > 1.0 in {fname}: {excessive_discounts[['item_name', 'discount_rate']].to_dict(orient='records')}")

    def test_07_item_name_hygiene_and_non_emptiness(self):
        """Verify item_name strings are clean, not whitespace, length >= 2."""
        for fname, df in self.catalog_dfs.items():
            # Check for empty or blank strings
            blanks = df[df['item_name'].str.strip() == ""]
            self.assertTrue(blanks.empty, f"Found blank item_name in {fname}")

            # Check min length >= 2
            short_names = df[df['item_name'].str.strip().str.len() < 2]
            self.assertTrue(short_names.empty, f"Found abnormally short item_name in {fname}: {short_names[['item_name']].to_dict(orient='records')}")

            # Check normalized_name is non-empty
            norm_blanks = df[df['normalized_name'].str.strip() == ""]
            self.assertTrue(norm_blanks.empty, f"Found blank normalized_name in {fname}")

    def test_08_no_untranslated_runic_ligatures(self):
        """Verify that Aboriginal runic glyphs from Al-Hadaba format were decoded."""
        runic_chars = set(AL_HADABA_FONT_MAP.keys())
        corrupt_items = []
        for fname, df in self.catalog_dfs.items():
            # iterrows builds Series that deep-copy the catalog's diagnostic
            # attrs for every offer. Iterate the two value columns directly.
            for name, norm in zip(df['item_name'], df['normalized_name']):
                for ch in runic_chars:
                    if ch in name or ch in norm:
                        corrupt_items.append((fname, ch, name, norm))

        self.assertEqual(
            len(corrupt_items),
            0,
            f"Found untranslated runic ligatures in catalogs: {corrupt_items[:10]}"
        )

    def test_09_no_raw_reversed_arabic_tokens(self):
        """Verify known reversed tokens are decoded in normalized_name."""
        reversed_tokens = list(REVERSED_TOKEN_MAP.keys())
        leakage = []
        for fname, df in self.catalog_dfs.items():
            for name, norm in zip(df['item_name'], df['normalized_name']):
                tokens = set(norm.split())
                for rev_tok in reversed_tokens:
                    # check if rev_tok is a distinct token in normalized_name
                    if rev_tok in tokens and rev_tok not in ['لم']:  # 'لم' could rarely be a valid negative particle
                        leakage.append((fname, rev_tok, name, norm))

        self.assertEqual(
            len(leakage),
            0,
            f"Found un-reversed Arabic tokens in normalized_name: {leakage[:10]}"
        )

    def test_10_warehouse_vendor_name_hygiene(self):
        """Verify warehouse_name is clean, not 'ERROR', not empty, and recognizable."""
        for fname, df in self.catalog_dfs.items():
            wh_series = df['warehouse_name']
            self.assertFalse((wh_series == "ERROR").any(), f"Warehouse name is 'ERROR' in {fname}")
            self.assertFalse((wh_series.str.strip() == "").any(), f"Empty warehouse name in {fname}")
            self.assertTrue((wh_series.str.len() >= 3).all(), f"Warehouse name too short in {fname}")

    def test_11_adversarial_parser_error_handling(self):
        """Adversarially test PDFCatalogParser on edge/malformed files."""
        # 1. 0-byte file
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            empty_path = f.name
        try:
            p = PDFCatalogParser(empty_path)
            res = p.parse()
            self.assertIsInstance(res, pd.DataFrame)
            self.assertEqual(len(res), 0)
            self.assertEqual(list(res.columns), EXPECTED_SCHEMA)
            self.assertIsNotNone(p.last_error)
        finally:
            if os.path.exists(empty_path):
                os.remove(empty_path)

        # 2. Corrupted file with random bytes
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 \x00\xff\xfe\x01\x02 corrupt data stream endobj")
            corrupt_path = f.name
        try:
            p = PDFCatalogParser(corrupt_path)
            res = p.parse()
            self.assertIsInstance(res, pd.DataFrame)
            self.assertEqual(len(res), 0)
            self.assertEqual(list(res.columns), EXPECTED_SCHEMA)
        finally:
            if os.path.exists(corrupt_path):
                os.remove(corrupt_path)

        # 3. Non-existent file
        fake_path = os.path.join(tempfile.gettempdir(), "non_existent_catalog_99999.pdf")
        p = PDFCatalogParser(fake_path)
        res = p.parse()
        self.assertIsInstance(res, pd.DataFrame)
        self.assertEqual(len(res), 0)
        self.assertIsNotNone(p.last_error)


if __name__ == "__main__":
    unittest.main()
