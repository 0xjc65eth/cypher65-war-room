"""
CYPHER65 // Licensing (R1 — PRO tier gate)
===========================================
Off-by-default monetization infrastructure (CFO overhaul, R1).

Design principle — OFF BY DEFAULT:
  When NO licensing env is set (the current production state), the gate is a
  no-op: every feature stays free and the dashboard behaves exactly as today
  (honest-telemetry ethos preserved, self-hosters never locked out).

  The gate ACTIVATES when the operator sets any of:
    - ``PRO_LICENSE_KEYS``        — static comma-separated keys (legacy mode)
    - ``LEMON_SQUEEZY_API_KEY``   — dynamic keys issued from paid checkouts
                                   (services/payments.py fulfills them here)
    - ``PRO_KEYS_DB=1``           — dynamic keys issued manually via the
                                   /api/admin/licenses route (no provider)

  When active, PRO-tier endpoints require a valid key via the
  ``X-License-Key`` header or the ``?license=`` query param. Gated routes
  return 402 Payment Required with an upgrade payload the frontend renders
  as a PRO CTA.

Feature matrix (docs/BUSINESS_PLAN.md, R1 scope):
  PRO:      Monte Carlo simulation, proximity meter, 30d history, webhooks
  (R2+):    API keys, CSV exports, config backup, white-label

Dynamic keys (R1 revenue):
  ``issue_license()`` creates a cryptographically-random key of the form
  ``C65-XXXX-XXXX-XXXX-XXXX`` persisted in the ``pro_licenses`` table (key,
  plan, email, source, created_at, expires_at, revoked_at). ``_key_valid``
  accepts BOTH static env keys and non-revoked, non-expired DB keys — so a
  customer who pays via LemonSqueezy gets a key the existing gate honors
  with zero changes to the gated routes.

Usage:
    from services.licensing import pro_required, is_pro, license_status,
                                    issue_license, generate_license_key

    @app.route("/api/monte_carlo")
    @pro_required
    def api_monte_carlo():
        ...
"""
import hmac
import logging
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import List, Optional

from flask import jsonify, request

from services.db import get_db

log = logging.getLogger("cypher65.licensing")

# PRO feature ids (drives the frontend badge/lock overlays). Kept in one
# place so the /api/license-status payload and any UI copy stay in sync.
PRO_FEATURES = [
    "monte_carlo",
    "proximity_meter",
    "history_30d",
    "webhooks",
]

# Dynamic key format: C65-XXXX-XXXX-XXXX-XXXX (16 chars of a safe alphabet).
_KEY_PREFIX = "C65"
_KEY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no I/L/O/0/1 — copy-safe

# Env vars that flip the gate ON (additive; existing deployments untouched).
_ACTIVATION_ENV = ("PRO_LICENSE_KEYS", "LEMON_SQUEEZY_API_KEY", "PRO_KEYS_DB")

_UTC = timezone.utc


# ── Configuration ─────────────────────────────────────────────────────

def _configured_keys() -> List[str]:
    """Read PRO_LICENSE_KEYS from the env at CALL time (test-friendly).

    Reading lazily (mirrors services/tenant.auth_configured) means tests can
    monkeypatch the env var without re-importing the module.
    """
    raw = os.environ.get("PRO_LICENSE_KEYS", "") or ""
    return [k.strip() for k in raw.split(",") if k.strip()]


def licensing_configured() -> bool:
    """True when the operator has activated the gate (any activation env)."""
    for name in _ACTIVATION_ENV:
        if os.environ.get(name):
            return True
    return False


def _db_key_valid(key: str) -> bool:
    """Validate a dynamically-issued key against the pro_licenses table.

    Accepts non-revoked, non-expired keys. The table may not exist yet
    (never written) — treated as "no such key", never raised.
    """
    if not key:
        return False
    try:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT expires_at FROM pro_licenses "
                "WHERE key = ? AND revoked_at IS NULL",
                (key,),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    if not row:
        return False
    exp = row["expires_at"]
    if not exp:
        return True  # lifetime key
    try:
        return datetime.fromisoformat(exp) > datetime.now(_UTC)
    except (TypeError, ValueError):
        return False


def _key_valid(key: str) -> bool:
    """Constant-time membership check against static env keys, then DB."""
    if not key:
        return False
    for k in _configured_keys():
        if hmac.compare_digest(str(key), str(k)):
            return True
    return _db_key_valid(key)


def current_license_key() -> str:
    """Extract the license key from X-License-Key header or ?license= param."""
    key = (request.headers.get("X-License-Key", "") or "").strip()
    if not key:
        key = (request.args.get("license", "") or "").strip()
    return key


def is_pro() -> bool:
    """True when the current request is entitled to PRO features.

    Open mode (no activation env) → always True (operator owns the
    deployment, never locked out).
    """
    if not licensing_configured():
        return True
    return _key_valid(current_license_key())


def pro_required(f):
    """Flask decorator: require a valid PRO license key on gated routes.

    No-op when licensing is not configured, so the current free deployment
    is untouched. When active and the caller has no valid key, returns
    402 with a structured upgrade payload.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not licensing_configured():
            return f(*args, **kwargs)
        if _key_valid(current_license_key()):
            return f(*args, **kwargs)
        return jsonify({
            "error": "PRO feature requires a license key",
            "code": "LICENSE_REQUIRED",
            "required_tier": "pro",
            "features": PRO_FEATURES,
            "upgrade": {
                "plan": "PRO",
                "price_usd_month": 9,
            },
        }), 402
    return wrapper


def license_status() -> dict:
    """Serialize current licensing state for /api/license-status.

    Drives the topbar PRO badge + frontend lock overlays + upgrade modal.
    """
    payments = "lemon_squeezy" if os.environ.get("LEMON_SQUEEZY_API_KEY") else None
    if not licensing_configured():
        return {
            "mode": "open",          # gate inactive — everything free
            "tier": "pro",
            "pro": True,
            "features": {f: "unlocked" for f in PRO_FEATURES},
            "upgrade": None,
            "payments": payments,
        }
    pro = _key_valid(current_license_key())
    return {
        "mode": "licensed",
        "tier": "pro" if pro else "free",
        "pro": pro,
        "features": {f: ("unlocked" if pro else "locked") for f in PRO_FEATURES},
        "upgrade": None if pro else {"plan": "PRO", "price_usd_month": 9},
        "payments": payments,
    }


# ── Dynamic key lifecycle (R1 revenue) ────────────────────────────────

def generate_license_key() -> str:
    """Generate a copy-safe PRO license key: C65-XXXX-XXXX-XXXX-XXXX."""
    groups = [
        "".join(secrets.choice(_KEY_ALPHABET) for _ in range(4))
        for _ in range(4)
    ]
    return f"{_KEY_PREFIX}-{'-'.join(groups)}"


def _ensure_licenses_table() -> None:
    """Create pro_licenses if missing (self-healing for fresh/scratch DBs)."""
    conn = get_db()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pro_licenses (
                key        TEXT PRIMARY KEY,
                plan       TEXT NOT NULL DEFAULT 'pro',
                email      TEXT DEFAULT '',
                source     TEXT DEFAULT 'manual',
                created_at TEXT NOT NULL,
                expires_at TEXT,
                revoked_at TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def issue_license(
    plan: str = "pro",
    email: str = "",
    source: str = "manual",
    months: Optional[int] = 12,
) -> str:
    """Create and persist a new PRO license key; return it.

    months=None → lifetime key. Raises sqlite3.Error on DB failure (caller
    decides whether to fail the request or degrade).
    """
    _ensure_licenses_table()
    key = generate_license_key()
    expires = None
    if months is not None:  # months=0 → expires immediately; None → lifetime
        expires = (datetime.now(_UTC) + timedelta(days=30 * months)).isoformat()
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO pro_licenses "
            "(key, plan, email, source, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (key, plan, email, source, datetime.now(_UTC).isoformat(), expires),
        )
        conn.commit()
    finally:
        conn.close()
    log.info("license issued: plan=%s source=%s email=%s months=%s", plan, source, email or "-", months)
    return key


def revoke_license(key: str) -> bool:
    """Revoke a license key (soft delete via revoked_at). False if unknown."""
    _ensure_licenses_table()
    conn = get_db()
    try:
        cur = conn.execute(
            "UPDATE pro_licenses SET revoked_at = ? WHERE key = ? AND revoked_at IS NULL",
            (datetime.now(_UTC).isoformat(), key),
        )
        conn.commit()
    finally:
        conn.close()
    return cur.rowcount > 0
