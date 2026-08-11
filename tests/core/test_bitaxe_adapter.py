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

        assert len(capabilities) == 8
        names = {c.name for c in capabilities}
        assert "telemetry" in names
        assert "restart" in names
        assert "identify" in names
        assert "logs" in names
        assert "pause" in names
        assert "resume" in names
        assert "set_frequency" in names
        assert "update_pool" in names
        assert next(c for c in capabilities if c.name == "set_frequency").supported is True

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

    def test_execute_command_unsupported_command(self):
        device = self._device_with_capabilities()
        adapter = BitaxeAdapter(device)

        result = adapter.execute_command("firmware_flash")

        assert result["success"] is False
        assert "not supported" in result["error"].lower()

    def test_execute_command_pause_makes_request(self):
        device = self._device_with_capabilities()
        adapter = BitaxeAdapter(device)

        with patch("core.adapters.bitaxe_adapter.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.raise_for_status = Mock()
            mock_post.return_value = mock_response

            result = adapter.execute_command("pause")

        assert result["success"] is True
        assert result["command"] == "pause"
        mock_post.assert_called_once_with("http://192.168.1.100/api/system/miningPause", timeout=5)

    def test_execute_command_resume_makes_request(self):
        device = self._device_with_capabilities()
        adapter = BitaxeAdapter(device)

        with patch("core.adapters.bitaxe_adapter.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.raise_for_status = Mock()
            mock_post.return_value = mock_response

            result = adapter.execute_command("resume")

        assert result["success"] is True
        assert result["command"] == "resume"
        mock_post.assert_called_once_with("http://192.168.1.100/api/system/miningResume", timeout=5)

    def test_execute_command_set_frequency_posts_overclock(self):
        device = self._device_with_capabilities()
        adapter = BitaxeAdapter(device)

        with patch("core.adapters.bitaxe_adapter.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.raise_for_status = Mock()
            mock_post.return_value = mock_response

            result = adapter.execute_command("set_frequency",
                                             {"frequency": 550, "coreVoltage": 1200})

        assert result["success"] is True
        assert result["command"] == "set_frequency"
        mock_post.assert_called_once_with(
            "http://192.168.1.100/api/system/overclock",
            json={"frequency": 550, "coreVoltage": 1200},
            timeout=5,
        )

    def test_execute_command_set_frequency_clamps_out_of_range(self):
        """Sanity clamps: absurd frequency/voltage never reach the ASIC."""
        device = self._device_with_capabilities()
        adapter = BitaxeAdapter(device)

        with patch("core.adapters.bitaxe_adapter.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.raise_for_status = Mock()
            mock_post.return_value = mock_response

            result = adapter.execute_command(
                "set_frequency",
                {"frequency": 99999, "coreVoltage": 9999, "powerLimit": 9999},
            )

        assert result["success"] is True
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["frequency"] == 2000   # clamped high
        assert kwargs["json"]["coreVoltage"] == 1600  # clamped high
        assert kwargs["json"]["powerLimit"] == 300    # clamped high

    def test_execute_command_set_frequency_requires_payload(self):
        device = self._device_with_capabilities()
        adapter = BitaxeAdapter(device)

        with patch("core.adapters.bitaxe_adapter.requests.post") as mock_post:
            result = adapter.execute_command("set_frequency", {})

        assert result["success"] is False
        mock_post.assert_not_called()

    def test_execute_command_unknown_keys_not_forwarded(self):
        """Only known overclock keys reach the device — no echo of arbitrary input."""
        device = self._device_with_capabilities()
        adapter = BitaxeAdapter(device)

        with patch("core.adapters.bitaxe_adapter.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.raise_for_status = Mock()
            mock_post.return_value = mock_response

            result = adapter.execute_command(
                "set_frequency",
                {"frequency": 550, "evil": "injected"},
            )

        assert result["success"] is True
        _, kwargs = mock_post.call_args
        assert "evil" not in kwargs["json"]
        assert kwargs["json"] == {"frequency": 550}

    def test_execute_command_update_pool_posts_payload(self):
        device = self._device_with_capabilities()
        adapter = BitaxeAdapter(device)

        with patch("core.adapters.bitaxe_adapter.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.raise_for_status = Mock()
            mock_post.return_value = mock_response

            result = adapter.execute_command(
                "update_pool",
                {"stratumURL": "stratum+tcp://pool.example.com", "stratumPort": 3333, "stratumUser": "user.worker"},
            )

        assert result["success"] is True
        mock_post.assert_called_once_with(
            "http://192.168.1.100/api/system/updatePool",
            json={"stratumURL": "stratum+tcp://pool.example.com", "stratumPort": 3333, "stratumUser": "user.worker"},
            timeout=5,
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Fase 5 · Hashrate windows (1m / 10m / 1h)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestHashrateWindows:
    """Fase 5: hashrate windows with field-name fallbacks."""

    @staticmethod
    def _telemetry(data: dict) -> dict:
        device = Device(name="Bitaxe", model="Bitaxe Max", ip="192.168.1.100")
        adapter = BitaxeAdapter(device)
        mock_response = Mock()
        mock_response.json.return_value = data
        mock_response.raise_for_status = Mock()
        with patch("core.adapters.bitaxe_adapter.requests.get", return_value=mock_response):
            return adapter.get_telemetry()

    def test_hashrate_1h_from_hashRate1hr_primary(self):
        """hashRate1hr is the canonical key; read directly."""
        t = self._telemetry({"hashRate1hr": 1.1e12})
        assert t["hashrate_1h"] == 1.1e12

    def test_hashrate_1h_fallback_to_hashRate1h(self):
        """When hashRate1hr is absent, fall back to hashRate1h."""
        t = self._telemetry({"hashRate1h": 1.2e12})
        assert t["hashrate_1h"] == 1.2e12

    def test_hashrate_1h_prefers_hashRate1hr_over_1h(self):
        """When both keys are present, hashRate1hr wins."""
        t = self._telemetry({"hashRate1hr": 1.1e12, "hashRate1h": 1.2e12})
        assert t["hashrate_1h"] == 1.1e12

    def test_hashrate_1m_direct_read(self):
        t = self._telemetry({"hashRate1m": 0.9e12})
        assert t["hashrate_1m"] == 0.9e12

    def test_hashrate_10m_direct_read(self):
        t = self._telemetry({"hashRate10m": 0.85e12})
        assert t["hashrate_10m"] == 0.85e12

    def test_all_windows_absent_are_none(self):
        """Empty payload → all windows are None (Honest Telemetry)."""
        t = self._telemetry({})
        assert t["hashrate_1m"] is None
        assert t["hashrate_10m"] is None
        assert t["hashrate_1h"] is None

    def test_hashrate_5m_not_promoted_to_10m(self):
        """Honest Telemetry: hashRate5m is never promoted to hashRate10m."""
        t = self._telemetry({"hashRate5m": 1e12})
        # 5m key is ignored — 10m stays None
        assert t["hashrate_10m"] is None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Fase 5 · chip_temp derivation (tempChip → temp fallback)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestChipTempDerivation:
    """Fase 5: chip_temp = tempChip (primary) else temperature fallback."""

    @staticmethod
    def _telemetry(data: dict) -> dict:
        device = Device(name="Bitaxe", model="Bitaxe Max", ip="192.168.1.100")
        adapter = BitaxeAdapter(device)
        mock_response = Mock()
        mock_response.json.return_value = data
        mock_response.raise_for_status = Mock()
        with patch("core.adapters.bitaxe_adapter.requests.get", return_value=mock_response):
            return adapter.get_telemetry()

    def test_chip_temp_from_tempChip_direct(self):
        """tempChip present → chip_temp = tempChip (not temp)."""
        t = self._telemetry({"tempChip": 72, "temp": 65})
        assert t["chip_temp"] == 72

    def test_chip_temp_fallback_to_temp_when_tempChip_absent(self):
        """tempChip absent → fallback to temp (main temperature)."""
        t = self._telemetry({"temp": 68})
        assert t["chip_temp"] == 68

    def test_chip_temp_zero_when_both_absent(self):
        """Neither tempChip nor temp → chip_temp is 0.0 (temperature default)."""
        t = self._telemetry({})
        assert t["chip_temp"] == 0.0

    def test_chip_temp_with_tempChip_zero(self):
        """tempChip=0 is a valid reading, not treated as absent."""
        t = self._telemetry({"tempChip": 0, "temp": 45})
        assert t["chip_temp"] == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Fase 5 · pool_status derivation (CONNECTED / PAUSED / NOT CONFIGURED)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestPoolStatusDerivation:
    """Fase 5 · pool_status derived from miningPaused + stratumURL."""

    @staticmethod
    def _telemetry(data: dict) -> dict:
        device = Device(name="Bitaxe", model="Bitaxe Max", ip="192.168.1.100")
        adapter = BitaxeAdapter(device)
        mock_response = Mock()
        mock_response.json.return_value = data
        mock_response.raise_for_status = Mock()
        with patch("core.adapters.bitaxe_adapter.requests.get", return_value=mock_response):
            return adapter.get_telemetry()

    def test_pool_connected_when_mining_and_url_present(self):
        """miningPaused=False + stratumURL → CONNECTED."""
        t = self._telemetry({
            "miningPaused": False,
            "stratumURL": "stratum+tcp://pool.btc.com:3333",
            "stratumPort": 3333,
            "stratumUser": "user.worker",
        })
        assert t["pool_status"] == "CONNECTED"
        assert t["pool"]["url"] == "stratum+tcp://pool.btc.com:3333"

    def test_pool_paused_when_mining_paused(self):
        """miningPaused=True → PAUSED (regardless of pool config)."""
        t = self._telemetry({
            "miningPaused": True,
            "stratumURL": "stratum+tcp://pool.btc.com:3333",
        })
        assert t["pool_status"] == "PAUSED"

    def test_pool_not_configured_when_no_url(self):
        """miningPaused=False but no stratumURL → NOT CONFIGURED."""
        t = self._telemetry({"miningPaused": False})
        assert t["pool_status"] == "NOT CONFIGURED"
        assert t["pool"]["url"] == ""

    def test_pool_not_configured_when_empty_url(self):
        """stratumURL="" (empty string) → NOT CONFIGURED."""
        t = self._telemetry({"miningPaused": False, "stratumURL": ""})
        assert t["pool_status"] == "NOT CONFIGURED"

    def test_pool_url_fallback_to_poolURL(self):
        """stratumURL absent → fallback to poolURL."""
        t = self._telemetry({
            "miningPaused": False,
            "poolURL": "stratum+tcp://fallback.example.com:4444",
            "stratumPort": 4444,
            "stratumUser": "fallback.user",
        })
        assert t["pool_status"] == "CONNECTED"
        assert t["pool"]["url"] == "stratum+tcp://fallback.example.com:4444"

    def test_pool_paused_takes_priority_over_connected(self):
        """Paused always wins, even with a valid stratum config."""
        t = self._telemetry({
            "miningPaused": True,
            "stratumURL": "stratum+tcp://pool.btc.com:3333",
            "stratumPort": 3333,
            "stratumUser": "paused.user",
        })
        assert t["pool_status"] == "PAUSED"
        # Pool identity still populated even when paused
        assert t["pool"]["url"] != ""

    def test_pool_fields_empty_when_not_configured(self):
        """No pool data → pool dict is all empty/zero."""
        t = self._telemetry({})
        assert t["pool"] == {"url": "", "port": 0, "user": ""}
        assert t["worker"] == ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Fase 5 · Field-name fallbacks (dual-key compatibility)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestFieldNameFallbacks:
    """Fase 5: every field with dual-key fallback is tested independently."""

    @staticmethod
    def _telemetry(data: dict) -> dict:
        device = Device(name="Bitaxe", model="Bitaxe Max", ip="192.168.1.100")
        adapter = BitaxeAdapter(device)
        mock_response = Mock()
        mock_response.json.return_value = data
        mock_response.raise_for_status = Mock()
        with patch("core.adapters.bitaxe_adapter.requests.get", return_value=mock_response):
            return adapter.get_telemetry()

    # ── hashrate ───────────────────────────────────────────────────

    def test_hashrate_from_hashRate_primary(self):
        t = self._telemetry({"hashRate": 5e12})
        assert t["hashrate"] == 5e12

    def test_hashrate_fallback_to_hashrate_lowercase(self):
        t = self._telemetry({"hashrate": 6e12})
        assert t["hashrate"] == 6e12

    def test_hashrate_prefers_hashRate_over_hashrate(self):
        t = self._telemetry({"hashRate": 5e12, "hashrate": 6e12})
        assert t["hashrate"] == 5e12

    # ── temperature ────────────────────────────────────────────────

    def test_temperature_from_temp_primary(self):
        t = self._telemetry({"temp": 72})
        assert t["temperature"] == 72

    def test_temperature_fallback_to_temperature(self):
        t = self._telemetry({"temperature": 74})
        assert t["temperature"] == 74

    def test_temperature_prefers_temp_over_temperature(self):
        t = self._telemetry({"temp": 72, "temperature": 74})
        assert t["temperature"] == 72

    # ── voltage ────────────────────────────────────────────────────

    def test_voltage_from_voltage_primary(self):
        t = self._telemetry({"voltage": 1200})
        assert t["voltage"] == 1200

    def test_voltage_fallback_to_coreVoltage(self):
        t = self._telemetry({"coreVoltage": 1180})
        assert t["voltage"] == 1180

    def test_voltage_prefers_voltage_over_coreVoltage(self):
        t = self._telemetry({"voltage": 1200, "coreVoltage": 1180})
        assert t["voltage"] == 1200

    # ── frequency ──────────────────────────────────────────────────

    def test_frequency_from_frequency_primary(self):
        t = self._telemetry({"frequency": 550})
        assert t["frequency"] == 550

    def test_frequency_fallback_to_actualFrequency(self):
        t = self._telemetry({"actualFrequency": 548})
        assert t["frequency"] == 548

    def test_frequency_prefers_frequency_over_actualFrequency(self):
        t = self._telemetry({"frequency": 550, "actualFrequency": 548})
        assert t["frequency"] == 550

    # ── fan_speed ──────────────────────────────────────────────────

    def test_fan_speed_from_fanspeed_primary(self):
        t = self._telemetry({"fanspeed": 80})
        assert t["fan_speed"] == 80

    def test_fan_speed_fallback_to_fanSpeed(self):
        t = self._telemetry({"fanSpeed": 85})
        assert t["fan_speed"] == 85

    def test_fan_speed_prefers_fanspeed_over_fanSpeed(self):
        t = self._telemetry({"fanspeed": 80, "fanSpeed": 85})
        assert t["fan_speed"] == 80

    # ── uptime ─────────────────────────────────────────────────────

    def test_uptime_from_uptimeSeconds_primary(self):
        t = self._telemetry({"uptimeSeconds": 3600})
        assert t["uptime"] == 3600

    def test_uptime_fallback_to_uptime(self):
        t = self._telemetry({"uptime": 1800})
        assert t["uptime"] == 1800

    def test_uptime_prefers_uptimeSeconds_over_uptime(self):
        t = self._telemetry({"uptimeSeconds": 3600, "uptime": 1800})
        assert t["uptime"] == 3600

    # ── best_difficulty ────────────────────────────────────────────

    def test_best_diff_from_bestDiff_primary(self):
        t = self._telemetry({"bestDiff": "5T"})
        assert t["best_difficulty"] == "5T"

    def test_best_diff_fallback_to_bestDifficulty(self):
        t = self._telemetry({"bestDifficulty": "10T"})
        assert t["best_difficulty"] == "10T"

    def test_best_diff_prefers_bestDiff_over_bestDifficulty(self):
        t = self._telemetry({"bestDiff": "5T", "bestDifficulty": "10T"})
        assert t["best_difficulty"] == "5T"

    def test_best_diff_empty_when_both_absent(self):
        t = self._telemetry({})
        assert t["best_difficulty"] == ""

    # ── best_session_difficulty ────────────────────────────────────

    def test_best_session_diff_from_bestSessionDiff_primary(self):
        t = self._telemetry({"bestSessionDiff": "3T"})
        assert t["best_session_difficulty"] == "3T"

    def test_best_session_diff_fallback_to_bestSessionDifficulty(self):
        t = self._telemetry({"bestSessionDifficulty": "4T"})
        assert t["best_session_difficulty"] == "4T"

    def test_best_session_diff_prefers_bestSessionDiff(self):
        t = self._telemetry({"bestSessionDiff": "3T", "bestSessionDifficulty": "4T"})
        assert t["best_session_difficulty"] == "3T"

    # ── stale_shares ───────────────────────────────────────────────

    def test_stale_shares_from_sharesStale_primary(self):
        t = self._telemetry({"sharesStale": 3})
        assert t["stale_shares"] == 3

    def test_stale_shares_fallback_to_staleShares(self):
        t = self._telemetry({"staleShares": 7})
        assert t["stale_shares"] == 7

    def test_stale_shares_prefers_sharesStale_over_staleShares(self):
        t = self._telemetry({"sharesStale": 3, "staleShares": 7})
        assert t["stale_shares"] == 3

    # ── worker ─────────────────────────────────────────────────────

    def test_worker_from_stratumUser_primary(self):
        t = self._telemetry({"stratumUser": "primary.user"})
        assert t["worker"] == "primary.user"

    def test_worker_fallback_to_worker_field(self):
        t = self._telemetry({"worker": "fallback.user"})
        assert t["worker"] == "fallback.user"

    def test_worker_prefers_stratumUser_over_worker(self):
        t = self._telemetry({"stratumUser": "primary.user", "worker": "fallback.user"})
        assert t["worker"] == "primary.user"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Fase 5 · fan_rpm, vr_temp, and cooling edge cases
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestFanRpmAndVrTemp:
    """Fase 5: fan_rpm, fan_rpm_2, vr_temp with missing-field behaviour."""

    @staticmethod
    def _telemetry(data: dict) -> dict:
        device = Device(name="Bitaxe", model="Bitaxe Max", ip="192.168.1.100")
        adapter = BitaxeAdapter(device)
        mock_response = Mock()
        mock_response.json.return_value = data
        mock_response.raise_for_status = Mock()
        with patch("core.adapters.bitaxe_adapter.requests.get", return_value=mock_response):
            return adapter.get_telemetry()

    def test_fan_rpm_from_fanrpm(self):
        t = self._telemetry({"fanrpm": 4500})
        assert t["fan_rpm"] == 4500

    def test_fan_rpm_zero_when_absent(self):
        t = self._telemetry({})
        assert t["fan_rpm"] == 0

    def test_fan_rpm_2_from_fan2rpm(self):
        t = self._telemetry({"fan2rpm": 4300})
        assert t["fan_rpm_2"] == 4300

    def test_fan_rpm_2_zero_when_absent(self):
        t = self._telemetry({})
        assert t["fan_rpm_2"] == 0

    def test_vr_temp_from_vrTemp(self):
        t = self._telemetry({"vrTemp": 68})
        assert t["vr_temp"] == 68

    def test_vr_temp_zero_when_absent(self):
        t = self._telemetry({})
        assert t["vr_temp"] == 0

    def test_all_cooling_fields_present(self):
        t = self._telemetry({"fanrpm": 4500, "fan2rpm": 4300, "vrTemp": 68, "fanspeed": 80})
        assert t["fan_rpm"] == 4500
        assert t["fan_rpm_2"] == 4300
        assert t["vr_temp"] == 68
        assert t["fan_speed"] == 80

    def test_temperature_2_from_temp2(self):
        t = self._telemetry({"temp2": 70})
        assert t["temperature_2"] == 70

    def test_temperature_2_zero_when_absent(self):
        t = self._telemetry({})
        assert t["temperature_2"] == 0

    def test_power_from_power_field(self):
        t = self._telemetry({"power": 30})
        assert t["power"] == 30

    def test_max_power_from_maxPower(self):
        t = self._telemetry({"maxPower": 35})
        assert t["max_power"] == 35

    def test_wifi_rssi_from_wifiRSSI(self):
        t = self._telemetry({"wifiRSSI": -55})
        assert t["wifi_rssi"] == -55

    def test_wifi_rssi_zero_when_absent(self):
        t = self._telemetry({})
        assert t["wifi_rssi"] == 0

    def test_core_voltage_actual_from_coreVoltageActual(self):
        t = self._telemetry({"coreVoltageActual": 1180})
        assert t["core_voltage_actual"] == 1180

    def test_accepted_shares_from_sharesAccepted(self):
        t = self._telemetry({"sharesAccepted": 100})
        assert t["accepted_shares"] == 100

    def test_rejected_shares_from_sharesRejected(self):
        t = self._telemetry({"sharesRejected": 2})
        assert t["rejected_shares"] == 2

    def test_pool_difficulty_from_poolDifficulty(self):
        t = self._telemetry({"poolDifficulty": 65536})
        assert t["pool_difficulty"] == 65536

    def test_hostname_from_hostname_field(self):
        t = self._telemetry({"hostname": "bitaxe-001"})
        assert t["hostname"] == "bitaxe-001"
