"""Tests for the device maintenance endpoints."""

from core.models.device import Device, DeviceStatus


class TestMaintenanceEndpoints:
    def test_post_maintenance_not_found(self, client):
        flask_client, _ = client
        response = flask_client.post(
            "/api/devices/does-not-exist/maintenance",
            json={"type": "cleaning"},
        )
        assert response.status_code == 404

    def test_post_maintenance_missing_type(self, client):
        flask_client, registry = client
        device = Device(name="Maint-Device", model="Bitaxe", ip="192.168.1.200", status=DeviceStatus.ONLINE)
        registry.add_device(device)

        response = flask_client.post(
            f"/api/devices/{device.id}/maintenance",
            json={"notes": "cleaned fans"},
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "type is required" in data["error"].lower()

    def test_post_and_get_maintenance(self, client):
        flask_client, registry = client
        device = Device(name="Maint-Device", model="Bitaxe", ip="192.168.1.200", status=DeviceStatus.ONLINE)
        registry.add_device(device)

        post_response = flask_client.post(
            f"/api/devices/{device.id}/maintenance",
            json={
                "type": "cleaning",
                "notes": "cleaned fans and heatsink",
                "performed_by": "technician A",
            },
        )
        assert post_response.status_code == 201
        post_data = post_response.get_json()
        assert post_data["success"] is True
        assert post_data["record"]["type"] == "cleaning"
        assert post_data["record"]["notes"] == "cleaned fans and heatsink"
        assert post_data["record"]["performed_by"] == "technician A"

        get_response = flask_client.get(f"/api/devices/{device.id}/maintenance")
        assert get_response.status_code == 200
        get_data = get_response.get_json()
        assert get_data["success"] is True
        assert len(get_data["records"]) == 1
        assert get_data["records"][0]["type"] == "cleaning"
