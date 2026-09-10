# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding='utf-8')
from test_bench_all import items
for it in items[:11]:
    print(f"#{it['num']:02d} | Req: {it['req']:<30} | Cat: {it['cat']:<35} | Winner: {it['winner']:<18} | Disc: {it['disc']} | Pub: {it['pub_price']}")
