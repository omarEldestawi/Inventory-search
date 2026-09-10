# -*- coding: utf-8 -*-
import pymupdf, re, unicodedata
from src.normalizer import (
    EASTERN_ARABIC_DIGITS,
    parse_discount,
    parse_dosage_and_pack,
    unreverse_arabic_text,
    normalize_arabic_text
)
from src.pdf_parser import fix_arabic_bidi_if_needed

doc = pymupdf.open(r"G:\My Drive\Pharama Daily orders\‎⁨المكرومي المنصورة⁩.pdf")

# Define columns:
# Col 1: [30, 220]  (currently in table, but let's check)
# Col 2: [220, 405]
# Col 3: [405, 590]

cols = [
    ("Col2", pymupdf.Rect(220, 80, 405, 790), 220, 250, 280),
    ("Col3", pymupdf.Rect(405, 80, 590, 790), 405, 435, 470)
]

for col_name, clip_rect, x_disc_min, x_price_min, x_name_min in cols:
    print(f"\n=================== {col_name} ===================")
    total_col_items = 0
    for pno in range(len(doc)):
        page = doc[pno]
        words = page.get_text("words", clip=clip_rect)
        
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
            
        page_items = 0
        for y in sorted(y_buckets.keys()):
            row_words = y_buckets[y]
            sorted_by_x = sorted(row_words, key=lambda w: w[0])
            
            # Leftmost is discount, next is price, rest is name (descending x)
            # Filter header row
            row_text = " ".join(w[4] for w in sorted_by_x)
            if any(h in row_text for h in ['الخصم', 'السعر', 'الصنف', 'المخزن']):
                continue
                
            # Words in this column:
            # First word: discount (usually x in [x_disc_min, x_price_min])
            # Second word: price (usually x in [x_price_min, x_name_min])
            # Remaining words: name
            discs = [w for w in sorted_by_x if x_disc_min - 10 <= w[0] < x_price_min]
            prices = [w for w in sorted_by_x if x_price_min <= w[0] < x_name_min]
            names = [w for w in sorted_by_x if w[0] >= x_name_min]
            
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
                        
            # In Makramy, text has Presentation Forms B and might be split or inverted.
            # Let's inspect how names look when sorted descending x:
            name_words_sorted = sorted(names, key=lambda w: w[0], reverse=True)
            raw_name = ' '.join(w[4] for w in name_words_sorted).strip()
            # Normalize NFKD
            raw_name = unicodedata.normalize('NFKD', raw_name)
            
            if raw_name and price_val > 0 and disc_val > 0:
                norm_name = normalize_arabic_text(raw_name)
                page_items += 1
                total_col_items += 1
                if pno == 0 and page_items <= 5:
                    print(f"  Sample P{pno+1}: Raw='{raw_name}' | Price={price_val} | Disc={disc_val}")
                    
        print(f"Page {pno+1}: {page_items} items")
    print(f"Total {col_name} items: {total_col_items}")
