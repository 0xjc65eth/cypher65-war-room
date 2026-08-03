"""
CYPHER65 // C4 — Automatic SQLite backup & integrity
=====================================================
Hermetic unit tests for services/db_backup.py.

These tests NEVER import `app` and never touch the production
data/war_room.sqlite — every DB is a scratch file under tmp_path, and the
backup dir is derived from the scratch DB path.
"""
import os
import sqlite3

import pytest

import services.db_backup as db_backup


# ── Helpers ─────────────────────────────────────────────────────────────────

def _make_db(path, rows=3):
    """Create a valid scratch SQLite DB with a table + N rows."""
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        for i in range(rows):
            conn.execute("INSERT INTO t (v) VALUES (?)", ("row-%d" % i,))
        conn.commit()
    finally:
        conn.close()
    return path


# ── backup_now ──────────────────────────────────────────────────────────────

class TestBackupNow:
    def test_creates_valid_backup_with_data(self, tmp_path):
        src = _make_db(tmp_path / "src.sqlite")
        dest_dir = tmp_path / "backups"

        out = db_backup.backup_now(str(src), dest_dir=str(dest_dir), keep=5)

        assert os.path.exists(out)
        # The backup must be openable and carry the same rows.
        conn = sqlite3.connect(out)
        try:
            n = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
            assert n == 3
        finally:
            conn.close()

    def test_backup_files_are_independent(self, tmp_path):
        src = _make_db(tmp_path / "src.sqlite", rows=2)
        dest_dir = tmp_path / "backups"
        first = db_backup.backup_now(str(src), dest_dir=str(dest_dir), keep=5)

        # Mutate source afterwards — the snapshot must not change.
        conn = sqlite3.connect(str(src))
        try:
            conn.execute("INSERT INTO t (v) VALUES ('later')")
            conn.commit()
        finally:
            conn.close()

        conn = sqlite3.connect(first)
        try:
            assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
        finally:
            conn.close()


# ── prune_backups / latest_backup ───────────────────────────────────────────

class TestRetention:
    def test_prune_keeps_only_newest(self, tmp_path):
        src = _make_db(tmp_path / "src.sqlite")
        dest_dir = tmp_path / "backups"
        for _ in range(5):
            db_backup.backup_now(str(src), dest_dir=str(dest_dir), keep=10)
        # 5 backups exist; prune to 2.
        db_backup.prune_backups(str(dest_dir), keep=2)
        remaining = sorted(os.listdir(str(dest_dir)))
        assert len(remaining) == 2

    def test_latest_backup_returns_newest(self, tmp_path):
        src = _make_db(tmp_path / "src.sqlite")
        dest_dir = tmp_path / "backups"
        paths = [db_backup.backup_now(str(src), dest_dir=str(dest_dir), keep=10)
                 for _ in range(3)]
        assert db_backup.latest_backup(dest_dir=str(dest_dir)) == paths[-1]

    def test_latest_backup_none_when_empty(self, tmp_path):
        assert db_backup.latest_backup(dest_dir=str(tmp_path / "empty")) is None


# ── integrity_ok ────────────────────────────────────────────────────────────

class TestIntegrity:
    def test_ok_on_valid_db(self, tmp_path):
        src = _make_db(tmp_path / "ok.sqlite")
        assert db_backup.integrity_ok(str(src)) is True

    def test_false_on_corrupt_db(self, tmp_path):
        bad = tmp_path / "corrupt.sqlite"
        bad.write_bytes(b"this is not a sqlite database at all" * 10)
        assert db_backup.integrity_ok(str(bad)) is False

    def test_true_when_missing(self, tmp_path):
        assert db_backup.integrity_ok(str(tmp_path / "missing.sqlite")) is True


# ── env gating ──────────────────────────────────────────────────────────────

class TestEnvGating:
    def test_backup_enabled_by_default(self, monkeypatch):
        monkeypatch.delenv("AUTO_BACKUP_INTERVAL", raising=False)
        assert db_backup.backup_enabled() is True

    def test_backup_disabled_with_zero(self, monkeypatch):
        monkeypatch.setenv("AUTO_BACKUP_INTERVAL", "0")
        assert db_backup.backup_enabled() is False

    def test_backup_loop_snapshots_then_exits_when_disabled(self, tmp_path, monkeypatch):
        src = _make_db(tmp_path / "src.sqlite")
        monkeypatch.setenv("AUTO_BACKUP_INTERVAL", "0")
        dest_dir = tmp_path / "backups"
        # Loop must take one snapshot and return (interval <= 0), not hang.
        db_backup.backup_loop(db_path=str(src))
        remaining = os.listdir(str(dest_dir))
        assert len(remaining) == 1
