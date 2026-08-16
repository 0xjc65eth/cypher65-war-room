"""Tests for core/adapters/braiins_adapter.py."""
from unittest.mock import Mock, patch

import pytest
import requests

from core.adapters.braiins_adapter import BraiinsAdapter
from core.models.device import Device, DeviceStatus


# ── Helpers ────────────────────────────────────────────────────────────

def _braiins_device(ip="10.0.0.1", firmware="Braiins OS+"):
    return Device(name="braiins-s19", model="Antminer S19 Pro",
                  firmware=firmware, ip=ip)


def _mock_socket_response(adapter, command_to_response: dict):
    """Patch _send_command to return canned responses per command."""
    def fake_send(cmd, port=None):
        return command_to_response.get(cmd)
    return patch.object(adapter, "_send_command", side_effect=fake_send)


# ═══════════════════════════════════════════════════════════════════════════
#  BraiinsAdapter — unit tests
# ═══════════════════════════════════════════════════════════════════════════

class TestBraiinsAdapter:
    """Basic adapter creation, capabilities, health check."""

    def test_get_capabilities(self):
        dev = _braiins_device()
        adapter = BraiinsAdapter(dev)
        caps = adapter.get_capabilities()
        names = {c.name for c in caps}
        assert len(caps) == 5
        assert "telemetry" in names
        assert "restart" in names
        assert "identify" in names
        assert "tuner_control" in names
        assert "set_frequency" in names

    def test_telemetry_capability_supported(self):
        dev = _braiins_device()
        adapter = BraiinsAdapter(dev)
        caps = adapter.get_capabilities()
        tele = next(c for c in caps if c.name == "telemetry")
        assert tele.supported is True

    def test_tuner_control_not_supported(self):
        dev = _braiins_device()
        adapter = BraiinsAdapter(dev)
        caps = adapter.get_capabilities()
        tuner = next(c for c in caps if c.name == "tuner_control")
        assert tuner.supported is False
        assert tuner.risk_level.value == "high"

    def test_restart_requires_confirmation(self):
        dev = _braiins_device()
        adapter = BraiinsAdapter(dev)
        caps = adapter.get_capabilities()
        restart = next(c for c in caps if c.name == "restart")
        assert restart.requires_confirmation is True

    def test_health_check_unreachable_no_host(self):
        dev = Device(name="no-ip", model="S19", firmware="Braiins OS+", ip="")
        adapter = BraiinsAdapter(dev)

        result = adapter.health_check()
        assert result["reachable"] is False

    def test_health_check_via_rest(self):
        dev = _braiins_device()
        adapter = BraiinsAdapter(dev)

        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"miner_stats": {"hashrate_ghps": 100}}

        with patch("core.adapters.braiins_adapter.requests.get",
                   return_value=mock_resp):
            result = adapter.health_check()
        assert result["reachable"] is True
        assert result["api"] == "rest"

    def test_health_check_via_cgminer_fallback(self):
        dev = _braiins_device()
        adapter = BraiinsAdapter(dev)

        # REST fails, socket succeeds
        with patch.object(adapter, "_rest_get", return_value=None), \
             patch.object(adapter, "_send_command",
                          return_value={"STATUS": [{"STATUS":"S"}],
                                        "VERSION": [{"Version":"BOSminer 22.0",
                                                     "Type":"Antminer S19 Pro"}]}):
            result = adapter.health_check()
        assert result["reachable"] is True
        assert result["api"] == "cgminer_socket"
        assert "BOSminer" in result["version"]


# ═══════════════════════════════════════════════════════════════════════════
#  Telemetry — cgminer socket path (primary fallback)
# ═══════════════════════════════════════════════════════════════════════════

class TestBraiinsTelemetryCgminer:
    """Telemetry via the cgminer socket with Braiins extensions."""

    @staticmethod
    def _telemetry(summary=None, temps=None, fans=None, tuner=None,
                   stats=None, pools=None, rest=None):
        dev = _braiins_device()
        adapter = BraiinsAdapter(dev)

        send_map = {}
        if summary is not None:
            send_map["summary"] = summary
        if temps is not None:
            send_map["temps"] = temps
        if fans is not None:
            send_map["fans"] = fans
        if tuner is not None:
            send_map["tunerstatus"] = tuner
        if stats is not None:
            send_map["stats"] = stats
        if pools is not None:
            send_map["pools"] = pools

        with patch.object(adapter, "_rest_get", return_value=rest), \
             patch.object(adapter, "_send_command",
                          side_effect=lambda cmd, port=None: send_map.get(cmd)):
            return adapter.get_telemetry()

    # ── Summary only (minimal) ──────────────────────────────────────

    def test_summary_only_minimal(self):
        t = self._telemetry(
            summary={
                "STATUS": [{"STATUS": "S"}],
                "SUMMARY": [{"GHS 5s": "110.0", "Elapsed": 86400,
                             "Accepted": 5000, "Rejected": 3, "Stale": 1,
                             "Best Share": "25.7T"}],
            },
        )
        assert t is not None
        assert t["hashrate"] == 110e9
        assert t["uptime"] == 86400
        # No temps/fans/stats → thermal/cooling all None
        assert t["chip_temp"] is None
        assert t["vr_temp"] is None
        assert t["fan_rpm"] is None
        assert t["voltage"] is None
        assert t["power"] is None
        assert t["pool_status"] is None

    # ── Braiins 'temps' command ─────────────────────────────────────

    def test_temps_command_max_chip_temp(self):
        t = self._telemetry(
            summary={
                "STATUS": [{"STATUS": "S"}],
                "SUMMARY": [{"GHS 5s": "100"}],
            },
            temps={
                "STATUS": [{"STATUS": "S"}],
                "TEMPS": [
                    {"Board": 0, "Chip": 0, "ID": 0, "temp": "68.5",
                     "temp_pcb": "55.0"},
                    {"Board": 0, "Chip": 1, "ID": 1, "temp": "72.0",
                     "temp_pcb": "56.5"},
                    {"Board": 1, "Chip": 0, "ID": 2, "temp": "70.0",
                     "temp_pcb": "54.0"},
                ],
            },
        )
        # chip_temp = max(temp) across all chips
        assert t["chip_temp"] == 72.0
        # temperature = max(temp_pcb) across all boards
        assert t["temperature"] == 56.5

    def test_temps_single_board(self):
        t = self._telemetry(
            summary={
                "STATUS": [{"STATUS": "S"}],
                "SUMMARY": [{"GHS 5s": "100"}],
            },
            temps={
                "STATUS": [{"STATUS": "S"}],
                "TEMPS": [
                    {"Board": 0, "Chip": 0, "ID": 0, "temp": "65.0",
                     "temp_pcb": "50.0"},
                ],
            },
        )
        assert t["chip_temp"] == 65.0
        assert t["temperature"] == 50.0

    # ── Braiins 'fans' command ──────────────────────────────────────

    def test_fans_command_average_rpm(self):
        t = self._telemetry(
            summary={
                "STATUS": [{"STATUS": "S"}],
                "SUMMARY": [{"GHS 5s": "100"}],
            },
            fans={
                "STATUS": [{"STATUS": "S"}],
                "FANS": [
                    {"FAN": 0, "ID": 0, "RPM": 4800, "Speed": 80},
                    {"FAN": 1, "ID": 1, "RPM": 4600, "Speed": 78},
                ],
            },
        )
        # fan_rpm = average across all fans
        assert t["fan_rpm"] == (4800 + 4600) / 2

    def test_fans_single_fan(self):
        t = self._telemetry(
            summary={
                "STATUS": [{"STATUS": "S"}],
                "SUMMARY": [{"GHS 5s": "100"}],
            },
            fans={
                "STATUS": [{"STATUS": "S"}],
                "FANS": [
                    {"FAN": 0, "ID": 0, "RPM": 5000, "Speed": 85},
                ],
            },
        )
        assert t["fan_rpm"] == 5000

    # ── Braiins 'tunerstatus' command ───────────────────────────────

    def test_tunerstatus_power(self):
        t = self._telemetry(
            summary={
                "STATUS": [{"STATUS": "S"}],
                "SUMMARY": [{"GHS 5s": "100"}],
            },
            tuner={
                "STATUS": [{"STATUS": "S"}],
                "TUNERSTATUS": [
                    {"power": "3100", "tuner_state": "TUNED",
                     "power_limit": "3500"},
                ],
            },
        )
        assert t["power"] == 3100

    def test_tunerstatus_power_fallback_to_power_w(self):
        t = self._telemetry(
            summary={
                "STATUS": [{"STATUS": "S"}],
                "SUMMARY": [{"GHS 5s": "100"}],
            },
            tuner={
                "STATUS": [{"STATUS": "S"}],
                "TUNERSTATUS": [
                    {"power_w": "3200", "tuner_state": "TUNING"},
                ],
            },
        )
        assert t["power"] == 3200

    # ── Stats fallback (when temps/fans/tuner unavailable) ──────────

    def test_stats_fallback_temps_fan_power(self):
        t = self._telemetry(
            summary={
                "STATUS": [{"STATUS": "S"}],
                "SUMMARY": [{"GHS 5s": "95"}],
            },
            stats={
                "STATUS": [{"STATUS": "S"}],
                "STATS": [
                    {"STATS": 0},
                    {"temp2_0": "65.0", "temp2_1": "60.0",
                     "fan_num": "2", "fan1": "4200",
                     "voltage": "11.8", "power": "2800"},
                ],
            },
        )
        assert t["chip_temp"] == 65.0
        assert t["vr_temp"] == 60.0
        assert t["fan_rpm"] == 4200
        assert t["voltage"] == 11.8
        assert t["power"] == 2800

    # ── Pool status ─────────────────────────────────────────────────

    def test_pool_connected_alive(self):
        t = self._telemetry(
            summary={
                "STATUS": [{"STATUS": "S"}],
                "SUMMARY": [{"GHS 5s": "100"}],
            },
            pools={
                "STATUS": [{"STATUS": "S"}],
                "POOLS": [
                    {"POOL": 0, "URL": "stratum+tcp://pool.btc.com:3333",
                     "User": "user.worker", "Status": "Alive"},
                ],
            },
        )
        assert t["pool_status"] == "CONNECTED"
        assert t["pool"]["url"] == "stratum+tcp://pool.btc.com:3333"

    def test_pool_disconnected(self):
        t = self._telemetry(
            summary={
                "STATUS": [{"STATUS": "S"}],
                "SUMMARY": [{"GHS 5s": "0"}],
            },
            pools={
                "STATUS": [{"STATUS": "S"}],
                "POOLS": [
                    {"POOL": 0, "URL": "stratum+tcp://dead.pool:3333",
                     "User": "user.worker", "Status": "Dead"},
                ],
            },
        )
        assert t["pool_status"] == "DISCONNECTED"

    def test_pool_not_configured_empty(self):
        t = self._telemetry(
            summary={
                "STATUS": [{"STATUS": "S"}],
                "SUMMARY": [{"GHS 5s": "0"}],
            },
            pools={
                "STATUS": [{"STATUS": "S"}],
                "POOLS": [],
            },
        )
        assert t["pool_status"] == "NOT CONFIGURED"

    # ── Full telemetry (all commands) ───────────────────────────────

    def test_full_telemetry_all_fields(self):
        t = self._telemetry(
            summary={
                "STATUS": [{"STATUS": "S"}],
                "SUMMARY": [{"GHS 5s": "120.0", "Elapsed": 604800,
                             "Accepted": 10000, "Rejected": 5, "Stale": 2,
                             "Best Share": "50T"}],
            },
            temps={
                "STATUS": [{"STATUS": "S"}],
                "TEMPS": [
                    {"Board": 0, "Chip": 0, "ID": 0, "temp": "70.0",
                     "temp_pcb": "55.0"},
                    {"Board": 0, "Chip": 1, "ID": 1, "temp": "74.5",
                     "temp_pcb": "56.0"},
                ],
            },
            fans={
                "STATUS": [{"STATUS": "S"}],
                "FANS": [
                    {"FAN": 0, "ID": 0, "RPM": 4800, "Speed": 80},
                    {"FAN": 1, "ID": 1, "RPM": 4600, "Speed": 78},
                ],
            },
            tuner={
                "STATUS": [{"STATUS": "S"}],
                "TUNERSTATUS": [
                    {"power": "3100", "tuner_state": "TUNED",
                     "power_limit": "3500"},
                ],
            },
            stats={
                "STATUS": [{"STATUS": "S"}],
                "STATS": [
                    {"STATS": 0},
                    {"voltage": "12.4", "fan_num": "2", "fan1": "4800"},
                ],
            },
            pools={
                "STATUS": [{"STATUS": "S"}],
                "POOLS": [
                    {"POOL": 0, "URL": "stratum+tcp://braiins.pool:3333",
                     "User": "braiins.worker", "Status": "Alive"},
                ],
            },
        )
        assert t["hashrate"] == 120e9
        # Temps from Braiins 'temps' command
        assert t["chip_temp"] == 74.5
        assert t["temperature"] == 56.0
        # Fans from Braiins 'fans' command
        assert t["fan_rpm"] == (4800 + 4600) / 2
        # Power from tunerstatus
        assert t["power"] == 3100
        # Voltage from stats fallback
        assert t["voltage"] == 12.4
        # Pool
        assert t["pool_status"] == "CONNECTED"
        assert t["pool"]["url"] == "stratum+tcp://braiins.pool:3333"
        # Shares
        assert t["accepted_shares"] == 10000
        assert t["rejected_shares"] == 5
        assert t["stale_shares"] == 2
        assert t["best_difficulty"] == "50T"
        assert t["uptime"] == 604800
        # Hashrate windows are always None (cgminer limitation)
        assert t["hashrate_1m"] is None
        assert t["hashrate_10m"] is None
        assert t["hashrate_1h"] is None
        # Source marker
        assert t["source"] == "braiins_adapter"
        assert t["stub"] is False

    # ── Edge cases ──────────────────────────────────────────────────

    def test_summary_as_dict_not_list(self):
        """SUMMARY as a dict (not list) should still work."""
        t = self._telemetry(
            summary={
                "STATUS": [{"STATUS": "S"}],
                "SUMMARY": {"GHS 5s": "50", "Elapsed": "3600"},
            },
        )
        assert t["hashrate"] == 50e9

    def test_unreachable_returns_none(self):
        dev = _braiins_device()
        adapter = BraiinsAdapter(dev)

        with patch.object(adapter, "_rest_get", return_value=None), \
             patch.object(adapter, "_send_command", return_value=None):
            assert adapter.get_telemetry() is None

    def test_no_status_in_summary_returns_none(self):
        dev = _braiins_device()
        adapter = BraiinsAdapter(dev)

        with patch.object(adapter, "_rest_get", return_value=None), \
             patch.object(adapter, "_send_command",
                          return_value={"SUMMARY": [{"GHS 5s": "100"}]}):
            assert adapter.get_telemetry() is None

    def test_empty_summary_list(self):
        dev = _braiins_device()
        adapter = BraiinsAdapter(dev)

        with patch.object(adapter, "_rest_get", return_value=None), \
             patch.object(adapter, "_send_command",
                          return_value={"STATUS": [{"STATUS":"S"}],
                                        "SUMMARY": []}):
            t = adapter.get_telemetry()
        assert t is not None
        assert t["hashrate"] == 0  # empty list → default 0


# ═══════════════════════════════════════════════════════════════════════════
#  Telemetry — REST API path
# ═══════════════════════════════════════════════════════════════════════════

class TestBraiinsTelemetryRest:
    """Telemetry via the modern Braiins OS+ REST API (/api/v1/miner/stats)."""

    def test_rest_telemetry_with_miner_stats(self):
        dev = _braiins_device()
        adapter = BraiinsAdapter(dev)

        rest_data = {
            "miner_stats": {
                "hashrate_ghps": "120.5",
                "chip_temp_avg": "72.0",
                "board_temp_avg": "60.0",
                "uptime_s": 604800,
                "accepted_shares": 50000,
                "rejected_shares": 10,
                "stale_shares": 3,
                "best_share": "45T",
                "version": "braiins-os_2024-10",
                "model": "Antminer S19 Pro",
            },
            "pool_stats": {
                "url": "stratum+tcp://pool.braiins.com:3333",
                "user": "worker.braiins",
                "status": "mining",
            },
            "power_stats": {
                "power_avg": "3050",
            },
        }

        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = rest_data

        with patch("core.adapters.braiins_adapter.requests.get",
                   return_value=mock_resp), \
             patch.object(adapter, "_send_command") as mock_send:
            t = adapter.get_telemetry()

        # REST succeeded → _send_command never called
        mock_send.assert_not_called()

        assert t is not None
        assert t["hashrate"] == 120.5e9
        assert t["chip_temp"] == 72.0
        assert t["temperature"] == 60.0
        assert t["power"] == 3050
        assert t["uptime"] == 604800
        assert t["accepted_shares"] == 50000
        assert t["pool_status"] == "CONNECTED"
        assert t["pool"]["url"] == "stratum+tcp://pool.braiins.com:3333"
        assert t["source"] == "braiins_adapter"

    def test_rest_falls_back_to_cgminer_when_unavailable(self):
        dev = _braiins_device()
        adapter = BraiinsAdapter(dev)

        with patch.object(adapter, "_rest_get", return_value=None), \
             patch.object(adapter, "_send_command",
                          side_effect=lambda cmd, port=None:
                          {"STATUS": [{"STATUS":"S"}],
                           "SUMMARY": [{"GHS 5s": "100", "Elapsed": 3600}]}
                          if cmd == "summary" else None):
            t = adapter.get_telemetry()

        assert t is not None
        assert t["hashrate"] == 100e9
        assert t["source"] == "braiins_adapter"

    def test_rest_pool_disconnected(self):
        dev = _braiins_device()
        adapter = BraiinsAdapter(dev)

        rest_data = {
            "miner_stats": {"hashrate_ghps": "0"},
            "pool_stats": {
                "url": "stratum+tcp://dead.pool:3333",
                "user": "worker",
                "status": "disconnected",
            },
            "power_stats": {},
        }

        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = rest_data

        with patch("core.adapters.braiins_adapter.requests.get",
                   return_value=mock_resp):
            t = adapter.get_telemetry()

        assert t["pool_status"] == "DISCONNECTED"

    def test_rest_no_pool(self):
        dev = _braiins_device()
        adapter = BraiinsAdapter(dev)

        rest_data = {
            "miner_stats": {"hashrate_ghps": "0"},
            "pool_stats": {},
            "power_stats": {},
        }

        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = rest_data

        with patch("core.adapters.braiins_adapter.requests.get",
                   return_value=mock_resp):
            t = adapter.get_telemetry()

        assert t["pool_status"] is None


# ═══════════════════════════════════════════════════════════════════════════
#  Commands
# ═══════════════════════════════════════════════════════════════════════════

class TestBraiinsCommands:
    """Command execution (restart, identify)."""

    def test_restart_sends_command(self):
        dev = _braiins_device()
        adapter = BraiinsAdapter(dev)

        with patch.object(adapter, "_send_command",
                          return_value={"STATUS": [{"STATUS": "S"}]}):
            result = adapter.execute_command("restart")
        assert result["success"] is True
        assert result["command"] == "restart"

    def test_restart_fails(self):
        dev = _braiins_device()
        adapter = BraiinsAdapter(dev)

        with patch.object(adapter, "_send_command", return_value=None):
            result = adapter.execute_command("restart")
        assert result["success"] is False

    def test_identify_sends_led_command(self):
        dev = _braiins_device()
        adapter = BraiinsAdapter(dev)

        with patch.object(adapter, "_send_command",
                          return_value={"STATUS": [{"STATUS": "S"}]}):
            result = adapter.execute_command("identify")
        assert result["success"] is True
        assert result["command"] == "identify"

    def test_identify_not_supported_by_firmware(self):
        dev = _braiins_device()
        adapter = BraiinsAdapter(dev)

        with patch.object(adapter, "_send_command", return_value=None):
            result = adapter.execute_command("identify")
        assert result["success"] is False
        assert "not supported" in result.get("note", "").lower()

    def test_unsupported_command_returns_stub(self):
        dev = _braiins_device()
        adapter = BraiinsAdapter(dev)

        # 'set_frequency' is in capabilities as supported=False,
        # so `supports()` returns False and execute_command rejects early
        result = adapter.execute_command("set_frequency")
        assert result["success"] is False
        assert "not supported" in result["error"].lower()


# ═══════════════════════════════════════════════════════════════════════════
#  Detector integration
# ═══════════════════════════════════════════════════════════════════════════

class TestBraiinsDetector:
    """Firmware detection of Braiins OS+ via detector.py."""

    def test_detect_braiins_via_rest_api(self, monkeypatch):
        from core.registry.detector import detect_firmware

        # AxeOS probe must fail (ConnectionRefused); Braiins REST probe succeeds
        def fake_get(url, timeout):
            if "/api/system/info" in url:
                raise requests.ConnectionError("not axeos")
            # Braiins REST probe on port 80
            mock = Mock()
            mock.status_code = 200
            mock.json.return_value = {
                "miner_stats": {
                    "hashrate_ghps": "100",
                    "version": "braiins-os_2024-10",
                    "model": "Antminer S19 Pro",
                },
            }
            return mock

        monkeypatch.setattr("core.registry.detector.requests.get", fake_get)

        result = detect_firmware("10.0.0.1")
        assert result["firmware"] == "braiins"
        assert result["adapter_type"] == "braiins"
        assert result["reachable"] is True
        assert result["version"] == "braiins-os_2024-10"
        assert result["model"] == "Antminer S19 Pro"
        assert result["capabilities"]["telemetry"] is True
        assert result["capabilities"]["tuner_control"] is True

    def test_detect_braiins_via_cgminer_bosminer_version(self, monkeypatch):
        from core.registry.detector import detect_firmware

        # AxeOS + Braiins REST both fail; cgminer socket returns BOSminer
        monkeypatch.setattr("core.registry.detector.requests.get",
                            lambda url, timeout: (_ for _ in ()).throw(requests.ConnectionError("offline")))

        class FakeSock:
            def __init__(self, *a, **k): pass
            def settimeout(self, t): pass
            def connect(self, addr): pass
            def send(self, data): pass
            def recv(self, n):
                return b'{"STATUS":[{"STATUS":"S"}],"VERSION":[{"Version":"BOSminer 22.0","Type":"Antminer S19 Pro"}]}\x00'
            def close(self): pass

        monkeypatch.setattr("core.registry.detector.socket.socket",
                            lambda *a, **k: FakeSock())

        result = detect_firmware("10.0.0.2")
        assert result["firmware"] == "braiins"
        assert result["adapter_type"] == "braiins"
        assert "BOSminer" in result["version"]

    def test_detect_braiins_via_cgminer_braiins_type(self, monkeypatch):
        from core.registry.detector import detect_firmware

        monkeypatch.setattr("core.registry.detector.requests.get",
                            lambda url, timeout: (_ for _ in ()).throw(requests.ConnectionError("offline")))

        class FakeSock:
            def __init__(self, *a, **k): pass
            def settimeout(self, t): pass
            def connect(self, addr): pass
            def send(self, data): pass
            def recv(self, n):
                return b'{"STATUS":[{"STATUS":"S"}],"VERSION":[{"Version":"5.0","Type":"Antminer S19 (Braiins OS+)"}]}\x00'
            def close(self): pass

        monkeypatch.setattr("core.registry.detector.socket.socket",
                            lambda *a, **k: FakeSock())

        result = detect_firmware("10.0.0.3")
        assert result["firmware"] == "braiins"
        assert result["adapter_type"] == "braiins"

    def test_detect_cgminer_not_braiins_when_generic(self, monkeypatch):
        from core.registry.detector import detect_firmware

        monkeypatch.setattr("core.registry.detector.requests.get",
                            lambda url, timeout: (_ for _ in ()).throw(requests.ConnectionError("offline")))

        class FakeSock:
            def __init__(self, *a, **k): pass
            def settimeout(self, t): pass
            def connect(self, addr): pass
            def send(self, data): pass
            def recv(self, n):
                return b'{"STATUS":[{"STATUS":"S"}],"VERSION":[{"Version":"4.12.0","Type":"Antminer S19"}]}\x00'
            def close(self): pass

        monkeypatch.setattr("core.registry.detector.socket.socket",
                            lambda *a, **k: FakeSock())

        result = detect_firmware("10.0.0.4")
        # Falls through to generic cgminer detection
        assert result["firmware"] == "cgminer"
        assert result["adapter_type"] == "cgminer"

    def test_detect_unknown_when_all_fail(self, monkeypatch):
        from core.registry.detector import detect_firmware

        monkeypatch.setattr("core.registry.detector.requests.get",
                            lambda url, timeout: (_ for _ in ()).throw(requests.ConnectionError("offline")))
        monkeypatch.setattr("core.registry.detector.socket.socket",
                            lambda *a, **k: (_ for _ in ()).throw(ConnectionRefusedError))

        result = detect_firmware("10.0.0.99")
        assert result["firmware"] == "unknown"
        assert result["adapter_type"] == "unknown"
        assert result["reachable"] is False

    def test_detect_axeos_declares_full_command_family(self, monkeypatch):
        """P0 Bitaxe parity: an AxeOS device must expose pause/resume/
        set_frequency/update_pool so the fleet grid renders real buttons
        (not dead ones). The detector is the single source of these caps."""
        from core.registry.detector import detect_firmware

        def fake_get(url, timeout):
            if "/api/system/info" not in url:
                raise requests.ConnectionError("wrong probe")
            mock = Mock()
            mock.status_code = 200
            mock.json.return_value = {
                "version": "3.2.0",
                "model": "Bitaxe Gamma",
                "hashrate": 4100000000000,
                "frequency": 550,
            }
            return mock

        monkeypatch.setattr("core.registry.detector.requests.get", fake_get)

        result = detect_firmware("10.0.0.7")
        assert result["firmware"] == "axeos"
        assert result["adapter_type"] == "bitaxe"
        caps = result["capabilities"]
        # P0 command family — every value must be truthy so
        # _caps_supported_commands() renders the buttons.
        for cmd in ("telemetry", "restart", "identify", "pause",
                    "resume", "set_frequency", "update_pool",
                    "frequencyControl"):
            assert caps.get(cmd) is True, f"{cmd} must be True, got {caps.get(cmd)}"

    def test_detect_cgminer_has_no_identify_or_pause(self, monkeypatch):
        """Generic cgminer must stay honest: no identify/pause (its API has
        no such commands) — prevents dead buttons on non-Bitaxe devices."""
        from core.registry.detector import detect_firmware

        monkeypatch.setattr("core.registry.detector.requests.get",
                            lambda url, timeout: (_ for _ in ()).throw(requests.ConnectionError("offline")))

        class FakeSock:
            def __init__(self, *a, **k): pass
            def settimeout(self, t): pass
            def connect(self, addr): pass
            def send(self, data): pass
            def recv(self, n):
                return b'{"STATUS":[{"STATUS":"S"}],"VERSION":[{"Version":"4.12.0","Type":"Antminer S19"}]}\x00'
            def close(self): pass

        monkeypatch.setattr("core.registry.detector.socket.socket",
                            lambda *a, **k: FakeSock())

        result = detect_firmware("10.0.0.8")
        assert result["firmware"] == "cgminer"
        caps = result["capabilities"]
        assert caps.get("identify") is False or "identify" not in caps
        assert caps.get("pause") is False or "pause" not in caps
        assert caps.get("set_frequency") is False


# ═══════════════════════════════════════════════════════════════════════════
#  Adapter factory (__init__.py)
# ═══════════════════════════════════════════════════════════════════════════

class TestBraiinsAdapterFactory:
    """core/adapters/__init__.py::get_adapter() selects BraiinsAdapter."""

    def test_get_adapter_for_braiins_firmware(self):
        from core.adapters import get_adapter
        dev = Device(name="s19-braiins", model="Antminer S19 Pro",
                     firmware="Braiins OS+", ip="10.0.0.1")
        adapter = get_adapter(dev)
        assert isinstance(adapter, BraiinsAdapter)

    def test_get_adapter_for_bosminer_firmware(self):
        from core.adapters import get_adapter
        dev = Device(name="s19-bos", model="Antminer S19",
                     firmware="BOSminer 22.0", ip="10.0.0.2")
        adapter = get_adapter(dev)
        assert isinstance(adapter, BraiinsAdapter)

    def test_get_adapter_for_braiins_model(self):
        from core.adapters import get_adapter
        dev = Device(name="worker1", model="Braiins Antminer S19",
                     firmware="", ip="10.0.0.3")
        adapter = get_adapter(dev)
        assert isinstance(adapter, BraiinsAdapter)
