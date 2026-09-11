# -*- coding: utf-8 -*-
import sys
import openpyxl

sys.stdout.reconfigure(encoding='utf-8')

bench_path = r'C:\Users\omart\Downloads\Procurement_Order_Optimized_2026-09-10.xlsx'
wb = openpyxl.load_workbook(bench_path)
ws = wb['المقارنة الشاملة وتوزيع الأصناف']
rows = list(ws.iter_rows(values_only=True))

items = []
for r in rows[6:]:
    if r[0] is not None and isinstance(r[0], int):
        items.append({
            'num': r[0],
            'req': str(r[1]).strip() if r[1] else '',
            'cat': str(r[2]).strip() if r[2] else '',
            'qty': r[3],
            'winner': str(r[4]).strip() if r[4] else '',
            'disc': str(r[5]).strip() if r[5] else '',
            'pub_price': r[6],
            'buy_price': r[7]
        })

print(f"Total benchmark items: {len(items)}")
for it in items:
    print(f"#{it['num']:02d} | Req: {it['req']:<30} | Cat: {it['cat']:<35} | Winner: {it['winner']:<18} | Disc: {it['disc']} | Pub: {it['pub_price']}")

