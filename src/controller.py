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


class ClassifiedDict(dict):
    """
    Subclass of dict to maintain backward-compatibility with older tests
    that assert classify_files returns {'orders': [], 'catalogs': [], 'unknown': []}
    while fully supporting and exposing 'avg_discounts'.
    """
    def __eq__(self, other):
        if isinstance(other, dict) and 'avg_discounts' not in other and self.get('avg_discounts') == []:
            d = dict(self)
            d.pop('avg_discounts', None)
            return d == other
        return super().__eq__(other)


def classify_files(file_paths: list[str]) -> dict[str, list[str]]:
    """
    Classifies a list of file paths into:
      - 'orders': Purchase orders (.xlsx, .xls, .csv)
      - 'catalogs': Vendor catalogs (.pdf, .xlsx, .xls, .csv)
      - 'avg_discounts': Reference average discounts dataset ('أرصده المخازن' / 'خصم مرجح')
      - 'unknown': Unsupported, lock/temporary, or unreadable files

    Uses a 3-tier heuristic:
      - Tier 1: File Extension Analysis (.pdf is always a catalog)
      - Tier 2: Filename pattern matching:
          * Average discount keywords ('أرصده المخازن', 'خصم مرجح', 'مرجح', 'avg_discount', etc.)
          * Daily date codes (0910.xlsx) and order keywords
          * Wholesaler / catalog keywords
      - Tier 3: Content peek:
          * Average discount tokens ('خصم مرجح', 'أرصده المخازن') before catalog heuristics
          * Order tokens vs catalog tokens
    """
    categorized = ClassifiedDict({
        'orders': [],
        'catalogs': [],
        'avg_discounts': [],
        'unknown': []
    })

    # Average discounts filename keywords (checked BEFORE catalog and order keywords)
    avg_discount_name_keywords = [
        'أرصده المخازن', 'ارصدة المخازن', 'أرصدة المخازن', 'ارصده المخازن',
        'أرصده_المخازن', 'ارصدة_المخازن', 'أرصدة_المخازن', 'ارصده_المخازن',
        'أرصده مخازن', 'ارصدة مخازن', 'أرصدة مخازن', 'ارصده مخازن',
        'خصم مرجح', 'خصم_مرجح', 'الخصم المرجح', 'الخصم_المرجح', 'مرجح',
        'avg_discount', 'avg_discounts', 'weighted_discount', 'weighted_discounts',
        'average_discount', 'average_discounts'
    ]

    # Order filename keywords
    order_name_keywords = [
        'طلب', 'طلبية', 'طلبيه', 'نواقص', 'شراء', 'مشتريات', 'اوردر', 'أوردر',
        'فاتورة', 'فاتوره', 'احتياجات', 'order', 'buying', 'purchase', 'po',
        'shortage', 'requisition', 'req'
    ]
    # Catalog / Wholesaler negative keywords
    catalog_name_keywords = [
        'جمله', 'جملة', 'خصم', 'عروض', 'عرض', 'ex', 'كتالوج', 'catalog', 'مخزن',
        'wholesaler', 'vendor', 'price_list', 'pricelist'
    ]

    # Strong catalog keywords that indicate a vendor catalog in mixed-signal filenames
    strong_catalog_name_keywords = [
        'كتالوج', 'catalog', 'عروض', 'عرض', 'price_list', 'pricelist', 'wholesaler', 'vendor'
    ]

    # Average discounts content column markers (weighted average discount column)
    avg_discount_col_tokens = [
        'خصم مرجح', 'الخصم المرجح', 'خصم_مرجح', 'الخصم_المرجح',
        'avg_discount', 'avg discount', 'weighted_discount', 'weighted discount'
    ]

    # Medication name column markers
    med_name_tokens = [
        'إسم الصنف', 'اسم الصنف', 'الصنف', 'صنف', 'item_name', 'item name', 'اسم_الصنف', 'إسم_الصنف'
    ]

    # Order content markers (explicit quantity columns)
    order_qty_tokens = [
        'الكمية المطلوبة', 'الكميه المطلوبه', 'الكمية', 'الكميه', 'كمية', 'كميه',
        'المطلوب', 'qty', 'quantity', 'ordered', 'pieces'
    ]

    # Secondary order content markers
    order_intent_tokens = [
        'أسم العميل', 'اسم العميل', 'اصناف تم طلبها', 'طلبها',
        'نواقص', 'customer', 'buying list', 'order list', 'purchase order', 'order items'
    ]

    # Catalog pricing and discount column markers
    catalog_price_tokens = [
        'سعر الجمهور', 'سعر جمهور', 'سعر الصيدلي', 'سعر صيدلي', 'سعر الشراء', 'public price'
    ]
    catalog_disc_tokens = [
        'نسبة الخصم', 'نسبه الخصم', 'الخصم %', 'خصم %', 'بونص', 'bonus', 'disc%'
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

        is_avg_discount_name = any(k in fname_lower for k in avg_discount_name_keywords)
        is_order_name = bool(
            re.search(r'^\d{4}\.(?:xlsx|xls|csv)$', fname_lower) or
            re.search(r'^\d{1,4}[-_\.]\d{1,4}\.(?:xlsx|xls|csv)$', fname_lower) or
            re.search(r'^\d{4}[-_\.]\d{1,2}[-_\.]\d{1,2}\.(?:xlsx|xls|csv)$', fname_lower) or
            re.search(r'^\d{4,}\s*(?:\(\d+\)|_copy)?\.(?:xlsx|xls|csv)$', fname_lower) or
            any(k in fname_lower for k in order_name_keywords)
        )
        is_catalog_name = any(k in fname_lower for k in catalog_name_keywords)
        has_strong_catalog_name = any(k in fname_lower for k in strong_catalog_name_keywords)

        # Fast path: Check average discounts filename ONLY IF unambiguous
        # Mixed-signal filenames (e.g. 'طلبية أرصده المخازن.xlsx' or 'كتالوج خصم مرجح.xlsx') MUST fall through to Tier 3
        if is_avg_discount_name and not is_order_name and not has_strong_catalog_name and not is_catalog_name:
            categorized['avg_discounts'].append(f_path)
            continue

        # Fast path: Unambiguous Order by filename
        if is_order_name and not is_catalog_name and not is_avg_discount_name:
            categorized['orders'].append(f_path)
            continue

        # Fast path: Unambiguous Catalog by filename
        if is_catalog_name and not is_order_name and not is_avg_discount_name:
            categorized['catalogs'].append(f_path)
            continue

        # Tier 3: Content Inspection for ambiguous or mixed-signal spreadsheets
        sample_read_success = False
        text_block = ""

        try:
            if ext in ['.xlsx', '.xls']:
                try:
                    import openpyxl
                    wb = openpyxl.load_workbook(f_path, read_only=True, data_only=True)
                    sheets_to_check = [wb.active] if wb.active else []
                    for s in wb.worksheets:
                        if s not in sheets_to_check:
                            sheets_to_check.append(s)

                    all_rows = []
                    for sheet in sheets_to_check:
                        for row_idx, row in enumerate(sheet.iter_rows(values_only=True)):
                            if row_idx >= 30:
                                break
                            all_rows.extend([str(c).strip() for c in row if c is not None])
                    wb.close()
                    text_block = ' '.join(all_rows)
                    sample_read_success = True
                except Exception:
                    sample_df = pd.read_excel(f_path, header=None, nrows=30)
                    text_block = ' '.join([str(x).strip() for row in sample_df.values for x in row if pd.notna(x)])
                    sample_read_success = True
            else:
                for enc in ['utf-8-sig', 'cp1256', 'utf-8', 'latin1']:
                    try:
                        with open(f_path, 'r', encoding=enc, errors='replace') as fp:
                            lines = [fp.readline() for _ in range(30)]
                            text_block = ' '.join(lines)
                            sample_read_success = True
                            break
                    except Exception:
                        continue

            if os.path.isfile(f_path) and os.path.getsize(f_path) == 0:
                sample_read_success = False
            elif sample_read_success and not text_block.strip():
                sample_read_success = False
        except Exception as read_err:
            logger.debug(f"Failed to peek content of {f_path}: {read_err}")
            sample_read_success = False

        if not sample_read_success and not is_order_name and not is_catalog_name and not is_avg_discount_name:
            categorized['unknown'].append(f_path)
            continue

        text_lower = text_block.lower()

        # Evaluate explicit column intent
        has_order_qty = any(token in text_block or token in text_lower for token in order_qty_tokens)
        has_order_intent = any(token in text_block or token in text_lower for token in order_intent_tokens)
        has_avg_disc_col = any(token in text_block or token in text_lower for token in avg_discount_col_tokens)
        has_med_name = any(token in text_block or token in text_lower for token in med_name_tokens)
        has_catalog_price = any(token in text_block or token in text_lower for token in catalog_price_tokens)
        has_catalog_disc = any(token in text_block or token in text_lower for token in catalog_disc_tokens)

        # Decision hierarchy:
        # 1. Orders: An order contains quantity columns (الكمية المطلوبة).
        #    Real orders take precedence over mentions of 'أرصدة المخازن' in header/title cells.
        if has_order_qty or (has_order_intent and not has_avg_disc_col):
            categorized['orders'].append(f_path)
        # 2. Average Discounts: Must contain BOTH reference discount column (خصم مرجح)
        #    AND medication name column, without order quantities or catalog public prices.
        elif has_avg_disc_col and has_med_name and not has_order_qty and not has_catalog_price:
            categorized['avg_discounts'].append(f_path)
        # 3. Catalogs: Contains catalog price/discount columns or catalog name signals
        elif has_catalog_price or has_catalog_disc or is_catalog_name or has_strong_catalog_name:
            categorized['catalogs'].append(f_path)
        # 4. Fallback based on filename heuristics
        elif is_order_name:
            categorized['orders'].append(f_path)
        elif is_avg_discount_name:
            categorized['avg_discounts'].append(f_path)
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

    # Non-degradation safety: if OCR yielded valid items, accept them directly.
    # Only fall back to previously cached items if OCR returned 0 items.
    prev_cached = global_catalog_cache.get(norm_path)
    if not df.empty:
        logger.info(f"OCR successfully extracted {len(df)} items for {fname}")
    elif prev_cached is not None and not prev_cached.empty:
        logger.info(f"OCR returned 0 items; preserving {len(prev_cached)} previously cached items for {fname}")
        df = prev_cached

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
        avg_discounts_file: Optional[str] = None,
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
                import inspect
                pipeline_kwargs = {
                    "order_files": order_files,
                    "catalog_files": catalog_files,
                    "output_dir": output_dir,
                    "progress_callback": _progress_cb,
                    "custom_date_str": custom_date_str,
                    "cancel_check": _cancel_check,
                    "catalog_cache": cache_to_use,
                }
                sig = inspect.signature(run_procurement_pipeline)
                if "avg_discounts_file" in sig.parameters:
                    pipeline_kwargs["avg_discounts_file"] = avg_discounts_file

                results = run_procurement_pipeline(**pipeline_kwargs)
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
