# -*- coding: utf-8 -*-
"""
Empirical test: What in update_idletasks() takes 130-160ms?
Test A: Only Treeview items (without benchmark_card or status_label changes).
Test B: Only benchmark_card (without Treeview changes).
Test C: What if benchmark_frame is already gridded in setUp?
Test D: What if Treeview items are inserted without grid_remove?
"""
import time
from app_gui import PharmaProcurementApp
from src.manual_search_adapter import SearchResultItem
from src.manual_search_window import SearchJobResult
from tests.test_gui_responsiveness import generate_candidate_dataset

def test_breakdown_components():
    print("=" * 70)
    print("EMPIRICAL TEST: Pinpointing 130-160ms in update_idletasks()")
    print("=" * 70)

    app = PharmaProcurementApp()
    app.withdraw()
    app.update()

    # Case 1: Window opened, benchmark_frame ALREADY gridded during setup
    print("\n--- Case 1: benchmark_frame pre-mapped during setup ---")
    for trial in range(3):
        win = app._open_manual_search_window()
        win.benchmark_frame.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 6))
        app.update_idletasks()
        app.update()

        candidates = generate_candidate_dataset(100)
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
        win._render_search_results(job_res)
        t_after_render = time.perf_counter()
        app.update_idletasks()
        t_after_idletasks = time.perf_counter()

        render_method_ms = (t_after_render - t_start) * 1000.0
        idletasks_ms = (t_after_idletasks - t_after_render) * 1000.0
        total_ms = (t_after_idletasks - t_start) * 1000.0
        print(f"Trial {trial+1}: render_method={render_method_ms:.2f} ms, idletasks={idletasks_ms:.2f} ms, Total={total_ms:.2f} ms")
        win._on_close()
        app.update()

    # Case 2: Window opened, NO reference benchmark (reference_benchmark=None)
    print("\n--- Case 2: NO reference benchmark (reference_benchmark=None) ---")
    for trial in range(3):
        win = app._open_manual_search_window()
        app.update_idletasks()
        app.update()

        candidates = generate_candidate_dataset(100)
        job_res = SearchJobResult(
            job_id=1,
            catalog_generation_id=0,
            query="Panadol",
            warehouse_filter=None,
            sort_mode="best_match",
            candidates=candidates,
            reference_benchmark=None,
            total_matches=100,
            catalog_errors=[],
        )

        t_start = time.perf_counter()
        win._render_search_results(job_res)
        t_after_render = time.perf_counter()
        app.update_idletasks()
        t_after_idletasks = time.perf_counter()

        render_method_ms = (t_after_render - t_start) * 1000.0
        idletasks_ms = (t_after_idletasks - t_after_render) * 1000.0
        total_ms = (t_after_idletasks - t_start) * 1000.0
        print(f"Trial {trial+1}: render_method={render_method_ms:.2f} ms, idletasks={idletasks_ms:.2f} ms, Total={total_ms:.2f} ms")
        win._on_close()
        app.update()

    # Case 3: Consecutive render (2nd render on same window)
    print("\n--- Case 3: 1st render vs 2nd render on SAME window ---")
    win = app._open_manual_search_window()
    app.update_idletasks()
    app.update()

    candidates = generate_candidate_dataset(100)
    job_res1 = SearchJobResult(
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
    win._render_search_results(job_res1)
    t_after_render = time.perf_counter()
    app.update_idletasks()
    t_after_idletasks = time.perf_counter()
    print(f"1st Render on Window: render={ (t_after_render-t_start)*1000:.2f} ms, idletasks={ (t_after_idletasks-t_after_render)*1000:.2f} ms, Total={ (t_after_idletasks-t_start)*1000:.2f} ms")

    job_res2 = SearchJobResult(
        job_id=2,
        catalog_generation_id=0,
        query="Panadol 2",
        warehouse_filter=None,
        sort_mode="best_match",
        candidates=candidates,
        reference_benchmark={"query": "Panadol 2", "formatted_pct": "25.0%"},
        total_matches=100,
        catalog_errors=[],
    )
    t_start2 = time.perf_counter()
    win._render_search_results(job_res2)
    t_after_render2 = time.perf_counter()
    app.update_idletasks()
    t_after_idletasks2 = time.perf_counter()
    print(f"2nd Render on Window: render={ (t_after_render2-t_start2)*1000:.2f} ms, idletasks={ (t_after_idletasks2-t_after_render2)*1000:.2f} ms, Total={ (t_after_idletasks2-t_start2)*1000:.2f} ms")

    win._on_close()
    app.update()
    app.destroy()

if __name__ == "__main__":
    test_breakdown_components()
