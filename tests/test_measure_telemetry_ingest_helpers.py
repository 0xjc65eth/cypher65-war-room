"""Fast contract tests for deterministic LOAD-002 harness workload helpers."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
import sys
import tempfile
import time
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "measure_telemetry_ingest.py"
SPEC = importlib.util.spec_from_file_location("measure_telemetry_ingest", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
HARNESS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = HARNESS
SPEC.loader.exec_module(HARNESS)
SMALL_WORKLOAD = HARNESS.Workload(
    device_count=2,
    unique_per_device=6,
    replay_per_device=2,
    conflict_per_device=1,
    tenant_probes_per_device=1,
    queue_capacity_per_device=1,
    late_arrival_sequence=4,
)


@contextmanager
def isolated_runtime(temporary: Path):
    """Yield a guarded minimal Flask app while restoring process/global state."""
    secret = secrets.token_urlsafe(32)
    env = {
        "DB_PATH": str(temporary / "bootstrap.sqlite3"),
        "SECRET_KEY": secret,
        "JWT_SECRET_KEY": secret,
        "SENTRY_DSN": "",
        "REVOKED_TOKENS_DB": "0",
    }

    def blocked(*_args, **_kwargs):
        raise AssertionError("test contract must not use external transport")

    with patch.dict(os.environ, env):
        with patch.object(socket.socket, "connect", blocked), patch.object(
            socket.socket, "connect_ex", blocked
        ), patch("socket.create_connection", blocked):
            app, routes, registry_type, create_token = HARNESS._prepare_app(secret)
            previous_registry = routes._registry
            try:
                with patch.object(routes, "AxeOSConnector", side_effect=blocked):
                    yield app, routes, registry_type, create_token
            finally:
                routes._registry = previous_registry


def test_percentiles_use_nearest_rank_and_empty_is_none() -> None:
    assert HARNESS._percentile([], 0.95) is None
    assert HARNESS._percentile([1.0, 2.0, 3.0, 4.0], 0.50) == 2.0
    assert HARNESS._percentile([1.0, 2.0, 3.0, 4.0], 0.95) == 4.0


def test_latency_summary_uses_milliseconds_and_empty_shape() -> None:
    assert HARNESS._latency_summary([]) == {
        "count": 0,
        "p50_ms": None,
        "p95_ms": None,
        "p99_ms": None,
        "max_ms": None,
    }
    result = HARNESS._latency_summary([1_000_000, 4_000_000])
    assert result == {
        "count": 2,
        "p50_ms": 1.0,
        "p95_ms": 4.0,
        "p99_ms": 4.0,
        "max_ms": 4.0,
    }


def test_workload_composition_is_exact_and_semantics_are_distinct() -> None:
    base = 1_800_000_000
    ops = HARNESS._make_operations(0, 2, base, HARNESS.FULL_WORKLOAD)
    assert len(ops) == HARNESS.FULL_WORKLOAD.submissions_per_device == 200
    counts = {
        kind: sum(op["kind"] == kind for op in ops)
        for kind in HARNESS.FULL_WORKLOAD.expected
    }
    assert counts == {"unique": 160, "replay": 36, "conflict": 2, "tenant_probe": 2}
    assert (
        sum(HARNESS.FULL_WORKLOAD.counts.values())
        == HARNESS.FULL_WORKLOAD.total_submissions
    )

    originals = {
        op["event"]["idempotency_key"]: op["event"]
        for op in ops
        if op["kind"] == "unique"
    }
    replay = next(op for op in ops if op["kind"] == "replay")
    assert replay["event"] == originals[replay["event"]["idempotency_key"]]
    conflict = next(op for op in ops if op["kind"] == "conflict")
    original = originals[conflict["event"]["idempotency_key"]]
    assert (
        conflict["event"]["telemetry"]["hashrate_hs"]
        == original["telemetry"]["hashrate_hs"] + 1
    )
    probe = next(op for op in ops if op["kind"] == "tenant_probe")
    assert probe["tenant"] == HARNESS.TENANT_B
    assert probe["event"] == originals[probe["event"]["idempotency_key"]]


def test_timestamp_late_arrival_is_current_derived_and_latest_stays_latest() -> None:
    now = 1_800_000_000
    base = now - HARNESS.FULL_WORKLOAD.unique_per_device - 2
    values = [
        HARNESS._sample_ts(base, i, HARNESS.FULL_WORKLOAD.late_arrival_sequence)
        for i in range(HARNESS.FULL_WORKLOAD.unique_per_device)
    ]
    assert values[158] == base - 1
    assert values[159] == now - 3
    assert max(values) == values[159] < now
    assert values[158] < values[157] < values[159]


def test_real_blueprint_and_sqlite_idempotency_contract_without_app_bootstrap() -> None:
    """Exercise a tiny real HTTP-handler contract without production app globals."""
    with tempfile.TemporaryDirectory(prefix="load002-fast-contract-") as temporary:
        secret = secrets.token_urlsafe(32)
        env = {
            "DB_PATH": str(Path(temporary) / "bootstrap.sqlite3"),
            "SECRET_KEY": secret,
            "JWT_SECRET_KEY": secret,
            "SENTRY_DSN": "",
            "REVOKED_TOKENS_DB": "0",
        }

        def blocked(*_args, **_kwargs):
            raise AssertionError("test contract must not use external transport")

        with patch.dict(os.environ, env):
            with patch.object(socket.socket, "connect", blocked), patch.object(
                socket.socket, "connect_ex", blocked
            ), patch("socket.create_connection", blocked):
                app, routes, registry_type, create_token = HARNESS._prepare_app(secret)
                previous_registry = routes._registry
                previous_connector = routes.AxeOSConnector
                try:
                    routes.AxeOSConnector = blocked
                    database = Path(temporary) / "telemetry.sqlite3"
                    registry, get_db = HARNESS._new_registry(registry_type, database)
                    routes.init_routes(registry)
                    first_device = registry.upsert_agent_device(
                        "192.0.2.9", tenant_id="tenant-a"
                    )
                    second_device = registry.upsert_agent_device(
                        "192.0.2.9", tenant_id="tenant-b"
                    )
                    assert first_device and second_device
                    with app.app_context():
                        tokens = {
                            tenant: create_token(
                                subject=tenant,
                                ttl=300,
                                extra_claims={"agent": True, "role": "agent"},
                            )
                            for tenant in ("tenant-a", "tenant-b")
                        }
                    sample = {
                        "ip": "192.0.2.9",
                        "idempotency_key": "load002-fast-event-01",
                        "telemetry": {
                            "ts": int(time.time()),
                            "hashrate_hs": 5_000_000_000_000,
                        },
                    }
                    with app.test_client() as client:

                        def post(tenant: str, event: dict) -> int:
                            return client.post(
                                "/api/agent/telemetry",
                                headers={"Authorization": f"Bearer {tokens[tenant]}"},
                                json=event,
                            ).status_code

                        assert post("tenant-a", sample) == 200
                        assert post("tenant-a", sample) == 200
                        changed = {
                            **sample,
                            "telemetry": {
                                **sample["telemetry"],
                                "hashrate_hs": 5_000_000_000_001,
                            },
                        }
                        assert post("tenant-a", changed) == 409
                        assert post("tenant-b", sample) == 200
                    conn = get_db()
                    try:
                        assert (
                            conn.execute(
                                "SELECT COUNT(*) FROM axe_telemetry"
                            ).fetchone()[0]
                            == 2
                        )
                        assert (
                            conn.execute(
                                "SELECT COUNT(*) FROM axe_telemetry WHERE tenant_id='tenant-a'"
                            ).fetchone()[0]
                            == 1
                        )
                    finally:
                        conn.close()
                finally:
                    routes._registry = previous_registry
                    routes.AxeOSConnector = previous_connector


def test_tiny_real_queue_worker_run_reconciles_and_emits_full_exclusive_artifact(
    tmp_path: Path, capsys
) -> None:
    destination = tmp_path / "diagnostic.json"
    args = SimpleNamespace(runs=1, max_wall_seconds=30, output=destination)
    result = HARNESS._run(args, SMALL_WORKLOAD)
    stdout_artifact = json.loads(capsys.readouterr().out)
    assert result["integrity_status"] == "PASS"
    assert stdout_artifact == result
    assert json.loads(destination.read_text(encoding="utf-8")) == result
    run = result["runs"][0]
    assert run["submitted"] == 20
    assert run["admitted"] == run["sent"] == run["completed"] == 20
    assert run["accepted_new_observed_by_declared_kind"] == 14
    assert run["replayed_observed_by_declared_kind"] == 4
    assert run["rejected_conflict_observed"] == 2
    assert run["persisted"] == 14
    assert run["persisted_by_tenant"] == {"load002-alpha": 12, "load002-beta": 2}
    assert run["distinct_worker_clients"] == 2
    assert run["invariant_checks"]["queue_bound_respected"]
    assert run["invariant_checks"]["active_handler_bound_respected"]
    assert result["source_provenance"]["git_dirty"]
    assert (
        "scripts/measure_telemetry_ingest.py"
        in result["source_provenance"]["input_sha256"]
    )
    assert not result["slo"]["approved"]
    assert destination.exists()
    try:
        HARNESS._run(args, SMALL_WORKLOAD)
    except FileExistsError:
        pass
    else:
        raise AssertionError("diagnostic artifact writer overwrote an existing path")


def test_producer_abort_drains_admitted_request_and_deadline_cleanup_is_bounded(
    tmp_path: Path,
) -> None:
    with isolated_runtime(tmp_path) as (app, routes, registry_type, create_token):
        partial_dir = tmp_path / "partial"
        partial_dir.mkdir()
        partial = HARNESS._run_once(
            run_index=3,
            run_dir=partial_dir,
            flask_app=app,
            agent_routes=routes,
            DeviceRegistry=registry_type,
            create_token=create_token,
            deadline_ns=time.perf_counter_ns() + 10_000_000_000,
            workload=SMALL_WORKLOAD,
            admission_limit=1,
        )
        assert partial["admitted"] == 1
        assert partial["sent"] == partial["completed"] == 1
        assert partial["persisted"] == 1
        assert partial["backlog"]["maximum_admitted_outstanding"] <= 1
        assert any("test-only producer stop" in error for error in partial["errors"])
        assert not partial["invariants_pass"]

        expired_dir = tmp_path / "expired"
        expired_dir.mkdir()
        started = time.perf_counter()
        expired = HARNESS._run_once(
            run_index=4,
            run_dir=expired_dir,
            flask_app=app,
            agent_routes=routes,
            DeviceRegistry=registry_type,
            create_token=create_token,
            deadline_ns=time.perf_counter_ns() - 1,
            workload=SMALL_WORKLOAD,
        )
        elapsed = time.perf_counter() - started
        assert elapsed < 10
        assert expired["admitted"] == expired["sent"] == expired["completed"] == 0
        assert expired["persisted"] == 0
        assert expired["backlog"]["maximum_active_handlers"] == 0
        assert any("time bound" in error for error in expired["errors"])
