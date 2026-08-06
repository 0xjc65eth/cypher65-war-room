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
      - Braiins OS+ devices (model/firmware containing "braiins" or "bosminer")
      - cgminer protocol devices (fallback)

    Raises NotImplementedError for unsupported devices until more adapters exist.
    """
    # Lazy import avoids circular imports while the package is being loaded.
    from core.adapters.bitaxe_adapter import BitaxeAdapter
    from core.adapters.braiins_adapter import BraiinsAdapter
    from core.adapters.cgminer_adapter import CgminerAdapter

    model = (device.model or "").lower()
    name = (device.name or "").lower()
    firmware = (device.firmware or "").lower()

    # AxeOS / ESP-Miner → BitaxeAdapter
    if "bitaxe" in model or "bitaxe" in name or "axe" in model or "esp-miner" in model:
        return BitaxeAdapter(device)

    # Braiins OS+ → BraiinsAdapter
    if "braiins" in firmware or "braiins" in model \
       or "bosminer" in firmware or "bosminer" in model:
        return BraiinsAdapter(device)

    # cgminer protocol → CgminerAdapter (catch-all for Antminer, Whatsminer, etc.)
    if "antminer" in model or "whatsminer" in model or "avalon" in model \
       or "cgminer" in firmware or "bmminer" in firmware:
        return CgminerAdapter(device)

    raise NotImplementedError(
        f"No adapter available for device {device.id} (model='{device.model}', name='{device.name}'). "
        "Supported: Bitaxe/ESP-Miner, Braiins OS+, cgminer (Antminer/Whatsminer/Avalon)."
    )
