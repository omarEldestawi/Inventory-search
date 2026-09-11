# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding='utf-8')
from test_diag3 import our_items, bench_by_req, norm

extras = [x for x in our_items if norm(x['req_name']) not in bench_by_req]
for i, o in enumerate(extras, 1):
    print(f"{i}. Req: '{o['req_name']}' -> Cat: '{o['cat_name']}' ({o['winner']}) Disc: {o['discount']} Price: {o['public_price']}")
