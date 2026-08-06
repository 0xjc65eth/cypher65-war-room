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

def fetch_braiins_contracts() -> Dict[str, Any]:
    """List caller-owned Braiins contracts (pending/running/paused + all).

    Requires BRAIINS_API_KEY (owner token, shown once at registration).
    Returns an explicit note when the key is missing so the panel never
    pretends there are zero contracts.
    """
    key = _braiins_key()
    if not key:
        return {"success": False, "needs_auth": True,
                "error": "BRAIINS_API_KEY not configured", "contracts": []}
    contracts: List[Dict[str, Any]] = []
    for ep in ("/contract/active", "/contract"):
        try:
            r = requests.get(BRAIINS_BASE + ep, headers={"apikey": key}, timeout=15)
            if not r.ok:
                continue
            data = r.json()
            items = data.get("items") or data.get("contracts") or []
            for c in items:
                if isinstance(c, dict):
                    contracts.append({
                        "id": c.get("id"),
                        "status": c.get("status"),
                        "speed_limit_ph": _num(c.get("speed_limit_ph") or c.get("speed_limit")),
                        "amount_sat": _num(c.get("amount_sat")),
                        "price_sat": _num(c.get("price_sat")),
                        "started_at": c.get("started_at") or c.get("created_at"),
                        "ended_at": c.get("ended_at"),
                    })
        except Exception as e:
            log.warning("[rental_performance] braiins contracts fetch failed (%s): %s", ep, e)
    return {"success": True, "needs_auth": False, "contracts": contracts}


def fetch_braiins_contract_speed(contract_id: str) -> Dict[str, Any]:
    """Braiins contract speed time series → [{ts, speed_ph}]."""
    key = _braiins_key()
    if not key:
        return {"success": False, "needs_auth": True,
                "error": "BRAIINS_API_KEY not configured"}
    try:
        r = requests.get(
            f"{BRAIINS_BASE}/contract/{contract_id}/speed",
            headers={"apikey": key},
            timeout=15,
        )
        if not r.ok:
            return {"success": False, "error": f"HTTP {r.status_code}"}
        data = r.json()
        items = data.get("items") or data.get("points") or []
        return {"success": True, "points": [
            {"ts": _num(p.get("timestamp") or p.get("ts")), "speed_ph": _num(p.get("speed_ph") or p.get("speed"))}
            for p in items if isinstance(p, dict)
        ]}
    except Exception as e:
        return {"success": False, "error": str(e)[:120]}


def _num(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None
