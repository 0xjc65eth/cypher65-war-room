"""Local E2E: scan → register → telemetry → Fleet list, no physical miner."""

import sqlite3
from unittest.mock import patch

import pytest

from app import app
from axe_fleet.registry import DeviceRegistry
from services.auth import create_token
from sim.harness import seeded_profile_uptime
from tests.virtual_hardware.nerdqaxe import VirtualNerdQaxe
import agent.agent as agent


@pytest.fixture
def fleet_pipeline(tmp_path, monkeypatch):
    old_testing = app.config.get("TESTING")
    old_secret = app.config.get("JWT_SECRET_KEY")
    app.config["TESTING"] = True
    app.config["JWT_SECRET_KEY"] = "agent-sim-test-secret-1234567890"
    monkeypatch.setenv("SECRET_KEY", "agent-sim-test-secret-1234567890")

    db_path = str(tmp_path / "sim-fleet.sqlite")

    def get_db():
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        return connection

    registry = DeviceRegistry(get_db)
    registry.ensure_tables()
    client = app.test_client()
    agent_jwt = create_token(
        subject="sim-tenant",
        ttl=3600,
        extra_claims={"agent": True, "role": "agent"},
    )
    viewer_jwt = create_token(subject="sim-tenant", extra_claims={"role": "admin"})
    try:
        with patch("axe_fleet.routes._registry", registry):
            yield client, registry, agent_jwt, viewer_jwt
    finally:
        if old_testing is None:
            app.config.pop("TESTING", None)
        else:
            app.config["TESTING"] = old_testing
        if old_secret is None:
            app.config.pop("JWT_SECRET_KEY", None)
        else:
            app.config["JWT_SECRET_KEY"] = old_secret


@pytest.mark.parametrize("seed", [7, 19, 43])
def test_scan_register_telemetry_and_fleet_listing(fleet_pipeline, monkeypatch, seed):
    """Each seed selects an explicit reproducible synthetic uptime value.

    The firmware contract is fixed by source, not stochastic. The seeded value
    varies only uptime; it is not a physical behavior model.
    """
    client, registry, agent_jwt, viewer_jwt = fleet_pipeline
    agent_headers = {"Authorization": f"Bearer {agent_jwt}"}
    viewer_headers = {"Authorization": f"Bearer {viewer_jwt}"}
    uptime = seeded_profile_uptime(seed)

    with VirtualNerdQaxe(uptime_seconds=uptime) as virtual:
        host, port = virtual.address.split(":")
        assert host == "127.0.0.1"
        assert 0 < int(port) < 65536
        # Avoid the production route-selection helper's UDP route probe to
        # 8.8.8.8; this contract lab must make no non-loopback network calls.
        monkeypatch.setattr(agent, "_local_ipv4_addresses", lambda: [host])
        monkeypatch.setattr(agent, "SCAN_CIDR", f"{host}/32")
        monkeypatch.setattr(agent, "EXPLICIT_DEVICES", [])
        monkeypatch.setattr(agent, "AXEOS_PORT", int(port))

        discovered, report = agent.scan_lan_with_report()
        assert report["result"] == "ok"
        assert report["host_count"] == 1
        assert len(discovered) == 1
        assert discovered[0]["ip"] == host
        assert discovered[0]["hashrate_hs"] == 4_800_000_000_000
        assert discovered[0]["mac"] == "AA:BB:CC:DD:EE:FF"

        registered = client.post(
            "/api/agent/register", headers=agent_headers, json={"devices": discovered}
        )
        assert registered.status_code == 201
        assert registered.get_json()["count"] == 1

        telemetry = agent._poll_telemetry(discovered[0])
        assert telemetry["hashrate_hs"] == 4_800_000_000_000
        assert telemetry["shares_accepted"] == 42
        pushed = client.post(
            "/api/agent/telemetry",
            headers=agent_headers,
            json={"ip": host, "telemetry": telemetry},
        )
        assert pushed.status_code == 200
        assert pushed.get_json()["status"] in ("ONLINE", "HASHING")

        listed = client.get("/api/axe-fleet/devices", headers=viewer_headers)
        assert listed.status_code == 200
        body = listed.get_json()
        assert body["count"] == 1
        device = body["devices"][0]
        assert device["tenant_id"] == "sim-tenant"

        assert device["ip_address"] == host
        assert device["model"] == "NerdQaxe++"
        assert device["mac_address"] == "AA:BB:CC:DD:EE:FF"
        assert device["telemetry"]["hashrate_hs"] == 4_800_000_000_000
        assert device["telemetry"]["shares_accepted"] == 42
        assert device["telemetry"]["uptime_seconds"] == uptime

        # Counterevidence: a different tenant cannot see this device.
        other_tenant = create_token(
            subject="other-tenant", extra_claims={"role": "admin"}
        )
        hidden = client.get(
            "/api/axe-fleet/devices",
            headers={"Authorization": f"Bearer {other_tenant}"},
        )
        assert hidden.status_code == 200
        assert hidden.get_json()["count"] == 0

        assert registry.get_device_by_ip(host, tenant_id="sim-tenant")

        # Exercise a real command/reboot/error/recovery sequence against only
        # the loopback virtual device, never a physical miner.
        restarted = agent._exec_command(
            {"ip_address": host, "command": "restart"},
            known={host: {"type": "bitaxe"}},
        )
        assert restarted == (True, "HTTP 200")
        outage_sample = agent._poll_telemetry(discovered[0])
        assert outage_sample == {}
        outage_push = client.post(
            "/api/agent/telemetry",
            headers=agent_headers,
            json={"ip": host, "telemetry": outage_sample},
        )
        assert outage_push.status_code == 200
        during_outage = client.get("/api/axe-fleet/devices", headers=viewer_headers)
        retained = during_outage.get_json()["devices"][0]
        assert retained["telemetry"]["uptime_seconds"] == uptime
        assert retained["telemetry"]["hashrate_hs"] == 4_800_000_000_000

        recovered = agent._poll_telemetry(discovered[0])
        assert recovered["uptime_seconds"] == 3
        recovery_push = client.post(
            "/api/agent/telemetry",
            headers=agent_headers,
            json={"ip": host, "telemetry": recovered},
        )
        assert recovery_push.status_code == 200
        after_recovery = client.get("/api/axe-fleet/devices", headers=viewer_headers)
        recovered_device = after_recovery.get_json()["devices"][0]
        assert recovered_device["telemetry"]["uptime_seconds"] == 3
        assert recovered_device["telemetry"]["hashrate_hs"] == 4_800_000_000_000
        assert recovered_device["tenant_id"] == "sim-tenant"


def test_seeded_profile_uptime_replays_and_varies():
    assert seeded_profile_uptime(19) == seeded_profile_uptime(19)
    assert len({seeded_profile_uptime(seed) for seed in (7, 19, 43)}) == 3


def test_seeded_profile_rejects_boolean_and_non_integer_seeds():
    with pytest.raises(TypeError, match="seed must be an integer"):
        seeded_profile_uptime(True)
    with pytest.raises(TypeError, match="seed must be an integer"):
        seeded_profile_uptime("19")


def test_fleet_oracle_rejects_hashrate_unit_regression():
    """The strict oracle catches accidental GH/s values in an H/s field."""
    from sim.harness import assert_fleet_matches_ground_truth

    expected = {
        "ip_address": "127.0.0.1",
        "model": "NerdQaxe++",
        "mac_address": "AA:BB:CC:DD:EE:FF",
        "hashrate_hs": 4_800_000_000_000,
        "shares_accepted": 42,
        "uptime_seconds": 7007,
    }
    observed = {**expected, "hashrate_hs": 4_800}

    with pytest.raises(AssertionError, match="hashrate_hs mismatch"):
        assert_fleet_matches_ground_truth(expected, observed)
