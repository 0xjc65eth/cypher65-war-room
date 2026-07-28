"""Tests for core/diagnostics/diagnostics_engine.py."""

import pytest

from core.diagnostics.diagnostics_engine import DiagnosticsEngine, DiagnosticSeverity
from core.models.device import Device, DeviceStatus


class TestDiagnosticsEngine:
    def test_no_telemetry_returns_only_offline_info(self):
        engine = DiagnosticsEngine()
        device = Device(name="Bitaxe", model="Bitaxe Max", ip="192.168.1.100", status=DeviceStatus.OFFLINE)

        diagnostics = engine.analyze(device)

        assert len(diagnostics) == 1
        assert diagnostics[0].category == "connectivity"
        assert diagnostics[0].severity == DiagnosticSeverity.INFO

    def test_high_temperature(self):
        engine = DiagnosticsEngine(config={"max_temperature": 80})
        device = Device(name="Bitaxe", model="Bitaxe Max", ip="192.168.1.100", status=DeviceStatus.ONLINE)
        device.current_telemetry = {"temperature": 95}

        diagnostics = engine.analyze(device)

        assert any(d.category == "temperature" and d.severity == DiagnosticSeverity.CRITICAL for d in diagnostics)

    def test_low_hashrate(self):
        engine = DiagnosticsEngine(config={"expected_hashrate": 1e12, "hashrate_drop_pct": 20})
        device = Device(name="Bitaxe", model="Bitaxe Max", ip="192.168.1.100", status=DeviceStatus.ONLINE)
        device.current_telemetry = {"hashrate": 1e11}

        diagnostics = engine.analyze(device)

        hashrate_diag = next((d for d in diagnostics if d.category == "hashrate"), None)
        assert hashrate_diag is not None
        assert hashrate_diag.severity == DiagnosticSeverity.WARNING

    def test_high_reject_rate(self):
        engine = DiagnosticsEngine(config={"max_reject_rate": 5})
        device = Device(name="Bitaxe", model="Bitaxe Max", ip="192.168.1.100", status=DeviceStatus.ONLINE)
        device.current_telemetry = {"accepted_shares": 100, "rejected_shares": 10, "stale_shares": 0}

        diagnostics = engine.analyze(device)

        assert any(d.category == "shares" and "Reject rate" in d.message for d in diagnostics)

    def test_instability(self):
        engine = DiagnosticsEngine(config={"max_reconnect_count": 2})
        device = Device(name="Bitaxe", model="Bitaxe Max", ip="192.168.1.100", status=DeviceStatus.ONLINE)
        device.metadata = {"reconnect_count": 5}

        diagnostics = engine.analyze(device)

        assert any(d.category == "instability" for d in diagnostics)


class TestDiagnosticsEndpoint:
    def test_diagnostics_endpoint_not_found(self, client):
        flask_client, _ = client
        response = flask_client.get("/api/devices/does-not-exist/diagnostics")
        assert response.status_code == 404

    def test_diagnostics_endpoint_returns_list(self, client):
        flask_client, registry = client
        device = Device(name="Diag-Device", model="Bitaxe", ip="192.168.1.100", status=DeviceStatus.ONLINE)
        device.current_telemetry = {"temperature": 95}
        registry.add_device(device)

        response = flask_client.get(f"/api/devices/{device.id}/diagnostics")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert isinstance(data["diagnostics"], list)
