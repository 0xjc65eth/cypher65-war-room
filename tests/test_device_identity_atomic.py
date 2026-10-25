"""Issue #813: real SQLite identity, lifecycle races and atomic sample effects."""

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from agent import agent
from axe_fleet.axeos_contract import official_esp_miner_info
from axe_fleet.connector import AxeOSConnectorError
from axe_fleet.registry import DeviceIdentityConflict, DeviceRegistry, DeviceRemoved

MAC_A = "02:11:22:33:44:55"
MAC_B = "02:11:22:33:44:66"
IP_A = "192.0.2.10"
IP_B = "192.0.2.11"


@pytest.fixture
def registry(tmp_path):
    db = tmp_path / "identity.sqlite"

    def connect():
        conn = sqlite3.connect(db, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    result = DeviceRegistry(connect)
    result.ensure_tables()
    return result


def register(registry, ip=IP_A, mac=MAC_A, tenant="acme"):
    return registry.upsert_agent_device(ip, tenant_id=tenant, info={"mac": mac})


def sample(registry, device, **kwargs):
    return registry.save_agent_telemetry(
        device["id"],
        {"ts": int(time.time()), "hashrate_hs": 1000},
        tenant_id="acme",
        identity_mac=MAC_A,
        expected_ip=IP_A,
        **kwargs,
    )


@pytest.mark.parametrize(
    "mac", [None, "", "invalid", "00:00:00:00:00:00", "01:00:5E:00:00:01"]
)
def test_missing_mac_never_seizes_known_row(registry, mac):
    device = register(registry)
    with pytest.raises(DeviceIdentityConflict, match="physical MAC"):
        registry.upsert_agent_device(
            IP_A, name="different miner", tenant_id="acme", info={"mac": mac}
        )
    assert registry.get_device(device["id"], tenant_id="acme") == device
    assert len(registry.list_devices(tenant_id="acme")) == 1


def test_unknown_legacy_mac_at_ip_is_not_adopted(registry):
    device = register(registry)
    with registry._get_db() as conn:
        conn.execute("DELETE FROM axe_device_identity_aliases")
        conn.execute(
            "UPDATE axe_devices SET mac_address='' WHERE id=?", (device["id"],)
        )
    with pytest.raises(DeviceIdentityConflict, match="IP locator"):
        register(registry, mac=MAC_B)
    assert registry.get_device(device["id"], tenant_id="acme")["mac_address"] == ""


@pytest.mark.parametrize("stored_mac", [MAC_B, ""])
def test_alias_cannot_override_contradictory_row(registry, stored_mac):
    device = register(registry)
    with registry._get_db() as conn:
        conn.execute(
            "UPDATE axe_devices SET mac_address=? WHERE id=?",
            (stored_mac, device["id"]),
        )
    with pytest.raises(DeviceIdentityConflict, match="canonical row"):
        register(registry, ip=IP_B)
    assert registry.get_device(device["id"], tenant_id="acme")["ip_address"] == IP_A


def test_concurrent_manual_and_multiple_agents_converge_history_and_commands(registry):
    info = official_esp_miner_info(macAddr=MAC_A)
    with patch("axe_fleet.registry.AxeOSConnector") as connector:
        connector.return_value.fetch_info.return_value = info
        connector.return_value.detect_capabilities.return_value = {"telemetry": True}
        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(
                pool.map(
                    lambda i: (
                        registry.add_device(IP_A, tenant_id="acme")
                        if i % 2
                        else register(registry)
                    )["id"],
                    range(16),
                )
            )
    assert len(set(ids)) == 1
    device = registry.get_device(ids[0], tenant_id="acme")
    registry.save_telemetry(
        device["id"], {"ts": 123, "hashrate_hs": 1234}, tenant_id="acme"
    )
    command = registry.enqueue_agent_command(device["id"], "identify", tenant_id="acme")
    moved = register(registry, ip=IP_B)
    assert moved["id"] == device["id"]
    assert len(registry.list_devices(tenant_id="acme")) == 1
    assert (
        registry.get_recent_telemetry(device["id"], tenant_id="acme")[0]["payload"][
            "hashrate_hs"
        ]
        == 1234
    )
    with registry._get_db() as conn:
        assert (
            conn.execute(
                "SELECT device_id FROM axe_agent_commands WHERE id=?", (command["id"],)
            ).fetchone()[0]
            == device["id"]
        )
    assert register(registry, tenant="other")["id"] != device["id"]


@pytest.mark.parametrize("changed", ["move", "remove"])
def test_preflight_race_rechecks_identity_without_any_effect(
    registry, monkeypatch, changed
):
    device = register(registry)
    callbacks = []
    registry.on_telemetry_committed = lambda *args: callbacks.append(args)
    registry.record_telemetry_quarantine(
        device["id"], ["temperature"], ["invalid"], tenant_id="acme"
    )
    entered, release = threading.Event(), threading.Event()
    original = registry._persist_live_telemetry

    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(registry, "_persist_live_telemetry", delayed)
    with patch("axe_fleet.registry.emit_event") as emit:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(sample, registry, device)
            assert entered.wait(5)
            if changed == "move":
                register(registry, ip=IP_B)
            else:
                registry.remove_device(device["id"], tenant_id="acme")
            quarantine_after_change = registry.get_telemetry_quarantines(
                tenant_id="acme"
            )
            release.set()
            with pytest.raises(DeviceIdentityConflict):
                pending.result(5)
        assert not emit.called
    assert registry.get_recent_telemetry(device["id"], tenant_id="acme") == []
    assert (
        registry.get_telemetry_quarantines(tenant_id="acme") == quarantine_after_change
    )
    assert callbacks == []


def test_sql_failure_after_insert_rolls_back_history_state_and_quarantine(registry):
    device = register(registry)
    registry.record_telemetry_quarantine(
        device["id"], ["temperature"], ["invalid"], tenant_id="acme"
    )
    callbacks = []
    registry.on_telemetry_committed = lambda *args: callbacks.append(args)
    with registry._get_db() as conn:
        conn.execute(
            "CREATE TRIGGER deny_sample_state BEFORE UPDATE OF status ON axe_devices BEGIN SELECT RAISE(ABORT, 'injected state failure'); END"
        )
    with patch("axe_fleet.registry.emit_event") as emit:
        with pytest.raises(sqlite3.IntegrityError, match="injected state failure"):
            sample(registry, device, idempotency_key="atomic-event-001")
        assert not emit.called
    assert callbacks == []
    assert registry.get_recent_telemetry(device["id"], tenant_id="acme") == []
    assert registry.get_device(device["id"], tenant_id="acme") == device
    assert registry.get_telemetry_quarantines(tenant_id="acme").get(device["id"])


def test_replay_preserves_newer_quarantine_and_does_not_repeat_events(registry):
    device = register(registry)
    event = {"ts": int(time.time()), "hashrate_hs": 1000}
    registry.save_agent_telemetry(device["id"], event, "acme", "atomic-event-002")
    registry.record_telemetry_quarantine(
        device["id"], ["temperature"], ["invalid"], tenant_id="acme"
    )
    before = registry.get_device(device["id"], tenant_id="acme")
    callbacks = []
    registry.on_telemetry_committed = lambda *args: callbacks.append(args)
    with patch("axe_fleet.registry.emit_event") as emit:
        assert (
            registry.save_agent_telemetry(
                device["id"], event, "acme", "atomic-event-002"
            )
            == "ONLINE"
        )
        assert not emit.called
    assert callbacks == []
    assert registry.get_device(device["id"], tenant_id="acme") == before
    assert registry.get_telemetry_quarantines(tenant_id="acme").get(device["id"])
    assert len(registry.get_recent_telemetry(device["id"], tenant_id="acme")) == 1


@pytest.mark.parametrize("observed_mac", [MAC_B, "", None])
def test_backend_poll_rejects_changed_or_missing_observed_mac(registry, observed_mac):
    device = register(registry)
    with patch("axe_fleet.registry.AxeOSConnector") as connector:
        connector.return_value.extract_telemetry.return_value = {
            "hashrate_hs": 2000,
            "mac": observed_mac,
        }
        assert registry.poll_device(device["id"], tenant_id="acme") == {}
    assert registry.get_device(device["id"], tenant_id="acme") == device
    assert registry.get_recent_telemetry(device["id"], tenant_id="acme") == []


@pytest.mark.parametrize("failed_probe", [False, True])
def test_poll_in_flight_cannot_write_after_dhcp(registry, failed_probe):
    device = register(registry)
    registry.update_device(device["id"], {"status": "ONLINE"}, tenant_id="acme")
    entered, release = threading.Event(), threading.Event()

    def probe():
        entered.set()
        assert release.wait(5)
        if failed_probe:
            raise AxeOSConnectorError("offline")
        return {"ts": int(time.time()), "hashrate_hs": 2000, "mac": MAC_A}

    with patch("axe_fleet.registry.AxeOSConnector") as connector:
        connector.return_value.extract_telemetry.side_effect = probe
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(registry.poll_device, device["id"], "acme")
            assert entered.wait(5)
            moved = register(registry, ip=IP_B)
            release.set()
            assert pending.result(5) == {}
    assert registry.get_device(device["id"], tenant_id="acme") == moved
    assert registry.get_recent_telemetry(device["id"], tenant_id="acme") == []


def test_poll_preserves_local_ownership_and_notifies_after_commit(registry):
    device = register(registry)
    registry.update_device(device["id"], {"agent_managed": 0}, tenant_id="acme")
    observed = []

    def committed(device_id, payload, status):
        # Independent connection sees BOTH state and sample; no borrowed tx.
        observed.append(
            (
                registry.get_device(device_id, tenant_id="acme")["status"],
                len(registry.get_recent_telemetry(device_id, tenant_id="acme")),
            )
        )

    registry.on_telemetry_committed = committed
    with patch("axe_fleet.registry.AxeOSConnector") as connector:
        connector.return_value.extract_telemetry.return_value = {
            "ts": int(time.time()),
            "hashrate_hs": 2000,
            "mac": MAC_A,
        }
        assert (
            registry.poll_device(device["id"], tenant_id="acme")["hashrate_hs"] == 2000
        )
    assert observed == [("ONLINE", 1)]
    assert registry.get_device(device["id"], tenant_id="acme")["agent_managed"] == 0


@pytest.mark.parametrize("observed", [MAC_B, None, ""])
def test_agent_poll_marks_contradictory_identity_unresolved(monkeypatch, observed):
    dev = {"ip": IP_A, "mac": MAC_A, "type": "bitaxe"}
    monkeypatch.setattr(
        agent, "_probe_axeos", lambda ip: official_esp_miner_info(macAddr=observed)
    )
    assert agent._poll_telemetry(dev) == {}
    assert agent._identity_unresolved(dev)


def test_tombstone_blocks_sample_and_registration_at_old_and_new_locator(registry):
    device = register(registry)
    assert registry.remove_device(device["id"], tenant_id="acme")
    assert register(registry) == {}
    assert register(registry, ip=IP_B) == {}
    with pytest.raises(DeviceRemoved):
        sample(registry, device)
    with pytest.raises(DeviceIdentityConflict):
        register(registry, mac=MAC_B)
    assert registry.get_recent_telemetry(device["id"], tenant_id="acme") == []


@pytest.fixture
def api(registry, monkeypatch):
    from flask import Flask
    from axe_fleet import routes
    from services.auth import create_token

    app = Flask("identity_contract")
    app.config.update(
        TESTING=True,
        JWT_SECRET_KEY="identity-contract-test-secret-012345",
        SECRET_KEY="identity-contract-test-secret-012345",
    )
    app.register_blueprint(routes.agent_bp)
    monkeypatch.setattr(routes, "_registry", registry)
    monkeypatch.setattr(routes, "_log_audit", lambda *args, **kwargs: None)
    with app.app_context():
        token = create_token(
            subject="acme", extra_claims={"agent": True, "role": "agent"}
        )
    return app.test_client(), {"Authorization": f"Bearer {token}"}


def test_api_old_ip_cannot_attribute_a_sample_to_new_occupant(api, registry):
    client, headers = api
    original = register(registry)
    register(registry, ip=IP_B)
    occupant = register(registry, mac=MAC_B)
    response = client.post(
        "/api/agent/telemetry",
        headers=headers,
        json={
            "ip": IP_A,
            "mac": MAC_A,
            "device_id": original["id"],
            "telemetry": {"hashrate_hs": 123_000_000_000},
        },
    )
    assert response.status_code == 409
    assert response.get_json()["code"] == "DEVICE_IDENTITY_CONFLICT"
    assert registry.get_recent_telemetry(original["id"], tenant_id="acme") == []
    assert registry.get_recent_telemetry(occupant["id"], tenant_id="acme") == []
    assert len(registry.list_devices(tenant_id="acme")) == 2


@pytest.mark.parametrize("mac", [None, "", "bad", "01:00:5E:00:00:01"])
def test_api_missing_mac_cannot_autocreate_or_quarantine_by_ip(api, registry, mac):
    client, headers = api
    device = register(registry)
    for ip in (IP_A, IP_B):
        response = client.post(
            "/api/agent/telemetry",
            headers=headers,
            json={
                "ip": ip,
                "mac": mac,
                "telemetry": {"hashrate_hs": "bad"},
            },
        )
        assert response.status_code == 409
    assert registry.get_device(device["id"], tenant_id="acme") == device
    assert registry.get_telemetry_quarantines(tenant_id="acme") == {}
    assert len(registry.list_devices(tenant_id="acme")) == 1


@pytest.mark.parametrize("contradiction", ["envelope_id", "sample_id", "sample_mac"])
def test_api_conflicting_sample_evidence_is_json_conflict(api, registry, contradiction):
    client, headers = api
    device = register(registry)
    event = {"ip": IP_A, "mac": MAC_A, "telemetry": {"hashrate_hs": 1000}}
    if contradiction == "envelope_id":
        event["device_id"] = "different"
    elif contradiction == "sample_id":
        event["telemetry"]["device_id"] = "different"
    else:
        event["telemetry"]["mac"] = MAC_B
    response = client.post("/api/agent/telemetry", headers=headers, json=event)
    assert response.status_code == 409
    assert response.is_json
    assert registry.get_recent_telemetry(device["id"], tenant_id="acme") == []


def test_batch_register_reports_each_conflict_and_keeps_nominal_identity(api, registry):
    client, headers = api
    first = register(registry)
    response = client.post(
        "/api/agent/register",
        headers=headers,
        json={
            "devices": [
                {"ip": IP_A, "mac": MAC_B},
                {"ip": IP_A, "mac": None},
                {"ip": IP_B, "mac": MAC_A},
                None,
            ]
        },
    )
    assert response.status_code == 201
    body = response.get_json()
    assert body["count"] == 1
    assert body["registered"][0]["id"] == first["id"]
    assert body["blocked_count"] == 3
    assert (
        body["blocked"][0]["code"]
        == body["blocked"][1]["code"]
        == "DEVICE_IDENTITY_CONFLICT"
    )
    assert len(registry.list_devices(tenant_id="acme")) == 1


def test_invalid_sample_quarantine_rechecks_locator_before_mutating(registry):
    device = register(registry)
    register(registry, ip=IP_B)
    with pytest.raises(DeviceIdentityConflict):
        registry.record_telemetry_quarantine(
            device["id"],
            ["temperature"],
            ["invalid"],
            tenant_id="acme",
            identity_mac=MAC_A,
            expected_ip=IP_A,
        )
    assert registry.get_telemetry_quarantines(tenant_id="acme") == {}


def test_agent_changed_mac_is_not_sent_as_cached_identity_heartbeat(monkeypatch):
    from types import SimpleNamespace

    dev = {"ip": IP_A, "mac": MAC_A, "type": "bitaxe"}
    sent = []

    class StopLoop(Exception):
        pass

    def post(path, payload, **kwargs):
        sent.append((path, payload))
        if path.endswith("register"):
            return 201, {"count": 1, "blocked": []}
        return 200, {"commands": []}

    def stop(seconds):
        raise StopLoop

    monkeypatch.setattr(agent, "EXPLICIT_DEVICES", [])
    monkeypatch.setattr(agent, "RESCAN_EVERY", 100)
    monkeypatch.setattr(agent, "scan_lan", lambda: [dev])
    monkeypatch.setattr(
        agent, "_probe_axeos", lambda ip: official_esp_miner_info(macAddr=MAC_B)
    )
    monkeypatch.setattr(agent, "_post", post)
    monkeypatch.setattr(agent, "time", SimpleNamespace(time=time.time, monotonic=time.monotonic, sleep=stop))
    with pytest.raises(StopLoop):
        agent._run_main()
    assert dev["identity_conflict"]
    assert not [item for item in sent if item[0].endswith("telemetry")]


def test_delayed_old_publisher_cannot_replace_new_sample_cache_or_emit_old_status(
    registry, monkeypatch
):
    device = register(registry)
    first_committed, release_first = threading.Event(), threading.Event()
    original = registry._notify_telemetry_committed
    cache = {}
    registry.on_telemetry_committed = lambda did, payload, status: cache.update(
        {"hashrate_hs": payload.get("hashrate_hs"), "status": status}
    )

    def delayed(*args, **kwargs):
        if threading.current_thread().name == "old-publisher":
            first_committed.set()
            assert release_first.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(registry, "_notify_telemetry_committed", delayed)
    errors = []

    def old_sample():
        try:
            registry.save_agent_telemetry(
                device["id"], {"ts": int(time.time()), "hashrate_hs": 100}, "acme"
            )
        except BaseException as error:
            errors.append(error)

    with patch("axe_fleet.registry.emit_event") as emit:
        worker = threading.Thread(target=old_sample, name="old-publisher")
        worker.start()
        assert first_committed.wait(5)
        registry.save_agent_telemetry(
            device["id"], {"ts": int(time.time()), "hashrate_hs": 0}, "acme"
        )
        assert cache == {"hashrate_hs": 0, "status": "IDLE"}
        release_first.set()
        worker.join(5)
        assert not worker.is_alive()
        assert not errors
        assert cache == {"hashrate_hs": 0, "status": "IDLE"}
        assert not [
            call for call in emit.call_args_list if call.args[0] == "miner.online"
        ]
    assert registry.get_device(device["id"], tenant_id="acme")["status"] == "IDLE"


def test_delayed_publisher_does_not_cache_removed_device(registry, monkeypatch):
    device = register(registry)
    first_committed, release = threading.Event(), threading.Event()
    original = registry._notify_telemetry_committed
    cache = []
    registry.on_telemetry_committed = lambda *args: cache.append(args)

    def delayed(*args, **kwargs):
        first_committed.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(registry, "_notify_telemetry_committed", delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(sample, registry, device)
        assert first_committed.wait(5)
        registry.remove_device(device["id"], tenant_id="acme")
        release.set()
        assert (
            pending.result(5) == "ONLINE"
        )  # Sample committed before remove; historical fact.
    assert cache == []
    assert len(registry.get_recent_telemetry(device["id"], tenant_id="acme")) == 1


def test_real_app_registry_hook_and_wrapper_publish_only_committed_rows(
    registry, monkeypatch
):
    import app as app_module

    live = app_module._axe_registry
    monkeypatch.setattr(live, "_get_db", registry._get_db)
    observed = []

    def cache(device_id, payload, status=""):
        observed.append(
            (status, len(registry.get_recent_telemetry(device_id, tenant_id="acme")))
        )

    monkeypatch.setattr(app_module, "_cache_axe_telemetry", cache)
    device = register(live)
    event = {"ts": int(time.time()), "hashrate_hs": 2000}
    assert (
        live.save_agent_telemetry(
            device["id"],
            event,
            "acme",
            "app-hook-event-001",
            identity_mac=MAC_A,
            expected_ip=IP_A,
        )
        == "ONLINE"
    )
    assert observed == [("ONLINE", 1)]
    # The wrapper accepts keys and returns the real insertion/replay bool.
    internal = {"ts": int(time.time()), "hashrate_hs": 0}
    assert (
        live.save_telemetry(device["id"], internal, "acme", "app-hook-event-002")
        is True
    )
    assert (
        live.save_telemetry(device["id"], internal, "acme", "app-hook-event-002")
        is False
    )
    assert len(observed) == 2


def test_manual_enrichment_cannot_mutate_identity_moved_during_probe(
    registry, monkeypatch
):
    from flask import Flask
    from axe_fleet import routes
    from core.registry import detector
    from services.auth import create_token
    import config

    app = Flask("manual_identity_contract")
    app.config.update(
        TESTING=True,
        JWT_SECRET_KEY="manual-identity-test-secret-012345",
        SECRET_KEY="manual-identity-test-secret-012345",
    )
    app.register_blueprint(routes.axe_fleet_bp, url_prefix="/api/axe-fleet")
    monkeypatch.setattr(routes, "_registry", registry)
    monkeypatch.setattr(routes, "_log_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(routes, "_can_add_worker", lambda tenant: True)
    monkeypatch.setattr(config, "is_cloud_deploy", lambda: False)
    monkeypatch.setattr(detector, "resolve_private_target", lambda ip: ip)
    ip = "192.168.12.10"

    def firmware_probe(target):
        original = registry.get_device_by_ip(ip, tenant_id="acme")
        assert original
        register(registry, ip="192.168.12.11")
        return {
            "reachable": True,
            "firmware": "ReplacementB",
            "model": "ReplacementB",
            "version": "B",
            "adapter_type": "axeos",
        }

    monkeypatch.setattr(detector, "detect_firmware", firmware_probe)
    with app.app_context():
        token = create_token(subject="acme", extra_claims={"role": "admin"})
    with patch("axe_fleet.registry.AxeOSConnector") as connector:
        connector.return_value.fetch_info.return_value = official_esp_miner_info(
            macAddr=MAC_A
        )
        connector.return_value.detect_capabilities.return_value = {"telemetry": True}
        response = app.test_client().post(
            "/api/axe-fleet/devices",
            headers={"Authorization": f"Bearer {token}"},
            json={"ip_address": ip},
        )
    assert response.status_code == 409
    current = registry.get_device_by_ip("192.168.12.11", tenant_id="acme")
    assert current
    assert current["model"] != "ReplacementB"
    assert current["firmware_version"] != "B"


def test_real_background_poll_does_not_recache_delayed_return_after_new_sample(
    registry, monkeypatch
):
    import app as app_module

    device = register(registry)
    registry.update_device(device["id"], {"agent_managed": 0}, tenant_id="acme")
    monkeypatch.setattr(app_module, "_axe_registry", registry)
    monkeypatch.setattr(app_module._shared_state, "axe_last_poll_ts", {})
    monkeypatch.setattr(app_module._shared_state, "axe_poll_error_counts", {})
    cache = {}
    monkeypatch.setattr(
        app_module,
        "_cache_axe_telemetry",
        lambda did, tel, status="": cache.update(
            {"hashrate_hs": tel.get("hashrate_hs"), "status": status}
        ),
    )
    registry.on_telemetry_committed = app_module._axe_telemetry_committed
    old_return_waiting, release = threading.Event(), threading.Event()
    original_poll = registry.poll_device

    def delayed_poll(*args, **kwargs):
        tel = original_poll(*args, **kwargs)
        old_return_waiting.set()
        assert release.wait(5)
        return tel

    monkeypatch.setattr(registry, "poll_device", delayed_poll)
    with patch("axe_fleet.registry.AxeOSConnector") as connector:
        connector.return_value.extract_telemetry.return_value = {
            "ts": int(time.time()),
            "hashrate_hs": 1000,
            "mac": MAC_A,
        }
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(app_module._poll_axe_fleet, int(time.time()))
            assert old_return_waiting.wait(5)
            assert cache == {"hashrate_hs": 1000, "status": "ONLINE"}
            assert (
                len(registry.get_recent_telemetry(device["id"], tenant_id="acme")) == 1
            )
            registry.save_agent_telemetry(
                device["id"], {"ts": int(time.time()), "hashrate_hs": 0}, "acme"
            )
            assert cache == {"hashrate_hs": 0, "status": "IDLE"}
            release.set()
            pending.result(5)
    assert cache == {"hashrate_hs": 0, "status": "IDLE"}
