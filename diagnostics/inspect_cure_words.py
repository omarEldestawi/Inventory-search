# -*- coding: utf-8 -*-
import pymupdf

cure_pdf = r"G:\My Drive\Pharama Daily orders\‎⁨كيور فارما خاص⁩.pdf"
doc = pymupdf.open(cure_pdf)
p0 = doc[0]

words = p0.get_text("words")
print(f"Total words on Cure page 0: {len(words)}")

# Group words by approximate y-coordinate
y_buckets = {}
for w in words:
    y_center = round(w[1], 1)
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
    row_words = sorted(y_buckets[y], key=lambda w: w[0])
    row_repr = " | ".join(f"{w[4]} (x={w[0]:.1f})" for w in row_words)
    print(f"y={y:.1f}: {row_repr}")
