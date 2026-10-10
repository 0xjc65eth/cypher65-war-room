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
import math
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional

from agents.solo_mining_advisor.tools import (
    get_braiins_orderbook,
    get_mrr_listings,
    get_nicehash_orderbook,
)

log = logging.getLogger("cypher65")

# Conservative post-halving assumption for EV calculations.
BTC_BLOCK_REWARD = 3.125
BLOCKS_PER_DAY = 144
DEFAULT_NETWORK_HASHRATE = 6e20  # ~600 EH/s fallback
DEFAULT_RENTAL_HASHRATE_TH = 1000.0  # 1 PH — used when provider does not expose size
PH_TO_TH = 1000.0  # 1 PH = 1000 TH — per-PH/day → per-TH/day conversion
# Plausible floor for a SHA-256 rental quote (~0.42 sats/TH·h). Anything
# below is an estimation glitch (e.g. giant-pool fee math underflowing to
# ~1e-9 BTC/TH·day) — never emit, persist or show it, or 'cheapest market'
# analytics collapse to 0 sats/TH·h.
MIN_PLAUSIBLE_PRICE_BTC_TH_DAY = 1e-7


@dataclass
class NormalizedOffer:
    """Common schema for a hashrate rental offer."""

    provider: str
    hashrate: float  # TH/s
    price_per_th_day: float  # BTC per TH per day
    duration_days: float
    fee_pct: float
    algorithm: str
    source: str = ""  # origin label: braiins|mrr|nicehash|parasite|derived
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
    if (
        not data
        or data.get("error")
        or data.get("needs_auth")
        or "price_btc_per_ph_day" not in data
    ):
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
    hashrate_th = (
        hashrate_ph * 1000.0 if hashrate_ph > 0 else DEFAULT_RENTAL_HASHRATE_TH
    )

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


def fetch_parasite_offer(
    network_hashrate: Optional[float] = None,
) -> Optional[NormalizedOffer]:
    """Parasite 'refinery' estimate — RETIRED (always None).

    The fee-only model is mathematically sub-floor: price collapses to
    4.5e12 / net_hr (the pool_hr term cancels), i.e. ~7.5e-9 BTC/TH·day
    ≈ 0.04 sats/TH·h — ~1000× below real rental prices. Every such quote
    would be rejected by MIN_PLAUSIBLE_PRICE_BTC_TH_DAY anyway, so calling
    the pool API every market poll only wastes a request on a guaranteed
    discard. Short-circuit here; the aggregator skips None."""
    return None
    # fmt: off
    from agents.solo_mining_advisor.tools import get_parasite_pool_stats  # noqa: F401
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
        price_per_th_day = (daily_pool_revenue_btc * (fee_pct / 100.0)) / (pool_hr_hs / 1e12) if pool_hr_hs > 0 else 0.0
        # A sub-floor quote is a glitch of the estimation, not real hashpower —
        # never emit it (it would be persisted as 'cheapest' and zero out the
        # market-timing analytics in the rentals panel).
        if price_per_th_day < MIN_PLAUSIBLE_PRICE_BTC_TH_DAY:
            return None

        return NormalizedOffer(
            provider="parasite",
            hashrate=pool_hr_hs / 1e12 if pool_hr_hs > 0 else DEFAULT_RENTAL_HASHRATE_TH,
            price_per_th_day=price_per_th_day,
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
_FETCH_CACHE_TTL = 60  # seconds — successful fetches
_FETCH_CACHE_EMPTY_TTL = 15  # seconds — empty/errored fetches (retry sooner)
# Fase 3 · P1: simple retry/backoff on transient provider failures (429/5xx).
# The provider tools already surface HTTP errors as error-dicts → fetchers
# return None, so we retry the whole fetch when it yields nothing, with a
# short linear backoff. Bounded (1 retry) so we never hammer the APIs.
_FETCH_RETRIES = 1  # extra attempts after the first
_FETCH_BACKOFF_BASE = 0.15  # seconds — linear backoff before each retry


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
        ttl = (
            _FETCH_CACHE_TTL
            if entry.get("value") is not None
            else _FETCH_CACHE_EMPTY_TTL
        )
        if now - entry.get("ts", 0) < ttl:
            return entry["value"]

    value = None
    for attempt in range(_FETCH_RETRIES + 1):
        try:
            value = fetcher()
            if value is not None:
                break
        except Exception as e:  # keep cache consistent on failure
            log.warning(
                "[hashrate_market] %s fetch failed (attempt %d/%d): %s",
                key,
                attempt + 1,
                _FETCH_RETRIES + 1,
                e,
            )
            value = None
        if attempt < _FETCH_RETRIES:
            time.sleep(_FETCH_BACKOFF_BASE * (attempt + 1))

    # Record completion time, not the pre-fetch time, so backoff/slow
    # fetches don't silently eat into the TTL.
    _FETCH_CACHE[key] = {"ts": time.time(), "value": value}
    # Freshness stamp (M4): the institutional view exposes per-venue
    # fetched_at so the panel can show how OLD the quote really is instead
    # of pretending a cached price is "now". Only stamped on a real fetch
    # (a cache hit returns the same object — the timestamp stays truthful).
    if value is not None and hasattr(value, "meta") and isinstance(value.meta, dict):
        value.meta["fetched_at"] = int(_FETCH_CACHE[key]["ts"])
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

    ``network_hashrate`` MUST be a value already resolved against the
    shared Metric Provenance Contract. Callers MUST NOT pass raw API
    values here: a missing network hashrate is reported as 0 and the
    caller records how the value was obtained, so this function can never
    silently turn a real 0 into 600 EH/s.
    """
    supplied = network_hashrate if network_hashrate is not None else 0.0
    net_hr = supplied if supplied > 0 else DEFAULT_NETWORK_HASHRATE
    if network_hashrate is None:
        network_hashrate_source = "UNKNOWN"
    elif supplied > 0:
        network_hashrate_source = "LIVE"
    else:
        network_hashrate_source = "FALLBACK"

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
        "roi": round(roi, 6),
        "estimated_cost_btc": round(estimated_cost, 8),
        "estimated_revenue_btc": round(estimated_revenue, 8),
        "expected_value_btc": round(expected_value, 8),
        "risk_level": risk,
        "network_hashrate": net_hr,
        "network_hashrate_source": network_hashrate_source,
        "duration_days": duration_days,
    }


def _source_for_network_hashrate(network_hashrate: Optional[float]) -> str:
    """Match the Metric Contract's network-hashrate provenance values.

    LIVE when a real network sample is present, FALLBACK when this module
    had to substitute the 600 EH/s default, UNKNOWN when nothing was
    supplied at all.
    """
    if network_hashrate is None:
        return "UNKNOWN"
    return "LIVE" if network_hashrate > 0 else "FALLBACK"



def score_offer(
    offer: NormalizedOffer, network_hashrate: Optional[float] = None
) -> Dict[str, Any]:
    """Convenience wrapper: full dict of offer + metrics.

    ``network_hashrate`` follows the same contract as compute_metrics:
    LIQUE, UNKNOWN, or FALLBACK. When the caller passes a real sample
    from snapshot, the score uses it and advertises LIVE; when only the
    600 EH/s default is available, the score is still computed but the
    payload says FALLBACK and the frontend must render it as estimated.
    """
    return {
        "id": f"{offer.provider}_{offer.price_per_th_day:.6f}",
        **offer.to_dict(),
        "metrics": compute_metrics(offer, network_hashrate),
        "network_hashrate_source": _source_for_network_hashrate(network_hashrate),
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
    opp["network_hashrate_source"] = _source_for_network_hashrate(network_hashrate)
    return opp


def _empty_metrics() -> Dict[str, Any]:
    return {
        "score": 0.0,
        "roi": 0.0,
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

_purged_glitch_history = False  # one-time legacy cleanup per process


def _purge_glitch_history(conn: Any) -> None:
    """One-time cleanup of legacy sub-floor (glitch) rows written by the old
    parasite estimator (1e-8 BTC/TH·day). Deleting them makes every consumer
    (rentals market timing, Market module charts) show REAL prices only."""
    global _purged_glitch_history
    if _purged_glitch_history:
        return
    _purged_glitch_history = True
    try:
        c = conn.cursor()
        c.execute(
            "DELETE FROM hashrate_market_history "
            "WHERE algorithm='sha256' AND price_per_th_day > 0 AND price_per_th_day < ?",
            (MIN_PLAUSIBLE_PRICE_BTC_TH_DAY,),
        )
        conn.commit()
    except Exception as e:
        # Issue #202: a failed purge is degradation — never silent.
        log.warning("[hashrate_market] glitch-history purge failed: %s", e)


def persist_market_history(
    conn: Any,
    offers: List[NormalizedOffer],
) -> None:
    """Persist the current market snapshot to SQLite.

    ``conn`` is an open sqlite3 connection with row_factory set.
    """
    if not offers:
        _purge_glitch_history(conn)
        return

    c = conn.cursor()
    ts = int(time.time())
    _purge_glitch_history(conn)
    for offer in offers:
        # sha256-only floor: scrypt and other algorithms have legitimately
        # cheaper per-TH prices and must never be filtered.
        if (
            offer.algorithm == "sha256"
            and offer.price_per_th_day < MIN_PLAUSIBLE_PRICE_BTC_TH_DAY
        ):
            continue  # glitch floor — never pollute the history table
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
           WHERE (algorithm != 'sha256' OR price_per_th_day >= ?)
           ORDER BY ts DESC, provider ASC
           LIMIT ?""",
        (MIN_PLAUSIBLE_PRICE_BTC_TH_DAY, limit),
    )
    rows = []
    for r in c.fetchall():
        rows.append(
            {
                "ts": r["ts"],
                "provider": r["provider"],
                "hashrate": r["hashrate"],
                "price_per_th_day": r["price_per_th_day"],
                "duration_days": r["duration_days"],
                "fee_pct": r["fee_pct"],
                "algorithm": r["algorithm"],
                "score": r["score"],
                "raw_data": r["raw_data"],
            }
        )
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
    "braiins": 1,  # Tier 1 — institutional (Braiins OS+, smartpool, regulated)
    "nicehash": 2,  # Tier 2 — established marketplace, KYC, escrow
    "mrr": 2,  # Tier 2 — established marketplace, escrow
    "parasite": 3,  # Tier 3 — pool-based, own hardware required, modeled not live
    "derived": 4,  # Tier 4 — synthetic/derived, not executable
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
        allowance = float(
            os.environ.get("HARDWARE_ALLOWANCE_PCT", hardware_allowance_pct)
        )
    except (TypeError, ValueError):
        eff, price, allowance = (
            efficiency_j_th,
            electricity_usd_per_kwh,
            hardware_allowance_pct,
        )
    if eff <= 0 or price <= 0:
        return None
    energy_kwh_per_th_day = (eff * 86400) / 3.6e6
    cost = energy_kwh_per_th_day * price * (1.0 + allowance)
    return cost if cost > 0 else None


def market_rankings_view(offers: List[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """Pure, deterministic rankings over valid scored public offer records."""
    def finite_number(value: Any, default: float = 0.0) -> float:
        try:
            number = float(value)
            return number if math.isfinite(number) else default
        except (TypeError, ValueError, OverflowError):
            return default

    provider = lambda row: str(row.get("provider") or "")
    real = [
        row for row in offers or []
        if isinstance(row, dict)
        and not row.get("estimated")
        and finite_number(row.get("price_per_th_day")) > 0
        and finite_number(row.get("hashrate")) > 0
    ]
    if not real:
        return {"cheapest": None, "best_score": None, "freshest": None, "most_capacity": None}
    cheapest = min(real, key=lambda row: (finite_number(row.get("price_per_th_day"), float("inf")), provider(row)))
    best_score = max(real, key=lambda row: (finite_number((row.get("metrics") or {}).get("score")), -finite_number(row.get("price_per_th_day")), provider(row)))
    with_quote_age = []
    for row in real:
        intelligence = row.get("market_intelligence") or (row.get("meta") or {}).get("market_intelligence") or {}
        age = intelligence.get("quote_age_seconds")
        if intelligence.get("freshness") == "LIVE" and age is not None and finite_number(age, -1) >= 0:
            with_quote_age.append((row, finite_number(age)))
    freshest = min(with_quote_age, key=lambda pair: (pair[1], provider(pair[0])), default=None)
    capacity = max(real, key=lambda row: (finite_number(row.get("hashrate")), provider(row)))
    return {
        "cheapest": provider(cheapest),
        "best_score": provider(best_score),
        "freshest": provider(freshest[0]) if freshest else None,
        "most_capacity": provider(capacity),
    }


def _timestamp_age_seconds(timestamp: Any, now: int) -> Optional[int]:
    """Return age only for finite, non-future timestamps; bad clocks are UNKNOWN."""
    try:
        stamp = float(timestamp)
        if not math.isfinite(stamp) or stamp > now:
            return None
        return max(0, now - int(stamp))
    except (TypeError, ValueError, OverflowError):
        return None


def _offer_value(offer: Any, key: str, default: Any = None) -> Any:
    if isinstance(offer, dict):
        return offer.get(key, default)
    return getattr(offer, key, default)


def _valid_market_offer(offer: Any) -> bool:
    """Reject malformed provider records before they affect availability or ranks."""
    try:
        numbers = [
            float(_offer_value(offer, "price_per_th_day")),
            float(_offer_value(offer, "hashrate")),
            float(_offer_value(offer, "duration_days", 1.0) or 1.0),
            float(_offer_value(offer, "fee_pct", 0.0) or 0.0),
        ]
    except (TypeError, ValueError, OverflowError):
        return False
    if not all(math.isfinite(number) for number in numbers):
        return False
    price, hashrate, duration, fee_pct = numbers
    if price <= 0 or hashrate <= 0 or duration <= 0 or fee_pct < 0:
        return False
    cost = hashrate * price * duration * (1 + fee_pct / 100)
    revenue = (hashrate * 1e12 / DEFAULT_NETWORK_HASHRATE) * BLOCKS_PER_DAY * BTC_BLOCK_REWARD * duration
    return math.isfinite(cost) and math.isfinite(revenue)


def build_market_intelligence(
    offers: List[NormalizedOffer],
    provider_cache: Optional[Dict[str, Dict[str, Any]]] = None,
    now: Optional[int] = None,
    stale_after_seconds: int = 300,
) -> Dict[str, Any]:
    """Summarize provider health, quote/cache freshness, and ranks.

    ``provider_cache`` accepts provider-name to ``{ts, price, source}`` entries.
    Timestamps are evidence: without one a quote is AVAILABLE but freshness is
    UNKNOWN, never LIVE by assumption.
    """
    now = int(time.time()) if now is None else int(now)
    stale_after_seconds = max(0, int(stale_after_seconds))
    cache = provider_cache if isinstance(provider_cache, dict) else {}
    supported = ("braiins", "mrr", "nicehash")
    by_provider = {}
    for offer in offers or []:
        provider = str(
            getattr(offer, "provider", "") or (offer.get("provider") if isinstance(offer, dict) else "")
        ).lower()
        if (
            provider in supported
            and provider not in by_provider
            and not bool(_offer_value(offer, "estimated", False))
            and _valid_market_offer(offer)
        ):
            by_provider[provider] = offer

    providers = {}
    fresh_count = 0
    for provider in supported:
        offer = by_provider.get(provider)
        cache_entry = cache.get(provider) if isinstance(cache.get(provider), dict) else {}
        if not cache_entry and provider_cache is None:
            cache_entry = _FETCH_CACHE.get(provider) or {}
        if not cache_entry and provider in cache and cache.get(provider):
            cache_entry = {"ts": cache.get(provider)}
        if not cache_entry and not offers and provider_cache is None:
            cache_entry = {"unavailable": True}
        cache_ts = cache_entry.get("ts")
        cached_offer = cache_entry.get("value")
        if offer is None and _valid_market_offer(cached_offer) and not bool(_offer_value(cached_offer, "estimated", False)):
            offer = cached_offer
            by_provider[provider] = offer
            cache_ts = cache_entry.get("ts")
        if not cache_entry and provider in cache:
            cache_entry = {"ts": cache.get(provider)}
            cache_ts = cache_entry.get("ts")
        cache_age = _timestamp_age_seconds(cache_ts, now)
        if (
            offer is None
            and cache_entry.get("price")
            and not cache_entry.get("estimated", False)
            and cache_age is not None
            and cache_age <= stale_after_seconds * 2
        ):
            try:
                cached_price = float(cache_entry["price"])
                cached_hashrate = float(cache_entry.get("hashrate") or DEFAULT_RENTAL_HASHRATE_TH)
                if math.isfinite(cached_price) and cached_price > 0 and math.isfinite(cached_hashrate) and cached_hashrate > 0:
                    offer = NormalizedOffer(
                        provider=provider,
                        hashrate=cached_hashrate,
                        price_per_th_day=cached_price / PH_TO_TH,
                        duration_days=1.0,
                        fee_pct=0.0,
                        algorithm="sha256",
                        source=cache_entry.get("source") or provider,
                        estimated=bool(cache_entry.get("estimated", False)),
                        meta={"cached_ts": cache_ts, "_stale": True},
                    )
                    by_provider[provider] = offer
            except (TypeError, ValueError, OverflowError):
                pass
        meta = getattr(offer, "meta", {}) if offer is not None else {}
        if not meta and isinstance(offer, dict):
            meta = offer.get("meta", {})
        meta = meta if isinstance(meta, dict) else {}
        cached_meta = getattr(cached_offer, "meta", {})
        quote_ts = meta.get("fetched_at")
        if quote_ts is None:
            quote_ts = meta.get("cached_ts")
        if quote_ts is None and isinstance(cached_meta, dict):
            quote_ts = cached_meta.get("fetched_at")
        if quote_ts is None and cached_offer is offer and cache_ts is not None:
            quote_ts = meta.get("fetched_at") or meta.get("cached_ts") or cache_ts
        quote_age = _timestamp_age_seconds(quote_ts, now)
        stale_flag = bool(meta.get("_stale"))
        has_quote = offer is not None
        is_fresh = has_quote and quote_age is not None and quote_age <= stale_after_seconds and not stale_flag
        if is_fresh:
            status = "AVAILABLE"
            freshness = "LIVE"
            fresh_count += 1
        elif has_quote:
            status = "AVAILABLE"
            freshness = "STALE" if quote_age is not None or stale_flag else "UNKNOWN"
        else:
            status = "UNAVAILABLE" if cache_ts is not None or (cache_entry and ("value" in cache_entry or cache_entry.get("unavailable"))) else "UNKNOWN"
            freshness = "NO DATA"
        offer_source = (
            getattr(offer, "source", "")
            or (offer.get("source") if isinstance(offer, dict) else None)
            or provider
        ) if has_quote else None
        offer_estimated = (
            bool(getattr(offer, "estimated", False))
            if has_quote and not isinstance(offer, dict)
            else bool(offer.get("estimated", False)) if has_quote else None
        )
        providers[provider] = {
            "status": status,
            "freshness": freshness,
            "quote_age_seconds": quote_age,
            "cache_age_seconds": cache_age,
            "source": offer_source,
            "estimated": offer_estimated,
            "cheapest": None,
            "best_score": None,
            "freshest": None,
            "most_capacity": None,
        }
    def _as_offer(raw_offer, provider):
        if isinstance(raw_offer, NormalizedOffer):
            return raw_offer
        try:
            return NormalizedOffer(
                provider=provider,
                hashrate=float(raw_offer.get("hashrate") or 0),
                price_per_th_day=float(raw_offer.get("price_per_th_day") or 0),
                duration_days=float(raw_offer.get("duration_days") or 1),
                fee_pct=float(raw_offer.get("fee_pct") or 0),
                algorithm=str(raw_offer.get("algorithm") or "sha256"),
                source=str(raw_offer.get("source") or ""),
                estimated=bool(raw_offer.get("estimated", False)),
                meta=dict(raw_offer.get("meta") or {}),
            )
        except (AttributeError, TypeError, ValueError, OverflowError):
            return None

    normalized = {
        provider: _as_offer(offer, provider)
        for provider, offer in by_provider.items()
    }
    normalized = {
        provider: offer
        for provider, offer in normalized.items()
        if offer is not None and _valid_market_offer(offer) and not offer.estimated
    }

    real_offers = [offer for offer in normalized.values() if not offer.estimated]
    scored = []
    for offer in real_offers:
        metrics = compute_metrics(offer, None)
        try:
            cost = float(offer.hashrate) * float(offer.price_per_th_day) * float(offer.duration_days or 1.0) * (1 + float(offer.fee_pct) / 100)
            revenue = float(offer.hashrate) * 1e12 / DEFAULT_NETWORK_HASHRATE * BLOCKS_PER_DAY * BTC_BLOCK_REWARD * float(offer.duration_days or 1.0)
            roi = (revenue - cost) / cost if cost > 0 else 0.0
            metrics["score"] = round(roi * 100, 2) if math.isfinite(roi) else 0.0
        except (TypeError, ValueError, OverflowError, ZeroDivisionError):
            metrics["score"] = 0.0
        scored.append((offer, metrics))
    cheapest = min(scored, key=lambda pair: (pair[0].price_per_th_day, pair[0].provider)) if scored else None
    best_score = max(scored, key=lambda pair: (pair[1]["score"], -pair[0].price_per_th_day, pair[0].provider)) if scored else None
    freshest = min(
        (
            pair for pair in scored
            if providers[pair[0].provider]["quote_age_seconds"] is not None
            and providers[pair[0].provider]["freshness"] == "LIVE"
        ),
        key=lambda pair: (providers[pair[0].provider]["quote_age_seconds"], pair[0].provider),
        default=None,
    )
    capacity = max(
        scored, key=lambda pair: (pair[0].hashrate, pair[0].provider), default=None
    )
    rankings = {
        "cheapest": cheapest[0].provider if cheapest else None,
        "best_score": best_score[0].provider if best_score else None,
        "freshest": freshest[0].provider if freshest else None,
        "most_capacity": capacity[0].provider if capacity else None,
    }
    for provider, provider_data in providers.items():
        if provider_data["status"] != "AVAILABLE":
            continue
        for rank_name, rank_provider in rankings.items():
            provider_data[rank_name] = rank_provider == provider if rank_provider else None
    available = len(normalized)
    status = (
        "NO DATA"
        if available == 0
        else "AVAILABLE"
        if available == len(supported) and fresh_count == len(supported)
        else "PARTIAL"
    )
    return {
        "status": status,
        "available_provider_count": available,
        "total_provider_count": len(supported),
        "provider_denominator": list(supported),
        "fresh_provider_count": fresh_count,
        "stale_provider_count": sum(1 for item in providers.values() if item["freshness"] == "STALE"),
        "cache_age_seconds": max(
            (item["cache_age_seconds"] for item in providers.values() if item["cache_age_seconds"] is not None),
            default=None,
        ),
        "cache_age_source": (
            max(
                (item for item in providers.items() if item[1]["cache_age_seconds"] is not None),
                key=lambda item: item[1]["cache_age_seconds"],
                default=(None, None),
            )[0]
        ),
        "providers": providers,
        "rankings": rankings,
    }


def compute_institutional_view(
    offers: List[NormalizedOffer],
    network_hashrate: Optional[float] = None,
    btc_usd: Optional[float] = None,
    provider_cache: Optional[Dict[str, Dict[str, Any]]] = None,
    now: Optional[int] = None,
) -> Dict[str, Any]:
    """Build the HashratePulse Enterprise institutional view from raw offers.

    Returns the Executive Snapshot + Ranked Venue Table as a single dict
    that the frontend renders directly.
    """
    offers = [offer for offer in (offers or []) if _valid_market_offer(offer)]
    market_intelligence = build_market_intelligence(
        offers,
        provider_cache if provider_cache is not None else _FETCH_CACHE,
        now,
        stale_after_seconds=300,
    )
    offers = [offer for offer in offers if _valid_market_offer(offer)]
    if not offers:
        return {
            "regime": "No Data",
            "snapshot": None,
            "venues": [],
            "notes": [],
            "market_intelligence": market_intelligence,
        }

    # Score every offer
    scored = [score_offer(o, network_hashrate) for o in offers]
    # Sort: estimated last, then best price first
    scored.sort(key=lambda s: (bool(s.get("estimated", False)), s["price_per_th_day"]))

    best = scored[0]
    best_price = best["price_per_th_day"]

    # Regime detection
    if len(scored) >= 3:
        spread_pct = (
            (scored[-1]["price_per_th_day"] - best_price) / best_price * 100
            if best_price > 0
            else 0
        )
        regime = (
            "Tight"
            if spread_pct < 5
            else (
                "Normal"
                if spread_pct < 15
                else ("Wide" if spread_pct < 40 else "Dislocated")
            )
        )
    else:
        regime = "Normal"

    # Total visible liquidity (PH/s)
    total_ph = sum(o.hashrate for o in offers) / 1000.0

    # VWAP — liquidity-WEIGHTED mean price, not a naive average. A venue
    # quoting a silly price with 100 PH should not skew the exec benchmark
    # the way a simple mean would (CFO audit: naive mean misleads allocation).
    prices = [s["price_per_th_day"] for s in scored]
    sizes_th = [max(float(s.get("hashrate") or 0), 1.0) for s in scored]
    vwap = (
        (sum(p * w for p, w in zip(prices, sizes_th)) / sum(sizes_th))
        if prices
        else 0.0
    )
    prices_sorted = sorted(prices)
    n = len(prices_sorted)
    median = (
        prices_sorted[n // 2]
        if n % 2
        else (prices_sorted[n // 2 - 1] + prices_sorted[n // 2]) / 2.0
    )
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
        "spread_vs_second_pct": (
            round((scored[1]["price_per_th_day"] - best_price) / best_price * 100, 1)
            if len(scored) > 1
            else 0
        ),
        "total_liquidity_ph": round(total_ph, 1),
        "total_liquidity_eh": round(total_ph / 1000, 3),
        "regime": regime,
        "vwap_4h_btc_ph_day": round(vwap * 1000, 6),
        "median_btc_ph_day": round(median * 1000, 6),
        "price_range_btc_ph_day": [
            round(price_min * 1000, 6),
            round(price_max * 1000, 6),
        ],
        "offer_count": len(scored),
        "btc_usd": btc_usd,
        "rent_vs_own": rent_vs_own,
    }

    venues = []
    for s in scored:
        price_ph = s["price_per_th_day"] * 1000
        spread_vs_best = (
            round((s["price_per_th_day"] - best_price) / best_price * 100, 1)
            if best_price > 0
            else 0
        )
        spread_vs_vwap = (
            round((s["price_per_th_day"] - vwap) / vwap * 100, 1) if vwap > 0 else 0
        )
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

        metrics = s.get("metrics") or {}
        _meta = s.get("meta") or {}
        venues.append(
            {
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
                # M5: profit-oriented columns — score/ROI/EV are already
                # computed by compute_metrics() but were dropped at the view
                # boundary; expose them so the panel ranks by VALUE, not just
                # by sticker price.
                "score": metrics.get("score"),
                "roi_pct": (
                    round(metrics.get("roi", 0.0) * 100.0, 1)
                    if metrics.get("roi") is not None
                    else None
                ),
                "expected_value_btc": metrics.get("expected_value_btc"),
                "estimated_cost_btc": metrics.get("estimated_cost_btc"),
                "risk_level": metrics.get("risk_level"),
                # M4: freshness — when this quote was really fetched (0/absent
                # on legacy payloads → frontend shows '—').
                "fetched_at": _meta.get("fetched_at"),
                "meta": _meta,
            }
        )

    notes = []
    if total_ph < 5:
        notes.append(
            "Low aggregate liquidity \u2014 size > 5 PH may require splitting across venues."
        )
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

    intelligence = market_intelligence
    snapshot["market_intelligence"] = {
        key: value for key, value in intelligence.items() if key != "providers"
    }
    return {
        "regime": regime,
        "snapshot": snapshot,
        "venues": venues,
        "notes": notes,
        "market_intelligence": intelligence,
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

    if last_known_prices is None:
        return []
    stale_grace = max_age_seconds * 2  # allow up to 2x TTL before discarding
    ts_now = int(time.time())
    offers: List[NormalizedOffer] = []
    if last_known_prices is not None:
        for provider, entry in last_known_prices.items():
            if not isinstance(entry, dict) or not entry.get("price"):
                continue
            entry_ts = entry.get("ts")
            age = _timestamp_age_seconds(entry_ts, ts_now)
            if age is None:
                continue  # no trustworthy timestamp; never treat as a current highlight
            if max_age_seconds > 0 and age > stale_grace:
                continue  # too old, discard
            try:
                price_per_ph_day = float(entry["price"])
            except (TypeError, ValueError, OverflowError):
                continue
            if not math.isfinite(price_per_ph_day) or price_per_ph_day <= 0:
                continue
            is_stale = max_age_seconds > 0 and age > max_age_seconds
            try:
                cached_hashrate = float(entry.get("hashrate") or DEFAULT_RENTAL_HASHRATE_TH)
            except (TypeError, ValueError, OverflowError):
                continue
            if not math.isfinite(cached_hashrate) or cached_hashrate <= 0:
                continue
            offers.append(
                NormalizedOffer(
                    provider=provider,
                    hashrate=cached_hashrate,
                    price_per_th_day=price_per_ph_day / PH_TO_TH,
                    duration_days=1.0,
                    fee_pct=0.0,
                    algorithm="sha256",
                    source=entry.get("source") or provider,
                    estimated=bool(entry.get("estimated", False)),
                    meta={
                        "cached_ts": entry_ts,
                        "label": entry.get("label", ""),
                        "_stale": is_stale,
                        "_age_s": age,
                    },
                )
            )

    scored = [score_offer(o, network_hashrate) for o in offers]
    scored.sort(key=market_offer_sort_key)
    intelligence = build_market_intelligence(offers, last_known_prices or {}, now=ts_now, stale_after_seconds=max_age_seconds)
    for item in scored:
        provider = item.get("provider")
        if provider in intelligence["providers"]:
            item["market_intelligence"] = intelligence["providers"][provider]
    intelligence["rankings"] = market_rankings_view(scored)
    return scored[:max_items]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
