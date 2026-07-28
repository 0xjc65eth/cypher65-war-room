"""Tests for core/registry/device_registry.py."""
import pytest

from core.registry.device_registry import DeviceRegistry
from core.models.device import Device, DeviceStatus


@pytest.fixture
def registry(tmp_path):
    db_path = tmp_path / "test_devices.sqlite"
    return DeviceRegistry(str(db_path))


class TestDeviceRegistry:
    def test_add_and_get_device(self, registry):
        device = Device(name="Test Miner", model="Bitaxe Max", ip="192.168.1.50")
        registry.add_device(device)

        retrieved = registry.get_device(device.id)
        assert retrieved is not None
        assert retrieved.name == "Test Miner"
        assert retrieved.model == "Bitaxe Max"
        assert retrieved.ip == "192.168.1.50"

    def test_list_devices(self, registry):
        registry.add_device(Device(name="A", model="Bitaxe"))
        registry.add_device(Device(name="B", model="Bitaxe"))

        devices = registry.list_devices()
        assert len(devices) == 2
        assert {d.name for d in devices} == {"A", "B"}

    def test_update_device(self, registry):
        device = Device(name="Old Name", model="Bitaxe")
        registry.add_device(device)

        device.name = "New Name"
        device.status = DeviceStatus.ONLINE
        registry.update_device(device)

        retrieved = registry.get_device(device.id)
        assert retrieved.name == "New Name"
        assert retrieved.status == DeviceStatus.ONLINE

    def test_count_by_status(self, registry):
        d1 = Device(name="online", model="Bitaxe")
        d1.status = DeviceStatus.ONLINE
        d2 = Device(name="offline", model="Bitaxe")
        d2.status = DeviceStatus.OFFLINE
        d3 = Device(name="warning", model="Bitaxe")
        d3.status = DeviceStatus.WARNING

        registry.add_device(d1)
        registry.add_device(d2)
        registry.add_device(d3)

        counts = registry.count_by_status()
        assert counts["online"] == 1
        assert counts["offline"] == 1
        assert counts["warning"] == 1

    def test_load_from_db_persists_state(self, tmp_path):
        db_path = tmp_path / "persist.sqlite"
        registry = DeviceRegistry(str(db_path))
        device = Device(name="Persistent", model="Bitaxe")
        registry.add_device(device)

        # Fresh registry instance pointing to the same DB
        new_registry = DeviceRegistry(str(db_path))
        new_registry.load_from_db()

        assert len(new_registry.list_devices()) == 1
        assert new_registry.get_device(device.id).name == "Persistent"
