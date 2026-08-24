"""Tests for beta analytics — self-hosted usage tracking (Issue #353)."""

import json
import sys
import time

import pytest

sys.path.insert(0, ".")

import services.beta_analytics as _analytics


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    """Disable rate limiting for all tests in this module."""
    monkeypatch.setattr(_analytics, "RATE_LIMIT_WINDOW", 0)
    _analytics._rate_cache.clear()
    yield
    _analytics._rate_cache.clear()


@pytest.fixture
def isolated_client():
    """Flask test client against the conftest-owned SCRATCH DB."""
    import app as _app_module

    _app_module.app.config["TESTING"] = True
    return _app_module.app.test_client()


# ── POST /api/analytics/track ────────────────────────────────────────────


class TestAnalyticsTrack:
    """POST /api/analytics/track — public endpoint, rate-limited."""

    def test_track_boot_event(self, isolated_client):
        resp = isolated_client.post(
            "/api/analytics/track",
            json={"event": "boot", "meta": {"vw": "1920x1080", "ts": 123}},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True

    def test_track_module_switch(self, isolated_client):
        resp = isolated_client.post(
            "/api/analytics/track",
            json={
                "event": "module_switch",
                "meta": {"from": "dashboard", "to": "market"},
            },
        )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_track_module_time(self, isolated_client):
        resp = isolated_client.post(
            "/api/analytics/track",
            json={
                "event": "module_time",
                "meta": {"module": "live", "seconds": 120},
            },
        )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_reject_empty_event(self, isolated_client):
        resp = isolated_client.post(
            "/api/analytics/track",
            json={"event": ""},
        )
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_reject_unknown_event(self, isolated_client):
        resp = isolated_client.post(
            "/api/analytics/track",
            json={"event": "unknown_event"},
        )
        # Rate-limited or invalid: 429 (service rejects unknown events)
        assert resp.status_code == 429

    def test_meta_defaults_to_empty_dict(self, isolated_client):
        resp = isolated_client.post(
            "/api/analytics/track",
            json={"event": "boot"},
        )
        assert resp.status_code == 200

    def test_meta_non_dict_ignored(self, isolated_client):
        resp = isolated_client.post(
            "/api/analytics/track",
            json={"event": "boot", "meta": "not-a-dict"},
        )
        assert resp.status_code == 200

    def test_rate_limit(self, isolated_client, monkeypatch):
        """Rate limit: 1 event per second per IP."""
        # Re-enable rate limiting for this test only
        monkeypatch.setattr(_analytics, "RATE_LIMIT_WINDOW", 1)
        _analytics._rate_cache.clear()
        resp1 = isolated_client.post(
            "/api/analytics/track",
            json={"event": "boot"},
        )
        assert resp1.status_code == 200
        # Immediate second call should be rate-limited → 429
        resp2 = isolated_client.post(
            "/api/analytics/track",
            json={"event": "boot"},
        )
        assert resp2.status_code == 429


# ── GET /api/admin/analytics ─────────────────────────────────────────────


class TestAnalyticsReport:
    """GET /api/admin/analytics — admin-gated report."""

    def test_requires_admin(self, isolated_client):
        resp = isolated_client.get(
            "/api/admin/analytics",
            environ_base={"REMOTE_ADDR": "203.0.113.5"},
        )
        assert resp.status_code == 403

    def test_localhost_allowed(self, isolated_client):
        resp = isolated_client.get("/api/admin/analytics")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total_events" in data
        assert "unique_tenants" in data
        assert "dau" in data
        assert "wau" in data
        assert "module_time" in data
        assert "module_usage" in data
        assert "boot_count" in data
        assert "module_switch_count" in data
        assert "dropoff" in data

    def test_days_param(self, isolated_client):
        resp = isolated_client.get("/api/admin/analytics?days=7")
        assert resp.status_code == 200
        assert resp.get_json()["days"] == 7

    def test_days_clamped(self, isolated_client):
        resp = isolated_client.get("/api/admin/analytics?days=999")
        assert resp.status_code == 200
        assert resp.get_json()["days"] == 365

    def test_report_with_data(self, isolated_client):
        """Seed events and verify the report reflects them."""
        # Seed boot events
        for i in range(3):
            isolated_client.post(
                "/api/analytics/track",
                json={"event": "boot", "meta": {"ts": i}},
            )

        # Seed module switch
        isolated_client.post(
            "/api/analytics/track",
            json={
                "event": "module_switch",
                "meta": {"from": "(boot)", "to": "market"},
            },
        )

        # Seed module time
        isolated_client.post(
            "/api/analytics/track",
            json={
                "event": "module_time",
                "meta": {"module": "market", "seconds": 90},
            },
        )

        resp = isolated_client.get("/api/admin/analytics")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["boot_count"] >= 3
        assert data["module_switch_count"] >= 1
        assert "market" in data["module_usage"]
        assert "market" in data["module_time"]
        assert data["module_time"]["market"]["avg_seconds"] == 90.0

    def test_dropoff_calculation(self, isolated_client):
        """Report always includes dropoff structure with correct keys."""
        resp = isolated_client.get("/api/admin/analytics")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "dropoff" in data
        assert "boot_without_switch" in data["dropoff"]
        assert "boot_total" in data["dropoff"]
        assert "rate" in data["dropoff"]
        assert isinstance(data["dropoff"]["boot_without_switch"], int)
        assert isinstance(data["dropoff"]["rate"], (int, float))
