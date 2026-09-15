"""
CYPHER65 // LAN Scanner — Auto-Discovery of Mining Devices
===========================================================
Discovers ASIC miners on the local network using:
  1. **ARP cache** — fast, no extra traffic, works on all OSes
  2. **TCP port probes** — cheap connect() to the candidate miner ports
     (80/443/4028/50051/8080) with a 200ms timeout per port
  3. **mDNS** — looks for _http._tcp services as extra candidates
  4. **Protocol identification** — asks a real miner protocol (AxeOS REST →
     Braiins OS+ REST → cgminer socket) and labels the host from the ANSWER

Steps 2 and 3 only produce CANDIDATES. ``firmware_hint`` is set exclusively
from validated protocol evidence in step 4, because an open TCP port is not a
firmware: routers, NAS panels, printers and TVs answer on :80 too, and
labelling them as miners is how a fleet fills up with phantom "braiins" rows.

Thread-pooled so 254 IPs scan in a few seconds. Results deduplicated by IP.
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

# ── Candidate ports to probe ────────────────────────────────────────────
# These are CANDIDATE ports only. An open TCP port is NEVER on its own
# evidence of a firmware — Phase 3 asks a real miner protocol and labels the
# host from the ANSWER (see _identify_miner). Ports follow the firmwares this
# repo actually supports: AxeOS/ESP-Miner and Braiins OS+ REST on :80, the
# Braiins OS+ REST alternate on :50051, cgminer JSON-over-TCP on :4028,
# modern authenticated firmware behind TLS on :443, and alternate web UIs
# on :8080.
PORT_SIGNATURES = {
    80: "http",  # AxeOS/ESP-Miner + Braiins OS+ REST
    443: "https",  # modern firmware behind TLS (Braiins OS+/Antminer)
    4028: "cgminer",  # cgminer/BMMiner/BOSminer JSON-over-TCP
    50051: "braiins_rest",  # Braiins OS+ REST on the non-standard port
    8080: "alt_http",  # alternate web UI (some firmware revisions)
}

# Canonical adapter types returned by core/registry/detector.detect_firmware()
# that we are willing to surface as a firmware hint.
_FIRMWARE_HINTS = {
    "bitaxe": "bitaxe",  # AxeOS/ESP-Miner
    "braiins": "braiins",  # Braiins OS+
    "cgminer": "cgminer",  # cgminer/BMMiner/BOSminer over :4028
}

# Thread count for parallel scanning — keeps it under 3s for a /24 subnet
_MAX_WORKERS = 64
# Per-port connect timeout (seconds)
_PROBE_TIMEOUT = 0.2
# Per-protocol-probe timeout. Deliberately shorter than the registry default
# (3s): a /24 where every host runs a web server would otherwise stall the
# identification phase behind dozens of 3s timeouts.
_IDENTIFY_TIMEOUT = 1.5


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
                if len(parts) == 4 and all(
                    p.isdigit() and 0 <= int(p) <= 255 for p in parts
                ):
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
            ips = [
                prefix + str(i) for i in range(1, 255) if prefix + str(i) != local_ip
            ]
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


def _identify_miner(ip: str) -> Optional[str]:
    """Return the protocol-validated adapter type for *ip*, or None.

    Delegates to ``core/registry/detector.detect_firmware`` — the single
    source of truth for firmware identity (AxeOS REST → Braiins OS+ REST →
    cgminer socket). A host that opens a port but answers no miner protocol
    returns None and must not be presented as a miner. Never raises.
    """
    try:
        from core.registry.detector import detect_firmware

        fw = detect_firmware(ip, timeout=_IDENTIFY_TIMEOUT)
    except Exception as e:  # noqa: BLE001 — identity probe is best-effort
        log.debug("[lan_scanner] detect_firmware failed for %s: %s", ip, e)
        return None
    if not fw or not fw.get("reachable"):
        return None
    adapter = str(fw.get("adapter_type") or "")
    return adapter if adapter in _FIRMWARE_HINTS else None


def scan_network() -> Dict[str, Any]:
    """Scan the local network and return discovered mining devices.

    Returns:
        {
            "scanned": <int>,
            "found": <int>,          # miners (a protocol answered)
            "alive": <int>,          # hosts with a port open, no miner protocol
            "alive_ips": [str],
            "devices": [{ip, open_ports: [int], firmware_hint: str,
                         miner_protocol: str, hostname: str|null}],
            "candidates": [{ip, open_ports: [int], firmware_hint: None,
                            miner_protocol: None, hostname: str|null}],
            "duration_ms": <int>,
        }

    ``firmware_hint`` is set ONLY from a validated miner protocol, and only
    such hosts land in ``devices``. Hosts that merely have a port open
    (routers, NAS, printers, TVs) go to ``candidates`` instead — never dressed
    up as miners, never eligible for "+ Add" in the UI.
    """
    start = time.monotonic()

    # ── Phase 1: collect candidate IPs (ARP + subnet scan) ──────────
    arp_ips = _arp_table_ips()
    subnet_ips = _local_subnet_ips()
    candidates = list(dict.fromkeys(arp_ips + subnet_ips))  # dedup

    if not candidates:
        log.info("[lan_scanner] no candidates — ARP empty, subnet scan failed")
        return {"scanned": 0, "found": 0, "duration_ms": 0, "devices": []}

    log.info(
        "[lan_scanner] probing %d IPs × %d ports", len(candidates), len(PORT_SIGNATURES)
    )

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

    # ── Phase 3: mDNS discovery (candidates only) ──────────────────
    mdns_ips: set = set()
    try:
        mdns_out = subprocess.check_output(
            ["dns-sd", "-B", "_http._tcp", "local."],
            text=True,
            timeout=3,
            stderr=subprocess.DEVNULL,
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
                        text=True,
                        timeout=2,
                        stderr=subprocess.DEVNULL,
                    )
                    for rline in resolve.splitlines():
                        rline = rline.strip()
                        rparts = rline.split()
                        for w in rparts:
                            w = w.strip("().")
                            dots = w.split(".")
                            if len(dots) == 4 and all(p.isdigit() for p in dots):
                                if dots[0] not in ("0", "127", "224", "255"):
                                    mdns_ips.add(w)
                                    if w not in results:
                                        results[w] = {
                                            "ip": w,
                                            "open_ports": [],
                                            "hostname": instance,
                                            "discovered_via": "mdns",
                                        }
                except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
                    pass
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass  # dns-sd not available (Windows / containers)

    # ── Phase 4: protocol-validated identity ───────────────────────
    # An open TCP port is NOT a firmware. Ask a real miner protocol (AxeOS
    # REST → Braiins OS+ REST → cgminer socket) and label the host from the
    # ANSWER. A host that answers nothing keeps firmware_hint=None: it stays
    # visible through open_ports instead of being presented as a miner we
    # could neither read nor command.
    targets = [
        ip
        for ip, dev in results.items()
        if ip in mdns_ips or any(port in dev["open_ports"] for port in PORT_SIGNATURES)
    ]
    if targets:
        with ThreadPoolExecutor(
            max_workers=min(_MAX_WORKERS, len(targets))
        ) as executor:
            probes = {executor.submit(_identify_miner, ip): ip for ip in targets}
            for future in as_completed(probes):
                ip = probes[future]
                try:
                    protocol = future.result()
                except Exception as e:  # noqa: BLE001 — one host cannot abort the sweep
                    log.debug("[lan_scanner] identify failed for %s: %s", ip, e)
                    protocol = None
                results[ip]["miner_protocol"] = protocol
                results[ip]["firmware_hint"] = _FIRMWARE_HINTS.get(protocol)
    for dev in results.values():
        dev.setdefault("miner_protocol", None)
        dev.setdefault("firmware_hint", None)

    duration_ms = int((time.monotonic() - start) * 1000)
    hosts = sorted(results.values(), key=lambda d: tuple(d["ip"].split(".")))
    # `devices` are miners (a protocol answered). Everything else that merely
    # opened a port is reported separately as a `candidate` — the UI must not
    # offer "+ Add" for a router, and `found` must not count one.
    miner_devices = [d for d in hosts if d.get("miner_protocol")]
    other_hosts = [d for d in hosts if not d.get("miner_protocol")]

    return {
        "scanned": len(candidates),
        "found": len(miner_devices),
        "alive": len(other_hosts),
        "alive_ips": [d["ip"] for d in other_hosts],
        "devices": miner_devices,
        "candidates": other_hosts,
        "duration_ms": duration_ms,
    }
