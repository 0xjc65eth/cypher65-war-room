"""Contract tests for render.yaml (Issue #14 — gist backup activation).

Guards the ops setup against regressions:
  - GITHUB_TOKEN is provisioned with `sync: false` (the real PAT is set in
    the Render dashboard, never committed to git).
  - REMOTE_BACKUP_INTERVAL is enabled with 300s.
  - No GitHub token pattern is ever committed in render.yaml.
"""
import os
import re
import sys

import pytest

yaml = pytest.importorskip("yaml")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RENDER_YAML = os.path.join(ROOT, "render.yaml")


def _env_vars():
    with open(RENDER_YAML, "r") as f:
        blueprint = yaml.safe_load(f)
    web = next(s for s in blueprint["services"] if s["type"] == "web")
    return web.get("envVars", [])


def _env(key):
    return next((e for e in _env_vars() if e.get("key") == key), None)


def test_github_token_is_provisioned_with_sync_false():
    env = _env("GITHUB_TOKEN")
    assert env is not None, "GITHUB_TOKEN must be provisioned in render.yaml"
    # `sync: false` → Render creates the key but the value lives in the
    # dashboard. A committed `value` would leak the secret into git.
    assert env.get("sync") is False
    assert "value" not in env, "GITHUB_TOKEN value must never be committed"


def test_remote_backup_interval_enabled():
    env = _env("REMOTE_BACKUP_INTERVAL")
    assert env is not None, "REMOTE_BACKUP_INTERVAL must be provisioned"
    assert env.get("value") == "300"


def test_no_token_pattern_committed():
    text = open(RENDER_YAML, "r").read()
    for pat in (r"github_pat_[A-Za-z0-9_]+", r"ghp_[A-Za-z0-9]+",
                r"gho_[A-Za-z0-9]+", r"ghu_[A-Za-z0-9]+", r"ghs_[A-Za-z0-9]+"):
        assert not re.search(pat, text), f"token pattern leaked: {pat}"


def test_backup_comment_documents_activation():
    text = open(RENDER_YAML, "r").read()
    assert "docs/DEPLOYMENT_OPS.md" in text
    assert "verify_remote_backup.py" in text
