#!/usr/bin/env python3
"""Run the explicit, local-only LOAD-002 telemetry ingestion diagnostic.

This diagnostic uses Flask's real test client, agent blueprint, route,
DeviceRegistry, and an isolated SQLite database. It does not measure network,
Render, physical ASICs, or production WSGI behavior and is not a performance
gate. It is intentionally excluded from default pytest.

Example::

    python scripts/measure_telemetry_ingest.py --runs 3 \
      --output artifacts/load-002-baseline.json
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
import platform
import queue
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch


TENANT_A = "load002-alpha"
TENANT_B = "load002-beta"


@dataclass(frozen=True)
class Workload:
    """Immutable request mix; production CLI uses the approved task's full shape."""

    device_count: int
    unique_per_device: int
    replay_per_device: int
    conflict_per_device: int
    tenant_probes_per_device: int
    queue_capacity_per_device: int
    late_arrival_sequence: int

    @property
    def submissions_per_device(self) -> int:
        return (
            self.unique_per_device
            + self.replay_per_device
            + self.conflict_per_device
            + self.tenant_probes_per_device
        )

    @property
    def total_submissions(self) -> int:
        return self.device_count * self.submissions_per_device

    @property
    def counts(self) -> dict[str, int]:
        return {
            "unique": self.device_count * self.unique_per_device,
            "replay": self.device_count * self.replay_per_device,
            "conflict": self.device_count * self.conflict_per_device,
            "tenant_probe": self.device_count * self.tenant_probes_per_device,
        }

    @property
    def expected(self) -> dict[str, dict[str, int]]:
        return {
            "unique": {"count": self.counts["unique"], "status": 200},
            "replay": {"count": self.counts["replay"], "status": 200},
            "conflict": {"count": self.counts["conflict"], "status": 409},
            "tenant_probe": {"count": self.counts["tenant_probe"], "status": 200},
        }

    @property
    def conflict_sequences(self) -> tuple[int, ...]:
        if self.conflict_per_device == 2:
            return (self.unique_per_device // 4, (self.unique_per_device * 3) // 4)
        return tuple(
            (index + 1) * self.unique_per_device // (self.conflict_per_device + 1)
            for index in range(self.conflict_per_device)
        )

    @property
    def tenant_probe_sequences(self) -> tuple[int, ...]:
        if self.tenant_probes_per_device == 2:
            return (self.unique_per_device // 3, (self.unique_per_device * 2) // 3)
        return tuple(
            (index + 1) * self.unique_per_device // (self.tenant_probes_per_device + 1)
            for index in range(self.tenant_probes_per_device)
        )


FULL_WORKLOAD = Workload(50, 160, 36, 2, 2, 2, 158)


def _sample_ts(base_ts: int, sequence: int, late_arrival_sequence: int = 158) -> int:
    """Return a near-current synthetic sample timestamp with one late arrival."""
    return base_ts - 1 if sequence == late_arrival_sequence else base_ts + sequence


def _percentile(values: list[float], percentile: float) -> float | None:
    """Return nearest-rank percentile in milliseconds, or None if empty."""
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return round(ordered[index], 6)


def _latency_summary(samples_ns: list[int]) -> dict[str, float | int | None]:
    milliseconds = [sample / 1_000_000 for sample in samples_ns]
    return {
        "count": len(samples_ns),
        "p50_ms": _percentile(milliseconds, 0.50),
        "p95_ms": _percentile(milliseconds, 0.95),
        "p99_ms": _percentile(milliseconds, 0.99),
        "max_ms": round(max(milliseconds), 6) if milliseconds else None,
    }


def _make_operations(
    device_index: int,
    run_index: int,
    base_ts: int,
    workload: Workload = FULL_WORKLOAD,
) -> list[dict[str, Any]]:
    """Build the declared ordered submissions for one synthetic device stream."""
    ip = f"192.0.2.{device_index + 1}"
    prefix = f"l002-r{run_index:02d}-d{device_index:02d}"
    originals: list[dict[str, Any]] = []
    operations: list[dict[str, Any]] = []
    for sequence in range(workload.unique_per_device):
        original = {
            "ip": ip,
            "idempotency_key": f"{prefix}-e{sequence:03d}",
            "telemetry": {
                "ts": _sample_ts(base_ts, sequence, workload.late_arrival_sequence),
                "hashrate_hs": 5_000_000_000_000 + device_index * 1_000_000 + sequence,
                "load002_sequence": sequence,
            },
        }
        originals.append(original)
        operations.append({"kind": "unique", "tenant": TENANT_A, "event": original})
    for sequence in range(workload.replay_per_device):
        operations.append(
            {"kind": "replay", "tenant": TENANT_A, "event": originals[sequence]}
        )
    for sequence in workload.conflict_sequences:
        original = originals[sequence]
        changed = {
            **original,
            "telemetry": {
                **original["telemetry"],
                "hashrate_hs": original["telemetry"]["hashrate_hs"] + 1,
            },
        }
        operations.append({"kind": "conflict", "tenant": TENANT_A, "event": changed})
    for sequence in workload.tenant_probe_sequences:
        operations.append(
            {"kind": "tenant_probe", "tenant": TENANT_B, "event": originals[sequence]}
        )
    if len(operations) != workload.submissions_per_device:
        raise AssertionError("workload operation count does not match its declaration")
    return operations


def _prepare_app(local_secret: str):
    """Create a minimal Flask app using the product's actual agent blueprint."""
    repo_root = str(Path(__file__).resolve().parents[1])
    added_path = repo_root not in sys.path
    if added_path:
        sys.path.insert(0, repo_root)
    try:
        from flask import Flask
        from axe_fleet import routes as agent_routes
        from axe_fleet.registry import DeviceRegistry
        from services.auth import create_token
    finally:
        if added_path:
            sys.path.remove(repo_root)

    flask_app = Flask("load002_local_harness")
    flask_app.config.update(
        TESTING=True,
        SECRET_KEY=local_secret,
        JWT_SECRET_KEY=local_secret,
        PROPAGATE_EXCEPTIONS=True,
    )
    flask_app.register_blueprint(agent_routes.agent_bp)
    return flask_app, agent_routes, DeviceRegistry, create_token


def _new_registry(DeviceRegistry, db_path: Path):
    """Create a real per-operation SQLite registry matching app DB pragmas."""
    bootstrap = sqlite3.connect(str(db_path), timeout=3.0)
    try:
        bootstrap.execute("PRAGMA journal_mode=WAL")
        mode = str(bootstrap.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        if mode != "wal":
            raise AssertionError(f"SQLite WAL unavailable: {mode}")
    finally:
        bootstrap.close()

    def get_db():
        conn = sqlite3.connect(str(db_path), timeout=3.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=3000")
        if int(conn.execute("PRAGMA synchronous").fetchone()[0]) != 1:
            conn.close()
            raise AssertionError("SQLite synchronous mode is not NORMAL")
        if int(conn.execute("PRAGMA busy_timeout").fetchone()[0]) != 3000:
            conn.close()
            raise AssertionError("SQLite busy timeout is not 3000ms")
        return conn

    registry = DeviceRegistry(get_db)
    registry.ensure_tables()
    return registry, get_db


def _run_once(
    *,
    run_index: int,
    run_dir: Path,
    flask_app,
    agent_routes,
    DeviceRegistry,
    create_token,
    deadline_ns: int,
    workload: Workload = FULL_WORKLOAD,
    admission_limit: int | None = None,
) -> dict[str, Any]:
    db_path = run_dir / "load-002.sqlite3"
    registry, get_db = _new_registry(DeviceRegistry, db_path)
    agent_routes.init_routes(registry)
    device_rows: list[dict[str, str]] = []
    for device_index in range(workload.device_count):
        ip = f"192.0.2.{device_index + 1}"
        alpha = registry.upsert_agent_device(ip, tenant_id=TENANT_A)
        beta = registry.upsert_agent_device(ip, tenant_id=TENANT_B)
        if not alpha or not beta:
            raise AssertionError(f"could not create synthetic tenant-scoped pair {ip}")
        device_rows.append({"ip": ip, "alpha_id": alpha["id"], "beta_id": beta["id"]})

    with flask_app.app_context():
        tokens = {
            TENANT_A: create_token(
                subject=TENANT_A,
                ttl=3600,
                extra_claims={"agent": True, "role": "agent"},
            ),
            TENANT_B: create_token(
                subject=TENANT_B,
                ttl=3600,
                extra_claims={"agent": True, "role": "agent"},
            ),
        }
    # Latest observation is two seconds behind wall clock; all samples are
    # current-derived and in the past, including the deliberately late one.
    base_ts = int(time.time()) - workload.unique_per_device - 2
    all_ops = [
        _make_operations(i, run_index, base_ts, workload)
        for i in range(workload.device_count)
    ]
    queues = [
        queue.Queue(maxsize=workload.queue_capacity_per_device)
        for _ in range(workload.device_count)
    ]
    start_barrier = threading.Barrier(workload.device_count + 1)
    stop_event = threading.Event()
    lock = threading.Lock()
    queued = active = admitted = sent = completed = 0
    max_queued = max_active = max_outstanding = 0
    by_kind_admitted: Counter[str] = Counter()
    by_kind_sent: Counter[str] = Counter()
    by_kind_completed: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    classified_statuses: Counter[str] = Counter()
    errors: list[str] = []
    client_threads: set[str] = set()
    offer_to_complete: list[int] = []
    admission_to_start: list[int] = []
    post_wall: list[int] = []
    offer_to_admit: list[int] = []
    latency_by_kind: dict[str, list[int]] = {kind: [] for kind in workload.expected}
    first_offer_ns: int | None = None
    final_complete_ns: int | None = None

    def worker(device_index: int) -> None:
        nonlocal queued, active, sent, completed, max_active, final_complete_ns
        client = flask_app.test_client()
        with lock:
            client_threads.add(threading.current_thread().name)
        start_barrier.wait(timeout=10)
        while True:
            try:
                item = queues[device_index].get(timeout=0.1)
            except queue.Empty:
                if stop_event.is_set():
                    return
                continue
            try:
                if not item["admission_ready"].wait(timeout=2.0):
                    raise TimeoutError(
                        "producer did not finalize successful queue admission"
                    )
                started = time.perf_counter_ns()
                with lock:
                    queued -= 1
                    active += 1
                    max_active = max(max_active, active)
                if started >= deadline_ns:
                    raise TimeoutError(
                        "overall time bound reached before handler start"
                    )
                with lock:
                    sent += 1
                    by_kind_sent[item["kind"]] += 1
                headers = {"Authorization": f"Bearer {tokens[item['tenant']]}"}
                post_start = time.perf_counter_ns()
                response = client.post(
                    "/api/agent/telemetry", headers=headers, json=item["event"]
                )
                finished = time.perf_counter_ns()
                status = int(response.status_code)
                body = response.get_json(silent=True) or {}
                expected_status = workload.expected[item["kind"]]["status"]
                with lock:
                    if status != expected_status:
                        errors.append(
                            f"{item['kind']} expected {expected_status}, got {status}: {str(body)[:180]}"
                        )
                    completed += 1
                    by_kind_completed[item["kind"]] += 1
                    statuses[str(status)] += 1
                    classified_statuses[f"{item['kind']}:{status}"] += 1
                    active -= 1
                    final_complete_ns = max(final_complete_ns or finished, finished)
                    offer_to_complete.append(finished - item["offered_ns"])
                    admission_to_start.append(started - item["admitted_ns"])
                    post_wall.append(finished - post_start)
                    offer_to_admit.append(item["admitted_ns"] - item["offered_ns"])
                    latency_by_kind[item["kind"]].append(finished - post_start)
            except Exception as exc:
                finished = time.perf_counter_ns()
                with lock:
                    errors.append(
                        f"{item.get('kind', 'unknown')} {type(exc).__name__}: {exc}"
                    )
                    completed += 1
                    by_kind_completed[item.get("kind", "unknown")] += 1
                    active = max(0, active - 1)
                    final_complete_ns = max(final_complete_ns or finished, finished)
                    offer_to_complete.append(
                        max(0, finished - item.get("offered_ns", finished))
                    )
            finally:
                queues[device_index].task_done()

    executor = ThreadPoolExecutor(
        max_workers=workload.device_count, thread_name_prefix="load002-agent"
    )
    futures = [executor.submit(worker, i) for i in range(workload.device_count)]
    try:
        start_barrier.wait(timeout=10)
        for operation_index in range(workload.submissions_per_device):
            for device_index in range(workload.device_count):
                if admission_limit is not None and admitted >= admission_limit:
                    raise RuntimeError(
                        "test-only producer stop after admitted request limit"
                    )
                if time.perf_counter_ns() >= deadline_ns:
                    raise TimeoutError("overall time bound reached during admission")
                item = dict(all_ops[device_index][operation_index])
                item["offered_ns"] = time.perf_counter_ns()
                item["admission_ready"] = threading.Event()
                if first_offer_ns is None:
                    first_offer_ns = item["offered_ns"]
                remaining = max(
                    0.001, min(0.25, (deadline_ns - time.perf_counter_ns()) / 1e9)
                )
                try:
                    queues[device_index].put(item, timeout=remaining)
                except queue.Full as exc:
                    raise TimeoutError(
                        "bounded per-device admission queue remained full"
                    ) from exc
                admitted_at = time.perf_counter_ns()
                with lock:
                    item["admitted_ns"] = admitted_at
                    admitted += 1
                    queued += 1
                    by_kind_admitted[item["kind"]] += 1
                    max_queued = max(max_queued, queued)
                    max_outstanding = max(max_outstanding, admitted - completed)
                item["admission_ready"].set()
    except Exception as exc:
        errors.append(f"producer {type(exc).__name__}: {exc}")
    finally:
        stop_event.set()
        # Queue get has a timeout; all successfully admitted items drain before workers exit.
        for future in futures:
            try:
                future.result(
                    timeout=max(5.0, (deadline_ns - time.perf_counter_ns()) / 1e9 + 5.0)
                )
            except Exception as exc:
                errors.append(f"worker shutdown {type(exc).__name__}: {exc}")
        executor.shutdown(wait=True, cancel_futures=True)

    finish_ns = final_complete_ns or time.perf_counter_ns()
    elapsed_s = max(1e-9, (finish_ns - (first_offer_ns or finish_ns)) / 1e9)
    conn = get_db()
    try:
        persisted_by_tenant = {
            str(r[0]): int(r[1])
            for r in conn.execute(
                "SELECT tenant_id, COUNT(*) FROM axe_telemetry GROUP BY tenant_id"
            )
        }
        device_count_by_tenant = {
            str(r[0]): int(r[1])
            for r in conn.execute(
                "SELECT tenant_id, COUNT(*) FROM axe_devices GROUP BY tenant_id"
            )
        }
        persisted_total = int(
            conn.execute("SELECT COUNT(*) FROM axe_telemetry").fetchone()[0]
        )
        duplicate_groups = int(
            conn.execute(
                "SELECT COUNT(*) FROM (SELECT tenant_id, device_id, idempotency_key FROM axe_telemetry "
                "GROUP BY tenant_id, device_id, idempotency_key HAVING COUNT(*) > 1)"
            ).fetchone()[0]
        )
        alpha_received: dict[str, list[int]] = {}
        for row in conn.execute(
            "SELECT device_id,payload FROM axe_telemetry WHERE tenant_id=? ORDER BY id",
            (TENANT_A,),
        ):
            payload = json.loads(row[1])
            alpha_received.setdefault(str(row[0]), []).append(
                int(payload["load002_sequence"])
            )
        canonical_ok = True
        for d, device in enumerate(device_rows):
            for tenant, device_id, sequences in (
                (TENANT_A, device["alpha_id"], range(workload.unique_per_device)),
                (TENANT_B, device["beta_id"], workload.tenant_probe_sequences),
            ):
                for seq in sequences:
                    key = f"l002-r{run_index:02d}-d{d:02d}-e{seq:03d}"
                    row = conn.execute(
                        "SELECT device_id,payload FROM axe_telemetry WHERE tenant_id=? AND idempotency_key=?",
                        (tenant, key),
                    ).fetchone()
                    if not row or str(row[0]) != device_id:
                        canonical_ok = False
                        continue
                    payload = json.loads(row[1])
                    if (
                        int(payload.get("load002_sequence", -1)) != seq
                        or int(payload.get("ts", -1))
                        != _sample_ts(base_ts, seq, workload.late_arrival_sequence)
                        or int(payload.get("hashrate_hs", -1))
                        != 5_000_000_000_000 + d * 1_000_000 + seq
                    ):
                        canonical_ok = False
        conflict_preserved = 0
        for d in range(workload.device_count):
            for seq in workload.conflict_sequences:
                key = f"l002-r{run_index:02d}-d{d:02d}-e{seq:03d}"
                row = conn.execute(
                    "SELECT payload FROM axe_telemetry WHERE tenant_id=? AND idempotency_key=?",
                    (TENANT_A, key),
                ).fetchone()
                if (
                    row
                    and int(json.loads(row[0])["hashrate_hs"])
                    == 5_000_000_000_000 + d * 1_000_000 + seq
                ):
                    conflict_preserved += 1
    finally:
        conn.close()

    receive_order_ok = all(
        alpha_received.get(row["alpha_id"], [])
        == list(range(workload.unique_per_device))
        for row in device_rows
    )
    latest_sequences: list[int | None] = []
    beta_latest_ok = True
    chart_chronology_ok = True
    late_arrival_devices = 0
    for row in device_rows:
        history = registry.get_recent_telemetry(
            row["alpha_id"],
            limit=workload.unique_per_device + 10,
            tenant_id=TENANT_A,
        )
        latest = int(history[0]["payload"].get("load002_sequence")) if history else None
        latest_sequences.append(latest)
        if latest != workload.unique_per_device - 1:
            beta_latest_ok = False
        beta_history = registry.get_recent_telemetry(
            row["beta_id"], limit=10, tenant_id=TENANT_B
        )
        expected_beta_latest = max(workload.tenant_probe_sequences)
        if (
            not beta_history
            or int(beta_history[0]["payload"].get("load002_sequence", -1))
            != expected_beta_latest
        ):
            beta_latest_ok = False
        chart = registry.get_telemetry_chart_data(
            row["alpha_id"],
            limit=workload.unique_per_device + 10,
            tenant_id=TENANT_A,
        )
        chart_ts = chart.get("ts", [])
        if chart_ts != sorted(chart_ts):
            chart_chronology_ok = False
        expected_ts = sorted(
            _sample_ts(base_ts, seq, workload.late_arrival_sequence)
            for seq in range(workload.unique_per_device)
        )
        if chart_ts == expected_ts:
            late_arrival_devices += 1

    expected_kinds = workload.counts
    expected_status = {
        "200": workload.counts["unique"]
        + workload.counts["replay"]
        + workload.counts["tenant_probe"],
        "409": workload.counts["conflict"],
    }
    expected_persisted_alpha = workload.device_count * workload.unique_per_device
    expected_persisted_beta = workload.device_count * workload.tenant_probes_per_device
    expected_persisted_total = expected_persisted_alpha + expected_persisted_beta
    invariant_checks = {
        "all_submissions_admitted": admitted == workload.total_submissions,
        "all_submissions_sent": sent == workload.total_submissions,
        "all_submissions_completed": completed == workload.total_submissions,
        "admitted_mix_observed": dict(by_kind_admitted) == expected_kinds,
        "sent_mix_observed": dict(by_kind_sent) == expected_kinds,
        "completed_mix_observed": dict(by_kind_completed) == expected_kinds,
        "expected_http_status_mix": dict(statuses) == expected_status,
        "tenant_scoped_device_counts_expected": device_count_by_tenant
        == {TENANT_A: workload.device_count, TENANT_B: workload.device_count},
        "persisted_count_expected": persisted_total == expected_persisted_total,
        "persisted_alpha_expected": persisted_by_tenant.get(TENANT_A, 0)
        == expected_persisted_alpha,
        "persisted_beta_expected": persisted_by_tenant.get(TENANT_B, 0)
        == expected_persisted_beta,
        "canonical_payloads_and_identities_verified": canonical_ok,
        "no_duplicate_idempotency_groups": duplicate_groups == 0,
        "all_conflicts_preserved_original": conflict_preserved
        == workload.counts["conflict"],
        "received_row_order_preserved": receive_order_ok,
        "latest_alpha_and_beta_sequences_verified": beta_latest_ok,
        "sample_time_chart_order_chronological": chart_chronology_ok,
        "late_arrival_case_observed_all_devices": late_arrival_devices
        == workload.device_count,
        "queue_bound_respected": max_queued
        <= workload.device_count * workload.queue_capacity_per_device,
        "active_handler_bound_respected": max_active <= workload.device_count,
        "all_worker_clients_started": len(client_threads) == workload.device_count,
        "admitted_outstanding_bound_respected": max_outstanding
        <= workload.device_count * (workload.queue_capacity_per_device + 1),
        "no_runtime_or_status_errors": not errors,
    }
    timing_arrays = [offer_to_complete, admission_to_start, post_wall, offer_to_admit]
    finite_timings = all(
        math.isfinite(value) and value >= 0 for arr in timing_arrays for value in arr
    )
    invariant_checks["timings_finite_nonnegative"] = finite_timings
    summary_values = [
        value
        for samples in timing_arrays
        for value in _latency_summary(samples).values()
        if value is not None and not isinstance(value, int)
    ]
    invariant_checks["percentiles_finite_nonnegative"] = all(
        math.isfinite(float(value)) and value >= 0 for value in summary_values
    )
    accepted_new_observed = (
        classified_statuses["unique:200"] + classified_statuses["tenant_probe:200"]
    )
    replayed_observed = classified_statuses["replay:200"]
    conflicts_observed = classified_statuses["conflict:409"]
    return {
        "run_index": run_index,
        "submitted": workload.total_submissions,
        "admitted": admitted,
        "sent": sent,
        "completed": completed,
        "accepted_new_observed_by_declared_kind": accepted_new_observed,
        "replayed_observed_by_declared_kind": replayed_observed,
        "rejected_conflict_observed": conflicts_observed,
        "persisted": persisted_total,
        "persisted_by_tenant": persisted_by_tenant,
        "tenant_scoped_device_rows_by_tenant": device_count_by_tenant,
        "http_status_counts": dict(statuses),
        "operation_status_counts": dict(classified_statuses),
        "workload_device_streams": workload.device_count,
        "tenant_scoped_device_rows": sum(device_count_by_tenant.values()),
        "distinct_worker_clients": len(client_threads),
        "duration_seconds": round(elapsed_s, 6),
        "throughput_completed_per_second": round(completed / elapsed_s, 3),
        "backlog": {
            "definition": "queued waiting-for-handler and active HTTP dispatches are separate; admitted outstanding is their sum",
            "queue_capacity_per_device": workload.queue_capacity_per_device,
            "queue_capacity_total": workload.device_count
            * workload.queue_capacity_per_device,
            "maximum_queued_waiting_for_handler": max_queued,
            "maximum_active_handlers": max_active,
            "maximum_admitted_outstanding": max_outstanding,
            "scope": "harness bounded queues only; not a production WSGI backlog measurement",
        },
        "latency": {
            "offered_to_http_completion": _latency_summary(offer_to_complete),
            "admission_queue_wait": _latency_summary(admission_to_start),
            "client_post_handler_wall_time": _latency_summary(post_wall),
            "producer_backpressure_before_admission": _latency_summary(offer_to_admit),
            "client_post_by_operation_kind": {
                kind: _latency_summary(values)
                for kind, values in latency_by_kind.items()
            },
            "units": "milliseconds, nearest-rank percentiles from perf_counter_ns",
        },
        "integrity": {
            "idempotency_duplicate_groups": duplicate_groups,
            "canonical_payloads_verified": canonical_ok,
            "conflict_original_payloads_preserved": conflict_preserved,
            "received_order_preserved_by_sqlite_row_id": receive_order_ok,
            "latest_alpha_sample_sequences": latest_sequences,
            "latest_beta_sample_sequence": (
                max(workload.tenant_probe_sequences) if beta_latest_ok else None
            ),
            "chart_chronological_by_sample_timestamp": chart_chronology_ok,
            "late_arrival_cases": late_arrival_devices,
            "note": "SQLite row id captures receive order; chart/history use sample timestamp ordering, so late arrivals can differ from receipt sequence.",
        },
        "invariant_checks": invariant_checks,
        "invariants_pass": all(invariant_checks.values()),
        "errors": errors[:100],
        "sqlite": {
            "journal_mode": "WAL",
            "synchronous": "NORMAL",
            "busy_timeout_ms": 3000,
            "connection_timeout_s": 3,
        },
    }


def _blocked_transport(*_args, **_kwargs):
    """Fail any attempt to use a real hardware/network transport."""
    raise AssertionError("external transport is prohibited in LOAD-002 local harness")


def _source_provenance(repo_root: Path) -> dict[str, Any]:
    """Hash source inputs and report whether the checkout contains local edits."""
    inputs = (
        Path(__file__).resolve(),
        repo_root / "tests/test_measure_telemetry_ingest_helpers.py",
        repo_root / "docs/telemetry-ingest-load-baseline.md",
    )
    hashes = {
        path.relative_to(repo_root)
        .as_posix(): hashlib.sha256(path.read_bytes())
        .hexdigest()
        for path in inputs
        if path.exists()
    }
    status_result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    status = status_result.stdout.splitlines() if status_result.returncode == 0 else []
    return {
        "git_dirty": bool(status) or status_result.returncode != 0,
        "git_status_porcelain": status,
        "input_sha256": hashes,
    }


def _run(
    args: argparse.Namespace, workload: Workload = FULL_WORKLOAD
) -> dict[str, Any]:
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(
            f"refusing to overwrite existing evidence artifact: {output}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    start_utc = datetime.now(timezone.utc).isoformat()
    deadline_ns = time.perf_counter_ns() + args.max_wall_seconds * 1_000_000_000
    records: list[dict[str, Any]] = []
    run_error: str | None = None
    local_secret = secrets.token_urlsafe(48)
    with tempfile.TemporaryDirectory(prefix="cypher65-load002-") as temp_root:
        root = Path(temp_root)
        env = {
            "DB_PATH": str(root / "isolated-bootstrap.sqlite3"),
            "SECRET_KEY": local_secret,
            "JWT_SECRET_KEY": local_secret,
            "SENTRY_DSN": "",
            "REVOKED_TOKENS_DB": "0",
        }
        with patch.dict(os.environ, env):
            # Guards are active before any product module/blueprint is imported.
            with patch.object(
                socket.socket, "connect", _blocked_transport
            ), patch.object(socket.socket, "connect_ex", _blocked_transport), patch(
                "socket.create_connection", _blocked_transport
            ):
                flask_app, agent_routes, DeviceRegistry, create_token = _prepare_app(
                    local_secret
                )
                original_registry = agent_routes._registry
                try:
                    with patch.object(
                        agent_routes, "AxeOSConnector", side_effect=_blocked_transport
                    ):
                        for run_index in range(args.runs):
                            if time.perf_counter_ns() >= deadline_ns:
                                raise TimeoutError(
                                    "wall-time cap reached before repeat"
                                )
                            run_dir = root / f"run-{run_index:02d}"
                            run_dir.mkdir()
                            records.append(
                                _run_once(
                                    run_index=run_index,
                                    run_dir=run_dir,
                                    flask_app=flask_app,
                                    agent_routes=agent_routes,
                                    DeviceRegistry=DeviceRegistry,
                                    create_token=create_token,
                                    deadline_ns=deadline_ns,
                                    workload=workload,
                                )
                            )
                except Exception as exc:
                    run_error = f"{type(exc).__name__}: {exc}"
                finally:
                    agent_routes._registry = original_registry
    revision_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        capture_output=True,
        text=True,
    )
    revision = (
        revision_result.stdout.strip()
        if revision_result.returncode == 0
        else "unavailable"
    )
    repo_root = Path(__file__).resolve().parents[1]
    provenance = _source_provenance(repo_root)
    artifact = {
        "schema_version": 1,
        "benchmark": "LOAD-002 local in-process telemetry integration diagnostic",
        "classification": "diagnostic_only_not_an_approved_performance_gate",
        "started_at_utc": start_utc,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": revision,
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_provenance": provenance,
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "sqlite": sqlite3.sqlite_version,
            "logical_cpu_count": os.cpu_count(),
            "runtime_profile": "local Flask test_client -> real agent blueprint/route -> DeviceRegistry -> isolated temporary SQLite",
            "external_network": "socket and AxeOSConnector guards raise before product imports/route transport",
            "physical_asic": False,
            "render_or_deployed_service": False,
            "rss_scope": "not measured; no host/container memory inference",
        },
        "workload": {
            "total_submissions_per_run": workload.total_submissions,
            "unique_first_submissions": workload.counts["unique"],
            "same_tenant_exact_replays": workload.counts["replay"],
            "changed_payload_conflicts": workload.counts["conflict"],
            "other_tenant_same_ip_key_probes": workload.counts["tenant_probe"],
            "replay_fraction": round(
                workload.counts["replay"] / workload.total_submissions, 6
            ),
            "conflict_fraction": round(
                workload.counts["conflict"] / workload.total_submissions, 6
            ),
            "tenant_probe_fraction": round(
                workload.counts["tenant_probe"] / workload.total_submissions, 6
            ),
            "concurrent_device_streams": workload.device_count,
            "worker_model": "one persistent test client per worker/device stream; per-stream order serialized; all workers start on a barrier",
            "queue_cap": f"{workload.queue_capacity_per_device} queued per stream ({workload.device_count * workload.queue_capacity_per_device}) plus at most {workload.device_count} active handlers",
            "tenant_aliases": f"{workload.device_count} primary streams plus {workload.device_count} same-IP device rows under a second tenant",
            "synthetic_ip_range": "192.0.2.0/24 documentation addresses only",
            "sample_timestamps": "derived from current epoch; all samples are in the past; sequence 158 arrives with a sample timestamp one second before the base while sequence 159 remains newest",
        },
        "slo": {
            "approved": False,
            "performance_gate": "NOT_EVALUATED_NO_APPROVED_SLO",
            "proposal_status": "unapproved_proposal_only; see docs/telemetry-ingest-load-baseline.md",
        },
        "run_count_requested": args.runs,
        "run_count_completed": len(records),
        "runs": records,
        "harness_error": run_error,
        "integrity_status": (
            "PASS"
            if run_error is None
            and records
            and all(r["invariants_pass"] for r in records)
            else "FAIL"
        ),
    }
    if any(
        not math.isfinite(float(v))
        for run in records
        for v in (run["duration_seconds"], run["throughput_completed_per_second"])
    ):
        artifact["integrity_status"] = "FAIL"
        artifact["harness_error"] = "non-finite aggregate timing metric"
    with output.open("x", encoding="utf-8") as artifact_file:
        artifact_file.write(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    print(json.dumps(artifact, indent=2, sort_keys=True))
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3, help="repeats, from 1 to 5")
    parser.add_argument(
        "--max-wall-seconds", type=int, default=180, help="total cap, 30 to 300 seconds"
    )
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/load-002-baseline-c597304.json")
    )
    args = parser.parse_args()
    if not 1 <= args.runs <= 5:
        parser.error("--runs must be between 1 and 5")
    if not 30 <= args.max_wall_seconds <= 300:
        parser.error("--max-wall-seconds must be between 30 and 300")
    if (
        FULL_WORKLOAD.total_submissions != 10_000
        or sum(FULL_WORKLOAD.counts.values()) != 10_000
    ):
        parser.error("workload composition must sum to exactly 10,000")
    try:
        artifact = _run(args)
    except Exception as exc:
        parser.error(
            f"harness setup failed without creating evidence: {type(exc).__name__}: {exc}"
        )
    return 0 if artifact["integrity_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
