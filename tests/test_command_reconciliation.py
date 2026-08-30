"""Integration tests for ACK versus observed command reconciliation."""

import time
from unittest.mock import MagicMock

import app as app_module
import routes.device_control as device_control
from services import operation_ledger


def _acknowledged(command="pause", ack_at=None):
    ack_at = int(time.time()) if ack_at is None else ack_at
    operation = operation_ledger.claim_operation(
        "default", "physical_command", "miner-1", command, {}
    )
    return operation_ledger.update_operation(
        operation["operation_id"],
        state="acknowledged",
        ack_state="acknowledged",
        reconciliation_state="pending",
        now=ack_at,
    )


def test_fresh_pause_observation_confirms_ack(monkeypatch):
    operation = _acknowledged("pause", ack_at=100)
    registry = MagicMock()
    registry.get_device.return_value = {
        "id": "miner-1",
        "status": "PAUSED",
        "current_telemetry": {
            "timestamp": 101,
            "hashrate_hs": 0,
            "mining_paused": True,
        },
    }
    monkeypatch.setattr(device_control, "_registry", registry)

    response = app_module.app.test_client().get(
        f"/api/devices/miner-1/commands/{operation['operation_id']}"
    )

    assert response.status_code == 200
    assert response.get_json()["ack"]["state"] == "acknowledged"
    assert response.get_json()["reconciliation"]["state"] == "confirmed"
    assert (
        operation_ledger.get_operation(operation["operation_id"])[
            "reconciliation_state"
        ]
        == "confirmed"
    )


def test_stale_telemetry_never_confirms_command(monkeypatch):
    now = int(time.time())
    operation = _acknowledged("resume", ack_at=now)
    registry = MagicMock()
    registry.get_device.return_value = {
        "id": "miner-1",
        "status": "ONLINE",
        "current_telemetry": {
            "timestamp": now,
            "hashrate_hs": 1,
            "mining_paused": False,
        },
    }
    monkeypatch.setattr(device_control, "_registry", registry)

    body = (
        app_module.app.test_client()
        .get(f"/api/devices/miner-1/commands/{operation['operation_id']}")
        .get_json()
    )

    assert body["success"] is False
    assert body["reconciliation"]["state"] == "pending"
    assert "fresh telemetry" in body["reconciliation"]["reason"]


def test_reconciliation_timeout_becomes_unknown_without_retry(monkeypatch):
    operation = _acknowledged("resume", ack_at=100)
    registry = MagicMock()
    registry.get_device.return_value = {
        "id": "miner-1",
        "status": "ONLINE",
        "current_telemetry": {
            "timestamp": 100,
            "hashrate_hs": 1,
            "mining_paused": False,
        },
    }
    monkeypatch.setattr(device_control, "_registry", registry)
    monkeypatch.setenv("COMMAND_RECONCILIATION_TIMEOUT_SECONDS", "10")

    body = (
        app_module.app.test_client()
        .get(f"/api/devices/miner-1/commands/{operation['operation_id']}")
        .get_json()
    )

    assert body["success"] is False
    assert body["reconciliation"]["state"] == "unknown"
    assert "timed out" in body["reconciliation"]["reason"]


def test_offline_after_dispatch_is_unknown_not_success(monkeypatch):
    operation = _acknowledged("restart")
    registry = MagicMock()
    registry.get_device.return_value = None
    monkeypatch.setattr(device_control, "_registry", registry)

    body = (
        app_module.app.test_client()
        .get(f"/api/devices/miner-1/commands/{operation['operation_id']}")
        .get_json()
    )

    assert body["success"] is False
    assert body["ack"]["state"] == "acknowledged"
    assert body["reconciliation"]["state"] == "unknown"


def test_operation_is_tenant_and_target_scoped(monkeypatch):
    operation = operation_ledger.claim_operation(
        "other-tenant", "physical_command", "miner-1", "pause", {}
    )
    monkeypatch.setattr(device_control, "_registry", MagicMock())

    response = app_module.app.test_client().get(
        f"/api/devices/miner-1/commands/{operation['operation_id']}"
    )

    assert response.status_code == 404
