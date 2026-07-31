"""
Unit tests for services/power_outlet.py

Tests cover:
  - Abstract interface cannot be instantiated directly
  - All methods raise NotImplementedError
  - Concrete subclass implements all methods correctly
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from services.power_outlet import PowerOutletAdapter


class TestPowerOutletInterface:
    """Tests for the abstract PowerOutletAdapter interface."""

    def test_interface_cannot_list_devices(self):
        """Calling list_devices on abstract class raises NotImplementedError."""
        class IncompleteAdapter(PowerOutletAdapter):
            pass
        adapter = IncompleteAdapter()
        with pytest.raises(NotImplementedError):
            adapter.list_devices()

    def test_interface_cannot_get_status(self):
        """Calling get_status on abstract class raises NotImplementedError."""
        class IncompleteAdapter(PowerOutletAdapter):
            pass
        adapter = IncompleteAdapter()
        with pytest.raises(NotImplementedError):
            adapter.get_status("plug1")

    def test_interface_cannot_power_on(self):
        """Calling power_on on abstract class raises NotImplementedError."""
        class IncompleteAdapter(PowerOutletAdapter):
            pass
        adapter = IncompleteAdapter()
        with pytest.raises(NotImplementedError):
            adapter.power_on("plug1")

    def test_interface_cannot_power_off(self):
        """Calling power_off on abstract class raises NotImplementedError."""
        class IncompleteAdapter(PowerOutletAdapter):
            pass
        adapter = IncompleteAdapter()
        with pytest.raises(NotImplementedError):
            adapter.power_off("plug1")

    def test_interface_cannot_toggle(self):
        """Calling toggle on abstract class raises NotImplementedError."""
        class IncompleteAdapter(PowerOutletAdapter):
            pass
        adapter = IncompleteAdapter()
        with pytest.raises(NotImplementedError):
            adapter.toggle("plug1")

    def test_interface_cannot_validate(self):
        """Calling validate_credentials on abstract class raises NotImplementedError."""
        class IncompleteAdapter(PowerOutletAdapter):
            pass
        adapter = IncompleteAdapter()
        with pytest.raises(NotImplementedError):
            adapter.validate_credentials()


class TestConcreteImplementation:
    """Test that a concrete implementation of PowerOutletAdapter works."""

    def test_concrete_implements_all_methods(self):
        """A fully implemented adapter should work without errors."""
        class TesterAdapter(PowerOutletAdapter):
            def list_devices(self, **kwargs):
                return [{"id": "test", "name": "Test Plug", "online": True, "state": False, "vendor": "test"}]

            def get_status(self, device_id, **kwargs):
                return {"success": True, "device_id": device_id, "state": False, "online": True, "power_watts": None}

            def power_on(self, device_id, **kwargs):
                return {"success": True, "new_state": True}

            def power_off(self, device_id, **kwargs):
                return {"success": True, "new_state": False}

            def toggle(self, device_id, **kwargs):
                return {"success": True, "new_state": True}

            def validate_credentials(self, **kwargs):
                return {"valid": True, "uid": "test_user"}

        adapter = TesterAdapter()
        devices = adapter.list_devices()
        assert len(devices) == 1
        assert devices[0]["vendor"] == "test"

        status = adapter.get_status("test")
        assert status["state"] is False

        assert adapter.power_on("test")["success"] is True
        assert adapter.power_off("test")["new_state"] is False
        assert adapter.toggle("test")["new_state"] is True
        assert adapter.validate_credentials()["valid"] is True


class TestConcreteKwargsPassthrough:
    """Test that kwargs are properly passed through the interface."""

    def test_kwargs_received(self):
        """kwargs dict should be received by implementation methods."""
        class KwargsCatcher(PowerOutletAdapter):
            def __init__(self):
                self.received_kwargs = None

            def list_devices(self, **kwargs):
                self.received_kwargs = kwargs
                return []

            def get_status(self, device_id, **kwargs):
                self.received_kwargs = kwargs
                return {"success": True, "device_id": device_id, "state": False, "online": True, "power_watts": None}

            def power_on(self, device_id, **kwargs):
                self.received_kwargs = kwargs
                return {"success": True, "new_state": True}

            def power_off(self, device_id, **kwargs):
                self.received_kwargs = kwargs
                return {"success": True, "new_state": False}

            def toggle(self, device_id, **kwargs):
                self.received_kwargs = kwargs
                return {"success": True, "new_state": True}

            def validate_credentials(self, **kwargs):
                self.received_kwargs = kwargs
                return {"valid": True}

        adapter = KwargsCatcher()
        adapter.list_devices(access_id="abc", region="us")
        assert adapter.received_kwargs == {"access_id": "abc", "region": "us"}

        adapter.power_on("plug1", access_id="abc")
        assert adapter.received_kwargs == {"access_id": "abc"}
