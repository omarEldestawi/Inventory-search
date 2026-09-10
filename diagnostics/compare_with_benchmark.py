# -*- coding: utf-8 -*-
import pandas as pd
from test_integrated_run import master

bench_path = r"G:\My Drive\Pharama Daily orders\Procurement_Order_Optimized_2026-09-10.xlsx"
bench_df = pd.read_excel(bench_path, sheet_name=0)

print(f"Master matched items count: {len(master)}")
print(f"Benchmark items count: {len(bench_df)}")

# Check overlap
master_reqs = set(master['اسم الصنف في أمر الشراء'])
bench_reqs = set(bench_df['اسم الصنف في أمر الشراء'])

common = master_reqs & bench_reqs
master_only = master_reqs - bench_reqs
bench_only = bench_reqs - master_reqs

print(f"\nCommon items ({len(common)}):")
for r in sorted(list(common)):
    m_row = master[master['اسم الصنف في أمر الشراء'] == r].iloc[0]
    b_row = bench_df[bench_df['اسم الصنف في أمر الشراء'] == r].iloc[0]
    print(f"  Req: {r}")
    print(f"    Our: {m_row['اسم الصنف في كتالوج المخزن الفائز']} ({m_row['المخزن الفائز']} - {m_row['أعلى خصم %']})")
    print(f"    Bch: {b_row['اسم الصنف في كتالوج المخزن الفائز']} ({b_row['المخزن الفائز']} - {b_row['أعلى خصم %']})")

print(f"\nMaster only ({len(master_only)}):")
for r in sorted(list(master_only)):
    m_row = master[master['اسم الصنف في أمر الشراء'] == r].iloc[0]
    print(f"  Req: {r} -> Matched: {m_row['اسم الصنف في كتالوج المخزن الفائز']} ({m_row['المخزن الفائز']} - {m_row['أعلى خصم %']})")

print(f"\nBenchmark only ({len(bench_only)}):")
for r in sorted(list(bench_only)):
    b_row = bench_df[bench_df['اسم الصنف في أمر الشراء'] == r].iloc[0]
    print(f"  Req: {r} -> Bench Matched: {b_row['اسم الصنف في كتالوج المخزن الفائز']} ({b_row['المخزن الفائز']} - {b_row['أعلى خصم %']})")
