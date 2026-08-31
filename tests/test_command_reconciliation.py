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
    safe_result = {}
    if command in {"restart", "reboot"}:
        safe_result = {
            "reboot_evidence": {
                "phase": "acknowledged",
                "offline_seen": False,
                "pre_command": {"uptime_seconds": 7200, "status": "online"},
            }
        }
    return operation_ledger.update_operation(
        operation["operation_id"],
        state="acknowledged",
        ack_state="acknowledged",
        reconciliation_state="pending",
        safe_result=safe_result,
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


def test_reboot_offline_then_reconnect_with_reset_uptime_is_confirmed(monkeypatch):
    operation = _acknowledged("restart")
    fresh_offline_at = int(operation["ack_at"]) + 1
    registry = MagicMock()
    registry.get_device.return_value = {
        "id": "miner-1",
        "status": "OFFLINE",
        "current_telemetry": {"timestamp": fresh_offline_at, "uptime_seconds": 7200},
    }
    monkeypatch.setattr(device_control, "_registry", registry)

    offline = (
        app_module.app.test_client()
        .get(f"/api/devices/miner-1/commands/{operation['operation_id']}")
        .get_json()
    )

    assert offline["success"] is False
    assert offline["ack"]["state"] == "acknowledged"
    assert offline["reconciliation"]["state"] == "pending"
    assert offline["phase"] == "offline"

    registry.get_device.return_value = {
        "id": "miner-1",
        "status": "ONLINE",
        "current_telemetry": {
            "timestamp": int(time.time()) + 1,
            "hashrate_hs": 1,
            "uptime_seconds": 12,
        },
    }
    online = (
        app_module.app.test_client()
        .get(f"/api/devices/miner-1/commands/{operation['operation_id']}")
        .get_json()
    )

    assert online["success"] is True
    assert online["reconciliation"]["state"] == "confirmed"
    assert online["phase"] == "verified"
    assert online["observed"]["uptime_seconds"] == 12


def test_reboot_never_confirms_without_observed_offline_transition(monkeypatch):
    operation = _acknowledged("restart")
    registry = MagicMock()
    registry.get_device.return_value = {
        "id": "miner-1",
        "status": "ONLINE",
        "current_telemetry": {
            "timestamp": int(time.time()) + 1,
            "hashrate_hs": 1,
            "uptime_seconds": 10,
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
    assert "offline transition was not observed" in body["reconciliation"]["reason"]


def test_reboot_never_confirms_when_uptime_did_not_reset(monkeypatch):
    operation = _acknowledged("restart")
    operation_ledger.update_operation(
        operation["operation_id"],
        state="acknowledged",
        reconciliation_state="pending",
        safe_result={
            "reboot_evidence": {
                "phase": "offline",
                "offline_seen": True,
                "pre_command": {"uptime_seconds": 7200, "status": "online"},
            }
        },
    )
    registry = MagicMock()
    registry.get_device.return_value = {
        "id": "miner-1",
        "status": "ONLINE",
        "current_telemetry": {
            "timestamp": int(time.time()) + 1,
            "hashrate_hs": 1,
            "uptime_seconds": 7300,
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
    assert "uptime reset" in body["reconciliation"]["reason"]


def test_verified_reboot_is_monotonic_when_later_poll_is_offline(monkeypatch):
    operation = _acknowledged("restart")
    operation_ledger.update_operation(
        operation["operation_id"],
        state="reconciled",
        reconciliation_state="confirmed",
        safe_result={
            "reason": "offline transition, reconnection and uptime reset verified",
            "observed": {"status": "online", "uptime_seconds": 3},
        },
    )
    registry = MagicMock()
    registry.get_device.return_value = None
    monkeypatch.setattr(device_control, "_registry", registry)

    body = (
        app_module.app.test_client()
        .get(f"/api/devices/miner-1/commands/{operation['operation_id']}")
        .get_json()
    )

    assert body["success"] is True
    assert body["phase"] == "verified"
    assert body["reconciliation"]["state"] == "confirmed"
    assert (
        operation_ledger.get_operation(operation["operation_id"])["state"]
        == "reconciled"
    )


def test_reboot_offline_timeout_becomes_unknown(monkeypatch):
    operation = _acknowledged("restart", ack_at=100)
    registry = MagicMock()
    registry.get_device.return_value = {
        "id": "miner-1",
        "status": "OFFLINE",
        "current_telemetry": {"timestamp": 101, "uptime_seconds": 7200},
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
    assert "remained offline" in body["reconciliation"]["reason"]


def test_stale_offline_status_does_not_prove_reboot_transition(monkeypatch):
    ack_at = int(time.time())
    operation = _acknowledged("restart", ack_at=ack_at)
    registry = MagicMock()
    registry.get_device.return_value = {
        "id": "miner-1",
        "status": "OFFLINE",
        "current_telemetry": {"timestamp": ack_at, "uptime_seconds": 7200},
    }
    monkeypatch.setattr(device_control, "_registry", registry)

    body = (
        app_module.app.test_client()
        .get(f"/api/devices/miner-1/commands/{operation['operation_id']}")
        .get_json()
    )

    assert body["reconciliation"]["state"] == "pending"
    assert "lacks post-dispatch timestamp" in body["reconciliation"]["reason"]
    stored = operation_ledger.get_operation(operation["operation_id"])
    assert stored["safe_result"]["reboot_evidence"]["offline_seen"] is False


def test_audit_failure_is_reported_instead_of_claiming_recorded(monkeypatch):
    operation = _acknowledged("pause", ack_at=100)
    registry = MagicMock()
    registry.get_device.return_value = {
        "id": "miner-1",
        "status": "PAUSED",
        "current_telemetry": {"timestamp": 101, "mining_paused": True},
    }
    monkeypatch.setattr(device_control, "_registry", registry)
    monkeypatch.setattr(device_control, "log_audit", lambda *args, **kwargs: None)

    body = (
        app_module.app.test_client()
        .get(f"/api/devices/miner-1/commands/{operation['operation_id']}")
        .get_json()
    )

    assert body["reconciliation"]["state"] == "confirmed"
    assert body["audit"]["state"] == "failed"
    replay = (
        app_module.app.test_client()
        .get(f"/api/devices/miner-1/commands/{operation['operation_id']}")
        .get_json()
    )
    assert replay["audit"]["state"] == "failed"


def test_registry_miss_does_not_prove_reboot_offline_transition(monkeypatch):
    operation = _acknowledged("restart")
    registry = MagicMock()
    registry.get_device.return_value = None
    monkeypatch.setattr(device_control, "_registry", registry)

    body = (
        app_module.app.test_client()
        .get(f"/api/devices/miner-1/commands/{operation['operation_id']}")
        .get_json()
    )

    assert body["reconciliation"]["state"] == "pending"
    assert body["phase"] == "reconnecting"
    assert "not proven" in body["reconciliation"]["reason"]
    stored = operation_ledger.get_operation(operation["operation_id"])
    assert stored["safe_result"]["reboot_evidence"]["offline_seen"] is False


def test_operation_is_tenant_and_target_scoped(monkeypatch):
    operation = operation_ledger.claim_operation(
        "other-tenant", "physical_command", "miner-1", "pause", {}
    )
    monkeypatch.setattr(device_control, "_registry", MagicMock())

    response = app_module.app.test_client().get(
        f"/api/devices/miner-1/commands/{operation['operation_id']}"
    )

    assert response.status_code == 404
