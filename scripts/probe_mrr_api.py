#!/usr/bin/env python3
"""Probe MRR API v2 endpoints with the configured credentials (read from .env)."""
import os, time, hmac, hashlib, json, sys

BASE = "https://www.miningrigrentals.com/api/v2"

def load_env(path):
    env = {}
    try:
        for line in open(path):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return env

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env = load_env(os.path.join(_root, ".env"))
KEY = env.get("MRR_API_KEY", "")
SEC = env.get("MRR_API_SECRET", "")

import requests

def call(ep, method="GET", params=None, body=None):
    nonce = str(int(time.time() * 1000))
    sign = hmac.new(SEC.encode(), (KEY + nonce + ep).encode(), hashlib.sha1).hexdigest()
    headers = {"x-api-key": KEY, "x-api-nonce": nonce, "x-api-sign": sign,
               "Content-Type": "application/json"}
    try:
        if method == "GET":
            r = requests.get(BASE + ep, headers=headers, params=params, timeout=15)
        else:
            r = requests.post(BASE + ep, headers=headers, json=body or {}, timeout=15)
        if r.status_code != 200:
            return {"HTTP": r.status_code, "body": r.text[:200]}
        return r.json()
    except Exception as e:
        return {"error": str(e)[:150]}

def summarize(data):
    """Compact JSON summary (keys + types, first values)."""
    if isinstance(data, dict):
        out = {}
        for k, v in list(data.items())[:12]:
            if isinstance(v, (dict, list)):
                out[k] = f"{type(v).__name__}[{len(v)}]" if not isinstance(v, list) else f"list[{len(v)}]"
            else:
                out[k] = str(v)[:60]
        return out
    if isinstance(data, list):
        return f"list[{len(data)}] first={summarize(data[0]) if data else None}"
    return str(data)[:80]

if __name__ == "__main__":
    print("KEY ok:", bool(KEY), "SEC ok:", bool(SEC))

    for ep, method, params in [
        ("/whoami", "GET", None),
        ("/account", "GET", None),
        ("/account/balance", "GET", None),
        ("/rig", "GET", {"type": "sha256", "order": "price"}),
        ("/rig/my", "GET", None),
        ("/rental", "GET", None),
        ("/rental", "GET", {"type": "renter"}),
        ("/rental", "GET", {"type": "owner"}),
        ("/rental", "GET", {"type": "renter", "history": "true"}),
        ("/info/algos", "GET", None),
        ("/account/transactions", "GET", {"limit": 3}),
    ]:
        res = call(ep, method, params)
        print(f"\n=== {method} {ep} {params or ''} ===")
        print(json.dumps(summarize(res), ensure_ascii=False, indent=1)[:1200])
