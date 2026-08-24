"""Beta Analytics — self-hosted usage tracking for the beta program.

Privacy-first: all data stays in the local SQLite database. No external
telemetry. Events are rate-limited (1/second per client) to prevent abuse.

Events tracked:
  - boot: page loaded (viewport, UA hash, timestamp)
  - module_switch: user navigated to a module (from, to, timestamp)
  - module_time: time spent in a module (module, seconds)

Usage:
    from services.beta_analytics import track_event, ensure_table, get_report
    track_event("boot", meta={"vw": "1920x1080"})
    track_event("module_switch", meta={"from": "live", "to": "market"})
    report = get_report(days=30)
"""

import json
import logging
import sqlite3
import time
from typing import Any, Dict, Optional

from services.db import get_db

log = logging.getLogger(__name__)

# Rate limit: max 1 event per second per client (by IP)
# Set _RATE_LIMIT_WINDOW = 0 to disable (for tests).
import os

RATE_LIMIT_WINDOW = float(os.environ.get("BETA_ANALYTICS_RATE_LIMIT", "1"))
_rate_cache: Dict[str, float] = {}


def ensure_table() -> None:
    """Create beta_analytics if missing (self-healing for fresh DBs)."""
    try:
        conn = get_db()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS beta_analytics (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        INTEGER NOT NULL,
                event     TEXT NOT NULL,
                meta      TEXT NOT NULL DEFAULT '{}',
                tenant_id TEXT NOT NULL DEFAULT '',
                client_ip TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_beta_analytics_event_ts "
            "ON beta_analytics(event, ts)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_beta_analytics_tenant "
            "ON beta_analytics(tenant_id, ts)"
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        log.warning("[beta_analytics] table bootstrap failed: %s", e)


def track_event(
    event: str,
    meta: Optional[Dict[str, Any]] = None,
    tenant_id: str = "",
    client_ip: str = "",
) -> bool:
    """Record one analytics event. Best-effort; failures are logged, not raised.

    Rate-limited: max 1 event per second per client IP.
    """
    if not event or event not in ("boot", "module_switch", "module_time"):
        return False

    # Rate limit (skip when window=0, e.g. tests)
    now = time.time()
    if RATE_LIMIT_WINDOW > 0:
        last = _rate_cache.get(client_ip, 0)
        if now - last < RATE_LIMIT_WINDOW:
            return False
    _rate_cache[client_ip] = now

    try:
        ensure_table()
        conn = get_db()
        ts = int(now)
        meta_json = json.dumps(meta or {}, separators=(",", ":"))[:4096]
        conn.execute(
            "INSERT INTO beta_analytics(ts, event, meta, tenant_id, client_ip) "
            "VALUES(?, ?, ?, ?, ?)",
            (ts, event, meta_json, tenant_id, client_ip),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        log.warning("[beta_analytics] track failed: %s", e)
        return False


def get_report(days: int = 30) -> Dict[str, Any]:
    """Generate an analytics report for the last N days.

    Returns:
        - total_events: total event count
        - unique_tenants: unique tenant_ids
        - dau: daily active users (unique tenants per day)
        - wau: weekly active users
        - module_time: avg seconds per module
        - module_usage: event count per module (from module_switch)
        - boot_count: total boots
        - module_switch_count: total switches
        - dropoff: boots with 0 module_switches (onboarding incomplete)
    """
    try:
        conn = get_db()
        since = int(time.time()) - (days * 86400)

        # Total events
        row = conn.execute(
            "SELECT COUNT(*) FROM beta_analytics WHERE ts >= ?", (since,)
        ).fetchone()
        total_events = row[0] if row else 0

        # Unique tenants
        row = conn.execute(
            "SELECT COUNT(DISTINCT tenant_id) FROM beta_analytics "
            "WHERE ts >= ? AND tenant_id != ''",
            (since,),
        ).fetchone()
        unique_tenants = row[0] if row else 0

        # DAU (unique tenants per day)
        dau_rows = conn.execute(
            "SELECT DATE(ts, 'unixepoch') as day, COUNT(DISTINCT tenant_id) "
            "FROM beta_analytics WHERE ts >= ? AND tenant_id != '' "
            "GROUP BY day ORDER BY day",
            (since,),
        ).fetchall()
        dau = [{"day": r[0], "users": r[1]} for r in dau_rows]

        # WAU (unique tenants per week)
        wau_rows = conn.execute(
            "SELECT STRFTIME('%Y-W%W', ts, 'unixepoch') as week, "
            "COUNT(DISTINCT tenant_id) "
            "FROM beta_analytics WHERE ts >= ? AND tenant_id != '' "
            "GROUP BY week ORDER BY week",
            (since,),
        ).fetchall()
        wau = [{"week": r[0], "users": r[1]} for r in wau_rows]

        # Module time (avg seconds per module from module_time events)
        mod_time_rows = conn.execute(
            "SELECT meta FROM beta_analytics " "WHERE event='module_time' AND ts >= ?",
            (since,),
        ).fetchall()
        mod_times: Dict[str, list] = {}
        for r in mod_time_rows:
            try:
                m = json.loads(r[0] or "{}")
                mod = m.get("module", "")
                secs = m.get("seconds", 0)
                if mod and isinstance(secs, (int, float)) and secs > 0:
                    mod_times.setdefault(mod, []).append(secs)
            except (json.JSONDecodeError, TypeError):
                pass
        module_time = {
            mod: {
                "avg_seconds": round(sum(v) / len(v), 1),
                "total_seconds": round(sum(v), 1),
                "sessions": len(v),
            }
            for mod, v in mod_times.items()
        }

        # Module usage (from module_switch events)
        switch_rows = conn.execute(
            "SELECT meta FROM beta_analytics "
            "WHERE event='module_switch' AND ts >= ?",
            (since,),
        ).fetchall()
        module_usage: Dict[str, int] = {}
        for r in switch_rows:
            try:
                m = json.loads(r[0] or "{}")
                to_mod = m.get("to", "")
                if to_mod:
                    module_usage[to_mod] = module_usage.get(to_mod, 0) + 1
            except (json.JSONDecodeError, TypeError):
                pass

        # Boot count
        row = conn.execute(
            "SELECT COUNT(*) FROM beta_analytics " "WHERE event='boot' AND ts >= ?",
            (since,),
        ).fetchone()
        boot_count = row[0] if row else 0

        # Module switch count
        row = conn.execute(
            "SELECT COUNT(*) FROM beta_analytics "
            "WHERE event='module_switch' AND ts >= ?",
            (since,),
        ).fetchone()
        module_switch_count = row[0] if row else 0

        # Dropoff: boots that never triggered a module_switch.
        # Self-hosted instances have no JWT, so tenant_id is always empty —
        # fall back to client_ip grouping, and if that's also empty (test
        # client), use row-level counting (boots without ANY switch).
        boot_rows = conn.execute(
            "SELECT client_ip FROM beta_analytics " "WHERE event='boot' AND ts >= ?",
            (since,),
        ).fetchall()
        switch_rows = conn.execute(
            "SELECT client_ip FROM beta_analytics "
            "WHERE event='module_switch' AND ts >= ?",
            (since,),
        ).fetchall()
        boot_ips = {r[0] for r in boot_rows if r[0]}
        switch_ips = {r[0] for r in switch_rows if r[0]}
        boot_total = len(boot_rows)
        # If we have IP data, use IP-based dropoff; otherwise fall back to
        # simple count: boots that had a switch vs total boots
        if boot_ips and switch_ips:
            dropoff_count = len(boot_ips - switch_ips)
        else:
            # Fallback: count boots where no module_switch exists at all
            dropoff_count = (
                boot_total - module_switch_count
                if module_switch_count < boot_total
                else 0
            )
        dropoff = {
            "boot_without_switch": dropoff_count,
            "boot_total": boot_total,
            "rate": (round(dropoff_count / boot_total * 100, 1) if boot_total else 0),
        }

        conn.close()
        return {
            "days": days,
            "total_events": total_events,
            "unique_tenants": unique_tenants,
            "dau": dau,
            "wau": wau,
            "module_time": module_time,
            "module_usage": module_usage,
            "boot_count": boot_count,
            "module_switch_count": module_switch_count,
            "dropoff": dropoff,
        }
    except Exception as e:
        log.warning("[beta_analytics] report failed: %s", e)
        return {"error": str(e)}
