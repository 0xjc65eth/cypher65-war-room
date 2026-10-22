"""Allowlisted, read-only fleet projection for the Mini War Room (#836)."""

import math
import time
from collections.abc import Iterable, Mapping
from typing import Any

STALE_AFTER_S = 900
_CURRENT_STATUSES = frozenset(("ONLINE", "IDLE", "HASHING"))
_METRICS = (
    ("hashrate", "hashrate_hs", "H/s", "sum"),
    ("power", "power_watts", "W", "sum"),
    ("temperature", "temperature", "°C", "max"),
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = float(value)
    except (OverflowError, ValueError):
        return None
    return result if math.isfinite(result) and result >= 0 else None


def build_mini_snapshot(
    devices: Iterable[Mapping[str, Any]], *, now: float | None = None
) -> dict[str, Any]:
    """Project scoped registry rows into anonymous current measurements only.

    Hashrate and power are sums; temperature is the maximum observed sensor
    value, not an average or a physical-health assertion. Each metric uses
    only its valid contributors. Missing data is never synthesized as zero.
    OFFLINE/PAUSED and STALE rows cannot contribute even with fresh samples.
    A latest sample has no known averaging window (``window_s=None``).

    Example::

        snapshot = build_mini_snapshot([], now=1_800_000_000)
        assert snapshot["state"] == "empty"
    """
    observed_now = _number(time.time() if now is None else now)
    if observed_now is None or observed_now <= 0:
        raise ValueError("a finite positive observation time is required")
    counts = dict.fromkeys(("total", "current", "stale", "offline", "unknown"), 0)
    samples: dict[str, list[tuple[float, float]]] = {
        key: [] for key, _, _, _ in _METRICS
    }
    for row in devices:
        counts["total"] += 1
        if not isinstance(row, Mapping):
            counts["unknown"] += 1
            continue
        status = row.get("status")
        if not isinstance(status, str):
            counts["unknown"] += 1
            continue
        if status in ("OFFLINE", "PAUSED"):
            counts["offline"] += 1
            continue
        if status == "STALE":
            counts["stale"] += 1
            continue
        telemetry = row.get("telemetry")
        if status not in _CURRENT_STATUSES or not isinstance(telemetry, Mapping):
            counts["unknown"] += 1
            continue
        timestamp = _number(telemetry.get("ts"))
        if timestamp is None or timestamp <= 0 or timestamp > observed_now:
            counts["unknown"] += 1
            continue
        if observed_now - timestamp > STALE_AFTER_S:
            counts["stale"] += 1
            continue
        contributed = False
        for key, field, _, _ in _METRICS:
            value = _number(telemetry.get(field))
            if value is not None:
                samples[key].append((value, timestamp))
                contributed = True
        counts["current" if contributed else "unknown"] += 1

    metrics: dict[str, Any] = {}
    for key, _, unit, aggregation in _METRICS:
        values = samples[key]
        value = None
        if values:
            try:
                aggregate = (
                    math.fsum(item[0] for item in values)
                    if aggregation == "sum"
                    else max(item[0] for item in values)
                )
                value = aggregate if math.isfinite(aggregate) else None
            except OverflowError:
                # An unrepresentable sum is unavailable, never Infinity or 0.
                pass
        oldest = min((item[1] for item in values), default=None)
        newest = max((item[1] for item in values), default=None)
        metrics[key] = {
            "value": value,
            "unit": unit,
            "contributors": len(values),
            "oldest_observed_at": oldest,
            "newest_observed_at": newest,
            "age_s": observed_now - oldest if oldest is not None else None,
            "source": "fleet_telemetry",
            "window_s": None,
            "aggregation": aggregation,
        }

    if not counts["total"]:
        state = "empty"
    elif counts["current"]:
        complete = counts["current"] == counts["total"] and all(
            metric["value"] is not None and metric["contributors"] == counts["total"]
            for metric in metrics.values()
        )
        state = "current" if complete else "partial"
    elif counts["stale"]:
        state = "stale"
    elif counts["offline"] == counts["total"]:
        state = "offline"
    else:
        state = "unknown"
    return {
        "schema_version": 1,
        "generated_at": observed_now,
        "stale_after_s": STALE_AFTER_S,
        "state": state,
        "counts": counts,
        "metrics": metrics,
    }
