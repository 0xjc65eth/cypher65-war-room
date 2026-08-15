"""
CYPHER65 // Conversion Telemetry (CFO — funnel + LTV/CAC)
==========================================================
Track the PRO acquisition funnel end-to-end and estimate unit economics.

Funnel stages (each is a row in the ``conversion_events`` table):
  paywall_view     — a gated route returned 402 (the user SAW the paywall)
  modal_open       — the user opened the upgrade modal (explicit interest)
  checkout_start   — the user clicked BUY and a checkout URL was created
  paid             — Lemon Squeezy order_created webhook fulfilled a key
  key_activated    — a redeemed key first passed the PRO gate

Every stage is OPT-IN for privacy: the only identifier stored is a SHA-256
hash of the tenant id / email (never raw emails), plus the event's own
``meta`` dict. The dashboard report aggregates counts + per-stage drop-off,
never individual rows.

LTV/CAC (pure estimates, CFO defaults, env-overridable):
  LTV = price_usd_month × license_months × margin_pct (default 12 months,
        5% processor + $0.50/sale margin → 0.94)
  CAC = marketing_spend_usd ÷ new_paid_count (requires MARKETING_SPEND_USD;
        without it the report says \"no marketing data\" instead of guessing)

Usage:
    from services.conversion import track_event, funnel_report, ltv_cac_report

    track_event("paywall_view", tenant_id="acme", meta={"feature": "monte_carlo"})
    print(funnel_report())
    print(ltv_cac_report())
"""

import csv
import hashlib
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from io import StringIO
from typing import Any, Dict, List, Optional

from services.db import get_db

log = logging.getLogger("cypher65.conversion")

# Funnel order (used to compute drop-off between consecutive stages).
FUNNEL_STAGES = (
    "paywall_view",
    "modal_open",
    "checkout_start",
    "paid",
    "key_activated",
)

# LTV defaults (CFO) — env-overridable so the operator can plug real numbers.
DEFAULT_PRICE_USD_MONTH = 9
DEFAULT_LICENSE_MONTHS = 12
DEFAULT_MARGIN_PCT = 0.94  # 5% LS + $0.50 fixed → ~94% of price retained
LTV_ENV = ("PRO_PRICE_USD_MONTH", "PRO_LICENSE_MONTHS", "PRO_MARGIN_PCT")

_UTC_EPOCH = 0  # unused placeholder kept for symmetry with other modules


def _anonymize(value: str) -> str:
    """Deterministic, non-reversible id for telemetry (never raw emails)."""
    if not value:
        return ""
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()[:24]


# ── Table bootstrap (idempotent) ────────────────────────────────────────────


def ensure_table() -> None:
    """Create conversion_events if missing (self-healing for fresh DBs)."""
    try:
        conn = get_db()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversion_events (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        INTEGER NOT NULL,
                event     TEXT NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT '',
                meta      TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conv_event_ts ON conversion_events(event, ts)"
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        log.warning("[conversion] table bootstrap failed: %s", e)


# ── Event tracking (never raises — telemetry must not break requests) ──────


def track_event(
    event: str,
    tenant_id: str = "",
    meta: Optional[Dict[str, Any]] = None,
    email: str = "",
) -> bool:
    """Record one funnel event. Best-effort; failures are logged, not raised.

    Args:
        event: one of FUNNEL_STAGES (any string is accepted defensively).
        tenant_id: tenant/sub id (anonymized before storage).
        meta: extra JSON-safe context (feature, plan, etc.).
        email: raw email is NEVER stored — only its hash (privacy).

    ``paywall_view`` is deduplicated per tenant per 24h: a user hitting N
    gated endpoints in one session would otherwise inflate the top of the
    funnel (each 402 fires the event). Anonymous callers (tenant_id="")
    are not deduplicated — we cannot tell them apart, so every 402 counts.
    """
    if not event:
        return False
    import json

    try:
        ensure_table()
        conn = get_db()
        ts = int(time.time())
        tenant_key = _anonymize(tenant_id)

        # Funnel top dedup: one paywall_view per tenant per 24h.
        if event == "paywall_view" and tenant_key:
            dup = conn.execute(
                "SELECT 1 FROM conversion_events "
                "WHERE event='paywall_view' AND tenant_id=? AND ts >= ? LIMIT 1",
                (tenant_key, ts - 86400),
            ).fetchone()
            if dup:
                conn.close()
                return False

        row = {
            "ts": ts,
            "event": str(event)[:64],
            "tenant_id": tenant_key,
            "meta": json.dumps(meta or {}),
            "created_at": ts,
        }
        if email:
            row["meta"] = json.dumps({**(meta or {}), "email_hash": _anonymize(email)})
        # Meta is operator-controlled only in size: cap it so the public
        # (unauthenticated) track endpoint cannot bloat the table.
        if len(row["meta"]) > 1000:
            row["meta"] = row["meta"][:1000]
        conn.execute(
            "INSERT INTO conversion_events (ts, event, tenant_id, meta, created_at) "
            "VALUES (:ts, :event, :tenant_id, :meta, :created_at)",
            row,
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:  # noqa: BLE001 — telemetry is best-effort
        log.warning("[conversion] track_event(%s) failed: %s", event, e)
        return False


# ── Funnel report ───────────────────────────────────────────────────────────


def funnel_report(days: int = 30) -> Dict[str, Any]:
    """Aggregate funnel counts + drop-off for the last ``days``.

    Returns:
        {
          "days": 30,
          "stages": {paywall_view: N, modal_open: N, checkout_start: N,
                     paid: N, key_activated: N},
          "drop_off": [{"from": "paywall_view", "to": "modal_open",
                        "loss_pct": 62.5, "loss_abs": 5}, ...],
          "conversion_rate_pct": 2.3,   # key_activated / paywall_view
          "visitors": 120,              # distinct anonymized tenants
          "paid_count": 3,
        }
    """
    try:
        ensure_table()
        conn = get_db()
        cutoff = int(time.time()) - days * 86400
        rows = conn.execute(
            "SELECT event, COUNT(*) AS n, COUNT(DISTINCT tenant_id) AS tenants "
            "FROM conversion_events WHERE ts >= ? GROUP BY event",
            (cutoff,),
        ).fetchall()
        # Raw (event, meta) rows drive the session view below — the events
        # table is small (funnel telemetry only), so this is cheap.
        rows_all = conn.execute(
            "SELECT event, meta FROM conversion_events WHERE ts >= ?",
            (cutoff,),
        ).fetchall()
        conn.close()
    except sqlite3.Error as e:
        log.warning("[conversion] funnel_report failed: %s", e)
        return {"days": days, "stages": {}, "drop_off": [], "error": str(e)}

    counts = {r["event"]: r["n"] for r in rows}
    tenants = {r["event"]: r["tenants"] for r in rows}
    stages = {}
    for stage in FUNNEL_STAGES:
        if stage in counts:
            stages[stage] = counts[stage]

    # Drop-off between consecutive stages with data.
    drop_off = []
    keys = [s for s in FUNNEL_STAGES if s in stages]
    for i in range(1, len(keys)):
        prev_n = stages[keys[i - 1]]
        cur_n = stages[keys[i]]
        loss = prev_n - cur_n
        loss_pct = round(loss / prev_n * 100, 1) if prev_n else 0.0
        drop_off.append(
            {
                "from": keys[i - 1],
                "to": keys[i],
                "prev": prev_n,
                "next": cur_n,
                "loss_abs": loss,
                "loss_pct": loss_pct,
                "conversion_pct": round(cur_n / prev_n * 100, 1) if prev_n else 0.0,
            }
        )

    # ── Session view (Issue #155): events carrying meta.funnel_id form a
    # per-user path across stages. The aggregate counts above mix users and
    # sessions; here we count DISTINCT funnels per stage so drop-off answers
    # "how many users who reached X also reached Y" — the real per-user
    # funnel, and the base for cohort LTV in #157. Backward compatible:
    # events recorded before this change carry no funnel_id and simply
    # don't contribute to the session view (zeros/empty below).
    session_stages: Dict[str, set] = {}  # event -> set of funnel_ids
    funnels_seen: set = set()
    for r in rows_all:
        try:
            m = json.loads(r["meta"] or "{}") or {}
            if not isinstance(m, dict):
                m = {}
        except (ValueError, TypeError):
            m = {}
        fid = str((m or {}).get("funnel_id") or "")[:64]
        if not fid:
            continue
        funnels_seen.add(fid)
        session_stages.setdefault(r["event"], set()).add(fid)

    session_counts = {
        s: len(session_stages.get(s, set()))
        for s in FUNNEL_STAGES
        if s in session_stages
    }
    session_drop_off = []
    keys_s = [s for s in FUNNEL_STAGES if s in session_counts]
    for i in range(1, len(keys_s)):
        prev_n = session_counts[keys_s[i - 1]]
        cur_n = session_counts[keys_s[i]]
        loss = prev_n - cur_n
        session_drop_off.append(
            {
                "from": keys_s[i - 1],
                "to": keys_s[i],
                "prev": prev_n,
                "next": cur_n,
                "loss_abs": loss,
                "loss_pct": round(loss / prev_n * 100, 1) if prev_n else 0.0,
                "conversion_pct": round(cur_n / prev_n * 100, 1) if prev_n else 0.0,
            }
        )
    # Per-user conversion: funnels that reached a money stage ÷ funnels that
    # saw the paywall (fallback: any funnel event when no paywall row carries
    # an id — e.g. checkout-first data before paywall dedup kicks in).
    money = session_stages.get("paid", set()) | session_stages.get(
        "key_activated", set()
    )
    # Base = first funnel stage that actually carries session ids
    # (paywall_view is fired server-side without a funnel_id, so
    # modal_open is usually the first attributed stage) — else any
    # funnel id seen in the window.
    base = session_stages.get("paywall_view", set())
    if not base:
        for _s in FUNNEL_STAGES:
            if _s in session_counts:
                base = session_stages[_s]
                break
    if not base:
        base = funnels_seen

    paywall = stages.get("paywall_view", 0)
    activated = stages.get("key_activated", 0)
    visitors = max(tenants.values()) if tenants else 0
    return {
        "days": days,
        "stages": stages,
        "drop_off": drop_off,
        "visitors": visitors,
        "paid_count": stages.get("paid", 0),
        "activated_count": activated,
        "conversion_rate_pct": round(activated / paywall * 100, 2) if paywall else 0.0,
        # Session view (Issue #155) — per-user funnel attribution.
        "sessions_count": len(funnels_seen),
        "session_stages": session_counts,
        "session_drop_off": session_drop_off,
        "session_conversion_rate_pct": (
            round(len(money) / len(base) * 100, 2) if base else 0.0
        ),
    }


# ── Weekly trend (Issue #156 — 18-B) ───────────────────────────────────────


def funnel_weekly_report(weeks: int = 8) -> List[Dict[str, Any]]:
    """Weekly funnel buckets (ISO weeks, UTC) for trend analysis.

    Returns a list of buckets (oldest → newest) covering the last ``weeks``
    ISO weeks that contain events — so the CFO can see whether conversion
    is improving week-over-week:

        [{"week": "2026-W31", "week_start_ts": 1785110400,
          "stages": {paywall_view: N, ...},
          "drop_off": [{from, to, prev, next, loss_abs, loss_pct,
                        conversion_pct}, ...],
          "conversion_rate_pct": 2.3, "sessions_count": 5}, ...]

    ``week`` is the ISO-8601 week key (Monday-start) in UTC; stages/drop-off
    mirror the aggregate ``funnel_report`` math per week; ``sessions_count``
    is the number of distinct funnel_ids (Issue #155 attribution) seen that
    week (0 when no session tokens are present).
    """
    if weeks < 1:
        weeks = 1
    if weeks > 52:
        weeks = 52
    try:
        ensure_table()
        conn = get_db()
        cutoff = int(time.time()) - weeks * 7 * 86400
        rows = conn.execute(
            "SELECT event, ts, meta FROM conversion_events "
            "WHERE ts >= ? ORDER BY ts ASC",
            (cutoff,),
        ).fetchall()
        conn.close()
    except sqlite3.Error as e:
        log.warning("[conversion] funnel_weekly_report failed: %s", e)
        return []

    buckets: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        try:
            dt = datetime.fromtimestamp(r["ts"], tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            continue
        iso = dt.isocalendar()
        key = f"{iso[0]}-W{iso[1]:02d}"
        if key not in buckets:
            buckets[key] = {
                "counts": {},
                "sessions": set(),
                "week_start_ts": int(
                    (dt - timedelta(days=dt.weekday()))
                    .replace(hour=0, minute=0, second=0, microsecond=0)
                    .timestamp()
                ),
            }
        b = buckets[key]
        b["counts"][r["event"]] = b["counts"].get(r["event"], 0) + 1
        # Session attribution (funnel_id) for the per-week sessions count.
        try:
            m = json.loads(r["meta"] or "{}") or {}
            if not isinstance(m, dict):
                m = {}
        except (ValueError, TypeError):
            m = {}
        fid = str(m.get("funnel_id") or "")[:64]
        if fid:
            b["sessions"].add(fid)

    out: List[Dict[str, Any]] = []
    for key in sorted(buckets):
        b = buckets[key]
        counts = {s: b["counts"].get(s, 0) for s in FUNNEL_STAGES if s in b["counts"]}
        # Drop-off between consecutive stages with data (mirrors funnel_report).
        keys = [s for s in FUNNEL_STAGES if s in counts]
        drop_off = []
        for i in range(1, len(keys)):
            prev_n = counts[keys[i - 1]]
            cur_n = counts[keys[i]]
            loss = prev_n - cur_n
            drop_off.append(
                {
                    "from": keys[i - 1],
                    "to": keys[i],
                    "prev": prev_n,
                    "next": cur_n,
                    "loss_abs": loss,
                    "loss_pct": round(loss / prev_n * 100, 1) if prev_n else 0.0,
                    "conversion_pct": round(cur_n / prev_n * 100, 1) if prev_n else 0.0,
                }
            )
        paywall = counts.get("paywall_view", 0)
        activated = counts.get("key_activated", 0)
        out.append(
            {
                "week": key,
                "week_start_ts": b["week_start_ts"],
                "stages": counts,
                "drop_off": drop_off,
                "conversion_rate_pct": (
                    round(activated / paywall * 100, 2) if paywall else 0.0
                ),
                "sessions_count": len(b["sessions"]),
            }
        )
    return out


def funnel_weekly_csv(buckets: List[Dict[str, Any]]) -> str:
    """Serialize weekly funnel buckets to CSV for spreadsheet export.

    One row per ISO week with the stage counts + conversion rate + sessions
    count — the most readable shape for Excel/Sheets. The caller prepends
    the UTF-8 BOM (matches the accepted-recos export convention).
    """
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "week",
            "paywall_view",
            "modal_open",
            "checkout_start",
            "paid",
            "key_activated",
            "conversion_rate_pct",
            "sessions_count",
        ]
    )
    for b in buckets:
        s = b.get("stages") or {}
        w.writerow(
            [
                b.get("week", ""),
                s.get("paywall_view", 0),
                s.get("modal_open", 0),
                s.get("checkout_start", 0),
                s.get("paid", 0),
                s.get("key_activated", 0),
                b.get("conversion_rate_pct", 0),
                b.get("sessions_count", 0),
            ]
        )
    return buf.getvalue()


# ── LTV / CAC estimates ─────────────────────────────────────────────────────


def ltv_cac_report(
    paid_count: Optional[int] = None, marketing_spend_usd: Optional[float] = None
) -> Dict[str, Any]:
    """Estimate LTV and CAC from env-tunable unit economics.

    LTV = price_usd_month × license_months × margin_pct
    CAC = marketing_spend_usd ÷ paid_count   (requires the spend number;
          absent → the report says \"no data\" instead of inventing a CAC)

    Args:
        paid_count: number of paying customers (from funnel_report); when
            omitted, the last-30d paid events are counted from the DB.
        marketing_spend_usd: explicit spend; falls back to the
            MARKETING_SPEND_USD env var.
    """
    try:
        price = float(os.environ.get("PRO_PRICE_USD_MONTH", DEFAULT_PRICE_USD_MONTH))
        months = float(os.environ.get("PRO_LICENSE_MONTHS", DEFAULT_LICENSE_MONTHS))
        margin = float(os.environ.get("PRO_MARGIN_PCT", DEFAULT_MARGIN_PCT))
    except (TypeError, ValueError):
        price, months, margin = (
            DEFAULT_PRICE_USD_MONTH,
            DEFAULT_LICENSE_MONTHS,
            DEFAULT_MARGIN_PCT,
        )

    ltv = price * months * margin

    if paid_count is None:
        try:
            ensure_table()
            conn = get_db()
            cutoff = int(time.time()) - 30 * 86400
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM conversion_events "
                "WHERE event='paid' AND ts >= ?",
                (cutoff,),
            ).fetchone()
            conn.close()
            paid_count = row["n"] if row else 0
        except sqlite3.Error:
            paid_count = 0

    spend = marketing_spend_usd
    if spend is None:
        raw = (os.environ.get("MARKETING_SPEND_USD") or "").strip()
        spend = float(raw) if raw else None

    cac = (
        round(spend / paid_count, 2) if (spend is not None and paid_count > 0) else None
    )
    return {
        "ltv_usd": round(ltv, 2),
        "assumptions": {
            "price_usd_month": price,
            "license_months": months,
            "margin_pct": margin,
            "env_keys": list(LTV_ENV) + ["MARKETING_SPEND_USD"],
        },
        "paid_count": paid_count,
        "marketing_spend_usd": spend,
        "cac_usd": cac,
        "ltv_cac_ratio": round(ltv / cac, 2) if (cac and cac > 0) else None,
        "payback_months": round(cac / price, 1) if (cac and price > 0) else None,
    }
