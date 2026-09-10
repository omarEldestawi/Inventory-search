# -*- coding: utf-8 -*-
"""
Excel/CSV Ingestion for Buying/Purchase Lists and Warehouse Catalogs.
Deduplicates requested items and aggregates quantities automatically.
"""
import os
import re
import pandas as pd
from .normalizer import normalize_arabic_text, parse_discount, parse_dosage_and_pack

def load_purchase_order(file_path: str) -> pd.DataFrame:
    """
    Load requested buying list from Excel or CSV.
    Detects header row automatically, deduplicates duplicate items,
    and aggregates (sums) requested quantities.
    """
    if file_path.endswith('.csv'):
        try:
            raw_df = pd.read_csv(file_path, encoding='utf-8-sig', header=None)
        except Exception:
            raw_df = pd.read_csv(file_path, encoding='cp1256', header=None)
    else:
        raw_df = pd.read_excel(file_path, header=None)

    # Find the header row by checking the first 15 rows
    header_row_idx = 0
    name_keywords = ['اسم', 'صنف', 'دواء', 'item', 'name', 'medicine', 'product', 'البيان']
    qty_keywords = ['كمية', 'عدد', 'مطلوب', 'qty', 'quantity', 'count', 'amount']
    
    for r_idx in range(min(15, len(raw_df))):
        row_vals = [str(x).strip().lower() for x in raw_df.iloc[r_idx].values if pd.notna(x)]
        if any(any(k in v for k in name_keywords) for v in row_vals):
            header_row_idx = r_idx
            break

    # Re-slice dataframe with discovered header
    headers = [str(x).strip() if pd.notna(x) else f"col_{i}" for i, x in enumerate(raw_df.iloc[header_row_idx].values)]
    df = raw_df.iloc[header_row_idx + 1:].copy()
    df.columns = headers

    # Standardize column names
    col_map = {}
    for col in df.columns:
        c_clean = str(col).strip().lower()
        if any(k in c_clean for k in name_keywords) and 'requested_item' not in col_map.values():
            col_map[col] = 'requested_item'
        elif any(k in c_clean for k in qty_keywords) and 'quantity' not in col_map.values():
            col_map[col] = 'quantity'
        elif any(k in c_clean for k in ['تركيز', 'جرعة', 'dosage', 'strength']):
            col_map[col] = 'dosage'
        elif any(k in c_clean for k in ['عبوة', 'حجم', 'pack', 'unit', 'size']):
            col_map[col] = 'unit_size'
            
    df = df.rename(columns=col_map)
    
    if 'requested_item' not in df.columns:
        df.rename(columns={df.columns[0]: 'requested_item'}, inplace=True)
    if 'quantity' not in df.columns:
        if len(df.columns) > 1:
            df.rename(columns={df.columns[1]: 'quantity'}, inplace=True)
        else:
            df['quantity'] = 1

    # Clean data
    df = df.dropna(subset=['requested_item'])
    df['requested_item'] = df['requested_item'].astype(str).str.strip()
    df = df[df['requested_item'] != '']
    
    # Fill and clean quantity
    df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(1).astype(int)
    # Ensure quantity is at least 1
    df['quantity'] = df['quantity'].apply(lambda q: max(1, q))
    
    # Normalize for deduplication
    df['normalized_name'] = df['requested_item'].apply(normalize_arabic_text)
    
    if 'dosage' not in df.columns or 'unit_size' not in df.columns:
        entities = df['requested_item'].apply(parse_dosage_and_pack)
        if 'dosage' not in df.columns:
            df['dosage'] = [e[0] for e in entities]
        if 'unit_size' not in df.columns:
            df['unit_size'] = [e[1] for e in entities]

    # Deduplicate requested items and sum quantities across repeated orders
    df_dedup = df.groupby('requested_item', as_index=False).agg({
        'quantity': 'sum',
        'normalized_name': 'first',
        'dosage': 'first',
        'unit_size': 'first'
    })
            
    return df_dedup[['requested_item', 'normalized_name', 'dosage', 'unit_size', 'quantity']]
