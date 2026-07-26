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
from typing import Dict, Any, List, Optional

log = logging.getLogger("cypher65.push")

# ── VAPID configuration ──────────────────────────────────────────────
import os

VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_CLAIMS = {"sub": "mailto:admin@cypher65.local"}

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
    Get current push subscriptions from the app module.
    Returns empty dict if app not accessible or no subscriptions.
    """
    try:
        import app as _app
        return getattr(_app, "_push_subscriptions", {})
    except Exception:
        return {}


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
