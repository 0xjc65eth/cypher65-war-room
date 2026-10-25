"""Fast diagnostic-contract tests for #606, not LOAD-001 performance acceptance.

The real route/SQLite tiny workloads prevent invented numbers, network commands,
tenant leakage and persistence mutations. No elapsed-time threshold is imposed.
"""

from copy import deepcopy
from contextlib import closing
import http.client
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import tracemalloc
import urllib.request

import pytest
import requests

from scripts import measure_fleet_scale as measurement


@pytest.mark.parametrize(
    "quantile,expected", [(0.5, 10), (0.95, 19), (0.99, 20), (1, 20)]
)
def test_nearest_rank_percentiles(quantile, expected):
    values = list(range(20, 0, -1))
    assert measurement.percentile(values, quantile) == expected
    assert values == list(range(20, 0, -1))


@pytest.mark.parametrize(
    "values,quantile",
    [
        ([], 0.5),
        ([1], 0),
        ([1], 1.1),
        ([float("nan")], 0.5),
        ([float("inf")], 0.5),
        ([-1], 0.5),
    ],
)
def test_invalid_percentiles_fail(values, quantile):
    with pytest.raises(ValueError):
        measurement.percentile(values, quantile)


def test_raw_samples_preserved_and_small_sample_p99_is_max():
    result = measurement.summarize_latencies([2.0, 0.0, 1.0])
    assert result["samples"] == [2.0, 0.0, 1.0]
    assert result["n"] == 3
    assert result["p50_ms"] == 1
    assert result["p99_ms"] == result["max_ms"] == 2


@pytest.mark.parametrize("mode", ["fresh", "stale", "mixed"])
def test_actual_registry_auth_summary_and_store_invariants(mode):
    from axe_fleet import routes

    previous_registry = routes._registry
    previous_environment = {
        key: os.environ.get(key) for key in ("DB_PATH", "API_KEY", "SECRET_KEY")
    }
    result = measurement.run_workload(4, mode, warmups=1, samples=2, memory_samples=1)
    assert routes._registry is previous_registry
    assert {
        key: os.environ.get(key) for key in previous_environment
    } == previous_environment
    assert not tracemalloc.is_tracing()
    assert result["kind"] == "diagnostic_measurement_not_acceptance_gate"
    assert result["latency"]["n"] == 2
    assert all(value >= 0 for value in result["latency"]["samples"])
    assert result["invariants"]["outbound_transport_attempts"] == 0
    assert result["invariants"]["store_unchanged"] is True
    assert result["invariants"]["other_tenant_summary_isolated"] is True
    assert result["invariants"]["anonymous_caller_blocked"] is True
    if mode == "mixed":
        assert result["load"]["statuses"] == {
            "ONLINE": 1,
            "STALE": 1,
            "IDLE": 1,
            "OFFLINE": 1,
        }
    assert result["process_peak_rss"]["native_value"] > 0
    assert "not RSS" in result["python_allocations"]["scope"]


@pytest.mark.parametrize(
    "case",
    ["dns", "connect", "connect_ex", "sendto", "http", "urllib", "requests", "socket"],
)
def test_transport_guards_fail_closed_and_restore(case):
    original_connect = socket.socket.connect
    with pytest.raises(measurement.NetworkForbidden):
        with measurement.deny_network() as attempts:
            if case == "dns":
                socket.getaddrinfo("example.invalid", 80)
            elif case in ("connect", "connect_ex", "sendto"):
                with socket.socket() as connection:
                    if case == "sendto":
                        connection.sendto(b"diagnostic", ("192.0.2.1", 80))
                    else:
                        getattr(connection, case)(("192.0.2.1", 80))
            elif case == "http":
                http.client.HTTPConnection("example.invalid").connect()
            elif case == "urllib":
                # Fixed HTTP URL; transport is denied above, never contacted.
                urllib.request.urlopen(
                    "http://example.invalid", timeout=1
                )  # nosec B310
            elif case == "requests":
                requests.get("http://example.invalid", timeout=1)
            else:
                socket.create_connection(("192.0.2.1", 80), timeout=1)
    assert len(attempts) == 1
    assert socket.socket.connect is original_connect


def test_swallowed_network_error_still_invalidates_measurement():
    with pytest.raises(measurement.NetworkForbidden, match="swallowed"):
        with measurement.deny_network():
            try:
                socket.create_connection(("192.0.2.1", 80), timeout=1)
            except measurement.NetworkForbidden:
                pass  # Deliberately exercise a production-style swallowed transport error.


def _valid_summary():
    rows = {
        "fresh": {
            "status": "ONLINE",
            "current_hr": 100,
            "last_known_hr": None,
            "ts": 1000,
        },
        "stale": {"status": "STALE", "current_hr": 0, "last_known_hr": 100, "ts": 1},
    }
    expected = {"tenant": measurement.TENANT, "devices": rows}
    actual = {
        "total_devices": 2,
        "online": 1,
        "warning": 0,
        "offline": 1,
        "total_hashrate_hs": 100,
        "devices": [
            {
                "id": device_id,
                "tenant_id": measurement.TENANT,
                "agent_managed": 1,
                "latency_ms": None,
                "status": row["status"],
                "_telemetry": {
                    "hashrate_hs": row["current_hr"],
                    "last_known_hashrate_hs": row["last_known_hr"],
                    "ts": row["ts"],
                    "age_seconds": 1000 - row["ts"],
                },
            }
            for device_id, row in rows.items()
        ],
    }
    return actual, expected


@pytest.mark.parametrize(
    "field,value",
    [
        ("devices", None),
        ("total_devices", 3),
        ("warning", 1),
        ("online", 2),
        ("offline", 0),
        ("total_hashrate_hs", 200),
        ("total_devices", 2.0),
        ("warning", False),
        ("online", True),
        ("offline", True),
        ("total_hashrate_hs", float("nan")),
        ("total_hashrate_hs", float("inf")),
    ],
)
def test_summary_count_and_hash_corruption_hard_fails(field, value):
    actual, expected = _valid_summary()
    measurement.verify_summary(actual, expected, 1000)
    actual[field] = value
    with pytest.raises(measurement.MeasurementError):
        measurement.verify_summary(actual, expected, 1000)


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "outside"),
        ("tenant_id", "other"),
        ("agent_managed", 0),
        ("agent_managed", True),
        ("latency_ms", 5),
        ("status", "ONLINE"),
    ],
)
def test_device_identity_tenant_and_stale_corruption_hard_fails(field, value):
    actual, expected = _valid_summary()
    actual["devices"][1][field] = value
    with pytest.raises(measurement.MeasurementError):
        measurement.verify_summary(actual, expected, 1000)


@pytest.mark.parametrize(
    "field,value",
    [
        ("hashrate_hs", 100),
        ("last_known_hashrate_hs", None),
        ("ts", 1000),
        ("age_seconds", 0),
        ("hashrate_hs", False),
        ("hashrate_hs", float("nan")),
        ("last_known_hashrate_hs", float("inf")),
        ("ts", True),
    ],
)
def test_latest_sample_provenance_and_age_corruption_hard_fails(field, value):
    actual, expected = _valid_summary()
    actual["devices"][1]["_telemetry"][field] = value
    with pytest.raises(measurement.MeasurementError):
        measurement.verify_summary(actual, expected, 1000)


def test_duplicate_device_hard_fails():
    actual, expected = _valid_summary()
    actual["devices"][1] = deepcopy(actual["devices"][0])
    with pytest.raises(measurement.MeasurementError, match="duplicate"):
        measurement.verify_summary(actual, expected, 1000)


def test_boolean_age_is_not_a_valid_zero_age():
    actual, expected = _valid_summary()
    actual["devices"][0]["_telemetry"]["age_seconds"] = False
    with pytest.raises(measurement.MeasurementError, match="age"):
        measurement.verify_summary(actual, expected, 1000)


@pytest.fixture
def registry(tmp_path):
    from axe_fleet.registry import DeviceRegistry

    db = tmp_path / "fleet.sqlite3"

    def connect():
        connection = sqlite3.connect(db)
        connection.row_factory = sqlite3.Row
        return connection

    instance = DeviceRegistry(connect)
    instance.ensure_tables()
    return instance, connect


def test_seed_replay_conflict_and_late_equal_samples_do_not_inflate_hash(registry):
    from axe_fleet.registry import TelemetryIdempotencyConflict

    instance, connect = registry
    now = int(time.time())
    with measurement.deny_network():
        expected = measurement.seed_workload(instance, 1, "fresh", now)
        device_id = next(iter(expected["devices"]))
        original = instance.get_recent_telemetry(
            device_id, tenant_id=measurement.TENANT
        )[0]["payload"]
        instance.save_agent_telemetry(
            device_id, original, tenant_id=measurement.TENANT, idempotency_key="seed-0"
        )
        with pytest.raises(TelemetryIdempotencyConflict):
            instance.save_agent_telemetry(
                device_id,
                {**original, "hashrate_hs": 200},
                tenant_id=measurement.TENANT,
                idempotency_key="seed-0",
            )
        with closing(connect()) as connection:
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM axe_telemetry WHERE tenant_id=?",
                    (measurement.TENANT,),
                ).fetchone()[0]
                == 1
            )
        for key, ts in (("equal", now), ("late", now - 1)):
            instance.save_agent_telemetry(
                device_id,
                {**original, "ts": ts},
                tenant_id=measurement.TENANT,
                idempotency_key=key,
            )
        device = instance.list_devices(
            tenant_id=measurement.TENANT, with_telemetry=True
        )[0]
        assert device["telemetry"]["ts"] == now
        assert device["hashrate_hs"] == measurement.HASHRATE_HS


@pytest.mark.parametrize(
    "count,mode", [(0, "fresh"), (501, "fresh"), (True, "fresh"), (1, "invalid")]
)
def test_invalid_fixture_load_rejected(registry, count, mode):
    with pytest.raises(measurement.MeasurementError):
        measurement.seed_workload(registry[0], count, mode, int(time.time()))


def test_failure_restores_registry_environment_and_tracemalloc(monkeypatch):
    from axe_fleet import routes

    previous_registry = routes._registry
    previous_db = os.environ.get("DB_PATH")

    def corrupt(*_args, **_kwargs):
        raise measurement.MeasurementError("injected invariant failure")

    monkeypatch.setattr(measurement, "verify_summary", corrupt)
    with pytest.raises(measurement.MeasurementError, match="injected"):
        measurement.run_workload(1, "fresh", 0, 1, 1)
    assert routes._registry is previous_registry
    assert os.environ.get("DB_PATH") == previous_db
    assert not tracemalloc.is_tracing()


def test_latency_refuses_tracemalloc():
    tracemalloc.start()
    try:
        with pytest.raises(measurement.MeasurementError, match="without tracemalloc"):
            measurement.run_workload(1, "fresh", 0, 1, 1)
    finally:
        tracemalloc.stop()


@pytest.mark.parametrize(
    "warmups,samples,memory",
    [
        (-1, 1, 1),
        (21, 1, 1),
        (0, 0, 1),
        (0, 101, 1),
        (0, 1, 0),
        (0, 1, 11),
        (False, 1, 1),
        (0, True, 1),
        (0, 1, True),
        (0, float("nan"), 1),
        (0, 1, float("inf")),
    ],
)
def test_invalid_measurement_bounds_fail(warmups, samples, memory):
    with pytest.raises(measurement.MeasurementError, match="out of bounds"):
        measurement.run_workload(1, "fresh", warmups, samples, memory)


def test_cli_real_worker_json_and_exclusive_artifact(tmp_path, capsys):
    output = tmp_path / "diagnostic.json"
    args = [
        "--devices",
        "100",
        "--modes",
        "fresh",
        "--warmups",
        "0",
        "--samples",
        "1",
        "--memory-samples",
        "1",
        "--output",
        str(output),
    ]
    assert measurement.main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert json.loads(output.read_text()) == result
    assert result["approved_thresholds"] is None
    assert result["cases"][0]["load"]["agent_managed_devices"] == 100
    assert len(result["source"]["git_head"]) == 40
    assert result["environment"]["sqlite"] == sqlite3.sqlite_version
    assert measurement.main(args) == 1
    assert "refusing overwrite" in capsys.readouterr().out
    assert json.loads(output.read_text()) == result


def test_worker_cli_and_argument_errors(capsys):
    # --worker is an internal subprocess entry point. The production launcher
    # isolates it from app/bootstrap workers; keep that isolation in the suite
    # so its global transport guard cannot intercept another test's threads.
    worker = subprocess.run(
        [
            sys.executable,
            str(measurement.ROOT / "scripts" / "measure_fleet_scale.py"),
            "--worker",
            "--devices",
            "100",
            "--modes",
            "stale",
            "--warmups",
            "0",
            "--samples",
            "1",
            "--memory-samples",
            "1",
        ],
        cwd=measurement.ROOT,
        env={
            key: os.environ[key]
            for key in ("PATH", "LANG", "LC_ALL", "TMPDIR")
            if key in os.environ
        }
        | {"PYTHON_DOTENV_DISABLED": "1"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert worker.returncode == 0, worker.stdout + worker.stderr
    result = json.loads(worker.stdout)
    assert result["load"]["telemetry_mode"] == "stale"
    assert result["invariants"]["outbound_transport_attempts"] == 0
    assert result["invariants"]["store_unchanged"] is True
    assert measurement.main(["--worker", "--devices", "100", "500"]) == 1
    assert "one workload" in capsys.readouterr().out
    for args in (["--samples", "101"], ["--samples", "wrong"], ["--devices", "1"]):
        with pytest.raises(SystemExit) as caught:
            measurement.main(args)
        assert caught.value.code == 2


def test_rss_native_units_described():
    result = measurement.process_peak_rss()
    assert result["native_value"] > 0
    assert "not current RSS or fleet memory" in result["scope"]
    assert result["native_unit"] in ("bytes", "KiB", "platform-dependent")


def test_cli_worker_failure_is_actionable_and_redacted(monkeypatch, capsys):
    failure = subprocess.CompletedProcess(
        [],
        7,
        stdout="",
        stderr="RuntimeError: transport failed\nAPI_KEY=sensitive-test-value",
    )
    monkeypatch.setattr(
        measurement.subprocess, "run", lambda *_args, **_kwargs: failure
    )
    assert (
        measurement.main(["--devices", "100", "--modes", "fresh", "--samples", "1"])
        == 1
    )
    text = capsys.readouterr().out
    assert "exit 7" in text and "transport failed" in text
    assert "sensitive-test-value" not in text and "redacted" in text
    assert "opaque" not in measurement._worker_failure(
        subprocess.CompletedProcess([], 1, stdout="Bearer opaque", stderr="")
    )
