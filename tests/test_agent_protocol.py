"""
CYPHER65 // AGENT PROTOCOL — cgminer firmware/stats + AxeOS discovery
=====================================================================
Unit tests against REAL mock servers (ephemeral ports) for the local agent
(agent/agent.py — the stdlib-only script users run on their LAN):

- _probe_host discovers a cgminer ASIC and extracts firmware/version from
  the `version` response (was hardcoded empty → Antminers showed no firmware)
- _poll_telemetry for cgminer now calls `stats` (temps/fans) and `pools`
  (URL/worker) — was summary-only → Antminers showed no temperature
- AxeOS HTTP discovery returns model/firmware/hostname/mac intact
"""
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import agent.agent as agent


# ── mock cgminer TCP server (realistic Antminer S19j Pro responses) ────────

def _cgminer_reply(cmd):
    if cmd == "version":
        return {
            "STATUS": [{"STATUS": "S", "Code": 22, "Msg": "CGMiner versions",
                        "Description": "cgminer 4.11.1"}],
            "VERSION": [{"CGMiner": "4.11.1", "API": "3.1", "Miner": "X19",
                         "Type": "Antminer S19j Pro"}],
        }
    if cmd == "summary":
        return {
            "STATUS": [{"STATUS": "S", "Code": 11, "Msg": "Summary"}],
            "SUMMARY": [{"GHS 5s": 91.2, "GHS av": 89.4, "Accepted": 1450,
                         "Rejected": 7, "Elapsed": 86500, "Best Share": "9.4T"}],
        }
    if cmd == "stats":
        return {
            "STATUS": [{"STATUS": "S", "Code": 71, "Msg": "Stats"}],
            "STATS": [
                {"STATS": 0, "ID": "POOL0"},
                {"STATS": 1, "ID": "BM1397_0", "temp2_0": 62.5, "temp2_1": 48.2,
                 "temp3_0": 61.0, "fan1": 4200, "fan2": 4100},
            ],
        }
    if cmd == "pools":
        return {
            "STATUS": [{"STATUS": "S", "Code": 54, "Msg": "Pools"}],
            "POOLS": [{"POOL": 0, "URL": "stratum+tcp://public-pool.io:21496",
                       "User": "bc1qtest.gamma01", "Status": "Alive",
                       "Accepted": 1450}],
        }
    if cmd == "restart":
        # cgminer-family restart is accepted then the device reboots.
        return {"STATUS": [{"STATUS": "S", "Code": 7, "Msg": "Restarting..."}]}
    return {"STATUS": [{"STATUS": "E", "Msg": f"unknown {cmd}"}]}


@pytest.fixture
def cgminer_mock():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    port = srv.getsockname()[1]
    stop = threading.Event()

    def _loop():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                conn.settimeout(2)
                data = conn.recv(4096)
                if data:
                    try:
                        cmd = json.loads(data.decode().strip()).get("command")
                    except (json.JSONDecodeError, ValueError):
                        cmd = None
                    conn.sendall(json.dumps(_cgminer_reply(cmd)).encode() + b"\x00")
            except Exception:
                pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    threading.Thread(target=_loop, daemon=True).start()
    yield port
    stop.set()
    try:
        srv.close()
    except OSError:
        pass


# ── mock AxeOS HTTP server (realistic Bitaxe Gamma /api/system/info) ───────

_AXEOS_INFO = {
    "board": "GAMMA", "model": "Gamma 900", "firmware": "AxeOS 2.13.0",
    "version": "2.13.0", "hostname": "bitaxe-gamma-01",
    "mac": "5C:86:4A:11:22:33", "hashrate": 912345678901,
    "hashRate1m": 900123456789, "hashRate10m": 895000000000,
    "hashRate1hr": 880000000000, "temp": 53.2, "temp2": 48.1, "vrTemp": 44.0,
    "power": 15.6, "coreVoltage": 1201, "frequency": 550,
    "fanspeed": 92, "fanSpeed": 92, "fanrpm": 4600, "fanRPM": 4600,
    "uptimeSeconds": 86500, "uptime": 86500, "bestDiff": "8.2T",
    "bestSessionDiff": "6.1T", "sharesAccepted": 1450, "sharesRejected": 7,
    "sharesStale": 1, "miningPaused": False, "stratumURL": "public-pool.io",
    "stratumPort": 21496, "stratumUser": "bc1qtest.gamma01", "wifiRSSI": -52,
}


class _AxeOSHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/api/system/info":
            body = json.dumps(_AXEOS_INFO).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def do_POST(self):
        # AxeOS restart/identify over HTTP :80.
        if self.path.rstrip("/").endswith("/api/system/restart") or \
                self.path.rstrip("/").endswith("/api/system/identify"):
            body = b'{"success": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture
def axeos_mock():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _AxeOSHandler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield port
    httpd.shutdown()


# ── discovery ─────────────────────────────────────────────────────────────

class TestDiscovery:
    def test_cgminer_host_extracts_firmware_and_version(self, monkeypatch, cgminer_mock):
        monkeypatch.setattr(agent, "CGMINER_PORT", cgminer_mock)
        found = agent._probe_host("127.0.0.1")
        assert found is not None
        assert found["type"] == "cgminer"
        assert found["model"] == "Antminer S19j Pro"
        assert found["firmware"] == "4.11.1"   # was "" before the fix
        assert found["version"] == "3.1"       # was "" before the fix

    def test_axeos_host_returns_full_identity(self, monkeypatch, axeos_mock):
        monkeypatch.setattr(agent, "AXEOS_PORT", axeos_mock)
        found = agent._probe_host("127.0.0.1")
        assert found["type"] == "bitaxe"
        assert found["model"] == "Gamma 900"
        assert found["firmware"] == "AxeOS 2.13.0"
        assert found["version"] == "2.13.0"
        assert found["hostname"] == "bitaxe-gamma-01"
        assert found["mac"] == "5C:86:4A:11:22:33"
        assert found["hashrate_hs"] == 912345678901


# ── telemetry ─────────────────────────────────────────────────────────────

class TestTelemetry:
    def test_cgminer_poll_includes_stats_temps_and_pools(self, monkeypatch, cgminer_mock):
        monkeypatch.setattr(agent, "CGMINER_PORT", cgminer_mock)
        tel = agent._poll_telemetry({"ip": "127.0.0.1", "type": "cgminer",
                                     "model": "Antminer S19j Pro"})
        assert tel["hashrate_hs"] == 91_200_000_000          # GHS 5s 91.2 × 1e9
        assert tel["temperature"] == 62.5                    # from stats temp2_0
        assert tel["fan_rpm"] == 4200                        # from stats fan1
        assert tel["pool_url"] == "stratum+tcp://public-pool.io:21496"
        assert tel["pool_user"] == "bc1qtest.gamma01"
        assert tel["best_diff"] == "9.4T"
        assert tel["shares_accepted"] == 1450
        assert tel["uptime_seconds"] == 86500

    def test_axeos_poll_is_full_telemetry(self, monkeypatch, axeos_mock):
        monkeypatch.setattr(agent, "AXEOS_PORT", axeos_mock)
        tel = agent._poll_telemetry({"ip": "127.0.0.1", "type": "bitaxe",
                                     "model": "Gamma 900"})
        assert tel["hashrate_hs"] == 912345678901
        assert tel["temperature"] == 53.2
        assert tel["fan_rpm"] == 4600
        assert tel["power_watts"] == 15.6
        assert tel["best_diff"] == "8.2T"
        assert tel["shares_accepted"] == 1450
        assert tel["model"] == "Gamma 900"

    def test_unreachable_cgminer_returns_empty_not_crash(self, monkeypatch):
        # No server on this port → poll must return {} (agent pushes {}).
        monkeypatch.setattr(agent, "CGMINER_PORT", 1)
        tel = agent._poll_telemetry({"ip": "127.0.0.1", "type": "cgminer"})
        assert tel == {}


# ── command execution (Fix 1: server sends ip_address, agent opens a REAL
#    socket on the LAN — AxeOS HTTP :80 vs cgminer JSON-over-TCP :4028) ────

class TestExecCommand:
    def test_axeos_restart_http(self, monkeypatch, axeos_mock):
        monkeypatch.setattr(agent, "AXEOS_PORT", axeos_mock)
        ok, result = agent._exec_command(
            {"ip_address": "127.0.0.1", "command": "restart"},
            known={"127.0.0.1": {"type": "bitaxe"}})
        assert ok is True
        assert "HTTP 200" in result

    def test_axeos_identify_http(self, monkeypatch, axeos_mock):
        monkeypatch.setattr(agent, "AXEOS_PORT", axeos_mock)
        ok, _ = agent._exec_command(
            {"ip_address": "127.0.0.1", "command": "identify"},
            known={"127.0.0.1": {"type": "bitaxe"}})
        assert ok is True

    def test_cgminer_restart_via_tcp_api(self, monkeypatch, cgminer_mock):
        monkeypatch.setattr(agent, "CGMINER_PORT", cgminer_mock)
        ok, result = agent._exec_command(
            {"ip_address": "127.0.0.1", "command": "restart"},
            known={"127.0.0.1": {"type": "cgminer"}})
        assert ok is True
        assert "accepted" in result

    def test_cgminer_identify_rejected(self, monkeypatch, cgminer_mock):
        """cgminer has NO identify command — honest failure, not a phantom
        success (the server no longer advertises the capability either)."""
        monkeypatch.setattr(agent, "CGMINER_PORT", cgminer_mock)
        ok, result = agent._exec_command(
            {"ip_address": "127.0.0.1", "command": "identify"},
            known={"127.0.0.1": {"type": "cgminer"}})
        assert ok is False
        assert "not supported" in result

    def test_unreachable_device_fails_honestly(self, monkeypatch):
        """No server → restart fails with a result string, never a crash."""
        monkeypatch.setattr(agent, "AXEOS_PORT", 1)
        ok, result = agent._exec_command(
            {"ip_address": "127.0.0.1", "command": "restart"},
            known={"127.0.0.1": {"type": "bitaxe"}})
        assert ok is False
        assert isinstance(result, str)

    def test_unknown_command(self):
        ok, result = agent._exec_command({"command": "frobnicate"}, known={})
        assert ok is False
        assert "unknown command" in result
