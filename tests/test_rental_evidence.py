"""Persistence, attribution and alert-window tests for rental evidence."""

import csv
import io
import sqlite3
import time
from types import SimpleNamespace

import pytest

from services import rental_evidence as evidence
from services.bootstrap import init_db


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Use real SQLite with the production schema in a per-test database."""
    path = str(tmp_path / "rental-evidence.sqlite")
    monkeypatch.setenv("DB_PATH", path)
    init_db()
    return path


def _sample(worker_id="pool-worker-1", hashrate=80e12, name="rental-worker"):
    return {"workerData": [{"id": worker_id, "name": name, "hashrate": hashrate}]}


def _configure(tenant="tenant-a", rental="rental-1", *, source_id=None, **overrides):
    if source_id is None:
        source_id = evidence.read(tenant, "mrr", rental)["sources"][0]["id"]
    body = {
        "source_id": source_id,
        "contract_th": 100,
        "threshold_pct": 90,
        "duration_s": 60,
        "max_gap_s": 30,
        "exclusive_worker": True,
    }
    body.update(overrides)
    return evidence.configure(tenant, "mrr", rental, body)


def _collect(tenant, address, payload, *, started=None, completed=None):
    now = time.time()
    started = now if started is None else started
    completed = max(started, now) + 0.001 if completed is None else completed
    evidence.collect(tenant, address, payload, started, completed)
    return completed


def test_schema_is_real_sqlite_and_idempotent(db):
    with sqlite3.connect(db) as conn:
        evidence.ensure_schema(conn)
        evidence.ensure_schema(conn)
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {
            "rental_evidence_sources",
            "rental_evidence_bindings",
            "rental_evidence_points",
            "rental_evidence_alerts",
        } <= tables
        index_names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
        assert "idx_rental_evidence_points" in index_names


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_id", True),
        ("contract_th", True),
        ("contract_th", float("nan")),
        ("contract_th", float("inf")),
        ("threshold_pct", False),
        ("threshold_pct", float("nan")),
        ("duration_s", True),
        ("duration_s", 60.5),
        ("max_gap_s", False),
        ("max_gap_s", 15.5),
    ],
)
def test_config_rejects_nonfinite_boolean_and_fractional_integer_values(db, field, value):
    _collect("tenant-a", "bc1qtestaddress000", _sample())
    with pytest.raises(ValueError):
        _configure(**{field: value})


def test_config_requires_explicit_exclusive_worker_and_whole_seconds(db):
    _collect("tenant-a", "bc1qtestaddress000", _sample())
    with pytest.raises(ValueError, match="exclusivo"):
        _configure(exclusive_worker=False)
    config = _configure(duration_s=75, max_gap_s=25)
    assert config["duration_s"] == 75
    assert config["max_gap_s"] == 25
    assert config["exclusive_worker"] is True


def test_source_is_tenant_scoped_and_export_cannot_cross_tenants(db):
    address = "bc1qtenantaddress000"
    _collect("tenant-a", address, _sample("=SUM(1,1)", 81e12))
    _collect("tenant-b", address, _sample("tenant-b-worker", 22e12))
    cfg_a = _configure(
        "tenant-a", "rental-a",
        source_id=evidence.read("tenant-a", "mrr", "rental-a")["sources"][0]["id"],
    )
    cfg_b = _configure(
        "tenant-b", "rental-a", source_id=evidence.read("tenant-b", "mrr", "rental-a")["sources"][0]["id"]
    )

    _collect("tenant-a", address, _sample("=SUM(1,1)", 81e12), started=cfg_a["created_at"] + 0.001)
    _collect("tenant-b", address, _sample("tenant-b-worker", 22e12), started=cfg_b["created_at"] + 0.001)

    a = evidence.read("tenant-a", "mrr", "rental-a")
    b = evidence.read("tenant-b", "mrr", "rental-a")
    assert [point["hashrate_th"] for point in a["points"]] == [81]
    assert [point["hashrate_th"] for point in b["points"]] == [22]
    assert "tenant-b-worker" not in evidence.export_csv("tenant-a", "mrr", "rental-a")
    exported = list(csv.DictReader(io.StringIO(evidence.export_csv("tenant-a", "mrr", "rental-a"))))
    assert exported[0]["worker_value"] == "'=SUM(1,1)"

    with pytest.raises(ValueError, match="Fonte inexistente"):
        evidence.configure(
            "tenant-b",
            "mrr",
            "cross-tenant",
            {"source_id": a["sources"][0]["id"], "contract_th": 100,
             "threshold_pct": 90, "duration_s": 60, "max_gap_s": 30,
             "exclusive_worker": True},
        )


def test_worker_cannot_be_bound_to_two_active_rentals(db):
    _collect("tenant-a", "bc1qtestaddress000", _sample())
    source_id = evidence.read("tenant-a", "mrr", "rental-1")["sources"][0]["id"]
    _configure("tenant-a", "rental-1", source_id=source_id)
    with pytest.raises(ValueError, match="outro aluguel"):
        _configure("tenant-a", "rental-2", source_id=source_id)


@pytest.mark.parametrize(
    "payload,expected_quality",
    [
        ({"workerData": [{"id": "other", "hashrate": 50e12}]}, "unmapped"),
        ({"workerData": [{"id": "pool-worker-1", "hashrate": 50e12},
                         {"id": "pool-worker-1", "hashrate": 60e12}]}, "ambiguous"),
        (None, "api_error"),
        ({"workerData": None}, "api_error"),
    ],
)
def test_exact_selector_failure_states_are_not_zero_hashrate(db, payload, expected_quality):
    address = "bc1qtestaddress000"
    _collect("tenant-a", address, _sample())
    cfg = _configure()
    _collect("tenant-a", address, payload, started=cfg["created_at"] + 0.001)
    point = evidence.read("tenant-a", "mrr", "rental-1")["points"][-1]
    assert point["quality"] == expected_quality
    assert point["hashrate_th"] is None
    assert point["delivery_pct"] is None
    assert evidence.read("tenant-a", "mrr", "rental-1")["evaluation"]["status"] != "under_delivery"


def test_selector_is_exact_and_case_sensitive(db):
    address = "bc1qtestaddress000"
    _collect("tenant-a", address, _sample("Pool-Worker"))
    cfg = _configure()
    _collect("tenant-a", address, _sample("pool-worker"), started=cfg["created_at"] + 0.001)
    point = evidence.read("tenant-a", "mrr", "rental-1")["points"][-1]
    assert point["quality"] == "unmapped"
    assert point["hashrate_th"] is None


def test_replayed_upstream_fetch_is_idempotent(db):
    address = "bc1qtestaddress000"
    _collect("tenant-a", address, _sample())
    cfg = _configure()
    start = cfg["created_at"] + 0.001
    complete = start + 0.001
    payload = _sample(hashrate=75e12)
    _collect("tenant-a", address, payload, started=start, completed=complete)
    _collect("tenant-a", address, payload, started=start, completed=complete)
    assert len(evidence.read("tenant-a", "mrr", "rental-1")["points"]) == 1


def test_collect_emits_each_sustained_alert_once(db, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(evidence, "time", SimpleNamespace(time=lambda: clock[0]))
    address = "bc1qtestaddress000"
    evidence.collect("tenant-a", address, _sample(), 999.9, 1000.0)
    config = _configure(duration_s=30, max_gap_s=30)
    assert config["created_at"] == 1000.0

    clock[0] = 1000.2
    first = evidence.collect("tenant-a", address, _sample(hashrate=50e12), 1000.1, 1000.2)
    assert first == []
    clock[0] = 1030.2
    second = evidence.collect("tenant-a", address, _sample(hashrate=50e12), 1030.1, 1030.2)
    assert len(second) == 1
    assert second[0]["window_start"] == 1000.2
    assert evidence.collect("tenant-a", address, _sample(hashrate=50e12), 1030.1, 1030.2) == []

    clock[0] = 1060.1
    continued = evidence.collect("tenant-a", address, _sample(hashrate=50e12), 1060.0, 1060.1)
    assert continued == []  # same low streak/window was already notified


def test_alert_and_evidence_dedup_rollback_together_then_replay_once(db, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(evidence, "time", SimpleNamespace(time=lambda: clock[0]))
    address = "bc1qtestaddress000"
    evidence.collect("tenant-a", address, _sample(), 999.9, 1000.0)
    _configure(duration_s=30, max_gap_s=30)
    first = (1000.1, 1000.2)
    final = (1030.1, 1030.2)

    clock[0] = first[1]
    evidence.collect("tenant-a", address, _sample(hashrate=50e12), *first)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TRIGGER reject_rental_alert BEFORE INSERT ON alerts "
            "BEGIN SELECT RAISE(ABORT, 'injected alert failure'); END"
        )

    clock[0] = final[1]
    with pytest.raises(sqlite3.IntegrityError, match="injected alert failure"):
        evidence.collect("tenant-a", address, _sample(hashrate=50e12), *final)

    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM rental_evidence_points").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM rental_evidence_alerts").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM alerts WHERE tenant_id='tenant-a'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM alert_history WHERE tenant_id='tenant-a'").fetchone()[0] == 0
        conn.execute("DROP TRIGGER reject_rental_alert")

    events = evidence.collect("tenant-a", address, _sample(hashrate=50e12), *final)
    assert len(events) == 1
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM rental_evidence_points").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM rental_evidence_alerts").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM alerts WHERE tenant_id='tenant-a' AND category='rental_delivery'"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM alert_history WHERE tenant_id='tenant-a' AND action_taken LIKE '%Aluguel%'"
        ).fetchone()[0] == 1

    assert evidence.collect("tenant-a", address, _sample(hashrate=50e12), *final) == []
    clock[0] = 1060.3
    assert evidence.collect(
        "tenant-a", address, _sample(hashrate=50e12), 1060.2, 1060.3
    ) == []
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM rental_evidence_alerts").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM alerts WHERE tenant_id='tenant-a' AND category='rental_delivery'"
        ).fetchone()[0] == 1


def test_oversized_worker_payload_is_unavailable_without_partial_discovery_or_alert(db, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(evidence, "time", SimpleNamespace(time=lambda: clock[0]))
    address = "bc1qtestaddress000"
    evidence.collect("tenant-a", address, _sample(), 999.9, 1000.0)
    _configure(duration_s=30, max_gap_s=30)

    clock[0] = 1000.2
    payload = {"workerData": [
        {"id": "pool-worker-1", "hashrate": 0},
        *[{"id": f"extra-{index}", "hashrate": 0} for index in range(250)],
    ]}
    events = evidence.collect("tenant-a", address, payload, 1000.1, 1000.2)
    result = evidence.read("tenant-a", "mrr", "rental-1")
    assert events == []
    assert result["points"][-1]["quality"] == "oversized"
    assert result["points"][-1]["hashrate_th"] is None
    assert result["points"][-1]["delivery_pct"] is None
    assert result["evaluation"]["status"] != "under_delivery"
    assert {source["worker_value"] for source in result["sources"]} == {"pool-worker-1"}


def test_late_older_healthy_sample_cannot_rewrite_newer_under_delivery(db, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(evidence, "time", SimpleNamespace(time=lambda: clock[0]))
    address = "bc1qtestaddress000"
    evidence.collect("tenant-a", address, _sample(), 999.9, 1000.0)
    _configure(duration_s=30, max_gap_s=30)
    clock[0] = 1000.2
    evidence.collect("tenant-a", address, _sample(hashrate=50e12), 1000.1, 1000.2)
    clock[0] = 1030.2
    evidence.collect("tenant-a", address, _sample(hashrate=50e12), 1030.1, 1030.2)
    before = evidence.read("tenant-a", "mrr", "rental-1")["evaluation"]
    assert before["status"] == "under_delivery"

    # A stale healthy response arrives after the newer low point, but its source
    # timestamp is older and must neither be persisted nor reset the verdict.
    events = evidence.collect("tenant-a", address, _sample(hashrate=100e12), 1014.9, 1015.0)
    after = evidence.read("tenant-a", "mrr", "rental-1")
    assert events == []
    assert len(after["points"]) == 2
    assert after["points"][-1]["observed_at"] == 1030.2
    assert after["evaluation"]["status"] == "under_delivery"
    assert after["evaluation"]["window_start"] == before["window_start"]


def test_sample_coverage_distinguishes_zero_missing_invalid_and_unconfigured(db):
    address = "bc1qtestaddress000"
    _collect("tenant-a", address, _sample())
    cfg = _configure()
    start = cfg["created_at"] + 0.001
    _collect("tenant-a", address, _sample(hashrate=0), started=start, completed=start + 0.001)
    missing_start = start + 1
    _collect("tenant-a", address, {"workerData": [{"id": "pool-worker-1", "hashrate": None}]},
             started=missing_start, completed=missing_start + 0.001)
    payload = evidence.read("tenant-a", "mrr", "rental-1")
    assert payload["coverage"] == {
        "status": "AVAILABLE",
        "observation_count": 2,
        "observed_count": 1,
        "missing_count": 1,
        "observed_pct": 50.0,
        "window_start": start + 0.001,
        "window_end": missing_start + 0.001,
    }
    assert payload["points"][0]["hashrate_th"] == 0
    assert payload["points"][0]["delivery_pct"] == 0
    assert payload["points"][1]["hashrate_th"] is None
    assert payload["coverage"]["status"] != "NOT CONFIGURED"

    evidence.disable("tenant-a", "mrr", "rental-1")
    unconfigured = evidence.read("tenant-a", "mrr", "rental-1")
    assert unconfigured["binding"] is None
    assert unconfigured["evaluation"]["status"] == "unconfigured"
    assert unconfigured["coverage"]["status"] == "NO DATA"
    assert unconfigured["coverage"]["observed_pct"] is None


def test_observed_pool_point_preserves_unknown_window_and_collection_bounds(db):
    address = "bc1qtestaddress000"
    _collect("tenant-a", address, _sample())
    cfg = _configure()
    start = cfg["created_at"] + 0.001
    complete = start + 0.001
    _collect("tenant-a", address, _sample(hashrate=100e12), started=start, completed=complete)
    point = evidence.read("tenant-a", "mrr", "rental-1")["points"][0]
    assert point["source"] == evidence.SOURCE
    assert point["collection_started_at"] == start
    assert point["collection_completed_at"] == complete
    assert point["observed_at"] == complete
    assert point["upstream_measured_at"] is None
    assert point["averaging_window_s"] is None
    assert point["hashrate_th"] == 100
    assert point["quality"] == "observed"


def test_evaluator_requires_sustained_low_samples_and_resets_after_healthy(db):
    config = {"threshold_pct": 90, "duration_s": 60, "max_gap_s": 30}
    point = lambda ts, pct, quality="observed": {
        "observed_at": ts, "quality": quality, "delivery_pct": pct,
        "hashrate_th": pct,
    }
    assert evidence.evaluate(config, [point(100, 50), point(130, 50)], 130)["status"] == "watching"
    verdict = evidence.evaluate(config, [point(100, 50), point(130, 50), point(160, 50)], 160)
    assert verdict["status"] == "under_delivery"
    assert verdict["alert"] == {
        "threshold_pct": 90, "duration_s": 60, "max_gap_s": 30,
        "observed_at": 160, "window_start": 100,
    }

    healthy_points = [point(100, 50), point(130, 50), point(160, 100)]
    assert evidence.evaluate(config, healthy_points, 160)["status"] == "healthy"
    restarted = healthy_points + [point(190, 50), point(220, 50), point(250, 50)]
    reset_verdict = evidence.evaluate(config, restarted, 250)
    assert reset_verdict["status"] == "under_delivery"
    assert reset_verdict["window_start"] == 190


def test_gap_breaks_low_streak_and_stale_is_not_zero(db):
    config = {"threshold_pct": 90, "duration_s": 60, "max_gap_s": 30}
    points = [
        {"observed_at": 100, "quality": "observed", "delivery_pct": 50, "hashrate_th": 50},
        {"observed_at": 130, "quality": "observed", "delivery_pct": 50, "hashrate_th": 50},
        {"observed_at": 161, "quality": "observed", "delivery_pct": 50, "hashrate_th": 50},
    ]
    verdict = evidence.evaluate(config, points, 161)
    assert verdict["status"] == "insufficient"
    assert verdict["samples"] == 1
    stale = evidence.evaluate(config, points, now=200)
    assert stale["status"] == "stale"
    assert stale["observed_th"] is None
    assert stale["alert"] is None


def test_rule_revision_does_not_backfill_or_mutate_retained_points(db):
    address = "bc1qtestaddress000"
    _collect("tenant-a", address, _sample())
    first = _configure(duration_s=60)
    start1 = first["created_at"] + 0.001
    _collect("tenant-a", address, _sample(hashrate=80e12), started=start1, completed=start1 + 0.001)
    second = _configure(duration_s=120)
    start2 = second["created_at"] + 0.001
    _collect("tenant-a", address, _sample(hashrate=70e12), started=start2, completed=start2 + 0.001)

    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT revision,point FROM rental_evidence_points ORDER BY revision"
        ).fetchall()
    assert [row[0] for row in rows] == [1, 2]
    old = __import__("json").loads(rows[0][1])
    new = __import__("json").loads(rows[1][1])
    assert old["config"]["duration_s"] == 60
    assert new["config"]["duration_s"] == 120
    assert old["hashrate_th"] == 80
    assert new["hashrate_th"] == 70
    exported = list(csv.DictReader(io.StringIO(evidence.export_csv("tenant-a", "mrr", "rental-1"))))
    assert [row["revision"] for row in exported] == ["1", "2"]


def test_point_and_source_bounds_are_enforced(db, monkeypatch):
    address = "bc1qtestaddress000"
    monkeypatch.setattr(evidence, "MAX_SOURCES", 2)
    workers = [{"id": f"worker-{i}", "hashrate": i + 1} for i in range(2)]
    _collect("tenant-a", address, {"workerData": workers})
    _collect("tenant-a", address, {"workerData": [{"id": "worker-extra", "hashrate": 3}]})
    assert len(evidence.read("tenant-a", "mrr", "unused")["sources"]) == 2

    source_id = evidence.read("tenant-a", "mrr", "unused")["sources"][0]["id"]
    cfg = evidence.configure(
        "tenant-a", "mrr", "bounded", {"source_id": source_id, "contract_th": 1,
        "threshold_pct": 90, "duration_s": 60, "max_gap_s": 30,
        "exclusive_worker": True},
    )
    monkeypatch.setattr(evidence, "MAX_POINTS", 2)
    for index in range(3):
        started = cfg["created_at"] + 0.01 + index * 0.01
        _collect("tenant-a", address, {"workerData": [workers[0]]},
                 started=started, completed=started + 0.001)
    points = evidence.read("tenant-a", "mrr", "bounded")["points"]
    assert len(points) == 2
