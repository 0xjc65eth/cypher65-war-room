"""
CYPHER65 // AXE FLEET — LAN Miner Discovery (subnet scan)
==========================================================
Automatic detection of miners on the local network so the operator never
has to type an IP manually.

Two detection paths, each with a short per-host timeout and a parallel
scan loop:

  1. Bitaxe / AxeOS / NerdAxe — HTTP API on port 80 (`/api/system/info`).
  2. cgminer / BMMiner / Braiins stock — JSON-over-TCP protocol on port 4028
     (the `version` command is a cheap fingerprint probe).

Pure functions (parse_cidr, _probe_cgminer_version, suggest_subnets) are
mirrored in tests/test_axe_fleet_scanner.py. The scan itself is I/O-bound
and intentionally run from a background thread by the Flask routes so a
/24 scan (~250 hosts, ~1s timeout each, 64 workers) never blocks a request.

Safety model: this module only reads device identity (model/hostname/
firmware/hashrate). It never sends writes, never stores results, and only
runs while the operator explicitly asks for a scan via the fleet UI.
"""
import ipaddress
import json
import logging
import re
import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

log = logging.getLogger("cypher65.axe.scanner")

# ── Timeouts / limits ─────────────────────────────────────────────────────
HTTP_PROBE_TIMEOUT = 1.2   # seconds per Bitaxe HTTP probe
TCP_PROBE_TIMEOUT = 0.9    # seconds per cgminer TCP probe
SCAN_WORKERS = 64          # concurrent probes (parallel /24 in ~4-6s)
MAX_HOSTS_PER_SCAN = 1024  # hard cap: a /22 = 1024 hosts is already huge

CGMINER_PORT = 4028
BITAXE_PORT = 80
HTTPS_PORT = 443

# Alive-presence probe timeout: a TCP connect that opens a port marks the
# host "up but not a miner" — capped low so firewalled subnets don't explode
# scan wall time (on top of the HTTP/TCP probe timeouts already spent).
ALIVE_PROBE_TIMEOUT = 0.4

# cgminer-family line terminators: \x00 (stock cgminer/BMMiner) and ~ (some
# Avalon builds). NOTE: newline is deliberately NOT an EOL token — strict
# cgminer is single-line JSON + \x00, and cutting at the first \n would
# truncate pretty-printed multi-line responses; _extract_json_lenient handles
# any line framing instead.
_CGMINER_EOL_TOKENS = (b"\x00", b"\x7e")


def _extract_json_lenient(raw: bytes):
    """Parse a JSON object out of a cgminer-family response even when the
    device wraps it in junk (leading banner, tilde frames, stray bytes,
    multi-line pretty-printing). Tries strict json.loads first, then the
    first balanced {...} block. Returns None when nothing JSON-like is
    present. Never raises."""
    text = raw.decode(errors="replace").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        return None
    try:
        parsed = json.loads(m.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _tcp_open(ip: str, port: int, timeout: float = ALIVE_PROBE_TIMEOUT) -> bool:
    """True when a TCP connect to ip:port succeeds (host is up and the
    port is listening) — regardless of protocol. Cheap, never raises."""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False

# ── Private / non-routable detection ──────────────────────────────────────
# RFC1918 + CGNAT + loopback + link-local ranges only exist INSIDE the
# network that owns them. A cloud-hosted dashboard (e.g. Render) can NEVER
# route to them, so a failed probe against one is a network-topology problem
# — not necessarily a dead miner. Surfacing this in the wizard saves the
# operator from chasing power/firewall on a miner that is actually fine.
PRIVATE_IP_HINT = (
    "IP privado (LAN) — este host não roteia para a rede caseira. Rode o app "
    "na MESMA Wi-Fi/local do miner (self-host), use um IP do Tailscale, ou — "
    "no modelo SaaS — instale o AGENTE LOCAL (Fleet → CONNECT AGENT): ele "
    "roda na sua rede e conecta para fora."
)

# Cloud variant: the dashboard itself is on a PaaS (Render etc.) — it is NOT
# part of the user's tailnet, so a Tailscale IP is unreachable from here too.
# The ONLY working path is the local agent connecting OUT from the user's LAN.
PRIVATE_IP_HINT_CLOUD = (
    "IP privado (LAN) — este dashboard está hospedado na NUVEM (ex. Render) "
    "e não roteia para a rede da sua casa. Instale o AGENTE LOCAL "
    "(Fleet → CONNECT AGENT): ele roda na sua rede (Docker/Pi/PC), descobre "
    "os miners e conecta para fora — é a única via que funciona no SaaS."
)


def private_ip_hint() -> str:
    """Topology hint text, aware of the deployment mode. On a cloud host the
    Tailscale suggestion is wrong (the cloud box is not in the user's
    tailnet), so the SaaS text points exclusively to the local agent."""
    try:
        from config import is_cloud_deploy
        if is_cloud_deploy():
            return PRIVATE_IP_HINT_CLOUD
    except Exception:  # noqa: BLE001 — hint must never crash a probe
        pass
    return PRIVATE_IP_HINT


def is_private_ip(ip: str) -> bool:
    """True for RFC1918 / CGNAT / loopback / link-local IPv4 addresses.

    These ranges are only routable inside the network that owns them, so a
    cloud host can never reach them. Pure — mirrored in
    tests/test_axe_fleet_scanner.py."""
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(str(ip).strip())
    except ValueError:
        return False
    if addr.version != 4:
        return False
    # CGNAT 100.64/10 changed classification across Python versions (it is
    # NOT is_private on 3.14), so check it explicitly.
    if addr in ipaddress.ip_network("100.64.0.0/10"):
        return True
    return addr.is_private or addr.is_loopback or addr.is_link_local


# ── CIDR / range parsing ─────────────────────────────────────────────────

def parse_cidr(cidr: str) -> list:
    """Expand a CIDR / range / single host into a list of IP strings.

    Accepts:
      - '192.168.1.0/24'        (CIDR, capped at MAX_HOSTS_PER_SCAN)
      - '192.168.1.5-60'        (inclusive range)
      - '192.168.1.7'           (single IP)
      - 'miner.local'           (hostname → resolves to its IPs)
    Returns [] for malformed input (never raises).
    """
    if not cidr:
        return []
    cidr = str(cidr).strip()
    try:
        # CIDR form. Note: Python 3.8+ .hosts() already treats /31 and /32 as
        # point-to-point (returns the whole network — both addresses for a
        # /31, the single address for a /32), so no special-casing needed.
        if "/" in cidr:
            net = ipaddress.ip_network(cidr, strict=False)
            hosts = [str(h) for h in net.hosts()]
            return hosts[:MAX_HOSTS_PER_SCAN]
        # Range form: a.b.c.x-y
        if "-" in cidr:
            base, _, last = cidr.rpartition("-")
            if base and base.count(".") == 3 and last.isdigit():
                head = ".".join(base.split(".")[:3])
                first = int(base.split(".")[3])
                end = int(last)
                if first < 0 or end < first or end - first + 1 > MAX_HOSTS_PER_SCAN:
                    return []
                return [f"{head}.{i}" for i in range(first, end + 1)]
        # Single IP
        ipaddress.ip_address(cidr)
        return [cidr]
    except ValueError:
        pass
    # Hostname fallback (resolve)
    try:
        infos = socket.getaddrinfo(cidr, None, socket.AF_INET)
        seen = []
        for info in infos:
            ip = info[4][0]
            if ip not in seen:
                seen.append(ip)
        return seen
    except socket.gaierror:
        return []


# ── Individual host probe ────────────────────────────────────────────────

def _probe_cgminer_version(ip: str, port: int = CGMINER_PORT, timeout: float = TCP_PROBE_TIMEOUT):
    """Fingerprint a cgminer-family miner via the JSON-over-TCP `version`
    command. Returns parsed version dict or None. Never raises.

    Tolerant framing (C): accepts `\x00` (stock cgminer/BMMiner), `~` (some
    Avalon builds) or newline terminators, and falls back to lenient JSON
    extraction when the response carries leading garbage."""
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, port))
        sock.sendall(b'{"command":"version"}\n')
        data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
            if any(tok in chunk for tok in _CGMINER_EOL_TOKENS) or len(data) > 65536:
                break
        return _extract_json_lenient(data)
    except (socket.timeout, OSError, json.JSONDecodeError) as e:
        log.debug("[scan] cgminer probe %s:%s failed: %s", ip, port, e)
        return None
    finally:
        if sock:
            try:
                sock.close()
            except OSError:
                pass


def probe_host(ip: str, timeout: float = HTTP_PROBE_TIMEOUT) -> dict:
    """Probe a single host for miner identity.

    Uses ``detect_firmware()`` (core/registry/detector.py) as the primary
    detection path — this automatically identifies AxeOS, Braiins OS+ and
    generic cgminer devices in the correct order.

    Returns a discovery dict (or None when nothing miner-like responds):
      {
        'ip', 'type' ('bitaxe'|'braiins'|'cgminer'), 'port',
        'model', 'hostname', 'firmware', 'version', 'hashrate_hs',
        'mac', 'pool_url', 'pool_user',
      }
    Never raises — network failures yield None.
    """
    if not ip:
        return None
    ip = str(ip).strip()

    # ── Unified detection via core/registry/detector ───────────────────
    from core.registry.detector import detect_firmware

    fw = detect_firmware(ip)
    if not fw or not fw.get("reachable"):
        return None

    adapter_type = fw.get("adapter_type", "unknown")
    firmware = fw.get("firmware", "")
    version = fw.get("version", "")
    model = fw.get("model", "")

    # ── Rich info for AxeOS devices (AxeOSConnector gives hostname, hashrate, pool) ──
    hostname = ""
    hashrate_hs = 0
    mac = ""
    pool_url = ""
    pool_user = ""

    if adapter_type == "bitaxe":
        try:
            from .connector import AxeOSConnector
            conn = AxeOSConnector(ip, timeout=timeout)
            info = conn.fetch_info()
            if isinstance(info, dict):
                hostname = str(info.get("hostname", ""))
                mac = str(info.get("mac", ""))
                try:
                    hashrate_hs = int(info.get("hashrate") or 0)
                except (TypeError, ValueError):
                    hashrate_hs = 0
                pool = info.get("pool")
                if isinstance(pool, dict):
                    pool_url = str(pool.get("url", ""))
                    pool_user = str(pool.get("user", ""))
                else:
                    pool_url = str(info.get("poolUrl", ""))
                    pool_user = str(info.get("poolUser", ""))
                if not model:
                    model = str(info.get("model") or info.get("board") or "Bitaxe")
        except Exception as e:  # noqa: BLE001
            log.debug("[scan] AxeOSConnector rich-info failed for %s: %s", ip, e)

    elif adapter_type == "braiins":
        # Braiins OS+ detected via REST API or cgminer socket — the detector
        # already captured firmware/version/model from the API response.
        # Rich info (hashrate/hostname) requires an extra cgminer 'summary'
        # call on port 4028.
        port = CGMINER_PORT
        try:
            ver = _probe_cgminer_version(ip)
            if ver and ver.get("STATUS"):
                # Try 'summary' for hashrate
                summary = None
                sock = None
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(TCP_PROBE_TIMEOUT)
                    sock.connect((ip, CGMINER_PORT))
                    sock.sendall(b'{"command":"summary"}\n')
                    data = b""
                    while True:
                        chunk = sock.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                        if any(tok in chunk for tok in _CGMINER_EOL_TOKENS) or len(data) > 65536:
                            break
                    summary = _extract_json_lenient(data)
                except Exception:
                    pass
                finally:
                    if sock:
                        try:
                            sock.close()
                        except OSError:
                            pass

                if summary and summary.get("STATUS"):
                    summary_data = summary.get("SUMMARY", [{}])
                    if isinstance(summary_data, list) and summary_data:
                        sd = summary_data[0]
                        try:
                            hashrate_hs = int(float(sd.get("GHS 5s", sd.get("GHS av", 0)) or 0) * 1e9)
                        except (ValueError, TypeError):
                            hashrate_hs = 0
        except Exception as e:
            log.debug("[scan] braiins rich-info failed for %s: %s", ip, e)

    elif adapter_type == "cgminer":
        port = CGMINER_PORT
        if not model:
            model = fw.get("model") or "cgminer"

    return {
        "ip": ip,
        "type": adapter_type,
        "port": BITAXE_PORT if adapter_type == "bitaxe" else CGMINER_PORT,
        "model": model or adapter_type,
        "hostname": hostname,
        "firmware": firmware,
        "version": version,
        "hashrate_hs": hashrate_hs,
        "mac": mac,
        "pool_url": pool_url,
        "pool_user": pool_user,
    }


# ── Single-host connectivity diagnosis ──────────────────────────────────

def diagnose_host(ip: str, timeout: float = HTTP_PROBE_TIMEOUT) -> dict:
    """Deep connectivity diagnosis for a single host (onboarding wizard).

    Runs every probe available for one IP and returns a unified result so the
    UI can show a step-by-step check (DNS → AxeOS HTTP → Braiins → cgminer TCP)
    before the operator commits to registering the device. Never raises.

    Detection now uses ``detect_firmware()`` (core/registry/detector.py) as a
    supplemental path that correctly identifies Braiins OS+ devices (REST
    :80/:50051 or cgminer socket with "BOSminer" version string).

    Returns:
      {
        'ip', 'port',
        'dns_resolution': bool,      # hostname resolved (IPs are always OK)
        'bitaxe_http': bool,         # AxeOS/ESP-Miner API answered on :80
        'cgminer_tcp': bool,         # cgminer protocol answered on :4028
        'https_tcp': bool,           # TCP :443 open (modern Braiins/Antminer)
        'http_server': bool,         # TCP :80 open but NOT ESP-Miner (auth page)
        'reachable': bool,           # any protocol detected
        'protocol': 'bitaxe'|'braiins'|'cgminer'|None,
        'adapter_type': str,         # canonical adapter type (bitaxe/braiins/cgminer)
        'detected_firmware': str,    # firmware label (e.g. "Braiins OS+")
        'detected_model': str,       # model from auto-detection
        'device_info': {...} | None, # model/hostname/firmware/hashrate when detected
        'elapsed_ms': int,
        'error_detail': str | None,
      }
    """
    ip = str(ip or "").strip()
    t0 = time.time()
    result = {
        "ip": ip,
        "dns_resolution": False,
        "bitaxe_http": False,
        "cgminer_tcp": False,
        "https_tcp": False,
        "http_server": False,
        "reachable": False,
        "protocol": None,
        "adapter_type": "",
        "detected_firmware": "",
        "detected_model": "",
        "device_info": None,
        "elapsed_ms": 0,
        "error_detail": None,
    }
    if not ip:
        result["error_detail"] = "empty host"
        return result

    # DNS / IP validation
    try:
        ipaddress.ip_address(ip)
        result["dns_resolution"] = True
    except ValueError:
        try:
            socket.getaddrinfo(ip, None, socket.AF_INET)
            result["dns_resolution"] = True
        except socket.gaierror as e:
            result["error_detail"] = f"DNS failure: {e}"
            result["elapsed_ms"] = int((time.time() - t0) * 1000)
            return result

    # Path 1 — Bitaxe / AxeOS HTTP
    try:
        from .connector import AxeOSConnector
        conn = AxeOSConnector(ip, timeout=timeout)
        info = conn.fetch_info()
        if isinstance(info, dict):
            result["bitaxe_http"] = True
            result["reachable"] = True
            result["protocol"] = "bitaxe"
            result["device_info"] = {
                "model": str(info.get("model") or info.get("board") or "Bitaxe"),
                "hostname": str(info.get("hostname", "")),
                "firmware": str(info.get("firmware", "")),
                "version": str(info.get("version", "")),
                "hashrate_hs": 0,
            }
            try:
                result["device_info"]["hashrate_hs"] = int(info.get("hashrate") or 0)
            except (TypeError, ValueError):
                pass
    except Exception as e:  # noqa: BLE001 — probe must never raise
        log.debug("[scan] diagnose bitaxe %s failed: %s", ip, e)

    # Path 2 — cgminer JSON-over-TCP (only if HTTP didn't already win)
    if not result["bitaxe_http"]:
        ver = _probe_cgminer_version(ip, timeout=timeout)
        if ver and ver.get("STATUS"):
            result["cgminer_tcp"] = True
            result["reachable"] = True
            result["protocol"] = "cgminer"
            model = ""
            for entry in (ver.get("VERSION") or []):
                if isinstance(entry, dict):
                    model = str(entry.get("Description") or entry.get("Type") or entry.get("Miner") or "")
                    break
            version = ""
            if isinstance(ver.get("VERSION"), list) and ver.get("VERSION"):
                version = str(ver["VERSION"][0].get("CGMiner") or "")
            result["device_info"] = {
                "model": model or "cgminer",
                "hostname": "",
                "firmware": "",
                "version": version,
                "hashrate_hs": 0,
            }

    # ── Supplemental: detect_firmware() for Braiins OS+ ─────────────────
    # The legacy AxeOS+cgminer probes above may miss Braiins OS+ devices
    # (REST :80/:50051 + cgminer socket "BOSminer"). Only run the unified
    # detector when nothing was found yet — it makes its own HTTP requests
    # (3s timeout each) and adds latency with no benefit when legacy probes
    # already succeeded.
    if not result["reachable"]:
        try:
            from core.registry.detector import detect_firmware
            fw = detect_firmware(ip)
            if fw and fw.get("reachable"):
                adapter = fw.get("adapter_type", "")
                result["adapter_type"] = adapter
                result["detected_firmware"] = fw.get("firmware", "")
                result["detected_model"] = fw.get("model", "")
                if adapter:
                    result["reachable"] = True
                    result["protocol"] = adapter
                    if not result["device_info"]:
                        result["device_info"] = {
                            "model": fw.get("model", adapter),
                            "hostname": "",
                            "firmware": fw.get("firmware", ""),
                            "version": fw.get("version", ""),
                            "hashrate_hs": 0,
                        }
                    # Mark the correct probe flag so the connectivity report
                    # shows the right row.
                    if adapter == "braiins":
                        result["cgminer_tcp"] = True
        except Exception:
            pass  # supplemental probe must never break the diagnosis

    if not result["reachable"]:
        detail = result["error_detail"] or "no miner protocol responded (checked AxeOS :80, Braiins :80/:50051 and cgminer :4028)"
        # D · Protocol-presence probes: even when no miner protocol answered,
        # a TCP :443 or a non-ESP-Miner web server on :80 is strong evidence
        # of a MODERN authenticated miner (Braiins OS+/Antminer login page).
        # Surface it instead of a flat "no miner protocol".
        if _tcp_open(ip, HTTPS_PORT):
            result["https_tcp"] = True
            detail = f"{detail} · porta TCP :443 aberta — possível firmware moderno (Braiins OS+/Antminer) com API autenticada; tente a porta 443 ou autentique no painel do miner"
        if _tcp_open(ip, BITAXE_PORT):
            result["http_server"] = True
            detail = f"{detail} · porta TCP :80 aberta mas NÃO respondeu como ESP-Miner — pode ser a página de login de um ASIC (Antminer/Braiins) que exige auth"
        # Private LAN target + nothing answered = almost certainly a
        # network-topology gap (cloud host vs local miner), not a dead miner.
        # Append the actionable hint so the wizard explains WHY it's
        # unreachable instead of a generic "check power / network / firewall".
        if is_private_ip(ip):
            detail = f"{detail} · {private_ip_hint()}"
        result["error_detail"] = detail
    result["elapsed_ms"] = int((time.time() - t0) * 1000)
    return result


# ── Concurrent subnet scan ───────────────────────────────────────────────

def _cidr_is_private(cidr: str) -> bool:
    """True when the CIDR targets a private (RFC1918/CGNAT/etc.) block — used
    to attach the cloud-vs-LAN topology hint to empty scans. Parses the
    network directly (no host-list expansion, no DNS resolution for
    hostname inputs — a hostname is never a "private CIDR" anyway).
    Never raises."""
    if not cidr:
        return False
    cidr = str(cidr).strip()
    try:
        if "/" in cidr:
            net = ipaddress.ip_network(cidr, strict=False)
            return is_private_ip(str(net.network_address))
        if "-" in cidr:
            base, _, _ = cidr.rpartition("-")
            return is_private_ip(base)
        return is_private_ip(cidr)
    except ValueError:
        return False


def scan_subnet(cidr: str, progress_cb=None, max_hosts: int = MAX_HOSTS_PER_SCAN,
                timeout: float = HTTP_PROBE_TIMEOUT, workers: int = SCAN_WORKERS) -> dict:
    """Scan a subnet/range for miners.

    Returns:
      {'cidr', 'total', 'found': [discovery dicts...], 'alive': int,
       'alive_ips': [str...], 'hint': str|None, 'elapsed_ms', 'error'}

    - `alive` / `alive_ips`: hosts whose TCP port 80 or 4028 opened (host is
      up) but no miner protocol answered — the "alive but not a miner" layer
      that turns a flat "no miners found" into an actionable diagnosis.
    - `hint`: private-LAN topology hint when the scanned CIDR is a private
      range AND nothing was found — the cloud-dashboard-vs-home-LAN gap.

    `progress_cb(scanned, total)` is invoked after every host completes so
    callers can stream progress to the UI.
    """
    hosts = parse_cidr(cidr)
    t0 = time.time()
    if not hosts:
        return {"cidr": cidr, "total": 0, "found": [], "alive": 0, "alive_ips": [],
                "hint": None, "elapsed_ms": 0, "error": "invalid or empty subnet"}
    hosts = hosts[:max_hosts]
    found = []
    alive_ips = []
    scanned = 0
    try:
        with ThreadPoolExecutor(max_workers=min(workers, max(1, len(hosts)))) as ex:
            futures = {ex.submit(probe_host, ip, timeout): ip for ip in hosts}
            for fut in as_completed(futures):
                scanned += 1
                ip = futures[fut]
                try:
                    result = fut.result()
                except Exception as e:  # noqa: BLE001 — per-host isolation
                    log.debug("[scan] probe exception: %s", e)
                    result = None
                if result:
                    found.append(result)
                elif _tcp_open(ip, BITAXE_PORT) or _tcp_open(ip, CGMINER_PORT):
                    # Alive (a TCP port opened) but no miner protocol — the
                    # host could be a router/switch/PC or a miner with a
                    # firewalled/authenticated API. Reported separately so the
                    # operator knows the subnet is reachable.
                    alive_ips.append(ip)
                if progress_cb:
                    try:
                        progress_cb(scanned, len(hosts))
                    except Exception:
                        pass
    except Exception as e:  # noqa: BLE001 — scan must never crash the caller
        return {"cidr": cidr, "total": len(hosts), "found": found, "alive": len(alive_ips),
                "alive_ips": alive_ips, "hint": None,
                "elapsed_ms": int((time.time() - t0) * 1000), "error": str(e)}
    # Most-recent-first keeps the freshest discovery on top.
    found.sort(key=lambda d: (d.get("hashrate_hs") or 0), reverse=True)
    # A · topology hint: private CIDR scanned + nothing found at all → the
    # dashboard is very likely cloud-hosted and cannot route to the home LAN.
    hint = None
    if not found and not alive_ips and _cidr_is_private(cidr):
        hint = private_ip_hint()
    return {"cidr": cidr, "total": len(hosts), "found": found, "alive": len(alive_ips),
            "alive_ips": alive_ips, "hint": hint,
            "elapsed_ms": int((time.time() - t0) * 1000), "error": None}


# ── Local subnet suggestion ──────────────────────────────────────────────

def _local_ipv4_addresses() -> list:
    """Best-effort list of this host's IPv4 addresses (public + private).
    Never raises."""
    out = []
    # UDP trick: connect() to a non-routable target binds a real source IP
    # without sending packets.
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        out.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    # Hostname resolution covers more interfaces.
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in out:
                out.append(ip)
    except OSError:
        pass
    return out


def suggest_subnets() -> list:
    """Suggest scan subnets based on this host's local interfaces.
    Returns a list of CIDR strings (e.g. ['192.168.1.0/24']).

    On a CLOUD deployment this returns [] — the host's interfaces belong to
    the PaaS VPC, NOT the user's home LAN, so prefilling that subnet would
    send the operator scanning the wrong network (and finding nothing). The
    SaaS answer is the local agent, not a scan."""
    try:
        from config import is_cloud_deploy
        if is_cloud_deploy():
            return []
    except Exception:  # noqa: BLE001 — suggestion is best-effort
        pass
    subnets = []
    seen = set()
    for ip in _local_ipv4_addresses():
        parts = ip.split(".")
        # Only real IPv4 addresses qualify (octets are numeric) — loopback
        # (127.x) and link-local (169.254.x) are never worth scanning.
        if len(parts) == 4 and all(p.isdigit() for p in parts):
            if parts[0] in ("127", "169", "0", "255"):
                continue
            cidr = f"{'.'.join(parts[:3])}.0/24"
            if cidr not in seen:
                seen.add(cidr)
                subnets.append(cidr)
    return subnets
