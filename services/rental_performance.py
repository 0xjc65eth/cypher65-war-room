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

from agents.solo_mining_advisor.tools import (
    _mrr_signed_headers,
    mrr_credentials,
    braiins_credentials,
)
import helpers
from helpers import csv_neutralize as _csv_neutralize
from services.db import get_db
from services.settings import is_default_tenant, load_settings

log = logging.getLogger("cypher65")

MRR_BASE = "https://www.miningrigrentals.com/api/v2"
BRAIINS_BASE = "https://hashpower.braiins.com/v1"
PH_TO_TH = 1000.0

# ── MRR list pagination (Issue #200) ───────────────────────────────────────
# MRR list endpoints (/rental) paginate via ?page= (1-based) with a HARD cap
# of 200 on `limit`. The old code made ONE call and ignored MRR's `total` —
# every rental beyond the top silently didn't exist for the panel, the P/L
# sweep and the CSV ledger. The loop below walks pages until MRR's `total`
# is covered, bounded so a misbehaving/ignored pagination param can never
# burn the MRR rate budget (the very reason the original single-call cap
# existed).
MRR_MAX_PAGE_SIZE = 200  # MRR API hard cap for `limit`
MRR_PAGE_SAFETY_MAX_RECORDS = 1000  # loop ceiling (rate-budget protection)
MRR_PAGE_SAFETY_MAX_PAGES = 10  # absolute loop bound (API-misbehavior guard)
# Effective ceiling per fetch = min(pages_cap * page_size, records_cap): with
# the panel's page size 50 → ≤10 pages / 500 records; CSV/sweep at 200 →
# ≤5 pages / 1000 records. Always bounded, always surfaced as `truncated`.

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
# ACCEPTED-recommendation ledger: when the operator (or the auto-exclusion)
# acts on the pilot's avoid suggestion, we snapshot the rig's delivery stats
# and WHEN — so the panel can show 'what was accepted' and the outcome after.
RIG_ACCEPTED_KEY = "_rental_accepted_recos"


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
        return {
            "score": None,
            "grade": None,
            "label": "NO DATA",
            "median_pct": None,
            "worst_pct": None,
            "mad_pct": None,
            "samples": 0,
        }

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
    """Blacklist a rig id (persistent per tenant). Returns True if added.

    This is the 'ACCEPT' action: the operator acted on the pilot's avoid
    suggestion, so the accepted-recommendation ledger records the rig with
    its delivery snapshot (the panel shows the outcome afterwards).
    """
    if rig_id is None or str(rig_id) == "":
        return False
    rid = str(rig_id)
    items = get_rig_blacklist(tenant_id=tenant_id)
    if rid not in items:
        items.append(rid)
        ok = _save_rig_blacklist(items, tenant_id=tenant_id)
        if ok:
            _record_accepted_reco(rid, "manual", tenant_id=tenant_id)
        return ok
    return True


def remove_rig_from_blacklist(rig_id, tenant_id: str = "") -> bool:
    """Remove a rig from BOTH blacklists (manual restore). Returns True if
    removed — a restored rig is never re-flagged by the same streak.

    The accepted-recommendation ledger entry for the rig is marked
    ``restored`` (+ when) so the panel/admin show the decision was REVOKED
    instead of only the delivery outcome afterwards."""
    rid = str(rig_id)
    items = [x for x in get_rig_blacklist(tenant_id=tenant_id) if x != rid]
    ok = _save_rig_blacklist(items, tenant_id=tenant_id)
    auto = [x for x in get_auto_blacklist(tenant_id=tenant_id) if x != rid]
    ok2 = _save_rig_ids(RIG_AUTO_BLACKLIST_KEY, auto, tenant_id=tenant_id)
    if ok and ok2:
        _mark_accepted_reco_restored(rid, tenant_id=tenant_id)
    return ok and ok2


def is_rig_blacklisted(rig_id, tenant_id: str = "") -> bool:
    """Quick check used by the list/detail routes (no full list re-parse).
    True when the rig is on EITHER the manual or the auto blacklist."""
    if rig_id is None:
        return False
    rid = str(rig_id)
    return rid in get_rig_blacklist(tenant_id=tenant_id) or rid in get_auto_blacklist(
        tenant_id=tenant_id
    )


def _ensure_rig_settings_tables() -> None:
    """Self-heal the settings tables (fresh DBs / tests): the real app always
    creates them via init_db, but a missing table must never silently drop a
    blacklist write."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT, updated_ts INTEGER)"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS tenant_settings (tenant_id TEXT, key TEXT, value TEXT, updated_ts INTEGER, PRIMARY KEY(tenant_id, key))"
        )
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
            c.execute(
                "SELECT value FROM tenant_settings WHERE tenant_id=? AND key=?",
                (tenant_id, key),
            )
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
    ts_items = [
        x
        for x in _load_rig_ids(RIG_AUTO_TS_KEY, tenant_id=tenant_id)
        if str(x).split(":")[0] != rid
    ]
    ts_items.append(f"{rid}:{now}")
    ok_ts = _save_rig_ids(RIG_AUTO_TS_KEY, ts_items, tenant_id=tenant_id)
    if ok_ids and ok_ts:
        _record_accepted_reco(rid, "auto", tenant_id=tenant_id)
    return ok_ids and ok_ts


# ── Accepted recommendations (ledger + outcome) ────────────────────────────
# The pilot flags rigs to avoid (grade F). When the operator ACTS — manual
# blacklist or the auto-exclusion fires — that's an accepted recommendation:
# we persist a per-tenant ledger with the rig's delivery snapshot at that
# moment (the pilot's case) so the panel can later show the OUTCOME (any
# delivery data for the same rig AFTER the decision). The ledger stores
# dicts, so it uses its own save/load (the rig-id lists stringify).


def _save_accepted_recos(entries: List[Dict], tenant_id: str = "") -> bool:
    """Persist the accepted-recommendation ledger (JSON list of dicts)."""
    _ensure_rig_settings_tables()
    raw = json.dumps(entries)
    ts = int(time.time())
    try:
        conn = get_db()
        c = conn.cursor()
        if is_default_tenant(tenant_id):
            c.execute(
                "INSERT INTO settings(key,value,updated_ts) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_ts=excluded.updated_ts",
                (RIG_ACCEPTED_KEY, raw, ts),
            )
        else:
            c.execute(
                "INSERT INTO tenant_settings(tenant_id,key,value,updated_ts) VALUES(?,?,?,?) "
                "ON CONFLICT(tenant_id,key) DO UPDATE SET value=excluded.value, updated_ts=excluded.updated_ts",
                (tenant_id, RIG_ACCEPTED_KEY, raw, ts),
            )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        log.warning("[rental_performance] accepted recos save failed: %s", e)
        return False


def _load_accepted_recos(tenant_id: str = "") -> List[Dict]:
    """Load the accepted-recommendation ledger (list of dicts, empty on miss)."""
    _ensure_rig_settings_tables()
    try:
        conn = get_db()
        c = conn.cursor()
        if is_default_tenant(tenant_id):
            c.execute("SELECT value FROM settings WHERE key=?", (RIG_ACCEPTED_KEY,))
        else:
            c.execute(
                "SELECT value FROM tenant_settings WHERE tenant_id=? AND key=?",
                (tenant_id, RIG_ACCEPTED_KEY),
            )
        row = c.fetchone()
        conn.close()
        if row and row["value"]:
            parsed = json.loads(row["value"])
            if isinstance(parsed, list):
                return [x for x in parsed if isinstance(x, dict)]
        return []
    except Exception as e:
        log.warning("[rental_performance] accepted recos load failed: %s", e)
        return []


def _rig_local_delivery(rig_id: Any, tenant_id: str = "") -> Dict[str, Any]:
    """Best name + (start_ts, percent) pairs + costs from the LOCAL track
    record for a rig (bucket='renter', provider='mrr'). Never raises."""
    pairs: List[Any] = []
    costs: List[float] = []
    name = ""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT rig_name, start, percent, cost_sats_per_thh "
            "FROM rental_history WHERE tenant_id=? AND rig_id=? "
            "AND bucket='renter' AND provider='mrr'",
            (tenant_id or "", str(rig_id)),
        )
        for row in c.fetchall():
            if not name and row["rig_name"]:
                name = str(row["rig_name"])
            ts = _parse_start_ts(row["start"])
            if row["percent"] is not None:
                pairs.append((ts, _num(row["percent"])))
            if row["cost_sats_per_thh"] is not None:
                costs.append(_num(row["cost_sats_per_thh"]))
        conn.close()
    except Exception as e:
        log.warning("[rental_performance] rig local delivery failed: %s", e)
    return {"name": name, "pairs": pairs, "costs": costs}


def _mark_accepted_reco_restored(rig_id: Any, tenant_id: str = "") -> bool:
    """Mark the ledger entry of a restored rig as REVOKED (restored + when).

    The verdict then reads 'revoked' (the decision was reversed), NOT the
    delivery outcome after it. Idempotent: only the newest entry per rig is
    touched; an entry with no record (never accepted) is a no-op. Never
    raises."""
    rid = str(rig_id)
    try:
        entries = _load_accepted_recos(tenant_id=tenant_id)
        touched = False
        for e in entries:
            if str(e.get("rig_id") or "") == rid:
                e["restored"] = True
                e["restored_ts"] = int(time.time())
                touched = True
        return _save_accepted_recos(entries, tenant_id=tenant_id) if touched else False
    except Exception as e:
        log.warning("[rental_performance] accepted reco restore mark failed: %s", e)
        return False


def _record_accepted_reco(rig_id: Any, source: str, tenant_id: str = "") -> bool:
    """Persist an ACCEPTED recommendation: the rig was excluded (manual
    blacklist or auto) — snapshot the pilot's case (delivery stats) at that
    moment so the panel can show the outcome afterwards. Dedup: keeps the
    NEWEST entry per rig. Never raises."""
    if rig_id is None or str(rig_id).strip() == "":
        return False
    rid = str(rig_id)
    local = _rig_local_delivery(rid, tenant_id=tenant_id)
    trust = compute_rig_trust_score([{"percent": p} for _, p in local["pairs"]])
    entry: Dict[str, Any] = {
        "rig_id": rid,
        "name": local["name"] or "",
        "ts": int(time.time()),
        "source": source,
        "delivery_pct": trust.get("median_pct"),
        "samples": trust.get("samples", 0),
        "grade": trust.get("grade"),
        # Honest framing: the pilot's avoid signal is grade F (the same set
        # build_rental_recommendations counts as avoid_count). A MANUAL
        # blacklist of a rig the pilot never flagged still lands here — the
        # UI shows 'não sugerido' instead of implying the pilot recommended it.
        "pilot_flagged": trust.get("grade") == "F",
    }
    entries = [
        x
        for x in _load_accepted_recos(tenant_id=tenant_id)
        if str(x.get("rig_id") or "") != rid
    ]
    entries.append(entry)
    return _save_accepted_recos(entries, tenant_id=tenant_id)


def get_accepted_recos(tenant_id: str = "") -> List[Dict]:
    """Accepted-recommendation ledger, newest first (for the panel summary)."""
    entries = _load_accepted_recos(tenant_id=tenant_id)
    entries.sort(key=lambda x: x.get("ts") or 0, reverse=True)
    return entries


def _accepted_outcome(e: Dict[str, Any], tenant_id: str = "") -> Dict[str, Any]:
    """Delivery AFTER an accepted decision + verdict for one ledger entry.

    Shared by the per-tenant panel summary and the global admin audit trail
    (one implementation, no drift). ``e`` carries the acceptance snapshot
    (delivery_pct = the pilot's case at acceptance); the median delivery %
    of the rig's rentals with ``start >= ts`` (same tenant) is the outcome:
      - avoided   → no new rentals after the decision (expected good result)
      - improved  → median after ≥ before + 5pp
      - worse     → median after ≤ before - 5pp
      - same      → within ±5pp
      - no_before → acceptance had no before reference

    A REVOKED decision (``restored`` set by remove_rig_from_blacklist) gets
    verdict ``revoked`` — the honest state is "the decision was reversed",
    not the delivery outcome afterwards. Never raises.
    """
    rid = e.get("rig_id")
    after_pcts: List[float] = []
    after_costs: List[float] = []
    accept_ts = e.get("ts") or 0
    if rid:
        try:
            conn = get_db()
            c = conn.cursor()
            c.execute(
                "SELECT start, percent, cost_sats_per_thh FROM rental_history "
                "WHERE tenant_id=? AND rig_id=? AND bucket='renter' "
                "AND provider='mrr'",  # symmetric with _rig_local_delivery
                (tenant_id or "", str(rid)),
            )
            for row in c.fetchall():
                ts = _parse_start_ts(row["start"])
                if ts is not None and ts >= accept_ts:
                    if row["percent"] is not None:
                        after_pcts.append(_num(row["percent"]))
                    if row["cost_sats_per_thh"] is not None:
                        after_costs.append(_num(row["cost_sats_per_thh"]))
            conn.close()
        except Exception as ex:
            log.warning("[rental_performance] accepted outcome failed: %s", ex)
    before = e.get("delivery_pct")
    after = round(sum(after_pcts) / len(after_pcts), 1) if after_pcts else None
    if e.get("restored"):
        # The decision was REVOKED (rig restored) — the verdict reflects the
        # reversal, regardless of what the delivery did afterwards.
        verdict = "revoked"
    elif after is None:
        # No new rentals after the decision: 'avoided' when the pilot had
        # a case (before stats), honest 'no data' when there was never a
        # track record to begin with.
        verdict = "no_before" if before is None else "avoided"
    elif before is None:
        verdict = "no_before"
    else:
        d = after - before
        verdict = "improved" if d >= 5 else ("worse" if d <= -5 else "same")
    return {
        **e,
        "delivery_after_pct": after,
        "cost_after_sats_per_thh": (
            round(sum(after_costs) / len(after_costs), 2) if after_costs else None
        ),
        "verdict": verdict,
    }


def compute_accepted_recos_summary(tenant_id: str = "") -> Dict[str, Any]:
    """Accepted recommendations + the DELIVERY OUTCOME afterwards.

    Per-tenant view (the RENTALS panel block): for every ledger entry of the
    tenant, attaches the outcome via _accepted_outcome.

    Returns {"count", "accepted": [...]} — accepted sorted newest first.
    """
    entries = get_accepted_recos(tenant_id=tenant_id)
    out = [_accepted_outcome(e, tenant_id=tenant_id) for e in entries]
    out.sort(key=lambda x: x.get("ts") or 0, reverse=True)
    return {"count": len(out), "accepted": out}


# ── Auto-exclusion history (WHEN + CAUSE) ─────────────────────────────────
# The accepted ledger snapshots the pilot's case at exclusion (grade,
# delivery %, samples). The auto-exclusion history joins that snapshot with
# the tenant's rule vigente (grade floor + min samples) so the operator sees
# BOTH when the pilot excluded a rig AND why (the rule that fired).


def _auto_exclusion_cause(entry: Dict[str, Any], thresholds: Dict[str, Any]) -> str:
    """Human-readable CAUSE for one auto-exclusion ledger entry: the rig's
    delivery snapshot at exclusion + the rule that fired. Never raises."""
    try:
        bits = []
        grade = entry.get("grade")
        if grade:
            bits.append(f"grade {grade}")
        d = entry.get("delivery_pct")
        if d is not None:
            try:
                bits.append(f"entrega {float(d):.1f}%")
            except (TypeError, ValueError):
                pass
        samples = entry.get("samples")
        if samples is not None:
            try:
                n = int(samples)
                bits.append(f"{n} amostra{'s' if n != 1 else ''}")
            except (TypeError, ValueError):
                pass
        rule = f"régua: floor {thresholds.get('grade', 'F')}, mín {thresholds.get('min_samples', 2)}"
        cause = " · ".join(bits) if bits else "sub-entrega"
        return f"{cause} — {rule}"
    except Exception:
        return "sub-entrega"


def auto_exclusion_history(tenant_id: str = "") -> Dict[str, Any]:
    """Auto-exclusions WITH when + cause (per tenant).

    Reads the accepted ledger entries with source='auto' (the snapshot at
    exclusion time — grade, delivery %, samples) and attaches the rule
    vigente (grade floor + min samples). Returns
    {"count", "exclusions": [{rig_id, name, ts, grade, delivery_pct, samples,
    min_samples, grade_floor, cause}]} sorted newest first. Never raises
    (empty → zeroed)."""
    th = _auto_exclude_thresholds(tenant_id=tenant_id)
    entries = [
        e
        for e in get_accepted_recos(tenant_id=tenant_id)
        if (e.get("source") or "") == "auto"
    ]
    exclusions: List[Dict[str, Any]] = []
    for e in entries:
        exclusions.append(
            {
                "rig_id": e.get("rig_id"),
                "name": e.get("name") or e.get("rig_id"),
                "ts": e.get("ts") or 0,
                "grade": e.get("grade"),
                "delivery_pct": e.get("delivery_pct"),
                "samples": e.get("samples", 0),
                "min_samples": th["min_samples"],
                "grade_floor": th["grade"],
                "cause": _auto_exclusion_cause(e, th),
            }
        )
    exclusions.sort(key=lambda x: x.get("ts") or 0, reverse=True)
    return {"count": len(exclusions), "exclusions": exclusions}


def admin_auto_exclusion_history(days: int = 0) -> Dict[str, Any]:
    """GLOBAL auto-exclusion history (ALL tenants, when + cause) for the
    /api/admin audit trail. Uses the shared _admin_audit_decisions pass so
    tenant tagging + the days window match the rest of the audit exactly
    (one implementation, no drift). Returns {"count", "exclusions":
    [{tenant_id, rig_id, name, ts, grade, delivery_pct, samples, cause}]}
    sorted newest first. Never raises."""
    exclusions: List[Dict[str, Any]] = []
    for d in _admin_audit_decisions(days=days):
        if (d.get("source") or "") != "auto":
            continue
        store_tid = "" if d.get("tenant_id") in ("", "default") else d.get("tenant_id")
        th = _auto_exclude_thresholds(tenant_id=store_tid)
        exclusions.append(
            {
                "tenant_id": d.get("tenant_id") or "default",
                "rig_id": d.get("rig_id"),
                "name": d.get("name") or d.get("rig_id"),
                "ts": d.get("ts") or 0,
                "grade": d.get("grade"),
                "delivery_pct": d.get("delivery_pct"),
                "samples": d.get("samples", 0),
                "min_samples": th["min_samples"],
                "grade_floor": th["grade"],
                "cause": _auto_exclusion_cause(d, th),
            }
        )
    exclusions.sort(key=lambda x: x.get("ts") or 0, reverse=True)
    return {"count": len(exclusions), "exclusions": exclusions}


def admin_auto_exclusion_aggregates(days: int = 0) -> Dict[str, Any]:
    """GLOBAL auto-exclusion CONCENTRATION report for /api/admin.

    Groups the SAME exclusion set as admin_auto_exclusion_history (shared
    pass → zero drift: same days window, same tenant tagging, same rule
    snapshot) into the pattern the platform operator needs to see the
    pilot's global behavior at a glance:

      - by_tenant: who triggers the pilot most — exclusion count per tenant
        (%% of total, distinct rigs, most-frequent grade, avg delivery).
      - by_rule: how aggressive each tenant's régua is — grouping per
        (grade_floor, min_samples) with tenant count + avg delivery.
      - top_rigs: systemic-problem rigs — the SAME rig auto-excluded in 2+
        tenants (the ledger dedups per tenant+rig, so recurrence across
        tenants is a provider-side pattern), top 5 by tenant_count.

    Never raises (empty ledger → zeroed lists).
    """
    hist = admin_auto_exclusion_history(days=days)
    out = _aggregate_exclusions(hist.get("exclusions") or [])
    out["days"] = days if days else None
    return out


def _aggregate_exclusions(exclusions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate an auto-exclusion list into the concentration report
    (by_tenant / by_rule / top_rigs).

    Kept separate so the admin route can aggregate the SAME history pass it
    already computed (zero drift + ONE audit pass, not two). Never raises.
    """
    total = len(exclusions)

    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _i(v, default: int = 0) -> int:
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    def _avg(vals):
        return round(sum(vals) / len(vals), 1) if vals else None

    by_tenant: Dict[str, Dict[str, Any]] = {}
    by_rule: Dict[tuple, Dict[str, Any]] = {}
    rigs: Dict[str, Dict[str, Any]] = {}  # key: rig_id (cross-tenant)
    for e in exclusions:
        tid = e.get("tenant_id") or "default"
        rid = str(e.get("rig_id") or "")
        t = by_tenant.setdefault(
            tid,
            {
                "count": 0,
                "rigs": set(),
                "grades": {},
                "deliveries": [],
            },
        )
        t["count"] += 1
        t["rigs"].add(rid)
        g = e.get("grade")
        if g:
            t["grades"][str(g)] = t["grades"].get(str(g), 0) + 1
        dv = _f(e.get("delivery_pct"))
        if dv is not None:
            t["deliveries"].append(dv)

        rule = (e.get("grade_floor") or "?", _i(e.get("min_samples"), 0))
        r = by_rule.setdefault(
            rule,
            {
                "count": 0,
                "tenants": set(),
                "deliveries": [],
            },
        )
        r["count"] += 1
        r["tenants"].add(tid)
        if dv is not None:
            r["deliveries"].append(dv)

        if not rid:
            continue
        # top_rigs = systemic-problem rigs: the SAME rig auto-excluded in
        # MULTIPLE tenants (the ledger dedups per tenant+rig — NEWEST entry
        # wins — so recurrence across tenants is a provider-side pattern,
        # which a within-tenant "repeat offender" could never show).
        rr = rigs.setdefault(
            rid,
            {
                "rig_id": rid,
                "name": e.get("name") or e.get("rig_id") or rid,
                "tenants": [],
                "total_count": 0,
                "last_ts": 0,
            },
        )
        if tid not in rr["tenants"]:
            rr["tenants"].append(tid)
        rr["total_count"] += 1
        rr["last_ts"] = max(rr["last_ts"], _i(e.get("ts"), 0))

    tenants_out = []
    for tid, t in by_tenant.items():
        # Tiebreak: most-frequent grade first, then the highest letter
        # (A–F sort lexicographically — 'F' > 'D' > 'C'...).
        top_grade = (
            max(t["grades"].items(), key=lambda kv: (kv[1], kv[0]))[0]
            if t["grades"]
            else None
        )
        tenants_out.append(
            {
                "tenant_id": tid,
                "count": t["count"],
                "pct": round(100.0 * t["count"] / total, 1) if total else 0.0,
                "rigs": len(t["rigs"]),
                "top_grade": top_grade,
                "delivery_avg_pct": _avg(t["deliveries"]),
            }
        )
    tenants_out.sort(key=lambda x: (x["count"], x["rigs"]), reverse=True)

    rules_out = []
    for (floor, mins), r in by_rule.items():
        rules_out.append(
            {
                "grade_floor": floor,
                "min_samples": mins,
                "count": r["count"],
                "pct": round(100.0 * r["count"] / total, 1) if total else 0.0,
                "tenants": len(r["tenants"]),
                "delivery_avg_pct": _avg(r["deliveries"]),
            }
        )
    rules_out.sort(key=lambda x: x["count"], reverse=True)

    top_rigs = [
        {
            "rig_id": r["rig_id"],
            "name": r["name"],
            "tenant_count": len(r["tenants"]),
            "tenants": r["tenants"],
            "total_count": r["total_count"],
            "last_ts": r["last_ts"],
        }
        for r in sorted(
            rigs.values(),
            key=lambda r: (len(r["tenants"]), r["total_count"], r["last_ts"]),
            reverse=True,
        )
        if len(r["tenants"]) >= 2  # genuine recurrence, not single-tenant noise
    ][:5]

    return {
        "count": total,
        "by_tenant": tenants_out,
        "by_rule": rules_out,
        "top_rigs": top_rigs,
    }


# ── Admin audit trail (global operator — ALL tenants) ──────────────────────
# The panel view is tenant-scoped by design; the platform operator needs the
# FLEET of decisions. The admin path reads EVERY tenant's ledger — from the
# global `settings` table (default tenant) AND `tenant_settings` (every named
# tenant) — tags each entry with its tenant and aggregates. Never called by
# a tenant-scoped request (only from the /api/admin route, which is gated).


def _load_all_accepted_recos() -> List[Dict[str, Any]]:
    """Every accepted-recommendation ledger entry across ALL tenants, tagged
    with ``tenant_id`` ('default' for the global settings table)."""
    _ensure_rig_settings_tables()
    out: List[Dict[str, Any]] = []
    conn = None
    try:
        conn = get_db()
        c = conn.cursor()
        # Default tenant (global settings table).
        c.execute("SELECT value FROM settings WHERE key=?", (RIG_ACCEPTED_KEY,))
        row = c.fetchone()
        if row and row["value"]:
            try:
                parsed = json.loads(row["value"])
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, list):
                for x in parsed:
                    if isinstance(x, dict):
                        out.append({**x, "tenant_id": "default"})
        # Named tenants (tenant_settings table).
        c.execute(
            "SELECT tenant_id, value FROM tenant_settings WHERE key=?",
            (RIG_ACCEPTED_KEY,),
        )
        for trow in c.fetchall():
            try:
                parsed = json.loads(trow["value"])
            except (TypeError, ValueError):
                continue
            if isinstance(parsed, list):
                for x in parsed:
                    if isinstance(x, dict):
                        out.append({**x, "tenant_id": str(trow["tenant_id"])})
    except Exception as e:
        log.warning("[rental_performance] admin recos load failed: %s", e)
    finally:
        # Always release the connection — even on a mid-query raise.
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return out


def _admin_audit_decisions(days: int = 0) -> List[Dict[str, Any]]:
    """Every accepted-recommendation decision across ALL tenants, with the
    delivery outcome attached (shared by the audit payload and the
    worse-concentration detector — ONE audit pass, zero drift). Each dict is
    the _accepted_outcome entry tagged with its tenant_id ('default' for the
    global settings table). Sorted newest first. Never raises (empty DB →
    empty list).
    """
    entries = _load_all_accepted_recos()
    now = int(time.time())
    try:
        days = int(days) if days else 0
    except (TypeError, ValueError):
        days = 0
    if days and days > 0:
        cutoff = now - days * 86400
        # ts=0 (missing timestamp) reads as epoch and drops under a days
        # window — acceptable: an entry without a date has no place in a
        # windowed audit.
        entries = [e for e in entries if (e.get("ts") or 0) >= cutoff]

    decisions: List[Dict[str, Any]] = []
    for e in entries:
        tid = e.get("tenant_id") or "default"
        # Storage normalizes the default tenant to '' in rental_history;
        # 'default' is only the admin DISPLAY label.
        store_tid = "" if tid in ("", "default") else tid
        outcome = _accepted_outcome(e, tenant_id=store_tid)
        outcome["tenant_id"] = tid
        decisions.append(outcome)
    decisions.sort(key=lambda x: x.get("ts") or 0, reverse=True)
    return decisions


def compute_admin_accepted_recos(days: int = 0, limit: int = 200) -> Dict[str, Any]:
    """Global audit trail of accepted recommendations (ALL tenants).

    Aggregates every tenant's accepted-recommendation ledger + the delivery
    outcome afterwards so the platform operator sees the fleet of decisions
    at a glance. ``limit`` caps the OUTPUT list only — ``count`` is always
    the true total (deliberate full-audit pass; the ledger dedups per rig, so
    the work is bounded by blacklisted rigs across tenants). Returns
    {"count", "by_source", "by_verdict", "by_tenant",
    "pilot_flagged", "avg_delivery_before", "avg_delivery_after", "days",
    "decisions"} — never raises (empty DB → zeroed aggregates).
    """
    decisions = _admin_audit_decisions(days=days)

    by_source: Dict[str, int] = {}
    by_verdict: Dict[str, int] = {}
    by_tenant: Dict[str, Dict[str, Any]] = {}
    pilot_flagged = 0
    before_vals: List[float] = []
    after_vals: List[float] = []
    for d in decisions:
        src = d.get("source") or "unknown"
        by_source[src] = by_source.get(src, 0) + 1
        v = d.get("verdict") or "unknown"
        by_verdict[v] = by_verdict.get(v, 0) + 1
        t = d.get("tenant_id") or "default"
        tb = by_tenant.setdefault(t, {"count": 0, "by_source": {}, "by_verdict": {}})
        tb["count"] += 1
        tb["by_source"][src] = tb["by_source"].get(src, 0) + 1
        tb["by_verdict"][v] = tb["by_verdict"].get(v, 0) + 1
        if d.get("pilot_flagged"):
            pilot_flagged += 1
        if d.get("delivery_pct") is not None:
            before_vals.append(d["delivery_pct"])
        if d.get("delivery_after_pct") is not None:
            after_vals.append(d["delivery_after_pct"])
    tenant_rows = [
        {
            "tenant_id": tid,
            "count": tb["count"],
            "by_source": tb["by_source"],
            "by_verdict": tb["by_verdict"],
        }
        for tid, tb in sorted(by_tenant.items(), key=lambda kv: -kv[1]["count"])
    ]
    return {
        "count": len(decisions),
        "by_source": by_source,
        "by_verdict": by_verdict,
        "by_tenant": tenant_rows,
        "pilot_flagged": pilot_flagged,
        "avg_delivery_before": (
            round(sum(before_vals) / len(before_vals), 1) if before_vals else None
        ),
        "avg_delivery_after": (
            round(sum(after_vals) / len(after_vals), 1) if after_vals else None
        ),
        "days": days or None,
        "decisions": decisions[:limit],
    }


# ── Tenant worse-concentration flag (padrão global de reincidência) ─────────
# An accepted recommendation that comes back 'worse' means the operator
# blacklisted a rig (after the pilot flagged it) and the rig went BACK to
# under-delivering on a later rental. One-off worse is noise; a tenant where
# a LARGE SHARE of accepted decisions end worse is a systemic pattern — bad
# sellers in that tenant's pool, weak acceptance criteria, or a delivery
# problem — and the platform operator should see it. Shared audit pass
# (_admin_audit_decisions) so the report never drifts from the JSON view.


def detect_tenant_worse_concentration(
    days: int = 0, min_worse: int = 2, worse_ratio: float = 0.5
) -> Dict[str, Any]:
    """Flag tenants with a concentrated 'worse' verdict pattern.

    A tenant is flagged when BOTH hold over the window:
      - worse_count >= min_worse (absolute recidivism — noise floor);
      - worse_count / total_decisions >= worse_ratio (the majority-ish share
        of their accepted decisions came back worse).

    ``revoked`` decisions (restored rigs) never count as worse — a revoked
    decision is a reversal, not a recidivism. Returns
    {"count", "tenants": [{tenant_id, total, worse, ratio_pct, severity,
    by_verdict}], "min_worse", "worse_ratio", "days"} — sorted by worse
    count desc, never raises (empty DB → zeroed). severity: CRIT when
    worse >= 3 AND ratio_pct >= 60, else WARN.
    """
    decisions = _admin_audit_decisions(days=days)
    per_tenant: Dict[str, Dict[str, Any]] = {}
    for d in decisions:
        t = d.get("tenant_id") or "default"
        tb = per_tenant.setdefault(t, {"count": 0, "worse": 0, "by_verdict": {}})
        tb["count"] += 1
        v = d.get("verdict") or "unknown"
        tb["by_verdict"][v] = tb["by_verdict"].get(v, 0) + 1
        if v == "worse":
            tb["worse"] += 1

    try:
        min_worse = max(1, int(min_worse))
        worse_ratio = max(0.0, min(1.0, float(worse_ratio)))
    except (TypeError, ValueError):
        min_worse = 2
        worse_ratio = 0.5

    flagged: List[Dict[str, Any]] = []
    for t, tb in per_tenant.items():
        if tb["worse"] < min_worse or tb["count"] <= 0:
            continue
        ratio_pct = round(100.0 * tb["worse"] / tb["count"], 1)
        if ratio_pct < worse_ratio * 100.0:
            continue
        severity = "CRIT" if (tb["worse"] >= 3 and ratio_pct >= 60.0) else "WARN"
        flagged.append(
            {
                "tenant_id": t,
                "total": tb["count"],
                "worse": tb["worse"],
                "ratio_pct": ratio_pct,
                "severity": severity,
                "by_verdict": tb["by_verdict"],
            }
        )
    flagged.sort(key=lambda x: -x["worse"])
    return {
        "count": len(flagged),
        "tenants": flagged,
        "min_worse": min_worse,
        "worse_ratio": worse_ratio,
        "days": days or None,
    }


# ── Admin audit CSV export (planilha do operador) ───────────────────────────
# Same payload as the JSON endpoint (one implementation, no drift): the
# operator exports the fleet of accepted decisions + delivery verdicts as a
# spreadsheet. CSV-specific concerns live HERE:
#   - text cells with a leading =/+/−/@ are neutralized (formula-injection
#     guard — the sheet opens and shows text, never executes);
#   - None → empty cell;
#   - the caller prefixes the UTF-8 BOM so Excel detects the encoding.

ADMIN_ACCEPTED_CSV_COLUMNS = [
    "tenant_id",
    "accepted_ts",
    "rig_id",
    "name",
    "source",
    "grade",
    "pilot_flagged",
    "delivery_pct",
    "samples",
    "delivery_after_pct",
    "cost_after_sats_per_thh",
    "restored",
    "restored_ts",
    "verdict",
]


def admin_accepted_recos_csv(data: Dict[str, Any]) -> str:
    """Render the admin accepted-recos audit payload as CSV (header + one row
    per decision). Consumes the SAME payload compute_admin_accepted_recos
    returns, so the spreadsheet never drifts from the JSON view. The caller
    prepends the UTF-8 BOM. Never raises (empty payload → header only)."""
    import csv as _csv
    import io as _io

    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow(ADMIN_ACCEPTED_CSV_COLUMNS)
    for d in data.get("decisions") or []:
        # Flags: '0' (known false) vs '' (legacy row predating the field).
        flagged = (
            "1" if d.get("pilot_flagged") else ("0" if "pilot_flagged" in d else "")
        )
        restored = "1" if d.get("restored") else ("0" if "restored" in d else "")
        w.writerow(
            [
                _csv_neutralize(d.get("tenant_id") or "default"),
                _fmt_unix_ts(d.get("ts")),
                _csv_neutralize(d.get("rig_id")),
                _csv_neutralize(d.get("name")),
                d.get("source") or "unknown",
                d.get("grade"),
                flagged,
                d.get("delivery_pct"),
                d.get("samples"),
                d.get("delivery_after_pct"),
                d.get("cost_after_sats_per_thh"),
                restored,
                _fmt_unix_ts(d.get("restored_ts")),
                d.get("verdict") or "unknown",
            ]
        )
    return buf.getvalue()


def _fmt_unix_ts(ts) -> Any:
    """Unix ts → ISO-ish UTC string for spreadsheets (None/0 → empty)."""
    import datetime as _dt

    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    try:
        return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
    except (OverflowError, OSError, ValueError):
        return ""


# ── Rentals ANALYSIS export (Controle de Rendimento) ───────────────────────
# The simple CSV lists the ledger; the ANALYSIS export is a capital-protection
# tool. Per rental it computes: performance vs a CONFIGURABLE minimum
# acceptable delivery (default 90%), the refund the operator is ENTITLED to
# (MRR policy: <80% delivery = full refund; 80%..min = proportional), the
# spread paid vs the market AT PURCHASE (persisted hashrate_market_history
# near the start ±3d, live quote fallback), the real loss and an automatic
# action suggestion (ok / monitor / request_refund / blacklist).
#
# Honesty rules:
#   - MRR does NOT expose received refunds → refund_sats stays empty and the
#     pending figure = the DUE amount (notes explain).
#   - dates parsing to 1970-01-01 are INVALID — flagged in notes and never
#     used for market/pl lookups.
#   - Braiins contracts carry no delivery % / seller → partial row + note.

# Full-refund threshold (MRR under-delivery policy).
REFUND_FULL_BELOW_PCT = 80.0
# Reliability below this → the analysis suggests blacklisting the seller.
BLACKLIST_RELIABILITY_BELOW = 70.0
# A date parsing within the first days of 1970 is invalid/incomplete data.
_EPOCH_INVALID_S = 10 * 86400

RENTAL_ANALYSIS_COLUMNS = [
    "id",
    "provider",
    "status",
    "start",
    "end",
    "length_hours",
    "blacklisted",
    # Pilot audit (Issue #119): o que o Auto-Pilot decidiu sobre o rig —
    # auto_excluded = está NA auto-blacklist agora; as demais colunas vêm do
    # ledger (histórico): causa, régua vigente, quando, e se foi REVOGADA.
    "auto_excluded",
    "auto_exclude_cause",
    "auto_exclude_rule",
    "auto_exclude_ts",
    "auto_exclude_restored",
    "advertised_th",
    "avg_th",
    "delivery_pct",
    "min_acceptable_delivery",
    "performance_ok",
    "cancelled_by_performance",
    "paid_sats",
    "refund_sats",
    "expected_refund_sats",
    "refund_pending_sats",
    "cost_sats_per_thh",
    "market_sats_per_thh",
    "spread_sats",
    "spread_pct",
    "effective_cost_sats",
    "loss_sats",
    "loss_after_refund_sats",
    "roi_pct",
    "seller_reliability_score",
    "risk_score",
    "efficiency_score",
    "should_blacklist",
    "auto_action",
    "notes",
]


def _is_epoch_date(value) -> bool:
    """True when ``value`` parses to a date inside the first days of 1970
    (invalid/incomplete data — never used for lookups). Also flags a
    PRESENT-but-unparseable value (garbage/empty strings silently skipping
    lookups is dishonest — the row is marked and the panel reads the note)."""
    if value is None or str(value).strip() == "":
        return False
    ts = _parse_start_ts(value)
    if ts is None:
        return True  # present but unparseable → invalid/incomplete
    return ts < _EPOCH_INVALID_S


def _market_price_for_ts(ts: Optional[float]) -> Optional[float]:
    """Cheapest PLAUSIBLE market price (sats/TH·h) at ``ts``: historical
    (persisted hashrate_market_history near the date) with the live quote as
    last resort — mirrors the overpay-alert lookup. None when neither covers."""
    p = _historical_market_sats_per_thh(ts)
    if p:
        return p
    try:
        ref = fetch_market_reference()
        return ref.get("price_sats_per_thh") if ref.get("available") else None
    except Exception:
        return None


def _auto_exclusion_map(tenant_id: str = "") -> Dict[str, Dict[str, Any]]:
    """rig_id → auto-exclusion ledger entry {grade, delivery_pct, samples,
    grade_floor, min_samples, cause, ts, restored} (newest per rig).

    Same ledger + rule the panel's AUTO-EXCLUSÕES section reads, so the CSV
    audit matches the UI byte-for-byte. Never raises."""
    try:
        th = _auto_exclude_thresholds(tenant_id=tenant_id)
        out: Dict[str, Dict[str, Any]] = {}
        for e in get_accepted_recos(tenant_id=tenant_id):
            if (e.get("source") or "") != "auto":
                continue
            rid = e.get("rig_id")
            if rid is None:
                continue
            rid_s = str(rid)
            entry = {
                "grade": e.get("grade"),
                "delivery_pct": e.get("delivery_pct"),
                "samples": e.get("samples", 0),
                "grade_floor": th["grade"],
                "min_samples": th["min_samples"],
                "cause": _auto_exclusion_cause(e, th),
                "ts": e.get("ts") or 0,
                "restored": bool(e.get("restored")),
            }
            prev = out.get(rid_s)
            if prev is None or entry["ts"] >= (prev["ts"] or 0):
                out[rid_s] = entry
        return out
    except Exception as e:
        log.warning("[rental_performance] auto-exclusion map failed: %s", e)
        return {}


def _fmt_ts_date(ts: Any) -> str:
    """Unix ts → YYYY-MM-DD (UTC); empty on invalid/absent."""
    try:
        ts = int(ts)
        if ts <= 0:
            return ""
        return time.strftime("%Y-%m-%d", time.gmtime(ts))
    except (TypeError, ValueError, OverflowError):
        return ""


def _mrr_analysis_row(
    r: Dict[str, Any],
    tenant_id: str,
    min_delivery_pct: float,
    blacklisted_ids: set,
    auto_ids: set,
    autoex: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """One ANALYSIS row for an MRR rental (renter bucket). Never raises."""
    _rig = r.get("rig") if isinstance(r.get("rig"), dict) else {}
    rid = _rig.get("id")
    rid_str = str(rid) if rid is not None else ""
    paid = _num(r.get("price_paid_btc"))
    paid_sats = round(paid * 1e8) if paid is not None else None
    adv_th = _num(r.get("hashrate_advertised_th"))
    avg_th = _num(r.get("hashrate_average_th"))
    delivery = _num(r.get("hashrate_percent"))
    lenh = _num(r.get("length_hours"))
    start = r.get("start")
    end = r.get("end")
    ended = bool(r.get("ended"))
    advertised_thh = (adv_th * lenh) if (adv_th and lenh) else None
    delivered_thh = (avg_th * lenh) if (avg_th and lenh) else None

    start_invalid = _is_epoch_date(start)
    end_invalid = _is_epoch_date(end)
    # Lookup window: valid start wins, else valid end, else None.
    _ts = None if start_invalid else _parse_start_ts(start)
    if _ts is None and not end_invalid:
        _ts = _parse_start_ts(end)
    market = _market_price_for_ts(_ts) if _ts else None

    # Performance vs the configurable minimum.
    perf_ok = delivery is not None and delivery >= min_delivery_pct
    cancelled_by_perf = delivery is not None and delivery < min_delivery_pct
    status = (
        "cancelled_performance"
        if cancelled_by_perf
        else ("active" if not ended else "completed")
    )

    # Refund entitlement (MRR under-delivery policy).
    expected_refund = 0
    if delivery is not None and delivery < REFUND_FULL_BELOW_PCT:
        expected_refund = paid_sats if paid_sats is not None else 0
    elif delivery is not None and delivery < min_delivery_pct:
        expected_refund = (
            round(paid_sats * (1.0 - delivery / 100.0), 2)
            if paid_sats is not None
            else 0
        )
    # refund_sats (received) is NOT exposed by MRR → empty cell, pending = due.
    refund_sats = None
    refund_pending = expected_refund if expected_refund else None

    # Unit costs + spread + loss.
    cost_sats_per_thh = (
        (paid_sats / advertised_thh)
        if (paid_sats is not None and advertised_thh)
        else None
    )
    fair_value = (market * advertised_thh) if (market and advertised_thh) else None
    spread_sats = (
        (paid_sats - fair_value) if (paid_sats is not None and fair_value) else None
    )
    spread_pct = (
        round(spread_sats / fair_value * 100.0, 1)
        if (spread_sats is not None and fair_value)
        else None
    )
    effective_cost = (
        (paid_sats / delivered_thh)
        if (paid_sats is not None and delivered_thh)
        else None
    )
    delivered_value = (market * delivered_thh) if (market and delivered_thh) else None
    loss_sats = (
        (paid_sats - (refund_sats or 0) - delivered_value)
        if (paid_sats is not None and delivered_value)
        else None
    )
    # Real (net) loss: what actually leaves the pocket after the refund the
    # operator is ENTITLED to. MRR never exposes received refunds, so the
    # DUE refund is the best honest estimate — pre-refund loss (loss_sats)
    # overstates capital damage for exactly the rentals this CSV flags.
    loss_after_refund = (
        (loss_sats - expected_refund)
        if (loss_sats is not None and expected_refund)
        else loss_sats
    )

    # Economic ROI (network-yield P/L) — only when the yield is computable.
    roi = None
    if delivered_thh and paid_sats is not None:
        pl = compute_rental_pl(
            delivered_thh,
            paid_sats,
            network_hashrate_hs=_resolve_network_hashrate_for_rental(start, end),
        )
        roi = pl.get("pl_pct")

    # Seller intelligence from the local track record.
    reliability = None
    if rid_str:
        local = _rig_local_delivery(rid_str, tenant_id=tenant_id)
        trust = compute_rig_trust_score([{"percent": p} for _, p in local["pairs"]])
        reliability = trust.get("score")
    risk = round(100.0 - reliability, 1) if reliability is not None else None
    already_bl = rid_str in blacklisted_ids or rid_str in auto_ids
    should_bl = reliability is not None and reliability < BLACKLIST_RELIABILITY_BELOW
    # Pilot audit: the rig's auto-exclusion ledger entry (histórico — inclui
    # decisões REVOGADAS) + se está na auto-blacklist AGORA.
    auto_entry = (autoex or {}).get(rid_str) or {}
    auto_rule = ""
    if auto_entry:
        auto_rule = (
            "floor "
            + str(auto_entry.get("grade_floor") or "F")
            + " · mín "
            + str(auto_entry.get("min_samples") or 2)
        )

    # Auto action: blacklist > request_refund > monitor > ok.
    if should_bl and not already_bl:
        action = "blacklist"
    elif expected_refund:
        action = "request_refund"
    elif delivery is None or start_invalid or end_invalid:
        action = "monitor"
    else:
        action = "ok"

    notes = []
    if cancelled_by_perf:
        notes.append(
            f"entrega {delivery:.0f}% < mín {min_delivery_pct:.0f}% → reembolso devido {expected_refund} sats"
        )
    if start_invalid or end_invalid:
        notes.append("data inválida (1970-01-01) — desconsiderada nos cálculos")
    if expected_refund and loss_sats is not None:
        notes.append("loss_after_refund já desconta o reembolso DEVIDO")
    if market is None:
        notes.append("sem preço de mercado na data")
    if already_bl:
        notes.append("rig já na blacklist")
    if auto_entry:
        notes.append(
            "auto-exclusão do piloto: "
            + (auto_entry.get("cause") or "sem causa")
            + (" (REVOGADA)" if auto_entry.get("restored") else "")
        )
    if expected_refund and refund_sats is None:
        notes.append("reembolso recebido não rastreado pela API — valor é o DEVIDO")

    return {
        "id": r.get("id"),
        "provider": "mrr",
        "status": status,
        "start": start,
        "end": end,
        "length_hours": lenh,
        "blacklisted": "1" if already_bl else "",
        "auto_excluded": "1" if rid_str in auto_ids else "",
        "auto_exclude_cause": auto_entry.get("cause") or "",
        "auto_exclude_rule": auto_rule,
        "auto_exclude_ts": _fmt_ts_date(auto_entry.get("ts")) if auto_entry else "",
        "auto_exclude_restored": "1" if auto_entry.get("restored") else "",
        "advertised_th": adv_th,
        "avg_th": avg_th,
        "delivery_pct": delivery,
        "min_acceptable_delivery": min_delivery_pct,
        "performance_ok": "1" if perf_ok else "",
        "cancelled_by_performance": "1" if cancelled_by_perf else "",
        "paid_sats": paid_sats,
        "refund_sats": refund_sats,
        "expected_refund_sats": round(expected_refund, 2) if expected_refund else 0,
        "refund_pending_sats": refund_pending,
        "cost_sats_per_thh": round(cost_sats_per_thh, 2) if cost_sats_per_thh else None,
        "market_sats_per_thh": round(market, 2) if market else None,
        "spread_sats": round(spread_sats, 2) if spread_sats is not None else None,
        "spread_pct": spread_pct,
        "effective_cost_sats": round(effective_cost, 2) if effective_cost else None,
        "loss_sats": round(loss_sats, 2) if loss_sats is not None else None,
        "loss_after_refund_sats": (
            round(loss_after_refund, 2) if loss_after_refund is not None else None
        ),
        "roi_pct": roi,
        "seller_reliability_score": reliability,
        "risk_score": risk,
        "efficiency_score": delivery,
        "should_blacklist": "1" if should_bl else "",
        "auto_action": action,
        "notes": "; ".join(notes),
    }


def build_rentals_analysis_rows(
    active: List[Dict],
    history: List[Dict],
    contracts: List[Dict],
    tenant_id: str = "",
    min_delivery_pct: float = 90.0,
) -> List[Dict[str, Any]]:
    """ANALYSIS rows for the yield-control CSV (renter MRR + Braiins).

    Owner rows are income (no delivery/refund semantics) → excluded. Every
    row is fail-closed (never raises on a partial payload).
    """
    try:
        min_delivery_pct = float(min_delivery_pct)
        if not (1.0 <= min_delivery_pct <= 100.0):
            min_delivery_pct = 90.0
    except (TypeError, ValueError):
        min_delivery_pct = 90.0
    bl = set(get_rig_blacklist(tenant_id=tenant_id))
    auto = set(get_auto_blacklist(tenant_id=tenant_id))
    # Pilot audit lookup: rig → auto-exclusion ledger entry (causa + régua +
    # revogada) — same ledger the panel section reads (Issue #119).
    autoex = _auto_exclusion_map(tenant_id=tenant_id)
    rows: List[Dict[str, Any]] = []
    for bucket in (active or [], history or []):
        for r in bucket:
            if not isinstance(r, dict):
                continue
            try:
                rows.append(
                    _mrr_analysis_row(r, tenant_id, min_delivery_pct, bl, auto, autoex)
                )
            except Exception as e:
                log.warning("[rental_performance] analysis row failed: %s", e)
    for c in contracts or []:
        if not isinstance(c, dict):
            continue
        amt = _num(c.get("amount_sat"))
        spd = _num(c.get("speed_limit_ph"))
        status = str(c.get("status") or "").replace("SPOT_BID_STATUS_", "") or (
            "active" if not c.get("ended_at") else "completed"
        )
        rows.append(
            {
                "id": c.get("id"),
                "provider": "braiins",
                "status": status,
                "start": c.get("started_at"),
                "end": c.get("ended_at"),
                "length_hours": None,
                "blacklisted": "",
                "auto_excluded": "",
                "auto_exclude_cause": "",
                "auto_exclude_rule": "",
                "auto_exclude_ts": "",
                "auto_exclude_restored": "",
                "advertised_th": (spd * PH_TO_TH) if spd else None,
                "avg_th": None,
                "delivery_pct": None,
                "min_acceptable_delivery": min_delivery_pct,
                "performance_ok": "",
                "cancelled_by_performance": "",
                "paid_sats": amt,
                "refund_sats": None,
                "expected_refund_sats": 0,
                "refund_pending_sats": None,
                "cost_sats_per_thh": None,
                "market_sats_per_thh": None,
                "spread_sats": None,
                "spread_pct": None,
                "effective_cost_sats": None,
                "loss_sats": None,
                "loss_after_refund_sats": None,
                "roi_pct": None,
                "seller_reliability_score": None,
                "risk_score": None,
                "efficiency_score": None,
                "should_blacklist": "",
                "auto_action": "monitor",
                "notes": "contrato Braiins — sem entrega medida nem seller no export; abra o detail para a série de speed",
            }
        )
    return rows


def rentals_analysis_csv(rows: List[Dict[str, Any]]) -> str:
    """Render ANALYSIS rows as CSV with the full column set (header + values,
    empty cells for None). The caller prepends the UTF-8 BOM."""
    import csv as _csv
    import io as _io

    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow(RENTAL_ANALYSIS_COLUMNS)
    for r in rows:
        w.writerow([r.get(col, "") for col in RENTAL_ANALYSIS_COLUMNS])
    return buf.getvalue()


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


def _is_mrr_auth_rejection(msg: str) -> bool:
    """True when an MRR error means the CREDENTIAL is invalid/outdated
    (Issue #152): 'Not Authenticated - Invalid Key - Bad Nonce.' is the
    classic signature — a key/secret that no longer matches the account (or
    a stuck nonce tracker on the key). It is NOT a concurrency bug (nonces
    are monotonic since #150) and NOT a missing-credential state. The panel
    uses this flag to explain 'regenerate the key' instead of showing a
    generic provider error.
    """
    m = (msg or "").lower()
    return any(
        k in m
        for k in (
            "not authenticated",
            "invalid key",
            "bad nonce",
            "unauthor",
            "forbidden",
        )
    )


def probe_mrr_credentials(tenant_id: str = "") -> Dict[str, Any]:
    """Perform one read-only MRR /whoami probe without exposing credentials."""
    creds = _mrr_creds(tenant_id=tenant_id)
    if not (creds["api_key"] and creds["api_secret"]):
        return {
            "success": False,
            "configured": False,
            "status": "missing",
            "provider": "mrr",
        }
    endpoint = "/whoami"
    try:
        response = requests.get(
            MRR_BASE + endpoint,
            headers=_mrr_signed_headers(
                creds["api_key"], creds["api_secret"], endpoint
            ),
            timeout=15,
        )
        if response.status_code in (401, 403):
            return {
                "success": False,
                "configured": True,
                "status": "rejected",
                "provider": "mrr",
                "http_status": response.status_code,
            }
        if not response.ok:
            return {
                "success": False,
                "configured": True,
                "status": "upstream_error",
                "provider": "mrr",
                "http_status": response.status_code,
            }
        data = response.json()
        auth = data.get("data") if isinstance(data, dict) else None
        authenticated = isinstance(auth, dict) and auth.get("authed") is True
        if authenticated:
            return {
                "success": True,
                "configured": True,
                "status": "accepted",
                "provider": "mrr",
                "http_status": response.status_code,
            }
        message = str((auth or {}).get("auth_mesage") or "")
        return {
            "success": False,
            "configured": True,
            "status": (
                "rejected" if _is_mrr_auth_rejection(message) else "unexpected_response"
            ),
            "provider": "mrr",
            "http_status": response.status_code,
        }
    except requests.Timeout:
        return {
            "success": False,
            "configured": True,
            "status": "timeout",
            "provider": "mrr",
        }
    except (requests.RequestException, ValueError, TypeError) as exc:
        log.warning(
            "[rental_performance] MRR credential probe failed: %s", type(exc).__name__
        )
        return {
            "success": False,
            "configured": True,
            "status": "provider_unavailable",
            "provider": "mrr",
        }


def fetch_mrr_rentals(
    rtype: str = "renter",
    history: bool = False,
    limit: int = 25,
    tenant_id: str = "",
) -> Dict[str, Any]:
    """List MRR rentals for a tenant (default: renter, active only).

    Issue #200: walks EVERY MRR page (bounded by the rate-budget safety
    caps) so rentals beyond the first page are no longer invisible to the
    panel, the P/L sweep or the CSV ledger. ``limit`` is the page size
    (clamped to MRR's 200 max); ``rendered``/``total``/``truncated`` expose
    the honest surface ("X de N") when the safety cap kicks in.

    Returns:
      {"success": True, "needs_auth": False, "rentals": [...],
       "total": MRR-reported total, "rendered": len(rentals),
       "truncated": rendered < total, "pages_fetched": n}
    """
    creds = _mrr_creds(tenant_id=tenant_id)
    if not (creds["api_key"] and creds["api_secret"]):
        return {
            "success": False,
            "needs_auth": True,
            "rentals": [],
            "total": 0,
            "rendered": 0,
            "truncated": False,
            "pages_fetched": 0,
        }

    # MRR signs the PATH WITHOUT query params (verified live: signing
    # '/rental?type=...' fails with 'String to sign: .../rental'). Pass the
    # filters as separate request params instead.
    endpoint = "/rental"
    page_size = max(1, min(int(limit or 25), MRR_MAX_PAGE_SIZE))

    rentals: List[Dict[str, Any]] = []
    seen_ids: Dict[str, bool] = {}  # dedup — pagination can drift mid-loop
    total: int = 0
    truncated = False
    page = 0
    try:
        while True:
            page += 1
            if page > MRR_PAGE_SAFETY_MAX_PAGES:
                truncated = True
                break
            qparams = {"type": rtype, "page": page}
            if history:
                qparams["history"] = "true"
            qparams["limit"] = page_size
            r = requests.get(
                MRR_BASE + endpoint,
                headers=_mrr_signed_headers(
                    creds["api_key"], creds["api_secret"], endpoint
                ),
                params=qparams,
                timeout=15,
            )
            if not r.ok:
                _err = f"HTTP {r.status_code}"
                return {
                    "success": False,
                    "needs_auth": False,
                    # Issue #152 (c): a 401/403 with a CONFIGURED key is a
                    # credential problem — the panel must explain
                    # 'regenerate' instead of a generic HTTP error.
                    "auth_rejected": _is_mrr_auth_rejection(_err)
                    or r.status_code in (401, 403),
                    "error": _err,
                    "rentals": [],
                    "total": 0,
                    "rendered": 0,
                    "truncated": False,
                    "pages_fetched": page,
                }
            data = r.json()
            if not data.get("success"):
                _err = str(data.get("data") or data.get("message") or "MRR error")
                return {
                    "success": False,
                    "needs_auth": False,
                    "auth_rejected": _is_mrr_auth_rejection(_err),
                    "error": _err,
                    "rentals": [],
                    "total": 0,
                    "rendered": 0,
                    "truncated": False,
                    "pages_fetched": page,
                }
            raw = data.get("data") or {}
            records = raw.get("rentals") or []
            if page == 1:
                # MRR's total is the target for the loop; later pages may
                # omit it or drift, so the first observation is the truth. A
                # malformed upstream total must NEVER fail the whole fetch
                # (the rentals already fetched would be thrown away) —
                # degrade to the page-1 count (single-page behavior, bounded).
                try:
                    total = int(raw.get("total") or 0)
                except (TypeError, ValueError):
                    total = 0
                if not total:
                    total = len(records)
            new_on_page = 0
            for rv in records:
                if not isinstance(rv, dict):
                    continue
                norm = _normalize_rental(rv)
                rid = norm.get("id")
                if rid is not None and rid in seen_ids:
                    continue  # page drift / duplicate — never double-list
                seen_ids[rid] = True
                rentals.append(norm)
                new_on_page += 1
            if not records:
                break  # empty page → end of the series
            if total and len(seen_ids) >= total:
                break  # MRR-reported total fully covered
            if new_on_page == 0:
                break  # pagination not shifting (param ignored?) — stop honest
            if len(seen_ids) >= MRR_PAGE_SAFETY_MAX_RECORDS:
                truncated = True
                break
        return {
            "success": True,
            "needs_auth": False,
            "rentals": rentals,
            "total": total or len(rentals),
            "rendered": len(rentals),
            "truncated": truncated or bool(total and len(rentals) < total),
            "pages_fetched": page,
        }
    except Exception as e:
        log.warning("[rental_performance] mrr rentals fetch failed: %s", e)
        return {
            "success": False,
            "needs_auth": False,
            "error": str(e)[:120],
            "rentals": [],
            "total": 0,
            "rendered": 0,
            "truncated": False,
            "pages_fetched": page,
        }


def fetch_mrr_rental_detail(rental_id: str, tenant_id: str = "") -> Dict[str, Any]:
    """Full detail + graph + log for one MRR rental."""
    creds = _mrr_creds(tenant_id=tenant_id)
    if not (creds["api_key"] and creds["api_secret"]):
        return {"success": False, "needs_auth": True}

    out: Dict[str, Any] = {"success": False}
    # Per-endpoint credential-rejection verdict (Issue #174) — aggregated
    # after the pool since threads run concurrently.
    _rejections: Dict[str, bool] = {}

    # Fetch detail + graph + log CONCURRENTLY (independent GETs). Sequential
    # calls made a detail click take up to ~45s worst case (three 15s
    # timeouts). Each call is a pure function of (endpoint, creds) — the MRR
    # signing is thread-safe (no shared mutable state).
    def _fetch_one(sub: str, key: str) -> None:
        endpoint = f"/rental/{rental_id}{sub}"
        try:
            r = requests.get(
                MRR_BASE + endpoint,
                headers=_mrr_signed_headers(
                    creds["api_key"], creds["api_secret"], endpoint
                ),
                timeout=15,
            )
            if not r.ok:
                # Carry the MRR error BODY, not just the status — the
                # 'Not Authenticated - Invalid Key - Bad Nonce.' signature
                # lives in the payload's `data` field and drives the
                # auth_rejected flag (Issue #174).
                _msg = f"HTTP {r.status_code}"
                try:
                    _j = r.json()
                    if isinstance(_j, dict):
                        _msg = _j.get("data") or _j.get("error") or _msg
                except Exception:
                    _t = (r.text or "").strip()
                    if _t:
                        _msg = f"HTTP {r.status_code} — {_t[:120]}"
                _rejections[key] = _is_mrr_auth_rejection(_msg) or r.status_code in (
                    401,
                    403,
                )
                out[key] = {"error": _msg}
                return
            data = r.json()
            if data.get("success"):
                _rejections[key] = False
                out[key] = data.get("data")
            else:
                _d = data.get("data")
                if isinstance(_d, dict):
                    _err = str(_d.get("message") or _d.get("permission") or _d)
                else:
                    _err = str(_d or data.get("message") or "MRR error")
                _rejections[key] = _is_mrr_auth_rejection(_err)
                out[key] = {"error": _err}
        except Exception as e:
            _rejections[key] = False
            out[key] = {"error": str(e)[:120]}

    with ThreadPoolExecutor(max_workers=3) as ex:
        list(
            ex.map(
                lambda kv: _fetch_one(*kv),
                (("", "detail"), ("/graph", "graph"), ("/log", "log")),
            )
        )

    # Issue #174: same classifier the list uses — a CONFIGURED key rejected
    # on any detail endpoint (Bad Nonce / Invalid Key / 401/403) is a
    # credential problem: the detail click explains 'regenerate the key'.
    out["auth_rejected"] = any(_rejections.values())
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
        "hashrate_advertised_th": _hash_to_th(
            advertised.get("hash"), advertised.get("type")
        ),
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
    "/contract/active",
    "/contract",
    "/spot/bid/current",
    "/spot/bid",
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
    Accepts both the legacy (`contract`) and spot (`bid`) field names.

    The LIVE /spot/bid API wraps each item in an envelope:
        {"bid": {...}, "counters_committed": {...}}
    with the id/status/amount nested under ``bid``. Unwrap it first —
    otherwise ``c.get("id")`` is None and every order is silently
    dropped, so a valid account renders as "no contracts" (Issue #193)."""
    if isinstance(c, dict):
        for wrap_key in ("bid", "contract"):
            inner = c.get(wrap_key)
            # Only unwrap the true envelope (top level has no id) — a flat
            # contract item that happens to carry a `bid` sub-object as data
            # must keep reading its own level.
            if isinstance(inner, dict) and not (
                c.get("id") or c.get("bid_id") or c.get("order_id")
            ):
                c = inner
                break
    cid = c.get("id") or c.get("bid_id") or c.get("order_id")
    status = c.get("status") or c.get("bid_status") or ""
    # Spot statuses are verbose (SPOT_BID_STATUS_ACTIVE / BID_STATUS_ACTIVE)
    # — collapse to the legacy-style short status the UI already renders
    # (RUNNING/ACTIVE/FULFILLED/…).
    short_status = (
        str(status).replace("SPOT_BID_STATUS_", "").replace("BID_STATUS_", "")
        if status
        else ""
    )
    started = (
        c.get("started_at")
        or c.get("created_at")
        or c.get("created_ts")
        or c.get("created")
    )
    ended = c.get("ended_at") or c.get("completed_at") or c.get("completed_ts")
    return {
        "id": cid,
        "status": short_status or status,
        "speed_limit_ph": _num(
            c.get("speed_limit_ph") or c.get("speed_limit") or c.get("limit_ph")
        ),
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
        # Issue #187: explicit credentials_missing flag — the panel shows the
        # config hint whenever the key is missing, even on replayed/stale
        # payloads (the version stamp on /api/rentals marks old payloads).
        return {
            "success": False,
            "needs_auth": True,
            "credentials_missing": True,
            "error": "BRAIINS_API_KEY not configured",
            "contracts": [],
        }

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
            log.warning(
                "[rental_performance] braiins contracts fetch failed (%s): %s", ep, e
            )

    contracts = list(seen.values())
    if contracts:
        return {"success": True, "needs_auth": False, "contracts": contracts}

    # No data — decide what to tell the panel.
    if any("=401" in s or "=403" in s for s in statuses):
        return {
            "success": False,
            "needs_auth": True,
            "auth_rejected": True,
            "error": "Braiins API rejected the key (HTTP 401/403) — check the token in Settings",
            "contracts": [],
        }
    if reached_ok:
        # An endpoint answered 200 with no items: the key is VALID and the
        # account is genuinely empty — report a clean empty result, not a
        # misleading error just because the legacy probes 404'd.
        return {"success": True, "needs_auth": False, "contracts": []}
    if statuses:
        return {
            "success": False,
            "needs_auth": False,
            "error": "Braiins API returned no contracts ("
            + "; ".join(statuses[:3])
            + ")",
            "contracts": [],
        }
    return {"success": True, "needs_auth": False, "contracts": []}


def fetch_braiins_contract_speed(
    contract_id: str, tenant_id: str = ""
) -> Dict[str, Any]:
    """Braiins contract speed time series → [{ts, speed_ph}].

    Probes /contract/{id}/speed then /spot/bid/speed/{id}; parses items /
    points / data envelopes.
    """
    key = _braiins_key(tenant_id=tenant_id)
    if not key:
        return {
            "success": False,
            "needs_auth": True,
            "error": "BRAIINS_API_KEY not configured",
        }
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
                return {
                    "success": True,
                    "points": [
                        {
                            "ts": _num(
                                p.get("timestamp") or p.get("ts") or p.get("time")
                            ),
                            "speed_ph": _num(
                                p.get("speed_ph") or p.get("speed") or p.get("value")
                            ),
                        }
                        for p in points
                    ],
                }
        except Exception as e:
            log.warning(
                "[rental_performance] braiins speed fetch failed (%s): %s", ep, e
            )
    return {
        "success": False,
        "error": "Braiins speed endpoint returned no data for " + contract_id,
    }


def fetch_braiins_contract_detail(
    contract_id: str, contract: Optional[Dict] = None, tenant_id: str = ""
) -> Dict[str, Any]:
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
            (
                c
                for c in listing.get("contracts", [])
                if str(c.get("id")) == str(contract_id)
            ),
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
    delivered_thh = (
        (avg_th * duration_h) if (avg_th is not None and duration_h) else None
    )
    # Cost: amount_sat paid for the delivered TH·h (mirrors the MRR perf banner).
    cost_sats_per_thh = None
    if amount_sat is not None and delivered_thh and delivered_thh > 0:
        cost_sats_per_thh = amount_sat / delivered_thh
    pct = (
        ((avg_ph / speed_limit_ph) * 100.0)
        if (avg_ph is not None and speed_limit_ph)
        else None
    )

    detail: Dict[str, Any] = {
        "id": contract_id,
        "owner": "Braiins Hashpower",
        "renter": "—",
        "ended": bool(ended_at),
        "start": started_at,
        "end": ended_at,
        "length": round(duration_h, 2) if duration_h is not None else None,
        "hashrate": {
            "advertised": {
                "hash": speed_limit_ph,
                "type": "ph",
                "nice": (
                    f"{speed_limit_ph:g} PH/s" if speed_limit_ph is not None else None
                ),
            },
            "average": {
                "hash": avg_ph,
                "type": "ph",
                "percent": pct,
                "nice": f"{avg_ph:g} PH/s" if avg_ph is not None else None,
            },
        },
        "price": {
            "paid": (amount_sat / 1e8) if amount_sat is not None else None,
            "currency": "BTC",
            "price_sat": price_sat,
        },
        "rig": {
            "name": "Braiins contract",
            "region": "Braiins",
            "status": contract.get("status") if contract else None,
        },
        # Pre-computed analytics so the frontend perf banner works for Braiins.
        "perf": {
            "percent": pct,
            "avg_th": avg_th,
            "limit_th": (
                (speed_limit_ph * 1000.0) if speed_limit_ph is not None else None
            ),
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
        detail.get("perf"),
        amount_sat,
        network_hashrate_hs=_resolve_network_hashrate_for_rental(
            detail.get("start"), detail.get("end")
        ),
    )
    if amount_sat is None:
        pl = {"available": False}
    return {
        "success": True,
        "detail": detail,
        "graph": {"points": points},
        "stability": stability,
        "pl": pl,
    }


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
BID_MIN_SPEED_PH = 0.001  # 1 TH/s
BID_MAX_SPEED_PH = 1000.0  # 1 EH/s
BID_MIN_AMOUNT_SAT = 1000
BID_MAX_AMOUNT_SAT = 100_000_000  # 1 BTC
# price_sat per PH/day band: 1e4..1e9 → ~0.4..~41,600 sats/TH·h (real market
# ~300-1500 sats/TH·h; a unit conversion bug lands far outside this band).
BID_MIN_PRICE_SAT_PH_DAY = 10_000
BID_MAX_PRICE_SAT_PH_DAY = 1_000_000_000


def braiins_price_unit(tenant_id: str = "") -> str:
    """The account's spot price unit (default 'sats/PH/day'). Reads
    spot/settings with the tenant's key; falls back to the default unit.

    Issue #267 (audit 17-Aug): the OFFICIAL contract field is ``hr_unit``
    (e.g. 'EH/day', '100PH/day', '10PH/day') — ``price_unit`` does not exist
    in the OpenAPI. We read ``hr_unit`` first, then ``price_unit`` as a
    legacy fallback (older responses / mocks), then the default."""
    key = _braiins_key(tenant_id=tenant_id)
    if not key:
        return "sats/PH/day"
    try:
        r = requests.get(
            f"{BRAIINS_BASE}/spot/settings", headers={"apikey": key}, timeout=8
        )
        if r.ok:
            data = r.json()
            unit = data.get("hr_unit") or data.get("price_unit") or "sats/PH/day"
            return str(unit)
    except Exception as e:
        log.warning("[rental_performance] braiins price unit failed: %s", e)
    return "sats/PH/day"


def braiins_market_limits(tenant_id: str = "") -> Dict[str, Any]:
    """LIVE order bounds from GET /spot/settings (official MarketSettings
    schema — Issue #268 F3). The server validates orders against these
    values, so the bid path must pre-validate against the SAME numbers
    instead of only the static clamps.

    Returns {} when unavailable (no key / network / parse) — callers fall
    back to the static band (never skip BOTH layers). Also carries
    ``hr_unit`` so a single settings call serves the #267 unit conversion
    AND the #268 bounds (incl. ``max_bids_per_subaccount`` — F7 cap).
    """
    key = _braiins_key(tenant_id=tenant_id)
    if not key:
        return {}
    try:
        r = requests.get(
            f"{BRAIINS_BASE}/spot/settings", headers={"apikey": key}, timeout=8
        )
        if not r.ok:
            return {}
        data = r.json() or {}
        want = (
            "hr_unit",
            "tick_size_sat",
            "min_bid_price_sat",
            "max_bid_price_sat",
            "min_limited_bid_amount_sat",
            "max_limited_bid_amount_sat",
            "min_bid_amount_sat",
            "max_bid_amount_sat",
            "min_bid_speed_limit_ph",
            "max_bid_speed_limit_ph",
            "max_bids_per_subaccount",
        )
        out: Dict[str, Any] = {}
        for k in want:
            v = data.get(k)
            if v is None:
                continue
            if k == "hr_unit":
                out[k] = str(v)
            elif k == "max_bids_per_subaccount":
                try:
                    out[k] = int(v)
                except (TypeError, ValueError):
                    continue
            else:
                try:
                    out[k] = float(v)
                except (TypeError, ValueError):
                    continue
        return out
    except Exception as e:
        log.warning("[rental_performance] braiins settings failed: %s", e)
        return {}


def fetch_braiins_balance(tenant_id: str = "") -> Dict[str, Any]:
    """BTC balances for all subaccounts (total/available/blocked, in sats).
    Requires the tenant's Braiins key; 401/403 is surfaced, never swallowed."""
    key = _braiins_key(tenant_id=tenant_id)
    if not key:
        return {
            "available": False,
            "error": "BRAIINS_API_KEY not configured",
            "needs_auth": True,
        }
    try:
        r = requests.get(
            f"{BRAIINS_BASE}/account/balance", headers={"apikey": key}, timeout=15
        )
        if not r.ok:
            return {
                "available": False,
                "error": f"HTTP {r.status_code}",
                "needs_auth": r.status_code in (401, 403),
            }
        data = r.json()
        # Envelope: either {items: [{balance_type, amount, ...}]} or a dict
        # with total/available/blocked amounts (sats). Tolerate an items list
        # nested under data.data (same resilience as _braiins_list_items).
        if (
            isinstance(data, dict)
            and data.get("data")
            and isinstance(data["data"], dict)
            and "items" in data["data"]
            and "items" not in data
        ):
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
        return {
            "available": True,
            "total_sat": total,
            "available_sat": available,
            "blocked_sat": blocked,
        }
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
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Place a spot bid on Braiins (REAL MONEY). Fail-closed on every axis.

    Returns {"success": True, "bid": {...}} or {"success": False, "error": ...,
    "needs_auth": bool}. Sanity clamps run BEFORE the POST — a unit bug must
    never reach the wire. F7: never exceeds MarketSettings.max_bids_per_subaccount
    (live count first; fail-closed when the count is unverifiable).
    """
    from services.safety_policy import can_purchase_hashrate

    if not dry_run and not can_purchase_hashrate():
        return {
            "success": False,
            "error": "real hashrate purchases are disabled by deployment policy",
            "policy_disabled": True,
        }
    key = _braiins_key(tenant_id=tenant_id)
    if not key:
        return {
            "success": False,
            "needs_auth": True,
            "error": "BRAIINS_API_KEY not configured",
        }
    try:
        speed_limit_ph = float(speed_limit_ph)
        amount_sat = int(amount_sat)
        price_sat = int(price_sat)
    except (TypeError, ValueError):
        return {"success": False, "error": "invalid numeric inputs"}
    if not (BID_MIN_SPEED_PH <= speed_limit_ph <= BID_MAX_SPEED_PH):
        return {
            "success": False,
            "error": f"speed_limit must be {BID_MIN_SPEED_PH}-{BID_MAX_SPEED_PH} PH/s",
        }
    if not (BID_MIN_AMOUNT_SAT <= amount_sat <= BID_MAX_AMOUNT_SAT):
        return {
            "success": False,
            "error": f"amount must be {BID_MIN_AMOUNT_SAT}-{BID_MAX_AMOUNT_SAT} sats",
        }
    if not (BID_MIN_PRICE_SAT_PH_DAY <= price_sat <= BID_MAX_PRICE_SAT_PH_DAY):
        return {
            "success": False,
            "error": f"price_sat out of plausible band ({BID_MIN_PRICE_SAT_PH_DAY}-{BID_MAX_PRICE_SAT_PH_DAY} sats/PH/day)",
        }
    url = (upstream_url or "").strip()
    if not (
        url.startswith("stratum+tcp://")
        or url.startswith("stratum+ssl://")
        or url.startswith("stratum://")
    ):
        return {
            "success": False,
            "error": "upstream_url must be a stratum URL (stratum+tcp://host:port)",
        }

    # Issue #268 (F4): the official UpstreamSpecification REQUIRES both url
    # and identity — a bid without a worker identity is rejected upstream.
    identity = (upstream_identity or "").strip()
    if not identity:
        return {
            "success": False,
            "error": "upstream_identity must be provided (Braiins requires a worker identity)",
        }

    # MONEY-SAFETY: the API expects price_sat in the ACCOUNT's configured unit
    # (spot/settings hr_unit, default sats/PH/day). The UI quote is always
    # PH/day — convert to the account's unit before the wire, or FAIL CLOSED
    # when the unit is unknown (never guess with real money). A unit mismatch
    # would otherwise place an order 10-1000× too expensive without tripping
    # the sanity band above (Issue #267: official field is hr_unit, which can
    # be EH/day / 100PH/day / 10PH/day / TH/day — not only PH/day).
    #
    # Issue #268 (F3): the SAME settings call also returns the LIVE order
    # bounds (tick_size_sat, min/max price, amount and speed bands). The
    # server validates orders against these, so pre-validate against the SAME
    # numbers and fail closed locally. {} → the static clamps above remain
    # the final net (never skip BOTH layers).
    limits = braiins_market_limits(tenant_id=tenant_id)
    unit = (
        str(
            limits.get("hr_unit") or braiins_price_unit(tenant_id=tenant_id) or ""
        ).strip()
        or "sats/PH/day"
    )
    factor = helpers.braiins_hr_unit_factor(unit)
    if factor is None:
        return {
            "success": False,
            "error": f"price unit must be supported (got '{unit}') — not placing order",
        }
    price_for_api = round(price_sat * factor)

    if limits:
        tick = limits.get("tick_size_sat") or 0
        if tick > 0 and abs(price_for_api / tick - round(price_for_api / tick)) > 1e-6:
            return {
                "success": False,
                "error": f"price must be a multiple of the market tick ({tick:g} sats)",
            }
        lo_price = limits.get("min_bid_price_sat")
        hi_price = limits.get("max_bid_price_sat")
        if lo_price is not None and price_for_api < lo_price:
            return {
                "success": False,
                "error": f"price must be at least {lo_price:g} sats",
            }
        if hi_price is not None and price_for_api > hi_price:
            return {
                "success": False,
                "error": f"price must be at most {hi_price:g} sats",
            }
        # Limited bids (we always send speed_limit_ph) use the *limited*
        # amount band; fall back to the plain band when absent (explicit
        # None checks — `or` would misread a legitimate 0.0 bound).
        lo_amt = limits.get("min_limited_bid_amount_sat")
        if lo_amt is None:
            lo_amt = limits.get("min_bid_amount_sat")
        hi_amt = limits.get("max_limited_bid_amount_sat")
        if hi_amt is None:
            hi_amt = limits.get("max_bid_amount_sat")
        if lo_amt is not None and amount_sat < lo_amt:
            return {
                "success": False,
                "error": f"amount must be at least {lo_amt:g} sats",
            }
        if hi_amt is not None and amount_sat > hi_amt:
            return {
                "success": False,
                "error": f"amount must be at most {hi_amt:g} sats",
            }
        lo_spd = limits.get("min_bid_speed_limit_ph")
        hi_spd = limits.get("max_bid_speed_limit_ph")
        if lo_spd is not None and speed_limit_ph < lo_spd:
            return {
                "success": False,
                "error": f"speed_limit must be at least {lo_spd:g} PH/s",
            }
        if hi_spd is not None and speed_limit_ph > hi_spd:
            return {
                "success": False,
                "error": f"speed_limit must be at most {hi_spd:g} PH/s",
            }

    # Issue #268 (F7): MarketSettings.max_bids_per_subaccount — never exceed
    # the account's active-bid cap. Count live bids via /spot/bid/current
    # (F8) and reject BEFORE the wire when at the cap. When the count cannot
    # be obtained (provider unreachable), fail closed — real money, absence
    # of evidence is risk. When the limit itself is unknown (settings
    # unavailable), the provider's own 4xx on an over-limit POST is the
    # final net (same discipline as the static clamps in F3).
    # Note: the check-then-POST window is a known TOCTOU (two concurrent bids
    # can both pass) — the provider's own 4xx on an over-limit POST is the
    # accepted backstop for that residual race.
    max_bids = limits.get("max_bids_per_subaccount")
    if max_bids is not None:
        active = braiins_active_bids(tenant_id=tenant_id)
        if not active.get("success"):
            return {
                "success": False,
                "error": "cannot verify active bids count (provider unreachable) — retry",
            }
        count = len(active.get("bids") or [])
        if count >= max_bids:
            return {
                "success": False,
                "error": f"max active bids reached ({count}/{max_bids}) — cancel a bid first",
            }

    body: Dict[str, Any] = {
        "dest_upstream": {"url": url, "identity": identity[:120]},
        "speed_limit_ph": speed_limit_ph,
        "amount_sat": amount_sat,
        "price_sat": price_for_api,
    }
    if memo and str(memo).strip():
        body["memo"] = str(memo).strip()[:200]
    if cl_order_id and str(cl_order_id).strip():
        body["cl_order_id"] = str(cl_order_id).strip()[:64]

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "validated": True,
            "request": {
                "speed_limit_ph": speed_limit_ph,
                "amount_sat": amount_sat,
                "price_sat": price_for_api,
                "price_unit": unit,
                "cl_order_id": body.get("cl_order_id") or "",
            },
        }

    try:
        r = requests.post(
            f"{BRAIINS_BASE}/spot/bid", json=body, headers={"apikey": key}, timeout=20
        )
        if not r.ok:
            return {
                "success": False,
                "error": f"HTTP {r.status_code}: {r.text[:160]}",
                "needs_auth": r.status_code in (401, 403),
            }
        data = r.json()
        # Envelope tolerance: {bid_id, order_id, id} at top level or nested.
        bid_id = (
            (data.get("bid_id") if isinstance(data, dict) else None)
            or (data.get("id") if isinstance(data, dict) else None)
            or (data.get("order_id") if isinstance(data, dict) else None)
        )
        return {"success": True, "bid": {"id": bid_id, "raw": data}}
    except requests.Timeout as e:
        log.warning("[rental_performance] braiins bid timed out: %s", e)
        return {
            "success": False,
            "error": "provider timeout — submission outcome is unknown; do not retry automatically",
            "ambiguous": True,
        }
    except requests.RequestException as e:
        log.warning("[rental_performance] braiins bid transport failed: %s", e)
        return {
            "success": False,
            "error": "provider transport failure — submission outcome is unknown; reconcile before retrying",
            "ambiguous": True,
        }
    except Exception as e:
        log.warning("[rental_performance] braiins bid post failed: %s", e)
        return {"success": False, "error": str(e)[:160]}


def braiins_active_bids(tenant_id: str = "") -> Dict[str, Any]:
    """Active spot bids for the tenant (GET /spot/bid/current, official
    SpotGetCurrentBidsResponse — Issue #268 F8). Each item wraps the bid
    under ``bid``: ``{"bid": {...}, "counters_committed": {...}}``.

    Returns {"success": True, "bids": [...]} with id / cl_order_id / status /
    amounts, or {"success": False, "needs_auth": bool, "error": ...} — a
    rejected key is surfaced, never mistaken for an empty account (same
    discipline as fetch_braiins_contracts).
    """
    key = _braiins_key(tenant_id=tenant_id)
    if not key:
        return {
            "success": False,
            "needs_auth": True,
            "error": "BRAIINS_API_KEY not configured",
            "bids": [],
        }
    try:
        r = requests.get(
            f"{BRAIINS_BASE}/spot/bid/current", headers={"apikey": key}, timeout=15
        )
        if not r.ok:
            return {
                "success": False,
                "needs_auth": r.status_code in (401, 403),
                "error": f"HTTP {r.status_code}",
                "bids": [],
            }
        bids = []
        for it in _braiins_list_items(r.json()):
            b = it.get("bid") if isinstance(it, dict) else None
            if not isinstance(b, dict):
                b = it  # tolerate flat items
            if not isinstance(b, dict):
                continue
            bids.append(
                {
                    "id": b.get("id") or b.get("bid_id"),
                    "cl_order_id": (b.get("cl_order_id") or "").strip(),
                    "status": (b.get("status") or "").strip(),
                    "amount_sat": b.get("amount_sat"),
                    "price_sat": b.get("price_sat"),
                    "created": b.get("created"),
                }
            )
        return {"success": True, "bids": bids}
    except Exception as e:
        log.warning("[rental_performance] braiins active bids failed: %s", e)
        return {"success": False, "error": str(e)[:120], "bids": []}


def reconcile_braiins_bid(
    tenant_id: str = "",
    cl_order_id: str = "",
    retries: int = 2,
    backoff: float = 0.8,
) -> Dict[str, Any]:
    """Post-creation reconciliation (Issue #268 F8): confirm a just-placed
    bid actually exists on the provider by correlating cl_order_id against
    GET /spot/bid/current.

    Best-effort by design — a failure here NEVER revokes the placement; it
    only means confirmation is pending (surfaced to the operator as
    ``reconciled: "unknown"``). Returns {"reconciled": True|False|"unknown",
    "bid_id", "status", "active_count", "reason"}.
    """
    # Truncated to 64 chars to mirror the POST payload (create_braiins_bid)
    # — the correlation key must be IDENTICAL in every layer, otherwise a
    # long client id would never match the provider's echo (Issue #268 F8).
    cl = (cl_order_id or "").strip()[:64]
    if not cl:
        return {"reconciled": False, "reason": "no cl_order_id"}
    # Retries absorb the provider's eventual consistency: a freshly placed
    # bid may take a moment to appear on /spot/bid/current. retries=0 (tests,
    # one-shot callers) disables the backoff entirely.
    attempts = max(retries, 0)
    for attempt in range(attempts + 1):
        res = braiins_active_bids(tenant_id=tenant_id)
        if not res.get("success"):
            return {
                "reconciled": "unknown",
                "reason": res.get("error") or "provider unreachable",
            }
        for b in res.get("bids") or []:
            if (b.get("cl_order_id") or "").strip() == cl:
                return {
                    "reconciled": True,
                    "bid_id": b.get("id"),
                    "status": b.get("status"),
                    "active_count": len(res.get("bids") or []),
                }
        if attempt < attempts:
            time.sleep(backoff)
    return {
        "reconciled": False,
        "reason": "not found in active bids",
        "active_count": len(res.get("bids") or []),
    }


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
        live = [
            o
            for o in offers
            if not getattr(o, "estimated", False)
            and (getattr(o, "price_per_th_day", 0) or 0) >= _MIN_PLAUSIBLE_PRICE
        ]
        if not live:
            live = [
                o
                for o in offers
                if (getattr(o, "price_per_th_day", 0) or 0) >= _MIN_PLAUSIBLE_PRICE
            ]
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
    out.update(
        {
            "yield_sats": round(yield_sats, 2),
            "pl_sats": round(pl_sats, 2),
            "pl_pct": round(pl_sats / paid_sats * 100.0, 1) if paid_sats else None,
        }
    )
    return out


def attach_pl(
    perf: Optional[Dict],
    paid_sats: Optional[float],
    network_hashrate_hs: Optional[float] = None,
) -> Dict[str, Any]:
    """Augment a perf block with P/L analytics (used by BOTH detail routes)."""
    if not perf or not perf.get("delivered_thh"):
        return {"available": False}
    pl = compute_rental_pl(
        perf.get("delivered_thh"), paid_sats, network_hashrate_hs=network_hashrate_hs
    )
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
    vals = [p.get("speed_ph") for p in (points or []) if p.get("speed_ph") is not None]
    if len(vals) < 2:
        return {
            "cv_pct": None,
            "mean_ph": None,
            "std_ph": None,
            "min_ph": None,
            "max_ph": None,
            "grade": None,
            "label": "NO DATA",
        }
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    std = var**0.5
    cv = (std / mean * 100.0) if mean else None
    if cv is None:
        grade, label = None, "NO DATA"
    elif cv < 5:
        grade, label = "STABLE", "STABLE"
    elif cv <= 15:
        grade, label = "MODERATE", "MODERATE"
    else:
        grade, label = "VARIABLE", "VARIABLE"
    return {
        "cv_pct": round(cv, 1) if cv is not None else None,
        "mean_ph": round(mean, 2),
        "std_ph": round(std, 2),
        "min_ph": min(vals),
        "max_ph": max(vals),
        "grade": grade,
        "label": label,
    }


# ── Click-first analytics: rig track record, provider rankings, heatmap, ──
#    expiring rentals, backtest (all drill-down targets for the panel).


def rig_track_record(
    rig_id: Any = None, rig_name: str = "", tenant_id: str = ""
) -> Dict[str, Any]:
    """Full rig intelligence for a recommendation-card click — same shape as
    the detail route's rig_analysis, so the panel can open the rig verdict
    (trust grade, track record, blacklist) straight from a RECO card."""
    return analyze_rig(rig_id, rig_name, tenant_id=tenant_id)


def compute_provider_rankings(
    active: List[Dict], history: List[Dict], owner: List[Dict], contracts: List[Dict]
) -> List[Dict[str, Any]]:
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
                delivered,
                (paid * 1e8) if paid is not None else None,
                network_hashrate_hs=_resolve_network_hashrate_for_rental(
                    r.get("start"), r.get("end")
                ),
            )
            if pl.get("pl_pct") is not None:
                pl_pcts.append(pl["pl_pct"])
            if delivered and paid is not None:
                costs.append((paid * 1e8) / delivered)
        out.append(
            {
                "provider": provider,
                "label": label,
                "rentals": len(rows),
                "avg_delivery_pct": round(sum(pcts) / len(pcts), 1) if pcts else None,
                "avg_cost_sats_per_thh": (
                    round(sum(costs) / len(costs), 2) if costs else None
                ),
                "avg_pl_pct": (
                    round(sum(pl_pcts) / len(pl_pcts), 1) if pl_pcts else None
                ),
                "spend_sats": round(spend),
            }
        )
    # Braiins contracts: no delivery % in the list payload (only the speed
    # series has it) — cost is derivable when amount_sat exists.
    b_rents = [c for c in (contracts or []) if isinstance(c, dict)]
    if b_rents:
        amts = [c.get("amount_sat") for c in b_rents if c.get("amount_sat") is not None]
        out.append(
            {
                "provider": "braiins",
                "label": "Braiins",
                "rentals": len(b_rents),
                "avg_delivery_pct": None,  # requires per-contract speed series
                "avg_cost_sats_per_thh": None,
                "avg_pl_pct": None,
                "spend_sats": round(sum(amts)) if amts else 0,
            }
        )
    out.sort(
        key=lambda x: (x["avg_delivery_pct"] is not None, x["avg_delivery_pct"] or 0),
        reverse=True,
    )
    return out


def compute_rig_heatmap(
    history: List[Dict], owner: List[Dict], tenant_id: str = ""
) -> List[Dict[str, Any]]:
    """Heatmap cells rig-name × (avg delivery %, avg cost, samples) so the
    operator sees 'which rig MODELS deliver well at what price' in a grid.
    Uses the LOCAL track record (instant) plus the owner bucket for income
    rigs. Cells need ≥2 samples to avoid one-off noise."""
    from collections import defaultdict

    agg = defaultdict(lambda: {"pcts": [], "costs": [], "spend": 0.0})
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT rig_name, percent, cost_sats_per_thh, paid_sats "
            "FROM rental_history WHERE tenant_id=? AND rig_name != '' AND bucket='renter'",
            (tenant_id or "",),
        )
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
        cells.append(
            {
                "rig": name[:32],
                "samples": len(g["pcts"]) or len(g["costs"]),
                "avg_delivery_pct": (
                    round(sum(g["pcts"]) / len(g["pcts"]), 1) if g["pcts"] else None
                ),
                "avg_cost_sats_per_thh": (
                    round(sum(g["costs"]) / len(g["costs"]), 2) if g["costs"] else None
                ),
                "spend_sats": round(g["spend"]),
            }
        )
    cells.sort(key=lambda x: -(x["avg_delivery_pct"] or 0))
    return cells


def compute_expiring_rentals(
    active: List[Dict], hours: float = 72.0
) -> List[Dict[str, Any]]:
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


def compute_backtest(
    th: float, hours: float, market: Optional[Dict] = None
) -> Dict[str, Any]:
    """'What if I rented X TH for Y hours?' — cost at the cheapest live market
    price vs expected gross yield. Honest: yield needs network hashrate;
    without it only the cost side is returned (no fabricated P/L)."""
    mkt = market or fetch_market_reference()
    price = mkt.get("price_sats_per_thh") if mkt.get("available") else None
    cost_sats = (price * th * hours) if price else None
    yield_per_thh = compute_expected_yield_sats_per_thh()
    yield_sats = (yield_per_thh * th * hours) if yield_per_thh is not None else None
    pl_sats = (
        (yield_sats - cost_sats)
        if (yield_sats is not None and cost_sats is not None)
        else None
    )
    return {
        "available": True,
        "th": th,
        "hours": hours,
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
WORST_RIG_EWMA_ALPHA = 0.5  # 50% weight on the newest rental at each step


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
            (tenant_id or "",),
        )
        rows = c.fetchall()
        conn.close()
    except Exception as e:
        log.warning("[rental_performance] worst rigs failed: %s", e)
        return {"worst": [], "count": 0, "min_samples": WORST_RIG_MIN_SAMPLES}

    # Per-rig: chronological (sort-key, pct) series + spend exposure. Sort
    # keys come from the shared _parse_start_ts so MRR 'YYYY-MM-DD …' AND
    # RFC3339 starts both order correctly (a lexicographic sort would not);
    # a row whose start never parses falls back to created_ts (same fallback
    # as compute_portfolio_series) so EWMA never reorders it to 'oldest'.
    by_rig: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"name": "", "series": [], "spend_sats": 0.0, "pl_per_thh": []}
    )
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
            pl = compute_rental_pl(
                dthh,
                _num(r["paid_sats"]),
                network_hashrate_hs=_rental_network_hashrate(r),
            )
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
        pl_avg = (
            (sum(b["pl_per_thh"]) / len(b["pl_per_thh"])) if b["pl_per_thh"] else None
        )
        # Same trust-grade engine as the rig track record modal, so the
        # leaderboard and the detail story never disagree (one scoring
        # system — the median-based grade A-F rides along on the danger row).
        trust = compute_rig_trust_score([{"percent": p} for p in pcts])
        worst.append(
            {
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
            }
        )
    worst.sort(key=lambda x: x["danger_score"], reverse=True)
    return {
        "worst": worst[:limit],
        "count": len(worst),
        "min_samples": WORST_RIG_MIN_SAMPLES,
    }


def compute_concentration_risk(
    active: List[Dict], history: List[Dict], owner: List[Dict], contracts: List[Dict]
) -> Dict[str, Any]:
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
    rig_spend: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"name": "", "spend": 0.0}
    )

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
        {
            "provider": p,
            "label": "MRR" if p == "mrr" else "Braiins",
            "spend_sats": round(s),
            "share_pct": round(s / total * 100.0, 1),
        }
        for p, s in prov_spend.items()
    ]
    providers.sort(key=lambda x: x["share_pct"], reverse=True)
    # Herfindahl-Hirschman over provider shares (10000 = fully concentrated).
    hhi = round(sum((s / total * 100.0) ** 2 for s in prov_spend.values()), 1)
    top_rig = None
    if rig_spend:
        rid, g = max(rig_spend.items(), key=lambda kv: kv[1]["spend"])
        top_rig = {
            "rig_id": rid,
            "rig_name": g["name"],
            "spend_sats": round(g["spend"]),
            "share_pct": round(g["spend"] / total * 100.0, 1),
        }
    return {
        "available": True,
        "total_spend_sats": round(total),
        "providers": providers,
        "hhi": hhi,
        "top_provider": providers[0],
        "top_rig": top_rig,
    }


# ── Difficulty-adjustment forecast (market timing, from local snapshots) ───
# When is the next 2016-block retarget, and how much will difficulty move?
# Renting right before a big difficulty SPIKE is like paying yesterday's
# price for tomorrow's fewer blocks. The forecast derives the CURRENT block
# cadence from the LOCAL snapshots table (height deltas over time — the same
# source the halving countdown uses) — zero extra network calls, honest '—'
# when there isn't enough history to measure.

DIFF_TARGET_SECONDS = 2016 * 600.0  # 2016 blocks × 10 min
DIFF_MAX_CHANGE_PCT = 350.0  # protocol cap on a single retarget


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
            "WHERE network_height IS NOT NULL ORDER BY ts DESC LIMIT 100"
        )
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
    avg_block_s = (
        intervals[n // 2]
        if n % 2
        else (intervals[n // 2 - 1] + intervals[n // 2]) / 2.0
    )
    avg_block_s = max(300.0, min(3600.0, avg_block_s))

    blocks_remaining = 2016 - (height % 2016)
    hours_to_adj = blocks_remaining * avg_block_s / 3600.0
    # Projected retarget: new_diff = old_diff × (target_time / actual_epoch_time)
    # → change % = (target / (avg_block_s × 2016) − 1) × 100.
    change_pct = (DIFF_TARGET_SECONDS / (avg_block_s * 2016.0) - 1.0) * 100.0
    change_pct = max(-DIFF_MAX_CHANGE_PCT, min(DIFF_MAX_CHANGE_PCT, change_pct))
    direction = "up" if change_pct > 2.0 else ("down" if change_pct < -2.0 else "flat")
    if direction == "up":
        verdict = (
            f"difficulty projetada +{change_pct:.0f}% no próximo ajuste "
            f"(~{hours_to_adj:.0f}h) — blocos mais rápidos que 10min; "
            f"aluguéis longos que cruzam o ajuste pagam mais caro por menos"
        )
    elif direction == "down":
        verdict = (
            f"difficulty projetada {change_pct:.0f}% no próximo ajuste "
            f"(~{hours_to_adj:.0f}h) — janela barata: alugar agora rende mais "
            f"TH·h por sats"
        )
    else:
        verdict = (
            f"difficulty estável no próximo ajuste (~{hours_to_adj:.0f}h) — "
            f"cadência de blocos alinhada ao alvo de 10min"
        )
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

RENTAL_RISK_ALERTS_SETTING = "rental_risk_alerts"  # "1" enables
RENTAL_RISK_DANGER_SETTING = "rental_risk_danger"  # min danger score (default 50)
RENTAL_RISK_TOP_N_SETTING = "rental_risk_top_n"  # top-N to watch (default 5)
RENTAL_RISK_CONC_PCT_SETTING = (
    "rental_risk_conc_pct"  # top-provider share % (default 55)
)


def _ensure_risk_alert_table() -> None:
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            """CREATE TABLE IF NOT EXISTS rental_risk_alerts (
            tenant_id TEXT NOT NULL DEFAULT '',
            alert_key TEXT NOT NULL,
            alert_value TEXT NOT NULL,
            metric REAL,
            fired_ts INTEGER,
            PRIMARY KEY (tenant_id, alert_key, alert_value)
        )"""
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("[rental_performance] risk-alert table ensure failed: %s", e)


def _mark_risk_alert_fired(
    tenant_id: str, alert_key: str, alert_value: str, metric: Optional[float]
) -> bool:
    """ATOMICALLY claim the dedup slot (INSERT OR IGNORE) — the concurrent
    /api/rentals request loses the race and does NOT double-fire."""
    _ensure_risk_alert_table()
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "INSERT OR IGNORE INTO rental_risk_alerts(tenant_id,alert_key,alert_value,metric,fired_ts) "
            "VALUES(?,?,?,?,?)",
            (tenant_id or "", alert_key, alert_value, metric, int(time.time())),
        )
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
    enabled = str((s.get(RENTAL_RISK_ALERTS_SETTING) or "").strip() or "").lower() in (
        "1",
        "true",
        "on",
        "sim",
    )
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
    return {
        "enabled": enabled,
        "danger": max(0.0, min(100.0, danger)),
        "top_n": max(1, min(20, top_n)),
        "conc_pct": max(10.0, min(100.0, conc_pct)),
    }


def evaluate_risk_alerts(
    tenant_id: str = "",
    concentration: Optional[Dict] = None,
    worst_rigs: Optional[Dict] = None,
) -> List[Dict[str, Any]]:
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
        for w in worst_rigs.get("worst", [])[: cfg["top_n"]]:
            danger = _num(w.get("danger_score"))
            if danger is None or danger < cfg["danger"]:
                continue
            if not _mark_risk_alert_fired(
                tenant_id, "worst_rig", str(w["rig_id"]), danger
            ):
                continue
            out.append(
                _build_risk_alert(
                    f"Rig {w.get('name') or w['rig_id']} (#{w['rig_id']}) entrou no top-{cfg['top_n']} dos PIORES rigs — "
                    f"danger {danger:.0f}/100 · entrega EWMA {_fmt(w.get('ewma_delivery_pct'))}% · "
                    f"fail rate {_fmt(w.get('fail_rate_pct'))}%",
                    severity="CRIT" if danger >= 70 else "WARN",
                    category="rental_risk_rig",
                    value=str(w["rig_id"]),
                    metric=danger,
                )
            )
    except Exception as e:
        log.warning("[rental_performance] risk worst-rig eval failed: %s", e)

    # Concentration: top-provider share crossing the threshold fires once.
    if concentration and concentration.get("available"):
        top = concentration.get("top_provider") or {}
        share = _num(top.get("share_pct"))
        if share is not None and share >= cfg["conc_pct"]:
            prov = str(top.get("provider") or "unknown")
            if _mark_risk_alert_fired(tenant_id, "concentration", prov, share):
                out.append(
                    _build_risk_alert(
                        f"Concentração de portfólio: {share:.0f}% do gasto ({top.get('label') or prov}) — "
                        f"acima do limite de {cfg['conc_pct']:.0f}% (HHI {_num(concentration.get('hhi')):.0f}). "
                        f"Um único provider/rig em falha derruba o livro inteiro.",
                        severity="WARN",
                        category="rental_risk_concentration",
                        value=prov,
                        metric=share,
                    )
                )
    return out


def _fmt(v: Optional[float]) -> str:
    return f"{v:.1f}" if v is not None else "—"


def _build_risk_alert(
    message: str, severity: str, category: str, value: str, metric: Optional[float]
) -> Dict[str, Any]:
    return {
        "severity": severity,
        "category": category,
        "message": message[:280],
        "value": value,
        "metric": metric,
    }


def risk_alert_enabled_tenants() -> List[str]:
    """Tenant ids with risk alerts enabled (for the periodic sweep). The
    worst-rig half of the sweep is LOCAL (zero provider cost), so unlike the
    P/L sweep there is no credential gate — only the opt-in matters."""
    out: List[str] = []
    try:
        _ensure_rig_settings_tables()
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT DISTINCT tenant_id, value FROM tenant_settings WHERE key=?",
            (RENTAL_RISK_ALERTS_SETTING,),
        )
        rows = c.fetchall()
        conn.close()
        for r in rows:
            if str((r["value"] or "")).strip().lower() in ("1", "true", "on", "sim"):
                out.append(r["tenant_id"])
    except Exception:
        pass
    try:
        s = load_settings(tenant_id="")
        if str((s.get(RENTAL_RISK_ALERTS_SETTING) or "")).strip().lower() in (
            "1",
            "true",
            "on",
            "sim",
        ):
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

RENTAL_PL_ALERT_SETTING = "rental_pl_alert_pct"  # e.g. "-50" (empty/0 = off)
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
        c.execute(
            "SELECT DISTINCT tenant_id, value FROM tenant_settings WHERE key=?",
            (RENTAL_PL_ALERT_SETTING,),
        )
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
        # Issue #200: page size 200 (MRR max) so the pagination loop covers
        # the FULL history in ~5 calls max instead of 20 at the old 50.
        listing = fetch_mrr_rentals(
            rtype="renter", history=True, limit=MRR_MAX_PAGE_SIZE, tenant_id=tenant_id
        )
        if not listing.get("success"):
            if listing.get("needs_auth"):
                log.debug(
                    "[rentals-sweep] %s: no MRR credentials", tenant_id or "default"
                )
            else:
                log.warning(
                    "[rentals-sweep] %s: MRR fetch failed: %s",
                    tenant_id or "default",
                    listing.get("error"),
                )
            return []
        history = listing.get("rentals", [])
        try:
            ingest_rentals([], history, [], [], tenant_id=tenant_id)
        except Exception as _ie:
            log.warning(
                "[rentals-sweep] %s: ingest error: %s", tenant_id or "default", _ie
            )
        return history
    except Exception as e:
        log.warning("[rentals-sweep] %s: sweep error: %s", tenant_id or "default", e)
        return []


def sweep_rental_pl_alerts(tenant_id: str = "") -> List[Dict[str, Any]]:
    """One P/L-alert sweep pass for a single tenant: fetch MRR renter history
    (ONE API call), evaluate, ingest, and return the ALERTS. Returns [] when
    nothing to judge or a provider hiccup (logged, never raised)."""
    return evaluate_rental_pl_alerts(
        _sweep_fetch_history(tenant_id), [], tenant_id=tenant_id
    )


def sweep_rental_market_alerts(tenant_id: str = "") -> List[Dict[str, Any]]:
    """One market-overpay sweep pass for a single tenant (same discipline as
    sweep_rental_pl_alerts): ONE MRR history fetch, evaluate overpay vs the
    market at purchase time, ingest, and return the ALERTS."""
    return evaluate_market_overpay_alerts(
        _sweep_fetch_history(tenant_id), [], tenant_id=tenant_id
    )


def _ensure_pl_alert_table() -> None:
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            """CREATE TABLE IF NOT EXISTS rental_pl_alerts (
            tenant_id TEXT NOT NULL DEFAULT '',
            provider TEXT NOT NULL DEFAULT 'mrr',
            rental_id TEXT NOT NULL,
            metric REAL,
            fired_ts INTEGER,
            PRIMARY KEY (tenant_id, provider, rental_id)
        )"""
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("[rental_performance] pl-alert table ensure failed: %s", e)


def _pl_alert_fired(tenant_id: str, provider: str, rental_id: str) -> bool:
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT 1 FROM rental_pl_alerts WHERE tenant_id=? AND provider=? AND rental_id=?",
            (tenant_id or "", provider, rental_id),
        )
        row = c.fetchone()
        conn.close()
        return row is not None
    except Exception:
        return False


def _mark_pl_alert_fired(
    tenant_id: str, provider: str, rental_id: str, metric: Optional[float]
) -> bool:
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
            (tenant_id or "", provider, rental_id, metric, int(time.time())),
        )
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
        c.execute(
            "DELETE FROM rental_pl_alerts WHERE fired_ts < ?",
            (int(time.time()) - RENTAL_PL_ALERT_PRUNE_DAYS * 86400,),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _build_pl_alert(
    provider: str,
    rental_id: Any,
    delivery_pct: Optional[float],
    cost_sats_per_thh: Optional[float],
    pl: Optional[Dict],
    market: Optional[Dict],
) -> Dict[str, Any]:
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


def evaluate_rental_pl_alerts(
    history: List[Dict],
    contracts: Optional[List[Dict]] = None,
    tenant_id: str = "",
    now: Optional[int] = None,
) -> List[Dict[str, Any]]:
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
        cost = (
            (paid_sats / delivered) if (paid_sats is not None and delivered) else None
        )

        pl: Optional[Dict] = None
        fired = False
        if delivered and paid_sats is not None:
            # Historical-P/L fix: judge against the hashrate observed at the
            # rental's time (snapshot lookup, current as last resort).
            pl = compute_rental_pl(
                delivered,
                paid_sats,
                network_hashrate_hs=_resolve_network_hashrate_for_rental(
                    r.get("start"), r.get("end")
                ),
            )
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

RENTAL_MARKET_OVERPAY_SETTING = (
    "rental_market_overpay_pct"  # e.g. "100" (empty/0 = off)
)

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
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_hashrate_market_history_ts ON hashrate_market_history(ts)"
        )
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
            (
                int(ts) - _MARKET_PRICE_WINDOW_S,
                int(ts) + _MARKET_PRICE_WINDOW_S,
                _MIN_PLAUSIBLE_PRICE,
            ),
        )
        row = c.fetchone()
        conn.close()
        if row and row[0]:
            val = float(row[0]) * 1e8 / 24.0  # BTC/TH/day → sats/TH·h
    except Exception as e:
        log.warning("[rental_performance] historical market price lookup failed: %s", e)
    if val and val > 0:
        _market_price_cache[day] = val
    return val


def _tenant_cost_baselines(tenant_id: str = "") -> Dict[str, Optional[float]]:
    """Three unit-cost references (sats/TH·h) from the tenant's OWN rental
    history (renter bucket) — each None when it can't be computed honestly:

      - 'average':   weighted mean of the ADVERTISED cost
                     (SUM paid_sats ÷ SUM advertised_th×hours).
      - 'effective': weighted mean of the DELIVERED cost
                     (SUM paid_sats ÷ SUM delivered_thh) — the REAL cost per
                     TH·h actually received; rises when delivery < 100%.
      - 'last':      the most recent rental's advertised cost — captures the
                     current regime (what the user paid LAST time).

    Used as the arbitrage baseline: a market price far below any of these is
    a real buying window for THIS user."""
    out: Dict[str, Optional[float]] = {"average": None, "effective": None, "last": None}
    try:
        conn = get_db()
        c = conn.cursor()
        # Average: advertised-basis, all paid rentals.
        c.execute(
            "SELECT SUM(paid_sats), SUM(advertised_th * length_hours) "
            "FROM rental_history WHERE tenant_id=? AND bucket='renter' "
            "AND paid_sats > 0 AND advertised_th > 0 AND length_hours > 0",
            (tenant_id or "",),
        )
        row = c.fetchone()
        if row:
            paid = float(row[0] or 0)
            adv_thh = float(row[1] or 0)
            if paid > 0 and adv_thh > 0:
                out["average"] = paid / adv_thh
        # Effective: delivered-basis, ONLY rentals that actually have delivery
        # data (both sides of the ratio) — otherwise spotty delivery records
        # would silently inflate the 'effective' cost.
        c.execute(
            "SELECT SUM(paid_sats), SUM(delivered_thh) FROM rental_history "
            "WHERE tenant_id=? AND bucket='renter' AND paid_sats > 0 "
            "AND delivered_thh > 0",
            (tenant_id or "",),
        )
        row = c.fetchone()
        if row:
            paid = float(row[0] or 0)
            deliv_thh = float(row[1] or 0)
            if paid > 0 and deliv_thh > 0:
                out["effective"] = paid / deliv_thh
        # Last: the most recent rental. start is TEXT in TWO formats (MRR
        # 'YYYY-MM-DD HH:MM:SS UTC' vs Braiins RFC3339 '…T…Z'), so lexical
        # ORDER BY is unreliable — resolve with _parse_start_ts in Python
        # (created_ts as tiebreaker when start is missing/opaque).
        c.execute(
            "SELECT paid_sats, advertised_th, length_hours, start, created_ts "
            "FROM rental_history WHERE tenant_id=? AND bucket='renter' "
            "AND paid_sats > 0 AND advertised_th > 0 AND length_hours > 0",
            (tenant_id or "",),
        )
        rows = c.fetchall()
        conn.close()
        if rows:

            def _sort_key(r):
                ts = _parse_start_ts(r[3])
                if ts is None:
                    ts = r[4] or 0  # created_ts (int) fallback
                return ts

            best = max(rows, key=_sort_key)
            if best[1] and best[2]:
                out["last"] = float(best[0]) / (float(best[1]) * float(best[2]))
    except Exception as e:
        log.warning("[rental_performance] cost baseline lookup failed: %s", e)
    return out


def _recent_market_sats_per_thh(
    now: Optional[int] = None, window_h: float = _ARB_MARKET_WINDOW_H
) -> Optional[float]:
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
            (int(now) - int(window_h * 3600), _MIN_PLAUSIBLE_PRICE),
        )
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
        c.execute(
            "SELECT DISTINCT tenant_id, value FROM tenant_settings WHERE key=?",
            (RENTAL_MARKET_ARB_SETTING,),
        )
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
        c.execute(
            "SELECT DISTINCT tenant_id, value FROM tenant_settings WHERE key=?",
            (RENTAL_MARKET_OVERPAY_SETTING,),
        )
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


def _build_overpay_alert(
    provider: str,
    rental_id: Any,
    cost_sats_per_thh: float,
    market_price: float,
    overpay_pct: float,
) -> Dict[str, Any]:
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


def evaluate_market_overpay_alerts(
    history: List[Dict],
    contracts: Optional[List[Dict]] = None,
    tenant_id: str = "",
    now: Optional[int] = None,
    extra: Optional[List[Dict]] = None,
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
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
    TH·h needed for the agreed price).

    ``dry_run``: compute the signal WITHOUT consulting or claiming the dedup
    slots — used by the panel banner so it stays visible even after the
    webhook already fired (the dispatch path is the ONLY dedup consumer)."""
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
        return (
            live_market.get("price_sats_per_thh")
            if live_market.get("available")
            else None
        )

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
        if not dry_run and _pl_alert_fired(tenant_id, "mrr_overpay", str(rid)):
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
        # dry_run skips the claim so the banner never consumes a slot.
        if not dry_run and not _mark_pl_alert_fired(
            tenant_id, "mrr_overpay", str(rid), round(overpay_pct, 1)
        ):
            continue
        out.append(
            _build_overpay_alert(
                "mrr", rid, cost_sats_per_thh, market_price, overpay_pct
            )
        )
    return out


# ── Arbitrage-opportunity alerts (market vs the tenant's own avg cost) ─────

_ARB_REF_LABEL = {
    "average": "custo médio",
    "effective": "custo efetivo (entrega real)",
    "last": "último aluguel",
}


def _build_arb_alert(
    bases: Dict[str, Optional[float]],
    ref_key: str,
    market_price: float,
    discount_pct: float,
    suggested_th: Optional[float] = None,
) -> Dict[str, Any]:
    """Opportunity payload: category market_arb — GOLD when the discount is
    extreme (≥50%), WARN otherwise. Reports ALL three baselines (média,
    efetivo, último) + which one drove the signal, so the user sees the
    context behind the window. ``suggested_th`` = the tenant's typical order
    size (median TH/s) for prefilling the buy modal."""
    severity = "GOLD" if discount_pct >= 50.0 else "WARN"
    ref_cost = bases.get(ref_key) or 0.0
    label = _ARB_REF_LABEL.get(ref_key, ref_key)
    parts = []
    if bases.get("average"):
        parts.append(f"média {bases['average']:.0f}")
    if bases.get("effective"):
        parts.append(f"efetivo {bases['effective']:.0f}")
    if bases.get("last"):
        parts.append(f"último {bases['last']:.0f}")
    ctx = f" ({' · '.join(parts)})" if parts else ""
    message = (
        f"ARBITRAGEM: mercado a {market_price:.0f} sats/TH·h — {discount_pct:.0f}% "
        f"abaixo do seu {label} ({ref_cost:.0f} sats/TH·h){ctx}. Janela de compra!"
    )[:280]
    return {
        "severity": severity,
        "category": "market_arb",
        "message": message,
        "rental_id": "",
        "provider": "mrr",
        "avg_cost_sats_per_thh": round(bases.get("average") or 0, 1),
        "effective_cost_sats_per_thh": round(bases.get("effective") or 0, 1),
        "last_cost_sats_per_thh": round(bases.get("last") or 0, 1),
        "ref_basis": ref_key,
        "market_price_sats_per_thh": round(market_price, 1),
        "discount_pct": round(discount_pct, 1),
        "suggested_th": round(suggested_th or 0, 1),
    }


def _tenant_typical_th(tenant_id: str = "") -> Optional[float]:
    """Median advertised TH/s across the tenant's past rentals (renter
    bucket) — a robust 'typical order size' for prefilling the Braiins spot
    buy modal (median resists outliers better than the mean). None when no
    usable history (frontend falls back to 1000 TH ≈ 1 PH/s)."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT advertised_th FROM rental_history "
            "WHERE tenant_id=? AND bucket='renter' AND advertised_th > 0",
            (tenant_id or "",),
        )
        vals = sorted(float(r[0]) for r in c.fetchall())
        conn.close()
        if not vals:
            return None
        n = len(vals)
        mid = n // 2
        med = vals[mid] if n % 2 == 1 else (vals[mid - 1] + vals[mid]) / 2.0
        # Round to a clean step (nearest 100 TH, min 100) so the buy-modal
        # prefill feels deliberate (e.g. 2533.7 → 2500) instead of awkward.
        return max(100.0, round(med / 100.0) * 100.0)
    except Exception as e:
        log.warning("[rental_performance] typical TH lookup failed: %s", e)
    return None


def evaluate_market_arb_alerts(
    tenant_id: str = "", now: Optional[int] = None, dry_run: bool = False
) -> List[Dict[str, Any]]:
    """Arbitrage opportunity: when the CURRENT market price (cheapest quote)
    is ≥ X% BELOW the tenant's own cost references → fire a per-tenant
    webhook/push ('compre agora' window).

    Three baselines from the tenant's rental_history (renter bucket): the
    advertised AVERAGE, the DELIVERED/effective cost (paid ÷ TH·h actually
    received — delivery < 100% raises it), and the LAST rental's cost. The
    reference used is the HIGHEST of the available baselines: if the market
    is ≥ X% below even the user's most expensive reference, it's a genuine
    window — and the message reports all three so the user sees the context.

    Local-first and provider-free: baselines come from the tenant's OWN
    rental_history and the market price from the local hashrate_market_history
    table (last 12h; ±3d fallback). So this family needs NO MRR credentials —
    gating is purely the threshold setting.

    Dedup: ONE alert per cooldown window (rental_market_arb_cooldown_hours,
    default 24h) — a persistently cheap market repeats the signal daily
    instead of spamming every sweep. Persisted in the shared rental_pl_alerts
    table with provider tag 'mrr_arb' and a bucket key as rental_id.

    ``dry_run``: compute the window WITHOUT claiming the cooldown dedup slot —
    used by the panel banner so the open window stays visible even after the
    webhook already fired (the dispatch path is the ONLY dedup consumer).
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
    # Baselines: never a fabricated number — no history = honest skip.
    bases = _tenant_cost_baselines(tenant_id)
    usable = {k: v for k, v in bases.items() if v and v > 0}
    if not usable:
        return []
    market_price = _recent_market_sats_per_thh(now)
    if not market_price or market_price <= 0:
        return []  # no market reference at all → honest skip
    # Reference = the HIGHEST baseline (most conservative signal): if the
    # market is ≥ X% below even the user's most expensive cost, it's a real
    # buying window. Ties break by an explicit priority (the more truthful
    # reference wins): effective (delivered reality) > last (recent regime)
    # > average.
    ref_key = max(
        usable, key=lambda k: (usable[k], {"effective": 2, "last": 1, "average": 0}[k])
    )
    ref_cost = usable[ref_key]
    discount_pct = (1.0 - market_price / ref_cost) * 100.0
    if discount_pct < threshold:
        return []  # market not cheap enough vs MY costs
    # Dedup: one alert per cooldown bucket (atomic claim, race-safe).
    # dry_run skips the claim so the banner never consumes the slot.
    bucket = int(now // (cooldown_h * 3600.0))
    dedup_id = f"arb-{bucket}"
    if not dry_run and not _mark_pl_alert_fired(
        tenant_id, "mrr_arb", dedup_id, round(discount_pct, 1)
    ):
        return []
    return [
        _build_arb_alert(
            bases, ref_key, market_price, discount_pct, _tenant_typical_th(tenant_id)
        )
    ]


# ── Auto-alert: accepted recommendation ended with verdict 'worse' ──────────
# The operator accepted a pilot recommendation (blacklisted a bad rig). When
# the delivery outcome afterwards comes back WORSE (the rig kept under-
# delivering after the exclusion), the blacklist didn't fix the problem —
# that deserves a proactive webhook/push, not only a panel badge.
#
# Local-first and provider-free: the ledger (tenant settings) + local
# rental_history — zero provider cost, so NO MRR credentials required;
# gating is purely the enable setting. Revoked entries (restored rigs) are
# NEVER flagged — a revoked decision is not 'worse', it was reversed.
RENTAL_RECO_WORSE_SETTING = "rental_reco_worse_alert"  # "1"/"0" (default off)


def reco_worse_enabled_tenants() -> List[str]:
    """Tenant ids that should be swept for accepted-recommendation 'worse'
    alerts.

    LOCAL evaluation (ledger + local history — zero provider cost), so no
    MRR credentials gate the sweep: the setting alone decides. Default/
    operator tenant included when its GLOBAL setting is enabled."""
    out: List[str] = []
    try:
        _ensure_rig_settings_tables()
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT DISTINCT tenant_id, value FROM tenant_settings WHERE key=?",
            (RENTAL_RECO_WORSE_SETTING,),
        )
        rows = c.fetchall()
        conn.close()
        for r in rows:
            if (r["value"] or "").strip() == "1":
                out.append(r["tenant_id"])
    except Exception as e:
        log.warning("[rental_performance] reco-worse tenant scan failed: %s", e)
    try:
        s = load_settings(tenant_id="")
        if (s.get(RENTAL_RECO_WORSE_SETTING) or "").strip() == "1":
            out.append("")
    except Exception:
        pass
    return list(dict.fromkeys(out))


def _build_reco_worse_alert(e: Dict[str, Any]) -> Dict[str, Any]:
    """Alert payload for an accepted recommendation that ended WORSE.
    Severity WARN, category rental_reco_worse — concise for both webhook
    embeds and Web Push."""
    name = e.get("name") or e.get("rig_id") or ""
    parts = [f"Recomendação aceita PIOROU: rig {name}"]
    before = e.get("delivery_pct")
    after = e.get("delivery_after_pct")
    if before is not None and after is not None:
        parts.append(f"entrega {before:.0f}% → {after:.0f}% após o blacklist")
    elif after is not None:
        parts.append(f"entrega {after:.0f}% após o blacklist")
    if e.get("samples") is not None:
        parts.append(f"{e['samples']} amostras")
    src = "auto" if e.get("source") == "auto" else "manual"
    parts.append(f"origem: {src}")
    return {
        "severity": "WARN",
        "category": "rental_reco_worse",
        "message": " — ".join(parts)[:280],
        "rig_id": str(e.get("rig_id") or ""),
    }


# ── Auto-exclusion alert (sweep fires webhook/push when the pilot bars a rig) ──
# The auto-exclusion itself is DEFAULT protection (runs for every tenant with
# a local track record, no opt-in). The ALERT is opt-in like the other rental
# families: when the periodic sweep excludes a rig, the tenant that enabled
# this setting gets webhook + push with the SAME readable cause the panel
# shows (Issue #100) — zero drift between the history and the alert.
AUTO_EXCLUDE_ALERT_SETTING = "rental_auto_exclude_alert"  # "1"/"0" (default off)


def build_auto_exclude_alert(
    rig_id: Any, tenant_id: str = ""
) -> Optional[Dict[str, Any]]:
    """One alert dict for a rig the sweep JUST auto-excluded.

    Opt-in (rental_auto_exclude_alert == '1'); the message reuses the
    auto-exclusion history cause: "rig <name> auto-excluído por sub-entrega —
    <cause>". Returns None when the tenant is not opted in or the rig has no
    ledger entry (or on any storage hiccup). Never raises."""
    try:
        s = load_settings(tenant_id=tenant_id)
        if (s.get(AUTO_EXCLUDE_ALERT_SETTING) or "").strip() != "1":
            return None
        rid = str(rig_id)
        for e in auto_exclusion_history(tenant_id=tenant_id)["exclusions"]:
            if e.get("rig_id") == rid:
                name = e.get("name") or e.get("rig_id") or rid
                cause = e.get("cause") or "sub-entrega"
                return {
                    "severity": "WARN",
                    "category": "rental_auto_exclude",
                    "message": (
                        f"rig {name} auto-excluído por sub-entrega — {cause}"[:280]
                    ),
                    "ts": e.get("ts") or 0,
                }
    except Exception as e:
        log.warning("[rental_performance] auto-exclude alert build failed: %s", e)
    return None


def evaluate_reco_worse_alerts(
    tenant_id: str = "", now: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Accepted recommendations whose outcome is WORSE → alerts.

    Reads the tenant's accepted-recommendation ledger (local, provider-free)
    and keeps only entries with verdict 'worse' AND not restored (revoked
    decisions are reversed, not worse). Dedup: ONE alert per rig EVER
    (persisted in the shared rental_pl_alerts table with provider tag
    'reco_worse' and the rig id as rental_id — same race-safe atomic claim
    as the P/L family).

    Gating: the setting rental_reco_worse_alert must be "1". Never raises.
    """
    s = load_settings(tenant_id=tenant_id)
    if (s.get(RENTAL_RECO_WORSE_SETTING) or "").strip() != "1":
        return []  # disabled
    now = int(now or time.time())
    _prune_pl_alerts()
    summary = compute_accepted_recos_summary(tenant_id=tenant_id)
    out: List[Dict[str, Any]] = []
    for e in summary.get("accepted", []):
        if e.get("verdict") != "worse":
            continue
        if e.get("restored"):
            continue  # revoked decision ≠ worse
        rid = str(e.get("rig_id") or "")
        if not rid:
            continue
        if not e.get("delivery_after_pct") or not e.get("delivery_pct"):
            continue  # no before/after reference → cannot honestly call it worse
        # Atomic claim: only the winner fires (race-safe, panel + sweep).
        metric = round(float(e["delivery_after_pct"]), 1)
        if not _mark_pl_alert_fired(tenant_id, "reco_worse", rid, metric):
            continue
        out.append(_build_reco_worse_alert(e))
    return out


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
        c.execute(
            """CREATE TABLE IF NOT EXISTS rental_history (
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
        )"""
        )
        # Migration: tables created before the owner/renter split lack the
        # bucket column — legacy rows default to 'renter' (behavior preserved;
        # new ingests mark owner rentals correctly).
        try:
            cols = {
                row[1]
                for row in c.execute("PRAGMA table_info(rental_history)").fetchall()
            }
            if "bucket" not in cols:
                c.execute(
                    "ALTER TABLE rental_history ADD COLUMN bucket TEXT NOT NULL DEFAULT 'renter'"
                )
            # Migration: tables created before the historical-P/L fix lack
            # network_hashrate_hs — legacy rows keep NULL and self-heal on
            # the next ingest (ON CONFLICT updates it), and every consumer
            # falls back to the snapshots table / current hashrate meanwhile.
            if "network_hashrate_hs" not in cols:
                c.execute(
                    "ALTER TABLE rental_history ADD COLUMN network_hashrate_hs REAL"
                )
        except Exception:
            pass
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("[rental_performance] history table ensure failed: %s", e)


def _rental_to_history_row(
    r: Dict[str, Any], provider: str = "mrr", bucket: str = "renter"
) -> Dict[str, Any]:
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
    cost = (
        (paid_sats / delivered_thh)
        if (paid_sats is not None and delivered_thh)
        else None
    )
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
                (
                    tenant_id or "",
                    r["provider"],
                    r.get("bucket", "renter"),
                    r["rental_id"],
                    r["rig_id"],
                    r["rig_name"],
                    r.get("start"),
                    r.get("end"),
                    r["percent"],
                    r["avg_th"],
                    r["advertised_th"],
                    r.get("cost_sats_per_thh"),
                    r.get("length_hours"),
                    r.get("delivered_thh"),
                    r.get("paid_sats"),
                    r.get("network_hashrate_hs"),
                    ts,
                ),
            )
        conn.commit()
        return True
    except Exception as e:
        log.warning("[rental_performance] history save failed: %s", e)
        return False
    finally:
        conn.close()


def get_local_rig_history(
    rig_id: Any = None,
    rig_name: str = "",
    exclude_rental_id: Any = None,
    tenant_id: str = "",
) -> List[Dict[str, Any]]:
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
    return [
        {
            "id": row["rental_id"],
            "start": row["start"],
            "percent": row["percent"],
            "avg_th": row["avg_th"],
            "advertised_th": row["advertised_th"],
            "cost_sats_per_thh": row["cost_sats_per_thh"],
            "length_hours": row["length_hours"],
        }
        for row in rows
    ]


def ingest_rentals(
    active: List[Dict],
    history: List[Dict],
    owner: List[Dict],
    contracts: List[Dict],
    tenant_id: str = "",
) -> bool:
    """Persist every bucket from the panel list fetch into local history.
    Called by /api/rentals once per fetch — the same-rig track record then
    builds up with zero extra provider calls on detail clicks."""
    rows: List[Dict] = []
    # Owner rentals are the operator's rigs leased OUT — money RECEIVED. They
    # must never be counted as spend by the renter analytics (portfolio
    # series, worst-rigs, heatmap), so the bucket column separates them.
    for _bname, _bucket in (("renter", active), ("renter", history), ("owner", owner)):
        for r in _bucket:
            if isinstance(r, dict):
                rows.append(_rental_to_history_row(r, provider="mrr", bucket=_bname))
    for c in contracts or []:
        speed_limit_ph = c.get("speed_limit_ph")
        limit_th = (speed_limit_ph * PH_TO_TH) if speed_limit_ph is not None else None
        rows.append(
            {
                "provider": "braiins",
                "rental_id": str(c.get("id") or ""),
                "rig_id": "",
                "rig_name": "Braiins contract",
                "start": c.get("started_at"),
                "end": c.get("ended_at"),
                "percent": None,
                "avg_th": limit_th,
                "advertised_th": limit_th,
                "cost_sats_per_thh": None,
                "length_hours": None,
                "delivered_thh": None,
                "paid_sats": c.get("amount_sat"),
            }
        )
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
    for fmt in (
        "%Y-%m-%d %H:%M:%S UTC",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    ):
        try:
            # MRR/RFC3339 strings are UTC — parse as UTC-aware so weekly
            # bucketing never shifts by the server's local offset.
            return (
                _dt.datetime.strptime(s, fmt)
                .replace(tzinfo=_dt.timezone.utc)
                .timestamp()
            )
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


def _resolve_network_hashrate_for_rental(
    start_value, end_value=None, current_fallback: bool = True
) -> Optional[float]:
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
        _row_get(row, "start"), _row_get(row, "end")
    )


def _series_bucket_key(dt, bucket: str) -> str:
    """Bucket label shared by the portfolio series and its drill-down: ISO
    week ("2026-W30") or calendar month ("2026-07")."""
    if bucket == "week":
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    return f"{dt.year:04d}-{dt.month:02d}"


def _bucket_elapsed_days(
    label: str, bucket: str, now_ts: Optional[float] = None
) -> int:
    """Days inside a series bucket, capped at the present for the CURRENT
    partial bucket (Issue #146 — self-mining EV attribution).

    A past week = 7 days, a past month = its calendar days; the current
    bucket counts only the days elapsed so far (today included); a future
    bucket (clock skew / imported rows) = 0 → no EV is attributed, never a
    fabricated number. Unparseable labels degrade to 0 (the caller then
    renders None, never 0 sats of EV).
    """
    import calendar as _cal
    import datetime as _dt

    try:
        now = _dt.datetime.fromtimestamp(
            now_ts if now_ts is not None else _dt.time(), tz=_dt.timezone.utc
        )
        if bucket == "week":
            iso_y, iso_w = (int(x) for x in label.split("-W"))
            # Monday of the ISO week (week 1 = the week containing Jan 4th).
            jan4 = _dt.datetime(iso_y, 1, 4, tzinfo=_dt.timezone.utc)
            bucket_start = (
                jan4
                - _dt.timedelta(days=jan4.isocalendar()[2] - 1)
                + _dt.timedelta(weeks=iso_w - 1)
            )
            full = 7
        else:
            y, m = (int(x) for x in label.split("-"))
            full = _cal.monthrange(y, m)[1]
            bucket_start = _dt.datetime(y, m, 1, tzinfo=_dt.timezone.utc)
        elapsed = (now - bucket_start).days + 1  # today counts as one day
        return max(0, min(full, elapsed))
    except Exception:
        return 0


def series_bucket_rentals(
    tenant_id: str = "", bucket: str = "week", label: str = ""
) -> List[Dict[str, Any]]:
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
        c.execute(
            "SELECT * FROM rental_history WHERE tenant_id=? AND bucket='renter'",
            (tenant_id or "",),
        )
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
        pl = compute_rental_pl(
            _num(r["delivered_thh"]),
            paid,
            network_hashrate_hs=_rental_network_hashrate(r),
        )
        nhr = _to_float(_row_get(r, "network_hashrate_hs"))
        out.append(
            {
                "provider": r["provider"],
                "rental_id": r["rental_id"],
                "rig_id": r["rig_id"],
                "rig_name": r["rig_name"],
                "start": r["start"],
                "spent_sats": round(paid) if paid is not None else None,
                "delivered_thh": (
                    round(_num(r["delivered_thh"]), 1)
                    if _num(r["delivered_thh"])
                    else None
                ),
                "network_hashrate_hs": round(nhr) if (nhr and nhr > 0) else None,
                "pl_sats": (
                    round(pl.get("pl_sats"), 1)
                    if pl.get("pl_sats") is not None
                    else None
                ),
            }
        )
    out.sort(key=lambda x: x["start"] or "")
    return out


def compute_portfolio_series(
    tenant_id: str = "",
    bucket: str = "week",
    created_ts_fallback: bool = True,
    own_ev_daily_sats: Optional[float] = None,
    now_ts: Optional[float] = None,
) -> Dict[str, Any]:
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
        direction at a glance;
      - OWN MINING EV (Issue #146, 21-C): when ``own_ev_daily_sats`` is
        passed (self-mining EV/day from compute_own_mining_ev, current
        hashrate × pinned yield), each bucket also carries ``own_ev_sats``
        (daily EV × days in the bucket — capped at the present for the
        current partial bucket, 0 for future buckets), ``total_pl_sats``
        (rentals P/L + own EV, None unless BOTH are known) and
        ``cum_total_sats`` (running cumulative of the total — unknown from
        the first bucket whose total is unknown). The EV is a CONSTANT
        per-day estimate (labeled ESTIMATE); buckets only exist where
        rentals were ingested, so a silent week with no rentals still shows
        no point (unchanged behaviour).

    Returns {"bucket", "estimate": True, "own_ev_estimate": bool,
    "own_ev_daily_sats": float|None, "points": [{label, spent_sats,
    delivered_thh, pl_sats, cum_pl_sats, own_ev_sats, total_pl_sats,
    cum_total_sats, rentals, rental_ids}], "totals": {...}} — rental_ids
    powers the chart drill-down.
    """
    bucket = bucket if bucket in ("week", "month") else "week"
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT * FROM rental_history WHERE tenant_id=? AND bucket='renter'",
            (tenant_id or "",),
        )
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
            agg[key] = {
                "label": key,
                "spent_sats": 0.0,
                "delivered_thh": 0.0,
                "pl_sats": 0.0,
                "pl_known": 0,
                "rentals": 0,
                "rental_ids": [],
            }
            order.append(key)
        paid = _num(r["paid_sats"])
        if paid is not None:
            agg[key]["spent_sats"] += paid
        # Historical-P/L fix: price each past rental against the network
        # hashrate observed at its time (persisted/snapshot/current fallback).
        pl = compute_rental_pl(
            _num(r["delivered_thh"]),
            paid,
            network_hashrate_hs=_rental_network_hashrate(r),
        )
        if pl.get("pl_sats") is not None:
            agg[key]["pl_sats"] += pl["pl_sats"]
            agg[key]["pl_known"] += 1
        if _num(r["delivered_thh"]):
            agg[key]["delivered_thh"] += _num(r["delivered_thh"])
        agg[key]["rentals"] += 1
        agg[key]["rental_ids"].append(str(r["rental_id"]))

    # Own mining EV per bucket (Issue #146 / 21-C): constant daily estimate
    # × days in the bucket. None when no hashrate/EV was provided.
    own_ev_daily = _num(own_ev_daily_sats)
    if own_ev_daily is not None and own_ev_daily <= 0:
        own_ev_daily = None

    points = []
    cum = 0.0
    cum_known = True
    cum_total = 0.0
    cum_total_known = True
    for key in sorted(order):
        g = agg[key]
        if g["pl_known"]:
            cum += g["pl_sats"]
        else:
            cum_known = False  # once unknown, cumulative is unknown too
        # EV: days in the bucket (partial current bucket capped; 0 for a
        # future bucket → None, never a fabricated 0-sats EV).
        own_ev = None
        if own_ev_daily is not None:
            _days = _bucket_elapsed_days(key, bucket, now_ts)
            if _days > 0:
                own_ev = round(own_ev_daily * _days)
        total_pl = None
        if own_ev is not None and g["pl_known"]:
            total_pl = round(g["pl_sats"] + own_ev, 1)
        if total_pl is not None:
            cum_total += total_pl
        else:
            cum_total_known = False
        points.append(
            {
                "label": g["label"],
                "spent_sats": round(g["spent_sats"]),
                "delivered_thh": (
                    round(g["delivered_thh"], 1) if g["delivered_thh"] else None
                ),
                # None (not 0.0) when nothing computable — the UI shows '—'.
                "pl_sats": round(g["pl_sats"], 1) if g["pl_known"] else None,
                "cum_pl_sats": round(cum, 1) if cum_known else None,
                # Self-mining EV (Issue #146) + consolidated totals.
                "own_ev_sats": own_ev,
                "total_pl_sats": total_pl,
                "cum_total_sats": (round(cum_total, 1) if cum_total_known else None),
                "rentals": g["rentals"],
                # Click-first drill-down: the ids of every rental in the bucket so
                # the chart can open the exact list behind a bar/week.
                "rental_ids": g["rental_ids"][:300],
            }
        )
    known_totals = [g for g in agg.values() if g["pl_known"]]
    own_known = own_ev_daily is not None and bool(points)
    own_ev_total = (
        round(sum(p["own_ev_sats"] for p in points if p["own_ev_sats"] is not None))
        if own_known
        else None
    )
    totals_pl = (
        round(sum(g["pl_sats"] for g in known_totals), 1) if known_totals else None
    )
    totals_total = None
    if own_ev_total is not None and totals_pl is not None:
        totals_total = round(totals_pl + own_ev_total, 1)
    return {
        "bucket": bucket,
        "estimate": True,  # P/L uses the CURRENT network hashrate — honest label
        # Issue #146: the own-mining EV entered the account (constant daily
        # estimate) — the UI appends the ESTIMATE note when this is true.
        "own_ev_estimate": own_known,
        "own_ev_daily_sats": round(own_ev_daily) if own_ev_daily is not None else None,
        "points": points,
        "totals": {
            "spent_sats": round(sum(g["spent_sats"] for g in agg.values())),
            "pl_sats": totals_pl,
            "own_ev_sats": own_ev_total,
            "total_pl_sats": totals_total,
            "rentals": sum(g["rentals"] for g in agg.values()),
        },
    }


def compute_portfolio_summary(
    active: List[Dict], history: List[Dict], owner: List[Dict], contracts: List[Dict]
) -> Dict[str, Any]:
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
                d = (
                    (float(avg_th) * float(lenh))
                    if (avg_th is not None and lenh)
                    else None
                )
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
            "avg_cost_sats_per_thh": (
                round(weighted_paid / delivered, 2) if delivered else None
            ),
            "avg_delivery_pct": round(sum(pcts) / len(pcts), 1) if pcts else None,
        }

    return {
        "spend": _agg([active, history]),
        "income": _agg([owner]),
        "split": {
            "mrr": len(active) + len(history) + len(owner),
            "braiins": len(contracts or []),
        },
        "counts": {
            "active": len(active),
            "history": len(history),
            "owner": len(owner),
            "contracts": len(contracts or []),
        },
    }


# ── Portfolio 21-A: consolidated P/L — own mining EV + rentals P/L ──────────
# The portfolio panels (summary + series) cover RENTALS only. This family
# brings the "próprio" (self-mining) into the same view so the operator sees
# the TOTAL net P/L: expected-value revenue from owned hashrate (same share-
# of-network EV math as the hash market) combined with the rentals P/L.


def compute_own_mining_ev(
    hashrate_hs: Optional[float],
    network_hashrate_hs: Optional[float],
    days: int = 30,
) -> Dict[str, Any]:
    """Expected-value revenue from SELF-MINING hashrate (Issue #21-A).

    Reuses the PINNED yield formula (compute_expected_yield_sats_per_thh,
    18.75 sats/TH·h @ 100 EH/s) — one source of truth for the share-of-
    network EV math, so a rented TH and an owned TH are priced identically.
    Honest label: ESTIMATE (gross, pre-pool-fee; EV, not realized revenue).
    Null-safe: missing hashrate or unknown network → None fields + the UI
    renders '—', never a fake number.
    """
    try:
        hr = float(hashrate_hs or 0)
    except (TypeError, ValueError):
        hr = 0.0
    base = {
        "hashrate_hs": round(hr) if hr > 0 else None,
        "hashrate_th": round(hr / 1e12, 2) if hr > 0 else None,
        "daily_revenue_sats": None,
        "month_revenue_sats": None,
        "estimate": False,
        "days": days,
    }
    if hr <= 0:
        return base
    # yield = sats/TH·h (None quando a rede é desconhecida → honesto '—').
    yield_thh = compute_expected_yield_sats_per_thh(network_hashrate_hs)
    if yield_thh is None:
        return base
    daily_sats = yield_thh * (hr / 1e12) * 24.0
    base["daily_revenue_sats"] = round(daily_sats)
    base["month_revenue_sats"] = round(daily_sats * days)
    base["estimate"] = True
    return base


def compute_exposure_allocation(
    own_hashrate_th: Optional[float] = None,
    mrr_hashrate_th: Optional[float] = None,
    braiins_hashrate_th: Optional[float] = None,
) -> Dict[str, Any]:
    """Alocação de exposição por classe de ativo (Issue #21-B).

    PRÓPRIO (self-mining) vs MRR vs BRAIINS — share do hashrate total
    gerenciado (TH/s). O Herfindahl-Hirschman (HHI) aqui é ESTENDIDO para
    incluir o próprio como ativo: é o mesmo índice do concentration_risk
    (0-10000; ≥2500 concentração moderada, ≥5000 alta), mas sobre as 3
    classes de exposição — se 90% do hashrate gerenciado é de uma classe
    só, um apagão/mercado daquela classe atinge o portfólio inteiro.

    Honesto: ``available: False`` quando NENHUMA classe tem hashrate
    mensurável (frio) — a UI renderiza '—', nunca um falso 'diversificado'.
    Todas as entradas em TH/s (o app converte os legs: own hs/1e12,
    rentals advertised_th, contratos perf.limit_th).
    """
    legs = {
        "own": _num(own_hashrate_th),
        "mrr": _num(mrr_hashrate_th),
        "braiins": _num(braiins_hashrate_th),
    }
    legs = {k: v for k, v in legs.items() if v and v > 0}
    if not legs:
        return {"available": False}
    total = sum(legs.values())
    classes = [
        {
            "class": k,
            "label": "PRÓPRIO" if k == "own" else ("MRR" if k == "mrr" else "Braiins"),
            "hashrate_th": round(v, 2),
            "share_pct": round(v / total * 100.0, 1),
        }
        for k, v in legs.items()
    ]
    classes.sort(key=lambda x: x["share_pct"], reverse=True)
    hhi = round(sum((v / total * 100.0) ** 2 for v in legs.values()), 1)
    top = classes[0]
    verdict = (
        "alta concentração"
        if hhi >= 5000
        else ("concentração moderada" if hhi >= 2500 else "diversificado")
    )
    return {
        "available": True,
        "total_hashrate_th": round(total, 2),
        "classes": classes,
        "hhi": hhi,
        "hhi_verdict": verdict,
        "top_class": top,
    }


def compute_global_portfolio(
    own_hashrate_hs: Optional[float] = None,
    network_hashrate_hs: Optional[float] = None,
    rentals_pl_30d_sats: Optional[float] = None,
    rentals_30d_count: int = 0,
    rentals_pl_all_sats: Optional[float] = None,
    rentals_spent_sats: Optional[float] = None,
    rentals_count: int = 0,
    own_detail: Optional[Dict[str, Any]] = None,
    days: int = 30,
) -> Dict[str, Any]:
    """Consolidated portfolio P/L: PRÓPRIO (self-mining EV) + RENTALS P/L.

    ``combined.pl_30d_sats`` = own EV (30d) + rentals P/L (last ~4 weeks) —
    the single honest "net" number for the period, labeled ESTIMATE. When
    either leg is unknown, combined is None (never a fake 0 that reads as
    'no loss'). ``own_detail`` (from the app's hashrate dedup) is merged into
    ``own`` so the UI can show WHICH source backed the hashrate (fleet vs
    pool worker) — Issue #21-A dedup rule.
    """
    own = compute_own_mining_ev(own_hashrate_hs, network_hashrate_hs, days=days)
    if own_detail:
        own.update({k: v for k, v in own_detail.items() if k not in own})
    rentals = {
        "pl_30d_sats": (
            round(rentals_pl_30d_sats, 1) if rentals_pl_30d_sats is not None else None
        ),
        "count_30d": int(rentals_30d_count or 0),
        "pl_all_sats": (
            round(rentals_pl_all_sats, 1) if rentals_pl_all_sats is not None else None
        ),
        "spent_sats": round(rentals_spent_sats) if rentals_spent_sats else None,
        "count": int(rentals_count or 0),
        "estimate": True,  # rentals P/L é EV (mesma metodologia da série)
    }
    combined = None
    if own.get("month_revenue_sats") is not None and rentals["pl_30d_sats"] is not None:
        combined = {
            "pl_30d_sats": own["month_revenue_sats"] + rentals["pl_30d_sats"],
            "own_ev_30d_sats": own["month_revenue_sats"],
            "rentals_pl_30d_sats": rentals["pl_30d_sats"],
            "estimate": True,
        }
    return {"own": own, "rentals": rentals, "combined": combined, "days": days}


# ── CFO recommendation engine: "where to rent again" ───────────────────────
# The single decision the operator makes every time: WHICH rig/provider to
# rent next. Builds on the local track record (reliability = trust score)
# × the live market (price quality = avg cost vs cheapest today) and returns
# a ranked shortlist + an avoid list. Honest: needs a track record — a rig
# with zero samples never appears in "top".


def build_rental_recommendations(tenant_id: str = "", top_n: int = 3) -> Dict[str, Any]:
    """Rank MRR rigs worth re-renting from the LOCAL track record.

    Score = 0.6 × reliability (trust.score 0-100, median-based) +
            0.4 × price quality (avg cost vs live market, capped at 1.5×
            cheaper = 100). Excludes manual + auto blacklists.

    Returns {"top": [rig...], "avoid": [rig...], "avoid_count": n,
             "tracked": n, "market": {...}} — empty top/avoid when no
    track record exists yet.

    ``avoid`` is the pilot's full case: every grade-F rig with the SAME
    fields as ``top`` (median/worst delivery, cost, trend, last rental),
    sorted worst-first (lowest median delivery). The operator accepts the
    suggestion in ONE click (blacklist) straight from the card.
    """
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT rig_id, rig_name, percent, cost_sats_per_thh, start "
            "FROM rental_history WHERE tenant_id=? AND provider='mrr' AND rig_id!='' "
            "AND bucket='renter'",
            (tenant_id or "",),
        )
        rows = c.fetchall()
        conn.close()
    except Exception:
        return {
            "top": [],
            "avoid": [],
            "avoid_count": 0,
            "tracked": 0,
            "market": {"available": False},
        }

    by_rig: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        rid = r["rig_id"]
        b = by_rig.setdefault(
            rid, {"name": r["rig_name"] or "", "samples": [], "costs": [], "starts": []}
        )
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

    def _rig_card(
        rid: str,
        b: Dict[str, Any],
        trust: Dict[str, Any],
        avg_cost: Optional[float],
        vs_mkt: Optional[float],
        trend: Optional[float],
    ) -> Dict[str, Any]:
        """Shared card shape for top + avoid entries (one schema, no drift)."""
        starts = sorted(b["starts"])
        return {
            "rig_id": rid,
            "name": b["name"],
            "grade": trust.get("grade"),
            "median_pct": trust.get("median_pct"),
            "worst_pct": trust.get("worst_pct"),
            "samples": trust.get("samples"),
            "avg_cost_sats_per_thh": round(avg_cost, 2) if avg_cost else None,
            "vs_market_pct": round(vs_mkt, 1) if vs_mkt is not None else None,
            "trend_pct": trend,
            "last_rental": starts[-1] if starts else None,
        }

    top: List[Dict[str, Any]] = []
    avoid: List[Dict[str, Any]] = []
    for rid, b in by_rig.items():
        # Chronological order for the trend (see the note at collection).
        samples = sorted(b["samples"], key=lambda x: x[0])
        pcts = [p for _, p in samples]
        trust = compute_rig_trust_score([{"percent": p} for p in pcts])
        if trust.get("samples", 0) < 1:
            continue
        if rid in manual or rid in auto:
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
            recent = sum(pcts[-3:]) / 3.0  # NEWEST 3
            older = sum(pcts[:-3]) / (len(pcts) - 3)
            trend = round(recent - older, 1)
        card = _rig_card(rid, b, trust, avg_cost, vs_mkt, trend)
        if trust.get("grade") == "F":
            # Pilot's avoid case — detailed card (the operator can accept it
            # in one click from the panel). Keep the score too: the same
            # 0.6×rel + 0.4×price formula ranks how BAD the rig is.
            card["score"] = score
            avoid.append(card)
            continue
        card["score"] = score
        top.append(card)
    top.sort(key=lambda x: x["score"], reverse=True)
    # Worst first: the lowest median delivery is the loudest avoid signal.
    # (median_pct is always set here — F-grade entries passed the samples>=1 gate.)
    avoid.sort(key=lambda x: x["median_pct"] or 0.0)
    return {
        "top": top[:top_n],
        "avoid": avoid,
        "avoid_count": len(avoid),
        "tracked": len(by_rig),
        "market": market,
    }


# 30-day market-trend cache: the query scans hashrate_market_history (which
# grows one row per offer per poll cycle) on EVERY panel load — the #1 hot
# path in /api/rentals (measured p95 ~1.1s). Market prices change over hours,
# not per request: a 300s TTL makes the panel fast while staying honest
# (data is never stale by more than the fetch cadence of the history table).
_TREND_CACHE: Dict[str, Any] = {"ts": 0, "payload": None}
_TREND_TTL_S = int(os.environ.get("MARKET_TREND_TTL", "300"))


def fetch_market_trend(days: int = 30) -> Dict[str, Any]:
    """Daily CHEAPEST SHA-256 market price (sats/TH·h) over the last N days
    from hashrate_market_history + a summary (avg/current/vs-avg). Empty
    points when the market snapshot was never persisted (quiet box) — the
    UI hides the timing card instead of showing a fabricated line.

    Cached in-memory (TTL = MARKET_TREND_TTL, default 300s) so the expensive
    30-day GROUP BY scan does not run on every panel load.
    """
    now = int(time.time())
    cache = _TREND_CACHE
    if cache["payload"] is not None and (now - cache["ts"]) < _TREND_TTL_S:
        return cache["payload"]
    try:
        conn = get_db()
        c = conn.cursor()
        try:
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_mkt_hist_alg_ts "
                "ON hashrate_market_history(algorithm, ts)"
            )
            conn.commit()
        except Exception:
            pass
        c.execute(
            """SELECT date(ts,'unixepoch') AS day, MIN(price_per_th_day) AS best_btc
               FROM hashrate_market_history
               WHERE algorithm='sha256' AND price_per_th_day >= ? AND ts >= ?
               GROUP BY day ORDER BY day ASC""",
            (_MIN_PLAUSIBLE_PRICE, now - days * 86400),
        )
        rows = c.fetchall()
        conn.close()
    except Exception as e:
        log.warning("[rental_performance] market trend failed: %s", e)
        return {"points": [], "summary": None}
    if not rows:
        return {"points": [], "summary": None}
    pts = [
        {"day": r["day"], "sats_per_thh": round(r["best_btc"] * 1e8 / 24.0, 2)}
        for r in rows
    ]
    vals = [p["sats_per_thh"] for p in pts]
    avg = sum(vals) / len(vals)
    cur = vals[-1]
    payload = {
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
    cache["ts"] = now
    cache["payload"] = payload
    return payload


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
        local = get_local_rig_history(
            wanted_id,
            wanted_name,
            exclude_rental_id=exclude_rental_id,
            tenant_id=tenant_id,
        )
        if local:
            return local

    listing = fetch_mrr_rentals(
        rtype="renter", history=True, limit=limit, tenant_id=tenant_id
    )
    if not listing.get("success"):
        return []
    rows = [
        _rental_to_history_row(r, provider="mrr")
        for r in listing.get("rentals", [])
        if isinstance(r, dict)
    ]
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
    out: List[Dict[str, Any]] = [
        {
            "id": row["rental_id"],
            "start": row["start"],
            "percent": row["percent"],
            "avg_th": row["avg_th"],
            "advertised_th": row["advertised_th"],
            "cost_sats_per_thh": row["cost_sats_per_thh"],
            "length_hours": row["length_hours"],
        }
        for row in keep
    ]
    out.sort(key=lambda x: str(x.get("start") or ""), reverse=True)
    return out


# Grade severity ladder for the auto-exclusion rule (A best → F worst).
# The tenant's configured grade is a FLOOR: a rig is excluded when its own
# grade is worse OR equal (rank <= floor rank). Default 'F' = only F rigs
# (the legacy behavior).
_AUTO_EXCLUDE_GRADE_RANK = {"A": 5, "B": 4, "C": 3, "D": 2, "F": 1}

# Settings keys driving the per-tenant auto-exclusion rule.
AUTO_EXCLUDE_MIN_SAMPLES_KEY = "rental_auto_blacklist_min_samples"
AUTO_EXCLUDE_GRADE_KEY = "rental_auto_blacklist_grade"

# Legacy hardcoded defaults (used when the settings are unset/invalid).
_AUTO_EXCLUDE_DEFAULT_MIN_SAMPLES = 2
_AUTO_EXCLUDE_DEFAULT_GRADE = "F"


def _auto_exclude_thresholds(tenant_id: str = "") -> Dict[str, Any]:
    """Per-tenant auto-exclusion thresholds from settings, with fail-closed
    defaults. Invalid/empty values fall back silently (never raises).

    Returns {"min_samples": int, "grade_rank": int, "grade": str} where
    grade_rank is the ladder rank of the configured floor grade (F=1 … A=5).
    """
    min_samples = _AUTO_EXCLUDE_DEFAULT_MIN_SAMPLES
    grade = _AUTO_EXCLUDE_DEFAULT_GRADE
    try:
        s = load_settings(tenant_id=tenant_id)
        raw_min = (s.get(AUTO_EXCLUDE_MIN_SAMPLES_KEY) or "").strip()
        if raw_min:
            parsed = int(float(raw_min))
            if parsed >= 1:
                min_samples = parsed
        raw_grade = (s.get(AUTO_EXCLUDE_GRADE_KEY) or "").strip().upper()
        if raw_grade in _AUTO_EXCLUDE_GRADE_RANK:
            grade = raw_grade
    except Exception as e:
        log.warning("[rental_performance] auto-exclude thresholds: %s", e)
    return {
        "min_samples": min_samples,
        "grade_rank": _AUTO_EXCLUDE_GRADE_RANK.get(grade, 1),
        "grade": grade,
    }


def _should_auto_exclude(rig_id: Any, history: List[Dict], tenant_id: str = "") -> bool:
    """SHARED auto-exclusion decision (detail path + periodic sweep).

    A rig keeps under-delivering → grade at/below the tenant's configured
    floor with enough samples → it joins the AUTO blacklist so bad
    performers vanish from the panel everywhere — without touching the
    user's manual blacklist. Per-tenant thresholds come from settings
    (rental_auto_blacklist_grade / rental_auto_blacklist_min_samples;
    defaults F + 2 = legacy behavior). A RESTORED rig is only re-excluded
    when a NEW bad rental arrived AFTER the previous auto-exclusion
    (otherwise the restore button is immediately undone by the same
    streak). Never raises.
    """
    try:
        if is_rig_blacklisted(rig_id, tenant_id=tenant_id) or is_rig_auto_blacklisted(
            rig_id, tenant_id=tenant_id
        ):
            return False
        trust = compute_rig_trust_score(history)
        th = _auto_exclude_thresholds(tenant_id=tenant_id)
        rig_rank = _AUTO_EXCLUDE_GRADE_RANK.get(trust.get("grade"), 0)
        if rig_rank == 0 or rig_rank > th["grade_rank"]:
            return False
        if trust.get("samples", 0) < th["min_samples"]:
            return False
        last_auto = _auto_blacklist_ts(rig_id, tenant_id=tenant_id)
        newest = _history_newest_ts(history)
        return last_auto == 0.0 or (newest is not None and newest > last_auto)
    except Exception as e:
        log.warning("[rental_performance] auto-exclude check failed: %s", e)
        return False


def auto_blacklist_candidate_tenants() -> List[str]:
    """Tenant ids with a LOCAL renter track record (auto-exclusion sweep
    candidates). The auto-exclusion is a DEFAULT protection (same rule the
    panel detail applies) — not an opt-in alert — so the sweep visits every
    tenant that has local history to judge, with ZERO provider cost.
    Never raises: a storage hiccup → empty list (the sweep skips the cycle)."""
    out: List[str] = []
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT DISTINCT tenant_id FROM rental_history "
            "WHERE bucket='renter' AND provider='mrr' AND rig_id!='' "
            "AND percent IS NOT NULL"
        )
        for row in c.fetchall():
            out.append(row["tenant_id"] or "")
        conn.close()
    except Exception as e:
        log.warning("[rental_performance] auto-blacklist candidates failed: %s", e)
    return list(dict.fromkeys(out))


def evaluate_auto_blacklist(tenant_id: str = "") -> List[str]:
    """One auto-exclusion sweep pass for a tenant: scan its LOCAL rig track
    record and auto-exclude every rig that passes the shared rule
    (_should_auto_exclude). Returns the rigs excluded THIS pass (for the
    sweep log + tests). Zero provider calls — purely local history."""
    excluded: List[str] = []
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT DISTINCT rig_id FROM rental_history "
            "WHERE tenant_id=? AND bucket='renter' AND provider='mrr' "
            "AND rig_id!='' AND percent IS NOT NULL",
            (tenant_id or "",),
        )
        rig_ids = [str(row["rig_id"]) for row in c.fetchall()]
        conn.close()
        for rid in rig_ids:
            history = fetch_rig_performance_history(rid, tenant_id=tenant_id)
            if _should_auto_exclude(rid, history, tenant_id=tenant_id):
                if add_rig_to_auto_blacklist(rid, tenant_id=tenant_id):
                    excluded.append(rid)
    except Exception as e:
        log.warning(
            "[rental_performance] auto-blacklist sweep %s: %s",
            tenant_id or "default",
            e,
        )
    return excluded


def analyze_rig(
    rig_id: Any = None,
    rig_name: str = "",
    exclude_rental_id: Any = None,
    tenant_id: str = "",
) -> Dict[str, Any]:
    """One-call rig intelligence for the detail panel.

    Combines the same-rig track record, the computed Trust Score (grade A-F),
    the manual blacklist state and a spend/consistency summary — so the
    frontend renders the full "should I rent this rig again?" verdict with a
    single endpoint instead of re-assembling fragments.

    Returns:
      {"history": [...], "trust": {...}, "blacklisted": bool,
       "auto_excluded_now": bool, "summary": {rentals, avg_pct,
       cost_avg_sats_thh, trend_pct}}
    """
    history = fetch_rig_performance_history(
        rig_id, rig_name, exclude_rental_id=exclude_rental_id, tenant_id=tenant_id
    )
    trust = compute_rig_trust_score(history)
    blacklisted = is_rig_blacklisted(rig_id, tenant_id=tenant_id)
    auto_blacklisted = is_rig_auto_blacklisted(rig_id, tenant_id=tenant_id)

    # CFO auto-exclusion — SHARED decision with the periodic sweep (one rule,
    # no drift): a rig that keeps under-delivering (grade F with ≥2 samples)
    # joins the AUTO list so bad performers vanish from the panel everywhere
    # — without touching the user's manual blacklist, and without re-flagging
    # a manually restored rig until NEW bad samples accumulate.
    # auto_excluded_now = True ONLY when this call performed the exclusion —
    # the caller (detail route) fires the opt-in alert exactly once per EVENT
    # (same rig_id:ts dedup claim the sweep uses — Issue #102/#108).
    auto_excluded_now = False
    if _should_auto_exclude(rig_id, history, tenant_id=tenant_id):
        auto_excluded_now = bool(add_rig_to_auto_blacklist(rig_id, tenant_id=tenant_id))
        auto_blacklisted = True

    pcts = [h["percent"] for h in history if h.get("percent") is not None]
    costs = [
        h["cost_sats_per_thh"]
        for h in history
        if h.get("cost_sats_per_thh") is not None
    ]
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
    return {
        "history": history,
        "trust": trust,
        "blacklisted": blacklisted,
        "auto_blacklisted": auto_blacklisted,
        "auto_excluded_now": auto_excluded_now,
        "summary": summary,
    }


def _num(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None
