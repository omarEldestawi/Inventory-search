# -*- coding: utf-8 -*-
import openpyxl, pandas as pd

wb = openpyxl.load_workbook(r"G:\My Drive\Pharama Daily orders\Procurement_Order_Optimized_2026-09-10.xlsx")
ws = wb['Master Comparison']
rows = list(ws.iter_rows(values_only=True))
bench_items = {}
for r in rows[7:]:
    if r[0] is not None and r[1] is not None:
        bench_items[str(r[1]).strip()] = {
            'winner': r[4],
            'disc': r[5],
            'wh_item': r[6]
        }

print(f"Total Benchmark Matched Items: {len(bench_items)}")

# Load master from test_integrated_run
from test_integrated_run import master

our_items = {}
for _, r in master.iterrows():
    req = str(r['اسم الصنف في أمر الشراء']).strip()
    our_items[req] = {
        'winner': r['المخزن الفائز'],
        'disc': r['أعلى خصم %'],
        'wh_item': r['اسم الصنف في كتالوج المخزن الفائز']
    }

print(f"Total Our Engine Matched Items: {len(our_items)}")

common = set(bench_items.keys()) & set(our_items.keys())
bench_only = set(bench_items.keys()) - set(our_items.keys())
our_only = set(our_items.keys()) - set(bench_items.keys())

print(f"\n✅ Common matches ({len(common)}):")
for k in sorted(list(common))[:10]:
    b = bench_items[k]
    o = our_items[k]
    print(f"  Req: {k}")
    print(f"    Our: {o['wh_item']} ({o['winner']} - {o['disc']})")
    print(f"    Bch: {b['wh_item']} ({b['winner']} - {b['disc']})")

print(f"\n⚠️ Benchmark only ({len(bench_only)}):")
for k in sorted(list(bench_only)):
    b = bench_items[k]
    print(f"  Req: {k} -> Bench: {b['wh_item']} ({b['winner']})")

print(f"\n✨ Our Engine only ({len(our_only)}):")
for k in sorted(list(our_only)):
    o = our_items[k]
    print(f"  Req: {k} -> Our: {o['wh_item']} ({o['winner']})")
