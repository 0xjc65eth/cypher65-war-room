import json
import logging
import time
from typing import Any, Dict, List, Optional

import requests

from core.adapters.base_adapter import BaseAdapter

log = logging.getLogger(__name__)
from core.models.device import Device, DeviceStatus
from core.models.capability import Capability, RiskLevel


class BitaxeAdapter(BaseAdapter):
    """
    Adapter para dispositivos Bitaxe / ESP-Miner.
    Implementação inicial com suporte básico.
    """

    def __init__(self, device: Device, api_url: Optional[str] = None):
        super().__init__(device)
        self.api_url = api_url or (f"http://{device.ip}" if device.ip else None)

    @staticmethod
    def _safe_number(value, type_cast=float, default=0):
        try:
            return type_cast(value) if value is not None else default
        except (ValueError, TypeError):
            return default

    def get_telemetry(self) -> Optional[Dict[str, Any]]:
        """
        Fetch telemetry from the device at /api/system/info.
        Returns a normalized dict or None when the device is unreachable.
        """
        if not self.api_url:
            return None

        url = f"{self.api_url}/api/system/info"
        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            data = response.json()

            collected_at = int(time.time())

            # Core metrics with multiple field-name fallbacks for compatibility
            hashrate = self._safe_number(
                data.get("hashRate")
                if data.get("hashRate") is not None
                else data.get("hashrate"),
                float,
                0,
            )
            temperature = self._safe_number(
                data.get("temp")
                if data.get("temp") is not None
                else data.get("temperature"),
                float,
                0,
            )
            temperature_2 = self._safe_number(data.get("temp2"), float, 0)
            vr_temp = self._safe_number(data.get("vrTemp"), float, 0)
            voltage = self._safe_number(
                data.get("voltage")
                if data.get("voltage") is not None
                else data.get("coreVoltage"),
                float,
                0,
            )
            core_voltage_actual = self._safe_number(data.get("coreVoltageActual"), float, 0)
            frequency = self._safe_number(
                data.get("frequency")
                if data.get("frequency") is not None
                else data.get("actualFrequency"),
                float,
                0,
            )
            fan_speed = self._safe_number(
                data.get("fanspeed")
                if data.get("fanspeed") is not None
                else data.get("fanSpeed"),
                float,
                0,
            )
            fan_rpm = self._safe_number(data.get("fanrpm"), float, 0)
            fan_rpm_2 = self._safe_number(data.get("fan2rpm"), float, 0)
            power = self._safe_number(data.get("power"), float, 0)
            max_power = self._safe_number(data.get("maxPower"), float, 0)
            uptime = self._safe_number(
                data.get("uptimeSeconds")
                if data.get("uptimeSeconds") is not None
                else data.get("uptime"),
                int,
                0,
            )
            best_diff_val = data.get("bestDiff")
            if best_diff_val is None:
                best_diff_val = data.get("bestDifficulty")
            best_diff = str(best_diff_val) if best_diff_val is not None else ""

            best_session_diff_val = data.get("bestSessionDiff")
            if best_session_diff_val is None:
                best_session_diff_val = data.get("bestSessionDifficulty")
            best_session_diff = str(best_session_diff_val) if best_session_diff_val is not None else ""

            # Shares
            accepted_shares = self._safe_number(data.get("sharesAccepted"), int, 0)
            rejected_shares = self._safe_number(data.get("sharesRejected"), int, 0)
            stale_value = data.get("sharesStale")
            if stale_value is None:
                stale_value = data.get("staleShares")
            stale_shares = self._safe_number(stale_value, int, 0)
            pool_difficulty = self._safe_number(data.get("poolDifficulty"), float, 0)
            mining_paused = bool(data.get("miningPaused"))

            # Pool / worker identity
            pool_url = str(data.get("stratumURL") or data.get("poolURL") or "")
            pool_port = self._safe_number(data.get("stratumPort"), int, 0)
            pool_user = str(data.get("stratumUser") or "")
            worker = str(data.get("stratumUser") or data.get("worker") or "")
            hostname = str(data.get("hostname") or "")
            wifi_rssi = self._safe_number(data.get("wifiRSSI"), int, 0)

            # Build pool/worker summary objects
            pool = {
                "url": pool_url,
                "port": pool_port,
                "user": pool_user,
            }

            return {
                # Quality / traceability fields
                "source": "bitaxe_adapter",
                "timestamp": collected_at,
                "freshness": 0,
                # Core telemetry
                "hashrate": hashrate,
                "temperature": temperature,
                "temperature_2": temperature_2,
                "vr_temp": vr_temp,
                "voltage": voltage,
                "core_voltage_actual": core_voltage_actual,
                "frequency": frequency,
                "fan_speed": fan_speed,
                "fan_rpm": fan_rpm,
                "fan_rpm_2": fan_rpm_2,
                "power": power,
                "max_power": max_power,
                "uptime": uptime,
                "best_difficulty": best_diff,
                "best_session_difficulty": best_session_diff,
                "accepted_shares": accepted_shares,
                "rejected_shares": rejected_shares,
                "stale_shares": stale_shares,
                "pool_difficulty": pool_difficulty,
                "mining_paused": mining_paused,
                # Pool / worker
                "pool": pool,
                "worker": worker,
                "hostname": hostname,
                "wifi_rssi": wifi_rssi,
                "stub": False,
            }
        except requests.RequestException as exc:
            # Device is unreachable or returned an HTTP error.
            return None
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            # Parsing error: log for debugging but treat as offline.
            log.warning("[bitaxe telemetry] parse error for %s: %s", self.api_url, exc)
            return None

    def execute_command(self, command: str, parameters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.supports(command):
            return {"success": False, "error": "Command not supported by this device"}

        if not self.api_url:
            return {"success": False, "error": "Device has no API URL configured"}

        if command == "restart":
            return self._post_command("restart", command)
        elif command == "identify":
            # Try the common identify/blink endpoint; fall back gracefully if unsupported.
            result = self._post_command("blink", command)
            if not result.get("success") and result.get("status_code") == 404:
                return {
                    "success": False,
                    "stub": False,
                    "command": command,
                    "device_id": self.device.id,
                    "note": "identify endpoint not available on this firmware",
                }
            return result

        # Real execution is not implemented yet; this is a deliberate stub.
        return {
            "success": False,
            "stub": True,
            "command": command,
            "device_id": self.device.id,
            "note": "execute_command is not yet implemented for this command on BitaxeAdapter",
        }

    def _post_command(self, endpoint: str, command_name: str) -> Dict[str, Any]:
        """POST to a Bitaxe /api/system/{endpoint} endpoint."""
        try:
            url = f"{self.api_url}/api/system/{endpoint}"
            response = requests.post(url, timeout=5)
            status_code = response.status_code
            response.raise_for_status()
            return {
                "success": True,
                "stub": False,
                "command": command_name,
                "device_id": self.device.id,
                "status_code": status_code,
            }
        except requests.RequestException as exc:
            return {
                "success": False,
                "command": command_name,
                "device_id": self.device.id,
                "error": str(exc),
                "status_code": getattr(getattr(exc, "response", None), "status_code", None),
            }

    def get_capabilities(self) -> List[Capability]:
        return [
            Capability(name="telemetry", supported=True),
            Capability(name="restart", supported=True, requires_confirmation=True, risk_level=RiskLevel.MEDIUM),
            Capability(name="identify", supported=True),
            Capability(name="logs", supported=True),
            Capability(name="set_frequency", supported=False, requires_confirmation=True, risk_level=RiskLevel.HIGH),
        ]

    def health_check(self) -> Dict[str, Any]:
        """Not implemented: use get_telemetry() for health data."""
        return {
            "status": self.device.status.value,
            "reachable": bool(self.api_url),
            "stub": True,
            "note": "health_check is not yet implemented for BitaxeAdapter; use get_telemetry()",
        }
