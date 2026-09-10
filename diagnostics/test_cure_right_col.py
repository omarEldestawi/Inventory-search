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

doc = pymupdf.open(r"G:\My Drive\Pharama Daily orders\‎⁨كيور فارما خاص⁩.pdf")
right_rect = pymupdf.Rect(305, 80, 590, 790)

all_items = []
for pno in range(len(doc)):
    page = doc[pno]
    words = page.get_text("words", clip=right_rect)
    
    # Cluster words by y coordinate
    y_buckets = {}
    for w in words:
        y_val = round(w[1], 1)
        # Find matching bucket within 3.5 points
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
        # In Cure right column:
        # Discount is at left of column (x around 320-335)
        # Price is next to it (x around 365-390)
        # Name is at the right (x > 400), ordered from right to left (descending x)
        sorted_by_x = sorted(row_words, key=lambda w: w[0])
        
        # Check if we have numbers
        # Let's inspect words
        discs = [w for w in sorted_by_x if 315 <= w[0] <= 345]
        prices = [w for w in sorted_by_x if 355 <= w[0] <= 405]
        names = [w for w in sorted_by_x if w[0] >= 405]
        
        # Also handle cases where price or discount is slightly shifted
        disc_val = 0.0
        price_val = 0.0
        
        if discs:
            disc_text = discs[0][4]
            disc_val = parse_discount(disc_text)
            
        if prices:
            price_text = prices[0][4]
            try:
                price_val = float(price_text.translate(EASTERN_ARABIC_DIGITS))
            except ValueError:
                m = re.search(r'[-+]?\d*\.?\d+', price_text.translate(EASTERN_ARABIC_DIGITS))
                if m:
                    price_val = float(m.group())
                    
        # Name words in Arabic reading order (descending x)
        name_words_sorted = sorted(names, key=lambda w: w[0], reverse=True)
        raw_name = ' '.join(w[4] for w in name_words_sorted).strip()
        
        # Normalize and clean
        if raw_name and price_val > 0 and disc_val > 0:
            norm_name = normalize_arabic_text(raw_name)
            all_items.append((pno+1, raw_name, norm_name, price_val, disc_val))
            page_items += 1
        else:
            # print if not parsed to see edge cases
            pass
            
    print(f"Page {pno+1}: {page_items} items extracted from right column")

print(f"Total right column items: {len(all_items)}")
print("\nFirst 10 items:")
for item in all_items[:10]:
    print(f"  P{item[0]}: Name='{item[1]}' (Norm='{item[2]}') | Price={item[3]} | Disc={item[4]}")
