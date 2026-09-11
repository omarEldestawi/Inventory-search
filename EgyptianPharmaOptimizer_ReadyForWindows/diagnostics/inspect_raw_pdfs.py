# -*- coding: utf-8 -*-
import os, sys, unicodedata, re, pymupdf

drive_dir = r"G:\My Drive\Pharama Daily orders"

def search_pdf_tables(pdf_name, keywords):
    fpath = os.path.join(drive_dir, pdf_name)
    doc = pymupdf.open(fpath)
    print(f"=== Searching {pdf_name} ({len(doc)} pages) ===")
    found = []
    for pno in range(len(doc)):
        page = doc[pno]
        tables = page.find_tables()
        # Also check page text
        text_lines = page.get_text().splitlines()
        for lno, l in enumerate(text_lines):
            for kw in keywords:
                if kw in l:
                    found.append((pno+1, f"TEXT line {lno}", l.strip()))
        for tno, t in enumerate(tables):
            rows = t.extract()
            for rno, r in enumerate(rows):
                r_str = ' | '.join(str(c).strip() for c in r if c and str(c).strip())
                for kw in keywords:
                    if kw in r_str:
                        found.append((pno+1, f"TABLE {tno} row {rno}", r_str, r))
    return found

# Let's search Cure Pharma
cure_kws = ['الكابرس', 'ايراستابكس', 'ايفرزين', 'بيزوكارد', 'جلوكوفاج', 'جليبوفين', 'جينتازون', 'دياسيرين', 'سيستون', 'شوجارلو', 'فيوسيدين', 'كارباميد', 'لوراز', 'ميجاليز']
res_cure = search_pdf_tables("‎⁨كيور فارما خاص⁩.pdf", cure_kws)

with open("raw_cure_hits.txt", "w", encoding="utf-8") as f:
    f.write(f"Cure Pharma hits: {len(res_cure)}\n")
    for item in res_cure:
        f.write(f"P{item[0]} {item[1]}: {item[2]}\n")
        if len(item) > 3:
            f.write(f"   Raw cells: {item[3]}\n")

# Search Makramy
makramy_kws = ['اماريل', 'امبوفير', 'اميكاسين', 'انتوكس', 'اوجمنتين', 'ايفاستين', 'تيبوفورتين', 'سوبراكس', 'فروساك', 'ليفابيون', 'ميوكوسول']
res_makramy = search_pdf_tables("‎⁨المكرومي المنصورة⁩.pdf", makramy_kws)
with open("raw_makramy_hits.txt", "w", encoding="utf-8") as f:
    f.write(f"Makramy hits: {len(res_makramy)}\n")
    for item in res_makramy:
        f.write(f"P{item[0]} {item[1]}: {item[2]}\n")
        if len(item) > 3:
            f.write(f"   Raw cells: {item[3]}\n")

# Search Forsan (عروض مميز)
forsan_kws = ['دابافيلداكتين', 'دابافيلدا', 'دابافیلداكتین', 'ميروكسنوريك', 'میروكسنوریك', 'ميروكس']
res_forsan = search_pdf_tables("‎⁨عروض مميز⁩.pdf", forsan_kws)
with open("raw_forsan_hits.txt", "w", encoding="utf-8") as f:
    f.write(f"Forsan hits: {len(res_forsan)}\n")
    for item in res_forsan:
        f.write(f"P{item[0]} {item[1]}: {item[2]}\n")
        if len(item) > 3:
            f.write(f"   Raw cells: {item[3]}\n")

# Search Hona Gomla
hona_kws = ['كولوسبازمين', 'کولوسبازمین', 'ميليتوفيكس', 'میلیتوفیکس', 'ميليتوفكس']
res_hona = search_pdf_tables("‎⁨هنا جمله بنها 456⁩.pdf", hona_kws)
with open("raw_hona_hits.txt", "w", encoding="utf-8") as f:
    f.write(f"Hona hits: {len(res_hona)}\n")
    for item in res_hona:
        f.write(f"P{item[0]} {item[1]}: {item[2]}\n")
        if len(item) > 3:
            f.write(f"   Raw cells: {item[3]}\n")

print("Finished searching all raw PDFs!")
