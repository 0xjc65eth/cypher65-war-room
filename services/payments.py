"""
CYPHER65 // Payments (R1 revenue — Lemon Squeezy adapter)
==========================================================
Off-by-default payment fulfillment for the PRO license gate.

Provider adapter: Lemon Squeezy (legacy, checkout intentionally disabled).

The signed webhook and idempotency ledger remain available for historical
orders, but the application-generated CYPHER65 key is not yet delivered back
to the authenticated checkout browser.  Enabling the hosted checkout before
that channel exists could accept money without giving the buyer a usable key.

Design — CHECKOUT DISABLED:
  ``payments_configured()`` stays false even when the legacy provider env vars
  exist.  The route returns 503 and purchase CTAs stay hidden.  Re-enable only
  after implementing an authenticated, expiring checkout-status channel that
  delivers the generated key to the same browser that started the purchase.

Historical fulfillment flow (not exposed for new checkout):
  Frontend "Buy PRO" → POST /api/upgrade/checkout → create_checkout() →
  LS hosted checkout URL (opened in a new tab) → LS posts order_created →
  POST /api/payments/webhook (x-signature HMAC-SHA256 verified) →
  handle_webhook() → licensing.issue_license() → customer activates the key
  in the upgrade modal (X-License-Key header, already wired in app.js).

Env vars:
  LEMON_SQUEEZY_API_KEY        — API key (private; insufficient by itself)
  LEMON_SQUEEZY_WEBHOOK_SECRET — secret for x-signature verification
  LEMON_SQUEEZY_STORE_ID       — expected store id for legacy webhooks
  LEMON_SQUEEZY_VARIANT_ID     — accepted legacy PRO variant id
"""

import hashlib
import hmac
import logging
import os
import time
from typing import Optional, Tuple

import requests

from helpers import email_sha, mask_email
from services import licensing
from services.db import get_db

log = logging.getLogger("cypher65.payments")

_API_BASE = "https://api.lemonsqueezy.com/v1"

# Variant ids → (plan, months). Operators override the PRO variant via env
# and pin the PREMIUM variant via LEMON_SQUEEZY_PREMIUM_VARIANT_ID (tier 2,
# Issue #182). Unknown variants are rejected and never fulfill a license.
_PLAN_MONTHS = {"pro": 12, "premium": 12}


def payments_configured(plan: str = "pro") -> bool:
    """Return False until card-license delivery is implemented end to end.

    The provider can create and sign orders, but that alone is insufficient:
    the generated CYPHER65 key currently has no authenticated delivery channel
    back to the buyer.  Keeping this public capability false is deliberate and
    prevents the UI/API from presenting a checkout that cannot complete.
    """
    del plan
    return False


def webhook_configured() -> bool:
    """True when signed webhooks can validate at least one sold variant."""
    return bool(
        os.environ.get("LEMON_SQUEEZY_API_KEY")
        and os.environ.get("LEMON_SQUEEZY_WEBHOOK_SECRET")
        and os.environ.get("LEMON_SQUEEZY_STORE_ID")
        and (
            os.environ.get("LEMON_SQUEEZY_VARIANT_ID")
            or os.environ.get("LEMON_SQUEEZY_PREMIUM_VARIANT_ID")
        )
    )


def payment_capabilities() -> dict:
    """Public, secret-free checkout capabilities for the UI."""
    plans = {
        "pro": payments_configured("pro"),
        "premium": payments_configured("premium"),
    }
    return {
        "provider": "lemon_squeezy" if any(plans.values()) else None,
        "available": any(plans.values()),
        "plans": plans,
        "reason": "license_delivery_unavailable",
    }


def _variant_months(variant_id: str):
    """Map a variant id to (plan, months).

    The operator pins the PREMIUM variant via LEMON_SQUEEZY_PREMIUM_VARIANT_ID;
    Unknown variants return ``None`` and can never issue a license.
    """
    vid = str(variant_id or "")
    premium_variant = (os.environ.get("LEMON_SQUEEZY_PREMIUM_VARIANT_ID") or "").strip()
    if premium_variant and vid == premium_variant:
        return "premium", _PLAN_MONTHS["premium"]
    pro_variant = (os.environ.get("LEMON_SQUEEZY_VARIANT_ID") or "").strip()
    if pro_variant and vid == pro_variant:
        return "pro", _PLAN_MONTHS["pro"]
    return None


def _audit(action: str, target: str = "", details: Optional[dict] = None) -> None:
    """Persist a payment audit event without PII, keys or provider payloads."""
    try:
        from services.tenant import log_audit

        log_audit(
            "default",
            action,
            target=str(target or "")[:32],
            details=details or {},
        )
    except Exception:
        log.warning("payment audit failed: %s", action, exc_info=True)


def create_checkout(
    plan: str = "pro", email: str = "", funnel_id: str = ""
) -> Optional[str]:
    """Return None while Lemon Squeezy customer key delivery is unavailable.

    The retained request-building code is unreachable until
    ``payments_configured`` can truthfully attest to a complete delivery
    flow. The public route therefore turns this into a clean 503.

    ``funnel_id`` (Issue #155): the browser's anonymous session id is carried
    inside ``checkout_data.custom`` so Lemon Squeezy echoes it back in the
    webhook's ``meta.custom_data`` — the ``paid`` funnel event can then be
    attributed to the same funnel that saw the paywall / started checkout.
    """
    from services.safety_policy import can_process_real_payment

    if not can_process_real_payment():
        return None
    if not payments_configured(plan):
        return None
    api_key = os.environ.get("LEMON_SQUEEZY_API_KEY") or ""
    store_id = os.environ.get("LEMON_SQUEEZY_STORE_ID") or ""
    # Tier-aware: PREMIUM plan uses its own pinned variant (Issue #182).
    plan = plan if plan in _PLAN_MONTHS else "pro"
    variant_id = (
        os.environ.get("LEMON_SQUEEZY_PREMIUM_VARIANT_ID")
        if plan == "premium"
        else os.environ.get("LEMON_SQUEEZY_VARIANT_ID")
    ) or ""
    custom = {"plan": plan}
    if funnel_id:
        custom["funnel_id"] = str(funnel_id)[:64]
    payload = {
        "data": {
            "type": "checkouts",
            "attributes": {
                "checkout_data": {
                    "email": email or None,
                    "custom": custom,
                },
                "product_options": {
                    "enabled_variants": [int(variant_id)],
                },
            },
            "relationships": {
                "store": {"data": {"type": "stores", "id": store_id}},
                "variant": {"data": {"type": "variants", "id": variant_id}},
            },
        }
    }
    try:
        r = requests.post(
            f"{_API_BASE}/checkouts",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/vnd.api+json",
                "Content-Type": "application/vnd.api+json",
            },
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        return ((data.get("data") or {}).get("attributes") or {}).get("url")
    except (requests.RequestException, ValueError, AttributeError):
        log.warning("checkout creation failed", exc_info=True)
        return None


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    """Verify Lemon Squeezy's x-signature (HMAC-SHA256 hex of raw body)."""
    secret = os.environ.get("LEMON_SQUEEZY_WEBHOOK_SECRET") or ""
    if not (secret and signature):
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


# ── Idempotency ledger (Issue #114) ────────────────────────────────────
# `processed_webhooks(order_id UNIQUE)` — guarantees a Lemon Squeezy order
# is fulfilled AT MOST ONCE, even under: (a) LS retries after our 5xx/timeout,
# (b) a captured-and-replayed request, (c) two concurrent deliveries racing.


def _ensure_processed_webhooks_table() -> None:
    """Create processed_webhooks if missing (self-healing, like pro_licenses)."""
    conn = get_db()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_webhooks (
                order_id     TEXT PRIMARY KEY,
                event        TEXT NOT NULL,
                license_key  TEXT NOT NULL DEFAULT '',
                processed_ts INTEGER NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _claim_order(order_id: str, event: str) -> Tuple[bool, str]:
    """Atomically claim an order for fulfillment.

    Returns (claimed, existing_key):
      - claimed=True  → THIS call owns the order; issue the key, then call
                        _complete_order() to persist it.
      - claimed=False → the order was already claimed. existing_key holds the
                        issued key (replay of a completed order) or "" when
                        another delivery is still in flight (race).

    The INSERT OR IGNORE + rowcount is the atomic claim: exactly one of N
    concurrent deliveries gets rowcount==1; the rest see the committed row.
    """
    _ensure_processed_webhooks_table()
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO processed_webhooks"
            " (order_id, event, license_key, processed_ts) VALUES (?, ?, '', ?)",
            (order_id, event, int(time.time())),
        )
        conn.commit()
        if cur.rowcount == 1:
            return True, ""
        row = conn.execute(
            "SELECT license_key FROM processed_webhooks WHERE order_id = ?",
            (order_id,),
        ).fetchone()
        return False, (row["license_key"] if row else "")
    finally:
        conn.close()


def _complete_order(order_id: str, key: str) -> None:
    """Persist the issued key after a successful fulfillment."""
    conn = get_db()
    try:
        conn.execute(
            "UPDATE processed_webhooks SET license_key = ?, processed_ts = ?"
            " WHERE order_id = ?",
            (key, int(time.time()), order_id),
        )
        conn.commit()
    finally:
        conn.close()


def _release_claim(order_id: str) -> None:
    """Delete a claim row so a retry can re-claim the order.

    Called ONLY on fulfillment failure (e.g. issue_license raised). Without
    this, a claimed-but-unfulfilled order would return None on every retry
    forever — the buyer paid but never receives a key.
    """
    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM processed_webhooks WHERE order_id = ?",
            (order_id,),
        )
        conn.commit()
    finally:
        conn.close()


# ── Subscription lifecycle (Issue #157 — 18-C) ────────────────────────
# LS fires subscription_created (the cohort's first purchase) and
# subscription_updated (fires on any change — card, status, or a RENEWAL,
# which moves renews_at forward). We record the opaque subscription id +
# timestamps only (NO PII) so conversion.cohort_ltv_report() can compute
# real LTV per cohort with actual renewals.


def _record_subscription_lifecycle(event_name: str, payload: dict) -> None:
    """Record subscription lifecycle events for real cohort LTV (Issue #157).

    subscription_created → the cohort's first purchase. subscription_updated
    is recorded as a renewal when renews_at is present; the recorder dedups
    per (subscription_id, renews_at), so unrelated updates (card change,
    status blip) never double-count a period. Best-effort — never raises.
    """
    try:
        from services.conversion import record_subscription_event

        data = payload.get("data") or {}
        attrs = data.get("attributes") or {}
        sub_id = str(data.get("id") or "").strip()
        if not sub_id:
            return
        renews_at = str(attrs.get("renews_at") or "").strip()
        created_at = str(attrs.get("created_at") or "").strip()
        event = (
            "subscription_created"
            if event_name == "subscription_created"
            else "renewal"
        )
        if event == "renewal" and not renews_at:
            # Paused/cancelled updates carry no next billing period — not a
            # renewal (the current period was already recorded).
            return
        record_subscription_event(
            subscription_id=sub_id,
            event=event,
            ts=int(time.time()),
            renews_at=renews_at,
            created_at=created_at,
        )
    except Exception:
        log.warning("[webhook] subscription lifecycle record failed", exc_info=True)


# ── PII redaction (Issue #116) ────────────────────────────────────────
# Buyer emails must NEVER reach the log sink in plain text. mask_email keeps
# the domain + local-prefix for fast triage; email_sha matches the funnel's
# email_hash so webhook logs correlate 1:1. Shared with licensing.py via
# helpers (single source of truth).


def handle_webhook(payload: dict) -> Optional[str]:
    """Fulfill an order_created webhook → issue a PRO license key.

    IDEMPOTENT (Issue #114): each Lemon Squeezy ``order id`` is fulfilled at
    most once. A replay of the same payload returns the ALREADY-ISSUED key
    (no second license, no duplicate ``paid`` event). Concurrent deliveries
    of the same order resolve via an atomic claim; only one issues.

    Known limitation (accepted): in the narrow race where the claimer fails
    AFTER a concurrent delivery already read the in-flight (empty) key and
    returned None (→ 200 handled:false), Lemon Squeezy won't retry and the
    row is released — the order then needs manual re-delivery from LS. The
    window is tiny (claimer must fail during issue_license after the other
    delivery's read) and the consequences match the "no-op" criterion.

    Returns the issued key, or None when the event is unhandled/unknown.

    NOTE on delivery: the 200 response (with the key) goes back to Lemon
    Squeezy's servers, NOT the buyer. The buyer receives their key via the
    operator's Lemon Squeezy license-key product (LS emails it natively on
    purchase). This handler's real job is keeping the gate in sync so the
    issued key is honored immediately by X-License-Key.
    """
    from services.safety_policy import can_process_real_payment

    if not can_process_real_payment():
        return None

    meta = payload.get("meta") or {}
    event_name = meta.get("event_name") or ""
    # Issue #157 (18-C): subscription lifecycle → real cohort LTV. These are
    # acknowledged (200) but never issue a license — only order_created does.
    if event_name in ("subscription_created", "subscription_updated"):
        _record_subscription_lifecycle(event_name, payload)
        return None
    if event_name != "order_created":
        return None
    data = payload.get("data") or {}
    attrs = data.get("attributes") or {}
    order_id = str(data.get("id") or "").strip()

    if not order_id:
        log.warning("webhook without order id — rejected")
        _audit(
            "payment.webhook_rejected",
            details={"provider": "lemon_squeezy", "reason": "missing_order_id"},
        )
        return None

    first_item = attrs.get("first_order_item") or {}
    variant_id = str(first_item.get("variant_id") or "")
    plan_data = _variant_months(variant_id)
    configured_store = str(os.environ.get("LEMON_SQUEEZY_STORE_ID") or "").strip()
    payload_store = str(attrs.get("store_id") or "").strip()
    if not plan_data or not configured_store or payload_store != configured_store:
        reason = "unknown_variant" if not plan_data else "store_mismatch"
        log.warning("webhook rejected: order=%s reason=%s", order_id[:16], reason)
        _audit(
            "payment.webhook_rejected",
            target=order_id,
            details={"provider": "lemon_squeezy", "reason": reason},
        )
        return None
    plan, months = plan_data
    claimed, existing_key = _claim_order(order_id, "order_created")
    if not claimed:
        _audit(
            "payment.webhook_duplicate",
            target=order_id,
            details={
                "provider": "lemon_squeezy",
                "status": "confirmed" if existing_key else "processing",
            },
        )
        if existing_key:
            log.info("webhook replay: order=%s already fulfilled", order_id[:16])
            return existing_key
        log.info("webhook in-flight: order=%s already being fulfilled", order_id[:16])
        return None

    email = (attrs.get("user_email") or "").strip()
    try:
        key = licensing.issue_license(
            plan=plan,
            # Email is needed transiently for provider attribution only; the
            # access-control DB does not need payment PII.
            email="",
            source="lemon_squeezy",
            months=months,
        )
    except Exception:
        # Release the claim so a Lemon Squeezy retry re-claims cleanly and
        # fulfills the order. Without this, the claimed-but-empty row would
        # return None on every retry forever → buyer never gets a key.
        if order_id:
            _release_claim(order_id)
        raise  # → 500 → LS retry with a clean slate
    # _complete_order is deliberately OUTSIDE the try/except: releasing the
    # claim after a key was emitted would make the retry issue a SECOND
    # license (violating "never 2 keys for 1 purchase"). If this UPDATE ever
    # fails, the row strands with key='' (retries return None, LS stops) —
    # benign: the license already exists in pro_licenses and LS emails the
    # key natively. Do NOT move this inside the try.
    if order_id:
        _complete_order(order_id, key)
    _audit(
        "payment.confirmed",
        target=order_id,
        details={"provider": "lemon_squeezy", "plan": plan},
    )
    # CFO: a PAID conversion — the funnel's money stage. Email hashed only.
    # Deduped implicitly: this block only runs for the delivery that CLAIMED
    # the order (replays return early above).
    # Issue #155: funnel_id attribution — LS echoes checkout_data.custom in
    # meta.custom_data, so the paid event lands in the same browser funnel
    # that saw the paywall and started the checkout.
    try:
        from services.conversion import track_event

        custom_data = meta.get("custom_data") or {}
        if not isinstance(custom_data, dict):
            custom_data = {}
        funnel_id = str(custom_data.get("funnel_id") or "")[:64]
        _paid_meta = {
            "order": str(data.get("id") or "")[:16],
            "plan": plan,
            "source": "lemon_squeezy",
        }
        if funnel_id:
            # Only attribute when a browser session id actually came back —
            # old checkouts keep the paid event clean (no empty field).
            _paid_meta["funnel_id"] = funnel_id
        track_event("paid", email=email, meta=_paid_meta)
    except Exception:
        pass
    # PII-safe fulfillment log (Issue #116): masked email + hash for
    # correlation with the funnel's email_hash — never the raw address.
    log.info(
        "webhook fulfilled: order=%s plan=%s email=%s email_sha=%s",
        data.get("id"),
        plan,
        mask_email(email),
        email_sha(email),
    )
    return key
