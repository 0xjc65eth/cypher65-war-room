"""
CYPHER65 // Payments (R1 revenue — Lemon Squeezy adapter)
==========================================================
Off-by-default payment fulfillment for the PRO license gate.

Provider: Lemon Squeezy — Merchant of Record (handles global sales tax/VAT,
cards, PayPal, Apple/Google Pay) with a native license-key product model.
Chosen over Stripe for R1 because a solo operator without a US entity avoids
global tax nexus entirely (Stripe is a processor, not a MoR) and LS delivers
license keys natively at 5% + $0.50 per sale.

Design — OFF BY DEFAULT:
  No ``LEMON_SQUEEZY_API_KEY`` → ``payments_configured()`` is False, the
  checkout route returns 503, and the webhook route returns 400. The R1 gate
  stays exactly as today until the operator activates it (see licensing.py).

Fulfillment flow:
  Frontend "Buy PRO" → POST /api/upgrade/checkout → create_checkout() →
  LS hosted checkout URL (opened in a new tab) → LS posts order_created →
  POST /api/payments/webhook (x-signature HMAC-SHA256 verified) →
  handle_webhook() → licensing.issue_license() → customer activates the key
  in the upgrade modal (X-License-Key header, already wired in app.js).

Env vars:
  LEMON_SQUEEZY_API_KEY        — API key (private) — ALSO activates the R1 gate
  LEMON_SQUEEZY_WEBHOOK_SECRET — secret for x-signature verification
  LEMON_SQUEEZY_STORE_ID       — numeric store id (checkout creation)
  LEMON_SQUEEZY_VARIANT_ID     — numeric variant/price id of the PRO product
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
# Issue #182). Unknown variants stay PRO — the legacy default.
_PLAN_MONTHS = {"pro": 12, "premium": 12}


def payments_configured() -> bool:
    """True when an LS API key is present (checkout/webhook live)."""
    return bool(os.environ.get("LEMON_SQUEEZY_API_KEY"))


def _variant_months(variant_id: str):
    """Map a variant id to (plan, months).

    The operator pins the PREMIUM variant via LEMON_SQUEEZY_PREMIUM_VARIANT_ID;
    everything else maps to the PRO variant (legacy default).
    """
    vid = str(variant_id or "")
    premium_variant = (os.environ.get("LEMON_SQUEEZY_PREMIUM_VARIANT_ID") or "").strip()
    if premium_variant and vid == premium_variant:
        return "premium", _PLAN_MONTHS["premium"]
    return "pro", _PLAN_MONTHS["pro"]


def create_checkout(
    plan: str = "pro", email: str = "", funnel_id: str = ""
) -> Optional[str]:
    """Create a Lemon Squeezy hosted checkout; return its URL or None.

    Network/API errors never raise — the route turns None into a clean 503.

    ``funnel_id`` (Issue #155): the browser's anonymous session id is carried
    inside ``checkout_data.custom`` so Lemon Squeezy echoes it back in the
    webhook's ``meta.custom_data`` — the ``paid`` funnel event can then be
    attributed to the same funnel that saw the paywall / started checkout.
    """
    api_key = os.environ.get("LEMON_SQUEEZY_API_KEY") or ""
    store_id = os.environ.get("LEMON_SQUEEZY_STORE_ID") or ""
    # Tier-aware: PREMIUM plan uses its own pinned variant (Issue #182).
    plan = plan if plan in _PLAN_MONTHS else "pro"
    variant_id = (
        os.environ.get("LEMON_SQUEEZY_PREMIUM_VARIANT_ID")
        if plan == "premium"
        else os.environ.get("LEMON_SQUEEZY_VARIANT_ID")
    ) or ""
    if not (api_key and store_id and variant_id):
        return None
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

    if order_id:
        claimed, existing_key = _claim_order(order_id, "order_created")
        if not claimed:
            if existing_key:
                # Replay of a completed order — return the key we already
                # issued. Never a second license, never a second "paid".
                log.info(
                    "webhook replay: order=%s already fulfilled — returning existing key",
                    order_id,
                )
                return existing_key
            # Another delivery of the same order is still in flight. Acknowledge
            # without issuing; LS will retry and then find the completed key.
            log.info(
                "webhook in-flight: order=%s already being fulfilled — no-op", order_id
            )
            return None
    else:
        # PII-safe (Issue #116): NEVER dump the raw payload — order_created
        # carries data.attributes.user_email. Log only safe identifiers.
        log.warning(
            "webhook without order id — processing without dedup: event=%s data_id=%s",
            meta.get("event_name"),
            data.get("id"),
        )

    email = (attrs.get("user_email") or "").strip()
    first_item = attrs.get("first_order_item") or {}
    variant_id = str(first_item.get("variant_id") or "")
    plan, months = _variant_months(variant_id)
    try:
        key = licensing.issue_license(
            plan=plan,
            email=email,
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
