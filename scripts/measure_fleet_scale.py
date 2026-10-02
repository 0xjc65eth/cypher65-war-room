#!/usr/bin/env python3
"""Local-only LOAD-001 diagnostic preparation; never a performance gate.

Example::

    python scripts/measure_fleet_scale.py --samples 25 --warmups 3

Each workload runs sequentially in a disposable subprocess with a real
SQLite registry and the authenticated Flask Fleet blueprint. Only outbound
transport is replaced with a fail-closed guard. No app.py/bootstrap workers,
miner, provider, operational database or credentials are used.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import gc
import hashlib
import http.client
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import resource
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import tracemalloc
from typing import Any, Iterator
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TENANT = "load001-synthetic"
OTHER_TENANT = "load001-other-synthetic"
HASHRATE_HS = 100_000_000_000_000
MAX_DEVICES = 500
SUMMARY_URL = "/api/axe-fleet/summary"


class MeasurementError(RuntimeError):
    """A diagnostic invariant or measurement contract failed."""


class NetworkForbidden(MeasurementError):
    """The local-only diagnostic attempted outbound transport."""


@contextmanager
def deny_network() -> Iterator[list[str]]:
    """Block HTTP, DNS and socket transports; fail even if callers swallow errors.

    Example: ``with deny_network() as attempts: run_local_diagnostic()``.
    """
    import requests

    attempts: list[str] = []

    def blocked(name: str):
        def deny(*_args, **_kwargs):
            attempts.append(name)
            raise NetworkForbidden(f"outbound transport forbidden: {name}")

        return deny

    with ExitStack() as stack:
        for owner, name in (
            (socket, "create_connection"),
            (socket, "getaddrinfo"),
            (socket.socket, "connect"),
            (socket.socket, "connect_ex"),
            (socket.socket, "sendto"),
            (http.client.HTTPConnection, "connect"),
            (urllib.request, "urlopen"),
            (requests.sessions.Session, "request"),
        ):
            stack.enter_context(patch.object(owner, name, blocked(name)))
        yield attempts
        if attempts:
            raise NetworkForbidden("outbound transport attempts were swallowed")


def percentile(values: list[float], quantile: float) -> float:
    """Nearest-rank percentile, without interpolation.

    Example: ``percentile([1.0, 2.0, 3.0], 0.95) == 3.0``.
    """
    if not values or not 0 < quantile <= 1:
        raise ValueError("nonempty samples and 0 < quantile <= 1 required")
    if any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("samples must be finite nonnegative milliseconds")
    ordered = sorted(values)
    return ordered[math.ceil(quantile * len(ordered)) - 1]


def summarize_latencies(values: list[float]) -> dict[str, Any]:
    """Preserve raw elapsed samples and explicit nearest-rank statistics.

    Example: ``summarize_latencies([1.0, 2.0])["p95_ms"] == 2.0``.
    """
    return {
        "unit": "ms",
        "samples": values,
        "n": len(values),
        "percentile_method": "nearest-rank: sorted[ceil(q*N)-1], no interpolation",
        "p50_ms": percentile(values, 0.50),
        "p95_ms": percentile(values, 0.95),
        "p99_ms": percentile(values, 0.99),
        "min_ms": min(values),
        "max_ms": max(values),
    }


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise MeasurementError(message)


def _numeric_equal(value: Any, expected: int | float | None, integer=False) -> bool:
    if expected is None:
        return value is None
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
        and (not integer or isinstance(value, int))
        and value == expected
    )


def verify_summary(
    data: dict, expected: dict, now: int, request_started_at: int | None = None
) -> None:
    """Hard-fail count, tenant, source, freshness and hash conservation errors.

    Example: ``verify_summary(response.get_json(), expected, int(time.time()))``.
    """
    rows = expected["devices"]
    actual = data.get("devices")
    _check(isinstance(actual, list), "summary devices must be a list")
    _check(len(actual) == len(rows), "summary device count mismatch")
    _check(
        _numeric_equal(data.get("total_devices"), len(rows), integer=True),
        "registered count mismatch",
    )
    _check(
        _numeric_equal(data.get("warning"), 0, integer=True),
        "unexpected warning count",
    )
    online = sum(row["status"] == "ONLINE" for row in rows.values())
    _check(
        _numeric_equal(data.get("online"), online, integer=True),
        "online count mismatch",
    )
    _check(
        _numeric_equal(data.get("offline"), len(rows) - online, integer=True),
        "offline bucket mismatch",
    )
    expected_hr = sum(row["current_hr"] or 0 for row in rows.values())
    _check(
        _numeric_equal(data.get("total_hashrate_hs"), expected_hr),
        "live hash sum mismatch",
    )
    seen: set[str] = set()
    for device in actual:
        device_id = device.get("id")
        _check(device_id in rows and device_id not in seen, "unknown/duplicate device")
        seen.add(device_id)
        row = rows[device_id]
        tel = device.get("_telemetry") or {}
        _check(device.get("tenant_id") == expected["tenant"], "tenant leaked")
        _check(
            _numeric_equal(device.get("agent_managed"), 1, integer=True),
            "fixture is not agent-managed",
        )
        _check(device.get("latency_ms") is None, "agent-managed probe was attempted")
        _check(device.get("status") == row["status"], "freshness status mismatch")
        _check(
            _numeric_equal(tel.get("hashrate_hs"), row["current_hr"]),
            "current hash mismatch",
        )
        _check(
            _numeric_equal(tel.get("ts"), row["ts"], integer=True),
            "latest sample source/time mismatch",
        )
        _check(
            _numeric_equal(tel.get("last_known_hashrate_hs"), row["last_known_hr"]),
            "stale last-known hash mismatch",
        )
        if row["ts"] is None:
            _check(
                tel.get("age_seconds") is None,
                "missing telemetry age must be unavailable",
            )
        else:
            earliest = max(
                0,
                (request_started_at if request_started_at is not None else now)
                - row["ts"],
            )
            latest = max(0, now - row["ts"])
            _check(
                isinstance(tel.get("age_seconds"), int)
                and not isinstance(tel.get("age_seconds"), bool)
                and earliest <= tel["age_seconds"] <= latest,
                "telemetry age outside real request window",
            )
    _check(seen == set(rows), "device identities did not reconcile")


def seed_workload(registry: Any, count: int, mode: str, observed_at: int) -> dict:
    """Persist synthetic fixtures through real agent registration/telemetry methods.

    Mixed cycles through fresh, stale, measured-zero and missing devices. Stored
    stale devices deliberately retain ONLINE so the summary must reconcile them.
    Example: ``seed_workload(registry, 100, "mixed", int(time.time()))``.
    """
    from axe_fleet.models import TELEMETRY_STALENESS_S

    _check(
        isinstance(count, int)
        and not isinstance(count, bool)
        and 0 < count <= MAX_DEVICES,
        "device count must be 1..500",
    )
    _check(mode in ("fresh", "stale", "mixed"), "unknown telemetry mode")
    states = ("fresh", "stale", "zero", "missing")
    rows = {}
    for index in range(count):
        state = states[index % 4] if mode == "mixed" else mode
        device = registry.upsert_agent_device(
            (
                f"192.0.2.{index % 250 + 1}"
                if index < 250
                else f"198.51.100.{index - 249}"
            ),
            f"Synthetic {index:04d}",
            tenant_id=TENANT,
            info={"type": "bitaxe", "firmware": "AxeOS", "model": "synthetic"},
        )
        _check(bool(device.get("id")), "agent registration failed")
        ts = (
            None
            if state == "missing"
            else (
                observed_at - TELEMETRY_STALENESS_S - 3600
                if state == "stale"
                else observed_at
            )
        )
        measured = 0 if state == "zero" else HASHRATE_HS
        if ts is not None:
            registry.save_agent_telemetry(
                device["id"],
                {
                    "ts": ts,
                    "hashrate_hs": measured,
                    "temperature": 60,
                    "power_watts": 1500,
                    "uptime_seconds": 86400,
                },
                tenant_id=TENANT,
                idempotency_key=f"seed-{index}",
            )
        if state == "stale":
            registry.update_device(device["id"], {"status": "ONLINE"}, tenant_id=TENANT)
        rows[device["id"]] = {
            "status": {
                "fresh": "ONLINE",
                "stale": "STALE",
                "zero": "IDLE",
                "missing": "OFFLINE",
            }[state],
            "ts": ts,
            "current_hr": (
                None if state == "missing" else (HASHRATE_HS if state == "fresh" else 0)
            ),
            "last_known_hr": HASHRATE_HS if state == "stale" else None,
        }
    sentinel = registry.upsert_agent_device(
        "203.0.113.1", "Other tenant sentinel", tenant_id=OTHER_TENANT
    )
    registry.save_agent_telemetry(
        sentinel["id"],
        {"ts": observed_at, "hashrate_hs": HASHRATE_HS * 2},
        tenant_id=OTHER_TENANT,
    )
    return {
        "tenant": TENANT,
        "devices": rows,
        "other_tenant_sentinel_count": 1,
        "other_tenant_expected": {
            "tenant": OTHER_TENANT,
            "devices": {
                sentinel["id"]: {
                    "status": "ONLINE",
                    "ts": observed_at,
                    "current_hr": HASHRATE_HS * 2,
                    "last_known_hr": None,
                }
            },
        },
        "staleness_horizon_s": TELEMETRY_STALENESS_S,
    }


def _logical_db_hash(connect) -> str:
    connection = connect()
    try:
        return hashlib.sha256("\n".join(connection.iterdump()).encode()).hexdigest()
    finally:
        connection.close()


def process_peak_rss() -> dict:
    """Report the process lifetime RSS high-water, not current/fleet memory.

    Example: ``process_peak_rss()["unit"] == "bytes"`` on Linux/macOS.
    """
    native = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    multiplier = (
        1
        if sys.platform == "darwin"
        else 1024 if sys.platform.startswith("linux") else None
    )
    return {
        "method": "resource.getrusage(RUSAGE_SELF).ru_maxrss",
        "native_value": native,
        "native_unit": (
            "bytes"
            if sys.platform == "darwin"
            else "KiB" if multiplier else "platform-dependent"
        ),
        "bytes": native * multiplier if multiplier else None,
        "unit": "bytes" if multiplier else "unknown",
        "scope": "worker-process RSS high-water at capture; imports, fixture setup, latency and separate allocation runs included; not current RSS or fleet memory",
    }


def run_workload(
    count: int, mode: str, warmups: int, samples: int, memory_samples: int
) -> dict:
    """Measure actual buffered authenticated GETs with an isolated SQLite store.

    Latency excludes JSON decoding/invariant checks and tracemalloc. Memory is
    a separate instrumented sequence, never added to process RSS.
    Example: ``run_workload(100, "fresh", 3, 25, 3)``.
    """
    _check(
        all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in (warmups, samples, memory_samples)
        )
        and 0 <= warmups <= 20
        and 1 <= samples <= 100
        and 1 <= memory_samples <= 10,
        "warmups/samples/memory-samples out of bounds",
    )
    _check(not tracemalloc.is_tracing(), "latency must run without tracemalloc")
    started = datetime.now(timezone.utc).isoformat()
    with tempfile.TemporaryDirectory(prefix="cypher65-load001-") as scratch:
        db_path = str(Path(scratch) / "fleet.sqlite3")
        environment = {
            "DB_PATH": db_path,
            "API_KEY": secrets.token_hex(32),
            "TENANT_API_KEYS": "",
            "REVOKED_TOKENS_DB": "0",
            "SECRET_KEY": secrets.token_hex(32),
            "PYTHON_DOTENV_DISABLED": "1",
        }
        with patch.dict(os.environ, environment), deny_network() as attempts:
            from flask import Flask
            from axe_fleet.registry import DeviceRegistry
            from axe_fleet import routes
            from services.auth import create_token

            def connect():
                connection = sqlite3.connect(db_path)
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA synchronous=NORMAL")
                connection.execute("PRAGMA busy_timeout=3000")
                return connection

            registry = DeviceRegistry(connect)
            registry.ensure_tables()
            observed_at = int(time.time())
            expected = seed_workload(registry, count, mode, observed_at)
            persisted = _logical_db_hash(connect)
            flask_app = Flask("load001_diagnostic")
            flask_app.config.update(
                TESTING=True,
                SECRET_KEY=environment["SECRET_KEY"],
                JWT_SECRET_KEY=environment["SECRET_KEY"],
            )
            flask_app.register_blueprint(
                routes.axe_fleet_bp, url_prefix="/api/axe-fleet"
            )
            previous_registry = routes._registry
            routes.init_routes(registry)
            try:
                with flask_app.app_context():
                    token = create_token(TENANT, extra_claims={"role": "viewer"})
                    other_token = create_token(
                        OTHER_TENANT, extra_claims={"role": "viewer"}
                    )
                headers = {"Authorization": f"Bearer {token}"}
                client = flask_app.test_client()
                remote = {"REMOTE_ADDR": "203.0.113.2"}
                _check(
                    client.get(SUMMARY_URL, environ_overrides=remote).status_code
                    == 403,
                    "anonymous caller was not blocked",
                )
                other_start = int(time.time())
                other_response = client.get(
                    SUMMARY_URL,
                    headers={"Authorization": f"Bearer {other_token}"},
                    buffered=True,
                    environ_overrides=remote,
                )
                _check(other_response.status_code == 200, "other tenant request failed")
                verify_summary(
                    other_response.get_json(),
                    expected["other_tenant_expected"],
                    int(time.time()),
                    other_start,
                )
                other_response.close()

                def request_once() -> tuple[float, int]:
                    request_started_at = int(time.time())
                    before = time.perf_counter_ns()
                    response = client.get(
                        SUMMARY_URL,
                        headers=headers,
                        buffered=True,
                        environ_overrides=remote,
                    )
                    elapsed_ms = (time.perf_counter_ns() - before) / 1_000_000
                    _check(
                        response.status_code == 200,
                        "summary request did not return 200",
                    )
                    verify_summary(
                        response.get_json(),
                        expected,
                        int(time.time()),
                        request_started_at,
                    )
                    response.close()
                    return elapsed_ms, len(response.data)

                for _ in range(warmups):
                    request_once()
                latencies = []
                payload_bytes = 0
                for _ in range(samples):
                    elapsed_ms, payload_bytes = request_once()
                    latencies.append(elapsed_ms)
                gc.collect()
                memory = []
                tracemalloc.start()
                try:
                    for _ in range(memory_samples):
                        gc.collect()
                        before_bytes, _ = tracemalloc.get_traced_memory()
                        tracemalloc.reset_peak()
                        request_once()  # duration intentionally discarded
                        current_bytes, peak_bytes = tracemalloc.get_traced_memory()
                        memory.append(
                            {
                                "before_bytes": before_bytes,
                                "current_bytes": current_bytes,
                                "peak_bytes": peak_bytes,
                                "incremental_peak_bytes": max(
                                    0, peak_bytes - before_bytes
                                ),
                            }
                        )
                finally:
                    tracemalloc.stop()
                _check(
                    _logical_db_hash(connect) == persisted,
                    "summary mutated the fixture store",
                )
                _check(not attempts, "transport guard was called")
                statuses = {
                    status: sum(
                        row["status"] == status for row in expected["devices"].values()
                    )
                    for status in ("ONLINE", "STALE", "IDLE", "OFFLINE")
                }
                result = {
                    "kind": "diagnostic_measurement_not_acceptance_gate",
                    "load": {
                        "agent_managed_devices": count,
                        "telemetry_mode": mode,
                        "synthetic": True,
                        "tenant_count": 2,
                        "other_tenant_sentinel_devices": 1,
                        "telemetry_observed_at": observed_at,
                        "staleness_horizon_s": expected["staleness_horizon_s"],
                        "statuses": statuses,
                    },
                    "started_at_utc": started,
                    "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                    "warmups": warmups,
                    "latency": summarize_latencies(latencies),
                    "response_bytes_last_sample": payload_bytes,
                    "python_allocations": {
                        "method": "tracemalloc; separate instrumented requests after latency",
                        "scope": "Python-tracked request allocations, including JSON decode/invariant check; excludes SQLite/C allocations and fixture setup; not RSS",
                        "samples": memory,
                    },
                    "process_peak_rss": process_peak_rss(),
                    "invariants": {
                        "tenant_count_hash_stale_latest": True,
                        "store_unchanged": True,
                        "other_tenant_summary_isolated": True,
                        "anonymous_caller_blocked": True,
                        "fixture_store_sha256": persisted,
                        "outbound_transport_attempts": len(attempts),
                    },
                }
                return result
            finally:
                routes.init_routes(previous_registry)


def source_metadata() -> dict:
    """Identify the checkout and exact production inputs without network access.

    Example: ``source_metadata()["measured_file_sha256"]``.
    """
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    )
    paths = (
        "scripts/measure_fleet_scale.py",
        "axe_fleet/registry.py",
        "axe_fleet/routes.py",
        "axe_fleet/models.py",
        "core/models/device.py",
        "services/tenant.py",
        "services/auth.py",
    )
    return {
        "git_head": revision,
        "working_tree_dirty": dirty,
        "measured_file_sha256": {
            path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            for path in paths
        },
    }


def _bounded(low: int, high: int):
    def parse(value: str) -> int:
        try:
            number = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError("integer required") from exc
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f"must be {low}..{high}")
        return number

    return parse


def _worker_failure(worker: subprocess.CompletedProcess) -> str:
    detail = worker.stdout.strip() or "\n".join(worker.stderr.splitlines()[-3:])
    detail = re.sub(r"(?i)(bearer\s+)\S+", r"\1[redacted]", detail)
    detail = re.sub(
        r"(?i)(SECRET_KEY|API_KEY|Authorization)[^\n]*", r"\1=[redacted]", detail
    )
    return f"diagnostic worker exit {worker.returncode}: {detail[:500]}"


def main(argv: list[str] | None = None) -> int:
    """Emit diagnostic JSON; exit nonzero only for usage/safety/invariant errors.

    Example: ``main(["--devices", "100", "--samples", "5"])``.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--devices", nargs="+", type=int, choices=(100, 500), default=[100, 500]
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=("fresh", "stale", "mixed"),
        default=["fresh", "stale", "mixed"],
    )
    parser.add_argument("--warmups", type=_bounded(0, 20), default=3)
    parser.add_argument("--samples", type=_bounded(1, 100), default=25)
    parser.add_argument("--memory-samples", type=_bounded(1, 10), default=3)
    parser.add_argument(
        "--output",
        type=Path,
        help="also create a new JSON artifact (refuses overwrite)",
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        _check(
            not args.output or not args.output.exists(),
            "output artifact already exists; refusing overwrite",
        )
        if args.worker:
            _check(
                len(args.devices) == len(args.modes) == 1,
                "worker requires one workload",
            )
            report = run_workload(
                args.devices[0],
                args.modes[0],
                args.warmups,
                args.samples,
                args.memory_samples,
            )
        else:
            cases = []
            for count in dict.fromkeys(args.devices):
                for mode in dict.fromkeys(args.modes):
                    safe_env = {
                        key: os.environ[key]
                        for key in ("PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT")
                        if key in os.environ
                    }
                    safe_env["PYTHON_DOTENV_DISABLED"] = "1"
                    command = [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "--worker",
                        "--devices",
                        str(count),
                        "--modes",
                        mode,
                        "--warmups",
                        str(args.warmups),
                        "--samples",
                        str(args.samples),
                        "--memory-samples",
                        str(args.memory_samples),
                    ]
                    worker = subprocess.run(
                        command,
                        cwd=ROOT,
                        env=safe_env,
                        capture_output=True,
                        text=True,
                        timeout=300,
                    )
                    _check(
                        worker.returncode == 0,
                        _worker_failure(worker),
                    )
                    cases.append(json.loads(worker.stdout))
            report = {
                "requirement": "LOAD-001",
                "issue": 606,
                "status": "diagnostic_only_acceptance_blocked_unapproved_slo",
                "approved_thresholds": None,
                "source": source_metadata(),
                "environment": {
                    "platform": platform.platform(),
                    "machine": platform.machine(),
                    "cpu_count": os.cpu_count(),
                    "python": platform.python_version(),
                    "sqlite": sqlite3.sqlite_version,
                    "flask": importlib.metadata.version("flask"),
                },
                "method": {
                    "endpoint": SUMMARY_URL,
                    "client": "in-process Flask test client; real blueprint/JWT tenant+viewer RBAC",
                    "latency_scope": "buffered GET with auth, registry SQLite reads and JSON serialization; no TCP, app middleware, background poll, JSON decode or invariant check",
                    "database": "fresh temporary file per worker; real registry, WAL/synchronous=NORMAL/busy_timeout=3000; 1 measurement per measured device",
                    "auth": "synthetic transient viewer JWT, API-key auth enabled; revocation persistence disabled",
                    "isolation": "sequential disposable worker per workload; transport-only fail-closed mocks, asserted unused",
                    "clock": "unmocked perf_counter_ns; telemetry timestamps generated from real wall clock",
                    "limitations": [
                        "synthetic agent-managed fleet only; no self-host miner-probe cost",
                        "single-process sequential warm-cache latency, not throughput or concurrency",
                        "process peak RSS and Python allocations are distinct and must not be added",
                        "mixed offline bucket includes IDLE according to current summary schema",
                        "small-sample p99 nearest-rank can equal maximum; repeat on target deployment before SLO approval",
                    ],
                },
                "cases": cases,
            }
        encoded = json.dumps(report, indent=2, allow_nan=False) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as artifact:
                artifact.write(encoded)
        sys.stdout.write(encoded)
        return 0
    except (MeasurementError, ValueError, OSError, subprocess.SubprocessError) as exc:
        sys.stdout.write(
            json.dumps(
                {"status": "diagnostic_error", "error": str(exc)}, allow_nan=False
            )
            + "\n"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
