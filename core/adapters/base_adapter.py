from abc import ABC, abstractmethod
import json
import logging
import socket
from typing import Any, Dict, List, Optional

from core.models.device import Device
from core.models.capability import Capability

log = logging.getLogger(__name__)


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

    def _send_cgminer_command(self, command: str, port: int, timeout: int = 5) -> Optional[dict]:
        """Send a JSON command over TCP to a cgminer-compatible API.

        Shared by CgminerAdapter and BraiinsAdapter. Returns parsed JSON
        or ``None`` on any failure (connection refused, timeout, bad JSON).

        Subclasses wrap this with their own logging.
        """
        host = getattr(self, 'host', None)
        if not host:
            return None
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((host, port))
            payload = json.dumps({"command": command}) + "\n"
            sock.send(payload.encode())
            data = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b"\x00" in chunk:
                    break
            text = data.decode(errors="replace").rstrip("\x00").strip()
            if text:
                return json.loads(text)
        except (socket.timeout, ConnectionRefusedError, OSError, json.JSONDecodeError):
            return None
        finally:
            if sock:
                sock.close()
        return None

    @staticmethod
    def _derive_cgminer_pool_status(pools_response: dict):
        """Derive (pool_status, pool_url, pool_user) from a cgminer 'pools' response.

        Shared by CgminerAdapter and BraiinsAdapter. Scans the POOLS list
        for the first "Alive" entry (CONNECTED) or falls back to the first
        configured pool (DISCONNECTED). Returns (None, "", "") when the
        response is empty or malformed.
        """
        pool_status = None
        pool_url = ""
        pool_user = ""
        if pools_response and "POOLS" in pools_response:
            pool_list = pools_response["POOLS"]
            if isinstance(pool_list, list):
                alive = [p for p in pool_list
                         if str(p.get("Status", "")).lower() == "alive"]
                if alive:
                    pool_status = "CONNECTED"
                    pool_url = str(alive[0].get("URL", ""))
                    pool_user = str(alive[0].get("User", ""))
                elif pool_list:
                    pool_status = "DISCONNECTED"
                    pool_url = str(pool_list[0].get("URL", ""))
                    pool_user = str(pool_list[0].get("User", ""))
                else:
                    pool_status = "NOT CONFIGURED"
        return pool_status, pool_url, pool_user
