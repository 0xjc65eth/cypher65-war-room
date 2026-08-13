"""
CYPHER65 // Issue #20 — Auto-Pilot advisory mode (Fase 2 do Big Bet)
=====================================================================
Unit tests for services.auto_pilot:

  1. build_advisory_recommendations() — PURE consolidation per device:
     - offline device      → crit rec with action restart (or navigate when
       the device cannot restart)
     - temperature >= 75°C → warn rec with action pause
     - hashrate < 70% of 7d peak → gold rec with action restart
     - worst rig danger >= 60 → warn rec with action blacklist (skipped when
       already blacklisted)
     - arbitrage window open → gold rec with action buy
     - healthy fleet       → [] (honest, never fabricates)
     - fail-closed: None/garbage inputs never raise
  2. record_rec_decision() / get_rec_audit() — per-tenant audit trail of
     accepted/ignored recommendations.

Hermetic: pure builder needs no DB; audit tests redirect DB_PATH to a
scratch sqlite via monkeypatch (same ethos as test_rental_performance.py).
"""

import os
import time

import pytest

from services.auto_pilot import (
    AP_RIG_POOR_DANGER_MIN,
    build_advisory_recommendations,
    record_rec_decision,
    get_rec_audit,
)
from helpers import AP_TEMP_HIGH_C


def _device(**overrides):
    d = {
        "id": "dev-1",
        "name": "MINER-1",
        "status": "ONLINE",
        "capabilities": {"restart": True, "pause": True},
        "telemetry": {"temperature": 50.0, "hashrate_hs": 5e12},
    }
    d.update(overrides)
    return d


def _rig(**overrides):
    r = {
        "rig_id": "rig-9",
        "name": "RIG-9",
        "danger": 78.0,
        "ewma_delivery_pct": 61.0,
        "samples": 5,
        "grade": "D",
    }
    r.update(overrides)
    return r


# ── Pure builder: per-device consolidation ───────────────────────────────

class TestBuildRecommendations:
    def test_healthy_fleet_returns_empty(self):
        assert build_advisory_recommendations(fleet=[_device()]) == []

    def test_none_inputs_never_raise(self):
        assert build_advisory_recommendations(None) == []
        assert build_advisory_recommendations({}) == []
        assert build_advisory_recommendations([]) == []

    def test_offline_device_yields_crit_restart(self):
        recs = build_advisory_recommendations(fleet=[_device(status="OFFLINE")])
        assert len(recs) == 1
        r = recs[0]
        assert r["id"] == "ap-offline-dev-1"
        assert r["issue_type"] == "offline"
        assert r["severity"] == "crit"
        assert r["action"]["type"] == "restart"

    def test_offline_device_without_restart_cap_falls_back_to_navigate(self):
        recs = build_advisory_recommendations(fleet=[
            _device(status="OFFLINE", capabilities={"restart": False})
        ])
        assert recs[0]["action"]["type"] == "navigate"
        assert recs[0]["action"]["label"] == "VER FLEET"

    def test_high_temp_yields_warn_pause(self):
        recs = build_advisory_recommendations(fleet=[
            _device(telemetry={"temperature": AP_TEMP_HIGH_C + 1, "hashrate_hs": 5e12})
        ])
        assert len(recs) == 1
        assert recs[0]["issue_type"] == "temp_high"
        assert recs[0]["severity"] == "warn"
        assert recs[0]["action"]["type"] == "pause"

    def test_hashrate_drop_below_70pct_of_peak_yields_gold_restart(self):
        recs = build_advisory_recommendations(
            fleet=[_device(telemetry={"temperature": 50.0, "hashrate_hs": 5e12})],
            peak_7d=10e12,  # current = 50% of peak → drop
        )
        assert any(r["issue_type"] == "hashrate_drop" and r["severity"] == "gold"
                   and r["action"]["type"] == "restart" for r in recs)

    def test_no_false_drop_without_peak(self):
        assert build_advisory_recommendations(fleet=[_device()], peak_7d=0.0) == []

    def test_offline_device_emits_only_offline_rec(self):
        # Offline short-circuits: one recommendation per device, no noise.
        recs = build_advisory_recommendations(
            fleet=[_device(status="OFFLINE",
                           telemetry={"temperature": 99.0, "hashrate_hs": 0})],
            peak_7d=10e12,
        )
        assert len(recs) == 1
        assert recs[0]["issue_type"] == "offline"

    def test_worst_rig_over_threshold_yields_blacklist(self):
        recs = build_advisory_recommendations(
            worst_rigs=[_rig()],
        )
        assert any(r["issue_type"] == "rig_poor" and r["action"]["type"] == "blacklist"
                   for r in recs)

    def test_worst_rig_below_threshold_is_skipped(self):
        recs = build_advisory_recommendations(
            worst_rigs=[_rig(danger=AP_RIG_POOR_DANGER_MIN - 5)],
        )
        assert all(r["issue_type"] != "rig_poor" for r in recs)

    def test_already_blacklisted_rig_is_skipped(self):
        recs = build_advisory_recommendations(
            worst_rigs=[_rig()],
            blacklisted_rigs=["rig-9"],
        )
        assert all(r["issue_type"] != "rig_poor" for r in recs)

    def test_arb_window_yields_buy(self):
        recs = build_advisory_recommendations(arb_window=[{"discount_pct": 15.0}])
        assert any(r["issue_type"] == "buy" and r["action"]["type"] == "buy"
                   and r["action"]["label"] == "COMPRAR AGORA" for r in recs)

    def test_severity_ordering_crit_first(self):
        recs = build_advisory_recommendations(
            fleet=[
                _device(id="dev-a", name="A", status="OFFLINE"),
                _device(id="dev-b", name="B",
                        telemetry={"temperature": AP_TEMP_HIGH_C + 2, "hashrate_hs": 1e12}),
                _device(id="dev-c", name="C",
                        telemetry={"temperature": 50.0, "hashrate_hs": 1e12}),
            ],
            peak_7d=10e12,
            arb_window=[{"discount_pct": 20.0}],
        )
        sev_order = {"crit": 0, "gold": 1, "warn": 2, "info": 3}
        ranks = [sev_order[r["severity"]] for r in recs]
        assert ranks == sorted(ranks)
        assert recs[0]["issue_type"] == "offline"

    def test_device_name_falls_back_to_id(self):
        recs = build_advisory_recommendations(fleet=[_device(name="", status="OFFLINE")])
        assert recs[0]["device_name"] == "dev-1"


# ── Audit trail (per tenant) ─────────────────────────────────────────────

@pytest.fixture
def scratch_db(tmp_path, monkeypatch):
    db = str(tmp_path / "ap_audit.sqlite")
    monkeypatch.setenv("DB_PATH", db)
    return db


def test_record_and_read_audit_roundtrip(scratch_db):
    rec = {
        "id": "ap-offline-dev-1",
        "device_id": "dev-1",
        "device_name": "MINER-1",
        "issue_type": "offline",
        "severity": "crit",
        "action": {"type": "restart", "label": "REINICIAR"},
    }
    ok = record_rec_decision("acme", rec, "accept", note="operador confirmou",
                             action_result={"ok": True})
    assert ok is True

    rows = get_rec_audit("acme")
    assert len(rows) == 1
    row = rows[0]
    assert row["tenant_id"] == "acme"
    assert row["rec_id"] == "ap-offline-dev-1"
    assert row["device_id"] == "dev-1"
    assert row["issue_type"] == "offline"
    assert row["action_type"] == "restart"
    assert row["decision"] == "accept"
    assert "operador confirmou" in row["note"]
    assert "ok" in row["result"]


def test_audit_scoped_per_tenant(scratch_db):
    rec = {"id": "ap-x", "device_id": "d", "issue_type": "temp_high",
           "action": {"type": "pause"}}
    record_rec_decision("acme", rec, "ignore", note="n")
    record_rec_decision("brave", rec, "accept", note="n2")

    assert len(get_rec_audit("acme")) == 1
    assert len(get_rec_audit("brave")) == 1
    assert get_rec_audit("acme")[0]["decision"] == "ignore"
    assert get_rec_audit("brave")[0]["decision"] == "accept"
    # Default tenant never sees named-tenant rows.
    assert len(get_rec_audit("default")) == 0


def test_audit_limit_respected(scratch_db):
    rec = {"id": "ap-y", "device_id": "d", "issue_type": "buy",
           "action": {"type": "buy"}}
    for _ in range(5):
        record_rec_decision("acme", rec, "ignore")
    rows = get_rec_audit("acme", limit=2)
    assert len(rows) == 2


def test_record_fail_closed_never_raises(scratch_db, monkeypatch):
    # record_rec_decision imports get_db from services.db INSIDE the function,
    # so the patch must land on services.db.get_db.
    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr("services.db.get_db", boom)
    ok = record_rec_decision("acme", {"id": "x"}, "accept")
    assert ok is False
    assert get_rec_audit("acme") == []


# ── HTTP routes (app client + patched builder) ───────────────────────────

@pytest.fixture
def client(scratch_db, monkeypatch):
    from app import app
    app.config["TESTING"] = True
    # Patch the real-data collector so the route tests are hermetic (no axe
    # registry, no network, no provider calls).
    monkeypatch.setattr(
        "services.auto_pilot.build_recommendations_for_tenant",
        lambda tenant_id="": [{
            "id": "ap-offline-dev-1",
            "device_id": "dev-1",
            "device_name": "MINER-1",
            "issue_type": "offline",
            "severity": "crit",
            "message": "MINER-1 está OFFLINE.",
            "action": {"type": "restart", "label": "REINICIAR"},
        }],
    )
    with app.test_client() as c:
        yield c


def test_recommendations_endpoint(client):
    resp = client.get("/api/auto-pilot/recommendations")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] == 1
    assert data["recommendations"][0]["issue_type"] == "offline"
    assert "action" in data["recommendations"][0]
    assert "armed" in data


def test_respond_ignore_records_audit(client, scratch_db):
    resp = client.post(
        "/api/auto-pilot/recommendations/ap-offline-dev-1/respond",
        json={"decision": "ignore"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["decision"] == "ignore"
    assert data["recorded"] is True

    audit = get_rec_audit("default")
    assert len(audit) == 1
    assert audit[0]["rec_id"] == "ap-offline-dev-1"
    assert audit[0]["decision"] == "ignore"


def test_respond_invalid_decision_400(client):
    resp = client.post(
        "/api/auto-pilot/recommendations/ap-x/respond",
        json={"decision": "maybe"},
    )
    assert resp.status_code == 400


def test_respond_accept_nonexistent_rec_409(client):
    resp = client.post(
        "/api/auto-pilot/recommendations/ap-never-existed/respond",
        json={"decision": "accept"},
    )
    assert resp.status_code == 409


def test_audit_endpoint(client, scratch_db):
    record_rec_decision("default",
                        {"id": "ap-x", "device_id": "d", "issue_type": "temp_high",
                         "action": {"type": "pause"}},
                        "accept", note="n")
    resp = client.get("/api/auto-pilot/recommendations/audit")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] == 1
    assert data["audit"][0]["decision"] == "accept"


def test_respond_accept_buy_opens_flow(client, scratch_db, monkeypatch):
    monkeypatch.setattr(
        "services.auto_pilot.build_recommendations_for_tenant",
        lambda tenant_id="": [{
            "id": "ap-buy-window",
            "device_id": "",
            "device_name": "Hash Market",
            "issue_type": "buy",
            "severity": "gold",
            "action": {"type": "buy", "label": "COMPRAR AGORA"},
        }],
    )
    resp = client.post(
        "/api/auto-pilot/recommendations/ap-buy-window/respond",
        json={"decision": "accept"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["open_buy_flow"] is True
    assert data["action_type"] == "buy"


def test_respond_accept_device_error_tuple_is_unpacked(client, scratch_db, monkeypatch):
    """Reviewer catch: _execute_device_command returns (jsonify, status)
    tuples on error paths — the respond handler must unpack both shapes and
    surface the real error, not an AttributeError on the tuple."""
    from flask import jsonify

    def fake_execute(device_id, command):
        return jsonify({"error": "device not found"}), 404

    monkeypatch.setattr("axe_fleet.routes._execute_device_command", fake_execute)
    resp = client.post(
        "/api/auto-pilot/recommendations/ap-offline-dev-1/respond",
        json={"decision": "accept"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["action_result"] == {"ok": False, "error": "device not found"}
    # The failed action is still audited with its result.
    audit = get_rec_audit("default")
    assert audit and audit[-1]["decision"] == "accept"
    assert "device not found" in audit[-1]["result"]


def test_audit_endpoint_malformed_limit_never_500(client, scratch_db):
    """Reviewer catch: request.args type=int returns None on malformed input
    — the route must clamp instead of raising int(None) → 500."""
    record_rec_decision("default",
                        {"id": "ap-x", "device_id": "d", "issue_type": "temp_high",
                         "action": {"type": "pause"}},
                        "accept")
    resp = client.get("/api/auto-pilot/recommendations/audit?limit=abc")
    assert resp.status_code == 200
    assert resp.get_json()["count"] == 1
