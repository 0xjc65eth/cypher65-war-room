"""Issue #860: production notifier/queue/probe with synthetic DNS and HTTP only."""

import json
import socket
import sqlite3
import time
from contextlib import closing
from types import SimpleNamespace

from flask import Flask
import pytest
import requests
import urllib3

from routes import settings_routes
from services import push_notifier as notifier
from services import user_polling, webhook_queue
from services.auth import create_token
from services.db import get_db
from services.webhook_delivery import WebhookDeliveryError, deliver_webhook


@pytest.fixture
def wire(monkeypatch):
    state = SimpleNamespace(
        addresses=["93.184.216.34"], status=204, sent=[], pools=[], dns=[], error=None
    )

    def resolve(host, port, **kwargs):
        state.dns.append((host, port))
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port))
            for ip in state.addresses
        ]

    class Pool:
        def __init__(self, host, **kwargs):
            self.host, self.options, self.closed = host, kwargs, False
            state.pools.append(self)

        def urlopen(self, method, target, **kwargs):
            state.sent.append((target, kwargs))
            if state.error:
                raise state.error
            return SimpleNamespace(status=state.status, close=lambda: None)

        def close(self):
            self.closed = True

    def forbidden(*args, **kwargs):
        pytest.fail("legacy requests transport must never be used")

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(urllib3, "HTTPSConnectionPool", Pool)
    monkeypatch.setattr(requests, "post", forbidden)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setattr(settings_routes, "is_pro", lambda: True)
    monkeypatch.setattr(notifier, "notify_tenant_alert", lambda *args, **kwargs: 0)
    webhook_queue.ensure_table()
    with closing(get_db()) as conn:
        conn.execute("DELETE FROM webhook_queue")
        conn.commit()

    app = Flask("live-webhook-fixture")
    app.config.update(TESTING=True, SECRET_KEY="fixture-live-webhook-secret")
    app.register_blueprint(settings_routes.settings_bp)
    with app.app_context():
        token = create_token("fixture-tenant", extra_claims={"role": "member"})

    def auto_probe(url):
        monkeypatch.setattr(
            settings_routes, "load_settings", lambda **kwargs: {"webhook_url": url}
        )
        return app.test_client().post(
            "/api/settings/test-auto-exclude-alert",
            headers={"Authorization": "Bearer " + token},
        )

    state.auto_probe = auto_probe
    return state


def send(url):
    return notifier.send_webhook_notification(
        url, "WARN", "fixture", "Synthetic alert", ts=1
    )


@pytest.mark.parametrize(
    "url,kind",
    [
        ("https://discord.com/api/webhooks/fixture/token", "discord"),
        ("https://api.telegram.org/botFIXTURE/sendMessage?chat_id=42", "telegram"),
        ("https://hooks.example.com/fixture", "generic"),
        ("https://discord.com.evil.example/fixture", "generic"),
        ("https://hooks.example.com/discord.com?api.telegram.org", "generic"),
    ],
)
def test_exact_provider_host_and_shared_pinned_transport(wire, url, kind):
    assert send(url) is True
    assert len(wire.sent) == len(wire.dns) == 1
    pool = wire.pools[0]
    assert pool.host == "93.184.216.34" and pool.closed
    assert pool.options["server_hostname"] == wire.dns[0][0]
    assert pool.options["assert_hostname"] == wire.dns[0][0]
    assert pool.options["cert_reqs"] == "CERT_REQUIRED"
    assert pool.options["retries"] is False
    options = wire.sent[0][1]
    assert options["redirect"] is False and options["retries"] is False
    assert options["preload_content"] is False
    payload = json.loads(options["body"])
    if kind == "discord":
        assert "embeds" in payload
    elif kind == "telegram":
        assert payload["chat_id"] == "42" and payload["parse_mode"] == "MarkdownV2"
    else:
        assert payload["event"] == "cypher65_war_room_alert"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "https://127.0.0.1/",
        "https://10.0.0.1/",
        "https://169.254.169.254/",
        "https://[::1]/",
        "https://[::ffff:127.0.0.1]/",
        "https://user:secret@hooks.example.com/",
        "https://hooks.example.com:444/",
    ],
)
@pytest.mark.parametrize("caller", ["direct", "dispatch", "retry", "auto-probe"])
def test_every_live_path_rejects_unsafe_destination(wire, url, caller):
    kwargs = dict(url=url, severity="WARN", category="fixture", message="Synthetic")
    if caller == "direct":
        assert send(url) is False
    elif caller == "dispatch":
        assert webhook_queue.dispatch_webhook_or_queue(**kwargs) is False
    elif caller == "retry":
        assert webhook_queue.enqueue_webhook(kwargs, delay_secs=0)
        assert webhook_queue.process_due_webhooks(now=int(time.time()) + 1) == 1
    else:
        response = wire.auto_probe(url)
        assert response.status_code == 200 and response.json["webhook_ok"] is False
    assert wire.sent == [] and wire.pools == []


@pytest.mark.parametrize(
    "addresses",
    [
        [],
        ["10.0.0.1"],
        ["93.184.216.34", "127.0.0.1"],
        ["2002:7f00:1::"],
        ["64:ff9b::7f00:1"],
    ],
)
def test_mixed_or_unsafe_dns_never_reaches_live_transport(wire, addresses):
    wire.addresses = addresses
    assert send("https://hooks.example.com/") is False
    assert wire.sent == []


@pytest.mark.parametrize("status", [200, 204, 299, 301, 302, 307, 308, 400, 429, 500])
def test_live_http_outcomes_are_honest_and_never_inline_retried(wire, status):
    wire.status = status
    assert send("https://hooks.example.com/secret?token=fixture") is (
        200 <= status < 300
    )
    assert len(wire.sent) == 1


def test_transport_exception_redacted_and_queued_retry_revalidates_dns(wire, caplog):
    wire.error = OSError("https://hooks.example.com/SECRET-TOKEN?key=SECRET-QUERY")
    kwargs = dict(
        url="https://hooks.example.com/SECRET-TOKEN",
        severity="WARN",
        category="fixture",
        message="Synthetic",
    )
    assert webhook_queue.dispatch_webhook_or_queue(**kwargs) is False
    assert len(wire.sent) == 1
    wire.error = None
    wire.addresses = ["127.0.0.1"]
    assert webhook_queue.process_due_webhooks(now=int(time.time()) + 100) == 1
    assert len(wire.sent) == 1 and len(wire.dns) == 2
    assert "SECRET-TOKEN" not in caplog.text and "SECRET-QUERY" not in caplog.text


@pytest.mark.parametrize(
    "timeout", [0, -1, True, None, "5", float("nan"), float("inf"), 6, 10**1000]
)
def test_phase_timeout_is_validated_before_dns_or_transport(wire, timeout):
    with pytest.raises(WebhookDeliveryError, match="invalid_timeout"):
        deliver_webhook("https://hooks.example.com/", {}, timeout=timeout)
    assert wire.dns == [] and wire.sent == []


def test_async_exception_does_not_blindly_replay_post(wire, monkeypatch, caplog):
    calls = []

    def partial_dispatch(**kwargs):
        calls.append(kwargs)
        raise OSError("SECRET-PROVIDER-DETAIL")

    class InlineThread:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(webhook_queue, "dispatch_webhook_or_queue", partial_dispatch)
    monkeypatch.setattr(user_polling.threading, "Thread", InlineThread)
    user_polling._fire_webhook_async(
        {
            "url": "https://hooks.example.com/",
            "severity": "WARN",
            "category": "fixture",
            "message": "Synthetic",
        }
    )
    assert len(calls) == 1 and not wire.sent
    assert "SECRET-PROVIDER-DETAIL" not in caplog.text


@pytest.mark.parametrize("tenant", ["fixture-tenant", "default", ""])
def test_retry_drops_unverifiable_named_tenant_identity_in_legacy_rows(wire, tenant):
    assert webhook_queue.enqueue_webhook(
        dict(
            url="https://hooks.example.com/",
            severity="WARN",
            category="fixture",
            message="Synthetic",
            worker="legacy-operator-worker",
            address="legacy-operator-wallet",
        ),
        tenant_id=tenant,
        delay_secs=0,
    )
    assert webhook_queue.process_due_webhooks(now=int(time.time()) + 1) == 1
    payload = json.loads(wire.sent[0][1]["body"])
    assert payload["worker"] == (
        "" if tenant == "fixture-tenant" else "legacy-operator-worker"
    )
    assert payload["address"] == (
        "" if tenant == "fixture-tenant" else "legacy-operator-wallet"
    )


def test_queue_database_failures_do_not_log_secret_exception_details(
    wire, monkeypatch, caplog
):
    def unavailable():
        raise sqlite3.OperationalError("SECRET-URL?token=fixture")

    monkeypatch.setattr(webhook_queue, "get_db", unavailable)
    webhook_queue.ensure_table()
    assert webhook_queue.enqueue_webhook({"url": "https://hooks.example.com/"}) is False
    assert webhook_queue.process_due_webhooks() == 0
    assert "SECRET-URL" not in caplog.text


def test_malformed_retry_payload_is_redacted_and_advances_attempt(wire, caplog):
    with closing(get_db()) as conn:
        conn.execute(
            "INSERT INTO webhook_queue (payload, attempts, next_retry_ts, created_at) "
            "VALUES (?, 0, 0, 0)",
            ("SECRET-INVALID-JSON",),
        )
        conn.commit()
    assert webhook_queue.process_due_webhooks(now=int(time.time()) + 1) == 1
    with closing(get_db()) as conn:
        assert conn.execute("SELECT attempts FROM webhook_queue").fetchone()[0] == 1
    assert "SECRET-INVALID-JSON" not in caplog.text and not wire.sent


def test_queue_loop_failure_logs_only_fixed_outcome(wire, monkeypatch, caplog):
    class StopLoop(BaseException):
        pass

    def failure():
        raise OSError("SECRET-LOOP-DETAIL")

    def stop(interval):
        raise StopLoop()

    monkeypatch.setattr(webhook_queue, "process_due_webhooks", failure)
    monkeypatch.setattr(webhook_queue.time, "sleep", stop)
    with pytest.raises(StopLoop):
        webhook_queue.webhook_queue_loop()
    assert "SECRET-LOOP-DETAIL" not in caplog.text
