"""
CYPHER65 // REVOKED_TOKENS_DB — multi-process JWT blacklist persistence
=======================================================================
Single-process deploys rely on the in-memory OrderedDict blacklist.
REVOKED_TOKENS_DB=1 additionally persists revocations to the SQLite
`revoked_tokens` table so a gunicorn/worker topology shares the blacklist
(process A's logout is enforced by process B).

Locks three properties:
- OFF by default: no env var → no DB file is ever created, memory path
  unchanged (the existing test_auth_hardening.py FIFO suite stays green).
- ON: revoke persists; verify honors a revocation from "another process"
  (simulated by clearing the in-memory dict and verifying again).
- Best-effort: DB write failures never raise and never break auth.
"""
import os
import sqlite3

import pytest

import app as _app_module
from services.auth import (
    _blacklisted_tokens,
    create_token,
    revoke_token,
    verify_token,
    _revoked_db_path,
)

app = _app_module.app

_TEST_SECRET = "h" * 32


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    """Every test: clean in-memory blacklist + isolated DB + fixed secret."""
    monkeypatch.setenv("SECRET_KEY", _TEST_SECRET)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "war_room.sqlite"))
    app.config["TESTING"] = True
    _blacklisted_tokens.clear()
    yield
    _blacklisted_tokens.clear()


@pytest.fixture
def revoked_db_enabled(monkeypatch):
    monkeypatch.setenv("REVOKED_TOKENS_DB", "1")


def _mint() -> str:
    with app.app_context():
        return create_token(subject="u1", extra_claims={"role": "viewer"})


def _db_has_token(token: str, db_path: str) -> bool:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM revoked_tokens WHERE token = ?", (token,)
        ).fetchone()
    return row is not None


class TestRevokedTokensDb:
    def test_disabled_by_default_no_db_file(self, tmp_path):
        """Default (no REVOKED_TOKENS_DB): persistence is a no-op — the
        DB file must not even be created (the scratch path stays empty)."""
        assert _revoked_db_path() is None
        token = _mint()
        assert revoke_token(token) is True
        # Memory path still works
        assert verify_token(token) is None
        db = tmp_path / "war_room.sqlite"
        assert not db.exists(), "DB must not be touched when REVOKED_TOKENS_DB is unset"

    def test_persists_revocation_to_sqlite(self, revoked_db_enabled, tmp_path):
        token = _mint()
        assert revoke_token(token) is True
        assert _db_has_token(token, str(tmp_path / "war_room.sqlite"))

    def test_other_process_honors_shared_blacklist(self, revoked_db_enabled, tmp_path):
        """Simulate a second process: the in-memory dict is empty (like a
        fresh worker), but verify must still reject the token persisted by
        the first process via SQLite."""
        token = _mint()
        assert revoke_token(token) is True
        # "Restart" — another process has no memory of this revocation.
        _blacklisted_tokens.clear()
        assert token not in _blacklisted_tokens
        assert verify_token(token) is None, \
            "revocation must be honored from the shared SQLite blacklist"

    def test_verify_does_not_block_valid_token(self, revoked_db_enabled, tmp_path):
        token = _mint()
        # Never revoked → verify succeeds even with persistence enabled.
        assert verify_token(token) is not None

    def test_unrevoked_token_survives_restart_clear(self, revoked_db_enabled, tmp_path):
        """A valid, never-revoked token must NOT be blocked after the
        in-memory dict is cleared (no phantom revocations in SQLite)."""
        token = _mint()
        _blacklisted_tokens.clear()
        assert verify_token(token) is not None

    def test_persist_failure_is_best_effort(self, revoked_db_enabled, tmp_path, monkeypatch):
        """A DB failure on persist must never break revoke/verify — the
        in-memory path remains authoritative for the single process."""
        token = _mint()
        monkeypatch.setattr("services.auth.sqlite3.connect",
                            lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("locked")))
        assert revoke_token(token) is True   # no raise
        assert verify_token(token) is None   # memory blacklist still blocks
