"""
CYPHER65 // AXE FLEET — AxeOS Connector
========================================
REST client for AxeOS/ESP-Miner API.
Discovers device capabilities, fetches telemetry, executes commands.

Based on ESP-Miner openapi.yaml at:
  https://github.com/bitaxeorg/ESP-Miner/blob/master/main/http_server/openapi.yaml

All requests are unauthenticated (LAN-only safety model).
"""
import json
import logging
import time

import requests

from .models import infer_capabilities, DEFAULT_CAPABILITIES

log = logging.getLogger("cypher65.axe")

# ── Defaults ──────────────────────────────────────────────────────────────
AXEOS_HTTP_TIMEOUT = 5       # seconds per HTTP request
AXEOS_WS_TIMEOUT = 10        # seconds for WebSocket connection
MIN_POLL_INTERVAL = 30       # minimum seconds between polls per device


class AxeOSConnectorError(Exception):
    """Raised on communication failure with an AxeOS device."""
    pass


class AxeOSConnector:
    """Low-level REST client for a single AxeOS/ESP-Miner device.

    Usage:
        conn = AxeOSConnector("192.168.1.100")
        info = conn.fetch_info()
        caps = conn.detect_capabilities()
        conn.restart()
    """

    def __init__(self, ip_address: str, port: int = 80, timeout: int = AXEOS_HTTP_TIMEOUT):
        self.ip = ip_address
        self.port = port
        self.timeout = timeout
        self.base_url = f"http://{ip_address}:{port}"

    # ── Low-level request ─────────────────────────────────────────────

    def _get(self, path: str, timeout: int = None) -> dict:
        """GET request to device. Returns parsed JSON dict or raises."""
        url = f"{self.base_url}{path}"
        try:
            r = requests.get(url, timeout=timeout or self.timeout)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.ConnectionError as e:
            raise AxeOSConnectorError(f"Connection failed to {self.ip}: {e}")
        except requests.exceptions.Timeout as e:
            raise AxeOSConnectorError(f"Timeout connecting to {self.ip}: {e}")
        except requests.exceptions.HTTPError as e:
            raise AxeOSConnectorError(f"HTTP error from {self.ip}{path}: {e}")
        except json.JSONDecodeError as e:
            raise AxeOSConnectorError(f"Invalid JSON from {self.ip}: {e}")

    def _post(self, path: str, data: dict = None, timeout: int = None) -> dict:
        """POST request to device."""
        url = f"{self.base_url}{path}"
        try:
            r = requests.post(url, json=data, timeout=timeout or self.timeout)
            r.raise_for_status()
            if r.text and r.text.strip():
                return r.json()
            return {"success": True}
        except requests.exceptions.ConnectionError as e:
            raise AxeOSConnectorError(f"Connection failed to {self.ip}: {e}")
        except requests.exceptions.Timeout as e:
            raise AxeOSConnectorError(f"Timeout connecting to {self.ip}: {e}")
        except json.JSONDecodeError:
            # Some AxeOS POST endpoints return plain text, not JSON
            return {"success": True}

    def _patch(self, path: str, data: dict, timeout: int = None) -> dict:
        """PATCH request to device (used for settings updates)."""
        url = f"{self.base_url}{path}"
        try:
            r = requests.patch(url, json=data, timeout=timeout or self.timeout)
            r.raise_for_status()
            if r.text and r.text.strip():
                return r.json()
            return {"success": True}
        except requests.exceptions.ConnectionError as e:
            raise AxeOSConnectorError(f"Connection failed to {self.ip}: {e}")
        except requests.exceptions.Timeout as e:
            raise AxeOSConnectorError(f"Timeout connecting to {self.ip}: {e}")

    # ── Read endpoints ────────────────────────────────────────────────

    def fetch_info(self) -> dict:
        """GET /api/system/info — comprehensive system, miner, ASIC info.
        Returns dict with keys like: firmware, hostname, model, version,
        hashrate, temp, voltage, fanSpeed, bestDiff, shares*, uptime, etc."""
        try:
            return self._get("/api/system/info")
        except AxeOSConnectorError as e:
            log.warning("[%s] fetch_info failed: %s", self.ip, e)
            raise

    def fetch_asic(self) -> dict:
        """GET /api/system/asic — ASIC settings and capabilities.
        Returns dict with keys: asicModel, frequency, coreVoltage, etc."""
        try:
            return self._get("/api/system/asic")
        except AxeOSConnectorError as e:
            log.warning("[%s] fetch_asic failed: %s", self.ip, e)
            raise

    def fetch_statistics(self) -> dict:
        """GET /api/system/statistics — historical logging data.
        Only returns data if statsFrequency > 0 on the device."""
        try:
            return self._get("/api/system/statistics")
        except AxeOSConnectorError as e:
            log.warning("[%s] fetch_statistics failed: %s", self.ip, e)
            raise

    def fetch_dashboard(self) -> dict:
        """GET /api/system/statistics/dashboard — dashboard-optimized stats."""
        try:
            return self._get("/api/system/statistics/dashboard")
        except AxeOSConnectorError as e:
            log.warning("[%s] fetch_dashboard failed: %s", self.ip, e)
            raise

    # ── Capability detection ──────────────────────────────────────────

    def detect_capabilities(self) -> dict:
        """Detect device capabilities by fetching /api/system/info and
        /api/system/asic, then inferring supported features from the response.
        Returns a capabilities dict.
        Never assumes support without confirmation."""
        caps_base = {}
        try:
            info = self.fetch_info()
            caps_base = infer_capabilities(info)
        except AxeOSConnectorError:
            # If basic info fails, all capabilities are off
            return {k: False for k in DEFAULT_CAPABILITIES}

        # Try ASIC endpoint for frequency/voltage capabilities
        try:
            asic = self.fetch_asic()
            if asic.get("frequency") is not None:
                caps_base["frequencyControl"] = True
            if asic.get("coreVoltage") is not None:
                caps_base["voltageControl"] = True
        except AxeOSConnectorError:
            pass  # ASIC endpoint not available — keep info-based inference

        return caps_base

    # ── Extract telemetry from system info ─────────────────────────────

    def extract_telemetry(self, info: dict = None) -> dict:
        """Extract a telemetry dict from /api/system/info response.
        Returns normalized telemetry dict with all TELEMETRY_SCHEMA keys."""
        from .models import new_telemetry, TELEMETRY_SCHEMA

        if info is None:
            try:
                info = self.fetch_info()
            except AxeOSConnectorError:
                return {}

        t = new_telemetry("")
        t["ts"] = int(time.time())

        t["hashrate_hs"] = int(info.get("hashrate") or 0)
        t["expected_hashrate"] = int(info.get("hashrate") or 0)

        # Temperature
        t["temperature"] = info.get("temp")
        if t["temperature"] is None:
            t["temperature"] = info.get("temperature")

        # Fan
        t["fan_speed"] = info.get("fanSpeed")
        t["fan_rpm"] = info.get("fanRPM")

        # Power / voltage / frequency
        t["power_watts"] = info.get("power")
        t["voltage_mv"] = info.get("coreVoltage")
        t["voltage_actual_mv"] = info.get("coreVoltageActual")
        t["frequency_mhz"] = info.get("frequency")
        t["current_ma"] = info.get("current")

        # Efficiency
        hr_hs = t["hashrate_hs"]
        pwr = t["power_watts"]
        if hr_hs > 0 and pwr and pwr > 0:
            t["efficiency_jth"] = round(pwr / (hr_hs / 1e12), 2)

        # Shares / best diff
        t["best_diff"] = str(info.get("bestDiff") or "")
        t["shares_accepted"] = int(info.get("sharesAccepted") or 0)
        t["shares_rejected"] = int(info.get("sharesRejected") or 0)
        accepted = t["shares_accepted"]
        rejected = t["shares_rejected"]
        total = accepted + rejected
        if total > 0:
            t["hw_error_pct"] = round(rejected / total * 100, 2)

        # HW errors
        t["hw_errors"] = int(info.get("hwErrors") or 0)

        # Uptime / system
        t["uptime_seconds"] = int(info.get("uptime") or 0)
        t["free_heap"] = int(info.get("freeHeap") or 0)
        t["wifi_rssi"] = info.get("wifiRSSI")

        # Pool
        t["pool_url"] = str(info.get("pool") or info.get("stratumURL") or "")
        t["pool_user"] = str(info.get("poolUser") or info.get("poolUsername") or "")
        t["stratum_status"] = str(info.get("stratumStatus") or info.get("poolStatus") or "")

        return t

    # ── Command endpoints ─────────────────────────────────────────────

    def restart(self) -> dict:
        """POST /api/system/restart — reboot the device.
        Returns after successful POST (device will go offline momentarily)."""
        return self._post("/api/system/restart")

    def identify(self) -> dict:
        """POST /api/system/identify — flash LED/screen for identification."""
        return self._post("/api/system/identify")

    def update_settings(self, settings: dict) -> dict:
        """PATCH /api/system — update device configuration.
        Common settings:
          - frequency (MHz)
          - coreVoltage (mV)
          - fanSpeed (0-100)
          - pool (stratum URL)
          - poolUser (wallet.worker)
          - hostname
        Always check capability before calling."""
        return self._patch("/api/system", settings)

    # ── Health check ──────────────────────────────────────────────────

    def ping(self) -> bool:
        """Quick connectivity check. True if device responds to /api/system/info
        within timeout."""
        try:
            self._get("/api/system/info", timeout=3)
            return True
        except AxeOSConnectorError:
            return False


# ── Convenience ──────────────────────────────────────────────────────────

def normalize_ip(ip_or_hostname: str) -> str:
    """Normalize an IP or hostname string. Returns stripped IP."""
    return ip_or_hostname.strip()


def batch_fetch_telemetry(devices: list, timeout: int = AXEOS_HTTP_TIMEOUT) -> dict:
    """Fetch telemetry from multiple devices in parallel.
    devices: list of dict with at least {"ip_address": str}
    Returns dict of {device_id: telemetry_dict}
    Failed devices return empty dict."""
    import concurrent.futures

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(devices), 20)) as ex:
        future_map = {}
        for d in devices:
            conn = AxeOSConnector(d["ip_address"], timeout=timeout)
            future = ex.submit(conn.extract_telemetry)
            future_map[future] = d["id"]

        for fut in concurrent.futures.as_completed(future_map):
            did = future_map[fut]
            try:
                tel = fut.result()
                if tel:
                    tel["device_id"] = did
                results[did] = tel
            except Exception:
                results[did] = {}
    return results
