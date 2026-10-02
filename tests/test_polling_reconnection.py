"""Regression coverage for agent recovery and bounded device-poll backoff."""

import logging
import sqlite3
import time
from unittest.mock import patch

import pytest

from app import app as _app
from axe_fleet.axeos_contract import official_esp_miner_info
from axe_fleet.connector import AxeOSConnectorError
from axe_fleet.registry import DeviceRegistry
from services.auth import create_token
from services import state


@pytest.fixture
def client(monkeypatch):
    """Flask test client with an isolated test JWT secret."""
    previous_testing = _app.config.get("TESTING")
    _app.config["TESTING"] = True
    previous_secret = _app.config.get("JWT_SECRET_KEY")
    secret = "polling-reconnect-test-secret-0123456789abcdef"
    _app.config["JWT_SECRET_KEY"] = secret
    monkeypatch.setenv("SECRET_KEY", secret)
    yield _app.test_client()
    if previous_secret is None:
        _app.config.pop("JWT_SECRET_KEY", None)
    else:
        _app.config["JWT_SECRET_KEY"] = previous_secret
    if previous_testing is None:
        _app.config.pop("TESTING", None)
    else:
        _app.config["TESTING"] = previous_testing


@pytest.fixture
def agent_token():
    """Create an agent token for the isolated tenant."""
    return create_token(
        subject="ops-003-tenant",
        ttl=3600,
        extra_claims={"agent": True, "role": "agent"},
    )


@pytest.fixture
def registry(tmp_path):
    """Use the real device registry with an isolated SQLite database."""
    db_path = str(tmp_path / "ops-003.sqlite")

    def get_db():
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        return connection

    result = DeviceRegistry(get_db)
    result.ensure_tables()
    return result


@pytest.fixture
def enable_info_logging():
    """Temporarily override conftest's process-wide log suppression."""
    previous_disable = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    try:
        yield
    finally:
        logging.disable(previous_disable)


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_agent_telemetry_recovery_emits_one_online_edge(
    client, agent_token, registry, caplog, enable_info_logging
):
    """Empty heartbeats preserve OFFLINE/STALE semantics through recovery."""
    caplog.set_level(logging.INFO, logger="cypher65")
    ip = "192.168.1.50"

    with patch("axe_fleet.routes._registry", registry):
        registered = client.post(
            "/api/agent/register",
            headers=_headers(agent_token),
            json={"devices": [{"ip": ip, "model": "Bitaxe"}]},
        )
        assert registered.status_code == 201
        device_id = registered.get_json()["registered"][0]["id"]

        offline = client.post(
            "/api/agent/telemetry",
            headers=_headers(agent_token),
            json={"ip": ip, "telemetry": {}},
        )
        assert offline.status_code == 200
        assert offline.get_json()["status"] == "OFFLINE"

        stale_sample = {
            "ts": int(time.time()) - 3600,
            "hashrate_hs": 4_000_000_000,
            "temperature": 62.0,
        }
        stale = client.post(
            "/api/agent/telemetry",
            headers=_headers(agent_token),
            json={"ip": ip, "telemetry": stale_sample},
        )
        assert stale.status_code == 200
        assert stale.get_json()["status"] == "STALE"

        empty_heartbeat = client.post(
            "/api/agent/telemetry",
            headers=_headers(agent_token),
            json={"ip": ip, "telemetry": {}},
        )
        assert empty_heartbeat.status_code == 200
        assert empty_heartbeat.get_json()["status"] == "STALE"

        recovered = client.post(
            "/api/agent/telemetry",
            headers=_headers(agent_token),
            json={
                "ip": ip,
                "telemetry": {
                    "ts": int(time.time()),
                    "hashrate_hs": 4_100_000_000,
                    "temperature": 61.5,
                },
            },
        )
        assert recovered.status_code == 200
        assert recovered.get_json()["status"] == "ONLINE"

        fresh_heartbeat = client.post(
            "/api/agent/telemetry",
            headers=_headers(agent_token),
            json={"ip": ip, "telemetry": {}},
        )
        assert fresh_heartbeat.status_code == 200
        assert fresh_heartbeat.get_json()["status"] == "ONLINE"

    device = registry.get_device(device_id, tenant_id="ops-003-tenant")
    assert device["status"] == "ONLINE"
    fleet_events = [
        record.ctx["event"]
        for record in caplog.records
        if record.getMessage() == "fleet event"
    ]
    assert fleet_events.count("miner.online") == 1


@pytest.mark.covers("OPS-003")
def test_device_poll_backoff_and_recovery_emit_one_event_per_edge(
    registry, monkeypatch, caplog
):
    """Retries back off on failures and recovery events are edge-triggered."""
    import app as app_module

    monkeypatch.setattr(app_module, "_axe_registry", registry)
    monkeypatch.setattr(state, "axe_last_poll_ts", {})
    monkeypatch.setattr(state, "axe_poll_error_counts", {})
    caplog.set_level(logging.INFO, logger="cypher65")

    recovered_telemetry = {
        "ts": 1_800_000_000,
        "hashrate_hs": 4_800_000_000_000,
        "temperature": 58,
    }
    with patch("axe_fleet.registry.AxeOSConnector") as connector:
        connector.return_value.fetch_info.return_value = official_esp_miner_info()
        connector.return_value.detect_capabilities.return_value = {"telemetry": True}
        connector.return_value.extract_telemetry.side_effect = [
            AxeOSConnectorError("temporary disconnect"),
            AxeOSConnectorError("still offline"),
            AxeOSConnectorError("still offline"),
            recovered_telemetry,
            recovered_telemetry,
            AxeOSConnectorError("second disconnect"),
            recovered_telemetry,
        ]

        device = registry.add_device("192.0.2.80", name="reconnect-test")
        device_id = device["id"]
        registry.update_device(device_id, {"status": "ONLINE"})
        caplog.clear()

        base = 1_800_000_000
        attempts = [
            base,  # initial attempt fails
            base + 60,  # first failure backs off to 120 seconds
            base + 120,  # second attempt fails
            base + 239,  # second failure backs off to 240 seconds
            base + 360,  # third attempt fails after the 240-second interval
            base + 659,  # capped backoff is 300 seconds
            base + 660,  # telemetry recovers
            base + 720,  # healthy cadence returns to 60 seconds
            base + 780,  # a later real failure starts a new backoff cycle
            base + 839,  # no retry before the 120-second backoff expires
            base + 900,  # second recovery
        ]
        call_counts = []
        for timestamp in attempts:
            app_module._poll_axe_fleet(timestamp)
            call_counts.append(connector.return_value.extract_telemetry.call_count)

    assert call_counts == [1, 1, 2, 2, 3, 3, 4, 5, 6, 6, 7]
    assert registry.get_device(device_id)["status"] == "ONLINE"

    events = [
        record.ctx["event"]
        for record in caplog.records
        if record.getMessage() == "fleet event"
    ]
    assert events == [
        "miner.offline",
        "miner.online",
        "miner.offline",
        "miner.online",
    ]
    assert state.axe_poll_error_counts == {}
