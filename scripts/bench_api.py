"""
CYPHER65 // API load benchmark (p50/p95/p99 latency per endpoint)
====================================================================
Measures real request latency against a running server — the metric the
test suite never covers. Honest telemetry applies here too: numbers come
from actual requests against YOUR server, no simulated data.

Usage:
    python scripts/bench_api.py [--base http://127.0.0.1:8765] [--requests 50]
                                [--token <jwt>] [--concurrency 8]

Endpoints tested: /api/healthz, /api/snapshot (with auth when --token given),
/api/alerts, /api/rentals, /api/hashrate-market.

Output: per-endpoint p50 / p95 / p99 latency + requests/sec. A p95 over
~500ms on /api/snapshot is the first sign the hot path needs work (the poll
loop writes cache; the route should serve from it).
"""
import argparse
import concurrent.futures
import statistics
import sys
import time
from collections import defaultdict
from urllib.parse import urljoin

import requests


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", default="http://127.0.0.1:8765", help="server base URL")
    p.add_argument("--requests", type=int, default=50, help="requests per endpoint")
    p.add_argument("--concurrency", type=int, default=8, help="parallel workers")
    p.add_argument("--token", default="", help="JWT bearer token (optional)")
    return p.parse_args()


def _pct(sorted_lat, pct):
    if not sorted_lat:
        return None
    idx = min(len(sorted_lat) - 1, int(len(sorted_lat) * pct))
    return sorted_lat[idx] * 1000  # ms


def main():
    args = _parse_args()
    endpoints = ["/api/healthz", "/api/snapshot", "/api/alerts", "/api/rentals",
                 "/api/hashrate-market"]
    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    results = defaultdict(list)

    def hit(endpoint):
        url = urljoin(args.base, endpoint)
        t0 = time.perf_counter()
        try:
            r = requests.get(url, headers=headers, timeout=30)
            status = r.status_code
        except requests.RequestException as e:
            status = f"ERR:{type(e).__name__}"
        dt = time.perf_counter() - t0
        return endpoint, dt, status

    # Warm the caches (first hit of snapshot/market does real I/O).
    for ep in endpoints:
        try:
            requests.get(urljoin(args.base, ep), headers=headers, timeout=60)
        except requests.RequestException:
            pass

    print(f"Benchmarking {args.base} · {args.requests}x{len(endpoints)} requests "
          f"· concurrency {args.concurrency}\n")
    print(f"{'endpoint':<22} {'status':<8} {'p50':>8} {'p95':>8} {'p99':>8} {'req/s':>8}")
    print("-" * 62)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futs = []
        for ep in endpoints:
            for _ in range(args.requests):
                futs.append(pool.submit(hit, ep))
        for fut in concurrent.futures.as_completed(futs):
            ep, dt, status = fut.result()
            results[ep].append((dt, status))

    worst = []
    for ep in endpoints:
        entries = results[ep]
        ok = [dt for dt, s in entries if s == 200]
        lat = sorted(ok) if ok else []
        if not lat:
            print(f"{ep:<22} {'ERR':<8} no 200 responses")
            continue
        total = sum(lat)
        rps = len(lat) / total if total else 0
        print(f"{ep:<22} {'200':<8} {_pct(lat, 0.50):>7.0f}ms "
              f"{_pct(lat, 0.95):>7.0f}ms {_pct(lat, 0.99):>7.0f}ms {rps:>7.1f}")
        if lat and _pct(lat, 0.95) is not None and _pct(lat, 0.95) > 500:
            worst.append((ep, _pct(lat, 0.95)))

    print()
    if worst:
        print("⚠ p95 > 500ms — hot path needs attention:")
        for ep, p95 in worst:
            print(f"   {ep}: p95 = {p95:.0f}ms")
        sys.exit(1)
    print("✅ all endpoints under 500ms p95")


if __name__ == "__main__":
    main()
