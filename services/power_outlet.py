"""
CYPHER65 // POWER OUTLET ADAPTER — Abstract Interface
=====================================================
Interface for controlling smart power outlets (plugs) from any vendor.
Currently implemented adapters:
  - TuyaCloudAdapter (services/tuya_adapter.py)

Design: each adapter is stateless — credentials/device mapping is passed
at method call time from the caller (which reads from settings DB).
"""


class PowerOutletAdapter:
    """Abstract interface for smart plug control.

    All methods accept **kwargs so concrete implementations can add
    vendor-specific parameters (region, uid, home_id, etc.) without
    changing the interface.
    """

    def list_devices(self, **kwargs) -> list[dict]:
        """List all power outlets accessible through this adapter.

        Returns:
            list of dict, each with at least:
              - id (str): device ID
              - name (str): human-friendly name
              - online (bool): whether the device is reachable
              - state (bool or None): current power state (True=on, False=off)
              - vendor (str): e.g. "tuya"
        """
        raise NotImplementedError

    def get_status(self, device_id: str, **kwargs) -> dict:
        """Get current status of a single outlet.

        Returns:
            dict with at least:
              - device_id (str)
              - online (bool)
              - state (bool)
              - power_watts (float or None): current power consumption
        """
        raise NotImplementedError

    def power_on(self, device_id: str, **kwargs) -> dict:
        """Turn the outlet on.

        Returns:
            dict with 'success': bool and optional 'error' key.
        """
        raise NotImplementedError

    def power_off(self, device_id: str, **kwargs) -> dict:
        """Turn the outlet off.

        Returns:
            dict with 'success': bool and optional 'error' key.
        """
        raise NotImplementedError

    def toggle(self, device_id: str, **kwargs) -> dict:
        """Toggle the outlet state (on→off, off→on).

        Returns:
            dict with 'success': bool, 'new_state': bool, and optional 'error'.
        """
        raise NotImplementedError

    def validate_credentials(self, **kwargs) -> dict:
        """Test that the stored credentials are valid by making a lightweight
        API call (e.g. list first device or check token validity).

        Returns:
            dict with 'valid': bool and optional 'error', 'account' fields.
        """
        raise NotImplementedError
