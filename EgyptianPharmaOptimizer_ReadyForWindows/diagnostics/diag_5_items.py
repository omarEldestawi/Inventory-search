# -*- coding: utf-8 -*-
from src.pharma_matcher import *

test_cases = [
    ("اوجمنتين  625مجم اقراص", "اوجمنتين 5 2 6 مجم اقراص   7 1 1"),
    ("تيبوفورتين40مجم اقراص", "مجم 40 تيبوفورتين"),
    ("دابافيلداكتين بلس5/1000مجم س ج", "دابافیلداكتین 1000/5 بلس باكت 60"),
    ("ليفابيون 6امبول", "سيجما جنيه 96 حقن/ ليفابيون"),
    ("ميليتوفيكس تريو 25/5/1000مجم", "24424 تریو میلیتوفیکس 25/5/1000 اقراص مج")
]

for req, cand in test_cases:
    print(f"\n--- Req: '{req}' vs Cand: '{cand}' ---")
    safe = is_safe_pharmaceutical_match(req, cand)
    print(f"  SAFE: {safe}")
    if not safe:
        print(f"  Form: req='{extract_form_category(req)}' cand='{extract_form_category(cand)}'")
        print(f"  Strength: {check_strength_compatibility(req, cand)}")
        print(f"  Modifier: {check_modifier_compatibility(req, cand)}")
        print(f"  Canon brand: '{extract_canonical_brand(req)}' vs '{extract_canonical_brand(cand)}'")
        print(f"  Brand root: '{extract_core_brand_root(req)}' vs '{extract_core_brand_root(cand)}'")
