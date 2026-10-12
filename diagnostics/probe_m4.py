import os
import sys
import time
import pandas as pd

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

from src.pdf_parser import PDFCatalogParser
from src.excel_parser import load_purchase_order
from src.allocator import MedicineAllocator

TRAIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "train")

def run_probe():
    t0 = time.time()
    pdf_files = sorted([f for f in os.listdir(TRAIN_DIR) if f.lower().endswith(".pdf")])
    print(f"Discovered {len(pdf_files)} PDF catalogs in train/...")
    
    catalog_dfs = []
    for f in pdf_files:
        p = os.path.join(TRAIN_DIR, f)
        parser = PDFCatalogParser(p)
        df = parser.parse()
        print(f"  {f[:30]}: {len(df)} items", flush=True)
        catalog_dfs.append(df)
        
    unified_catalog = pd.concat(catalog_dfs, ignore_index=True)
    t_parse = time.time() - t0
    print(f"\n[CATALOGS] Total extracted offers: {len(unified_catalog)} in {t_parse:.2f}s", flush=True)
    
    # Check max price
    max_price = unified_catalog['base_price'].max()
    print(f"[CATALOGS] Max price: {max_price}", flush=True)
    
    # Load orders
    p11 = os.path.join(TRAIN_DIR, "0911.xlsx")
    p12 = os.path.join(TRAIN_DIR, "0912.xlsx")
    
    df11 = load_purchase_order(p11, drop_zero_qty=True)
    df12 = load_purchase_order(p12, drop_zero_qty=True)
    print(f"[ORDERS] 0911: {len(df11)} items, sum={df11['quantity'].sum()}", flush=True)
    print(f"[ORDERS] 0912: {len(df12)} items, sum={df12['quantity'].sum()}", flush=True)
    
    # Allocator deterministic only
    allocator = MedicineAllocator(unified_catalog, enable_ai=False)
    
    t_alloc0 = time.time()
    res11 = allocator.allocate_order(df11)
    res12 = allocator.allocate_order(df12)
    t_alloc = time.time() - t_alloc0
    print(f"\n[ALLOCATION] Completed in {t_alloc:.2f}s", flush=True)
    
    k11 = res11['kpis']
    k12 = res12['kpis']
    
    m11, t11 = k11['matched_items'], k11['total_items']
    m12, t12 = k12['matched_items'], k12['total_items']
    
    print(f"PO 0911: {m11}/{t11} matched ({m11/t11*100:.2f}%)", flush=True)
    print(f"  Public: {k11['total_public_value']:,.2f} EGP, Purchase: {k11['total_purchase_cost']:,.2f} EGP, Savings: {k11['total_savings']:,.2f} EGP ({k11['savings_pct']:.2f}%)", flush=True)
    print(f"PO 0912: {m12}/{t12} matched ({m12/t12*100:.2f}%)", flush=True)
    print(f"  Public: {k12['total_public_value']:,.2f} EGP, Purchase: {k12['total_purchase_cost']:,.2f} EGP, Savings: {k12['total_savings']:,.2f} EGP ({k12['savings_pct']:.2f}%)", flush=True)
    tot_m = m11 + m12
    tot_t = t11 + t12
    tot_spend = k11['total_purchase_cost'] + k12['total_purchase_cost']
    tot_savings = k11['total_savings'] + k12['total_savings']
    print(f"\nOVERALL: {tot_m}/{tot_t} matched ({tot_m/tot_t*100:.2f}%)", flush=True)
    print(f"TOTAL SPEND: {tot_spend:,.2f} EGP", flush=True)
    print(f"TOTAL SAVINGS: {tot_savings:,.2f} EGP", flush=True)
    
    # Wholesaler breakdown
    wh_counts = {}
    for res in [res11, res12]:
        for w, count in res['kpis']['allocation_counts'].items():
            wh_counts[w] = wh_counts.get(w, 0) + count
    print("\nWINNING WHOLESALERS BREAKDOWN:", flush=True)
    for w, c in sorted(wh_counts.items(), key=lambda x: -x[1]):
        print(f"  {w}: {c} items allocated", flush=True)

if __name__ == "__main__":
    run_probe()
