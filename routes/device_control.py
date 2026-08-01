"""
CYPHER65 // Device Control — Unified Command Endpoint
=====================================================
POST /api/devices/<device_id>/command

Validates commands through SafetyEngine, dispatches to the correct adapter
(AxeOSConnector for Bitaxe/AxeOS, CgminerAdapter for cgminer-family),
and returns the execution result.

Read-only fallback: if a command is not supported by the firmware/adapter,
returns a clear error — never simulates execution.

Supports BOTH registry shapes:
  - core/registry/device_registry.CoreDeviceRegistry  → Device objects
  - axe_fleet/registry.DeviceRegistry                 → dicts
"""
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from flask import Blueprint, jsonify, request

from services.tenant import require_tenant

from core.adapters.bitaxe_adapter import BitaxeAdapter
from core.adapters.cgminer_adapter import CgminerAdapter
from core.models.device import Device, DeviceStatus
from core.safety.safety_engine import SafetyEngine

log = logging.getLogger("cypher65.device_control")

# ── Registry injected from app.py ──────────────────────────────────────
_registry = None
_safety: Optional[SafetyEngine] = None
_record_cb: Optional[Callable] = None  # app._record_command — audits every attempt


def init_device_control(registry, safety_engine: Optional[SafetyEngine] = None,
                        record_command: Optional[Callable] = None):
    """Inject DeviceRegistry and SafetyEngine. Called from app.py."""
    global _registry, _safety, _record_cb
    _registry = registry
    _safety = safety_engine or SafetyEngine()
    _record_cb = record_command


device_control_bp = Blueprint("device_control", __name__)


# ── Helpers: normalize core Device objects vs axe-fleet dicts ──────────

def _is_core_device(device: Any) -> bool:
    """True if the registry returned a core Device object (not a dict)."""
    return isinstance(device, Device)


def _fw_and_ip(device: Device, raw: Any) -> tuple:
    """Return (firmware, ip) from either a Device object or a registry dict."""
    if _is_core_device(raw):
        return (raw.firmware or ""), (raw.ip or "")
    return (raw.get("firmware") or ""), (raw.get("ip_address") or "")


def _capability_map(device: Device, raw: Any) -> Dict[str, bool]:
    """Build {capability_name: supported} from a Device object (List[Capability])
    or a registry dict (flags dict OR list of dicts)."""
    if _is_core_device(raw):
        caps = device.capabilities or []
        return {
            c.name: bool(c.supported)
            for c in caps if getattr(c, "name", None)
        }
    caps = raw.get("capabilities") or {}
    if isinstance(caps, dict):
        return {str(k): bool(v) for k, v in caps.items()}
    if isinstance(caps, list):
        out = {}
        for c in caps:
            if isinstance(c, dict):
                out[str(c.get("name", ""))] = bool(c.get("supported", False))
            elif getattr(c, "name", None):
                out[c.name] = bool(c.supported)
        return out
    return {}


# ── Helper: convert registry entry → core Device object ─────────────────
def _dict_to_device(d: Any) -> Device:
    """Return a core Device from either a Device object or a registry dict."""
    if _is_core_device(d):
        return d
    status_map = {
        "ONLINE": DeviceStatus.ONLINE,
        "HASHING": DeviceStatus.ONLINE,
        "IDLE": DeviceStatus.ONLINE,
        "WARNING": DeviceStatus.WARNING,
        "OFFLINE": DeviceStatus.OFFLINE,
        "CRITICAL": DeviceStatus.CRITICAL,
        "ERROR": DeviceStatus.CRITICAL,
    }
    device = Device(
        id=d.get("id", ""),
        name=d.get("name", ""),
        model=d.get("model", ""),
        firmware=d.get("firmware", ""),
        ip=d.get("ip_address"),
        hostname=d.get("hostname"),
        status=status_map.get(d.get("status", "OFFLINE"), DeviceStatus.OFFLINE),
    )
    # Attach telemetry snapshot if the registry supports it
    tel = d.get("current_telemetry")
    if isinstance(tel, dict):
        device.current_telemetry = tel
    elif _registry and hasattr(_registry, "get_recent_telemetry"):
        try:
            tel_raw = _registry.get_recent_telemetry(d["id"], limit=1)
            if tel_raw:
                device.current_telemetry = tel_raw[0].get("payload", {})
        except Exception as e:  # defensive — telemetry is best-effort
            log.debug("[device_control] telemetry attach failed: %s", e)
    return device


# ── Helper: build adapter based on firmware ────────────────────────────
def _build_adapter(raw: Any, device: Device):
    """Build the appropriate adapter for this device's firmware.
    Returns None if firmware is unknown/unsupported (read-only)."""
    firmware, ip = _fw_and_ip(device, raw)
    firmware = firmware.lower()

    if "axeos" in firmware or "bitaxe" in firmware or "esp-miner" in firmware:
        return BitaxeAdapter(device, api_url=f"http://{ip}")
    if ip:
        # Try cgminer adapter for Antminer, Whatsminer, Braiins OS, etc.
        return CgminerAdapter(device, host=ip)

    log.warning("[device_control] unknown firmware for %s: %s", device.id, firmware)
    return None


# ── Known commands with metadata ───────────────────────────────────────
COMMAND_META = {
    "restart": {
        "label": "Restart",
        "requires_confirmation": True,
        "risk_level": "medium",
        "description": "Reboot the miner (goes offline for ~30s)",
    },
    "identify": {
        "label": "Identify",
        "requires_confirmation": False,
        "risk_level": "low",
        "description": "Flash LED/screen to locate the device",
    },
    "pause": {
        "label": "Pause",
        "requires_confirmation": True,
        "risk_level": "medium",
        "description": "Pause mining temporarily (AxeOS 2.4+)",
    },
    "resume": {
        "label": "Resume",
        "requires_confirmation": False,
        "risk_level": "low",
        "description": "Resume mining after pause",
    },
}


def _record_attempt(device_id: str, command: str, parameters: Dict[str, Any],
                    result: Dict[str, Any]):
    """Audit a command attempt (blocked or executed) through app._record_command."""
    if _record_cb is None:
        return
    try:
        _record_cb(device_id, command, parameters, result)
    except Exception as e:
        log.warning("[device_control] record_command callback failed: %s", e)


@device_control_bp.route("/api/devices/<device_id>/command", methods=["POST"])
@require_tenant
def execute_device_command(device_id: str, tenant_id: str = ""):
    """Execute a command on a device (scoped to the request tenant).

    JSON body:
      { "command": "restart|identify|pause|resume", "parameters": {} }

    Flow:
      1. Lookup device in registry (scoped by tenant)
      2. Check if command is supported via capabilities
      3. Validate through SafetyEngine (blocked → 403, audited)
      4. Execute via adapter (record result)
      5. Record restart cooldown if applicable
      6. Return result

    Returns 400 if command not supported / validation fails.
    Returns 403 if blocked by the SafetyEngine.
    Returns 503 if device unreachable.
    Returns 200 on success.
    """
    if _registry is None:
        return jsonify({"success": False, "error": "registry not initialized"}), 500

    # 1. Lookup device (tenant-scoped)
    raw = _registry.get_device(device_id, tenant_id=tenant_id)
    if not raw:
        return jsonify({"success": False, "error": "device not found"}), 404

    data = request.get_json(silent=True) or {}
    command = (data.get("command") or "").strip().lower()
    parameters = data.get("parameters") or {}

    if not command:
        return jsonify({"success": False, "error": "command is required"}), 400

    # Normalize to a core Device for the SafetyEngine
    device = _dict_to_device(raw)

    # 2. Check if command is supported via capabilities
    caps = _capability_map(device, raw)
    cap_map = {
        "restart": "restart",
        "identify": "identify",
        "pause": "pause",
        "resume": "resume",
        "configure": "configure",
    }
    cap_key = cap_map.get(command, command)
    if not caps.get(cap_key):
        record = {
            "success": False,
            "error": f"'{command}' not supported by this device",
            "reason": f"'{command}' not supported by this device",
        }
        _record_attempt(device_id, command, parameters, record)
        return jsonify({
            "success": False,
            "error": f"'{command}' not supported by this device",
            "device_id": device_id,
            "supported_commands": [k for k, v in caps.items() if v],
            "read_only": True,
        }), 400

    # 3. Validate through SafetyEngine
    if _safety:
        result = _safety.validate_command(device, command, parameters)
        if not result.allowed:
            record = {
                "success": False,
                "allowed": False,
                "reason": result.reason,
                "risk_level": result.risk_level.value if result.risk_level else "unknown",
                "requires_confirmation": result.requires_confirmation,
            }
            _record_attempt(device_id, command, parameters, record)
            return jsonify({
                "success": False,
                "error": result.reason or "Command blocked by safety engine",
                "device_id": device_id,
                "command": command,
                "violations": result.violations,
                "requires_confirmation": result.requires_confirmation,
                "risk_level": result.risk_level.value if result.risk_level else "unknown",
            }), 403

    # 4. Build adapter and execute
    adapter = _build_adapter(raw, device)
    if adapter is None:
        return jsonify({
            "success": False,
            "error": "firmware not supported for command execution",
            "device_id": device_id,
            "firmware": raw.get("firmware", "") if not _is_core_device(raw) else (raw.firmware or ""),
            "read_only": True,
        }), 400

    try:
        exec_result = adapter.execute_command(command, parameters)
    except Exception as e:
        log.error("[device_control] execute error: %s", e)
        return jsonify({
            "success": False,
            "error": f"execution failed: {str(e)}",
            "device_id": device_id,
            "command": command,
        }), 500

    # 5. Record restart cooldown
    if command == "restart" and _safety and exec_result.get("success"):
        _safety.record_restart(device)

    # 6. Audit the executed attempt
    _record_attempt(device_id, command, parameters, exec_result)

    # 7. Log execution to terminal
    log.info("[device_control] %s → %s: %s (success=%s)",
             device_id, command, parameters,
             exec_result.get("success", False))

    return jsonify({
        "success": exec_result.get("success", False),
        "device_id": device_id,
        "command": command,
        "result": exec_result,
        "meta": COMMAND_META.get(command),
    })


@device_control_bp.route("/api/devices/<device_id>/test", methods=["POST"])
@require_tenant
def test_device_command(device_id: str, tenant_id: str = ""):
    """Simulate a command on a device for UI testing (tenant-scoped).
    Does NOT contact real hardware. Returns simulated success response.

    JSON body:
      { "command": "restart|identify|pause|resume" }

    Use this to test the remote control UI buttons without real hardware.
    """
    if _registry is None:
        return jsonify({"success": False, "error": "registry not initialized"}), 500

    raw = _registry.get_device(device_id, tenant_id=tenant_id)
    if not raw:
        return jsonify({"success": False, "error": "device not found"}), 404

    data = request.get_json(silent=True) or {}
    command = (data.get("command") or "").strip().lower()

    if not command:
        return jsonify({"success": False, "error": "command is required"}), 400

    if command not in COMMAND_META:
        return jsonify({
            "success": False,
            "error": f"unknown command: {command}",
            "supported_commands": list(COMMAND_META.keys()),
        }), 400

    log.info("[device_control] SIMULATED %s → %s (test mode)", device_id, command)

    simulated_results = {
        "restart": {
            "success": True,
            "simulated": True,
            "note": "SIMULATED: device restart acknowledged (test mode)",
            "status_code": 200,
        },
        "identify": {
            "success": True,
            "simulated": True,
            "note": "SIMULATED: device identify blink triggered (test mode)",
            "status_code": 200,
        },
        "pause": {
            "success": True,
            "simulated": True,
            "note": "SIMULATED: mining paused (test mode)",
            "status_code": 200,
        },
        "resume": {
            "success": True,
            "simulated": True,
            "note": "SIMULATED: mining resumed (test mode)",
            "status_code": 200,
        },
    }

    return jsonify({
        "success": True,
        "device_id": device_id,
        "command": command,
        "simulated": True,
        "result": simulated_results.get(command),
        "meta": COMMAND_META.get(command),
        "test_mode": True,
    })


@device_control_bp.route("/api/devices/<device_id>/capabilities", methods=["GET"])
@require_tenant
def get_device_capabilities(device_id: str, tenant_id: str = ""):
    """Get supported commands and their metadata for a device (tenant-scoped).
    Returns both raw capabilities and enriched command list with metadata.
    Used by the UI to render only supported command buttons."""
    if _registry is None:
        return jsonify({"success": False, "error": "registry not initialized"}), 500

    raw = _registry.get_device(device_id, tenant_id=tenant_id)
    if not raw:
        return jsonify({"success": False, "error": "device not found"}), 404

    device = _dict_to_device(raw)
    caps = _capability_map(device, raw)

    # Build enriched command list
    commands = []
    for cmd_key, cmd_meta in COMMAND_META.items():
        cap_key = {"restart": "restart", "identify": "identify",
                   "pause": "pause", "resume": "resume"}.get(cmd_key, cmd_key)
        supported = caps.get(cap_key, False)
        commands.append({
            "command": cmd_key,
            "supported": supported,
            **cmd_meta,
        })

    return jsonify({
        "device_id": device_id,
        "raw_capabilities": caps,
        "commands": commands,
        "read_only": not any(c["supported"] for c in commands),
    })
