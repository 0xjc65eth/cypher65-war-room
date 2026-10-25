"""Replay safety contract for local-agent telemetry samples (TEL-001)."""

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from app import app
from axe_fleet.registry import DeviceRegistry
from services.auth import create_token
from agent import agent as local_agent


@pytest.fixture
def registry(tmp_path):
    """Create a real registry backed by an isolated SQLite database."""
    db_path = str(tmp_path / "telemetry.sqlite")

    def get_db():
        conn = sqlite3.connect(db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    result = DeviceRegistry(get_db)
    result.ensure_tables()
    return result


@pytest.fixture
def client(monkeypatch):
    """Return a Flask client and an agent token for tenant ``acme``."""
    app.config["TESTING"] = True
    monkeypatch.setenv("SECRET_KEY", "telemetry-idempotency-test-secret-012345")
    app.config["JWT_SECRET_KEY"] = "telemetry-idempotency-test-secret-012345"
    token = create_token(subject="acme", extra_claims={"agent": True, "role": "agent"})
    return app.test_client(), {"Authorization": f"Bearer {token}"}


@pytest.mark.covers("TEL-001")
def test_agent_replay_keeps_one_history_point_and_aggregate(client, registry):
    """Same tenant/device/key/timestamp/payload is acknowledged exactly once."""
    flask_client, headers = client
    ip = "192.168.88.20"
    device = registry.upsert_agent_device(
        ip, tenant_id="acme", info={"mac": "02:00:00:00:04:01"}
    )
    event = {
        "ip": ip,
        "mac": device["mac_address"],
        "idempotency_key": "sample-event-0001",
        "telemetry": {"ts": 1_790_000_000, "hashrate_hs": 4_800_000_000_000},
    }

    with patch("axe_fleet.routes._registry", registry):
        first = flask_client.post("/api/agent/telemetry", headers=headers, json=event)
        replay = flask_client.post("/api/agent/telemetry", headers=headers, json=event)

    assert first.status_code == replay.status_code == 200
    assert (
        first.get_json()["device_id"] == replay.get_json()["device_id"] == device["id"]
    )
    history = registry.get_recent_telemetry(device["id"], tenant_id="acme")
    series = registry.get_telemetry_chart_data(device["id"], tenant_id="acme")
    assert len(history) == 1
    assert series["ts"] == [event["telemetry"]["ts"]]
    assert series["hashrate_hs"] == [4_800_000_000_000]


@pytest.mark.covers("TEL-001")
def test_local_agent_retries_the_same_timestamped_event(monkeypatch):
    """Transient failures reuse the same key and sample timestamp."""
    event = local_agent._build_telemetry_event(
        "192.168.88.24", {"hashrate_hs": 6_000}, mac="02:00:00:00:04:18"
    )
    sent = []

    def initial_post(_path, payload, timeout):
        sent.append(payload)
        assert timeout == 10.0
        return 503, {}

    def retry_post(_path, payload, timeout, attempts):
        sent.append(payload)
        assert timeout == 10.0
        assert attempts == 3
        return 200, {"success": True}

    monkeypatch.setattr(local_agent, "_post", initial_post)
    monkeypatch.setattr(local_agent, "_post_retry", retry_post)
    assert local_agent._push_telemetry_event(event) == (200, {"success": True})
    assert len(event["idempotency_key"]) == 32
    assert event["telemetry"]["ts"] > 0
    assert sent[0] is sent[1] is event
    assert event["mac"] == "02:00:00:00:04:18"


@pytest.mark.covers("TEL-001")
def test_reusing_key_for_changed_sample_returns_conflict_without_overwrite(
    client, registry
):
    """A changed payload never silently overwrites a previously accepted event."""
    flask_client, headers = client
    ip = "192.168.88.21"
    device = registry.upsert_agent_device(
        ip, tenant_id="acme", info={"mac": "02:00:00:00:04:01"}
    )
    event = {
        "ip": ip,
        "mac": device["mac_address"],
        "idempotency_key": "sample-event-0002",
        "telemetry": {"ts": 1_790_000_001, "hashrate_hs": 1_000},
    }
    changed = {
        **event,
        "telemetry": {"ts": 1_790_000_001, "hashrate_hs": 2_000},
    }

    with patch("axe_fleet.routes._registry", registry):
        assert (
            flask_client.post(
                "/api/agent/telemetry", headers=headers, json=event
            ).status_code
            == 200
        )
        conflict = flask_client.post(
            "/api/agent/telemetry", headers=headers, json=changed
        )

    assert conflict.status_code == 409
    history = registry.get_recent_telemetry(device["id"], tenant_id="acme")
    assert len(history) == 1
    assert history[0]["payload"]["hashrate_hs"] == 1_000


@pytest.mark.covers("TEL-001")
def test_keyed_request_requires_a_stable_sample_timestamp(client, registry):
    """A keyed event cannot depend on server arrival time for its identity."""
    flask_client, headers = client
    ip = "192.168.88.25"
    device = registry.upsert_agent_device(
        ip, tenant_id="acme", info={"mac": "02:00:00:00:04:01"}
    )
    event = {
        "ip": ip,
        "mac": device["mac_address"],
        "idempotency_key": "sample-event-0005",
        "telemetry": {"hashrate_hs": 1_000},
    }
    with patch("axe_fleet.routes._registry", registry):
        response = flask_client.post(
            "/api/agent/telemetry", headers=headers, json=event
        )
    assert response.status_code == 400
    assert (
        registry.get_recent_telemetry(
            registry.get_device_by_ip(ip, tenant_id="acme")["id"], tenant_id="acme"
        )
        == []
    )


@pytest.mark.covers("TEL-001")
def test_concurrent_identical_replays_insert_one_row(registry):
    """The unique database constraint closes concurrent retry races."""
    device = registry.upsert_agent_device(
        "192.168.88.22", tenant_id="acme", info={"mac": "02:00:00:00:04:16"}
    )
    sample = {"ts": 1_790_000_002, "hashrate_hs": 3_000}

    def persist():
        return registry.save_agent_telemetry(
            device["id"],
            sample,
            tenant_id="acme",
            idempotency_key="sample-event-0003",
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _index: persist(), range(16)))

    assert len(registry.get_recent_telemetry(device["id"], tenant_id="acme")) == 1


@pytest.mark.covers("TEL-001")
def test_replay_waits_for_atomic_sample_and_state_commit(registry, monkeypatch):
    """A concurrent replay cannot observe or acknowledge a half-written sample."""
    device = registry.upsert_agent_device(
        "192.168.88.26", tenant_id="acme", info={"mac": "02:00:00:00:04:1A"}
    )
    sample = {"ts": int(time.time()), "hashrate_hs": 7_000}
    inserted = threading.Event()
    allow_commit = threading.Event()
    replay_started = threading.Event()
    original_write = registry._save_telemetry_tx
    first_write = True

    def delayed_write(*args, **kwargs):
        nonlocal first_write
        result = original_write(*args, **kwargs)
        if first_write:
            first_write = False
            inserted.set()
            assert allow_commit.wait(timeout=5)
        return result

    def replay():
        replay_started.set()
        return registry.save_agent_telemetry(
            device["id"],
            sample,
            tenant_id="acme",
            idempotency_key="sample-event-race01",
        )

    monkeypatch.setattr(registry, "_save_telemetry_tx", delayed_write)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            registry.save_agent_telemetry,
            device["id"],
            sample,
            "acme",
            "sample-event-race01",
        )
        try:
            assert inserted.wait(timeout=5)
            second = pool.submit(replay)
            assert replay_started.wait(timeout=5)
            # Reader sees the previous complete state, not an inserted sample.
            assert registry.get_recent_telemetry(device["id"], tenant_id="acme") == []
            assert (
                registry.get_device(device["id"], tenant_id="acme")["status"]
                == "OFFLINE"
            )
            assert not second.done()
        finally:
            allow_commit.set()
        assert first.result(timeout=5) == second.result(timeout=5) == "ONLINE"
    assert registry.get_device(device["id"], tenant_id="acme")["status"] == "ONLINE"
    assert len(registry.get_recent_telemetry(device["id"], tenant_id="acme")) == 1


@pytest.mark.covers("TEL-001")
def test_retry_after_failed_transaction_has_no_partial_history_or_state(
    registry, monkeypatch
):
    """An exception after INSERT rolls back sample/state/quarantine together."""
    device = registry.upsert_agent_device(
        "192.168.88.27", tenant_id="acme", info={"mac": "02:00:00:00:04:1B"}
    )
    before = registry.get_device(device["id"], tenant_id="acme")
    registry.record_telemetry_quarantine(
        device["id"], ["temperature"], ["out_of_range"], tenant_id="acme"
    )
    quarantine = registry.get_telemetry_quarantines(tenant_id="acme")
    sample = {"ts": int(time.time()), "hashrate_hs": 8_000}
    original_write = registry._save_telemetry_tx
    first_attempt = True

    def fail_after_insert(*args, **kwargs):
        nonlocal first_attempt
        result = original_write(*args, **kwargs)
        if first_attempt:
            first_attempt = False
            raise RuntimeError("simulated interruption after INSERT before commit")
        return result

    monkeypatch.setattr(registry, "_save_telemetry_tx", fail_after_insert)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        registry.save_agent_telemetry(
            device["id"],
            sample,
            tenant_id="acme",
            idempotency_key="sample-event-retry01",
        )
    assert registry.get_recent_telemetry(device["id"], tenant_id="acme") == []
    assert registry.get_device(device["id"], tenant_id="acme") == before
    assert registry.get_telemetry_quarantines(tenant_id="acme") == quarantine

    replay_status = registry.save_agent_telemetry(
        device["id"], sample, tenant_id="acme", idempotency_key="sample-event-retry01"
    )
    recovered = registry.get_device(device["id"], tenant_id="acme")
    assert replay_status == recovered["status"] == "ONLINE"
    assert recovered["agent_managed"] == 1
    assert recovered["last_seen"] >= before["last_seen"]
    assert len(registry.get_recent_telemetry(device["id"], tenant_id="acme")) == 1
    assert registry.get_telemetry_quarantines(tenant_id="acme") == {}


@pytest.mark.covers("TEL-001")
def test_idempotency_key_is_scoped_to_tenant(registry):
    """Separate tenants can independently use the same event key."""
    sample = {"ts": 1_790_000_003, "hashrate_hs": 4_000}
    for tenant_id in ("alpha", "beta"):
        assert (
            registry.save_telemetry(
                "shared-device-id",
                sample,
                tenant_id=tenant_id,
                idempotency_key="sample-event-0004",
            )
            is True
        )

    assert (
        len(registry.get_recent_telemetry("shared-device-id", tenant_id="alpha")) == 1
    )
    assert len(registry.get_recent_telemetry("shared-device-id", tenant_id="beta")) == 1


@pytest.mark.covers("TEL-001")
def test_legacy_calls_without_key_remain_append_only(registry):
    """Older clients remain compatible but do not receive replay protection."""
    device = registry.upsert_agent_device(
        "192.168.88.23", tenant_id="acme", info={"mac": "02:00:00:00:04:17"}
    )
    sample = {"ts": 1_790_000_004, "hashrate_hs": 5_000}
    registry.save_agent_telemetry(device["id"], sample, tenant_id="acme")
    registry.save_agent_telemetry(device["id"], sample, tenant_id="acme")
    assert len(registry.get_recent_telemetry(device["id"], tenant_id="acme")) == 2


@pytest.mark.covers("TEL-001")
def test_existing_telemetry_rows_survive_schema_migration(tmp_path):
    """Upgrade a pre-key table in place without dropping historical rows."""
    db_path = str(tmp_path / "legacy-telemetry.sqlite")
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE axe_telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            device_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            tenant_id TEXT DEFAULT 'default'
        )"""
    )
    conn.execute(
        "INSERT INTO axe_telemetry (ts, device_id, payload, tenant_id) VALUES (?, ?, ?, ?)",
        (1_790_000_005, "legacy-device", '{"hashrate_hs":6000}', "acme"),
    )
    conn.commit()
    conn.close()

    def get_db():
        connection = sqlite3.connect(db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    migrated = DeviceRegistry(get_db)
    migrated.ensure_tables()
    rows = migrated.get_recent_telemetry("legacy-device", tenant_id="acme")
    assert len(rows) == 1
    assert rows[0]["payload"]["hashrate_hs"] == 6_000
