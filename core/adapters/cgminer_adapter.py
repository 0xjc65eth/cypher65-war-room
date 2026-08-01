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
import json
import logging
import socket
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
        if not self.host:
            return None
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(CGMINER_TIMEOUT)
            sock.connect((self.host, self.port))
            payload = json.dumps({"command": command}) + "\n"
            sock.send(payload.encode())
            # Read until null byte (cgminer delimiter)
            data = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b"\x00" in chunk:
                    break
            # Strip null byte and parse
            text = data.decode(errors="replace").rstrip("\x00").strip()
            if text:
                return json.loads(text)
        except (socket.timeout, ConnectionRefusedError, OSError, json.JSONDecodeError) as e:
            log.warning("[cgminer] %s command failed: %s", self.host, e)
            return None
        finally:
            if sock:
                sock.close()
        return None

    def get_telemetry(self) -> Optional[Dict[str, Any]]:
        """Fetch telemetry via cgminer 'summary' + 'stats' commands."""
        summary = self._send_command("summary")
        if not summary or not summary.get("STATUS"):
            return None

        collected_at = int(time.time())
        stats = self._send_command("stats")
        pools = self._send_command("pools")

        # Parse summary - usually a list with one entry
        summary_data = summary.get("SUMMARY", [{}])
        if isinstance(summary_data, list):
            summary_data = summary_data[0] if summary_data else {}

        hr = float(summary_data.get("GHS 5s", summary_data.get("GHS av", 0)) or 0) * 1e9
        accepted = int(summary_data.get("Accepted", 0))
        rejected = int(summary_data.get("Rejected", 0))
        stale = int(summary_data.get("Stale", 0))
        uptime = int(summary_data.get("Elapsed", 0))
        best_share = str(summary_data.get("Best Share", ""))

        # Temperature from stats (per-chain)
        temp = None
        vr_temp = None
        if stats and "STATS" in stats:
            stats_list = stats["STATS"]
            if isinstance(stats_list, list) and len(stats_list) > 1:
                temp = stats_list[1].get("temp2_0", stats_list[1].get("temp", None))
                # Fase 5: VR/board temperature when the chain reports it.
                vr_temp = stats_list[1].get("temp2_1", stats_list[1].get("temp2_2", None))

        return {
            "source": "cgminer_adapter",
            "timestamp": collected_at,
            "freshness": 0,
            "hashrate": hr,
            # Fase 5: chip_temp = ASIC temp (same as temperature for cgminer)
            "chip_temp": temp,
            "vr_temp": vr_temp,
            "temperature": temp,
            "accepted_shares": accepted,
            "rejected_shares": rejected,
            "stale_shares": stale,
            "best_difficulty": best_share,
            "uptime": uptime,
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
