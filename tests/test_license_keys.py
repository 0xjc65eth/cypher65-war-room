"""
CYPHER65 // R1 revenue — dynamic PRO license keys + Lemon Squeezy adapter
=========================================================================
Validates the revenue path built on top of the existing licensing gate:

1. Key generation: copy-safe C65-XXXX-XXXX-XXXX-XXXX format, no ambiguous
   characters (I/L/O/0/1).
2. DB-backed lifecycle: issue → valid; expired → invalid; revoked → invalid;
   missing table → clean False (never raises).
3. Gate activation: LEMON_SQUEEZY_API_KEY / PRO_KEYS_DB flip licensing on
   (additive to PRO_LICENSE_KEYS).
4. Webhook: x-signature HMAC-SHA256 verification (right/wrong), order_created
   fulfillment issues a key the gate honors; unknown events are no-ops.
5. Routes: /api/upgrade/checkout (503 unconfigured / URL when configured),
   /api/payments/webhook (200 + key on valid order), /api/admin/licenses
   (403 unauthenticated / 200 + key with X-API-Key).

HERMETIC — never touches data/war_room.sqlite: tests/conftest.py redirects
DB_PATH to a scratch DB before `import app` (same as test_licensing.py).
"""

import hashlib
import hmac
import json
import os
import re
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as _app_module
from services import licensing, payments

app = _app_module.app

_KEY_RE = re.compile(r"^C65-[A-Z0-9]{4}(-[A-Z0-9]{4}){3}$")
_AMBIGUOUS = set("ILO01")


@pytest.fixture(autouse=True)
def _scrub_payment_env(monkeypatch):
    """Every test starts with the gate OFF and no payment env vars."""
    for name in (
        "PRO_LICENSE_KEYS",
        "LEMON_SQUEEZY_API_KEY",
        "LEMON_SQUEEZY_WEBHOOK_SECRET",
        "LEMON_SQUEEZY_STORE_ID",
        "LEMON_SQUEEZY_VARIANT_ID",
        "PRO_KEYS_DB",
        "API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def client():
    _app_module.app.config["TESTING"] = True
    return _app_module.app.test_client()


def _activate_db_gate(monkeypatch):
    monkeypatch.setenv("PRO_KEYS_DB", "1")


def _ls_env(monkeypatch):
    monkeypatch.setenv("LEMON_SQUEEZY_API_KEY", "ls-test-key")
    monkeypatch.setenv("LEMON_SQUEEZY_WEBHOOK_SECRET", "whsec-test")
    monkeypatch.setenv("LEMON_SQUEEZY_STORE_ID", "1")
    monkeypatch.setenv("LEMON_SQUEEZY_VARIANT_ID", "10")


def _sign(raw: bytes) -> str:
    return hmac.new(
        b"whsec-test", raw, hashlib.sha256
    ).hexdigest()


# ── Key generation ───────────────────────────────────────────────────

def test_generated_key_format_and_safe_alphabet():
    for _ in range(50):
        key = licensing.generate_license_key()
        assert _KEY_RE.match(key), key
        assert not (_AMBIGUOUS & set(key.replace("C65-", "").replace("-", "")))


def test_generated_keys_unique():
    keys = {licensing.generate_license_key() for _ in range(200)}
    assert len(keys) == 200


# ── DB-backed lifecycle ──────────────────────────────────────────────

def test_issue_license_then_valid(monkeypatch):
    _activate_db_gate(monkeypatch)
    key = licensing.issue_license(plan="pro", email="a@b.c", source="test")
    assert licensing._key_valid(key) is True


def test_issued_key_honored_by_license_status(client, monkeypatch):
    _activate_db_gate(monkeypatch)
    key = licensing.issue_license(months=12)
    r = client.get("/api/license-status", headers={"X-License-Key": key})
    assert r.status_code == 200
    assert r.get_json()["pro"] is True
    assert r.get_json()["tier"] == "pro"


def test_expired_key_invalid(monkeypatch):
    _activate_db_gate(monkeypatch)
    key = licensing.issue_license(months=0)  # expires immediately
    assert licensing._key_valid(key) is False


def test_lifetime_key_never_expires(monkeypatch):
    _activate_db_gate(monkeypatch)
    key = licensing.issue_license(months=None)
    assert licensing._key_valid(key) is True


def test_revoked_key_invalid(monkeypatch):
    _activate_db_gate(monkeypatch)
    key = licensing.issue_license()
    assert licensing.revoke_license(key) is True
    assert licensing._key_valid(key) is False
    assert licensing.revoke_license(key) is False  # already revoked


def test_unknown_key_invalid(monkeypatch):
    _activate_db_gate(monkeypatch)
    # A key that was never issued is invalid (clean False, never raises).
    assert licensing._key_valid("C65-ABCD-EFGH-JKMN-PQRS") is False


# ── Gate activation ──────────────────────────────────────────────────

def test_ls_api_key_activates_gate(monkeypatch):
    _ls_env(monkeypatch)
    assert licensing.licensing_configured() is True


def test_pro_keys_db_activates_gate(monkeypatch):
    _activate_db_gate(monkeypatch)
    assert licensing.licensing_configured() is True


def test_open_mode_when_nothing_set():
    assert licensing.licensing_configured() is False
    assert licensing.is_pro() is True


# ── Webhook signature + fulfillment ──────────────────────────────────

def _order_payload(email="buyer@example.com", variant_id=10, order_id="12345"):
    return {
        "meta": {"event_name": "order_created"},
        "data": {
            "id": order_id,
            "attributes": {
                "user_email": email,
                "first_order_item": {"variant_id": variant_id},
            },
        },
    }


def test_webhook_signature_verify(monkeypatch):
    _ls_env(monkeypatch)  # webhook secret must be set for verification
    raw = json.dumps(_order_payload()).encode()
    good = _sign(raw)
    assert payments.verify_webhook_signature(raw, good) is True
    assert payments.verify_webhook_signature(raw, "deadbeef") is False
    assert payments.verify_webhook_signature(raw, "") is False


def test_webhook_fulfills_order(monkeypatch):
    _ls_env(monkeypatch)
    payload = _order_payload()
    key = payments.handle_webhook(payload)
    assert key and _KEY_RE.match(key)
    assert licensing._key_valid(key) is True  # the gate honors the issued key


def test_webhook_unknown_event_noop(monkeypatch):
    _ls_env(monkeypatch)
    payload = {"meta": {"event_name": "subscription_created"}, "data": {}}
    assert payments.handle_webhook(payload) is None


# ── Idempotency (Issue #114) ──────────────────────────────────────────

def test_webhook_replay_returns_same_key(monkeypatch):
    """Same order delivered twice → ONE key, and the replay returns it."""
    _ls_env(monkeypatch)
    payload = _order_payload(email="buyer@example.com", order_id="7001")
    first = payments.handle_webhook(payload)
    assert first and _KEY_RE.match(first)
    replay = payments.handle_webhook(payload)
    assert replay == first  # never a second license
    assert licensing._key_valid(first) is True


def test_webhook_replay_issues_only_one_license(monkeypatch):
    """The license ledger grows by exactly ONE key after a replay."""
    _ls_env(monkeypatch)
    from services.db import get_db
    def _count():
        c = get_db()
        try:
            return c.execute(
                "SELECT COUNT(*) AS n FROM pro_licenses WHERE source='lemon_squeezy'"
            ).fetchone()["n"]
        finally:
            c.close()
    baseline = _count()
    payload = _order_payload(order_id="7002")
    payments.handle_webhook(payload)
    payments.handle_webhook(payload)
    payments.handle_webhook(payload)
    assert _count() == baseline + 1


def test_webhook_replay_route_returns_same_key(client, monkeypatch):
    """The HTTP route also dedupes: POST twice → same key both times."""
    _ls_env(monkeypatch)
    raw = json.dumps(_order_payload(email="buyer@example.com", order_id="7003")).encode()
    sig = _sign(raw)
    r1 = client.post(
        "/api/payments/webhook", data=raw, content_type="application/json",
        headers={"X-Signature": sig},
    )
    assert r1.status_code == 200
    key1 = r1.get_json()["license_key"]
    r2 = client.post(
        "/api/payments/webhook", data=raw, content_type="application/json",
        headers={"X-Signature": sig},
    )
    assert r2.status_code == 200
    assert r2.get_json()["license_key"] == key1


def test_webhook_different_orders_issue_different_keys(monkeypatch):
    """Distinct orders still each get their own key."""
    _ls_env(monkeypatch)
    k1 = payments.handle_webhook(_order_payload(order_id="7004"))
    k2 = payments.handle_webhook(_order_payload(email="other@example.com", order_id="7005"))
    assert k1 and k2
    assert k1 != k2


def test_webhook_replay_no_duplicate_track_event(monkeypatch):
    """The funnel 'paid' event fires exactly once per order."""
    _ls_env(monkeypatch)
    calls = []
    import services.conversion as conversion_mod
    monkeypatch.setattr(conversion_mod, "track_event",
                        lambda *a, **kw: calls.append(kw))
    payload = _order_payload(order_id="7006")
    payments.handle_webhook(payload)
    payments.handle_webhook(payload)  # replay
    assert len(calls) == 1


def test_webhook_releases_claim_on_license_failure(monkeypatch):
    """If issue_license raises, the claim is released so a retry fulfills."""
    _ls_env(monkeypatch)
    payload = _order_payload(order_id="7008")
    calls = {"n": 0}
    real = licensing.issue_license

    def _flaky(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.OperationalError("db locked (simulated)")
        return real(**kw)

    monkeypatch.setattr(licensing, "issue_license", _flaky)
    with pytest.raises(sqlite3.OperationalError):
        payments.handle_webhook(payload)  # first attempt fails
    key = payments.handle_webhook(payload)  # retry re-claims and succeeds
    assert key and _KEY_RE.match(key)
    assert licensing._key_valid(key) is True
    # A third delivery is a replay of a COMPLETED order → same key.
    assert payments.handle_webhook(payload) == key


def test_webhook_route_end_to_end(client, monkeypatch):
    _ls_env(monkeypatch)
    # Unique order id so this test exercises a FRESH fulfillment (not a replay
    # of the order id shared with test_webhook_fulfills_order).
    raw = json.dumps(_order_payload(email="buyer@example.com", order_id="7007")).encode()
    r = client.post(
        "/api/payments/webhook",
        data=raw,
        content_type="application/json",
        headers={"X-Signature": _sign(raw)},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert _KEY_RE.match(body["license_key"])


def test_webhook_route_bad_signature(client, monkeypatch):
    _ls_env(monkeypatch)
    raw = json.dumps(_order_payload()).encode()
    r = client.post(
        "/api/payments/webhook",
        data=raw,
        content_type="application/json",
        headers={"X-Signature": "forged"},
    )
    assert r.status_code == 403


def test_webhook_route_unconfigured(client):
    r = client.post("/api/payments/webhook", data=b"{}", content_type="application/json")
    assert r.status_code == 400


# ── Checkout route ───────────────────────────────────────────────────

def test_checkout_route_503_unconfigured(client):
    r = client.post("/api/upgrade/checkout", json={"plan": "pro"})
    assert r.status_code == 503
    assert r.get_json()["code"] == "PAYMENTS_NOT_CONFIGURED"


def test_checkout_route_returns_url(client, monkeypatch):
    _ls_env(monkeypatch)
    monkeypatch.setattr(
        payments, "create_checkout", lambda plan="pro", email="": "https://buy.lemonsqueezy.com/x"
    )
    r = client.post("/api/upgrade/checkout", json={"plan": "pro"})
    assert r.status_code == 200
    assert r.get_json()["checkout_url"].startswith("https://")


# ── Admin route (manual key issuance) ────────────────────────────────

def test_admin_route_403_without_key(client):
    # Test client defaults to 127.0.0.1 (local bypass) — simulate a remote peer.
    r = client.post(
        "/api/admin/licenses",
        json={"plan": "pro"},
        environ_base={"REMOTE_ADDR": "203.0.113.5"},
    )
    assert r.status_code == 403


def test_admin_route_issues_key_with_api_key(client, monkeypatch):
    monkeypatch.setenv("API_KEY", "op-secret")
    r = client.post(
        "/api/admin/licenses",
        json={"plan": "pro", "email": "community@x.io", "months": 12},
        headers={"X-API-Key": "op-secret"},
    )
    assert r.status_code == 200
    key = r.get_json()["license_key"]
    assert _KEY_RE.match(key)
    # Issued key works against the gate once active.
    _activate_db_gate(monkeypatch)
    assert licensing._key_valid(key) is True


def test_admin_route_rejects_wrong_api_key(client, monkeypatch):
    monkeypatch.setenv("API_KEY", "op-secret")
    r = client.post(
        "/api/admin/licenses",
        json={"plan": "pro"},
        headers={"X-API-Key": "nope"},
        environ_base={"REMOTE_ADDR": "203.0.113.5"},
    )
    assert r.status_code == 403


# ── license-status payload ───────────────────────────────────────────

def test_license_status_reports_payments_provider(client, monkeypatch):
    _ls_env(monkeypatch)
    r = client.get("/api/license-status")
    assert r.status_code == 200
    assert r.get_json()["payments"] == "lemon_squeezy"


def test_license_status_open_mode_no_payments(client):
    r = client.get("/api/license-status")
    assert r.status_code == 200
    assert r.get_json()["payments"] is None
    assert r.get_json()["mode"] == "open"
