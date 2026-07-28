"""
core/adapters/__init__.py
Factory for selecting the right device adapter based on device model/manufacturer.
"""
from core.adapters.base_adapter import BaseAdapter
from core.models.device import Device


def get_adapter(device: Device) -> BaseAdapter:
    """Return the appropriate adapter for a given device.

    Currently supports:
      - Bitaxe / ESP-Miner devices (any model containing "bitaxe" or "axe")

    Raises NotImplementedError for unsupported devices until more adapters exist.
    """
    # Lazy import avoids circular imports while the package is being loaded.
    from core.adapters.bitaxe_adapter import BitaxeAdapter

    model = (device.model or "").lower()
    name = (device.name or "").lower()
    if "bitaxe" in model or "bitaxe" in name or "axe" in model or "esp-miner" in model:
        return BitaxeAdapter(device)
    raise NotImplementedError(
        f"No adapter available for device {device.id} (model='{device.model}', name='{device.name}'). "
        "Only Bitaxe/ESP-Miner devices are currently supported."
    )
