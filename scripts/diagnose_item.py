# -*- coding: utf-8 -*-
"""
Deep dive into specific matching failures.
"""
import os
import sys
import re
import pandas as pd

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.pdf_parser import PDFCatalogParser
from src.normalizer import (
    extract_canonical_brand,
    extract_sorted_brand_tokens,
    extract_dosage_form,
    normalize_arabic_text
)
from src.pharma_matcher import (
    extract_core_brand_root,
    extract_form_category,
    check_strength_compatibility,
    check_modifier_compatibility,
    is_safe_pharmaceutical_match,
    extract_drug_strengths_smart,
    clean_arabic_string
)

TRAIN_DIR = os.getenv("TRAIN_DIR", os.path.join(os.path.expanduser("~"), "Desktop", "train"))

# Load all catalog items
catalog_files = sorted([f for f in os.listdir(TRAIN_DIR) if f.endswith(".pdf")])
all_items = []
for f in catalog_files:
    p = os.path.join(TRAIN_DIR, f)
    parser = PDFCatalogParser(p)
    df = parser.parse()
    if not df.empty:
        for itm in df['item_name'].dropna():
            all_items.append((parser.warehouse_name, itm))

print(f"Loaded {len(all_items)} total catalog item instances.")

test_queries = [
    "انتي كوكس 6امبول",
    "انتي كوكس لبوس",
    "اوتريفين بخاخ",
    "اسيتايل سستايين 600مجم اكياس",
    "افالوكس400مجم اقراص",
    "ايفرزين لوشن",
    "افيروثيازيد20/12.5/5مجم 30قرص",
    "اسبرين بروتكت 100مجم3شريط"
]

for q in test_queries:
    print(f"\n==========================================")
    print(f"Query: '{q}'")
    cb_q = extract_canonical_brand(q)
    br_q = extract_core_brand_root(q)
    fc_q = extract_form_category(q)
    st_q = extract_drug_strengths_smart(clean_arabic_string(q))
    print(f"  Canonical Brand: '{cb_q}'")
    print(f"  Brand Root:      '{br_q}'")
    print(f"  Form Category:   '{fc_q}'")
    print(f"  Strengths:       {st_q}")
    
    # Search catalog items containing key words
    keywords = [w for w in re.split(r'\s+', br_q) if len(w) >= 3]
    hits = []
    for wh, itm in all_items:
        if any(kw in itm for kw in keywords):
            hits.append((wh, itm))
            
    print(f"  Found {len(hits)} keyword matches in catalogs.")
    for wh, itm in hits[:8]:
        cb_c = extract_canonical_brand(itm)
        br_c = extract_core_brand_root(itm)
        fc_c = extract_form_category(itm)
        st_c = extract_drug_strengths_smart(clean_arabic_string(itm))
        
        safe = is_safe_pharmaceutical_match(q, itm)
        form_compat = (fc_q == fc_c) if (fc_q != 'UNKNOWN' and fc_c != 'UNKNOWN') else True
        if fc_q in ('INJECTABLE', 'ORAL_LIQUID', 'DROPS', 'INFANT_MILK') and fc_c != fc_q:
            form_compat = False
        str_compat = check_strength_compatibility(q, itm)
        mod_compat = check_modifier_compatibility(q, itm)
        
        print(f"    Candidate: '{itm}' ({wh})")
        print(f"      SafeMatch: {safe} | FormCompat: {form_compat} ({fc_q} vs {fc_c}) | StrCompat: {str_compat} ({st_q} vs {st_c}) | ModCompat: {mod_compat}")
        print(f"      Roots: '{br_q}' vs '{br_c}' | CB: '{cb_q}' vs '{cb_c}'")
