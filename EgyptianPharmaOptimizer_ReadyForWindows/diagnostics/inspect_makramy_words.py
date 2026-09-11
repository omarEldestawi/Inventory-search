# -*- coding: utf-8 -*-
import pymupdf

makramy_pdf = r"G:\My Drive\Pharama Daily orders\‎⁨المكرومي المنصورة⁩.pdf"
doc = pymupdf.open(makramy_pdf)
p0 = doc[0]

print("=== Makramy Page 0 words sample ===")
words = p0.get_text("words")
print(f"Total words on page 0: {len(words)}")

# Group words by approximate y-coordinate (e.g. rounded to 1 decimal or bucket of 3 points)
y_buckets = {}
for w in words:
    y_center = round(w[1], 1)
    # Find matching bucket within 3 points
    found_bucket = None
    for b in y_buckets:
        if abs(b - y_center) < 3.0:
            found_bucket = b
            break
    if found_bucket is None:
        found_bucket = y_center
        y_buckets[found_bucket] = []
    y_buckets[found_bucket].append(w)

sorted_ys = sorted(y_buckets.keys())
print(f"Total line rows found by y clustering: {len(sorted_ys)}")
for y in sorted_ys[:15]:
    row_words = sorted(y_buckets[y], key=lambda w: w[0]) # sort by x
    row_repr = " | ".join(f"{w[4]} (x={w[0]:.1f})" for w in row_words)
    print(f"y={y:.1f}: {row_repr}")
