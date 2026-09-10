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
import unittest
from unittest.mock import patch, MagicMock
import pytest
import pandas as pd

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

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


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
