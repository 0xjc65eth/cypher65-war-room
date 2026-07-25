"""
CYPHER65 // Test fixtures
=========================
Shared mock utilities for unit-testing app.py persistence functions.
"""

import logging

# Silence noisy loggers during tests
logging.disable(logging.CRITICAL)


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
