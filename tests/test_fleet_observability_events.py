"""Structured Fleet event contracts for Issue #629."""

import logging
import sqlite3
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

from app import app as _app
from axe_fleet import routes
from axe_fleet.registry import DeviceRegistry
from core.registry import detector
from services.auth import create_token
from services import observability, pool_detection


@pytest.fixture
def registry(tmp_path):
    """Create a registry using an isolated SQLite database."""
    db_path = str(tmp_path / "fleet-events.sqlite")

    def get_db():
        connection = sqlite3.connect(db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    result = DeviceRegistry(get_db)
    result.ensure_tables()
    return result


@pytest.fixture
def client(monkeypatch):
    """Create the app test client with a deterministic signing secret."""
    monkeypatch.setenv("SECRET_KEY", "fleet-event-test-secret-1234567890")
    _app.config["TESTING"] = True
    saved_secret = _app.config.get("JWT_SECRET_KEY")
    _app.config["JWT_SECRET_KEY"] = "fleet-event-test-secret-1234567890"
    yield _app.test_client()
    if saved_secret is None:
        _app.config.pop("JWT_SECRET_KEY", None)
    else:
        _app.config["JWT_SECRET_KEY"] = saved_secret


@pytest.fixture
def user_token():
    """Issue an admin token for the route tenant used by scan tests."""
    return create_token(subject="acme", extra_claims={"role": "admin"})


def test_emit_event_has_correlation_and_drops_unapproved_fields(caplog):
    """Events use the JSON context contract and reject raw/sensitive fields."""
    observability.set_request_id("req-fleet-event-001")
    caplog.set_level(logging.INFO, logger="cypher65")
    try:
        observability.emit_event(
            "miner.offline",
            tenant_id="tenant-a",
            device_id="device-1",
            apiKey="not-for-logs",
            pool_user="pool-wallet-identity",
            reason="telemetry_timeout",
            raw_payload=object(),
        )
    finally:
        observability.clear_request_id()

    record = next(
        record for record in caplog.records if record.getMessage() == "fleet event"
    )
    assert record.ctx["event"] == "miner.offline"
    assert record.ctx["tenant_id"] == "tenant-a"
    assert record.ctx["device_id"] == "device-1"
    assert record.ctx["request_id"] == "req-fleet-event-001"
    assert isinstance(record.ctx["ts"], int)
    assert record.ctx["reason"] == "telemetry_timeout"
    assert "apiKey" not in record.ctx
    assert "pool_user" not in record.ctx
    assert "raw_payload" not in record.ctx
    assert "not-for-logs" not in repr(record.ctx)
    assert "pool-wallet-identity" not in repr(record.ctx)


def test_emit_event_uses_event_correlation_when_context_is_absent(caplog):
    """Background events still carry a correlation ID when no request is active."""
    observability.clear_request_id()
    caplog.set_level(logging.INFO, logger="cypher65")

    observability.emit_event("fleet.discovery.finished", scan_id="scan-1")

    record = next(
        record for record in caplog.records if record.getMessage() == "fleet event"
    )
    assert record.ctx["event"] == "fleet.discovery.finished"
    assert record.ctx["request_id"].startswith("evt-")


def test_event_logging_failure_never_escapes_business_path(monkeypatch):
    """A failing custom logging handler cannot raise into the caller."""

    def fail(*_args, **_kwargs):
        raise RuntimeError("logging unavailable")

    monkeypatch.setattr(observability.log, "info", fail)
    observability.emit_event(
        "miner.offline", tenant_id="tenant-a", device_id="device-1"
    )


def test_status_events_are_edge_triggered_for_repeated_offline_heartbeats(
    registry, caplog
):
    """Repeated identical status updates emit one offline event per transition."""
    caplog.set_level(logging.INFO, logger="cypher65")
    device = registry.upsert_agent_device("192.0.2.10", tenant_id="tenant-a")
    registry.update_device(device["id"], {"status": "ONLINE"}, tenant_id="tenant-a")
    caplog.clear()

    registry.save_agent_telemetry(device["id"], {}, tenant_id="tenant-a")
    registry.save_agent_telemetry(device["id"], {}, tenant_id="tenant-a")

    events = [
        record.ctx for record in caplog.records if record.getMessage() == "fleet event"
    ]
    offline = [event for event in events if event["event"] == "miner.offline"]
    assert len(offline) == 1
    assert offline[0]["tenant_id"] == "tenant-a"
    assert offline[0]["device_id"] == device["id"]
    assert offline[0]["previous_status"] == "ONLINE"
    assert offline[0]["status"] == "OFFLINE"


def test_status_events_report_stale_and_recovery_transitions(registry, caplog):
    """Stale and recovered status are each emitted only at their edge."""
    caplog.set_level(logging.INFO, logger="cypher65")
    device = registry.upsert_agent_device("192.0.2.11", tenant_id="tenant-b")
    old_sample = {
        "ts": int(time.time()) - 3600,
        "hashrate_hs": 4_000_000_000,
        "shares_accepted": 10,
        "best_diff": "100",
    }

    registry.save_agent_telemetry(device["id"], old_sample, tenant_id="tenant-b")
    registry.save_agent_telemetry(device["id"], old_sample, tenant_id="tenant-b")
    registry.save_agent_telemetry(
        device["id"],
        {
            "ts": int(time.time()),
            "hashrate_hs": 4_000_000_000,
            "shares_accepted": 11,
            "best_diff": "101",
        },
        tenant_id="tenant-b",
    )

    events = [
        record.ctx["event"]
        for record in caplog.records
        if record.getMessage() == "fleet event"
    ]
    assert events.count("miner.telemetry.stale") == 1
    assert events.count("miner.online") == 1
    assert events.count("miner.telemetry.received") == 1
    assert events.count("share.stale") == 1
    assert events.count("share.updated") == 1


def test_concurrent_same_status_updates_emit_one_offline_edge(registry, caplog):
    """SQLite row serialization prevents concurrent duplicate transition logs."""
    caplog.set_level(logging.INFO, logger="cypher65")
    device = registry.upsert_agent_device("192.0.2.12", tenant_id="tenant-c")
    registry.update_device(device["id"], {"status": "ONLINE"}, tenant_id="tenant-c")
    caplog.clear()

    def mark_offline(_index):
        return registry.update_device(
            device["id"], {"status": "OFFLINE"}, tenant_id="tenant-c"
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all(pool.map(mark_offline, range(8)))

    events = [
        record.ctx["event"]
        for record in caplog.records
        if record.getMessage() == "fleet event"
    ]
    assert events.count("miner.offline") == 1


def test_concurrent_same_share_snapshot_emits_one_update(registry, caplog):
    """Concurrent equal share snapshots serialize against persisted telemetry."""
    caplog.set_level(logging.INFO, logger="cypher65")
    device = registry.upsert_agent_device("192.0.2.13", tenant_id="tenant-share")
    registry.save_agent_telemetry(
        device["id"],
        {
            "ts": int(time.time()),
            "hashrate_hs": 1_000_000,
            "shares_accepted": 10,
        },
        tenant_id="tenant-share",
    )
    caplog.clear()

    def save_snapshot(index):
        return registry.save_telemetry(
            device["id"],
            {
                "ts": int(time.time()) + index,
                "hashrate_hs": 1_000_000,
                "shares_accepted": 11,
            },
            tenant_id="tenant-share",
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all(pool.map(save_snapshot, range(8)))

    events = [
        record.ctx["event"]
        for record in caplog.records
        if record.getMessage() == "fleet event"
    ]
    assert events.count("share.updated") == 1


def test_share_update_dedup_does_not_require_hashrate(registry, caplog):
    """Share telemetry can be valid even when a device omits hashrate."""
    caplog.set_level(logging.INFO, logger="cypher65")
    device = registry.upsert_agent_device("192.0.2.14", tenant_id="tenant-share-nohr")
    caplog.clear()

    for offset in range(3):
        registry.save_telemetry(
            device["id"],
            {"ts": int(time.time()) + offset, "shares_accepted": 11},
            tenant_id="tenant-share-nohr",
        )

    events = [
        record.ctx["event"]
        for record in caplog.records
        if record.getMessage() == "fleet event"
    ]
    assert events.count("share.updated") == 1


def test_stale_share_sample_does_not_replace_fresh_event_baseline(registry, caplog):
    """An old replay cannot make a previously reported share count look new."""
    caplog.set_level(logging.INFO, logger="cypher65")
    device = registry.upsert_agent_device("192.0.2.15", tenant_id="tenant-share-stale")
    now = int(time.time())
    registry.save_telemetry(
        device["id"],
        {"ts": now, "hashrate_hs": 1_000_000, "shares_accepted": 100},
        tenant_id="tenant-share-stale",
    )
    registry.save_telemetry(
        device["id"],
        {"ts": now - 3600, "shares_accepted": 90},
        tenant_id="tenant-share-stale",
    )
    caplog.clear()

    registry.save_telemetry(
        device["id"],
        {
            "ts": now + 1,
            "hashrate_hs": 1_000_000,
            "shares_accepted": 100,
        },
        tenant_id="tenant-share-stale",
    )

    events = [
        record.ctx["event"]
        for record in caplog.records
        if record.getMessage() == "fleet event"
    ]
    assert "share.updated" not in events


def test_agent_liveness_emits_only_connection_edges(monkeypatch, caplog):
    """Heartbeat TTL transitions emit connect/disconnect once without IP data."""
    monkeypatch.setattr(routes, "_agent_heartbeats", {})
    monkeypatch.setattr(routes, "_agent_liveness", {})
    caplog.set_level(logging.INFO, logger="cypher65")

    routes._store_agent_heartbeat("tenant-presence", {}, now=1_000)
    assert routes.agent_presence("tenant-presence", now=1_091)["alive"] is False
    assert routes.agent_presence("tenant-presence", now=1_092)["alive"] is False
    routes._store_agent_heartbeat("tenant-presence", {}, now=1_093)

    events = [
        record.ctx for record in caplog.records if record.getMessage() == "fleet event"
    ]
    assert [event["event"] for event in events] == [
        "fleet.agent.connected",
        "fleet.agent.disconnected",
        "fleet.agent.connected",
    ]
    assert all(event["tenant_id"] == "tenant-presence" for event in events)
    assert all("ip_address" not in event for event in events)


def test_scan_route_emits_correlated_lifecycle_without_network_identifiers(
    client, user_token, monkeypatch, caplog
):
    """The scan route reports safe lifecycle events for found/unidentified hosts."""
    from unittest.mock import patch

    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.setattr(routes, "_scans", {})
    caplog.set_level(logging.INFO, logger="cypher65")
    scan_result = {
        "total": 2,
        "found": [{"ip": "192.168.1.20", "type": "bitaxe"}],
        "alive": 1,
        "alive_ips": ["192.168.1.21"],
        "rejected_reasons": {"auth": 1},
    }
    with patch("axe_fleet.scanner.scan_subnet", return_value=scan_result):
        response = client.post(
            "/api/axe-fleet/scan",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"cidr": "192.168.1.0/24"},
        )
        assert response.status_code == 202
        scan_id = response.get_json()["scan_id"]
        for _ in range(100):
            client.get(
                f"/api/axe-fleet/scan/{scan_id}",
                headers={"Authorization": f"Bearer {user_token}"},
            )
            if any(
                record.getMessage() == "fleet event"
                and record.ctx.get("event") == "fleet.discovery.finished"
                for record in caplog.records
            ):
                break
            time.sleep(0.01)

    events = [
        record.ctx for record in caplog.records if record.getMessage() == "fleet event"
    ]
    names = [event["event"] for event in events]
    assert names == [
        "fleet.discovery.started",
        "fleet.discovery.device_found",
        "fleet.discovery.device_rejected",
        "fleet.discovery.finished",
    ]
    assert len({event["request_id"] for event in events}) == 1
    assert all(event["tenant_id"] == "acme" for event in events)
    assert all("cidr" not in event and "ip_address" not in event for event in events)
    rejected = next(
        event for event in events if event["event"] == "fleet.discovery.device_rejected"
    )
    assert rejected["reason"] == "auth"
    assert rejected["count"] == 1


def test_scanner_preserves_safe_detector_reason_counts(monkeypatch):
    """Scan result carries category counts, never rejected host addresses."""
    from unittest.mock import patch

    from axe_fleet.scanner import scan_subnet

    with (
        patch(
            "core.registry.detector.detect_firmware",
            return_value={"reachable": False, "failure_reason": "auth"},
        ),
        patch("axe_fleet.scanner._tcp_open", return_value=True),
    ):
        result = scan_subnet("192.168.9.1/32", workers=1)

    assert result["rejected_reasons"] == {"auth": 1}
    assert "alive_ips" in result  # legacy diagnostics remain available to callers
    assert "192.168.9.1" not in repr(result["rejected_reasons"])


def test_manual_add_route_emits_success_without_address_or_probe_data(
    client, user_token, registry, monkeypatch, caplog
):
    """Manual registration records outcome, never the supplied LAN address."""
    from unittest.mock import patch

    monkeypatch.delenv("RENDER", raising=False)
    caplog.set_level(logging.INFO, logger="cypher65")
    with (
        patch.object(routes, "_registry", registry),
        patch.object(routes, "_can_add_worker", return_value=True),
        patch("axe_fleet.registry.AxeOSConnector") as connector,
        patch(
            "core.registry.detector.detect_firmware",
            return_value={"reachable": True, "adapter_type": "bitaxe"},
        ),
    ):
        connector.return_value.fetch_info.return_value = {}
        response = client.post(
            "/api/axe-fleet/devices",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"ip_address": "192.168.1.44", "name": "Test miner"},
        )

    assert response.status_code == 201
    events = [
        record.ctx for record in caplog.records if record.getMessage() == "fleet event"
    ]
    assert [event["event"] for event in events] == [
        "manual_add.started",
        "manual_add.success",
    ]
    assert events[-1]["device_id"] == response.get_json()["device"]["id"]
    assert all("ip_address" not in event for event in events)
    assert all("192.168.1.44" not in repr(event) for event in events)


@pytest.mark.parametrize("reason", ["dns", "timeout", "refused", "auth"])
def test_manual_add_route_reports_safe_probe_failure_reason(
    client, user_token, registry, monkeypatch, caplog, reason
):
    """A failed probe is distinct from successful registry creation."""
    from unittest.mock import patch

    monkeypatch.delenv("RENDER", raising=False)
    caplog.set_level(logging.INFO, logger="cypher65")
    with (
        patch.object(routes, "_registry", registry),
        patch.object(routes, "_can_add_worker", return_value=True),
        patch("axe_fleet.registry.AxeOSConnector") as connector,
        patch(
            "core.registry.detector.resolve_private_target",
            side_effect=(
                ValueError("hostname could not be resolved")
                if reason == "dns"
                else None
            ),
            return_value="192.168.1.45",
        ),
        patch(
            "core.registry.detector.detect_firmware",
            return_value={"reachable": False, "failure_reason": reason},
        ),
    ):
        connector.return_value.fetch_info.return_value = {}
        response = client.post(
            "/api/axe-fleet/devices",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"ip_address": "192.168.1.45", "name": "Probe failure"},
        )

    assert response.status_code == 201
    events = [
        record.ctx for record in caplog.records if record.getMessage() == "fleet event"
    ]
    failed = next(event for event in events if event["event"] == "manual_add.failed")
    assert failed["stage"] == "probe"
    assert failed["reason"] == reason
    assert all("192.168.1.45" not in repr(event) for event in events)


@pytest.mark.parametrize("reason", ["auth", "timeout", "refused"])
def test_detector_returns_only_safe_probe_failure_categories(monkeypatch, reason):
    """Detector summarizes HTTP/socket failures without exposing exceptions."""
    if reason == "auth":
        monkeypatch.setattr(
            detector.requests,
            "get",
            lambda *_args, **_kwargs: MagicMock(status_code=401),
        )
    elif reason == "timeout":
        monkeypatch.setattr(
            detector.requests,
            "get",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                detector.requests.Timeout("timeout detail must not escape")
            ),
        )
    else:
        monkeypatch.setattr(
            detector.requests,
            "get",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                detector.requests.ConnectionError("connection refused")
            ),
        )

    class RefusedSocket:
        def __init__(self, *_args, **_kwargs):
            pass

        def settimeout(self, _timeout):
            return None

        def connect(self, _target):
            if reason == "timeout":
                raise socket.timeout("timeout detail must not escape")
            raise ConnectionRefusedError("socket detail must not escape")

    monkeypatch.setattr(detector.socket, "socket", RefusedSocket)
    result = detector.detect_firmware("192.168.1.46", timeout=0.01)
    assert result["reachable"] is False
    assert result["failure_reason"] == reason
    assert "detail" not in repr(result)


def test_pool_provider_event_is_edge_triggered(monkeypatch, caplog):
    """Repeated stats/cache reads do not spam pool discovery events."""
    monkeypatch.setattr(pool_detection, "_LAST_DETECTED_PROVIDER", {})
    caplog.set_level(logging.INFO, logger="cypher65")
    report = {"device_id": "device-pool-1"}

    def result(provider_id):
        return {
            "detection": {"provider_id": provider_id, "pool_type": "solo"},
            "stats": {"source": "asic"},
        }

    pool_detection._emit_detected_pool("tenant-pool", report, result("pool-a"))
    pool_detection._emit_detected_pool("tenant-pool", report, result("pool-a"))
    pool_detection._emit_detected_pool("tenant-pool", report, result("pool-b"))

    events = [
        record.ctx for record in caplog.records if record.getMessage() == "fleet event"
    ]
    assert [event["provider_id"] for event in events] == ["pool-a", "pool-b"]
    assert all(event["device_id"] == "device-pool-1" for event in events)
    assert all("pool_url" not in event and "pool_user" not in event for event in events)


def test_detected_pool_cache_path_emits_safe_provider_event(
    registry, monkeypatch, caplog
):
    """The real report/cache path invokes the emitter without external API I/O."""
    monkeypatch.setattr(pool_detection, "_REPORT_CACHE", {})
    monkeypatch.setattr(pool_detection, "_STATS_CACHE", {})
    monkeypatch.setattr(pool_detection, "_LAST_DETECTED_PROVIDER", {})
    device = registry.upsert_agent_device("192.0.2.20", tenant_id="tenant-pool-path")
    registry.save_telemetry(
        device["id"],
        {
            "ts": int(time.time()),
            "pool_url": "stratum+tcp://private-pool.example:3333",
            "pool_user": "wallet-worker-secret",
        },
        tenant_id="tenant-pool-path",
    )
    monkeypatch.setattr(
        pool_detection,
        "_resolve",
        lambda *_args, **_kwargs: {
            "detection": {"provider_id": "pool-a", "pool_type": "solo"},
            "stats": {"source": "asic"},
        },
    )
    caplog.set_level(logging.INFO, logger="cypher65")

    pool_detection.detected_pool_for(
        "wallet-address", "tenant-pool-path", get_db=registry._get_db, now=1000.0
    )
    pool_detection.detected_pool_for(
        "wallet-address", "tenant-pool-path", get_db=registry._get_db, now=1010.0
    )

    events = [
        record.ctx for record in caplog.records if record.getMessage() == "fleet event"
    ]
    pool_events = [event for event in events if event["event"] == "miner.pool.detected"]
    assert len(pool_events) == 1
    assert pool_events[0]["provider_id"] == "pool-a"
    assert pool_events[0]["device_id"] == device["id"]
    assert "wallet-worker-secret" not in repr(pool_events)
    assert "private-pool.example" not in repr(pool_events)
