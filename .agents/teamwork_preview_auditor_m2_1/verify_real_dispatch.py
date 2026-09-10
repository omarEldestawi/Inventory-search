# -*- coding: utf-8 -*-
"""
Empirical Execution Tracing for Milestone M2.
Independently verifies that app_gui.py dispatches ProcurementEngineBridge,
executes the background worker thread with real catalog and order files,
processes progress events, and updates UI widgets with real KPI results.
"""
import os
import sys
import time
import tempfile

project_root = os.path.abspath("c:/Users/omart/.gemini/antigravity/scratch/Inventory-search")
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app_gui import PharmaProcurementApp
from src.controller import ProcurementEngineBridge

def test_real_dispatch_and_kpi_binding():
    print("[AUDIT TRACE] Initializing headless PharmaProcurementApp...")
    app = PharmaProcurementApp()
    app.withdraw()

    # Create temp output directory
    with tempfile.TemporaryDirectory() as tmp_out:
        app.output_dir_var.set(tmp_out)

        order_path = os.path.join(project_root, "input", "orders", "طلبية_اليوم.xlsx")
        catalog_path = os.path.join(project_root, "input", "catalogs", "الشركة_المتحدة.pdf")

        assert os.path.exists(order_path), f"Missing order file: {order_path}"
        assert os.path.exists(catalog_path), f"Missing catalog file: {catalog_path}"

        print(f"[AUDIT TRACE] Adding files:\n  Order: {order_path}\n  Catalog: {catalog_path}")
        app.add_files([order_path, catalog_path])

        is_valid, reason = app.file_model.validate(tmp_out)
        print(f"[AUDIT TRACE] Validation status: is_valid={is_valid}, reason={reason}")
        assert is_valid, f"Validation failed unexpectedly: {reason}"
        assert app.run_button.cget("state") == "normal", "Run button should be normal when valid"

        print("[AUDIT TRACE] Triggering _on_run_optimization()...")
        app._on_run_optimization()

        assert app.bridge is not None, "Bridge was not created"
        assert isinstance(app.bridge, ProcurementEngineBridge), "Bridge is not ProcurementEngineBridge instance"
        print("[AUDIT TRACE] Verified ProcurementEngineBridge successfully created.")

        # Poll until execution finishes
        progress_events = []
        max_wait_seconds = 60
        start_time = time.time()

        while app.bridge.is_running and (time.time() - start_time) < max_wait_seconds:
            # Emulate Tkinter after(50) event loop
            app.poll_queue()
            pct = app.progress_bar.get()
            status = app.status_label.cget("text")
            if not progress_events or progress_events[-1] != (pct, status):
                progress_events.append((pct, status))
                print(f"  -> Progress: {pct*100:.1f}% | {status}")
            time.sleep(0.1)

        # Final queue flush
        app.poll_queue()
        elapsed = time.time() - start_time
        print(f"[AUDIT TRACE] Execution completed in {elapsed:.2f}s")

        assert not app.bridge.is_running, "Worker thread timed out or failed to complete"
        assert app.bridge.last_error is None, f"Pipeline encountered error: {app.bridge.last_error}"
        assert app.bridge.last_result is not None, "No result found in bridge"

        results = app.bridge.last_result
        kpis = results.get("kpis", {})
        print(f"[AUDIT TRACE] Engine KPIs: {kpis}")

        # Verify UI widget bindings
        req_text = app.card_req.cget("text")
        alloc_text = app.card_alloc.cget("text")
        oos_text = app.card_oos.cget("text")
        disc_text = app.card_disc.cget("text")
        sav_text = app.card_sav.cget("text")
        wh_text = app.wholesalers_pills_label.cget("text")
        open_rep_state = app.open_report_btn.cget("state")
        open_fld_state = app.open_folder_btn.cget("state")

        print("[AUDIT TRACE] UI Widget Values:")
        print(f"  card_req: {req_text} (expected: {kpis.get('total_items')})")
        print(f"  card_alloc: {alloc_text} (expected: {kpis.get('matched_items')})")
        print(f"  card_oos: {oos_text} (expected: {kpis.get('out_of_stock')})")
        print(f"  card_disc: {disc_text} (expected: {kpis.get('avg_discount'):.1f}%)")
        print(f"  card_sav: {sav_text}")
        print(f"  wholesalers: {wh_text}")
        print(f"  open_report_btn state: {open_rep_state}")
        print(f"  open_folder_btn state: {open_fld_state}")

        assert req_text == str(kpis.get("total_items")), "card_req does not match engine output"
        assert str(kpis.get("matched_items")) in alloc_text, "card_alloc does not match engine output"
        assert oos_text == str(kpis.get("out_of_stock")), "card_oos does not match engine output"
        assert disc_text == f"{kpis.get('avg_discount'):.1f}%", "card_disc does not match engine output"
        assert open_rep_state == "normal", "open_report_btn should be enabled"
        assert open_fld_state == "normal", "open_folder_btn should be enabled"

        # Verify generated report exists on disk
        report_path = app.current_report_path
        print(f"[AUDIT TRACE] Report path on disk: {report_path}")
        assert report_path and os.path.exists(report_path), f"Report file does not exist: {report_path}"
        assert os.path.getsize(report_path) > 1000, "Report file is suspiciously small"

        print("[AUDIT TRACE] All real execution bindings verified successfully and authentically!")

    app.destroy()

if __name__ == "__main__":
    test_real_dispatch_and_kpi_binding()
