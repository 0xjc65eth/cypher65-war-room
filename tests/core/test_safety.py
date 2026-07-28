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
