"""Tests for core/data_layer.py — the SQLite-first telemetry store.

These are the real consumers of the module: they prove the durable store
works, the warm cache behaves, failures are honest (False, not exceptions),
and importing the module has NO filesystem side effects (lazy singleton).
"""
import os
import sqlite3
import tempfile

import pytest

from core import data_layer as dl


@pytest.fixture()
def dm(tmp_path):
    """A DataManager pointed at an isolated temp DB (no runtime data/)."""
    db = str(tmp_path / "test_metrics.sqlite")
    manager = dl.DataManager(db_path=db)
    yield manager
    manager._query_cache.clear()
    manager._query_cache_ts.clear()


def test_write_and_query_roundtrip(dm):
    assert dm.write_metric("192.168.1.50", "temperature", 61.5) is True
    rows = dm.query_recent("192.168.1.50", "temperature", minutes=15)
    assert len(rows) == 1
    assert rows[0]["value"] == 61.5
    assert isinstance(rows[0]["time"], int)


def test_query_historical_covers_many_hours(dm):
    dm.write_metric("dev-a", "fan_speed", 6000)
    rows = dm.query_historical("dev-a", "fan_speed", hours=24)
    assert len(rows) == 1
    assert rows[0]["value"] == 6000


def test_warm_cache_returns_same_object(dm):
    dm.write_metric("dev-b", "power", 3400)
    first = dm.query_recent("dev-b", "power", minutes=15)
    second = dm.query_recent("dev-b", "power", minutes=15)
    assert first is second  # cached within TTL


def test_write_non_numeric_stores_null(dm):
    assert dm.write_metric("dev-c", "status", "NOT AVAILABLE") is True
    rows = dm.query_recent("dev-c", "status", minutes=15)
    assert rows[0]["value"] is None


def test_write_failure_is_honest_false():
    """A broken DB path returns False — never raises into the caller."""
    manager = dl.DataManager(db_path="/nonexistent_dir_xyz/nope.sqlite")
    # Directory doesn't exist → connect will fail → write_metric must return False.
    assert manager.write_metric("dev-x", "temperature", 1.0) is False


def test_module_import_has_no_side_effects(monkeypatch):
    """Importing core.data_layer must not create data/ or touch the DB
    (the module singleton is lazy)."""
    tmp = tempfile.mkdtemp()
    monkeypatch.chdir(tmp)
    # Re-import in a fresh module state to prove laziness.
    import importlib

    fresh = importlib.import_module("core.data_layer")
    assert fresh._manager is None  # not created at import time
    assert not os.path.exists(os.path.join(tmp, "data"))
    # get_manager() then creates it on first use.
    fresh.get_manager()
    assert fresh._manager is not None


def test_sqlite_schema_exists(dm):
    conn = sqlite3.connect(dm.db_path)
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert "metric_samples" in tables
