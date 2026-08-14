"""Tests for the periodic AUTO-BLACKLIST sweep (Issue #90).

The auto-exclusion of under-delivering rigs (grade F, >=2 samples) used to
fire ONLY inside analyze_rig (the operator opening a rig's track record in
the panel). This family wires it into the UserPollingWorker's periodic sweep
so the exclusion happens WITHOUT the user opening the panel:

  - _should_auto_exclude — the SHARED decision (detail path + sweep, one
    rule, no drift): grade F + >=2 samples, not already excluded, and a
    restored rig is only re-excluded on NEW bad data after the restore.
  - auto_blacklist_candidate_tenants — tenants with a LOCAL renter track
    record (zero provider cost, default protection, no opt-in gate).
  - evaluate_auto_blacklist — one pass for a tenant: scans local history,
    auto-excludes the rigs that pass the rule, returns the NEW exclusions.
  - _rentals_sweep_once — visits the auto-blacklist family (mocked in the
    existing sweep tests for determinism).
"""

import datetime as _dt
import sys

import pytest

sys.path.insert(0, ".")

import services.rental_performance as rp  # noqa: E402
import services.user_polling as _up  # noqa: E402

# Frozen "now" — the restore window compares sample dates against the ts
# recorded at auto-exclusion (int(time.time())), so the test clock must be
# stable and AFTER the sample dates.
NOW = 1_800_000_000  # 2027-01-15


@pytest.fixture(autouse=True)
def _freeze_time(monkeypatch):
    monkeypatch.setattr(rp.time, "time", lambda: NOW)


def _dt_str(ts):
    """Unix ts → MRR-style start string (UTC)."""
    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC")


def _row(rental_id, rig_id, start, pct, bucket="renter"):
    """A rental_history row (mirrors the ingest output shape)."""
    return {
        "provider": "mrr", "bucket": bucket, "rental_id": rental_id,
        "rig_id": rig_id, "rig_name": f"Rig {rig_id}", "start": start,
        "end": None, "percent": pct, "avg_th": 100.0, "advertised_th": 100.0,
        "cost_sats_per_thh": 500.0, "length_hours": 1.0,
        "delivered_thh": 100.0, "paid_sats": 50000,
    }


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.sqlite"))


def test_should_auto_exclude_grade_f_with_two_samples(db):
    """Grade F + >=2 samples → excluded; good rig / single sample → not."""
    bad = [
        {"percent": 60.0, "start": "2026-07-20 10:00:00"},
        {"percent": 55.0, "start": "2026-07-21 10:00:00"},
    ]
    assert rp._should_auto_exclude("rig-f", bad, tenant_id="t1") is True
    # Only 1 sample → confidence too low.
    assert rp._should_auto_exclude("rig-f", bad[:1], tenant_id="t1") is False
    # Good delivery → never excluded.
    good = [{"percent": 96.0, "start": "2026-07-20 10:00:00"},
            {"percent": 97.0, "start": "2026-07-21 10:00:00"}]
    assert rp._should_auto_exclude("rig-good", good, tenant_id="t1") is False


def test_should_auto_exclude_respects_restore(db):
    """A restored rig is only re-excluded on NEW bad data after the restore."""
    # Samples BEFORE the frozen now → auto-exclusion fires at NOW.
    bad = [
        {"percent": 55.0, "start": _dt_str(NOW - 2 * 86400)},
        {"percent": 50.0, "start": _dt_str(NOW - 86400)},
    ]
    assert rp._should_auto_exclude("rig-r", bad, tenant_id="t1") is True
    rp.add_rig_to_auto_blacklist("rig-r", tenant_id="t1")
    assert rp.is_rig_auto_blacklisted("rig-r", tenant_id="t1")
    # Restore the rig → the decision flips off for the SAME streak.
    rp.remove_rig_from_blacklist("rig-r", tenant_id="t1")
    assert not rp.is_rig_auto_blacklisted("rig-r", tenant_id="t1")
    assert rp._should_auto_exclude("rig-r", bad, tenant_id="t1") is False
    # NEW bad rental AFTER the restore (sample AFTER the exclusion ts) → re-excluded.
    newer = bad + [{"percent": 52.0, "start": _dt_str(NOW + 86400)}]
    assert rp._should_auto_exclude("rig-r", newer, tenant_id="t1") is True


def test_should_auto_exclude_never_raises(db):
    assert rp._should_auto_exclude("rig-x", None, tenant_id="t1") is False
    assert rp._should_auto_exclude("", [{"percent": 50.0}], tenant_id="t1") is False


def test_auto_blacklist_candidate_tenants(db):
    """Tenants with LOCAL renter track record are candidates (no opt-in gate,
    zero provider cost); owner buckets and empty history never count."""
    rp.save_rental_history([
        _row("1", "rig-a", "2026-07-20 10:00:00", 55.0),
        _row("2", "rig-a", "2026-07-21 10:00:00", 52.0),
    ], tenant_id="t-a")
    rp.save_rental_history([
        _row("3", "rig-b", "2026-07-20 10:00:00", 58.0),
    ], tenant_id="t-b")
    # Owner-only rows (rented OUT) must NOT make the tenant a candidate.
    rp.save_rental_history([
        _row("4", "rig-o", "2026-07-20 10:00:00", 99.0, bucket="owner"),
    ], tenant_id="t-owner")
    cands = rp.auto_blacklist_candidate_tenants()
    assert "t-a" in cands and "t-b" in cands
    assert "t-owner" not in cands


def test_evaluate_auto_blacklist_excludes_and_isolates(db):
    """evaluate_auto_blacklist excludes the grade-F rigs of ONE tenant and
    never touches another tenant's list."""
    rp.save_rental_history([
        _row("1", "rig-f", "2026-07-20 10:00:00", 55.0),
        _row("2", "rig-f", "2026-07-21 10:00:00", 52.0),
        _row("3", "rig-g", "2026-07-20 10:00:00", 96.0),
        _row("4", "rig-g", "2026-07-21 10:00:00", 97.0),
    ], tenant_id="t-a")
    rp.save_rental_history([
        _row("5", "rig-other", "2026-07-20 10:00:00", 40.0),
        _row("6", "rig-other", "2026-07-21 10:00:00", 42.0),
    ], tenant_id="t-b")

    excluded = rp.evaluate_auto_blacklist(tenant_id="t-a")
    assert excluded == ["rig-f"]
    assert rp.is_rig_auto_blacklisted("rig-f", tenant_id="t-a")
    assert not rp.is_rig_auto_blacklisted("rig-g", tenant_id="t-a")
    # Tenant isolation: t-b's bad rig is untouched by t-a's pass.
    assert not rp.is_rig_auto_blacklisted("rig-other", tenant_id="t-b")
    assert rp.get_auto_blacklist(tenant_id="t-b") == []

    # Idempotent: a second pass finds nothing new.
    assert rp.evaluate_auto_blacklist(tenant_id="t-a") == []


def test_evaluate_auto_blacklist_never_raises(db):
    assert rp.evaluate_auto_blacklist(tenant_id="t-none") == []


def test_sweep_once_visits_auto_blacklist_family(monkeypatch):
    """The periodic sweep visits the auto-blacklist family (default
    protection) and logs the exclusions — no dispatch needed (the ledger is
    recorded inside add_rig_to_auto_blacklist)."""
    monkeypatch.setattr(_up, "_RENTAL_SWEEP_STAGGER", 0.0)
    visited = []

    monkeypatch.setattr(rp, "pl_alert_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "market_overpay_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "market_arb_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "reco_worse_enabled_tenants", lambda: [])
    monkeypatch.setattr(rp, "risk_alert_enabled_tenants", lambda: [])
    monkeypatch.setattr(
        rp, "auto_blacklist_candidate_tenants", lambda: ["t-a", "t-b"])
    monkeypatch.setattr(
        rp, "evaluate_auto_blacklist",
        lambda tenant_id="": (visited.append(tenant_id) or
                              (["rig-x"] if tenant_id == "t-b" else [])))

    n = _up._rentals_sweep_once()
    assert n == 2
    assert visited == ["t-a", "t-b"]
