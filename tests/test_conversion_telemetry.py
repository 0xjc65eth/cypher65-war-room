"""Hermetic tests for CFO conversion telemetry (services/conversion.py).

Covers:
  1. track_event: rows persisted, email/tenant anonymized, best-effort on bad DB.
  2. funnel_report: stage counts, drop-off between consecutive stages,
     conversion rate paywall → key_activated.
  3. ltv_cac_report: LTV from env-tunable unit economics, CAC from
     MARKETING_SPEND_USD, payback, LTV/CAC ratio, no-data when no spend.
  4. Routes: /api/conversion/track (unknown event 400, known 200),
     /api/admin/conversion (403 without admin, 200 with localhost/api key).
"""

import os
import sys
import time

import pytest

sys.path.insert(0, ".")

import services.conversion as conv  # noqa: E402


@pytest.fixture
def isolated_client():
    """Flask test client against the conftest-owned SCRATCH DB."""
    import app as _app_module
    _app_module.app.config["TESTING"] = True
    return _app_module.app.test_client()


@pytest.fixture()
def clean_events(monkeypatch):
    """Redirect to a scratch DB and wipe the events table per test."""
    from services.db import get_db
    conv.ensure_table()
    conn = get_db()
    conn.execute("DELETE FROM conversion_events")
    conn.commit()
    conn.close()
    yield
    conn = get_db()
    conn.execute("DELETE FROM conversion_events")
    conn.commit()
    conn.close()


# ── track_event ────────────────────────────────────────────────────────────

def test_track_event_persists(clean_events):
    assert conv.track_event("modal_open", tenant_id="acme") is True
    from services.db import get_db
    conn = get_db()
    row = conn.execute("SELECT * FROM conversion_events").fetchone()
    conn.close()
    assert row is not None
    assert row["event"] == "modal_open"
    # Tenant anonymized: never the raw id in the table.
    assert row["tenant_id"] != "acme"
    assert len(row["tenant_id"]) == 24  # sha256 truncated


def test_track_event_hashes_email(clean_events):
    conv.track_event("paid", email="buyer@example.com")
    from services.db import get_db
    conn = get_db()
    row = conn.execute("SELECT meta FROM conversion_events").fetchone()
    conn.close()
    import json
    meta = json.loads(row["meta"])
    assert "email_hash" in meta
    assert meta["email_hash"] != "buyer@example.com"
    assert "buyer@example.com" not in row["meta"]


def test_track_event_empty_is_noop(clean_events):
    assert conv.track_event("") is False
    from services.db import get_db
    conn = get_db()
    n = conn.execute("SELECT COUNT(*) AS n FROM conversion_events").fetchone()["n"]
    conn.close()
    assert n == 0


def test_anonymize_deterministic_and_different():
    assert conv._anonymize("Alice@X.com") == conv._anonymize("alice@x.com")
    assert conv._anonymize("a") != conv._anonymize("b")
    assert conv._anonymize("") == ""


# ── funnel_report ──────────────────────────────────────────────────────────

def test_funnel_counts_and_dropoff(clean_events):
    # 10 saw the paywall, 4 opened the modal, 2 started checkout, 1 paid, 1 activated.
    for _ in range(10):
        conv.track_event("paywall_view")
    for _ in range(4):
        conv.track_event("modal_open")
    for _ in range(2):
        conv.track_event("checkout_start")
    conv.track_event("paid")
    conv.track_event("key_activated")

    r = conv.funnel_report(days=30)
    assert r["stages"]["paywall_view"] == 10
    assert r["stages"]["modal_open"] == 4
    assert r["stages"]["checkout_start"] == 2
    assert r["stages"]["paid"] == 1
    assert r["stages"]["key_activated"] == 1
    assert r["paid_count"] == 1
    assert r["activated_count"] == 1
    assert r["conversion_rate_pct"] == 10.0  # 1 / 10 paywalls → activated

    # Drop-off paywall → modal: 10 → 4 = 60% loss, 40% conversion.
    first = r["drop_off"][0]
    assert first["from"] == "paywall_view" and first["to"] == "modal_open"
    assert first["loss_abs"] == 6
    assert first["loss_pct"] == 60.0
    assert first["conversion_pct"] == 40.0


def test_funnel_visitors_distinct_tenants(clean_events):
    conv.track_event("paywall_view", tenant_id="t1")
    conv.track_event("paywall_view", tenant_id="t1")
    conv.track_event("paywall_view", tenant_id="t2")
    r = conv.funnel_report()
    assert r["visitors"] == 2


def test_paywall_view_dedup_per_tenant(clean_events):
    # One user hitting 5 gated endpoints in a session = 1 paywall event,
    # so the funnel top is not inflated. Different tenants still count.
    assert conv.track_event("paywall_view", tenant_id="t1") is True   # 1st records
    for _ in range(4):
        assert conv.track_event("paywall_view", tenant_id="t1") is False  # dups
    assert conv.track_event("paywall_view", tenant_id="t2") is True
    r = conv.funnel_report()
    assert r["stages"]["paywall_view"] == 2  # t1 + t2, not 11


def test_paywall_view_no_dedup_anonymous(clean_events):
    # Anonymous callers (tenant_id="") cannot be distinguished — every 402 counts.
    assert conv.track_event("paywall_view") is True
    assert conv.track_event("paywall_view") is True
    r = conv.funnel_report()
    assert r["stages"]["paywall_view"] == 2


def test_other_events_not_deduped(clean_events):
    # modal_open etc. are explicit user actions — repeated opens are real signal.
    assert conv.track_event("modal_open", tenant_id="t1") is True
    assert conv.track_event("modal_open", tenant_id="t1") is True
    r = conv.funnel_report()
    assert r["stages"]["modal_open"] == 2


def test_meta_capped(clean_events):
    big = {"blob": "x" * 5000}
    assert conv.track_event("modal_open", tenant_id="t1", meta=big) is True
    from services.db import get_db
    conn = get_db()
    row = conn.execute("SELECT meta FROM conversion_events").fetchone()
    conn.close()
    assert len(row["meta"]) <= 1000


def test_funnel_empty(clean_events):
    r = conv.funnel_report()
    assert r["stages"] == {}
    assert r["drop_off"] == []
    assert r["conversion_rate_pct"] == 0.0
    assert r["paid_count"] == 0


# ── LTV / CAC ──────────────────────────────────────────────────────────────

def test_ltv_defaults(monkeypatch):
    monkeypatch.delenv("PRO_PRICE_USD_MONTH", raising=False)
    monkeypatch.delenv("PRO_LICENSE_MONTHS", raising=False)
    monkeypatch.delenv("PRO_MARGIN_PCT", raising=False)
    r = conv.ltv_cac_report(paid_count=0)
    # 9 × 12 × 0.94 = 101.52
    assert r["ltv_usd"] == 101.52
    assert r["cac_usd"] is None  # no marketing spend configured → no fake CAC
    assert r["ltv_cac_ratio"] is None


def test_ltv_env_overrides(monkeypatch):
    monkeypatch.setenv("PRO_PRICE_USD_MONTH", "20")
    monkeypatch.setenv("PRO_LICENSE_MONTHS", "6")
    monkeypatch.setenv("PRO_MARGIN_PCT", "0.9")
    r = conv.ltv_cac_report(paid_count=0)
    assert r["ltv_usd"] == 108.0  # 20 × 6 × 0.9
    assert r["assumptions"]["price_usd_month"] == 20


def test_cac_from_spend(monkeypatch, clean_events):
    monkeypatch.setenv("MARKETING_SPEND_USD", "500")
    conv.track_event("paid")
    r = conv.ltv_cac_report(paid_count=1)
    assert r["marketing_spend_usd"] == 500.0
    assert r["cac_usd"] == 500.0
    assert r["payback_months"] == round(500.0 / 9, 1)  # ~55.6 months
    # LTV/CAC ratio: 101.52 / 500 ≈ 0.20 (bad economics — the report says so).
    assert r["ltv_cac_ratio"] is not None and r["ltv_cac_ratio"] < 1


def test_cac_zero_paid_no_division(monkeypatch):
    monkeypatch.setenv("MARKETING_SPEND_USD", "100")
    r = conv.ltv_cac_report(paid_count=0)
    assert r["cac_usd"] is None  # no division by zero


def test_cac_paid_count_from_db(clean_events):
    # Explicit paid_count=None → counts 'paid' events from the last 30d.
    conv.track_event("paid")
    r = conv.ltv_cac_report()
    assert r["paid_count"] == 1


# ── Routes ─────────────────────────────────────────────────────────────────

def test_track_route_known_event(isolated_client):
    resp = isolated_client.post("/api/conversion/track",
                                json={"event": "modal_open", "meta": {"plan": "pro"}})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_track_route_unknown_event(isolated_client):
    resp = isolated_client.post("/api/conversion/track", json={"event": "not_a_stage"})
    assert resp.status_code == 400


def test_admin_conversion_requires_admin(isolated_client):
    # Simulate a remote caller (Flask test client defaults to 127.0.0.1,
    # which is whitelisted) with no operator key → 403.
    resp = isolated_client.get(
        "/api/admin/conversion",
        environ_base={"REMOTE_ADDR": "203.0.113.5"},
    )
    assert resp.status_code == 403


def test_admin_conversion_with_operator_key(isolated_client, monkeypatch):
    monkeypatch.setenv("API_KEY", "operator-key-123")
    resp = isolated_client.get("/api/admin/conversion",
                               headers={"X-API-Key": "operator-key-123"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert "funnel" in data and "economics" in data
    assert "stages" in data["funnel"]
    assert "ltv_usd" in data["economics"]
