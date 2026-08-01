"""Tests for core/adapters/bitaxe_adapter.py."""
from unittest.mock import Mock, patch

import pytest
import requests

from core.adapters.bitaxe_adapter import BitaxeAdapter
from core.models.device import Device, DeviceStatus


class TestBitaxeAdapter:
    def test_get_capabilities(self):
        device = Device(name="Bitaxe", model="Bitaxe Max", ip="192.168.1.100")
        adapter = BitaxeAdapter(device)
        capabilities = adapter.get_capabilities()

        assert len(capabilities) == 5
        names = {c.name for c in capabilities}
        assert "telemetry" in names
        assert "restart" in names
        assert "identify" in names
        assert "logs" in names
        assert "set_frequency" in names

    def test_get_capabilities_telemetry_supported(self):
        device = Device(name="Bitaxe", model="Bitaxe Max", ip="192.168.1.100")
        adapter = BitaxeAdapter(device)
        capabilities = adapter.get_capabilities()

        telemetry_cap = next(c for c in capabilities if c.name == "telemetry")
        assert telemetry_cap.supported is True

    def test_get_telemetry_real_data(self):
        device = Device(name="Bitaxe", model="Bitaxe Max", ip="192.168.1.100")
        adapter = BitaxeAdapter(device)

        mock_response = Mock()
        mock_response.json.return_value = {
            "hashRate": 1234567890,
            "hashRate1m": 1200000000,
            "hashRate5m": 1180000000,
            "hashRate10m": 1170000000,
            "hashRate1hr": 1150000000,
            "temp": 75,
            "temp2": 70,
            "vrTemp": 68,
            "voltage": 1200,
            "coreVoltage": 1200,
            "coreVoltageActual": 1180,
            "frequency": 550,
            "actualFrequency": 548,
            "fanspeed": 80,
            "fanrpm": 4500,
            "fan2rpm": 4300,
            "power": 30,
            "maxPower": 35,
            "uptimeSeconds": 3600,
            "bestDiff": "5T",
            "sharesAccepted": 100,
            "sharesRejected": 2,
            "staleShares": 1,
            "poolDifficulty": 65536,
            "miningPaused": False,
            "stratumURL": "pool.example.com",
            "stratumPort": 3333,
            "stratumUser": "worker.001",
            "hostname": "bitaxe-001",
            "wifiRSSI": -55,
        }
        mock_response.raise_for_status = Mock()

        with patch("core.adapters.bitaxe_adapter.requests.get", return_value=mock_response):
            telemetry = adapter.get_telemetry()

        assert telemetry is not None
        assert telemetry["source"] == "bitaxe_adapter"
        assert telemetry["stub"] is False
        assert telemetry["hashrate"] == 1234567890
        # Fase 5: hashrate windows (hashRate10m read directly; 5m never
        # promoted to 10m — Honest Telemetry)
        assert telemetry["hashrate_1m"] == 1200000000
        assert telemetry["hashrate_10m"] == 1170000000
        assert telemetry["hashrate_1h"] == 1150000000
        # Fase 5: chip temp falls back to main temp when tempChip absent
        assert telemetry["chip_temp"] == 75
        assert telemetry["temperature"] == 75
        assert telemetry["temperature_2"] == 70
        assert telemetry["vr_temp"] == 68
        assert telemetry["voltage"] == 1200
        assert telemetry["core_voltage_actual"] == 1180
        assert telemetry["frequency"] == 550
        assert telemetry["fan_speed"] == 80
        assert telemetry["fan_rpm"] == 4500
        assert telemetry["power"] == 30
        assert telemetry["max_power"] == 35
        assert telemetry["uptime"] == 3600
        assert telemetry["best_difficulty"] == "5T"
        assert telemetry["accepted_shares"] == 100
        assert telemetry["rejected_shares"] == 2
        assert telemetry["stale_shares"] == 1
        assert telemetry["pool_difficulty"] == 65536
        assert telemetry["mining_paused"] is False
        assert telemetry["pool_status"] == "CONNECTED"
        assert telemetry["pool"] == {"url": "pool.example.com", "port": 3333, "user": "worker.001"}
        assert telemetry["worker"] == "worker.001"
        assert telemetry["hostname"] == "bitaxe-001"
        assert telemetry["wifi_rssi"] == -55
        assert "timestamp" in telemetry
        assert telemetry["freshness"] == 0
        assert telemetry["source"] == "bitaxe_adapter"

    def test_get_telemetry_stale_shares_zero(self):
        """Ensure stale_shares=0 is preserved and not overridden by fallback."""
        device = Device(name="Bitaxe", model="Bitaxe Max", ip="192.168.1.100")
        adapter = BitaxeAdapter(device)

        mock_response = Mock()
        mock_response.json.return_value = {
            "sharesStale": 0,
            "staleShares": 999,
        }
        mock_response.raise_for_status = Mock()

        with patch("core.adapters.bitaxe_adapter.requests.get", return_value=mock_response):
            telemetry = adapter.get_telemetry()

        assert telemetry is not None
        assert telemetry["stale_shares"] == 0

    def test_get_telemetry_missing_windows_are_none(self):
        """Fase 5: when the firmware does not expose hash-rate windows, the
        fields are None (serialization turns them into NOT AVAILABLE)."""
        device = Device(name="Bitaxe", model="Bitaxe Max", ip="192.168.1.100")
        adapter = BitaxeAdapter(device)

        mock_response = Mock()
        mock_response.json.return_value = {
            "hashRate": 1e12,
            "temp": 60,
            "vrTemp": 55,
            "miningPaused": True,
        }
        mock_response.raise_for_status = Mock()

        with patch("core.adapters.bitaxe_adapter.requests.get", return_value=mock_response):
            telemetry = adapter.get_telemetry()

        assert telemetry is not None
        assert telemetry["hashrate_1m"] is None
        assert telemetry["hashrate_10m"] is None
        assert telemetry["hashrate_1h"] is None
        assert telemetry["pool_status"] == "PAUSED"
        assert telemetry["chip_temp"] == 60

    def test_get_telemetry_offline(self):
        device = Device(name="Bitaxe", model="Bitaxe Max", ip="192.168.1.100")
        adapter = BitaxeAdapter(device)

        with patch("core.adapters.bitaxe_adapter.requests.get", side_effect=requests.RequestException("connection refused")):
            telemetry = adapter.get_telemetry()

        assert telemetry is None

    def _device_with_capabilities(self, ip="192.168.1.100"):
        device = Device(name="Bitaxe", model="Bitaxe Max", ip=ip)
        device.capabilities = BitaxeAdapter(device).get_capabilities()
        return device

    def test_execute_command_restart_makes_request(self):
        device = self._device_with_capabilities()
        adapter = BitaxeAdapter(device)

        with patch("core.adapters.bitaxe_adapter.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.raise_for_status = Mock()
            mock_post.return_value = mock_response

            result = adapter.execute_command("restart")

        assert result["success"] is True
        assert result["command"] == "restart"
        mock_post.assert_called_once_with("http://192.168.1.100/api/system/restart", timeout=5)

    def test_execute_command_identify_makes_request(self):
        device = self._device_with_capabilities()
        adapter = BitaxeAdapter(device)

        with patch("core.adapters.bitaxe_adapter.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.raise_for_status = Mock()
            mock_post.return_value = mock_response

            result = adapter.execute_command("identify")

        assert result["success"] is True
        assert result["command"] == "identify"
        mock_post.assert_called_once_with("http://192.168.1.100/api/system/blink", timeout=5)

    def test_execute_command_unsupported_returns_stub(self):
        device = self._device_with_capabilities()
        adapter = BitaxeAdapter(device)

        result = adapter.execute_command("set_frequency")

        assert result["success"] is False
        assert "not supported" in result["error"].lower()
