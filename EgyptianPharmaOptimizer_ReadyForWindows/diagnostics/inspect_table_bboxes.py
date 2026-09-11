# -*- coding: utf-8 -*-
import pymupdf, sys

for pdf_name in [r"G:\My Drive\Pharama Daily orders\‎⁨كيور فارما خاص⁩.pdf", r"G:\My Drive\Pharama Daily orders\‎⁨المكرومي المنصورة⁩.pdf"]:
    doc = pymupdf.open(pdf_name)
    p0 = doc[0]
    print(f"\n==================== {pdf_name.split()[-2]} ====================")
    print(f"Page rect: {p0.rect}")
    tables = p0.find_tables()
    print(f"Tables count: {len(tables.tables)}")
    for t in tables:
        print(f"  Table bbox: {t.bbox}")
        rows = t.extract()
        print(f"  Rows: {len(rows)}, cols: {len(rows[0]) if rows else 0}")
