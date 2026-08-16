"""Tests for the per-tenant AUTO-EXCLUSION ALERT (sweep fires webhook/push).

The periodic rentals sweep auto-excludes rigs that keep under-delivering
(DEFAULT protection — runs for every tenant with a local track record, no
opt-in). This alert family is the OPT-IN notification layer: when the sweep
bars a rig, tenants with `rental_auto_exclude_alert=1` get webhook + push
with the SAME readable cause the panel history shows (Issue #100).

Covers:
  - build_auto_exclude_alert(): gated on the setting (default off), reuses
    the auto-exclusion history cause, None for unknown rigs, never raises.
  - dispatch_auto_exclude_alerts(): fires webhook + push once per exclusion
    EVENT (dedup key includes the exclusion ts, so a restored rig that gets
    re-excluded later re-alerts); respects the setting; returns the count.
  - _rentals_sweep_once(): real end-to-end — exclusion + alert without
    anyone opening the panel.
"""
import datetime as _dt
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.user_polling as _up  # noqa: E402
from services import rental_performance as rp  # noqa: E402
from services.settings import save_setting  # noqa: E402

NOW = 1_800_000_000  # fixed reference "now"


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Per-test scratch DB (get_db reads DB_PATH at call time). The real app
    creates the settings tables via init_db — tests ensure them the same way
    so default-tenant save_setting() writes land (no 'no such table')."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.sqlite"))
    rp._ensure_rig_settings_tables()


@pytest.fixture
def clock(monkeypatch):
    """Mutable fake clock — rp.time.time returns the current fake 'now'."""
    state = {"now": NOW}
    monkeypatch.setattr(rp.time, "time", lambda: state["now"])
    return state


@pytest.fixture(autouse=True)
def _fresh_settings_cache():
    """The settings caches are module-level and survive between tests in the
    same process. There are TWO: `_tenant_settings_cache` (tenant_settings
    table) AND `_settings_cache` (global settings table — the DEFAULT
    tenant). Both must be invalidated around every test or the alert gating
    leaks across tests (a '1' saved by one test reads as '1' in the next)."""
    from services import settings as _settings_mod
    _settings_mod._settings_cache = None
    _settings_mod._tenant_settings_cache.clear()
    yield
    _settings_mod._settings_cache = None
    _settings_mod._tenant_settings_cache.clear()


def _dt_str(ts):
    """Unix ts → MRR-style start string (UTC)."""
    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC")


def _hr(rental_id, rig_id, start, pct):
    """A rental_history row shaped like _rental_to_history_row output."""
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


def _capture_fires(monkeypatch):
    """Mock the daemon fire fns so tests assert deterministically."""
    fired = {"webhook": [], "push": []}
    monkeypatch.setattr(
        _up, "_fire_webhook_async", lambda kw: fired["webhook"].append(kw))
    monkeypatch.setattr(
        _up, "_fire_push_async",
        lambda t, s, c, m: fired["push"].append((t, s, c, m)))
    return fired


# ── build_auto_exclude_alert ──────────────────────────────────────────────

def test_build_alert_disabled_by_default(db, clock):
    """No setting → None even with a fresh exclusion (opt-in, default off)."""
    _seed([_hr("r1", "rig-b", _dt_str(NOW - 86400), 60.0),
           _hr("r2", "rig-b", _dt_str(NOW - 2 * 86400), 55.0)])
    rp.add_rig_to_auto_blacklist("rig-b")
    assert rp.build_auto_exclude_alert("rig-b") is None


def test_build_alert_enabled_with_cause(db, clock):
    """Setting '1' → WARN alert reusing the history cause (zero drift)."""
    save_setting("rental_auto_exclude_alert", "1")
    _seed([_hr("r1", "rig-b", _dt_str(NOW - 86400), 60.0),
           _hr("r2", "rig-b", _dt_str(NOW - 2 * 86400), 55.0)])
    rp.add_rig_to_auto_blacklist("rig-b")
    a = rp.build_auto_exclude_alert("rig-b")
    assert a is not None
    assert a["severity"] == "WARN"
    assert a["category"] == "rental_auto_exclude"
    assert "auto-excluído por sub-entrega" in a["message"]
    assert "grade F" in a["message"]
    assert "entrega 57.5%" in a["message"]  # median of [60, 55]
    assert "régua: floor F, mín 2" in a["message"]
    assert a["ts"] == NOW


def test_build_alert_unknown_rig(db, clock):
    """Enabled but the rig never excluded → None (no fabricated alert)."""
    save_setting("rental_auto_exclude_alert", "1")
    assert rp.build_auto_exclude_alert("ghost-rig") is None


# ── dispatch_auto_exclude_alerts ──────────────────────────────────────────

def test_dispatch_fires_once_when_enabled(db, clock, monkeypatch):
    """One exclusion → one webhook + one push with the alert payload."""
    fired = _capture_fires(monkeypatch)
    save_setting("rental_auto_exclude_alert", "1")
    save_setting("webhook_url", "https://discord.com/api/webhooks/x")
    _seed([_hr("r1", "rig-b", _dt_str(NOW - 86400), 60.0),
           _hr("r2", "rig-b", _dt_str(NOW - 2 * 86400), 55.0)])
    rp.add_rig_to_auto_blacklist("rig-b")

    n = _up.dispatch_auto_exclude_alerts("", ["rig-b"])
    assert n == 1
    assert len(fired["webhook"]) == 1
    assert fired["webhook"][0]["category"] == "rental_auto_exclude"
    assert "auto-excluído por sub-entrega" in fired["webhook"][0]["message"]
    assert len(fired["push"]) == 1
    assert fired["push"][0] == ("", "WARN", "rental_auto_exclude",
                                fired["webhook"][0]["message"])


def test_dispatch_dedup_same_event(db, clock, monkeypatch):
    """The same exclusion event never double-fires (atomic claim)."""
    fired = _capture_fires(monkeypatch)
    save_setting("rental_auto_exclude_alert", "1")
    save_setting("webhook_url", "https://discord.com/api/webhooks/x")
    _seed([_hr("r1", "rig-b", _dt_str(NOW - 86400), 60.0),
           _hr("r2", "rig-b", _dt_str(NOW - 2 * 86400), 55.0)])
    rp.add_rig_to_auto_blacklist("rig-b")

    assert _up.dispatch_auto_exclude_alerts("", ["rig-b"]) == 1
    assert _up.dispatch_auto_exclude_alerts("", ["rig-b"]) == 0
    assert len(fired["webhook"]) == 1
    assert len(fired["push"]) == 1


def test_dispatch_respects_setting_off(db, clock, monkeypatch):
    """Not opted in → 0 alerts, nothing fired (exclusion still happened)."""
    fired = _capture_fires(monkeypatch)
    _seed([_hr("r1", "rig-b", _dt_str(NOW - 86400), 60.0),
           _hr("r2", "rig-b", _dt_str(NOW - 2 * 86400), 55.0)])
    rp.add_rig_to_auto_blacklist("rig-b")
    assert rp.get_auto_blacklist() == ["rig-b"]
    assert _up.dispatch_auto_exclude_alerts("", ["rig-b"]) == 0
    assert fired == {"webhook": [], "push": []}


def test_restore_then_re_exclude_re_alerts(db, clock, monkeypatch):
    """A RESTORED rig re-excluded by a NEW bad rental is a NEW event — the
    dedup key carries the exclusion ts, so the operator gets re-alerted."""
    fired = _capture_fires(monkeypatch)
    save_setting("rental_auto_exclude_alert", "1")
    _seed([_hr("r1", "rig-b", _dt_str(NOW - 2 * 86400), 60.0),
           _hr("r2", "rig-b", _dt_str(NOW - 86400), 55.0)])
    rp.add_rig_to_auto_blacklist("rig-b")
    assert _up.dispatch_auto_exclude_alerts("", ["rig-b"]) == 1

    # Operator restores the rig (clears BOTH blacklists, marks 'restored').
    assert rp.remove_rig_from_blacklist("rig-b") is True

    # A NEW bad rental arrives AFTER the previous exclusion → re-excluded.
    clock["now"] = NOW + 86400
    _seed([_hr("r3", "rig-b", _dt_str(NOW + 86400), 50.0)])
    assert rp.evaluate_auto_blacklist() == ["rig-b"]
    # New event (new ts in the dedup key) → re-alerts.
    assert _up.dispatch_auto_exclude_alerts("", ["rig-b"]) == 1
    assert len(fired["push"]) == 2


def test_auto_exclude_alert_counters_by_path(db, clock, monkeypatch):
    """dispatch bumps per-path counters — sweep (default) vs panel — and
    auto_exclude_alert_counters() returns {sweep, panel, total}. The dedup
    claim is shared across paths (same event called from panel after sweep
    does NOT double-count)."""
    fired = _capture_fires(monkeypatch)
    save_setting("rental_auto_exclude_alert", "1")
    _seed([_hr("r1", "rig-b", _dt_str(NOW - 2 * 86400), 60.0),
           _hr("r2", "rig-b", _dt_str(NOW - 86400), 55.0)])
    rp.add_rig_to_auto_blacklist("rig-b")
    # Hermetic start: module counters are process-wide.
    _up._AUTO_EXCLUDE_ALERTS_BY_PATH.clear()
    _up._AUTO_EXCLUDE_ALERTS_BY_PATH.update({"sweep": 0, "panel": 0})

    # Sweep path (default) fires once; panel path on the SAME event → dedup.
    assert _up.dispatch_auto_exclude_alerts("", ["rig-b"]) == 1
    assert _up.dispatch_auto_exclude_alerts("", ["rig-b"], path="panel") == 0
    assert _up.auto_exclude_alert_counters() == {"sweep": 1, "panel": 0,
                                                 "total": 1}

    # Restore + re-exclude → NEW event, dispatched via the PANEL path.
    assert rp.remove_rig_from_blacklist("rig-b") is True
    clock["now"] = NOW + 86400
    _seed([_hr("r3", "rig-b", _dt_str(NOW + 86400), 50.0)])
    assert rp.evaluate_auto_blacklist() == ["rig-b"]
    assert _up.dispatch_auto_exclude_alerts("", ["rig-b"], path="panel") == 1
    assert _up.auto_exclude_alert_counters() == {"sweep": 1, "panel": 1,
                                                 "total": 2}


def test_auto_exclude_alert_counters_ignore_noop(db, clock, monkeypatch):
    """No alerts dispatched (setting off / dedup) → counters untouched;
    snapshot is always well-formed with a total."""
    _capture_fires(monkeypatch)
    _up._AUTO_EXCLUDE_ALERTS_BY_PATH.clear()
    _up._AUTO_EXCLUDE_ALERTS_BY_PATH.update({"sweep": 0, "panel": 0})
    _seed([_hr("r1", "rig-b", _dt_str(NOW - 2 * 86400), 60.0),
           _hr("r2", "rig-b", _dt_str(NOW - 86400), 55.0)])
    rp.add_rig_to_auto_blacklist("rig-b")
    # Opt-in off → 0 dispatched, 0 bumped.
    assert _up.dispatch_auto_exclude_alerts("", ["rig-b"]) == 0
    assert _up.dispatch_auto_exclude_alerts("", [], path="panel") == 0
    assert _up.auto_exclude_alert_counters() == {"sweep": 0, "panel": 0,
                                                 "total": 0}


# ── _rentals_sweep_once (real end-to-end) ─────────────────────────────────

def test_sweep_dispatches_auto_exclude_alert(db, clock, monkeypatch):
    """The sweep excludes AND alerts without anyone opening the panel."""
    monkeypatch.setattr(_up, "_RENTAL_SWEEP_STAGGER", 0.0)
    fired = _capture_fires(monkeypatch)
    tid = "t-sweep"
    save_setting("rental_auto_exclude_alert", "1", tenant_id=tid)
    save_setting("webhook_url", "https://discord.com/api/webhooks/x",
                 tenant_id=tid)
    _seed([_hr("r1", "rig-b", _dt_str(NOW - 2 * 86400), 60.0),
           _hr("r2", "rig-b", _dt_str(NOW - 86400), 55.0)], tenant_id=tid)

    n = _up._rentals_sweep_once()
    assert n >= 1
    # The rig was auto-excluded by the sweep...
    assert rp.get_auto_blacklist(tenant_id=tid) == ["rig-b"]
    # ...and the tenant got the opt-in alert (webhook + push).
    assert len(fired["push"]) == 1
    assert fired["push"][0][0] == tid
    assert fired["push"][0][1] == "WARN"
    assert fired["push"][0][2] == "rental_auto_exclude"
    assert "auto-excluído por sub-entrega" in fired["push"][0][3]
    assert len(fired["webhook"]) == 1
    assert fired["webhook"][0]["tenant_id"] == tid


# ── Panel path (analyze_rig → /api/rentals/detail) — Issue #108 ────────────

def _seed_bad_rig(rig_id="rig-b", tenant_id=""):
    """Two under-delivering samples → grade F, auto-excludable (default rule)."""
    _seed([_hr("r1", rig_id, _dt_str(NOW - 2 * 86400), 60.0),
           _hr("r2", rig_id, _dt_str(NOW - 86400), 55.0)], tenant_id=tenant_id)


def test_analyze_rig_marks_auto_excluded_now_first_call_only(db, clock):
    """The detail panel performs the SHARED auto-exclusion and reports
    auto_excluded_now=True ONLY on the call that excluded it — re-opening
    the detail of an already-excluded rig never re-triggers."""
    _seed_bad_rig()
    first = rp.analyze_rig("rig-b")
    assert first["auto_blacklisted"] is True
    assert first["auto_excluded_now"] is True
    assert rp.get_auto_blacklist() == ["rig-b"]

    second = rp.analyze_rig("rig-b")
    assert second["auto_blacklisted"] is True
    assert second["auto_excluded_now"] is False


def test_analyze_rig_does_not_flag_good_rig(db, clock):
    """No exclusion → auto_excluded_now False (never fabricates an event)."""
    _seed([_hr("r1", "rig-good", _dt_str(NOW - 86400), 96.0)])
    res = rp.analyze_rig("rig-good")
    assert res["auto_blacklisted"] is False
    assert res["auto_excluded_now"] is False


def test_panel_and_sweep_dispatch_share_event_claim(db, clock, monkeypatch):
    """The SAME event excluded via the panel ('default' tenant from
    require_tenant) must dedup against the sweep's canonical '' claim — one
    alert total, whichever path fires first."""
    fired = _capture_fires(monkeypatch)
    save_setting("rental_auto_exclude_alert", "1")
    save_setting("webhook_url", "https://discord.com/api/webhooks/x")
    _seed_bad_rig()
    # Panel path: the exclusion happens in analyze_rig, then the detail
    # route dispatches with tenant_id='default'.
    assert rp.analyze_rig("rig-b")["auto_excluded_now"] is True
    assert _up.dispatch_auto_exclude_alerts("default", ["rig-b"]) == 1
    assert len(fired["push"]) == 1
    # Sweep path later: same rig already excluded → evaluate returns [] and
    # even a direct dispatch with '' (canonical) claims the SAME row.
    assert rp.evaluate_auto_blacklist() == []
    assert _up.dispatch_auto_exclude_alerts("", ["rig-b"]) == 0
    assert len(fired["push"]) == 1


def test_panel_and_sweep_dedup_inverse_order(db, clock, monkeypatch):
    """Order does not matter: sweep claims first (''), panel ('default')
    afterwards still dedups to ONE alert."""
    fired = _capture_fires(monkeypatch)
    save_setting("rental_auto_exclude_alert", "1")
    _seed_bad_rig()
    rp.add_rig_to_auto_blacklist("rig-b")
    assert _up.dispatch_auto_exclude_alerts("", ["rig-b"]) == 1
    assert _up.dispatch_auto_exclude_alerts("default", ["rig-b"]) == 0
    assert len(fired["push"]) == 1


def test_panel_path_realert_after_restore(db, clock, monkeypatch):
    """Full PANEL flow: analyze_rig excludes → restore → NEW bad sample →
    analyze_rig re-excludes → the NEW event re-alerts (the canonical claim
    is keyed by the new ts, so restore+re-exclusion via the panel fires
    again — never blocked by the first event's claim)."""
    fired = _capture_fires(monkeypatch)
    save_setting("rental_auto_exclude_alert", "1")
    _seed_bad_rig()
    # Event 1: excluded via the panel path.
    assert rp.analyze_rig("rig-b")["auto_excluded_now"] is True
    assert _up.dispatch_auto_exclude_alerts("default", ["rig-b"]) == 1
    assert len(fired["push"]) == 1
    # Operator restores the rig.
    assert rp.remove_rig_from_blacklist("rig-b") is True
    # NEW bad sample AFTER the restore → re-excludable (new ts → new event).
    clock["now"] = NOW + 5 * 86400
    _seed([_hr("r3", "rig-b", _dt_str(NOW + 4 * 86400), 50.0)])
    assert rp.analyze_rig("rig-b")["auto_excluded_now"] is True
    assert _up.dispatch_auto_exclude_alerts("default", ["rig-b"]) == 1
    assert len(fired["push"]) == 2


# ── Route wiring: /api/rentals/detail dispatches on auto_excluded_now ─────

import app as _app_module  # noqa: E402


@pytest.fixture
def rclient():
    _app_module.app.config["TESTING"] = True
    _app_module._RENTALS_CACHE.clear()
    with _app_module.app.test_client() as c:
        yield c
        _app_module._RENTALS_CACHE.clear()


def _mock_detail_route(monkeypatch, auto_excluded_now=False,
                        exclusions=None, thresholds=None):
    """Mock the MRR detail route's provider/analytics fns + analyze_rig."""
    dispatched = []
    monkeypatch.setattr(
        _app_module._rental_perf, "fetch_mrr_rental_detail",
        lambda rid, tenant_id="": {
            "success": True,
            "detail": {"rig": {"id": "R1", "name": "Rig R1"}},
            "graph": {}, "log": {}})
    monkeypatch.setattr(_app_module._rental_perf, "compute_mrr_perf", lambda raw: {})
    monkeypatch.setattr(_app_module._rental_perf, "attach_pl", lambda *a, **k: {})
    monkeypatch.setattr(_app_module._rental_perf,
                        "_resolve_network_hashrate_for_rental", lambda *a, **k: None)
    monkeypatch.setattr(
        _app_module._rental_perf, "analyze_rig",
        lambda *a, **k: {"history": [], "auto_excluded_now": auto_excluded_now})
    monkeypatch.setattr(_app_module._rental_perf, "fetch_market_reference", lambda: {})
    monkeypatch.setattr(
        _app_module._rental_perf, "_auto_exclude_thresholds",
        lambda tenant_id="": (thresholds if thresholds is not None
                               else {"grade": "F", "min_samples": 2}))
    monkeypatch.setattr(
        _app_module._rental_perf, "auto_exclusion_history",
        lambda tenant_id="": {"count": len(exclusions or []),
                               "exclusions": exclusions or []})
    monkeypatch.setattr(
        _up, "dispatch_auto_exclude_alerts",
        lambda t, r, path="sweep": (dispatched.append((t, list(r), path)) or 1))
    return dispatched


def test_detail_route_returns_auto_exclude_badge_fields(rclient, monkeypatch):
    """When THIS call performs the exclusion, the response carries the
    badge payload: auto_excluded_now, alert dispatch count, the vigente
    rule AND the exact ledger entry the AUTO-EXCLUSÕES section renders
    (parity so the pre-added card matches a refresh byte-for-byte)."""
    entry = {"rig_id": "R1", "name": "Rig R1", "ts": 1000, "grade": "F",
             "delivery_pct": 57.5, "samples": 2, "min_samples": 2,
             "grade_floor": "F", "cause": "sub-entrega (grade F)"}
    _mock_detail_route(monkeypatch, auto_excluded_now=True, exclusions=[entry])
    resp = rclient.get("/api/rentals/detail?provider=mrr&id=5657736")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["auto_excluded_now"] is True
    assert body["auto_exclude_alert_dispatched"] == 1
    assert body["auto_exclude_rule"] == {"grade_floor": "F", "min_samples": 2}
    assert body["auto_exclude_entry"] == entry


def test_detail_route_badge_fields_empty_when_no_new_exclusion(rclient, monkeypatch):
    """Plain detail open (no exclusion performed) → falsy badge payload,
    so the frontend banner never shows on a normal lookup."""
    _mock_detail_route(monkeypatch, auto_excluded_now=False)
    resp = rclient.get("/api/rentals/detail?provider=mrr&id=5657736")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["auto_excluded_now"] is False
    assert body["auto_exclude_alert_dispatched"] == 0
    assert body["auto_exclude_rule"] == {}
    assert body["auto_exclude_entry"] == {}


def test_detail_route_skips_dispatch_when_no_new_exclusion(rclient, monkeypatch):
    """Rig already excluded (or no exclusion) → no alert dispatched."""
    dispatched = _mock_detail_route(monkeypatch, auto_excluded_now=False)
    resp = rclient.get("/api/rentals/detail?provider=mrr&id=5657736")
    assert resp.status_code == 200
    assert dispatched == []
