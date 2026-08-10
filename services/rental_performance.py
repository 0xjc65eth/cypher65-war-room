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

import json
import os
import time
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import requests

from agents.solo_mining_advisor.tools import _mrr_signed_headers, mrr_credentials, braiins_credentials
from services.db import get_db
from services.settings import is_default_tenant, load_settings

log = logging.getLogger("cypher65")

MRR_BASE = "https://www.miningrigrentals.com/api/v2"
BRAIINS_BASE = "https://hashpower.braiins.com/v1"
PH_TO_TH = 1000.0

# ── Rig Trust Score + bad-rig exclusion (CFO: decide where to rent again) ──
# Every rig accumulates a track record of delivery % (avg vs advertised) over
# past rentals. compute_rig_trust_score() turns that history into a 0-100
# score + grade A-F so the operator can tell at a glance which rigs are
# reliable and which under-deliver. Rigs can ALSO be blacklisted manually
# (persistent per tenant) — the panel then hides/marks them automatically.

# Grade bands on the ROBUST (median-based) score.
RIG_GRADE_BANDS = [  # (min_score, grade)
    (95, "A"),
    (90, "B"),
    (82, "C"),
    (70, "D"),
    (0, "F"),
]

# Human labels per grade (drives the UI badge + auto-hide decision).
RIG_GRADE_LABEL = {
    "A": "RELIABLE",
    "B": "RELIABLE",
    "C": "CAUTION",
    "D": "RISKY",
    "F": "AVOID",
}

# Settings key holding the per-tenant rig blacklist (JSON list of rig ids).
# Internal key (leading '_') bypasses the DEFAULT_SETTINGS whitelist.
RIG_BLACKLIST_KEY = "_rental_rig_blacklist"
# AUTO blacklist (separate key so a manual restore is never re-flagged by
# the same under-delivery streak until NEW bad samples accumulate). The TS
# map records WHEN each rig was last auto-excluded and SURVIVES a restore —
# that's what lets the re-exclusion gate compare against new samples.
RIG_AUTO_BLACKLIST_KEY = "_rental_auto_blacklist"
RIG_AUTO_TS_KEY = "_rental_auto_blacklist_ts"


def _to_float(v):
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def compute_rig_trust_score(history: List[Dict]) -> Dict[str, Any]:
    """Score 0-100 + grade A-F for a rig from its delivery track record.

    ``history`` is the ``fetch_rig_performance_history`` output: past rentals
    of the SAME rig, each with a ``percent`` (avg vs advertised hashrate).

    Methodology (CFO read — robust statistics, not raw means):
      - base = MEDIAN of delivery % (a single terrible rental must not tank
        a rig that otherwise delivers);
      - penalty for inconsistency (mean absolute deviation) — a rig that
        swings 60%→110% is riskier than one steady at 96%;
      - penalty for a terrible worst delivery (<85%);
      - sample-size confidence cap (1-2 rentals can't earn an A/B).

    Returns {"score", "grade", "label", "median_pct", "worst_pct",
             "mad_pct", "samples"} — or NO DATA (all null, samples 0) when
    the rig has no measured deliveries yet.
    """
    pcts = []
    for h in history or []:
        p = _to_float(h.get("percent"))
        if p is not None:
            pcts.append(p)
    if not pcts:
        return {"score": None, "grade": None, "label": "NO DATA",
                "median_pct": None, "worst_pct": None, "mad_pct": None,
                "samples": 0}

    n = len(pcts)
    s = sorted(pcts)
    median = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0
    mad = sum(abs(p - median) for p in pcts) / n
    worst = min(pcts)

    score = median - mad * 0.5 - max(0.0, 85.0 - worst) * 0.4
    # Confidence cap: <3 samples → at most C band (89); <5 → at most B (94).
    if n < 3:
        score = min(score, 89.0)
    elif n < 5:
        score = min(score, 94.0)
    score = max(0.0, min(100.0, score))
    grade = next(g for low, g in RIG_GRADE_BANDS if score >= low)
    return {
        "score": round(score, 1),
        "grade": grade,
        "label": RIG_GRADE_LABEL.get(grade, grade),
        "median_pct": round(median, 1),
        "worst_pct": round(worst, 1),
        "mad_pct": round(mad, 1),
        "samples": n,
    }


# ── Per-tenant rig blacklist (persistent) ───────────────────────────────────
# Stored as a JSON array of rig ids under an internal settings key, scoped to
# the tenant: default → global `settings` table, named tenant → its own
# `tenant_settings` rows. Never inherits/leaks across tenants.

def _save_rig_blacklist(items: List[str], tenant_id: str = "") -> bool:
    """Persist the MANUAL rig blacklist (JSON list) — tenant-aware."""
    return _save_rig_ids(RIG_BLACKLIST_KEY, items, tenant_id=tenant_id)


def get_rig_blacklist(tenant_id: str = "") -> List[str]:
    """Persisted rig ids the tenant blacklisted (never rent again)."""
    return _load_rig_ids(RIG_BLACKLIST_KEY, tenant_id=tenant_id)


def add_rig_to_blacklist(rig_id, tenant_id: str = "") -> bool:
    """Blacklist a rig id (persistent per tenant). Returns True if added."""
    if rig_id is None or str(rig_id) == "":
        return False
    rid = str(rig_id)
    items = get_rig_blacklist(tenant_id=tenant_id)
    if rid not in items:
        items.append(rid)
        return _save_rig_blacklist(items, tenant_id=tenant_id)
    return True


def remove_rig_from_blacklist(rig_id, tenant_id: str = "") -> bool:
    """Remove a rig from BOTH blacklists (manual restore). Returns True if
    removed — a restored rig is never re-flagged by the same streak."""
    rid = str(rig_id)
    items = [x for x in get_rig_blacklist(tenant_id=tenant_id) if x != rid]
    ok = _save_rig_blacklist(items, tenant_id=tenant_id)
    auto = [x for x in get_auto_blacklist(tenant_id=tenant_id) if x != rid]
    return _save_rig_ids(RIG_AUTO_BLACKLIST_KEY, auto, tenant_id=tenant_id) and ok


def is_rig_blacklisted(rig_id, tenant_id: str = "") -> bool:
    """Quick check used by the list/detail routes (no full list re-parse).
    True when the rig is on EITHER the manual or the auto blacklist."""
    if rig_id is None:
        return False
    rid = str(rig_id)
    return rid in get_rig_blacklist(tenant_id=tenant_id) or \
        rid in get_auto_blacklist(tenant_id=tenant_id)


def _ensure_rig_settings_tables() -> None:
    """Self-heal the settings tables (fresh DBs / tests): the real app always
    creates them via init_db, but a missing table must never silently drop a
    blacklist write."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT, updated_ts INTEGER)")
        c.execute("CREATE TABLE IF NOT EXISTS tenant_settings (tenant_id TEXT, key TEXT, value TEXT, updated_ts INTEGER, PRIMARY KEY(tenant_id, key))")
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("[rental_performance] settings table ensure failed: %s", e)


def _save_rig_ids(key: str, items: List[str], tenant_id: str = "") -> bool:
    """Persist a JSON list of rig ids under an internal settings key (tenant-ware)."""
    _ensure_rig_settings_tables()
    raw = json.dumps([str(x) for x in items])
    ts = int(time.time())
    try:
        conn = get_db()
        c = conn.cursor()
        if is_default_tenant(tenant_id):
            c.execute(
                "INSERT INTO settings(key,value,updated_ts) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_ts=excluded.updated_ts",
                (key, raw, ts),
            )
        else:
            c.execute(
                "INSERT INTO tenant_settings(tenant_id,key,value,updated_ts) VALUES(?,?,?,?) "
                "ON CONFLICT(tenant_id,key) DO UPDATE SET value=excluded.value, updated_ts=excluded.updated_ts",
                (tenant_id, key, raw, ts),
            )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        log.warning("[rental_performance] rig list save failed (%s): %s", key, e)
        return False


def _load_rig_ids(key: str, tenant_id: str = "") -> List[str]:
    """Load a JSON list of rig ids from an internal settings key (tenant-aware)."""
    _ensure_rig_settings_tables()
    try:
        conn = get_db()
        c = conn.cursor()
        if is_default_tenant(tenant_id):
            c.execute("SELECT value FROM settings WHERE key=?", (key,))
        else:
            c.execute("SELECT value FROM tenant_settings WHERE tenant_id=? AND key=?",
                      (tenant_id, key))
        row = c.fetchone()
        conn.close()
        if row and row["value"]:
            parsed = json.loads(row["value"])
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        return []
    except Exception as e:
        log.warning("[rental_performance] rig list load failed (%s): %s", key, e)
        return []


def get_auto_blacklist(tenant_id: str = "") -> List[str]:
    """Plain rig ids auto-excluded for under-delivery — entries are stored as
    'rig_id:ts' (ts = when the exclusion happened) so a restore can be
    respected: re-exclusion only fires on NEW bad data after that moment."""
    raw = _load_rig_ids(RIG_AUTO_BLACKLIST_KEY, tenant_id=tenant_id)
    return [str(x).split(":")[0] for x in raw if str(x)]


def _history_newest_ts(history: List[Dict]) -> Optional[float]:
    """Newest sample timestamp from a rig-history list (starts are strings:
    MRR 'YYYY-MM-DD HH:MM:SS UTC', Braiins RFC3339, or unix). None when
    nothing parses — callers then fall back to the permissive path."""
    import datetime as _dt
    newest = None
    for h in history or []:
        ts = _parse_start_ts(h.get("start"))
        if ts is None:
            continue
        if newest is None or ts > newest:
            newest = ts
    return newest


def _auto_blacklist_ts(rig_id, tenant_id: str = "") -> float:
    """When the rig was last auto-excluded (0.0 = never). Read from a SEPARATE
    map that SURVIVES a restore — clearing the auto list must not erase the
    reference point, or the same streak would re-exclude immediately."""
    rid = str(rig_id)
    for x in _load_rig_ids(RIG_AUTO_TS_KEY, tenant_id=tenant_id):
        parts = str(x).split(":")
        if len(parts) == 2 and parts[0] == rid:
            try:
                return float(parts[1])
            except ValueError:
                return 0.0
    return 0.0


def is_rig_auto_blacklisted(rig_id, tenant_id: str = "") -> bool:
    if rig_id is None:
        return False
    return str(rig_id) in get_auto_blacklist(tenant_id=tenant_id)


def add_rig_to_auto_blacklist(rig_id, tenant_id: str = "") -> bool:
    """Auto-exclude a rig AND record when it happened in the separate ts map
    (the restore reference). Never raises."""
    if rig_id is None or str(rig_id) == "":
        return False
    rid = str(rig_id)
    now = int(time.time())
    items = [x for x in get_auto_blacklist(tenant_id=tenant_id) if x != rid]
    items.append(rid)
    ok_ids = _save_rig_ids(RIG_AUTO_BLACKLIST_KEY, items, tenant_id=tenant_id)
    ts_items = [x for x in _load_rig_ids(RIG_AUTO_TS_KEY, tenant_id=tenant_id)
                if str(x).split(":")[0] != rid]
    ts_items.append(f"{rid}:{now}")
    ok_ts = _save_rig_ids(RIG_AUTO_TS_KEY, ts_items, tenant_id=tenant_id)
    return ok_ids and ok_ts


# ── Credentials: shared resolver in agents/solo_mining_advisor/tools.py ──
# Tenant-aware: named tenants resolve ONLY their own credentials (never env /
# global settings) so 1000+ users each see their own MRR/Braiins data.

def _mrr_creds(tenant_id: str = "") -> dict:
    return mrr_credentials(tenant_id=tenant_id)


def _braiins_key(tenant_id: str = "") -> str:
    """Braiins API key for a tenant (default = operator env→Settings).
    Stripped — the `apikey` header is verbatim and a pasted token with a
    trailing newline/space silently 401s."""
    return (braiins_credentials(tenant_id=tenant_id).get("api_key") or "").strip()


# ── MRR: rentals ─────────────────────────────────────────────────────────────

def fetch_mrr_rentals(
    rtype: str = "renter",
    history: bool = False,
    limit: int = 25,
    tenant_id: str = "",
) -> Dict[str, Any]:
    """List MRR rentals for a tenant (default: renter, active only).

    Returns a normalized list plus auth status so the panel can render an
    honest empty/error state:
      {"success": True, "needs_auth": False, "rentals": [...], "total": n}
    """
    creds = _mrr_creds(tenant_id=tenant_id)
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


def fetch_mrr_rental_detail(rental_id: str, tenant_id: str = "") -> Dict[str, Any]:
    """Full detail + graph + log for one MRR rental."""
    creds = _mrr_creds(tenant_id=tenant_id)
    if not (creds["api_key"] and creds["api_secret"]):
        return {"success": False, "needs_auth": True}

    out: Dict[str, Any] = {"success": False}

    # Fetch detail + graph + log CONCURRENTLY (independent GETs). Sequential
    # calls made a detail click take up to ~45s worst case (three 15s
    # timeouts). Each call is a pure function of (endpoint, creds) — the MRR
    # signing is thread-safe (no shared mutable state).
    def _fetch_one(sub: str, key: str) -> None:
        endpoint = f"/rental/{rental_id}{sub}"
        try:
            r = requests.get(
                MRR_BASE + endpoint,
                headers=_mrr_signed_headers(creds["api_key"], creds["api_secret"], endpoint),
                timeout=15,
            )
            if not r.ok:
                out[key] = {"error": f"HTTP {r.status_code}"}
                return
            data = r.json()
            out[key] = data.get("data") if data.get("success") else {"error": data.get("data")}
        except Exception as e:
            out[key] = {"error": str(e)[:120]}

    with ThreadPoolExecutor(max_workers=3) as ex:
        list(ex.map(lambda kv: _fetch_one(*kv),
                    (("", "detail"), ("/graph", "graph"), ("/log", "log"))))

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


def fetch_braiins_contracts(tenant_id: str = "") -> Dict[str, Any]:
    """List caller-owned Braiins contracts/bids (active + history) for a tenant.

    Requires BRAIINS_API_KEY (owner token, shown once at registration) — for
    a named tenant, ITS OWN key (isolated per tenant_settings). Probes the
    legacy /contract endpoints and the current /spot/bid family, and NEVER
    reports an empty account when the truth is a rejected key: an explicit
    error is returned instead.
    """
    key = _braiins_key(tenant_id=tenant_id)
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


def fetch_braiins_contract_speed(contract_id: str, tenant_id: str = "") -> Dict[str, Any]:
    """Braiins contract speed time series → [{ts, speed_ph}].

    Probes /contract/{id}/speed then /spot/bid/speed/{id}; parses items /
    points / data envelopes.
    """
    key = _braiins_key(tenant_id=tenant_id)
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


def fetch_braiins_contract_detail(contract_id: str, contract: Optional[Dict] = None,
                                  tenant_id: str = "") -> Dict[str, Any]:
    """Full detail for one Braiins contract, NORMALIZED to the MRR detail
    schema so the RENTALS detail panel renders identically for both
    providers (grid rows, performance banner, chart).

    ``contract`` is the already-fetched normalized dict from the list
    payload (the frontend has it) — avoids re-probing the list endpoints
    on every detail click. Falls back to a list re-probe when omitted.

    Returns {"success", "detail": {...mrr-shaped...}, "graph": {"points": [...]}}
    """
    key = _braiins_key(tenant_id=tenant_id)
    if not key:
        return {"success": False, "needs_auth": True}

    if contract is None:
        # Callers without the list payload (e.g. tests) re-probe the list.
        listing = fetch_braiins_contracts(tenant_id=tenant_id)
        contract = next(
            (c for c in listing.get("contracts", []) if str(c.get("id")) == str(contract_id)),
            None,
        )
    speed = fetch_braiins_contract_speed(contract_id, tenant_id=tenant_id)
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
    # Braiins contracts carry no rig identity → no delivery track record.
    # The speed series itself is the signal: CV of the PH/s values turns
    # "how flat did this contract run?" into a stability grade.
    stability = compute_speed_stability(points)
    # Economic P/L — expected gross yield (network hashrate OBSERVED at the
    # contract's time — snapshot lookup, current fallback) vs amount paid.
    pl = attach_pl(
        detail.get("perf"), amount_sat,
        network_hashrate_hs=_resolve_network_hashrate_for_rental(
            detail.get("start"), detail.get("end")))
    if amount_sat is None:
        pl = {"available": False}
    return {"success": True, "detail": detail, "graph": {"points": points},
            "stability": stability, "pl": pl}


# ── Braiins spot EXECUTION: quote, balance, place bid (real money!) ────────
# The jump from analytics to operation: the operator can buy hashrate on the
# Braiins spot market directly from the panel. Units follow the live API:
#   - spot/settings reports the account's price unit (default sats/PH/day)
#   - POST /spot/bid body: dest_upstream.url (stratum), speed_limit_ph (PH/s),
#     amount_sat (budget), price_sat (per the reported unit), cl_order_id
#     (idempotency), memo
# Server-side SANITY CLAMPS guard real money: a unit bug must never turn a
# 1 TH bid into a 1000 PH order. Every bid is explicit (confirm dialog) and
# idempotent (client order id regenerated per modal session).

# Plausible bounds for a SHA-256 spot bid (fail-closed on anything outside):
BID_MIN_SPEED_PH = 0.001        # 1 TH/s
BID_MAX_SPEED_PH = 1000.0       # 1 EH/s
BID_MIN_AMOUNT_SAT = 1000
BID_MAX_AMOUNT_SAT = 100_000_000  # 1 BTC
# price_sat per PH/day band: 1e4..1e9 → ~0.4..~41,600 sats/TH·h (real market
# ~300-1500 sats/TH·h; a unit conversion bug lands far outside this band).
BID_MIN_PRICE_SAT_PH_DAY = 10_000
BID_MAX_PRICE_SAT_PH_DAY = 1_000_000_000


def braiins_price_unit(tenant_id: str = "") -> str:
    """The account's spot price unit (default 'sats/PH/day'). Reads
    spot/settings with the tenant's key; falls back to the default unit."""
    key = _braiins_key(tenant_id=tenant_id)
    if not key:
        return "sats/PH/day"
    try:
        r = requests.get(f"{BRAIINS_BASE}/spot/settings", headers={"apikey": key}, timeout=8)
        if r.ok:
            return str((r.json().get("price_unit") or "sats/PH/day"))
    except Exception as e:
        log.warning("[rental_performance] braiins price unit failed: %s", e)
    return "sats/PH/day"


def fetch_braiins_balance(tenant_id: str = "") -> Dict[str, Any]:
    """BTC balances for all subaccounts (total/available/blocked, in sats).
    Requires the tenant's Braiins key; 401/403 is surfaced, never swallowed."""
    key = _braiins_key(tenant_id=tenant_id)
    if not key:
        return {"available": False, "error": "BRAIINS_API_KEY not configured",
                "needs_auth": True}
    try:
        r = requests.get(f"{BRAIINS_BASE}/account/balance",
                         headers={"apikey": key}, timeout=15)
        if not r.ok:
            return {"available": False,
                    "error": f"HTTP {r.status_code}",
                    "needs_auth": r.status_code in (401, 403)}
        data = r.json()
        # Envelope: either {items: [{balance_type, amount, ...}]} or a dict
        # with total/available/blocked amounts (sats). Tolerate an items list
        # nested under data.data (same resilience as _braiins_list_items).
        if isinstance(data, dict) and data.get("data") and isinstance(data["data"], dict) \
                and "items" in data["data"] and "items" not in data:
            data = data["data"]
        total = available = blocked = None
        items = data.get("items") if isinstance(data, dict) else None
        if isinstance(items, list):
            for it in items:
                typ = str(it.get("balance_type") or "")
                amt = _num(it.get("amount"))
                if amt is None:
                    continue
                if "total" in typ.lower():
                    total = amt
                elif "blocked" in typ.lower():
                    blocked = amt
                elif "available" in typ.lower():
                    available = amt
        if isinstance(data, dict):
            if total is None and data.get("total") is not None:
                total = _num(data["total"])
            if available is None and data.get("available") is not None:
                available = _num(data["available"])
            if blocked is None and data.get("blocked") is not None:
                blocked = _num(data["blocked"])
        if available is None and total is not None:
            available = total - (blocked or 0)
        return {"available": True, "total_sat": total, "available_sat": available,
                "blocked_sat": blocked}
    except Exception as e:
        log.warning("[rental_performance] braiins balance failed: %s", e)
        return {"available": False, "error": str(e)[:120]}


def braiins_quote(tenant_id: str = "") -> Dict[str, Any]:
    """Cheapest live Braiins ASK, in the units the UI uses (sats/TH·h) plus
    the raw PH/day price for the bid body + available budget. Powers the
    'comprar agora' modal prefill."""
    from agents.solo_mining_advisor.tools import get_braiins_orderbook
    ob = get_braiins_orderbook()
    if ob.get("error"):
        return {"available": False, "error": ob["error"]}
    btc_per_th_day = ob.get("price_btc_per_th_day")
    if not btc_per_th_day:
        return {"available": False, "error": "no braiins price"}
    bal = fetch_braiins_balance(tenant_id=tenant_id)
    return {
        "available": True,
        "price_sats_per_thh": round(btc_per_th_day * 1e8 / 24.0, 2),
        "price_sat_per_ph_day": round(btc_per_th_day * 1e8 * PH_TO_TH, 0),
        "best_hr_ph": ob.get("best_order_hr_ph"),
        "price_unit": ob.get("price_raw_unit") or "sats/PH/day",
        "balance": bal,
    }


def create_braiins_bid(
    speed_limit_ph: float,
    amount_sat: int,
    price_sat: int,
    upstream_url: str,
    upstream_identity: str = "",
    memo: str = "",
    cl_order_id: str = "",
    tenant_id: str = "",
) -> Dict[str, Any]:
    """Place a spot bid on Braiins (REAL MONEY). Fail-closed on every axis.

    Returns {"success": True, "bid": {...}} or {"success": False, "error": ...,
    "needs_auth": bool}. Sanity clamps run BEFORE the POST — a unit bug must
    never reach the wire.
    """
    key = _braiins_key(tenant_id=tenant_id)
    if not key:
        return {"success": False, "needs_auth": True,
                "error": "BRAIINS_API_KEY not configured"}
    try:
        speed_limit_ph = float(speed_limit_ph)
        amount_sat = int(amount_sat)
        price_sat = int(price_sat)
    except (TypeError, ValueError):
        return {"success": False, "error": "invalid numeric inputs"}
    if not (BID_MIN_SPEED_PH <= speed_limit_ph <= BID_MAX_SPEED_PH):
        return {"success": False, "error": f"speed_limit must be {BID_MIN_SPEED_PH}-{BID_MAX_SPEED_PH} PH/s"}
    if not (BID_MIN_AMOUNT_SAT <= amount_sat <= BID_MAX_AMOUNT_SAT):
        return {"success": False, "error": f"amount must be {BID_MIN_AMOUNT_SAT}-{BID_MAX_AMOUNT_SAT} sats"}
    if not (BID_MIN_PRICE_SAT_PH_DAY <= price_sat <= BID_MAX_PRICE_SAT_PH_DAY):
        return {"success": False, "error": f"price_sat out of plausible band ({BID_MIN_PRICE_SAT_PH_DAY}-{BID_MAX_PRICE_SAT_PH_DAY} sats/PH/day)"}
    url = (upstream_url or "").strip()
    if not (url.startswith("stratum+tcp://") or url.startswith("stratum+ssl://")
            or url.startswith("stratum://")):
        return {"success": False, "error": "upstream_url must be a stratum URL (stratum+tcp://host:port)"}

    # MONEY-SAFETY: the API expects price_sat in the ACCOUNT's configured unit
    # (spot/settings, default sats/PH/day). The UI quote is always PH/day —
    # convert to the account's unit before the wire, or FAIL CLOSED when the
    # unit is unknown (never guess with real money). A unit mismatch would
    # otherwise place an order 1000× too expensive without tripping the
    # sanity band above.
    unit = (braiins_price_unit(tenant_id=tenant_id) or "sats/PH/day").strip().lower()
    price_for_api = price_sat
    if "th/day" in unit:
        price_for_api = round(price_sat / 1000.0)  # PH/day → TH/day
    elif "ph/day" not in unit and unit not in ("", "sats/ph/day"):
        return {"success": False,
                "error": f"unsupported account price unit '{unit}' — not placing order"}

    body: Dict[str, Any] = {
        "dest_upstream": {"url": url},
        "speed_limit_ph": speed_limit_ph,
        "amount_sat": amount_sat,
        "price_sat": price_for_api,
    }
    if upstream_identity and str(upstream_identity).strip():
        body["dest_upstream"]["identity"] = str(upstream_identity).strip()[:120]
    if memo and str(memo).strip():
        body["memo"] = str(memo).strip()[:200]
    if cl_order_id and str(cl_order_id).strip():
        body["cl_order_id"] = str(cl_order_id).strip()[:64]

    try:
        r = requests.post(f"{BRAIINS_BASE}/spot/bid", json=body,
                          headers={"apikey": key}, timeout=20)
        if not r.ok:
            return {"success": False,
                    "error": f"HTTP {r.status_code}: {r.text[:160]}",
                    "needs_auth": r.status_code in (401, 403)}
        data = r.json()
        # Envelope tolerance: {bid_id, order_id, id} at top level or nested.
        bid_id = (data.get("bid_id") if isinstance(data, dict) else None) or \
            (data.get("id") if isinstance(data, dict) else None) or \
            (data.get("order_id") if isinstance(data, dict) else None)
        return {"success": True, "bid": {"id": bid_id, "raw": data}}
    except Exception as e:
        log.warning("[rental_performance] braiins bid post failed: %s", e)
        return {"success": False, "error": str(e)[:160]}


# ── Analytics: market reference + rig track record ──────────────────────────

# Shared live market fetcher (cheapest SHA-256 rental price). Imported at
# module level so tests can monkeypatch it; hashrate_market never imports
# this module, so there is no cycle.
from services.hashrate_market import (  # noqa: E402
    fetch_all_offers as _fetch_market_offers,
    MIN_PLAUSIBLE_PRICE_BTC_TH_DAY as _MIN_PLAUSIBLE_PRICE,
)


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
        # Plausible prices only — a sub-floor quote (estimation glitch ≈ 0
        # sats/TH·h) must never feed the sats/TH/h comparison, or 'vs market'
        # reads as 'everything is 100% overpriced'.
        live = [o for o in offers if not getattr(o, "estimated", False)
                and (getattr(o, "price_per_th_day", 0) or 0) >= _MIN_PLAUSIBLE_PRICE]
        if not live:
            live = [o for o in offers if (getattr(o, "price_per_th_day", 0) or 0) >= _MIN_PLAUSIBLE_PRICE]
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


# ── Economic analytics: expected yield + P/L per rental ─────────────────────
# The cost figure (sats/TH·h) answers "what did I pay?" — but the question a
# renter actually asks is "did I make money?". Expected gross yield derives
# from Bitcoin consensus (block reward ÷ network hashrate):
#
#   share_of_network_per_th = 1e12 / net_Hs
#   btc_per_th_day = share × blocks_per_day × block_reward
#   sats_per_th_h  = btc_per_th_day × 1e8 / 24
#
# Mirrors the app.py profitability block constants (144 blocks/day, 3.125 BTC
# reward at the current halving epoch). Pool fees are NOT subtracted — the
# figure is labeled GROSS so it never overstates a verdict.

BTC_BLOCKS_PER_DAY = 144.0
DEFAULT_BLOCK_REWARD_BTC = 3.125


def _network_hashrate_hs() -> float:
    """Current network hashrate in H/s from the shared polling state.
    0.0 on a cold box (no poll yet) — callers treat it as 'unknown'."""
    try:
        from services.state import latest_snapshot
        v = (latest_snapshot.get("network") or {}).get("hashrate")
        return float(v) if v else 0.0
    except Exception:
        return 0.0


def compute_expected_yield_sats_per_thh(
    network_hashrate_hs: Optional[float] = None,
    block_reward_btc: float = DEFAULT_BLOCK_REWARD_BTC,
) -> Optional[float]:
    """Gross expected yield of 1 TH/s over 1 hour, in sats (before pool fee).

    ``network_hashrate_hs`` defaults to the shared polling state; returns
    None when the network hashrate is unknown so the UI shows '—' instead
    of a fabricated number.
    """
    hs = network_hashrate_hs
    if hs is None:
        hs = _network_hashrate_hs()
    try:
        hs = float(hs)
    except (TypeError, ValueError):
        return None
    if hs <= 0:
        return None
    share = 1e12 / hs
    sats_per_th_day = share * BTC_BLOCKS_PER_DAY * float(block_reward_btc) * 1e8
    return sats_per_th_day / 24.0


def compute_rental_pl(
    delivered_thh: Optional[float],
    paid_sats: Optional[float],
    network_hashrate_hs: Optional[float] = None,
    block_reward_btc: float = DEFAULT_BLOCK_REWARD_BTC,
) -> Dict[str, Any]:
    """Economic P/L of one rental: expected gross yield vs what was paid.

    Returns:
      {expected_yield_sats_per_thh, break_even_sats_per_thh, yield_sats,
       paid_sats, pl_sats, pl_pct} — pl fields are None when inputs are
       missing (honest '—' instead of fake money).
    """
    y = compute_expected_yield_sats_per_thh(network_hashrate_hs, block_reward_btc)
    out: Dict[str, Any] = {
        "expected_yield_sats_per_thh": y,
        "break_even_sats_per_thh": y,
        "yield_sats": None,
        "paid_sats": paid_sats,
        "pl_sats": None,
        "pl_pct": None,
    }
    if y is None or delivered_thh is None or paid_sats is None:
        return out
    yield_sats = y * delivered_thh
    pl_sats = yield_sats - paid_sats
    out.update({
        "yield_sats": round(yield_sats, 2),
        "pl_sats": round(pl_sats, 2),
        "pl_pct": round(pl_sats / paid_sats * 100.0, 1) if paid_sats else None,
    })
    return out


def attach_pl(perf: Optional[Dict], paid_sats: Optional[float],
              network_hashrate_hs: Optional[float] = None) -> Dict[str, Any]:
    """Augment a perf block with P/L analytics (used by BOTH detail routes)."""
    if not perf or not perf.get("delivered_thh"):
        return {"available": False}
    pl = compute_rental_pl(perf.get("delivered_thh"), paid_sats,
                           network_hashrate_hs=network_hashrate_hs)
    pl["available"] = pl.get("yield_sats") is not None
    return pl


def compute_speed_stability(points: List[Dict]) -> Dict[str, Any]:
    """Braiins contract stability from the speed series (CV of PH/s values).

    Contracts expose no rig identity → no delivery track record. The speed
    series itself is the signal: a contract that holds flat speed is
    predictable; one swinging 80-150% of limit is not. Returns:
      {cv_pct, mean_ph, std_ph, min_ph, max_ph, grade, label}
    or NO DATA (all None) when fewer than 2 points.
    """
    vals = [p.get("speed_ph") for p in (points or [])
            if p.get("speed_ph") is not None]
    if len(vals) < 2:
        return {"cv_pct": None, "mean_ph": None, "std_ph": None,
                "min_ph": None, "max_ph": None, "grade": None,
                "label": "NO DATA"}
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    std = var ** 0.5
    cv = (std / mean * 100.0) if mean else None
    if cv is None:
        grade, label = None, "NO DATA"
    elif cv < 5:
        grade, label = "STABLE", "STABLE"
    elif cv <= 15:
        grade, label = "MODERATE", "MODERATE"
    else:
        grade, label = "VARIABLE", "VARIABLE"
    return {"cv_pct": round(cv, 1) if cv is not None else None,
            "mean_ph": round(mean, 2), "std_ph": round(std, 2),
            "min_ph": min(vals), "max_ph": max(vals),
            "grade": grade, "label": label}


# ── Click-first analytics: rig track record, provider rankings, heatmap, ──
#    expiring rentals, backtest (all drill-down targets for the panel).


def rig_track_record(rig_id: Any = None, rig_name: str = "",
                     tenant_id: str = "") -> Dict[str, Any]:
    """Full rig intelligence for a recommendation-card click — same shape as
    the detail route's rig_analysis, so the panel can open the rig verdict
    (trust grade, track record, blacklist) straight from a RECO card."""
    return analyze_rig(rig_id, rig_name, tenant_id=tenant_id)


def compute_provider_rankings(active: List[Dict], history: List[Dict],
                              owner: List[Dict], contracts: List[Dict]) -> List[Dict[str, Any]]:
    """Per-provider performance comparison (delivery / cost / P/L) so the
    operator answers 'where does the market deliver best?' at a glance.

    Only providers with data are included (honest — no fabricated rows).
    Returns [{provider, label, rentals, avg_delivery_pct, avg_cost_sats_per_thh,
    avg_pl_pct, spend_sats}] sorted by avg delivery desc.
    """
    def _bucket_rows(buckets: List[List[Dict]]) -> List[Dict]:
        return [r for b in buckets for r in b if isinstance(r, dict)]

    # Renter buckets only: the ranking answers 'where does the MARKET deliver
    # best?' — owner rows measure the operator's OWN rigs leased out (income
    # side), which must never distort delivery/cost/P·L of rented hashpower.
    mrr_rows = _bucket_rows([active, history])
    out: List[Dict[str, Any]] = []

    for provider, label, rows in (("mrr", "MRR", mrr_rows),):
        if not rows:
            continue
        pcts, costs, pl_pcts, spend = [], [], [], 0.0
        for r in rows:
            p = _num(r.get("hashrate_percent"))
            if p is not None:
                pcts.append(p)
            paid = _num(r.get("price_paid_btc"))
            if paid is not None:
                spend += paid * 1e8
            avg_th = _num(r.get("hashrate_average_th"))
            lenh = _num(r.get("length_hours"))
            delivered = (avg_th * lenh) if (avg_th and lenh) else None
            # Historical-P/L fix: rank providers on hashrate observed at each
            # rental's time (snapshot lookup, current as last resort).
            pl = compute_rental_pl(
                delivered, (paid * 1e8) if paid is not None else None,
                network_hashrate_hs=_resolve_network_hashrate_for_rental(
                    r.get("start"), r.get("end")))
            if pl.get("pl_pct") is not None:
                pl_pcts.append(pl["pl_pct"])
            if delivered and paid is not None:
                costs.append((paid * 1e8) / delivered)
        out.append({
            "provider": provider,
            "label": label,
            "rentals": len(rows),
            "avg_delivery_pct": round(sum(pcts) / len(pcts), 1) if pcts else None,
            "avg_cost_sats_per_thh": round(sum(costs) / len(costs), 2) if costs else None,
            "avg_pl_pct": round(sum(pl_pcts) / len(pl_pcts), 1) if pl_pcts else None,
            "spend_sats": round(spend),
        })
    # Braiins contracts: no delivery % in the list payload (only the speed
    # series has it) — cost is derivable when amount_sat exists.
    b_rents = [c for c in (contracts or []) if isinstance(c, dict)]
    if b_rents:
        amts = [c.get("amount_sat") for c in b_rents if c.get("amount_sat") is not None]
        out.append({
            "provider": "braiins",
            "label": "Braiins",
            "rentals": len(b_rents),
            "avg_delivery_pct": None,  # requires per-contract speed series
            "avg_cost_sats_per_thh": None,
            "avg_pl_pct": None,
            "spend_sats": round(sum(amts)) if amts else 0,
        })
    out.sort(key=lambda x: (x["avg_delivery_pct"] is not None, x["avg_delivery_pct"] or 0),
             reverse=True)
    return out


def compute_rig_heatmap(history: List[Dict], owner: List[Dict],
                        tenant_id: str = "") -> List[Dict[str, Any]]:
    """Heatmap cells rig-name × (avg delivery %, avg cost, samples) so the
    operator sees 'which rig MODELS deliver well at what price' in a grid.
    Uses the LOCAL track record (instant) plus the owner bucket for income
    rigs. Cells need ≥2 samples to avoid one-off noise."""
    from collections import defaultdict
    agg = defaultdict(lambda: {"pcts": [], "costs": [], "spend": 0.0})
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT rig_name, percent, cost_sats_per_thh, paid_sats "
                  "FROM rental_history WHERE tenant_id=? AND rig_name != '' AND bucket='renter'",
                  (tenant_id or "",))
        for row in c.fetchall():
            name = str(row["rig_name"] or "").strip()
            if not name:
                continue
            g = agg[name]
            if row["percent"] is not None:
                g["pcts"].append(_num(row["percent"]))
            if row["cost_sats_per_thh"] is not None:
                g["costs"].append(_num(row["cost_sats_per_thh"]))
            if row["paid_sats"] is not None:
                g["spend"] += _num(row["paid_sats"])
        conn.close()
    except Exception as e:
        log.warning("[rental_performance] heatmap failed: %s", e)
    cells = []
    for name, g in agg.items():
        if len(g["pcts"]) + len(g["costs"]) < 2:
            continue
        cells.append({
            "rig": name[:32],
            "samples": len(g["pcts"]) or len(g["costs"]),
            "avg_delivery_pct": round(sum(g["pcts"]) / len(g["pcts"]), 1) if g["pcts"] else None,
            "avg_cost_sats_per_thh": round(sum(g["costs"]) / len(g["costs"]), 2) if g["costs"] else None,
            "spend_sats": round(g["spend"]),
        })
    cells.sort(key=lambda x: -(x["avg_delivery_pct"] or 0))
    return cells


def compute_expiring_rentals(active: List[Dict], hours: float = 72.0) -> List[Dict[str, Any]]:
    """Active rentals whose end is within ``hours`` — a clickable calendar of
    what's about to finish (drill-down to the rental detail)."""
    now = time.time()
    out = []
    for r in active or []:
        end_u = _num(r.get("end_unix"))
        if end_u is None or end_u <= now:
            continue
        if end_u - now <= hours * 3600.0:
            out.append({**r, "ends_in_hours": round((end_u - now) / 3600.0, 1)})
    out.sort(key=lambda x: x["ends_in_hours"])
    return out


def compute_backtest(th: float, hours: float,
                    market: Optional[Dict] = None) -> Dict[str, Any]:
    """'What if I rented X TH for Y hours?' — cost at the cheapest live market
    price vs expected gross yield. Honest: yield needs network hashrate;
    without it only the cost side is returned (no fabricated P/L)."""
    mkt = market or fetch_market_reference()
    price = mkt.get("price_sats_per_thh") if mkt.get("available") else None
    cost_sats = (price * th * hours) if price else None
    yield_per_thh = compute_expected_yield_sats_per_thh()
    yield_sats = (yield_per_thh * th * hours) if yield_per_thh is not None else None
    pl_sats = (yield_sats - cost_sats) if (yield_sats is not None and cost_sats is not None) else None
    return {
        "available": True,
        "th": th, "hours": hours,
        "thh": round(th * hours, 1),
        "market_sats_per_thh": price,
        "cost_sats": round(cost_sats) if cost_sats is not None else None,
        "expected_yield_sats": round(yield_sats) if yield_sats is not None else None,
        "pl_sats": round(pl_sats) if pl_sats is not None else None,
        "yield_known": yield_per_thh is not None,
    }


# ── Worst-rig leaderboard + portfolio concentration (CFO risk view) ────────
# The counterpart to the recommendation engine: instead of 'where to rent
# again', answer 'which rigs burned me before'. Ranked from the LOCAL
# rental_history (tenant-scoped, instant) with industry-grade signals:
#   - EWMA delivery % — recent rentals weigh more (a rig that was fine six
#     months ago but under-delivers now must surface TODAY);
#   - failure rate    — share of rentals delivered below 90%;
#   - volatility      — stddev of delivery % (unstable = riskier);
#   - worst delivery  — the single worst rental;
#   - economic P/L    — expected gross yield vs paid per TH·h (honest '—'
#     when the network hashrate is unknown — never fabricated money);
#   - danger score 0-100 (higher = worse) blending the four signals.
# Honest gating: a rig needs ≥2 measured deliveries to be ranked at all —
# one bad rental is noise, not a verdict. Blacklist flags ride along so the
# panel can show WHY a rig is already excluded.

WORST_RIG_MIN_SAMPLES = 2
WORST_RIG_EWMA_ALPHA = 0.5   # 50% weight on the newest rental at each step


def compute_worst_rigs(tenant_id: str = "", limit: int = 8) -> Dict[str, Any]:
    """Rank the tenant's WORST rigs by historical delivery quality.

    Reads ONLY the local rental_history table (no provider calls — instant,
    and the same data the panel already shows). Every rig with ≥2 measured
    deliveries gets an EWMA-weighted delivery %, failure rate, volatility
    (stddev), worst delivery, trend, risk-adjusted P/L and a composite
    danger score.

    Returns {"worst": [...], "count": n, "min_samples": 2} sorted by danger
    desc, capped at ``limit``. Never raises — storage hiccup → empty list.
    """
    from collections import defaultdict
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT rig_id, rig_name, percent, start, paid_sats, delivered_thh, created_ts "
            "FROM rental_history WHERE tenant_id=? AND rig_id != '' AND bucket='renter'",
            (tenant_id or "",))
        rows = c.fetchall()
        conn.close()
    except Exception as e:
        log.warning("[rental_performance] worst rigs failed: %s", e)
        return {"worst": [], "count": 0,
                "min_samples": WORST_RIG_MIN_SAMPLES}

    # Per-rig: chronological (sort-key, pct) series + spend exposure. Sort
    # keys come from the shared _parse_start_ts so MRR 'YYYY-MM-DD …' AND
    # RFC3339 starts both order correctly (a lexicographic sort would not);
    # a row whose start never parses falls back to created_ts (same fallback
    # as compute_portfolio_series) so EWMA never reorders it to 'oldest'.
    by_rig: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"name": "", "series": [], "spend_sats": 0.0, "pl_per_thh": []})
    for r in rows:
        rid = r["rig_id"]
        b = by_rig[rid]
        if not b["name"]:
            b["name"] = r["rig_name"] or ""
        p = _to_float(r["percent"])
        if p is not None:
            ts = _parse_start_ts(r["start"])
            if ts is None and r["created_ts"]:
                ts = float(r["created_ts"])
            b["series"].append((ts or 0.0, p))
        if r["paid_sats"] is not None:
            b["spend_sats"] += _num(r["paid_sats"])
        dthh = _to_float(r["delivered_thh"])
        if dthh and r["paid_sats"] is not None:
            # Historical-P/L fix: per-rig economics priced at the hashrate
            # observed at each rental's time, not today's.
            pl = compute_rental_pl(dthh, _num(r["paid_sats"]),
                                   network_hashrate_hs=_rental_network_hashrate(r))
            if pl.get("pl_sats") is not None:
                b["pl_per_thh"].append(pl["pl_sats"] / dthh)

    manual = set(get_rig_blacklist(tenant_id=tenant_id))
    auto = set(get_auto_blacklist(tenant_id=tenant_id))

    worst: List[Dict[str, Any]] = []
    for rid, b in by_rig.items():
        series = sorted(b["series"], key=lambda x: x[0])
        pcts = [p for _, p in series]
        if len(pcts) < WORST_RIG_MIN_SAMPLES:
            continue
        # EWMA delivery — recent rentals dominate (alpha on the newest).
        ewma = pcts[0]
        for p in pcts[1:]:
            ewma = WORST_RIG_EWMA_ALPHA * p + (1 - WORST_RIG_EWMA_ALPHA) * ewma
        mean = sum(pcts) / len(pcts)
        worst_pct = min(pcts)
        stddev = (sum((p - mean) ** 2 for p in pcts) / len(pcts)) ** 0.5
        fail_rate = sum(1 for p in pcts if p < 90.0) / len(pcts)
        # Trend: newest 3 vs the previous ones (positive = improving).
        trend = None
        if len(pcts) >= 4:
            recent = sum(pcts[-3:]) / 3.0
            older = sum(pcts[:-3]) / (len(pcts) - 3)
            trend = round(recent - older, 1)
        # Danger score 0-100 (higher = worse): EWMA deficit 40% · volatility
        # 15% · failure rate 25% · worst delivery 20%.
        deficit = max(0.0, 100.0 - ewma)
        vol_term = min(30.0, stddev) / 30.0 * 100.0
        fail_term = fail_rate * 100.0
        worst_term = min(1.0, max(0.0, 85.0 - worst_pct) / 85.0) * 100.0
        danger = 0.40 * deficit + 0.15 * vol_term + 0.25 * fail_term + 0.20 * worst_term
        # Confidence cap: exactly 2 samples → at most 65 (a two-rental rig
        # must not top the leaderboard on a single bad streak).
        if len(pcts) < 3:
            danger = min(danger, 65.0)
        rid_str = str(rid)
        pl_avg = (sum(b["pl_per_thh"]) / len(b["pl_per_thh"])) if b["pl_per_thh"] else None
        # Same trust-grade engine as the rig track record modal, so the
        # leaderboard and the detail story never disagree (one scoring
        # system — the median-based grade A-F rides along on the danger row).
        trust = compute_rig_trust_score([{"percent": p} for p in pcts])
        worst.append({
            "rig_id": rid_str,
            "name": b["name"],
            "grade": trust.get("grade"),
            "samples": len(pcts),
            "ewma_delivery_pct": round(ewma, 1),
            "avg_delivery_pct": round(mean, 1),
            "worst_pct": round(worst_pct, 1),
            "volatility_pct": round(stddev, 1),
            "fail_rate_pct": round(fail_rate * 100.0, 1),
            "trend_pct": trend,
            "pl_sats_per_thh": round(pl_avg, 2) if pl_avg is not None else None,
            "spend_sats": round(b["spend_sats"]),
            "danger_score": round(danger, 1),
            "blacklisted": rid_str in manual,
            "auto_blacklisted": rid_str in auto,
        })
    worst.sort(key=lambda x: x["danger_score"], reverse=True)
    return {"worst": worst[:limit], "count": len(worst),
            "min_samples": WORST_RIG_MIN_SAMPLES}


def compute_concentration_risk(active: List[Dict], history: List[Dict],
                               owner: List[Dict],
                               contracts: List[Dict]) -> Dict[str, Any]:
    """Provider + rig concentration of the tenant's rental spend.

    Portfolio-level risk (CFO): if 90% of everything rented comes from ONE
    provider or ONE rig, a single failure (bad actor, grid outage) hits the
    whole book. Returns:
      {"available": True, "total_spend_sats": n,
       "providers": [{provider, label, spend_sats, share_pct}],
       "hhi": 0-10000 (Herfindahl over providers), "top_provider": {...},
       "top_rig": {rig_id, rig_name, spend_sats, share_pct}}
    — or {"available": False} when no spend is measurable (honest '—').
    """
    from collections import defaultdict
    prov_spend: Dict[str, float] = defaultdict(float)
    rig_spend: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"name": "", "spend": 0.0})

    def _acc(rows: Optional[List[Dict]]) -> None:
        for r in rows or []:
            if not isinstance(r, dict):
                continue
            paid = _num(r.get("price_paid_btc"))
            sats = (paid * 1e8) if paid is not None else None
            if sats is None or sats <= 0:
                continue
            prov_spend["mrr"] += sats
            rig = r.get("rig") or {}
            rid = rig.get("id")
            if rid is not None:
                g = rig_spend[str(rid)]
                if not g["name"]:
                    g["name"] = rig.get("name") or ""
                g["spend"] += sats

    _acc(active)
    _acc(history)
    _acc(owner)
    for c in contracts or []:
        if isinstance(c, dict) and c.get("amount_sat"):
            prov_spend["braiins"] += _num(c["amount_sat"]) or 0.0

    total = sum(prov_spend.values())
    if total <= 0:
        return {"available": False}
    providers = [
        {"provider": p, "label": "MRR" if p == "mrr" else "Braiins",
         "spend_sats": round(s), "share_pct": round(s / total * 100.0, 1)}
        for p, s in prov_spend.items()
    ]
    providers.sort(key=lambda x: x["share_pct"], reverse=True)
    # Herfindahl-Hirschman over provider shares (10000 = fully concentrated).
    hhi = round(sum((s / total * 100.0) ** 2 for s in prov_spend.values()), 1)
    top_rig = None
    if rig_spend:
        rid, g = max(rig_spend.items(), key=lambda kv: kv[1]["spend"])
        top_rig = {"rig_id": rid, "rig_name": g["name"],
                   "spend_sats": round(g["spend"]),
                   "share_pct": round(g["spend"] / total * 100.0, 1)}
    return {"available": True, "total_spend_sats": round(total),
            "providers": providers, "hhi": hhi,
            "top_provider": providers[0], "top_rig": top_rig}


# ── Difficulty-adjustment forecast (market timing, from local snapshots) ───
# When is the next 2016-block retarget, and how much will difficulty move?
# Renting right before a big difficulty SPIKE is like paying yesterday's
# price for tomorrow's fewer blocks. The forecast derives the CURRENT block
# cadence from the LOCAL snapshots table (height deltas over time — the same
# source the halving countdown uses) — zero extra network calls, honest '—'
# when there isn't enough history to measure.

DIFF_TARGET_SECONDS = 2016 * 600.0   # 2016 blocks × 10 min
DIFF_MAX_CHANGE_PCT = 350.0          # protocol cap on a single retarget


def compute_difficulty_forecast() -> Dict[str, Any]:
    """Projected next difficulty adjustment from local block-cadence data.

    Methodology (CFO read):
      - current difficulty + height from the shared polling snapshot;
      - rolling average block time from the LAST 100 local snapshots
        (height delta ÷ time delta per interval, MEDIAN across intervals to
        shrug off an outlier poll);
      - blocks_remaining = 2016 − (height mod 2016);
      - projected change = (target_seconds / (avg_block_time × 2016) − 1)
        → faster blocks than 10 min mean difficulty goes UP.

    Returns {"available": True, "avg_block_time_s", "blocks_remaining",
    "hours_to_adjustment", "projected_change_pct", "direction" (up/down/flat),
    "verdict"} or {"available": False} when height/difficulty/block cadence
    is unknown (cold box) — never fabricates a projection.
    """
    try:
        from services.state import latest_snapshot
        net = latest_snapshot.get("network") or {}
        difficulty = _to_float(net.get("difficulty"))
        height = net.get("height")
    except Exception:
        difficulty, height = None, None
    if difficulty is None or height is None:
        return {"available": False}
    try:
        height = int(height)
    except (TypeError, ValueError):
        return {"available": False}

    # Rolling block cadence from local snapshots (height deltas).
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT ts, network_height FROM snapshots "
            "WHERE network_height IS NOT NULL ORDER BY ts DESC LIMIT 100")
        rows = c.fetchall()
        conn.close()
    except Exception:
        rows = []
    # The query is DESC (newest first) — reverse so the interval loop walks
    # oldest → newest and height/ts deltas come out POSITIVE.
    rows = list(reversed(rows))
    intervals: List[float] = []
    for i in range(1, len(rows)):
        older, newer = rows[i - 1], rows[i]
        try:
            dh = int(newer["network_height"]) - int(older["network_height"])
            dt = float(newer["ts"]) - float(older["ts"])
        except (TypeError, ValueError, KeyError):
            continue
        if dh > 0 and dt > 0:
            intervals.append(dt / dh)
    if not intervals:
        return {"available": False}
    intervals.sort()
    n = len(intervals)
    avg_block_s = intervals[n // 2] if n % 2 else (intervals[n // 2 - 1] + intervals[n // 2]) / 2.0
    avg_block_s = max(300.0, min(3600.0, avg_block_s))

    blocks_remaining = 2016 - (height % 2016)
    hours_to_adj = blocks_remaining * avg_block_s / 3600.0
    # Projected retarget: new_diff = old_diff × (target_time / actual_epoch_time)
    # → change % = (target / (avg_block_s × 2016) − 1) × 100.
    change_pct = (DIFF_TARGET_SECONDS / (avg_block_s * 2016.0) - 1.0) * 100.0
    change_pct = max(-DIFF_MAX_CHANGE_PCT, min(DIFF_MAX_CHANGE_PCT, change_pct))
    direction = "up" if change_pct > 2.0 else ("down" if change_pct < -2.0 else "flat")
    if direction == "up":
        verdict = (f"difficulty projetada +{change_pct:.0f}% no próximo ajuste "
                   f"(~{hours_to_adj:.0f}h) — blocos mais rápidos que 10min; "
                   f"aluguéis longos que cruzam o ajuste pagam mais caro por menos")
    elif direction == "down":
        verdict = (f"difficulty projetada {change_pct:.0f}% no próximo ajuste "
                   f"(~{hours_to_adj:.0f}h) — janela barata: alugar agora rende mais "
                   f"TH·h por sats")
    else:
        verdict = (f"difficulty estável no próximo ajuste (~{hours_to_adj:.0f}h) — "
                   f"cadência de blocos alinhada ao alvo de 10min")
    return {
        "available": True,
        "difficulty": difficulty,
        "height": height,
        "avg_block_time_s": round(avg_block_s, 1),
        "blocks_remaining": blocks_remaining,
        "hours_to_adjustment": round(hours_to_adj, 1),
        "projected_change_pct": round(change_pct, 1),
        "direction": direction,
        "verdict": verdict,
    }


# ── Risk alerts: worst-rig leaderboard + concentration thresholds ──────────
# Second alert family after rental P/L: when a rig ENTERS the worst-rig top-N
# (danger score past the tenant threshold) or the portfolio concentration
# crosses a provider-share threshold, the tenant gets a webhook + push.
# Same discipline as the P/L alerts: persisted dedup (one alert per rig /
# per concentration event), tenant-scoped, settings-gated, atomic claim.

RENTAL_RISK_ALERTS_SETTING = "rental_risk_alerts"          # "1" enables
RENTAL_RISK_DANGER_SETTING = "rental_risk_danger"          # min danger score (default 50)
RENTAL_RISK_TOP_N_SETTING = "rental_risk_top_n"            # top-N to watch (default 5)
RENTAL_RISK_CONC_PCT_SETTING = "rental_risk_conc_pct"      # top-provider share % (default 55)


def _ensure_risk_alert_table() -> None:
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS rental_risk_alerts (
            tenant_id TEXT NOT NULL DEFAULT '',
            alert_key TEXT NOT NULL,
            alert_value TEXT NOT NULL,
            metric REAL,
            fired_ts INTEGER,
            PRIMARY KEY (tenant_id, alert_key, alert_value)
        )""")
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("[rental_performance] risk-alert table ensure failed: %s", e)


def _mark_risk_alert_fired(tenant_id: str, alert_key: str, alert_value: str,
                           metric: Optional[float]) -> bool:
    """ATOMICALLY claim the dedup slot (INSERT OR IGNORE) — the concurrent
    /api/rentals request loses the race and does NOT double-fire."""
    _ensure_risk_alert_table()
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "INSERT OR IGNORE INTO rental_risk_alerts(tenant_id,alert_key,alert_value,metric,fired_ts) "
            "VALUES(?,?,?,?,?)",
            (tenant_id or "", alert_key, alert_value, metric, int(time.time())))
        conn.commit()
        claimed = c.rowcount == 1
        conn.close()
        return claimed
    except Exception:
        # Fail-open: a dedup write hiccup must never suppress a risk alert.
        return True


def _risk_alert_settings(tenant_id: str = "") -> Dict[str, Any]:
    """Enabled + thresholds from the tenant's settings (honest defaults)."""
    s = load_settings(tenant_id=tenant_id)
    enabled = str((s.get(RENTAL_RISK_ALERTS_SETTING) or "").strip() or "").lower() in ("1", "true", "on", "sim")
    try:
        danger = float((s.get(RENTAL_RISK_DANGER_SETTING) or "50") or 50)
    except (TypeError, ValueError):
        danger = 50.0
    try:
        top_n = int((s.get(RENTAL_RISK_TOP_N_SETTING) or "5") or 5)
    except (TypeError, ValueError):
        top_n = 5
    try:
        conc_pct = float((s.get(RENTAL_RISK_CONC_PCT_SETTING) or "55") or 55)
    except (TypeError, ValueError):
        conc_pct = 55.0
    return {"enabled": enabled, "danger": max(0.0, min(100.0, danger)),
            "top_n": max(1, min(20, top_n)), "conc_pct": max(10.0, min(100.0, conc_pct))}


def evaluate_risk_alerts(tenant_id: str = "",
                         concentration: Optional[Dict] = None,
                         worst_rigs: Optional[Dict] = None) -> List[Dict[str, Any]]:
    """Worst-rig top-N + concentration threshold → per-tenant risk alerts.

    Dedup: one alert per rig (alert_key='worst_rig', value=rig_id) and one
    per concentration crossing (alert_key='concentration', value=provider).
    Worst-rig ranking is LOCAL (no provider calls); both analytics can be
    passed in pre-computed (the panel already built them for the payload —
    zero recompute), or computed here when omitted (sweep). Concentration
    is skipped when None (sweep keeps zero-cost discipline).

    Returns alert dicts [{severity, category, message, ...}] — the caller
    dispatches them through the shared tenant webhook+push.
    """
    cfg = _risk_alert_settings(tenant_id=tenant_id)
    if not cfg["enabled"]:
        return []
    out: List[Dict[str, Any]] = []

    # Worst-rig top-N: any rig in the top-N with danger ≥ threshold fires.
    try:
        if worst_rigs is None:
            worst_rigs = compute_worst_rigs(tenant_id=tenant_id, limit=cfg["top_n"])
        # Honor the tenant's top-N even when a precomputed (wider) list was
        # passed in from the panel — a rig ranked beyond top_n must not fire.
        for w in worst_rigs.get("worst", [])[:cfg["top_n"]]:
            danger = _num(w.get("danger_score"))
            if danger is None or danger < cfg["danger"]:
                continue
            if not _mark_risk_alert_fired(tenant_id, "worst_rig", str(w["rig_id"]), danger):
                continue
            out.append(_build_risk_alert(
                f"Rig {w.get('name') or w['rig_id']} (#{w['rig_id']}) entrou no top-{cfg['top_n']} dos PIORES rigs — "
                f"danger {danger:.0f}/100 · entrega EWMA {_fmt(w.get('ewma_delivery_pct'))}% · "
                f"fail rate {_fmt(w.get('fail_rate_pct'))}%",
                severity="CRIT" if danger >= 70 else "WARN",
                category="rental_risk_rig",
                value=str(w["rig_id"]), metric=danger))
    except Exception as e:
        log.warning("[rental_performance] risk worst-rig eval failed: %s", e)

    # Concentration: top-provider share crossing the threshold fires once.
    if concentration and concentration.get("available"):
        top = concentration.get("top_provider") or {}
        share = _num(top.get("share_pct"))
        if share is not None and share >= cfg["conc_pct"]:
            prov = str(top.get("provider") or "unknown")
            if _mark_risk_alert_fired(tenant_id, "concentration", prov, share):
                out.append(_build_risk_alert(
                    f"Concentração de portfólio: {share:.0f}% do gasto ({top.get('label') or prov}) — "
                    f"acima do limite de {cfg['conc_pct']:.0f}% (HHI {_num(concentration.get('hhi')):.0f}). "
                    f"Um único provider/rig em falha derruba o livro inteiro.",
                    severity="WARN", category="rental_risk_concentration",
                    value=prov, metric=share))
    return out


def _fmt(v: Optional[float]) -> str:
    return f"{v:.1f}" if v is not None else "—"


def _build_risk_alert(message: str, severity: str, category: str,
                      value: str, metric: Optional[float]) -> Dict[str, Any]:
    return {"severity": severity, "category": category,
            "message": message[:280], "value": value, "metric": metric}


def risk_alert_enabled_tenants() -> List[str]:
    """Tenant ids with risk alerts enabled (for the periodic sweep). The
    worst-rig half of the sweep is LOCAL (zero provider cost), so unlike the
    P/L sweep there is no credential gate — only the opt-in matters."""
    out: List[str] = []
    try:
        _ensure_rig_settings_tables()
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT DISTINCT tenant_id, value FROM tenant_settings WHERE key=?",
                  (RENTAL_RISK_ALERTS_SETTING,))
        rows = c.fetchall()
        conn.close()
        for r in rows:
            if str((r["value"] or "")).strip().lower() in ("1", "true", "on", "sim"):
                out.append(r["tenant_id"])
    except Exception:
        pass
    try:
        s = load_settings(tenant_id="")
        if str((s.get(RENTAL_RISK_ALERTS_SETTING) or "")).strip().lower() in ("1", "true", "on", "sim"):
            out.append("")
    except Exception:
        pass
    return list(dict.fromkeys(out))


def sweep_risk_alerts(tenant_id: str = "") -> List[Dict[str, Any]]:
    """One risk-alert sweep pass for a tenant: evaluate worst-rig top-N (local,
    zero provider calls) + dispatch-ready alerts. Concentration is skipped
    here (needs the buckets) — it fires on the panel load instead."""
    try:
        return evaluate_risk_alerts(tenant_id=tenant_id, concentration=None)
    except Exception as e:
        log.warning("[rental_performance] risk sweep %s: %s", tenant_id or "default", e)
        return []


# ── Auto-alert: rental closed with P/L below threshold ─────────────────────
# Fired from /api/rentals each time the panel loads (the moment the server
# learns a rental ended). One alert PER RENTAL EVER (persisted dedup), gated
# to recent closes (window) so first-enable never backfills a flood of old
# rentals. Decision is honest — never fabricates a metric:
#   - threshold empty/0 → disabled
#   - yield known (network hashrate): economic P/L < threshold
#   - yield unknown (cold box): effective cost > market × (1 + |threshold|/100)
#   - neither → skipped
# Braiins ended contracts are SKIPPED on purpose: the list payload has no
# delivered TH·h (requires the per-contract speed series) — alerting on
# advertised speed would be dishonest.

RENTAL_PL_ALERT_SETTING = "rental_pl_alert_pct"          # e.g. "-50" (empty/0 = off)
RENTAL_PL_WINDOW_SETTING = "rental_pl_alert_window_hours"  # default 48
RENTAL_PL_ALERT_PRUNE_DAYS = 90


def pl_alert_enabled_tenants() -> List[str]:
    """Tenant ids that should be swept for rental P/L alerts.

    The periodic sweep (UserPollingWorker) must not fetch MRR history for
    every one of 1000+ tenants every cycle — that would burn the MRR rate
    budget. Only tenants with BOTH:
      - the alert configured (rental_pl_alert_pct < 0), AND
      - MRR credentials present (otherwise fetch_mrr_rentals returns
        needs_auth immediately — a wasted cycle),
    are returned. The default/operator tenant is included when its GLOBAL
    setting is enabled. Never raises: a storage hiccup → empty list (the
    sweep simply skips this cycle).
    """
    out: List[str] = []
    try:
        _ensure_rig_settings_tables()  # self-heal: fresh DBs lack the table
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT DISTINCT tenant_id, value FROM tenant_settings WHERE key=?",
                  (RENTAL_PL_ALERT_SETTING,))
        rows = c.fetchall()
        conn.close()
        for r in rows:
            try:
                thr = float((r["value"] or "").strip())
            except (TypeError, ValueError):
                continue
            if thr < 0 and mrr_credentials(tenant_id=r["tenant_id"])["api_key"]:
                out.append(r["tenant_id"])
    except Exception as e:
        log.warning("[rental_performance] pl-alert tenant scan failed: %s", e)
        # A named-tenant scan failure must NOT skip the default tenant below
        # (the operator's own alerts still matter) — fall through, don't return.
    # Default tenant (operator self-host): global settings table.
    try:
        s = load_settings(tenant_id="")
        thr = (s.get(RENTAL_PL_ALERT_SETTING) or "").strip()
        if thr and float(thr) < 0 and mrr_credentials(tenant_id="")["api_key"]:
            out.append("")
    except Exception:
        pass
    # Dedup (default tenant could theoretically appear as '' in the scan).
    return list(dict.fromkeys(out))


def _sweep_fetch_history(tenant_id: str = "") -> List[Dict]:
    """Shared by the P/L and market-overpay sweeps: ONE MRR renter history
    fetch + local ingest (the portfolio series + rig track record depend on
    the ingest). Returns [] on a provider hiccup (logged) — the caller then
    simply has nothing to evaluate. One fetch per enabled tenant per cycle,
    never per alert family."""
    try:
        listing = fetch_mrr_rentals(rtype="renter", history=True, limit=50,
                                    tenant_id=tenant_id)
        if not listing.get("success"):
            if listing.get("needs_auth"):
                log.debug("[rentals-sweep] %s: no MRR credentials", tenant_id or "default")
            else:
                log.warning("[rentals-sweep] %s: MRR fetch failed: %s",
                            tenant_id or "default", listing.get("error"))
            return []
        history = listing.get("rentals", [])
        try:
            ingest_rentals([], history, [], [], tenant_id=tenant_id)
        except Exception as _ie:
            log.warning("[rentals-sweep] %s: ingest error: %s",
                        tenant_id or "default", _ie)
        return history
    except Exception as e:
        log.warning("[rentals-sweep] %s: sweep error: %s",
                    tenant_id or "default", e)
        return []


def sweep_rental_pl_alerts(tenant_id: str = "") -> List[Dict[str, Any]]:
    """One P/L-alert sweep pass for a single tenant: fetch MRR renter history
    (ONE API call), evaluate, ingest, and return the ALERTS. Returns [] when
    nothing to judge or a provider hiccup (logged, never raised)."""
    return evaluate_rental_pl_alerts(_sweep_fetch_history(tenant_id), [],
                                     tenant_id=tenant_id)


def sweep_rental_market_alerts(tenant_id: str = "") -> List[Dict[str, Any]]:
    """One market-overpay sweep pass for a single tenant (same discipline as
    sweep_rental_pl_alerts): ONE MRR history fetch, evaluate overpay vs the
    market at purchase time, ingest, and return the ALERTS."""
    return evaluate_market_overpay_alerts(_sweep_fetch_history(tenant_id), [],
                                          tenant_id=tenant_id)


def _ensure_pl_alert_table() -> None:
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS rental_pl_alerts (
            tenant_id TEXT NOT NULL DEFAULT '',
            provider TEXT NOT NULL DEFAULT 'mrr',
            rental_id TEXT NOT NULL,
            metric REAL,
            fired_ts INTEGER,
            PRIMARY KEY (tenant_id, provider, rental_id)
        )""")
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("[rental_performance] pl-alert table ensure failed: %s", e)


def _pl_alert_fired(tenant_id: str, provider: str, rental_id: str) -> bool:
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT 1 FROM rental_pl_alerts WHERE tenant_id=? AND provider=? AND rental_id=?",
                  (tenant_id or "", provider, rental_id))
        row = c.fetchone()
        conn.close()
        return row is not None
    except Exception:
        return False


def _mark_pl_alert_fired(tenant_id: str, provider: str, rental_id: str,
                         metric: Optional[float]) -> bool:
    """ATOMICALLY claim the dedup slot (INSERT OR IGNORE). Returns True only
    for the caller that INSERTED (rowcount 1) — a concurrent /api/rentals
    request gets False and must NOT fire (check-then-set would double-fire
    webhooks on panel refresh + another tab). Fail-open on storage errors:
    never suppress a bad-rental alert because the dedup write hiccuped."""
    _ensure_pl_alert_table()
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "INSERT OR IGNORE INTO rental_pl_alerts(tenant_id,provider,rental_id,metric,fired_ts) "
            "VALUES(?,?,?,?,?)",
            (tenant_id or "", provider, rental_id, metric, int(time.time())))
        conn.commit()
        claimed = c.rowcount == 1
        conn.close()
        return claimed
    except Exception as e:
        log.warning("[rental_performance] pl-alert mark failed: %s", e)
        return True  # fail-open: deliver the alert, dedup may re-fire once


_pl_prune_ts = 0.0  # module-level gate: prune at most once per hour


def _prune_pl_alerts(force: bool = False) -> None:
    """Drop dedup rows older than the prune horizon. Gated to once/hour — the
    full-table DELETE must never scan on every panel load at 1000+ tenants."""
    global _pl_prune_ts
    now = time.time()
    if not force and (now - _pl_prune_ts) < 3600.0:
        return
    _pl_prune_ts = now
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("DELETE FROM rental_pl_alerts WHERE fired_ts < ?",
                  (int(time.time()) - RENTAL_PL_ALERT_PRUNE_DAYS * 86400,))
        conn.commit()
        conn.close()
    except Exception:
        pass


def _build_pl_alert(provider: str, rental_id: Any, delivery_pct: Optional[float],
                    cost_sats_per_thh: Optional[float],
                    pl: Optional[Dict], market: Optional[Dict]) -> Dict[str, Any]:
    """Alert payload: severity WARN, category rental_pl — concise enough for
    both webhook embeds and Web Push (≤ ~200 chars)."""
    parts = [f"Rental #{rental_id} ({provider.upper()}) fechou com prejuízo"]
    if pl and pl.get("pl_pct") is not None:
        parts.append(f"P/L {pl['pl_pct']:.0f}% (yield vs custo)")
    if cost_sats_per_thh is not None:
        parts.append(f"custo {cost_sats_per_thh:.0f} sats/TH·h")
    if delivery_pct is not None:
        parts.append(f"{delivery_pct:.0f}% do anunciado")
    if market and market.get("price_sats_per_thh") and cost_sats_per_thh:
        diff = (cost_sats_per_thh / market["price_sats_per_thh"] - 1.0) * 100.0
        parts.append(f"{diff:+.0f}% vs mercado ({market.get('provider') or 'market'})")
    return {
        "severity": "WARN",
        "category": "rental_pl",
        "message": " — ".join(parts)[:280],
        "rental_id": str(rental_id),
        "provider": provider,
    }


def evaluate_rental_pl_alerts(history: List[Dict], contracts: Optional[List[Dict]] = None,
                              tenant_id: str = "", now: Optional[int] = None) -> List[Dict[str, Any]]:
    """Closed MRR rentals with economic P/L below the tenant threshold → alerts.

    Dedup: one alert per rental EVER (persisted per tenant/provider/rental id).
    Window: only rentals that ended within ``rental_pl_alert_window_hours`` —
    a rental with an unknown end time is treated as recent (bounded by the
    history cap + dedup). Braiins contracts are intentionally skipped.
    """
    s = load_settings(tenant_id=tenant_id)
    raw = (s.get(RENTAL_PL_ALERT_SETTING) or "").strip()
    try:
        threshold = float(raw)
    except (TypeError, ValueError):
        return []
    if not raw or threshold >= 0:
        return []  # disabled / non-sensical threshold
    window_h = 48.0
    try:
        window_h = float((s.get(RENTAL_PL_WINDOW_SETTING) or "48") or 48)
    except (TypeError, ValueError):
        window_h = 48.0
    if window_h <= 0:
        window_h = 48.0
    now = int(now or time.time())

    _prune_pl_alerts()
    market: Optional[Dict] = None  # lazily fetched once (cached fetcher)

    def _overpaid(cost: float) -> bool:
        """Cold-box fallback: effective cost > market × (1 + |threshold|/100)."""
        nonlocal market
        if market is None:
            market = fetch_market_reference()
        m = market.get("price_sats_per_thh") if market.get("available") else None
        return bool(m and cost > m * (1.0 + abs(threshold) / 100.0))

    out: List[Dict[str, Any]] = []
    for r in history or []:
        if not r.get("ended"):
            continue
        rid = r.get("id")
        if rid is None:
            continue
        end_u = _num(r.get("end_unix"))
        if end_u is not None and (now - end_u) > window_h * 3600.0:
            continue
        if _pl_alert_fired(tenant_id, "mrr", str(rid)):
            continue

        avg_th = _num(r.get("hashrate_average_th"))
        length_h = _num(r.get("length_hours"))
        paid = _num(r.get("price_paid_btc"))
        delivered = (avg_th * length_h) if (avg_th and length_h) else None
        paid_sats = (paid * 1e8) if paid is not None else None
        delivery_pct = _num(r.get("hashrate_percent"))
        cost = (paid_sats / delivered) if (paid_sats is not None and delivered) else None

        pl: Optional[Dict] = None
        fired = False
        if delivered and paid_sats is not None:
            # Historical-P/L fix: judge against the hashrate observed at the
            # rental's time (snapshot lookup, current as last resort).
            pl = compute_rental_pl(
                delivered, paid_sats,
                network_hashrate_hs=_resolve_network_hashrate_for_rental(
                    r.get("start"), r.get("end")))
            if pl.get("pl_pct") is not None:
                fired = pl["pl_pct"] < threshold
            elif cost is not None:
                fired = _overpaid(cost)  # yield unknown → overpay vs market
        elif cost is not None:
            fired = _overpaid(cost)
        if not fired:
            continue  # nothing to judge honestly / not bad enough

        metric = pl["pl_pct"] if (pl and pl.get("pl_pct") is not None) else None
        # Atomic claim: only the winner of the INSERT fires (race-safe dedup).
        if not _mark_pl_alert_fired(tenant_id, "mrr", str(rid), metric):
            continue
        out.append(_build_pl_alert("mrr", rid, delivery_pct, cost, pl, market))
    return out


# ── Auto-alert: price paid X% ABOVE market at purchase time ────────────────
# The P/L family judges "did the rental make money?" (yield vs paid). This
# family judges the COUNTER price: "did I overpay for the hashpower I bought?".
# The comparison is the AGREED price per TH·h (paid ÷ advertised TH × hours) —
# computable at purchase time with no delivery dependency — against the
# cheapest market price OBSERVED at that moment (hashrate_market_history
# nearest snapshot; live quote only as last resort). Fires once per rental
# (persisted dedup, same table, provider tag 'mrr_overpay' so the P/L slot
# stays independent).

RENTAL_MARKET_OVERPAY_SETTING = "rental_market_overpay_pct"  # e.g. "100" (empty/0 = off)

# ── Arbitrage-opportunity alert (market vs the tenant's OWN avg cost) ──────
# When the CURRENT market price is ≥ X% BELOW what the tenant historically
# PAID per TH·h, the market is offering a genuine buying window for THEM —
# fire a per-tenant webhook/push. Local-first: the baseline comes from the
# tenant's own rental_history and the market price from the local
# hashrate_market_history table — ZERO provider cost, so no MRR credentials
# are required (gating is purely the threshold setting).
RENTAL_MARKET_ARB_SETTING = "rental_market_arb_pct"  # e.g. "30" (empty/0 = off)
RENTAL_MARKET_ARB_COOLDOWN_SETTING = "rental_market_arb_cooldown_hours"  # default 24
_ARB_MARKET_WINDOW_H = 12.0  # "agora" = cheapest quote in the last 12h

# Nearest-market window around the purchase timestamp (±3 days). The market
# history persists every market poll, so a snapshot within days is far more
# accurate than today's quote for a purchase a week ago.
_MARKET_PRICE_WINDOW_S = 3 * 86400
_market_price_cache: Dict[int, Optional[float]] = {}
_market_index_ensured = False


def _ensure_market_history_index() -> None:
    """Idempotent index on hashrate_market_history(ts) — normally created by
    init_db, but self-heal here so the nearest-price lookup never full-scans
    a fresh DB (tests / cold box)."""
    global _market_index_ensured
    if _market_index_ensured:
        return
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("CREATE INDEX IF NOT EXISTS idx_hashrate_market_history_ts ON hashrate_market_history(ts)")
        conn.commit()
        conn.close()
        _market_index_ensured = True
    except Exception:
        pass


def _historical_market_sats_per_thh(ts: Optional[float]) -> Optional[float]:
    """Cheapest PLAUSIBLE market price (sats/TH·h) observed near ``ts`` — the
    MIN across venues in hashrate_market_history within ±3 days, same
    semantics as fetch_market_reference() (cheapest quote). Cached per UTC
    day; only positive values are cached (a day gaining coverage later is
    re-resolved). Returns None when nothing covers that window."""
    if not ts:
        return None
    import datetime as _dt
    day = int(_dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).strftime("%Y%m%d"))
    if day in _market_price_cache:
        return _market_price_cache[day]
    _ensure_market_history_index()
    val: Optional[float] = None
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT MIN(price_per_th_day) FROM hashrate_market_history "
            "WHERE ts BETWEEN ? AND ? AND algorithm='sha256' AND price_per_th_day >= ?",
            (int(ts) - _MARKET_PRICE_WINDOW_S, int(ts) + _MARKET_PRICE_WINDOW_S,
             _MIN_PLAUSIBLE_PRICE))
        row = c.fetchone()
        conn.close()
        if row and row[0]:
            val = float(row[0]) * 1e8 / 24.0  # BTC/TH/day → sats/TH·h
    except Exception as e:
        log.warning("[rental_performance] historical market price lookup failed: %s", e)
    if val and val > 0:
        _market_price_cache[day] = val
    return val


def _tenant_avg_cost_sats_per_thh(tenant_id: str = "") -> Optional[float]:
    """Weighted-average unit cost (sats/TH·h) the tenant actually PAID across
    their historical rentals (renter bucket). Baseline for the arbitrage
    alert: a market price far below this = a real buying window for THIS user.
    None when there's no usable track record (honest skip)."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT SUM(paid_sats), SUM(advertised_th * length_hours) "
            "FROM rental_history WHERE tenant_id=? AND bucket='renter' "
            "AND paid_sats > 0 AND advertised_th > 0 AND length_hours > 0",
            (tenant_id or "",))
        row = c.fetchone()
        conn.close()
        if row and row[0] and row[1]:
            return float(row[0]) / float(row[1])
    except Exception as e:
        log.warning("[rental_performance] avg cost lookup failed: %s", e)
    return None


def _recent_market_sats_per_thh(now: Optional[int] = None,
                                window_h: float = _ARB_MARKET_WINDOW_H) -> Optional[float]:
    """Cheapest plausible market price (sats/TH·h) in the last ``window_h``
    hours — the freshest window for an 'oportunidade AGORA' signal. Falls
    back to the ±3-day historical (cached per day). LOCAL-ONLY by design:
    this family is zero provider cost, so there is deliberately NO live
    quote fallback here."""
    now = int(now or time.time())
    try:
        _ensure_market_history_index()
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT MIN(price_per_th_day) FROM hashrate_market_history "
            "WHERE ts >= ? AND algorithm='sha256' AND price_per_th_day >= ?",
            (int(now) - int(window_h * 3600), _MIN_PLAUSIBLE_PRICE))
        row = c.fetchone()
        conn.close()
        if row and row[0]:
            return float(row[0]) * 1e8 / 24.0  # BTC/TH/day → sats/TH·h
    except Exception as e:
        log.warning("[rental_performance] recent market price lookup failed: %s", e)
    return _historical_market_sats_per_thh(now)


def market_arb_enabled_tenants() -> List[str]:
    """Tenant ids that should be swept for market-arbitrage alerts.

    LOCAL evaluation (baseline from the tenant's own rental_history + the
    local market table) → zero provider cost, so NO MRR credentials are
    required: gating is purely the threshold setting. Default/operator tenant
    included when its GLOBAL setting is enabled."""
    out: List[str] = []
    try:
        _ensure_rig_settings_tables()
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT DISTINCT tenant_id, value FROM tenant_settings WHERE key=?",
                  (RENTAL_MARKET_ARB_SETTING,))
        rows = c.fetchall()
        conn.close()
        for r in rows:
            try:
                thr = float((r["value"] or "").strip())
            except (TypeError, ValueError):
                continue
            if thr > 0:
                out.append(r["tenant_id"])
    except Exception as e:
        log.warning("[rental_performance] arb-alert tenant scan failed: %s", e)
    try:
        s = load_settings(tenant_id="")
        thr = (s.get(RENTAL_MARKET_ARB_SETTING) or "").strip()
        if thr and float(thr) > 0:
            out.append("")
    except Exception:
        pass
    return list(dict.fromkeys(out))


def market_overpay_enabled_tenants() -> List[str]:
    """Tenant ids that should be swept for market-overpay alerts.

    Same gating as pl_alert_enabled_tenants: only tenants with the threshold
    CONFIGURED (rental_market_overpay_pct > 0) AND MRR credentials get a
    sweep visit — never burns the MRR rate budget on 1000+ idle tenants.
    Default/operator tenant included when its GLOBAL setting is enabled."""
    out: List[str] = []
    try:
        _ensure_rig_settings_tables()
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT DISTINCT tenant_id, value FROM tenant_settings WHERE key=?",
                  (RENTAL_MARKET_OVERPAY_SETTING,))
        rows = c.fetchall()
        conn.close()
        for r in rows:
            try:
                thr = float((r["value"] or "").strip())
            except (TypeError, ValueError):
                continue
            if thr > 0 and mrr_credentials(tenant_id=r["tenant_id"])["api_key"]:
                out.append(r["tenant_id"])
    except Exception as e:
        log.warning("[rental_performance] overpay-alert tenant scan failed: %s", e)
    try:
        s = load_settings(tenant_id="")
        thr = (s.get(RENTAL_MARKET_OVERPAY_SETTING) or "").strip()
        if thr and float(thr) > 0 and mrr_credentials(tenant_id="")["api_key"]:
            out.append("")
    except Exception:
        pass
    return list(dict.fromkeys(out))


def _build_overpay_alert(provider: str, rental_id: Any, cost_sats_per_thh: float,
                         market_price: float, overpay_pct: float) -> Dict[str, Any]:
    """Alert payload: category rental_overpay — concise for webhook + push.
    CRIT when paying ≥3× the market (≥200% over), WARN otherwise."""
    severity = "CRIT" if overpay_pct >= 200.0 else "WARN"
    message = (
        f"Rental #{rental_id} ({provider.upper()}) pagou {overpay_pct:.0f}% acima "
        f"do mercado na compra — custo {cost_sats_per_thh:.0f} sats/TH·h vs "
        f"mercado {market_price:.0f} sats/TH·h"
    )[:280]
    return {
        "severity": severity,
        "category": "rental_overpay",
        "message": message,
        "rental_id": str(rental_id),
        "provider": provider,
        "overpay_pct": round(overpay_pct, 1),
    }


def evaluate_market_overpay_alerts(history: List[Dict],
                                   contracts: Optional[List[Dict]] = None,
                                   tenant_id: str = "", now: Optional[int] = None,
                                   extra: Optional[List[Dict]] = None) -> List[Dict[str, Any]]:
    """Rentals whose AGREED price per TH·h is ≥ X% above the market at the
    purchase time → per-tenant alerts (webhook + push via the shared
    dispatcher).

    ``history`` = ended rentals (windowed by end); ``extra`` = ACTIVE rentals
    (windowed by START — the 'na hora da compra' freshness: a rental bought
    an hour ago alerts now, not when it ends weeks later). The agreed price
    (paid ÷ advertised TH × hours) is delivery-independent, so active and
    ended rentals are judged identically.

    Market reference: nearest hashrate_market_history snapshot to the rental
    start (±3 days), live quote only as fallback. Dedup: once per rental EVER
    (persisted, provider tag 'mrr_overpay' — independent of the P/L slot).
    Braiins contracts are skipped (the list payload lacks the advertised
    TH·h needed for the agreed price)."""
    s = load_settings(tenant_id=tenant_id)
    raw = (s.get(RENTAL_MARKET_OVERPAY_SETTING) or "").strip()
    try:
        threshold = float(raw)
    except (TypeError, ValueError):
        return []
    if not raw or threshold <= 0:
        return []  # disabled / non-sensical threshold
    window_h = 48.0
    try:
        window_h = float((s.get(RENTAL_PL_WINDOW_SETTING) or "48") or 48)
    except (TypeError, ValueError):
        window_h = 48.0
    if window_h <= 0:
        window_h = 48.0
    now = int(now or time.time())

    _prune_pl_alerts()
    live_market: Optional[Dict] = None  # lazily fetched once (cached fetcher)

    def _live_price() -> Optional[float]:
        nonlocal live_market
        if live_market is None:
            live_market = fetch_market_reference()
        return live_market.get("price_sats_per_thh") if live_market.get("available") else None

    out: List[Dict[str, Any]] = []
    rows = list(history or []) + list(extra or [])
    seen: set = set()
    for r in rows:
        rid = r.get("id")
        if rid is None or str(rid) in seen:
            continue
        seen.add(str(rid))
        end_u = _num(r.get("end_unix"))
        start_u = _num(r.get("start_unix"))
        if r.get("ended"):
            if end_u is not None and (now - end_u) > window_h * 3600.0:
                continue
        else:
            # Active rental: only when BOUGHT within the window (fresh signal).
            if start_u is None or (now - start_u) > window_h * 3600.0:
                continue
        if _pl_alert_fired(tenant_id, "mrr_overpay", str(rid)):
            continue

        paid = _num(r.get("price_paid_btc"))
        adv_th = _num(r.get("hashrate_advertised_th"))
        length_h = _num(r.get("length_hours"))
        if paid is None or not adv_th or not length_h or length_h <= 0:
            continue  # can't derive the agreed price — never guess
        paid_sats = paid * 1e8
        agreed_thh = adv_th * length_h
        if agreed_thh <= 0:
            continue
        cost_sats_per_thh = paid_sats / agreed_thh
        # Market at purchase: nearest historical snapshot (cached per day),
        # live quote ONLY as last resort — lazy so a covered day never hits
        # the network per rental.
        _ts = _parse_start_ts(r.get("start"))
        if _ts is None:
            _ts = _parse_start_ts(r.get("end"))
        market_price = _historical_market_sats_per_thh(_ts)
        if market_price is None:
            market_price = _live_price()
        if not market_price:
            continue  # no market reference at all → honest skip
        overpay_pct = (cost_sats_per_thh / market_price - 1.0) * 100.0
        if overpay_pct < threshold:
            continue
        # Atomic claim: only the winner of the INSERT fires (race-safe dedup).
        if not _mark_pl_alert_fired(tenant_id, "mrr_overpay", str(rid),
                                    round(overpay_pct, 1)):
            continue
        out.append(_build_overpay_alert("mrr", rid, cost_sats_per_thh,
                                        market_price, overpay_pct))
    return out


# ── Arbitrage-opportunity alerts (market vs the tenant's own avg cost) ─────

def _build_arb_alert(avg_cost: float, market_price: float,
                     discount_pct: float) -> Dict[str, Any]:
    """Opportunity payload: category market_arb — GOLD when the discount is
    extreme (≥50%), WARN otherwise. Concise for webhook + push."""
    severity = "GOLD" if discount_pct >= 50.0 else "WARN"
    message = (
        f"ARBITRAGEM: mercado a {market_price:.0f} sats/TH·h — {discount_pct:.0f}% "
        f"abaixo do seu custo médio ({avg_cost:.0f} sats/TH·h). Janela de compra!"
    )[:280]
    return {
        "severity": severity,
        "category": "market_arb",
        "message": message,
        "rental_id": "",
        "provider": "mrr",
        "avg_cost_sats_per_thh": round(avg_cost, 1),
        "market_price_sats_per_thh": round(market_price, 1),
        "discount_pct": round(discount_pct, 1),
    }


def evaluate_market_arb_alerts(tenant_id: str = "",
                               now: Optional[int] = None) -> List[Dict[str, Any]]:
    """Arbitrage opportunity: when the CURRENT market price (cheapest quote)
    is ≥ X% BELOW the tenant's own historical average cost per TH·h → fire a
    per-tenant webhook/push ('compre agora' window).

    Local-first and provider-free: the baseline is the tenant's OWN
    rental_history (bucket 'renter'), and the market price comes from the
    local hashrate_market_history table (last 12h; ±3d fallback; live quote
    as last resort). So this family needs NO MRR credentials — gating is
    purely the threshold setting.

    Dedup: ONE alert per cooldown window (rental_market_arb_cooldown_hours,
    default 24h) — a persistently cheap market repeats the signal daily
    instead of spamming every sweep. Persisted in the shared rental_pl_alerts
    table with provider tag 'mrr_arb' and a bucket key as rental_id.
    """
    s = load_settings(tenant_id=tenant_id)
    raw = (s.get(RENTAL_MARKET_ARB_SETTING) or "").strip()
    try:
        threshold = float(raw)
    except (TypeError, ValueError):
        return []
    if not raw or threshold <= 0:
        return []  # disabled / non-sensical threshold
    cooldown_h = 24.0
    try:
        cooldown_h = float((s.get(RENTAL_MARKET_ARB_COOLDOWN_SETTING) or "24") or 24)
    except (TypeError, ValueError):
        cooldown_h = 24.0
    if cooldown_h <= 0:
        cooldown_h = 24.0
    # Clamp to the dedup-table prune horizon so a very long cooldown never
    # outlives its own dedup row (prune would delete the bucket mid-window
    # and re-fire the alert).
    cooldown_h = min(cooldown_h, RENTAL_PL_ALERT_PRUNE_DAYS * 24.0)
    now = int(now or time.time())

    _prune_pl_alerts()
    # Baseline: the tenant's own historical average cost (never a fabricated
    # number — no history = honest skip).
    avg_cost = _tenant_avg_cost_sats_per_thh(tenant_id)
    if not avg_cost or avg_cost <= 0:
        return []
    market_price = _recent_market_sats_per_thh(now)
    if not market_price or market_price <= 0:
        return []  # no market reference at all → honest skip
    discount_pct = (1.0 - market_price / avg_cost) * 100.0
    if discount_pct < threshold:
        return []  # market not cheap enough vs MY costs
    # Dedup: one alert per cooldown bucket (atomic claim, race-safe).
    bucket = int(now // (cooldown_h * 3600.0))
    dedup_id = f"arb-{bucket}"
    if not _mark_pl_alert_fired(tenant_id, "mrr_arb", dedup_id,
                                round(discount_pct, 1)):
        return []
    return [_build_arb_alert(avg_cost, market_price, discount_pct)]


# ── Local rental-history persistence ────────────────────────────────────────
# The same-rig track record used to re-fetch the whole MRR history list on
# EVERY detail click (slow + rate-limit-prone with 1000+ users). The panel's
# list fetch now ingests every bucket into a local table, and analyze_rig
# reads LOCAL FIRST — instant track records that survive provider outages.

HISTORY_LOCAL_FIRST_ENV = "RENTAL_HISTORY_LOCAL_FIRST"


def _ensure_history_table() -> None:
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS rental_history (
            tenant_id TEXT NOT NULL DEFAULT '',
            provider TEXT NOT NULL DEFAULT 'mrr',
            bucket TEXT NOT NULL DEFAULT 'renter',
            rental_id TEXT NOT NULL,
            rig_id TEXT NOT NULL DEFAULT '',
            rig_name TEXT NOT NULL DEFAULT '',
            start TEXT, end TEXT,
            percent REAL, avg_th REAL, advertised_th REAL,
            cost_sats_per_thh REAL, length_hours REAL,
            delivered_thh REAL, paid_sats REAL,
            network_hashrate_hs REAL,
            created_ts INTEGER,
            PRIMARY KEY (tenant_id, provider, rental_id)
        )""")
        # Migration: tables created before the owner/renter split lack the
        # bucket column — legacy rows default to 'renter' (behavior preserved;
        # new ingests mark owner rentals correctly).
        try:
            cols = {row[1] for row in c.execute("PRAGMA table_info(rental_history)").fetchall()}
            if "bucket" not in cols:
                c.execute("ALTER TABLE rental_history ADD COLUMN bucket TEXT NOT NULL DEFAULT 'renter'")
            # Migration: tables created before the historical-P/L fix lack
            # network_hashrate_hs — legacy rows keep NULL and self-heal on
            # the next ingest (ON CONFLICT updates it), and every consumer
            # falls back to the snapshots table / current hashrate meanwhile.
            if "network_hashrate_hs" not in cols:
                c.execute("ALTER TABLE rental_history ADD COLUMN network_hashrate_hs REAL")
        except Exception:
            pass
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("[rental_performance] history table ensure failed: %s", e)


def _rental_to_history_row(r: Dict[str, Any], provider: str = "mrr",
                           bucket: str = "renter") -> Dict[str, Any]:
    """Normalized rental dict → rental_history row (shared by ingest + fetch).

    ``bucket`` separates RENTER spend (rentals the operator paid for) from
    OWNER income (rigs leased OUT) — analytics that answer 'how much did I
    spend?' must never count money received."""
    rig = r.get("rig") or {}
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
    # Historical-P/L fix: persist the network hashrate OBSERVED at the rental's
    # time (nearest snapshot, fallback current) so past rentals are priced
    # against the network they actually mined in — not today's hashrate.
    _nhr = _resolve_network_hashrate_for_rental(r.get("start"), r.get("end"))
    return {
        "provider": provider,
        "bucket": bucket,
        "rental_id": str(r.get("id") or ""),
        "rig_id": str(rig.get("id") or "") if rig.get("id") is not None else "",
        "rig_name": str(rig.get("name") or ""),
        "start": r.get("start"),
        "end": r.get("end"),
        "percent": round(pct, 2) if pct is not None else None,
        "avg_th": avg_th,
        "advertised_th": adv_th,
        "cost_sats_per_thh": round(cost, 2) if cost is not None else None,
        "length_hours": length_h,
        "delivered_thh": delivered_thh,
        "paid_sats": paid_sats,
        "network_hashrate_hs": _nhr if (_nhr and _nhr > 0) else None,
    }


def save_rental_history(rows: List[Dict], tenant_id: str = "") -> bool:
    """Upsert rental rows into the local history (per tenant, per provider)."""
    if not rows:
        return False
    _ensure_history_table()
    ts = int(time.time())
    conn = get_db()
    c = conn.cursor()
    try:
        for r in rows:
            c.execute(
                """INSERT INTO rental_history
                   (tenant_id, provider, bucket, rental_id, rig_id, rig_name,
                    start, end, percent, avg_th, advertised_th,
                    cost_sats_per_thh, length_hours, delivered_thh,
                    paid_sats, network_hashrate_hs, created_ts)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(tenant_id, provider, rental_id) DO UPDATE SET
                     bucket=excluded.bucket,  -- self-heals legacy owner rows mislabeled 'renter'
                     rig_id=excluded.rig_id, rig_name=excluded.rig_name,
                     start=excluded.start, end=excluded.end,
                     percent=excluded.percent, avg_th=excluded.avg_th,
                     advertised_th=excluded.advertised_th,
                     cost_sats_per_thh=excluded.cost_sats_per_thh,
                     length_hours=excluded.length_hours,
                     delivered_thh=excluded.delivered_thh,
                     paid_sats=excluded.paid_sats,
                     network_hashrate_hs=excluded.network_hashrate_hs,
                     created_ts=excluded.created_ts""",
                (tenant_id or "", r["provider"], r.get("bucket", "renter"),
                 r["rental_id"], r["rig_id"], r["rig_name"], r.get("start"),
                 r.get("end"), r["percent"], r["avg_th"], r["advertised_th"],
                 r.get("cost_sats_per_thh"), r.get("length_hours"),
                 r.get("delivered_thh"), r.get("paid_sats"),
                 r.get("network_hashrate_hs"), ts),
            )
        conn.commit()
        return True
    except Exception as e:
        log.warning("[rental_performance] history save failed: %s", e)
        return False
    finally:
        conn.close()


def get_local_rig_history(rig_id: Any = None, rig_name: str = "",
                          exclude_rental_id: Any = None,
                          tenant_id: str = "") -> List[Dict[str, Any]]:
    """Same-rig track record from the LOCAL table (instant, no provider call).
    Shape matches the remote fetcher's output ({id, start, percent, avg_th,
    advertised_th, cost_sats_per_thh, length_hours})."""
    if not (rig_id or rig_name):
        return []
    try:
        conn = get_db()
        c = conn.cursor()
        q = "SELECT * FROM rental_history WHERE tenant_id=?"
        args: List[Any] = [tenant_id or ""]
        # Renter-only: the track record answers 'should I rent this rig again?'
        # — owner rows (my own rig leased out) are income-side and must not
        # pollute it. Matches the remote fallback (rtype='renter').
        q += " AND bucket='renter'"
        wanted_id = str(rig_id) if rig_id is not None else None
        wanted_name = str(rig_name or "").strip().lower()
        if wanted_id:
            q += " AND rig_id=?"
            args.append(wanted_id)
        elif wanted_name:
            q += " AND LOWER(rig_name)=LOWER(?)"
            args.append(wanted_name)
        if exclude_rental_id is not None:
            q += " AND rental_id!=?"
            args.append(str(exclude_rental_id))
        q += " ORDER BY COALESCE(start,'') DESC LIMIT 100"
        c.execute(q, args)
        rows = c.fetchall()
        conn.close()
    except Exception:
        return []  # table missing / any SQL issue → fall back to remote
    return [{
        "id": row["rental_id"], "start": row["start"],
        "percent": row["percent"], "avg_th": row["avg_th"],
        "advertised_th": row["advertised_th"],
        "cost_sats_per_thh": row["cost_sats_per_thh"],
        "length_hours": row["length_hours"],
    } for row in rows]


def ingest_rentals(active: List[Dict], history: List[Dict], owner: List[Dict],
                   contracts: List[Dict], tenant_id: str = "") -> bool:
    """Persist every bucket from the panel list fetch into local history.
    Called by /api/rentals once per fetch — the same-rig track record then
    builds up with zero extra provider calls on detail clicks."""
    rows: List[Dict] = []
    # Owner rentals are the operator's rigs leased OUT — money RECEIVED. They
    # must never be counted as spend by the renter analytics (portfolio
    # series, worst-rigs, heatmap), so the bucket column separates them.
    for _bname, _bucket in (("renter", active), ("renter", history),
                            ("owner", owner)):
        for r in _bucket:
            if isinstance(r, dict):
                rows.append(_rental_to_history_row(r, provider="mrr", bucket=_bname))
    for c in contracts or []:
        speed_limit_ph = c.get("speed_limit_ph")
        limit_th = (speed_limit_ph * PH_TO_TH) if speed_limit_ph is not None else None
        rows.append({
            "provider": "braiins",
            "rental_id": str(c.get("id") or ""),
            "rig_id": "", "rig_name": "Braiins contract",
            "start": c.get("started_at"), "end": c.get("ended_at"),
            "percent": None, "avg_th": limit_th, "advertised_th": limit_th,
            "cost_sats_per_thh": None, "length_hours": None,
            "delivered_thh": None, "paid_sats": c.get("amount_sat"),
        })
    return save_rental_history(rows, tenant_id=tenant_id)


def _parse_start_ts(value) -> Optional[float]:
    """Best-effort unix ts from the varied date strings in rental_history
    (MRR 'YYYY-MM-DD HH:MM:SS UTC', RFC3339, or raw unix). None when
    nothing parses. Shared by the rig-history recency gate and the
    portfolio series bucketer — one parser, no drift."""
    import datetime as _dt
    s = str(value or "").strip()
    if not s:
        return None
    # RFC3339 ('T' separator, optional Z/fractional seconds — Braiins) plus
    # the space-separated MRR formats. All treated as UTC.
    for fmt in ("%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
                "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            # MRR/RFC3339 strings are UTC — parse as UTC-aware so weekly
            # bucketing never shifts by the server's local offset.
            return _dt.datetime.strptime(s, fmt).replace(tzinfo=_dt.timezone.utc).timestamp()
        except ValueError:
            continue
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


# ── Historical network hashrate (exact past P/L) ───────────────────────────
# The portfolio P/L used the CURRENT network hashrate for past rentals,
# which distorts historical economics (the network grows each epoch). The
# snapshots table records the OBSERVED network hashrate per poll — the
# nearest snapshot to each rental's start is the exact historical figure.
# Rows persist it at ingest (network_hashrate_hs); legacy rows self-heal on
# the next ingest; live-fetch consumers resolve on demand with a per-day
# cache so the panel never pays one query per rental.

# Nearest-snapshot search window around the rental start (±3 days). Network
# hashrate moves on the ~2-week difficulty epoch scale, so a snapshot within
# days is far more accurate than today's value.
_SNAPSHOT_HR_WINDOW_S = 3 * 86400
_snapshot_hr_cache: Dict[int, Optional[float]] = {}
_snapshot_index_ensured = False


def _ensure_snapshot_index() -> None:
    """Idempotent index on snapshots(ts) — the nearest-hashrate lookup does a
    range scan per distinct day; on a long-polled table (100k+ rows) that is
    a full scan without it. Once per process, guarded."""
    global _snapshot_index_ensured
    if _snapshot_index_ensured:
        return
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON snapshots(ts)")
        conn.commit()
        conn.close()
        _snapshot_index_ensured = True
    except Exception:
        pass


def _resolve_network_hashrate_for_ts(ts: Optional[float]) -> Optional[float]:
    """Observed network hashrate (H/s) nearest to ``ts`` from the snapshots
    table, within ±3 days. None when no snapshot covers that window (callers
    then fall back to the current hashrate). Cached per UTC day — only
    POSITIVE results are cached, so a day that gains snapshot coverage later
    (e.g. after a remote-backup restore) is re-resolved, never pinned to the
    old fallback."""
    if not ts:
        return None
    import datetime as _dt
    day = int(_dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).strftime("%Y%m%d"))
    if day in _snapshot_hr_cache:
        return _snapshot_hr_cache[day]
    _ensure_snapshot_index()
    val: Optional[float] = None
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT network_hashrate FROM snapshots "
            "WHERE ts BETWEEN ? AND ? AND network_hashrate > 0 "
            "ORDER BY ABS(ts - ?) LIMIT 1",
            (int(ts) - _SNAPSHOT_HR_WINDOW_S, int(ts) + _SNAPSHOT_HR_WINDOW_S, int(ts)),
        )
        row = c.fetchone()
        conn.close()
        if row and row[0]:
            val = float(row[0])
    except Exception as e:
        log.warning("[rental_performance] snapshot hashrate lookup failed: %s", e)
    if val and val > 0:
        _snapshot_hr_cache[day] = val
    return val


def _resolve_network_hashrate_for_rental(start_value, end_value=None,
                                         current_fallback: bool = True) -> Optional[float]:
    """Network hashrate for a rental's period: nearest snapshot to its START
    (fallback to END when the start is missing), else the current hashrate.
    Returns None only when nothing is available at all."""
    ts = _parse_start_ts(start_value)
    if ts is None:
        ts = _parse_start_ts(end_value)
    hs = _resolve_network_hashrate_for_ts(ts)
    if hs is not None and hs > 0:
        return hs
    if current_fallback:
        return _network_hashrate_hs()
    return None


def _row_get(row, key: str, default=None):
    """Read a column from a dict OR a sqlite3.Row (both support row[key];
    only dicts have .get). Consumers pass either shape interchangeably."""
    try:
        if hasattr(row, "keys"):
            return row[key]
        return getattr(row, key, default)
    except (KeyError, IndexError, TypeError):
        return default


def _rental_network_hashrate(row) -> Optional[float]:
    """Best network hashrate for a local rental_history row: the persisted
    ingest-time value, else the nearest snapshot, else the current hashrate.
    Returns None only when nothing is known (yield then shows '—')."""
    v = _to_float(_row_get(row, "network_hashrate_hs"))
    if v and v > 0:
        return v
    return _resolve_network_hashrate_for_rental(
        _row_get(row, "start"), _row_get(row, "end"))


def _series_bucket_key(dt, bucket: str) -> str:
    """Bucket label shared by the portfolio series and its drill-down: ISO
    week ("2026-W30") or calendar month ("2026-07")."""
    if bucket == "week":
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    return f"{dt.year:04d}-{dt.month:02d}"


def series_bucket_rentals(tenant_id: str = "", bucket: str = "week",
                          label: str = "") -> List[Dict[str, Any]]:
    """Drill-down for the portfolio chart: every LOCAL rental_history row that
    falls in the given bucket label (e.g. "2026-W30" or "2026-07").

    Zero provider calls — pure local table read, so clicking a bar in the
    chart is instant. Returns rows with provider/rental_id/rig/spend/delivery
    so the frontend can list 'which rentals made up that bar' and deep-link
    to the provider or the rental detail.
    """
    bucket = bucket if bucket in ("week", "month") else "week"
    import datetime as _dt
    out: List[Dict[str, Any]] = []
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM rental_history WHERE tenant_id=? AND bucket='renter'", (tenant_id or "",))
        rows = c.fetchall()
        conn.close()
    except Exception as e:
        log.warning("[rental_performance] series drill-down failed: %s", e)
        return out
    for r in rows:
        ts = _parse_start_ts(r["start"])
        if ts is None:
            if not r["created_ts"]:
                continue
            ts = float(r["created_ts"])
        dt = _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc)
        if _series_bucket_key(dt, bucket) != label:
            continue
        paid = _num(r["paid_sats"])
        # Historical-P/L fix: price this past rental against the network
        # hashrate OBSERVED at its time (persisted at ingest, snapshot fallback).
        pl = compute_rental_pl(_num(r["delivered_thh"]), paid,
                               network_hashrate_hs=_rental_network_hashrate(r))
        nhr = _to_float(_row_get(r, "network_hashrate_hs"))
        out.append({
            "provider": r["provider"],
            "rental_id": r["rental_id"],
            "rig_id": r["rig_id"],
            "rig_name": r["rig_name"],
            "start": r["start"],
            "spent_sats": round(paid) if paid is not None else None,
            "delivered_thh": round(_num(r["delivered_thh"]), 1) if _num(r["delivered_thh"]) else None,
            "network_hashrate_hs": round(nhr) if (nhr and nhr > 0) else None,
            "pl_sats": round(pl.get("pl_sats"), 1) if pl.get("pl_sats") is not None else None,
        })
    out.sort(key=lambda x: x["start"] or "")
    return out


def compute_portfolio_series(tenant_id: str = "", bucket: str = "week",
                             created_ts_fallback: bool = True) -> Dict[str, Any]:
    """Portfolio time series (spent + estimated P/L) per week/month, straight
    from the LOCAL rental_history table — no provider calls.

    Methodology (CFO read):
      - each row = one rental/bid the tenant already fetched (ingested by
        /api/rentals); spent = paid_sats, delivered = delivered_thh;
      - P/L per rental uses the SAME economic math as the detail banner
        (expected gross yield × delivered TH·h − paid) — now priced against
        the network hashrate OBSERVED at the rental's time (persisted at
        ingest; nearest-snapshot fallback; current hashrate only as last
        resort), so PAST weeks no longer move when today's network grows.
        Still labeled ESTIMATE (gross, pre-pool-fee, reward at the halving
        epoch) so the chart never overstates;
      - buckets by ISO week (bucket='week') or calendar month (bucket='month')
        from the row's start date (created_ts fallback for unparseable rows);
      - cum_pl_sats = running cumulative so the operator sees the trend
        direction at a glance.

    Returns {"bucket", "estimate": True, "points": [{label, spent_sats,
    delivered_thh, pl_sats, cum_pl_sats, rentals, rental_ids}],
    "totals": {...}} — rental_ids powers the chart drill-down.
    """
    bucket = bucket if bucket in ("week", "month") else "week"
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM rental_history WHERE tenant_id=? AND bucket='renter'", (tenant_id or "",))
        rows = c.fetchall()
        conn.close()
    except Exception as e:
        log.warning("[rental_performance] portfolio series failed: %s", e)
        return {"bucket": bucket, "estimate": True, "points": [], "totals": {}}

    import datetime as _dt
    agg: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for r in rows:
        ts = _parse_start_ts(r["start"])
        if ts is None:
            if not created_ts_fallback or not r["created_ts"]:
                continue
            ts = float(r["created_ts"])
        dt = _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc)
        key = _series_bucket_key(dt, bucket)
        if key not in agg:
            # pl_known tracks whether ANY rental in the bucket had computable
            # P/L — an all-unknown bucket must render null (never a flat 0
            # that reads as 'no loss' on a cold box).
            agg[key] = {"label": key, "spent_sats": 0.0, "delivered_thh": 0.0,
                        "pl_sats": 0.0, "pl_known": 0, "rentals": 0,
                        "rental_ids": []}
            order.append(key)
        paid = _num(r["paid_sats"])
        if paid is not None:
            agg[key]["spent_sats"] += paid
        # Historical-P/L fix: price each past rental against the network
        # hashrate observed at its time (persisted/snapshot/current fallback).
        pl = compute_rental_pl(_num(r["delivered_thh"]), paid,
                               network_hashrate_hs=_rental_network_hashrate(r))
        if pl.get("pl_sats") is not None:
            agg[key]["pl_sats"] += pl["pl_sats"]
            agg[key]["pl_known"] += 1
        if _num(r["delivered_thh"]):
            agg[key]["delivered_thh"] += _num(r["delivered_thh"])
        agg[key]["rentals"] += 1
        agg[key]["rental_ids"].append(str(r["rental_id"]))

    points = []
    cum = 0.0
    cum_known = True
    for key in sorted(order):
        g = agg[key]
        if g["pl_known"]:
            cum += g["pl_sats"]
        else:
            cum_known = False  # once unknown, cumulative is unknown too
        points.append({
            "label": g["label"],
            "spent_sats": round(g["spent_sats"]),
            "delivered_thh": round(g["delivered_thh"], 1) if g["delivered_thh"] else None,
            # None (not 0.0) when nothing computable — the UI shows '—'.
            "pl_sats": round(g["pl_sats"], 1) if g["pl_known"] else None,
            "cum_pl_sats": round(cum, 1) if cum_known else None,
            "rentals": g["rentals"],
            # Click-first drill-down: the ids of every rental in the bucket so
            # the chart can open the exact list behind a bar/week.
            "rental_ids": g["rental_ids"][:300],
        })
    known_totals = [g for g in agg.values() if g["pl_known"]]
    return {
        "bucket": bucket,
        "estimate": True,  # P/L uses the CURRENT network hashrate — honest label
        "points": points,
        "totals": {
            "spent_sats": round(sum(g["spent_sats"] for g in agg.values())),
            "pl_sats": round(sum(g["pl_sats"] for g in known_totals), 1) if known_totals else None,
            "rentals": sum(g["rentals"] for g in agg.values()),
        },
    }


def compute_portfolio_summary(active: List[Dict], history: List[Dict],
                              owner: List[Dict], contracts: List[Dict]) -> Dict[str, Any]:
    """Aggregate portfolio analytics for the RENTALS panel top strip.

    Spend side = MRR renter (active + history). Income side = MRR owner
    (rigs leased out). Every metric is null-safe (honest '—').
    Returns {"spend": {...}, "income": {...}, "split": {...}, "counts": {...}}
    """
    def _agg(buckets: List[List[Dict]]) -> Dict[str, Any]:
        n = 0
        spent = 0.0
        delivered = 0.0
        weighted_paid = 0.0
        pcts: List[float] = []
        for bucket in buckets:
            for r in bucket:
                n += 1
                paid = r.get("price_paid_btc")
                paid_sats = (float(paid) * 1e8) if paid is not None else None
                if paid_sats is not None:
                    spent += paid_sats
                avg_th = r.get("hashrate_average_th")
                lenh = r.get("length_hours")
                d = (float(avg_th) * float(lenh)) if (avg_th is not None and lenh) else None
                if d:
                    delivered += d
                    if paid_sats is not None:
                        weighted_paid += paid_sats
                p = r.get("hashrate_percent")
                if p is not None:
                    pcts.append(float(p))
        return {
            "count": n,
            "spent_sats": round(spent) if n else 0,
            "delivered_thh": round(delivered, 1) if delivered else None,
            # Cost weighted by delivered TH·h (an honest blended rate — a
            # cheap short rental must not skew the average).
            "avg_cost_sats_per_thh": round(weighted_paid / delivered, 2) if delivered else None,
            "avg_delivery_pct": round(sum(pcts) / len(pcts), 1) if pcts else None,
        }

    return {
        "spend": _agg([active, history]),
        "income": _agg([owner]),
        "split": {"mrr": len(active) + len(history) + len(owner),
                  "braiins": len(contracts or [])},
        "counts": {"active": len(active), "history": len(history),
                   "owner": len(owner), "contracts": len(contracts or [])},
    }


# ── CFO recommendation engine: "where to rent again" ───────────────────────
# The single decision the operator makes every time: WHICH rig/provider to
# rent next. Builds on the local track record (reliability = trust score)
# × the live market (price quality = avg cost vs cheapest today) and returns
# a ranked shortlist + an avoid list. Honest: needs a track record — a rig
# with zero samples never appears in "top".


def build_rental_recommendations(tenant_id: str = "",
                                 top_n: int = 3) -> Dict[str, Any]:
    """Rank MRR rigs worth re-renting from the LOCAL track record.

    Score = 0.6 × reliability (trust.score 0-100, median-based) +
            0.4 × price quality (avg cost vs live market, capped at 1.5×
            cheaper = 100). Excludes manual + auto blacklists and grade F.

    Returns {"top": [rig...], "avoid_count": n, "tracked": n,
             "market": {...}} — empty top when no track record exists yet.
    """
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT rig_id, rig_name, percent, cost_sats_per_thh, start "
            "FROM rental_history WHERE tenant_id=? AND provider='mrr' AND rig_id!='' "
            "AND bucket='renter'",
            (tenant_id or "",))
        rows = c.fetchall()
        conn.close()
    except Exception:
        return {"top": [], "avoid_count": 0, "tracked": 0,
                "market": {"available": False}}

    by_rig: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        rid = r["rig_id"]
        b = by_rig.setdefault(rid, {"name": r["rig_name"] or "",
                                    "samples": [], "costs": [], "starts": []})
        if r["percent"] is not None:
            # (start, pct) pairs — SQL has no ORDER BY, so the recent-vs-
            # older trend MUST sort chronologically (insertion order is NOT
            # rental order: new rentals append at the end of the table).
            b["samples"].append((str(r["start"] or ""), r["percent"]))
        if r["cost_sats_per_thh"] is not None:
            b["costs"].append(r["cost_sats_per_thh"])
        if r["start"]:
            b["starts"].append(str(r["start"]))

    manual = set(get_rig_blacklist(tenant_id=tenant_id))
    auto = set(get_auto_blacklist(tenant_id=tenant_id))
    market = fetch_market_reference()
    mkt = market.get("price_sats_per_thh") if market.get("available") else None

    top: List[Dict[str, Any]] = []
    avoid_count = 0
    for rid, b in by_rig.items():
        # Chronological order for the trend (see the note at collection).
        samples = sorted(b["samples"], key=lambda x: x[0])
        pcts = [p for _, p in samples]
        trust = compute_rig_trust_score(
            [{"percent": p} for p in pcts])
        if trust.get("samples", 0) < 1:
            continue
        if rid in manual or rid in auto:
            continue
        if trust.get("grade") == "F":
            avoid_count += 1
            continue
        avg_cost = (sum(b["costs"]) / len(b["costs"])) if b["costs"] else None
        price_q = 60.0  # neutral when no cost data
        vs_mkt = None
        if avg_cost and mkt:
            vs_mkt = (avg_cost / mkt - 1.0) * 100.0
            price_q = min(100.0, max(0.0, 100.0 * mkt / avg_cost))
        rel = trust.get("score") or 0.0
        score = round(0.6 * rel + 0.4 * price_q, 1)
        starts = sorted(b["starts"])
        trend = None
        if len(pcts) >= 4:
            recent = sum(pcts[-3:]) / 3.0          # NEWEST 3
            older = sum(pcts[:-3]) / (len(pcts) - 3)
            trend = round(recent - older, 1)
        top.append({
            "rig_id": rid,
            "name": b["name"],
            "grade": trust.get("grade"),
            "score": score,
            "median_pct": trust.get("median_pct"),
            "worst_pct": trust.get("worst_pct"),
            "samples": trust.get("samples"),
            "avg_cost_sats_per_thh": round(avg_cost, 2) if avg_cost else None,
            "vs_market_pct": round(vs_mkt, 1) if vs_mkt is not None else None,
            "trend_pct": trend,
            "last_rental": starts[-1] if starts else None,
        })
    top.sort(key=lambda x: x["score"], reverse=True)
    return {"top": top[:top_n], "avoid_count": avoid_count,
            "tracked": len(by_rig), "market": market}


def fetch_market_trend(days: int = 30) -> Dict[str, Any]:
    """Daily CHEAPEST SHA-256 market price (sats/TH·h) over the last N days
    from hashrate_market_history + a summary (avg/current/vs-avg). Empty
    points when the market snapshot was never persisted (quiet box) — the
    UI hides the timing card instead of showing a fabricated line."""
    try:
        conn = get_db()
        c = conn.cursor()
        # The history table grows one row per offer per poll cycle — the
        # (algorithm, ts) index keeps the 30-day range scan cheap on every
        # panel load (CREATE IF NOT EXISTS is a no-op after the first run).
        try:
            c.execute("CREATE INDEX IF NOT EXISTS idx_mkt_hist_alg_ts "
                      "ON hashrate_market_history(algorithm, ts)")
            conn.commit()
        except Exception:
            pass
        c.execute(
            """SELECT date(ts,'unixepoch') AS day, MIN(price_per_th_day) AS best_btc
               FROM hashrate_market_history
               WHERE algorithm='sha256' AND price_per_th_day >= ? AND ts >= ?
               GROUP BY day ORDER BY day ASC""",
            (_MIN_PLAUSIBLE_PRICE, int(time.time()) - days * 86400))
        rows = c.fetchall()
        conn.close()
    except Exception as e:
        log.warning("[rental_performance] market trend failed: %s", e)
        return {"points": [], "summary": None}
    if not rows:
        return {"points": [], "summary": None}
    pts = [{"day": r["day"],
            "sats_per_thh": round(r["best_btc"] * 1e8 / 24.0, 2)}
           for r in rows]
    vals = [p["sats_per_thh"] for p in pts]
    avg = sum(vals) / len(vals)
    cur = vals[-1]
    return {
        "points": pts,
        "summary": {
            "days": len(pts),
            "avg_sats_per_thh": round(avg, 2),
            "current_sats_per_thh": cur,
            "min_sats_per_thh": min(vals),
            "max_sats_per_thh": max(vals),
            "vs_avg_pct": round((cur / avg - 1.0) * 100.0, 1) if avg else None,
        },
    }


def fetch_rig_performance_history(
    rig_id: Any = None,
    rig_name: str = "",
    exclude_rental_id: Any = None,
    limit: int = 100,
    tenant_id: str = "",
) -> List[Dict[str, Any]]:
    """Past MRR rentals of the SAME rig → track record for the detail panel.

    Matches by rig.id (authoritative) or rig.name (fallback), excludes the
    rental currently being viewed, newest first. Each entry:
      {id, start, percent, avg_th, advertised_th, cost_sats_per_thh,
       length_hours}
    Enables the "histórico de % por rig" view: how THIS rig delivered on
    previous rentals before deciding where to rent again.

    LOCAL-FIRST: the /api/rentals list fetch ingests every bucket into the
    local rental_history table, so the same-rig record is served from SQLite
    instantly — the MRR history API is only hit when the local table has no
    rows for this rig yet (set RENTAL_HISTORY_LOCAL_FIRST=0 to force remote
    for tests/debugging).
    """
    if not (rig_id or rig_name):
        return []
    wanted_id = str(rig_id) if rig_id is not None else None
    wanted_name = str(rig_name or "").strip().lower()

    if os.environ.get(HISTORY_LOCAL_FIRST_ENV, "1") != "0":
        local = get_local_rig_history(wanted_id, wanted_name,
                                      exclude_rental_id=exclude_rental_id,
                                      tenant_id=tenant_id)
        if local:
            return local

    listing = fetch_mrr_rentals(rtype="renter", history=True, limit=limit,
                                tenant_id=tenant_id)
    if not listing.get("success"):
        return []
    rows = [_rental_to_history_row(r, provider="mrr")
            for r in listing.get("rentals", []) if isinstance(r, dict)]
    keep = []
    for row in rows:
        if wanted_id and row["rig_id"] and row["rig_id"] == wanted_id:
            pass
        elif wanted_name and row["rig_name"].strip().lower() == wanted_name:
            pass
        else:
            continue
        if exclude_rental_id is not None and row["rental_id"] == str(exclude_rental_id):
            continue
        keep.append(row)
    if keep:
        save_rental_history(keep, tenant_id=tenant_id)
    out: List[Dict[str, Any]] = [{
        "id": row["rental_id"], "start": row["start"],
        "percent": row["percent"], "avg_th": row["avg_th"],
        "advertised_th": row["advertised_th"],
        "cost_sats_per_thh": row["cost_sats_per_thh"],
        "length_hours": row["length_hours"],
    } for row in keep]
    out.sort(key=lambda x: str(x.get("start") or ""), reverse=True)
    return out


def analyze_rig(rig_id: Any = None, rig_name: str = "",
                exclude_rental_id: Any = None, tenant_id: str = "") -> Dict[str, Any]:
    """One-call rig intelligence for the detail panel.

    Combines the same-rig track record, the computed Trust Score (grade A-F),
    the manual blacklist state and a spend/consistency summary — so the
    frontend renders the full "should I rent this rig again?" verdict with a
    single endpoint instead of re-assembling fragments.

    Returns:
      {"history": [...], "trust": {...}, "blacklisted": bool,
       "summary": {rentals, avg_pct, cost_avg_sats_thh, trend_pct}}
    """
    history = fetch_rig_performance_history(
        rig_id, rig_name, exclude_rental_id=exclude_rental_id, tenant_id=tenant_id)
    trust = compute_rig_trust_score(history)
    blacklisted = is_rig_blacklisted(rig_id, tenant_id=tenant_id)
    auto_blacklisted = is_rig_auto_blacklisted(rig_id, tenant_id=tenant_id)

    # CFO auto-exclusion: a rig that keeps under-delivering (grade F with ≥2
    # samples) joins the AUTO list so bad performers vanish from the panel
    # everywhere — without touching the user's manual blacklist, and without
    # re-flagging a manually restored rig until NEW bad samples accumulate.
    if (not blacklisted and not auto_blacklisted
            and trust.get("grade") == "F" and trust.get("samples", 0) >= 2):
        # Respect a restore: only re-exclude when a NEW bad rental arrived
        # AFTER the previous auto-exclusion (otherwise the restore button
        # would be immediately undone by the same streak).
        last_auto = _auto_blacklist_ts(rig_id, tenant_id=tenant_id)
        newest = _history_newest_ts(history)
        if last_auto == 0.0 or (newest is not None and newest > last_auto):
            add_rig_to_auto_blacklist(rig_id, tenant_id=tenant_id)
            auto_blacklisted = True

    pcts = [h["percent"] for h in history if h.get("percent") is not None]
    costs = [h["cost_sats_per_thh"] for h in history if h.get("cost_sats_per_thh") is not None]
    summary = {
        "rentals": len(history),
        "avg_pct": round(sum(pcts) / len(pcts), 1) if pcts else None,
        "cost_avg_sats_thh": round(sum(costs) / len(costs), 2) if costs else None,
        # Trend: avg of the 3 most recent vs the previous ones (positive =
        # improving). Rough but honest — never fabricates a slope.
        "trend_pct": None,
    }
    if len(pcts) >= 4:
        recent = sum(pcts[:3]) / 3.0
        older = sum(pcts[3:]) / (len(pcts) - 3)
        summary["trend_pct"] = round(recent - older, 1)
    return {"history": history, "trust": trust, "blacklisted": blacklisted,
            "auto_blacklisted": auto_blacklisted, "summary": summary}


def _num(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None
