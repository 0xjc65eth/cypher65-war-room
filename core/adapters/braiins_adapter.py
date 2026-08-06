"""
CYPHER65 // Braiins OS+ Adapter
================================
Adapter for ASICs running Braiins OS+ firmware (BOSminer).

Braiins OS+ exposes TWO API layers:
  1. **Legacy cgminer socket** (port 4028) — always available, same wire
     protocol as stock cgminer but with Braiins-extended commands
     (``temps``, ``fans``, ``tunerstatus``). No auth required on LAN.
  2. **Modern REST/gRPC API** (port 80 or 50051) — richer telemetry via
     ``GET /api/v1/miner/stats``, ``GET /api/v1/cooling/state``, etc.
     May require session token (POST /api/v1/auth/login).

Strategy: primary path = REST probe on port 80; fallback = cgminer
socket on port 4028. The cgminer protocol is always available on
Braiins OS+ and provides a superset of the standard cgminer fields.

Reference: https://academy.braiins.com/braiins-os/papi-bosminer
"""
import json
import logging
import socket
import time
from typing import Any, Dict, List, Optional

import requests

from core.adapters.base_adapter import BaseAdapter
from core.models.device import Device
from core.models.capability import Capability, RiskLevel

log = logging.getLogger(__name__)

CGMINER_PORT = 4028
REST_PORT = 80
REST_ALT_PORT = 50051
SOCKET_TIMEOUT = 5
HTTP_TIMEOUT = 5


class BraiinsAdapter(BaseAdapter):
    """Adapter for Braiins OS+ firmware.

    Reads telemetry from the cgminer socket (port 4028) enriched with
    Braiins-specific commands and optionally from the REST API.
    """

    def __init__(self, device: Device, host: Optional[str] = None,
                 socket_port: int = CGMINER_PORT):
        super().__init__(device)
        self.host = host or device.ip
        self.socket_port = socket_port

    # ── cgminer socket helpers (mirrored from CgminerAdapter) ─────────

    def _send_command(self, command: str, port: int = None) -> Optional[dict]:
        """Send a JSON command over TCP to the cgminer API (port 4028)."""
        if not self.host:
            return None
        p = port or self.socket_port
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(SOCKET_TIMEOUT)
            sock.connect((self.host, p))
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
        except (socket.timeout, ConnectionRefusedError, OSError,
                json.JSONDecodeError) as e:
            log.debug("[braiins] %s command '%s' failed: %s",
                      self.host, command, e)
            return None
        finally:
            if sock:
                sock.close()
        return None

    @staticmethod
    def _safe_number(value, type_cast=float, default=None):
        """Coerce raw value (often a string in cgminer) to a number."""
        try:
            return type_cast(value) if value is not None else default
        except (ValueError, TypeError):
            return default

    # ── REST probe (modern Braiins OS+ API) ───────────────────────────

    def _rest_get(self, path: str, port: int = None) -> Optional[dict]:
        """GET a Braiins OS+ REST endpoint; returns parsed JSON or None."""
        if not self.host:
            return None
        p = port or REST_PORT
        url = f"http://{self.host}:{p}{path}"
        try:
            r = requests.get(url, timeout=HTTP_TIMEOUT)
            if r.status_code == 200:
                return r.json()
        except (requests.ConnectionError, requests.Timeout,
                json.JSONDecodeError):
            pass
        return None

    # ── Telemetry ─────────────────────────────────────────────────────

    def get_telemetry(self) -> Optional[Dict[str, Any]]:
        """Fetch telemetry from Braiins OS+.

        Primary: REST API ``/api/v1/miner/stats`` (modern firmwares).
        Fallback: cgminer socket on port 4028 with Braiins-extended
        commands (``temps``, ``fans``, ``tunerstatus``).

        Returns None when the device is completely unreachable.
        """
        # ── Path 1: modern REST API (port 80, then 50051) ─────────
        rest = self._rest_get("/api/v1/miner/stats")
        if rest:
            return self._parse_rest_telemetry(rest)

        # ── Path 2: cgminer socket with Braiins extensions ────────
        return self._parse_cgminer_telemetry()

    def _parse_rest_telemetry(self, data: dict) -> Optional[Dict[str, Any]]:
        """Parse the modern REST API response into canonical telemetry."""
        collected_at = int(time.time())

        miner = data.get("miner_stats") or {}
        pool = data.get("pool_stats") or {}
        power = data.get("power_stats") or {}

        hr = self._safe_number(
            miner.get("hashrate_avg") or miner.get("hashrate_ghps"),
            float, 0) * 1e9 if miner.get("hashrate_avg") else \
            self._safe_number(miner.get("hashrate_ghps"), float, 0) * 1e9

        return self._build_telemetry_dict(
            collected_at=collected_at,
            hashrate=hr,
            chip_temp=self._safe_number(miner.get("chip_temp_avg")),
            vr_temp=None,  # REST API doesn't expose VR temp directly
            temperature=self._safe_number(miner.get("board_temp_avg")),
            fan_rpm=None,  # fetched separately from /cooling/state
            voltage=None,
            power=self._safe_number(power.get("power_avg") or power.get("power_w")),
            pool_status=self._derive_pool_status(pool),
            pool_url=str(pool.get("url") or ""),
            pool_user=str(pool.get("user") or ""),
            accepted_shares=self._safe_number(
                miner.get("accepted_shares") or pool.get("accepted"), int, 0),
            rejected_shares=self._safe_number(
                miner.get("rejected_shares") or pool.get("rejected"), int, 0),
            stale_shares=self._safe_number(
                miner.get("stale_shares") or pool.get("stale"), int, 0),
            uptime=self._safe_number(miner.get("uptime_s") or miner.get("uptime"), int, 0),
            best_share=str(miner.get("best_share") or ""),
        )

    def _parse_cgminer_telemetry(self) -> Optional[Dict[str, Any]]:
        """Parse the cgminer socket response with Braiins extensions."""
        summary = self._send_command("summary")
        if not summary or not summary.get("STATUS"):
            return None

        collected_at = int(time.time())

        # summary
        summary_data = summary.get("SUMMARY", [{}])
        if isinstance(summary_data, list):
            summary_data = summary_data[0] if summary_data else {}

        hr = float(summary_data.get("GHS 5s",
                   summary_data.get("GHS av", 0)) or 0) * 1e9
        accepted = int(summary_data.get("Accepted", 0))
        rejected = int(summary_data.get("Rejected", 0))
        stale = int(summary_data.get("Stale", 0))
        uptime = int(summary_data.get("Elapsed", 0))
        best_share = str(summary_data.get("Best Share", ""))

        # Braiins-specific: 'temps' command (per-board/chip temps)
        temps_data = self._send_command("temps")

        # Braiins-specific: 'fans' command (fan RPM per position)
        fans_data = self._send_command("fans")

        # Braiins-specific: 'tunerstatus' (autotune state, power limit)
        tuner_data = self._send_command("tunerstatus")

        # Standard cgminer stats (chain-level data)
        stats_data = self._send_command("stats")

        # Pool info
        pools_data = self._send_command("pools")

        # ── Extract temperatures ──────────────────────────────────
        chip_temp = None
        board_temp = None
        vr_temp = None

        # Braiins 'temps': array of {Board, Chip, ID, temp, temp_pcb, ...}
        if temps_data and "TEMPS" in temps_data:
            temps_list = temps_data["TEMPS"]
            if isinstance(temps_list, list) and temps_list:
                # Collect max chip temp across all boards
                chip_temps = [self._safe_number(t.get("temp"))
                              for t in temps_list
                              if self._safe_number(t.get("temp")) is not None]
                if chip_temps:
                    chip_temp = max(chip_temps)
                # Board/PCB temp
                pcb_temps = [self._safe_number(t.get("temp_pcb"))
                             for t in temps_list
                             if self._safe_number(t.get("temp_pcb")) is not None]
                if pcb_temps:
                    board_temp = max(pcb_temps)

        # Fallback to stats chain data if temps command unavailable
        if chip_temp is None and stats_data and "STATS" in stats_data:
            stats_list = stats_data["STATS"]
            if isinstance(stats_list, list) and len(stats_list) > 1:
                chain = stats_list[1]
                chip_temp = self._safe_number(
                    chain.get("temp2_0", chain.get("temp", None)))
                vr_temp = self._safe_number(
                    chain.get("temp2_1", chain.get("temp2_2",
                              chain.get("temp3", None))))
                if board_temp is None:
                    board_temp = self._safe_number(
                        chain.get("temp", None))

        # ── Extract fan RPM ───────────────────────────────────────
        fan_rpm = None

        if fans_data and "FANS" in fans_data:
            fans_list = fans_data["FANS"]
            if isinstance(fans_list, list) and fans_list:
                fan_rpms = [self._safe_number(f.get("RPM"))
                            for f in fans_list
                            if self._safe_number(f.get("RPM")) is not None]
                if fan_rpms:
                    # Average RPM across all fans
                    fan_rpm = sum(fan_rpms) / len(fan_rpms)

        if fan_rpm is None and stats_data and "STATS" in stats_data:
            stats_list = stats_data["STATS"]
            if isinstance(stats_list, list) and len(stats_list) > 1:
                chain = stats_list[1]
                fan_count = int(chain.get("fan_num", 0))
                if fan_count > 0:
                    fan_rpm = self._safe_number(
                        chain.get("fan1", chain.get("fan_rpm",
                                  chain.get("fan_speed", None))))

        # ── Extract voltage ───────────────────────────────────────
        voltage = None
        if stats_data and "STATS" in stats_data:
            stats_list = stats_data["STATS"]
            if isinstance(stats_list, list) and len(stats_list) > 1:
                chain = stats_list[1]
                voltage = self._safe_number(
                    chain.get("voltage", chain.get("chain_voltage", None)))

        # ── Extract power (prefer tunerstatus) ────────────────────
        power = None

        if tuner_data and "TUNERSTATUS" in tuner_data:
            tuner = tuner_data["TUNERSTATUS"]
            if isinstance(tuner, list) and tuner:
                t = tuner[0]
                power = self._safe_number(
                    t.get("power", t.get("Power", t.get("power_w",
                          t.get("PowerLimit", None)))))

        if power is None and stats_data and "STATS" in stats_data:
            stats_list = stats_data["STATS"]
            if isinstance(stats_list, list) and len(stats_list) > 1:
                chain = stats_list[1]
                power = self._safe_number(
                    chain.get("power", chain.get("chain_power",
                              chain.get("power_watts", None))))

        # ── Pool status ───────────────────────────────────────────
        pool_status = None
        pool_url = ""
        pool_user = ""
        if pools_data and "POOLS" in pools_data:
            pool_list = pools_data["POOLS"]
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

        return self._build_telemetry_dict(
            collected_at=collected_at,
            hashrate=hr,
            chip_temp=chip_temp,
            vr_temp=vr_temp,
            temperature=board_temp or chip_temp,
            fan_rpm=fan_rpm,
            voltage=voltage,
            power=power,
            pool_status=pool_status,
            pool_url=pool_url,
            pool_user=pool_user,
            accepted_shares=accepted,
            rejected_shares=rejected,
            stale_shares=stale,
            uptime=uptime,
            best_share=best_share,
        )

    def _build_telemetry_dict(
        self, collected_at, hashrate, chip_temp, vr_temp, temperature,
        fan_rpm, voltage, power, pool_status, pool_url, pool_user,
        accepted_shares, rejected_shares, stale_shares, uptime, best_share
    ) -> Dict[str, Any]:
        """Assemble the canonical telemetry dict.

        cgminer-based protocols (including Braiins) do NOT expose hashrate
        windows (1m/10m/1h) — those stay None and are filled by
        ``normalize_telemetry()``.
        """
        return {
            "source": "braiins_adapter",
            "timestamp": collected_at,
            "freshness": 0,
            "hashrate": hashrate,
            "hashrate_1m": None,
            "hashrate_10m": None,
            "hashrate_1h": None,
            "chip_temp": chip_temp,
            "vr_temp": vr_temp,
            "temperature": temperature,
            "fan_rpm": fan_rpm,
            "voltage": voltage,
            "power": power,
            "accepted_shares": accepted_shares,
            "rejected_shares": rejected_shares,
            "stale_shares": stale_shares,
            "best_difficulty": best_share,
            "uptime": uptime,
            "pool_status": pool_status,
            "pool": {"url": pool_url, "user": pool_user} if pool_url else {},
            "stub": False,
        }

    @staticmethod
    def _derive_pool_status(pool: dict) -> Optional[str]:
        """Derive pool_status from a REST pool_stats dict."""
        if not pool or not pool.get("url"):
            return None
        state = str(pool.get("status") or pool.get("state") or "").lower()
        if state in ("alive", "connected", "online", "mining"):
            return "CONNECTED"
        if state in ("dead", "disconnected", "offline"):
            return "DISCONNECTED"
        return None

    # ── Commands ───────────────────────────────────────────────────────

    def execute_command(self, command: str,
                        parameters: Optional[Dict[str, Any]] = None
                        ) -> Dict[str, Any]:
        if not self.supports(command):
            return {"success": False,
                    "error": "Command not supported by this device"}

        if command == "restart":
            result = self._send_command("restart")
            return {"success": bool(result), "stub": False,
                    "command": command, "device_id": self.device.id}

        if command == "identify":
            # Braiins OS+ supports LED blink via cgminer's 'led' command
            result = self._send_command("led")
            if result:
                return {"success": True, "stub": False,
                        "command": command, "device_id": self.device.id}
            return {"success": False, "stub": True,
                    "command": command, "device_id": self.device.id,
                    "note": "LED blink not supported by this firmware"}

        return {"success": False, "stub": True,
                "command": command, "device_id": self.device.id,
                "note": f"{command} not yet implemented for Braiins OS+"}

    # ── Capabilities ───────────────────────────────────────────────────

    def get_capabilities(self) -> List[Capability]:
        return [
            Capability(name="telemetry", supported=True),
            Capability(name="restart", supported=True,
                       requires_confirmation=True, risk_level=RiskLevel.MEDIUM),
            Capability(name="identify", supported=True),
            Capability(name="tuner_control", supported=False,
                       requires_confirmation=True, risk_level=RiskLevel.HIGH),
            Capability(name="set_frequency", supported=False,
                       requires_confirmation=True, risk_level=RiskLevel.HIGH),
        ]

    # ── Health check ───────────────────────────────────────────────────

    def health_check(self) -> Dict[str, Any]:
        """Probe both APIs to determine reachability."""
        if not self.host:
            return {"status": "unreachable", "reachable": False}

        # Try REST first
        rest = self._rest_get("/api/v1/miner/stats")
        if rest:
            return {"status": "reachable", "reachable": True,
                    "api": "rest", "port": REST_PORT}

        # Try cgminer socket
        version = self._send_command("version")
        if version:
            vdata = version.get("VERSION", [{}])
            v = vdata[0] if isinstance(vdata, list) and vdata else {}
            return {"status": "reachable", "reachable": True,
                    "api": "cgminer_socket", "port": self.socket_port,
                    "version": str(v.get("Version", "")),
                    "type": str(v.get("Type", ""))}

        return {"status": "unreachable", "reachable": False}
