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
import re
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as _app_module
from services import btcpay, licensing

app = _app_module.app

_KEY_RE = re.compile(r"^C65-[A-Z0-9]{4}(-[A-Z0-9]{4}){3}$")

FIXED_ADDR = "35gjAoadgQxrNc1Kx6QiSLx7wCCXRnRFkM"


@pytest.fixture(autouse=True)
def _scrub_btcpay_env(monkeypatch):
    """Every test starts with the gate OFF and no BTCPay env vars."""
    for name in (
        "BTCPAY_URL",
        "BTCPAY_API_KEY",
        "BTCPAY_STORE_ID",
        "BTCPAY_WEBHOOK_SECRET",
        "PAYMENT_BTC_ADDRESS",
        "LN_INVOICE_ENDPOINT",
        "LN_ADDRESS",
        "PRO_LICENSE_KEYS",
        "PRO_KEYS_DB",
        "LEMON_SQUEEZY_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def client():
    _app_module.app.config["TESTING"] = True
    return _app_module.app.test_client()


def _btcpay_env(monkeypatch, addr=FIXED_ADDR, secret="btcpay-whsec-test"):
    monkeypatch.setenv("BTCPAY_URL", "https://btcpay.example.com")
    monkeypatch.setenv("BTCPAY_API_KEY", "btcpay-api-test")
    monkeypatch.setenv("BTCPAY_STORE_ID", "store_1")
    monkeypatch.setenv("BTCPAY_WEBHOOK_SECRET", secret)
    monkeypatch.setenv("PAYMENT_BTC_ADDRESS", addr)


def _sign(raw: bytes, secret: str = "btcpay-whsec-test") -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def _invoice_payload(invoice_id="inv_1", event_type="InvoiceSettled"):
    return {"invoiceId": invoice_id, "type": event_type, "deliveryId": "d1"}


# ── Off-by-default ───────────────────────────────────────────────────


def test_btcpay_unconfigured_by_default():
    assert btcpay.btcpay_configured() is False
    assert btcpay.payment_address() == ""


def test_btcpay_configured_with_env(monkeypatch):
    _btcpay_env(monkeypatch)
    assert btcpay.btcpay_configured() is True
    assert btcpay.payment_address() == FIXED_ADDR


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
    inv = btcpay.create_invoice(plan="pro", funnel_id="f-1")
    assert inv["id"] == "inv_payload"
    assert "checkoutLink" in inv
    assert captured["url"].endswith("/api/v1/stores/store_1/invoices")
    assert captured["json"]["currency"] == "BTC"
    assert captured["json"]["metadata"]["plan"] == "pro"
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


def test_webhook_releases_claim_on_license_failure(monkeypatch):
    _btcpay_env(monkeypatch)
    payload = _invoice_payload(invoice_id="inv_flaky")
    calls = {"n": 0}
    real = licensing.issue_license

    def _flaky(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.OperationalError("db locked (simulated)")
        return real(**kw)

    monkeypatch.setattr(licensing, "issue_license", _flaky)
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


def test_webhook_plan_fallback_pro_when_ledger_missing(monkeypatch):
    """Unknown invoice in the ledger still fulfills (defensive PRO), never
    raises — a replayed/legacy invoice can't block the buyer."""
    _btcpay_env(monkeypatch)
    key = btcpay.handle_invoice_webhook(_invoice_payload(invoice_id="inv_unknown"))
    assert key and _KEY_RE.match(key)
    assert licensing._key_plan(key) == "pro"


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
    assert btcpay.webln_invoice_available() is True


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
                    "payment_hash": "ph_1",
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


def test_checkout_webln_fallback(client, monkeypatch):
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
    assert r.status_code == 200
    body = r.get_json()
    assert body["method"] == "lightning"
    assert body["provider"] == "webln"
    assert body["bolt11"] == "lnbc1routefallback"


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
    assert body["ok"] is True
    assert _KEY_RE.match(body["license_key"])


def test_btcpay_webhook_route_replay_same_key(client, monkeypatch):
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
    assert r2.get_json()["license_key"] == r1.get_json()["license_key"]


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
    r = client.get("/api/upgrade/status/inv_nope")
    assert r.status_code == 404


def test_status_route_returns_status(client, monkeypatch):
    _btcpay_env(monkeypatch)
    monkeypatch.setattr(
        btcpay,
        "get_invoice",
        lambda iid: {"id": iid, "status": "Settled", "amount": "0.00012"},
    )
    r = client.get("/api/upgrade/status/inv_live")
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "Settled"
    assert body["invoice_id"] == "inv_live"


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
