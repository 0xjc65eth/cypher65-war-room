"""
CYPHER65 // R1 — PRO Licensing gate tests
==========================================
Validates the off-by-default monetization gate (services/licensing.py):

1. Open mode (no PRO_LICENSE_KEYS) → every feature stays free, no 402s.
2. Licensed mode (PRO_LICENSE_KEYS set) → gated routes return 402 without a
   valid key, and unlock via X-License-Key header or ?license= param.
3. /api/license-status reports mode/tier/features correctly.
4. Settings webhook_url + chart-data 30d/all are gated; other settings are not.
"""

import os
import sys
import pytest

# Ensure the repo root is importable (tests run from repo root, but be safe).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# HERMETIC TESTS — must NEVER touch the production data/war_room.sqlite:
#   - It has a LIVE writer (the Dockerized app via Colima holds write FDs).
#   - It has a recurring index-corruption incident (idx_maintenance_records_ts,
#     idx_audit_logs_tenant_ts) that pre-dates this feature.
# `import app` runs init_db() + _core_registry.load_from_db() at module scope
# against whatever DB_PATH points at. tests/conftest.py now owns a single
# process-wide redirect to a scratch DB BEFORE any test module imports app
# (C4 hermetic suite), so a per-module redirect here would be redundant AND
# harmful: if another module imports app first (alphabetically earlier),
# init_db() runs against the conftest scratch, then this module's own scratch
# would have NO tables and route tests would fail.

import app as _app_module
from services.licensing import (
    PREMIUM_FEATURES,
    PRO_FEATURES,
    _configured_keys,
    is_pro,
    license_status,
    licensing_configured,
)

app = _app_module.app


@pytest.fixture(autouse=True)
def _scrub_license_env(monkeypatch):
    """Every test starts with NO PRO_LICENSE_KEYS (open mode)."""
    monkeypatch.delenv("PRO_LICENSE_KEYS", raising=False)


# ── Unit: licensing_configured / is_pro ──────────────────────────────


def test_open_mode_not_configured():
    assert licensing_configured() is False
    assert _configured_keys() == []


def test_configured_keys_parsed(monkeypatch):
    monkeypatch.setenv("PRO_LICENSE_KEYS", "KEY-ONE, KEY-TWO ,")
    assert _configured_keys() == ["KEY-ONE", "KEY-TWO"]


def test_is_pro_open_mode():
    """Open mode → is_pro() True regardless of request context."""
    assert is_pro() is True


# ── Endpoint behavior ─────────────────────────────────────────────────


@pytest.fixture
def isolated_client():
    """Flask test client against the conftest-owned SCRATCH DB.

    tests/conftest.py redirects DB_PATH process-wide before app is imported,
    so every route (get_db reads the env at call time) hits scratch —
    production data is never read or written by these tests.
    """
    app.config["TESTING"] = True
    return app.test_client()


def test_monte_carlo_open_mode_free(isolated_client):
    """Open mode: Monte Carlo never 402s."""
    r = isolated_client.get("/api/monte_carlo?hours=1&runs=100")
    assert r.status_code == 200  # may be 'insufficient data', but never 402


def test_proximity_open_mode_free(isolated_client):
    r = isolated_client.get("/api/proximity")
    assert r.status_code == 200


def test_chart_30d_open_mode_free(isolated_client):
    r = isolated_client.get("/api/chart-data?chart=hashrate&range=30d")
    assert r.status_code == 200


def test_license_status_open_mode(isolated_client):
    r = isolated_client.get("/api/license-status")
    assert r.status_code == 200
    d = r.get_json()
    assert d["mode"] == "open"
    assert d["pro"] is True
    assert d["tier"] == "premium"
    assert d["premium"] is True
    assert d["features"] == {
        **{f: "unlocked" for f in PRO_FEATURES},
        **{f: "unlocked" for f in PREMIUM_FEATURES},
    }


# ── Licensed mode (gate active) ───────────────────────────────────────


def _set_keys(monkeypatch, keys="PRO-KEY-123"):
    monkeypatch.setenv("PRO_LICENSE_KEYS", keys)


def test_monte_carlo_gated_402(isolated_client, monkeypatch):
    _set_keys(monkeypatch)
    r = isolated_client.get("/api/monte_carlo?hours=1&runs=100")
    assert r.status_code == 402
    d = r.get_json()
    assert d["code"] == "LICENSE_REQUIRED"
    assert d["upgrade"]["plan"] == "PRO"


def test_monte_carlo_gated_header_unlocks(isolated_client, monkeypatch):
    _set_keys(monkeypatch)
    r = isolated_client.get(
        "/api/monte_carlo?hours=1&runs=100", headers={"X-License-Key": "PRO-KEY-123"}
    )
    assert r.status_code == 200  # unlocked → handler runs


def test_monte_carlo_gated_query_unlocks(isolated_client, monkeypatch):
    _set_keys(monkeypatch)
    r = isolated_client.get("/api/monte_carlo?hours=1&runs=100&license=PRO-KEY-123")
    assert r.status_code == 200


def test_monte_carlo_gated_wrong_key_402(isolated_client, monkeypatch):
    _set_keys(monkeypatch)
    r = isolated_client.get(
        "/api/monte_carlo?hours=1&runs=100", headers={"X-License-Key": "NOPE"}
    )
    assert r.status_code == 402


def test_proximity_gated_402(isolated_client, monkeypatch):
    _set_keys(monkeypatch)
    r = isolated_client.get("/api/proximity")
    assert r.status_code == 402


def test_chart_30d_gated_402(isolated_client, monkeypatch):
    _set_keys(monkeypatch)
    r = isolated_client.get("/api/chart-data?chart=hashrate&range=30d")
    assert r.status_code == 402
    assert r.get_json()["code"] == "LICENSE_REQUIRED"


def test_chart_30d_gated_unlock(isolated_client, monkeypatch):
    _set_keys(monkeypatch)
    r = isolated_client.get(
        "/api/chart-data?chart=hashrate&range=30d",
        headers={"X-License-Key": "PRO-KEY-123"},
    )
    assert r.status_code == 200


def test_chart_1h_not_gated(isolated_client, monkeypatch):
    """The default 1h range is FREE — never 402s even with the gate active."""
    _set_keys(monkeypatch)
    r = isolated_client.get("/api/chart-data?chart=hashrate&range=1h")
    assert r.status_code == 200


def test_license_status_licensed_free(isolated_client, monkeypatch):
    _set_keys(monkeypatch)
    d = isolated_client.get("/api/license-status").get_json()
    assert d["mode"] == "licensed"
    assert d["pro"] is False
    assert d["premium"] is False
    assert d["tier"] == "free"
    assert d["features"] == {
        **{f: "locked" for f in PRO_FEATURES},
        **{f: "locked" for f in PREMIUM_FEATURES},
    }
    assert d["upgrade"]["plan"] == "PRO"


def test_license_status_licensed_pro(isolated_client, monkeypatch):
    _set_keys(monkeypatch)
    d = isolated_client.get(
        "/api/license-status", headers={"X-License-Key": "PRO-KEY-123"}
    ).get_json()
    assert d["mode"] == "licensed"
    assert d["pro"] is True
    assert d["premium"] is False
    assert d["tier"] == "pro"
    assert d["features"] == {
        **{f: "unlocked" for f in PRO_FEATURES},
        **{f: "locked" for f in PREMIUM_FEATURES},
    }
    assert d["upgrade"] == {"plan": "PREMIUM", "price_usd_month": 29}


# ── Settings webhook gate ─────────────────────────────────────────────


def test_webhook_setting_gated(isolated_client, monkeypatch):
    _set_keys(monkeypatch)
    r = isolated_client.post(
        "/api/settings", json={"webhook_url": "https://example.com/hook"}
    )
    assert r.status_code == 200  # route itself is not gated
    d = r.get_json()
    assert d["applied"] == []
    assert any(
        x["key"] == "webhook_url" and "PRO" in x["reason"] for x in d["rejected"]
    )


def test_non_webhook_setting_not_gated(isolated_client, monkeypatch):
    _set_keys(monkeypatch)
    r = isolated_client.post("/api/settings", json={"cost_mode": "none"})
    assert r.status_code == 200
    # cost_mode is a known setting and not PRO-gated → accepted
    assert "cost_mode" in r.get_json()["applied"]


# ── license_status() pure function ────────────────────────────────────


def test_license_status_open_mode_pure():
    assert license_status()["mode"] == "open"
    assert license_status()["pro"] is True
