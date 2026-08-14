"""
CYPHER65 // Push Notification Service
=====================================
Sends Web Push notifications for critical mining alerts.
Hooks into the polling loop to detect new CRIT/WARN alerts
and dispatches them to subscribed browsers.

Usage from polling.py:
    from services.push_notifier import notify_alert
    notify_alert(severity, category, message)
"""

import json
import logging
import time
import datetime as _dt
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse, parse_qs

import requests

log = logging.getLogger("cypher65.push")

# ── VAPID configuration (Issue #15) ───────────────────────────────────
# Web Push is OFF until the operator sets VAPID_PUBLIC_KEY + VAPID_PRIVATE_KEY
# (deploy blueprint: render.yaml). The push service needs a contact subject to
# reach the operator about key expiry / policy — VAPID_SUBJECT env-gates it,
# falling back to the repo-local placeholder only as a last resort.
import os

VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:admin@cypher65.local")
VAPID_CLAIMS = {"sub": VAPID_SUBJECT}

# ── Event severity → notification title mapping ──────────────────────
SEVERITY_TITLES = {
    "CRIT": "🚨 CRITICAL: Mining Alert",
    "CRITICAL": "🚨 CRITICAL: Mining Alert",
    "WARN": "⚠️ WARNING: Mining Alert",
    "GOLD": "🏆 GOLD: Mining Milestone",
    "SUCCESS": "✅ Mining Update",
    "INFO": "ℹ️ Mining Info",
}

# ── Category → context-aware message prefix ──────────────────────────
CATEGORY_CONTEXT = {
    "worker_offline": "Worker has stopped hashing",
    "stale_share": "Share not submitted recently",
    "hashrate_drop": "Hashrate has dropped significantly",
    "disk_write_failure": "Database write failure detected",
    "wallet_changed": "Wallet address changed",
    "new_block": "New block found",
    "best_diff_bump": "Best difficulty improved",
    "network": "Network status change",
}


def _get_push_subscriptions() -> Dict[str, Any]:
    """
    Get current push subscriptions from the app module (legacy in-memory
    store — used only by callers that never migrated to the DB table).
    Returns empty dict if app not accessible or no subscriptions.
    """
    try:
        import app as _app
        return getattr(_app, "_push_subscriptions", {})
    except Exception:
        return {}


# ── Persistent per-tenant push subscriptions (Phase: multi-tenant) ───────
# The old in-memory _push_subscriptions dict was never populated (no
# subscribe endpoint existed), so Web Push never actually fired. These
# helpers persist subscriptions in SQLite scoped to a tenant_id, and
# notify_tenant_alert() delivers to exactly that tenant's devices.


def _ensure_subscriptions_table() -> None:
    try:
        from services.db import get_db
        conn = get_db()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                endpoint   TEXT PRIMARY KEY,
                keys       TEXT NOT NULL DEFAULT '{}',
                tenant_id  TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_push_sub_tenant "
                     "ON push_subscriptions(tenant_id)")
        conn.commit()
        conn.close()
    except Exception:
        pass


# Cap on stored subscriptions: the subscribe endpoint is unauthenticated, so
# bound growth (spam / stale devices) — prune by recency when over the cap.
_PUSH_SUBS_MAX = 5000


def save_subscription(endpoint: str, keys: Dict[str, str], tenant_id: str = "") -> bool:
    """Upsert a push subscription for a tenant. Best-effort."""
    if not endpoint:
        return False
    try:
        _ensure_subscriptions_table()
        from services.db import get_db
        conn = get_db()
        conn.execute(
            "INSERT INTO push_subscriptions (endpoint, keys, tenant_id, created_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(endpoint) DO UPDATE SET keys=excluded.keys, "
            "tenant_id=excluded.tenant_id, created_at=excluded.created_at",
            (endpoint, json.dumps(keys or {}), tenant_id, int(time.time())),
        )
        # Bounded table: prune the oldest rows (by created_at) past the cap
        # so an unauthenticated subscribe endpoint cannot grow the DB forever.
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM push_subscriptions").fetchone()
        if row and row["n"] > _PUSH_SUBS_MAX:
            excess = row["n"] - _PUSH_SUBS_MAX
            conn.execute(
                "DELETE FROM push_subscriptions WHERE endpoint IN "
                "(SELECT endpoint FROM push_subscriptions ORDER BY created_at "
                "ASC LIMIT ?)", (excess,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        log.warning("[push] save_subscription failed: %s", e)
        return False


def remove_subscription(endpoint: str) -> bool:
    """Delete a subscription (called on 404/410 prune)."""
    try:
        _ensure_subscriptions_table()
        from services.db import get_db
        conn = get_db()
        conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        log.warning("[push] remove_subscription failed: %s", e)
        return False


def get_subscriptions_for_tenant(tenant_id: str = "") -> List[Dict[str, Any]]:
    """All push subscriptions owned by a tenant (or the global '' tenant)."""
    try:
        _ensure_subscriptions_table()
        from services.db import get_db
        conn = get_db()
        rows = conn.execute(
            "SELECT endpoint, keys FROM push_subscriptions WHERE tenant_id = ?",
            (tenant_id,),
        ).fetchall()
        conn.close()
        out = []
        for r in rows:
            try:
                keys = json.loads(r["keys"])
            except Exception:
                keys = {}
            out.append({"endpoint": r["endpoint"], "keys": keys})
        return out
    except Exception as e:
        log.warning("[push] get_subscriptions_for_tenant failed: %s", e)
        return []


def notify_tenant_alert(tenant_id: str, severity: str, category: str,
                        message: str, url: str = "/") -> int:
    """Send a Web Push to ALL devices subscribed under a tenant.

    Returns the number of devices notified. Requires pywebpush installed AND
    VAPID keys configured — otherwise it degrades silently (no crash).
    Expired subscriptions (HTTP 404/410) are pruned from the DB.
    """
    if severity not in ("CRIT", "CRITICAL", "WARN", "GOLD"):
        return 0
    if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY:
        return 0
    # Canonical default tenant: /api/push/subscribe stores the operator's
    # dashboard subscription under '' (the legacy/operator tenant), while
    # every require_tenant route normalizes anonymous sessions to 'default'.
    # Without this mapping, worker/sweep pushes to the operator would look up
    # tenant_id='default' and MISS the subscription — silent no-delivery.
    log_tenant = tenant_id or "default"
    if tenant_id == "default":
        tenant_id = ""
    subs = get_subscriptions_for_tenant(tenant_id)
    if not subs:
        return 0
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        log.warning("[push] pywebpush not installed — skipping tenant push")
        return 0

    title = SEVERITY_TITLES.get(severity, "⚡ Mining Alert")
    context = CATEGORY_CONTEXT.get(category, "")
    body = f"{context}: {message}"[:200] if context else message[:200]
    payload = {
        "title": title,
        "body": body,
        "tag": f"cypher65-{category}-{int(time.time() / 300)}",
        "data": {"url": url, "severity": severity, "category": category},
        "requireInteraction": severity in ("CRIT", "CRITICAL"),
        "renotify": True,
        "vibrate": [300, 100, 300] if severity in ("CRIT", "CRITICAL") else [200, 100, 200],
    }

    sent = 0
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys": sub.get("keys", {}),
                },
                data=json.dumps(payload),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS,
            )
            sent += 1
        except WebPushException as e:
            if e.response and e.response.status_code in (404, 410):
                remove_subscription(sub["endpoint"])
        except Exception:
            pass
    if sent > 0:
        log.info("[push] tenant %s notified on %d device(s) for %s/%s",
                 log_tenant[:8], sent, severity, category)
    return sent


def notify_alert(severity: str, category: str, message: str,
                  url: str = "/") -> bool:
    """
    Send a push notification for a mining alert.

    Called from the polling loop when a new critical alert is detected.
    Skips if no subscribers or push not available.

    Args:
        severity: CRIT, WARN, GOLD, SUCCESS, INFO
        category: worker_offline, stale_share, etc.
        message: Alert message text
        url: Dashboard URL to open on click

    Returns:
        True if notification was sent, False if skipped/failed
    """
    # Only send for CRIT/WARN/GOLD severity to avoid noise
    if severity not in ("CRIT", "CRITICAL", "WARN", "GOLD"):
        return False

    subscriptions = _get_push_subscriptions()
    if not subscriptions:
        return False

    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        log.warning("[push] pywebpush not installed — skipping notification")
        return False

    title = SEVERITY_TITLES.get(severity, "⚡ Mining Alert")
    context = CATEGORY_CONTEXT.get(category, "")
    body = f"{context}: {message}" if context else message
    body = body[:200]  # Truncate long messages

    payload = {
        "title": title,
        "body": body,
        "tag": f"cypher65-{category}-{int(time.time() / 300)}",  # dedup within 5min
        "data": {"url": url, "severity": severity, "category": category},
        "requireInteraction": severity in ("CRIT", "CRITICAL"),
        "renotify": True,
        "vibrate": [300, 100, 300] if severity in ("CRIT", "CRITICAL") else [200, 100, 200],
    }

    sent = 0
    failed = 0

    for endpoint, sub in list(subscriptions.items()):
        try:
            webpush(
                subscription_info={
                    "endpoint": endpoint,
                    "keys": sub.get("keys", {}),
                },
                data=json.dumps(payload),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS,
            )
            sent += 1
        except WebPushException as e:
            if e.response and e.response.status_code in (404, 410):
                # Subscription expired
                try:
                    import app as _app
                    if endpoint in _app._push_subscriptions:
                        del _app._push_subscriptions[endpoint]
                except Exception:
                    pass
            failed += 1
        except Exception:
            failed += 1

    if sent > 0:
        log.info("[push] Sent %d notification(s) for %s/%s", sent, severity, category)

    return sent > 0


def notify_if_alert_exists(alerts: List[Dict]) -> bool:
    """
    Check a list of alerts and send push for any that are new and critical.

    Args:
        alerts: List of alert dicts with 'severity', 'category', 'message' keys

    Returns:
        True if any notification was sent
    """
    sent_any = False
    for alert in alerts:
        sev = alert.get("severity", "INFO")
        cat = alert.get("category", "unknown")
        msg = alert.get("message", "")
        if notify_alert(sev, cat, msg):
            sent_any = True
    return sent_any


# ═══════════════════════════════════════════════════════════════════════════
#  Webhook Notifier — Discord / Telegram real-time alert push
# ═══════════════════════════════════════════════════════════════════════════

# Severity → Discord embed colour (decimal).
_WEBHOOK_SEVERITY_COLOR = {
    "CRIT": 0xFF1744,
    "CRITICAL": 0xFF1744,
    "WARN": 0xFFA000,
    "GOLD": 0xFFD700,
    "SUCCESS": 0x00C853,
    "INFO": 0x5E5952,
}

# Severity → emoji prefix used in Telegram / fallback messages.
_WEBHOOK_SEVERITY_EMOJI = {
    "CRIT": "🚨",
    "CRITICAL": "🚨",
    "WARN": "⚠️",
    "GOLD": "🏆",
    "SUCCESS": "✅",
    "INFO": "ℹ️",
}


def send_webhook_notification(
    url: str,
    severity: str,
    category: str,
    message: str,
    ts: int = 0,
    worker: str = "",
    address: str = "",
    timeout: int = 5,
) -> bool:
    """Send a webhook notification for a mining alert.

    Auto-detects Discord vs Telegram and formats the payload accordingly:
      - Discord: rich embed with colour, fields, and footer.
      - Telegram: Markdown-formatted message via ``parse_mode``.
      - Generic (fallback): plain JSON POST with the legacy payload shape.

    Args:
        url: Webhook URL (Discord or Telegram).
        severity, category, message: Alert details from the engine.
        ts: Unix timestamp of the alert.
        worker: Worker / pool worker name (optional).
        address: BTC address (optional).
        timeout: HTTP timeout in seconds.

    Returns:
        True if the POST succeeded (2xx), False otherwise.
        Never raises — all exceptions are caught and logged.
    """
    if not url:
        return False

    is_discord = "discord.com" in url.lower()
    is_telegram = "api.telegram.org" in url.lower()

    try:
        if is_discord:
            return _send_discord_webhook(url, severity, category, message,
                                         ts, worker, address, timeout)
        if is_telegram:
            return _send_telegram_webhook(url, severity, category, message,
                                          ts, worker, address, timeout)
        # Generic fallback — same JSON shape the legacy inline block used.
        payload = {
            "event": "cypher65_war_room_alert",
            "severity": severity,
            "category": category,
            "message": message,
            "ts": ts,
            "worker": worker,
            "address": address,
        }
        resp = requests.post(url, json=payload, timeout=timeout)
        return resp.ok
    except Exception as e:
        log.warning("[webhook] post error: %s", e)
        return False


# Severity ordering for the webhook threshold filter. Single source of truth
# shared by app.py's AlertEngine callback and services/polling.py — callers
# must never re-declare their own ranking.
WEBHOOK_SEVERITY_RANK = {"INFO": 0, "WARN": 1, "CRIT": 2, "CRITICAL": 2, "GOLD": 1, "SUCCESS": 1}


def severity_meets_threshold(severity: str, min_severity: str = "WARN") -> bool:
    """True when ``severity`` is at least as important as ``min_severity``.

    Ordering: INFO < WARN / CRIT / GOLD / SUCCESS. Unknown severities rank
    as INFO so they are filtered out unless the threshold is INFO.
    """
    return (WEBHOOK_SEVERITY_RANK.get(severity, 0)
            >= WEBHOOK_SEVERITY_RANK.get(min_severity, 1))


def send_webhook_for_alert(
    url: str,
    severity: str,
    category: str,
    message: str,
    ts: int = 0,
    worker: str = "",
    address: str = "",
    min_severity: str = "WARN",
    timeout: int = 5,
) -> bool:
    """Severity-thresholded dispatch to Discord/Telegram/generic webhook.

    Returns False when the URL is missing, the alert is below ``min_severity``,
    or the POST fails. Never raises.
    """
    if not url or not severity_meets_threshold(severity, min_severity):
        return False
    return send_webhook_notification(
        url=url, severity=severity, category=category, message=message,
        ts=ts, worker=worker, address=address, timeout=timeout,
    )


def _send_discord_webhook(url, severity, category, message, ts, worker,
                          address, timeout) -> bool:
    """Send a Discord webhook with a rich embed."""
    emoji = _WEBHOOK_SEVERITY_EMOJI.get(severity, "⚡")
    color = _WEBHOOK_SEVERITY_COLOR.get(severity, 0x5E5952)

    # Human-readable timestamp for the embed footer.
    ts_str = _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if ts else ""

    embed = {
        "title": f"{emoji} CYPHER65 — {severity} Alert",
        "description": message[:2000],
        "color": color,
        "fields": [
            {"name": "Severity", "value": severity, "inline": True},
            {"name": "Category", "value": category, "inline": True},
        ],
        "footer": {"text": ts_str},
        "timestamp": _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).isoformat() + "Z" if ts else None,
    }

    # Add worker / address as extra fields when available.
    if worker:
        embed["fields"].append({"name": "Worker", "value": worker, "inline": True})
    if address:
        addr_short = address[:10] + "…" + address[-6:] if len(address) > 16 else address
        embed["fields"].append({"name": "Address", "value": addr_short, "inline": True})

    payload = {"embeds": [embed]}
    resp = requests.post(url, json=payload, timeout=timeout)

    if not resp.ok:
        # Discord returns a helpful error body — log it once for debugging.
        log.debug("[webhook] discord %s — %s", resp.status_code,
                  resp.text[:200] if resp.text else "")
    return resp.ok


def _send_telegram_webhook(url, severity, category, message, ts, worker,
                           address, timeout) -> bool:
    """Send a Telegram message via bot webhook.

    Telegram Bot API ``sendMessage``-compatible: the URL ends with
    ``/bot<token>/sendMessage``. Payload carries ``chat_id`` from the
    query string and ``parse_mode: "MarkdownV2"`` for formatting.
    """
    emoji = _WEBHOOK_SEVERITY_EMOJI.get(severity, "⚡")

    # Try to extract chat_id from query string (common setup pattern).
    chat_id = ""
    try:
        qs = parse_qs(urlparse(url).query)
        chat_id = (qs.get("chat_id") or [""])[0]
    except Exception:
        pass

    # Build a clean Markdown message.
    lines = [
        f"{emoji} *CYPHER65 \\- {_tg_escape(severity)} Alert*",  # noqa: W605
        "",
        f"*Category:* `{category}`",
        f"*Message:* {_tg_escape(message[:500])}",
    ]
    if worker:
        lines.append(f"*Worker:* `{_tg_escape(worker)}`")
    if address:
        lines.append(f"*Address:* `{address[:10]}…{address[-6:] if len(address) > 16 else address}`")

    payload = {
        "text": "\n".join(lines),
        "parse_mode": "MarkdownV2",
    }
    if chat_id:
        payload["chat_id"] = chat_id

    resp = requests.post(url, json=payload, timeout=timeout)
    if not resp.ok:
        log.debug("[webhook] telegram %s — %s", resp.status_code,
                  resp.text[:200] if resp.text else "")
    return resp.ok


def _tg_escape(text: str) -> str:
    """Escape Telegram MarkdownV2 special characters."""
    for ch in "_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, "\\" + ch)
    return text
