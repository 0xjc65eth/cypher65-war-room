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


@pytest.fixture(autouse=True)
def _enable_validated_payment_processing(monkeypatch):
    """Webhook telemetry tests intentionally run behind the payment gate."""
    monkeypatch.setenv("ENABLE_REAL_PAYMENTS", "true")


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
    # Calls WITHOUT meta all share feature='' → deduped per (tenant, ''),
    # which keeps the legacy per-tenant behavior for feature-less rows:
    # the funnel top is not inflated by repeated hits of the same endpoint.
    # (With meta.feature set, each DISTINCT feature counts — see
    # test_paywall_view_dedup_per_feature.) Different tenants still count.
    assert conv.track_event("paywall_view", tenant_id="t1") is True  # 1st records
    for _ in range(4):
        assert conv.track_event("paywall_view", tenant_id="t1") is False  # dups
    assert conv.track_event("paywall_view", tenant_id="t2") is True
    r = conv.funnel_report()
    assert r["stages"]["paywall_view"] == 2  # t1 + t2, not 11


def test_paywall_view_dedup_per_feature(clean_events):
    # Issue #158: dedup is per (tenant, feature) — hitting the SAME gated
    # endpoint twice in a day counts once, but each DIFFERENT feature counts
    # (so the breakdown shows which endpoint blocks users).
    assert (
        conv.track_event(
            "paywall_view", tenant_id="t1", meta={"feature": "monte_carlo"}
        )
        is True
    )
    assert (
        conv.track_event(
            "paywall_view", tenant_id="t1", meta={"feature": "monte_carlo"}
        )
        is False
    )  # dup
    assert (
        conv.track_event("paywall_view", tenant_id="t1", meta={"feature": "auto_pilot"})
        is True
    )  # new feature
    assert (
        conv.track_event("paywall_view", tenant_id="t1", meta={"feature": "auto_pilot"})
        is False
    )  # dup
    assert (
        conv.track_event(
            "paywall_view", tenant_id="t2", meta={"feature": "monte_carlo"}
        )
        is True
    )  # new tenant
    r = conv.funnel_report()
    assert r["stages"]["paywall_view"] == 3  # t1: 2 features + t2: 1
    # Breakdown: monte_carlo = 2 (t1 + t2), auto_pilot = 1.
    by_feature = {f["feature"]: f["count"] for f in r["paywall_by_feature"]}
    assert by_feature.get("monte_carlo") == 2
    assert by_feature.get("auto_pilot") == 1


def test_paywall_by_feature_unknown_fallback(clean_events):
    # paywall_view without meta.feature (legacy / anonymous) buckets to 'unknown'.
    assert conv.track_event("paywall_view", tenant_id="t1") is True
    assert (
        conv.track_event(
            "paywall_view", tenant_id="t1", meta={"feature": "monte_carlo"}
        )
        is True
    )
    r = conv.funnel_report()
    by_feature = {f["feature"]: f["count"] for f in r["paywall_by_feature"]}
    assert by_feature.get("unknown") == 1
    assert by_feature.get("monte_carlo") == 1
    # Top-10 cap: many features → still ≤10 entries.
    for i in range(15):
        conv.track_event(
            "paywall_view", tenant_id=f"t{i}", meta={"feature": f"feat_{i}"}
        )
    r2 = conv.funnel_report()
    assert len(r2["paywall_by_feature"]) <= 10


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


def test_ltv_defaults(monkeypatch, clean_sub_events):
    monkeypatch.delenv("PRO_PRICE_USD_MONTH", raising=False)
    monkeypatch.delenv("PRO_LICENSE_MONTHS", raising=False)
    monkeypatch.delenv("PRO_MARGIN_PCT", raising=False)
    r = conv.ltv_cac_report(paid_count=0)
    # 9 × 12 × 0.94 = 101.52
    assert r["ltv_usd"] == 101.52
    assert r["cac_usd"] is None  # no marketing spend configured → no fake CAC
    assert r["ltv_cac_ratio"] is None


def test_ltv_env_overrides(monkeypatch, clean_sub_events):
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


# ── Subscription lifecycle + cohort LTV (Issue #157 — 18-C) ───────────────


@pytest.fixture()
def clean_sub_events():
    """Wipe subscription_events per test (like clean_events for the funnel)."""
    from services.db import get_db

    conv.ensure_subscription_table()
    conn = get_db()
    conn.execute("DELETE FROM subscription_events")
    conn.commit()
    conn.close()
    yield
    conn = get_db()
    conn.execute("DELETE FROM subscription_events")
    conn.commit()
    conn.close()


def test_record_subscription_created_once(clean_sub_events):
    assert (
        conv.record_subscription_event(
            "sub_1", "subscription_created", 1000, created_at="2026-08-03T12:00:00Z"
        )
        is True
    )
    # Replay (LS redelivery) → deduped, no double row.
    assert (
        conv.record_subscription_event(
            "sub_1", "subscription_created", 1001, created_at="2026-08-03T12:00:00Z"
        )
        is False
    )
    from services.db import get_db

    conn = get_db()
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM subscription_events WHERE subscription_id='sub_1'"
    ).fetchone()["n"]
    conn.close()
    assert n == 1


def test_record_renewal_dedup_per_period(clean_sub_events):
    conv.record_subscription_event(
        "sub_1", "subscription_created", 1000, created_at="2026-08-03T12:00:00Z"
    )
    # First renewal (period 1 ends → renews_at moved forward).
    assert (
        conv.record_subscription_event("sub_1", "renewal", 2000, renews_at="2026-09-03")
        is True
    )
    # Same period re-delivered / unrelated update → no double count.
    assert (
        conv.record_subscription_event("sub_1", "renewal", 2001, renews_at="2026-09-03")
        is False
    )
    # Second renewal (new period) counts.
    assert (
        conv.record_subscription_event("sub_1", "renewal", 3000, renews_at="2026-10-03")
        is True
    )
    from services.db import get_db

    conn = get_db()
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM subscription_events "
        "WHERE subscription_id='sub_1' AND event='renewal'"
    ).fetchone()["n"]
    conn.close()
    assert n == 2


def test_record_renewal_without_period_ignored(clean_sub_events):
    # Paused/cancelled update carries no renews_at → not a renewal.
    assert (
        conv.record_subscription_event("sub_1", "renewal", 2000, renews_at="") is False
    )


def test_cohort_ltv_report(clean_sub_events, monkeypatch):
    monkeypatch.setenv("PRO_PRICE_USD_MONTH", "10")
    monkeypatch.setenv("PRO_MARGIN_PCT", "1.0")
    # Cohort 2026-08: 2 subs, 1 renewal each (retention m1 = 100%).
    conv.record_subscription_event(
        "s1", "subscription_created", 1000, created_at="2026-08-01T12:00:00Z"
    )
    conv.record_subscription_event("s1", "renewal", 2000, renews_at="2026-09-01")
    conv.record_subscription_event(
        "s2", "subscription_created", 1001, created_at="2026-08-15T12:00:00Z"
    )
    conv.record_subscription_event("s2", "renewal", 2001, renews_at="2026-09-15")
    # Cohort 2026-09: 1 sub, 3 renewals.
    conv.record_subscription_event(
        "s3", "subscription_created", 3000, created_at="2026-09-10T12:00:00Z"
    )
    conv.record_subscription_event("s3", "renewal", 4000, renews_at="2026-10-10")
    conv.record_subscription_event("s3", "renewal", 5000, renews_at="2026-11-10")
    conv.record_subscription_event("s3", "renewal", 6000, renews_at="2026-12-10")

    r = conv.cohort_ltv_report()
    assert r["has_renewal_data"] is True
    assert [c["cohort_month"] for c in r["cohorts"]] == ["2026-08", "2026-09"]
    c1 = r["cohorts"][0]
    assert c1["subscriptions"] == 2
    assert c1["renewals"] == 2
    # Revenue = 10 × (2 subs + 2 renewals) × 1.0 = 40; LTV = 20.
    assert c1["revenue_usd"] == 40.0
    assert c1["ltv_usd"] == 20.0
    assert c1["retention_m1_pct"] == 100.0
    assert c1["retention_m3_pct"] == 0.0
    c2 = r["cohorts"][1]
    assert c2["subscriptions"] == 1
    assert c2["renewals"] == 3
    assert c2["revenue_usd"] == 40.0  # 10 × 4 × 1.0
    assert c2["ltv_usd"] == 40.0
    assert c2["retention_m1_pct"] == 100.0
    assert c2["retention_m3_pct"] == 100.0
    # Overall real LTV = (40 + 40) / 3 subs ≈ 26.67.
    assert r["ltv_real_usd"] == round(80.0 / 3, 2)


def test_cohort_ltv_empty(clean_sub_events):
    r = conv.cohort_ltv_report()
    assert r["has_renewal_data"] is False
    assert r["cohorts"] == []
    assert r["ltv_real_usd"] is None


def test_ltv_cac_fallback_estimate_without_renewals(clean_sub_events, monkeypatch):
    monkeypatch.delenv("PRO_PRICE_USD_MONTH", raising=False)
    monkeypatch.delenv("PRO_LICENSE_MONTHS", raising=False)
    monkeypatch.delenv("PRO_MARGIN_PCT", raising=False)
    # No subscription data → falls back to the price×months estimate.
    r = conv.ltv_cac_report(paid_count=0)
    assert r["ltv_source"] == "estimate"
    assert r["has_renewal_data"] is False
    assert r["ltv_usd"] == 101.52  # 9 × 12 × 0.94
    assert r["ltv_estimate_usd"] == 101.52
    assert r["cohorts"] == []


def test_ltv_cac_uses_real_cohort(clean_sub_events, monkeypatch):
    monkeypatch.setenv("PRO_PRICE_USD_MONTH", "10")
    monkeypatch.setenv("PRO_MARGIN_PCT", "1.0")
    conv.record_subscription_event(
        "s1", "subscription_created", 1000, created_at="2026-08-01T12:00:00Z"
    )
    conv.record_subscription_event("s1", "renewal", 2000, renews_at="2026-09-01")
    r = conv.ltv_cac_report(paid_count=1)
    assert r["ltv_source"] == "cohort_real"
    assert r["has_renewal_data"] is True
    assert r["ltv_usd"] == 20.0  # 10 × (1 sub + 1 renewal) × 1.0 / 1
    assert r["ltv_estimate_usd"] == 120.0  # 10 × 12 × 1.0 kept for reference
    assert len(r["cohorts"]) == 1


# ── Feature over-concentration alert (Issue #163) ─────────────────────────


def test_detect_feature_overconcentration_flags_top(clean_events):
    conv.track_event("paywall_view", tenant_id="t1", meta={"feature": "monte_carlo"})
    conv.track_event("paywall_view", tenant_id="t2", meta={"feature": "monte_carlo"})
    conv.track_event("paywall_view", tenant_id="t3", meta={"feature": "auto_pilot"})
    r = conv.funnel_report()
    alert = conv.detect_feature_overconcentration(r["paywall_by_feature"], min_pct=50.0)
    assert alert is not None
    assert alert["feature"] == "monte_carlo"
    assert alert["count"] == 2
    assert alert["share_pct"] == 66.7  # 2/3
    assert alert["min_pct"] == 50.0


def test_detect_feature_overconcentration_no_flag(clean_events):
    # 3 features evenly split → none crosses 50%.
    for i, feat in enumerate(("a", "b", "c")):
        conv.track_event("paywall_view", tenant_id=f"t{i}", meta={"feature": feat})
    r = conv.funnel_report()
    assert (
        conv.detect_feature_overconcentration(r["paywall_by_feature"], min_pct=50.0)
        is None
    )
    # Threshold tuned down to 34 → 'a' (33.3%) still not enough; at 33 it flags.
    assert (
        conv.detect_feature_overconcentration(r["paywall_by_feature"], min_pct=34.0)
        is None
    )
    alert = conv.detect_feature_overconcentration(r["paywall_by_feature"], min_pct=33.0)
    assert alert is not None and alert["share_pct"] == 33.3


def test_detect_feature_overconcentration_exact_threshold(clean_events):
    # share == min_pct exactly (50/50 split at 50%) MUST trigger (>=).
    alert = conv.detect_feature_overconcentration(
        [{"feature": "a", "count": 5}, {"feature": "b", "count": 5}], min_pct=50.0
    )
    assert alert is not None
    assert alert["feature"] == "a" and alert["share_pct"] == 50.0
    # min_pct=None / garbage falls back to the 50% default — no crash.
    r = conv.detect_feature_overconcentration(
        [{"feature": "a", "count": 2}, {"feature": "b", "count": 1}], min_pct=None
    )
    assert r is not None and r["min_pct"] == 50.0  # 66.7% >= default 50
    assert (
        conv.detect_feature_overconcentration(
            [{"feature": "a", "count": 2}, {"feature": "b", "count": 1}],
            min_pct="oops",
        )
        is not None
    )


def test_detect_feature_overconcentration_empty_and_garbage():
    assert conv.detect_feature_overconcentration([], min_pct=50.0) is None
    assert (
        conv.detect_feature_overconcentration(
            [{"feature": "x", "count": 0}], min_pct=1.0
        )
        is None
    )
    # Unknown bucket counts as a real feature (legacy rows can legitimately flag).
    r = conv.detect_feature_overconcentration(
        [{"feature": "unknown", "count": 9}, {"feature": "a", "count": 1}], min_pct=50.0
    )
    assert r is not None and r["feature"] == "unknown" and r["share_pct"] == 90.0


def test_admin_conversion_feature_alert_payload(
    isolated_client, monkeypatch, clean_events
):
    monkeypatch.setenv("API_KEY", "operator-key-123")
    conv.track_event("paywall_view", tenant_id="t1", meta={"feature": "monte_carlo"})
    conv.track_event("paywall_view", tenant_id="t2", meta={"feature": "monte_carlo"})
    conv.track_event("paywall_view", tenant_id="t3", meta={"feature": "auto_pilot"})
    resp = isolated_client.get(
        "/api/admin/conversion?feature_pct=50",
        headers={"X-API-Key": "operator-key-123"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["feature_alert"] is not None
    assert data["feature_alert"]["feature"] == "monte_carlo"
    # Threshold clamped: feature_pct=999 → 50 (no crash).
    resp2 = isolated_client.get(
        "/api/admin/conversion?feature_pct=999",
        headers={"X-API-Key": "operator-key-123"},
    )
    assert resp2.status_code == 200


# ── Routes ─────────────────────────────────────────────────────────────────


def test_track_route_known_event(isolated_client):
    resp = isolated_client.post(
        "/api/conversion/track", json={"event": "modal_open", "meta": {"plan": "pro"}}
    )
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
    resp = isolated_client.get(
        "/api/admin/conversion", headers={"X-API-Key": "operator-key-123"}
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert "funnel" in data and "economics" in data
    assert "stages" in data["funnel"]
    assert "ltv_usd" in data["economics"]


# ── Proxy-aware admin gate (Issue #254 — Sev-2 Render) ────────────────────
# No Render o proxy entrega remote_addr=loopback; o gate antigo tratava isso
# como operador local e expunha /api/admin/* publicamente. Agora header de
# proxy marca o request como remoto → exige X-API-Key válida.


def test_admin_conversion_localhost_without_proxy_allowed(isolated_client, monkeypatch):
    """Localhost REAL (sem proxy headers) continua liberado — dev/ssh-tunnel."""
    monkeypatch.delenv("API_KEY", raising=False)
    resp = isolated_client.get("/api/admin/conversion")
    assert resp.status_code == 200


def test_admin_conversion_blocked_behind_proxy_without_key(
    isolated_client, monkeypatch
):
    """O caso do Render: loopback COM X-Forwarded-For = remoto → 403 sem key."""
    monkeypatch.delenv("API_KEY", raising=False)
    resp = isolated_client.get(
        "/api/admin/conversion",
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
        headers={"X-Forwarded-For": "203.0.113.5"},
    )
    assert resp.status_code == 403


def test_admin_conversion_allowed_behind_proxy_with_valid_key(
    isolated_client, monkeypatch
):
    """Operador remoto com X-API-Key válida → 200 mesmo atrás do proxy."""
    monkeypatch.setenv("API_KEY", "operator-key-123")
    resp = isolated_client.get(
        "/api/admin/conversion",
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
        headers={"X-Forwarded-For": "203.0.113.5", "X-API-Key": "operator-key-123"},
    )
    assert resp.status_code == 200


def test_admin_conversion_blocked_behind_proxy_with_wrong_key(
    isolated_client, monkeypatch
):
    """Key errada atrás do proxy → 403 (nunca cai no caminho local)."""
    monkeypatch.setenv("API_KEY", "operator-key-123")
    resp = isolated_client.get(
        "/api/admin/conversion",
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
        headers={"X-Forwarded-For": "203.0.113.5", "X-API-Key": "nope"},
    )
    assert resp.status_code == 403


def test_admin_licenses_blocked_behind_proxy_without_key(isolated_client, monkeypatch):
    """Rota crítica de emissão de chaves: loopback+proxy sem key → 403."""
    monkeypatch.delenv("API_KEY", raising=False)
    resp = isolated_client.post(
        "/api/admin/licenses",
        json={"months": 1},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
        headers={"X-Forwarded-For": "203.0.113.5"},
    )
    assert resp.status_code == 403


# ── Session attribution (Issue #155 — funnel_id ponta-a-ponta) ─────────────


def _seed_session_events():
    """Seed a realistic per-user funnel path with funnel_ids.

    f_1 sees paywall, opens modal, starts checkout and pays.
    f_2 sees paywall, opens modal, starts checkout, bails (no paid).
    f_3 sees paywall, opens modal, bails.
    """
    conv.track_event("paywall_view", meta={"funnel_id": "f_1"})
    conv.track_event("modal_open", meta={"funnel_id": "f_1"})
    conv.track_event("checkout_start", meta={"funnel_id": "f_1", "plan": "pro"})
    conv.track_event("paid", meta={"funnel_id": "f_1", "plan": "pro"})
    conv.track_event("paywall_view", meta={"funnel_id": "f_2"})
    conv.track_event("modal_open", meta={"funnel_id": "f_2"})
    conv.track_event("checkout_start", meta={"funnel_id": "f_2", "plan": "pro"})
    conv.track_event("paywall_view", meta={"funnel_id": "f_3"})
    conv.track_event("modal_open", meta={"funnel_id": "f_3"})


def test_track_event_persists_funnel_id(clean_events):
    conv.track_event("checkout_start", meta={"funnel_id": "f_abc123", "plan": "pro"})
    import json
    from services.db import get_db

    conn = get_db()
    row = conn.execute("SELECT meta FROM conversion_events").fetchone()
    conn.close()
    meta = json.loads(row["meta"])
    assert meta.get("funnel_id") == "f_abc123"


def test_funnel_report_session_view(clean_events):
    _seed_session_events()
    rep = conv.funnel_report()
    assert rep["sessions_count"] == 3
    assert rep["session_stages"]["modal_open"] == 3
    assert rep["session_stages"]["checkout_start"] == 2
    assert rep["session_stages"]["paid"] == 1
    # Per-user drop-off: modal 3 → checkout 2 (1 loss), checkout 2 → paid 1.
    so = {d["to"]: d for d in rep["session_drop_off"]}
    assert so["checkout_start"]["prev"] == 3
    assert so["checkout_start"]["next"] == 2
    assert so["checkout_start"]["loss_abs"] == 1
    assert so["checkout_start"]["conversion_pct"] == pytest.approx(66.7, abs=0.2)
    assert so["paid"]["prev"] == 2
    assert so["paid"]["next"] == 1
    # money ÷ base = 1 ÷ 3
    assert rep["session_conversion_rate_pct"] == pytest.approx(33.3, abs=0.2)
    # Aggregate (per-event count) still present and larger — no regression.
    assert rep["stages"]["modal_open"] == 3
    assert rep["stages"]["checkout_start"] == 2


def test_funnel_report_session_view_no_ids_backward_compat(clean_events):
    """Events recorded before #155 carry no funnel_id → session view zeros,
    aggregate funnel untouched."""
    conv.track_event("modal_open")
    conv.track_event("paid")
    rep = conv.funnel_report()
    assert rep["sessions_count"] == 0
    assert rep["session_stages"] == {}
    assert rep["session_drop_off"] == []
    assert rep["session_conversion_rate_pct"] == 0.0
    assert rep["stages"]["modal_open"] == 1
    assert rep["stages"]["paid"] == 1


def test_funnel_report_session_view_paywall_without_ids(clean_events):
    """paywall_view is fired server-side without a funnel_id — the session
    base must fall back to the first attributed stage (modal_open here), not
    zero."""
    conv.track_event("paywall_view")  # server-side, no funnel_id
    conv.track_event("modal_open", meta={"funnel_id": "f_1"})
    conv.track_event("checkout_start", meta={"funnel_id": "f_1"})
    conv.track_event("paid", meta={"funnel_id": "f_1"})
    rep = conv.funnel_report()
    assert rep["sessions_count"] == 1
    assert rep["session_stages"]["modal_open"] == 1
    assert rep["session_conversion_rate_pct"] == 100.0


def test_disabled_card_checkout_does_not_call_provider(isolated_client, monkeypatch):
    """Legacy LS credentials cannot bypass the disabled delivery gate."""
    captured = {}

    def _fake(plan="pro", email="", funnel_id=""):
        captured["plan"] = plan
        captured["funnel_id"] = funnel_id
        return "https://checkout.example/x"

    monkeypatch.setenv("LEMON_SQUEEZY_API_KEY", "ls-test-key")
    monkeypatch.setenv("LEMON_SQUEEZY_WEBHOOK_SECRET", "whsec-test")
    monkeypatch.setenv("LEMON_SQUEEZY_STORE_ID", "1")
    monkeypatch.setenv("LEMON_SQUEEZY_VARIANT_ID", "10")
    import app as _app_module

    monkeypatch.setattr(_app_module._payments, "create_checkout", _fake)
    resp = isolated_client.post(
        "/api/upgrade/checkout",
        json={"plan": "pro", "method": "card", "funnel_id": "f_route_test"},
    )
    assert resp.status_code == 503
    assert captured == {}


def test_disabled_card_checkout_never_contacts_provider(monkeypatch):
    """Complete legacy env still fails closed before any provider request."""
    import services.payments as payments

    monkeypatch.setenv("LEMON_SQUEEZY_API_KEY", "ls-test-key")
    monkeypatch.setenv("LEMON_SQUEEZY_WEBHOOK_SECRET", "whsec-test")
    monkeypatch.setenv("LEMON_SQUEEZY_STORE_ID", "1")
    monkeypatch.setenv("LEMON_SQUEEZY_VARIANT_ID", "10")
    sent = []

    def _post(*args, **kwargs):
        sent.append((args, kwargs))
        raise AssertionError("disabled checkout must not contact Lemon Squeezy")

    monkeypatch.setattr(payments.requests, "post", _post)
    url = payments.create_checkout(plan="pro", funnel_id="f_payload_test")
    assert url is None
    assert sent == []


def test_webhook_paid_attributes_funnel_id(monkeypatch):
    """order_created webhook with meta.custom_data.funnel_id lands the paid
    event in the same browser funnel."""
    import services.payments as payments

    monkeypatch.setenv("LEMON_SQUEEZY_API_KEY", "ls-test-key")
    monkeypatch.setenv("LEMON_SQUEEZY_WEBHOOK_SECRET", "whsec-test")
    monkeypatch.setenv("LEMON_SQUEEZY_STORE_ID", "1")
    monkeypatch.setenv("LEMON_SQUEEZY_VARIANT_ID", "10")
    payload = {
        "meta": {
            "event_name": "order_created",
            "custom_data": {"funnel_id": "f_webhook_test"},
        },
        "data": {
            "id": "9001",
            "attributes": {
                "store_id": 1,
                "user_email": "buyer@example.com",
                "first_order_item": {"variant_id": 10},
            },
        },
    }
    assert payments.handle_webhook(payload)
    import json
    from services.db import get_db

    conn = get_db()
    row = conn.execute(
        "SELECT meta FROM conversion_events WHERE event='paid' ORDER BY ts DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert row is not None
    assert json.loads(row["meta"]).get("funnel_id") == "f_webhook_test"


def test_webhook_paid_no_custom_data_no_crash(monkeypatch):
    """Webhooks from old checkouts carry no custom_data — the paid event is
    still recorded, just without attribution."""
    import services.payments as payments

    monkeypatch.setenv("LEMON_SQUEEZY_API_KEY", "ls-test-key")
    monkeypatch.setenv("LEMON_SQUEEZY_WEBHOOK_SECRET", "whsec-test")
    monkeypatch.setenv("LEMON_SQUEEZY_STORE_ID", "1")
    monkeypatch.setenv("LEMON_SQUEEZY_VARIANT_ID", "10")
    payload = {
        "meta": {"event_name": "order_created"},
        "data": {
            "id": "9002",
            "attributes": {
                "store_id": 1,
                "user_email": "buyer@example.com",
                "first_order_item": {"variant_id": 10},
            },
        },
    }
    assert payments.handle_webhook(payload)
    import json
    from services.db import get_db

    conn = get_db()
    row = conn.execute(
        "SELECT meta FROM conversion_events WHERE event='paid' ORDER BY ts DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert row is not None
    assert "funnel_id" not in json.loads(row["meta"])


# ── Weekly trend buckets + CSV export (Issue #156 — 18-B) ──────────────────


def _insert_at(ts, event, meta=None):
    """Insert a conversion event at an explicit ts (bypasses time.time)."""
    from services.db import get_db
    import json as _json

    conn = get_db()
    conn.execute(
        "INSERT INTO conversion_events (ts, event, tenant_id, meta, created_at) "
        "VALUES (?, ?, '', ?, ?)",
        (ts, event, _json.dumps(meta or {}), ts),
    )
    conn.commit()
    conn.close()


def _iso_key(ts):
    from datetime import datetime, timezone

    iso = datetime.fromtimestamp(ts, tz=timezone.utc).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


@pytest.fixture
def weekly_clock(monkeypatch):
    """Freeze weekly reports and their fixtures to one deterministic anchor."""
    from datetime import datetime, timezone

    anchor = int(datetime(2030, 8, 14, 12, 0, tzinfo=timezone.utc).timestamp())
    monkeypatch.setattr(conv.time, "time", lambda: anchor)
    return anchor


def _recent_week_ts(now_ts, weeks_ago=1):
    """Noon-UTC timestamp in a completed ISO week before ``now_ts``."""
    from datetime import datetime, timedelta, timezone

    now = datetime.fromtimestamp(now_ts, tz=timezone.utc)
    this_monday = (now - timedelta(days=now.weekday())).replace(
        hour=12, minute=0, second=0, microsecond=0
    )
    return int((this_monday - timedelta(weeks=weeks_ago)).timestamp())


def _iso_week_start_ts(ts):
    from datetime import datetime, timedelta, timezone

    instant = datetime.fromtimestamp(ts, tz=timezone.utc)
    monday = (instant - timedelta(days=instant.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return int(monday.timestamp())


def test_funnel_weekly_buckets(clean_events, weekly_clock):
    # Two distinct, completed ISO weeks inside the report window.
    t_old = _recent_week_ts(weekly_clock, weeks_ago=2)
    t_new = _recent_week_ts(weekly_clock, weeks_ago=1)
    _insert_at(t_old, "paywall_view")
    _insert_at(t_old, "modal_open")
    _insert_at(t_old, "checkout_start")
    _insert_at(t_old, "paid")
    _insert_at(t_old, "key_activated")
    _insert_at(t_new, "paywall_view")
    _insert_at(t_new, "paywall_view")  # two paywalls next week, zero conversions

    weekly = conv.funnel_weekly_report(weeks=8)
    keys = [b["week"] for b in weekly]
    assert keys == sorted(keys)
    assert keys[0] == _iso_key(t_old)
    assert keys[1] == _iso_key(t_new)

    old = weekly[0]
    assert old["stages"]["paywall_view"] == 1
    assert old["stages"]["key_activated"] == 1
    assert old["conversion_rate_pct"] == 100.0
    assert old["drop_off"][0]["from"] == "paywall_view"
    assert old["drop_off"][0]["to"] == "modal_open"

    new = weekly[1]
    assert new["stages"]["paywall_view"] == 2
    assert new["conversion_rate_pct"] == 0.0
    # week_start_ts is the Monday 00:00 UTC of the bucket.
    assert new["week_start_ts"] == _iso_week_start_ts(t_new)


def test_funnel_weekly_sessions_count(clean_events, weekly_clock):
    t = _recent_week_ts(weekly_clock)
    _insert_at(t, "paywall_view", {"funnel_id": "f_1"})
    _insert_at(t, "modal_open", {"funnel_id": "f_1"})
    _insert_at(t, "checkout_start", {"funnel_id": "f_1"})
    _insert_at(t, "paid", {"funnel_id": "f_1"})
    _insert_at(t, "paywall_view", {"funnel_id": "f_2"})
    _insert_at(t, "modal_open")  # no funnel_id → not attributed

    weekly = conv.funnel_weekly_report(weeks=8)
    assert len(weekly) == 1
    assert weekly[0]["sessions_count"] == 2
    assert weekly[0]["stages"]["paywall_view"] == 2
    assert weekly[0]["stages"]["modal_open"] == 2


def test_funnel_weekly_empty_and_weeks_clamp(clean_events):
    assert conv.funnel_weekly_report(weeks=8) == []
    # weeks=0 / 999 clamp to the valid range without crashing.
    assert conv.funnel_weekly_report(weeks=0) == []
    assert conv.funnel_weekly_report(weeks=999) == []


def test_funnel_weekly_csv(clean_events, weekly_clock):
    t = _recent_week_ts(weekly_clock)
    _insert_at(t, "paywall_view")
    _insert_at(t, "key_activated")

    weekly = conv.funnel_weekly_report(weeks=8)
    out = conv.funnel_weekly_csv(weekly)
    lines = out.strip().split("\n")
    assert lines[0].startswith("week,paywall_view,modal_open")
    assert "conversion_rate_pct" in lines[0]
    row = lines[1].split(",")
    assert row[0] == _iso_key(t)
    assert row[1] == "1"  # paywall_view
    assert row[5] == "1"  # key_activated
    assert row[6] == "100.0"  # conversion_rate_pct
    assert row[7] == "0"  # sessions_count
    # Empty buckets → just the header (no feature columns when none exist).
    assert conv.funnel_weekly_csv([]) == (
        "week,paywall_view,modal_open,checkout_start,paid,key_activated,"
        "conversion_rate_pct,sessions_count\r\n"
    )


def test_funnel_weekly_csv_feature_columns(clean_events, weekly_clock):
    # Week 1: monte_carlo (2) + auto_pilot (1); Week 2: only monte_carlo (1).
    t1 = _recent_week_ts(weekly_clock, weeks_ago=2)
    t2 = _recent_week_ts(weekly_clock, weeks_ago=1)
    _insert_at(t1, "paywall_view", {"feature": "monte_carlo"})
    _insert_at(t1, "paywall_view", {"feature": "monte_carlo"})
    _insert_at(t1, "paywall_view", {"feature": "auto_pilot"})
    _insert_at(t2, "paywall_view", {"feature": "monte_carlo"})

    weekly = conv.funnel_weekly_report(weeks=8)
    assert len(weekly) == 2
    # Per-week breakdown exposed on the JSON buckets too (Issue #165).
    bf1 = {f["feature"]: f["count"] for f in weekly[0]["paywall_by_feature"]}
    assert bf1 == {"monte_carlo": 2, "auto_pilot": 1}
    bf2 = {f["feature"]: f["count"] for f in weekly[1]["paywall_by_feature"]}
    assert bf2 == {"monte_carlo": 1}

    out = conv.funnel_weekly_csv(weekly)
    # csv.writer emits CRLF — normalize so trailing \r never pollutes cells.
    lines = [ln.rstrip("\r") for ln in out.split("\n") if ln]
    header = lines[0].split(",")
    # Feature count columns appended AFTER the standard 8, sorted; the
    # feature_pct share columns come right after the counts (Issue #168) and
    # the feature_delta trend columns after the shares (Issue #171).
    assert header[8] == "feature:auto_pilot"
    assert header[9] == "feature:monte_carlo"
    assert header[10] == "feature_pct:auto_pilot"
    assert header[11] == "feature_pct:monte_carlo"
    assert header[12] == "feature_delta:auto_pilot"
    assert header[13] == "feature_delta:monte_carlo"
    r1 = lines[1].split(",")
    assert r1[0] == _iso_key(t1)
    assert r1[header.index("feature:monte_carlo")] == "2"
    assert r1[header.index("feature:auto_pilot")] == "1"
    # Week 1: 3 paywalls total → monte_carlo 2/3 = 66.7%, auto_pilot 33.3%.
    assert r1[header.index("feature_pct:monte_carlo")] == "66.7"
    assert r1[header.index("feature_pct:auto_pilot")] == "33.3"
    # First row → no baseline → delta EMPTY (never a fake 0).
    assert r1[header.index("feature_delta:monte_carlo")] == ""
    assert r1[header.index("feature_delta:auto_pilot")] == ""
    r2 = lines[2].split(",")
    assert r2[0] == _iso_key(t2)
    assert r2[header.index("feature:monte_carlo")] == "1"
    assert r2[header.index("feature:auto_pilot")] == "0"  # absent this week
    # Week 2: 1 paywall → monte_carlo 100%; absent feature → 0.0.
    assert r2[header.index("feature_pct:monte_carlo")] == "100.0"
    assert r2[header.index("feature_pct:auto_pilot")] == "0.0"
    # Week 2 trend vs Week 1: +33.3 (100.0-66.7) and -33.3 (0.0-33.3).
    assert r2[header.index("feature_delta:monte_carlo")] == "33.3"
    assert r2[header.index("feature_delta:auto_pilot")] == "-33.3"


def test_funnel_weekly_csv_feature_pct_zero_paywall_week():
    """Issue #168: a week with NO paywalls (feature union from other weeks)
    renders 0.0 share — never a ZeroDivisionError or a fabricated number."""
    buckets = [
        {
            "week": "2026-W31",
            "stages": {"paywall_view": 3},
            "paywall_by_feature": [{"feature": "monte_carlo", "count": 2}],
        },
        {"week": "2026-W32", "stages": {}, "paywall_by_feature": []},
    ]
    out = conv.funnel_weekly_csv(buckets)
    lines = [ln.rstrip("\r") for ln in out.split("\n") if ln]
    header = lines[0].split(",")
    r2 = lines[2].split(",")
    assert r2[0] == "2026-W32"
    assert r2[header.index("feature:monte_carlo")] == "0"
    assert r2[header.index("feature_pct:monte_carlo")] == "0.0"
    # W32 has no paywalls → share 0.0 vs W31's 66.7 → delta -66.7.
    assert r2[header.index("feature_delta:monte_carlo")] == "-66.7"


def test_funnel_weekly_csv_feature_delta_new_feature_appears():
    """Issue #171: a feature ABSENT last week that appears this week gets its
    FULL share as delta (previous 0.0) — the trend is honest, never a fake 0."""
    buckets = [
        {
            "week": "2026-W30",
            "stages": {"paywall_view": 4},
            "paywall_by_feature": [{"feature": "auto_pilot", "count": 3}],
        },
        {
            "week": "2026-W31",
            "stages": {"paywall_view": 4},
            "paywall_by_feature": [
                {"feature": "auto_pilot", "count": 2},
                {"feature": "monte_carlo", "count": 2},
            ],
        },
    ]
    out = conv.funnel_weekly_csv(buckets)
    lines = [ln.rstrip("\r") for ln in out.split("\n") if ln]
    header = lines[0].split(",")
    r2 = lines[2].split(",")
    # monte_carlo: absent W30 (0.0) → 50.0% in W31 → delta +50.0.
    assert r2[header.index("feature_delta:monte_carlo")] == "50.0"
    # auto_pilot: 75.0% → 50.0% → delta -25.0.
    assert r2[header.index("feature_delta:auto_pilot")] == "-25.0"


def test_funnel_weekly_csv_formula_injection_neutralized():
    """Issue #184: feature names are tenant/client-controlled — a name like
    ``=HYPERLINK(...)`` / ``=1+1`` would EXECUTE in Excel/Sheets. The CSV
    must prefix dangerous text cells with ``'`` (shared csv_neutralize guard)
    while numbers/None pass through untouched."""
    buckets = [
        {
            "week": "2026-W31",
            "stages": {"paywall_view": 2},
            "paywall_by_feature": [
                {"feature": "=1+1", "count": 1},
                {"feature": "safe_name", "count": 1},
            ],
        }
    ]
    out = conv.funnel_weekly_csv(buckets)
    rows = _csv_rows(out)
    header = rows[0]
    # Header cells neutralized: '=1+1' → "'=1+1" (inert text), safe names pass.
    assert "feature:'=1+1" in header
    assert "feature:safe_name" in header
    assert "feature_pct:'=1+1" in header
    assert "feature_delta:'=1+1" in header
    # No raw formula-prefixed cell anywhere in the CSV body.
    assert not any(
        cell.startswith(("=", "+", "@")) for cell in header
    ), "raw formula prefix leaked into a header cell"
    # Counts are NUMBERS and stay numbers (never prefixed / never quoted weirdly).
    row = rows[1]
    assert row[header.index("feature:'=1+1")] == "1"
    assert row[header.index("feature:safe_name")] == "1"
    # Share columns: 1/2 = 50.0 both — math unaffected by the guard.
    assert row[header.index("feature_pct:'=1+1")] == "50.0"
    assert row[header.index("feature_pct:safe_name")] == "50.0"


def _csv_rows(out):
    """Parse funnel CSV output with csv.reader (handles quoting) — split(',') is
    wrong when a cell contains a comma (e.g. an evil feature name)."""
    import csv as _csv
    import io as _io

    return list(_csv.reader(_io.StringIO(out)))


def test_funnel_weekly_csv_other_dangerous_prefixes():
    """Issue #184: @ and + prefixes are also formula risks (Excel treats
    cells starting with @ as formula / + as arithmetic) — all neutralized."""
    buckets = [
        {
            "week": "2026-W32",
            "stages": {"paywall_view": 3},
            "paywall_by_feature": [
                {"feature": "@SUM(1,1)", "count": 1},
                {"feature": "+2+2", "count": 1},
                {"feature": "-cmd", "count": 1},
            ],
        }
    ]
    out = conv.funnel_weekly_csv(buckets)
    header = _csv_rows(out)[0]
    assert "feature:'@SUM(1,1)" in header
    assert "feature:'+2+2" in header
    assert "feature:'-cmd" in header
    assert not any(
        cell.startswith(("=", "+", "@", "-")) for cell in header
    ), "raw formula prefix leaked into a header cell"


def test_funnel_weekly_csv_week_cell_neutralized():
    """Issue #184: the week cell is text — a crafted bucket (server-side only,
    but defensive) with a formula prefix must not leak raw into the CSV."""
    buckets = [{"week": '=HYPERLINK("http://evil","x")', "stages": {}}]
    out = conv.funnel_weekly_csv(buckets)
    row = _csv_rows(out)[1]
    assert row[0] == '\'=HYPERLINK("http://evil","x")'


def test_admin_conversion_weekly_payload(
    isolated_client, monkeypatch, clean_events, weekly_clock
):
    monkeypatch.setenv("API_KEY", "operator-key-123")
    t = _recent_week_ts(weekly_clock)
    _insert_at(t, "paywall_view")
    _insert_at(t, "key_activated")

    resp = isolated_client.get(
        "/api/admin/conversion?weeks=4",
        headers={"X-API-Key": "operator-key-123"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert "weekly" in data
    assert len(data["weekly"]) == 1
    assert data["weekly"][0]["week"] == _iso_key(t)


def test_admin_conversion_csv_export(
    isolated_client, monkeypatch, clean_events, weekly_clock
):
    monkeypatch.setenv("API_KEY", "operator-key-123")
    t = _recent_week_ts(weekly_clock)
    _insert_at(t, "paywall_view")
    _insert_at(t, "modal_open")

    resp = isolated_client.get(
        "/api/admin/conversion?format=csv",
        headers={"X-API-Key": "operator-key-123"},
    )
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert "attachment" in (resp.headers.get("Content-Disposition") or "")
    assert "funnel_weekly_" in resp.headers["Content-Disposition"]
    body = resp.get_data(as_text=True)
    assert body.startswith("\ufeffweek,paywall_view")  # BOM + header
    assert _iso_key(t) in body


def test_admin_conversion_csv_feature_columns(
    isolated_client, monkeypatch, clean_events, weekly_clock
):
    monkeypatch.setenv("API_KEY", "operator-key-123")
    t = _recent_week_ts(weekly_clock)
    _insert_at(t, "paywall_view", {"feature": "monte_carlo"})
    _insert_at(t, "paywall_view", {"feature": "auto_pilot"})

    resp = isolated_client.get(
        "/api/admin/conversion?format=csv",
        headers={"X-API-Key": "operator-key-123"},
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert body.startswith("\ufeffweek,paywall_view,modal_open")
    assert "feature:monte_carlo" in body
    assert "feature:auto_pilot" in body
    # csv.writer emits CRLF — strip each line so trailing \r never pollutes
    # the last column / the header lookup.
    lines = [ln.rstrip("\r") for ln in body.split("\n") if ln]
    header = lines[0].lstrip("\ufeff").split(",")
    row = lines[1].split(",")
    assert row[header.index("feature:monte_carlo")] == "1"
    assert row[header.index("feature:auto_pilot")] == "1"
    # Share % columns ride along on the CSV export (Issue #168): 1/2 = 50.0.
    assert "feature_pct:monte_carlo" in header
    assert "feature_pct:auto_pilot" in header
    assert row[header.index("feature_pct:monte_carlo")] == "50.0"
    assert row[header.index("feature_pct:auto_pilot")] == "50.0"
    # Trend columns ride along (Issue #171); single week → no baseline → empty.
    assert "feature_delta:monte_carlo" in header
    assert "feature_delta:auto_pilot" in header
    assert row[header.index("feature_delta:monte_carlo")] == ""
    assert row[header.index("feature_delta:auto_pilot")] == ""


def test_admin_conversion_csv_requires_admin(isolated_client):
    resp = isolated_client.get(
        "/api/admin/conversion?format=csv",
        environ_base={"REMOTE_ADDR": "203.0.113.5"},
    )
    assert resp.status_code == 403
