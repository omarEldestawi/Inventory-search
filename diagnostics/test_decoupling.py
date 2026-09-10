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

for b in doc[0].get_text("blocks"):
    if b[0] < 210 or b[1] < 80 or b[3] > 800:
        continue
    raw_text = b[4].strip()
    if any(h in raw_text for h in ['الخصم', 'السعر', 'الصنف', 'المخزن', 'أصناف', 'شركة اروى']):
        continue
        
    text = unicodedata.normalize('NFKD', raw_text)
    
    # 1. Decouple Eastern Arabic digits from ASCII digits
    text = re.sub(r'([٠-٩]+)([0-9]+)', r'\1 \2', text)
    text = re.sub(r'([0-9]+)([٠-٩]+)', r'\1 \2', text)
    
    # 2. Decouple letters from digits
    text = re.sub(r'([a-zA-Z\u0600-\u06FF])([0-9٠-٩]+)', r'\1 \2', text)
    text = re.sub(r'([0-9٠-٩]+)([a-zA-Z\u0600-\u06FF])', r'\1 \2', text)
    
    # 3. Translate Eastern Arabic digits
    text = text.translate(EASTERN_ARABIC_DIGITS)
    
    line = ' '.join(text.split()).strip()
    
    # Extract discount (last number)
    m = re.search(r'(\d+(?:\.\d+)?)\s*$', line)
    if not m:
        continue
    disc_val = parse_discount(m.group(1))
    prefix = line[:m.start()].strip()
    
    # Extract price (number immediately before discount)
    m_price = re.search(r'(\d+(?:\.\d+)?)\s*(?:ج|جنيه)?\s*$', prefix)
    if not m_price:
        continue
    price_val = float(m_price.group(1))
    raw_name = prefix[:m_price.start()].strip()
    raw_name = re.sub(r'\b(?:ج|جنيه|س\.ج|س\.ق|سعر|جديد|قديم)\b', ' ', raw_name)
    raw_name = re.sub(r'[\s/]+$', '', raw_name).strip()
    
    if any(k in raw_name for k in ['اماريل', 'تراكايين', 'امبوفير', 'اميكاسين', 'انتوكس', 'اوجمنتين']):
        print(f"Match: Name='{raw_name}' | Price={price_val} | Disc={disc_val}")
