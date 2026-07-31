"""
CYPHER65 // TAILSCALE ADAPTER
=============================
Remote access status checker for Tailscale.

Provides:
  - Check if Tailscale is running on the host
  - Query host's Tailscale IP/name
  - Validate remote connectivity via Tailscale API

Uses two sources:
  1. Local `tailscale status` / `tailscale ip` CLI (for self-info)
  2. Tailscale API v2 (for tailnet device discovery — optional, needs OAuth)

This adapter is intentionally lightweight — it wraps the CLI for local
inspection and exposes the REST API as a secondary source for advanced
features like "list devices in tailnet".
"""
import json
import logging
import requests
import shutil
import subprocess
import time
from typing import Optional

log = logging.getLogger("cypher65.tailscale")


def _run_tailscale_cli(*args: str) -> Optional[str]:
    """Run `tailscale <args>` and return stdout, or None on failure."""
    if not shutil.which("tailscale"):
        log.info("[tailscale] CLI not found in PATH")
        return None
    try:
        r = subprocess.run(
            ["tailscale", *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0:
            return r.stdout.strip()
        log.debug("[tailscale] CLI error (code=%d): %s", r.returncode, r.stderr.strip())
        return None
    except FileNotFoundError:
        log.info("[tailscale] tailscale binary not found")
        return None
    except subprocess.TimeoutExpired:
        log.warning("[tailscale] CLI timed out")
        return None
    except Exception as e:
        log.warning("[tailscale] CLI error: %s", e)
        return None


def get_local_status() -> dict:
    """Check local Tailscale status.

    Returns a dict with:
      - tailscale_installed (bool): whether the tailscale binary exists
      - connected (bool): whether tailscale is running and connected
      - ip (str): Tailscale IPv4 address (e.g. "100.x.x.x")
      - hostname (str): device name in the tailnet
      - magic_dns_name (str): e.g. "hostname.tailnet-name.ts.net"
      - last_seen (str): relative time
      - online (bool): whether this device is visible to the tailnet
    """
    result = {
        "tailscale_installed": False,
        "connected": False,
        "ip": None,
        "hostname": None,
        "magic_dns_name": None,
        "last_seen": None,
        "online": False,
        "error": None,
        "checked_at": int(time.time()),
    }

    # Check if tailscale binary exists
    if not shutil.which("tailscale"):
        result["error"] = "Tailscale CLI not found on this host"
        return result

    result["tailscale_installed"] = True

    # Get device IP
    ip_out = _run_tailscale_cli("ip", "-4")
    if ip_out:
        result["ip"] = ip_out.strip()
        result["connected"] = True
    else:
        result["error"] = "tailscale is not running or not connected"
        return result

    # Get status JSON for more details
    status_out = _run_tailscale_cli("status", "--json")
    if status_out:
        try:
            status_data = json.loads(status_out)
            self_entry = status_data.get("Self", {})
            result["hostname"] = self_entry.get("HostName", "")
            result["online"] = self_entry.get("Online", False)
            tailnet_name = status_data.get("MagicDNSSuffix", "")
            if result["hostname"] and tailnet_name:
                result["magic_dns_name"] = f"{result['hostname']}.{tailnet_name}"
        except (json.JSONDecodeError, AttributeError):
            pass

    # Fallback: get device name from `tailscale status` text
    if not result["hostname"]:
        status_text = _run_tailscale_cli("status")
        if status_text:
            for line in status_text.splitlines():
                if line.strip().startswith(result["ip"]):
                    parts = line.split()
                    if len(parts) >= 2:
                        result["hostname"] = parts[1].split(".")[0]

    return result


def check_remote_device(api_key: str = "", tailnet: str = "", device_filter: str = "") -> dict:
    """Check Tailscale API v2 for remote device status.

    This is optional — requires an OAuth client or API key from
    https://login.tailscale.com/admin/settings/keys

    Args:
        api_key: Tailscale API access token (OAuth or static key)
        tailnet: Tailnet name (or "-" for current)
        device_filter: Optional hostname substring to filter by

    Returns:
        dict with 'devices' list and aggregate 'status'
    """

    result = {
        "api_available": bool(api_key),
        "devices": [],
        "device_count": 0,
        "online_count": 0,
        "error": None,
    }

    if not api_key:
        return result

    try:
        tailnet = tailnet or "-"
        resp = requests.get(
            f"https://api.tailscale.com/api/v2/tailnet/{tailnet}/devices",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if resp.status_code != 200:
            result["error"] = f"API returned HTTP {resp.status_code}"
            return result

        data = resp.json().get("devices", [])
        filtered = data
        if device_filter:
            filtered = [d for d in data if device_filter.lower() in d.get("hostname", "").lower()]

        result["devices"] = [
            {
                "id": d.get("id", ""),
                "name": d.get("name", ""),
                "hostname": d.get("hostname", ""),
                "addresses": d.get("addresses", []),
                "ipv4": next((a for a in d.get("addresses", []) if a.startswith("100.")), None),
                "os": d.get("os", ""),
                "online": d.get("online", False),
                "last_seen": d.get("lastSeen", ""),
                "created": d.get("created", ""),
            }
            for d in filtered
        ]
        result["device_count"] = len(result["devices"])
        result["online_count"] = sum(1 for d in result["devices"] if d["online"])

    except Exception as e:
        log.warning("[tailscale] API error: %s", e)
        result["error"] = str(e)

    return result


def diagnose_connection(remote_ip: str = "", timeout: int = 5) -> dict:
    """Test direct HTTP connectivity to a remote host (e.g. another
    tailnet device serving this dashboard).

    Args:
        remote_ip: Tailscale IP of the remote host
        timeout: HTTP timeout in seconds

    Returns:
        dict with connectivity test results
    """

    result = {
        "remote_ip": remote_ip,
        "reachable": False,
        "http_status": None,
        "elapsed_ms": None,
        "error": None,
    }

    if not remote_ip:
        result["error"] = "no remote IP provided"
        return result

    try:
        t0 = time.time()
        r = requests.get(f"http://{remote_ip}:8765/api/healthz", timeout=timeout)
        elapsed = int((time.time() - t0) * 1000)
        result["reachable"] = r.status_code == 200
        result["http_status"] = r.status_code
        result["elapsed_ms"] = elapsed
        if not result["reachable"]:
            result["error"] = f"HTTP {r.status_code}"
    except requests.exceptions.ConnectionError as e:
        result["error"] = f"connection refused: {e}"
    except requests.exceptions.Timeout:
        result["error"] = f"timed out after {timeout}s"
    except Exception as e:
        result["error"] = str(e)

    return result
