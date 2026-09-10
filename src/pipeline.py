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
from typing import Callable, Optional, Union
import pandas as pd

try:
    from .pdf_parser import PDFCatalogParser
    from .excel_parser import load_purchase_order
    from .allocator import MedicineAllocator
    from .report_generator import ArabicExcelReportGenerator
    from .normalizer import parse_discount, normalize_vendor_name, parse_dosage_and_pack
except ImportError:
    from pdf_parser import PDFCatalogParser
    from excel_parser import load_purchase_order
    from allocator import MedicineAllocator
    from report_generator import ArabicExcelReportGenerator
    from normalizer import parse_discount, normalize_vendor_name, parse_dosage_and_pack

logger = logging.getLogger("ProcurementPipeline")


class PipelineExecutionError(RuntimeError):
    """Raised when the procurement pipeline encounters a fatal error, containing diagnostic details."""
    def __init__(self, message: str, diagnostics: Optional[dict] = None):
        super().__init__(message)
        self.diagnostics = diagnostics or {}


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
    clean_df['warehouse_name'] = [warehouse_name] * len(raw_df)
    clean_df['item_name'] = raw_df[item_col].astype(str).str.strip()
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
    output_dir: str,
    progress_callback: Optional[Callable[[float, str], None]] = None,
    custom_date_str: Optional[str] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
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

    Returns:
        dict:
            'results': dict (full allocation output dict with 'kpis', 'master_comparison', etc.)
            'report_path': str (absolute path to primary generated Excel workbook)
            'arabic_report_path': str (absolute path to Arabic alias workbook)
            'kpis': dict (summary procurement metrics)

    Raises:
        PipelineExecutionError: If any pipeline stage fails, wrapping diagnostics.
        ValueError: If inputs are invalid or empty.
        InterruptedError: If cancelled by cancel_check.
    """
    current_stage = "initialization"
    diagnostics = {
        "stage": current_stage,
        "order_files": list(order_files) if order_files else [],
        "catalog_files": list(catalog_files) if catalog_files else [],
        "output_dir": output_dir,
        "custom_date_str": custom_date_str,
        "catalogs_processed": 0,
        "orders_processed": 0,
        "total_catalog_items": 0,
        "total_order_items": 0,
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
        _notify(0.05, "التحقق من صحة الملفات المدخلة... / Validating input files...")
        _check_cancellation()

        if not order_files:
            raise ValueError("No purchase order files provided. At least one order file (.xlsx/.csv) is required.")
        if not catalog_files:
            raise ValueError("No catalog files provided. At least one vendor catalog (.pdf/.xlsx/.csv) is required.")
        if not output_dir:
            raise ValueError("Output directory must be specified.")

        os.makedirs(output_dir, exist_ok=True)

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
            if cat_file.lower().endswith('.pdf'):
                try:
                    parser_inst = PDFCatalogParser(cat_file, warehouse_name=w_name)
                    df_cat = parser_inst.parse()
                except Exception as cat_err:
                    logger.warning(f"Error parsing PDF catalog '{base_name}': {cat_err}")
            elif cat_file.lower().endswith(('.xlsx', '.xls', '.csv')):
                try:
                    df_cat = parse_excel_catalog(cat_file, warehouse_name=w_name)
                except Exception as cat_err:
                    logger.warning(f"Error parsing Excel/CSV catalog '{base_name}': {cat_err}")

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

        # 4. Run Optimization and Allocation
        current_stage = "allocation"
        diagnostics["stage"] = current_stage
        _notify(0.75, "جاري مطابقة الأصناف وتوزيعها على أعلى الخصومات... / Running allocation engine...")

        allocator = MedicineAllocator(consolidated_inventory)
        results = allocator.allocate_order(buying_list)

        kpis = results.get('kpis', {})
        matched = kpis.get('matched_items', 0)
        total_req = kpis.get('total_items', len(buying_list))
        _notify(0.85, f"اكتمل التوزيع: تم تخصيص {matched} من {total_req} صنف بنجاح.")
        _check_cancellation()

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
            'kpis': kpis
        }

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
