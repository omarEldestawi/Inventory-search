# -*- coding: utf-8 -*-
"""
Empirical Challenger Verification Suite for Milestone M2:
Manual Search Adapter, Ordering Invariance, Concurrency & Safeguards.
Author: challenger_m2_1
"""
import os
import sys
import tempfile
import threading
import concurrent.futures
import pytest
import pandas as pd
import numpy as np

from src.manual_search_adapter import ManualSearchAdapter, SearchResultItem, ManualSearchResult
from src.manual_search_adapter import ManualSearchAdapter, SearchResultItem, ManualSearchResult
from src.allocator import MedicineAllocator
from src.controller import global_catalog_cache
from src.catalog_diagnostics import CatalogResult, FileFingerprint, ImportDiagnostics, PageDiagnostics, GroupDiagnostics, RowDiagnostic, ReviewIssue


def create_cached_catalog(path: str, df: pd.DataFrame, diagnostics=None, review_issues=None) -> str:
    norm_path = os.path.normpath(os.path.abspath(path))
    df.to_excel(norm_path, index=False)
    fp = FileFingerprint.from_path(norm_path)
    res = CatalogResult(
        dataframe=df,
        diagnostics=diagnostics or ImportDiagnostics(),
        fingerprint=fp,
        review_issues=review_issues or [],
    )
    global_catalog_cache.set(norm_path, res.to_dataframe(), force=True)
    return norm_path


@pytest.fixture
def sample_catalog_fixture(tmp_path):
    """Creates a temporary multi-warehouse Excel catalog fixture with known items."""
    path1 = str(tmp_path / "warehouse_united.xlsx")
    df1 = pd.DataFrame({
        "item_name": [
            "بانادول اكسترا 500 مجم اقراص",
            "كونجستال 24 قرص",
            "اوميبرازول 20 مجم كبسول",
            "كتافلام 50 مجم اقراص",
        ],
        "base_price": [50.0, 30.0, 40.0, 60.0],
        "discount_rate": [0.15, 0.10, 0.25, 0.05],
        "stock_status": [True, True, True, True],
        "warehouse_name": ["المتحدة", "المتحدة", "المتحدة", "المتحدة"],
    })
    create_cached_catalog(path1, df1)

    path2 = str(tmp_path / "warehouse_ibnsina.xlsx")
    df2 = pd.DataFrame({
        "item_name": [
            "بانادول اكسترا 500 مجم اقراص",
            "كونجستال 24 قرص",
            "اموكسيل 500 مجم كبسول",
            "كتافلام 50 مجم اقراص",
        ],
        "base_price": [50.0, 30.0, 35.0, 60.0],
        "discount_rate": [0.18, 0.15, 0.22, 0.08],
        "stock_status": [True, True, True, True],
        "warehouse_name": ["ابن سينا", "ابن سينا", "ابن سينا", "ابن سينا"],
    })
    create_cached_catalog(path2, df2)

    return [path1, path2]


@pytest.fixture
def synthetic_250_items_fixture(tmp_path):
    """Creates a temporary catalog with exactly 250 items matching 'بانادول'."""
    path = str(tmp_path / "large_catalog.xlsx")
    items = []
    base_prices = []
    discounts = []
    warehouses = []
    for i in range(1, 251):
        items.append(f"بانادول صنف {i:03d} 500 مجم اقراص")
        base_prices.append(20.0 + (i % 50))
        # Unique discounts from 0.01 up to 0.70
        discounts.append(round(0.01 + (i / 500.0), 4))
        warehouses.append("مخزن الأدوية العام")

    df = pd.DataFrame({
        "item_name": items,
        "base_price": base_prices,
        "discount_rate": discounts,
        "stock_status": [True] * 250,
        "warehouse_name": warehouses,
    })
    create_cached_catalog(path, df)
    return path


@pytest.fixture
def sample_avg_discounts_fixture(tmp_path):
    """Creates a sample average discounts reference Excel file."""
    path = str(tmp_path / "average_discounts.xlsx")
    df = pd.DataFrame({
        "اسم الصنف": [
            "بانادول اكسترا 500 مجم اقراص",
            "كونجستال 24 قرص",
            "كتافلام 50 مجم اقراص",
        ],
        "خصم مرجح": [0.165, 0.125, 0.070],
    })
    df.to_excel(path, index=False)
    return path


class TestCandidateRelevanceOrderingInvariance:
    """
    Empirically verify candidate relevance ordering invariance:
    Compare candidate ranking from MedicineAllocator._find_safe_candidates
    vs ManualSearchAdapter.search(query, sort_mode='best_match').
    """

    def test_relevance_ordering_verbatim_match(self, sample_catalog_fixture):
        adapter = ManualSearchAdapter(
            catalog_files=sample_catalog_fixture,
            catalog_gen_id=1
        )
        assert adapter._allocator is not None

        queries = [
            "بانادول اكسترا",
            "كونجستال",
            "كتافلام",
            "بانادول",
        ]

        for q in queries:
            expected_df = adapter._allocator._find_safe_candidates(q)
            res = adapter.search(q, sort_mode="best_match")

            # Number of candidates match (up to 100)
            expected_len = min(len(expected_df), 100)
            assert len(res.candidates) == expected_len, f"Candidate count mismatch for query '{q}'"
            assert res.total_matches == len(expected_df), f"total_matches mismatch for query '{q}'"

            # Exact verbatim sequence match: medicine name, warehouse, base price, discount
            for idx, candidate in enumerate(res.candidates):
                exp_row = expected_df.iloc[idx]
                assert candidate.medicine_name == str(exp_row["item_name"])
                assert candidate.warehouse_name == str(exp_row["warehouse_name"])
                assert abs(candidate.base_price - float(exp_row["base_price"])) < 1e-4
                assert abs(candidate.discount_pct - round(float(exp_row["discount_rate"]) * 100.0, 2)) < 1e-4

    def test_blank_query_browsing_ordering_invariance(self, sample_catalog_fixture):
        adapter = ManualSearchAdapter(catalog_files=sample_catalog_fixture, catalog_gen_id=1)
        res = adapter.search("", sort_mode="best_match")
        expected_df = adapter._allocator.valid_inv

        assert res.total_matches == len(expected_df)
        assert len(res.candidates) == min(len(expected_df), 100)

        for idx, candidate in enumerate(res.candidates):
            exp_row = expected_df.iloc[idx]
            assert candidate.medicine_name == str(exp_row["item_name"])
            assert candidate.warehouse_name == str(exp_row["warehouse_name"])


class TestHighestDiscountMode:
    """
    Empirically verify "Highest Discount" mode:
    Sort candidates by discount descending and verify candidate set
    matches "Best Match" candidate set.
    """

    def test_highest_discount_candidate_set_invariance(self, sample_catalog_fixture):
        adapter = ManualSearchAdapter(catalog_files=sample_catalog_fixture, catalog_gen_id=1)

        for q in ["بانادول", "كونجستال", "كتافلام", ""]:
            res_bm = adapter.search(q, sort_mode="best_match")
            res_hd = adapter.search(q, sort_mode="highest_discount")

            assert res_bm.total_matches == res_hd.total_matches

            # Candidate set invariance: same items present
            set_bm = {(c.medicine_name, c.warehouse_name, c.base_price, c.discount_pct) for c in res_bm.candidates}
            set_hd = {(c.medicine_name, c.warehouse_name, c.base_price, c.discount_pct) for c in res_hd.candidates}
            assert set_bm == set_hd, f"Candidate sets differ between Best Match and Highest Discount for query '{q}'"

            # Verify monotonic descending order in Highest Discount mode
            discounts = [c.discount_pct for c in res_hd.candidates]
            for i in range(len(discounts) - 1):
                assert discounts[i] >= discounts[i + 1], (
                    f"Highest discount ordering violated at index {i}: {discounts[i]} < {discounts[i+1]}"
                )


class TestWarehouseFilterEmpirical:
    """
    Empirically verify warehouse filter:
    Passing a specific warehouse name retains only items from that warehouse.
    """

    def test_filter_by_warehouse_name(self, sample_catalog_fixture):
        adapter = ManualSearchAdapter(catalog_files=sample_catalog_fixture, catalog_gen_id=1)

        # Unfiltered
        res_all = adapter.search("بانادول اكسترا", warehouse_filter=None)
        assert res_all.total_matches == 2
        whs_all = {c.warehouse_name for c in res_all.candidates}
        assert "المتحدة" in whs_all and "ابن سينا" in whs_all

        # Filter by "المتحدة"
        res_united = adapter.search("بانادول اكسترا", warehouse_filter="المتحدة")
        assert res_united.total_matches == 1
        for c in res_united.candidates:
            assert c.warehouse_name == "المتحدة", f"Item leaked from wrong warehouse: {c.warehouse_name}"

        # Filter by "ابن سينا"
        res_ibnsina = adapter.search("بانادول اكسترا", warehouse_filter="ابن سينا")
        assert res_ibnsina.total_matches == 1
        for c in res_ibnsina.candidates:
            assert c.warehouse_name == "ابن سينا", f"Item leaked from wrong warehouse: {c.warehouse_name}"

        # Sum of items across warehouses equals unfiltered matches
        assert res_united.total_matches + res_ibnsina.total_matches == res_all.total_matches

    def test_filter_nonexistent_warehouse(self, sample_catalog_fixture):
        adapter = ManualSearchAdapter(catalog_files=sample_catalog_fixture, catalog_gen_id=1)
        res = adapter.search("بانادول", warehouse_filter="مخزن غير موجود")
        assert res.total_matches == 0
        assert len(res.candidates) == 0


class TestHundredRowRenderCapEmpirical:
    """
    Empirically verify 100-row render cap:
    Create a synthetic catalog with 250 matching items and verify
    adapter returns exactly 100 items while reporting total_matches=250.
    """

    def test_render_cap_with_250_items(self, synthetic_250_items_fixture):
        adapter = ManualSearchAdapter(
            catalog_files=[synthetic_250_items_fixture],
            catalog_gen_id=1
        )

        # 1. Best Match mode
        res_bm = adapter.search("بانادول", sort_mode="best_match")
        assert res_bm.total_matches == 250, f"Expected total_matches=250, got {res_bm.total_matches}"
        assert len(res_bm.candidates) == 100, f"Expected capped len=100, got {len(res_bm.candidates)}"

        # 2. Highest Discount mode
        res_hd = adapter.search("بانادول", sort_mode="highest_discount")
        assert res_hd.total_matches == 250, f"Expected total_matches=250, got {res_hd.total_matches}"
        assert len(res_hd.candidates) == 100, f"Expected capped len=100, got {len(res_hd.candidates)}"

        # Verify that in Highest Discount mode, the 100 returned items are indeed the top 100 discounts
        all_discounts = sorted([
            round(0.01 + (i / 500.0), 4) * 100.0 for i in range(1, 251)
        ], reverse=True)
        expected_top_100_discounts = [round(d, 2) for d in all_discounts[:100]]
        actual_top_100_discounts = [c.discount_pct for c in res_hd.candidates]

        assert actual_top_100_discounts == expected_top_100_discounts, "Top 100 highest discounts mismatch"


class TestReferenceBenchmarkIsolationEmpirical:
    """
    Empirically verify reference benchmark card:
    Verify that reference average discount matches _lookup_ref_discount
    and is isolated from purchasable items.
    """

    def test_benchmark_matches_and_isolated(self, sample_catalog_fixture, sample_avg_discounts_fixture):
        adapter = ManualSearchAdapter(
            catalog_files=sample_catalog_fixture,
            catalog_gen_id=1,
            avg_discounts_path=sample_avg_discounts_fixture,
        )

        q = "بانادول اكسترا 500 مجم اقراص"
        res = adapter.search(q)

        # Reference benchmark is populated
        assert res.reference_benchmark is not None
        assert res.reference_benchmark["discount_pct"] == 16.5
        assert res.reference_benchmark["formatted_pct"] == "16.5%"

        # Crucial check: benchmark is NOT injected as a candidate row in candidates
        for c in res.candidates:
            # Candidate warehouse must be real supplier, not "مرجع استرشادي" or similar
            assert c.warehouse_name in ["المتحدة", "ابن سينا"]
            assert c.discount_pct in [15.0, 18.0]

    def test_benchmark_missing_file_isolation(self, sample_catalog_fixture):
        adapter = ManualSearchAdapter(
            catalog_files=sample_catalog_fixture,
            catalog_gen_id=1,
            avg_discounts_path="nonexistent_avg_discounts.xlsx"
        )
        res = adapter.search("بانادول اكسترا")
        assert res.reference_benchmark is None
        assert res.total_matches > 0  # Search functions normally


class TestThreadSafetyConcurrentSearchEmpirical:
    """
    Empirically verify thread safety:
    Test 10 concurrent threads invoking ManualSearchAdapter.search simultaneously.
    """

    def test_concurrent_search_10_threads(self, sample_catalog_fixture):
        adapter = ManualSearchAdapter(catalog_files=sample_catalog_fixture, catalog_gen_id=1)
        queries = ["بانادول", "كونجستال", "كتافلام", "اوميبرازول", "اموكسيل", ""]
        sort_modes = ["best_match", "highest_discount"]
        wh_filters = [None, "المتحدة", "ابن سينا"]

        errors = []
        results = []

        def worker_task(thread_idx: int, iterations: int = 20):
            try:
                for it in range(iterations):
                    q = queries[(thread_idx + it) % len(queries)]
                    sm = sort_modes[(thread_idx + it) % len(sort_modes)]
                    wh = wh_filters[(thread_idx + it) % len(wh_filters)]

                    job_id = thread_idx * 1000 + it
                    res = adapter.search(query=q, warehouse_filter=wh, sort_mode=sm, job_id=job_id)

                    assert res.job_id == job_id
                    assert res.query == q
                    assert res.sort_mode == sm
                    assert res.warehouse_filter == wh
                    assert isinstance(res.candidates, list)
                    assert len(res.candidates) <= 100

                    # Verify internal fields validity
                    for c in res.candidates:
                        assert isinstance(c.medicine_name, str)
                        assert isinstance(c.warehouse_name, str)
                        assert c.base_price > 0.0
                        assert 0.0 <= c.discount_pct <= 85.0
                        if c.net_price is not None:
                            expected_net = round(c.base_price * (1.0 - c.discount_pct / 100.0), 2)
                            assert abs(c.net_price - expected_net) <= 0.01

                    results.append(len(res.candidates))
            except Exception as e:
                errors.append(f"Thread {thread_idx} failed: {e}")

        threads = []
        for t_idx in range(10):
            t = threading.Thread(target=worker_task, args=(t_idx, 20))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=15.0)
            assert not t.is_alive(), "A worker thread deadlocked or timed out!"

        assert len(errors) == 0, f"Thread safety errors occurred: {errors}"
        assert len(results) == 200, f"Expected 200 completed queries across 10 threads, got {len(results)}"


class TestProcurementExclusionsEmpirical:
    """
    Empirically verify that rejected rows, unresolved review issues,
    out of stock rows, and invalid prices are strictly excluded from manual search.
    """

    def test_rejected_and_unresolved_rows_excluded(self, tmp_path):
        cat_path = str(tmp_path / "procurement_safety_catalog.xlsx")

        # 3 rows: 1 good, 1 rejected, 1 unresolved review issue
        df = pd.DataFrame({
            "source_id": ["p1_r1", "p1_r2", "p1_r3"],
            "item_name": [
                "كونجستال 24 قرص سليم",
                "كونجستال 24 قرص مرفوض",
                "كونجستال 24 قرص مراجع معلق",
            ],
            "base_price": [30.0, 30.0, 30.0],
            "discount_rate": [0.10, 0.10, 0.10],
            "stock_status": [True, True, True],
            "warehouse_name": ["مخزن الأمان", "مخزن الأمان", "مخزن الأمان"],
        })

        # Build CatalogResult with rejection & unresolved issue
        r_rej = RowDiagnostic(page=1, group=0, row=0, outcome="rejected", source_id="p1_r2")
        grp = GroupDiagnostics(group=0, strategy="digital", rows=[r_rej])
        pg = PageDiagnostics(page=1, groups=[grp])
        diag = ImportDiagnostics(pages=[pg])

        issue = ReviewIssue(
            source_id="p1_r3",
            resolved=False,
            rejection_reason="uncertain_price"
        )

        create_cached_catalog(cat_path, df, diagnostics=diag, review_issues=[issue])

        adapter = ManualSearchAdapter(catalog_files=[cat_path], catalog_gen_id=1)
        res = adapter.search("كونجستال")

        # Only p1_r1 should survive
        candidate_names = [c.medicine_name for c in res.candidates]
        assert "كونجستال 24 قرص سليم" in candidate_names
        assert "كونجستال 24 قرص مرفوض" not in candidate_names
        assert "كونجستال 24 قرص مراجع معلق" not in candidate_names
        assert res.total_matches == 1
