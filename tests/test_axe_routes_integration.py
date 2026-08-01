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
#  GET /api/axe-fleet/remote/onboarding
#  FLEET audit G3: payload must carry the step checklist PLUS an honest
#  scope (what the user can execute remotely) and Tailscale limitations,
#  so the REMOTE ACCESS tutorial sets expectations before setup.
# ══════════════════════════════════════════════════════════════════════════

class TestRemoteOnboarding:
    """Tests for GET /api/axe-fleet/remote/onboarding — G3 scope/limitations."""

    ENDPOINT = "/api/axe-fleet/remote/onboarding"

    @pytest.fixture(autouse=True)
    def _mock_tailscale(self, monkeypatch):
        """Deterministic tailscale status — no real daemon access."""
        monkeypatch.setattr(
            "services.tailscale_adapter.get_local_status",
            lambda: {
                "tailscale_installed": True,
                "connected": True,
                "ip": "100.64.0.1",
                "hostname": "mining-host",
            },
        )
        monkeypatch.setattr(
            "services.tailscale_adapter.diagnose_connection",
            lambda *a, **k: {"reachable": True},
        )
        monkeypatch.setattr(
            "axe_fleet.routes._get_tuya_credentials", lambda: {"access_id": ""}
        )

    def test_payload_includes_scope_and_limitations(self, client):
        """G3: the onboarding payload must explain what the user can do
        remotely and Tailscale's constraints — not just the steps."""
        resp = client.get(self.ENDPOINT)
        assert resp.status_code == 200
        data = resp.get_json()
        assert "scope" in data and isinstance(data["scope"], list)
        assert "limitations" in data and isinstance(data["limitations"], list)
        # Scope is actionable: monitoring, commands, settings, full dashboard
        # (pt-BR payload — assert the Portuguese markers).
        joined_scope = " ".join(data["scope"]).lower()
        assert "monitorar" in joined_scope
        assert "comandos" in joined_scope
        # Limitations are honest: tailnet-only, host online, auth required
        joined_lim = " ".join(data["limitations"]).lower()
        assert "tailnet" in joined_lim
        assert "host" in joined_lim

    def test_steps_still_present(self, client):
        """Adding G3 fields must not regress the existing checklist payload."""
        resp = client.get(self.ENDPOINT)
        data = resp.get_json()
        assert "steps" in data and len(data["steps"]) >= 4
        assert all("id" in s and "label" in s and "instructions" in s for s in data["steps"])
        assert "progress" in data


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


# ══════════════════════════════════════════════════════════════════════════
#  GET /api/axe-fleet/health
#  P1.1 — fleet_stats schema alignment: online/warning/offline counts,
#  aggregates (avg health/temp, total power, efficiency, best diff) and
#  normalized per-device cards consumed by renderAxeFleet/_renderAxeCard.
# ══════════════════════════════════════════════════════════════════════════

class TestFleetHealth:
    """Tests for GET /api/axe-fleet/health — fleet_stats schema (P1.1)."""

    ENDPOINT = "/api/axe-fleet/health"

    @pytest.fixture(autouse=True)
    def _no_real_probe(self, monkeypatch):
        """Never hit the network from these tests — the latency probe would
        otherwise do real socket connects to private IPs (slow + cache
        pollution across tests)."""
        monkeypatch.setattr("axe_fleet.routes._probe_miner_latency_ms", lambda ip="", timeout=0.75: None)

    def _device(self, device_id, name, status, last_seen=1700000000):
        return {
            "id": device_id,
            "name": name,
            "model": "Bitaxe ULP",
            "ip_address": "192.168.1.100",
            "last_seen": last_seen,
            "status": status,
            "capabilities": {"telemetry": True, "restart": True},
        }

    def _telemetry(self, hashrate_hs, temperature=None, power_watts=None,
                   best_diff="", uptime_seconds=0, efficiency_jth=None,
                   hw_error_pct=0.0, shares_accepted=0, shares_rejected=0,
                   frequency_mhz=None, voltage_mv=None, ts=1700000000):
        return [{"ts": ts, "payload": {
            "hashrate_hs": hashrate_hs,
            "temperature": temperature,
            "fan_speed": 80,
            "fan_rpm": 4200,
            "power_watts": power_watts,
            "frequency_mhz": frequency_mhz,
            "voltage_mv": voltage_mv,
            "best_diff": best_diff,
            "uptime_seconds": uptime_seconds,
            "efficiency_jth": efficiency_jth,
            "shares_accepted": shares_accepted,
            "shares_rejected": shares_rejected,
            "hw_error_pct": hw_error_pct,
        }}]

    def test_returns_fleet_stats_with_status_counts(self, client):
        """fleet_stats should expose online/warning/offline counts and aggregates."""
        mock_registry = MagicMock()
        mock_registry.list_devices.return_value = [
            self._device("d1", "Online A", "ONLINE"),
            self._device("d2", "Hashing B", "HASHING"),
            self._device("d3", "Warn C", "WARNING"),
            self._device("d4", "Off D", "OFFLINE"),
        ]
        mock_registry.get_recent_telemetry.side_effect = [
            self._telemetry(5200000000000, 62, 42, "42.8T", 259200, 8.08, 0.3, 15823, 47, 525, 1200),
            self._telemetry(2100000000000, 58, 18, "12.5T", 604800, 8.57, 0.2, 45231, 89, 450, 1100),
            self._telemetry(3800000000000, 82, 38, "28.3T", 43200, 10.0, 3.5, 5872, 215, 500, 1250),
            self._telemetry(0, None, 0, "", 0, None, 0.0),
        ]

        with patch("axe_fleet.routes._registry", mock_registry):
            with patch("axe_fleet.models.infer_health_score", return_value=70):
                resp = client.get(self.ENDPOINT)
        assert resp.status_code == 200
        data = resp.get_json()

        fs = data["fleet_stats"]
        # P1.1: online/warning/offline present and counted correctly
        assert fs["total_devices"] == 4
        assert fs["online"] == 2     # ONLINE + HASHING
        assert fs["warning"] == 1
        assert fs["offline"] == 1
        # Aggregates
        assert fs["total_hashrate_hs"] == 5200000000000 + 2100000000000 + 3800000000000
        assert fs["total_hashrate_str"] == "11.10 TH/s"
        assert fs["total_power_w"] == 42 + 18 + 38
        assert fs["avg_temperature_c"] == 67.3
        assert fs["avg_health_score"] == 70
        assert fs["best_diff"] == "42.8T"
        assert fs["efficiency_jth"] == 8.83

    def test_zeroed_fleet_stats_when_no_devices(self, client):
        """Empty fleet should return zeroed stats, not crash."""
        mock_registry = MagicMock()
        mock_registry.list_devices.return_value = []

        with patch("axe_fleet.routes._registry", mock_registry):
            resp = client.get(self.ENDPOINT)
        assert resp.status_code == 200
        fs = resp.get_json()["fleet_stats"]
        assert fs["total_devices"] == 0
        assert fs["online"] == 0
        assert fs["warning"] == 0
        assert fs["offline"] == 0
        assert fs["avg_temperature_c"] is None
        assert fs["avg_health_score"] == 0
        assert fs["total_hashrate_hs"] == 0

    def test_device_health_normalized_for_cards(self, client):
        """device_health items should carry the fields _renderAxeCard reads."""
        mock_registry = MagicMock()
        mock_registry.list_devices.return_value = [
            self._device("d1", "Online A", "ONLINE"),
            self._device("d2", "Warn C", "WARNING"),
        ]
        mock_registry.get_recent_telemetry.side_effect = [
            self._telemetry(5200000000000, 62, 42, "42.8T", 259200, 8.08, 0.3, 15823, 47, 525, 1200),
            self._telemetry(3800000000000, 82, 38, "28.3T", 43200, 10.0, 3.5, 5872, 215, 500, 1250),
        ]

        with patch("axe_fleet.routes._registry", mock_registry):
            with patch("axe_fleet.models.infer_health_score", return_value=65):
                resp = client.get(self.ENDPOINT)
        data = resp.get_json()

        assert len(data["device_health"]) == 2
        d = data["device_health"][0]
        # Card fields: status, health_score, capabilities, telemetry.*
        assert d["id"] == "d1"
        assert d["name"] == "Online A"
        assert d["status"] == "ONLINE"
        assert d["health_score"] == 65
        assert "restart" in d["capabilities"]
        tel = d["telemetry"]
        assert tel["hashrate_str"] == "5.20 TH/s"
        assert tel["temperature"] == 62
        assert tel["best_diff"] == "42.8T"
        assert tel["uptime_str"] == "3d"
        assert tel["frequency_mhz"] == 525
        assert tel["voltage_mv"] == 1200
        assert tel["shares_accepted"] == 15823
        assert tel["shares_rejected"] == 47
        assert tel["hw_error_pct"] == 0.3
        assert tel["power_watts"] == 42
        assert tel["efficiency_jth"] == 8.08
        assert "age_seconds" in tel

    def test_groups_breakdown(self, client):
        """groups should bucket device ids by online/warning/offline."""
        mock_registry = MagicMock()
        mock_registry.list_devices.return_value = [
            self._device("d1", "Online A", "ONLINE"),
            self._device("d2", "Hashing B", "HASHING"),
            self._device("d3", "Warn C", "WARNING"),
            self._device("d4", "Off D", "OFFLINE"),
        ]
        mock_registry.get_recent_telemetry.side_effect = [
            self._telemetry(1000000000000, 55, 10, "5T", 100, 10.0),
            self._telemetry(2000000000000, 60, 20, "9T", 200, 10.0),
            self._telemetry(3000000000000, 82, 30, "7T", 300, 10.0),
            self._telemetry(0, None, 0),
        ]

        with patch("axe_fleet.routes._registry", mock_registry):
            with patch("axe_fleet.models.infer_health_score", return_value=50):
                resp = client.get(self.ENDPOINT)
        data = resp.get_json()
        assert data["groups"] == {
            "online": ["d1", "d2"],
            "warning": ["d3"],
            "offline": ["d4"],
        }

    def test_handles_registry_uninitialized(self, client):
        """When registry is None, return 500 with clear error."""
        with patch("axe_fleet.routes._registry", None):
            resp = client.get(self.ENDPOINT)
        assert resp.status_code == 500
        assert "error" in resp.get_json()

    # ── Fase 5 serializer passthrough ────────────────────────────────────
    def test_device_health_exposes_fase5_fields(self, client):
        """device_health must carry chip/vr temps, hashrate windows and
        device metadata (manufacturer/firmware/version) the cards render."""
        mock_registry = MagicMock()
        mock_registry.list_devices.return_value = [
            {
                **self._device("d1", "Garage Bitaxe", "ONLINE"),
                "manufacturer": "Bitaxe",
                "firmware": "AxeOS",
                "firmware_version": "2.6.0",
                "hostname": "bitaxe-garage",
            }
        ]
        tel = self._telemetry(5200000000000, 62, 42, "42.8T", 259200, 8.08, 0.3, 15823, 47, 525, 1200)[0]["payload"]
        tel.update({
            "chip_temp": 70,
            "vr_temp": 67,
            "temp_asic": 70,
            "temp_vreg": 67,
            "hashrate_1m": 5408000000000,
            "hashrate_10m": 5300000000000,
            "hashrate_1h": 5200000000000,
            "shares_stale": 3,
            "stratum_status": "connected",
        })
        mock_registry.get_recent_telemetry.return_value = [{"ts": 1700000000, "payload": tel}]

        with patch("axe_fleet.routes._registry", mock_registry):
            with patch("axe_fleet.models.infer_health_score", return_value=80):
                resp = client.get(self.ENDPOINT)
        assert resp.status_code == 200
        d = resp.get_json()["device_health"][0]
        assert d["manufacturer"] == "Bitaxe"
        assert d["firmware"] == "AxeOS"
        assert d["firmware_version"] == "2.6.0"
        assert d["hostname"] == "bitaxe-garage"
        t = d["telemetry"]
        assert t["chip_temp"] == 70
        assert t["vr_temp"] == 67
        assert t["temp_asic"] == 70
        assert t["temp_vreg"] == 67
        assert t["hashrate_1m"] == 5408000000000
        assert t["hashrate_1h"] == 5200000000000
        assert t["shares_stale"] == 3
        assert t["stratum_status"] == "connected"

    def test_broken_telemetry_payload_treated_as_empty(self, client):
        """Hardening: legacy broken payloads (bare {"device_id": ...} stubs
        written before the poll fix) must be ignored — never zero the fleet."""
        mock_registry = MagicMock()
        mock_registry.list_devices.return_value = [self._device("d1", "Online A", "ONLINE")]
        # The polluted legacy row: no hashrate_hs key at all.
        mock_registry.get_recent_telemetry.return_value = [{"ts": 1700000000, "payload": {"device_id": "d1"}}]

        with patch("axe_fleet.routes._registry", mock_registry):
            with patch("axe_fleet.models.infer_health_score", return_value=45):
                resp = client.get(self.ENDPOINT)
        assert resp.status_code == 200
        d = resp.get_json()["device_health"][0]
        # Because the payload was rejected, telemetry is honest zeros/—,
        # not a crash and not a fabricated value.
        assert d["telemetry"]["hashrate_hs"] == 0
        assert d["telemetry"]["temperature"] is None
        assert d["telemetry"]["chip_temp"] is None


# ══════════════════════════════════════════════════════════════════════════
#  GET /api/axe-fleet/summary
#  Regression: online counter now delegates to device_status_is_online
#  (ONLINE/WARNING/HASHING) and WARNING is kept in its own bucket — a
#  degraded-but-reachable miner must never be counted as offline.
# ══════════════════════════════════════════════════════════════════════════

class TestFleetSummary:
    """Tests for GET /api/axe-fleet/summary — online/warning/offline counts
    + per-device latency_ms/advice layer (payload parity with fleet_health)."""

    ENDPOINT = "/api/axe-fleet/summary"

    @pytest.fixture(autouse=True)
    def _no_real_probe(self, monkeypatch):
        """Never hit the network from these tests — the latency probe would
        otherwise do real socket connects to private IPs (slow + cache
        pollution across tests). Mirrors TestFleetHealth."""
        monkeypatch.setattr("axe_fleet.routes._probe_miner_latency_ms", lambda ip="", timeout=0.75: None)

    def _device(self, device_id, status):
        return {
            "id": device_id,
            "name": f"Dev {device_id}",
            "model": "Bitaxe ULP",
            "ip_address": "192.168.1.100",
            "last_seen": 1700000000,
            "status": status,
        }

    def test_warning_not_counted_as_offline(self, client):
        """WARNING device must land in its own bucket, never offline.
        Regression: old code did offline = total - online, silently counting
        degraded-but-reachable WARNING miners as offline."""
        mock_registry = MagicMock()
        mock_registry.list_devices.return_value = [
            self._device("d1", "ONLINE"),
            self._device("d2", "WARNING"),
            self._device("d3", "OFFLINE"),
        ]
        mock_registry.get_recent_telemetry.return_value = []

        with patch("axe_fleet.routes._registry", mock_registry):
            resp = client.get(self.ENDPOINT)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total_devices"] == 3
        assert data["online"] == 1
        assert data["warning"] == 1
        assert data["offline"] == 1

    def test_hashing_counts_as_online(self, client):
        """HASHING (STATUS_HASHING) is an actively-mining device → online."""
        mock_registry = MagicMock()
        mock_registry.list_devices.return_value = [
            self._device("d1", "HASHING"),
            self._device("d2", "ONLINE"),
            self._device("d3", "WARNING"),
        ]
        mock_registry.get_recent_telemetry.return_value = []

        with patch("axe_fleet.routes._registry", mock_registry):
            resp = client.get(self.ENDPOINT)
        data = resp.get_json()
        assert data["online"] == 2  # HASHING + ONLINE
        assert data["warning"] == 1
        assert data["offline"] == 0

    def test_empty_fleet_zeroed(self, client):
        """Empty fleet should return zeroed counters."""
        mock_registry = MagicMock()
        mock_registry.list_devices.return_value = []

        with patch("axe_fleet.routes._registry", mock_registry):
            resp = client.get(self.ENDPOINT)
        data = resp.get_json()
        assert data["total_devices"] == 0
        assert data["online"] == 0
        assert data["warning"] == 0
        assert data["offline"] == 0

    def test_registry_uninitialized_returns_500(self, client):
        """When registry is None, return 500 with clear error."""
        with patch("axe_fleet.routes._registry", None):
            resp = client.get(self.ENDPOINT)
        assert resp.status_code == 500
        assert "error" in resp.get_json()

    def test_device_entries_carry_latency_and_advice(self, client):
        """Payload parity: every device entry exposes latency_ms + advice
        exactly like fleet_health, so consumers can swap endpoints without
        schema drift. Online device gets a probed latency; offline device
        must NOT be probed and gets the offline advice."""
        mock_registry = MagicMock()
        mock_registry.list_devices.return_value = [
            self._device("d1", "ONLINE"),
            self._device("d2", "OFFLINE"),
        ]
        mock_registry.get_recent_telemetry.side_effect = [
            [{"ts": 1700000000, "payload": {
                "hashrate_hs": 5200000000000, "temperature": 62,
                "hw_error_pct": 0.3, "shares_accepted": 1000, "shares_stale": 0}}],
            [{"ts": 1700000000, "payload": {
                "hashrate_hs": 0, "temperature": None}}],
        ]

        with patch("axe_fleet.routes._registry", mock_registry):
            with patch("axe_fleet.routes._probe_miner_latency_ms",
                       side_effect=lambda ip="", timeout=0.75: 23 if ip else None):
                resp = client.get(self.ENDPOINT)
        assert resp.status_code == 200
        devices = resp.get_json()["devices"]
        online = next(d for d in devices if d["status"] == "ONLINE")
        offline = next(d for d in devices if d["status"] == "OFFLINE")
        assert online["latency_ms"] == 23
        assert offline["latency_ms"] is None
        assert offline["advice"] == ["device offline — checar energia/rede"]
        # Healthy online miner must not produce advice noise (same rule as
        # fleet_health) — its payload is healthy: temp 62, hw 0.3%, no stale.
        assert online["advice"] == []
        assert all("latency_ms" in d and "advice" in d for d in devices)
        # Fase 5 parity: _telemetry carries the same enriched keys the
        # fleet_health card renderer reads (chip/vr temps + pool passthrough).
        assert online["_telemetry"]["hashrate_str"] == "5.20 TH/s"
        assert online["_telemetry"]["uptime_str"] == "—"
        assert offline["_telemetry"]["stratum_status"] == ""


# ══════════════════════════════════════════════════════════════════════════
#  POST /api/axe-fleet/test-devices
#  Regression: the SEED TEST button route must emit the Fase 5 fields
#  (chip_temp, vr_temp, hashrate_1h, ...) exactly like the boot auto-seed,
#  or cards show NOT AVAILABLE after seeding. Gated by DEBUG_MOCK=1.
# ══════════════════════════════════════════════════════════════════════════

class TestSeedTestDevices:
    """Tests for POST /api/axe-fleet/test-devices — Fase 5 emission."""

    ENDPOINT = "/api/axe-fleet/test-devices"

    def test_seed_emits_fase5_fields(self, client, monkeypatch):
        """Seeded telemetry must carry chip/VR temps + hashrate windows so
        cards render real values instead of NOT AVAILABLE."""
        monkeypatch.setenv("DEBUG_MOCK", "1")
        mock_registry = MagicMock()
        mock_registry.list_devices.return_value = []  # empty fleet → seed allowed
        saved = []

        def _capture(device_id, tel, **kwargs):
            saved.append(tel)

        mock_registry.save_telemetry.side_effect = _capture

        with patch("axe_fleet.routes._registry", mock_registry):
            resp = client.post(self.ENDPOINT)
        assert resp.status_code == 201
        # 4 mock devices × 10 historical points
        assert len(saved) == 40
        # Online device telemetry carries the Fase 5 fields
        online_tel = next(t for t in saved if t.get("hashrate_hs", 0) > 0)
        assert online_tel["chip_temp"] is not None
        assert online_tel["vr_temp"] is not None
        assert online_tel["temp_asic"] is not None
        assert online_tel["temp_vreg"] is not None
        assert online_tel["hashrate_1m"] is not None
        assert online_tel["hashrate_10m"] is not None
        assert online_tel["hashrate_1h"] is not None
        # Offline device honestly reports None (never a fabricated number)
        offline_tel = next(t for t in saved if t.get("hashrate_hs", 0) == 0)
        assert offline_tel["chip_temp"] is None
        assert offline_tel["hashrate_1h"] is None

    def test_seed_disabled_without_debug_mock(self, client, monkeypatch):
        """Without DEBUG_MOCK=1 the endpoint must be locked down (403)."""
        monkeypatch.delenv("DEBUG_MOCK", raising=False)
        mock_registry = MagicMock()
        with patch("axe_fleet.routes._registry", mock_registry):
            resp = client.post(self.ENDPOINT)
        assert resp.status_code == 403
        assert "disabled" in resp.get_json()["error"]


# ══════════════════════════════════════════════════════════════════════════
#  FLEET audit — gap 1/2/3: per-device latency_ms (PING), advice chips and
#  pool_url/pool_user passthrough in GET /api/axe-fleet/health.
# ══════════════════════════════════════════════════════════════════════════

class TestFleetHealthTelemetryGaps:
    """Tests for the fleet_health per-device telemetry additions."""

    ENDPOINT = "/api/axe-fleet/health"

    def _device(self, device_id, name, status, ip="192.168.1.100"):
        return {
            "id": device_id,
            "name": name,
            "model": "Bitaxe ULP",
            "ip_address": ip,
            "last_seen": 1700000000,
            "status": status,
            "capabilities": {"telemetry": True, "restart": True},
        }

    def _telemetry(self, hashrate_hs=5200000000000, temperature=62,
                   chip_temp=None, hw_error_pct=0.3, shares_accepted=1000,
                   shares_stale=0, wifi_rssi=-60, pool_url="",
                   stratum_status="connected"):
        return [{"ts": 1700000000, "payload": {
            "hashrate_hs": hashrate_hs,
            "temperature": temperature,
            "chip_temp": chip_temp,
            "hw_error_pct": hw_error_pct,
            "shares_accepted": shares_accepted,
            "shares_stale": shares_stale,
            "wifi_rssi": wifi_rssi,
            "pool_url": pool_url,
            "stratum_status": stratum_status,
        }}]

    def test_latency_ms_probed_for_online_device(self, client):
        """Online device gets a real latency_ms from the probe."""
        mock_registry = MagicMock()
        mock_registry.list_devices.return_value = [
            self._device("d1", "Garage Bitaxe", "ONLINE")
        ]
        mock_registry.get_recent_telemetry.return_value = self._telemetry()

        with patch("axe_fleet.routes._registry", mock_registry):
            with patch("axe_fleet.routes._probe_miner_latency_ms", return_value=23) as probe:
                resp = client.get(self.ENDPOINT)
        assert resp.status_code == 200
        d = resp.get_json()["device_health"][0]
        assert d["latency_ms"] == 23
        probe.assert_called_once()

    def test_latency_ms_none_for_offline_device(self, client):
        """Offline device must NOT be probed (endpoint never blocks on dead IPs)."""
        mock_registry = MagicMock()
        mock_registry.list_devices.return_value = [
            self._device("d1", "Basement S19", "OFFLINE", ip="192.168.1.200")
        ]
        mock_registry.get_recent_telemetry.return_value = self._telemetry(hashrate_hs=0)

        with patch("axe_fleet.routes._registry", mock_registry):
            with patch("axe_fleet.routes._probe_miner_latency_ms") as probe:
                resp = client.get(self.ENDPOINT)
        assert resp.status_code == 200
        d = resp.get_json()["device_health"][0]
        assert d["latency_ms"] is None
        probe.assert_not_called()

    def test_advice_rules_emit_actionable_chips(self, client):
        """A hot miner with HW errors + stale shares gets multiple advice chips."""
        mock_registry = MagicMock()
        mock_registry.list_devices.return_value = [
            self._device("d1", "Hot Lab", "WARNING")
        ]
        mock_registry.get_recent_telemetry.return_value = self._telemetry(
            hashrate_hs=3800000000000, temperature=82, chip_temp=90,
            hw_error_pct=5.5, shares_accepted=100, shares_stale=4,
            wifi_rssi=-80, stratum_status="connected")

        with patch("axe_fleet.routes._registry", mock_registry):
            with patch("axe_fleet.routes._probe_miner_latency_ms", return_value=180):
                resp = client.get(self.ENDPOINT)
        d = resp.get_json()["device_health"][0]
        joined = " ".join(d["advice"])
        assert "temp ≥80°C" in joined
        assert "chip ≥85°C" in joined
        assert "HW errors ≥5%" in joined
        assert "stale shares >1%" in joined
        assert "ping alto (>150ms)" in joined
        assert "Wi-Fi fraco" in joined

    def test_healthy_device_has_no_advice(self, client):
        """Healthy miner → empty advice list (no noise)."""
        mock_registry = MagicMock()
        mock_registry.list_devices.return_value = [
            self._device("d1", "Healthy", "ONLINE")
        ]
        mock_registry.get_recent_telemetry.return_value = self._telemetry()

        with patch("axe_fleet.routes._registry", mock_registry):
            with patch("axe_fleet.routes._probe_miner_latency_ms", return_value=20):
                resp = client.get(self.ENDPOINT)
        d = resp.get_json()["device_health"][0]
        assert d["advice"] == []

    def test_offline_advice_is_offline(self, client):
        """Offline device advice must be exactly the offline recommendation."""
        mock_registry = MagicMock()
        mock_registry.list_devices.return_value = [
            self._device("d1", "Dead", "OFFLINE", ip="192.168.1.200")
        ]
        mock_registry.get_recent_telemetry.return_value = self._telemetry(hashrate_hs=0)

        with patch("axe_fleet.routes._registry", mock_registry):
            resp = client.get(self.ENDPOINT)
        d = resp.get_json()["device_health"][0]
        assert d["advice"] == ["device offline — checar energia/rede"]

    def test_pool_url_and_user_serialized(self, client):
        """pool_url/pool_user must pass through so the card shows the pool."""
        mock_registry = MagicMock()
        mock_registry.list_devices.return_value = [
            self._device("d1", "Garage", "ONLINE")
        ]
        tel = self._telemetry(pool_url="stratum+tcp://pool.parasite.example:3333",
                              stratum_status="connected")
        tel[0]["payload"]["pool_user"] = "bc1abc.worker1"
        mock_registry.get_recent_telemetry.return_value = tel

        with patch("axe_fleet.routes._registry", mock_registry):
            with patch("axe_fleet.routes._probe_miner_latency_ms", return_value=30):
                resp = client.get(self.ENDPOINT)
        t = resp.get_json()["device_health"][0]["telemetry"]
        assert t["pool_url"] == "stratum+tcp://pool.parasite.example:3333"
        assert t["pool_user"] == "bc1abc.worker1"
        assert t["stratum_status"] == "connected"


# ══════════════════════════════════════════════════════════════════════════
#  Unit tests — _device_advice + _probe_miner_latency_ms (pure functions)
# ══════════════════════════════════════════════════════════════════════════

class TestDeviceAdviceUnit:
    """Unit tests for the fleet advice rule engine."""

    def test_offline_short_circuits_to_offline_advice(self):
        from axe_fleet.routes import _device_advice
        assert _device_advice("OFFLINE", {"temperature": 99}) == \
            ["device offline — checar energia/rede"]

    def test_high_temp_advice(self):
        from axe_fleet.routes import _device_advice
        advice = _device_advice("ONLINE", {"temperature": 85})
        assert any("temp ≥80°C" in a for a in advice)

    def test_non_reachable_statuses_short_circuit(self):
        """ERROR/CRITICAL/MAINTENANCE behave like OFFLINE; PAUSED is distinct.
        Locks in the advice branches so a paused miner never gets misleading
        'hashrate zero' telemetry advice."""
        from axe_fleet.routes import _device_advice
        for st in ("ERROR", "CRITICAL", "MAINTENANCE"):
            advice = _device_advice(st, {"temperature": 99, "hashrate_hs": 0})
            assert advice == [f"device {st.lower()} — checar energia/rede"]
        assert _device_advice("PAUSED", {"hashrate_hs": 0}) == \
            ["device pausado — miner não está hasheando"]

    def test_missing_status_defaults_to_offline(self):
        """None/empty status must default to the offline advice."""
        from axe_fleet.routes import _device_advice
        assert _device_advice(None, {"hashrate_hs": 0}) == \
            ["device offline — checar energia/rede"]
        assert _device_advice("", {"temperature": 99}) == \
            ["device offline — checar energia/rede"]

    def test_zero_hashrate_online_advice(self):
        from axe_fleet.routes import _device_advice
        advice = _device_advice("ONLINE", {"hashrate_hs": 0})
        assert any("hashrate zero" in a for a in advice)

    def test_latency_threshold_advice(self):
        from axe_fleet.routes import _device_advice
        # A mining device (hashrate > 0) — so the only variable is latency.
        base = {"hashrate_hs": 1e12}
        assert any("ping alto" in a for a in _device_advice("ONLINE", dict(base), latency_ms=200))
        assert _device_advice("ONLINE", dict(base), latency_ms=50) == []

    def test_healthy_empty(self):
        from axe_fleet.routes import _device_advice
        assert _device_advice("ONLINE", {"hashrate_hs": 1e12, "temperature": 50,
                                           "hw_error_pct": 0.1,
                                           "shares_accepted": 100, "shares_stale": 0,
                                           "wifi_rssi": -55}) == []


class TestProbeLatencyUnit:
    """Unit tests for the miner latency probe."""

    def test_empty_ip_returns_none(self):
        from axe_fleet.routes import _probe_miner_latency_ms
        assert _probe_miner_latency_ms("") is None

    def test_connection_error_returns_none(self):
        from axe_fleet.routes import _probe_miner_latency_ms
        with patch("axe_fleet.routes.socket.create_connection", side_effect=OSError("refused")):
            assert _probe_miner_latency_ms("192.168.1.100") is None

    def test_success_returns_elapsed_ms(self):
        from axe_fleet.routes import _probe_miner_latency_ms, _latency_cache
        _latency_cache.clear()
        try:
            with patch("axe_fleet.routes.socket.create_connection") as conn:
                conn.return_value.__enter__.return_value = conn.return_value
                conn.return_value.__exit__.return_value = None
                with patch("axe_fleet.routes.time.time", side_effect=[1.000, 1.045, 1.100]):
                    # round((1.045-1.000)*1000) == 45 (int() would truncate
                    # the float delta to 44 — regression guard). The 3rd
                    # time.time() feeds the cache-store ts so the write path
                    # is actually exercised.
                    assert _probe_miner_latency_ms("192.168.1.103") == 45
                assert _latency_cache.get("192.168.1.103", {}).get("ms") == 45
        finally:
            _latency_cache.clear()

    def test_latency_cached_second_call_skips_probe(self):
        """A fresh probe is cached; the next call within TTL reuses it.
        Cache is seeded directly (deterministic — no time/time mocking)."""
        import time as _t
        from axe_fleet.routes import _probe_miner_latency_ms, _latency_cache, _LATENCY_TTL
        _latency_cache.clear()
        try:
            _latency_cache["192.168.1.101"] = {"ms": 42, "ts": _t.time()}
            with patch("axe_fleet.routes.socket.create_connection") as conn:
                result = _probe_miner_latency_ms("192.168.1.101")
                conn.assert_not_called()  # served from cache
            assert result == 42
            assert _LATENCY_TTL >= 1
        finally:
            _latency_cache.clear()

    def test_failed_probe_not_cached(self):
        """A failed probe (None) must NOT be cached so a recovered miner is
        detected on the next poll."""
        import time as _t
        from axe_fleet.routes import _probe_miner_latency_ms, _latency_cache
        _latency_cache.clear()
        try:
            with patch("axe_fleet.routes.socket.create_connection", side_effect=OSError("refused")):
                assert _probe_miner_latency_ms("192.168.1.102") is None
            assert "192.168.1.102" not in _latency_cache
        finally:
            _latency_cache.clear()

    def test_cache_ttl_eviction_preserves_fresh_entries(self):
        """TTL-first eviction: stale entries (older than _LATENCY_TTL) are
        swept before the cap applies; fresh entries survive. Never a full
        clear, so live miner PINGs are preserved across a burst of new IPs."""
        from axe_fleet.routes import _cache_latency_ms, _latency_cache
        _latency_cache.clear()
        try:
            _latency_cache["192.168.0.1"] = {"ms": 5, "ts": 1.0}   # stale (now=100 → age 99 ≥ TTL)
            _latency_cache["192.168.0.2"] = {"ms": 6, "ts": 90.0}  # fresh (age 10 < TTL)
            with patch("axe_fleet.routes.time.time", return_value=100.0):
                _cache_latency_ms("192.168.0.3", 45)
            # stale swept, fresh preserved, new entry stored
            assert "192.168.0.1" not in _latency_cache
            assert _latency_cache.get("192.168.0.2", {}).get("ms") == 6
            assert _latency_cache.get("192.168.0.3", {}).get("ms") == 45
        finally:
            _latency_cache.clear()

    def test_cache_caps_at_max_entries_fifo(self):
        """Past _LATENCY_CACHE_MAX entries, only the OLDEST fresh entries are
        dropped (FIFO by ts) — never a full clear — so the cache stays at the
        cap and the newest data survives."""
        from axe_fleet.routes import _cache_latency_ms, _latency_cache, _LATENCY_CACHE_MAX
        _latency_cache.clear()
        try:
            # Seed a FULL cache with FRESH entries (ages 1.0s → 0.5s, all < TTL)
            # before the time.time mock is installed.
            for i in range(_LATENCY_CACHE_MAX):
                _latency_cache[f"192.168.{i // 256}.{i % 256}"] = {"ms": 5, "ts": 999.0 + i / 1000}
            with patch("axe_fleet.routes.time.time", return_value=1000.0):
                _cache_latency_ms("10.255.255.250", 45)
            # Cap: drop 1 oldest → still 500 total, new entry present.
            assert len(_latency_cache) == _LATENCY_CACHE_MAX
            assert _latency_cache.get("10.255.255.250", {}).get("ms") == 45
            # Oldest seeded entry (ts=999.0) evicted; a fresh one survives.
            assert "192.168.0.0" not in _latency_cache
            assert "192.168.0.1" in _latency_cache
        finally:
            _latency_cache.clear()
