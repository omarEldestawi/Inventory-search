# -*- coding: utf-8 -*-
import pymupdf, re
from src.normalizer import EASTERN_ARABIC_DIGITS, unreverse_arabic_text, parse_discount, normalize_arabic_text
from src.pdf_parser import fix_arabic_bidi_if_needed

doc = pymupdf.open(r'G:\My Drive\Pharama Daily orders\‎⁨كيور فارما خاص⁩.pdf')

target_words_rev = {
    'سرباكلا': 'الكابرس',
    'سكباتساريا': 'ايراستابكس',
    'نيزرفيا': 'ايفرزين',
    'دراكوزيب': 'بيزوكارد',
    'جافوكولج': 'جلوكوفاج',
    'نيفوبيلج': 'جليبوفين',
    'نوزاتنيج': 'جينتازون',
    'نيريسايد': 'دياسيرين',
    'نوتسيس': 'سيستون',
    'ولراجوش': 'شوجارلو',
    'نيديسويف': 'فيوسيدين',
    'ديامبراك': 'كارباميد',
    'زارول': 'لوراز',
    'زيلاجيم': 'ميجاليز'
}

with open("cure_rows_audit_all.txt", "w", encoding="utf-8") as out:
    for pno in range(len(doc)):
        tables = doc[pno].find_tables()
        for tno, t in enumerate(tables):
            rows = t.extract()
            for rno, row in enumerate(rows):
                non_empty = [str(c).strip() for c in row if c and str(c).strip()]
                if not non_empty:
                    continue
                cell_text = non_empty[0]
                # Check if any target reversed word in cell_text
                matched_target = [name for rev, name in target_words_rev.items() if rev in cell_text]
                if matched_target:
                    out.write(f"\n--- Target: {matched_target} (P{pno+1} R{rno}) ---\n")
                    out.write(f"Raw cell text: '{cell_text}'\n")
                    
                    # Trace Case A
                    norm_text = cell_text.translate(EASTERN_ARABIC_DIGITS)
                    parts = norm_text.split()
                    out.write(f"Parts: {parts}\n")
                    if len(parts) >= 3:
                        m0 = re.match(r'^\d+(?:\.\d+)?$', parts[0])
                        m1 = re.match(r'^\d+(?:\.\d+)?$', parts[1])
                        out.write(f"m0({parts[0]})={bool(m0)}, m1({parts[1]})={bool(m1)}\n")
                        if m0 and m1:
                            raw_name = ' '.join(parts[2:])
                            unrev = fix_arabic_bidi_if_needed(raw_name)
                            out.write(f"SUCCESS Case A -> Name: '{unrev}' | Disc: {parts[0]} | Price: {parts[1]}\n")
                        else:
                            out.write(f"FAILED Case A regex match on parts[0] or parts[1]\n")
                    else:
                        out.write(f"FAILED Case A len(parts) < 3\n")

print("Done cure_rows_audit_all.txt")
