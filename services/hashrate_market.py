"""
CYPHER65 // Hashrate Market Intelligence
==========================================
Fetch, normalize, score and persist rental-market offers from
Braiins Hashpower and MiningRigRentals (MRR).

The public schema is intentionally small so that additional providers can
be added later without changing consumers.
"""

import json
import os
import time
import logging
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional

from agents.solo_mining_advisor.tools import get_braiins_orderbook, get_mrr_listings, get_nicehash_orderbook

log = logging.getLogger("cypher65")

# Conservative post-halving assumption for EV calculations.
BTC_BLOCK_REWARD = 3.125
BLOCKS_PER_DAY = 144
DEFAULT_NETWORK_HASHRATE = 6e20  # ~600 EH/s fallback
DEFAULT_RENTAL_HASHRATE_TH = 1000.0  # 1 PH — used when provider does not expose size
PH_TO_TH = 1000.0  # 1 PH = 1000 TH — per-PH/day → per-TH/day conversion


@dataclass
class NormalizedOffer:
    """Common schema for a hashrate rental offer."""

    provider: str
    hashrate: float          # TH/s
    price_per_th_day: float  # BTC per TH per day
    duration_days: float
    fee_pct: float
    algorithm: str
    source: str = ""         # origin label: braiins|mrr|nicehash|parasite|derived
    estimated: bool = False  # True → price is derived/estimated, not a live quote
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Provider fetchers → NormalizedOffer
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_braiins_offer() -> Optional[NormalizedOffer]:
    """Fetch the cheapest Braiins Hashpower ask and normalize it."""
    data = get_braiins_orderbook()
    if not data or data.get("error") or "price_btc_per_ph_day" not in data:
        return None

    price_per_ph_day = float(data["price_btc_per_ph_day"])
    if price_per_ph_day <= 0:
        return None

    # price_btc_per_ph_day -> BTC/TH/day (1 PH = 1000 TH)
    price_per_th_day = price_per_ph_day / PH_TO_TH

    return NormalizedOffer(
        provider="braiins",
        hashrate=DEFAULT_RENTAL_HASHRATE_TH,
        price_per_th_day=price_per_th_day,
        duration_days=1.0,
        fee_pct=0.0,
        algorithm="sha256",
        source="braiins",
        meta={
            "source": "hashpower.braiins.com",
            "available_asks": data.get("available_asks"),
            "available_bids": data.get("available_bids"),
            "price_unit": data.get("price_unit"),
            "price_raw": data.get("price_raw"),
        },
    )


def fetch_mrr_offer() -> Optional[NormalizedOffer]:
    """Fetch the cheapest MRR listing and normalize it."""
    data = get_mrr_listings()
    if not data or data.get("error") or data.get("needs_auth") or "price_btc_per_ph_day" not in data:
        return None

    price_per_ph_day = float(data["price_btc_per_ph_day"])
    if price_per_ph_day <= 0:
        return None

    price_per_th_day = price_per_ph_day / PH_TO_TH
    hashrate_th = _safe_float(data.get("best_rig_hash_th"), DEFAULT_RENTAL_HASHRATE_TH)
    if hashrate_th <= 0:
        hashrate_th = DEFAULT_RENTAL_HASHRATE_TH

    return NormalizedOffer(
        provider="mrr",
        hashrate=hashrate_th,
        price_per_th_day=price_per_th_day,
        duration_days=1.0,
        fee_pct=0.0,
        algorithm=data.get("algo", "sha256"),
        source="mrr",
        meta={
            "source": "miningrigrentals.com",
            "rig_name": data.get("best_rig_name"),
            "total_listings": data.get("total_listings"),
        },
    )


def fetch_nicehash_offer() -> Optional[NormalizedOffer]:
    """Fetch the cheapest NiceHash SHA256 sell order and normalize it."""
    data = get_nicehash_orderbook()
    if not data or data.get("error") or "price_btc_per_ph_day" not in data:
        return None

    price_per_ph_day = float(data["price_btc_per_ph_day"])
    if price_per_ph_day <= 0:
        return None

    # price_btc_per_ph_day -> BTC/TH/day (1 PH = 1000 TH)
    price_per_th_day = price_per_ph_day / PH_TO_TH

    # Speed in PH/s -> TH/s
    hashrate_ph = _safe_float(data.get("best_order_speed_ph"), 0)
    hashrate_th = hashrate_ph * 1000.0 if hashrate_ph > 0 else DEFAULT_RENTAL_HASHRATE_TH

    return NormalizedOffer(
        provider="nicehash",
        hashrate=hashrate_th,
        price_per_th_day=price_per_th_day,
        duration_days=1.0,
        fee_pct=0.0,
        algorithm="sha256",
        source="nicehash",
        meta={
            "source": "api2.nicehash.com",
            "available_orders": data.get("available_orders"),
            "algorithm": data.get("algorithm"),
            "market": data.get("market"),
        },
    )


def fetch_parasite_offer(network_hashrate: Optional[float] = None) -> Optional[NormalizedOffer]:
    """Fetch a 'refinery' rental offer from Parasite Space pool.
    Parasite is a mining pool (not a marketplace), but we model their
    pool-fee-based mining as a 'rental' where cost = pool fee + opportunity cost.
    The price is estimated from the pool's share of network and fee structure."""
    from agents.solo_mining_advisor.tools import get_parasite_pool_stats
    try:
        stats = get_parasite_pool_stats()
        if not stats or stats.get("error") or stats.get("pool_status") == "empty":
            return None

        pool_hr = _safe_float(stats.get("pool_hashrate"), 0)
        if pool_hr <= 0:
            return None

        # Parasite fee is ~1%. Convert to BTC/TH/day equivalent
        # Cost = (pool_fee / pool_hashrate_share) * daily_reward
        # Simplified: 1% fee on estimated daily BTC = 0.01 * 144 * 3.125 * (your_hr / net_hr)
        pool_hr_hs = pool_hr  # already in H/s from API
        # Use the real network hashrate when known (snapshot), else fall back.
        net_hr = network_hashrate if network_hashrate and network_hashrate > 0 else DEFAULT_NETWORK_HASHRATE
        share_of_network = pool_hr_hs / net_hr
        daily_pool_revenue_btc = share_of_network * 144 * 3.125

        # Price = pool fee (1%) of daily revenue per TH/day
        fee_pct = 1.0
        price_per_th_day = (daily_pool_revenue_btc * (fee_pct / 100.0)) / (pool_hr_hs / 1e12) if pool_hr_hs > 0 else 1e-8

        return NormalizedOffer(
            provider="parasite",
            hashrate=pool_hr_hs / 1e12 if pool_hr_hs > 0 else DEFAULT_RENTAL_HASHRATE_TH,
            price_per_th_day=max(price_per_th_day, 1e-8),
            duration_days=1.0,
            fee_pct=fee_pct,
            algorithm="sha256",
            source="parasite",
            estimated=True,
            meta={
                "source": "parasite.space/api/pool-stats",
                "pool_hashrate_hs": pool_hr_hs,
                "pool_workers": stats.get("pool_workers"),
                "pool_users": stats.get("pool_users"),
                "pool_highest_diff": stats.get("pool_highest_diff"),
                "label": "Parasite Pool (own hardware required)",
                "disclaimer": "Pool mining cost (fee) — not a rental marketplace",
            },
        )
    except Exception as e:
        log.warning("[hashrate_market] Parasite fetch failed: %s", e)
        return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Module-level TTL cache (Fase 3)
#  ── layered below app.py's _HASHRATE_MARKET_CACHE so every consumer
#     (/api/hashrate-market, /api/opportunities/compare, /api/snapshot
#     highlights) benefits from a short-lived in-memory cache without
#     hammering the provider APIs on rapid polls.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_FETCH_CACHE: Dict[str, Dict[str, Any]] = {}
_FETCH_CACHE_TTL = 60          # seconds — successful fetches
_FETCH_CACHE_EMPTY_TTL = 15    # seconds — empty/errored fetches (retry sooner)
# Fase 3 · P1: simple retry/backoff on transient provider failures (429/5xx).
# The provider tools already surface HTTP errors as error-dicts → fetchers
# return None, so we retry the whole fetch when it yields nothing, with a
# short linear backoff. Bounded (1 retry) so we never hammer the APIs.
_FETCH_RETRIES = 1             # extra attempts after the first
_FETCH_BACKOFF_BASE = 0.15     # seconds — linear backoff before each retry


def clear_fetch_cache() -> None:
    """Drop all cached provider results (used by tests)."""
    _FETCH_CACHE.clear()


def _cached_fetch(key: str, fetcher: Any) -> Optional[NormalizedOffer]:
    """Run ``fetcher`` and cache its result for a short TTL.

    Empty results (None) get a shorter TTL so a transient provider outage
    recovers quickly; successful results are kept for the full TTL.

    Retry/backoff (Fase 3 · P1): a transient 429/5xx provider hiccup yields
    None through the tools layer, so we retry the fetch up to ``_FETCH_RETRIES``
    extra times with a short linear backoff before giving up. The TTL cache
    above also bounds the request rate, preventing 429 loops.
    """
    now = time.time()
    entry = _FETCH_CACHE.get(key)
    if entry is not None:
        ttl = _FETCH_CACHE_TTL if entry.get("value") is not None else _FETCH_CACHE_EMPTY_TTL
        if now - entry.get("ts", 0) < ttl:
            return entry["value"]

    value = None
    for attempt in range(_FETCH_RETRIES + 1):
        try:
            value = fetcher()
            if value is not None:
                break
        except Exception as e:  # keep cache consistent on failure
            log.warning("[hashrate_market] %s fetch failed (attempt %d/%d): %s",
                        key, attempt + 1, _FETCH_RETRIES + 1, e)
            value = None
        if attempt < _FETCH_RETRIES:
            time.sleep(_FETCH_BACKOFF_BASE * (attempt + 1))

    # Record completion time, not the pre-fetch time, so backoff/slow
    # fetches don't silently eat into the TTL.
    _FETCH_CACHE[key] = {"ts": time.time(), "value": value}
    return value


def fetch_all_offers(network_hashrate: Optional[float] = None) -> List[NormalizedOffer]:
    """Fetch offers from all supported providers, isolating failures.

    Results are cached for a short TTL (_FETCH_CACHE) so rapid polls from
    multiple endpoints don't hammer the provider APIs.
    """
    offers: List[NormalizedOffer] = []

    for key, fetcher in [
        ("braiins", fetch_braiins_offer),
        ("mrr", fetch_mrr_offer),
        ("nicehash", fetch_nicehash_offer),
        ("parasite", lambda: fetch_parasite_offer(network_hashrate)),
    ]:
        try:
            o = _cached_fetch(key, fetcher)
            if o:
                offers.append(o)
        except Exception as e:
            log.warning("[hashrate_market] %s fetch failed: %s", key, e)

    return offers


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Metrics & scoring
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def compute_metrics(
    offer: NormalizedOffer,
    network_hashrate: Optional[float] = None,
) -> Dict[str, Any]:
    """Return cost/revenue/EV/score/risk metrics for a normalized offer.

    Revenue is estimated from the rented hashrate's share of the network
    times the daily block reward. It is a rough expected value only.
    """
    net_hr = network_hashrate if network_hashrate and network_hashrate > 0 else DEFAULT_NETWORK_HASHRATE

    hashrate_hps = offer.hashrate * 1e12
    daily_revenue_btc = (hashrate_hps / net_hr) * BLOCKS_PER_DAY * BTC_BLOCK_REWARD
    duration_days = offer.duration_days or 1.0

    estimated_cost = (
        offer.hashrate
        * offer.price_per_th_day
        * duration_days
        * (1.0 + offer.fee_pct / 100.0)
    )
    estimated_revenue = daily_revenue_btc * duration_days
    expected_value = estimated_revenue - estimated_cost
    roi = expected_value / estimated_cost if estimated_cost > 0 else 0.0
    score = round(roi * 100.0, 2)

    # Risk level: negative EV or high cost relative to revenue → HIGH
    if expected_value < 0 or roi < -0.10:
        risk = "HIGH"
    elif roi < 0.05:
        risk = "MEDIUM"
    else:
        risk = "LOW"

    return {
        "score": score,
        "estimated_cost_btc": round(estimated_cost, 8),
        "estimated_revenue_btc": round(estimated_revenue, 8),
        "expected_value_btc": round(expected_value, 8),
        "risk_level": risk,
        "network_hashrate": net_hr,
        "duration_days": duration_days,
    }


def score_offer(offer: NormalizedOffer, network_hashrate: Optional[float] = None) -> Dict[str, Any]:
    """Convenience wrapper: full dict of offer + metrics."""
    return {
        "id": f"{offer.provider}_{offer.price_per_th_day:.6f}",
        **offer.to_dict(),
        "metrics": compute_metrics(offer, network_hashrate),
    }


def enrich_opportunity_dict(
    opp: Dict[str, Any],
    snapshot: Optional[Dict[str, Any]] = None,
    network_hashrate: Optional[float] = None,
) -> Dict[str, Any]:
    """Attach metrics to an existing opportunity dict (e.g. from agents/opportunity_engine).

    Uses the opportunity's ``price`` (BTC/PH/day) and a default rental hashrate.
    """
    price = opp.get("price")
    if price is None or price <= 0:
        opp["metrics"] = _empty_metrics()
        return opp

    offer = NormalizedOffer(
        provider=opp.get("platform", "unknown"),
        hashrate=DEFAULT_RENTAL_HASHRATE_TH,
        price_per_th_day=float(price) / PH_TO_TH,
        duration_days=1.0,
        fee_pct=0.0,
        algorithm="sha256",
        meta={},
    )

    if network_hashrate is None and snapshot is not None:
        network_hashrate = (snapshot.get("network") or {}).get("hashrate")

    opp["metrics"] = compute_metrics(offer, network_hashrate)
    return opp


def _empty_metrics() -> Dict[str, Any]:
    return {
        "score": 0.0,
        "estimated_cost_btc": 0.0,
        "estimated_revenue_btc": 0.0,
        "expected_value_btc": 0.0,
        "risk_level": "UNKNOWN",
        "network_hashrate": None,
        "duration_days": 1.0,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Persistence
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def persist_market_history(
    conn: Any,
    offers: List[NormalizedOffer],
) -> None:
    """Persist the current market snapshot to SQLite.

    ``conn`` is an open sqlite3 connection with row_factory set.
    """
    if not offers:
        return

    c = conn.cursor()
    ts = int(time.time())
    for offer in offers:
        metrics = compute_metrics(offer)
        c.execute(
            """INSERT INTO hashrate_market_history
            (ts, provider, hashrate, price_per_th_day, duration_days, fee_pct,
             algorithm, score, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ts,
                offer.provider,
                offer.hashrate,
                offer.price_per_th_day,
                offer.duration_days,
                offer.fee_pct,
                offer.algorithm,
                metrics["score"],
                json.dumps(offer.to_dict()),
            ),
        )
    conn.commit()


def fetch_market_history(conn: Any, limit: int = 100) -> List[Dict[str, Any]]:
    """Return the most recent market history rows."""
    c = conn.cursor()
    c.execute(
        """SELECT ts, provider, hashrate, price_per_th_day, duration_days,
                  fee_pct, algorithm, score, raw_data
           FROM hashrate_market_history
           ORDER BY ts DESC, provider ASC
           LIMIT ?""",
        (limit,),
    )
    rows = []
    for r in c.fetchall():
        rows.append({
            "ts": r["ts"],
            "provider": r["provider"],
            "hashrate": r["hashrate"],
            "price_per_th_day": r["price_per_th_day"],
            "duration_days": r["duration_days"],
            "fee_pct": r["fee_pct"],
            "algorithm": r["algorithm"],
            "score": r["score"],
            "raw_data": r["raw_data"],
        })
    return rows


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Command Center highlights (cheap, no external HTTP)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def market_offer_sort_key(scored_offer: Dict[str, Any]) -> tuple:
    """Real-first sort key for the HASH MARKET grid.

    Live marketplace quotes (``estimated=False``) always sort BEFORE
    estimated/derived offers — the parasite pool-fee model carries an
    inflated ROI score that would otherwise crown its ~1 sat/TH/d synthetic
    card at the top of the grid. Within each group the EV score still
    orders descending, so the best real deal stays first.

    Returns ``(estimated, -score)``: False < True, so real quotes win the
    first slots; ``max_items`` still caps the final list, real offers fill
    the slots first and estimated offers only fill what is left.
    """
    metrics = scored_offer.get("metrics") or {}
    score = float(metrics.get("score") or 0.0)
    return (bool(scored_offer.get("estimated", False)), -score)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Institutional View — HashratePulse Enterprise
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Risk tiers per HashratePulse Enterprise framework
RISK_TIERS = {
    "braiins": 1,     # Tier 1 — institutional (Braiins OS+, smartpool, regulated)
    "nicehash": 2,    # Tier 2 — established marketplace, KYC, escrow
    "mrr": 2,         # Tier 2 — established marketplace, escrow
    "parasite": 3,    # Tier 3 — pool-based, own hardware required, modeled not live
    "derived": 4,     # Tier 4 — synthetic/derived, not executable
    "unknown": 4,
}
RISK_TIER_LABELS = {
    1: "Tier 1 \u00b7 Institutional",
    2: "Tier 2 \u00b7 Established",
    3: "Tier 3 \u00b7 Specialized",
    4: "Tier 4 \u00b7 Experimental",
}


def _risk_tier(provider: str, estimated: bool = False) -> int:
    """Return the HashratePulse risk tier for a provider."""
    if estimated:
        return 4
    return RISK_TIERS.get(provider.lower(), 4)


def _estimate_own_mining_cost_usd_per_th_day(
    efficiency_j_th: float = 30.0,
    electricity_usd_per_kwh: float = 0.05,
    hardware_allowance_pct: float = 0.15,
) -> Optional[float]:
    """Estimated all-in USD cost to mine 1 TH/day on OWNED hardware.

    CFO benchmark for the rent-vs-own callout in the institutional view.
    Pure math, no network calls:
      - 1 TH/s = 1e12 hashes/sec → 1e12 * 86400 hashes/day.
      - Energy = hashes * J/TH / 1e12 (J) per second → J/day = J/TH * 86400.
      - kWh = J/day / 3.6e6; USD = kWh * price/kWh.
      - Hardware allowance: adds a % on top of electricity to cover ASIC
        amortization/repairs (S19-class ~30 J/TH @ 5c/kWh ≈ 3.6c/TH/day).
    Env-overridable so operators can plug in their REAL power cost.
    """
    try:
        eff = float(os.environ.get("OWN_MINING_EFFICIENCY_J_TH", efficiency_j_th))
        price = float(os.environ.get("ELECTRICITY_USD_KWH", electricity_usd_per_kwh))
        allowance = float(os.environ.get("HARDWARE_ALLOWANCE_PCT", hardware_allowance_pct))
    except (TypeError, ValueError):
        eff, price, allowance = efficiency_j_th, electricity_usd_per_kwh, hardware_allowance_pct
    if eff <= 0 or price <= 0:
        return None
    energy_kwh_per_th_day = (eff * 86400) / 3.6e6
    cost = energy_kwh_per_th_day * price * (1.0 + allowance)
    return cost if cost > 0 else None


def compute_institutional_view(
    offers: List[NormalizedOffer],
    network_hashrate: Optional[float] = None,
    btc_usd: Optional[float] = None,
) -> Dict[str, Any]:
    """Build the HashratePulse Enterprise institutional view from raw offers.

    Returns the Executive Snapshot + Ranked Venue Table as a single dict
    that the frontend renders directly.
    """
    if not offers:
        return {"regime": "No Data", "snapshot": None, "venues": [], "notes": []}

    # Score every offer
    scored = [score_offer(o, network_hashrate) for o in offers]
    # Sort: estimated last, then best price first
    scored.sort(key=lambda s: (bool(s.get("estimated", False)), s["price_per_th_day"]))

    best = scored[0]
    best_price = best["price_per_th_day"]

    # Regime detection
    if len(scored) >= 3:
        spread_pct = (scored[-1]["price_per_th_day"] - best_price) / best_price * 100 if best_price > 0 else 0
        regime = "Tight" if spread_pct < 5 else ("Normal" if spread_pct < 15 else ("Wide" if spread_pct < 40 else "Dislocated"))
    else:
        regime = "Normal"

    # Total visible liquidity (PH/s)
    total_ph = sum(o.hashrate for o in offers) / 1000.0

    # VWAP — liquidity-WEIGHTED mean price, not a naive average. A venue
    # quoting a silly price with 100 PH should not skew the exec benchmark
    # the way a simple mean would (CFO audit: naive mean misleads allocation).
    prices = [s["price_per_th_day"] for s in scored]
    sizes_th = [max(float(s.get("hashrate") or 0), 1.0) for s in scored]
    vwap = (sum(p * w for p, w in zip(prices, sizes_th)) /
            sum(sizes_th)) if prices else 0.0
    prices_sorted = sorted(prices)
    n = len(prices_sorted)
    median = (prices_sorted[n // 2] if n % 2
              else (prices_sorted[n // 2 - 1] + prices_sorted[n // 2]) / 2.0)
    price_min = prices_sorted[0]
    price_max = prices_sorted[-1]

    # ── Rent vs own benchmark (CFO) ────────────────────────────────────────
    # The operator's fleet is the alternative: renting hashrate only makes
    # sense if the cheapest rental is NOT way above the cost of mining the
    # same TH on owned hardware. Estimated from typical S19/X19 economics
    # (efficiency 30 J/TH, electricity 5c/kWh → ~0.036 USD/TH/day opex +
    # a 15% hardware-cost allowance). BTC/USD converts the rental price.
    rent_vs_own = None
    if btc_usd:
        rental_usd_th_day = best_price * btc_usd  # BTC/TH/d × USD/BTC → USD/TH/d
        own_cost_usd_th_day = _estimate_own_mining_cost_usd_per_th_day()
        if own_cost_usd_th_day:
            ratio = rental_usd_th_day / own_cost_usd_th_day
            rent_vs_own = {
                "rental_usd_th_day": round(rental_usd_th_day, 4),
                "own_cost_usd_th_day": round(own_cost_usd_th_day, 4),
                "ratio": round(ratio, 2),
                # ratio 1.0 = rental == own cost; <1 rental cheaper, >1 dearer
                "cheaper_than_own": ratio < 1.0,
                "premium_pct": round((ratio - 1.0) * 100, 0) if ratio >= 1.0 else 0,
                "discount_pct": round((1.0 - ratio) * 100, 0) if ratio < 1.0 else 0,
            }

    snapshot = {
        "best_price_btc_ph_day": round(best_price * 1000, 6),
        "best_price_sats_th_day": round(best_price * 1e8, 1),
        "best_venue": best["provider"],
        "spread_vs_second_pct": round((scored[1]["price_per_th_day"] - best_price) / best_price * 100, 1) if len(scored) > 1 else 0,
        "total_liquidity_ph": round(total_ph, 1),
        "total_liquidity_eh": round(total_ph / 1000, 3),
        "regime": regime,
        "vwap_4h_btc_ph_day": round(vwap * 1000, 6),
        "median_btc_ph_day": round(median * 1000, 6),
        "price_range_btc_ph_day": [round(price_min * 1000, 6),
                                    round(price_max * 1000, 6)],
        "offer_count": len(scored),
        "btc_usd": btc_usd,
        "rent_vs_own": rent_vs_own,
    }

    venues = []
    for s in scored:
        price_ph = s["price_per_th_day"] * 1000
        spread_vs_best = round((s["price_per_th_day"] - best_price) / best_price * 100, 1) if best_price > 0 else 0
        spread_vs_vwap = round((s["price_per_th_day"] - vwap) / vwap * 100, 1) if vwap > 0 else 0
        tier = _risk_tier(s["provider"], s.get("estimated", False))
        depth = round(s["hashrate"] / 1000, 1)
        depth_score = "Deep" if depth > 10 else ("Adequate" if depth > 1 else "Thin")

        if s.get("estimated"):
            rec = "Avoid \u2014 modeled quote, not executable"
        elif tier >= 4:
            rec = "Avoid \u2014 counterparty concerns"
        elif spread_vs_best > 20:
            rec = "Liquidity constrained"
        elif tier == 1 and spread_vs_best <= 2:
            rec = "Preferred venue \u2014 best execution"
        elif spread_vs_best <= 5:
            rec = "Acceptable for tactical allocation"
        else:
            rec = "Acceptable risk-adjusted"

        venues.append({
            "venue": s["provider"],
            "price_btc_ph_day": round(price_ph, 6),
            "price_sats_th_day": round(s["price_per_th_day"] * 1e8, 1),
            "spread_vs_best_pct": spread_vs_best,
            "spread_vs_vwap_pct": spread_vs_vwap,
            "available_ph": depth,
            "depth_score": depth_score,
            "risk_tier": tier,
            "risk_tier_label": RISK_TIER_LABELS.get(tier, "Unknown"),
            "recommendation": rec,
            "estimated": bool(s.get("estimated", False)),
            "source": s.get("source", ""),
            "meta": s.get("meta", {}),
        })

    notes = []
    if total_ph < 5:
        notes.append("Low aggregate liquidity \u2014 size > 5 PH may require splitting across venues.")
    if regime in ("Wide", "Dislocated"):
        notes.append(
            f"Market regime is {regime} \u2014 spreads are elevated. "
            "Consider waiting for normalization if not time-sensitive."
        )
    # Deepest-venue note: where can you actually SIZE the trade? Executive
    # buyers care about executable liquidity, not just the best sticker price.
    real = [v for v in venues if not v.get("estimated")]
    if real:
        deepest = max(real, key=lambda v: v.get("available_ph") or 0)
        if (deepest.get("available_ph") or 0) >= 5:
            notes.append(
                f"{deepest['venue']} has the deepest visible liquidity "
                f"({deepest.get('available_ph')} PH/s) \u2014 preferred for sizes above 5 PH."
            )
    # Rent vs own executive callout (CFO): tells the operator whether renting
    # is cheaper or dearer than mining the same hashrate on owned ASICs.
    if rent_vs_own:
        if rent_vs_own["cheaper_than_own"]:
            notes.append(
                f"Best rental is {rent_vs_own['discount_pct']:.0f}% CHEAPER than "
                "mining on owned hardware today \u2014 tactical lease makes sense."
            )
        else:
            notes.append(
                f"Best rental costs {rent_vs_own['premium_pct']:.0f}% MORE than "
                "mining on owned hardware \u2014 prefer your own fleet unless "
                "you need instant scale."
            )
    for v in venues:
        if v["risk_tier"] >= 3 and not v["estimated"]:
            notes.append(
                f"{v['venue']}: Tier {v['risk_tier']} counterparty \u2014 "
                "verify payout reliability before deploying > 1 PH."
            )

    return {
        "regime": regime,
        "snapshot": snapshot,
        "venues": venues,
        "notes": notes,
    }


def build_highlights(
    snapshot: Optional[Dict[str, Any]] = None,
    last_known_prices: Optional[Dict[str, Any]] = None,
    max_items: int = 3,
    max_age_seconds: int = 300,
) -> List[Dict[str, Any]]:
    """Build a small list of market highlights from cached prices.

    Implements stale-while-revalidate: if data exceeds max_age_seconds
    but is less than 2x max_age_seconds, it is included with a ``_stale``
    flag so the frontend can show it while fresh data loads in the
    background. Data older than 2x max_age_seconds is discarded entirely.

    Does not call external APIs, so it is safe to run on every /api/snapshot.
    """
    network_hashrate = None
    if snapshot is not None:
        network_hashrate = (snapshot.get("network") or {}).get("hashrate")

    stale_grace = max_age_seconds * 2  # allow up to 2x TTL before discarding
    ts_now = int(time.time())
    offers: List[NormalizedOffer] = []
    if last_known_prices:
        for provider, entry in last_known_prices.items():
            if not entry or not entry.get("price"):
                continue
            entry_ts = entry.get("ts") or 0
            age = ts_now - entry_ts
            if max_age_seconds > 0 and age > stale_grace:
                continue  # too old, discard
            price_per_ph_day = float(entry["price"])
            if price_per_ph_day <= 0:
                continue
            is_stale = max_age_seconds > 0 and age > max_age_seconds
            offers.append(
                NormalizedOffer(
                    provider=provider,
                    hashrate=DEFAULT_RENTAL_HASHRATE_TH,
                    price_per_th_day=price_per_ph_day / PH_TO_TH,
                    duration_days=1.0,
                    fee_pct=0.0,
                    algorithm="sha256",
                    source=entry.get("source") or provider,
                    estimated=bool(entry.get("estimated", False)),
                    meta={
                        "cached_ts": entry.get("ts"),
                        "label": entry.get("label", ""),
                        "_stale": is_stale,
                        "_age_s": age,
                    },
                )
            )

    scored = [score_offer(o, network_hashrate) for o in offers]
    scored.sort(key=market_offer_sort_key)
    return scored[:max_items]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
