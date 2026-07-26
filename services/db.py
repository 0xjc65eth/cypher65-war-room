"""
CYPHER65 — Database access layer
=================================
Shared SQLite connection helper used by all routes and services.
"""

import sqlite3
import config

DB_PATH = config.DB_PATH


def get_db():
    """Return a new SQLite connection with row_factory set."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
