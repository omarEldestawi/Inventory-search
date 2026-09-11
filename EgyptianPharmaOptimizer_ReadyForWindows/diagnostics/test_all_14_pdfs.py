# -*- coding: utf-8 -*-
import sys
import os
import glob
import pandas as pd

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from src.pdf_parser import PDFCatalogParser

pdf_files = sorted(glob.glob('input/catalogs/*.pdf'))
print(f"Testing extraction on {len(pdf_files)} PDF catalogs:\n")

total_listings = 0
for pdf in pdf_files:
    fname = os.path.basename(pdf)
    parser = PDFCatalogParser(pdf)
    df = parser.parse()
    print(f"• {fname:<38} : {len(df):>4} items extracted")
    if not df.empty:
        total_listings += len(df)
        # show sample
        sample_names = df['item_name'].head(3).tolist()
        print(f"    Sample: {sample_names}")
    else:
        print("    [!] FAILED TO EXTRACT ANY ITEMS")

print(f"\nTotal items extracted across all catalogs: {total_listings}")
