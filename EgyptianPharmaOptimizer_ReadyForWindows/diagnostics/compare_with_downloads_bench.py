# -*- coding: utf-8 -*-
import openpyxl, pandas as pd

bench_path = r"C:\Users\omart\Downloads\Procurement_Order_Optimized_2026-09-10.xlsx"
wb = openpyxl.load_workbook(bench_path, data_only=True)
ws = wb['المقارنة الشاملة وتوزيع الأصناف']
b_rows = [r for r in ws.iter_rows(values_only=True) if r[0] is not None and isinstance(r[0], int)]

bench_items = {}
for r in b_rows:
    req = str(r[1]).strip()
    bench_items[req] = {
        'num': r[0],
        'cand': str(r[2]).strip(),
        'winner': str(r[4]).strip(),
        'disc': r[5],
        'price': r[6]
    }

from test_integrated_run import master

our_items = {}
for _, r in master.iterrows():
    req = str(r['اسم الصنف في أمر الشراء']).strip()
    our_items[req] = {
        'cand': str(r['اسم الصنف في كتالوج المخزن الفائز']).strip(),
        'winner': str(r['المخزن الفائز']).strip(),
        'disc': r['أعلى خصم %'],
        'price': r['سعر الجمهور']
    }

common = set(bench_items.keys()) & set(our_items.keys())
bench_only = set(bench_items.keys()) - set(our_items.keys())
our_only = set(our_items.keys()) - set(bench_items.keys())

print(f"Total Benchmark Items: {len(bench_items)}")
print(f"Total Our Matched Items: {len(our_items)}")
print(f"✅ Common items matched: {len(common)} / 54")

print(f"\n⚠️ In Benchmark but NOT matched in Our Engine ({len(bench_only)}):")
for req in sorted(list(bench_only)):
    b = bench_items[req]
    print(f"  Req: '{req}'")
    print(f"       -> Bench: '{b['cand']}' ({b['winner']} - {b['disc']})")

print(f"\n✨ In Our Engine but NOT in Benchmark ({len(our_only)}):")
for req in sorted(list(our_only)):
    o = our_items[req]
    print(f"  Req: '{req}'")
    print(f"       -> Our:   '{o['cand']}' ({o['winner']} - {o['disc']})")
