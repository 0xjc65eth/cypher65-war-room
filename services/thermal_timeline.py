"""Bounded, tenant-scoped historical observations; never a hardware controller."""

import json
import math
import sqlite3
import time
from typing import Any

from axe_fleet.registry import normalize_device_mac

MAX_SAMPLES = 300
MAX_DEVICES = 100
MAX_MAINTENANCE = 200
STALE_SECONDS = 900
MAX_PAYLOAD_BYTES = 65_536
FIELDS = {
    "temperature_c": ("temperature", -40, 150),
    "hashrate_hs": ("hashrate_hs", 0, 1e18),
    "fan_rpm": ("fan_rpm", 0, 100_000),
    "fan_speed": ("fan_speed", 0, 100),
    "power_watts": ("power_watts", 0, None),
    "voltage_mv": ("voltage_mv", 0, None),
    "frequency_mhz": ("frequency_mhz", 0, None),
}
CONFIG_FIELDS = ("voltage_mv", "frequency_mhz", "fan_speed")
MAINTENANCE_TYPES = frozenset(
    ("firmware_update", "cleaning", "hardware_check", "repair", "inspection")
)


def _number(value: Any, minimum: float, maximum: float | None) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        if not math.isfinite(value) or value < minimum:
            return None
    except OverflowError:
        return None
    if maximum is not None and value > maximum:
        return None
    return value


def _mac(value: Any) -> str | None:
    return normalize_device_mac(value)


def list_timeline_devices(conn: sqlite3.Connection, tenant_id: str) -> dict:
    """Return only live device identities for one tenant, bounded at 100.

    Example: ``list_timeline_devices(conn, "operator-a")["devices"]``.
    """
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("tenant required")
    rows = conn.execute(
        "SELECT id, name FROM axe_devices WHERE tenant_id=? "
        "AND COALESCE(removed_at,0)=0 ORDER BY name, id LIMIT ?",
        (tenant_id, MAX_DEVICES + 1),
    ).fetchall()
    return {
        "devices": [
            {"id": row["id"], "name": row["name"]} for row in rows[:MAX_DEVICES]
        ],
        "truncated": len(rows) > MAX_DEVICES,
    }


def _maintenance(conn, device, tenant_id, start, now):
    mac = _mac(device["mac_address"])
    if mac is None:
        return "unlinked", [], False
    conn.create_function("thermal_canonical_mac", 1, _mac, deterministic=True)
    axes = conn.execute(
        "SELECT id FROM axe_devices WHERE tenant_id=? "
        "AND COALESCE(removed_at,0)=0 AND thermal_canonical_mac(mac_address)=? LIMIT 2",
        (tenant_id, mac),
    ).fetchall()
    if len(axes) != 1:
        return "ambiguous", [], False
    # Core is optional on a fresh fleet-only database; do not infer its identity.
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='devices'"
    ).fetchone():
        return "unlinked", [], False
    cores = conn.execute(
        "SELECT id FROM devices WHERE tenant_id=? AND thermal_canonical_mac(mac)=? LIMIT 2",
        (tenant_id, mac),
    ).fetchall()
    if len(cores) != 1:
        return ("ambiguous" if cores else "unlinked"), [], False
    core_id = cores[0]["id"]
    legacy = conn.execute(
        "SELECT 1 FROM maintenance_records WHERE tenant_id IS NULL AND device_id=? "
        "AND ts BETWEEN ? AND ? LIMIT 1",
        (core_id, start, now),
    ).fetchone()
    rows = conn.execute(
        "SELECT ts,type FROM maintenance_records WHERE tenant_id=? AND device_id=? "
        "AND ts BETWEEN ? AND ? ORDER BY ts DESC,id DESC LIMIT ?",
        (tenant_id, core_id, start, now, MAX_MAINTENANCE + 1),
    ).fetchall()
    markers = [
        {
            "ts": row["ts"],
            "kind": "maintenance",
            "type": row["type"] if row["type"] in MAINTENANCE_TYPES else "other",
        }
        for row in reversed(rows[:MAX_MAINTENANCE])
    ]
    return (
        "legacy_unscoped" if legacy else "available",
        markers,
        len(rows) > MAX_MAINTENANCE,
    )


def build_thermal_timeline(
    conn: sqlite3.Connection,
    tenant_id: str,
    device_id: str,
    hours: int = 6,
    *,
    now: int | None = None,
) -> dict | None:
    """Project up to 300 recent local observations without interpolation.

    Example: ``build_thermal_timeline(conn, "operator-a", "axe-1", 6)``.
    None means no live device owned by this tenant, not an empty fleet fallback.
    """
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("tenant required")
    if isinstance(hours, bool) or hours not in (1, 6, 24):
        raise ValueError("invalid hours")
    now = int(time.time()) if now is None else now
    start = now - hours * 3600
    device = conn.execute(
        "SELECT id,name,mac_address,status FROM axe_devices WHERE tenant_id=? AND id=? "
        "AND COALESCE(removed_at,0)=0",
        (tenant_id, device_id),
    ).fetchone()
    if device is None:
        return None
    rows = conn.execute(
        "SELECT id,ts,CASE WHEN length(CAST(payload AS BLOB))<=? "
        "THEN payload ELSE NULL END AS payload "
        "FROM axe_telemetry WHERE tenant_id=? AND device_id=? "
        "AND ts BETWEEN ? AND ? ORDER BY ts DESC,id DESC LIMIT ?",
        (MAX_PAYLOAD_BYTES, tenant_id, device_id, start, now, MAX_SAMPLES + 1),
    ).fetchall()
    samples = []
    seen = set()
    invalid_timestamps = set()
    skipped = 0
    for row in rows[:MAX_SAMPLES]:
        ts = row["ts"]
        if not isinstance(ts, int) or ts in seen:
            skipped += 1
            continue
        seen.add(ts)
        raw = row["payload"]
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            skipped += 1
            invalid_timestamps.add(ts)
            continue
        try:
            payload = json.loads(raw)
        except (ValueError, RecursionError):
            skipped += 1
            invalid_timestamps.add(ts)
            continue
        if not isinstance(payload, dict):
            skipped += 1
            invalid_timestamps.add(ts)
            continue
        # A heartbeat or invalid required measurement is never plotted as zero.
        if _number(payload.get("hashrate_hs"), 0, 1e18) is None:
            skipped += 1
            invalid_timestamps.add(ts)
            continue
        sample = {
            name: _number(payload.get(source), minimum, maximum)
            for name, (source, minimum, maximum) in FIELDS.items()
        }
        sample.update(
            ts=ts, source="axe_telemetry", window_seconds=None, gap_before_seconds=None
        )
        samples.append(sample)
    samples.reverse()
    markers = []
    gaps = 0
    for before, after in zip(samples, samples[1:]):
        distance = after["ts"] - before["ts"]
        if distance > STALE_SECONDS or any(
            before["ts"] < ts < after["ts"] for ts in invalid_timestamps
        ):
            after["gap_before_seconds"] = distance
            gaps += 1
            continue
        changes = [
            {"field": field, "before": before[field], "after": after[field]}
            for field in CONFIG_FIELDS
            if before[field] is not None
            and after[field] is not None
            and before[field] != after[field]
        ]
        if changes:
            markers.append(
                {
                    "ts": after["ts"],
                    "kind": "observed_configuration_change",
                    "changes": changes,
                }
            )
    context, maintenance, maintenance_truncated = _maintenance(
        conn, device, tenant_id, start, now
    )
    markers.extend(maintenance)
    markers.sort(key=lambda marker: (marker["ts"], marker["kind"]))
    latest = samples[-1]["ts"] if samples else None
    age = now - latest if latest is not None else None
    status = str(device["status"] or "").upper()
    if status not in (
        "ONLINE",
        "OFFLINE",
        "HASHING",
        "PAUSED",
        "WARNING",
        "ERROR",
        "STALE",
        "IDLE",
        "UNKNOWN",
    ):
        status = "UNKNOWN"
    state = "current"
    if not rows:
        state = "empty"
    elif age is None:
        state = "unknown"
    elif status in ("OFFLINE", "PAUSED"):
        state = "offline"
    elif age > STALE_SECONDS:
        state = "stale"
    return {
        "schema_version": 1,
        "generated_at": now,
        "source": "local_telemetry_history",
        "hours": hours,
        "device": {"id": device["id"], "name": device["name"], "status": status},
        "samples": samples,
        "markers": markers,
        "maintenance_context": context,
        "maintenance_truncated": maintenance_truncated,
        "latest_sample_ts": latest,
        "age_seconds": age,
        "state": state,
        "stale_after_s": STALE_SECONDS,
        "coverage": {
            "returned": len(samples),
            "scanned": min(len(rows), MAX_SAMPLES),
            "skipped": skipped,
            "truncated": len(rows) > MAX_SAMPLES,
            "gaps": gaps,
        },
    }
