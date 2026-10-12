# -*- coding: utf-8 -*-
"""
Empirical Adversarial Verification Suite: Milestone 1_2 Gen2
Catalog Yield, Schema Conformance, and Boundary Constraints across all 23 catalogs in train/
Author: Challenger M1_2 gen2 (Empirical Challenger)
"""
import os
import sys
import unittest
import pandas as pd
import numpy as np

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.pdf_parser import PDFCatalogParser
from src.normalizer import normalize_vendor_name

EXPECTED_SCHEMA = [
    'warehouse_name', 'item_name', 'normalized_name', 'dosage',
    'unit_size', 'base_price', 'discount_rate', 'stock_status'
]

TRAIN_DIR = os.path.join(PROJECT_ROOT, "train")
if not os.path.isdir(TRAIN_DIR):
    TRAIN_DIR = os.getenv("TRAIN_DIR", os.path.join(os.path.expanduser("~"), "Desktop", "train"))


class TestM12ChallengerCatalogVerification(unittest.TestCase):
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
        cls.parsing_errors = {}

        for fname in cls.pdf_files:
            fpath = os.path.join(TRAIN_DIR, fname)
            try:
                parser = PDFCatalogParser(fpath)
                df = parser.parse()
                cls.catalog_dfs[fname] = df
                cls.catalog_stats[fname] = {
                    "count": len(df),
                    "min_price": float(df['base_price'].min()) if not df.empty else 0.0,
                    "max_price": float(df['base_price'].max()) if not df.empty else 0.0,
                    "min_discount": float(df['discount_rate'].min()) if not df.empty else 0.0,
                    "max_discount": float(df['discount_rate'].max()) if not df.empty else 0.0,
                    "warehouse": parser.warehouse_name,
                    "columns": list(df.columns)
                }
            except Exception as e:
                cls.parsing_errors[fname] = str(e)

        stats_dir = os.path.join(PROJECT_ROOT, ".agents", "teamwork_preview_challenger_m1_2_gen2")
        if os.path.isdir(stats_dir):
            import json
            with open(os.path.join(stats_dir, "empirical_catalog_stats.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "total_items": sum(s["count"] for s in cls.catalog_stats.values()),
                    "catalogs": cls.catalog_stats
                }, f, ensure_ascii=False, indent=2)

    def test_01_catalog_count_and_no_crashes(self):
        """Verify that exactly 23 catalogs exist and 0 crashes occurred during parsing."""
        self.assertEqual(len(self.pdf_files), 23, "Must discover exactly 23 PDF catalogs")
        self.assertEqual(len(self.parsing_errors), 0, f"Encountered parsing crashes: {self.parsing_errors}")
        self.assertEqual(len(self.catalog_dfs), 23, "All 23 catalogs must be parsed into DataFrames")

    def test_02_strict_schema_conformance_all_23_catalogs(self):
        """Verify every single catalog DataFrame matches the exact required schema and non-empty rows."""
        for fname, df in self.catalog_dfs.items():
            with self.subTest(catalog=fname):
                self.assertIsInstance(df, pd.DataFrame, f"{fname} did not return a DataFrame")
                self.assertGreater(len(df), 0, f"{fname} produced 0 extracted items")
                self.assertEqual(
                    list(df.columns),
                    EXPECTED_SCHEMA,
                    f"{fname} columns do not match expected schema: {list(df.columns)} vs {EXPECTED_SCHEMA}"
                )

    def test_03_total_yield_threshold(self):
        """Verify total extracted items across all 23 catalogs reaches >= 11,000."""
        total_items = sum(len(df) for df in self.catalog_dfs.values())
        print(f"\n[EMPIRICAL EVIDENCE] Total yield across 23 catalogs: {total_items}")
        self.assertGreaterEqual(
            total_items,
            11000,
            f"Total catalog yield ({total_items}) is below mandatory minimum 11,000 items"
        )

    def test_04_specific_edge_case_catalog_gates(self):
        """Verify specific gate thresholds on known challenging catalogs."""
        gates = {
            "العربيه": 700,      # مخزن العربيه للصيادله الزقازيق
            "سينا": 300,         # سينا.pdf
            "القمة": 400,        # القمة شبين (2).pdf
            "دار الفؤاد": 200    # دار الفؤاد السبت33.pdf
        }
        for pattern, min_count in gates.items():
            matching_files = [f for f in self.catalog_dfs.keys() if pattern in f]
            for fname in matching_files:
                count = len(self.catalog_dfs[fname])
                safe_fname = fname.encode('ascii', 'backslashreplace').decode('ascii')
                sys.stdout.write(f"[GATE CHECK] {safe_fname}: {count} items (target: >= {min_count})\n")
                self.assertGreaterEqual(
                    count,
                    min_count,
                    f"Catalog '{fname}' yielded {count} items, expected at least {min_count}"
                )

    def test_05_strict_price_boundaries_all_catalogs(self):
        """Verify no item in any catalog has base_price >= 10,000.0 or base_price <= 0.0."""
        violations = []
        for fname, df in self.catalog_dfs.items():
            high_prices = df[df['base_price'] >= 10000.0]
            if not high_prices.empty:
                for _, r in high_prices.iterrows():
                    violations.append((fname, r['item_name'], r['base_price']))
            non_positive = df[df['base_price'] <= 0.0]
            if not non_positive.empty:
                for _, r in non_positive.iterrows():
                    violations.append((fname, r['item_name'], r['base_price']))

            # No NaNs
            self.assertFalse(df['base_price'].isna().any(), f"NaN base_price in {fname}")

        self.assertEqual(
            len(violations),
            0,
            f"Found {len(violations)} price boundary violations (>= 10,000 or <= 0): {violations[:5]}"
        )

    def test_06_strict_discount_boundaries_all_catalogs(self):
        """Verify discount_rate is between 0.0 and 1.0 (inclusive) and not NaN for all items."""
        violations = []
        for fname, df in self.catalog_dfs.items():
            neg_disc = df[df['discount_rate'] < 0.0]
            if not neg_disc.empty:
                for _, r in neg_disc.iterrows():
                    violations.append((fname, r['item_name'], r['discount_rate']))
            excess_disc = df[df['discount_rate'] > 1.0]
            if not excess_disc.empty:
                for _, r in excess_disc.iterrows():
                    violations.append((fname, r['item_name'], r['discount_rate']))

            self.assertFalse(df['discount_rate'].isna().any(), f"NaN discount_rate in {fname}")

        self.assertEqual(
            len(violations),
            0,
            f"Found {len(violations)} discount boundary violations (< 0 or > 1.0): {violations[:5]}"
        )

    def test_07_data_field_validity_and_types(self):
        """Verify data types and non-empty values for critical fields across all catalogs."""
        for fname, df in self.catalog_dfs.items():
            with self.subTest(catalog=fname):
                # warehouse_name non-empty string and not "ERROR"
                self.assertTrue((df['warehouse_name'].str.strip() != "").all(), f"Empty warehouse in {fname}")
                self.assertFalse((df['warehouse_name'] == "ERROR").any(), f"ERROR warehouse in {fname}")

                # item_name non-empty string
                self.assertTrue((df['item_name'].str.strip() != "").all(), f"Empty item_name in {fname}")
                self.assertTrue((df['item_name'].str.len() >= 2).all(), f"Suspiciously short item_name in {fname}")

                # normalized_name non-empty string
                self.assertTrue((df['normalized_name'].str.strip() != "").all(), f"Empty normalized_name in {fname}")

                # base_price and discount_rate numeric
                self.assertTrue(pd.api.types.is_numeric_dtype(df['base_price']), f"base_price not numeric in {fname}")
                self.assertTrue(pd.api.types.is_numeric_dtype(df['discount_rate']), f"discount_rate not numeric in {fname}")

    def test_08_adversarial_error_handling_corrupted_pdf(self):
        """Verify that PDFCatalogParser handles corrupted / empty files gracefully without unhandled crashes."""
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 empty corrupted file")
            corrupt_path = f.name
        try:
            parser = PDFCatalogParser(corrupt_path)
            df = parser.parse()
            self.assertIsInstance(df, pd.DataFrame)
            self.assertEqual(len(df), 0)
            self.assertEqual(list(df.columns), EXPECTED_SCHEMA)
            self.assertIsNotNone(parser.last_error)
        finally:
            if os.path.exists(corrupt_path):
                os.remove(corrupt_path)


if __name__ == "__main__":
    unittest.main()
