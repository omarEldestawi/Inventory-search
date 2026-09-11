# -*- coding: utf-8 -*-
import pymupdf, re, unicodedata

doc = pymupdf.open(r"G:\My Drive\Pharama Daily orders\‎⁨المكرومي المنصورة⁩.pdf")

print("=== Makramy Page 0 Blocks ===")
blocks = doc[0].get_text("blocks")
print(f"Total blocks: {len(blocks)}")

# Let's see blocks that have x0 >= 210 (columns 2 and 3)
right_blocks = [b for b in blocks if b[0] >= 210 and b[1] >= 80 and b[3] <= 790]
print(f"Right blocks count: {len(right_blocks)}")

for b in right_blocks[:25]:
    text = b[4].strip().replace('\n', ' // ')
    print(f"Bbox ({b[0]:.1f}, {b[1]:.1f}, {b[2]:.1f}, {b[3]:.1f}): '{text}'")
