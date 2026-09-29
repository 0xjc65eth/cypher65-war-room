"""Issue #638: offline identity, CIDR expansion cap, interface CIDRs, heartbeat."""

import ipaddress
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import agent.agent as agent


def test_expand_cidr_does_not_materialize_slash8():
    consumed = {"n": 0}

    class BoomNet:
        num_addresses = 1 << 24

        def hosts(self):
            def gen():
                while True:
                    consumed["n"] += 1
                    if consumed["n"] > agent.MAX_HOSTS + 8:
                        raise AssertionError("expanded past MAX_HOSTS")
                    yield ipaddress.IPv4Address("10.0.0.1")

            return gen()

    with patch("ipaddress.ip_network", return_value=BoomNet()):
        hosts = agent._expand_cidr("10.0.0.0/8")
    assert len(hosts) == agent.MAX_HOSTS
    assert consumed["n"] == agent.MAX_HOSTS + 1  # loop checks i >= limit after yield


def test_cidr_truncated_uses_num_addresses_not_hosts():
    assert agent._cidr_truncated("192.168.1.0/24") is False
    assert agent._cidr_truncated("10.0.0.0/8") is True
    assert agent._cidr_truncated("192.168.1.7") is False


def test_default_subnets_prefers_interface_netmasks(monkeypatch):
    monkeypatch.setattr(agent, "_interface_cidrs", lambda: ["10.4.0.0/22"])
    assert agent._default_subnets() == ["10.4.0.0/22"]


def test_scan_report_has_no_device_ips():
    report = agent.scan_report(
        ["192.168.1.0/24"],
        ["192.168.1.%d" % i for i in range(1, 10)],
        [],
        truncated=False,
    )
    blob = str(report)
    assert "192.168.1." not in blob
    assert report["result"] == "no_devices"
    assert report["host_count"] == 9
    assert report["prefix_lens"] == [24]


def test_explicit_offline_stays_unknown_until_cgminer(monkeypatch):
    probes = [None, None, {"ip": "10.0.0.8", "type": "cgminer", "model": "S19"}]
    polls = []
    registrations = []
    sleeps = []

    class StopLoop(Exception):
        pass

    def post(path, payload, **kwargs):
        if path == "/api/agent/heartbeat":
            return 200, {"success": True}
        if path == "/api/agent/register":
            registrations.append(list(payload["devices"]))
            return 201, {"count": len(payload["devices"]), "blocked": []}
        if path == "/api/agent/telemetry":
            return 200, {}
        assert path == "/api/agent/commands/pull"
        return 200, {"commands": []}

    def probe(ip):
        return (
            probes.pop(0) if probes else {"ip": ip, "type": "cgminer", "model": "S19"}
        )

    def poll(device):
        polls.append(dict(device))
        return {"hashrate_hs": 1}

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise StopLoop

    monkeypatch.setattr(agent, "AGENT_TOKEN", "fixture-token")
    monkeypatch.setattr(agent, "EXPLICIT_DEVICES", ["10.0.0.8"])
    monkeypatch.setattr(agent, "RESCAN_EVERY", 1)
    monkeypatch.setattr(agent, "_probe_host", probe)
    monkeypatch.setattr(agent, "_poll_telemetry", poll)
    monkeypatch.setattr(agent, "_post", post)
    monkeypatch.setattr(agent, "_post_retry", post)
    monkeypatch.setattr(
        agent, "time", SimpleNamespace(time=agent.time.time, sleep=sleep)
    )
    with pytest.raises(StopLoop):
        agent.main()

    assert registrations == [[{"ip": "10.0.0.8", "type": "cgminer", "model": "S19"}]]
    assert polls and polls[0]["type"] == "cgminer"


def test_blocked_ips_are_not_reintroduced(monkeypatch):
    devices = [{"ip": "192.168.1.50", "type": "bitaxe"}]
    registrations = []
    sleeps = []

    class StopLoop(Exception):
        pass

    def post(path, payload, **kwargs):
        if path == "/api/agent/heartbeat":
            return 200, {"success": True}
        if path == "/api/agent/register":
            registrations.append(payload["devices"])
            return 200, {"count": 0, "blocked": [{"ip": "192.168.1.50"}]}
        if path == "/api/agent/telemetry":
            raise AssertionError("blocked device must not be polled")
        return 200, {"commands": []}

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise StopLoop

    monkeypatch.setattr(agent, "AGENT_TOKEN", "fixture-token")
    monkeypatch.setattr(agent, "EXPLICIT_DEVICES", [])
    monkeypatch.setattr(agent, "RESCAN_EVERY", 1)
    monkeypatch.setattr(agent, "scan_lan", lambda: devices)
    monkeypatch.setattr(agent, "_poll_telemetry", lambda d: {"hashrate_hs": 1})
    monkeypatch.setattr(agent, "_post", post)
    monkeypatch.setattr(agent, "_post_retry", post)
    monkeypatch.setattr(
        agent, "time", SimpleNamespace(time=agent.time.time, sleep=sleep)
    )
    with pytest.raises(StopLoop):
        agent.main()
    assert len(registrations) == 1
