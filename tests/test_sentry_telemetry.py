"""Hermetic tests for services/sentry_telemetry (Issue #176).

Covers:
  1. get_sentry_config: no DSN → disabled; traces sample rate default 0.1.
  2. compute_release: SENTRY_RELEASE env → git short SHA → dev fallback
     (module cache reset per test — the cache is set once at app import).
  3. init_sentry: no DSN → False; package missing → graceful False;
     DSN + SDK present → True (with init monkeypatched — no real network).
  4. _inject_request_id / _inject_breadcrumb_request_id: the active
     request_id (Issue #124 ContextVar) lands on events/breadcrumbs; no id →
     event untouched.
  5. set_request_tag: safe no-op when Sentry inactive.
"""

import sys

import pytest

sys.path.insert(0, ".")

import services.sentry_telemetry as st  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    """The module freezes DSN/release/active at import — reset per test."""
    monkeypatch.setattr(st, "_release_cache", None)
    monkeypatch.setattr(st, "_active", False)


# ── config ─────────────────────────────────────────────────────────────────


def test_config_disabled_without_dsn():
    cfg = st.get_sentry_config()
    assert cfg["enabled"] is False
    assert cfg["dsn"] == ""
    assert cfg["traces_sample_rate"] == 0.1
    assert cfg["environment"] in ("cloud", "self-hosted")
    assert cfg["release"]  # never empty — Sentry rejects empty releases


# ── release tracking ───────────────────────────────────────────────────────


def test_compute_release_env_override(monkeypatch):
    monkeypatch.setenv("SENTRY_RELEASE", "v1.2.3")
    assert st.compute_release() == "v1.2.3"


def test_compute_release_git_sha(monkeypatch):
    monkeypatch.delenv("SENTRY_RELEASE", raising=False)

    class _Out:
        stdout = b"abc1234\n"

    monkeypatch.setattr(st.subprocess, "run", lambda *a, **k: _Out(), raising=False)
    assert st.compute_release() == "cypher65-war-room@abc1234"


def test_compute_release_dev_fallback(monkeypatch):
    monkeypatch.delenv("SENTRY_RELEASE", raising=False)

    def _boom(*a, **k):
        raise OSError("no git")

    monkeypatch.setattr(st.subprocess, "run", _boom, raising=False)
    assert st.compute_release() == "cypher65-war-room@dev"


# ── init ───────────────────────────────────────────────────────────────────


def test_init_sentry_no_dsn_returns_false(monkeypatch):
    monkeypatch.setattr(st, "_DSN", "")
    assert st.init_sentry() is False
    assert st.sentry_active() is False


def test_init_sentry_graceful_without_sdk(monkeypatch):
    # DSN set but the package missing → False, no raise (honest no-op).
    monkeypatch.setattr(st, "_DSN", "https://abc@sentry.io/1")
    monkeypatch.setitem(sys.modules, "sentry_sdk", None)
    assert st.init_sentry() is False
    assert st.sentry_active() is False


def test_init_sentry_success(monkeypatch):
    sentry_sdk = pytest.importorskip("sentry_sdk")
    monkeypatch.setattr(st, "_DSN", "https://abc@sentry.io/1")
    calls = {}

    def _fake_init(**kw):
        calls.update(kw)

    monkeypatch.setattr(sentry_sdk, "init", _fake_init)
    assert st.init_sentry() is True
    assert st.sentry_active() is True
    # Release/environment/PII guard wired in the init kwargs.
    assert calls["send_default_pii"] is False
    assert calls["include_local_variables"] is False
    assert calls["before_send"] is st._inject_request_id
    assert calls["before_breadcrumb"] is st._inject_breadcrumb_request_id
    assert calls["release"]


# ── request_id correlation ─────────────────────────────────────────────────


def test_inject_request_id_when_no_rid():
    from services.observability import clear_request_id

    clear_request_id()
    event = {"message": "boom", "tags": {}, "extra": {}}
    out = st._inject_request_id(dict(event), {})
    assert out == event  # untouched — no fabricated correlation


def test_inject_request_id_with_rid():
    from services.observability import clear_request_id, set_request_id

    clear_request_id()
    set_request_id("req-deadbeef")
    try:
        out = st._inject_request_id({"message": "boom"}, {})
        assert out["tags"]["request_id"] == "req-deadbeef"
        assert out["extra"]["request_id"] == "req-deadbeef"
    finally:
        clear_request_id()


def test_inject_breadcrumb_request_id():
    from services.observability import clear_request_id, set_request_id

    clear_request_id()
    crumb = {"type": "log", "message": "x"}
    assert st._inject_breadcrumb_request_id(dict(crumb), {}) == crumb
    set_request_id("req-feed")
    try:
        out = st._inject_breadcrumb_request_id(dict(crumb), {})
        assert out["data"]["request_id"] == "req-feed"
    finally:
        clear_request_id()


def test_set_request_tag_inactive_is_noop():
    # _active is False (autouse reset) — must not raise, even without the SDK.
    st.set_request_tag("req-xyz")
