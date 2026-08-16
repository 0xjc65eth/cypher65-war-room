#!/usr/bin/env python3
"""Print full raw MRR responses for the endpoints that returned success:False."""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from probe_mrr_api import call

for ep, params in [
    ("/account", None),
    ("/account/balance", None),
    ("/rig/my", None),
    ("/account/transactions", {"limit": 3}),
    ("/account/profile", None),
    ("/rental/0", None),
]:
    res = call(ep, "GET", params)
    print(f"=== {ep} ===")
    print(json.dumps(res, ensure_ascii=False)[:800])
    print()
