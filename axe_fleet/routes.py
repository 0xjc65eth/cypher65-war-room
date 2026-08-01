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
import os
import sqlite3
import threading
import time
import uuid
from functools import wraps

from flask import Blueprint, jsonify, request, session

from services.tenant import get_tenant_id as _get_tenant_id, require_tenant

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
@require_tenant
def list_devices(tenant_id: str = ""):
    """List all registered AxeOS devices with latest telemetry."""
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    devices = _registry.list_devices(tenant_id=tenant_id)
    return jsonify({"devices": devices, "count": len(devices), "tenant_id": tenant_id})


@axe_fleet_bp.route("/devices", methods=["POST"])
@require_tenant
def add_device(tenant_id: str = ""):
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
        device = _registry.add_device(ip, name or ip, tenant_id=tenant_id)
        return jsonify({"success": True, "device": device}), 201
    except Exception as e:
        log.error("[axe] add_device error: %s", e)
        return jsonify({"error": f"failed to add device: {str(e)}"}), 500


@axe_fleet_bp.route("/devices/<device_id>", methods=["DELETE"])
@require_tenant
def remove_device(device_id: str, tenant_id: str = ""):
    """Remove a device from the registry."""
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    removed = _registry.remove_device(device_id, tenant_id=tenant_id)
    if not removed:
        return jsonify({"error": "device not found"}), 404
    return jsonify({"success": True})


@axe_fleet_bp.route("/devices/<device_id>", methods=["GET"])
@require_tenant
def get_device(device_id: str, tenant_id: str = ""):
    """Get device details with recent telemetry."""
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    device = _registry.get_device(device_id, tenant_id=tenant_id)
    if not device:
        return jsonify({"error": "device not found"}), 404

    telemetry = _registry.get_recent_telemetry(device_id, limit=60, tenant_id=tenant_id)
    latest = telemetry[0]["payload"] if telemetry else None

    return jsonify({
        "device": device,
        "latest_telemetry": latest,
        "telemetry_count": len(telemetry),
    })


# ── Per-device telemetry endpoint ────────────────────────────────────────


@axe_fleet_bp.route("/devices/<device_id>/telemetry", methods=["GET"])
@require_tenant
def device_telemetry(device_id: str, tenant_id: str = ""):
    """Get detailed telemetry history for a specific device.
    Query params:
      - limit (int, optional): max entries, default 120
    Returns full telemetry payload with metadata."""
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    device = _registry.get_device(device_id, tenant_id=tenant_id)
    if not device:
        return jsonify({"error": "device not found"}), 404

    limit = request.args.get("limit", 120, type=int)
    telemetry = _registry.get_recent_telemetry(device_id, limit=limit, tenant_id=tenant_id)

    return jsonify({
        "device": {
            "id": device["id"],
            "name": device["name"],
            "model": device["model"],
            "ip_address": device["ip_address"],
            "status": device["status"],
        },
        "telemetry": [{"ts": e["ts"], "payload": e["payload"]} for e in telemetry],
        "count": len(telemetry),
    })


# ── Per-device chart data endpoint ───────────────────────────────────────


@axe_fleet_bp.route("/devices/<device_id>/chart-data", methods=["GET"])
@require_tenant
def device_chart_data(device_id: str, tenant_id: str = ""):
    """Get chart-ready telemetry series for a device.
    Query params:
      - limit (int, optional): max data points, default 120
    Returns structured arrays suitable for direct Chart.js consumption."""
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    device = _registry.get_device(device_id, tenant_id=tenant_id)
    if not device:
        return jsonify({"error": "device not found"}), 404

    limit = request.args.get("limit", 120, type=int)
    series = _registry.get_telemetry_chart_data(device_id, limit=limit, tenant_id=tenant_id)

    return jsonify({
        "device_id": device_id,
        "device_name": device["name"],
        "series": series,
        "count": len(series["ts"]),
    })


# ── Per-device health score endpoint ─────────────────────────────────────


@axe_fleet_bp.route("/devices/<device_id>/health", methods=["GET"])
@require_tenant
def device_health(device_id: str, tenant_id: str = ""):
    """Get health score and status for a specific device.
    Returns health_score (0-100), active issues, and latest telemetry."""
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    device = _registry.get_device(device_id, tenant_id=tenant_id)
    if not device:
        return jsonify({"error": "device not found"}), 404

    from .models import infer_health_score

    now = int(time.time())
    tel_raw = _registry.get_recent_telemetry(device_id, limit=1, tenant_id=tenant_id)
    tel = tel_raw[0]["payload"] if tel_raw else {}
    health_score = infer_health_score(tel) if tel else 0

    # Build active issues
    issues = []
    if device.get("status") == "OFFLINE":
        issues.append("device_offline")
    elif device.get("status") == "WARNING":
        issues.append("device_warning")
    if tel:
        temp = tel.get("temperature")
        if temp is not None and temp >= 80:
            issues.append("high_temperature")
        hw_pct = tel.get("hw_error_pct", 0)
        if hw_pct >= 5:
            issues.append("high_hw_error_rate")
        hr = int(tel.get("hashrate_hs", 0))
        if hr == 0:
            issues.append("zero_hashrate")

    return jsonify({
        "device_id": device_id,
        "device_name": device["name"],
        "status": device.get("status", "OFFLINE"),
        "health_score": health_score,
        "health_label": _health_label(health_score),
        "active_issues": issues,
        "latest_telemetry": tel,
        "last_seen": device.get("last_seen", 0),
        "age_seconds": now - device.get("last_seen", now),
    })


@axe_fleet_bp.route("/devices/<device_id>/refresh", methods=["POST"])
def refresh_device(device_id: str):
    """Re-detect capabilities and refresh device info."""
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    device = _registry.get_device(device_id, tenant_id=_get_tenant_id())
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


# ── Tenant-aware auth decorators (defined above, before first route) ──


def _require_local_or_session(f):
    """Require either localhost access or an active Flask session.
    
    This is a lightweight security layer for device control endpoints.
    In production, replace with full JWT/OAuth authentication.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        # Allow localhost always (safe for development)
        remote = request.remote_addr or ""
        if remote in ("127.0.0.1", "::1", "localhost"):
            return f(*args, **kwargs)
        
        # Also allow requests from the same machine
        if remote == request.host.split(":")[0]:
            return f(*args, **kwargs)
        
        # Check for active Flask session
        if session and session.get("authenticated"):
            return f(*args, **kwargs)
        
        # Check for Authorization header (Bearer token or API key)
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and len(auth) > 20:
            return f(*args, **kwargs)
        
        # Check for X-API-Key header (simple key-based auth)
        api_key = request.headers.get("X-API-Key", "")
        if api_key and len(api_key) >= 16:
            return f(*args, **kwargs)
        
        log.warning("[axe] Unauthorized device control attempt from %s", remote)
        return jsonify({"error": "authentication required — device control restricted to localhost or authenticated session"}), 401
    return wrapper


# ── Device commands ─────────────────────────────────────────────────────


@axe_fleet_bp.route("/devices/<device_id>/restart", methods=["POST"])
@_require_local_or_session
def restart_device(device_id: str):
    """Restart a device. Requires restart capability."""
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    return _execute_device_command(device_id, "restart")


@axe_fleet_bp.route("/devices/<device_id>/identify", methods=["POST"])
@_require_local_or_session
def identify_device(device_id: str):
    """Flash device LED/screen for identification."""
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    return _execute_device_command(device_id, "identify")


@axe_fleet_bp.route("/devices/<device_id>/config", methods=["POST"])
@_require_local_or_session
def configure_device(device_id: str):
    """Update device settings.
    JSON body: { "settings": { "frequency": 600, "coreVoltage": 1200 } }
    """
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    device = _registry.get_device(device_id, tenant_id=_get_tenant_id())
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
@require_tenant
def fleet_summary(tenant_id: str = ""):
    """Fleet-wide summary: total, online, offline, total hashrate, etc."""
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    devices = _registry.list_devices(tenant_id=tenant_id)
    total = len(devices)
    online = sum(1 for d in devices if d.get("status") == "ONLINE" or d.get("status") == "HASHING")
    offline = total - online
    from .models import infer_health_score
    total_hr = 0
    enriched_devices = []
    for d in devices:
        tel = _registry.get_recent_telemetry(d["id"], limit=1, tenant_id=tenant_id)
        p = {}
        if tel:
            p = tel[0].get("payload", {})
            total_hr += int(p.get("hashrate_hs", 0))
        # Enrich device with latest telemetry metrics
        enriched = dict(d)
        enriched["_telemetry"] = {
            "hashrate_hs": p.get("hashrate_hs", 0),
            "temperature": p.get("temperature"),
            "fan_speed": p.get("fan_speed"),
            "fan_rpm": p.get("fan_rpm"),
            "power_watts": p.get("power_watts"),
            "efficiency_jth": p.get("efficiency_jth"),
            "shares_accepted": p.get("shares_accepted", 0),
            "shares_rejected": p.get("shares_rejected", 0),
            "uptime_seconds": p.get("uptime_seconds", 0),
            "best_diff": p.get("best_diff"),
            "hw_error_pct": p.get("hw_error_pct", 0),
            "voltage_mv": p.get("voltage_mv"),
            "frequency_mhz": p.get("frequency_mhz"),
        }
        # Compute health score from model (import outside loop)
        try:
            health = infer_health_score(enriched["_telemetry"])
            enriched["_health"] = {
                "score": health.get("score", 50),
                "label": health.get("label", "unknown"),
                "issues": health.get("issues", []),
            }
        except Exception:
            enriched["_health"] = {"score": 50, "label": "unknown", "issues": []}
        enriched_devices.append(enriched)

    return jsonify({
        "total_devices": total,
        "online": online,
        "offline": offline,
        "total_hashrate_hs": total_hr,
        "total_hashrate_str": _fmt_hr(total_hr),
        "devices": enriched_devices,
    })


# ── Test / seed endpoint ──────────────────────────────────────────────


@axe_fleet_bp.route("/test-devices", methods=["POST"])
def seed_test_devices():
    """Populate fleet with simulated AxeOS devices for testing.
    Creates 4 devices with realistic telemetry (hashrate, temp, fan, power,
    uptime, best diff) and capabilities (restart, identify, pause).

    GATED by DEBUG_MOCK (config.py): disabled in production so mock devices
    are never exposed via the public API. Set DEBUG_MOCK=1 for local dev.

    Use DELETE /api/axe-fleet/devices/<id> to remove individual devices
    after testing.
    """
    if os.environ.get("DEBUG_MOCK") != "1":
        return jsonify({"error": "test-devices endpoint disabled (set DEBUG_MOCK=1)"}), 403
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


# ── Connectivity diagnostic endpoint ─────────────────────────────────────


@axe_fleet_bp.route("/diagnose/<path:ip_or_host>", methods=["GET"])
def diagnose_device(ip_or_host: str):
    """Run a full connectivity diagnostic against a device IP/hostname.

    Returns a comprehensive JSON result with:
      - ip, port, dns_resolution, http_connect, api_response
      - http_status, elapsed_ms, error_type, error_detail
      - device_info if connected successfully (model, firmware, hostname, hashrate)

    This endpoint does NOT require the device to be registered.
    Use it to test connectivity BEFORE adding a device.

    Example:
      GET /api/axe-fleet/diagnose/192.168.1.100
      GET /api/axe-fleet/diagnose/192.168.1.50?port=8080
    """
    port = request.args.get("port", 80, type=int)
    try:
        conn = AxeOSConnector(ip_or_host, port=port)
        result = conn._diagnose_connectivity()
        return jsonify(result)
    except Exception as e:
        return jsonify({
            "ip": ip_or_host,
            "port": port,
            "error": True,
            "error_type": "EXCEPTION",
            "error_detail": str(e),
            "http_connect": False,
        })


# ── Remote Access (Tailscale) ──────────────────────────────────────────


@axe_fleet_bp.route("/remote/status", methods=["GET"])
def remote_status():
    """Get Tailscale remote access status for the host.
    Checks local tailscale daemon and returns connection info.
    """
    from services.tailscale_adapter import get_local_status
    status = get_local_status()
    return jsonify({"remote_access": status})


@axe_fleet_bp.route("/remote/health", methods=["GET"])
def remote_health():
    """Full remote health check: tailscale status + Axe Fleet reachability.
    Returns a combined health payload.
    """
    from services.tailscale_adapter import get_local_status, diagnose_connection

    ts = get_local_status()
    health = {
        "tailscale": ts,
        "fleet": {
            "total_devices": 0,
            "reachable": 0,
            "unreachable": 0,
        },
        "overall": "offline",
        "errors": [],
    }

    if not ts["connected"]:
        health["errors"].append("Tailscale not connected")
        return jsonify(health)

    # Test reachability of registered devices
    if _registry:
        devices = _registry.list_devices()
        reachable = 0
        for d in devices:
            diag = diagnose_connection(d["ip_address"], timeout=3)
            if diag.get("reachable"):
                reachable += 1
        health["fleet"] = {
            "total_devices": len(devices),
            "reachable": reachable,
            "unreachable": len(devices) - reachable,
        }

    health["overall"] = "online" if not health["errors"] else "degraded"
    return jsonify(health)


@axe_fleet_bp.route("/remote/devices", methods=["GET"])
def remote_devices():
    """List devices reachable via the tailnet.
    Only returns devices that respond to ping.
    Uses optional Tailscale API key from settings for enhanced info.
    """
    from services.tailscale_adapter import get_local_status

    ts = get_local_status()
    result = {
        "tailscale": ts,
        "devices": [],
        "count": 0,
    }

    if not ts["connected"]:
        return jsonify(result)

    if _registry:
        for d in _registry.list_devices():
            from services.tailscale_adapter import diagnose_connection
            diag = diagnose_connection(d["ip_address"], timeout=3)
            entry = {
                "id": d.get("id", ""),
                "name": d.get("name", ""),
                "ip": d.get("ip_address", ""),
                "model": d.get("model", ""),
                "status": d.get("status", "OFFLINE"),
                "reachable": diag.get("reachable", False),
                "latency_ms": diag.get("elapsed_ms"),
            }
            result["devices"].append(entry)

    result["count"] = len(result["devices"])
    return jsonify(result)


@axe_fleet_bp.route("/remote/test-connection", methods=["POST"])
def remote_test_connection():
    """Run a full remote connectivity test suite.
    Returns per-test results with pass/fail and timing.
    """
    from services.tailscale_adapter import get_local_status, diagnose_connection

    data = request.get_json(silent=True) or {}
    target_ip = data.get("target_ip", "")

    tests = []

    # Test 1: Local tailscale daemon
    ts = get_local_status()
    tests.append({
        "name": "Tailscale daemon",
        "passed": ts["connected"],
        "detail": f"IP: {ts['ip']}, Hostname: {ts['hostname']}" if ts["connected"] else ts.get("error", "not running"),
    })

    # Test 2: Host self-reachability
    if ts["ip"]:
        self_test = diagnose_connection(ts["ip"], timeout=5)
        tests.append({
            "name": "Local dashboard reachability",
            "passed": self_test["reachable"],
            "detail": f"{self_test.get('elapsed_ms', 'N/A')}ms" if self_test["reachable"] else self_test.get("error", "unreachable"),
        })

    # Test 3: Target IP (optional, e.g. another tailnet device)
    if target_ip:
        target_test = diagnose_connection(target_ip, timeout=5)
        tests.append({
            "name": f"Remote target {target_ip}",
            "passed": target_test["reachable"],
            "detail": f"{target_test.get('elapsed_ms', 'N/A')}ms" if target_test["reachable"] else target_test.get("error", "unreachable"),
        })

    # Test 4: Registered devices
    if _registry:
        devices = _registry.list_devices()
        reachable_count = 0
        for d in devices:
            diag = diagnose_connection(d["ip_address"], timeout=3)
            if diag.get("reachable"):
                reachable_count += 1
        tests.append({
            "name": f"Fleet devices ({len(devices)} total)",
            "passed": reachable_count == len(devices),
            "detail": f"{reachable_count}/{len(devices)} reachable",
        })

    all_passed = all(t["passed"] for t in tests)
    return jsonify({
        "success": all_passed,
        "overall": "passed" if all_passed else "failed",
        "tests": tests,
        "checked_at": int(time.time()),
    })


# ── Power Plugs (Tuya Smart Plugs) ────────────────────────────────────────


def _get_tuya_credentials() -> dict:
    """Read Tuya credentials from settings DB or environment variables.
    Returns dict with keys: access_id, access_secret, region (or empty).
    """
    s = {}
    try:
        conn = _get_db_internal()
        cur = conn.cursor()
        for k in ('tuya_access_id', 'tuya_access_secret', 'tuya_region', 'tuya_uid'):
            cur.execute("SELECT value FROM settings WHERE key=?", (k,))
            r = cur.fetchone()
            if r and r['value']:
                s[k] = r['value']
        conn.close()
    except Exception as e:
        log.warning("[tuya] failed to read settings from DB: %s", e)

    # Environment variables override DB
    s["access_id"] = os.environ.get("TUYA_ACCESS_ID", "") or s.get("tuya_access_id", "")
    s["access_secret"] = os.environ.get("TUYA_ACCESS_SECRET", "") or s.get("tuya_access_secret", "")
    s["region"] = os.environ.get("TUYA_REGION", "") or s.get("tuya_region", "us")
    s["uid"] = os.environ.get("TUYA_UID", "") or s.get("tuya_uid", "")
    return {
        "access_id": s.get("tuya_access_id", "") or os.environ.get("TUYA_ACCESS_ID", ""),
        "access_secret": s.get("tuya_access_secret", "") or os.environ.get("TUYA_ACCESS_SECRET", ""),
        "region": s.get("tuya_region", "") or os.environ.get("TUYA_REGION", "us"),
        "uid": s.get("tuya_uid", "") or os.environ.get("TUYA_UID", ""),
    }


@axe_fleet_bp.route("/power-plugs", methods=["GET"])
def list_power_plugs():
    """List all Tuya smart plugs associated with the user account.
    Credentials from settings DB or environment variables.
    """
    from services.tuya_adapter import TuyaCloudAdapter

    creds = _get_tuya_credentials()
    if not creds.get("access_id") or not creds.get("access_secret"):
        return jsonify({
            "plugs": [],
            "count": 0,
            "configured": False,
            "message": "Tuya credentials not configured. Add TUYA_ACCESS_ID and TUYA_ACCESS_SECRET in Settings.",
        })

    adapter = TuyaCloudAdapter()
    devices = adapter.list_devices(**creds)
    return jsonify({
        "plugs": devices,
        "count": len(devices),
        "configured": True,
    })


@axe_fleet_bp.route("/power-plugs/save-credentials", methods=["POST"])
@_require_local_or_session
def save_tuya_credentials():
    """Save Tuya Cloud credentials to the settings DB.
    Body (JSON):
      - access_id (str, required)
      - access_secret (str, required)
      - region (str, optional, default 'us')
      - uid (str, optional)
    """
    data = request.get_json(silent=True) or {}
    access_id = (data.get("access_id") or "").strip()
    access_secret = (data.get("access_secret") or "").strip()
    region = (data.get("region") or "us").strip()
    uid = (data.get("uid") or "").strip()

    if not access_id or not access_secret:
        return jsonify({"success": False, "error": "access_id and access_secret are required"}), 400

    from services.tuya_adapter import TuyaCloudAdapter
    adapter = TuyaCloudAdapter()
    validation = adapter.validate_credentials(
        access_id=access_id, access_secret=access_secret, region=region
    )
    if not validation.get("valid"):
        return jsonify({"success": False, "error": validation.get("error", "invalid credentials")})

    try:
        conn = _get_db_internal()
        now = int(time.time())
        pairs = [
            ("tuya_access_id", access_id),
            ("tuya_access_secret", access_secret),
            ("tuya_region", region),
        ]
        if uid:
            pairs.append(("tuya_uid", uid))
        c = conn.cursor()
        for k, v in pairs:
            c.execute(
                "INSERT INTO settings (key, value, updated_ts) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_ts=excluded.updated_ts",
                (k, v, now),
            )
        conn.commit()
        conn.close()
        log.info("[tuya] credentials saved (region=%s)", region)
        return jsonify({"success": True, "valid": True, "uid": validation.get("uid", uid)})
    except Exception as e:
        log.error("[tuya] failed to save credentials: %s", e)
        return jsonify({"success": False, "error": f"failed to save: {str(e)}"}), 500


@axe_fleet_bp.route("/power-plugs/validate", methods=["POST"])
def validate_tuya_credentials():
    """Validate Tuya credentials without listing devices.
    Body (JSON, optional): override stored credentials.
    """
    from services.tuya_adapter import TuyaCloudAdapter

    data = request.get_json(silent=True) or {}
    creds = _get_tuya_credentials()
    # Allow override from request body
    if data.get("access_id"):
        creds["access_id"] = data["access_id"]
    if data.get("access_secret"):
        creds["access_secret"] = data["access_secret"]
    if data.get("region"):
        creds["region"] = data["region"]

    if not creds.get("access_id") or not creds.get("access_secret"):
        return jsonify({"valid": False, "error": "missing credentials"})

    adapter = TuyaCloudAdapter()
    result = adapter.validate_credentials(**creds)
    return jsonify(result)


@axe_fleet_bp.route("/power-plugs/<plug_id>/on", methods=["POST"])
@_require_local_or_session
def power_plug_on(plug_id: str):
    """Turn a Tuya smart plug ON."""
    return _execute_plug_command(plug_id, "power_on")


@axe_fleet_bp.route("/power-plugs/<plug_id>/off", methods=["POST"])
@_require_local_or_session
def power_plug_off(plug_id: str):
    """Turn a Tuya smart plug OFF."""
    return _execute_plug_command(plug_id, "power_off")


@axe_fleet_bp.route("/power-plugs/<plug_id>/toggle", methods=["POST"])
@_require_local_or_session
def power_plug_toggle(plug_id: str):
    """Toggle a Tuya smart plug ON/OFF."""
    return _execute_plug_command(plug_id, "toggle")


@axe_fleet_bp.route("/power-plugs/<plug_id>/status", methods=["GET"])
def power_plug_status(plug_id: str):
    """Get current status of a specific Tuya plug."""
    from services.tuya_adapter import TuyaCloudAdapter

    creds = _get_tuya_credentials()
    if not creds.get("access_id") or not creds.get("access_secret"):
        return jsonify({"success": False, "error": "Tuya credentials not configured"})

    adapter = TuyaCloudAdapter()
    result = adapter.get_status(plug_id, **creds)
    return jsonify(result)


# Background power-cycle task store
_power_cycle_tasks: dict = {}
_power_cycle_lock = threading.Lock()


@axe_fleet_bp.route("/miners/<device_id>/power-cycle", methods=["POST"])
@_require_local_or_session
def miner_power_cycle(device_id: str):
    """Power-cycle a miner: turn plug OFF, wait, turn ON.
    Runs asynchronously in a background thread so the request returns
    immediately. Poll /power-cycle/status/<task_id> for progress.

    Requires:
      - Miner must be registered in Axe Fleet
      - A Tuya smart plug must be associated with this miner

    Body (JSON):
      - plug_id (str, required): Tuya plug to cycle
      - off_seconds (int, optional): seconds to stay off, default 10
      - confirm (bool, required): must be true — safety confirmation
    """
    from services.tuya_adapter import TuyaCloudAdapter

    data = request.get_json(silent=True) or {}
    plug_id = data.get("plug_id", "")
    off_seconds = max(5, min(60, int(data.get("off_seconds", 10))))
    confirmed = data.get("confirm", False)

    if not plug_id:
        return jsonify({"success": False, "error": "plug_id is required"})
    if not confirmed:
        return jsonify({"success": False, "error": "power-cycle requires confirmation (confirm: true)"})

    if _registry:
        device = _registry.get_device(device_id, tenant_id=_get_tenant_id())
        if not device:
            return jsonify({"success": False, "error": "miner not found"})

    creds = _get_tuya_credentials()
    if not creds.get("access_id") or not creds.get("access_secret"):
        return jsonify({"success": False, "error": "Tuya credentials not configured"})

    # Create async task
    task_id = uuid.uuid4().hex[:12]
    task = {
        "id": task_id,
        "device_id": device_id,
        "plug_id": plug_id,
        "status": "pending",
        "steps": [],
        "error": None,
        "created_at": int(time.time()),
    }
    with _power_cycle_lock:
        _power_cycle_tasks[task_id] = task

    def _run():
        from services.tuya_adapter import TuyaCloudAdapter as _TCA
        _adapter = _TCA()
        try:
            # Step 1: OFF
            task["status"] = "turning_off"
            off_r = _adapter.power_off(plug_id, **creds)
            if not off_r.get("success"):
                task["status"] = "failed"
                task["error"] = f"power-off failed: {off_r.get('error')}"
                _audit_power_action(device_id, "power_cycle", False, task["error"])
                return
            task["steps"].append("off")
            log.info("[power-cycle] %s → OFF (task %s)", device_id, task_id)

            # Step 2: Wait
            task["status"] = "waiting"
            log.info("[power-cycle] waiting %ds (task %s)", off_seconds, task_id)
            time.sleep(off_seconds)

            # Step 3: ON
            task["status"] = "turning_on"
            on_r = _adapter.power_on(plug_id, **creds)
            if not on_r.get("success"):
                task["status"] = "failed"
                task["error"] = f"power-on failed: {on_r.get('error')}"
                _audit_power_action(device_id, "power_cycle", False, task["error"])
                return
            task["steps"].append("on")
            log.info("[power-cycle] %s → ON (task %s)", device_id, task_id)

            task["status"] = "completed"
            _audit_power_action(device_id, "power_cycle", True,
                                f"cycled via plug {plug_id} ({off_seconds}s off)")
        except Exception as e:
            task["status"] = "failed"
            task["error"] = str(e)
            log.error("[power-cycle] task %s exception: %s", task_id, e)

    t = threading.Thread(target=_run, daemon=True, name=f"pwr-cycle-{task_id}")
    t.start()

    return jsonify({
        "success": True,
        "task_id": task_id,
        "status": "pending",
        "message": f"Power-cycle started. Poll /api/axe-fleet/power-cycle/status/{task_id}",
    })


@axe_fleet_bp.route("/power-cycle/status/<task_id>", methods=["GET"])
def power_cycle_status(task_id: str):
    """Get the status of an async power-cycle task."""
    with _power_cycle_lock:
        task = _power_cycle_tasks.get(task_id)
    if not task:
        return jsonify({"success": False, "error": "task not found"}), 404
    return jsonify({"success": True, "task": task})


# ── Audit helpers ──────────────────────────────────────────────────────────


def _audit_power_action(device_id: str, action: str, success: bool, detail: str = ""):
    """Log a power action to the alerts/audit trail."""
    try:
        conn = _get_db_internal()
        c = conn.cursor()
        c.execute(
            "INSERT INTO alert_history (ts, alert_type, device_id, severity, action_taken) "
            "VALUES (?, ?, ?, ?, ?)",
            (int(time.time()), "power_action", device_id,
             "INFO" if success else "WARN",
             f"[{action}] {'OK' if success else 'FAIL'}: {detail}"),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("[audit] power action log error: %s", e)


# DB path — same as app.py's DB_PATH, but with a local default
_AXE_DB_PATH = os.environ.get("DB_PATH", "data/war_room.sqlite")


def _get_db_internal():
    """Get a fresh SQLite connection for internal audit logging.
    Uses the same DB_PATH as the main app (from env or default)."""
    conn = sqlite3.connect(_AXE_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _execute_plug_command(plug_id: str, method: str) -> tuple:
    """Execute a power plug command with consistent error handling."""
    from services.tuya_adapter import TuyaCloudAdapter

    creds = _get_tuya_credentials()
    if not creds.get("access_id") or not creds.get("access_secret"):
        return jsonify({"success": False, "error": "Tuya credentials not configured"}), 200

    adapter = TuyaCloudAdapter()
    fn = getattr(adapter, method, None)
    if not fn:
        return jsonify({"success": False, "error": f"unknown method: {method}"}), 400

    result = fn(plug_id, **creds)
    if result.get("success"):
        _audit_power_action(plug_id, method.replace("_", " "), True)
    return jsonify(result)


# ── Onboarding ────────────────────────────────────────────────────────────


@axe_fleet_bp.route("/remote/onboarding", methods=["GET"])
def remote_onboarding():
    """Return a structured onboarding checklist for remote access setup.
    Returns JSON with steps, status, and instructions.
    """
    from services.tailscale_adapter import get_local_status

    ts = get_local_status()

    steps = [
        {
            "id": "tailscale_install",
            "label": "Install Tailscale",
            "done": ts["tailscale_installed"],
            "instructions": "Install Tailscale on your host machine: https://tailscale.com/download",
        },
        {
            "id": "tailscale_login",
            "label": "Log in to Tailscale",
            "done": ts["connected"],
            "instructions": "Run 'tailscale up' and authenticate with your Tailscale account",
        },
        {
            "id": "tailnet_connect",
            "label": "Connect devices to same tailnet",
            "done": ts["connected"],
            "instructions": f"Install Tailscale on your phone/laptop and log in with the same account. Your host IP is: {ts['ip'] or 'N/A'}",
        },
        {
            "id": "dashboard_reachable",
            "label": "Dashboard reachable via tailnet",
            "done": False,
            "instructions": f"Open http://{ts['ip']}:8765 from your phone/laptop to verify remote access" if ts["ip"] else "Connect Tailscale first",
        },
        {
            "id": "tuya_configured",
            "label": "Tuya smart plugs configured",
            "done": bool(_get_tuya_credentials().get("access_id")),
            "instructions": "Add Tuya Cloud credentials (Access ID, Secret, Region) via Settings or .env file",
        },
    ]

    # Update step 4 status
    if ts["ip"]:
        from services.tailscale_adapter import diagnose_connection
        diag = diagnose_connection(ts["ip"], timeout=3)
        steps[3]["done"] = diag["reachable"]
        if steps[3]["done"]:
            steps[3]["instructions"] = "Dashboard is reachable via tailnet ✓"

    all_done = all(s["done"] for s in steps)

    return jsonify({
        "onboarding_complete": all_done,
        "progress": f"{sum(1 for s in steps if s['done'])}/{len(steps)}",
        "steps": steps,
        "remote_ip": ts.get("ip"),
        "remote_hostname": ts.get("hostname"),
    })


# ── Helpers ─────────────────────────────────────────────────────────────


def _execute_device_command(device_id: str, command: str):
    """Execute a command on a device. Shared by restart/identify endpoints."""
    device = _registry.get_device(device_id, tenant_id=_get_tenant_id())
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
@require_tenant
def fleet_health(tenant_id: str = ""):
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
    devices = _registry.list_devices(tenant_id=tenant_id)
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
        tel_raw = _registry.get_recent_telemetry(did, limit=1, tenant_id=tenant_id)
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


def _health_label(score: int) -> str:
    """Convert a health score (0-100) to a human-readable label."""
    if score >= 90:
        return "excellent"
    if score >= 70:
        return "good"
    if score >= 50:
        return "fair"
    if score >= 25:
        return "poor"
    return "critical"


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
