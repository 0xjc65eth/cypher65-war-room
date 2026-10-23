"""Contract, isolation and finite-math regression tests for Issue #836."""

import json
import sqlite3
import time
from unittest.mock import Mock

import pytest
from flask import Flask
from jinja2 import DictLoader

from axe_fleet.registry import DeviceRegistry
from routes.mini_war_room import create_mini_war_room_blueprint
from services.auth import create_refresh_token, create_token, revoke_token
from services.mini_war_room import build_mini_snapshot

NOW = 1_800_000_000


def row(status="ONLINE", timestamp=NOW, **metrics):
    return {
        "status": status,
        "telemetry": {"ts": timestamp, **metrics},
        "name": "PRIVATE-DEVICE",
        "ip_address": "192.0.2.99",
        "wallet": "PRIVATE-WALLET",
        "id": "PRIVATE-ID",
        "commands": ["restart"],
    }


def complete(**changes):
    return row(hashrate_hs=100, power_watts=20, temperature=40, **changes)


def test_empty_allowlist_contract():
    result = build_mini_snapshot([], now=NOW)
    assert set(result) == {
        "schema_version",
        "generated_at",
        "stale_after_s",
        "state",
        "counts",
        "metrics",
    }
    assert result["schema_version"] == 1
    assert result["state"] == "empty"
    assert set(result["metrics"]) == {"hashrate", "power", "temperature"}
    for metric in result["metrics"].values():
        assert set(metric) == {
            "value",
            "unit",
            "contributors",
            "oldest_observed_at",
            "newest_observed_at",
            "age_s",
            "source",
            "window_s",
            "aggregation",
        }
        assert metric["value"] is None
        assert metric["contributors"] == 0
        assert metric["oldest_observed_at"] is None
        assert metric["newest_observed_at"] is None
        assert metric["age_s"] is None
        assert metric["source"] == "fleet_telemetry"
        assert metric["window_s"] is None


def test_current_aggregates_units_times_no_sensitive_fields():
    result = build_mini_snapshot(
        [
            complete(timestamp=NOW - 90),
            row("HASHING", NOW - 10, hashrate_hs=200, power_watts=30, temperature=42),
        ],
        now=NOW,
    )
    assert result["state"] == "current"
    assert result["counts"] == {
        "total": 2,
        "current": 2,
        "stale": 0,
        "offline": 0,
        "unknown": 0,
    }
    for key, value, unit in (
        ("hashrate", 300, "H/s"),
        ("power", 50, "W"),
        ("temperature", 42, "°C"),
    ):
        metric = result["metrics"][key]
        assert metric["value"] == value
        assert metric["unit"] == unit
        assert metric["contributors"] == 2
        assert metric["oldest_observed_at"] == NOW - 90
        assert metric["newest_observed_at"] == NOW - 10
        assert metric["age_s"] == 90
    encoded = json.dumps(result)
    for forbidden in (
        "PRIVATE",
        "192.0.2",
        "wallet",
        "commands",
        "restart",
        "ip_address",
    ):
        assert forbidden not in encoded


@pytest.mark.parametrize("status", ["ONLINE", "HASHING", "IDLE"])
def test_measured_zero_is_valid(status):
    result = build_mini_snapshot(
        [row(status, hashrate_hs=0, power_watts=0, temperature=0)], now=NOW
    )
    assert result["state"] == "current"
    assert all(metric["value"] == 0 for metric in result["metrics"].values())


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        -1,
        "10",
        float("nan"),
        float("inf"),
        -float("inf"),
        10**1000,
        {},
        [],
    ],
)
def test_invalid_values_never_become_zero(value):
    result = build_mini_snapshot(
        [row(hashrate_hs=value, power_watts=value, temperature=value)], now=NOW
    )
    assert result["state"] == "unknown"
    assert result["counts"]["unknown"] == 1
    assert all(metric["value"] is None for metric in result["metrics"].values())


@pytest.mark.parametrize(
    "timestamp", [None, 0, -1, True, "1800000000", NOW + 1, float("nan"), float("inf")]
)
def test_invalid_or_future_timestamp_is_unknown(timestamp):
    result = build_mini_snapshot([complete(timestamp=timestamp)], now=NOW)
    assert result["state"] == "unknown"
    assert result["metrics"]["hashrate"]["value"] is None


@pytest.mark.parametrize(
    "age,expected",
    [(899, "current"), (900, "current"), (900.001, "stale"), (901, "stale")],
)
def test_freshness_boundary(age, expected):
    result = build_mini_snapshot([complete(timestamp=NOW - age)], now=NOW)
    assert result["state"] == expected
    assert result["counts"][expected] == 1


@pytest.mark.parametrize(
    "status,expected",
    [
        ("OFFLINE", "offline"),
        ("PAUSED", "offline"),
        ("STALE", "stale"),
        ("UNKNOWN", "unknown"),
        (None, "unknown"),
        ({}, "unknown"),
        ("online", "unknown"),
    ],
)
def test_noncurrent_status_excludes_fresh_values(status, expected):
    result = build_mini_snapshot([complete(status=status)], now=NOW)
    assert result["state"] == expected
    assert result["metrics"]["hashrate"]["value"] is None


def test_partial_per_metric_counts_not_full_fleet_capacity():
    result = build_mini_snapshot(
        [
            complete(),
            row(hashrate_hs=30),
            complete(status="OFFLINE"),
            complete(timestamp=NOW - 901),
            {},
            None,
        ],
        now=NOW,
    )
    assert result["state"] == "partial"
    assert result["counts"] == {
        "total": 6,
        "current": 2,
        "offline": 1,
        "stale": 1,
        "unknown": 2,
    }
    assert result["metrics"]["hashrate"]["value"] == 130
    assert result["metrics"]["hashrate"]["contributors"] == 2
    assert result["metrics"]["power"]["value"] == 20
    assert result["metrics"]["power"]["contributors"] == 1


def test_overflow_is_unavailable_not_infinity():
    result = build_mini_snapshot(
        [
            row(hashrate_hs=1e308, power_watts=1e308, temperature=40),
            row(hashrate_hs=1e308, power_watts=1e308, temperature=50),
        ],
        now=NOW,
    )
    assert result["state"] == "partial"
    assert result["metrics"]["hashrate"]["value"] is None
    assert result["metrics"]["power"]["value"] is None
    assert result["metrics"]["temperature"]["value"] == 50
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("now", [0, -1, True, float("inf"), float("nan")])
def test_invalid_server_clock_fails_closed(now):
    with pytest.raises(ValueError):
        build_mini_snapshot([complete()], now=now)


def test_default_clock_and_missing_nonmapping_telemetry(monkeypatch):
    monkeypatch.setattr("services.mini_war_room.time.time", lambda: NOW)
    result = build_mini_snapshot(
        [{"status": "ONLINE"}, {"status": "ONLINE", "telemetry": []}, complete()]
    )
    assert result["generated_at"] == NOW
    assert result["counts"]["unknown"] == 2
    assert result["metrics"]["hashrate"]["value"] == 100


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("TENANT_API_KEYS", raising=False)
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test-mini-key-at-least-32-characters")
    app.jinja_loader = DictLoader({"mini_war_room.html": "shell {{ presentation }}"})
    registry = Mock()
    registry.list_devices.return_value = []
    app.register_blueprint(create_mini_war_room_blueprint(lambda: registry))
    return app, app.test_client(), registry


def assert_private(response):
    assert response.headers["Cache-Control"] == "no-store, private, max-age=0"
    assert response.headers["Pragma"] == "no-cache"
    assert {"Authorization", "Cookie", "X-API-Key", "*"} <= set(response.vary)


def test_open_mode_default_scope_and_public_shell(harness):
    _, client, registry = harness
    response = client.get("/api/mini-war-room")
    assert response.status_code == 200
    assert_private(response)
    registry.list_devices.assert_called_once_with(
        tenant_id="default", with_telemetry=True
    )
    for presentation in ("monitor", "obs"):
        response = client.get(
            "/mini-war-room", query_string={"presentation": presentation}
        )
        assert response.status_code == 200
        assert response.text == "shell " + presentation
        assert_private(response)


@pytest.mark.parametrize(
    "header,value",
    [
        ("Authorization", "Bearer invalid"),
        ("Authorization", "Basic invalid"),
        ("Authorization", ""),
        ("X-API-Key", "bad"),
        ("X-API-Key", ""),
    ],
)
@pytest.mark.parametrize("configured", [True, False])
def test_invalid_explicit_credentials_cannot_downgrade_local_or_session(
    harness, monkeypatch, header, value, configured
):
    _, client, registry = harness
    if configured:
        monkeypatch.setenv("API_KEY", "valid-owner-key")
    with client.session_transaction() as session:
        session.update(authenticated=True, tenant_id="tenant-session", role="admin")
    response = client.get("/api/mini-war-room", headers={header: value})
    assert response.status_code == 401
    assert_private(response)
    registry.list_devices.assert_not_called()


def test_remote_anonymous_denied_configured_and_viewer_allowed(harness, monkeypatch):
    app, client, registry = harness
    monkeypatch.setenv("API_KEY", "owner-key")
    response = client.get(
        "/api/mini-war-room", environ_base={"REMOTE_ADDR": "198.51.100.2"}
    )
    assert response.status_code == 403
    assert_private(response)
    registry.list_devices.assert_not_called()
    with app.app_context():
        token = create_token("tenant-viewer", extra_claims={"role": "viewer"})
    response = client.get(
        "/api/mini-war-room", headers={"Authorization": "Bearer " + token}
    )
    assert response.status_code == 200
    registry.list_devices.assert_called_once_with(
        tenant_id="tenant-viewer", with_telemetry=True
    )


@pytest.mark.parametrize(
    "kind", ["expired", "refresh", "revoked", "empty-sub", "bad-role"]
)
def test_invalid_token_kind_role_cannot_read(harness, monkeypatch, kind):
    app, client, registry = harness
    monkeypatch.setenv("API_KEY", "owner-key")
    with app.app_context():
        if kind == "refresh":
            token, _ = create_refresh_token("tenant-a")
        else:
            token = create_token(
                "" if kind == "empty-sub" else "tenant-a",
                ttl=-100 if kind == "expired" else 3600,
                extra_claims={"role": "invalid" if kind == "bad-role" else "viewer"},
            )
        if kind == "revoked":
            revoke_token(token)
    response = client.get(
        "/api/mini-war-room", headers={"Authorization": "Bearer " + token}
    )
    assert response.status_code == (403 if kind == "bad-role" else 401)
    assert_private(response)
    registry.list_devices.assert_not_called()


def test_api_keys_scope_and_conflicting_bearer_rejected(harness, monkeypatch):
    app, client, registry = harness
    monkeypatch.setenv(
        "TENANT_API_KEYS", json.dumps({"tenant-a": "key-a", "tenant-b": "key-b"})
    )
    response = client.get("/api/mini-war-room", headers={"X-API-Key": "key-a"})
    assert response.status_code == 200
    registry.list_devices.assert_called_once_with(
        tenant_id="tenant-a", with_telemetry=True
    )
    registry.reset_mock()
    with app.app_context():
        token = create_token("tenant-b", extra_claims={"role": "viewer"})
    response = client.get(
        "/api/mini-war-room",
        headers={"X-API-Key": "key-a", "Authorization": "Bearer " + token},
    )
    assert response.status_code == 401
    registry.list_devices.assert_not_called()


def test_session_tenant_isolation(harness, monkeypatch):
    _, client, registry = harness
    monkeypatch.setenv("API_KEY", "owner-key")
    with client.session_transaction() as session:
        session.update(authenticated=True, tenant_id="tenant-session", role="viewer")
    response = client.get(
        "/api/mini-war-room", environ_base={"REMOTE_ADDR": "198.51.100.2"}
    )
    assert response.status_code == 200
    registry.list_devices.assert_called_once_with(
        tenant_id="tenant-session", with_telemetry=True
    )


def test_empty_session_tenant_never_selects_all_registry_rows(harness):
    _, client, registry = harness
    with client.session_transaction() as session:
        session.update(authenticated=True, tenant_id="", role="viewer")
    response = client.get("/api/mini-war-room")
    assert response.status_code == 401
    assert_private(response)
    registry.list_devices.assert_not_called()


def test_valid_bearer_with_invalid_explicit_api_key_is_denied(harness):
    app, client, registry = harness
    with app.app_context():
        token = create_token("tenant-a", extra_claims={"role": "viewer"})
    response = client.get(
        "/api/mini-war-room",
        headers={"Authorization": "Bearer " + token, "X-API-Key": "bad"},
    )
    assert response.status_code == 401
    registry.list_devices.assert_not_called()


def test_missing_registry_fails_private_without_exception_details(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("TENANT_API_KEYS", raising=False)
    app = Flask(__name__)
    app.config.update(TESTING=True)
    app.register_blueprint(create_mini_war_room_blueprint(lambda: None))
    response = app.test_client().get("/api/mini-war-room")
    assert response.status_code == 503
    assert response.json == {"error": "fleet telemetry unavailable"}
    assert_private(response)


def test_unavailable_and_405_are_private_no_secret_events(harness, monkeypatch):
    _, client, registry = harness
    event = Mock()
    monkeypatch.setattr("routes.mini_war_room.emit_event", event)
    registry.list_devices.side_effect = RuntimeError("PRIVATE-WALLET PASSWORD")
    response = client.get("/api/mini-war-room")
    assert response.status_code == 503
    assert_private(response)
    assert "PRIVATE" not in response.text
    event.assert_called_once_with("mini_snapshot_unavailable", outcome="unavailable")
    for path in ("/mini-war-room", "/api/mini-war-room"):
        response = client.post(path)
        assert response.status_code == 405
        assert_private(response)
    response = client.get("/mini-war-room?presentation=bad")
    assert response.status_code == 400
    assert_private(response)


def test_actual_sqlite_registry_tenant_and_tombstone_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "TENANT_API_KEYS", json.dumps({"tenant-a": "key-a", "tenant-b": "key-b"})
    )
    db_path = tmp_path / "fleet.sqlite"

    def connection():
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        return db

    registry = DeviceRegistry(connection)
    registry.ensure_tables()
    now = int(time.time())
    db = connection()
    for device_id, tenant, rate, removed in (
        ("a", "tenant-a", 10, 0),
        ("b", "tenant-b", 9999, 0),
        ("removed", "tenant-a", 8888, now),
    ):
        db.execute(
            "INSERT INTO axe_devices(id,name,ip_address,status,added_at,updated_at,tenant_id,removed_at) "
            "VALUES(?,?,?,'ONLINE',?,?,?,?)",
            (device_id, "PRIVATE-" + device_id, "192.0.2.5", now, now, tenant, removed),
        )
        db.execute(
            "INSERT INTO axe_telemetry(ts,device_id,payload,tenant_id) VALUES(?,?,?,?)",
            (
                now,
                device_id,
                json.dumps(
                    {
                        "ts": now,
                        "hashrate_hs": rate,
                        "power_watts": 5,
                        "temperature": 40,
                    }
                ),
                tenant,
            ),
        )
    db.commit()
    db.close()
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test-mini-key-at-least-32-characters")
    app.register_blueprint(create_mini_war_room_blueprint(lambda: registry))
    for key, expected in (("key-a", 10), ("key-b", 9999)):
        response = app.test_client().get(
            "/api/mini-war-room", headers={"X-API-Key": key}
        )
        assert response.status_code == 200
        assert_private(response)
        assert response.json["counts"]["total"] == 1
        assert response.json["metrics"]["hashrate"]["value"] == expected
        assert "PRIVATE" not in response.text
        assert "192.0.2" not in response.text
