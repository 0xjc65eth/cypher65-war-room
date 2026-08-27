"""Issue #123 — Coverage 65→80: financial/ops gap tests.

Maps to the coverage report (coverage report -m) gaps:
  - services/rental_performance.py:
      _ensure_market_history_index / _historical_market_sats_per_thh /
      _recent_market_sats_per_thh   (the spread/loss market reference)
      _auto_exclusion_cause / _auto_exclude_thresholds / _auto_exclusion_map
      _should_auto_exclude (restore path) / build_auto_exclude_alert
      compute_difficulty_forecast / series_bucket_rentals
      compute_worst_rigs / _risk_alert_settings / evaluate_risk_alerts
      risk_alert_enabled_tenants / sweep_risk_alerts
      detect_tenant_worse_concentration
  - services/payments.py: create_checkout env paths.
  - services/auto_pilot.py: collectors fail-closed.

Hermetic: every test uses a scratch DB (DB_PATH) and never hits the network.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import rental_performance as rp  # noqa: E402
import services.payments as payments  # noqa: E402
import services.auto_pilot as ap  # noqa: E402


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Per-test scratch DB (get_db reads DB_PATH at call time)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.sqlite"))
    # Module-level caches must not leak between tests.
    rp._market_price_cache.clear()
    rp._market_index_ensured = False


@pytest.fixture(autouse=True)
def _fresh_settings_cache():
    from services import settings as _settings_mod
    _settings_mod.invalidate_cache()
    yield
    _settings_mod.invalidate_cache()


def _seed_market_row(ts, price_per_th_day, algorithm="sha256", provider="mrr"):
    """Insert one hashrate_market_history row (schema mirrors init_db)."""
    conn = rp.get_db()
    c = conn.cursor()
    c.execute(
        "CREATE TABLE IF NOT EXISTS hashrate_market_history ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL,"
        " provider TEXT NOT NULL, hashrate REAL, price_per_th_day REAL,"
        " duration_days REAL, fee_pct REAL, algorithm TEXT, score REAL,"
        " raw_data TEXT)")
    c.execute(
        "INSERT INTO hashrate_market_history"
        " (ts, provider, hashrate, price_per_th_day, duration_days, fee_pct,"
        "  algorithm, score, raw_data)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (ts, provider, None, price_per_th_day, 1.0, 0.0, algorithm, 1.0, "{}"))
    conn.commit()
    conn.close()


def _seed_history_row(tenant_id, rental_id, rig_id, start, pct, **kw):
    """One rental_history row (mirrors ingest output shape)."""
    row = {
        "provider": "mrr", "bucket": "renter", "rental_id": rental_id,
        "rig_id": rig_id, "rig_name": "Rig " + rig_id, "start": start,
        "end": None, "percent": pct, "avg_th": 100.0, "advertised_th": 100.0,
        "cost_sats_per_thh": 500.0, "length_hours": 1.0,
        "delivered_thh": 100.0, "paid_sats": 50000,
    }
    row.update(kw)
    assert rp.save_rental_history([row], tenant_id=tenant_id) is True


def _dt_str(days_ago: int) -> str:
    """UTC date string 'days_ago' days before now."""
    import datetime as _dt
    ts = int(rp.time.time()) - days_ago * 86400
    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC")


# Frozen "now" for timestamp-sensitive tests (auto-exclusion ts / verdict
# windows) — same convention as test_rental_auto_blacklist_sweep.
_FROZEN_NOW = 1_800_000_000  # 2027-01-15


def _ts_str(ts: int) -> str:
    """UTC date string from an ABSOLUTE unix ts."""
    import datetime as _dt
    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC")


def _freeze_now(monkeypatch):
    """Freeze rp.time.time so auto-exclusion/verdict ts are deterministic.

    NOTE: rental_performance does ``import time`` at module level, so this
    patches the STDLIB ``time`` module itself (process-wide for the test
    duration). Same convention as test_rental_auto_blacklist_sweep.py;
    monkeypatch restores it and pytest runs serially, so it is safe."""
    monkeypatch.setattr(rp.time, "time", lambda: _FROZEN_NOW)


# ── Market price at purchase (real SQL — the spread/loss reference) ───────

def test_historical_market_price_lookup_and_conversion(db):
    """Cheapest sha256 price within ±3d, converted BTC/TH/day → sats/TH·h."""
    import time as _t
    now = int(_t.time())
    _seed_market_row(now - 86400, 0.0001)        # 1 day ago — in window
    _seed_market_row(now - 86400, 0.0002, provider="other")  # more expensive
    _seed_market_row(now - 86400, 0.00005, algorithm="scrypt")  # non-sha256 → ignored

    p = rp._historical_market_sats_per_thh(now)
    # 0.0001 BTC/TH/day * 1e8 / 24 = 416.67 sats/TH·h
    assert p == pytest.approx(416.67, abs=0.01)
    # Cache hit returns the same value without a second query.
    assert rp._historical_market_sats_per_thh(now) == p


def test_historical_market_price_outside_window_none(db):
    """Nothing within ±3 days → None (never fabricates a price)."""
    import time as _t
    now = int(_t.time())
    _seed_market_row(now - 10 * 86400, 0.0001)
    assert rp._historical_market_sats_per_thh(now) is None


def test_historical_market_price_none_ts(db):
    """ts=None → None without touching the DB."""
    assert rp._historical_market_sats_per_thh(None) is None


def test_recent_market_price_window(db):
    """Cheapest quote inside the last window_h hours."""
    import time as _t
    now = int(_t.time())
    _seed_market_row(now - 3600, 0.0001)
    _seed_market_row(now - 3600, 0.0004)
    p = rp._recent_market_sats_per_thh(now=now, window_h=12.0)
    assert p == pytest.approx(416.67, abs=0.01)


def test_recent_market_price_falls_back_to_historical(db):
    """No recent rows → the ±3d historical lookup covers it."""
    import time as _t
    now = int(_t.time())
    _seed_market_row(now - 2 * 86400, 0.0002)  # 2d ago — beyond window_h, inside ±3d
    p = rp._recent_market_sats_per_thh(now=now, window_h=12.0)
    assert p == pytest.approx(833.33, abs=0.01)


# ── Auto-exclusion rule edges ─────────────────────────────────────────────

def test_auto_exclusion_cause_full_bits(db):
    """Cause joins grade + delivery + samples + the vigente rule."""
    cause = rp._auto_exclusion_cause(
        {"grade": "F", "delivery_pct": 55.0, "samples": 3},
        {"grade": "F", "min_samples": 2})
    assert "grade F" in cause
    assert "entrega 55.0%" in cause
    assert "3 amostras" in cause
    assert "floor F" in cause and "mín 2" in cause


def test_auto_exclusion_cause_minimal_bits(db):
    """No grade/delivery/samples → the honest 'sub-entrega' fallback."""
    cause = rp._auto_exclusion_cause({}, {"grade": "F", "min_samples": 2})
    assert cause.startswith("sub-entrega")
    assert "floor F" in cause


def test_auto_exclusion_cause_bad_types_never_raise(db):
    """Garbage values are skipped per-field, never raised."""
    cause = rp._auto_exclusion_cause(
        {"grade": None, "delivery_pct": "abc", "samples": "x"},
        {"grade": "F", "min_samples": 2})
    assert "sub-entrega" in cause


def test_auto_exclude_thresholds_defaults(db):
    """Unset settings → legacy defaults (F + 2 samples)."""
    th = rp._auto_exclude_thresholds(tenant_id="t-unset")
    assert th["grade"] == "F"
    assert th["min_samples"] == 2
    assert th["grade_rank"] == 1


def test_auto_exclude_thresholds_custom(db):
    """Configured grade C + min 3 → rank 3 + 3 samples."""
    from services.settings import save_setting
    save_setting(rp.AUTO_EXCLUDE_GRADE_KEY, "C", tenant_id="t-cfg")
    save_setting(rp.AUTO_EXCLUDE_MIN_SAMPLES_KEY, "3", tenant_id="t-cfg")
    th = rp._auto_exclude_thresholds(tenant_id="t-cfg")
    assert th["grade"] == "C"
    assert th["grade_rank"] == 3
    assert th["min_samples"] == 3


def test_auto_exclude_thresholds_invalid_falls_back(db):
    """Garbage numbers/grade → silent defaults."""
    from services.settings import save_setting
    save_setting(rp.AUTO_EXCLUDE_GRADE_KEY, "ZZ", tenant_id="t-bad")
    save_setting(rp.AUTO_EXCLUDE_MIN_SAMPLES_KEY, "0", tenant_id="t-bad")
    th = rp._auto_exclude_thresholds(tenant_id="t-bad")
    assert th["grade"] == "F"
    assert th["min_samples"] == 2


def test_should_auto_exclude_restored_needs_new_data(db, monkeypatch):
    """A restored rig is only re-excluded when a NEW bad sample arrived
    AFTER the previous auto-exclusion (the restore must not be undone by
    the same streak)."""
    _freeze_now(monkeypatch)
    # Bad history → auto-exclude records WHEN it happened (ts = _FROZEN_NOW).
    _seed_history_row("", "r1", "rig-r", _ts_str(_FROZEN_NOW - 10 * 86400), 55.0)
    _seed_history_row("", "r2", "rig-r", _ts_str(_FROZEN_NOW - 9 * 86400), 60.0)
    history = rp.fetch_rig_performance_history("rig-r", tenant_id="")
    assert rp._should_auto_exclude("rig-r", history, tenant_id="") is True
    assert rp.add_rig_to_auto_blacklist("rig-r") is True

    # RESTORE (remove from both lists) — the ts map survives, so the same
    # streak must NOT re-exclude, but NEW bad data after the exclusion ts may.
    assert rp.remove_rig_from_blacklist("rig-r") is True

    # Restore → same streak (samples all BEFORE the exclusion) must NOT
    # re-exclude. Build history with only pre-restore samples.
    pre = [
        {"percent": 55.0, "start": _ts_str(_FROZEN_NOW - 10 * 86400)},
        {"percent": 60.0, "start": _ts_str(_FROZEN_NOW - 9 * 86400)},
    ]
    assert rp._should_auto_exclude("rig-r", pre, tenant_id="") is False

    # A NEW bad sample AFTER the exclusion ts → re-excludes.
    post = pre + [{"percent": 50.0, "start": _ts_str(_FROZEN_NOW + 86400)}]
    assert rp._should_auto_exclude("rig-r", post, tenant_id="") is True


def test_auto_exclusion_map_newest_wins_and_skips_manual(db):
    """Map only keeps source='auto' entries, newest per rig."""
    _seed_history_row("", "r1", "rig-a", _dt_str(10), 55.0)
    _seed_history_row("", "r2", "rig-a", _dt_str(9), 60.0)
    # Manual blacklist → NOT part of the auto-exclusion map.
    assert rp.add_rig_to_blacklist("rig-manual") is True
    assert rp.add_rig_to_auto_blacklist("rig-a") is True
    m = rp._auto_exclusion_map(tenant_id="")
    assert "rig-a" in m
    assert "rig-manual" not in m
    assert m["rig-a"]["grade_floor"] == "F"
    assert m["rig-a"]["cause"] != ""


def test_build_auto_exclude_alert_optin_and_message(db):
    """Opt-in on → alert with cause; off → None; no ledger → None."""
    from services.settings import save_setting
    _seed_history_row("", "r1", "rig-a", _dt_str(10), 55.0)
    _seed_history_row("", "r2", "rig-a", _dt_str(9), 60.0)
    assert rp.add_rig_to_auto_blacklist("rig-a") is True

    # Not opted in → None.
    assert rp.build_auto_exclude_alert("rig-a", tenant_id="") is None

    # Opted in → WARN alert with the exclusion cause.
    save_setting(rp.AUTO_EXCLUDE_ALERT_SETTING, "1", tenant_id="")
    alert = rp.build_auto_exclude_alert("rig-a", tenant_id="")
    assert alert is not None
    assert alert["severity"] == "WARN"
    assert alert["category"] == "rental_auto_exclude"
    assert "auto-excluído" in alert["message"]
    assert "grade F" in alert["message"]

    # Opted in but rig never excluded → None.
    assert rp.build_auto_exclude_alert("rig-never", tenant_id="") is None


# ── Difficulty forecast ────────────────────────────────────────────────────

def test_difficulty_forecast_available(db, monkeypatch):
    """With height + difficulty + block cadence → a real projection."""
    import services.state as _state
    conn = rp.get_db()
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS snapshots ("
              " id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL,"
              " network_height INTEGER)")
    c.executemany(
        "INSERT INTO snapshots (ts, network_height) VALUES (?,?)",
        [(1000, 100), (1600, 101), (2200, 102)])  # 600s/block
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        _state, "latest_snapshot",
        {"network": {"difficulty": 1.0e12, "height": 850000}})
    out = rp.compute_difficulty_forecast()
    assert out.get("available") is True
    assert out["avg_block_time_s"] == pytest.approx(600.0, abs=0.01)
    assert out["blocks_remaining"] == 2016 - (850000 % 2016)
    assert out["hours_to_adjustment"] > 0
    # 600s/block == target → flat.
    assert out["direction"] == "flat"
    assert out["projected_change_pct"] == pytest.approx(0.0, abs=0.01)


def test_difficulty_forecast_unavailable_without_height(db, monkeypatch):
    """No height/difficulty → available False (never fabricates)."""
    import services.state as _state
    monkeypatch.setattr(_state, "latest_snapshot", {"network": {}})
    assert rp.compute_difficulty_forecast() == {"available": False}


def test_difficulty_forecast_unavailable_without_cadence(db, monkeypatch):
    """Height known but no snapshots cadence → available False."""
    import services.state as _state
    monkeypatch.setattr(
        _state, "latest_snapshot",
        {"network": {"difficulty": 1.0e12, "height": 850000}})
    assert rp.compute_difficulty_forecast() == {"available": False}


# ── Portfolio series drill-down ────────────────────────────────────────────

def test_series_bucket_rentals_week_and_month(db):
    """Drill-down rows match the bucket label (ISO week / calendar month)."""
    import datetime as _dt
    _seed_history_row("", "r1", "rig-a", "2026-07-01 12:00:00 UTC", 100.0)

    dt = _dt.datetime(2026, 7, 1, tzinfo=_dt.timezone.utc)
    week = rp._series_bucket_key(dt, "week")
    month = rp._series_bucket_key(dt, "month")
    rows_w = rp.series_bucket_rentals(tenant_id="", bucket="week", label=week)
    rows_m = rp.series_bucket_rentals(tenant_id="", bucket="month", label=month)
    assert len(rows_w) == 1
    assert len(rows_m) == 1
    assert rows_w[0]["rental_id"] == "r1"
    assert rows_w[0]["provider"] == "mrr"
    assert rows_w[0]["rig_id"] == "rig-a"
    # Other labels → empty (no fabricated rows).
    assert rp.series_bucket_rentals(tenant_id="", bucket="week",
                                    label="2026-W99") == []


# ── Worst rigs + risk alerts ──────────────────────────────────────────────

def test_compute_worst_rigs_ranks_bad_deliveries(db):
    """Local history → danger-ranked worst rigs (≥2 samples)."""
    _seed_history_row("", "h1", "rig-bad", _dt_str(10), 45.0)
    _seed_history_row("", "h2", "rig-bad", _dt_str(9), 50.0)
    _seed_history_row("", "h3", "rig-good", _dt_str(10), 98.0)
    _seed_history_row("", "h4", "rig-good", _dt_str(9), 97.0)

    out = rp.compute_worst_rigs(tenant_id="", limit=8)
    assert out["count"] >= 2
    assert out["min_samples"] == 2
    worst = out["worst"]
    assert worst and worst[0]["rig_id"] == "rig-bad"
    assert worst[0]["danger_score"] > 50.0


def test_risk_alert_settings_defaults_and_clamps(db, monkeypatch):
    """Unset → defaults; garbage → clamped fallbacks; enabled variants."""
    cfg = rp._risk_alert_settings(tenant_id="t-unset")
    assert cfg == {"enabled": False, "danger": 50.0, "top_n": 5, "conc_pct": 55.0}

    monkeypatch.setattr(
        rp, "load_settings",
        lambda tenant_id="": {
            rp.RENTAL_RISK_ALERTS_SETTING: "1",
            rp.RENTAL_RISK_DANGER_SETTING: "abc",
            rp.RENTAL_RISK_TOP_N_SETTING: "200",
        })
    cfg = rp._risk_alert_settings(tenant_id="t-cfg")
    assert cfg["enabled"] is True
    assert cfg["danger"] == 50.0        # invalid → default
    assert cfg["top_n"] == 20           # clamped max


def test_risk_alert_enabled_tenants(db):
    """Opt-in rows in tenant_settings + the default tenant → listed once."""
    # save_setting rejects non-whitelisted keys — insert tenant rows directly
    # (mirrors what the settings route does for internal alert keys).
    conn = rp.get_db()
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS tenant_settings ("
              " tenant_id TEXT, key TEXT, value TEXT, updated_ts INTEGER,"
              " PRIMARY KEY(tenant_id, key))")
    c.executemany(
        "INSERT INTO tenant_settings(tenant_id,key,value,updated_ts) "
        "VALUES(?,?,?,?)",
        [(tid, rp.RENTAL_RISK_ALERTS_SETTING, v, 1)
         for tid, v in (("t1", "1"), ("t2", "0"))])
    conn.commit()
    conn.close()
    tenants = rp.risk_alert_enabled_tenants()
    assert "t1" in tenants
    assert "t2" not in tenants


def test_evaluate_risk_alerts_worst_rig_and_concentration(db, monkeypatch):
    """Enabled + worst-rig danger + concentration crossing → alerts."""
    monkeypatch.setattr(
        rp, "load_settings",
        lambda tenant_id="": {rp.RENTAL_RISK_ALERTS_SETTING: "1",
                              rp.RENTAL_RISK_DANGER_SETTING: "50"})

    out = rp.evaluate_risk_alerts(
        tenant_id="",
        worst_rigs={"worst": [{
            "rig_id": "rig-x", "name": "X", "danger_score": 80.0,
            "ewma_delivery_pct": 40.0, "fail_rate_pct": 55.0}]},
        concentration={"available": True,
                       "top_provider": {"provider": "mrr", "share_pct": 70.0,
                                        "label": "MRR"},
                       "hhi": 6000.0})
    cats = [a["category"] for a in out]
    assert "rental_risk_rig" in cats
    assert "rental_risk_concentration" in cats


def test_sweep_risk_alerts_disabled_returns_empty(db):
    """Sweep pass with alerts disabled → [] (never raises)."""
    assert rp.sweep_risk_alerts(tenant_id="t-off") == []


# ── Admin audit pass (cross-tenant) ───────────────────────────────────────

def test_admin_audit_loads_default_and_named_tenants(db):
    """_load_all_accepted_recos tags default + tenant_settings entries."""
    from services.settings import save_setting
    import json
    import time as _t
    now = int(_t.time())
    conn = rp.get_db()
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS settings ("
              " key TEXT PRIMARY KEY, value TEXT, updated_ts INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS tenant_settings ("
              " tenant_id TEXT, key TEXT, value TEXT, updated_ts INTEGER,"
              " PRIMARY KEY(tenant_id, key))")
    conn.commit()
    conn.close()
    _seed_history_row("", "h1", "rig-d", "2026-07-01 12:00:00 UTC", 90.0)
    _seed_history_row("t1", "h2", "rig-t", "2026-07-01 12:00:00 UTC", 90.0)
    assert rp.add_rig_to_blacklist("rig-d", tenant_id="") is True
    assert rp.add_rig_to_blacklist("rig-t", tenant_id="t1") is True

    all_entries = rp._load_all_accepted_recos()
    by_tid = {e.get("tenant_id"): e for e in all_entries}
    assert "default" in by_tid and by_tid["default"]["rig_id"] == "rig-d"
    assert "t1" in by_tid and by_tid["t1"]["rig_id"] == "rig-t"

    audit = rp.compute_admin_accepted_recos()
    assert audit["count"] == 2
    assert audit["by_tenant"][0]["tenant_id"] in ("default", "t1")


def test_detect_tenant_worse_concentration(db, monkeypatch):
    """A tenant whose accepted decisions mostly come back WORSE → flagged."""
    _freeze_now(monkeypatch)
    # 3 decisions accepted (before ≈ 90%) then re-rented much worse AFTER
    # the acceptance ts → verdict 'worse' for all three.
    for i, rid in enumerate(["rig-w1", "rig-w2", "rig-w3"]):
        _seed_history_row("t-w", f"b{i}", rid,
                          _ts_str(_FROZEN_NOW - 30 * 86400), 90.0)
        assert rp.add_rig_to_blacklist(rid, tenant_id="t-w") is True
        _seed_history_row("t-w", f"a{i}", rid,
                          _ts_str(_FROZEN_NOW + 2 * 86400), 45.0)  # after → worse

    out = rp.detect_tenant_worse_concentration()
    assert out["count"] == 1
    t = out["tenants"][0]
    assert t["tenant_id"] == "t-w"
    assert t["worse"] == 3
    assert t["ratio_pct"] == 100.0
    assert t["severity"] == "CRIT"


# ── Payments: checkout env paths ──────────────────────────────────────────

def test_create_checkout_missing_env_returns_none(db, monkeypatch):
    monkeypatch.delenv("LEMON_SQUEEZY_API_KEY", raising=False)
    monkeypatch.delenv("LEMON_SQUEEZY_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("LEMON_SQUEEZY_STORE_ID", raising=False)
    monkeypatch.delenv("LEMON_SQUEEZY_VARIANT_ID", raising=False)
    assert payments.create_checkout() is None


def test_create_checkout_full_legacy_env_remains_disabled(db, monkeypatch):
    monkeypatch.setenv("LEMON_SQUEEZY_API_KEY", "k")
    monkeypatch.setenv("LEMON_SQUEEZY_WEBHOOK_SECRET", "whsec")
    monkeypatch.setenv("LEMON_SQUEEZY_STORE_ID", "s")
    monkeypatch.setenv("LEMON_SQUEEZY_VARIANT_ID", "42")

    def _unexpected_request(*args, **kwargs):
        raise AssertionError("disabled checkout must not contact provider")

    monkeypatch.setattr(payments.requests, "post", _unexpected_request)
    url = payments.create_checkout(plan="pro", email="a@b.co")
    assert url is None


def test_disabled_checkout_returns_before_legacy_network_call(db, monkeypatch):
    monkeypatch.setenv("LEMON_SQUEEZY_API_KEY", "k")
    monkeypatch.setenv("LEMON_SQUEEZY_WEBHOOK_SECRET", "whsec")
    monkeypatch.setenv("LEMON_SQUEEZY_STORE_ID", "s")
    monkeypatch.setenv("LEMON_SQUEEZY_VARIANT_ID", "42")

    def _boom(*args, **kwargs):
        raise AssertionError("disabled checkout must not reach the network")

    monkeypatch.setattr(payments.requests, "post", _boom)
    assert payments.create_checkout() is None


# ── Auto-Pilot collectors fail-closed ─────────────────────────────────────

def test_collect_fleet_registry_none_returns_empty(db, monkeypatch):
    import axe_fleet.routes as _ar
    monkeypatch.setattr(_ar, "_registry", None)
    assert ap._collect_fleet(tenant_id="t1") == []


def test_collect_peak_7d_empty_db_returns_zero(db):
    assert ap._collect_peak_7d(tenant_id="") == 0.0


def test_collect_worst_rigs_and_blacklist_fail_closed(db, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(rp, "compute_worst_rigs", _boom)
    assert ap._collect_worst_rigs(tenant_id="") == []
    monkeypatch.setattr(rp, "get_rig_blacklist", _boom)
    assert ap._collect_blacklisted(tenant_id="") == []
