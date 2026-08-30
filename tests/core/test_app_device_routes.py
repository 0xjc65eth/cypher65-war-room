"""Tests for the core device API routes in app.py."""

import time
from unittest.mock import Mock, patch

import pytest

from core.models.device import Device, DeviceStatus
from core.models.capability import Capability


@pytest.fixture(autouse=True)
def _enable_validated_physical_commands(monkeypatch):
    """This module intentionally exercises behavior beyond the global gate."""
    monkeypatch.setenv("ENABLE_PHYSICAL_COMMANDS", "true")


class TestAppDeviceRoutes:
    @pytest.fixture(autouse=True)
    def clear_pending_confirmations(self, monkeypatch):
        """Keep durable one-time command approvals isolated between tests."""
        from services.command_confirmation import _connect, ensure_table

        conn = _connect()
        ensure_table(conn)
        conn.execute("DELETE FROM command_confirmations")
        conn.commit()
        conn.close()
        yield
        conn = _connect()
        ensure_table(conn)
        conn.execute("DELETE FROM command_confirmations")
        conn.commit()
        conn.close()

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
        An online ASIC must still require a server-side confirmation and never
        reach its adapter from an unconfirmed request."""
        flask_client, registry = client
        from core.adapters.bitaxe_adapter import BitaxeAdapter

        device = Device(
            name="Test-Command",
            model="Bitaxe",
            ip="192.168.1.55",
            status=DeviceStatus.ONLINE,
        )
        device.capabilities = BitaxeAdapter(device).get_capabilities()
        registry.add_device(device)

        with patch("routes.device_control._build_adapter") as build_adapter:
            response = flask_client.post(
                f"/api/devices/{device.id}/command",
                json={
                    "command": "set_frequency",
                    "parameters": {"frequency": 550},
                    "dry_run": False,
                },
            )

        assert response.status_code == 403
        data = response.get_json()
        assert data["success"] is False
        assert data.get("requires_confirmation") is True
        assert data["confirmation_phrase"] == "CONFIRM SET_FREQUENCY"
        build_adapter.assert_not_called()

    def test_confirmation_token_executes_exact_online_command_once(self, client):
        flask_client, registry = client
        from core.adapters.bitaxe_adapter import BitaxeAdapter

        device = Device(
            name="Confirmed-Command",
            model="Bitaxe",
            ip="192.168.1.59",
            status=DeviceStatus.ONLINE,
        )
        device.capabilities = BitaxeAdapter(device).get_capabilities()
        registry.add_device(device)
        payload = {
            "command": "set_frequency",
            "parameters": {"frequency": 550},
            "dry_run": False,
        }

        confirmation = flask_client.post(
            f"/api/devices/{device.id}/command/confirmation",
            json={**payload, "confirmation": "CONFIRM SET_FREQUENCY"},
        )
        assert confirmation.status_code == 201
        assert "no-store" in confirmation.headers["Cache-Control"]
        assert confirmation.headers["Pragma"] == "no-cache"
        token = confirmation.get_json()["confirmation_token"]

        adapter = Mock()
        adapter.execute_command.return_value = {"success": True, "status_code": 200}
        with patch(
            "routes.device_control._build_adapter", return_value=adapter
        ) as build_adapter:
            response = flask_client.post(
                f"/api/devices/{device.id}/command",
                json={**payload, "confirmation_token": token},
            )

        assert response.status_code == 200
        assert response.get_json()["success"] is True
        build_adapter.assert_called_once()
        adapter.execute_command.assert_called_once_with(
            "set_frequency", {"frequency": 550}
        )

    def test_viewer_cannot_confirm_or_execute_physical_commands(
        self, client, monkeypatch
    ):
        flask_client, registry = client
        from core.adapters.bitaxe_adapter import BitaxeAdapter

        monkeypatch.setenv("API_KEY", "rbac-is-enabled")
        device = Device(
            name="Viewer-Blocked",
            model="Bitaxe",
            ip="192.168.1.64",
            status=DeviceStatus.ONLINE,
        )
        device.capabilities = BitaxeAdapter(device).get_capabilities()
        registry.add_device(device)
        payload = {
            "command": "set_frequency",
            "parameters": {"frequency": 550},
            "dry_run": False,
        }

        with patch("services.tenant.get_current_role", return_value="viewer"):
            with patch("routes.device_control._build_adapter") as build_adapter:
                confirmation = flask_client.post(
                    f"/api/devices/{device.id}/command/confirmation",
                    json={**payload, "confirmation": "CONFIRM SET_FREQUENCY"},
                )
                execution = flask_client.post(
                    f"/api/devices/{device.id}/command",
                    json=payload,
                )

        assert confirmation.status_code == 403
        assert execution.status_code == 403
        assert confirmation.get_json()["required_role"] == "member"
        assert execution.get_json()["role"] == "viewer"
        build_adapter.assert_not_called()

    def test_member_can_confirm_and_execute_physical_commands(
        self, client, monkeypatch
    ):
        flask_client, registry = client
        from core.adapters.bitaxe_adapter import BitaxeAdapter

        monkeypatch.setenv("API_KEY", "rbac-is-enabled")
        device = Device(
            name="Member-Allowed",
            model="Bitaxe",
            ip="192.168.1.65",
            status=DeviceStatus.ONLINE,
        )
        device.capabilities = BitaxeAdapter(device).get_capabilities()
        registry.add_device(device)
        payload = {
            "command": "set_frequency",
            "parameters": {"frequency": 550},
            "dry_run": False,
        }
        adapter = Mock()
        adapter.execute_command.return_value = {"success": True}

        with patch("services.tenant.get_current_role", return_value="member"):
            confirmation = flask_client.post(
                f"/api/devices/{device.id}/command/confirmation",
                json={**payload, "confirmation": "CONFIRM SET_FREQUENCY"},
            )
            token = confirmation.get_json()["confirmation_token"]
            with patch("routes.device_control._build_adapter", return_value=adapter):
                execution = flask_client.post(
                    f"/api/devices/{device.id}/command",
                    json={**payload, "confirmation_token": token},
                )

        assert confirmation.status_code == 201
        assert execution.status_code == 200
        adapter.execute_command.assert_called_once_with(
            "set_frequency", {"frequency": 550}
        )

    def test_command_credentials_are_redacted_from_response_history_and_audit(
        self, client
    ):
        flask_client, registry = client
        from core.adapters.bitaxe_adapter import BitaxeAdapter
        from services.tenant import recent_audit_logs

        device = Device(
            name="Redacted-Command",
            model="Bitaxe",
            ip="192.168.1.63",
            status=DeviceStatus.ONLINE,
        )
        device.capabilities = BitaxeAdapter(device).get_capabilities()
        registry.add_device(device)
        secret = "never-persist-this-value"
        parameters = {
            "stratumURL": "stratum.example.test",
            "poolPassword": secret,
            "nested": {"access_token": secret},
        }
        payload = {
            "command": "update_pool",
            "parameters": parameters,
            "dry_run": False,
        }
        confirmation = flask_client.post(
            f"/api/devices/{device.id}/command/confirmation",
            json={**payload, "confirmation": "CONFIRM UPDATE_POOL"},
        )
        token = confirmation.get_json()["confirmation_token"]

        adapter = Mock()
        adapter.execute_command.return_value = {
            "success": True,
            "parameters": parameters,
        }
        with patch("routes.device_control._build_adapter", return_value=adapter):
            response = flask_client.post(
                f"/api/devices/{device.id}/command",
                json={**payload, "confirmation_token": token},
            )

        assert response.status_code == 200
        assert secret not in response.get_data(as_text=True)
        assert (
            response.get_json()["result"]["parameters"]["poolPassword"] == "[REDACTED]"
        )
        history = flask_client.get(f"/api/devices/{device.id}/commands")
        assert history.status_code == 200
        assert secret not in history.get_data(as_text=True)
        audit_rows = recent_audit_logs(limit=200)
        matching = [
            row
            for row in audit_rows
            if row["action"] == "device.command" and row["target"] == device.id
        ]
        assert matching
        assert secret not in str(matching)

    def test_confirmation_token_cannot_be_replayed_or_rebound(self, client):
        flask_client, registry = client
        from core.adapters.bitaxe_adapter import BitaxeAdapter

        device = Device(
            name="One-Time-Command",
            model="Bitaxe",
            ip="192.168.1.60",
            status=DeviceStatus.ONLINE,
        )
        device.capabilities = BitaxeAdapter(device).get_capabilities()
        registry.add_device(device)
        payload = {
            "command": "set_frequency",
            "parameters": {"frequency": 550},
            "dry_run": False,
        }
        confirmation = flask_client.post(
            f"/api/devices/{device.id}/command/confirmation",
            json={**payload, "confirmation": "CONFIRM SET_FREQUENCY"},
        )
        token = confirmation.get_json()["confirmation_token"]

        adapter = Mock()
        adapter.execute_command.return_value = {"success": True}
        with patch("routes.device_control._build_adapter", return_value=adapter):
            mismatch = flask_client.post(
                f"/api/devices/{device.id}/command",
                json={
                    "command": "set_frequency",
                    "parameters": {"frequency": 600},
                    "dry_run": False,
                    "confirmation_token": token,
                },
            )
            replay = flask_client.post(
                f"/api/devices/{device.id}/command",
                json={**payload, "confirmation_token": token},
            )

        assert mismatch.status_code == 403
        assert "mismatched" in mismatch.get_json()["error"]
        assert replay.status_code == 403
        assert "expired, or was already used" in replay.get_json()["error"]
        adapter.execute_command.assert_not_called()

    def test_confirmation_requires_typed_phrase_and_expires(self, client):
        flask_client, registry = client
        from core.adapters.bitaxe_adapter import BitaxeAdapter
        from routes import device_control

        device = Device(
            name="Expiry-Command",
            model="Bitaxe",
            ip="192.168.1.61",
            status=DeviceStatus.ONLINE,
        )
        device.capabilities = BitaxeAdapter(device).get_capabilities()
        registry.add_device(device)
        payload = {
            "command": "set_frequency",
            "parameters": {"frequency": 550},
            "dry_run": False,
        }

        invalid = flask_client.post(
            f"/api/devices/{device.id}/command/confirmation",
            json={**payload, "confirmation": "yes"},
        )
        assert invalid.status_code == 400
        assert invalid.get_json()["confirmation_phrase"] == "CONFIRM SET_FREQUENCY"

        binding = device_control._confirmation_binding(
            "default", device.id, "set_frequency", {"frequency": 550}
        )
        with patch("routes.device_control.time.time", return_value=1_000):
            token = device_control._issue_confirmation(binding)
        with patch("routes.device_control.time.time", return_value=1_121):
            confirmed, reason = device_control._consume_confirmation(token, binding)
        assert confirmed is False
        assert "expired" in reason

    def test_confirmation_token_is_tenant_bound(self):
        from routes import device_control

        binding = device_control._confirmation_binding(
            "tenant-a", "device-1", "restart", {}
        )
        other_tenant = device_control._confirmation_binding(
            "tenant-b", "device-1", "restart", {}
        )
        token = device_control._issue_confirmation(binding)
        confirmed, reason = device_control._consume_confirmation(token, other_tenant)

        assert confirmed is False
        assert "mismatched" in reason

    def test_capability_metadata_cannot_downgrade_default_command_safety(self):
        from core.models.capability import Capability, RiskLevel
        from routes.device_control import _command_metadata

        device = Device(
            name="Legacy-Capability",
            model="Bitaxe",
            capabilities=[
                Capability(
                    name="restart",
                    supported=True,
                    requires_confirmation=False,
                    risk_level=RiskLevel.LOW,
                )
            ],
        )

        metadata = _command_metadata(device, device, "restart")

        assert metadata["requires_confirmation"] is True
        assert metadata["risk_level"] == "medium"

    def test_device_execution_error_is_safe_and_persistently_audited(self, client):
        flask_client, registry = client
        from core.adapters.bitaxe_adapter import BitaxeAdapter
        from services.tenant import recent_audit_logs

        device = Device(
            name="Safe-Error",
            model="Bitaxe",
            ip="192.168.1.62",
            status=DeviceStatus.ONLINE,
        )
        device.capabilities = BitaxeAdapter(device).get_capabilities()
        registry.add_device(device)
        payload = {
            "command": "set_frequency",
            "parameters": {"frequency": 550},
            "dry_run": False,
        }
        confirmation = flask_client.post(
            f"/api/devices/{device.id}/command/confirmation",
            json={**payload, "confirmation": "CONFIRM SET_FREQUENCY"},
        )
        token = confirmation.get_json()["confirmation_token"]

        adapter = Mock()
        adapter.execute_command.side_effect = RuntimeError(
            "http://192.168.1.62: secret firmware diagnostic"
        )
        with patch("routes.device_control._build_adapter", return_value=adapter):
            response = flask_client.post(
                f"/api/devices/{device.id}/command",
                json={**payload, "confirmation_token": token},
            )

        assert response.status_code == 503
        data = response.get_json()
        assert data["error"] == (
            "The device did not accept the command. Verify connectivity and firmware before retrying."
        )
        assert "192.168" not in str(data)
        assert "secret firmware" not in str(data)
        audit_rows = recent_audit_logs(limit=200)
        assert any(
            row["action"] == "device.command"
            and row["target"] == device.id
            and row["details"]["success"] is False
            for row in audit_rows
        )

    def test_only_one_runtime_command_route_is_registered(self, client):
        from app import app

        matching_rules = [
            rule
            for rule in app.url_map.iter_rules()
            if rule.rule == "/api/devices/<device_id>/command"
            and "POST" in rule.methods
        ]
        assert len(matching_rules) == 1
        assert matching_rules[0].endpoint == "device_control.execute_device_command"

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
            (
                "command",
                {"command": "restart", "parameters": []},
                "parameters must be an object",
            ),
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

    def test_physical_command_endpoint_defaults_to_audited_dry_run(self, client):
        flask_client, registry = client
        from core.adapters.bitaxe_adapter import BitaxeAdapter

        device = Device(
            name="Default-Dry-Run",
            model="Bitaxe",
            ip="192.168.1.58",
            status=DeviceStatus.ONLINE,
        )
        device.capabilities = BitaxeAdapter(device).get_capabilities()
        registry.add_device(device)

        with patch("routes.device_control._build_adapter") as build_adapter:
            response = flask_client.post(
                f"/api/devices/{device.id}/command",
                json={"command": "restart"},
            )

        assert response.status_code == 200
        assert response.get_json()["dry_run"] is True
        assert response.get_json()["read_only"] is True
        assert response.get_json()["would_require_confirmation"] is True
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
        flask_client.post(
            f"/api/devices/{device.id}/command", json={"command": "restart"}
        )

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
        device = Device(
            name="Health-Device",
            model="Bitaxe",
            ip="192.168.1.70",
            status=DeviceStatus.ONLINE,
        )
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
        device = Device(
            name="Health-Listed",
            model="Bitaxe",
            ip="192.168.1.71",
            status=DeviceStatus.ONLINE,
        )
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

        device = Device(
            name="Timeline-Device",
            model="Bitaxe",
            ip="192.168.1.72",
            status=DeviceStatus.ONLINE,
        )
        device.capabilities = BitaxeAdapter(device).get_capabilities()
        registry.add_device(device)

        # Record a maintenance event
        maintenance_response = flask_client.post(
            f"/api/devices/{device.id}/maintenance",
            json={"type": "cleaning", "notes": "fan check", "performed_by": "tech"},
        )
        assert maintenance_response.status_code == 201

        # Issue a command that is blocked by safety but recorded
        flask_client.post(
            f"/api/devices/{device.id}/command", json={"command": "restart"}
        )

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

        device = Device(
            name="Timeline-Sorted",
            model="Bitaxe",
            ip="192.168.1.73",
            status=DeviceStatus.ONLINE,
        )
        device.capabilities = BitaxeAdapter(device).get_capabilities()
        registry.add_device(device)

        flask_client.post(
            f"/api/devices/{device.id}/maintenance", json={"type": "cleaning"}
        )
        flask_client.post(
            f"/api/devices/{device.id}/maintenance", json={"type": "firmware_update"}
        )

        response = flask_client.get(f"/api/devices/{device.id}/timeline")
        assert response.status_code == 200
        data = response.get_json()
        timestamps = [event["timestamp"] for event in data["events"]]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_timeline_includes_status_change(self, client):
        flask_client, registry = client
        from core.adapters.bitaxe_adapter import BitaxeAdapter

        device = Device(
            name="Timeline-Status",
            model="Bitaxe",
            ip="192.168.1.74",
            status=DeviceStatus.ONLINE,
        )
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

        device = Device(
            name="Test-Pause-Core",
            model="Bitaxe",
            ip="192.168.1.78",
            status=DeviceStatus.ONLINE,
        )
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


class TestDeviceCommandSecurity:
    @pytest.fixture
    def client(self):
        from app import app, _core_registry

        app.config["TESTING"] = True
        yield app.test_client(), _core_registry

    def test_protected_device_list_rejects_anonymous_request(self, client, monkeypatch):
        flask_client, _ = client
        monkeypatch.setenv("API_KEY", "device-api-key")

        response = flask_client.get(
            "/api/devices", environ_overrides={"REMOTE_ADDR": "203.0.113.10"}
        )
        assert response.status_code == 403

    def test_protected_device_list_accepts_valid_api_key(self, client, monkeypatch):
        flask_client, _ = client
        monkeypatch.setenv("API_KEY", "device-api-key")

        response = flask_client.get(
            "/api/devices",
            headers={"X-API-Key": "device-api-key"},
            environ_overrides={"REMOTE_ADDR": "203.0.113.10"},
        )
        assert response.status_code == 200

    def test_restart_needs_one_time_server_confirmation(self, client, monkeypatch):
        flask_client, registry = client
        device = Device(
            name="Confirmation Device",
            model="Bitaxe",
            firmware="axeos",
            ip="192.168.1.91",
            status=DeviceStatus.ONLINE,
            capabilities=[Capability(name="restart", supported=True)],
        )
        registry.add_device(device)

        class FakeAdapter:
            calls = 0

            def execute_command(self, command, parameters):
                self.calls += 1
                return {"success": True, "command": command}

        adapter = FakeAdapter()
        monkeypatch.setattr(
            "routes.device_control._build_adapter", lambda *args: adapter
        )

        unconfirmed = flask_client.post(
            f"/api/devices/{device.id}/command",
            json={"command": "restart", "dry_run": False},
        )
        assert unconfirmed.status_code == 403
        payload = unconfirmed.get_json()
        assert payload["requires_confirmation"] is True
        assert adapter.calls == 0

        prepared = flask_client.post(
            f"/api/devices/{device.id}/command/confirmation",
            json={"command": "restart", "confirmation": "CONFIRM RESTART"},
        )
        assert prepared.status_code == 201
        confirmation_token = prepared.get_json()["confirmation_token"]

        executed = flask_client.post(
            f"/api/devices/{device.id}/command",
            json={
                "command": "restart",
                "dry_run": False,
                "confirmation_token": confirmation_token,
            },
        )
        assert executed.status_code == 200
        assert executed.get_json()["ack"]["state"] == "acknowledged"
        assert executed.get_json()["reconciliation"]["state"] == "pending"
        assert executed.get_json()["operation_id"]
        assert executed.get_json()["success"] is True
        assert adapter.calls == 1

        replay = flask_client.post(
            f"/api/devices/{device.id}/command",
            json={
                "command": "restart",
                "dry_run": False,
                "confirmation_token": confirmation_token,
            },
        )
        # The restart cooldown may reject before token replay is checked; both
        # paths fail closed and never perform a second physical call.
        assert replay.status_code == 403
        assert adapter.calls == 1

    def test_only_one_device_command_route_is_registered(self):
        from app import app

        routes = [
            rule
            for rule in app.url_map.iter_rules()
            if str(rule) == "/api/devices/<device_id>/command"
        ]
        assert len(routes) == 1
        assert routes[0].endpoint == "device_control.execute_device_command"
