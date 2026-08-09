"""
CYPHER65 // Webhook Delivery Queue (retry with backoff)
=======================================================
Webhook dispatch is currently fire-and-forget: if Discord/Telegram is
temporarily unreachable at alert time, the POST fails and the alert is LOST
forever (the per-worker ``alert_seen`` dedup prevents a re-fire).

This module adds a PERSISTENT SQLite-backed retry queue:

    dispatch_webhook_or_queue(...)  → try now; on failure, enqueue
    process_due_webhooks()          → deliver due rows with exponential backoff
    webhook_queue_loop()            → daemon thread hook for app boot

Failure policy (per row):
  - attempts 0..3 with backoff [30s, 2min, 10min, 30min]
  - after WEBHOOK_MAX_ATTEMPTS the row is dropped (logged) — a webhook that
    is down for 40+ minutes is a configuration problem, not a retry problem.

Usage:
    from services.webhook_queue import dispatch_webhook_or_queue, webhook_queue_loop
    ok = dispatch_webhook_or_queue(url=..., severity="CRIT", ...)
"""
import json
import logging
import sqlite3
import time
from typing import Any, Dict, Optional

from services.db import get_db
# Top-level imports (monkeypatch-safe): tests patch these module attributes,
# and dispatch/process call them by reference. Local imports would bypass
# monkeypatch and make the retry queue untestable.
from services.push_notifier import (
    send_webhook_for_alert,
    send_webhook_notification,
    severity_meets_threshold,
)

log = logging.getLogger("cypher65.webhook_queue")

# Retry schedule (seconds between attempts), indexed by current attempt count.
WEBHOOK_RETRY_BACKOFF = [30, 120, 600, 1800]
WEBHOOK_MAX_ATTEMPTS = len(WEBHOOK_RETRY_BACKOFF)
_QUEUE_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS webhook_queue (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    payload     TEXT NOT NULL,            -- JSON of the webhook kwargs
    attempts    INTEGER NOT NULL DEFAULT 0,
    next_retry_ts INTEGER NOT NULL,
    last_error  TEXT NOT NULL DEFAULT '',
    tenant_id   TEXT NOT NULL DEFAULT '',
    created_at  INTEGER NOT NULL
)
"""
_QUEUE_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_webhook_queue_due "
    "ON webhook_queue(next_retry_ts, attempts)"
)


def ensure_table() -> None:
    """Idempotent bootstrap — safe to call on every dispatch (cheap)."""
    try:
        conn = get_db()
        conn.execute(_QUEUE_TABLE_DDL)
        conn.execute(_QUEUE_INDEX_DDL)
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        log.warning("[webhook_queue] bootstrap failed: %s", e)


def enqueue_webhook(webhook_kwargs: Dict[str, Any], tenant_id: str = "",
                    delay_secs: Optional[int] = None) -> bool:
    """Persist a failed webhook for later retry.

    Args:
        webhook_kwargs: the kwargs send_webhook_notification accepts
            (url, severity, category, message, ts, worker, address, timeout).
        tenant_id: owner (for future admin filtering / per-tenant budgets).
        delay_secs: first retry delay; defaults to WEBHOOK_RETRY_BACKOFF[0].

    Returns True when queued. Best-effort — never raises.
    """
    if not webhook_kwargs or not webhook_kwargs.get("url"):
        return False
    import json as _json
    try:
        ensure_table()
        conn = get_db()
        now = int(time.time())
        delay = delay_secs if delay_secs is not None else WEBHOOK_RETRY_BACKOFF[0]
        conn.execute(
            "INSERT INTO webhook_queue (payload, attempts, next_retry_ts, "
            "tenant_id, created_at) VALUES (?, 0, ?, ?, ?)",
            (_json.dumps(webhook_kwargs), now + delay, tenant_id, now),
        )
        conn.commit()
        conn.close()
        log.info("[webhook_queue] queued retry for %s (tenant=%s, retry in %ds)",
                 (webhook_kwargs.get("category") or "?"), tenant_id[:8] or "-", delay)
        return True
    except Exception as e:  # noqa: BLE001 — queue is best-effort
        log.warning("[webhook_queue] enqueue failed: %s", e)
        return False


def dispatch_webhook_or_queue(
    url: str,
    severity: str,
    category: str,
    message: str,
    ts: int = 0,
    worker: str = "",
    address: str = "",
    min_severity: str = "WARN",
    timeout: int = 5,
    tenant_id: str = "",
) -> bool:
    """Send a webhook now; on failure, persist it for retry.

    This is the entry point callers should use instead of the raw
    ``send_webhook_notification`` when they want delivery guarantees:
      - success → returns True, nothing queued
      - below min_severity / empty url → returns False, NOT queued (it is a
        legitimate skip, not a delivery failure)
      - network/HTTP failure → queued for retry, returns False

    Never raises.
    """
    try:
        ok = send_webhook_for_alert(
            url=url, severity=severity, category=category, message=message,
            ts=ts, worker=worker, address=address,
            min_severity=min_severity, timeout=timeout,
        )
    except Exception as e:
        log.warning("[webhook_queue] dispatch error: %s", e)
        ok = False
    if not ok:
        # Only queue genuine delivery failures — a below-threshold alert is a
        # legitimate skip (send_webhook_for_alert returns False for both, so
        # re-check the threshold to avoid queueing noise).
        if url and severity_meets_threshold(severity, min_severity):
            enqueue_webhook({
                "url": url, "severity": severity, "category": category,
                "message": message, "ts": ts, "worker": worker,
                "address": address, "min_severity": min_severity,
                "timeout": timeout,
            }, tenant_id=tenant_id)
    return ok


def process_due_webhooks(now: Optional[int] = None, max_batch: int = 20) -> int:
    """Deliver due webhook rows with retry/backoff. Returns rows processed.

    Call periodically (webhook_queue_loop) or after a dispatch failure. Each
    due row is attempted once; on failure its attempt counter advances and
    next_retry_ts moves out by WEBHOOK_RETRY_BACKOFF[attempts]; rows past
    WEBHOOK_MAX_ATTEMPTS are dropped (logged). Never raises.
    """
    now = int(now or time.time())
    processed = 0
    try:
        ensure_table()
        conn = get_db()
        rows = conn.execute(
            "SELECT id, payload, attempts FROM webhook_queue "
            "WHERE next_retry_ts <= ? AND attempts < ? "
            "ORDER BY next_retry_ts LIMIT ?",
            (now, WEBHOOK_MAX_ATTEMPTS, max_batch),
        ).fetchall()
        for row in rows:
            processed += 1
            qid, payload_raw, attempts = row["id"], row["payload"], row["attempts"]
            try:
                kwargs = json.loads(payload_raw)
                ok = send_webhook_notification(
                    url=kwargs.get("url", ""),
                    severity=kwargs.get("severity", "WARN"),
                    category=kwargs.get("category", ""),
                    message=kwargs.get("message", ""),
                    ts=kwargs.get("ts", 0),
                    worker=kwargs.get("worker", ""),
                    address=kwargs.get("address", ""),
                    timeout=kwargs.get("timeout", 5),
                )
            except Exception as e:  # noqa: BLE001
                log.warning("[webhook_queue] retry row %d error: %s", qid, e)
                ok = False
            if ok:
                conn.execute("DELETE FROM webhook_queue WHERE id = ?", (qid,))
            else:
                nxt = attempts + 1
                if nxt >= WEBHOOK_MAX_ATTEMPTS:
                    log.warning("[webhook_queue] dropping webhook %d after "
                                "%d attempts (provider down too long)", qid, nxt)
                    conn.execute("DELETE FROM webhook_queue WHERE id = ?", (qid,))
                else:
                    delay = WEBHOOK_RETRY_BACKOFF[nxt]
                    conn.execute(
                        "UPDATE webhook_queue SET attempts=?, next_retry_ts=?, "
                        "last_error=? WHERE id=?",
                        (nxt, now + delay, "failed", qid),
                    )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        log.warning("[webhook_queue] process error: %s", e)
    return processed


def queue_depth() -> int:
    """Pending rows (any state) — for /api/admin/sessions-style observability."""
    try:
        ensure_table()
        conn = get_db()
        row = conn.execute("SELECT COUNT(*) AS n FROM webhook_queue").fetchone()
        conn.close()
        return row["n"] if row else 0
    except sqlite3.Error:
        return 0


def webhook_queue_loop(interval: int = 30) -> None:
    """Daemon thread body: deliver due webhooks every ``interval`` seconds."""
    while True:
        try:
            process_due_webhooks()
        except Exception as e:  # noqa: BLE001 — loop must never die
            log.warning("[webhook_queue] loop iteration error: %s", e)
        time.sleep(interval)
