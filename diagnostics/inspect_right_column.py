# -*- coding: utf-8 -*-
import pymupdf

cure_pdf = r"G:\My Drive\Pharama Daily orders\‎⁨كيور فارما خاص⁩.pdf"
doc = pymupdf.open(cure_pdf)
p0 = doc[0]

print("=== Cure Pharma Page 0 words sample on right column ===")
# Right column rect
right_rect = pymupdf.Rect(290, 80, 595, 790)
words = p0.get_text("words", clip=right_rect)
print(f"Total words on right rect: {len(words)}")
# Print first 20 words (x0, y0, x1, y1, word, block_no, line_no, word_no)
for w in words[:25]:
    print(w)

print("\n=== Cure Pharma Page 0 lines using get_text('text', clip=right_rect) ===")
txt = p0.get_text("text", clip=right_rect)
lines = [l.strip() for l in txt.splitlines() if l.strip()]
print(f"Total lines: {len(lines)}")
for l in lines[:30]:
    print("LINE:", l)
