"""
CYPHER65 // CgMiner Adapter — unit tests
========================================
Covers core/adapters/cgminer_adapter.py (44% → target ≥90%):
  - _send_command: success, no host, timeout, connection refused, bad JSON
  - get_telemetry: no summary, full parse (temp/vr_temp, shares, uptime)
  - execute_command: restart, unimplemented command
  - get_capabilities
  - health_check: reachable / unreachable
  - supports() fallback from base adapter
"""
import json
import socket
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock

from core.models.device import Device, DeviceStatus
from core.adapters.cgminer_adapter import CgminerAdapter, CGMINER_TIMEOUT


def _make_adapter(ip="192.168.1.50"):
    dev = Device(ip=ip, name="s19")
    return CgminerAdapter(dev)


# ═══════════════════════════════════════════════════════════════════════════
# 1. _send_command
# ═══════════════════════════════════════════════════════════════════════════

class TestSendCommand:
    def test_no_host_returns_none(self):
        dev = Device(ip=None)
        adapter = CgminerAdapter(dev)
        assert adapter._send_command("summary") is None

    def test_success_roundtrip(self):
        adapter = _make_adapter()
        fake_sock = MagicMock()
        # recv returns chunk then null byte then empty
        fake_sock.recv.side_effect = [b'{"STATUS":[{"STATUS":"S"}],', b'"SUMMARY":[{"GHS av":1}]}\x00', b""]
        with patch.object(socket, "socket", return_value=fake_sock):
            result = adapter._send_command("summary")
        assert result is not None
        assert result["STATUS"][0]["STATUS"] == "S"
        # payload must have been a JSON command + newline
        sent = fake_sock.send.call_args[0][0]
        payload = json.loads(sent.decode())
        assert payload["command"] == "summary"

    def test_connection_refused_returns_none(self):
        adapter = _make_adapter()
        fake_sock = MagicMock()
        fake_sock.connect.side_effect = ConnectionRefusedError("refused")
        with patch.object(socket, "socket", return_value=fake_sock):
            assert adapter._send_command("summary") is None

    def test_timeout_returns_none(self):
        adapter = _make_adapter()
        fake_sock = MagicMock()
        fake_sock.connect.side_effect = socket.timeout("timeout")
        with patch.object(socket, "socket", return_value=fake_sock):
            assert adapter._send_command("summary") is None

    def test_bad_json_returns_none(self):
        adapter = _make_adapter()
        fake_sock = MagicMock()
        fake_sock.recv.side_effect = [b"not-json\x00", b""]
        with patch.object(socket, "socket", return_value=fake_sock):
            assert adapter._send_command("summary") is None

    def test_oserror_returns_none(self):
        adapter = _make_adapter()
        fake_sock = MagicMock()
        fake_sock.recv.side_effect = OSError("closed")
        with patch.object(socket, "socket", return_value=fake_sock):
            assert adapter._send_command("summary") is None

    def test_empty_response_returns_none(self):
        adapter = _make_adapter()
        fake_sock = MagicMock()
        fake_sock.recv.side_effect = [b"", b""]
        with patch.object(socket, "socket", return_value=fake_sock):
            assert adapter._send_command("summary") is None

    def test_socket_closed_on_error(self):
        adapter = _make_adapter()
        fake_sock = MagicMock()
        fake_sock.connect.side_effect = OSError("boom")
        with patch.object(socket, "socket", return_value=fake_sock):
            adapter._send_command("summary")
        fake_sock.close.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════
# 2. get_telemetry
# ═══════════════════════════════════════════════════════════════════════════

class TestGetTelemetry:
    def test_no_summary_returns_none(self):
        adapter = _make_adapter()
        with patch.object(adapter, "_send_command", return_value=None):
            assert adapter.get_telemetry() is None

    def test_full_parse(self):
        adapter = _make_adapter()
        summary = {
            "STATUS": [{"STATUS": "S"}],
            "SUMMARY": [{"GHS av": 14.5, "Accepted": 100, "Rejected": 2,
                         "Stale": 1, "Elapsed": 3600, "Best Share": "123T"}],
        }
        stats = {"STATS": [{}, {"temp2_0": 68, "temp2_1": 72}]}
        pools = {"POOLS": []}

        def fake_send(cmd):
            return {"summary": summary, "stats": stats, "pools": pools}[cmd]

        with patch.object(adapter, "_send_command", side_effect=fake_send):
            t = adapter.get_telemetry()
        assert t is not None
        assert t["source"] == "cgminer_adapter"
        assert t["hashrate"] == 14.5 * 1e9  # GHS → H/s
        assert t["accepted_shares"] == 100
        assert t["rejected_shares"] == 2
        assert t["stale_shares"] == 1
        assert t["uptime"] == 3600
        assert t["best_difficulty"] == "123T"
        assert t["chip_temp"] == 68
        assert t["vr_temp"] == 72
        assert t["stub"] is False

    def test_summary_missing_hr_keys_default_zero(self):
        adapter = _make_adapter()
        summary = {"STATUS": [{"STATUS": "S"}], "SUMMARY": [{}]}
        with patch.object(adapter, "_send_command", return_value=summary):
            t = adapter.get_telemetry()
        assert t["hashrate"] == 0
        assert t["accepted_shares"] == 0

    def test_no_stats_section(self):
        adapter = _make_adapter()
        summary = {"STATUS": [{"STATUS": "S"}], "SUMMARY": [{"GHS av": 1}]}
        stats = {"STATS": [{}]}
        with patch.object(adapter, "_send_command",
                          side_effect=lambda c: summary if c == "summary" else stats):
            t = adapter.get_telemetry()
        assert t["chip_temp"] is None
        assert t["vr_temp"] is None


# ═══════════════════════════════════════════════════════════════════════════
# 3. execute_command / capabilities / health_check
# ═══════════════════════════════════════════════════════════════════════════

class TestCommands:
    def test_restart_success(self):
        adapter = _make_adapter()
        with patch.object(adapter, "_send_command", return_value={"STATUS": ["ok"]}):
            result = adapter.execute_command("restart")
        assert result == {"success": True, "stub": False}

    def test_restart_failure(self):
        adapter = _make_adapter()
        with patch.object(adapter, "_send_command", return_value=None):
            result = adapter.execute_command("restart")
        assert result["success"] is False

    def test_unimplemented_command(self):
        adapter = _make_adapter()
        result = adapter.execute_command("set_frequency")
        assert result["success"] is False
        assert result["stub"] is True
        assert "not implemented" in result["note"]

    def test_capabilities(self):
        adapter = _make_adapter()
        caps = adapter.get_capabilities()
        names = {c.name: c.supported for c in caps}
        assert names["telemetry"] is True
        assert names["restart"] is True
        assert names["set_frequency"] is False

    def test_health_check_reachable(self):
        adapter = _make_adapter()
        with patch.object(adapter, "_send_command", return_value={"STATUS": ["ok"]}):
            assert adapter.health_check() == {"status": "reachable", "reachable": True}

    def test_health_check_unreachable(self):
        adapter = _make_adapter()
        with patch.object(adapter, "_send_command", return_value=None):
            assert adapter.health_check() == {"status": "unreachable", "reachable": False}

    def test_supports_fallback_to_adapter(self):
        adapter = _make_adapter()
        # Device without capabilities metadata → adapter list is consulted
        assert adapter.supports("restart") is True
        assert adapter.supports("set_frequency") is False
