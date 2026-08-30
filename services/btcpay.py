"""
CYPHER65 // Payments (P4 — BTCPay Server adapter, Issue #248)
=============================================================
Bitcoin payment fulfillment for the PRO/PREMIUM license gate. BTCPay settles
to the wallet configured in its store; the optional fixed address is operator
metadata and is never substituted for a per-invoice payment target.

Provider: BTCPay Server Greenfield API — self-custody (funds go straight to
the operator's own wallet), 0% platform fee, no KYC (aligned with the
Bitcoin-native audience). Supports on-chain (BIP-21) AND Lightning (BOLT-11)
payment rails; Lightning settles instantly, on-chain after 1 confirmation.

Design — OFF BY DEFAULT (same ethos as payments.py / Lemon Squeezy):
  URL + API key + store id + webhook secret are all required, as is the
  explicit post-reconciliation release gate
  ``BTCPAY_RECONCILIATION_VERIFIED=1``. Any missing value keeps
  ``btcpay_configured()`` false, checkout at 503, and the public tab hidden.
  The existing Lemon Squeezy (card) path is untouched.

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
node adapter (LN_INVOICE_ENDPOINT) — the frontend calls
window.webln.sendPayment() and records the preimage through the EXISTING
donations ledger path.

Payment address metadata (P4-3): PAYMENT_BTC_ADDRESS (default "")
  — NEVER the data-wallet BTC_ADDRESS (services/polling.py uses that for
  Parasite API data). It does not settle BTCPay or WebLN invoices.

Env vars:
  BTCPAY_URL             — e.g. https://btcpay.example.com (Greenfield API root)
  BTCPAY_API_KEY         — Greenfield API key (store + invoice scope)
  BTCPAY_STORE_ID        — store id
  BTCPAY_WEBHOOK_SECRET  — shared secret for the x-btcpay-sig HMAC-SHA256
  BTCPAY_RECONCILIATION_VERIFIED — set to 1 only after the real E2E runbook
  PAYMENT_BTC_ADDRESS    — operator revenue/reference address (not invoice target)
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


def btcpay_credentials_configured() -> bool:
    """True when the four server-side BTCPay credentials are present."""
    return bool(
        os.environ.get("BTCPAY_URL")
        and os.environ.get("BTCPAY_API_KEY")
        and os.environ.get("BTCPAY_STORE_ID")
        and os.environ.get("BTCPAY_WEBHOOK_SECRET")
    )


def btcpay_reconciliation_verified() -> bool:
    """Explicit operator release gate set only after real settlement tests."""
    value = str(os.environ.get("BTCPAY_RECONCILIATION_VERIFIED") or "").strip()
    return value.lower() in {"1", "true", "yes"}


def btcpay_configured() -> bool:
    """True only when checkout, fulfillment and reconciliation are ready.

    Creating invoices without a webhook secret exposes a payment method that
    can accept funds but can never issue the purchased license. Keep the gate
    off until the settlement HMAC and idempotent license delivery have been
    verified end-to-end in the target environment.
    """
    return btcpay_credentials_configured() and btcpay_reconciliation_verified()


def payment_address() -> str:
    """Operator reference address (P4-3), never the monitored BTC_ADDRESS."""
    return (os.environ.get("PAYMENT_BTC_ADDRESS") or "").strip()


def _plan_months(plan: str) -> int:
    return _PLAN_MONTHS.get(plan, _PLAN_MONTHS["pro"])


def payment_state(provider_status: str, fulfilled: bool = False) -> str:
    """Normalize provider-specific invoice states for API/UI consumers."""
    status = str(provider_status or "").strip().lower()
    if status == "settled":
        return "confirmed" if fulfilled else "pending"
    if status == "expired":
        return "expired"
    if status == "invalid":
        return "invalid"
    return "pending"


def _audit(action: str, target: str = "", details: Optional[dict] = None) -> None:
    """Persist a payment audit event without keys, preimages or buyer data."""
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
    from services.safety_policy import can_process_real_payment

    if not can_process_real_payment():
        return None
    # Kept in the signature for caller compatibility; CYPHER65 does not need
    # buyer PII to create or fulfill an invoice, so it is never transmitted.
    del buyer_email
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
                created_ts INTEGER NOT NULL,
                status_token_hash TEXT NOT NULL DEFAULT ''
            )
            """
        )
        cols = {
            row[1] for row in conn.execute("PRAGMA table_info(btcpay_invoice_plans)")
        }
        if "status_token_hash" not in cols:
            conn.execute(
                "ALTER TABLE btcpay_invoice_plans "
                "ADD COLUMN status_token_hash TEXT NOT NULL DEFAULT ''"
            )
        conn.commit()
    finally:
        conn.close()


def record_invoice_plan(
    invoice_id: str, plan: str = "pro", status_token: str = ""
) -> bool:
    """Persist invoice_id → plan at checkout time (best-effort, never raises)."""
    if not invoice_id:
        return False
    plan = plan if plan in _PLAN_MONTHS else "pro"
    try:
        _ensure_invoice_plan_table()
        conn = get_db()
        try:
            token_hash = (
                hashlib.sha256(status_token.encode("utf-8")).hexdigest()
                if status_token
                else ""
            )
            cur = conn.execute(
                "INSERT OR IGNORE INTO btcpay_invoice_plans"
                " (invoice_id, plan, created_ts, status_token_hash) VALUES (?, ?, ?, ?)",
                (invoice_id, plan, int(time.time()), token_hash),
            )
            conn.commit()
            return cur.rowcount == 1
        finally:
            conn.close()
    except Exception:
        log.warning("record_invoice_plan failed: %s", invoice_id[:16])
        return False


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


def invoice_hash_known(payment_hash: str) -> bool:
    """True when a payment_hash was created by OUR checkout (plan ledger).

    The WebLN confirm route only fulfills hashes WE issued — an attacker can
    trivially compute sha256(preimage) for any self-chosen preimage, so a
    hash that was never recorded at checkout must be rejected (never falls
    back to the defensive PRO plan)."""
    if not payment_hash:
        return False
    try:
        _ensure_invoice_plan_table()
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT 1 FROM btcpay_invoice_plans WHERE invoice_id = ?",
                (payment_hash,),
            ).fetchone()
        finally:
            conn.close()
    except Exception:
        return False
    return row is not None


def verify_invoice_status_token(invoice_id: str, status_token: str) -> bool:
    """Authorize polling without treating a provider invoice id as a secret."""
    if not (invoice_id and status_token):
        return False
    try:
        _ensure_invoice_plan_table()
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT status_token_hash FROM btcpay_invoice_plans WHERE invoice_id = ?",
                (invoice_id,),
            ).fetchone()
        finally:
            conn.close()
    except Exception:
        return False
    expected = str(row["status_token_hash"] or "") if row else ""
    actual = hashlib.sha256(status_token.encode("utf-8")).hexdigest()
    return bool(expected) and hmac.compare_digest(expected, actual)


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


def fulfilled_license_key(invoice_id: str) -> str:
    """The license key already issued for a fulfilled invoice (or "").

    Local ledger read — no network. Lets the frontend status poll flip to
    "PRO ativado ✓" with the key applied the moment the invoice Settles,
    without waiting for the webhook round-trip (Issue #249)."""
    if not invoice_id:
        return ""
    try:
        _ensure_processed_invoices_table()
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT license_key FROM processed_invoices WHERE invoice_id = ?",
                (invoice_id,),
            ).fetchone()
        finally:
            conn.close()
    except Exception:
        return ""
    return str(row["license_key"] or "") if row else ""


# ── Fulfillment ──────────────────────────────────────────────────────


def handle_invoice_webhook(payload: dict) -> Optional[str]:
    """Fulfill a BTCPay invoice webhook → issue a PRO/PREMIUM license key.

    Only ``Settled`` (paid + confirmed) fulfills. ``Processing`` (paid,
    awaiting confirmation) and ``Expired``/``Invalid`` are acknowledged
    no-ops — the frontend polls get_invoice() for the Settled transition.

    IDEMPOTENT: each invoice is fulfilled at most once; a replay returns the
    already-issued key. Returns the issued key, or None when unhandled.
    """
    from services.safety_policy import can_process_real_payment

    if not can_process_real_payment():
        return None
    # BTCPay webhook shape: {"invoiceId": "...", "type": "InvoiceSettled",
    #                        "deliveryId": "...", "webhookId": "..."}
    invoice_id = str(payload.get("invoiceId") or payload.get("id") or "").strip()
    event_type = str(payload.get("type") or "").strip()
    if not invoice_id:
        log.warning("btcpay webhook without invoice id — no-op (event=%s)", event_type)
        _audit(
            "payment.webhook_rejected",
            details={"provider": "btcpay", "reason": "missing_invoice_id"},
        )
        return None
    # Only Settled (final, 1+ confirmation) fulfills.
    if event_type not in ("InvoiceSettled", "invoice_settled"):
        return None

    # A valid store signature authenticates BTCPay, not the commercial intent
    # of every invoice in that store. Only invoices created by this checkout
    # and recorded locally may issue CYPHER65 licenses.
    if not invoice_hash_known(invoice_id):
        log.warning("btcpay webhook for unknown invoice rejected: %s", invoice_id[:16])
        _audit(
            "payment.webhook_rejected",
            target=invoice_id,
            details={"provider": "btcpay", "reason": "unknown_invoice"},
        )
        return None

    claimed, existing_key = _claim_invoice(invoice_id)
    if not claimed:
        _audit(
            "payment.webhook_duplicate",
            target=invoice_id,
            details={
                "provider": "btcpay",
                "status": "confirmed" if existing_key else "processing",
            },
        )
        if existing_key:
            log.info("btcpay replay: invoice=%s already fulfilled", invoice_id[:16])
            return existing_key
        log.info(
            "btcpay in-flight: invoice=%s already claimed — no-op", invoice_id[:16]
        )
        return None

    # Plan resolution: from the LOCAL ledger written at checkout time —
    # zero network in the webhook path (a BTCPay outage during delivery must
    # never silently downgrade PREMIUM→PRO). Unknown invoices were rejected
    # above and can never reach this plan resolution.
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
    _audit(
        "payment.confirmed",
        target=invoice_id,
        details={"provider": "btcpay", "plan": plan},
    )
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


def fulfill_webln_payment(payment_hash: str, preimage: str) -> Optional[str]:
    """Verify a WebLN payment proof and issue the license AT MOST ONCE.

    The BOLT-11 payment_hash is the SHA-256 of the 32-byte preimage — only
    the payer (or the payee after settlement) ever holds the preimage, so a
    matching preimage is cryptographic proof of payment. The plan comes from
    the LOCAL ledger written at checkout (payment_hash → plan), never from
    network calls.

    Returns:
      - license key str → fulfilled now (or replay of an already-fulfilled
        payment returns the SAME key — idempotent, mirrors BTCPay).
      - ""  → verified payment whose fulfillment is in-flight (another
        delivery claimed it) — frontend keeps showing "ativando…".
      - None → proof rejected: unknown payment_hash or preimage mismatch.
    """
    from services.safety_policy import can_process_real_payment

    if not can_process_real_payment():
        return None
    if not (payment_hash and preimage):
        return None
    # SHA-256 proof: sha256(preimage) == payment_hash (BOLT-11 spec).
    try:
        digest = hashlib.sha256(bytes.fromhex(preimage)).hexdigest().lower()
    except (TypeError, ValueError):
        # Non-hex preimage (some wallets return raw bytes/base64) — hash the
        # utf-8 text as a lenient fallback; the ledger hash decides.
        digest = hashlib.sha256(preimage.encode("utf-8", "ignore")).hexdigest().lower()
    if digest != str(payment_hash).strip().lower():
        _audit(
            "payment.proof_rejected",
            target=payment_hash,
            details={"provider": "webln", "reason": "preimage_mismatch"},
        )
        return None
    # Only hashes WE issued at checkout may fulfill — never fall back to the
    # defensive PRO plan for a hash an attacker generated themselves.
    if not invoice_hash_known(payment_hash):
        _audit(
            "payment.proof_rejected",
            target=payment_hash,
            details={"provider": "webln", "reason": "unknown_invoice"},
        )
        return None
    plan = _invoice_plan(payment_hash)
    claimed, existing_key = _claim_invoice(payment_hash)
    if not claimed:
        # Replay of an already-fulfilled payment → same key; in-flight → "".
        _audit(
            "payment.webhook_duplicate",
            target=payment_hash,
            details={
                "provider": "webln",
                "status": "confirmed" if existing_key else "processing",
            },
        )
        return existing_key
    try:
        key = licensing.issue_license(
            plan=plan,
            email="",
            source="webln",
            months=_plan_months(plan),
        )
    except Exception:
        _release_claim(payment_hash)
        raise
    _complete_invoice(payment_hash, key)
    _audit(
        "payment.confirmed",
        target=payment_hash,
        details={"provider": "webln", "plan": plan},
    )
    try:
        from services.conversion import track_event

        track_event(
            "paid",
            email="",
            meta={
                "method": "lightning",
                "provider": "webln",
                "invoice": str(payment_hash)[:16],
                "plan": plan,
            },
        )
    except Exception:
        pass
    log.info(
        "webln fulfilled: hash=%s plan=%s key_sha=%s",
        str(payment_hash)[:16],
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
    """Legacy adapter capability; never expose it as a commercial checkout.

    The beta release policy permits payments only through a reconciled BTCPay
    flow. Keeping invoice creation helpers available preserves internal API
    compatibility without advertising an unvalidated purchase path.
    """
    return False


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
        payment_hash = str(data.get("payment_hash") or "").strip().lower()
        if not invoice or len(payment_hash) != 64:
            return None
        try:
            bytes.fromhex(payment_hash)
        except ValueError:
            return None
        return {
            "bolt11": invoice,
            "payment_hash": payment_hash,
            "amount_sat": amount_sat,
            "plan": plan,
        }
    except (requests.RequestException, ValueError, AttributeError):
        log.warning("webln invoice creation failed", exc_info=True)
        return None
