"""
CYPHER65 // AXE FLEET — Flask API Routes
==========================================
Blueprint for /api/axe-fleet/* endpoints.
Registered in app.py with minimal integration.

Endpoints:
  GET    /api/axe-fleet/devices          — list all devices
  POST   /api/axe-fleet/devices          — add a new device
  DELETE /api/axe-fleet/devices/<id>     — remove a device
  GET    /api/axe-fleet/devices/<id>     — get device detail + telemetry
  POST   /api/axe-fleet/devices/<id>/refresh — re-detect capabilities
  POST   /api/axe-fleet/devices/<id>/restart  — restart device
  POST   /api/axe-fleet/devices/<id>/identify — identify device
  POST   /api/axe-fleet/devices/<id>/config   — update device settings
  GET    /api/axe-fleet/summary          — fleet-wide summary stats
  GET    /api/axe-fleet/health           — fleet-wide health stats
"""
import json
import logging
import time
import uuid

from flask import Blueprint, jsonify, request

from .connector import AxeOSConnector, AxeOSConnectorError
from .models import infer_capabilities
from .registry import DeviceRegistry

log = logging.getLogger("cypher65.axe.routes")

# Registry is injected by app.py after creation
_registry = None


def init_routes(registry: DeviceRegistry):
    """Inject the DeviceRegistry instance. Called from app.py."""
    global _registry
    _registry = registry


axe_fleet_bp = Blueprint("axe_fleet", __name__)


# ── Device management ──────────────────────────────────────────────────


@axe_fleet_bp.route("/devices", methods=["GET"])
def list_devices():
    """List all registered AxeOS devices with latest telemetry."""
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    devices = _registry.list_devices()
    return jsonify({"devices": devices, "count": len(devices)})


@axe_fleet_bp.route("/devices", methods=["POST"])
def add_device():
    """Register a new AxeOS device.
    JSON body: { "ip_address": "...", "name": "..." }
    """
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500

    data = request.get_json(silent=True) or {}
    ip = (data.get("ip_address") or "").strip()
    name = (data.get("name") or "").strip()

    if not ip:
        return jsonify({"error": "ip_address is required"}), 400

    # Check if already registered
    existing = _registry.get_device_by_ip(ip)
    if existing:
        return jsonify({"error": "device already registered", "device": existing}), 409

    try:
        device = _registry.add_device(ip, name or ip)
        return jsonify({"success": True, "device": device}), 201
    except Exception as e:
        log.error("[axe] add_device error: %s", e)
        return jsonify({"error": f"failed to add device: {str(e)}"}), 500


@axe_fleet_bp.route("/devices/<device_id>", methods=["DELETE"])
def remove_device(device_id: str):
    """Remove a device from the registry."""
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    removed = _registry.remove_device(device_id)
    if not removed:
        return jsonify({"error": "device not found"}), 404
    return jsonify({"success": True})


@axe_fleet_bp.route("/devices/<device_id>", methods=["GET"])
def get_device(device_id: str):
    """Get device details with recent telemetry."""
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    device = _registry.get_device(device_id)
    if not device:
        return jsonify({"error": "device not found"}), 404

    telemetry = _registry.get_recent_telemetry(device_id, limit=60)
    latest = telemetry[0]["payload"] if telemetry else None

    return jsonify({
        "device": device,
        "latest_telemetry": latest,
        "telemetry_count": len(telemetry),
    })


@axe_fleet_bp.route("/devices/<device_id>/refresh", methods=["POST"])
def refresh_device(device_id: str):
    """Re-detect capabilities and refresh device info."""
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    device = _registry.get_device(device_id)
    if not device:
        return jsonify({"error": "device not found"}), 404

    try:
        conn = AxeOSConnector(device["ip_address"])
        info = conn.fetch_info()
        caps = conn.detect_capabilities()
        _registry.update_device(device_id, {
            "model": str(info.get("model", "")),
            "firmware": str(info.get("firmware", "")),
            "firmware_version": str(info.get("version", "")),
            "hostname": str(info.get("hostname", "")),
            "status": "ONLINE" if info.get("hashrate") else "IDLE",
            "capabilities": caps,
        })
        return jsonify({"success": True, "capabilities": caps})
    except AxeOSConnectorError as e:
        return jsonify({"error": f"device unreachable: {str(e)}"}), 503


# ── Device commands ─────────────────────────────────────────────────────


@axe_fleet_bp.route("/devices/<device_id>/restart", methods=["POST"])
def restart_device(device_id: str):
    """Restart a device. Requires restart capability."""
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    return _execute_device_command(device_id, "restart")


@axe_fleet_bp.route("/devices/<device_id>/identify", methods=["POST"])
def identify_device(device_id: str):
    """Flash device LED/screen for identification."""
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    return _execute_device_command(device_id, "identify")


@axe_fleet_bp.route("/devices/<device_id>/config", methods=["POST"])
def configure_device(device_id: str):
    """Update device settings.
    JSON body: { "settings": { "frequency": 600, "coreVoltage": 1200 } }
    """
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    device = _registry.get_device(device_id)
    if not device:
        return jsonify({"error": "device not found"}), 404

    data = request.get_json(silent=True) or {}
    settings = data.get("settings", {})

    if not settings:
        return jsonify({"error": "settings object required"}), 400

    caps = device.get("capabilities", {})
    if not caps.get("configure"):
        return jsonify({"error": "configuration not supported by this device"}), 400

    # Validate settings against capabilities
    if "frequency" in settings and not caps.get("frequencyControl"):
        return jsonify({"error": "frequency control not supported by this device"}), 400
    if "coreVoltage" in settings and not caps.get("voltageControl"):
        return jsonify({"error": "voltage control not supported by this device"}), 400

    try:
        conn = AxeOSConnector(device["ip_address"])
        result = conn.update_settings(settings)
        return jsonify({"success": True, "result": result})
    except AxeOSConnectorError as e:
        return jsonify({"error": str(e)}), 503


# ── Fleet summary ──────────────────────────────────────────────────────


@axe_fleet_bp.route("/summary", methods=["GET"])
def fleet_summary():
    """Fleet-wide summary: total, online, offline, total hashrate, etc."""
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    devices = _registry.list_devices()
    total = len(devices)
    online = sum(1 for d in devices if d.get("status") == "ONLINE" or d.get("status") == "HASHING")
    offline = total - online
    total_hr = 0
    for d in devices:
        tel = _registry.get_recent_telemetry(d["id"], limit=1)
        if tel:
            p = tel[0].get("payload", {})
            total_hr += int(p.get("hashrate_hs", 0))

    return jsonify({
        "total_devices": total,
        "online": online,
        "offline": offline,
        "total_hashrate_hs": total_hr,
        "total_hashrate_str": _fmt_hr(total_hr),
        "devices": devices,
    })


# ── Test / seed endpoint ──────────────────────────────────────────────


@axe_fleet_bp.route("/test-devices", methods=["POST"])
def seed_test_devices():
    """Populate fleet with simulated AxeOS devices for testing.
    Creates 4 devices with realistic telemetry (hashrate, temp, fan, power,
    uptime, best diff) and capabilities (restart, identify, pause).
    
    Use DELETE /api/axe-fleet/devices/<id> to remove individual devices
    after testing.
    """
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500

    now = int(time.time())
    devices = _registry.list_devices()
    if len(devices) >= 4:
        return jsonify({"error": "Fleet already has devices — remove them first or use individual IP add",
                        "device_count": len(devices)}), 409

    mock_devices = [
        {
            "name": "Garage Bitaxe",
            "ip": "192.168.1.100",
            "model": "Bitaxe ULP",
            "firmware": "AxeOS",
            "version": "2.6.0",
            "hostname": "bitaxe-garage",
            "status": "ONLINE",
            "hashrate_hs": 5200000000000,  # 5.2 TH/s
            "temperature": 62,
            "fan_speed": 80,
            "fan_rpm": 4200,
            "power_watts": 42,
            "voltage_mv": 1200,
            "frequency_mhz": 525,
            "best_diff": "42.8T",
            "uptime_seconds": 259200,  # 3 days
            "efficiency_jth": round(42 / 5.2, 2),
            "shares_accepted": 15823,
            "shares_rejected": 47,
            "hw_error_pct": 0.3,
            "wifi_rssi": -65,
            "free_heap": 128000,
        },
        {
            "name": "Office NerdAxe",
            "ip": "192.168.1.101",
            "model": "NerdAxe v2",
            "firmware": "AxeOS",
            "version": "2.5.1",
            "hostname": "nerdaxe-office",
            "status": "ONLINE",
            "hashrate_hs": 2100000000000,  # 2.1 TH/s
            "temperature": 58,
            "fan_speed": 65,
            "fan_rpm": 3800,
            "power_watts": 18,
            "voltage_mv": 1100,
            "frequency_mhz": 450,
            "best_diff": "12.5T",
            "uptime_seconds": 604800,  # 7 days
            "efficiency_jth": round(18 / 2.1, 2),
            "shares_accepted": 45231,
            "shares_rejected": 89,
            "hw_error_pct": 0.2,
            "wifi_rssi": -72,
            "free_heap": 95000,
        },
        {
            "name": "Lab Bitaxe (hot)",
            "ip": "192.168.1.102",
            "model": "Bitaxe Max",
            "firmware": "AxeOS",
            "version": "2.6.0",
            "hostname": "bitaxe-lab",
            "status": "WARNING",
            "hashrate_hs": 3800000000000,  # 3.8 TH/s
            "temperature": 82,  # High temp → warning
            "fan_speed": 100,
            "fan_rpm": 5200,
            "power_watts": 38,
            "voltage_mv": 1250,
            "frequency_mhz": 500,
            "best_diff": "28.3T",
            "uptime_seconds": 43200,  # 12 hours
            "efficiency_jth": round(38 / 3.8, 2),
            "shares_accepted": 5872,
            "shares_rejected": 215,
            "hw_error_pct": 3.5,  # High error rate
            "wifi_rssi": -85,
            "free_heap": 72000,
        },
        {
            "name": "Basement S19",
            "ip": "192.168.1.200",
            "model": "Antminer S19 Pro",
            "firmware": "Braiins OS+",
            "version": "22.0",
            "hostname": "s19-basement",
            "status": "OFFLINE",
            "hashrate_hs": 0,
            "temperature": None,
            "fan_speed": 0,
            "fan_rpm": 0,
            "power_watts": 0,
            "voltage_mv": None,
            "frequency_mhz": 0,
            "best_diff": "",
            "uptime_seconds": 0,
            "efficiency_jth": None,
            "shares_accepted": 0,
            "shares_rejected": 0,
            "hw_error_pct": 0.0,
            "wifi_rssi": None,
            "free_heap": 0,
        },
    ]

    created = []
    for m in mock_devices:
        device_id = uuid.uuid4().hex[:12]

        # Register device
        device_dict = {
            "id": device_id,
            "name": m["name"],
            "model": m["model"],
            "manufacturer": "Bitaxe" if "Bitaxe" in m["model"] or "NerdAxe" in m["model"] else "Bitmain",
            "firmware": m["firmware"],
            "firmware_version": m["version"],
            "api_version": "2.0.0",
            "ip_address": m["ip"],
            "hostname": m["hostname"],
            "mac_address": "",
            "last_seen": now if m["hashrate_hs"] > 0 else 0,
            "status": m["status"],
            "group_id": "test-fleet",
            "added_at": now,
            "updated_at": now,
        }

        # Set capabilities based on firmware
        caps = {
            "telemetry": True,
            "statistics": True,
            "restart": m["status"] == "ONLINE" or m["status"] == "WARNING",
            "identify": m["status"] == "ONLINE" or m["status"] == "WARNING",
            "pause": m["firmware"] == "AxeOS",
            "resume": m["firmware"] == "AxeOS",
            "frequencyControl": m["firmware"] == "AxeOS",
            "voltageControl": m["firmware"] == "AxeOS",
            "powerControl": False,
            "configure": m["firmware"] == "AxeOS",
        }
        device_dict["capabilities"] = caps

        # Persist via registry internals
        _registry._persist_device(device_dict)

        # Populate telemetry (10 historical data points for charts)
        for i in range(10):
            ts = now - (9 - i) * 300  # 5 min intervals
            temp_variation = (i % 3 - 1) * 2  # -2, 0, +2
            hr_variation = m["hashrate_hs"] * (1 + (i % 5 - 2) * 0.02)  # ±4%

            tel = {
                "ts": ts,
                "device_id": device_id,
                "hashrate_hs": int(hr_variation) if m["hashrate_hs"] > 0 else 0,
                "temperature": m["temperature"] + temp_variation if m["temperature"] is not None else None,
                "fan_speed": m["fan_speed"],
                "fan_rpm": m["fan_rpm"],
                "power_watts": m["power_watts"],
                "voltage_mv": m["voltage_mv"],
                "frequency_mhz": m["frequency_mhz"],
                "best_diff": m["best_diff"],
                "uptime_seconds": m["uptime_seconds"] + ts - now,
                "efficiency_jth": m["efficiency_jth"],
                "shares_accepted": max(0, m["shares_accepted"] + (i - 5) * 100),
                "shares_rejected": max(0, m["shares_rejected"] + (i - 5) * 5),
                "hw_error_pct": m["hw_error_pct"],
                "wifi_rssi": m["wifi_rssi"],
                "free_heap": m["free_heap"],
                "stratum_status": "connected" if m["hashrate_hs"] > 0 else "disconnected",
            }
            _registry.save_telemetry(device_id, tel)

        created.append(device_dict)

    log.info("[axe] seeded %d test devices", len(created))
    return jsonify({"success": True, "devices": created, "count": len(created)}), 201


# ── Helpers ─────────────────────────────────────────────────────────────


def _execute_device_command(device_id: str, command: str):
    """Execute a command on a device. Shared by restart/identify endpoints."""
    device = _registry.get_device(device_id)
    if not device:
        return jsonify({"error": "device not found"}), 404

    caps = device.get("capabilities", {})
    if not caps.get(command):
        return jsonify({"error": f"'{command}' not supported by this device"}), 400

    try:
        conn = AxeOSConnector(device["ip_address"])
        if command == "restart":
            result = conn.restart()
        elif command == "identify":
            result = conn.identify()
        else:
            return jsonify({"error": f"unknown command: {command}"}), 400
        return jsonify({"success": True, "result": result})
    except AxeOSConnectorError as e:
        return jsonify({"error": str(e)}), 503


@axe_fleet_bp.route("/health", methods=["GET"])
def fleet_health():
    """Fleet-wide health summary with per-device health scores, capabilities,
    fleet-level averages and grouped device lists.

    Returns:
      fleet_stats:  aggregated metrics (total, online, avg_temp, total_power_w,
                    avg_health, total_hashrate_hs, best_diff, efficiency_jth)
      device_health: list of devices with health_score, capabilities, and
                     latest telemetry
      groups:       devices grouped by status (online, warning, offline)
    """
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    devices = _registry.list_devices()
    now = int(time.time())

    from .models import infer_health_score

    total = len(devices)
    online = 0
    offline = 0
    warning = 0
    total_hashrate_hs = 0
    total_power_w = 0
    temp_sum = 0
    temp_count = 0
    health_sum = 0
    health_count = 0
    best_diff_global = 0.0
    best_diff_str_global = ""

    device_health_list = []
    groups = {"online": [], "warning": [], "offline": []}

    for d in devices:
        did = d["id"]
        tel_raw = _registry.get_recent_telemetry(did, limit=1)
        tel = tel_raw[0]["payload"] if tel_raw else {}
        status = d.get("status", "OFFLINE")

        # Calculate health score
        health_score = infer_health_score(tel) if tel else 0

        # Aggregate
        if status in ("ONLINE", "HASHING"):
            online += 1
            groups["online"].append(did)
        elif status == "WARNING":
            warning += 1
            groups["warning"].append(did)
        else:
            offline += 1
            groups["offline"].append(did)

        hr = int(tel.get("hashrate_hs", 0))
        pw = tel.get("power_watts")
        tmp = tel.get("temperature")
        bd = parse_diff_to_float(tel.get("best_diff", "")) if tel.get("best_diff") else 0.0

        total_hashrate_hs += hr
        if pw:
            total_power_w += pw
        if tmp is not None:
            temp_sum += tmp
            temp_count += 1
        health_sum += health_score
        health_count += 1
        if bd > best_diff_global:
            best_diff_global = bd
            best_diff_str_global = tel.get("best_diff", "")

        # Capabilities
        caps = d.get("capabilities", {}) or {}
        supported_cmds = [k for k, v in caps.items() if v]

        device_health_list.append({
            "id": did,
            "name": d.get("name", ""),
            "model": d.get("model", ""),
            "ip_address": d.get("ip_address", ""),
            "status": status,
            "health_score": health_score,
            "capabilities": supported_cmds,
            "telemetry": {
                "hashrate_hs": hr,
                "hashrate_str": _fmt_hr(hr),
                "temperature": tmp,
                "power_watts": pw,
                "frequency_mhz": tel.get("frequency_mhz"),
                "voltage_mv": tel.get("voltage_mv"),
                "best_diff": tel.get("best_diff", ""),
                "uptime_seconds": tel.get("uptime_seconds", 0),
                "uptime_str": _fmt_uptime(tel.get("uptime_seconds", 0)),
                "free_heap": tel.get("free_heap"),
                "wifi_rssi": tel.get("wifi_rssi"),
                "shares_accepted": tel.get("shares_accepted", 0),
                "shares_rejected": tel.get("shares_rejected", 0),
                "hw_error_pct": tel.get("hw_error_pct", 0.0),
                "efficiency_jth": tel.get("efficiency_jth"),
                "ts": tel.get("ts", now),
                "age_seconds": now - tel.get("ts", now),
            },
            "last_seen": d.get("last_seen", 0),
        })

    avg_temp = round(temp_sum / temp_count, 1) if temp_count > 0 else None
    avg_health = round(health_sum / health_count, 0) if health_count > 0 else 0
    efficiency_jth = round(total_power_w / (total_hashrate_hs / 1e12), 2) if total_hashrate_hs > 0 and total_power_w > 0 else None

    return jsonify({
        "fleet_stats": {
            "total_devices": total,
            "online": online,
            "warning": warning,
            "offline": offline,
            "total_hashrate_hs": total_hashrate_hs,
            "total_hashrate_str": _fmt_hr(total_hashrate_hs),
            "total_power_w": total_power_w,
            "avg_temperature_c": avg_temp,
            "avg_health_score": avg_health,
            "best_diff": best_diff_str_global,
            "efficiency_jth": efficiency_jth,
        },
        "device_health": device_health_list,
        "groups": groups,
    })


def _fmt_hr(hs: int) -> str:
    """Format hashrate in H/s to human-readable string."""
    if hs >= 1e15:
        return f"{hs / 1e15:.2f} PH/s"
    if hs >= 1e12:
        return f"{hs / 1e12:.2f} TH/s"
    if hs >= 1e9:
        return f"{hs / 1e9:.2f} GH/s"
    if hs >= 1e6:
        return f"{hs / 1e6:.2f} MH/s"
    return f"{hs:.0f} H/s"


def _fmt_uptime(seconds: int) -> str:
    """Format uptime in seconds to human-readable string."""
    if not seconds:
        return "—"
    d = seconds // 86400
    h = (seconds % 86400) // 3600
    m = (seconds % 3600) // 60
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    return " ".join(parts) if parts else "<1m"


def parse_diff_to_float(diff_str: str) -> float:
    """Parse a difficulty string like '42.8T' to float."""
    if not diff_str:
        return 0.0
    if isinstance(diff_str, (int, float)):
        return float(diff_str)
    try:
        s = str(diff_str).strip()
        m = __import__("re").match(r"^([\d.]+)\s*([kKmMgGtTpPeE]?)", s)
        if not m:
            return 0.0
        num = float(m.group(1))
        suf = m.group(2).upper()
        mult = {"": 1, "K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12, "P": 1e15, "E": 1e18}
        return num * mult.get(suf, 1)
    except (ValueError, TypeError):
        return 0.0
