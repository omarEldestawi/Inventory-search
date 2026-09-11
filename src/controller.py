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

        # Fast path: If unambiguous by filename
        if is_order_name and not is_catalog_name:
            categorized['orders'].append(f_path)
            continue
        if is_catalog_name and not is_order_name:
            categorized['catalogs'].append(f_path)
            continue

        # Tier 3: Lightweight Content Inspection
        is_order_content = False
        sample_read_success = False

        try:
            if ext in ['.xlsx', '.xls']:
                try:
                    import openpyxl
                    wb = openpyxl.load_workbook(f_path, read_only=True, data_only=True)
                    sheet = wb.active or wb.worksheets[0]
                    rows_text = []
                    for row_idx, row in enumerate(sheet.iter_rows(values_only=True)):
                        if row_idx >= 15:
                            break
                        rows_text.extend([str(c).strip() for c in row if c is not None])
                    wb.close()
                    text_block = ' '.join(rows_text)
                    sample_read_success = True
                except Exception:
                    sample_df = pd.read_excel(f_path, header=None, nrows=15)
                    text_block = ' '.join([str(x).strip() for row in sample_df.values for x in row if pd.notna(x)])
                    sample_read_success = True
            else:
                text_block = ""
                for enc in ['utf-8-sig', 'cp1256', 'utf-8', 'latin1']:
                    try:
                        with open(f_path, 'r', encoding=enc, errors='replace') as fp:
                            lines = [fp.readline() for _ in range(15)]
                            text_block = ' '.join(lines)
                            sample_read_success = True
                            break
                    except Exception:
                        continue

            if os.path.isfile(f_path) and os.path.getsize(f_path) == 0:
                sample_read_success = False
            elif sample_read_success and text_block:
                text_lower = text_block.lower()
                if any(token in text_block or token in text_lower for token in order_content_tokens):
                    is_order_content = True
            elif not text_block.strip():
                sample_read_success = False
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

class CatalogCache:
    """Thread-safe in-memory cache for parsed catalog DataFrames."""
    def __init__(self):
        self._cache: Dict[str, pd.DataFrame] = {}
        self._lock = threading.Lock()

    def get(self, file_path: str) -> Optional[pd.DataFrame]:
        with self._lock:
            norm = os.path.normpath(os.path.abspath(file_path))
            df = self._cache.get(norm)
            return df.copy() if df is not None else None

    def set(self, file_path: str, df: pd.DataFrame):
        with self._lock:
            norm = os.path.normpath(os.path.abspath(file_path))
            self._cache[norm] = df.copy() if df is not None else pd.DataFrame()

    def remove(self, file_path: str):
        with self._lock:
            norm = os.path.normpath(os.path.abspath(file_path))
            self._cache.pop(norm, None)

    def clear(self):
        with self._lock:
            self._cache.clear()

    def all_cached(self) -> Dict[str, pd.DataFrame]:
        with self._lock:
            return {k: v.copy() for k, v in self._cache.items()}


global_catalog_cache = CatalogCache()


def inspect_single_catalog(catalog_file: str) -> tuple[str, int, pd.DataFrame]:
    """
    Inspects a single catalog file, returning (normalized_path, count, df).
    Reads from cache if present; otherwise parses and caches.
    """
    if not catalog_file or not isinstance(catalog_file, str):
        return "", 0, pd.DataFrame()
    norm = os.path.normpath(os.path.abspath(catalog_file))
    if not os.path.isfile(norm):
        return norm, 0, pd.DataFrame()

    cached_df = global_catalog_cache.get(norm)
    if cached_df is not None:
        return norm, len(cached_df), cached_df

    df = pd.DataFrame()
    fname = os.path.basename(norm)
    w_raw = os.path.splitext(fname)[0]
    try:
        if norm.lower().endswith('.pdf'):
            try:
                from .pdf_parser import PDFCatalogParser
            except ImportError:
                from pdf_parser import PDFCatalogParser
            parser = PDFCatalogParser(norm)
            df = parser.parse()
        elif norm.lower().endswith(('.xlsx', '.xls', '.csv')):
            try:
                from .pipeline import parse_excel_catalog
                from .normalizer import normalize_vendor_name
            except ImportError:
                from pipeline import parse_excel_catalog
                from normalizer import normalize_vendor_name
            df = parse_excel_catalog(norm, normalize_vendor_name(w_raw))
    except Exception as exc:
        logger.debug(f"Fast inspection failed for {norm}: {exc}")

    global_catalog_cache.set(norm, df)
    return norm, len(df), df


def inspect_catalog_counts(catalog_files: list[str]) -> dict[str, int]:
    """
    Inspects medication count for a list of catalog files.
    Reads from in-memory cache if available; otherwise uses fast digital parser and caches.
    Returns mapping of normalized file path to detected medication count.
    """
    counts = {}
    for f in catalog_files:
        norm, count, _ = inspect_single_catalog(f)
        if norm:
            counts[norm] = count
    return counts


def reread_catalog_with_ocr(catalog_file: str, progress_callback=None) -> tuple[str, int, list[dict]]:
    """
    On-demand re-reads an individual catalog using RapidOCR and RapidTable.
    Caches the parsed DataFrame in memory and returns (normalized_path, count, item_records).
    """
    if not catalog_file or not isinstance(catalog_file, str):
        raise ValueError("Invalid catalog file path provided.")

    norm_path = os.path.normpath(os.path.abspath(catalog_file))
    if not os.path.isfile(norm_path):
        raise FileNotFoundError(f"Catalog file not found: {norm_path}")

    fname = os.path.basename(norm_path)
    w_raw = os.path.splitext(fname)[0]

    df = pd.DataFrame()
    last_err = None
    if norm_path.lower().endswith('.pdf'):
        try:
            from .pdf_parser import PDFCatalogParser
        except ImportError:
            from pdf_parser import PDFCatalogParser
        parser = PDFCatalogParser(norm_path)
        try:
            df = parser.parse_ocr(progress_callback=progress_callback)
            last_err = getattr(parser, "last_error", None)
        except Exception as ocr_err:
            last_err = str(ocr_err)
    else:
        try:
            from .pipeline import parse_excel_catalog
            from .normalizer import normalize_vendor_name
        except ImportError:
            from pipeline import parse_excel_catalog
            from normalizer import normalize_vendor_name
        df = parse_excel_catalog(norm_path, normalize_vendor_name(w_raw))

    if df.empty and last_err:
        raise RuntimeError(last_err)

    global_catalog_cache.set(norm_path, df)
    records = df.to_dict(orient="records") if not df.empty else []
    for rec in records:
        rec["name"] = rec.get("item_name", "")
        rec["price"] = rec.get("base_price", 0.0)
        rec["vendor"] = rec.get("warehouse_name", "")
        rec["category"] = "Catalog"

    return norm_path, len(df), records


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
        output_dir: Optional[str] = None,
        custom_date_str: Optional[str] = None,
        catalog_cache: Optional[Dict[str, pd.DataFrame]] = None,
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

                cache_to_use = catalog_cache if catalog_cache is not None else global_catalog_cache.all_cached()
                results = run_procurement_pipeline(
                    order_files=order_files,
                    catalog_files=catalog_files,
                    output_dir=output_dir,
                    progress_callback=_progress_cb,
                    custom_date_str=custom_date_str,
                    cancel_check=_cancel_check,
                    catalog_cache=cache_to_use,
                )
                self.last_result = results
                self.queue.put(("DONE", results))
            except InterruptedError as int_err:
                msg = str(int_err)
                tb = traceback.format_exc()
                self.last_error = (msg, tb)
                self.queue.put(("ERROR", f"Pipeline Cancelled: {msg}", tb))

            except (PermissionError, OSError) as perm_exc:
                if isinstance(perm_exc, PermissionError) or "access is denied" in str(perm_exc).lower():
                    logger.error(f"Write permission error in worker thread: {perm_exc}")
                msg = str(perm_exc)
                tb = traceback.format_exc()
                self.last_error = (msg, tb)
                self.queue.put(("ERROR", msg, tb))

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
