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


# ── CSV export (?format=csv) ───────────────────────────────────────────────

import csv as _csv
import io as _io


def test_admin_accepted_recos_csv_columns_and_rows(db, clock):
    """The CSV generator serializes ONE row per decision with the full audit
    schema, None → empty cell, and neutralizes formula-injection cells."""
    data = {
        "count": 2,
        "decisions": [
            {"tenant_id": "tenant-a", "ts": NOW, "rig_id": "rig-1",
             "name": "=SUM(A1)", "source": "manual", "grade": "F",
             "pilot_flagged": True, "delivery_pct": 62.0, "samples": 3,
             "delivery_after_pct": None, "cost_after_sats_per_thh": None,
             "restored": False, "restored_ts": 0, "verdict": "avoided"},
            {"tenant_id": "default", "ts": NOW - 86400, "rig_id": "rig-2",
             "name": "Rig Dois", "source": "auto", "grade": "D",
             "pilot_flagged": False, "delivery_pct": 80.0, "samples": 4,
             "delivery_after_pct": 95.2, "cost_after_sats_per_thh": 3100.0,
             "restored": True, "restored_ts": NOW, "verdict": "revoked"},
        ],
    }
    out = rp.admin_accepted_recos_csv(data)
    rows = list(_csv.reader(_io.StringIO(out)))
    assert rows[0] == rp.ADMIN_ACCEPTED_CSV_COLUMNS
    assert len(rows) == 3  # header + 2 decisions
    r1 = dict(zip(rows[0], rows[1]))
    # Formula-injection guard: leading '=' neutralized to a quoted string.
    assert r1["name"] == "'=SUM(A1)"
    assert r1["tenant_id"] == "tenant-a"
    assert r1["verdict"] == "avoided"
    assert r1["pilot_flagged"] == "1"
    # None → empty cell; ts rendered as UTC, 0/None → empty.
    assert r1["delivery_after_pct"] == ""
    assert r1["cost_after_sats_per_thh"] == ""
    assert r1["accepted_ts"].endswith("UTC")
    assert r1["restored_ts"] == ""
    r2 = dict(zip(rows[0], rows[2]))
    assert r2["restored"] == "1"
    assert r2["verdict"] == "revoked"
    assert r2["tenant_id"] == "default"


def test_admin_accepted_recos_csv_empty_payload(db):
    out = rp.admin_accepted_recos_csv({"count": 0, "decisions": []})
    rows = list(_csv.reader(_io.StringIO(out)))
    assert rows == [rp.ADMIN_ACCEPTED_CSV_COLUMNS]


def test_route_csv_export(rclient, db, clock):
    """?format=csv → text/csv attachment with BOM + full audit rows."""
    _seed([_hr("a1", "rig-a", _dt_str(NOW - 86400), 74.0)])
    rp.add_rig_to_blacklist("rig-a")
    _seed([_hr("b1", "rig-b", _dt_str(NOW - 86400), 60.0)], tenant_id="tenant-a")
    rp.add_rig_to_blacklist("rig-b", tenant_id="tenant-a")

    resp = rclient.get("/api/admin/rentals/accepted-recos?format=csv")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert "attachment" in (resp.headers.get("Content-Disposition") or "")
    assert resp.headers["Content-Disposition"].startswith("attachment; filename=accepted_recos_audit_")
    body = resp.get_data(as_text=True)
    assert body.startswith("\ufeff")  # BOM → Excel abre UTF-8
    rows = list(_csv.reader(_io.StringIO(body.lstrip("\ufeff"))))
    assert rows[0] == rp.ADMIN_ACCEPTED_CSV_COLUMNS
    assert len(rows) == 3  # header + 2 decisions (default + named tenant)
    # Both tenants appear; verdicts computed by the shared outcome.
    tenants = {dict(zip(rows[0], r))["tenant_id"] for r in rows[1:]}
    assert tenants == {"default", "tenant-a"}


def test_route_csv_403_without_gate(rclient, db, clock):
    """The CSV branch keeps the SAME admin gate — never public."""
    resp = rclient.get("/api/admin/rentals/accepted-recos?format=csv",
                       environ_base={"REMOTE_ADDR": "8.8.8.8"})
    assert resp.status_code == 403


def test_route_csv_defaults_to_full_limit(rclient, db, clock, monkeypatch):
    """The CSV export defaults to the FULL cap (1000), not the JSON
    pagination default (200) — a truncated file must never be mistaken for
    the complete audit trail. A smaller explicit ?limit still wins."""
    calls = []
    monkeypatch.setattr(
        _app_module._rental_perf, "compute_admin_accepted_recos",
        lambda days=0, limit=200: (calls.append(limit) or {"count": 0, "decisions": []}))
    resp = rclient.get("/api/admin/rentals/accepted-recos?format=csv")
    assert resp.status_code == 200
    assert calls == [1000]  # full cap by default
    resp2 = rclient.get("/api/admin/rentals/accepted-recos?format=csv&limit=50")
    assert resp2.status_code == 200
    assert calls == [1000, 50]  # explicit limit wins


# ── Tenant worse-concentration report ───────────────────────────────────────


def test_worse_concentration_flags_recidivist_tenant(db, clock):
    """A tenant where a large share of accepted decisions end 'worse' is
    flagged (min_worse + worse_ratio both hold); a healthy tenant is not."""
    # tenant-a: 3 of 5 accepted decisions come back worse → flagged.
    for i in range(3):
        _seed([_hr(f"wa{i}", f"rig-wa{i}", _dt_str(NOW - 3 * 86400), 55.0)],
              tenant_id="tenant-a")
        rp.add_rig_to_blacklist(f"rig-wa{i}", tenant_id="tenant-a")
        _seed([_hr(f"wa{i}b", f"rig-wa{i}", _dt_str(NOW + 3600), 48.0)],
              tenant_id="tenant-a")
    for i in range(2):
        _seed([_hr(f"ok{i}", f"rig-ok{i}", _dt_str(NOW - 3 * 86400), 60.0)],
              tenant_id="tenant-a")
        rp.add_rig_to_blacklist(f"rig-ok{i}", tenant_id="tenant-a")
        _seed([_hr(f"ok{i}b", f"rig-ok{i}", _dt_str(NOW + 3600), 96.0)],
              tenant_id="tenant-a")
    # tenant-b: 1 of 5 worse → below the ratio bar, never flagged.
    for i in range(5):
        _seed([_hr(f"tb{i}", f"rig-tb{i}", _dt_str(NOW - 3 * 86400), 60.0)],
              tenant_id="tenant-b")
        rp.add_rig_to_blacklist(f"rig-tb{i}", tenant_id="tenant-b")
        _seed([_hr(f"tb{i}b", f"rig-tb{i}", _dt_str(NOW + 3600),
                   80.0 if i == 0 else 95.0)], tenant_id="tenant-b")

    rep = rp.detect_tenant_worse_concentration()
    assert rep["count"] == 1
    flag = rep["tenants"][0]
    assert flag["tenant_id"] == "tenant-a"
    assert flag["total"] == 5
    assert flag["worse"] == 3
    assert flag["ratio_pct"] == 60.0
    # 3 worse + ratio >= 60 → CRIT.
    assert flag["severity"] == "CRIT"
    assert rep["min_worse"] == 2
    assert rep["worse_ratio"] == 0.5


def test_worse_concentration_thresholds_and_window(db, clock):
    """Custom thresholds and the days window shape the report."""
    for i in range(3):
        _seed([_hr(f"x{i}", f"rig-x{i}", _dt_str(NOW - 3 * 86400), 55.0)],
              tenant_id="t-x")
        rp.add_rig_to_blacklist(f"rig-x{i}", tenant_id="t-x")
        _seed([_hr(f"x{i}b", f"rig-x{i}", _dt_str(NOW + 3600), 50.0)],
              tenant_id="t-x")
    # One improved decision in the same tenant → ratio 3/4 = 75%.
    _seed([_hr("g0", "rig-g0", _dt_str(NOW - 3 * 86400), 55.0)],
          tenant_id="t-x")
    rp.add_rig_to_blacklist("rig-g0", tenant_id="t-x")
    _seed([_hr("g0b", "rig-g0", _dt_str(NOW + 3600), 96.0)],
          tenant_id="t-x")
    # min_worse=4 > 3 worse → nothing flagged.
    assert rp.detect_tenant_worse_concentration(min_worse=4)["count"] == 0
    # worse_ratio=0.9 → 75% < 90% → nothing flagged.
    assert rp.detect_tenant_worse_concentration(worse_ratio=0.9)["count"] == 0
    # days window that EXCLUDES the acceptance samples → nothing flagged.
    assert rp.detect_tenant_worse_concentration(days=0) is not None
    clock["now"] = NOW + 10 * 86400
    assert rp.detect_tenant_worse_concentration(days=5)["count"] == 0


def test_worse_concentration_ignores_revoked_and_empty(db, clock):
    """Revoked decisions (restored rigs) never count as recidivism; empty DB
    → zeroed report.

    Discriminating case: 2 worse + 1 revoked in one tenant with min_worse=3
    — a buggy detector that counted revoked as worse would see 3 and flag;
    the correct one sees 2 < 3 and stays silent."""
    for i in range(2):
        _seed([_hr(f"w{i}", f"rig-w{i}", _dt_str(NOW - 3 * 86400), 55.0)],
              tenant_id="t-z")
        rp.add_rig_to_blacklist(f"rig-w{i}", tenant_id="t-z")
        _seed([_hr(f"w{i}b", f"rig-w{i}", _dt_str(NOW + 3600), 48.0)],
              tenant_id="t-z")
    _seed([_hr("r2", "rig-r2", _dt_str(NOW - 3 * 86400), 55.0)],
          tenant_id="t-z")
    rp.add_rig_to_blacklist("rig-r2", tenant_id="t-z")
    rp.remove_rig_from_blacklist("rig-r2", tenant_id="t-z")  # → revoked

    # min_worse=3: 2 worse + revoked (never worse) → NOT flagged
    # (a buggy detector counting revoked as worse would see 3 and flag).
    assert rp.detect_tenant_worse_concentration(min_worse=3)["count"] == 0

    # Default thresholds: 2 worse / 3 total = 66.7% → WARN, NOT CRIT —
    # the revoked decision never inflates worse to 3.
    rep = rp.detect_tenant_worse_concentration()
    assert rep["count"] == 1
    assert rep["tenants"][0]["tenant_id"] == "t-z"
    assert rep["tenants"][0]["worse"] == 2
    assert rep["tenants"][0]["severity"] == "WARN"

    assert rp.detect_tenant_worse_concentration()["count"] == 1
    empty = rp.detect_tenant_worse_concentration()
    assert empty == {"count": 1, "tenants": rep["tenants"], "min_worse": 2,
                     "worse_ratio": 0.5, "days": None}


def test_route_carries_worse_concentration(rclient, db, clock):
    """The admin route JSON carries the worse-concentration report."""
    for i in range(3):
        _seed([_hr(f"c{i}", f"rig-c{i}", _dt_str(NOW - 3 * 86400), 55.0)])
        rp.add_rig_to_blacklist(f"rig-c{i}")
        _seed([_hr(f"c{i}b", f"rig-c{i}", _dt_str(NOW + 3600), 48.0)])
    resp = rclient.get("/api/admin/rentals/accepted-recos?worse_min=2&worse_ratio=0.5")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "worse_concentration" in data
    rep = data["worse_concentration"]
    assert rep["count"] == 1
    assert rep["tenants"][0]["tenant_id"] == "default"
    assert rep["tenants"][0]["worse"] == 3
    assert rep["min_worse"] == 2
    assert rep["worse_ratio"] == 0.5
