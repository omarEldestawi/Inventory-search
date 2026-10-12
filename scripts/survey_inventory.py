r"""
Survey Inventory and Matching Coverage across 23 PDFs and 2 Excel POs in C:\Users\omart\Desktop\train.
"""
import os
import sys
import json
import re
import pandas as pd

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
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
    parse_dosage_and_pack,
    ARABIC_TO_ENGLISH_BRANDS,
    CANONICAL_NOISE_WORDS
)
from src.pharma_matcher import (
    extract_core_brand_root,
    extract_form_category,
    is_safe_pharmaceutical_match,
    check_strength_compatibility,
    check_modifier_compatibility
)
from src.allocator import MedicineAllocator

TRAIN_DIR = r"C:\Users\omart\Desktop\train"
if not os.path.isdir(TRAIN_DIR):
    TRAIN_DIR = os.path.join(PROJECT_ROOT, "train")
OUTPUT_REPORT = os.path.join(PROJECT_ROOT, "scripts", "survey_report.json")

def main():
    print("Starting comprehensive survey...")
    
    # 1. Inspect Excel POs
    po_files = ["0911.xlsx", "0912.xlsx"]
    po_data = {}
    all_po_items = {}
    
    for f in po_files:
        path = os.path.join(TRAIN_DIR, f)
        if not os.path.exists(path):
            print(f"PO file not found: {path}")
            continue
        try:
            df = load_purchase_order(path)
            items = df.to_dict(orient="records")
            po_data[f] = {
                "count": len(items),
                "items": [it["requested_item"] for it in items]
            }
            for it in items:
                name = it["requested_item"]
                all_po_items[name] = all_po_items.get(name, 0) + it.get("quantity", 1)
        except Exception as e:
            print(f"Error loading PO {f}: {e}")
            po_data[f] = {"error": str(e)}

    print(f"Loaded {len(po_data)} POs with {len(all_po_items)} unique combined items.")

    # 2. Ingest 23 PDF Catalogs (Digital parsing)
    catalog_files = [f for f in os.listdir(TRAIN_DIR) if f.endswith(".pdf")]
    catalog_stats = {}
    all_catalog_records = []
    
    for f in sorted(catalog_files):
        pdf_path = os.path.join(TRAIN_DIR, f)
        parser = PDFCatalogParser(pdf_path)
        try:
            cat_df = parser.parse()
            records = cat_df.to_dict(orient="records") if not cat_df.empty else []
            all_catalog_records.extend(records)
            
            # Language analysis
            arabic_count = 0
            english_count = 0
            for r in records:
                name = r.get("item_name", "")
                has_ar = bool(re.search(r'[\u0600-\u06ff]', name))
                has_en = bool(re.search(r'[a-zA-Z]', name))
                if has_ar:
                    arabic_count += 1
                elif has_en:
                    english_count += 1

            catalog_stats[f] = {
                "warehouse_name": parser.warehouse_name,
                "item_count": len(records),
                "arabic_count": arabic_count,
                "english_count": english_count,
                "sample_items": [r.get("item_name", "") for r in records[:5]]
            }
            print(f"Parsed {f}: {len(records)} items (Warehouse: {parser.warehouse_name})")
        except Exception as e:
            print(f"Error parsing PDF {f}: {e}")
            catalog_stats[f] = {"error": str(e), "item_count": 0}

    total_catalog_items = len(all_catalog_records)
    print(f"Total catalog records: {total_catalog_items}")
    catalog_df = pd.DataFrame(all_catalog_records) if all_catalog_records else pd.DataFrame()

    # 3. Allocation and Matching Analysis
    allocator = MedicineAllocator(catalog_df)
    
    # Analyze PO items against allocator
    matching_analysis = {}
    for po_name, p_data in po_data.items():
        if "items" not in p_data:
            continue
        items_list = p_data["items"]
        df_order = pd.DataFrame([{"requested_item": it, "quantity": 1} for it in items_list])
        alloc_res = allocator.allocate_order(df_order)
        master = alloc_res["master_comparison"]
        oos = alloc_res["out_of_stock"]
        kpis = alloc_res["kpis"]
        
        matched_items_detail = []
        if not master.empty:
            for _, r in master.iterrows():
                matched_items_detail.append({
                    "requested": r.get("اسم الصنف في أمر الشراء") or r.get("اسم الصنف المطلوب") or "",
                    "matched_catalog": r.get("اسم الصنف في كشف المخزن الفائز") or r.get("اسم الصنف في كتالوج المخزن الفائز") or "",
                    "warehouse": r.get("المخزن الفائز", ""),
                    "discount": r.get("أعلى خصم %", 0.0)
                })
        
        unmatched_items_detail = []
        if not oos.empty:
            for _, r in oos.iterrows():
                req = r["اسم الصنف المطلوب"]
                # Diagnose why it failed
                # 1. Is canonical brand found?
                cb = extract_canonical_brand(req)
                br = extract_core_brand_root(req)
                sb = extract_sorted_brand_tokens(req)
                fc = extract_form_category(req)
                
                # Check candidate matches in catalog_df
                potential_hits = []
                for _, crow in catalog_df.iterrows():
                    c_name = crow["item_name"]
                    c_cb = extract_canonical_brand(c_name)
                    c_br = extract_core_brand_root(c_name)
                    if (cb and cb == c_cb) or (br and br in c_br) or (c_br and c_br in br):
                        # Why rejected?
                        form_ok = extract_form_category(req) == extract_form_category(c_name)
                        str_ok = check_strength_compatibility(req, c_name)
                        mod_ok = check_modifier_compatibility(req, c_name)
                        potential_hits.append({
                            "candidate": c_name,
                            "form_ok": form_ok,
                            "str_ok": str_ok,
                            "mod_ok": mod_ok
                        })
                        if len(potential_hits) >= 3:
                            break
                            
                unmatched_items_detail.append({
                    "requested": req,
                    "canonical_brand": cb,
                    "brand_root": br,
                    "form_category": fc,
                    "potential_candidates": potential_hits
                })
                
        matching_analysis[po_name] = {
            "total_items": kpis["total_items"],
            "matched_items": kpis["matched_items"],
            "out_of_stock": kpis["out_of_stock"],
            "avg_discount": kpis["avg_discount"],
            "num_warehouses": kpis["num_warehouses"],
            "matched_samples": matched_items_detail[:10],
            "unmatched_samples": unmatched_items_detail
        }

    # Summary Report
    report = {
        "po_stats": {k: {"count": v.get("count", 0)} for k, v in po_data.items()},
        "catalog_stats": catalog_stats,
        "total_catalog_records": total_catalog_items,
        "matching_analysis": matching_analysis,
        "current_brand_dictionary_count": len(ARABIC_TO_ENGLISH_BRANDS)
    }

    with open(OUTPUT_REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"Survey analysis complete! Written to {OUTPUT_REPORT}")

if __name__ == "__main__":
    main()
