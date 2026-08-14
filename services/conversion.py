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

import hashlib
import logging
import os
import sqlite3
import time
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
    }


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
