# -*- coding: utf-8 -*-
import os, sys, pymupdf, re, unicodedata, pandas as pd
from dotenv import load_dotenv

load_dotenv()
drive_dir = r"G:\My Drive\Pharama Daily orders"

from src.normalizer import (
    EASTERN_ARABIC_DIGITS,
    parse_discount,
    parse_dosage_and_pack,
    unreverse_arabic_text,
    normalize_arabic_text,
    normalize_vendor_name
)
from src.pdf_parser import PDFCatalogParser, fix_arabic_bidi_if_needed
from src.excel_parser import load_purchase_order
from src.allocator import MedicineAllocator

def extract_cure_right_column(page):
    right_rect = pymupdf.Rect(305, 80, 590, 790)
    words = page.get_text("words", clip=right_rect)
    y_buckets = {}
    for w in words:
        y_val = round(w[1], 1)
        matched = None
        for b in y_buckets:
            if abs(b - y_val) <= 3.5:
                matched = b
                break
        if matched is None:
            matched = y_val
            y_buckets[matched] = []
        y_buckets[matched].append(w)
        
    items = []
    for y in sorted(y_buckets.keys()):
        row_words = y_buckets[y]
        sorted_by_x = sorted(row_words, key=lambda w: w[0])
        discs = [w for w in sorted_by_x if 315 <= w[0] <= 345]
        prices = [w for w in sorted_by_x if 355 <= w[0] <= 405]
        names = [w for w in sorted_by_x if w[0] >= 405]
        
        disc_val = 0.0
        price_val = 0.0
        if discs:
            disc_val = parse_discount(discs[0][4])
        if prices:
            try:
                price_val = float(prices[0][4].translate(EASTERN_ARABIC_DIGITS))
            except ValueError:
                m = re.search(r'[-+]?\d*\.?\d+', prices[0][4].translate(EASTERN_ARABIC_DIGITS))
                if m:
                    price_val = float(m.group())
                    
        name_words_sorted = sorted(names, key=lambda w: w[0], reverse=True)
        raw_name = ' '.join(w[4] for w in name_words_sorted).strip()
        raw_name = unicodedata.normalize('NFKD', raw_name)
        
        if raw_name and price_val > 0 and disc_val > 0:
            norm_name = normalize_arabic_text(raw_name)
            dosage, unit_size = parse_dosage_and_pack(raw_name)
            items.append({
                'warehouse_name': 'كيور فارما',
                'item_name': raw_name,
                'normalized_name': norm_name,
                'dosage': dosage,
                'unit_size': unit_size,
                'base_price': price_val,
                'discount_rate': disc_val,
                'stock_status': True
            })
    return items

def extract_makramy_blocks(page):
    blocks = page.get_text("blocks")
    items = []
    for b in blocks:
        if b[0] < 210 or b[1] < 80 or b[3] > 800:
            continue
        raw_text = b[4].strip()
        if not raw_text or any(h in raw_text for h in ['الخصم', 'السعر', 'الصنف', 'المخزن', 'أصناف', 'شركة اروى']):
            continue
            
        text = unicodedata.normalize('NFKD', raw_text)
        text = re.sub(r'([٠-٩]+)([0-9]+)', r'\1 \2', text)
        text = re.sub(r'([0-9]+)([٠-٩]+)', r'\1 \2', text)
        text = re.sub(r'([a-zA-Z\u0600-\u06FF])([0-9٠-٩]+)', r'\1 \2', text)
        text = re.sub(r'([0-9٠-٩]+)([a-zA-Z\u0600-\u06FF])', r'\1 \2', text)
        text = text.translate(EASTERN_ARABIC_DIGITS)
        
        line = ' '.join(text.split()).strip()
        m = re.search(r'(\d+(?:\.\d+)?)\s*$', line)
        if not m:
            continue
        disc_val = parse_discount(m.group(1))
        prefix = line[:m.start()].strip()
        
        m_price = re.search(r'(\d+(?:\.\d+)?)\s*(?:ج|جنيه)?\s*$', prefix)
        if not m_price:
            continue
        price_val = float(m_price.group(1))
        raw_name = prefix[:m_price.start()].strip()
        raw_name = re.sub(r'\b(?:ج|جنيه|س\.ج|س\.ق|سعر|جديد|قديم)\b', ' ', raw_name)
        raw_name = re.sub(r'[\s/]+$', '', raw_name).strip()
        
        if len(raw_name) >= 2 and disc_val > 0 and price_val > 0:
            norm_name = normalize_arabic_text(raw_name)
            dosage, unit_size = parse_dosage_and_pack(raw_name)
            items.append({
                'warehouse_name': 'مخزن المكرومي',
                'item_name': raw_name,
                'normalized_name': norm_name,
                'dosage': dosage,
                'unit_size': unit_size,
                'base_price': price_val,
                'discount_rate': disc_val,
                'stock_status': True
            })
    return items

def parse_excel_catalog(file_path: str, warehouse_name: str) -> pd.DataFrame:
    try:
        raw_df = pd.read_excel(file_path) if file_path.endswith(('.xlsx', '.xls')) else pd.read_csv(file_path)
    except Exception as e:
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
    clean_df = clean_df[clean_df['item_name'].str.len() > 1]
    clean_df = clean_df[~clean_df['item_name'].isin(['nan', 'None', '', 'الصنف', 'اسم الصنف'])]
    return clean_df

# Ingest all files
all_catalogs = []
pdf_files = [f for f in os.listdir(drive_dir) if f.endswith('.pdf')]
for pdf in pdf_files:
    w_raw = os.path.splitext(pdf)[0]
    w_name = normalize_vendor_name(w_raw)
    fpath = os.path.join(drive_dir, pdf)
    p_inst = PDFCatalogParser(fpath, warehouse_name=w_name)
    df_base = p_inst.parse()
    extra_items = []
    if 'كيور' in w_name:
        doc = pymupdf.open(fpath)
        for page in doc:
            extra_items.extend(extract_cure_right_column(page))
    elif 'المكرومي' in w_name:
        doc = pymupdf.open(fpath)
        for page in doc:
            extra_items.extend(extract_makramy_blocks(page))
            
    if extra_items:
        df_full = pd.concat([df_base, pd.DataFrame(extra_items)], ignore_index=True)
    else:
        df_full = df_base
    print(f"Catalog {w_name}: {len(df_full)} rows")
    all_catalogs.append(df_full)

# Excel catalogs
excel_files = [f for f in os.listdir(drive_dir) if f.endswith(('.xlsx', '.xls')) and '0910' not in f and not f.startswith('~$') and not f.startswith('أفضل') and not f.startswith('Procurement')]
for exc in excel_files:
    w_raw = os.path.splitext(exc)[0]
    w_name = normalize_vendor_name(w_raw)
    df = parse_excel_catalog(os.path.join(drive_dir, exc), warehouse_name=w_name)
    print(f"Catalog {w_name}: {len(df)} rows")
    all_catalogs.append(df)

consolidated = pd.concat(all_catalogs, ignore_index=True)
print(f"\nTotal Consolidated Inventory: {len(consolidated)} listings")

order_file = os.path.join(drive_dir, "0910.xlsx")
buying_list = load_purchase_order(order_file)
print(f"Loaded order {len(buying_list)} items")

allocator = MedicineAllocator(consolidated)
results = allocator.allocate_order(buying_list)
kpis = results['kpis']
print("\n" + "="*50)
print(f"Matched items: {kpis['matched_items']}")
print(f"Deterministic: {kpis['deterministic_matches']}")
print(f"Average discount: {kpis['avg_discount']}%")
print("Allocations per warehouse:")
for w, count in kpis['allocation_counts'].items():
    print(f"  {w}: {count}")

# Check the two dangerous false positives
master = results['master_comparison']
antodine = master[master['اسم الصنف في أمر الشراء'].str.contains('انتودين')]
print("\nAntodine matches in output:")
print(antodine[['اسم الصنف في أمر الشراء', 'اسم الصنف في كتالوج المخزن الفائز']])

zithro = master[master['اسم الصنف في أمر الشراء'].str.contains('زيثروماكس')]
print("\nZithromax matches in output:")
print(zithro[['اسم الصنف في أمر الشراء', 'اسم الصنف في كتالوج المخزن الفائز']])
