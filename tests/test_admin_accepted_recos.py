"""Tests for the /api/admin audit trail of accepted recommendations.

Covers:
  - _load_all_accepted_recos(): reads the default-tenant ledger (settings
    table) AND every named-tenant ledger (tenant_settings), tagging tenant_id
    ('default' for the global table).
  - compute_admin_accepted_recos(): global aggregates — by_source, by_verdict,
    by_tenant, pilot_flagged, delivery averages, per-decision tenant_id +
    verdict; empty DB → zeroed aggregates (never raises).
  - days window filter + limit.
  - Route GET /api/admin/rentals/accepted-recos: 403 without the admin gate
    (non-local, no key), 200 locally, 200 with X-API-Key on a non-local call.
"""
import datetime as _dt
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import rental_performance as rp  # noqa: E402

NOW = 1_800_000_000  # fixed reference "now"


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Per-test scratch DB (get_db reads DB_PATH at call time)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.sqlite"))


@pytest.fixture
def clock(monkeypatch):
    """Mutable fake clock — rp.time.time returns the current fake 'now'."""
    state = {"now": NOW}
    monkeypatch.setattr(rp.time, "time", lambda: state["now"])
    return state


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


# ── Global ledger reader ───────────────────────────────────────────────────

def test_load_all_reads_default_and_named(db, clock):
    _seed([_hr("a1", "rig-a", _dt_str(NOW - 86400), 74.0)])
    rp.add_rig_to_blacklist("rig-a")                       # default tenant
    _seed([_hr("b1", "rig-b", _dt_str(NOW - 86400), 60.0)], tenant_id="tenant-a")
    rp.add_rig_to_auto_blacklist("rig-b", tenant_id="tenant-a")

    all_entries = rp._load_all_accepted_recos()
    assert len(all_entries) == 2
    tids = {e["tenant_id"] for e in all_entries}
    assert tids == {"default", "tenant-a"}
    by_tid = {e["tenant_id"]: e for e in all_entries}
    assert by_tid["default"]["rig_id"] == "rig-a"
    assert by_tid["tenant-a"]["rig_id"] == "rig-b"


def test_load_all_empty(db):
    assert rp._load_all_accepted_recos() == []


# ── Global aggregation ─────────────────────────────────────────────────────

def test_admin_aggregates_all_tenants(db, clock):
    # default: manual blacklist of a grade-F rig, avoided afterwards.
    _seed([_hr("a1", "rig-a", _dt_str(NOW - 2 * 86400), 72.0),
           _hr("a2", "rig-a", _dt_str(NOW - 86400), 78.0)])
    rp.add_rig_to_blacklist("rig-a")
    # tenant-a: auto exclusion, then the rig improved on re-rental.
    _seed([_hr("b1", "rig-b", _dt_str(NOW - 86400), 60.0)], tenant_id="tenant-a")
    rp.add_rig_to_auto_blacklist("rig-b", tenant_id="tenant-a")
    _seed([_hr("b2", "rig-b", _dt_str(NOW + 3600), 95.0)], tenant_id="tenant-a")

    admin = rp.compute_admin_accepted_recos()
    assert admin["count"] == 2
    assert admin["by_source"] == {"manual": 1, "auto": 1}
    assert admin["by_verdict"] == {"avoided": 1, "improved": 1}
    assert admin["pilot_flagged"] == 2  # both grade F at acceptance
    assert admin["avg_delivery_before"] == 67.5   # (75 + 60) / 2
    assert admin["avg_delivery_after"] == 95.0
    tenant_rows = {t["tenant_id"]: t for t in admin["by_tenant"]}
    assert set(tenant_rows) == {"default", "tenant-a"}
    assert tenant_rows["default"]["count"] == 1
    assert tenant_rows["tenant-a"]["by_source"] == {"auto": 1}
    # Every decision is tagged with tenant + verdict.
    dec = {d["rig_id"]: d for d in admin["decisions"]}
    assert dec["rig-a"]["tenant_id"] == "default"
    assert dec["rig-a"]["verdict"] == "avoided"
    assert dec["rig-b"]["tenant_id"] == "tenant-a"
    assert dec["rig-b"]["verdict"] == "improved"


def test_admin_empty_db_zeroed(db, clock):
    admin = rp.compute_admin_accepted_recos()
    assert admin["count"] == 0
    assert admin["by_source"] == {}
    assert admin["by_verdict"] == {}
    assert admin["by_tenant"] == []
    assert admin["pilot_flagged"] == 0
    assert admin["avg_delivery_before"] is None
    assert admin["avg_delivery_after"] is None
    assert admin["decisions"] == []


def test_admin_days_window(db, clock):
    clock["now"] = NOW - 40 * 86400
    _seed([_hr("o1", "rig-old", _dt_str(clock["now"] - 86400), 50.0)])
    rp.add_rig_to_blacklist("rig-old")
    clock["now"] = NOW - 5 * 86400
    _seed([_hr("n1", "rig-new", _dt_str(clock["now"] - 86400), 70.0)])
    rp.add_rig_to_blacklist("rig-new")

    admin = rp.compute_admin_accepted_recos(days=30)
    assert admin["count"] == 1
    assert [d["rig_id"] for d in admin["decisions"]] == ["rig-new"]


def test_admin_limit(db, clock):
    for i in range(3):
        _seed([_hr(f"r{i}", f"rig-{i}", _dt_str(NOW - 86400), 60.0 + i)])
        rp.add_rig_to_blacklist(f"rig-{i}")
    admin = rp.compute_admin_accepted_recos(limit=2)
    assert admin["count"] == 3          # total, not capped
    assert len(admin["decisions"]) == 2  # list capped


# ── /api/admin route ───────────────────────────────────────────────────────

import app as _app_module  # noqa: E402


@pytest.fixture
def rclient():
    """Flask test client (mirrors tests/test_rental_performance.py)."""
    _app_module.app.config["TESTING"] = True
    with _app_module.app.test_client() as c:
        yield c


def test_route_403_without_admin_gate(rclient):
    """Non-local remote without an operator API key → 403 (never public)."""
    resp = rclient.get("/api/admin/rentals/accepted-recos",
                       environ_base={"REMOTE_ADDR": "8.8.8.8"})
    assert resp.status_code == 403


def test_route_200_local_with_aggregation(rclient, db, clock):
    """Localhost (test client default remote) passes the gate and returns
    the global aggregation (default + named tenants)."""
    _seed([_hr("a1", "rig-a", _dt_str(NOW - 86400), 74.0)])
    rp.add_rig_to_blacklist("rig-a")
    _seed([_hr("b1", "rig-b", _dt_str(NOW - 86400), 60.0)], tenant_id="tenant-a")
    rp.add_rig_to_blacklist("rig-b", tenant_id="tenant-a")

    resp = rclient.get("/api/admin/rentals/accepted-recos")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] == 2
    assert len(data["by_tenant"]) == 2
    assert data["decisions"][0]["tenant_id"] in ("default", "tenant-a")


def test_route_200_with_operator_key(rclient, db, clock, monkeypatch):
    """Non-local remote WITH the operator API key → 200."""
    monkeypatch.setenv("API_KEY", "op-secret-123")
    _seed([_hr("a1", "rig-a", _dt_str(NOW - 86400), 74.0)])
    rp.add_rig_to_blacklist("rig-a")
    resp = rclient.get("/api/admin/rentals/accepted-recos?days=30&limit=50",
                       environ_base={"REMOTE_ADDR": "8.8.8.8"},
                       headers={"X-API-Key": "op-secret-123"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] == 1
    assert data["days"] == 30
