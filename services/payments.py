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
from typing import Optional

import requests

from services import licensing

log = logging.getLogger("cypher65.payments")

_API_BASE = "https://api.lemonsqueezy.com/v1"

# Variant ids → (plan, months). Operators override the PRO variant via env.
_PLAN_MONTHS = {"pro": 12}


def payments_configured() -> bool:
    """True when an LS API key is present (checkout/webhook live)."""
    return bool(os.environ.get("LEMON_SQUEEZY_API_KEY"))


def _variant_months(variant_id: str):
    """Map a variant id to (plan, months).

    Today every variant maps to a 12-month PRO license — this is the seam
    where future multi-tier pricing (e.g. annual vs lifetime) would branch
    on the operator's LEMON_SQUEEZY_VARIANT_ID.
    """
    return "pro", 12


def create_checkout(plan: str = "pro", email: str = "") -> Optional[str]:
    """Create a Lemon Squeezy hosted checkout; return its URL or None.

    Network/API errors never raise — the route turns None into a clean 503.
    """
    api_key = os.environ.get("LEMON_SQUEEZY_API_KEY") or ""
    store_id = os.environ.get("LEMON_SQUEEZY_STORE_ID") or ""
    variant_id = os.environ.get("LEMON_SQUEEZY_VARIANT_ID") or ""
    if not (api_key and store_id and variant_id):
        return None
    payload = {
        "data": {
            "type": "checkouts",
            "attributes": {
                "checkout_data": {
                    "email": email or None,
                    "custom": {"plan": plan},
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


def handle_webhook(payload: dict) -> Optional[str]:
    """Fulfill an order_created webhook → issue a PRO license key.

    Returns the issued key, or None when the event is unhandled/unknown.

    NOTE on delivery: the 200 response (with the key) goes back to Lemon
    Squeezy's servers, NOT the buyer. The buyer receives their key via the
    operator's Lemon Squeezy license-key product (LS emails it natively on
    purchase). This handler's real job is keeping the gate in sync so the
    issued key is honored immediately by X-License-Key.
    """
    meta = payload.get("meta") or {}
    if meta.get("event_name") != "order_created":
        return None
    data = payload.get("data") or {}
    attrs = data.get("attributes") or {}
    email = (attrs.get("user_email") or "").strip()
    first_item = attrs.get("first_order_item") or {}
    variant_id = str(first_item.get("variant_id") or "")
    plan, months = _variant_months(variant_id)
    key = licensing.issue_license(
        plan=plan,
        email=email,
        source="lemon_squeezy",
        months=months,
    )
    log.info("webhook fulfilled: order=%s plan=%s email=%s", data.get("id"), plan, email or "-")
    return key
