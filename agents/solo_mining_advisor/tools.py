"""
CYPHER SOLO MINING ADVISOR — Tools
====================================
Tool wrappers that the Solo Mining Advisor agent calls.
Each tool fetches real-time data — never hardcoded values.

Tools:
  get_network_difficulty()  → current BTC network difficulty
  get_btc_price()           → BTC price in USD, BRL, EUR, GBP
  get_braiins_orderbook()   → Braiins Hashpower market rates
  get_mrr_listings()        → MiningRigRentals active listings
  get_parasite_pool_stats() → parasite.space worker/pool stats
"""

import os
import time
import hmac
import hashlib
import logging

import requests

log = logging.getLogger("cypher65.agent")

# ── API endpoints ────────────────────────────────────────────────────────
MEMPOOL_API = "https://mempool.space/api"
COINGECKO_API = "https://api.coingecko.com/api/v3/simple/price"
BRAIINS_API = "https://hashpower.braiins.com/v1"
MRR_BASE = "https://www.miningrigrentals.com/api/v2"
PARASITE_API = "https://parasite.space/api"

# Default worker address (configurable)
DEFAULT_WORKER = os.environ.get(
    "BTC_ADDRESS",
    "bc1qpc3832jcu6m8qpqjvz5lkuydwjzv8v5vq5t5rs",
)


# ═══════════════════════════════════════════════════════════════════════════
#  TOOL 1: get_network_difficulty()
# ═══════════════════════════════════════════════════════════════════════════

def get_network_difficulty():
    """Fetch current Bitcoin network difficulty.
    Returns:
        {"difficulty": float, "source": str} on success
        {"error": str} on failure
    """
    last_err = None
    # Primary: blockchain.info (most reliable as of 2024-2026)
    try:
        r = requests.get(
            "https://blockchain.info/q/getdifficulty",
            timeout=8,
            headers={"User-Agent": "cypher65-solo-mining-advisor/1.0"},
        )
        if r.ok:
            return {
                "difficulty": float(r.text.strip()),
                "source": "blockchain.info/q/getdifficulty",
            }
        last_err = f"HTTP {r.status_code}"
    except Exception as e:
        last_err = str(e)[:100]
        log.warning("[get_network_difficulty] blockchain.info failed: %s", e)

    # Fallback: mempool.space
    try:
        r = requests.get(
            f"{MEMPOOL_API}/v1/difficulty-adjustment",
            timeout=8,
            headers={"User-Agent": "cypher65-solo-mining-advisor/1.0"},
        )
        if r.ok:
            data = r.json()
            diff = data.get("difficulty")
            if diff:
                return {
                    "difficulty": float(diff),
                    "source": "mempool.space/v1/difficulty-adjustment",
                }
            last_err = "mempool response missing 'difficulty' key"
        else:
            last_err = f"HTTP {r.status_code}"
    except Exception as e:
        last_err = str(e)[:100]
        log.warning("[get_network_difficulty] mempool.space failed: %s", e)

    return {"error": f"All difficulty sources unreachable (last: {last_err})"}


# ═══════════════════════════════════════════════════════════════════════════
#  TOOL 2: get_btc_price()
# ═══════════════════════════════════════════════════════════════════════════

def get_btc_price(currencies="usd,brl,eur,gbp"):
    """Fetch BTC price from CoinGecko.
    Args:
        currencies: comma-separated list (default: usd,brl,eur,gbp)
    Returns:
        {"prices": {"usd": float, ...}, "source": str} on success
        {"error": str} on failure
    """
    last_err = None
    try:
        r = requests.get(
            COINGECKO_API,
            params={"ids": "bitcoin", "vs_currencies": currencies},
            timeout=10,
            headers={"User-Agent": "cypher65-solo-mining-advisor/1.0"},
        )
        if r.ok:
            prices = r.json().get("bitcoin", {})
            return {
                "prices": {k.lower(): v for k, v in prices.items()},
                "source": "coingecko.com",
            }
        last_err = f"HTTP {r.status_code}"
    except Exception as e:
        last_err = str(e)[:100]
        log.warning("[get_btc_price] error: %s", e)

    return {"error": f"CoinGecko unreachable: {last_err or 'unknown'}"}


# ═══════════════════════════════════════════════════════════════════════════
#  TOOL 3: get_braiins_orderbook()
# ═══════════════════════════════════════════════════════════════════════════

def get_braiins_orderbook():
    """Fetch real-time Braiins Hashpower orderbook.
    Returns cheapest available hashrate in BTC/PH/day.
    Returns:
        {"price_btc_per_ph_day": float, "source": str, "available_asks": int, ...}
        {"error": str} on failure
    """
    try:
        # Check pricing units
        settings_r = requests.get(
            f"{BRAIINS_API}/spot/settings",
            timeout=8,
            headers={"User-Agent": "cypher65-solo-mining-advisor/1.0"},
        )
        price_unit = "sats/PH/day"
        if settings_r.ok:
            settings = settings_r.json()
            price_unit = settings.get("price_unit", "sats/PH/day")

        # Fetch orderbook
        r = requests.get(
            f"{BRAIINS_API}/spot/orderbook",
            timeout=8,
            headers={"User-Agent": "cypher65-solo-mining-advisor/1.0"},
        )
        if not r.ok:
            return {"error": f"Braiins API returned HTTP {r.status_code}"}

        data = r.json()
        asks = data.get("asks", [])
        bids = data.get("bids", [])

        if not asks and not bids:
            return {"error": "Braiins orderbook is empty (no asks or bids)"}

        # Cheapest hashrate = lowest ask price
        if asks:
            best = min(asks, key=lambda a: float(a.get("price", 0)))
            price_raw = float(best.get("price", 0))
        else:
            best = max(bids, key=lambda b: float(b.get("price", 0)))
            price_raw = float(best.get("price", 0))

        if price_raw <= 0:
            return {"error": "Braiins orderbook has no valid prices"}

        # Normalize to BTC/PH/day
        if "sats" in price_unit.lower():
            btc_per_ph_day = price_raw / 100_000_000
        elif "btc" in price_unit.lower():
            btc_per_ph_day = price_raw
        else:
            btc_per_ph_day = price_raw / 100_000_000  # assume sats

        return {
            "price_btc_per_ph_day": btc_per_ph_day,
            "price_raw": price_raw,
            "price_unit": price_unit,
            "source": "hashpower.braiins.com/v1/spot/orderbook",
            "available_asks": len(asks),
            "available_bids": len(bids),
        }

    except Exception as e:
        log.warning("[get_braiins_orderbook] error: %s", e)
        return {"error": f"Braiins API unreachable: {str(e)[:100]}"}


# ═══════════════════════════════════════════════════════════════════════════
#  TOOL 4: get_mrr_listings()
# ═══════════════════════════════════════════════════════════════════════════

def get_mrr_listings(algo="sha256", api_key=None, api_secret=None):
    """Fetch active MiningRigRentals listings for SHA-256/AsicBoost.
    Requires MRR API credentials (key + secret).
    Set via env vars MRR_API_KEY / MRR_API_SECRET or pass directly.
    Args:
        algo: "sha256" (default) or "sha256_asicboost"
        api_key: MRR API key (optional, falls back to env)
        api_secret: MRR API secret (optional, falls back to env)
    Returns:
        {"price_btc_per_ph_day": float, "source": str, "total_listings": int, ...}
        {"needs_auth": True, "error": str} if credentials missing
        {"error": str} on other failures
    """
    api_key = api_key or os.environ.get("MRR_API_KEY")
    api_secret = api_secret or os.environ.get("MRR_API_SECRET")

    if not api_key or not api_secret:
        return {
            "needs_auth": True,
            "error": "MRR_API_KEY/MRR_API_SECRET not configured. "
                     "Set env vars or pass credentials.",
        }

    endpoint = f"/rig?type={algo}&order=price"
    nonce = str(int(time.time() * 1000))

    # HMAC-SHA1 signature
    sign_string = api_key + nonce + endpoint
    sign = hmac.new(
        api_secret.encode("utf-8"),
        sign_string.encode("utf-8"),
        hashlib.sha1,
    ).hexdigest()

    headers = {
        "x-api-key": api_key,
        "x-api-nonce": nonce,
        "x-api-sign": sign,
        "Content-Type": "application/json",
    }

    try:
        r = requests.get(
            f"{MRR_BASE}{endpoint}",
            headers=headers,
            timeout=12,
        )
        if not r.ok:
            return {"error": f"MRR API returned HTTP {r.status_code}"}

        data = r.json()
        if not data.get("success"):
            return {"error": data.get("message", "MRR API error")}

        listings = data.get("data", [])
        if not listings:
            return {"error": "No active SHA-256 listings found on MRR"}

        # Find cheapest listing (lowest price per TH/day)
        best_price_btc_per_th_day = float("inf")
        best_listing = None
        for rig in listings:
            price_obj = rig.get("price", {})
            amount = float(price_obj.get("amount", 0))
            currency = price_obj.get("currency", "BTC").upper()
            unit = price_obj.get("unit", "th*day")
            hashrate_th = float(rig.get("hash", 0))

            if amount <= 0 or hashrate_th <= 0:
                continue

            # Normalize to BTC per TH per day
            if "th" in unit.lower() and "day" in unit.lower():
                btc_per_th_day = amount if currency == "BTC" else amount / 1e8
            elif "gh" in unit.lower():
                btc_per_th_day = (amount if currency == "BTC" else amount / 1e8) * 1000
            elif "ph" in unit.lower():
                btc_per_th_day = (amount if currency == "BTC" else amount / 1e8) / 1_000_000
            else:
                btc_per_th_day = amount if currency == "BTC" else amount / 1e8

            if btc_per_th_day < best_price_btc_per_th_day:
                best_price_btc_per_th_day = btc_per_th_day
                best_listing = rig

        if not best_listing:
            return {"error": "Could not parse MRR listing prices"}

        # TH/day → PH/day: multiply by 1,000,000
        btc_per_ph_day = best_price_btc_per_th_day * 1_000_000

        return {
            "price_btc_per_ph_day": btc_per_ph_day,
            "price_btc_per_th_day": best_price_btc_per_th_day,
            "source": "miningrigrentals.com/api/v2",
            "best_rig_name": best_listing.get("name", "unknown"),
            "best_rig_hash_th": best_listing.get("hash", 0),
            "total_listings": len(listings),
            "algo": algo,
        }

    except Exception as e:
        log.warning("[get_mrr_listings] error: %s", e)
        return {"error": f"MRR API unreachable: {str(e)[:100]}"}


# ═══════════════════════════════════════════════════════════════════════════
#  TOOL 5: get_parasite_pool_stats()
# ═══════════════════════════════════════════════════════════════════════════

def get_parasite_pool_stats(worker_id=None):
    """Fetch stats from parasite.space pool.
    Args:
        worker_id: BTC address (optional, defaults to DEFAULT_WORKER)
    Returns:
        {"pool_hashrate": float, "pool_workers": int, "worker_best_diff": str, ...}
        {"error": str} on failure
    """
    worker = worker_id or DEFAULT_WORKER

    stats = {}
    pool_ok = False
    worker_ok = False

    # Pool-level stats
    try:
        r = requests.get(
            f"{PARASITE_API}/pool-stats",
            timeout=8,
            headers={"User-Agent": "cypher65-solo-mining-advisor/1.0"},
        )
        if r.ok:
            data = r.json()
            stats["pool_hashrate"] = data.get("hashrate", 0)
            stats["pool_workers"] = data.get("workers", 0)
            stats["pool_users"] = data.get("users", 0)
            stats["pool_highest_diff"] = data.get("highestDifficulty", "0")
            stats["pool_last_block_height"] = data.get("lastBlockHeight")
            stats["pool_work_since_last_block"] = data.get("workSinceLastBlock")
            pool_ok = True
    except Exception as e:
        log.warning("[get_parasite_pool_stats] pool-stats error: %s", e)

    # Worker-level stats
    try:
        r = requests.get(
            f"{PARASITE_API}/user/{worker}",
            timeout=8,
            headers={"User-Agent": "cypher65-solo-mining-advisor/1.0"},
        )
        if r.ok:
            data = r.json()
            worker_data = data.get("workerData", [])
            if worker_data:
                w = worker_data[0]
                stats["worker_hashrate"] = w.get("hashrate")
                stats["worker_best_diff"] = w.get("bestDifficulty", "0")
                stats["worker_last_submit"] = w.get("lastSubmission")
                stats["worker_uptime"] = w.get("uptime")
                stats["worker_status"] = "online"
            else:
                stats["worker_status"] = "not_found"
            stats["account_total_diff"] = (
                data.get("account", {}).get("total_diff")
                if isinstance(data.get("account"), dict) else None
            )
            worker_ok = True
    except Exception as e:
        log.warning("[get_parasite_pool_stats] user error: %s", e)

    if not stats:
        return {"error": "parasite.space API unreachable"}

    # Signal data completeness so callers can distinguish "pool data is 0"
    # from "pool data failed to fetch"
    if pool_ok and worker_ok:
        stats["pool_status"] = "full"
    elif pool_ok:
        stats["pool_status"] = "partial_pool_only"
    elif worker_ok:
        stats["pool_status"] = "partial_worker_only"
    else:
        stats["pool_status"] = "empty"

    stats["source"] = "parasite.space/api"
    stats["worker_address"] = worker
    return stats


# ═══════════════════════════════════════════════════════════════════════════
#  Tool registry — maps tool names to callables for agent dispatch
# ═══════════════════════════════════════════════════════════════════════════

TOOL_REGISTRY = {
    "get_network_difficulty": get_network_difficulty,
    "get_btc_price": get_btc_price,
    "get_braiins_orderbook": get_braiins_orderbook,
    "get_mrr_listings": get_mrr_listings,
    "get_parasite_pool_stats": get_parasite_pool_stats,
}

TOOL_SCHEMAS = {
    "get_network_difficulty": {
        "description": "Fetch current Bitcoin network difficulty from blockchain.info or mempool.space.",
        "parameters": {},
    },
    "get_btc_price": {
        "description": "Fetch BTC price from CoinGecko. Returns USD, BRL, EUR, GBP by default.",
        "parameters": {
            "currencies": {
                "type": "string",
                "description": "Comma-separated currency codes (default: usd,brl,eur,gbp)",
                "default": "usd,brl,eur,gbp",
            },
        },
    },
    "get_braiins_orderbook": {
        "description": "Fetch real-time Braiins Hashpower orderbook. Returns cheapest hashrate in BTC/PH/day.",
        "parameters": {},
    },
    "get_mrr_listings": {
        "description": "Fetch active MiningRigRentals listings for SHA-256/AsicBoost. Requires MRR_API_KEY/MRR_API_SECRET env vars.",
        "parameters": {
            "algo": {
                "type": "string",
                "description": "Algorithm to search: sha256 or sha256_asicboost",
                "default": "sha256",
            },
        },
    },
    "get_parasite_pool_stats": {
        "description": "Fetch stats from parasite.space pool (pool-level + worker-level).",
        "parameters": {
            "worker_id": {
                "type": "string",
                "description": "BTC worker address (optional, defaults to configured address)",
            },
        },
    },
}


def call_tool(name, params=None):
    """Dispatch a tool call by name. Returns the tool's result dict."""
    if name not in TOOL_REGISTRY:
        return {"error": f"Unknown tool: {name}"}

    tool_fn = TOOL_REGISTRY[name]
    try:
        if params:
            return tool_fn(**params)
        return tool_fn()
    except Exception as e:
        log.error("[call_tool] %s error: %s", name, e)
        return {"error": f"Tool {name} failed: {str(e)[:200]}"}
