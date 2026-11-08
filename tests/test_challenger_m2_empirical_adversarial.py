# -*- coding: utf-8 -*-
"""
tests/test_challenger_m2_empirical_adversarial.py
Adversarial Empirical Verification Suite for Milestone 2:
1. Single instance reuse under rapid concurrent burst
2. 60 ms debounce timer precision and cancellation verification
3. Bounded worker queue strict capacity enforcement (<= 1)
4. Stale asynchronous result drop & out-of-order completion resistance
5. Complete catalog generation invalidation across all catalog modification hooks
6. Safe teardown under active background search load without TclError
7. Strict procurement decoupling (zero mutation of acknowledged_token or procurement readiness)
"""
from __future__ import annotations

import os
import queue
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
    ReviewIssue,
)

_TEST_APP: Optional[PharmaProcurementApp] = None


def get_test_app() -> PharmaProcurementApp:
    global _TEST_APP
    if _TEST_APP is None:
        _TEST_APP = PharmaProcurementApp()
        _TEST_APP.withdraw()
    return _TEST_APP


def create_temp_catalog_file(df: pd.DataFrame) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    path = os.path.normpath(os.path.abspath(tmp.name))
    tmp.close()
    df.to_excel(path, index=False)
    fp = FileFingerprint.from_path(path)
    res = CatalogResult(
        dataframe=df,
        diagnostics=ImportDiagnostics(),
        fingerprint=fp,
        review_issues=[],
    )
    global_catalog_cache.set(path, res.to_dataframe(), force=True)
    return path


class TestAdversarialSingleInstanceReuse(unittest.TestCase):
    """Stress-test single instance reuse under burst triggers."""

    def setUp(self):
        self.app = get_test_app()
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

    def test_burst_open_creates_strictly_single_window(self):
        windows = []
        for _ in range(25):
            win = self.app._open_manual_search_window()
            windows.append(win)
            self.app.update_idletasks()

        # All references returned must be the exact same object
        first_win = windows[0]
        for idx, w in enumerate(windows):
            self.assertIs(w, first_win, f"Window at call {idx} was not identical instance")

        self.assertTrue(first_win.winfo_exists())
        self.assertIs(self.app._manual_search_window, first_win)

    def test_withdrawn_window_deiconifies_and_focuses(self):
        win = self.app._open_manual_search_window()
        self.app.update_idletasks()
        # Transient windows are minimized via withdraw
        win.withdraw()
        self.app.update_idletasks()
        self.assertEqual(win.state(), "withdrawn")

        win2 = self.app._open_manual_search_window()
        self.app.update_idletasks()

        self.assertIs(win, win2)
        # Window state must be restored by deiconify()
        state = win.state()
        self.assertIn(state, ("normal", "zoomed"))


class TestAdversarialDebounceTimer(unittest.TestCase):
    """Stress-test 60ms debounce timer with rapid keystroke sequences."""

    def setUp(self):
        self.app = get_test_app()
        self.win = self.app._open_manual_search_window()
        self.app.update_idletasks()

    def tearDown(self):
        if self.win and self.win.winfo_exists():
            self.win._on_close()
        self.app._manual_search_window = None

    def test_rapid_keystrokes_suppress_intermediate_searches(self):
        initial_job_id = self.win._latest_job_id

        # Rapidly type 8 characters with 15ms intervals (<60ms debounce)
        chars = "panadol "
        for ch in chars:
            current = self.win._search_var.get()
            self.win._search_var.set(current + ch)
            time.sleep(0.015)
            self.app.update_idletasks()

        # Job ID should NOT have updated yet because debounce timer keeps resetting
        self.assertEqual(
            self.win._latest_job_id,
            initial_job_id,
            "Intermediate keystroke triggered premature search before debounce settled"
        )

        # Wait for debounce timer (60ms + margin)
        time.sleep(0.12)
        self.app.update()

        # Exactly 1 new job ID increment
        self.assertEqual(
            self.win._latest_job_id,
            initial_job_id + 1,
            "Debounced query failed to submit exactly 1 job after typing ceased"
        )


class TestAdversarialBoundedQueue(unittest.TestCase):
    """Stress-test worker queue bound <= 1 under worker blockage."""

    def setUp(self):
        self.app = get_test_app()
        self.win = self.app._open_manual_search_window()
        self.app.update_idletasks()

    def tearDown(self):
        if self.win and self.win.winfo_exists():
            self.win._on_close()
        self.app._manual_search_window = None

    def test_rapid_query_flood_maintains_qsize_at_most_one(self):
        # Flood 30 rapid query triggers
        for i in range(30):
            self.win._trigger_search(f"med_{i}")
            qsize = self.win._job_queue.qsize()
            self.assertLessEqual(
                qsize, 1,
                f"Job queue size {qsize} exceeded maximum bound of 1 at iteration {i}"
            )
        self.app.update()


class TestAdversarialStaleResultRejection(unittest.TestCase):
    """Verify stale asynchronous results and obsolete catalog generations are dropped."""

    def setUp(self):
        self.app = get_test_app()
        self.win = self.app._open_manual_search_window()
        self.app.update_idletasks()

    def tearDown(self):
        if self.win and self.win.winfo_exists():
            self.win._on_close()
        self.app._manual_search_window = None

    def test_out_of_order_slow_result_is_discarded(self):
        current_gen = self.win._catalog_generation_id
        self.win._latest_job_id = 100

        # Create slow old result (job_id 95)
        stale_item = SearchResultItem("StaleDrugOld", "WholesalerA", 50.0, 10.0, 45.0, None)
        stale_res = SearchJobResult(
            job_id=95,
            catalog_generation_id=current_gen,
            query="old",
            warehouse_filter=None,
            sort_mode="best_match",
            candidates=[stale_item],
            reference_benchmark=None,
            total_matches=1,
            catalog_errors=[],
        )

        # Create fresh result (job_id 100)
        fresh_item = SearchResultItem("FreshDrugNew", "WholesalerB", 80.0, 20.0, 64.0, None)
        fresh_res = SearchJobResult(
            job_id=100,
            catalog_generation_id=current_gen,
            query="new",
            warehouse_filter=None,
            sort_mode="best_match",
            candidates=[fresh_item],
            reference_benchmark=None,
            total_matches=1,
            catalog_errors=[],
        )

        # First render fresh result
        self.win._render_search_results(fresh_res)
        tree_children = self.win.tree.get_children()
        self.assertEqual(len(tree_children), 1)
        self.assertEqual(self.win.tree.item(tree_children[0])["values"][0], "FreshDrugNew")

        # Now push stale result into _result_queue and run poller
        self.win._result_queue.put(stale_res)
        self.win._poll_result_queue()
        self.app.update_idletasks()

        # Treeview MUST NOT have been overwritten with StaleDrugOld!
        tree_children = self.win.tree.get_children()
        self.assertEqual(len(tree_children), 1)
        self.assertEqual(
            self.win.tree.item(tree_children[0])["values"][0],
            "FreshDrugNew",
            "Stale asynchronous result incorrectly overwrote newer search result!"
        )

    def test_stale_catalog_generation_result_is_discarded(self):
        self.win._catalog_generation_id = 5
        self.win._latest_job_id = 10

        old_gen_item = SearchResultItem("OldGenDrug", "WholesalerA", 30.0, 5.0, 28.5, None)
        old_gen_res = SearchJobResult(
            job_id=10,
            catalog_generation_id=4,  # Old generation
            query="med",
            warehouse_filter=None,
            sort_mode="best_match",
            candidates=[old_gen_item],
            reference_benchmark=None,
            total_matches=1,
            catalog_errors=[],
        )

        self.win.tree.delete(*self.win.tree.get_children())
        self.win._result_queue.put(old_gen_res)
        self.win._poll_result_queue()
        self.app.update_idletasks()

        # Treeview must remain empty because generation 4 != generation 5
        self.assertEqual(len(self.win.tree.get_children()), 0)


class TestAdversarialCatalogGenerationInvalidation(unittest.TestCase):
    """Empirically verify all catalog modification entrypoints bump generation."""

    def setUp(self):
        self.app = get_test_app()
        self.app.file_model.clear()
        self.win = self.app._open_manual_search_window()
        self.app.update_idletasks()

    def tearDown(self):
        if self.win and self.win.winfo_exists():
            self.win._on_close()
        self.app._manual_search_window = None
        self.app.file_model.clear()

    def test_all_catalog_hooks_bump_generation(self):
        initial_gen = self.app._catalog_generation_id

        # 1. Direct bump
        self.app._bump_catalog_generation()
        self.assertEqual(self.app._catalog_generation_id, initial_gen + 1)
        self.assertEqual(self.win._catalog_generation_id, initial_gen + 1)

        # 2. Add files via app.add_files
        with patch.object(self.app.file_model, "add_paths", return_value=(1, [])):
            self.app.add_files(["mock_catalog.xlsx"])
        self.assertEqual(self.app._catalog_generation_id, initial_gen + 2)
        self.assertEqual(self.win._catalog_generation_id, initial_gen + 2)

        # 3. Clear all
        self.app._on_clear_all()
        self.assertEqual(self.app._catalog_generation_id, initial_gen + 3)
        self.assertEqual(self.win._catalog_generation_id, initial_gen + 3)

        # 4. Remove file
        self.app._on_remove_file("mock_catalog.xlsx")
        self.assertEqual(self.app._catalog_generation_id, initial_gen + 4)
        self.assertEqual(self.win._catalog_generation_id, initial_gen + 4)


class TestAdversarialSafeTeardown(unittest.TestCase):
    """Stress-test safe teardown while background searches are running."""

    @classmethod
    def setUpClass(cls):
        # Pre-warm MedicationDB so SQLite WAL / OS file cache is loaded
        try:
            from src.medication_db import MedicationDB
            MedicationDB()
        except Exception:
            pass

    def setUp(self):
        self.app = get_test_app()
        if getattr(self.app, "_manual_search_window", None) is not None:
            try:
                self.app._manual_search_window._on_close()
            except Exception:
                pass
            self.app._manual_search_window = None
        self.temp_files = []

    def tearDown(self):
        if getattr(self.app, "_manual_search_window", None) is not None:
            try:
                self.app._manual_search_window._on_close()
            except Exception:
                pass
            self.app._manual_search_window = None
        for p in self.temp_files:
            global_catalog_cache.remove(p)
            try:
                os.remove(p)
            except OSError:
                pass

    def test_teardown_during_high_search_activity(self):
        # Simulate a search in progress in the background worker
        def slow_search(*args, **kwargs):
            time.sleep(0.3)
            return ManualSearchResult(
                job_id=1,
                catalog_gen_id=0,
                query="test",
                warehouse_filter=None,
                sort_mode="best_match",
                candidates=[],
                reference_benchmark=None,
                total_matches=0,
                catalog_errors=[],
            )

        with patch.object(ManualSearchAdapter, "_build_index"), \
             patch.object(ManualSearchAdapter, "search", side_effect=slow_search):
            win = self.app._open_manual_search_window()
            self.app.update_idletasks()

            # Fire search to start background activity
            win._trigger_search("active_query")
            time.sleep(0.05)

            worker = win._worker_thread
            self.assertTrue(worker.is_alive())

            # Immediately close while search is actively in-flight
            win._on_close()
            self.app.update_idletasks()
            self.app.update()

            # 1. Verify window was destroyed cleanly without widget errors
            self.assertFalse(win.winfo_exists())
            self.assertIsNone(self.app._manual_search_window)

            # 2. Verify all timers are cancelled and cancellation flags set
            self.assertTrue(win._cancelled)
            self.assertTrue(win._stop_event.is_set())
            self.assertIsNone(win._debounce_timer)
            self.assertIsNone(win._poll_timer)

            # 3. Verify polling on closed/destroyed window causes zero TclError
            try:
                win._poll_result_queue()
            except Exception as exc:
                self.fail(f"_poll_result_queue failed on closed window: {exc}")

            # 4. Wait for worker daemon thread to observe stop event and exit cleanly
            worker.join(timeout=3.0)
            if worker.is_alive():
                import sys, traceback
                print("\n=== ACTIVE THREAD STACKS ===")
                for tid, frame in sys._current_frames().items():
                    print(f"\n--- Thread {tid} ---")
                    traceback.print_stack(frame)
                print("=== END STACKS ===\n")
            self.assertFalse(worker.is_alive(), "Worker daemon thread failed to exit after stop event was set")


class TestAdversarialProcurementDecoupling(unittest.TestCase):
    """Verify that opening manual search never marks or approves catalog for procurement."""

    def setUp(self):
        self.app = get_test_app()
        self.app.file_model.clear()
        self.temp_files = []

    def tearDown(self):
        if getattr(self.app, "_manual_search_window", None) is not None:
            try:
                self.app._manual_search_window._on_close()
            except Exception:
                pass
            self.app._manual_search_window = None
        self.app.file_model.clear()
        for p in self.temp_files:
            global_catalog_cache.remove(p)
            try:
                os.remove(p)
            except OSError:
                pass

    def test_manual_search_leaves_acknowledged_token_strictly_none(self):
        df = pd.DataFrame([
            {"item_name": "Augmentin 1g", "base_price": 120.0, "discount_rate": 0.20, "stock_status": True}
        ])
        cat_path = create_temp_catalog_file(df)
        self.temp_files.append(cat_path)

        fi = FileItem(cat_path, "Catalog")
        fi.acknowledged_token = None
        self.app.file_model.files = [fi]

        cat_item = self.app.file_model.files[0]
        self.assertIsNone(cat_item.acknowledged_token)

        # Open search window
        win = self.app._open_manual_search_window()
        self.app.update_idletasks()

        # Execute searches, filter, sort
        win._search_var.set("Augmentin")
        time.sleep(0.1)
        self.app.update()

        win._sort_mode_var.set("highest_discount")
        win._trigger_search("Augmentin")
        time.sleep(0.1)
        self.app.update()

        # Verify acknowledged_token is still None
        self.assertIsNone(
            cat_item.acknowledged_token,
            "Manual search mutated acknowledged_token!"
        )

        # Close search window
        win._on_close()
        self.app.update_idletasks()

        self.assertIsNone(
            cat_item.acknowledged_token,
            "Manual search mutated acknowledged_token after window closed!"
        )


if __name__ == "__main__":
    unittest.main()
