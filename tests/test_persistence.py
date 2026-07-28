"""
Unit tests for wallet address persistence logic in app.py.

Tests `_load_persisted_address()` which reads `_btc_address`
from the settings DB and overrides the module-level BTC_ADDRESS global.

Each test monkeypatches `app.get_db` to control what the DB returns,
then verifies that `app.BTC_ADDRESS` is (or is not) modified and that
the function return value is correct.
"""

import pytest
import logging

# ── Module-level test helpers ────────────────────────────────────────────────
# We import app at module level so all tests share the same module reference.
# The import triggers init_db() and _load_persisted_address() once (runs
# the real DB on first import), but each test replaces app.get_db with a mock
# and calls the function again under controlled conditions.

import app as _app_module  # noqa: E402

# Reference the function under test
_load_persisted_address = _app_module._load_persisted_address


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_conn_with_address():
    """Return a MockConn whose cursor returns a saved _btc_address."""
    from tests.conftest import MockRow, MockCursor, MockConn
    row = MockRow({"value": "bc1qtestwallet123abc456def789ghi012jklmno"})
    cursor = MockCursor(fetchone_result=row)
    return MockConn(cursor)


@pytest.fixture
def mock_conn_empty():
    """Return a MockConn whose cursor returns None (no _btc_address saved)."""
    from tests.conftest import MockCursor, MockConn
    cursor = MockCursor(fetchone_result=None)
    return MockConn(cursor)


# ── Test 1: DB has a saved address → BTC_ADDRESS is overwritten ──────────────

class TestRestoreWithAddress:
    """_load_persisted_address reads a valid _btc_address from DB."""

    def test_overwrites_global(self, monkeypatch, mock_conn_with_address):
        """Should set app.BTC_ADDRESS to the persisted address."""
        monkeypatch.setattr(_app_module, "get_db", lambda: mock_conn_with_address)

        # Save original and set a known default
        original = _app_module.BTC_ADDRESS
        _app_module.BTC_ADDRESS = "bc1qdefaultaddress0000000000000000000000000"
        try:
            result = _load_persisted_address()
            assert result is True, "Expected True when address is restored"
            assert _app_module.BTC_ADDRESS == "bc1qtestwallet123abc456def789ghi012jklmno"
        finally:
            _app_module.BTC_ADDRESS = original

    def test_returns_true(self, monkeypatch, mock_conn_with_address):
        """Should return True when a valid address is found in DB."""
        monkeypatch.setattr(_app_module, "get_db", lambda: mock_conn_with_address)
        original = _app_module.BTC_ADDRESS
        _app_module.BTC_ADDRESS = "bc1qoriginalxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        try:
            result = _load_persisted_address()
            assert result is True
        finally:
            _app_module.BTC_ADDRESS = original

    def test_closes_conn(self, monkeypatch, mock_conn_with_address):
        """Connection should be closed after restore."""
        monkeypatch.setattr(_app_module, "get_db", lambda: mock_conn_with_address)
        original = _app_module.BTC_ADDRESS
        _app_module.BTC_ADDRESS = "bc1qoriginalxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        try:
            _load_persisted_address()
            assert mock_conn_with_address.closed is True
        finally:
            _app_module.BTC_ADDRESS = original


# ── Test 2: DB is empty → BTC_ADDRESS unchanged, returns False ───────────────

class TestRestoreEmptyDB:
    """_load_persisted_address when DB has no _btc_address."""

    def test_keeps_original_global(self, monkeypatch, mock_conn_empty):
        """Should NOT modify app.BTC_ADDRESS when DB is empty."""
        monkeypatch.setattr(_app_module, "get_db", lambda: mock_conn_empty)
        original = _app_module.BTC_ADDRESS
        _app_module.BTC_ADDRESS = "bc1qkeepsamexxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        try:
            result = _load_persisted_address()
            assert result is False, "Expected False when no address in DB"
            assert _app_module.BTC_ADDRESS == "bc1qkeepsamexxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        finally:
            _app_module.BTC_ADDRESS = original

    def test_returns_false(self, monkeypatch, mock_conn_empty):
        """Should return False when no address is saved."""
        monkeypatch.setattr(_app_module, "get_db", lambda: mock_conn_empty)
        original = _app_module.BTC_ADDRESS
        _app_module.BTC_ADDRESS = "bc1qanotherxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        try:
            result = _load_persisted_address()
            assert result is False
        finally:
            _app_module.BTC_ADDRESS = original

    def test_rejects_short_address(self, monkeypatch):
        """Address shorter than 10 chars should NOT overwrite global."""
        from tests.conftest import MockRow, MockCursor, MockConn
        row = MockRow({"value": "short"})
        cursor = MockCursor(fetchone_result=row)
        conn = MockConn(cursor)
        monkeypatch.setattr(_app_module, "get_db", lambda: conn)

        original = _app_module.BTC_ADDRESS
        _app_module.BTC_ADDRESS = "bc1qpreservexxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        try:
            result = _load_persisted_address()
            assert result is False, "Expected False for address < 10 chars"
            assert _app_module.BTC_ADDRESS == "bc1qpreservexxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        finally:
            _app_module.BTC_ADDRESS = original

    def test_closes_conn_on_no_result(self, monkeypatch, mock_conn_empty):
        """Connection should be closed even when no address is found."""
        monkeypatch.setattr(_app_module, "get_db", lambda: mock_conn_empty)
        original = _app_module.BTC_ADDRESS
        _app_module.BTC_ADDRESS = "bc1qclosesconnxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        try:
            _load_persisted_address()
            assert mock_conn_empty.closed is True
        finally:
            _app_module.BTC_ADDRESS = original


# ── Test 3: DB access raises exception → BTC_ADDRESS unchanged, returns False ─

class TestRestoreDBError:
    """_load_persisted_address when get_db() raises an exception."""

    def test_keeps_original_on_exception(self, monkeypatch):
        """Should NOT modify BTC_ADDRESS when get_db raises."""
        def failing_get_db():
            raise RuntimeError("DB connection failed")

        monkeypatch.setattr(_app_module, "get_db", failing_get_db)
        original = _app_module.BTC_ADDRESS
        _app_module.BTC_ADDRESS = "bc1qpreserveonerrorxxxxxxxxxxxxxxxxxxxxxxx"
        try:
            result = _load_persisted_address()
            assert result is False, "Expected False when get_db raises"
            assert _app_module.BTC_ADDRESS == "bc1qpreserveonerrorxxxxxxxxxxxxxxxxxxxxxxx"
        finally:
            _app_module.BTC_ADDRESS = original

    def test_returns_false_on_exception(self, monkeypatch):
        """Should return False when DB access fails."""
        def failing_get_db():
            raise ValueError("corrupt DB")

        monkeypatch.setattr(_app_module, "get_db", failing_get_db)
        original = _app_module.BTC_ADDRESS
        _app_module.BTC_ADDRESS = "bc1qshouldstayxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        try:
            result = _load_persisted_address()
            assert result is False
        finally:
            _app_module.BTC_ADDRESS = original

    def test_execute_raises(self, monkeypatch):
        """Should handle cursor.execute() failures gracefully."""
        class CursorRaises:
            def execute(self, sql, params=None):  # noqa: ARG002
                raise RuntimeError("SQL error")
            def fetchone(self):
                return None  # Should not be reached

        class ConnRaises:
            def cursor(self):
                return CursorRaises()
            def close(self):
                pass

        monkeypatch.setattr(_app_module, "get_db", lambda: ConnRaises())
        original = _app_module.BTC_ADDRESS
        _app_module.BTC_ADDRESS = "bc1qhandlesexecerrorxxxxxxxxxxxxxxxxxxxxxxx"
        try:
            result = _load_persisted_address()
            assert result is False, "Expected False when execute raises"
            assert _app_module.BTC_ADDRESS == "bc1qhandlesexecerrorxxxxxxxxxxxxxxxxxxxxxxx"
        finally:
            _app_module.BTC_ADDRESS = original
