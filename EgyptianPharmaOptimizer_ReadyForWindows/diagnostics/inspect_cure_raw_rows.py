# -*- coding: utf-8 -*-
import pymupdf, sys

cure_pdf = r"G:\My Drive\Pharama Daily orders\‎⁨كيور فارما خاص⁩.pdf"
doc = pymupdf.open(cure_pdf)

with open("cure_raw_inspection.txt", "w", encoding="utf-8") as out:
    for pno in range(len(doc)):
        page = doc[pno]
        tables = page.find_tables()
        out.write(f"=== PAGE {pno+1}: {len(tables.tables)} tables ===\n")
        for tno, t in enumerate(tables):
            rows = t.extract()
            out.write(f"  Table {tno}: {len(rows)} rows, {len(t.header.names) if t.header else 'no header'} cols\n")
            for rno, r in enumerate(rows):
                r_str = " | ".join(str(c).strip() for c in r if c and str(c).strip())
                # If any of our missing items are in r_str
                for kw in ['الكابرس', 'ايراستابكس', 'ايفرزين', 'بيزوكارد', 'جلوكوفاج', 'جليبوفين', 'جينتازون', 'دياسيرين', 'سيستون', 'شوجارلو', 'فيوسيدين', 'كارباميد', 'لوراز', 'ميجاليز']:
                    if kw in r_str:
                        out.write(f"    R{rno} (len {len(r)}): raw={r}\n")
                        out.write(f"         joined: '{r_str}'\n")

print("Done cure_raw_inspection.txt")
