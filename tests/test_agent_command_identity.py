"""Issue #842: physical commands use fresh identity and at-most-once delivery.

All transports are replaced with fixtures. No physical or external endpoint is
called, including on the intentionally vulnerable red baseline.
"""

import sqlite3
import time
from unittest.mock import Mock, patch

import pytest

from agent import agent
from axe_fleet.registry import DeviceRegistry, _caps_for_type
from tests.test_agent_command_safety import (  # noqa: F401
    _active_device,
    _command_row,
    _headers,
    agent_token,
    client,
    registry,
)

MAC = "02:00:00:00:05:01"
IP = "192.168.10.20"


def command(**changes):
    result = {
        "id": "fixture-command-842",
        "device_id": "fixture-device-842",
        "ip_address": IP,
        "command": "restart",
        "command_protocol": 1,
        "expected_mac": MAC,
        "expected_type": "bitaxe",
        "expires_at": int(time.time()) + 300,
        "params": {},
    }
    result.update(changes)
    return result


@pytest.fixture
def transports(monkeypatch):
    """Never let a test dispatch escape to an actual socket/HTTP client."""
    http = Mock(return_value=(200, {}))
    tcp = Mock(return_value={"STATUS": [{"STATUS": "S"}]})
    probe = Mock(return_value={"ip": IP, "mac": MAC, "type": "bitaxe"})
    monkeypatch.setattr(agent, "_http_json", http)
    monkeypatch.setattr(agent, "_cgminer_cmd", tcp)
    monkeypatch.setattr(agent, "_probe_host", probe)
    return http, tcp, probe


@pytest.mark.parametrize("info", [{}, {"type": "unknown"}, {"type": "router"}])
def test_unknown_protocol_has_no_mutable_capabilities(info):
    caps = _caps_for_type(info)
    assert caps["telemetry"] is True
    assert not any(
        caps[name] for name in ("restart", "identify", "pause", "resume", "configure")
    )


@pytest.mark.parametrize("firmware", [None, "", "unverified"])
def test_bitaxe_type_alone_does_not_grant_axeos_only_capabilities(firmware):
    caps = _caps_for_type({"type": "bitaxe", "firmware": firmware})
    assert caps["restart"] is True
    assert caps["identify"] is True
    assert not any(caps[name] for name in ("pause", "resume", "configure"))


def test_known_axeos_firmware_preserves_existing_optional_capabilities():
    caps = _caps_for_type({"type": "bitaxe", "firmware": "AxeOS"})
    assert all(caps[name] for name in ("pause", "resume", "configure"))


@pytest.mark.parametrize(
    "changes",
    [
        {"command_protocol": None},
        {"command_protocol": True},
        {"command_protocol": 2},
        {"expected_mac": ""},
        {"expected_mac": "01:00:5E:00:00:01"},
        {"expected_type": "unknown"},
        {"ip_address": "host.example"},
        {"device_id": ""},
        {"params": {"frequency": 900}},
        {"expires_at": None},
        {"expires_at": True},
        {"expires_at": "tomorrow"},
        {"expires_at": 1},
        {"expires_at": 10**1000},
    ],
)
def test_invalid_envelope_never_probes_or_dispatches(transports, changes):
    http, tcp, probe = transports
    ok, _ = agent._exec_command(command(**changes), known={})
    assert ok is False
    probe.assert_not_called()
    http.assert_not_called()
    tcp.assert_not_called()


@pytest.mark.parametrize(
    "observed",
    [
        None,
        {},
        {"ip": IP, "type": "bitaxe", "mac": ""},
        {"ip": IP, "type": "bitaxe", "mac": "02:00:00:00:05:02"},
        {"ip": IP, "type": "cgminer", "mac": MAC},
        {"ip": "192.168.10.21", "type": "bitaxe", "mac": MAC},
    ],
)
def test_current_identity_not_cached_locator_controls_dispatch(transports, observed):
    http, tcp, probe = transports
    probe.return_value = observed
    ok, _ = agent._exec_command(command(), known={IP: {"type": "bitaxe", "mac": MAC}})
    assert ok is False
    probe.assert_called_once_with(IP)
    http.assert_not_called()
    tcp.assert_not_called()


def test_probe_failure_blocks_transport(transports):
    http, tcp, probe = transports
    probe.side_effect = TimeoutError("fixture probe timed out")
    ok, message = agent._exec_command(command(), known={})
    assert ok is False
    assert "identity" in message
    http.assert_not_called()
    tcp.assert_not_called()


def test_verified_axeos_dispatches_once_after_fresh_probe(transports):
    http, tcp, probe = transports
    ok, message = agent._exec_command(command(), known={IP: {"type": "cgminer"}})
    assert ok is True and message == "HTTP 200"
    probe.assert_called_once_with(IP)
    http.assert_called_once()
    tcp.assert_not_called()


def test_command_expiring_during_identity_probe_never_dispatches(
    transports, monkeypatch
):
    http, tcp, probe = transports
    now = time.time()
    clock = [now]
    monotonic = [10.0]
    monkeypatch.setattr(agent.time, "time", lambda: clock[0])
    monkeypatch.setattr(agent.time, "monotonic", lambda: monotonic[0])

    def delayed_identity(_target):
        # Even if the wall clock moves back, the original budget cannot grow.
        clock[0] -= 60
        monotonic[0] += 5
        return {"ip": IP, "mac": MAC, "type": "bitaxe"}

    probe.side_effect = delayed_identity
    ok, reason = agent._exec_command(command(expires_at=int(now) + 3))
    assert not ok and "expired" in reason
    http.assert_not_called()
    tcp.assert_not_called()


def test_batch_cannot_renew_expired_budget_after_wall_clock_rollback(
    transports, monkeypatch
):
    http, tcp, probe = transports
    now = time.time()
    clock, monotonic = [now], [10.0]
    monkeypatch.setattr(agent.time, "time", lambda: clock[0])
    monkeypatch.setattr(agent.time, "monotonic", lambda: monotonic[0])

    def delayed_identity(_target):
        clock[0] -= 60
        monotonic[0] += 5
        return {"ip": IP, "mac": MAC, "type": "bitaxe"}

    probe.side_effect = delayed_identity
    pull_started = (now, 10.0)
    first = agent._exec_command(
        command(expires_at=int(now) + 3), received_at=pull_started
    )
    second = agent._exec_command(
        command(expires_at=int(now) + 3), received_at=pull_started
    )
    assert not first[0] and not second[0]
    probe.assert_called_once()
    http.assert_not_called()
    tcp.assert_not_called()


@pytest.mark.parametrize(
    "kind,action", [("cgminer", "restart"), ("braiins", "identify")]
)
def test_known_tcp_protocol_requires_current_matching_identity(
    transports, kind, action
):
    http, tcp, probe = transports
    probe.return_value = {"ip": IP, "mac": MAC, "type": kind}
    ok, _ = agent._exec_command(command(expected_type=kind, command=action), known={})
    assert ok is True
    tcp.assert_called_once_with(IP, "led" if kind == "braiins" else "restart")
    http.assert_not_called()


def pull(client, token, registry, protocol=1):
    with patch("axe_fleet.routes._registry", registry):
        return client.post(
            "/api/agent/commands/pull",
            headers=_headers(token),
            json={} if protocol is None else {"command_protocol": protocol},
        )


def test_pull_negotiates_protocol_and_binds_canonical_identity(
    client, agent_token, registry, monkeypatch
):
    monkeypatch.setenv("ENABLE_PHYSICAL_COMMANDS", "true")
    device = _active_device(registry)
    queued = registry.enqueue_agent_command(device["id"], "restart", tenant_id="acme")
    assert (
        pull(client, agent_token, registry, protocol=None).get_json()["commands"] == []
    )
    assert _command_row(registry, queued["id"])["status"] == "pending"
    delivered = pull(client, agent_token, registry).get_json()["commands"]
    assert len(delivered) == 1
    assert delivered[0]["command_protocol"] == 1
    assert delivered[0]["expected_mac"] == MAC
    assert delivered[0]["expected_type"] == "bitaxe"
    assert int(time.time()) < delivered[0]["expires_at"] <= int(time.time()) + 300


@pytest.mark.parametrize("protocol", [True, "1", 0, 2])
def test_invalid_consumer_protocol_does_not_consume_command(
    client, agent_token, registry, monkeypatch, protocol
):
    monkeypatch.setenv("ENABLE_PHYSICAL_COMMANDS", "true")
    device = _active_device(registry)
    queued = registry.enqueue_agent_command(device["id"], "restart", tenant_id="acme")
    assert (
        pull(client, agent_token, registry, protocol=protocol).get_json()["commands"]
        == []
    )
    assert _command_row(registry, queued["id"])["status"] == "pending"


def test_lost_ack_cannot_redispatch_after_server_or_agent_restart(
    client, agent_token, registry, monkeypatch, transports
):
    monkeypatch.setenv("ENABLE_PHYSICAL_COMMANDS", "true")
    device = _active_device(registry)
    queued = registry.enqueue_agent_command(device["id"], "restart", tenant_id="acme")
    delivered = pull(client, agent_token, registry).get_json()["commands"][0]
    assert agent._exec_command(delivered, known={})[0] is True
    # Simulate lost ACK, then restart both processes. Only persisted SQLite
    # state is retained; neither in-memory map nor cooldown may save us.
    with registry._get_db() as conn:
        conn.execute(
            "UPDATE axe_agent_commands SET pulled_at=? WHERE id=?",
            (int(time.time()) - 61, queued["id"]),
        )
    restarted = DeviceRegistry(registry._get_db)
    restarted.ensure_tables()
    assert pull(client, agent_token, restarted).get_json()["commands"] == []
    assert not restarted.mark_command_pulled(queued["id"], tenant_id="acme")
    assert _command_row(restarted, queued["id"]) == {
        "status": "unknown",
        "result": "delivery_outcome_unknown",
    }
    transports[0].assert_called_once()
    # A late ACK is evidence of acknowledgement, not a second dispatch.
    assert restarted.ack_agent_command(queued["id"], "other", True) is False
    assert restarted.ack_agent_command(queued["id"], "acme", True) is True
    assert _command_row(restarted, queued["id"])["status"] == "done"


def test_legacy_caps_cannot_create_an_identity_envelope(
    client, agent_token, registry, monkeypatch
):
    monkeypatch.setenv("ENABLE_PHYSICAL_COMMANDS", "true")
    device = _active_device(registry)
    with registry._get_db() as conn:
        conn.execute(
            "UPDATE axe_devices SET capabilities=? WHERE id=?",
            ('{"restart":true}', device["id"]),
        )
    queued = registry.enqueue_agent_command(device["id"], "restart", tenant_id="acme")
    assert pull(client, agent_token, registry).get_json()["commands"] == []
    assert (
        _command_row(registry, queued["id"])["result"] == "command_identity_unavailable"
    )
