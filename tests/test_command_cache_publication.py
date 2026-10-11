"""Issue #814: commands publish committed state after delayed telemetry callbacks.

SQLite, command confirmation/ledger, and the application's cache callback are
real. Only the physical connector is replaced; no miner or network is contacted.
"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import sqlite3
from threading import Event

import pytest

import app as app_module
from axe_fleet import routes
from axe_fleet.connector import AxeOSConnectorError
from axe_fleet.registry import DeviceRegistry
from services import operation_ledger, state
from services.auth import create_token


TENANT = "command-publication"
MAC = "02:00:00:00:08:14"
WAIT_SECONDS = 5


@pytest.fixture
def publication_context(tmp_path, monkeypatch):
    db_path = tmp_path / "publication.sqlite"

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    registry = DeviceRegistry(get_db)
    registry.ensure_tables()
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("ENABLE_PHYSICAL_COMMANDS", "true")
    monkeypatch.setenv("TENANT_API_KEYS", "require-explicit-auth")
    secret = "command-publication-test-secret-0123456789abcdef"
    monkeypatch.setenv("SECRET_KEY", secret)
    monkeypatch.setitem(app_module.app.config, "JWT_SECRET_KEY", secret)
    monkeypatch.setitem(app_module.app.config, "TESTING", True)
    monkeypatch.setattr(routes, "_registry", registry)
    monkeypatch.setattr(state, "axe_telemetry_cache", {})
    registry.on_telemetry_committed = app_module._cache_axe_telemetry
    token = create_token(subject=TENANT, extra_claims={"role": "admin"})
    headers = {"Authorization": f"Bearer {token}"}
    device = registry.upsert_agent_device(
        "192.0.2.14",
        tenant_id=TENANT,
        info={"mac": MAC, "type": "bitaxe", "firmware": "AxeOS"},
    )
    return registry, device["id"], headers


def _history(registry, device_id):
    return registry.get_recent_telemetry(device_id, tenant_id=TENANT)


def _status(registry, device_id):
    return registry.get_device(device_id, tenant_id=TENANT)["status"]


def _confirmed_post(device_id, command, headers):
    with app_module.app.test_client() as client:
        endpoint = f"/api/axe-fleet/devices/{device_id}/{command}"
        prepared = client.post(endpoint, headers=headers, json={"dry_run": False})
        assert prepared.status_code == 202, prepared.get_json()
        return client.post(
            endpoint,
            headers=headers,
            json={
                "dry_run": False,
                "confirmation_token": prepared.get_json()["confirmation_token"],
            },
        )


@pytest.mark.parametrize(
    "command,agent_managed,transport_error,resume_hashrate,expected_status",
    [
        ("pause", False, False, None, "PAUSED"),
        ("pause", True, False, None, "PAUSED"),
        ("resume", False, False, 0, "IDLE"),
        ("resume", False, False, 3e12, "ONLINE"),
        ("pause", False, True, None, "ONLINE"),
    ],
    ids=[
        "direct-pause",
        "queued-pause",
        "resume-idle",
        "resume-online",
        "transport-unknown",
    ],
)
def test_delayed_real_callback_and_command_converge(
    publication_context,
    monkeypatch,
    command,
    agent_managed,
    transport_error,
    resume_hashrate,
    expected_status,
):
    registry, device_id, headers = publication_context

    def save_sample(hashrate):
        # This is the shared atomic boundary used by polling and Agent ingestion.
        return registry._persist_live_telemetry(
            device_id,
            {"hashrate_hs": hashrate, "mining_paused": False},
            TENANT,
            agent_managed=agent_managed,
        )

    save_sample(1e12)
    assert registry.update_device(
        device_id,
        {"agent_managed": int(agent_managed)},
        tenant_id=TENANT,
    )
    callback_entered = Event()
    release_callback = Event()
    command_written = Event()
    transport_failed = Event()
    callback_statuses = []

    def delayed_callback(did, telemetry, status):
        callback_statuses.append(status)
        if len(callback_statuses) == 1:
            assert status == "ONLINE"
            callback_entered.set()
            assert release_callback.wait(WAIT_SECONDS), "callback was not released"
        app_module._cache_axe_telemetry(did, telemetry, status)

    registry.on_telemetry_committed = delayed_callback
    real_update = registry.update_device

    def observe_committed_update(did, updates, **kwargs):
        updated = real_update(did, updates, **kwargs)
        if updated and "status" in updates:
            command_written.set()
        return updated

    monkeypatch.setattr(registry, "update_device", observe_committed_update)

    class Connector:
        def __init__(self, ip):
            assert ip == "192.0.2.14"

        def pause(self):
            if transport_error:
                transport_failed.set()
                raise AxeOSConnectorError("synthetic transport failure")
            return {"success": True}

        def resume(self):
            return {"success": True}

        def extract_telemetry(self):
            return {"hashrate_hs": resume_hashrate, "mining_paused": False}

    monkeypatch.setattr(routes, "AxeOSConnector", Connector)
    with ThreadPoolExecutor(max_workers=2) as pool:
        telemetry_future = pool.submit(save_sample, 2e12)
        try:
            assert callback_entered.wait(WAIT_SECONDS)
            assert _status(registry, device_id) == "ONLINE"
            assert len(_history(registry, device_id)) == 2
            command_future = pool.submit(_confirmed_post, device_id, command, headers)
            if transport_error:
                assert transport_failed.wait(WAIT_SECONDS)
                response = command_future.result(timeout=WAIT_SECONDS)
                assert not command_written.is_set()
            else:
                assert command_written.wait(WAIT_SECONDS), "command did not commit"
                assert _status(registry, device_id) == expected_status
                # The command committed before the old ONLINE callback returned.
                assert not telemetry_future.done()
            assert state.axe_telemetry_cache[device_id]["hashrate_hs"] == 1e12
        finally:
            release_callback.set()
        assert telemetry_future.result(timeout=WAIT_SECONDS) == "ONLINE"
        response = command_future.result(timeout=WAIT_SECONDS)

    data = response.get_json()
    assert _status(registry, device_id) == expected_status
    assert state.axe_telemetry_cache[device_id]["status"] == expected_status
    # Publication reuses the actual committed measurement, including resume:
    # a command's re-probe must not silently become a persisted telemetry sample.
    assert state.axe_telemetry_cache[device_id]["hashrate_hs"] == 2e12
    assert state.axe_telemetry_cache[device_id]["hashrate"] == 2e12
    assert len(_history(registry, device_id)) == 2
    if transport_error:
        assert response.status_code == 503
        assert data["ack"]["state"] == "unknown"
        assert data["reconciliation"]["state"] == "unknown"
        assert callback_statuses == ["ONLINE"]
    else:
        assert response.status_code == 200
        assert data["success"] is True
        assert data["reconciliation"]["state"] == "pending"
        assert callback_statuses == ["ONLINE", expected_status]
        if agent_managed:
            assert data["queued"] is True
            assert data["ack"] == {"state": "pending", "source": "local_agent"}
            queued = registry.pending_agent_commands(tenant_id=TENANT)
            assert len(queued) == 1
            assert queued[0]["device_id"] == device_id
            assert queued[0]["command"] == "pause"
            assert queued[0]["status"] == "pending"
        else:
            assert data["ack"] == {"state": "acknowledged", "source": "axeos"}


@pytest.mark.parametrize("blocked_reason", ["wrong-tenant", "removed"])
def test_publication_cannot_mutate_cache_for_inaccessible_device(
    publication_context,
    blocked_reason,
):
    registry, device_id, _ = publication_context
    registry.save_agent_telemetry(device_id, {"hashrate_hs": 1e12}, tenant_id=TENANT)
    cached = deepcopy(state.axe_telemetry_cache)
    history = _history(registry, device_id)
    if blocked_reason == "removed":
        assert registry.remove_device(device_id, tenant_id=TENANT)
        publish_tenant = TENANT
    else:
        publish_tenant = "different-tenant"
    routes._mark_cache_status(device_id, publish_tenant)
    assert state.axe_telemetry_cache == cached
    assert _history(registry, device_id) == history


def test_publication_without_measurement_never_invents_hashrate(publication_context):
    registry, device_id, _ = publication_context
    assert _history(registry, device_id) == []
    registry.publish_device_state(device_id, TENANT)
    cached = state.axe_telemetry_cache[device_id]
    assert cached["status"] == _status(registry, device_id) == "OFFLINE"
    assert "hashrate_hs" not in cached
    assert cached["hashrate"] is None
    assert _history(registry, device_id) == []


@pytest.mark.parametrize(
    "command,agent_managed",
    [("pause", False), ("pause", True), ("resume", False)],
    ids=["direct-pause", "queued-pause", "direct-resume"],
)
@pytest.mark.parametrize("failure", ["update-refused", "cache-exception"])
def test_cache_publication_failure_keeps_command_ack_and_ledger(
    publication_context,
    monkeypatch,
    command,
    agent_managed,
    failure,
):
    registry, device_id, headers = publication_context
    registry.save_agent_telemetry(device_id, {"hashrate_hs": 1e12}, tenant_id=TENANT)
    assert registry.update_device(
        device_id,
        {"agent_managed": int(agent_managed)},
        tenant_id=TENANT,
    )
    cached = deepcopy(state.axe_telemetry_cache)
    history = _history(registry, device_id)
    publications = []
    real_publish = registry.publish_device_state

    def observed_publish(did, tenant):
        publications.append((did, tenant))
        real_publish(did, tenant)

    monkeypatch.setattr(registry, "publish_device_state", observed_publish)
    if failure == "update-refused":
        monkeypatch.setattr(registry, "update_device", lambda *a, **kw: False)
    else:

        def broken_cache(*args):
            raise RuntimeError("synthetic cache failure after DB commit")

        registry.on_telemetry_committed = broken_cache

    class Connector:
        def __init__(self, ip):
            assert ip == "192.0.2.14"

        def pause(self):
            return {"success": True}

        def resume(self):
            return {"success": True}

        def extract_telemetry(self):
            return {"hashrate_hs": 0, "mining_paused": False}

    monkeypatch.setattr(routes, "AxeOSConnector", Connector)
    response = _confirmed_post(device_id, command, headers)
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert data["reconciliation"]["state"] == "pending"
    operation = operation_ledger.get_operation(data["operation_id"])
    assert operation["tenant_id"] == TENANT
    assert operation["target"] == device_id
    assert operation["reconciliation_state"] == "pending"
    if agent_managed:
        assert data["queued"] is True
        assert data["ack"]["state"] == operation["ack_state"] == "pending"
        assert operation["state"] == "dispatched"
        assert len(registry.pending_agent_commands(tenant_id=TENANT)) == 1
    else:
        assert data["ack"]["state"] == operation["ack_state"] == "acknowledged"
        assert operation["state"] == "acknowledged"
    if failure == "update-refused":
        assert publications == []
        assert _status(registry, device_id) == "ONLINE"
    else:
        assert publications == [(device_id, TENANT)]
        assert _status(registry, device_id) == (
            "PAUSED" if command == "pause" else "IDLE"
        )
    assert state.axe_telemetry_cache == cached
    assert _history(registry, device_id) == history


def test_state_publication_adds_no_telemetry_or_measurement_events(
    publication_context,
    monkeypatch,
):
    registry, device_id, _ = publication_context
    registry.save_agent_telemetry(device_id, {"hashrate_hs": 1e12}, tenant_id=TENANT)
    assert registry.update_device(device_id, {"status": "PAUSED"}, tenant_id=TENANT)
    history = _history(registry, device_id)
    emitted = []
    monkeypatch.setattr(
        "axe_fleet.registry.emit_event",
        lambda *a, **kw: emitted.append((a, kw)),
    )
    registry.publish_device_state(device_id, TENANT)
    registry.publish_device_state(device_id, TENANT)
    assert state.axe_telemetry_cache[device_id]["status"] == "PAUSED"
    assert state.axe_telemetry_cache[device_id]["hashrate_hs"] == 1e12
    assert _history(registry, device_id) == history
    assert emitted == []
