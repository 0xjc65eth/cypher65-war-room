"""Route-level contract for explicit, encrypted pool rollback."""

import os
import sqlite3
import time
from unittest.mock import Mock, patch

import pytest

from core.adapters.bitaxe_adapter import BitaxeAdapter
from core.models.device import Device, DeviceStatus


NEW_POOL = {
    "stratumURL": "new-pool.example.test",
    "stratumPort": 3333,
    "stratumUser": "private-wallet.new-worker",
}
PRIOR_POOL = {
    "stratumURL": "stratum+tcp://prior-pool.example.test",
    "stratumPort": 3333,
    "stratumUser": "private-wallet.prior-worker",
}


@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch, tmp_path):
    from routes import device_control
    from services.pool_intelligence import (
        CapabilityState,
        PoolDryRunResult,
        PoolDryRunStage,
        PoolProtocol,
    )

    monkeypatch.setenv("DB_PATH", str(tmp_path / "rollback-routes.sqlite"))
    monkeypatch.setenv("SECRET_KEY", "rollback-route-secret-0123456789")
    monkeypatch.setenv("ENABLE_PHYSICAL_COMMANDS", "true")
    monkeypatch.setattr(
        device_control,
        "run_pool_dry_run",
        lambda parameters: PoolDryRunResult(
            ready=True,
            stage=PoolDryRunStage.READY,
            protocol=PoolProtocol.STRATUM_V1,
            capability=CapabilityState.SUPPORTED,
            dns_latency_ms=1.0,
            tcp_latency_ms=2.0,
            stratum_latency_ms=3.0,
            total_latency_ms=6.0,
        ),
    )


@pytest.fixture
def client_and_registry():
    from app import _core_registry, app

    app.config["TESTING"] = True
    return app.test_client(), _core_registry


def _device(registry, *, complete_pool=True, age=0):
    device = Device(
        name="Rollback-Test",
        model="Bitaxe",
        ip="192.168.1.220",
        status=DeviceStatus.ONLINE,
    )
    device.capabilities = BitaxeAdapter(device).get_capabilities()
    device.current_telemetry = {
        "temperature": 50,
        "hashrate": 5e12,
        "timestamp": int(time.time()) - age,
    }
    if complete_pool:
        device.current_telemetry["pool"] = {
            "url": PRIOR_POOL["stratumURL"],
            "port": PRIOR_POOL["stratumPort"],
            "user": PRIOR_POOL["stratumUser"],
        }
    registry.add_device(device)
    return device


def _dispatch_pool_update(flask_client, device, adapter):
    confirmation = flask_client.post(
        f"/api/devices/{device.id}/command/confirmation",
        json={
            "command": "update_pool",
            "parameters": NEW_POOL,
            "confirmation": "CONFIRM UPDATE_POOL",
        },
    )
    assert confirmation.status_code == 201
    with patch("routes.device_control._build_adapter", return_value=adapter):
        execution = flask_client.post(
            f"/api/devices/{device.id}/command",
            headers={"Idempotency-Key": "initial-pool-change"},
            json={
                "command": "update_pool",
                "parameters": NEW_POOL,
                "dry_run": False,
                "confirmation_token": confirmation.get_json()["confirmation_token"],
            },
        )
    assert execution.status_code == 200
    return execution.get_json()["operation_id"]


def _confirm_rollback(flask_client, device, source_operation_id):
    confirmation = flask_client.post(
        f"/api/devices/{device.id}/commands/{source_operation_id}/rollback/confirmation",
        json={"confirmation": "CONFIRM ROLLBACK POOL"},
    )
    assert confirmation.status_code == 201
    return confirmation.get_json()["confirmation_token"]


def test_rollback_is_preflighted_confirmed_idempotent_and_reconciled(
    client_and_registry,
):
    flask_client, registry = client_and_registry
    device = _device(registry)
    adapter = Mock()
    adapter.execute_command.return_value = {"success": True}
    source_operation_id = _dispatch_pool_update(flask_client, device, adapter)

    token = _confirm_rollback(flask_client, device, source_operation_id)
    with patch("routes.device_control._build_adapter", return_value=adapter):
        rollback = flask_client.post(
            f"/api/devices/{device.id}/commands/{source_operation_id}/rollback",
            headers={"Idempotency-Key": "rollback-once"},
            json={"confirmation_token": token},
        )
        replay = flask_client.post(
            f"/api/devices/{device.id}/commands/{source_operation_id}/rollback",
            headers={"Idempotency-Key": "rollback-once"},
            json={"confirmation_token": token},
        )

    assert rollback.status_code == 200
    assert replay.status_code == 200
    assert replay.get_json()["duplicate"] is True
    assert adapter.execute_command.call_count == 2
    assert adapter.execute_command.call_args_list[1].args == ("update_pool", PRIOR_POOL)
    response_text = rollback.get_data(as_text=True)
    assert "prior-pool" not in response_text
    assert "private-wallet" not in response_text

    rollback_operation_id = rollback.get_json()["operation_id"]
    device.current_telemetry["timestamp"] = int(time.time()) + 1
    device.current_telemetry["pool"] = {
        "url": PRIOR_POOL["stratumURL"],
        "port": PRIOR_POOL["stratumPort"],
        "user": PRIOR_POOL["stratumUser"],
    }
    reconciled = flask_client.get(
        f"/api/devices/{device.id}/commands/{rollback_operation_id}"
    )
    assert reconciled.status_code == 200
    assert reconciled.get_json()["reconciliation"]["state"] == "confirmed"
    assert "prior-pool" not in reconciled.get_data(as_text=True)
    assert "private-wallet" not in reconciled.get_data(as_text=True)

    conn = sqlite3.connect(os.environ["DB_PATH"])
    stored = " ".join(
        conn.execute(
            "SELECT sealed_payload, target_hash FROM pool_rollback_targets"
        ).fetchone()
    )
    conn.close()
    assert "prior-pool" not in stored
    assert "private-wallet" not in stored


@pytest.mark.parametrize("complete_pool,age", [(False, 0), (True, 121)])
def test_update_blocks_before_dispatch_without_recent_complete_target(
    client_and_registry, complete_pool, age
):
    flask_client, registry = client_and_registry
    device = _device(registry, complete_pool=complete_pool, age=age)
    adapter = Mock()
    adapter.execute_command.return_value = {"success": True}
    confirmation = flask_client.post(
        f"/api/devices/{device.id}/command/confirmation",
        json={
            "command": "update_pool",
            "parameters": NEW_POOL,
            "confirmation": "CONFIRM UPDATE_POOL",
        },
    )

    with patch("routes.device_control._build_adapter", return_value=adapter):
        response = flask_client.post(
            f"/api/devices/{device.id}/command",
            json={
                "command": "update_pool",
                "parameters": NEW_POOL,
                "dry_run": False,
                "confirmation_token": confirmation.get_json()["confirmation_token"],
            },
        )

    assert response.status_code == 409
    assert response.get_json()["reason"] == "rollback_observation_unavailable"
    adapter.execute_command.assert_not_called()


def test_update_blocks_before_dispatch_without_stable_encryption_key(
    client_and_registry, monkeypatch
):
    flask_client, registry = client_and_registry
    device = _device(registry)
    confirmation = flask_client.post(
        f"/api/devices/{device.id}/command/confirmation",
        json={
            "command": "update_pool",
            "parameters": NEW_POOL,
            "confirmation": "CONFIRM UPDATE_POOL",
        },
    )
    monkeypatch.delenv("SECRET_KEY")
    adapter = Mock()

    with patch("routes.device_control._build_adapter", return_value=adapter):
        response = flask_client.post(
            f"/api/devices/{device.id}/command",
            json={
                "command": "update_pool",
                "parameters": NEW_POOL,
                "dry_run": False,
                "confirmation_token": confirmation.get_json()["confirmation_token"],
            },
        )

    assert response.status_code == 503
    assert response.get_json()["reason"] == "rollback_encryption_unavailable"
    adapter.execute_command.assert_not_called()


def test_rollback_observation_rejects_noop_with_invalid_age_override(
    client_and_registry, monkeypatch
):
    from routes import device_control
    from services.pool_intelligence import PoolRollbackError

    _, registry = client_and_registry
    device = _device(registry)
    monkeypatch.setenv("POOL_ROLLBACK_OBSERVATION_MAX_AGE_SECONDS", "invalid")

    with pytest.raises(PoolRollbackError, match="pool_configuration_unchanged"):
        device_control._pool_rollback_observation(device, PRIOR_POOL)


def test_rollback_preflight_failure_issues_no_confirmation(
    client_and_registry, monkeypatch
):
    from routes import device_control
    from services.pool_intelligence import (
        CapabilityState,
        PoolDryRunResult,
        PoolDryRunStage,
    )

    flask_client, registry = client_and_registry
    device = _device(registry)
    adapter = Mock()
    adapter.execute_command.return_value = {"success": True}
    source_operation_id = _dispatch_pool_update(flask_client, device, adapter)
    monkeypatch.setattr(
        device_control,
        "run_pool_dry_run",
        lambda parameters: PoolDryRunResult(
            ready=False,
            stage=PoolDryRunStage.RESOLUTION,
            capability=CapabilityState.ERROR,
            failure_code="destination_rejected",
        ),
    )

    response = flask_client.post(
        f"/api/devices/{device.id}/commands/{source_operation_id}/rollback/confirmation",
        json={"confirmation": "CONFIRM ROLLBACK POOL"},
    )

    assert response.status_code == 422
    assert "confirmation_token" not in response.get_json()
    assert response.get_json()["reason"] == "rollback_preflight_failed"


def test_update_blocks_when_target_cannot_be_persisted(
    client_and_registry, monkeypatch
):
    from routes import device_control
    from services.pool_intelligence import PoolRollbackError

    flask_client, registry = client_and_registry
    device = _device(registry)
    confirmation = flask_client.post(
        f"/api/devices/{device.id}/command/confirmation",
        json={
            "command": "update_pool",
            "parameters": NEW_POOL,
            "confirmation": "CONFIRM UPDATE_POOL",
        },
    )
    monkeypatch.setattr(
        device_control,
        "store_pool_rollback_target",
        Mock(side_effect=PoolRollbackError("rollback_target_conflict")),
    )
    adapter = Mock()

    with patch("routes.device_control._build_adapter", return_value=adapter):
        response = flask_client.post(
            f"/api/devices/{device.id}/command",
            json={
                "command": "update_pool",
                "parameters": NEW_POOL,
                "dry_run": False,
                "confirmation_token": confirmation.get_json()["confirmation_token"],
            },
        )

    assert response.status_code == 503
    assert response.get_json()["reason"] == "rollback_target_conflict"
    adapter.execute_command.assert_not_called()


def test_rollback_rejects_unknown_source_and_wrong_phrase(client_and_registry):
    flask_client, registry = client_and_registry
    device = _device(registry)
    missing = flask_client.post(
        f"/api/devices/{device.id}/commands/missing/rollback/confirmation",
        json={"confirmation": "CONFIRM ROLLBACK POOL"},
    )
    missing_execution = flask_client.post(
        f"/api/devices/{device.id}/commands/missing/rollback",
        headers={"Idempotency-Key": "missing-source"},
        json={"confirmation_token": "x" * 43},
    )
    adapter = Mock()
    adapter.execute_command.return_value = {"success": True}
    source_operation_id = _dispatch_pool_update(flask_client, device, adapter)
    wrong_phrase = flask_client.post(
        f"/api/devices/{device.id}/commands/{source_operation_id}/rollback/confirmation",
        json={"confirmation": "yes"},
    )

    assert missing.status_code == 404
    assert missing_execution.status_code == 404
    assert wrong_phrase.status_code == 400
    assert wrong_phrase.get_json()["confirmation_phrase"] == "CONFIRM ROLLBACK POOL"


def test_rollback_requires_valid_idempotency_and_one_time_confirmation(
    client_and_registry,
):
    flask_client, registry = client_and_registry
    device = _device(registry)
    adapter = Mock()
    adapter.execute_command.return_value = {"success": True}
    source_operation_id = _dispatch_pool_update(flask_client, device, adapter)
    token = _confirm_rollback(flask_client, device, source_operation_id)
    endpoint = f"/api/devices/{device.id}/commands/{source_operation_id}/rollback"

    missing_key = flask_client.post(endpoint, json={"confirmation_token": token})
    invalid_key = flask_client.post(
        endpoint,
        headers={"Idempotency-Key": "bad key"},
        json={"confirmation_token": token},
    )
    with patch("routes.device_control._build_adapter", return_value=adapter):
        bad_token = flask_client.post(
            endpoint,
            headers={"Idempotency-Key": "bad-token"},
            json={"confirmation_token": "x" * 43},
        )

    assert missing_key.status_code == 400
    assert invalid_key.status_code == 400
    assert bad_token.status_code == 403
    assert adapter.execute_command.call_count == 1


def test_rollback_rechecks_preflight_immediately_before_dispatch(
    client_and_registry, monkeypatch
):
    from routes import device_control
    from services.pool_intelligence import (
        CapabilityState,
        PoolDryRunResult,
        PoolDryRunStage,
    )

    flask_client, registry = client_and_registry
    device = _device(registry)
    adapter = Mock()
    adapter.execute_command.return_value = {"success": True}
    source_operation_id = _dispatch_pool_update(flask_client, device, adapter)
    token = _confirm_rollback(flask_client, device, source_operation_id)
    monkeypatch.setattr(
        device_control,
        "run_pool_dry_run",
        lambda parameters: PoolDryRunResult(
            ready=False,
            stage=PoolDryRunStage.RESOLUTION,
            capability=CapabilityState.ERROR,
            failure_code="destination_rejected",
        ),
    )

    with patch("routes.device_control._build_adapter", return_value=adapter):
        response = flask_client.post(
            f"/api/devices/{device.id}/commands/{source_operation_id}/rollback",
            headers={"Idempotency-Key": "preflight-failed"},
            json={"confirmation_token": token},
        )

    assert response.status_code == 422
    assert response.get_json()["reason"] == "rollback_preflight_failed"
    assert adapter.execute_command.call_count == 1


@pytest.mark.parametrize("outcome", ["exception", "rejected"])
def test_rollback_dispatch_failure_is_safe_and_never_retried(
    client_and_registry, outcome
):
    flask_client, registry = client_and_registry
    device = _device(registry)
    initial_adapter = Mock()
    initial_adapter.execute_command.return_value = {"success": True}
    source_operation_id = _dispatch_pool_update(flask_client, device, initial_adapter)
    token = _confirm_rollback(flask_client, device, source_operation_id)
    rollback_adapter = Mock()
    if outcome == "exception":
        rollback_adapter.execute_command.side_effect = RuntimeError("private transport")
    else:
        rollback_adapter.execute_command.return_value = {"success": False}
    endpoint = f"/api/devices/{device.id}/commands/{source_operation_id}/rollback"

    with patch("routes.device_control._build_adapter", return_value=rollback_adapter):
        response = flask_client.post(
            endpoint,
            headers={"Idempotency-Key": f"rollback-{outcome}"},
            json={"confirmation_token": token},
        )
        replay = flask_client.post(
            endpoint,
            headers={"Idempotency-Key": f"rollback-{outcome}"},
            json={"confirmation_token": token},
        )

    assert response.status_code == 503
    assert "private transport" not in response.get_data(as_text=True)
    assert replay.status_code == 200
    assert replay.get_json()["duplicate"] is True
    rollback_adapter.execute_command.assert_called_once()
