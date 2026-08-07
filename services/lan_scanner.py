"""
CYPHER65 // LAN Scanner — Auto-Discovery of Mining Devices
===========================================================
Discovers ASIC miners on the local network using:
  1. **ARP cache** — fast, no extra traffic, works on all OSes
  2. **TCP port probes** — confirms cgminer (4028), Braiins REST (80),
     Bitaxe (8080) with a 200ms timeout per port
  3. **mDNS** — looks for _http._tcp services (Braiins OS+ advertises)

Thread-pooled so 254 IPs scan in ~3s. Results deduplicated by IP.
"""

import json
import logging
import platform
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ── Port signature → firmware hint mapping ──────────────────────────────
PORT_SIGNATURES = {
    4028: "cgminer",       # cgminer/BMMiner (Antminer, Whatsminer, Avalon, Braiins)
    80:   "braiins_rest",  # Braiins OS+ modern REST API
    8080: "bitaxe",        # Bitaxe AxeOS web UI
}

# Thread count for parallel scanning — keeps it under 3s for a /24 subnet
_MAX_WORKERS = 64
# Per-port connect timeout (seconds)
_PROBE_TIMEOUT = 0.2


def _arp_table_ips() -> List[str]:
    """Return a list of IP addresses from the system ARP cache.

    Cross-platform: uses ``arp -a`` on macOS/Linux/Windows.
    Filters out incomplete/invalid entries.
    """
    ips = []
    try:
        if platform.system() == "Windows":
            out = subprocess.check_output(["arp", "-a"], text=True, timeout=5)
        else:
            out = subprocess.check_output(["arp", "-a", "-n"], text=True, timeout=5)
        for line in out.splitlines():
            line = line.strip()
            if not line or "incomplete" in line.lower():
                continue
            # Extract IPv4 address
            for word in line.replace("(", " ").replace(")", " ").split():
                word = word.strip("()")
                parts = word.split(".")
                if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
                    ips.append(word)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        log.debug("[lan_scanner] ARP table read failed: %s", e)
    return list(dict.fromkeys(ips))  # dedup, preserve order


def _local_subnet_ips() -> List[str]:
    """Generate all IPs in the /24 subnet of each non-loopback interface.

    Falls back to a /24 around the host's primary IP when interfaces
    can't be enumerated.
    """
    ips = []
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        parts = local_ip.rsplit(".", 1)
        if len(parts) == 2:
            prefix = parts[0] + "."
            ips = [prefix + str(i) for i in range(1, 255) if prefix + str(i) != local_ip]
    except Exception:
        pass
    return ips


def _probe_port(ip: str, port: int) -> bool:
    """Return True if *port* on *ip* accepts a TCP connection within _PROBE_TIMEOUT."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(_PROBE_TIMEOUT)
        result = sock.connect_ex((ip, port))
        sock.close()
        return result == 0
    except OSError:
        return False


def scan_network() -> Dict[str, Any]:
    """Scan the local network and return discovered mining devices.

    Returns:
        {
            "scanned": <int>,
            "found": <int>,
            "duration_ms": <int>,
            "devices": [{ip, open_ports: [int], firmware_hint: str|null, hostname: str|null}],
        }
    """
    start = time.monotonic()

    # ── Phase 1: collect candidate IPs (ARP + subnet scan) ──────────
    arp_ips = _arp_table_ips()
    subnet_ips = _local_subnet_ips()
    candidates = list(dict.fromkeys(arp_ips + subnet_ips))  # dedup

    if not candidates:
        log.info("[lan_scanner] no candidates — ARP empty, subnet scan failed")
        return {"scanned": 0, "found": 0, "duration_ms": 0, "devices": []}

    log.info("[lan_scanner] probing %d IPs × %d ports", len(candidates), len(PORT_SIGNATURES))

    # ── Phase 2: parallel port probes ───────────────────────────────
    results: Dict[str, Dict] = {}  # ip → {ip, open_ports, hostname}

    def _probe_ip(ip: str):
        open_ports = []
        for port in sorted(PORT_SIGNATURES):
            if _probe_port(ip, port):
                open_ports.append(port)
        if open_ports:
            hostname = None
            try:
                hostname = socket.gethostbyaddr(ip)[0]
            except (socket.herror, socket.gaierror):
                pass
            return ip, {"ip": ip, "open_ports": open_ports, "hostname": hostname}
        return ip, None

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        futures = {executor.submit(_probe_ip, ip): ip for ip in candidates}
        for future in as_completed(futures):
            ip, data = future.result()
            if data:
                results[ip] = data

    # ── Phase 3: firmware hint from port signature ──────────────────
    for dev in results.values():
        ports = dev["open_ports"]
        if 4028 in ports and 80 in ports:
            dev["firmware_hint"] = "braiins"   # both cgminer + REST = Braiins OS+
        elif 4028 in ports:
            dev["firmware_hint"] = "cgminer"
        elif 8080 in ports:
            dev["firmware_hint"] = "bitaxe"
        elif 80 in ports:
            dev["firmware_hint"] = "braiins_rest"
        else:
            dev["firmware_hint"] = None

    # ── Phase 4: mDNS probe (optional, non-blocking best-effort) ────
    try:
        mdns_out = subprocess.check_output(
            ["dns-sd", "-B", "_http._tcp", "local."],
            text=True, timeout=3, stderr=subprocess.DEVNULL,
        )
        for line in mdns_out.splitlines():
            line = line.strip()
            if not line or "Timestamp" in line or "Browsing" in line:
                continue
            # dns-sd -B output:  Timestamp  Flags  If  Domain  ServiceType  InstanceName
            parts = line.split()
            if len(parts) >= 6:
                instance = parts[5]
                # Resolve the instance to get IP
                try:
                    resolve = subprocess.check_output(
                        ["dns-sd", "-q", instance + ".local."],
                        text=True, timeout=2, stderr=subprocess.DEVNULL,
                    )
                    for rline in resolve.splitlines():
                        rline = rline.strip()
                        rparts = rline.split()
                        for w in rparts:
                            w = w.strip("().")
                            dots = w.split(".")
                            if len(dots) == 4 and all(p.isdigit() for p in dots):
                                if dots[0] not in ("0", "127", "224", "255"):
                                    if w not in results:
                                        results[w] = {
                                            "ip": w,
                                            "open_ports": [],
                                            "hostname": instance,
                                            "firmware_hint": "braiins",
                                        }
                except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
                    pass
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass  # dns-sd not available (Windows / containers)

    duration_ms = int((time.monotonic() - start) * 1000)
    devices = sorted(results.values(), key=lambda d: tuple(d["ip"].split(".")))

    return {
        "scanned": len(candidates),
        "found": len(devices),
        "duration_ms": duration_ms,
        "devices": devices,
    }
