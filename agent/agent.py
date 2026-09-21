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
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
)

SERVER_URL = (os.environ.get("CYPHER65_SERVER_URL") or "http://localhost:8765").rstrip(
    "/"
)
AGENT_TOKEN = os.environ.get("CYPHER65_AGENT_TOKEN") or ""
POLL_INTERVAL = int(os.environ.get("CYPHER65_POLL_INTERVAL") or 30)
SCAN_CIDR = os.environ.get("CYPHER65_SCAN_CIDR") or ""
EXPLICIT_DEVICES = [
    ip.strip()
    for ip in (os.environ.get("CYPHER65_DEVICES") or "").split(",")
    if ip.strip()
]

HTTP_TIMEOUT = 2.0  # per AxeOS HTTP probe
TCP_TIMEOUT = 1.0  # per cgminer TCP probe
SCAN_WORKERS = 64
MAX_HOSTS = 1024
RESCAN_EVERY = 10  # full LAN re-scan every N poll cycles (new miners)

# Protocol ports. Defaults match real hardware (AxeOS HTTP :80, cgminer
# JSON-over-TCP :4028, Braiins OS+ REST alt :50051); overridable via env for
# test rigs/mock miners.
AXEOS_PORT = int(os.environ.get("CYPHER65_AXEOS_PORT") or 80)
CGMINER_PORT = int(os.environ.get("CYPHER65_CGMINER_PORT") or 4028)
BRAIINS_REST_PORT = int(os.environ.get("CYPHER65_BRAIINS_REST_PORT") or 50051)

# ESP-Miner identity: strong markers only. ``frequency`` alone is a Wi-Fi
# field on routers/HA/cameras and must NEVER classify a host as a miner.
# Mirror of axe_fleet.axeos_contract.AXEOS_STRONG_MARKERS (stdlib-only agent).
_AXEOS_MARKERS = (
    "ASICModel",
    "boardVersion",
    "hashRate",
    "hashrate",
    "expectedHashrate",
    "bestDiff",
    "sharesAccepted",
)

try:
    from axe_fleet.axeos_contract import (  # type: ignore
        extract_axeos_telemetry as _extract_axeos_telemetry,
        looks_like_axeos as _looks_like_axeos_payload,
    )
except ImportError:  # standalone installer: agent.py only
    _extract_axeos_telemetry = None
    _looks_like_axeos_payload = None

# cgminer-family framing: most firmwares terminate JSON with \x00, some
# (Avalon) wrap frames in ~ (\x7e) tildes. Mirror of the server scanner's
# tolerant parser — the agent is what runs against REAL hardware on the
# user's LAN, so the leniency must live here too.
_CGMINER_EOL_TOKENS = (b"\x00", b"\x7e")

# ── HTTP helpers (stdlib urllib — the agent has ZERO dependencies so the
#    1-line installer works on any machine with python3, no pip install) ──


def _headers():
    return {
        "Authorization": f"Bearer {AGENT_TOKEN}",
        "Content-Type": "application/json",
    }


def _http_json(
    method, url, payload=None, headers=None, timeout=10.0, log_failures=True
):
    """Minimal urllib JSON request. Returns (status_code, parsed_json_or_{}).
    `log_failures` is off for LAN probes (every dead host would spam the
    log on a /24 scan + re-scans) and on for cloud API calls."""
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
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
    return _http_json(
        "POST",
        f"{SERVER_URL}{path}",
        payload=payload,
        headers=_headers(),
        log_failures=True,
        timeout=timeout,
    )


def _post_retry(path, payload, timeout=10.0, attempts=4):
    """Retry transient cloud failures. Never retry 401 (bad token) or
    403/410 (plan cap / tombstone) — those need operator action."""
    delay = 1.0
    last = (0, {})
    for attempt in range(attempts):
        code, resp = _post(path, payload, timeout=timeout)
        if code in (200, 201):
            return code, resp
        if code in (401, 403, 410):
            if code == 401:
                log.error(
                    "[FLEET_AUTH] HTTP 401 — token rejected; generate a new "
                    "token in Fleet → CONNECT AGENT"
                )
            return code, resp
        last = (code, resp)
        if attempt < attempts - 1:
            log.warning("[FLEET_RETRY] %s HTTP %s — retry in %.0fs", path, code, delay)
            time.sleep(delay)
            delay = min(delay * 2, 30)
    return last


def _get_json(url, timeout=HTTP_TIMEOUT):
    """GET and parse JSON; returns parsed dict or None. Used for AxeOS :80.
    LAN probe — failures are expected (dead hosts), logged at debug only."""
    try:
        status, parsed = _http_json(
            "GET", url, headers={}, timeout=timeout, log_failures=False
        )
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
        if (
            len(parts) == 4
            and all(p.isdigit() for p in parts)
            and parts[0] not in ("127", "169", "0", "255")
        ):
            cidr = f"{'.'.join(parts[:3])}.0/24"
            if cidr not in subnets:
                subnets.append(cidr)
    return subnets


def _expand_cidr(cidr):
    import ipaddress

    try:
        if "/" in cidr:
            return [str(h) for h in ipaddress.ip_network(cidr, strict=False).hosts()][
                :MAX_HOSTS
            ]
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


def _probe_axeos_payload(info):
    """True when a parsed /api/system/info body is ESP-Miner evidence."""
    if _looks_like_axeos_payload is not None:
        return bool(_looks_like_axeos_payload(info))
    if not isinstance(info, dict) or not info:
        return False
    return any(key in info for key in _AXEOS_MARKERS)


def _identity_from_axeos(ip, info):
    """Discovery dict from a validated ESP-Miner info payload."""
    tel = {}
    if _extract_axeos_telemetry is not None:
        try:
            tel = _extract_axeos_telemetry(info) or {}
        except Exception:
            tel = {}
    hr = tel.get("hashrate_hs")
    if hr is None:
        raw = info.get("hashRate")
        camel = raw is not None
        if raw is None:
            raw = info.get("hashrate")
        try:
            n = float(raw)
        except (TypeError, ValueError):
            n = None
        if n is None:
            hr = 0
        elif camel and 0 < abs(n) < 1e6:
            hr = int(n * 1e9)
        else:
            hr = int(n or 0)
    return {
        "ip": ip,
        "type": "bitaxe",
        "model": str(
            tel.get("model")
            or info.get("model")
            or info.get("board")
            or info.get("ASICModel")
            or "Bitaxe"
        ),
        "firmware": str(tel.get("firmware") or info.get("firmware") or ""),
        "version": str(tel.get("version") or info.get("version") or ""),
        "hostname": str(tel.get("hostname") or info.get("hostname") or ""),
        "mac": str(tel.get("mac") or info.get("macAddr") or info.get("mac") or ""),
        "hashrate_hs": int(hr or 0),
    }


def _probe_axeos(ip):
    """AxeOS/ESP-Miner HTTP :80 — returns info dict or None.

    Requires ESP-Miner identity keys. Accepting any JSON 200 here is how a
    router's JSON catch-all gets registered as a Bitaxe and then pushes empty
    telemetry forever, so an unrecognized payload is rejected outright.
    """
    info = _get_json(f"http://{ip}:{AXEOS_PORT}/api/system/info")
    if not _probe_axeos_payload(info):
        return None
    return info


def _probe_braiins_rest(ip):
    """Braiins OS+ REST (``GET /api/v1/miner/stats``) on :80 then :50051.

    Returns the parsed payload, or None. ``miner_stats`` is the Braiins OS+
    identity block — the whole telemetry lives under it — so a 200 without it
    is not a Braiins miner we could read, and must not be reported as one.
    """
    for port in (AXEOS_PORT, BRAIINS_REST_PORT):
        data = _get_json(f"http://{ip}:{port}/api/v1/miner/stats")
        if (
            isinstance(data, dict)
            and isinstance(data.get("miner_stats"), dict)
            and data["miner_stats"]
        ):
            return data
    return None


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
    """Full discovery probe for one host. Returns discovery dict or None.

    Every branch is gated on a validated minimer protocol (AxeOS REST →
    Braiins OS+ REST → cgminer socket) — never on a mere open port, so a
    neighbour on the LAN cannot be announced as a miner.
    """
    info = _probe_axeos(ip)
    if isinstance(info, dict):
        return _identity_from_axeos(ip, info)
    rest = _probe_braiins_rest(ip)
    if isinstance(rest, dict):
        miner = rest.get("miner_stats") or {}
        pool = rest.get("pool_stats") or {}
        try:
            ghps = float(miner.get("hashrate_avg") or miner.get("hashrate_ghps") or 0)
        except (TypeError, ValueError):
            ghps = 0.0
        return {
            "ip": ip,
            "type": "braiins",
            "model": str(
                miner.get("model") or miner.get("miner_type") or "Braiins OS+"
            ),
            "firmware": "Braiins OS+",
            "version": str(miner.get("version") or miner.get("firmware_version") or ""),
            "hostname": "",
            "mac": "",
            "hashrate_hs": int(ghps * 1e9),
            "pool_url": str(pool.get("url") or ""),
            "pool_user": str(pool.get("user") or ""),
        }
    ver = _probe_cgminer(ip)
    if ver and ver.get("STATUS"):
        model = ""
        firmware = ""
        version = ""
        for e in ver.get("VERSION") or []:
            if isinstance(e, dict):
                model = str(e.get("Description") or e.get("Type") or "")
                # VERSION also carries the cgminer/firmware build + API level
                # (e.g. CGMiner "4.11.1", API "3.1") — surface both so the
                # dashboard shows firmware for cgminer ASICs, not "".
                firmware = str(e.get("CGMiner") or "")
                version = str(e.get("API") or "")
                break
        return {
            "ip": ip,
            "type": "cgminer",
            "model": model or "cgminer",
            "firmware": firmware,
            "version": version,
            "hostname": "",
            "mac": "",
            "hashrate_hs": 0,
        }
    return None


def scan_lan():
    """Scan the configured subnet(s) and return discovered devices."""
    hosts = []
    subnets = [SCAN_CIDR] if SCAN_CIDR else _default_subnets()
    scan_id = f"{int(time.time())}-{os.getpid()}"
    if EXPLICIT_DEVICES:
        hosts = list(EXPLICIT_DEVICES)
        subnets = ["explicit"]
    else:
        for cidr in subnets:
            hosts += _expand_cidr(cidr)
    found = []
    log.info(
        "[FLEET_SCAN] scan_id=%s subnet=%s hosts=%s",
        scan_id,
        ",".join(subnets) or "none",
        len(hosts),
    )
    if not hosts:
        log.warning("[FLEET_SCAN] scan_id=%s result=NO_LAN_INTERFACE", scan_id)
        return found
    with ThreadPoolExecutor(max_workers=min(SCAN_WORKERS, len(hosts))) as ex:
        futs = {ex.submit(_probe_host, ip): ip for ip in hosts}
        for fut in as_completed(futs):
            ip = futs[fut]
            try:
                r = fut.result()
            except Exception:
                r = None
            if r:
                found.append(r)
                log.info(
                    "[FLEET_DISCOVERY] scan_id=%s ip=%s protocol=%s model=%s result=FOUND",
                    scan_id,
                    r.get("ip") or ip,
                    r.get("type"),
                    r.get("model"),
                )
    log.info(
        "[FLEET_SCAN] scan_id=%s hosts=%s miners=%s",
        scan_id,
        len(hosts),
        len(found),
    )
    return found


# ── Telemetry polling (normalized shape, mirrors registry extract_telemetry) ─


# ── Normalizers (mirror axe_fleet/models.best_diff_from_value — the agent
#    is stdlib-only, so the shared helper lives on the server; this mirror
#    must stay in sync, guarded by tests/test_fleet_audit_regressions.py) ──
def _best_diff(value):
    """Best Share ("P Share") normalization: None → "", 0 → "0" (a verified
    zero is a number, not "unsupported"), anything else → its string.
    The legacy `str(x or "")` collapsed legitimate zeros into ""."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return ""
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return str(value).strip()
    if as_float == 0.0:
        return "0"
    return str(value).strip()


def _braiins_rest_telemetry(ip):
    """Normalized telemetry from the Braiins OS+ REST API, or {}.

    Field names mirror core/adapters/braiins_adapter._parse_rest_telemetry so
    the agent and the server-side adapter report the same columns. An empty
    dict means "REST not answering" (the caller then tries cgminer) — never
    "device is dead".
    """
    data = _probe_braiins_rest(ip)
    if not isinstance(data, dict):
        return {}
    miner = data.get("miner_stats") or {}
    pool = data.get("pool_stats") or {}
    power = data.get("power_stats") or {}

    def _num(value, cast=float):
        try:
            return cast(value)
        except (TypeError, ValueError):
            return None

    ghps = _num(miner.get("hashrate_avg") or miner.get("hashrate_ghps"))
    hr = int((ghps or 0.0) * 1e9)
    power_w = _num(power.get("power_avg") or power.get("power_w"))
    tel = {
        "hashrate_hs": hr,
        "temperature": _num(miner.get("board_temp_avg")),
        "temp_asic": _num(miner.get("chip_temp_avg")),
        "fan_rpm": None,  # REST exposes fans under /api/v1/cooling/state
        "power_watts": power_w,
        "best_diff": _best_diff(miner.get("best_share")),
        "shares_accepted": _num(
            miner.get("accepted_shares") or pool.get("accepted"), int
        )
        or 0,
        "shares_rejected": _num(
            miner.get("rejected_shares") or pool.get("rejected"), int
        )
        or 0,
        "shares_stale": _num(miner.get("stale_shares") or pool.get("stale"), int) or 0,
        "uptime_seconds": _num(miner.get("uptime_s") or miner.get("uptime"), int) or 0,
        "pool_url": str(pool.get("url") or ""),
        "pool_user": str(pool.get("user") or ""),
        "model": str(miner.get("model") or miner.get("miner_type") or "Braiins OS+"),
    }
    if hr and power_w:
        tel["efficiency_jth"] = round(power_w / (hr / 1e12), 2)
    return tel


def _poll_telemetry(dev):
    """Fetch one device's telemetry. Returns normalized dict (hashrate_hs,
    temperature, fan_rpm, power_watts, best_diff, shares_*, ...) or {}."""
    ip = dev["ip"]
    if dev.get("type") == "bitaxe":
        info = _probe_axeos(ip)
        if not isinstance(info, dict):
            return {}
        if _extract_axeos_telemetry is not None:
            try:
                tel = _extract_axeos_telemetry(info)
            except Exception:
                tel = {}
            if tel:
                log.info(
                    "[FLEET_TELEMETRY] ip=%s hashrate=%s temp=%s accepted=%s "
                    "rejected=%s best_diff=%s",
                    ip,
                    tel.get("hashrate_hs"),
                    tel.get("temperature"),
                    tel.get("shares_accepted"),
                    tel.get("shares_rejected"),
                    tel.get("best_diff"),
                )
                return tel
        ident = _identity_from_axeos(ip, info)
        return {
            "hashrate_hs": ident.get("hashrate_hs"),
            "temperature": info.get("temp"),
            "best_diff": _best_diff(info.get("bestDiff")),
            "shares_accepted": info.get("sharesAccepted"),
            "shares_rejected": info.get("sharesRejected"),
            "uptime_seconds": info.get("uptimeSeconds") or info.get("uptime"),
            "pool_url": str(info.get("stratumURL") or info.get("pool") or ""),
            "pool_user": str(info.get("stratumUser") or info.get("poolUser") or ""),
            "model": ident.get("model") or "Bitaxe",
            "mining_paused": info.get("miningPaused") is True,
        }
    if dev.get("type") == "braiins":
        # Braiins OS+ REST carries the full telemetry. When the REST API does
        # not answer (older firmware, /api/v1 disabled) fall through to the
        # cgminer path below — Braiins OS+ serves that API too, so a
        # reachable miner is never reported as dead.
        rest_tel = _braiins_rest_telemetry(ip)
        if rest_tel:
            return rest_tel
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
        s = (
            summary["SUMMARY"][0]
            if isinstance(summary["SUMMARY"], list) and summary["SUMMARY"]
            else {}
        )
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
            "best_diff": _best_diff(s.get("Best Share")),
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
      - Braiins OS+: same cgminer API over :4028 for restart, plus `led` for
        identify; Braiins OS+ has no pause/resume (the registry does not
        advertise them for this type).
    """
    dev_ip = cmd.get("ip_address") or cmd.get("device_ip") or cmd.get("device_id")
    name = cmd.get("command")
    if name == "probe":
        target = (cmd.get("params") or {}).get("ip") or dev_ip
        if not target or target == "_probe":
            return False, "probe ip missing"
        probed = _probe_host(target)
        if not probed:
            return False, "not a miner"
        if known is not None:
            known[target] = probed
        code, resp = _post_retry("/api/agent/register", {"devices": [probed]})
        if code in (200, 201):
            log.info("[FLEET_REGISTER] ip=%s result=SUCCESS via probe", target)
            return True, f"registered {target}"
        return False, f"register HTTP {code}"
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
        if dev_type == "braiins":
            if name not in ("restart", "identify"):
                # Braiins OS+ has no pause/resume. Reject rather than fake a
                # success the miner never performed.
                return False, f"{name} not supported by Braiins OS+"
            # Braiins OS+ exposes the cgminer API: `restart` reboots the miner
            # and `led` blinks the identification LED.
            parsed = _cgminer_cmd(dev_ip, "restart" if name == "restart" else "led")
            if parsed and parsed.get("STATUS"):
                return True, f"braiins {name} accepted"
            return False, f"braiins {name} failed/unreachable"
        # bitaxe/AxeOS: the ESP-Miner API exposes pause/resume as
        # /api/system/miningPause + /api/system/miningResume (empty body),
        # restart/identify as /api/system/{restart|identify}.
        endpoint = {
            "restart": "restart",
            "identify": "identify",
            "pause": "miningPause",
            "resume": "miningResume",
        }[name]
        status, _ = _http_json(
            "POST",
            f"http://{dev_ip}:{AXEOS_PORT}/api/system/{endpoint}",
            payload=None,
            headers={},
            timeout=5,
        )
        return status == 200, f"HTTP {status}"
    return False, f"unknown command: {name}"


# ── Main loop ────────────────────────────────────────────────────────────


def main():
    if not AGENT_TOKEN:
        log.error(
            "CYPHER65_AGENT_TOKEN não definido — gere em Painel → Fleet → Connect Agent"
        )
        raise SystemExit(2)
    log.info("CYPHER65 agent — server=%s poll=%ds", SERVER_URL, POLL_INTERVAL)

    # 1 · Register discovered devices with the cloud dashboard.
    log.info("scanning LAN…")
    discovered = scan_lan()
    log.info("discovered %d device(s)", len(discovered))
    blocked_ips = set()
    if discovered:
        code, resp = _post_retry("/api/agent/register", {"devices": discovered})
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
                log.warning(
                    "plan worker limit: %d device(s) blocked — %s",
                    len(blocked_ips),
                    resp.get("message")
                    or "remova devices ou aumente o limite do plano",
                )
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
            known[ip] = {
                "ip": ip,
                "type": "bitaxe",
                "model": "Bitaxe",
                "firmware": "",
                "version": "",
                "hostname": "",
                "mac": "",
                "hashrate_hs": 0,
            }
    # Never poll/push devices the server refused (plan cap) — each push would
    # 403 forever and the dashboard would never show them anyway.
    for ip in blocked_ips:
        known.pop(ip, None)

    cycle = 0
    while True:
        t0 = time.time()
        # 2 · Poll each known device + push telemetry.
        drop = []
        for ip, dev in list(known.items()):
            tel = _poll_telemetry(dev)
            # Push UNCONDITIONALLY: `telemetry: {}` is legal and keeps the
            # server's last_seen/status fresh, so a device that answered
            # nothing (firewall, reboot, poll failure) still shows as
            # present instead of looking dead forever. Empty heartbeats
            # use a shorter timeout so unreachable devices can't stall the
            # poll loop on a cloud hiccup.
            code, resp = _post(
                "/api/agent/telemetry",
                {"ip": ip, "telemetry": tel},
                timeout=3.0 if not tel else 10.0,
            )
            if code in (0, 429, 500, 502, 503):
                code, resp = _post_retry(
                    "/api/agent/telemetry",
                    {"ip": ip, "telemetry": tel},
                    timeout=3.0 if not tel else 10.0,
                    attempts=3,
                )
            if code == 410 and resp.get("removed"):
                # Operator removed this device on the dashboard — drop it from
                # the poll set so we stop pushing a device that can never come
                # back through the agent path.
                log.warning("device %s removed by operator on dashboard — dropping", ip)
                drop.append(ip)
        for ip in drop:
            known.pop(ip, None)
        # 3 · Pull queued commands and execute them locally.
        code, resp = _post("/api/agent/commands/pull", {})
        if code == 200:
            for cmd in resp.get("commands") or []:
                log.info(
                    "executing %s → %s (%s)",
                    cmd.get("command"),
                    cmd.get("device_id"),
                    cmd.get("ip_address") or "no-ip",
                )
                ok, result = _exec_command(cmd, known)
                _post(
                    f"/api/agent/commands/{cmd['id']}/ack",
                    {"success": ok, "result": result},
                )
        # 4 · Re-scan periodically so newly added miners appear (a miner that
        # was powered off during boot, or added later, would otherwise never
        # be picked up — scan once at startup is not enough).
        cycle += 1
        if cycle % RESCAN_EVERY == 0:
            log.info("re-scanning LAN for new miners…")
            fresh = scan_lan()
            new = [d for d in fresh if d["ip"] not in known]
            if new:
                code, resp = _post_retry("/api/agent/register", {"devices": new})
                log.info(
                    "registered %d new device(s)",
                    code in (200, 201) and resp.get("count") or 0,
                )
                if code in (200, 201):
                    # Only trust the register response: devices the server
                    # admitted go into the poll set; devices it refused (plan
                    # cap OR tombstoned/removed) must NOT be polled/pushed —
                    # otherwise telemetry 403-spams forever for refused ones.
                    admitted = {
                        b.get("ip") for b in (resp.get("blocked") or []) if b.get("ip")
                    }
                    for d in new:
                        if d["ip"] not in admitted:
                            known[d["ip"]] = d
                        else:
                            log.warning(
                                "device %s refused by server (plan cap / removed) — skipping",
                                d["ip"],
                            )
                else:
                    log.warning(
                        "re-register failed (HTTP %s): %s", code, resp.get("error")
                    )
        elapsed = time.time() - t0
        sleep = max(1, POLL_INTERVAL - elapsed)
        time.sleep(sleep)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("agent stopped")
