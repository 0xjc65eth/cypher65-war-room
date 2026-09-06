"""Automation must call adapter.execute_command(command, parameters)."""

from unittest.mock import MagicMock

from core.models.device import Device, DeviceStatus


def test_automation_callback_uses_adapter_arity(monkeypatch):
    monkeypatch.setenv("ENABLE_PHYSICAL_COMMANDS", "true")
    monkeypatch.setenv("ENABLE_AUTONOMOUS_COMMANDS", "true")

    import app as app_module

    device = Device(
        id="auto-1",
        name="Bitaxe",
        model="Bitaxe Max",
        status=DeviceStatus.ONLINE,
    )
    device.current_telemetry = {"temperature": 50, "hashrate": 5e12}
    monkeypatch.setattr(app_module._core_registry, "get_device", lambda _id: device)
    monkeypatch.setattr(
        app_module._core_registry, "update_device", lambda *a, **k: None
    )

    adapter = MagicMock()
    adapter.supports.return_value = True
    adapter.execute_command.return_value = {"success": True}
    monkeypatch.setattr(app_module, "get_adapter", lambda _device: adapter)
    monkeypatch.setattr(app_module, "_record_command", lambda *a, **k: None)

    result = app_module._execute_command_for_automation("auto-1", "restart", {})

    assert result["success"] is True
    adapter.execute_command.assert_called_once_with("restart", {})
