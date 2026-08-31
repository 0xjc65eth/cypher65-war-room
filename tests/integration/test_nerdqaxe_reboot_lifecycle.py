"""Network integration: CYPHER65 reboot lifecycle against virtual NerdQaxe."""

import time

from core.adapters.bitaxe_adapter import BitaxeAdapter
from core.models.capability import Capability
from core.models.device import Device, DeviceStatus
from services import operation_ledger
from services.tenant import recent_audit_logs
from tests.virtual_hardware.nerdqaxe import VirtualNerdQaxe


def test_nerdqaxe_reboot_ack_offline_reconnect_uptime_verified(monkeypatch, tmp_path):
    import app as app_module
    import routes.device_control as device_control

    monkeypatch.setenv("DB_PATH", str(tmp_path / "war-room.sqlite"))
    app_module.init_db()
    monkeypatch.setenv("ENABLE_PHYSICAL_COMMANDS", "true")
    monkeypatch.setattr(device_control, "_safety", None)
    monkeypatch.setattr(device_control, "_record_cb", app_module._record_command)

    with VirtualNerdQaxe(uptime_seconds=7200) as virtual:
        device = Device(
            name="Virtual NerdQaxe",
            model="NerdQaxe++",
            firmware="axeos",
            ip=virtual.address,
            status=DeviceStatus.ONLINE,
            capabilities=[
                Capability(name="restart", supported=True, requires_confirmation=True)
            ],
        )
        adapter = BitaxeAdapter(device, api_url=f"http://{virtual.address}")
        before = adapter.get_telemetry()
        assert before and before["uptime"] == 7200
        device.current_telemetry = before

        class Registry:
            def __init__(self, current_device):
                self.device = current_device

            def get_device(self, device_id, tenant_id=""):
                return (
                    self.device if self.device and device_id == self.device.id else None
                )

        registry = Registry(device)
        monkeypatch.setattr(device_control, "_registry", registry)
        client = app_module.app.test_client()

        prepared = client.post(
            f"/api/devices/{device.id}/command/confirmation",
            json={"command": "restart", "confirmation": "CONFIRM RESTART"},
        )
        assert prepared.status_code == 201

        dispatched = client.post(
            f"/api/devices/{device.id}/command",
            headers={"Idempotency-Key": "android-reboot-1"},
            json={
                "command": "restart",
                "dry_run": False,
                "confirmation_token": prepared.get_json()["confirmation_token"],
            },
        )
        assert dispatched.status_code == 200
        ack = dispatched.get_json()
        assert ack["ack"]["state"] == "acknowledged"
        assert ack["reconciliation"]["state"] == "pending"
        assert virtual.restart_count == 1

        # A reboot can temporarily evict the device from a mutable registry.
        # A lost-response replay must still resolve from the durable operation.
        registry.device = None
        replay = client.post(
            f"/api/devices/{device.id}/command",
            headers={"Idempotency-Key": "android-reboot-1"},
            json={
                "command": "restart",
                "dry_run": False,
                "confirmation_token": prepared.get_json()["confirmation_token"],
            },
        ).get_json()
        assert replay["duplicate"] is True
        assert replay["operation_id"] == ack["operation_id"]
        assert virtual.restart_count == 1
        registry.device = device

        second_confirmation = client.post(
            f"/api/devices/{device.id}/command/confirmation",
            json={"command": "restart", "confirmation": "CONFIRM RESTART"},
        ).get_json()["confirmation_token"]
        duplicate = client.post(
            f"/api/devices/{device.id}/command",
            headers={"Idempotency-Key": "android-reboot-1"},
            json={
                "command": "restart",
                "dry_run": False,
                "confirmation_token": second_confirmation,
            },
        ).get_json()
        assert duplicate["duplicate"] is True
        assert duplicate["operation_id"] == ack["operation_id"]
        assert virtual.restart_count == 1

        # The production adapter independently observes the network outage.
        assert adapter.get_telemetry() is None
        device.status = DeviceStatus.OFFLINE
        device.current_telemetry = {
            "timestamp": int(
                operation_ledger.get_operation(ack["operation_id"])["ack_at"]
            )
            + 1,
            "uptime_seconds": 7200,
        }
        offline = client.get(
            f"/api/devices/{device.id}/commands/{ack['operation_id']}"
        ).get_json()
        assert offline["phase"] == "offline"
        assert offline["reconciliation"]["state"] == "pending"

        # A later real HTTP poll observes reconnection and the reset uptime.
        after = adapter.get_telemetry()
        assert after and after["uptime"] == 3
        after["timestamp"] = int(time.time()) + 1
        device.status = DeviceStatus.ONLINE
        device.current_telemetry = after
        verified = client.get(
            f"/api/devices/{device.id}/commands/{ack['operation_id']}"
        ).get_json()

        assert verified["success"] is True
        assert verified["phase"] == "verified"
        assert verified["reconciliation"]["state"] == "confirmed"
        assert verified["observed"]["uptime_seconds"] == 3
        stored = operation_ledger.get_operation(ack["operation_id"])
        assert stored["state"] == "reconciled"
        assert stored["safe_result"]["reboot_evidence"]["offline_seen"] is True
        reconciled_audit = next(
            row
            for row in recent_audit_logs("default")
            if row["details"].get("operation_id") == ack["operation_id"]
            and row["details"].get("reconciliation_state") == "confirmed"
        )
        assert reconciled_audit["target"] == device.id
        assert reconciled_audit["details"]["command"] == "restart"

        registry.device = None
        completed_replay = client.post(
            f"/api/devices/{device.id}/command",
            headers={"Idempotency-Key": "android-reboot-1"},
            json={
                "command": "restart",
                "dry_run": False,
                "confirmation_token": prepared.get_json()["confirmation_token"],
            },
        ).get_json()
        assert completed_replay["duplicate"] is True
        assert completed_replay["phase"] == "verified"
        assert completed_replay["reconciliation"]["state"] == "confirmed"
        assert completed_replay["audit"]["state"] == "recorded"
        assert virtual.restart_count == 1
