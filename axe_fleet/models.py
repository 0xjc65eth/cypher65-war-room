"""
CYPHER65 // AXE FLEET — Data Models
====================================
Device, Capability, Telemetry, and related types for the AxeOS fleet manager.
All models use simple dicts for SQLite compatibility (no ORM).
"""

import math


_AGENT_TELEMETRY_NUMERIC_FIELDS = {
    "hashrate_hs": (0, 1e18, False),
    "expected_hashrate": (0, 1e18, False),
    "hashrate_1m": (0, 1e18, False),
    "hashrate_10m": (0, 1e18, False),
    "hashrate_1h": (0, 1e18, False),
    "temperature": (-40, 150, False),
    "temp_asic": (-40, 150, False),
    "temp_vreg": (-40, 150, False),
    "chip_temp": (-40, 150, False),
    "vr_temp": (-40, 150, False),
    "fan_speed": (0, 100, False),
    "fan_rpm": (0, 100_000, False),
    "power_watts": (0, None, False),
    "voltage_mv": (0, None, False),
    "voltage_actual_mv": (0, None, False),
    "frequency_mhz": (0, None, False),
    "current_ma": (0, None, False),
    "efficiency_jth": (0, None, False),
    "best_diff_raw": (0, None, False),
    "shares_accepted": (0, None, True),
    "shares_rejected": (0, None, True),
    "shares_stale": (0, None, True),
    "hw_errors": (0, None, True),
    "hw_error_pct": (0, 100, False),
    "uptime_seconds": (0, None, True),
    "free_heap": (0, None, True),
    "wifi_rssi": (-150, 0, False),
    "ts": (0, None, True),
}
_AGENT_TELEMETRY_STRING_FIELDS = {
    "best_diff",
    "best_session_diff",
    "pool_url",
    "pool_user",
    "stratum_status",
    "model",
    "mac",
    "hostname",
    "firmware",
    "version",
}
_AGENT_TELEMETRY_FLEXIBLE_FIELDS = {"pool_diff", "last_share_ts"}
_AGENT_TELEMETRY_OPTIONAL_NUMERIC_FIELDS = {
    "expected_hashrate",
    "hashrate_1m",
    "hashrate_10m",
    "hashrate_1h",
    "temperature",
    "temp_asic",
    "temp_vreg",
    "chip_temp",
    "vr_temp",
    "fan_speed",
    "fan_rpm",
    "power_watts",
    "voltage_mv",
    "voltage_actual_mv",
    "frequency_mhz",
    "current_ma",
    "efficiency_jth",
    "best_diff_raw",
    "shares_accepted",
    "shares_rejected",
    "shares_stale",
    "hw_errors",
    "hw_error_pct",
    "uptime_seconds",
    "free_heap",
    "wifi_rssi",
}
_AGENT_TELEMETRY_OPTIONAL_FLEXIBLE_FIELDS = {"pool_diff", "last_share_ts"}
_AGENT_TELEMETRY_BOOLEAN_FIELDS = {"mining_paused"}


def _is_finite_number(value):
    try:
        return math.isfinite(value)
    except (TypeError, OverflowError):
        return False


def _numeric_string(value):
    """Return a parsed float for numeric strings, otherwise None."""
    try:
        return float(value.strip())
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def _valid_field_name(field):
    """Keep untrusted JSON keys from injecting control characters into logs."""
    return "".join(
        char if char.isalnum() or char in "_.-[]" else "_" for char in str(field)
    )[:160]


def _safe_field_path(value, path=""):
    """Normalize an unknown nested path before returning it to logs/audit."""
    if isinstance(value, dict):
        return [
            field
            for key, nested in value.items()
            for field in _safe_field_path(
                nested,
                f"{path}.{_valid_field_name(key)}" if path else _valid_field_name(key),
            )
        ]
    if isinstance(value, list):
        return [
            field
            for index, nested in enumerate(value)
            for field in _safe_field_path(nested, f"{path}[{index}]")
        ]
    if isinstance(value, float) and not math.isfinite(value):
        return [path or "telemetry"]
    return []


def _non_finite_fields(value, path=""):
    """Compatibility alias for tests/callers of the former private helper."""
    return _safe_field_path(value, path)


def validate_agent_telemetry(payload: dict) -> list[dict]:
    """Return safe field/reason pairs for invalid agent telemetry.

    Empty objects are legal liveness heartbeats. A measured sample must carry
    ``hashrate_hs``; optional sensors may be omitted or ``None`` when firmware
    does not expose them. Hashrate fields are bounded at 1 EH/s per device: a
    deliberately generous ceiling that leaves room for future ASICs while
    rejecting values several orders beyond any single-device reading.
    """
    if not isinstance(payload, dict):
        return [{"field": "telemetry", "reason": "must_be_object"}]
    if not payload:
        return []

    errors = []
    if "hashrate_hs" not in payload or payload.get("hashrate_hs") is None:
        errors.append({"field": "hashrate_hs", "reason": "required_for_sample"})

    for field in _non_finite_fields(payload):
        errors.append({"field": field, "reason": "not_finite"})

    for field, (minimum, maximum, integral) in _AGENT_TELEMETRY_NUMERIC_FIELDS.items():
        if field not in payload:
            continue
        value = payload[field]
        if value is None:
            if (
                field != "hashrate_hs"
                and field not in _AGENT_TELEMETRY_OPTIONAL_NUMERIC_FIELDS
            ):
                errors.append({"field": field, "reason": "invalid_type"})
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append({"field": field, "reason": "invalid_type"})
            continue
        if not _is_finite_number(value):
            # Non-finite floats are already reported by the recursive pass.
            if not isinstance(value, float):
                errors.append({"field": field, "reason": "not_finite"})
            continue
        if integral and not isinstance(value, int) and not value.is_integer():
            errors.append({"field": field, "reason": "must_be_integer"})
            continue
        if value < minimum or (maximum is not None and value > maximum):
            errors.append({"field": field, "reason": "out_of_range"})

    for field in _AGENT_TELEMETRY_STRING_FIELDS:
        if field not in payload:
            continue
        value = payload[field]
        if value is None or not isinstance(value, str):
            errors.append({"field": field, "reason": "invalid_type"})
    for field in _AGENT_TELEMETRY_BOOLEAN_FIELDS:
        if field in payload and not isinstance(payload[field], bool):
            errors.append({"field": field, "reason": "invalid_type"})

    for field in _AGENT_TELEMETRY_FLEXIBLE_FIELDS:
        if field not in payload:
            continue
        value = payload[field]
        if value is None and field in _AGENT_TELEMETRY_OPTIONAL_FLEXIBLE_FIELDS:
            continue
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            errors.append({"field": field, "reason": "invalid_type"})
            continue
        if isinstance(value, (int, float)):
            number = value
        else:
            number = _numeric_string(value)
            # last_share_ts also accepts ISO-8601 strings; pool difficulty
            # strings may carry unit suffixes (for example "256M").
            if number is None:
                continue
        if not _is_finite_number(number):
            errors.append({"field": field, "reason": "not_finite"})
        elif number < 0:
            errors.append({"field": field, "reason": "out_of_range"})

    # Stable and unique diagnostics keep repeated malformed values from
    # producing duplicate audit fields/reasons.
    unique_errors = {(error["field"], error["reason"]) for error in errors}
    return [
        {"field": field, "reason": reason} for field, reason in sorted(unique_errors)
    ]


# ── Device capability flags ──────────────────────────────────────────────
# Inferred from AxeOS/ESP-Miner API responses at connection time.
# Never assume a capability exists — detect per-device.
DEFAULT_CAPABILITIES = {
    "telemetry": False,
    "statistics": False,
    "restart": False,
    "identify": False,
    "pause": False,
    "resume": False,
    "frequencyControl": False,
    "voltageControl": False,
    "powerControl": False,
    "otaFirmware": False,
    "otaWebUI": False,
    "websocket": False,
    "scoreboard": False,
    "configure": False,
}

# ── Device status constants ──────────────────────────────────────────────
# STALE (Fleet audit, Issue #627): telemetry exists but is OLD. A device can
# no longer sit at IDLE/ONLINE forever on a dead heartbeat — an empty agent
# heartbeat (device unreachable) refreshes last_seen but carries NO fresh
# measurement, so the honest status is STALE when the newest stored telemetry
# is older than the staleness horizon, OFFLINE when there is none.
STATUS_ONLINE = "ONLINE"
STATUS_OFFLINE = "OFFLINE"
STATUS_HASHING = "HASHING"
STATUS_PAUSED = "PAUSED"
STATUS_WARNING = "WARNING"
STATUS_ERROR = "ERROR"
STATUS_STALE = "STALE"
STATUS_IDLE = "IDLE"

# A telemetry reading older than this is STALE regardless of reachability
# signals (agent polls every 30s in production; 15 min covers ~30 lost
# cycles plus agent restarts without ever rendering week-old numbers as live).
TELEMETRY_STALENESS_S = 15 * 60
# Small producer clock skew is tolerated, but a far-future measurement cannot
# prove current health.
TELEMETRY_FUTURE_SKEW_S = 5 * 60

# ── Device schema keys ───────────────────────────────────────────────────
DEVICE_SCHEMA = {
    "id": "",  # unique id (uuid or hash)
    "name": "",  # user-assigned name (e.g. "Garage Bitaxe")
    "model": "",  # Bitaxe / NerdAxe / NerdQaxe / NerdQaxe++ / unknown
    "manufacturer": "",  # inferred from model / system info
    "firmware": "",  # e.g. "AxeOS"
    "firmware_version": "",  # e.g. "2.6.0"
    "api_version": "",  # e.g. "2.0.0"
    "ip_address": "",  # IPv4 string
    "hostname": "",  # device hostname
    "mac_address": "",  # MAC (if available)
    "last_seen": 0,  # unix ts
    "status": STATUS_OFFLINE,
    "group_id": "",  # optional group for fleet management
    "added_at": 0,  # unix ts
    "updated_at": 0,  # unix ts
}

# ── Telemetry schema keys ────────────────────────────────────────────────
TELEMETRY_SCHEMA = {
    "ts": 0,  # unix timestamp of measurement
    "device_id": "",  # refers to device.id
    "hashrate_hs": 0,  # H/s
    "hashrate_str": "",  # formatted (e.g. "1.21 TH/s")
    "expected_hashrate": 0,  # H/s (from ASIC config)
    # Fase 5: hashrate windows (H/s) — None/0 when firmware does not expose them
    "hashrate_1m": None,  # H/s 1-minute average
    "hashrate_10m": None,  # H/s 10-minute average
    "hashrate_1h": None,  # H/s 1-hour average
    "temperature": None,  # °C (board temp)
    "temp_asic": None,  # °C (ASIC junction temp, if available)
    "temp_vreg": None,  # °C (voltage regulator temp)
    "fan_speed": None,  # 0-100 percent
    "fan_rpm": None,
    "power_watts": None,  # watts
    "voltage_mv": None,  # core voltage in mV
    "voltage_actual_mv": None,  # actual measured voltage
    "frequency_mhz": None,  # ASIC frequency in MHz
    "current_ma": None,  # current in mA
    "efficiency_jth": None,  # J/TH
    "best_diff": "",  # best difficulty string
    "best_diff_raw": 0.0,
    "shares_accepted": 0,
    "shares_rejected": 0,
    "shares_stale": 0,
    "hw_errors": 0,
    "hw_error_pct": 0.0,  # HW error rate in %
    "uptime_seconds": 0,
    "free_heap": 0,
    "wifi_rssi": None,
    "pool_url": "",
    "pool_user": "",
    "stratum_status": "",
    "mining_paused": False,  # ESP-Miner miningPaused — explicit operator intent
}


def new_device(ip_address: str, name: str = "") -> dict:
    """Create a new device dict with default values."""
    import time

    d = dict(DEVICE_SCHEMA)
    d["ip_address"] = ip_address
    d["name"] = name or ip_address
    d["added_at"] = int(time.time())
    d["updated_at"] = int(time.time())
    d["capabilities"] = dict(DEFAULT_CAPABILITIES)
    return d


def new_telemetry(device_id: str) -> dict:
    """Create a new telemetry dict with default values."""
    t = dict(TELEMETRY_SCHEMA)
    t["device_id"] = device_id
    t["ts"] = 0
    return t


def best_diff_from_value(value) -> str:
    """Normalize a firmware/agent Best Share ("P Share") into the payload
    string — the ONE conversion every producer must use.

    Contract (Fleet audit, Issue #627):
      - None / missing            → ""   ("—" in the UI: never invent a 0)
      - 0 / "0" / "0.0" / 0.0    → "0"  (a VERIFIED zero stays zero)
      - 1234 / "1.23M" / 5e8      → str(value).strip() (formatting is the
        frontend's job via fmt.diff; K/M/G/T/P/E handled there)

    The legacy idiom `str(value or "")` collapsed a legitimate 0 into "",
    hiding a real "no share yet" state behind a false "unsupported" one —
    and the three producers (connector, agent, adapters) disagreed with each
    other. cgminer already preserved "0"; this makes every path agree.
    """
    if value is None:
        return ""
    if isinstance(value, bool):  # bool is int; a True/False here is garbage
        return ""
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return str(value).strip()
    if as_float == 0.0:
        return "0"
    return str(value).strip()


def is_telemetry_stale(last_ts, now=None, horizon: int = TELEMETRY_STALENESS_S) -> bool:
    """True when the newest stored telemetry for a device is older than the
    staleness horizon (or absent). Pure — mirrored in the fleet audit tests.
    """
    if now is None:
        import time

        now = int(time.time())
    try:
        ts = int(last_ts or 0)
    except (TypeError, ValueError):
        return True
    if ts <= 0:
        return True
    age = int(now) - ts
    if age < -TELEMETRY_FUTURE_SKEW_S:
        return True
    return age > horizon


def derive_device_status(telemetry: dict = None, hashrate: int = None) -> str:
    """Derive a device status from telemetry.

    PAUSED wins over hashrate (Issue #13): miningPaused is explicit operator
    intent — a paused device must render PAUSED, never IDLE/ONLINE, even if
    the firmware still reports a stale hashrate. Otherwise ONLINE when hashing
    (>0 H/s), IDLE when reachable but idle.
    """
    t = telemetry or {}
    # Strict `is True`: a stringy "false" from a quirky agent/firmware must
    # never pause a device (`bool("false")` is True in Python).
    if t.get("mining_paused") is True:
        return STATUS_PAUSED
    hr = hashrate if hashrate is not None else int(t.get("hashrate_hs") or 0)
    return STATUS_ONLINE if hr > 0 else "IDLE"


def infer_capabilities(system_info: dict) -> dict:
    """Detect device capabilities from /api/system/info response.
    Returns a capabilities dict with detected flags set to True."""
    caps = dict(DEFAULT_CAPABILITIES)

    if not system_info:
        return caps

    # Basic telemetry is always available if we got a response
    caps["telemetry"] = True
    caps["statistics"] = True
    caps["restart"] = True  # POST /api/system/restart is standard
    caps["identify"] = True  # POST /api/system/identify is standard

    # Frequency/voltage control: check if ASIC exposes frequency
    asic_count = system_info.get("asicCount", 0)
    if asic_count and int(asic_count) > 0:
        caps["frequencyControl"] = True
        caps["voltageControl"] = True
        caps["configure"] = True

    # Pause/resume: not universally supported; check firmware version
    fw = str(system_info.get("firmware", "")).lower()
    ver = str(system_info.get("version", ""))
    if "axeos" in fw and ver:
        # AxeOS 2.4+ supports pause via PATCH /api/system with {"power": 0}
        try:
            parts = ver.split(".")
            major = int(parts[0]) if len(parts) > 0 else 0
            minor = int(parts[1]) if len(parts) > 1 else 0
            if major > 2 or (major == 2 and minor >= 4):
                caps["pause"] = True
                caps["resume"] = True
        except (ValueError, IndexError):
            pass

    return caps


def infer_health_score(telemetry: dict) -> int:
    """Calculate health score 0-100 for a device based on telemetry.
    Components: hashrate ratio, temperature, HW errors, uptime."""
    score = 100
    if not telemetry:
        return 0

    # Hashrate ratio (expected vs actual): 0-40 points
    expected = telemetry.get("expected_hashrate") or 0
    actual = telemetry.get("hashrate_hs") or 0
    if expected > 0 and actual > 0:
        ratio = actual / expected
        if ratio >= 0.95:
            hr_score = 40
        elif ratio >= 0.85:
            hr_score = 30
        elif ratio >= 0.70:
            hr_score = 20
        elif ratio >= 0.50:
            hr_score = 10
        else:
            hr_score = 0
    elif actual > 0:
        hr_score = 20  # hashing but no baseline
    else:
        hr_score = 0
    score -= 40 - hr_score

    # Temperature: 0-25 points
    temp = telemetry.get("temperature")
    if temp is not None:
        if temp < 55:
            temp_score = 25
        elif temp < 65:
            temp_score = 20
        elif temp < 75:
            temp_score = 10
        elif temp < 85:
            temp_score = 5
        else:
            temp_score = 0
        score -= 25 - temp_score

    # HW error rate: 0-20 points
    hw_pct = telemetry.get("hw_error_pct") or 0
    if hw_pct < 0.1:
        hw_score = 20
    elif hw_pct < 0.5:
        hw_score = 15
    elif hw_pct < 1.0:
        hw_score = 10
    elif hw_pct < 5.0:
        hw_score = 5
    else:
        hw_score = 0
    score -= 20 - hw_score

    # Uptime: 0-15 points
    uptime = telemetry.get("uptime_seconds") or 0
    if uptime >= 86400 * 7:  # 7 days
        up_score = 15
    elif uptime >= 86400:  # 1 day
        up_score = 10
    elif uptime >= 3600:  # 1 hour
        up_score = 5
    elif uptime > 0:
        up_score = 3
    else:
        up_score = 0
    score -= 15 - up_score

    return max(0, min(100, score))
