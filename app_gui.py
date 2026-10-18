# -*- coding: utf-8 -*-
from __future__ import annotations
"""
Egyptian Pharmaceutical Procurement Optimizer - Modern Windows 11 Desktop GUI.
CustomTkinter graphical interface with bilingual typography (Arabic & English),
asynchronous thread-safe worker bridge, file management, and post-run KPI analytics.
"""
import os
import sys
import queue
import threading
import logging

import datetime
import subprocess
import traceback
from typing import Optional, List, Dict, Tuple

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox

# Configure Windows AppUserModelID for crisp taskbar icon resolution and grouping
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("EgyptianPharma.ProcurementOptimizer.App.1.8")
    except Exception:
        pass

try:
    from src.controller import (
        classify_files,
        ProcurementEngineBridge,
        inspect_catalog_counts,
        inspect_single_catalog,
        reread_catalog_with_ocr,
        global_catalog_cache,
    )
    from src.pipeline import (
        run_procurement_pipeline,
        PipelineExecutionError,
        get_default_output_dir,
        resolve_safe_output_dir,
        validate_directory_writable,
        is_in_installation_dir,
    )
except ImportError:
    from controller import (
        classify_files,
        ProcurementEngineBridge,
        inspect_catalog_counts,
        inspect_single_catalog,
        reread_catalog_with_ocr,
        global_catalog_cache,
    )
    from pipeline import (
        run_procurement_pipeline,
        PipelineExecutionError,
        get_default_output_dir,
        resolve_safe_output_dir,
        validate_directory_writable,
        is_in_installation_dir,
    )


logger = logging.getLogger("PharmaGUI")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# Appearance and Theme Configurations
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

# Theme Palette
COLOR_ACCENT = "#1F4E79"        # Windows 11 Deep Navy Accent
COLOR_ACCENT_HOVER = "#163A5C"
COLOR_CATALOG_BADGE = "#0284C7"  # Sky Blue for Wholesaler Catalogs
COLOR_ORDER_BADGE = "#059669"    # Emerald Green for Purchase Orders
COLOR_WARN_BADGE = "#D97706"     # Amber Warning
COLOR_DANGER = "#DC2626"         # Rose Danger Red
COLOR_DANGER_HOVER = "#B91C1C"
COLOR_SUCCESS = "#10B981"
COLOR_SURFACE_DARK = "#1E293B"
COLOR_SURFACE_LIGHT = "#F1F5F9"
COLOR_CARD_DARK = "#2D3748"
COLOR_CARD_LIGHT = "#FFFFFF"

# Font definitions using Segoe UI
FONT_FAMILY = "Segoe UI"


_FONT_CACHE = {}


def get_font(size: int = 12, weight: str = "normal") -> ctk.CTkFont:
    """Returns a cached Segoe UI CTkFont instance."""
    key = (size, weight)
    font = _FONT_CACHE.get(key)
    if font is None:
        font = ctk.CTkFont(family=FONT_FAMILY, size=size, weight=weight)
        _FONT_CACHE[key] = font
    return font


def format_file_size(size_bytes: int) -> str:
    """Formats file size into human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def open_file_externally(file_path: str) -> bool:
    """Opens a file with the system default application (e.g. Excel)."""
    if not file_path or not os.path.exists(file_path):
        return False
    norm_path = os.path.normpath(os.path.abspath(file_path))
    try:
        if sys.platform == "win32":
            os.startfile(norm_path)
            return True
        elif sys.platform == "darwin":
            subprocess.run(["open", norm_path], check=False)
            return True
        else:
            subprocess.run(["xdg-open", norm_path], check=False)
            return True
    except Exception as exc:
        logger.error(f"Failed to open file {norm_path}: {exc}")
        return False


def open_folder_externally(file_path: str) -> bool:
    """Opens the directory containing the file and highlights the file on Windows."""
    if not file_path:
        return False
    target_path = os.path.normpath(os.path.abspath(file_path))
    target_dir = os.path.dirname(target_path) if os.path.isfile(target_path) else target_path
    if not os.path.exists(target_dir):
        return False

    try:
        if sys.platform == "win32":
            if os.path.isfile(target_path):
                subprocess.run(["explorer", f"/select,{target_path}"], check=False)
            else:
                os.startfile(target_dir)
            return True
        elif sys.platform == "darwin":
            subprocess.run(["open", "-R", target_path] if os.path.isfile(target_path) else ["open", target_dir], check=False)
            return True
        else:
            subprocess.run(["xdg-open", target_dir], check=False)
            return True
    except Exception as exc:
        logger.error(f"Failed to open folder for {target_path}: {exc}")
        return False


class FileItem:
    """Represents an ingested input file in the GUI model."""
    def __init__(self, path: str, category: str):
        self.path = os.path.normpath(os.path.abspath(path))
        self.filename = os.path.basename(self.path)
        self.ext = os.path.splitext(self.filename)[1].lower()
        self.category = category  # "Order" or "Catalog"
        self.auto_category = category
        self.is_override = False
        try:
            self.size_bytes = os.path.getsize(self.path) if os.path.isfile(self.path) else 0
        except OSError:
            self.size_bytes = 0
        self.size_str = format_file_size(self.size_bytes)
        # Milestone 1: Catalog Inspection & OCR State
        self.item_count: Optional[int] = None
        self.is_ocr: bool = False
        self.ocr_running: bool = False
        self.ocr_status_msg: str = ""


    def set_category(self, new_category: str):
        """Sets category and tracks if user manually overridden."""
        self.category = new_category
        self.is_override = (self.category != self.auto_category)


class FileListModel:
    """Model tracking selected files, classification, manual overrides, and validation."""
    def __init__(self):
        self.files: List[FileItem] = []

    def add_paths(self, file_paths: List[str]) -> Tuple[int, int]:
        """
        Adds paths with deduplication and auto-classification.
        Returns (added_count, duplicate_count).
        """
        added = 0
        duplicate = 0
        existing_paths = {f.path for f in self.files}

        # Filter valid files and non-duplicates
        candidates = []
        for p in file_paths:
            if not p or not os.path.isfile(p):
                continue
            norm = os.path.normpath(os.path.abspath(p))
            if norm in existing_paths:
                duplicate += 1
            else:
                candidates.append(norm)
                existing_paths.add(norm)

        if not candidates:
            return 0, duplicate

        # Run 3-tier classification
        classification = classify_files(candidates)
        order_set = set(classification.get('orders', []))
        catalog_set = set(classification.get('catalogs', []))
        avg_discounts_set = set(classification.get('avg_discounts', []))

        for cand in candidates:
            if cand in avg_discounts_set:
                self.files.append(FileItem(cand, "AvgDiscounts"))
                added += 1
            elif cand in order_set:
                self.files.append(FileItem(cand, "Order"))
                added += 1
            elif cand in catalog_set:
                self.files.append(FileItem(cand, "Catalog"))
                added += 1
            else:
                logger.info(f"Skipping unclassified or ignored file: {cand}")

        return added, duplicate

    def remove_path(self, path: str):
        """Removes a file by its normalized path."""
        norm = os.path.normpath(os.path.abspath(path))
        self.files = [f for f in self.files if f.path != norm]

    def clear(self):
        """Clears all tracked files."""
        self.files.clear()

    def set_override(self, path: str, category: str):
        """Manually sets the category for a specific file."""
        norm = os.path.normpath(os.path.abspath(path))
        for f in self.files:
            if f.path == norm:
                f.set_category(category)
                break

    def get_order_files(self) -> List[str]:
        """Returns list of paths classified as purchase orders."""
        return [f.path for f in self.files if f.category == "Order"]

    def get_catalog_files(self) -> List[str]:
        """Returns list of paths classified as wholesaler catalogs."""
        return [f.path for f in self.files if f.category == "Catalog"]

    def get_avg_discounts_files(self) -> List[str]:
        """Returns list of paths classified as average discounts reference datasets."""
        return [f.path for f in self.files if f.category == "AvgDiscounts"]

    def get_summary(self) -> Dict[str, int]:
        """Returns dictionary of counts."""
        orders = len(self.get_order_files())
        catalogs = len(self.get_catalog_files())
        avg_discounts = len(self.get_avg_discounts_files())
        return {
            "total": len(self.files),
            "orders": orders,
            "catalogs": catalogs,
            "avg_discounts": avg_discounts,
        }

    def validate(self, output_dir: str) -> Tuple[bool, str]:
        """
        Validates if optimization can be run.
        Requires at least 1 order file, at least 1 catalog file, and a valid destination directory.
        """
        orders = self.get_order_files()
        catalogs = self.get_catalog_files()

        if not orders and not catalogs:
            return False, "يرجى إضافة ملفات الكتالوجات وأوامر الشراء للبدء / Add catalogs and orders to begin"
        if not orders:
            return False, "يرجى إضافة أمر شراء واحد على الأقل (.xlsx / .csv) / At least 1 order required"
        if not catalogs:
            return False, "يرجى إضافة كتالوج مخزن واحد على الأقل (.pdf / .xlsx) / At least 1 catalog required"
        if not output_dir or not str(output_dir).strip():
            return False, "يرجى تحديد مجلد حفظ المخرجات / Output directory must be specified"
        if is_in_installation_dir(output_dir):
            return False, "المجلد المحدد يقع ضمن ملفات تثبيت البرنامج المحمية / Selected directory is in protected installation path"

        return True, "جاهز للبدء والتوزيع / Ready to optimize"


class PharmaProcurementApp(ctk.CTk):
    """
    Modern Windows 11 CustomTkinter Desktop Application.
    Bilingual (Arabic/English) UI with Segoe UI typography, asynchronous worker,
    multi-file management, real-time progress, and post-run KPI analytics.
    """

    def __init__(self):
        super().__init__()

        self.title("نظام المشتريات الصيدلانية v1.8 / Egyptian Pharma Procurement Optimizer v1.8")
        self.geometry("1200x780")
        self.minsize(980, 660)

        # Set App Icon if present
        icon_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "assets", "app.ico"))
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        # Data & Model State
        self.file_model = FileListModel()
        self.bridge: Optional[ProcurementEngineBridge] = None
        self.current_report_path: Optional[str] = None
        self.last_kpi_data: Optional[dict] = None
        self._file_card_widgets: Dict[str, ctk.CTkFrame] = {}

        # Default Output Destination: Guaranteed safe user-writable directory outside installation path
        default_out = get_default_output_dir()
        self.output_dir_var = tk.StringVar(value=default_out)

        # Layout Setup
        self._setup_grid_layout()
        self._build_sidebar()
        self._build_main_panel()

        # Milestone 1: OCR & Inspection Async Queue & Threads
        self._ocr_queue: queue.Queue = queue.Queue()
        self._active_ocr_threads: Dict[str, threading.Thread] = {}

        # Update initial validation and state
        self._update_ui_state()

        # Start OCR queue poller
        self.after(100, self._poll_ocr_queue)


    def _setup_grid_layout(self):
        """Configures main responsive grid layout."""
        self.grid_columnconfigure(0, weight=0, minsize=320)  # Left Sidebar
        self.grid_columnconfigure(1, weight=1)               # Main Content
        self.grid_rowconfigure(0, weight=1)

    # -------------------------------------------------------------------------
    # Left Sidebar / Action Panel
    # -------------------------------------------------------------------------
    def _build_sidebar(self):
        """Builds left sidebar with branding, destination picker, run button, and theme switcher."""
        self.sidebar_frame = ctk.CTkFrame(self, corner_radius=0, width=320)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        self.sidebar_frame.grid_rowconfigure(7, weight=1)  # Push theme toggle to bottom

        # Branding Header
        self.brand_title = ctk.CTkLabel(
            self.sidebar_frame,
            text="نظام المشتريات الصيدلانية",
            font=get_font(18, "bold"),
            anchor="w"
        )
        self.brand_title.grid(row=0, column=0, padx=20, pady=(20, 2), sticky="ew")

        self.brand_subtitle = ctk.CTkLabel(
            self.sidebar_frame,
            text="Egyptian Pharma Optimizer",
            font=get_font(13, "normal"),
            text_color=("gray40", "gray70"),
            anchor="w"
        )
        self.brand_subtitle.grid(row=1, column=0, padx=20, pady=(0, 15), sticky="ew")

        # Separator 1
        sep1 = ctk.CTkFrame(self.sidebar_frame, height=2, fg_color=("gray80", "gray30"))
        sep1.grid(row=2, column=0, padx=20, pady=5, sticky="ew")

        # Destination Directory Picker Section
        dest_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="📁 مجلد حفظ المخرجات / Output Folder",
            font=get_font(12, "bold"),
            anchor="w"
        )
        dest_label.grid(row=3, column=0, padx=20, pady=(15, 6), sticky="ew")

        dest_container = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        dest_container.grid(row=4, column=0, padx=20, pady=0, sticky="ew")
        dest_container.grid_columnconfigure(0, weight=1)

        self.dest_entry = ctk.CTkEntry(
            dest_container,
            textvariable=self.output_dir_var,
            font=get_font(11),
            placeholder_text="مسار مجلد الحفظ..."
        )
        self.dest_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.dest_browse_btn = ctk.CTkButton(
            dest_container,
            text="استعراض...",
            width=75,
            font=get_font(11, "bold"),
            command=self._on_browse_destination
        )
        self.dest_browse_btn.grid(row=0, column=1, sticky="e")

        # Separator 2
        sep2 = ctk.CTkFrame(self.sidebar_frame, height=2, fg_color=("gray80", "gray30"))
        sep2.grid(row=5, column=0, padx=20, pady=20, sticky="ew")

        # Primary Action Button (Run Optimization)
        self.run_button = ctk.CTkButton(
            self.sidebar_frame,
            text="بدء التحسين والتوزيع\nRun Optimization",
            font=get_font(14, "bold"),
            height=50,
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HOVER,
            command=self._on_run_optimization
        )
        self.run_button.grid(row=6, column=0, padx=20, pady=(0, 8), sticky="ew")

        # Validation Guidance Label
        self.validation_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="",
            font=get_font(11),
            text_color=("gray40", "gray60"),
            wraplength=280,
            justify="center"
        )
        self.validation_label.grid(row=7, column=0, padx=20, pady=(0, 10), sticky="n")

        # Theme Selector & Version Tag (Bottom of sidebar)
        theme_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        theme_frame.grid(row=8, column=0, padx=20, pady=(10, 15), sticky="sew")
        theme_frame.grid_columnconfigure(1, weight=1)

        theme_label = ctk.CTkLabel(
            theme_frame,
            text="🎨 المظهر / Theme:",
            font=get_font(11, "bold"),
            anchor="w"
        )
        theme_label.grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)

        self.theme_menu = ctk.CTkOptionMenu(
            theme_frame,
            values=["System", "Dark", "Light"],
            font=get_font(11),
            command=self._on_change_theme,
            width=110
        )
        self.theme_menu.grid(row=0, column=1, sticky="e", pady=4)
        self.theme_menu.set("System")

        self.update_btn = ctk.CTkButton(
            self.sidebar_frame,
            text="🔄 معالج التحديثات / Update Wizard",
            font=get_font(11, "bold"),
            fg_color=COLOR_CATALOG_BADGE,
            text_color="white",
            hover_color=("blue", "darkblue"),
            height=32,
            command=self._open_update_wizard
        )
        self.update_btn.grid(row=9, column=0, padx=20, pady=(0, 8), sticky="ew")

        app_info_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="v1.8 Windows 11 Edition • Engine Ready",
            font=get_font(9),
            text_color=("gray50", "gray50"),
            anchor="center"
        )
        app_info_label.grid(row=10, column=0, padx=20, pady=(0, 15), sticky="ew")

    # -------------------------------------------------------------------------
    # Right Main Panel
    # -------------------------------------------------------------------------
    def _build_main_panel(self):
        """Builds right main panel with toolbar, scrollable file list, progress bar, and KPI dashboard."""
        self.main_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(1, weight=1)  # File list expands

        # Top Toolbar
        self._build_toolbar()

        # Scrollable File List
        self._build_file_list()

        # Progress Section
        self._build_progress_section()

        # Post-Run KPI Dashboard Card
        self._build_kpi_dashboard()

    def _build_toolbar(self):
        """Builds multi-file selection toolbar with action buttons and badge counters."""
        self.toolbar_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.toolbar_frame.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.toolbar_frame.grid_columnconfigure(4, weight=1)

        self.add_files_btn = ctk.CTkButton(
            self.toolbar_frame,
            text="+ إضافة ملفات / Add Files",
            font=get_font(12, "bold"),
            width=160,
            command=self._on_add_files
        )
        self.add_files_btn.grid(row=0, column=0, padx=(0, 8), sticky="w")

        self.add_folder_btn = ctk.CTkButton(
            self.toolbar_frame,
            text="+ إضافة مجلد / Add Folder",
            font=get_font(12, "bold"),
            width=160,
            fg_color=("gray70", "gray30"),
            hover_color=("gray60", "gray40"),
            text_color=("black", "white"),
            command=self._on_add_folder
        )
        self.add_folder_btn.grid(row=0, column=1, padx=(0, 8), sticky="w")

        self.clear_all_btn = ctk.CTkButton(
            self.toolbar_frame,
            text="مسح الكل / Clear All",
            font=get_font(12),
            width=110,
            fg_color="transparent",
            border_width=1,
            border_color=("gray60", "gray40"),
            text_color=("gray20", "gray80"),
            hover_color=("gray85", "gray25"),
            command=self._on_clear_all
        )
        self.clear_all_btn.grid(row=0, column=2, padx=(0, 8), sticky="w")

        self.top_update_btn = ctk.CTkButton(
            self.toolbar_frame,
            text="🔄 التحديثات / Updates (v1.8)",
            font=get_font(11, "bold"),
            width=165,
            fg_color=("gray75", "gray25"),
            hover_color=("gray65", "gray35"),
            text_color=("black", "white"),
            command=self._open_update_wizard
        )
        self.top_update_btn.grid(row=0, column=3, padx=(0, 8), sticky="w")

        # File Counter Badge
        self.counter_badge = ctk.CTkLabel(
            self.toolbar_frame,
            text="0 ملفات (0 طلبية | 0 كتالوج)",
            font=get_font(12, "bold"),
            anchor="e"
        )
        self.counter_badge.grid(row=0, column=4, sticky="e")

    def _build_file_list(self):
        """Builds scrollable container displaying selected files with badges and overrides."""
        self.file_scroll_frame = ctk.CTkScrollableFrame(
            self.main_frame,
            label_text="الملفات المحددة / Selected Documents",
            label_font=get_font(13, "bold"),
            corner_radius=8
        )
        self.file_scroll_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 12))
        self.file_scroll_frame.grid_columnconfigure(0, weight=1)

        # Empty State Placeholder Label
        self.empty_label = ctk.CTkLabel(
            self.file_scroll_frame,
            text="📋 اسحب أو أضف ملفات الكتالوجات (PDF/Excel) وأوامر الشراء (Excel/CSV) للبدء\n"
                 "Select purchase orders (.xlsx) and wholesaler catalogs (.pdf, .xlsx) above",
            font=get_font(13),
            text_color=("gray50", "gray50"),
            justify="center"
        )
        self.empty_label.grid(row=0, column=0, pady=80, padx=20)

    def _build_progress_section(self):
        """Builds active progress bar and localized status feedback."""
        self.progress_container = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.progress_container.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        self.progress_container.grid_columnconfigure(0, weight=1)

        self.progress_bar = ctk.CTkProgressBar(self.progress_container, height=12)
        self.progress_bar.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self.progress_bar.set(0.0)

        self.status_label = ctk.CTkLabel(
            self.progress_container,
            text="جاهز للتشغيل / Ready",
            font=get_font(11),
            anchor="w",
            text_color=("gray30", "gray70")
        )
        self.status_label.grid(row=1, column=0, sticky="ew")

    def _build_kpi_dashboard(self):
        """Builds post-run KPI analytics card with metrics and Windows shell open actions."""
        self.kpi_frame = ctk.CTkFrame(self.main_frame, corner_radius=8)
        self.kpi_frame.grid(row=3, column=0, sticky="ew", pady=(0, 0))
        self.kpi_frame.grid_columnconfigure(0, weight=1)
        self.kpi_frame.grid_columnconfigure(1, weight=1)
        self.kpi_frame.grid_columnconfigure(2, weight=1)
        self.kpi_frame.grid_columnconfigure(3, weight=1)
        self.kpi_frame.grid_columnconfigure(4, weight=1)

        # Title and Wholesalers Badge Area
        kpi_header_frame = ctk.CTkFrame(self.kpi_frame, fg_color="transparent")
        kpi_header_frame.grid(row=0, column=0, columnspan=5, sticky="ew", padx=15, pady=(10, 6))
        kpi_header_frame.grid_columnconfigure(1, weight=1)

        self.kpi_title = ctk.CTkLabel(
            kpi_header_frame,
            text="📊 ملخص نتائج التوزيع والتحسين المالي / Optimization Summary",
            font=get_font(13, "bold"),
            anchor="w"
        )
        self.kpi_title.grid(row=0, column=0, sticky="w")

        self.wholesalers_pills_label = ctk.CTkLabel(
            kpi_header_frame,
            text="المخازن الموزع عليها: لا توجد بعد",
            font=get_font(11, "bold"),
            text_color=COLOR_CATALOG_BADGE,
            anchor="e"
        )
        self.wholesalers_pills_label.grid(row=0, column=1, sticky="e")

        # 5 KPI Metric Cards
        self.card_req = self._create_kpi_card(self.kpi_frame, 0, "إجمالي المطلوب", "Total Items", "0")
        self.card_alloc = self._create_kpi_card(self.kpi_frame, 1, "الأصناف الموزعة", "Allocated", "0", COLOR_SUCCESS)
        self.card_oos = self._create_kpi_card(self.kpi_frame, 2, "النواقص", "Out of Stock", "0", COLOR_DANGER)
        self.card_disc = self._create_kpi_card(self.kpi_frame, 3, "متوسط الخصم", "Avg Discount", "0.0%", COLOR_CATALOG_BADGE)
        self.card_sav = self._create_kpi_card(self.kpi_frame, 4, "إجمالي الوفر", "Total Savings", "0.00 ج.م", COLOR_SUCCESS)

        # Bottom Shell Action Buttons
        action_bar = ctk.CTkFrame(self.kpi_frame, fg_color="transparent")
        action_bar.grid(row=2, column=0, columnspan=5, sticky="ew", padx=15, pady=(8, 12))
        action_bar.grid_columnconfigure(0, weight=1)

        self.open_report_btn = ctk.CTkButton(
            action_bar,
            text="📄 فتح التقرير / Open Report",
            font=get_font(12, "bold"),
            fg_color=COLOR_ORDER_BADGE,
            hover_color="#047857",
            width=180,
            state="disabled",
            command=self._on_open_report
        )
        self.open_report_btn.grid(row=0, column=1, padx=(0, 10))

        self.open_folder_btn = ctk.CTkButton(
            action_bar,
            text="📁 فتح المجلد / Open Containing Folder",
            font=get_font(12, "bold"),
            fg_color=("gray70", "gray30"),
            hover_color=("gray60", "gray40"),
            text_color=("black", "white"),
            width=220,
            state="disabled",
            command=self._on_open_folder
        )
        self.open_folder_btn.grid(row=0, column=2, padx=(0, 0))

    def _create_kpi_card(self, parent, col: int, ar_label: str, en_label: str, init_val: str, val_color=None):
        """Creates a modern metric display card inside the KPI frame."""
        card = ctk.CTkFrame(parent, corner_radius=6, fg_color=("gray90", "gray20"))
        card.grid(row=1, column=col, padx=6, pady=6, sticky="nsew")

        lbl_top = ctk.CTkLabel(
            card,
            text=f"{ar_label}\n{en_label}",
            font=get_font(10),
            text_color=("gray40", "gray60")
        )
        lbl_top.pack(pady=(6, 2))

        val_label = ctk.CTkLabel(
            card,
            text=init_val,
            font=get_font(15, "bold"),
            text_color=val_color or ("black", "white")
        )
        val_label.pack(pady=(0, 6))

        return val_label

    # -------------------------------------------------------------------------
    # Event Handlers & User Actions
    # -------------------------------------------------------------------------
    def _on_change_theme(self, mode: str):
        """Changes CustomTkinter appearance mode."""
        ctk.set_appearance_mode(mode)

    def _on_browse_destination(self):
        """Opens folder picker to select destination directory."""
        initial = self.output_dir_var.get()
        if not initial or not os.path.isdir(initial) or is_in_installation_dir(initial):
            initial = get_default_output_dir()
        selected = filedialog.askdirectory(initialdir=initial, title="اختر مجلد حفظ تقرير المشتريات / Select Output Folder")
        if selected:
            norm_selected = os.path.normpath(os.path.abspath(selected))
            if is_in_installation_dir(norm_selected):
                messagebox.showwarning(
                    "تحذير مسار التثبيت / Protected Directory",
                    "لا يمكن اختيار مجلد تثبيت البرنامج لحفظ التقارير منعاً لمشاكل الصلاحيات.\n"
                    "يرجى اختيار مجلد في مجلدات المستخدم الخاصة بك (مثل سطح المكتب أو المستندات).\n\n"
                    "Cannot select application installation directory for output.\n"
                    "Please choose a user folder such as Desktop or Documents."
                )
                return
            try:
                validate_directory_writable(norm_selected)
            except (PermissionError, OSError) as exc:
                messagebox.showwarning(
                    "صلاحيات المجلد / Permission Error",
                    f"المجلد المحدد غير قابل للكتابة:\n{exc}\n\nSelected folder is not writable."
                )
                return
            self.output_dir_var.set(norm_selected)
            self._update_ui_state()

    def _on_add_files(self):
        """Opens multi-file dialog for selecting catalogs and orders."""
        file_types = [
            ("Supported Documents (PDF, Excel, CSV)", "*.pdf;*.xlsx;*.xls;*.csv"),
            ("PDF Catalogs (*.pdf)", "*.pdf"),
            ("Excel Spreadsheets (*.xlsx, *.xls)", "*.xlsx;*.xls"),
            ("CSV Files (*.csv)", "*.csv"),
            ("All Files (*.*)", "*.*"),
        ]
        selected_files = filedialog.askopenfilenames(
            title="اختر ملفات الكتالوجات وأوامر الشراء / Select Orders and Catalogs",
            filetypes=file_types
        )
        if selected_files:
            self.add_files(list(selected_files))

    def _on_add_folder(self):
        """Opens folder dialog and scans for supported documents."""
        folder = filedialog.askdirectory(title="اختر مجلد الكتالوجات أو الطلبيات / Select Folder")
        if not folder:
            return

        supported_exts = {".pdf", ".xlsx", ".xls", ".csv"}
        found_files = []
        for root, _, files in os.walk(folder):
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if (
                    ext in supported_exts
                    and not file.startswith("~$")
                    and not file.startswith("Procurement_Order_")
                    and not file.startswith("أفضل_اسعار")
                ):
                    found_files.append(os.path.join(root, file))

        if found_files:
            self.add_files(found_files)

    def add_files(self, file_paths: List[str]):
        """Adds files to model and refreshes the scrollable list."""
        added, dups = self.file_model.add_paths(file_paths)
        if added > 0:
            self._render_file_list()
            self._update_ui_state()
            try:
                self.after(50, lambda: self._async_inspect_counts(self.file_model.get_catalog_files()))
            except Exception:
                self._async_inspect_counts(self.file_model.get_catalog_files())
        else:
            self._update_ui_state()

    def _async_inspect_counts(self, file_paths: List[str]):
        """Inspects medication counts in catalogs asynchronously in parallel without freezing GUI."""
        uninspected = [
            f.path for f in self.file_model.files
            if f.category == "Catalog" and f.item_count is None and f.path in file_paths
        ]
        if not uninspected:
            return

        def _worker(paths_to_inspect):
            for p in paths_to_inspect:
                try:
                    norm, count, _ = inspect_single_catalog(p)
                    self._ocr_queue.put(("INSPECT_FILE_DONE", norm, count))
                except Exception as e:
                    logger.debug(f"Catalog inspection thread error for {p}: {e}")

        t = threading.Thread(target=_worker, args=(uninspected,), name="CatalogInspectWorker", daemon=True)
        t.start()

    def _start_ocr_reread(self, path: str):
        """Triggers on-demand Arabic OCR re-read for a specific catalog in background thread."""
        for f in self.file_model.files:
            if f.path == path:
                f.ocr_running = True
                f.ocr_status_msg = "⏳ جاري بدء المسح بـ OCR..."
                break
        self._render_file_list()

        def _worker():
            try:
                def _prog(pct, msg):
                    self._ocr_queue.put(("OCR_PROGRESS", path, pct, msg))
                ret_path, count, items = reread_catalog_with_ocr(path, progress_callback=_prog)
                self._ocr_queue.put(("OCR_DONE", ret_path, count, items))
            except Exception as e:
                logger.error(f"OCR reread error for {path}: {e}")
                self._ocr_queue.put(("OCR_ERROR", path, str(e)))

        t = threading.Thread(target=_worker, name=f"OCRWorker-{os.path.basename(path)}", daemon=True)
        self._active_ocr_threads[path] = t
        t.start()

    def _update_file_card_badge(self, path: str):
        """Updates the item count badge label on an existing card widget directly without re-rendering."""
        norm_path = os.path.normpath(os.path.abspath(path))
        target_f = None
        for f in self.file_model.files:
            if os.path.normpath(f.path) == norm_path:
                target_f = f
                break
        if not target_f or target_f.category != "Catalog":
            return

        card = self._file_card_widgets.get(target_f.path)
        if card and hasattr(card, "_count_badge"):
            if target_f.item_count is not None:
                if target_f.item_count > 0:
                    ocr_tag = " [OCR]" if target_f.is_ocr else ""
                    count_text = f"📦 {target_f.item_count} صنف / items{ocr_tag}"
                    count_color = COLOR_SUCCESS if target_f.is_ocr else COLOR_CATALOG_BADGE
                else:
                    count_text = "⚠️ 0 صنف (يحتاج OCR) / 0 items (needs OCR)"
                    count_color = COLOR_WARN_BADGE
            else:
                count_text = "⏳ جاري فحص الأصناف... / Checking count..."
                count_color = ("gray50", "gray60")
            try:
                card._count_badge.configure(text=count_text, text_color=count_color)
            except Exception:
                self._render_file_list()
        else:
            self._render_file_list()

    def _poll_ocr_queue(self):
        """Polls OCR and inspection queue without freezing GUI."""
        try:
            while True:
                msg = self._ocr_queue.get_nowait()
                m_type = msg[0]
                if m_type == "INSPECT_FILE_DONE":
                    norm_path, count = msg[1], msg[2]
                    for f in self.file_model.files:
                        if os.path.normpath(f.path) == norm_path:
                            f.item_count = count
                            break
                    self._update_file_card_badge(norm_path)
                elif m_type == "INSPECT_DONE":
                    counts = msg[1]
                    for f in self.file_model.files:
                        norm = os.path.normpath(f.path)
                        if norm in counts:
                            f.item_count = counts[norm]
                            self._update_file_card_badge(norm)
                elif m_type == "OCR_PROGRESS":
                    path, pct, status = msg[1], msg[2], msg[3]
                    for f in self.file_model.files:
                        if f.path == path:
                            f.ocr_status_msg = status
                            break
                    card = self._file_card_widgets.get(path)
                    if card and hasattr(card, "_ocr_status_lbl"):
                        try:
                            card._ocr_status_lbl.configure(text=status)
                        except Exception:
                            pass
                    try:
                        self.status_label.configure(text=f"[{os.path.basename(path)}] {status}")
                    except Exception:
                        pass
                elif m_type == "OCR_DONE":
                    path, count, items = msg[1], msg[2], msg[3]
                    for f in self.file_model.files:
                        if f.path == path:
                            f.ocr_running = False
                            f.item_count = count
                            f.is_ocr = True
                            f.ocr_status_msg = f"✓ اكتمل المسح ({count} صنف)"
                            break
                    self._active_ocr_threads.pop(path, None)
                    self._render_file_list()
                    self.status_label.configure(
                        text=f"✓ اكتمل مسح الكتالوج بـ OCR: تم التعرف على {count} صنف بنجاح! / OCR completed ({count} items)"
                    )
                elif m_type == "OCR_ERROR":
                    path, err_msg = msg[1], msg[2]
                    for f in self.file_model.files:
                        if f.path == path:
                            f.ocr_running = False
                            f.ocr_status_msg = f"✕ خطأ OCR"
                            break
                    self._active_ocr_threads.pop(path, None)
                    self._render_file_list()
                    self.status_label.configure(text=f"✕ فشل مسح OCR: {err_msg} / OCR failed")
        except queue.Empty:
            pass
        finally:
            self.after(100, self._poll_ocr_queue)

    def _on_clear_all(self):
        """Clears all files from model and GUI."""
        self.file_model.clear()
        self._render_file_list()
        self._update_ui_state()

    def _on_remove_file(self, path: str):
        """Removes an individual file by path."""
        self.file_model.remove_path(path)
        self._render_file_list()
        self._update_ui_state()

    def _on_override_category(self, path: str, choice: str):
        """Handles manual category override from dropdown menu."""
        # choice is "أمر شراء (Order)", "كتالوج مخزن (Catalog)", or "خصم مرجح (Avg Discounts)"
        if "Avg" in choice or "مرجح" in choice:
            new_category = "AvgDiscounts"
        elif "Order" in choice or "شراء" in choice:
            new_category = "Order"
        else:
            new_category = "Catalog"
        self.file_model.set_override(path, new_category)
        self._render_file_list()
        self._update_ui_state()

    # -------------------------------------------------------------------------
    # File List Rendering & Item Viewer Modal
    # -------------------------------------------------------------------------
    def _open_catalog_item_viewer(self, path: str):
        """Opens a modern searchable modal showing extracted catalog items and discounts."""
        norm_path = os.path.normpath(os.path.abspath(path))
        fname = os.path.basename(norm_path)
        w_raw = os.path.splitext(fname)[0]

        # Retrieve or inspect dataframe
        cached_df = global_catalog_cache.get(norm_path)
        if cached_df is None or cached_df.empty:
            _, _, cached_df = inspect_single_catalog(norm_path)

        viewer = ctk.CTkToplevel(self)
        viewer.title(f"عرض الأصناف والخصومات - {fname} / Items & Discounts Viewer")
        viewer.geometry("880x600")
        viewer.minsize(700, 450)
        viewer.transient(self)
        viewer.grab_set()

        viewer.grid_columnconfigure(0, weight=1)
        viewer.grid_rowconfigure(1, weight=1)

        # Header Frame
        header_frame = ctk.CTkFrame(viewer, fg_color="transparent")
        header_frame.grid(row=0, column=0, sticky="ew", padx=20, pady=(15, 10))
        header_frame.grid_columnconfigure(0, weight=1)

        title_lbl = ctk.CTkLabel(
            header_frame,
            text=f"📦 كتالوج: {fname}  |  المورد: {w_raw}",
            font=get_font(14, "bold"),
            anchor="w"
        )
        title_lbl.grid(row=0, column=0, sticky="w", pady=(0, 6))

        # Search Bar and Count Frame
        filter_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        filter_frame.grid(row=1, column=0, sticky="ew")
        filter_frame.grid_columnconfigure(0, weight=1)

        search_var = tk.StringVar()
        search_entry = ctk.CTkEntry(
            filter_frame,
            textvariable=search_var,
            font=get_font(12),
            placeholder_text="🔍 بحث في أسماء الأصناف أو الأسعار أو نسب الخصم... / Search items, price, discount...",
            height=34
        )
        search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        count_info_lbl = ctk.CTkLabel(
            filter_frame,
            text="0 صنف",
            font=get_font(11, "bold"),
            text_color=COLOR_CATALOG_BADGE
        )
        count_info_lbl.grid(row=0, column=1, sticky="e")

        # Table Container using ttk.Treeview
        table_frame = ctk.CTkFrame(viewer, corner_radius=6)
        table_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=5)
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(0, weight=1)

        import tkinter.ttk as ttk
        columns = ("seq", "name", "price", "discount", "status")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        
        tree.heading("seq", text="#")
        tree.heading("name", text="اسم الصنف / Medicine Name")
        tree.heading("price", text="سعر الجمهور / Public Price")
        tree.heading("discount", text="نسبة الخصم / Discount %")
        tree.heading("status", text="الحالة / Status")

        tree.column("seq", width=50, anchor="center")
        tree.column("name", width=420, anchor="w")
        tree.column("price", width=120, anchor="center")
        tree.column("discount", width=120, anchor="center")
        tree.column("status", width=100, anchor="center")

        scroll_y = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        scroll_x = ttk.Scrollbar(table_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)

        tree.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")

        # Convert cached_df to records
        raw_records = []
        if cached_df is not None and not cached_df.empty:
            for idx, r in cached_df.iterrows():
                name = str(r.get('item_name', '')).strip()
                if not name:
                    continue
                price = float(r.get('base_price', 0.0) or 0.0)
                disc = float(r.get('discount_rate', 0.0) or 0.0)
                if 0 < disc <= 1.0:
                    disc_pct = disc * 100.0
                else:
                    disc_pct = disc
                stock = "متوفر ✓" if r.get('stock_status', True) else "غير متوفر ✕"
                raw_records.append({
                    "seq": len(raw_records) + 1,
                    "name": name,
                    "price_str": f"{price:,.2f} ج.م" if price > 0 else "غير محدد",
                    "price_num": price,
                    "disc_str": f"{disc_pct:.1f}%",
                    "disc_num": disc_pct,
                    "status": stock,
                    "raw_text": f"{name} {price} {disc_pct:.1f}% {stock}".lower()
                })

        def _populate_tree(query: str = ""):
            tree.delete(*tree.get_children())
            q = query.strip().lower()
            matching_count = 0
            for item in raw_records:
                if not q or q in item["raw_text"]:
                    matching_count += 1
                    tree.insert("", "end", values=(
                        matching_count,
                        item["name"],
                        item["price_str"],
                        item["disc_str"],
                        item["status"]
                    ))
            count_info_lbl.configure(
                text=f"معروض: {matching_count} من {len(raw_records)} صنف / Showing {matching_count} of {len(raw_records)}"
            )

        def _on_search_changed(*args):
            _populate_tree(search_var.get())

        search_var.trace_add("write", _on_search_changed)
        _populate_tree("")

        # Bottom Bar
        bottom_bar = ctk.CTkFrame(viewer, fg_color="transparent")
        bottom_bar.grid(row=2, column=0, sticky="ew", padx=20, pady=(10, 15))
        bottom_bar.grid_columnconfigure(0, weight=1)

        close_btn = ctk.CTkButton(
            bottom_bar,
            text="إغلاق / Close",
            font=get_font(12, "bold"),
            width=120,
            command=viewer.destroy
        )
        close_btn.grid(row=0, column=1, sticky="e")

    # -------------------------------------------------------------------------
    # Software Update Wizard
    # -------------------------------------------------------------------------
    def _open_update_wizard(self):
        """Opens the modern Software Update Wizard modal dialog."""
        wizard = ctk.CTkToplevel(self)
        wizard.title("معالج تحديث البرنامج / Software Update Wizard")
        wizard.geometry("560x420")
        wizard.minsize(500, 380)
        wizard.transient(self)
        wizard.grab_set()

        wizard.grid_columnconfigure(0, weight=1)
        wizard.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(wizard, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 10))
        header.grid_columnconfigure(1, weight=1)

        icon_lbl = ctk.CTkLabel(header, text="🚀", font=get_font(28))
        icon_lbl.grid(row=0, column=0, rowspan=2, padx=(0, 14), sticky="nw")

        title_lbl = ctk.CTkLabel(
            header,
            text="معالج تحديث البرنامج الذكي / Software Update Wizard",
            font=get_font(15, "bold"),
            anchor="w"
        )
        title_lbl.grid(row=0, column=1, sticky="w")

        sub_lbl = ctk.CTkLabel(
            header,
            text="النسخة المثبتة حالياً: v1.8 Windows 11 Edition",
            font=get_font(11),
            text_color=("gray40", "gray60"),
            anchor="w"
        )
        sub_lbl.grid(row=1, column=1, sticky="w")

        # Content Card
        card = ctk.CTkFrame(wizard, corner_radius=8)
        card.grid(row=1, column=0, sticky="nsew", padx=24, pady=10)
        card.grid_columnconfigure(0, weight=1)

        info_text = (
            "✨ مميزات نظام التحديث التلقائي (Inno Setup In-Place Upgrade):\n\n"
            "• ترقية آمنة 100%: يتم تثبيت التحديث فوق النسخة الحالية مباشرة.\n"
            "• الحفاظ على البيانات: لا يتم حذف ملفات الطلبيات أو المخرجات المحفوظة.\n"
            "• أيقونة وسطح مكتب موحد: يتم تحديث الاختصارات وأيقونة شريط المهام تلقائياً.\n\n"
            "لترقية النظام إلى النسخة الأحدث:\n"
            "1. يمكنك تحميل أحدث مثبت Setup.exe عبر صفحة التحديثات.\n"
            "2. أو تشغيل ملف التثبيت الجديد وسيقوم باستبدال الملفات تلقائياً."
        )

        txt_widget = ctk.CTkLabel(
            card,
            text=info_text,
            font=get_font(11),
            justify="right",
            anchor="e",
            wraplength=480
        )
        txt_widget.grid(row=0, column=0, padx=16, pady=16, sticky="nsew")

        # Bottom Action Bar
        bottom = ctk.CTkFrame(wizard, fg_color="transparent")
        bottom.grid(row=2, column=0, sticky="ew", padx=24, pady=(10, 20))
        bottom.grid_columnconfigure(0, weight=1)

        def _open_releases():
            import webbrowser
            webbrowser.open("https://github.com/omarEldestawi/Inventory-search/releases")

        check_btn = ctk.CTkButton(
            bottom,
            text="🌐 فحص التحديثات في GitHub / Check Online",
            font=get_font(11, "bold"),
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HOVER,
            command=_open_releases
        )
        check_btn.grid(row=0, column=0, sticky="w")

        close_w_btn = ctk.CTkButton(
            bottom,
            text="إغلاق / Close",
            font=get_font(11),
            width=100,
            fg_color=("gray70", "gray30"),
            hover_color=("gray60", "gray40"),
            command=wizard.destroy
        )
        close_w_btn.grid(row=0, column=1, sticky="e", padx=(10, 0))

    def _render_file_list(self):
        """Renders individual file cards inside the scrollable container."""
        # Clear existing card widgets
        for widget in self._file_card_widgets.values():
            try:
                widget.destroy()
            except Exception:
                pass
        self._file_card_widgets.clear()

        if not self.file_model.files:
            self.empty_label.grid(row=0, column=0, pady=80, padx=20)
            return

        self.empty_label.grid_forget()

        for idx, f_item in enumerate(self.file_model.files):
            card = ctk.CTkFrame(self.file_scroll_frame, corner_radius=6, fg_color=("gray90", "gray22"))
            card.grid(row=idx, column=0, sticky="ew", padx=6, pady=3)
            card.grid_columnconfigure(1, weight=1)

            # Extension Badge
            ext_text = f_item.ext.replace(".", "").upper()
            ext_badge_color = COLOR_DANGER if ext_text == "PDF" else (COLOR_ORDER_BADGE if "XLS" in ext_text else COLOR_WARN_BADGE)
            ext_badge = ctk.CTkLabel(
                card,
                text=f"[{ext_text}]",
                font=get_font(10, "bold"),
                text_color=ext_badge_color,
                width=45
            )
            ext_badge.grid(row=0, column=0, padx=(10, 5), pady=8, sticky="w")

            # File Name & Size
            name_text = f"{f_item.filename}  ({f_item.size_str})"
            name_label = ctk.CTkLabel(
                card,
                text=name_text,
                font=get_font(11, "bold"),
                anchor="w"
            )
            name_label.grid(row=0, column=1, padx=5, pady=8, sticky="ew")

            # Category Status Badge
            if f_item.category == "AvgDiscounts":
                cat_badge_text = "📊 خصم مرجح / Avg Disc"
                cat_badge_color = COLOR_ACCENT
                current_choice = "خصم مرجح (Avg Discounts)"
            elif f_item.category == "Order":
                cat_badge_text = "📋 أمر شراء / Order"
                cat_badge_color = COLOR_ORDER_BADGE
                current_choice = "أمر شراء (Order)"
            else:
                cat_badge_text = "🏷️ كتالوج / Catalog"
                cat_badge_color = COLOR_CATALOG_BADGE
                current_choice = "كتالوج مخزن (Catalog)"

            cat_badge = ctk.CTkLabel(
                card,
                text=cat_badge_text,
                font=get_font(10, "bold"),
                text_color=cat_badge_color,
                width=120
            )
            cat_badge.grid(row=0, column=2, padx=5, pady=8, sticky="e")

            # Manual Category Override Dropdown
            override_menu = ctk.CTkOptionMenu(
                card,
                values=["أمر شراء (Order)", "كتالوج مخزن (Catalog)", "خصم مرجح (Avg Discounts)"],
                font=get_font(10),
                width=165,
                height=26,
                command=lambda val, p=f_item.path: self._on_override_category(p, val)
            )
            override_menu.set(current_choice)
            override_menu.grid(row=0, column=3, padx=5, pady=8, sticky="e")

            # Delete Button (✕)
            del_btn = ctk.CTkButton(
                card,
                text="✕",
                width=28,
                height=26,
                font=get_font(11, "bold"),
                fg_color=COLOR_DANGER,
                hover_color=COLOR_DANGER_HOVER,
                command=lambda p=f_item.path: self._on_remove_file(p)
            )
            del_btn.grid(row=0, column=4, padx=(5, 10), pady=8, sticky="e")

            # Row 1: Catalog Inspection & OCR Re-read Action
            if f_item.category == "Catalog":
                # Medication Count Badge (Formatted cleanly without duplicate number)
                if f_item.item_count is not None:
                    if f_item.item_count > 0:
                        ocr_tag = " [OCR]" if f_item.is_ocr else ""
                        count_text = f"📦 {f_item.item_count} صنف / items{ocr_tag}"
                        count_color = COLOR_SUCCESS if f_item.is_ocr else COLOR_CATALOG_BADGE
                    else:
                        count_text = "⚠️ 0 صنف (يحتاج OCR) / 0 items (needs OCR)"
                        count_color = COLOR_WARN_BADGE
                else:
                    count_text = "⏳ جاري فحص الأصناف... / Checking count..."
                    count_color = ("gray50", "gray60")

                count_badge = ctk.CTkLabel(
                    card,
                    text=count_text,
                    font=get_font(10, "bold"),
                    text_color=count_color,
                    anchor="w"
                )
                count_badge.grid(row=1, column=0, columnspan=2, padx=(10, 5), pady=(0, 6), sticky="w")
                card._count_badge = count_badge

                # Action button: View Items & Discounts
                view_items_btn = ctk.CTkButton(
                    card,
                    text="👁️ عرض الأصناف والخصومات / View Items & Discounts",
                    font=get_font(10, "bold"),
                    width=210,
                    height=24,
                    fg_color=COLOR_ORDER_BADGE,
                    hover_color="#047857",
                    command=lambda p=f_item.path: self._open_catalog_item_viewer(p)
                )
                view_items_btn.grid(row=1, column=2, padx=5, pady=(0, 6), sticky="e")

                # Action button: Re-read with OCR
                if f_item.ocr_running:
                    ocr_btn = ctk.CTkButton(
                        card,
                        text="⏳ جاري المسح بـ OCR...",
                        font=get_font(10, "bold"),
                        width=180,
                        height=24,
                        state="disabled",
                        fg_color=("gray60", "gray30")
                    )
                else:
                    ocr_btn = ctk.CTkButton(
                        card,
                        text="🔄 إعادة قراءة بـ OCR / Re-read with OCR",
                        font=get_font(10, "bold"),
                        width=180,
                        height=24,
                        fg_color=COLOR_CATALOG_BADGE,
                        hover_color="#0369A1",
                        command=lambda p=f_item.path: self._start_ocr_reread(p)
                    )
                ocr_btn.grid(row=1, column=3, padx=5, pady=(0, 6), sticky="e")

                # Status label
                ocr_status_lbl = ctk.CTkLabel(
                    card,
                    text=f_item.ocr_status_msg or "",
                    font=get_font(9),
                    text_color=("gray40", "gray60"),
                    anchor="e"
                )
                ocr_status_lbl.grid(row=1, column=4, padx=(2, 10), pady=(0, 6), sticky="e")
                card._ocr_status_lbl = ocr_status_lbl

            self._file_card_widgets[f_item.path] = card


    # -------------------------------------------------------------------------
    # State Synchronization & Validation Gate
    # -------------------------------------------------------------------------
    def _update_ui_state(self):
        """Updates summary counts, validation gate, and button states."""
        summary = self.file_model.get_summary()
        self.counter_badge.configure(
            text=f"{summary['total']} ملفات ({summary['orders']} طلبية | {summary['catalogs']} كتالوج)"
        )

        out_dir = self.output_dir_var.get()
        is_valid, reason = self.file_model.validate(out_dir)

        self.validation_label.configure(text=reason)

        is_running = self.bridge is not None and self.bridge.is_running
        if is_running:
            self.run_button.configure(state="disabled", text="جاري المعالجة...\nProcessing...")
            self.add_files_btn.configure(state="disabled")
            self.add_folder_btn.configure(state="disabled")
            self.clear_all_btn.configure(state="disabled")
            self.dest_browse_btn.configure(state="disabled")
            self.dest_entry.configure(state="disabled")
        else:
            self.run_button.configure(
                state="normal" if is_valid else "disabled",
                text="بدء التحسين والتوزيع\nRun Optimization"
            )
            self.add_files_btn.configure(state="normal")
            self.add_folder_btn.configure(state="normal")
            self.clear_all_btn.configure(state="normal")
            self.dest_browse_btn.configure(state="normal")
            self.dest_entry.configure(state="normal")

    # -------------------------------------------------------------------------
    # Asynchronous Execution Pattern
    # -------------------------------------------------------------------------
    def _on_run_optimization(self):
        """Starts asynchronous procurement pipeline using ProcurementEngineBridge."""
        is_valid, reason = self.file_model.validate(self.output_dir_var.get())
        if not is_valid:
            messagebox.showwarning("تنبيه / Warning", reason)
            return

        order_files = self.file_model.get_order_files()
        catalog_files = self.file_model.get_catalog_files()
        avg_discounts_files = self.file_model.get_avg_discounts_files()
        avg_discounts_file = avg_discounts_files[0] if avg_discounts_files else None
        output_dir = self.output_dir_var.get()

        # Reset Progress and Status
        self.progress_bar.set(0.0)
        self.status_label.configure(text="جاري بدء محرك التوزيع الصيدلاني... / Initializing engine...")
        self.open_report_btn.configure(state="disabled")
        self.open_folder_btn.configure(state="disabled")

        # Initialize bridge and start daemon thread
        self.bridge = ProcurementEngineBridge()
        self.bridge.start(
            order_files=order_files,
            catalog_files=catalog_files,
            output_dir=output_dir,
            avg_discounts_file=avg_discounts_file
        )

        self._update_ui_state()

        # Schedule queue poller (50ms)
        self.after(50, self.poll_queue)

    def poll_queue(self):
        """Polls message queue from worker thread every 50ms without UI freezing."""
        if not self.bridge:
            return

        try:
            while True:
                msg = self.bridge.get_message(block=False)
                if msg is None:
                    break

                tag = msg[0]
                if tag == "PROGRESS":
                    pct = float(msg[1])
                    status_text = str(msg[2])
                    self.progress_bar.set(pct)
                    self.status_label.configure(text=status_text)
                elif tag == "DONE":
                    results = msg[1]
                    try:
                        self._on_pipeline_completed(results)
                    except Exception as comp_exc:
                        logger.error(f"Exception in _on_pipeline_completed: {comp_exc}")
                        self._on_pipeline_failed(str(comp_exc), traceback.format_exc())
                elif tag == "ERROR":
                    err_msg = str(msg[1])
                    tb = str(msg[2]) if len(msg) > 2 else ""
                    self._on_pipeline_failed(err_msg, tb)
        except Exception as exc:
            logger.error(f"Exception during queue polling: {exc}")

        if self.bridge and self.bridge.is_running:
            self.after(50, self.poll_queue)
        else:
            self._update_ui_state()

    def _on_pipeline_completed(self, results: dict):
        """Handles successful pipeline completion, updating KPI cards and action buttons."""
        self.progress_bar.set(1.0)
        self.status_label.configure(
            text="✓ اكتملت العملية بنجاح! تم إنشاء تقرير المشتريات المجمع / Completed successfully!"
        )

        if not isinstance(results, dict):
            results = {}
        report_path = results.get("report_path") or results.get("arabic_report_path")
        self.current_report_path = report_path
        self.last_kpi_data = results.get("kpis") or {}
        if report_path:
            actual_dir = os.path.dirname(os.path.abspath(report_path))
            if actual_dir and os.path.isdir(actual_dir) and actual_dir != self.output_dir_var.get():
                self.output_dir_var.set(actual_dir)


        # Populate KPI Cards
        kpis = self.last_kpi_data if isinstance(self.last_kpi_data, dict) else {}
        try:
            total_items = int(kpis.get("total_items", 0) or 0)
        except (ValueError, TypeError):
            total_items = 0

        try:
            matched_items = int(kpis.get("matched_items", 0) or 0)
        except (ValueError, TypeError):
            matched_items = 0

        try:
            det_matches = int(kpis.get("deterministic_matches", 0) or 0)
        except (ValueError, TypeError):
            det_matches = 0

        try:
            raw_oos = kpis.get("out_of_stock")
            if raw_oos is not None:
                oos_count = int(raw_oos)
            else:
                oos_count = max(0, total_items - matched_items)
        except (ValueError, TypeError):
            oos_count = max(0, total_items - matched_items)

        avg_disc = kpis.get("avg_discount", 0.0)
        try:
            avg_disc_val = float(avg_disc)
            if not (avg_disc_val == avg_disc_val):  # check NaN
                avg_disc_val = 0.0
        except (ValueError, TypeError):
            avg_disc_val = 0.0
        if 0 < avg_disc_val <= 1.0:
            avg_disc_val = avg_disc_val * 100.0

        tot_savings = kpis.get("total_savings", 0.0)
        try:
            tot_savings_val = float(tot_savings)
            if not (tot_savings_val == tot_savings_val):  # check NaN
                tot_savings_val = 0.0
        except (ValueError, TypeError):
            tot_savings_val = 0.0

        allocation_counts = kpis.get("allocation_counts")
        if not isinstance(allocation_counts, dict):
            allocation_counts = {}

        allocation_values = kpis.get("allocation_values")
        if not isinstance(allocation_values, dict):
            allocation_values = {}


        self.card_req.configure(text=str(total_items))
        self.card_alloc.configure(text=f"{matched_items} ({det_matches} مؤكد)")
        self.card_oos.configure(text=str(oos_count))
        self.card_disc.configure(text=f"{avg_disc_val:.1f}%")
        self.card_sav.configure(text=f"{tot_savings_val:,.2f} ج.م")


        # Update Winning Wholesalers Pills (Listing wholesalers with count and total value)
        if allocation_counts:
            sorted_wh = sorted(allocation_counts.items(), key=lambda x: x[1], reverse=True)
            pills_parts = []
            for w, cnt in sorted_wh:
                val = allocation_values.get(w, 0.0)
                if val > 0:
                    pills_parts.append(f"🏆 {w}: {cnt} ({val:,.2f} ج.م)")
                else:
                    pills_parts.append(f"🏆 {w}: {cnt}")
            pills_str = " | ".join(pills_parts)
            self.wholesalers_pills_label.configure(text=f"المخازن الموزع عليها: {pills_str}")
        else:
            self.wholesalers_pills_label.configure(text="المخازن الموزع عليها: لا توجد عروض متطابقة")

        # Enable Output Shell Buttons
        if self.current_report_path and os.path.exists(self.current_report_path):
            self.open_report_btn.configure(state="normal")
            self.open_folder_btn.configure(state="normal")

    def _on_pipeline_failed(self, error_msg: str, traceback_str: str):
        """Handles pipeline failure, displaying localized error dialog."""
        self.progress_bar.set(0.0)
        self.status_label.configure(
            text=f"✕ فشلت العملية: {error_msg} / Optimization failed"
        )
        self._show_error_dialog(error_msg, traceback_str)

    def _show_error_dialog(self, error_msg: str, traceback_str: str):
        """Displays a clean error dialog with error message and technical diagnostics."""
        err_win = ctk.CTkToplevel(self)
        err_win.title("خطأ في المعالجة / Optimization Error")
        err_win.geometry("640x440")
        err_win.minsize(500, 320)
        err_win.transient(self)
        err_win.grab_set()

        err_win.grid_columnconfigure(0, weight=1)
        err_win.grid_rowconfigure(2, weight=1)

        header = ctk.CTkLabel(
            err_win,
            text="⚠️ حدث خطأ أثناء تشغيل محرك التوزيع الصيدلاني",
            font=get_font(14, "bold"),
            text_color=COLOR_DANGER
        )
        header.grid(row=0, column=0, padx=20, pady=(20, 5), sticky="w")

        msg_lbl = ctk.CTkLabel(
            err_win,
            text=error_msg,
            font=get_font(12),
            wraplength=580,
            justify="left"
        )
        msg_lbl.grid(row=1, column=0, padx=20, pady=(5, 10), sticky="w")

        tb_box = ctk.CTkTextbox(err_win, font=ctk.CTkFont(family="Consolas", size=10))
        tb_box.grid(row=2, column=0, padx=20, pady=5, sticky="nsew")
        tb_box.insert("1.0", traceback_str or "No traceback available.")
        tb_box.configure(state="disabled")

        btn = ctk.CTkButton(
            err_win,
            text="إغلاق / Close",
            width=120,
            font=get_font(11, "bold"),
            command=err_win.destroy
        )
        btn.grid(row=3, column=0, padx=20, pady=(10, 20), sticky="e")

    # -------------------------------------------------------------------------
    # Windows Shell Integration Handlers
    # -------------------------------------------------------------------------
    def _on_open_report(self):
        """Opens generated procurement Excel workbook in native viewer."""
        if self.current_report_path:
            success = open_file_externally(self.current_report_path)
            if not success:
                messagebox.showerror(
                    "خطأ / Error",
                    f"تعذر فتح ملف التقرير: {self.current_report_path}\nCould not open report file."
                )

    def _on_open_folder(self):
        """Opens containing folder in Windows Explorer."""
        target = self.current_report_path or self.output_dir_var.get()
        if target:
            success = open_folder_externally(target)
            if not success:
                messagebox.showerror(
                    "خطأ / Error",
                    f"تعذر فتح المجلد: {target}\nCould not open destination folder."
                )


def run_headless_self_test(existing_app: Optional[PharmaProcurementApp] = None) -> int:
    """
    Executes automated headless self-test for CLI invocation (`--self-test`).
    Instantiates GUI with `app.withdraw()`, verifies critical component trees and
    bridge binding, and exits with code 0.
    """
    print("[SELF-TEST] Launching headless CustomTkinter GUI self-test...")
    created_here = False
    if existing_app is not None:
        app = existing_app
    else:
        app = PharmaProcurementApp()
        created_here = True

    app.withdraw()
    app.update_idletasks()

    # 1. Verify Core Model & Component Attributes
    assert hasattr(app, "file_model"), "Missing file_model"
    assert hasattr(app, "run_button"), "Missing run_button"
    assert hasattr(app, "progress_bar"), "Missing progress_bar"
    assert hasattr(app, "status_label"), "Missing status_label"
    assert hasattr(app, "kpi_frame"), "Missing kpi_frame"
    assert hasattr(app, "counter_badge"), "Missing counter_badge"
    assert hasattr(app, "open_report_btn"), "Missing open_report_btn"
    assert hasattr(app, "open_folder_btn"), "Missing open_folder_btn"
    assert hasattr(app, "_ocr_queue"), "Missing _ocr_queue"
    assert hasattr(app, "_active_ocr_threads"), "Missing _active_ocr_threads"
    assert callable(getattr(app, "_start_ocr_reread", None)), "Missing _start_ocr_reread"
    assert callable(getattr(app, "_async_inspect_counts", None)), "Missing _async_inspect_counts"
    assert callable(getattr(app, "_open_catalog_item_viewer", None)), "Missing _open_catalog_item_viewer"

    # 2. Verify Initial State
    assert len(app.file_model.files) == 0, "Initial file list should be empty"
    assert app.run_button.cget("state") == "disabled", "Run button should be disabled when empty"

    # 3. Verify Theme Selector
    app._on_change_theme("Dark")
    app._on_change_theme("Light")
    app._on_change_theme("System")

    # 4. Verify Catalog Inspection and Card Rendering with Count Badge
    test_item = FileItem("sample_warehouse_catalog.pdf", "Catalog")
    test_item.item_count = 15
    test_item.is_ocr = True
    app.file_model.files.append(test_item)
    app._render_file_list()
    assert len(app._file_card_widgets) == 1, "Catalog card should be rendered"
    app.file_model.clear()
    app._render_file_list()
    assert len(app.file_model.files) == 0, "File model should be clean after test"


    # 4. Clean destruction if created here
    if created_here:
        app.destroy()
    print("[SELF-TEST] CustomTkinter Windows 11 GUI initialized, validated, and verified cleanly.")
    return 0


def main():
    """Application entry point."""
    if "--self-test" in sys.argv:
        code = run_headless_self_test()
        sys.exit(code)

    app = PharmaProcurementApp()
    app.mainloop()


if __name__ == "__main__":
    main()
