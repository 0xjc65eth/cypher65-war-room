"""
CYPHER65 // CgMiner Adapter
============================
Adapter for ASICs using the classic cgminer/BMMiner JSON-over-TCP protocol
(port 4028). Covers Antminer stock, Whatsminer, Avalon, Vnish, LuxOS and
any firmware implementing the cgminer protocol.

Read-only by default: writing (frequency, voltage, power) varies by
manufacturer and requires explicit model detection.

Reference: https://en.bitcoin.it/wiki/Cgminer_API
"""
import logging
import time
from typing import Any, Dict, List, Optional

from core.adapters.base_adapter import BaseAdapter
from core.models.device import Device
from core.models.capability import Capability, RiskLevel

log = logging.getLogger(__name__)


CGMINER_DEFAULT_PORT = 4028
CGMINER_TIMEOUT = 5  # seconds


class CgminerAdapter(BaseAdapter):
    """
    Adapter for cgminer/BMMiner protocol devices.
    Read-only: telemetry, version detection, health check.
    Commands that modify frequency/voltage are NOT supported
    without explicit model detection.
    """

    def __init__(self, device: Device, host: Optional[str] = None, port: int = CGMINER_DEFAULT_PORT):
        super().__init__(device)
        self.host = host or device.ip
        self.port = port

    def _send_command(self, command: str) -> Optional[dict]:
        """Send a JSON command over TCP to the cgminer API.
        Returns parsed JSON response or None on failure."""
        result = self._send_cgminer_command(command, self.port, CGMINER_TIMEOUT)
        if result is None:
            log.warning("[cgminer] %s command '%s' failed", self.host, command)
        return result

    def get_telemetry(self) -> Optional[Dict[str, Any]]:
        """Fetch telemetry via cgminer 'summary' + 'stats' + 'pools' commands.

        Collects every canonical ``TELEMETRY_KEYS`` field the cgminer protocol
        can expose. Fields the firmware doesn't report are left as ``None`` —
        the caller MUST run ``normalize_telemetry()`` (core/models/device.py)
        to fill them with the explicit ``NOT_AVAILABLE`` marker before
        rendering in the UI.

        cgminer does NOT expose hashrate windows (1m/10m/1h) — those stay
        ``None`` and are filled by ``normalize_telemetry()``.
        """
        summary = self._send_command("summary")
        if not summary or not summary.get("STATUS"):
            return None

        collected_at = int(time.time())
        stats = self._send_command("stats")
        pools = self._send_command("pools")

        # Parse summary — usually a list with one entry
        summary_data = summary.get("SUMMARY", [{}])
        if isinstance(summary_data, list):
            summary_data = summary_data[0] if summary_data else {}

        hr = float(summary_data.get("GHS 5s", summary_data.get("GHS av", 0)) or 0) * 1e9
        accepted = int(summary_data.get("Accepted", 0))
        rejected = int(summary_data.get("Rejected", 0))
        stale = int(summary_data.get("Stale", 0))
        uptime = int(summary_data.get("Elapsed", 0))
        best_share = str(summary_data.get("Best Share", ""))

        # ── Per-chain stats (temperature, fan, voltage, power) ──────────
        # cgminer 'stats' returns STATS[n] per chain (index 1+). Collect
        # the first chain's values; multi-chain devices can be extended
        # later with per-chain telemetry arrays.
        temp = None
        vr_temp = None
        fan_rpm = None
        voltage = None
        power = None
        if stats and "STATS" in stats:
            stats_list = stats["STATS"]
            if isinstance(stats_list, list) and len(stats_list) > 1:
                chain = stats_list[1]
                # ASIC / junction temp (temp2_0 is usually chip 0, temp = board)
                temp = self._safe_number(
                    chain.get("temp2_0", chain.get("temp", None)))
                # VR / board temp (temp2_1/2_2 on multi-PCB, temp3 on newer)
                vr_temp = self._safe_number(
                    chain.get("temp2_1", chain.get("temp2_2", chain.get("temp3", None))))
                # Fan RPM — cgminer reports fan_num + individual fan speeds
                fan_count = int(chain.get("fan_num", 0))
                if fan_count > 0:
                    fan_rpm = self._safe_number(
                        chain.get("fan1", chain.get("fan_rpm", None)))
                    if fan_rpm is None:
                        # Some firmwares use fan_speed (RPM, not PWM %)
                        fan_rpm = self._safe_number(chain.get("fan_speed", None))
                # Voltage — chain-level DC/DC regulator reading
                voltage = self._safe_number(
                    chain.get("voltage", chain.get("chain_voltage", None)))
                # Power — watts per chain (BOSminer/LuxOS expose this)
                power = self._safe_number(
                    chain.get("power", chain.get("chain_power",
                            chain.get("power_watts", None))))

        # ── Pool status derivation ──────────────────────────────────────
        pool_status, pool_url, pool_user = self._derive_cgminer_pool_status(pools)

        return {
            "source": "cgminer_adapter",
            "timestamp": collected_at,
            "freshness": 0,
            # Core hashrate (cgminer has no 1m/10m/1h windows — normalize fills NOT_AVAILABLE)
            "hashrate": hr,
            "hashrate_1m": None,
            "hashrate_10m": None,
            "hashrate_1h": None,
            # Thermal (Fase 5)
            "chip_temp": temp,
            "vr_temp": vr_temp,
            "temperature": temp,
            # Cooling & power (Fase 5)
            "fan_rpm": fan_rpm,
            "voltage": voltage,
            "power": power,
            # Shares
            "accepted_shares": accepted,
            "rejected_shares": rejected,
            "stale_shares": stale,
            "best_difficulty": best_share,
            "uptime": uptime,
            # Pool (Fase 5)
            "pool_status": pool_status,
            "pool": {"url": pool_url, "user": pool_user} if pool_url else {},
            "stub": False,
        }

    def execute_command(self, command: str, parameters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if command == "restart":
            result = self._send_command("restart")
            return {"success": bool(result), "stub": False}
        return {"success": False, "stub": True, "note": f"{command} not implemented for cgminer"}

    def get_capabilities(self) -> List[Capability]:
        return [
            Capability(name="telemetry", supported=True),
            Capability(name="restart", supported=True, requires_confirmation=True, risk_level=RiskLevel.MEDIUM),
            Capability(name="set_frequency", supported=False, requires_confirmation=True, risk_level=RiskLevel.HIGH),
        ]

    def health_check(self) -> Dict[str, Any]:
        result = self._send_command("version")
        if result:
            return {"status": "reachable", "reachable": True}
        return {"status": "unreachable", "reachable": False}
