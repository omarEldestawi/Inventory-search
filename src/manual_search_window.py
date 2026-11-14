# -*- coding: utf-8 -*-
"""
Manual Search Window Module.
Provides a responsive, non-blocking CTkToplevel window with 60 ms keystroke debounce,
bounded background worker queue, job tagging, 100-row render cap, and isolated
reference benchmark display.
"""
from __future__ import annotations

import os
import queue
import logging
import threading
import tkinter as tk
from tkinter import ttk
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Callable

import customtkinter as ctk

try:
    from .manual_search_adapter import ManualSearchAdapter, SearchResultItem, ManualSearchResult
except ImportError:
    from manual_search_adapter import ManualSearchAdapter, SearchResultItem, ManualSearchResult

logger = logging.getLogger("ManualSearchWindow")


def _get_font(size: int, weight: str = "normal"):
    try:
        from app_gui import get_font
        return get_font(size, weight)
    except Exception:
        return ("Segoe UI", size, weight)


@dataclass
class SearchJob:
    job_id: int
    catalog_generation_id: int
    query: str
    warehouse_filter: Optional[str]
    sort_mode: str
    catalog_snapshot: List[str]
    force_reload: bool = False


@dataclass
class SearchJobResult:
    job_id: int
    catalog_generation_id: int
    query: str
    warehouse_filter: Optional[str]
    sort_mode: str
    candidates: List[SearchResultItem]
    reference_benchmark: Optional[Dict[str, Any]]
    total_matches: int
    catalog_errors: List[str]
    error: Optional[str] = None


class ManualSearchWindow(ctk.CTkToplevel):
    """
    Single reusable, non-blocking CTkToplevel window for interactive medication search.
    - 60 ms GUI-thread keystroke debounce timer
    - Background worker thread with bounded queue (at most 1 active, 1 replaceable pending)
    - Stale result rejection via job_id and catalog_generation_id
    - Safe teardown releasing all timers, queues, and resources
    - ttk.Treeview with 100-row render cap (< 15 ms rendering)
    - Dedicated Reference Benchmark card separated from supplier offers
    """
    def __init__(
        self,
        parent,
        file_model,
        catalog_generation_id: int = 0,
        on_close_callback: Optional[Callable[[], None]] = None,
        avg_discounts_path: Optional[str] = None,
    ):
        super().__init__(parent)
        self.parent = parent
        self.file_model = file_model
        self._catalog_generation_id = catalog_generation_id
        self.on_close_callback = on_close_callback
        self.avg_discounts_path = avg_discounts_path

        # Window properties
        self.title("البحث اليدوي في الكتالوجات / Manual Catalog Search")
        self.geometry("1100x700")
        self.minsize(850, 550)

        # Non-blocking transient setup (OMIT grab_set)
        try:
            self.transient(parent)
        except Exception as e:
            logger.debug(f"Transient setting failed: {e}")

        # Concurrency & Debounce state
        self._latest_job_id: int = 0
        self._debounce_timer: Optional[str] = None
        self._poll_timer: Optional[str] = None
        self._cancelled: bool = False
        self._item_pool: List[str] = []

        self._job_lock = threading.Lock()
        self._job_queue: queue.Queue = queue.Queue(maxsize=1)
        self._result_queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()

        # UI state variables
        self._search_var = tk.StringVar()
        self._warehouse_var = tk.StringVar(value="الكل / All")
        self._sort_mode_var = tk.StringVar(value="best_match")

        # Build UI layout
        self._build_ui()

        # Bind events
        self._search_var.trace_add("write", self._on_entry_changed)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Start background worker thread
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            args=(self._job_queue, self._result_queue, self._stop_event, self.avg_discounts_path),
            name="ManualSearchWorker",
            daemon=True
        )
        self._worker_thread.start()

        # Start GUI polling callback
        self._poll_timer = self.after(50, self._poll_result_queue)

        # Initial search trigger (empty/presentation slice)
        self._trigger_search(self._search_var.get())

    def _build_ui(self):
        """Constructs controls header, benchmark card, Treeview table, and status bar."""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)  # Table container expands

        # -------------------------------------------------------------
        # Row 0: Controls Header
        # -------------------------------------------------------------
        controls_frame = ctk.CTkFrame(self, fg_color="transparent")
        controls_frame.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        controls_frame.grid_columnconfigure(0, weight=1)

        # Search Entry
        self.search_entry = ctk.CTkEntry(
            controls_frame,
            textvariable=self._search_var,
            placeholder_text="🔍 ابحث باسم الدواء التجاري أو العلمي... / Search brand or generic name...",
            font=_get_font(13),
            height=38,
        )
        self.search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        # Warehouse Filter Dropdown
        warehouses = self._get_active_warehouses()
        self.warehouse_menu = ctk.CTkOptionMenu(
            controls_frame,
            variable=self._warehouse_var,
            values=["الكل / All"] + warehouses,
            font=_get_font(12),
            height=38,
            width=160,
            command=self._on_filter_changed,
        )
        self.warehouse_menu.grid(row=0, column=1, sticky="w", padx=(0, 10))

        # Sort Mode Segmented Button
        self.sort_segmented_btn = ctk.CTkSegmentedButton(
            controls_frame,
            values=["أفضل تطابق / Best Match", "أعلى خصم / Highest Discount"],
            font=_get_font(11, "bold"),
            height=38,
            command=self._on_sort_changed,
        )
        self.sort_segmented_btn.set("أفضل تطابق / Best Match")
        self.sort_segmented_btn.grid(row=0, column=2, sticky="w", padx=(0, 10))

        # Refresh Button
        self.refresh_btn = ctk.CTkButton(
            controls_frame,
            text="🔄",
            width=42,
            height=38,
            font=_get_font(14),
            command=lambda: self._trigger_search(self._search_var.get().strip(), force_reload=True),
        )
        self.refresh_btn.grid(row=0, column=3, sticky="w")

        # -------------------------------------------------------------
        # Row 1: Dedicated Reference Benchmark Card (Initially Hidden)
        # -------------------------------------------------------------
        self.benchmark_frame = ctk.CTkFrame(self, fg_color=("gray92", "gray22"), corner_radius=6)
        self.benchmark_label = ctk.CTkLabel(
            self.benchmark_frame,
            text="",
            font=_get_font(12, "bold"),
            text_color=("#0284C7", "#38BDF8"),
            anchor="w",
        )
        self.benchmark_label.pack(side="left", padx=12, pady=6)

        self.benchmark_disclaimer = ctk.CTkLabel(
            self.benchmark_frame,
            text="⚠️ مرجع استرشادي غير معروض للبيع كطلب مباشر / Benchmark Only - Not a supplier offer",
            font=_get_font(10),
            text_color=("gray50", "gray50"),
            anchor="e",
        )
        self.benchmark_disclaimer.pack(side="right", padx=12, pady=6)
        # Keep benchmark card statically gridded so Row 1->Row 2 geometry never shifts during renders
        self.benchmark_frame.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 6))

        # -------------------------------------------------------------
        # Row 2: Tabular Results (ttk.Treeview with Scrollbar)
        # -------------------------------------------------------------
        table_frame = ctk.CTkFrame(self, corner_radius=6)
        table_frame.grid(row=2, column=0, sticky="nsew", padx=16, pady=8)
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(0, weight=1)

        columns = ("medicine_name", "warehouse_name", "base_price", "discount_pct", "net_price")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")

        self.tree.heading("medicine_name", text="اسم الصنف في الكتالوج / Medicine Name")
        self.tree.heading("warehouse_name", text="المورد / Wholesaler")
        self.tree.heading("base_price", text="السعر الرسمي / Base Price")
        self.tree.heading("discount_pct", text="الخصم / Discount %")
        self.tree.heading("net_price", text="سعر الشراء / Net Price")

        self.tree.column("medicine_name", width=380, anchor="w")
        self.tree.column("warehouse_name", width=160, anchor="center")
        self.tree.column("base_price", width=120, anchor="e")
        self.tree.column("discount_pct", width=110, anchor="center")
        self.tree.column("net_price", width=130, anchor="e")

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.grid(row=0, column=0, sticky="nsew", padx=(2, 0), pady=2)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 2), pady=2)
        self._item_pool = [self.tree.insert("", "end", values=("", "", "", "", "")) for _ in range(100)]
        self.tree.detach(*self._item_pool)

        # -------------------------------------------------------------
        # Row 3: Status & Diagnostics Footer Bar
        # -------------------------------------------------------------
        footer_frame = ctk.CTkFrame(self, fg_color="transparent")
        footer_frame.grid(row=3, column=0, sticky="ew", padx=16, pady=(4, 12))
        footer_frame.grid_columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(
            footer_frame,
            text="جاهز للبحث / Ready",
            font=_get_font(11),
            text_color=("gray40", "gray60"),
            anchor="w",
        )
        self.status_label.grid(row=0, column=0, sticky="w")

        self.error_label = ctk.CTkLabel(
            footer_frame,
            text="",
            font=_get_font(11, "bold"),
            text_color="#DC2626",
            anchor="e",
        )
        self.error_label.grid(row=0, column=1, sticky="e")

    # -----------------------------------------------------------------
    # Event Handlers & Debounce
    # -----------------------------------------------------------------
    def _on_entry_changed(self, *args):
        """Triggers 60 ms GUI-thread timer upon entry keystrokes."""
        if self._cancelled:
            return
        if self._debounce_timer is not None:
            try:
                self.after_cancel(self._debounce_timer)
            except Exception:
                pass
            self._debounce_timer = None

        self._debounce_timer = self.after(60, self._on_debounced_query)

    def _on_debounced_query(self):
        """Fired when 60 ms debounce timer expires."""
        self._debounce_timer = None
        if self._cancelled:
            return
        query = self._search_var.get().strip()
        self._trigger_search(query)

    def _on_filter_changed(self, _choice):
        self._trigger_search(self._search_var.get().strip())

    def _on_sort_changed(self, value):
        if "Highest" in value or "أعلى" in value:
            self._sort_mode_var.set("highest_discount")
        else:
            self._sort_mode_var.set("best_match")
        self._trigger_search(self._search_var.get().strip())

    def _trigger_search(self, query: str, force_reload: bool = False):
        """Prepares SearchJob with active snapshot and submits to bounded worker queue."""
        if self._cancelled:
            return

        if self._debounce_timer is not None:
            self.after_cancel(self._debounce_timer)
            self._debounce_timer = None

        self._latest_job_id += 1
        warehouse = self._warehouse_var.get()
        if warehouse in ("الكل / All", "All", "الكل", "جميع المخازن"):
            warehouse = None

        sort_mode = self._sort_mode_var.get()

        # Capture active catalog snapshot strictly on GUI thread
        raw_catalogs = self.file_model.get_catalog_files() if hasattr(self.file_model, "get_catalog_files") else []
        catalog_snapshot = list(dict.fromkeys(
            os.path.normpath(os.path.abspath(p)) for p in raw_catalogs
        ))

        job = SearchJob(
            job_id=self._latest_job_id,
            catalog_generation_id=self._catalog_generation_id,
            query=query,
            warehouse_filter=warehouse,
            sort_mode=sort_mode,
            catalog_snapshot=catalog_snapshot,
            force_reload=force_reload,
        )

        self.status_label.configure(text="⏳ جاري البحث في الكتالوجات النشطة... / Searching active catalogs...")

        with self._job_lock:
            # Drain any unpicked pending job from queue to maintain bound <= 1
            try:
                self._job_queue.get_nowait()
            except queue.Empty:
                pass
            self._job_queue.put(job)

    # -----------------------------------------------------------------
    # Background Worker Loop
    # -----------------------------------------------------------------
    @staticmethod
    def _worker_loop(job_queue, result_queue, stop_event, avg_discounts_path):
        """Worker thread processing at most 1 active job and consuming from bounded queue."""
        adapter: Optional[ManualSearchAdapter] = None
        last_gen_id: int = -1
        last_catalogs = None

        while not stop_event.is_set():
            job: Optional[SearchJob] = job_queue.get()

            if job is None or stop_event.is_set():
                break

            try:
                # Check file changes off the GUI thread. Rebuilding uses the
                # existing content fingerprints to validate the catalog cache.
                catalogs = {}
                for path in job.catalog_snapshot:
                    try:
                        stat = os.stat(path)
                        catalogs[path] = (stat.st_size, stat.st_mtime_ns)
                    except OSError:
                        catalogs[path] = None
                if (adapter is None or job.force_reload
                        or job.catalog_generation_id != last_gen_id or catalogs != last_catalogs):
                    adapter = ManualSearchAdapter(
                        catalog_files=job.catalog_snapshot,
                        catalog_gen_id=job.catalog_generation_id,
                        avg_discounts_path=avg_discounts_path,
                    )
                    last_gen_id = job.catalog_generation_id
                    last_catalogs = catalogs

                res: ManualSearchResult = adapter.search(
                    query=job.query,
                    warehouse_filter=job.warehouse_filter,
                    sort_mode=job.sort_mode,
                    job_id=job.job_id,
                )

                job_res = SearchJobResult(
                    job_id=res.job_id,
                    catalog_generation_id=res.catalog_gen_id,
                    query=res.query,
                    warehouse_filter=res.warehouse_filter,
                    sort_mode=res.sort_mode,
                    candidates=res.candidates,
                    reference_benchmark=res.reference_benchmark,
                    total_matches=res.total_matches,
                    catalog_errors=res.catalog_errors,
                    error=None,
                )
            except Exception as exc:
                logger.error(f"Manual search worker error: {exc}", exc_info=True)
                job_res = SearchJobResult(
                    job_id=job.job_id,
                    catalog_generation_id=job.catalog_generation_id,
                    query=job.query,
                    warehouse_filter=job.warehouse_filter,
                    sort_mode=job.sort_mode,
                    candidates=[],
                    reference_benchmark=None,
                    total_matches=0,
                    catalog_errors=[str(exc)],
                    error=str(exc),
                )

            if not stop_event.is_set():
                result_queue.put(job_res)

    # -----------------------------------------------------------------
    # GUI Poller & Rendering
    # -----------------------------------------------------------------
    def _poll_result_queue(self):
        """GUI-thread polling callback draining results and discarding stale jobs."""
        if self._cancelled:
            return

        try:
            while not self._result_queue.empty():
                res: SearchJobResult = self._result_queue.get_nowait()
                if self._cancelled:
                    return

                # Stale rejection checks
                if res.catalog_generation_id != self._catalog_generation_id:
                    logger.debug(
                        f"Discarding result from old generation: {res.catalog_generation_id} != {self._catalog_generation_id}"
                    )
                    continue
                if res.job_id < self._latest_job_id or self._debounce_timer is not None:
                    logger.debug(f"Discarding stale job result: {res.job_id} < {self._latest_job_id}")
                    continue

                self._render_search_results(res)
        except queue.Empty:
            pass
        except Exception as exc:
            logger.error(f"Error polling result queue: {exc}")
        finally:
            if not self._cancelled:
                self._poll_timer = self.after(50, self._poll_result_queue)

    def _render_search_results(self, res: SearchJobResult):
        """Renders search results, reference benchmark card, and status labels."""
        # 1. Reference Benchmark Card
        if res.reference_benchmark and (res.reference_benchmark.get("formatted_pct") or res.reference_benchmark.get("ref_discount_str")):
            pct_str = res.reference_benchmark.get("formatted_pct") or res.reference_benchmark.get("ref_discount_str")
            q_name = res.reference_benchmark.get("query", res.query)
            bench_text = f"📊 متوسط الخصم المرجعي للصنف ({q_name}): {pct_str}"
            if self.benchmark_label.cget("text") != bench_text:
                self.benchmark_label.configure(text=bench_text)
        else:
            if self.benchmark_label.cget("text") != "":
                self.benchmark_label.configure(text="")

        # 2. Table Render (100-row cap with in-place item recycling and pooled nodes)
        display_slice = res.candidates[:100]
        existing_children = self.tree.get_children()
        n_curr = len(existing_children)
        n_new = len(display_slice)

        # Clear interactive selection if active
        if self.tree.selection():
            self.tree.selection_remove(self.tree.selection())

        # Pre-format rows to avoid string formatting inside Tkinter loop
        formatted_rows = [
            (
                item.medicine_name,
                item.warehouse_name,
                f"{item.base_price:.2f} ج.م" if item.base_price > 0 else "-",
                f"{item.discount_pct:.1f}%",
                f"{item.net_price:.2f} ج.م" if item.net_price is not None else "-",
            )
            for item in display_slice
        ]

        # Temporarily decouple scrollbar callback without unmapping Treeview from grid
        sb = self.tree.cget("yscrollcommand")
        if sb:
            self.tree.configure(yscrollcommand="")
        try:
            # Update existing rows in place without Tcl node allocation churn
            min_count = min(n_curr, n_new)
            for i in range(min_count):
                self.tree.item(existing_children[i], values=formatted_rows[i])

            # Reattach pre-allocated pool nodes if new results exceed current count
            if n_new > n_curr:
                existing_set = set(existing_children)
                detached_pool = [iid for iid in self._item_pool if iid not in existing_set]
                pool_idx = 0
                for i in range(n_curr, n_new):
                    if pool_idx < len(detached_pool):
                        iid = detached_pool[pool_idx]
                        pool_idx += 1
                        try:
                            self.tree.item(iid, values=formatted_rows[i])
                            self.tree.reattach(iid, "", "end")
                            continue
                        except tk.TclError:
                            pass
                    iid = self.tree.insert("", "end", values=formatted_rows[i])
                    self._item_pool.append(iid)
            # Detach surplus pool rows if new results are fewer than current count
            elif n_curr > n_new:
                pool_set = set(self._item_pool)
                to_detach = [iid for iid in existing_children[n_new:] if iid in pool_set]
                to_delete = [iid for iid in existing_children[n_new:] if iid not in pool_set]
                if to_detach:
                    self.tree.detach(*to_detach)
                if to_delete:
                    self.tree.delete(*to_delete)
        finally:
            if sb:
                self.tree.configure(yscrollcommand=sb)

        # 3. Status text
        if res.error:
            new_status = f"❌ خطأ أثناء البحث: {res.error}"
        elif res.total_matches == 0:
            if res.query:
                new_status = f"❌ لم يتم العثور على أدوية مطابقة لبحثك: '{res.query}'"
            else:
                new_status = "🔍 لا توجد أدوية مطابقة في الكتالوجات النشطة."
        else:
            if res.total_matches > 100:
                new_status = f"✓ تم العثور على {res.total_matches} نتيجة مطابقة (يتم عرض أفضل 100 صنف)"
            else:
                new_status = f"✓ تم العثور على {res.total_matches} نتيجة مطابقة"

        if self.status_label.cget("text") != new_status:
            self.status_label.configure(text=new_status)

        # 4. Partial errors banner
        new_err = f"⚠️ تعذر قراءة بعض الملفات ({len(res.catalog_errors)})" if res.catalog_errors else ""
        if self.error_label.cget("text") != new_err:
            self.error_label.configure(text=new_err)

    def notify_catalogs_changed(self, new_catalog_generation_id: int):
        """Called by parent when catalogs are added, removed, replaced, or edited."""
        self._catalog_generation_id = new_catalog_generation_id
        # Refresh warehouse dropdown options
        warehouses = self._get_active_warehouses()
        self.warehouse_menu.configure(values=["الكل / All"] + warehouses)
        if self._warehouse_var.get() not in (["الكل / All"] + warehouses):
            self._warehouse_var.set("الكل / All")
        # Trigger fresh search against new catalog generation
        self._trigger_search(self._search_var.get().strip())

    def _get_active_warehouses(self) -> List[str]:
        """Extracts unique warehouse names from active catalog files."""
        if not hasattr(self.file_model, "get_catalog_files"):
            return []
        files = self.file_model.get_catalog_files()
        whs = set()
        for f in files:
            bn = os.path.splitext(os.path.basename(f))[0]
            try:
                from normalizer import normalize_vendor_name
                whs.add(normalize_vendor_name(bn))
            except Exception:
                whs.add(bn)
        return sorted(list(whs))

    # -----------------------------------------------------------------
    # Safe Teardown Protocol
    # -----------------------------------------------------------------
    def _on_close(self):
        """Cancels timers, stops worker, drains queues, and destroys window safely."""
        self._cancelled = True
        self._stop_event.set()

        if self._debounce_timer is not None:
            try:
                self.after_cancel(self._debounce_timer)
            except Exception:
                pass
            self._debounce_timer = None

        if self._poll_timer is not None:
            try:
                self.after_cancel(self._poll_timer)
            except Exception:
                pass
            self._poll_timer = None

        # Wake worker so it exits promptly
        try:
            self._job_queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self._job_queue.put_nowait(None)
        except Exception:
            pass

        # Drain queues
        while not self._result_queue.empty():
            try:
                self._result_queue.get_nowait()
            except queue.Empty:
                break

        if self.on_close_callback:
            try:
                self.on_close_callback()
            except Exception:
                pass

        self.destroy()
