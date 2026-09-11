# -*- coding: utf-8 -*-
import os, sys, re, unicodedata, openpyxl, pandas as pd
import pymupdf

from src.pdf_parser import PDFCatalogParser
from src.normalizer import (
    normalize_vendor_name,
    extract_canonical_brand,
    extract_sorted_brand_tokens,
    unreverse_arabic_text,
    normalize_arabic_text,
    EASTERN_ARABIC_DIGITS,
    parse_discount
)
from src.pharma_matcher import (
    clean_arabic_string,
    is_safe_pharmaceutical_match,
    extract_core_brand_root,
    extract_form_category,
    check_strength_compatibility,
    check_modifier_compatibility,
    extract_drug_strengths_smart,
    extract_modifiers
)
from src.allocator import MedicineAllocator

drive_dir = r"G:\My Drive\Pharama Daily orders"
bench_path = r"C:\Users\omart\Downloads\Procurement_Order_Optimized_2026-09-10.xlsx"
out_path = r"G:\My Drive\Pharama Daily orders\Procurement_Order_Optimized_2026-09-10.xlsx"

wb_b = openpyxl.load_workbook(bench_path, data_only=True)
ws_b = wb_b['المقارنة الشاملة وتوزيع الأصناف']
b_rows = list(ws_b.iter_rows(values_only=True))

wb_o = openpyxl.load_workbook(out_path, data_only=True)
ws_o = wb_o['المقارنة الشاملة وتوزيع الأصناف']
o_rows = list(ws_o.iter_rows(values_only=True))

bench_items = []
for r in b_rows[6:]:
    if r[0] is not None and isinstance(r[0], int):
        bench_items.append({
            'num': r[0],
            'req': str(r[1]).strip() if r[1] else '',
            'bench_item': str(r[2]).strip() if r[2] else '',
            'qty': r[3],
            'winner': str(r[4]).strip() if r[4] else '',
            'disc': r[5],
            'price': r[6]
        })

out_reqs = set()
for r in o_rows[8:]:
    if r[0] is not None and isinstance(r[0], int):
        if r[1]:
            out_reqs.add(str(r[1]).strip())

missing = [b for b in bench_items if b['req'] not in out_reqs]
print(f"Missing count: {len(missing)}")

# Map suppliers to PDFs
supplier_files = {
    'كيور فارما': '‎⁨كيور فارما خاص⁩.pdf',
    'المكرومي المنصورة': '‎⁨المكرومي المنصورة⁩.pdf',
    'الفرسان بنها': '‎⁨عروض مميز⁩.pdf',
    'هنا جمله بنها': '‎⁨هنا جمله بنها 456⁩.pdf'
}

# Parse all PDFs
parsed_dfs = {}
raw_docs = {}
for clean_n, fname in [
    ('كيور فارما', '‎⁨كيور فارما خاص⁩.pdf'),
    ('المكرومي المنصورة', '‎⁨المكرومي المنصورة⁩.pdf'),
    ('الفرسان بنها', '‎⁨عروض مميز⁩.pdf'),
    ('هنا جمله بنها', '‎⁨هنا جمله بنها 456⁩.pdf')
]:
    fpath = os.path.join(drive_dir, fname)
    parser = PDFCatalogParser(fpath, warehouse_name=clean_n)
    df = parser.parse()
    parsed_dfs[clean_n] = df
    raw_docs[clean_n] = pymupdf.open(fpath)

print("Parsed all 4 relevant catalogs.")

results = []
for it in missing:
    num = it['num']
    req = it['req']
    b_item = it['bench_item']
    supp = it['winner']
    
    # Check safety gate
    safe = is_safe_pharmaceutical_match(req, b_item)
    f_req = extract_form_category(req)
    f_cand = extract_form_category(b_item)
    form_ok = (f_req == 'UNKNOWN' or f_cand == 'UNKNOWN' or f_req == f_cand)
    str_ok = check_strength_compatibility(req, b_item)
    mod_ok = check_modifier_compatibility(req, b_item)
    c_brand_req = extract_canonical_brand(req)
    c_brand_cand = extract_canonical_brand(b_item)
    s_brand_req = extract_sorted_brand_tokens(req)
    s_brand_cand = extract_sorted_brand_tokens(b_item)
    
    df_supp = parsed_dfs.get(supp, pd.DataFrame())
    extracted_exact = df_supp[df_supp['item_name'] == b_item] if not df_supp.empty else pd.DataFrame()
    
    c_root = extract_core_brand_root(req)
    extracted_partial = pd.DataFrame()
    if not df_supp.empty:
        extracted_partial = df_supp[df_supp['item_name'].str.contains(c_root, na=False, regex=False)]
        if extracted_partial.empty:
            # try first 4 letters of brand
            root4 = c_root[:4] if len(c_root) >= 4 else c_root
            extracted_partial = df_supp[df_supp['item_name'].str.contains(root4, na=False, regex=False)]
            
    # Search raw PDF
    doc = raw_docs.get(supp)
    raw_found = []
    if doc:
        for pno in range(len(doc)):
            p_text = doc[pno].get_text()
            if b_item in p_text or c_root in p_text:
                raw_found.append(pno + 1)
            # also search inside tables of page
            tables = doc[pno].find_tables()
            for t in tables:
                t_rows = t.extract()
                for r in t_rows:
                    row_s = ' '.join(str(c) for c in r if c)
                    if (b_item and b_item in row_s) or (c_root and c_root in row_s):
                        raw_found.append(f"P{pno+1}_T")
                        break
                        
    results.append({
        'num': num,
        'req': req,
        'bench_item': b_item,
        'supp': supp,
        'safe': safe,
        'form_ok': form_ok,
        'f_req': f_req,
        'f_cand': f_cand,
        'str_ok': str_ok,
        's_req': extract_drug_strengths_smart(req),
        's_cand': extract_drug_strengths_smart(b_item),
        'mod_ok': mod_ok,
        'm_req': extract_modifiers(req),
        'm_cand': extract_modifiers(b_item),
        'c_brand_req': c_brand_req,
        'c_brand_cand': c_brand_cand,
        's_brand_req': s_brand_req,
        's_brand_cand': s_brand_cand,
        'extracted_exact_count': len(extracted_exact),
        'extracted_partial_count': len(extracted_partial),
        'extracted_partial_items': extracted_partial['item_name'].tolist()[:3] if not extracted_partial.empty else [],
        'raw_pages': list(set(raw_found))
    })

with open('investigate_31_out.txt', 'w', encoding='utf-8') as out:
    for r in results:
        out.write(f"#{r['num']:02d} | Req: {r['req']}\n")
        out.write(f"    Bench Item : {r['bench_item']} (Supp: {r['supp']})\n")
        out.write(f"    Raw PDF hits: {r['raw_pages']}\n")
        out.write(f"    Extracted Exact: {r['extracted_exact_count']} | Extracted Partial: {r['extracted_partial_count']}\n")
        if r['extracted_partial_items']:
            out.write(f"    Partial Items in Catalog DF: {r['extracted_partial_items']}\n")
        out.write(f"    Pharma Matcher: SAFE={r['safe']}\n")
        out.write(f"        Form OK: {r['form_ok']} (req={r['f_req']}, cand={r['f_cand']})\n")
        out.write(f"        Strength OK: {r['str_ok']} (req={r['s_req']}, cand={r['s_cand']})\n")
        out.write(f"        Modifier OK: {r['mod_ok']} (req={r['m_req']}, cand={r['m_cand']})\n")
        out.write(f"        Brand Match: c_brand='{r['c_brand_req']}' vs '{r['c_brand_cand']}', s_brand='{r['s_brand_req']}' vs '{r['s_brand_cand']}'\n\n")

print("Done. Saved to investigate_31_out.txt")
