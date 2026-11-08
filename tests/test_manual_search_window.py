# -*- coding: utf-8 -*-
"""
tests/test_manual_search_window.py - Comprehensive Milestone 2 Test Suite
Verifies:
1. Non-blocking CTkToplevel window launch & single instance reuse
2. 60 ms keystroke debounce timer behavior
3. Bounded worker queue (at most 1 active, 1 replaceable pending job)
4. Stale asynchronous result rejection via job_id and catalog_generation_id
5. Warehouse filtering and 100-row render cap
6. Best Match relevance order vs Highest Discount display sorting
7. Display field formatting and isolated reference benchmark card
8. Safe window teardown without Tkinter callback errors
9. Catalog lifecycle invalidation hooks and generation bumping
10. Active catalog resolution & procurement decoupling
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
from typing import Optional, List
import pandas as pd
import customtkinter as ctk

from app_gui import PharmaProcurementApp, FileItem, FileListModel
from src.manual_search_adapter import (
    ManualSearchAdapter,
    SearchResultItem,
    ManualSearchResult,
)
from src.manual_search_window import (
    ManualSearchWindow,
    SearchJob,
    SearchJobResult,
)
from src.controller import global_catalog_cache
from src.catalog_diagnostics import (
    CatalogResult,
    FileFingerprint,
    ImportDiagnostics,
    PageDiagnostics,
    GroupDiagnostics,
    RowDiagnostic,
    ReviewIssue,
)

_SHARED_APP: Optional[PharmaProcurementApp] = None


def get_shared_app() -> PharmaProcurementApp:
    global _SHARED_APP
    if _SHARED_APP is None:
        _SHARED_APP = PharmaProcurementApp()
        _SHARED_APP.withdraw()
    return _SHARED_APP


def create_test_catalog(
    df: pd.DataFrame,
    diagnostics: Optional[ImportDiagnostics] = None,
    review_issues: Optional[List[ReviewIssue]] = None,
) -> str:
    """Helper creating a real Excel file with verified FileFingerprint and caching it."""
    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    path = os.path.normpath(os.path.abspath(tmp.name))
    tmp.close()
    df.to_excel(path, index=False)
    fp = FileFingerprint.from_path(path)
    diag = diagnostics if diagnostics is not None else ImportDiagnostics()
    res = CatalogResult(
        dataframe=df,
        diagnostics=diag,
        fingerprint=fp,
        review_issues=review_issues or [],
    )
    global_catalog_cache.set(path, res.to_dataframe(), force=True)
    return path


class TestWindowLaunchAndReuse(unittest.TestCase):
    """Category 1: Non-blocking CTkToplevel window launch & single instance reuse."""

    def setUp(self):
        self.app = get_shared_app()
        if getattr(self.app, "_manual_search_window", None) is not None:
            try:
                self.app._manual_search_window._on_close()
            except Exception:
                pass
            self.app._manual_search_window = None

    def tearDown(self):
        if getattr(self.app, "_manual_search_window", None) is not None:
            try:
                self.app._manual_search_window._on_close()
            except Exception:
                pass
            self.app._manual_search_window = None

    def test_01_toolbar_launcher_opens_window(self):
        self.assertIn("بحث يدوي", self.app.manual_search_btn.cget("text"))
        win = self.app._open_manual_search_window()
        self.assertIsNotNone(win)
        self.assertIsInstance(win, ManualSearchWindow)
        self.assertIs(self.app._manual_search_window, win)

    def test_02_sidebar_launcher_opens_window(self):
        self.assertIn("بحث يدوي", self.app.sidebar_search_btn.cget("text"))
        win = self.app._open_manual_search_window()
        self.assertIsNotNone(win)
        self.assertIsInstance(win, ManualSearchWindow)

    def test_03_single_instance_reuse_on_repeated_clicks(self):
        win1 = self.app._open_manual_search_window()
        win2 = self.app._open_manual_search_window()
        self.assertIs(win1, win2)

    def test_04_window_is_non_modal(self):
        win = self.app._open_manual_search_window()
        self.assertIsNone(win.grab_status())

    def test_05_window_close_resets_parent_reference(self):
        win = self.app._open_manual_search_window()
        self.assertIsNotNone(self.app._manual_search_window)
        win._on_close()
        self.assertIsNone(self.app._manual_search_window)


class TestDebounceBehavior(unittest.TestCase):
    """Category 2: 60 ms keystroke debounce timer behavior."""

    def setUp(self):
        self.app = get_shared_app()
        self.win = self.app._open_manual_search_window()

    def tearDown(self):
        if self.win is not None:
            try:
                self.win._on_close()
            except Exception:
                pass
            self.win = None

    def test_01_keystroke_schedules_60ms_timer(self):
        self.win._debounce_timer = None
        self.win._search_var.set("Panadol")
        self.assertIsNotNone(self.win._debounce_timer)

    def test_02_rapid_keystrokes_cancel_prior_timers(self):
        self.win._search_var.set("C")
        t1 = self.win._debounce_timer
        self.win._search_var.set("Ca")
        t2 = self.win._debounce_timer
        self.assertNotEqual(t1, t2)
        self.win._search_var.set("Cat")
        t3 = self.win._debounce_timer
        self.assertNotEqual(t2, t3)

    def test_03_debounce_timer_fires_on_gui_thread(self):
        job_id_before = self.win._latest_job_id
        self.win._search_var.set("Aspirin")
        self.win._on_debounced_query()
        self.assertGreater(self.win._latest_job_id, job_id_before)


class TestBoundedQueueAndWorker(unittest.TestCase):
    """Category 3: Bounded worker queue (at most 1 active, 1 replaceable pending job)."""

    def setUp(self):
        self.app = get_shared_app()
        self.win = self.app._open_manual_search_window()

    def tearDown(self):
        if self.win is not None:
            try:
                self.win._on_close()
            except Exception:
                pass
            self.win = None

    def test_01_bounded_queue_at_most_one_active_one_pending(self):
        self.win._trigger_search("query1")
        self.win._trigger_search("query2")
        self.win._trigger_search("query3")
        self.assertLessEqual(self.win._job_queue.qsize(), 1)

    def test_02_burst_input_no_backlog(self):
        for i in range(25):
            self.win._trigger_search(f"burst_query_{i}")
        self.assertLessEqual(self.win._job_queue.qsize(), 1)

    def test_03_worker_thread_stops_cleanly(self):
        self.assertTrue(self.win._worker_thread.is_alive())
        self.win._on_close()
        self.win._worker_thread.join(timeout=1.0)
        self.assertFalse(self.win._worker_thread.is_alive())
        self.win = None


class TestStaleResultRejection(unittest.TestCase):
    """Category 4: Stale asynchronous result rejection via job_id and catalog_generation_id."""

    def setUp(self):
        self.app = get_shared_app()
        self.win = self.app._open_manual_search_window()

    def tearDown(self):
        if self.win is not None:
            try:
                self.win._on_close()
            except Exception:
                pass
            self.win = None

    def test_01_stale_job_id_discarded(self):
        self.win._latest_job_id = 10
        self.win._catalog_generation_id = 1
        stale_res = SearchJobResult(
            job_id=8,
            catalog_generation_id=1,
            query="old",
            warehouse_filter=None,
            sort_mode="best_match",
            candidates=[],
            reference_benchmark=None,
            total_matches=0,
            catalog_errors=[],
        )
        self.win._result_queue.put(stale_res)
        with patch.object(self.win, "_render_search_results") as mock_render:
            self.win._poll_result_queue()
            mock_render.assert_not_called()

    def test_02_stale_catalog_generation_discarded(self):
        self.win._latest_job_id = 10
        self.win._catalog_generation_id = 4
        stale_gen_res = SearchJobResult(
            job_id=10,
            catalog_generation_id=2,
            query="old_gen",
            warehouse_filter=None,
            sort_mode="best_match",
            candidates=[],
            reference_benchmark=None,
            total_matches=0,
            catalog_errors=[],
        )
        self.win._result_queue.put(stale_gen_res)
        with patch.object(self.win, "_render_search_results") as mock_render:
            self.win._poll_result_queue()
            mock_render.assert_not_called()

    def test_03_current_result_updates_view(self):
        self.win._latest_job_id = 15
        self.win._catalog_generation_id = 3
        valid_res = SearchJobResult(
            job_id=15,
            catalog_generation_id=3,
            query="fresh",
            warehouse_filter=None,
            sort_mode="best_match",
            candidates=[],
            reference_benchmark=None,
            total_matches=0,
            catalog_errors=[],
        )
        self.win._result_queue.put(valid_res)
        with patch.object(self.win, "_render_search_results") as mock_render:
            self.win._poll_result_queue()
            mock_render.assert_called_once_with(valid_res)


class TestWarehouseFilteringAndRenderCap(unittest.TestCase):
    """Category 5: Warehouse filtering and 100-row render cap."""

    @classmethod
    def setUpClass(cls):
        rows = []
        for i in range(150):
            rows.append({
                "warehouse_name": "Warehouse Alpha",
                "item_name": "Panadol Extra Tab",
                "base_price": 40.0 + (i % 10),
                "discount_rate": 0.15 + (i % 20) * 0.01,
                "stock_status": True,
            })
        for j in range(100):
            rows.append({
                "warehouse_name": "Warehouse Beta",
                "item_name": "Panadol Extra Tab",
                "base_price": 50.0 + (j % 10),
                "discount_rate": 0.20 + (j % 15) * 0.01,
                "stock_status": True,
            })
        cls.df = pd.DataFrame(rows)
        cls.cat_path = create_test_catalog(cls.df)

    @classmethod
    def tearDownClass(cls):
        global_catalog_cache.remove(cls.cat_path)
        try:
            os.remove(cls.cat_path)
        except OSError:
            pass

    def test_01_warehouse_filter_all(self):
        adapter = ManualSearchAdapter([self.cat_path])
        res = adapter.search("", warehouse_filter="الكل / All")
        self.assertEqual(res.total_matches, 250)
        self.assertEqual(len(res.candidates), 100)
        wh_set = {c.warehouse_name for c in res.candidates}
        self.assertIn("Warehouse Alpha", wh_set)

    def test_02_warehouse_filter_specific(self):
        adapter = ManualSearchAdapter([self.cat_path])
        res = adapter.search("", warehouse_filter="Warehouse Alpha")
        self.assertEqual(res.total_matches, 150)
        wh_set = {c.warehouse_name for c in res.candidates}
        self.assertEqual(wh_set, {"Warehouse Alpha"})

    def test_03_render_cap_100_rows_enforced(self):
        adapter = ManualSearchAdapter([self.cat_path])
        res = adapter.search("", warehouse_filter=None)
        self.assertEqual(res.total_matches, 250)
        self.assertEqual(len(res.candidates), 100)

    def test_04_render_cap_status_label(self):
        app = get_shared_app()
        win = app._open_manual_search_window()
        try:
            sample_candidates = [
                SearchResultItem("Med A", "Wh A", 10.0, 15.0, 8.5, None)
                for _ in range(100)
            ]
            job_res = SearchJobResult(
                job_id=1,
                catalog_generation_id=0,
                query="Panadol",
                warehouse_filter=None,
                sort_mode="best_match",
                candidates=sample_candidates,
                reference_benchmark=None,
                total_matches=250,
                catalog_errors=[],
            )
            win._render_search_results(job_res)
            self.assertIn("250", win.status_label.cget("text"))
            self.assertIn("100", win.status_label.cget("text"))
            self.assertEqual(len(win.tree.get_children()), 100)
        finally:
            win._on_close()


class TestRelevanceOrderVsHighestDiscount(unittest.TestCase):
    """Category 6: Best Match relevance order vs Highest Discount display sorting."""

    @classmethod
    def setUpClass(cls):
        rows = [
            {"warehouse_name": "WhA", "item_name": "Cataflam 50mg Tab", "base_price": 50.0, "discount_rate": 0.10, "stock_status": True},
            {"warehouse_name": "WhB", "item_name": "Cataflam 50mg Tab", "base_price": 50.0, "discount_rate": 0.35, "stock_status": True},
            {"warehouse_name": "WhC", "item_name": "Cataflam 50mg Tab", "base_price": 50.0, "discount_rate": 0.05, "stock_status": True},
            {"warehouse_name": "WhD", "item_name": "Cataflam 50mg Tab", "base_price": 50.0, "discount_rate": 0.20, "stock_status": True},
            {"warehouse_name": "WhE", "item_name": "Cataflam 50mg Tab", "base_price": 50.0, "discount_rate": 0.15, "stock_status": True},
        ]
        cls.df = pd.DataFrame(rows)
        cls.cat_path = create_test_catalog(cls.df)

    @classmethod
    def tearDownClass(cls):
        global_catalog_cache.remove(cls.cat_path)
        try:
            os.remove(cls.cat_path)
        except OSError:
            pass

    def test_01_best_match_preserves_allocator_order(self):
        adapter = ManualSearchAdapter([self.cat_path])
        res = adapter.search("Cataflam 50mg Tab", sort_mode="best_match")
        raw_cands = adapter._allocator._find_safe_candidates("Cataflam 50mg Tab")
        self.assertEqual(len(res.candidates), len(raw_cands))
        best_warehouses = [c.warehouse_name for c in res.candidates]
        raw_warehouses = list(raw_cands["warehouse_name"])
        self.assertEqual(best_warehouses, raw_warehouses)

    def test_02_highest_discount_sorts_already_matched_candidates(self):
        adapter = ManualSearchAdapter([self.cat_path])
        res = adapter.search("Cataflam 50mg Tab", sort_mode="highest_discount")
        discounts = [c.discount_pct for c in res.candidates]
        self.assertEqual(len(discounts), 5)
        self.assertEqual(discounts, sorted(discounts, reverse=True))
        self.assertEqual(discounts[0], 35.0)
        self.assertEqual(discounts[-1], 5.0)

    def test_03_identical_candidate_set(self):
        adapter = ManualSearchAdapter([self.cat_path])
        res_best = adapter.search("Cataflam 50mg Tab", sort_mode="best_match")
        res_disc = adapter.search("Cataflam 50mg Tab", sort_mode="highest_discount")
        set_best = {c.warehouse_name for c in res_best.candidates}
        set_disc = {c.warehouse_name for c in res_disc.candidates}
        self.assertEqual(set_best, set_disc)


class TestDisplayContractsAndReferenceBenchmark(unittest.TestCase):
    """Category 7: Display field contracts & isolated reference benchmark card."""

    @classmethod
    def setUpClass(cls):
        rows = [
            {"warehouse_name": "Warehouse Alpha", "item_name": "Augmentin 1g Tab", "base_price": 100.0, "discount_rate": 0.20, "stock_status": True},
        ]
        cls.df = pd.DataFrame(rows)
        cls.cat_path = create_test_catalog(cls.df)

    @classmethod
    def tearDownClass(cls):
        global_catalog_cache.remove(cls.cat_path)
        try:
            os.remove(cls.cat_path)
        except OSError:
            pass

    def test_01_display_fields_formatting(self):
        adapter = ManualSearchAdapter([self.cat_path])
        res = adapter.search("Augmentin 1g Tab")
        self.assertEqual(len(res.candidates), 1)
        item = res.candidates[0]
        self.assertEqual(item.medicine_name, "Augmentin 1g Tab")
        self.assertEqual(item.warehouse_name, "Warehouse Alpha")
        self.assertEqual(item.base_price, 100.0)
        self.assertEqual(item.discount_pct, 20.0)
        self.assertEqual(item.net_price, 80.0)

    def test_02_reference_benchmark_card_isolated(self):
        adapter = ManualSearchAdapter([self.cat_path])
        with patch.object(adapter._allocator, "_lookup_ref_discount", return_value=0.225):
            res = adapter.search("Augmentin 1g Tab")
            self.assertIsNotNone(res.reference_benchmark)
            self.assertEqual(res.reference_benchmark["discount_pct"], 22.5)
            self.assertEqual(res.reference_benchmark["formatted_pct"], "22.5%")
            # Crucial: benchmark is never in candidate offers list
            self.assertEqual(len(res.candidates), 1)
            self.assertEqual(res.candidates[0].warehouse_name, "Warehouse Alpha")

        app = get_shared_app()
        win = app._open_manual_search_window()
        try:
            job_res = SearchJobResult(
                job_id=1,
                catalog_generation_id=0,
                query="Augmentin 1g Tab",
                warehouse_filter=None,
                sort_mode="best_match",
                candidates=res.candidates,
                reference_benchmark=res.reference_benchmark,
                total_matches=1,
                catalog_errors=[],
            )
            win._render_search_results(job_res)
            self.assertIn("22.5%", win.benchmark_label.cget("text"))
            self.assertEqual(len(win.tree.get_children()), 1)
        finally:
            win._on_close()

    def test_03_missing_reference_does_not_crash(self):
        adapter = ManualSearchAdapter([self.cat_path], avg_discounts_path="non_existent_ref.xlsx")
        res = adapter.search("Augmentin 1g Tab")
        self.assertIsNotNone(res)
        self.assertEqual(len(res.candidates), 1)


class TestSafeTeardownAndTkinterSafety(unittest.TestCase):
    """Category 8: Safe window teardown without Tkinter callback errors."""

    def setUp(self):
        self.app = get_shared_app()
        self.win = self.app._open_manual_search_window()

    def test_01_close_cancels_debounce_timer(self):
        self.win._search_var.set("Brufen")
        self.assertIsNotNone(self.win._debounce_timer)
        self.win._on_close()
        self.assertIsNone(self.win._debounce_timer)
        self.win = None

    def test_02_close_cancels_poller_timer(self):
        self.assertIsNotNone(self.win._poll_timer)
        self.win._on_close()
        self.assertIsNone(self.win._poll_timer)
        self.win = None

    def test_03_no_tcl_error_on_destroyed_widgets(self):
        self.win._on_close()
        try:
            self.win._poll_result_queue()
        except Exception as e:
            self.fail(f"_poll_result_queue raised on closed window: {e}")
        self.win = None

    def test_close_returns_while_catalog_loading_is_in_progress(self):
        self.win._on_close()
        started = threading.Event()
        release = threading.Event()

        def load_catalogs(**kwargs):
            started.set()
            release.wait(timeout=5)
            raise RuntimeError("Test catalog load ended")

        with patch("src.manual_search_window.ManualSearchAdapter", side_effect=load_catalogs):
            self.win = self.app._open_manual_search_window()
            try:
                self.assertTrue(started.wait(timeout=2))
                before = time.perf_counter()
                self.win._on_close()
                self.assertLess(time.perf_counter() - before, 0.2)
                self.assertTrue(self.win._worker_thread.is_alive())
            finally:
                release.set()
                self.win._worker_thread.join(timeout=2)
                if not self.win._cancelled:
                    self.win._on_close()
            self.assertFalse(self.win._worker_thread.is_alive())

    def test_partial_warning_persists_until_a_successful_result(self):
        result = SearchJobResult(
            job_id=1,
            catalog_generation_id=0,
            query="Panadol",
            warehouse_filter=None,
            sort_mode="best_match",
            candidates=[],
            reference_benchmark=None,
            total_matches=0,
            catalog_errors=["Catalog unavailable"],
        )
        try:
            self.win._render_search_results(result)
            warning = self.win.error_label.cget("text")
            self.assertTrue(warning)
            self.win._render_search_results(result)
            self.assertEqual(self.win.error_label.cget("text"), warning)
            result.catalog_errors = []
            self.win._render_search_results(result)
            self.assertEqual(self.win.error_label.cget("text"), "")
        finally:
            self.win._on_close()


class TestCatalogLifecycleInvalidation(unittest.TestCase):
    """Category 9: Catalog lifecycle invalidation hooks and generation bumping."""

    def setUp(self):
        self.app = get_shared_app()

    def test_refresh_rebuilds_the_catalog_adapter(self):
        def make_adapter(*, catalog_files, catalog_gen_id, avg_discounts_path):
            adapter = MagicMock()
            adapter.search.side_effect = lambda **kwargs: ManualSearchResult(
                catalog_gen_id=catalog_gen_id,
                candidates=[],
                reference_benchmark=None,
                total_matches=0,
                catalog_errors=[],
                **kwargs,
            )
            return adapter

        with patch("src.manual_search_window.ManualSearchAdapter", side_effect=make_adapter) as build:
            win = self.app._open_manual_search_window()
            try:
                win._result_queue.get(timeout=2)
                win._trigger_search("Panadol")
                self.assertEqual(win._result_queue.get(timeout=2).query, "Panadol")
                self.assertEqual(build.call_count, 1)
                win.refresh_btn.invoke()
                win._result_queue.get(timeout=2)
                self.assertEqual(build.call_count, 2)
            finally:
                win._on_close()

    def test_01_generation_id_increments_on_add_files(self):
        gen0 = self.app._catalog_generation_id
        with patch.object(self.app.file_model, "add_paths", return_value=(1, [])):
            self.app.add_files(["dummy.xlsx"])
        self.assertEqual(self.app._catalog_generation_id, gen0 + 1)

    def test_02_generation_id_increments_on_remove_file(self):
        gen0 = self.app._catalog_generation_id
        self.app._on_remove_file("dummy.xlsx")
        self.assertEqual(self.app._catalog_generation_id, gen0 + 1)

    def test_03_generation_id_increments_on_clear_all(self):
        gen0 = self.app._catalog_generation_id
        self.app._on_clear_all()
        self.assertEqual(self.app._catalog_generation_id, gen0 + 1)

    def test_04_generation_id_increments_on_refresh_catalog(self):
        gen0 = self.app._catalog_generation_id
        with patch.object(self.app, "_async_inspect_counts"):
            self.app._on_refresh_catalog("dummy.xlsx")
        self.assertEqual(self.app._catalog_generation_id, gen0 + 1)

    def test_05_generation_id_increments_on_replace_catalog(self):
        gen0 = self.app._catalog_generation_id
        with patch.object(self.app, "_async_inspect_counts"):
            self.app._replace_catalog_file("old_cat.xlsx", "new_cat.xlsx")
        self.assertEqual(self.app._catalog_generation_id, gen0 + 1)

    def test_06_generation_id_increments_on_review_done(self):
        gen0 = self.app._catalog_generation_id
        win = self.app._show_catalog_review_window("dummy.xlsx")
        try:
            mock_res = MagicMock()
            mock_res.dataframe = pd.DataFrame()
            mock_res.diagnostics.status = "VALID"
            mock_res.diagnostics.summary.return_value = "OK"
            win.on_done_callback(mock_res)
            self.assertEqual(self.app._catalog_generation_id, gen0 + 1)
        finally:
            try:
                win.destroy()
            except Exception:
                pass

    def test_07_generation_id_increments_on_override_category(self):
        gen0 = self.app._catalog_generation_id
        self.app._on_override_category("dummy.xlsx", "كتالوج مخزن (Catalog)")
        self.assertEqual(self.app._catalog_generation_id, gen0 + 1)

    def test_08_window_notified_on_generation_bump(self):
        win = self.app._open_manual_search_window()
        try:
            with patch.object(win, "notify_catalogs_changed") as mock_notify:
                self.app._bump_catalog_generation()
                mock_notify.assert_called_once_with(self.app._catalog_generation_id)
        finally:
            win._on_close()


class TestActiveCatalogResolutionAndProcurementDecoupling(unittest.TestCase):
    """Category 10: Active catalog resolution & procurement decoupling."""

    @classmethod
    def setUpClass(cls):
        cls.active_df = pd.DataFrame([
            {"warehouse_name": "ActiveWh", "item_name": "Antinal 200mg Cap", "base_price": 30.0, "discount_rate": 0.15, "stock_status": True},
        ])
        cls.active_path = create_test_catalog(cls.active_df)

        cls.inactive_df = pd.DataFrame([
            {"warehouse_name": "InactiveWh", "item_name": "Inactive Med 500mg", "base_price": 50.0, "discount_rate": 0.25, "stock_status": True},
        ])
        cls.inactive_path = create_test_catalog(cls.inactive_df)

    @classmethod
    def tearDownClass(cls):
        global_catalog_cache.remove(cls.active_path)
        global_catalog_cache.remove(cls.inactive_path)
        for p in (cls.active_path, cls.inactive_path):
            try:
                os.remove(p)
            except OSError:
                pass

    def test_01_search_strictly_resolves_against_active_catalogs(self):
        adapter = ManualSearchAdapter([self.active_path])
        res = adapter.search("Inactive Med 500mg")
        self.assertEqual(len(res.candidates), 0)
        res_antinal = adapter.search("Antinal 200mg Cap")
        self.assertEqual(len(res_antinal.candidates), 1)
        self.assertEqual(res_antinal.candidates[0].warehouse_name, "ActiveWh")

    def test_02_opening_and_searching_never_touches_acknowledged_token(self):
        app = get_shared_app()
        fi = FileItem(self.active_path, "Catalog")
        fi.acknowledged_token = None
        app.file_model.files = [fi]

        win = app._open_manual_search_window()
        try:
            win._trigger_search("Antinal 200mg Cap")
            self.assertIsNone(fi.acknowledged_token)
        finally:
            win._on_close()
        self.assertIsNone(fi.acknowledged_token)

    def test_03_unresolved_review_issues_excluded(self):
        df_iss = pd.DataFrame([
            {"source_id": "sid_good", "warehouse_name": "WhA", "item_name": "Amoxil 500mg Cap", "base_price": 35.0, "discount_rate": 0.12, "stock_status": True},
            {"source_id": "sid_iss", "warehouse_name": "WhA", "item_name": "Flagyl 500mg Tab", "base_price": 25.0, "discount_rate": 0.10, "stock_status": True},
        ])
        iss = ReviewIssue(source_id="sid_iss", resolved=False)
        tpath = create_test_catalog(df_iss, review_issues=[iss])
        try:
            adapter = ManualSearchAdapter([tpath])
            cands = adapter.search("").candidates
            names = [c.medicine_name for c in cands]
            self.assertIn("Amoxil 500mg Cap", names)
            self.assertNotIn("Flagyl 500mg Tab", names)
        finally:
            global_catalog_cache.remove(tpath)
            try:
                os.remove(tpath)
            except OSError:
                pass

    def test_04_rejected_rows_excluded(self):
        df_rej = pd.DataFrame([
            {"source_id": "sid_good", "warehouse_name": "WhA", "item_name": "Amoxil 500mg Cap", "base_price": 20.0, "discount_rate": 0.10, "stock_status": True},
            {"source_id": "sid_rej", "warehouse_name": "WhA", "item_name": "Bad Med 500mg Cap", "base_price": 20.0, "discount_rate": 0.10, "stock_status": True},
        ])
        r_rej = RowDiagnostic(page=1, group=0, row=0, outcome="rejected", source_id="sid_rej")
        r_good = RowDiagnostic(page=1, group=0, row=1, outcome="accepted", source_id="sid_good")
        g = GroupDiagnostics(group=0, strategy="digital", rows=[r_rej, r_good])
        p = PageDiagnostics(page=1, groups=[g])
        diag = ImportDiagnostics(pages=[p])
        tpath = create_test_catalog(df_rej, diagnostics=diag)
        try:
            adapter = ManualSearchAdapter([tpath])
            cands = adapter.search("").candidates
            names = [c.medicine_name for c in cands]
            self.assertIn("Amoxil 500mg Cap", names)
            self.assertNotIn("Bad Med 500mg Cap", names)
        finally:
            global_catalog_cache.remove(tpath)
            try:
                os.remove(tpath)
            except OSError:
                pass

    def test_05_stock_validation_respected(self):
        df_stock = pd.DataFrame([
            {"warehouse_name": "WhA", "item_name": "InStock Medicine 500mg Tab", "base_price": 40.0, "discount_rate": 0.10, "stock_status": True},
            {"warehouse_name": "WhA", "item_name": "OutOfStock Medicine 500mg Tab", "base_price": 40.0, "discount_rate": 0.10, "stock_status": False},
        ])
        tpath = create_test_catalog(df_stock)
        try:
            adapter = ManualSearchAdapter([tpath])
            cands = adapter.search("").candidates
            names = [c.medicine_name for c in cands]
            self.assertIn("InStock Medicine 500mg Tab", names)
            self.assertNotIn("OutOfStock Medicine 500mg Tab", names)
        finally:
            global_catalog_cache.remove(tpath)
            try:
                os.remove(tpath)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
