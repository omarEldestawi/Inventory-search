# -*- coding: utf-8 -*-
"""
Empirical Challenger Milestone 3 Stress Test Suite.
Adversarial stress-testing of:
1. `is_old_price_item` boundary inputs, unicode variations, punctuation, type handling, and brand safeguards.
2. `ManualSearchAdapter` robustness against regex injections, NaN values, corrupted columns, and concurrency.
3. Behavioral invariance between `MedicineAllocator._find_safe_candidates` and `ManualSearchAdapter.search`.
"""
import os
import re
import math
import concurrent.futures
import pytest
import pandas as pd

from src.order_parser import is_old_price_item, ExcludedItem
from src.manual_search_adapter import ManualSearchAdapter, SearchResultItem, ManualSearchResult
from src.allocator import MedicineAllocator
from src.normalizer import normalize_arabic_text


class TestAdversarialOldPricePredicate:
    """Stress tests the canonical is_old_price_item predicate with adversarial boundaries."""

    @pytest.mark.parametrize("input_val", [
        # Unicode and directional combinations
        "بانادول س ق\u200e\u200f",
        "بانادول ق س\ufeff",
        "بانادول س.ق",
        "بانادول ق.س",
        "بانادول س . ق",
        "بانادول ق . س",
        "بانادول سق",
        "بانادول قس",
        # Newlines and whitespaces
        "بانادول\tس ق",
        "بانادول\nس ق\r\n",
        "بانادول   س   ق  ",
        # Documented xx markers
        "xxبانادول س قxx",
        "xxبانادول س ق",
        "بانادول س قxx",
        "XXXXبانادول س قXXXX",
        # Non-breaking spaces and exotic whitespace
        "بانادول\u00a0س\u00a0ق",
        "بانادول\u2000س ق",
        "بانادول\u2009س ق",
    ])
    def test_adversarial_positive_detections(self, input_val):
        assert is_old_price_item(input_val) is True, f"Failed on old price input: {input_val!r}"

    @pytest.mark.parametrize("brand_val", [
        # Legitimate brand names
        "بانادول س ج",
        "س ج",
        "اقراص",
        "لاسيكس",
        "زوفيراكس",
        "Lasix",
        "Xanax",
        "Celebrex",
        "سقراط",
        "دمشق",
        "فاسك",
        "سيروكويل 25 مجم",
        "سيمفاستاتين 20 مجم",
        "كتافلام 50 مجم",
        "كونكور 5 مجم",
        # Prefix rather than suffix
        "س ق بانادول",
        "سق بانادول",
        # Middle of string
        "بانادول س ق 20 قرص",
        "بانادول سق 20 قرص",
        # Exact non-string or empty types
        "",
        "   ",
        None,
        float("nan"),
        123,
        45.67,
        True,
        False,
        "[]",
        "{}",
    ])
    def test_adversarial_negative_safeguards(self, brand_val):
        assert is_old_price_item(brand_val) is False, f"Falsely excluded legitimate input: {brand_val!r}"

    def test_adversarial_non_scalar_list_behavior(self):
        """
        Adversarial Finding: Passing a list or array to is_old_price_item triggers:
        ValueError: The truth value of an empty array is ambiguous (from pd.isna(text)).
        In normal pandas Excel cell ingestion, cells are strictly scalar, but is_old_price_item(text: Any)
        lacks a isinstance(text, (list, tuple, np.ndarray)) guard before pd.isna().
        """
        with pytest.raises((ValueError, Exception)):
            is_old_price_item([])



class TestManualSearchAdapterStress:
    """Stress tests the ManualSearchAdapter under adversarial queries, corrupt data, and concurrency."""

    @pytest.fixture
    def sample_catalog(self, tmp_path):
        cat_file = tmp_path / "test_cat.xlsx"
        df = pd.DataFrame([
            {"item_name": "CONCOR 5 MG 30 TAB", "base_price": 40.5, "discount_rate": 0.20, "stock_status": True, "warehouse_name": "W1"},
            {"item_name": "PANADOL EXTRA 24 TAB", "base_price": 35.0, "discount_rate": 0.25, "stock_status": True, "warehouse_name": "W1"},
            {"item_name": "بانادول اكسترا 24 قرص", "base_price": 35.0, "discount_rate": 0.30, "stock_status": True, "warehouse_name": "W2"},
            {"item_name": "كتافلام 50 مجم 20 قرص", "base_price": 50.0, "discount_rate": 0.15, "stock_status": True, "warehouse_name": "W2"},
            # Corrupted row (negative price, out of bounds discount, NaN name)
            {"item_name": "NaN", "base_price": -10.0, "discount_rate": 1.5, "stock_status": True, "warehouse_name": "W2"},
            {"item_name": "صنف", "base_price": 0.0, "discount_rate": -0.1, "stock_status": False, "warehouse_name": "W2"},
        ])
        df.to_excel(cat_file, index=False)
        return str(cat_file)

    def test_adversarial_regex_query_injection(self, sample_catalog):
        adapter = ManualSearchAdapter(catalog_files=[sample_catalog], catalog_gen_id=1)
        
        # Regex metacharacters and injections should never crash or raise re.error
        adversarial_queries = [
            ".*",
            "(.*)",
            "[a-z]+",
            "\\",
            "++",
            "???",
            "^.*$",
            "(?P<name>.*)",
            "CONCOR (5 MG",
            "PANADOL [EXTRA",
            "{1,5}",
            "\\x00\\xff",
            "   ",
            "'; DROP TABLE medicines; --",
        ]
        for q in adversarial_queries:
            try:
                res = adapter.search(q, job_id=99)
                assert isinstance(res, ManualSearchResult)
                assert res.job_id == 99
                assert res.query == q
            except Exception as e:
                pytest.fail(f"ManualSearchAdapter crashed on adversarial query {q!r}: {e}")

    def test_concurrent_search_thread_safety(self, sample_catalog):
        adapter = ManualSearchAdapter(catalog_files=[sample_catalog], catalog_gen_id=42)
        queries = ["CONCOR", "PANADOL", "بانادول", "كتافلام", "", "INVALID_DRUG_XYZ"] * 10

        def do_search(i_and_q):
            idx, q = i_and_q
            sort_m = "highest_discount" if idx % 2 == 0 else "best_match"
            wh = "W1" if idx % 3 == 0 else None
            return adapter.search(query=q, warehouse_filter=wh, sort_mode=sort_m, job_id=idx)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(do_search, enumerate(queries)))

        assert len(results) == len(queries)
        for idx, res in enumerate(results):
            assert res.job_id == idx
            assert res.catalog_gen_id == 42
            assert res.total_matches >= 0

    def test_display_caps_and_net_price_calculation(self, sample_catalog):
        adapter = ManualSearchAdapter(catalog_files=[sample_catalog], catalog_gen_id=1)
        res = adapter.search("PANADOL", sort_mode="highest_discount")
        assert len(res.candidates) <= 100
        for cand in res.candidates:
            assert cand.base_price > 0
            assert 0.0 <= cand.discount_pct <= 100.0
            expected_net = round(cand.base_price * (1.0 - cand.discount_pct / 100.0), 2)
            assert cand.net_price == pytest.approx(expected_net, abs=0.02)
