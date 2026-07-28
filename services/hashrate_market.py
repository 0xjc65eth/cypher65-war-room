"""
CYPHER65 // Hashrate Market Intelligence
==========================================
Fetch, normalize, score and persist rental-market offers from
Braiins Hashpower and MiningRigRentals (MRR).

The public schema is intentionally small so that additional providers can
be added later without changing consumers.
"""

import json
import time
import logging
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional

from agents.solo_mining_advisor.tools import get_braiins_orderbook, get_mrr_listings

log = logging.getLogger("cypher65")

# Conservative post-halving assumption for EV calculations.
BTC_BLOCK_REWARD = 3.125
BLOCKS_PER_DAY = 144
DEFAULT_NETWORK_HASHRATE = 6e20  # ~600 EH/s fallback
DEFAULT_RENTAL_HASHRATE_TH = 1000.0  # 1 PH — used when provider does not expose size


@dataclass
class NormalizedOffer:
    """Common schema for a hashrate rental offer."""

    provider: str
    hashrate: float          # TH/s
    price_per_th_day: float  # BTC per TH per day
    duration_days: float
    fee_pct: float
    algorithm: str
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

    # price_btc_per_ph_day -> BTC/TH/day
    price_per_th_day = price_per_ph_day / 1_000_000.0

    return NormalizedOffer(
        provider="braiins",
        hashrate=DEFAULT_RENTAL_HASHRATE_TH,
        price_per_th_day=price_per_th_day,
        duration_days=1.0,
        fee_pct=0.0,
        algorithm="sha256",
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

    price_per_th_day = price_per_ph_day / 1_000_000.0
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
        meta={
            "source": "miningrigrentals.com",
            "rig_name": data.get("best_rig_name"),
            "total_listings": data.get("total_listings"),
        },
    )


def fetch_all_offers() -> List[NormalizedOffer]:
    """Fetch offers from all supported providers, isolating failures."""
    offers: List[NormalizedOffer] = []

    try:
        b = fetch_braiins_offer()
        if b:
            offers.append(b)
    except Exception as e:
        log.warning("[hashrate_market] Braiins fetch failed: %s", e)

    try:
        m = fetch_mrr_offer()
        if m:
            offers.append(m)
    except Exception as e:
        log.warning("[hashrate_market] MRR fetch failed: %s", e)

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
        price_per_th_day=float(price) / 1_000_000.0,
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

def build_highlights(
    snapshot: Optional[Dict[str, Any]] = None,
    last_known_prices: Optional[Dict[str, Any]] = None,
    max_items: int = 3,
    max_age_seconds: int = 300,
) -> List[Dict[str, Any]]:
    """Build a small list of market highlights from cached prices.

    Does not call external APIs, so it is safe to run on every /api/snapshot.
    """
    network_hashrate = None
    if snapshot is not None:
        network_hashrate = (snapshot.get("network") or {}).get("hashrate")

    ts_now = int(time.time())
    offers: List[NormalizedOffer] = []
    if last_known_prices:
        for provider, entry in last_known_prices.items():
            if not entry or not entry.get("price"):
                continue
            entry_ts = entry.get("ts") or 0
            if max_age_seconds > 0 and (ts_now - entry_ts) > max_age_seconds:
                continue
            price_per_ph_day = float(entry["price"])
            if price_per_ph_day <= 0:
                continue
            offers.append(
                NormalizedOffer(
                    provider=provider,
                    hashrate=DEFAULT_RENTAL_HASHRATE_TH,
                    price_per_th_day=price_per_ph_day / 1_000_000.0,
                    duration_days=1.0,
                    fee_pct=0.0,
                    algorithm="sha256",
                    meta={"cached_ts": entry.get("ts"), "label": entry.get("label", "")},
                )
            )

    scored = [score_offer(o, network_hashrate) for o in offers]
    scored.sort(key=lambda x: x["metrics"]["score"], reverse=True)
    return scored[:max_items]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
