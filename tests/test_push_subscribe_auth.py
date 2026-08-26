"""Tests for the hardened /api/push/subscribe (Issue #115).

Security contract locked here:
  - A non-empty tenant comes ONLY from a valid Bearer JWT (sub). The request
    body can never choose a tenant.
  - An invalid/forged JWT is refused with 401 (no silent fallback to the
    operator's '' tenant — the exact vector the issue closes).
  - Anonymous visitors may ONLY subscribe under '' with a well-formed
    https:// endpoint, and are rate-limited per IP (10/min).
  - A valid JWT stores the subscription under its OWN tenant (the caller can
    never write into another tenant's channel).
  - Malformed endpoints (http://, javascript:, data:, too-long) are rejected.

HERMETIC — uses the app's test client + scratch DB (conftest redirects
DB_PATH); the generic rate limiter is disabled in TESTING mode but the
push-specific anonymous budget is checked inside the route, so it is
exercised here directly.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from services import auth as _auth
from services.push_notifier import get_subscriptions_for_tenant

_GOOD_ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc123"


@pytest.fixture(autouse=True)
def _scrub_env(monkeypatch):
    """Deterministic JWT secret so the JWT is verifiable.

    Uses monkeypatch.setitem so the config key is auto-restored at teardown
    — a direct assignment would leak app.config["JWT_SECRET_KEY"] into later
    test files in the same process (exact footgun test_tenant_auth.py
    documents: cross-file pollution broke test_rbac_register.py).
    """
    monkeypatch.setenv("SECRET_KEY", "push-subscribe-test-secret-0123456789abcdef")
    monkeypatch.setitem(app.config, "JWT_SECRET_KEY", "push-subscribe-test-secret-0123456789abcdef")


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    yield app.test_client()


def _post(client, endpoint=_GOOD_ENDPOINT, token=None, extra=None, headers=None):
    body = {"endpoint": endpoint, "keys": {"p256dh": "x", "auth": "y"}}
    if extra:
        body.update(extra)
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    if token:
        h["Authorization"] = "Bearer " + token
    return client.post("/api/push/subscribe", data=json.dumps(body),
                       content_type="application/json", headers=h)


# ── Anonymous path (operator tenant '') ─────────────────────────────────

def test_anonymous_https_endpoint_subscribes_under_operator(client):
    r = _post(client)
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    assert r.get_json()["tenant"] == "default"  # '' displayed as default
    assert get_subscriptions_for_tenant("")  # stored under the operator tenant


def test_anonymous_http_endpoint_rejected(client):
    r = _post(client, endpoint="http://insecure.example/x")
    assert r.status_code == 400
    assert "https" in r.get_json()["error"]


def test_anonymous_javascript_endpoint_rejected(client):
    r = _post(client, endpoint="javascript:alert(1)")
    assert r.status_code == 400


def test_anonymous_missing_endpoint_rejected(client):
    r = _post(client, endpoint="")
    assert r.status_code == 400


def test_anonymous_overlong_endpoint_rejected(client):
    r = _post(client, endpoint="https://x.example/" + "a" * 3000)
    assert r.status_code == 400


def test_anonymous_rate_limited_per_ip(client):
    """>10 anonymous subscriptions from one IP in a minute → 429.

    Uses a distinct REMOTE_ADDR so the bucket is deterministic regardless of
    how many anonymous https posts ran before (the shared 127.0.0.1 bucket
    is pre-polluted by earlier tests in this file).
    """
    h = {"X-Forwarded-For": "203.0.113.77"}
    code = 200
    for _ in range(11):
        r = client.post(
            "/api/push/subscribe",
            data=json.dumps({"endpoint": _GOOD_ENDPOINT, "keys": {}}),
            content_type="application/json",
            headers=h,
            environ_base={"REMOTE_ADDR": "203.0.113.77"},
        )
        code = r.status_code
    assert code == 429
    assert r.get_json()["error"] == "rate limited"


# ── JWT path (non-empty tenant from sub ONLY) ──────────────────────────

def test_valid_jwt_subscribes_under_own_tenant(client):
    # Sub ≤ 8 chars so the response's display-truncated tenant matches.
    # DISTINCT endpoint from the anonymous tests — save_subscription upserts
    # ON CONFLICT(endpoint), so reusing _GOOD_ENDPOINT would move the row to
    # 'acme' and fake the isolation assertion via the upsert, not via tenant
    # scoping.
    token = _auth.create_token(subject="acme")
    r = _post(client, endpoint=_GOOD_ENDPOINT + "/acme", token=token)
    assert r.status_code == 200
    assert r.get_json()["tenant"] == "acme"
    assert get_subscriptions_for_tenant("acme")
    # NOT stored under the operator tenant.
    assert _GOOD_ENDPOINT + "/acme" not in [s.get("endpoint") for s in get_subscriptions_for_tenant("")]


def test_invalid_jwt_refused_401(client):
    r = _post(client, token="forged.token.value")
    assert r.status_code == 401
    assert r.get_json()["error"] == "invalid token"


def test_expired_jwt_refused_401(client):
    token = _auth.create_token(subject="tenant-old", ttl=-10)  # already expired
    r = _post(client, token=token)
    assert r.status_code == 401


def test_body_cannot_spoof_tenant(client):
    """Even with a tenant field in the body, the JWT sub is authoritative."""
    token = _auth.create_token(subject="acme")
    r = _post(client, token=token, extra={"tenant_id": "tenant-victim"})
    assert r.status_code == 200
    assert r.get_json()["tenant"] == "acme"
    assert not get_subscriptions_for_tenant("tenant-victim")


def test_jwt_path_not_rate_limited_by_anonymous_budget(client):
    """Authenticated users get their own bucket — 15 rapid subscribes pass."""
    token = _auth.create_token(subject="busy")
    for _ in range(15):
        r = _post(client, token=token,
                  endpoint=_GOOD_ENDPOINT + str(_))
        assert r.status_code == 200
