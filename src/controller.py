# -*- coding: utf-8 -*-
"""
Procurement Controller & Bridge Layer.
Provides 3-tier file auto-classification (orders vs catalogs) and an asynchronous,
thread-safe worker bridge (ProcurementEngineBridge) for GUI integration.
"""
import os
import re
import queue
import logging
import threading
import traceback
from typing import Optional, Union, Dict, List
import pandas as pd

try:
    from .pipeline import run_procurement_pipeline, PipelineExecutionError
except ImportError:
    from pipeline import run_procurement_pipeline, PipelineExecutionError

logger = logging.getLogger("ProcurementController")


def classify_files(file_paths: list[str]) -> dict[str, list[str]]:
    """
    Classifies a list of file paths into:
      - 'orders': Purchase orders (.xlsx, .xls, .csv)
      - 'catalogs': Vendor catalogs (.pdf, .xlsx, .xls, .csv)
      - 'unknown': Unsupported, lock/temporary, or unreadable files

    Uses a 3-tier heuristic:
      - Tier 1: File Extension Analysis (.pdf is always a catalog)
      - Tier 2: Filename pattern matching (regex for daily date codes like 0910.xlsx,
        Arabic/English order keywords vs wholesaler keywords)
      - Tier 3: Content peek (sample initial rows looking for customer/order markers)
    """
    categorized = {
        'orders': [],
        'catalogs': [],
        'unknown': []
    }

    # Order filename keywords
    order_name_keywords = ['طلب', 'طلبية', 'نواقص', 'شراء', 'order', 'buying', 'purchase', 'po']
    # Catalog / Wholesaler negative keywords
    catalog_name_keywords = ['جمله', 'جملة', 'خصم', 'عروض', 'عرض', 'ex', 'كتالوج', 'catalog', 'مخزن']

    # Order content markers
    order_content_tokens = [
        'أسم العميل', 'اسم العميل', 'اصناف تم طلبها', 'طلبها',
        'نواقص', 'الكمية المطلوبة', 'الكميه المطلوبه', 'المطلوب',
        'customer', 'buying list', 'order list', 'purchase order', 'order items'
    ]

    for f_path in file_paths:
        if not f_path or not isinstance(f_path, str):
            categorized['unknown'].append(f_path)
            continue

        if not os.path.isfile(f_path):
            categorized['unknown'].append(f_path)
            continue

        fname = os.path.basename(f_path)

        # Ignore temporary / lock files or metadata
        if fname.startswith('~$') or fname.startswith('Procurement_Order_') or fname.startswith('أفضل_اسعار') or fname.endswith(('.tmp', '.ini')):
            categorized['unknown'].append(f_path)
            continue

        ext = os.path.splitext(fname)[1].lower()

        # Tier 1: PDFs are unconditionally catalogs in this domain
        if ext == '.pdf':
            categorized['catalogs'].append(f_path)
            continue

        # Non-supported extensions
        if ext not in ['.xlsx', '.xls', '.csv']:
            categorized['unknown'].append(f_path)
            continue

        # Tier 2: Filename heuristics for spreadsheets
        fname_lower = fname.lower()
        is_order_name = bool(
            re.search(r'^\d{4}\.(?:xlsx|xls|csv)$', fname_lower) or
            any(k in fname_lower for k in order_name_keywords)
        )
        is_catalog_name = any(k in fname_lower for k in catalog_name_keywords)

        # Tier 3: Content Inspection
        is_order_content = False
        sample_read_success = False

        try:
            if ext in ['.xlsx', '.xls']:
                sample_df = pd.read_excel(f_path, header=None, nrows=15)
                sample_read_success = True
            else:
                sample_df = None
                for enc in ['utf-8-sig', 'cp1256', 'utf-8', 'latin1']:
                    try:
                        sample_df = pd.read_csv(f_path, header=None, nrows=15, encoding=enc)
                        sample_read_success = True
                        break
                    except Exception:
                        continue

            if sample_df is not None and not sample_df.empty:
                text_block = ' '.join([str(x).strip() for row in sample_df.values for x in row if pd.notna(x)])
                text_lower = text_block.lower()
                if any(token in text_block or token in text_lower for token in order_content_tokens):
                    is_order_content = True
        except Exception as read_err:
            logger.debug(f"Failed to peek content of {f_path}: {read_err}")
            sample_read_success = False

        # If file could not be read at all and was not a clear order name, mark unknown
        if not sample_read_success and not is_order_name:
            categorized['unknown'].append(f_path)
            continue

        # Classification decision
        if is_order_content or (is_order_name and not is_catalog_name):
            categorized['orders'].append(f_path)
        else:
            categorized['catalogs'].append(f_path)

    return categorized


class ProcurementEngineBridge:
    """
    Bridge connecting the GUI controller to the background procurement pipeline.
    Runs pipeline asynchronously in a daemon thread, communicating status and progress
    to the UI via a thread-safe queue.Queue.
    """

    def __init__(self, message_queue: Optional[queue.Queue] = None):
        """
        Initializes the bridge with an optional existing queue.Queue.
        If not provided, an internal thread-safe queue is created.
        """
        self.queue = message_queue if message_queue is not None else queue.Queue()
        self.worker_thread: Optional[threading.Thread] = None
        self._is_running = False
        self._cancel_event = threading.Event()
        self.last_result: Optional[dict] = None
        self.last_error: Optional[tuple] = None

    @property
    def is_running(self) -> bool:
        """Returns True if the background worker thread is currently executing."""
        if self._is_running and self.worker_thread is not None:
            return self.worker_thread.is_alive()
        return False

    def start(
        self,
        order_files: list[str],
        catalog_files: list[str],
        output_dir: str,
        custom_date_str: Optional[str] = None,
    ) -> threading.Thread:
        """
        Launches the procurement pipeline in a daemon background thread.
        Posts ("PROGRESS", percent, message), ("DONE", results), or ("ERROR", msg, tb)
        to the message queue.
        """
        if self.is_running:
            raise RuntimeError("Procurement pipeline is already running in background.")

        self._cancel_event.clear()
        self._is_running = True
        self.last_result = None
        self.last_error = None

        def _worker_target():
            try:
                def _progress_cb(pct: float, msg: str):
                    self.queue.put(("PROGRESS", pct, msg))

                def _cancel_check() -> bool:
                    return self._cancel_event.is_set()

                results = run_procurement_pipeline(
                    order_files=order_files,
                    catalog_files=catalog_files,
                    output_dir=output_dir,
                    progress_callback=_progress_cb,
                    custom_date_str=custom_date_str,
                    cancel_check=_cancel_check,
                )
                self.last_result = results
                self.queue.put(("DONE", results))
            except InterruptedError as int_err:
                msg = str(int_err)
                tb = traceback.format_exc()
                self.last_error = (msg, tb)
                self.queue.put(("ERROR", f"Pipeline Cancelled: {msg}", tb))
            except Exception as exc:
                msg = str(exc)
                tb = traceback.format_exc()
                self.last_error = (msg, tb)
                self.queue.put(("ERROR", msg, tb))
            finally:
                self._is_running = False

        self.worker_thread = threading.Thread(
            target=_worker_target,
            name="ProcurementEngineWorker",
            daemon=True
        )
        self.worker_thread.start()
        return self.worker_thread

    def cancel(self):
        """Signals the background pipeline to cancel execution."""
        self._cancel_event.set()

    def get_message(self, block: bool = False, timeout: Optional[float] = None) -> Optional[tuple]:
        """
        Fetches the next message from the queue.
        Returns None if queue is empty (when block=False or timeout expires).
        """
        try:
            return self.queue.get(block=block, timeout=timeout)
        except queue.Empty:
            return None

    def join(self, timeout: Optional[float] = None):
        """Waits for the background worker thread to terminate."""
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=timeout)
