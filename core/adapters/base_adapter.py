from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from core.models.device import Device
from core.models.capability import Capability


class BaseAdapter(ABC):
    """
    Interface base para todos os adapters de dispositivos.
    Todo adapter concreto (Bitaxe, NerdQaxe, Braiins, etc.) deve herdar desta classe.
    """

    def __init__(self, device: Device):
        self.device = device

    @abstractmethod
    def get_telemetry(self) -> Optional[Dict[str, Any]]:
        """Retorna telemetria atual do dispositivo"""
        pass

    @abstractmethod
    def execute_command(self, command: str, parameters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Executa um comando no dispositivo"""
        pass

    @abstractmethod
    def get_capabilities(self) -> List[Capability]:
        """Retorna lista de capabilities suportadas por este device"""
        pass

    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        """Verifica saúde do dispositivo"""
        pass

    @staticmethod
    def _safe_number(value, type_cast=float, default=None):
        """Coerce a raw value (often a string from device APIs) to a number.

        Shared by all adapters. Returns *default* when the value is ``None``
        or cannot be coerced — callers that need a different sentinel pass
        it explicitly.
        """
        try:
            return type_cast(value) if value is not None else default
        except (ValueError, TypeError):
            return default

    def supports(self, capability_name: str) -> bool:
        """Verifica se o device suporta uma capability específica.

        Falls back to the adapter's own capability list when the device has
        no capabilities assigned (e.g. loaded from a legacy DB row).
        """
        if self.device.has_capability(capability_name):
            return True
        # Fallback: device may have been loaded without capability metadata.
        return any(
            c.name == capability_name and c.supported
            for c in self.get_capabilities()
        )
