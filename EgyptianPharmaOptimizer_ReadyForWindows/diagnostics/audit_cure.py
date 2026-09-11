# -*- coding: utf-8 -*-
import os, sys, pymupdf, openpyxl, pandas as pd
from src.pdf_parser import PDFCatalogParser
from src.normalizer import unreverse_arabic_text
from src.pdf_parser import fix_arabic_bidi_if_needed
from src.normalizer import *
from src.pharma_matcher import *

cure_pdf = r"G:\My Drive\Pharama Daily orders\‎⁨كيور فارما خاص⁩.pdf"
doc = pymupdf.open(cure_pdf)
parser = PDFCatalogParser(cure_pdf, warehouse_name='كيور فارما')
df_cure = parser.parse()

print(f"Cure parsed: {len(df_cure)} rows")

targets = [
    ("الكابرس", "الكابرس تريو5/160/12.5مجم س ج", "قرص 14---12.5/10/160 تريو الكابرس"),
    ("ايراستابكس", "ايراستابكس تريو 20مجم اقراص س ج", "قرص 12.5/5/20 تريو ايراستابكس"),
    ("ايفرزين", "ايفرزين لوشن", "كريم ايفرزين"),
    ("بيزوكارد", "بيزوكارد5مجم30قرص س ج", "اقراص مجم 5 بيزوكارد"),
    ("جلوكوفاج", "جلوكوفاج1000اقراص س ج", "قرص مجم 1000 جلوكوفاج"),
    ("جليبوفين", "جليبوفين500/5مجم30قرص", "قـــرص 1000 /5 جليبوفين"),
    ("جينتازون", "جينتازون كريم", "كريم جينتازون"),
    ("دياسيرين", "دياسيرين 3شريط س ج", "شريط 3 دياسيرين"),
    ("سيستون", "سيستون  اقراص س ج", "اقراص سيستون"),
    ("شوجارلو", "شوجارلو بلس 50/850اقراص", "بلس مجم 1000/50 شوجارلو"),
    ("فيوسيدين", "فيوسيدين 15جم مرهم صغير", "صغير كريـم جم 15 فيوسيدين"),
    ("كارباميد", "كارباميد كريم ممفيس س ج", "ج 45 ممفيس كريم كارباميد"),
    ("لوراز", "لوراز اقراص س ج", "قــرص لوراز"),
    ("ميجاليز", "ميجاليز شراب س ج", "ميجاليز")
]

with open("audit_cure_details.txt", "w", encoding="utf-8") as out:
    for kw, req, b_item in targets:
        out.write(f"\n==================== TARGET: {kw} ====================\n")
        out.write(f"Req: {req}\nBench Match: {b_item}\n")
        
        # 1. Raw PDF tables
        for pno in range(len(doc)):
            tables = doc[pno].find_tables()
            for tno, t in enumerate(tables):
                for rno, row in enumerate(t.extract()):
                    row_str = " ".join(str(c) for c in row if c)
                    if kw in row_str:
                        out.write(f"  Raw P{pno+1} T{tno} R{rno}: {row}\n")
                        
        # 2. What was extracted in df_cure?
        matches = df_cure[df_cure['item_name'].str.contains(kw, na=False)]
        out.write(f"  Extracted in df_cure ({len(matches)} rows):\n")
        for _, row in matches.iterrows():
            out.write(f"    item_name: '{row['item_name']}' | base_price: {row['base_price']} | discount: {row['discount_rate']}\n")

print("Done audit_cure_details.txt")
