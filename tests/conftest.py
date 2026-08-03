"""
CYPHER65 // Test fixtures
=========================
Shared mock utilities for unit-testing app.py persistence functions.
"""

import logging
import os
import tempfile

# Silence noisy loggers during tests
logging.disable(logging.CRITICAL)

# ── C4 // HERMETIC SUITE ────────────────────────────────────────────────────
# Never touch the production data/war_room.sqlite. The recurring index
# corruption (idx_maintenance_records_ts / idx_audit_logs_tenant_ts) was
# caused by TWO WRITERS on the same file: the Docker/Colima app writing via
# its volume mount, and pytest's `import app` — which runs init_db() +
# _core_registry.load_from_db() at module scope in ~20 test files — hitting
# the real DB from the host.
#
# Redirect the env var BEFORE any test module imports `app` (conftest is
# imported first by pytest, so the scratch path is in effect for every
# module-level `import app`). Per-test DB_PATH overrides still win where a
# test needs its own scratch DB via monkeypatch.setenv.
_SCRATCH_DIR = tempfile.mkdtemp(prefix="cypher65_tests_")
os.environ["DB_PATH"] = os.path.join(_SCRATCH_DIR, "war_room.sqlite")


class MockRow:
    """Mimics sqlite3.Row dict-like access for test mocking.
    The real sqlite3.Row supports r["key"] access — this mock
    replicates only the interface that _restore_btc_address_from_db
    actually uses (__getitem__ with string keys).
    """
    def __init__(self, data: dict):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]

    def __bool__(self):
        return bool(self._data)


class MockCursor:
    """Mimics sqlite3.Cursor with a configurable fetchone return value."""

    def __init__(self, fetchone_result=None):
        self._result = fetchone_result
        self.executed_sql = None

    def execute(self, sql, params=None):
        self.executed_sql = sql
        return self

    def fetchone(self):
        return self._result


class MockConn:
    """Mimics sqlite3.Connection, returning a given cursor on cursor()."""

    def __init__(self, cursor: MockCursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True
