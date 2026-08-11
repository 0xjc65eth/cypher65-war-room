#!/usr/bin/env python3
"""
CYPHER65 // WAR ROOM — LOCAL AGENT (SaaS)
=========================================
Run this ON THE USER'S HOME NETWORK (Docker / Pi / any always-on box). The
agent connects OUT to the cloud dashboard (Render) — no open ports needed,
NAT/CGNAT safe — and:

  1. Discovers miners on the local LAN (AxeOS :80 / cgminer :4028 / HTTPS :443)
  2. Registers them with the cloud dashboard (tenant-scoped via agent token)
  3. Polls telemetry and pushes it in batches (every POLL_INTERVAL seconds)
  4. Pulls queued commands (restart/identify) and executes them locally

Env vars:
  CYPHER65_SERVER_URL     dashboard base URL, e.g. https://war-room.onrender.com
                          (default http://localhost:8765)
  CYPHER65_AGENT_TOKEN    agent JWT minted in the dashboard:
                          POST /api/agent/token (logged-in user) → token
  CYPHER65_POLL_INTERVAL  telemetry push interval, seconds (default 30)
  CYPHER65_SCAN_CIDR      optional override CIDR/range to scan; default =
                          derived from this host's local IPv4 /24s
  CYPHER65_DEVICES        optional comma-separated IPs (skip scan, poll only)

Run:  python3 agent.py        (stdlib only — no pip install needed)
"""
import json
import logging
import os
import re
import socket
import time
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

log = logging.getLogger("cypher65.agent")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s [%(name)s] %(message)s")

SERVER_URL = (os.environ.get("CYPHER65_SERVER_URL") or "http://localhost:8765").rstrip("/")
AGENT_TOKEN = os.environ.get("CYPHER65_AGENT_TOKEN") or ""
POLL_INTERVAL = int(os.environ.get("CYPHER65_POLL_INTERVAL") or 30)
SCAN_CIDR = os.environ.get("CYPHER65_SCAN_CIDR") or ""
EXPLICIT_DEVICES = [ip.strip() for ip in (os.environ.get("CYPHER65_DEVICES") or "").split(",") if ip.strip()]

HTTP_TIMEOUT = 2.0      # per AxeOS HTTP probe
TCP_TIMEOUT = 1.0       # per cgminer TCP probe
SCAN_WORKERS = 64
MAX_HOSTS = 1024
RESCAN_EVERY = 10       # full LAN re-scan every N poll cycles (new miners)

# Protocol ports. Defaults match real hardware (AxeOS HTTP :80, cgminer
# JSON-over-TCP :4028); overridable via env for test rigs/mock miners.
AXEOS_PORT = int(os.environ.get("CYPHER65_AXEOS_PORT") or 80)
CGMINER_PORT = int(os.environ.get("CYPHER65_CGMINER_PORT") or 4028)

# cgminer-family framing: most firmwares terminate JSON with \x00, some
# (Avalon) wrap frames in ~ (\x7e) tildes. Mirror of the server scanner's
# tolerant parser — the agent is what runs against REAL hardware on the
# user's LAN, so the leniency must live here too.
_CGMINER_EOL_TOKENS = (b"\x00", b"\x7e")

# ── HTTP helpers (stdlib urllib — the agent has ZERO dependencies so the
#    1-line installer works on any machine with python3, no pip install) ──


def _headers():
    return {"Authorization": f"Bearer {AGENT_TOKEN}", "Content-Type": "application/json"}


def _http_json(method, url, payload=None, headers=None, timeout=10.0,
               log_failures=True):
    """Minimal urllib JSON request. Returns (status_code, parsed_json_or_{}).
    `log_failures` is off for LAN probes (every dead host would spam the
    log on a /24 scan + re-scans) and on for cloud API calls."""
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method=method,
                                 headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode(errors="replace")
            status = getattr(resp, "status", 200)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        status = e.code
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        if log_failures:
            log.warning("[api] %s %s failed: %s", method, url, e)
        else:
            log.debug("[probe] %s %s failed: %s", method, url, e)
        return 0, {}
    try:
        parsed = json.loads(body) if body else {}
    except (json.JSONDecodeError, ValueError):
        parsed = {}
    return status, parsed


def _post(path, payload, timeout=10.0):
    return _http_json("POST", f"{SERVER_URL}{path}", payload=payload,
                      headers=_headers(), log_failures=True, timeout=timeout)

def _get_json(url, timeout=HTTP_TIMEOUT):
    """GET and parse JSON; returns parsed dict or None. Used for AxeOS :80.
    LAN probe — failures are expected (dead hosts), logged at debug only."""
    try:
        status, parsed = _http_json("GET", url, headers={}, timeout=timeout,
                                    log_failures=False)
        return parsed if status == 200 and parsed else None
    except Exception:
        return None


# ── Local discovery (mirrors axe_fleet/scanner.py, standalone) ────────────


def _local_ipv4_addresses():
    out = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        out.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in out:
                out.append(ip)
    except OSError:
        pass
    return out


def _default_subnets():
    subnets = []
    for ip in _local_ipv4_addresses():
        parts = ip.split(".")
        if len(parts) == 4 and all(p.isdigit() for p in parts) and parts[0] not in ("127", "169", "0", "255"):
            cidr = f"{'.'.join(parts[:3])}.0/24"
            if cidr not in subnets:
                subnets.append(cidr)
    return subnets


def _expand_cidr(cidr):
    import ipaddress
    try:
        if "/" in cidr:
            return [str(h) for h in ipaddress.ip_network(cidr, strict=False).hosts()][:MAX_HOSTS]
        if "-" in cidr:
            base, _, last = cidr.rpartition("-")
            head = ".".join(base.split(".")[:3])
            first = int(base.split(".")[3])
            return [f"{head}.{i}" for i in range(first, int(last) + 1)][:MAX_HOSTS]
        return [cidr]
    except Exception:
        return []


def _extract_json_lenient(raw):
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


def _probe_axeos(ip):
    """AxeOS/ESP-Miner HTTP :80 — returns info dict or None."""
    return _get_json(f"http://{ip}:{AXEOS_PORT}/api/system/info")


def _cgminer_cmd(ip, command):
    """Send one cgminer-family JSON command over TCP (:4028) and return the
    parsed response dict (or None). Lenient framing: accepts \x00 (most
    firmwares) and ~ (Avalon) terminators, banner prefixes and pretty-printed
    JSON. Shared by discovery (version) and telemetry (summary/stats/pools)."""
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TCP_TIMEOUT)
        sock.connect((ip, CGMINER_PORT))
        sock.sendall((json.dumps({"command": command}) + "\n").encode())
        data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
            if any(tok in chunk for tok in _CGMINER_EOL_TOKENS) or len(data) > 65536:
                break
        return _extract_json_lenient(data)
    except (socket.timeout, OSError):
        return None
    finally:
        if sock:
            try:
                sock.close()
            except OSError:
                pass


def _probe_cgminer(ip):
    """cgminer JSON-over-TCP :4028 — returns parsed version dict or None."""
    parsed = _cgminer_cmd(ip, "version")
    return parsed if parsed and parsed.get("STATUS") else None


def _probe_host(ip):
    """Full discovery probe for one host. Returns discovery dict or None."""
    info = _probe_axeos(ip)
    if isinstance(info, dict):
        try:
            hr = int(info.get("hashrate") or 0)
        except (TypeError, ValueError):
            hr = 0
        return {
            "ip": ip, "type": "bitaxe",
            "model": str(info.get("model") or info.get("board") or "Bitaxe"),
            "firmware": str(info.get("firmware", "")),
            "version": str(info.get("version", "")),
            "hostname": str(info.get("hostname", "")),
            "mac": str(info.get("mac", "")),
            "hashrate_hs": hr,
        }
    ver = _probe_cgminer(ip)
    if ver and ver.get("STATUS"):
        model = ""
        firmware = ""
        version = ""
        for e in (ver.get("VERSION") or []):
            if isinstance(e, dict):
                model = str(e.get("Description") or e.get("Type") or "")
                # VERSION also carries the cgminer/firmware build + API level
                # (e.g. CGMiner "4.11.1", API "3.1") — surface both so the
                # dashboard shows firmware for cgminer ASICs, not "".
                firmware = str(e.get("CGMiner") or "")
                version = str(e.get("API") or "")
                break
        return {
            "ip": ip, "type": "cgminer", "model": model or "cgminer",
            "firmware": firmware, "version": version, "hostname": "", "mac": "",
            "hashrate_hs": 0,
        }
    return None


def scan_lan():
    """Scan the configured subnet(s) and return discovered devices."""
    hosts = []
    if EXPLICIT_DEVICES:
        hosts = list(EXPLICIT_DEVICES)
    else:
        for cidr in ([SCAN_CIDR] if SCAN_CIDR else _default_subnets()):
            hosts += _expand_cidr(cidr)
    found = []
    if not hosts:
        return found
    with ThreadPoolExecutor(max_workers=min(SCAN_WORKERS, len(hosts))) as ex:
        futs = {ex.submit(_probe_host, ip): ip for ip in hosts}
        for fut in as_completed(futs):
            try:
                r = fut.result()
            except Exception:
                r = None
            if r:
                found.append(r)
    return found


# ── Telemetry polling (normalized shape, mirrors registry extract_telemetry) ─


def _poll_telemetry(dev):
    """Fetch one device's telemetry. Returns normalized dict (hashrate_hs,
    temperature, fan_rpm, power_watts, best_diff, shares_*, ...) or {}."""
    ip = dev["ip"]
    if dev.get("type") == "bitaxe":
        info = _probe_axeos(ip)
        if not isinstance(info, dict):
            return {}
        def _num(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        hr = _num(info.get("hashrate"))
        power = _num(info.get("power"))
        tel = {
            "hashrate_hs": int(hr or 0),
            "temperature": _num(info.get("temp")) or _num(info.get("temperature")),
            "fan_rpm": _num(info.get("fanRPM")) or _num(info.get("fanrpm")),
            "fan_speed": _num(info.get("fanSpeed")),
            "power_watts": power,
            "voltage_mv": _num(info.get("coreVoltage")),
            "frequency_mhz": _num(info.get("frequency")),
            "best_diff": str(info.get("bestDiff") or ""),
            "shares_accepted": int(info.get("sharesAccepted") or 0),
            "shares_rejected": int(info.get("sharesRejected") or 0),
            "uptime_seconds": int(info.get("uptime") or 0),
            "pool_url": str(info.get("pool") or info.get("stratumURL") or ""),
            "pool_user": str(info.get("poolUser") or ""),
            "wifi_rssi": _num(info.get("wifiRSSI")),
            "model": str(info.get("model") or "Bitaxe"),
        }
        if hr and power and power > 0:
            tel["efficiency_jth"] = round(power / (hr / 1e12), 2)
        return tel
    # cgminer: summary → hashrate/shares; stats → per-chain temps + fans
    # (Antminer/Braiins/LuxOS report temp2_0/temp3_0 and fan1/fan2 under the
    # second STATS entry); pools → pool URL/worker for the dashboard.
    summary = _cgminer_cmd(ip, "summary")
    if not summary or not summary.get("SUMMARY"):
        # Device unreachable — return {} (the agent pushes it as a heartbeat
        # so the server still refreshes last_seen). Never invent a 0-H/s
        # reading for a device we could not talk to.
        return {}
    # Parse defensively: real firmwares occasionally return non-numeric
    # strings ("N/A") or non-dict entries — a crash here would kill the
    # whole agent loop, so malformed data degrades to {} instead.
    try:
        s = summary["SUMMARY"][0] if isinstance(summary["SUMMARY"], list) and summary["SUMMARY"] else {}
        if not isinstance(s, dict):
            s = {}
        ghs = float(s.get("GHS 5s", s.get("GHS av", 0)) or 0)

        temperature = None
        fan_rpm = None
        stats = _cgminer_cmd(ip, "stats")
        _st = (stats or {}).get("STATS") or []
        if len(_st) > 1 and isinstance(_st[1], dict):
            temperature = _st[1].get("temp2_0") or _st[1].get("temp")
            fan_rpm = _st[1].get("fan1") or _st[1].get("fan2")

        pool_url = ""
        pool_user = ""
        pools = _cgminer_cmd(ip, "pools")
        if pools and isinstance(pools.get("POOLS"), list) and pools["POOLS"]:
            _p = pools["POOLS"][0]
            if isinstance(_p, dict):
                pool_url = str(_p.get("URL") or "")
                pool_user = str(_p.get("User") or "")

        return {
            "hashrate_hs": int(ghs * 1e9),
            "temperature": temperature,
            "fan_rpm": fan_rpm,
            "power_watts": None,
            "best_diff": str(s.get("Best Share", "")),
            "shares_accepted": int(s.get("Accepted", 0)),
            "shares_rejected": int(s.get("Rejected", 0)),
            "uptime_seconds": int(s.get("Elapsed", 0)),
            "pool_url": pool_url,
            "pool_user": pool_user,
            "model": dev.get("model") or "cgminer",
        }
    except (ValueError, TypeError, AttributeError, IndexError):
        return {}


# ── Command execution ────────────────────────────────────────────────────


def _exec_command(cmd, known=None):
    """Execute a queued command on the local device. Returns (success, result).

    The server now sends the device's LAN ip_address in the payload (the
    registry UUID is useless for opening a socket). Protocol by type:
      - bitaxe/AxeOS: HTTP POST /api/system/{restart|identify} on :80
      - cgminer-family: JSON-over-TCP restart command on :4028 (cgminer has
        NO identify command — the server no longer advertises it).
    """
    dev_ip = cmd.get("ip_address") or cmd.get("device_ip") or cmd.get("device_id")
    name = cmd.get("command")
    if name in ("restart", "identify", "pause", "resume"):
        # Resolve device type from the agent's own discovery map when known
        # (the server does not persist type; the agent probed it directly).
        dev = (known or {}).get(dev_ip, {})
        dev_type = str(dev.get("type") or "").lower()
        if dev_type == "cgminer":
            if name != "restart":
                return False, f"{name} not supported via cgminer API"
            parsed = _cgminer_cmd(dev_ip, "restart")
            if parsed and parsed.get("STATUS"):
                return True, "cgminer restart accepted"
            return False, "cgminer restart failed/unreachable"
        # bitaxe/AxeOS: the ESP-Miner API exposes pause/resume as
        # /api/system/miningPause + /api/system/miningResume (empty body),
        # restart/identify as /api/system/{restart|identify}.
        endpoint = {
            "restart": "restart",
            "identify": "identify",
            "pause": "miningPause",
            "resume": "miningResume",
        }[name]
        status, _ = _http_json("POST", f"http://{dev_ip}:{AXEOS_PORT}/api/system/{endpoint}",
                               payload=None, headers={}, timeout=5)
        return status == 200, f"HTTP {status}"
    return False, f"unknown command: {name}"


# ── Main loop ────────────────────────────────────────────────────────────


def main():
    if not AGENT_TOKEN:
        log.error("CYPHER65_AGENT_TOKEN não definido — gere em Painel → Fleet → Connect Agent")
        raise SystemExit(2)
    log.info("CYPHER65 agent — server=%s poll=%ds", SERVER_URL, POLL_INTERVAL)

    # 1 · Register discovered devices with the cloud dashboard.
    log.info("scanning LAN…")
    discovered = scan_lan()
    log.info("discovered %d device(s)", len(discovered))
    blocked_ips = set()
    if discovered:
        code, resp = _post("/api/agent/register", {"devices": discovered})
        if code in (200, 201):
            log.info("registered %s", resp.get("count"))
            blocked = resp.get("blocked") or []
            if blocked:
                # Plan worker cap hit: the server refused NEW devices. The
                # operator must free a slot or upgrade — surface it once so
                # the agent log explains why some miners never appear, and
                # drop them from the poll set so we don't 403-spam the server
                # with telemetry pushes for devices that were never admitted.
                blocked_ips = {b.get("ip") for b in blocked if b.get("ip")}
                log.warning("plan worker limit: %d device(s) blocked — %s",
                            len(blocked_ips),
                            resp.get("message") or "remova devices ou aumente o limite do plano")
        else:
            log.warning("register failed (HTTP %s): %s", code, resp.get("error"))

    known = {d["ip"]: d for d in discovered}
    # Even if the scan found nothing, allow explicit IPs via CYPHER65_DEVICES.
    # Run the FULL discovery probe (AxeOS :80 THEN cgminer :4028) so an
    # explicit cgminer IP is detected as such — hardcoding type=bitaxe would
    # only ever try :80 and miss every cgminer/ASIC miner.
    for ip in EXPLICIT_DEVICES:
        if ip in known:
            continue
        probed = _probe_host(ip)
        if probed:
            known[ip] = probed
        else:
            known[ip] = {"ip": ip, "type": "bitaxe", "model": "Bitaxe",
                         "firmware": "", "version": "", "hostname": "", "mac": "",
                         "hashrate_hs": 0}
    # Never poll/push devices the server refused (plan cap) — each push would
    # 403 forever and the dashboard would never show them anyway.
    for ip in blocked_ips:
        known.pop(ip, None)

    cycle = 0
    while True:
        t0 = time.time()
        # 2 · Poll each known device + push telemetry.
        for ip, dev in known.items():
            tel = _poll_telemetry(dev)
            # Push UNCONDITIONALLY: `telemetry: {}` is legal and keeps the
            # server's last_seen/status fresh, so a device that answered
            # nothing (firewall, reboot, poll failure) still shows as
            # present+IDLE instead of looking dead forever. Empty heartbeats
            # use a shorter timeout so unreachable devices can't stall the
            # poll loop on a cloud hiccup.
            code, resp = _post("/api/agent/telemetry", {"ip": ip, "telemetry": tel},
                               timeout=3.0 if not tel else 10.0)
            if code == 410 and resp.get("removed"):
                # Operator removed this device on the dashboard — drop it from
                # the poll set so we stop pushing a device that can never come
                # back through the agent path.
                log.warning("device %s removed by operator on dashboard — dropping", ip)
                known.pop(ip, None)
        # 3 · Pull queued commands and execute them locally.
        code, resp = _post("/api/agent/commands/pull", {})
        if code == 200:
            for cmd in resp.get("commands") or []:
                log.info("executing %s → %s (%s)", cmd.get("command"),
                         cmd.get("device_id"), cmd.get("ip_address") or "no-ip")
                ok, result = _exec_command(cmd, known)
                _post(f"/api/agent/commands/{cmd['id']}/ack",
                      {"success": ok, "result": result})
        # 4 · Re-scan periodically so newly added miners appear (a miner that
        # was powered off during boot, or added later, would otherwise never
        # be picked up — scan once at startup is not enough).
        cycle += 1
        if cycle % RESCAN_EVERY == 0:
            log.info("re-scanning LAN for new miners…")
            fresh = scan_lan()
            new = [d for d in fresh if d["ip"] not in known]
            if new:
                code, resp = _post("/api/agent/register", {"devices": new})
                log.info("registered %d new device(s)", code in (200, 201) and resp.get("count") or 0)
                if code in (200, 201):
                    # Only trust the register response: devices the server
                    # admitted go into the poll set; devices it refused (plan
                    # cap OR tombstoned/removed) must NOT be polled/pushed —
                    # otherwise telemetry 403-spams forever for refused ones.
                    admitted = {b.get("ip") for b in (resp.get("blocked") or []) if b.get("ip")}
                    for d in new:
                        if d["ip"] not in admitted:
                            known[d["ip"]] = d
                        else:
                            log.warning("device %s refused by server (plan cap / removed) — skipping", d["ip"])
                else:
                    log.warning("re-register failed (HTTP %s): %s", code, resp.get("error"))
        elapsed = time.time() - t0
        sleep = max(1, POLL_INTERVAL - elapsed)
        time.sleep(sleep)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("agent stopped")
