"""Tests for the accepted-recommendation 'worse' alert family.

When an accepted recommendation (a blacklisted rig) ends with verdict
'worse' — the rig kept under-delivering AFTER the exclusion — the tenant
gets a proactive webhook/push, not only a panel badge.

Covers:
  - Fires for verdict 'worse' (with before/after references), gated by the
    rental_reco_worse_alert setting (default off).
  - NEVER fires for revoked decisions (restored rigs).
  - Dedup: one alert per rig EVER (persisted, race-safe claim).
  - Tenant isolation (dedup + ledger per tenant).
  - reco_worse_enabled_tenants(): setting-gated, default + named.
  - _rentals_sweep_once() visits + dispatches reco-worse alerts.
  - Panel payload still carries accepted_recos (route path unchanged).
"""
import datetime as _dt
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import rental_performance as rp  # noqa: E402

NOW = 1_800_000_000  # fixed "now"


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Per-test scratch DB (get_db reads DB_PATH at call time)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.sqlite"))


@pytest.fixture(autouse=True)
def _freeze_time(monkeypatch):
    """Deterministic 'now' — ledger ts/dedup ts come from rp.time.time.
    Also resets the module-level settings cache after each test so a
    previous test's save_setting ('1') never leaks into the next test's
    fresh DB (the cache is module-global)."""
    monkeypatch.setattr(rp.time, "time", lambda: NOW)
    yield
    from services.settings import invalidate_cache
    invalidate_cache()


@pytest.fixture
def enabled(monkeypatch):
    """Enable the alert via the DEFAULT tenant's settings table."""
    rp._ensure_rig_settings_tables()
    from services.settings import invalidate_cache, save_setting
    invalidate_cache()
    assert save_setting(rp.RENTAL_RECO_WORSE_SETTING, "1") is True
    invalidate_cache()


def _dt_str(ts):
    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC")


def _hr(rental_id, rig_id, start, pct):
    return {
        "provider": "mrr", "bucket": "renter", "rental_id": rental_id,
        "rig_id": rig_id, "rig_name": "rig-" + rig_id,
        "start": start, "end": None, "percent": pct,
        "avg_th": 100.0, "advertised_th": 100.0,
        "cost_sats_per_thh": None, "length_hours": 24.0,
        "delivered_thh": 2400.0, "paid_sats": None,
        "network_hashrate_hs": None,
    }


def _seed(rows, tenant_id=""):
    assert rp.save_rental_history(rows, tenant_id=tenant_id) is True


def _accept_worse_rig(rig_id, before_pct, after_pct):
    """Blacklist a rig (accepted), then add a WORSE delivery after — the
    classic 'worse' scenario."""
    _seed([_hr("b1", rig_id, _dt_str(NOW - 20 * 86400), before_pct),
           _hr("b2", rig_id, _dt_str(NOW - 10 * 86400), before_pct)])
    assert rp.add_rig_to_blacklist(rig_id) is True
    _seed([_hr("a1", rig_id, _dt_str(NOW + 5 * 86400), after_pct)])


# ── Core behavior ───────────────────────────────────────────────────────────

def test_worse_verdict_fires_alert(db, enabled):
    """A worse outcome (delivery dropped ≥5pp after the blacklist) fires ONE
    WARN alert with the rental_reco_worse category + the before→after delta."""
    _accept_worse_rig("rig-a", 80.0, 60.0)  # before median 80 → after 60
    alerts = rp.evaluate_reco_worse_alerts()
    assert len(alerts) == 1
    a = alerts[0]
    assert a["severity"] == "WARN"
    assert a["category"] == "rental_reco_worse"
    assert a["rig_id"] == "rig-a"
    assert "PIOROU" in a["message"]
    assert "80%" in a["message"] and "60%" in a["message"]


def test_worse_dedup_once_per_rig(db, enabled):
    """The SAME rig never alerts again (persisted dedup, like P/L)."""
    _accept_worse_rig("rig-b", 80.0, 60.0)
    assert len(rp.evaluate_reco_worse_alerts()) == 1
    assert rp.evaluate_reco_worse_alerts() == []


def test_improved_or_avoided_never_fires(db, enabled):
    """Improved / avoided / no_before outcomes never fire this alert."""
    # Improved: delivery went UP after the blacklist.
    _accept_worse_rig("rig-c", 60.0, 90.0)
    # Avoided: no new rentals after the decision.
    _seed([_hr("d1", "rig-d", _dt_str(NOW - 10 * 86400), 70.0)])
    rp.add_rig_to_blacklist("rig-d")
    assert rp.evaluate_reco_worse_alerts() == []


def test_revoked_never_fires(db, enabled):
    """A RESTORED (revoked) rig must NOT alert — it was reversed, not worse."""
    _accept_worse_rig("rig-e", 80.0, 60.0)
    assert rp.remove_rig_from_blacklist("rig-e") is True
    # Ledger entry now restored → verdict 'revoked' → no alert.
    assert rp.evaluate_reco_worse_alerts() == []


def test_disabled_by_default(db):
    """Setting off (default '0') → no alerts even with a worse outcome."""
    _accept_worse_rig("rig-f", 80.0, 60.0)
    assert rp.evaluate_reco_worse_alerts() == []


def test_tenant_isolation(db, enabled):
    """Dedup is per-tenant: each tenant's own ledger alerts independently."""
    _accept_worse_rig("rig-g", 80.0, 60.0)                      # default
    _seed([_hr("h1", "rig-h", _dt_str(NOW - 10 * 86400), 70.0)],
          tenant_id="tN")
    assert rp.add_rig_to_blacklist("rig-h", tenant_id="tN") is True
    _seed([_hr("h2", "rig-h", _dt_str(NOW + 5 * 86400), 50.0)],
          tenant_id="tN")
    # Named tenant needs its OWN setting enabled.
    from services.settings import invalidate_cache, save_setting
    assert save_setting(rp.RENTAL_RECO_WORSE_SETTING, "1", tenant_id="tN") is True
    invalidate_cache()

    assert len(rp.evaluate_reco_worse_alerts()) == 1       # default rig-g
    assert len(rp.evaluate_reco_worse_alerts(tenant_id="tN")) == 1  # rig-h
    # Default tenant again → still deduped.
    assert rp.evaluate_reco_worse_alerts() == []


# ── Enabled-tenants scan ────────────────────────────────────────────────────

def test_enabled_tenants_setting_gated(db, enabled):
    """Default tenant is swept when its global setting is '1'."""
    assert "" in rp.reco_worse_enabled_tenants()


def test_enabled_tenants_off_by_default(db):
    """No tenant swept until the setting is '1'."""
    assert rp.reco_worse_enabled_tenants() == []


def test_enabled_tenants_named_tenant(db):
    rp._ensure_rig_settings_tables()
    from services.settings import invalidate_cache, save_setting
    assert save_setting(rp.RENTAL_RECO_WORSE_SETTING, "1", tenant_id="t9") is True
    invalidate_cache()
    assert "t9" in rp.reco_worse_enabled_tenants()


# ── Sweep integration ───────────────────────────────────────────────────────

def test_sweep_once_dispatches_reco_worse(monkeypatch):
    """_rentals_sweep_once must DISPATCH reco-worse alerts it evaluates (the
    same regression the P/L sweep guarded against)."""
    import services.user_polling as _up
    monkeypatch.setattr(_up, "_RENTAL_SWEEP_STAGGER", 0.0)
    visited = []
    dispatched = []
    alert = {"severity": "WARN", "category": "rental_reco_worse",
             "message": "Recomendação aceita PIOROU", "rig_id": "9"}

    monkeypatch.setattr(rp, "pl_alert_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "market_overpay_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "market_arb_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "risk_alert_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "reco_worse_enabled_tenants", lambda: ["t-a"])
    monkeypatch.setattr(rp, "auto_blacklist_candidate_tenants", lambda: [])
    monkeypatch.setattr(rp, "evaluate_auto_blacklist", lambda tenant_id="": [])
    monkeypatch.setattr(
        rp, "evaluate_reco_worse_alerts",
        lambda tenant_id="": (visited.append(tenant_id) or [alert]))
    monkeypatch.setattr(
        _up, "dispatch_reco_worse_alerts",
        lambda t, alerts: dispatched.append((t, alerts)))

    n = _up._rentals_sweep_once()
    assert n == 1
    assert visited == ["t-a"]
    assert len(dispatched) == 1
    assert dispatched[0][0] == "t-a"
    assert dispatched[0][1] == [alert]


def test_dispatch_reco_worse_fires_webhook_and_push(monkeypatch):
    """dispatch_reco_worse_alerts fires webhook + push per tenant (shared
    family dispatcher), no-op on empty."""
    import services.user_polling as _up
    fired = []
    monkeypatch.setattr(_up, "_dispatch_tenant_alert_family",
                        lambda t, alerts: fired.append((t, alerts)))
    _up.dispatch_reco_worse_alerts("t-x", [])
    assert fired == []
    alert = {"severity": "WARN", "category": "rental_reco_worse", "message": "m"}
    _up.dispatch_reco_worse_alerts("t-x", [alert])
    assert len(fired) == 1 and fired[0][0] == "t-x"
