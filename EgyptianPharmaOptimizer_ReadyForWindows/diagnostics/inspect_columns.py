# -*- coding: utf-8 -*-
import os, sys, pymupdf

drive_dir = r"G:\My Drive\Pharama Daily orders"

for fn in os.listdir(drive_dir):
    if "كيور" in fn or "المكرومي" in fn:
        fpath = os.path.join(drive_dir, fn)
        doc = pymupdf.open(fpath)
        print(f"=== {fn} (Pages: {len(doc)}) ===")
        p0 = doc[0]
        print(f"Page 0 rect: {p0.rect}")
        drawings = p0.get_drawings()
        print(f"Drawings: {len(drawings)}")
        tables = p0.find_tables()
        print(f"Tables found: {len(tables.tables)}")
        for tno, t in enumerate(tables):
            print(f"  Table {tno} bbox: {t.bbox}, row count: {len(t.extract())}")
        blocks = p0.get_text("blocks")
        print(f"Blocks found: {len(blocks)}")
        for bno, b in enumerate(blocks):
            sample = b[4].strip().replace('\n', ' // ')[:80]
            print(f"  Block {bno} bbox: ({b[0]:.1f}, {b[1]:.1f}, {b[2]:.1f}, {b[3]:.1f}) text: {sample}")
