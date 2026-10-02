"""Integration regression coverage for agent telemetry recovery (OPS-003)."""

import logging
import sqlite3
import time
from unittest.mock import patch

import pytest

from app import app as _app
from services.auth import create_token
from axe_fleet.registry import DeviceRegistry


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
    """Use a real DeviceRegistry backed by a temporary SQLite database."""
    db_path = str(tmp_path / "ops-003.sqlite")

    def get_db():
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        return connection

    device_registry = DeviceRegistry(get_db)
    device_registry.ensure_tables()
    return device_registry


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
