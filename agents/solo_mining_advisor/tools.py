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
  get_nicehash_orderbook()  → NiceHash Hashpower marketplace
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
NICEHASH_PUBLIC_API = "https://api2.nicehash.com/main/api/v2/hashpower/orderBook"
PARASITE_API = "https://parasite.space/api"

# 1 PH = 1000 TH — canonical unit conversion for per-PH/day → per-TH/day
PH_TO_TH = 1000.0

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
        # Check pricing units — with a configured API key the probe gets the
        # caller's individual pricing layer; without it, degrades gracefully
        # to the default unit (spot/settings now 401s without `apikey`).
        settings_headers = {"User-Agent": "cypher65-solo-mining-advisor/1.0"}
        _braiins_key = braiins_credentials()["api_key"]
        if _braiins_key:
            settings_headers["apikey"] = _braiins_key
        settings_r = requests.get(
            f"{BRAIINS_API}/spot/settings",
            timeout=8,
            headers=settings_headers,
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
        # Braiins API returns 'price_sat' (price in satoshis) per PH/day
        if asks:
            best = min(asks, key=lambda a: float(a.get("price_sat", 0)))
            price_sat = float(best.get("price_sat", 0))
        else:
            best = max(bids, key=lambda b: float(b.get("price_sat", 0)))
            price_sat = float(best.get("price_sat", 0))

        if price_sat <= 0:
            return {"error": "Braiins orderbook has no valid prices"}

        # Convert satoshis to BTC, honoring the API's reported price unit.
        # Braiins quotes in sats/PH/day by default; if settings report
        # sats/TH/day, scale by PH_TO_TH (1 PH = 1000 TH).
        unit_norm = (price_unit or "sats/PH/day").lower()
        if "th" in unit_norm:
            btc_per_th_day = price_sat / 100_000_000
            btc_per_ph_day = btc_per_th_day * PH_TO_TH
        else:
            btc_per_ph_day = price_sat / 100_000_000
            btc_per_th_day = btc_per_ph_day / PH_TO_TH
        available_hr_ph = float(best.get("hr_matched_ph", 0)) or float(best.get("hr_available_ph", 0))

        return {
            "price_btc_per_ph_day": btc_per_ph_day,
            "price_btc_per_th_day": btc_per_th_day,
            "price_raw": price_sat,
            "price_raw_unit": "sats/TH/day" if "th" in unit_norm else "sats/PH/day",
            "price_unit": price_unit,
            "source": "hashpower.braiins.com/v1/spot/orderbook",
            "available_asks": len(asks),
            "available_bids": len(bids),
            "best_order_hr_ph": available_hr_ph,
        }

    except Exception as e:
        log.warning("[get_braiins_orderbook] error: %s", e)
        return {"error": f"Braiins API unreachable: {str(e)[:100]}"}


# ═══════════════════════════════════════════════════════════════════════════
#  TOOL 4: get_mrr_listings()
# ═══════════════════════════════════════════════════════════════════════════

def mrr_credentials() -> dict:
    """Resolve MRR API credentials: env vars first, Settings modal fallback.

    Shared by every MRR consumer (market quotes, rentals, balance) so the
    credential resolution lives in one place.
    """
    api_key = os.environ.get("MRR_API_KEY") or ""
    api_secret = os.environ.get("MRR_API_SECRET") or ""
    if not (api_key and api_secret):
        try:
            from services.settings import load_settings
            _s = load_settings()
            api_key = api_key or (_s.get("mrr_api_key") or "")
            api_secret = api_secret or (_s.get("mrr_api_secret") or "")
        except Exception:
            pass
    return {"api_key": api_key, "api_secret": api_secret}


def braiins_credentials() -> dict:
    """Resolve the Braiins Hashpower API key: env first, Settings modal fallback.

    The owner token unlocks bids/contracts/balance; read-only token covers
    market data. Shared by every Braiins consumer (orderbook settings probe,
    rentals contracts/speed, future bid management).
    """
    api_key = os.environ.get("BRAIINS_API_KEY") or ""
    if not api_key:
        try:
            from services.settings import load_settings
            _s = load_settings()
            api_key = api_key or (_s.get("braiins_api_key") or "")
        except Exception:
            pass
    return {"api_key": api_key}


def _mrr_signed_headers(api_key: str, api_secret: str, endpoint: str) -> dict:
    """Build the HMAC-SHA1 auth headers for MRR API v2 requests.

    Signature string = api_key + nonce + endpoint (path WITHOUT the base
    URL, query params included, no trailing slash). Shared by all MRR
    calls (market quotes, rentals, balance) so the auth scheme lives in
    one place.
    """
    nonce = str(int(time.time() * 1000))
    sign = hmac.new(
        api_secret.encode("utf-8"),
        (api_key + nonce + endpoint).encode("utf-8"),
        hashlib.sha1,
    ).hexdigest()
    return {
        "x-api-key": api_key,
        "x-api-nonce": nonce,
        "x-api-sign": sign,
        "Content-Type": "application/json",
    }


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
    if not api_key or not api_secret:
        _creds = mrr_credentials()
        api_key = api_key or _creds["api_key"]
        api_secret = api_secret or _creds["api_secret"]

    if not api_key or not api_secret:
        return {
            "needs_auth": True,
            "error": "MRR_API_KEY/MRR_API_SECRET not configured. "
                     "Set env vars or pass credentials.",
        }

    endpoint = f"/rig?type={algo}&order=price"
    headers = _mrr_signed_headers(api_key, api_secret, endpoint)

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

        raw_data = data.get("data", {})
        # MRR API v2: "data" is a dict with "records" key containing the array
        if isinstance(raw_data, dict):
            records = raw_data.get("records", [])
        elif isinstance(raw_data, list):
            records = raw_data
        else:
            records = []

        if not records:
            return {"error": "No active SHA-256 listings found on MRR"}

        # Find cheapest listing (lowest price per TH/day)
        best_price_btc_per_th_day = float("inf")
        best_listing = None
        for rig in records:
            if not isinstance(rig, dict):
                continue

            # MRR API v2: price is a dict keyed by currency, e.g. {"BTC": {"price": "0.0001", "hour": "0.0001", ...}}
            price_currencies = rig.get("price", {})
            if not isinstance(price_currencies, dict):
                continue
            btc_price_data = price_currencies.get("BTC")
            if not btc_price_data or not isinstance(btc_price_data, dict):
                continue

            # Price comes in BTC per hour
            price_per_hour = float(btc_price_data.get("price", 0))
            if price_per_hour <= 0:
                price_per_hour = float(btc_price_data.get("hour", 0))
            if price_per_hour <= 0:
                continue

            # Hashrate: MRR API v2 hashrate.advertised.hash (in TH/s)
            hashrate_obj = rig.get("hashrate", {})
            if isinstance(hashrate_obj, dict):
                advertised = hashrate_obj.get("advertised", {})
                if isinstance(advertised, dict):
                    hashrate_th = float(advertised.get("hash", 0))
                else:
                    hashrate_th = float(hashrate_obj.get("hash", 0)) if isinstance(hashrate_obj.get("hash"), (int, float, str)) else 0
            else:
                hashrate_th = float(rig.get("hash", 0))

            if hashrate_th <= 0:
                continue

            # Price per TH per day = (price_per_hour * 24) / hashrate_in_th
            btc_per_th_day = (price_per_hour * 24) / hashrate_th

            if btc_per_th_day < best_price_btc_per_th_day:
                best_price_btc_per_th_day = btc_per_th_day
                best_listing = rig

        if not best_listing:
            return {
                "error": "Could not parse MRR listing prices",
                "debug": {
                    "total_records": len(records),
                    "sample_keys": list(records[0].keys()) if records else [],
                },
            }

        # TH/day → PH/day: multiply by PH_TO_TH (1 PH = 1000 TH)
        btc_per_ph_day = best_price_btc_per_th_day * PH_TO_TH

        # Extract hashrate from best listing for return
        hashrate_obj = best_listing.get("hashrate", {})
        if isinstance(hashrate_obj, dict):
            advertised = hashrate_obj.get("advertised", {})
            if isinstance(advertised, dict):
                best_hashrate_th = float(advertised.get("hash", 0))
            else:
                best_hashrate_th = float(hashrate_obj.get("hash", 0))
        else:
            best_hashrate_th = float(best_listing.get("hash", 0))

        return {
            "price_btc_per_ph_day": btc_per_ph_day,
            "price_btc_per_th_day": best_price_btc_per_th_day,
            "source": "miningrigrentals.com/api/v2",
            "best_rig_name": best_listing.get("name", "unknown"),
            "best_rig_hash_th": best_hashrate_th,
            "total_listings": len(records),
            "algo": algo,
        }

    except Exception as e:
        log.warning("[get_mrr_listings] error: %s", e)
        return {"error": f"MRR API unreachable: {str(e)[:100]}"}


# ═══════════════════════════════════════════════════════════════════════════
#  TOOL 5: get_nicehash_orderbook()
# ═══════════════════════════════════════════════════════════════════════════

def get_nicehash_orderbook(algorithm="SHA256", location=None):
    """Fetch real-time NiceHash Hashpower orderbook (public, no auth needed).

    Args:
        algorithm: "SHA256" (default) or "SHA256ASICBOOST"
        location: optional market location ID (0=Europe, 1=USA, None=all)

    Returns:
        {"price_btc_per_ph_day": float, "source": str, "available_orders": int, ...}
        {"error": str} on failure
    """
    try:
        params = {"algorithm": algorithm}
        if location is not None:
            params["location"] = location

        r = requests.get(
            NICEHASH_PUBLIC_API,
            params=params,
            timeout=10,
            headers={"User-Agent": "cypher65-solo-mining-advisor/1.0"},
        )
        if not r.ok:
            return {"error": f"NiceHash API returned HTTP {r.status_code}"}

        data = r.json()

        # NiceHash v2 API: orders are nested under stats.{currency}.orders
        # The top-level response has only a 'stats' key with per-currency data.
        stats = data.get("stats", {})
        btc_stats = stats.get("BTC", stats.get("btc", {})) if isinstance(stats, dict) else {}
        orders = btc_stats.get("orders", [])

        if not orders:
            return {"error": "NiceHash orderbook is empty (no orders found)"}

        # Filter active STANDARD/MARKET sell orders
        active_orders = [
            o for o in orders
            if o.get("alive", False) and float(o.get("price", 0)) > 0
        ]
        if not active_orders:
            return {"error": "NiceHash has no active sell orders"}

        # Find cheapest: lowest price wins
        best = min(active_orders, key=lambda o: float(o.get("price", float("inf"))))
        price_raw = float(best.get("price", 0))
        if price_raw <= 0:
            return {"error": "NiceHash best order has invalid price"}

        # NiceHash v2 orderBook `price` is BTC/TH/day (per API docs). The old
        # code assigned the same number to both PH and TH keys — impossible.
        # per-PH = per-TH × 1000 (1 PH = 1000 TH).
        btc_per_th_day = price_raw  # already BTC/TH/day
        btc_per_ph_day = price_raw * PH_TO_TH

        # Speed is in H/s (marketFactor = 1e18 for EH)
        speed_hs = float(best.get("acceptedSpeed", 0) or best.get("speed", 0))
        speed_ph = speed_hs / 1e15 if speed_hs > 0 else 0

        # Limit in H/s
        limit_hs = float(best.get("limit", 0))

        return {
            "price_btc_per_ph_day": btc_per_ph_day,
            "price_btc_per_th_day": btc_per_th_day,
            "price_raw": price_raw,
            "price_unit": "BTC/TH/day",
            "source": "api2.nicehash.com (stats.BTC.orders)",
            "algorithm": algorithm,
            "available_orders": len(active_orders),
            "best_order_speed_ph": speed_ph,
            "best_order_speed_hs": speed_hs,
            "best_order_limit_hs": limit_hs,
            "market": "global",
        }

    except Exception as e:
        log.warning("[get_nicehash_orderbook] error: %s", e)
        return {"error": f"NiceHash API unreachable: {str(e)[:100]}"}


# ═══════════════════════════════════════════════════════════════════════════
#  TOOL 6: get_parasite_pool_stats()
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
    "get_nicehash_orderbook": get_nicehash_orderbook,
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
    "get_nicehash_orderbook": {
        "description": "Fetch real-time NiceHash Hashpower orderbook (public, no auth needed). Returns cheapest SHA256 sell order in BTC/PH/day.",
        "parameters": {
            "algorithm": {
                "type": "string",
                "description": "Algorithm: SHA256 or SHA256ASICBOOST",
                "default": "SHA256",
            },
            "location": {
                "type": "integer",
                "description": "Market location: 0=Europe, 1=USA (optional, returns all)",
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
