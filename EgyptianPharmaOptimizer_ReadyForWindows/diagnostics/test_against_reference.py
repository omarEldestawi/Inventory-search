# -*- coding: utf-8 -*-
import sys
import openpyxl
from src.pharma_matcher import is_safe_pharmaceutical_match, extract_core_brand_root, extract_form_category, extract_strengths_and_stages

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

wb_opt = openpyxl.load_workbook('input/Procurement_Order_Optimized.xlsx')
ws = wb_opt['Master Comparison']
opt_rows = [r for r in ws.iter_rows(values_only=True) if r and r[0] is not None and isinstance(r[0], int)]

passed = 0
failed = 0
print(f"Testing {len(opt_rows)} matches from reference template:\n")
for r in opt_rows:
    req = str(r[1]) if r[1] is not None else ''
    wh_item = str(r[6]) if r[6] is not None else ''
    is_match = is_safe_pharmaceutical_match(req, wh_item)
    if is_match:
        passed += 1
    else:
        failed += 1
        if failed <= 15:
            print(f"Req: '{req}' <-> WH: '{wh_item}'")
            print(f"   Req Form={extract_form_category(req)}, WH Form={extract_form_category(wh_item)}")
            print(f"   Req Str={extract_strengths_and_stages(req)}, WH Str={extract_strengths_and_stages(wh_item)}")
            print(f"   Req Brand={extract_core_brand_root(req)}, WH Brand={extract_core_brand_root(wh_item)}")

print(f"\nTotal passed: {passed} / {len(opt_rows)}")
