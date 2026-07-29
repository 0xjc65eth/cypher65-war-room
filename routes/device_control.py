"""
CYPHER65 // Device Control — Unified Command Endpoint
=====================================================
POST /api/devices/<device_id>/command

Validates commands through SafetyEngine, dispatches to the correct adapter
(AxeOSConnector for Bitaxe/AxeOS, CgminerAdapter for cgminer-family),
and returns the execution result.

Read-only fallback: if a command is not supported by the firmware/adapter,
returns a clear error — never simulates execution.
"""
import json
import logging
import time
from typing import Optional

from flask import Blueprint, jsonify, request

from core.adapters.bitaxe_adapter import BitaxeAdapter
from core.adapters.cgminer_adapter import CgminerAdapter
from core.models.device import Device, DeviceStatus
from core.safety.safety_engine import SafetyEngine

log = logging.getLogger("cypher65.device_control")

# ── Registry injected from app.py ──────────────────────────────────────
_registry = None
_safety: Optional[SafetyEngine] = None


def init_device_control(registry, safety_engine: Optional[SafetyEngine] = None):
    """Inject DeviceRegistry and SafetyEngine. Called from app.py."""
    global _registry, _safety
    _registry = registry
    _safety = safety_engine or SafetyEngine()


device_control_bp = Blueprint("device_control", __name__)


# ── Helper: convert registry dict → core Device object ─────────────────
def _dict_to_device(d: dict) -> Device:
    """Convert a registry device dict to a core Device for SafetyEngine."""
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
    # Attach telemetry snapshot if available
    tel_raw = _registry.get_recent_telemetry(d["id"], limit=1) if _registry else []
    if tel_raw:
        device.current_telemetry = tel_raw[0].get("payload", {})
    return device


# ── Helper: build adapter based on firmware ────────────────────────────
def _build_adapter(device_dict: dict, device: Device):
    """Build the appropriate adapter for this device's firmware.
    Returns None if firmware is unknown/unsupported (read-only)."""
    firmware = (device_dict.get("firmware") or "").lower()
    ip = device_dict.get("ip_address", "")

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


@device_control_bp.route("/api/devices/<device_id>/command", methods=["POST"])
def execute_device_command(device_id: str):
    """Execute a command on a device.
    
    JSON body:
      { "command": "restart|identify|pause|resume", "parameters": {} }
    
    Flow:
      1. Lookup device in registry
      2. Check if command is supported via capabilities
      3. Validate through SafetyEngine
      4. Execute via adapter
      5. Record restart cooldown if applicable
      6. Return result
    
    Returns 400 if command not supported / validation fails.
    Returns 503 if device unreachable.
    Returns 200 on success.
    """
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500

    # 1. Lookup device
    device_dict = _registry.get_device(device_id)
    if not device_dict:
        return jsonify({"error": "device not found"}), 404

    data = request.get_json(silent=True) or {}
    command = (data.get("command") or "").strip().lower()
    parameters = data.get("parameters") or {}

    if not command:
        return jsonify({"error": "command is required"}), 400

    # 2. Check if command is supported via capabilities
    caps = device_dict.get("capabilities", {}) or {}
    # Map command name to capability flag
    cap_map = {
        "restart": "restart",
        "identify": "identify",
        "pause": "pause",
        "resume": "resume",
        "configure": "configure",
    }
    cap_key = cap_map.get(command, command)
    if not caps.get(cap_key):
        return jsonify({
            "error": f"'{command}' not supported by this device",
            "device_id": device_id,
            "supported_commands": [k for k, v in caps.items() if v],
            "read_only": True,
        }), 400

    # 3. Validate through SafetyEngine
    device = _dict_to_device(device_dict)
    if _safety:
        result = _safety.validate_command(device, command, parameters)
        if not result.allowed:
            return jsonify({
                "error": result.reason or "Command blocked by safety engine",
                "device_id": device_id,
                "command": command,
                "violations": result.violations,
                "requires_confirmation": result.requires_confirmation,
                "risk_level": result.risk_level.value if result.risk_level else "unknown",
            }), 400

    # 4. Build adapter and execute
    adapter = _build_adapter(device_dict, device)
    if adapter is None:
        return jsonify({
            "error": "firmware not supported for command execution",
            "device_id": device_id,
            "firmware": device_dict.get("firmware", ""),
            "read_only": True,
        }), 400

    try:
        exec_result = adapter.execute_command(command, parameters)
    except Exception as e:
        log.error("[device_control] execute error: %s", e)
        return jsonify({
            "error": f"execution failed: {str(e)}",
            "device_id": device_id,
            "command": command,
        }), 500

    # 5. Record restart cooldown
    if command == "restart" and _safety and exec_result.get("success"):
        _safety.record_restart(device)

    # 6. Log execution to terminal
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
def test_device_command(device_id: str):
    """Simulate a command on a device for UI testing.
    Does NOT contact real hardware. Returns simulated success response.

    JSON body:
      { "command": "restart|identify|pause|resume" }

    Use this to test the remote control UI buttons without real hardware.
    """
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500

    device_dict = _registry.get_device(device_id)
    if not device_dict:
        return jsonify({"error": "device not found"}), 404

    data = request.get_json(silent=True) or {}
    command = (data.get("command") or "").strip().lower()

    if not command:
        return jsonify({"error": "command is required"}), 400

    if command not in COMMAND_META:
        return jsonify({
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
def get_device_capabilities(device_id: str):
    """Get supported commands and their metadata for a device.
    Returns both raw capabilities and enriched command list with metadata.
    Used by the UI to render only supported command buttons."""
    if _registry is None:
        return jsonify({"error": "registry not initialized"}), 500

    device_dict = _registry.get_device(device_id)
    if not device_dict:
        return jsonify({"error": "device not found"}), 404

    caps = device_dict.get("capabilities", {}) or {}

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
