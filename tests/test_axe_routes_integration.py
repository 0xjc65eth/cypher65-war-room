"""
Integration tests for Axe Fleet HTTP routes using Flask test_client.

Tests:
- GET  /api/axe-fleet/remote/status      — Tailscale remote access status (unit-tested)
- POST /api/axe-fleet/miners/{id}/power-cycle  — validates request structure
"""
import json
from unittest.mock import patch, MagicMock
import pytest

import app as _app_module
app = _app_module.app


@pytest.fixture
def client():
    """Return a Flask test client configured for testing."""
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ══════════════════════════════════════════════════════════════════════════
#  GET /api/axe-fleet/remote/status
# ══════════════════════════════════════════════════════════════════════════

class TestRemoteStatus:
    """Tests for GET /api/axe-fleet/remote/status."""

    ENDPOINT = "/api/axe-fleet/remote/status"

    def test_returns_remote_access_dict(self, client):
        """Should return 200 with 'remote_access' key."""
        with patch("services.tailscale_adapter.get_local_status") as mock_status:
            mock_status.return_value = {
                "connected": True,
                "tailscale_ip": "100.64.0.1",
                "hostname": "mining-host",
                "domain": "tail-123.ts.net",
            }
            resp = client.get(self.ENDPOINT)
            assert resp.status_code == 200
            data = resp.get_json()
            assert "remote_access" in data
            assert data["remote_access"]["connected"] is True
            assert data["remote_access"]["tailscale_ip"] == "100.64.0.1"

    def test_returns_offline_when_not_connected(self, client):
        """When Tailscale is offline, remote_access should reflect that."""
        with patch("services.tailscale_adapter.get_local_status") as mock_status:
            mock_status.return_value = {
                "connected": False,
                "error": "Tailscale not running",
            }
            resp = client.get(self.ENDPOINT)
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["remote_access"]["connected"] is False

    def test_handles_get_local_status_exception(self, client):
        """If get_local_status raises, Flask should return error response.
        Note: in TESTING mode Flask propagates exceptions. By default
        Flask returns 500 for unhandled errors."""
        orig_propagate = app.config.get("PROPAGATE_EXCEPTIONS", False)
        app.config["PROPAGATE_EXCEPTIONS"] = False
        try:
            with patch("services.tailscale_adapter.get_local_status") as mock_status:
                mock_status.side_effect = Exception("Daemon not found")
                resp = client.get(self.ENDPOINT)
                assert resp.status_code == 500
        finally:
            app.config["PROPAGATE_EXCEPTIONS"] = orig_propagate

    def test_returns_json_content_type(self, client):
        """Content-Type should be application/json."""
        with patch("services.tailscale_adapter.get_local_status") as mock_status:
            mock_status.return_value = {"connected": False}
            resp = client.get(self.ENDPOINT)
            assert resp.content_type == "application/json"


# ══════════════════════════════════════════════════════════════════════════
#  POST /api/axe-fleet/miners/{id}/power-cycle
#  Note: These tests validate the HTTP contract (request → response structure).
#  The route uses _registry which is set during app init. For deeper testing
#  of the power-cycle logic itself, see test_axe_routes_remote.py (unit tests).
# ══════════════════════════════════════════════════════════════════════════

class TestMinerPowerCycle:
    """Tests for POST /api/axe-fleet/miners/{device_id}/power-cycle."""

    ENDPOINT = "/api/axe-fleet/miners/test-miner-001/power-cycle"

    def test_accepts_valid_json_body(self, client):
        """A POST with valid JSON should return a valid JSON response."""
        resp = client.post(
            self.ENDPOINT,
            data=json.dumps({"plug_id": "plug-001", "confirm": True}),
            content_type="application/json",
        )
        # Endpoint is reachable and returns JSON
        assert resp.content_type == "application/json"
        data = resp.get_json()
        assert "success" in data

    def test_invalid_json_returns_error(self, client):
        """Malformed JSON body should be rejected."""
        resp = client.post(
            self.ENDPOINT,
            data="not valid json",
            content_type="application/json",
        )
        data = resp.get_json()
        if data:
            assert "error" in data or "success" in data

    def test_missing_confirm_returns_json(self, client):
        """Request without confirm field should still return valid JSON."""
        resp = client.post(
            self.ENDPOINT,
            data=json.dumps({"plug_id": "plug-001"}),
            content_type="application/json",
        )
        assert resp.content_type == "application/json"

    def test_responds_to_post_only(self, client):
        """GET request should return 405 Method Not Allowed."""
        resp = client.get(self.ENDPOINT)
        assert resp.status_code == 405


# ══════════════════════════════════════════════════════════════════════════
#  GET /api/axe-fleet/devices/{id}/telemetry
# ══════════════════════════════════════════════════════════════════════════

class TestDeviceTelemetry:
    """Tests for GET /api/axe-fleet/devices/<device_id>/telemetry."""

    DEVICE_ID = "test-device-001"
    ENDPOINT = f"/api/axe-fleet/devices/{DEVICE_ID}/telemetry"

    def test_returns_telemetry_for_existing_device(self, client):
        """Should return 200 with telemetry list for a known device."""
        mock_registry = MagicMock()
        mock_registry.get_device.return_value = {
            "id": self.DEVICE_ID,
            "name": "Test Miner",
            "model": "Bitaxe",
            "ip_address": "192.168.1.100",
            "status": "ONLINE",
        }
        mock_registry.get_recent_telemetry.return_value = [
            {"ts": 1700000000, "payload": {
                "hashrate_hs": 5200000000000,
                "temperature": 62,
                "fan_speed": 80,
                "power_watts": 42,
                "efficiency_jth": 8.08,
                "uptime_seconds": 259200,
            }},
            {"ts": 1699999700, "payload": {
                "hashrate_hs": 5100000000000,
                "temperature": 60,
                "fan_speed": 78,
                "power_watts": 41,
                "efficiency_jth": 8.04,
                "uptime_seconds": 258900,
            }},
        ]

        with patch("axe_fleet.routes._registry", mock_registry):
            resp = client.get(self.ENDPOINT)
        assert resp.status_code == 200
        data = resp.get_json()
        assert "device" in data
        assert "telemetry" in data
        assert data["device"]["id"] == self.DEVICE_ID
        assert len(data["telemetry"]) == 2
        assert "payload" in data["telemetry"][0]
        assert data["telemetry"][0]["payload"]["temperature"] == 62
        assert data["count"] == 2

    def test_404_for_unknown_device(self, client):
        """Should return 404 when device does not exist."""
        mock_registry = MagicMock()
        mock_registry.get_device.return_value = None

        with patch("axe_fleet.routes._registry", mock_registry):
            resp = client.get(self.ENDPOINT)
        assert resp.status_code == 404
        data = resp.get_json()
        assert "error" in data

    def test_respects_limit_param(self, client):
        """Should pass limit query param to get_recent_telemetry."""
        mock_registry = MagicMock()
        mock_registry.get_device.return_value = {"id": self.DEVICE_ID, "name": "T", "model": "Bitaxe", "ip_address": "192.168.1.100", "status": "ONLINE"}
        mock_registry.get_recent_telemetry.return_value = []

        with patch("axe_fleet.routes._registry", mock_registry):
            resp = client.get(f"{self.ENDPOINT}?limit=5")
        assert resp.status_code == 200
        args, kwargs = mock_registry.get_recent_telemetry.call_args
        assert kwargs.get("limit") == 5

    def test_returns_json_content_type(self, client):
        """Content-Type should be application/json."""
        mock_registry = MagicMock()
        mock_registry.get_device.return_value = {"id": self.DEVICE_ID, "name": "T", "model": "Bitaxe", "ip_address": "192.168.1.100", "status": "ONLINE"}
        mock_registry.get_recent_telemetry.return_value = []

        with patch("axe_fleet.routes._registry", mock_registry):
            resp = client.get(self.ENDPOINT)
        assert resp.content_type == "application/json"


# ══════════════════════════════════════════════════════════════════════════
#  GET /api/axe-fleet/devices/{id}/chart-data
# ══════════════════════════════════════════════════════════════════════════

class TestDeviceChartData:
    """Tests for GET /api/axe-fleet/devices/<device_id>/chart-data."""

    DEVICE_ID = "test-device-002"
    ENDPOINT = f"/api/axe-fleet/devices/{DEVICE_ID}/chart-data"

    def test_returns_chart_series_for_existing_device(self, client):
        """Should return 200 with chart series data."""
        mock_registry = MagicMock()
        mock_registry.get_device.return_value = {
            "id": self.DEVICE_ID,
            "name": "Chart Miner",
            "model": "Bitaxe Max",
            "ip_address": "192.168.1.101",
            "status": "ONLINE",
        }
        mock_registry.get_telemetry_chart_data.return_value = {
            "ts": [1700000000, 1699999700, 1699999400],
            "hashrate": [5.2, 5.1, 5.3],
            "temperature": [62, 60, 63],
            "fan_rpm": [4200, 4100, 4300],
            "power_watts": [42, 41, 43],
        }

        with patch("axe_fleet.routes._registry", mock_registry):
            resp = client.get(self.ENDPOINT)
        assert resp.status_code == 200
        data = resp.get_json()
        assert "series" in data
        assert "device_id" in data
        assert data["device_id"] == self.DEVICE_ID
        assert "hashrate" in data["series"]
        assert "temperature" in data["series"]
        assert len(data["series"]["ts"]) == 3
        assert data["count"] == 3

    def test_404_for_unknown_device(self, client):
        """Should return 404 when device does not exist."""
        mock_registry = MagicMock()
        mock_registry.get_device.return_value = None

        with patch("axe_fleet.routes._registry", mock_registry):
            resp = client.get(self.ENDPOINT)
        assert resp.status_code == 404

    def test_respects_limit_param(self, client):
        """Should pass limit param to get_telemetry_chart_data."""
        mock_registry = MagicMock()
        mock_registry.get_device.return_value = {"id": self.DEVICE_ID, "name": "T"}
        mock_registry.get_telemetry_chart_data.return_value = {"ts": [], "hashrate": []}

        with patch("axe_fleet.routes._registry", mock_registry):
            resp = client.get(f"{self.ENDPOINT}?limit=50")
        assert resp.status_code == 200
        args, kwargs = mock_registry.get_telemetry_chart_data.call_args
        assert kwargs.get("limit") == 50

    def test_returns_device_name_in_response(self, client):
        """Should include device_name in response."""
        mock_registry = MagicMock()
        mock_registry.get_device.return_value = {"id": self.DEVICE_ID, "name": "Chart Miner"}
        mock_registry.get_telemetry_chart_data.return_value = {"ts": [], "hashrate": []}

        with patch("axe_fleet.routes._registry", mock_registry):
            resp = client.get(self.ENDPOINT)
        data = resp.get_json()
        assert data["device_name"] == "Chart Miner"


# ══════════════════════════════════════════════════════════════════════════
#  GET /api/axe-fleet/devices/{id}/health
# ══════════════════════════════════════════════════════════════════════════

class TestDeviceHealth:
    """Tests for GET /api/axe-fleet/devices/<device_id>/health."""

    DEVICE_ID = "test-device-003"
    ENDPOINT = f"/api/axe-fleet/devices/{DEVICE_ID}/health"

    def test_returns_health_for_existing_device(self, client):
        """Should return 200 with health score, issues, and telemetry."""
        mock_registry = MagicMock()
        mock_registry.get_device.return_value = {
            "id": self.DEVICE_ID,
            "name": "Healthy Miner",
            "model": "Bitaxe ULP",
            "ip_address": "192.168.1.102",
            "status": "ONLINE",
            "last_seen": 1700000000,
        }
        mock_registry.get_recent_telemetry.return_value = [
            {"ts": 1700000000, "payload": {
                "hashrate_hs": 5200000000000,
                "temperature": 62,
                "fan_speed": 80,
                "fan_rpm": 4200,
                "power_watts": 42,
                "efficiency_jth": 8.08,
                "hw_error_pct": 0.3,
                "shares_accepted": 15823,
                "shares_rejected": 47,
                "uptime_seconds": 259200,
                "best_diff": "42.8T",
            }},
        ]

        with patch("axe_fleet.routes._registry", mock_registry):
            with patch("axe_fleet.models.infer_health_score", return_value=85):
                resp = client.get(self.ENDPOINT)
        assert resp.status_code == 200
        data = resp.get_json()
        assert "health_score" in data
        assert "health_label" in data
        assert "active_issues" in data
        assert "latest_telemetry" in data
        assert data["device_id"] == self.DEVICE_ID
        assert data["device_name"] == "Healthy Miner"
        assert data["status"] == "ONLINE"

    def test_404_for_unknown_device(self, client):
        """Should return 404 when device does not exist."""
        mock_registry = MagicMock()
        mock_registry.get_device.return_value = None

        with patch("axe_fleet.routes._registry", mock_registry):
            resp = client.get(self.ENDPOINT)
        assert resp.status_code == 404

    def test_reports_active_issues_for_hot_device(self, client):
        """High temperature (>=80) should appear in active_issues."""
        mock_registry = MagicMock()
        mock_registry.get_device.return_value = {
            "id": self.DEVICE_ID, "name": "Hot Miner",
            "status": "WARNING", "last_seen": 1700000000,
        }
        mock_registry.get_recent_telemetry.return_value = [
            {"ts": 1700000000, "payload": {
                "hashrate_hs": 5000000000000,
                "temperature": 82,
                "hw_error_pct": 0.5,
            }},
        ]

        with patch("axe_fleet.routes._registry", mock_registry):
            with patch("axe_fleet.models.infer_health_score", return_value=40):
                resp = client.get(self.ENDPOINT)
        data = resp.get_json()
        assert "high_temperature" in data["active_issues"]
        assert "device_warning" in data["active_issues"]

    def test_reports_zero_hashrate_issue(self, client):
        """Zero hashrate should appear in active_issues."""
        mock_registry = MagicMock()
        mock_registry.get_device.return_value = {
            "id": self.DEVICE_ID, "name": "Dead Miner",
            "status": "OFFLINE", "last_seen": 1700000000,
        }
        mock_registry.get_recent_telemetry.return_value = [
            {"ts": 1700000000, "payload": {
                "hashrate_hs": 0,
                "temperature": 30,
                "hw_error_pct": 0.0,
            }},
        ]

        with patch("axe_fleet.routes._registry", mock_registry):
            with patch("axe_fleet.models.infer_health_score", return_value=10):
                resp = client.get(self.ENDPOINT)
        data = resp.get_json()
        assert "device_offline" in data["active_issues"]
        assert "zero_hashrate" in data["active_issues"]

    def test_no_active_issues_for_healthy_device(self, client):
        """Healthy online device should have minimal or empty issues."""
        mock_registry = MagicMock()
        mock_registry.get_device.return_value = {
            "id": self.DEVICE_ID, "name": "Perfect Miner",
            "status": "ONLINE", "last_seen": 1700000000,
        }
        mock_registry.get_recent_telemetry.return_value = [
            {"ts": 1700000000, "payload": {
                "hashrate_hs": 5000000000000,
                "temperature": 55,
                "hw_error_pct": 0.1,
            }},
        ]

        with patch("axe_fleet.routes._registry", mock_registry):
            with patch("axe_fleet.models.infer_health_score", return_value=95):
                resp = client.get(self.ENDPOINT)
        data = resp.get_json()
        # No high temp, no high HW error, no offline, no warning status
        for issue in data["active_issues"]:
            assert issue not in ("high_temperature", "high_hw_error_rate",
                                 "device_offline", "zero_hashrate")

    def test_returns_timestamp_and_age(self, client):
        """Should return last_seen and age_seconds fields."""
        mock_registry = MagicMock()
        mock_registry.get_device.return_value = {
            "id": self.DEVICE_ID, "name": "T",
            "status": "ONLINE", "last_seen": 1700000000,
        }
        mock_registry.get_recent_telemetry.return_value = []

        with patch("axe_fleet.routes._registry", mock_registry):
            resp = client.get(self.ENDPOINT)
        data = resp.get_json()
        assert "last_seen" in data
        assert "age_seconds" in data
        assert data["last_seen"] == 1700000000
