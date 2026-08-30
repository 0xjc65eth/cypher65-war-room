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
import logging
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
        "LEMON_SQUEEZY_PREMIUM_VARIANT_ID",
        "PRO_KEYS_DB",
        "API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ENABLE_REAL_PAYMENTS", "true")


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
    return hmac.new(b"whsec-test", raw, hashlib.sha256).hexdigest()


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


def test_expired_key_status_is_explicit_and_never_pro(client, monkeypatch):
    _activate_db_gate(monkeypatch)
    key = licensing.issue_license(months=0)
    body = client.get("/api/license-status", headers={"X-License-Key": key}).get_json()
    assert body["license_state"] == "expired"
    assert body["tier"] == "free"
    assert body["pro"] is False


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


def test_revoked_key_status_is_explicit_and_never_pro(client, monkeypatch):
    _activate_db_gate(monkeypatch)
    key = licensing.issue_license()
    assert licensing.revoke_license(key) is True
    body = client.get("/api/license-status", headers={"X-License-Key": key}).get_json()
    assert body["license_state"] == "revoked"
    assert body["pro"] is False


def test_revoked_paid_license_keeps_confirmed_payment_history(client, monkeypatch):
    _activate_db_gate(monkeypatch)
    key = licensing.issue_license(source="lemon_squeezy")
    assert licensing.revoke_license(key) is True
    body = client.get("/api/license-status", headers={"X-License-Key": key}).get_json()
    assert body["license_state"] == "revoked"
    assert body["payment_state"] == "confirmed"


def test_trial_and_paid_license_states_are_distinct(client, monkeypatch):
    _activate_db_gate(monkeypatch)
    trial = licensing.issue_license(source="beta-trial")
    paid = licensing.issue_license(source="btcpay")
    trial_body = client.get(
        "/api/license-status", headers={"X-License-Key": trial}
    ).get_json()
    paid_body = client.get(
        "/api/license-status", headers={"X-License-Key": paid}
    ).get_json()
    assert trial_body["license_state"] == "trial_active"
    assert paid_body["license_state"] == "paid_active"
    assert paid_body["payment_state"] == "confirmed"


def test_unknown_key_status_is_invalid(client, monkeypatch):
    _activate_db_gate(monkeypatch)
    body = client.get(
        "/api/license-status",
        headers={"X-License-Key": "C65-ABCD-EFGH-JKMN-PQRS"},
    ).get_json()
    assert body["license_state"] == "invalid"
    assert body["pro"] is False


def test_unknown_key_invalid(monkeypatch):
    _activate_db_gate(monkeypatch)
    # A key that was never issued is invalid (clean False, never raises).
    assert licensing._key_valid("C65-ABCD-EFGH-JKMN-PQRS") is False


# ── Gate activation ──────────────────────────────────────────────────


def test_ls_config_does_not_activate_gate_without_license_delivery(monkeypatch, client):
    _ls_env(monkeypatch)
    assert licensing.licensing_configured() is False
    status = client.get("/api/license-status").get_json()
    assert status["payments"] is None
    assert status["payment_plans"] == {"pro": False, "premium": False}
    response = client.post(
        "/api/upgrade/checkout", json={"plan": "pro", "method": "card"}
    )
    assert response.status_code == 503


def test_partial_ls_config_does_not_activate_gate_or_checkout(monkeypatch, client):
    monkeypatch.setenv("LEMON_SQUEEZY_API_KEY", "partial-only")
    assert licensing.licensing_configured() is False
    status = client.get("/api/license-status").get_json()
    assert status["payments"] is None
    assert status["checkout_state"] == "unavailable"
    assert status["payment_state"] == "checkout_unavailable"
    response = client.post(
        "/api/upgrade/checkout", json={"plan": "pro", "method": "card"}
    )
    assert response.status_code == 503


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
                "store_id": 1,
                "user_email": email,
                "first_order_item": {"variant_id": variant_id},
            },
        },
    }


@pytest.fixture()
def clean_sub_db():
    """Wipe subscription_events so webhook subscription tests stay hermetic."""
    from services.db import get_db

    from services import conversion as _conv

    _conv.ensure_subscription_table()
    conn = get_db()
    conn.execute("DELETE FROM subscription_events")
    conn.commit()
    conn.close()
    yield
    conn = get_db()
    conn.execute("DELETE FROM subscription_events")
    conn.commit()
    conn.close()


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


@pytest.mark.parametrize(
    "payload",
    [
        _order_payload(order_id="", variant_id=10),
        _order_payload(order_id="bad-variant", variant_id=999),
        {
            **_order_payload(order_id="bad-store", variant_id=10),
            "data": {
                **_order_payload(order_id="bad-store", variant_id=10)["data"],
                "attributes": {
                    **_order_payload(order_id="bad-store", variant_id=10)["data"][
                        "attributes"
                    ],
                    "store_id": 999,
                },
            },
        },
    ],
)
def test_invalid_webhook_payload_never_issues_license(monkeypatch, payload):
    _ls_env(monkeypatch)
    from services.db import get_db

    conn = get_db()
    try:
        before = conn.execute("SELECT COUNT(*) AS n FROM pro_licenses").fetchone()["n"]
    finally:
        conn.close()
    assert payments.handle_webhook(payload) is None
    conn = get_db()
    try:
        after = conn.execute("SELECT COUNT(*) AS n FROM pro_licenses").fetchone()["n"]
    finally:
        conn.close()
    assert after == before


def _sub_payload(
    event_name,
    sub_id="sub_1",
    renews_at="2026-09-03T12:00:00Z",
    created_at="2026-08-03T12:00:00Z",
):
    return {
        "meta": {"event_name": event_name},
        "data": {
            "id": sub_id,
            "attributes": {"renews_at": renews_at, "created_at": created_at},
        },
    }


def test_webhook_subscription_created_records_lifecycle(monkeypatch, clean_sub_db):
    # subscription_created is acknowledged (no key issued) but recorded for
    # the real cohort LTV ledger (Issue #157).
    calls = []

    def _fake(event_name, payload):
        calls.append((event_name, payload["data"]["id"]))

    monkeypatch.setattr(payments, "_record_subscription_lifecycle", _fake)
    key = payments.handle_webhook(_sub_payload("subscription_created"))
    assert key is None  # acknowledged, never fulfills a license
    assert calls == [("subscription_created", "sub_1")]


def test_webhook_subscription_updated_records_renewal(monkeypatch, clean_sub_db):
    # subscription_updated with a (new) renews_at = a renewal for cohort LTV.
    calls = []

    def _fake(event_name, payload):
        calls.append(
            (
                event_name,
                payload["data"]["id"],
                payload["data"]["attributes"]["renews_at"],
            )
        )

    monkeypatch.setattr(payments, "_record_subscription_lifecycle", _fake)
    key = payments.handle_webhook(_sub_payload("subscription_updated"))
    assert key is None
    assert calls == [("subscription_updated", "sub_1", "2026-09-03T12:00:00Z")]


def test_webhook_subscription_lifecycle_real_records_rows(clean_sub_db, monkeypatch):
    # The REAL _record_subscription_lifecycle (not mocked): subscription_created
    # records the cohort; subscription_updated with a NEW renews_at records a
    # renewal; same renews_at (blip) is deduped; empty renews_at is skipped.
    from services.db import get_db

    from services import conversion as _conv

    _conv.ensure_subscription_table()
    # created → 1 row (cohort).
    payments.handle_webhook(_sub_payload("subscription_created"))
    # updated with the SAME period → not a renewal (echo of created period).
    payments.handle_webhook(_sub_payload("subscription_updated"))
    # updated with a NEW period → a renewal.
    payments.handle_webhook(
        _sub_payload("subscription_updated", renews_at="2026-10-03T12:00:00Z")
    )
    # updated with NO renews_at (pause/cancel) → skipped entirely.
    payments.handle_webhook(_sub_payload("subscription_updated", renews_at=""))

    conn = get_db()
    rows = conn.execute(
        "SELECT event, renews_at FROM subscription_events WHERE subscription_id='sub_1' "
        "ORDER BY id ASC"
    ).fetchall()
    conn.close()
    assert [(r["event"], r["renews_at"]) for r in rows] == [
        ("subscription_created", "2026-09-03T12:00:00Z"),
        ("renewal", "2026-10-03T12:00:00Z"),
    ]


def test_webhook_subscription_lifecycle_no_sub_id_noop(clean_sub_db):
    from services.db import get_db

    from services import conversion as _conv

    _conv.ensure_subscription_table()
    payload = {"meta": {"event_name": "subscription_created"}, "data": {"id": ""}}
    payments.handle_webhook(payload)
    conn = get_db()
    n = conn.execute("SELECT COUNT(*) AS n FROM subscription_events").fetchone()["n"]
    conn.close()
    assert n == 0


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


def test_webhook_writes_pii_safe_confirmation_and_duplicate_audit(monkeypatch):
    _ls_env(monkeypatch)
    from services.tenant import recent_audit_logs

    payload = _order_payload(email="audit-buyer@example.com", order_id="audit-7002")
    key = payments.handle_webhook(payload)
    assert key
    assert payments.handle_webhook(payload) == key
    rows = [r for r in recent_audit_logs("default", 200) if r["target"] == "audit-7002"]
    actions = [r["action"] for r in rows]
    assert actions.count("payment.confirmed") == 1
    assert actions.count("payment.webhook_duplicate") == 1
    serialized = json.dumps(rows)
    assert key not in serialized
    assert "audit-buyer@example.com" not in serialized


def test_webhook_replay_route_is_idempotent_without_exposing_key(client, monkeypatch):
    """The HTTP route dedupes and never sends a license to provider logs."""
    _ls_env(monkeypatch)
    raw = json.dumps(
        _order_payload(email="buyer@example.com", order_id="7003")
    ).encode()
    sig = _sign(raw)
    r1 = client.post(
        "/api/payments/webhook",
        data=raw,
        content_type="application/json",
        headers={"X-Signature": sig},
    )
    assert r1.status_code == 200
    assert r1.get_json() == {"ok": True, "handled": True}
    r2 = client.post(
        "/api/payments/webhook",
        data=raw,
        content_type="application/json",
        headers={"X-Signature": sig},
    )
    assert r2.status_code == 200
    assert r2.get_json() == {"ok": True, "handled": True}


def test_webhook_different_orders_issue_different_keys(monkeypatch):
    """Distinct orders still each get their own key."""
    _ls_env(monkeypatch)
    k1 = payments.handle_webhook(_order_payload(order_id="7004"))
    k2 = payments.handle_webhook(
        _order_payload(email="other@example.com", order_id="7005")
    )
    assert k1 and k2
    assert k1 != k2


def test_webhook_replay_no_duplicate_track_event(monkeypatch):
    """The funnel 'paid' event fires exactly once per order."""
    _ls_env(monkeypatch)
    calls = []
    import services.conversion as conversion_mod

    monkeypatch.setattr(
        conversion_mod, "track_event", lambda *a, **kw: calls.append(kw)
    )
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
    raw = json.dumps(
        _order_payload(email="buyer@example.com", order_id="7007")
    ).encode()
    r = client.post(
        "/api/payments/webhook",
        data=raw,
        content_type="application/json",
        headers={"X-Signature": _sign(raw)},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body == {"ok": True, "handled": True}


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
    r = client.post(
        "/api/payments/webhook", data=b"{}", content_type="application/json"
    )
    assert r.status_code == 400


# ── Checkout route ───────────────────────────────────────────────────


def test_checkout_route_503_unconfigured(client):
    r = client.post("/api/upgrade/checkout", json={"plan": "pro"})
    assert r.status_code == 503
    assert r.get_json()["code"] == "PAYMENTS_NOT_CONFIGURED"


def test_checkout_route_stays_unavailable_with_legacy_ls_env(client, monkeypatch):
    _ls_env(monkeypatch)
    monkeypatch.setattr(
        payments,
        "create_checkout",
        # Issue #155: the route now also forwards the browser funnel_id.
        lambda plan="pro", email="", funnel_id="": "https://buy.lemonsqueezy.com/x",
    )
    r = client.post("/api/upgrade/checkout", json={"plan": "pro", "method": "card"})
    assert r.status_code == 503
    assert r.get_json()["code"] == "PAYMENTS_NOT_CONFIGURED"


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


def test_license_status_does_not_advertise_legacy_card_provider(client, monkeypatch):
    _ls_env(monkeypatch)
    r = client.get("/api/license-status")
    assert r.status_code == 200
    assert r.get_json()["payments"] is None
    assert r.get_json()["checkout_state"] == "unavailable"


def test_license_status_open_mode_no_payments(client):
    r = client.get("/api/license-status")
    assert r.status_code == 200
    assert r.get_json()["payments"] is None
    assert r.get_json()["mode"] == "open"
    assert r.get_json()["license_state"] == "trial_active"
    assert r.get_json()["checkout_state"] == "unavailable"


def test_open_beta_does_not_validate_an_arbitrary_submitted_key(client):
    body = client.get(
        "/api/license-status",
        headers={"X-License-Key": "C65-FAKE-FAKE-FAKE-FAKE"},
    ).get_json()
    assert body["license_state"] == "trial_active"
    assert body["submitted_license_state"] == "invalid"
    assert body["key_valid"] is False


# ── PII redaction (Issue #116) ────────────────────────────────────────


def test_webhook_log_masks_email(caplog, monkeypatch):
    """The fulfillment log must never contain the raw buyer email."""
    _ls_env(monkeypatch)
    raw = "privacy.test@example.com"
    with caplog.at_level(logging.INFO, logger="cypher65.payments"):
        key = payments.handle_webhook(_order_payload(email=raw, order_id="8001"))
    assert key and _KEY_RE.match(key)
    assert raw not in caplog.text  # full email NEVER reaches the log
    assert "pri…@example.com" in caplog.text  # masked form present
    assert "email_sha=" in caplog.text  # correlation hash present
    from services.db import get_db

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT email FROM pro_licenses WHERE key = ?", (key,)
        ).fetchone()
    finally:
        conn.close()
    assert row["email"] == ""


def test_webhook_no_order_id_logs_without_payload(caplog, monkeypatch):
    """A malformed order_created without an order id must not dump the raw
    payload (it carries user_email) into the log — safe fields only."""
    _ls_env(monkeypatch)
    raw_email = "leaky.payload@example.com"
    payload = {
        "meta": {"event_name": "order_created"},
        "data": {"attributes": {"user_email": raw_email}},
    }
    with caplog.at_level(logging.WARNING, logger="cypher65.payments"):
        payments.handle_webhook(payload)
    assert raw_email not in caplog.text  # payload never dumped
    assert "webhook without order id — rejected" in caplog.text


def test_mask_email_edge_cases():
    m = payments.mask_email  # re-exported from helpers (single source of truth)
    assert m("alice@x.io") == "ali…@x.io"
    assert m("a@x.io") == "a@x.io"  # short local part: nothing to hide
    assert m("no-at-sign") == "no-…"  # 3-char prefix, no domain to keep
    assert m("") == "-"
    assert m(None) == "-"


def test_email_sha_matches_funnel_anonymize():
    """Webhook log hash correlates 1:1 with the funnel's email_hash."""
    from services.conversion import _anonymize

    for email in ("Buyer@Example.com", "x@y.io", ""):
        assert payments.email_sha(email) == _anonymize(email)


# ── Paywall end-to-end (11/11 validation, Issue #256) ────────────────
# Published as automated tests the one-shot local validation that confirmed
# the paywall activation before flipping PRO_KEYS_DB in production:
#   1. Open mode → /api/proximity = 200 (gate no-op).
#   2-4. PRO_KEYS_DB=1 → 402 + LICENSE_REQUIRED + PRO upgrade payload.
#   5. /api/admin/conversion exposes the funnel (admin gate local ok).
#   6-8. Every 402 tracks paywall_view; funnel_report non-empty; visitors≥1.
#   9-11. Admin-issued key unlocks PRO (X-License-Key); no key stays 402.


@pytest.fixture()
def clean_events():
    """Wipe conversion_events so paywall funnel tests stay hermetic."""
    from services import conversion as _conv

    from services.db import get_db

    _conv.ensure_table()
    conn = get_db()
    conn.execute("DELETE FROM conversion_events")
    conn.commit()
    conn.close()
    yield
    conn = get_db()
    conn.execute("DELETE FROM conversion_events")
    conn.commit()
    conn.close()


def test_paywall_open_mode_proximity_200(client):
    """Check 1 — open mode: gate is a no-op, PRO route answers 200."""
    r = client.get("/api/proximity")
    assert r.status_code == 200


def test_paywall_gate_402_payload(client, monkeypatch):
    """Checks 2-4 — PRO_KEYS_DB=1: 402 + LICENSE_REQUIRED + PRO upgrade."""
    _activate_db_gate(monkeypatch)
    r = client.get("/api/proximity")
    assert r.status_code == 402
    body = r.get_json()
    assert body["code"] == "LICENSE_REQUIRED"
    assert body["required_tier"] == "pro"
    assert "features" in body  # PRO_FEATURES list exposed for the paywall
    assert body["upgrade"]["plan"] == "PRO"
    assert body["upgrade"]["price_usd_month"] == 9


def test_paywall_402_tracks_paywall_view(client, monkeypatch, clean_events):
    """Checks 5-8 — each 402 tracks paywall_view; funnel becomes non-empty."""
    from services import conversion as _conv

    _activate_db_gate(monkeypatch)
    assert client.get("/api/proximity").status_code == 402
    assert client.get("/api/proximity").status_code == 402
    assert client.get("/api/monte_carlo").status_code == 402  # 3rd 402

    funnel = _conv.funnel_report(days=30)
    stages = funnel.get("stages") or {}
    assert stages.get("paywall_view", 0) >= 3
    assert funnel.get("visitors", 0) >= 1  # distinct tenant (anonymous here)
    assert len(stages) > 0  # funnel_report non-empty

    # Check 5 — the CFO route exposes the same funnel (admin gate: local ok).
    r = client.get("/api/admin/conversion?days=30")
    assert r.status_code == 200
    funnel_route = (r.get_json() or {}).get("funnel") or {}
    stages_route = funnel_route.get("stages") or {}
    assert stages_route.get("paywall_view", 0) >= 3


def test_paywall_issued_key_unlocks_route(client, monkeypatch):
    """Checks 9-11 — admin-issued key unlocks PRO; no key stays 402."""
    _activate_db_gate(monkeypatch)
    monkeypatch.setenv("API_KEY", "op-secret")
    r = client.post(
        "/api/admin/licenses",
        json={"plan": "pro", "days": 30, "note": "validate-paywall"},
        headers={"X-API-Key": "op-secret"},
    )
    assert r.status_code == 200
    key = r.get_json()["license_key"]
    assert _KEY_RE.match(key)

    r_ok = client.get("/api/proximity", headers={"X-License-Key": key})
    assert r_ok.status_code == 200  # valid key passes the gate

    r_no = client.get("/api/proximity")
    assert r_no.status_code == 402  # absent key still blocked
