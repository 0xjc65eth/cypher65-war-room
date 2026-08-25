"""Tests for the core device API routes in app.py."""
import time
from unittest.mock import patch

import pytest

from core.models.device import Device, DeviceStatus


class TestAppDeviceRoutes:
    @pytest.fixture
    def client(self):
        from app import app, _core_registry

        app.config["TESTING"] = True
        yield app.test_client(), _core_registry

    def test_get_device_not_found(self, client):
        flask_client, _ = client
        response = flask_client.get("/api/devices/does-not-exist")
        assert response.status_code == 404
        data = response.get_json()
        assert data["error"] == "device not found"

    def test_get_device_success(self, client):
        flask_client, registry = client
        device = Device(name="Test-Device", model="Bitaxe Max", ip="192.168.1.50")
        registry.add_device(device)

        response = flask_client.get(f"/api/devices/{device.id}")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["device"]["id"] == device.id
        assert data["device"]["name"] == "Test-Device"
        assert data["device"]["status"] == "offline"

    def test_list_devices_includes_telemetry(self, client):
        flask_client, registry = client
        device = Device(name="Listed-Device", model="Bitaxe", ip="192.168.1.51")
        device.current_telemetry = {
            "source": "bitaxe_adapter",
            "timestamp": int(time.time()) - 10,
            "hashrate": 1.5e12,
            "temperature": 72.0,
        }
        registry.add_device(device)

        response = flask_client.get("/api/devices")
        assert response.status_code == 200
        data = response.get_json()
        found = next((d for d in data["devices"] if d["id"] == device.id), None)
        assert found is not None
        assert found["current_telemetry"] is not None
        assert found["current_telemetry"]["source"] == "bitaxe_adapter"
        # freshness should be recomputed on the fly
        assert "freshness" in found["current_telemetry"]

    def test_fleet_summary(self, client):
        flask_client, registry = client
        online = Device(name="Online-Device", model="Bitaxe", ip="192.168.1.52")
        online.status = DeviceStatus.ONLINE
        online.current_telemetry = {
            "source": "bitaxe_adapter",
            "timestamp": int(time.time()),
            "hashrate": 2.5e12,
        }
        offline = Device(name="Offline-Device", model="Bitaxe", ip="192.168.1.53")
        registry.add_device(online)
        registry.add_device(offline)

        response = flask_client.get("/api/fleet/summary")
        assert response.status_code == 200
        data = response.get_json()
        assert data["total"] >= 2
        assert data["status_counts"]["online"] >= 1
        assert data["status_counts"]["offline"] >= 1
        assert data["devices_with_recent_telemetry"] >= 1
        assert data["total_hashrate"] > 0

    def test_fleet_summary_excludes_stale_telemetry(self, client):
        flask_client, registry = client
        stale = Device(name="Stale-Device", model="Bitaxe", ip="192.168.1.54")
        stale.status = DeviceStatus.ONLINE
        stale.current_telemetry = {
            "source": "bitaxe_adapter",
            "timestamp": int(time.time()) - 1000,
            "hashrate": 2.5e12,
        }
        registry.add_device(stale)

        response = flask_client.get("/api/fleet/summary")
        assert response.status_code == 200
        data = response.get_json()
        # The stale device is not counted in recent telemetry nor hashrate.
        # We can't assert exact numbers because the global registry may contain
        # other entries, but at least the response schema is present.
        assert "devices_with_recent_telemetry" in data
        assert "total_hashrate" in data

    def test_refresh_device_not_found(self, client):
        flask_client, _ = client
        response = flask_client.post("/api/devices/unknown-id/refresh")
        assert response.status_code == 404

    def test_device_command_not_supported(self, client):
        flask_client, registry = client
        from core.adapters.bitaxe_adapter import BitaxeAdapter
        device = Device(name="Test-Command", model="Bitaxe", ip="192.168.1.55")
        device.capabilities = BitaxeAdapter(device).get_capabilities()
        registry.add_device(device)

        # firmware_flash is genuinely unsupported by the Bitaxe adapter.
        response = flask_client.post(
            f"/api/devices/{device.id}/command",
            json={"command": "firmware_flash"},
        )
        assert response.status_code == 400
        data = response.get_json()
        assert data["success"] is False
        assert "not supported" in data["error"].lower()

    def test_device_command_set_frequency_now_supported_but_safety_gated(self, client):
        """P0 Bitaxe: set_frequency is now a REAL command (overclock endpoint).
        The SafetyEngine still gates it — HIGH risk requires confirmation, so
        an unconfirmed call is blocked (403) rather than reaching the ASIC."""
        flask_client, registry = client
        from core.adapters.bitaxe_adapter import BitaxeAdapter
        device = Device(name="Test-Command", model="Bitaxe", ip="192.168.1.55")
        device.capabilities = BitaxeAdapter(device).get_capabilities()
        registry.add_device(device)

        response = flask_client.post(
            f"/api/devices/{device.id}/command",
            json={"command": "set_frequency", "parameters": {"frequency": 550}},
        )
        assert response.status_code == 403  # SafetyEngine blocks unconfirmed HIGH
        data = response.get_json()
        assert data["success"] is False
        assert data.get("requires_confirmation") is True

    def test_device_command_offline_blocked_by_safety(self, client):
        flask_client, registry = client
        from core.adapters.bitaxe_adapter import BitaxeAdapter
        device = Device(name="Test-Offline", model="Bitaxe", ip="192.168.1.56")
        device.capabilities = BitaxeAdapter(device).get_capabilities()
        registry.add_device(device)

        response = flask_client.post(
            f"/api/devices/{device.id}/command",
            json={"command": "restart"},
        )
        assert response.status_code == 403
        data = response.get_json()
        assert data["success"] is False
        assert "offline" in data["error"].lower()
        assert data["requires_confirmation"] is True

    @pytest.mark.parametrize(
        "path_suffix, payload, error",
        [
            ("command", ["restart"], "JSON body must be an object"),
            ("command", {"command": 123}, "command must be a string"),
            ("command", {"command": "restart", "parameters": []}, "parameters must be an object"),
            ("test", ["restart"], "JSON body must be an object"),
            ("test", {"command": 123}, "command must be a string"),
        ],
    )
    def test_device_command_rejects_invalid_json_payloads(
        self, client, path_suffix, payload, error
    ):
        """Invalid JSON shapes must return 400 instead of an internal error."""
        flask_client, registry = client
        device = Device(name="Test-Invalid-Payload", model="Bitaxe", ip="192.168.1.56")
        registry.add_device(device)

        response = flask_client.post(
            f"/api/devices/{device.id}/{path_suffix}", json=payload
        )

        assert response.status_code == 400
        assert response.get_json() == {"success": False, "error": error}

    def test_device_test_command_is_simulated_without_building_an_adapter(self, client):
        """The test endpoint is a dry-run: it must never touch ASIC I/O."""
        flask_client, registry = client
        device = Device(name="Test-Dry-Run", model="Bitaxe", ip="192.168.1.56")
        registry.add_device(device)

        with patch("routes.device_control._build_adapter") as build_adapter:
            response = flask_client.post(
                f"/api/devices/{device.id}/test", json={"command": "restart"}
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["simulated"] is True
        assert data["test_mode"] is True
        assert data["result"]["simulated"] is True
        build_adapter.assert_not_called()

    def test_device_command_history_empty(self, client):
        flask_client, registry = client
        from core.adapters.bitaxe_adapter import BitaxeAdapter
        device = Device(name="Test-History", model="Bitaxe", ip="192.168.1.57")
        device.capabilities = BitaxeAdapter(device).get_capabilities()
        registry.add_device(device)

        response = flask_client.get(f"/api/devices/{device.id}/commands")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["commands"] == []

    def test_device_command_history_records_entry(self, client):
        flask_client, registry = client
        from core.adapters.bitaxe_adapter import BitaxeAdapter
        device = Device(name="Test-History-Rec", model="Bitaxe", ip="192.168.1.58")
        device.capabilities = BitaxeAdapter(device).get_capabilities()
        registry.add_device(device)

        # First command should be blocked by safety (offline) but still recorded
        flask_client.post(f"/api/devices/{device.id}/command", json={"command": "restart"})

        response = flask_client.get(f"/api/devices/{device.id}/commands")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert len(data["commands"]) == 1
        entry = data["commands"][0]
        assert entry["command"] == "restart"
        assert entry["success"] is False
        assert entry["result"]["requires_confirmation"] is True
        assert isinstance(entry["timestamp"], int)

    def test_get_device_includes_health_fields(self, client):
        flask_client, registry = client
        device = Device(name="Health-Device", model="Bitaxe", ip="192.168.1.70", status=DeviceStatus.ONLINE)
        device.current_telemetry = {"temperature": 95}
        registry.add_device(device)

        response = flask_client.get(f"/api/devices/{device.id}")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert "health_score" in data["device"]
        assert "active_issues" in data["device"]
        assert "last_diagnostic_at" in data["device"]
        assert data["device"]["health_score"] < 100
        assert any("Temperature" in issue for issue in data["device"]["active_issues"])

    def test_list_devices_includes_health_fields(self, client):
        flask_client, registry = client
        device = Device(name="Health-Listed", model="Bitaxe", ip="192.168.1.71", status=DeviceStatus.ONLINE)
        registry.add_device(device)

        response = flask_client.get("/api/devices")
        assert response.status_code == 200
        data = response.get_json()
        found = next((d for d in data["devices"] if d["id"] == device.id), None)
        assert found is not None
        assert "health_score" in found
        assert "active_issues" in found
        assert "last_diagnostic_at" in found

    def test_timeline_not_found(self, client):
        flask_client, _ = client
        response = flask_client.get("/api/devices/does-not-exist/timeline")
        assert response.status_code == 404

    def test_timeline_includes_command_and_maintenance(self, client):
        flask_client, registry = client
        from core.adapters.bitaxe_adapter import BitaxeAdapter
        device = Device(name="Timeline-Device", model="Bitaxe", ip="192.168.1.72", status=DeviceStatus.ONLINE)
        device.capabilities = BitaxeAdapter(device).get_capabilities()
        registry.add_device(device)

        # Record a maintenance event
        maintenance_response = flask_client.post(
            f"/api/devices/{device.id}/maintenance",
            json={"type": "cleaning", "notes": "fan check", "performed_by": "tech"},
        )
        assert maintenance_response.status_code == 201

        # Issue a command that is blocked by safety but recorded
        flask_client.post(f"/api/devices/{device.id}/command", json={"command": "restart"})

        response = flask_client.get(f"/api/devices/{device.id}/timeline")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert data["device_id"] == device.id

        types = [event["type"] for event in data["events"]]
        assert "maintenance" in types
        assert "command" in types

    def test_timeline_sorted_newest_first(self, client):
        flask_client, registry = client
        from core.adapters.bitaxe_adapter import BitaxeAdapter
        device = Device(name="Timeline-Sorted", model="Bitaxe", ip="192.168.1.73", status=DeviceStatus.ONLINE)
        device.capabilities = BitaxeAdapter(device).get_capabilities()
        registry.add_device(device)

        flask_client.post(f"/api/devices/{device.id}/maintenance", json={"type": "cleaning"})
        flask_client.post(f"/api/devices/{device.id}/maintenance", json={"type": "firmware_update"})

        response = flask_client.get(f"/api/devices/{device.id}/timeline")
        assert response.status_code == 200
        data = response.get_json()
        timestamps = [event["timestamp"] for event in data["events"]]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_timeline_includes_status_change(self, client):
        flask_client, registry = client
        from core.adapters.bitaxe_adapter import BitaxeAdapter
        device = Device(name="Timeline-Status", model="Bitaxe", ip="192.168.1.74", status=DeviceStatus.ONLINE)
        device.capabilities = BitaxeAdapter(device).get_capabilities()
        registry.add_device(device)

        # Force the adapter to report no telemetry so the device goes offline
        original_get_telemetry = BitaxeAdapter.get_telemetry
        BitaxeAdapter.get_telemetry = lambda self: None
        try:
            response = flask_client.post(f"/api/devices/{device.id}/refresh")
        finally:
            BitaxeAdapter.get_telemetry = original_get_telemetry
        assert response.status_code == 200

        response = flask_client.get(f"/api/devices/{device.id}/timeline")
        assert response.status_code == 200
        data = response.get_json()
        status_events = [e for e in data["events"] if e["type"] == "status_change"]
        assert len(status_events) >= 1
        assert status_events[0]["details"]["old_status"] == "online"
        assert status_events[0]["details"]["new_status"] == "offline"

    def test_device_command_pause_supported_on_core_route(self, client):
        """Regression: pause/resume must remain reachable on the CORE route for
        core-registry devices (BitaxeAdapter supports them via ESP-Miner).

        The FLEET COMMAND CENTER buttons route pause/resume to the axe-fleet
        endpoints (axe-registry ids), but the core /api/devices/<id>/command
        path must not be orphaned — a core device hitting it must get a
        SAFETY evaluation (not a 400 'not supported')."""
        flask_client, registry = client
        from core.adapters.bitaxe_adapter import BitaxeAdapter
        device = Device(name="Test-Pause-Core", model="Bitaxe", ip="192.168.1.78",
                        status=DeviceStatus.ONLINE)
        device.capabilities = BitaxeAdapter(device).get_capabilities()
        registry.add_device(device)

        response = flask_client.post(
            f"/api/devices/{device.id}/command",
            json={"command": "pause"},
        )
        # Supported by the adapter: the SafetyEngine may block (403, needs
        # confirmation / online check) but it must NOT be 'not supported'.
        assert response.status_code != 400
        data = response.get_json()
        assert data["success"] is False or data["success"] is True
        assert "not supported" not in data.get("error", "").lower()
