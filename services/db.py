"""
CYPHER65 — Database access layer
=================================
Shared SQLite connection helper used by all routes and services.
"""

import os
import sqlite3
import config

DB_PATH = config.DB_PATH


def get_db():
    """Return a new SQLite connection with row_factory set.

    DB_PATH is read from the environment at call time (falling back to
    config.DB_PATH) so test suites can redirect every query to a scratch DB
    with monkeypatch.setenv('DB_PATH', ...) — no import-order tricks needed.

    Audit C5: every connection enables WAL + busy_timeout so concurrent
    polling writers never hit "database is locked" and readers see fresh
    data. Best-effort — WAL is unavailable on :memory: DBs and the pragmas
    are skipped rather than raised.
    """
    conn = sqlite3.connect(os.environ.get("DB_PATH", DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=3000")
    except sqlite3.Error:
        pass
    return conn
