# -*- coding: utf-8 -*-
"""
tests/test_gui_responsiveness.py - Milestone 3 GUI Responsiveness & Latency Benchmark Suite.

Hardware Environment Benchmark:
- CPU: AMD Ryzen 7 2700 Eight-Core Processor (8 Cores, 16 Threads @ 3.20 GHz)
- OS Platform: Windows 11 (Windows-11-10.0.26300-SP0, AMD64)
- Python Version: 3.12.10 (tags/v3.12.10:0cc8128, Apr 8 2025, 12:21:36) [MSC v.1943 64 bit (AMD64)]

Verifies and benchmarks the 200 ms GUI responsiveness target on documented hardware:
1. Keystroke-to-debounce processing latency on the GUI thread under typing bursts (assert latency <= 200 ms).
2. Treeview rendering latency with 100 candidate rows (assert latency <= 200 ms, typically < 15 ms).
3. GUI event loop stall during asynchronous catalog loading and search queries using a periodic GUI pump timer (assert max task-induced GUI stall <= 200 ms).
4. Filter switching and sort mode toggling latency on already-rendered candidate sets (assert latency <= 200 ms).
5. Hardware environment details (CPU model, OS platform/version, Python version) recorded and validated.
"""
from __future__ import annotations

import os
import sys
import time
import platform
import tempfile
import threading
import queue
import unittest
from typing import Optional, List, Dict, Any
from unittest.mock import patch

import pandas as pd
import customtkinter as ctk
from tkinter import ttk

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
)

# 200 ms responsiveness budget (in seconds)
MAX_RESPONSIVENESS_BUDGET_SEC: float = 0.200


def get_hardware_info() -> Dict[str, str]:
    """Inspects and returns documented hardware and runtime environment details."""
    cpu_model = os.environ.get("PROCESSOR_IDENTIFIER", platform.processor() or platform.machine())
    try:
        import subprocess
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            cpu_model = proc.stdout.strip()
    except Exception:
        pass

    return {
        "cpu_model": cpu_model,
        "os_platform": platform.platform(),
        "os_version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_version": sys.version.replace("\n", " "),
        "python_implementation": platform.python_implementation(),
    }


_SHARED_APP: Optional[PharmaProcurementApp] = None


def get_shared_app() -> PharmaProcurementApp:
    global _SHARED_APP
    if _SHARED_APP is None:
        _SHARED_APP = PharmaProcurementApp()
        _SHARED_APP.withdraw()
    return _SHARED_APP


def create_mock_catalog_file(df: pd.DataFrame) -> str:
    """Helper to create a temporary Excel catalog and set it in global cache."""
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


def generate_candidate_dataset(count: int = 100) -> List[SearchResultItem]:
    """Generates realistic pharmaceutical search candidates for rendering tests."""
    candidates = []
    warehouses = ["ابن سينا فارما", "الشركة المتحدة للتوزيع", "فارما اوفرسيز", "مخزن الرواد"]
    drugs = [
        ("بانادول اكسترا 24 قرص", 45.0, 0.22),
        ("كونكور 5 مجم 30 قرص", 60.0, 0.18),
        ("اوجمنتين 1 جم 14 قرص", 110.0, 0.25),
        ("كتافلام 50 مجم 20 قرص", 55.0, 0.20),
        ("اماريل 2 مجم 30 قرص", 42.0, 0.15),
        ("بروفين 400 مجم 30 فوار", 38.0, 0.19),
        ("انتينال 24 كبسولة", 32.0, 0.21),
        ("كاربامازيبين 200 مجم", 28.0, 0.12),
        ("فولتارين 100 مجم 10 اقماع", 48.0, 0.24),
        ("اسبرين بروتكت 100 مجم", 35.0, 0.16),
    ]

    for i in range(count):
        base_name, base_price, base_disc = drugs[i % len(drugs)]
        wh = warehouses[i % len(warehouses)]
        price = round(base_price + (i * 0.5), 2)
        disc_rate = round(base_disc + ((i % 5) * 0.01), 4)
        net_price = round(price * (1.0 - disc_rate), 2)
        candidates.append(
            SearchResultItem(
                medicine_name=f"{base_name} [دفعة {i+1}]",
                warehouse_name=wh,
                base_price=price,
                discount_pct=round(disc_rate * 100.0, 2),
                net_price=net_price,
                ref_discount_pct=round(base_disc * 100.0, 2),
            )
        )
    return candidates


# =============================================================================
# Category 1: Hardware Environment Recording & Validation
# =============================================================================

class TestHardwareEnvironmentDetails(unittest.TestCase):
    """Logs and asserts documented hardware and platform execution environment."""

    def test_01_hardware_environment_recorded(self):
        hw = get_hardware_info()
        print("\n" + "=" * 60)
        print("MILESTONE 3 HARDWARE & RUNTIME BENCHMARK ENVIRONMENT:")
        print(f"  CPU Model:             {hw['cpu_model']}")
        print(f"  Architecture:          {hw['machine']} ({hw['processor']})")
        print(f"  Operating System:      {hw['os_platform']} (Version {hw['os_version']})")
        print(f"  Python Version:        {hw['python_version']}")
        print(f"  Python Implementation: {hw['python_implementation']}")
        print(f"  Responsiveness Target: <= {MAX_RESPONSIVENESS_BUDGET_SEC * 1000:.0f} ms")
        print("=" * 60)

        self.assertIsNotNone(hw["cpu_model"])
        self.assertGreater(len(hw["cpu_model"]), 0)
        self.assertIn("Windows", hw["os_platform"])
        self.assertIn("3.12", hw["python_version"])


# =============================================================================
# Category 2: Keystroke-to-Debounce Processing Latency (< 200 ms)
# =============================================================================

class TestKeystrokeDebounceProcessingLatency(unittest.TestCase):
    """
    Measures keystroke-to-debounce processing latency on the GUI thread under typing bursts.
    Target: All per-keystroke GUI event processing latencies <= 200 ms (typically < 1 ms).
    """

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

    def test_01_burst_typing_per_keystroke_latency(self):
        """Simulates rapid typing burst (30 keystrokes) and measures GUI thread latency."""
        query_text = "Panadol Extra 24 Tab RapidFuzz"
        latencies_ms: List[float] = []

        accumulated = ""
        for char in query_text:
            accumulated += char
            t_start = time.perf_counter()
            # Set StringVar to trigger trace_add -> _on_entry_changed
            self.win._search_var.set(accumulated)
            t_elapsed_ms = (time.perf_counter() - t_start) * 1000.0
            latencies_ms.append(t_elapsed_ms)

            # Assert strict <= 200 ms per keystroke budget
            self.assertLessEqual(
                t_elapsed_ms,
                MAX_RESPONSIVENESS_BUDGET_SEC * 1000.0,
                f"Keystroke '{char}' took {t_elapsed_ms:.2f} ms (budget <= 200 ms)",
            )

        max_lat = max(latencies_ms)
        avg_lat = sum(latencies_ms) / len(latencies_ms)
        print(
            f"\n[BENCHMARK] Keystroke typing burst ({len(query_text)} chars): "
            f"max={max_lat:.3f} ms, avg={avg_lat:.3f} ms (budget <= 200 ms)"
        )
        self.assertLessEqual(max_lat, 200.0)
        self.assertLessEqual(avg_lat, 50.0)

    def test_02_debounce_expiry_and_dispatch_latency(self):
        """Measures GUI thread latency when 60 ms debounce timer expires and triggers search."""
        self.win._search_var.set("Cataflam 50mg")

        # Measure direct execution time of _on_debounced_query on GUI thread
        t_start = time.perf_counter()
        self.win._on_debounced_query()
        t_elapsed_ms = (time.perf_counter() - t_start) * 1000.0

        print(f"\n[BENCHMARK] Debounce expiry & search dispatch latency: {t_elapsed_ms:.3f} ms")
        self.assertLessEqual(
            t_elapsed_ms,
            MAX_RESPONSIVENESS_BUDGET_SEC * 1000.0,
            f"Debounce dispatch took {t_elapsed_ms:.2f} ms (budget <= 200 ms)",
        )
        self.assertGreater(self.win._latest_job_id, 0)

    def test_03_sustained_burst_under_active_background_worker(self):
        """Simulates rapid typing bursts while the background worker thread is active."""
        # Start a background search
        self.win._trigger_search("Initial Heavy Query")

        latencies_ms: List[float] = []
        burst_chars = list("Augmentin 1g 14 Tablets Bid")
        accumulated = ""

        for ch in burst_chars:
            accumulated += ch
            t0 = time.perf_counter()
            self.win._search_var.set(accumulated)
            t_ms = (time.perf_counter() - t0) * 1000.0
            latencies_ms.append(t_ms)
            self.assertLessEqual(t_ms, 200.0)

        max_lat = max(latencies_ms)
        avg_lat = sum(latencies_ms) / len(latencies_ms)
        print(
            f"\n[BENCHMARK] Burst typing under active worker ({len(burst_chars)} chars): "
            f"max={max_lat:.3f} ms, avg={avg_lat:.3f} ms"
        )
        self.assertLessEqual(max_lat, 200.0)


# =============================================================================
# Category 3: Treeview Rendering Latency with 100 Rows (< 200 ms, typ < 15 ms)
# =============================================================================

class TestTreeviewRenderingLatency(unittest.TestCase):
    """
    Measures Treeview rendering latency with 100 candidate rows.
    Target: Rendering latency <= 200 ms (typically < 15 ms).
    """

    def setUp(self):
        self.app = get_shared_app()
        self.app.update()
        self.win = self.app._open_manual_search_window()
        self.app.update_idletasks()
        self.app.update()

    def tearDown(self):
        if self.win is not None:
            try:
                self.win._on_close()
            except Exception:
                pass
            self.win = None
        self.app.update()

    def test_01_treeview_rendering_latency_100_rows(self):
        """Renders 100 candidate rows into Treeview and forces geometry layout update."""
        candidates = generate_candidate_dataset(100)
        self.assertEqual(len(candidates), 100)

        job_res = SearchJobResult(
            job_id=1,
            catalog_generation_id=0,
            query="Panadol",
            warehouse_filter=None,
            sort_mode="best_match",
            candidates=candidates,
            reference_benchmark={"query": "Panadol", "formatted_pct": "22.5%"},
            total_matches=100,
            catalog_errors=[],
        )

        t_start = time.perf_counter()
        self.win._render_search_results(job_res)
        self.app.update_idletasks()
        render_ms = (time.perf_counter() - t_start) * 1000.0

        rendered_rows = len(self.win.tree.get_children())
        self.assertEqual(rendered_rows, 100)

        print(f"\n[BENCHMARK] Treeview render latency (100 candidate rows): {render_ms:.3f} ms")
        self.assertLessEqual(
            render_ms,
            MAX_RESPONSIVENESS_BUDGET_SEC * 1000.0,
            f"100-row render took {render_ms:.2f} ms (budget <= 200 ms)",
        )

    def test_02_consecutive_renders_latency(self):
        """Simulates 5 rapid result updates (100 rows each) and measures each latency."""
        latencies_ms: List[float] = []

        for i in range(5):
            candidates = generate_candidate_dataset(100)
            job_res = SearchJobResult(
                job_id=i + 1,
                catalog_generation_id=0,
                query=f"Batch {i}",
                warehouse_filter=None,
                sort_mode="best_match",
                candidates=candidates,
                reference_benchmark=None,
                total_matches=100,
                catalog_errors=[],
            )
            t_start = time.perf_counter()
            self.win._render_search_results(job_res)
            self.app.update_idletasks()
            dt_ms = (time.perf_counter() - t_start) * 1000.0
            latencies_ms.append(dt_ms)
            self.assertLessEqual(dt_ms, 200.0)

        max_lat = max(latencies_ms)
        avg_lat = sum(latencies_ms) / len(latencies_ms)
        print(
            f"\n[BENCHMARK] 5 Consecutive 100-row updates: "
            f"max={max_lat:.3f} ms, avg={avg_lat:.3f} ms"
        )
        self.assertLessEqual(max_lat, 200.0)
        self.assertLessEqual(avg_lat, 200.0)

    def test_03_enforces_100_row_cap_with_250_candidates(self):
        """Passes 250 candidates; verifies Treeview caps at 100 and latency <= 200 ms."""
        candidates = generate_candidate_dataset(250)
        self.assertEqual(len(candidates), 250)

        job_res = SearchJobResult(
            job_id=99,
            catalog_generation_id=0,
            query="Oversized",
            warehouse_filter=None,
            sort_mode="best_match",
            candidates=candidates,
            reference_benchmark=None,
            total_matches=250,
            catalog_errors=[],
        )

        t_start = time.perf_counter()
        self.win._render_search_results(job_res)
        self.app.update_idletasks()
        dt_ms = (time.perf_counter() - t_start) * 1000.0

        rendered_rows = len(self.win.tree.get_children())
        self.assertEqual(rendered_rows, 100, "Must enforce strictly <= 100 rows in Treeview")
        self.assertIn("250", self.win.status_label.cget("text"))
        self.assertIn("100", self.win.status_label.cget("text"))

        print(f"\n[BENCHMARK] 250 candidates (capped to 100) render latency: {dt_ms:.3f} ms")
        self.assertLessEqual(dt_ms, 200.0)


# =============================================================================
# Category 4: GUI Event Loop Stall During Asynchronous Catalog Operations
# =============================================================================

class TestGuiEventLoopStallDuringAsyncOperations(unittest.TestCase):
    """
    Measures GUI event loop stall during asynchronous catalog loading and search queries.
    Uses a periodic GUI pump timer (e.g. 15 ms interval) to detect main thread stalls.
    Target: Max task-induced GUI stall <= 200 ms.
    """

    def setUp(self):
        self.app = get_shared_app()
        rows = [
            {"warehouse_name": "IbnSina", "item_name": "Panadol Extra 24 Tab", "base_price": 45.0, "discount_rate": 0.22, "stock_status": True},
            {"warehouse_name": "United", "item_name": "Panadol Advance 24 Tab", "base_price": 40.0, "discount_rate": 0.20, "stock_status": True},
            {"warehouse_name": "Overseas", "item_name": "Cataflam 50mg 20 Tab", "base_price": 55.0, "discount_rate": 0.18, "stock_status": True},
            {"warehouse_name": "Rowad", "item_name": "Augmentin 1g 14 Tab", "base_price": 110.0, "discount_rate": 0.25, "stock_status": True},
            {"warehouse_name": "IbnSina", "item_name": "Concor 5mg 30 Tab", "base_price": 60.0, "discount_rate": 0.19, "stock_status": True},
        ]
        self.cat_df = pd.DataFrame(rows)
        self.cat_path = create_mock_catalog_file(self.cat_df)
        self.app.file_model.clear()
        self.app.file_model.add_paths([self.cat_path])

        self.win = self.app._open_manual_search_window()
        self.app.update()

    def tearDown(self):
        if self.win is not None:
            try:
                self.win._on_close()
            except Exception:
                pass
            self.win = None
        global_catalog_cache.remove(self.cat_path)
        try:
            os.remove(self.cat_path)
        except OSError:
            pass

    def test_01_gui_event_loop_stall_during_async_search(self):
        """
        Runs a periodic 15 ms GUI pump timer while background search queries run.
        Measures jitter/stall of GUI event loop: max stall must be <= 200 ms.
        """
        pump_interval_ms = 15.0
        tick_timestamps: List[float] = []
        pump_active = True

        def pump_timer():
            if pump_active and self.win is not None and not self.win._cancelled:
                tick_timestamps.append(time.perf_counter())
                self.win.after(int(pump_interval_ms), pump_timer)

        # Trigger asynchronous search queries
        self.win._trigger_search("Panadol")
        self.app.update()
        self.win._trigger_search("Augmentin")
        self.app.update()
        self.win._trigger_search("Cataflam")
        self.app.update()

        # Start GUI pump timer to measure event loop responsiveness while worker processes jobs
        tick_timestamps.append(time.perf_counter())
        self.win.after(int(pump_interval_ms), pump_timer)

        # Pump GUI event loop for 1.2 seconds while worker runs
        end_time = time.perf_counter() + 1.2
        while time.perf_counter() < end_time:
            self.app.update()
            time.sleep(0.01)

        pump_active = False

        # Calculate time gaps between consecutive pump ticks
        gaps_ms: List[float] = []
        for i in range(1, len(tick_timestamps)):
            gap_ms = (tick_timestamps[i] - tick_timestamps[i - 1]) * 1000.0
            gaps_ms.append(gap_ms)

        self.assertGreater(len(gaps_ms), 10, "Expected at least 10 pump timer ticks")

        # Task-induced stall is how much the gap exceeds the expected interval
        stalls_ms = [max(0.0, g - pump_interval_ms) for g in gaps_ms]
        max_stall_ms = max(stalls_ms)
        avg_gap_ms = sum(gaps_ms) / len(gaps_ms)

        print(
            f"\n[BENCHMARK] GUI Pump Timer (15 ms): {len(gaps_ms)} ticks recorded. "
            f"Max stall: {max_stall_ms:.2f} ms, Avg tick gap: {avg_gap_ms:.2f} ms "
            f"(target max stall <= 200 ms)"
        )

        self.assertLessEqual(
            max_stall_ms,
            MAX_RESPONSIVENESS_BUDGET_SEC * 1000.0,
            f"GUI event loop stalled for {max_stall_ms:.2f} ms during async search (budget <= 200 ms)",
        )

    def test_02_gui_event_loop_responsiveness_under_rapid_query_burst(self):
        """Dispatches 10 rapid queries and verifies event loop pump responsiveness."""
        tick_timestamps: List[float] = []
        pump_active = True

        def pump_timer():
            if pump_active and self.win is not None and not self.win._cancelled:
                tick_timestamps.append(time.perf_counter())
                self.win.after(10, pump_timer)

        self.win.after(10, pump_timer)
        self.app.update()
        tick_timestamps.append(time.perf_counter())

        for i in range(10):
            self.win._trigger_search(f"Drug Query {i}")
            self.app.update()

        end_time = time.perf_counter() + 0.8
        while time.perf_counter() < end_time:
            self.app.update()
            time.sleep(0.01)

        pump_active = False

        gaps_ms = [
            (tick_timestamps[i] - tick_timestamps[i - 1]) * 1000.0
            for i in range(1, len(tick_timestamps))
        ]
        self.assertGreater(len(gaps_ms), 5)
        stalls_ms = [max(0.0, g - 10.0) for g in gaps_ms]
        max_stall_ms = max(stalls_ms)

        print(
            f"\n[BENCHMARK] Rapid 10-query burst: {len(gaps_ms)} ticks. "
            f"Max stall: {max_stall_ms:.2f} ms"
        )
        self.assertLessEqual(max_stall_ms, 200.0)


# =============================================================================
# Category 5: Filter Switching & Sort Mode Toggling Latency (< 200 ms)
# =============================================================================

class TestFilterAndSortToggleLatency(unittest.TestCase):
    """
    Measures filter switching and sort mode toggling latency on already-rendered candidate sets.
    Target: All switching and re-rendering latencies <= 200 ms.
    """

    def setUp(self):
        self.app = get_shared_app()
        self.win = self.app._open_manual_search_window()

        # Render 100 initial candidates
        self.initial_candidates = generate_candidate_dataset(100)
        job_res = SearchJobResult(
            job_id=1,
            catalog_generation_id=0,
            query="Panadol",
            warehouse_filter=None,
            sort_mode="best_match",
            candidates=self.initial_candidates,
            reference_benchmark=None,
            total_matches=100,
            catalog_errors=[],
        )
        self.win._render_search_results(job_res)
        self.app.update_idletasks()

    def tearDown(self):
        if self.win is not None:
            try:
                self.win._on_close()
            except Exception:
                pass
            self.win = None

    def test_01_warehouse_filter_switch_latency(self):
        """Measures GUI thread latency of switching warehouse filter."""
        t_start = time.perf_counter()
        self.win._warehouse_var.set("ابن سينا فارما")
        self.win._on_filter_changed("ابن سينا فارما")
        switch_ms = (time.perf_counter() - t_start) * 1000.0

        print(f"\n[BENCHMARK] Warehouse filter switch latency: {switch_ms:.3f} ms")
        self.assertLessEqual(
            switch_ms,
            MAX_RESPONSIVENESS_BUDGET_SEC * 1000.0,
            f"Filter switch took {switch_ms:.2f} ms (budget <= 200 ms)",
        )

    def test_02_sort_mode_toggle_latency(self):
        """Measures GUI thread latency of toggling sort mode."""
        t_start = time.perf_counter()
        self.win._on_sort_changed("أعلى خصم / Highest Discount")
        toggle_ms = (time.perf_counter() - t_start) * 1000.0

        self.assertEqual(self.win._sort_mode_var.get(), "highest_discount")
        print(f"\n[BENCHMARK] Sort mode toggle to Highest Discount: {toggle_ms:.3f} ms")
        self.assertLessEqual(
            toggle_ms,
            MAX_RESPONSIVENESS_BUDGET_SEC * 1000.0,
            f"Sort toggle took {toggle_ms:.2f} ms (budget <= 200 ms)",
        )

        # Toggle back to Best Match
        t_start2 = time.perf_counter()
        self.win._on_sort_changed("أفضل تطابق / Best Match")
        toggle_ms2 = (time.perf_counter() - t_start2) * 1000.0

        self.assertEqual(self.win._sort_mode_var.get(), "best_match")
        print(f"\n[BENCHMARK] Sort mode toggle to Best Match: {toggle_ms2:.3f} ms")
        self.assertLessEqual(toggle_ms2, 200.0)

    def test_03_end_to_end_sort_and_rerender_latency(self):
        """
        Measures sorting 100 candidates by discount_pct descending and re-rendering into Treeview.
        """
        t_start = time.perf_counter()

        # 1. Sort candidates by discount descending (stable mergesort)
        sorted_candidates = sorted(
            self.initial_candidates,
            key=lambda c: c.discount_pct,
            reverse=True,
        )

        # 2. Re-render into Treeview
        job_res = SearchJobResult(
            job_id=2,
            catalog_generation_id=0,
            query="Panadol",
            warehouse_filter=None,
            sort_mode="highest_discount",
            candidates=sorted_candidates,
            reference_benchmark=None,
            total_matches=100,
            catalog_errors=[],
        )
        self.win._render_search_results(job_res)
        self.app.update_idletasks()

        elapsed_ms = (time.perf_counter() - t_start) * 1000.0

        # Verify items in Treeview are sorted descending by discount
        rendered_items = self.win.tree.get_children()
        self.assertEqual(len(rendered_items), 100)
        first_disc = float(self.win.tree.item(rendered_items[0])["values"][3].replace("%", ""))
        last_disc = float(self.win.tree.item(rendered_items[-1])["values"][3].replace("%", ""))
        self.assertGreaterEqual(first_disc, last_disc)

        print(f"\n[BENCHMARK] End-to-end sort & re-render latency (100 rows): {elapsed_ms:.3f} ms")
        self.assertLessEqual(
            elapsed_ms,
            MAX_RESPONSIVENESS_BUDGET_SEC * 1000.0,
            f"End-to-end sort and re-render took {elapsed_ms:.2f} ms (budget <= 200 ms)",
        )

    def test_04_rapid_filter_sort_sequence_latency(self):
        """Executes a rapid 6-operation alternating sequence of filter and sort changes."""
        latencies_ms: List[float] = []

        operations = [
            lambda: self.win._on_filter_changed("ابن سينا فارما"),
            lambda: self.win._on_sort_changed("أعلى خصم / Highest Discount"),
            lambda: self.win._on_filter_changed("الشركة المتحدة للتوزيع"),
            lambda: self.win._on_sort_changed("أفضل تطابق / Best Match"),
            lambda: self.win._on_filter_changed("الكل / All"),
            lambda: self.win._on_sort_changed("أعلى خصم / Highest Discount"),
        ]

        for op in operations:
            t0 = time.perf_counter()
            op()
            t_ms = (time.perf_counter() - t0) * 1000.0
            latencies_ms.append(t_ms)
            self.assertLessEqual(t_ms, 200.0)

        max_lat = max(latencies_ms)
        avg_lat = sum(latencies_ms) / len(latencies_ms)
        print(
            f"\n[BENCHMARK] Rapid 6-operation filter/sort sequence: "
            f"max={max_lat:.3f} ms, avg={avg_lat:.3f} ms"
        )
        self.assertLessEqual(max_lat, 200.0)


if __name__ == "__main__":
    unittest.main()
