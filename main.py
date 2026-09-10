# -*- coding: utf-8 -*-
"""
Medicine Price & Discount Comparator CLI Pipeline.
Ingests Arabic Warehouse PDF and Excel catalogs, allocates items by max discount,
and generates the final Arabic Excel procurement order.
Supports Google Drive desktop folder directly or local input folders.
"""
import sys
import os
import re
import glob
import argparse
import datetime
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from src.pdf_parser import PDFCatalogParser
from src.excel_parser import load_purchase_order
from src.allocator import MedicineAllocator
from src.report_generator import ArabicExcelReportGenerator
from src.normalizer import parse_discount, normalize_vendor_name

def parse_excel_catalog(file_path: str, warehouse_name: str) -> pd.DataFrame:
    """Extracts catalog items, discounts, and prices from warehouse Excel/CSV files."""
    try:
        raw_df = pd.read_excel(file_path) if file_path.endswith(('.xlsx', '.xls')) else pd.read_csv(file_path)
    except Exception as e:
        print(f"(Error reading {os.path.basename(file_path)}: {e})")
        return pd.DataFrame()

    item_col, disc_col, price_col = None, None, None
    for col in raw_df.columns:
        c_str = str(col).strip().lower()
        if any(k in c_str for k in ['صنف', 'اسم', 'دواء', 'item', 'product', 'البيان']) and item_col is None:
            item_col = col
        elif any(k in c_str for k in ['جملة', 'خصم', 'discount', '%', 'نسبة']) and disc_col is None:
            disc_col = col
        elif any(k in c_str for k in ['سعر ج', 'سعر', 'جمهور', 'price', 'رسمي']) and price_col is None:
            price_col = col

    if item_col is None:
        item_col = raw_df.columns[0]
    if disc_col is None and len(raw_df.columns) > 1:
        disc_col = raw_df.columns[1]

    clean_df = pd.DataFrame()
    clean_df['warehouse_name'] = [warehouse_name] * len(raw_df)
    clean_df['item_name'] = raw_df[item_col].astype(str).str.strip()
    clean_df['normalized_name'] = clean_df['item_name'].apply(lambda x: x.strip().lower())
    clean_df['dosage'] = ''
    clean_df['unit_size'] = ''
    clean_df['base_price'] = pd.to_numeric(raw_df[price_col], errors='coerce').fillna(0.0) if price_col else 0.0
    clean_df['discount_rate'] = raw_df[disc_col].apply(parse_discount) if disc_col else 0.0
    clean_df['stock_status'] = True

    # Filter out empty or noise rows
    clean_df = clean_df[clean_df['item_name'].str.len() > 1]
    clean_df = clean_df[~clean_df['item_name'].isin(['nan', 'None', '', 'الصنف', 'اسم الصنف'])]
    return clean_df

def scan_drive_directory(drive_dir: str):
    """
    Dynamically scans Google Drive folder, separating daily purchase orders from warehouse catalogs.
    Handles changing daily filenames, date codes (e.g. 0910.xlsx, 0911.xlsx), and varying layouts.
    """
    all_files = [
        os.path.join(drive_dir, f) for f in os.listdir(drive_dir)
        if not f.startswith('~$') and not f.startswith('أفضل_اسعار') and not f.startswith('Procurement_Order_') and not f.endswith('.ini')
        and f.endswith(('.pdf', '.xlsx', '.xls', '.csv'))
    ]

    order_files = []
    pdf_catalogs = []
    excel_catalogs = []

    for f in all_files:
        fname = os.path.basename(f)
        if fname.endswith('.pdf'):
            pdf_catalogs.append(f)
        else:
            # Check filename patterns for orders
            is_order_name = bool(re.search(r'^\d{4}\.(?:xlsx|xls|csv)$', fname) or any(k in fname.lower() for k in ['طلب', 'نواقص', 'شراء', 'order', 'buying']))
            
            # Check content patterns by sampling initial rows
            is_order_content = False
            try:
                sample_df = pd.read_excel(f, header=None, nrows=10)
                text_block = ' '.join([str(x) for row in sample_df.values for x in row if pd.notna(x)])
                is_order_content = any(k in text_block for k in ['أسم العميل', 'اسم العميل', 'اصناف تم طلبها', 'طلبها', 'نواقص', 'الكمية المطلوبة', 'الكميه المطلوبه', 'المطلوب'])
            except Exception:
                pass
                
            if is_order_content or (is_order_name and not any(k in fname for k in ['جمله', 'جملة', 'خصم', 'عروض', 'عرض', 'EX'])):
                order_files.append(f)
            else:
                excel_catalogs.append(f)

    # Sort orders by modification time so that today's newest daily order is always selected
    order_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    return order_files, pdf_catalogs, excel_catalogs

def main():
    parser = argparse.ArgumentParser(description="Medicine Price & Discount Comparator (Arabic Support)")
    parser.add_argument("--drive-dir", default=os.getenv("DRIVE_DIR"), help="Path to Google Drive folder containing daily files")
    parser.add_argument("--catalogs-dir", default="input/catalogs", help="Directory containing warehouse PDF/Excel catalogs")
    parser.add_argument("--orders-dir", default="input/orders", help="Directory containing purchase order Excel/CSV files")
    parser.add_argument("--order-file", default=None, help="Specific purchase order file path")
    parser.add_argument("--output-dir", default=None, help="Directory to save generated Excel reports")
    parser.add_argument("--date", default=None, help="Custom date for report name (YYYY-MM-DD), default is today")

    args = parser.parse_args()

    print("=" * 70)
    print(" 🏥 نظام مقارنة أسعار وخصومات الأدوية وتوزيع الطلبيات (Medicine Price Comparator)")
    print("=" * 70)

    # 1. Detect Source Directory
    using_drive = bool(args.drive_dir and os.path.exists(args.drive_dir))
    
    if using_drive:
        print(f"[+] Connected to Google Drive Directory:\n    📁 {args.drive_dir}")
        order_files, pdf_files, excel_catalog_files = scan_drive_directory(args.drive_dir)
        output_dir = args.output_dir or args.drive_dir
    else:
        os.makedirs(args.catalogs_dir, exist_ok=True)
        os.makedirs(args.orders_dir, exist_ok=True)
        pdf_files = glob.glob(os.path.join(args.catalogs_dir, "*.pdf"))
        excel_catalog_files = (
            glob.glob(os.path.join(args.catalogs_dir, "*.xlsx")) +
            glob.glob(os.path.join(args.catalogs_dir, "*.xls")) +
            glob.glob(os.path.join(args.catalogs_dir, "*.csv"))
        )
        order_files = (
            glob.glob(os.path.join(args.orders_dir, "*.xlsx")) +
            glob.glob(os.path.join(args.orders_dir, "*.csv"))
        )
        output_dir = args.output_dir or "output"

    os.makedirs(output_dir, exist_ok=True)

    # 2. Ingest Warehouse Catalogs
    if not pdf_files and not excel_catalog_files:
        print(f"\n[!] No warehouse catalogs found in: {args.drive_dir if using_drive else args.catalogs_dir}")
        sys.exit(0)

    all_catalogs = []
    print(f"\n[+] Ingesting {len(pdf_files)} PDF catalog(s) and {len(excel_catalog_files)} Excel catalog(s)...")

    # Process PDFs
    for pdf in pdf_files:
        w_raw = os.path.splitext(os.path.basename(pdf))[0]
        w_name = normalize_vendor_name(w_raw)
        print(f"  -> Reading PDF Catalog: '{w_name}' ...", end=" ", flush=True)
        parser_inst = PDFCatalogParser(pdf, warehouse_name=w_name)
        df = parser_inst.parse()
        print(f"({len(df)} items extracted)")
        if not df.empty:
            all_catalogs.append(df)

    # Process Excel Catalogs
    for exc in excel_catalog_files:
        w_raw = os.path.splitext(os.path.basename(exc))[0]
        w_name = normalize_vendor_name(w_raw)
        print(f"  -> Reading Excel Catalog: '{w_name}' ...", end=" ", flush=True)
        df = parse_excel_catalog(exc, warehouse_name=w_name)
        print(f"({len(df)} items extracted)")
        if not df.empty:
            all_catalogs.append(df)

    if not all_catalogs:
        print("\n[!] No valid catalog items could be extracted.")
        sys.exit(1)

    consolidated_inventory = pd.concat(all_catalogs, ignore_index=True)
    num_suppliers = len(consolidated_inventory['warehouse_name'].unique())
    print(f"\n[✓] Consolidated Inventory built: {len(consolidated_inventory)} total listings across {num_suppliers} warehouses.")

    # 3. Ingest Target Purchase Order
    target_order_file = args.order_file
    if not target_order_file:
        if order_files:
            # Pick most recently modified order file if multiple
            order_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            target_order_file = order_files[0]
        else:
            print(f"\n[!] No purchase order found!")
            sys.exit(0)

    print(f"\n[+] Loading Daily Purchase Order from: '{os.path.basename(target_order_file)}' ...")
    buying_list = load_purchase_order(target_order_file)
    print(f"[✓] Loaded {len(buying_list)} unique requested items (deduplicated & aggregated).")

    # 4. Match & Allocate (Deterministic + Gemini 3.6 Flash Fallback + Safety Gates)
    print("\n[+] Allocating items to warehouses with highest discount rates...")
    allocator = MedicineAllocator(consolidated_inventory)
    results = allocator.allocate_order(buying_list)

    # 5. Generate Multi-Sheet Arabic Excel
    print(f"\n[+] Generating Arabic Excel workbook in: {output_dir} ...")
    report_gen = ArabicExcelReportGenerator(results, output_dir=output_dir)
    final_path = report_gen.generate(custom_date_str=args.date)
    print(f"[✓] Excel Report successfully created & saved: {final_path}")

    # Also save a local backup copy in output/ if running from Google Drive
    if using_drive and os.path.abspath(output_dir) != os.path.abspath("output"):
        try:
            import shutil
            os.makedirs("output", exist_ok=True)
            backup_path = os.path.join("output", os.path.basename(final_path))
            shutil.copy2(final_path, backup_path)
            print(f"[✓] Local backup copy saved to: {backup_path}")
        except Exception:
            pass

    # 6. Print KPI Summary
    kpis = results['kpis']
    print("\n" + "=" * 70)
    print(f" 📊 ملخص التوزيع والنتائج (Procurement Summary):")
    print(f"  • إجمالي الأصناف المطلوبة: {kpis['total_items']}")
    print(f"  • الأصناف الموزعة بنجاح: {kpis['matched_items']}")
    print(f"    - مطابقة محلية مؤكدة: {kpis.get('deterministic_matches', 0)}")
    print(f"    - مطابقة معتمدة عبر المساعد الذكي: {kpis.get('ai_assisted_matches', 0)}")
    print(f"  • الأصناف غير المتوفرة (نواقص): {kpis['out_of_stock']}")
    print(f"  • متوسط نسبة الخصم للطلبية: {kpis['avg_discount']}%")
    print("\n📦 توزيع الأصناف على المخازن الفائزة بأعلى خصم:")
    for w_name, count in kpis.get('allocation_counts', {}).items():
        print(f"  • {w_name}: {count} صنف")
    print("=" * 70)
    print(f"\nتم حفظ ورفع الملف بنجاح إلى Google Drive:\n👉 {os.path.abspath(final_path)}\n")

if __name__ == "__main__":
    main()
