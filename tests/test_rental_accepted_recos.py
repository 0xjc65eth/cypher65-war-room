"""Tests for the accepted-recommendation ledger in the RENTALS panel.

Covers:
  - Recording: manual blacklist + auto exclusion both persist an entry with
    the pilot's delivery snapshot (median %, samples, grade, name).
  - Dedup: newest entry per rig (re-blacklisting never duplicates).
  - Outcome: compute_accepted_recos_summary() verdicts — avoided (no new
    rentals after the decision), improved, worse, same, no_before.
  - Tenant isolation: default vs named tenants never share the ledger.
  - /api/rentals payload carries accepted_recos (tenant-scoped, empty shape).
"""
import datetime as _dt
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import rental_performance as rp  # noqa: E402

NOW = 1_800_000_000  # fixed "now" — deterministic before/after windows


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Per-test scratch DB (get_db reads DB_PATH at call time)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.sqlite"))


@pytest.fixture(autouse=True)
def _freeze_time(monkeypatch):
    """Deterministic 'now' — the accepted-reco ts comes from rp.time.time."""
    monkeypatch.setattr(rp.time, "time", lambda: NOW)


def _dt_str(ts):
    """Unix ts → MRR-style start string (UTC)."""
    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC")


def _hr(rental_id, rig_id, start, pct, cost=None):
    """A rental_history row shaped like _rental_to_history_row output."""
    return {
        "provider": "mrr", "bucket": "renter", "rental_id": rental_id,
        "rig_id": rig_id, "rig_name": "rig-" + rig_id,
        "start": start, "end": None, "percent": pct,
        "avg_th": 100.0, "advertised_th": 100.0,
        "cost_sats_per_thh": cost, "length_hours": 24.0,
        "delivered_thh": 2400.0, "paid_sats": None,
        "network_hashrate_hs": None,
    }


def _seed(rows, tenant_id=""):
    assert rp.save_rental_history(rows, tenant_id=tenant_id) is True


# ── Recording ──────────────────────────────────────────────────────────────

def test_manual_blacklist_records_accepted_reco(db):
    _seed([_hr("r1", "rig-a", _dt_str(NOW - 20 * 86400), 72.0),
           _hr("r2", "rig-a", _dt_str(NOW - 10 * 86400), 78.0)])
    assert rp.add_rig_to_blacklist("rig-a") is True
    recos = rp.get_accepted_recos()
    assert len(recos) == 1
    e = recos[0]
    assert e["rig_id"] == "rig-a"
    assert e["source"] == "manual"
    assert e["ts"] == NOW
    assert e["delivery_pct"] == 75.0       # median of [72, 78]
    assert e["samples"] == 2
    assert e["grade"] in ("D", "F")
    assert e["name"] == "rig-rig-a"


def test_auto_blacklist_records_accepted_reco(db):
    _seed([_hr("r1", "rig-b", _dt_str(NOW - 86400), 60.0)])
    assert rp.add_rig_to_auto_blacklist("rig-b") is True
    recos = rp.get_accepted_recos()
    assert len(recos) == 1
    assert recos[0]["rig_id"] == "rig-b"
    assert recos[0]["source"] == "auto"


def test_accepted_dedup_keeps_newest_per_rig(db):
    _seed([_hr("r1", "rig-c", _dt_str(NOW - 86400), 50.0)])
    rp.add_rig_to_blacklist("rig-c")
    rp.add_rig_to_blacklist("rig-c")       # same rig again → still one entry
    assert len(rp.get_accepted_recos()) == 1


def test_accepted_cross_source_dedup(db):
    """Manual then auto on the same rig → single entry (newest source wins)."""
    _seed([_hr("r1", "rig-c2", _dt_str(NOW - 86400), 50.0)])
    rp.add_rig_to_blacklist("rig-c2")
    rp.add_rig_to_auto_blacklist("rig-c2")
    recos = rp.get_accepted_recos()
    assert len(recos) == 1
    assert recos[0]["source"] == "auto"


def test_pilot_flagged_true_for_grade_f(db):
    """Grade-F rig at acceptance → the pilot HAD flagged it (avoid)."""
    _seed([_hr("r1", "rig-pf", _dt_str(NOW - 86400), 60.0)])
    rp.add_rig_to_blacklist("rig-pf")
    assert rp.get_accepted_recos()[0]["pilot_flagged"] is True


def test_pilot_flagged_false_for_good_rig(db):
    """A deliberately-blacklisted RELIABLE rig (grade A) was NOT a pilot
    suggestion — the ledger says so honestly."""
    _seed([_hr(f"g{i}", "rig-good", _dt_str(NOW - (i + 1) * 86400), 98.5)
           for i in range(5)])
    rp.add_rig_to_blacklist("rig-good")
    e = rp.get_accepted_recos()[0]
    assert e["grade"] == "A"
    assert e["pilot_flagged"] is False


def test_accepted_empty_without_history(db):
    assert rp.get_accepted_recos() == []
    assert rp.compute_accepted_recos_summary() == {"count": 0, "accepted": []}


# ── Outcome verdicts ───────────────────────────────────────────────────────

def test_summary_avoided_when_no_new_rentals(db):
    _seed([_hr("r1", "rig-d", _dt_str(NOW - 86400), 70.0)])
    rp.add_rig_to_blacklist("rig-d")
    s = rp.compute_accepted_recos_summary()
    assert s["count"] == 1
    e = s["accepted"][0]
    assert e["verdict"] == "avoided"
    assert e["delivery_after_pct"] is None
    assert e["cost_after_sats_per_thh"] is None


def test_summary_improved_and_worse(db):
    # rig-e: before ~74 (bad), after ~95 → improved
    _seed([_hr("e1", "rig-e", _dt_str(NOW - 2 * 86400), 72.0),
           _hr("e2", "rig-e", _dt_str(NOW - 86400), 76.0)])
    rp.add_rig_to_blacklist("rig-e")
    _seed([_hr("e3", "rig-e", _dt_str(NOW + 3600), 94.0),
           _hr("e4", "rig-e", _dt_str(NOW + 7200), 96.0)])
    # rig-f: before ~95, after ~80 → worse
    _seed([_hr("f1", "rig-f", _dt_str(NOW - 2 * 86400), 94.0),
           _hr("f2", "rig-f", _dt_str(NOW - 86400), 96.0)])
    rp.add_rig_to_blacklist("rig-f")
    _seed([_hr("f3", "rig-f", _dt_str(NOW + 3600), 78.0),
           _hr("f4", "rig-f", _dt_str(NOW + 7200), 82.0)])
    s = rp.compute_accepted_recos_summary()
    by_rig = {x["rig_id"]: x for x in s["accepted"]}
    assert by_rig["rig-e"]["verdict"] == "improved"
    assert by_rig["rig-e"]["delivery_after_pct"] == 95.0
    assert by_rig["rig-f"]["verdict"] == "worse"
    assert by_rig["rig-f"]["delivery_after_pct"] == 80.0


def test_summary_same_within_5pp(db):
    _seed([_hr("g1", "rig-g", _dt_str(NOW - 86400), 90.0)])
    rp.add_rig_to_blacklist("rig-g")
    _seed([_hr("g2", "rig-g", _dt_str(NOW + 3600), 92.0)])
    s = rp.compute_accepted_recos_summary()
    assert s["accepted"][0]["verdict"] == "same"


def test_summary_no_before_reference(db):
    # Ledger entry without a local delivery reference (rig never ingested
    # into history before acceptance) → no_before, not a crash.
    rp.add_rig_to_blacklist("rig-h")
    s = rp.compute_accepted_recos_summary()
    assert s["accepted"][0]["verdict"] == "no_before"
    assert s["accepted"][0]["delivery_pct"] is None


def test_accepted_tenant_isolation(db):
    _seed([_hr("t1", "rig-t", _dt_str(NOW - 86400), 60.0)], tenant_id="tenant-a")
    rp.add_rig_to_blacklist("rig-t", tenant_id="tenant-a")
    assert len(rp.get_accepted_recos(tenant_id="tenant-a")) == 1
    assert rp.get_accepted_recos(tenant_id="tenant-b") == []


# ── /api/rentals payload ──────────────────────────────────────────────────

import app as _app_module  # noqa: E402


@pytest.fixture

def rclient():
    """Flask test client (mirrors tests/test_rental_performance.py)."""
    _app_module.app.config["TESTING"] = True
    _app_module._RENTALS_CACHE.clear()
    with _app_module.app.test_client() as c:
        yield c
        _app_module._RENTALS_CACHE.clear()


def test_list_route_carries_accepted_recos(rclient, monkeypatch):
    """GET /api/rentals exposes the accepted-recos summary block."""
    _app_module._RENTALS_CACHE.clear()
    monkeypatch.setattr(
        _app_module._rental_perf, "fetch_mrr_rentals",
        lambda rtype="renter", history=False, limit=50, tenant_id="": {
            "success": True, "needs_auth": False, "rentals": [], "total": 0})
    monkeypatch.setattr(
        _app_module._rental_perf, "fetch_braiins_contracts",
        lambda tenant_id="": {"success": True, "needs_auth": False,
                              "contracts": []})
    monkeypatch.setattr(
        _app_module._rental_perf, "get_rig_blacklist",
        lambda tenant_id="": [])
    resp = rclient.get("/api/rentals")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "accepted_recos" in data
    recos = data["accepted_recos"]
    assert isinstance(recos, dict)
    assert set(recos.keys()) == {"count", "accepted"}
    assert isinstance(recos["accepted"], list)
    _app_module._RENTALS_CACHE.clear()
