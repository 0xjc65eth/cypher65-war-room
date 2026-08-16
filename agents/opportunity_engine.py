"""
CYPHER65 // Opportunity Engine
==============================
Scans Braiins Hashpower and MiningRigRentals (MRR) markets for
rental deals. Generates stable, price-based IDs for deduplication
so the frontend can suppress repeat popups for the same deal.

Extracted from app.py for testability and modularity.
"""

import time
import logging

log = logging.getLogger("cypher65")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ID generation — stable, price-based dedup key
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def generate_opportunity_id(platform: str, price: float) -> str:
    """Generate a stable, deterministic opportunity ID.

    The ID is derived from the platform name and the price rounded
    to 3 decimal places. The same platform + price always produces
    the same ID, enabling the frontend ``_oppShown`` dedup map to
    suppress repeat popups across sequential scans.

    Parameters
    ----------
    platform : str
        One of ``'braiins'`` or ``'mrr'``.
    price : float
        The ``price_btc_per_ph_day`` value from the marketplace.

    Returns
    -------
    str
        e.g. ``'braiins_0.000'`` or ``'mrr_0.001'``
    """
    return f"{platform}_{round(float(price), 3)}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Platform scanners
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _scan_braiins(execute_tool, snapshot):
    """Query Braiins Hashpower marketplace and return an opportunity dict
    if a valid price is available and worker data exists in the snapshot.

    Returns a single-element list with the opportunity dict, or an
    empty list if no deal is available.
    """
    try:
        braiins = execute_tool("get_braiins_orderbook")
    except Exception as e:
        log.warning("[opp] braiins tool failed: %s", e)
        return []

    braiins_price = braiins.get("price_btc_per_ph_day")
    if braiins_price is None or braiins_price <= 0:
        return []

    difficulty = (snapshot.get("network") or {}).get("difficulty")
    worker_hr = (snapshot.get("worker") or {}).get("hashrate", 0)
    if not difficulty or not worker_hr:
        log.debug(
            "[opp] braiins scan skipped: missing data — difficulty=%s, worker_hr=%s",
            difficulty,
            worker_hr,
        )
        return []

    worker_th = float(worker_hr) / 1e12
    one_btc_worth_ph_days = 1.0 / (float(braiins_price) * 1e6)

    return [
        {
            "id": generate_opportunity_id("braiins", braiins_price),
            "platform": "braiins",
            "title": f"Braiins · {float(braiins_price)*1e6:.1f} sats/PH/day",
            "description": (
                f"With {worker_th:.1f} TH/s you could mine "
                f"~{worker_th / 1000 * one_btc_worth_ph_days:.4f} BTC/day equivalent"
            ),
            "meta": "source: braiins hashpower marketplace — REAL price",
            "price": braiins_price,
            "severity": "INFO",
            "status": "REAL",
        }
    ]


def _scan_mrr(execute_tool, braiins_price):
    """Query MiningRigRentals marketplace and return an opportunity dict
    if a valid price exists and it is at least 10% cheaper than Braiins
    (or Braiins has no price available).

    Returns a single-element list with the opportunity dict, or an
    empty list if no deal is worth showing.
    """
    try:
        mrr = execute_tool("get_mrr_listings")
    except Exception as e:
        log.warning("[opp] mrr tool failed: %s", e)
        return []

    mrr_price = mrr.get("price_btc_per_ph_day")
    if mrr_price is None or mrr_price <= 0:
        return []

    # Only show MRR if it's cheaper than Braiins (if Braiins data exists)
    if braiins_price is not None and not (mrr_price < braiins_price * 0.9):
        return []

    title = (
        f"MRR · {float(mrr_price)*1e6:.1f} sats/PH/day "
        f"({(1 - float(mrr_price)/float(braiins_price))*100:.0f}% cheaper)"
        if braiins_price
        else f"MRR · {float(mrr_price)*1e6:.1f} sats/PH/day"
    )

    return [
        {
            "id": generate_opportunity_id("mrr", mrr_price),
            "platform": "mrr",
            "title": title,
            "description": "MiningRigRentals has active listings — compare with Braiins for best deal",
            "meta": "source: mrr.com marketplace — ESTIMATED",
            "price": mrr_price,
            "severity": "INFO",
            "status": "ESTIMATED",
        }
    ]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  OBSOLETE fallback — last known price shown when market is unavailable
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _make_obsolete(platform, entry):
    """Build a single OBSOLETE opportunity dict from a last_known entry.

    Parameters
    ----------
    platform : str
        ``'braiins'`` or ``'mrr'``.
    entry : dict or None
        Must have ``price``, ``ts``, ``label`` keys.

    Returns
    -------
    dict or None
        Opportunity dict with ``status='OBSOLETE'``, or None if entry is
        missing or incomplete (price, ts, label required).
    """
    if not entry:
        return None
    price = entry.get("price")
    ts = entry.get("ts")
    label = entry.get("label")
    if price is None or ts is None or not label:
        return None
    age_secs = int(time.time()) - ts
    age_human = (
        f"{age_secs // 60}m ago" if age_secs < 3600 else f"{age_secs // 3600}h ago"
    )
    return {
        "id": generate_opportunity_id(platform, price) + "_obsolete",
        "platform": platform,
        "title": f"{platform.title()} \u00b7 OBSOLETE - {label}",
        "description": (
            f"Market data currently UNAVAILABLE. Showing last known price "
            f"from {age_human}. Prices may have changed significantly."
        ),
        "meta": f"source: CACHED from {age_human} \u2014 not real-time market data",
        "price": price,
        "severity": "WARN",
        "status": "OBSOLETE",
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Main scan — orchestrates both platforms
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def scan(execute_tool, snapshot, last_known_prices=None):
    """Run a full opportunity scan across all supported platforms.

    If live scan returns no opportunities but ``last_known_prices`` has
    cached data, OBSOLETE fallback entries are generated so the frontend
    never shows a completely blank panel.

    Parameters
    ----------
    execute_tool : callable
        Function with signature ``(tool_name, params=None) -> dict``
        that returns marketplace data (e.g. ``get_braiins_orderbook``).
        Injected so this module stays testable without real HTTP calls.
    snapshot : dict
        The current ``state.latest_snapshot`` dict, containing at least
        ``network.difficulty`` and ``worker.hashrate`` to compute
        conversion estimates.
    last_known_prices : dict or None
        Mutable dict with ``braiins`` / ``mrr`` sub-keys, each storing
        ``{"price": float, "ts": int, "label": str}`` or ``None``.
        Writable — scan() updates entries when real data is found.
        If None, no fallback is generated and no prices are cached.

    Returns
    -------
    tuple
        ``(opportunities, scan_stats)`` where:
        - opportunities: up to 3 dicts, sorted by platform (Braiins first)
        - scan_stats: dict with ``braiins_ok``, ``braiins_errors``,
          ``mrr_ok``, ``mrr_errors`` counters
    """
    opportunities = []
    scan_stats = {"braiins_ok": 0, "braiins_errors": 0, "mrr_ok": 0, "mrr_errors": 0}

    # ── Braiins scan (isolated — failures MUST NOT lose prior work) ──
    try:
        braiins_opps = _scan_braiins(execute_tool, snapshot)
        braiins_price = braiins_opps[0]["price"] if braiins_opps else None
        opportunities.extend(braiins_opps)
        scan_stats["braiins_ok"] = 1
        # Cache real price
        if braiins_opps and last_known_prices is not None:
            p = braiins_opps[0]
            short_label = (
                p.get("title", "").split("\u00b7", 1)[-1].strip()
                if "\u00b7" in p.get("title", "")
                else p.get("title", "")
            )
            last_known_prices["braiins"] = {
                "price": p["price"],
                "ts": int(time.time()),
                "label": short_label,
            }
    except Exception as e:
        log.warning("[opp] braiins scan exception: %s", e)
        braiins_price = None
        scan_stats["braiins_errors"] = 1

    # ── MRR scan (isolated — failures MUST NOT lose Braiins opportunities) ──
    try:
        mrr_opps = _scan_mrr(execute_tool, braiins_price)
        opportunities.extend(mrr_opps)
        scan_stats["mrr_ok"] = 1
        # Cache real price
        if mrr_opps and last_known_prices is not None:
            p = mrr_opps[0]
            short_label = (
                p.get("title", "").split("\u00b7", 1)[-1].strip()
                if "\u00b7" in p.get("title", "")
                else p.get("title", "")
            )
            last_known_prices["mrr"] = {
                "price": p["price"],
                "ts": int(time.time()),
                "label": short_label,
            }
    except Exception as e:
        log.warning("[opp] mrr scan exception: %s", e)
        scan_stats["mrr_errors"] = 1

    # ── Fallback: generate OBSOLETE opportunities if live scan found nothing ──
    if not opportunities and last_known_prices is not None:
        for platform in ("braiins", "mrr"):
            obs = _make_obsolete(platform, last_known_prices.get(platform))
            if obs:
                opportunities.append(obs)
                log.debug("[opp] generated OBSOLETE fallback for %s", platform)

    return opportunities[:3], scan_stats


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Response builder — wraps opportunities in the standard envelope
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def build_response(opportunities, scan_stats=None):
    """Wrap a list of opportunity dicts in the standard API response envelope.

    Parameters
    ----------
    opportunities : list[dict]
        The results of ``scan()`` (or an empty list).
    scan_stats : dict or None
        Optional dict with ``braiins_ok``, ``braiins_errors``, ``mrr_ok``,
        ``mrr_errors`` counters from ``scan()``. If None, no ``scan_stats``
        key is added to the response (backward compatible).

    Returns
    -------
    dict
        JSON-serializable dict with ``opportunities``, ``ts``, and
        ``disclaimer`` keys. Includes ``scan_stats`` if provided.
    """
    response = {
        "opportunities": opportunities[:3],
        "ts": int(time.time()),
        "disclaimer": (
            "All prices are ESTIMATED based on current market data. "
            "Actual rental prices vary."
        ),
    }
    if scan_stats is not None:
        response["scan_stats"] = scan_stats
    return response
