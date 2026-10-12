r"""
Fast survey of 23 PDFs and 2 Excel POs in train dataset.
Optimized with O(1) index lookups, real-time stdout flushing, and detailed breakdown.
"""
import os
import sys
import json
import re
import unicodedata
import pandas as pd

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
        sys.stderr.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        pass

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.pdf_parser import PDFCatalogParser
from src.excel_parser import load_purchase_order
from src.normalizer import (
    normalize_arabic_text,
    extract_canonical_brand,
    extract_sorted_brand_tokens,
    extract_dosage_form,
    ARABIC_TO_ENGLISH_BRANDS
)
from src.pharma_matcher import (
    extract_core_brand_root,
    extract_form_category,
    check_strength_compatibility,
    check_modifier_compatibility
)
from src.allocator import MedicineAllocator

TRAIN_DIR = os.getenv("TRAIN_DIR", os.path.join(os.path.expanduser("~"), "Desktop", "train"))
OUTPUT_REPORT = os.path.join(PROJECT_ROOT, "scripts", "fast_survey_report.json")

def main():
    print("=== STARTING FAST PHARMA PROCUREMENT SURVEY ===", flush=True)

    # 1. Inspect Excel POs
    po_files = ["0911.xlsx", "0912.xlsx"]
    po_dfs = {}
    for f in po_files:
        path = os.path.join(TRAIN_DIR, f)
        if os.path.exists(path):
            df = load_purchase_order(path)
            po_dfs[f] = df
            print(f"PO '{f}': {len(df)} distinct requested items after aggregation.", flush=True)
        else:
            print(f"PO '{f}' NOT FOUND at {path}", flush=True)

    # 2. Ingest 23 PDF Catalogs
    pdf_files = sorted([f for f in os.listdir(TRAIN_DIR) if f.endswith(".pdf")])
    print(f"Discovered {len(pdf_files)} PDF catalog files in {TRAIN_DIR}.", flush=True)

    all_catalog_rows = []
    catalog_metrics = {}

    for i, f in enumerate(pdf_files, 1):
        pdf_path = os.path.join(TRAIN_DIR, f)
        parser = PDFCatalogParser(pdf_path)
        try:
            df = parser.parse()
            rows = df.to_dict(orient="records") if not df.empty else []
            all_catalog_rows.extend(rows)
            
            ar_count = 0
            en_count = 0
            for r in rows:
                nm = r.get("item_name", "")
                if re.search(r'[\u0600-\u06ff]', nm):
                    ar_count += 1
                elif re.search(r'[a-zA-Z]', nm):
                    en_count += 1

            catalog_metrics[f] = {
                "warehouse": parser.warehouse_name,
                "items": len(rows),
                "arabic_items": ar_count,
                "english_items": en_count
            }
            print(f"[{i}/{len(pdf_files)}] Parsed '{f}' -> {len(rows)} items (Warehouse: '{parser.warehouse_name}')", flush=True)
        except Exception as e:
            print(f"[{i}/{len(pdf_files)}] ERROR parsing '{f}': {e}", flush=True)
            catalog_metrics[f] = {"error": str(e), "items": 0}

    total_cat_items = len(all_catalog_rows)
    print(f"\nTotal catalog items extracted: {total_cat_items}", flush=True)

    catalog_df = pd.DataFrame(all_catalog_rows) if all_catalog_rows else pd.DataFrame()

    # Build unique catalog brand vocabulary
    cat_items_unique = sorted(list(catalog_df['item_name'].dropna().unique())) if not catalog_df.empty else []
    print(f"Unique catalog item strings: {len(cat_items_unique)}", flush=True)

    # 3. Benchmark Deterministic Allocation on POs
    print("\nInitializing MedicineAllocator on catalog inventory...", flush=True)
    allocator = MedicineAllocator(catalog_df)

    po_results = {}
    for po_name, po_df in po_dfs.items():
        print(f"\n--- Allocating Order: {po_name} ({len(po_df)} items) ---", flush=True)
        alloc_res = allocator.allocate_order(po_df)
        kpis = alloc_res["kpis"]
        master = alloc_res["master_comparison"]
        oos = alloc_res["out_of_stock"]

        match_rate = round(kpis["matched_items"] / kpis["total_items"] * 100, 1) if kpis["total_items"] > 0 else 0.0
        print(f"Results for {po_name}:", flush=True)
        print(f"  Total Items: {kpis['total_items']}", flush=True)
        print(f"  Matched Items: {kpis['matched_items']} ({match_rate}%)", flush=True)
        print(f"  Out of Stock: {kpis['out_of_stock']}", flush=True)
        print(f"  Avg Discount: {kpis['avg_discount']}%", flush=True)
        print(f"  Winning Wholesalers: {kpis['num_warehouses']}", flush=True)

        # 4. Diagnose Out-of-Stock Items
        # Check why items failed:
        # Pre-build lookup sets from catalog for fast analysis
        cat_brands_ar = set()
        cat_brands_en = set()
        for c in cat_items_unique:
            b_ar = extract_core_brand_root(c)
            if b_ar:
                cat_brands_ar.add(b_ar)
                cat_brands_ar.add(b_ar.replace(' ', ''))
            words = re.findall(r'[a-zA-Z]{3,}', c)
            for w in words:
                cat_brands_en.add(w.lower())

        unmatched_diagnostic = []
        if not oos.empty:
            for _, r in oos.iterrows():
                req = r["اسم الصنف المطلوب"]
                req_ar = bool(re.search(r'[\u0600-\u06ff]', req))
                req_en = bool(re.search(r'[a-zA-Z]', req))
                cb = extract_canonical_brand(req)
                br = extract_core_brand_root(req)
                fc = extract_form_category(req)

                # Check if brand words exist in English or Arabic catalog
                req_en_words = [w.lower() for w in re.findall(r'[a-zA-Z]{3,}', req)]
                has_en_match = any(w in cat_brands_en for w in req_en_words)
                has_ar_match = (br in cat_brands_ar) or (br.replace(' ', '') in cat_brands_ar)

                unmatched_diagnostic.append({
                    "requested": req,
                    "lang": "AR" if req_ar and not req_en else ("EN" if req_en and not req_ar else "MIXED"),
                    "canonical_brand": cb,
                    "brand_root": br,
                    "form": fc,
                    "has_exact_brand_in_catalog": has_ar_match or has_en_match,
                    "in_dictionary": cb in ARABIC_TO_ENGLISH_BRANDS.values()
                })

        po_results[po_name] = {
            "kpis": kpis,
            "match_rate": match_rate,
            "unmatched_items": unmatched_diagnostic
        }

    # Summary
    report = {
        "catalog_metrics": catalog_metrics,
        "total_catalog_items": total_cat_items,
        "unique_catalog_items": len(cat_items_unique),
        "po_results": po_results,
        "current_dict_size": len(ARABIC_TO_ENGLISH_BRANDS)
    }

    with open(OUTPUT_REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n=== SURVEY FINISHED SUCCESSFULY! Saved to {OUTPUT_REPORT} ===", flush=True)

if __name__ == "__main__":
    main()
