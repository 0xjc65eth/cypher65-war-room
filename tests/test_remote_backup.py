"""
Hermetic tests for the zero-cost remote backup (GitHub gist) service.
Covers env-gating, snapshot→gist round-trip, boot-restore guard, and the
loop worker. All GitHub API calls are mocked — no network.
"""

import os
import sqlite3
import sys
import types

import pytest
from cryptography.fernet import Fernet

sys.path.insert(0, ".")

import services.remote_backup as rb  # noqa: E402

TEST_BACKUP_KEY = Fernet.generate_key().decode("ascii")


@pytest.fixture(autouse=True)
def _clean_env():
    saved = {k: os.environ.get(k) for k in
             ("GITHUB_TOKEN", "REMOTE_BACKUP_INTERVAL", "REMOTE_BACKUP_GIST_ID",
              "REMOTE_BACKUP_ENCRYPTION_KEY")}
    os.environ["GITHUB_TOKEN"] = "gh_test_token"
    os.environ["REMOTE_BACKUP_INTERVAL"] = "300"
    os.environ["REMOTE_BACKUP_ENCRYPTION_KEY"] = TEST_BACKUP_KEY
    os.environ.pop("REMOTE_BACKUP_GIST_ID", None)
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _make_db(path):
    """Create a tiny SQLite DB with a user-data row."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE settings (key TEXT, value TEXT)")
    conn.execute("INSERT INTO settings VALUES ('cost_mode', 'power')")
    conn.commit()
    conn.close()
    return path


def _empty_db(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE settings (key TEXT, value TEXT)")
    conn.commit()
    conn.close()


class _FakeResp:
    def __init__(self, ok, json_data=None, status_code=200, text=""):
        self.ok = ok
        self._json = json_data or {}
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._json


def _mock_requests(monkeypatch, gist_id="gist123"):
    """Patch services.remote_backup.requests with a scripted fake."""
    fake = types.SimpleNamespace(
        calls=[],
        gist_id=gist_id,
    )

    def _get(url, **kw):
        fake.calls.append(("GET", url, kw))
        if url.endswith("/gists"):
            return _FakeResp(True, [{"id": gist_id, "files": {rb.GIST_FILENAME: {}}}])
        return _FakeResp(True, {
            "id": gist_id,
            "files": {rb.GIST_FILENAME: {"content": "stale"}},
        })

    def _post(url, **kw):
        fake.calls.append(("POST", url, kw))
        return _FakeResp(True, {"id": gist_id})

    def _patch(url, **kw):
        fake.calls.append(("PATCH", url, kw))
        return _FakeResp(True, {"id": gist_id})

    monkeypatch.setattr(rb.requests, "get", _get)
    monkeypatch.setattr(rb.requests, "post", _post)
    monkeypatch.setattr(rb.requests, "patch", _patch)
    return fake


# ── Env gating ─────────────────────────────────────────────────────────────

def test_disabled_without_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert rb.remote_backup_enabled() is False
    assert rb.remote_backup_now() is False


def test_disabled_with_zero_interval(monkeypatch):
    monkeypatch.setenv("REMOTE_BACKUP_INTERVAL", "0")
    assert rb.remote_backup_enabled() is False


def test_disabled_without_encryption_key(monkeypatch):
    monkeypatch.delenv("REMOTE_BACKUP_ENCRYPTION_KEY", raising=False)
    assert rb.remote_backup_enabled() is False


def test_disabled_with_invalid_encryption_key(monkeypatch):
    monkeypatch.setenv("REMOTE_BACKUP_ENCRYPTION_KEY", "not-a-fernet-key")
    assert rb.remote_backup_enabled() is False


def test_enabled_with_token_and_interval():
    assert rb.remote_backup_enabled() is True


# ── Backup → gist round trip ───────────────────────────────────────────────

def test_backup_pushes_authenticated_encrypted_snapshot(monkeypatch, tmp_path):
    db = _make_db(str(tmp_path / "war.sqlite"))
    fake = _mock_requests(monkeypatch)

    ok = rb.remote_backup_now(db_path=db)

    assert ok is True
    # PATCH carries only authenticated ciphertext, never raw SQLite bytes.
    patch_call = [c for c in fake.calls if c[0] == "PATCH"]
    assert patch_call, "expected a PATCH to the gist"
    content = patch_call[0][2]["json"]["files"][rb.GIST_FILENAME]["content"]
    assert content.startswith(rb.ENCRYPTED_PREFIX)
    assert "SQLite format 3" not in content
    # The snapshot helper must produce a file whose bytes carry the SQLite
    # magic header (0x53514c69746520666f726d61742033 = 'SQLite format 3').
    raw = rb._snapshot_bytes(db)
    assert raw[:16] == b"SQLite format 3\x00"
    assert rb._decrypt_snapshot(content) == raw


def test_restore_round_trip(monkeypatch, tmp_path):
    db = str(tmp_path / "war.sqlite")
    _make_db(db)
    raw = rb._snapshot_bytes(db)
    encrypted = rb._encrypt_snapshot(raw)

    # Fresh boot: local DB is empty (no user rows) → restore happens.
    empty = str(tmp_path / "fresh.sqlite")
    _empty_db(empty)

    def _get(url, **kw):
        if url.endswith("/gists"):
            return _FakeResp(True, [{"id": "g1", "files": {rb.GIST_FILENAME: {}}}])
        return _FakeResp(True, {"id": "g1",
                                "files": {rb.GIST_FILENAME: {"content": encrypted}}})

    def _post(url, **kw):
        return _FakeResp(True, {"id": "g1"})

    monkeypatch.setattr(rb.requests, "get", _get)
    monkeypatch.setattr(rb.requests, "post", _post)

    assert rb.remote_restore(db_path=empty) is True
    conn = sqlite3.connect(empty)
    rows = conn.execute("SELECT COUNT(*) FROM settings WHERE value='power'").fetchone()
    conn.close()
    assert rows[0] == 1  # user data restored


def test_restore_never_clobbers_existing_data(monkeypatch, tmp_path):
    db = str(tmp_path / "war.sqlite")
    _make_db(db)  # already has a settings row → must NOT be overwritten

    def _get(url, **kw):
        return _FakeResp(True, {"files": {rb.GIST_FILENAME: {"content": "garbage"}}})

    monkeypatch.setattr(rb.requests, "get", _get)
    assert rb.remote_restore(db_path=db) is False
    # The "garbage" payload was never written — file still valid.
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT COUNT(*) FROM settings").fetchone()
    conn.close()
    assert rows[0] == 1


def test_restore_noop_when_gist_empty(monkeypatch, tmp_path):
    empty = str(tmp_path / "fresh.sqlite")
    _empty_db(empty)

    def _get(url, **kw):
        return _FakeResp(True, {"files": {rb.GIST_FILENAME: {"content": ""}}})

    monkeypatch.setattr(rb.requests, "get", _get)
    assert rb.remote_restore(db_path=empty) is False


@pytest.mark.parametrize("content", ["legacy-base64", rb.ENCRYPTED_PREFIX + "tampered"])
def test_restore_rejects_legacy_or_tampered_payload(monkeypatch, tmp_path, content):
    empty = str(tmp_path / "fresh.sqlite")
    _empty_db(empty)
    before = rb._snapshot_bytes(empty)

    monkeypatch.setattr(
        rb.requests,
        "get",
        lambda *a, **k: _FakeResp(
            True, {"files": {rb.GIST_FILENAME: {"content": content}}}
        ),
    )

    assert rb.remote_restore(db_path=empty) is False
    assert rb._snapshot_bytes(empty) == before


def test_restore_noop_when_disabled(monkeypatch, tmp_path):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert rb.remote_restore(db_path=str(tmp_path / "x.sqlite")) is False


# ── Gist id env shortcut ───────────────────────────────────────────────────

def test_gist_id_env_shortcut(monkeypatch, tmp_path):
    monkeypatch.setenv("REMOTE_BACKUP_GIST_ID", "known-gist")
    db = _make_db(str(tmp_path / "war.sqlite"))
    fake = _mock_requests(monkeypatch)

    assert rb.remote_backup_now(db_path=db) is True
    # No LIST/CREATE round trip — direct PATCH to the known id.
    urls = [c[1] for c in fake.calls]
    assert any("known-gist" in u for u in urls)


def test_gist_id_cached_after_first_lookup(monkeypatch, tmp_path):
    """After discovery, subsequent backups must NOT call GET /gists again
    (avoids per-cycle API round trips + duplicate-gist drift)."""
    monkeypatch.setattr(rb, "_cached_gist_id", None)
    db = _make_db(str(tmp_path / "war.sqlite"))
    fake = _mock_requests(monkeypatch)

    assert rb.remote_backup_now(db_path=db) is True
    get_calls = [c for c in fake.calls if c[0] == "GET"]
    assert get_calls, "first backup should discover the gist via GET"
    assert rb._cached_gist_id == "gist123"

    fake2 = _mock_requests(monkeypatch, gist_id="ignored-now")
    assert rb.remote_backup_now(db_path=db) is True
    get2 = [c for c in fake2.calls if c[0] == "GET"]
    assert get2 == [], "second backup reuses the cached id — no GET"
    monkeypatch.setattr(rb, "_cached_gist_id", None)


# ── Loop worker ────────────────────────────────────────────────────────────

def test_loop_respects_stop_event(monkeypatch):
    calls = {"n": 0}

    def _now(**kw):
        calls["n"] += 1
        return True

    monkeypatch.setattr(rb, "remote_backup_now", _now)
    # Stop set BEFORE the loop starts → no snapshot is taken (clean shutdown).
    stop = types.SimpleNamespace(is_set=lambda: True)
    rb.remote_backup_loop(stop_event=stop)
    assert calls["n"] == 0


def test_loop_snaps_immediately_then_stops(monkeypatch):
    calls = {"n": 0}

    def _now(**kw):
        calls["n"] += 1
        return True

    monkeypatch.setattr(rb, "remote_backup_now", _now)
    # Interval 0 → one immediate snapshot, then the loop returns.
    monkeypatch.setenv("REMOTE_BACKUP_INTERVAL", "0")
    stop = types.SimpleNamespace(is_set=lambda: False)
    rb.remote_backup_loop(stop_event=stop)
    assert calls["n"] == 1
