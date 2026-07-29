"""
CYPHER65 // Firmware Detector
==============================
Auto-detect the firmware of an ASIC by trying known API endpoints
in order. Returns the best-matching adapter type and detected capabilities.

Detection order:
1. AxeOS/ESP-Miner (REST HTTP, port 80)
2. cgminer/BMMiner (socket TCP, port 4028)
3. Unknown / unreachable
"""
import json
import logging
import socket
import time

import requests

log = logging.getLogger(__name__)

# Timeout for detection attempts (seconds)
DETECT_TIMEOUT = 3


def detect_firmware(ip_address: str) -> dict:
    """Detect firmware type by probing known API endpoints.

    Returns:
        dict with keys:
          - firmware: str ("axeos", "cgminer", "unknown")
          - adapter_type: str ("bitaxe", "cgminer", "unknown")
          - version: str (detected version string)
          - model: str (detected model)
          - capabilities: dict (detected capabilities)
          - reachable: bool
    """
    result = {
        "firmware": "unknown",
        "adapter_type": "unknown",
        "version": "",
        "model": "",
        "capabilities": {},
        "reachable": False,
    }

    # 1. Try AxeOS/ESP-Miner REST API
    try:
        r = requests.get(f"http://{ip_address}/api/system/info", timeout=DETECT_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            result.update({
                "firmware": "axeos",
                "adapter_type": "bitaxe",
                "version": str(data.get("version", "")),
                "model": str(data.get("model", "")),
                "reachable": True,
            })
            # Detect capabilities from hashrate presence
            if data.get("hashrate") is not None:
                result["capabilities"] = {
                    "telemetry": True,
                    "restart": True,
                    "identify": True,
                }
            if data.get("frequency") is not None:
                result["capabilities"]["frequencyControl"] = True
            return result
    except (requests.ConnectionError, requests.Timeout, json.JSONDecodeError):
        pass

    # 2. Try cgminer protocol (TCP port 4028)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(DETECT_TIMEOUT)
        sock.connect((ip_address, 4028))
        sock.send(b'{"command":"version"}\n')
        data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\x00" in chunk:
                break
        sock.close()

        text = data.decode(errors="replace").rstrip("\x00").strip()
        if text:
            parsed = json.loads(text)
            version_data = parsed.get("VERSION", [{}])
            if isinstance(version_data, list) and version_data:
                v = version_data[0]
                result.update({
                    "firmware": "cgminer",
                    "adapter_type": "cgminer",
                    "version": str(v.get("Version", "")),
                    "model": str(v.get("Type", "")),
                    "reachable": True,
                    "capabilities": {
                        "telemetry": True,
                        "restart": True,
                        "set_frequency": False,
                    },
                })
                return result
    except (socket.timeout, ConnectionRefusedError, OSError, json.JSONDecodeError):
        pass

    return result
