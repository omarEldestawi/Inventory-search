# -*- coding: utf-8 -*-
import pymupdf, re, unicodedata, pandas as pd
from src.pdf_parser import PDFCatalogParser
from src.pharma_matcher import is_safe_pharmaceutical_match
from src.normalizer import (
    EASTERN_ARABIC_DIGITS,
    parse_discount,
    parse_dosage_and_pack,
    unreverse_arabic_text,
    normalize_arabic_text
)

cure_pdf = r"G:\My Drive\Pharama Daily orders\‎⁨كيور فارما خاص⁩.pdf"
doc = pymupdf.open(cure_pdf)

# 1. Existing table extraction
parser = PDFCatalogParser(cure_pdf, warehouse_name='كيور فارما')
df_table = parser.parse()
print(f"Table parser extracted: {len(df_table)} rows")

# 2. Extract right column by word y-clustering
right_rect = pymupdf.Rect(305, 80, 590, 790)
right_items = []

for pno in range(len(doc)):
    page = doc[pno]
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
            right_items.append({
                'warehouse_name': 'كيور فارما',
                'item_name': raw_name,
                'normalized_name': norm_name,
                'dosage': dosage,
                'unit_size': unit_size,
                'base_price': price_val,
                'discount_rate': disc_val,
                'stock_status': True
            })

df_right = pd.DataFrame(right_items)
print(f"Right column extracted: {len(df_right)} rows")
df_combined = pd.concat([df_table, df_right], ignore_index=True)
print(f"Combined Cure Pharma: {len(df_combined)} rows")

# Test targets:
targets = [
    "بيزوكارد5مجم30قرص س ج",
    "جلوكوفاج1000اقراص س ج",
    "جينتازون كريم",
    "دياسيرين 3شريط س ج",
    "سيستون  اقراص س ج",
    "كارباميد كريم ممفيس س ج",
    "لوراز اقراص س ج",
    "ميجاليز شراب س ج"
]

for t in targets:
    matches = [row['item_name'] for _, row in df_combined.iterrows() if is_safe_pharmaceutical_match(t, row['item_name'])]
    print(f"Target: '{t}' -> Matches: {matches}")
