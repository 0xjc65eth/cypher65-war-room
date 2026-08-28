"""Integration coverage for high-risk ASIC configuration and power controls."""

from unittest.mock import MagicMock, call, patch

import pytest

import app as _app_module


@pytest.fixture
def physical_controls(monkeypatch):
    import axe_fleet.routes as routes

    _app_module.app.config["TESTING"] = True
    registry = MagicMock()
    registry.get_device.return_value = {
        "id": "miner-1",
        "ip_address": "192.168.1.91",
        "capabilities": {
            "configure": True,
            "frequencyControl": True,
            "voltageControl": True,
        },
    }
    monkeypatch.setattr(routes, "_registry", registry)
    monkeypatch.setattr(
        routes,
        "_get_tuya_credentials",
        lambda tenant_id="": {
            "access_id": "id",
            "access_secret": "secret",
            "region": "us",
        },
    )
    monkeypatch.setattr(routes, "_log_audit", MagicMock())
    with routes._power_cycle_lock:
        routes._power_cycle_tasks.clear()
    with _app_module.app.test_client() as client:
        yield client, registry
    with routes._power_cycle_lock:
        routes._power_cycle_tasks.clear()


class TestDeviceConfigurationSafety:
    endpoint = "/api/axe-fleet/devices/miner-1/config"

    def test_configuration_requires_a_bound_server_confirmation(
        self, physical_controls
    ):
        client, _ = physical_controls
        connector = MagicMock()
        connector.update_settings.return_value = {"success": True}

        with patch("axe_fleet.routes.AxeOSConnector", return_value=connector):
            prepared = client.post(
                self.endpoint,
                json={"settings": {"frequency": 600}, "dry_run": False},
            )
            assert prepared.status_code == 202
            token = prepared.get_json()["confirmation_token"]
            connector.update_settings.assert_not_called()

            import axe_fleet.routes as routes

            routes._log_audit.assert_any_call(
                "default",
                "fleet.command_confirmation_issued",
                target="miner-1",
                details={"command": "configure", "parameter_keys": ["settings"]},
            )

            changed = client.post(
                self.endpoint,
                json={"settings": {"frequency": 650}, "confirmation_token": token,
                      "dry_run": False},
            )
            assert changed.status_code == 409
            connector.update_settings.assert_not_called()
            routes._log_audit.assert_any_call(
                "default",
                "fleet.command_confirmation_rejected",
                target="miner-1",
                details={"command": "configure", "reason": "invalid_or_expired"},
            )

            prepared_again = client.post(
                self.endpoint,
                json={"settings": {"frequency": 600}, "dry_run": False},
            )
            executed = client.post(
                self.endpoint,
                json={"settings": {"frequency": 600}, "dry_run": False,
                      "confirmation_token": prepared_again.get_json()["confirmation_token"]},
            )
            assert executed.status_code == 200
            connector.update_settings.assert_called_once_with({"frequency": 600})

    def test_configuration_rejects_unknown_or_unsafe_settings(self, physical_controls):
        client, _ = physical_controls

        unknown = client.post(self.endpoint, json={"settings": {"unsafe": 1}})
        assert unknown.status_code == 400
        assert "unsupported" in unknown.get_json()["error"]

        unsafe = client.post(self.endpoint, json={"settings": {"coreVoltage": 2500}})
        assert unsafe.status_code == 400
        assert "between" in unsafe.get_json()["error"]

        non_object = client.post(self.endpoint, json=["not", "an", "object"])
        assert non_object.status_code == 400

    def test_configuration_exposes_a_firmware_failure(self, physical_controls):
        client, _ = physical_controls
        connector = MagicMock()
        connector.update_settings.return_value = {"success": False, "error": "rejected"}
        with patch("axe_fleet.routes.AxeOSConnector", return_value=connector):
            prepared = client.post(
                self.endpoint,
                json={"settings": {"frequency": 600}, "dry_run": False},
            )
            failed = client.post(
                self.endpoint,
                json={
                    "settings": {"frequency": 600},
                    "dry_run": False,
                    "confirmation_token": prepared.get_json()["confirmation_token"],
                },
            )
        assert failed.status_code == 502
        assert failed.get_json()["success"] is False

    def test_configuration_dry_run_never_contacts_the_miner(self, physical_controls):
        client, _ = physical_controls
        with patch("axe_fleet.routes.AxeOSConnector") as connector:
            response = client.post(
                self.endpoint,
                json={"settings": {"frequency": 600}, "dry_run": True},
            )
        assert response.status_code == 200
        assert response.get_json()["dry_run"] is True
        connector.assert_not_called()


class TestPowerControlSafety:
    cycle_endpoint = "/api/axe-fleet/miners/miner-1/power-cycle"

    def test_power_cycle_requires_confirmation_before_starting_a_thread(
        self, physical_controls
    ):
        client, _ = physical_controls
        with patch("axe_fleet.routes.threading.Thread") as thread:
            prepared = client.post(
                self.cycle_endpoint,
                json={"plug_id": "plug-1", "off_seconds": 5, "dry_run": False},
            )
            assert prepared.status_code == 202
            token = prepared.get_json()["confirmation_token"]
            thread.assert_not_called()

            started = client.post(
                self.cycle_endpoint,
                json={
                    "plug_id": "plug-1",
                    "off_seconds": 5,
                    "dry_run": False,
                    "confirmation_token": token,
                },
            )
            assert started.status_code == 200
            assert started.get_json()["task_id"]
            thread.return_value.start.assert_called_once()

    def test_power_cycle_rejects_invalid_duration_and_deduplicates_active_work(
        self, physical_controls
    ):
        client, _ = physical_controls
        bad_duration = client.post(
            self.cycle_endpoint,
            json={"plug_id": "plug-1", "off_seconds": "five"},
        )
        assert bad_duration.status_code == 400
        assert (
            client.post(
                self.cycle_endpoint,
                json={"plug_id": "plug-1", "off_seconds": 5.5},
            ).status_code
            == 400
        )

        import axe_fleet.routes as routes

        with routes._power_cycle_lock:
            routes._power_cycle_tasks["active-1"] = {
                "id": "active-1",
                "tenant_id": "default",
                "device_id": "miner-1",
                "plug_id": "plug-1",
                "status": "waiting",
            }
        duplicate = client.post(self.cycle_endpoint, json={"plug_id": "plug-1"})
        assert duplicate.status_code == 409
        assert duplicate.get_json()["task_id"] == "active-1"

    def test_plug_off_requires_server_confirmation(self, physical_controls):
        client, _ = physical_controls
        with patch("axe_fleet.routes._execute_plug_command") as execute:
            prepared = client.post(
                "/api/axe-fleet/power-plugs/plug-1/off", json={"dry_run": False}
            )
            assert prepared.status_code == 202
            token = prepared.get_json()["confirmation_token"]
            execute.assert_not_called()

            execute.return_value = {"success": True}
            confirmed = client.post(
                "/api/axe-fleet/power-plugs/plug-1/off",
                json={"confirmation_token": token, "dry_run": False},
            )
            assert confirmed.status_code == 200
            execute.assert_called_once_with("plug-1", "power_off", tenant_id="default")

    def test_remote_unauthenticated_power_control_is_rejected(
        self, physical_controls, monkeypatch
    ):
        client, _ = physical_controls
        monkeypatch.setenv("API_KEY", "operator-key")

        response = client.post(
            "/api/axe-fleet/power-plugs/plug-1/off",
            json={},
            environ_overrides={"REMOTE_ADDR": "203.0.113.9"},
        )
        assert response.status_code == 401


class TestTuyaCredentialInputSafety:
    def test_tuya_credential_endpoints_reject_invalid_payloads_before_api_calls(
        self, physical_controls
    ):
        client, _ = physical_controls
        with patch("services.tuya_adapter.TuyaCloudAdapter") as adapter:
            array_payload = client.post(
                "/api/axe-fleet/power-plugs/save-credentials",
                json=["not", "an", "object"],
            )
            assert array_payload.status_code == 400

            bad_region = client.post(
                "/api/axe-fleet/power-plugs/save-credentials",
                json={
                    "access_id": "id",
                    "access_secret": "secret",
                    "region": "unexpected-region",
                },
            )
            assert bad_region.status_code == 400

            bad_override = client.post(
                "/api/axe-fleet/power-plugs/validate",
                json={"access_id": 99},
            )
            assert bad_override.status_code == 400
            adapter.assert_not_called()

    def test_saves_credentials_under_the_callers_tenant(self, physical_controls):
        client, _ = physical_controls
        with (
            patch("services.tuya_adapter.TuyaCloudAdapter") as adapter,
            patch("services.settings.save_setting", return_value=True) as save_setting,
        ):
            adapter.return_value.validate_credentials.return_value = {"valid": True}
            response = client.post(
                "/api/axe-fleet/power-plugs/save-credentials",
                json={
                    "access_id": "id",
                    "access_secret": "secret",
                    "region": "eu",
                },
            )
        assert response.status_code == 200
        assert save_setting.call_args_list == [
            call("tuya_access_id", "id", "default"),
            call("tuya_access_secret", "secret", "default"),
            call("tuya_region", "eu", "default"),
        ]

    def test_named_tenant_never_inherits_operator_tuya_environment(self, monkeypatch):
        import axe_fleet.routes as routes
        import services.settings as settings

        monkeypatch.setenv("TUYA_ACCESS_ID", "operator-id")
        monkeypatch.setenv("TUYA_ACCESS_SECRET", "operator-secret")
        monkeypatch.setattr(
            settings,
            "load_settings",
            lambda tenant_id="": {
                "tuya_access_id": f"{tenant_id}-id",
                "tuya_access_secret": f"{tenant_id}-secret",
                "tuya_region": "eu",
                "tuya_uid": "",
            },
        )
        assert routes._get_tuya_credentials("tenant-a") == {
            "access_id": "tenant-a-id",
            "access_secret": "tenant-a-secret",
            "region": "eu",
            "uid": "",
        }

    def test_tuya_errors_never_echo_credentials(self, physical_controls):
        client, _ = physical_controls
        access_id = "sensitive-access-id"
        access_secret = "sensitive-access-secret"
        with patch("services.tuya_adapter.TuyaCloudAdapter") as adapter:
            adapter.return_value.validate_credentials.return_value = {
                "valid": False,
                "error": f"denied {access_id} with {access_secret}",
            }
            response = client.post(
                "/api/axe-fleet/power-plugs/save-credentials",
                json={
                    "access_id": access_id,
                    "access_secret": access_secret,
                    "region": "eu",
                },
            )

        body = response.get_data(as_text=True)
        assert response.status_code == 200
        assert access_id not in body
        assert access_secret not in body
        assert "[REDACTED]" in body
