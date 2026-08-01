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
    """
    conn = sqlite3.connect(os.environ.get("DB_PATH", DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn
