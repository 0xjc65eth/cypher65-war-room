"""Regression coverage for Issue #644 Fleet freshness semantics."""

from unittest.mock import MagicMock, patch

import pytest

from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as flask_client:
        yield flask_client


def _device(status="STALE"):
    return {
        "id": "d1",
        "name": "Old miner",
        "model": "Bitaxe",
        "ip_address": "192.168.1.100",
        "last_seen": 1_700_000_000,
        "status": status,
        "capabilities": {},
    }


def test_health_uses_registry_freshness_status(client):
    registry = MagicMock()
    registry.list_devices.return_value = [_device()]
    registry.get_recent_telemetry.return_value = [
        {
            "ts": 1_700_000_000,
            "payload": {"hashrate_hs": 1_200_000_000_000, "ts": 1_700_000_000},
        }
    ]

    with patch("axe_fleet.routes._registry", registry):
        response = client.get("/api/axe-fleet/health")

    assert response.status_code == 200
    data = response.get_json()
    assert data["fleet_stats"]["online"] == 0
    assert data["fleet_stats"]["offline"] == 1
    assert data["fleet_stats"]["total_hashrate_hs"] == 0
    assert data["device_health"][0]["status"] == "STALE"
    registry.list_devices.assert_called_once_with(
        tenant_id="default", with_telemetry=True
    )


def test_summary_excludes_stale_hashrate_from_live_total(client):
    registry = MagicMock()
    registry.list_devices.return_value = [_device()]
    registry.get_recent_telemetry.return_value = [
        {
            "ts": 1_700_000_000,
            "payload": {"hashrate_hs": 1_200_000_000_000, "ts": 1_700_000_000},
        }
    ]

    with patch("axe_fleet.routes._registry", registry):
        response = client.get("/api/axe-fleet/summary")

    assert response.status_code == 200
    data = response.get_json()
    assert data["online"] == 0
    assert data["offline"] == 1
    assert data["total_hashrate_hs"] == 0
    telemetry = data["devices"][0]["_telemetry"]
    assert telemetry["hashrate_hs"] == 0
    assert telemetry["last_known_hashrate_hs"] == 1_200_000_000_000
    registry.list_devices.assert_called_once_with(
        tenant_id="default", with_telemetry=True
    )


def test_summary_preserves_missing_measurements(client):
    registry = MagicMock()
    registry.list_devices.return_value = [_device()]
    registry.get_recent_telemetry.return_value = []

    with patch("axe_fleet.routes._registry", registry):
        response = client.get("/api/axe-fleet/summary")

    assert response.status_code == 200
    telemetry = response.get_json()["devices"][0]["_telemetry"]
    assert telemetry["hashrate_hs"] is None
    assert telemetry["shares_accepted"] is None
    assert telemetry["uptime_seconds"] is None
    assert telemetry["ts"] is None
    assert telemetry["age_seconds"] is None
