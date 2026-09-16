"""
CYPHER65 // P4 revenue — BTCPay Server adapter (Issue #248)
===========================================================
Validates the Bitcoin payment path built on top of the existing licensing
gate:

1. Off-by-default: no BTCPAY_* env → btcpay_configured() False, checkout BTC
   returns 503, webhook returns 400.
2. Payment address (P4-3): PAYMENT_BTC_ADDRESS is read for the BIP-21 target,
   NEVER the data-wallet BTC_ADDRESS.
3. Amounts: plan → sats via live BTC quote (fallback reference price).
4. Invoice creation: BTCPay Greenfield payload shape + checkout URL.
5. Webhook: x-btcpay-sig "sha256=<hex>" HMAC-SHA256 verification
   (right/wrong/empty), InvoiceSettled → issue_license → the gate honors the
   key; Processing/Expired/Invalid are acknowledged no-ops.
6. Idempotency: same invoice delivered twice → ONE key, replay returns it.
7. WebLN fallback: LN_INVOICE_ENDPOINT produces a BOLT-11 invoice.
8. Routes: /api/upgrade/checkout {method:"btc"} (503 unconfigured / invoice
   payload when configured), /api/payments/btcpay/webhook (403 bad signature),
   /api/upgrade/status/<id> (503/404/200), /api/license-status enrichment.

HERMETIC — never touches data/war_room.sqlite (conftest redirects DB_PATH).
"""

import hashlib
import hmac
import json
import logging
import os
import queue
import re
import sqlite3
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as _app_module
from services import btcpay, licensing

app = _app_module.app

_KEY_RE = re.compile(r"^C65-[A-Z0-9]{4}(-[A-Z0-9]{4}){3}$")

FIXED_ADDR = "35gjAoadgQxrNc1Kx6QiSLx7wCCXRnRFkM"
STATUS_TOKEN = "status-token-test"


@pytest.fixture(autouse=True)
def _scrub_btcpay_env(monkeypatch):
    """Every test starts with the gate OFF and no BTCPay env vars."""
    for name in (
        "BTCPAY_URL",
        "BTCPAY_API_KEY",
        "BTCPAY_STORE_ID",
        "BTCPAY_WEBHOOK_SECRET",
        "BTCPAY_RECONCILIATION_VERIFIED",
        "PAYMENT_BTC_ADDRESS",
        "LN_INVOICE_ENDPOINT",
        "LN_ADDRESS",
        "PRO_LICENSE_KEYS",
        "PRO_KEYS_DB",
        "LEMON_SQUEEZY_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ENABLE_REAL_PAYMENTS", "true")


@pytest.fixture()
def client():
    _app_module.app.config["TESTING"] = True
    return _app_module.app.test_client()


def _btcpay_env(monkeypatch, addr=FIXED_ADDR, secret="btcpay-whsec-test"):
    monkeypatch.setenv("BTCPAY_URL", "https://btcpay.example.com")
    monkeypatch.setenv("BTCPAY_API_KEY", "btcpay-api-test")
    monkeypatch.setenv("BTCPAY_STORE_ID", "store_1")
    monkeypatch.setenv("BTCPAY_WEBHOOK_SECRET", secret)
    monkeypatch.setenv("BTCPAY_RECONCILIATION_VERIFIED", "1")
    monkeypatch.setenv("PAYMENT_BTC_ADDRESS", addr)


def _sign(raw: bytes, secret: str = "btcpay-whsec-test") -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def _invoice_payload(invoice_id="inv_1", event_type="InvoiceSettled", known=True):
    if known and invoice_id:
        btcpay.record_invoice_plan(invoice_id, "pro")
    return {"invoiceId": invoice_id, "type": event_type, "deliveryId": "d1"}


# ── Off-by-default ───────────────────────────────────────────────────


def test_btcpay_unconfigured_by_default():
    assert btcpay.btcpay_configured() is False
    assert btcpay.payment_address() == ""


def test_btcpay_configured_with_env(monkeypatch):
    _btcpay_env(monkeypatch)
    assert btcpay.btcpay_configured() is True
    assert btcpay.payment_address() == FIXED_ADDR


def test_btcpay_credentials_do_not_enable_checkout_before_reconciliation(
    monkeypatch, client
):
    _btcpay_env(monkeypatch)
    monkeypatch.setenv("BTCPAY_RECONCILIATION_VERIFIED", "0")
    assert btcpay.btcpay_credentials_configured() is True
    assert btcpay.btcpay_configured() is False
    status = client.get("/api/license-status").get_json()
    assert status["btcpay"] is False
    assert status["checkout_state"] == "unavailable"
    assert status["checkout_unavailable_reason"] == "reconciliation_required"
    response = client.post(
        "/api/upgrade/checkout", json={"plan": "pro", "method": "btc"}
    )
    assert response.status_code == 503
    assert response.get_json()["reason"] == "reconciliation_required"


def test_btcpay_requires_webhook_secret_before_exposing_checkout(monkeypatch, client):
    """Invoice creation without settlement fulfillment is an unsafe partial
    configuration and must keep the public BTC channel off."""
    _btcpay_env(monkeypatch)
    monkeypatch.delenv("BTCPAY_WEBHOOK_SECRET")
    assert btcpay.btcpay_configured() is False
    assert client.get("/api/license-status").get_json()["btcpay"] is False
    response = client.post(
        "/api/upgrade/checkout",
        json={"plan": "pro", "method": "btc"},
    )
    assert response.status_code == 503
    assert response.get_json()["code"] == "PAYMENTS_NOT_CONFIGURED"


def test_payment_address_never_uses_data_btc_address(monkeypatch):
    """P4-3: PAYMENT_BTC_ADDRESS (receita) é independente do BTC_ADDRESS
    (dados — polling da Parasite). Setar apenas BTC_ADDRESS não ativa o
    endereço de pagamento."""
    monkeypatch.setenv("BTC_ADDRESS", "bc1qdatawallet0000000000000000000000")
    assert btcpay.payment_address() == ""
    _btcpay_env(monkeypatch)
    assert btcpay.payment_address() == FIXED_ADDR


# ── Amounts (sats) ───────────────────────────────────────────────────


def test_plan_amount_sats_pro_positive():
    assert btcpay.plan_amount_sats("pro") > 0
    assert btcpay.plan_amount_sats("premium") > btcpay.plan_amount_sats("pro")


def test_plan_amount_sats_uses_live_quote_when_available(monkeypatch):
    import services.state as _state_mod

    monkeypatch.setitem(_state_mod.latest_snapshot, "btc_price", {"usd": 100_000.0})
    sats = btcpay.plan_amount_sats("pro", usd_month=10)
    # 10 USD at 100k/BTC → 0.0001 BTC → 10.000 sats (10 / 100000 * 1e8)
    assert sats == 10_000
    # Fallback (no quote) still yields a sane positive amount.
    monkeypatch.setitem(_state_mod.latest_snapshot, "btc_price", {"usd": None})
    assert btcpay.plan_amount_sats("pro", usd_month=10) > 0


# ── Invoice creation ─────────────────────────────────────────────────


def test_create_invoice_none_unconfigured(monkeypatch):
    assert btcpay.create_invoice(plan="pro") is None


def test_create_invoice_payload_and_url(monkeypatch):
    _btcpay_env(monkeypatch)
    captured = {}

    def _fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout

        class R:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "id": "inv_payload",
                    "checkoutLink": "https://btcpay.example.com/i/inv_payload",
                    "amount": "0.00012",
                    "status": "New",
                }

        return R()

    monkeypatch.setattr(btcpay.requests, "post", _fake_post)
    inv = btcpay.create_invoice(
        plan="pro", funnel_id="f-1", buyer_email="not-stored@example.com"
    )
    assert inv["id"] == "inv_payload"
    assert "checkoutLink" in inv
    assert captured["url"].endswith("/api/v1/stores/store_1/invoices")
    assert captured["json"]["currency"] == "BTC"
    assert captured["json"]["metadata"]["plan"] == "pro"
    assert "buyerEmail" not in captured["json"]["metadata"]
    assert captured["json"]["additionalData"]["posData"]["funnel_id"] == "f-1"
    assert captured["headers"]["Authorization"] == "token btcpay-api-test"
    assert captured["timeout"] == 15


def test_create_invoice_network_error_returns_none(monkeypatch):
    _btcpay_env(monkeypatch)

    class _Err:
        def raise_for_status(self):
            raise requests.exceptions.ConnectionError("boom")

    import requests

    monkeypatch.setattr(btcpay.requests, "post", lambda *a, **k: _Err())
    assert btcpay.create_invoice(plan="pro") is None


# ── Webhook signature ────────────────────────────────────────────────


def test_webhook_signature_verify(monkeypatch):
    _btcpay_env(monkeypatch)
    raw = json.dumps(_invoice_payload()).encode()
    assert btcpay.verify_webhook_signature(raw, _sign(raw)) is True
    # Wrong secret / forged sig / empty all rejected.
    assert btcpay.verify_webhook_signature(raw, "deadbeef") is False
    assert btcpay.verify_webhook_signature(raw, "") is False
    # Plain hex without the "sha256=" prefix still verifies (lenient parse).
    plain = hmac.new(b"btcpay-whsec-test", raw, hashlib.sha256).hexdigest()
    assert btcpay.verify_webhook_signature(raw, plain) is True


# ── Fulfillment ─────────────────────────────────────────────────────


def test_webhook_settled_fulfills(monkeypatch):
    _btcpay_env(monkeypatch)
    monkeypatch.setenv("PRO_KEYS_DB", "1")  # activate the gate to honor the key
    key = btcpay.handle_invoice_webhook(_invoice_payload(invoice_id="inv_a"))
    assert key and _KEY_RE.match(key)
    assert licensing._key_valid(key) is True  # the gate honors the BTC key


def test_webhook_processing_is_noop(monkeypatch):
    _btcpay_env(monkeypatch)
    for evt in ("InvoiceProcessing", "InvoiceExpired", "InvoiceInvalid"):
        assert btcpay.handle_invoice_webhook(_invoice_payload(event_type=evt)) is None


def test_webhook_unknown_event_noop(monkeypatch):
    _btcpay_env(monkeypatch)
    payload = {"invoiceId": "inv_x", "type": "StoreWebhookDelivered"}
    assert btcpay.handle_invoice_webhook(payload) is None


def test_webhook_without_invoice_id_noop(monkeypatch):
    _btcpay_env(monkeypatch)
    assert btcpay.handle_invoice_webhook({"type": "InvoiceSettled"}) is None


def test_webhook_replay_returns_same_key(monkeypatch):
    _btcpay_env(monkeypatch)
    payload = _invoice_payload(invoice_id="inv_replay")
    first = btcpay.handle_invoice_webhook(payload)
    assert first and _KEY_RE.match(first)
    assert btcpay.handle_invoice_webhook(payload) == first  # never 2 licenses


def test_webhook_replay_issues_only_one_license(monkeypatch):
    _btcpay_env(monkeypatch)
    from services.db import get_db

    def _count():
        c = get_db()
        try:
            return c.execute(
                "SELECT COUNT(*) AS n FROM pro_licenses WHERE source='btcpay'"
            ).fetchone()["n"]
        finally:
            c.close()

    baseline = _count()
    payload = _invoice_payload(invoice_id="inv_ledger")
    btcpay.handle_invoice_webhook(payload)
    btcpay.handle_invoice_webhook(payload)
    btcpay.handle_invoice_webhook(payload)
    assert _count() == baseline + 1


def test_webhook_releases_claim_on_license_failure(_iso_db, monkeypatch):
    """Issue #565: the license INSERT fails inside the atomic transaction →
    the claim rolls back WITH it (the legacy _release_claim dance is gone)
    and the provider retry fulfills cleanly on a fresh claim."""
    _btcpay_env(monkeypatch)
    payload = _invoice_payload(invoice_id="inv_flaky")
    calls = {"n": 0}
    real = licensing.issue_license_in_conn

    def _flaky(conn, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.OperationalError("db locked (simulated)")
        return real(conn, **kw)

    monkeypatch.setattr(licensing, "issue_license_in_conn", _flaky)
    with pytest.raises(sqlite3.OperationalError):
        btcpay.handle_invoice_webhook(payload)
    key = btcpay.handle_invoice_webhook(payload)  # retry re-claims and succeeds
    assert key and _KEY_RE.match(key)
    assert licensing._key_valid(key) is True
    assert btcpay.handle_invoice_webhook(payload) == key  # replay → same key


def test_webhook_tracks_paid_event_once(monkeypatch):
    _btcpay_env(monkeypatch)
    calls = []
    import services.conversion as conversion_mod

    monkeypatch.setattr(
        conversion_mod, "track_event", lambda *a, **kw: calls.append(kw)
    )
    payload = _invoice_payload(invoice_id="inv_funnel")
    btcpay.handle_invoice_webhook(payload)
    btcpay.handle_invoice_webhook(payload)  # replay
    assert len(calls) == 1
    assert calls[0]["meta"]["method"] == "btc"
    assert calls[0]["meta"]["provider"] == "btcpay"


def test_webhook_plan_resolution_premium(monkeypatch):
    """Settled invoice whose plan was persisted at checkout → premium
    license, resolved from the LOCAL ledger (no network in the webhook)."""
    _btcpay_env(monkeypatch)
    btcpay.record_invoice_plan("inv_prem", "premium")
    key = btcpay.handle_invoice_webhook(_invoice_payload(invoice_id="inv_prem"))
    assert key and _KEY_RE.match(key)
    assert licensing._key_plan(key) == "premium"


def test_webhook_unknown_invoice_never_issues_license(monkeypatch):
    """A signed store event is insufficient without local checkout intent."""
    _btcpay_env(monkeypatch)
    key = btcpay.handle_invoice_webhook(
        _invoice_payload(invoice_id="inv_unknown", known=False)
    )
    assert key is None
    assert btcpay.fulfilled_license_key("inv_unknown") == ""


def test_webhook_log_masks_key_sha(caplog, monkeypatch):
    """Fulfillment log must not leak the raw license key — hash only."""
    _btcpay_env(monkeypatch)
    with caplog.at_level(logging.INFO, logger="cypher65.btcpay"):
        key = btcpay.handle_invoice_webhook(_invoice_payload(invoice_id="inv_log"))
    assert key and _KEY_RE.match(key)
    assert key not in caplog.text  # raw key NEVER reaches the log
    assert "key_sha=" in caplog.text  # correlation hash present


# ── WebLN fallback ───────────────────────────────────────────────────


def test_webln_available_only_with_endpoint(monkeypatch):
    assert btcpay.webln_invoice_available() is False
    monkeypatch.setenv("LN_ADDRESS", "ops@ln.example.com")
    assert btcpay.webln_invoice_available() is False
    monkeypatch.setenv("LN_INVOICE_ENDPOINT", "https://ln.example.com/invoice")
    assert btcpay.webln_invoice_available() is False


def test_create_webln_invoice(monkeypatch):
    monkeypatch.setenv("LN_INVOICE_ENDPOINT", "https://ln.example.com/invoice")
    captured = {}

    def _fake_get(url, params=None, timeout=None):
        captured["params"] = params
        captured["timeout"] = timeout

        class R:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "invoice": "lnbc1mockbolt11invoice",
                    "payment_hash": "ab" * 32,
                }

        return R()

    monkeypatch.setattr(btcpay.requests, "get", _fake_get)
    inv = btcpay.create_webln_invoice(plan="pro")
    assert inv["bolt11"] == "lnbc1mockbolt11invoice"
    assert captured["params"]["amount_sat"] > 0
    assert "CYPHER65 PRO" in captured["params"]["memo"]


def test_create_webln_invoice_none_unconfigured(monkeypatch):
    assert btcpay.create_webln_invoice(plan="pro") is None


# ── Routes ───────────────────────────────────────────────────────────


def test_checkout_btc_503_unconfigured(client):
    r = client.post("/api/upgrade/checkout", json={"plan": "pro", "method": "btc"})
    assert r.status_code == 503
    assert r.get_json()["code"] == "PAYMENTS_NOT_CONFIGURED"


def test_checkout_card_still_503_unconfigured(client):
    """Card path (LS) is untouched by the BTC work — still 503 unconfigured."""
    r = client.post("/api/upgrade/checkout", json={"plan": "pro", "method": "card"})
    assert r.status_code == 503


def test_checkout_btc_payload(client, monkeypatch):
    _btcpay_env(monkeypatch)
    monkeypatch.setattr(
        btcpay,
        "create_invoice",
        lambda plan="pro", funnel_id="", buyer_email="": {
            "id": "inv_route",
            "checkoutLink": "https://btcpay.example.com/i/inv_route",
            "amount": "0.00012",
            "status": "New",
        },
    )
    r = client.post("/api/upgrade/checkout", json={"plan": "pro", "method": "btc"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["method"] == "btc"
    assert body["provider"] == "btcpay"
    assert body["invoice_id"] == "inv_route"
    assert body["status_token"]
    # Hosted checkout URL (BTCPay renders its own per-invoice QR/BIP-21).
    assert body["checkout_url"] == "https://btcpay.example.com/i/inv_route"
    assert "address" not in body and "bip21" not in body
    assert body["amount_sat"] > 0
    assert body["expires_in_min"] == 15
    # The plan was persisted for the webhook (no network in the webhook).
    assert btcpay._invoice_plan("inv_route") == "pro"


def test_checkout_btc_persists_premium_plan(client, monkeypatch):
    """Checkout persists invoice→plan so the webhook resolves premium
    WITHOUT any network call — a BTCPay outage can't downgrade it."""
    _btcpay_env(monkeypatch)
    monkeypatch.setattr(
        btcpay,
        "create_invoice",
        lambda plan="pro", funnel_id="", buyer_email="": {
            "id": "inv_prem_plan",
            "checkoutLink": "https://btcpay.example.com/i/inv_prem_plan",
            "amount": "0.0004",
            "status": "New",
        },
    )
    r = client.post("/api/upgrade/checkout", json={"plan": "premium", "method": "btc"})
    assert r.status_code == 200
    assert btcpay._invoice_plan("inv_prem_plan") == "premium"


def test_invoice_plan_ledger_roundtrip():
    btcpay.record_invoice_plan("inv_ledger_plan", "premium")
    assert btcpay._invoice_plan("inv_ledger_plan") == "premium"
    # Unknown / unset → defensive PRO.
    assert btcpay._invoice_plan("inv_never_seen") == "pro"
    # Invalid plan normalizes to PRO.
    btcpay.record_invoice_plan("inv_bad_plan", "enterprise")
    assert btcpay._invoice_plan("inv_bad_plan") == "pro"


def test_status_token_is_hashed_at_rest_and_compared_exactly():
    from services.db import get_db

    assert btcpay.record_invoice_plan("inv_token_hash", "pro", STATUS_TOKEN) is True
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT status_token_hash FROM btcpay_invoice_plans WHERE invoice_id = ?",
            ("inv_token_hash",),
        ).fetchone()
    finally:
        conn.close()
    assert row["status_token_hash"] == hashlib.sha256(STATUS_TOKEN.encode()).hexdigest()
    assert row["status_token_hash"] != STATUS_TOKEN
    assert btcpay.verify_invoice_status_token("inv_token_hash", STATUS_TOKEN) is True
    assert btcpay.verify_invoice_status_token("inv_token_hash", "wrong") is False


def test_checkout_does_not_expose_legacy_webln_fallback(client, monkeypatch):
    monkeypatch.setenv("LN_INVOICE_ENDPOINT", "https://ln.example.com/invoice")
    monkeypatch.setattr(
        btcpay,
        "create_webln_invoice",
        lambda plan="pro": {
            "bolt11": "lnbc1routefallback",
            "payment_hash": "ph_route",
            "amount_sat": 12000,
            "plan": plan,
        },
    )
    r = client.post("/api/upgrade/checkout", json={"plan": "pro", "method": "btc"})
    assert r.status_code == 503
    body = r.get_json()
    assert body["payment_state"] == "checkout_unavailable"
    assert body["reason"] == "provider_not_configured"


def test_checkout_unknown_method_400(client, monkeypatch):
    _btcpay_env(monkeypatch)
    r = client.post("/api/upgrade/checkout", json={"plan": "pro", "method": "paypal"})
    assert r.status_code == 400


def test_btcpay_webhook_route_end_to_end(client, monkeypatch):
    _btcpay_env(monkeypatch)
    raw = json.dumps(_invoice_payload(invoice_id="inv_e2e")).encode()
    r = client.post(
        "/api/payments/btcpay/webhook",
        data=raw,
        content_type="application/json",
        headers={"x-btcpay-sig": _sign(raw)},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body == {"ok": True, "handled": True}


def test_btcpay_webhook_route_replay_is_idempotent_without_exposing_key(
    client, monkeypatch
):
    _btcpay_env(monkeypatch)
    raw = json.dumps(_invoice_payload(invoice_id="inv_e2e_replay")).encode()
    hdrs = {"x-btcpay-sig": _sign(raw)}
    r1 = client.post(
        "/api/payments/btcpay/webhook",
        data=raw,
        content_type="application/json",
        headers=hdrs,
    )
    r2 = client.post(
        "/api/payments/btcpay/webhook",
        data=raw,
        content_type="application/json",
        headers=hdrs,
    )
    assert r1.status_code == 200
    assert r1.get_json() == {"ok": True, "handled": True}
    assert r2.get_json() == {"ok": True, "handled": True}


def test_btcpay_webhook_route_bad_signature(client, monkeypatch):
    _btcpay_env(monkeypatch)
    raw = json.dumps(_invoice_payload()).encode()
    r = client.post(
        "/api/payments/btcpay/webhook",
        data=raw,
        content_type="application/json",
        headers={"x-btcpay-sig": "forged"},
    )
    assert r.status_code == 403


def test_btcpay_webhook_route_unconfigured(client):
    r = client.post(
        "/api/payments/btcpay/webhook", data=b"{}", content_type="application/json"
    )
    assert r.status_code == 400


def test_status_route_503_unconfigured(client):
    r = client.get("/api/upgrade/status/inv_1")
    assert r.status_code == 503


def test_status_route_404_unknown(client, monkeypatch):
    _btcpay_env(monkeypatch)
    monkeypatch.setattr(btcpay, "get_invoice", lambda iid: None)
    r = client.get(
        "/api/upgrade/status/inv_nope", headers={"X-Checkout-Token": "forged"}
    )
    assert r.status_code == 403


def test_status_route_rejects_missing_or_wrong_checkout_token(client, monkeypatch):
    _btcpay_env(monkeypatch)
    btcpay.record_invoice_plan("inv_private", "pro", STATUS_TOKEN)
    assert client.get("/api/upgrade/status/inv_private").status_code == 403
    assert (
        client.get(f"/api/upgrade/status/inv_private?token={STATUS_TOKEN}").status_code
        == 403
    )
    assert (
        client.get(
            "/api/upgrade/status/inv_private",
            headers={"X-Checkout-Token": "wrong"},
        ).status_code
        == 403
    )


def test_status_route_returns_status(client, monkeypatch):
    _btcpay_env(monkeypatch)
    btcpay.record_invoice_plan("inv_live", "pro", STATUS_TOKEN)
    monkeypatch.setattr(
        btcpay,
        "get_invoice",
        lambda iid: {"id": iid, "status": "Settled", "amount": "0.00012"},
    )
    r = client.get(
        "/api/upgrade/status/inv_live",
        headers={"X-Checkout-Token": STATUS_TOKEN},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "Settled"
    assert body["invoice_id"] == "inv_live"
    assert body["payment_state"] == "pending"


def test_status_route_returns_license_key_when_settled(client, monkeypatch):
    """Issue #249: Settled + fulfilled → the frontend gets the key so it can
    apply it and show "PRO ativado ✓" without waiting for the webhook."""
    _btcpay_env(monkeypatch)
    monkeypatch.setattr(
        btcpay,
        "get_invoice",
        lambda iid: {"id": iid, "status": "Settled", "amount": "0.00012"},
    )
    # Fulfill once (webhook path) so the ledger holds the key.
    btcpay.record_invoice_plan("inv_settled_key", "pro", STATUS_TOKEN)
    key = btcpay.handle_invoice_webhook(_invoice_payload(invoice_id="inv_settled_key"))
    assert key and _KEY_RE.match(key)
    r = client.get(
        "/api/upgrade/status/inv_settled_key",
        headers={"X-Checkout-Token": STATUS_TOKEN},
    )
    assert r.status_code == 200
    assert r.get_json()["license_key"] == key
    assert r.get_json()["payment_state"] == "confirmed"


def test_status_route_no_key_when_not_settled(client, monkeypatch):
    """Pending invoices never leak a key — the field is empty until Settled."""
    _btcpay_env(monkeypatch)
    btcpay.record_invoice_plan("inv_pending", "pro", STATUS_TOKEN)
    monkeypatch.setattr(
        btcpay,
        "get_invoice",
        lambda iid: {"id": iid, "status": "New", "amount": "0.00012"},
    )
    r = client.get(
        "/api/upgrade/status/inv_pending",
        headers={"X-Checkout-Token": STATUS_TOKEN},
    )
    assert r.status_code == 200
    assert r.get_json()["license_key"] == ""
    assert r.get_json()["payment_state"] == "pending"


@pytest.mark.parametrize(
    ("provider_status", "expected"),
    [("Expired", "expired"), ("Invalid", "invalid")],
)
def test_status_route_normalizes_terminal_payment_states(
    client, monkeypatch, provider_status, expected
):
    _btcpay_env(monkeypatch)
    invoice_id = f"inv_{expected}"
    btcpay.record_invoice_plan(invoice_id, "pro", STATUS_TOKEN)
    monkeypatch.setattr(
        btcpay,
        "get_invoice",
        lambda iid: {"id": iid, "status": provider_status, "amount": "0.00012"},
    )
    response = client.get(
        f"/api/upgrade/status/{invoice_id}",
        headers={"X-Checkout-Token": STATUS_TOKEN},
    )
    assert response.status_code == 200
    assert response.get_json()["payment_state"] == expected


def test_webln_internal_fulfillment_is_idempotent(monkeypatch):
    """Issue #249: sha256(preimage) == payment_hash (BOLT-11) → license issued
    from the LOCAL plan ledger — idempotent per payment_hash."""
    monkeypatch.setenv("LN_INVOICE_ENDPOINT", "https://ln.example.com/invoice")
    preimage = "ab" * 32  # 32-byte preimage, hex
    payment_hash = hashlib.sha256(bytes.fromhex(preimage)).hexdigest()
    btcpay.record_invoice_plan(payment_hash, "pro")
    key = btcpay.fulfill_webln_payment(payment_hash, preimage)
    assert _KEY_RE.match(key)
    assert licensing._key_valid(key) is True
    # Replay → SAME key, never a second license.
    assert btcpay.fulfill_webln_payment(payment_hash, preimage) == key


def test_webln_internal_fulfillment_preserves_premium_plan(monkeypatch):
    """Plan comes from the ledger recorded at checkout — premium honored."""
    monkeypatch.setenv("LN_INVOICE_ENDPOINT", "https://ln.example.com/invoice")
    preimage = "cd" * 32
    payment_hash = hashlib.sha256(bytes.fromhex(preimage)).hexdigest()
    btcpay.record_invoice_plan(payment_hash, "premium")
    key = btcpay.fulfill_webln_payment(payment_hash, preimage)
    assert licensing._key_plan(key) == "premium"


def test_webln_internal_fulfillment_rejects_wrong_preimage(monkeypatch):
    """A preimage that does NOT hash to the payment_hash is rejected."""
    monkeypatch.setenv("LN_INVOICE_ENDPOINT", "https://ln.example.com/invoice")
    preimage = "ef" * 32
    payment_hash = hashlib.sha256(bytes.fromhex(preimage)).hexdigest()
    btcpay.record_invoice_plan(payment_hash, "pro")
    assert btcpay.fulfill_webln_payment(payment_hash, "11" * 32) is None


def test_webln_internal_fulfillment_rejects_unknown_hash(monkeypatch):
    monkeypatch.setenv("LN_INVOICE_ENDPOINT", "https://ln.example.com/invoice")
    preimage = "22" * 32
    payment_hash = hashlib.sha256(bytes.fromhex(preimage)).hexdigest()
    # Never checked out → hash unknown; no preimage can exist for it.
    assert btcpay.fulfill_webln_payment(payment_hash, preimage) is None


def test_webln_confirm_unconfigured_503(client):
    r = client.post(
        "/api/upgrade/webln/confirm",
        json={"payment_hash": "ph", "preimage": "ab"},
    )
    assert r.status_code == 503


def test_webln_confirm_remains_unavailable_even_with_legacy_endpoint(
    client, monkeypatch
):
    monkeypatch.setenv("LN_INVOICE_ENDPOINT", "https://ln.example.com/invoice")
    r = client.post("/api/upgrade/webln/confirm", json={"payment_hash": "ph"})
    assert r.status_code == 503
    r = client.post("/api/upgrade/webln/confirm", json={})
    assert r.status_code == 503


def test_license_status_enriches_btc_payload(client, monkeypatch):
    """license-status exposes the BTC payment surface for the frontend."""
    r = client.get("/api/license-status")
    assert r.status_code == 200
    body = r.get_json()
    assert body["btcpay"] is False
    assert body["payment_btc_address"] == ""
    _btcpay_env(monkeypatch)
    r2 = client.get("/api/license-status")
    body2 = r2.get_json()
    assert body2["btcpay"] is True
    assert body2["payment_btc_address"] == FIXED_ADDR


# ── Crash-safe fulfillment (Issue #565) ─────────────────────────────


@pytest.fixture()
def _iso_db(tmp_path, monkeypatch):
    """Scratch DB_PATH for THIS test only.

    The crash-safe tests make strict ledger assertions (counts == 0/1, claim
    rows present/absent). The session-wide scratch DB (conftest) is shared by
    every test that fulfills licenses, so counts there are not a reliable
    baseline. A fresh DB file per test isolates the ledger completely —
    get_db() resolves DB_PATH at call time (services/bootstrap.py).
    """
    db = tmp_path / "crash_safe.sqlite"
    monkeypatch.setenv("DB_PATH", str(db))
    return db


class _BoomProxy:
    """Connection proxy that raises when the guarded statement runs.

    sqlite3.Connection is an immutable C type — its execute() cannot be
    monkeypatched. The proxy delegates every call to the real connection and
    injects the crash at exactly the statement the test chooses, modelling a
    process death between two statements of the fulfillment transaction.
    """

    def __init__(self, inner, fragment: str):
        self._inner = inner
        self._fragment = fragment

    def execute(self, sql, *args):
        if self._fragment in sql:
            raise sqlite3.OperationalError(f"crash at {self._fragment!r} (simulated)")
        return self._inner.execute(sql, *args)

    def commit(self):
        return self._inner.commit()

    def rollback(self):
        return self._inner.rollback()

    def close(self):
        return self._inner.close()


def _licenses_count(source: str) -> int:
    from services.db import get_db

    c = get_db()
    try:
        return c.execute(
            "SELECT COUNT(*) AS n FROM pro_licenses WHERE source = ?", (source,)
        ).fetchone()["n"]
    finally:
        c.close()


def _claim_row(invoice_id: str):
    from services.db import get_db

    c = get_db()
    try:
        return c.execute(
            "SELECT invoice_id, event, license_key FROM processed_invoices"
            " WHERE invoice_id = ?",
            (invoice_id,),
        ).fetchone()
    finally:
        c.close()


def test_atomic_fulfill_crash_after_license_insert_rolls_back_both(
    _iso_db, monkeypatch
):
    """The core crash window (Issue #565): the license INSERT commits-able and
    the process dies BEFORE the completion UPDATE — nothing may survive: no
    empty claim, no orphan key. The provider's retry re-claims on a clean
    slate and fulfills exactly one license."""
    _btcpay_env(monkeypatch)
    payload = _invoice_payload(invoice_id="inv_crash_mid")
    real_get_db = btcpay.get_db

    def _crashing_get_db():
        return _BoomProxy(real_get_db(), "UPDATE processed_invoices")

    monkeypatch.setattr(btcpay, "get_db", _crashing_get_db)
    with pytest.raises(sqlite3.OperationalError):
        btcpay.handle_invoice_webhook(payload)
    # Rolled back: neither the claim nor the license survived.
    assert _claim_row("inv_crash_mid") is None
    assert _licenses_count("btcpay") == 0

    # The provider retry re-claims and fulfills on a clean slate.
    monkeypatch.setattr(btcpay, "get_db", real_get_db)
    key = btcpay.handle_invoice_webhook(payload)
    assert key and _KEY_RE.match(key)
    row = _claim_row("inv_crash_mid")
    assert row["license_key"] == key  # claim and key committed atomically
    assert _licenses_count("btcpay") == 1
    assert btcpay.handle_invoice_webhook(payload) == key  # replay → same key


def test_atomic_fulfill_crash_at_license_insert_rolls_back_claim(
    _iso_db, monkeypatch
):
    """Failure BEFORE the license INSERT (e.g. db locked): the claim must not
    survive either — the atomic path never leaves a claimed-but-empty row."""
    _btcpay_env(monkeypatch)
    payload = _invoice_payload(invoice_id="inv_crash_ins")
    real_get_db = btcpay.get_db

    def _crashing_get_db():
        return _BoomProxy(real_get_db(), "INSERT INTO pro_licenses")

    monkeypatch.setattr(btcpay, "get_db", _crashing_get_db)
    with pytest.raises(sqlite3.OperationalError):
        btcpay.handle_invoice_webhook(payload)
    assert _claim_row("inv_crash_ins") is None
    assert _licenses_count("btcpay") == 0

    monkeypatch.setattr(btcpay, "get_db", real_get_db)
    key = btcpay.handle_invoice_webhook(payload)
    assert key and _KEY_RE.match(key)
    assert _licenses_count("btcpay") == 1
    assert btcpay.handle_invoice_webhook(payload) == key


def test_webln_fulfillment_crash_rolls_back_atomically(_iso_db, monkeypatch):
    """WebLN path uses the same atomic transaction: a crash between the
    license INSERT and the completion rolls back claim + license; the retry
    fulfills exactly once with the ledger-resolved plan."""
    monkeypatch.setenv("LN_INVOICE_ENDPOINT", "https://ln.example.com/invoice")
    preimage = "cd" * 32
    payment_hash = hashlib.sha256(bytes.fromhex(preimage)).hexdigest()
    btcpay.record_invoice_plan(payment_hash, "premium")
    real_get_db = btcpay.get_db

    def _crashing_get_db():
        return _BoomProxy(real_get_db(), "UPDATE processed_invoices")

    monkeypatch.setattr(btcpay, "get_db", _crashing_get_db)
    with pytest.raises(sqlite3.OperationalError):
        btcpay.fulfill_webln_payment(payment_hash, preimage)
    assert _claim_row(payment_hash) is None
    assert _licenses_count("webln") == 0

    monkeypatch.setattr(btcpay, "get_db", real_get_db)
    key = btcpay.fulfill_webln_payment(payment_hash, preimage)
    assert _KEY_RE.match(key)
    assert licensing._key_plan(key) == "premium"  # plan preserved
    assert _claim_row(payment_hash)["license_key"] == key
    assert _licenses_count("webln") == 1
    assert btcpay.fulfill_webln_payment(payment_hash, preimage) == key


def test_webhook_concurrent_deliveries_issue_one_license(_iso_db, monkeypatch):
    """Concurrent deliveries serialize on BEGIN IMMEDIATE: the loser blocks
    until the winner commits and returns the SAME key — one license total."""
    _btcpay_env(monkeypatch)
    payload = _invoice_payload(invoice_id="inv_concurrent")
    results = queue.Queue()
    barrier = threading.Barrier(2)

    def _worker():
        barrier.wait()  # both threads race the same invoice at the same time
        try:
            results.put(("ok", btcpay.handle_invoice_webhook(payload)))
        except Exception as exc:  # pragma: no cover - surfaces real bugs
            results.put(("err", exc))

    threads = [threading.Thread(target=_worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)
    outcomes = [results.get(timeout=1) for _ in range(2)]
    assert all(status == "ok" for status, _ in outcomes), outcomes
    keys = {key for _, key in outcomes}
    assert len(keys) == 1  # same key from both deliveries
    assert _licenses_count("btcpay") == 1  # exactly one license
    assert _claim_row("inv_concurrent")["license_key"] == keys.pop()


def test_webln_concurrent_confirms_issue_one_license(_iso_db, monkeypatch):
    """Same serialization guarantee for the WebLN confirm path."""
    monkeypatch.setenv("LN_INVOICE_ENDPOINT", "https://ln.example.com/invoice")
    preimage = "ab" * 32
    payment_hash = hashlib.sha256(bytes.fromhex(preimage)).hexdigest()
    btcpay.record_invoice_plan(payment_hash, "pro")
    results = queue.Queue()
    barrier = threading.Barrier(2)

    def _worker():
        barrier.wait()
        try:
            results.put(
                ("ok", btcpay.fulfill_webln_payment(payment_hash, preimage))
            )
        except Exception as exc:  # pragma: no cover - surfaces real bugs
            results.put(("err", exc))

    threads = [threading.Thread(target=_worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)
    outcomes = [results.get(timeout=1) for _ in range(2)]
    assert all(status == "ok" for status, _ in outcomes), outcomes
    keys = {key for _, key in outcomes}
    assert len(keys) == 1
    assert _licenses_count("webln") == 1


def test_stuck_empty_claim_fails_visibly_and_never_reissues(
    _iso_db, monkeypatch, caplog
):
    """A legacy persisted empty claim (pre-#565 crash) must fail VISIBLY:
    PaymentClaimStuckError + audit trail + error log, and NO second license
    is issued automatically — an orphan license may already exist."""
    _btcpay_env(monkeypatch)
    invoice_id = "inv_orphan"
    btcpay.record_invoice_plan(invoice_id, "pro")  # known invoice
    # Simulate the pre-#565 crash: claim committed with an empty key.
    from services.db import get_db

    licensing.ensure_licenses_table()  # fresh isolated DB
    btcpay._ensure_processed_invoices_table()
    c = get_db()
    try:
        c.execute(
            "INSERT INTO processed_invoices (invoice_id, event, license_key,"
            " processed_ts) VALUES (?, 'invoice_settled', '', ?)",
            (invoice_id, int(time.time())),
        )
        c.commit()
    finally:
        c.close()
    baseline = _licenses_count("btcpay")
    with caplog.at_level(logging.ERROR, logger="cypher65.btcpay"):
        with pytest.raises(btcpay.PaymentClaimStuckError) as excinfo:
            btcpay.handle_invoice_webhook(
                {"invoiceId": invoice_id, "type": "InvoiceSettled"}
            )
    assert excinfo.value.invoice_id == invoice_id
    assert "manual reconciliation" in str(excinfo.value)
    assert "NOT issuing a new one" in caplog.text  # visible operator signal
    assert _licenses_count("btcpay") == baseline  # NO automatic reissue
    # A later replay keeps failing visibly — the buyer is never silent-lost.
    with pytest.raises(btcpay.PaymentClaimStuckError):
        btcpay.handle_invoice_webhook(
            {"invoiceId": invoice_id, "type": "InvoiceSettled"}
        )


def test_stuck_claim_error_propagates_through_webln_path(_iso_db, monkeypatch):
    """The WebLN path surfaces the same visible failure (no silent OK, no
    automatic reissue) for a legacy empty claim."""
    monkeypatch.setenv("LN_INVOICE_ENDPOINT", "https://ln.example.com/invoice")
    preimage = "ab" * 32
    payment_hash = hashlib.sha256(bytes.fromhex(preimage)).hexdigest()
    btcpay.record_invoice_plan(payment_hash, "pro")
    from services.db import get_db

    licensing.ensure_licenses_table()  # fresh isolated DB
    btcpay._ensure_processed_invoices_table()
    c = get_db()
    try:
        c.execute(
            "INSERT INTO processed_invoices (invoice_id, event, license_key,"
            " processed_ts) VALUES (?, 'invoice_settled', '', ?)",
            (payment_hash, int(time.time())),
        )
        c.commit()
    finally:
        c.close()
    baseline = _licenses_count("webln")
    with pytest.raises(btcpay.PaymentClaimStuckError):
        btcpay.fulfill_webln_payment(payment_hash, preimage)
    assert _licenses_count("webln") == baseline  # no automatic reissue


def test_legacy_claim_primitives_still_work(_iso_db, monkeypatch):
    """Backward-compat: _claim_invoice/_complete_invoice/_release_claim keep
    their pre-#565 behavior for any external caller."""
    _btcpay_env(monkeypatch)
    claimed, key = btcpay._claim_invoice("inv_legacy")
    assert claimed is True and key == ""
    claimed2, key2 = btcpay._claim_invoice("inv_legacy")
    assert claimed2 is False and key2 == ""  # in-flight (empty key)
    btcpay._complete_invoice("inv_legacy", "C65-AAAA-BBBB-CCCC-DDDD")
    claimed3, key3 = btcpay._claim_invoice("inv_legacy")
    assert claimed3 is False and key3 == "C65-AAAA-BBBB-CCCC-DDDD"
    btcpay._release_claim("inv_legacy")
    assert btcpay.fulfilled_license_key("inv_legacy") == ""
