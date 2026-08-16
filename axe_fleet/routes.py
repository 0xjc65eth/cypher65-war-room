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
import socket
import sqlite3
import threading
import time
import uuid
from functools import wraps

from flask import Blueprint, jsonify, request, session, send_file

from services.tenant import (
    get_tenant_id as _get_tenant_id,
    require_tenant,
    role_required as _role_required,
    can_add_worker as _can_add_worker,
    get_tenant_plan as _get_tenant_plan,
    log_audit as _log_audit,
)

from core.models.device import device_status_is_online

from .connector import AxeOSConnector, AxeOSConnectorError
from .models import infer_capabilities, STATUS_PAUSED, derive_device_status
from .registry import DeviceRegistry

log = logging.getLogger("cypher65.axe.routes")

# Registry is injected by app.py after creation
_registry = None


def init_routes(registry: DeviceRegistry):
    """Inject the DeviceRegistry instance. Called from app.py."""
    global _registry
    _registry = registry


axe_fleet_bp = Blueprint("axe_fleet", __name__)


# ── Telemetry trust helpers (FLEET audit hardening) ─────────────────────
# Legacy rows written before the poll fix may be bare {"device_id": ...}
# stubs. Only payloads containing hashrate_hs are trusted; anything else is
# treated as empty so the UI never shows zeroed fake data.


def _is_trusted_payload(payload) -> bool:
    """True only for well-formed telemetry dicts (must contain hashrate_hs)."""
    return isinstance(payload, dict) and "hashrate_hs" in payload


def _caps_supported_commands(caps) -> list:
    """Flatten a capabilities dict into the supported-command ARRAY shape
    every consumer expects (fleet_health, fleet_summary, the FLEET COMMAND
    CENTER's buildCommandCenterRows — all render command buttons off this
    list). A raw dict fails Array.isArray() in the JS and drops the device
    into READ-ONLY; a list passes through (older serializers); junk → []
    (the honest 'no commands' state)."""
    if isinstance(caps, dict):
        return [k for k, v in caps.items() if v]
    if isinstance(caps, list):
        return [c for c in caps if isinstance(c, str)]
    return []


def _latest_telemetry(tel_raw) -> dict:
    """Return the latest trusted telemetry payload from a
    get_recent_telemetry(limit=1) result, or {} if none/untrusted."""
    if (
        tel_raw
        and isinstance(tel_raw[0], dict)
        and _is_trusted_payload(tel_raw[0].get("payload"))
    ):
        return tel_raw[0]["payload"]
    return {}


def _mark_cache_status(device_id: str, status: str) -> None:
    """Flip the snapshot-cache entry status so the Fleet card reflects a
    command immediately (Issue #13 — no wait for the next poll). Best-effort:
    the poll loop remains the source of truth and confirms on the next cycle."""
    try:
        import services.state as _shared_state

        entry = _shared_state.axe_telemetry_cache.get(device_id)
        if isinstance(entry, dict):
            entry = dict(entry)
            entry["status"] = status
            _shared_state.axe_telemetry_cache[device_id] = entry
    except Exception:
        pass


# Per-IP latency probe cache (FLEET audit). Probing every reachable device
# synchronously per /health call would block the endpoint for large fleets
# (N × timeout worst case). A short TTL keeps PING fresh while capping the
# probe cost to one pass per IP per window.
_latency_cache: dict = {}
_latency_cache_lock = threading.Lock()
_LATENCY_TTL = 30  # seconds
# Long-running servers could otherwise grow one entry per unique IP forever
# (a NAT/scan re-assigning IPs, churned device list, etc.). The cap is
# enforced with TTL-first eviction: expired entries (older than the TTL) are
# swept before the cap applies, and only if the cache is STILL over the cap
# are the oldest fresh entries dropped (FIFO by probe timestamp). A full
# clear is never used, so live miner PINGs survive a burst of new IPs.
_LATENCY_CACHE_MAX = 500


def _cache_latency_ms(ip: str, elapsed: int) -> None:
    """Store a successful probe in the latency cache under lock.

    Enforces _LATENCY_CACHE_MAX with TTL-first eviction: entries older than
    _LATENCY_TTL are removed first (fresh entries preserved), then — only if
    the cache is still over the cap — the oldest entries by probe timestamp
    are dropped (FIFO). Never a full clear. Never raises: the probe is
    best-effort and must stay on the hot path of /health.
    """
    try:
        with _latency_cache_lock:
            now = time.time()
            # 1) TTL sweep: drop stale entries, keep fresh ones.
            stale = [
                k
                for k, v in _latency_cache.items()
                if now - v.get("ts", 0) >= _LATENCY_TTL
            ]
            for k in stale:
                del _latency_cache[k]
            # 2) Cap fallback: evict the oldest fresh entries (FIFO by ts)
            #    until the new entry fits — never wipe the whole cache.
            over = len(_latency_cache) - _LATENCY_CACHE_MAX + 1
            if over > 0:
                oldest = sorted(
                    _latency_cache, key=lambda k: _latency_cache[k].get("ts", 0)
                )[:over]
                for k in oldest:
                    del _latency_cache[k]
            _latency_cache[ip] = {"ms": elapsed, "ts": now}
    except Exception:
        pass


def _probe_miner_latency_ms(ip: str = "", timeout: float = 0.75) -> int | None:
    """Measure reachability latency to a miner's HTTP API (port 80).

    Returns the TCP connect round-trip in milliseconds (cached for 30s per
    IP), or None when the probe fails/times out (never raises). The fleet
    card renders PING from this value; a dead device honestly reports '—'.
    """
    if not ip:
        return None
    now = time.time()
    try:
        with _latency_cache_lock:
            hit = _latency_cache.get(ip)
            if hit and now - hit["ts"] < _LATENCY_TTL:
                return hit["ms"]
    except Exception:
        pass
    try:
        t0 = now
        with socket.create_connection((ip, 80), timeout=timeout):
            # round() not int() — float deltas like 44.999…ms are 45ms.
            elapsed = round((time.time() - t0) * 1000)
    except OSError:
        elapsed = None  # socket.timeout subclasses OSError in py3.10+
    # Only cache SUCCESSFUL probes — a dead miner that recovers must be
    # detected on the next poll, and a cached None would keep the card at
    # '—' for up to the TTL. Failed probes are cheap anyway (fast refusal).
    if elapsed is not None:
        _cache_latency_ms(ip, elapsed)
    return elapsed


def _device_advice(status: str, tel: dict, latency_ms: int | None = None) -> list:
    """Rule-based per-device advice derived from telemetry.

    Returns a list of actionable recommendations (empty when the miner is
    healthy). Pure function — unit-testable without I/O.
    """
    advice = []
    # Normalize case like device_status_is_online — axe_fleet stores uppercase
    # STATUS_* today, but a lowercase status must not silently change advice.
    status = str(status or "").upper()
    # Non-reachable statuses short-circuit: a paused/errored miner isn't
    # broken-in-a-way-telemetry-can-explain, so don't emit misleading
    # "hashrate zero" advice. A missing status defaults to offline.
    if not status:
        advice.append("device offline — checar energia/rede")
        return advice
    if status in ("OFFLINE", "ERROR", "CRITICAL", "MAINTENANCE"):
        advice.append("device " + status.lower() + " — checar energia/rede")
        return advice
    if status == "PAUSED":
        advice.append("device pausado — miner não está hasheando")
        return advice

    temp = tel.get("temperature")
    if temp is not None and temp >= 80:
        advice.append("temp ≥80°C — melhorar ventilação ou reduzir overclock")
    chip = tel.get("chip_temp") or tel.get("temp_asic")
    if chip is not None and chip >= 85:
        advice.append("chip ≥85°C — considerar undervolt/reduzir freq")
    hw = tel.get("hw_error_pct")
    if hw is not None and hw >= 5:
        advice.append("HW errors ≥5% — reduzir frequência/voltagem")
    accepted = tel.get("shares_accepted") or 0
    stale = tel.get("shares_stale") or 0
    if accepted + stale > 0 and (stale / (accepted + stale)) > 0.01:
        advice.append("stale shares >1% — latência de rede, usar cabo/QoS no stratum")
    if latency_ms is not None and latency_ms > 150:
        advice.append("ping alto (>150ms) — usar Ethernet/QoS no stratum")
    rssi = tel.get("wifi_rssi")
    if rssi is not None and rssi <= -75:
        advice.append("Wi-Fi fraco (≤-75dBm) — usar cabo de rede")
    hr = int(tel.get("hashrate_hs") or 0)
    if hr == 0 and status in ("ONLINE", "WARNING", "HASHING"):
        advice.append("hashrate zero — checar conexão stratum/pool")
    return advice


# ── Device management ──────────────────────────────────────────────────


@axe_fleet_bp.route("/devices", methods=["GET"])
@require_tenant
@_role_required("viewer")
def list_devices(tenant_id: str = ""):
    """List all registered AxeOS devices with latest telemetry."""
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    devices = _registry.list_devices(tenant_id=tenant_id, with_telemetry=True)
    return jsonify({"devices": devices, "count": len(devices), "tenant_id": tenant_id})


@axe_fleet_bp.route("/devices", methods=["POST"])
@require_tenant
@_role_required("member")
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

    # Check if already registered (tenant-scoped — the same IP may exist in
    # another tenant's fleet and must not 409 this request). Runs BEFORE the
    # cloud guard so re-adding an existing device surfaces the 409 + device
    # (the operator may have registered it before this deployment change).
    existing = _registry.get_device_by_ip(ip, tenant_id=tenant_id)
    if existing:
        return jsonify({"error": "device already registered", "device": existing}), 409

    # ── SaaS topology guard: on a cloud deploy a private LAN IP is
    #    unreachable by construction — registering it would create a card
    #    that stays OFFLINE forever (the server poll can't reach it either),
    #    which users read as "a ferramenta não reconhece o device". Reject
    #    with the actionable path instead. Public-IP miners stay allowed
    #    (rare but reachable), and the wizard's diagnose gate still applies
    #    for non-cloud self-hosters.
    from config import is_cloud_deploy
    from .scanner import is_private_ip

    if is_cloud_deploy() and is_private_ip(ip):
        _log_audit(
            tenant_id,
            "fleet.device_add_blocked",
            target=ip,
            details={"reason": "cloud_private_ip_unreachable"},
        )
        return (
            jsonify(
                {
                    "success": False,
                    "is_cloud": True,
                    "error": "private LAN IP unreachable from cloud deploy",
                    "message": "IP privado (LAN) inalcançável a partir da nuvem. Instale o AGENTE LOCAL (Fleet → CONNECT AGENT): ele roda na sua rede, descobre os miners e conecta para fora — é a única via que funciona no SaaS.",
                }
            ),
            403,
        )

    # ── Fase 4 · B3: plan enforcement — the FREE tier caps workers per
    #    tenant. Honest rejection: the operator sees the limit and usage
    #    instead of a silent success that exceeds the plan.
    if not _can_add_worker(tenant_id):
        plan = _get_tenant_plan(tenant_id)
        _log_audit(
            tenant_id,
            "fleet.device_add_blocked",
            target=ip,
            details={"reason": "plan_worker_limit", "max_workers": plan["max_workers"]},
        )
        return (
            jsonify(
                {
                    "success": False,
                    "error": "plan worker limit reached",
                    "message": f"O plano {plan['plan']} permite no máximo {plan['max_workers']} workers. Remova um device ou aumente o limite.",
                    "plan": plan["plan"],
                    "max_workers": plan["max_workers"],
                }
            ),
            403,
        )

    # ── Auto-detect firmware (best-effort, never blocks registration) ──
    firmware = ""
    model = ""
    version = ""
    status = "OFFLINE"
    try:
        from core.registry.detector import detect_firmware

        fw = detect_firmware(ip)
        if fw and fw.get("reachable"):
            firmware = fw.get("firmware", "")
            model = fw.get("model", "")
            version = fw.get("version", "")
            status = "ONLINE" if fw.get("adapter_type") else "OFFLINE"
    except Exception:
        pass  # probe failure must never prevent registration

    try:
        device = _registry.add_device(ip, name or ip, tenant_id=tenant_id)
        # Enrich with auto-detected metadata when available
        if firmware or model:
            try:
                _registry.update_device(
                    device["id"],
                    {
                        "firmware": firmware,
                        "model": model or device.get("model", ""),
                        "firmware_version": version,
                        "status": status,
                    },
                )
                # Re-fetch so the response carries the enriched fields
                enriched = _registry.get_device(device["id"], tenant_id=tenant_id)
                if enriched:
                    device = enriched
            except Exception:
                pass  # enrichment is best-effort; base device is still valid

        _log_audit(
            tenant_id,
            "fleet.device_added",
            target=device.get("id", ""),
            details={
                "ip": ip,
                "name": name or ip,
                "detected_firmware": firmware or "none",
            },
        )
        return jsonify({"success": True, "device": device}), 201
    except Exception as e:
        log.error("[axe] add_device error: %s", e)
        return jsonify({"error": f"failed to add device: {str(e)}"}), 500


@axe_fleet_bp.route("/devices/<device_id>", methods=["DELETE"])
@require_tenant
@_role_required("member")
def remove_device(device_id: str, tenant_id: str = ""):
    """Remove a device from the registry."""
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    removed = _registry.remove_device(device_id, tenant_id=tenant_id)
    if not removed:
        return jsonify({"error": "device not found"}), 404
    _log_audit(tenant_id, "fleet.device_removed", target=device_id)
    return jsonify({"success": True})


@axe_fleet_bp.route("/devices/<device_id>", methods=["GET"])
@require_tenant
@_role_required("viewer")
def get_device(device_id: str, tenant_id: str = ""):
    """Get device details with recent telemetry."""
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    device = _registry.get_device(device_id, tenant_id=tenant_id)
    if not device:
        return jsonify({"error": "device not found"}), 404

    telemetry = _registry.get_recent_telemetry(device_id, limit=60, tenant_id=tenant_id)
    latest = _latest_telemetry(telemetry) or None

    return jsonify(
        {
            "device": device,
            "latest_telemetry": latest,
            "telemetry_count": len(telemetry),
        }
    )


# ── Per-device telemetry endpoint ────────────────────────────────────────


@axe_fleet_bp.route("/devices/<device_id>/telemetry", methods=["GET"])
@require_tenant
@_role_required("viewer")
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
    telemetry = _registry.get_recent_telemetry(
        device_id, limit=limit, tenant_id=tenant_id
    )

    return jsonify(
        {
            "device": {
                "id": device["id"],
                "name": device["name"],
                "model": device["model"],
                "ip_address": device["ip_address"],
                "status": device["status"],
            },
            "telemetry": [
                {"ts": e["ts"], "payload": e["payload"]}
                for e in telemetry
                if _is_trusted_payload(e.get("payload"))
            ],
            "count": len(telemetry),
        }
    )


# ── Per-device chart data endpoint ───────────────────────────────────────


@axe_fleet_bp.route("/devices/<device_id>/chart-data", methods=["GET"])
@require_tenant
@_role_required("viewer")
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
    series = _registry.get_telemetry_chart_data(
        device_id, limit=limit, tenant_id=tenant_id
    )

    return jsonify(
        {
            "device_id": device_id,
            "device_name": device["name"],
            "series": series,
            "count": len(series["ts"]),
        }
    )


# ── Per-device health score endpoint ─────────────────────────────────────


@axe_fleet_bp.route("/devices/<device_id>/health", methods=["GET"])
@require_tenant
@_role_required("viewer")
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
    # Hardening: only well-formed payloads (must contain hashrate_hs) are
    # trusted. Legacy broken stubs {"device_id": ...} are treated as empty.
    tel = _latest_telemetry(tel_raw)
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

    return jsonify(
        {
            "device_id": device_id,
            "device_name": device["name"],
            "status": device.get("status", "OFFLINE"),
            "health_score": health_score,
            "health_label": _health_label(health_score),
            "active_issues": issues,
            "latest_telemetry": tel,
            "last_seen": device.get("last_seen", 0),
            "age_seconds": now - device.get("last_seen", now),
        }
    )


# ── Per-device history endpoint (Phase C) ─────────────────────────────


@axe_fleet_bp.route("/devices/<device_id>/history", methods=["GET"])
@require_tenant
@_role_required("viewer")
def device_history(device_id: str, tenant_id: str = ""):
    """Get device telemetry history for Chart.js consumption.

    Returns a proximity_history-style list of {ts, hashrate, temperature,
    efficiency_jth, fan_rpm, power_watts} points suitable for a multi-line
    Chart.js graph in the Device Detail panel.

    Query params:
      - limit (int, optional): max data points, default 120
    """
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    device = _registry.get_device(device_id, tenant_id=tenant_id)
    if not device:
        return jsonify({"error": "device not found"}), 404

    limit = request.args.get("limit", 120, type=int)

    # Reuse the existing chart-data series (same axe_telemetry source).
    series = _registry.get_telemetry_chart_data(
        device_id, limit=limit, tenant_id=tenant_id
    )

    # Build a proximity_history-style point list for the Chart.js consumer.
    history = []
    n = len(series["ts"])
    for i in range(n):
        hr = series["hashrate_hs"][i]
        # Efficiency: compute on-the-fly so the caller always gets a value
        # even when the firmware doesn't report it.
        eff = series["efficiency_jth"][i]
        if eff is None and hr and series["power_watts"][i]:
            try:
                eff = round(series["power_watts"][i] / (hr / 1e12), 2)
            except (TypeError, ZeroDivisionError):
                pass
        history.append(
            {
                "ts": series["ts"][i],
                "hashrate": hr,
                "hashrate_str": _fmt_hr(int(hr)) if hr else "—",
                "temperature": series["temperature"][i],
                "efficiency_jth": eff,
                "fan_rpm": series["fan_rpm"][i],
                "power_watts": series["power_watts"][i],
            }
        )

    return jsonify(
        {
            "device_id": device_id,
            "device_name": device["name"],
            "status": device.get("status", "OFFLINE"),
            "history": history,
            "count": len(history),
        }
    )


@axe_fleet_bp.route("/devices/<device_id>/refresh", methods=["POST"])
@require_tenant
@_role_required("member")
def refresh_device(device_id: str, tenant_id: str = ""):
    """Re-detect capabilities and refresh device info."""
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    device = _registry.get_device(device_id, tenant_id=tenant_id)
    if not device:
        return jsonify({"error": "device not found"}), 404

    try:
        conn = AxeOSConnector(device["ip_address"])
        info = conn.fetch_info()
        caps = conn.detect_capabilities()
        _registry.update_device(
            device_id,
            {
                "model": str(info.get("model", "")),
                "firmware": str(info.get("firmware", "")),
                "firmware_version": str(info.get("version", "")),
                "hostname": str(info.get("hostname", "")),
                "status": "ONLINE" if info.get("hashrate") else "IDLE",
                "capabilities": caps,
            },
        )
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

        # Validate credentials — NEVER trust a raw opaque header. A Bearer
        # token must decode/verify as a real JWT; an X-API-Key must resolve
        # to a configured tenant key (multi-tenant isolation preserved).
        from services.auth import verify_token, resolve_tenant_for_api_key

        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and verify_token(
            auth[7:], expected_type="access"
        ):
            return f(*args, **kwargs)
        api_key = request.headers.get("X-API-Key", "")
        if api_key and resolve_tenant_for_api_key(api_key) is not None:
            return f(*args, **kwargs)
        # Open self-host mode (no auth configured): fall back to the legacy
        # lenient header check so the documented tailnet/session flow keeps
        # working exactly as before — there is no auth to validate against.
        from services.tenant import auth_configured

        if not auth_configured():
            if len(auth) > 20 or (api_key and len(api_key) >= 16):
                return f(*args, **kwargs)

        log.warning("[axe] Unauthorized device control attempt from %s", remote)
        return (
            jsonify(
                {
                    "error": "authentication required — device control restricted to localhost or authenticated session"
                }
            ),
            401,
        )

    return wrapper


# ── Device commands ─────────────────────────────────────────────────────


@axe_fleet_bp.route("/devices/<device_id>/restart", methods=["POST"])
@_require_local_or_session
@_role_required("member")
def restart_device(device_id: str):
    """Restart a device. Requires restart capability."""
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    return _execute_device_command(device_id, "restart")


@axe_fleet_bp.route("/devices/<device_id>/identify", methods=["POST"])
@_require_local_or_session
@_role_required("member")
def identify_device(device_id: str):
    """Flash device LED/screen for identification."""
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    return _execute_device_command(device_id, "identify")


@axe_fleet_bp.route("/devices/<device_id>/pause", methods=["POST"])
@_require_local_or_session
@_role_required("member")
def pause_device(device_id: str):
    """Pause hashing on a device (ESP-Miner miningPause).

    Agent-managed devices route through the LOCAL agent command queue (the
    cloud can't reach the home LAN); direct devices hit the AxeOS HTTP API.
    """
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    return _execute_device_command(device_id, "pause")


@axe_fleet_bp.route("/devices/<device_id>/resume", methods=["POST"])
@_require_local_or_session
@_role_required("member")
def resume_device(device_id: str):
    """Resume hashing on a paused device (ESP-Miner miningResume)."""
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    return _execute_device_command(device_id, "resume")


@axe_fleet_bp.route("/devices/<device_id>/config", methods=["POST"])
@_require_local_or_session
@_role_required("member")
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
@_role_required("viewer")
def fleet_summary(tenant_id: str = ""):
    """Fleet-wide summary: total, online, offline, total hashrate, etc.

    Payload mirrors fleet_health: every device entry carries the same
    per-device advice/latency layer (latency_ms + advice) so consumers can
    swap endpoints without schema drift.
    """
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500
    devices = _registry.list_devices(tenant_id=tenant_id)
    total = len(devices)
    # Reachability via the shared helper (ONLINE/WARNING/HASHING). WARNING is
    # kept in its own bucket (mirrors fleet_health) — a degraded-but-reachable
    # miner must never be counted as offline.
    online = 0
    warning = 0
    for d in devices:
        status = d.get("status", "OFFLINE")
        if status == "WARNING":
            warning += 1
        elif device_status_is_online(status):
            online += 1
    offline = total - online - warning
    from .models import infer_health_score

    now = int(time.time())
    total_hr = 0
    enriched_devices = []
    for d in devices:
        tel = _registry.get_recent_telemetry(d["id"], limit=1, tenant_id=tenant_id)
        p = _latest_telemetry(tel)
        total_hr += int(p.get("hashrate_hs", 0))
        status = d.get("status", "OFFLINE")
        # Reachability latency (PING) — only probed for reachable statuses so
        # the endpoint never blocks on dead IPs (mirrors fleet_health).
        latency_ms = None
        # agent_managed devices live on the user's LAN — the cloud can NEVER
        # reach them, so a latency probe would block every /summary call with
        # a useless 0.75s TCP timeout per device. Skip it (PING renders '—').
        if device_status_is_online(status) and not int(d.get("agent_managed", 0) or 0):
            latency_ms = _probe_miner_latency_ms(d.get("ip_address", ""))
        advice = _device_advice(status, p, latency_ms)
        # Enrich device with latest telemetry metrics
        enriched = dict(d)
        # Capabilities as a supported-command ARRAY (shared helper with
        # fleet_health): the FLEET COMMAND CENTER renders the restart/
        # identify buttons off this list — a dict here would fail
        # Array.isArray() in the JS and drop every agent-managed device
        # into READ-ONLY.
        enriched["capabilities"] = _caps_supported_commands(d.get("capabilities"))
        enriched["latency_ms"] = latency_ms
        enriched["advice"] = advice
        enriched["_telemetry"] = {
            "hashrate_hs": p.get("hashrate_hs", 0),
            "hashrate_str": _fmt_hr(int(p.get("hashrate_hs", 0))),
            "temperature": p.get("temperature"),
            "fan_speed": p.get("fan_speed"),
            "fan_rpm": p.get("fan_rpm"),
            "power_watts": p.get("power_watts"),
            "efficiency_jth": p.get("efficiency_jth"),
            "shares_accepted": p.get("shares_accepted", 0),
            "shares_rejected": p.get("shares_rejected", 0),
            "shares_stale": p.get("shares_stale", 0),
            "uptime_seconds": p.get("uptime_seconds", 0),
            "uptime_str": _fmt_uptime(p.get("uptime_seconds", 0)),
            "best_diff": p.get("best_diff"),
            "hw_error_pct": p.get("hw_error_pct", 0),
            "voltage_mv": p.get("voltage_mv"),
            "frequency_mhz": p.get("frequency_mhz"),
            "wifi_rssi": p.get("wifi_rssi"),
            "free_heap": p.get("free_heap"),
            # Fase 5 parity with fleet_health: chip/ASIC/VR temps, hashrate
            # windows and pool passthrough — consumers can swap endpoints.
            "chip_temp": p.get("chip_temp"),
            "vr_temp": p.get("vr_temp"),
            "temp_asic": p.get("temp_asic"),
            "temp_vreg": p.get("temp_vreg"),
            "hashrate_1m": p.get("hashrate_1m"),
            "hashrate_10m": p.get("hashrate_10m"),
            "hashrate_1h": p.get("hashrate_1h"),
            "stratum_status": p.get("stratum_status", ""),
            "pool_url": p.get("pool_url", ""),
            "pool_user": p.get("pool_user", ""),
            # Worker-intelligence: current stratum diff target + last-share
            # timestamp (best-effort — None when the firmware doesn't expose
            # them; the LIVE MINING panel renders an honest '—').
            "pool_diff": p.get("pool_diff"),
            "last_share_ts": p.get("last_share_ts"),
            "ts": p.get("ts", now),
            "age_seconds": now - p.get("ts", now),
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

    return jsonify(
        {
            "total_devices": total,
            "online": online,
            "warning": warning,
            "offline": offline,
            "total_hashrate_hs": total_hr,
            "total_hashrate_str": _fmt_hr(total_hr),
            "devices": enriched_devices,
        }
    )


# ── Test / seed endpoint ──────────────────────────────────────────────


@axe_fleet_bp.route("/test-devices", methods=["POST"])
@require_tenant
@_role_required("member")
def seed_test_devices(tenant_id: str = ""):
    """Populate fleet with simulated AxeOS devices for testing.
    Creates 4 devices with realistic telemetry (hashrate, temp, fan, power,
    uptime, best diff) and capabilities (restart, identify, pause).

    GATED by DEBUG_MOCK (config.py): disabled in production so mock devices
    are never exposed via the public API. Set DEBUG_MOCK=1 for local dev.

    Tenant-scoped: seeded devices are persisted under the caller's tenant
    so they never pollute another tenant's fleet.

    Use DELETE /api/axe-fleet/devices/<id> to remove individual devices
    after testing.
    """
    if os.environ.get("DEBUG_MOCK") != "1":
        return (
            jsonify({"error": "test-devices endpoint disabled (set DEBUG_MOCK=1)"}),
            403,
        )
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500

    now = int(time.time())
    devices = _registry.list_devices(tenant_id=tenant_id)
    if len(devices) >= 4:
        return (
            jsonify(
                {
                    "error": "Fleet already has devices — remove them first or use individual IP add",
                    "device_count": len(devices),
                }
            ),
            409,
        )

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
            "manufacturer": (
                "Bitaxe"
                if "Bitaxe" in m["model"] or "NerdAxe" in m["model"]
                else "Bitmain"
            ),
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
            "tenant_id": tenant_id,
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
                "temperature": (
                    m["temperature"] + temp_variation
                    if m["temperature"] is not None
                    else None
                ),
                # Fase 5: chip/ASIC/VR temps + hashrate windows (matches the
                # app.py auto-seed) so SEED TEST cards show real values.
                "chip_temp": (
                    m["temperature"] + temp_variation + 8
                    if m["temperature"] is not None
                    else None
                ),
                "vr_temp": (
                    m["temperature"] + temp_variation + 5
                    if m["temperature"] is not None
                    else None
                ),
                "temp_asic": (
                    m["temperature"] + temp_variation + 8
                    if m["temperature"] is not None
                    else None
                ),
                "temp_vreg": (
                    m["temperature"] + temp_variation + 5
                    if m["temperature"] is not None
                    else None
                ),
                "hashrate_1m": int(hr_variation) if m["hashrate_hs"] > 0 else None,
                "hashrate_10m": int(hr_variation) if m["hashrate_hs"] > 0 else None,
                "hashrate_1h": int(m["hashrate_hs"]) if m["hashrate_hs"] > 0 else None,
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
                "stratum_status": (
                    "connected" if m["hashrate_hs"] > 0 else "disconnected"
                ),
            }
            _registry.save_telemetry(device_id, tel)

        created.append(device_dict)

    log.info("[axe] seeded %d test devices", len(created))
    return jsonify({"success": True, "devices": created, "count": len(created)}), 201


# ── LAN miner discovery (subnet scan) ────────────────────────────────────
# Background scan store: scan_id → {status, cidr, total, scanned, found, error,
# created_at, tenant_id}. Scans run in a daemon thread; the UI polls
# GET /scan/<id> for progress. Tenant-scoped: a scan started by one tenant is
# never readable by another (mirrors _power_cycle_tasks isolation).
_scans: dict = {}
_scans_lock = threading.Lock()
_SCANS_MAX = 20


def _gc_scans() -> None:
    """Evict scans when the store exceeds _SCANS_MAX (FIFO by age).

    Finished scans are evicted first; if the store is STILL over the cap
    (e.g. many concurrent scans still running), the oldest entries are
    dropped regardless of status so a flood of scan requests can never grow
    the store unboundedly.
    """
    if len(_scans) <= _SCANS_MAX:
        return
    # 1) Drop finished scans (oldest first).
    finished = [
        sid for sid, s in _scans.items() if s.get("status") in ("done", "error")
    ]
    finished.sort(key=lambda sid: _scans[sid].get("created_at", 0))
    for sid in finished[: len(_scans) - _SCANS_MAX]:
        _scans.pop(sid, None)
    # 2) Fallback: still over the cap → drop oldest regardless of status.
    if len(_scans) > _SCANS_MAX:
        overflow = len(_scans) - _SCANS_MAX
        oldest = sorted(_scans, key=lambda sid: _scans[sid].get("created_at", 0))[
            :overflow
        ]
        for sid in oldest:
            _scans.pop(sid, None)


@axe_fleet_bp.route("/scan/subnets", methods=["GET"])
@require_tenant
@_role_required("viewer")
def scan_suggest_subnets(tenant_id: str = ""):
    """Suggest local subnets to scan, derived from this host's interfaces.

    Also reports `is_cloud` so the UI can switch to the local-agent
    onboarding: on a cloud deploy, suggest_subnets() returns [] (the host's
    interfaces are the PaaS VPC, not the user's LAN) and scan/IP-add are
    impossible."""
    from config import is_cloud_deploy
    from .scanner import suggest_subnets

    try:
        subnets = suggest_subnets()
    except Exception as e:  # noqa: BLE001
        log.warning("[axe] suggest_subnets error: %s", e)
        subnets = []
    return jsonify({"subnets": subnets, "is_cloud": is_cloud_deploy()})


@axe_fleet_bp.route("/scan", methods=["POST"])
@require_tenant
@_role_required("member")
def start_scan(tenant_id: str = ""):
    """Start an asynchronous LAN scan for miners.
    JSON body: { "cidr": "192.168.1.0/24" }
    Returns { scan_id } immediately; poll GET /api/axe-fleet/scan/<id> for
    progress. The scan thread is daemonized and capped by scanner.MAX_HOSTS.
    """
    from .scanner import scan_subnet

    # ── SaaS topology guard: a cloud host (Render etc.) can NEVER reach the
    #    user's home LAN, so a subnet scan from here is guaranteed to find
    #    nothing — it would only burn the server on a 250-host probe fan-out.
    #    Block it and point the operator at the local agent instead.
    from config import is_cloud_deploy

    if is_cloud_deploy():
        return (
            jsonify(
                {
                    "success": False,
                    "is_cloud": True,
                    "error": "subnet scan unavailable on cloud deploy",
                    "message": "Este dashboard roda na nuvem e não alcança a sua LAN. Instale o AGENTE LOCAL (Fleet → CONNECT AGENT) — ele roda na sua rede, descobre os miners e conecta para fora.",
                }
            ),
            400,
        )

    data = request.get_json(silent=True) or {}
    cidr = (data.get("cidr") or "").strip()
    if not cidr:
        from .scanner import suggest_subnets

        try:
            suggested = suggest_subnets()
        except Exception:  # noqa: BLE001
            suggested = []
        cidr = suggested[0] if suggested else ""
    if not cidr:
        return jsonify({"error": "cidr is required — e.g. 192.168.1.0/24"}), 400

    # ── Anti-flood guard: one active scan per tenant. A LAN scan fans out up
    #    to 64 concurrent probes; without this cap, a member could spam POST
    #    /scan and saturate the network with parallel probe threads. The
    #    store cap alone only bounds memory, not thread/socket churn.
    #    Check + insert happen under ONE lock acquisition so two racing
    #    requests for the same tenant can never both pass the guard.
    scan_id = uuid.uuid4().hex[:12]
    now = int(time.time())
    with _scans_lock:
        for _sid, _s in _scans.items():
            if _s.get("tenant_id") == tenant_id and _s.get("status") == "running":
                return (
                    jsonify(
                        {
                            "error": "scan already running for this tenant",
                            "scan_id": _sid,
                        }
                    ),
                    409,
                )
        _scans[scan_id] = {
            "id": scan_id,
            "tenant_id": tenant_id,
            "cidr": cidr,
            "status": "running",
            "total": 0,
            "scanned": 0,
            "found": [],
            # Alive-vs-miner layer + private-LAN topology hint (scanner).
            "alive": 0,
            "alive_ips": [],
            "hint": None,
            "error": None,
            "created_at": now,
        }
        _gc_scans()
    # Local reference for the daemon thread's closures (the store dict itself
    # is the source of truth; mutations below are visible to readers).
    scan = _scans[scan_id]

    def _progress(scanned, total):
        scan["scanned"] = scanned
        scan["total"] = total

    def _run():
        try:
            result = scan_subnet(cidr, progress_cb=_progress)
            scan["total"] = result.get("total", scan.get("total", 0))
            scan["scanned"] = result.get("total", 0)
            scan["found"] = result.get("found", [])
            scan["alive"] = result.get("alive", 0)
            scan["alive_ips"] = result.get("alive_ips", [])
            scan["hint"] = result.get("hint")
            scan["error"] = result.get("error")
            scan["status"] = "done" if not result.get("error") else "error"
            log.info(
                "[axe] scan %s (%s) done: %d/%d found",
                scan_id,
                cidr,
                len(scan["found"]),
                scan["total"],
            )
        except Exception as e:  # noqa: BLE001
            scan["error"] = str(e)
            scan["status"] = "error"
            log.error("[axe] scan %s failed: %s", scan_id, e)

    t = threading.Thread(target=_run, daemon=True, name=f"axe-scan-{scan_id}")
    t.start()

    return (
        jsonify(
            {"success": True, "scan_id": scan_id, "cidr": cidr, "status": "running"}
        ),
        202,
    )


@axe_fleet_bp.route("/scan/<scan_id>", methods=["GET"])
@require_tenant
@_role_required("viewer")
def scan_status(scan_id: str, tenant_id: str = ""):
    """Poll progress/results of a scan. Tenant-scoped read."""
    with _scans_lock:
        scan = _scans.get(scan_id)
    if not scan or scan.get("tenant_id", "") != tenant_id:
        return jsonify({"error": "scan not found"}), 404
    return jsonify({"scan": scan})


# ── Connectivity diagnostic endpoint ─────────────────────────────────────


@axe_fleet_bp.route("/diagnose/<path:ip_or_host>", methods=["GET"])
@_require_local_or_session
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
    # NOTE: `port` is accepted for backward compatibility with the legacy
    # Bitaxe-only endpoint but is IGNORED — diagnose_host() always probes
    # AxeOS HTTP :80 and cgminer TCP :4028.
    port = request.args.get("port", 80, type=int)
    try:
        # Unified diagnosis: AxeOS HTTP (:80) + cgminer TCP (:4028) with
        # per-protocol flags so the onboarding wizard can render a
        # step-by-step connectivity report (DNS → Bitaxe → cgminer).
        from .scanner import diagnose_host as _diagnose_host

        result = _diagnose_host(ip_or_host)
        result["port"] = port
        return jsonify(result)
    except Exception as e:
        return jsonify(
            {
                "ip": ip_or_host,
                "port": port,
                "error": True,
                "error_type": "EXCEPTION",
                "error_detail": str(e),
                "reachable": False,
            }
        )


# ── Lightweight firmware detection endpoint ──────────────────────────────


@axe_fleet_bp.route("/detect/<path:ip_or_host>", methods=["GET"])
def detect_firmware_endpoint(ip_or_host: str):
    """Quick firmware detection via ``detect_firmware()``.

    Lighter than /diagnose — calls only the firmware detector (REST APIs +
    cgminer fingerprint), no TCP connectivity scan or per-protocol flags.
    Returns the raw detector result for fast firmware preview.

    This endpoint does NOT require auth (local-only for the wizard).
    The device does NOT need to be registered.

    Example:
      GET /api/axe-fleet/detect/192.168.1.200

    Returns:
      {
        "firmware": "braiins" | "axeos" | "cgminer" | "unknown",
        "adapter_type": "braiins" | "bitaxe" | "cgminer" | "unknown",
        "version": "...",
        "model": "...",
        "capabilities": {...},
        "reachable": bool
      }
    """
    try:
        from core.registry.detector import detect_firmware

        result = detect_firmware(ip_or_host)
        return jsonify(result)
    except Exception as e:
        return jsonify(
            {
                "firmware": "unknown",
                "adapter_type": "unknown",
                "version": "",
                "model": "",
                "capabilities": {},
                "reachable": False,
                "error": str(e),
            }
        )


# ── Remote Access (Tailscale) ──────────────────────────────────────────


@axe_fleet_bp.route("/remote/status", methods=["GET"])
@require_tenant
@_role_required("viewer")
def remote_status(tenant_id: str = ""):
    """Get Tailscale remote access status for the host.
    Checks local tailscale daemon and returns connection info.
    """
    from services.tailscale_adapter import get_local_status

    status = get_local_status()
    return jsonify({"remote_access": status})


@axe_fleet_bp.route("/remote/health", methods=["GET"])
@require_tenant
@_role_required("viewer")
def remote_health(tenant_id: str = ""):
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

    # Test reachability of registered devices (tenant-scoped — the remote
    # panel must never probe or expose another tenant's miners).
    if _registry:
        devices = _registry.list_devices(tenant_id=tenant_id)
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
@require_tenant
@_role_required("viewer")
def remote_devices(tenant_id: str = ""):
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
        for d in _registry.list_devices(tenant_id=tenant_id):
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
@require_tenant
@_role_required("member")
def remote_test_connection(tenant_id: str = ""):
    """Run a full remote connectivity test suite.
    Returns per-test results with pass/fail and timing.
    """
    from services.tailscale_adapter import get_local_status, diagnose_connection

    data = request.get_json(silent=True) or {}
    target_ip = data.get("target_ip", "")

    tests = []

    # Test 1: Local tailscale daemon
    ts = get_local_status()
    tests.append(
        {
            "name": "Tailscale daemon",
            "passed": ts["connected"],
            "detail": (
                f"IP: {ts['ip']}, Hostname: {ts['hostname']}"
                if ts["connected"]
                else ts.get("error", "not running")
            ),
        }
    )

    # Test 2: Host self-reachability
    if ts["ip"]:
        self_test = diagnose_connection(ts["ip"], timeout=5)
        tests.append(
            {
                "name": "Local dashboard reachability",
                "passed": self_test["reachable"],
                "detail": (
                    f"{self_test.get('elapsed_ms', 'N/A')}ms"
                    if self_test["reachable"]
                    else self_test.get("error", "unreachable")
                ),
            }
        )

    # Test 3: Target IP (optional, e.g. another tailnet device)
    if target_ip:
        target_test = diagnose_connection(target_ip, timeout=5)
        tests.append(
            {
                "name": f"Remote target {target_ip}",
                "passed": target_test["reachable"],
                "detail": (
                    f"{target_test.get('elapsed_ms', 'N/A')}ms"
                    if target_test["reachable"]
                    else target_test.get("error", "unreachable")
                ),
            }
        )

    # Test 4: Registered devices (tenant-scoped)
    if _registry:
        devices = _registry.list_devices(tenant_id=tenant_id)
        reachable_count = 0
        for d in devices:
            diag = diagnose_connection(d["ip_address"], timeout=3)
            if diag.get("reachable"):
                reachable_count += 1
        tests.append(
            {
                "name": f"Fleet devices ({len(devices)} total)",
                "passed": reachable_count == len(devices),
                "detail": f"{reachable_count}/{len(devices)} reachable",
            }
        )

    all_passed = all(t["passed"] for t in tests)
    return jsonify(
        {
            "success": all_passed,
            "overall": "passed" if all_passed else "failed",
            "tests": tests,
            "checked_at": int(time.time()),
        }
    )


# ── Power Plugs (Tuya Smart Plugs) ────────────────────────────────────────


def _get_tuya_credentials() -> dict:
    """Read Tuya credentials from settings DB or environment variables.
    Returns dict with keys: access_id, access_secret, region (or empty).
    """
    s = {}
    try:
        conn = _get_db_internal()
        cur = conn.cursor()
        for k in ("tuya_access_id", "tuya_access_secret", "tuya_region", "tuya_uid"):
            cur.execute("SELECT value FROM settings WHERE key=?", (k,))
            r = cur.fetchone()
            if r and r["value"]:
                s[k] = r["value"]
        conn.close()
    except Exception as e:
        log.warning("[tuya] failed to read settings from DB: %s", e)

    # Environment variables override DB
    s["access_id"] = os.environ.get("TUYA_ACCESS_ID", "") or s.get("tuya_access_id", "")
    s["access_secret"] = os.environ.get("TUYA_ACCESS_SECRET", "") or s.get(
        "tuya_access_secret", ""
    )
    s["region"] = os.environ.get("TUYA_REGION", "") or s.get("tuya_region", "us")
    s["uid"] = os.environ.get("TUYA_UID", "") or s.get("tuya_uid", "")
    return {
        "access_id": s.get("tuya_access_id", "")
        or os.environ.get("TUYA_ACCESS_ID", ""),
        "access_secret": s.get("tuya_access_secret", "")
        or os.environ.get("TUYA_ACCESS_SECRET", ""),
        "region": s.get("tuya_region", "") or os.environ.get("TUYA_REGION", "us"),
        "uid": s.get("tuya_uid", "") or os.environ.get("TUYA_UID", ""),
    }


@axe_fleet_bp.route("/power-plugs", methods=["GET"])
@require_tenant
@_role_required("viewer")
def list_power_plugs(tenant_id: str = ""):
    """List all Tuya smart plugs associated with the user account.
    Credentials from settings DB or environment variables.
    """
    from services.tuya_adapter import TuyaCloudAdapter

    creds = _get_tuya_credentials()
    if not creds.get("access_id") or not creds.get("access_secret"):
        return jsonify(
            {
                "plugs": [],
                "count": 0,
                "configured": False,
                "message": "Tuya credentials not configured. Add TUYA_ACCESS_ID and TUYA_ACCESS_SECRET in Settings.",
            }
        )

    adapter = TuyaCloudAdapter()
    devices = adapter.list_devices(**creds)
    return jsonify(
        {
            "plugs": devices,
            "count": len(devices),
            "configured": True,
        }
    )


@axe_fleet_bp.route("/power-plugs/save-credentials", methods=["POST"])
@_require_local_or_session
@_role_required("member")
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
        return (
            jsonify(
                {"success": False, "error": "access_id and access_secret are required"}
            ),
            400,
        )

    from services.tuya_adapter import TuyaCloudAdapter

    adapter = TuyaCloudAdapter()
    validation = adapter.validate_credentials(
        access_id=access_id, access_secret=access_secret, region=region
    )
    if not validation.get("valid"):
        return jsonify(
            {"success": False, "error": validation.get("error", "invalid credentials")}
        )

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
        return jsonify(
            {"success": True, "valid": True, "uid": validation.get("uid", uid)}
        )
    except Exception as e:
        log.error("[tuya] failed to save credentials: %s", e)
        return jsonify({"success": False, "error": f"failed to save: {str(e)}"}), 500


@axe_fleet_bp.route("/power-plugs/validate", methods=["POST"])
@_role_required("member")
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
@_role_required("member")
def power_plug_on(plug_id: str):
    """Turn a Tuya smart plug ON."""
    return _execute_plug_command(plug_id, "power_on")


@axe_fleet_bp.route("/power-plugs/<plug_id>/off", methods=["POST"])
@_require_local_or_session
@_role_required("member")
def power_plug_off(plug_id: str):
    """Turn a Tuya smart plug OFF."""
    return _execute_plug_command(plug_id, "power_off")


@axe_fleet_bp.route("/power-plugs/<plug_id>/toggle", methods=["POST"])
@_require_local_or_session
@_role_required("member")
def power_plug_toggle(plug_id: str):
    """Toggle a Tuya smart plug ON/OFF."""
    return _execute_plug_command(plug_id, "toggle")


@axe_fleet_bp.route("/power-plugs/<plug_id>/status", methods=["GET"])
@require_tenant
@_role_required("viewer")
def power_plug_status(plug_id: str, tenant_id: str = ""):
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
@_role_required("member")
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
        return jsonify(
            {
                "success": False,
                "error": "power-cycle requires confirmation (confirm: true)",
            }
        )

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
        "tenant_id": _get_tenant_id(),
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
            _audit_power_action(
                device_id,
                "power_cycle",
                True,
                f"cycled via plug {plug_id} ({off_seconds}s off)",
            )
        except Exception as e:
            task["status"] = "failed"
            task["error"] = str(e)
            log.error("[power-cycle] task %s exception: %s", task_id, e)

    t = threading.Thread(target=_run, daemon=True, name=f"pwr-cycle-{task_id}")
    t.start()

    return jsonify(
        {
            "success": True,
            "task_id": task_id,
            "status": "pending",
            "message": f"Power-cycle started. Poll /api/axe-fleet/power-cycle/status/{task_id}",
        }
    )


@axe_fleet_bp.route("/power-cycle/status/<task_id>", methods=["GET"])
@require_tenant
@_role_required("viewer")
def power_cycle_status(task_id: str, tenant_id: str = ""):
    """Get the status of an async power-cycle task."""
    with _power_cycle_lock:
        task = _power_cycle_tasks.get(task_id)
    # Tenant-scoped: another tenant's viewer must never read this task.
    if task and task.get("tenant_id", "") != tenant_id:
        task = None
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
            (
                int(time.time()),
                "power_action",
                device_id,
                "INFO" if success else "WARN",
                f"[{action}] {'OK' if success else 'FAIL'}: {detail}",
            ),
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
        return (
            jsonify({"success": False, "error": "Tuya credentials not configured"}),
            200,
        )

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
@require_tenant
@_role_required("viewer")
def remote_onboarding(tenant_id: str = ""):
    """Return a structured onboarding checklist for remote access setup.
    Returns JSON with steps, status, and instructions.
    """
    from services.tailscale_adapter import get_local_status

    ts = get_local_status()

    steps = [
        {
            "id": "tailscale_install",
            "label": "Instalar Tailscale no host",
            "done": ts["tailscale_installed"],
            "instructions": "Instale o Tailscale na máquina host: https://tailscale.com/download",
        },
        {
            "id": "tailscale_login",
            "label": "Fazer login no Tailscale",
            "done": ts["connected"],
            "instructions": "Rode 'tailscale up' e autentique com sua conta Tailscale",
        },
        {
            "id": "tailnet_connect",
            "label": "Conectar dispositivos ao mesmo tailnet",
            "done": ts["connected"],
            "instructions": f"Instale o Tailscale no celular/notebook e faça login com a mesma conta. IP do host: {ts['ip'] or 'N/A'}",
        },
        {
            "id": "dashboard_reachable",
            "label": "Dashboard acessível via tailnet",
            "done": False,
            "instructions": (
                f"Abra http://{ts['ip']}:8765 do celular/notebook para verificar o acesso remoto"
                if ts["ip"]
                else "Conecte o Tailscale primeiro"
            ),
        },
        {
            "id": "tuya_configured",
            "label": "Tomadas Tuya configuradas",
            "done": bool(_get_tuya_credentials().get("access_id")),
            "instructions": "Adicione as credenciais Tuya Cloud (Access ID, Secret, Region) em Settings ou no .env",
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

    # FLEET audit G3: what the user can actually DO remotely vs Tailscale's
    # constraints. Rendered by the REMOTE ACCESS panel so expectations are
    # set before the user wires everything up (honest scope, no surprises).
    # pt-BR — the whole dashboard UI is Portuguese, and G3's goal is an
    # explanatory tutorial the user actually reads.
    scope = [
        "Monitorar a frota, telemetria (temp/hashrate/ping) e alertas de qualquer lugar do tailnet",
        "Executar comandos nos devices (restart / identify / pause) e power-cycle via tomadas Tuya",
        "Alterar configurações do miner (frequência / voltagem) quando o firmware suportar",
        "Abrir o dashboard completo (Live Mining, Probability, Hash Market, AI Operator) remotamente",
    ]
    limitations = [
        "O Tailscale só alcança devices do seu tailnet — o host e seu celular/notebook precisam usar a mesma conta Tailscale",
        "Acesso remoto exige o host LIGADO e o Tailscale conectado (sem relay na nuvem para o próprio dashboard)",
        "Comandos nos devices exigem um JWT válido (login) ou sessão autenticada — estar no tailnet sozinho não libera comandos; IP público na internet não libera",
        "Os miners precisam estar alcançáveis pela rede do host (o Tailscale conecta o controle, não o firewall LAN de cada miner)",
        "Sem DNS/HTTPS público: o acesso é pelo IP do tailnet (ex.: http://100.x.x.x:8765), não por domínio",
        "Frotas grandes podem ter polling mais lento: os probes de latência são cacheados por IP (TTL 30s)",
    ]

    return jsonify(
        {
            "onboarding_complete": all_done,
            "progress": f"{sum(1 for s in steps if s['done'])}/{len(steps)}",
            "steps": steps,
            "remote_ip": ts.get("ip"),
            "remote_hostname": ts.get("hostname"),
            "scope": scope,
            "limitations": limitations,
        }
    )


# ── Helpers ─────────────────────────────────────────────────────────────


def _execute_device_command(device_id: str, command: str, tenant_id: str = None):
    """Execute a command on a device. Shared by restart/identify endpoints.

    SaaS agent model: when the device is agent_managed (polled by the user's
    LOCAL agent), the command cannot be executed from the cloud — it is
    ENQUEUED so the agent pulls and runs it on the home LAN.

    ``tenant_id`` (Issue #178): explicit tenant for BACKGROUND callers (the
    Auto-Pilot autonomous pass runs in the poll thread with NO request
    context — _get_tenant_id() would raise there). Falls back to the request
    tenant when None."""
    tid = tenant_id or _get_tenant_id()
    device = _registry.get_device(device_id, tenant_id=tid)
    if not device:
        return jsonify({"error": "device not found"}), 404

    caps = device.get("capabilities", {})
    if not caps.get(command):
        return jsonify({"error": f"'{command}' not supported by this device"}), 400

    # Agent-managed → route through the command queue (agent executes locally).
    if int(device.get("agent_managed", 0) or 0):
        queued = _registry.enqueue_agent_command(device_id, command, tenant_id=tid)
        if not queued:
            return jsonify({"error": "could not enqueue agent command"}), 500
        if command == "pause":
            # Issue #13: reflect the operator's intent immediately even when
            # the command runs on the home LAN — the agent's next telemetry
            # push (carrying mining_paused) confirms and self-heals any gap.
            _registry.update_device(device_id, {"status": STATUS_PAUSED}, tenant_id=tid)
            _mark_cache_status(device_id, STATUS_PAUSED)
        _log_audit(
            tid,
            "fleet.agent_command_queued",
            target=device_id,
            details={"command": command, "cmd_id": queued.get("id")},
        )
        return jsonify(
            {
                "success": True,
                "queued": True,
                "message": f"'{command}' enviado para o agente local executar",
                "command_id": queued.get("id"),
            }
        )

    try:
        conn = AxeOSConnector(device["ip_address"])
        tid = tenant_id or _get_tenant_id()
        if command == "restart":
            result = conn.restart()
        elif command == "identify":
            result = conn.identify()
        elif command == "pause":
            # ESP-Miner: POST /api/system/miningPause (empty body).
            result = conn.pause()
            # Issue #13: reflect PAUSED immediately — never wait for the next
            # poll. The DB row + snapshot cache flip together so the Fleet
            # card shows the truth the moment the command succeeds.
            _registry.update_device(device_id, {"status": STATUS_PAUSED}, tenant_id=tid)
            _mark_cache_status(device_id, STATUS_PAUSED)
        elif command == "resume":
            # ESP-Miner: POST /api/system/miningResume (empty body).
            result = conn.resume()
            # Re-poll right away: the device decides ONLINE/IDLE by its real
            # hashrate (a paused device only leaves PAUSED when it hashes).
            try:
                tel = conn.extract_telemetry()
            except AxeOSConnectorError:
                tel = {}
            if tel:
                new_st = derive_device_status(tel)
                _registry.update_device(device_id, {"status": new_st}, tenant_id=tid)
                _mark_cache_status(device_id, new_st)
        else:
            return jsonify({"error": f"unknown command: {command}"}), 400
        return jsonify({"success": True, "result": result})
    except AxeOSConnectorError as e:
        return jsonify({"error": str(e)}), 503


@axe_fleet_bp.route("/health", methods=["GET"])
@require_tenant
@_role_required("viewer")
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
        # Hardening: trust only well-formed telemetry payloads. Legacy rows
        # written before the poll fix may be a bare {"device_id": ...} stub —
        # treat those as empty so the UI never shows zeroed fake data.
        tel = _latest_telemetry(tel_raw)
        status = d.get("status", "OFFLINE")

        # Calculate health score
        health_score = infer_health_score(tel) if tel else 0

        # Aggregate. WARNING is intentionally its own bucket (the frontend
        # renders ONLINE/WARN/OFFLINE separately) — a degraded miner is not
        # offline. Everything else delegates to the shared reachability
        # helper (ONLINE/HASHING → online; OFFLINE/unknown → offline).
        if status == "WARNING":
            warning += 1
            groups["warning"].append(did)
        elif device_status_is_online(status):
            online += 1
            groups["online"].append(did)
        else:
            offline += 1
            groups["offline"].append(did)

        # Reachability latency (PING on the card) — only probed for
        # reachable statuses so the endpoint never blocks on dead IPs.
        latency_ms = None
        # Same SaaS guard as fleet_summary: agent_managed IPs are unreachable
        # from the cloud — probing them only burns 0.75s per device per
        # /health call. Skip (PING '—'), never mark them down because of it.
        if device_status_is_online(status) and not int(d.get("agent_managed", 0) or 0):
            latency_ms = _probe_miner_latency_ms(d.get("ip_address", ""))
        advice = _device_advice(status, tel, latency_ms)

        hr = int(tel.get("hashrate_hs", 0))
        pw = tel.get("power_watts")
        tmp = tel.get("temperature")
        bd = (
            parse_diff_to_float(tel.get("best_diff", ""))
            if tel.get("best_diff")
            else 0.0
        )

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

        # Capabilities — flattened to the supported-command array (shared
        # helper: fleet_summary must never drift from this shape again).
        supported_cmds = _caps_supported_commands(d.get("capabilities"))

        device_health_list.append(
            {
                "id": did,
                "name": d.get("name", ""),
                "model": d.get("model", ""),
                "manufacturer": d.get("manufacturer", ""),
                "firmware": d.get("firmware", ""),
                "firmware_version": d.get("firmware_version", ""),
                "ip_address": d.get("ip_address", ""),
                "hostname": d.get("hostname", ""),
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
                    "pool_diff": tel.get("pool_diff"),
                    "last_share_ts": tel.get("last_share_ts"),
                    "uptime_seconds": tel.get("uptime_seconds", 0),
                    "uptime_str": _fmt_uptime(tel.get("uptime_seconds", 0)),
                    "free_heap": tel.get("free_heap"),
                    "wifi_rssi": tel.get("wifi_rssi"),
                    "shares_accepted": tel.get("shares_accepted", 0),
                    "shares_rejected": tel.get("shares_rejected", 0),
                    "shares_stale": tel.get("shares_stale", 0),
                    "hw_error_pct": tel.get("hw_error_pct", 0.0),
                    "efficiency_jth": tel.get("efficiency_jth"),
                    # Fase 5: expose chip/ASIC/VR temps + hashrate windows the
                    # frontend cards render. Without these the cards always show
                    # NOT AVAILABLE even when the firmware reports real values.
                    "chip_temp": tel.get("chip_temp"),
                    "vr_temp": tel.get("vr_temp"),
                    "temp_asic": tel.get("temp_asic"),
                    "temp_vreg": tel.get("temp_vreg"),
                    "hashrate_1m": tel.get("hashrate_1m"),
                    "hashrate_10m": tel.get("hashrate_10m"),
                    "hashrate_1h": tel.get("hashrate_1h"),
                    "fan_speed": tel.get("fan_speed"),
                    "fan_rpm": tel.get("fan_rpm"),
                    "stratum_status": tel.get("stratum_status", ""),
                    "pool_url": tel.get("pool_url", ""),
                    "pool_user": tel.get("pool_user", ""),
                    "ts": tel.get("ts", now),
                    "age_seconds": now - tel.get("ts", now),
                },
                "latency_ms": latency_ms,
                "advice": advice,
                "last_seen": d.get("last_seen", 0),
            }
        )

    avg_temp = round(temp_sum / temp_count, 1) if temp_count > 0 else None
    avg_health = round(health_sum / health_count, 0) if health_count > 0 else 0
    efficiency_jth = (
        round(total_power_w / (total_hashrate_hs / 1e12), 2)
        if total_hashrate_hs > 0 and total_power_w > 0
        else None
    )

    return jsonify(
        {
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
        }
    )


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
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
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


# ══════════════════════════════════════════════════════════════════════════
# AGENT API — /api/agent/*  (SaaS: local agent → cloud dashboard)
# ══════════════════════════════════════════════════════════════════════════
# The user runs a LIGHTWEIGHT agent on their home LAN (Docker). The agent
# connects OUT to this cloud dashboard (no open ports needed — NAT/CGNAT
# safe) and:
#   • registers devices it discovers (scan ARP/subnet local)
#   • pushes telemetry in batches (every ~30s)
#   • pulls queued commands (restart/identify) and acks the result
# Auth: `Authorization: Bearer <agent-token>` — a long-lived JWT minted via
# POST /api/agent/token by a logged-in user, scoped to their tenant.
# The agent token is a JWT with the `agent: true` claim; tenant comes from
# `sub` (same as user tokens).

agent_bp = Blueprint("agent", __name__, url_prefix="/api/agent")

# Long-lived agent token: 1 year. The agent runs unattended on the home LAN;
# a short-lived token would break polling until the user re-generates it.
AGENT_TOKEN_TTL = 365 * 86400


def _require_agent(f):
    """Require a valid agent token (JWT with `agent: true` claim).
    Injects `agent_tenant_id` (the tenant that owns the agent) into kwargs."""

    @wraps(f)
    def wrapper(*args, **kwargs):
        from services.auth import verify_token

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "agent token required"}), 401
        payload = verify_token(auth_header[7:], expected_type="access")
        if not payload or not payload.get("agent"):
            return jsonify({"error": "invalid agent token"}), 401
        kwargs["agent_tenant_id"] = payload.get("sub") or "default"
        return f(*args, **kwargs)

    return wrapper


@agent_bp.route("/token", methods=["POST"])
@require_tenant
@_role_required("member")
def agent_issue_token(tenant_id: str = ""):
    """Mint a long-lived agent token for the caller's tenant.
    Requires a logged-in user (member+). Returns the JWT the user pastes
    into the agent's env (CYPHER65_AGENT_TOKEN)."""
    from services.auth import create_token

    tid = tenant_id or "default"
    token = create_token(
        subject=tid, ttl=AGENT_TOKEN_TTL, extra_claims={"agent": True, "role": "agent"}
    )
    _log_audit(tid, "agent.token_issued", details={"ttl_days": 365})
    return jsonify(
        {
            "success": True,
            "token": token,
            "tenant_id": tid,
            "expires_in": AGENT_TOKEN_TTL,
            "server_url": request.url_root.rstrip("/"),
            "usage": "CYPHER65_AGENT_TOKEN=<token> em Docker na sua LAN (o agente conecta para fora)",
        }
    )


@agent_bp.route("/register", methods=["POST"])
@_require_agent
def agent_register_devices(agent_tenant_id: str = ""):
    """Register devices discovered by the agent (upsert by IP+tenant).
    Body: {"devices": [{"ip": ..., "name": ..., "model": ...,
           "firmware": ..., "version": ..., "hostname": ...,
           "type": "bitaxe"|"cgminer", "mac": ...}, ...]}
    Returns the registered device dicts."""
    data = request.get_json(silent=True) or {}
    devices = data.get("devices") or []
    if not isinstance(devices, list) or not devices:
        return jsonify({"error": "devices array required"}), 400
    out = []
    blocked = []
    for d in devices:
        ip = (d.get("ip") or "").strip()
        if not ip:
            continue
        # Plan worker cap: only NEW devices consume a slot (an upsert refresh
        # of an already-registered device must never be rejected). Mirrors the
        # manual POST /devices gate — the agent path must not bypass the plan.
        existing = _registry.get_device_by_ip(ip, tenant_id=agent_tenant_id)
        if not existing and not _can_add_worker(agent_tenant_id):
            plan = _get_tenant_plan(agent_tenant_id)
            blocked.append(
                {
                    "ip": ip,
                    "error": "plan worker limit reached",
                    "max_workers": plan["max_workers"],
                    "plan": plan["plan"],
                }
            )
            _log_audit(
                agent_tenant_id,
                "agent.register_blocked",
                target=ip,
                details={"reason": "plan_worker_limit"},
            )
            continue
        dev = _registry.upsert_agent_device(
            ip,
            name=(d.get("name") or "").strip(),
            tenant_id=agent_tenant_id,
            info={
                "model": d.get("model"),
                "firmware": d.get("firmware"),
                "version": d.get("version"),
                "hostname": d.get("hostname"),
                "mac": d.get("mac"),
                "manufacturer": d.get("manufacturer"),
                # type drives capabilities (bitaxe restart/identify via :80;
                # cgminer restart via :4028, no identify).
                "type": d.get("type"),
            },
        )
        if not dev:
            # Tombstone: operator removed this IP — the agent must NOT
            # resurrect it. Report it as blocked so the agent drops it from
            # its poll set instead of 403-spamming telemetry forever.
            blocked.append({"ip": ip, "error": "device removed by operator"})
            _log_audit(
                agent_tenant_id,
                "agent.register_blocked",
                target=ip,
                details={"reason": "device_removed"},
            )
            continue
        out.append(dev)
    _log_audit(
        agent_tenant_id,
        "agent.register",
        details={"count": len(out), "blocked": len(blocked)},
    )
    return (
        jsonify(
            {
                "success": True,
                "registered": out,
                "count": len(out),
                "blocked": blocked,
                "blocked_count": len(blocked),
            }
        ),
        201,
    )


@agent_bp.route("/telemetry", methods=["POST"])
@_require_agent
def agent_telemetry(agent_tenant_id: str = ""):
    """Push telemetry for one device (agent polling result).
    Body: {"ip": ..., "telemetry": {...}} — telemetry uses the SAME
    normalized shape as the registry's extract_telemetry (hashrate_hs,
    temperature, fan_rpm, power_watts, best_diff, shares_*, ...)."""
    data = request.get_json(silent=True) or {}
    ip = (data.get("ip") or "").strip()
    tel = data.get("telemetry")
    # Require the explicit key: `telemetry: {}` (empty) is legal (a device
    # that answered nothing), but a MISSING key is a malformed push.
    if not ip or not isinstance(tel, dict):
        return jsonify({"error": "ip and telemetry object required"}), 400
    device = _registry.get_device_by_ip(ip, tenant_id=agent_tenant_id)
    if not device:
        # Agent reported a device it registered earlier but the row is gone
        # (e.g. server DB reset). Re-upsert with the telemetry as identity —
        # but respect the plan worker cap so the telemetry path can't bypass
        # the limit that register enforces.
        if not _can_add_worker(agent_tenant_id):
            plan = _get_tenant_plan(agent_tenant_id)
            _log_audit(
                agent_tenant_id,
                "agent.telemetry_blocked",
                target=ip,
                details={"reason": "plan_worker_limit"},
            )
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "plan worker limit reached",
                        "message": f"O plano {plan['plan']} permite no máximo {plan['max_workers']} workers. Remova um device ou aumente o limite.",
                        "plan": plan["plan"],
                        "max_workers": plan["max_workers"],
                    }
                ),
                403,
            )
        device = _registry.upsert_agent_device(
            ip, tenant_id=agent_tenant_id, info={"model": tel.get("model")}
        )
        if not device:
            # Tombstoned: the operator removed this device. Acknowledge
            # with 410 so the agent stops pushing it (it can never come
            # back via the agent path — only an explicit operator add).
            _log_audit(
                agent_tenant_id,
                "agent.telemetry_blocked",
                target=ip,
                details={"reason": "device_removed"},
            )
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "device removed by operator",
                        "removed": True,
                    }
                ),
                410,
            )
    _registry.save_agent_telemetry(device["id"], tel, tenant_id=agent_tenant_id)
    return jsonify(
        {
            "success": True,
            "device_id": device["id"],
            "status": derive_device_status(tel),
        }
    )


@agent_bp.route("/commands/pull", methods=["POST"])
@_require_agent
def agent_pull_commands(agent_tenant_id: str = ""):
    """Pull queued commands (restart/identify) for this tenant's devices.
    Returns [] when nothing is pending."""
    cmds = _registry.pending_agent_commands(tenant_id=agent_tenant_id)
    pulled = []
    for c in cmds:
        if _registry.mark_command_pulled(c["id"], tenant_id=agent_tenant_id):
            # Resolve the device's LAN IP server-side. The agent executes
            # commands on the HOME network — it needs the reachable IP, not
            # the registry UUID. (The command's device_id alone was useless:
            # the agent would try to open a TCP/HTTP socket to a UUID string.)
            dev = _registry.get_device(c["device_id"], tenant_id=agent_tenant_id)
            pulled.append(
                {
                    "id": c["id"],
                    "device_id": c["device_id"],
                    "ip_address": (dev or {}).get("ip_address", ""),
                    "command": c["command"],
                    "params": c.get("params", {}),
                }
            )
    return jsonify({"success": True, "commands": pulled})


@agent_bp.route("/commands/<command_id>/ack", methods=["POST"])
@_require_agent
def agent_ack_command(command_id: str, agent_tenant_id: str = ""):
    """Ack a command result after executing it locally.
    Body: {"success": bool, "result": str|dict}"""
    data = request.get_json(silent=True) or {}
    success = bool(data.get("success"))
    result = data.get("result") or ""
    if isinstance(result, (dict, list)):
        result = json.dumps(result)
    ok = _registry.ack_agent_command(
        command_id, agent_tenant_id, success=success, result=str(result)
    )
    return (
        jsonify({"success": ok})
        if ok
        else (jsonify({"error": "command not found"}), 404)
    )


# ── Agent assets: the 1-line installer + the stdlib-only agent.py ─────────
# The user's dashboard shows `curl -sSL <origin>/agent/install.sh | bash`.
# The installer downloads agent.py from here — both served from the repo's
# agent/ directory, public (no auth: they are scripts the user must be able
# to fetch from a machine OUTSIDE the dashboard session).

agent_assets_bp = Blueprint("agent_assets", __name__, url_prefix="/agent")

_AGENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent")


@agent_assets_bp.route("/install.sh", methods=["GET"])
def agent_install_script():
    """Serve the one-line installer (bash). Public — the whole point is a
    curl|bash from a machine on the user's LAN."""
    path = os.path.join(_AGENT_DIR, "install.sh")
    if not os.path.exists(path):
        return jsonify({"error": "installer not found"}), 404
    return send_file(path, mimetype="text/x-shellscript", max_age=300, conditional=True)


@agent_assets_bp.route("/agent.py", methods=["GET"])
def agent_script():
    """Serve the stdlib-only agent source the installer downloads. Public."""
    path = os.path.join(_AGENT_DIR, "agent.py")
    if not os.path.exists(path):
        return jsonify({"error": "agent script not found"}), 404
    return send_file(path, mimetype="text/x-python", max_age=300, conditional=True)
