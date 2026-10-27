"""Real SQLite regressions for cache boundaries, not HTTP tenant certification."""

from concurrent.futures import ThreadPoolExecutor
import sqlite3
from types import SimpleNamespace

from core import data_layer
from core.data_layer import DataManager


def test_managers_for_different_databases_never_share_rows(tmp_path):
    first = DataManager(str(tmp_path / "a.sqlite"))
    second = DataManager(str(tmp_path / "b.sqlite"))
    assert first.write_metric("same-device", "power", 10)
    assert second.write_metric("same-device", "power", 20)
    assert first.query_recent("same-device", "power")[0]["value"] == 10
    assert second.query_recent("same-device", "power")[0]["value"] == 20


def test_successful_write_invalidates_every_matching_window(tmp_path):
    manager = DataManager(str(tmp_path / "metrics.sqlite"))
    assert manager.write_metric("device", "power", 10)
    short = manager.query_recent("device", "power", minutes=15)
    long = manager.query_recent("device", "power", minutes=60)
    assert manager.query_recent("device", "power", minutes=15) is short
    assert manager.write_metric("device", "power", 20)
    assert [row["value"] for row in manager.query_recent("device", "power", 15)] == [
        10,
        20,
    ]
    assert [row["value"] for row in manager.query_recent("device", "power", 60)] == [
        10,
        20,
    ]
    assert short == long


def test_delimited_device_and_metric_names_do_not_collide(tmp_path):
    manager = DataManager(str(tmp_path / "metrics.sqlite"))
    assert manager.write_metric("device:sub", "metric", 10)
    assert manager.write_metric("device", "sub:metric", 20)
    assert manager.query_recent("device:sub", "metric")[0]["value"] == 10
    assert manager.query_recent("device", "sub:metric")[0]["value"] == 20


def test_reads_do_not_republish_stale_cache_after_concurrent_writes(tmp_path):
    manager = DataManager(str(tmp_path / "metrics.sqlite"))
    assert manager.write_metric("device", "power", 0)
    manager.query_recent("device", "power")

    def write_and_read(value):
        assert manager.write_metric("device", "power", value)
        return len(manager.query_recent("device", "power"))

    with ThreadPoolExecutor(max_workers=8) as workers:
        counts = list(workers.map(write_and_read, range(1, 33)))
    assert min(counts) >= 2
    rows = manager.query_recent("device", "power")
    assert len(rows) == 33
    assert sorted(row["value"] for row in rows) == list(range(33))


def test_warm_cache_has_bounded_retention(tmp_path):
    manager = DataManager(str(tmp_path / "metrics.sqlite"))
    for index in range(300):
        assert manager.query_recent(f"empty-{index}", "power") == []
    assert len(manager._query_cache) <= 256
    assert len(manager._query_cache_ts) <= 256


def test_expired_cache_reloads_external_database_changes(tmp_path, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(data_layer, "time", SimpleNamespace(time=lambda: clock[0]))
    manager = DataManager(str(tmp_path / "metrics.sqlite"))
    assert manager.write_metric("device", "power", 10)
    original = manager.query_recent("device", "power")
    with sqlite3.connect(manager.db_path) as conn:
        conn.execute(
            "INSERT INTO metric_samples(device_id,metric,value,ts) VALUES(?,?,?,?)",
            ("device", "power", 20, 1000),
        )
    assert manager.query_recent("device", "power") is original
    clock[0] += 301
    assert [row["value"] for row in manager.query_recent("device", "power")] == [10, 20]


def test_failed_write_does_not_publish_or_invalidate_cache(tmp_path, monkeypatch):
    manager = DataManager(str(tmp_path / "metrics.sqlite"))
    assert manager.write_metric("device", "power", 10)
    original = manager.query_recent("device", "power")

    def busy(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(data_layer.sqlite3, "connect", busy)
    assert manager.write_metric("device", "power", 20) is False
    assert manager.query_recent("device", "power") is original


def test_public_wrappers_share_only_the_selected_manager(tmp_path, monkeypatch):
    manager = DataManager(str(tmp_path / "metrics.sqlite"))
    monkeypatch.setattr(data_layer, "_manager", manager)
    assert data_layer.get_manager() is manager
    assert data_layer.write_metric("device", "power", 10)
    assert data_layer.query_recent("device", "power")[0]["value"] == 10
    assert data_layer.query_historical("device", "power")[0]["value"] == 10


def test_invalidation_preserves_unrelated_cached_metrics(tmp_path):
    manager = DataManager(str(tmp_path / "metrics.sqlite"))
    assert manager.write_metric("device", "temperature", 60)
    temperature = manager.query_recent("device", "temperature")
    assert manager.write_metric("device", "power", 10)
    assert manager.query_recent("device", "temperature") is temperature


def test_existing_mirror_circuit_recovers_after_its_cooldown(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(data_layer, "time", SimpleNamespace(time=lambda: clock[0]))
    breaker = data_layer.CircuitBreaker(max_fails=2, cooldown=10)
    breaker.failure()
    assert breaker.allow()
    breaker.failure()
    assert not breaker.allow()
    clock[0] += 11
    assert breaker.allow()
    breaker.success()
    assert breaker._fail_ts == []
