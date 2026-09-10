# -*- coding: utf-8 -*-
import pymupdf

doc = pymupdf.open(r'G:\My Drive\Pharama Daily orders\‎⁨كيور فارما خاص⁩.pdf')

pages_to_check = {
    1: ['الكابرس'],
    2: ['بيزوكارد'],
    3: ['جلوكوفاج', 'جليبوفين', 'جينتازون', 'دياسيرين'],
    4: ['سيستون'],
    5: ['فيوسيدين', 'كارباميد'],
    6: ['لوراز']
}

with open("cure_text_lines.txt", "w", encoding="utf-8") as out:
    for pno, kws in pages_to_check.items():
        page = doc[pno-1]
        lines = page.get_text().splitlines()
        blocks = page.get_text("blocks")
        out.write(f"\n==================== PAGE {pno} ====================\n")
        out.write(f"Total lines: {len(lines)}, Total blocks: {len(blocks)}\n")
        for b in blocks:
            b_text = b[4]
            for kw in kws:
                if kw in b_text:
                    out.write(f"BLOCK for {kw} (bbox {b[:4]}):\n{b_text}\n---\n")

print("Done cure_text_lines.txt")
