# -*- coding: utf-8 -*-
import pymupdf, sys

makramy_pdf = r"G:\My Drive\Pharama Daily orders\‎⁨المكرومي المنصورة⁩.pdf"
doc = pymupdf.open(makramy_pdf)

with open("makramy_deep_inspection.txt", "w", encoding="utf-8") as out:
    out.write(f"=== Makramy Mansoura: {len(doc)} pages ===\n")
    for pno in range(len(doc)):
        page = doc[pno]
        rect = page.rect
        tables = page.find_tables()
        blocks = page.get_text("blocks")
        out.write(f"\nPage {pno+1}: rect={rect}, tables={len(tables.tables)}, blocks={len(blocks)}\n")
        for tno, t in enumerate(tables):
            rows = t.extract()
            out.write(f"  Table {tno}: bbox={t.bbox}, rows={len(rows)}, cols={len(t.header.names) if t.header else None}\n")
            for rno in range(min(5, len(rows))):
                out.write(f"    R{rno}: {rows[rno]}\n")

print("Done makramy_deep_inspection.txt")
