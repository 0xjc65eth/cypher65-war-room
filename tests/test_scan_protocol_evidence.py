"""
CYPHER65 // Protocol evidence instead of port guessing (Issue #569)
===================================================================
An open TCP port is NOT a firmware. A router, NAS panel, printer or TV
answering on :80 used to be labelled ``braiins_rest`` by the legacy LAN
scanner, which is how a fleet fills up with phantom miners that then push
empty telemetry forever.

These tests pin the fail-closed rules added in #569:

- ``core/registry/detector``: a JSON 200 on ``/api/system/info`` or
  ``/api/v1/miner/stats`` WITHOUT that firmware's identity block is not a
  miner — and a real one is still detected (regression guard).
- ``services/lan_scanner``: ``firmware_hint`` comes only from a validated
  miner protocol; a host with :80 open that answers nothing keeps
  ``firmware_hint: None``, and mDNS candidates are no longer hardcoded as
  ``braiins``.
- ``agent/agent.py``: the LAN agent only announces a validated miner, and
  discovers Braiins OS+ REST-only hardware (previously invisible) with full
  telemetry.
- ``app``: ``/api/network/scan`` refuses to sweep a datacenter subnet on a
  cloud deploy (same guard ``/api/axe-fleet/scan`` already had).
"""

import pytest
import requests

import app as _app_module

app = _app_module.app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class _Resp:
    """Minimal requests.Response stand-in."""

    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _no_sockets(monkeypatch, module):
    """Make every TCP socket construction fail (hermetic: no real I/O).

    The cgminer probe in detector/agent creates a raw socket; without this a
    test would try to reach 10.0.0.x on the real network.
    """

    def _refuse(*_a, **_kw):
        raise OSError("network disabled in tests")

    monkeypatch.setattr(module.socket, "socket", _refuse)


# ══════════════════════════════════════════════════════════════════════════
#  core/registry/detector.py — identity blocks are required
# ══════════════════════════════════════════════════════════════════════════


class TestDetectorProtocolEvidence:
    def test_generic_json_200_is_not_axeos(self, monkeypatch):
        """A router's JSON catch-all on /api/system/info must not be a Bitaxe."""
        from core.registry import detector

        monkeypatch.setattr(
            detector.requests,
            "get",
            lambda url, timeout: _Resp({"status": "ok", "device": "router"}),
        )
        _no_sockets(monkeypatch, detector)

        result = detector.detect_firmware("10.0.0.9")

        assert result["reachable"] is False
        assert result["adapter_type"] == "unknown"
        assert result["firmware"] == "unknown"

    def test_axeos_with_markers_is_still_detected(self, monkeypatch):
        """Regression: the stricter check must not reject real AxeOS."""
        from core.registry import detector

        monkeypatch.setattr(
            detector.requests,
            "get",
            lambda url, timeout: _Resp(
                {"version": "2.13.0", "model": "Gamma 900", "hashrate": 912345678901}
            ),
        )
        _no_sockets(monkeypatch, detector)

        result = detector.detect_firmware("10.0.0.9")

        assert result["adapter_type"] == "bitaxe"
        assert result["firmware"] == "axeos"
        assert result["reachable"] is True

    def test_braiins_200_without_miner_stats_is_not_braiins(self, monkeypatch):
        """A JSON endpoint on the Braiins path is not a Braiins miner."""
        from core.registry import detector

        def fake_get(url, timeout):
            if "/api/system/info" in url:
                raise requests.ConnectionError("not axeos")
            return _Resp({"pools": [], "note": "some other service"})

        monkeypatch.setattr(detector.requests, "get", fake_get)
        _no_sockets(monkeypatch, detector)

        result = detector.detect_firmware("10.0.0.9")

        assert result["reachable"] is False
        assert result["adapter_type"] == "unknown"

    def test_braiins_with_miner_stats_is_still_detected(self, monkeypatch):
        """Regression: the stricter check must not reject real Braiins OS+."""
        from core.registry import detector

        def fake_get(url, timeout):
            if "/api/system/info" in url:
                raise requests.ConnectionError("not axeos")
            return _Resp(
                {
                    "miner_stats": {
                        "hashrate_ghps": "100",
                        "version": "braiins-os_2024-10",
                        "model": "Antminer S19 Pro",
                    }
                }
            )

        monkeypatch.setattr(detector.requests, "get", fake_get)
        _no_sockets(monkeypatch, detector)

        result = detector.detect_firmware("10.0.0.9")

        assert result["adapter_type"] == "braiins"
        assert result["reachable"] is True
        assert result["model"] == "Antminer S19 Pro"

    def test_timeout_is_forwarded_to_every_probe(self, monkeypatch):
        """The LAN scanner passes a short timeout so a /24 full of web servers
        cannot stall the identification phase behind 3s probes."""
        from core.registry import detector

        seen = []

        def fake_get(url, timeout):
            seen.append(timeout)
            raise requests.ConnectionError("nothing here")

        monkeypatch.setattr(detector.requests, "get", fake_get)
        _no_sockets(monkeypatch, detector)

        detector.detect_firmware("10.0.0.9", timeout=0.5)

        assert seen and all(t == 0.5 for t in seen)


# ══════════════════════════════════════════════════════════════════════════
#  services/lan_scanner.py — hints come from evidence, never from a port
# ══════════════════════════════════════════════════════════════════════════


def _hermetic_scanner(monkeypatch, ls, ips, open_port_for, identify):
    """Wire scan_network to fake hosts/probes with no real network I/O."""
    monkeypatch.setattr(ls, "_arp_table_ips", lambda: list(ips))
    monkeypatch.setattr(ls, "_local_subnet_ips", lambda: [])
    monkeypatch.setattr(
        ls,
        "_probe_port",
        lambda ip, port: bool(open_port_for(ip, port)),
    )
    monkeypatch.setattr(ls, "_identify_miner", identify)

    def _no_dns_sd(*_a, **_kw):
        raise FileNotFoundError("dns-sd not available")

    monkeypatch.setattr(ls.subprocess, "check_output", _no_dns_sd)


class TestLanScannerProtocolEvidence:
    def test_host_with_only_port_80_open_is_not_a_miner(self, monkeypatch):
        """This is the reported bug: a neighbour on :80 showed up as braiins."""
        import services.lan_scanner as ls

        _hermetic_scanner(
            monkeypatch,
            ls,
            ips=["192.168.1.10"],
            open_port_for=lambda ip, port: port == 80,
            identify=lambda ip: None,
        )

        out = ls.scan_network()

        # Reported as a candidate host, NOT as a miner.
        assert out["found"] == 0
        assert out["devices"] == []
        assert out["alive"] == 1
        assert out["alive_ips"] == ["192.168.1.10"]
        dev = out["candidates"][0]
        assert dev["open_ports"] == [80]
        assert dev["firmware_hint"] is None
        assert dev["miner_protocol"] is None

    def test_bitaxe_on_port_80_is_labelled_bitaxe(self, monkeypatch):
        """AxeOS/ESP-Miner answers :80. The legacy scanner called :80
        'braiins_rest' and :8080 'bitaxe' — a real Bitaxe was mislabelled."""
        import services.lan_scanner as ls

        _hermetic_scanner(
            monkeypatch,
            ls,
            ips=["192.168.1.20"],
            open_port_for=lambda ip, port: port == 80,
            identify=lambda ip: "bitaxe",
        )

        out = ls.scan_network()
        assert out["found"] == 1
        assert out["alive"] == 0
        dev = out["devices"][0]

        assert dev["miner_protocol"] == "bitaxe"
        assert dev["firmware_hint"] == "bitaxe"

    def test_braiins_and_cgminer_hints_come_from_the_protocol(self, monkeypatch):
        import services.lan_scanner as ls

        _hermetic_scanner(
            monkeypatch,
            ls,
            ips=["192.168.1.30", "192.168.1.31"],
            open_port_for=lambda ip, port: port == 4028,
            identify=lambda ip: "braiins" if ip.endswith(".30") else "cgminer",
        )

        by_ip = {d["ip"]: d for d in ls.scan_network()["devices"]}

        assert by_ip["192.168.1.30"]["firmware_hint"] == "braiins"
        assert by_ip["192.168.1.31"]["firmware_hint"] == "cgminer"

    def test_unrecognized_adapter_is_never_a_hint(self, monkeypatch):
        """detect_firmware can return adapter types we do not support."""
        import services.lan_scanner as ls

        _hermetic_scanner(
            monkeypatch,
            ls,
            ips=["192.168.1.40"],
            open_port_for=lambda ip, port: port == 80,
            identify=lambda ip: None,
        )
        # Sanity: the mapping only carries canonical adapter types.
        assert set(ls._FIRMWARE_HINTS) == {"bitaxe", "braiins", "cgminer"}

    def test_mdns_candidate_is_not_hardcoded_as_braiins(self, monkeypatch):
        """mDNS discovery used to stamp firmware_hint='braiins' unconditionally."""
        import services.lan_scanner as ls

        # One candidate that answers nothing, so the mDNS phase is reached
        # (the scanner returns early when the candidate list itself is empty).
        monkeypatch.setattr(ls, "_arp_table_ips", lambda: ["192.168.1.99"])
        monkeypatch.setattr(ls, "_local_subnet_ips", lambda: [])
        monkeypatch.setattr(ls, "_probe_port", lambda ip, port: False)
        monkeypatch.setattr(ls, "_identify_miner", lambda ip: None)

        browse = "12:00:00.100  Add  4  local.  _http._tcp.  bitaxe-gamma-01\n"
        resolve = (
            "12:00:00.200  Add  4  local.  _http._tcp.  bitaxe-gamma-01  192.168.1.55\n"
        )

        def fake_check_output(cmd, **_kw):
            return resolve if "-q" in cmd else browse

        monkeypatch.setattr(ls.subprocess, "check_output", fake_check_output)

        out = ls.scan_network()

        assert out["found"] == 0
        dev = out["candidates"][0]
        assert dev["ip"] == "192.168.1.55"
        assert dev["hostname"] == "bitaxe-gamma-01"
        assert dev["discovered_via"] == "mdns"
        assert dev["firmware_hint"] is None
        assert dev["miner_protocol"] is None

    def test_mdns_miner_is_validated_and_kept(self, monkeypatch):
        """A real miner found only via mDNS still reaches `devices`."""
        import services.lan_scanner as ls

        monkeypatch.setattr(ls, "_arp_table_ips", lambda: ["192.168.1.99"])
        monkeypatch.setattr(ls, "_local_subnet_ips", lambda: [])
        monkeypatch.setattr(ls, "_probe_port", lambda ip, port: False)
        monkeypatch.setattr(ls, "_identify_miner", lambda ip: "braiins")

        browse = "12:00:00.100  Add  4  local.  _http._tcp.  bosminer-01\n"
        resolve = (
            "12:00:00.200  Add  4  local.  _http._tcp.  bosminer-01  192.168.1.56\n"
        )

        def fake_check_output(cmd, **_kw):
            return resolve if "-q" in cmd else browse

        monkeypatch.setattr(ls.subprocess, "check_output", fake_check_output)

        out = ls.scan_network()

        assert out["found"] == 1
        assert out["devices"][0]["ip"] == "192.168.1.56"
        assert out["devices"][0]["firmware_hint"] == "braiins"

    def test_identify_miner_maps_only_supported_adapters(self, monkeypatch):
        import services.lan_scanner as ls
        from core.registry import detector

        monkeypatch.setattr(
            detector,
            "detect_firmware",
            lambda ip, timeout=None: {"reachable": True, "adapter_type": "bitaxe"},
        )
        assert ls._identify_miner("10.0.0.1") == "bitaxe"

        monkeypatch.setattr(
            detector,
            "detect_firmware",
            lambda ip, timeout=None: {"reachable": True, "adapter_type": "wat"},
        )
        assert ls._identify_miner("10.0.0.1") is None

    def test_identify_miner_swallows_probe_failures(self, monkeypatch):
        import services.lan_scanner as ls
        from core.registry import detector

        def _boom(ip, timeout=None):
            raise RuntimeError("probe exploded")

        monkeypatch.setattr(detector, "detect_firmware", _boom)
        assert ls._identify_miner("10.0.0.1") is None


# ══════════════════════════════════════════════════════════════════════════
#  app.py — /api/network/scan must respect the cloud topology guard
# ══════════════════════════════════════════════════════════════════════════


class TestNetworkScanCloudGuard:
    def test_cloud_deploy_refuses_lan_scan(self, monkeypatch, client):
        monkeypatch.setenv("RENDER", "true")

        resp = client.post("/api/network/scan")

        assert resp.status_code == 400
        body = resp.get_json()
        assert body["success"] is False
        assert body["is_cloud"] is True
        assert "AGENTE LOCAL" in body["message"]

    def test_self_host_still_scans(self, monkeypatch, client):
        """Regression: a self-hosted deploy keeps the endpoint working."""
        import services.lan_scanner as ls

        monkeypatch.delenv("RENDER", raising=False)
        monkeypatch.delenv("CLOUD_MODE", raising=False)
        monkeypatch.setattr(
            ls,
            "scan_network",
            lambda: {"scanned": 1, "found": 0, "duration_ms": 1, "devices": []},
        )

        resp = client.post("/api/network/scan")

        assert resp.status_code == 200
        assert resp.get_json()["success"] is True


# ══════════════════════════════════════════════════════════════════════════
#  agent/agent.py — validate before announcing, and see Braiins REST
# ══════════════════════════════════════════════════════════════════════════

_BRAIINS_REST = {
    "miner_stats": {
        "hashrate_ghps": "110000",  # GH/s → 110 TH/s
        "board_temp_avg": 62.0,
        "chip_temp_avg": 71.5,
        "accepted_shares": 1450,
        "rejected_shares": 7,
        "stale_shares": 1,
        "uptime_s": 86500,
        "best_share": "9.4T",
        "version": "braiins-os_2024-10",
        "model": "Antminer S19 Pro",
    },
    "pool_stats": {
        "url": "stratum+tcp://public-pool.io:21496",
        "user": "bc1qtest",
        "accepted": 1450,
        "rejected": 7,
    },
    "power_stats": {"power_avg": 3200.0},
}


class TestAgentProtocolEvidence:
    def test_agent_rejects_generic_json_as_axeos(self, monkeypatch):
        import agent.agent as agent

        monkeypatch.setattr(
            agent, "_get_json", lambda url, **kw: {"status": "ok", "device": "router"}
        )
        assert agent._probe_axeos("10.0.0.5") is None

    def test_agent_accepts_axeos_with_markers(self, monkeypatch):
        import agent.agent as agent

        monkeypatch.setattr(
            agent, "_get_json", lambda url, **kw: {"hashrate": 1, "version": "2.13.0"}
        )
        assert agent._probe_axeos("10.0.0.5") is not None

    def test_agent_braiins_requires_miner_stats(self, monkeypatch):
        import agent.agent as agent

        tried = []

        def fake_get_json(url, **kw):
            tried.append(url)
            return {"pools": [], "note": "not a miner"}

        monkeypatch.setattr(agent, "_get_json", fake_get_json)

        assert agent._probe_braiins_rest("10.0.0.5") is None
        # Both the standard REST port and the alternate were tried.
        assert len(tried) == 2
        assert any(":80/" in u for u in tried)
        assert any(f":{agent.BRAIINS_REST_PORT}/" in u for u in tried)

    def test_agent_probe_host_returns_none_for_a_non_miner(self, monkeypatch):
        import agent.agent as agent

        monkeypatch.setattr(agent, "_probe_axeos", lambda ip: None)
        monkeypatch.setattr(agent, "_probe_braiins_rest", lambda ip: None)
        monkeypatch.setattr(agent, "_probe_cgminer", lambda ip: None)

        assert agent._probe_host("10.0.0.5") is None

    def test_agent_discovers_braiins_rest_only_device(self, monkeypatch):
        """REST-only Braiins OS+ (no :4028) used to be invisible to the agent."""
        import agent.agent as agent

        monkeypatch.setattr(agent, "_probe_axeos", lambda ip: None)
        monkeypatch.setattr(agent, "_probe_braiins_rest", lambda ip: _BRAIINS_REST)
        monkeypatch.setattr(agent, "_probe_cgminer", lambda ip: None)

        dev = agent._probe_host("10.0.0.5")

        assert dev["type"] == "braiins"
        assert dev["hashrate_hs"] == int(110000 * 1e9)
        assert dev["model"] == "Antminer S19 Pro"
        assert dev["firmware"] == "Braiins OS+"
        assert dev["version"] == "braiins-os_2024-10"
        assert dev["pool_url"] == "stratum+tcp://public-pool.io:21496"
        assert dev["pool_user"] == "bc1qtest"

    def test_agent_braiins_telemetry_is_complete(self, monkeypatch):
        import agent.agent as agent

        monkeypatch.setattr(agent, "_probe_braiins_rest", lambda ip: _BRAIINS_REST)

        tel = agent._braiins_rest_telemetry("10.0.0.5")

        assert tel["hashrate_hs"] == int(110000 * 1e9)
        assert tel["temperature"] == 62.0
        assert tel["temp_asic"] == 71.5
        assert tel["power_watts"] == 3200.0
        assert tel["shares_accepted"] == 1450
        assert tel["shares_rejected"] == 7
        assert tel["shares_stale"] == 1
        assert tel["uptime_seconds"] == 86500
        assert tel["best_diff"] == "9.4T"
        assert tel["pool_url"] == "stratum+tcp://public-pool.io:21496"
        assert tel["pool_user"] == "bc1qtest"
        # 3200 W at 110 TH/s → 29.09 J/TH
        assert tel["efficiency_jth"] == 29.09

    def test_agent_braiins_telemetry_empty_when_rest_is_silent(self, monkeypatch):
        """{} means 'try cgminer', never 'the miner is dead'."""
        import agent.agent as agent

        monkeypatch.setattr(agent, "_probe_braiins_rest", lambda ip: None)
        assert agent._braiins_rest_telemetry("10.0.0.5") == {}

    def test_agent_braiins_commands_use_the_cgminer_api(self, monkeypatch):
        import agent.agent as agent

        sent = []
        monkeypatch.setattr(
            agent,
            "_cgminer_cmd",
            lambda ip, cmd: sent.append(cmd) or {"STATUS": [{"STATUS": "S"}]},
        )
        known = {"10.0.0.5": {"type": "braiins"}}

        ok, _ = agent._exec_command(
            {"ip_address": "10.0.0.5", "command": "restart"}, known
        )
        assert ok is True

        ok, _ = agent._exec_command(
            {"ip_address": "10.0.0.5", "command": "identify"}, known
        )
        assert ok is True

        assert sent == ["restart", "led"]

    def test_agent_braiins_pause_is_rejected_not_faked(self, monkeypatch):
        import agent.agent as agent

        monkeypatch.setattr(agent, "_cgminer_cmd", lambda ip, cmd: {"STATUS": [{}]})
        known = {"10.0.0.5": {"type": "braiins"}}

        ok, message = agent._exec_command(
            {"ip_address": "10.0.0.5", "command": "pause"}, known
        )

        assert ok is False
        assert "not supported" in message
