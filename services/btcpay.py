"""
CYPHER65 // Payments (P4 — BTCPay Server adapter, Issue #248)
=============================================================
Bitcoin payment fulfillment for the PRO/PREMIUM license gate, paid
exclusively in BTC to the operator's fixed address.

Provider: BTCPay Server Greenfield API — self-custody (funds go straight to
the operator's own wallet), 0% platform fee, no KYC (aligned with the
Bitcoin-native audience). Supports on-chain (BIP-21) AND Lightning (BOLT-11)
payment rails; Lightning settles instantly, on-chain after 1 confirmation.

Design — OFF BY DEFAULT (same ethos as payments.py / Lemon Squeezy):
  No ``BTCPAY_URL`` + ``BTCPAY_API_KEY`` → ``btcpay_configured()`` is False,
  the BTC checkout path returns 503 and the webhook returns 400. The
  existing Lemon Squeezy (card) path is untouched.

Fulfillment flow:
  Frontend "Pay with Bitcoin" → POST /api/upgrade/checkout {method:"btc"}
  → create_invoice() → BTCPay invoice (on-chain + Lightning) →
  buyer pays (QR BIP-21 / WebLN) → BTCPay posts invoice webhook →
  POST /api/payments/btcpay/webhook (signature verified) →
  handle_invoice_webhook() → licensing.issue_license() → the SAME
  X-License-Key gate the Lemon Squeezy path uses honors the issued key.

Idempotency: BTCPay invoices are fulfilled AT MOST ONCE — the invoice id is
the dedup key (mirrors the LS processed_webhooks ledger). A webhook replay
returns the already-issued key, never a second license.

Fallback WebLN (Issue #248): when the server can't reach a BTCPay instance,
``create_webln_invoice()`` generates a BOLT-11 via the operator's Lightning
node env (LN_ADDRESS) — the frontend calls window.webln.sendPayment() and
records the preimage through the EXISTING donations ledger path.

Payment address (fixed, P4-3): PAYMENT_BTC_ADDRESS (default "")
  — NEVER the data-wallet BTC_ADDRESS (services/polling.py uses that for
  Parasite API data; the two roles are strictly separated).

Env vars:
  BTCPAY_URL             — e.g. https://btcpay.example.com (Greenfield API root)
  BTCPAY_API_KEY         — Greenfield API key (store + invoice scope)
  BTCPAY_STORE_ID        — store id
  BTCPAY_WEBHOOK_SECRET  — shared secret for the x-btcpay-sig HMAC-SHA256
  PAYMENT_BTC_ADDRESS    — the operator's fixed BTC address (BIP-21 target)
"""

import hashlib
import hmac
import logging
import os
import time
from typing import Optional, Tuple

import requests

from helpers import mask_email, email_sha
from services import licensing
from services.db import get_db

log = logging.getLogger("cypher65.btcpay")

_API_TIMEOUT = 15

# Plan → months for issued licenses (mirrors payments._PLAN_MONTHS).
_PLAN_MONTHS = {"pro": 12, "premium": 12}

# BTC/USD fallback when no live quote is available (only used to derive a
# sanity display value; the INVOICE amount is always in sats).
_DEFAULT_BTC_USD = 75_000.0


def btcpay_configured() -> bool:
    """True when the BTCPay instance env is present (checkout/webhook live)."""
    return bool(
        os.environ.get("BTCPAY_URL")
        and os.environ.get("BTCPAY_API_KEY")
        and os.environ.get("BTCPAY_STORE_ID")
    )


def payment_address() -> str:
    """The fixed payment address (P4-3): PAYMENT_BTC_ADDRESS, never BTC_ADDRESS."""
    return (os.environ.get("PAYMENT_BTC_ADDRESS") or "").strip()


def _plan_months(plan: str) -> int:
    return _PLAN_MONTHS.get(plan, _PLAN_MONTHS["pro"])


# ── Price helpers ────────────────────────────────────────────────────
# The dashboard already tracks a live BTC/USD quote (merge_btc_quotes,
# cached 5min). The invoice amount is ALWAYS expressed in sats; USD is only
# a reference label for orientation ("≈ $9/mo"), never a charge.


def _usd_to_sats(usd_month: float) -> int:
    btc_usd = _live_btc_usd() or _DEFAULT_BTC_USD
    btc = usd_month / btc_usd
    return max(1, int(btc * 100_000_000))


def _live_btc_usd() -> Optional[float]:
    """Best-effort live BTC/USD from the in-memory snapshot quote (never
    raises). Source: services.state.latest_snapshot["btc_price"]["usd"] —
    the same quote the dashboard topbar renders (merged CoinGecko/Binance)."""
    try:
        from services import state as _state

        cached = (_state.latest_snapshot or {}).get("btc_price") or {}
        usd = cached.get("usd")
        return float(usd) if usd else None
    except Exception:
        return None


def plan_amount_sats(plan: str, usd_month: Optional[float] = None) -> int:
    """Sats for a plan's monthly price (USD reference → live BTC quote)."""
    price_usd = usd_month or (29 if plan == "premium" else 9)
    return _usd_to_sats(price_usd)


# ── BTCPay Greenfield API ────────────────────────────────────────────


def _api_headers(api_key: str) -> dict:
    return {
        "Authorization": f"token {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def create_invoice(
    plan: str = "pro",
    amount_sat: Optional[int] = None,
    funnel_id: str = "",
    buyer_email: str = "",
) -> Optional[dict]:
    """Create a BTCPay invoice; return its dict (id, checkout url, etc.) or
    None on any network/API error (route turns None into a clean 503).

    The invoice amount is in sats (BTCPay stores amounts in satoshi when
    ``amount`` is passed without currency = "BTC" and we use sats*1e8
    precision — we pass exact sats via currency BTC and amount in BTC).
    """
    api_key = os.environ.get("BTCPAY_API_KEY") or ""
    store_id = os.environ.get("BTCPAY_STORE_ID") or ""
    base = (os.environ.get("BTCPAY_URL") or "").rstrip("/")
    if not (api_key and store_id and base):
        return None
    plan = plan if plan in _PLAN_MONTHS else "pro"
    amount_sat = amount_sat or plan_amount_sats(plan)
    custom = {"plan": plan}
    if funnel_id:
        custom["funnel_id"] = str(funnel_id)[:64]
    metadata = {
        "plan": plan,
        "months": _plan_months(plan),
    }
    if buyer_email:
        metadata["buyerEmail"] = buyer_email[:200]
    payload = {
        "amount": amount_sat / 100_000_000.0,  # BTC (BTCPay native unit)
        "currency": "BTC",
        "checkout": {
            "defaultPaymentMethod": "BTCOnChain",
            "expirationMinutes": 15,
            "moneroPercent": 0,
        },
        "metadata": metadata,
        "additionalData": {"posData": custom},
        "notificationEmail": "",
    }
    try:
        r = requests.post(
            f"{base}/api/v1/stores/{store_id}/invoices",
            json=payload,
            headers=_api_headers(api_key),
            timeout=_API_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        return {
            "id": data.get("id"),
            "checkoutLink": data.get("checkoutLink"),
            "amount": data.get("amount"),
            "status": data.get("status"),
        }
    except (requests.RequestException, ValueError, AttributeError):
        log.warning("btcpay invoice creation failed", exc_info=True)
        return None


def get_invoice(invoice_id: str) -> Optional[dict]:
    """Fetch a BTCPay invoice (status polling for the frontend)."""
    api_key = os.environ.get("BTCPAY_API_KEY") or ""
    store_id = os.environ.get("BTCPAY_STORE_ID") or ""
    base = (os.environ.get("BTCPAY_URL") or "").rstrip("/")
    if not (api_key and store_id and base) or not invoice_id:
        return None
    try:
        r = requests.get(
            f"{base}/api/v1/stores/{store_id}/invoices/{invoice_id}",
            headers=_api_headers(api_key),
            timeout=_API_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        return {
            "id": data.get("id"),
            "status": data.get("status"),
            "amount": data.get("amount"),
            "type": data.get("type"),
        }
    except (requests.RequestException, ValueError, AttributeError):
        log.warning("btcpay invoice fetch failed: %s", invoice_id[:16])
        return None


# ── Webhook verification ─────────────────────────────────────────────
# BTCPay signs the raw request body with HMAC-SHA256 using the store's
# webhook secret, sent in the ``x-btcpay-sig`` header as
# "sha256=<hex digest>". Mirrors the Lemon Squeezy x-signature pattern.


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    secret = os.environ.get("BTCPAY_WEBHOOK_SECRET") or ""
    if not (secret and signature):
        return False
    sig = signature.strip()
    if sig.startswith("sha256="):
        sig = sig[len("sha256=") :]
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


# ── Invoice → plan ledger (no network in the webhook path) ──────────
# The plan is persisted at CHECKOUT time (record_invoice_plan) so the
# webhook resolves it from the local DB — never a live get_invoice() call
# (a BTCPay outage during delivery must not silently downgrade PREMIUM→PRO).


def _ensure_invoice_plan_table() -> None:
    conn = get_db()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS btcpay_invoice_plans (
                invoice_id TEXT PRIMARY KEY,
                plan       TEXT NOT NULL DEFAULT 'pro',
                created_ts INTEGER NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def record_invoice_plan(invoice_id: str, plan: str = "pro") -> None:
    """Persist invoice_id → plan at checkout time (best-effort, never raises)."""
    if not invoice_id:
        return
    plan = plan if plan in _PLAN_MONTHS else "pro"
    try:
        _ensure_invoice_plan_table()
        conn = get_db()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO btcpay_invoice_plans"
                " (invoice_id, plan, created_ts) VALUES (?, ?, ?)",
                (invoice_id, plan, int(time.time())),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        log.warning("record_invoice_plan failed: %s", invoice_id[:16])


def _invoice_plan(invoice_id: str) -> str:
    """Resolve the plan for an invoice from the LOCAL ledger (no network)."""
    try:
        _ensure_invoice_plan_table()
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT plan FROM btcpay_invoice_plans WHERE invoice_id = ?",
                (invoice_id,),
            ).fetchone()
        finally:
            conn.close()
    except Exception:
        return "pro"
    if not row:
        return "pro"
    plan = str(row["plan"] or "pro").strip().lower()
    return plan if plan in _PLAN_MONTHS else "pro"


# ── Idempotency ledger ───────────────────────────────────────────────
# processed_invoices(invoice_id UNIQUE) — a BTCPay invoice is fulfilled AT
# MOST ONCE, even under webhook retries / concurrent deliveries / replays.


def _ensure_processed_invoices_table() -> None:
    conn = get_db()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_invoices (
                invoice_id   TEXT PRIMARY KEY,
                event        TEXT NOT NULL DEFAULT 'invoice_settled',
                license_key  TEXT NOT NULL DEFAULT '',
                processed_ts INTEGER NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _claim_invoice(invoice_id: str) -> Tuple[bool, str]:
    """Atomically claim an invoice for fulfillment (INSERT OR IGNORE claim).

    Returns (claimed, existing_key):
      - claimed=True   → this call owns the invoice; issue the key.
      - claimed=False  → already claimed. existing_key holds the issued key
                         (replay) or "" when another delivery is in flight.
    """
    _ensure_processed_invoices_table()
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO processed_invoices"
            " (invoice_id, event, license_key, processed_ts) VALUES (?, ?, '', ?)",
            (invoice_id, "invoice_settled", int(time.time())),
        )
        conn.commit()
        if cur.rowcount == 1:
            return True, ""
        row = conn.execute(
            "SELECT license_key FROM processed_invoices WHERE invoice_id = ?",
            (invoice_id,),
        ).fetchone()
        return False, (row["license_key"] if row else "")
    finally:
        conn.close()


def _complete_invoice(invoice_id: str, key: str) -> None:
    conn = get_db()
    try:
        conn.execute(
            "UPDATE processed_invoices SET license_key = ?, processed_ts = ?"
            " WHERE invoice_id = ?",
            (key, int(time.time()), invoice_id),
        )
        conn.commit()
    finally:
        conn.close()


def _release_claim(invoice_id: str) -> None:
    """Delete a claim so a retry can re-claim after a fulfillment failure."""
    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM processed_invoices WHERE invoice_id = ?",
            (invoice_id,),
        )
        conn.commit()
    finally:
        conn.close()


# ── Fulfillment ──────────────────────────────────────────────────────


def handle_invoice_webhook(payload: dict) -> Optional[str]:
    """Fulfill a BTCPay invoice webhook → issue a PRO/PREMIUM license key.

    Only ``Settled`` (paid + confirmed) fulfills. ``Processing`` (paid,
    awaiting confirmation) and ``Expired``/``Invalid`` are acknowledged
    no-ops — the frontend polls get_invoice() for the Settled transition.

    IDEMPOTENT: each invoice is fulfilled at most once; a replay returns the
    already-issued key. Returns the issued key, or None when unhandled.
    """
    # BTCPay webhook shape: {"invoiceId": "...", "type": "InvoiceSettled",
    #                        "deliveryId": "...", "webhookId": "..."}
    invoice_id = str(payload.get("invoiceId") or payload.get("id") or "").strip()
    event_type = str(payload.get("type") or "").strip()
    if not invoice_id:
        log.warning("btcpay webhook without invoice id — no-op (event=%s)", event_type)
        return None
    # Only Settled (final, 1+ confirmation) fulfills.
    if event_type not in ("InvoiceSettled", "invoice_settled"):
        return None

    claimed, existing_key = _claim_invoice(invoice_id)
    if not claimed:
        if existing_key:
            log.info("btcpay replay: invoice=%s already fulfilled", invoice_id[:16])
            return existing_key
        log.info(
            "btcpay in-flight: invoice=%s already claimed — no-op", invoice_id[:16]
        )
        return None

    # Plan resolution: from the LOCAL ledger written at checkout time —
    # zero network in the webhook path (a BTCPay outage during delivery must
    # never silently downgrade PREMIUM→PRO). Unknown → PRO (defensive).
    plan = _invoice_plan(invoice_id)
    months = _plan_months(plan)
    try:
        key = licensing.issue_license(
            plan=plan,
            email="",
            source="btcpay",
            months=months,
        )
    except Exception:
        if invoice_id:
            _release_claim(invoice_id)
        raise
    if invoice_id:
        _complete_invoice(invoice_id, key)
    # CFO: a PAID conversion attributed to the BTC channel.
    try:
        from services.conversion import track_event

        track_event(
            "paid",
            email="",
            meta={
                "method": "btc",
                "provider": "btcpay",
                "invoice": invoice_id[:16],
                "plan": plan,
            },
        )
    except Exception:
        pass
    log.info(
        "btcpay fulfilled: invoice=%s plan=%s key_sha=%s",
        invoice_id[:16],
        plan,
        email_sha(key),
    )
    return key


# ── Fallback WebLN (no BTCPay instance) ──────────────────────────────
# Issue #248: when BTCPay isn't configured, a Lightning invoice can still be
# generated from an operator Lightning node (LN_ADDRESS / LN_INVOICE_ENDPOINT).
# The frontend calls window.webln.sendPayment() and the preimage is recorded
# via the EXISTING donations ledger (source='webln'), which already dedups.


def webln_invoice_available() -> bool:
    return bool(os.environ.get("LN_ADDRESS") or os.environ.get("LN_INVOICE_ENDPOINT"))


def create_webln_invoice(
    plan: str = "pro", amount_sat: Optional[int] = None
) -> Optional[dict]:
    """Create a BOLT-11 invoice for WebLN via the operator's Lightning node.

    Endpoint contract (operator-provided, e.g. a small lnbits/lncli wrapper):
      GET  /invoice?amount_sat=N&memo=CYPHER65+PRO
      →    {"invoice": "lnbc...", "payment_hash": "..."}
    Returns the dict or None when unavailable/failed (never raises).
    """
    endpoint = (os.environ.get("LN_INVOICE_ENDPOINT") or "").rstrip("/")
    if not endpoint:
        return None
    plan = plan if plan in _PLAN_MONTHS else "pro"
    amount_sat = amount_sat or plan_amount_sats(plan)
    memo = f"CYPHER65 {plan.upper()}"
    try:
        r = requests.get(
            endpoint,
            params={"amount_sat": amount_sat, "memo": memo},
            timeout=_API_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        invoice = str(data.get("invoice") or "").strip()
        if not invoice:
            return None
        return {
            "bolt11": invoice,
            "payment_hash": str(data.get("payment_hash") or "").strip(),
            "amount_sat": amount_sat,
            "plan": plan,
        }
    except (requests.RequestException, ValueError, AttributeError):
        log.warning("webln invoice creation failed", exc_info=True)
        return None
