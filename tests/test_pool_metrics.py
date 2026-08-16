"""
CYPHER65 // persistent pool metrics — Issue #17
================================================
Tests for services/pool_metrics (SQLite health-sampler storage) + the
/api/admin/pool-metrics route. Covers record/fetch/dedupe/purge, the sampler
loop's resilience to a failing stats source, and the admin-gated endpoint.
"""

import sqlite3
import threading
import time

import pytest

import services.pool_metrics as pool_metrics_module
from services.pool_metrics import (
    POOL_METRICS_INDEX,
    POOL_METRICS_SCHEMA,
    fetch_history,
    purge_pool_metrics,
    record_snapshot,
    sampler_loop,
)


@pytest.fixture
def conn():
    """In-memory DB with the pool_metrics schema (row_factory=Row)."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute(POOL_METRICS_SCHEMA)
    c.execute(POOL_METRICS_INDEX)
    yield c
    c.close()


def _stats(**overrides):
    s = {
        "sessions_active": 12,
        "scheduled": 3,
        "queue_pending": 2,
        "workers_alive": 8,
        "pool_size": 8,
        "total_polls": 4100,
        "total_errors": 2,
        "polls_per_sec": 3.5,
        "uptime_secs": 86400.0,
        "last_poll_ts": 12345.0,
        "stalled": False,
        "webhook_queue": 1,
        "auto_exclude_total": 4,
    }
    s.update(overrides)
    return s


def _count(conn):
    return conn.execute("SELECT COUNT(*) FROM pool_metrics").fetchone()[0]


# ═════════════════════════════════════════════════════════════════════════
#  record / fetch
# ═════════════════════════════════════════════════════════════════════════


class TestRecordFetch:
    def test_record_then_fetch_roundtrip(self, conn):
        ts = int(time.time())
        assert record_snapshot(conn, _stats(), ts=ts) == 1
        rows = fetch_history(conn, hours=24)
        assert len(rows) == 1
        r = rows[0]
        assert r["ts"] == ts
        assert r["sessions_active"] == 12
        assert r["polls_per_sec"] == 3.5
        assert r["queue_pending"] == 2
        assert r["total_polls"] == 4100
        # boolean → int for the SQLite column
        assert r["stalled"] == 0
        assert r["webhook_queue"] == 1
        assert r["auto_exclude_total"] == 4

    def test_record_dedupe_same_second(self, conn):
        ts = int(time.time())
        assert record_snapshot(conn, _stats(), ts=ts) == 1
        # A double-fired sampler tick in the same second is ignored.
        assert record_snapshot(conn, _stats(sessions_active=99), ts=ts) == 0
        assert _count(conn) == 1

    def test_fetch_hours_window_excludes_old(self, conn):
        now = int(time.time())
        record_snapshot(conn, _stats(), ts=now)
        record_snapshot(conn, _stats(sessions_active=7), ts=now - 48 * 3600)
        rows = fetch_history(conn, hours=24)
        assert [r["sessions_active"] for r in rows] == [12]

    def test_fetch_limit_returns_most_recent_ascending(self, conn):
        now = int(time.time())
        for i in range(5):
            record_snapshot(conn, _stats(sessions_active=10 + i), ts=now - i)
        rows = fetch_history(conn, hours=24, limit=3)
        # ts=now(10), now-1(11), now-2(12) are the most recent 3 → ascending
        assert [r["sessions_active"] for r in rows] == [12, 11, 10]

    def test_purge_only_removes_old(self, conn):
        now = int(time.time())
        record_snapshot(conn, _stats(), ts=now)
        record_snapshot(conn, _stats(sessions_active=7), ts=now - 8 * 86400)
        deleted = purge_pool_metrics(conn, days=7)
        assert deleted == 1
        assert _count(conn) == 1
        assert fetch_history(conn, hours=24)[0]["sessions_active"] == 12


# ═════════════════════════════════════════════════════════════════════════
#  sampler loop
# ═════════════════════════════════════════════════════════════════════════


class TestSamplerLoop:
    @pytest.fixture
    def db_file(self, tmp_path):
        """File-backed scratch DB: sqlite forbids using a connection from
        another thread, so conn_fn() opens a fresh connection per tick
        (exactly like the real app's get_db())."""
        path = str(tmp_path / "pool_metrics.sqlite")
        c = sqlite3.connect(path)
        c.execute(POOL_METRICS_SCHEMA)
        c.execute(POOL_METRICS_INDEX)
        c.commit()
        c.close()
        return path

    def test_sampler_records_periodically(self, db_file, monkeypatch):
        # Fake clock: each tick advances 60s so every snapshot gets a distinct
        # ts (real time would dedupe all ticks into the same second).
        fake = {"now": 1_700_000_000.0}
        monkeypatch.setattr(pool_metrics_module.time, "time", lambda: fake["now"])
        stop = threading.Event()
        calls = {"n": 0}

        def _stats_fn():
            fake["now"] += 60.0
            calls["n"] += 1
            return _stats(sessions_active=calls["n"])

        def _conn_fn():
            c = sqlite3.connect(db_file)
            c.row_factory = sqlite3.Row
            return c

        t = threading.Thread(
            target=sampler_loop,
            kwargs={
                "stats_fn": _stats_fn,
                "conn_fn": _conn_fn,
                "interval": 0.02,
                "jitter": 0.0,
                "stop_event": stop,
            },
            daemon=True,
        )
        t.start()
        time.sleep(0.12)  # ~6 ticks
        stop.set()
        t.join(timeout=2)
        assert not t.is_alive()
        db = sqlite3.connect(db_file)
        try:
            rows = db.execute(
                "SELECT sessions_active FROM pool_metrics ORDER BY ts ASC"
            ).fetchall()
        finally:
            db.close()
        assert len(rows) >= 2
        assert rows[-1][0] > rows[0][0]

    def test_sampler_survives_failing_stats_source(self, db_file, monkeypatch):
        fake = {"now": 1_700_000_000.0}
        monkeypatch.setattr(pool_metrics_module.time, "time", lambda: fake["now"])
        stop = threading.Event()
        calls = {"n": 0}

        def _stats_fn():
            fake["now"] += 60.0
            calls["n"] += 1
            if calls["n"] % 2 == 1:
                raise RuntimeError("upstream poll pool broken (mock)")
            return _stats()

        def _conn_fn():
            return sqlite3.connect(db_file)

        t = threading.Thread(
            target=sampler_loop,
            kwargs={
                "stats_fn": _stats_fn,
                "conn_fn": _conn_fn,
                "interval": 0.02,
                "jitter": 0.0,
                "stop_event": stop,
            },
            daemon=True,
        )
        t.start()
        time.sleep(0.12)  # even-numbered ticks succeed
        stop.set()
        t.join(timeout=2)
        assert not t.is_alive()  # the loop must NOT die on the error
        db = sqlite3.connect(db_file)
        try:
            n = db.execute("SELECT COUNT(*) FROM pool_metrics").fetchone()[0]
        finally:
            db.close()
        assert n >= 1  # at least the healthy ticks landed


# ═════════════════════════════════════════════════════════════════════════
#  Admin endpoint (localhost gate — test client counts as local)
# ═════════════════════════════════════════════════════════════════════════


class TestAdminEndpoint:
    def test_pool_metrics_route_returns_history(self):
        import app as app_module

        # Seed one row so the endpoint has data to return.
        conn = app_module.get_db()
        try:
            record_snapshot(conn, _stats(), ts=int(time.time()))
        finally:
            conn.close()

        client = app_module.app.test_client()
        r = client.get(
            "/api/admin/pool-metrics?hours=24",
            headers={"X-Requested-With": "fetch"},
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data["hours"] == 24
        assert data["count"] >= 1
        assert data["points"][0]["sessions_active"] == 12
        assert data["points"][0]["ts"] > 0

    def test_pool_metrics_route_limits(self):
        import app as app_module

        client = app_module.app.test_client()
        # hours out of range → clamped to 24; limit too big → clamped to 0 (all)
        r = client.get("/api/admin/pool-metrics?hours=999&limit=99999")
        assert r.status_code == 200
        data = r.get_json()
        assert data["hours"] == 24
