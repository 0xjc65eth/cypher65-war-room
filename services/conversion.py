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

    ``paywall_view`` is deduplicated per (tenant, feature) per 24h (Issue
    #158): a user hitting the SAME gated endpoint twice in a day counts once
    (no inflation of the funnel top), but each DIFFERENT gated feature they
    hit counts — so ``paywall_by_feature`` shows which endpoint actually
    blocks users, instead of hiding every feature behind one per-tenant
    bucket. Anonymous callers (tenant_id="") are not deduplicated — we
    cannot tell them apart, so every 402 counts.
    """
    if not event:
        return False
    import json

    try:
        ensure_table()
        conn = get_db()
        ts = int(time.time())
        tenant_key = _anonymize(tenant_id)

        # Funnel top dedup: one paywall_view per (tenant, feature) per 24h.
        if event == "paywall_view" and tenant_key:
            feature = str((meta or {}).get("feature") or "")[:64]
            recent = conn.execute(
                "SELECT meta FROM conversion_events "
                "WHERE event='paywall_view' AND tenant_id=? AND ts >= ?",
                (tenant_key, ts - 86400),
            ).fetchall()
            for r in recent:
                try:
                    m = json.loads(r["meta"] or "{}") or {}
                    if not isinstance(m, dict):
                        m = {}
                except (ValueError, TypeError):
                    m = {}
                if str(m.get("feature") or "")[:64] == feature:
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

    # ── Feature breakdown (Issue #158 — 18-D): which gated endpoint blocks
    # the most users? paywall_view rows carry meta.feature (endpoint name,
    # set by the pro_required decorator) — aggregate per feature so the CFO
    # sees WHERE users get stuck, not just how many. Events recorded before
    # this change have no feature → bucketed as 'unknown'.
    paywall_features: Dict[str, int] = {}
    for r in rows_all:
        if r["event"] != "paywall_view":
            continue
        try:
            m = json.loads(r["meta"] or "{}") or {}
            if not isinstance(m, dict):
                m = {}
        except (ValueError, TypeError):
            m = {}
        fname = str(m.get("feature") or "")[:64]
        paywall_features[fname or "unknown"] = (
            paywall_features.get(fname or "unknown", 0) + 1
        )
    paywall_by_feature = [
        {"feature": k, "count": v}
        for k, v in sorted(paywall_features.items(), key=lambda kv: -kv[1])
    ][:10]

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
        # Feature breakdown (Issue #158 — 18-D).
        "paywall_by_feature": paywall_by_feature,
        # Session view (Issue #155) — per-user funnel attribution.
        "sessions_count": len(funnels_seen),
        "session_stages": session_counts,
        "session_drop_off": session_drop_off,
        "session_conversion_rate_pct": (
            round(len(money) / len(base) * 100, 2) if base else 0.0
        ),
    }


# ── Feature over-concentration alert (Issue #163) ──────────────────────────


def detect_feature_overconcentration(
    paywall_by_feature: List[Dict[str, Any]], min_pct: float = 50.0
) -> Optional[Dict[str, Any]]:
    """Alert when a single feature concentrates too much of the paywalls.

    Product signal (Issue #163): when ONE gated endpoint accounts for X% of
    all 402s, that feature is the #1 friction point — the CFO should know
    without reading the whole breakdown. Pure function over the already-
    computed ``paywall_by_feature`` list (Issue #158); returns None when no
    feature crosses the threshold.

    Args:
        paywall_by_feature: [{feature, count}, ...] sorted desc (or empty).
        min_pct: share threshold (default 50). ``unknown`` counts as a real
            feature bucket — a legacy-heavy dataset can legitimately flag it.

    Returns:
        {"feature", "count", "share_pct", "min_pct"} or None.
    """
    # Defensive: the caller (route) always clamps, but a direct call with
    # None/"" or a non-numeric threshold must not crash the alert logic.
    try:
        min_pct = float(min_pct or 50.0)
    except (TypeError, ValueError):
        min_pct = 50.0
    if not paywall_by_feature:
        return None
    total = sum(int(f.get("count") or 0) for f in paywall_by_feature)
    if total <= 0:
        return None
    top = max(paywall_by_feature, key=lambda f: int(f.get("count") or 0))
    count = int(top.get("count") or 0)
    share = round(count / total * 100, 1) if total else 0.0
    if share < min_pct:
        return None
    return {
        "feature": str(top.get("feature") or "unknown")[:64],
        "count": count,
        "share_pct": share,
        "min_pct": round(float(min_pct), 1),
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
          "conversion_rate_pct": 2.3, "sessions_count": 5,
          "paywall_by_feature": [{feature, count}, ...]}, ...]

    ``week`` is the ISO-8601 week key (Monday-start) in UTC; stages/drop-off
    mirror the aggregate ``funnel_report`` math per week; ``sessions_count``
    is the number of distinct funnel_ids (Issue #155 attribution) seen that
    week (0 when no session tokens are present). ``paywall_by_feature``
    mirrors the funnel_report breakdown per week (Issue #165): which gated
    endpoint blocked users THAT week (meta.feature, 'unknown' fallback).
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
                "features": {},
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
        # Feature breakdown per week (Issue #165): paywall_view rows carry
        # meta.feature — count per feature so the CSV can show WHICH gated
        # endpoint blocked users each week (same shape as funnel_report).
        if r["event"] == "paywall_view":
            fname = str(m.get("feature") or "")[:64]
            b["features"][fname or "unknown"] = (
                b["features"].get(fname or "unknown", 0) + 1
            )

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
        features = [
            {"feature": k, "count": v}
            for k, v in sorted(b["features"].items(), key=lambda kv: -kv[1])
        ][:10]
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
                "paywall_by_feature": features,
            }
        )
    return out


def funnel_weekly_csv(buckets: List[Dict[str, Any]]) -> str:
    """Serialize weekly funnel buckets to CSV for spreadsheet export.

    One row per ISO week with the stage counts + conversion rate + sessions
    count — the most readable shape for Excel/Sheets. When any week carries
    a ``paywall_by_feature`` breakdown (Issue #165), one column per feature
    is appended AFTER the standard columns (``feature:<name>``, union of
    features seen across the report, sorted for a stable layout; 0 when the
    feature had no paywalls that week). Each count column is followed by a
    ``feature_pct:<name>`` share column (Issue #168) — count / that week's
    paywall_view × 100, 1 decimal — so the CFO sorts by IMPACT straight in
    the spreadsheet. No features → the header is exactly the legacy one, so
    older consumers are unaffected. The caller prepends the UTF-8 BOM
    (matches the accepted-recos export convention).
    """
    feature_cols = sorted(
        {
            str(f.get("feature") or "unknown")
            for b in buckets
            for f in (b.get("paywall_by_feature") or [])
        }
    )
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
        + [f"feature:{f}" for f in feature_cols]
        + [f"feature_pct:{f}" for f in feature_cols]
    )
    for b in buckets:
        s = b.get("stages") or {}
        paywalls = int(s.get("paywall_view", 0) or 0)
        by_feature = {
            str(f.get("feature") or "unknown"): int(f.get("count") or 0)
            for f in (b.get("paywall_by_feature") or [])
        }
        # Share % of THAT week's paywalls — 0.0 when no paywalls (no feature
        # could have caused impact) or when the feature is absent.
        pct_feature = {
            f: (round(c / paywalls * 100.0, 1) if paywalls else 0.0)
            for f, c in by_feature.items()
        }
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
            + [by_feature.get(f, 0) for f in feature_cols]
            + [pct_feature.get(f, 0.0) for f in feature_cols]
        )
    return buf.getvalue()


# ── Subscription lifecycle (Issue #157 — 18-C: real cohort LTV) ───────────
# Lemon Squeezy fires subscription_created / subscription_updated on the
# subscription object. We record ONLY the opaque subscription id + timestamps
# (NO PII — never the email), so the CFO can compute real LTV per cohort
# (price × months actually paid, including renewals) instead of the pure
# price×months estimate.


def ensure_subscription_table() -> None:
    """Create subscription_events if missing (self-healing, like the rest)."""
    try:
        conn = get_db()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subscription_events (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                subscription_id TEXT NOT NULL,
                event           TEXT NOT NULL,
                ts              INTEGER NOT NULL,
                renews_at       TEXT NOT NULL DEFAULT '',
                created_at      TEXT NOT NULL DEFAULT '',
                created_at_ts   INTEGER NOT NULL DEFAULT 0,
                UNIQUE(subscription_id, event, renews_at)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sub_evt_sub "
            "ON subscription_events(subscription_id)"
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        log.warning("[conversion] subscription table bootstrap failed: %s", e)


def _iso_to_ts(iso: str) -> int:
    """Parse an LS ISO-8601 timestamp to unix; 0 when unparseable."""
    if not iso:
        return 0
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except (ValueError, TypeError):
        return 0


def _month_key(ts: int) -> str:
    """UTC YYYY-MM bucket for a unix ts ('' when invalid)."""
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m")
    except (ValueError, OSError, OverflowError, TypeError):
        return ""


def record_subscription_event(
    subscription_id: str,
    event: str,
    ts: int,
    renews_at: str = "",
    created_at: str = "",
    created_at_ts: int = 0,
) -> bool:
    """Record one subscription lifecycle event (best-effort, idempotent).

    ``event`` is 'subscription_created' or 'renewal'. A renewal only counts
    when ``renews_at`` is a NEW billing period for that subscription — the
    initial subscription_updated (echoing the created period) and card/
    status blips never inflate the renewal count. No PII is stored.
    """
    if not subscription_id:
        return False
    try:
        ensure_subscription_table()
        if not created_at_ts and created_at:
            created_at_ts = _iso_to_ts(created_at)
        conn = get_db()
        if event == "renewal":
            if not renews_at:
                conn.close()
                return False
            # Blocks the echo of the CREATED period: subscription_created also
            # stores renews_at, so a subscription_updated carrying the same
            # renews_at is NOT a renewal (card/status blip) — it must not
            # count. The UNIQUE row alone can't catch this (event differs),
            # hence the explicit check across any event for this subscription.
            dup = conn.execute(
                "SELECT 1 FROM subscription_events "
                "WHERE subscription_id = ? AND renews_at = ? LIMIT 1",
                (subscription_id, renews_at),
            ).fetchone()
            if dup:
                conn.close()
                return False
        # INSERT OR IGNORE absorbs the race window (two concurrent deliveries
        # with the same period): the UNIQUE row ignores the loser instead of
        # raising IntegrityError, and rowcount==1 tells us who inserted — no
        # connection leak on the lost race.
        cur = conn.execute(
            "INSERT OR IGNORE INTO subscription_events "
            "(subscription_id, event, ts, renews_at, created_at, created_at_ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (subscription_id, event, int(ts), renews_at, created_at, created_at_ts),
        )
        conn.commit()
        inserted = cur.rowcount == 1
        conn.close()
        return inserted
    except (sqlite3.Error, TypeError, ValueError):
        log.warning("[conversion] record_subscription_event failed", exc_info=True)
        return False


def cohort_ltv_report(
    price_usd_month: Optional[float] = None, margin_pct: Optional[float] = None
) -> Dict[str, Any]:
    """Real LTV by purchase cohort from subscription_events (no PII).

    Each subscription joins the cohort of its creation month; every renewal
    adds one more paid month. Per cohort we report subscriptions, renewals,
    accumulated revenue (price × (subs + renewals) × margin), LTV per sub,
    retention at months 1/3/6/12 (share of subs with ≥N renewals) and how
    old the cohort is (young cohorts can't show m12 yet — the CFO must read
    retention with cohort_age_days in mind).

    Returns: {"has_renewal_data": bool, "ltv_real_usd": float|None,
              "cohorts": [{cohort_month, subscriptions, renewals,
                           revenue_usd, ltv_usd, retention_m1_pct, ...,
                           cohort_age_days}, ...]}
    """
    try:
        price = float(
            price_usd_month
            if price_usd_month is not None
            else os.environ.get("PRO_PRICE_USD_MONTH", DEFAULT_PRICE_USD_MONTH)
        )
        margin = float(
            margin_pct
            if margin_pct is not None
            else os.environ.get("PRO_MARGIN_PCT", DEFAULT_MARGIN_PCT)
        )
    except (TypeError, ValueError):
        price, margin = DEFAULT_PRICE_USD_MONTH, DEFAULT_MARGIN_PCT

    try:
        ensure_subscription_table()
        conn = get_db()
        rows = conn.execute(
            "SELECT subscription_id, event, renews_at, created_at_ts, ts "
            "FROM subscription_events ORDER BY created_at_ts ASC, ts ASC"
        ).fetchall()
        conn.close()
    except sqlite3.Error as e:
        log.warning("[conversion] cohort_ltv_report failed: %s", e)
        return {"has_renewal_data": False, "ltv_real_usd": None, "cohorts": []}

    subs: Dict[str, Dict[str, Any]] = {}
    # Two passes (order-independent): a renewal row may carry created_at_ts=0
    # (recorded without created_at) and would sort BEFORE its cohort row if
    # we bucket in one loop — renewals must never be lost to row order.
    for r in rows:
        if r["event"] == "subscription_created":
            m = _month_key(r["created_at_ts"] or r["ts"])
            d = subs.setdefault(r["subscription_id"], {"month": m, "renewals": 0})
            d["month"] = m or d["month"]
    for r in rows:
        if r["event"] == "renewal" and r["subscription_id"] in subs:
            subs[r["subscription_id"]]["renewals"] += 1

    cohorts: Dict[str, Dict[str, Any]] = {}
    for sid, d in subs.items():
        c = cohorts.setdefault(
            d["month"], {"subscriptions": 0, "renewals": 0, "renewal_dist": []}
        )
        c["subscriptions"] += 1
        c["renewals"] += d["renewals"]
        c["renewal_dist"].append(d["renewals"])

    now_ts = int(time.time())
    total_subs = 0
    total_rev = 0.0
    any_renewal = False
    out: List[Dict[str, Any]] = []
    for month in sorted(cohorts):
        c = cohorts[month]
        n = c["subscriptions"]
        rev = round(price * (n + c["renewals"]) * margin, 2)
        total_subs += n
        total_rev += rev
        any_renewal = any_renewal or c["renewals"] > 0

        def _retained(nth: int) -> float:
            if not n:
                return 0.0
            return round(sum(1 for x in c["renewal_dist"] if x >= nth) / n * 100, 1)

        out.append(
            {
                "cohort_month": month,
                "subscriptions": n,
                "renewals": c["renewals"],
                "revenue_usd": rev,
                "ltv_usd": round(rev / n, 2) if n else 0.0,
                "retention_m1_pct": _retained(1),
                "retention_m3_pct": _retained(3),
                "retention_m6_pct": _retained(6),
                "retention_m12_pct": _retained(12),
                "cohort_age_days": max(0, now_ts - _iso_to_ts(month + "-01")) // 86400,
            }
        )

    return {
        "has_renewal_data": any_renewal,
        "ltv_real_usd": round(total_rev / total_subs, 2) if total_subs else None,
        "cohorts": out,
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

    ltv_estimate = price * months * margin

    # Issue #157 (18-C): when real renewal data exists, the cohort LTV
    # replaces the estimate (price × months actually paid incl. renewals).
    # Fallback keeps the report usable before the first renewal arrives.
    _cohort = cohort_ltv_report(price_usd_month=price, margin_pct=margin)
    if _cohort.get("has_renewal_data") and _cohort.get("ltv_real_usd"):
        ltv = _cohort["ltv_real_usd"]
        ltv_source = "cohort_real"
    else:
        ltv = ltv_estimate
        ltv_source = "estimate"

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
        "ltv_source": ltv_source,
        "ltv_estimate_usd": round(ltv_estimate, 2),
        "has_renewal_data": _cohort.get("has_renewal_data", False),
        "cohorts": _cohort.get("cohorts", []),
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
