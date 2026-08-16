"""
CYPHER65 // SOLO MINING ADVISOR
Terminal-style Bitcoin solo mining calculator.
Calculates block probability, expected time, EV, and hashpower rental comparisons.
"""

import math
import re
import requests
import json
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════

HASHES_PER_DIFF = 2**32  # hashes expected per difficulty-1 share
SECONDS_PER_BLOCK = 600  # Bitcoin target block time
PARASITE_API = "https://parasite.space/api"
MEMPOOL_API = "https://mempool.space/api"
COINGECKO_API = "https://api.coingecko.com/api/v3/simple/price"


# ═══════════════════════════════════════════════════════════════════════════
# DATA FETCHERS — never hardcode real-time values
# ═══════════════════════════════════════════════════════════════════════════


def get_network_difficulty():
    """Fetch current Bitcoin network difficulty from mempool.space."""
    try:
        r = requests.get(f"{MEMPOOL_API}/v1/difficulty-adjustment", timeout=8)
        if r.ok:
            data = r.json()
            return float(data.get("difficulty", 0))
    except Exception:
        pass
    # Fallback: use /api/blocks tip height + estimate
    try:
        r = requests.get(f"{MEMPOOL_API}/blocks/tip/height", timeout=8)
        if r.ok:
            height = int(r.text.strip())
            # Approximate difficulty from height (every 2016 blocks adjusted)
            # This is a rough estimate; real value should come from API
            return _estimate_difficulty_from_height(height)
    except Exception:
        pass
    return None


def _estimate_difficulty_from_height(height):
    """Rough difficulty estimate — only used as last resort.
    Returns None if height is unreasonable — caller should handle."""
    # Bitcoin difficulty adjusts every 2016 blocks (~2 weeks)
    # Historical: ~1 at genesis, ~110T at height 870k (2026)
    # Better to return None than an absurd extrapolation
    return None  # API or user must provide difficulty


def get_btc_price(currencies="usd,brl"):
    """Fetch BTC price from CoinGecko."""
    try:
        r = requests.get(
            f"{COINGECKO_API}",
            params={"ids": "bitcoin", "vs_currencies": currencies},
            timeout=10,
        )
        if r.ok:
            return r.json().get("bitcoin", {})
    except Exception:
        pass
    return {}


def get_parasite_best_diff(worker_id=None):
    """Fetch best difficulty from parasite.space.
    If worker_id is provided, fetches worker-specific stats.
    Otherwise returns pool-level stats."""
    url = (
        f"{PARASITE_API}/user/{worker_id}"
        if worker_id
        else f"{PARASITE_API}/pool-stats"
    )
    try:
        r = requests.get(url, timeout=8)
        if r.ok:
            data = r.json()
            return {
                "pool_hashrate": data.get("hashrate", 0),
                "pool_workers": data.get("workerCount", 0),
                "pool_best_diff": data.get("bestDifficulty", 0),
            }
    except Exception:
        pass
    return {}


# ═══════════════════════════════════════════════════════════════════════════
# CORE CALCULATIONS — section 3.2 formulas
# ═══════════════════════════════════════════════════════════════════════════


def calc_block_probability(hashrate_hs, difficulty, duration_seconds):
    """
    P(>=1 block in duration) = 1 - e^(-lambda)
    Where lambda = (hashrate / (difficulty * 2^32)) * duration
    """
    hashes_per_block = difficulty * HASHES_PER_DIFF
    block_rate = hashrate_hs / hashes_per_block
    lam = block_rate * duration_seconds
    prob = 1 - math.exp(-lam)
    return {
        "hashes_per_block": hashes_per_block,
        "block_rate_per_sec": block_rate,
        "lambda": lam,
        "p_at_least_1_block": prob,
        "p_at_least_1_block_pct": prob * 100,
        "p_zero_blocks_pct": math.exp(-lam) * 100,
    }


def calc_expected_time(hashrate_hs, difficulty):
    """E[time to 1 block] = (difficulty * 2^32) / hashrate"""
    hashes_per_block = difficulty * HASHES_PER_DIFF
    seconds = hashes_per_block / hashrate_hs
    days = seconds / 86400
    years = days / 365.25
    return {
        "seconds": seconds,
        "hours": seconds / 3600,
        "days": days,
        "years": years,
    }


def calc_best_diff_expected(hashrate_hs, duration_seconds):
    """Expected best share difficulty after N hashes."""
    total_hashes = hashrate_hs * duration_seconds
    expected_best_diff = total_hashes / HASHES_PER_DIFF
    return {
        "total_hashes": total_hashes,
        "expected_best_diff": expected_best_diff,
    }


def calc_prob_best_diff_exceeds(hashrate_hs, duration_seconds, threshold_diff):
    """
    Probability that the best share in a period exceeds a threshold difficulty.
    Uses exponential approximation: P(best > X) ≈ 1 - (1 - e^(-X/avg_share))^N
    """
    total_hashes = hashrate_hs * duration_seconds
    n_shares = total_hashes / HASHES_PER_DIFF  # approximate share count
    avg_share_diff = 1.0  # per-hash expected
    prob_one_exceeds = (
        math.exp(-threshold_diff / avg_share_diff) if threshold_diff > 0 else 1
    )
    prob_at_least_one = 1 - (1 - prob_one_exceeds) ** max(1, n_shares)
    return {
        "n_shares_approx": n_shares,
        "p_best_exceeds_threshold": prob_at_least_one,
        "p_best_exceeds_pct": prob_at_least_one * 100,
    }


# ═══════════════════════════════════════════════════════════════════════════
# RENTAL COMPARISON — section 4 logic
# ═══════════════════════════════════════════════════════════════════════════


def normalize_cost(price, unit):
    """
    Normalize any rental price to BTC/PH/day.
    Supported inputs:
      - "sats/PH/day": price in sats
      - "BTC/EH/day": price in BTC
      - "USD/TH/day": price in USD (needs BTC price)
    """
    unit = unit.lower().strip()
    if unit == "sats/ph/day":
        return float(price) / 100_000_000  # sats -> BTC
    elif unit == "btc/eh/day":
        return float(price) / 1000  # EH -> PH
    elif unit == "btc/ph/day":
        return float(price)
    elif unit == "usd/th/day":
        # Need BTC price to convert
        btc_price = get_btc_price()
        usd_btc = btc_price.get("usd", 0)
        if usd_btc <= 0:
            return None
        usd_per_ph = float(price) * 1_000_000  # TH -> PH
        return usd_per_ph / usd_btc
    else:
        return None


def compare_rentals(
    budget_btc,
    difficulty,
    duration_hours,
    braiins_price_btc_per_ph_day=None,
    mrr_price_btc_per_ph_day=None,
    objective="EV",
    auto_fetch=True,
    mrr_api_key=None,
    mrr_api_secret=None,
):
    """
    Compare Braiins vs MRR for solo mining.
    If prices not provided and auto_fetch=True, fetches real-time prices from APIs.
    objective: "EV" | "JACKPOT" | "VARIANCE_MIN"
    """
    duration_days = duration_hours / 24
    duration_seconds = duration_hours * 3600
    options = []
    api_errors = []

    # Normalize manually-provided prices, or auto-fetch from APIs
    if braiins_price_btc_per_ph_day is not None and braiins_price_btc_per_ph_day > 0:
        b_price = (
            normalize_cost(braiins_price_btc_per_ph_day, "btc/ph/day")
            if isinstance(braiins_price_btc_per_ph_day, str)
            else braiins_price_btc_per_ph_day
        )
        b_source = "manual"
    elif auto_fetch:
        braiins_data = get_braiins_orderbook()
        if braiins_data and braiins_data.get("price_btc_per_ph_day"):
            b_price = braiins_data["price_btc_per_ph_day"]
            b_source = "live"
        else:
            b_price = None
            b_source = "unavailable"
            api_errors.append(
                f"Braiins: {braiins_data.get('error', 'no orderbook data') if braiins_data else 'API unreachable'}"
            )
    else:
        b_price = None
        b_source = None

    if mrr_price_btc_per_ph_day is not None and mrr_price_btc_per_ph_day > 0:
        m_price = (
            normalize_cost(mrr_price_btc_per_ph_day, "btc/ph/day")
            if isinstance(mrr_price_btc_per_ph_day, str)
            else mrr_price_btc_per_ph_day
        )
        m_source = "manual"
    elif auto_fetch:
        mrr_data = get_mrr_listings(api_key=mrr_api_key, api_secret=mrr_api_secret)
        if mrr_data and mrr_data.get("price_btc_per_ph_day"):
            m_price = mrr_data["price_btc_per_ph_day"]
            m_source = "live"
        elif mrr_data and mrr_data.get("needs_auth"):
            m_price = None
            m_source = "needs_auth"
            api_errors.append(f"MRR: {mrr_data.get('error', 'credentials required')}")
        else:
            m_price = None
            m_source = "unavailable"
            api_errors.append(
                f"MRR: {mrr_data.get('error', 'no listings') if mrr_data else 'API unreachable'}"
            )
    else:
        m_price = None
        m_source = None

    for name, price_btc_ph_day in [
        ("Braiins Hashpower", b_price),
        ("MiningRigRentals (MRR)", m_price),
    ]:
        if price_btc_ph_day is None or price_btc_ph_day <= 0:
            continue

        # How much hashrate can we buy?
        cost_per_ph = price_btc_ph_day * duration_days
        if cost_per_ph <= 0:
            continue
        hashpower_ph = budget_btc / cost_per_ph
        hashrate_hs = hashpower_ph * 1e15  # PH/s -> H/s

        # Calculate probabilities
        prob = calc_block_probability(hashrate_hs, difficulty, duration_seconds)
        exp_time = calc_expected_time(hashrate_hs, difficulty)

        # EV calculation (simplified: assume finder gets 1 BTC bonus)
        block_reward = 3.125  # current subsidy
        # EV = P(block) * (1 BTC finder bonus + proportional share of remaining reward)
        # Conservative estimate: finder bonus is the main value driver for solo miners
        finder_bonus = 1.0  # parasite.space guarantees 1 BTC to block finder
        proportional_share = (
            prob["p_at_least_1_block"] * block_reward * 0.01
        )  # ~1% of block reward as pool share
        ev_bruto = prob["p_at_least_1_block"] * finder_bonus + proportional_share
        ev_liquido = ev_bruto - budget_btc

        price_source = b_source if name.startswith("Braiins") else m_source
        options.append(
            {
                "platform": name,
                "price_btc_per_ph_day": price_btc_ph_day,
                "price_source": price_source,
                "cost_total_btc": cost_per_ph,
                "hashpower_ph": hashpower_ph,
                "hashrate_hs": hashrate_hs,
                "p_block_pct": prob["p_at_least_1_block_pct"],
                "expected_time_days": exp_time["days"],
                "expected_time_years": exp_time["years"],
                "ev_btc": ev_liquido,
            }
        )

    # Include api_errors and source info in each option
    for opt in options:
        opt["api_errors"] = api_errors
        if api_errors:
            opt["api_status"] = "partial"
        else:
            opt["api_status"] = "ok"

    # Sort by objective
    if objective == "JACKPOT":
        options.sort(key=lambda x: x["p_block_pct"], reverse=True)
    elif objective == "VARIANCE_MIN":
        options.sort(key=lambda x: x["hashpower_ph"], reverse=True)
    else:  # EV (default)
        options.sort(key=lambda x: x["ev_btc"], reverse=True)

    # Attach api_errors to the result for caller visibility
    # Always return a list for consistent handling by callers.
    # If no options were generated but there are API errors, return an
    # error-entry option so format_compare_output can display them.
    if not options and api_errors:
        options.append(
            {
                "platform": "API ERROR",
                "price_btc_per_ph_day": 0,
                "price_source": "error",
                "cost_total_btc": 0,
                "hashpower_ph": 0,
                "hashrate_hs": 0,
                "p_block_pct": 0,
                "expected_time_days": 0,
                "expected_time_years": 0,
                "ev_btc": 0,
                "api_errors": api_errors,
                "api_status": "error",
            }
        )
    return options


# ═══════════════════════════════════════════════════════════════════════════
# TERMINAL OUTPUT FORMATTER
# ═══════════════════════════════════════════════════════════════════════════


def format_calc_output(hashrate, difficulty, duration_hours, user=None):
    """Format a full solo mining calculation as terminal output.
    user: prompt identity (e.g. the connected wallet short-form).
    Defaults to a neutral 'miner' — never a hardcoded person."""
    who = _safe_term_user(user)
    hashrate_hs = _parse_hashrate(hashrate)
    duration_seconds = duration_hours * 3600
    prob = calc_block_probability(hashrate_hs, difficulty, duration_seconds)
    exp_time = calc_expected_time(hashrate_hs, difficulty)
    best_diff = calc_best_diff_expected(hashrate_hs, duration_seconds)

    lines = []
    lines.append(
        f"{who}@cypher:~/solo-mining$ calc --hashrate {hashrate} --duration {duration_hours}h"
    )
    lines.append("")
    lines.append("[OK] Parameters received")
    lines.append(f"  hashrate........... {hashrate}")
    lines.append(
        f"  duration............ {duration_hours}h ({duration_hours/24:.2f} days)"
    )
    lines.append(f"  difficulty.......... {difficulty:,.0f}")
    lines.append("")
    lines.append("─── Block Discovery ───")
    lines.append(f"  Hashes per block.... {prob['hashes_per_block']:,.0f}")
    lines.append(f"  Block rate........... {prob['block_rate_per_sec']:.6e} blocks/s")
    lines.append(f"  Lambda(t)............ {prob['lambda']:.6e}")
    lines.append(f"  P(>=1 block)......... {prob['p_at_least_1_block_pct']:.6f}%")
    lines.append(f"  P(0 blocks).......... {prob['p_zero_blocks_pct']:.2f}%")
    lines.append("")
    lines.append("─── Expected Time ───")
    lines.append(f"  E[time to block].... {exp_time['days']:,.1f} days")
    lines.append(f"                    = {exp_time['years']:,.2f} years")
    lines.append("")
    lines.append("─── Best Difficulty (Estimated) ───")
    lines.append(f"  Total hashes......... {best_diff['total_hashes']:,.0f}")
    lines.append(f"  Expected best diff... {best_diff['expected_best_diff']:,.1f}")
    lines.append("")
    lines.append("[WARN] Solo mining is a lottery. EV is negative vs pool mining.")
    lines.append("[OK] Calculation complete.")

    return "\n".join(lines)


def format_compare_output(
    budget_btc,
    difficulty,
    duration_hours,
    braiins_price=None,
    mrr_price=None,
    auto_fetch=True,
    mrr_api_key=None,
    mrr_api_secret=None,
    user=None,
):
    """Format rental comparison as terminal table.
    user: prompt identity (e.g. the connected wallet short-form).
    Defaults to a neutral 'miner' — never a hardcoded person."""
    import os

    if mrr_api_key is None:
        mrr_api_key = os.environ.get("MRR_API_KEY")
    if mrr_api_secret is None:
        mrr_api_secret = os.environ.get("MRR_API_SECRET")
    who = _safe_term_user(user)
    results = compare_rentals(
        budget_btc,
        difficulty,
        duration_hours,
        braiins_price,
        mrr_price,
        auto_fetch=auto_fetch,
        mrr_api_key=mrr_api_key,
        mrr_api_secret=mrr_api_secret,
    )

    lines = []
    lines.append(
        f"{who}@cypher:~/solo-mining$ compare --budget {budget_btc}BTC --duration {duration_hours}h"
    )
    lines.append("")
    lines.append(
        f"[OK] Budget: {budget_btc} BTC | Duration: {duration_hours}h | Difficulty: {difficulty:,.0f}"
    )
    lines.append("")

    if not results:
        lines.append("[ERROR] No rental options available.")
        lines.append(
            "        Provide prices via --braiins/--mrr flags, or ensure network connectivity."
        )
        return "\n".join(lines)

    # If the only option is an API error entry, display errors
    if len(results) == 1 and results[0].get("api_status") == "error":
        lines.append("[ERROR] Could not fetch rental prices:")
        for err in results[0].get("api_errors", []):
            lines.append(f"        {err}")
        lines.append("")
        lines.append(
            "[WARN] Provide prices manually: --braiins <price> --mrr <price> (BTC/PH/day)"
        )
        return "\n".join(lines)

    lines.append(
        "  Platform              Price/PH/d    Hashpower   P(block)   Expected Time      EV(BTC)"
    )
    lines.append(
        "  ─────────────────────  ────────────  ──────────  ─────────  ────────────────   ───────"
    )
    for r in results:
        lines.append(
            f"  {r['platform']:<22s}  {r['price_btc_per_ph_day']:>10.6f}   {r['hashpower_ph']:>8.2f}PH  "
            f"{r['p_block_pct']:>7.4f}%  {r['expected_time_days']:>12.0f}d  "
            f"{r['ev_btc']:>+10.6f}"
        )

    lines.append("")
    if results[0]["ev_btc"] < 0:
        lines.append("[WARN] All options have negative EV. Solo mining is a lottery.")
    else:
        lines.append(
            f"[OK] Best option: {results[0]['platform']} (EV={results[0]['ev_btc']:+.6f} BTC)"
        )
    lines.append("")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
# MARKET DATA — Braiins Hashpower & MiningRigRentals (real API calls)
# ═══════════════════════════════════════════════════════════════════════════

BRAIINS_API = "https://hashpower.braiins.com/v1"


def get_braiins_orderbook():
    """Fetch real-time Braiins Hashpower orderbook.
    Returns the cheapest available hashrate in BTC/PH/day, or None if unavailable.
    """
    try:
        # First check settings for pricing units
        settings_r = requests.get(f"{BRAIINS_API}/spot/settings", timeout=8)
        price_unit = "sats/PH/day"  # default assumption
        if settings_r.ok:
            settings = settings_r.json()
            price_unit = settings.get("price_unit", "sats/PH/day")

        # Fetch the orderbook
        r = requests.get(f"{BRAIINS_API}/spot/orderbook", timeout=8)
        if not r.ok:
            return None
        data = r.json()

        # The orderbook has bids (buyers) and asks (sellers).
        # We want the cheapest available hashrate = lowest ask price.
        asks = data.get("asks", [])
        if not asks:
            # Fallback: use highest bid as proxy for market rate
            bids = data.get("bids", [])
            if not bids:
                return None
            best_bid = max(bids, key=lambda b: float(b.get("price", 0)))
            price_raw = float(best_bid.get("price", 0))
        else:
            best_ask = min(asks, key=lambda a: float(a.get("price", 0)))
            price_raw = float(best_ask.get("price", 0))

        if price_raw <= 0:
            return None

        # Normalize to BTC/PH/day
        if "sats" in price_unit.lower():
            btc_per_ph_day = price_raw / 100_000_000
        elif "btc" in price_unit.lower():
            btc_per_ph_day = price_raw
        else:
            btc_per_ph_day = price_raw / 100_000_000  # assume sats

        return {
            "source": "Braiins Hashpower",
            "price_btc_per_ph_day": btc_per_ph_day,
            "price_raw": price_raw,
            "price_unit": price_unit,
            "available_asks": len(asks),
            "available_bids": len(data.get("bids", [])),
        }

    except Exception as e:
        return None


def get_mrr_listings(algo="sha256", api_key=None, api_secret=None):
    """Fetch active MiningRigRentals listings for SHA-256/AsicBoost.
    Requires MRR API credentials (key + secret).
    Set via parameters or env vars MRR_API_KEY / MRR_API_SECRET.
    Returns cheapest available hashrate in BTC/PH/day, or None.
    """
    import os
    import hmac
    import hashlib

    api_key = api_key or os.environ.get("MRR_API_KEY")
    api_secret = api_secret or os.environ.get("MRR_API_SECRET")

    if not api_key or not api_secret:
        return {
            "source": "MiningRigRentals",
            "price_btc_per_ph_day": None,
            "error": "MRR_API_KEY/MRR_API_SECRET not configured. Set env vars or pass credentials.",
            "needs_auth": True,
        }

    MRR_BASE = "https://www.miningrigrentals.com/api/v2"
    endpoint = f"/rig?type={algo}&order=price"
    # Issue #150 — nonce monotônico compartilhado (fix do "Bad Nonce" #148):
    # duas chamadas no mesmo ms geravam o MESMO nonce e o MRR rejeita.
    from helpers import next_monotonic_nonce_ms

    nonce = next_monotonic_nonce_ms()

    # HMAC-SHA1 signature
    sign_string = api_key + nonce + endpoint
    sign = hmac.new(
        api_secret.encode("utf-8"), sign_string.encode("utf-8"), hashlib.sha1
    ).hexdigest()

    headers = {
        "x-api-key": api_key,
        "x-api-nonce": nonce,
        "x-api-sign": sign,
        "Content-Type": "application/json",
    }

    try:
        r = requests.get(f"{MRR_BASE}{endpoint}", headers=headers, timeout=12)
        if not r.ok:
            return {
                "source": "MiningRigRentals",
                "price_btc_per_ph_day": None,
                "error": f"MRR API returned HTTP {r.status_code}",
            }

        data = r.json()
        if not data.get("success"):
            return {
                "source": "MiningRigRentals",
                "price_btc_per_ph_day": None,
                "error": data.get("message", "MRR API error"),
            }

        listings = data.get("data", [])
        if not listings:
            return {
                "source": "MiningRigRentals",
                "price_btc_per_ph_day": None,
                "error": "No active SHA-256 listings found",
            }

        # Find the cheapest listing (lowest price per TH/day)
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
                btc_per_th_day = (
                    amount if currency == "BTC" else amount / 1e8
                ) / 1_000_000
            else:
                btc_per_th_day = amount if currency == "BTC" else amount / 1e8

            if btc_per_th_day < best_price_btc_per_th_day:
                best_price_btc_per_th_day = btc_per_th_day
                best_listing = rig

        if not best_listing:
            return {
                "source": "MiningRigRentals",
                "price_btc_per_ph_day": None,
                "error": "Could not parse listing prices",
            }

        # TH/day -> PH/day: multiply by 1,000,000
        btc_per_ph_day = best_price_btc_per_th_day * 1_000_000

        return {
            "source": "MiningRigRentals",
            "price_btc_per_ph_day": btc_per_ph_day,
            "price_btc_per_th_day": best_price_btc_per_th_day,
            "best_rig_name": best_listing.get("name", "unknown"),
            "best_rig_hash_th": best_listing.get("hash", 0),
            "total_listings": len(listings),
            "algo": algo,
        }

    except Exception as e:
        return {
            "source": "MiningRigRentals",
            "price_btc_per_ph_day": None,
            "error": str(e),
        }


def _safe_term_user(user):
    """Sanitize the terminal prompt identity: strip to a safe charset.
    Falls back to 'miner' for empty/invalid values."""
    # Keep the U+2026 ellipsis (…): the frontend sends fmt.shortAddr() output
    # (e.g. "bc1qar0srr…wf5mdq") as the prompt identity — stripping it would
    # make the backend echo differ from the client echo. The literal char is
    # used instead of \u2026 to avoid raw-string escape ambiguity.
    who = (user or "").strip()
    who = re.sub(r"[^A-Za-z0-9_.:\-…]", "", who)[:48]
    return who or "miner"


def _parse_hashrate(hr_str):
    """Parse hashrate string like '225TH', '225 TH/s', '1.5PH', '100EH' to H/s."""
    hr_str = str(hr_str).strip().upper().replace(" ", "")
    # Strip /S suffix first
    hr_str = hr_str.removesuffix("/S")
    multipliers = {
        "EH": 1e18,
        "PH": 1e15,
        "TH": 1e12,
        "GH": 1e9,
        "MH": 1e6,
        "KH": 1e3,
        "H": 1,
    }
    for unit, mult in multipliers.items():
        if hr_str.endswith(unit):
            num = hr_str[: -len(unit)]
            return float(num) * mult
    return float(hr_str)
