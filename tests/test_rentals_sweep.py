"""Hermetic tests for the periodic RENTAL P/L SWEEP.

The sweep lets a bad rental fire webhook/push WITHOUT the user opening the
panel: a daemon loop visits only tenants that ENABLED the alert AND have MRR
credentials (pl_alert_enabled_tenants), fetches MRR renter history (1 call),
evaluates, ingests, and dispatches via the shared dispatch_rental_pl_alerts.

Covers:
  1. pl_alert_enabled_tenants — default + named tenants, requires MRR key,
     ignores disabled/positive thresholds, never raises on a bad DB.
  2. sweep_rental_pl_alerts — 1 MRR call, evaluate + ingest + count; needs_auth
     / provider errors are 0 (never crash).
  3. dispatch_rental_pl_alerts — shared dispatcher fires webhook + push per
     tenant (no-op on empty, tenant-aware settings).
  4. _rentals_sweep_once — visits every enabled tenant, staggers, and the
     route still works through the shared dispatcher.
"""

import sys
import time

import pytest

sys.path.insert(0, ".")

import services.user_polling as _up  # noqa: E402
import services.rental_performance as rp  # noqa: E402


class _FakeListing:
    """Minimal shape of fetch_mrr_rentals output."""

    def __init__(self, rentals=None, success=True, needs_auth=False, error=""):
        self.data = {
            "success": success,
            "needs_auth": needs_auth,
            "rentals": rentals or [],
            "total": len(rentals or []),
            "error": error,
        }

    def get(self, k, default=None):
        return self.data.get(k, default)


def _mr_history_row(rid="1", ended=True, paid=0.00001, avg_th=100.0, lenh=1.0):
    return {
        "id": rid,
        "ended": ended,
        "start": "2026-07-25 19:17:20 UTC",
        "end": "2026-07-25 23:08:20 UTC",
        "end_unix": int(time.time()) - 3600,
        "price_paid_btc": paid,
        "hashrate_average_th": avg_th,
        "hashrate_percent": 96.5,
        "length_hours": lenh,
        "rig": {"id": "376882", "name": "A02 165TH"},
    }


# ── pl_alert_enabled_tenants ────────────────────────────────────────────────


def test_enabled_tenants_requires_negative_threshold_and_mrr_key(tmp_path, monkeypatch):
    """Only tenants with rental_pl_alert_pct < 0 AND MRR credentials are
    returned (the sweep must not burn provider calls for opted-out accounts)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "sweep.sqlite"))
    from services.db import get_db
    conn = get_db()
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS tenant_settings (tenant_id TEXT, key TEXT, value TEXT, updated_ts INTEGER, PRIMARY KEY(tenant_id,key))")
    c.execute("INSERT OR REPLACE INTO tenant_settings VALUES ('t-good', 'rental_pl_alert_pct', '-50', 0)")
    c.execute("INSERT OR REPLACE INTO tenant_settings VALUES ('t-good', 'mrr_api_key', 'k1', 0)")
    c.execute("INSERT OR REPLACE INTO tenant_settings VALUES ('t-no-key', 'rental_pl_alert_pct', '-50', 0)")
    c.execute("INSERT OR REPLACE INTO tenant_settings VALUES ('t-positive', 'rental_pl_alert_pct', '10', 0)")
    c.execute("INSERT OR REPLACE INTO tenant_settings VALUES ('t-positive', 'mrr_api_key', 'k2', 0)")
    c.execute("INSERT OR REPLACE INTO tenant_settings VALUES ('t-empty', 'rental_pl_alert_pct', '', 0)")
    c.execute("INSERT OR REPLACE INTO tenant_settings VALUES ('t-empty', 'mrr_api_key', 'k3', 0)")
    conn.commit()
    conn.close()

    tenants = rp.pl_alert_enabled_tenants()
    assert "t-good" in tenants
    assert "t-no-key" not in tenants
    assert "t-positive" not in tenants
    assert "t-empty" not in tenants


def test_enabled_tenants_includes_default_when_configured(tmp_path, monkeypatch):
    """The operator/global tenant is included when its GLOBAL setting is on."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "sweep2.sqlite"))
    monkeypatch.setenv("MRR_API_KEY", "env-key")
    # The real app creates the global `settings` table at init_db(); a fresh
    # test DB needs it before save_setting can persist.
    from services.db import get_db
    conn = get_db()
    conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT, updated_ts INTEGER)")
    conn.commit()
    conn.close()
    from services.settings import save_setting, invalidate_cache
    invalidate_cache()
    save_setting("rental_pl_alert_pct", "-75")
    invalidate_cache()
    tenants = rp.pl_alert_enabled_tenants()
    assert "" in tenants


def test_enabled_tenants_never_raises_on_missing_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "sweep3.sqlite"))
    monkeypatch.delenv("MRR_API_KEY", raising=False)
    monkeypatch.delenv("MRR_API_SECRET", raising=False)
    from services.settings import invalidate_cache
    invalidate_cache()  # drop any module-cache leak from earlier tests
    assert rp.pl_alert_enabled_tenants() == []


# ── sweep_rental_pl_alerts ──────────────────────────────────────────────────


def test_sweep_fetches_evaluates_ingests_and_returns_alerts(tmp_path, monkeypatch):
    """One pass: 1 MRR call → evaluate (returns 1 alert) + ingest so the
    local track record stays fresh. Returns the ALERTS (the caller dispatches)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "sweep4.sqlite"))
    calls = {"fetch": 0, "ingest": 0}
    listing = _FakeListing(rentals=[_mr_history_row()])
    alert = {"severity": "WARN", "category": "rental_pl",
             "message": "Rental #1 fechou com prejuízo",
             "rental_id": "1", "provider": "mrr"}

    monkeypatch.setattr(
        rp, "fetch_mrr_rentals",
        lambda rtype="renter", history=False, limit=25, tenant_id="": (
            calls.__setitem__("fetch", calls["fetch"] + 1) or listing))
    monkeypatch.setattr(
        rp, "ingest_rentals",
        lambda *a, **k: calls.__setitem__("ingest", calls["ingest"] + 1) or True)
    monkeypatch.setattr(
        rp, "evaluate_rental_pl_alerts",
        lambda history, contracts=None, tenant_id="", now=None: [alert])

    alerts = rp.sweep_rental_pl_alerts(tenant_id="t1")
    assert alerts == [alert]
    assert calls["fetch"] == 1  # exactly ONE provider call per pass
    assert calls["ingest"] == 1


def test_sweep_needs_auth_is_empty_not_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "sweep5.sqlite"))
    monkeypatch.setattr(
        rp, "fetch_mrr_rentals",
        lambda rtype="renter", history=False, limit=25, tenant_id="": {
            "success": False, "needs_auth": True, "rentals": [], "total": 0})
    assert rp.sweep_rental_pl_alerts(tenant_id="t1") == []


def test_sweep_provider_error_is_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "sweep6.sqlite"))
    monkeypatch.setattr(
        rp, "fetch_mrr_rentals",
        lambda rtype="renter", history=False, limit=25, tenant_id="": {
            "success": False, "needs_auth": False, "rentals": [],
            "total": 0, "error": "HTTP 503"})
    assert rp.sweep_rental_pl_alerts(tenant_id="t1") == []


# ── dispatch_rental_pl_alerts (shared with /api/rentals) ────────────────────


def test_dispatch_fires_webhook_and_push_per_tenant(monkeypatch):
    fired = {"webhook": [], "push": []}
    monkeypatch.setattr(
        _up, "_fire_webhook_async", lambda kw: fired["webhook"].append(kw))
    monkeypatch.setattr(
        _up, "_fire_push_async",
        lambda t, s, c, m: fired["push"].append((t, s, c, m)))
    import services.settings as _settings_mod
    monkeypatch.setattr(
        _settings_mod, "load_settings",
        lambda tenant_id="": {"webhook_url": "https://discord.com/api/webhooks/x",
                              "webhook_min_severity": "WARN"})

    _up.dispatch_rental_pl_alerts("t1", [{
        "severity": "WARN", "category": "rental_pl",
        "message": "Rental #9 ruim", "rental_id": "9", "provider": "mrr"}])
    assert len(fired["webhook"]) == 1
    assert fired["webhook"][0]["tenant_id"] == "t1"
    assert fired["webhook"][0]["category"] == "rental_pl"
    assert len(fired["push"]) == 1
    assert fired["push"][0] == ("t1", "WARN", "rental_pl", "Rental #9 ruim")


def test_dispatch_empty_alerts_is_noop(monkeypatch):
    fired = {"webhook": 0, "push": 0}
    monkeypatch.setattr(_up, "_fire_webhook_async", lambda kw: fired.__setitem__("webhook", 1))
    monkeypatch.setattr(_up, "_fire_push_async",
                        lambda *a: fired.__setitem__("push", 1))
    _up.dispatch_rental_pl_alerts("t1", [])
    assert fired == {"webhook": 0, "push": 0}


# ── _rentals_sweep_once ─────────────────────────────────────────────────────


def test_sweep_once_visits_and_dispatches_alerts(monkeypatch):
    """CRITICAL REGRESSION GUARD: the sweep pass must DISPATCH the alerts it
    evaluates — otherwise the dedup slot is claimed and the alert is swallowed
    forever (the exact bug the review caught)."""
    monkeypatch.setattr(_up, "_RENTAL_SWEEP_STAGGER", 0.0)
    visited = []
    dispatched = []
    alert = {"severity": "WARN", "category": "rental_pl",
             "message": "Rental ruim", "rental_id": "9", "provider": "mrr"}

    monkeypatch.setattr(
        rp, "pl_alert_enabled_tenants", lambda: ["t-a", "t-b"])
    monkeypatch.setattr(rp, "market_overpay_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "market_arb_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "reco_worse_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "auto_blacklist_candidate_tenants", lambda: [])
    monkeypatch.setattr(rp, "evaluate_auto_blacklist", lambda tenant_id="": [])
    monkeypatch.setattr(rp, "risk_alert_enabled_tenants", lambda: [])
    # ONE shared MRR fetch per enabled tenant (rate budget), then BOTH
    # families' evaluators consume that history — never one fetch per
    # alert family.
    monkeypatch.setattr(rp, "_sweep_fetch_history", lambda tenant_id="": [])
    monkeypatch.setattr(
        rp, "evaluate_rental_pl_alerts",
        lambda hist, contracts, tenant_id="": (visited.append(tenant_id) or ([alert] if tenant_id == "t-b" else [])))
    monkeypatch.setattr(
        _up, "dispatch_rental_pl_alerts",
        lambda t, alerts: dispatched.append((t, alerts)))

    n = _up._rentals_sweep_once()
    assert n == 2
    assert visited == ["t-a", "t-b"]
    # t-b's alert WAS dispatched (t-a had none).
    assert len(dispatched) == 1
    assert dispatched[0][0] == "t-b"
    assert dispatched[0][1] == [alert]


def test_sweep_once_is_staggered(monkeypatch):
    """Stagger sleep happens BETWEEN tenants (sleep count == tenants - 1)."""
    monkeypatch.setattr(_up, "_RENTAL_SWEEP_STAGGER", 0.01)
    sleeps = []
    monkeypatch.setattr(_up.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(
        rp, "pl_alert_enabled_tenants", lambda: ["a", "b", "c"])
    monkeypatch.setattr(rp, "market_overpay_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "market_arb_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "reco_worse_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "auto_blacklist_candidate_tenants", lambda: [])
    monkeypatch.setattr(rp, "evaluate_auto_blacklist", lambda tenant_id="": [])
    monkeypatch.setattr(rp, "risk_alert_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "_sweep_fetch_history", lambda tenant_id="": [])
    monkeypatch.setattr(rp, "evaluate_rental_pl_alerts",
                        lambda hist, contracts, tenant_id="": [])

    _up._rentals_sweep_once()
    assert len(sleeps) == 2  # 3 tenants → 2 gaps


def test_sweep_interval_env_wiring(monkeypatch):
    """RENTAL_SWEEP_INTERVAL env drives the cadence (0 disables)."""
    monkeypatch.setattr(_up, "_RENTAL_SWEEP_INTERVAL", 0)
    assert _up._RENTAL_SWEEP_INTERVAL == 0
    monkeypatch.setattr(_up, "_RENTAL_SWEEP_INTERVAL", 120)
    assert _up._RENTAL_SWEEP_INTERVAL == 120


def test_sweep_start_honors_disabled_env(monkeypatch):
    """RENTAL_SWEEP_INTERVAL=0 → start_rentals_sweep is a no-op."""
    monkeypatch.setattr(_up, "_RENTAL_SWEEP_INTERVAL", 0)
    monkeypatch.setattr(_up, "_rental_sweep_started", True)
    started = []
    monkeypatch.setattr(_up.threading.Thread, "start", lambda self: started.append(1))
    _up.start_rentals_sweep()
    assert started == []


# ── market-overpay family (price paid vs market at purchase) ───────────────

def test_market_overpay_enabled_tenants_requires_positive_threshold_and_mrr_key(tmp_path, monkeypatch):
    """Only tenants with rental_market_overpay_pct > 0 AND MRR credentials are
    returned (the sweep must not burn provider calls for opted-out accounts)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "sweep7.sqlite"))
    from services.db import get_db
    conn = get_db()
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS tenant_settings (tenant_id TEXT, key TEXT, value TEXT, updated_ts INTEGER, PRIMARY KEY(tenant_id,key))")
    c.execute("INSERT OR REPLACE INTO tenant_settings VALUES ('t-good', 'rental_market_overpay_pct', '100', 0)")
    c.execute("INSERT OR REPLACE INTO tenant_settings VALUES ('t-good', 'mrr_api_key', 'k1', 0)")
    c.execute("INSERT OR REPLACE INTO tenant_settings VALUES ('t-no-key', 'rental_market_overpay_pct', '100', 0)")
    c.execute("INSERT OR REPLACE INTO tenant_settings VALUES ('t-neg', 'rental_market_overpay_pct', '-50', 0)")
    c.execute("INSERT OR REPLACE INTO tenant_settings VALUES ('t-neg', 'mrr_api_key', 'k2', 0)")
    c.execute("INSERT OR REPLACE INTO tenant_settings VALUES ('t-empty', 'rental_market_overpay_pct', '', 0)")
    c.execute("INSERT OR REPLACE INTO tenant_settings VALUES ('t-empty', 'mrr_api_key', 'k3', 0)")
    conn.commit()
    conn.close()
    tenants = rp.market_overpay_enabled_tenants()
    assert "t-good" in tenants
    assert "t-no-key" not in tenants
    assert "t-neg" not in tenants
    assert "t-empty" not in tenants


def test_sweep_rental_market_alerts_fetches_evaluates_and_returns(tmp_path, monkeypatch):
    """sweep_rental_market_alerts: 1 MRR call → evaluate + ingest → alerts."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "sweep8.sqlite"))
    calls = {"fetch": 0}
    listing = _FakeListing(rentals=[_mr_history_row()])
    alert = {"severity": "WARN", "category": "rental_overpay",
             "message": "Rental #1 pagou 150% acima do mercado",
             "rental_id": "1", "provider": "mrr"}
    monkeypatch.setattr(
        rp, "fetch_mrr_rentals",
        lambda rtype="renter", history=False, limit=25, tenant_id="": (
            calls.__setitem__("fetch", calls["fetch"] + 1) or listing))
    monkeypatch.setattr(rp, "ingest_rentals", lambda *a, **k: True)
    monkeypatch.setattr(
        rp, "evaluate_market_overpay_alerts",
        lambda history, contracts=None, tenant_id="", now=None, extra=None: [alert])
    assert rp.sweep_rental_market_alerts(tenant_id="t1") == [alert]
    assert calls["fetch"] == 1


def test_dispatch_rental_market_alerts_fires_webhook_and_push(monkeypatch):
    fired = {"webhook": [], "push": []}
    monkeypatch.setattr(_up, "_fire_webhook_async",
                        lambda kw: fired["webhook"].append(kw))
    monkeypatch.setattr(_up, "_fire_push_async",
                        lambda t, s, c, m: fired["push"].append((t, s, c, m)))
    import services.settings as _settings_mod
    monkeypatch.setattr(
        _settings_mod, "load_settings",
        lambda tenant_id="": {"webhook_url": "https://discord.com/api/webhooks/x",
                              "webhook_min_severity": "WARN"})

    _up.dispatch_rental_market_alerts("t1", [{
        "severity": "CRIT", "category": "rental_overpay",
        "message": "Rental #9 pagou 300% acima do mercado",
        "rental_id": "9", "provider": "mrr"}])
    assert len(fired["webhook"]) == 1
    assert fired["webhook"][0]["tenant_id"] == "t1"
    assert fired["webhook"][0]["category"] == "rental_overpay"
    assert fired["push"][0] == ("t1", "CRIT", "rental_overpay",
                                 "Rental #9 pagou 300% acima do mercado")


def test_sweep_once_visits_and_dispatches_market_alerts(monkeypatch):
    """The market family is gated to ITS enabled set and dispatched by the
    sweep loop (never swallowed after the dedup slot is claimed)."""
    monkeypatch.setattr(_up, "_RENTAL_SWEEP_STAGGER", 0.0)
    dispatched = []
    fetches = []
    alert = {"severity": "WARN", "category": "rental_overpay",
             "message": "Overpay!", "rental_id": "9", "provider": "mrr"}
    monkeypatch.setattr(rp, "pl_alert_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "risk_alert_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "market_arb_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "reco_worse_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "auto_blacklist_candidate_tenants", lambda: [])
    monkeypatch.setattr(rp, "evaluate_auto_blacklist", lambda tenant_id="": [])
    monkeypatch.setattr(rp, "market_overpay_enabled_tenants", lambda: ["t-m"])
    monkeypatch.setattr(rp, "_sweep_fetch_history",
                        lambda tenant_id="": (fetches.append(tenant_id) or []))
    monkeypatch.setattr(rp, "evaluate_market_overpay_alerts",
                        lambda hist, contracts, tenant_id="": [alert])
    monkeypatch.setattr(_up, "dispatch_rental_market_alerts",
                        lambda t, alerts: dispatched.append((t, alerts)))
    n = _up._rentals_sweep_once()
    assert n == 1
    assert fetches == ["t-m"]  # exactly one shared MRR fetch
    assert dispatched == [("t-m", [alert])]


def test_sweep_once_dual_enabled_shares_one_fetch(monkeypatch):
    """A tenant with BOTH P/L and market-overpay enabled pays ONE MRR fetch
    per cycle (the shared _sweep_fetch_history contract) — never one per
    alert family (provider rate budget)."""
    monkeypatch.setattr(_up, "_RENTAL_SWEEP_STAGGER", 0.0)
    fetches = []
    pl_dispatched = []
    mkt_dispatched = []
    monkeypatch.setattr(rp, "pl_alert_enabled_tenants", lambda: ["t-dual"])
    monkeypatch.setattr(rp, "market_overpay_enabled_tenants", lambda: ["t-dual"])
    monkeypatch.setattr(rp, "market_arb_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "reco_worse_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "auto_blacklist_candidate_tenants", lambda: [])
    monkeypatch.setattr(rp, "evaluate_auto_blacklist", lambda tenant_id="": [])
    monkeypatch.setattr(rp, "risk_alert_enabled_tenants", lambda: [])
    monkeypatch.setattr(
        rp, "_sweep_fetch_history",
        lambda tenant_id="": (fetches.append(tenant_id) or [{"rental_id": "1"}]))
    monkeypatch.setattr(rp, "evaluate_rental_pl_alerts",
                        lambda hist, contracts, tenant_id="": [{"severity": "WARN"}])
    monkeypatch.setattr(rp, "evaluate_market_overpay_alerts",
                        lambda hist, contracts, tenant_id="": [{"severity": "WARN"}])
    monkeypatch.setattr(_up, "dispatch_rental_pl_alerts",
                        lambda t, a: pl_dispatched.append((t, a)))
    monkeypatch.setattr(_up, "dispatch_rental_market_alerts",
                        lambda t, a: mkt_dispatched.append((t, a)))
    n = _up._rentals_sweep_once()
    assert n == 1
    assert fetches == ["t-dual"]  # ONE fetch feeding BOTH families
    assert len(pl_dispatched) == 1
    assert len(mkt_dispatched) == 1


def test_sweep_once_visits_and_dispatches_arb_alerts(monkeypatch):
    """Arbitrage family: gated to ITS enabled set, evaluated LOCALLY (no
    _sweep_fetch_history call — zero provider cost), and dispatched by the
    sweep loop (never swallowed after the dedup slot is claimed)."""
    monkeypatch.setattr(_up, "_RENTAL_SWEEP_STAGGER", 0.0)
    dispatched = []
    fetched = []
    alert = {"severity": "GOLD", "category": "market_arb",
             "message": "ARBITRAGEM!", "rental_id": "", "provider": "mrr"}
    monkeypatch.setattr(rp, "pl_alert_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "market_overpay_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "market_arb_enabled_tenants", lambda: ["t-arb"])
    monkeypatch.setattr(rp, "reco_worse_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "auto_blacklist_candidate_tenants", lambda: [])
    monkeypatch.setattr(rp, "evaluate_auto_blacklist", lambda tenant_id="": [])
    monkeypatch.setattr(rp, "risk_alert_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "_sweep_fetch_history",
                        lambda tenant_id="": (fetched.append(tenant_id) or []))
    monkeypatch.setattr(rp, "evaluate_market_arb_alerts",
                        lambda tenant_id="", now=None: [alert])
    monkeypatch.setattr(_up, "dispatch_rental_arb_alerts",
                        lambda t, a: dispatched.append((t, a)))
    n = _up._rentals_sweep_once()
    assert n == 1
    assert fetched == []  # LOCAL family — must NOT hit the provider
    assert dispatched == [("t-arb", [alert])]


# ── reco-worse / risk / auto-blacklist families (Issue #135 coverage) ───────

def test_sweep_once_visits_and_dispatches_reco_worse_alerts(monkeypatch):
    """Accepted-recommendation 'worse' family: LOCAL evaluation (zero
    provider cost) and dispatched by the sweep loop."""
    monkeypatch.setattr(_up, "_RENTAL_SWEEP_STAGGER", 0.0)
    dispatched = []
    fetched = []
    alert = {"severity": "CRIT", "category": "reco_worse",
             "message": "Rig voltou a entregar mal", "rig_id": "r9"}
    monkeypatch.setattr(rp, "pl_alert_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "market_overpay_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "market_arb_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "reco_worse_enabled_tenants", lambda: ["t-reco"])
    monkeypatch.setattr(rp, "auto_blacklist_candidate_tenants", lambda: [])
    monkeypatch.setattr(rp, "evaluate_auto_blacklist", lambda tenant_id="": [])
    monkeypatch.setattr(rp, "risk_alert_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "_sweep_fetch_history",
                        lambda tenant_id="": (fetched.append(tenant_id) or []))
    monkeypatch.setattr(rp, "evaluate_reco_worse_alerts",
                        lambda tenant_id="", now=None: [alert])
    monkeypatch.setattr(_up, "dispatch_reco_worse_alerts",
                        lambda t, a: dispatched.append((t, a)))
    n = _up._rentals_sweep_once()
    assert n == 1
    assert fetched == []  # LOCAL family — no provider call
    assert dispatched == [("t-reco", [alert])]


def test_sweep_once_visits_and_dispatches_risk_alerts(monkeypatch):
    """Risk (worst-rig top-N) family: gated to its enabled set, LOCAL
    evaluation, dispatched by the sweep."""
    monkeypatch.setattr(_up, "_RENTAL_SWEEP_STAGGER", 0.0)
    dispatched = []
    alert = {"severity": "WARN", "category": "rental_risk",
             "message": "worst rigs", "rig_id": "r1"}
    monkeypatch.setattr(rp, "pl_alert_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "market_overpay_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "market_arb_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "reco_worse_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "auto_blacklist_candidate_tenants", lambda: [])
    monkeypatch.setattr(rp, "evaluate_auto_blacklist", lambda tenant_id="": [])
    monkeypatch.setattr(rp, "risk_alert_enabled_tenants", lambda: ["t-risk"])
    monkeypatch.setattr(rp, "_sweep_fetch_history", lambda tenant_id="": [])
    monkeypatch.setattr(rp, "sweep_risk_alerts",
                        lambda tenant_id="", now=None: [alert])
    monkeypatch.setattr(_up, "dispatch_tenant_risk_alerts",
                        lambda t, a: dispatched.append((t, a)))
    n = _up._rentals_sweep_once()
    assert n == 1
    assert dispatched == [("t-risk", [alert])]


def test_sweep_once_auto_blacklist_dispatches_exclude_alerts(monkeypatch):
    """CFO auto-exclusion family: DEFAULT protection (runs for any tenant
    with a local track record), rigs dispatched via
    dispatch_auto_exclude_alerts when the alert is opted-in."""
    monkeypatch.setattr(_up, "_RENTAL_SWEEP_STAGGER", 0.0)
    dispatched = []
    monkeypatch.setattr(rp, "pl_alert_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "market_overpay_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "market_arb_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "reco_worse_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "risk_alert_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "auto_blacklist_candidate_tenants",
                        lambda: ["t-auto"])
    monkeypatch.setattr(rp, "evaluate_auto_blacklist",
                        lambda tenant_id="": [{"rig_id": "r-auto", "name": "RigX"}])
    monkeypatch.setattr(_up, "dispatch_auto_exclude_alerts",
                        lambda t, rigs: (dispatched.append((t, rigs)) or 2))
    n = _up._rentals_sweep_once()
    assert n == 1
    assert len(dispatched) == 1
    assert dispatched[0][0] == "t-auto"


def test_sweep_once_tenant_exception_is_isolated(monkeypatch):
    """One tenant raising inside the loop must NOT stop the pass — the next
    tenant is still visited and counted."""
    monkeypatch.setattr(_up, "_RENTAL_SWEEP_STAGGER", 0.0)
    visited = []
    monkeypatch.setattr(rp, "pl_alert_enabled_tenants", lambda: ["t-bad", "t-ok"])
    monkeypatch.setattr(rp, "market_overpay_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "market_arb_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "reco_worse_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "auto_blacklist_candidate_tenants", lambda: [])
    monkeypatch.setattr(rp, "evaluate_auto_blacklist", lambda tenant_id="": [])
    monkeypatch.setattr(rp, "risk_alert_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "_sweep_fetch_history", lambda tenant_id="": [])

    def _explode(hist, contracts, tenant_id=""):
        visited.append(tenant_id)
        if tenant_id == "t-bad":
            raise RuntimeError("provider exploded")
        return []

    monkeypatch.setattr(rp, "evaluate_rental_pl_alerts", _explode)
    n = _up._rentals_sweep_once()
    # visited += 1 sits at the END of the loop try — the exploding tenant is
    # not counted, but the pass CONTINUED to t-ok (exception isolated).
    assert n == 1
    assert visited == ["t-bad", "t-ok"]


def test_sweep_once_top_level_exception_returns_zero(monkeypatch):
    """A failure in the family-import/gating phase returns 0 (never raises)."""
    monkeypatch.setattr(
        rp, "pl_alert_enabled_tenants",
        lambda: (_ for _ in ()).throw(RuntimeError("db gone")))
    assert _up._rentals_sweep_once() == 0


def test_sweep_loop_jitter_then_runs_and_breaks(monkeypatch):
    """_rentals_sweep_loop: boot jitter (5 + random*15s) first, then one pass
    per interval. We break the infinite loop by raising from time.sleep."""
    sleeps = []
    calls = {"pass": 0}
    monkeypatch.setattr(
        _up.time, "sleep",
        lambda s: sleeps.append(s) if len(sleeps) < 2 else (_ for _ in ()).throw(KeyboardInterrupt()))
    monkeypatch.setattr(_up, "_rentals_sweep_once",
                        lambda: calls.__setitem__("pass", calls["pass"] + 1))
    monkeypatch.setattr(_up, "_RENTAL_SWEEP_INTERVAL", 30)
    import random as _random
    monkeypatch.setattr(_random, "random", lambda: 0.5)
    try:
        _up._rentals_sweep_loop()
    except KeyboardInterrupt:
        pass
    # Sequence: jitter-sleep → pass → interval-sleep → pass → sleep raises
    assert len(sleeps) == 2  # boot jitter + interval sleep
    assert sleeps[0] == 5 + 0.5 * 15
    assert sleeps[1] == 30
    assert calls["pass"] == 2  # one pass per loop iteration before break
