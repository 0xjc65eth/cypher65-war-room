"""Bounded energy scenarios from local evidence, never a miner controller."""

import json
import math
import sqlite3
import time
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

MAX_DEVICES = 100
MAX_PAYLOAD_BYTES = 65_536
STALE_SECONDS = 900
CAPABILITIES = frozenset(
    (
        "telemetry",
        "statistics",
        "restart",
        "identify",
        "pause",
        "resume",
        "frequencyControl",
        "voltageControl",
        "powerControl",
        "otaFirmware",
        "otaWebUI",
        "websocket",
        "scoreboard",
        "configure",
    )
)
CURRENCIES = frozenset(("EUR", "USD", "BRL", "GBP"))
_SOLAR = {
    "state": "not_configured",
    "source": "local_agent",
    "observed_at": None,
    "age_seconds": None,
    "power_watts": None,
}


def _number(value: Any, minimum: float = 0, maximum: float = 1e9) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value) and minimum <= value <= maximum
    except OverflowError:
        return False


def _text(value: Any, maximum: int = 128) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= maximum
        and value == value.strip()
        and all(ord(c) >= 32 for c in value)
    )


def _keys(value: Any, required: set[str], optional: set[str] | None = None) -> bool:
    return (
        isinstance(value, dict)
        and required <= value.keys()
        and value.keys() <= required | (optional or set())
    )


def validate_evaluation(value: Any) -> dict[str, Any]:
    """Validate a finite, bounded operator scenario without trusting live inputs.

    Example: ``validate_evaluation(request_json)`` raises ValueError on misuse.
    """
    if not _keys(value, {"device_id", "hours", "tariff", "constraints", "profiles"}):
        raise ValueError("invalid_request")
    if not _text(value["device_id"]):
        raise ValueError("invalid_device")
    hours = value["hours"]
    if isinstance(hours, bool) or not isinstance(hours, int) or not 1 <= hours <= 24:
        raise ValueError("invalid_hours")
    tariff = value["tariff"]
    if not _keys(tariff, {"value", "currency", "observed_at", "valid_until", "source"}):
        raise ValueError("invalid_tariff")
    if (
        not _number(tariff["value"], maximum=10000)
        or not isinstance(tariff["currency"], str)
        or tariff["currency"] not in CURRENCIES
        or tariff["source"] != "operator"
    ):
        raise ValueError("invalid_tariff")
    for key in ("observed_at", "valid_until"):
        if type(tariff[key]) is not int or not 0 <= tariff[key] <= 253402300799:
            raise ValueError("invalid_tariff_time")
    if tariff["valid_until"] <= tariff["observed_at"]:
        raise ValueError("invalid_tariff_time")
    constraints = value["constraints"]
    if not _keys(constraints, {"max_power_watts"}, {"max_cost"}):
        raise ValueError("invalid_constraints")
    if any(not _number(number) for number in constraints.values()):
        raise ValueError("invalid_constraints")
    profiles = value["profiles"]
    if not isinstance(profiles, list) or len(profiles) > 8:
        raise ValueError("invalid_profiles")
    seen = set()
    for profile in profiles:
        if not _keys(
            profile,
            {
                "id",
                "name",
                "model",
                "firmware",
                "firmware_version",
                "expected_power_watts",
                "required_capabilities",
                "approved",
            },
        ):
            raise ValueError("invalid_profile")
        if any(
            not _text(profile[key])
            for key in ("id", "name", "model", "firmware", "firmware_version")
        ):
            raise ValueError("invalid_profile")
        caps = profile["required_capabilities"]
        if (
            profile["id"] in seen
            or not _number(profile["expected_power_watts"])
            or type(profile["approved"]) is not bool
            or not isinstance(caps, list)
            or len(caps) > len(CAPABILITIES)
            or any(not isinstance(cap, str) or cap not in CAPABILITIES for cap in caps)
            or len(set(caps)) != len(caps)
        ):
            raise ValueError("invalid_profile")
        seen.add(profile["id"])
    return value


def _public_device(row: sqlite3.Row) -> dict[str, Any]:
    try:
        caps = json.loads(row["capabilities"] or "{}")
    except (ValueError, TypeError, RecursionError):
        caps = {}
    return {
        **{
            key: row[key] if _text(row[key]) else ""
            for key in ("id", "name", "model", "firmware", "firmware_version")
        },
        "capabilities": sorted(
            key
            for key in CAPABILITIES
            if isinstance(caps, dict) and caps.get(key) is True
        ),
    }


def _tenant(tenant_id: str) -> None:
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("tenant_required")


def list_advisor_devices(conn: sqlite3.Connection, tenant_id: str) -> dict[str, Any]:
    """List at most 100 owned live identities, never locators or raw metadata.

    Example: ``list_advisor_devices(conn, "tenant-a")["devices"]``.
    """
    _tenant(tenant_id)
    rows = conn.execute(
        "SELECT id,name,model,firmware,firmware_version,"
        "CASE WHEN length(CAST(capabilities AS BLOB))<=? THEN capabilities "
        "ELSE NULL END AS capabilities FROM axe_devices WHERE tenant_id=? "
        "AND COALESCE(removed_at,0)=0 ORDER BY name,id LIMIT ?",
        (MAX_PAYLOAD_BYTES, tenant_id, MAX_DEVICES + 1),
    ).fetchall()
    return {
        "devices": [_public_device(row) for row in rows[:MAX_DEVICES]],
        "truncated": len(rows) > MAX_DEVICES,
    }


def advisor_snapshot(
    conn: sqlite3.Connection, tenant_id: str, device_id: str, *, now: int | None = None
) -> dict[str, Any] | None:
    """Read only the newest tenant-owned observation without older-row fallback.

    Example: ``advisor_snapshot(conn, "tenant-a", "axe-1")`` returns None if absent.
    A heartbeat, malformed newest sample, missing power, or future time is unknown.
    """
    _tenant(tenant_id)
    if not _text(device_id):
        raise ValueError("invalid_device")
    now = int(time.time()) if now is None else now
    device = conn.execute(
        "SELECT id,name,model,firmware,firmware_version,status,"
        "CASE WHEN length(CAST(capabilities AS BLOB))<=? THEN capabilities "
        "ELSE NULL END AS capabilities FROM axe_devices WHERE tenant_id=? AND id=? "
        "AND COALESCE(removed_at,0)=0",
        (MAX_PAYLOAD_BYTES, tenant_id, device_id),
    ).fetchone()
    if device is None:
        return None
    row = conn.execute(
        "SELECT ts,CASE WHEN length(CAST(payload AS BLOB))<=? THEN payload "
        "ELSE NULL END AS payload FROM axe_telemetry WHERE tenant_id=? AND device_id=? "
        "ORDER BY ts DESC,id DESC LIMIT 1",
        (MAX_PAYLOAD_BYTES, tenant_id, device_id),
    ).fetchone()
    telemetry: dict[str, Any] = {
        "state": "empty",
        "source": "axe_telemetry",
        "observed_at": None,
        "age_seconds": None,
        "stale_after_s": STALE_SECONDS,
        "power_watts": None,
        "hashrate_hs": None,
        "temperature_c": None,
    }
    if row is not None:
        ts = row["ts"]
        timestamp_valid = type(ts) is int and 0 < ts <= now
        telemetry.update(
            state="unknown",
            observed_at=ts if timestamp_valid else None,
            age_seconds=now - ts if timestamp_valid else None,
        )
        try:
            payload = json.loads(row["payload"])
        except (ValueError, TypeError, RecursionError):
            payload = None
        if (
            timestamp_valid
            and isinstance(payload, dict)
            and not payload.get("_invalid_fields")
            and payload.get("mining_paused") is not True
            and _number(payload.get("hashrate_hs"), maximum=1e18)
        ):
            telemetry["hashrate_hs"] = payload["hashrate_hs"]
            if _number(payload.get("power_watts")):
                telemetry["power_watts"] = payload["power_watts"]
                telemetry["state"] = "current" if now - ts < STALE_SECONDS else "stale"
            if _number(payload.get("temperature"), -40, 150):
                telemetry["temperature_c"] = payload["temperature"]
    if str(device["status"]).upper() not in ("ONLINE", "HASHING", "IDLE"):
        telemetry["state"] = "offline"
    return {
        "schema_version": 1,
        "generated_at": now,
        "device": _public_device(device),
        "telemetry": telemetry,
        "solar": dict(_SOLAR),
    }


def _amount(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP), "f")


def _below_resolution(value: Decimal) -> bool:
    return value > 0 and Decimal(_amount(value)) == 0


def evaluate_energy(
    conn: sqlite3.Connection, tenant_id: str, request: Any, *, now: int | None = None
) -> dict[str, Any] | None:
    """Compare explicit operator power scenarios; never forecast profit or apply.

    Example: ``evaluate_energy(conn, "tenant-a", validated_operator_request)``.
    Decimal arithmetic uses W / 1000 * hours * currency/kWh, rounded to six places.
    """
    value = validate_evaluation(request)
    snapshot = advisor_snapshot(conn, tenant_id, value["device_id"], now=now)
    if snapshot is None:
        return None
    now = snapshot["generated_at"]
    tariff = value["tariff"]
    tariff_state = (
        "future"
        if tariff["observed_at"] > now
        else "expired" if tariff["valid_until"] <= now else "current"
    )
    factor = Decimal(value["hours"]) / Decimal(1000)
    price = Decimal(str(tariff["value"]))
    blockers = []
    if snapshot["telemetry"]["state"] != "current":
        blockers.append("telemetry_unavailable_or_stale")
    if tariff_state != "current":
        blockers.append("tariff_not_current")
    baseline: dict[str, Any] = {
        "state": "blocked",
        "energy_kwh": None,
        "cost": None,
        "energy_below_resolution": False,
        "cost_below_resolution": False,
    }
    if not blockers:
        energy = Decimal(str(snapshot["telemetry"]["power_watts"])) * factor
        baseline = {
            "state": "available",
            "energy_kwh": _amount(energy),
            "cost": _amount(energy * price),
            "energy_below_resolution": _below_resolution(energy),
            "cost_below_resolution": _below_resolution(energy * price),
        }
    profiles = []
    eligible = []
    for profile in value["profiles"]:
        reasons = list(blockers)
        if not profile["approved"]:
            reasons.append("not_operator_approved")
        for field in ("model", "firmware", "firmware_version"):
            if profile[field] != snapshot["device"][field]:
                reasons.append(field + "_mismatch")
        if not set(profile["required_capabilities"]) <= set(
            snapshot["device"]["capabilities"]
        ):
            reasons.append("capabilities_mismatch")
        power = Decimal(str(profile["expected_power_watts"]))
        energy = power * factor
        cost = energy * price
        if power > Decimal(str(value["constraints"]["max_power_watts"])):
            reasons.append("power_limit_exceeded")
        max_cost = value["constraints"].get("max_cost")
        if max_cost is not None and cost > Decimal(str(max_cost)):
            reasons.append("cost_limit_exceeded")
        profiles.append(
            {
                "id": profile["id"],
                "name": profile["name"],
                "eligible": not reasons,
                "reasons": reasons,
                "expected_power_watts": profile["expected_power_watts"],
                "energy_kwh": _amount(energy),
                "cost": _amount(cost),
                "energy_below_resolution": _below_resolution(energy),
                "cost_below_resolution": _below_resolution(cost),
            }
        )
        if not reasons:
            eligible.append(profile["id"])
    return {
        **snapshot,
        "mode": "read_only",
        "hours": value["hours"],
        "currency": tariff["currency"],
        "tariff_state": tariff_state,
        "tariff": dict(tariff),
        "resolution": {
            "energy_kwh": "0.000001",
            "cost": "0.000001",
            "rounding": "half_up",
        },
        "expires_at": (
            min(
                snapshot["telemetry"]["observed_at"] + STALE_SECONDS,
                tariff["valid_until"],
            )
            if not blockers
            else None
        ),
        "baseline": baseline,
        "profiles": profiles,
        "suggestion": {
            "type": "review_candidates",
            "profile_id": None,
            "eligible_profile_ids": eligible,
            "reasons": [] if eligible else blockers or ["no_eligible_profiles"],
        },
        "limitations": [
            "constant_power_scenario_not_forecast",
            "operator_inputs_not_certified",
            "device_reported_power_not_wall_meter",
            "no_profit_estimate",
            "solar_not_configured",
            "no_hardware_commands",
        ],
    }
