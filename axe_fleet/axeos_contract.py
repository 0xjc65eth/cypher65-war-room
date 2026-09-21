"""Canonical ESP-Miner / AxeOS ``/api/system/info`` contract.

Official firmware (ESP-Miner OpenAPI, e.g. Gamma-Max ``system_api_json.c``):

    hashRate, hashRate_1m, hashRate_10m, hashRate_1h   — GH/s
    expectedHashrate                                   — GH/s
    uptimeSeconds, macAddr, stratumURL, stratumUser
    ASICModel, boardVersion, frequency
    bestDiff, bestSessionDiff
    sharesAccepted, sharesRejected
    fanspeed, fanrpm, temp, vrTemp

Legacy CYPHER65 fixtures and some older forks used lowercase ``hashrate``
already in H/s. Both shapes must round-trip to the fleet schema
(``hashrate_hs`` in H/s). A missing measurement is ``None``, never a
fabricated ``0``.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

# Strong identity: a catch-all JSON 200 from a router/NAS/HA/camera is NOT
# a miner. ``frequency`` alone is a Wi-Fi/radio field on many appliances.
AXEOS_STRONG_MARKERS = (
    "ASICModel",
    "boardVersion",
    "hashRate",
    "hashrate",
    "expectedHashrate",
    "bestDiff",
    "sharesAccepted",
)

# Values at or above this (when the key is camelCase ``hashRate``) are
# already H/s — the legacy test corpus used 1.2e12-style numbers under
# the official key. Real ESP-Miner GH/s readings are ~0.1 … 5e5.
_GHS_TO_HS_THRESHOLD = 1e6


def looks_like_axeos(data: object) -> bool:
    """True when a ``/api/system/info`` payload carries ESP-Miner identity.

    Fail-closed: an unrecognized 200 must fall through to Braiins/cgminer
    probes instead of being registered as a miner we cannot read.
    """
    if not isinstance(data, dict) or not data:
        return False
    return any(key in data for key in AXEOS_STRONG_MARKERS)


def finite_number(value: Any) -> float | None:
    """Parse a firmware number. ``N/A``, ``Infinity``, objects → None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in ("n/a", "na", "null", "none", "nan"):
            return None
        value = text
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    return number


def axeos_rate_to_hs(value: Any, *, camel_hashrate: bool) -> int | None:
    """Normalize one ESP-Miner hashrate reading to H/s.

    Official ``hashRate`` is GH/s. Legacy lowercase ``hashrate`` is H/s.
    A camelCase value already in H/s (>= 1e6) is left alone so historical
    fixtures keep working.
    """
    number = finite_number(value)
    if number is None:
        return None
    if number == 0:
        return 0
    if camel_hashrate and abs(number) < _GHS_TO_HS_THRESHOLD:
        return int(number * 1e9)
    return int(number)


def hashrate_hs_from_axeos(info: dict) -> int | None:
    """Current hashrate in H/s, or None when the firmware omitted it."""
    if not isinstance(info, dict):
        return None
    if info.get("hashRate") is not None:
        return axeos_rate_to_hs(info.get("hashRate"), camel_hashrate=True)
    if info.get("hashrate") is not None:
        return axeos_rate_to_hs(info.get("hashrate"), camel_hashrate=False)
    return None


def _first(info: dict, keys: Iterable[str]) -> Any:
    for key in keys:
        if key in info and info[key] not in (None, ""):
            return info[key]
    return None


def _window_hs(info: dict, *keys: str) -> int | None:
    for key in keys:
        if key not in info or info[key] is None:
            continue
        camel = key.startswith("hashRate")
        return axeos_rate_to_hs(info[key], camel_hashrate=camel)
    return None


def extract_axeos_telemetry(info: dict) -> dict:
    """Fleet-normalized telemetry from an ESP-Miner ``/api/system/info`` body.

    Missing measurements are ``None`` (or ``""`` for best_diff). Callers
    must not coerce those to 0 before persistence.
    """
    from .models import best_diff_from_value

    if not isinstance(info, dict):
        return {}

    hr = hashrate_hs_from_axeos(info)
    expected = None
    if info.get("expectedHashrate") is not None:
        expected = axeos_rate_to_hs(info.get("expectedHashrate"), camel_hashrate=True)
    elif hr is not None:
        expected = None  # never copy actual → expected

    temp = finite_number(_first(info, ("temp", "temperature")))
    tel = {
        "hashrate_hs": hr,
        "expected_hashrate": expected,
        "hashrate_1m": _window_hs(info, "hashRate_1m", "hashRate1m"),
        "hashrate_10m": _window_hs(info, "hashRate_10m", "hashRate10m"),
        "hashrate_1h": _window_hs(info, "hashRate_1h", "hashRate1hr", "hashRate1h"),
        "temperature": temp,
        "temp_asic": (
            finite_number(_first(info, ("tempChip", "temp_asic")))
            if _first(info, ("tempChip", "temp_asic")) is not None
            else temp
        ),
        "temp_vreg": finite_number(_first(info, ("vrTemp", "temp2", "temp_vreg"))),
        "fan_speed": finite_number(_first(info, ("fanspeed", "fanSpeed"))),
        "fan_rpm": finite_number(_first(info, ("fanrpm", "fanRPM"))),
        "power_watts": finite_number(info.get("power")),
        "voltage_mv": finite_number(_first(info, ("coreVoltage", "voltage"))),
        "voltage_actual_mv": finite_number(info.get("coreVoltageActual")),
        "frequency_mhz": finite_number(_first(info, ("frequency", "actualFrequency"))),
        "current_ma": finite_number(info.get("current")),
        "best_diff": best_diff_from_value(_first(info, ("bestDiff", "bestDifficulty"))),
        "best_session_diff": best_diff_from_value(
            _first(info, ("bestSessionDiff", "bestSessionDifficulty"))
        ),
        "shares_accepted": _int_or_none(info.get("sharesAccepted")),
        "shares_rejected": _int_or_none(info.get("sharesRejected")),
        "shares_stale": _int_or_none(_first(info, ("sharesStale", "staleShares"))),
        "uptime_seconds": _int_or_none(_first(info, ("uptimeSeconds", "uptime"))),
        "free_heap": _int_or_none(info.get("freeHeap")),
        "wifi_rssi": finite_number(info.get("wifiRSSI")),
        "pool_url": str(_first(info, ("stratumURL", "pool", "poolURL")) or ""),
        "pool_user": str(
            _first(info, ("stratumUser", "poolUser", "poolUsername", "worker")) or ""
        ),
        "stratum_status": str(_first(info, ("stratumStatus", "poolStatus")) or ""),
        "mining_paused": info.get("miningPaused") is True,
        "model": str(_first(info, ("model", "board", "ASICModel")) or "Bitaxe"),
        "mac": str(_first(info, ("macAddr", "mac")) or ""),
        "hostname": str(info.get("hostname") or ""),
        "firmware": str(info.get("firmware") or info.get("axeOSVersion") or ""),
        "version": str(info.get("version") or ""),
    }
    hr_hs = tel["hashrate_hs"]
    pwr = tel["power_watts"]
    if hr_hs and pwr and pwr > 0:
        tel["efficiency_jth"] = round(pwr / (hr_hs / 1e12), 2)
    accepted = tel["shares_accepted"]
    rejected = tel["shares_rejected"]
    if accepted is not None and rejected is not None:
        total = accepted + rejected
        if total > 0:
            tel["hw_error_pct"] = round(rejected / total * 100, 2)
    return tel


def _int_or_none(value: Any) -> int | None:
    number = finite_number(value)
    if number is None:
        return None
    return int(number)


def official_esp_miner_info(**overrides: Any) -> dict:
    """Canonical ESP-Miner ``/api/system/info`` body for tests and the lab.

    Numbers match the OpenAPI units (hashRate in GH/s). 4800 GH/s = 4.8 TH/s.
    """
    payload = {
        "hashRate": 4800.0,
        "hashRate_1m": 4750.0,
        "hashRate_10m": 4700.0,
        "hashRate_1h": 4600.0,
        "expectedHashrate": 5000.0,
        "temp": 58.0,
        "vrTemp": 62.0,
        "fanspeed": 80,
        "fanrpm": 4200,
        "power": 35.0,
        "coreVoltage": 1150,
        "frequency": 550,
        "uptimeSeconds": 7200,
        "bestDiff": 0,
        "bestSessionDiff": 0,
        "sharesAccepted": 42,
        "sharesRejected": 1,
        "ASICModel": "BM1370",
        "boardVersion": "401",
        "model": "NerdQaxe++",
        "hostname": "virtual-nerdqaxe",
        "macAddr": "AA:BB:CC:DD:EE:FF",
        "firmware": "AxeOS 2.4",
        "version": "2.4.0",
        "stratumURL": "solo.ckpool.org",
        "stratumPort": 3333,
        "stratumUser": "virtual.worker",
        "miningPaused": False,
    }
    payload.update(overrides)
    return payload
