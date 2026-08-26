"""Tests for core/safety/safety_engine.py."""
import pytest

from core.safety.safety_engine import SafetyEngine, SafetyResult
from core.models.device import Device, DeviceStatus
from core.models.capability import RiskLevel


class TestSafetyEngine:
    def test_offline_device_blocked(self):
        engine = SafetyEngine()
        device = Device(name="Bitaxe", model="Bitaxe Max", status=DeviceStatus.OFFLINE)
        result = engine.validate_command(device, "restart")

        assert result.allowed is False
        assert "offline" in result.reason.lower()
        assert result.risk_level == RiskLevel.HIGH

    def test_online_device_allowed(self):
        engine = SafetyEngine()
        device = Device(name="Bitaxe", model="Bitaxe Max", status=DeviceStatus.ONLINE)
        result = engine.validate_command(device, "restart")

        assert result.allowed is True
        assert result.reason is None or result.reason == ""
        assert result.requires_confirmation is True
        assert result.risk_level == RiskLevel.MEDIUM

    @pytest.mark.parametrize(
        ("command", "risk_level"),
        [
            ("pause", RiskLevel.MEDIUM),
            ("resume", RiskLevel.MEDIUM),
            ("set_frequency", RiskLevel.HIGH),
            ("update_pool", RiskLevel.HIGH),
        ],
    )
    def test_state_changing_commands_require_confirmation(self, command, risk_level):
        engine = SafetyEngine()
        device = Device(name="Bitaxe", model="Bitaxe Max", status=DeviceStatus.ONLINE)

        result = engine.validate_command(device, command)

        assert result.allowed is True
        assert result.requires_confirmation is True
        assert result.risk_level == risk_level

    def test_high_temperature_blocked(self):
        engine = SafetyEngine(config={"max_temperature": 85})
        device = Device(name="Bitaxe", model="Bitaxe Max", status=DeviceStatus.ONLINE)
        device.current_telemetry = {"temperature": 95}
        result = engine.validate_command(device, "restart")

        assert result.allowed is False
        assert "temperature" in result.reason.lower()

    def test_safe_temperature_allowed(self):
        engine = SafetyEngine(config={"max_temperature": 85})
        device = Device(name="Bitaxe", model="Bitaxe Max", status=DeviceStatus.ONLINE)
        device.current_telemetry = {"temperature": 70}
        result = engine.validate_command(device, "restart")

        assert result.allowed is True

    # ── Coverage-123: the remaining 18 uncovered statements ──────────────

    def test_hashrate_too_low_blocked(self):
        """min_hashrate configured + hashrate <= floor → blocked."""
        engine = SafetyEngine(config={"min_hashrate": 10.0})
        device = Device(name="Bitaxe", model="Bitaxe Max", status=DeviceStatus.ONLINE)
        device.current_telemetry = {"temperature": 50, "hashrate": 5.0}
        result = engine.validate_command(device, "restart")

        assert result.allowed is False
        assert "hashrate" in result.reason.lower()

    def test_reject_rate_blocked(self):
        """reject share rate above max_reject_rate (default 5%) → blocked."""
        engine = SafetyEngine()
        device = Device(name="Bitaxe", model="Bitaxe Max", status=DeviceStatus.ONLINE)
        device.current_telemetry = {
            "temperature": 50, "hashrate": 5e12,
            "accepted_shares": 80, "rejected_shares": 20, "stale_shares": 0,
        }
        result = engine.validate_command(device, "restart")

        assert result.allowed is False
        assert "reject rate" in result.reason.lower()

    def test_stale_rate_blocked(self):
        """stale share rate above max_stale_rate (default 5%) → blocked."""
        engine = SafetyEngine()
        device = Device(name="Bitaxe", model="Bitaxe Max", status=DeviceStatus.ONLINE)
        device.current_telemetry = {
            "temperature": 50, "hashrate": 5e12,
            "accepted_shares": 80, "rejected_shares": 0, "stale_shares": 20,
        }
        result = engine.validate_command(device, "restart")

        assert result.allowed is False
        assert "stale rate" in result.reason.lower()

    def test_share_rates_with_zero_total_safe(self):
        """_rate with total=0 returns 0.0 (no division by zero)."""
        assert SafetyEngine._rate(0, 0) == 0.0
        assert SafetyEngine._rate(5, 0) == 0.0
        # Normal path still works.
        assert SafetyEngine._rate(25, 100) == 25.0

    def test_model_defaults_override_global(self):
        """Per-model defaults override global limits (layered config)."""
        engine = SafetyEngine(config={
            "max_temperature": 85,
            "model_defaults": {"bitaxe max": {"max_temperature": 70.0}},
        })
        device = Device(name="Bitaxe", model="Bitaxe Max", status=DeviceStatus.ONLINE)
        device.current_telemetry = {"temperature": 75}
        result = engine.validate_command(device, "restart")

        assert result.allowed is False
        assert "temperature" in result.reason.lower()

    def test_device_safety_config_overrides_all(self):
        """Per-device safety_config (metadata) has the highest priority."""
        engine = SafetyEngine(config={
            "max_temperature": 85,
            "model_defaults": {"bitaxe max": {"max_temperature": 70.0}},
        })
        device = Device(name="Bitaxe", model="Bitaxe Max", status=DeviceStatus.ONLINE)
        device.metadata = {"safety_config": {"max_temperature": 90.0}}
        device.current_telemetry = {"temperature": 88}
        result = engine.validate_command(device, "restart")

        assert result.allowed is True

    def test_restart_cooldown_active(self):
        """A restart right after another restart → blocked by cooldown."""
        engine = SafetyEngine(config={"restart_cooldown_minutes": 5})
        device = Device(name="Bitaxe", model="Bitaxe Max", status=DeviceStatus.ONLINE)
        device.current_telemetry = {"temperature": 50, "hashrate": 5e12}

        engine.record_restart(device)
        result = engine.validate_command(device, "restart")

        assert result.allowed is False
        assert "cooldown" in result.reason.lower()

    def test_other_command_ignores_cooldown(self):
        """Cooldown only gates 'restart' — other commands pass."""
        engine = SafetyEngine(config={"restart_cooldown_minutes": 5})
        device = Device(name="Bitaxe", model="Bitaxe Max", status=DeviceStatus.ONLINE)
        device.current_telemetry = {"temperature": 50, "hashrate": 5e12}

        engine.record_restart(device)
        result = engine.validate_command(device, "identify")

        assert result.allowed is True

    def test_no_telemetry_is_safe(self):
        """Device with no telemetry snapshot → no telemetry violations."""
        engine = SafetyEngine()
        device = Device(name="Bitaxe", model="Bitaxe Max", status=DeviceStatus.ONLINE)
        device.current_telemetry = None

        result = engine.validate_command(device, "restart")
        assert result.allowed is True
