# -*- coding: utf-8 -*-
import pymupdf, reprlib

doc = pymupdf.open(r"G:\My Drive\Pharama Daily orders\‎⁨المكرومي المنصورة⁩.pdf")

for b in doc[0].get_text("blocks"):
    if 'اماريل' in b[4] and '78' in b[4]:
        print("Raw Amaril block:")
        print(repr(b[4]))
    if 'تراكايين' in b[4]:
        print("Raw Ultracaine block:")
        print(repr(b[4]))
