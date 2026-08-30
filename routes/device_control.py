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

from services.tenant import require_tenant, role_required
from services.command_confirmation import (
    consume_confirmation as _consume_persisted_confirmation,
    issue_confirmation as _issue_persisted_confirmation,
)
from services.safety_policy import can_execute_physical_command

from core.adapters.bitaxe_adapter import BitaxeAdapter
from core.adapters.cgminer_adapter import CgminerAdapter
from core.models.device import Device, DeviceStatus
from core.safety.safety_engine import SafetyEngine

log = logging.getLogger("cypher65.device_control")

# ── Registry injected from app.py ──────────────────────────────────────
_registry = None
_safety: Optional[SafetyEngine] = None
_record_cb: Optional[Callable] = None  # app._record_command — audits every attempt

CONFIRMATION_TTL_SECONDS = 120


def init_device_control(
    registry,
    safety_engine: Optional[SafetyEngine] = None,
    record_command: Optional[Callable] = None,
):
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
        return {c.name: bool(c.supported) for c in caps if getattr(c, "name", None)}
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
    # Trust only well-formed telemetry — must carry a hashrate key
    # (axe_fleet uses hashrate_hs, core uses the canonical hashrate).
    # Legacy broken stubs {"device_id": ...} are never attached.
    if isinstance(tel, dict) and ("hashrate_hs" in tel or "hashrate" in tel):
        device.current_telemetry = tel
    elif _registry and hasattr(_registry, "get_recent_telemetry"):
        try:
            tel_raw = _registry.get_recent_telemetry(d["id"], limit=1)
            # Trust only well-formed telemetry payloads (must carry a
            # hashrate key) — legacy broken stubs are ignored.
            if tel_raw:
                payload = tel_raw[0].get("payload", {})
                if isinstance(payload, dict) and (
                    "hashrate_hs" in payload or "hashrate" in payload
                ):
                    device.current_telemetry = payload
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
        "requires_confirmation": True,
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
        "requires_confirmation": True,
        "risk_level": "low",
        "description": "Resume mining after pause",
    },
    "set_frequency": {
        "label": "Set frequency",
        "requires_confirmation": True,
        "risk_level": "high",
        "description": "Change ASIC frequency (can affect power and thermals)",
    },
    "update_pool": {
        "label": "Update pool",
        "requires_confirmation": True,
        "risk_level": "high",
        "description": "Change the miner pool configuration",
    },
}


_SENSITIVE_FIELD_NAMES = {
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "credential",
    "credentials",
    "passphrase",
    "private_key",
    "privatekey",
    "secret",
}
_SENSITIVE_FIELD_SUFFIXES = ("password", "secret", "token")


def redact_command_data(value: Any) -> Any:
    """Return a JSON-like copy with credential-shaped fields redacted.

    Command payloads can be extended by firmware integrations, so audit and
    API output must not rely on a fixed list of today's adapter parameters.
    """
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            compact = normalized.replace("_", "")
            if (
                normalized in _SENSITIVE_FIELD_NAMES
                or compact in _SENSITIVE_FIELD_NAMES
                or compact.endswith(_SENSITIVE_FIELD_SUFFIXES)
            ):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_command_data(item)
        return redacted
    if isinstance(value, list):
        return [redact_command_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_command_data(item) for item in value)
    return value


def _record_attempt(
    device_id: str, command: str, parameters: Dict[str, Any], result: Dict[str, Any]
):
    """Audit an attempt without persisting credentials from command payloads."""
    if _record_cb is None:
        return
    try:
        _record_cb(
            device_id,
            command,
            redact_command_data(parameters),
            redact_command_data(result),
        )
    except Exception as e:
        log.warning("[device_control] record_command callback failed: %s", e)


def _request_json_object():
    """Return a JSON object body, or a JSON-safe 400 response.

    Flask returns lists and scalar JSON values successfully. Command routes
    accept objects only, so validate the envelope before accessing ``.get``.
    """
    data = request.get_json(silent=True)
    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return None, (
            jsonify({"success": False, "error": "JSON body must be an object"}),
            400,
        )
    return data, None


def _capability_metadata(raw: Any, device: Device, command: str) -> Dict[str, Any]:
    """Return command metadata declared by the device capability, if present."""
    if _is_core_device(raw):
        for capability in device.capabilities or []:
            if getattr(capability, "name", "") == command:
                risk = getattr(capability, "risk_level", None)
                return {
                    "requires_confirmation": bool(
                        getattr(capability, "requires_confirmation", False)
                    ),
                    "risk_level": getattr(risk, "value", risk) or "low",
                }
        return {}

    capabilities = raw.get("capabilities") or {}
    if isinstance(capabilities, list):
        for capability in capabilities:
            if isinstance(capability, dict) and capability.get("name") == command:
                return {
                    "requires_confirmation": bool(
                        capability.get("requires_confirmation", False)
                    ),
                    "risk_level": capability.get("risk_level") or "low",
                }
    return {}


def _command_metadata(raw: Any, device: Device, command: str) -> Dict[str, Any]:
    """Merge safety metadata without allowing either source to lower a gate."""
    defaults = dict(COMMAND_META.get(command, {}))
    capability = _capability_metadata(raw, device, command)
    metadata = {**defaults, **capability}
    metadata["requires_confirmation"] = bool(
        defaults.get("requires_confirmation") or capability.get("requires_confirmation")
    )
    risk_rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    default_risk = str(defaults.get("risk_level") or "low").lower()
    capability_risk = str(capability.get("risk_level") or "low").lower()
    metadata["risk_level"] = max(
        (default_risk, capability_risk), key=lambda risk: risk_rank.get(risk, 0)
    )
    metadata.setdefault("label", command.replace("_", " ").title())
    return metadata


def _confirmation_phrase(command: str) -> str:
    return f"CONFIRM {command.upper()}"


def _confirmation_binding(
    tenant_id: str, device_id: str, command: str, parameters: Dict[str, Any]
) -> Optional[str]:
    """Create a stable, strict binding for a one-time approval token."""
    try:
        return json.dumps(
            {
                "tenant_id": tenant_id or "default",
                "device_id": device_id,
                "command": command,
                "parameters": parameters,
            },
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError):
        return None


def _issue_confirmation(binding: str) -> str:
    """Compatibility wrapper over the durable multi-process store."""
    parsed = json.loads(binding)
    issued = _issue_persisted_confirmation(
        parsed["tenant_id"],
        parsed["device_id"],
        parsed["command"],
        parsed["parameters"],
        now=int(time.time()),
    )
    return issued["confirmation_token"]


def _consume_confirmation(token: Any, binding: str) -> tuple[bool, str]:
    """Consume an approval atomically; mismatches and replays fail closed."""
    if not isinstance(token, str) or not token.strip():
        return False, "A one-time human confirmation is required before this command."
    try:
        parsed = json.loads(binding)
        valid = _consume_persisted_confirmation(
            token,
            parsed["tenant_id"],
            parsed["device_id"],
            parsed["command"],
            parsed["parameters"],
            now=int(time.time()),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        valid = False
    if not valid:
        return False, "Confirmation is mismatched, expired, or was already used."
    return True, ""


def _safe_execution_failure() -> Dict[str, Any]:
    """Keep transport and firmware internals in server logs, not API output."""
    return {
        "success": False,
        "error": "The device did not accept the command. Verify connectivity and firmware before retrying.",
    }


@device_control_bp.route(
    "/api/devices/<device_id>/command/confirmation", methods=["POST"]
)
@require_tenant
@role_required("member")
def issue_device_command_confirmation(device_id: str, tenant_id: str = ""):
    """Issue a short-lived approval after the operator types the confirmation.

    The resulting token is bound to this tenant, device, command, and exact
    parameters. It can be consumed once by the execution endpoint and is not
    persisted as a one-way token digest so multi-process deployments enforce
    the same single-use approval.
    """
    if _registry is None:
        return jsonify({"success": False, "error": "registry not initialized"}), 500

    raw = _registry.get_device(device_id, tenant_id=tenant_id)
    if not raw:
        return jsonify({"success": False, "error": "device not found"}), 404

    data, error_response = _request_json_object()
    if error_response:
        return error_response

    command_value = data.get("command") or ""
    if not isinstance(command_value, str):
        return jsonify({"success": False, "error": "command must be a string"}), 400
    command = command_value.strip().lower()
    parameters = data.get("parameters")
    if parameters is None:
        parameters = {}
    elif not isinstance(parameters, dict):
        return jsonify({"success": False, "error": "parameters must be an object"}), 400

    device = _dict_to_device(raw)
    caps = _capability_map(device, raw)
    if not command or not caps.get(command):
        return (
            jsonify(
                {"success": False, "error": "command is not supported by this device"}
            ),
            400,
        )

    metadata = _command_metadata(raw, device, command)
    if not metadata["requires_confirmation"]:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "this command does not require confirmation",
                }
            ),
            400,
        )

    if _safety:
        result = _safety.validate_command(device, command, parameters)
        if not result.allowed:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": result.reason or "Command blocked by safety engine",
                        "device_id": device_id,
                        "command": command,
                        "violations": result.violations,
                    }
                ),
                403,
            )

    phrase = _confirmation_phrase(command)
    if data.get("confirmation") != phrase:
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"Type '{phrase}' to confirm this command.",
                    "confirmation_phrase": phrase,
                }
            ),
            400,
        )

    binding = _confirmation_binding(tenant_id, device_id, command, parameters)
    if binding is None:
        return (
            jsonify(
                {"success": False, "error": "parameters must be valid JSON values"}
            ),
            400,
        )

    response = jsonify(
        {
            "success": True,
            "confirmation_token": _issue_confirmation(binding),
            "expires_in_seconds": CONFIRMATION_TTL_SECONDS,
            "command": command,
            "device_id": device_id,
        }
    )
    response.status_code = 201
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response


@device_control_bp.route("/api/devices/<device_id>/command", methods=["POST"])
@require_tenant
@role_required("member")
def execute_device_command(device_id: str, tenant_id: str = ""):
    """Execute a command on a device (scoped to the request tenant).

    JSON body:
      {
        "command": "restart|identify|pause|resume",
        "parameters": {},
        "dry_run": true,
        "confirmation_token": "required for state-changing commands"
      }

    Flow:
      1. Lookup device in registry (scoped by tenant)
      2. Check if command is supported via capabilities
      3. Validate through SafetyEngine (blocked → 403, audited)
      4. Consume a server-side confirmation token when required
      5. Execute via adapter (record result)
      6. Record restart cooldown if applicable
      7. Return result

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

    data, error_response = _request_json_object()
    if error_response:
        return error_response

    command_value = data.get("command") or ""
    if not isinstance(command_value, str):
        return jsonify({"success": False, "error": "command must be a string"}), 400
    command = command_value.strip().lower()
    parameters = data.get("parameters")
    if parameters is None:
        parameters = {}
    elif not isinstance(parameters, dict):
        return jsonify({"success": False, "error": "parameters must be an object"}), 400
    dry_run = data.get("dry_run", True)
    if not isinstance(dry_run, bool):
        return jsonify({"success": False, "error": "dry_run must be a boolean"}), 400

    if not command:
        return jsonify({"success": False, "error": "command is required"}), 400
    if not isinstance(parameters, dict):
        return jsonify({"success": False, "error": "parameters must be an object"}), 400

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
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"'{command}' not supported by this device",
                    "device_id": device_id,
                    "supported_commands": [k for k, v in caps.items() if v],
                    "read_only": True,
                }
            ),
            400,
        )

    # 3. Validate through SafetyEngine
    safety_result = None
    if _safety:
        safety_result = _safety.validate_command(device, command, parameters)
        if not safety_result.allowed:
            record = {
                "success": False,
                "allowed": False,
                "reason": safety_result.reason,
                "risk_level": (
                    safety_result.risk_level.value
                    if safety_result.risk_level
                    else "unknown"
                ),
                "requires_confirmation": safety_result.requires_confirmation,
            }
            _record_attempt(device_id, command, parameters, record)
            return (
                jsonify(
                    {
                        "success": False,
                        "error": safety_result.reason
                        or "Command blocked by safety engine",
                        "device_id": device_id,
                        "command": command,
                        "violations": safety_result.violations,
                        "requires_confirmation": safety_result.requires_confirmation,
                        "risk_level": (
                            safety_result.risk_level.value
                            if safety_result.risk_level
                            else "unknown"
                        ),
                    }
                ),
                403,
            )

    # Read-only is the API default. A caller must explicitly opt into physical
    # execution; dry-runs still traverse capability and safety validation and
    # are recorded in the same audit stream.
    if dry_run:
        record = {
            "success": True,
            "dry_run": True,
            "read_only": True,
            "allowed": True,
            "would_require_confirmation": bool(
                _command_metadata(raw, device, command)["requires_confirmation"]
            )
            or bool(safety_result and safety_result.requires_confirmation),
        }
        _record_attempt(device_id, command, parameters, record)
        return jsonify(
            {
                **record,
                "device_id": device_id,
                "command": command,
                "parameters": redact_command_data(parameters),
            }
        )

    # Deployment-level kill switch.  Dry-runs have already returned above;
    # only a real side effect reaches this gate.  Licensing, role and a valid
    # confirmation token are necessary but never sufficient to bypass it.
    if not dry_run and not can_execute_physical_command():
        record = {
            "success": False,
            "allowed": False,
            "error": "physical commands are disabled by deployment policy",
            "reason": "deployment_policy_disabled",
            "read_only": True,
        }
        _record_attempt(device_id, command, parameters, record)
        return jsonify(record), 503

    # 4. A device capability and SafetyEngine can both require confirmation.
    # The controller is the enforcement point: metadata is never just a UI hint.
    metadata = _command_metadata(raw, device, command)
    confirmation_required = bool(metadata["requires_confirmation"]) or bool(
        safety_result and safety_result.requires_confirmation
    )
    if confirmation_required:
        binding = _confirmation_binding(tenant_id, device_id, command, parameters)
        confirmed, reason = _consume_confirmation(
            data.get("confirmation_token"), binding or ""
        )
        if not confirmed:
            record = {
                "success": False,
                "allowed": False,
                "error": reason,
                "reason": reason,
                "risk_level": metadata["risk_level"],
                "requires_confirmation": True,
            }
            _record_attempt(device_id, command, parameters, record)
            return (
                jsonify(
                    {
                        "success": False,
                        "error": reason,
                        "device_id": device_id,
                        "command": command,
                        "requires_confirmation": True,
                        "confirmation_phrase": _confirmation_phrase(command),
                        "confirmation_endpoint": f"/api/devices/{device_id}/command/confirmation",
                        "risk_level": metadata["risk_level"],
                    }
                ),
                403,
            )

    # 5. Build adapter and execute
    adapter = _build_adapter(raw, device)
    if adapter is None:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "firmware not supported for command execution",
                    "device_id": device_id,
                    "firmware": (
                        raw.get("firmware", "")
                        if not _is_core_device(raw)
                        else (raw.firmware or "")
                    ),
                    "read_only": True,
                }
            ),
            400,
        )

    try:
        exec_result = adapter.execute_command(command, parameters)
    except Exception:
        log.exception("[device_control] execute error for %s → %s", device_id, command)
        safe_result = _safe_execution_failure()
        _record_attempt(device_id, command, parameters, safe_result)
        return (
            jsonify(
                {
                    "success": False,
                    "error": safe_result["error"],
                    "device_id": device_id,
                    "command": command,
                }
            ),
            503,
        )

    if not isinstance(exec_result, dict) or not exec_result.get("success", False):
        log.warning(
            "[device_control] device rejected %s → %s: %r",
            device_id,
            command,
            redact_command_data(exec_result),
        )
        safe_result = _safe_execution_failure()
        _record_attempt(device_id, command, parameters, safe_result)
        return (
            jsonify(
                {
                    "success": False,
                    "error": safe_result["error"],
                    "device_id": device_id,
                    "command": command,
                    "result": safe_result,
                }
            ),
            503,
        )

    # 6. Record restart cooldown
    if command == "restart" and _safety and exec_result.get("success"):
        _safety.record_restart(device)

    # 7. Audit the executed attempt
    public_result = redact_command_data(exec_result)
    _record_attempt(device_id, command, parameters, public_result)

    # 8. Log execution to terminal
    log.info(
        "[device_control] %s → %s: %s (success=%s)",
        device_id,
        command,
        redact_command_data(parameters),
        exec_result.get("success", False),
    )

    return jsonify(
        {
            "success": exec_result.get("success", False),
            "device_id": device_id,
            "command": command,
            "result": public_result,
            "meta": metadata,
        }
    )


@device_control_bp.route("/api/devices/<device_id>/test", methods=["POST"])
@require_tenant
@role_required("member")
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

    data, error_response = _request_json_object()
    if error_response:
        return error_response

    command_value = data.get("command") or ""
    if not isinstance(command_value, str):
        return jsonify({"success": False, "error": "command must be a string"}), 400
    command = command_value.strip().lower()

    if not command:
        return jsonify({"success": False, "error": "command is required"}), 400

    if command not in COMMAND_META:
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"unknown command: {command}",
                    "supported_commands": list(COMMAND_META.keys()),
                }
            ),
            400,
        )

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

    return jsonify(
        {
            "success": True,
            "device_id": device_id,
            "command": command,
            "simulated": True,
            "result": simulated_results.get(command),
            "meta": COMMAND_META.get(command),
            "test_mode": True,
        }
    )


@device_control_bp.route("/api/devices/<device_id>/capabilities", methods=["GET"])
@require_tenant
@role_required("viewer")
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
        cap_key = {
            "restart": "restart",
            "identify": "identify",
            "pause": "pause",
            "resume": "resume",
        }.get(cmd_key, cmd_key)
        supported = caps.get(cap_key, False)
        commands.append(
            {
                "command": cmd_key,
                "supported": supported,
                **cmd_meta,
            }
        )

    return jsonify(
        {
            "device_id": device_id,
            "raw_capabilities": caps,
            "commands": commands,
            "read_only": not any(c["supported"] for c in commands),
        }
    )
