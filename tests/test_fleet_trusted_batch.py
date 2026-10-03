"""Issue #735: fleet aggregate endpoints reuse the trusted registry batch.

These tests exercise the Flask routes against a real, isolated SQLite database.
They assert SQL statement cardinality and data contracts, not latency or SLOs.
"""

import sqlite3
import time
from unittest.mock import patch

import pytest

from app import app
from axe_fleet.registry import DeviceRegistry
from services.auth import create_token


@pytest.fixture
def fleet_context(tmp_path, monkeypatch):
    db_path = str(tmp_path / "fleet-735.sqlite")

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    registry = DeviceRegistry(get_db)
    registry.ensure_tables()
    monkeypatch.setattr(app, "testing", True)
    app.config["TESTING"] = True
    previous_secret = app.config.get("JWT_SECRET_KEY")
    app.config["JWT_SECRET_KEY"] = "issue735-test-secret-0123456789abcdef"
    monkeypatch.setenv("SECRET_KEY", "issue735-test-secret-0123456789abcdef")
    monkeypatch.setenv("TENANT_API_KEYS", "auth-enabled-for-rbac-test")
    monkeypatch.setattr(
        "axe_fleet.routes._probe_miner_latency_ms",
        lambda *_: pytest.fail("unexpected TCP probe"),
    )
    with patch("axe_fleet.routes._registry", registry):
        yield registry, app.test_client()
    if previous_secret is None:
        app.config.pop("JWT_SECRET_KEY", None)
    else:
        app.config["JWT_SECRET_KEY"] = previous_secret


def _token(tenant="measure", role="admin"):
    return create_token(subject=tenant, extra_claims={"role": role})


def _headers(tenant="measure", role="admin"):
    return {"Authorization": f"Bearer {_token(tenant, role)}"}


@pytest.mark.parametrize("endpoint", ["summary", "health"])
def test_fleet_routes_never_fallback_to_per_device_telemetry(fleet_context, endpoint):
    registry, client = fleet_context
    devices = [
        registry.upsert_agent_device(
            f"192.0.2.{index}", tenant_id="measure", info={"type": "bitaxe"}
        )
        for index in (10, 11)
    ]
    with patch.object(
        registry,
        "get_recent_telemetry",
        side_effect=AssertionError("per-device telemetry fallback called"),
    ):
        response = client.get(f"/api/axe-fleet/{endpoint}", headers=_headers())
    assert response.status_code == 200
    assert len(devices) == 2


def _insert_raw_telemetry(registry, device_id, tenant, ts, raw_payload):
    conn = registry._get_db()
    try:
        conn.execute(
            "INSERT INTO axe_telemetry (ts, device_id, payload, tenant_id) VALUES (?, ?, ?, ?)",
            (ts, device_id, raw_payload, tenant),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.parametrize("endpoint", ["summary", "health"])
def test_routes_reuse_latest_trusted_sample_across_heartbeats_and_invalid_rows(
    fleet_context, endpoint
):
    registry, client = fleet_context
    device = registry.upsert_agent_device(
        "192.0.2.90", tenant_id="measure", info={"type": "bitaxe"}
    )
    now = int(time.time())
    sample_ts = now - 180
    registry.update_device(
        device["id"], {"status": "HASHING", "last_seen": now}, tenant_id="measure"
    )
    first = {
        "device_id": device["id"],
        "ts": sample_ts,
        "hashrate_hs": 9_100_000_000,
        "shares_accepted": 4,
        "temperature": 61,
    }
    later_tie = {
        **first,
        "hashrate_hs": 9_200_000_000,
        "shares_accepted": 7,
        "temperature": 63,
    }
    registry.save_telemetry(device["id"], first, tenant_id="measure")
    registry.save_telemetry(device["id"], later_tie, tenant_id="measure")
    for offset in range(1, 53):
        _insert_raw_telemetry(
            registry, device["id"], "measure", sample_ts + offset, "{}"
        )
    invalid = ["{", "[]", '{"temperature":61}', '{"hashrate_hs":null}']
    for index, raw in enumerate(invalid, start=53):
        _insert_raw_telemetry(registry, device["id"], "measure", sample_ts + index, raw)
    delayed_older = {**first, "ts": sample_ts - 1, "hashrate_hs": 8_800_000_000}
    registry.save_telemetry(device["id"], delayed_older, tenant_id="measure")

    response = client.get(f"/api/axe-fleet/{endpoint}", headers=_headers())
    assert response.status_code == 200
    body = response.get_json()
    if endpoint == "summary":
        result = body["devices"][0]["_telemetry"]
    else:
        result = body["device_health"][0]["telemetry"]
    assert result["hashrate_hs"] == later_tie["hashrate_hs"]
    assert result["shares_accepted"] == later_tie["shares_accepted"]
    assert result["temperature"] == later_tie["temperature"]
    assert result["ts"] == sample_ts


def test_summary_and_health_keep_zero_stale_absent_tenant_and_quarantine_contracts(
    fleet_context,
):
    registry, client = fleet_context
    now = int(time.time())
    zero = registry.upsert_agent_device(
        "192.0.2.101", tenant_id="measure", info={"type": "bitaxe"}
    )
    stale = registry.upsert_agent_device(
        "192.0.2.102", tenant_id="measure", info={"type": "bitaxe"}
    )
    absent = registry.upsert_agent_device(
        "192.0.2.103", tenant_id="measure", info={"type": "bitaxe"}
    )
    other_tenant = registry.upsert_agent_device(
        "192.0.2.101", tenant_id="other", info={"type": "bitaxe"}
    )
    registry.update_device(
        other_tenant["id"], {"status": "HASHING", "last_seen": now}, tenant_id="other"
    )
    registry.update_device(
        zero["id"], {"status": "IDLE", "last_seen": now}, tenant_id="measure"
    )
    registry.update_device(
        stale["id"], {"status": "HASHING", "last_seen": now}, tenant_id="measure"
    )
    registry.save_telemetry(
        zero["id"],
        {"ts": now, "hashrate_hs": 0, "shares_accepted": 0},
        tenant_id="measure",
    )
    stale_ts = now - 901
    registry.save_telemetry(
        stale["id"],
        {"ts": stale_ts, "hashrate_hs": 77_000_000, "hashrate_1h": 77_000_000},
        tenant_id="measure",
    )
    registry.save_telemetry(
        other_tenant["id"],
        {"ts": now, "hashrate_hs": 999_000_000},
        tenant_id="other",
    )
    registry.record_telemetry_quarantine(
        stale["id"], ["temperature"], ["out_of_range"], tenant_id="measure"
    )

    aggregate_results = {}
    for endpoint in ("summary", "health"):
        response = client.get(f"/api/axe-fleet/{endpoint}", headers=_headers())
        assert response.status_code == 200
        body = response.get_json()
        rows = body["devices"] if endpoint == "summary" else body["device_health"]
        rows_by_id = {row["id"]: row for row in rows}
        assert set(rows_by_id) == {zero["id"], stale["id"], absent["id"]}
        zero_tel = (
            rows_by_id[zero["id"]]["_telemetry"]
            if endpoint == "summary"
            else rows_by_id[zero["id"]]["telemetry"]
        )
        assert zero_tel["hashrate_hs"] == 0
        assert zero_tel["ts"] == now
        absent_tel = (
            rows_by_id[absent["id"]]["_telemetry"]
            if endpoint == "summary"
            else rows_by_id[absent["id"]]["telemetry"]
        )
        assert absent_tel["hashrate_hs"] is None
        assert absent_tel["ts"] is None
        stale_row = rows_by_id[stale["id"]]
        stale_tel = (
            stale_row["_telemetry"] if endpoint == "summary" else stale_row["telemetry"]
        )
        assert stale_row["status"] == "STALE"
        assert stale_tel["ts"] == stale_ts
        assert stale_tel["last_known_hashrate_hs"] == 77_000_000
        assert stale_row["telemetry_quarantine"]["fields"] == ["temperature"]
        assert isinstance(stale_row["capabilities"], list)
        aggregate_results[endpoint] = rows_by_id

        other_response = client.get(
            f"/api/axe-fleet/{endpoint}", headers=_headers(tenant="other")
        )
        assert other_response.status_code == 200
        other_body = other_response.get_json()
        other_rows = (
            other_body["devices"]
            if endpoint == "summary"
            else other_body["device_health"]
        )
        assert [row["id"] for row in other_rows] == [other_tenant["id"]]
        other_row = other_rows[0]
        other_tel = (
            other_row["_telemetry"] if endpoint == "summary" else other_row["telemetry"]
        )
        assert other_tel["hashrate_hs"] == 999_000_000
        assert other_row["telemetry_quarantine"] is None

    for device_id in (zero["id"], stale["id"], absent["id"]):
        summary_tel = aggregate_results["summary"][device_id]["_telemetry"]
        health_tel = aggregate_results["health"][device_id]["telemetry"]
        for key in ("hashrate_hs", "ts", "shares_accepted"):
            assert summary_tel[key] == health_tel[key]
        if summary_tel["age_seconds"] is not None:
            assert abs(summary_tel["age_seconds"] - health_tel["age_seconds"]) <= 1


def test_fleet_aggregate_routes_keep_viewer_role_gate(fleet_context):
    _, client = fleet_context
    for endpoint in ("summary", "health"):
        response = client.get(
            f"/api/axe-fleet/{endpoint}",
            headers=_headers(role="anonymous"),
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )
        assert response.status_code == 403
