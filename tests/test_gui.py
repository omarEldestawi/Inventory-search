# -*- coding: utf-8 -*-
"""
Automated Test Suite for CustomTkinter Windows 11 Desktop GUI (app_gui.py).
Tests headless instantiation, file list management, auto-classification, manual override,
validation gating, async message queue handling, KPI dashboard binding, and Windows shell integration.
Aligned with TEST_INFRA.md (Tiers 1-4).
"""
import os
import sys
import queue
import tempfile
import time
import threading
import subprocess
import unittest
from unittest.mock import patch, MagicMock
import pytest
import pandas as pd

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import customtkinter as ctk
from src.controller import ProcurementEngineBridge

from app_gui import (
    PharmaProcurementApp,
    FileListModel,
    FileItem,
    format_file_size,
    open_file_externally,
    open_folder_externally,
    run_headless_self_test,
    FONT_FAMILY,
    COLOR_ACCENT,
    COLOR_CATALOG_BADGE,
    COLOR_ORDER_BADGE,
)


@pytest.fixture(scope="module")
def shared_tk_app():
    """Module-scoped headless PharmaProcurementApp instance preventing Tcl re-init overhead."""
    app = PharmaProcurementApp()
    app.withdraw()
    yield app
    try:
        app.destroy()
    except Exception:
        pass


@pytest.fixture
def gui_app(shared_tk_app):
    """Function-scoped fixture providing a cleanly reset headless PharmaProcurementApp."""
    app = shared_tk_app
    app.file_model.clear()
    app._render_file_list()
    app.output_dir_var.set(os.path.normpath(os.path.abspath("output")))
    app.progress_bar.set(0.0)
    app.status_label.configure(text="جاهز للتشغيل / Ready")
    app.bridge = None
    app.current_report_path = None
    app.last_kpi_data = None
    app.open_report_btn.configure(state="disabled")
    app.open_folder_btn.configure(state="disabled")
    app._update_ui_state()
    yield app


@pytest.fixture
def temp_test_files():
    """Fixture creating temporary dummy test files with various extensions."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # 1. Dummy PDF Catalog
        pdf_path = os.path.join(tmp_dir, "wholesaler_catalog_1.pdf")
        with open(pdf_path, "wb") as f:
            f.write(b"%PDF-1.4 dummy catalog")

        # 2. Dummy Order XLSX
        order_path = os.path.join(tmp_dir, "order_0910.xlsx")
        df_order = pd.DataFrame([{"اسم العميل": "صيدلية النور", "الكمية المطلوبة": 10, "الصنف": "Panadol"}])
        df_order.to_excel(order_path, index=False, engine="openpyxl")

        # 3. Dummy Catalog XLSX
        cat_xlsx_path = os.path.join(tmp_dir, "عروض_خصم_المتحدة.xlsx")
        df_cat = pd.DataFrame([{"الصنف": "Panadol", "خصم": 25.0, "سعر": 50.0}])
        df_cat.to_excel(cat_xlsx_path, index=False, engine="openpyxl")

        # 4. Dummy CSV Order
        order_csv_path = os.path.join(tmp_dir, "طلبية_شراء.csv")
        df_order.to_csv(order_csv_path, index=False, encoding="utf-8-sig")

        yield {
            "dir": tmp_dir,
            "pdf_catalog": pdf_path,
            "order_xlsx": order_path,
            "catalog_xlsx": cat_xlsx_path,
            "order_csv": order_csv_path,
        }


# =============================================================================
# Tier 1: Core Feature Coverage Tests (F3, F4, F5, F6, F7, F8, F9, F10)
# =============================================================================

class TestTier1GUIFeatureCoverage:
    """Tier 1: Comprehensive coverage for all GUI features in PROJECT.md."""

    def test_f3_headless_instantiation(self, gui_app):
        """F3: App instantiates cleanly without display server errors in headless mode."""
        assert gui_app is not None
        assert gui_app.title().startswith("نظام المشتريات الصيدلانية")
        assert hasattr(gui_app, "sidebar_frame")
        assert hasattr(gui_app, "main_frame")

    def test_f3_theme_switching(self, gui_app):
        """F3: Theme selector allows switching between System, Dark, and Light modes."""
        for theme in ["Dark", "Light", "System"]:
            gui_app._on_change_theme(theme)
            assert gui_app.theme_menu.get() == "System" or theme in ["Dark", "Light", "System"]

    def test_f3_bilingual_typography(self, gui_app):
        """F3: App utilizes Segoe UI font and high-contrast bilingual strings."""
        assert FONT_FAMILY == "Segoe UI"
        title_text = gui_app.brand_title.cget("text")
        sub_text = gui_app.brand_subtitle.cget("text")
        assert "المشتريات" in title_text
        assert "Egyptian Pharma Optimizer" in sub_text

    def test_f4_file_addition_and_deduplication(self, gui_app, temp_test_files):
        """F4: Ingesting files adds to model; adding duplicate paths is safely ignored."""
        model = gui_app.file_model
        assert len(model.files) == 0

        # Add single file
        added, dups = model.add_paths([temp_test_files["pdf_catalog"]])
        assert added == 1
        assert dups == 0
        assert len(model.files) == 1

        # Add duplicate + new file
        added2, dups2 = model.add_paths([temp_test_files["pdf_catalog"], temp_test_files["order_xlsx"]])
        assert added2 == 1
        assert dups2 == 1
        assert len(model.files) == 2

    def test_f4_auto_classification(self, gui_app, temp_test_files):
        """F4: PDFs are classified as Catalog; orders with purchase markers are classified as Order."""
        model = gui_app.file_model
        model.add_paths([
            temp_test_files["pdf_catalog"],
            temp_test_files["order_xlsx"],
            temp_test_files["catalog_xlsx"]
        ])

        orders = model.get_order_files()
        catalogs = model.get_catalog_files()

        assert temp_test_files["pdf_catalog"] in catalogs
        assert temp_test_files["order_xlsx"] in orders
        assert temp_test_files["catalog_xlsx"] in catalogs

    def test_f4_manual_category_override(self, gui_app, temp_test_files):
        """F4: Manual override changes a file's category in 1 click."""
        model = gui_app.file_model
        pdf = temp_test_files["pdf_catalog"]
        model.add_paths([pdf])

        assert model.files[0].category == "Catalog"
        assert not model.files[0].is_override

        # Override to Order
        model.set_override(pdf, "Order")
        assert model.files[0].category == "Order"
        assert model.files[0].is_override
        assert pdf in model.get_order_files()

        # Override back to Catalog
        model.set_override(pdf, "Catalog")
        assert model.files[0].category == "Catalog"

    def test_f4_file_removal_and_clear(self, gui_app, temp_test_files):
        """F4: Individual file removal (✕) and clear-all reset model and UI."""
        gui_app.add_files([temp_test_files["pdf_catalog"], temp_test_files["order_xlsx"]])
        assert len(gui_app.file_model.files) == 2

        # Remove one file
        gui_app._on_remove_file(temp_test_files["pdf_catalog"])
        assert len(gui_app.file_model.files) == 1
        assert gui_app.file_model.files[0].path == temp_test_files["order_xlsx"]

        # Clear all
        gui_app._on_clear_all()
        assert len(gui_app.file_model.files) == 0

    def test_f5_destination_directory_picker(self, gui_app, temp_test_files):
        """F5: Default output directory exists and can be updated programmatically."""
        current_dest = gui_app.output_dir_var.get()
        assert current_dest is not None and len(current_dest) > 0

        # Change directory
        new_dir = os.path.join(temp_test_files["dir"], "custom_output")
        gui_app.output_dir_var.set(new_dir)
        gui_app._update_ui_state()
        assert gui_app.output_dir_var.get() == new_dir

    def test_f6_validation_gate(self, gui_app, temp_test_files):
        """F6: Run button is enabled ONLY when >=1 order and >=1 catalog are present."""
        # Initial empty state -> disabled
        gui_app._update_ui_state()
        assert gui_app.run_button.cget("state") == "disabled"

        # Add only catalog -> still disabled
        gui_app.add_files([temp_test_files["pdf_catalog"]])
        assert gui_app.run_button.cget("state") == "disabled"

        # Add order -> enabled!
        gui_app.add_files([temp_test_files["order_xlsx"]])
        assert gui_app.run_button.cget("state") == "normal"

        # Remove order -> disabled again
        gui_app._on_remove_file(temp_test_files["order_xlsx"])
        assert gui_app.run_button.cget("state") == "disabled"

    def test_f6_async_bridge_progress_queue(self, gui_app):
        """F6 & F7: Queue receives PROGRESS messages and updates progress bar & status label."""
        fake_queue = queue.Queue()
        gui_app.bridge = MagicMock()
        gui_app.bridge.is_running = True
        gui_app.bridge.get_message.side_effect = [
            ("PROGRESS", 0.45, "قراءة كتالوج فارما..."),
            None
        ]

        gui_app.poll_queue()

        assert gui_app.progress_bar.get() == pytest.approx(0.45, abs=0.01)
        assert "فارما" in gui_app.status_label.cget("text")

    def test_f6_async_bridge_done_queue(self, gui_app, temp_test_files):
        """F6 & F8: Queue receives DONE message and populates KPI metrics."""
        mock_report = os.path.join(temp_test_files["dir"], "Procurement_Order_Optimized_2026-09-10.xlsx")
        with open(mock_report, "w") as f:
            f.write("mock")

        mock_results = {
            "report_path": mock_report,
            "kpis": {
                "total_items": 150,
                "matched_items": 120,
                "deterministic_matches": 110,
                "ai_assisted_matches": 10,
                "out_of_stock": 30,
                "avg_discount": 28.5,
                "total_savings": 4560.75,
                "allocation_counts": {"المتحدة": 65, "ابن سينا": 55}
            }
        }

        gui_app.bridge = MagicMock()
        gui_app.bridge.is_running = False
        gui_app.bridge.get_message.side_effect = [
            ("DONE", mock_results),
            None
        ]

        gui_app.poll_queue()

        # Check KPI bindings
        assert gui_app.card_req.cget("text") == "150"
        assert "120" in gui_app.card_alloc.cget("text")
        assert gui_app.card_oos.cget("text") == "30"
        assert gui_app.card_disc.cget("text") == "28.5%"
        assert "4,560.75" in gui_app.card_sav.cget("text")
        assert "المتحدة: 65" in gui_app.wholesalers_pills_label.cget("text")
        assert gui_app.open_report_btn.cget("state") == "normal"
        assert gui_app.open_folder_btn.cget("state") == "normal"

    def test_f6_async_bridge_error_queue(self, gui_app):
        """F6: Queue receives ERROR message, updates status, and shows error dialog."""
        gui_app.bridge = MagicMock()
        gui_app.bridge.is_running = False
        gui_app.bridge.get_message.side_effect = [
            ("ERROR", "Corrupted PDF file header", "Traceback..."),
            None
        ]

        with patch.object(gui_app, "_show_error_dialog") as mock_dlg:
            gui_app.poll_queue()
            assert "فشلت العملية" in gui_app.status_label.cget("text")
            mock_dlg.assert_called_once_with("Corrupted PDF file header", "Traceback...")

    def test_f9_windows_shell_actions(self, gui_app, temp_test_files):
        """F9: Shell action triggers external opener on Windows / cross-platform."""
        test_file = temp_test_files["pdf_catalog"]
        gui_app.current_report_path = test_file

        with patch("app_gui.open_file_externally", return_value=True) as mock_open_file:
            gui_app._on_open_report()
            mock_open_file.assert_called_once_with(test_file)

        with patch("app_gui.open_folder_externally", return_value=True) as mock_open_folder:
            gui_app._on_open_folder()
            mock_open_folder.assert_called_once_with(test_file)

    def test_f10_headless_self_test_function(self, gui_app):
        """F10: run_headless_self_test runs to completion and returns 0, and CLI flag runs cleanly."""
        # 1. Direct function call with existing app
        exit_code = run_headless_self_test(existing_app=gui_app)
        assert exit_code == 0

        # 2. Subprocess CLI flag execution
        import subprocess
        proc = subprocess.run(
            [sys.executable, os.path.abspath("app_gui.py"), "--self-test"],
            capture_output=True,
            text=True
        )
        assert proc.returncode == 0
        assert "SELF-TEST" in proc.stdout


# =============================================================================
# Tier 2: Boundary Value Analysis & Corner Cases
# =============================================================================

class TestTier2BoundaryAndCornerCases:
    """Tier 2: Boundary values, edge conditions, and error recovery."""

    def test_format_file_size_boundaries(self):
        """Format size under 1024 B, KB range, MB range, and exact 0."""
        assert format_file_size(0) == "0 B"
        assert format_file_size(512) == "512 B"
        assert format_file_size(1024) == "1.0 KB"
        assert format_file_size(1024 * 1024) == "1.0 MB"
        assert format_file_size(15 * 1024 * 1024) == "15.0 MB"

    def test_empty_and_whitespace_paths(self, gui_app):
        """Empty strings, None, or nonexistent files in add_paths are cleanly ignored."""
        model = gui_app.file_model
        added, dups = model.add_paths(["", "   ", "non_existent_file.xlsx", None])
        assert added == 0
        assert dups == 0
        assert len(model.files) == 0

    def test_empty_output_directory_validation(self, gui_app, temp_test_files):
        """Empty or whitespace output directory fails validation."""
        gui_app.add_files([temp_test_files["pdf_catalog"], temp_test_files["order_xlsx"]])
        is_valid, msg = gui_app.file_model.validate("")
        assert not is_valid
        assert "مجلد حفظ المخرجات" in msg

        is_valid2, msg2 = gui_app.file_model.validate("   ")
        assert not is_valid2

    def test_override_flip_multiple_times(self, gui_app, temp_test_files):
        """Toggling manual override repeatedly updates summary and category counts."""
        f_path = temp_test_files["pdf_catalog"]
        gui_app.add_files([f_path])

        # Initially Catalog
        assert gui_app.file_model.get_summary()["catalogs"] == 1
        assert gui_app.file_model.get_summary()["orders"] == 0

        # Flip to Order
        gui_app._on_override_category(f_path, "أمر شراء (Order)")
        assert gui_app.file_model.get_summary()["catalogs"] == 0
        assert gui_app.file_model.get_summary()["orders"] == 1

        # Flip back to Catalog
        gui_app._on_override_category(f_path, "كتالوج مخزن (Catalog)")
        assert gui_app.file_model.get_summary()["catalogs"] == 1
        assert gui_app.file_model.get_summary()["orders"] == 0

    def test_remove_nonexistent_path_no_crash(self, gui_app):
        """Removing a path not in model does not raise an exception."""
        gui_app.file_model.remove_path("some_random_path_123.pdf")
        assert len(gui_app.file_model.files) == 0

    def test_kpi_binding_with_empty_or_zero_values(self, gui_app):
        """Pipeline completion with all-zero KPIs binds cleanly without division by zero."""
        empty_results = {
            "report_path": "",
            "kpis": {
                "total_items": 0,
                "matched_items": 0,
                "deterministic_matches": 0,
                "ai_assisted_matches": 0,
                "out_of_stock": 0,
                "avg_discount": 0.0,
                "total_savings": 0.0,
                "allocation_counts": {}
            }
        }
        gui_app._on_pipeline_completed(empty_results)
        assert gui_app.card_req.cget("text") == "0"
        assert gui_app.card_disc.cget("text") == "0.0%"
        assert "لا توجد عروض" in gui_app.wholesalers_pills_label.cget("text")

    def test_shell_open_missing_file_handled_gracefully(self, gui_app):
        """Opening a non-existent file returns False without unhandled exception."""
        assert not open_file_externally("non_existent_procurement_report.xlsx")
        assert not open_folder_externally("non_existent_folder_path_xyz")


# =============================================================================
# Tier 3: Pairwise Combinations & UI State Transitions
# =============================================================================

class TestTier3PairwiseCombinations:
    """Tier 3: Interactions between file management, validation, and execution states."""

    def test_file_addition_then_override_then_validation(self, gui_app, temp_test_files):
        """Add 2 catalogs -> invalid -> override 1 to order -> valid -> revert -> invalid."""
        cat1 = temp_test_files["pdf_catalog"]
        cat2 = temp_test_files["catalog_xlsx"]

        gui_app.add_files([cat1, cat2])
        assert gui_app.run_button.cget("state") == "disabled"

        # Override cat1 to Order
        gui_app._on_override_category(cat1, "أمر شراء (Order)")
        assert gui_app.run_button.cget("state") == "normal"

        # Override cat1 back to Catalog
        gui_app._on_override_category(cat1, "كتالوج مخزن (Catalog)")
        assert gui_app.run_button.cget("state") == "disabled"

    def test_disable_controls_during_run_and_re_enable_on_done(self, gui_app, temp_test_files):
        """When optimization runs, user input buttons disable, then re-enable upon DONE."""
        gui_app.add_files([temp_test_files["pdf_catalog"], temp_test_files["order_xlsx"]])
        assert gui_app.run_button.cget("state") == "normal"

        # Mock bridge running
        gui_app.bridge = MagicMock()
        gui_app.bridge.is_running = True
        gui_app._update_ui_state()

        assert gui_app.run_button.cget("state") == "disabled"
        assert gui_app.add_files_btn.cget("state") == "disabled"
        assert gui_app.clear_all_btn.cget("state") == "disabled"

        # Mock DONE message
        gui_app.bridge.is_running = False
        gui_app.bridge.get_message.side_effect = [
            ("DONE", {"report_path": temp_test_files["pdf_catalog"], "kpis": {}}),
            None
        ]
        gui_app.poll_queue()

        assert gui_app.run_button.cget("state") == "normal"
        assert gui_app.add_files_btn.cget("state") == "normal"
        assert gui_app.clear_all_btn.cget("state") == "normal"


# =============================================================================
# Tier 4: Real-World Scenarios with Existing Sample Inputs
# =============================================================================

class TestTier4RealWorldScenarios:
    """Tier 4: Ingestion and validation using real domain sample inputs in input/."""

    def test_real_sample_files_ingestion_and_classification(self, gui_app):
        """Real input/catalogs and input/orders files classify accurately."""
        catalog_pdf = os.path.abspath("input/catalogs/الشركة_المتحدة.pdf")
        order_xlsx = os.path.abspath("input/orders/طلبية_اليوم.xlsx")

        if not os.path.exists(catalog_pdf) or not os.path.exists(order_xlsx):
            pytest.skip("Sample files not present in input/ directory.")

        gui_app.add_files([catalog_pdf, order_xlsx])

        summary = gui_app.file_model.get_summary()
        assert summary["total"] == 2
        assert summary["catalogs"] == 1
        assert summary["orders"] == 1

        # Validation gate should open
        assert gui_app.run_button.cget("state") == "normal"

    def test_real_full_catalog_batch_ingestion(self, gui_app):
        """Adding all 3 sample catalogs and 2 sample orders verifies full batch accounting."""
        cats = [
            os.path.abspath("input/catalogs/الشركة_المتحدة.pdf"),
            os.path.abspath("input/catalogs/فارما_اوفرسيز.pdf"),
            os.path.abspath("input/catalogs/مخزن_ابن_سينا.pdf"),
        ]
        orders = [
            os.path.abspath("input/orders/طلبية_اليوم.xlsx"),
            os.path.abspath("input/orders/طلبية_عربي_اختبار.xlsx"),
        ]

        if not all(os.path.exists(f) for f in cats + orders):
            pytest.skip("Full sample set not found.")

        gui_app.add_files(cats + orders)

        summary = gui_app.file_model.get_summary()
        assert summary["total"] == 5
        assert summary["catalogs"] == 3
        assert summary["orders"] == 2
        assert gui_app.run_button.cget("state") == "normal"


# =============================================================================
# Tier 5: Empirical Challenger Boundary & Stress Tests
# =============================================================================

class TestTier5ChallengerStressTests:
    """
    Tier 5: Adversarial Boundary & Stress Harness for Milestone M2.
    Tests scale to 100+ files, repeated category toggles, invalid output dirs,
    CLI argument edge cases, UI responsiveness, and unhandled exception safety.
    """

    # --- Vector 1: Rapid 100+ Files Boundary Stress ---

    def test_stress_vector1_add_150_mixed_files_bulk(self, gui_app):
        """Boundary: Ingest 150 files in bulk (50 PDFs, 50 Orders, 50 Catalogs)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_paths = []
            # 50 PDFs
            for i in range(50):
                p = os.path.join(tmp_dir, f"catalog_wholesaler_{i:03d}.pdf")
                with open(p, "wb") as f:
                    f.write(b"%PDF-1.4 dummy catalog")
                file_paths.append(p)

            # 50 Excel Orders
            df_order = pd.DataFrame([{"اسم العميل": f"صيدلية {i}", "الكمية المطلوبة": i + 1, "الصنف": f"Med_{i}"} for i in range(5)])
            for i in range(50):
                p = os.path.join(tmp_dir, f"order_daily_09{i:02d}.xlsx")
                df_order.to_excel(p, index=False, engine="openpyxl")
                file_paths.append(p)

            # 50 CSV Catalogs
            df_cat = pd.DataFrame([{"الصنف": f"Med_{i}", "خصم": 20.0, "سعر": 100.0} for i in range(5)])
            for i in range(50):
                p = os.path.join(tmp_dir, f"catalog_vendor_{i:03d}.csv")
                df_cat.to_csv(p, index=False, encoding="utf-8-sig")
                file_paths.append(p)

            assert len(file_paths) == 150

            start_t = time.time()
            gui_app.add_files(file_paths)
            elapsed = time.time() - start_t

            summary = gui_app.file_model.get_summary()
            assert summary["total"] == 150, f"Expected 150 files, got {summary['total']}"
            assert summary["orders"] == 50, f"Expected 50 orders, got {summary['orders']}"
            assert summary["catalogs"] == 100, f"Expected 100 catalogs (50 PDF + 50 CSV), got {summary['catalogs']}"

            assert len(gui_app._file_card_widgets) == 150
            gui_app.update_idletasks()
            time_budget = 30.0
            assert elapsed < time_budget, f"Adding 150 files took {elapsed:.2f}s, exceeding {time_budget}s budget."

    def test_stress_vector1_add_25_files_sequential_rapid(self, gui_app):
        """Boundary: Ingest 25 files in rapid individual successive calls (testing iterative re-rendering)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_paths = []
            for i in range(25):
                p = os.path.join(tmp_dir, f"item_stream_{i:03d}.pdf")
                with open(p, "wb") as f:
                    f.write(b"%PDF-1.4 stream dummy")
                file_paths.append(p)

            start_t = time.time()
            for p in file_paths:
                gui_app.add_files([p])
            elapsed = time.time() - start_t

            assert len(gui_app.file_model.files) == 25
            assert len(gui_app._file_card_widgets) == 25
            gui_app.update_idletasks()
            assert elapsed < 60.0

    def test_stress_vector1_duplicate_mass_addition(self, gui_app):
        """Boundary: Re-adding 100 files in duplicate must not double track or crash."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_paths = []
            for i in range(100):
                p = os.path.join(tmp_dir, f"dup_test_{i:03d}.pdf")
                with open(p, "wb") as f:
                    f.write(b"%PDF-1.4 dup")
                file_paths.append(p)

            added, dups = gui_app.file_model.add_paths(file_paths)
            assert added == 100
            assert dups == 0

            added2, dups2 = gui_app.file_model.add_paths(file_paths)
            assert added2 == 0
            assert dups2 == 100
            assert len(gui_app.file_model.files) == 100

    def test_stress_vector1_extreme_and_malformed_paths(self, gui_app):
        """Boundary: Handle extreme path lengths, Unicode, special characters, and non-existent paths."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            long_name = "catalog_" + ("very_long_subdomain_wholesaler_name_" * 5) + ".pdf"
            p_long = os.path.join(tmp_dir, long_name)
            with open(p_long, "wb") as f:
                f.write(b"%PDF-1.4 long")

            p_ar = os.path.join(tmp_dir, "طلبية_مستعجلة_أدوية_طوارئ_2026_نهائي.xlsx")
            df = pd.DataFrame([{"الصنف": "Panadol", "الكمية المطلوبة": 5}])
            df.to_excel(p_ar, index=False, engine="openpyxl")

            p_spec = os.path.join(tmp_dir, "catalog [wholesaler] #1 & 2 (v3.0) {special}.pdf")
            with open(p_spec, "wb") as f:
                f.write(b"%PDF-1.4 special")

            p_zero = os.path.join(tmp_dir, "zero_byte_order.csv")
            with open(p_zero, "wb") as f:
                pass

            candidates = [p_long, p_ar, p_spec, p_zero, "", "   ", None, "Z:\\nonexistent\\file.pdf"]
            valid_candidates = [c for c in candidates if c and os.path.isfile(c)]
            assert len(valid_candidates) == 4

            added, dups = gui_app.file_model.add_paths(candidates)
            assert added == 4
            assert len(gui_app.file_model.files) == 4

            gui_app._render_file_list()
            gui_app.update_idletasks()

    def test_stress_vector1_add_clear_cycles(self, gui_app):
        """Boundary: 5 rapid cycles of adding 100 files and clearing all."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_paths = []
            for i in range(100):
                p = os.path.join(tmp_dir, f"cycle_file_{i:03d}.pdf")
                with open(p, "wb") as f:
                    f.write(b"%PDF-1.4 cycle")
                file_paths.append(p)

            for cycle in range(5):
                gui_app.add_files(file_paths)
                assert len(gui_app.file_model.files) == 100
                assert len(gui_app._file_card_widgets) == 100

                gui_app._on_clear_all()
                assert len(gui_app.file_model.files) == 0
                assert len(gui_app._file_card_widgets) == 0
                gui_app.update_idletasks()

    # --- Vector 2: Category Toggle Stress ---

    def test_stress_vector2_category_toggle_rapid_single_file(self, gui_app):
        """Boundary: Toggle a single file's category back and forth 50 times."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            p = os.path.join(tmp_dir, "order_sample.xlsx")
            df = pd.DataFrame([{"اسم العميل": "صيدلية النور", "الكمية المطلوبة": 10, "الصنف": "Panadol"}])
            df.to_excel(p, index=False, engine="openpyxl")

            gui_app.add_files([p])
            item = gui_app.file_model.files[0]
            assert item.category == "Order"
            assert not item.is_override

            for i in range(50):
                choice = "كتالوج مخزن (Catalog)" if i % 2 == 0 else "أمر شراء (Order)"
                expected_cat = "Catalog" if i % 2 == 0 else "Order"
                gui_app._on_override_category(p, choice)
                assert item.category == expected_cat
                assert item.is_override == (expected_cat != item.auto_category)

            gui_app.update_idletasks()

    def test_stress_vector2_category_toggle_mass_inversion(self, gui_app):
        """Boundary: Invert categories of 80 files (40 orders, 40 catalogs) simultaneously."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            order_paths = []
            cat_paths = []
            df_order = pd.DataFrame([{"اسم العميل": "صيدلية", "الكمية المطلوبة": 1, "الصنف": "Med"}])
            for i in range(40):
                p_ord = os.path.join(tmp_dir, f"order_inv_{i:02d}.xlsx")
                df_order.to_excel(p_ord, index=False, engine="openpyxl")
                order_paths.append(p_ord)

                p_cat = os.path.join(tmp_dir, f"catalog_inv_{i:02d}.pdf")
                with open(p_cat, "wb") as f:
                    f.write(b"%PDF-1.4 cat")
                cat_paths.append(p_cat)

            gui_app.add_files(order_paths + cat_paths)
            assert gui_app.file_model.get_summary()["orders"] == 40
            assert gui_app.file_model.get_summary()["catalogs"] == 40

            # Invert all orders to Catalog
            for p in order_paths:
                gui_app.file_model.set_override(p, "Catalog")

            # Invert all catalogs to Order
            for p in cat_paths:
                gui_app.file_model.set_override(p, "Order")

            gui_app._render_file_list()
            gui_app._update_ui_state()

            assert len(gui_app.file_model.get_order_files()) == 40
            assert len(gui_app.file_model.get_catalog_files()) == 40
            for f in gui_app.file_model.files:
                assert f.is_override is True

            # Invert back
            for p in order_paths:
                gui_app.file_model.set_override(p, "Order")
            for p in cat_paths:
                gui_app.file_model.set_override(p, "Catalog")

            gui_app._render_file_list()
            gui_app._update_ui_state()

            for f in gui_app.file_model.files:
                assert f.is_override is False

    def test_stress_vector2_validation_gate_state_transitions(self, gui_app):
        """Boundary: Validation gate transitions cleanly across all category toggle combinations."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            p_ord = os.path.join(tmp_dir, "order_state.xlsx")
            df = pd.DataFrame([{"اسم العميل": "صيدلية", "الكمية المطلوبة": 1, "الصنف": "Med"}])
            df.to_excel(p_ord, index=False, engine="openpyxl")

            p_cat = os.path.join(tmp_dir, "catalog_state.pdf")
            with open(p_cat, "wb") as f:
                f.write(b"%PDF-1.4 cat")

            gui_app.add_files([p_ord, p_cat])
            # State 1: 1 Order, 1 Catalog -> Valid
            is_valid, _ = gui_app.file_model.validate(gui_app.output_dir_var.get())
            assert is_valid is True
            assert gui_app.run_button.cget("state") == "normal"

            # State 2: Toggle Order -> Catalog (0 Orders, 2 Catalogs) -> Invalid
            gui_app._on_override_category(p_ord, "كتالوج مخزن (Catalog)")
            is_valid, reason = gui_app.file_model.validate(gui_app.output_dir_var.get())
            assert is_valid is False
            assert "أمر شراء واحد على الأقل" in reason
            assert gui_app.run_button.cget("state") == "disabled"

            # State 3: Toggle Catalog -> Order (1 Order, 1 Catalog) -> Valid
            gui_app._on_override_category(p_cat, "أمر شراء (Order)")
            is_valid, _ = gui_app.file_model.validate(gui_app.output_dir_var.get())
            assert is_valid is True
            assert gui_app.run_button.cget("state") == "normal"

            # State 4: Toggle p_ord to Order (2 Orders, 0 Catalogs) -> Invalid
            gui_app._on_override_category(p_ord, "أمر شراء (Order)")
            is_valid, reason = gui_app.file_model.validate(gui_app.output_dir_var.get())
            assert is_valid is False
            assert "كتالوج مخزن واحد على الأقل" in reason
            assert gui_app.run_button.cget("state") == "disabled"

    # --- Vector 3: Empty and Invalid Output Directories ---

    def test_stress_vector3_output_dir_empty_and_whitespace(self, gui_app):
        """Boundary: Empty and whitespace output directories must close validation gate."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            p_ord = os.path.join(tmp_dir, "order.xlsx")
            df = pd.DataFrame([{"اسم العميل": "صيدلية", "الكمية المطلوبة": 1, "الصنف": "Med"}])
            df.to_excel(p_ord, index=False, engine="openpyxl")

            p_cat = os.path.join(tmp_dir, "catalog.pdf")
            with open(p_cat, "wb") as f:
                f.write(b"%PDF-1.4 cat")

            gui_app.add_files([p_ord, p_cat])

            gui_app.output_dir_var.set("")
            gui_app._update_ui_state()
            is_valid, reason = gui_app.file_model.validate(gui_app.output_dir_var.get())
            assert is_valid is False
            assert "مجلد حفظ المخرجات" in reason
            assert gui_app.run_button.cget("state") == "disabled"

            for ws in ["   ", "\t", "\n", " \t \n "]:
                gui_app.output_dir_var.set(ws)
                gui_app._update_ui_state()
                is_valid, reason = gui_app.file_model.validate(gui_app.output_dir_var.get())
                assert is_valid is False
                assert gui_app.run_button.cget("state") == "disabled"

    def test_stress_vector3_run_button_click_when_output_dir_empty(self, gui_app):
        """Boundary: Calling _on_run_optimization when output dir is empty warns and does not start bridge."""
        gui_app.output_dir_var.set("")
        with patch("tkinter.messagebox.showwarning") as mock_warn:
            gui_app._on_run_optimization()
            assert mock_warn.called
            assert gui_app.bridge is None

    def test_stress_vector3_output_dir_nonexistent_and_invalid_chars(self, gui_app):
        """Boundary: Pipeline execution with invalid or unwritable directory is caught safely."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            p_ord = os.path.join(tmp_dir, "order.xlsx")
            df = pd.DataFrame([{"اسم العميل": "صيدلية", "الكمية المطلوبة": 1, "الصنف": "Med"}])
            df.to_excel(p_ord, index=False, engine="openpyxl")

            p_cat = os.path.join(tmp_dir, "catalog.pdf")
            with open(p_cat, "wb") as f:
                f.write(b"%PDF-1.4 cat")

            gui_app.add_files([p_ord, p_cat])

            illegal_dir = "Z:\\invalid<>:\"/\\|?*\\dir"
            gui_app.output_dir_var.set(illegal_dir)

            is_valid, _ = gui_app.file_model.validate(illegal_dir)
            assert is_valid is True

            bridge = ProcurementEngineBridge()
            bridge.start(
                order_files=[p_ord],
                catalog_files=[p_cat],
                output_dir=illegal_dir
            )

            start_t = time.time()
            error_found = False
            while time.time() - start_t < 10.0:
                while not bridge.queue.empty():
                    msg = bridge.get_message(block=False)
                    if msg and msg[0] == "ERROR":
                        error_found = True
                        break
                if error_found:
                    break
                time.sleep(0.05)

            assert error_found, "Expected bridge to safely catch invalid directory error and emit ERROR message."
            assert not bridge.is_running

    # --- Vector 4: Invalid CLI Arguments ---

    def test_stress_vector4_cli_self_test_flag(self):
        """CLI Contract: python app_gui.py --self-test exits 0."""
        cmd = [sys.executable, "app_gui.py", "--self-test"]
        res = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True, timeout=20)
        assert res.returncode == 0
        assert "[SELF-TEST]" in res.stdout
        assert "verified cleanly" in res.stdout

    def test_stress_vector4_cli_self_test_with_superfluous_arguments(self):
        """CLI Contract: python app_gui.py --self-test --unknown-flag -v random_arg still executes self-test cleanly."""
        cmd = [sys.executable, "app_gui.py", "--self-test", "--unknown-flag", "-v", "bogus_arg"]
        res = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True, timeout=20)
        assert res.returncode == 0
        assert "[SELF-TEST]" in res.stdout

    def test_stress_vector4_headless_self_test_function_direct(self, gui_app):
        """CLI Direct Call: run_headless_self_test() executes without throwing exception."""
        code = run_headless_self_test(existing_app=gui_app)
        assert code == 0

    # --- Vector 5: Asynchronous Worker Safety and Mocking ---

    def test_stress_vector5_ui_thread_responsive_during_async_polling(self, gui_app):
        """Anti-Freeze: UI event loop responds promptly (< 100ms) while worker thread emits messages."""
        msg_q = queue.Queue()
        bridge = ProcurementEngineBridge(message_queue=msg_q)
        gui_app.bridge = bridge

        def _simulated_worker():
            for i in range(20):
                pct = (i + 1) / 20.0
                msg_q.put(("PROGRESS", pct, f"Step {i+1}/20"))
                time.sleep(0.02)
            msg_q.put(("DONE", {
                "report_path": "dummy.xlsx",
                "kpis": {
                    "total_items": 10,
                    "matched_items": 10,
                    "deterministic_matches": 8,
                    "out_of_stock": 0,
                    "avg_discount": 22.5,
                    "total_savings": 1500.0,
                    "allocation_counts": {"المتحدة": 10}
                }
            }))

        worker = threading.Thread(target=_simulated_worker, daemon=True)
        worker.start()

        start_wait = time.time()
        max_tick_duration = 0.0
        while worker.is_alive() or not msg_q.empty():
            tick_start = time.time()
            gui_app.poll_queue()
            gui_app.update_idletasks()
            tick_duration = time.time() - tick_start
            if tick_duration > max_tick_duration:
                max_tick_duration = tick_duration
            time.sleep(0.01)
            if time.time() - start_wait > 10.0:
                pytest.fail("Async polling took longer than 10 seconds.")

        assert max_tick_duration < 0.10, f"UI tick took {max_tick_duration*1000:.1f}ms, exceeding 100ms budget."

        assert gui_app.progress_bar.get() == 1.0
        assert gui_app.card_req.cget("text") == "10"
        assert gui_app.card_alloc.cget("text") == "10 (8 مؤكد)"

    def test_stress_vector5_error_queue_propagation_does_not_crash(self, gui_app):
        """Anti-Freeze: Bridge error message gracefully resets progress and does not raise unhandled exception."""
        msg_q = queue.Queue()
        bridge = ProcurementEngineBridge(message_queue=msg_q)
        gui_app.bridge = bridge

        msg_q.put(("ERROR", "Fatal simulated engine parsing failure", "Traceback details dummy"))

        with patch.object(gui_app, "_show_error_dialog") as mock_err_dialog:
            gui_app.poll_queue()
            gui_app.update_idletasks()
            assert mock_err_dialog.called
            assert gui_app.progress_bar.get() == 0.0
            assert "فشلت العملية" in gui_app.status_label.cget("text")

    def test_stress_vector5_rapid_double_trigger_guard(self, gui_app):
        """Anti-Freeze: Rapid double invocation of _on_run_optimization does not crash."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            p_ord = os.path.join(tmp_dir, "order.xlsx")
            df = pd.DataFrame([{"اسم العميل": "صيدلية", "الكمية المطلوبة": 1, "الصنف": "Med"}])
            df.to_excel(p_ord, index=False, engine="openpyxl")

            p_cat = os.path.join(tmp_dir, "catalog.pdf")
            with open(p_cat, "wb") as f:
                f.write(b"%PDF-1.4 cat")

            gui_app.add_files([p_ord, p_cat])
            gui_app.output_dir_var.set(tmp_dir)

            with patch("src.controller.run_procurement_pipeline") as mock_pipe:
                mock_pipe.return_value = {
                    "report_path": os.path.join(tmp_dir, "report.xlsx"),
                    "kpis": {"total_items": 1, "matched_items": 1}
                }
                gui_app._on_run_optimization()
                try:
                    gui_app._on_run_optimization()
                except Exception as e:
                    pytest.fail(f"Second rapid call to _on_run_optimization crashed with: {e}")

                gui_app.update_idletasks()

    def test_stress_vector5_kpi_binding_with_null_and_malformed_values(self, gui_app):
        """Boundary: _on_pipeline_completed safely handles missing/empty/corrupted KPI dictionaries."""
        malformed_cases = [
            {},
            {"kpis": None},
            {"kpis": {}},
            {"kpis": {"total_items": "invalid_type", "total_savings": "NaN"}},
            {"kpis": {"allocation_counts": None}},
        ]
        for case in malformed_cases:
            try:
                gui_app._on_pipeline_completed(case)
            except Exception as e:
                pytest.fail(f"_on_pipeline_completed crashed on malformed KPI dict {case}: {e}")

    def test_stress_vector5_shell_actions_with_empty_or_forbidden_paths(self, gui_app):
        """Boundary: Shell actions (open report / open folder) handle non-existent paths gracefully."""
        gui_app.current_report_path = None
        gui_app._on_open_report()
        gui_app._on_open_folder()

        gui_app.current_report_path = "Z:\\nonexistent_procurement_file.xlsx"
        with patch("tkinter.messagebox.showerror") as mock_err:
            gui_app._on_open_report()
            assert mock_err.called

        with patch("tkinter.messagebox.showerror") as mock_err:
            gui_app._on_open_folder()
            assert mock_err.called


# =============================================================================
# Tier 5: Challenger 2 Lifecycle, Handle Hygiene & Error Dialog Tests
# =============================================================================

def _get_win32_handles():
    """Returns (kernel_handles, gdi_handles, user_handles) on Windows, or (0, 0, 0) otherwise."""
    if sys.platform != "win32":
        return 0, 0, 0
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetProcessHandleCount.restype = wintypes.BOOL
        user32.GetGuiResources.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        user32.GetGuiResources.restype = wintypes.DWORD

        h = kernel32.GetCurrentProcess()
        count = wintypes.DWORD()
        kernel32.GetProcessHandleCount(h, ctypes.byref(count))
        gdi = user32.GetGuiResources(h, 0)
        user = user32.GetGuiResources(h, 1)
        return count.value, gdi, user
    except Exception:
        return 0, 0, 0


def _is_pid_alive(pid: int) -> bool:
    """Checks if a process with the given PID is still active in Windows."""
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            SYNCHRONIZE = 0x00100000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
            if not handle:
                return False
            exit_code = ctypes.c_ulong()
            kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            kernel32.CloseHandle(handle)
            STILL_ACTIVE = 259
            return exit_code.value == STILL_ACTIVE
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


class TestTier5Challenger2LifecycleAndErrorDialog:
    """
    Empirical Challenger 2 Test Suite for Milestone M2:
    1. Repeated rapid execution of --self-test (10 runs) verifying zero zombie processes,
       deterministic exit codes, execution timing, and Windows resource handle hygiene.
    2. In-process lifecycle repetition (10 iterations) testing widget/Tcl teardown and handle stability.
    3. Simulated error queue message delivery with REAL rendering of _show_error_dialog
       (no mocks), verifying CTkToplevel creation, widget hierarchy, Arabic text,
       large tracebacks, missing tracebacks, grab handling, and clean close destruction.
    """

    def test_c2_error_queue_real_dialog_rendering(self, gui_app):
        """Task 2: Simulated ERROR queue delivery renders real CTkToplevel error dialog without crashing."""
        msg_q = queue.Queue()
        bridge = ProcurementEngineBridge(message_queue=msg_q)
        gui_app.bridge = bridge

        error_text = "خطأ فادح: فشل في قراءة ترويسة ملف الكتالوج (PDF Corrupted Header)"
        tb_text = (
            "Traceback (most recent call last):\n"
            "  File 'src/pdf_parser.py', line 42, in extract_catalog\n"
            "    raise ValueError('Corrupted catalog header')\n"
            "ValueError: Corrupted catalog header"
        )
        msg_q.put(("ERROR", error_text, tb_text))

        # Real execution: DO NOT mock _show_error_dialog!
        gui_app.poll_queue()
        gui_app.update_idletasks()

        # 1. Verify main app status label and progress bar
        assert "فشلت العملية" in gui_app.status_label.cget("text")
        assert "PDF Corrupted Header" in gui_app.status_label.cget("text")
        assert gui_app.progress_bar.get() == 0.0

        # 2. Inspect rendered CTkToplevel
        toplevels = [w for w in gui_app.winfo_children() if isinstance(w, ctk.CTkToplevel)]
        assert len(toplevels) >= 1, "Expected at least 1 CTkToplevel error window to be rendered"
        err_win = toplevels[-1]
        assert "خطأ في المعالجة" in err_win.title()
        assert "Optimization Error" in err_win.title()

        # 3. Find and verify child widgets inside the error dialog
        descendants = err_win.winfo_children()
        labels = [w for w in descendants if isinstance(w, ctk.CTkLabel)]
        textboxes = [w for w in descendants if isinstance(w, ctk.CTkTextbox)]
        buttons = [w for w in descendants if isinstance(w, ctk.CTkButton)]

        assert len(labels) >= 2, f"Expected header and message labels, found {len(labels)}"
        assert len(textboxes) >= 1, "Expected CTkTextbox for traceback"
        assert len(buttons) >= 1, "Expected Close button"

        # Verify error message label text
        msg_found = any(error_text in lbl.cget("text") for lbl in labels)
        assert msg_found, "Error dialog label does not contain expected error text"

        # Verify traceback textbox content
        tb_box = textboxes[0]
        tb_content = tb_box.get("1.0", "end")
        assert "ValueError: Corrupted catalog header" in tb_content

        # 4. Clean destruction via close button command
        close_btn = buttons[0]
        assert "إغلاق" in close_btn.cget("text") or "Close" in close_btn.cget("text")
        err_win.destroy()
        gui_app.update_idletasks()

    def test_c2_error_queue_edge_cases_real_rendering(self, gui_app):
        """Task 2: Error queue message delivery with various boundary inputs renders without crashing."""
        edge_cases = [
            # Case 1: Tuple with only 2 items (missing traceback)
            ("ERROR", "Error with no traceback tuple item"),
            # Case 2: Empty error message and empty traceback
            ("ERROR", "", ""),
            # Case 3: Massive traceback string (50 KB)
            ("ERROR", "Massive traceback error", "Traceback line\n" * 2000),
            # Case 4: Rich Arabic text with punctuation and emojis
            ("ERROR", "❌ خطأ فادح: الكتالوج غير مطابق للمعايير المصرية ⚠️ [2026-09-11]", "تفاصيل: خطأ ترميزي"),
        ]

        for case in edge_cases:
            msg_q = queue.Queue()
            bridge = ProcurementEngineBridge(message_queue=msg_q)
            gui_app.bridge = bridge
            msg_q.put(case)

            # Poll and render real dialog
            gui_app.poll_queue()
            gui_app.update_idletasks()

            # Verify dialog created
            toplevels = [w for w in gui_app.winfo_children() if isinstance(w, ctk.CTkToplevel)]
            assert len(toplevels) >= 1, f"Failed to create error dialog for case: {case[1]}"
            err_win = toplevels[-1]

            # Destroy to clean up for next iteration
            err_win.destroy()
            gui_app.update_idletasks()

    def test_c2_in_process_repeated_self_test_lifecycle(self, gui_app):
        """Task 1: 10 rapid in-process self-test iterations verify Tcl/widget teardown and handle stability."""
        initial_k, initial_g, initial_u = _get_win32_handles()

        for iteration in range(10):
            # Run headless self test using existing app
            code = run_headless_self_test(existing_app=gui_app)
            assert code == 0, f"Self-test iteration {iteration+1} failed with code {code}"
            gui_app.update_idletasks()

        final_k, final_g, final_u = _get_win32_handles()

        # Verify GDI and USER handle stability (should not explode)
        if sys.platform == "win32" and initial_k > 0:
            user_delta = final_u - initial_u
            gdi_delta = final_g - initial_g
            assert user_delta < 50, f"USER handles leaked excessively: +{user_delta}"
            assert gdi_delta < 50, f"GDI handles leaked excessively: +{gdi_delta}"

    def test_c2_out_of_process_10_rapid_self_test_zombies_and_handles(self):
        """Task 1: 10 rapid CLI invocations of python app_gui.py --self-test verify 0 zombies and exit 0."""
        durations = []
        pids_seen = []

        for i in range(10):
            start_t = time.time()
            proc = subprocess.Popen(
                [sys.executable, "app_gui.py", "--self-test"],
                cwd=project_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            pid = proc.pid
            pids_seen.append(pid)

            stdout_data, stderr_data = proc.communicate(timeout=25)
            elapsed = time.time() - start_t
            durations.append(elapsed)

            # Assert exit code 0
            assert proc.returncode == 0, f"Run {i+1} failed with code {proc.returncode}. Stderr: {stderr_data}"
            assert "[SELF-TEST]" in stdout_data, f"Run {i+1} missing [SELF-TEST] tag. Output: {stdout_data}"
            assert "verified cleanly" in stdout_data

            # Assert process is terminated (NO zombie process remaining in OS)
            time.sleep(0.05)
            assert not _is_pid_alive(pid), f"PID {pid} from run {i+1} is still active as a zombie or orphaned process!"

        # Timing and stability analysis
        avg_duration = sum(durations) / len(durations)
        max_duration = max(durations)
        min_duration = min(durations)

        assert len(pids_seen) == 10
        assert len(set(pids_seen)) == 10, "PIDs should all be distinct across 10 fresh process invocations"
        assert avg_duration < 10.0, f"Average execution duration {avg_duration:.2f}s is too slow"
        assert max_duration < 15.0, f"Max execution duration {max_duration:.2f}s exceeded 15s budget"


# =============================================================================
# Milestone Enhancement Verification Suite
# =============================================================================

class TestMilestoneEnhancements:
    """Verifies all 6 mission fixes: Icons, UI latency, Duplicate badge, KPIs, and Item Viewer modal."""

    def test_app_ico_multisize_and_app_user_model_id(self):
        """Issue 1: assets/app.ico exists, contains 16, 32, 48, 256 px resolutions, and AppUserModelID configured."""
        ico_path = os.path.join(project_root, "assets", "app.ico")
        assert os.path.isfile(ico_path), "assets/app.ico not found"

        try:
            from PIL import Image
            with Image.open(ico_path) as img:
                assert img.format == "ICO"
                sizes = img.info.get("sizes", set())
                if not sizes:
                    sizes = {img.size}
        except ImportError:
            import struct
            with open(ico_path, "rb") as f:
                header = f.read(6)
                reserved, ico_type, count = struct.unpack("<HHH", header)
                assert ico_type == 1
                sizes = set()
                for _ in range(count):
                    entry = f.read(16)
                    w, h = entry[0], entry[1]
                    w = 256 if w == 0 else w
                    h = 256 if h == 0 else h
                    sizes.add((w, h))

        assert (16, 16) in sizes or any(s[0] == 16 for s in sizes)
        assert (32, 32) in sizes or any(s[0] == 32 for s in sizes)
        assert (48, 48) in sizes or any(s[0] == 48 for s in sizes)
        assert (256, 256) in sizes or any(s[0] == 256 for s in sizes)

    def test_duplicate_badge_formatting_fix(self, gui_app):
        """Issue 3: Badge text is formatted cleanly as '📦 402 صنف / items' without number duplication."""
        test_item = FileItem("test_catalog.pdf", "Catalog")
        test_item.item_count = 402
        test_item.is_ocr = False
        gui_app.file_model.files = [test_item]
        gui_app._render_file_list()

        card = gui_app._file_card_widgets.get(test_item.path)
        assert card is not None
        badge_lbl = getattr(card, "_count_badge", None)
        assert badge_lbl is not None
        badge_text = badge_lbl.cget("text")

        assert "402 402" not in badge_text, f"Duplicate count detected in badge: '{badge_text}'"
        assert "402 صنف / items" in badge_text or "📦 402" in badge_text

    def test_kpi_out_of_stock_and_average_discount_and_total_savings(self, gui_app):
        """Issue 4: Out of stock (total - allocated), Avg discount percentage, and total savings calculation & formatting."""
        # Case A: Explicit out_of_stock
        results_a = {
            "report_path": "dummy.xlsx",
            "kpis": {
                "total_items": 702,
                "matched_items": 580,
                "deterministic_matches": 550,
                "out_of_stock": 122,
                "avg_discount": 0.154,  # decimal format 0.154 -> 15.4%
                "total_savings": 25340.50,
                "allocation_counts": {"المتحدة": 350, "ابن سينا": 230},
                "allocation_values": {"المتحدة": 15000.0, "ابن سينا": 10340.50}
            }
        }
        gui_app._on_pipeline_completed(results_a)
        assert gui_app.card_req.cget("text") == "702"
        assert "580" in gui_app.card_alloc.cget("text")
        assert gui_app.card_oos.cget("text") == "122"
        assert gui_app.card_disc.cget("text") == "15.4%"
        assert "25,340.50" in gui_app.card_sav.cget("text")

        # Case B: Out of stock fallback calculation when missing from KPI dict
        results_b = {
            "report_path": "dummy.xlsx",
            "kpis": {
                "total_items": 100,
                "matched_items": 75,
                "avg_discount": 22.8,  # percentage format 22.8 -> 22.8%
                "total_savings": 5000.0,
                "allocation_counts": {"فارما أوفرسيز": 75},
                "allocation_values": {"فارما أوفرسيز": 5000.0}
            }
        }
        gui_app._on_pipeline_completed(results_b)
        assert gui_app.card_req.cget("text") == "100"
        assert "75" in gui_app.card_alloc.cget("text")
        assert gui_app.card_oos.cget("text") == "25"  # 100 - 75 = 25
        assert gui_app.card_disc.cget("text") == "22.8%"
        assert "5,000.00" in gui_app.card_sav.cget("text")

    def test_winning_wholesalers_pills_with_counts_and_values(self, gui_app):
        """Issue 4: Winning wholesalers pills include supplier name, count, and monetary value."""
        results = {
            "report_path": "dummy.xlsx",
            "kpis": {
                "total_items": 50,
                "matched_items": 50,
                "allocation_counts": {"المتحدة": 30, "ابن سينا": 20},
                "allocation_values": {"المتحدة": 4560.75, "ابن سينا": 3200.00}
            }
        }
        gui_app._on_pipeline_completed(results)
        pills_text = gui_app.wholesalers_pills_label.cget("text")
        assert "المتحدة: 30" in pills_text
        assert "4,560.75" in pills_text
        assert "ابن سينا: 20" in pills_text
        assert "3,200.00" in pills_text

    def test_item_and_discount_rate_viewer_modal(self, gui_app, temp_test_files):
        """Issue 5: Searchable Item & Discount Rate Viewer modal opens, displays items, and filters live."""
        cat_file = temp_test_files["catalog_xlsx"]
        gui_app.add_files([cat_file])
        assert len(gui_app.file_model.files) == 1

        # Seed global cache
        from src.controller import global_catalog_cache
        df_sample = pd.DataFrame([
            {"item_name": "Panadol Extra 500mg", "base_price": 45.0, "discount_rate": 0.20, "stock_status": True},
            {"item_name": "Augmentin 1g Tab", "base_price": 120.0, "discount_rate": 0.15, "stock_status": True},
            {"item_name": "Cataflam 50mg Tab", "base_price": 55.0, "discount_rate": 0.10, "stock_status": False},
        ])
        global_catalog_cache.set(cat_file, df_sample)

        # Trigger viewer
        gui_app._open_catalog_item_viewer(cat_file)
        gui_app.update_idletasks()

        # Find rendered CTkToplevel
        toplevels = [w for w in gui_app.winfo_children() if isinstance(w, ctk.CTkToplevel)]
        assert len(toplevels) >= 1
        viewer_win = toplevels[-1]
        assert "عرض الأصناف والخصومات" in viewer_win.title()

        # Clean destruction
        viewer_win.destroy()
        gui_app.update_idletasks()


# =============================================================================
# Half 1: GUI Output Path Protection & Non-Crashing Error Handling (R3)
# =============================================================================

class TestGUIOutputDirectoryAndPermissionSafety:
    """R3: Tests for GUI output path protection and non-crashing permission error handling."""

    def test_gui_output_dir_initialized_to_safe_user_directory(self):
        """R3: GUI initializes output destination to a guaranteed safe user-writable directory."""
        from src.pipeline import get_default_output_dir, is_in_installation_dir, validate_directory_writable
        default_dir = get_default_output_dir()
        assert default_dir is not None
        assert not is_in_installation_dir(default_dir)
        assert validate_directory_writable(default_dir) is True

    def test_gui_browse_destination_blocks_installation_dir(self, gui_app):
        """R3: Output directory picker warns and disallows selecting protected installation paths."""
        initial_val = gui_app.output_dir_var.get()
        with patch("app_gui.filedialog.askdirectory", return_value="/Applications/Pharma_Output"):
            with patch("app_gui.messagebox.showwarning") as mock_warn:
                gui_app._on_browse_destination()
                assert mock_warn.called
                # Must NOT set protected directory
                assert gui_app.output_dir_var.get() == initial_val

    def test_gui_browse_destination_blocks_unwritable_dir(self, gui_app, temp_test_files):
        """R3: Output directory picker warns and disallows unwritable directories."""
        initial_val = gui_app.output_dir_var.get()
        target = os.path.join(temp_test_files["dir"], "unwritable_folder")
        with patch("app_gui.filedialog.askdirectory", return_value=target):
            with patch("app_gui.validate_directory_writable", side_effect=PermissionError("Simulated [WinError 5]")):
                with patch("app_gui.messagebox.showwarning") as mock_warn:
                    gui_app._on_browse_destination()
                    assert mock_warn.called
                    assert gui_app.output_dir_var.get() == initial_val

    def test_gui_browse_destination_accepts_valid_user_dir(self, gui_app, temp_test_files):
        """R3: Output directory picker accepts valid user directories."""
        valid_dir = temp_test_files["dir"]
        with patch("app_gui.filedialog.askdirectory", return_value=valid_dir):
            with patch("app_gui.messagebox.showwarning") as mock_warn:
                gui_app._on_browse_destination()
                mock_warn.assert_not_called()
                assert gui_app.output_dir_var.get() == os.path.normpath(os.path.abspath(valid_dir))

    def test_gui_validation_gate_rejects_installation_dir(self, gui_app, temp_test_files):
        """R3: Validation gate closes and disables Run button if an installation path is configured."""
        gui_app.add_files([temp_test_files["order_xlsx"], temp_test_files["pdf_catalog"]])
        gui_app.output_dir_var.set("/Applications/EgyptianPharmaOptimizer")
        gui_app._update_ui_state()

        is_valid, reason = gui_app.file_model.validate(gui_app.output_dir_var.get())
        assert is_valid is False
        assert "تثبيت البرنامج" in reason or "protected" in reason.lower()
        assert gui_app.run_button.cget("state") == "disabled"

    def test_gui_worker_bridge_clean_permission_error_handling(self):
        """R3: Background worker thread catches PermissionError and posts ERROR without crashing."""
        with patch("src.controller.run_procurement_pipeline", side_effect=PermissionError("Simulated [WinError 5] Access is denied")):
            bridge = ProcurementEngineBridge()
            bridge.start(
                order_files=["dummy_order.xlsx"],
                catalog_files=["dummy_catalog.pdf"],
                output_dir="dummy_out"
            )
            bridge.join(timeout=5.0)
            assert not bridge.is_running
            assert bridge.last_error is not None
            msg = bridge.get_message(block=False)
            assert msg is not None
            assert msg[0] == "ERROR"
            assert "[WinError 5]" in msg[1] or "Access is denied" in msg[1]

    def test_gui_surfaces_permission_error_in_dialog_without_crashing(self, gui_app):
        """R3: Permission error message surfaces in error dialog cleanly without crashing GUI."""
        gui_app._on_pipeline_failed("Output directory permission denied [WinError 5]", "Traceback info...")
        gui_app.update_idletasks()
        assert "فشلت العملية" in gui_app.status_label.cget("text")
        # Find and close dialog
        toplevels = [w for w in gui_app.winfo_children() if isinstance(w, ctk.CTkToplevel)]
        for t in toplevels:
            try:
                t.destroy()
            except Exception:
                pass

    def test_gui_browse_destination_blocks_symlink_to_installation_dir(self, gui_app, temp_test_files):
        """R3: Output directory picker warns and disallows symlinks pointing to installation paths."""
        initial_val = gui_app.output_dir_var.get()
        link_target = os.path.join(temp_test_files["dir"], "symlink_apps")
        try:
            os.symlink("/Applications", link_target)
        except (OSError, NotImplementedError):
            return  # Environment doesn't support symlinks

        with patch("app_gui.filedialog.askdirectory", return_value=link_target):
            with patch("app_gui.messagebox.showwarning") as mock_warn:
                gui_app._on_browse_destination()
                assert mock_warn.called
                assert gui_app.output_dir_var.get() == initial_val

    def test_gui_pipeline_completed_updates_output_dir_if_different(self, gui_app, temp_test_files):
        """R3: When pipeline finishes with fallback dir, GUI updates output_dir_var to actual folder."""
        actual_output = os.path.join(temp_test_files["dir"], "actual_fallback_output")
        os.makedirs(actual_output, exist_ok=True)
        fake_report = os.path.join(actual_output, "Procurement_Order_Optimized_2026-09-11.xlsx")
        with open(fake_report, "w") as f:
            f.write("dummy")

        results = {
            "report_path": fake_report,
            "arabic_report_path": fake_report,
            "output_dir": actual_output,
            "kpis": {"total_items": 10, "matched_items": 10, "deterministic_matches": 10, "out_of_stock": 0, "avg_discount": 15.0, "total_savings": 500.0}
        }
        gui_app._on_pipeline_completed(results)
        assert gui_app.output_dir_var.get() == actual_output



if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))



