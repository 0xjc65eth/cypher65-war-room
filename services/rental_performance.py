"""
CYPHER65 // Rental Performance — MRR rentals + Braiins contracts
==================================================================
Operator-owned rental intelligence for the dashboard RENTALS panel:

  - MRR  `GET /rental`            → list rentals (renter/owner, active/history)
  - MRR  `GET /rental/{id}`       → detail (hashrate advertised/average, price paid, rig)
  - MRR  `GET /rental/{id}/graph` → hashrate time series (bars, per minute)
  - MRR  `GET /rental/{id}/log`   → event log (created/paid/started/finished)
  - Braiins `GET /contract`       → caller-owned contracts (needs BRAIINS_API_KEY)
  - Braiins `GET /contract/{id}/speed` → contract speed time series

Fail-closed: any hiccup returns an empty/safe block — the panel never
breaks because a provider credential is missing (MRR keys optional; Braiins
key not configured yet → contracts list returns an explicit note).
"""

import os
import time
import logging
from typing import Any, Dict, List, Optional

import requests

from agents.solo_mining_advisor.tools import _mrr_signed_headers, mrr_credentials, braiins_credentials

log = logging.getLogger("cypher65")

MRR_BASE = "https://www.miningrigrentals.com/api/v2"
BRAIINS_BASE = "https://hashpower.braiins.com/v1"
PH_TO_TH = 1000.0


# ── Credentials: shared resolver in agents/solo_mining_advisor/tools.py ──
_mrr_creds = mrr_credentials


def _braiins_key() -> str:
    """Braiins API key: env first, Settings modal fallback (shared resolver)."""
    return braiins_credentials().get("api_key") or ""


# ── MRR: rentals ─────────────────────────────────────────────────────────────

def fetch_mrr_rentals(
    rtype: str = "renter",
    history: bool = False,
    limit: int = 25,
) -> Dict[str, Any]:
    """List MRR rentals for the operator (default: renter, active only).

    Returns a normalized list plus auth status so the panel can render an
    honest empty/error state:
      {"success": True, "needs_auth": False, "rentals": [...], "total": n}
    """
    creds = _mrr_creds()
    if not (creds["api_key"] and creds["api_secret"]):
        return {"success": False, "needs_auth": True, "rentals": [], "total": 0}

    # MRR signs the PATH WITHOUT query params (verified live: signing
    # '/rental?type=...' fails with 'String to sign: .../rental'). Pass the
    # filters as separate request params instead.
    endpoint = "/rental"
    qparams = {"type": rtype}
    if history:
        qparams["history"] = "true"
    qparams["limit"] = limit

    try:
        r = requests.get(
            MRR_BASE + endpoint,
            headers=_mrr_signed_headers(creds["api_key"], creds["api_secret"], endpoint),
            params=qparams,
            timeout=15,
        )
        if not r.ok:
            return {"success": False, "needs_auth": False, "error": f"HTTP {r.status_code}", "rentals": [], "total": 0}
        data = r.json()
        if not data.get("success"):
            return {"success": False, "needs_auth": False,
                    "error": str(data.get("data") or data.get("message") or "MRR error"),
                    "rentals": [], "total": 0}
        raw = data.get("data") or {}
        records = raw.get("rentals") or []
        rentals = []
        for rv in records:
            if not isinstance(rv, dict):
                continue
            rentals.append(_normalize_rental(rv))
        return {
            "success": True,
            "needs_auth": False,
            "rentals": rentals,
            "total": raw.get("total") or len(rentals),
        }
    except Exception as e:
        log.warning("[rental_performance] mrr rentals fetch failed: %s", e)
        return {"success": False, "needs_auth": False, "error": str(e)[:120], "rentals": [], "total": 0}


def fetch_mrr_rental_detail(rental_id: str) -> Dict[str, Any]:
    """Full detail + graph + log for one MRR rental."""
    creds = _mrr_creds()
    if not (creds["api_key"] and creds["api_secret"]):
        return {"success": False, "needs_auth": True}

    out: Dict[str, Any] = {"success": False}
    for sub, key in (("", "detail"), ("/graph", "graph"), ("/log", "log")):
        endpoint = f"/rental/{rental_id}{sub}"
        try:
            r = requests.get(
                MRR_BASE + endpoint,
                headers=_mrr_signed_headers(creds["api_key"], creds["api_secret"], endpoint),
                timeout=15,
            )
            if not r.ok:
                out[key] = {"error": f"HTTP {r.status_code}"}
                continue
            data = r.json()
            out[key] = data.get("data") if data.get("success") else {"error": data.get("data")}
        except Exception as e:
            out[key] = {"error": str(e)[:120]}

    out["success"] = bool(out.get("detail") and not out["detail"].get("error"))
    return out


def _hash_to_th(value: Any, unit: Any) -> Optional[float]:
    """Convert an MRR hashrate value to TH/s.

    MRR reports hashrate as ``{hash: 0.165, type: "ph", nice: "165.00T"}`` —
    the raw ``hash`` is in the ``type`` unit (ph/mh/gh/th). Normalizing to
    TH/s here keeps the panel honest (0.165 PH = 165 TH, NOT 0.165 TH).
    """
    v = _num(value)
    if v is None:
        return None
    unit = str(unit or "").lower()
    if unit == "ph":
        return v * PH_TO_TH
    if unit == "th":
        return v
    if unit == "gh":
        return v / 1000.0
    if unit == "mh":
        return v / 1_000_000.0
    return v  # unknown unit — keep raw (honest, no invented scale)


def _normalize_rental(rv: Dict[str, Any]) -> Dict[str, Any]:
    """Map an MRR rental dict to the panel's display schema."""
    hr = rv.get("hashrate") or {}
    advertised = hr.get("advertised") or {}
    average = hr.get("average") or {}
    price = rv.get("price") or {}
    rig = rv.get("rig") or {}
    rig_status = rig.get("status") or {}
    return {
        "id": rv.get("id"),
        "owner": rv.get("owner"),
        "renter": rv.get("renter"),
        "hashrate_advertised_th": _hash_to_th(advertised.get("hash"), advertised.get("type")),
        "hashrate_average_th": _hash_to_th(average.get("hash"), average.get("type")),
        "hashrate_percent": _num(average.get("percent")),
        "price_paid_btc": _num(price.get("paid")),
        "price_currency": price.get("currency") or "BTC",
        "length_hours": _num(rv.get("length")),
        "extended_hours": _num(rv.get("extended")),
        "start": rv.get("start"),
        "end": rv.get("end"),
        "start_unix": _num(rv.get("start_unix")),
        "end_unix": _num(rv.get("end_unix")),
        "ended": bool(rv.get("ended")),
        "rig": {
            "id": rig.get("id"),
            "name": rig.get("name"),
            "type": rig.get("type"),
            "region": rig.get("region"),
            "rpi": _num(rig.get("rpi")),
            "online": bool(rig.get("online")),
            "status": rig_status.get("status"),
        },
    }


# ── Braiins: contracts (requires BRAIINS_API_KEY) ───────────────────────────
# The public Braiins Hashpower API is a moving target: the legacy endpoints
# (`/contract`, `/contract/active`) and the current spot-market ones
# (`/spot/bid`, `/spot/bid/current`) both expose the caller's hashrate
# orders. We probe both families, parse any envelope shape that actually
# comes back (items / contracts / records / data / bids), and dedupe by id.
# Crucially: an HTTP 401/403 from a CONFIGURED key is surfaced as an error —
# silently swallowing it made the panel claim "No rentals" when the real
# problem was a rejected/expired key.

# Candidate list endpoints in probe order (legacy first, spot fallback).
_BRAIINS_LIST_ENDPOINTS = (
    "/contract/active", "/contract",
    "/spot/bid/current", "/spot/bid",
)

# Candidate speed endpoints (legacy first, spot fallback).
_BRAIINS_SPEED_ENDPOINTS = (
    "/contract/{}/speed",
    "/spot/bid/speed/{}",
)


def _braiins_list_items(data: Any) -> List[Dict]:
    """Resilient envelope unwrap — Braiins has used items/contracts/records/
    data/bids across API versions. Never raises."""
    if not isinstance(data, dict):
        return []
    for key in ("items", "contracts", "records", "bids"):
        v = data.get(key)
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
    v = data.get("data")
    if isinstance(v, list):
        return [x for x in v if isinstance(x, dict)]
    if isinstance(v, dict):
        for key in ("items", "contracts", "records", "bids"):
            inner = v.get(key)
            if isinstance(inner, list):
                return [x for x in inner if isinstance(x, dict)]
    return []


def _normalize_braiins_contract(c: Dict[str, Any]) -> Dict[str, Any]:
    """Map a Braiins contract/bid dict to the panel's display schema.
    Accepts both the legacy (`contract`) and spot (`bid`) field names."""
    cid = c.get("id") or c.get("bid_id") or c.get("order_id")
    status = c.get("status") or c.get("bid_status") or ""
    # Spot statuses are verbose (SPOT_BID_STATUS_ACTIVE) — collapse to the
    # legacy-style short status the UI already renders (RUNNING/ACTIVE/…).
    short_status = str(status).replace("SPOT_BID_STATUS_", "") if status else ""
    started = c.get("started_at") or c.get("created_at") or c.get("created_ts")
    ended = c.get("ended_at") or c.get("completed_at") or c.get("completed_ts")
    return {
        "id": cid,
        "status": short_status or status,
        "speed_limit_ph": _num(c.get("speed_limit_ph") or c.get("speed_limit") or c.get("limit_ph")),
        "amount_sat": _num(c.get("amount_sat") or c.get("amount")),
        "price_sat": _num(c.get("price_sat") or c.get("price")),
        "started_at": started,
        "ended_at": ended,
    }


def fetch_braiins_contracts() -> Dict[str, Any]:
    """List caller-owned Braiins contracts/bids (active + history).

    Requires BRAIINS_API_KEY (owner token, shown once at registration).
    Probes the legacy /contract endpoints and the current /spot/bid family,
    and NEVER reports an empty account when the truth is a rejected key:
    an explicit error is returned instead.
    """
    key = _braiins_key()
    if not key:
        return {"success": False, "needs_auth": True,
                "error": "BRAIINS_API_KEY not configured", "contracts": []}

    seen: Dict[str, Any] = {}
    statuses: List[str] = []
    reached_ok = False  # any endpoint answered 200 → the account IS reachable
    for ep in _BRAIINS_LIST_ENDPOINTS:
        try:
            r = requests.get(BRAIINS_BASE + ep, headers={"apikey": key}, timeout=15)
            if not r.ok:
                statuses.append(f"{ep}={r.status_code}")
                continue
            reached_ok = True
            data = r.json()
            for c in _braiins_list_items(data):
                norm = _normalize_braiins_contract(c)
                if norm["id"] is None:
                    continue
                # First endpoint wins per id (active list preferred over the
                # all-contracts list, so statuses stay freshest).
                seen.setdefault(str(norm["id"]), norm)
        except Exception as e:
            statuses.append(f"{ep}=exc:{str(e)[:40]}")
            log.warning("[rental_performance] braiins contracts fetch failed (%s): %s", ep, e)

    contracts = list(seen.values())
    if contracts:
        return {"success": True, "needs_auth": False, "contracts": contracts}

    # No data — decide what to tell the panel.
    if any("=401" in s or "=403" in s for s in statuses):
        return {"success": False, "needs_auth": True,
                "error": "Braiins API rejected the key (HTTP 401/403) — check the token in Settings",
                "contracts": []}
    if reached_ok:
        # An endpoint answered 200 with no items: the key is VALID and the
        # account is genuinely empty — report a clean empty result, not a
        # misleading error just because the legacy probes 404'd.
        return {"success": True, "needs_auth": False, "contracts": []}
    if statuses:
        return {"success": False, "needs_auth": False,
                "error": "Braiins API returned no contracts (" + "; ".join(statuses[:3]) + ")",
                "contracts": []}
    return {"success": True, "needs_auth": False, "contracts": []}


def fetch_braiins_contract_speed(contract_id: str) -> Dict[str, Any]:
    """Braiins contract speed time series → [{ts, speed_ph}].

    Probes /contract/{id}/speed then /spot/bid/speed/{id}; parses items /
    points / data envelopes.
    """
    key = _braiins_key()
    if not key:
        return {"success": False, "needs_auth": True,
                "error": "BRAIINS_API_KEY not configured"}
    for ep_tpl in _BRAIINS_SPEED_ENDPOINTS:
        ep = ep_tpl.format(contract_id)
        try:
            r = requests.get(BRAIINS_BASE + ep, headers={"apikey": key}, timeout=15)
            if not r.ok:
                continue
            data = r.json()
            points = _braiins_list_items(data)
            if not points:
                # Some versions wrap the series under a nested key (e.g.
                # data.points) — unwrap once more before giving up.
                nested = data.get("data")
                if isinstance(nested, dict):
                    points = _braiins_list_items(nested)
            if points:
                return {"success": True, "points": [
                    {"ts": _num(p.get("timestamp") or p.get("ts") or p.get("time")),
                     "speed_ph": _num(p.get("speed_ph") or p.get("speed") or p.get("value"))}
                    for p in points
                ]}
        except Exception as e:
            log.warning("[rental_performance] braiins speed fetch failed (%s): %s", ep, e)
    return {"success": False, "error": "Braiins speed endpoint returned no data for " + contract_id}


def fetch_braiins_contract_detail(contract_id: str, contract: Optional[Dict] = None) -> Dict[str, Any]:
    """Full detail for one Braiins contract, NORMALIZED to the MRR detail
    schema so the RENTALS detail panel renders identically for both
    providers (grid rows, performance banner, chart).

    ``contract`` is the already-fetched normalized dict from the list
    payload (the frontend has it) — avoids re-probing the list endpoints
    on every detail click. Falls back to a list re-probe when omitted.

    Returns {"success", "detail": {...mrr-shaped...}, "graph": {"points": [...]}}
    """
    key = _braiins_key()
    if not key:
        return {"success": False, "needs_auth": True}

    if contract is None:
        # Callers without the list payload (e.g. tests) re-probe the list.
        listing = fetch_braiins_contracts()
        contract = next(
            (c for c in listing.get("contracts", []) if str(c.get("id")) == str(contract_id)),
            None,
        )
    speed = fetch_braiins_contract_speed(contract_id)
    points = speed.get("points", [])

    speed_limit_ph = contract.get("speed_limit_ph") if contract else None
    # Average delivered speed across the series (PH/s).
    avg_ph = None
    vals = [p["speed_ph"] for p in points if p.get("speed_ph") is not None]
    if vals:
        avg_ph = sum(vals) / len(vals)

    amount_sat = contract.get("amount_sat") if contract else None
    price_sat = contract.get("price_sat") if contract else None
    started_at = contract.get("started_at") if contract else None
    ended_at = contract.get("ended_at") if contract else None

    # Duration in hours from the series span when timestamps are unix; the
    # contract dates are RFC3339 strings on Braiins, so fall back to the
    # series' first/last ts for the delivered TH·h math.
    ts_vals = [p["ts"] for p in points if p.get("ts") is not None]
    duration_h = None
    if len(ts_vals) >= 2:
        span = max(ts_vals) - min(ts_vals)
        if span > 0:
            duration_h = span / 3600.0

    avg_th = (avg_ph * 1000.0) if avg_ph is not None else None
    delivered_thh = (avg_th * duration_h) if (avg_th is not None and duration_h) else None
    # Cost: amount_sat paid for the delivered TH·h (mirrors the MRR perf banner).
    cost_sats_per_thh = None
    if amount_sat is not None and delivered_thh and delivered_thh > 0:
        cost_sats_per_thh = amount_sat / delivered_thh
    pct = ((avg_ph / speed_limit_ph) * 100.0) if (avg_ph is not None and speed_limit_ph) else None

    detail: Dict[str, Any] = {
        "id": contract_id,
        "owner": "Braiins Hashpower",
        "renter": "—",
        "ended": bool(ended_at),
        "start": started_at,
        "end": ended_at,
        "length": round(duration_h, 2) if duration_h is not None else None,
        "hashrate": {
            "advertised": {"hash": speed_limit_ph, "type": "ph",
                           "nice": f"{speed_limit_ph:g} PH/s" if speed_limit_ph is not None else None},
            "average": {"hash": avg_ph, "type": "ph", "percent": pct,
                        "nice": f"{avg_ph:g} PH/s" if avg_ph is not None else None},
        },
        "price": {"paid": (amount_sat / 1e8) if amount_sat is not None else None,
                  "currency": "BTC", "price_sat": price_sat},
        "rig": {"name": "Braiins contract", "region": "Braiins",
                 "status": contract.get("status") if contract else None},
        # Pre-computed analytics so the frontend perf banner works for Braiins.
        "perf": {
            "percent": pct,
            "avg_th": avg_th,
            "limit_th": (speed_limit_ph * 1000.0) if speed_limit_ph is not None else None,
            "delivered_thh": delivered_thh,
            "cost_sats_per_thh": cost_sats_per_thh,
        },
    }
    return {"success": True, "detail": detail, "graph": {"points": points}}


# ── Analytics: market reference + rig track record ──────────────────────────

# Shared live market fetcher (cheapest SHA-256 rental price). Imported at
# module level so tests can monkeypatch it; hashrate_market never imports
# this module, so there is no cycle.
from services.hashrate_market import fetch_all_offers as _fetch_market_offers  # noqa: E402


def fetch_market_reference() -> Dict[str, Any]:
    """Cheapest live market price for SHA-256 hashpower, in sats/TH/h.

    Uses the shared hashrate-market fetchers (cached, short TTL) so the
    rentals detail can compare the operator's EFFECTIVE cost against renting
    hashpower again today. Returns:
      {"available": True, "price_sats_per_thh": 512.3,
       "price_btc_per_th_day": 0.0001230, "provider": "braiins", "ts": ...}
    or {"available": False} when no live quote is reachable. Never raises.
    """
    try:
        offers = _fetch_market_offers()
        # Positive prices only — a 0/negative quote is a provider glitch and
        # must never feed the sats/TH/h comparison.
        live = [o for o in offers if not getattr(o, "estimated", False)
                and (getattr(o, "price_per_th_day", 0) or 0) > 0]
        if not live:
            live = [o for o in offers if (getattr(o, "price_per_th_day", 0) or 0) > 0]
        if not live:
            return {"available": False}
        best = min(live, key=lambda o: o.price_per_th_day)
        price_btc_per_th_day = float(best.price_per_th_day)
        return {
            "available": True,
            "price_sats_per_thh": round(price_btc_per_th_day * 1e8 / 24.0, 2),
            "price_btc_per_th_day": price_btc_per_th_day,
            "provider": getattr(best, "provider", "market"),
            "ts": int(time.time()),
        }
    except Exception as e:
        log.warning("[rental_performance] market reference failed: %s", e)
        return {"available": False}


def compute_mrr_perf(detail: Dict[str, Any]) -> Dict[str, Any]:
    """Compute the perf analytics block from a RAW MRR detail payload.

    Mirrors the Braiins perf schema (percent / avg_th / limit_th /
    delivered_thh / cost_sats_per_thh) so the frontend perf banner renders
    identically for BOTH providers.
    """
    hr = detail.get("hashrate") or {}
    advertised = hr.get("advertised") or {}
    average = hr.get("average") or {}
    adv_th = _hash_to_th(advertised.get("hash"), advertised.get("type"))
    avg_th = _hash_to_th(average.get("hash"), average.get("type"))
    pct = _num(average.get("percent"))
    if pct is None and avg_th is not None and adv_th:
        pct = (avg_th / adv_th * 100.0) if adv_th else None
    price = detail.get("price") or {}
    paid_sats = None
    if price.get("paid") is not None:
        paid_sats = _num(price["paid"]) * 1e8
    length_h = _num(detail.get("length"))
    delivered_thh = (avg_th * length_h) if (avg_th is not None and length_h) else None
    cost_sats_per_thh = None
    if paid_sats is not None and delivered_thh:
        cost_sats_per_thh = paid_sats / delivered_thh
    return {
        "percent": pct,
        "avg_th": avg_th,
        "limit_th": adv_th,
        "delivered_thh": delivered_thh,
        "cost_sats_per_thh": cost_sats_per_thh,
    }


def fetch_rig_performance_history(
    rig_id: Any = None,
    rig_name: str = "",
    exclude_rental_id: Any = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Past MRR rentals of the SAME rig → track record for the detail panel.

    Matches by rig.id (authoritative) or rig.name (fallback), excludes the
    rental currently being viewed, newest first. Each entry:
      {id, start, percent, avg_th, advertised_th, cost_sats_per_thh,
       length_hours}
    Enables the "histórico de % por rig" view: how THIS rig delivered on
    previous rentals before deciding where to rent again.
    """
    if not (rig_id or rig_name):
        return []
    listing = fetch_mrr_rentals(rtype="renter", history=True, limit=limit)
    if not listing.get("success"):
        return []
    wanted_id = str(rig_id) if rig_id is not None else None
    wanted_name = str(rig_name or "").strip().lower()
    out: List[Dict[str, Any]] = []
    for r in listing.get("rentals", []):
        if exclude_rental_id is not None and str(r.get("id")) == str(exclude_rental_id):
            continue
        rig = r.get("rig") or {}
        rid = str(rig.get("id") or "")
        rname = str(rig.get("name") or "").strip().lower()
        if wanted_id and rid and rid == wanted_id:
            pass
        elif wanted_name and rname and rname == wanted_name:
            pass
        else:
            continue
        avg_th = r.get("hashrate_average_th")
        adv_th = r.get("hashrate_advertised_th")
        pct = r.get("hashrate_percent")
        if pct is None and avg_th is not None and adv_th:
            pct = (avg_th / adv_th * 100.0) if adv_th else None
        paid_sats = None
        if r.get("price_paid_btc") is not None:
            paid_sats = r["price_paid_btc"] * 1e8
        length_h = r.get("length_hours")
        delivered_thh = (avg_th * length_h) if (avg_th is not None and length_h) else None
        cost = (paid_sats / delivered_thh) if (paid_sats is not None and delivered_thh) else None
        out.append({
            "id": r.get("id"),
            "start": r.get("start"),
            "percent": round(pct, 2) if pct is not None else None,
            "avg_th": avg_th,
            "advertised_th": adv_th,
            "cost_sats_per_thh": round(cost, 2) if cost is not None else None,
            "length_hours": length_h,
        })
    out.sort(key=lambda x: str(x.get("start") or ""), reverse=True)
    return out


def _num(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None
