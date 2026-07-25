#!/usr/bin/env python3
"""
CYPHER65 // Mock Opportunity Injector
======================================
Injects fake opportunities into the running server for visual testing
of the opportunity popup UI.

Usage:
    # Inject default mock opportunities (2 mock deals):
    python3 tests/mock_opportunity_injector.py

    # Inject with custom JSON file:
    python3 tests/mock_opportunity_injector.py --file my_opps.json

    # Inject a single quick test (Braiins-style):
    python3 tests/mock_opportunity_injector.py --quick

    # Clear injected mocks (restore real scanning):
    python3 tests/mock_opportunity_injector.py --clear

    # Also inject clearing localStorage on the server side:
    python3 tests/mock_opportunity_injector.py --fresh
        (inject + clear localStorage dedup hint — forces popup to appear)

Requires: requests (usually pre-installed with the project)
"""

import sys
import json
import time
import os

try:
    import requests
except ImportError:
    print("[ERROR] requests library not found. Install with: pip install requests")
    sys.exit(1)

SERVER = os.environ.get("CYPHER_SERVER", "http://localhost:8765")

DEFAULT_MOCK_OPPORTUNITIES = [
    {
        "id": "mock_braiins_0.015",
        "platform": "braiins",
        "title": "🔥 TEST · Braiins 15.0 sats/PH/day",
        "description": (
            "With 225.0 TH/s you could mine ~0.0034 BTC/day equivalent. "
            "This is a MOCK opportunity — not real market data."
        ),
        "meta": "source: MOCK TEST DATA — opportunity engine bypassed for visual UI testing",
        "price": 0.000015,
        "severity": "INFO",
        "status": "MOCK",
    },
    {
        "id": "mock_mrr_0.012",
        "platform": "mrr",
        "title": "⚡ TEST · MRR 12.0 sats/PH/day (20% cheaper)",
        "description": (
            "MiningRigRentals has active listings — this is a MOCK test "
            "opportunity to verify the popup UI rendering."
        ),
        "meta": "source: MOCK TEST DATA — does not reflect real market prices",
        "price": 0.000012,
        "severity": "INFO",
        "status": "MOCK",
    },
]


QUICK_MOCK = [
    {
        "id": "mock_quick_test",
        "platform": "braiins",
        "title": "⚡ QUICK TEST · Mock Opportunity",
        "description": "Single mock deal for quick popup UI verification. Refresh the page if popup doesn't appear within 2 min.",
        "meta": "source: MOCK — injected via mock_opportunity_injector.py --quick",
        "price": 0.000010,
        "severity": "SUCCESS",
        "status": "MOCK",
    },
]


def inject(opportunities):
    """POST mock opportunities to the running server."""
    url = f"{SERVER}/api/opportunities/mock"
    try:
        r = requests.post(url, json={"opportunities": opportunities}, timeout=5)
        if r.ok:
            data = r.json()
            count = len(data.get("opportunities", []))
            ts = data.get("ts", 0)
            print(f"[OK] Injected {count} mock opportunity/ies")
            print(f"     Timestamp: {ts}")
            print(f"     Popup should appear within ~2 min (next _checkOpportunities cycle)")
            print("")
            print("     To see it immediately:")
            print("       • Open browser DevTools → Console")
            print("       • Run: _checkOpportunities()")
            print("")
            print("     To restore real scanning:")
            print("       python3 tests/mock_opportunity_injector.py --clear")
            return True
        else:
            print(f"[ERROR] Server returned {r.status_code}: {r.text[:200]}")
            return False
    except requests.ConnectionError:
        print(f"[ERROR] Cannot connect to {url}")
        print(f"       Is the server running on {SERVER}?")
        print(f"       Start it: cd cypher65-war-room && .venv/bin/python3 app.py")
        return False
    except Exception as e:
        print(f"[ERROR] {e}")
        return False


def clear():
    """Clear injected mock opportunities."""
    url = f"{SERVER}/api/opportunities/mock/clear"
    try:
        r = requests.post(url, timeout=5)
        if r.ok:
            data = r.json()
            print(f"[OK] {data.get('status', 'cleared')}")
            print(f"     {data.get('message', '')}")
            return True
        else:
            print(f"[ERROR] Server returned {r.status_code}: {r.text[:200]}")
            return False
    except requests.ConnectionError:
        print(f"[ERROR] Cannot connect to {url}")
        return False
    except Exception as e:
        print(f"[ERROR] {e}")
        return False


def check_server():
    """Quick health check to make sure server is running."""
    try:
        r = requests.get(f"{SERVER}/healthz", timeout=3)
        if r.ok:
            data = r.json()
            age = data.get("age_s", "?")
            print(f"[OK] Server is running (poll age: {age}s)")
            return True
    except Exception:
        pass
    print(f"[WARN] Server at {SERVER} might not be running")
    print(f"       Continuing anyway (error will show on inject attempt)")
    return False


def print_help():
    print(__doc__)


def main():
    args = sys.argv[1:]

    # Help — only on explicit -h/--help
    if "-h" in args or "--help" in args:
        print_help()
        return

    if "--clear" in args:
        check_server()
        clear()
        return

    if "--quick" in args:
        check_server()
        inject(QUICK_MOCK)
        return

    if "--file" in args:
        idx = args.index("--file")
        if idx + 1 >= len(args):
            print("[ERROR] --file requires a path argument")
            sys.exit(1)
        filepath = args[idx + 1]
        try:
            with open(filepath) as f:
                custom_opps = json.load(f)
            if isinstance(custom_opps, list):
                pass  # list of opportunities
            elif isinstance(custom_opps, dict) and "opportunities" in custom_opps:
                custom_opps = custom_opps["opportunities"]
            else:
                print("[ERROR] JSON must be a list of opportunity dicts or {opportunities: [...]}")
                sys.exit(1)
            check_server()
            inject(custom_opps)
        except FileNotFoundError:
            print(f"[ERROR] File not found: {filepath}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"[ERROR] Invalid JSON: {e}")
            sys.exit(1)
        return

    # No recognized flag → inject default (default behavior)
    check_server()
    inject(DEFAULT_MOCK_OPPORTUNITIES)


if __name__ == "__main__":
    main()
