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
AXEOS_HTTP_TIMEOUT = 5  # seconds per HTTP request
AXEOS_WS_TIMEOUT = 10  # seconds for WebSocket connection
MIN_POLL_INTERVAL = 30  # minimum seconds between polls per device


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

    def __init__(
        self, ip_address: str, port: int = 80, timeout: int = AXEOS_HTTP_TIMEOUT
    ):
        self.ip = ip_address
        self.port = port
        self.timeout = timeout
        self.base_url = f"http://{ip_address}:{port}"

    # ── Low-level request ─────────────────────────────────────────────

    def _get(self, path: str, timeout: int = None) -> dict:
        """GET request to device. Returns parsed JSON dict or raises."""
        url = f"{self.base_url}{path}"
        t0 = time.time()
        try:
            # timeout always resolves to a positive int (self.timeout default,
            # AXEOS_HTTP_TIMEOUT as final fallback) — never None.
            r = requests.get(
                url, timeout=timeout or self.timeout or AXEOS_HTTP_TIMEOUT
            )  # nosec B113
            elapsed = time.time() - t0
            log.info("[%s] GET %s → %s (%.2fs)", self.ip, path, r.status_code, elapsed)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.ConnectionError as e:
            elapsed = time.time() - t0
            err_type = self._classify_connection_error(e)
            log.error(
                "[%s] GET %s FAILED after %.2fs — %s: %s",
                self.ip,
                path,
                elapsed,
                err_type,
                e,
            )
            raise AxeOSConnectorError(
                f"Connection failed to {self.ip} (GET {path}): "
                f"{err_type} after {elapsed:.1f}s — {e}"
            )
        except requests.exceptions.Timeout as e:
            elapsed = time.time() - t0
            log.error(
                "[%s] GET %s TIMEOUT after %.2fs (timeout=%ss)",
                self.ip,
                path,
                elapsed,
                timeout or self.timeout,
            )
            raise AxeOSConnectorError(
                f"Timeout connecting to {self.ip} (GET {path}): "
                f"no response after {elapsed:.1f}s (timeout={timeout or self.timeout}s)"
            )
        except requests.exceptions.HTTPError as e:
            elapsed = time.time() - t0
            status = e.response.status_code if e.response is not None else "N/A"
            log.error(
                "[%s] GET %s HTTP %s after %.2fs — %s",
                self.ip,
                path,
                status,
                elapsed,
                e,
            )
            raise AxeOSConnectorError(
                f"HTTP error from {self.ip}{path}: status={status} — {e}"
            )
        except json.JSONDecodeError as e:
            elapsed = time.time() - t0
            log.error(
                "[%s] GET %s INVALID JSON after %.2fs — %s", self.ip, path, elapsed, e
            )
            raise AxeOSConnectorError(f"Invalid JSON from {self.ip} (GET {path}): {e}")

    def _post(self, path: str, data: dict = None, timeout: int = None) -> dict:
        """POST request to device."""
        url = f"{self.base_url}{path}"
        t0 = time.time()
        try:
            # timeout always resolves to a positive int — never None.
            r = requests.post(
                url, json=data, timeout=timeout or self.timeout or AXEOS_HTTP_TIMEOUT
            )  # nosec B113
            elapsed = time.time() - t0
            log.info("[%s] POST %s → %s (%.2fs)", self.ip, path, r.status_code, elapsed)
            r.raise_for_status()
            if r.text and r.text.strip():
                return r.json()
            return {"success": True}
        except requests.exceptions.ConnectionError as e:
            elapsed = time.time() - t0
            err_type = self._classify_connection_error(e)
            log.error(
                "[%s] POST %s FAILED after %.2fs — %s: %s",
                self.ip,
                path,
                elapsed,
                err_type,
                e,
            )
            raise AxeOSConnectorError(
                f"Connection failed to {self.ip} (POST {path}): "
                f"{err_type} after {elapsed:.1f}s — {e}"
            )
        except requests.exceptions.Timeout as e:
            elapsed = time.time() - t0
            log.error(
                "[%s] POST %s TIMEOUT after %.2fs (timeout=%ss)",
                self.ip,
                path,
                elapsed,
                timeout or self.timeout,
            )
            raise AxeOSConnectorError(
                f"Timeout connecting to {self.ip} (POST {path}): "
                f"no response after {elapsed:.1f}s"
            )
        except json.JSONDecodeError:
            # Some AxeOS POST endpoints return plain text, not JSON
            elapsed = time.time() - t0
            log.warning(
                "[%s] POST %s → non-JSON response (%.2fs), treating as success",
                self.ip,
                path,
                elapsed,
            )
            return {"success": True}

    def _patch(self, path: str, data: dict, timeout: int = None) -> dict:
        """PATCH request to device (used for settings updates)."""
        url = f"{self.base_url}{path}"
        t0 = time.time()
        try:
            # timeout always resolves to a positive int — never None.
            r = requests.patch(
                url, json=data, timeout=timeout or self.timeout or AXEOS_HTTP_TIMEOUT
            )  # nosec B113
            elapsed = time.time() - t0
            log.info(
                "[%s] PATCH %s → %s (%.2fs)", self.ip, path, r.status_code, elapsed
            )
            r.raise_for_status()
            if r.text and r.text.strip():
                return r.json()
            return {"success": True}
        except requests.exceptions.ConnectionError as e:
            elapsed = time.time() - t0
            err_type = self._classify_connection_error(e)
            log.error(
                "[%s] PATCH %s FAILED after %.2fs — %s: %s",
                self.ip,
                path,
                elapsed,
                err_type,
                e,
            )
            raise AxeOSConnectorError(
                f"Connection failed to {self.ip} (PATCH {path}): "
                f"{err_type} after {elapsed:.1f}s — {e}"
            )
        except requests.exceptions.Timeout as e:
            elapsed = time.time() - t0
            log.error(
                "[%s] PATCH %s TIMEOUT after %.2fs (timeout=%ss)",
                self.ip,
                path,
                elapsed,
                timeout or self.timeout,
            )
            raise AxeOSConnectorError(
                f"Timeout connecting to {self.ip} (PATCH {path}): "
                f"no response after {elapsed:.1f}s"
            )

    def _classify_connection_error(
        self, exc: requests.exceptions.ConnectionError
    ) -> str:
        """Classify the type of connection error for better diagnostics."""
        msg = str(exc).lower()
        if "no route to host" in msg or "network is unreachable" in msg:
            return "NO_ROUTE"
        if "connection refused" in msg or "actively refused" in msg:
            return "REFUSED"
        if (
            "dns" in msg
            or "name resolution" in msg
            or "name or service not known" in msg
        ):
            return "DNS_FAILURE"
        if "connection reset" in msg:
            return "RESET"
        if "connection aborted" in msg:
            return "ABORTED"
        if "eof" in msg or "end of file" in msg:
            return "EOF"
        return "UNKNOWN"

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
            log.warning(
                "[%s] detect_capabilities: fetch_info failed — "
                "all capabilities disabled",
                self.ip,
            )
            return {k: False for k in DEFAULT_CAPABILITIES}

        # Try ASIC endpoint for frequency/voltage capabilities
        try:
            asic = self.fetch_asic()
            if asic.get("frequency") is not None:
                caps_base["frequencyControl"] = True
            if asic.get("coreVoltage") is not None:
                caps_base["voltageControl"] = True
        except AxeOSConnectorError:
            log.info(
                "[%s] detect_capabilities: ASIC endpoint unavailable — "
                "frequency/voltage control disabled",
                self.ip,
            )

        return caps_base

    # ── Extract telemetry from system info ─────────────────────────────

    def extract_telemetry(self, info: dict = None) -> dict:
        """Extract a telemetry dict from /api/system/info response.
        Returns normalized telemetry dict with all TELEMETRY_SCHEMA keys."""
        from .models import new_telemetry, TELEMETRY_SCHEMA

        if info is None:
            try:
                info = self.fetch_info()
            except AxeOSConnectorError as e:
                log.warning(
                    "[%s] extract_telemetry: fetch_info failed — "
                    "returning empty telemetry: %s",
                    self.ip,
                    e,
                )
                return {}

        t = new_telemetry("")
        t["ts"] = int(time.time())

        t["hashrate_hs"] = int(info.get("hashrate") or 0)
        t["expected_hashrate"] = int(info.get("hashrate") or 0)

        # Fase 5: hashrate windows (H/s) — AxeOS exposes hashRate1m/10m/1hr.
        # Honest Telemetry: hashRate5m is never promoted to hashrate_10m.
        hr_1m = info.get("hashRate1m")
        hr_10m = info.get("hashRate10m")
        hr_1h = info.get("hashRate1hr") or info.get("hashRate1h")
        t["hashrate_1m"] = int(hr_1m) if hr_1m is not None else None
        t["hashrate_10m"] = int(hr_10m) if hr_10m is not None else None
        t["hashrate_1h"] = int(hr_1h) if hr_1h is not None else None

        # Temperature
        t["temperature"] = info.get("temp")
        if t["temperature"] is None:
            t["temperature"] = info.get("temperature")

        # Fase 5: ASIC + VR temperatures
        t["temp_asic"] = info.get("tempChip") or info.get("temp_asic")
        t["temp_vreg"] = (
            info.get("vrTemp") or info.get("temp2") or info.get("temp_vreg")
        )

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
        # Worker-intelligence extras (best-effort — many AxeOS builds expose
        # the current stratum difficulty target; last-share time is rarer).
        # None → the UI renders an honest '—'.
        t["pool_diff"] = (
            info.get("poolDifficulty") or info.get("difficulty") or info.get("poolDiff")
        )
        _last_share = info.get("lastShare")
        if _last_share is None:
            _last_share = info.get("lastShareTime") or info.get("lastShareTimestamp")
        t["last_share_ts"] = _last_share
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

        # Pause state — explicit operator intent (Issue #13): a paused device
        # reports miningPaused=true and must render PAUSED, not IDLE/ONLINE.
        # Strict `is True`: `bool("false")` is True in Python — a stringy
        # firmware/agent value must never falsely pause a device.
        t["mining_paused"] = info.get("miningPaused") is True

        # Pool
        t["pool_url"] = str(info.get("pool") or info.get("stratumURL") or "")
        t["pool_user"] = str(info.get("poolUser") or info.get("poolUsername") or "")
        t["stratum_status"] = str(
            info.get("stratumStatus") or info.get("poolStatus") or ""
        )

        return t

    # ── Command endpoints ─────────────────────────────────────────────

    def restart(self) -> dict:
        """POST /api/system/restart — reboot the device.
        Returns after successful POST (device will go offline momentarily)."""
        return self._post("/api/system/restart")

    def identify(self) -> dict:
        """POST /api/system/identify — flash LED/screen for identification."""
        return self._post("/api/system/identify")

    def pause(self) -> dict:
        """POST /api/system/miningPause — pause hashing on the device.

        ESP-Miner API: the ASIC stays powered but stops hashing, so the
        device stays reachable for Resume. Only call when the 'pause'
        capability is advertised."""
        return self._post("/api/system/miningPause")

    def resume(self) -> dict:
        """POST /api/system/miningResume — resume hashing on a paused device."""
        return self._post("/api/system/miningResume")

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
        t0 = time.time()
        try:
            self._get("/api/system/info", timeout=3)
            elapsed = time.time() - t0
            log.info("[%s] ping OK (%.2fs)", self.ip, elapsed)
            return True
        except AxeOSConnectorError as e:
            elapsed = time.time() - t0
            log.info("[%s] ping FAILED (%.2fs): %s", self.ip, max(elapsed, 0), e)
            return False

    def _diagnose_connectivity(self) -> dict:
        """Run a full connectivity diagnostic against this device.
        Returns a dict with results from multiple diagnostics:
        {
            'ip': str,
            'port': int,
            'dns_resolution': bool,
            'arp_entry': bool,
            'ping_icmp': bool,       # not yet implemented
            'http_connect': bool,
            'api_response': bool,
            'http_status': int or None,
            'elapsed_ms': int,
            'error_type': str or None,
            'error_detail': str or None,
        }
        This method does NOT raise — it always returns a result dict.
        """
        result = {
            "ip": self.ip,
            "port": self.port,
            "dns_resolution": None,
            "http_connect": False,
            "api_response": False,
            "http_status": None,
            "elapsed_ms": None,
            "error_type": None,
            "error_detail": None,
        }
        t0 = time.time()
        try:
            r = requests.get(f"{self.base_url}/api/system/info", timeout=3)
            result["elapsed_ms"] = int((time.time() - t0) * 1000)
            result["http_status"] = r.status_code
            result["http_connect"] = True
            if r.status_code == 200:
                try:
                    data = r.json()
                    result["api_response"] = True
                    result["device_info"] = {
                        "model": data.get("model"),
                        "firmware": data.get("firmware"),
                        "hostname": data.get("hostname"),
                        "hashrate": data.get("hashrate"),
                    }
                except json.JSONDecodeError:
                    result["api_response"] = False
                    result["error_detail"] = "Response was not valid JSON"
        except requests.exceptions.ConnectionError as e:
            result["elapsed_ms"] = int((time.time() - t0) * 1000)
            result["error_type"] = self._classify_connection_error(e)
            result["error_detail"] = str(e)
        except requests.exceptions.Timeout as e:
            result["elapsed_ms"] = int((time.time() - t0) * 1000)
            result["error_type"] = "TIMEOUT"
            result["error_detail"] = f"No response after {self.timeout}s"
        except requests.exceptions.RequestException as e:
            result["elapsed_ms"] = int((time.time() - t0) * 1000)
            result["error_type"] = "REQUEST_ERROR"
            result["error_detail"] = str(e)

        return result


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
            except Exception as exc:
                log.error("[batch_fetch_telemetry] device=%s exception: %s", did, exc)
                results[did] = {}
    return results
