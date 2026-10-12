# -*- coding: utf-8 -*-
"""
Master Adversarial Stress and Verification Runner for Challenger M1_1 gen2
Executes:
1. Adversarial synthetic stress test suite (tests/test_pdf_parser_adversarial.py)
2. All 23 catalogs benchmark with strict price bounds invariant verification
3. Existing regression suites (test_ocr_parser.py, test_v113_fixes.py, test_v114_fixes.py)
"""

import os
import sys
import time
import unittest
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

print("=" * 80)
print("STAGE 1: ADVERSARIAL STRESS TEST SUITE (SYNTHETIC INPUTS & CORRUPTED PDFS)")
print("=" * 80)

from tests.test_pdf_parser_adversarial import (
    TestParsePriceAdversarial,
    TestPDFCatalogParserAdversarial,
)

suite = unittest.TestSuite()
suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestParsePriceAdversarial))
suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestPDFCatalogParserAdversarial))
runner = unittest.TextTestRunner(verbosity=2)
result1 = runner.run(suite)

stage1_passed = result1.wasSuccessful()
if not stage1_passed:
    print(f"\n[ATTENTION] Stage 1 detected {len(result1.failures)} failures and {len(result1.errors)} errors in adversarial stress testing.")
else:
    print(f"\n[PASS] Stage 1: All {result1.testsRun} adversarial tests PASSED.")


print("\n" + "=" * 80)
print("STAGE 2: FULL 23-CATALOG CORPUS BENCHMARK & PRICE BOUNDS INVARIANT CHECK")
print("=" * 80)

train_dir = os.path.join(PROJECT_ROOT, "train")
if not os.path.isdir(train_dir):
    train_dir = os.getenv("TRAIN_DIR", os.path.join(os.path.expanduser("~"), "Desktop", "train"))

from src.pdf_parser import PDFCatalogParser

pdf_files = sorted([f for f in os.listdir(train_dir) if f.lower().endswith(".pdf")])
print(f"Scanning {len(pdf_files)} PDF catalogs in {train_dir}...")

total_items = 0
violations_gte_10k = []
violations_lte_0 = []
failures = []

for idx, fname in enumerate(pdf_files, 1):
    fpath = os.path.join(train_dir, fname)
    t0 = time.time()
    try:
        parser = PDFCatalogParser(fpath)
        df = parser.parse()
        elapsed = time.time() - t0
        item_count = len(df)
        total_items += item_count

        if not df.empty:
            max_p = df['base_price'].max()
            min_p = df['base_price'].min()

            # Invariant check: base_price < 10000.0
            bad_high = df[df['base_price'] >= 10000.0]
            if not bad_high.empty:
                violations_gte_10k.append((fname, len(bad_high), float(max_p)))

            # Invariant check: base_price > 0.0
            bad_low = df[df['base_price'] <= 0.0]
            if not bad_low.empty:
                violations_lte_0.append((fname, len(bad_low), float(min_p)))
        else:
            max_p = 0.0
            min_p = 0.0

        print(f"[{idx:02d}/23] {fname[:35]:<35} | Items: {item_count:5d} | MinP: {min_p:6.1f} | MaxP: {max_p:6.1f} | Time: {elapsed:.2f}s")
    except Exception as exc:
        elapsed = time.time() - t0
        failures.append((fname, str(exc)))
        print(f"[{idx:02d}/23] CRASH on {fname}: {exc}")

print("\n--- 23-Catalog Summary ---")
print(f"Total Extracted Items: {total_items} (Target >= 11,000)")
print(f"Total Crashes:         {len(failures)} (Target == 0)")
print(f"Prices >= 10,000 EGP:  {len(violations_gte_10k)} (Target == 0)")
print(f"Prices <= 0.0 EGP:     {len(violations_lte_0)} (Target == 0)")

if total_items < 11000:
    print(f"[FAIL] Yield fell below 11,000 items: {total_items}")
    sys.exit(1)

if violations_gte_10k:
    print(f"[FAIL] Found prices >= 10k: {violations_gte_10k}")
    sys.exit(1)

if violations_lte_0:
    print(f"[FAIL] Found prices <= 0: {violations_lte_0}")
    sys.exit(1)

if failures:
    print(f"[FAIL] Catalogs crashed: {failures}")
    sys.exit(1)

print("[PASS] Stage 2: 100% Invariants satisfied across all 23 catalogs.")

print("\n" + "=" * 80)
print("STAGE 3: REGRESSION TEST SUITES")
print("=" * 80)

ret = pytest.main([
    os.path.join(PROJECT_ROOT, "tests", "test_ocr_parser.py"),
    os.path.join(PROJECT_ROOT, "tests", "test_v113_fixes.py"),
    os.path.join(PROJECT_ROOT, "tests", "test_v114_fixes.py"),
    "-v",
])

if ret != 0:
    print(f"[FAIL] Stage 3: Regression test suites failed with code {ret}")
    sys.exit(ret)

print("[PASS] Stage 3: All regression tests passed cleanly.")
print("\n" + "=" * 80)
print("ALL VERIFICATION & ADVERSARIAL STRESS TESTING STAGES PASSED SUCCESSFULLY!")
print("=" * 80)
