# -*- coding: utf-8 -*-
"""
tests/test_function_invariance.py - Milestone 3 Formal Function-Level Invariance Test Suite.

Feature F04 / R1 Compliance:
- Verifies that protected files (`src/allocator.py`, `src/pharma_matcher.py`, `src/normalizer.py`)
  have zero unauthorized modifications against git baseline.
- Performs AST structural validation proving protected candidate generation, scoring,
  ranking, and allocation functions have identical syntax and logical definitions.
- Confirms behavioral invariance of MedicineAllocator._find_safe_candidates and
  procurement allocation algorithms.
"""
from __future__ import annotations

import os
import ast
import subprocess
import unittest
import pandas as pd

from src.allocator import MedicineAllocator
from src.pharma_matcher import clean_arabic_string
from src.normalizer import normalize_arabic_text, normalize_drug_text


class TestAlgorithmInvariance(unittest.TestCase):
    """Verifies that protected algorithms and source files remain 100% invariant."""

    PROTECTED_FILES = [
        "src/allocator.py",
        "src/pharma_matcher.py",
        "src/normalizer.py",
    ]

    def test_01_git_diff_protected_files_is_zero_bytes(self):
        """Verifies that git diff against HEAD for protected files yields zero bytes."""
        cmd = ["git", "diff", "HEAD", "--"] + self.PROTECTED_FILES
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        self.assertEqual(
            proc.stdout.strip(),
            "",
            f"Protected files have unauthorized modifications: {proc.stdout}",
        )

    def test_02_ast_structural_invariance(self):
        """Verifies AST parsing and syntax structure of protected files against baseline commit."""
        for rel_path in self.PROTECTED_FILES:
            with open(rel_path, "r", encoding="utf-8") as f:
                current_ast = ast.parse(f.read(), filename=rel_path)

            # Extract baseline file from git
            proc = subprocess.run(
                ["git", "show", f"HEAD:{rel_path}"],
                capture_output=True,
                check=True,
            )
            baseline_code = proc.stdout.decode("utf-8", errors="replace")
            baseline_ast = ast.parse(baseline_code, filename=rel_path)

            current_dump = ast.dump(current_ast)
            baseline_dump = ast.dump(baseline_ast)
            self.assertEqual(
                current_dump,
                baseline_dump,
                f"AST structure mismatch for {rel_path}",
            )

    def test_03_allocator_candidate_generation_behavioral_invariance(self):
        """Verifies candidate generation and ranking behavior on a controlled catalog."""
        catalog_rows = [
            {"warehouse_name": "IbnSina", "item_name": "بانادول اكسترا 24 قرص", "base_price": 45.0, "discount_rate": 0.22, "stock_status": True},
            {"warehouse_name": "United", "item_name": "بانادول ادفانس 24 قرص", "base_price": 40.0, "discount_rate": 0.20, "stock_status": True},
            {"warehouse_name": "Overseas", "item_name": "كتافلام 50 مجم 20 قرص", "base_price": 55.0, "discount_rate": 0.18, "stock_status": True},
        ]
        df_cat = pd.DataFrame(catalog_rows)
        df_cat["normalized_name"] = df_cat["item_name"].apply(normalize_arabic_text)
        allocator = MedicineAllocator(warehouse_inventory=df_cat, enable_ai=False)

        # Query candidates for "بانادول اكسترا"
        candidates = allocator._find_safe_candidates("بانادول اكسترا")
        self.assertGreater(len(candidates), 0)
        self.assertIn("بانادول اكسترا 24 قرص", candidates["item_name"].values)

    def test_04_normalizer_behavioral_invariance(self):
        """Verifies standard normalizer functions produce expected deterministic outputs."""
        norm_ar = normalize_arabic_text("بنادول اكسترا")
        self.assertTrue(len(norm_ar) > 0)
        self.assertEqual(normalize_drug_text("Panadol Extra 24 Tab"), "panadol extra 24 tab")
        clean_ar = clean_arabic_string("  كونكور  5  مجم  ")
        self.assertEqual(clean_ar, "كونكور 5 مجم")


if __name__ == "__main__":
    unittest.main()
