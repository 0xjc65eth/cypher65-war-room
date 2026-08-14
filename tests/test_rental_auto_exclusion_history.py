"""Tests for the auto-exclusion history (WHEN + CAUSE) — RENTALS + admin audit.

Covers:
  - auto_exclusion_history(): per-tenant history of PILOT auto-exclusions with
    the delivery snapshot at exclusion time (grade, delivery %, samples) + the
    rule vigente (grade floor + min samples) + a human-readable cause.
  - Only source='auto' entries appear (manual blacklists are excluded).
  - Tenant isolation (default vs named tenants never share the history).
  - Custom rule from settings reflected in the returned rule fields.
  - admin_auto_exclusion_history(): GLOBAL pass across ALL tenants (tagging
    tenant_id) honoring the days window via the shared _admin_audit_decisions.
  - /api/rentals carries auto_exclusions (tenant-scoped, empty shape).
  - /api/admin/rentals/accepted-recos carries auto_exclusions (gated, global).
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


@pytest.fixture(autouse=True)
def _fresh_settings_cache():
    """The tenant settings cache is module-level and survives between test
    files in the same process — invalidate it around every test so the rule
    thresholds never leak across tests."""
    from services import settings as _settings_mod
    _settings_mod._tenant_settings_cache.clear()
    yield
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


def _auto_exclude(rig_id, tenant_id=""):
    assert rp.add_rig_to_auto_blacklist(rig_id, tenant_id=tenant_id) is True


# ── auto_exclusion_history (tenant-scoped) ────────────────────────────────

def test_auto_exclusion_history_empty(db, clock):
    """No exclusions → zeroed shape, never raises."""
    h = rp.auto_exclusion_history()
    assert h == {"count": 0, "exclusions": []}


def test_auto_exclusion_history_when_and_cause(db, clock):
    """An auto-exclusion carries WHEN (ts), the delivery snapshot (grade,
    delivery %, samples) and the rule vigente + readable cause."""
    _seed([_hr("r1", "rig-b", _dt_str(NOW - 86400), 60.0)])
    _auto_exclude("rig-b")
    h = rp.auto_exclusion_history()
    assert h["count"] == 1
    e = h["exclusions"][0]
    assert e["rig_id"] == "rig-b"
    assert e["ts"] == NOW
    assert e["delivery_pct"] == 60.0
    assert e["samples"] == 1
    assert e["grade"] == "F"
    # Default rule vigente: floor F, min 2 (legacy behavior preserved).
    assert e["min_samples"] == 2
    assert e["grade_floor"] == "F"
    assert "grade F" in e["cause"]
    assert "entrega 60.0%" in e["cause"]
    assert "1 amostra" in e["cause"]
    assert "1 amostras" not in e["cause"]  # PT-BR singular for n=1
    assert "régua: floor F, mín 2" in e["cause"]


def test_auto_exclusion_history_custom_rule_reflected(db, clock):
    """A per-tenant custom rule (floor D, min 3) is reflected in the returned
    rule fields — the history shows the régua vigente."""
    from services.settings import save_setting
    save_setting("rental_auto_blacklist_grade", "D", tenant_id="t-rule")
    save_setting("rental_auto_blacklist_min_samples", "3", tenant_id="t-rule")
    _seed([_hr("r1", "rig-d", _dt_str(NOW - 86400), 70.0)], tenant_id="t-rule")
    _auto_exclude("rig-d", tenant_id="t-rule")
    h = rp.auto_exclusion_history(tenant_id="t-rule")
    e = h["exclusions"][0]
    assert e["min_samples"] == 3
    assert e["grade_floor"] == "D"
    assert "régua: floor D, mín 3" in e["cause"]


def test_auto_exclusion_history_ignores_manual(db, clock):
    """Manual blacklists are NOT pilot auto-exclusions — excluded from the
    auto history (they live in the accepted-recos ledger with source='manual')."""
    _seed([_hr("r1", "rig-a", _dt_str(NOW - 86400), 72.0)])
    assert rp.add_rig_to_blacklist("rig-a") is True
    assert rp.get_rig_blacklist() == ["rig-a"]
    h = rp.auto_exclusion_history()
    assert h["count"] == 0


def test_auto_exclusion_history_tenant_isolation(db, clock):
    """Named-tenant exclusions never leak into the default tenant's history."""
    _seed([_hr("r1", "rig-a", _dt_str(NOW - 86400), 60.0)], tenant_id="t-a")
    _auto_exclude("rig-a", tenant_id="t-a")
    assert rp.auto_exclusion_history(tenant_id="")["count"] == 0
    assert rp.auto_exclusion_history(tenant_id="t-a")["count"] == 1
    assert rp.auto_exclusion_history(tenant_id="t-b")["count"] == 0


def test_auto_exclusion_history_newest_first(db, clock):
    """Multiple exclusions are sorted newest first (ts desc)."""
    _seed([_hr("r1", "rig-1", _dt_str(NOW - 86400), 60.0),
           _hr("r2", "rig-2", _dt_str(NOW - 86400), 61.0)])
    clock["now"] = NOW - 10 * 86400
    _auto_exclude("rig-1")
    clock["now"] = NOW - 5 * 86400
    _auto_exclude("rig-2")
    h = rp.auto_exclusion_history()
    ts = [e["ts"] for e in h["exclusions"]]
    assert ts == sorted(ts, reverse=True)
    assert h["exclusions"][0]["rig_id"] == "rig-2"


# ── admin_auto_exclusion_history (global operator) ────────────────────────

def test_admin_auto_exclusion_history_global_tenants_tagged(db, clock):
    """Global pass aggregates default + named tenants, tagging tenant_id."""
    _seed([_hr("r1", "rig-a", _dt_str(NOW - 86400), 60.0)])
    _auto_exclude("rig-a")
    _seed([_hr("r2", "rig-b", _dt_str(NOW - 86400), 55.0)], tenant_id="tenant-a")
    _auto_exclude("rig-b", tenant_id="tenant-a")
    h = rp.admin_auto_exclusion_history()
    assert h["count"] == 2
    tenants = sorted(e["tenant_id"] for e in h["exclusions"])
    assert tenants == ["default", "tenant-a"]
    # Manual exclusions never leak into the global auto history either.
    _seed([_hr("r3", "rig-c", _dt_str(NOW - 86400), 74.0)], tenant_id="tenant-b")
    rp.add_rig_to_blacklist("rig-c", tenant_id="tenant-b")
    assert rp.admin_auto_exclusion_history()["count"] == 2


def test_admin_auto_exclusion_history_days_window(db, clock):
    """The days window (shared with the rest of the audit) drops exclusions
    older than the cutoff."""
    _seed([_hr("r1", "rig-a", _dt_str(NOW - 86400), 60.0)])
    _auto_exclude("rig-a")
    assert rp.admin_auto_exclusion_history(days=30)["count"] == 1
    # Advance 'now' past the 30-day window — the decision ts stays at NOW.
    clock["now"] = NOW + 40 * 86400
    assert rp.admin_auto_exclusion_history(days=30)["count"] == 0


# ── admin_auto_exclusion_aggregates (padrão global do piloto) ─────────────

def test_admin_auto_exclusion_aggregates_by_tenant(db, clock):
    """by_tenant groups the global exclusions: who triggers the pilot most,
    sorted by count desc, with pct/rigs/top_grade/delivery avg."""
    _seed([_hr("a1", "rig-a", _dt_str(NOW - 3 * 86400), 60.0)])
    _auto_exclude("rig-a")
    _seed([_hr("b1", "rig-b", _dt_str(NOW - 2 * 86400), 55.0),
           _hr("b2", "rig-c", _dt_str(NOW - 86400), 50.0)], tenant_id="tenant-a")
    _auto_exclude("rig-b", tenant_id="tenant-a")
    _auto_exclude("rig-c", tenant_id="tenant-a")

    agg = rp.admin_auto_exclusion_aggregates()
    assert agg["count"] == 3
    assert agg["days"] is None
    tenants = agg["by_tenant"]
    assert [t["tenant_id"] for t in tenants] == ["tenant-a", "default"]
    ta = tenants[0]
    assert ta["count"] == 2
    assert round(ta["pct"], 1) == 66.7
    assert ta["rigs"] == 2
    assert round(ta["delivery_avg_pct"], 1) == 52.5
    de = tenants[1]
    assert de["tenant_id"] == "default"
    assert de["count"] == 1
    assert round(de["pct"], 1) == 33.3
    assert de["rigs"] == 1


def test_admin_auto_exclusion_aggregates_by_rule(db, clock):
    """by_rule groups by the vigente régua (floor/min): how aggressive each
    tenant's rule is, with tenant count + avg delivery."""
    from services.settings import save_setting
    save_setting("rental_auto_blacklist_grade", "D", tenant_id="t-rule")
    save_setting("rental_auto_blacklist_min_samples", "3", tenant_id="t-rule")
    _seed([_hr("r1", "rig-d", _dt_str(NOW - 86400), 70.0)], tenant_id="t-rule")
    _auto_exclude("rig-d", tenant_id="t-rule")
    _seed([_hr("a1", "rig-a", _dt_str(NOW - 86400), 60.0)])
    _auto_exclude("rig-a")

    rules = rp.admin_auto_exclusion_aggregates()["by_rule"]
    by = {(r["grade_floor"], r["min_samples"]): r for r in rules}
    assert set(by) == {("D", 3), ("F", 2)}
    assert by[("D", 3)]["count"] == 1
    assert by[("D", 3)]["tenants"] == 1
    assert by[("D", 3)]["delivery_avg_pct"] == 70.0
    assert by[("F", 2)]["count"] == 1
    assert by[("F", 2)]["tenants"] == 1
    # Aggressiveness is visible: D/3 fired for a 70% rig (would NOT fire
    # under the default F/2 rule) — the régua snapshot is per-tenant.
    assert by[("D", 3)]["pct"] == by[("F", 2)]["pct"] == 50.0


def test_admin_auto_exclusion_aggregates_top_rigs_multi_tenant(db, clock):
    """top_rigs surfaces SYSTEMIC-problem rigs: the SAME rig auto-excluded in
    2+ tenants (single-tenant exclusions are noise and stay out)."""
    _seed([_hr("a1", "rig-x", _dt_str(NOW - 3 * 86400), 60.0)])
    _auto_exclude("rig-x")
    _seed([_hr("b1", "rig-x", _dt_str(NOW - 2 * 86400), 55.0)], tenant_id="tenant-a")
    _auto_exclude("rig-x", tenant_id="tenant-a")
    _seed([_hr("c1", "rig-solo", _dt_str(NOW - 86400), 50.0)], tenant_id="tenant-b")
    _auto_exclude("rig-solo", tenant_id="tenant-b")

    top = rp.admin_auto_exclusion_aggregates()["top_rigs"]
    assert len(top) == 1
    assert top[0]["rig_id"] == "rig-x"
    assert top[0]["tenant_count"] == 2
    assert top[0]["total_count"] == 2
    assert sorted(top[0]["tenants"]) == ["default", "tenant-a"]
    assert top[0]["last_ts"] > 0


def test_admin_auto_exclusion_aggregates_days_window(db, clock):
    """The days window is shared with the history (same pass → zero drift)."""
    _seed([_hr("a1", "rig-a", _dt_str(NOW - 86400), 60.0)])
    _auto_exclude("rig-a")
    assert rp.admin_auto_exclusion_aggregates(days=30)["count"] == 1
    clock["now"] = NOW + 40 * 86400
    agg = rp.admin_auto_exclusion_aggregates(days=30)
    assert agg["count"] == 0
    assert agg["by_tenant"] == []
    assert agg["by_rule"] == []
    assert agg["top_rigs"] == []
    assert agg["days"] == 30


def test_admin_auto_exclusion_aggregates_empty(db, clock):
    """Empty ledger → zeroed shape, never raises."""
    agg = rp.admin_auto_exclusion_aggregates()
    assert agg == {"count": 0, "by_tenant": [], "by_rule": [],
                   "top_rigs": [], "days": None}


# ── Routes ────────────────────────────────────────────────────────────────

import app as _app_module  # noqa: E402


@pytest.fixture
def rclient():
    """Flask test client (mirrors tests/test_admin_accepted_recos.py)."""
    _app_module.app.config["TESTING"] = True
    with _app_module.app.test_client() as c:
        yield c


def test_rentals_route_carries_auto_exclusions(monkeypatch):
    """GET /api/rentals exposes the tenant-scoped auto-exclusion history."""
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
    _app_module.app.config["TESTING"] = True
    with _app_module.app.test_client() as c:
        resp = c.get("/api/rentals")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "auto_exclusions" in data
        h = data["auto_exclusions"]
        assert isinstance(h, dict)
        assert set(h.keys()) == {"count", "exclusions"}
        assert h["count"] == 0
    _app_module._RENTALS_CACHE.clear()


def test_admin_route_carries_auto_exclusions(rclient, db, clock):
    """Localhost admin call returns the global auto-exclusion history."""
    _seed([_hr("a1", "rig-a", _dt_str(NOW - 86400), 60.0)])
    _auto_exclude("rig-a")
    resp = rclient.get("/api/admin/rentals/accepted-recos")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "auto_exclusions" in data
    h = data["auto_exclusions"]
    assert h["count"] == 1
    assert h["exclusions"][0]["tenant_id"] == "default"
    assert "cause" in h["exclusions"][0]


def test_admin_route_carries_auto_exclusion_aggregates(rclient, db, clock):
    """Localhost admin call returns the global concentration report — the
    same shared pass, so by_tenant reflects the seeded exclusions."""
    _seed([_hr("a1", "rig-a", _dt_str(NOW - 86400), 60.0)])
    _auto_exclude("rig-a")
    _seed([_hr("b1", "rig-b", _dt_str(NOW - 86400), 55.0)], tenant_id="tenant-a")
    _auto_exclude("rig-b", tenant_id="tenant-a")
    resp = rclient.get("/api/admin/rentals/accepted-recos")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "auto_exclusion_aggregates" in data
    agg = data["auto_exclusion_aggregates"]
    assert agg["count"] == 2
    assert {t["tenant_id"] for t in agg["by_tenant"]} == {"default", "tenant-a"}
    assert agg["by_tenant"][0]["count"] == 1
    assert agg["by_rule"]  # at least the default F/2 bucket
    assert agg["top_rigs"] == []  # one rig per tenant → no systemic pattern
