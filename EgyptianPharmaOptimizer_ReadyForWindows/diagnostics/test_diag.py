# -*- coding: utf-8 -*-
import sys, os, glob
import openpyxl
import pandas as pd
import unicodedata
import re
import pymupdf

sys.stdout.reconfigure(encoding='utf-8')

from src.pdf_parser import PDFCatalogParser
from src.normalizer import (
    normalize_vendor_name,
    extract_canonical_brand,
    extract_sorted_brand_tokens,
    clean_arabic_string,
    unreverse_arabic_text,
    EASTERN_ARABIC_DIGITS,
    parse_discount
)
from src.pharma_matcher import (
    is_safe_pharmaceutical_match,
    extract_core_brand_root,
    extract_form_category,
    check_strength_compatibility,
    check_modifier_compatibility
)

drive_dir = r"G:\My Drive\Pharama Daily orders"

# Let's inspect each PDF's parsing process directly
with open("parsing_deep_investigation.txt", "w", encoding="utf-8") as out:
    
    # 1. Inspect Cure Pharma (كيور فارما)
    cure_pdf = os.path.join(drive_dir, "‎⁨كيور فارما خاص⁩.pdf")
    cure_parser = PDFCatalogParser(cure_pdf, warehouse_name='كيور فارما')
    cure_df = cure_parser.parse()
    out.write(f"=== CURE PHARMA: {len(cure_df)} items extracted ===\n")
    
    # Let's check what Cure Pharma table rows look like
    doc = pymupdf.open(cure_pdf)
    for pno in range(len(doc)):
        tables = doc[pno].find_tables()
        for t in tables:
            rows = t.extract()
            for rno, row in enumerate(rows):
                # Search row text for any missing keyword
                row_str = ' '.join(str(c) for c in row if c)
                for kw in ['الكابرس', 'ايراستابكس', 'ايفرزين', 'بيزوكارد', 'جلوكوفاج', 'جليبوفين', 'جينتازون', 'دياسيرين', 'سيستون', 'شوجارلو', 'فيوسيدين', 'كارباميد', 'لوراز', 'ميجاليز']:
                    if kw in row_str or kw in unicodedata.normalize('NFKD', row_str):
                        out.write(f"  P{pno+1} R{rno}: raw={row}\n")
                        # Trace how _process_table handles this row
                        non_empty = [str(c).strip() for c in row if c and str(c).strip()]
                        cell_text = non_empty[0].translate(EASTERN_ARABIC_DIGITS) if non_empty else ''
                        parts = cell_text.split()
                        unrev = unreverse_arabic_text(' '.join(parts[2:])) if len(parts) >= 3 else ''
                        out.write(f"    parts={parts[:4]} | unreversed='{unrev}'\n")
                        # Check if it was in cure_df
                        in_df = cure_df[cure_df['item_name'].apply(lambda x: kw in x or kw in unicodedata.normalize('NFKD', x))]
                        out.write(f"    Extracted into cure_df: {len(in_df)} items -> {in_df['item_name'].tolist() if not in_df.empty else 'NONE'}\n")

    # 2. Inspect Makramy (المكرومي المنصورة)
    mak_pdf = os.path.join(drive_dir, "‎⁨المكرومي المنصورة⁩.pdf")
    mak_parser = PDFCatalogParser(mak_pdf, warehouse_name='مخزن المكرومي')
    mak_df = mak_parser.parse()
    out.write(f"\n=== MAKRAMY: {len(mak_df)} items extracted ===\n")
    doc_mak = pymupdf.open(mak_pdf)
    for pno in range(len(doc_mak)):
        tables = doc_mak[pno].find_tables()
        for t in tables:
            rows = t.extract()
            for rno, row in enumerate(rows):
                row_str = ' '.join(str(c) for c in row if c)
                for kw in ['اماريل', 'امبوفير', 'اميكاسين', 'انتوكس', 'اوجمنتين', 'ايفاستين', 'تيبوفورتين', 'سوبراكس', 'فروساك', 'ليفابيون', 'ميوكوسول']:
                    if kw in row_str or kw in unicodedata.normalize('NFKD', row_str):
                        out.write(f"  P{pno+1} R{rno}: raw={row}\n")
                        non_empty = [str(c).strip() for c in row if c and str(c).strip()]
                        cell_text = non_empty[0].translate(EASTERN_ARABIC_DIGITS) if non_empty else ''
                        parts = cell_text.split()
                        unrev = unreverse_arabic_text(' '.join(parts[2:])) if len(parts) >= 3 else ''
                        out.write(f"    parts={parts[:4]} | unreversed='{unrev}'\n")
                        in_df = mak_df[mak_df['item_name'].apply(lambda x: kw in x or kw in unicodedata.normalize('NFKD', x))]
                        out.write(f"    Extracted into mak_df: {len(in_df)} items -> {in_df['item_name'].tolist() if not in_df.empty else 'NONE'}\n")

    # 3. Inspect Hana Benha (هنا جمله بنها)
    hana_pdf = os.path.join(drive_dir, "‎⁨هنا جمله بنها 456⁩.pdf")
    hana_parser = PDFCatalogParser(hana_pdf, warehouse_name='مخزن هنا جملة')
    hana_df = hana_parser.parse()
    out.write(f"\n=== HANA BENHA: {len(hana_df)} items extracted ===\n")
    for kw in ['كولوسبازمين', 'ميليتوفيكس']:
        in_df = hana_df[hana_df['item_name'].apply(lambda x: kw in x or kw in unicodedata.normalize('NFKD', x))]
        out.write(f"  Keyword '{kw}' in hana_df: {len(in_df)} items -> {in_df['item_name'].tolist() if not in_df.empty else 'NONE'}\n")
        
    # 4. Inspect Forsan / Oroud Momayaz (عروض مميز / الفرسان بنها)
    forsan_pdf = os.path.join(drive_dir, "‎⁨عروض مميز⁩.pdf")
    forsan_parser = PDFCatalogParser(forsan_pdf, warehouse_name='عروض مميز')
    forsan_df = forsan_parser.parse()
    out.write(f"\n=== FORSAN / OROUD MOMAYAZ: {len(forsan_df)} items extracted ===\n")
    for kw in ['دابافيلداكتين', 'دابافيل', 'دابافیل', 'ميروكسنوريك', 'میروكسنوریك', 'تيراليبسي', 'تیرالیبسی', 'ريموواكس', 'ریموواكس']:
        in_df = forsan_df[forsan_df['item_name'].apply(lambda x: kw in x or kw in unicodedata.normalize('NFKD', x))]
        out.write(f"  Keyword '{kw}' in forsan_df: {len(in_df)} items -> {in_df['item_name'].tolist() if not in_df.empty else 'NONE'}\n")

print("Investigation written to parsing_deep_investigation.txt")
sys.exit(0)



all_catalogs = []
catalog_stats = {}
raw_pdf_docs = {}

for pdf in pdf_files:
    raw_name = os.path.splitext(os.path.basename(pdf))[0]
    w_name = normalize_vendor_name(raw_name)
    parser_inst = PDFCatalogParser(pdf, warehouse_name=w_name)
    df = parser_inst.parse()
    catalog_stats[raw_name] = {'vendor': w_name, 'count': len(df), 'path': pdf}
    if not df.empty:
        df['_source_file'] = raw_name
        all_catalogs.append(df)
    try:
        raw_pdf_docs[raw_name] = pymupdf.open(pdf)
    except Exception as e:
        pass

for exc in excel_catalog_files:
    raw_name = os.path.splitext(os.path.basename(exc))[0]
    w_name = normalize_vendor_name(raw_name)
    df = parse_excel_catalog(exc, warehouse_name=w_name)
    catalog_stats[raw_name] = {'vendor': w_name, 'count': len(df), 'path': exc}
    if not df.empty:
        df['_source_file'] = raw_name
        all_catalogs.append(df)

consolidated_inv = pd.concat(all_catalogs, ignore_index=True) if all_catalogs else pd.DataFrame()

# Detailed per-item trace for each missing item
with open("diag_results.txt", "w", encoding="utf-8") as out:
    out.write("=== CATALOG EXTRACTION STATS ===\n")
    for raw_name, info in catalog_stats.items():
        out.write(f"File: {raw_name} -> Vendor: '{info['vendor']}' -> Items Extracted: {info['count']}\n")
    out.write(f"Total Consolidated Items: {len(consolidated_inv)}\n\n")

    out.write("=== SUMMARY ===\n")
    out.write(f"Benchmark total: {len(bench_items)}\n")
    out.write(f"Our total: {len(our_items)}\n")
    out.write(f"Common items: {len(matched_both)}\n")
    out.write(f"Missing from our output: {len(missing_from_ours)}\n")
    out.write(f"Extra in our output: {len(extra_in_ours)}\n\n")

    out.write("========================================================================\n")
    out.write("=== DETAILED INVESTIGATION OF ALL 31 MISSING ITEMS ===\n")
    out.write("========================================================================\n\n")

    for i, b in enumerate(missing_from_ours, 1):
        out.write(f"------------------------------------------------------------------------\n")
        out.write(f"Missing Item #{i:02d} (Benchmark #{b['num']}):\n")
        out.write(f"  Requested Item : '{b['req_name']}'\n")
        out.write(f"  Bench Matched  : '{b['cat_name']}'\n")
        out.write(f"  Bench Winner   : '{b['winner']}' | Discount: {b['discount']} | Price: {b['public_price']}\n")
        
        # 1. Check if bench cat_name exists in consolidated_inv
        b_cat = b['cat_name']
        exact_inv = consolidated_inv[consolidated_inv['item_name'] == b_cat]
        norm_b_cat = norm(b_cat)
        fuzzy_inv = consolidated_inv[consolidated_inv['item_name'].apply(lambda x: norm_b_cat in norm(x) or norm(x) in norm_b_cat)]
        
        # Also check partial word match in inventory
        words_b_cat = [w for w in norm_b_cat.split() if len(w) >= 3 and not w.isdigit()]
        if words_b_cat:
            first_word = words_b_cat[0]
            word_matches = consolidated_inv[consolidated_inv['item_name'].apply(lambda x: first_word in norm(x))]
        else:
            word_matches = pd.DataFrame()

        # 2. Check if text exists in raw PDF docs
        found_in_raw = []
        for pdf_name, doc in raw_pdf_docs.items():
            for p_num, page in enumerate(doc):
                txt = page.get_text()
                # Check for first significant word
                for kw in [b_cat] + words_b_cat[:2]:
                    if kw and kw in txt:
                        found_in_raw.append((pdf_name, p_num + 1, kw))
                        break

        out.write(f"  Extraction Status:\n")
        if not exact_inv.empty:
            out.write(f"    [EXACT INVENTORY MATCH]: Found {len(exact_inv)} listings in inventory.\n")
            for _, row in exact_inv.iterrows():
                out.write(f"      -> Vendor: '{row['warehouse_name']}' | Item: '{row['item_name']}' | Disc: {row['discount_rate']} | Price: {row['base_price']}\n")
        elif not fuzzy_inv.empty:
            out.write(f"    [FUZZY INVENTORY MATCH]: Found {len(fuzzy_inv)} close listings in inventory.\n")
            for _, row in fuzzy_inv.head(3).iterrows():
                out.write(f"      -> Vendor: '{row['warehouse_name']}' | Item: '{row['item_name']}' | Disc: {row['discount_rate']} | Price: {row['base_price']}\n")
        else:
            out.write(f"    [NOT IN EXTRACTED INVENTORY]: Benchmark catalog string '{b_cat}' not extracted.\n")
            if not word_matches.empty:
                out.write(f"    Inventory with keyword '{first_word}': {len(word_matches)} items found.\n")
                for _, row in word_matches.head(3).iterrows():
                    out.write(f"      -> Vendor: '{row['warehouse_name']}' | Item: '{row['item_name']}'\n")

        if found_in_raw:
            out.write(f"    Raw PDF Search:\n")
            for f_pdf, p_no, kw in found_in_raw[:3]:
                out.write(f"      -> Found keyword '{kw}' in PDF '{f_pdf}' on Page {p_no}\n")
        else:
            out.write(f"    Raw PDF Search: Keyword not found in any raw PDF text.\n")

        # 3. Pharmaceutical Safety & Compatibility Check
        out.write(f"  Pharma Matcher Diagnostic:\n")
        req_item = b['req_name']
        cand_item = b['cat_name']
        
        # Test candidate generation tokens
        cb_req = extract_canonical_brand(req_item)
        cb_cand = extract_canonical_brand(cand_item)
        sb_req = extract_sorted_brand_tokens(req_item)
        sb_cand = extract_sorted_brand_tokens(cand_item)
        br_req = extract_core_brand_root(req_item)
        br_cand = extract_core_brand_root(cand_item)
        
        out.write(f"    Tokens for Req : canonical='{cb_req}', sorted='{sb_req}', root='{br_req}'\n")
        out.write(f"    Tokens for Cand: canonical='{cb_cand}', sorted='{sb_cand}', root='{br_cand}'\n")
        
        form_req = extract_form_category(req_item)
        form_cand = extract_form_category(cand_item)
        out.write(f"    Dosage Form: Req='{form_req}', Cand='{form_cand}' -> Compatible: {form_req == 'UNKNOWN' or form_cand == 'UNKNOWN' or form_req == form_cand}\n")
        
        str_compat = check_strength_compatibility(req_item, cand_item)
        out.write(f"    Strength Compat: {str_compat}\n")
        
        mod_req = extract_modifiers(req_item)
        mod_cand = extract_modifiers(cand_item)
        mod_compat = check_modifier_compatibility(req_item, cand_item)
        out.write(f"    Modifier Compat: {mod_compat} (Req: {mod_req}, Cand: {mod_cand})\n")
        
        safe_match = is_safe_pharmaceutical_match(req_item, cand_item)
        out.write(f"    is_safe_pharmaceutical_match: {safe_match}\n")

        # What was the root failure reason?
        failure_reasons = []
        if exact_inv.empty and fuzzy_inv.empty:
            failure_reasons.append("PDF_NOT_EXTRACTED: Catalog item not extracted by PDFCatalogParser")
        if not (cb_req == cb_cand or sb_req == sb_cand or br_req == br_cand or (br_req and br_cand and (br_req in br_cand or br_cand in br_req))):
            failure_reasons.append("TOKEN_MISMATCH: Brand tokens between req and cand do not match in index")
        if form_req != 'UNKNOWN' and form_cand != 'UNKNOWN' and form_req != form_cand:
            failure_reasons.append(f"FORM_MISMATCH: Req form {form_req} != Cand form {form_cand}")
        if not str_compat:
            failure_reasons.append("STRENGTH_MISMATCH: Strength ratio or active strength rejected")
        if not mod_compat:
            failure_reasons.append("MODIFIER_MISMATCH: Formulation modifiers do not match")
        if not safe_match:
            failure_reasons.append("SAFETY_REJECTED: Rejected by is_safe_pharmaceutical_match")
            
        out.write(f"  Root Cause Assessment: {'; '.join(failure_reasons) if failure_reasons else 'VALID_MATCH_BUT_NOT_SELECTED'}\n\n")

    out.write("========================================================================\n")
    out.write("=== ANALYSIS OF 10 EXTRA ITEMS IN OUR OUTPUT ===\n")
    out.write("========================================================================\n\n")
    for i, o in enumerate(extra_in_ours, 1):
        out.write(f"{i}. Req: '{o['req_name']}'\n")
        out.write(f"   Our Matched: '{o['cat_name']}' (Winner: '{o['winner']}', Disc: {o['discount']}, Price: {o['public_price']})\n")
        form_r = extract_form_category(o['req_name'])
        form_c = extract_form_category(o['cat_name'])
        str_c = check_strength_compatibility(o['req_name'], o['cat_name'])
        mod_c = check_modifier_compatibility(o['req_name'], o['cat_name'])
        out.write(f"   Form: Req={form_r} vs Cand={form_c} | Strength Compat={str_c} | Mod Compat={mod_c}\n")
        out.write(f"   Safety Match: {is_safe_pharmaceutical_match(o['req_name'], o['cat_name'])}\n\n")

print("Detailed diagnostic finished. Written to diag_results.txt")



