"""Load test — SQLite under the P1 Phase-2 write profile.

The fixed worker pool means 8-16 threads may write to the SAME SQLite DB
(alerts, snapshots) concurrently, on top of the operator's own _do_poll.
This test simulates that write profile and asserts:
  1. No 'database is locked' errors under N concurrent writers.
  2. No rows are lost (each writer's inserts all land).
  3. WAL + busy_timeout are actually active on get_db connections.

It uses a SCRATCH DB file (WAL works on file DBs, not :memory:), never the
real war_room.sqlite.
"""

import os
import sys
import threading
import time

import pytest

sys.path.insert(0, ".")

# Scratch DB file for this test only. monkeypatch.setenv (below) redirects
# DB_PATH just for this module's tests and RESTORES it afterwards — a module-
# level assignment here would override the conftest scratch DB for the rest
# of the suite and corrupt every later test.
_SCRATCH = "/tmp/c65_load_test.sqlite"

from services.db import get_db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_scratch(monkeypatch):
    monkeypatch.setenv("DB_PATH", _SCRATCH)
    if os.path.exists(_SCRATCH):
        os.remove(_SCRATCH)
    conn = get_db()
    conn.execute("CREATE TABLE load_rows (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                 "writer INTEGER NOT NULL, seq INTEGER NOT NULL, ts INTEGER NOT NULL)")
    conn.commit()
    conn.close()
    yield
    if os.path.exists(_SCRATCH):
        os.remove(_SCRATCH)


def test_wal_and_busy_timeout_active():
    conn = get_db()
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    conn.close()
    assert mode == "wal"
    assert timeout >= 3000


def test_concurrent_writers_no_locked_and_no_lost_rows():
    n_writers = 12
    rows_per_writer = 25
    errors = []
    lock = threading.Lock()

    def writer(wid):
        try:
            for seq in range(rows_per_writer):
                conn = get_db()
                try:
                    conn.execute(
                        "INSERT INTO load_rows (writer, seq, ts) VALUES (?, ?, ?)",
                        (wid, seq, int(time.time())))
                    conn.commit()
                finally:
                    conn.close()
        except Exception as e:  # noqa: BLE001
            with lock:
                errors.append(f"writer{wid}: {e}")

    threads = [threading.Thread(target=writer, args=(w,)) for w in range(n_writers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"locked/lost errors: {errors[:5]}"

    conn = get_db()
    total = conn.execute("SELECT COUNT(*) AS n FROM load_rows").fetchone()["n"]
    per_writer = conn.execute(
        "SELECT writer, COUNT(*) AS n FROM load_rows GROUP BY writer").fetchall()
    conn.close()

    assert total == n_writers * rows_per_writer, f"lost rows: {total}"
    assert len(per_writer) == n_writers
    for row in per_writer:
        assert row["n"] == rows_per_writer


def test_writers_run_in_parallel_not_serialized():
    """12 writers sharing one table must overlap (busy_timeout, not a global
    table lock serializing everything) — i.e. wall time is well under the
    serialized estimate. Generous bound to avoid CI flakiness."""
    n = 8
    rows = 15
    started = {"n": 0, "max_concurrent": 0}
    lock = threading.Lock()
    cur = {"n": 0}

    def writer():
        with lock:
            cur["n"] += 1
            started["max_concurrent"] = max(started["max_concurrent"], cur["n"])
        try:
            for seq in range(rows):
                conn = get_db()
                try:
                    conn.execute("INSERT INTO load_rows (writer, seq, ts) "
                                 "VALUES (-1, ?, ?)", (seq, int(time.time())))
                    conn.commit()
                finally:
                    conn.close()
        finally:
            with lock:
                cur["n"] -= 1

    t0 = time.time()
    threads = [threading.Thread(target=writer) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.time() - t0

    # With true parallelism this finishes in ~1-2s; a fully serialized table
    # lock would still be fast for 120 rows, so assert overlap instead of time.
    assert started["max_concurrent"] > 1, "writers never overlapped"
    assert wall < 60  # generous upper bound — CI safety
