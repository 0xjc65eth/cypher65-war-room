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
    - complete payment provider   — checkout + signed fulfillment settings;
                                   a partial API credential never activates it
    - ``PRO_KEYS_DB=1``           — dynamic keys issued manually via the
                                   /api/admin/licenses route (no provider)

  When active, PRO-tier endpoints require a valid key via the
  ``X-License-Key`` header or the ``?license=`` query param. Gated routes
  return 402 Payment Required with an upgrade payload the frontend renders
  as a PRO CTA.

Feature matrix (docs/BUSINESS_PLAN.md, R1 scope):
  PRO:      Monte Carlo simulation, proximity meter, 30d history, webhooks
  PREMIUM:  AI Operator real (LLM chat) — $29/mo, upsell PRO → PREMIUM
  (R2+):    API keys, CSV exports, config backup, white-label

Tiers: ``pro`` < ``premium``. A premium key also unlocks every PRO feature
(_key_valid accepts it); ``is_premium()`` gates the PREMIUM surface. Static
premium keys live in ``PREMIUM_LICENSE_KEYS`` (mirror of PRO_LICENSE_KEYS);
dynamic premium keys are DB rows with plan='premium' (Lemon Squeezy premium
variant or /api/admin/licenses plan=premium).

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

from helpers import mask_email
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import List, Optional

from flask import has_request_context, jsonify, request

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

# PREMIUM feature ids (tier 2 — AI Operator real LLM). Kept here so the
# /api/license-status payload and any UI copy stay in sync.
PREMIUM_FEATURES = ["ai_operator"]

# Dynamic key format: C65-XXXX-XXXX-XXXX-XXXX (16 chars of a safe alphabet).
_KEY_PREFIX = "C65"
_KEY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no I/L/O/0/1 — copy-safe

# Explicit key stores flip the gate on immediately. Payment providers only
# activate it when checkout *and* fulfillment are complete; a stray API key
# must never lock the product behind a checkout that cannot deliver a key.
_ACTIVATION_ENV = ("PRO_LICENSE_KEYS", "PREMIUM_LICENSE_KEYS", "PRO_KEYS_DB")

_PAID_SOURCES = frozenset(("lemon_squeezy", "btcpay", "webln"))

_UTC = timezone.utc


# ── Configuration ─────────────────────────────────────────────────────


def _configured_keys() -> List[str]:
    """Read PRO_LICENSE_KEYS from the env at CALL time (test-friendly).

    Reading lazily (mirrors services/tenant.auth_configured) means tests can
    monkeypatch the env var without re-importing the module.
    """
    raw = os.environ.get("PRO_LICENSE_KEYS", "") or ""
    return [k.strip() for k in raw.split(",") if k.strip()]


def _configured_premium_keys() -> List[str]:
    """Read PREMIUM_LICENSE_KEYS from the env at CALL time (test-friendly)."""
    raw = os.environ.get("PREMIUM_LICENSE_KEYS", "") or ""
    return [k.strip() for k in raw.split(",") if k.strip()]


def licensing_configured() -> bool:
    """True when the operator has activated a usable license gate."""
    for name in _ACTIVATION_ENV:
        if os.environ.get(name):
            return True
    btcpay_ready = all(
        os.environ.get(name)
        for name in (
            "BTCPAY_URL",
            "BTCPAY_API_KEY",
            "BTCPAY_STORE_ID",
            "BTCPAY_WEBHOOK_SECRET",
        )
    )
    return bool(btcpay_ready or os.environ.get("LN_INVOICE_ENDPOINT"))


def _db_license_record(key: str) -> Optional[dict]:
    """Return the complete DB record needed to explain a key's state."""
    if not key:
        return None
    try:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT plan, source, expires_at, revoked_at FROM pro_licenses "
                "WHERE key = ?",
                (key,),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return dict(row) if row else None


def license_details(key: str = "") -> dict:
    """Resolve an authoritative, user-facing license lifecycle state.

    The response deliberately contains no key, email or provider payment
    details. ``trial_active`` covers open beta and non-payment/manual keys;
    provider-issued keys are ``paid_active``.
    """
    if not key and not licensing_configured():
        return {
            "license_state": "trial_active",
            "tier": "premium",
            "access_source": "open_beta",
            "expires_at": None,
        }
    if not key:
        return {
            "license_state": "license_required",
            "tier": "free",
            "access_source": None,
            "expires_at": None,
        }
    for configured in _configured_premium_keys():
        if hmac.compare_digest(str(key), str(configured)):
            return {
                "license_state": "paid_active",
                "tier": "premium",
                "access_source": "static",
                "expires_at": None,
            }
    for configured in _configured_keys():
        if hmac.compare_digest(str(key), str(configured)):
            return {
                "license_state": "paid_active",
                "tier": "pro",
                "access_source": "static",
                "expires_at": None,
            }
    row = _db_license_record(key)
    if not row:
        return {
            "license_state": "invalid",
            "tier": "free",
            "access_source": None,
            "expires_at": None,
        }
    source = str(row.get("source") or "manual").strip().lower()
    expires_at = row.get("expires_at") or None
    if row.get("revoked_at"):
        state = "revoked"
    elif expires_at:
        try:
            state = (
                "expired"
                if datetime.fromisoformat(str(expires_at)) <= datetime.now(_UTC)
                else "paid_active" if source in _PAID_SOURCES else "trial_active"
            )
        except (TypeError, ValueError):
            state = "invalid"
    else:
        state = "paid_active" if source in _PAID_SOURCES else "trial_active"
    active = state in ("paid_active", "trial_active")
    plan = str(row.get("plan") or "pro").strip().lower()
    return {
        "license_state": state,
        "tier": ("premium" if plan == "premium" else "pro") if active else "free",
        "access_source": source,
        "expires_at": expires_at,
    }


def _db_key_valid(key: str) -> bool:
    """Validate a dynamically-issued key against the pro_licenses table.

    Accepts non-revoked, non-expired keys. The table may not exist yet
    (never written) — treated as "no such key", never raised.
    """
    if not key:
        return False
    return license_details(key)["license_state"] in ("paid_active", "trial_active")


def _key_valid(key: str) -> bool:
    """Constant-time membership check against static env keys, then DB.

    Accepts PRO AND PREMIUM static keys (a premium key also unlocks PRO
    features), plus any non-revoked DB key.
    """
    if not key:
        return False
    for k in _configured_keys() + _configured_premium_keys():
        if hmac.compare_digest(str(key), str(k)):
            return True
    return _db_key_valid(key)


def _key_plan(key: str) -> str:
    """Resolve the tier of a key: 'premium' | 'pro' | 'free'.

    Static env keys win (PREMIUM_LICENSE_KEYS > PRO_LICENSE_KEYS); DB keys
    report their stored plan. Empty/unknown → 'free'. Never raises.
    """
    if not key:
        return "free"
    return str(license_details(key)["tier"])


def current_license_key() -> str:
    """Extract the license key from X-License-Key header or ?license= param."""
    if not has_request_context():
        return ""
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


def is_premium() -> bool:
    """True when the current request is entitled to the PREMIUM tier.

    Open mode → always True (self-hosters never locked out, same ethos as
    is_pro). Licensed mode → True ONLY for a premium key (static
    PREMIUM_LICENSE_KEYS or a DB key with plan='premium').
    """
    if not licensing_configured():
        return True
    return _key_plan(current_license_key()) == "premium"


def server_pro_active() -> bool:
    """PRO entitlement for BACKGROUND tasks (no request context).

    Request-scoped ``is_pro()`` reads the X-License-Key header — impossible
    in the poll/sweep threads (Issue #178: Auto-Pilot Fase 4 runs the
    autonomous pass inside _do_poll). Rules:
      - Open mode (no activation env) → True: the operator owns the
        deployment and is never locked out (same ethos as is_pro()).
      - Licensed mode → True ONLY when the operator pins a server-side key
        via AUTO_PILOT_PRO_KEY (a valid static/env key) — the background
        pilot must never act on an expired/absent license.
    """
    if not licensing_configured():
        return True
    key = (os.environ.get("AUTO_PILOT_PRO_KEY") or "").strip()
    return bool(key) and _key_valid(key)


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
        # CFO: the user just SAW the paywall — that is funnel stage #1.
        # Best-effort telemetry (never raises, never blocks the 402).
        _track_paywall(getattr(f, "__name__", ""), tier="pro")
        return (
            jsonify(
                {
                    "error": "PRO feature requires a license key",
                    "code": "LICENSE_REQUIRED",
                    "required_tier": "pro",
                    "features": PRO_FEATURES,
                    "upgrade": {
                        "plan": "PRO",
                        "price_usd_month": 9,
                    },
                }
            ),
            402,
        )

    return wrapper


def _track_paywall(feature: str, tier: str = "pro") -> None:
    """Best-effort funnel telemetry for a 402 paywall (never raises)."""

    try:
        from services.conversion import track_event

        tenant = ""
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            try:
                from services.auth import verify_token

                payload = verify_token(auth[7:]) or {}
                tenant = payload.get("sub") or ""
            except Exception:
                pass
        track_event(
            "paywall_view",
            tenant_id=tenant,
            meta={"feature": feature, "tier": tier},
        )
    except Exception:
        pass


def premium_required(f):
    """Flask decorator: require the PREMIUM tier on gated routes.

    No-op in open mode (self-hosters keep everything free). In licensed
    mode: a valid premium key passes; anyone else gets 402 with the tier
    upgrade payload (free → PRO first, PRO → PREMIUM) + paywall telemetry.
    """

    @wraps(f)
    def wrapper(*args, **kwargs):
        if not licensing_configured():
            return f(*args, **kwargs)
        key = current_license_key()
        if _key_plan(key) == "premium":
            return f(*args, **kwargs)
        # The user just SAW the premium paywall — funnel stage #1.
        _track_paywall(getattr(f, "__name__", ""), tier="premium")
        current_tier = "pro" if _key_valid(key) else "free"
        return (
            jsonify(
                {
                    "error": "PREMIUM feature requires a license key",
                    "code": "LICENSE_REQUIRED",
                    "required_tier": "premium",
                    "current_tier": current_tier,
                    "features": PREMIUM_FEATURES,
                    "upgrade": {
                        "plan": "PREMIUM",
                        "price_usd_month": 29,
                    },
                }
            ),
            402,
        )

    return wrapper


def _ai_operator_configured() -> bool:
    """True when the server has an LLM key wired for the AI Operator.

    Read at call time (import-safe, never raises) so /api/license-status can
    tell the frontend whether the PREMIUM surface is usable on this deploy.
    """
    try:
        from services import ai_operator

        return bool(getattr(ai_operator, "AI_API_KEY", ""))
    except Exception:
        return False


def license_status() -> dict:
    """Serialize current licensing state for /api/license-status.

    Drives the topbar PRO badge + frontend lock overlays + upgrade modal.
    """
    ai_configured = _ai_operator_configured()
    configured = licensing_configured()
    key = current_license_key()
    details = license_details(key)
    if not configured:
        key_valid = (
            details["license_state"] in ("paid_active", "trial_active") if key else None
        )
        return {
            "mode": "open",
            "tier": "premium",
            "pro": True,
            "premium": True,
            "license_state": "trial_active",
            "submitted_license_state": details["license_state"] if key else None,
            "key_valid": key_valid,
            "access_source": "open_beta",
            "expires_at": None,
            "features": {f: "unlocked" for f in PRO_FEATURES + PREMIUM_FEATURES},
            "upgrade": None,
            "payments": None,
            "ai_configured": ai_configured,
        }
    plan = details["tier"]
    premium = plan == "premium"
    pro = plan in ("premium", "pro")
    upgrade = None
    if not pro:
        upgrade = {"plan": "PRO", "price_usd_month": 9}
    elif not premium:
        upgrade = {"plan": "PREMIUM", "price_usd_month": 29}
    return {
        "mode": "licensed" if configured else "open",
        "tier": plan,  # premium | pro | free
        "pro": pro,
        "premium": premium,
        "license_state": details["license_state"],
        "access_source": details["access_source"],
        "expires_at": details["expires_at"],
        "key_valid": details["license_state"] in ("paid_active", "trial_active"),
        "features": {f: ("unlocked" if pro else "locked") for f in PRO_FEATURES}
        | {f: ("unlocked" if premium else "locked") for f in PREMIUM_FEATURES},
        "upgrade": upgrade,
        "payments": None,
        "ai_configured": ai_configured,
    }


# ── Dynamic key lifecycle (R1 revenue) ────────────────────────────────


def generate_license_key() -> str:
    """Generate a copy-safe PRO license key: C65-XXXX-XXXX-XXXX-XXXX."""
    groups = [
        "".join(secrets.choice(_KEY_ALPHABET) for _ in range(4)) for _ in range(4)
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
    # PII-safe log (Issue #116): masked email only — never the raw address.
    log.info(
        "license issued: plan=%s source=%s email=%s months=%s",
        plan,
        source,
        mask_email(email),
        months,
    )
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
