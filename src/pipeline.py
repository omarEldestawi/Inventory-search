# -*- coding: utf-8 -*-
"""
Core Procurement Execution Pipeline.
Decoupled headless pipeline for ingesting catalogs, combining purchase orders,
running deterministic clinical allocation, and generating multi-sheet RTL Excel reports.
"""
import os
import re
import sys
import logging
import datetime
import traceback
import tempfile
import time
import threading
from typing import Any, Callable, Optional, Union
import pandas as pd

try:
    from .pdf_parser import PDFCatalogParser
    from .excel_parser import load_purchase_order
    from .allocator import MedicineAllocator, evaluate_above_average_discounts
    from .report_generator import ArabicExcelReportGenerator
    from .normalizer import parse_discount, normalize_vendor_name, parse_dosage_and_pack
    from .average_discounts import load_average_discounts_file, resolve_default_avg_discounts_path
    from .catalog_diagnostics import (
        FileFingerprint,
        CatalogResult,
        ImportDiagnostics,
        PageDiagnostics,
        GroupDiagnostics,
        METADATA_KEY,
        PARSER_REVISION,
    )
except ImportError:
    from pdf_parser import PDFCatalogParser
    from excel_parser import load_purchase_order
    from allocator import MedicineAllocator, evaluate_above_average_discounts
    from report_generator import ArabicExcelReportGenerator
    from normalizer import parse_discount, normalize_vendor_name, parse_dosage_and_pack
    from average_discounts import load_average_discounts_file, resolve_default_avg_discounts_path
    from catalog_diagnostics import (
        FileFingerprint,
        CatalogResult,
        ImportDiagnostics,
        PageDiagnostics,
        GroupDiagnostics,
        METADATA_KEY,
        PARSER_REVISION,
    )

logger = logging.getLogger("ProcurementPipeline")


def is_in_installation_dir(dir_path: str) -> bool:
    """
    Checks if a path is located inside the application installation directory,
    such as Program Files, _internal, /Applications, macOS .app bundle, or frozen executable folder.
    Guarantees cross-platform protection across Windows, macOS, and Linux, including symlink resolution.
    """
    if not dir_path or not isinstance(dir_path, str):
        return False

    norm_target = os.path.normpath(os.path.abspath(dir_path))
    try:
        real_target = os.path.realpath(norm_target)
    except Exception:
        real_target = norm_target

    targets_to_check = [norm_target, real_target, str(dir_path)]

    # 1. PyInstaller frozen environment
    if getattr(sys, "frozen", False):
        exe_dir = os.path.normpath(os.path.dirname(sys.executable)).lower()
        try:
            real_exe = os.path.realpath(exe_dir).lower()
        except Exception:
            real_exe = exe_dir

        for t in [norm_target.lower(), real_target.lower()]:
            if t == exe_dir or t.startswith(exe_dir + os.sep.lower()) or t == real_exe or t.startswith(real_exe + os.sep.lower()):
                return True

        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            norm_mei = os.path.normpath(os.path.abspath(meipass)).lower()
            try:
                real_mei = os.path.realpath(norm_mei).lower()
            except Exception:
                real_mei = norm_mei
            for t in [norm_target.lower(), real_target.lower()]:
                if t == norm_mei or t.startswith(norm_mei + os.sep.lower()) or t == real_mei or t.startswith(real_mei + os.sep.lower()):
                    return True

    # 2. Path components containing _internal, Program Files, or .app bundle
    protected_parts = {
        "_internal",
        "program files",
        "program files (x86)",
        "commonprogramfiles",
        "commonprogramfiles(x86)",
    }
    for t in targets_to_check:
        parts = set(p.lower() for p in re.split(r"[\\/]", t) if p)
        if any(p in protected_parts for p in parts):
            return True
        if any(part.endswith(".app") for part in parts):
            return True

    # 3. macOS / Unix system & installation directories
    protected_unix_prefixes = (
        "/applications",
        "/system",
        "/library",
        "/usr",
        "/opt",
        "/etc",
        "/bin",
        "/sbin",
        "/private/etc",
        "/private/var/root",
    )
    unix_targets = []
    for t in [norm_target.lower(), real_target.lower(), str(dir_path).lower()]:
        unix_targets.append(t.replace("\\", "/"))
        stripped = re.sub(r"^[a-zA-Z]:", "", t).replace("\\", "/")
        unix_targets.append(stripped)

    for t in unix_targets:
        for prefix in protected_unix_prefixes:
            if t == prefix or t.startswith(prefix + "/"):
                return True

    # 4. Standard Windows system/installation directories & environment variables
    sys_env_vars = [
        "ProgramFiles",
        "ProgramFiles(x86)",
        "ProgramW6432",
        "CommonProgramFiles",
        "CommonProgramFiles(x86)",
        "SystemRoot",
        "ProgramData",
    ]
    for env_var in sys_env_vars:
        env_val = os.environ.get(env_var)
        if env_val:
            norm_env = os.path.normpath(os.path.abspath(env_val)).lower()
            try:
                real_env = os.path.realpath(norm_env).lower()
            except Exception:
                real_env = norm_env
            for t in [norm_target.lower(), real_target.lower()]:
                if (
                    t == norm_env
                    or t.startswith(norm_env + os.sep.lower())
                    or t == real_env
                    or t.startswith(real_env + os.sep.lower())
                ):
                    return True

    # 5. Fallback checks for well-known Program Files / Windows substrings
    for pf in [
        r":\program files",
        r":/program files",
        r":\windows",
        r":/windows",
        r":\programdata",
        r":/programdata",
        r"c:\program files",
        r"c:/program files",
    ]:
        for t in [norm_target.lower(), real_target.lower(), str(dir_path).lower()]:
            if pf in t:
                return True

    return False


def validate_directory_writable(dir_path: str) -> bool:
    """
    Validates write permissions by creating dir_path (if needed) and performing
    a test file creation/deletion probe.
    Returns True if writable; raises PermissionError or OSError otherwise.
    """
    if not dir_path or not isinstance(dir_path, str):
        raise ValueError(f"Invalid directory path: {dir_path}")

    # Explicitly reject existing regular files
    if os.path.isfile(dir_path):
        raise PermissionError(f"Target path '{dir_path}' is an existing regular file, not a directory.")

    try:
        os.makedirs(dir_path, exist_ok=True)
    except (PermissionError, OSError) as exc:
        raise PermissionError(
            f"Output directory '{dir_path}' cannot be created or accessed ([WinError 5] or permission denied): {exc}"
        ) from exc

    test_file = os.path.join(
        dir_path,
        f".write_test_{os.getpid()}_{threading.get_ident()}_{time.time_ns()}.tmp"
    )
    try:
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("write_perm_check")
    except (PermissionError, OSError) as exc:
        raise PermissionError(
            f"Output directory '{dir_path}' is not writable ([WinError 5] or permission denied): {exc}"
        ) from exc
    finally:
        try:
            if os.path.exists(test_file):
                os.remove(test_file)
        except Exception:
            pass
    return True


def get_default_output_dir() -> str:
    """
    Returns a safe, user-writable default output directory.
    Never defaults inside Program Files, _internal, or /Applications.
    Checks Desktop first, then Documents, then user home, then temp.
    """
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, "Desktop", "Pharma_Output"),
        os.path.join(home, "OneDrive", "Desktop", "Pharma_Output"),
        os.path.join(home, "Documents", "Pharma_Output"),
        os.path.join(home, "OneDrive", "Documents", "Pharma_Output"),
        os.path.join(home, "Downloads", "Pharma_Output"),
        os.path.join(home, "Pharma_Output"),
        os.path.join(tempfile.gettempdir(), "Pharma_Output"),
    ]
    for candidate in candidates:
        try:
            if not is_in_installation_dir(candidate):
                validate_directory_writable(candidate)
                return os.path.normpath(os.path.abspath(candidate))
        except (PermissionError, OSError):
            continue

    # Fallback to guaranteed temp directory
    fallback = os.path.join(tempfile.gettempdir(), "Pharma_Output")
    try:
        if not is_in_installation_dir(fallback):
            validate_directory_writable(fallback)
            return os.path.normpath(os.path.abspath(fallback))
    except (PermissionError, OSError):
        pass

    td = tempfile.mkdtemp(prefix="Pharma_Output_")
    return os.path.normpath(os.path.abspath(td))


def resolve_safe_output_dir(configured_dir: Optional[str] = None) -> str:
    """
    Resolves a guaranteed user-writable output directory.
    - If configured_dir is None, empty, in installation dir, or not writable,
      automatically falls back to safe user directory.
    - Validates write permissions with probe before returning.
    """
    if not configured_dir or not str(configured_dir).strip():
        logger.info("No output directory specified; using safe default user directory.")
        return get_default_output_dir()

    norm_dir = os.path.normpath(os.path.abspath(configured_dir))

    # Reject installation paths immediately (including symlinks and UNC shares)
    if is_in_installation_dir(norm_dir):
        logger.warning(
            f"Configured output directory '{configured_dir}' is inside protected installation path. "
            f"Falling back to user-writable directory."
        )
        return get_default_output_dir()

    # Check write permission with probe
    try:
        validate_directory_writable(norm_dir)
        return norm_dir
    except (PermissionError, OSError) as perm_err:
        err_str = str(perm_err).lower()
        is_permission_or_space_issue = (
            isinstance(perm_err, PermissionError) or
            "permission" in err_str or
            "access is denied" in err_str or
            "winerror 5" in err_str or
            "read-only" in err_str or
            "no space left" in err_str or
            "enospc" in err_str or
            getattr(perm_err, "errno", None) in (13, 1, 30, 28)  # EACCES, EPERM, EROFS, ENOSPC
        )
        if is_permission_or_space_issue:
            logger.warning(
                f"Configured output directory '{configured_dir}' is not writable ({perm_err}). "
                f"Falling back to safe user directory."
            )
            fallback = get_default_output_dir()
            logger.info(f"Using safe fallback output directory: {fallback}")
            return fallback
        # Re-raise non-permission filesystem errors (e.g. invalid syntax) for diagnostics
        raise


class PipelineExecutionError(RuntimeError):
    """Raised when the procurement pipeline encounters a fatal error, containing diagnostic details."""
    def __init__(self, message: str, diagnostics: Optional[dict] = None):
        super().__init__(message)
        self.diagnostics = diagnostics or {}


def validate_cached_catalog(
    candidate: Any,
    expected_file_path: str,
) -> Optional[CatalogResult]:
    """
    Validates that a cached catalog candidate matches the current file and parser.
    Reuse cached results only when identity is verifiable and matches the current file and parser.
    Requires:
      - File exists on disk.
      - Matching canonical file identity.
      - Fingerprint is present, uses an absolute path, and matches canonical file path.
      - Matching content SHA-256 hash against the file on disk.
      - Matching parser revision and extraction library version.
      - Valid non-empty dataframe and diagnostics metadata.
    Treats absent, malformed, relative-path, or mismatched fingerprints as cache misses.
    Returns the verified CatalogResult if valid; otherwise returns None.
    """
    if not expected_file_path or not isinstance(expected_file_path, str):
        return None

    norm_expected = os.path.normpath(os.path.abspath(expected_file_path))
    if not os.path.isfile(norm_expected):
        return None

    try:
        canonical_expected = os.path.normcase(os.path.realpath(norm_expected))
    except Exception:
        canonical_expected = os.path.normcase(norm_expected)

    if candidate is None:
        return None

    if isinstance(candidate, CatalogResult):
        cached_res = candidate
    elif isinstance(candidate, pd.DataFrame):
        if candidate.empty:
            return None
        cached_res = CatalogResult.from_dataframe(candidate)
    else:
        return None

    if cached_res is None or cached_res.dataframe is None:
        return None

    fp = getattr(cached_res, "fingerprint", None)
    if fp is None or not isinstance(fp, FileFingerprint):
        return None

    fp_path = getattr(fp, "path", None)
    if not fp_path or not isinstance(fp_path, str) or not os.path.isabs(fp_path):
        return None

    try:
        canonical_fp = os.path.normcase(os.path.realpath(os.path.abspath(fp_path)))
    except Exception:
        canonical_fp = os.path.normcase(os.path.abspath(fp_path))

    if canonical_fp != canonical_expected:
        return None

    fp_sha = getattr(fp, "sha256", None)
    if not fp_sha or not isinstance(fp_sha, str) or len(fp_sha) != 64:
        return None

    if not getattr(fp, "parser_revision", None) or not getattr(fp, "library_version", None):
        return None

    try:
        if not fp.is_current(norm_expected):
            return None
    except Exception:
        return None

    if not hasattr(cached_res, "diagnostics") or cached_res.diagnostics is None:
        return None

    return cached_res


def parse_excel_catalog(file_path: str, warehouse_name: str) -> pd.DataFrame:
    """
    Extracts catalog items, discounts, and prices from warehouse Excel or CSV files.
    Standardizes schema to match PDFCatalogParser output:
    ['warehouse_name', 'item_name', 'normalized_name', 'dosage', 'unit_size', 'base_price', 'discount_rate', 'stock_status']
    """
    empty_schema = pd.DataFrame(columns=[
        'warehouse_name', 'item_name', 'normalized_name', 'dosage',
        'unit_size', 'base_price', 'discount_rate', 'stock_status'
    ])
    
    if not os.path.isfile(file_path):
        logger.warning(f"Catalog file not found: {file_path}")
        return empty_schema

    raw_df = None
    if file_path.lower().endswith(('.xlsx', '.xls')):
        try:
            raw_df = pd.read_excel(file_path)
        except Exception as e:
            logger.warning(f"Failed to read Excel catalog {file_path}: {e}")
            return empty_schema
    else:
        # Try multiple encodings for CSV
        for enc in ['utf-8-sig', 'cp1256', 'utf-8', 'latin1']:
            try:
                raw_df = pd.read_csv(file_path, encoding=enc)
                break
            except Exception:
                continue
        if raw_df is None:
            logger.warning(f"Failed to read CSV catalog with standard encodings: {file_path}")
            return empty_schema

    if raw_df.empty:
        return empty_schema

    # Column identification keywords
    item_keywords = ['صنف', 'اسم', 'دواء', 'item', 'name', 'medicine', 'product', 'البيان', 'description']
    disc_keywords = ['جملة', 'خصم', 'discount', '%', 'نسبة', 'rate', 'disc']
    price_keywords = ['سعر ج', 'سعر', 'جمهور', 'price', 'رسمي', 'public', 'cost']

    item_col, disc_col, price_col = None, None, None
    for col in raw_df.columns:
        c_str = str(col).strip().lower()
        if any(k in c_str for k in item_keywords) and item_col is None:
            item_col = col
        elif any(k in c_str for k in disc_keywords) and disc_col is None:
            disc_col = col
        elif any(k in c_str for k in price_keywords) and price_col is None:
            price_col = col

    # Fallback to column indices if keywords not found in column headers
    if item_col is None and len(raw_df.columns) > 0:
        item_col = raw_df.columns[0]
    if disc_col is None and len(raw_df.columns) > 1:
        disc_col = raw_df.columns[1]

    clean_df = pd.DataFrame()
    clean_warehouse = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', '', str(warehouse_name))
    clean_df['warehouse_name'] = [clean_warehouse] * len(raw_df)
    clean_df['item_name'] = raw_df[item_col].astype(str).str.replace(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', '', regex=True).str.strip()
    clean_df['normalized_name'] = clean_df['item_name'].apply(lambda x: str(x).strip().lower())
    
    # Extract dosage and unit size if available
    entities = clean_df['item_name'].apply(parse_dosage_and_pack)
    clean_df['dosage'] = [e[0] for e in entities]
    clean_df['unit_size'] = [e[1] for e in entities]

    clean_df['base_price'] = pd.to_numeric(raw_df[price_col], errors='coerce').fillna(0.0) if price_col else 0.0
    clean_df['discount_rate'] = raw_df[disc_col].apply(parse_discount) if disc_col else 0.0
    clean_df['stock_status'] = True

    # Filter out empty, header, or noise rows
    clean_df = clean_df[clean_df['item_name'].str.len() > 1]
    noise_values = {'nan', 'none', '', 'null', 'صنف', 'الصنف', 'اسم الصنف', 'البيان', 'item', 'name'}
    clean_df = clean_df[~clean_df['item_name'].str.lower().isin(noise_values)]
    
    return clean_df.reset_index(drop=True)


def run_procurement_pipeline(
    order_files: list[str],
    catalog_files: list[str],
    output_dir: Optional[str] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None,
    custom_date_str: Optional[str] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    catalog_cache: Optional[dict] = None,
    avg_discounts_file: Optional[str] = None,
    allow_partial_imports: bool = False,
    accepted_partial_tokens: Optional[Union[set[str], list[str], tuple[str, ...]]] = None,
) -> dict:
    """
    Executes catalog ingestion, purchase order loading & combining, clinical safety allocation,
    and multi-sheet RTL Excel report generation.


    Args:
        order_files: List of paths to purchase order files (.xlsx, .xls, .csv).
        catalog_files: List of paths to vendor catalog files (.pdf, .xlsx, .xls, .csv).
        output_dir: Destination directory for the generated Excel workbook.
        progress_callback: Optional callable(percent: float, message: str) reporting 0.0 to 1.0.
        custom_date_str: Optional date string ('YYYY-MM-DD') for report naming.
        cancel_check: Optional callable() returning True if operation should be aborted.
        catalog_cache: Optional cache dictionary for parsed catalog DataFrames.
        avg_discounts_file: Optional path to reference average discounts dataset ('أرصده المخازن' / 'خصم مرجح').
        allow_partial_imports: If True, allows partial catalog imports without explicit acknowledgment token.
        accepted_partial_tokens: Set or list of acknowledgment tokens explicitly approved by user.

    Returns:
        dict:
            'results': dict (full allocation output dict with 'kpis', 'master_comparison', 'above_average_discounts', etc.)
            'report_path': str (absolute path to primary generated Excel workbook)
            'arabic_report_path': str (absolute path to Arabic alias workbook)
            'kpis': dict (summary procurement metrics)
            'above_average_discounts': pd.DataFrame (medications with discounts > reference average)

    Raises:
        PipelineExecutionError: If any pipeline stage fails, wrapping diagnostics.
        ValueError: If inputs are invalid or empty.
        InterruptedError: If cancelled by cancel_check.
    """
    current_stage = "initialization"
    accepted_tokens = set(accepted_partial_tokens) if accepted_partial_tokens else set()
    diagnostics = {
        "stage": current_stage,
        "order_files": list(order_files) if order_files else [],
        "catalog_files": list(catalog_files) if catalog_files else [],
        "output_dir": output_dir,
        "custom_date_str": custom_date_str,
        "avg_discounts_file": avg_discounts_file,
        "catalogs_processed": 0,
        "orders_processed": 0,
        "total_catalog_items": 0,
        "total_order_items": 0,
        "catalog_diagnostics": {},
    }

    def _notify(pct: float, msg: str):
        if progress_callback:
            try:
                progress_callback(pct, msg)
            except Exception as cb_err:
                logger.warning(f"Error in progress callback: {cb_err}")

    def _check_cancellation():
        if cancel_check and cancel_check():
            raise InterruptedError("Procurement pipeline was cancelled by user.")

    try:
        # 1. Validation Stage
        current_stage = "input_validation"
        diagnostics["stage"] = current_stage
        _check_cancellation()

        if not order_files:
            raise ValueError("No purchase order files provided. At least one order file (.xlsx/.csv) is required.")
        if not catalog_files:
            raise ValueError("No catalog files provided. At least one vendor catalog (.pdf/.xlsx/.csv) is required.")
        if output_dir is not None and not str(output_dir).strip():
            raise ValueError("Output directory cannot be empty.")

        # Safe User-Writable Output Directory Resolution and Write Permission Validation
        output_dir = resolve_safe_output_dir(output_dir)
        validate_directory_writable(output_dir)
        diagnostics["output_dir"] = output_dir

        _notify(0.05, "التحقق من صحة الملفات المدخلة... / Validating input files...")


        # 2. Ingest Catalogs
        current_stage = "catalog_ingestion"
        diagnostics["stage"] = current_stage
        _notify(0.10, "بدء قراءة وتجهيز كتالوجات الموردين... / Ingesting vendor catalogs...")
        
        all_catalogs = []
        catalog_count = len(catalog_files)

        for idx, cat_file in enumerate(catalog_files):
            _check_cancellation()
            if not os.path.isfile(cat_file):
                logger.warning(f"Catalog file does not exist: {cat_file}")
                continue

            base_name = os.path.basename(cat_file)
            w_raw = os.path.splitext(base_name)[0]
            w_name = normalize_vendor_name(w_raw)

            pct = 0.10 + ((idx + 1) / max(catalog_count, 1)) * 0.40
            _notify(pct, f"قراءة كتالوج ({idx+1}/{catalog_count}): {w_name}...")

            df_cat = pd.DataFrame()
            norm_cat = os.path.normpath(os.path.abspath(cat_file))
            cached_candidate = None
            if catalog_cache is not None:
                if hasattr(catalog_cache, "get") and not isinstance(catalog_cache, dict):
                    cand = catalog_cache.get(norm_cat)
                    if cand is None or (isinstance(cand, pd.DataFrame) and cand.empty):
                        cand = catalog_cache.get(cat_file)
                    if cand is not None and not (isinstance(cand, pd.DataFrame) and cand.empty):
                        cached_candidate = cand
                elif isinstance(catalog_cache, dict):
                    cand = catalog_cache.get(norm_cat)
                    if cand is None or (isinstance(cand, pd.DataFrame) and cand.empty):
                        cand = catalog_cache.get(cat_file)
                    if cand is not None and not (isinstance(cand, pd.DataFrame) and cand.empty):
                        cached_candidate = cand

            if cached_candidate is not None and not (isinstance(cached_candidate, pd.DataFrame) and cached_candidate.empty):
                verified_res = validate_cached_catalog(cached_candidate, norm_cat)
                if verified_res is not None:
                    df_cat = verified_res.to_dataframe()
                    logger.info(f"Using verified cached catalog for '{base_name}'.")
                else:
                    logger.info(
                        f"Cached catalog '{base_name}' is unverified, malformed, or stale on disk; re-parsing fresh copy."
                    )
                    df_cat = pd.DataFrame()

            if df_cat.empty and cat_file.lower().endswith('.pdf'):
                try:
                    parser_inst = PDFCatalogParser(cat_file, warehouse_name=w_name)
                    df_cat = parser_inst.parse()
                    # Fallback for scanned PDFs: if digital extraction yielded 0 items, attempt OCR extraction
                    if df_cat.empty:
                        logger.info(
                            f"Digital extraction found 0 items for {base_name}. "
                            f"Falling back to OCR extraction for scanned PDF..."
                        )
                        _notify(pct, f"مسح الكتالوج الممسوح ضوئياً بـ OCR: {w_name}...")
                        df_cat = parser_inst.parse_ocr(progress_callback=progress_callback)
                        if df_cat.empty and getattr(parser_inst, "last_error", None):
                            logger.warning(f"OCR parsing for '{base_name}' reported: {parser_inst.last_error}")
                except Exception as cat_err:
                    logger.warning(f"Error parsing PDF catalog '{base_name}': {cat_err}")
            elif df_cat.empty and cat_file.lower().endswith(('.xlsx', '.xls', '.csv')):
                try:
                    df_cat = parse_excel_catalog(cat_file, warehouse_name=w_name)
                    if not df_cat.empty:
                        try:
                            fp = FileFingerprint.from_path(norm_cat)
                        except OSError:
                            fp = None
                        page_diag = PageDiagnostics(
                            page=1,
                            strategy="excel",
                            expected_count_known=True,
                            accepted_rows=len(df_cat),
                            groups=[
                                GroupDiagnostics(
                                    group=0,
                                    strategy="excel",
                                    candidate_rows=len(df_cat),
                                    accepted_rows=len(df_cat),
                                )
                            ],
                        )
                        diag = ImportDiagnostics(
                            pages=[page_diag],
                            accepted_rows=len(df_cat),
                            unique_records=len(df_cat),
                            duplicate_records=0,
                        )
                        res = CatalogResult(dataframe=df_cat, diagnostics=diag, fingerprint=fp)
                        df_cat = res.to_dataframe()
                except Exception as cat_err:
                    logger.warning(f"Error parsing Excel/CSV catalog '{base_name}': {cat_err}")

            cat_res = CatalogResult.from_dataframe(df_cat) if df_cat is not None else None
            if cat_res is not None:
                diagnostics["catalog_diagnostics"][norm_cat] = cat_res.diagnostics.to_dict()
                if cat_res.diagnostics.requires_acknowledgment:
                    token = cat_res.acknowledgment_token
                    if not allow_partial_imports and token not in accepted_tokens:
                        summary_str = cat_res.diagnostics.summary()
                        raise PipelineExecutionError(
                            f"Partial catalog import detected for '{base_name}' ({summary_str}). "
                            f"Explicit acknowledgment is required before procurement (token: {token}).",
                            diagnostics={
                                **diagnostics,
                                **cat_res.diagnostics.to_dict(),
                                "partial_catalog": norm_cat,
                                "acknowledgment_token": token,
                            },
                        )

            if df_cat is not None and not df_cat.empty:
                all_catalogs.append(df_cat)
                diagnostics["catalogs_processed"] += 1

        if not all_catalogs:
            raise RuntimeError(
                f"Failed to extract valid catalog items from any of the {catalog_count} provided catalog file(s)."
            )

        consolidated_inventory = pd.concat(all_catalogs, ignore_index=True)
        diagnostics["total_catalog_items"] = len(consolidated_inventory)
        unique_wh = len(consolidated_inventory['warehouse_name'].unique())
        
        _notify(0.55, f"تم تجميع {len(consolidated_inventory)} صنف عبر {unique_wh} مخزن مورد.")
        _check_cancellation()

        # 3. Ingest Purchase Orders
        current_stage = "order_ingestion"
        diagnostics["stage"] = current_stage
        _notify(0.60, "قراءة وتجميع طلبات الشراء... / Ingesting purchase orders...")

        all_orders = []
        order_count = len(order_files)

        for idx, ord_file in enumerate(order_files):
            _check_cancellation()
            if not os.path.isfile(ord_file):
                logger.warning(f"Order file does not exist: {ord_file}")
                continue

            base_name = os.path.basename(ord_file)
            pct = 0.60 + ((idx + 1) / max(order_count, 1)) * 0.12
            _notify(pct, f"قراءة ملف الطلبيات ({idx+1}/{order_count}): {base_name}...")

            try:
                df_order = load_purchase_order(ord_file)
                if df_order is not None and not df_order.empty:
                    all_orders.append(df_order)
                    diagnostics["orders_processed"] += 1
            except Exception as ord_err:
                logger.warning(f"Error parsing purchase order '{base_name}': {ord_err}")

        if not all_orders:
            raise RuntimeError(
                f"Failed to load valid purchase order items from any of the {order_count} provided order file(s)."
            )

        # Deduplicate and combine multiple purchase orders if more than one
        if len(all_orders) == 1:
            buying_list = all_orders[0]
        else:
            combined_orders = pd.concat(all_orders, ignore_index=True)
            buying_list = combined_orders.groupby('requested_item', as_index=False).agg({
                'quantity': 'sum',
                'normalized_name': 'first',
                'dosage': 'first',
                'unit_size': 'first'
            })[['requested_item', 'normalized_name', 'dosage', 'unit_size', 'quantity']]

        diagnostics["total_order_items"] = len(buying_list)
        if buying_list.empty:
            raise ValueError("Consolidated purchase order contains zero valid requested items.")

        _notify(0.72, f"تم تجهيز {len(buying_list)} صنف فريد للشراء والتوزيع.")
        _check_cancellation()

        # 4. Resolve Reference Average Discounts Dataset & Run Allocation
        current_stage = "reference_discounts_loading"
        diagnostics["stage"] = current_stage
        target_avg_path = avg_discounts_file
        if not target_avg_path:
            target_avg_path = resolve_default_avg_discounts_path()

        avg_discounts_df = None
        if target_avg_path and os.path.isfile(target_avg_path):
            try:
                avg_discounts_df = load_average_discounts_file(target_avg_path)
                logger.info(f"Loaded {len(avg_discounts_df)} reference average discount items from {target_avg_path}")
            except Exception as ad_err:
                logger.warning(f"Failed to load average discounts file '{target_avg_path}': {ad_err}")
                avg_discounts_df = None

        current_stage = "allocation"
        diagnostics["stage"] = current_stage
        _notify(0.75, "جاري مطابقة الأصناف وتوزيعها على أعلى الخصومات... / Running allocation engine...")

        allocator = MedicineAllocator(consolidated_inventory, avg_discounts_df=avg_discounts_df)
        results = allocator.allocate_order(buying_list)

        kpis = results.get('kpis', {})
        matched = kpis.get('matched_items', 0)
        total_req = kpis.get('total_items', len(buying_list))
        _notify(0.85, f"اكتمل التوزيع: تم تخصيص {matched} من {total_req} صنف بنجاح.")
        _check_cancellation()

        # Above-average discounts evaluation across reference dataset
        above_avg_df = pd.DataFrame()
        if avg_discounts_df is not None and not avg_discounts_df.empty:
            _notify(0.85, "تقييم الأصناف ذات الخصومات الأعلى من المرجح... / Evaluating above-average discounts...")
            try:
                above_avg_df = evaluate_above_average_discounts(avg_discounts_df, allocator, progress_callback=_notify)
                logger.info(f"Evaluated {len(above_avg_df)} medications with catalog discounts exceeding reference average")
            except Exception as eval_err:
                logger.warning(f"Error evaluating above-average discounts: {eval_err}")
                above_avg_df = pd.DataFrame()

        results['above_average_discounts'] = above_avg_df
        per_wh_above_avg = getattr(above_avg_df, 'attrs', {}).get('per_warehouse', {})
        results['per_warehouse_above_average_discounts'] = per_wh_above_avg

        # 5. Generate Arabic Excel Report
        current_stage = "report_generation"
        diagnostics["stage"] = current_stage
        _notify(0.90, "جاري إنشاء تقرير المشتريات المجمع (RTL)... / Generating Excel report...")

        report_gen = ArabicExcelReportGenerator(results, output_dir=output_dir)
        primary_report_path = report_gen.generate(custom_date_str=custom_date_str)
        primary_report_path = os.path.abspath(primary_report_path)

        # Resolve Arabic alias path
        today_date = datetime.date.today()
        today_str = custom_date_str or today_date.strftime("%Y-%m-%d")
        expected_arabic_filename = f"أفضل_اسعار_{today_str}.xlsx"
        arabic_candidate = os.path.abspath(os.path.join(output_dir, expected_arabic_filename))
        arabic_report_path = arabic_candidate if os.path.exists(arabic_candidate) else primary_report_path

        current_stage = "completed"
        diagnostics["stage"] = current_stage
        _notify(1.0, "اكتملت العملية بنجاح! / Procurement pipeline completed successfully!")

        return {
            'results': results,
            'report_path': primary_report_path,
            'arabic_report_path': arabic_report_path,
            'output_dir': output_dir,
            'kpis': kpis,
            'above_average_discounts': above_avg_df,
            'per_warehouse_above_average_discounts': per_wh_above_avg,
            'catalog_diagnostics': diagnostics.get("catalog_diagnostics", {}),
        }

    except PipelineExecutionError:
        raise
    except InterruptedError:
        logger.info("Procurement pipeline was cancelled by caller.")
        raise
    except Exception as exc:
        diagnostics["error_type"] = type(exc).__name__
        diagnostics["error_message"] = str(exc)
        diagnostics["traceback"] = traceback.format_exc()
        logger.error(f"Pipeline failure at stage '{current_stage}': {exc}\n{diagnostics['traceback']}")
        raise PipelineExecutionError(
            f"Procurement pipeline failed at stage '{current_stage}': {exc}",
            diagnostics=diagnostics
        ) from exc
