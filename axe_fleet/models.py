"""
CYPHER65 // AXE FLEET — Data Models
====================================
Device, Capability, Telemetry, and related types for the AxeOS fleet manager.
All models use simple dicts for SQLite compatibility (no ORM).
"""

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
STATUS_ONLINE = "ONLINE"
STATUS_OFFLINE = "OFFLINE"
STATUS_HASHING = "HASHING"
STATUS_PAUSED = "PAUSED"
STATUS_WARNING = "WARNING"
STATUS_ERROR = "ERROR"

# ── Device schema keys ───────────────────────────────────────────────────
DEVICE_SCHEMA = {
    "id": "",                 # unique id (uuid or hash)
    "name": "",               # user-assigned name (e.g. "Garage Bitaxe")
    "model": "",              # Bitaxe / NerdAxe / NerdQaxe / NerdQaxe++ / unknown
    "manufacturer": "",       # inferred from model / system info
    "firmware": "",           # e.g. "AxeOS"
    "firmware_version": "",   # e.g. "2.6.0"
    "api_version": "",        # e.g. "2.0.0"
    "ip_address": "",         # IPv4 string
    "hostname": "",           # device hostname
    "mac_address": "",        # MAC (if available)
    "last_seen": 0,           # unix ts
    "status": STATUS_OFFLINE,
    "group_id": "",           # optional group for fleet management
    "added_at": 0,            # unix ts
    "updated_at": 0,          # unix ts
}

# ── Telemetry schema keys ────────────────────────────────────────────────
TELEMETRY_SCHEMA = {
    "ts": 0,                  # unix timestamp of measurement
    "device_id": "",          # refers to device.id
    "hashrate_hs": 0,         # H/s
    "hashrate_str": "",       # formatted (e.g. "1.21 TH/s")
    "expected_hashrate": 0,   # H/s (from ASIC config)
    # Fase 5: hashrate windows (H/s) — None/0 when firmware does not expose them
    "hashrate_1m": None,      # H/s 1-minute average
    "hashrate_10m": None,     # H/s 10-minute average
    "hashrate_1h": None,      # H/s 1-hour average
    "temperature": None,      # °C (board temp)
    "temp_asic": None,        # °C (ASIC junction temp, if available)
    "temp_vreg": None,        # °C (voltage regulator temp)
    "fan_speed": None,        # 0-100 percent
    "fan_rpm": None,
    "power_watts": None,      # watts
    "voltage_mv": None,       # core voltage in mV
    "voltage_actual_mv": None, # actual measured voltage
    "frequency_mhz": None,    # ASIC frequency in MHz
    "current_ma": None,       # current in mA
    "efficiency_jth": None,   # J/TH
    "best_diff": "",          # best difficulty string
    "best_diff_raw": 0.0,
    "shares_accepted": 0,
    "shares_rejected": 0,
    "shares_stale": 0,
    "hw_errors": 0,
    "hw_error_pct": 0.0,      # HW error rate in %
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
    score -= (40 - hr_score)

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
        score -= (25 - temp_score)

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
    score -= (20 - hw_score)

    # Uptime: 0-15 points
    uptime = telemetry.get("uptime_seconds") or 0
    if uptime >= 86400 * 7:    # 7 days
        up_score = 15
    elif uptime >= 86400:       # 1 day
        up_score = 10
    elif uptime >= 3600:        # 1 hour
        up_score = 5
    elif uptime > 0:
        up_score = 3
    else:
        up_score = 0
    score -= (15 - up_score)

    return max(0, min(100, score))
