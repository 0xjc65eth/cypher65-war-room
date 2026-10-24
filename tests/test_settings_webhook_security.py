"""Issue #857: real route regressions; all DNS and HTTP are synthetic."""

import json
import socket
import threading
from types import SimpleNamespace

from flask import Flask
import pytest
import requests
import urllib3

from routes import settings_routes as routes
from services.auth import create_token


@pytest.fixture
def channel(monkeypatch):
    monkeypatch.setenv("API_KEY", "fixture-operator-key")
    monkeypatch.setenv("TENANT_API_KEYS", json.dumps({"tenant-b": "fixture-key-b"}))
    monkeypatch.setenv("SECRET_KEY", "fixture-webhook-secret-01234567890123456789")
    app = Flask("webhook-security")
    app.config.update(TESTING=True, SECRET_KEY="fixture-session-key")
    app.register_blueprint(routes.settings_bp)
    state = SimpleNamespace(
        url="https://hooks.example.com/fixture?token=not-a-real-secret",
        addresses=["93.184.216.34"],
        status=204,
        sent=[],
        dns=[],
        pools=[],
        legacy=[],
        loads=[],
        transport_error=None,
        close_error=False,
        remote_addr="198.51.100.20",
        response_closed=False,
    )

    def settings(tenant_id=""):
        state.loads.append(tenant_id)
        return {"webhook_url": state.url}

    monkeypatch.setattr(routes, "load_settings", settings)
    monkeypatch.setattr(routes, "is_pro", lambda: True)
    monkeypatch.setattr("config.BTC_ADDRESS", "private-operator-wallet")
    monkeypatch.setattr("config.WORKER_NAME", "private-operator-worker")

    def resolve(host, port, **kwargs):
        state.dns.append((host, port))
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port))
            for ip in state.addresses
        ]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)

    class Pool:
        def __init__(self, host, **kwargs):
            self.host, self.kwargs, self.closed = host, kwargs, False
            state.pools.append(self)

        def urlopen(self, method, target, **kwargs):
            state.sent.append((method, target, kwargs))
            if state.transport_error:
                raise state.transport_error

            def close():
                state.response_closed = True
                if state.close_error:
                    raise OSError("private-operator-wallet secret cleanup details")

            return SimpleNamespace(status=state.status, close=close)

        def close(self):
            self.closed = True

    monkeypatch.setattr(urllib3, "HTTPSConnectionPool", Pool)

    def legacy_post(url, **kwargs):
        state.legacy.append((url, kwargs))
        return SimpleNamespace(status_code=state.status)

    monkeypatch.setattr(requests, "post", legacy_post)

    def headers(tenant="tenant-a", role="member"):
        with app.app_context():
            token = create_token(tenant, extra_claims={"role": role})
        return {"Authorization": "Bearer " + token}

    state.headers = headers
    state.app = app
    state.call = lambda headers=None: app.test_client().post(
        "/api/settings/test-webhook",
        headers=headers if headers is not None else state.headers(),
        environ_overrides={"REMOTE_ADDR": state.remote_addr},
    )
    return state


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/internal",
        "https://127.0.0.1/internal",
        "https://10.1.2.3/",
        "https://169.254.169.254/metadata",
        "https://[::1]/",
        "https://[::ffff:127.0.0.1]/",
        "https://[64:ff9b::7f00:1]/",
        "https://0.0.0.0/",
        "https://224.0.0.1/",
        "https://user:password@hooks.example.com/",
        "https://hooks.example.com:8443/",
        "https://hooks.example.com/#fragment",
        "https://hooks.example.com\\@localhost/",
        "https://hooks.example.com/\r\nX-Secret: value",
        "file:///etc/passwd",
        "https://bad..example.com/",
        "https://-bad.example.com/",
        "https://hooks.example.com/" + "x" * 2048,
    ],
)
def test_unsafe_url_never_reaches_any_transport(channel, url):
    channel.url = url
    response = channel.call()
    assert response.status_code == 400
    assert response.json["success"] is False
    assert not channel.sent and not channel.legacy


@pytest.mark.parametrize(
    "addresses",
    [
        [],
        ["127.0.0.1"],
        ["10.1.2.3"],
        ["169.254.169.254"],
        ["93.184.216.34", "127.0.0.1"],
        ["::ffff:10.1.2.3"],
        ["2002:7f00:1::"],
        ["not-an-ip"],
        ["93.184.216.34"] * 17,
    ],
)
def test_all_dns_answers_must_pass_public_destination_policy(channel, addresses):
    channel.addresses = addresses
    response = channel.call()
    assert response.status_code == 400
    assert not channel.sent and not channel.legacy
    assert "not-a-real-secret" not in response.get_data(as_text=True)


def test_public_delivery_pins_numeric_ip_and_preserves_tls_host(channel, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9999")
    response = channel.call()
    assert response.status_code == 200
    assert response.json == {"success": True, "status_code": 204}
    assert channel.dns == [("hooks.example.com", 443)]
    assert not channel.legacy
    pool = channel.pools[0]
    assert pool.host == "93.184.216.34"
    assert pool.kwargs["server_hostname"] == "hooks.example.com"
    assert pool.kwargs["assert_hostname"] == "hooks.example.com"
    assert pool.kwargs["cert_reqs"] == "CERT_REQUIRED"
    assert pool.kwargs["retries"] is False
    assert pool.kwargs["timeout"].connect_timeout > 0
    assert pool.kwargs["timeout"].read_timeout > 0
    method, target, kwargs = channel.sent[0]
    assert method == "POST" and target == "/fixture?token=not-a-real-secret"
    assert kwargs["headers"]["Host"] == "hooks.example.com"
    assert kwargs["redirect"] is False and kwargs["retries"] is False
    assert kwargs["preload_content"] is False
    payload = json.loads(kwargs["body"])
    assert payload["event"] == "cypher65_war_room_alert"
    assert payload["severity"] == "TEST"
    assert payload["address"] == "" and payload["worker"] == "cypher65-test"
    assert "private-operator" not in json.dumps(payload)
    assert pool.closed


@pytest.mark.parametrize("status", [301, 302, 307, 308, 400, 401, 429, 500, 503])
def test_upstream_failure_or_redirect_is_never_success_or_retried(channel, status):
    channel.status = status
    response = channel.call()
    assert response.status_code == 502
    assert response.json == {
        "success": False,
        "status_code": status,
        "error": "Webhook de teste não foi aceito pelo destino",
    }
    assert len(channel.sent) == 1 and not channel.legacy
    assert channel.pools[0].closed


def test_transport_failure_is_redacted_closed_and_not_retried(channel):
    channel.transport_error = urllib3.exceptions.ReadTimeoutError(
        None, channel.url, "private-operator-wallet secret transport details"
    )
    response = channel.call()
    assert response.status_code == 502
    assert response.json["success"] is False
    assert len(channel.sent) == 1
    assert channel.pools[0].closed
    text = response.get_data(as_text=True)
    assert "not-a-real-secret" not in text and "private-operator" not in text


@pytest.mark.parametrize(
    "headers",
    [
        {"Authorization": "Bearer invalid"},
        {"Authorization": "Basic invalid"},
        {"X-API-Key": "invalid"},
        {"X-API-Key": ""},
    ],
)
@pytest.mark.parametrize("remote_addr", ["198.51.100.20", "127.0.0.1"])
def test_explicit_bad_credentials_do_not_fall_back_to_open_localhost(
    channel, headers, remote_addr, monkeypatch
):
    channel.remote_addr = remote_addr
    monkeypatch.delenv("API_KEY")
    monkeypatch.delenv("TENANT_API_KEYS")
    response = channel.call(headers)
    assert response.status_code in (401, 403)
    assert not channel.loads and not channel.sent and not channel.legacy


def test_conflicting_valid_credentials_are_rejected_before_settings(channel):
    headers = {**channel.headers("tenant-a"), "X-API-Key": "fixture-key-b"}
    response = channel.call(headers)
    assert response.status_code == 401
    assert not channel.loads and not channel.sent and not channel.legacy


def test_viewer_and_anonymous_remote_cannot_trigger_delivery(channel):
    for headers in [channel.headers(role="viewer"), {}]:
        assert channel.call(headers).status_code == 403
    assert not channel.loads and not channel.sent and not channel.legacy


def test_non_ascii_key_cannot_bypass_or_crash_the_identity_boundary(channel):
    headers = {**channel.headers(), "X-API-Key": "é"}
    assert channel.call(headers).status_code == 401
    assert not channel.loads and not channel.sent and not channel.legacy


def test_empty_legacy_session_tenant_does_not_fall_back_to_operator(channel):
    client = channel.app.test_client()
    with client.session_transaction() as session:
        session.update(authenticated=True, tenant_id="", role="admin")
    response = client.post("/api/settings/test-webhook")
    assert response.status_code == 401
    assert not channel.loads and not channel.sent and not channel.legacy


def test_explicit_viewer_stays_read_only_in_open_mode(channel, monkeypatch):
    monkeypatch.delenv("API_KEY")
    monkeypatch.delenv("TENANT_API_KEYS")
    assert channel.call(channel.headers(role="viewer")).status_code == 403
    assert not channel.loads and not channel.sent and not channel.legacy


def test_valid_bearer_does_not_mix_with_another_tenants_session(channel):
    client = channel.app.test_client()
    with client.session_transaction() as session:
        session.update(authenticated=True, tenant_id="tenant-b", role="admin")
    response = client.post("/api/settings/test-webhook", headers=channel.headers())
    assert response.status_code == 401
    assert not channel.loads and not channel.sent and not channel.legacy


def test_cleanup_failure_does_not_skip_pool_close_or_expose_details(channel):
    channel.close_error = True
    response = channel.call()
    assert response.status_code == 200
    assert response.json == {"success": True, "status_code": 204}
    assert channel.response_closed and channel.pools[0].closed
    assert "private-operator" not in response.get_data(as_text=True)


def test_public_ip_literal_is_pinned_without_a_hostname_resolution(channel):
    channel.url = "https://93.184.216.34/fixture"
    assert channel.call().status_code == 200
    assert channel.dns == []
    assert channel.pools[0].host == "93.184.216.34"


@pytest.mark.parametrize("identity", ["key", "both"])
def test_valid_key_and_matching_identity_only_load_the_callers_settings(
    channel, identity
):
    headers = {"X-API-Key": "fixture-key-b"}
    if identity == "both":
        headers.update(channel.headers("tenant-b"))
    assert channel.call(headers).status_code == 200
    assert channel.loads == ["tenant-b"]
    assert len(channel.sent) == 1 and not channel.legacy


def test_dns_error_is_unavailable_without_transport_or_secret_error(
    channel, monkeypatch
):
    def fail(*args, **kwargs):
        raise socket.gaierror("private-operator-wallet secret resolver details")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    response = channel.call()
    assert response.status_code == 502
    assert not channel.sent and not channel.legacy
    assert "private-operator" not in response.get_data(as_text=True)


def test_dns_timeout_and_capacity_are_bounded(channel, monkeypatch):
    from services import webhook_delivery as delivery

    started, release, done = threading.Event(), threading.Event(), threading.Event()
    capacity = threading.BoundedSemaphore(1)
    monkeypatch.setattr(delivery, "_DNS_CAPACITY", capacity)
    monkeypatch.setattr(delivery, "DNS_TIMEOUT_SECONDS", 0.02)

    def delayed(*args, **kwargs):
        started.set()
        try:
            release.wait(timeout=1)
            return [
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    ("93.184.216.34", 443),
                )
            ]
        finally:
            done.set()

    monkeypatch.setattr(socket, "getaddrinfo", delayed)
    try:
        assert channel.call().status_code == 502
        assert started.is_set()
        assert channel.call().status_code == 502
        assert not channel.sent and not channel.legacy
        assert not capacity.acquire(blocking=False)
    finally:
        release.set()
        assert done.wait(timeout=1)


def test_thread_start_failure_releases_capacity(channel, monkeypatch):
    from services import webhook_delivery as delivery

    capacity = threading.BoundedSemaphore(1)
    monkeypatch.setattr(delivery, "_DNS_CAPACITY", capacity)

    def fail(self):
        raise RuntimeError("private-operator-wallet secret thread details")

    monkeypatch.setattr(threading.Thread, "start", fail)
    assert channel.call().status_code == 502
    assert capacity.acquire(blocking=False)
    assert not channel.sent and not channel.legacy
