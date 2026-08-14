"""
CYPHER65 // request_id correlation middleware (Issue #124)
===========================================================
Hermetic route-level tests for the X-Request-ID contract:

  1. Every response carries an X-Request-ID header (minted when absent).
  2. A client-supplied X-Request-ID is honored (sanitized, capped at 64).
  3. Injection-shaped headers are stripped to safe chars.
  4. Different requests get different ids (correlation, not a global).

Uses the same client fixture pattern as test_settings_test_alert.py and the
shared scratch DB from conftest (never touches data/war_room.sqlite).
"""
import re

import pytest

import app as _app_module

app = _app_module.app


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


_SAFE = re.compile(r"^[A-Za-z0-9_-]+$")


def test_every_response_carries_minted_x_request_id(client):
    r = client.get("/api/healthz")
    assert r.status_code == 200
    rid = r.headers.get("X-Request-ID")
    assert rid
    assert rid.startswith("req-")      # minted server-side
    assert len(rid) == len("req-") + 12


def test_client_supplied_id_is_honored(client):
    r = client.get("/api/healthz", headers={"X-Request-ID": "my-trace-123"})
    assert r.headers.get("X-Request-ID") == "my-trace-123"


def test_injected_header_is_sanitized(client):
    r = client.get("/api/healthz",
                   headers={"X-Request-ID": "bad chars<script>alert(1)</script>"})
    rid = r.headers.get("X-Request-ID")
    assert _SAFE.match(rid)              # only [A-Za-z0-9_-] survive
    assert rid == "badcharsscriptalert1script"  # whitespace + <> stripped


def test_overlong_header_is_capped_at_64(client):
    r = client.get("/api/healthz", headers={"X-Request-ID": "A" * 300})
    assert len(r.headers.get("X-Request-ID")) <= 64


def test_different_requests_get_different_ids(client):
    r1 = client.get("/api/healthz")
    r2 = client.get("/api/healthz")
    rid1 = r1.headers.get("X-Request-ID")
    rid2 = r2.headers.get("X-Request-ID")
    assert rid1 and rid2 and rid1 != rid2
