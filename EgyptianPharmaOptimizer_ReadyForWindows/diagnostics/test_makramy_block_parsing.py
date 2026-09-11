# -*- coding: utf-8 -*-
import pymupdf, re, unicodedata
from src.normalizer import (
    EASTERN_ARABIC_DIGITS,
    parse_discount,
    parse_dosage_and_pack,
    unreverse_arabic_text,
    normalize_arabic_text
)

doc = pymupdf.open(r"G:\My Drive\Pharama Daily orders\‎⁨المكرومي المنصورة⁩.pdf")

all_makramy_items = []

for pno in range(len(doc)):
    page = doc[pno]
    blocks = page.get_text("blocks")
    page_count = 0
    for b in blocks:
        # Check if block is in column 2 or column 3 (x0 >= 210)
        # Note: Column 1 is handled by find_tables, but let's see if blocks cover col 2 & 3
        if b[0] < 210 or b[1] < 80 or b[3] > 800:
            continue
            
        raw_text = b[4].strip()
        if not raw_text or any(h in raw_text for h in ['الخصم', 'السعر', 'الصنف', 'المخزن', 'أصناف', 'شركة اروى']):
            continue
            
        # Normalize Unicode presentation forms & digits
        text = unicodedata.normalize('NFKD', raw_text)
        text = text.translate(EASTERN_ARABIC_DIGITS)
        
        # Replace newlines with space
        line = ' '.join(text.split()).strip()
        
        # Decouple digits from Arabic letters
        line = re.sub(r'([a-zA-Z\u0600-\u06FF])(\d+)', r'\1 \2', line)
        line = re.sub(r'(\d+)([a-zA-Z\u0600-\u06FF])', r'\1 \2', line)
        
        # Typical pattern: <Medicine Name ...> <Price> <Discount>
        # e.g. "امبوفير امبول 275 23" or "اماريل 2 مجم 30 قرص س.ج ج 87 78 32"
        # At the end of the line: Discount is the last number, Price is the number before it
        # Let's extract numbers from the end:
        m = re.search(r'(\d+(?:\.\d+)?)\s*$', line)
        if not m:
            continue
        disc_str = m.group(1)
        disc_val = parse_discount(disc_str)
        
        prefix = line[:m.start()].strip()
        m_price = re.search(r'(\d+(?:\.\d+)?)\s*(?:ج|جنيه)?\s*$', prefix)
        if not m_price:
            continue
        price_val = float(m_price.group(1))
        raw_name = prefix[:m_price.start()].strip()
        
        # Clean trailing artifacts like 'ج', 'س.ج', '//'
        raw_name = re.sub(r'[\s/]+$', '', raw_name).strip()
        
        if len(raw_name) >= 2 and disc_val > 0 and price_val > 0:
            norm_name = normalize_arabic_text(raw_name)
            all_makramy_items.append((pno+1, raw_name, norm_name, price_val, disc_val))
            page_count += 1
            
    print(f"Page {pno+1}: {page_count} items from blocks")

print(f"Total Makramy items extracted from blocks: {len(all_makramy_items)}")
print("\nSample items:")
for it in all_makramy_items[:15]:
    print(f"  P{it[0]}: Name='{it[1]}' | Price={it[3]} | Disc={it[4]}")
