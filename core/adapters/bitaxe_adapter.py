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
                (
                    data.get("hashRate")
                    if data.get("hashRate") is not None
                    else data.get("hashrate")
                ),
                float,
                0,
            )
            # Fase 5 · janelas de hashrate (AxeOS / ESP-Miner): hashRate1m,
            # hashRate10m, hashRate1hr. Sem valor → None (a serialização
            # preenche NOT AVAILABLE). NOTA: hashRate5m NÃO é promovido a
            # hashRate10m — Honest Telemetry: um janela de 5m não é 10m.
            hashrate_1m = self._safe_number(data.get("hashRate1m"), float, None)
            hashrate_10m = self._safe_number(data.get("hashRate10m"), float, None)
            hashrate_1h = self._safe_number(
                (
                    data.get("hashRate1hr")
                    if data.get("hashRate1hr") is not None
                    else data.get("hashRate1h")
                ),
                float,
                None,
            )
            temperature = self._safe_number(
                (
                    data.get("temp")
                    if data.get("temp") is not None
                    else data.get("temperature")
                ),
                float,
                0,
            )
            temperature_2 = self._safe_number(data.get("temp2"), float, 0)
            vr_temp = self._safe_number(data.get("vrTemp"), float, 0)
            # Fase 5 · chip_temp = temperatura do ASIC (temp principal)
            chip_temp = self._safe_number(
                (
                    data.get("tempChip")
                    if data.get("tempChip") is not None
                    else temperature
                ),
                float,
                None,
            )
            voltage = self._safe_number(
                (
                    data.get("voltage")
                    if data.get("voltage") is not None
                    else data.get("coreVoltage")
                ),
                float,
                0,
            )
            core_voltage_actual = self._safe_number(
                data.get("coreVoltageActual"), float, 0
            )
            frequency = self._safe_number(
                (
                    data.get("frequency")
                    if data.get("frequency") is not None
                    else data.get("actualFrequency")
                ),
                float,
                0,
            )
            fan_speed = self._safe_number(
                (
                    data.get("fanspeed")
                    if data.get("fanspeed") is not None
                    else data.get("fanSpeed")
                ),
                float,
                0,
            )
            fan_rpm = self._safe_number(data.get("fanrpm"), float, 0)
            fan_rpm_2 = self._safe_number(data.get("fan2rpm"), float, 0)
            power = self._safe_number(data.get("power"), float, 0)
            max_power = self._safe_number(data.get("maxPower"), float, 0)
            uptime = self._safe_number(
                (
                    data.get("uptimeSeconds")
                    if data.get("uptimeSeconds") is not None
                    else data.get("uptime")
                ),
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
            best_session_diff = (
                str(best_session_diff_val) if best_session_diff_val is not None else ""
            )

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
            # Fase 5 · pool status derivado (CONNECTED / PAUSED / NOT CONFIGURED)
            if mining_paused:
                pool_status = "PAUSED"
            elif pool_url:
                pool_status = "CONNECTED"
            else:
                pool_status = "NOT CONFIGURED"

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
                "hashrate_1m": hashrate_1m,
                "hashrate_10m": hashrate_10m,
                "hashrate_1h": hashrate_1h,
                "temperature": temperature,
                "temperature_2": temperature_2,
                "chip_temp": chip_temp,
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
                "pool_status": pool_status,
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

    def execute_command(
        self, command: str, parameters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if not self.supports(command):
            return {"success": False, "error": "Command not supported by this device"}

        if not self.api_url:
            return {"success": False, "error": "Device has no API URL configured"}

        parameters = parameters or {}

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
        elif command == "pause":
            # ESP-Miner: POST /api/system/miningPause (empty body)
            return self._post_command("miningPause", command)
        elif command == "resume":
            # ESP-Miner: POST /api/system/miningResume (empty body)
            return self._post_command("miningResume", command)
        elif command == "set_frequency":
            # ESP-Miner: POST /api/system/overclock with JSON body.
            # Allowed fields: frequency (MHz), voltage (mV), coreVoltage (mV),
            # powerLimit (W), autotune (bool). Only known keys are forwarded
            # (never echo arbitrary caller keys to the device).
            body = {}
            freq = self._safe_number(parameters.get("frequency"), float, None)
            if freq is not None:
                # Sanity clamps: 100–2000 MHz (Honest Telemetry — refuse
                # absurd values instead of bricking the ASIC).
                body["frequency"] = int(max(100.0, min(2000.0, freq)))
            volt = self._safe_number(
                parameters.get("voltage", parameters.get("coreVoltage")),
                float,
                None,
            )
            if volt is not None:
                # Sanity clamps: 1000–1600 mV.
                body["coreVoltage"] = int(max(1000.0, min(1600.0, volt)))
            power = self._safe_number(parameters.get("powerLimit"), float, None)
            if power is not None:
                body["powerLimit"] = int(max(1.0, min(300.0, power)))
            autotune = parameters.get("autotune")
            if isinstance(autotune, bool):
                body["autotune"] = autotune
            if not body:
                return {
                    "success": False,
                    "command": command,
                    "device_id": self.device.id,
                    "error": "set_frequency requires at least one of: frequency, voltage/coreVoltage, powerLimit, autotune",
                }
            return self._post_command("overclock", command, body=body)
        elif command == "update_pool":
            # ESP-Miner: POST /api/system/updatePool {stratumURL, stratumPort, stratumUser}
            body = {}
            url = str(parameters.get("stratumURL") or "").strip()
            port = self._safe_number(parameters.get("stratumPort"), int, None)
            user = str(parameters.get("stratumUser") or "").strip()
            if url:
                body["stratumURL"] = url
            if port is not None:
                body["stratumPort"] = int(max(1, min(65535, port)))
            if user:
                body["stratumUser"] = user
            if not body:
                return {
                    "success": False,
                    "command": command,
                    "device_id": self.device.id,
                    "error": "update_pool requires at least one of: stratumURL, stratumPort, stratumUser",
                }
            return self._post_command("updatePool", command, body=body)

        # Unknown but "supported" command — honest failure, not a silent stub.
        return {
            "success": False,
            "stub": False,
            "command": command,
            "device_id": self.device.id,
            "error": f"command '{command}' has no implementation on BitaxeAdapter",
        }

    def _post_command(
        self, endpoint: str, command_name: str, body: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """POST to a Bitaxe /api/system/{endpoint} endpoint.

        ``body`` (optional dict) is sent as JSON when present — used by
        overclock / updatePool / setPassword which require a payload.
        """
        try:
            url = f"{self.api_url}/api/system/{endpoint}"
            if body:
                response = requests.post(url, json=body, timeout=5)
            else:
                response = requests.post(url, timeout=5)
            status_code = response.status_code
            response.raise_for_status()
            return {
                "success": True,
                "stub": False,
                "command": command_name,
                "device_id": self.device.id,
                "status_code": status_code,
                "parameters": body or None,
            }
        except requests.RequestException as exc:
            return {
                "success": False,
                "command": command_name,
                "device_id": self.device.id,
                "error": str(exc),
                "status_code": getattr(
                    getattr(exc, "response", None), "status_code", None
                ),
            }

    def get_capabilities(self) -> List[Capability]:
        return [
            Capability(name="telemetry", supported=True),
            Capability(
                name="restart",
                supported=True,
                requires_confirmation=True,
                risk_level=RiskLevel.MEDIUM,
            ),
            Capability(name="identify", supported=True),
            Capability(
                name="pause",
                supported=True,
                requires_confirmation=True,
                risk_level=RiskLevel.MEDIUM,
            ),
            Capability(
                name="resume",
                supported=True,
                requires_confirmation=True,
                risk_level=RiskLevel.MEDIUM,
            ),
            Capability(
                name="set_frequency",
                supported=True,
                requires_confirmation=True,
                risk_level=RiskLevel.HIGH,
            ),
            Capability(
                name="update_pool",
                supported=True,
                requires_confirmation=True,
                risk_level=RiskLevel.HIGH,
            ),
            Capability(name="logs", supported=True),
        ]

    def health_check(self) -> Dict[str, Any]:
        """Not implemented: use get_telemetry() for health data."""
        return {
            "status": self.device.status.value,
            "reachable": bool(self.api_url),
            "stub": True,
            "note": "health_check is not yet implemented for BitaxeAdapter; use get_telemetry()",
        }
