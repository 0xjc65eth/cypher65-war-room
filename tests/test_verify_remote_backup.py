"""Hermetic tests for scripts/verify_remote_backup.py (Issue #14).

The script is the operator's "prove the $0 gist backup is live" tool. All
GitHub API calls are mocked — no network, no real token needed. Covers the
exit-code contract: 0 verified · 1 not enabled · 2 probe/push failure.
"""
import importlib.util
import os
import sys

import pytest
from cryptography.fernet import Fernet

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = importlib.util.spec_from_file_location(
    "verify_remote_backup", os.path.join(ROOT, "scripts", "verify_remote_backup.py"))
_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_mod)

rb = _mod.rb


class _FakeResp:
    def __init__(self, ok=True, json_data=None, status_code=200):
        self.ok = ok
        self._json = json_data or {}
        self.status_code = status_code

    def json(self):
        return self._json


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("GITHUB_TOKEN", "REMOTE_BACKUP_INTERVAL", "REMOTE_BACKUP_GIST_ID",
              "REMOTE_BACKUP_ENCRYPTION_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("REMOTE_BACKUP_ENCRYPTION_KEY", Fernet.generate_key().decode())


def test_exit_1_when_no_token(monkeypatch, capsys):
    monkeypatch.setattr(rb, "_token", lambda: "")
    assert _mod.run([]) == 1
    assert "GITHUB_TOKEN not set" in capsys.readouterr().out


def test_exit_1_when_disabled(monkeypatch, capsys):
    monkeypatch.setattr(rb, "_token", lambda: "gh_test_token")
    monkeypatch.setattr(rb, "remote_backup_enabled", lambda: False)
    assert _mod.run([]) == 1
    assert "remote_backup_enabled()=False" in capsys.readouterr().out


def test_exit_1_when_encryption_key_missing(monkeypatch, capsys):
    monkeypatch.setattr(rb, "_token", lambda: "gh_test_token")
    monkeypatch.setattr(rb, "_encryption_key", lambda: "")
    assert _mod.run([]) == 1
    assert "REMOTE_BACKUP_ENCRYPTION_KEY" in capsys.readouterr().out


def test_exit_2_when_gist_unreachable(monkeypatch, capsys):
    monkeypatch.setattr(rb, "_token", lambda: "gh_test_token")
    monkeypatch.setattr(rb, "remote_backup_enabled", lambda: True)
    monkeypatch.setattr(rb, "_find_or_create_gist", lambda: None)
    assert _mod.run([]) == 2
    out = capsys.readouterr().out
    assert "could not find/open the backup gist" in out


def test_exit_0_read_only_probe(monkeypatch, capsys):
    monkeypatch.setattr(rb, "_token", lambda: "gh_test_token")
    monkeypatch.setattr(rb, "_interval", lambda: 300)
    monkeypatch.setattr(rb, "remote_backup_enabled", lambda: True)
    monkeypatch.setattr(rb, "_find_or_create_gist", lambda: "gist-123")
    monkeypatch.setattr(
        _mod.requests, "get",
        lambda *a, **k: _FakeResp(json_data={
            "files": {rb.GIST_FILENAME: {
                "size": 4321, "updated_at": "2026-08-13T00:00:00Z"}}}))
    assert _mod.run([]) == 0
    out = capsys.readouterr().out
    assert "gist-123" in out
    assert "4321 bytes" in out
    assert "verified" in out


def test_exit_0_roundtrip_uses_separate_file(monkeypatch, capsys):
    """--roundtrip must patch ONLY the verify file, never the prod one."""
    patched_files = {}

    monkeypatch.setattr(rb, "_token", lambda: "gh_test_token")
    monkeypatch.setattr(rb, "_interval", lambda: 300)
    monkeypatch.setattr(rb, "remote_backup_enabled", lambda: True)
    monkeypatch.setattr(rb, "_find_or_create_gist", lambda: "gist-123")
    monkeypatch.setattr(
        _mod.requests, "get",
        lambda *a, **k: _FakeResp(json_data={
            "files": {rb.GIST_FILENAME: {"size": 4321, "updated_at": "2026-08-13"}}}))

    def fake_patch(url, **kwargs):
        patched_files.update(kwargs.get("json", {}).get("files", {}))
        return _FakeResp(ok=True)

    monkeypatch.setattr(_mod.requests, "patch", fake_patch)
    assert _mod.run(["--roundtrip"]) == 0
    assert _mod.VERIFY_FILENAME in patched_files
    assert rb.GIST_FILENAME not in patched_files  # prod file untouched


def test_exit_2_when_roundtrip_upload_fails(monkeypatch, capsys):
    monkeypatch.setattr(rb, "_token", lambda: "gh_test_token")
    monkeypatch.setattr(rb, "_interval", lambda: 300)
    monkeypatch.setattr(rb, "remote_backup_enabled", lambda: True)
    monkeypatch.setattr(rb, "_find_or_create_gist", lambda: "gist-123")
    monkeypatch.setattr(
        _mod.requests, "get",
        lambda *a, **k: _FakeResp(json_data={
            "files": {rb.GIST_FILENAME: {"size": 4321, "updated_at": "2026-08-13"}}}))
    monkeypatch.setattr(_mod.requests, "patch",
                        lambda *a, **k: _FakeResp(ok=False, status_code=422))
    assert _mod.run(["--roundtrip"]) == 2
    assert "round-trip upload FAILED" in capsys.readouterr().out


def test_exit_0_with_hint_when_gist_empty(monkeypatch, capsys):
    """A 0-byte placeholder must NOT claim 'receiving backups' — honest hint."""
    monkeypatch.setattr(rb, "_token", lambda: "gh_test_token")
    monkeypatch.setattr(rb, "_interval", lambda: 300)
    monkeypatch.setattr(rb, "remote_backup_enabled", lambda: True)
    monkeypatch.setattr(rb, "_find_or_create_gist", lambda: "gist-123")
    monkeypatch.setattr(
        _mod.requests, "get",
        lambda *a, **k: _FakeResp(json_data={
            "files": {rb.GIST_FILENAME: {"size": 0, "updated_at": "2026-08-13"}}}))
    assert _mod.run([]) == 0
    out = capsys.readouterr().out
    assert "backup file is empty" in out
    assert "receiving backups" not in out


def test_script_compiles_and_is_importable():
    """The script must stay importable (it is, at module import time)."""
    assert hasattr(_mod, "run")
    assert _mod.VERIFY_FILENAME == "war_room.verify.sqlite.enc"
